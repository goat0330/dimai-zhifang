"""Adapt persisted Yichang reports to the legacy Dify investigation workflow."""

from __future__ import annotations

import asyncio
import json
import math
import re
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from ..java_client import lookup_business_record
from ..yichang_report import (
    UNKNOWN,
    build_report_draft,
    render_local_report_markdown,
    render_report_status_markdown,
)
from ..yichang_archive import archive_yichang_report, is_simulated_report
from ..yichang_store import list_gold_records
from ..yichang_monitor import compact_monitoring_evidence


AGENT_ID = "A5"
REPORT_BIZ_TYPE = 1
REPORT_CONTENT_TYPE = 1


def build_legacy_workflow_inputs(
    scene_record: Mapping[str, Any],
    *,
    persisted_facts: Mapping[str, Any],
    existing_report: str = "",
) -> dict[str, str]:
    """Map Java's persisted scene record to the old workflow Start variables."""
    geo_guard_evidence = {
        "event": persisted_facts.get("event", {}),
        "tasks": persisted_facts.get("tasks", []),
        "approvals": persisted_facts.get("approvals", []),
        "task_proposals": persisted_facts.get("task_proposals", []),
        "feedback": persisted_facts.get("feedback", []),
        "attachments": persisted_facts.get("attachments", []),
        "risk_review": persisted_facts.get("risk_review") or {},
        "execution_trace": persisted_facts.get("execution_trace", {}),
        "evidence_status": persisted_facts.get("evidence_status", UNKNOWN),
        "is_simulated": persisted_facts.get("is_simulated", UNKNOWN),
        "simulation_status": persisted_facts.get("simulation_status", UNKNOWN),
        "data_source": persisted_facts.get("data_source", UNKNOWN),
        "facts_status": persisted_facts.get("facts_status", UNKNOWN),
        "missing_fields": persisted_facts.get("missing_fields", []),
        "missing_legacy_fields": persisted_facts.get("missing_legacy_fields", []),
        "source_status": persisted_facts.get("source_status", {}),
        "p6_static_snapshot": persisted_facts.get("p6_static_snapshot", UNKNOWN),
        "p6_dynamic_snapshot": persisted_facts.get("p6_dynamic_snapshot", UNKNOWN),
        "p6_candidates": persisted_facts.get("p6_candidates", UNKNOWN),
        "model_status": persisted_facts.get("model_status", UNKNOWN),
    }
    event_facts = geo_guard_evidence.get("event")
    if isinstance(event_facts, Mapping):
        event_facts = dict(event_facts)
        event_monitoring = event_facts.get("monitoring")
        if isinstance(event_monitoring, Mapping):
            event_facts["monitoring"] = compact_monitoring_evidence(event_monitoring)
        event_risk_info = event_facts.get("risk_info")
        if isinstance(event_risk_info, Mapping):
            event_risk_info = dict(event_risk_info)
            risk_monitoring = event_risk_info.get("monitoring")
            if isinstance(risk_monitoring, Mapping):
                event_risk_info["monitoring"] = compact_monitoring_evidence(risk_monitoring)
            event_facts["risk_info"] = event_risk_info
        geo_guard_evidence["event"] = event_facts
    risk_review = geo_guard_evidence.get("risk_review")
    if isinstance(risk_review, Mapping):
        risk_review = dict(risk_review)
        review_monitoring = risk_review.get("monitoring")
        if isinstance(review_monitoring, Mapping):
            risk_review["monitoring"] = compact_monitoring_evidence(review_monitoring)
        geo_guard_evidence["risk_review"] = risk_review
    report_info = dict(scene_record)
    # The exported DSL carries report_info into merged_facts_json; a root-level
    # geo_guard_evidence field is ignored by its base-facts node.
    report_info["geo_guard_evidence"] = geo_guard_evidence
    context = {
        "report_info": report_info,
    }
    return {
        "incident_context": json.dumps(context, ensure_ascii=False, default=str),
        "report": existing_report,
    }


def _fact_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    payload = value.get("payload")
    if not isinstance(payload, Mapping):
        return dict(value)
    result = dict(payload)
    for key in (
        "record_id", "parent_id", "record_type", "scenario_id", "source_task_id", "sourceTaskId",
        "status", "created_at", "updated_at",
        "trace_id", "traceId", "is_simulated", "isSimulated",
        "simulation_status", "simulationStatus",
        "source_kind", "sourceKind", "source_type", "sourceType",
        "data_source", "dataSource",
    ):
        envelope_value = value.get(key)
        if envelope_value not in (None, "") and result.get(key) in (None, ""):
            result[key] = envelope_value
    return result


