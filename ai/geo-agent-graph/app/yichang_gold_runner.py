"""Runtime execution of the v1.1 two-event Yichang Gold fixtures."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .config import settings
from .dify_adapters.a3_monitor import process_monitoring_with_dify
from .dify_adapters.a5_report import generate_report_from_facts
from .rag_archive import _docx_bytes, _gold_photo_attachments
from .rag_client import retrieve_yichang
from .yichang_decision import process_decision
from .yichang_field import process_field_report
from .yichang_report import sync_report_markdown_status
from .yichang_store import (
    get_gold_record,
    list_gold_records,
    new_gold_id,
    save_gold_record,
    update_gold_record,
)


_EVENT_DIRS = {
    "GOLD-01": "GOLD-01-WF",
    "GOLD-02": "GOLD-02-03-ZG",
}


def _fixture_root() -> Path:
    return Path(settings.yichang_scenario_fixture_dir).expanduser().resolve()


def _read_json(folder: Path, relative_path: str) -> Any:
    path = (folder / relative_path).resolve()
    if folder.resolve() not in path.parents:
        raise ValueError("Gold fixture path escaped its event directory")
    return json.loads(path.read_text(encoding="utf-8"))


def _folder(scenario_id: str) -> Path:
    directory = _EVENT_DIRS.get(scenario_id)
    if directory is None:
        raise ValueError("scenario_id must be GOLD-01 or GOLD-02; run GOLD-03 as a stage of GOLD-02")
    folder = _fixture_root() / "events" / directory
    if not folder.is_dir():
        raise ValueError(f"v1.1 Gold fixture directory is unavailable: {folder}")
    return folder


def _risk_fixture(folder: Path, scenario_id: str) -> dict[str, Any]:
    path = folder / "risk_snapshot.json"
    if not path.is_file() and scenario_id == "GOLD-02":
        path = folder / "stages" / "GOLD-02" / "risk_snapshot_reference.json"
    if not path.is_file():
        raise ValueError(f"P6 reference fixture is unavailable for {scenario_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _relationship(event_fixture_id: str) -> dict[str, Any]:
    path = _fixture_root() / "relationships.json"
    if not path.is_file():
        return {}
    relationships = json.loads(path.read_text(encoding="utf-8"))
    return next((item for item in relationships.get("events", [])
                 if item.get("fixture_event_id") == event_fixture_id), {})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_run(run_id: str) -> dict[str, Any]:
    record = get_gold_record(run_id)
    if not record or record.get("record_type") != "gold_run":
        raise ValueError("Gold run was not found")
    return record["payload"]


def _save_run(run: Mapping[str, Any]) -> dict[str, Any]:
    return update_gold_record(str(run["run_id"]), dict(run)) or {}


def _load_event(run: Mapping[str, Any]) -> dict[str, Any]:
    record = get_gold_record(str(run["runtime_event_id"]))
    if not record or record.get("record_type") != "event":
        raise ValueError("Gold run event was not found")
    return record["payload"]


def _save_event(event: Mapping[str, Any]) -> dict[str, Any]:
    record_id = str(event["event_id"])
    return update_gold_record(record_id, dict(event)) or {}


def _records(run: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        record for record in list_gold_records(str(run["scenario_id"]))
        if record.get("payload", {}).get("run_id") == run.get("run_id")
    ]


def _mapping(run: dict[str, Any]) -> dict[str, Any]:
    value = run.get("fixture_to_runtime")
    if not isinstance(value, dict):
        value = {"event": {}, "discoveries": {}, "alarms": {}, "devices": {}, "investigations": {}, "decisions": {},
                 "proposals": {}, "approvals": {}, "tasks": {}, "feedbacks": {},
                 "task_reviews": {}, "reports": {}, "monitoring_stages": {}}
        run["fixture_to_runtime"] = value
    for key in ("event", "discoveries", "alarms", "devices", "investigations", "decisions", "proposals", "approvals",
                "tasks", "feedbacks", "task_reviews", "reports", "monitoring_stages", "dify_executions"):
        value.setdefault(key, {})
    return value


def read_dual_gold_run(run_id: str) -> dict[str, Any]:
    run = _load_run(run_id)
    records = _records(run)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record["record_type"], []).append(record)
    return {
        "run": run,
        "event": get_gold_record(str(run["runtime_event_id"])),
        "records": grouped,
        "fixture_to_runtime": run.get("fixture_to_runtime", {}),
        "execution_engine": "local",
        "is_simulated": True,
    }


def _timeline(event: dict[str, Any], stage: str, business_time: str | None, **refs: Any) -> None:
    event.setdefault("timeline", []).append({
        "stage": stage,
        "business_time": business_time,
        "executed_at": _now(),
        "status": "persisted",
        **refs,
    })


def _persist_report_docx(report: dict[str, Any]) -> dict[str, Any]:
    report_id = str(report.get("report_id") or "")
    report_text = report.get("report_text")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", report_id) or not isinstance(report_text, str) or not report_text.strip():
        raise ValueError("A persisted report ID and non-empty Markdown body are required for DOCX export")
    database = Path(settings.yichang_scenario_db_path).expanduser()
    if not database.is_absolute():
        database = Path.cwd() / database
    report_dir = database.resolve().parent / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{report_id}.docx"
    report_path = report_dir / file_name
    report_path.write_bytes(_docx_bytes(report_text, _gold_photo_attachments(report)))
    report["docx_status"] = "generated"
    report["docx_file_name"] = file_name
    report["docx_url"] = f"/api/v1/yichang/gold-runs/{report.get('run_id')}/reports/{report_id}/docx"
    return report


def _fixture_mapping(event_fixture: Mapping[str, Any], risk_fixture: Mapping[str, Any]) -> dict[str, Any]:
    candidate = risk_fixture.get("p6_candidate") if isinstance(risk_fixture.get("p6_candidate"), Mapping) else {}
    slope_id = candidate.get("slope_unit_id")
    if not slope_id:
        raise ValueError("Gold fixture has no P6 candidate slope_unit_id")
    return {
        "p6_slope_unit_id": slope_id,
        "mapping_status": candidate.get("mapping_status", "candidate_unverified"),
        "mapping_scope": candidate.get("mapping_scope", "gold_demo_query_only"),
        "source": candidate.get(
            "mapping_source",
            "Gold fixture candidate mapping; spatial match remains unverified",
        ),
        "coordinate_crs_status": candidate.get("coordinate_crs_status"),
        "snapshot_id_reference": candidate.get("snapshot_id"),
        "expert_approval_evidenced": False,
        "official_warning_allowed": False,
    }


async def start_dual_gold_run(scenario_id: str, *, run_id: str | None = None) -> dict[str, Any]:
    folder = _folder(scenario_id)
    if run_id:
        existing = get_gold_record(run_id)
        if existing and existing.get("record_type") == "gold_run":
            if existing["payload"].get("fixture_event_id") != _read_json(folder, "event.json").get("event_id"):
                raise ValueError("run_id belongs to a different Gold fixture")
            return read_dual_gold_run(run_id)
        raise ValueError("run_id can only resume an existing Gold run")

    event_fixture = _read_json(folder, "event.json")
    discovery_fixture = _read_json(folder, "discovery.json")
    investigation_fixture = _read_json(folder, "investigation.json")
    risk_fixture = _risk_fixture(folder, scenario_id)
    relationship = _relationship(str(event_fixture["event_id"]))
    decision_fixture = _read_json(folder, "decision_and_disposal.json")
    task_fixtures = _read_json(folder, "tasks.json")
    if not isinstance(task_fixtures, list) or len(task_fixtures) != 4:
        raise ValueError("v1.1 fixture must contain exactly four task proposals")

    canonical_scenario = scenario_id
    runtime_run_id = new_gold_id("run", canonical_scenario)
    event_id = new_gold_id("event", canonical_scenario)
    trace_id = new_gold_id("trace", canonical_scenario)
    mapping = {
        "event": {event_fixture["event_id"]: event_id},
        "discoveries": {}, "alarms": {}, "devices": {}, "investigations": {}, "decisions": {}, "proposals": {},
        "approvals": {}, "tasks": {}, "feedbacks": {}, "task_reviews": {},
        "reports": {}, "monitoring_stages": {}, "dify_executions": {},
    }
    run = {
        "run_id": runtime_run_id,
        "scenario_id": canonical_scenario,
        "scenario_ids": event_fixture.get("scenario_ids", [scenario_id]),
        "fixture_event_id": event_fixture["event_id"],
        "runtime_event_id": event_id,
        "trace_id": trace_id,
        "fixture_version": "1.1.0",
        "fixture_report_keys": relationship.get("report_fixture_keys", []),
        "status": "running",
        "phase": "discovery_and_assessment",
        "fixture_to_runtime": mapping,
        "is_simulated": True,
        "execution_engine": "local",
        "created_at": _now(),
    }
    save_gold_record("gold_run", canonical_scenario, run, record_id=runtime_run_id)

    try:
        p6_mapping = _fixture_mapping(event_fixture, risk_fixture)
        if scenario_id == "GOLD-01":
            photo_refs = investigation_fixture.get("photo_refs") or discovery_fixture.get("image_refs") or []
            field_result = await process_field_report({
                "event_id": event_id,
                "text": discovery_fixture.get("narrative"),
                "admin_area": investigation_fixture.get("location", {}).get("admin_area"),
                "visit_time": discovery_fixture.get("discovery_time"),
                "occurred_at": event_fixture.get("event_time"),
                "hazard_point_id": event_fixture.get("hazard_point", {}).get("id"),
                "slope_unit_id": investigation_fixture.get("location", {}).get("local_gold_slope_unit_id"),
                "p6_mapping": p6_mapping,
                "spatial_ref_status": "candidate_unverified",
                "spatial_object_source": "v1.1 Gold fixture; synthetic display location",
                "photo_refs": photo_refs,
                "is_simulated": True,
                "data_source": discovery_fixture.get("data_source"),
                "correlation_id": trace_id,
            }, execute_dify=False, execute_llm=False)
            event = dict(field_result)
            event.update({
                "event_type": event_fixture.get("event_type"),
                "source_event_id": event_fixture["event_id"],
                "fixture_event_id": event_fixture["event_id"],
                "field_investigation_record": {
                    **(field_result.get("field_investigation_record") or {}),
                    "gold_fixture_record": investigation_fixture,
                },
            })
            a2_record_id = new_gold_id("field-report", canonical_scenario)
            save_gold_record("field_report", canonical_scenario, {
                **field_result, "record_id": a2_record_id, "run_id": runtime_run_id,
                "event_id": event_id, "trace_id": trace_id,
                "fixture_discovery_id": discovery_fixture.get("discovery_id"),
                "is_simulated": True,
            }, record_id=a2_record_id, parent_id=event_id)
            mapping["discoveries"][discovery_fixture["discovery_id"]] = new_gold_id("discovery", canonical_scenario)
            save_gold_record("discovery", canonical_scenario, {
                **discovery_fixture, "discovery_id": mapping["discoveries"][discovery_fixture["discovery_id"]],
                "fixture_discovery_id": discovery_fixture["discovery_id"], "event_id": event_id,
                "run_id": runtime_run_id, "trace_id": trace_id, "is_simulated": True,
            }, record_id=mapping["discoveries"][discovery_fixture["discovery_id"]], parent_id=event_id)
            data_source = discovery_fixture.get("data_source")
            monitoring_result = None
        else:
            stage_input = _read_json(folder, "stages/GOLD-02/alarm_and_field.json")
            stage_input.pop("p6_snapshot_id", None)
            stage_input.update({"event_id": event_id, "correlation_id": trace_id, "p6_mapping": p6_mapping})
            monitoring_result = await process_monitoring_with_dify(stage_input, execute_dify=False)
            event = dict(monitoring_result.get("event") or {})
            event.update({
                "source_event_id": event_fixture["event_id"], "fixture_event_id": event_fixture["event_id"],
                "hazard_point_id": event_fixture.get("hazard_point", {}).get("id")
                or stage_input.get("hazard_point_id"),
                "spatial_display": event_fixture.get("spatial_display"),
                "device": stage_input.get("monitoring_device"),
                "monitoring_series_id": stage_input.get("monitoring_series_id"),
                "p6_mapping": p6_mapping,
            })
            data_source = stage_input.get("data_source")
            alarm_id = stage_input.get("alarm_id")
            alarm_id = alarm_id or event_fixture.get("alarm_id") or discovery_fixture.get("alarm_id")
            alarm_runtime_id = new_gold_id("alarm", canonical_scenario)
            mapping["alarms"][str(alarm_id)] = alarm_runtime_id
            assets = _read_json(folder, "assets.json")
            fixture_device_id = str(assets.get("device_id") or stage_input.get("monitoring_device", {}).get("device_id"))
            device_runtime_id = new_gold_id("device", canonical_scenario)
            mapping["devices"][fixture_device_id] = device_runtime_id
            mapping["discoveries"][discovery_fixture["discovery_id"]] = new_gold_id("discovery", canonical_scenario)
            for record_type, payload, record_id in (
                ("discovery", {**discovery_fixture, "fixture_discovery_id": discovery_fixture["discovery_id"],
                                "event_id": event_id, "run_id": runtime_run_id, "trace_id": trace_id,
                                "is_simulated": True}, mapping["discoveries"][discovery_fixture["discovery_id"]]),
                ("alarm", {"alarm_id": alarm_runtime_id, "fixture_alarm_id": alarm_id,
                           "event_id": event_id, "run_id": runtime_run_id, "trace_id": trace_id,
                           "source": stage_input.get("data_source"), "is_simulated": True}, alarm_runtime_id),
                ("device", {**assets, "device_id": device_runtime_id, "fixture_device_id": fixture_device_id,
                            "event_id": event_id, "run_id": runtime_run_id, "trace_id": trace_id,
                            "is_simulated": True}, device_runtime_id),
            ):
                save_gold_record(record_type, canonical_scenario, payload, record_id=record_id, parent_id=event_id)
            monitoring_id = new_gold_id("monitoring", canonical_scenario)
            mapping["monitoring_stages"]["GOLD-02"] = monitoring_id
            save_gold_record("monitoring_assessment", canonical_scenario, {
                **monitoring_result, "record_id": monitoring_id, "run_id": runtime_run_id,
                "event_id": event_id, "trace_id": trace_id, "stage_id": "GOLD-02",
                "is_simulated": True,
            }, record_id=monitoring_id, parent_id=event_id)
            data_source = stage_input.get("data_source")
            event["discovery_id"] = mapping["discoveries"][discovery_fixture["discovery_id"]]
            event["alarm_id"] = alarm_runtime_id
            event["device_id"] = device_runtime_id
            event["p6_snapshot"] = monitoring_result.get("p6_snapshot")
            event["p6_dynamic_snapshot"] = monitoring_result.get("p6_dynamic_snapshot")

        investigation_id = new_gold_id("investigation", canonical_scenario)
        mapping["investigations"][investigation_fixture["investigation_record_id"]] = investigation_id
        save_gold_record("investigation", canonical_scenario, {
            **investigation_fixture, "investigation_id": investigation_id,
            "fixture_investigation_id": investigation_fixture["investigation_record_id"],
            "event_id": event_id, "run_id": runtime_run_id, "trace_id": trace_id,
            "is_simulated": True,
        }, record_id=investigation_id, parent_id=event_id)

        event.update({
            "event_id": event_id, "run_id": runtime_run_id, "trace_id": trace_id,
            "scenario_id": canonical_scenario, "scenario_ids": run["scenario_ids"],
            "discovery_id": mapping["discoveries"][discovery_fixture["discovery_id"]],
            "fixture_event_id": event_fixture["event_id"], "event_status": "awaiting_plan_review",
            "status": "awaiting_plan_review", "is_simulated": True,
            "data_source": data_source or "v1.1_gold_fixture",
            "p6_mapping": p6_mapping,
            "p6_fixture_reference": risk_fixture.get("p6_candidate"),
            "hazard_cancelled": False,
            "archive_required_for_event_completion": False,
            "timeline": [],
        })
        _timeline(event, "discovered", discovery_fixture.get("discovery_time"),
                  discovery_id=mapping["discoveries"][discovery_fixture["discovery_id"]])
        _timeline(event, "investigated", investigation_fixture.get("investigation_time", {}).get("end"),
                  investigation_id=investigation_id)
        event_record = save_gold_record("event", canonical_scenario, event, record_id=event_id,
                                        parent_id=runtime_run_id)

        query = " ".join(str(value) for value in (
            event.get("admin_area"), event.get("hazard_point_id"), event.get("summary"),
            event.get("event_type"),
        ) if value)
        rag_status = "deferred_to_phase2"
        rag_error = None
        evidence: list[dict[str, Any]] = []
        rag_id = new_gold_id("rag-retrieval", canonical_scenario)
        save_gold_record("rag_retrieval", canonical_scenario, {
            "record_id": rag_id, "run_id": runtime_run_id, "event_id": event_id,
            "trace_id": trace_id, "query": query, "status": rag_status,
            "evidence": evidence, "evidence_count": len(evidence), "error": rag_error,
            "execution_engine": "not_run", "is_simulated": True,
            "data_source": "Geo-RAG deferred to Phase 2; Gold event facts remain simulated",
        }, record_id=rag_id, parent_id=event_id)

        decision_result = await process_decision(event, evidence, execute_dify=False)
        decision_id = new_gold_id("decision", canonical_scenario)
        decision = {
            **decision_result, "decision_id": decision_id, "run_id": runtime_run_id,
            "event_id": event_id, "trace_id": trace_id, "scenario_id": canonical_scenario,
            "decision_status": "awaiting_plan_review", "is_simulated": True,
            "execution_engine": "local", "source_kind": "gold_phase1_adapter",
            "rag_status": rag_status,
        }
        save_gold_record("decision", canonical_scenario, decision, record_id=decision_id, parent_id=event_id)
        mapping["decisions"][decision_fixture.get("decision_fixture_key", "decision")] = decision_id
        proposals_by_key = {item.get("task_fixture_key"): item for item in decision_fixture.get("proposals", [])}
        for task_fixture in task_fixtures:
            task_key = task_fixture.get("task_fixture_key")
            proposal_fixture = proposals_by_key.get(task_key)
            if not isinstance(proposal_fixture, Mapping):
                raise ValueError(f"decision fixture is missing task proposal {task_key}")
            proposal_id = new_gold_id("proposal", canonical_scenario)
            proposal_key = str(task_fixture.get("proposal_fixture_key") or proposal_fixture.get("proposal_fixture_key"))
            action = {
                "action": task_fixture.get("task_content"), "action_type": task_fixture.get("action_type"),
                "title": task_fixture.get("title"), "location": task_fixture.get("target_location"),
                "responsible_department": task_fixture.get("department"),
                "person": task_fixture.get("responsible_person"),
                "co_responsible_persons": task_fixture.get("co_responsible_persons", []),
                "due_at": task_fixture.get("deadline"), "resources": task_fixture.get("resources"),
                "completion_criteria": task_fixture.get("acceptance_criteria"),
                "measure_categories": task_fixture.get("measure_categories", []),
            }
            proposal = {
                "proposal_id": proposal_id, "fixture_proposal_key": proposal_key,
                "task_fixture_key": task_key, "event_id": event_id, "decision_id": decision_id,
                "run_id": runtime_run_id, "trace_id": trace_id, "status": "pending_plan_review",
                "action": action, "is_simulated": True, "execution_engine": "local",
                "proposal_source": "v1.1 Gold fixture mapped to the local A4 decision; awaiting Phase 2 Dify output",
                "data_source": data_source,
            }
            save_gold_record("task_proposal", canonical_scenario, proposal,
                             record_id=proposal_id, parent_id=event_id)
            mapping["proposals"][str(proposal_key)] = proposal_id
            mapping["proposals"][str(task_key)] = proposal_id

        _timeline(event, "p6_and_a4_assessed", event_fixture.get("event_time"),
                  decision_id=decision_id, p6_status=(decision.get("p6_snapshot") or {}).get("status"))
        _save_event(event)

        report = await _generate_a5_report(run, event, investigation_fixture, decision, [], "investigation")
        investigation_report_key = next((key for key in run.get("fixture_report_keys", [])
                                         if "INVESTIGATION" in key), f"{event_fixture['event_id']}:REPORT:INVESTIGATION")
        mapping["reports"][investigation_report_key] = report["report_id"]
        run.update({"phase": "awaiting_plan_review", "status": "awaiting_plan_review",
                    "rag_status": rag_status, "started_at": _now(), "error": None})
        _save_run(run)
        return read_dual_gold_run(runtime_run_id)
    except Exception as exc:
        run.update({"phase": "discovery_and_assessment", "status": "failed",
                    "error": f"{type(exc).__name__}: {str(exc)[:240]}", "failed_at": _now()})
        _save_run(run)
        raise


async def execute_gold_a4(run_id: str) -> dict[str, Any]:
    """Run A4 against persisted Gold facts and retain its actual Dify and RAG traces."""
    run = _load_run(run_id)
    mapping = _mapping(run)
    prior_a4_executions = [item for item in _records(run)
                           if item["record_type"] == "dify_execution"
                           and item["payload"].get("agent_id") == "A4"]
    existing_id = mapping["dify_executions"].get("A4")
    existing = get_gold_record(existing_id) if existing_id else (prior_a4_executions[-1] if prior_a4_executions else None)
    if existing and (existing["payload"].get("status") != "error" or len(prior_a4_executions) >= 3):
        if not existing_id:
            mapping["dify_executions"]["A4"] = existing["record_id"]
            _save_run(run)
        return read_dual_gold_run(run_id)

    event = _load_event(run)
    decision_record = next((item for item in _records(run) if item["record_type"] == "decision"), None)
    if decision_record is None:
        raise ValueError("A persisted local A4 decision is required before the Dify execution")
    local_decision = decision_record["payload"]
    event = {
        **event,
        "p6_snapshot": local_decision.get("p6_snapshot"),
        "p6_dynamic_snapshot": local_decision.get("p6_dynamic_snapshot"),
        "p6_exposure": local_decision.get("p6_exposure"),
    }
    query = " ".join(str(value) for value in (
        event.get("admin_area"), event.get("hazard_point_id"), event.get("summary"), event.get("event_type"),
    ) if value).strip()
    rag_status = "completed"
    rag_error = None
    try:
        retrieval = await retrieve_yichang(query or "宜昌地质灾害调查处置依据", top_k=8)
        evidence = retrieval.get("evidences", []) if isinstance(retrieval, Mapping) else []
        if not isinstance(evidence, list):
            evidence = []
    except Exception as exc:
        evidence = []
        rag_status = f"unavailable:{type(exc).__name__}"
        rag_error = str(exc)[:240]

    rag_record = next((item for item in _records(run) if item["record_type"] == "rag_retrieval"), None)
    rag_id = rag_record["record_id"] if rag_record else new_gold_id("rag-retrieval", str(run["scenario_id"]))
    rag_payload = {
        "record_id": rag_id, "run_id": run_id, "event_id": event["event_id"],
        "trace_id": run["trace_id"], "query": query, "status": rag_status,
        "evidence": evidence,
        "evidence_ids": [item.get("evidence_id") for item in evidence if item.get("evidence_id")],
        "evidence_count": len(evidence), "error": rag_error, "execution_engine": "geo-rag",
        "data_source": "geo_rag 宜昌知识库检索；演示事件记录",
        "is_simulated": True,
    }
    if rag_record:
        update_gold_record(rag_id, rag_payload)
    else:
        save_gold_record("rag_retrieval", str(run["scenario_id"]), rag_payload,
                         record_id=rag_id, parent_id=str(event["event_id"]))

    result = await process_decision(event, evidence, execute_dify=True)
    execution = result.get("a4_execution") if isinstance(result.get("a4_execution"), Mapping) else {}
    execution_id = new_gold_id("dify-execution", str(run["scenario_id"]))
    execution_payload = {
        "record_id": execution_id, "agent_id": "A4", "event_id": event["event_id"],
        "attempt": len(prior_a4_executions) + 1,
        "run_id": run_id, "trace_id": run["trace_id"], "execution_engine": execution.get("execution_engine"),
        "status": execution.get("status"), "configured": execution.get("configured"),
        "rag_record_id": rag_id, "rag_status": rag_status,
        "recommendation_engine": result.get("recommendation_engine"),
        "llm_status": result.get("llm_status"), "a4_review": result.get("a4_review"),
        "disposal_plan": result.get("disposal_plan"), "task_proposal": result.get("task_proposal"),
        "workflows": execution.get("workflows", {}),
        "output_status": {
            role: item.get("output_status")
            for role, item in (execution.get("workflows", {}) or {}).items()
            if isinstance(item, Mapping)
        },
        "is_simulated": True,
        "data_source": "persisted Gold business facts; external Geo-RAG and Dify execution",
    }
    save_gold_record("dify_execution", str(run["scenario_id"]), execution_payload,
                     record_id=execution_id, parent_id=str(event["event_id"]))
    mapping["dify_executions"]["A4"] = execution_id
    decision_payload = dict(local_decision)
    decision_payload.update({
        "dify_execution_id": execution_id, "dify_status": execution.get("status"),
        "dify_output_status": execution_payload["output_status"],
        "dify_recommendation_engine": result.get("recommendation_engine"),
        "dify_a4_review": result.get("a4_review"),
        "dify_disposal_plan": result.get("disposal_plan"),
        "dify_task_proposal": result.get("task_proposal"),
        "rag_record_id": rag_id, "rag_status": rag_status,
    })
    update_gold_record(decision_record["record_id"], decision_payload)
    event["a4_dify_execution_id"] = execution_id
    event["rag_status"] = rag_status
    _timeline(event, "a4_dify_execution_persisted", None, execution_id=execution_id,
              status=execution.get("status"), output_status=execution_payload["output_status"])
    _save_event(event)
    run.update({"a4_execution_id": execution_id, "a4_status": execution.get("status"),
                "a4_output_status": execution_payload["output_status"], "rag_status": rag_status})
    _save_run(run)
    return read_dual_gold_run(run_id)


async def execute_gold_a2(run_id: str) -> dict[str, Any]:
    """Replay the persisted GOLD-01 field report and synthetic photo through A2."""
    run = _load_run(run_id)
    if run.get("scenario_id") != "GOLD-01":
        raise ValueError("A2 Gold image execution is available for GOLD-01 only")
    mapping = _mapping(run)
    existing_id = mapping["dify_executions"].get("A2")
    if existing_id and get_gold_record(existing_id):
        return read_dual_gold_run(run_id)

    event = _load_event(run)
    folder = _folder("GOLD-01")
    discovery = _read_json(folder, "discovery.json")
    investigation = _read_json(folder, "investigation.json")
    photo_refs = investigation.get("photo_refs") or discovery.get("image_refs") or []
    if not isinstance(photo_refs, list) or not photo_refs:
        raise ValueError("GOLD-01 must contain a synthetic photo reference")

    # Fixture refs use the repository's tests/gold/yichang assets. Keep this
    # mapping explicit so an arbitrary fixture path cannot be read by the API.
    service_root = Path(__file__).resolve().parents[1]
    photo_uploads = []
    for index, reference in enumerate(photo_refs):
        ref_path = str(reference.get("path")) if isinstance(reference, Mapping) else str(reference)
        parts = Path(ref_path.replace("\\", "/")).parts
        if len(parts) < 6 or parts[:4] != ("fixtures", "tests", "gold", "yichang"):
            raise ValueError(f"Unsupported Gold photo reference: {ref_path}")
        image_path = (service_root / "tests" / "gold" / "yichang" / Path(*parts[4:])).resolve()
        allowed_root = (service_root / "tests" / "gold" / "yichang" / "assets").resolve()
        if allowed_root not in image_path.parents or not image_path.is_file():
            raise ValueError(f"Gold synthetic photo is unavailable: {ref_path}")
        content = image_path.read_bytes()
        photo_uploads.append({
            "index": index,
            "reference": reference,
            "filename": image_path.name,
            "mime_type": "image/png",
            "content": content,
        })

    field_data = {
        "event_id": event["event_id"],
        "text": discovery.get("narrative"),
        "admin_area": investigation.get("location", {}).get("admin_area"),
        "visit_time": discovery.get("discovery_time"),
        "occurred_at": event.get("event_time"),
        "hazard_point_id": investigation.get("location", {}).get("hazard_point_id"),
        "slope_unit_id": investigation.get("location", {}).get("local_gold_slope_unit_id"),
        "p6_mapping": event.get("p6_mapping"),
        "spatial_ref_status": "candidate_unverified",
        "spatial_object_source": "v1.1 Gold fixture; synthetic display location",
        "photo_refs": photo_refs,
        "photo_uploads": photo_uploads,
        "is_simulated": True,
        "data_source": discovery.get("data_source"),
        "correlation_id": run["trace_id"],
    }
    result = await process_field_report(field_data, execute_dify=True, execute_llm=False)
    vision = result.get("vision_execution") if isinstance(result.get("vision_execution"), Mapping) else {}
    field_record = next((item for item in _records(run) if item["record_type"] == "field_report"), None)
    field_payload = dict(field_record["payload"]) if field_record else {}
    result_record = {
        **field_payload,
        **result,
        "record_id": field_record["record_id"] if field_record else new_gold_id("field-report", "GOLD-01"),
        "run_id": run_id,
        "event_id": event["event_id"],
        "trace_id": run["trace_id"],
        "fixture_discovery_id": discovery.get("discovery_id"),
        "field_investigation_record": {
            **(result.get("field_investigation_record") or {}),
            "gold_fixture_record": investigation,
        },
        "is_simulated": True,
    }
    if field_record:
        update_gold_record(field_record["record_id"], result_record)
    else:
        save_gold_record("field_report", "GOLD-01", result_record,
                         record_id=result_record["record_id"], parent_id=str(event["event_id"]))

    execution_id = new_gold_id("agent-execution", "GOLD-01")
    execution_payload = {
        "record_id": execution_id, "agent_id": "A2", "event_id": event["event_id"],
        "run_id": run_id, "trace_id": run["trace_id"],
        "execution_engine": vision.get("execution_engine", "local"),
        "status": vision.get("status", "not_run"),
        "output_status": vision.get("output_verification_status") or vision.get("analysis_status"),
        "dify_app": "GEO识图-多图汇总", "app_mode": "advanced-chat",
        "uploaded_file_ids": vision.get("uploaded_file_ids", []),
        "workflow_run_id": vision.get("workflow_run_id"),
        "task_id": vision.get("task_id"), "message_id": vision.get("message_id"),
        "conversation_id": vision.get("conversation_id"),
        "image_input_contract_status": vision.get("status") if vision.get("execution_engine") == "local" else "enabled",
        "raw_outputs": vision.get("outputs"), "error": vision.get("error"),
        "data_source": "GOLD-01 synthetic image and persisted field report",
        "is_simulated": True,
    }
    save_gold_record("dify_execution", "GOLD-01", execution_payload,
                     record_id=execution_id, parent_id=str(event["event_id"]))
    mapping["dify_executions"]["A2"] = execution_id
    event["a2_execution_id"] = execution_id
    _timeline(event, "a2_image_analysis_attempted", discovery.get("discovery_time"),
              execution_id=execution_id, status=execution_payload["status"],
              execution_engine=execution_payload["execution_engine"])
    _save_event(event)
    run["a2_status"] = execution_payload["status"]
    _save_run(run)
    return read_dual_gold_run(run_id)


async def execute_gold_a3(run_id: str, stage_id: str) -> dict[str, Any]:
    """Run the configured A3 explanation apps for one persisted Gold monitoring stage."""
    run = _load_run(run_id)
    if run.get("scenario_id") != "GOLD-02" or stage_id not in {"GOLD-02", "GOLD-03"}:
        raise ValueError("A3 Gold execution requires a GOLD-02/03 monitoring stage")
    mapping = _mapping(run)
    execution_key = f"A3:{stage_id}"
    existing_id = mapping["dify_executions"].get(execution_key)
    if existing_id and get_gold_record(existing_id):
        return read_dual_gold_run(run_id)
    monitoring_id = mapping["monitoring_stages"].get(stage_id)
    if not monitoring_id:
        raise ValueError(f"Persisted monitoring stage {stage_id} is required before A3 execution")

    folder = _folder("GOLD-02")
    fixture_path = "stages/GOLD-02/alarm_and_field.json" if stage_id == "GOLD-02" else "stages/GOLD-03/recovery_review.json"
    stage_input = _read_json(folder, fixture_path)
    stage_input.pop("p6_snapshot_id", None)
    event = _load_event(run)
    stage_input.update({
        "event_id": event["event_id"],
        "stage_id": stage_id,
        "correlation_id": run["trace_id"],
        "parent_correlation_id": run["trace_id"],
        "p6_mapping": event.get("p6_mapping"),
    })
    result = await process_monitoring_with_dify(
        stage_input, user=f"{run_id}:{stage_id}", execute_dify=True,
    )
    explanation = result.get("explanation") if isinstance(result.get("explanation"), Mapping) else {}
    alert = result.get("alert") if isinstance(result.get("alert"), Mapping) else {}
    calls = {"trend": explanation, "alert": alert}
    executed = {
        role: call.get("response")
        for role, call in calls.items()
        if isinstance(call.get("response"), Mapping)
        and call["response"].get("execution_engine") == "dify"
    }
    failed = [call.get("status") for call in executed.values()
              if str(call.get("status", "")).lower() not in {"completed", "succeeded", "success"}]
    execution_status = "completed" if executed and not failed else (
        "partial_error" if executed else "no_dify_call"
    )
    output_status = {
        role: ("available" if isinstance(call.get("response"), Mapping)
               and call["response"].get("response") not in (None, "") else "empty_or_skipped")
        for role, call in calls.items()
    }
    execution_id = new_gold_id("dify-execution", "GOLD-02")
    execution_payload = {
        "record_id": execution_id, "agent_id": "A3", "stage_id": stage_id,
        "event_id": event["event_id"], "run_id": run_id, "trace_id": run["trace_id"],
        "execution_engine": "dify" if executed else "local",
        "status": execution_status, "output_status": output_status,
        "calls": calls, "monitoring_assessment": result.get("monitoring_assessment"),
        "p6_dynamic_monitoring": result.get("p6_dynamic_monitoring"),
        "data_source": stage_input.get("data_source"), "is_simulated": True,
        "error": "; ".join(str(item) for item in failed) or None,
    }
    save_gold_record("dify_execution", "GOLD-02", execution_payload,
                     record_id=execution_id, parent_id=str(event["event_id"]))
    mapping["dify_executions"][execution_key] = execution_id
    monitoring_record = get_gold_record(str(monitoring_id))
    if monitoring_record:
        monitoring_payload = dict(monitoring_record["payload"])
        monitoring_payload["a3_dify_execution_id"] = execution_id
        monitoring_payload["a3_dify_output_status"] = output_status
        update_gold_record(str(monitoring_id), monitoring_payload)
    event.setdefault("a3_execution_refs", {})[stage_id] = execution_id
    _timeline(event, "a3_dify_execution_persisted", result.get("monitoring", {}).get("as_of"),
              stage_id=stage_id, execution_id=execution_id, status=execution_status)
    _save_event(event)
    run.setdefault("a3_status_by_stage", {})[stage_id] = execution_status
    _save_run(run)
    return read_dual_gold_run(run_id)


async def _generate_a5_report(
    run: dict[str, Any], event: dict[str, Any], investigation: dict[str, Any],
    decision: dict[str, Any], tasks: list[dict[str, Any]], report_type: str,
    *, execute_dify: bool = False, existing_report_id: str | None = None,
) -> dict[str, Any]:
    records = _records(run)
    feedback = [item["payload"] for item in records if item["record_type"] == "feedback"]
    task_reviews = [item["payload"] for item in records if item["record_type"] == "task_review"]
    attachments = [item["payload"] for item in records if item["record_type"] == "attachment"]
    approvals = [item["payload"] for item in records if item["record_type"] == "approval"]
    facts = {
        "event": event, "investigation": investigation, "tasks": tasks, "feedback": feedback,
        "task_reviews": task_reviews, "approvals": approvals, "risk_review": decision,
        "attachments": attachments, "facts_status": "ready",
        "source_status": {"event": "sqlite_readback", "investigation": "sqlite_readback",
                           "decision": "sqlite_readback", "tasks": "sqlite_readback",
                           "feedback": "sqlite_readback", "task_reviews": "sqlite_readback"},
        "is_simulated": True,
    }
    report = await generate_report_from_facts(
        facts,
        user=str(run["run_id"]),
        query=f"根据已持久化的宜昌Gold事件事实生成{report_type}报告。",
        allow_simulated_gold_dify=execute_dify,
    )
    report_id = existing_report_id or new_gold_id("report", str(run["scenario_id"]))
    report.update({
        "report_id": report_id, "report_type": report_type,
        "title": {"investigation": "地质灾害应急调查报告", "retrospective": "地质灾害处置复盘报告"}.get(report_type, report_type),
        "event_id": event["event_id"], "run_id": run["run_id"], "trace_id": run["trace_id"],
        "scenario_id": run["scenario_id"], "is_simulated": True,
        "execution_engine": report.get("execution_engine") or "local",
        "status": "draft_unreviewed", "review_status": "not_reviewed",
        "archive_status": "not_required_for_event_completion",
        "source_facts": facts,
        "associations": {"event_id": event["event_id"],
                         "task_ids": [item.get("task_id") for item in tasks if item.get("task_id")],
                         "decision_id": decision.get("decision_id")},
    })
    if not isinstance(report.get("report_text"), str) or not report["report_text"].strip():
        report["report_text"] = _render_runtime_report(report_type, event, investigation, decision, tasks, feedback, task_reviews)
        report["execution_engine"] = "local"
        report["generation"] = {"execution_engine": "local", "status": "local_facts_template_fallback",
                                "fallback_reason": "A5 adapter returned no report text"}
    report["sections"] = dict(report.get("sections") or {})
    synchronized_text = sync_report_markdown_status(report)
    if synchronized_text is not None:
        report["report_text"] = synchronized_text
    report["sections"]["runtime_business_markdown"] = report["report_text"]
    _persist_report_docx(report)
    if existing_report_id and get_gold_record(existing_report_id):
        update_gold_record(report_id, report)
    else:
        save_gold_record("report", str(run["scenario_id"]), report, record_id=report_id,
                         parent_id=str(event["event_id"]))
    generation = report.get("generation") if isinstance(report.get("generation"), Mapping) else {}
    if generation.get("execution_engine") == "dify":
        execution_id = new_gold_id("dify-execution", str(run["scenario_id"]))
        execution_payload = {
            "record_id": execution_id, "agent_id": "A5", "report_type": report_type,
            "event_id": event["event_id"], "report_id": report_id, "run_id": run["run_id"],
            "trace_id": generation.get("trace_id") or run["trace_id"],
            "execution_engine": "dify", "status": generation.get("dify_execution_status") or generation.get("status"),
            "output_status": generation.get("dify_output_status"),
            "dify_app": generation.get("dify_app"), "app_mode": generation.get("app_mode"),
            "workflow_run_id": generation.get("workflow_run_id"), "task_id": generation.get("task_id"),
            "message_id": generation.get("message_id"), "conversation_id": generation.get("conversation_id"),
            "raw_outputs": generation.get("raw_outputs"), "raw_response": generation.get("raw_response"),
            "input_snapshot": generation.get("input_snapshot"),
            "error": generation.get("error"), "is_simulated": True,
            "data_source": "persisted Gold business records read back from SQLite",
        }
        save_gold_record("dify_execution", str(run["scenario_id"]), execution_payload,
                         record_id=execution_id, parent_id=str(event["event_id"]))
        report["dify_execution_id"] = execution_id
        update_gold_record(report_id, report)
        _mapping(run)[f"dify_executions"][f"A5:{report_type}"] = execution_id
        _save_run(run)
    return report


async def execute_gold_a5_investigation(run_id: str) -> dict[str, Any]:
    """Re-run the persisted investigation report through A5 and keep its original report ID."""
    run = _load_run(run_id)
    mapping = _mapping(run)
    execution_key = "A5:investigation"
    existing_execution = mapping["dify_executions"].get(execution_key)
    if existing_execution and get_gold_record(existing_execution):
        return read_dual_gold_run(run_id)
    records = _records(run)
    event = _load_event(run)
    investigation_record = next((item for item in records if item["record_type"] == "investigation"), None)
    decision_record = next((item for item in records if item["record_type"] == "decision"), None)
    if not investigation_record or not decision_record:
        raise ValueError("Persisted A2 investigation and A4 assessment are required before A5")
    report_key = next((key for key in mapping["reports"] if "INVESTIGATION" in key), None)
    existing_report_id = mapping["reports"].get(report_key) if report_key else None
    report = await _generate_a5_report(
        run, event, investigation_record["payload"], decision_record["payload"], [],
        "investigation", execute_dify=True, existing_report_id=existing_report_id,
    )
    if not report_key:
        report_key = f"{run['fixture_event_id']}:REPORT:INVESTIGATION"
    mapping["reports"][report_key] = report["report_id"]
    execution_id = report.get("dify_execution_id")
    if execution_id:
        mapping["dify_executions"][execution_key] = execution_id
    event["a5_investigation_report_id"] = report["report_id"]
    _timeline(event, "a5_investigation_report_generated", None,
              report_id=report["report_id"], execution_id=execution_id,
              generation_status=report.get("generation_status"))
    _save_event(event)
    _save_run(run)
    return read_dual_gold_run(run_id)


def _render_runtime_report(
    report_type: str, event: Mapping[str, Any], investigation: Mapping[str, Any],
    decision: Mapping[str, Any], tasks: list[Mapping[str, Any]],
    feedback: list[Mapping[str, Any]], reviews: list[Mapping[str, Any]],
) -> str:
    title = "地质灾害应急调查报告" if report_type == "investigation" else "地质灾害处置复盘报告"
    lines = [f"# {title}（合成业务案例）", "", f"- 事件：`{event.get('event_id')}`",
             f"- 场景：{', '.join(event.get('scenario_ids', []))}",
             f"- 地点：{event.get('admin_area') or event.get('location_description') or '未核实'}",
             f"- 事件时间：{event.get('occurred_at') or event.get('event_time') or '未提供'}",
             "- 数据属性：模拟业务事实；不代表现实险情或现实处置。", ""]
    if report_type == "investigation":
        lines.extend(["## 调查记录", str(investigation.get("conclusion") or investigation.get("mock_case_facts", {}).get("preliminary_conclusion") or "调查结论待补充。"),
                      "", "## 变形迹象与威胁对象"])
        for item in investigation.get("observed_features", []):
            lines.append(f"- {item}")
        for item in investigation.get("threat_objects", []):
            lines.append(f"- {item.get('type')}: {item.get('status')}; 数量={item.get('count')}")
    else:
        lines.extend(["## 研判与处置依据", str(decision.get("recommendation") or decision.get("disposal_opinion") or "本地适配器未生成额外研判文字。"),
                      "", "## 任务执行与验收", "|任务ID|措施|负责人|状态|反馈数|复核|", "|---|---|---|---|---:|---|"])
        for task in tasks:
            task_id = task.get("task_id")
            task_feedback = [item for item in feedback if item.get("task_id") == task_id]
            review = next((item for item in reviews if item.get("task_id") == task_id), {})
            action = task.get("action") if isinstance(task.get("action"), Mapping) else {}
            lines.append(f"|{task_id}|{action.get('title') or action.get('action_type')}|{action.get('person')}|{task.get('status')}|{len(task_feedback)}|{review.get('review_result', '待复核')}|")
        lines.extend(["", "## 遗留风险", str(investigation.get("residual_risk") or "模拟恢复不代表隐患销号或现实安全结论。")])
    return "\n".join(lines).strip() + "\n"


async def approve_gold_plan(run_id: str, *, fixture_replay: bool, reviewer_id: str | None = None) -> dict[str, Any]:
    if not fixture_replay:
        raise ValueError("This Gold endpoint only accepts an explicit fixture_replay approval")
    run = _load_run(run_id)
    mapping = _mapping(run)
    event = _load_event(run)
    if mapping["approvals"].get("plan"):
        return read_dual_gold_run(run_id)
    if run.get("phase") != "awaiting_plan_review":
        raise ValueError("Gold plan is not awaiting review")
    folder = _folder(str(run["scenario_id"]))
    plan_review = _read_json(folder, "plan_review.json")
    if plan_review.get("decision") != "approved_for_gold_replay":
        raise ValueError("Gold plan review fixture is not an approval")
    proposals = [item for item in _records(run) if item["record_type"] == "task_proposal"]
    expected = set(mapping["proposals"].values())
    if len(proposals) != 4 or {item["record_id"] for item in proposals} != expected:
        raise ValueError("Four persisted task proposals are required before plan approval")
    approval_id = new_gold_id("approval", str(run["scenario_id"]))
    approved_by = reviewer_id or plan_review.get("reviewer_id")
    approval = {
        **plan_review, "approval_id": approval_id, "event_id": event["event_id"],
        "run_id": run_id, "reviewer_id": approved_by, "fixture_review_key": plan_review.get("review_fixture_key"),
        "approved_proposal_ids": sorted(expected), "approved": True,
        "approval_type": "disposal_plan", "approval_mode": "simulated_gold_test_harness",
        "execution_engine": "local", "is_simulated": True,
    }
    save_gold_record("approval", str(run["scenario_id"]), approval, record_id=approval_id,
                     parent_id=str(event["event_id"]))
    mapping["approvals"]["plan"] = approval_id
    mapping["approvals"][str(plan_review.get("review_fixture_key"))] = approval_id
    task_fixtures = _read_json(folder, "tasks.json")
    fixture_tasks = {item["task_fixture_key"]: item for item in task_fixtures}
    for proposal_record in proposals:
        proposal = proposal_record["payload"]
        task_key = str(proposal.get("task_fixture_key"))
        existing_id = mapping["tasks"].get(task_key)
        existing = get_gold_record(existing_id) if existing_id else None
        if existing:
            continue
        task_id = new_gold_id("task", str(run["scenario_id"]))
        fixture = fixture_tasks[task_key]
        action = dict(proposal.get("action") or {})
        task = {
            "task_id": task_id, "event_id": event["event_id"], "run_id": run_id,
            "trace_id": run["trace_id"], "scenario_id": run["scenario_id"],
            "proposal_id": proposal_record["record_id"], "fixture_task_key": task_key,
            "fixture_proposal_key": proposal.get("fixture_proposal_key"),
            "status": "assigned_pending_feedback", "action": action,
            "assignee_id": fixture.get("responsible_person_id"),
            "co_assignee_ids": fixture.get("co_responsible_person_ids", []),
            "reviewer_id": approved_by, "approval_id": approval_id,
            "approval_mode": "simulated_gold_test_harness", "execution_engine": "local",
            "formal_java_task_created": False, "is_simulated": True,
            "data_source": fixture.get("data_source", "v1.1_gold_fixture"),
            "dispatch_time": fixture.get("dispatch_time_expected"),
        }
        save_gold_record("task", str(run["scenario_id"]), task, record_id=task_id,
                         parent_id=str(event["event_id"]))
        mapping["tasks"][task_key] = task_id
        proposal.update({"status": "approved_for_dispatch", "task_id": task_id,
                         "approval_id": approval_id, "approval_mode": "simulated_gold_test_harness"})
        update_gold_record(proposal_record["record_id"], proposal)
        _save_run(run)

    task_records = [record["payload"] for record in _records(run) if record["record_type"] == "task"]
    disposal_text = _render_runtime_report("disposal_opinion", event, {},
                                           {"recommendation": "四条任务来自已持久化A4研判与v1.1措施契约，均须按模拟场景执行。"},
                                           task_records, [], [])
    disposal_id = new_gold_id("report", str(run["scenario_id"]))
    disposal_fixture_key = next((key for key in run.get("fixture_report_keys", []) if "DISPOSAL" in key),
                                 f"{run['fixture_event_id']}:REPORT:DISPOSAL")
    disposal_report = {
        "report_id": disposal_id, "fixture_report_key": disposal_fixture_key,
        "report_type": "disposal_opinion", "title": "地质灾害应急调查处置意见书",
        "report_text": disposal_text, "event_id": event["event_id"], "run_id": run_id,
        "trace_id": run["trace_id"], "scenario_id": run["scenario_id"],
        "task_ids": [item["task_id"] for item in task_records],
        "approval_id": approval_id, "status": "approved_for_gold_replay",
        "review_status": "approved", "execution_engine": "local",
        "is_simulated": True, "data_source": "persisted Gold task proposals and plan approval",
    }
    disposal_report["sections"] = {"runtime_business_markdown": disposal_report["report_text"]}
    disposal_report["report_text"] = sync_report_markdown_status(disposal_report) or disposal_report["report_text"]
    disposal_report["sections"]["runtime_business_markdown"] = disposal_report["report_text"]
    _persist_report_docx(disposal_report)
    save_gold_record("report", str(run["scenario_id"]), disposal_report,
                     record_id=disposal_id, parent_id=str(event["event_id"]))
    mapping["reports"][disposal_fixture_key] = disposal_id
    _timeline(event, "plan_review_approved_and_tasks_created", plan_review.get("review_time"),
              approval_id=approval_id, task_ids=[item["task_id"] for item in task_records])
    event.update({"status": "task_execution_in_progress", "event_status": "task_execution_in_progress"})
    _save_event(event)
    run.update({"phase": "task_execution_in_progress", "status": "task_execution_in_progress",
                "plan_review_id": approval_id, "approved_at": _now()})
    _save_run(run)
    return read_dual_gold_run(run_id)


async def replay_gold_feedbacks(run_id: str, *, fixture_replay: bool, stage_id: str | None = None) -> dict[str, Any]:
    if not fixture_replay:
        raise ValueError("Set fixture_replay=true to replay the mock Gold feedback records")
    run = _load_run(run_id)
    mapping = _mapping(run)
    if not mapping["approvals"].get("plan"):
        raise ValueError("The disposal plan must be approved before fixture feedback can be submitted")
    folder = _folder(str(run["scenario_id"]))
    event = _load_event(run)
    feedback_fixtures = _read_json(folder, "feedbacks.json")
    if run["scenario_id"] == "GOLD-01":
        target_stage = "GOLD-01"
        selected = feedback_fixtures
    else:
        target_stage = stage_id or ("GOLD-03" if mapping["monitoring_stages"].get("GOLD-03") else "GOLD-02")
        if target_stage not in {"GOLD-02", "GOLD-03"}:
            raise ValueError("stage_id must be GOLD-02 or GOLD-03")
        selected = [item for item in feedback_fixtures
                    if f":{target_stage}:" in str(item.get("data_source", ""))]
    if not selected:
        raise ValueError(f"No fixture feedback records found for {target_stage}")
    if target_stage == "GOLD-03" and not mapping["monitoring_stages"].get("GOLD-03"):
        raise ValueError("GOLD-03 recovery monitoring must be executed before its feedback")
    created: list[str] = []
    for fixture in selected:
        key = str(fixture["feedback_fixture_key"])
        if mapping["feedbacks"].get(key):
            created.append(mapping["feedbacks"][key])
            continue
        task_id = mapping["tasks"].get(str(fixture.get("task_fixture_key")))
        if not task_id:
            raise ValueError(f"No runtime task is mapped for {fixture.get('task_fixture_key')}")
        feedback_id = new_gold_id("feedback", str(run["scenario_id"]))
        feedback = {
            **fixture, "feedback_id": feedback_id, "fixture_feedback_key": key,
            "fixture_task_key": fixture.get("task_fixture_key"), "task_id": task_id,
            "event_id": event["event_id"], "run_id": run_id, "trace_id": run["trace_id"],
            "scenario_id": run["scenario_id"], "status": "submitted_pending_task_review",
            "execution_engine": "local", "is_simulated": True,
        }
        save_gold_record("feedback", str(run["scenario_id"]), feedback,
                         record_id=feedback_id, parent_id=task_id)
        mapping["feedbacks"][key] = feedback_id
        created.append(feedback_id)
        task_record = get_gold_record(task_id)
        if task_record:
            task_payload = dict(task_record["payload"])
            task_payload["status"] = "feedback_received_pending_review"
            task_payload["last_feedback_id"] = feedback_id
            update_gold_record(task_id, task_payload)
        _save_run(run)
    expected_feedback_keys = {str(item["feedback_fixture_key"]) for item in feedback_fixtures}
    if expected_feedback_keys.issubset(mapping["feedbacks"].keys()):
        event.update({"status": "awaiting_task_review", "event_status": "awaiting_task_review"})
        run.update({"phase": "awaiting_task_review", "status": "awaiting_task_review"})
    elif run["scenario_id"] == "GOLD-02" and target_stage == "GOLD-02":
        event.update({"status": "awaiting_recovery_stage", "event_status": "awaiting_recovery_stage"})
        run.update({"phase": "awaiting_recovery_stage", "status": "awaiting_recovery_stage"})
    else:
        event.update({"status": "task_execution_in_progress", "event_status": "task_execution_in_progress"})
    _timeline(event, "task_feedback_persisted", None, feedback_ids=created, stage_id=target_stage)
    _save_event(event)
    _save_run(run)
    return {"run_id": run_id, "event_id": event["event_id"], "stage_id": target_stage,
            "feedback_ids": created, "feedback_count": len(created), "status": run["status"],
            "execution_engine": "local", "is_simulated": True}


async def run_gold_recovery_stage(run_id: str) -> dict[str, Any]:
    run = _load_run(run_id)
    if run.get("scenario_id") != "GOLD-02":
        raise ValueError("GOLD-03 is only a recovery stage of a GOLD-02 run")
    mapping = _mapping(run)
    if mapping["monitoring_stages"].get("GOLD-03"):
        return read_dual_gold_run(run_id)
    if not mapping["approvals"].get("plan") or len(mapping["tasks"]) != 4:
        raise ValueError("Approve the GOLD-02 disposal plan and create its four tasks before GOLD-03")
    feedback_fixtures = _read_json(_folder("GOLD-02"), "feedbacks.json")
    initial_feedback_keys = {
        str(item["feedback_fixture_key"]) for item in feedback_fixtures
        if ":GOLD-02:" in str(item.get("data_source", ""))
    }
    if not initial_feedback_keys.issubset(mapping["feedbacks"].keys()):
        raise ValueError("Persist the GOLD-02 task feedbacks before appending GOLD-03 recovery monitoring")
    if mapping["task_reviews"]:
        raise ValueError("GOLD-03 must run before task reviews")
    folder = _folder("GOLD-02")
    event = _load_event(run)
    initial = _read_json(folder, "stages/GOLD-02/alarm_and_field.json")
    recovery = _read_json(folder, "stages/GOLD-03/recovery_review.json")
    initial_rows = initial.get("observations", [])
    recovery_rows = recovery.get("observations", [])
    overlap = recovery.get("measurement_contract", {}).get("overlap_hours")
    if not isinstance(overlap, int) or overlap <= 0 or initial_rows[-overlap:] != recovery_rows[:overlap]:
        raise ValueError("GOLD-02/GOLD-03 monitoring series overlap failed exact row validation")
    stage_input = dict(recovery)
    stage_input.pop("p6_snapshot_id", None)
    stage_input.update({"event_id": event["event_id"], "correlation_id": run["trace_id"],
                        "parent_correlation_id": run["trace_id"], "stage_id": "GOLD-03"})
    monitoring_result = await process_monitoring_with_dify(stage_input, execute_dify=False)
    recovery_risk_path = folder / "stages" / "GOLD-03" / "risk_snapshot_reference.json"
    recovery_risk = json.loads(recovery_risk_path.read_text(encoding="utf-8"))
    monitoring_id = new_gold_id("monitoring", "GOLD-02")
    save_gold_record("monitoring_assessment", "GOLD-02", {
        **monitoring_result, "record_id": monitoring_id, "run_id": run_id,
        "event_id": event["event_id"], "trace_id": run["trace_id"], "stage_id": "GOLD-03",
        "series_overlap_rows": overlap, "is_simulated": True,
    }, record_id=monitoring_id, parent_id=str(event["event_id"]))
    mapping["monitoring_stages"]["GOLD-03"] = monitoring_id
    event.update({
        "monitoring": monitoring_result.get("monitoring"),
        "monitoring_assessment": monitoring_result.get("monitoring_assessment"),
        "p6_snapshot": monitoring_result.get("p6_snapshot"),
        "p6_dynamic_snapshot": monitoring_result.get("p6_dynamic_snapshot"),
        "p6_fixture_reference": recovery_risk.get("p6_candidate"),
        "p6_dynamic_monitoring": monitoring_result.get("p6_dynamic_monitoring"),
        "recovery_detected": monitoring_result.get("recovery_detected"),
        "recovery_stage": monitoring_result.get("monitoring", {}).get("recovery_stage"),
        "stage_id": "GOLD-03",
        "status": "task_execution_in_progress",
        "event_status": "task_execution_in_progress",
        "hazard_cancelled": False,
    })
    _timeline(event, "recovery_monitoring_appended", recovery.get("as_of"),
              monitoring_id=monitoring_id, overlap_rows=overlap)
    _save_event(event)
    run.update({"phase": "GOLD-03_recovery_observed", "status": "task_execution_in_progress",
                "recovery_stage_id": monitoring_id, "recovery_observed_at": _now()})
    _save_run(run)
    return read_dual_gold_run(run_id)


async def review_gold_task(run_id: str, task_fixture_key: str, *, fixture_replay: bool,
                           reviewer_id: str | None = None) -> dict[str, Any]:
    if not fixture_replay:
        raise ValueError("Set fixture_replay=true to replay a Gold task review")
    run = _load_run(run_id)
    mapping = _mapping(run)
    folder = _folder(str(run["scenario_id"]))
    task_id = mapping["tasks"].get(task_fixture_key)
    if not task_id:
        raise ValueError("Task fixture key has no persisted runtime task")
    if mapping["task_reviews"].get(task_fixture_key):
        return read_dual_gold_run(run_id)
    if run["scenario_id"] == "GOLD-02" and not mapping["monitoring_stages"].get("GOLD-03"):
        raise ValueError("Run GOLD-03 recovery monitoring before task acceptance")
    review_fixture = _read_json(folder, "task_reviews.json")
    review = next((item for item in review_fixture.get("items", [])
                   if item.get("task_fixture_key") == task_fixture_key), None)
    if not review:
        raise ValueError("Task review fixture was not found")
    records = _records(run)
    feedback_by_fixture = {
        item["payload"].get("fixture_feedback_key"): item["payload"]
        for item in records if item["record_type"] == "feedback"
    }
    required_keys = review.get("feedback_fixture_keys", [])
    if any(key not in feedback_by_fixture for key in required_keys):
        raise ValueError("Every feedback referenced by this independent task review must be persisted first")
    feedback_times = [datetime.fromisoformat(str(feedback_by_fixture[key]["feedback_time"]).replace("Z", "+00:00"))
                      for key in required_keys]
    review_time = datetime.fromisoformat(str(review["review_time"]).replace("Z", "+00:00"))
    if feedback_times and review_time <= max(feedback_times):
        raise ValueError("Task review time must be later than its final required feedback")
    task_review_id = new_gold_id("task-review", str(run["scenario_id"]))
    approval_id = new_gold_id("approval", str(run["scenario_id"]))
    fixture_result = str(review.get("review_result") or "")
    result = {
        **review, "task_review_id": task_review_id, "approval_id": approval_id,
        "fixture_review_key": review.get("review_fixture_key"), "task_id": task_id,
        "event_id": run["runtime_event_id"], "run_id": run_id, "trace_id": run["trace_id"],
        "feedback_ids": [feedback_by_fixture[key]["feedback_id"] for key in required_keys],
        "reviewer_id": reviewer_id or review.get("reviewer_id"),
        "review_result": fixture_result,
        "status": fixture_result if fixture_result in {"accepted", "accepted_with_followup"} else "rejected",
        "approval_mode": "simulated_gold_test_harness", "execution_engine": "local",
        "is_simulated": True,
    }
    save_gold_record("task_review", str(run["scenario_id"]), result,
                     record_id=task_review_id, parent_id=task_id)
    mapping["task_reviews"][task_fixture_key] = task_review_id
    mapping["approvals"][str(review.get("review_fixture_key"))] = approval_id
    mapping["approvals"][f"task_review:{task_fixture_key}"] = approval_id
    task_record = get_gold_record(task_id)
    if task_record:
        task_payload = dict(task_record["payload"])
        task_payload.update({"status": result["status"], "task_review_id": task_review_id,
                             "review_approval_id": approval_id})
        update_gold_record(task_id, task_payload)
    save_gold_record("approval", str(run["scenario_id"]), {
        "approval_id": approval_id, "approval_type": "task_review", "task_review_id": task_review_id,
        "task_id": task_id, "event_id": run["runtime_event_id"], "run_id": run_id,
        "reviewer_id": result["reviewer_id"],
        "approved": result["status"] in {"accepted", "accepted_with_followup"},
        "approval_mode": "simulated_gold_test_harness", "execution_engine": "local", "is_simulated": True,
    }, record_id=approval_id, parent_id=task_id)
    _save_run(run)
    expected_keys = {item.get("task_fixture_key") for item in _read_json(folder, "tasks.json")}
    review_records = [get_gold_record(value) for value in mapping["task_reviews"].values()]
    all_accepted = expected_keys.issubset(mapping["task_reviews"].keys()) and all(
        item and item["payload"].get("status") in {"accepted", "accepted_with_followup"}
        for item in review_records
    )
    if all_accepted:
        event = _load_event(run)
        event.update({"status": "awaiting_final_report", "event_status": "awaiting_final_report"})
        _timeline(event, "all_tasks_independently_reviewed", review.get("review_time"),
                  task_review_ids=list(mapping["task_reviews"].values()))
        _save_event(event)
        run.update({"phase": "awaiting_final_report", "status": "awaiting_final_report"})
        _save_run(run)
    return read_dual_gold_run(run_id)


async def create_gold_retrospective(run_id: str, *, execute_dify: bool = False) -> dict[str, Any]:
    run = _load_run(run_id)
    mapping = _mapping(run)
    folder = _folder(str(run["scenario_id"]))
    if run["scenario_id"] == "GOLD-02" and not mapping["monitoring_stages"].get("GOLD-03"):
        raise ValueError("GOLD-03 recovery monitoring is required for this combined event")
    task_fixture_keys = {item["task_fixture_key"] for item in _read_json(folder, "tasks.json")}
    review_records = [get_gold_record(mapping["task_reviews"].get(key, "")) for key in task_fixture_keys]
    if not task_fixture_keys.issubset(mapping["task_reviews"].keys()) or any(
        not item or item["payload"].get("status") not in {"accepted", "accepted_with_followup"}
        for item in review_records
    ):
        raise ValueError("All four task reviews must be accepted before retrospective report generation")
    existing_report_id = mapping["reports"].get("final_retrospective")
    existing_report = get_gold_record(str(existing_report_id)) if existing_report_id else None
    a5_execution_id = mapping["dify_executions"].get("A5:retrospective")
    if existing_report and (not execute_dify or (a5_execution_id and get_gold_record(a5_execution_id))):
        return read_dual_gold_run(run_id)
    event = _load_event(run)
    records = _records(run)
    investigation_record = next(item["payload"] for item in records if item["record_type"] == "investigation")
    decision = next(item["payload"] for item in records if item["record_type"] == "decision")
    task_records = [item["payload"] for item in records if item["record_type"] == "task"]
    reuse_report_id = existing_report_id
    if existing_report and existing_report["payload"].get("review_status") == "approved":
        superseded = dict(existing_report["payload"])
        superseded.update({"status": "superseded", "review_status": "superseded",
                           "superseded_by_dify_execution": True})
        update_gold_record(str(existing_report_id), superseded)
        mapping["reports"]["superseded_retrospective"] = str(existing_report_id)
        reuse_report_id = None
        old_approval_id = mapping["approvals"].get("final_report")
        if old_approval_id:
            mapping["approvals"] = {key: value for key, value in mapping["approvals"].items()
                                     if value != old_approval_id}
    report = await _generate_a5_report(
        run, event, investigation_record, decision, task_records, "retrospective",
        execute_dify=execute_dify, existing_report_id=reuse_report_id,
    )
    final_key = next((key for key in run.get("fixture_report_keys", []) if "RETROSPECTIVE" in key),
                     f"{run['fixture_event_id']}:REPORT:RETROSPECTIVE")
    mapping["reports"][final_key] = report["report_id"]
    mapping["reports"]["final_retrospective"] = report["report_id"]
    event.update({"status": "awaiting_final_report_review", "event_status": "awaiting_final_report_review"})
    _timeline(event, "retrospective_report_generated", None, report_id=report["report_id"],
              generation_engine=report.get("execution_engine"))
    _save_event(event)
    run.update({"phase": "awaiting_final_report_review", "status": "awaiting_final_report_review",
                "final_report_id": report["report_id"], "a5_execution_engine": report.get("execution_engine")})
    _save_run(run)
    return read_dual_gold_run(run_id)


async def approve_gold_final_report(run_id: str, *, fixture_replay: bool,
                                    reviewer_id: str | None = None) -> dict[str, Any]:
    if not fixture_replay:
        raise ValueError("Set fixture_replay=true to replay the final Gold report review")
    run = _load_run(run_id)
    mapping = _mapping(run)
    if mapping["approvals"].get("final_report"):
        return read_dual_gold_run(run_id)
    event = _load_event(run)
    report_id = mapping["reports"].get("final_retrospective")
    report_record = get_gold_record(str(report_id)) if report_id else None
    if not report_record or report_record.get("record_type") != "report":
        raise ValueError("A persisted final retrospective report is required")
    task_keys = {item.get("task_fixture_key") for item in _read_json(_folder(str(run["scenario_id"])), "tasks.json")}
    review_records = [get_gold_record(mapping["task_reviews"].get(key, "")) for key in task_keys]
    if not task_keys.issubset(mapping["task_reviews"].keys()) or any(
        not item or item["payload"].get("status") not in {"accepted", "accepted_with_followup"}
        for item in review_records
    ):
        raise ValueError("All four accepted task reviews are required before final report approval")
    final_fixture = _read_json(_folder(str(run["scenario_id"])), "final_review.json")
    approval_id = new_gold_id("approval", str(run["scenario_id"]))
    approval = {
        **final_fixture, "approval_id": approval_id, "event_id": event["event_id"],
        "run_id": run_id, "report_id": report_id,
        "fixture_review_key": final_fixture.get("review_fixture_key"),
        "reviewer_id": reviewer_id or final_fixture.get("reviewer_id"),
        "approved": final_fixture.get("decision") == "approved_for_gold_replay",
        "approval_type": "final_report", "approval_mode": "simulated_gold_test_harness",
        "execution_engine": "local", "is_simulated": True,
    }
    if not approval["approved"]:
        raise ValueError("Final report review fixture is not an approval")
    save_gold_record("approval", str(run["scenario_id"]), approval,
                     record_id=approval_id, parent_id=str(report_id))
    mapping["approvals"]["final_report"] = approval_id
    mapping["approvals"][str(final_fixture.get("review_fixture_key"))] = approval_id
    report = dict(report_record["payload"])
    report.update({"status": "approved", "review_status": "approved", "reviewer_id": approval["reviewer_id"],
                   "approval_id": approval_id, "reviewed_at": final_fixture.get("review_time"),
                   "approval_mode": "simulated_gold_test_harness"})
    report["report_text"] = sync_report_markdown_status(report) or report.get("report_text")
    report.setdefault("sections", {})["runtime_business_markdown"] = report["report_text"]
    _persist_report_docx(report)
    update_gold_record(str(report_id), report)
    event.update({"status": "completed", "event_status": "completed",
                  "closure_reason": "final_retrospective_report_review_approved",
                  "completed_report_id": report_id, "hazard_cancelled": False,
                  "real_world_safe_status_established": False})
    _timeline(event, "final_report_review_approved_event_completed", final_fixture.get("review_time"),
              report_id=report_id, approval_id=approval_id)
    _save_event(event)
    run.update({"phase": "completed", "status": "completed", "final_review_id": approval_id,
                "completed_at": _now()})
    _save_run(run)
    return read_dual_gold_run(run_id)
