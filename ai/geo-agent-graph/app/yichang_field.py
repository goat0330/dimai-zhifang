"""Small Yichang adapter for structured field reports."""

import json
from typing import Any
from uuid import uuid4

from .dify_adapters.a2_field import run_a2_field_vision
from .llm import build_llm, llm_enabled


def _first_text(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _field_record_value(data: dict[str, Any], section: str, *keys: str) -> Any:
    sources = []
    investigation_record = data.get("field_investigation_record")
    if isinstance(investigation_record, dict):
        nested_section = investigation_record.get(section)
        if isinstance(nested_section, dict):
            sources.append(nested_section)
    section_value = data.get(section)
    if isinstance(section_value, dict):
        sources.append(section_value)
    field_report = data.get("field_report")
    if isinstance(field_report, dict) and field_report is not section_value:
        sources.append(field_report)
    sources.append(data)
    for source in sources:
        for key in keys:
            value = source.get(key)
            if value is not None and value != "":
                return value
    return None


def _field_record_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _reference_id(data: dict[str, Any], id_key: str, object_key: str) -> Any:
    value = data.get(id_key)
    if value is None:
        value = data.get(object_key)
    if isinstance(value, dict):
        object_id = value.get(id_key)
        value = value.get("id") if object_id is None else object_id
    if isinstance(value, str):
        return value.strip() or None
    return value


def _confirmed_p6_slope_unit_id(data: dict[str, Any]) -> str | None:
    value = data.get("p6_slope_unit_id")
    status = data.get("spatial_ref_status")
    source = data.get("spatial_object_source")
    if (
        isinstance(value, str)
        and value == value.strip()
        and value.startswith("YCSU_")
        and len(value) > len("YCSU_")
        and isinstance(status, str)
        and status.strip().casefold() == "human_confirmed"
        and isinstance(source, str)
        and bool(source.strip())
    ):
        return value
    return None


def _photo_refs(data: dict[str, Any]) -> list[Any]:
    refs = data.get("photo_refs", data.get("photos", []))
    if isinstance(refs, (str, dict)):
        refs = [refs]
    if not isinstance(refs, list):
        return []
    safe_refs = []
    for ref in refs:
        if isinstance(ref, str):
            safe_refs.append(ref)
        elif isinstance(ref, dict):
            safe_ref = {key: value for key, value in ref.items()
                        if key not in {"content", "content_base64", "data_uri", "bytes"}}
            if not safe_ref and any(key in ref for key in {"content", "content_base64", "data_uri", "bytes"}):
                safe_ref = {"kind": "inline_photo"}
            if safe_ref:
                safe_refs.append(safe_ref)
    return safe_refs


def _manual_corrections(data: dict[str, Any]) -> list[dict[str, Any]]:
    corrections = next((
        data[key] for key in ("manual_corrections", "human_corrections", "manual_correction", "人工更正")
        if key in data and data[key] is not None
    ), [])
    if isinstance(corrections, dict):
        corrections = [corrections]
    if not isinstance(corrections, list):
        return []
    return [dict(item) for item in corrections if isinstance(item, dict)]


def _normalize_gps(value: Any) -> tuple[dict[str, float] | None, str]:
    if value is None:
        return None, "missing"
    if not isinstance(value, dict):
        return None, "invalid"
    lat = value.get("lat", value.get("latitude"))
    lon = value.get("lon", value.get("lng", value.get("longitude")))
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None, "invalid"
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, "invalid"
    return {"lat": lat, "lon": lon}, "valid"


def _verified_vision_findings(value: Any) -> tuple[list[dict[str, Any]], str]:
    if value is None:
        return [], "not_provided"
    if not isinstance(value, dict) or value.get("verified") is not True:
        return [], "unverified_result_rejected"
    findings = value.get("findings")
    if not isinstance(findings, list):
        return [], "unverified_result_rejected"
    accepted = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        label = item.get("label", item.get("finding"))
        if not isinstance(label, str) or not label.strip():
            continue
        accepted.append({
            "label": label.strip(),
            "source": "verified_vision_result",
            "evidence_ref": item.get("evidence_ref"),
            "confidence": item.get("confidence"),
        })
    return accepted, "completed_verified"


def _parse_text_findings(content: Any, narrative: str) -> tuple[list[dict[str, str]], str]:
    try:
        result = json.loads(content if isinstance(content, str) else str(content))
    except (TypeError, ValueError, json.JSONDecodeError):
        return [], "invalid_structured_output"
    if not isinstance(result, dict) or not isinstance(result.get("findings"), list):
        return [], "invalid_structured_output"
    accepted = []
    for item in result["findings"]:
        if not isinstance(item, dict):
            continue
        label, quote = item.get("label"), item.get("source_quote")
        if not isinstance(label, str) or not isinstance(quote, str):
            continue
        label, quote = label.strip(), quote.strip()
        if label and quote and label in quote and quote in narrative:
            accepted.append({"label": label, "source": "field_text", "source_quote": quote})
    if result["findings"] and not accepted:
        return [], "ungrounded_output_rejected"
    return accepted, "completed" if accepted else "completed_no_grounded_findings"


def _field_investigation_record(
    data: dict[str, Any],
    *,
    narrative: str,
    admin_area: str | None,
    visit_time: str | None,
    source_kind: str,
    is_simulated: bool,
    data_source: str,
    gps: dict[str, float] | None,
    gps_status: str,
    photo_refs: list[Any],
    image_status: str,
    vision_execution: dict[str, Any],
    vision_findings: list[dict[str, Any]],
    text_findings: list[dict[str, str]],
    hazard_point_id: Any,
    slope_unit_id: Any,
    p6_slope_unit_id: str | None,
    spatial_ref_status: Any,
    spatial_object_source: Any,
    p6_mapping: dict[str, Any] | None,
) -> dict[str, Any]:
    record_id = _field_record_value(data, "basic_field_info", "record_id", "report_id", "调查记录编号")
    reporter = _field_record_value(
        data, "basic_field_info", "reporter", "reporter_name", "inspector", "巡查人员", "填报人", "报告人"
    )
    investigator = _field_record_value(
        data, "basic_field_info", "investigator", "investigator_name", "调查人员", "调查人"
    )
    reported_coordinates = _field_record_value(
        data, "spatial_location", "reported_coordinates", "coordinate_text", "coordinates", "经纬度", "坐标"
    )
    threats = data.get("threatened_objects")
    threat_values = {
        "types": _field_record_value(data, "threatened_objects", "types", "object_types", "承灾体类型"),
        "households": _field_record_value(data, "threatened_objects", "households", "household_count", "户数"),
        "people": _field_record_value(data, "threatened_objects", "people", "person_count", "人数"),
        "rooms": _field_record_value(data, "threatened_objects", "rooms", "room_count", "房间数"),
        "roads": _field_record_value(data, "threatened_objects", "roads", "road_count", "道路"),
        "road_name": _field_record_value(data, "threatened_objects", "road_name", "道路名称"),
        "road_grade": _field_record_value(data, "threatened_objects", "road_grade", "道路等级"),
        "livestock": _field_record_value(data, "threatened_objects", "livestock", "livestock_count", "牲畜数"),
        "asset_value": _field_record_value(data, "threatened_objects", "asset_value", "asset_value_cny", "财产损失估值"),
        "indirect_loss": _field_record_value(data, "threatened_objects", "indirect_loss", "indirect_loss_cny", "间接损失"),
    }
    threat_details = _field_record_value(data, "threatened_objects", "details", "objects", "承灾对象")
    if threat_details is None and isinstance(threats, (list, str)):
        threat_details = threats

    raw_disaster_type = data.get("disaster_type")
    if isinstance(raw_disaster_type, str) and raw_disaster_type.strip():
        disaster_type = raw_disaster_type.strip()
    else:
        disaster_type = _field_record_value(
            data, "disaster_type", "type", "label", "name", "hazard_type", "灾害类型"
        )
    disaster_type_code = _field_record_value(
        data, "disaster_type", "type_code", "hazard_type_code", "disaster_type_code", "灾害类型编码"
    )
    conclusion = _field_record_value(
        data, "investigation_conclusions", "summary", "conclusion", "investigation_conclusion", "调查结论"
    )
    causes = _field_record_list(_field_record_value(
        data, "investigation_conclusions", "causes", "cause_analysis", "诱发因素"
    ))
    recommendations = _field_record_list(_field_record_value(
        data, "investigation_conclusions", "recommendations", "disposal_recommendations", "建议措施"
    ))
    measurement_status = _field_record_value(
        data, "deformation_signs", "measurement_status", "测量状态"
    )
    movement_confirmed = _field_record_value(
        data, "deformation_signs", "movement_confirmed", "位移已确认"
    )
    explicit_signs = _field_record_list(_field_record_value(
        data, "deformation_signs", "observed_signs", "signs", "变形迹象"
    ))
    deformation_observations = [
        item if isinstance(item, dict) else {
            "label": item,
            "source": "field_report",
            "verification_status": "source_reported",
        }
        for item in explicit_signs
    ]
    deformation_observations.extend(text_findings)
    deformation_observations.extend(vision_findings)

    source_claims = _field_record_value(data, "photo_recognition", "source_claims")
    if source_claims is None:
        source_claims = data.get("source_photo_claims")
    if image_status == "completed_verified":
        photo_verification = "verified"
    elif (
        image_status == "completed_dify"
        or vision_execution.get("output_verification_status") == "unverified"
        or source_claims is not None
    ):
        photo_verification = "unverified"
    elif photo_refs:
        photo_verification = "pending"
    else:
        photo_verification = "not_provided"

    items_to_verify = _field_record_list(_field_record_value(
        data, "items_to_verify", "items", "items_to_verify", "待核实事项"
    ))

    def add_verification_item(item: str) -> None:
        if item not in items_to_verify:
            items_to_verify.append(item)

    if gps_status != "valid":
        if reported_coordinates is None:
            add_verification_item("设备 GPS 坐标未提供或无效，现场点位关联待核验。")
        else:
            add_verification_item("设备 GPS 坐标未提供或无效；原始报告坐标单独保留，未转换为 GPS 或用于空间关联。")
    if (photo_refs or source_claims is not None) and photo_verification != "verified":
        add_verification_item("照片识别结果未核验，灾害类型、变形迹象、承灾体、新鲜程度、阶段和风险等级保持缺失。")
    if vision_execution.get("status") == "source_bytes_unavailable":
        add_verification_item("照片引用已保留，但服务端可读取的图片字节不可用。")
    if not any(value is not None for value in threat_values.values()) and threat_details is None:
        add_verification_item("受威胁对象及数量未提供，待现场核查。")
    if threat_values["roads"] is not None and (
        threat_values["road_name"] is None or threat_values["road_grade"] is None
    ):
        add_verification_item("受威胁道路名称或等级未提供，待核查。")
    if conclusion is None and not causes and not recommendations:
        add_verification_item("调查结论、成因和处置建议未提供。")
    if measurement_status == "not_measured":
        add_verification_item("现场迹象尺寸尚未量测，待补测。")
    if movement_confirmed is False:
        add_verification_item("持续位移尚未确认，待复测。")
    if isinstance(p6_mapping, dict) and p6_mapping.get("mapping_status") == "candidate_unverified":
        add_verification_item("P6 坡单元关系仍为未核验候选。")
    if _field_record_value(data, "deformation_signs", "review_required", "需人工审核") is True:
        add_verification_item("该现场记录标记为需人工审核。")

    spatial_location = {
        "location": _field_record_value(data, "spatial_location", "location", "address", "详细地址", "地点"),
        "reported_coordinates": reported_coordinates,
        "coordinate_status": _field_record_value(
            data, "spatial_location", "coordinate_status", "source_crs_status", "坐标核验状态"
        ),
        "elevation_m": _field_record_value(data, "spatial_location", "elevation_m", "elevation", "海拔"),
        "gps": gps,
        "gps_status": gps_status,
        "hazard_point_id": hazard_point_id,
        "hazard_point_name": _field_record_value(
            data, "spatial_location", "hazard_point_name", "隐患点名称"
        ),
        "slope_unit_id": slope_unit_id,
        "p6_slope_unit_id": p6_slope_unit_id,
        "p6_mapping": p6_mapping,
        "spatial_ref_status": spatial_ref_status,
        "spatial_object_source": spatial_object_source,
    }
    return {
        "basic_field_info": {
            "record_id": record_id,
            "reporter": reporter,
            "investigator": investigator,
            "visit_time": visit_time,
            "admin_area": admin_area,
            "narrative": narrative or None,
            "source_kind": source_kind,
            "is_simulated": is_simulated,
            "data_source": data_source,
        },
        "spatial_location": spatial_location,
        "disaster_type": {
            "type": disaster_type,
            "type_code": disaster_type_code,
            "verification_status": "source_reported" if disaster_type is not None or disaster_type_code is not None else "missing",
        },
        "photo_recognition": {
            "status": image_status,
            "verification_status": photo_verification,
            "source": vision_execution.get("execution_engine"),
            "photo_refs": photo_refs,
            "source_claims": source_claims,
            "verified_findings": vision_findings,
            "recognized_fields": {
                "image_type": None,
                "disaster_type": None,
                "deformation_signs": None,
                "threatened_object_types": None,
                "freshness": None,
                "stage": None,
                "risk_level": None,
            },
        },
        "deformation_signs": {
            "observations": deformation_observations,
            "measurement_status": measurement_status,
            "movement_confirmed": movement_confirmed,
            "verification_status": (
                "source_reported" if explicit_signs or measurement_status is not None or movement_confirmed is not None
                else "source_grounded" if text_findings else "missing"
            ),
        },
        "threatened_objects": {
            **threat_values,
            "details": threat_details,
            "verification_status": "source_reported" if any(value is not None for value in threat_values.values()) or threat_details is not None else "missing",
        },
        "investigation_conclusions": {
            "summary": conclusion,
            "causes": causes,
            "recommendations": recommendations,
            "verification_status": "source_reported" if conclusion is not None or causes or recommendations else "missing",
        },
        "items_to_verify": items_to_verify,
    }


async def _analyze_text(narrative: str) -> tuple[list[dict[str, str]], str]:
    if not narrative:
        return [], "not_applicable"
    if not llm_enabled():
        return [], "llm_not_configured"
    try:
        response = await build_llm().ainvoke([
            ("system", "你是现场险情文字整理助手。只从巡查原文提取明确写出的裂缝、滑移、变形、渗水等迹象；不分析照片、不补充原文没有的事实。label 必须是 source_quote 中的原文连续词组；不得把‘未见’‘未发现’等否定表述当作已出现的迹象。只输出JSON：{\"findings\":[{\"label\":\"原文词组\",\"source_quote\":\"原文连续片段\"}]}。没有明确迹象时findings为空。"),
            ("user", narrative),
        ])
    except Exception:
        return [], "llm_unavailable"
    return _parse_text_findings(response.content, narrative)


async def process_field_report(
    input: dict[str, Any],
    evidence: list[dict[str, Any]] | None = None,
    *,
    execute_dify: bool = True,
    execute_llm: bool = True,
) -> dict[str, Any]:
    """Normalize field evidence and, when configured, run the A2 image Chatflow."""
    data = input if isinstance(input, dict) else {}
    narrative = _first_text(data, "text", "inspection_text", "巡查文本", "narrative", "description")
    if not narrative:
        nested_narrative = _field_record_value(data, "basic_field_info", "narrative", "text", "巡查文本", "description")
        narrative = nested_narrative.strip() if isinstance(nested_narrative, str) else ""
    photo_refs = _photo_refs(data)
    manual_corrections = _manual_corrections(data)
    gps_value = data.get("gps")
    if gps_value is None:
        gps_value = data.get("GPS")
    if gps_value is None:
        gps_value = _field_record_value(data, "spatial_location", "gps")
    gps, gps_status = _normalize_gps(gps_value)
    vision_findings, vision_result_status = _verified_vision_findings(data.get("structured_vision_result"))
    text_findings, text_status = await _analyze_text(narrative) if execute_llm else ([], "not_run")
    is_simulated = data.get("is_simulated") is True or data.get("source_kind") == "SIMULATED"
    source_kind = "SIMULATED" if is_simulated else "FIELD_REPORT"
    data_source = _first_text(data, "data_source") or (
        "simulated_field_input" if is_simulated else "field_report_input"
    )
    admin_area = _first_text(data, "admin_area", "county", "county_name") or None
    if admin_area is None:
        nested_admin_area = _field_record_value(data, "basic_field_info", "admin_area", "county", "county_name", "行政区")
        admin_area = nested_admin_area.strip() if isinstance(nested_admin_area, str) and nested_admin_area.strip() else None
    slope_unit_id = _reference_id(data, "slope_unit_id", "slope_unit")
    hazard_point_id = _reference_id(data, "hazard_point_id", "hazard_point")
    p6_slope_unit_id = _confirmed_p6_slope_unit_id(data)
    spatial_ref_status = data.get("spatial_ref_status")
    spatial_object_source = data.get("spatial_object_source")
    p6_mapping = data.get("p6_mapping")
    p6_mapping = dict(p6_mapping) if isinstance(p6_mapping, dict) else None
    visit_time = _first_text(
        data, "visit_time", "inspection_time", "occurred_at", "event_time", "timestamp", "巡查时间"
    ) or None
    if visit_time is None:
        nested_visit_time = _field_record_value(data, "basic_field_info", "visit_time", "inspection_time", "occurred_at", "巡查时间")
        visit_time = nested_visit_time.strip() if isinstance(nested_visit_time, str) and nested_visit_time.strip() else None
    correlation_id = _first_text(data, "correlation_id") or str(uuid4())

    if vision_result_status == "completed_verified":
        image_status = vision_result_status
        vision_execution = {
            "execution_engine": "caller_verified",
            "status": "completed_verified",
            "analysis_status": image_status,
            "output_verification_status": "verified",
            "outputs": {},
            "uploaded_file_ids": [],
            "trace_id": None,
            "task_id": None,
            "workflow_run_id": None,
            "conversation_id": None,
            "error": None,
        }
    elif photo_refs and execute_dify:
        vision_execution = await run_a2_field_vision(
            data,
            photo_refs=photo_refs,
            narrative=narrative,
            admin_area=admin_area,
            gps=gps,
            visit_time=visit_time,
            hazard_point_id=hazard_point_id,
            slope_unit_id=slope_unit_id,
            correlation_id=correlation_id,
            source_kind=source_kind,
            is_simulated=is_simulated,
            data_source=data_source,
        )
        image_status = vision_execution.get("analysis_status", "pending_visual_model")
    elif photo_refs:
        vision_execution = {
            "execution_engine": "local",
            "status": "deferred_to_phase2",
            "analysis_status": "pending_visual_model",
            "outputs": {},
            "uploaded_file_ids": [],
            "trace_id": None,
            "task_id": None,
            "workflow_run_id": None,
            "conversation_id": None,
            "error": None,
        }
        image_status = vision_execution.get("analysis_status", "pending_visual_model")
    else:
        image_status = "not_configured"
        vision_execution = {
            "execution_engine": "local",
            "status": "not_applicable",
            "analysis_status": image_status,
            "outputs": {},
            "uploaded_file_ids": [],
            "trace_id": None,
            "task_id": None,
            "workflow_run_id": None,
            "conversation_id": None,
            "error": None,
        }

    dify_outputs = vision_execution.get("outputs", {})
    output_verification_status = vision_execution.get("output_verification_status")
    if image_status == "completed_dify":
        output_verification_status = "unverified"
    verified_outputs = dify_outputs if output_verification_status == "verified" else {}
    visual_observation = {
        "status": image_status,
        "source": vision_execution.get("execution_engine"),
        "verified": output_verification_status == "verified",
        "source_kind": source_kind,
        "is_simulated": is_simulated,
        "data_source": data_source,
        "summary": verified_outputs.get("aiReportDetail"),
        "risk_label": verified_outputs.get("aiRiskLabel"),
        "risk_level": verified_outputs.get("aiRiskLevel"),
        "properties": verified_outputs.get("aiVisionProps", {}),
        "observations": vision_findings,
        "photo_refs": photo_refs,
        "spatial_association": {
            "admin_area": admin_area,
            "gps": gps,
            "hazard_point_id": hazard_point_id,
            "slope_unit_id": slope_unit_id,
            "p6_slope_unit_id": p6_slope_unit_id,
            "spatial_ref_status": spatial_ref_status,
            "spatial_object_source": spatial_object_source,
        },
    }

    correction_findings = [
        {"source": "manual_correction", "correction": correction}
        for correction in manual_corrections
    ]
    findings = [*text_findings, *vision_findings, *correction_findings]
    uncertainty = [str(item) for item in data.get("uncertainty", []) if isinstance(item, str)] \
        if isinstance(data.get("uncertainty", []), list) else []
    if p6_mapping and p6_mapping.get("mapping_status") == "candidate_unverified":
        uncertainty.append("P6 坡单元映射仅为未核验候选，未认定与本次巡查点位完成空间关联。")
    missing_fields = []
    if not admin_area:
        missing_fields.append("admin_area")
        uncertainty.append("未提供县市/行政区，需人工补充或通过可靠GIS关联确认。")
    if gps_status != "valid":
        missing_fields.append("gps")
        uncertainty.append("GPS缺失或格式无效，未执行空间点位关联。")
    if photo_refs and image_status == "pending_visual_model":
        if vision_execution.get("status") == "not_configured":
            uncertainty.append("Dify A2 未配置，本次仅保留原图引用，视觉识别仍待处理。")
        elif vision_execution.get("status") == "source_bytes_unavailable":
            uncertainty.append("现有照片引用未提供服务端可读取的图片字节，未将浏览器/OSS 引用冒充为 Dify 文件。")
        elif vision_execution.get("status") == "image_input_not_enabled":
            uncertainty.append("当前发布的 Dify A2 契约未启用图片输入，照片引用保留，视觉识别待处理。")
        elif vision_execution.get("status") == "dify_parameters_unavailable":
            uncertainty.append("无法读取当前 Dify A2 发布契约，未上传照片或调用视觉识别，照片引用保留。")
        elif vision_execution.get("execution_engine") == "dify":
            uncertainty.append("Dify A2 未返回可用的结构化视觉结果，原图保留且识别结论未采纳。")
        else:
            uncertainty.append("已接收照片引用，但当前没有可用的视觉识别结果。")
    if vision_result_status == "unverified_result_rejected":
        uncertainty.append("输入的视觉结果未标记为已核验，未采纳其中的识别结论。")
    if output_verification_status == "unverified":
        uncertainty.append("Dify 返回的视觉结果尚未核验，未采纳为结构化识别结论。")
    if narrative and text_status == "llm_not_configured":
        uncertainty.append("文字迹象尚未由已配置的语言模型整理。")
    if not narrative and not photo_refs and not findings:
        missing_fields.append("field_evidence")

    evidence_anchors: list[dict[str, Any]] = []
    if narrative:
        evidence_anchors.append({"kind": "field_text", "source_quote": narrative, "source": "caller_input"})
    for ref in photo_refs:
        evidence_anchors.append({"kind": "photo_reference", "reference": ref, "analysis_status": image_status})
    for correction in manual_corrections:
        evidence_anchors.append({"kind": "manual_correction", "correction": correction})
    if isinstance(evidence, list):
        evidence_anchors.extend(item for item in evidence if isinstance(item, dict))

    event_status = "ready_for_a4_review" if "field_evidence" not in missing_fields else "incomplete_input"
    if output_verification_status == "verified":
        visual_analysis = "completed"
    elif image_status == "completed_dify":
        visual_analysis = "pending_verification"
    elif photo_refs:
        visual_analysis = "pending"
    else:
        visual_analysis = "not_applicable"
    evidence_ids = [
        str(item["evidence_id"])
        for item in evidence_anchors
        if item.get("evidence_id") not in (None, "")
    ]
    field_investigation_record = _field_investigation_record(
        data,
        narrative=narrative,
        admin_area=admin_area,
        visit_time=visit_time,
        source_kind=source_kind,
        is_simulated=is_simulated,
        data_source=data_source,
        gps=gps,
        gps_status=gps_status,
        photo_refs=photo_refs,
        image_status=image_status,
        vision_execution=vision_execution,
        vision_findings=vision_findings,
        text_findings=text_findings,
        hazard_point_id=hazard_point_id,
        slope_unit_id=slope_unit_id,
        p6_slope_unit_id=p6_slope_unit_id,
        spatial_ref_status=spatial_ref_status,
        spatial_object_source=spatial_object_source,
        p6_mapping=p6_mapping,
    )
    result = {
        "status": event_status,
        "event_id": data.get("event_id"),
        "summary": narrative or visual_observation.get("summary"),
        "execution_engine": vision_execution.get("execution_engine", "local"),
        "trace_id": vision_execution.get("trace_id"),
        "source_kind": source_kind,
        "correlation_id": correlation_id,
        "event_status": event_status,
        "occurred_at": visit_time,
        "admin_area": admin_area,
        "slope_unit_id": slope_unit_id,
        "p6_slope_unit_id": p6_slope_unit_id,
        "hazard_point_id": hazard_point_id,
        "spatial_ref_status": spatial_ref_status,
        "spatial_object_source": spatial_object_source,
        "is_simulated": is_simulated,
        "data_source": data_source,
        "field_report": {
            "narrative": narrative or None,
            "photo_refs": photo_refs,
            "manual_corrections": manual_corrections,
            "visit_time": visit_time,
            "gps": gps,
            "gps_status": gps_status,
        },
        "field_investigation_record": field_investigation_record,
        "findings": findings,
        "visual_analysis": visual_analysis,
        "image_analysis_status": image_status,
        "visual_observation": visual_observation,
        "vision_execution": vision_execution,
        "text_analysis_status": text_status,
        "evidence_anchors": evidence_anchors,
        "evidence_ids": evidence_ids,
        "missing_fields": missing_fields,
        "uncertainty": list(dict.fromkeys(uncertainty)),
        "trace": [
            {"step": "normalize_field_report", "status": "completed"},
            {"step": "text_analysis", "status": text_status},
            {"step": "image_analysis", "status": image_status},
        ],
    }
    if p6_mapping is not None:
        result["p6_mapping"] = p6_mapping
    return result