def _fact_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [_fact_record(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [record for item in value if (record := _fact_record(item))]
    return []


def _legacy_scene_record(event: Mapping[str, Any]) -> dict[str, Any]:
    source = dict(event)
    for key in ("scene_record", "sceneRecord", "report_info", "reportInfo"):
        nested = event.get(key)
        if isinstance(nested, Mapping):
            source.update(nested)
            break

    aliases = {
        "disasterName": ("disasterName", "disaster_name", "event_name", "name"),
        "location": ("location", "address", "detailedAddress", "checkCenterLocation", "admin_area"),
        "disasterCoordinates": ("disasterCoordinates", "coordinates", "checkInCoordinates", "gps"),
        "occurrenceTime": ("occurrenceTime", "occurred_at", "event_time", "eventTime"),
        "disasterType": ("disasterType", "disaster_type", "event_type", "hazard_type"),
        "casualtiesDesc": ("casualtiesDesc", "casualties_desc"),
        "deadPeople": ("deadPeople", "dead_people"),
        "directLoss": ("directLoss", "direct_loss"),
        "scaleLength": ("scaleLength", "scale_length"),
        "scaleWidth": ("scaleWidth", "scale_width"),
        "scaleVolume": ("scaleVolume", "scale_volume"),
        "disasterNature": ("disasterNature", "disaster_nature"),
        "structureDesc": ("structureDesc", "structure_desc"),
        "causeType": ("causeType", "cause_type"),
        "causeRemark": ("causeRemark", "cause_remark"),
        "threatHouseholds": ("threatHouseholds", "threat_households"),
        "threatPeople": ("threatPeople", "threat_people"),
        "threatAsset": ("threatAsset", "threat_asset"),
        "measuresEvacuation": ("measuresEvacuation", "measures_evacuation"),
        "measuresEvacuationRemark": ("measuresEvacuationRemark", "measures_evacuation_remark"),
        "measuresProtection": ("measuresProtection", "measures_protection"),
        "measuresProtectionRemark": ("measuresProtectionRemark", "measures_protection_remark"),
        "measuresMonitoring": ("measuresMonitoring", "measures_monitoring"),
        "measuresMonitoringRemark": ("measuresMonitoringRemark", "measures_monitoring_remark"),
        "measuresHazardRemoval": ("measuresHazardRemoval", "measures_hazard_removal"),
        "measuresHazardRemovalRemark": ("measuresHazardRemovalRemark", "measures_hazard_removal_remark"),
        "investigationUnit": ("investigationUnit", "investigation_unit"),
        "investigator": ("investigator",),
        "investigationDate": ("investigationDate", "investigation_date"),
    }
    scene_record = {}
    for target, keys in aliases.items():
        for key in keys:
            value = source.get(key)
            if value is not None and (not isinstance(value, str) or value.strip()):
                scene_record[target] = value
                break
    characteristics = source.get("specialCharacteristics", source.get("special_characteristics"))
    if isinstance(characteristics, Mapping):
        scene_record["specialCharacteristics"] = dict(characteristics)
    return scene_record


def _missing_legacy_workflow_fields(scene_record: Mapping[str, Any]) -> list[str]:
    required = (
        "deadPeople", "directLoss", "scaleLength", "scaleWidth", "scaleVolume",
        "threatHouseholds", "threatPeople", "threatAsset",
    )
    missing = []
    for key in required:
        value = scene_record.get(key)
        try:
            numeric_value = float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            missing.append(key)
            continue
        if not math.isfinite(numeric_value):
            missing.append(key)
    return missing


async def _java_get(path: str, *, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not settings.java_backend_base_url or not settings.java_backend_bearer_token:
        return {"status": "not_configured", "data": None}
    base = settings.java_backend_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.java_backend_bearer_token}"}
    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            response = await client.get(f"{base}{path}", params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"status": "error", "data": None, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    if not isinstance(payload, dict) or payload.get("code") != 200:
        message = payload.get("msg") if isinstance(payload, dict) else None
        return {"status": "rejected", "data": None, "error": message or "Java API returned an invalid response"}
    data = payload.get("data")
    return {"status": "found" if data not in (None, [], {}) else "not_found", "data": data}


def _rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [dict(item) for item in data if isinstance(item, Mapping)]
    if isinstance(data, Mapping):
        for key in ("rows", "records", "list"):
            rows = data.get(key)
            if isinstance(rows, list):
                return [dict(item) for item in rows if isinstance(item, Mapping)]
        return [dict(data)]
    return []


def _record_id(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _gold_store_records_for_event(event: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not is_simulated_report({"source_facts": {"event": event}}):
        return []
    scenario_id = _record_id(event, "scenario_id", "scenarioId")
    event_id = _record_id(event, "event_id", "eventId", "record_id", "id")
    trace_id = _record_id(event, "trace_id", "traceId")
    if not scenario_id or not event_id:
        return []

    database_path = Path(settings.yichang_gold_db_path)
    if not database_path.is_absolute():
        database_path = Path(__file__).resolve().parents[2] / database_path
    if not database_path.is_file():
        return []

    records = _fact_records(list_gold_records(str(scenario_id)))
    matching_ids: set[str] = set()
    for record in records:
        record_id = _record_id(record, "record_id", "recordId", "id")
        record_trace_id = _record_id(record, "trace_id", "traceId")
        record_event_id = _record_id(record, "event_id", "eventId", "last_event_id", "lastEventId")
        linked_to_event = (
            str(record_event_id) == str(event_id)
            or str(record.get("parent_id")) == str(event_id)
        )
        same_trace = trace_id not in (None, "") and str(record_trace_id) == str(trace_id)
        is_event = (
            record.get("record_type") == "event"
            and str(record_id) == str(event_id)
        )
        if not (is_event or linked_to_event or same_trace) or record_id in (None, ""):
            continue
        matching_ids.add(str(record_id))

    task_ids = set()
    for record in records:
        identifier = _record_id(record, "record_id", "recordId", "task_id", "taskId", "id")
        if record.get("record_type") == "task" and identifier not in (None, ""):
            if str(identifier) in matching_ids:
                task_ids.add(str(identifier))
    for record in records:
        approval_id = _record_id(record, "record_id", "recordId", "id")
        if (
            record.get("record_type") == "approval"
            and str(record.get("parent_id")) in task_ids
            and approval_id not in (None, "")
        ):
            matching_ids.add(str(approval_id))

    return [
        {**(dict(record["payload"]) if isinstance(record.get("payload"), Mapping) else {}), **record}
        for record in records
        if str(_record_id(record, "record_id", "recordId", "id")) in matching_ids
    ]


def _is_persisted_simulated_gold_event(
    event: Mapping[str, Any], records: Sequence[Mapping[str, Any]],
) -> bool:
    scenario_id = _record_id(event, "scenario_id", "scenarioId")
    event_id = _record_id(event, "event_id", "eventId", "record_id", "id")
    trace_id = _record_id(event, "trace_id", "traceId")
    data_source = _record_id(event, "data_source", "dataSource")
    if scenario_id not in {"GOLD-01", "GOLD-02", "GOLD-03"}:
        return False
    if not is_simulated_report({"source_facts": {"event": event}}):
        return False
    if not isinstance(data_source, str) or not data_source.casefold().startswith(
        f"local_gold_fixture:{scenario_id}".casefold()
    ):
        return False
    if event_id in (None, "") or trace_id in (None, ""):
        return False

    event_persisted = any(
        record.get("record_type") == "event"
        and str(record.get("record_id")) == str(event_id)
        and str(_record_id(record, "trace_id", "traceId")) == str(trace_id)
        and record.get("is_simulated") is True
        for record in records
    )
    decision_persisted = any(
        record.get("record_type") == "decision"
        and str(_record_id(record, "event_id", "eventId")) == str(event_id)
        and str(_record_id(record, "trace_id", "traceId")) == str(trace_id)
        and record.get("is_simulated") is True
        for record in records
    )
    approved_plan_proposals = set()
    for approval in records:
        if (
            approval.get("record_type") == "approval"
            and approval.get("approval_type") == "disposal_plan"
            and approval.get("approved") is True
            and approval.get("is_simulated") is True
            and str(_record_id(approval, "event_id", "eventId")) == str(event_id)
            and approval.get("approval_mode") == "simulated_gold_test_harness"
        ):
            approved_plan_proposals.update(
                str(value) for value in approval.get("approved_proposal_ids", []) if value not in (None, "")
            )

    approved_task_ids = set()
    for task in records:
        if task.get("record_type") != "task" or task.get("is_simulated") is not True:
            continue
        task_id = _record_id(task, "task_id", "taskId", "record_id", "recordId", "id")
        task_event_id = _record_id(task, "event_id", "eventId", "last_event_id", "lastEventId")
        task_trace_id = _record_id(task, "trace_id", "traceId")
        reviewer_id = _record_id(task, "reviewer_id", "reviewerId")
        status = str(task.get("status", "")).casefold()
        proposal_id = _record_id(task, "proposal_id", "proposalId")
        plan_approval_id = _record_id(task, "approval_id", "approvalId")
        plan_approved = (
            proposal_id not in (None, "")
            and str(proposal_id) in approved_plan_proposals
            and any(
                approval.get("record_type") == "approval"
                and approval.get("approval_type") == "disposal_plan"
                and str(_record_id(approval, "record_id", "approval_id", "approvalId")) == str(plan_approval_id)
                and approval.get("approved") is True
                for approval in records
            )
        )
        direct_task_approval = any(
            approval.get("record_type") == "approval"
            and approval.get("approval_type") == "task"
            and approval.get("approved") is True
            and approval.get("is_simulated") is True
            and str(approval.get("parent_id")) == str(task_id)
            and str(_record_id(approval, "task_id", "taskId")) == str(task_id)
            and str(_record_id(approval, "event_id", "eventId")) == str(event_id)
            and str(_record_id(approval, "reviewer_id", "reviewerId")) == str(reviewer_id)
            and approval.get("approval_mode", approval.get("approvalMode"))
            in {"human_reviewer", "simulated_gold_test_harness"}
            for approval in records
        )
        reviewed = status in {"accepted", "accepted_with_followup"} and any(
            approval.get("record_type") == "approval"
            and approval.get("approval_type") == "task_review"
            and approval.get("approved") is True
            and approval.get("is_simulated") is True
            and str(approval.get("parent_id")) == str(task_id)
            and str(_record_id(approval, "task_id", "taskId")) == str(task_id)
            and str(_record_id(approval, "event_id", "eventId")) == str(event_id)
            for approval in records
        )
        approval_mode = task.get("approval_mode", task.get("approvalMode"))
        if (
            task_id in (None, "")
            or str(task_event_id) != str(event_id)
            or str(task_trace_id) != str(trace_id)
            or not reviewer_id
            or status not in {"demo_assigned", "demo_feedback_received", "accepted", "accepted_with_followup"}
            or approval_mode not in {"human_reviewer", "simulated_gold_test_harness"}
            or not (plan_approved or direct_task_approval)
            or (status in {"accepted", "accepted_with_followup"} and not reviewed)
        ):
            continue
        approved_task_ids.add(str(task_id))

    feedback_persisted = any(
        feedback.get("record_type") == "feedback"
        and feedback.get("is_simulated") is True
        and str(_record_id(feedback, "event_id", "eventId")) == str(event_id)
        and str(_record_id(feedback, "task_id", "taskId", "source_task_id", "sourceTaskId"))
        in approved_task_ids
        and any(feedback.get(key) not in (None, "", [], {}) for key in (
            "text", "textRecord", "feedback_text", "feedbackText", "field_description", "actual_actions",
            "photos", "photo_refs", "image_ids", "attachments",
        ))
        for feedback in records
    )
    return event_persisted and decision_persisted and feedback_persisted


def _merge_record_metadata(
    primary: Mapping[str, Any],
    persisted: Mapping[str, Any],
) -> dict[str, Any]:
    result = dict(primary)
    for key in ("record_id", "parent_id", "record_type", "scenario_id", "status", "created_at", "updated_at"):
        value = persisted.get(key)
        if result.get(key) in (None, "") and value not in (None, ""):
            result[key] = value
    return result


def _merge_fact_records(
    primary: Sequence[Mapping[str, Any]],
    additional: Sequence[Mapping[str, Any]],
    *id_keys: str,
) -> list[dict[str, Any]]:
    result = [dict(item) for item in primary]
    known: dict[str, int] = {}
    for index, item in enumerate(result):
        identifier = _record_id(item, *id_keys)
        if identifier not in (None, ""):
            known.setdefault(str(identifier), index)
    for item in additional:
        identifier = _record_id(item, *id_keys)
        if identifier not in (None, "") and str(identifier) in known:
            index = known[str(identifier)]
            result[index] = _merge_record_metadata(result[index], item)
            continue
        result.append(dict(item))
        if identifier not in (None, ""):
            known[str(identifier)] = len(result) - 1
    return result


def _attachment_values(value: Any) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [str(item).strip() for item in value if item not in (None, "") and str(item).strip()]
    if not isinstance(value, str) or not value.strip():
        return []
    text = value.strip()
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, list):
        return [str(item).strip() for item in decoded if item not in (None, "") and str(item).strip()]
    return [item.strip() for item in text.split(",") if item.strip()]


def _persisted_attachments(
    scene_record: Mapping[str, Any],
    feedback: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for field in ("photoPanorama", "photoDamage", "photoDeformation"):
        for value in _attachment_values(scene_record.get(field)):
            attachments.append({
                "attachment_id": value,
                "source_type": "scene_record",
                "source_field": field,
                "source_record_id": _record_id(scene_record, "id", "handleId"),
            })
    for item in feedback:
        feedback_id = _record_id(item, "feedback_id", "feedbackId", "history_id", "historyId", "id")
        task_id = _record_id(item, "task_id", "taskId", "source_task_id", "sourceTaskId")
        for field in ("photos", "scenePhoto", "photo"):
            for value in _attachment_values(item.get(field)):
                attachments.append({
                    "attachment_id": value,
                    "source_type": "task_feedback",
                    "source_field": field,
                    "source_record_id": feedback_id if feedback_id is not None else UNKNOWN,
                    "task_id": task_id if task_id is not None else UNKNOWN,
                })
    return attachments


async def load_persisted_report_facts(handle_id: int | str) -> dict[str, Any]:
    """Read report inputs and review state from Java's persisted business records."""
    identifier = str(handle_id)
    if not identifier.isdigit() or int(identifier) <= 0:
        raise ValueError("A positive persisted Java handle_id is required")

    event_result, scene_result, task_result, review_result = await asyncio.gather(
        _java_get(f"/dizai/taskHandle/{identifier}"),
        _java_get(f"/dizai/taskHandleSceneRecord/getByHandleId/{identifier}"),
        _java_get("/dizai/taskDistList/listAll", params={"handleId": identifier}),
        _java_get(
            "/dizai/taskHandleDetail/latest",
            params={"bizType": REPORT_BIZ_TYPE, "bizId": identifier, "contentType": REPORT_CONTENT_TYPE},
        ),
    )

    event = event_result.get("data") if isinstance(event_result.get("data"), Mapping) else {}
    scene_record = scene_result.get("data") if isinstance(scene_result.get("data"), Mapping) else {}
    task_rows = _rows(task_result.get("data"))
    tasks: list[dict[str, Any]] = []
    feedback: list[dict[str, Any]] = []
    task_reads: list[dict[str, Any]] = []
    for row in task_rows:
        task_id = _record_id(row, "id", "taskId", "task_id")
        if task_id is None:
            tasks.append(row)
            task_reads.append({
                "task_id": UNKNOWN,
                "record_status": "missing_id",
                "feedback_status": "unavailable",
            })
            continue
        try:
            detail = await lookup_business_record("task", task_id)
        except (httpx.HTTPError, ValueError) as exc:
            detail = {
                "status": "error",
                "feedback_status": "unavailable",
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            }
        record = detail.get("record") if isinstance(detail.get("record"), Mapping) else row
        tasks.append(dict(record))
        feedback_status = detail.get("feedback_status")
        histories = detail.get("feedbacks")
        if isinstance(histories, list):
            for history in histories:
                if isinstance(history, Mapping):
                    item = dict(history)
                    item.setdefault("source_task_id", task_id)
                    feedback.append(item)
        task_reads.append({
            "task_id": task_id,
            "record_status": detail.get("status", "unavailable"),
            "feedback_status": feedback_status or "unavailable",
        })

    risk_review = review_result.get("data") if isinstance(review_result.get("data"), Mapping) else None
    attachments = _persisted_attachments(scene_record, feedback)
    event_with_scene = dict(event)
    event_with_scene["scene_record"] = dict(scene_record)
    statuses = {
        "event": event_result.get("status"),
        "scene_record": scene_result.get("status"),
        "tasks": task_result.get("status"),
        "risk_review": review_result.get("status"),
        "task_reads": task_reads,
    }
    required_ok = (
        statuses["event"] == "found"
        and statuses["scene_record"] == "found"
        and statuses["tasks"] in {"found", "not_found"}
        and statuses["risk_review"] in {"found", "not_found"}
        and all(item["record_status"] == "found" and item["feedback_status"] == "read" for item in task_reads)
    )
    facts_status = "ready" if required_ok else "partial" if statuses["event"] == "found" else "unavailable"
    return {
        "event": event_with_scene,
        "scene_record": dict(scene_record),
        "tasks": tasks,
        "feedback": feedback,
        "risk_review": dict(risk_review) if risk_review else None,
        "attachments": attachments,
        "source_status": statuses,
        "facts_status": facts_status,
    }


def _existing_report(facts: Mapping[str, Any]) -> str:
    review = facts.get("risk_review")
    if not isinstance(review, Mapping):
        return ""
    value = review.get("planContent") or review.get("plan_content")
    if not isinstance(value, str) or not value.strip() or value.strip() == "待补充应急调查报告":
        return ""
    return value


def _report_text(execution: Mapping[str, Any]) -> str | None:
    return next(iter(_report_text_candidates(execution)), None)


def _report_text_candidates(execution: Mapping[str, Any]) -> list[str]:
    values = []
    for value in (execution.get("outputs"), execution.get("response")):
        text = _extract_report_text(value)
        if text and text not in values:
            values.append(text)
    return values


def _extract_report_text(value: Any, depth: int = 0) -> str | None:
    if depth > 5:
        return None
    if isinstance(value, Mapping):
        for key in ("report_text", "answer", "text", "content", "outputs", "data", "result", "response"):
            if key in value:
                text = _extract_report_text(value[key], depth + 1)
                if text:
                    return text
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.startswith("```"):
        match = re.fullmatch(r"```(?:markdown|md|json)?\s*\n?(.*?)\n?```", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            text = match.group(1).strip()
    if text.startswith(("{", "[")):
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            decoded = None
        if decoded is not None:
            extracted = _extract_report_text(decoded, depth + 1)
            return extracted or text
    return text or None


_LEGACY_REPORT_TEMPLATE_MARKERS = (
    "{disaster_image}",
    "{damage_photo}",
    "{deformation_photo}",
    "待补充应急调查报告",
)


def _usable_report_text(execution: Mapping[str, Any]) -> str | None:
    for value in _report_text_candidates(execution):
        if any(marker in value for marker in _LEGACY_REPORT_TEMPLATE_MARKERS):
            continue
        headings = re.findall(r"(?m)^\s{0,3}#{2,3}\s+\S.+$", value)
        if len(headings) >= 6:
            return value
    return None


def _canonicalize_dify_status(text: str, report: Mapping[str, Any]) -> str:
    lines = []
    skipping_status = False
    for line in text.splitlines():
        if re.match(r"^\s{0,3}#{1,6}\s*(?:报告状态|审核状态|归档状态)\s*$", line):
            skipping_status = True
            continue
        if skipping_status:
            if re.match(r"^\s{0,3}#{1,6}\s+", line):
                skipping_status = False
            else:
                continue
        lines.append(line)
    title = str(report.get("title") or "宜昌地质灾害事件调查与处置复盘报告")
    title_index = next((index for index, line in enumerate(lines) if line.startswith("# ")), None)
    if title_index is None:
        lines = [f"# {title}", "", *lines]
        title_index = 0
    status_block = render_report_status_markdown(report)
    lines[title_index + 1:title_index + 1] = ["", *status_block, ""]
    return "\n".join(lines).strip() + "\n"


_P6_SCENARIO_FIELDS = {
    "dynamic": ("h_dynamic_grade", "h_dynamic_score", "r_dynamic_grade", "r_dynamic_score"),
    "forecast": ("h_forecast_grade", "h_forecast_score", "r_forecast_grade", "r_forecast_score"),
    "dynamic_08": ("h_dynamic_08_grade", "h_dynamic_08_score", "r_dynamic_08_grade", "r_dynamic_08_score"),
}
_P6_SCENARIO_LABELS = {
    "dynamic": "Dynamic H/R 候选",
    "forecast": "Forecast H/R 候选",
    "dynamic_08": "Dynamic_08 H/R 候选",
}


def _p6_candidate_sources(
    event: Mapping[str, Any], risk_review: Mapping[str, Any] | None,
) -> list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]:
    sources = []
    for record in (risk_review, event):
        if not isinstance(record, Mapping):
            continue
        owners = [record]
        risk_info = record.get("risk_info")
        if isinstance(risk_info, Mapping):
            owners.append(risk_info)
        for owner in owners:
            for key in ("p6_dynamic_api_response", "p6_dynamic_snapshot", "p6_dynamic_monitoring"):
                candidate = owner.get(key)
                if isinstance(candidate, Mapping) and candidate:
                    sources.append((candidate, owner, record))
    return sources


def _p6_component(value: Any) -> dict[str, str]:
    component = value if isinstance(value, Mapping) else {}
    grade = component.get("grade")
    score = component.get("score")
    status = component.get("status")
    if status in (None, ""):
        status = "candidate" if grade not in (None, "") or score not in (None, "") else "missing"
    return {
        "status": _p6_display(status),
        "grade": _p6_display(grade),
        "score": _p6_display(score),
    }


def _p6_display(value: Any) -> str:
    if value is None or value == "":
        return "missing"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) if value else "missing"
    return str(value)


def _p6_candidate_scenarios(snapshot: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    item = snapshot.get("item")
    if isinstance(item, Mapping) and item:
        scenarios = {}
        for name, (h_grade, h_score, r_grade, r_score) in _P6_SCENARIO_FIELDS.items():
            if not any(key in item for key in (h_grade, h_score, r_grade, r_score)):
                continue
            scenarios[name] = {
                "H": {"grade": item.get(h_grade), "score": item.get(h_score)},
                "R": {"grade": item.get(r_grade), "score": item.get(r_score)},
            }
        return scenarios

    dynamic = snapshot.get("dynamic")
    if isinstance(dynamic, Mapping):
        scenarios = {}
        for name, (h_grade, h_score, r_grade, r_score) in _P6_SCENARIO_FIELDS.items():
            if not any(key in dynamic for key in (h_grade, h_score, r_grade, r_score)):
                continue
            scenarios[name] = {
                "H": {"grade": dynamic.get(h_grade), "score": dynamic.get(h_score)},
                "R": {"grade": dynamic.get(r_grade), "score": dynamic.get(r_score)},
                "rain_source_type": (
                    dynamic.get("rain_forecast_type") if name == "forecast"
                    else dynamic.get("rain_past_type")
                ),
            }
        if scenarios:
            return scenarios

    sibling_scenarios = {
        name: dict(snapshot[name])
        for name in _P6_SCENARIO_FIELDS
        if isinstance(snapshot.get(name), Mapping)
    }
    if sibling_scenarios:
        return sibling_scenarios

    values = snapshot.get("scenarios")
    if not isinstance(values, Mapping):
        values = snapshot.get("scenario_results")
    if isinstance(values, Mapping):
        return {
            name: dict(values[name])
            for name in _P6_SCENARIO_FIELDS
            if isinstance(values.get(name), Mapping)
        }

    if isinstance(snapshot.get("H"), Mapping) or isinstance(snapshot.get("R"), Mapping):
        name = snapshot.get("scenario")
        name = name if name in _P6_SCENARIO_LABELS else "dynamic"
        return {name: {"H": snapshot.get("H"), "R": snapshot.get("R")}}
    if snapshot.get("status") not in (None, "", "missing"):
        name = snapshot.get("scenario")
        name = name if name in _P6_SCENARIO_LABELS else "dynamic"
        return {name: {}}
    return {}


def _p6_candidate_report_section(
    event: Mapping[str, Any], risk_review: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    sources = _p6_candidate_sources(event, risk_review)
    if not sources:
        return None
    selected, scenarios = max(
        ((source, _p6_candidate_scenarios(source[0])) for source in sources),
        key=lambda item: (len(item[1]), isinstance(item[0][0].get("item"), Mapping)),
        default=(None, {}),
    )
    if selected is None:
        return None

    snapshot, owner, record = selected
    metadata = [snapshot]
    for key in ("unit_snapshot", "latest_snapshot", "snapshot", "service_status", "item", "dynamic"):
        nested = snapshot.get(key)
        if isinstance(nested, Mapping):
            metadata.append(nested)
    metadata.extend((owner, record))
    for parent in (owner, record):
        for key in ("p6_dynamic_snapshot", "p6_dynamic_monitoring"):
            sibling = parent.get(key)
            if isinstance(sibling, Mapping) and sibling is not snapshot:
                metadata.append(sibling)

    def first_value(*keys: str) -> Any:
        for source in metadata:
            for key in keys:
                value = source.get(key)
                if value is not None and value != "":
                    return value
        return None

    normalized_scenarios = {}
    for name in _P6_SCENARIO_FIELDS:
        if name not in scenarios:
            continue
        scenario = scenarios[name]
        normalized_scenarios[name] = {
            "rain_source_type": _p6_display(
                scenario.get("rain_source_type") or (
                    first_value("rain_forecast_type", "forecast_type") if name == "forecast"
                    else first_value("rain_past_type", "historical_type")
                )
            ),
            "H": _p6_component(scenario.get("H")),
            "R": _p6_component(scenario.get("R")),
        }

    raw_types = first_value("rain_source_types")
    if raw_types is None:
        raw_types = [
            value for value in (
                first_value("rain_past_type", "historical_type"),
                first_value("rain_forecast_type", "forecast_type"),
            )
            if value not in (None, "")
        ]
    if not raw_types:
        raw_types = [
            scenario["rain_source_type"]
            for scenario in normalized_scenarios.values()
            if scenario["rain_source_type"] != "missing"
        ]
    if not normalized_scenarios:
        return None

    return {
        "snapshot_id": _p6_display(first_value("snapshot_id")),
        "as_of_local": _p6_display(first_value("as_of_local", "as_of")),
        "source": _p6_display(first_value("provider", "source")),
        "model": _p6_display(first_value("model")),
        "rule_version": _p6_display(first_value("rule_version")),
        "rain_source_types": _p6_display(raw_types),
        "rain_status": _p6_display(first_value("rain_status")),
        "rain_mapping_status": _p6_display(first_value("rain_mapping_status")),
        "rain_mapping_distance_km": _p6_display(
            first_value("rain_mapping_distance_km", "rain_distance_km")
        ),
        "permitted_use": _p6_display(first_value("permitted_use", "candidate_use")),
        "scenarios": normalized_scenarios,
    }


def _render_p6_candidate_section(candidate: Mapping[str, Any]) -> str:
    lines = [
        "## P6 Dynamic / Forecast 候选事实",
        f"- snapshot_id：{candidate['snapshot_id']}",
        f"- as_of_local：{candidate['as_of_local']}",
        f"- 数据来源：{candidate['source']}",
        f"- model：{candidate['model']}",
        f"- rule_version：{candidate['rule_version']}",
        f"- rain_source_types：{candidate['rain_source_types']}",
        f"- rain_status：{candidate['rain_status']}",
        f"- rain_mapping_status：{candidate['rain_mapping_status']}",
        f"- rain_mapping_distance_km：{candidate['rain_mapping_distance_km']}",
        f"- 候选用途：{candidate['permitted_use']}",
        "- 说明：模型降雨场字段不是雨量站实测；以上仅为候选筛查信息，不是官方预警。",
    ]
    for name, scenario in candidate["scenarios"].items():
        lines.extend((
            "",
            f"### {_P6_SCENARIO_LABELS[name]}",
            f"- rain_source_type：{scenario['rain_source_type']}",
        ))
        for component in ("H", "R"):
            value = scenario[component]
            lines.append(
                f"- {component}：grade={value['grade']}，score={value['score']}，status={value['status']}"
            )
    return "\n".join(lines)


async def generate_report_draft(
    handle_id: int | str,
    *,
    user: str,
    query: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Read a Java handle and return a persistable A5 report draft."""
    facts = await load_persisted_report_facts(handle_id)
    report = await generate_report_from_facts(
        facts, user=user, query=query, conversation_id=conversation_id,
    )
    report["handle_id"] = handle_id
    return report


async def generate_report_from_facts(
    facts: Mapping[str, Any],
    *,
    user: str,
    query: str | None = None,
    conversation_id: str | None = None,
    allow_simulated_gold_dify: bool = True,
) -> dict[str, Any]:
    """Build a report from already-persisted event/task/evidence facts.

    Gold runners may pass their SQLite readback records here. Java callers should
    use ``generate_report_draft`` so this adapter reads the source records itself.
    Request text and prior Dify conversation state are intentionally not passed to
    A5; the legacy chat prompt can otherwise treat them as report facts.
    """
    from app.dify_client import dify_configured, run_agent

    event_rows = _fact_records(facts.get("event"))
    event = event_rows[0] if event_rows else {}
    gold_records = _gold_store_records_for_event(event)
    event_id = _record_id(event, "event_id", "eventId", "record_id", "id")
    gold_event = next((
        item for item in gold_records
        if item.get("record_type") == "event"
        and str(_record_id(item, "event_id", "eventId", "record_id", "id")) == str(event_id)
    ), None)
    if gold_event is not None:
        event = _merge_record_metadata(event, gold_event)
    gold_tasks = [item for item in gold_records if item.get("record_type") == "task"]
    gold_proposals = [item for item in gold_records if item.get("record_type") == "task_proposal"]
    gold_feedback = [item for item in gold_records if item.get("record_type") == "feedback"]
    gold_attachments = [item for item in gold_records if item.get("record_type") == "attachment"]
    gold_decisions = [item for item in gold_records if item.get("record_type") == "decision"]
    gold_approvals = [
        item for item in gold_records
        if item.get("record_type") == "approval"
        and item.get("approval_type") in {"task", "recovery_review"}
    ]
    tasks = _merge_fact_records(
        _fact_records(facts.get("tasks")), gold_tasks, "task_id", "taskId", "id", "record_id",
    )
    task_proposal_value = facts.get("task_proposals")
    if task_proposal_value in (None, [], {}):
        task_proposal_value = facts.get("task_proposal")
    task_proposals = _merge_fact_records(
        _fact_records(task_proposal_value), gold_proposals,
        "proposal_id", "proposalId", "record_id", "recordId", "id",
    )
    feedback = _merge_fact_records(
        _fact_records(facts.get("feedback")), gold_feedback,
        "feedback_id", "feedbackId", "history_id", "historyId", "id", "record_id",
    )
    approvals = _merge_fact_records(
        _fact_records(facts.get("approvals")), gold_approvals,
        "approval_id", "approvalId", "record_id", "recordId", "id",
    )
    review_rows = [item for item in _fact_records(facts.get("risk_review")) if item]
    if not review_rows:
        review_rows = gold_decisions
    elif gold_decisions:
        current_review = review_rows[-1]
        current_event_id = _record_id(current_review, "event_id", "eventId")
        current_trace_id = _record_id(current_review, "trace_id", "traceId")
        persisted_review = next((
            item for item in reversed(gold_decisions)
            if str(_record_id(item, "event_id", "eventId")) == str(current_event_id)
            and (
                current_trace_id in (None, "")
                or str(_record_id(item, "trace_id", "traceId")) == str(current_trace_id)
            )
        ), None)
        if persisted_review is not None:
            review_rows[-1] = _merge_record_metadata(current_review, persisted_review)
    risk_review = review_rows[-1] if review_rows else None
    attachments = _merge_fact_records(
        _fact_records(facts.get("attachments")), gold_attachments,
        "attachment_id", "attachmentId", "file_id", "fileId", "id", "record_id",
    )
    execution_trace = next((
        facts.get(key) for key in ("execution_trace", "a4_execution_trace", "a4_execution")
        if facts.get(key) not in (None, "", [], {})
    ), None)
    if execution_trace is None and isinstance(risk_review, Mapping):
        execution_trace = next((
            risk_review.get(key) for key in ("a4_execution", "execution_trace", "a4_execution_trace")
            if risk_review.get(key) not in (None, "", [], {})
        ), None)
    source_status = facts.get("source_status")
    evidence_status = facts.get("evidence_status")
    if evidence_status in (None, "", [], {}):
        if isinstance(source_status, Mapping):
            evidence_status = next((
                source_status.get(key) for key in ("evidence", "attachments", "evidence_readback")
                if source_status.get(key) not in (None, "", [], {})
            ), UNKNOWN)
        else:
            evidence_status = UNKNOWN
    if gold_records:
        source_status = dict(source_status) if isinstance(source_status, Mapping) else {}
        source_status.setdefault("gold_store", "sqlite_readback")
        source_status.setdefault("task_proposals", "sqlite_readback" if task_proposals else "not_found")
        source_status.setdefault("approvals", "sqlite_readback" if approvals else "not_found")
        source_status.setdefault("a4_execution", "sqlite_readback" if execution_trace is not None else "not_found")
        source_status.setdefault("risk_review", source_status.get("review", "sqlite_readback"))
        if evidence_status == UNKNOWN:
            evidence_ids = [
                identifier for item in attachments
                if (identifier := _record_id(item, "attachment_id", "attachmentId", "file_id", "fileId", "file_ref"))
                not in (None, "")
            ]
            evidence_status = {
                "status": "sqlite_readback" if attachments else "not_found",
                "execution_engine": "local",
                "evidence_count": len(attachments),
                "evidence_ids": evidence_ids,
                "is_simulated": True,
            }
        source_status.setdefault(
            "evidence",
            evidence_status.get("status", UNKNOWN) if isinstance(evidence_status, Mapping) else evidence_status,
        )
    for item in attachments:
        if "attachment_id" not in item:
            file_ref = _record_id(item, "file_ref", "fileId", "file_id", "oss_id")
            if file_ref is not None:
                item["attachment_id"] = file_ref

    report = build_report_draft(
        event,
        tasks,
        feedback,
        risk_review,
        attachments,
        task_proposals=task_proposals,
        execution_trace=execution_trace,
        evidence_status=evidence_status,
    )
    report["source_facts"]["approvals"] = approvals
    p6_candidates = _p6_candidate_report_section(event, risk_review)
    if p6_candidates is not None:
        report["sections"]["p6_candidates"] = p6_candidates
    report["archive_status"] = "pending_archive"
    report["evidence_library_status"] = "not_submitted"
    report["report_text"] = None
    report["source_status"] = source_status or {"facts": "provided_persisted_facts"}
    task_reads = report["source_status"].get("task_reads") if isinstance(report["source_status"], Mapping) else None
    for index, read in enumerate(task_reads if isinstance(task_reads, list) else []):
        if not isinstance(read, Mapping):
            continue
        task_id = read.get("task_id")
        if read.get("record_status") != "found":
            field = f"task_reads[{index}].record_status"
            if field not in report["missing_fields"]:
                report["missing_fields"].append(field)
        if read.get("feedback_status") != "read":
            field = f"task_reads[{index}].feedback_status"
            if field not in report["missing_fields"]:
                report["missing_fields"].append(field)
        elif task_id not in (None, "") and not any(
            str(_record_id(item, "source_task_id", "sourceTaskId", "task_id", "taskId")) == str(task_id)
            for item in feedback
        ):
            field = f"feedback[{task_id}]"
            if field not in report["missing_fields"]:
                report["missing_fields"].append(field)
    configured = dify_configured(AGENT_ID)
    facts_status = facts.get("facts_status", "ready")
    facts_readable = bool(event) and facts_status in {"ready", "partial"}
    if not facts_readable:
        report["generation"] = {
            "execution_engine": None,
            "status": "facts_unavailable",
            "dify_configured": configured,
        }
        report["generation_error"] = "Persisted event facts are required before A5 generation."
        report["execution_engine"] = None
        report["generation_status"] = "facts_unavailable"
        return report

    scene_record = _legacy_scene_record(event)
    missing_fields = _missing_legacy_workflow_fields(scene_record)
    simulated_facts = report["is_simulated"] or is_simulated_report({"source_facts": facts})
    partial_facts = facts_status == "partial"
    gold_dify_opt_in_requested = allow_simulated_gold_dify is True
    persisted_gold_simulation = _is_persisted_simulated_gold_event(event, gold_records)
    simulated_gold_dify_allowed = gold_dify_opt_in_requested and persisted_gold_simulation
    local_template = not configured or (
        (bool(missing_fields) or simulated_facts or partial_facts) and not simulated_gold_dify_allowed
    )
    if simulated_facts and not simulated_gold_dify_allowed:
        execution = {
            "execution_engine": "local",
            "status": "simulated_facts_local_only",
        }
    elif not configured:
        execution = {
            "execution_engine": "local",
            "status": "not_configured",
            "outputs": {},
            "response": None,
            "error": "Dify base URL or this agent's server-side API key is not configured",
        }
    elif missing_fields and not simulated_gold_dify_allowed:
        execution = {
            "execution_engine": "local",
            "status": "missing_legacy_report_facts",
            "error": "Required numeric report fields are absent or non-numeric in persisted facts.",
        }
    elif partial_facts and not simulated_gold_dify_allowed:
        execution = {
            "execution_engine": "local",
            "status": "partial_persisted_facts_local_only",
            "error": "One or more persisted source reads are incomplete; missing details remain visible for review.",
        }
    else:
        risk_review_mapping = risk_review if isinstance(risk_review, Mapping) else {}
        model_status = risk_review_mapping.get("model_status")
        model_status = model_status if isinstance(model_status, Mapping) else {}
        p6_static_snapshot = risk_review_mapping.get("p6_snapshot") or model_status.get("p6_snapshot")
        if not isinstance(p6_static_snapshot, Mapping):
            p6_static_snapshot = event.get("p6_snapshot") if isinstance(event.get("p6_snapshot"), Mapping) else UNKNOWN
        p6_dynamic_snapshot = risk_review_mapping.get("p6_dynamic_snapshot")
        if not isinstance(p6_dynamic_snapshot, Mapping):
            p6_dynamic_snapshot = event.get("p6_dynamic_snapshot") if isinstance(event.get("p6_dynamic_snapshot"), Mapping) else UNKNOWN
        input_missing_fields = list(dict.fromkeys([*report["missing_fields"], *missing_fields]))
        persisted_facts = {
            "event": event,
            "tasks": tasks,
            "approvals": approvals,
            "feedback": feedback,
            "task_proposals": task_proposals,
            "risk_review": risk_review,
            "attachments": attachments,
            "execution_trace": execution_trace,
            "evidence_status": evidence_status,
            "is_simulated": report["is_simulated"],
            "simulation_status": report["simulation_status"],
            "data_source": report["source_metadata"].get("data_source", UNKNOWN),
            "facts_status": facts_status,
            "missing_fields": input_missing_fields,
            "missing_legacy_fields": missing_fields,
            "source_status": report["source_status"],
            "p6_static_snapshot": p6_static_snapshot,
            "p6_dynamic_snapshot": p6_dynamic_snapshot,
            "p6_candidates": p6_candidates if p6_candidates is not None else UNKNOWN,
            "model_status": model_status if model_status else UNKNOWN,
        }
        existing_report = facts.get("existing_report")
        if not isinstance(existing_report, str):
            if gold_records:
                existing_report = render_local_report_markdown(report) if simulated_gold_dify_allowed else ""
            else:
                existing_report = _existing_report(persisted_facts)
        workflow_inputs = build_legacy_workflow_inputs(
            scene_record,
            persisted_facts=persisted_facts,
            existing_report=existing_report,
        )
        execution = await run_agent(AGENT_ID, inputs=workflow_inputs, user=user)
        if simulated_gold_dify_allowed and execution.get("execution_engine") == "dify":
            execution["input_snapshot"] = workflow_inputs
    status = execution.get("status", "error")
    successful_status = status in {"completed", "succeeded", "success"}
    raw_dify_text = _report_text(execution) if successful_status else None
    dify_text = _usable_report_text(execution) if successful_status else None
    text = dify_text
    if execution.get("execution_engine") != "dify":
        dify_output_status = "not_run"
    elif not successful_status:
        dify_output_status = "execution_failed"
    elif raw_dify_text is None:
        dify_output_status = "empty_output"
    elif dify_text is None:
        dify_output_status = "unsupported_output"
    else:
        dify_output_status = "accepted"
    local_generator = "local_template" if local_template else None
    if local_template or not dify_text:
        if not local_template:
            local_generator = "local_template_fallback"
        execution.setdefault("trace_id", str(uuid.uuid4()))
    generation_status = status
    if not local_template and not dify_text and successful_status:
        generation_status = dify_output_status
    report["generation"] = {
        "execution_engine": execution.get("execution_engine"),
        "status": generation_status,
        "dify_app": execution.get("dify_app"),
        "app_mode": execution.get("app_mode"),
        "dify_execution_status": status if execution.get("execution_engine") == "dify" else None,
        "dify_output_status": dify_output_status,
        **({"generator": local_generator} if local_generator else {}),
        "dify_configured": configured,
        "conversation_id": execution.get("conversation_id"),
        "task_id": execution.get("task_id"),
        "workflow_run_id": execution.get("workflow_run_id"),
        "message_id": execution.get("message_id"),
        "trace_id": execution.get("trace_id"),
        "trace_id": execution.get("trace_id"),
        "raw_outputs": execution.get("outputs"),
        "raw_response": execution.get("response"),
        "input_snapshot": execution.get("input_snapshot"),
        "error": execution.get("error"),
        "missing_legacy_fields": missing_fields,
        "is_simulated": report["is_simulated"],
        **({
            "simulated_gold_dify_opt_in": {
                "eligible": persisted_gold_simulation,
                "used": simulated_gold_dify_allowed and execution.get("execution_engine") == "dify",
            },
        } if gold_dify_opt_in_requested else {}),
    }
    report["execution_engine"] = execution.get("execution_engine")
    report["generation_status"] = generation_status
    if local_template or not dify_text:
        text = render_local_report_markdown(report)
    elif text:
        text = _canonicalize_dify_status(text, report)
    if text and p6_candidates is not None:
        text = f"{text.rstrip()}\n\n{_render_p6_candidate_section(p6_candidates)}\n"
    if text:
        report["report_text"] = text
        report["sections"]["legacy_report_markdown"] = text
    return report


def _review_approved(record: Mapping[str, Any]) -> bool:
    statuses = (record.get("status"), record.get("review_status"), record.get("reviewStatus"))
    return any(
        status == 2 or (isinstance(status, str) and status.strip().casefold() in {"approved", "passed", "通过"})
        for status in statuses
    )


def _archive_allowed(record: Mapping[str, Any]) -> bool:
    content = record.get("planContentJson", record.get("plan_content_json"))
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            content = None
    candidates = [record, content] if isinstance(content, Mapping) else [record]
    return any(
        candidate.get(key) is True
        for candidate in candidates
        for key in ("allow_archive", "allowArchive", "archive_allowed", "archiveAllowed")
    )


def _persisted_report_ids(facts: Mapping[str, Any]) -> list[str]:
    records = facts.get("tasks") if isinstance(facts.get("tasks"), list) else []
    review = facts.get("risk_review")
    values = [
        _record_id(item, "report_id", "reportId")
        for item in [*records, review if isinstance(review, Mapping) else {}]
        if isinstance(item, Mapping)
    ]
    return list(dict.fromkeys(str(value) for value in values if value not in (None, "", UNKNOWN)))


def _archive_not_submitted(reason: str) -> dict[str, Any]:
    return {
        "archive_status": "pending_archive",
        "evidence_library_status": "not_submitted",
        "reason": reason,
    }


async def archive_persisted_report(handle_id: int | str, report: Mapping[str, Any]) -> dict[str, Any]:
    """Index only the exact persisted report whose saved review allows archiving."""
    identifier = str(handle_id)
    if not identifier.isdigit() or int(identifier) <= 0:
        raise ValueError("A positive persisted Java handle_id is required")
    facts = await load_persisted_report_facts(identifier)
    if facts.get("facts_status") != "ready":
        return _archive_not_submitted("persisted_source_facts_unavailable")
    if is_simulated_report(report) or is_simulated_report({"source_facts": {"event": facts.get("event")}}):
        return _archive_not_submitted("simulated_report_requires_local_gold_archive")
    record = facts.get("risk_review")
    if not isinstance(record, Mapping):
        return _archive_not_submitted("persisted_review_not_found")
    if not _review_approved(record):
        return _archive_not_submitted("report_not_approved")
    if not _archive_allowed(record):
        return _archive_not_submitted("archive_not_allowed_by_persisted_review")
    report_text = report.get("report_text")
    if not isinstance(report_text, str) or not report_text.strip() or report_text.strip() == "待补充应急调查报告":
        return _archive_not_submitted("report_text_required")
    if report_text != _existing_report({"risk_review": record}):
        return _archive_not_submitted("report_does_not_match_approved_content")
    persisted_ids = _persisted_report_ids(facts)
    associations = report.get("associations")
    explicit_id = report.get("report_id", report.get("reportId"))
    if explicit_id in ("", UNKNOWN):
        explicit_id = None
    approved_report_id = _record_id(record, "report_id", "reportId")
    if approved_report_id in ("", UNKNOWN):
        approved_report_id = None
    if approved_report_id is not None:
        if explicit_id is not None and str(explicit_id) != str(approved_report_id):
            return _archive_not_submitted("report_id_mismatch")
        report_id = str(approved_report_id)
    elif explicit_id is not None:
        report_id = str(explicit_id) if str(explicit_id) in persisted_ids else None
        if report_id is None:
            return _archive_not_submitted("report_id_not_persisted")
    else:
        requested_ids = associations.get("existing_report_ids", []) if isinstance(associations, Mapping) else []
        matches = list(dict.fromkeys(
            str(value) for value in requested_ids if str(value) in persisted_ids
        )) if isinstance(requested_ids, list) else []
        report_id = matches[0] if len(matches) == 1 else None
        if report_id is None and not matches and len(persisted_ids) == 1:
            report_id = persisted_ids[0]
    if report_id is None:
        return _archive_not_submitted("java_report_id_required")

    event = facts.get("event") if isinstance(facts.get("event"), Mapping) else {}
    actual_event_id = _record_id(event, "event_id", "eventId", "handleId", "id")
    if actual_event_id in (None, "", UNKNOWN):
        return _archive_not_submitted("persisted_event_id_unavailable")
    requested_event_id = associations.get("event_id") if isinstance(associations, Mapping) else None
    if requested_event_id not in (None, "", UNKNOWN) and str(requested_event_id) != str(actual_event_id):
        return _archive_not_submitted("event_association_mismatch")

    archival_report = dict(report)
    archival_report["report_id"] = report_id
    archival_report["associations"] = {
        **(dict(associations) if isinstance(associations, Mapping) else {}),
        "event_id": actual_event_id,
        "task_ids": [value for item in facts["tasks"] if (value := _record_id(item, "task_id", "taskId", "id")) is not None],
    }
    sections = dict(report.get("sections")) if isinstance(report.get("sections"), Mapping) else {}
    sections["legacy_report_markdown"] = report_text
    archival_report["sections"] = sections
    try:
        result = await archive_yichang_report(
            archival_report,
            report_approved=True,
            archive_approved=True,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "archive_status": "pending_archive",
            "evidence_library_status": "unknown",
            "reason": "geo_rag_unavailable",
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
        }
    result_status = result.get("status")
    verification = result.get("a1_verification")
    a1_verified = isinstance(verification, Mapping) and verification.get("status") == "retrieved"
    archive_status = (
        "indexed" if result_status in {"indexed", "added", "submitted"} and a1_verified
        else "pending_a1_verification" if result_status == "indexed"
        else "pending_archive"
    )
    return {
        **result,
        "archive_status": archive_status,
        "evidence_library_status": result_status or "unknown",
    }
