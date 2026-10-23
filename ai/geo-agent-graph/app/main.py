import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from .graph import COMPILED_GRAPHS, WORKFLOW_DEFINITIONS
from .java_client import (
    create_reviewed_task,
    list_task_feedback,
    lookup_business_record,
    submit_reviewed_task_feedback,
)
from .llm import llm_enabled
from .rag_archive import archive_approved_report, get_yichang_document_status
from .rag_client import retrieve_yichang
from .schemas import RunRequest, RunResponse
from .config import settings
from .dify_registry import list_dify_apps
from .dify_adapters.a1_qa import map_verified_gold_report_evidence, run_a1_chatflow
from .dify_adapters.a3_monitor import process_monitoring_with_dify
from .dify_adapters.a5_report import (
    archive_persisted_report,
    generate_report_draft as generate_persisted_report_draft,
    generate_report_from_facts,
)
from .yichang_decision import process_decision
from .yichang_field import process_field_report
from .yichang_gold import run_gold_scenario
from .yichang_gold_runner import (
    approve_gold_final_report,
    approve_gold_plan,
    create_gold_retrospective,
    execute_gold_a2,
    execute_gold_a3,
    execute_gold_a4,
    execute_gold_a5_investigation,
    read_dual_gold_run,
    replay_gold_feedbacks,
    review_gold_task,
    run_gold_recovery_stage,
    start_dual_gold_run,
)
from .yichang_monitor import RealMonitoringAdapter
from .yichang_qa import answer_yichang_query
from .yichang_contract import YICHANG_KNOWLEDGE_BASES
from .yichang_report import render_local_report_markdown, sync_report_markdown_status
from .yichang_store import (
    get_gold_record,
    list_gold_children,
    list_gold_records,
    new_gold_id,
    save_gold_record,
    update_gold_record,
)

logger = logging.getLogger(__name__)
app = FastAPI(
    title="Geo Agent Graph API",
    version="0.2.0",
    description="LangGraph orchestration layer for geological-disaster business agents.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


def _verified_gold_archive_proof(report_payload, archive_payload, approval, report_id, event_id):
    approval_payload = approval.get("payload", {}) if isinstance(approval, dict) else {}
    revision = archive_payload.get("archive_revision")
    revision_suffix = "__indexed" if revision == "indexed" else ""
    expected_file_name = f"宜昌GeoGuard复盘报告_{report_id}{revision_suffix}.docx"
    if not (
        report_payload.get("report_approved") is True
        and report_payload.get("archive_approved") is True
        and report_payload.get("review_status") == "approved"
        and report_payload.get("approval_mode") == "simulated_gold_test_harness"
        and report_payload.get("is_simulated") is True
        and isinstance(report_payload.get("report_text"), str)
        and bool(report_payload["report_text"].strip())
        and archive_payload.get("gold_test_archive") is True
        and archive_payload.get("execution_engine") == "geo-rag"
        and archive_payload.get("document_id")
        and archive_payload.get("file_name") == expected_file_name
        and approval_payload.get("approval_type") == "report_and_archive"
        and approval_payload.get("approved") is True
        and approval_payload.get("report_id") == report_id
        and approval_payload.get("event_id") == event_id
        and approval_payload.get("approval_mode") == "simulated_gold_test_harness"
    ):
        return None
    return {
        "report_id": str(report_id), "event_id": event_id,
        "trace_id": report_payload.get("trace_id"),
        "report_approved": True, "archive_approved": True,
        "approval_mode": "simulated_gold_test_harness", "review_status": "approved",
        "is_simulated": True, "source_kind": "simulated_gold_indexed_archive",
        "report_text": report_payload["report_text"],
        "document_id": str(archive_payload["document_id"]), "file_name": expected_file_name,
        "archive_revision": revision or "initial",
    }


def _gold_a1_readback_status(verified, a1, a1_success):
    if not verified:
        return "not_verified"
    if a1_success:
        return "verified"
    if not a1 or a1.get("execution_engine") != "dify":
        return "retrieved_without_model_answer"
    return "document_retrieved_a1_failed"


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "geo-agent-graph",
        "llm_configured": llm_enabled(),
        "dify_apps": list_dify_apps(),
    }


async def _archive_indexed_gold_report_revision(
    report_id, event_id, report_payload, previous_archive, scenario_id,
):
    """Append an indexed-status DOCX revision after the initial report is indexed."""
    final_payload = dict(report_payload)
    final_payload.update({
        "status": "archived", "review_status": "approved", "archive_status": "indexed",
        "evidence_library_status": "indexed", "report_approved": True, "archive_approved": True,
        "is_simulated": True, "approval_mode": "simulated_gold_test_harness",
    })
    final_text = sync_report_markdown_status(final_payload)
    if final_text is not None:
        final_payload["report_text"] = final_text
        final_payload.setdefault("sections", {})["legacy_report_markdown"] = final_text
    final_payload["archive_revision"] = "indexed"

    result = await archive_approved_report(final_payload, report_approved=True, archive_approved=True)
    if not result.get("document_id"):
        return result, None, final_payload

    previous_document_id = previous_archive.get("payload", {}).get("document_id") if previous_archive else None
    archive_payload = {
        **result, "status": result.get("status"), "archive_status": result.get("status"),
        "evidence_library_status": result.get("status"),
        "report_id": str(report_id), "event_id": event_id,
        "reviewer_id": final_payload.get("reviewer_id"),
        "approval_mode": "simulated_gold_test_harness", "gold_test_archive": True,
        "is_simulated": True, "execution_engine": "geo-rag", "archive_revision": "indexed",
        "supersedes_document_id": previous_document_id,
        "data_source": final_payload.get("data_source", "local_gold_report"),
    }
    archive_record = save_gold_record("archive", scenario_id, archive_payload, parent_id=str(report_id))
    if previous_archive and result.get("status") == "indexed":
        previous_payload = dict(previous_archive.get("payload", {}))
        previous_payload["superseded_by_document_id"] = result["document_id"]
        update_gold_record(previous_archive["record_id"], previous_payload)

    final_payload.update({"archive_execution_engine": "geo-rag"})
    if result.get("status") == "indexed":
        final_payload.update({
            "document_id": result["document_id"], "supersedes_document_id": previous_document_id,
            "archive_revision_status": "indexed",
        })
    else:
        final_payload.update({
            "pending_document_id": result["document_id"], "pending_archive_revision": "indexed",
            "archive_revision_status": result.get("status"),
        })
    update_gold_record(str(report_id), final_payload)
    return archive_payload, archive_record, final_payload


@app.get("/api/v1/workflows")
async def workflows():
    return {
        "execution_engine": "langgraph",
        "workflows": [{"id": name, **definition} for name, definition in WORKFLOW_DEFINITIONS.items()],
        "dify_apps": list_dify_apps(),
    }


