"""Yichang-scoped QA over the existing knowledge bases and supplied context."""

import json
import re
import sqlite3
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

from .config import settings
from .dify_adapters.a1_qa import map_persisted_event_evidence, run_a1_chatflow
from .dify_adapters.a4_decision import is_simulated_evidence
from .java_client import lookup_business_record
from .llm import answer_with_evidence
from .rag_client import retrieve as retrieve_from_rag, retrieve_yichang
from .yichang_contract import YICHANG_KB_IDS, YICHANG_KNOWLEDGE_BASES


_BUSINESS_LOOKUP = re.compile(
    r"(?:事件|任务|报告).*(?:状态|进展|历史|反馈|详情|编号|记录|最新|列表|清单|数量|统计)"
    r"|(?:查询|查找|列出|统计).*(?:旧|历史|既有|已有|当前|所有|全部)?"
    r"(?:事件|任务|报告)(?:列表|清单|记录|详情|状态|进展|历史|反馈|编号|最新|数量)?(?=\s|$)"
    r"|\b(?:EV|TASK|RPT)-[A-Z0-9_-]+\b",
    re.I,
)
_GOLD_RECORD_ID = re.compile(
    r"\b(?P<record_id>DEMO-GOLD-(?P<record_type>EVENT|TASK|REPORT)-[A-Z0-9][A-Z0-9_-]*)\b",
    re.I,
)
_PREFIXED_RECORD_ID = re.compile(r"\b(?P<prefix>EV|TASK|RPT)-(?P<record_id>[A-Z0-9][A-Z0-9_-]*)\b", re.I)
_TYPED_NUMERIC_RECORD_ID = re.compile(
    r"(?P<record_type>事件|任务|报告)\s*(?:编号|ID)\s*(?:是|为|[:：#])?\s*(?P<record_id>\d+)\b",
    re.I,
)
_EXPLICIT_REPORT_ID = re.compile(r"\b(?:DEMO-GOLD-REPORT|RPT)-[A-Z0-9][A-Z0-9_-]*\b", re.I)
_DEMO_GOLD_REPORT_ID = re.compile(r"\bDEMO-GOLD-REPORT-[A-Z0-9][A-Z0-9_-]*\b", re.I)
_REPORT_ARCHIVE_LOOKUP = re.compile(
    r"(?:归档|存档|入库|审批|审核|批准|原文|正文|全文|报告内容|approved|archived|archive|report text)",
    re.I,
)
_REPORT_STATUS_LOOKUP = re.compile(r"(?:状态|进展|处理状态|记录状态)")
_COUNTIES = ("秭归", "五峰", "长阳", "兴山", "夷陵", "远安", "当阳", "枝江", "宜都", "点军", "猇亭", "西陵", "伍家岗")
_PRIVATE_CONTEXT_KEYS = {
    "access_token",
    "api_key",
    "auth",
    "authorization",
    "conversation_id",
    "credentials",
    "dify_user",
    "headers",
    "token",
    "user",
    "user_id",
}
_EVIDENCE_REFERENCE = re.compile(r"\bEV-[A-Z0-9_-]+\b", re.I)


def _region(query: str, context: Mapping[str, Any] | None) -> dict[str, str | None]:
    supplied = context.get("admin_area", "") if context else ""
    text = f"{query} {supplied}"
    county = next((name for name in _COUNTIES if name in text), None)
    return {"city": "宜昌市", "county": county}


def _public_context(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _public_context(item)
            for key, item in value.items()
            if str(key).casefold().replace("-", "_") not in _PRIVATE_CONTEXT_KEYS
        }
    if isinstance(value, list):
        return [_public_context(item) for item in value]
    return value


