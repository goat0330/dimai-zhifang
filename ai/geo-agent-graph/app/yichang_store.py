"""Persistence for simulated Gold runs, separate from Java business records."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import settings


def _db_path() -> Path:
    path = Path(settings.yichang_gold_db_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path(), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS yichang_gold_records (
            record_id TEXT PRIMARY KEY,
            scenario_id TEXT NOT NULL,
            record_type TEXT NOT NULL,
            parent_id TEXT,
            status TEXT NOT NULL,
            is_simulated INTEGER NOT NULL CHECK (is_simulated = 1),
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_yichang_gold_scenario_type "
        "ON yichang_gold_records(scenario_id, record_type, created_at)"
    )
    return connection


def new_gold_id(record_type: str, scenario_id: str) -> str:
    kind = "".join(char for char in record_type.upper() if char.isalnum())[:12]
    scenario = "".join(char for char in scenario_id.upper() if char.isalnum() or char == "-")
    return f"DEMO-GOLD-{kind}-{scenario}-{uuid4().hex[:12]}"


def save_gold_record(
    record_type: str,
    scenario_id: str,
    payload: dict[str, Any],
    *,
    record_id: str | None = None,
    parent_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("is_simulated") is not True:
        raise ValueError("Gold persistence only accepts records explicitly marked is_simulated=true")
    record_id = record_id or new_gold_id(record_type, scenario_id)
    status = str(payload.get("status") or payload.get("event_status") or "recorded")
    now = datetime.now(timezone.utc).isoformat()
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # leanguard: local Gold-only SQLite; switch to Java persistence when a verified Gold-safe Java API exists.
    with _connect() as connection:
        connection.execute(
            """INSERT INTO yichang_gold_records
               (record_id, scenario_id, record_type, parent_id, status, is_simulated, payload_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (record_id, scenario_id, record_type, parent_id, status, encoded, now, now),
        )
        row = connection.execute(
            "SELECT record_id, scenario_id, record_type, parent_id, status, is_simulated, payload_json, created_at, updated_at "
            "FROM yichang_gold_records WHERE record_id = ?",
            (record_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError("Gold record was not readable after insert")
    return _row_to_record(row)


def update_gold_record(record_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("is_simulated") is not True:
        raise ValueError("Gold persistence only accepts records explicitly marked is_simulated=true")
    now = datetime.now(timezone.utc).isoformat()
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    status = str(payload.get("status") or payload.get("event_status") or "recorded")
    with _connect() as connection:
        connection.execute(
            "UPDATE yichang_gold_records SET status = ?, payload_json = ?, updated_at = ? WHERE record_id = ?",
            (status, encoded, now, record_id),
        )
        row = connection.execute(
            "SELECT record_id, scenario_id, record_type, parent_id, status, is_simulated, payload_json, created_at, updated_at "
            "FROM yichang_gold_records WHERE record_id = ?",
            (record_id,),
        ).fetchone()
    return _row_to_record(row) if row else None


def get_gold_record(record_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT record_id, scenario_id, record_type, parent_id, status, is_simulated, payload_json, created_at, updated_at "
            "FROM yichang_gold_records WHERE record_id = ?",
            (record_id,),
        ).fetchone()
    return _row_to_record(row) if row else None


def list_gold_records(scenario_id: str, record_type: str | None = None) -> list[dict[str, Any]]:
    with _connect() as connection:
        if record_type:
            rows = connection.execute(
                "SELECT record_id, scenario_id, record_type, parent_id, status, is_simulated, payload_json, created_at, updated_at "
                "FROM yichang_gold_records WHERE scenario_id = ? AND record_type = ? ORDER BY created_at, rowid",
                (scenario_id, record_type),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT record_id, scenario_id, record_type, parent_id, status, is_simulated, payload_json, created_at, updated_at "
                "FROM yichang_gold_records WHERE scenario_id = ? ORDER BY created_at, rowid",
                (scenario_id,),
            ).fetchall()
    return [_row_to_record(row) for row in rows]


def list_gold_children(parent_id: str, record_type: str | None = None) -> list[dict[str, Any]]:
    with _connect() as connection:
        if record_type:
            rows = connection.execute(
                "SELECT record_id, scenario_id, record_type, parent_id, status, is_simulated, payload_json, created_at, updated_at "
                "FROM yichang_gold_records WHERE parent_id = ? AND record_type = ? ORDER BY created_at, rowid",
                (parent_id, record_type),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT record_id, scenario_id, record_type, parent_id, status, is_simulated, payload_json, created_at, updated_at "
                "FROM yichang_gold_records WHERE parent_id = ? ORDER BY created_at, rowid",
                (parent_id,),
            ).fetchall()
    return [_row_to_record(row) for row in rows]


def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "record_id": row["record_id"],
        "scenario_id": row["scenario_id"],
        "record_type": row["record_type"],
        "parent_id": row["parent_id"],
        "status": row["status"],
        "is_simulated": bool(row["is_simulated"]),
        "payload": json.loads(row["payload_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
