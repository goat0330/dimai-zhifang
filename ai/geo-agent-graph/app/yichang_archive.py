"""Route reviewed Yichang reports through DOCX archival and A1 readback."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .rag_archive import archive_approved_report
from .rag_client import retrieve_yichang


def _is_simulated_source(record: Mapping[str, Any]) -> bool:
    for key in ("is_simulated", "isSimulated"):
        simulated = record.get(key)
        if simulated is True or (
            isinstance(simulated, str) and simulated.strip().casefold() in {"true", "1", "yes"}
        ):
            return True
    for key in ("simulation_status", "simulationStatus", "source_kind", "sourceKind", "source_type", "sourceType"):
        value = record.get(key)
        if isinstance(value, str) and value.strip().casefold() in {"simulated", "simulation"}:
            return True
    for key in ("data_source", "dataSource"):
        data_source = record.get(key)
        if isinstance(data_source, str):
            value = data_source.strip().casefold()
            if value.startswith("local_gold_fixture") or value in {"gold-fixture", "gold_fixture"}:
                return True
    return False


def is_simulated_report(report: Mapping[str, Any]) -> bool:
    if _is_simulated_source(report):
        return True
    source_metadata = report.get("source_metadata")
    if isinstance(source_metadata, Mapping) and _is_simulated_source(source_metadata):
        return True
    associations = report.get("associations")
    if isinstance(associations, Mapping):
        for key in ("event_id", "new_report_id"):
            value = associations.get(key)
            if isinstance(value, str) and value.startswith("DEMO-GOLD-"):
                return True
    report_id = report.get("report_id", report.get("reportId"))
    if isinstance(report_id, str) and report_id.startswith("DEMO-GOLD-"):
        return True

    source_facts = report.get("source_facts")
    if not isinstance(source_facts, Mapping):
        return False
    for key in ("event", "risk_review", "tasks", "feedback", "attachments"):
        records = source_facts.get(key)
        if isinstance(records, Mapping):
            records = [records]
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, Mapping):
                continue
            if _is_simulated_source(record):
                return True
    return False


def _report_id(report: Mapping[str, Any]) -> str | None:
    value = report.get("report_id", report.get("reportId"))
    associations = report.get("associations")
    if value in (None, "") and isinstance(associations, Mapping):
        value = associations.get("new_report_id")
        if value in (None, "", "unknown"):
            existing = associations.get("existing_report_ids")
            value = existing[0] if isinstance(existing, list) and len(existing) == 1 else None
    return str(value) if value not in (None, "", "unknown") else None


async def archive_yichang_report(
    report: dict[str, Any],
    *,
    report_approved: bool,
    archive_approved: bool,
) -> dict[str, Any]:
    """Archive a real approved report, then verify its evidence through A1 retrieval."""
    if report_approved is not True or archive_approved is not True:
        return {"status": "awaiting_report_and_archive_approval", "document_id": None}
    if is_simulated_report(report):
        return {
            "status": "simulated_report_requires_local_gold_archive",
            "document_id": None,
        }

    result = await archive_approved_report(
        report,
        report_approved=report_approved,
        archive_approved=archive_approved,
    )
    if result.get("status") not in {"indexed", "added", "submitted"}:
        return result

    report_id = _report_id(report)
    try:
        retrieval = await retrieve_yichang(report_id or "", top_k=5)
        evidences = retrieval.get("evidences", []) if isinstance(retrieval, Mapping) else []
        expected_file_name = result.get("file_name")
        expected_markers = (
            f'"report_id": {json.dumps(report_id, ensure_ascii=False)}',
            '"report_approved": true',
            '"archive_approved": true',
            '"is_simulated": false',
        )
        matched = [
            item for item in evidences
            if isinstance(item, Mapping)
            and expected_file_name
            and item.get("file_name") == expected_file_name
            and isinstance(item.get("text"), str)
            and all(marker in item["text"] for marker in expected_markers)
        ]
        verification = {
            "status": "retrieved" if matched else ("not_found" if result.get("status") == "indexed" else "index_pending"),
            "execution_engine": "geo-rag",
            "evidence_count": len(matched),
            "evidence_ids": [item.get("evidence_id") or item.get("document_id") for item in matched],
        }
    except Exception as exc:
        verification = {
            "status": f"unavailable:{type(exc).__name__}",
            "execution_engine": "geo-rag",
            "evidence_ids": [],
        }
    return {**result, "a1_verification": verification}