def _is_simulated_context(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            field = str(key).casefold().replace("-", "_")
            if field in {"is_simulated", "issimulated"} and (item is True or str(item).casefold() == "true"):
                return True
            if field in {"source_kind", "sourcekind"} and str(item).casefold() in {"simulated", "simulation"}:
                return True
            if field in {"data_source", "datasource"} and str(item).casefold().startswith("local_gold_fixture"):
                return True
            if field in {"id", "record_id", "event_id", "task_id", "report_id", "scenario_id"}:
                if str(item).upper().startswith(("GOLD-", "DEMO-GOLD-")):
                    return True
            if _is_simulated_context(item):
                return True
    elif isinstance(value, list):
        return any(_is_simulated_context(item) for item in value)
    return False


def _business_record_reference(query: str) -> dict[str, str] | None:
    gold = _GOLD_RECORD_ID.search(query)
    if gold:
        return {
            "source": "local_gold_store",
            "record_type": gold.group("record_type").casefold(),
            "record_id": gold.group("record_id"),
        }

    prefixed = _PREFIXED_RECORD_ID.search(query)
    if prefixed:
        record_type = {"EV": "event", "TASK": "task", "RPT": "report"}[prefixed.group("prefix").upper()]
        return {
            "source": "java_backend",
            "record_type": record_type,
            "record_id": prefixed.group(0),
            "backend_record_id": prefixed.group("record_id"),
        }

    typed = _TYPED_NUMERIC_RECORD_ID.search(query)
    if typed:
        record_type = {"事件": "event", "任务": "task", "报告": "report"}[typed.group("record_type")]
        return {
            "source": "java_backend",
            "record_type": record_type,
            "record_id": typed.group("record_id"),
            "backend_record_id": typed.group("record_id"),
        }
    return None


def _gold_database_uri() -> str | None:
    path = Path(settings.yichang_scenario_db_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    if not path.is_file():
        return None
    return f"{path.as_uri()}?mode=ro"


def _gold_record_from_row(row: sqlite3.Row) -> dict[str, Any] | None:
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError):
        return None
    return {
        "record_id": row["record_id"],
        "scenario_id": row["scenario_id"],
        "record_type": row["record_type"],
        "parent_id": row["parent_id"],
        "status": row["status"],
        "is_simulated": bool(row["is_simulated"]),
        "payload": payload,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _read_gold_record(record_id: str) -> dict[str, Any]:
    database_uri = _gold_database_uri()
    if database_uri is None:
        return {"status": "local_gold_store_unavailable", "record": None}

    try:
        with sqlite3.connect(database_uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT record_id, scenario_id, record_type, parent_id, status, is_simulated, payload_json, created_at, updated_at "
                "FROM yichang_gold_records WHERE record_id = ?",
                (record_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        return {"status": "local_gold_store_unavailable", "record": None, "error_type": type(exc).__name__}

    if row is None:
        return {"status": "not_found", "record": None}
    record = _gold_record_from_row(row)
    if record is None:
        return {"status": "local_gold_store_unavailable", "record": None, "error_type": "invalid_payload"}
    return {"status": "found", "record": record}


def _read_gold_children(parent_id: str) -> dict[str, Any]:
    database_uri = _gold_database_uri()
    if database_uri is None:
        return {"status": "local_gold_store_unavailable", "records": []}

    try:
        with sqlite3.connect(database_uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT record_id, scenario_id, record_type, parent_id, status, is_simulated, payload_json, created_at, updated_at "
                "FROM yichang_gold_records WHERE parent_id = ? ORDER BY created_at, rowid",
                (parent_id,),
            ).fetchall()
    except sqlite3.Error as exc:
        return {
            "status": "local_gold_store_unavailable",
            "records": [],
            "error_type": type(exc).__name__,
        }

    records = [_gold_record_from_row(row) for row in rows]
    if any(record is None for record in records):
        return {"status": "local_gold_store_unavailable", "records": [], "error_type": "invalid_payload"}
    return {"status": "found", "records": records}


async def _lookup_java_event_record(record_id: str) -> dict[str, Any]:
    if not settings.java_backend_base_url or not settings.java_backend_bearer_token:
        return {"status": "java_api_not_configured", "record": None}

    headers = {"Authorization": f"Bearer {settings.java_backend_bearer_token}"}
    base = settings.java_backend_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        response = await client.get(f"{base}/dizai/taskHandle/{record_id}")
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, Mapping) or payload.get("code") != 200:
        return {
            "status": "java_api_rejected",
            "record": None,
            "message": payload.get("msg") if isinstance(payload, Mapping) else None,
        }
    record = payload.get("data")
    return {"status": "found" if record is not None else "not_found", "record": record}


def _record_lookup_response(
    query: str,
    context: Mapping[str, Any] | None,
    trace_id: str,
    record_type: str,
    record_id: str,
    source: str,
    lookup: Mapping[str, Any],
    *,
    java_queried: bool,
    backend_record_id: str | None = None,
) -> dict[str, Any]:
    lookup_status = str(lookup.get("status") or "unknown")
    record = lookup.get("record")
    found = lookup_status == "found" and isinstance(record, Mapping)
    backend_record_id = backend_record_id or record_id
    source_endpoint = None
    if source == "java_backend":
        endpoint = {
            "event": "taskHandle",
            "task": "taskDistList",
            "report": "reportDisaster",
        }[record_type]
        source_endpoint = f"/dizai/{endpoint}/{backend_record_id}"
    simulated: bool | None = None
    status_fields: dict[str, Any] = {}
    business_context = None

    if found:
        simulation_marker = record.get("is_simulated")
        if simulation_marker is None:
            simulation_marker = record.get("isSimulated")
        simulated = simulation_marker is True or str(simulation_marker).casefold() == "true"
        status_keys = ("respStatus", "handleProcess") if record_type == "event" and source == "java_backend" else ("status",)
        status_fields = {key: record[key] for key in status_keys if key in record}
        business_context = {
            "record_id": record_id,
            "record_type": record_type,
            "source": source,
            **({"source_endpoint": source_endpoint} if source_endpoint else {}),
            "status": status_fields,
            "is_simulated": simulated,
        }
        if source == "local_gold_store":
            business_context["payload"] = _public_context(record.get("payload", {}))
            business_context["scenario_id"] = record.get("scenario_id")
            business_context["parent_id"] = record.get("parent_id")
        elif record_type == "task" and "feedback_status" in lookup:
            business_context["feedback_status"] = lookup.get("feedback_status")
        status = "completed"
        answer = (
            f"已从 {source}{' ' + source_endpoint if source_endpoint else ''} 读取{record_type}编号 {record_id}；"
            f"状态字段：{json.dumps(status_fields, ensure_ascii=False, sort_keys=True) if status_fields else '接口未返回可识别的状态字段'}；"
            f"is_simulated={'true' if simulated else 'false'}。"
        )
        error = None
    else:
        status_map = {
            "not_found": "business_record_not_found",
            "java_api_not_configured": "java_api_not_configured",
            "local_gold_store_unavailable": "gold_store_unavailable",
            "java_api_rejected": "java_api_rejected",
            "java_api_unavailable": "java_api_unavailable",
            "invalid_java_record_id": "invalid_record_id",
            "gold_record_type_mismatch": "gold_record_type_mismatch",
            "gold_record_missing_simulation_marker": "gold_record_missing_simulation_marker",
        }
        status = status_map.get(lookup_status, "business_record_lookup_unavailable")
        error = lookup.get("message") or lookup.get("error_type")
        if lookup_status == "java_api_not_configured":
            answer = f"Java {record_type}查询接口当前未配置；本次未执行实时查询，无法核实编号 {record_id}。"
        elif lookup_status == "local_gold_store_unavailable":
            answer = f"本地 Gold 存储当前不可读，无法核实编号 {record_id}。"
        elif lookup_status == "not_found":
            answer = f"未在 {source} 找到{record_type}编号 {record_id}。"
        elif lookup_status == "gold_record_type_mismatch":
            answer = f"本地 Gold 记录 {record_id} 的类型与查询不一致，未采用该记录。"
        elif lookup_status == "gold_record_missing_simulation_marker":
            answer = f"本地 Gold 记录 {record_id} 缺少模拟标记，未采用该记录。"
        else:
            answer = f"读取{record_type}编号 {record_id} 失败；来源接口状态为 {lookup_status}。"

    trace_step = "local_gold_record_lookup" if source == "local_gold_store" else "java_business_lookup"
    execution_engine = "java" if java_queried else "local"
    trace = [{
        "trace_id": trace_id,
        "step": trace_step,
        "status": lookup_status,
        "record_id": record_id,
        "record_type": record_type,
        "source_endpoint": source_endpoint,
        "source": source,
        "is_simulated": simulated,
        "execution_engine": execution_engine,
    }, {
        "trace_id": trace_id,
        "step": "dify_a1_chatflow",
        "status": "skipped_persisted_record_lookup",
        "execution_engine": "local",
    }, {
        "trace_id": trace_id,
        "step": "llm_answer",
        "status": "skipped_persisted_record_lookup",
    }]
    if source == "local_gold_store":
        trace.append({"trace_id": trace_id, "step": "java_business_lookup", "status": "not_queried"})

    return {
        "status": status,
        "answer": answer,
        "region": _region(query, context),
        "evidence": [],
        "evidence_ids": [],
        "record_id": record_id,
        "record_type": record_type,
        "record_status": status_fields if found else None,
        "source_endpoint": source_endpoint,
        "business_lookup": True,
        "business_status": lookup_status,
        "business_context": business_context,
        "business_context_source": source,
        "is_simulated": simulated,
        "java_queried": java_queried,
        "execution_engine": execution_engine,
        "app_name": "GeoGuard A1 persisted record lookup",
        "app_mode": f"{source}_{record_type}_lookup",
        "dify_status": "skipped_persisted_record_lookup",
        "outputs": {},
        "parsed_output": None,
        "conversation_id": context.get("conversation_id") if isinstance(context, Mapping) else None,
        "message_id": None,
        "task_id": None,
        "workflow_run_id": None,
        "duration_ms": 0,
        "trace_id": trace_id,
        "error": error,
        "trace": trace,
    }


def _unretrieved_citations(answer: str, parsed_output: Any, evidence: list[dict[str, Any]]) -> list[str]:
    citations = {match.group(0).casefold() for match in _EVIDENCE_REFERENCE.finditer(answer)}

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key).casefold() in {"evidence_id", "evidence_ids"}:
                    if isinstance(item, str):
                        citations.update(match.group(0).casefold() for match in _EVIDENCE_REFERENCE.finditer(item))
                    elif isinstance(item, list):
                        for evidence_id in item:
                            if isinstance(evidence_id, str):
                                citations.update(match.group(0).casefold() for match in _EVIDENCE_REFERENCE.finditer(evidence_id))
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(parsed_output)
    available = {str(item["evidence_id"]).casefold() for item in evidence if item.get("evidence_id")}
    return sorted(citations - available)


def _citations(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    labels = {kb_id: name for name, kb_id in YICHANG_KNOWLEDGE_BASES.items()}
    result = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        evidence_id = item.get("evidence_id")
        source_spans = item.get("source_spans")
        kb_id = item.get("knowledge_base_id")
        if (
            not isinstance(evidence_id, str)
            or not evidence_id.strip()
            or kb_id not in labels
            or not isinstance(source_spans, list)
            or not any(isinstance(span, Mapping) for span in source_spans)
            or not isinstance(item.get("text"), str)
            or not item["text"].strip()
        ):
            continue
        citation = {
            key: item[key]
            for key in ("evidence_id", "knowledge_base_id", "document_id", "chunk_id", "file_name", "page", "source_spans", "text")
            if key in item
        }
        citation["evidence_id"] = evidence_id.strip()
        citation["knowledge_base_label"] = labels[kb_id]
        result.append(citation)
    return result


def _gold_report_evidence(
    report_id: str,
    report_record: Mapping[str, Any] | None,
    children: list[dict[str, Any]],
    event_record: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(report_record, Mapping):
        return None
    report = report_record.get("payload")
    if not isinstance(report, Mapping):
        return None
    event_id = report_record.get("parent_id")
    associations = report.get("associations")
    event = event_record.get("payload") if isinstance(event_record, Mapping) else None
    scenario_id = report_record.get("scenario_id")
    report_status = report.get("status")
    archive_status = report.get("archive_status")
    if not (
        (report_status == "archived" and archive_status == "indexed")
        or (report_status == "archived_demo_local" and archive_status == "archived_demo_local")
    ):
        return None
    if (
        report_record.get("record_id") != report_id
        or report_record.get("record_type") != "report"
        or report_record.get("status") != report_status
        or report_record.get("is_simulated") is not True
        or report.get("report_id") != report_id
        or report.get("is_simulated") is not True
        or not isinstance(report.get("report_text"), str)
        or not report["report_text"].strip()
        or not isinstance(event_id, str)
        or not isinstance(associations, Mapping)
        or associations.get("event_id") != event_id
        or not isinstance(event_record, Mapping)
        or event_record.get("record_id") != event_id
        or event_record.get("record_type") != "event"
        or event_record.get("scenario_id") != scenario_id
        or event_record.get("is_simulated") is not True
        or not isinstance(event, Mapping)
        or event.get("event_id") != event_id
        or event.get("is_simulated") is not True
    ):
        return None

    approval_types: set[str] = set()
    approval_ids = []
    for child in children:
        if not isinstance(child, Mapping) or child.get("record_type") != "approval":
            continue
        payload = child.get("payload")
        if not isinstance(payload, Mapping) or payload.get("report_id") != report_id:
            continue
        approval_type = payload.get("approval_type")
        if not isinstance(approval_type, str) or approval_type not in {"report", "archive", "report_and_archive"}:
            continue
        if (
            child.get("parent_id") != report_id
            or child.get("scenario_id") != scenario_id
            or child.get("is_simulated") is not True
            or payload.get("is_simulated") is not True
            or payload.get("approved") is not True
            or payload.get("event_id") not in (None, event_id)
        ):
            return None
        approval_types.add(approval_type)
        if isinstance(child.get("record_id"), str):
            approval_ids.append(child["record_id"])
    if "report_and_archive" not in approval_types and not {"report", "archive"}.issubset(approval_types):
        return None

    archive_record = next((
        child for child in reversed(children)
        if isinstance(child, Mapping)
        and child.get("record_type") == "archive"
        and child.get("parent_id") == report_id
        and child.get("scenario_id") == scenario_id
        and child.get("status") == archive_status
        and child.get("is_simulated") is True
        and isinstance(child.get("payload"), Mapping)
        and child["payload"].get("report_id") == report_id
        and child["payload"].get("event_id") == event_id
        and child["payload"].get("status") == archive_status
        and child["payload"].get("is_simulated") is True
        and (archive_status != "archived_demo_local" or child["payload"].get("execution_engine") == "local")
        and isinstance(child["payload"].get("document_id"), str)
        and child["payload"]["document_id"].strip()
    ), None)
    if archive_record is None:
        return None
    archive = archive_record["payload"]
    evidence_id = archive_record.get("record_id")
    if not isinstance(evidence_id, str) or not evidence_id.strip():
        return None
    return {
        "evidence_id": evidence_id,
        "record_id": evidence_id,
        "report_id": report_id,
        "event_id": event_id,
        "document_id": archive["document_id"],
        "text": report["report_text"],
        "archive_status": archive_status,
        "approval_record_ids": approval_ids,
        "is_simulated": True,
        "execution_engine": "local",
        "source_kind": (
            "simulated_gold_local_archive"
            if archive_status == "archived_demo_local"
            else "simulated_gold_indexed_archive"
        ),
    }


def _approved_local_gold_report_evidence(
    report_id: str,
    report_record: Mapping[str, Any] | None,
    children: list[dict[str, Any]],
    event_record: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(report_record, Mapping) or not isinstance(event_record, Mapping):
        return None
    report = report_record.get("payload")
    event = event_record.get("payload")
    if not isinstance(report, Mapping) or not isinstance(event, Mapping):
        return None
    event_id = report_record.get("parent_id")
    scenario_id = report_record.get("scenario_id")
    if not (
        report_record.get("record_id") == report_id
        and report_record.get("record_type") == "report"
        and report_record.get("status") == "approved"
        and report_record.get("is_simulated") is True
        and report.get("report_id") == report_id
        and report.get("status") == "approved"
        and report.get("review_status") == "approved"
        and report.get("archive_status") == "not_required_for_event_completion"
        and report.get("is_simulated") is True
        and isinstance(report.get("report_text"), str)
        and bool(report["report_text"].strip())
        and isinstance(report.get("associations"), Mapping)
        and report["associations"].get("event_id") == event_id
        and event_record.get("record_id") == event_id
        and event_record.get("record_type") == "event"
        and event_record.get("scenario_id") == scenario_id
        and event_record.get("is_simulated") is True
        and event.get("event_id") == event_id
        and event.get("status") == "completed"
        and event.get("completed_report_id") == report_id
        and event.get("is_simulated") is True
    ):
        return None
    approval = next((
        item for item in children
        if isinstance(item, Mapping)
        and item.get("record_type") == "approval"
        and item.get("parent_id") == report_id
        and item.get("scenario_id") == scenario_id
        and item.get("is_simulated") is True
        and isinstance(item.get("payload"), Mapping)
        and item["payload"].get("approval_type") == "final_report"
        and item["payload"].get("report_id") == report_id
        and item["payload"].get("event_id") == event_id
        and item["payload"].get("approved") is True
        and item["payload"].get("approval_mode") == "simulated_gold_test_harness"
        and item["payload"].get("is_simulated") is True
    ), None)
    if not approval:
        return None
    return {
        "evidence_id": report_id,
        "record_id": report_id,
        "report_id": report_id,
        "event_id": event_id,
        "document_id": None,
        "text": report["report_text"],
        "archive_status": "not_required_for_event_completion",
        "approval_record_ids": [approval.get("record_id")] if approval.get("record_id") else [],
        "is_simulated": True,
        "execution_engine": "local",
        "source_kind": "simulated_gold_approved_local_report",
    }


def _gold_report_state(
    report_id: str,
    report_record: Mapping[str, Any],
    event_record: Mapping[str, Any],
    children_lookup: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    report = report_record.get("payload")
    event_id = event_record.get("record_id")
    event = event_record.get("payload")
    associations = report.get("associations") if isinstance(report, Mapping) else None
    event_matches = bool(
        isinstance(event, Mapping)
        and event_record.get("record_type") == "event"
        and event_record.get("is_simulated") is True
        and event.get("event_id") == event_id
        and event.get("is_simulated") is True
    )
    record_matches = bool(
        isinstance(report, Mapping)
        and report_record.get("record_id") == report_id
        and report_record.get("record_type") == "report"
        and report_record.get("parent_id") == event_id
        and report_record.get("scenario_id") == event_record.get("scenario_id")
        and report_record.get("is_simulated") is True
        and report_record.get("status") == report.get("status")
        and report.get("report_id") == report_id
        and report.get("is_simulated") is True
        and isinstance(associations, Mapping)
        and associations.get("event_id") == event_id
        and event_matches
    )
    children = children_lookup.get("records", []) if children_lookup.get("status") == "found" else []
    gold_evidence = (
        _gold_report_evidence(report_id, report_record, children, event_record)
        if record_matches and children_lookup.get("status") == "found"
        else None
    )
    local_approved_evidence = None
    if gold_evidence is None and record_matches and children_lookup.get("status") == "found":
        local_approved_evidence = _approved_local_gold_report_evidence(
            report_id, report_record, children, event_record,
        )
        gold_evidence = local_approved_evidence
    approval_records = [
        item for item in children
        if isinstance(item, Mapping) and item.get("record_type") == "approval"
    ]
    report_text_available = bool(
        isinstance(report, Mapping)
        and isinstance(report.get("report_text"), str)
        and report["report_text"].strip()
    )
    approval_details = []
    for item in approval_records:
        payload = item.get("payload")
        approval_details.append({
            "record_id": item.get("record_id"),
            "approval_type": payload.get("approval_type") if isinstance(payload, Mapping) else None,
            "approved": payload.get("approved") if isinstance(payload, Mapping) else None,
            "record_is_simulated": item.get("is_simulated") is True,
            "payload_is_simulated": payload.get("is_simulated") if isinstance(payload, Mapping) else None,
        })
    summary = {
        "report_id": report_id,
        "record_match": "matched" if record_matches else "invalid",
        "status": report_record.get("status"),
        "review_status": report.get("review_status") if isinstance(report, Mapping) else None,
        "archive_status": report.get("archive_status") if isinstance(report, Mapping) else None,
        "approval_record_ids": [item.get("record_id") for item in approval_records],
        "approval_records": approval_details,
        "approval_types": [
            item["payload"].get("approval_type")
            for item in approval_records
            if isinstance(item.get("payload"), Mapping)
        ],
        "is_simulated": report_record.get("is_simulated") is True,
        "payload_is_simulated": report.get("is_simulated") if isinstance(report, Mapping) else None,
        "record_status": report_record.get("status"),
        "report_text_available": report_text_available,
        "evidence_status": (
            "approved_simulated_local_report"
            if local_approved_evidence
            else "simulated_local_archive"
            if gold_evidence
            else "report_text_missing"
            if record_matches and not report_text_available
            else "not_approved_or_archived"
            if record_matches
            else "local_gold_children_unavailable"
            if children_lookup.get("status") == "local_gold_store_unavailable"
            else "invalid_gold_report_record"
        ),
    }
    return summary, gold_evidence


def _gold_event_report_lookup_response(
    query: str,
    context: Mapping[str, Any] | None,
    trace_id: str,
    event_id: str,
    lookup: Mapping[str, Any],
) -> dict[str, Any]:
    record = lookup.get("record")
    if lookup.get("status") == "found" and isinstance(record, Mapping):
        payload = record.get("payload")
        if record.get("record_type") != "event":
            lookup = {"status": "gold_record_type_mismatch", "record": None}
        elif record.get("is_simulated") is not True:
            lookup = {"status": "gold_record_missing_simulation_marker", "record": None}
        elif (
            not isinstance(payload, Mapping)
            or payload.get("event_id") not in (None, event_id)
            or payload.get("is_simulated") is not True
        ):
            lookup = {"status": "gold_record_invalid_payload", "record": None}

    response = _record_lookup_response(
        query, context, trace_id, "event", event_id, "local_gold_store", lookup,
        java_queried=False,
    )
    if lookup.get("status") != "found" or not isinstance(record, Mapping):
        return response

    children_lookup = _read_gold_children(event_id)
    reports = []
    archived_evidence = []
    event_evidence = []
    event_payload = record.get("payload")
    event_trace_id = event_payload.get("trace_id") if isinstance(event_payload, Mapping) else None
    if children_lookup.get("status") == "found":
        for child in children_lookup.get("records", []):
            if not isinstance(child, Mapping):
                continue
            if child.get("record_type") == "rag_retrieval" and isinstance(event_trace_id, str):
                event_evidence.extend(
                    map_persisted_event_evidence(event_id, event_trace_id, child)
                )
                continue
            if child.get("record_type") != "report":
                continue
            report_id = child.get("record_id")
            if not isinstance(report_id, str) or not report_id.strip():
                continue
            report_children = _read_gold_children(report_id)
            summary, archived = _gold_report_state(report_id, child, record, report_children)
            reports.append(summary)
            if archived:
                archived_evidence.append(archived)

    evidence = []
    seen_evidence_ids = set()
    for item in [*event_evidence, *archived_evidence]:
        evidence_id = item.get("evidence_id")
        if isinstance(evidence_id, str) and evidence_id not in seen_evidence_ids:
            seen_evidence_ids.add(evidence_id)
            evidence.append(item)

    response["reports"] = reports
    response["event_id"] = event_id
    response["report_lookup_status"] = children_lookup.get("status")
    response["evidence"] = evidence
    response["evidence_ids"] = [item["evidence_id"] for item in evidence]
    response["trace"][0]["step"] = "local_gold_event_report_lookup"
    response["business_context_source"] = "local_gold_store"
    response["app_name"] = "GeoGuard A1 local Gold event/report lookup"
    response["app_mode"] = "local_gold_event_report_lookup"
    response["dify_status"] = "skipped_local_gold_event_report_lookup"
    response["trace"][0]["report_count"] = len(reports)
    response["trace"][0]["evidence_count"] = len(evidence)
    response["trace"][0]["event_rag_evidence_count"] = len({
        item["evidence_id"] for item in event_evidence
    })
    response["trace"][0]["event_rag_evidence_trace_id"] = event_trace_id
    report_states = [
        {
            "report_id": item["report_id"],
            "status": item["status"],
            "review_status": item["review_status"],
            "archive_status": item["archive_status"],
            "approval_record_ids": item["approval_record_ids"],
            "approval_records": item["approval_records"],
            "approval_types": item["approval_types"],
            "is_simulated": item["is_simulated"],
            "payload_is_simulated": item["payload_is_simulated"],
            "report_text_available": item["report_text_available"],
            "evidence_status": item["evidence_status"],
        }
        for item in reports
    ]
    response["answer"] += (
        " 本地 Gold 事件及关联报告均按模拟记录处理，不代表真实业务记录或正式预警。"
        + (" 关联报告状态：" + json.dumps(report_states, ensure_ascii=False) if report_states else " 未找到关联报告记录。")
    )
    if event_evidence:
        response["answer"] += (
            f" 已回查到 {response['trace'][0]['event_rag_evidence_count']} 条与该事件 Trace "
            "精确关联的 Geo-RAG 证据片段；保留原文定位，属于 Gold 模拟事件上下文。"
        )
    if archived_evidence:
        response["answer"] += " 已归档报告仅作为本地模拟归档返回，不是正式业务证据。"
    else:
        response["answer"] += " 未审核或未归档报告不会作为正式证据返回。"
    return response


def _indexed_approved_report_archive(
    report_id: str,
    retrieval: Any,
    *,
    event_id: str | None = None,
) -> dict[str, Any] | None:
    evidences = retrieval.get("evidences") if isinstance(retrieval, Mapping) else None
    if not isinstance(evidences, list):
        return None

    filename_id = re.sub(r"[^A-Za-z0-9._-]", "-", report_id)
    expected_file_name = f"宜昌GeoGuard复盘报告_{filename_id}.docx"
    evidence_kb_id = YICHANG_KNOWLEDGE_BASES["evidence"]
    by_document: dict[str, list[Mapping[str, Any]]] = {}
    for item in evidences:
        if not isinstance(item, Mapping):
            continue
        document_id = item.get("document_id")
        if (
            item.get("knowledge_base_id") != evidence_kb_id
            or item.get("file_name") != expected_file_name
            or not isinstance(document_id, str)
            or not document_id.strip()
        ):
            continue
        by_document.setdefault(document_id, []).append(item)

    for document_id, chunks in by_document.items():
        combined_text = "\n".join(
            str(item.get("text") or "")
            for item in sorted(
                chunks,
                key=lambda item: (item.get("metadata") or {}).get("chunk_index", 0)
                if isinstance(item.get("metadata"), Mapping)
                else 0,
            )
        )
        metadata = None
        for match in re.finditer(r"```json\s*(\{.*?\})\s*```", combined_text, re.S | re.I):
            try:
                candidate = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if (
                isinstance(candidate, Mapping)
                and candidate.get("report_id") == report_id
                and (event_id is None or candidate.get("event_id") == event_id)
            ):
                metadata = candidate
                break
        if not (
            metadata
            and metadata.get("report_approved") is True
            and metadata.get("archive_approved") is True
            and metadata.get("is_simulated") is False
        ):
            continue

        citations = _citations(chunks)
        if citations:
            return {
                "document_id": document_id,
                "report_id": report_id,
                "event_id": metadata.get("event_id"),
                "evidence": citations,
                "text": "\n\n".join(item["text"] for item in citations),
            }
    return None


async def answer_yichang_query(query: str, context: dict | None = None) -> dict:
    """Answer Yichang knowledge queries and explicit persisted-record lookups."""
    trace_id = f"yqa-{uuid.uuid4().hex}"
    gold_report_match = _DEMO_GOLD_REPORT_ID.search(query)
    report_id = gold_report_match.group(0) if gold_report_match else None
    reference = _business_record_reference(query)
    prefixed_id_match = _PREFIXED_RECORD_ID.search(query)
    archive_report_id = (
        prefixed_id_match.group(0).upper()
        if prefixed_id_match and prefixed_id_match.group("prefix").upper() == "RPT"
        else None
    )
    archive_report_lookup = bool(
        archive_report_id
        and (
            _REPORT_ARCHIVE_LOOKUP.search(query)
            or not _REPORT_STATUS_LOOKUP.search(query)
        )
    )
    archive_event_id = (
        reference["record_id"]
        if reference
        and reference["source"] == "local_gold_store"
        and reference["record_type"] == "event"
        else None
    )
    business_lookup = bool(_BUSINESS_LOOKUP.search(query)) and report_id is None and archive_event_id is None
    business_context = _public_context(context) if isinstance(context, Mapping) else None
    business_context = business_context if business_context else None
    trace = [{
        "trace_id": trace_id,
        "step": (
            "local_gold_report_lookup"
            if report_id
            else "local_gold_event_report_lookup"
            if archive_event_id
            else "local_report_archive_lookup"
            if archive_report_lookup
            else "yichang_rag_retrieval"
        ),
        "status": "running",
        **({} if report_id or archive_report_lookup or archive_event_id else {"knowledge_base_ids": list(YICHANG_KB_IDS)}),
    }]

    if report_id:
        report_lookup = _read_gold_record(report_id)
        report_record = report_lookup.get("record")
        children_lookup = {"status": "not_found", "records": []}
        event_record = None
        lookup_status = "unavailable" if report_lookup.get("status") == "local_gold_store_unavailable" else "completed"
        if lookup_status != "unavailable" and isinstance(report_record, Mapping):
            children_lookup = _read_gold_children(report_id)
            if children_lookup.get("status") == "local_gold_store_unavailable":
                lookup_status = "unavailable"
            event_id = report_record.get("parent_id")
            if lookup_status != "unavailable" and isinstance(event_id, str) and event_id:
                event_lookup = _read_gold_record(event_id)
                if event_lookup.get("status") == "local_gold_store_unavailable":
                    lookup_status = "unavailable"
                else:
                    event_record = event_lookup.get("record")

        report_record = report_record if isinstance(report_record, Mapping) else {}
        event_record = event_record if isinstance(event_record, Mapping) else {}
        gold_children = children_lookup.get("records", [])
        report_state, gold_evidence = _gold_report_state(
            report_id, report_record, event_record, children_lookup,
        )
        report_id_match = "matched" if gold_evidence else ("unavailable" if lookup_status == "unavailable" else "not_found")
        report_record_match = (
            report_state["record_match"]
            if report_lookup.get("status") == "found"
            else "unavailable" if lookup_status == "unavailable" else "not_found"
        )
        evidence = [gold_evidence] if gold_evidence else []
        if lookup_status == "unavailable":
            trace[0].update({"status": "unavailable"})
        else:
            trace[0].update({"status": "completed", "evidence_count": len(evidence)})
        trace[0].update({
            "report_id": report_id,
            "report_id_match": report_id_match,
            "candidate_evidence_count": sum(
                isinstance(child, Mapping) and child.get("record_type") == "archive"
                for child in gold_children
            ),
            "report_record_match": report_record_match,
            "execution_engine": "local",
            "is_simulated": report_record.get("is_simulated") is True if report_lookup.get("status") == "found" else None,
        })
        skipped_status = "skipped_local_gold_report_lookup" if gold_evidence else f"skipped_report_evidence_{report_id_match}"
        trace.extend([
            {"trace_id": trace_id, "step": "dify_a1_chatflow", "status": skipped_status, "execution_engine": "local"},
            {"trace_id": trace_id, "step": "llm_answer", "status": skipped_status},
            {"trace_id": trace_id, "step": "java_business_lookup", "status": "not_queried"},
        ])
        answer = (
            (
                f"本地 Gold 模拟审批通过报告原文（事件完成不要求单独归档）：\n{gold_evidence['text']}"
                if gold_evidence and gold_evidence.get("source_kind") == "simulated_gold_approved_local_report"
                else f"本地 Gold 模拟归档报告原文：\n{gold_evidence['text']}"
            )
            if gold_evidence
            else (
                f"本地 Gold 归档存储当前不可用，无法核对报告 ID {report_id}；本次未生成报告回答。"
                if lookup_status == "unavailable"
                else (
                    f"已找到本地 Gold 模拟报告记录 {report_id}；状态：{report_state['status']}，审核状态："
                    f"{report_state['review_status']}，归档状态：{report_state['archive_status']}。报告正文缺失，"
                    "未返回报告内容，不作为正式业务证据或预警依据。"
                    if report_state["evidence_status"] == "report_text_missing"
                    else (
                    f"已找到本地 Gold 模拟报告记录 {report_id}；状态：{report_state['status']}，审核状态："
                    f"{report_state['review_status']}，归档状态：{report_state['archive_status']}。"
                    "该记录未满足可引用归档条件，不作为正式业务证据或预警依据。"
                    if report_record_match == "matched"
                    else f"未找到包含完整报告 ID {report_id} 的本地 Gold 模拟归档证据，本次未使用其他报告内容作答。"
                    )
                )
            )
        )
        return {
            "status": "completed" if gold_evidence else f"report_evidence_{report_id_match}",
            "answer": answer,
            "region": _region(query, context),
            "evidence": evidence,
            "evidence_ids": [item["evidence_id"] for item in evidence],
            "report_id": report_id,
            "report_id_match": report_id_match,
            "report_record_match": report_record_match,
            "report_status": report_state["status"],
            "review_status": report_state["review_status"],
            "archive_status": report_state["archive_status"],
            "approval_record_ids": report_state["approval_record_ids"],
            "approval_records": report_state["approval_records"],
            "approval_types": report_state["approval_types"],
            "payload_is_simulated": report_state["payload_is_simulated"],
            "report_text_available": report_state["report_text_available"],
            "report_state": report_state,
            "business_lookup": False,
            "business_status": "not_applicable",
            "business_context": None,
            "business_context_source": (
                gold_evidence.get("source_kind") if gold_evidence
                else "local_gold_store" if report_lookup.get("status") == "found"
                else "none"
            ),
            "is_simulated": report_record.get("is_simulated") is True if report_lookup.get("status") == "found" else None,
            "java_queried": False,
            "execution_engine": "local",
            "app_name": "GeoGuard A1 local Gold archive",
            "app_mode": "local_gold_archive",
            "dify_status": skipped_status,
            "outputs": {},
            "parsed_output": None,
            "conversation_id": context.get("conversation_id") if isinstance(context, Mapping) else None,
            "task_id": None,
            "workflow_run_id": None,
            "duration_ms": 0,
            "trace_id": trace_id,
            "error": None,
            "trace": trace,
        }

    if archive_event_id:
        event_lookup = _read_gold_record(archive_event_id)
        return _gold_event_report_lookup_response(
            query, context, trace_id, archive_event_id, event_lookup,
        )

    if archive_report_lookup and archive_report_id:
        try:
            retrieval = await retrieve_from_rag(
                archive_report_id,
                top_k=20,
                knowledge_base_ids=(YICHANG_KNOWLEDGE_BASES["evidence"],),
            )
            archived_report = _indexed_approved_report_archive(archive_report_id, retrieval)
            lookup_error = None
        except Exception as exc:
            archived_report = None
            lookup_error = type(exc).__name__

        verified = isinstance(archived_report, Mapping)
        unavailable_status = "skipped_verified_report_archive_lookup" if verified else "skipped_report_archive_unavailable"
        trace[0].update({
            "status": "completed" if verified else "unavailable",
            "report_id": archived_report.get("report_id") if verified else archive_report_id,
            "report_id_match": "matched" if verified else "not_locally_verifiable",
            "report_archive_status": "indexed" if verified else "unavailable",
            "reason": None if verified else "no_verified_indexed_report_match",
            "execution_engine": "geo-rag",
            "evidence_count": len(archived_report["evidence"]) if verified else 0,
            **({"document_id": archived_report["document_id"]} if verified else {}),
            **({"error_type": lookup_error} if lookup_error else {}),
        })
        trace.extend([
            {"trace_id": trace_id, "step": "dify_a1_chatflow", "status": unavailable_status, "execution_engine": "local"},
            {"trace_id": trace_id, "step": "llm_answer", "status": unavailable_status},
            {"trace_id": trace_id, "step": "java_business_lookup", "status": "not_queried"},
        ])
        if verified:
            report_query_answer = (
                f"已从 Geo-RAG 宜昌证据库检索到报告 {archive_report_id} 的已索引审批归档证据片段：\n"
                f"{archived_report['text']}"
            )
        else:
            report_query_answer = (
                f"未能从 Geo-RAG 宜昌证据库取得同时匹配报告 ID {archive_report_id}、报告审批、"
                "归档审批和非模拟标记的可引用已索引证据；因此无法确认该报告已批准并实际归档，也不返回报告事实。"
            )
        return {
            "status": "completed" if verified else "report_archive_unavailable",
            "answer": report_query_answer,
            "region": _region(query, context),
            "evidence": archived_report["evidence"] if verified else [],
            "evidence_ids": [item["evidence_id"] for item in archived_report["evidence"]] if verified else [],
            "report_id": archived_report.get("report_id") if verified else archive_report_id,
            "report_id_match": "matched" if verified else "not_locally_verifiable",
            "report_archive_status": "indexed" if verified else "unavailable",
            "document_id": archived_report["document_id"] if verified else None,
            "business_lookup": False,
            "business_status": "not_applicable",
            "business_context": None,
            "business_context_source": "geo_rag_indexed_report_archive" if verified else "none",
            "is_simulated": False if verified else None,
            "java_queried": False,
            "execution_engine": "geo-rag",
            "app_name": "GeoGuard A1 Geo-RAG report archive lookup",
            "app_mode": "geo_rag_report_archive_lookup",
            "dify_status": unavailable_status,
            "outputs": {},
            "parsed_output": None,
            "conversation_id": context.get("conversation_id") if isinstance(context, Mapping) else None,
            "task_id": None,
            "workflow_run_id": None,
            "duration_ms": 0,
            "trace_id": trace_id,
            "error": None,
            "trace": trace,
        }

    if reference:
        record_type = reference["record_type"]
        record_id = reference["record_id"]
        source = reference["source"]
        if source == "local_gold_store":
            lookup = _read_gold_record(record_id)
            record = lookup.get("record")
            if lookup.get("status") == "found" and isinstance(record, Mapping):
                if record.get("record_type") != record_type:
                    lookup = {"status": "gold_record_type_mismatch", "record": None}
                elif record.get("is_simulated") is not True:
                    lookup = {"status": "gold_record_missing_simulation_marker", "record": None}
            return _record_lookup_response(
                query, context, trace_id, record_type, record_id, source, lookup, java_queried=False,
            )

        backend_record_id = reference.get("backend_record_id", record_id)
        if not backend_record_id.isdigit() or int(backend_record_id) <= 0:
            lookup = {"status": "invalid_java_record_id", "record": None}
            java_queried = False
        else:
            try:
                lookup = (
                    await _lookup_java_event_record(backend_record_id)
                    if record_type == "event"
                    else await lookup_business_record(record_type, backend_record_id)
                )
            except Exception as exc:
                lookup = {"status": "java_api_unavailable", "record": None, "error_type": type(exc).__name__}
            java_queried = lookup.get("status") != "java_api_not_configured"

        if lookup.get("status") == "java_api_not_configured" and business_context:
            pass
        else:
            return _record_lookup_response(
                query,
                context,
                trace_id,
                record_type,
                record_id,
                source,
                lookup,
                java_queried=java_queried,
                backend_record_id=backend_record_id,
            )

    try:
        retrieval_top_k = 30 if _EXPLICIT_REPORT_ID.search(query) else 8
        retrieval = await retrieve_yichang(query, top_k=retrieval_top_k)
    except Exception as exc:
        trace[0].update({"status": "unavailable", "error_type": type(exc).__name__})
        retrieval = None

    raw_evidence = retrieval.get("evidences") if isinstance(retrieval, Mapping) else None
    candidates = _citations([
        item for item in raw_evidence
        if isinstance(item, Mapping) and not is_simulated_evidence(item)
    ]) if isinstance(raw_evidence, list) else []
    evidence = candidates
    if retrieval is not None:
        trace[0].update({"status": "completed", "evidence_count": len(evidence)})

    if business_lookup:
        simulated = _is_simulated_context(context) if business_context else False
        trace.append({
            "trace_id": trace_id,
            "step": "dify_a1_chatflow",
            "status": "skipped_business_lookup",
            "execution_engine": "local",
        })
        if business_context:
            business_status = "caller_context_used_not_java_live"
            answer_status = "business_context_only"
            provenance = "simulated_gold" if simulated else "caller_supplied_unverified"
            qualifier = (
                "以下仅整理调用方提供的 Gold 模拟记录；它不是已核实的真实业务记录：\n"
                if simulated
                else "以下仅整理调用方提供的业务上下文；未实时查询 Java 业务库，内容未经本次独立核实：\n"
            )
            answer = qualifier + json.dumps(business_context, ensure_ascii=False, sort_keys=True)
            trace.append({"trace_id": trace_id, "step": "llm_answer", "status": "skipped_business_context_only"})
        else:
            business_status = "not_queried_context_required"
            answer_status = "business_context_required"
            provenance = "none"
            answer = "该事件、任务或报告查询需要调用方显式提供业务上下文。本次未查询 Java 业务库，不能回答具体记录或状态。"
            trace.append({"trace_id": trace_id, "step": "llm_answer", "status": "skipped_business_context_required"})
        trace.append({"trace_id": trace_id, "step": "java_business_lookup", "status": "not_queried"})
        return {
            "status": answer_status,
            "answer": answer,
            "region": _region(query, context),
            "evidence": evidence,
            "evidence_ids": [item["evidence_id"] for item in evidence],
            "business_lookup": True,
            "business_status": business_status,
            "business_context": business_context,
            "business_context_source": provenance,
            "is_simulated": simulated,
            "java_queried": False,
            "execution_engine": "local",
            "app_name": "GeoGuard A1 business-context gate",
            "app_mode": "local_context_gate",
            "dify_status": "skipped_business_lookup",
            "outputs": {},
            "parsed_output": None,
            "conversation_id": context.get("conversation_id") if isinstance(context, Mapping) else None,
            "task_id": None,
            "workflow_run_id": None,
            "duration_ms": 0,
            "trace_id": trace_id,
            "error": None,
            "trace": trace,
        }

    dify_result = await run_a1_chatflow(query, evidence, context)
    if dify_result and dify_result.get("execution_engine") == "dify":
        answer_status = str(dify_result.get("status") or "unknown")
        answer = dify_result.get("answer") or ""
        if answer_status == "error":
            answer = "Dify A1 流程调用失败，未生成回答。"
        elif not answer:
            answer_status = "empty_response"
            answer = "Dify A1 流程未返回可用回答。"
        unsupported_citations = _unretrieved_citations(answer, dify_result.get("parsed_output"), evidence)
        if answer_status not in {"error", "empty_response"} and unsupported_citations:
            answer_status = "unsupported_evidence_citation"
            answer = "Dify A1 返回了本次 Geo-RAG 检索未包含的 evidence_id，回答已抑制。"
        trace.append({
            "trace_id": dify_result.get("trace_id") or trace_id,
            "step": "dify_a1_chatflow",
            "status": dify_result.get("status", "unknown"),
            "app_name": dify_result.get("app_name"),
            "app_mode": dify_result.get("app_mode"),
            "task_id": dify_result.get("task_id"),
            "message_id": dify_result.get("message_id"),
            "workflow_run_id": dify_result.get("workflow_run_id"),
        })
        trace.append({"trace_id": trace_id, "step": "java_business_lookup", "status": "not_queried"})
        return {
            "status": answer_status,
            "answer": answer,
            "region": _region(query, context),
            "evidence": evidence,
            "evidence_ids": [item["evidence_id"] for item in evidence],
            "business_lookup": business_lookup,
            "business_status": "not_applicable",
            "business_context": None,
            "business_context_source": "none",
            "is_simulated": False,
            "java_queried": None,
            "execution_engine": dify_result.get("execution_engine"),
            "app_name": dify_result.get("app_name"),
            "app_mode": dify_result.get("app_mode"),
            "outputs": {} if unsupported_citations else dify_result.get("outputs", {}),
            "parsed_output": None if unsupported_citations else dify_result.get("parsed_output"),
            "conversation_id": dify_result.get("conversation_id"),
            "message_id": dify_result.get("message_id"),
            "task_id": dify_result.get("task_id"),
            "workflow_run_id": dify_result.get("workflow_run_id"),
            "duration_ms": dify_result.get("duration_ms"),
            "trace_id": dify_result.get("trace_id"),
            "error": "Dify cited an evidence_id absent from this retrieval." if unsupported_citations else dify_result.get("error"),
            "trace": trace,
        }

    dify_status = dify_result.get("status") if dify_result else "not_configured"
    trace.append({
        "trace_id": dify_result.get("trace_id", trace_id) if dify_result else trace_id,
        "step": "dify_a1_chatflow",
        "status": dify_status,
    })

    if retrieval is None:
        business_status = "not_applicable"
        answer_status = "rag_unavailable"
        answer = "宜昌知识库检索当前不可用，未生成基于知识库的回答。"
        trace.append({"trace_id": trace_id, "step": "llm_answer", "status": "skipped_rag_unavailable"})
    else:
        business_status = "not_applicable"
        try:
            generated = await answer_with_evidence(query, evidence)
            answer_status = generated.get("status", "unknown")
            answer = generated.get("answer", "")
            if _unretrieved_citations(answer, generated, evidence):
                answer_status = "unsupported_evidence_citation"
                answer = "本地回答引用了本次 Geo-RAG 检索未包含的 evidence_id，回答已抑制。"
        except Exception as exc:
            answer_status = "llm_unavailable"
            answer = "宜昌知识库已返回证据，但回答生成服务当前不可用。"
            trace.append({"trace_id": trace_id, "step": "llm_answer", "status": "unavailable",
                          "error_type": type(exc).__name__})
        else:
            trace.append({"trace_id": trace_id, "step": "llm_answer", "status": answer_status})

    trace.append({"trace_id": trace_id, "step": "java_business_lookup", "status": "not_queried"})
    return {
        "status": answer_status,
        "answer": answer,
        "region": _region(query, context),
        "evidence": evidence,
        "evidence_ids": [item["evidence_id"] for item in evidence],
        "business_lookup": False,
        "business_status": "not_applicable",
        "business_context": None,
        "business_context_source": "none",
        "is_simulated": False,
        "java_queried": False,
        "execution_engine": "local",
        "app_name": "GeoGuard A1 local RAG",
        "app_mode": "local_rag",
        "dify_status": dify_status,
        "outputs": {},
        "parsed_output": None,
        "conversation_id": context.get("conversation_id") if isinstance(context, Mapping) else None,
        "task_id": None,
        "workflow_run_id": None,
        "duration_ms": 0,
        "trace_id": trace_id,
        "error": None,
        "trace": trace,
    }
