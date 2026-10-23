"""Yichang monitoring adapters with explicit provenance and no official thresholds."""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_METRIC_ALIASES = {
    "continuous_rainfall_mm": (
        "continuous_rainfall_mm", "continuous_rainfall", "rainfall_continuous_mm",
        "连续降雨", "连续降雨量",
    ),
    "rainfall_24h_mm": (
        "rainfall_24h_mm", "rainfall_24h", "rainfall_24_hour_mm", "rainfall_1d_mm", "24h_rainfall_mm",
    ),
    "rainfall_3d_mm": (
        "rainfall_3d_mm", "rainfall_72h_mm", "rainfall_3_day_mm", "rainfall_3days_mm",
    ),
    "rainfall_7d_mm": (
        "rainfall_7d_mm", "rainfall_168h_mm", "rainfall_7_day_mm", "rainfall_7days_mm",
    ),
    "short_term_rainfall_mm": (
        "short_term_rainfall_mm", "short_rainfall_mm", "short_term_rainfall", "rainfall_1h_mm",
        "rainfall_1_hour_mm", "短时降雨", "短时降雨量", "1小时雨量",
    ),
    "displacement_mm": (
        "displacement_mm", "ground_displacement_mm", "displacement", "位移", "累计位移",
    ),
    "displacement_rate_mm_per_day": (
        "displacement_rate_mm_per_day", "displacement_rate_mm_day", "位移速率mm/d", "位移速率毫米/天",
    ),
    "displacement_rate_mm_per_hour": (
        "displacement_rate_mm_per_hour", "displacement_rate_mm_h", "displacement_rate",
        "rate_mm_h", "位移速率", "位移速率mm/h",
    ),
    "reservoir_level_m": (
        "reservoir_level_m", "reservoir_level", "water_level_m", "water_level", "库水位",
    ),
    "reservoir_trend": (
        "reservoir_trend", "reservoir_level_trend", "water_level_trend", "库水位趋势",
    ),
    "recovery_status": (
        "recovery_status", "recovery_state", "recovery", "恢复状态", "恢复情况",
    ),
}
_ALIAS_TO_METRIC = {
    alias.casefold().replace(" ", "_"): metric
    for metric, aliases in _METRIC_ALIASES.items()
    for alias in (metric, *aliases)
}
_NESTED_FIELDS = {
    "continuous_rainfall_mm": ("rainfall", ("continuous", "continuous_mm", "continuous_rainfall_mm", "cumulative")),
    "short_term_rainfall_mm": ("rainfall", ("short_term", "short_term_mm", "short_term_rainfall_mm", "one_hour", "1h")),
    "rainfall_24h_mm": ("rainfall", ("24h", "24h_mm", "24_hour", "24_hour_mm", "rainfall_24h_mm")),
    "rainfall_3d_mm": ("rainfall", ("3d", "3d_mm", "72h", "72h_mm", "rainfall_3d_mm")),
    "rainfall_7d_mm": ("rainfall", ("7d", "7d_mm", "168h", "168h_mm", "rainfall_7d_mm")),
    "displacement_mm": ("displacement", ("value", "value_mm", "displacement_mm", "amount")),
    "displacement_rate_mm_per_hour": ("displacement", ("rate", "rate_mm_h", "rate_mm_per_hour", "displacement_rate_mm_per_hour")),
    "reservoir_level_m": ("reservoir", ("level", "level_m", "reservoir_level_m", "water_level_m")),
    "reservoir_trend": ("reservoir", ("trend", "level_trend", "reservoir_trend")),
    "recovery_status": ("recovery", ("status", "state", "recovery_status")),
}
_TIMESTAMP_KEYS = ("observed_at", "sampled_at", "timestamp", "time", "采样时间", "观测时间")
_EVENT_KEYS = (
    "event_id", "scenario_id", "stage_id", "lineage_key", "parent_scenario_id", "correlation_id",
    "admin_area", "slope_unit_id", "hazard_point_id", "monitor_point_id",
    "monitor_device_id", "monitor_to_hazard_link_status", "monitor_to_hazard_link_source",
    "spatial_object_source", "parent_correlation_id", "location", "event_type", "occurred_at",
)
_EVENT_FIELD_ALIASES = {
    "event_id": ("event_id", "eventId"),
    "scenario_id": ("scenario_id", "scenarioId"),
    "stage_id": ("stage_id", "stageId"),
    "lineage_key": ("lineage_key", "lineageKey"),
    "parent_scenario_id": ("parent_scenario_id", "parentScenarioId"),
    "correlation_id": ("correlation_id", "correlationId"),
    "admin_area": ("admin_area", "adminArea"),
    "slope_unit_id": ("slope_unit_id", "slopeUnitId"),
    "hazard_point_id": ("hazard_point_id", "hazardPointId"),
    "monitor_point_id": ("monitor_point_id", "monitorPointId"),
    "monitor_device_id": ("monitor_device_id", "monitorDeviceId"),
    "parent_correlation_id": ("parent_correlation_id", "parentCorrelationId"),
    "event_type": ("event_type", "eventType"),
    "occurred_at": ("occurred_at", "occurredAt"),
}
_EXPECTED_UNITS = {
    "continuous_rainfall_mm": "mm",
    "rainfall_24h_mm": "mm",
    "rainfall_3d_mm": "mm",
    "rainfall_7d_mm": "mm",
    "short_term_rainfall_mm": "mm",
    "displacement_mm": "mm",
    "displacement_rate_mm_per_day": "mm/d",
    "displacement_rate_mm_per_hour": "mm/h",
    "reservoir_level_m": "m",
}
_RAIN_WINDOW_HOURS = {"rainfall_24h_mm": 24, "rainfall_3d_mm": 72, "rainfall_7d_mm": 168}
_OPERATORS = {">=", ">", "<=", "<", "==", "=", "!=", "gte", "gt", "lte", "lt", "eq", "ne"}
_OPERATOR_ALIASES = {"gte": ">=", "gt": ">", "lte": "<=", "lt": "<", "eq": "==", "=": "==", "ne": "!="}
_DYNAMIC_RISK_NOT_CONNECTED_REASON = (
    "缺少事件级动态 H/R 服务契约：现有 P6 API 仅只读历史候选快照，Worker B/D 是整市离线候选批处理；"
    "未找到按 slope_unit_id/time_slice_id 接收带单位、时间与来源的降雨窗口、位移和库水位字段并返回带算法版本结果的调用接口。"
)


def _key(value: Any) -> str:
    return str(value).strip().casefold().replace(" ", "_").replace("-", "_")


def _canonical_metric(value: Any) -> str:
    raw = str(value).strip()
    return _ALIAS_TO_METRIC.get(raw.casefold().replace(" ", "_"), raw)


