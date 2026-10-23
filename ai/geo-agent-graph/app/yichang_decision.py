"""Yichang A4 decision adapter: evidence-backed review, not a risk model."""

import json
import re
from collections.abc import Mapping
from typing import Any

from .dify_adapters.a4_decision import DISPOSAL_MEASURE_CATEGORIES, is_simulated_evidence, run_a4_workflow
from .llm import build_llm, llm_enabled
from .p6_client import lookup_dynamic_slope_unit, lookup_slope_unit


COMPONENTS = ("rf_static_susceptibility", "dynamic_hazard", "vulnerability", "risk")
_P6_COMPONENTS = {
    "S": "rf_static_susceptibility",
    "H": "dynamic_hazard",
    "V": "vulnerability",
    "R": "risk",
}
_SIMULATED_DISPOSAL_FALLBACKS = {
    "人员安置": (
        "先核实坐标及实际受威胁对象；如确认人员处于影响范围，再由属地责任人员研判是否安置。"
        "当前建议不构成转移决定。"
    ),
    "警示防护": (
        "现场记录如涉及疑似张裂，应先核实点位和迹象；由属地人员研判是否需要临时警示。"
        "此建议不形成预警等级或正式预警。"
    ),
    "监测巡查": (
        "待核准坐标后复核现场记录中的疑似张裂、变化及受威胁对象，并记录核查过程；"
        "现有材料不提供专业监测结论。"
    ),
    "排危除险": (
        "目前未提供专业排危意见；如现场复核确认存在需处置隐患，再由专业人员评估排危必要性，"
        "当前不构成排危决定或实施指令。"
    ),
    "工程治理": (
        "目前未提供工程治理意见；待点位、裂缝和受威胁对象核实后，由专业人员评估方案必要性，"
        "当前不构成治理决定。"
    ),
    "宣传告知": (
        "核实点位和受影响对象后，再向相关人员说明已核实事实和未确认事项；"
        "不发布未经确认的预警等级或避险指令。"
    ),
    "交通管制": (
        "先核准坐标并评估道路受影响对象；如核查发现交通风险，再由有权主体按职责研判是否实施交通管制，"
        "当前不构成管制决定或执行。"
    ),
    "其他建议": (
        "补充坐标系或经纬度、疑似裂缝现场复核、受威胁对象调查，并取得专业排危与工程意见后提交人工审查；"
        "不据此自动形成预警或工程处置决定。"
    ),
}
_FALLBACK = "待人工核查事件事实、空间对象关联及现场或监测证据，并核对已提供筛查结果的来源、版本和适用范围；缺失或未接入项保持原状态，A4 未计算专业模型结论。"
_UNSAFE_CLAIM = re.compile(
    r"\d|百分之[零〇一二两三四五六七八九十百千万亿]+|第[零〇一二两三四五六七八九十百千万亿]+|"
    r"[零〇一二两三四五六七八九十百千万亿半]+(?:个|处|次|米|毫米|厘米|公里|小时|分钟|天|日|周|月|年|级|分|人|名|组|项|条|步|页|点|度|张|件|户|座|倍|%|％)|"
    r"(?:几|数|若干)(?:个|处|次|小时|分钟|天|周|月|年|人|名|组|项|条|步|页|张|件|户|座)|"
    r"CUV|四性|易发性|危险性|易损性|脆弱性|风险性|风险等级|预警等级|预警级别|阈值|发生概率|"
    r"红色预警|橙色预警|黄色预警|蓝色预警|susceptibility|dynamic hazard|vulnerability|four[-_ ]?natures|"
    r"风险分值|风险评分|风险(?:判断|结论)?(?:为|是)?(?:高|较高|中|较低|低)|(?:高|较高|中|较低|低)风险|"
    r"(?:高|较高|中|较低|低)危险性|高危|低危|risk[-_ ]?(?:score|level)|warning[-_ ]?level|probability|threshold|"
    r"责任人|责任单位|责任部门|指派|截止|限时|时限|期限|立即|尽快|明日|今日|次日|"
    r"已派单|派单成功|已派发|已创建任务|任务已创建|告警已发布|预警已发布",
    re.I,
)
# A4 responses repeat source-labelled candidate values and IDs. Reject unsafe decisions,
# while allowing those values and explicit missing-state descriptions through.
_UNSAFE_DIFY_CLAIM = re.compile(
    r"CUV\s*(?:[:=]|为|是)\s*[-+]?\d|四性(?:分值|评分|结果)\s*(?:[:=]|为|是)\s*[-+]?\d|"
    r"(?:风险(?:等级|级别)?|预警(?:等级|级别)?|(?:risk|warning)[\s_-]*level)\s*(?:[:=]|为|是|is)\s*"
    r"(?:高|较高|中|较低|低|红|橙|黄|蓝|high|medium|low|red|orange|yellow|blue|[1-4]级)|"
    r"(?:高|较高|中|较低|低)风险|(?:高|较高|中|较低|低)危险性|高危|低危|"
    r"(?:阈值|threshold|发生概率|probability)\s*(?:[:=]|为|是|is)\s*[-+]?\d|"
    r"(?:责任人|责任单位|责任部门)\s*(?:[:=]|为|是)\s*"
    r"(?!(?:未提供|缺失|待核实|未知|missing|null|unknown))[^，,。；;\s]{2,}|"
    r"(?:截止|时限|期限)\s*(?:[:=]|为|是)\s*(?:[-+]?\d|[零〇一二两三四五六七八九十百千万])|"
    r"(?:立即|尽快)[^，,。；;]{0,6}(?:撤离|转移|疏散|封路|设警|发布预警|派单|处置)|"
    r"已派单|派单成功|已派发|已创建任务|任务已创建|告警已发布|预警已发布|任务已(?:完成|闭环)|"
    r"official_warning_allowed[\"']?\s*[:=]\s*(?:true|是|允许)|"
    r"\b(?:task|work item)\s+(?:has been\s+)?(?:created|assigned|closed|completed)\b",
    re.I,
)


