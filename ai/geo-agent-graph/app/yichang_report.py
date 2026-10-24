"""Build a traceable Yichang investigation and review report draft.

This adapter only organizes facts already supplied by business services. It does
not persist, review, archive, or infer missing business facts.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any


UNKNOWN = "unknown"
_REPORT_VALUE_LIMIT = 240


def build_report_draft(
    event: Mapping[str, Any] | None,
    tasks: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    feedback: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    risk_review: Mapping[str, Any] | None,
    attachments: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    *,
    task_proposals: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    execution_trace: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    evidence_status: Any = None,
) -> dict[str, Any]:
    """Return a structured draft from supplied event, task, and evidence facts.

    Input records are copied into the result unchanged under ``source_facts``;
    derived associations only reference identifiers present in those records.
    """
    event_record = _record(event)
    risk_record = _record(risk_review)
    investigation_record = _nested_mapping(
        event_record, "field_investigation_record", "fieldInvestigationRecord",
    )
    spatial_location = _nested_mapping(investigation_record, "spatial_location", "spatialLocation")
    disaster_type = _nested_mapping(investigation_record, "disaster_type", "disasterType")
    task_records = _records(tasks)
    task_proposal_records = _records(task_proposals)
    feedback_records = _records(feedback)
    attachment_records = _records(attachments)
    execution_records = _records(execution_trace)

    event_id = _first_event(event_record, "event_id", "eventId", "handleId", "id")
    task_ids = _identifiers(task_records, "task_id", "taskId", "id")
    feedback_ids = _identifiers(
        feedback_records, "feedback_id", "feedbackId", "history_id", "historyId", "id"
    )
    warning_event_ids = _all_identifiers(
        event_record, task_records, feedback_records, risk_record, attachment_records,
        keys=("warning_event_id", "warningEventId"),
    )
    chain_ids = _all_identifiers(
        event_record, task_records, feedback_records, risk_record, attachment_records,
        keys=("chain_id", "chainId"),
    )
    correlation_ids = _all_identifiers(
        event_record, task_records, feedback_records, risk_record, attachment_records,
        keys=("correlation_id", "correlationId"),
    )
    trace_ids = _all_identifiers(
        event_record, task_records, feedback_records, risk_record, attachment_records,
        keys=("trace_id", "traceId"),
    )
    trace_ids = _unique([
        *trace_ids,
        *_execution_trace_ids(execution_trace),
    ])
    existing_report_ids = _unique(
        [
            *(_identifiers([event_record], "report_id", "reportId")),
            *(_identifiers(task_records, "report_id", "reportId")),
            *(_identifiers(feedback_records, "report_id", "reportId")),
            *(_identifiers([risk_record], "report_id", "reportId")),
            *(_identifiers(attachment_records, "report_id", "reportId")),
        ]
    )

    lineage = _lineage(
        event_record,
        task_records,
        task_proposal_records,
        feedback_records,
        risk_record,
        attachment_records,
        execution_records,
    )
    is_simulated = any(source["is_simulated"] is True for source in lineage)
    missing_fields: list[str] = []
    draft_tasks = _draft_records(
        task_records, "task_id", ("task_id", "taskId", "id"), "tasks", missing_fields
    )
    draft_feedback = _draft_records(
        feedback_records,
        "feedback_id",
        ("feedback_id", "feedbackId", "history_id", "historyId", "id"),
        "feedback",
        missing_fields,
    )
    draft_attachments = _draft_records(
        attachment_records,
        "attachment_id",
        ("attachment_id", "attachmentId", "file_id", "fileId", "id"),
        "attachments",
        missing_fields,
    )

    event_type = _first_event_detail(
        event_record, "disaster_type", "disasterType", "event_type", "eventType", "hazard_type", "hazardType",
    )
    if not _present(event_type):
        event_type = _first_report_value(disaster_type, ("type", "name", "label"))
    if not _present(event_type) and _present(disaster_type.get("type_code")):
        event_type = f"未确认（原始类型编码 {disaster_type['type_code']}；名称待核实）"
        missing_fields.append("field_investigation_record.disaster_type.type")

    location = _first_event_detail(
        event_record, "location", "address", "detailedAddress", "checkCenterLocation", "geometry_ref", "geometryRef",
    )
    if not _present(location):
        location = _first_report_value(spatial_location, ("location", "address"))

    basic_info = {
        "event_id": _known_or_missing(event_id, "event.event_id", missing_fields),
        "source_kind": _known_or_missing(
            _first_event(event_record, "source_kind", "sourceKind", "source_type", "sourceType"),
            "event.source_kind",
            missing_fields,
        ),
        "event_type": _known_or_missing(event_type, "event.event_type", missing_fields),
        "occurred_at": _known_or_missing(
            _first_event_detail(
                event_record, "occurred_at", "occurredAt", "occurrenceTime", "event_time", "eventTime",
                "reported_at", "reportedAt",
            ),
            "event.occurred_at",
            missing_fields,
        ),
        "location": _known_or_missing(location, "event.location", missing_fields),
        "slope_unit_id": _known_or_missing(
            _first_event_detail(event_record, "slope_unit_id", "slopeUnitId"),
            "event.slope_unit_id",
            missing_fields,
        ),
        "hazard_point_id": _known_or_missing(
            _first_event_detail(event_record, "hazard_point_id", "hazardPointId"),
            "event.hazard_point_id",
            missing_fields,
        ),
    }
    for source_name, present in (
        ("risk_review", bool(risk_record)),
        ("tasks", bool(task_records)),
        ("feedback", bool(feedback_records)),
        ("attachments", bool(attachment_records)),
    ):
        if not present:
            missing_fields.append(source_name)

    return {
        "report_type": "yichang_event_investigation_review",
        "title": "宜昌地质灾害事件调查与处置复盘报告（草案）",
        "status": "draft_unreviewed_unarchived",
        "generation_status": "not_started",
        "review_status": "not_reviewed",
        "archive_status": "not_archived",
        "is_simulated": is_simulated,
        "simulation_status": "simulated" if is_simulated else "not_marked_as_simulated",
        "associations": {
            "event_id": event_id if _present(event_id) else UNKNOWN,
            "warning_event_ids": warning_event_ids,
            "task_ids": task_ids,
            "feedback_ids": feedback_ids,
            "chain_ids": chain_ids,
            "correlation_ids": correlation_ids,
            "existing_report_ids": existing_report_ids,
            "new_report_id": UNKNOWN,
        },
        "source_metadata": {
            "source_kind": _first_event(event_record, "source_kind", "sourceKind", "source_type", "sourceType") or UNKNOWN,
            "correlation_ids": correlation_ids,
            "trace_ids": trace_ids,
            "is_simulated": is_simulated,
            "data_source": _first(event_record, "data_source", "dataSource") or UNKNOWN,
        },
        "sections": {
            "basic_info": basic_info,
            "risk_review": risk_record if risk_record else UNKNOWN,
            "disposal_tasks": draft_tasks if draft_tasks else UNKNOWN,
            "task_proposals": task_proposal_records if task_proposal_records else UNKNOWN,
            "field_feedback": draft_feedback if draft_feedback else UNKNOWN,
            "evidence": draft_attachments if draft_attachments else UNKNOWN,
            "review_conclusion": UNKNOWN,
        },
        "source_facts": {
            "event": event_record if event_record else UNKNOWN,
            "tasks": task_records,
            "task_proposals": task_proposal_records,
            "feedback": feedback_records,
            "risk_review": risk_record if risk_record else UNKNOWN,
            "attachments": attachment_records,
            "execution_trace": execution_trace if _present(execution_trace) else UNKNOWN,
        },
        "evidence_status": evidence_status if _present(evidence_status) else UNKNOWN,
        "evidence_ids": _evidence_ids(lineage),
        "data_lineage": lineage,
        "missing_fields": missing_fields,
    }


def render_local_report_markdown(draft: Mapping[str, Any]) -> str:
    """Render supplied draft facts as a readable, explicitly unapproved report."""
    sections = draft.get("sections") if isinstance(draft.get("sections"), Mapping) else {}
    associations = draft.get("associations") if isinstance(draft.get("associations"), Mapping) else {}
    source_metadata = draft.get("source_metadata") if isinstance(draft.get("source_metadata"), Mapping) else {}
    source_facts = draft.get("source_facts") if isinstance(draft.get("source_facts"), Mapping) else {}
    trace_ids = source_metadata.get("trace_ids") or _source_identifiers(source_facts, "trace_id", "traceid")
    scenario_ids = _source_identifiers(source_facts, "scenario_id", "scenarioid")
    basic_info = sections.get("basic_info") if isinstance(sections.get("basic_info"), Mapping) else {}

    def visible_fields(fields):
        if not package_materials:
            return fields
        return tuple((label, aliases) for label, aliases in fields if not label.endswith("ID"))

    package_materials = draft.get("is_simulated") is True
    generation_line = (
        "> 报告依据：随软件交付的秭归市事件资料及已保存的处置记录。"
        if package_materials else "> 报告依据：当前事件已保存的业务记录。"
    )
    data_source_line = (
        "> 数据来源：随软件交付的业务资料（非实时设备采集）。"
        if package_materials else f"> 数据来源：{_report_value(source_metadata.get('data_source'))}"
    )
    data_property_line = (
        "> 数据属性：历史事件资料，不代表实时设备状态或正式审核结果。"
        if package_materials else "> 数据属性：以原始记录标注为准。"
    )

    lines = [
        f"# {_report_title(draft)}",
        "",
        generation_line,
        data_source_line,
        data_property_line,
        "",
    ]
    lines.extend(render_report_status_markdown(draft))
    lines.append("")
    lines.extend(_render_business_report_sections(draft))
    if package_materials:
        lines.extend([
            "",
            "## 业务记录",
            "- 事件、任务、反馈和审核记录已关联保存，可在协同处置中心按事件查询。",
            "",
        ])
    else:
        lines.extend([
            "",
            "## 结构化证据与关联标识",
            "- 事件、任务、反馈、附件、审核与执行留痕保存在报告结构中。",
            "",
            "## 关联标识",
            f"- 事件 ID：{_report_value(associations.get('event_id'))}",
            f"- 任务 ID：{_report_ids(associations.get('task_ids'))}",
            f"- 反馈 ID：{_report_ids(associations.get('feedback_ids'))}",
            f"- 预警事件 ID：{_report_ids(associations.get('warning_event_ids'))}",
            f"- 链路 ID：{_report_ids(associations.get('chain_ids'))}",
            f"- 关联 ID：{_report_ids(associations.get('correlation_ids'))}",
            f"- 场景 ID：{_report_ids(scenario_ids)}",
            f"- 追踪 ID：{_report_ids(trace_ids)}",
            f"- 既有报告 ID：{_report_ids(associations.get('existing_report_ids'))}",
            f"- 新报告 ID：{_report_value(associations.get('new_report_id'))}",
            f"- 证据 ID：{_report_ids(draft.get('evidence_ids'))}",
            "",
        ])
    lines.append("## 基本信息")
    for label, key in (
        ("事件 ID", "event_id"),
        ("来源类型", "source_kind"),
        ("灾害类型", "event_type"),
        ("发生时间", "occurred_at"),
        ("地点", "location"),
        ("坡单元 ID", "slope_unit_id"),
        ("隐患点 ID", "hazard_point_id"),
    ):
        if package_materials and label == "事件 ID":
            continue
        lines.append(f"- {label}：{_report_value(basic_info.get(key))}")

    risk_review = sections.get("risk_review") if isinstance(sections.get("risk_review"), Mapping) else {}
    lines.extend(_render_selected_fields("风险/复核状态", risk_review, (
        ("决策状态", ("decision_status", "review_status", "status")),
        ("执行引擎", ("execution_engine",)),
        ("建议来源", ("recommendation_engine",)),
        ("模型/工作流状态", ("llm_status", "model_status", "modelStatus")),
        ("正式预警已创建", ("formal_warning_created",)),
        ("任务已创建", ("task_created",)),
    ), required=("决策状态",)))
    four_natures = risk_review.get("four_natures") or risk_review.get("assessments")
    lines.extend(_render_four_natures(four_natures))
    p6_snapshot = risk_review.get("p6_snapshot")
    if not isinstance(p6_snapshot, Mapping):
        model_status = risk_review.get("model_status")
        p6_snapshot = model_status.get("p6_snapshot") if isinstance(model_status, Mapping) else None
    if isinstance(p6_snapshot, Mapping):
        lines.extend(_render_p6_static_snapshot(p6_snapshot))
    p6_candidates = sections.get("p6_candidates")
    if isinstance(p6_candidates, Mapping):
        lines.extend(_render_p6_candidate_report_section(p6_candidates))
    monitoring = risk_review.get("monitoring")
    monitoring_fields = (
        ("状态", ("status", "monitoring_status")),
        ("来源", ("source", "data_source")),
        ("模型", ("model",)),
        ("版本", ("version",)),
        ("摘要", ("summary",)),
        ("阈值用途标记", ("trigger_rule_scope",)),
        ("证据 ID", ("evidence_ids", "evidence_id")),
    )
    lines.extend(_render_selected_fields(
        "监测状态", monitoring if isinstance(monitoring, Mapping) else {},
        visible_fields(monitoring_fields), required=("状态",),
    ))
    lines.extend(_render_selected_records(
        "处置动作建议", risk_review.get("action_items"), "动作", _ACTION_FIELDS,
        required=("动作",),
    ))
    lines.extend(_render_selected_records(
        "处置任务", sections.get("disposal_tasks"), "任务", visible_fields(_TASK_FIELDS),
        required=("任务状态",) if package_materials else ("任务 ID", "任务状态"),
    ))
    lines.extend(_render_selected_records(
        "任务提案", sections.get("task_proposals"), "提案", visible_fields(_TASK_PROPOSAL_FIELDS),
        required=("提案状态",) if package_materials else ("提案 ID", "提案状态"),
    ))
    lines.extend(_render_selected_records(
        "现场反馈", sections.get("field_feedback"), "反馈", visible_fields(_FEEDBACK_FIELDS),
        required=("状态",) if package_materials else ("反馈 ID",),
    ))
    lines.extend(_render_selected_records(
        "证据与附件", sections.get("evidence"), "证据", visible_fields(_EVIDENCE_FIELDS),
        required=("来源类型",) if package_materials else ("证据 ID",),
    ))
    lines.extend(_render_evidence_status(draft.get("evidence_status")))
    lines.extend(_render_selected_fields(
        "现有审核结论", {"conclusion": sections.get("review_conclusion")},
        (("结论", ("conclusion",)),), required=("结论",),
    ))
    lines.extend(_render_selected_records(
        "资料来源与业务状态", draft.get("data_lineage"), "来源", visible_fields((
            ("来源类型", ("source_type",)),
            ("来源 ID", ("source_id",)),
            ("数据来源", ("data_source",)),
            ("模型状态", ("model_status",)),
            ("模型版本", ("model_version",)),
            ("证据 ID", ("evidence_ids",)),
        )), required=("来源类型",),
    ))
    source_status = draft.get("source_status")
    if isinstance(source_status, Mapping):
        source_status_fields = (
            ("事件读取", ("event",)),
            ("现场记录读取", ("scene_record",)),
            ("任务列表读取", ("tasks",)),
            ("任务提案读取", ("task_proposals",)),
            ("反馈读取", ("feedback",)),
            ("证据读取", ("evidence", "attachments")),
            ("复核记录读取", ("risk_review",)),
            ("辅助决策记录读取", ("a4_execution",)),
            ("本地业务记录读取", ("gold_store",)),
        )
        if any(key in source_status for _, aliases in source_status_fields for key in aliases):
            lines.extend(_render_selected_fields(
                "持久化读取状态", source_status, source_status_fields,
            ))
        task_reads = source_status.get("task_reads")
        if isinstance(task_reads, Sequence) and not isinstance(task_reads, (str, bytes, bytearray)) and task_reads:
            lines.extend(_render_selected_records(
                "任务与反馈读取状态", task_reads, "任务", (
                    ("任务 ID", ("task_id",)),
                    ("任务记录读取", ("record_status",)),
                    ("反馈读取", ("feedback_status",)),
                ), required=("任务 ID", "任务记录读取", "反馈读取"),
            ))

    missing_fields = draft.get("missing_fields")
    lines.extend(["## 缺失字段", ""])
    if isinstance(missing_fields, Sequence) and not isinstance(missing_fields, (str, bytes, bytearray)) and missing_fields:
        lines.extend(f"- {_report_value(field)}" for field in missing_fields)
    else:
        lines.append("- 未记录缺失字段")
    return "\n".join(lines).rstrip() + "\n"


def render_report_status_markdown(draft: Mapping[str, Any]) -> list[str]:
    """Render one canonical status block from the structured report states."""
    generation = draft.get("generation") if isinstance(draft.get("generation"), Mapping) else {}
    generation_status = draft.get("generation_status", generation.get("status", UNKNOWN))
    review_status = draft.get("review_status", UNKNOWN)
    archive_status = draft.get("archive_status", UNKNOWN)
    return [
        "## 报告状态",
        f"- 生成状态：{_report_value(generation_status)}",
        f"- 报告状态：{_report_value(_effective_report_status(draft, review_status, archive_status))}",
        f"- 审核状态：{_report_value(review_status)}（{_status_label(review_status, 'review')}）",
        f"- 归档状态：{_report_value(archive_status)}（{_status_label(archive_status, 'archive')}）",
        f"- 证据库状态：{_report_value(draft.get('evidence_library_status'))}",
    ]


def sync_report_markdown_status(report: Mapping[str, Any]) -> str | None:
    """Replace only a report's Markdown status block and synchronize its title."""
    text = report.get("report_text")
    if not isinstance(text, str):
        return None

    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    title_index = next((
        index for index, line in enumerate(lines)
        if line.rstrip("\r\n").startswith("# ")
    ), None)
    if title_index is not None:
        title_line = lines[title_index]
        title_text = title_line.rstrip("\r\n")[2:].strip()
        synchronized_title = _report_title({**report, "title": title_text})
        line_ending = "\r\n" if title_line.endswith("\r\n") else "\n" if title_line.endswith("\n") else ""
        lines[title_index] = f"# {synchronized_title}{line_ending}"

    status_index = next((
        index for index, line in enumerate(lines)
        if line.rstrip("\r\n").strip() == "## 报告状态"
    ), None)
    status_block = newline.join(render_report_status_markdown(report)) + newline
    if status_index is not None:
        end_index = next((
            index for index in range(status_index + 1, len(lines))
            if lines[index].lstrip().startswith("#")
        ), len(lines))
        if end_index < len(lines):
            status_block += newline
        lines[status_index:end_index] = [status_block]
    else:
        insert_at = title_index + 1 if title_index is not None else 0
        lines[insert_at:insert_at] = [status_block + newline]
    return "".join(lines)