@app.get("/api/v1/yichang/agents")
async def yichang_agents():
    return {
        "region": "宜昌市",
        "agents": {
            "A1": {"status": "implemented", "entry": "/api/v1/yichang/qa", "knowledge_bases": 3,
                   "java_business_lookup": "/api/v1/yichang/business/{task|report}/{java_id}"},
            "A2": {"status": "field_adapter_with_optional_dify_vision", "entry": "/api/v1/yichang/field-reports", "vision_status": "requires_dify_credentials_and_server_readable_photo_bytes"},
            "A3": {"status": "gold_rules_with_optional_dify_explanation_and_alert", "entry": "/api/v1/yichang/monitor/gold", "real_monitoring_status": "not_connected"},
            "A4": {"status": "analysis_and_plan_adapters", "entry": "/api/v1/yichang/decisions", "risk_models": "missing_values_remain_missing"},
            "A5": {"status": "draft_and_archive_adapter_implemented", "entry": "/api/v1/yichang/report-drafts",
                   "archive_status": "requires_persisted_java_review_or_gold_report_and_explicit_approval"},
        },
        "llm_configured": llm_enabled(),
        "dify_apps": list_dify_apps(),
        "java_task_api_configured": bool(settings.java_backend_base_url and settings.java_backend_bearer_token),
        "java_feedback_entry": "/api/v1/yichang/tasks/{java_task_id}/feedback",
    }


@app.post("/api/v1/yichang/qa")
async def yichang_qa(req: RunRequest):
    return await answer_yichang_query(req.query, req.context)


@app.post("/api/v1/yichang/field-reports")
async def yichang_field_report(payload: dict = Body(...)):
    return await process_field_report(payload)


@app.post("/api/v1/yichang/monitor/gold")
async def yichang_gold_monitor(payload: dict = Body(...)):
    return await process_monitoring_with_dify(payload)


@app.post("/api/v1/yichang/monitor/real")
async def yichang_real_monitor():
    return RealMonitoringAdapter().process()


@app.post("/api/v1/yichang/gold/{scenario_id}/run")
async def yichang_gold_run(scenario_id: str, payload: dict = Body(default={})):
    try:
        return await run_gold_scenario(scenario_id, gold_test_approval=payload.get("gold_test_approval"))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/yichang/gold/{scenario_id}/records")
async def yichang_gold_records(scenario_id: str):
    return {"scenario_id": scenario_id, "records": list_gold_records(scenario_id)}


