"""Map Yichang decision events to the checked-in legacy A4 Dify starts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.dify_client import dify_configured, run_agent
from app.dify_registry import get_dify_app
from app.yichang_monitor import compact_monitoring_evidence

DISPOSAL_MEASURE_CATEGORIES = (
    "人员安置", "警示防护", "监测巡查", "排危除险", "工程治理", "宣传告知", "交通管制", "其他建议",
)
DIFY_EVIDENCE_EXCERPT_COUNT = 2
DIFY_EVIDENCE_EXCERPT_CHARS = 400


def _record(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {"raw_value": value, "status": "provided_unverified"}
        return dict(parsed) if isinstance(parsed, Mapping) else {"value": parsed, "status": "provided_unverified"}
    if value not in (None, ""):
        return {"value": value, "status": "provided_unverified"}
    return {}


def _legacy_records(value: Any, record_fields: set[str], collection_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(value, str) and value.strip():
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    if isinstance(value, Mapping):
        collection = next((value[key] for key in collection_fields if isinstance(value.get(key), list)), None)
        if collection is not None:
            value = collection
        elif record_fields.intersection(value):
            value = [value]
        else:
            return []
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _plan_type_values(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = [value] if value.strip() else []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def is_simulated_evidence(item: Mapping[str, Any]) -> bool:
    metadata = item.get("metadata")
    if item.get("is_simulated") is True or (
        isinstance(metadata, Mapping) and metadata.get("is_simulated") is True
    ):
        return True
    values = [item.get(key) for key in ("evidence_id", "document_id", "chunk_id", "file_name", "title", "name")]
    if isinstance(metadata, Mapping):
        values.extend(metadata.get(key) for key in ("document_id", "file_name", "title", "name"))
    return any(
        "demo-gold" in str(value).casefold().replace("_", "-").replace(" ", "-")
        for value in values if value not in (None, "")
    )


def _merge_evidence(existing: Any, incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(existing, str) and existing.strip():
        try:
            existing = json.loads(existing)
        except (TypeError, ValueError):
            existing = []
    if isinstance(existing, Mapping):
        existing = [existing]
    records = []
    by_id = {}
    for item in [*(existing if isinstance(existing, list) else []), *incoming]:
        if not isinstance(item, Mapping) or is_simulated_evidence(item):
            continue
        # Dify Start paragraph inputs cap each field at 20,480 chars. Keep all stable
        # citations but only a few short excerpts; full evidence remains in the RAG trace.
        record = {
            key: item[key]
            for key in ("evidence_id", "document_id", "chunk_id", "knowledge_base_id", "file_name", "page", "text")
            if key in item
        }
        if not record:
            continue
        evidence_id = record.get("evidence_id")
        if evidence_id not in (None, "") and str(evidence_id) in by_id:
            by_id[str(evidence_id)].update(record)
        else:
            records.append(record)
            if evidence_id not in (None, ""):
                by_id[str(evidence_id)] = record
    excerpts = 0
    for record in records:
        if not isinstance(record.get("text"), str):
            continue
        if excerpts < DIFY_EVIDENCE_EXCERPT_COUNT:
            record["text"] = record["text"][:DIFY_EVIDENCE_EXCERPT_CHARS]
            excerpts += 1
        else:
            record.pop("text")
            record["excerpt_status"] = "omitted_to_fit_dify_input_limit"
    return records


def _compact_a4_monitoring(value: Any) -> dict[str, Any]:
    result = compact_monitoring_evidence(_record(value), sample_size=3)
    result.pop("metric_availability", None)
    validation = result.get("validation")
    if not isinstance(validation, Mapping):
        return result

    compact_validation: dict[str, Any] = {}
    metrics = validation.get("metrics")
    if isinstance(metrics, Mapping):
        metric_fields = ("status", "expected_unit", "expected_window_hours", "observed_count", "missing_count")
        compact_validation["metrics"] = {
            str(name): {key: item[key] for key in metric_fields if key in item}
            for name, item in metrics.items() if isinstance(item, Mapping)
        }
    windows = validation.get("rainfall_windows")
    if isinstance(windows, Mapping):
        aggregate_fields = (
            "status", "source", "window_hours", "window_start", "window_end", "coverage", "total_mm",
        )
        compact_validation["rainfall_windows"] = {
            str(name): {
                "status": item.get("status"),
                "aggregation": {key: item["aggregation"][key] for key in aggregate_fields
                                if key in item["aggregation"]},
            }
            for name, item in windows.items()
            if isinstance(item, Mapping) and isinstance(item.get("aggregation"), Mapping)
        }
    for name, fields in (
        ("object_identity", ("status", "event_ids", "observation_id_count", "issue_or_pair_count")),
        ("displacement_reservoir_association", ("status", "pair_count", "event_object_id", "issue_or_pair_count")),
    ):
        item = validation.get(name)
        if isinstance(item, Mapping):
            compact_validation[name] = {key: item[key] for key in fields if key in item}
    result["validation"] = compact_validation
    return result


def _event_facts(event: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "event_id", "scenario_id", "trace_id", "source_kind", "correlation_id", "admin_area", "city", "county",
        "street", "village",
        "slope_unit_id", "p6_slope_unit_id", "hazard_point_id", "data_source", "is_simulated", "location", "event_type",
        "spatial_ref_status", "spatial_object_source", "p6_mapping",
        "description", "summary", "text", "occurred_at", "visit_time", "gps", "photo_refs",
        "field_notes", "field_report", "field_verification", "findings", "event_status",
        "image_analysis_status", "text_analysis_status", "missing_fields", "uncertainty",
    )
    return {
        key: event[key] for key in keys
        if key in event and (event[key] is not None or key == "gps")
    }


def _field_report_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    report = _record(event.get("field_report"))
    full_text = event.get("text")
    narrative = next((
        value for value in (
            full_text, report.get("narrative"), report.get("sceneTextRecord"), report.get("text"),
            event.get("summary"), event.get("description"),
        )
        if isinstance(value, str) and value.strip()
    ), None)
    if narrative:
        if isinstance(full_text, str) and full_text.strip():
            report["narrative"] = narrative
            report["sceneTextRecord"] = narrative
        else:
            for key in ("narrative", "sceneTextRecord"):
                if not isinstance(report.get(key), str) or not report[key].strip():
                    report[key] = narrative
    return report


def _slope_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = _record(event.get("slope_unit_info"))
    if not payload:
        payload = _record(event.get("slope_unit"))
    if not payload:
        p6_snapshot = event.get("p6_snapshot")
        if isinstance(p6_snapshot, Mapping):
            payload = _record(p6_snapshot.get("unit_snapshot"))
    defaults = {
        "id": event.get("slope_unit_id"),
        "city": event.get("city"),
        "county": event.get("county", event.get("admin_area")),
        "street": event.get("street"),
        "village": event.get("village"),
        "detailedAddress": event.get("detailed_address", event.get("location")),
        "data_source": event.get("data_source"),
        "is_simulated": event.get("is_simulated"),
        "admin_area": event.get("admin_area"),
        "input_status": (
            "provided_unverified"
            if payload or any(event.get(key) not in (None, "") for key in ("slope_unit_id", "slope_unit", "slope_unit_info"))
            else "missing"
        ),
    }
    for key, item in defaults.items():
        if key not in payload and item is not None:
            payload[key] = item
    return payload


def _task_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    source = event.get("task_info") or event.get("task")
    payload = _record(source)
    event_report = _field_report_payload(event)
    task_report = _record(payload.get("reportInfo"))
    if event_report or task_report:
        payload["reportInfo"] = {
            **event_report,
            **{key: value for key, value in task_report.items() if value not in (None, "", {}, [])},
        }
    defaults = {
        "unitId": event.get("slope_unit_id"),
        "detailedAddress": event.get("detailed_address", event.get("location")),
        "source_kind": event.get("source_kind"),
        "data_source": event.get("data_source"),
        "findings": event.get("findings"),
        "missing_fields": event.get("missing_fields"),
        "uncertainty": event.get("uncertainty"),
        "is_simulated": event.get("is_simulated"),
        "event_status": event.get("event_status"),
        "image_analysis_status": event.get("image_analysis_status"),
        "text_analysis_status": event.get("text_analysis_status"),
        "input_status": "provided_unverified" if source else "missing",
    }
    for key, item in defaults.items():
        if key not in payload and item is not None:
            payload[key] = item
    return payload


def _normalize_missing_assessments(assessments: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(assessments)
    for name in ("rf_static_susceptibility", "dynamic_hazard", "vulnerability", "risk"):
        if normalized.get(name) is None or normalized.get(name) == {}:
            normalized[name] = {"status": "missing", "value": None}
    return normalized


def _p6_dynamic_record(value: Mapping[str, Any]) -> dict[str, Any]:
    permitted_use = "候选筛查（不得用于官方预警）"
    if not value:
        return {"status": "missing", "permitted_use": permitted_use, "official_warning_allowed": False}

    fields = (
        "status", "reason", "execution_engine", "source", "source_kind", "data_source", "provider",
        "provider_status", "snapshot_id", "as_of", "as_of_local", "data_time", "data_time_semantics",
        "data_time_status", "valid_time", "valid_time_status", "scenario", "model", "model_version", "version",
        "rule", "rule_version", "slope_unit_id", "rain_status", "rain_source_type",
        "rain_source_types", "rain_past_type", "rain_forecast_type", "rain_past_status", "rain_forecast_status",
        "rain_mapping", "rain_mapping_status", "rain_distance", "rain_distance_m", "rain_distance_km",
        "h_status", "h_grade", "h_score", "h_source", "h_model_version", "h_rule_version",
        "r_status", "r_grade", "r_score", "r_source", "r_model_version", "r_rule_version",
        "permitted_use", "evaluation_status", "expert_approval_evidenced", "official_warning_allowed",
        "calculation_permitted", "approval_status", "is_simulated", "is_station_observation",
        "h_dynamic_status", "h_dynamic_grade", "h_dynamic_score",
        "r_dynamic_status", "r_dynamic_grade", "r_dynamic_score", "h_forecast_status", "h_forecast_grade",
        "h_forecast_score", "r_forecast_status", "r_forecast_grade", "r_forecast_score",
        "h_dynamic_08_status", "h_dynamic_08_grade", "h_dynamic_08_score", "r_dynamic_08_status",
        "r_dynamic_08_grade", "r_dynamic_08_score",
    )
    fields += tuple(
        f"{component}_{mode}_{suffix}"
        for mode in ("dynamic", "forecast", "dynamic_08")
        for component in ("h", "r")
        for suffix in ("source", "data_source", "model", "model_version", "version", "rule_version")
    )
    payload = {key: value[key] for key in fields if key in value}
    for component in ("H", "R"):
        if component not in value:
            continue
        item = value[component]
        if item is None:
            payload[component] = None
        elif isinstance(item, Mapping):
            component_fields = (
                "status", "grade", "score", "source", "data_source", "model", "model_version", "version",
                "rule_version", "permitted_use", "evaluation_status", "expert_approval_evidenced",
                "official_warning_allowed", "calculation_permitted",
            )
            component_payload = {key: item[key] for key in component_fields if key in item}
            component_payload["permitted_use"] = permitted_use
            component_payload["official_warning_allowed"] = False
            payload[component] = component_payload
    payload["permitted_use"] = permitted_use
    payload["official_warning_allowed"] = False
    return payload


def _p6_dynamic_monitoring_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        return {"status": "missing", "official_warning_allowed": False}

    fields = (
        "status", "source", "result_type", "scenario", "p6_slope_unit_id", "is_simulated_sensor_data",
        "recalculation_status", "mapping_status", "query_status", "unit_mapping_status", "snapshot_id",
        "rule_version", "as_of", "model", "rain_source", "historical_type", "forecast_type", "unit_count",
        "rain_status", "rain_mapping_status", "rain_mapping_distance_km", "rain_grid_id",
        "h_candidate_grade", "r_candidate_grade", "reason",
    )
    payload = {key: value[key] for key in fields if key in value}
    payload.setdefault("status", "missing")

    rain_windows = value.get("rain_windows")
    if isinstance(rain_windows, Mapping):
        window_fields = ("source_type", "status", "24h_mm", "72h_mm", "168h_mm")
        payload["rain_windows"] = {}
        for period in ("historical", "forecast", "historical_08"):
            window = rain_windows.get(period)
            if isinstance(window, Mapping):
                payload["rain_windows"][period] = {
                    key: window[key] for key in window_fields if key in window
                }

    scenario_results = value.get("scenario_results")
    if isinstance(scenario_results, Mapping):
        payload["scenario_results"] = {}
        for scenario in ("dynamic", "forecast", "dynamic_08"):
            result = scenario_results.get(scenario)
            if not isinstance(result, Mapping):
                continue
            item = {key: result[key] for key in ("status", "rain_source_type") if key in result}
            for axis in ("H", "R"):
                candidate = result.get(axis)
                if isinstance(candidate, Mapping):
                    item[axis] = {
                        key: candidate[key] for key in ("status", "grade", "score") if key in candidate
                    }
            payload["scenario_results"][scenario] = item

    raw_provenance = value.get("candidate_provenance")
    if isinstance(raw_provenance, Mapping):
        provenance_fields = (
            "source_kind", "source", "provider", "provider_status", "model", "snapshot_id", "rule_version",
            "data_time", "data_time_semantics", "data_time_status", "valid_time", "valid_time_status",
            "rain_source_types", "is_station_observation", "is_simulated", "expert_approval_evidenced",
            "approval_status", "evaluation_status", "permitted_use", "official_warning_allowed",
        )
        provenance = {key: raw_provenance[key] for key in provenance_fields if key in raw_provenance}
        provenance["permitted_use"] = "候选筛查（不得用于官方预警）"
        provenance["official_warning_allowed"] = False
        candidate_grades = raw_provenance.get("candidate_grades")
        if isinstance(candidate_grades, Mapping):
            provenance["candidate_grades"] = {}
            for scenario in ("dynamic", "forecast", "dynamic_08"):
                grade_set = candidate_grades.get(scenario)
                if not isinstance(grade_set, Mapping):
                    continue
                provenance["candidate_grades"][scenario] = {}
                for axis in ("H", "R"):
                    candidate = grade_set.get(axis)
                    if isinstance(candidate, Mapping):
                        provenance["candidate_grades"][scenario][axis] = {
                            key: candidate[key] for key in ("status", "grade", "score") if key in candidate
                        }
        payload["candidate_provenance"] = provenance

    payload["official_warning_allowed"] = False
    return payload


def _p6_dynamic_snapshot_payload(value: Any) -> dict[str, Any]:
    permitted_use = "候选筛查（不得用于官方预警）"
    if not isinstance(value, Mapping) or not value:
        return {"status": "missing", "permitted_use": permitted_use, "official_warning_allowed": False}

    payload = _p6_dynamic_record(value)
    raw_provenance = value.get("candidate_provenance")
    if isinstance(raw_provenance, Mapping):
        provenance_fields = (
            "source_kind", "source", "provider", "provider_status", "model", "snapshot_id", "rule_version",
            "data_time", "data_time_semantics", "data_time_status", "valid_time", "valid_time_status",
            "rain_source_types", "is_station_observation", "is_simulated", "expert_approval_evidenced",
            "approval_status", "evaluation_status", "permitted_use", "official_warning_allowed",
        )
        payload["candidate_provenance"] = {
            key: raw_provenance[key] for key in provenance_fields if key in raw_provenance
        }
        payload["candidate_provenance"]["permitted_use"] = permitted_use
        payload["candidate_provenance"]["official_warning_allowed"] = False
    for mode in ("dynamic", "forecast", "dynamic_08"):
        if mode not in value:
            continue
        item = value[mode]
        if item is None:
            payload[mode] = None
        elif isinstance(item, Mapping):
            payload[mode] = _p6_dynamic_record(item)
            payload[mode]["permitted_use"] = permitted_use
            payload[mode]["official_warning_allowed"] = False
    payload["permitted_use"] = permitted_use
    payload["official_warning_allowed"] = False
    return payload


def _risk_payload(
    event: Mapping[str, Any], components: Mapping[str, Any], monitoring: Mapping[str, Any]
) -> dict[str, Any]:
    payload = _record(event.get("risk_info"))
    # Keep the bounded A3 summary but avoid duplicating its raw snapshots.
    payload.pop("monitoring_assessment", None)
    p6_dynamic_monitoring = event.get("p6_dynamic_monitoring")
    if not isinstance(p6_dynamic_monitoring, Mapping):
        p6_dynamic_monitoring = payload.get("p6_dynamic_monitoring")
    payload.pop("p6_dynamic_monitoring", None)
    existing_assessments = payload.get("assessments")
    assessments = {
        **(dict(existing_assessments) if isinstance(existing_assessments, Mapping) else {}),
        **dict(components),
    }
    payload["assessments"] = _normalize_missing_assessments(assessments)
    if "dynamic_risk" in event:
        payload["dynamic_risk"] = event["dynamic_risk"]
    monitoring_payload = _record(monitoring)
    if not monitoring_payload:
        monitoring_payload = _record(payload.get("monitoring"))
    if not monitoring_payload:
        monitoring_payload = {"status": "missing"}
    monitoring_payload = _compact_a4_monitoring(monitoring_payload)
    payload["monitoring"] = monitoring_payload
    p6_snapshot = event.get("p6_snapshot")
    if not isinstance(p6_snapshot, Mapping):
        p6_snapshot = payload.get("p6_snapshot")
    if isinstance(p6_snapshot, Mapping):
        payload["p6_snapshot"] = p6_snapshot
    if isinstance(event.get("p6_mapping"), Mapping):
        payload["p6_mapping"] = dict(event["p6_mapping"])
    if "p6_exposure" in event:
        payload["p6_exposure"] = event["p6_exposure"]
    p6_dynamic_snapshot = event.get("p6_dynamic_snapshot")
    if not isinstance(p6_dynamic_snapshot, Mapping):
        p6_dynamic_snapshot = payload.get("p6_dynamic_snapshot")
    payload["p6_dynamic_snapshot"] = _p6_dynamic_snapshot_payload(p6_dynamic_snapshot)
    payload["p6_dynamic_monitoring"] = _p6_dynamic_monitoring_payload(p6_dynamic_monitoring)
    event_facts = _event_facts(event)
    if "p6_mapping" not in event_facts and isinstance(payload.get("p6_mapping"), Mapping):
        event_facts["p6_mapping"] = dict(payload["p6_mapping"])
    merged_event = _record(payload.get("event"))
    merged_event.update(event_facts)
    payload["event"] = merged_event
    return payload


def build_analysis_inputs(
    event: Mapping[str, Any],
    components: Mapping[str, Any],
    monitoring: Mapping[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, str]:
    """Build only the four Start variables from Geo-AI-analyse.yml."""
    task = _task_payload(event)
    chain = event.get("process_chain")
    if chain is None:
        chain = task.get("process_chain")
    risk = _risk_payload(event, components, monitoring)
    risk["evidence"] = _merge_evidence(risk.get("evidence"), evidence)
    risk.setdefault("input_status", {
        "process_chain": "provided_unverified" if chain is not None else "missing",
        "monitoring": risk["monitoring"].get("status", "missing"),
    })
    return {
        "slope_unit_info": _json_text(_slope_payload(event)),
        "task_info": _json_text(task),
        "risk_info": json.dumps(risk, ensure_ascii=False, separators=(",", ":"), default=str),
        "process_chain": _json_text(chain if chain is not None else []),
    }


def build_plan_inputs(
    event: Mapping[str, Any],
    components: Mapping[str, Any],
    monitoring: Mapping[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, str]:
    """Build Start values with the JSON shapes expected by the legacy plan DSL."""
    risk_source = _record(event.get("risk_info"))
    facts = _event_facts(event)
    if "p6_mapping" not in facts and isinstance(risk_source.get("p6_mapping"), Mapping):
        facts["p6_mapping"] = dict(risk_source["p6_mapping"])
    hazard_info = _legacy_records(
        event.get("hazard_info"),
        {"hazard_name", "risk_grade", "stability_status", "stability_trend", "deformation_features", "potential_hazards"},
        ("hazards", "items"),
    )
    raw_monitor_info = event.get("monitor_info")
    if raw_monitor_info is None and isinstance(event.get("monitoring"), Mapping):
        raw_monitor_info = event["monitoring"].get("monitor_points", event["monitoring"].get("monitors"))
    monitor_info = _legacy_records(
        raw_monitor_info,
        {"monitor_name", "responsible_person", "responsible_person_phone"},
        ("monitors", "monitor_points", "items"),
    )
    slope_info = _record(event.get("slope_info"))
    if not slope_info:
        p6_snapshot = event.get("p6_snapshot")
        if not isinstance(p6_snapshot, Mapping):
            p6_snapshot = risk_source.get("p6_snapshot")
        if isinstance(p6_snapshot, Mapping):
            slope_info = _record(p6_snapshot.get("unit_snapshot"))
    if not slope_info:
        slope_info = _record(event.get("slope_unit_info", event.get("slope_unit")))
    if not slope_info:
        slope_info = _slope_payload(event)

    plan_types = _plan_type_values(event.get("plan_types"))
    schemes = event.get("schemes", "")
    expert_opinion = event.get("expert_opinion", "")
    field_report = _record(event.get("field_report"))
    text = event.get("text") or event.get("description") or field_report.get("narrative") or event.get("summary") or (
        "请基于已提供的宜昌事件事实、证据和模型状态整理人工审核建议；"
        "明确缺失信息，不推断四性分值或风险、预警等级，不声称任务已创建或派发。"
    )
    event_facts = dict(facts)
    event_facts.pop("field_report", None)
    evidence_refs = _merge_evidence([], evidence)
    monitoring_payload = _record(monitoring)
    if not monitoring_payload:
        monitoring_payload = _record(risk_source.get("monitoring"))
    if not monitoring_payload:
        monitoring_payload = {"status": "missing"}
    monitoring_payload = _compact_a4_monitoring(monitoring_payload)
    p6_snapshot = event.get("p6_snapshot")
    if not isinstance(p6_snapshot, Mapping):
        p6_snapshot = risk_source.get("p6_snapshot")
    p6_exposure = event.get("p6_exposure")
    if p6_exposure is None:
        p6_exposure = risk_source.get("p6_exposure")
    p6_dynamic_snapshot = event.get("p6_dynamic_snapshot")
    if not isinstance(p6_dynamic_snapshot, Mapping):
        p6_dynamic_snapshot = risk_source.get("p6_dynamic_snapshot")
    review_context = {
        "event": event_facts,
        "is_simulated": event.get("is_simulated"),
        "missing_fields": event.get("missing_fields", []),
        "assessments": _normalize_missing_assessments(components),
        "dynamic_risk": event.get("dynamic_risk"),
        "monitoring": monitoring_payload,
        "p6_snapshot": p6_snapshot,
        "p6_exposure": p6_exposure,
        "p6_dynamic_snapshot": _p6_dynamic_snapshot_payload(p6_dynamic_snapshot),
        "evidence_refs": evidence_refs,
    }
    text = text if isinstance(text, str) else _json_text(text)
    text = f"{text}\n\n【宜昌A4审核上下文（原始状态；缺失项不补值）】\n{_json_text(review_context)}"
    return {
        "text": text,
        "plan_types": _json_text(plan_types),
        "schemes": "" if schemes is None else (schemes if isinstance(schemes, str) else _json_text(schemes)),
        "expert_opinion": "" if expert_opinion is None else (
            expert_opinion if isinstance(expert_opinion, str) else _json_text(expert_opinion)
        ),
        "hazard_info": _json_text(hazard_info),
        "slope_info": _json_text(slope_info),
        "monitor_info": _json_text(monitor_info),
    }


def _a4_field(value: Mapping[str, Any], *aliases: str) -> Any:
    return next((value[key] for key in aliases if key in value), None)


def _a4_has_field(value: Mapping[str, Any], *aliases: str) -> bool:
    return any(key in value for key in aliases)


def _valid_a4_review_record(value: Any, *, require_legacy_fields: bool) -> bool:
    if not isinstance(value, Mapping):
        return False
    has_task = _a4_has_field(value, "task_understanding", "taskUnderstanding")
    has_judgment = _a4_has_field(
        value, "current_judgment", "currentJudgment", "disposal_opinion", "disposalOpinion", "conclusion",
    )
    has_evidence_ids = _a4_has_field(value, "evidence_basis_ids", "evidenceBasisIds", "evidence_ids", "evidenceIds")
    has_missing_fields = _a4_has_field(value, "missing_fields", "missingFields")
    has_model_status = _a4_has_field(value, "model_status", "modelStatus")
    has_review_flag = _a4_has_field(value, "human_review_required", "humanReviewRequired")
    has_actions = _a4_has_field(value, "action_items", "actionItems")
    if not has_judgment or not has_evidence_ids or not has_model_status or not has_review_flag:
        return False
    if require_legacy_fields and not (has_task and has_missing_fields and has_actions):
        return False
    task_understanding = _a4_field(value, "task_understanding", "taskUnderstanding")
    if has_task and not isinstance(task_understanding, str):
        return False
    if not isinstance(_a4_field(
        value, "current_judgment", "currentJudgment", "disposal_opinion", "disposalOpinion", "conclusion",
    ), str):
        return False
    evidence_ids = _a4_field(value, "evidence_basis_ids", "evidenceBasisIds", "evidence_ids", "evidenceIds")
    missing_fields = _a4_field(value, "missing_fields", "missingFields")
    if not isinstance(evidence_ids, list) or not all(isinstance(item, str) for item in evidence_ids):
        return False
    if has_missing_fields and (
        not isinstance(missing_fields, list) or not all(isinstance(item, str) for item in missing_fields)
    ):
        return False
    if not isinstance(_a4_field(value, "human_review_required", "humanReviewRequired"), bool):
        return False
    model_status = _a4_field(value, "model_status", "modelStatus")
    if not isinstance(model_status, (list, Mapping)):
        return False

    model_status_fields = {
        "component", "status", "source", "model", "version", "p6_component_status",
        "calibration_status", "is_simulated", "spatial_unit_id",
    }
    for item in model_status if isinstance(model_status, list) else ():
        if not isinstance(item, Mapping) or not {"component", "status", "source", "model", "version"}.issubset(item):
            return False
        if not set(item).issubset(model_status_fields):
            return False
        if any(not isinstance(item[key], str) for key in ("component", "status", "source", "model", "version")):
            return False
        if any(key in item and not isinstance(item[key], str)
               for key in ("p6_component_status", "calibration_status", "spatial_unit_id")):
            return False
        if "is_simulated" in item and not isinstance(item["is_simulated"], bool):
            return False

    action_items = _a4_field(value, "action_items", "actionItems")
    if has_actions:
        if not isinstance(action_items, list):
            return False
        for item in action_items:
            if (not isinstance(item, Mapping) or not isinstance(item.get("action"), str)
                    or not isinstance(item.get("basis_evidence_ids", []), list)
                    or not all(isinstance(evidence_id, str) for evidence_id in item.get("basis_evidence_ids", []))):
                return False
    elif require_legacy_fields:
        return False
    return True


def _a4_disposal_plan(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    plan = next((value[key] for key in ("DisposalPlan", "disposal_plan", "disposalPlan")
                 if isinstance(value.get(key), Mapping)), value)
    measures = plan.get("measures") if isinstance(plan.get("measures"), Mapping) else plan
    for category in DISPOSAL_MEASURE_CATEGORIES:
        items = measures.get(category)
        if not isinstance(items, list):
            return None
        for item in items:
            if isinstance(item, str):
                continue
            if not isinstance(item, Mapping) or not any(
                isinstance(item.get(key), str) for key in ("action", "measure", "suggestion", "recommendation")
            ):
                return None
            if not isinstance(item.get("basis_evidence_ids", []), list) or not all(
                isinstance(evidence_id, str) for evidence_id in item.get("basis_evidence_ids", [])
            ):
                return None
    return dict(plan)


def _matches_a4_review_contract(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    decision_record = next((value[key] for key in ("DecisionRecord", "decision_record", "decisionRecord")
                            if isinstance(value.get(key), Mapping)), None)
    if decision_record is None:
        return _valid_a4_review_record(value, require_legacy_fields=True)

    disposal_plan = next((value[key] for key in ("DisposalPlan", "disposal_plan", "disposalPlan")
                          if isinstance(value.get(key), Mapping)), None)
    task_proposal = next((value[key] for key in ("TaskProposal", "task_proposal", "taskProposal")
                          if isinstance(value.get(key), Mapping)), None)
    if not _valid_a4_review_record(decision_record, require_legacy_fields=False):
        return False
    if _a4_disposal_plan(disposal_plan) is None:
        return False
    if not isinstance(task_proposal, Mapping):
        return False
    task_aliases = (
        ("responsible_department", "responsibleDepartment", "responsible_unit", "responsibleUnit", "department"),
        ("person", "responsible_person", "responsiblePerson", "assignee"),
        ("location", "detailedAddress"),
        ("due_at", "dueAt", "deadline"),
        ("resources", "resource_requirements"),
        ("completion_criteria", "completionCriteria", "submitRequire"),
    )
    for aliases in task_aliases:
        if not any(key in task_proposal for key in aliases):
            return False
        supplied = next((task_proposal[key] for key in aliases if key in task_proposal), None)
        if aliases[0] != "resources" and supplied is not None and not isinstance(supplied, str):
            return False
    resources = next((task_proposal[key] for key in ("resources", "resource_requirements")
                      if key in task_proposal), None)
    if not isinstance(resources, list):
        return False
    if "basis_evidence_ids" in task_proposal and (
        not isinstance(task_proposal["basis_evidence_ids"], list)
        or not all(isinstance(evidence_id, str) for evidence_id in task_proposal["basis_evidence_ids"])
    ):
        return False
    return True


def _a4_structured_output(value: Any, depth: int = 0) -> dict[str, Any] | None:
    if depth > 5:
        return None
    if isinstance(value, str):
        try:
            return _a4_structured_output(json.loads(value.strip()), depth + 1)
        except (TypeError, ValueError):
            return None
    if not isinstance(value, Mapping):
        return None
    if _matches_a4_review_contract(value):
        return dict(value)
    for key in (
        "answer", "text", "output", "data", "result", "response", "outputs",
        "DecisionRecord", "decision_record", "decisionRecord",
    ):
        if key in value:
            parsed = _a4_structured_output(value[key], depth + 1)
            if parsed is not None:
                return parsed
    return None


def _a4_plan_output(value: Any, depth: int = 0) -> dict[str, Any] | None:
    if depth > 5:
        return None
    if isinstance(value, str):
        try:
            return _a4_plan_output(json.loads(value.strip()), depth + 1)
        except (TypeError, ValueError):
            return None
    if not isinstance(value, Mapping):
        return None
    if _a4_disposal_plan(value) is not None:
        return dict(value)
    for key in ("answer", "text", "output", "data", "result", "response", "outputs"):
        if key in value:
            parsed = _a4_plan_output(value[key], depth + 1)
            if parsed is not None:
                return parsed
    return None


async def _run_workflow(
    agent_key: str,
    workflow_kind: str,
    event: Mapping[str, Any],
    components: Mapping[str, Any],
    monitoring: Mapping[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    app = get_dify_app(agent_key)
    inputs = (
        build_plan_inputs(event, components, monitoring, evidence)
        if workflow_kind == "plan"
        else build_analysis_inputs(event, components, monitoring, evidence)
    )
    configured = dify_configured(agent_key)
    user = str(event.get("correlation_id") or event.get("event_id") or "yichang-a4")
    query = (
        "请基于输入事实和证据整理人工审核建议。保留缺失项与模型状态；不得推断或补造CUV/四性数值、"
        "风险或预警等级、责任人、时限、任务状态。"
    )
    try:
        result = await run_agent(
            agent_key,
            inputs=inputs,
            user=user,
            query=query,
            conversation_id=None,
        )
    except Exception as exc:
        result = {
            "execution_engine": "dify" if configured else "local",
            "status": "error",
            "response": None,
            "outputs": {},
            "error": f"{type(exc).__name__}: {str(exc)[:400]}",
        }

    if not isinstance(result, Mapping):
        result = {}
    status = result.get("status", "unknown")
    raw_response = result.get("response")
    is_plan = workflow_kind == "plan"
    plan_text = raw_response if is_plan and isinstance(raw_response, str) else None
    structured_output = None
    is_a4_analysis = workflow_kind == "analysis"
    completed = str(status).lower() in {"completed", "succeeded", "success"}
    if is_a4_analysis and completed:
        structured_output = _a4_structured_output(result.get("response")) or _a4_structured_output(
            result.get("outputs")
        )
    elif is_plan and completed:
        structured_output = _a4_plan_output(result.get("response")) or _a4_plan_output(result.get("outputs"))
    if is_plan and structured_output is not None:
        output_status = "accepted"
    elif is_plan and plan_text and plan_text.strip():
        output_status = "text_only_review_required"
    elif not is_a4_analysis:
        output_status = "not_used"
    elif structured_output is not None:
        output_status = "accepted"
    elif completed:
        output_status = "unsupported_output"
    elif str(status).lower() in {"error", "failed", "partial_error"}:
        output_status = "execution_failed"
    else:
        output_status = "not_used"
    return {
        "agent_key": agent_key,
        "agent_id": result.get("agent_id", app.agent_id),
        "app_role": result.get("app_role", app.app_role),
        "registry_id": result.get("registry_id", app.registry_id),
        "app_name": result.get("app_name", app.app_name),
        "workflow_kind": workflow_kind,
        "input_fields": list(inputs),
        "configured": configured,
        "execution_engine": result.get("execution_engine", "dify" if configured else "local"),
        "status": status,
        "response": structured_output if is_a4_analysis else raw_response,
        "outputs": {} if is_a4_analysis else result.get("outputs"),
        "raw_response": raw_response,
        "raw_outputs": result.get("outputs"),
        "structured_output": structured_output,
        "output_status": output_status,
        **(
            {
                "plan_text": plan_text,
                "text_only_review_required": bool(plan_text and plan_text.strip()) and structured_output is None,
            }
            if is_plan else {}
        ),
        "trace_id": result.get("trace_id"),
        "task_id": result.get("task_id"),
        "message_id": result.get("message_id"),
        "conversation_id": result.get("conversation_id"),
        "duration_ms": result.get("duration_ms"),
        "error": result.get("error"),
    }


def _disabled_plan(
    event: Mapping[str, Any],
    components: Mapping[str, Any],
    monitoring: Mapping[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    inputs = build_plan_inputs(event, components, monitoring, evidence)
    return {
        "agent_key": "A4_PLAN",
        "agent_id": "A4",
        "app_role": "plan",
        "registry_id": "A4_PLAN",
        "app_name": "A4_PLAN",
        "workflow_kind": "plan",
        "input_fields": list(inputs),
        "configured": False,
        "execution_engine": "disabled",
        "status": "disabled",
        "response": None,
        "outputs": {},
        "raw_response": None,
        "raw_outputs": {},
        "structured_output": None,
        "output_status": "not_used",
        "plan_text": None,
        "text_only_review_required": False,
        "trace_id": None,
        "task_id": None,
        "message_id": None,
        "conversation_id": None,
        "duration_ms": None,
        "error": "A4_PLAN 未配置；执行已禁用，不使用本地 DSL、LLM 或其他回退。",
    }


async def run_a4_workflow(
    event: Mapping[str, Any],
    components: Mapping[str, Any],
    monitoring: Mapping[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    analysis = await _run_workflow("A4", "analysis", event, components, monitoring, evidence)
    plan = (
        await _run_workflow("A4_PLAN", "plan", event, components, monitoring, evidence)
        if dify_configured("A4_PLAN")
        else _disabled_plan(event, components, monitoring, evidence)
    )
    workflows = {"analysis": analysis, "plan": plan}
    statuses = [item["status"] for item in workflows.values()]
    engines = [item["execution_engine"] for item in workflows.values()]
    if any(item == "error" for item in statuses):
        status = "partial_error" if any(item == "completed" for item in statuses) else "error"
    elif all(item == "completed" for item in statuses):
        status = "completed"
    elif any(item == "completed" for item in statuses):
        status = "partial"
    elif any(item == "disabled" for item in statuses):
        status = "disabled"
    elif any(item == "unavailable" for item in statuses):
        status = "unavailable"
    elif all(item == "not_configured" for item in statuses):
        status = "not_configured"
    else:
        status = "unknown"
    execution_engines = set(engines)
    execution_engine = next(iter(execution_engines)) if len(execution_engines) == 1 else "mixed"
    return {
        "agent_id": "A4",
        "execution_engine": execution_engine,
        "status": status,
        "configured": {role: item["configured"] for role, item in workflows.items()},
        "workflows": workflows,
    }