def _coerce(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    if text.casefold() in {"true", "false"}:
        return text.casefold() == "true"
    try:
        number = float(text)
    except ValueError:
        return text
    return number if math.isfinite(number) else text


def _scalar(value: Any) -> Any:
    if isinstance(value, Mapping):
        for key in ("value", "value_mm", "level", "level_m", "amount", "total", "measurement"):
            if key in value:
                return _scalar(value[key])
        return None
    return _coerce(value)


def _unit_from_key(value: Any) -> str | None:
    key = _key(value)
    if key.endswith(("_mm_per_day", "_mm_day", "_mm_d", "_mm_per_d")):
        return "mm/d"
    if key.endswith(("_mm_per_hour", "_mm_h", "_mm_hour")):
        return "mm/h"
    if key.endswith("_mm"):
        return "mm"
    if key.endswith("_m"):
        return "m"
    return None


def _normalize_unit(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().casefold().replace(" ", "").replace("毫米", "mm").replace("米", "m")
    return {
        "mm/day": "mm/d", "mm/d": "mm/d", "mmperday": "mm/d", "mm/天": "mm/d",
        "mm/hour": "mm/h", "mm/h": "mm/h", "mmperhour": "mm/h", "mm/小时": "mm/h",
        "millimeter": "mm", "millimeters": "mm", "mm": "mm", "meter": "m", "meters": "m", "m": "m",
    }.get(normalized, normalized)


def _csv_rows(text: str) -> list[dict[str, Any]]:
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def _payload(value: Any) -> tuple[dict[str, Any], str, str]:
    if isinstance(value, Path):
        text = value.read_text(encoding="utf-8-sig")
        parsed, input_format, status = _payload(text)
        if value.suffix.casefold() == ".csv":
            input_format = "csv"
        elif value.suffix.casefold() == ".json":
            input_format = "json"
        return parsed, input_format, status
    if isinstance(value, Mapping):
        parsed = dict(value)
        format_hint = str(parsed.get("format", parsed.get("input_format", "structured"))).casefold()
        csv_text = parsed.get("csv_text", parsed.get("csv"))
        if not isinstance(csv_text, str) and format_hint == "csv" and isinstance(parsed.get("data"), str):
            csv_text = parsed["data"]
        if isinstance(csv_text, str):
            parsed.pop("csv_text", None)
            parsed.pop("csv", None)
            parsed.pop("data", None)
            parsed["observations"] = _csv_rows(csv_text)
            return parsed, "csv", "completed"
        return parsed, format_hint, "completed"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return {"observations": list(value)}, "structured", "completed"
    if isinstance(value, str):
        text = value.lstrip("\ufeff").strip()
        if not text:
            return {}, "unknown", "empty_input"
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError):
            rows = _csv_rows(text)
            if not rows:
                return {}, "csv", "empty_input"
            parsed = {"observations": rows}
            return parsed, "csv", "completed"
        if isinstance(decoded, Mapping):
            parsed, input_format, status = _payload(decoded)
            return parsed, "json" if input_format == "structured" else input_format, status
        if isinstance(decoded, list):
            return {"observations": decoded}, "json", "completed"
        return {}, "json", "invalid_input"
    return {}, "unknown", "invalid_input"


def _observation_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    for field in ("observations", "series", "records", "data"):
        value = payload.get(field)
        if isinstance(value, Mapping):
            return [dict(value)]
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [dict(item) for item in value if isinstance(item, Mapping)]

    row = {key: value for key, value in payload.items() if key not in {
        "thresholds", "trigger_rules", "trigger_rule", "match_mode", "event", "format", "input_format",
        "data_source", "source", "is_simulated", *_EVENT_KEYS,
    }}
    has_metric = any(_metric_value(row, metric) is not None for metric in _METRIC_ALIASES)
    has_long_value = _long_metric_value(row) is not None
    return [row] if has_metric or has_long_value else []


def _long_metric_value(row: Mapping[str, Any]) -> tuple[str, Any] | None:
    metric_name = next((row[key] for key in ("metric", "indicator", "variable", "field") if row.get(key) not in (None, "")), None)
    value = next((row[key] for key in ("value", "observed_value", "measurement") if key in row), None)
    if metric_name is None or value is None:
        return None
    return _canonical_metric(metric_name), _coerce(value)


def _metric_value(row: Mapping[str, Any], metric: str) -> Any:
    for key, value in row.items():
        if _key(key) in {"metric", "indicator", "variable", "field"}:
            continue
        if _canonical_metric(key) == metric:
            scalar_value = _scalar(value)
            if scalar_value is not None:
                return scalar_value

    nested = _NESTED_FIELDS.get(metric)
    if nested:
        group_name, aliases = nested
        group = row.get(group_name)
        if isinstance(group, Mapping):
            wanted = {alias.casefold().replace(" ", "_") for alias in aliases}
            for key, value in group.items():
                if str(key).casefold().replace(" ", "_") in wanted:
                    return _scalar(value)

    long_value = _long_metric_value(row)
    return long_value[1] if long_value and long_value[0] == metric else None


def _normalize_observation(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for key in _TIMESTAMP_KEYS:
        if row.get(key) not in (None, ""):
            normalized["observed_at"] = row[key]
            break
    for metric in _METRIC_ALIASES:
        value = _metric_value(row, metric)
        if value is not None:
            normalized[metric] = value
    return normalized


def _unit_for_metric(row: Mapping[str, Any], metric: str) -> Any:
    units = row.get("units")
    aliases = _METRIC_ALIASES[metric]
    if isinstance(units, Mapping):
        for key, value in units.items():
            if _canonical_metric(key) == metric and value not in (None, ""):
                return value
    for key in (f"{metric}_unit", f"{metric}_units", *(f"{alias}_unit" for alias in aliases)):
        if row.get(key) not in (None, ""):
            return row[key]

    nested = _NESTED_FIELDS.get(metric)
    if nested:
        group_name, nested_aliases = nested
        group = row.get(group_name)
        if isinstance(group, Mapping):
            for key, value in group.items():
                if str(key).casefold().replace(" ", "_") in {
                    alias.casefold().replace(" ", "_") for alias in nested_aliases
                } and isinstance(value, Mapping) and value.get("unit") not in (None, ""):
                    return value["unit"]
            if group.get("unit") not in (None, ""):
                return group["unit"]

    for key in row:
        if _canonical_metric(key) == metric:
            unit = _unit_from_key(key)
            if unit:
                return unit
    if nested:
        for alias in nested[1]:
            unit = _unit_from_key(alias)
            if unit:
                return unit
    return None


def _window_hours_for_metric(row: Mapping[str, Any], metric: str) -> Any:
    aliases = _METRIC_ALIASES[metric]
    for key in (f"{metric}_window_hours", f"{metric.removesuffix('_mm')}_window_hours", "rainfall_window_hours"):
        if row.get(key) not in (None, ""):
            return row[key]
    group = row.get("rainfall")
    nested = _NESTED_FIELDS[metric][1]
    if isinstance(group, Mapping):
        for key, value in group.items():
            if str(key).casefold().replace(" ", "_") in {
                alias.casefold().replace(" ", "_") for alias in nested
            } and isinstance(value, Mapping) and value.get("window_hours") not in (None, ""):
                return value["window_hours"]
        if group.get("window_hours") not in (None, ""):
            return group["window_hours"]
    for alias in aliases:
        key = f"{alias}_window_hours"
        if row.get(key) not in (None, ""):
            return row[key]
    return None


def _window_hours(value: Any) -> Any:
    parsed = _scalar(value)
    if isinstance(parsed, (int, float)) and not isinstance(parsed, bool):
        return parsed
    if isinstance(parsed, str):
        return {"24h": 24, "1d": 24, "72h": 72, "3d": 72, "168h": 168, "7d": 168}.get(
            parsed.strip().casefold().replace(" ", "")
        )
    return None


def _aware_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _rainfall_increment_details(row: Mapping[str, Any]) -> tuple[Any, list[str]]:
    value = _scalar(row.get("rainfall_increment_mm"))
    units = row.get("units")
    unit = row.get("rainfall_increment_mm_unit")
    if unit in (None, "") and isinstance(units, Mapping):
        unit = next((item for key, item in units.items()
                     if _key(key) == "rainfall_increment_mm" and item not in (None, "")), None)
    interval = _coerce(row.get("rainfall_increment_interval_hours"))
    errors: list[str] = []
    if unit in (None, ""):
        errors.append("missing_unit")
    elif _normalize_unit(unit) != "mm":
        errors.append("invalid_unit")
    if row.get("rainfall_increment_interval_hours") in (None, ""):
        errors.append("unknown_interval")
    elif not isinstance(interval, (int, float)) or isinstance(interval, bool) or interval != 1:
        errors.append("invalid_interval")
    if value is None:
        errors.append("missing_value")
    elif not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
        errors.append("invalid_value")
    return value, errors


def _rainfall_window_aggregation(
    rows: Sequence[Mapping[str, Any]], as_of_value: Any, *, source: str,
) -> dict[str, Any]:
    source_field = "observations[].rainfall_increment_mm"
    as_of = _aware_datetime(as_of_value)
    as_of_problem = None if as_of is not None else (
        "missing_as_of" if as_of_value in (None, "") else "invalid_as_of"
    )
    as_of_utc = as_of.astimezone(timezone.utc) if as_of else None
    candidates: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if "rainfall_increment_mm" not in row:
            continue
        timestamp_value = next((row[key] for key in _TIMESTAMP_KEYS if row.get(key) not in (None, "")), None)
        timestamp = _aware_datetime(timestamp_value)
        value, errors = _rainfall_increment_details(row)
        candidates.append({
            "observation_index": index,
            "observed_at": timestamp,
            "value_mm": value,
            "errors": errors,
        })
    unplaced_record_count = sum(item["observed_at"] is None for item in candidates)
    windows: dict[str, dict[str, Any]] = {}
    for metric, hours in _RAIN_WINDOW_HOURS.items():
        base = {
            "source": source,
            "source_field": source_field,
            "is_simulated": True,
            "window_hours": hours,
            "window_start": None,
            "window_end": as_of.isoformat() if as_of else None,
            "window_bounds": "(window_start, window_end]",
            "observation_count": 0,
            "candidate_record_count": 0,
            "expected_count": hours,
            "missing_count": hours,
            "coverage": {
                "status": "unknown" if as_of_problem else "missing",
                "fraction": 0.0,
            },
            "total_mm": None,
            "observations": [],
            "issues": {},
        }
        if as_of_problem:
            base.update(status=as_of_problem, as_of=as_of_value, candidate_record_count=len(candidates))
            if unplaced_record_count:
                base["issues"]["unplaced_record_count"] = unplaced_record_count
            windows[metric] = base
            continue

        window_start = as_of - timedelta(hours=hours)
        start_utc = window_start.astimezone(timezone.utc)
        base["window_start"] = window_start.isoformat()
        base["as_of"] = as_of.isoformat()
        expected_ends = {
            as_of_utc - timedelta(hours=offset)
            for offset in range(hours - 1, -1, -1)
        }
        in_window: dict[datetime, list[dict[str, Any]]] = {}
        for item in candidates:
            timestamp = item["observed_at"]
            if timestamp is None:
                continue
            key = timestamp.astimezone(timezone.utc)
            if start_utc < key <= as_of_utc:
                in_window.setdefault(key, []).append(item)

        observed: list[dict[str, Any]] = []
        issues: dict[str, int] = {}
        duplicate_timestamps: list[str] = []
        for timestamp, items in in_window.items():
            if len(items) > 1:
                issues["duplicate_count"] = issues.get("duplicate_count", 0) + len(items) - 1
                duplicate_timestamps.append(timestamp.isoformat())
                continue
            item = items[0]
            if timestamp not in expected_ends:
                issues["misaligned_count"] = issues.get("misaligned_count", 0) + 1
                continue
            for error in item["errors"]:
                issues[error] = issues.get(error, 0) + 1
            if not item["errors"]:
                observed.append({
                    "observation_index": item["observation_index"],
                    "observed_at": item["observed_at"].isoformat(),
                    "value_mm": item["value_mm"],
                    "unit": "mm",
                    "interval_hours": 1,
                })
        if duplicate_timestamps:
            issues["duplicate_timestamps"] = duplicate_timestamps
        if unplaced_record_count:
            issues["unplaced_record_count"] = unplaced_record_count
        base["candidate_record_count"] = sum(len(items) for items in in_window.values()) + unplaced_record_count
        observed.sort(key=lambda item: _aware_datetime(item["observed_at"]).astimezone(timezone.utc))
        observation_count = len(observed)
        missing_count = hours - observation_count
        integrity_issues = any(
            key in issues for key in (
                "duplicate_count", "misaligned_count", "missing_unit", "invalid_unit",
                "unknown_interval", "invalid_interval", "invalid_value", "unplaced_record_count",
            )
        )
        complete = observation_count == hours and not integrity_issues
        coverage_status = "invalid" if integrity_issues else (
            "complete" if complete else "partial" if observation_count else "missing"
        )
        status = "available" if complete else (
            "invalid" if integrity_issues else "partial" if observation_count else "missing"
        )
        base.update({
            "status": status,
            "observation_count": observation_count,
            "missing_count": missing_count,
            "coverage": {
                "status": coverage_status,
                "fraction": observation_count / hours,
            },
            "observations": observed,
            "issues": issues,
        })
        if complete:
            base["total_mm"] = sum(item["value_mm"] for item in observed)
        windows[metric] = base

    if as_of_problem:
        status = as_of_problem
    elif any(window["status"] == "invalid" for window in windows.values()):
        status = "invalid"
    elif all(window["status"] == "available" for window in windows.values()):
        status = "available"
    elif any(window["status"] == "partial" for window in windows.values()):
        status = "partial"
    else:
        status = "missing"
    return {
        "status": status,
        "source": source,
        "source_field": source_field,
        "measurement": "hourly_interval_increment",
        "unit": "mm",
        "interval_hours": 1,
        "as_of": as_of.isoformat() if as_of else as_of_value,
        "is_simulated": True,
        "candidate_record_count": len(candidates),
        "unplaced_record_count": unplaced_record_count,
        "windows": windows,
    }


def compact_monitoring_evidence(value: Any, sample_size: int = 8) -> dict[str, Any]:
    """Keep agent prompts bounded while the complete series remains in persisted facts."""
    if not isinstance(value, Mapping):
        return {}

    result = dict(value)
    observations = None
    for key in ("series", "observations"):
        rows = result.get(key)
        if isinstance(rows, list):
            if observations is None:
                observations = rows
            result[key] = rows[-sample_size:]
    if observations is not None:
        result["observation_count"] = len(observations)
        result["observation_sample_scope"] = f"latest_{sample_size}_only; full series remains in persisted event"

    validation = result.get("validation")
    if not isinstance(validation, Mapping):
        return result

    compact: dict[str, Any] = {}
    metric_fields = (
        "status", "expected_unit", "expected_window_hours", "declared_window_hours",
        "window_status", "observed_count", "valid_count", "missing_count",
    )
    for section in ("metrics", "rainfall_windows"):
        records = validation.get(section)
        if not isinstance(records, Mapping):
            continue
        compact_records: dict[str, Any] = {}
        for name, item in records.items():
            if not isinstance(item, Mapping):
                continue
            summary = {key: item[key] for key in metric_fields if key in item}
            aggregation = item.get("aggregation")
            if section == "rainfall_windows" and isinstance(aggregation, Mapping):
                agg_fields = (
                    "status", "source", "window_hours", "window_start", "window_end",
                    "observation_count", "candidate_record_count", "expected_count", "missing_count",
                    "coverage", "total_mm",
                )
                agg_summary = {key: aggregation[key] for key in agg_fields if key in aggregation}
                issues = aggregation.get("issues")
                if isinstance(issues, Mapping):
                    agg_summary["issue_counts"] = {
                        key: item_value for key, item_value in issues.items()
                        if not isinstance(item_value, list)
                    }
                    duplicate_times = issues.get("duplicate_timestamps")
                    if isinstance(duplicate_times, list):
                        agg_summary["duplicate_timestamp_count"] = len(duplicate_times)
                summary["aggregation"] = agg_summary
            compact_records[str(name)] = summary
        compact[section] = compact_records

    for section, fields in (
        ("object_identity", ("status", "event_ids", "observation_id_count")),
        ("displacement_reservoir_association", ("status", "pair_count", "event_object_id")),
    ):
        item = validation.get(section)
        if not isinstance(item, Mapping):
            continue
        summary = {key: item[key] for key in fields if key in item}
        samples_key = "mismatches" if section == "object_identity" else "pairs"
        samples = item.get(samples_key)
        if isinstance(samples, list):
            summary["issue_or_pair_count"] = len(samples)
            summary["samples"] = samples[:3]
        compact[section] = summary

    result["validation"] = compact
    return result

def _not_connected_rainfall_window_aggregation(*, is_simulated: bool) -> dict[str, Any]:
    source = "real_monitoring_source_not_connected"
    source_field = "observations[].rainfall_increment_mm"
    return {
        "status": "not_connected",
        "source": source,
        "source_field": source_field,
        "measurement": "hourly_interval_increment",
        "unit": "mm",
        "interval_hours": 1,
        "as_of": None,
        "is_simulated": is_simulated,
        "windows": {
            metric: {
                "status": "not_connected",
                "source": source,
                "source_field": source_field,
                "is_simulated": is_simulated,
                "window_hours": hours,
                "window_start": None,
                "window_end": None,
                "window_bounds": "(window_start, window_end]",
                "observation_count": 0,
                "expected_count": hours,
                "missing_count": None,
                "coverage": {"status": "not_connected", "fraction": None},
                "total_mm": None,
                "observations": [],
                "issues": {},
            }
            for metric, hours in _RAIN_WINDOW_HOURS.items()
        },
    }


def _metric_validation(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, set[int]]]:
    validation: dict[str, dict[str, Any]] = {}
    eligible: dict[str, set[int]] = {}
    for metric in _METRIC_ALIASES:
        expected_unit = _EXPECTED_UNITS.get(metric)
        expected_hours = _RAIN_WINDOW_HOURS.get(metric)
        observations: list[dict[str, Any]] = []
        valid_indexes: set[int] = set()
        observed_count = 0
        for index, row in enumerate(rows):
            value = _metric_value(row, metric)
            if value is None:
                continue
            observed_count += 1
            item: dict[str, Any] = {"observation_index": index, "status": "available"}
            valid = True
            if expected_unit:
                supplied_unit = _unit_for_metric(row, metric)
                normalized_unit = _normalize_unit(supplied_unit)
                item.update(expected_unit=expected_unit, supplied_unit=supplied_unit)
                if supplied_unit is None:
                    item["unit_status"] = "missing"
                    item["status"] = "missing_unit"
                    valid = False
                elif normalized_unit != expected_unit:
                    item["unit_status"] = "invalid"
                    item["status"] = "invalid_unit"
                    valid = False
                else:
                    item["unit_status"] = "validated"
                numeric_value = _scalar(value)
                if not isinstance(numeric_value, (int, float)) or isinstance(numeric_value, bool):
                    item["status"] = "invalid_value"
                    valid = False
            if expected_hours:
                declared_hours = _window_hours_for_metric(row, metric)
                item["expected_window_hours"] = expected_hours
                item["declared_window_hours"] = declared_hours
                if declared_hours is not None and _window_hours(declared_hours) != expected_hours:
                    item["window_status"] = "invalid"
                    item["status"] = "invalid_window"
                    valid = False
                else:
                    item["window_status"] = "validated_by_field" if declared_hours is None else "validated"
            if valid:
                valid_indexes.add(index)
            observations.append(item)
        if not observed_count:
            status = "missing"
        elif len(valid_indexes) == observed_count:
            status = "available" if observed_count == len(rows) else "partial"
        elif valid_indexes:
            status = "partial_invalid"
        else:
            status = "invalid"
        validation[metric] = {
            "status": status,
            "expected_unit": expected_unit,
            "expected_window_hours": expected_hours,
            "observed_count": observed_count,
            "valid_count": len(valid_indexes),
            "missing_count": len(rows) - observed_count,
            "observations": observations,
        }
        eligible[metric] = valid_indexes if expected_unit else {
            index for index, row in enumerate(rows) if _metric_value(row, metric) is not None
        }
    return validation, eligible


def _id_value(value: Mapping[str, Any], canonical: str) -> Any:
    aliases = _EVENT_FIELD_ALIASES.get(canonical, (canonical,))
    for alias in aliases:
        if value.get(alias) not in (None, ""):
            return value[alias]
    return None


def _object_identity_validation(
    event_fields: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    identifiers = ("slope_unit_id", "hazard_point_id", "monitor_point_id", "monitor_device_id")
    mismatches: list[dict[str, Any]] = []
    row_id_count = 0
    for index, row in enumerate(rows):
        for identifier in identifiers:
            observed_id = _id_value(row, identifier)
            expected_id = event_fields.get(identifier)
            if observed_id not in (None, ""):
                row_id_count += 1
            if observed_id not in (None, "") and expected_id not in (None, "") \
                    and str(observed_id).strip() != str(expected_id).strip():
                mismatches.append({
                    "observation_index": index, "identifier": identifier,
                    "event_id": expected_id, "observation_id": observed_id,
                })
    has_event_id = any(event_fields.get(key) not in (None, "") for key in identifiers)
    status = "mismatch" if mismatches else (
        "available" if has_event_id and row_id_count else
        "event_id_present_observation_id_missing" if has_event_id else
        "observation_id_present_event_id_missing" if row_id_count else "missing"
    )
    return {
        "status": status,
        "event_ids": {key: event_fields[key] for key in identifiers if event_fields.get(key) not in (None, "")},
        "observation_id_count": row_id_count,
        "mismatches": mismatches,
    }


def _displacement_reservoir_association(
    rows: Sequence[Mapping[str, Any]], event_fields: Mapping[str, Any],
) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    saw_displacement = saw_reservoir = False
    for index, row in enumerate(rows):
        has_displacement = _metric_value(row, "displacement_mm") is not None \
            or _metric_value(row, "displacement_rate_mm_per_day") is not None \
            or _metric_value(row, "displacement_rate_mm_per_hour") is not None
        has_reservoir = _metric_value(row, "reservoir_level_m") is not None
        saw_displacement |= has_displacement
        saw_reservoir |= has_reservoir
        if not (has_displacement and has_reservoir):
            continue
        displacement_id = row.get("displacement_object_id") or row.get("displacementObjectId")
        reservoir_id = row.get("reservoir_object_id") or row.get("reservoirObjectId")
        if displacement_id not in (None, "") and reservoir_id not in (None, "") \
                and str(displacement_id).strip() != str(reservoir_id).strip():
            pair_status = "object_id_mismatch"
        elif (displacement_id in (None, "")) != (reservoir_id in (None, "")):
            pair_status = "paired_object_id_missing"
        elif row.get("observed_at") in (None, ""):
            pair_status = "co_observed_timestamp_missing"
        elif displacement_id in (None, "") and not (
            event_fields.get("slope_unit_id") or event_fields.get("monitor_point_id")
        ):
            pair_status = "co_observed_object_id_missing"
        else:
            pair_status = "co_observed"
        pairs.append({"observation_index": index, "status": pair_status,
                      "displacement_object_id": displacement_id, "reservoir_object_id": reservoir_id,
                      "observed_at": row.get("observed_at")})
    if not pairs:
        status = "partial" if saw_displacement or saw_reservoir else "missing"
    elif any(pair["status"] == "object_id_mismatch" for pair in pairs):
        status = "object_id_mismatch"
    elif all(pair["status"] in {"co_observed", "co_observed_timestamp_missing"} for pair in pairs):
        status = "co_observed_same_record"
    elif any(pair["status"] == "co_observed_object_id_missing" for pair in pairs):
        status = "co_observed_object_id_missing"
    else:
        status = "partial_link_metadata"
    return {"status": status, "pair_count": len(pairs), "pairs": pairs,
            "event_object_id": event_fields.get("slope_unit_id") or event_fields.get("monitor_point_id")}


def _rules(value: Any, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    raw_rules: list[tuple[Any, Any]] = []
    if isinstance(value, Mapping) and isinstance(value.get("trigger"), Mapping):
        value = value["trigger"]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        raw_rules.extend((None, item) for item in value)
    elif isinstance(value, Mapping):
        if "metric" in value:
            raw_rules.append((None, value))
        elif isinstance(value.get("conditions"), list):
            raw_rules.extend((None, item) for item in value["conditions"])
        else:
            raw_rules.extend(value.items())

    for row in rows:
        long_value = _long_metric_value(row)
        threshold = row.get("threshold", row.get("threshold_value"))
        if long_value and threshold not in (None, ""):
            raw_rules.append((long_value[0], {
                "operator": row.get("operator") or ">=", "threshold": threshold,
                "rule_id": row.get("rule_id"),
            }))
        elif not long_value:
            supplied_metrics = [metric for metric in _METRIC_ALIASES if _metric_value(row, metric) is not None]
            for metric in supplied_metrics:
                threshold = next((row[key] for key in (
                    f"{metric}_threshold", f"threshold_{metric}", f"{metric}_limit",
                ) if row.get(key) not in (None, "")), None)
                if threshold is None and len(supplied_metrics) == 1:
                    threshold = row.get("threshold", row.get("threshold_value"))
                if threshold not in (None, ""):
                    raw_rules.append((metric, {
                        "operator": row.get(f"{metric}_operator") or row.get("operator") or ">=",
                        "threshold": threshold,
                        "rule_id": row.get(f"{metric}_rule_id", row.get("rule_id")),
                    }))

    normalized: list[dict[str, Any]] = []
    for metric_name, definition in raw_rules:
        if not isinstance(definition, Mapping):
            threshold = _coerce(definition)
            operator = "==" if isinstance(threshold, (str, bool)) else ">="
            detail: Mapping[str, Any] = {}
        else:
            detail = definition
            metric_name = metric_name or detail.get("metric")
            threshold = detail.get("threshold", detail.get("value", detail.get("limit")))
            operator = detail.get("operator", detail.get("op"))
            if operator is None:
                operator = next((key for key in ("gte", "gt", "lte", "lt", "eq", "ne") if key in detail), None)
                if operator is not None:
                    threshold = detail[operator]
            if operator is None:
                operator = "==" if isinstance(_coerce(threshold), (str, bool)) else ">="
        if metric_name in (None, "") or threshold in (None, ""):
            continue
        operator = str(operator).strip().casefold()
        if operator not in _OPERATORS:
            continue
        normalized.append({
            "metric": _canonical_metric(metric_name),
            "operator": _OPERATOR_ALIASES.get(operator, operator),
            "threshold": _coerce(threshold),
            **({"rule_id": detail["rule_id"]} if detail.get("rule_id") not in (None, "") else {}),
        })
    return normalized


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    actual_number, expected_number = _coerce(actual), _coerce(expected)
    numeric = isinstance(actual_number, (int, float)) and not isinstance(actual_number, bool) \
        and isinstance(expected_number, (int, float)) and not isinstance(expected_number, bool)
    if operator in {">=", ">", "<=", "<"} and not numeric:
        return False
    if numeric:
        return {
            ">=": actual_number >= expected_number,
            ">": actual_number > expected_number,
            "<=": actual_number <= expected_number,
            "<": actual_number < expected_number,
            "==": actual_number == expected_number,
            "!=": actual_number != expected_number,
        }[operator]
    if operator not in {"==", "!="}:
        return False
    equal = str(actual_number).casefold() == str(expected_number).casefold()
    return equal if operator == "==" else not equal


def _match_rule(
    rule: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], eligible_indices: set[int] | None = None,
) -> dict[str, Any] | None:
    for index, row in enumerate(rows):
        if eligible_indices is not None and index not in eligible_indices:
            continue
        value = _metric_value(row, str(rule["metric"]))
        if value is not None and _compare(value, str(rule["operator"]), rule["threshold"]):
            match = {
                "metric": rule["metric"], "operator": rule["operator"],
                "threshold": rule["threshold"], "observed_value": value,
                "observation_index": index,
            }
            if row.get("observed_at") not in (None, ""):
                match["observed_at"] = row["observed_at"]
            if rule.get("rule_id") is not None:
                match["rule_id"] = rule["rule_id"]
            return match
    return None


def _missing_rf() -> dict[str, Any]:
    return {
        "status": "missing", "value": None, "source": None, "model": None,
        "version": None, "evidence_ids": [],
    }


def _metric_availability(
    rows: Sequence[Mapping[str, Any]], *, unavailable_status: str | None = None,
) -> dict[str, dict[str, Any]]:
    availability: dict[str, dict[str, Any]] = {}
    for metric in _METRIC_ALIASES:
        if unavailable_status:
            availability[metric] = {
                "status": unavailable_status, "observed_count": 0, "missing_count": None,
            }
            continue
        observed_count = sum(_metric_value(row, metric) is not None for row in rows)
        status = "missing" if not observed_count else (
            "available" if observed_count == len(rows) else "partial"
        )
        availability[metric] = {
            "status": status,
            "observed_count": observed_count,
            "missing_count": len(rows) - observed_count,
        }
    return availability


def _dynamic_risk_not_connected() -> dict[str, Any]:
    return {
        "status": "not_connected",
        "value": None,
        "source": None,
        "model": None,
        "version": None,
        "reason": _DYNAMIC_RISK_NOT_CONNECTED_REASON,
    }


def _explicit_event_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    nested = payload.get("event") if isinstance(payload.get("event"), Mapping) else {}
    fields: dict[str, Any] = {}
    for key in _EVENT_KEYS:
        aliases = _EVENT_FIELD_ALIASES.get(key, (key,))
        value = next((source[alias] for source in (nested, payload) for alias in aliases
                      if source.get(alias) not in (None, "")), None)
        if value not in (None, ""):
            fields[key] = value
    return fields


def _recovery_observation(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for index, row in enumerate(rows):
        value = _metric_value(row, "recovery_status")
        if value is None:
            continue
        if value is True:
            stage = "recovered"
        elif value is False:
            stage = "not_recovering"
        elif isinstance(value, str):
            normalized = value.strip().casefold().replace(" ", "_")
            stage = (
                "recovered" if normalized in {"true", "recovered", "recovery_completed", "已恢复", "恢复完成"}
                else "recovering" if normalized in {"recovering", "in_recovery", "recovery_in_progress", "恢复", "恢复中"}
                else "not_recovering" if normalized in {"false", "normal", "stable", "not_recovering", "未恢复", "稳定", "正常"}
                else "unclassified"
            )
        else:
            stage = "unclassified"
        latest = {"observation_index": index, "observed_value": value, "stage": stage}
        if row.get("observed_at") not in (None, ""):
            latest["observed_at"] = row["observed_at"]
    return latest


def _monitoring_assessment(result: Mapping[str, Any]) -> dict[str, Any]:
    monitoring = result.get("monitoring") if isinstance(result.get("monitoring"), Mapping) else {}
    event = result.get("event") if isinstance(result.get("event"), Mapping) else {}
    provenance = result.get("result_provenance") if isinstance(result.get("result_provenance"), Mapping) else {}
    compact = compact_monitoring_evidence(monitoring, sample_size=1)
    compact_validation = compact.get("validation") if isinstance(compact.get("validation"), Mapping) else {}
    metric_availability = monitoring.get("metric_availability") \
        if isinstance(monitoring.get("metric_availability"), Mapping) else {}
    latest_rows = compact.get("series") if isinstance(compact.get("series"), list) else []
    latest = latest_rows[-1] if latest_rows and isinstance(latest_rows[-1], Mapping) else {}
    object_identity = compact_validation.get("object_identity") \
        if isinstance(compact_validation.get("object_identity"), Mapping) else {"status": "missing"}
    association = compact_validation.get("displacement_reservoir_association") \
        if isinstance(compact_validation.get("displacement_reservoir_association"), Mapping) else {"status": "missing"}
    trigger_rule = monitoring.get("trigger_rule") if isinstance(monitoring.get("trigger_rule"), Mapping) else {}
    triggered_rules = monitoring.get("triggered_rules") if isinstance(monitoring.get("triggered_rules"), list) else []

    def measurement(metric: str) -> dict[str, Any]:
        availability = metric_availability.get(metric) if isinstance(metric_availability.get(metric), Mapping) else {}
        return {
            "status": availability.get("status", "missing"),
            "value": latest.get(metric),
            "unit": _EXPECTED_UNITS.get(metric),
        }

    monitoring_status = monitoring.get("status", "missing")
    recovery_detected = result.get("recovery_detected")
    recovery_stage = monitoring.get("recovery_stage", "missing")
    recovery_state = None if recovery_stage in {"missing", "not_connected"} else recovery_detected
    if triggered_rules:
        trigger_reason_status = "matched"
    elif recovery_detected is True:
        trigger_reason_status = "recovery_observed"
    elif monitoring_status in {"missing", "not_connected"}:
        trigger_reason_status = monitoring_status
    elif trigger_rule.get("purpose") == "not_applied_to_real_input":
        trigger_reason_status = "not_applied"
    else:
        trigger_reason_status = "no_match"

    return {
        "status": monitoring_status,
        "event_status": result.get("event_status", "missing"),
        "monitoring_object": {
            "slope_unit_id": result.get("slope_unit_id"),
            "hazard_point_id": result.get("hazard_point_id"),
            "monitor_point_id": event.get("monitor_point_id"),
            "monitor_device_id": event.get("monitor_device_id"),
            "admin_area": result.get("admin_area"),
            "spatial_object_source": event.get("spatial_object_source"),
            "geometry_status": event.get("geometry_status"),
            "identity_validation": object_identity,
            "displacement_reservoir_association": association,
        },
        "rainfall": {
            "latest_observed_at": latest.get("observed_at"),
            "measurements": {
                metric: measurement(metric)
                for metric in (
                    "short_term_rainfall_mm", "continuous_rainfall_mm",
                    "rainfall_24h_mm", "rainfall_3d_mm", "rainfall_7d_mm",
                )
            },
            "windows": compact_validation.get("rainfall_windows", {}),
        },
        "displacement": {
            "latest_observed_at": latest.get("observed_at"),
            "displacement": measurement("displacement_mm"),
            "rate_per_day": measurement("displacement_rate_mm_per_day"),
            "rate_per_hour": measurement("displacement_rate_mm_per_hour"),
            "association_validation": association,
        },
        "reservoir_level": {
            "latest_observed_at": latest.get("observed_at"),
            "level": measurement("reservoir_level_m"),
            "trend": measurement("reservoir_trend"),
        },
        "anomaly_trend": {
            "status": (
                "triggered" if monitoring.get("triggered") is True else
                "no_trigger" if monitoring.get("triggered") is False and monitoring_status == "available"
                else monitoring_status
            ),
            "triggered": monitoring.get("triggered"),
            "triggered_rules": triggered_rules,
            "trend_prediction_model_status": provenance.get("trend_prediction_model", "missing"),
        },
        "trigger_reason": {
            "status": trigger_reason_status,
            "purpose": trigger_rule.get("purpose"),
            "match_mode": trigger_rule.get("match_mode"),
            "scope": monitoring.get("trigger_rule_scope"),
            "matched_rules": triggered_rules,
            "recovery_detected": recovery_state,
            "official_warning_created": monitoring.get("official_warning_created", False),
        },
        "recovery_status": {
            "status": recovery_stage,
            "detected": recovery_state,
            "stage": recovery_stage,
            "observation": result.get("recovery_observation"),
        },
        "source": {
            "kind": result.get("source_kind"),
            "data_source": result.get("data_source"),
            "source_mode": result.get("source_mode"),
            "observation_source": provenance.get("observation_source", "missing"),
            "is_simulated": result.get("is_simulated"),
            "model_version": result.get("model_version"),
        },
        "model_status": {
            "model_version": result.get("model_version"),
            "trend_prediction_model": provenance.get("trend_prediction_model", "missing"),
            "dynamic_risk": result.get("dynamic_risk"),
            "p6_dynamic_monitoring": result.get("p6_dynamic_monitoring"),
            "risk_assessments": result.get("assessments", {}),
            "formal_result": provenance.get("formal_result", False),
        },
    }


def _attach_monitoring_assessment(result: dict[str, Any]) -> dict[str, Any]:
    assessment = _monitoring_assessment(result)
    result["monitoring_assessment"] = assessment
    event = result.get("event")
    if isinstance(event, dict):
        event["monitoring_assessment"] = assessment
    return result


class GoldMonitoringAdapter:
    """Evaluate fixture-supplied conditions; never infer an official alarm threshold."""

    def process(self, value: Any) -> dict[str, Any]:
        payload, input_format, parse_status = _payload(value)
        raw_rows = _observation_rows(payload)
        series = [_normalize_observation(row) for row in raw_rows]
        source_event = payload.get("event") if isinstance(payload.get("event"), Mapping) else {}
        event_fields = _explicit_event_fields(payload)
        if event_fields.get("correlation_id") in (None, ""):
            parent_correlation_id = event_fields.get("parent_correlation_id")
            if parent_correlation_id not in (None, ""):
                event_fields["correlation_id"] = parent_correlation_id
        source_mode = payload.get("source_mode", payload.get("sourceMode",
                      source_event.get("source_mode", source_event.get("sourceMode"))))
        raw_simulation = payload.get("is_simulated", payload.get("isSimulated",
                           source_event.get("is_simulated", source_event.get("isSimulated"))))
        source_kind_hint = str(payload.get("source_kind", payload.get("sourceKind",
                                 source_event.get("source_kind", source_event.get("sourceKind", ""))))).strip().upper()
        if _scalar(raw_simulation) is False or (raw_simulation is None and source_kind_hint == "REAL"):
            return RealMonitoringAdapter().process(value)
        is_simulated = True
        source_kind = "SIMULATED"
        model_version = next((source.get(key) for source in (payload, source_event)
                             for key in ("model_version", "modelVersion", "parameter_version", "parameterVersion")
                             if source.get(key) not in (None, "")), None)
        if model_version is None:
            model_version = next((row.get(key) for row in raw_rows
                                  for key in ("model_version", "modelVersion", "parameter_version", "parameterVersion")
                                  if row.get(key) not in (None, "")), None)
        metric_validation, eligible_rule_rows = _metric_validation(raw_rows)
        identity_validation = _object_identity_validation(event_fields, raw_rows)
        association_validation = _displacement_reservoir_association(raw_rows, event_fields)
        if identity_validation["status"] == "mismatch":
            eligible_rule_rows = {metric: set() for metric in eligible_rule_rows}
        if association_validation["status"] == "object_id_mismatch":
            for metric in ("displacement_mm", "displacement_rate_mm_per_day", "displacement_rate_mm_per_hour", "reservoir_level_m"):
                eligible_rule_rows[metric] = set()
        supplied_conditions = _rules(payload.get(
            "gold_test_thresholds",
            payload.get("thresholds", payload.get("trigger_rules", payload.get("trigger_rule"))),
        ), raw_rows)
        conditions = supplied_conditions
        match_mode = str(payload.get("match_mode", "any")).casefold()
        if match_mode not in {"any", "all"}:
            match_mode = "any"

        matches = [_match_rule(rule, series, eligible_rule_rows.get(rule["metric"], set())) for rule in conditions]
        matched = [item for item in matches if item is not None]
        threshold_triggered = bool(conditions) and (
            len(matched) == len(conditions) if match_mode == "all" else bool(matched)
        )
        recovery_observation = None if identity_validation["status"] == "mismatch" else _recovery_observation(raw_rows)
        recovery_detected = recovery_observation is not None and recovery_observation["stage"] in {
            "recovering", "recovered",
        }
        triggered = threshold_triggered or recovery_detected
        row_source = next((row.get("data_source", row.get("dataSource", row.get("source"))) for row in raw_rows
                           if row.get("data_source", row.get("dataSource", row.get("source"))) not in (None, "")), None)
        data_source = payload.get("data_source") or payload.get("dataSource") \
            or source_event.get("data_source") or source_event.get("dataSource") \
            or payload.get("source") or row_source or ("gold_fixture" if is_simulated else "monitoring_input")
        rainfall_window_aggregation = _rainfall_window_aggregation(
            raw_rows, payload.get("as_of"), source=data_source,
        )
        metric_availability = _metric_availability(series)
        missing_metrics = [metric for metric, item in metric_availability.items() if item["status"] == "missing"]
        partial_metrics = [metric for metric, item in metric_availability.items() if item["status"] == "partial"]
        monitoring_status = "available" if series else "missing"
        event_status = "ready_for_a4_review" if triggered else ("no_trigger" if series else "incomplete_input")
        rainfall_windows = {metric: metric_validation[metric] for metric in _RAIN_WINDOW_HOURS}
        for metric, window in rainfall_window_aggregation["windows"].items():
            rainfall_windows[metric]["aggregation"] = window
        validation = {
            "metrics": metric_validation,
            "rainfall_windows": rainfall_windows,
            "object_identity": identity_validation,
            "displacement_reservoir_association": association_validation,
        }
        dynamic_monitoring_status = {
            "status": "unavailable",
            "source": "P6 dynamic H/R service (not connected)",
            "query_status": "not_requested" if is_simulated else "not_connected",
            "recalculation_status": "unavailable",
            "reason": _DYNAMIC_RISK_NOT_CONNECTED_REASON,
        }
        result_provenance = {
            "observation_source": ("gold_simulated" if is_simulated else data_source) if series else "missing",
            "source_mode": source_mode,
            "deterministic_evaluation": "completed" if series else "missing_input",
            "trend_prediction_model": "not_connected",
            "model_version": model_version,
            "formal_result": False,
        }
        summary = (
            f"{'Gold 回归样本' if is_simulated else '输入观测'}匹配 {len(matched)} 条显式条件；阈值仅用于 Gold 回归，不代表官方预警标准。"
            if triggered else
            ("Gold 回归样本未匹配显式条件；未使用默认或官方阈值。" if is_simulated
             else "真实输入未应用 Gold 回归阈值；未生成正式预警或动态风险等级。")
        )
        monitoring = {
            "status": monitoring_status,
            "source": "GoldMonitoringAdapter",
            "data_source": data_source,
            "source_mode": source_mode,
            "is_simulated": is_simulated,
            "model_version": model_version,
            "series": series,
            "metric_availability": metric_availability,
            "validation": validation,
            "summary": summary,
            "calculation_mode": "gold_deterministic_rules",
            "trigger_rule": {
                "purpose": "gold_regression_only" if is_simulated else "not_applied_to_real_input",
                "match_mode": match_mode,
                "conditions": conditions,
            },
            "triggered_rules": matched,
            "triggered": triggered,
            "recovery_detected": recovery_detected,
            "recovery_stage": recovery_observation["stage"] if recovery_observation else "missing",
            "trigger_rule_scope": "gold_regression_only",
            "official_warning_created": False,
        }
        dynamic_risk = _dynamic_risk_not_connected()
        assessments = {"rf_static_susceptibility": _missing_rf()}
        event_type = event_fields.get("event_type")
        if not event_type:
            event_type = (
                ("simulated_" if is_simulated else "") + "monitoring_recovery" if recovery_detected else
                ("simulated_" if is_simulated else "") + "monitoring_threshold_match" if threshold_triggered else
                ("simulated_" if is_simulated else "") + "monitoring_observation"
            )
        event = {
            **event_fields,
            "source_kind": source_kind,
            "event_type": event_type,
            "data_source": data_source,
            "source_mode": source_mode,
            "is_simulated": is_simulated,
            "model_version": model_version,
            "event_status": event_status,
            "monitoring": monitoring,
            "dynamic_risk": dynamic_risk,
            "p6_dynamic_monitoring": dynamic_monitoring_status,
            "assessments": assessments,
            "formal_warning_created": False,
            "task_created": False,
        }
        trace = [
            {"step": "parse_gold_input", "status": parse_status, "input_format": input_format},
            {"step": "normalize_observations", "status": "completed" if series else "missing", "observation_count": len(series), "missing_metrics": missing_metrics, "partial_metrics": partial_metrics},
            {
                "step": "aggregate_hourly_rainfall_windows",
                "status": rainfall_window_aggregation["status"],
                "source_field": rainfall_window_aggregation["source_field"],
                "as_of": rainfall_window_aggregation["as_of"],
                "is_simulated": True,
                "windows": {
                    metric: {
                        "status": window["status"],
                        "observation_count": window["observation_count"],
                        "expected_count": window["expected_count"],
                        "missing_count": window["missing_count"],
                        "coverage": window["coverage"],
                        "total_mm": window["total_mm"],
                    }
                    for metric, window in rainfall_window_aggregation["windows"].items()
                },
            },
            {"step": "validate_monitoring_dimensions", "status": "completed" if series else "missing", "object_identity": identity_validation["status"], "displacement_reservoir_association": association_validation["status"]},
            {"step": "evaluate_fixture_conditions", "status": "completed" if conditions else "not_configured", "purpose": "gold_regression_only" if is_simulated else "not_applied_to_real_input", "condition_count": len(conditions), "matched_count": len(matched), "match_mode": match_mode},
            {"step": "detect_explicit_recovery_state", "status": "recovery_observed" if recovery_detected else "no_recovery_state", "observation": recovery_observation},
            {"step": "calculate_dynamic_risk", "status": dynamic_risk["status"], "reason": dynamic_risk["reason"]},
            {
                "step": "recalculate_p6_dynamic_hr",
                "status": "pending",
                "availability": "unavailable",
                "reason": _DYNAMIC_RISK_NOT_CONNECTED_REASON,
            },
            {"step": "prepare_a4_event", "status": event_status, "formal_warning_created": False, "task_created": False},
        ]
        result = {
            "status": "triggered" if threshold_triggered else ("recovery_observed" if recovery_detected else ("no_trigger" if series else "missing_input")),
            "event_status": event_status,
            "a4_ready": triggered,
            "event": event,
            "event_id": event.get("event_id"),
            "source_kind": source_kind,
            "execution_engine": "local",
            "result_provenance": result_provenance,
            "correlation_id": event.get("correlation_id"),
            "admin_area": event.get("admin_area"),
            "slope_unit_id": event.get("slope_unit_id"),
            "hazard_point_id": event.get("hazard_point_id"),
            "data_source": data_source,
            "source_mode": source_mode,
            "is_simulated": is_simulated,
            "model_version": model_version,
            "monitoring": monitoring,
            "metric_availability": metric_availability,
            "validation": validation,
            "dynamic_risk": dynamic_risk,
            "p6_dynamic_monitoring": dynamic_monitoring_status,
            "recovery_detected": recovery_detected,
            "recovery_observation": recovery_observation,
            "assessments": assessments,
            "missing_model_components": ["rf_static_susceptibility"],
            "formal_warning_created": False,
            "task_created": False,
            "explanation": None,
            "trace": trace,
        }
        return _attach_monitoring_assessment(result)


class RealMonitoringAdapter:
    """Report the real source as disconnected until a monitoring integration exists."""

    def process(self, value: Any = None) -> dict[str, Any]:
        payload, _, _ = _payload(value)
        nested = payload.get("event") if isinstance(payload.get("event"), Mapping) else {}
        rows = _observation_rows(payload)
        row_simulation = any(_scalar(row.get("is_simulated", row.get("isSimulated"))) is True for row in rows)
        row_source = next((row.get("data_source", row.get("dataSource", row.get("source"))) for row in rows
                           if row.get("data_source", row.get("dataSource", row.get("source"))) not in (None, "")), None)
        data_source = payload.get("data_source") or payload.get("dataSource") \
            or nested.get("data_source") or nested.get("dataSource") \
            or payload.get("source") or row_source or "real_monitoring_not_connected"
        is_simulated = _scalar(payload.get("is_simulated", payload.get("isSimulated"))) is True \
            or _scalar(nested.get("is_simulated", nested.get("isSimulated"))) is True or row_simulation
        event_fields = _explicit_event_fields(payload)
        metric_availability = _metric_availability((), unavailable_status="not_connected")
        model_version = payload.get("model_version", payload.get("modelVersion",
                        nested.get("model_version", nested.get("modelVersion"))))
        source_mode = payload.get("source_mode", payload.get("sourceMode",
                      nested.get("source_mode", nested.get("sourceMode"))))
        rainfall_window_aggregation = _not_connected_rainfall_window_aggregation(
            is_simulated=is_simulated,
        )
        result_provenance = {
            "observation_source": "real_monitoring_not_connected",
            "source_mode": source_mode,
            "deterministic_evaluation": "not_run",
            "trend_prediction_model": "not_connected",
            "model_version": model_version,
            "formal_result": False,
        }
        monitoring = {
            "status": "not_connected",
            "source": "RealMonitoringAdapter",
            "data_source": data_source,
            "source_mode": source_mode,
            "is_simulated": is_simulated,
            "model_version": model_version,
            "series": [],
            "metric_availability": metric_availability,
            "validation": {
                "metrics": {},
                "rainfall_windows": {
                    metric: {
                        "status": "not_connected",
                        "expected_window_hours": hours,
                        "aggregation": rainfall_window_aggregation["windows"][metric],
                    }
                    for metric, hours in _RAIN_WINDOW_HOURS.items()
                },
                "object_identity": {"status": "not_connected"},
                "displacement_reservoir_association": {"status": "not_connected"},
            },
            "summary": "真实监测数据源尚未接入；未执行阈值判断或趋势预测。",
            "calculation_mode": "not_run",
            "trigger_rule": {
                "purpose": "not_connected",
                "match_mode": None,
                "conditions": [],
            },
            "triggered_rules": [],
            "triggered": None,
            "recovery_detected": None,
            "recovery_stage": "not_connected",
            "trigger_rule_scope": "not_interpreted_as_official_threshold",
            "official_warning_created": False,
        }
        dynamic_risk = _dynamic_risk_not_connected()
        p6_dynamic_monitoring = {
            "status": "unavailable",
            "source": "P6 dynamic H/R service (not connected)",
            "query_status": "not_connected",
            "recalculation_status": "unavailable",
            "reason": _DYNAMIC_RISK_NOT_CONNECTED_REASON,
        }
        result = {
            "status": "not_connected",
            "event_status": "not_connected",
            "a4_ready": False,
            "event": None,
            "event_id": None,
            "source_kind": "SIMULATED" if is_simulated else "REAL",
            "execution_engine": "local",
            "result_provenance": result_provenance,
            "correlation_id": event_fields.get("correlation_id"),
            "admin_area": event_fields.get("admin_area"),
            "slope_unit_id": event_fields.get("slope_unit_id"),
            "hazard_point_id": event_fields.get("hazard_point_id"),
            "data_source": data_source,
            "source_mode": source_mode,
            "is_simulated": is_simulated,
            "model_version": model_version,
            "monitoring": monitoring,
            "metric_availability": metric_availability,
            "validation": monitoring["validation"],
            "dynamic_risk": dynamic_risk,
            "p6_dynamic_monitoring": p6_dynamic_monitoring,
            "recovery_detected": None,
            "recovery_observation": None,
            "assessments": {"rf_static_susceptibility": _missing_rf()},
            "missing_model_components": ["rf_static_susceptibility"],
            "formal_warning_created": False,
            "task_created": False,
            "explanation": None,
            "trace": [
                {"step": "read_real_monitoring_source", "status": "not_connected", "data_source": data_source},
                {"step": "aggregate_hourly_rainfall_windows", "status": "not_connected", "is_simulated": is_simulated},
                {"step": "calculate_dynamic_risk", "status": dynamic_risk["status"], "reason": dynamic_risk["reason"]},
                {
                    "step": "recalculate_p6_dynamic_hr",
                    "status": "pending",
                    "availability": "unavailable",
                    "reason": _DYNAMIC_RISK_NOT_CONNECTED_REASON,
                },
            ],
        }
        return _attach_monitoring_assessment(result)
