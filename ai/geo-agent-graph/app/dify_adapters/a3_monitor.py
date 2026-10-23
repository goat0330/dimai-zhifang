"""Optional Dify explanation for deterministic Yichang monitoring results."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.dify_client import run_agent
from app.p6_client import lookup_dynamic_slope_unit, lookup_slope_unit
from app.yichang_monitor import GoldMonitoringAdapter, compact_monitoring_evidence


_TREND_AGENT_ID = "A3"
_ALERT_AGENT_ID = "A3_ALERT"
_DEFAULT_USER = "geo-guard-a3-monitor"


def _rainfall_window_aggregations(monitoring: Mapping[str, Any]) -> dict[str, Any]:
    compact = compact_monitoring_evidence(monitoring)
    validation = compact.get("validation") if isinstance(compact.get("validation"), Mapping) else {}
    windows = validation.get("rainfall_windows") if isinstance(validation.get("rainfall_windows"), Mapping) else {}
    result: dict[str, Any] = {}
    for metric in ("rainfall_24h_mm", "rainfall_3d_mm", "rainfall_7d_mm"):
        window = windows.get(metric) if isinstance(windows.get(metric), Mapping) else {}
        aggregation = window.get("aggregation")
        result[metric] = aggregation if isinstance(aggregation, Mapping) else {
            "status": "unavailable", "total_mm": None,
        }
    return result


def _readable_evidence(result: Mapping[str, Any], monitoring: Mapping[str, Any]) -> str:
    validation = monitoring.get("validation") if isinstance(monitoring.get("validation"), Mapping) else {}
    metrics = validation.get("metrics") if isinstance(validation.get("metrics"), Mapping) else {}
    windows = validation.get("rainfall_windows") if isinstance(validation.get("rainfall_windows"), Mapping) else {}
    series = monitoring.get("series") if isinstance(monitoring.get("series"), list) else []
    latest = series[-1] if series and isinstance(series[-1], Mapping) else {}
    lines = [
        f"数据来源：{result.get('data_source') or '缺失'}；类型："
        f"{'Gold模拟回归' if result.get('is_simulated') is True else '真实监测输入'}"
        f"（is_simulated={result.get('is_simulated') is True}）。",
        f"模型版本：{result.get('model_version') or '未提供'}；观测记录数：{len(series)}。",
    ]
    for metric, label, hours in (
        ("rainfall_24h_mm", "24小时降雨", 24),
        ("rainfall_3d_mm", "3日降雨", 72),
        ("rainfall_7d_mm", "7日降雨", 168),
    ):
        check = windows.get(metric) if isinstance(windows.get(metric), Mapping) else {}
        value = latest.get(metric)
        lines.append(
            f"{label}（{hours}小时，mm）：{value if value is not None else '缺失'}；数据校验={check.get('status', 'missing')}。"
        )
        aggregation = check.get("aggregation") if isinstance(check.get("aggregation"), Mapping) else {}
        coverage = aggregation.get("coverage") if isinstance(aggregation.get("coverage"), Mapping) else {}
        aggregate_value = aggregation.get("total_mm")
        lines.append(
            f"{label}逐时段聚合：状态={aggregation.get('status', 'unavailable')}；"
            f"累计={aggregate_value if aggregate_value is not None else '缺失'} mm；"
            f"覆盖={coverage.get('status', 'unknown')} ({coverage.get('fraction', 'unknown')})；"
            f"窗口={aggregation.get('window_start', '缺失')} 至 {aggregation.get('window_end', '缺失')}。"
        )
    for metric, label, unit in (
        ("displacement_mm", "位移", "mm"),
        ("displacement_rate_mm_per_day", "位移速率", "mm/d"),
        ("reservoir_level_m", "库水位", "m"),
    ):
        check = metrics.get(metric) if isinstance(metrics.get(metric), Mapping) else {}
        value = latest.get(metric)
        lines.append(
            f"{label}（{unit}）：{value if value is not None else '缺失'}；数据校验={check.get('status', 'missing')}。"
        )
    identity = validation.get("object_identity") if isinstance(validation.get("object_identity"), Mapping) else {}
    association = validation.get("displacement_reservoir_association") \
        if isinstance(validation.get("displacement_reservoir_association"), Mapping) else {}
    rules = monitoring.get("triggered_rules") if isinstance(monitoring.get("triggered_rules"), list) else []
    matched = "；".join(
        f"{item.get('metric')} {item.get('operator')} {item.get('threshold')}（观测值 {item.get('observed_value')}）"
        for item in rules if isinstance(item, Mapping)
    ) or "无"
    recovery = monitoring.get("recovery_stage") or "缺失"
    dynamic_risk = result.get("dynamic_risk") if isinstance(result.get("dynamic_risk"), Mapping) else {}
    p6_dynamic = result.get("p6_dynamic_monitoring") if isinstance(result.get("p6_dynamic_monitoring"), Mapping) else {}
    p6_snapshot = result.get("p6_snapshot") if isinstance(result.get("p6_snapshot"), Mapping) else {}
    p6_provenance = result.get("p6_snapshot_provenance") \
        if isinstance(result.get("p6_snapshot_provenance"), Mapping) else {}
    p6_mode = p6_provenance.get("source_mode") or "未提供"
    if p6_provenance.get("source_mode") == "historical_replay":
        p6_mode = "historical_replay（历史回放，非实时）"
    warning_allowed = p6_provenance.get("official_warning_allowed")
    warning_allowed_label = "未提供" if warning_allowed is None else str(warning_allowed).lower()
    lines.extend((
        f"对象ID校验：{identity.get('status', 'missing')}；位移/库水位关联：{association.get('status', 'missing')}。",
        f"恢复状态：{recovery}；A3正式动态风险：{dynamic_risk.get('status', 'unavailable')}。",
        f"P6快照来源模式：{p6_mode}；官方预警允许：{warning_allowed_label}。",
    ))
    if result.get("is_simulated") is True:
        lines.append(f"Gold回归规则命中：{matched}；仅用于模拟回归，不代表官方预警阈值。")
    else:
        lines.append(f"真实监测阈值判断：{monitoring.get('status', 'missing')}；未据此生成正式预警。")
    if p6_dynamic.get("status") == "candidate_available":
        rain_source = p6_dynamic.get("rain_source") or "来源缺失"
        model = p6_dynamic.get("model") or "模型缺失"
        scenarios = p6_dynamic.get("scenario_results") if isinstance(p6_dynamic.get("scenario_results"), Mapping) else {}
        forecast = scenarios.get("forecast") if isinstance(scenarios.get("forecast"), Mapping) else {}
        dynamic_08 = scenarios.get("dynamic_08") if isinstance(scenarios.get("dynamic_08"), Mapping) else {}
        forecast_h = forecast.get("H") if isinstance(forecast.get("H"), Mapping) else {}
        forecast_r = forecast.get("R") if isinstance(forecast.get("R"), Mapping) else {}
        dynamic_08_h = dynamic_08.get("H") if isinstance(dynamic_08.get("H"), Mapping) else {}
        dynamic_08_r = dynamic_08.get("R") if isinstance(dynamic_08.get("R"), Mapping) else {}
        lines.append(
            f"P6动态筛查候选（{rain_source} {model}模型降雨场，非雨量站实测、非官方预警）："
            f"H={p6_dynamic.get('h_candidate_grade') or '缺失'}，"
            f"R={p6_dynamic.get('r_candidate_grade') or '缺失'}；"
            f"as_of={p6_dynamic.get('as_of') or '缺失'}，"
            f"rain_status={p6_dynamic.get('rain_status') or '缺失'}，"
            f"mapping={p6_dynamic.get('rain_mapping_status') or '缺失'}，"
            f"distance_km={p6_dynamic.get('rain_mapping_distance_km') if p6_dynamic.get('rain_mapping_distance_km') is not None else '缺失'}；"
            f"forecast H/R={forecast_h.get('grade') or '缺失'}/{forecast_r.get('grade') or '缺失'}；"
            f"dynamic_08 H/R={dynamic_08_h.get('grade') or '缺失'}/{dynamic_08_r.get('grade') or '缺失'}。"
        )
    else:
        lines.append(f"P6动态H/R候选：{p6_dynamic.get('status', 'unavailable')}；{p6_dynamic.get('reason', '缺失映射或服务不可用')}。")
    return "\n".join(lines)


def _query(result: Mapping[str, Any], *, agent_id: str) -> str:
    monitoring = result.get("monitoring") if isinstance(result.get("monitoring"), Mapping) else {}
    event = result.get("event") if isinstance(result.get("event"), Mapping) else {}
    p6 = result.get("p6_dynamic_monitoring") if isinstance(result.get("p6_dynamic_monitoring"), Mapping) else {}
    p6_snapshot = result.get("p6_snapshot") if isinstance(result.get("p6_snapshot"), Mapping) else {}
    is_alert = agent_id == _ALERT_AGENT_ID
    compact_monitoring = compact_monitoring_evidence(monitoring)
    observations = compact_monitoring.get("series") if isinstance(compact_monitoring.get("series"), list) else []
    context = {
        "purpose": "gold_alert_candidate_explanation" if is_alert else "monitoring_trend_evidence_explanation",
        "monitoring_assessment": result.get("monitoring_assessment"),
        "source_kind": result.get("source_kind"),
        "data_source": result.get("data_source"),
        "is_simulated": result.get("is_simulated") is True,
        "event_status": result.get("event_status"),
        "event_id": event.get("event_id"),
        "scenario_id": event.get("scenario_id"),
        "stage_id": event.get("stage_id"),
        "lineage_key": event.get("lineage_key"),
        "parent_scenario_id": event.get("parent_scenario_id"),
        "event_type": event.get("event_type"),
        "result_provenance": result.get("result_provenance"),
        "model_version": result.get("model_version"),
        "readable_evidence": _readable_evidence(result, monitoring),
        "metric_availability": monitoring.get("metric_availability", {}),
        "validation": compact_monitoring.get("validation", {}),
        "rainfall_window_aggregations": _rainfall_window_aggregations(monitoring),
        "observation_count": compact_monitoring.get("observation_count", len(observations)),
        "observations": observations[-8:],
        "observation_sample_scope": "latest_8_only; full rainfall window totals and trigger evidence are supplied separately",
        "trigger_rule": monitoring.get("trigger_rule", {}),
        "triggered_rules": monitoring.get("triggered_rules", []),
        "recovery_detected": monitoring.get("recovery_detected"),
        "recovery_stage": monitoring.get("recovery_stage"),
        "dynamic_risk_status": (result.get("dynamic_risk") or {}).get("status"),
        "p6_dynamic_monitoring": result.get("p6_dynamic_monitoring"),
        "p6_dynamic_snapshot": result.get("p6_dynamic_snapshot"),
        "p6_recalculation_status": p6.get("recalculation_status", "unavailable"),
        "p6_snapshot_status": p6_snapshot.get("status"),
        "p6_unit_snapshot": p6_snapshot.get("unit_snapshot"),
        "p6_info_snapshot": p6_snapshot.get("info_snapshot"),
        "p6_snapshot_provenance": result.get("p6_snapshot_provenance"),
        "p6_parameter_version": result.get("p6_parameter_version"),
        "formal_warning_created": False,
    }
    instructions = (
        "请只组织并解释下列 Gold 阈值触发证据，输出只能作为待人工复核的告警候选说明；"
        "不得创建正式预警、补造预警等级、套用官方阈值或改变任务状态。"
        if is_alert else
        "请只组织并解释下列监测证据。不得补造观测值、趋势预测、风险/预警等级或官方阈值。"
    )
    return (
        instructions + "缺失字段保持缺失。is_simulated=true 时必须明确说明这是 Gold 模拟回归数据；"
        "P6 source_mode=historical_replay 表示历史回放而非实时数据；official_warning_allowed=false 时不得创建正式预警。"
        "恢复观察仅供人工复核，不得据此结案或创建正式预警。\n"
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )


async def explain_monitoring_result(
    result: Mapping[str, Any],
    *,
    agent_id: str = _TREND_AGENT_ID,
    user: str = _DEFAULT_USER,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Call one optional Dify app and retain its engine, registry role, and status."""
    response = await run_agent(
        agent_id,
        inputs={},
        user=user,
        query=_query(result, agent_id=agent_id),
        conversation_id=conversation_id,
    )
    return {
        "agent_id": response.get("agent_id", "A3"),
        "registry_id": response.get("registry_id", agent_id),
        "app_role": response.get("app_role", "alert" if agent_id == _ALERT_AGENT_ID else "primary"),
        "execution_engine": response.get("execution_engine", "unknown"),
        "status": response.get("status", "error"),
        "purpose": "alert_candidate_explanation" if agent_id == _ALERT_AGENT_ID else "evidence_explanation_only",
        "is_simulated": result.get("is_simulated") is True,
        "response": response,
    }