def _ids(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return list(dict.fromkeys(str(item) for item in value if item not in (None, "")))


def _component(value: Any) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        return {"status": "provided_unverified", "value": value, "source": None,
                "model": None, "version": None, "evidence_ids": []}

    result = value.get("value", value.get("result"))
    status = value.get("status")
    reported_status = None
    if not isinstance(status, str) or not status.strip():
        status = "provided_unverified" if result is not None else "missing"
    elif status == "available" and result is None:
        reported_status = status
        status = "missing"
    elif status == "available" and not (
        value.get("source") not in (None, "") and value.get("version") not in (None, "")
    ):
        reported_status = status
        status = "provided_unverified"
    component = {key: item for key, item in value.items() if key not in {"value", "result", "evidence_ids"}}
    component.update({
        "status": status,
        "value": result,
        "source": value.get("source"),
        "model": value.get("model"),
        "version": value.get("version"),
        "evidence_ids": _ids(value.get("evidence_ids")),
    })
    if reported_status:
        component["reported_status"] = reported_status
    return component


def _missing_assessment(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, Mapping):
        return value.get("status") in (None, "missing", "not_configured", "unavailable") and value.get(
            "value", value.get("result")
        ) is None
    return False


def _p6_assessments(snapshot: Mapping[str, Any], simulated: bool = False) -> dict[str, dict[str, Any]]:
    unit = snapshot.get("unit_snapshot")
    info = snapshot.get("info_snapshot")
    if not isinstance(unit, Mapping):
        return {}
    info = info if isinstance(info, Mapping) else {}
    info_components = info.get("components") if isinstance(info.get("components"), Mapping) else {}
    context = info.get("record_context") if isinstance(info.get("record_context"), Mapping) else {}
    parameter_version = info.get("parameter_version")
    source = snapshot.get("source") or (
        "Yichang P6 read-only query API"
        if snapshot.get("execution_engine") == "p6_query_api"
        else "provided P6 snapshot"
    )
    interpretations = {
        "S": "静态易发性候选值；具体空间估算依据见P6信息快照。",
        "H": "历史降雨条件危险性筛查，不代表当前事件实时危险性；S×Rain v2仍属未校准试验。",
        "V": "AI工程条件情景值，未证明专家审批。",
        "R": "相对筛查分值，仅限试验筛查，不是正式预警或概率。",
    }
    flat_fields = {
        "S": ("s_score", "s_grade", "s_status", "s_model_version", "s_source", "s_data_source"),
        "H": ("h_score", "h_grade", "h_status", "h_model_version", "h_fusion_rule_version",
              "h_fusion_calibration_status", "h_source", "h_data_source"),
        "V": ("v_score", "v_grade", "v_status", "v_model_version", "v_source", "v_data_source"),
        "R": ("r_score", "r_grade", "r_status", "r_model_version", "r_rule_version", "r_source", "r_data_source"),
    }
    result = {}
    for p6_name, assessment_name in _P6_COMPONENTS.items():
        raw = unit.get(p6_name)
        fields = {key: unit[key] for key in flat_fields[p6_name] if key in unit}
        if raw is None and not fields:
            continue
        component_info = info_components.get(p6_name)
        component_info = component_info if isinstance(component_info, Mapping) else {}
        basis_key = {"S": "S_basis", "H": "H_basis", "V": "V_basis", "R": "R_use"}[p6_name]
        value = raw
        if raw is None:
            value = fields.get(f"{p6_name.lower()}_score")
        p6_status = fields.get(f"{p6_name.lower()}_status")
        if p6_status is None and isinstance(raw, Mapping):
            p6_status = raw.get("status")
        component_source = fields.get(f"{p6_name.lower()}_data_source", fields.get(f"{p6_name.lower()}_source"))
        if component_source is None and isinstance(raw, Mapping):
            component_source = raw.get("source")
        component_source = component_source or component_info.get("source")
        component_version = fields.get(f"{p6_name.lower()}_model_version")
        if p6_name == "H":
            component_version = component_version or fields.get("h_fusion_rule_version")
        if p6_name == "R":
            component_version = component_version or fields.get("r_rule_version")
        if component_version is None and isinstance(raw, Mapping):
            component_version = raw.get("version") or raw.get("model_version")
        component_version = component_version or component_info.get("version")
        result[assessment_name] = {
            "status": "provided_unverified" if value is not None else "missing",
            "value": value,
            "source": component_source or source,
            "model": (raw.get("model") if isinstance(raw, Mapping) else None)
                     or fields.get(f"{p6_name.lower()}_model")
                     or component_info.get("model") or "P6 differentiated trial screening",
            "version": component_version or parameter_version,
            "p6_snapshot_status": snapshot.get("status"),
            "p6_info_status": snapshot.get("info_status", "provided" if info else "missing"),
            "p6_component_status": p6_status or component_info.get("status"),
            "p6_basis": context.get(basis_key),
            "interpretation": interpretations[p6_name],
            "permitted_use": info.get("permitted_use"),
            "evaluation_status": info.get("evaluation_status"),
            "expert_approval_evidenced": info.get("expert_approval_evidenced"),
            "official_warning_allowed": info.get("official_warning_allowed"),
            "p6_fields": fields,
            "is_simulated": simulated or snapshot.get("is_simulated") is True,
        }
        for key in ("grade", "fusion_calibration_status", "fusion_rule_version"):
            p6_key = f"{p6_name.lower()}_{key}"
            if p6_key in unit:
                result[assessment_name][key] = unit[p6_key]
    return result


def _p6_exposure(snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
    unit = snapshot.get("unit_snapshot")
    if not isinstance(unit, Mapping):
        return None
    if not any(key in unit for key in ("E_total", "E_hotspot", "e_grade", "e_status")):
        return None
    return {
        key: unit.get(key)
        for key in (
            "E_total", "E_hotspot", "e_grade", "e_status", "e_data_source",
            "e_model_version", "e_rule_version",
        )
        if key in unit or key == "e_grade"
    }


def _monitoring(value: Any, simulated: bool) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        value = {}
    status = value.get("status")
    if not isinstance(status, str) or not status.strip():
        status = "provided_unverified" if value.get("series") or value.get("observations") else "missing"
    result = dict(value)
    result.update({
        "status": status,
        "source": value.get("source"),
        "model": value.get("model"),
        "version": value.get("version"),
        "summary": value.get("summary"),
        "evidence_ids": _ids(value.get("evidence_ids")),
        "is_simulated": simulated or value.get("is_simulated") is True,
    })
    if result["is_simulated"] and "trigger_rule" in value:
        result["trigger_rule"] = value["trigger_rule"]
        result["trigger_rule_scope"] = "gold_regression_only"
    else:
        result["trigger_rule_scope"] = "not_interpreted_as_official_threshold"
    return result


def _citations(evidence: list[dict], event: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    citations = []
    by_id = {}
    event_anchors = event.get("evidence_anchors") if isinstance(event, Mapping) else None
    candidates = [
        *(event_anchors if isinstance(event_anchors, list) else []),
        *(evidence if isinstance(evidence, list) else []),
    ]
    for item in candidates:
        if not isinstance(item, Mapping) or is_simulated_evidence(item):
            continue
        citation = {key: item[key] for key in
                    ("evidence_id", "document_id", "chunk_id", "file_name", "page", "text", "source_spans")
                    if key in item}
        if not citation:
            continue
        evidence_id = citation.get("evidence_id")
        if evidence_id not in (None, "") and str(evidence_id) in by_id:
            by_id[str(evidence_id)].update(citation)
        else:
            citations.append(citation)
            if evidence_id not in (None, ""):
                by_id[str(evidence_id)] = citation
    return citations


def _dynamic_risk(value: Any, simulated: bool) -> dict[str, Any]:
    if isinstance(value, Mapping):
        result = dict(value)
    elif value is None:
        result = {"status": "missing"}
    else:
        result = {"status": "provided_unverified", "value": value}
    status = result.get("status")
    if not isinstance(status, str) or not status.strip():
        result["status"] = "provided_unverified" if any(
            result.get(key) is not None for key in ("value", "result", "score")
        ) else "missing"
    if simulated:
        result.setdefault("is_simulated", True)
    return result


def _missing_evidence(event: Mapping[str, Any], citations: list[dict[str, Any]]) -> list[dict[str, str]]:
    gaps = []
    fields = event.get("missing_fields")
    if isinstance(fields, list):
        gaps.extend(
            {"item": str(field), "status": "missing", "source": "event_input"}
            for field in fields if field not in (None, "")
        )
    if not citations:
        gaps.append({
            "item": "supporting_evidence",
            "status": "missing",
            "source": "A2 event and Geo-RAG",
            "reason": "no evidence records were supplied",
        })
    return gaps


def _unique_evidence_ids(components: dict, monitoring: dict, citations: list[dict], dynamic_risk: Any = None) -> list[str]:
    values = [item for item in components.values()]
    values.append(monitoring)
    if isinstance(dynamic_risk, Mapping):
        values.append(dynamic_risk)
    values.extend(citations)
    return list(dict.fromkeys(
        str(evidence_id)
        for item in values
        for evidence_id in _ids(item.get("evidence_ids", item.get("evidence_id")))
    ))


def _spatial_unit_id(event: Mapping[str, Any]) -> Any:
    nested = event.get("slope_unit_info", event.get("slope_unit"))
    if not isinstance(nested, Mapping):
        nested = {}
    task = event.get("task_info", event.get("task"))
    if not isinstance(task, Mapping):
        task = {}
    value = _first_value(
        event.get("slope_unit_id"), nested.get("slope_unit_id"), nested.get("unitId"), nested.get("id"),
        task.get("unitId"), task.get("slope_unit_id"),
    )
    return value


def _p6_mapping_unit_id(event: Mapping[str, Any]) -> Any:
    mapping = event.get("p6_mapping")
    if not isinstance(mapping, Mapping):
        return None
    unit_id = _first_value(mapping.get("p6_slope_unit_id"))
    return None if isinstance(unit_id, str) and not unit_id.strip() else unit_id


def _dynamic_snapshot_from_lookup(result: Mapping[str, Any]) -> dict[str, Any]:
    metadata = result.get("unit_snapshot")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    item = result.get("item")
    item = item if isinstance(item, Mapping) else {}
    mode = {
        **dict(metadata),
        **dict(item),
        **{
            key: result[key]
            for key in ("status", "scenario", "snapshot_id", "slope_unit_id", "snapshot_query_mode", "reason")
            if key in result
        },
        "permitted_use": "candidate_lookup_and_trial_screening",
        "expert_approval_evidenced": False,
        "official_warning_allowed": False,
    }
    return {
        "status": result.get("status", "unknown"),
        "execution_engine": "p6_dynamic_query_api",
        "scenario": "dynamic",
        "snapshot_id": result.get("snapshot_id"),
        "slope_unit_id": result.get("slope_unit_id"),
        "as_of_local": metadata.get("as_of_local"),
        "model": metadata.get("model"),
        "rule_version": metadata.get("rule_version"),
        "permitted_use": "candidate_lookup_and_trial_screening",
        "expert_approval_evidenced": False,
        "official_warning_allowed": False,
        "dynamic": mode,
    }


def _java_task_payload(event: dict[str, Any], simulated: bool, recommendation: str,
                       completion_criteria: str) -> tuple[dict[str, Any] | None, str]:
    unit_id = _spatial_unit_id(event)
    unit_id = str(unit_id).strip() if unit_id not in (None, "") else ""
    if simulated or unit_id.upper().startswith("GOLD-"):
        return None, "blocked_simulated_object"
    if not unit_id:
        return None, "missing_java_unit_id"
    task = event.get("task_info", event.get("task"))
    task = task if isinstance(task, Mapping) else {}
    source_type = task.get("sourceType")
    if not isinstance(source_type, int) or isinstance(source_type, bool) or source_type not in range(7):
        source_type = {"FIELD_REPORT": 2, "MONITOR_WARNING": 5}.get(str(event.get("source_kind", "")).upper())
    if source_type is None:
        return None, "missing_java_source_type"
    return {
        "unitId": unit_id,
        "sourceType": source_type,
        "taskSource": "宜昌A4人工审核",
        "submitRequire": completion_criteria,
        "inspectionSuggestion": recommendation,
    }, "ready_for_human_review"


def _first_value(*values: Any) -> Any:
    return next((value for value in values if value not in (None, "")), None)


def _action_item(event: dict[str, Any], simulated: bool, recommendation: str,
                 evidence_ids: list[str]) -> dict[str, Any]:
    task = event.get("task_info", event.get("task"))
    task = task if isinstance(task, Mapping) else {}
    location = _first_value(
        event.get("location"), event.get("detailed_address"), task.get("detailedAddress"), task.get("location"),
    )
    if isinstance(location, Mapping):
        location = " / ".join(str(location[key]) for key in (
            "city", "county", "street", "village", "detailedAddress", "address",
        ) if location.get(key) not in (None, "")) or None
    if location is None:
        refs = [event.get("admin_area"), _spatial_unit_id(event), event.get("hazard_point_id")]
        refs = [item for item in refs if item]
        location = " / ".join(str(item) for item in refs) if refs else "待人工确认"
    responsible_department = _first_value(
        event.get("responsible_department"), event.get("responsible_unit"), event.get("department"),
        task.get("responsible_department"), task.get("responsibleDepartment"), task.get("responsible_unit"),
    ) or "待分配"
    person = _first_value(
        event.get("responsible_person"), event.get("assignee"), event.get("person"),
        task.get("responsible_person"), task.get("responsiblePerson"), task.get("assignee"), task.get("person"),
    ) or "待分配"
    due_at = _first_value(
        event.get("due_at"), event.get("deadline"), event.get("due_date"),
        task.get("due_at"), task.get("dueAt"), task.get("deadline"), task.get("limitedDate"),
    ) or "待安排"
    completion_criteria = _first_value(
        event.get("completion_criteria"), task.get("completion_criteria"), task.get("submitRequire"),
    ) or "核实现场迹象、坡单元或隐患点关联及现场/监测证据；核对已提供筛查结果的来源与适用范围，并记录结果。"
    java_task_payload, task_request_status = _java_task_payload(
        event, simulated, recommendation, completion_criteria,
    )
    existing_task_id = None if simulated else _first_value(
        event.get("task_id"), task.get("task_id"), task.get("taskId"), task.get("id"),
    )
    return {
        "action": _first_value(event.get("action"), "人工核查事件现场与空间对象关联"),
        "location": location,
        "responsible_department": responsible_department,
        "person": person,
        "due_at": due_at,
        "completion_criteria": completion_criteria,
        "completion_criteria_source": (
            "provided_input" if completion_criteria != "核实现场迹象、坡单元或隐患点关联及现场/监测证据；核对已提供筛查结果的来源与适用范围，并记录结果。"
            else "a4_review_template"
        ),
        "basis_evidence_ids": evidence_ids,
        "java_task_payload": java_task_payload,
        "task_request_status": task_request_status,
        "human_approval_required": True,
        "assignment_status": "provided_unverified" if responsible_department != "待分配" or person != "待分配" else "unassigned",
        "due_status": "provided_unverified" if due_at != "待安排" else "not_provided",
        "dispatch_status": "not_dispatched",
        "review_status": "pending_human_confirmation",
        "task_id": existing_task_id,
    }


def _llm_context(event: dict[str, Any], components: dict, monitoring: dict,
                citations: list[dict]) -> dict[str, Any]:
    facts = {key: event[key] for key in (
        "source_kind", "correlation_id", "admin_area", "slope_unit_id", "hazard_point_id",
        "spatial_ref_status", "spatial_object_source", "p6_mapping",
        "data_source", "is_simulated", "location", "event_type", "description", "occurred_at", "field_notes",
        "field_report", "findings", "event_status", "missing_fields", "uncertainty", "dynamic_risk",
        "p6_snapshot", "p6_dynamic_snapshot", "p6_exposure",
    ) if key in event}
    statuses = {name: {key: component.get(key) for key in ("status", "source", "model", "version")}
                for name, component in components.items()}
    monitoring_status = {key: monitoring.get(key) for key in
                         ("status", "source", "model", "version", "summary", "is_simulated")}
    return {"event_facts": facts, "assessment_status": statuses,
            "monitoring_status": monitoring_status,
            "evidence": [{key: item[key] for key in ("evidence_id", "file_name", "page", "text") if key in item}
                         for item in citations]}


async def _recommendation(context: dict[str, Any]) -> tuple[str, str]:
    if not llm_enabled():
        return _fallback_recommendation(context), "llm_not_configured"
    try:
        response = await build_llm().ainvoke([
            ("system", "你是地质灾害事件核查建议助手。只用中文给出简短、可执行的人工核查建议。"
             "只依据输入事实和证据，不给风险等级、预警等级、CUV/四性数值、阈值、概率或模型结论；"
             "不补写责任人、时限、任务状态，不声称已经派单。只输出建议正文。"),
            ("user", json.dumps(context, ensure_ascii=False)),
        ])
        text = response.content.strip() if isinstance(response.content, str) else ""
        if not text or _UNSAFE_CLAIM.search(text):
            return _fallback_recommendation(context), "unsupported_output"
        return text, "completed"
    except Exception:
        return _fallback_recommendation(context), "llm_unavailable"


def _fallback_recommendation(context: Mapping[str, Any]) -> str:
    facts = context.get("event_facts") if isinstance(context.get("event_facts"), Mapping) else {}
    has_event_record = any(facts.get(key) for key in ("field_report", "field_notes", "findings", "description"))
    has_evidence = bool(context.get("evidence"))
    if has_event_record or has_evidence:
        return (
            "依据已提供的现场记录或检索证据，建议人工核对记录所述迹象与空间对象关联，"
            "复核证据来源和时间，核对已提供筛查结果的来源、版本和适用范围，并留存现场核查结果及原始监测记录；"
            "缺失或未接入项保持原状态，不据此形成专业模型结论。"
        )
    return _FALLBACK


def _dify_recommendation(execution: Mapping[str, Any]) -> str | None:
    def extract(value: Any) -> str | None:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json|markdown)?\s*|\s*```$", "", text, flags=re.I).strip()
            try:
                decoded = json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                return text or None
            return extract(decoded)
        if isinstance(value, Mapping):
            for key in (
                "current_judgment", "currentJudgment", "CurrentJudgment", "recommendation", "conclusion",
                "Conclusion", "disposal_opinion", "disposalOpinion", "DecisionRecord", "decision_record",
                "decisionRecord", "answer", "text", "output",
            ):
                if key in value:
                    found = extract(value[key])
                    if found:
                        return found
        return None

    for candidate in (execution.get("response"), execution.get("outputs")):
        text = extract(candidate)
        if text and not _UNSAFE_DIFY_CLAIM.search(text):
            return text
    return None


def _dify_structured_review(execution: Mapping[str, Any]) -> dict[str, Any] | None:
    def canonical_record(value: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(value)
        aliases = {
            "task_understanding": ("taskUnderstanding",),
            "current_judgment": ("currentJudgment", "CurrentJudgment", "disposal_opinion", "disposalOpinion", "conclusion", "Conclusion"),
            "evidence_basis_ids": ("evidenceBasisIds", "evidence_ids", "evidenceIds"),
            "missing_fields": ("missingFields",),
            "model_status": ("modelStatus",),
            "human_review_required": ("humanReviewRequired",),
            "action_items": ("actionItems",),
        }
        for name, alternatives in aliases.items():
            if name not in result:
                supplied = next((value[key] for key in alternatives if key in value), None)
                if supplied is not None:
                    result[name] = supplied
        return result

    def decode(value: Any, depth: int = 0) -> dict[str, Any] | None:
        if depth > 5:
            return None
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json|markdown)?\s*|\s*```$", "", text, flags=re.I).strip()
            try:
                return decode(json.loads(text), depth + 1)
            except (TypeError, ValueError, json.JSONDecodeError):
                return None
        if not isinstance(value, Mapping):
            return None
        decision_record = next((value[key] for key in ("DecisionRecord", "decision_record", "decisionRecord")
                                if isinstance(value.get(key), Mapping)), None)
        if decision_record is not None:
            result = canonical_record(decision_record)
            for aliases, normalized in (
                (("DisposalPlan", "disposal_plan", "disposalPlan"), "disposal_plan"),
                (("TaskProposal", "task_proposal", "taskProposal"), "task_proposal"),
            ):
                supplied = next((value[key] for key in aliases if key in value), None)
                if supplied is not None:
                    result[normalized] = supplied
            return result
        if any(key in value for key in (
            "task_understanding", "taskUnderstanding", "current_judgment", "currentJudgment", "CurrentJudgment",
            "action_items", "actionItems", "disposal_opinion", "disposalOpinion", "conclusion", "Conclusion",
        )):
            return canonical_record(value)
        for key in ("outputs", "response", "answer", "text", "output", "data", "result"):
            if key in value:
                found = decode(value[key], depth + 1)
                if found is not None:
                    return found
        return None

    for candidate in (execution.get("response"), execution.get("outputs")):
        review = decode(candidate)
        if review is not None:
            return review
    return None


def _review_action_items(review: Mapping[str, Any] | None, evidence_ids: list[str], fallback: str) -> list[dict[str, Any]]:
    raw_items = review.get("action_items") if isinstance(review, Mapping) else None
    result = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, Mapping):
                action = item.get("action")
                basis_ids = _ids(item.get("basis_evidence_ids"))
            else:
                action = item
                basis_ids = []
            if not isinstance(action, str) or not action.strip() or _UNSAFE_CLAIM.search(action):
                continue
            result.append({
                "action": action.strip(),
                "basis_evidence_ids": [value for value in basis_ids if value in evidence_ids],
                "human_review_required": True,
                "dispatch_status": "not_dispatched",
            })
    if not result:
        result.append({
            "action": fallback,
            "basis_evidence_ids": [],
            "human_review_required": True,
            "dispatch_status": "not_dispatched",
        })
    return result


def _missing_task_assignment_fields(business_action: Mapping[str, Any]) -> list[str]:
    placeholders = {
        "",
        "待分配",
        "待安排",
        "未提供",
        "未提供 Gold 映射",
    }
    missing = []
    for field in ("responsible_department", "person", "due_at"):
        value = business_action.get(field)
        if not isinstance(value, str) or value.strip() in placeholders:
            missing.append(field)
    return missing


def _gold_task_contract(event: Mapping[str, Any]) -> Mapping[str, Any] | None:
    contract = event.get("gold_task_contract")
    return contract if isinstance(contract, Mapping) else None


def _missing_gold_task_contract_fields(event: Mapping[str, Any]) -> list[str]:
    contract = _gold_task_contract(event)
    if contract is None:
        return ["gold_task_contract"]
    placeholders = {"", "待分配", "待安排", "未提供", "待人工确认"}
    return [
        field for field in (
            "action", "location", "responsible_department", "person", "due_at", "completion_criteria",
        )
        if not isinstance(contract.get(field), str) or contract[field].strip() in placeholders
    ]


def _disposal_plan(review: Mapping[str, Any] | None, plan_run: Mapping[str, Any] | None,
                   evidence_ids: list[str], simulated: bool) -> dict[str, Any]:
    source = review.get("disposal_plan") if isinstance(review, Mapping) else None
    if not isinstance(source, Mapping) and isinstance(plan_run, Mapping):
        source = plan_run.get("structured_output")
    if isinstance(source, Mapping):
        source = next((source[key] for key in ("DisposalPlan", "disposal_plan", "disposalPlan")
                       if isinstance(source.get(key), Mapping)), source)
    measures = source.get("measures") if isinstance(source, Mapping) and isinstance(source.get("measures"), Mapping) else source
    measures = measures if isinstance(measures, Mapping) else {}
    normalized = {}
    for category in DISPOSAL_MEASURE_CATEGORIES:
        items = measures.get(category)
        items = items if isinstance(items, list) else []
        accepted = []
        for item in items:
            if isinstance(item, Mapping):
                action = next((item[key] for key in ("action", "measure", "suggestion", "recommendation")
                               if isinstance(item.get(key), str)), None)
                basis_ids = _ids(item.get("basis_evidence_ids"))
            else:
                action = item if isinstance(item, str) else None
                basis_ids = []
            if not action or not action.strip() or _UNSAFE_CLAIM.search(action):
                continue
            accepted.append({
                "action": action.strip(),
                "basis_evidence_ids": [value for value in basis_ids if value in evidence_ids],
                "human_review_required": True,
                "dispatch_status": "not_dispatched",
            })
        normalized[category] = accepted
    has_suggestions = any(normalized.values())
    summary = source.get("summary") if isinstance(source, Mapping) else None
    if not isinstance(summary, str) or not summary.strip():
        summary = None
    text_only = False
    if isinstance(plan_run, Mapping) and (
        plan_run.get("output_status") == "text_only_review_required"
        or plan_run.get("text_only_review_required") is True
    ):
        plan_text = plan_run.get("plan_text")
        if not isinstance(plan_text, str):
            plan_text = plan_run.get("raw_response")
        if not isinstance(plan_text, str):
            plan_text = plan_run.get("response")
        if isinstance(plan_text, str) and plan_text.strip():
            summary = plan_text.strip()
            text_only = True
    use_simulated_fallback = simulated and not has_suggestions and summary is None
    if use_simulated_fallback:
        normalized = {
            category: [{
                "action": _SIMULATED_DISPOSAL_FALLBACKS[category],
                "basis_evidence_ids": [],
                "human_review_required": True,
                "dispatch_status": "not_dispatched",
                "is_simulated": True,
                "official_warning_allowed": False,
            }]
            for category in DISPOSAL_MEASURE_CATEGORIES
        }
    return {
        "measures": normalized,
        "summary": summary,
        "status": "local_simulated_fallback" if use_simulated_fallback else (
            "text_only_review_required" if text_only else (
                "provided_unverified" if has_suggestions else "missing"
            )
        ),
        "source": "local_simulated_fallback" if use_simulated_fallback else (
            "dify_text" if text_only else None
        ),
        "text_only_review_required": text_only,
        "missing_fields": [],
        "review_status": "pending_human_confirmation",
        "human_review_required": True,
        "dispatch_status": "not_dispatched",
        "is_simulated": simulated,
        "official_warning_allowed": False,
    }


def _task_proposal(event: Mapping[str, Any], evidence_ids: list[str], simulated: bool,
                   trace_id: Any = None) -> dict[str, Any] | None:
    contract = _gold_task_contract(event)
    if not contract or _missing_gold_task_contract_fields(event):
        return None
    proposal = {
        "event_id": event.get("event_id"),
        "action": contract.get("action"),
        "location": contract.get("location"),
        "responsible_department": contract.get("responsible_department"),
        "person": contract.get("person"),
        "due_at": contract.get("due_at"),
        "resources": contract.get("resources") if isinstance(contract.get("resources"), list) else [],
        "completion_criteria": contract.get("completion_criteria"),
        "basis_evidence_ids": [
            value for value in _ids(contract.get("basis_evidence_ids")) if value in evidence_ids
        ],
        "missing_fields": [],
        "status": "awaiting_human_approval",
        "review_status": "pending_human_confirmation",
        "human_approval_required": True,
        "dispatch_status": "not_dispatched",
        "task_id": None,
        "is_simulated": simulated,
        "formal_java_task_created": False,
    }
    if trace_id not in (None, ""):
        proposal["trace_id"] = trace_id
    return proposal


async def process_decision(
    event: dict,
    evidence: list[dict],
    *,
    execute_dify: bool = True,
) -> dict[str, Any]:
    """Compose supplied evidence and model outputs without computing risk values."""
    event = event if isinstance(event, dict) else {}
    evidence = evidence if isinstance(evidence, list) else []
    raw_monitoring = event.get("monitoring")
    simulated = event.get("is_simulated") is True or event.get("source_kind") == "SIMULATED" or (
        isinstance(raw_monitoring, Mapping) and raw_monitoring.get("is_simulated") is True
    )
    p6_mapping_unit_id = _p6_mapping_unit_id(event)
    supplied_snapshot = event.get("p6_snapshot")
    p6_snapshot = (
        dict(supplied_snapshot)
        if isinstance(supplied_snapshot, Mapping) and supplied_snapshot
        else await lookup_slope_unit(p6_mapping_unit_id)
    )
    supplied_dynamic_snapshot = event.get("p6_dynamic_snapshot")
    if isinstance(supplied_dynamic_snapshot, Mapping) and supplied_dynamic_snapshot:
        p6_dynamic_snapshot = dict(supplied_dynamic_snapshot)
    elif p6_mapping_unit_id is not None:
        p6_dynamic_snapshot = _dynamic_snapshot_from_lookup(
            await lookup_dynamic_slope_unit(p6_mapping_unit_id, scenario="dynamic")
        )
    else:
        p6_dynamic_snapshot = {
            "status": "missing_mapping",
            "reason": "missing_p6_slope_unit_id",
            "execution_engine": "p6_dynamic_query_api",
            "permitted_use": "candidate_lookup_and_trial_screening",
            "expert_approval_evidenced": False,
            "official_warning_allowed": False,
        }
    simulated = simulated or (isinstance(p6_snapshot, Mapping) and p6_snapshot.get("is_simulated") is True)
    enriched_event = dict(event)
    enriched_event["p6_snapshot"] = p6_snapshot
    enriched_event["p6_dynamic_snapshot"] = p6_dynamic_snapshot
    enriched_event["is_simulated"] = simulated
    spatial_unit_id = _spatial_unit_id(enriched_event)
    if spatial_unit_id not in (None, ""):
        enriched_event.setdefault("slope_unit_id", spatial_unit_id)
    dynamic_risk = _dynamic_risk(event.get("dynamic_risk"), simulated)
    enriched_event["dynamic_risk"] = dynamic_risk
    p6_unit = p6_snapshot.get("unit_snapshot") if isinstance(p6_snapshot, Mapping) else None
    exposure = _p6_exposure(p6_snapshot) if isinstance(p6_snapshot, Mapping) else None
    if exposure is None and isinstance(p6_unit, Mapping) and "exposure" in p6_unit:
        exposure = p6_unit["exposure"]
    provided_exposure = enriched_event.get("p6_exposure")
    if isinstance(provided_exposure, Mapping):
        enriched_event["p6_exposure"] = {**(exposure if isinstance(exposure, Mapping) else {}), **provided_exposure}
    elif provided_exposure is None and exposure is not None:
        enriched_event["p6_exposure"] = exposure
    raw_components = event.get("assessments")
    raw_components = raw_components if isinstance(raw_components, Mapping) else {}
    raw_components = dict(raw_components)
    for name, candidate in _p6_assessments(p6_snapshot, simulated).items():
        if _missing_assessment(raw_components.get(name)):
            raw_components[name] = candidate
    components = {name: _component(raw_components.get(name)) for name in COMPONENTS}
    monitoring = _monitoring(raw_monitoring, simulated)
    simulated = simulated or monitoring["is_simulated"]
    if simulated:
        dynamic_risk.setdefault("is_simulated", True)
    citations = _citations(evidence, event)
    evidence_ids = list(dict.fromkeys([
        *_ids(event.get("evidence_ids")),
        *_unique_evidence_ids(components, monitoring, citations, dynamic_risk),
    ]))
    context_event = {**enriched_event, "dynamic_risk": dynamic_risk, "is_simulated": simulated}
    context = _llm_context(context_event, components, monitoring, citations)
    execution = await run_a4_workflow(enriched_event, components, monitoring, citations) if execute_dify else {
        "agent_id": "A4",
        "execution_engine": "local",
        "status": "deferred_to_phase2",
        "configured": False,
        "workflows": {},
    }
    execution_engine = execution.get("execution_engine", "local")
    workflow_runs = execution.get("workflows") if isinstance(execution.get("workflows"), Mapping) else {}
    if not workflow_runs and execution_engine == "dify":
        workflow_runs = {"a4": execution}
    dify_analysis_runs = []
    for role, result in workflow_runs.items():
        if not isinstance(result, Mapping) or result.get("execution_engine") != "dify":
            continue
        if (
            str(role).casefold() == "plan"
            or str(result.get("workflow_kind") or "").casefold() == "plan"
            or str(result.get("app_role") or "").casefold() == "plan"
            or str(result.get("registry_id") or "").casefold() == "a4_plan"
        ):
            continue
        dify_analysis_runs.append(result)
    accepted = []
    accepted_reviews = []
    for role, result in workflow_runs.items():
        if (
            not isinstance(result, Mapping) or result.get("execution_engine") != "dify"
            or str(result.get("status", "")).lower() not in {"completed", "succeeded", "success"}
        ):
            continue
        if (
            str(role).casefold() == "plan"
            or str(result.get("workflow_kind") or "").casefold() == "plan"
            or str(result.get("app_role") or "").casefold() == "plan"
            or str(result.get("registry_id") or "").casefold() == "a4_plan"
        ):
            continue
        review_recommendation = _dify_recommendation(result)
        if review_recommendation:
            accepted.append(review_recommendation)
            accepted_reviews.append(_dify_structured_review(result))
    accepted = list(dict.fromkeys(accepted))
    structured_review = next((item for item in accepted_reviews if isinstance(item, Mapping)), None)
    recommendation_engine = "local_rules"
    if accepted:
        recommendation = "\n\n".join(accepted)
        recommendation_engine = "dify"
        llm_status = "completed"
    elif dify_analysis_runs:
        recommendation = _fallback_recommendation(context)
        dify_errors = any(
            str(result.get("status", "")).lower() in {"error", "failed", "partial_error"}
            for result in dify_analysis_runs
        )
        dify_completed = any(
            str(result.get("status", "")).lower() in {"completed", "succeeded", "success"}
            for result in dify_analysis_runs
        )
        llm_status = "dify_error" if dify_errors else (
            "unsupported_output" if dify_completed else "local_fallback"
        )
    elif execution_engine in {"dify", "mixed"}:
        recommendation = _fallback_recommendation(context)
        recommendation_engine = "local_rules"
        llm_status = (
            "local_fallback"
            if any(isinstance(result, Mapping) and result.get("configured") is True
                   for result in workflow_runs.values())
            else "not_configured"
        )
    elif not execute_dify:
        recommendation = _fallback_recommendation(context)
        recommendation_engine = "local_rules"
        llm_status = "deferred_to_phase2"
    else:
        recommendation, llm_status = await _recommendation(context)
        if llm_status == "completed":
            recommendation_engine = "local_llm"
    if recommendation is None:
        recommendation = _fallback_recommendation(context)

    business_action = _action_item(event, simulated, recommendation, evidence_ids)
    missing_fields = _ids(event.get("missing_fields"))
    assignment_missing_fields = _missing_task_assignment_fields(business_action)
    task_contract_missing_fields = _missing_gold_task_contract_fields(event)
    for field in [*assignment_missing_fields, *task_contract_missing_fields]:
        if field not in missing_fields:
            missing_fields.append(field)
    if not citations and "supporting_evidence" not in missing_fields:
        missing_fields.append("supporting_evidence")
    assessment_status = {
        name: {key: item[key] for key in (
            "status", "source", "model", "version", "p6_snapshot_status", "p6_component_status",
            "permitted_use", "expert_approval_evidenced", "official_warning_allowed", "is_simulated",
            "grade", "fusion_calibration_status", "fusion_rule_version", "p6_fields",
        ) if key in item}
        for name, item in components.items()
    }
    p6_info = p6_snapshot.get("info_snapshot") if isinstance(p6_snapshot, Mapping) else None
    p6_info = dict(p6_info) if isinstance(p6_info, Mapping) else {}
    model_status = {
        "assessments": assessment_status,
        "dynamic_risk": {key: dynamic_risk[key] for key in (
            "status", "source", "model", "version", "reason", "is_simulated",
        ) if key in dynamic_risk},
        "monitoring": {key: monitoring[key] for key in (
            "status", "source", "model", "version", "calculation_mode", "trigger_rule_scope", "is_simulated",
        ) if key in monitoring},
        "p6_snapshot": {
            key: p6_snapshot[key] for key in ("status", "execution_engine", "info_status", "source")
            if isinstance(p6_snapshot, Mapping) and key in p6_snapshot
        },
        "p6_mapping": event.get("p6_mapping"),
        "p6_exposure": enriched_event.get("p6_exposure"),
        "p6_dynamic_snapshot": enriched_event.get("p6_dynamic_snapshot"),
    }
    if p6_mapping_unit_id is not None:
        model_status["p6_snapshot"]["p6_slope_unit_id"] = p6_mapping_unit_id
    model_status["p6_snapshot"]["is_simulated"] = simulated
    if p6_info:
        model_status["p6_snapshot"]["info_snapshot"] = p6_info
    a4_review = {
        "task_understanding": (
            _dify_recommendation({"response": structured_review.get("task_understanding")})
            if isinstance(structured_review, Mapping) else None
        ),
        "current_judgment": recommendation,
        "evidence_basis_ids": evidence_ids,
        "missing_fields": missing_fields,
        "missing_evidence": _missing_evidence(event, citations),
        "model_status": model_status,
        "human_review_required": True,
        "action_items": _review_action_items(
            structured_review, evidence_ids, business_action["action"],
        ),
        "review_status": "pending_human_confirmation",
    }

    analysis_run = next((
        result for role, result in workflow_runs.items()
        if isinstance(result, Mapping) and str(role).casefold() in {"analysis", "a4"}
    ), {})
    plan_run = next((
        result for role, result in workflow_runs.items()
        if isinstance(result, Mapping) and (
            str(role).casefold() == "plan"
            or str(result.get("workflow_kind") or "").casefold() == "plan"
            or str(result.get("app_role") or "").casefold() == "plan"
        )
    ), {})
    a4_trace_id = analysis_run.get("trace_id") if isinstance(analysis_run, Mapping) else None
    disposal_plan = _disposal_plan(structured_review, plan_run, evidence_ids, simulated)
    disposal_plan["missing_fields"] = list(dict.fromkeys([
        *assignment_missing_fields, *task_contract_missing_fields,
    ]))
    task_proposal = _task_proposal(
        event, evidence_ids, simulated, a4_trace_id,
    )
    decision_record = {
        "record_type": "DecisionRecord",
        "event_id": event.get("event_id"),
        "trace_id": a4_trace_id or event.get("trace_id"),
        "decision_status": "pending_human_confirmation",
        "disposal_opinion": recommendation,
        "review_report": a4_review,
        "is_simulated": simulated,
        "formal_warning_created": False,
        "task_created": False,
        **a4_review,
    }

    execution_summary = {
        "agent_id": execution.get("agent_id", "A4"),
        "execution_engine": execution_engine,
        "status": execution.get("status", "unknown"),
        "configured": execution.get("configured"),
        "workflows": {},
        "recommendation_engine": recommendation_engine,
    }
    if execution.get("error"):
        execution_summary["error"] = execution["error"]
    for role, result in workflow_runs.items():
        if not isinstance(result, Mapping):
            continue
        workflow_recommendation = _dify_recommendation(result) if result.get("execution_engine") == "dify" else None
        workflow_summary = {
            key: result.get(key) for key in (
                "agent_key", "agent_id", "app_role", "registry_id", "app_name", "workflow_kind",
                "input_fields", "configured", "execution_engine", "status", "trace_id", "task_id",
                "message_id", "conversation_id", "duration_ms", "error", "raw_response", "raw_outputs",
            )
        }
        for key in ("plan_text", "text_only_review_required"):
            if key in result:
                workflow_summary[key] = result[key]
        workflow_summary["output_status"] = result.get("output_status") or (
            "accepted" if workflow_recommendation else (
                "unsupported_output" if result.get("execution_engine") == "dify" and result.get("status") == "completed"
                else "not_used"
            )
        )
        execution_summary["workflows"][role] = workflow_summary
    if not workflow_runs:
        execution_summary["error"] = execution.get("error")
        execution_summary["output_status"] = (
            "accepted" if recommendation_engine == "dify" else (
                "unsupported_output" if execution_engine == "dify" and execution.get("status") == "completed"
                else "not_used"
            )
        )

    return {
        "event": {**{key: event.get(key) for key in (
            "event_id", "source_kind", "correlation_id", "admin_area", "slope_unit_id",
            "hazard_point_id", "data_source",
        )}, **{
            key: event[key] for key in ("spatial_ref_status", "spatial_object_source", "p6_mapping")
            if key in event
        }, "slope_unit_id": spatial_unit_id or event.get("slope_unit_id"), "is_simulated": simulated},
        "is_simulated": simulated,
        "four_natures": components,
        "dynamic_risk": dynamic_risk,
        "monitoring": monitoring,
        "p6_snapshot": p6_snapshot,
        "p6_exposure": enriched_event.get("p6_exposure"),
        "p6_dynamic_snapshot": enriched_event.get("p6_dynamic_snapshot"),
        "review_basis": {"event_facts": context["event_facts"],
                          "assessment_status": context["assessment_status"],
                          "monitoring_status": context["monitoring_status"], "evidence": citations,
                          "missing_evidence": _missing_evidence(event, citations),
                          "p6_snapshot": p6_snapshot,
                          "p6_dynamic_snapshot": enriched_event.get("p6_dynamic_snapshot"),
                          "p6_exposure": enriched_event.get("p6_exposure")},
        "evidence_ids": evidence_ids,
        "recommendation": recommendation,
        "execution_engine": execution_engine,
        "recommendation_engine": recommendation_engine,
        "a4_execution": execution_summary,
        "llm_status": llm_status,
        "action_items": [business_action],
        "a4_review": a4_review,
        "decision_record": decision_record,
        "disposal_plan": disposal_plan,
        "task_proposal": task_proposal,
        "decision_status": "pending_human_confirmation",
        "formal_warning_created": False,
        "task_created": False,
    }