def _effective_report_status(
    report: Mapping[str, Any], review_status: Any, archive_status: Any,
) -> Any:
    archive_value = str(archive_status or "").strip().casefold()
    if archive_value in {"archived", "indexed", "pending_a1_verification", "已归档", "已入库"}:
        return archive_status
    review_value = str(review_status or "").strip().casefold()
    if review_value in {"approved", "passed", "通过", "已审核"}:
        return "approved_pending_archive" if archive_value in {"pending_archive", "not_archived", "未归档"} else review_status
    return report.get("status", UNKNOWN)


def _report_title(draft: Mapping[str, Any]) -> str:
    title = str(draft.get("title") or "宜昌地质灾害事件调查与处置复盘报告")
    review_status = str(draft.get("review_status") or "").casefold()
    archive_status = str(draft.get("archive_status") or "").casefold()
    finalized = review_status in {"approved", "passed", "通过", "已审核"} or archive_status in {
        "archived", "indexed", "已归档", "已入库",
    }
    if finalized:
        title = title.replace("（草案）", "").replace("(草案)", "")
    return title


def _status_label(value: Any, kind: str) -> str:
    normalized = str(value or "").strip().casefold()
    labels = {
        "review": {
            "not_reviewed": "未审核",
            "pending_review": "待审核",
            "approved": "已审核",
            "passed": "已审核",
            "rejected": "审核未通过",
            "通过": "已审核",
            "已审核": "已审核",
        },
        "archive": {
            "not_archived": "未归档",
            "pending_archive": "待归档",
            "pending_a1_verification": "待完成 A1 核验",
            "archived": "已归档",
            "indexed": "已入库",
            "已归档": "已归档",
            "已入库": "已入库",
        },
    }
    return labels.get(kind, {}).get(normalized, "状态未映射")