async def process_monitoring_with_dify(
    value: Any,
    *,
    user: str = _DEFAULT_USER,
    conversation_id: str | None = None,
    execute_dify: bool = True,
) -> dict[str, Any]:
    """Validate locally, query P6 metadata when applicable, then optionally explain with Dify."""
    result = GoldMonitoringAdapter().process(value)
    await _attach_p6_snapshot(result, value)
    monitoring_not_connected = result["monitoring"]["status"] == "not_connected"
    p6_candidate_available = result["p6_dynamic_monitoring"].get("status") == "candidate_available"
    if not execute_dify:
        explanation = _skipped_result(_TREND_AGENT_ID, "deferred_to_phase2", result["is_simulated"])
        alert = _skipped_result(_ALERT_AGENT_ID, "deferred_to_phase2", result["is_simulated"])
    elif result["monitoring"]["status"] in {"missing", "not_connected"} and not (
        monitoring_not_connected and p6_candidate_available
    ):
        status = "skipped_real_monitoring_not_connected" if result["monitoring"]["status"] == "not_connected" \
            else "skipped_missing_input"
        explanation = _skipped_result(_TREND_AGENT_ID, status, result["is_simulated"])
        alert = _skipped_result(_ALERT_AGENT_ID, status, result["is_simulated"])
    else:
        explanation = await explain_monitoring_result(
            result, agent_id=_TREND_AGENT_ID, user=user, conversation_id=conversation_id,
        )
        if monitoring_not_connected:
            alert = _skipped_result(
                _ALERT_AGENT_ID, "skipped_real_monitoring_not_connected", result["is_simulated"],
            )
        elif result["status"] == "triggered":
            alert = await explain_monitoring_result(
                result, agent_id=_ALERT_AGENT_ID, user=user, conversation_id=conversation_id,
            )
        else:
            alert = _skipped_result(_ALERT_AGENT_ID, "skipped_no_threshold_trigger", result["is_simulated"])
    result["explanation"] = explanation
    result["alert"] = alert
    p6_recalculation_trace = next(
        (step for step in result["trace"] if step.get("step") == "recalculate_p6_dynamic_hr"),
        None,
    )
    if p6_recalculation_trace is not None:
        p6_recalculation_trace.update(
            status="not_performed",
            availability=result["p6_dynamic_monitoring"]["status"],
            snapshot_status=result["p6_dynamic_monitoring"].get("query_status"),
            reason="A3只读取P6已计算的动态筛查快照，不在本地重算H/R。",
        )
    result["trace"].extend((
        {
            "step": "prepare_a3_workflow_input",
            "status": "prepared" if explanation["status"] not in {
                "skipped_missing_input", "skipped_real_monitoring_not_connected",
            } else "skipped",
            "input_channel": "sys.query",
            "inputs": {},
            "mapped_fields": [
                "source_kind",
                "data_source",
                "is_simulated",
                "event_status",
                "event.event_id",
                "event.scenario_id",
                "event.stage_id",
                "event.lineage_key",
                "event.parent_scenario_id",
                "monitoring_assessment",
                "monitoring.validation.rainfall_windows.*.aggregation",
                "monitoring.metric_availability",
                "monitoring.series",
                "p6_snapshot.unit_snapshot",
                "p6_snapshot.info_snapshot",
                "p6_snapshot_provenance",
                "p6_dynamic_monitoring",
                "p6_dynamic_snapshot",
            ],
            "skip_reason": explanation["status"] if explanation["status"].startswith("skipped_") else None,
        },
        {
            "step": "query_p6_unit_snapshot",
            "status": result["p6_snapshot_provenance"]["status"],
            "snapshot_status": result["p6_snapshot_provenance"]["status"],
            "dynamic_monitoring_status": result["p6_dynamic_monitoring"]["status"],
        },
        {
            "step": "query_p6_dynamic_snapshot",
            "status": result["p6_dynamic_api_response"].get("status", "missing_mapping")
            if isinstance(result.get("p6_dynamic_api_response"), Mapping) else "not_requested",
            "dynamic_monitoring_status": result["p6_dynamic_monitoring"]["status"],
            "snapshot_id": result["p6_dynamic_monitoring"].get("snapshot_id"),
            "rule_version": result["p6_dynamic_monitoring"].get("rule_version"),
        },
        {
            "step": "organize_monitoring_trend_explanation",
            "status": explanation["status"],
            "execution_engine": explanation["execution_engine"],
            "registry_id": explanation["registry_id"],
            "purpose": explanation["purpose"],
            "trend_prediction_model_status": result["result_provenance"].get("trend_prediction_model", "not_connected"),
        },
        {
            "step": "organize_monitoring_alert_candidate",
            "status": alert["status"],
            "execution_engine": alert["execution_engine"],
            "registry_id": alert["registry_id"],
        },
    ))
    return result


