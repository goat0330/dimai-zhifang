"""Read-only queries for versioned ECMWF-driven H/R time slices."""
from __future__ import annotations

import json
import os
import sqlite3
import zlib
from contextlib import closing
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from fastapi.responses import Response

HERE = Path(__file__).resolve().parent
PROFILE_PATH = Path(os.environ.get("P6_RUNTIME_PROFILE", HERE.parent / "P6_runtime_profile.json"))
if not PROFILE_PATH.is_file():
    raise RuntimeError(f"Active P6 runtime profile is required: {PROFILE_PATH}")
PROFILE = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
OUTPUT_DIR = Path(PROFILE.get("dynamic_runtime_dir", HERE / "runtime"))
DB = Path(os.getenv("P6_DYNAMIC_DB", str(PROFILE.get("database_path", OUTPUT_DIR / "p6_dynamic.sqlite3"))))
MAP_TILES = OUTPUT_DIR / "map_tiles" / "P6_动态风险图层_最新.mbtiles"
router = APIRouter(prefix="/api/v1/dynamic", tags=["宜昌动态风险"])
SCENARIOS = {
    "dynamic": ("r_dynamic_grade", "h_dynamic_grade"),
    "forecast": ("r_forecast_grade", "h_forecast_grade"),
    "dynamic_08": ("r_dynamic_08_grade", "h_dynamic_08_grade"),
}
HGrade = Literal["H1", "H2", "H3", "H4", "H5"]
RGrade = Literal["R1", "R2", "R3", "R4", "R5"]
Scenario = Literal["dynamic", "forecast", "dynamic_08"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DynamicSnapshot(ContractModel):
    snapshot_id: str
    provider: str
    model: str
    rule_version: str
    fetched_at: str
    as_of_local: str
    timezone: str
    data_window_start_local: str
    data_window_end_local: str
    historical_type: str
    forecast_type: str | None
    forecast_available: bool
    unit_count: int
    missing_count: int


class UpdateAttempt(ContractModel):
    started_at: str
    success: int


class StatusResponse(ContractModel):
    status: Literal["ok"]
    latest_snapshot_id: str
    as_of_local: str
    fetched_at: str
    unit_count: int
    model: str
    last_attempt: UpdateAttempt | None


class SnapshotPage(ContractModel):
    total: int
    items: list[DynamicSnapshot]


class LatestResponse(ContractModel):
    snapshot: DynamicSnapshot
    scenario: Scenario


class SnapshotReference(ContractModel):
    snapshot_id: str
    as_of_local: str
    model: str
    rule_version: str


class DynamicUnitItem(ContractModel):
    slope_unit_id: str
    slopeUnitId: str
    county: str
    unit_lat: float
    unit_lon: float
    rain_grid_id: str
    rain_grid_lat: float
    rain_grid_lon: float
    rain_mapping_distance_km: float
    rain_mapping_status: str
    rain_past_type: str
    rain_forecast_type: str | None
    rain_past_status: str
    rain_forecast_status: str
    rain_status: str
    rain_past24h_mm: float | None
    rain_past72h_mm: float | None
    rain_past168h_mm: float | None
    rain_forecast24h_mm: float | None
    rain_forecast72h_mm: float | None
    rain_past24h_08_mm: float | None
    rain_past72h_08_mm: float | None
    rain_past168h_08_mm: float | None
    h_dynamic_score: float | None
    h_dynamic_grade: HGrade | None
    h_forecast_score: float | None
    h_forecast_grade: HGrade | None
    h_dynamic_08_score: float | None
    h_dynamic_08_grade: HGrade | None
    r_dynamic_score: float | None
    r_dynamic_grade: RGrade | None
    r_forecast_score: float | None
    r_forecast_grade: RGrade | None
    r_dynamic_08_score: float | None
    r_dynamic_08_grade: RGrade | None


class DynamicUnitResponse(ContractModel):
    snapshot: SnapshotReference
    scenario: Scenario
    item: DynamicUnitItem


class DynamicUnitPage(ContractModel):
    snapshot_id: str
    scenario: Scenario
    total: int
    offset: int
    limit: int
    items: list[DynamicUnitItem]


class CountyRiskCounts(ContractModel):
    county: str
    total_units: int
    r1: int
    r2: int
    r3: int
    r4: int
    r5: int


class CountyResponse(ContractModel):
    snapshot_id: str
    scenario: Scenario
    items: list[CountyRiskCounts]


class PointGeometry(ContractModel):
    type: Literal["Point"]
    coordinates: tuple[float, float]


class MapProperties(ContractModel):
    slopeUnitId: str
    county: str
    hScore: float | None
    hGrade: HGrade | None
    rScore: float | None
    rGrade: RGrade | None


class MapFeature(ContractModel):
    type: Literal["Feature"]
    geometry: PointGeometry
    properties: MapProperties


class MapResponse(ContractModel):
    type: Literal["FeatureCollection"]
    snapshot_id: str
    scenario: Scenario
    total: int
    offset: int
    limit: int
    features: list[MapFeature]


def _db() -> sqlite3.Connection:
    if not DB.exists():
        raise HTTPException(503, "No successful P6 dynamic rainfall update yet")
    conn = sqlite3.connect(DB.as_uri() + "?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _latest(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT snapshot_id FROM latest_snapshot WHERE key='latest'").fetchone()
    if row is None:
        raise HTTPException(503, "No successful P6 dynamic rainfall update yet")
    return str(row[0])


def _snapshot(conn: sqlite3.Connection, snapshot_id: str) -> dict:
    row = conn.execute("SELECT metadata_json FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Snapshot not found")
    value = json.loads(row[0])
    public_fields = (
        "snapshot_id", "provider", "model", "rule_version", "fetched_at", "as_of_local",
        "timezone", "data_window_start_local", "data_window_end_local", "historical_type",
        "forecast_type", "forecast_available", "unit_count", "missing_count",
    )
    return {key: value[key] for key in public_fields if key in value}


def _validate_scenario(meta: dict, scenario: str) -> None:
    if scenario == "forecast" and not meta.get("forecast_available", False):
        raise HTTPException(409, "Forecast scenario is unavailable for this historical time slice")


def _external_id(item: dict) -> dict:
    item["slopeUnitId"] = item["slope_unit_id"]
    return item


def _read_payload(value) -> dict:
    if isinstance(value, bytes):
        if value.startswith(b"\x78"):
            value = zlib.decompress(value)
        value = value.decode("utf-8")
    return json.loads(value)


@router.get("/status", response_model=StatusResponse)
def status():
    try:
        with closing(_db()) as conn:
            latest_id = _latest(conn)
            meta = _snapshot(conn, latest_id)
            return {"status": "ok", "latest_snapshot_id": latest_id, "as_of_local": meta["as_of_local"],
                    "fetched_at": meta["fetched_at"], "unit_count": meta["unit_count"],
                    "model": meta["model"], "last_attempt": None}
    except HTTPException:
        raise


@router.get("/snapshots", response_model=SnapshotPage)
def snapshots(limit: int = Query(20, ge=1, le=200), offset: int = Query(0, ge=0)):
    with closing(_db()) as conn:
        rows = conn.execute("SELECT snapshot_id FROM snapshots ORDER BY as_of_local DESC,fetched_at DESC LIMIT ? OFFSET ?",
                            (limit, offset)).fetchall()
        return {"total": conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
                "items": [_snapshot(conn, r[0]) for r in rows]}


@router.get("/latest", response_model=LatestResponse)
def latest(scenario: Literal["dynamic", "forecast", "dynamic_08"] = "dynamic"):
    with closing(_db()) as conn:
        snapshot_id = _latest(conn)
        meta = _snapshot(conn, snapshot_id)
        _validate_scenario(meta, scenario)
        return {"snapshot": meta, "scenario": scenario}


@router.get("/units/{slope_unit_id}", response_model=DynamicUnitResponse)
def unit(slope_unit_id: str, scenario: Literal["dynamic", "forecast", "dynamic_08"] = "dynamic",
         snapshot_id: str | None = None):
    with closing(_db()) as conn:
        snapshot_id = snapshot_id or _latest(conn)
        meta = _snapshot(conn, snapshot_id)
        _validate_scenario(meta, scenario)
        row = conn.execute("SELECT payload_json FROM units WHERE snapshot_id=? AND slope_unit_id=?",
                           (snapshot_id, slope_unit_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Slope unit not found in this snapshot")
        return {"snapshot": {"snapshot_id": snapshot_id, "as_of_local": meta["as_of_local"],
                              "model": meta["model"], "rule_version": meta["rule_version"]},
                "scenario": scenario, "item": _external_id(_read_payload(row[0]))}


@router.get("/units", response_model=DynamicUnitPage)
def units(county: str | None = None, scenario: Literal["dynamic", "forecast", "dynamic_08"] = "dynamic",
          r_grade: str | None = Query(None, pattern=r"^R[1-5]$"),
          limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), snapshot_id: str | None = None):
    grade_col = SCENARIOS[scenario][0]
    with closing(_db()) as conn:
        snapshot_id = snapshot_id or _latest(conn)
        _validate_scenario(_snapshot(conn, snapshot_id), scenario)
        clauses, args = ["snapshot_id=?"], [snapshot_id]
        if county is not None:
            clauses.append("county=?"); args.append(county)
        if r_grade is not None:
            clauses.append(f"{grade_col}=?"); args.append(r_grade)
        where = " AND ".join(clauses)
        total = conn.execute(f"SELECT COUNT(*) FROM units WHERE {where}", args).fetchone()[0]
        rows = conn.execute(f"SELECT payload_json FROM units WHERE {where} ORDER BY slope_unit_id LIMIT ? OFFSET ?",
                            [*args, limit, offset]).fetchall()
        return {"snapshot_id": snapshot_id, "scenario": scenario, "total": total, "offset": offset,
                "limit": limit, "items": [_external_id(_read_payload(r[0])) for r in rows]}


@router.get("/counties", response_model=CountyResponse)
def counties(scenario: Literal["dynamic", "forecast", "dynamic_08"] = "dynamic", snapshot_id: str | None = None):
    with closing(_db()) as conn:
        snapshot_id = snapshot_id or _latest(conn)
        _validate_scenario(_snapshot(conn, snapshot_id), scenario)
        rows = conn.execute("SELECT county,total_units,r1,r2,r3,r4,r5 FROM county_summary "
                            "WHERE snapshot_id=? AND scenario=? ORDER BY county", (snapshot_id, scenario)).fetchall()
        return {"snapshot_id": snapshot_id, "scenario": scenario, "items": [dict(r) for r in rows]}


@router.get("/map", response_model=MapResponse)
def map_layer(scenario: Literal["dynamic", "forecast", "dynamic_08"] = "dynamic",
              county: str | None = None, r_grade: str | None = Query(None, pattern=r"^R[1-5]$"),
              limit: int = Query(2000, ge=1, le=10000), offset: int = Query(0, ge=0),
              snapshot_id: str | None = None):
    grade_col, h_col = SCENARIOS[scenario]
    with closing(_db()) as conn:
        snapshot_id = snapshot_id or _latest(conn)
        _validate_scenario(_snapshot(conn, snapshot_id), scenario)
        clauses, args = ["snapshot_id=?"], [snapshot_id]
        if county is not None:
            clauses.append("county=?"); args.append(county)
        if r_grade is not None:
            clauses.append(f"{grade_col}=?"); args.append(r_grade)
        where = " AND ".join(clauses)
        total = conn.execute(f"SELECT COUNT(*) FROM units WHERE {where}", args).fetchone()[0]
        rows = conn.execute(f"SELECT payload_json FROM units WHERE {where} ORDER BY slope_unit_id LIMIT ? OFFSET ?",
                            [*args, limit, offset]).fetchall()
        features = []
        for row in rows:
            item = _read_payload(row[0])
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates":
                               [item["unit_lon"], item["unit_lat"]]},
                "properties": {"slopeUnitId": item["slope_unit_id"], "county": item["county"],
                               "hScore": item[h_col.replace("grade", "score")], "hGrade": item[h_col],
                               "rScore": item[grade_col.replace("grade", "score")], "rGrade": item[grade_col]}})
        return {"type": "FeatureCollection", "snapshot_id": snapshot_id, "scenario": scenario,
                "total": total, "offset": offset, "limit": limit, "features": features}


