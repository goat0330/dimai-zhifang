"""Run checked-in Gold fixtures through the real adapters and local persistence."""

from __future__ import annotations

import json
import mimetypes
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from .rag_archive import archive_approved_report
from .rag_client import retrieve_yichang
from .dify_adapters.a3_monitor import process_monitoring_with_dify
from .dify_adapters.a5_report import generate_report_from_facts
from .yichang_decision import process_decision
from .yichang_field import process_field_report
from .yichang_qa import answer_yichang_query
from .yichang_store import (
    get_gold_record,
    list_gold_records,
    new_gold_id,
    save_gold_record,
    update_gold_record,
)
from .yichang_report import sync_report_markdown_status


_FIXTURES = {
    "GOLD-01": "GOLD-01-field.json",
    "GOLD-02": "GOLD-02-monitor.json",
    "GOLD-03": "GOLD-03-recovery.json",
}
_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "gold" / "yichang"


def _gold_photo_uploads(scenario: Mapping[str, Any]) -> list[dict[str, Any]]:
    if (scenario.get("scenario_id") != "GOLD-01" or scenario.get("is_simulated") is not True
            or scenario.get("data_source") != "local_gold_fixture:GOLD-01"):
        return []
    references = scenario.get("photo_refs")
    if not isinstance(references, list) or not references:
        return []

    project_root = Path(__file__).resolve().parents[1]
    asset_root = (_FIXTURE_DIR / "assets").resolve()
    uploads = []
    for index, reference in enumerate(references):
        if not isinstance(reference, str) or not reference.strip():
            return []
        path = (project_root / reference).resolve()
        if asset_root not in path.parents:
            return []
        try:
            content = path.read_bytes()
        except OSError:
            return []
        mime_type = mimetypes.guess_type(path.name)[0]
        if not content or not mime_type or not mime_type.startswith("image/"):
            return []
        uploads.append({
            "index": index,
            "reference": reference,
            "filename": path.name,
            "mime_type": mime_type,
            "bytes": content,
        })
    return uploads if len(uploads) == len(references) else []