def _source_p6_mapping(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    event = value.get("event") if isinstance(value.get("event"), Mapping) else {}
    mapping = value.get("p6_mapping") or event.get("p6_mapping")
    return mapping if isinstance(mapping, Mapping) else None


def _mapped_p6_slope_unit_id(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    event = value.get("event") if isinstance(value.get("event"), Mapping) else {}
    mapping = _source_p6_mapping(value) or {}
    mapped_id = value.get("p6_slope_unit_id") or event.get("p6_slope_unit_id") or mapping.get("p6_slope_unit_id")
    return str(mapped_id).strip() if mapped_id not in (None, "") else None


def _p6_query_options(value: Any) -> tuple[str, str | None]:
    if not isinstance(value, Mapping):
        return "dynamic", None
    event = value.get("event") if isinstance(value.get("event"), Mapping) else {}
    scenario = value.get("p6_scenario") or event.get("p6_scenario") or "dynamic"
    snapshot_id = value.get("p6_snapshot_id") or event.get("p6_snapshot_id")
    scenario = str(scenario).strip() or "dynamic"
    snapshot_id = str(snapshot_id).strip() if snapshot_id not in (None, "") else None
    return scenario, snapshot_id


async def _attach_p6_snapshot(result: dict[str, Any], input_value: Any) -> None:
    mapped_slope_unit_id = _mapped_p6_slope_unit_id(input_value)
    requested_scenario, requested_snapshot_id = _p6_query_options(input_value)
    result["p6_snapshot"] = None
    result["p6_dynamic_snapshot"] = None
    result["p6_dynamic_api_response"] = None
    result["p6_snapshot_provenance"] = {
        "status": "missing_mapping" if not mapped_slope_unit_id else "not_requested",
        "source": "P6 read-only static candidate snapshot",
        "slope_unit_id": mapped_slope_unit_id,
        "source_mode": None,
        "parameter_version": None,
        "official_warning_allowed": None,
        "unit_status": None,
        "info_status": None,
    }
    dynamic = result["p6_dynamic_monitoring"]
    dynamic.update(
        status="unavailable",
        source="P6 ECMWF IFS dynamic H/R screening candidate",
        result_type="p6_dynamic_screening_candidate",
        scenario=requested_scenario,
        p6_slope_unit_id=mapped_slope_unit_id,
        is_simulated_sensor_data=result["is_simulated"] is True,
        official_warning_allowed=False,
        recalculation_status="not_performed",
        mapping_status="provided" if mapped_slope_unit_id else "missing",
        query_status="not_requested",
    )
    static_lookup_id = mapped_slope_unit_id
    snapshot = await lookup_slope_unit(static_lookup_id) if static_lookup_id else {
        "status": "missing_mapping", "reason": "missing_p6_slope_unit_id",
    }
    result["p6_snapshot"] = snapshot
    provenance = result["p6_snapshot_provenance"]
    provenance["slope_unit_id"] = static_lookup_id
    provenance["status"] = snapshot.get("status", "error")
    for key in ("unit_status", "info_status"):
        if key in snapshot:
            provenance[key] = snapshot[key]
    result["result_provenance"]["p6_query_status"] = snapshot.get("status", "error")
    unit = snapshot.get("unit_snapshot") if isinstance(snapshot.get("unit_snapshot"), Mapping) else {}
    info = snapshot.get("info_snapshot") if isinstance(snapshot.get("info_snapshot"), Mapping) else {}
    for key in ("source_mode", "parameter_version", "official_warning_allowed", "evaluation_status", "permitted_use"):
        if key in info:
            provenance[key] = info[key]
    returned_id = unit.get("slope_unit_id")
    if returned_id not in (None, ""):
        result["validation"]["p6_object_id"] = {
            "status": "matched" if str(returned_id).strip().casefold() == str(static_lookup_id).strip().casefold() else "mismatch",
            "requested_id": static_lookup_id,
            "returned_id": returned_id,
        }
    parameter_version = info.get("parameter_version")
    if parameter_version not in (None, ""):
        result["p6_parameter_version"] = parameter_version
        result["result_provenance"]["p6_parameter_version"] = parameter_version
    if "source_mode" in provenance:
        result["result_provenance"]["p6_source_mode"] = provenance["source_mode"]
    if "official_warning_allowed" in provenance:
        result["result_provenance"]["p6_official_warning_allowed"] = provenance["official_warning_allowed"]

    dynamic_snapshot = await lookup_dynamic_slope_unit(
        mapped_slope_unit_id, scenario=requested_scenario, snapshot_id=requested_snapshot_id,
    ) if mapped_slope_unit_id else {
        "status": "missing_mapping", "reason": "missing_p6_slope_unit_id", "scenario": requested_scenario,
    }
    result["p6_dynamic_api_response"] = dynamic_snapshot
    dynamic_status = dynamic_snapshot.get("status", "unavailable")
    result["result_provenance"]["p6_dynamic_query_status"] = dynamic_status
    if dynamic_status == "completed":
        latest = dynamic_snapshot.get("latest_snapshot") if isinstance(dynamic_snapshot.get("latest_snapshot"), Mapping) else {}
        selected = dynamic_snapshot.get("selected_snapshot") if isinstance(dynamic_snapshot.get("selected_snapshot"), Mapping) else {}
        unit_snapshot = dynamic_snapshot.get("unit_snapshot") if isinstance(dynamic_snapshot.get("unit_snapshot"), Mapping) else {}
        if requested_snapshot_id:
            snapshot_metadata = selected or unit_snapshot
        else:
            snapshot_metadata = latest or selected or unit_snapshot
        item = dynamic_snapshot.get("item") if isinstance(dynamic_snapshot.get("item"), Mapping) else {}
        status_snapshot = dynamic_snapshot.get("service_status") if isinstance(dynamic_snapshot.get("service_status"), Mapping) else {}
        historical_type = snapshot_metadata.get("historical_type") or item.get("rain_past_type")
        forecast_type = snapshot_metadata.get("forecast_type") or item.get("rain_forecast_type")
        scenario_fields = {
            "dynamic": ("h_dynamic_grade", "h_dynamic_score", "r_dynamic_grade", "r_dynamic_score", historical_type),
            "forecast": ("h_forecast_grade", "h_forecast_score", "r_forecast_grade", "r_forecast_score", forecast_type),
            "dynamic_08": ("h_dynamic_08_grade", "h_dynamic_08_score", "r_dynamic_08_grade", "r_dynamic_08_score", historical_type),
        }
        scenario_results: dict[str, dict[str, Any]] = {}
        for scenario_name, (h_grade_key, h_score_key, r_grade_key, r_score_key, rain_source_type) in scenario_fields.items():
            h_grade, r_grade = item.get(h_grade_key), item.get(r_grade_key)
            scenario_results[scenario_name] = {
                "status": "candidate_available" if h_grade is not None and r_grade is not None else
                "partial" if h_grade is not None or r_grade is not None else "missing",
                "rain_source_type": rain_source_type,
                "H": {"status": "candidate" if h_grade is not None else "missing", "grade": h_grade, "score": item.get(h_score_key)},
                "R": {"status": "candidate" if r_grade is not None else "missing", "grade": r_grade, "score": item.get(r_score_key)},
            }
        rain_windows = {
            "historical": {
                "source_type": historical_type,
                "status": item.get("rain_past_status"),
                "24h_mm": item.get("rain_past24h_mm"),
                "72h_mm": item.get("rain_past72h_mm"),
                "168h_mm": item.get("rain_past168h_mm"),
            },
            "forecast": {
                "source_type": forecast_type,
                "status": item.get("rain_forecast_status"),
                "24h_mm": item.get("rain_forecast24h_mm"),
                "72h_mm": item.get("rain_forecast72h_mm"),
            },
            "historical_08": {
                "source_type": historical_type,
                "status": item.get("rain_past_status"),
                "24h_mm": item.get("rain_past24h_08_mm"),
                "72h_mm": item.get("rain_past72h_08_mm"),
                "168h_mm": item.get("rain_past168h_08_mm"),
            },
        }
        selected_scenario_result = scenario_results.get(requested_scenario) or {}
        selected_h = selected_scenario_result.get("H") if isinstance(selected_scenario_result.get("H"), Mapping) else {}
        selected_r = selected_scenario_result.get("R") if isinstance(selected_scenario_result.get("R"), Mapping) else {}
        dynamic.update(
            status="candidate_available",
            query_status="completed",
            unit_mapping_status="matched",
            scenario=requested_scenario,
            snapshot_id=dynamic_snapshot.get("snapshot_id"),
            rule_version=snapshot_metadata.get("rule_version") or unit_snapshot.get("rule_version"),
            as_of=snapshot_metadata.get("as_of_local") or unit_snapshot.get("as_of_local"),
            model=snapshot_metadata.get("model") or unit_snapshot.get("model") or status_snapshot.get("model"),
            rain_source=snapshot_metadata.get("provider") or snapshot_metadata.get("rain_source"),
            historical_type=historical_type,
            forecast_type=forecast_type,
            unit_count=status_snapshot.get("unit_count") or snapshot_metadata.get("unit_count"),
            rain_status=item.get("rain_status"),
            rain_mapping_status=item.get("rain_mapping_status"),
            rain_mapping_distance_km=item.get("rain_mapping_distance_km"),
            rain_grid_id=item.get("rain_grid_id"),
            rain_windows=rain_windows,
            h_candidate_grade=selected_h.get("grade"),
            r_candidate_grade=selected_r.get("grade"),
            scenario_results=scenario_results,
            reason="P6 ECMWF IFS H/R动态筛查候选；模型降雨场不是雨量站实测，结果不是官方预警。",
        )
        raw_candidate_provenance = dynamic_snapshot.get("candidate_provenance")
        candidate_provenance = None
        if isinstance(raw_candidate_provenance, Mapping):
            candidate_provenance = {
                **raw_candidate_provenance,
                "candidate_grades": {
                    scenario_name: {
                        axis: scenario_results[scenario_name][axis]
                        for axis in ("H", "R")
                    }
                    for scenario_name in ("dynamic", "forecast", "dynamic_08")
                },
            }
            dynamic["candidate_provenance"] = candidate_provenance
        result["p6_dynamic_snapshot"] = {
            "status": "candidate_available",
            "execution_engine": "p6_dynamic_query_api",
            "source": f"{dynamic['rain_source'] or 'P6'}模型降雨场（{dynamic['model'] or '模型缺失'}；非雨量站实测）",
            "rain_source": dynamic["rain_source"],
            "snapshot_id": dynamic["snapshot_id"],
            "as_of_local": dynamic["as_of"],
            "scenario": requested_scenario,
            "model": dynamic["model"],
            "rule_version": dynamic["rule_version"],
            "slope_unit_id": mapped_slope_unit_id,
            "rain_status": dynamic["rain_status"],
            "rain_source_type": selected_scenario_result.get("rain_source_type"),
            "rain_source_types": [value for value in (dynamic["historical_type"], dynamic["forecast_type"]) if value],
            "rain_mapping_status": dynamic["rain_mapping_status"],
            "rain_distance_km": dynamic["rain_mapping_distance_km"],
            "rain_grid_id": dynamic["rain_grid_id"],
            "rain_windows": rain_windows,
            "dynamic": scenario_results["dynamic"],
            "forecast": scenario_results["forecast"],
            "dynamic_08": scenario_results["dynamic_08"],
            "permitted_use": "候选筛查（不得用于官方预警）",
        }
        if candidate_provenance is not None:
            result["p6_dynamic_snapshot"]["candidate_provenance"] = candidate_provenance
        result["result_provenance"].update(
            p6_dynamic_snapshot_id=dynamic["snapshot_id"],
            p6_dynamic_rule_version=dynamic["rule_version"],
            p6_dynamic_model=dynamic["model"],
        )
    else:
        missing_mapping = dynamic_status == "missing_mapping"
        mapping_missing_in_snapshot = dynamic_status == "mapping_missing"
        dynamic.update(
            status="skipped" if dynamic_status == "skipped" else "unavailable",
            query_status=dynamic_status,
            mapping_status=("missing" if missing_mapping else
                            "missing_in_snapshot" if mapping_missing_in_snapshot else
                            "invalid" if dynamic_status == "skipped" else dynamic.get("mapping_status")),
            reason=(
                "缺少明确的 P6 YCSU 映射，未查询动态 H/R。"
                if missing_mapping else
                f"指定 P6 时片未包含该单元：{dynamic_snapshot.get('reason') or 'unit not present in snapshot'}"
                if mapping_missing_in_snapshot else
                dynamic_snapshot.get("reason") or "P6动态H/R候选查询不可用。"
            ),
        )
        result["p6_dynamic_snapshot"] = {
            "status": "skipped" if dynamic_status == "skipped" else "unavailable",
            "execution_engine": "p6_dynamic_query_api",
            "source": "P6 ECMWF IFS dynamic H/R screening candidate",
            "scenario": requested_scenario,
            "slope_unit_id": mapped_slope_unit_id,
            "reason": dynamic["reason"],
            "mapping_status": dynamic["mapping_status"],
            "permitted_use": "候选筛查（不得用于官方预警）",
        }
    result["dynamic_risk"]["reason"] = (
        "A3未生成正式动态风险等级；P6 H/R仅作为独立的动态筛查候选提供。"
        if dynamic_status == "completed" else
        f"A3未生成正式动态风险等级；P6动态H/R候选不可用：{dynamic.get('reason', '未提供明确映射')}"
    )
    assessment = result.get("monitoring_assessment")
    if isinstance(assessment, dict):
        model_status = assessment.get("model_status")
        if isinstance(model_status, dict):
            model_status.update(
                dynamic_risk=result["dynamic_risk"],
                p6_snapshot_provenance=provenance,
                p6_dynamic_monitoring=dynamic,
                p6_dynamic_snapshot=result["p6_dynamic_snapshot"],
            )
    for step in result["trace"]:
        if step.get("step") == "calculate_dynamic_risk":
            step["reason"] = result["dynamic_risk"]["reason"]
    event = result.get("event")
    if isinstance(event, dict):
        p6_mapping = _source_p6_mapping(input_value)
        input_event = input_value.get("event") if isinstance(input_value, Mapping) and isinstance(
            input_value.get("event"), Mapping,
        ) else {}
        event_context = {}
        if mapped_slope_unit_id:
            event_context["p6_slope_unit_id"] = mapped_slope_unit_id
        for key in (
            "spatial_ref_status", "spatial_object_source", "geometry_status",
            "monitor_to_hazard_link_status", "monitor_to_hazard_link_source", "parent_correlation_id",
        ):
            value = input_value.get(key) if isinstance(input_value, Mapping) else None
            if value is None:
                value = input_event.get(key)
            if value is not None:
                event_context[key] = value
        event.update(
            p6_snapshot=snapshot,
            p6_snapshot_status=snapshot.get("status", "error"),
            p6_snapshot_provenance=provenance,
            p6_dynamic_snapshot=result["p6_dynamic_snapshot"],
            p6_dynamic_monitoring=dynamic,
            monitoring_assessment=assessment,
            validation=result["validation"],
        )
        event.update(event_context)
        if p6_mapping is not None:
            event["p6_mapping"] = dict(p6_mapping)
        risk_info = event.get("risk_info")
        risk_info = dict(risk_info) if isinstance(risk_info, Mapping) else {}
        risk_event = risk_info.get("event")
        risk_event = dict(risk_event) if isinstance(risk_event, Mapping) else {}
        risk_event.update(event_context)
        if risk_event:
            risk_info["event"] = risk_event
        risk_info.update(
            result_provenance=result["result_provenance"],
            p6_snapshot=snapshot,
            p6_snapshot_provenance=provenance,
            p6_dynamic_snapshot=result["p6_dynamic_snapshot"],
            p6_dynamic_monitoring=dynamic,
            monitoring_assessment=assessment,
        )
        if p6_mapping is not None:
            risk_info["p6_mapping"] = dict(p6_mapping)
        event["risk_info"] = risk_info


def _skipped_result(agent_id: str, status: str, is_simulated: bool) -> dict[str, Any]:
    return {
        "agent_id": "A3",
        "registry_id": agent_id,
        "app_role": "alert" if agent_id == _ALERT_AGENT_ID else "primary",
        "execution_engine": "local",
        "status": status,
        "purpose": "alert_candidate_explanation" if agent_id == _ALERT_AGENT_ID else "evidence_explanation_only",
        "is_simulated": is_simulated,
        "response": None,
    }