def _render_business_report_sections(draft: Mapping[str, Any]) -> list[str]:
    source_facts = draft.get("source_facts") if isinstance(draft.get("source_facts"), Mapping) else {}
    sections = draft.get("sections") if isinstance(draft.get("sections"), Mapping) else {}
    event = source_facts.get("event") if isinstance(source_facts.get("event"), Mapping) else {}
    event = _business_event(event)
    event, field_report = _field_report_projection(event)
    field_verification = _nested_mapping(event, "field_verification", "fieldVerification")
    if not field_verification:
        feedback_records = _records(source_facts.get("feedback"))
        field_verification = feedback_records[-1] if feedback_records else {}
    risk_review = source_facts.get("risk_review")
    risk_review = risk_review if isinstance(risk_review, Mapping) else {}
    basic_info = sections.get("basic_info") if isinstance(sections.get("basic_info"), Mapping) else {}

    narrative = _first_report_value(field_report, ("narrative", "text", "summary"))
    if not _present(narrative):
        narrative = _first_report_value(event, ("narrative", "text", "description", "summary"))
    spatial_location = _nested_mapping(field_report, "spatial_location", "spatialLocation")
    location = _first_report_value(spatial_location, ("location", "address"))
    if not _present(location):
        location = _first_report_value(event, ("location", "address", "admin_area", "adminArea"))
    if not _present(location):
        location = basic_info.get("location")
    disaster_type = _nested_mapping(field_report, "disaster_type", "disasterType")
    event_type = _first_report_value(event, ("event_type", "eventType", "disaster_type", "disasterType", "hazard_type"))
    if not _present(event_type):
        event_type = _first_report_value(disaster_type, ("type", "name", "label"))
    if not _present(event_type) and _present(disaster_type.get("type_code")):
        event_type = f"未确认（原始类型编码 {disaster_type['type_code']}；名称待核实）"
    if not _present(event_type):
        event_type = basic_info.get("event_type")
    occurred_at = _first_report_value(event, ("occurred_at", "occurredAt", "occurrenceTime", "event_time", "eventTime"))
    if not _present(occurred_at):
        occurred_at = basic_info.get("occurred_at")
    observed_signs = _first_report_value(field_report, ("observed_signs", "observedSigns", "signs"))
    measurement_status = _first_report_value(field_report, ("measurement_status", "measurementStatus"))
    movement_confirmed = _first_report_value(field_report, ("movement_confirmed", "movementConfirmed"))
    exposure_status = _first_report_value(field_report, ("exposure_status", "exposureStatus"))
    spatial_status = _first_report_value(event, ("spatial_ref_status", "spatialRefStatus", "coordinate_status"))
    gps = _first_report_value(event, ("gps", "coordinates", "disasterCoordinates"))
    if not _present(gps):
        gps = _first_report_value(spatial_location, ("reported_coordinates", "gps"))
    verification_text = _first_report_value(field_verification, ("text", "narrative", "summary"))

    lines = [
        "## 一、事件与资料概况",
        f"- 事件类型：{_business_value(event_type)}",
        f"- 发生/发现时间：{_business_value(occurred_at)}",
        f"- 地点：{_business_value(location)}",
        f"- 现场记录：{_business_value(narrative)}",
        "",
        "## 二、调查情况",
        f"- 现场征象：{_business_value(observed_signs)}",
        f"- 量测状态：{_business_value(measurement_status)}",
        f"- 持续位移：{_movement_label(movement_confirmed)}",
        f"- 受威胁人员与道路暴露：{_exposure_label(exposure_status)}",
        f"- 点位/坐标状态：{_business_value(spatial_status)}；GPS/坐标：{_business_value(gps)}",
    ]
    photo_recognition = _nested_mapping(field_report, "photo_recognition", "photoRecognition")
    photo_refs = _first_report_value(photo_recognition, ("photo_refs", "photoRefs"))
    if not _present(photo_refs):
        photo_refs = _first_report_value(field_report, ("photo_refs", "photoRefs"))
    verified_findings = _first_report_value(photo_recognition, ("verified_findings", "verifiedFindings"))
    lines.extend([
        f"- 照片识别状态：{_business_value(_first_report_value(photo_recognition, ('status', 'verification_status', 'verificationStatus')))}；已核验发现：{_business_value(verified_findings)}",
        f"- 照片引用：{_business_value(photo_refs)}",
    ])
    p6_mapping = _nested_mapping(spatial_location, "p6_mapping", "p6Mapping")
    if not p6_mapping:
        p6_mapping = _nested_mapping(event, "p6_mapping", "p6Mapping")
    if p6_mapping:
        lines.append(
            "- P6 坡单元关联："
            f"ID={_business_value(_first_report_value(p6_mapping, ('p6_slope_unit_id', 'p6SlopeUnitId')))}；"
            f"状态={_business_value(_first_report_value(p6_mapping, ('mapping_status', 'mappingStatus')))}；"
            f"空间依据={_business_value(_first_report_value(p6_mapping, ('coordinate_basis', 'source')))}；"
            f"专家审批证据={_business_value(_first_report_value(p6_mapping, ('expert_approval_evidenced', 'expertApprovalEvidenced')))}；"
            f"允许正式预警={_business_value(_first_report_value(p6_mapping, ('official_warning_allowed', 'officialWarningAllowed')))}"
        )
    threatened_objects = _nested_mapping(field_report, "threatened_objects", "threatenedObjects")
    threat_status = _first_report_value(threatened_objects, ("verification_status", "verificationStatus"))
    if threatened_objects:
        lines.append(
            "- 受威胁对象记录："
            f"状态={_business_value(threat_status)}；户数={_business_value(threatened_objects.get('households'))}；"
            f"人数={_business_value(threatened_objects.get('people'))}；道路={_business_value(threatened_objects.get('roads'))}"
        )
    conclusions = _nested_mapping(field_report, "investigation_conclusions", "investigationConclusions")
    if conclusions:
        lines.append(f"- 调查结论：{_business_value(_first_report_value(conclusions, ('summary', 'conclusion')))}")
    items_to_verify = _first_report_value(field_report, ("items_to_verify", "itemsToVerify"))
    if isinstance(items_to_verify, Sequence) and not isinstance(items_to_verify, (str, bytes, bytearray)):
        lines.append("- 调查待核实清单：")
        lines.extend(f"  - {_business_value(item)}" for item in items_to_verify)
    for label, aliases in (
        ("地质环境", ("geological_setting", "geology", "geological_background")),
        ("变形特征", ("deformation_features", "deformation", "crack_measurements")),
        ("影响情况", ("impacts", "impact_description", "casualtiesDesc", "damage")),
        ("成因分析", ("cause_analysis", "causeRemark", "cause_type", "causeType")),
    ):
        value = _first_report_value(event, aliases)
        if _present(value):
            lines.append(f"- {label}：{_business_value(value)}")
    if _present(verification_text):
        lines.append(f"- 后续现场复核记录：{_business_value(verification_text)}")

    lines.extend(["", "## 三、事件与处置时间线", "| 时间 | 事项 | 记录状态/内容 |", "| --- | --- | --- |"])
    timeline = _timeline_entries(source_facts)
    if timeline:
        lines.extend(f"| {_table_cell(time)} | {_table_cell(title)} | {_table_cell(detail)} |" for time, title, detail, _ in timeline)
    else:
        lines.append("| 未记录 | 事件及处置时间线 | 待补充持久化时间记录 |")

    issues = _review_issues(event, field_report, field_verification, risk_review)
    lines.extend(["", "## 四、复核发现与待核实事项"])
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("- 当前持久化记录未提供复核发现；不得据此推断现场不存在问题。")

    actions = _disposal_actions(source_facts, event, field_report, field_verification, risk_review)
    lines.extend([
        "",
        "## 五、处置意见与整改措施",
        "以下列出持久化任务/建议及由原始现场记录明确提出的待办。未记录的责任人和期限保留为待明确；建议项不代表已派单或已审批。",
        "",
        "| 优先级 | 措施/任务 | 责任人/单位 | 完成期限 | 完成标准 | 当前状态 | 来源 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ])
    if actions:
        for action in actions:
            lines.append("| " + " | ".join(_table_cell(action.get(key, "未记录")) for key in (
                "priority", "action", "owner", "deadline", "criteria", "status", "source",
            )) + " |")
    else:
        lines.append("| 未记录 | 未提供可核验的处置措施 | 未记录 | 未记录 | 待补充 | 未形成记录 | 持久化来源未提供 |")
    lines.extend(_render_a4_disposal_plan(risk_review))

    conclusion = _business_conclusion(draft, event, field_report, field_verification)
    lines.extend([
        "",
        "## 六、结论与后续跟踪",
        f"- 结论：{conclusion}",
        "- 跟踪要求：核实未确认事项并补齐责任人、期限与完成标准；复核结果须由有权审核人确认后再更新业务状态。",
    ])
    return lines


def _render_a4_disposal_plan(risk_review: Mapping[str, Any]) -> list[str]:
    plan = _find_a4_disposal_plan(risk_review)
    if plan is None:
        return []
    measures = plan.get("measures")
    if not isinstance(measures, Mapping):
        return []

    lines = [
        "",
        "### A4 八类处置建议（建议项，不等同任务）",
        "以下内容来自持久化的 A4 处置建议记录；不表示已派发或已执行。空列表按空类保留，真实任务与反馈仍以持久化任务、反馈记录为准。",
        "",
        "| 措施类别 | 建议动作 | 人工审核状态 | 派发状态 | 依据证据 | 类别/计划状态 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for category in _DISPOSAL_MEASURE_CATEGORIES:
        if category not in measures:
            lines.append(_a4_measure_row(
                category, "未记录（类别字段缺失）", "unknown", "unknown", "unknown", "unknown（类别字段缺失）",
            ))
            continue
        items = measures[category]
        if not isinstance(items, list):
            lines.append(_a4_measure_row(
                category, "unknown（类别内容格式无效）", "unknown", "unknown", "unknown", "unknown（类别内容格式无效）",
            ))
            continue
        if not items:
            lines.append(_a4_measure_row(
                category,
                "无该类建议（措施列表为空）",
                _a4_human_review_status({}, plan),
                _a4_dispatch_status({}, plan),
                "无（空类）",
                "empty（措施列表明确为空）",
            ))
            continue
        for item in items:
            record = dict(item) if isinstance(item, Mapping) else {"action": item} if isinstance(item, str) else {}
            action = _first_report_value(record, ("action", "measure", "suggestion", "recommendation"))
            lines.append(_a4_measure_row(
                category,
                _business_value(action),
                _a4_human_review_status(record, plan),
                _a4_dispatch_status(record, plan),
                _a4_basis_evidence(record, plan),
                _a4_measure_status(record, plan),
            ))
    return lines


def _find_a4_disposal_plan(risk_review: Mapping[str, Any]) -> Mapping[str, Any] | None:
    owners = [risk_review]
    for key in ("decision_record", "decisionRecord", "DecisionRecord", "a4_review", "a4Review"):
        nested = risk_review.get(key)
        if isinstance(nested, Mapping):
            owners.append(nested)
    for owner in owners:
        for key in ("disposal_plan", "disposalPlan", "DisposalPlan"):
            candidate = owner.get(key)
            if isinstance(candidate, Mapping):
                nested = next((candidate[name] for name in ("disposal_plan", "disposalPlan", "DisposalPlan")
                               if isinstance(candidate.get(name), Mapping)), candidate)
                if isinstance(nested.get("measures"), Mapping):
                    return nested
        if isinstance(owner.get("measures"), Mapping):
            return owner
    return None


def _a4_measure_row(category: str, action: str, review: str, dispatch: str, evidence: str, status: str) -> str:
    return "| " + " | ".join(_table_cell(value) for value in (category, action, review, dispatch, evidence, status)) + " |"


def _a4_human_review_status(item: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    required = _a4_item_or_plan_value(item, plan, ("human_review_required", "humanReviewRequired"))
    review = _a4_item_or_plan_value(item, plan, ("review_status", "reviewStatus", "approval_status", "approvalStatus"))
    if required is True:
        label = "需人工审核"
    elif required is False:
        label = "无需人工审核（记录值）"
    elif _present(required):
        label = _business_value(required)
    else:
        label = UNKNOWN
    if _present(review):
        label += f"；审核状态：{_business_value(review)}"
    return label


def _a4_dispatch_status(item: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    status = _a4_item_or_plan_value(item, plan, ("dispatch_status", "dispatchStatus"))
    if not _present(status):
        return UNKNOWN
    if str(status).strip().casefold() in {"not_dispatched", "未派发"}:
        return "not_dispatched（未派发）"
    return _business_value(status)


def _a4_measure_status(item: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    status = _a4_item_or_plan_value(item, plan, ("status", "measure_status", "measureStatus"))
    return _business_value(status)


def _a4_item_or_plan_value(item: Mapping[str, Any], plan: Mapping[str, Any], aliases: Sequence[str]) -> Any:
    value = _first_report_value(item, aliases)
    return value if _present(value) else _first_report_value(plan, aliases)


def _a4_basis_evidence(item: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    aliases = ("basis_evidence_ids", "basisEvidenceIds", "evidence_ids", "evidenceIds", "evidence_id")
    for record in (item, plan):
        for key in aliases:
            if key not in record or record[key] is None:
                continue
            value = record[key]
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                return _report_ids(value) if value else "无（记录为空）"
            if isinstance(value, str) and value.strip():
                return value.strip()
            if _present(value):
                return UNKNOWN
    return UNKNOWN


def _business_event(event: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("payload", "scene_record", "sceneRecord", "report_info", "reportInfo"):
        nested = event.get(key)
        if isinstance(nested, Mapping):
            result.update(nested)
    result.update(event)
    return result


def _field_report_projection(event: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Project the persisted A2 field card into the report's display vocabulary."""
    projected_event = dict(event)
    field_report = dict(_nested_mapping(event, "field_report", "fieldReport"))
    investigation = _nested_mapping(event, "field_investigation_record", "fieldInvestigationRecord")
    basic = _nested_mapping(investigation, "basic_field_info", "basicFieldInfo")
    spatial = _nested_mapping(investigation, "spatial_location", "spatialLocation")
    disaster = _nested_mapping(investigation, "disaster_type", "disasterType")
    photo = _nested_mapping(investigation, "photo_recognition", "photoRecognition")
    deformation = _nested_mapping(investigation, "deformation_signs", "deformationSigns")
    threatened = _nested_mapping(investigation, "threatened_objects", "threatenedObjects")
    conclusions = _nested_mapping(investigation, "investigation_conclusions", "investigationConclusions")
    items_to_verify = _first_report_value(investigation, ("items_to_verify", "itemsToVerify"))

    for target, source, aliases in (
        ("narrative", basic, ("narrative", "text", "summary")),
        ("visit_time", basic, ("visit_time", "visitTime")),
        ("observed_signs", deformation, ("observations", "signs")),
        ("measurement_status", deformation, ("measurement_status", "measurementStatus")),
        ("movement_confirmed", deformation, ("movement_confirmed", "movementConfirmed")),
        ("exposure_status", threatened, ("verification_status", "verificationStatus")),
    ):
        if not _present(field_report.get(target)):
            value = _first_report_value(source, aliases)
            if _present(value):
                field_report[target] = value
    field_report.setdefault("spatial_location", spatial)
    field_report.setdefault("disaster_type", disaster)
    field_report.setdefault("photo_recognition", photo)
    field_report.setdefault("threatened_objects", threatened)
    field_report.setdefault("investigation_conclusions", conclusions)
    if _present(items_to_verify):
        field_report["items_to_verify"] = items_to_verify
        field_report.setdefault("review_required", True)

    if not _present(projected_event.get("spatial_ref_status")):
        value = _first_report_value(spatial, ("coordinate_status", "gps_status", "spatial_ref_status"))
        if _present(value):
            projected_event["spatial_ref_status"] = value
    if not _present(projected_event.get("gps")):
        value = _first_report_value(spatial, ("gps", "reported_coordinates"))
        if _present(value):
            projected_event["gps"] = value
    return projected_event, field_report


def _nested_mapping(record: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    return next((record[key] for key in keys if isinstance(record.get(key), Mapping)), {})


def _business_value(value: Any) -> str:
    return _report_value(value) if _present(value) else "未记录（待补充或核实）"


def _movement_label(value: Any) -> str:
    if value is True:
        return "已确认（原始记录）"
    if value is False:
        return "未确认（原始记录）"
    return _business_value(value)


def _exposure_label(value: Any) -> str:
    if isinstance(value, str) and value.strip().casefold() in {"unknown", "missing", "未明", "未知", "缺失"}:
        return "未知（原始记录未提供，待核查）"
    return _business_value(value)


def _timeline_entries(source_facts: Mapping[str, Any]) -> list[tuple[str, str, str, int | float | None]]:
    entries: list[tuple[str, str, str, int | float | None]] = []

    def add(record: Mapping[str, Any], title: str, summary_aliases: Sequence[str], default_detail: str) -> None:
        timestamp = _first_report_value(record, (
            "occurred_at", "occurredAt", "visit_time", "visitTime", "created_at", "createdAt",
            "updated_at", "updatedAt", "recorded_at", "recordedAt", "feedback_at", "feedbackAt",
            "approved_at", "approvedAt", "submitted_at", "submittedAt",
        ))
        detail = _first_report_value(record, summary_aliases)
        if not _present(detail):
            detail = _first_report_value(record, ("status", "review_status", "reviewStatus", "task_status", "taskStatus"))
        if not _present(timestamp) and not _present(detail) and title != "现场事件记录":
            return
        time_text = str(timestamp) if _present(timestamp) else "未记录"
        detail_text = _business_value(detail) if _present(detail) else default_detail
        entries.append((time_text, title, detail_text, _timestamp_order(timestamp)))

    event = source_facts.get("event")
    if isinstance(event, Mapping):
        event = _business_event(event)
        add(event, "现场事件记录", ("narrative", "text", "description", "summary"), "已读取事件记录")
        visit_time = _first_report_value(event, ("visit_time", "visitTime"))
        occurred_at = _first_report_value(event, ("occurred_at", "occurredAt", "occurrenceTime", "event_time", "eventTime"))
        if _present(visit_time) and str(visit_time) != str(occurred_at):
            entries.append((str(visit_time), "现场巡查时间", _business_value(_first_report_value(event, ("text", "narrative"))), _timestamp_order(visit_time)))
        for nested_key, label in (("field_verification", "现场反馈记录"), ("fieldVerification", "现场反馈记录")):
            nested = event.get(nested_key)
            if isinstance(nested, Mapping):
                add(nested, label, ("text", "narrative", "summary"), "已读取现场复核记录")
                break

    record_groups = (
        ("tasks", "持久化处置任务", ("action", "task_name", "taskName", "description", "title")),
        ("task_proposals", "任务提案", ("action", "task_name", "taskName", "description", "title")),
        ("feedback", "现场反馈", ("text", "textRecord", "feedback_text", "feedbackText", "content")),
        ("risk_review", "风险/复核记录", ("conclusion", "review_conclusion", "reviewConclusion", "decision_status", "decisionStatus")),
        ("attachments", "附件/证据记录", ("file_name", "fileName", "caption", "description")),
        ("approvals", "审批记录", ("approval_result", "approvalResult", "status", "result")),
    )
    for key, label, aliases in record_groups:
        for record in _records(source_facts.get(key)):
            add(record, label, aliases, "已读取持久化记录")
    return sorted(entries, key=lambda item: (item[3] is None, item[3] if item[3] is not None else 0))


def _timestamp_order(value: Any) -> float | None:
    if not _present(value):
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _review_issues(
    event: Mapping[str, Any], field_report: Mapping[str, Any],
    field_verification: Mapping[str, Any], risk_review: Mapping[str, Any],
) -> list[str]:
    issues: list[str] = []
    for key in ("review_issues", "issues", "findings", "problems", "gaps"):
        for item in _records(risk_review.get(key)):
            value = _first_report_value(item, ("issue", "finding", "title", "description", "detail", "text"))
            if _present(value):
                issues.append(_business_value(value))
        value = risk_review.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            issues.extend(_business_value(item) for item in value if not isinstance(item, Mapping) and _present(item))
        elif isinstance(value, str) and value.strip():
            issues.append(value.strip())

    spatial_status = _first_report_value(event, ("spatial_ref_status", "spatialRefStatus", "coordinate_status"))
    if _present(spatial_status) and any(term in str(spatial_status).casefold() for term in ("unverified", "unknown", "未核", "未验")):
        issues.append(f"现场点位/坐标尚未核准：{_business_value(spatial_status)}。")
    measurement_status = _first_report_value(field_report, ("measurement_status", "measurementStatus"))
    if isinstance(measurement_status, str) and measurement_status.strip().casefold() in {"not_measured", "未量测", "未测量"}:
        issues.append("裂缝尺寸、延伸方向及其与既有隐患边界关系尚未量测。")
    if _first_report_value(field_report, ("movement_confirmed", "movementConfirmed")) is False:
        issues.append("持续位移尚未确认。")
    exposure_status = _first_report_value(field_report, ("exposure_status", "exposureStatus"))
    if isinstance(exposure_status, str) and exposure_status.strip().casefold() in {"unknown", "未明", "未知"}:
        issues.append("受威胁人员与道路情况尚待核查。")
    if _first_report_value(field_report, ("review_required", "reviewRequired")) is True or _first_report_value(field_verification, ("review_required", "reviewRequired")) is True:
        issues.append("现场记录要求专业人员/审核人复核，当前记录未提供已完成审核结论。")
    return list(dict.fromkeys(issues))


def _disposal_actions(
    source_facts: Mapping[str, Any], event: Mapping[str, Any], field_report: Mapping[str, Any],
    field_verification: Mapping[str, Any], risk_review: Mapping[str, Any],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(record: Mapping[str, Any], source: str, fallback_action: str | None = None) -> None:
        nested_action = record.get("action")
        action_record = dict(nested_action) if isinstance(nested_action, Mapping) else {}
        action_record.update(record)
        if isinstance(nested_action, Mapping):
            action_record["action"] = _first_report_value(nested_action, ("action", "action_type", "title", "description", "content"))
        action = _first_report_value(action_record, ("action", "action_type", "task_name", "taskName", "title", "recommendation", "description", "content"))
        if not _present(action):
            action = fallback_action
        if not _present(action):
            return
        rows.append({
            "priority": _cell_value(_first_report_value(action_record, ("priority", "priority_level", "priorityLevel", "urgency", "level"))),
            "action": _cell_value(action),
            "owner": _cell_value(_first_report_value(action_record, ("responsible_department", "responsible_unit", "responsible_person", "assignee", "owner", "department", "person"))),
            "deadline": _cell_value(_first_report_value(action_record, ("due_at", "dueAt", "due_time", "dueTime", "deadline", "due_date", "dueDate"))),
            "criteria": _cell_value(_first_report_value(action_record, ("completion_criteria", "completionCriteria", "submitRequire", "acceptance_criteria", "acceptanceCriteria", "completion_standard"))),
            "status": _cell_value(_first_report_value(action_record, ("status", "task_status", "taskStatus", "dispatch_status", "approval_status"))),
            "source": source,
        })

    for record in _action_records(risk_review.get("action_items")):
        add(record, "持久化风险复核建议")
    for record in _records(source_facts.get("tasks")):
        add(record, "持久化任务")
    for record in _records(source_facts.get("task_proposals")):
        add(record, "持久化任务提案（审批状态以记录为准）")

    # The GOLD-01 field narrative explicitly records these unresolved items. They
    # remain recommendations, not dispatched tasks, until a task record exists.
    text = " ".join(str(value) for value in (
        _first_report_value(field_report, ("narrative", "text")),
        _first_report_value(field_verification, ("text", "narrative")),
        _first_report_value(event, ("text", "narrative")),
    ) if _present(value))
    if not rows or text:
        suggestions: list[tuple[str, str]] = []
        spatial_status = _first_report_value(event, ("spatial_ref_status", "spatialRefStatus", "coordinate_status"))
        if ("未核准" in text or "未核准" in str(spatial_status) or "unverified" in str(spatial_status).casefold()) and not any("点位" in row["action"] for row in rows):
            suggestions.append(("核对现场点位与坐标", "现场点位核准；GPS/坐标状态按核验结果记录"))
        measurement_status = _first_report_value(field_report, ("measurement_status", "measurementStatus"))
        if (str(measurement_status).casefold() in {"not_measured", "未量测", "未测量"} or "复测裂缝" in text) and not any("裂缝" in row["action"] for row in rows):
            suggestions.append(("复测疑似裂缝并确认位移情况", "记录裂缝长度、宽度、延伸方向及与既有隐患边界关系；记录持续位移是否确认"))
        exposure_status = _first_report_value(field_report, ("exposure_status", "exposureStatus"))
        if (str(exposure_status).casefold() in {"unknown", "未明", "未知"} or "受威胁人员" in text or "道路情况待核查" in text) and not any("人员" in row["action"] or "道路" in row["action"] for row in rows):
            suggestions.append(("核查受威胁人员与道路情况", "形成受威胁人员及道路影响情况的核查记录"))
        review_required = _first_report_value(field_report, ("review_required", "reviewRequired")) is True or _first_report_value(field_verification, ("review_required", "reviewRequired")) is True
        if (review_required or "专业人员审核" in text or "审核人复核" in text) and not any("审核" in row["action"] or "复核" in row["action"] for row in rows):
            suggestions.append(("由专业人员/审核人复核现场调查结果", "形成审核意见，并注明未确认事项及依据"))
        for action, criteria in suggestions:
            rows.append({
                "priority": "未记录",
                "action": action,
                "owner": "未记录（待明确）",
                "deadline": "未记录（待明确）",
                "criteria": criteria,
                "status": "现场记录提出，尚未形成正式任务",
                "source": "持久化现场记录中的明确待核事项",
            })
    return rows


def _cell_value(value: Any) -> str:
    return _report_value(value) if _present(value) else "未记录"


def _action_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, str):
        return [{"action": value}] if value.strip() else []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(item) if isinstance(item, Mapping) else {"action": item} for item in value
                if isinstance(item, Mapping) or (isinstance(item, str) and item.strip())]
    return []


def _table_cell(value: Any) -> str:
    text = _cell_value(value)
    if any(token in text.casefold() for token in ("gold", "demo", "mock", "fixture", "simulated")):
        return "随软件交付的秭归市事件资料"
    for internal_stage, display_stage in (
        ("GOLD-01", "现场巡查阶段"),
        ("GOLD-02", "监测告警阶段"),
        ("GOLD-03", "恢复观察阶段"),
    ):
        text = text.replace(internal_stage, display_stage)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _business_conclusion(
    draft: Mapping[str, Any], event: Mapping[str, Any], field_report: Mapping[str, Any],
    field_verification: Mapping[str, Any],
) -> str:
    simulated = draft.get("is_simulated") is True or event.get("is_simulated") is True
    pending_review = (
        _first_report_value(field_report, ("review_required", "reviewRequired")) is True
        or _first_report_value(field_verification, ("review_required", "reviewRequired")) is True
    )
    if simulated:
        base = "该记录基于随软件交付的秭归市事件资料，尚未经当前事件现场核查和实时设备数据确认，不作为正式灾害等级、预警或销号结论。"
    else:
        base = "本报告仅整理当前提供的持久化事实；缺失或未核实字段不作推断。"
    if pending_review:
        base += " 当前记录要求人工/专业审核，且未提供已完成审核结论。"
    verification_text = str(_first_report_value(field_verification, ("text", "narrative", "summary")) or "")
    if "不得据此自动结案" in verification_text or "不得自动结案" in verification_text:
        base += " 现场复核记录明确要求不得据此自动结案或隐患销号。"
    p6_mapping = _nested_mapping(event, "p6_mapping", "p6Mapping")
    warning_allowed = _first_report_value(p6_mapping, ("official_warning_allowed", "officialWarningAllowed"))
    if warning_allowed is False:
        base += " P6 映射记录明确标记不允许发布正式预警。"
    return base


_FOUR_NATURES = (
    ("易发性（S）", ("rf_static_susceptibility", "S")),
    ("危险性（H）", ("dynamic_hazard", "H")),
    ("易损性（V）", ("vulnerability", "V")),
    ("风险性（R）", ("risk", "R")),
)
_DISPOSAL_MEASURE_CATEGORIES = (
    "人员安置", "警示防护", "监测巡查", "排危除险",
    "工程治理", "宣传告知", "交通管制", "其他建议",
)
_COMPONENT_FIELDS = (
    ("状态", ("status",)),
    ("值", ("value", "result")),
    ("来源", ("source",)),
    ("模型", ("model",)),
    ("版本", ("version", "model_version", "modelVersion")),
    ("P6 组件状态", ("p6_component_status",)),
    ("评估状态", ("evaluation_status",)),
    ("专家审批有证据", ("expert_approval_evidenced",)),
    ("正式预警允许", ("official_warning_allowed",)),
    ("证据 ID", ("evidence_ids", "evidence_id")),
)
_ACTION_DETAILS = (
    ("地点", ("location",)),
    ("责任单位", ("responsible_department", "responsible_unit", "department")),
    ("人员", ("person", "assignee", "responsible_person")),
    ("时限", ("due_at", "dueAt", "deadline")),
    ("完成标准", ("completion_criteria", "submitRequire")),
    ("派发状态", ("dispatch_status",)),
    ("分配状态", ("assignment_status",)),
    ("时限状态", ("due_status",)),
    ("任务请求状态", ("task_request_status",)),
    ("需要人工审批", ("human_approval_required",)),
    ("依据证据 ID", ("basis_evidence_ids", "evidence_ids")),
)
_ACTION_FIELDS = (("动作", ("action", "action_type")), *_ACTION_DETAILS)
_TASK_FIELDS = (
    ("任务 ID", ("task_id", "taskId", "id")),
    ("任务状态", ("status", "task_status", "taskStatus")),
    ("事件 ID", ("event_id", "eventId")),
    ("追踪 ID", ("trace_id", "traceId")),
    ("场景 ID", ("scenario_id", "scenarioId")),
    ("任务来源", ("task_source", "taskSource", "source_type", "sourceType")),
    ("数据来源", ("data_source", "dataSource")),
    ("执行引擎", ("execution_engine", "executionEngine")),
    ("正式 Java 任务已创建", ("formal_java_task_created", "formalJavaTaskCreated")),
    ("动作", ("action", "action_type")),
    ("责任单位", ("responsible_department", "responsible_unit", "department")),
    ("时限", ("due_at", "dueAt", "deadline")),
)
_TASK_PROPOSAL_FIELDS = (
    ("提案 ID", ("proposal_id", "proposalId", "record_id", "recordId", "id")),
    ("事件 ID", ("event_id", "eventId")),
    ("提案状态", ("status", "proposal_status", "proposalStatus")),
    ("追踪 ID", ("trace_id", "traceId")),
    ("动作", ("action", "action_type")),
    ("任务来源", ("task_source", "taskSource", "source_type", "sourceType")),
    ("数据来源", ("data_source", "dataSource")),
    ("执行引擎", ("execution_engine", "executionEngine")),
    ("正式 Java 任务已创建", ("formal_java_task_created", "formalJavaTaskCreated")),
)
_FEEDBACK_FIELDS = (
    ("反馈 ID", ("feedback_id", "feedbackId", "history_id", "historyId", "id")),
    ("任务 ID", ("task_id", "taskId", "source_task_id", "sourceTaskId")),
    ("事件 ID", ("event_id", "eventId")),
    ("追踪 ID", ("trace_id", "traceId")),
    ("状态", ("status", "source_type", "sourceType")),
    ("反馈内容", ("textRecord", "text_record", "feedback_text", "feedbackText", "text", "content")),
    ("数据来源", ("data_source", "dataSource")),
    ("来源字段", ("source_field", "sourceField")),
    ("证据 ID", ("evidence_ids", "evidence_id", "attachment_id", "photos", "photo")),
)
_EVIDENCE_FIELDS = (
    ("证据 ID", ("evidence_id", "evidenceId", "attachment_id", "attachmentId", "file_id", "fileId", "file_ref")),
    ("来源类型", ("source_type", "sourceType", "source_kind", "sourceKind")),
    ("数据来源", ("data_source", "dataSource")),
    ("来源字段", ("source_field", "sourceField")),
    ("来源记录 ID", ("source_record_id", "sourceRecordId")),
    ("文件名", ("file_name", "fileName")),
)


def _render_four_natures(value: Any) -> list[str]:
    components = value if isinstance(value, Mapping) else {}
    lines = ["", "## 四性及模型状态"]
    for label, aliases in _FOUR_NATURES:
        component = next((components[key] for key in aliases if isinstance(components.get(key), Mapping)), {})
        lines.extend(["", f"### {label}"])
        lines.extend(_render_fields(component, _COMPONENT_FIELDS, required=("状态", "值", "模型", "版本")))
    return lines


def _render_p6_candidate_report_section(candidate: Mapping[str, Any]) -> list[str]:
    scenarios = candidate.get("scenarios") if isinstance(candidate.get("scenarios"), Mapping) else {}
    lines = ["", "## P6 动态降雨候选筛查"]
    lines.extend(_render_fields(candidate, (
        ("快照 ID", ("snapshot_id",)),
        ("时点", ("as_of_local",)),
        ("来源", ("source",)),
        ("模型", ("model",)),
        ("规则版本", ("rule_version",)),
        ("降雨来源类型", ("rain_source_types",)),
        ("降雨状态", ("rain_status",)),
        ("降雨网格映射状态", ("rain_mapping_status",)),
        ("降雨网格距离（km）", ("rain_mapping_distance_km",)),
        ("允许用途", ("permitted_use",)),
    ), required=("快照 ID", "允许用途")))
    for name, scenario in scenarios.items():
        if not isinstance(scenario, Mapping):
            continue
        lines.extend(["", f"### 情景：{name}"])
        lines.extend(_render_fields(scenario, (
            ("降雨来源类型", ("rain_source_type",)),
            ("H（危险性）", ("H",)),
            ("R（相对风险筛查）", ("R",)),
        )))
    lines.extend((
        "",
        "- 边界：模型降雨场不是雨量站实测；候选筛查不等同专家审批、正式预警或现场灾害结论。",
    ))
    return lines


def _render_p6_static_snapshot(snapshot: Mapping[str, Any]) -> list[str]:
    unit = snapshot.get("unit_snapshot") if isinstance(snapshot.get("unit_snapshot"), Mapping) else {}
    info = snapshot.get("info_snapshot") if isinstance(snapshot.get("info_snapshot"), Mapping) else {}
    lines = ["", "## P6 静态快照"]
    lines.extend(_render_fields(snapshot, (
        ("状态", ("status",)),
        ("执行引擎", ("execution_engine",)),
        ("信息状态", ("info_status",)),
        ("来源", ("source",)),
    ), required=("状态",)))
    lines.extend(["", "### 坡单元快照"])
    lines.extend(_render_fields(unit, (
        ("坡单元 ID", ("slope_unit_id", "slopeUnitId")),
        ("S 候选值", ("S", "s_score", "sScore")),
        ("S 状态", ("s_status", "sStatus")),
        ("S 模型版本", ("s_model_version", "sModelVersion")),
        ("S 来源", ("s_source", "sSource", "source")),
    ), required=("S 候选值",)))
    lines.extend(["", "### 快照用途与审核边界"])
    lines.extend(_render_fields(info, (
        ("评估状态", ("evaluation_status", "evaluationStatus")),
        ("来源模式", ("source_mode", "sourceMode")),
        ("允许用途", ("permitted_use", "permittedUse")),
        ("专家审批有证据", ("expert_approval_evidenced", "expertApprovalEvidenced")),
        ("正式预警允许", ("official_warning_allowed", "officialWarningAllowed")),
    ), required=("评估状态", "专家审批有证据", "正式预警允许")))
    return lines


def _render_evidence_status(value: Any) -> list[str]:
    lines = ["", "## 证据读取状态"]
    if isinstance(value, Mapping):
        lines.extend(_render_fields(value, (
            ("状态", ("status", "evidence_status", "read_status")),
            ("执行引擎", ("execution_engine", "executionEngine")),
            ("证据数量", ("evidence_count", "evidenceCount", "count")),
            ("证据 ID", ("evidence_ids", "evidenceIds", "evidence_id")),
            ("数据来源", ("data_source", "dataSource", "source")),
        ), required=("状态",)))
    else:
        lines.append(f"- 状态：{_report_value(value)}")
    return lines


def _render_selected_fields(
    title: str,
    record: Any,
    fields: Sequence[tuple[str, tuple[str, ...]]],
    *,
    required: Sequence[str] = (),
) -> list[str]:
    lines = ["", f"## {title}"]
    lines.extend(_render_fields(record if isinstance(record, Mapping) else {}, fields, required=required))
    return lines


def _render_selected_records(
    title: str,
    records: Any,
    item_label: str,
    fields: Sequence[tuple[str, tuple[str, ...]]],
    *,
    required: Sequence[str] = (),
) -> list[str]:
    if isinstance(records, Mapping):
        items = [records]
    elif isinstance(records, Sequence) and not isinstance(records, (str, bytes, bytearray)):
        items = [item for item in records if isinstance(item, Mapping)]
    else:
        items = []
    lines = ["", f"## {title}"]
    if not items:
        lines.append(f"- {UNKNOWN}")
        return lines
    for index, record in enumerate(items, start=1):
        lines.extend(["", f"### {item_label} {index}"])
        lines.extend(_render_fields(record, fields, required=required))
    return lines


def _render_fields(
    record: Mapping[str, Any],
    fields: Sequence[tuple[str, tuple[str, ...]]],
    *,
    required: Sequence[str] = (),
) -> list[str]:
    lines = []
    for label, aliases in fields:
        value = _first_report_value(record, aliases)
        if not _present(value) and label not in required:
            continue
        if label == "动作" and isinstance(value, Mapping):
            lines.append("- 动作：")
            lines.extend(_render_fields(value, _ACTION_DETAILS))
        else:
            lines.append(f"- {label}：{_report_ids(value) if label.endswith('ID') else _report_value(value)}")
    return lines or [f"- {UNKNOWN}"]


def _first_report_value(record: Mapping[str, Any], aliases: Sequence[str]) -> Any:
    return next((record[key] for key in aliases if key in record and _present(record[key])), None)


def _report_value(value: Any) -> str:
    if not _present(value):
        return UNKNOWN
    if isinstance(value, Mapping) or (
        isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
    ):
        text = json.dumps(_bounded_report_value(value), ensure_ascii=False, sort_keys=True, default=str)
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    if any(token in text.casefold() for token in ("gold", "demo", "mock", "fixture", "simulated")):
        text = "随软件交付的秭归市事件资料"
    return text if len(text) <= _REPORT_VALUE_LIMIT else text[:_REPORT_VALUE_LIMIT - 1] + "…"


def _bounded_report_value(value: Any, depth: int = 0) -> Any:
    if isinstance(value, Mapping):
        if depth >= 2:
            return "nested structure omitted"
        result = {}
        for index, (key, item) in enumerate(value.items()):
            if index == 8:
                break
            result[str(key)] = _bounded_report_value(item, depth + 1)
        if len(value) > len(result):
            result["…"] = f"{len(value) - len(result)} more fields omitted"
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result = [_bounded_report_value(item, depth + 1) for item in value[:8]]
        if len(value) > 8:
            result.append(f"{len(value) - 8} more items omitted")
        return result
    if isinstance(value, str) and len(value) > _REPORT_VALUE_LIMIT:
        return value[:_REPORT_VALUE_LIMIT - 1] + "…"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)[:_REPORT_VALUE_LIMIT]


def _report_ids(values: Any) -> str:
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
        items = [value for value in values if _present(value)]
        return "、".join(_report_value(value) for value in items) or UNKNOWN
    return _report_value(values)


def _source_identifiers(source_facts: Mapping[str, Any], *keys: str) -> list[Any]:
    wanted = {key.casefold() for key in keys}
    values: list[Any] = []
    for source in source_facts.values():
        if isinstance(source, Mapping):
            records = [source]
        elif isinstance(source, Sequence) and not isinstance(source, (str, bytes, bytearray)):
            records = [record for record in source if isinstance(record, Mapping)]
        else:
            records = []
        for record in records:
            for key, item in record.items():
                if str(key).casefold() in wanted and _present(item):
                    values.append(item)
    return _unique(values)


def _execution_trace_ids(value: Any) -> list[Any]:
    identifiers: list[Any] = []
    for record in _records(value):
        trace_id = _first(record, "trace_id", "traceId")
        if _present(trace_id):
            identifiers.append(trace_id)
        workflows = record.get("workflows")
        if isinstance(workflows, Mapping):
            workflow_records = [item for item in workflows.values() if isinstance(item, Mapping)]
        else:
            workflow_records = _records(record.get("trace"))
        identifiers.extend(
            _first(item, "trace_id", "traceId")
            for item in workflow_records
            if _present(_first(item, "trace_id", "traceId"))
        )
    return _unique(identifiers)


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _first(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if _present(value):
            return value
    return None


def _first_event(record: Mapping[str, Any], *keys: str) -> Any:
    value = _first(record, *keys)
    if _present(value):
        return value
    for nested_key in ("scene_record", "sceneRecord", "report_info", "reportInfo"):
        nested = record.get(nested_key)
        if isinstance(nested, Mapping):
            value = _first(nested, *keys)
            if _present(value):
                return value
    return None


def _first_event_detail(record: Mapping[str, Any], *keys: str) -> Any:
    for nested_key in ("scene_record", "sceneRecord", "report_info", "reportInfo"):
        nested = record.get(nested_key)
        if isinstance(nested, Mapping):
            value = _first(nested, *keys)
            if _present(value):
                return value
    return _first(record, *keys)


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return bool(value)
    return True


def _known_or_missing(value: Any, path: str, missing_fields: list[str]) -> Any:
    if _present(value):
        return value
    missing_fields.append(path)
    return UNKNOWN


def _identifiers(records: Sequence[Mapping[str, Any]], *keys: str) -> list[Any]:
    return _unique([identifier for record in records if _present(identifier := _first(record, *keys))])


def _draft_records(
    records: Sequence[Mapping[str, Any]],
    canonical_id: str,
    id_keys: tuple[str, ...],
    path: str,
    missing_fields: list[str],
) -> list[dict[str, Any]]:
    result = []
    for index, record in enumerate(records):
        draft_record = dict(record)
        identifier = _first(record, *id_keys)
        if _present(identifier):
            if not _present(draft_record.get(canonical_id)):
                draft_record[canonical_id] = identifier
        else:
            draft_record[canonical_id] = UNKNOWN
            missing_fields.append(f"{path}[{index}].{canonical_id}")
        result.append(draft_record)
    return result


def _all_identifiers(
    event: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    feedback: Sequence[Mapping[str, Any]],
    risk_review: Mapping[str, Any],
    attachments: Sequence[Mapping[str, Any]],
    *,
    keys: tuple[str, ...],
) -> list[Any]:
    records = [event, *tasks, *feedback, risk_review, *attachments]
    return _identifiers(records, *keys)


def _unique(values: Sequence[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _lineage(
    event: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    task_proposals: Sequence[Mapping[str, Any]],
    feedback: Sequence[Mapping[str, Any]],
    risk_review: Mapping[str, Any],
    attachments: Sequence[Mapping[str, Any]],
    execution_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    sources = [
        ("event", [event], ("event_id", "eventId", "handleId", "id")),
        ("task", tasks, ("task_id", "taskId", "id")),
        ("task_proposal", task_proposals, ("proposal_id", "proposalId", "record_id", "recordId", "id")),
        ("feedback", feedback, ("feedback_id", "feedbackId", "history_id", "historyId", "id")),
        ("risk_review", [risk_review], ("review_id", "reviewId", "assessment_id", "assessmentId", "id")),
        ("attachment", attachments, ("attachment_id", "attachmentId", "file_id", "fileId", "id")),
        ("a4_execution_trace", execution_records, ("trace_id", "traceId", "agent_id", "agentId", "id")),
    ]
    lineage: list[dict[str, Any]] = []
    for source_type, records, id_keys in sources:
        for record in records:
            evidence_ids = _record_evidence_ids(record)
            is_simulated = _is_simulated(record)
            lineage.append(
                {
                    "source_type": source_type,
                    "source_id": _first(record, *id_keys) if _present(_first(record, *id_keys)) else UNKNOWN,
                    "evidence_ids": evidence_ids,
                    "is_simulated": is_simulated,
                    "simulation_marked": _simulation_marked(record),
                    "data_source": _first(record, "data_source", "dataSource") or UNKNOWN,
                    "model_status": _first(record, "model_status", "modelStatus") or UNKNOWN,
                    "model_version": _first(record, "model_version", "modelVersion") or UNKNOWN,
                }
            )
    return lineage


def _record_evidence_ids(record: Mapping[str, Any]) -> list[Any]:
    values: list[Any] = []
    evidence_ids = _first(record, "evidence_ids", "evidenceIds")
    if isinstance(evidence_ids, Sequence) and not isinstance(evidence_ids, (str, bytes, bytearray)):
        values.extend(item for item in evidence_ids if _present(item))
    elif _present(evidence_ids):
        values.append(evidence_ids)
    for keys in (
        ("evidence_id", "evidenceId"),
        ("attachment_id", "attachmentId"),
        ("file_id", "fileId"),
    ):
        value = _first(record, *keys)
        if _present(value):
            values.append(value)
    return _unique(values)


def _is_simulated(record: Mapping[str, Any]) -> bool:
    explicit = _first(record, "is_simulated", "isSimulated")
    if explicit is True or (isinstance(explicit, str) and explicit.strip().casefold() in {"true", "1", "yes"}):
        return True
    status = _first(record, "simulation_status", "simulationStatus")
    source_kind = _first(record, "source_kind", "sourceKind", "source_type", "sourceType")
    return any(
        isinstance(value, str) and value.strip().casefold() in {"simulated", "simulation"}
        for value in (status, source_kind)
    )


def _simulation_marked(record: Mapping[str, Any]) -> bool:
    if any(key in record for key in ("is_simulated", "isSimulated", "simulation_status", "simulationStatus")):
        return True
    source_kind = _first(record, "source_kind", "sourceKind", "source_type", "sourceType")
    return isinstance(source_kind, str) and source_kind.strip().casefold() in {"simulated", "simulation"}


def _evidence_ids(lineage: Sequence[Mapping[str, Any]]) -> list[Any]:
    return _unique([item for source in lineage for item in source["evidence_ids"]])