@app.post("/api/v1/yichang/gold-runs/{scenario_id}/start")
async def yichang_dual_gold_start(scenario_id: str, payload: dict = Body(default={})):
    try:
        return await start_dual_gold_run(scenario_id, run_id=payload.get("run_id"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/yichang/gold-runs/{run_id}")
async def yichang_dual_gold_read(run_id: str):
    try:
        return read_dual_gold_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/yichang/gold-runs/{run_id}/reports/{report_id}/docx")
async def yichang_dual_gold_report_docx(run_id: str, report_id: str):
    try:
        snapshot = read_dual_gold_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    report = next((item["payload"] for item in snapshot["records"].get("report", [])
                   if item["record_id"] == report_id), None)
    if not report:
        raise HTTPException(status_code=404, detail="Report does not belong to this Gold run")
    report = dict(report)
    report["report_text"] = sync_report_markdown_status(report) or report.get("report_text")
    report.setdefault("sections", {})["runtime_business_markdown"] = report["report_text"]
    from .yichang_gold_runner import _persist_report_docx
    report = _persist_report_docx(report)
    update_gold_record(report_id, report)
    database = settings.yichang_scenario_db_path
    report_dir = Path(database).expanduser()
    if not report_dir.is_absolute():
        report_dir = Path.cwd() / report_dir
    path = report_dir.resolve().parent / "reports" / report["docx_file_name"]
    return FileResponse(
        path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=report["docx_file_name"],
    )


@app.post("/api/v1/yichang/gold-runs/{run_id}/a4/execute")
async def yichang_dual_gold_a4_execute(run_id: str):
    try:
        return await execute_gold_a4(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/yichang/gold-runs/{run_id}/a2/execute")
async def yichang_dual_gold_a2_execute(run_id: str):
    try:
        return await execute_gold_a2(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/yichang/gold-runs/{run_id}/stages/{stage_id}/a3/execute")
async def yichang_dual_gold_a3_execute(run_id: str, stage_id: str):
    try:
        return await execute_gold_a3(run_id, stage_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/yichang/gold-runs/{run_id}/a5/investigation/execute")
async def yichang_dual_gold_a5_investigation_execute(run_id: str):
    try:
        return await execute_gold_a5_investigation(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/yichang/gold-runs/{run_id}/plan-review")
async def yichang_dual_gold_plan_review(run_id: str, payload: dict = Body(...)):
    try:
        return await approve_gold_plan(
            run_id, fixture_replay=payload.get("fixture_replay") is True,
            reviewer_id=payload.get("reviewer_id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/yichang/gold-runs/{run_id}/feedbacks/replay")
async def yichang_dual_gold_feedback_replay(run_id: str, payload: dict = Body(...)):
    try:
        return await replay_gold_feedbacks(
            run_id, fixture_replay=payload.get("fixture_replay") is True,
            stage_id=payload.get("stage_id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/yichang/gold-runs/{run_id}/stages/GOLD-03")
async def yichang_dual_gold_recovery(run_id: str):
    try:
        return await run_gold_recovery_stage(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/yichang/gold-runs/{run_id}/task-reviews/{task_fixture_key}")
async def yichang_dual_gold_task_review(run_id: str, task_fixture_key: str, payload: dict = Body(...)):
    try:
        return await review_gold_task(
            run_id, task_fixture_key, fixture_replay=payload.get("fixture_replay") is True,
            reviewer_id=payload.get("reviewer_id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/yichang/gold-runs/{run_id}/reports/retrospective")
async def yichang_dual_gold_retrospective(run_id: str, payload: dict = Body(default={})):
    try:
        return await create_gold_retrospective(run_id, execute_dify=payload.get("execute_dify") is True)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/yichang/gold-runs/{run_id}/reports/final-review")
async def yichang_dual_gold_final_review(run_id: str, payload: dict = Body(...)):
    try:
        return await approve_gold_final_report(
            run_id, fixture_replay=payload.get("fixture_replay") is True,
            reviewer_id=payload.get("reviewer_id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/yichang/decisions")
async def yichang_decision(payload: dict = Body(...)):
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    event_id = str(event.get("event_id") or "")
    event_record = None
    if event_id.upper().startswith("DEMO-GOLD-EVENT-"):
        event_record = get_gold_record(event_id)
        if (event_record is None or event_record.get("record_type") != "event"
                or event_record.get("is_simulated") is not True
                or event.get("is_simulated") is not True):
            raise HTTPException(status_code=422, detail="A persisted simulated Gold event is required")
    query = payload.get("rag_query") or " ".join(str(event.get(key) or "") for key in
                                                   ("admin_area", "hazard_point_id", "description", "event_type"))
    rag_status = "completed"
    try:
        retrieved = await retrieve_yichang(query.strip() or "宜昌地质灾害处置核查", top_k=8)
        evidence = retrieved.get("evidences", [])
    except Exception as exc:
        evidence = []
        rag_status = f"unavailable:{type(exc).__name__}"
    decision = await process_decision(event, evidence)
    decision["rag_status"] = rag_status
    if event_record is not None:
        scenario_id = event_record["scenario_id"]
        trace_id = event_record["payload"].get("trace_id") or event.get("trace_id")
        data_source = event_record["payload"].get("data_source", "local_gold_fixture")
        rag_record_id = new_gold_id("rag-retrieval", scenario_id)
        rag_record = save_gold_record(
            "rag_retrieval", scenario_id,
            {"record_id": rag_record_id, "event_id": event_id, "trace_id": trace_id,
             "query": query, "status": rag_status, "evidence_count": len(evidence),
             "evidence_ids": [item.get("evidence_id") for item in evidence if item.get("evidence_id")],
             "evidences": evidence, "is_simulated": True, "data_source": data_source,
             "execution_engine": "geo-rag"},
            record_id=rag_record_id, parent_id=event_id,
        )

        decision_id = new_gold_id("decision", scenario_id)
        proposal_id = new_gold_id("task-proposal", scenario_id)
        action_items = decision.get("action_items") if isinstance(decision.get("action_items"), list) else []
        fallback_action = dict(action_items[0]) if action_items and isinstance(action_items[0], dict) else {
            "action": "人工核查事件事实和空间对象关联",
            "location": event.get("location") or event.get("admin_area"),
            "human_approval_required": True,
        }
        a4_review = decision.get("a4_review") if isinstance(decision.get("a4_review"), dict) else {}
        a4_action_suggestions = a4_review.get("action_items")
        a4_action_suggestions = a4_action_suggestions if isinstance(a4_action_suggestions, list) else []
        a4_action = next((item for item in a4_action_suggestions
                          if isinstance(item, dict) and isinstance(item.get("action"), str)
                          and item["action"].strip()), None)
        action = dict(fallback_action)
        action_source = "local_review_fallback"
        if a4_action is not None:
            action.update({
                "action": a4_action["action"].strip(),
                "basis_evidence_ids": list(a4_action.get("basis_evidence_ids", []))
                if isinstance(a4_action.get("basis_evidence_ids"), list) else [],
                "action_source": "dify_a4_review",
                "human_approval_required": True,
                "review_status": "pending_human_confirmation",
                "dispatch_status": "not_dispatched",
            })
            action_source = "dify_a4_review"
        a4_execution = decision.get("a4_execution") if isinstance(decision.get("a4_execution"), dict) else {}
        a4_workflows = a4_execution.get("workflows") if isinstance(a4_execution.get("workflows"), dict) else {}
        a4_analysis = a4_workflows.get("analysis") if isinstance(a4_workflows.get("analysis"), dict) else {}
        dify_execution_ref = {
            key: a4_analysis[key] for key in ("trace_id", "task_id", "message_id", "conversation_id")
            if a4_analysis.get(key)
        }
        proposal = {
            "proposal_id": proposal_id, "event_id": event_id, "trace_id": trace_id,
            "decision_id": decision_id, "status": "awaiting_human_approval", "action": action,
            "action_source": action_source,
            "local_fallback_action": fallback_action if a4_action is not None else None,
            "a4_action_suggestions": a4_action_suggestions,
            "dify_execution_ref": dify_execution_ref,
            "is_simulated": True, "data_source": data_source, "execution_engine": "local",
        }
        decision.update({
            "decision_id": decision_id, "event_id": event_id, "trace_id": trace_id,
            "scenario_id": scenario_id, "is_simulated": True,
            "rag_record_id": rag_record["record_id"], "task_proposal_id": proposal_id,
            "status": decision.get("decision_status", "pending_human_confirmation"),
        })
        save_gold_record("decision", scenario_id, decision, record_id=decision_id, parent_id=event_id)
        save_gold_record("task_proposal", scenario_id, proposal, record_id=proposal_id, parent_id=event_id)

        event_payload = dict(event_record["payload"])
        for key in ("p6_snapshot", "p6_dynamic_snapshot", "p6_exposure"):
            if key in decision:
                event_payload[key] = decision[key]
        update_gold_record(event_id, event_payload)
        decision["task_proposal"] = proposal
        decision["persistence"] = {
            "status": "persisted", "execution_engine": "local",
            "decision_record_id": decision_id, "rag_record_id": rag_record["record_id"],
            "task_proposal_id": proposal_id,
        }
    return decision


@app.post("/api/v1/yichang/report-drafts")
async def yichang_report_draft(payload: dict = Body(...)):
    handle_id = payload.get("handle_id") or payload.get("handleId")
    if handle_id not in (None, ""):
        return await generate_persisted_report_draft(
            handle_id,
            user=str(payload.get("user") or f"yichang-a5-{handle_id}"),
            query=payload.get("query"),
            conversation_id=payload.get("conversation_id"),
        )

    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    event_id = str(payload.get("event_id") or event.get("event_id") or "")
    stored_event = get_gold_record(event_id) if event_id.startswith("DEMO-GOLD-EVENT-") else None
    if not stored_event or stored_event.get("record_type") != "event":
        raise HTTPException(status_code=422, detail="A persisted Java handle_id or Gold event_id is required")

    scenario_id = stored_event["scenario_id"]
    child_records = list_gold_records(scenario_id)
    event_tasks = [record for record in child_records if record["record_type"] == "task"
                   and (record["payload"].get("event_id") == event_id
                        or record["payload"].get("last_event_id") == event_id)]
    if scenario_id == "GOLD-03" and not event_tasks:
        event_tasks = [record for record in list_gold_records("GOLD-02", "task")
                       if record["payload"].get("last_event_id") == event_id]
    decisions = list_gold_children(event_id, "decision")
    if not decisions:
        raise HTTPException(status_code=409, detail="A persisted A4 decision is required before a Gold report draft")

    approved_tasks = []
    feedback_records = []
    for task in event_tasks:
        task_id = task["record_id"]
        approvals = list_gold_children(task_id, "approval")
        human_approved = any(
            item.get("payload", {}).get("approval_type") == "task"
            and item.get("payload", {}).get("approved") is True
            and item.get("payload", {}).get("approval_mode") in {"human_reviewer", "simulated_gold_test_harness"}
            and bool(str(item.get("payload", {}).get("reviewer_id") or "").strip())
            for item in approvals
        )
        if not human_approved:
            continue
        approved_tasks.append(task)
        feedback_records.extend(
            item for item in list_gold_children(task_id, "feedback")
            if item.get("payload", {}).get("task_id") == task_id
            and item.get("payload", {}).get("event_id") in {
                event_id, task.get("payload", {}).get("last_event_id")
            }
            and bool(str(item.get("payload", {}).get("reviewer_id") or "").strip())
        )
    if not approved_tasks:
        raise HTTPException(status_code=409, detail="A human-approved persisted Gold task is required before an A5 report draft")
    if not feedback_records:
        raise HTTPException(status_code=409, detail="Persisted feedback for the approved Gold task is required before an A5 report draft")
    event_tasks = approved_tasks
    task_payload = event_tasks[-1].get("payload", {})
    task_decision_id = task_payload.get("decision_id")
    risk_review_record = next((record for record in decisions
                               if record.get("record_id") == task_decision_id), None)
    if risk_review_record is None and len(decisions) == 1:
        risk_review_record = decisions[0]
    if risk_review_record is None:
        raise HTTPException(status_code=409, detail="The approved Gold task must link to its persisted A4 decision")
    attachments = list_gold_children(event_id, "attachment")
    report = await generate_report_from_facts(
        {
            "event": stored_event["payload"],
            "tasks": [record["payload"] for record in event_tasks],
            "feedback": [record["payload"] for record in feedback_records],
            "risk_review": risk_review_record["payload"],
            "attachments": [record["payload"] for record in attachments],
            "facts_status": "ready",
            "source_status": {"event": "sqlite_readback", "tasks": "human_approved_sqlite_readback",
                              "feedback": "reviewer_submitted_sqlite_readback", "review": "sqlite_readback"},
        },
        user=str(payload.get("user") or event_id),
        query=payload.get("query"),
        conversation_id=payload.get("conversation_id"),
        allow_simulated_gold_dify=True,
    )
    report_id = new_gold_id("report", scenario_id)
    report["report_id"] = report_id
    report["trace_id"] = stored_event["payload"].get("trace_id")
    report["is_simulated"] = True
    report.setdefault("associations", {}).update({
        "event_id": event_id, "new_report_id": report_id,
        "decision_id": task_decision_id, "proposal_id": task_payload.get("proposal_id"),
    })
    if report.get("generation", {}).get("generator") in {"local_template", "local_template_fallback"}:
        report["report_text"] = render_local_report_markdown(report)
        report.setdefault("sections", {})["legacy_report_markdown"] = report["report_text"]
    report["status"] = "draft_unreviewed_unarchived"
    report["review_status"] = "not_reviewed"
    report["archive_status"] = "pending_archive"
    save_gold_record("report", scenario_id, report, record_id=report_id, parent_id=event_id)
    return report


@app.post("/api/v1/yichang/reports/archive")
async def yichang_archive_report(payload: dict = Body(...)):
    report = payload.get("report")
    if not isinstance(report, dict):
        raise HTTPException(status_code=422, detail="Reviewed report payload is required")
    report_id = report.get("report_id")
    associations = report.get("associations") if isinstance(report.get("associations"), dict) else {}
    report_id = report_id or associations.get("new_report_id")
    gold_record = get_gold_record(str(report_id)) if str(report_id or "").startswith("DEMO-GOLD-") else None
    handle_id = payload.get("handle_id") or report.get("handle_id") or report.get("handleId")
    if handle_id not in (None, ""):
        return await archive_persisted_report(handle_id, report)
    if not gold_record or gold_record.get("record_type") != "report" or report.get("is_simulated") is not True:
        return {"status": "pending_archive", "reason": "persisted_java_review_or_gold_report_required",
                "document_id": None}
    if payload.get("report_approved") is not True or payload.get("archive_approved") is not True:
        return {"status": "awaiting_report_and_archive_approval", "document_id": None}
    reviewer_id = str(payload.get("reviewer_id") or "").strip()
    if not reviewer_id:
        raise HTTPException(status_code=422, detail="reviewer_id is required for Gold report approval")
    if not isinstance(report.get("report_text"), str) or not report["report_text"].strip():
        raise HTTPException(status_code=422, detail="report_text is required for Gold demo evidence")

    report_payload = dict(gold_record["payload"])
    persisted_associations = report_payload.get("associations")
    persisted_associations = persisted_associations if isinstance(persisted_associations, dict) else {}
    event_id = str(gold_record.get("parent_id") or persisted_associations.get("event_id") or "")
    event_record = get_gold_record(event_id) if event_id else None
    if (
        not event_id
        or not event_record
        or event_record.get("record_type") != "event"
        or event_record.get("scenario_id") != gold_record.get("scenario_id")
        or event_record.get("is_simulated") is not True
        or event_record.get("payload", {}).get("event_id") != event_id
        or persisted_associations.get("event_id") not in (None, event_id)
    ):
        raise HTTPException(status_code=409, detail="Gold report event association is not verified")
    if (
        associations.get("event_id") not in (None, "", event_id)
        or associations.get("new_report_id") not in (None, "", str(report_id))
        or report.get("trace_id") not in (None, "", report_payload.get("trace_id"))
    ):
        raise HTTPException(status_code=409, detail="Reviewed report cannot replace persisted event, report, or trace IDs")

    existing_archives = list_gold_children(str(report_id), "archive")
    if payload.get("geo_rag_gold_test_archive") is True:
        archived = next((item for item in reversed(existing_archives)
                         if item.get("payload", {}).get("gold_test_archive") is True
                         and item.get("payload", {}).get("execution_engine") == "geo-rag"
                         and item.get("payload", {}).get("document_id")), None)
        if archived:
            report_payload.setdefault("reviewer_id", reviewer_id)
            if archived.get("payload", {}).get("archive_revision") != "indexed":
                final_result, final_record, final_report_payload = await _archive_indexed_gold_report_revision(
                    str(report_id), event_id, report_payload, archived, gold_record["scenario_id"],
                )
                if not final_record:
                    return {
                        **dict(archived["payload"]), "status": "indexed_revision_pending",
                        "final_revision_status": final_result.get("status"), "idempotent": True,
                    }
                archived = final_record
                report_payload = final_report_payload
            result = dict(archived["payload"])
            document_id = result.get("document_id")
            previous_readback = result.get("a1_readback")
            retry_a1 = not previous_readback or (
                previous_readback.get("status") in {"not_verified", "unavailable"}
                and not previous_readback.get("message_id")
            )
            if retry_a1 and document_id:
                try:
                    document = await get_yichang_document_status(str(document_id))
                    index_status = document.get("status")
                    result["index_status"] = index_status
                    if index_status == "indexed":
                        approval = next((item for item in list_gold_children(str(report_id), "approval")
                                         if item.get("payload", {}).get("approval_type") == "report_and_archive"), None)
                        proof = _verified_gold_archive_proof(
                            report_payload, result, approval, str(report_id), event_id,
                        )
                        query = f"回查宜昌 Gold 复盘报告 {report_id}，事件 {event_id} 的现场发现和处置建议。"
                        retrieved = await retrieve_yichang(query, top_k=100)
                        evidence = retrieved.get("evidences", [])
                        verified = map_verified_gold_report_evidence(
                            str(report_id), evidence, expected_event_id=event_id,
                            expected_trace_id=report_payload.get("trace_id"),
                            verified_archive=proof,
                        )
                        a1 = await run_a1_chatflow(
                            query, evidence,
                            {"report_id": str(report_id), "event_id": event_id,
                             "report_trace_id": report_payload.get("trace_id")},
                            verified_gold_archive=proof,
                        ) if proof and verified else None
                        a1_success = bool(a1 and a1.get("execution_engine") == "dify"
                                          and a1.get("status") in {"completed", "succeeded", "success"})
                        a1_readback = {
                            "status": _gold_a1_readback_status(verified, a1, a1_success),
                            "retrieval_status": "verified" if verified else "not_verified",
                            "answer_status": "completed" if a1_success else (a1.get("status") if a1 else "not_run"),
                            "retrieval_engine": "geo-rag",
                            "answer_execution_engine": a1.get("execution_engine") if a1 else "not_run",
                            "report_id": str(report_id), "event_id": event_id,
                            "document_id": document_id,
                            "knowledge_base_id": YICHANG_KNOWLEDGE_BASES["evidence"],
                            "evidence_ids": [item.get("evidence_id") for item in verified],
                            "execution_engine": a1.get("execution_engine") if a1 else "local",
                            "status_detail": a1.get("status") if a1 else "not_run",
                            "workflow_run_id": a1.get("workflow_run_id") if a1 else None,
                            "message_id": a1.get("message_id") if a1 else None,
                            "trace_id": a1.get("trace_id") if a1 else None,
                            "error": a1.get("error") if a1 else None,
                        }
                        result.update({"status": "indexed", "archive_status": "indexed",
                                       "evidence_library_status": "indexed", "a1_readback": a1_readback})
                        archive_payload = {**result, "gold_test_archive": True,
                                           "execution_engine": "geo-rag", "is_simulated": True}
                        update_gold_record(archived["record_id"], archive_payload)
                        current_report = get_gold_record(str(report_id))
                        if current_report:
                            current_payload = dict(current_report["payload"])
                            current_payload.update({
                                "status": "archived", "archive_status": "indexed",
                                "evidence_library_status": "indexed", "document_id": document_id,
                                "a1_readback": a1_readback, "is_simulated": True,
                            })
                            current_payload["report_text"] = sync_report_markdown_status(current_payload) or current_payload.get("report_text")
                            current_payload.setdefault("sections", {})["legacy_report_markdown"] = current_payload["report_text"]
                            update_gold_record(str(report_id), current_payload)
                        superseded_document_id = archived.get("payload", {}).get("supersedes_document_id")
                        if superseded_document_id:
                            for old_archive in list_gold_children(str(report_id), "archive"):
                                if old_archive.get("payload", {}).get("document_id") == superseded_document_id:
                                    old_payload = dict(old_archive["payload"])
                                    old_payload["superseded_by_document_id"] = document_id
                                    update_gold_record(old_archive["record_id"], old_payload)
                except Exception as exc:
                    result["index_check_error"] = type(exc).__name__
            result["idempotent"] = True
            return result

        report_payload["report_text"] = report["report_text"].strip()
        report_payload.update({
            "review_status": "approved",
            "status": "approved_unarchived",
            "approval_mode": "simulated_gold_test_harness",
            "reviewer_id": reviewer_id,
            "archive_status": "pending_archive",
            "evidence_library_status": "pending_archive",
            "report_approved": True,
            "archive_approved": True,
            "is_simulated": True,
        })
        report_payload["report_text"] = sync_report_markdown_status(report_payload) or report_payload["report_text"]
        report_payload.setdefault("sections", {})["legacy_report_markdown"] = report_payload["report_text"]
        archive_result = await archive_approved_report(
            report_payload, report_approved=True, archive_approved=True,
        )
        archive_status = str(archive_result.get("status") or "error")
        archive_record_payload = {
            **archive_result,
            "status": archive_status,
            "archive_status": archive_status,
            "report_id": str(report_id),
            "event_id": event_id,
            "reviewer_id": reviewer_id,
            "approval_mode": "simulated_gold_test_harness",
            "gold_test_archive": True,
            "is_simulated": True,
            "execution_engine": "geo-rag",
            "data_source": report_payload.get("data_source", "local_gold_report"),
        }
        archive_record = save_gold_record(
            "archive", gold_record["scenario_id"], archive_record_payload,
            parent_id=str(report_id),
        )
        approvals = list_gold_children(str(report_id), "approval")
        approval = next((item for item in approvals
                         if item.get("payload", {}).get("approval_type") == "report_and_archive"), None)
        if approval is None:
            approval = save_gold_record(
                "approval", gold_record["scenario_id"],
                {"approval_type": "report_and_archive", "report_id": str(report_id),
                 "event_id": event_id, "reviewer_id": reviewer_id,
                 "trace_id": report_payload.get("trace_id"),
                 "approval_mode": "simulated_gold_test_harness", "approved": True,
                 "is_simulated": True, "execution_engine": "local"},
                parent_id=str(report_id),
            )
        report_payload["approval_id"] = approval["record_id"]
        if archive_status != "indexed":
            report_payload.update({
                "status": "archive_pending", "archive_status": archive_status,
                "evidence_library_status": archive_status, "archive_execution_engine": "geo-rag",
                "is_simulated": True,
            })
            report_payload["report_text"] = sync_report_markdown_status(report_payload) or report_payload["report_text"]
            report_payload.setdefault("sections", {})["legacy_report_markdown"] = report_payload["report_text"]
        update_gold_record(str(report_id), report_payload)

        if archive_status == "indexed" and archive_result.get("document_id"):
            initial_archive = {"record_id": archive_record["record_id"], "payload": archive_record_payload}
            final_result, final_record, final_report_payload = await _archive_indexed_gold_report_revision(
                str(report_id), event_id, report_payload, initial_archive, gold_record["scenario_id"],
            )
            if not final_record:
                return {
                    **archive_result, "status": "indexed_revision_pending",
                    "final_revision_status": final_result.get("status"),
                    "report_id": str(report_id), "event_id": event_id,
                    "approval_id": approval["record_id"], "is_simulated": True,
                    "gold_test_archive": True, "execution_engine": "geo-rag",
                }
            archive_result = final_result
            archive_record = final_record
            archive_record_payload = final_record["payload"]
            report_payload = final_report_payload
            if archive_result.get("status") != "indexed":
                return {
                    **archive_result, "status": "archive_finalization_pending",
                    "report_id": str(report_id), "event_id": event_id,
                    "approval_id": approval["record_id"], "is_simulated": True,
                    "gold_test_archive": True, "execution_engine": "geo-rag",
                }

        if archive_status == "indexed" and archive_result.get("status") == "indexed" and archive_result.get("document_id"):
            query = f"回查宜昌 Gold 复盘报告 {report_id}，事件 {event_id} 的现场发现和处置建议。"
            try:
                retrieved = await retrieve_yichang(query, top_k=100)
                evidence = retrieved.get("evidences", [])
                proof = _verified_gold_archive_proof(
                    report_payload, archive_record_payload, approval, str(report_id), event_id,
                )
                verified = map_verified_gold_report_evidence(
                    str(report_id), evidence, expected_event_id=event_id,
                    expected_trace_id=report_payload.get("trace_id"),
                    verified_archive=proof,
                )
                a1 = await run_a1_chatflow(
                    query, evidence,
                    {"report_id": str(report_id), "event_id": event_id,
                     "report_trace_id": report_payload.get("trace_id")},
                    verified_gold_archive=proof,
                ) if proof and verified else None
                a1_success = bool(a1 and a1.get("execution_engine") == "dify"
                                  and a1.get("status") in {"completed", "succeeded", "success"})
                a1_readback = {
                    "status": _gold_a1_readback_status(verified, a1, a1_success),
                    "retrieval_status": "verified" if verified else "not_verified",
                    "answer_status": "completed" if a1_success else (a1.get("status") if a1 else "not_run"),
                    "retrieval_engine": "geo-rag",
                    "answer_execution_engine": a1.get("execution_engine") if a1 else "not_run",
                    "report_id": str(report_id),
                    "event_id": event_id,
                    "document_id": archive_result.get("document_id"),
                    "knowledge_base_id": YICHANG_KNOWLEDGE_BASES["evidence"],
                    "evidence_ids": [item.get("evidence_id") for item in verified],
                    "execution_engine": a1.get("execution_engine") if a1 else "local",
                    "status_detail": a1.get("status") if a1 else "not_run",
                    "workflow_run_id": a1.get("workflow_run_id") if a1 else None,
                    "message_id": a1.get("message_id") if a1 else None,
                    "trace_id": a1.get("trace_id") if a1 else None,
                    "error": a1.get("error") if a1 else None,
                }
            except Exception as exc:
                a1_readback = {"status": "unavailable", "report_id": str(report_id),
                               "document_id": archive_result.get("document_id"),
                               "error": type(exc).__name__}
            archive_record_payload["a1_readback"] = a1_readback
            update_gold_record(archive_record["record_id"], archive_record_payload)
            report_payload["a1_readback"] = a1_readback
            report_payload["report_text"] = sync_report_markdown_status(report_payload) or report_payload.get("report_text")
            report_payload.setdefault("sections", {})["legacy_report_markdown"] = report_payload["report_text"]
            update_gold_record(str(report_id), report_payload)
            archive_result["a1_readback"] = a1_readback
        archive_result.update({
            "report_id": str(report_id), "event_id": event_id,
            "approval_id": approval["record_id"], "is_simulated": True,
            "gold_test_archive": True, "execution_engine": "geo-rag",
        })
        return archive_result

    if existing_archives:
        archived = next((item for item in reversed(existing_archives)
                         if item.get("status") == "archived_demo_local"), None)
        if not archived:
            raise HTTPException(status_code=409, detail="Gold report has an incomplete archive record")
        archive_payload = archived.get("payload") if isinstance(archived.get("payload"), dict) else {}
        if (
            archived.get("parent_id") != report_id
            or archived.get("scenario_id") != gold_record.get("scenario_id")
            or archived.get("is_simulated") is not True
            or archive_payload.get("report_id") != report_id
            or archive_payload.get("event_id") != event_id
            or archive_payload.get("is_simulated") is not True
            or archive_payload.get("execution_engine") != "local"
            or not archive_payload.get("document_id")
        ):
            raise HTTPException(status_code=409, detail="Gold report archive associations are not verified")
        if report["report_text"].strip() != str(report_payload.get("report_text") or "").strip():
            raise HTTPException(status_code=409, detail="An archived Gold report cannot be replaced")
        result = dict(archive_payload)
        result["idempotent"] = True
        try:
            readback = await answer_yichang_query(f"请按完整报告 ID {report_id} 回查 Gold 演示报告。", {})
            evidence = readback.get("evidence", []) if isinstance(readback, dict) else []
            matched = next((item for item in evidence if item.get("report_id") == report_id), None)
            result["a1_readback"] = {
                "status": "verified" if matched else "not_verified",
                "report_id": report_id,
                "evidence_id": matched.get("evidence_id") if matched else None,
            }
        except Exception as exc:
            result["a1_readback"] = {"status": "unavailable", "report_id": report_id,
                                      "error": type(exc).__name__}
        update_gold_record(archived["record_id"], {**archive_payload, "a1_readback": result["a1_readback"]})
        return result

    # Gold reports stay in the isolated local Gold store. They must not be mixed
    # into the production Yichang evidence knowledge base.
    draft_text = str(report_payload.get("report_text") or "")
    reviewed_text = report["report_text"].strip()
    if draft_text != reviewed_text:
        report_payload["draft_report_text"] = draft_text
    report_payload["report_text"] = reviewed_text
    reviewer_conclusion = report.get("reviewer_conclusion")
    if isinstance(reviewer_conclusion, str):
        report_payload["reviewer_conclusion"] = reviewer_conclusion
    reviewed_sections = report.get("sections")
    if isinstance(reviewed_sections, dict) and isinstance(reviewed_sections.get("review_conclusion"), str):
        sections = report_payload.get("sections")
        sections = dict(sections) if isinstance(sections, dict) else {}
        sections["review_conclusion"] = reviewed_sections["review_conclusion"]
        report_payload["sections"] = sections
    report_payload.update({
        "review_status": "approved",
        "approval_mode": "human_reviewer",
        "archive_status": "archived_demo_local",
        "status": "archived_demo_local",
        "reviewer_id": reviewer_id,
        "is_simulated": True,
        "execution_engine": "local",
    })
    existing_evidence = list_gold_children(str(report_id), "demo_evidence")
    if existing_evidence:
        evidence_record = existing_evidence[-1]
        evidence_id = evidence_record["record_id"]
        raise HTTPException(status_code=409, detail="Gold archive has evidence without a matching archive record")
    else:
        evidence_id = new_gold_id("evidence", gold_record["scenario_id"])
        evidence_record = save_gold_record(
            "demo_evidence", gold_record["scenario_id"],
            {
                "evidence_id": evidence_id,
                "report_id": str(report_id),
                "event_id": event_id,
                "file_name": f"demo-evidence:{report_id}",
                "report_text": report_payload["report_text"],
                "report": report_payload,
                "reviewer_id": reviewer_id,
                "approval_mode": "human_reviewer",
                "archive_status": "archived_demo_local",
                "is_simulated": True,
                "data_source": report_payload.get("data_source", "local_gold_report"),
                "execution_engine": "local",
            },
            record_id=evidence_id,
            parent_id=str(report_id),
        )
    update_gold_record(str(report_id), report_payload)
    archive_result = {
        "status": "archived_demo_local",
        "document_id": evidence_id,
        "report_id": str(report_id),
        "event_id": event_id,
        "is_simulated": True,
        "execution_engine": "local",
        "reviewer_id": reviewer_id,
        "file_name": evidence_record["payload"].get("file_name"),
    }
    approvals = list_gold_children(str(report_id), "approval")
    if not any(item.get("payload", {}).get("approval_type") == "report_and_archive" for item in approvals):
        save_gold_record(
            "approval", gold_record["scenario_id"],
            {"approval_type": "report_and_archive", "report_id": report_id, "event_id": event_id,
             "reviewer_id": reviewer_id,
             "trace_id": report_payload.get("trace_id"), "approval_mode": "human_reviewer",
             "approved": True, "is_simulated": True,
             "data_source": report_payload.get("data_source", "local_gold_report")},
            parent_id=str(report_id),
        )
    archives = list_gold_children(str(report_id), "archive")
    archive_record = None
    if not archives:
        archive_record = save_gold_record(
            "archive", gold_record["scenario_id"],
            {**archive_result, "data_source": report_payload.get("data_source", "local_gold_report")},
            parent_id=str(report_id),
        )
    try:
        readback = await answer_yichang_query(f"请按完整报告 ID {report_id} 回查 Gold 演示报告。", {})
        evidence = readback.get("evidence", []) if isinstance(readback, dict) else []
        matched = next((item for item in evidence if item.get("report_id") == report_id), None)
        archive_result["a1_readback"] = {
            "status": "verified" if matched else "not_verified",
            "report_id": report_id,
            "evidence_id": matched.get("evidence_id") if matched else None,
        }
    except Exception as exc:
        archive_result["a1_readback"] = {"status": "unavailable", "report_id": report_id,
                                         "error": type(exc).__name__}
    if archive_record:
        update_gold_record(archive_record["record_id"], {
            **archive_record["payload"], "a1_readback": archive_result["a1_readback"],
        })
    return archive_result


@app.post("/api/v1/yichang/tasks/confirm")
async def yichang_confirm_task(payload: dict = Body(...)):
    if payload.get("approved") is not True:
        raise HTTPException(status_code=400, detail="Human approval is required before Java task creation")
    task = payload.get("task")
    if not isinstance(task, dict):
        raise HTTPException(status_code=422, detail="A task payload is required")
    event_id = str(task.get("event_id") or "")
    if event_id.upper().startswith("DEMO-GOLD-EVENT-"):
        event_record = get_gold_record(event_id)
        if (event_record is None or event_record.get("record_type") != "event"
                or event_record.get("is_simulated") is not True
                or task.get("is_simulated") is not True):
            raise HTTPException(status_code=422, detail="A persisted simulated Gold event is required")
        reviewer_id = str(payload.get("reviewer_id") or "").strip()
        if not reviewer_id:
            raise HTTPException(status_code=422, detail="reviewer_id is required for Gold task approval")
        scenario_id = event_record["scenario_id"]
        existing_tasks = list_gold_records(scenario_id, "task")
        existing = next((item for item in existing_tasks
                         if item.get("payload", {}).get("event_id") == event_id), None)
        if scenario_id == "GOLD-03":
            existing = next((item for item in list_gold_records("GOLD-02", "task")
                             if item.get("payload", {}).get("last_event_id") == event_id), existing)
            if existing is None:
                raise HTTPException(status_code=409, detail="A prior GOLD-02 task is required for recovery review")
            task_payload = dict(existing["payload"])
            task_payload.update({"status": "recovery_review_confirmed", "last_event_id": event_id,
                                 "recovery_reviewer_id": reviewer_id,
                                 "is_simulated": True, "execution_engine": "local"})
            updated = update_gold_record(existing["record_id"], task_payload)
            save_gold_record(
                "approval", scenario_id,
                {"approval_type": "recovery_review", "event_id": event_id,
                 "task_id": existing["record_id"], "reviewer_id": reviewer_id,
                 "approved": True, "is_simulated": True, "execution_engine": "local"},
                parent_id=existing["record_id"],
            )
            return {"status": "recovery_review_confirmed", "task_id": existing["record_id"],
                    "event_id": event_id, "task": updated["payload"],
                    "execution_engine": "local", "is_simulated": True,
                    "formal_java_task_created": False}
        if existing is not None:
            return {"status": existing["status"], "task_id": existing["record_id"],
                    "event_id": event_id, "task": existing["payload"],
                    "execution_engine": "local", "is_simulated": True,
                    "formal_java_task_created": False}
        proposal_id = str(task.get("proposal_id") or "")
        proposal = get_gold_record(proposal_id) if proposal_id else None
        if (proposal is None or proposal.get("record_type") != "task_proposal"
                or proposal.get("parent_id") != event_id
                or proposal.get("payload", {}).get("event_id") != event_id):
            raise HTTPException(status_code=422, detail="A persisted Gold task proposal is required")
        proposal_action = proposal["payload"].get("action")
        submitted_action = task.get("action")
        if not isinstance(proposal_action, dict) or not isinstance(submitted_action, dict):
            raise HTTPException(status_code=422, detail="A reviewed Gold task action is required")
        reviewed_action = dict(proposal_action)
        for field in ("action", "location", "responsible_department", "person", "due_at", "completion_criteria"):
            value = submitted_action.get(field)
            if not isinstance(value, str) or not value.strip():
                raise HTTPException(status_code=422, detail=f"Reviewed task field '{field}' is required")
            value = value.strip()
            if field in {"responsible_department", "person", "due_at"} and value in {"待分配", "待安排", "未指定"}:
                raise HTTPException(status_code=422, detail=f"Reviewed task field '{field}' must be assigned")
            reviewed_action[field] = value
        try:
            due_at = datetime.fromisoformat(reviewed_action["due_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="due_at must be ISO 8601 with a timezone") from exc
        if due_at.utcoffset() is None:
            raise HTTPException(status_code=422, detail="due_at must include a timezone offset")
        decisions = list_gold_children(event_id, "decision")
        decision = next((item for item in decisions
                         if item.get("payload", {}).get("task_proposal_id") == proposal_id), None)
        if decision is None and len(decisions) == 1:
            decision = decisions[0]
        decision_id = proposal["payload"].get("decision_id") or (decision.get("record_id") if decision else None)
        if not decision_id:
            raise HTTPException(status_code=409, detail="The Gold proposal is not linked to a persisted A4 decision")
        task_id = new_gold_id("task", scenario_id)
        task_payload = {
            "task_id": task_id,
            "event_id": event_id,
            "proposal_id": proposal_id,
            "decision_id": decision_id,
            "trace_id": event_record["payload"].get("trace_id"),
            "dify_execution_ref": proposal["payload"].get("dify_execution_ref", {}),
            "scenario_id": scenario_id,
            "status": "demo_assigned",
            "action": reviewed_action,
            "slope_unit_id": event_record["payload"].get("slope_unit_id"),
            "task_source": "宜昌 GeoGuard Gold 隔离演示任务",
            "reviewer_id": reviewer_id,
            "approval_mode": "simulated_gold_test_harness",
            "is_simulated": True,
            "data_source": event_record["payload"].get("data_source", "local_gold_scenario"),
            "execution_engine": "local",
            "formal_java_task_created": False,
        }
        saved = save_gold_record("task", scenario_id, task_payload,
                                 record_id=task_id, parent_id=event_id)
        proposal_payload = dict(proposal["payload"])
        proposal_payload.update({"status": "approved_demo_assigned", "decision_id": decision_id, "task_id": task_id,
                                 "reviewer_id": reviewer_id, "approval_mode": "simulated_gold_test_harness",
                                 "reviewed_action": reviewed_action})
        update_gold_record(proposal_id, proposal_payload)
        save_gold_record(
            "approval", scenario_id,
            {"approval_type": "task", "event_id": event_id, "task_id": task_id,
             "reviewer_id": reviewer_id, "approved": True, "is_simulated": True,
             "approval_mode": "simulated_gold_test_harness", "execution_engine": "local"},
            parent_id=task_id,
        )
        return {"status": "demo_assigned", "task_id": task_id, "event_id": event_id,
                "task": saved["payload"], "execution_engine": "local",
                "is_simulated": True, "formal_java_task_created": False}
    if not task.get("unitId"):
        raise HTTPException(status_code=422, detail="A valid existing Java slope-unit unitId is required")
    if str(task["unitId"]).upper().startswith("GOLD-"):
        return {"status": "gold_test_object_not_valid_java_unit", "task_id": None}
    return await create_reviewed_task(task, human_approved=True)


@app.get("/api/v1/yichang/business/{record_type}/{record_id}")
async def yichang_business_record(record_type: str, record_id: str):
    if record_id.upper().startswith("DEMO-GOLD-"):
        record = get_gold_record(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Gold demo record was not found")
        return record
    return await lookup_business_record(record_type, record_id)


@app.get("/api/v1/yichang/tasks/{task_id}/feedback")
async def yichang_task_feedback(task_id: str):
    if task_id.upper().startswith("DEMO-GOLD-TASK-"):
        task = get_gold_record(task_id)
        if task is None or task["record_type"] != "task":
            raise HTTPException(status_code=404, detail="Gold demo task was not found")
        feedback = list_gold_children(task_id, "feedback")
        return {"status": "completed", "task_id": task_id, "feedback": feedback,
                "execution_engine": "local", "is_simulated": True}
    return await list_task_feedback(task_id)


@app.post("/api/v1/yichang/tasks/{task_id}/feedback")
async def yichang_submit_task_feedback(task_id: str, payload: dict = Body(...)):
    if payload.get("approved") is not True:
        raise HTTPException(status_code=400, detail="Human approval is required before Java feedback submission")
    feedback = payload.get("feedback")
    if not isinstance(feedback, dict):
        raise HTTPException(status_code=422, detail="Java task feedback fields are required")
    if task_id.upper().startswith("DEMO-GOLD-TASK-"):
        task = get_gold_record(task_id)
        if task is None or task["record_type"] != "task":
            raise HTTPException(status_code=404, detail="Gold demo task was not found")
        reviewer_id = str(payload.get("reviewer_id") or "").strip()
        if not reviewer_id:
            raise HTTPException(status_code=422, detail="reviewer_id is required for Gold feedback")
        event_id = task["payload"].get("event_id")
        feedback_event_id = str(feedback.get("event_id") or task["payload"].get("last_event_id") or event_id)
        event_record = get_gold_record(feedback_event_id)
        if (event_record is None or event_record.get("record_type") != "event"
                or feedback_event_id not in {event_id, task["payload"].get("last_event_id")}):
            raise HTTPException(status_code=422, detail="Feedback must reference the linked Gold event")
        feedback_id = new_gold_id("feedback", event_record["scenario_id"])
        saved = save_gold_record(
            "feedback", event_record["scenario_id"],
            {**feedback, "feedback_id": feedback_id,
             "task_id": task_id, "event_id": feedback_event_id, "status": "persisted_local_demo_feedback",
             "proposal_id": task["payload"].get("proposal_id"),
             "decision_id": task["payload"].get("decision_id"),
             "dify_execution_ref": task["payload"].get("dify_execution_ref", {}),
             "is_simulated": True, "data_source": feedback.get("data_source", "local_gold_feedback_endpoint"),
             "execution_engine": "local", "approval_mode": "simulated_gold_test_harness",
             "reviewer_id": reviewer_id},
            record_id=feedback_id, parent_id=task_id,
        )
        task_payload = dict(task["payload"])
        task_payload["status"] = "recovery_verified" if feedback_event_id != event_id else "demo_feedback_received"
        task_payload["last_feedback_id"] = saved["record_id"]
        update_gold_record(task_id, task_payload)
        return {"status": "saved", "task_id": task_id, "feedback": saved,
                "task_status": task_payload["status"], "execution_engine": "local", "is_simulated": True}
    return await submit_reviewed_task_feedback(task_id, feedback, human_approved=True)


def initial_state(req: RunRequest):
    return {
        "query": req.query,
        "workflow": req.workflow,
        "hazard_input": req.hazard_input,
        "context": req.context,
        "business_context": {},
        "candidate_match": {},
        "comparison": [],
        "field_verification": [],
        "missing_fields": [],
        "evidence": [],
        "more_evidence_attempted": False,
        "needs_more_evidence": False,
        "risk_classification": {},
        "result": {},
        "trace": [],
    }


def response_from(final: dict, workflow: str) -> RunResponse:
    return RunResponse(
        workflow=workflow,
        structured_result=final.get("result", {}),
        evidence=final.get("evidence", []),
        trace=final.get("trace", []),
    )


@app.post("/api/v1/run", response_model=RunResponse)
async def run(req: RunRequest):
    final = await COMPILED_GRAPHS[req.workflow].ainvoke(initial_state(req))
    return response_from(final, req.workflow)


@app.post("/api/v1/run/stream")
async def run_stream(req: RunRequest):
    async def events():
        final = {}
        node_titles = {node["id"]: node["title"] for node in WORKFLOW_DEFINITIONS[req.workflow]["nodes"]}
        try:
            async for event in COMPILED_GRAPHS[req.workflow].astream_events(initial_state(req), version="v2"):
                node_id = event.get("metadata", {}).get("langgraph_node")
                if node_id not in node_titles or event.get("name") != node_id:
                    continue
                if event.get("event") == "on_chain_start":
                    payload = {"stage": node_id, "node_id": node_id, "status": "running",
                               "summary": f"正在执行：{node_titles[node_id]}", "data": {}}
                    yield f"event: trace\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                elif event.get("event") == "on_chain_end":
                    node_update = event.get("data", {}).get("output")
                    if not isinstance(node_update, dict):
                        continue
                    final.update(node_update)
                    traces = node_update.get("trace", [])
                    trace = traces[-1] if traces else {
                        "stage": node_id, "status": "completed", "summary": f"节点 {node_id} 完成", "data": {}
                    }
                    payload = {**trace, "node_id": node_id}
                    yield f"event: trace\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            result = response_from(final, req.workflow).model_dump()
            yield f"event: result\ndata: {json.dumps(result, ensure_ascii=False)}\n\n"
            yield "event: done\ndata: {}\n\n"
        except Exception as exc:
            logger.exception("LangGraph streaming execution failed")
            payload = {"error": "graph_execution_failed", "detail": type(exc).__name__}
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