async def run_gold_scenario(
    scenario_id: str,
    *,
    rag_retriever: Callable[..., Awaitable[dict[str, Any]]] = retrieve_yichang,
    report_archiver: Callable[..., Awaitable[dict[str, Any]]] = archive_approved_report,
    gold_test_approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    filename = _FIXTURES.get(scenario_id)
    if filename is None:
        raise ValueError("Unknown Yichang Gold scenario")
    scenario = json.loads((_FIXTURE_DIR / filename).read_text(encoding="utf-8"))
    approval = gold_test_approval if isinstance(gold_test_approval, Mapping) else {}
    harness_enabled = approval.get("enabled") is True
    approver = str(approval.get("reviewer_id") or "").strip()
    if harness_enabled and not approver:
        raise ValueError("Gold test-harness approvals require a reviewer_id")
    test_task_approved = harness_enabled and approval.get("task_approved") is True
    test_report_approved = harness_enabled and approval.get("report_approved") is True
    test_archive_approved = harness_enabled and approval.get("archive_approved") is True

    trace_id = new_gold_id("trace", scenario_id)
    steps: list[dict[str, Any]] = []
    a2_result = None
    a3_result = None

    if scenario_id == "GOLD-01":
        field_input = dict(scenario)
        photo_uploads = _gold_photo_uploads(scenario)
        if photo_uploads:
            field_input["photo_uploads"] = photo_uploads
        a2_result = await process_field_report(field_input)
        event = dict(a2_result)
        steps.extend(a2_result.get("trace", []))
    else:
        monitor_input = dict(scenario)
        if monitor_input.get("parent_correlation_id"):
            monitor_input["correlation_id"] = monitor_input["parent_correlation_id"]
        a3_result = await process_monitoring_with_dify(monitor_input)
        event = dict(a3_result.get("event") or {})
        steps.extend(a3_result.get("trace", []))

    p6_mapping = scenario.get("p6_mapping")
    if isinstance(p6_mapping, Mapping):
        event["p6_mapping"] = dict(p6_mapping)
    for key in ("spatial_ref_status", "spatial_object_source"):
        if key in scenario:
            event[key] = scenario[key]

    source_event_id = event.get("event_id")
    event_id = new_gold_id("event", scenario_id)
    if a2_result is not None:
        a2_result["event_id"] = event_id
        a2_result["trace_id"] = trace_id
    if a3_result is not None:
        a3_result["event_id"] = event_id
        a3_event = a3_result.get("event")
        if isinstance(a3_event, dict):
            a3_event["event_id"] = event_id
            a3_event["trace_id"] = trace_id
    event.update({
        "event_id": event_id,
        "source_event_id": source_event_id,
        "scenario_id": scenario_id,
        "trace_id": trace_id,
        "is_simulated": True,
        "data_source": scenario.get("data_source", f"local_gold_fixture:{scenario_id}"),
    })
    save_gold_record("event", scenario_id, event, record_id=event_id)
    steps.append({"step": "event_persist", "status": "persisted", "event_id": event_id,
                  "execution_engine": "local"})

    narrative = (event.get("field_report") or {}).get("narrative")
    query_parts = [scenario.get(key) for key in ("admin_area", "hazard_point_name") if scenario.get(key)]
    query_parts.extend(event.get(key) for key in ("hazard_point_id", "event_type") if event.get(key))
    if narrative:
        query_parts.append(narrative)
    monitoring = event.get("monitoring")
    if isinstance(monitoring, Mapping):
        series = monitoring.get("series") or monitoring.get("observations")
        if isinstance(series, list) and series:
            latest = series[-1] if isinstance(series[-1], Mapping) else {}
            latest_fields = (
                "observed_at", "rainfall_increment_mm", "short_term_rainfall_mm",
                "displacement_mm", "displacement_rate_mm_per_day", "reservoir_level_m",
                "reservoir_trend", "recovery_status",
            )
            compact = {
                "data_source": event.get("data_source"),
                "is_simulated": event.get("is_simulated") is True,
                "observation_count": len(series),
                "window_start": series[0].get("observed_at") if isinstance(series[0], Mapping) else None,
                "window_end": latest.get("observed_at"),
                "latest_observation": {key: latest[key] for key in latest_fields if key in latest},
                "triggered_rules": [
                    {key: item[key] for key in ("metric", "operator", "threshold", "observed_value", "observed_at") if key in item}
                    for item in monitoring.get("triggered_rules", []) if isinstance(item, Mapping)
                ],
                "recovery_stage": monitoring.get("recovery_stage"),
            }
            query_parts.append("监测摘要=" + json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
    query = " ".join(str(part) for part in query_parts) or "宜昌地质灾害现场核查与处置依据"
    simulated_event = event.get("is_simulated") is True
    rag_status = "completed"
    rag_execution_engine = "geo-rag"
    rag_error = None
    try:
        retrieval = await rag_retriever(query, top_k=8)
        evidence = retrieval.get("evidences", []) if isinstance(retrieval, Mapping) else []
    except Exception as exc:
        evidence = []
        rag_status = f"unavailable:{type(exc).__name__}"
        rag_error = str(exc)[:300]
    rag_record_id = new_gold_id("rag-retrieval", scenario_id)
    rag_record = save_gold_record(
        "rag_retrieval",
        scenario_id,
        {
            "record_id": rag_record_id,
            "event_id": event_id,
            "trace_id": trace_id,
            "query": query,
            "status": rag_status,
            "execution_engine": rag_execution_engine,
            "evidence_count": len(evidence),
            "evidence": evidence,
            "error": rag_error,
            "is_simulated": simulated_event,
            "data_source": "geo_rag 宜昌知识库检索",
        },
        record_id=rag_record_id,
        parent_id=event_id,
    )
    steps.append({"step": "yichang_three_kb_retrieval", "status": rag_status,
                  "evidence_count": len(evidence), "record_id": rag_record["record_id"],
                  "execution_engine": rag_execution_engine})

    decision = await process_decision(event, evidence)
    decision["event_id"] = event_id
    decision["trace_id"] = trace_id
    decision["is_simulated"] = True
    decision.setdefault("status", decision.get("decision_status", "completed"))
    decision_id = new_gold_id("decision", scenario_id)
    decision["decision_id"] = decision_id
    save_gold_record("decision", scenario_id, decision, record_id=decision_id, parent_id=event_id)
    for key in ("p6_snapshot", "p6_dynamic_snapshot", "p6_exposure"):
        if key in decision:
            event[key] = decision[key]
    update_gold_record(event_id, event)
    steps.append({"step": "a4_review_composition", "status": decision.get("decision_status"),
                  "execution_engine": decision.get("execution_engine", "local"),
                  "formal_warning_created": False})

    actions = decision.get("action_items") if isinstance(decision.get("action_items"), list) else []
    a4_proposals = decision.get("task_proposals")
    if isinstance(a4_proposals, Mapping):
        a4_proposals = [a4_proposals]
    a4_proposals = [item for item in a4_proposals if isinstance(item, Mapping)] \
        if isinstance(a4_proposals, list) else []
    a4_proposal = dict(a4_proposals[0]) if a4_proposals else None
    action = dict(actions[0]) if actions and isinstance(actions[0], Mapping) else {
        "action": "人工核查事件事实和空间对象关联",
        "location": event.get("location") or event.get("admin_area"),
        "human_approval_required": True,
    }
    if a4_proposal:
        proposed_action = a4_proposal.get("action") or a4_proposal.get("task")
        if isinstance(proposed_action, Mapping):
            action = {**action, **dict(proposed_action)}
        else:
            if isinstance(proposed_action, str) and proposed_action.strip():
                action["action"] = proposed_action.strip()
            for field in (
                "location", "category", "priority", "responsible_department", "person",
                "due_at", "resources", "completion_criteria", "human_approval_required",
            ):
                if field in a4_proposal:
                    action[field] = a4_proposal[field]
    proposal_id = new_gold_id("task-proposal", scenario_id)
    decision["task_proposal_id"] = proposal_id
    proposal = {
        "proposal_id": proposal_id,
        "decision_id": decision_id,
        "event_id": event_id,
        "trace_id": trace_id,
        "status": "awaiting_human_approval",
        "action": action,
        "a4_proposal": a4_proposal,
        "is_simulated": True,
        "data_source": scenario["data_source"],
        "execution_engine": "local",
    }
    save_gold_record("task_proposal", scenario_id, proposal, record_id=proposal_id, parent_id=event_id)
    update_gold_record(decision_id, decision)

    task_record = None
    if scenario_id == "GOLD-03":
        prior_tasks = list_gold_records("GOLD-02", "task")
        if prior_tasks:
            task_record = prior_tasks[-1]
            task_payload = dict(task_record["payload"])
            task_payload["status"] = "awaiting_recovery_review"
            task_payload["last_event_id"] = event_id
            task_payload["trace_id"] = trace_id
            task_record = update_gold_record(task_record["record_id"], task_payload)
    elif test_task_approved:
        task_id = new_gold_id("task", scenario_id)
        task_approval_id = new_gold_id("approval", scenario_id)
        assignment = approval.get("task_assignment") if isinstance(approval.get("task_assignment"), Mapping) else {}
        reviewed_action = dict(action)
        for field, aliases in (
            ("responsible_department", ("responsible_department", "department")),
            ("person", ("person", "responsible_person")),
            ("due_at", ("due_at", "deadline")),
            ("resources", ("resources", "resource_requirements")),
            ("completion_criteria", ("completion_criteria", "acceptance_criteria")),
        ):
            value = next((assignment.get(key) for key in aliases if assignment.get(key) not in (None, "", [])), None)
            if value is not None:
                reviewed_action[field] = value
        if assignment:
            reviewed_action["assignment_source"] = "simulated_gold_test_harness"
        task_payload = {
            "task_id": task_id,
            "approval_id": task_approval_id,
            "event_id": event_id,
            "decision_id": decision_id,
            "proposal_id": proposal_id,
            "trace_id": trace_id,
            "scenario_id": scenario_id,
            "status": "demo_assigned",
            "action": reviewed_action,
            "task_source": "宜昌 GeoGuard Gold 隔离演示任务",
            "reviewer_id": approver,
            "approval_mode": "simulated_gold_test_harness",
            "is_simulated": True,
            "data_source": scenario["data_source"],
            "execution_engine": "local",
            "formal_java_task_created": False,
        }
        task_record = save_gold_record("task", scenario_id, task_payload, record_id=task_id, parent_id=event_id)
        decision["task_created"] = True
        decision["task_id"] = task_id
        decision["task_execution_engine"] = "local"
        if actions and isinstance(actions[0], dict):
            actions[0].update({"task_id": task_id, "dispatch_status": "demo_assigned"})
        update_gold_record(decision_id, decision)
        save_gold_record(
            "approval", scenario_id,
            {"approval_type": "task", "reviewer_id": approver, "trace_id": trace_id,
             "approval_id": task_approval_id, "event_id": event_id, "proposal_id": proposal_id,
             "task_id": task_id, "reviewed_action": reviewed_action,
             "approval_mode": "simulated_gold_test_harness",
             "approved": True, "is_simulated": True, "data_source": scenario["data_source"]},
            record_id=task_approval_id,
            parent_id=task_id,
        )
    if task_record:
        steps.append({"step": "task_persist", "status": task_record["status"],
                      "task_id": task_record["record_id"], "execution_engine": "local"})
    else:
        steps.append({"step": "task_persist", "status": "awaiting_human_approval",
                      "task_id": None, "proposal_id": proposal_id, "execution_engine": "local"})

    field_verification = scenario.get("field_verification")
    attachments = []
    if a2_result:
        attachments.extend({"file_ref": ref, "is_simulated": True,
                            "data_source": a2_result.get("data_source")}
                           for ref in (a2_result.get("field_report") or {}).get("photo_refs", []))
    if isinstance(field_verification, Mapping):
        attachments.extend({"file_ref": ref, "is_simulated": True,
                            "data_source": field_verification.get("data_source")}
                           for ref in field_verification.get("photo_refs", []))
    for attachment in attachments:
        attachment["attachment_id"] = new_gold_id("attachment", scenario_id)
        attachment["event_id"] = event_id
        attachment["trace_id"] = trace_id
        attachment["is_simulated"] = True
        save_gold_record("attachment", scenario_id, attachment,
                         record_id=attachment["attachment_id"], parent_id=event_id)
    if not harness_enabled or not task_record:
        steps.append({"step": "feedback_persist", "status": "awaiting_human_task_and_feedback"})
        steps.append({"step": "a5_report_persist", "status": "waiting_for_persisted_task_and_feedback"})
        return {
            "status": "persisted_pending_approval" if not task_record else "persisted_awaiting_recovery_review",
            "scenario_id": scenario_id,
            "trace_id": trace_id,
            "correlation_id": event.get("correlation_id"),
            "event_id": event_id,
            "task_id": task_record["record_id"] if task_record else None,
            "report_id": None,
            "is_simulated": True,
            "data_source": scenario.get("data_source"),
            "execution_engine": "local",
            "approval_mode": "human_approval_required",
            "a2": a2_result,
            "a3": a3_result,
            "rag": {"status": rag_status, "execution_engine": rag_execution_engine,
                    "record_id": rag_record_id, "evidence_count": len(evidence), "evidence": evidence,
                    "error": rag_error},
            "a4": decision,
            "java_task": {
                "status": task_record["status"] if task_record else "awaiting_human_approval",
                "task_id": task_record["record_id"] if task_record else None,
                "created": bool(task_record and task_record["record_type"] == "task"),
                "execution_engine": "local",
                "formal_java_task_created": False,
            },
            "task_proposal": proposal,
            "a5": None,
            "evidence_archive": {"status": "waiting_for_persisted_task_and_feedback",
                                 "document_id": None, "execution_engine": "local", "is_simulated": True},
            "persisted_record_ids": [
                record["record_id"]
                for record in list_gold_records(scenario_id)
                if record["payload"].get("trace_id") == trace_id
            ] + ([task_record["record_id"]] if task_record else []),
            "expected": scenario.get("expected", {}),
            "trace": [{"trace_id": trace_id, "is_simulated": True, **step} for step in steps],
        }
    feedback: list[dict[str, Any]] = []
    if isinstance(field_verification, Mapping):
        feedback_item = {
            **dict(field_verification),
            "feedback_id": new_gold_id("feedback", scenario_id),
            "event_id": event_id,
            "trace_id": trace_id,
            "task_id": task_record["record_id"] if task_record else None,
            "status": "persisted_simulated_field_verification",
            "is_simulated": True,
        }
        save_gold_record("feedback", scenario_id, feedback_item,
                         record_id=feedback_item["feedback_id"],
                         parent_id=feedback_item["task_id"] or event_id)
        feedback.append(feedback_item)
        steps.append({"step": "feedback_persist", "status": "persisted_simulated_fixture_feedback",
                      "feedback_id": feedback_item["feedback_id"], "execution_engine": "local"})
    else:
        steps.append({"step": "feedback_persist", "status": "no_feedback_in_fixture"})

    persisted_event = get_gold_record(event_id)
    persisted_decision = next(
        (record["payload"] for record in reversed(list_gold_records(scenario_id, "decision"))
         if record.get("parent_id") == event_id),
        decision,
    )
    persisted_feedback = [record["payload"] for record in list_gold_records(scenario_id, "feedback")
                          if record.get("payload", {}).get("trace_id") == trace_id]
    persisted_task_proposals = [record["payload"] for record in list_gold_records(scenario_id, "task_proposal")
                                if record.get("parent_id") == event_id
                                and record.get("payload", {}).get("trace_id") == trace_id]
    persisted_approvals = [record["payload"] for record in list_gold_records(scenario_id, "approval")
                           if record.get("payload", {}).get("trace_id") == trace_id]
    persisted_attachments = [record["payload"] for record in list_gold_records(scenario_id, "attachment")
                             if record.get("payload", {}).get("trace_id") == trace_id]
    report_tasks = [task_record["payload"]] if task_record else []
    report_facts = {
        "event": persisted_event["payload"] if persisted_event else {},
        "tasks": report_tasks,
        "task_proposals": persisted_task_proposals,
        "approvals": persisted_approvals,
        "feedback": persisted_feedback,
        "risk_review": persisted_decision,
        "attachments": persisted_attachments,
        "execution_trace": {
            "event_trace_id": trace_id,
            "a2": a2_result.get("trace") if isinstance(a2_result, Mapping) else None,
            "a3": a3_result.get("trace") if isinstance(a3_result, Mapping) else None,
            "a4": persisted_decision.get("execution_trace") or persisted_decision.get("generation"),
            "execution_engine": persisted_decision.get("execution_engine", "local"),
        },
        "evidence_status": {
            "status": rag_status,
            "execution_engine": rag_execution_engine,
            "evidence_count": len(evidence),
            "evidence_ids": [item.get("evidence_id") for item in evidence if isinstance(item, Mapping)],
            "is_simulated": simulated_event,
        },
        "facts_status": "ready" if persisted_event else "unavailable",
        "source_status": {"event": "sqlite_readback", "tasks": "sqlite_readback",
                           "task_proposals": "sqlite_readback", "approvals": "sqlite_readback",
                           "feedback": "sqlite_readback", "review": "sqlite_readback",
                           "attachments": "sqlite_readback", "rag_retrieval": "sqlite_readback"},
    }
    report = await generate_report_from_facts(
        report_facts,
        user=str(event.get("correlation_id") or event_id),
        query="根据已持久化的宜昌Gold事件、任务、反馈与证据生成结构化调查复盘草稿；保留缺失项与模拟标记。",
        allow_simulated_gold_dify=True,
    )
    report_id = new_gold_id("report", scenario_id)
    report["report_id"] = report_id
    report["trace_id"] = trace_id
    report["is_simulated"] = True
    report["scenario_id"] = scenario_id
    report["data_source"] = scenario.get("data_source", f"local_gold_fixture:{scenario_id}")
    report["execution_engine"] = report.get("execution_engine", "local")
    associations = report.setdefault("associations", {})
    associations.update({"event_id": event_id, "new_report_id": report_id})
    if task_record:
        associations["task_ids"] = [task_record["record_id"]]
    report["review_status"] = "approved" if test_report_approved else "not_reviewed"
    report["approval_mode"] = "simulated_gold_test_harness" if harness_enabled else "human_approval_required"
    report["status"] = "approved_unarchived" if test_report_approved else "draft_unreviewed_unarchived"
    report["report_approved"] = test_report_approved
    report["archive_approved"] = test_archive_approved
    report["archive_status"] = "pending_archive" if test_archive_approved else "awaiting_archive_approval"
    report["evidence_library_status"] = "not_submitted"
    report_text = sync_report_markdown_status(report)
    if report_text is not None:
        report["report_text"] = report_text
        report.setdefault("sections", {})["legacy_report_markdown"] = report_text
    save_gold_record("report", scenario_id, report, record_id=report_id, parent_id=event_id)
    if test_report_approved:
        save_gold_record(
            "approval", scenario_id,
            {"approval_type": "report", "report_id": report_id, "reviewer_id": approver,
             "trace_id": trace_id, "approval_mode": "simulated_gold_test_harness",
             "approved": True, "is_simulated": True, "data_source": scenario["data_source"]},
            parent_id=report_id,
        )
    if test_archive_approved:
        save_gold_record(
            "approval", scenario_id,
            {"approval_type": "archive", "report_id": report_id, "reviewer_id": approver,
             "trace_id": trace_id, "approval_mode": "simulated_gold_test_harness",
             "approved": True, "is_simulated": True, "data_source": scenario["data_source"]},
            parent_id=report_id,
        )
    steps.append({"step": "a5_report_persist", "status": report["status"],
                  "report_id": report_id, "execution_engine": report["execution_engine"]})

    archive_result: dict[str, Any] = {
        "status": "awaiting_report_and_archive_approval",
        "document_id": None,
        "execution_engine": "local" if report.get("is_simulated") is True else "geo-rag",
    }
    if test_report_approved and test_archive_approved:
        if report.get("is_simulated") is True:
            evidence_id = new_gold_id("demo-evidence", scenario_id)
            archive_result = {
                "status": "archived_demo_local",
                "document_id": evidence_id,
                "execution_engine": "local",
                "is_simulated": True,
                "reviewer_id": approver,
            }
            report["archive_status"] = "archived_demo_local"
            report["evidence_library_status"] = "archived_demo_local"
            report["status"] = "archived_demo_local"
            report_text = sync_report_markdown_status(report)
            if report_text is not None:
                report["report_text"] = report_text
                report.setdefault("sections", {})["legacy_report_markdown"] = report_text
            update_gold_record(report_id, report)
            save_gold_record(
                "demo_evidence",
                scenario_id,
                {
                    "evidence_id": evidence_id,
                    "report_id": report_id,
                    "event_id": event_id,
                    "trace_id": trace_id,
                    "report_text": report.get("report_text"),
                    "report": dict(report),
                    "reviewer_id": approver,
                    "approval_mode": report["approval_mode"],
                    "status": "archived_demo_local",
                    "archive_status": "archived_demo_local",
                    "is_simulated": True,
                    "data_source": scenario["data_source"],
                    "execution_engine": "local",
                },
                record_id=evidence_id,
                parent_id=report_id,
            )
        else:
            try:
                archive_result = await report_archiver(report, report_approved=True, archive_approved=True)
            except Exception as exc:
                archive_result = {"status": f"unavailable:{type(exc).__name__}", "document_id": None}
            report["archive_status"] = archive_result.get("status", "unknown")
            if report["archive_status"] == "indexed":
                report["status"] = "archived"
            elif report["archive_status"] in {"added", "submitted"}:
                report["status"] = "archive_submitted_index_pending"
            update_gold_record(report_id, report)
        archive_payload = {
            **archive_result,
            "report_id": report_id,
            "event_id": event_id,
            "trace_id": trace_id,
            "is_simulated": report.get("is_simulated") is True,
            "data_source": scenario["data_source"],
            "execution_engine": archive_result.get("execution_engine") or (
                "geo-rag" if archive_result.get("document_id") else "local"
            ),
        }
        archive_record = save_gold_record("archive", scenario_id, archive_payload, parent_id=report_id)
    else:
        archive_record = None

    if report.get("is_simulated") is True:
        a1_verification = {
            "status": "not_attempted_simulated_local_only",
            "execution_engine": "local",
            "evidence_ids": [],
            "report_id_match": "not_attempted",
            "is_simulated": True,
        }
        if archive_result.get("status") == "archived_demo_local":
            try:
                a1_lookup = await answer_yichang_query(report_id)
                evidence_ids = a1_lookup.get("evidence_ids", [])
                retrieved = (
                    a1_lookup.get("report_id") == report_id
                    and a1_lookup.get("report_id_match") == "matched"
                    and evidence_ids == [archive_record["record_id"]]
                    and a1_lookup.get("execution_engine") == "local"
                    and a1_lookup.get("is_simulated") is True
                )
                a1_verification = {
                    "status": "retrieved_demo_local" if retrieved else "not_retrieved_demo_local",
                    "execution_engine": "local",
                    "report_id_match": a1_lookup.get("report_id_match"),
                    "evidence_ids": evidence_ids,
                    "evidence_count": len(evidence_ids),
                    "is_simulated": a1_lookup.get("is_simulated") is True,
                }
            except Exception as exc:
                a1_verification = {
                    "status": f"unavailable:{type(exc).__name__}",
                    "execution_engine": "local",
                    "report_id_match": "unavailable",
                    "evidence_ids": [],
                    "is_simulated": True,
                }
    else:
        a1_verification = {"status": "not_attempted", "execution_engine": "geo-rag", "evidence_ids": []}
    if report.get("is_simulated") is not True and archive_result.get("status") in {"indexed", "added", "submitted"}:
        try:
            indexed = await rag_retriever(f"{report_id} 宜昌地质灾害事件复盘报告", top_k=5)
            indexed_evidence = indexed.get("evidences", []) if isinstance(indexed, Mapping) else []
            matched_evidence = [item for item in indexed_evidence if isinstance(item, Mapping)
                                and report_id in json.dumps(item, ensure_ascii=False)]
            verification_status = "retrieved" if matched_evidence else (
                "not_found" if archive_result.get("status") == "indexed" else "index_pending"
            )
            a1_verification = {
                "status": verification_status,
                "execution_engine": "geo-rag",
                "evidence_count": len(matched_evidence),
                "evidence_ids": [item.get("evidence_id") or item.get("document_id")
                                 for item in matched_evidence],
            }
        except Exception as exc:
            a1_verification = {"status": f"unavailable:{type(exc).__name__}",
                               "execution_engine": "geo-rag", "evidence_ids": []}

    task_status = task_record["status"] if task_record else "awaiting_human_approval"
    approval_mode = "simulated_gold_test_harness" if harness_enabled else "human_approval_required"
    final_status = "completed_persisted" if harness_enabled and task_record else "persisted_pending_approval"
    archive_status = archive_result.get("status")
    if task_record and archive_status == "archived_demo_local":
        final_status = "completed_persisted_demo_local"
    elif task_record and archive_status in {"indexed", "added", "submitted"}:
        final_status = (
            "completed_persisted_pending_index_verification"
            if a1_verification["status"] != "retrieved"
            else "completed_persisted"
        )
    elif task_record and test_report_approved and test_archive_approved:
        final_status = "completed_persisted_archive_failed"
    elif task_record:
        final_status = "completed_persisted_awaiting_report_archive_approval"

    return {
        "status": final_status,
        "scenario_id": scenario_id,
        "trace_id": trace_id,
        "correlation_id": event.get("correlation_id"),
        "event_id": event_id,
        "task_id": task_record["record_id"] if task_record else None,
        "report_id": report_id,
        "is_simulated": True,
        "data_source": scenario.get("data_source"),
        "execution_engine": "local",
        "approval_mode": approval_mode,
        "a2": a2_result,
        "a3": a3_result,
        "rag": {"status": rag_status, "execution_engine": rag_execution_engine,
                "record_id": rag_record_id, "evidence_count": len(evidence), "evidence": evidence,
                "error": rag_error},
        "a4": decision,
        "java_task": {
            "status": task_status,
            "task_id": task_record["record_id"] if task_record else None,
            "created": bool(task_record and task_record["record_type"] == "task"),
            "execution_engine": "local",
            "formal_java_task_created": False,
        },
        "task_proposal": proposal,
        "task_approval_id": task_record["payload"].get("approval_id") if task_record else None,
        "a5": report,
        "evidence_archive": {**archive_result, "a1_verification": a1_verification},
        "persisted_record_ids": [
            record["record_id"]
            for record in list_gold_records(scenario_id)
            if record["payload"].get("trace_id") == trace_id
        ] + ([task_record["record_id"]] if task_record else []),
        "expected": scenario.get("expected", {}),
        "trace": [{"trace_id": trace_id, "is_simulated": True, **step} for step in steps],
    }
