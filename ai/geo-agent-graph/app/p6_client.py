"""Read-only client for the Yichang P6 candidate-screening query API."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

from .config import settings


async def lookup_slope_unit(slope_unit_id: Any) -> dict[str, Any]:
    slope_unit_id = str(slope_unit_id or "").strip()
    if not slope_unit_id:
        return {"status": "skipped", "reason": "missing_slope_unit_id", "execution_engine": "p6_query_api"}
    if slope_unit_id.casefold().startswith(("gold-", "demo-gold-")):
        return {"status": "skipped", "reason": "gold_test_object", "execution_engine": "p6_query_api"}
    if not re.fullmatch(r"YCSV2_[0-9]{6}", slope_unit_id):
        return {
            "status": "skipped",
            "reason": "not_a_p6_slope_unit_id",
            "execution_engine": "p6_query_api",
            "slope_unit_id": slope_unit_id,
        }
    if not settings.p6_api_base_url:
        return {"status": "not_configured", "execution_engine": "p6_query_api", "slope_unit_id": slope_unit_id}

    base = settings.p6_api_base_url.rstrip("/")
    encoded_id = quote(slope_unit_id, safe="")
    result: dict[str, Any] = {
        "status": "error",
        "execution_engine": "p6_query_api",
        "slope_unit_id": slope_unit_id,
        "unit_snapshot": None,
        "info_snapshot": None,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.p6_timeout_seconds) as client:
            unit_response = await client.get(f"{base}/api/v1/units/{encoded_id}")
            if unit_response.status_code == 404:
                return {**result, "status": "not_found", "unit_status": 404}
            unit_response.raise_for_status()
            unit = unit_response.json()
            if not isinstance(unit, dict):
                return {**result, "status": "invalid_response", "unit_status": "not_object"}
            result.update(unit_snapshot=unit, unit_status="completed")

            try:
                info_response = await client.get(
                    f"{base}/api/v1/info", params={"slope_unit_id": slope_unit_id}
                )
                if info_response.status_code == 404:
                    return {**result, "status": "partial", "info_status": 404}
                info_response.raise_for_status()
                info = info_response.json()
            except (httpx.HTTPError, ValueError) as exc:
                return {
                    **result,
                    "status": "partial",
                    "info_status": "error",
                    "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                }
            if not isinstance(info, dict):
                return {**result, "status": "partial", "info_status": "not_object"}
    except (httpx.HTTPError, ValueError) as exc:
        return {**result, "error": f"{type(exc).__name__}: {str(exc)[:240]}"}

    return {
        **result,
        "status": "completed",
        "unit_status": "completed",
        "info_status": "completed",
        "unit_snapshot": unit,
        "info_snapshot": info,
    }


async def lookup_dynamic_slope_unit(
    slope_unit_id: Any,
    *,
    scenario: str = "dynamic",
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    slope_unit_id = str(slope_unit_id or "").strip()
    if not slope_unit_id:
        return {"status": "missing_mapping", "reason": "missing_p6_slope_unit_id"}
    if slope_unit_id.casefold().startswith(("gold-", "demo-gold-")):
        return {"status": "skipped", "reason": "gold_test_object"}
    if not re.fullmatch(r"YCSV2_[0-9]{6}", slope_unit_id):
        return {"status": "skipped", "reason": "not_a_p6_slope_unit_id", "slope_unit_id": slope_unit_id}
    if scenario not in {"dynamic", "forecast", "dynamic_08"}:
        return {"status": "skipped", "reason": "unsupported_scenario", "scenario": scenario}
    if not settings.p6_api_base_url:
        return {"status": "not_configured", "slope_unit_id": slope_unit_id, "scenario": scenario}

    base = settings.p6_api_base_url.rstrip("/")
    encoded_id = quote(slope_unit_id, safe="")
    requested_snapshot_id = str(snapshot_id or "").strip() or None
    selected_snapshot_id = requested_snapshot_id
    status_payload: dict[str, Any] | None = None
    latest_snapshot: dict[str, Any] | None = None
    status_snapshot_id = None
    stage = "unit" if selected_snapshot_id else "status"
    try:
        async with httpx.AsyncClient(timeout=settings.p6_timeout_seconds) as client:
            if selected_snapshot_id is None:
                status_response = await client.get(f"{base}/api/v1/dynamic/status")
                if status_response.status_code >= 400:
                    return {
                        "status": "unavailable", "stage": stage,
                        "http_status": status_response.status_code,
                        "slope_unit_id": slope_unit_id, "scenario": scenario,
                    }
                status_payload = status_response.json()
                if not isinstance(status_payload, dict):
                    return {"status": "invalid_response", "stage": stage, "reason": "status_not_object"}
                status_snapshot_id = status_payload.get("latest_snapshot_id")
                if status_payload.get("status") != "ok" or not status_snapshot_id:
                    return {
                        "status": "unavailable", "stage": stage,
                        "reason": "latest_snapshot_missing", "service_status": status_payload,
                        "slope_unit_id": slope_unit_id, "scenario": scenario,
                    }

                stage = "latest"
                latest_response = await client.get(
                    f"{base}/api/v1/dynamic/latest", params={"scenario": scenario},
                )
                if latest_response.status_code >= 400:
                    return {
                        "status": "unavailable", "stage": stage,
                        "http_status": latest_response.status_code,
                        "service_status": status_payload,
                        "slope_unit_id": slope_unit_id, "scenario": scenario,
                    }
                latest_payload = latest_response.json()
                if not isinstance(latest_payload, dict) or not isinstance(latest_payload.get("snapshot"), dict):
                    return {"status": "invalid_response", "stage": stage, "reason": "latest_snapshot_not_object"}
                latest_snapshot = latest_payload["snapshot"]
                selected_snapshot_id = latest_snapshot.get("snapshot_id") or status_snapshot_id

            stage = "unit"
            unit_response = await client.get(
                f"{base}/api/v1/dynamic/units/{encoded_id}",
                params={"scenario": scenario, "snapshot_id": selected_snapshot_id},
            )
            if unit_response.status_code == 404:
                return {
                    "status": "mapping_missing", "stage": stage,
                    "reason": "slope_unit_not_in_snapshot",
                    "http_status": 404, "slope_unit_id": slope_unit_id,
                    "scenario": scenario, "snapshot_id": selected_snapshot_id,
                    "service_status": status_payload, "latest_snapshot": latest_snapshot,
                }
            if unit_response.status_code >= 400:
                return {
                    "status": "unavailable", "stage": stage,
                    "http_status": unit_response.status_code,
                    "slope_unit_id": slope_unit_id, "scenario": scenario,
                    "snapshot_id": selected_snapshot_id,
                }
            unit_payload = unit_response.json()
            if not isinstance(unit_payload, dict) or not isinstance(unit_payload.get("item"), dict):
                return {"status": "invalid_response", "stage": stage, "reason": "unit_item_not_object"}
            unit_snapshot = unit_payload.get("snapshot")
            if not isinstance(unit_snapshot, dict):
                return {"status": "invalid_response", "stage": stage, "reason": "unit_snapshot_not_object"}
            item = unit_payload["item"]
            returned_id = item.get("slope_unit_id") or item.get("slopeUnitId")
            if returned_id in (None, ""):
                return {
                    "status": "invalid_response", "stage": stage,
                    "reason": "slope_unit_id_missing", "slope_unit_id": slope_unit_id,
                    "snapshot_id": selected_snapshot_id,
                }
            if str(returned_id).strip().casefold() != slope_unit_id.casefold():
                return {
                    "status": "invalid_response", "stage": stage,
                    "reason": "slope_unit_id_mismatch", "slope_unit_id": slope_unit_id,
                    "returned_slope_unit_id": returned_id, "snapshot_id": selected_snapshot_id,
                }
            returned_scenario = unit_payload.get("scenario")
            if returned_scenario not in (None, scenario):
                return {
                    "status": "invalid_response", "stage": stage,
                    "reason": "scenario_mismatch", "scenario": scenario,
                    "returned_scenario": returned_scenario, "snapshot_id": selected_snapshot_id,
                }
            returned_snapshot_id = unit_snapshot.get("snapshot_id")
            if returned_snapshot_id not in (None, selected_snapshot_id):
                return {
                    "status": "invalid_response", "stage": stage,
                    "reason": "snapshot_id_mismatch", "snapshot_id": selected_snapshot_id,
                    "returned_snapshot_id": returned_snapshot_id,
                }
    except httpx.HTTPError as exc:
        return {
            "status": "unavailable", "stage": stage,
            "reason": type(exc).__name__, "slope_unit_id": slope_unit_id,
            "scenario": scenario,
        }
    except ValueError:
        return {"status": "invalid_response", "stage": stage, "reason": "invalid_json"}

    provenance_snapshot = unit_snapshot if requested_snapshot_id else (latest_snapshot or unit_snapshot)
    model = provenance_snapshot.get("model") or unit_snapshot.get("model") or item.get("model")
    rule_version = provenance_snapshot.get("rule_version") or unit_snapshot.get("rule_version")
    data_time = provenance_snapshot.get("as_of_local") or unit_snapshot.get("as_of_local")
    provider = (
        provenance_snapshot.get("provider") or provenance_snapshot.get("rain_source")
        or item.get("provider") or item.get("rain_source")
    )
    valid_time = (
        provenance_snapshot.get("valid_time") or unit_snapshot.get("valid_time")
        or item.get("valid_time")
    )
    rain_source_types = [
        value for value in (item.get("rain_past_type"), item.get("rain_forecast_type"))
        if value not in (None, "")
    ]
    model_rainfall = any(str(value).startswith("MODEL_") for value in rain_source_types)
    candidate_provenance = {
        "source_kind": "model_rainfall_candidate" if model_rainfall else "p6_dynamic_screening_candidate",
        "source": (
            f"P6 {model} model-rainfall screening candidate" if model_rainfall and model
            else "P6 model-rainfall screening candidate" if model_rainfall
            else "P6 dynamic H/R screening candidate"
        ),
        "provider": provider,
        "provider_status": "provided" if provider not in (None, "") else "missing",
        "model": model,
        "snapshot_id": selected_snapshot_id,
        "rule_version": rule_version,
        "data_time": data_time,
        "data_time_semantics": "snapshot_as_of_local",
        "data_time_status": "provided" if data_time not in (None, "") else "missing",
        "valid_time": valid_time,
        "valid_time_status": "provided" if valid_time not in (None, "") else "missing",
        "rain_source_types": rain_source_types,
        "is_station_observation": False,
        "official_warning_allowed": False,
    }
    return {
        "status": "completed",
        "slope_unit_id": slope_unit_id,
        "scenario": scenario,
        "status_snapshot_id": status_snapshot_id,
        "snapshot_id": selected_snapshot_id,
        "service_status": status_payload,
        "latest_snapshot": latest_snapshot,
        "selected_snapshot": unit_snapshot,
        "unit_snapshot": unit_snapshot,
        "item": item,
        "candidate_provenance": candidate_provenance,
        "snapshot_query_mode": "explicit" if requested_snapshot_id else "latest",
    }