@router.get("/tiles/{z}/{x}/{y}.pbf", response_class=Response)
def map_tile(z: int, x: int, y: int, scenario: Literal["dynamic", "forecast"] = "dynamic",
             snapshot_id: str | None = None):
    if z < 7 or z > 15 or x < 0 or y < 0 or x >= 2 ** z or y >= 2 ** z:
        return Response(status_code=204)
    with closing(_db()) as conn:
        latest_id = _latest(conn)
        if snapshot_id and snapshot_id != latest_id:
            raise HTTPException(409, "Map tiles are available for the latest P6 time slice only")
        _validate_scenario(_snapshot(conn, latest_id), scenario)
    if not MAP_TILES.exists():
        raise HTTPException(503, "P6 slope-unit map tiles are not ready")
    tile_row = 2 ** z - 1 - y
    with closing(sqlite3.connect(MAP_TILES.as_uri() + "?mode=ro&immutable=1", uri=True)) as conn:
        row = conn.execute("SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                           (z, x, tile_row)).fetchone()
    if row is None:
        return Response(status_code=204, headers={"Cache-Control": "public, max-age=3600"})
    tile = row[0]
    headers = {"Cache-Control": "public, max-age=31536000, immutable"}
    if tile.startswith(b"\x1f\x8b"):
        headers["Content-Encoding"] = "gzip"
    return Response(content=tile, media_type="application/vnd.mapbox-vector-tile", headers=headers)
