"""Input and output adaptation for the optional legacy A1 Dify Chatflow."""

import html
import json
import re
from collections.abc import Mapping
from typing import Any

from ..dify_client import dify_configured, run_agent
from ..p6_client import lookup_dynamic_slope_unit


A1_AGENT_ID = "A1"
_COMMAND_OUTPUT = re.compile(r"^\s*\(@(?P<command>[\w-]+)\)\s*(?P<body>\{.*\})\s*$", re.S)
_GOLD_REPORT_SOURCE_ID = re.compile(r"DEMO-GOLD-REPORT-[A-Z0-9][A-Z0-9_-]*", re.I)
_GOLD_REPORT_ID = re.compile(r"DEMO-GOLD-REPORT-[A-Z0-9][A-Z0-9_-]*", re.I)
_REPORT_ID_IN_QUERY = re.compile(r"\b(?:DEMO-GOLD-REPORT|RPT)-[A-Z0-9][A-Z0-9_-]*\b", re.I)
_REPORT_ID_ASSIGNMENT = re.compile(r"(?:report[_ ]id|报告\s*ID)\s*[:=：]\s*([A-Za-z0-9][A-Za-z0-9_.:-]*)", re.I)
_GOLD_EVENT_ID_IN_QUERY = re.compile(r"\bDEMO-GOLD-EVENT-[A-Z0-9][A-Z0-9_-]*\b", re.I)
_GOLD_TRACE_ID_IN_QUERY = re.compile(r"\bDEMO-GOLD-TRACE-[A-Z0-9][A-Z0-9_-]*\b", re.I)
_EVENT_ID_IN_QUERY = re.compile(r"\b(?:DEMO-GOLD-EVENT|EVT)-[A-Z0-9][A-Z0-9_-]*\b", re.I)
_TRACE_ID_IN_QUERY = re.compile(r"\b(?:DEMO-GOLD-TRACE|TRACE)-[A-Z0-9][A-Z0-9_-]*\b", re.I)
_EVENT_ID_ASSIGNMENT = re.compile(r"(?:event[_ ]id|事件\s*ID)\s*[:=：]\s*([A-Za-z0-9][A-Za-z0-9_.:-]*)", re.I)
_TRACE_ID_ASSIGNMENT = re.compile(r"(?:trace[_ ]id|追踪\s*ID)\s*[:=：]\s*([A-Za-z0-9][A-Za-z0-9_.:-]*)", re.I)
_REPORT_LOOKUP_INTENT = re.compile(r"报告|复盘|调查|归档|report|archive|review|investigat", re.I)
_REPORT_STATUS_LOOKUP_INTENT = re.compile(r"状态|进度|status", re.I)
_GOLD_REPORT_JSON = re.compile(r"```json\s*(\{.*?\})\s*```", re.S | re.I)
_YICHANG_EVIDENCE_KB_ID = "KB-b31a881b2b49"
_YCSU_ID = re.compile(r"(?<![A-Za-z0-9_])YCSU_[A-Za-z0-9_-]+(?![A-Za-z0-9_-])", re.I)
_HR_REQUEST = re.compile(
    r"(?<![A-Za-z])H\s*(?:/|、|,|和|与|及|&|\band\b)\s*R(?![A-Za-z])",
    re.I,
)
_P6_SCENARIO_IN_QUERY = re.compile(
    r"(?<![A-Za-z0-9_])(?:p6_)?scenario\s*[:=]\s*(dynamic_08|dynamic|forecast)\b", re.I,
)
_P6_SNAPSHOT_IN_QUERY = re.compile(
    r"(?<![A-Za-z0-9_])(?:p6_)?snapshot_id\s*[:=]\s*([A-Za-z0-9_.:-]+)", re.I,
)
_P6_DYNAMIC_08_INTENT = re.compile(
    r"(?<![A-Za-z0-9_])dynamic_08(?![A-Za-z0-9_])|(?:(?:每日|每天)\s*)?08\s*时(?:\s*滚动)?",
    re.I,
)
_P6_SCENARIOS = {"dynamic", "forecast", "dynamic_08"}
_P6_SCENARIO_FIELDS = {
    "dynamic": ("h_dynamic_grade", "h_dynamic_score", "r_dynamic_grade", "r_dynamic_score"),
    "forecast": ("h_forecast_grade", "h_forecast_score", "r_forecast_grade", "r_forecast_score"),
    "dynamic_08": (
        "h_dynamic_08_grade", "h_dynamic_08_score", "r_dynamic_08_grade", "r_dynamic_08_score",
    ),
}
_EVIDENCE_FIELDS = (
    "evidence_id",
    "report_id",
    "event_id",
    "trace_id",
    "report_approved",
    "archive_approved",
    "approval_mode",
    "review_status",
    "knowledge_base_id",
    "knowledge_base_label",
    "document_id",
    "chunk_id",
    "file_name",
    "archive_file_name",
    "archive_status",
    "page",
    "source_spans",
    "text",
    "report_body",
    "evidence_repository",
    "record_status",
    "live_status",
    "is_simulated",
    "source_kind",
    "data_source",
)
_CHATFLOW_EVIDENCE_LIMIT = 4
_CHATFLOW_EVIDENCE_TEXT_LIMIT = 600


def _compact_chatflow_evidence(item: Mapping[str, Any]) -> dict[str, Any]:
    row = {
        key: item[key]
        for key in _EVIDENCE_FIELDS
        if key in item and key not in {"source_spans", "text", "report_body"}
    }
    spans = item.get("source_spans")
    if isinstance(spans, list):
        source_pages = list(dict.fromkeys(
            span.get("page") for span in spans
            if isinstance(span, Mapping) and span.get("page") is not None
        ))
        row["source_spans"] = [
            {
                key: span[key]
                for key in ("block_id", "page", "bbox")
                if key in span
            }
            for span in spans[:1]
            if isinstance(span, Mapping)
        ]
        row["source_pages"] = source_pages
        row["source_span_count"] = len(spans)
    for key in ("text", "report_body"):
        value = item.get(key)
        if isinstance(value, str):
            row[key] = value[:_CHATFLOW_EVIDENCE_TEXT_LIMIT]
            if len(value) > _CHATFLOW_EVIDENCE_TEXT_LIMIT:
                row[f"{key}_truncated"] = True
    row["source_provenance"] = _source_provenance(item)
    return row


def map_persisted_event_evidence(
    event_id: str,
    trace_id: str,
    retrieval_record: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Map evidence only from a completed, simulated RAG record for this exact event and trace."""
    if not isinstance(event_id, str) or not event_id.strip():
        return []
    if not isinstance(trace_id, str) or not trace_id.strip():
        return []
    if not isinstance(retrieval_record, Mapping):
        return []

    payload = retrieval_record.get("payload")
    if (
        retrieval_record.get("record_type") != "rag_retrieval"
        or retrieval_record.get("parent_id") != event_id
        or retrieval_record.get("status") != "completed"
        or retrieval_record.get("is_simulated") is not True
        or not isinstance(payload, Mapping)
        or payload.get("event_id") != event_id
        or payload.get("trace_id") != trace_id
        or payload.get("is_simulated") is not True
    ):
        return []

    evidence_items = payload.get("evidences")
    if not isinstance(evidence_items, list):
        evidence_items = payload.get("evidence")
    if not isinstance(evidence_items, list):
        return []

    mapped_evidence = []
    for item in evidence_items:
        if not isinstance(item, Mapping):
            continue
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            continue
        if item.get("event_id") not in (None, event_id) or item.get("trace_id") not in (None, trace_id):
            continue
        if _GOLD_REPORT_SOURCE_ID.search(str(item.get("report_id") or "")):
            continue
        if _GOLD_REPORT_SOURCE_ID.search(str(item.get("file_name") or "")):
            continue
        mapped = {key: item[key] for key in _EVIDENCE_FIELDS if key in item}
        mapped["event_id"] = event_id
        mapped["trace_id"] = trace_id
        mapped_evidence.append(mapped)
    return mapped_evidence


def _non_general_report_evidence_item(item: Mapping[str, Any]) -> bool:
    gold_report = any(
        _GOLD_REPORT_SOURCE_ID.search(str(item.get(key) or ""))
        for key in ("report_id", "file_name", "text")
    )
    source_kind = str(item.get("source_kind") or "").casefold()
    archive_report = (
        str(item.get("file_name") or "").startswith("宜昌GeoGuard复盘报告_")
        or bool(item.get("report_id"))
    )
    simulated_report = archive_report and (
        item.get("is_simulated") is True
        or "simulated" in source_kind
        or "gold" in source_kind
    )
    return gold_report or simulated_report


def _report_chunk_order(item: Mapping[str, Any]) -> tuple[int, int | str]:
    metadata = item.get("metadata")
    index = metadata.get("chunk_index", 0) if isinstance(metadata, Mapping) else 0
    try:
        return (0, int(index))
    except (TypeError, ValueError):
        return (1, str(index))


def _report_body_snippet(text: str) -> str:
    body = text
    for marker in ("## 来源关联", "## 结构化来源数据", "结构化来源数据：", "结构化来源数据:"):
        body = body.split(marker, 1)[0]
    body = re.sub(r"^\s*#[^\r\n]*(?:\r?\n)+", "", body, count=1)
    body = re.sub(r"^\s*【Gold 模拟数据】[^\r\n]*(?:\r?\n)+", "", body, count=1)
    body = body.strip()
    if body == "待补充应急调查报告":
        return ""
    return body


def _report_metadata_candidates(text: str) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    decoder = json.JSONDecoder()
    for match in _GOLD_REPORT_JSON.finditer(text):
        try:
            candidate = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, Mapping):
            parsed = dict(candidate)
            candidates[json.dumps(parsed, sort_keys=True, ensure_ascii=False, default=str)] = parsed
    for marker in re.finditer(r"结构化来源数据\s*[:：]?", text):
        start = text.find("{", marker.end())
        if start < 0:
            continue
        try:
            candidate, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, Mapping):
            parsed = dict(candidate)
            candidates[json.dumps(parsed, sort_keys=True, ensure_ascii=False, default=str)] = parsed
    return list(candidates.values())


def _has_report_body(text: str, metadata: Mapping[str, Any]) -> bool:
    body = _report_body_snippet(text)
    if not body or body == "待补充应急调查报告":
        return False
    if "report_text" in metadata:
        report_text = metadata.get("report_text")
        if (
            not isinstance(report_text, str)
            or not report_text.strip()
            or report_text.strip() == "待补充应急调查报告"
        ):
            return False
    return True


def _normalize_report_body_text(text: str) -> str:
    text = html.unescape(text)
    text = text.translate(str.maketrans({"（": "(", "）": ")", "：": ":", "；": ";", "，": ",", "。": ".", "、": ","}))
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|>])", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s{0,3}>\s?", "", text)
    text = re.sub(r"(?m)^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$", "", text)
    text = re.sub(r"(?m)^[ \t]{0,3}[·•][ \t]*", "", text)
    text = re.sub(r"(?m)^\s{0,3}(?:[-+*]|\d+[.)])\s+", "", text)
    text = re.sub(r"`{1,3}|\*{1,3}", "", text)
    return re.sub(r"[\s|\\]+", "", text)


def _report_body_anchor(report_text: Any) -> str:
    if not isinstance(report_text, str) or not report_text.strip():
        return ""

    source_headings = {
        "来源关联", "结构化来源数据", "结构化证据与关联标识", "关联标识",
    }
    lines = []
    in_status_block = False
    skipped_title = False
    for line in report_text.splitlines():
        heading = re.match(r"^\s{0,3}(#{1,6})\s*(.*?)\s*#*\s*$", line)
        if heading:
            heading_text = heading.group(2).strip()
            if heading_text == "报告状态":
                in_status_block = True
                continue
            if in_status_block:
                in_status_block = False
            if heading_text in source_headings:
                break
            if len(heading.group(1)) == 1 and not skipped_title:
                skipped_title = True
                continue
        elif in_status_block:
            continue

        plain_line = html.unescape(line).strip()
        if plain_line.startswith("【Gold 模拟数据】") or re.match(
            r"^>\s*(?:正文生成|生成方式|数据来源|模拟状态)\s*[:：]", plain_line,
        ):
            continue
        lines.append(line)

    sections: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        heading = re.match(r"^\s{0,3}#{1,6}\s*(.*?)\s*#*\s*$", line)
        if not heading:
            continue
        next_heading = next((
            position for position in range(index + 1, len(lines))
            if re.match(r"^\s{0,3}#{1,6}\s*", lines[position])
        ), len(lines))
        body = _normalize_report_body_text("\n".join(lines[index + 1:next_heading]))
        if body:
            sections.append((heading.group(1).strip(), body))

    preferred = next((
        body for heading, body in sections
        if re.search(r"(?:^|[、.．])事件与资料概况$", heading)
    ), "")
    candidates = ([preferred] if preferred else []) + [
        body for heading, body in sections if body != preferred
    ]
    for candidate in candidates:
        if len(candidate) >= 60:
            return candidate[:80]

    body_without_headings = _normalize_report_body_text("\n".join(
        line for line in lines
        if not re.match(r"^\s{0,3}#{1,6}\s*", line)
    ))
    return body_without_headings[:80] if len(body_without_headings) >= 60 else ""


def _has_located_report_body_anchor(
    item: Mapping[str, Any],
    document_id: str,
    report_text: Any,
) -> bool:
    source_spans = item.get("source_spans")
    text = item.get("text")
    body_anchor = _report_body_anchor(report_text)
    return bool(
        body_anchor
        and item.get("document_id") == document_id
        and isinstance(item.get("evidence_id"), str)
        and item["evidence_id"].strip()
        and isinstance(item.get("chunk_id"), str)
        and item["chunk_id"].strip()
        and isinstance(item.get("file_name"), str)
        and isinstance(text, str)
        and text.strip()
        and isinstance(source_spans, list)
        and any(isinstance(span, Mapping) for span in source_spans)
        and body_anchor in _normalize_report_body_text(text)
    )


def _verified_gold_archive_binding(
    report_id: str,
    archive: Mapping[str, Any] | None,
    expected_file_name: str,
) -> bool:
    accepted_file_names = {expected_file_name}
    if expected_file_name.endswith(".docx"):
        accepted_file_names.add(expected_file_name[:-5] + "__indexed.docx")
    return bool(
        isinstance(archive, Mapping)
        and _GOLD_REPORT_ID.fullmatch(report_id)
        and archive.get("report_id") == report_id
        and archive.get("file_name") in accepted_file_names
        and isinstance(archive.get("document_id"), str)
        and archive.get("document_id", "").strip()
        and archive.get("report_approved") is True
        and archive.get("archive_approved") is True
        and archive.get("approval_mode") in {"human_reviewer", "simulated_gold_test_harness"}
        and archive.get("review_status") == "approved"
        and archive.get("is_simulated") is True
        and isinstance(archive.get("report_text"), str)
        and archive.get("report_text", "").strip()
        and archive.get("report_text", "").strip() != "待补充应急调查报告"
    )


def map_verified_gold_report_evidence(
    report_id: str,
    evidence_items: list[dict[str, Any]] | None,
    *,
    expected_event_id: str | None = None,
    expected_trace_id: str | None = None,
    verified_archive: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Map only exact, approved, simulated Gold report chunks with intact source locators."""
    if not isinstance(report_id, str) or not _GOLD_REPORT_ID.fullmatch(report_id.strip()):
        return []
    report_id = report_id.strip()
    expected_file_name = (
        "宜昌GeoGuard复盘报告_"
        + re.sub(r"[^A-Za-z0-9._-]", "-", report_id)
        + ".docx"
    )
    archive_proof = verified_archive if isinstance(verified_archive, Mapping) else None
    proof_bound = _verified_gold_archive_binding(report_id, archive_proof, expected_file_name)
    by_document: dict[str, list[Mapping[str, Any]]] = {}
    for item in evidence_items if isinstance(evidence_items, list) else []:
        if not isinstance(item, Mapping):
            continue
        document_id = item.get("document_id")
        if (
            item.get("knowledge_base_id") != _YICHANG_EVIDENCE_KB_ID
            or not isinstance(document_id, str)
            or not document_id.strip()
            or (
                proof_bound
                and document_id != archive_proof.get("document_id")
            )
            or (
                not proof_bound
                and item.get("file_name") != expected_file_name
            )
        ):
            continue
        by_document.setdefault(document_id, []).append(item)

    mapped_evidence: list[dict[str, Any]] = []
    for document_id, chunks in by_document.items():
        ordered_chunks = sorted(chunks, key=_report_chunk_order)
        combined_text = "\n".join(str(item.get("text") or "") for item in ordered_chunks)
        metadata_candidates = [
            candidate for candidate in _report_metadata_candidates(combined_text)
            if candidate.get("report_id") == report_id
        ]
        if proof_bound:
            if (
                document_id != archive_proof.get("document_id")
                or not any(
                    _has_located_report_body_anchor(item, document_id, archive_proof.get("report_text"))
                    for item in ordered_chunks
                )
                or len(metadata_candidates) > 1
            ):
                continue
            metadata = dict(archive_proof)
            if metadata_candidates:
                indexed_metadata = metadata_candidates[0]
                for key in (
                    "report_id", "event_id", "trace_id", "report_approved", "archive_approved",
                    "approval_mode", "review_status", "is_simulated", "document_id", "file_name",
                ):
                    indexed_value = indexed_metadata.get(key)
                    proof_value = metadata.get(key)
                    if indexed_value not in (None, "") and proof_value not in (None, "") and indexed_value != proof_value:
                        metadata = {}
                        break
                if not metadata:
                    continue
                metadata.update(indexed_metadata)
        elif len(metadata_candidates) == 1:
            metadata = metadata_candidates[0]
        else:
            continue
        event_id = metadata.get("event_id")
        trace_id = metadata.get("trace_id")
        approval_mode = metadata.get("approval_mode")
        if not (
            isinstance(event_id, str)
            and event_id.strip()
            and isinstance(trace_id, str)
            and trace_id.strip()
            and metadata.get("report_approved") is True
            and metadata.get("archive_approved") is True
            and approval_mode in {"human_reviewer", "simulated_gold_test_harness"}
            and metadata.get("review_status") == "approved"
            and metadata.get("is_simulated") is True
            and (expected_event_id is None or event_id == expected_event_id)
            and (expected_trace_id is None or trace_id == expected_trace_id)
            and _has_report_body(combined_text, metadata)
        ):
            continue

        if any(
            item.get("report_id") not in (None, "", report_id)
            or item.get("event_id") not in (None, "", event_id)
            or item.get("trace_id") not in (None, "", trace_id)
            or item.get("is_simulated") not in (None, True)
            or item.get("report_approved") not in (None, True)
            or item.get("archive_approved") not in (None, True)
            or item.get("approval_mode") not in (None, "human_reviewer", "simulated_gold_test_harness")
            or item.get("review_status") not in (None, "approved")
            for item in ordered_chunks
        ):
            continue

        for item in ordered_chunks:
            source_spans = item.get("source_spans")
            report_text = metadata.get("report_text")
            report_body = (
                report_text.strip()
                if isinstance(report_text, str) and report_text.strip() in str(item.get("text") or "")
                else _report_body_snippet(str(item.get("text") or ""))
            )
            if (
                not isinstance(item.get("evidence_id"), str)
                or not item["evidence_id"].strip()
                or item.get("document_id") != document_id
                or not isinstance(item.get("chunk_id"), str)
                or not item["chunk_id"].strip()
                or not isinstance(item.get("file_name"), str)
                or not isinstance(item.get("text"), str)
                or not item["text"].strip()
                or not report_body
                or not isinstance(source_spans, list)
                or not any(isinstance(span, Mapping) for span in source_spans)
            ):
                continue
            mapped = {key: item[key] for key in _EVIDENCE_FIELDS if key in item}
            mapped.update({
                "report_id": report_id,
                "event_id": event_id,
                "trace_id": trace_id,
                "report_approved": True,
                "archive_approved": True,
                "approval_mode": approval_mode,
                "review_status": "approved",
                "is_simulated": True,
                "source_kind": metadata.get("source_kind") or "simulated_gold_indexed_archive",
                "report_body": report_body,
                "archive_file_name": (
                    archive_proof.get("file_name") if proof_bound else expected_file_name
                ),
                "archive_status": "present_in_supplied_geo_rag_evidence",
                "evidence_repository": "geo_rag_evidence_kb",
                "record_status": "simulated_gold",
                "live_status": "not_independently_verified",
            })
            mapped_evidence.append(mapped)
    return mapped_evidence


def _merge_report_metadata(
    metadata: Mapping[str, Any],
    chunks: list[Mapping[str, Any]],
) -> dict[str, Any] | None:
    merged = dict(metadata)
    for key in (
        "report_id", "event_id", "trace_id", "report_approved", "archive_approved",
        "approval_mode", "review_status", "is_simulated", "source_kind", "data_source",
    ):
        values = [item[key] for item in chunks if item.get(key) not in (None, "")]
        if key in merged and merged[key] not in (None, ""):
            if any(value != merged[key] for value in values):
                return None
        elif values:
            distinct = {json.dumps(value, ensure_ascii=False, sort_keys=True, default=str) for value in values}
            if len(distinct) != 1:
                return None
            merged[key] = values[0]
    return merged


def _record_status(metadata: Mapping[str, Any]) -> str:
    simulated = metadata.get("is_simulated")
    source_kind = str(metadata.get("source_kind") or "").casefold()
    if simulated is True:
        return "simulated_gold" if "gold" in source_kind or _GOLD_REPORT_SOURCE_ID.search(
            str(metadata.get("report_id") or "")
        ) else "simulated"
    if simulated is False:
        return "explicitly_marked_non_simulated_not_independently_verified"
    if "simulated" in source_kind or "gold" in source_kind:
        return "simulated_gold" if "gold" in source_kind or _GOLD_REPORT_SOURCE_ID.search(
            str(metadata.get("report_id") or "")
        ) else "simulated"
    return "unknown_simulation_status"


def map_verified_indexed_report_evidence(
    evidence_items: list[dict[str, Any]] | None,
    *,
    report_id: str | None = None,
    event_id: str | None = None,
    trace_id: str | None = None,
    verified_gold_archive: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Map exact archived report chunks from the Yichang Geo-RAG evidence KB."""
    if not report_id and not event_id:
        return []
    archive_report_id = (
        verified_gold_archive.get("report_id")
        if isinstance(verified_gold_archive, Mapping)
        and isinstance(verified_gold_archive.get("report_id"), str)
        else None
    )
    archive_expected_file_name = (
        "宜昌GeoGuard复盘报告_"
        + re.sub(r"[^A-Za-z0-9._-]", "-", archive_report_id)
        + ".docx"
        if archive_report_id else None
    )
    proof_bound = bool(
        archive_expected_file_name
        and _verified_gold_archive_binding(
            archive_report_id, verified_gold_archive, archive_expected_file_name,
        )
    )
    by_document: dict[str, list[Mapping[str, Any]]] = {}
    for item in evidence_items if isinstance(evidence_items, list) else []:
        document_id = item.get("document_id") if isinstance(item, Mapping) else None
        file_name = item.get("file_name") if isinstance(item, Mapping) else None
        if (
            item.get("knowledge_base_id") == _YICHANG_EVIDENCE_KB_ID
            and isinstance(document_id, str)
            and document_id.strip()
            and isinstance(file_name, str)
            and (
                (file_name.startswith("宜昌GeoGuard复盘报告_") and file_name.endswith(".docx"))
                or (
                    proof_bound
                    and document_id == verified_gold_archive.get("document_id")
                )
            )
        ):
            by_document.setdefault(document_id, []).append(item)

    mapped_evidence: list[dict[str, Any]] = []
    for document_id, chunks in by_document.items():
        ordered_chunks = sorted(chunks, key=_report_chunk_order)
        combined_text = "\n".join(str(item.get("text") or "") for item in ordered_chunks)
        metadata_candidates = _report_metadata_candidates(combined_text)
        candidate_report_ids = {
            str(candidate.get("report_id"))
            for candidate in metadata_candidates
            if candidate.get("report_id") not in (None, "")
        }
        candidate_report_ids.update(
            str(item.get("report_id"))
            for item in ordered_chunks
            if item.get("report_id") not in (None, "")
        )
        if isinstance(verified_gold_archive, Mapping) and verified_gold_archive.get("report_id"):
            candidate_report_ids.add(str(verified_gold_archive["report_id"]))
        if report_id:
            candidate_report_ids.intersection_update({report_id})

        has_gold_report = any(_GOLD_REPORT_ID.fullmatch(value) for value in candidate_report_ids)
        for candidate_id in candidate_report_ids:
            if not _GOLD_REPORT_ID.fullmatch(candidate_id):
                continue
            gold_rows = map_verified_gold_report_evidence(
                candidate_id,
                [dict(item) for item in ordered_chunks],
                expected_event_id=event_id,
                expected_trace_id=trace_id,
                verified_archive=(
                    verified_gold_archive
                    if isinstance(verified_gold_archive, Mapping)
                    and verified_gold_archive.get("report_id") == candidate_id
                    else None
                ),
            )
            mapped_evidence.extend(gold_rows)
        if has_gold_report:
            continue

        for candidate in metadata_candidates:
            merged = _merge_report_metadata(candidate, ordered_chunks)
            if not isinstance(merged, Mapping):
                continue
            resolved_report_id = merged.get("report_id")
            resolved_event_id = merged.get("event_id")
            resolved_trace_id = merged.get("trace_id")
            if (
                not isinstance(resolved_report_id, str)
                or not resolved_report_id.strip()
                or not isinstance(resolved_event_id, str)
                or not resolved_event_id.strip()
                or (report_id is not None and resolved_report_id != report_id)
                or (event_id is not None and resolved_event_id != event_id)
                or (trace_id is not None and resolved_trace_id != trace_id)
                or merged.get("report_approved") is not True
                or merged.get("archive_approved") is not True
                or (merged.get("review_status") not in (None, "approved"))
            ):
                continue
            simulated = merged.get("is_simulated")
            source_kind = str(merged.get("source_kind") or "").casefold()
            if simulated is False and ("simulated" in source_kind or "gold" in source_kind):
                continue
            if simulated is True and (
                merged.get("approval_mode") not in {"human_reviewer", "simulated_gold_test_harness"}
                or merged.get("review_status") != "approved"
            ):
                continue
            report_text = merged.get("report_text")
            if "report_text" in merged and (
                not isinstance(report_text, str)
                or not report_text.strip()
                or report_text.strip() == "待补充应急调查报告"
            ):
                continue
            if isinstance(report_text, str):
                normalized_text = re.sub(r"[\s\\]+", "", combined_text)
                body_anchor = re.sub(r"[\s\\]+", "", report_text[:80])
                if not body_anchor or body_anchor not in normalized_text:
                    continue
            combined_body = (
                report_text.strip()
                if isinstance(report_text, str) and report_text.strip()
                else _report_body_snippet(combined_text)
            )
            if not combined_body:
                continue
            expected_file_name = (
                "宜昌GeoGuard复盘报告_"
                + re.sub(r"[^A-Za-z0-9._-]", "-", str(resolved_report_id))
                + ".docx"
            )
            if (
                merged.get("document_id") not in (None, document_id)
                or merged.get("file_name") not in (None, expected_file_name)
                or any(item.get("file_name") != expected_file_name for item in ordered_chunks)
            ):
                continue
            record_status = _record_status(merged)
            document_rows = []
            for item in ordered_chunks:
                source_spans = item.get("source_spans")
                chunk_text = item.get("text")
                report_body = _report_body_snippet(str(chunk_text or ""))
                if not report_body and isinstance(report_text, str) and report_text.strip() in str(chunk_text or ""):
                    report_body = report_text.strip()
                if (
                    not isinstance(item.get("evidence_id"), str)
                    or not item["evidence_id"].strip()
                    or not isinstance(item.get("chunk_id"), str)
                    or not item["chunk_id"].strip()
                    or not isinstance(item.get("file_name"), str)
                    or not isinstance(chunk_text, str)
                    or not chunk_text.strip()
                    or not report_body
                    or not isinstance(source_spans, list)
                    or not any(isinstance(span, Mapping) for span in source_spans)
                    or item.get("report_id") not in (None, "", resolved_report_id)
                    or item.get("event_id") not in (None, "", resolved_event_id)
                    or item.get("trace_id") not in (None, "", resolved_trace_id)
                ):
                    continue
                mapped = {key: item[key] for key in _EVIDENCE_FIELDS if key in item}
                mapped.update({
                    "report_id": resolved_report_id,
                    "event_id": resolved_event_id,
                    "trace_id": resolved_trace_id,
                    "report_approved": True,
                    "archive_approved": True,
                    "approval_mode": merged.get("approval_mode"),
                    "review_status": merged.get("review_status"),
                    "is_simulated": simulated,
                    "source_kind": source_kind,
                    "report_body": report_body,
                    "archive_status": "present_in_supplied_geo_rag_evidence",
                    "evidence_repository": "geo_rag_evidence_kb",
                    "record_status": record_status,
                    "live_status": "not_independently_verified",
                })
                document_rows.append(mapped)
            if document_rows:
                mapped_evidence.extend(document_rows)
                break
    return mapped_evidence


_PRIVATE_CONTEXT_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "auth",
    "credentials",
    "conversation_id",
    "dify_user",
    "dify_a1_api_key",
    "dify_api_key",
    "headers",
    "token",
    "user",
    "user_id",
}
_OMITTED_CONTEXT_KEYS = _PRIVATE_CONTEXT_KEYS | {
    "dataset_id",
    "dataset_ids",
    "knowledge_base_id",
    "knowledge_base_ids",
}
def _public_context(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _public_context(item)
            for key, item in value.items()
            if str(key).casefold().replace("-", "_") not in _OMITTED_CONTEXT_KEYS
        }
    if isinstance(value, list):
        return [_public_context(item) for item in value]
    return value


def _source_provenance(item: Mapping[str, Any]) -> str:
    """Describe only explicit simulation markers; missing markers stay unknown."""
    simulated = item.get("is_simulated")
    source_kind = str(item.get("source_kind") or "").strip().casefold()
    data_source = str(item.get("data_source") or "").strip().casefold()
    simulated_marker = (
        simulated is True
        or (isinstance(simulated, str) and simulated.strip().casefold() == "true")
        or source_kind in {"simulated", "simulation"}
        or data_source.startswith("local_gold_fixture")
    )
    if simulated_marker:
        if (
            "gold" in source_kind
            or "gold" in data_source
            or _GOLD_REPORT_SOURCE_ID.search(str(item.get("report_id") or ""))
        ):
            return "simulated_gold"
        return "simulated"
    if simulated is False or (isinstance(simulated, str) and simulated.strip().casefold() == "false"):
        return "explicitly_marked_non_simulated_not_independently_verified"
    return "unmarked_unknown"


def _context_values(context: Mapping[str, Any], keys: tuple[str, ...]) -> list[str]:
    containers = [context]
    event = context.get("event")
    if isinstance(event, Mapping):
        containers.append(event)
    values = []
    for container in containers:
        for key in keys:
            value = container.get(key)
            if value not in (None, ""):
                values.append(str(value).strip())
    return values


def _report_ids_in_query(query: str) -> list[str]:
    matches = [match.group(0) for match in _REPORT_ID_IN_QUERY.finditer(query)]
    matches.extend(match.group(1) for match in _REPORT_ID_ASSIGNMENT.finditer(query))
    return list(dict.fromkeys(matches))


def _gold_report_request(query: str, context: Mapping[str, Any]) -> tuple[str | None, bool]:
    query_ids = _report_ids_in_query(query)
    gold_query_ids = [report_id for report_id in query_ids if _GOLD_REPORT_ID.fullmatch(report_id)]
    context_report_id = context.get("report_id")
    context_report_id = context_report_id.strip() if isinstance(context_report_id, str) else ""
    context_gold_id = context_report_id if _GOLD_REPORT_ID.fullmatch(context_report_id) else None
    if len(query_ids) > 1 or len(gold_query_ids) > 1:
        return (gold_query_ids[0] if len(gold_query_ids) == 1 else None), True
    if not gold_query_ids and context_gold_id is None:
        return None, False
    report_id = gold_query_ids[0] if gold_query_ids else context_gold_id
    if query_ids and context_report_id and context_report_id != report_id:
        return report_id, True
    return report_id, False


def _gold_report_expected_ids(
    query: str,
    context: Mapping[str, Any],
    report_id: str,
) -> tuple[str | None, str | None, bool]:
    event_ids = {match.group(0) for match in _GOLD_EVENT_ID_IN_QUERY.finditer(query)}
    event_ids.update(_context_values(context, ("report_event_id", "event_id")))
    trace_ids = {match.group(0) for match in _GOLD_TRACE_ID_IN_QUERY.finditer(query)}
    trace_ids.update(_context_values(context, ("report_trace_id",)))
    if context.get("report_id") == report_id:
        trace_ids.update(_context_values(context, ("trace_id",)))
    if len(event_ids) > 1 or len(trace_ids) > 1:
        return None, None, True
    return next(iter(event_ids), None), next(iter(trace_ids), None), False


def _gold_report_unavailable(report_id: str | None, reason: str) -> dict[str, Any]:
    report_label = f"报告 {report_id}" if report_id else "请求的 Gold 报告"
    return {
        "status": "report_archive_unavailable",
        "answer": (
            f"未能从宜昌证据库取得通过报告 ID、事件、追踪、审批和正文校验的 {report_label} 模拟归档证据；"
            "本次不依据该报告作答。"
        ),
        "response": None,
        "outputs": {"report_id": report_id, "evidence_ids": [], "reason": reason},
        "parsed_output": None,
        "execution_engine": "local",
        "app_name": "GeoGuard A1 Gold report evidence gate",
        "app_mode": "exact_gold_report_lookup",
        "conversation_id": None,
        "message_id": None,
        "task_id": None,
        "workflow_run_id": None,
        "duration_ms": 0,
        "trace_id": None,
        "error": None,
    }


def _report_lookup_request(
    query: str,
    context: Mapping[str, Any],
) -> tuple[str | None, str | None, str | None, bool]:
    query_report_ids = _report_ids_in_query(query)
    context_report_id = context.get("report_id")
    context_report_id = context_report_id.strip() if isinstance(context_report_id, str) else ""
    report_ids = set(query_report_ids)
    if context_report_id:
        report_ids.add(context_report_id)

    query_event_ids = {match.group(0) for match in _EVENT_ID_IN_QUERY.finditer(query)}
    query_event_ids.update(match.group(1) for match in _EVENT_ID_ASSIGNMENT.finditer(query))
    context_event_ids = set(_context_values(context, ("report_event_id", "event_id")))
    event_ids = query_event_ids | context_event_ids
    query_trace_ids = {match.group(0) for match in _TRACE_ID_IN_QUERY.finditer(query)}
    query_trace_ids.update(match.group(1) for match in _TRACE_ID_ASSIGNMENT.finditer(query))
    context_trace_ids = set(_context_values(context, ("report_trace_id",)))
    if context_report_id:
        context_trace_ids.update(
            value for value in _context_values(context, ("trace_id",))
            if _TRACE_ID_IN_QUERY.fullmatch(value)
        )
    trace_ids = query_trace_ids | context_trace_ids

    report_id = next(iter(report_ids), None) if len(report_ids) <= 1 else None
    event_id = next(iter(event_ids), None) if len(event_ids) <= 1 else None
    trace_id = next(iter(trace_ids), None) if len(trace_ids) <= 1 else None
    report_intent = bool(_REPORT_LOOKUP_INTENT.search(query))
    archive_intent = bool(re.search(
        r"归档|存档|入库|复盘|调查|报告原文|报告正文|全文|archive|archived|report text|full report",
        query,
        re.I,
    ))
    explicit_event_id = bool(re.search(r"\bevent[_ ]id\s*[:=]", query, re.I))
    requested = bool(report_id and (archive_intent or not _REPORT_STATUS_LOOKUP_INTENT.search(query)))
    requested = requested or bool(event_id and (report_intent or explicit_event_id))
    conflict = len(report_ids) > 1 or len(event_ids) > 1 or len(trace_ids) > 1
    return (report_id, event_id, trace_id, conflict) if requested or conflict else (None, None, None, False)


def _report_lookup_summary(
    report_id: str | None,
    event_id: str | None,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    report_ids = {str(item.get("report_id")) for item in evidence if item.get("report_id")}
    event_ids = {str(item.get("event_id")) for item in evidence if item.get("event_id")}
    record_statuses = sorted({str(item.get("record_status") or "unknown_simulation_status") for item in evidence})
    return {
        "status": "matched",
        "report_id": report_id or (next(iter(report_ids)) if len(report_ids) == 1 else None),
        "event_id": event_id or (next(iter(event_ids)) if len(event_ids) == 1 else None),
        "evidence_repository": "geo_rag_evidence_kb",
        "archive_status": "present_in_supplied_geo_rag_evidence",
        "record_status": record_statuses[0] if len(record_statuses) == 1 else "mixed_or_unknown",
        "live_status": "not_independently_verified",
        "evidence_ids": [item["evidence_id"] for item in evidence if item.get("evidence_id")],
        "body_snippets": [
            {"evidence_id": item.get("evidence_id"), "text": item.get("report_body")}
            for item in evidence if item.get("report_body")
        ],
        "source_locators": [
            {
                key: item[key]
                for key in (
                    "evidence_id", "knowledge_base_id", "document_id", "chunk_id",
                    "file_name", "archive_file_name", "page", "source_spans",
                )
                if key in item
            }
            for item in evidence
        ],
    }


def _report_lookup_unavailable(
    report_id: str | None,
    event_id: str | None,
    reason: str,
) -> dict[str, Any]:
    lookup = {
        "status": "unavailable",
        "report_id": report_id,
        "event_id": event_id,
        "evidence_repository": "geo_rag_evidence_kb",
        "record_status": "unknown_simulation_status",
        "live_status": "not_independently_verified",
        "evidence_ids": [],
        "source_locators": [],
        "reason": reason,
    }
    target = f"报告 {report_id}" if report_id else f"事件 {event_id} 关联的报告"
    return {
        "status": "report_archive_unavailable",
        "answer": f"未能从宜昌 Geo-RAG 证据库的精确结果中核实{target}及其正文与来源定位。",
        "response": None,
        "outputs": {"report_lookup": lookup, "report_evidence": [], "reason": reason},
        "parsed_output": None,
        "execution_engine": "local",
        "app_name": "GeoGuard A1 report evidence lookup",
        "app_mode": "exact_report_lookup",
        "conversation_id": None,
        "message_id": None,
        "task_id": None,
        "workflow_run_id": None,
        "duration_ms": 0,
        "trace_id": None,
        "error": None,
    }


def _local_report_lookup_result(
    report_lookup: Mapping[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    record_status = report_lookup.get("record_status")
    status_note = (
        "这是 Gold 模拟归档内容，不代表真实业务记录或线上实时状态。"
        if record_status in {"simulated", "simulated_gold"}
        else "记录带有非模拟标记，但本次没有独立核实其真实业务状态。"
        if record_status == "explicitly_marked_non_simulated_not_independently_verified"
        else "模拟/真实状态未知，本次不将其表述为真实业务事实。"
    )
    snippets = "\n\n".join(str(item.get("report_body") or "") for item in evidence)
    return {
        "status": "completed",
        "answer": f"已取得精确匹配的归档报告正文片段。{status_note}\n\n{snippets}",
        "response": None,
        "outputs": {"report_lookup": dict(report_lookup), "report_evidence": evidence},
        "parsed_output": None,
        "execution_engine": "local",
        "app_name": "GeoGuard A1 report evidence lookup",
        "app_mode": "exact_report_lookup",
        "conversation_id": None,
        "message_id": None,
        "task_id": None,
        "workflow_run_id": None,
        "duration_ms": 0,
        "trace_id": None,
        "error": None,
    }


def _p6_request(query: str, context: Mapping[str, Any]) -> dict[str, Any] | None:
    if not _HR_REQUEST.search(query):
        return None

    query_scenarios = [match.group(1).casefold() for match in _P6_SCENARIO_IN_QUERY.finditer(query)]
    context_scenarios = [
        value.casefold()
        for value in _context_values(context, ("p6_scenario", "scenario"))
        if value.casefold() in _P6_SCENARIOS
    ]
    forecast_intent = re.search(r"预测|预报|(?<![A-Za-z])forecast(?![A-Za-z])", query, re.I)
    dynamic_08_intent = bool(_P6_DYNAMIC_08_INTENT.search(query))
    dynamic_intent = re.search(r"动态|(?<![A-Za-z0-9_])dynamic(?![A-Za-z0-9_])", query, re.I)
    if dynamic_08_intent and (forecast_intent or dynamic_intent):
        return {"status": "ambiguous_scenario", "reason": "query_mentions_conflicting_scenarios"}
    if forecast_intent and dynamic_intent:
        return {"status": "ambiguous_scenario", "reason": "query_mentions_conflicting_scenarios"}
    if dynamic_08_intent:
        query_scenarios.append("dynamic_08")
    if forecast_intent:
        query_scenarios.append("forecast")
    elif dynamic_intent:
        query_scenarios.append("dynamic")
    scenario_values = set(query_scenarios + context_scenarios)
    if len(scenario_values) > 1:
        return {"status": "ambiguous_scenario", "reason": "conflicting_p6_scenarios"}
    if scenario_values:
        scenario = next(iter(scenario_values))
    else:
        return None

    query_ids = [match.group(0) for match in _YCSU_ID.finditer(query)]
    context_ids = [
        value for value in _context_values(
            context, ("p6_slope_unit_id", "slopeUnitId", "slope_unit_id"),
        )
        if _YCSU_ID.fullmatch(value)
    ]
    unit_ids = {value.casefold(): value for value in query_ids + context_ids}
    if len(unit_ids) > 1:
        return {"status": "mapping_conflict", "reason": "conflicting_p6_slope_unit_ids", "scenario": scenario}
    slope_unit_id = next(iter(unit_ids.values()), None)
    if not slope_unit_id:
        return {
            "status": "missing_mapping",
            "reason": "missing_explicit_p6_ycsu_slope_unit_id",
            "scenario": scenario,
        }

    query_snapshots = [match.group(1) for match in _P6_SNAPSHOT_IN_QUERY.finditer(query)]
    context_snapshots = _context_values(context, ("p6_snapshot_id", "snapshotId", "snapshot_id"))
    snapshot_ids = {value for value in query_snapshots + context_snapshots if value}
    if len(snapshot_ids) > 1:
        return {
            "status": "ambiguous_snapshot",
            "reason": "conflicting_p6_snapshot_ids",
            "slope_unit_id": slope_unit_id,
            "scenario": scenario,
        }
    return {
        "status": "requested",
        "slope_unit_id": slope_unit_id,
        "scenario": scenario,
        "snapshot_id": next(iter(snapshot_ids), None),
    }


def _p6_prompt_payload(
    result: Mapping[str, Any],
    *,
    slope_unit_id: str,
    scenario: str,
    requested_snapshot_id: str | None,
) -> dict[str, Any]:
    status = str(result.get("status") or "unavailable")
    selected = result.get("unit_snapshot") or result.get("selected_snapshot")
    selected = selected if isinstance(selected, Mapping) else {}
    latest = result.get("latest_snapshot")
    latest = latest if isinstance(latest, Mapping) else {}
    service_status = result.get("service_status")
    service_status = service_status if isinstance(service_status, Mapping) else {}
    snapshot_id = (
        result.get("snapshot_id")
        or selected.get("snapshot_id")
        or latest.get("snapshot_id")
        or requested_snapshot_id
    )
    as_of_local = selected.get("as_of_local") or latest.get("as_of_local")
    candidate_available = status == "completed" and bool(snapshot_id)
    source_locator = (
        f"P6[{slope_unit_id}|scenario={scenario}|snapshot_id={snapshot_id}|"
        f"as_of_local={as_of_local or 'not_returned'}]"
        if candidate_available
        else None
    )
    payload: dict[str, Any] = {
        "status": "candidate_available" if candidate_available else (
            "invalid_response" if status == "completed" else status
        ),
        "execution_engine": "p6_dynamic_query_api",
        "source": latest.get("provider") or selected.get("provider") or "P6 dynamic query API",
        "slope_unit_id": slope_unit_id,
        "scenario": scenario,
        "snapshot_id": snapshot_id,
        "as_of_local": as_of_local,
        "model": selected.get("model") or latest.get("model") or service_status.get("model"),
        "rule_version": selected.get("rule_version") or latest.get("rule_version"),
        "rain_source_type": (
            (latest.get("forecast_type") or selected.get("forecast_type")) if scenario == "forecast"
            else (latest.get("historical_type") or selected.get("historical_type"))
        ),
        "official_warning_allowed": False,
        "permitted_use": "候选筛查（不得用于官方预警）",
        "disclaimer": (
            "P6 H/R动态或预测筛查候选；降雨输入为模型场，不是雨量站实测；结果不是官方预警。"
        ),
        "source_locator": source_locator,
    }
    if candidate_available:
        item = result.get("item") if isinstance(result.get("item"), Mapping) else {}
        h_grade, h_score, r_grade, r_score = _P6_SCENARIO_FIELDS[scenario]
        payload.update({
            "rain_status": item.get("rain_status"),
            "rain_mapping_status": item.get("rain_mapping_status"),
            "rain_mapping_distance_km": item.get("rain_mapping_distance_km"),
            "H": {"grade": item.get(h_grade), "score": item.get(h_score)},
            "R": {"grade": item.get(r_grade), "score": item.get(r_score)},
            "citation_instruction": (
                f"使用这些候选值时引用来源定位符【{source_locator}】；"
                "它不是 Geo-RAG evidence_id，不得改写为 EV-*。"
            ),
        })
    else:
        payload["reason"] = (
            "P6响应缺少 snapshot_id，未转交 H/R 候选值。"
            if status == "completed" else
            result.get("reason") or "P6动态H/R候选不可用。"
        )
    return payload


def _chatflow_query(
    query: str,
    evidence: list[dict[str, Any]],
    context: Mapping[str, Any] | None,
    p6_dynamic: Mapping[str, Any] | None = None,
) -> str:
    parts = [f"【用户问题】\n{query}"]
    evidence_rows = [
        _compact_chatflow_evidence(item)
        for item in evidence[:_CHATFLOW_EVIDENCE_LIMIT]
        if isinstance(item, Mapping)
    ]
    if evidence_rows:
        parts.append(
            "【Geo-RAG 宜昌三库检索证据】\n"
            "以下内容及定位符由调用方提供的宜昌 Geo-RAG 检索结果组成；本适配器不独立核验线上服务状态。"
            "仅可引用其中存在的 evidence_id；不得补造文档、页码或来源。knowledge_base_id 是 Geo-RAG 来源标识，"
            "不是 Dify dataset_id，也不代表已绑定 Dify 知识库。"
            "source_provenance=simulated_gold 表示明确标注的 Gold 模拟证据；"
            "explicitly_marked_non_simulated_not_independently_verified 只表示有非模拟标记，"
            "不表示本次已独立核实；unmarked_unknown 表示来源状态未知。\n"
            + json.dumps(evidence_rows, ensure_ascii=False, default=str)
        )
        report_rows = [item for item in evidence_rows if item.get("report_body")]
        if report_rows:
            parts.append(
                "【精确报告正文与来源状态】报告正文片段使用 report_body；引用时保留对应 evidence_id、"
                "knowledge_base_id、document_id、chunk_id、file_name、page 和 source_spans。"
                "若存在 archive_file_name，它来自与 document_id 绑定的已验证归档记录；file_name 仍保留检索 chunk 原值。"
                "evidence_repository=geo_rag_evidence_kb 说明来源库标识；live_status=not_independently_verified"
                "表示未独立核验在线状态。"
            )
            if any(item.get("is_simulated") is True for item in report_rows):
                parts.append("报告带有模拟标记，必须说明是模拟/演示数据，不得称为真实业务记录或线上实时归档。")
            elif any(item.get("is_simulated") is False for item in report_rows):
                parts.append("非模拟标记只表示来源有该标记，不代表已独立核实其真实业务状态。")
            else:
                parts.append("报告模拟/真实状态未知，不得将其表述为真实业务事实。")
        if any(
            _GOLD_REPORT_SOURCE_ID.search(str(item.get("report_id") or ""))
            and item.get("is_simulated") is True
            for item in evidence
            if isinstance(item, Mapping)
        ):
            parts.append(
                "【精确 Gold 报告性质】本次只包含经本地校验的精确报告 ID、事件 ID、追踪 ID、"
                "报告审批、归档批准和正文完整性的 Gold 报告片段。回答必须明确标注这是 Gold 模拟/演示数据，"
                "不得描述为真实业务记录、正式预警或真实人工复核结论。"
            )
    else:
        parts.append("【Geo-RAG 宜昌三库检索证据】\n本次未取得本地检索证据。")

    if isinstance(p6_dynamic, Mapping):
        parts.append(
            "【P6动态H/R筛查候选】\n"
            "这是按显式 YCSU 单元 ID 查询的 P6 只读候选结果，不能作为 Geo-RAG 文献证据、"
            "雨量站实测或官方预警。回答只能使用下列字段；如引用 H/R，必须保留候选属性"
            "并按 citation_instruction 引用来源定位符，不得伪造 EV-* evidence_id。\n"
            + json.dumps(dict(p6_dynamic), ensure_ascii=False, default=str)
        )

    context = context if isinstance(context, Mapping) else {}
    public_context = _public_context(context)
    if public_context:
        parts.append(
            "【调用方提供的上下文】\n"
            "这些字段来自本次调用方输入，不代表已实时查询或已核实的业务记录。\n"
            "若上下文标注 is_simulated=true、Gold 或模拟，必须保留其模拟性质；"
            "缺少来源标记时不得推断为真实记录。\n"
            + json.dumps(public_context, ensure_ascii=False, default=str)
        )
    return "\n\n".join(parts)


def _answer_from(value: Any) -> tuple[str, Any | None]:
    if isinstance(value, Mapping):
        parsed = dict(value)
        for key in ("answer", "response", "text", "content", "output"):
            item = value.get(key)
            if isinstance(item, str):
                return item, parsed
            if isinstance(item, Mapping):
                nested = item.get("answer") or item.get("text")
                if isinstance(nested, str):
                    return nested, parsed
        return json.dumps(parsed, ensure_ascii=False, default=str), parsed
    if isinstance(value, str):
        command = _COMMAND_OUTPUT.match(value)
        if command:
            try:
                payload = json.loads(command.group("body"))
            except json.JSONDecodeError:
                return value, None
            return value, {"command": command.group("command"), "payload": payload}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value, None
        if isinstance(parsed, Mapping):
            for key in ("answer", "response", "text", "content", "output"):
                if isinstance(parsed.get(key), str):
                    return parsed[key], parsed
        return value, parsed
    if value is None:
        return "", None
    return str(value), None


def _normalise(result: dict[str, Any]) -> dict[str, Any]:
    outputs = result.get("outputs") if isinstance(result.get("outputs"), Mapping) else {}
    response = result.get("response")
    source = response if response not in (None, "") else outputs
    answer, parsed_output = _answer_from(source)
    return {
        "status": result.get("status", "unknown"),
        "answer": answer,
        "response": response,
        "outputs": dict(outputs),
        "parsed_output": parsed_output,
        "execution_engine": result.get("execution_engine", "dify"),
        "app_name": result.get("app_name"),
        "app_mode": result.get("app_mode"),
        "conversation_id": result.get("conversation_id"),
        "message_id": result.get("message_id"),
        "task_id": result.get("task_id"),
        "workflow_run_id": result.get("workflow_run_id"),
        "duration_ms": result.get("duration_ms"),
        "trace_id": result.get("trace_id"),
        "error": result.get("error"),
    }


async def run_a1_chatflow(
    query: str,
    evidence: list[dict[str, Any]],
    context: Mapping[str, Any] | None = None,
    *,
    verified_gold_archive: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Run A1 only when its Dify app has a server-side API configuration."""
    context = context if isinstance(context, Mapping) else {}
    requested_report_id, requested_event_id, requested_trace_id, request_conflict = _report_lookup_request(
        query, context,
    )
    report_lookup = None
    if request_conflict:
        return _report_lookup_unavailable(
            requested_report_id, requested_event_id, "conflicting_exact_report_event_or_trace_ids",
        )
    if requested_report_id or requested_event_id:
        evidence = map_verified_indexed_report_evidence(
            evidence,
            report_id=requested_report_id,
            event_id=requested_event_id,
            trace_id=requested_trace_id,
            verified_gold_archive=verified_gold_archive,
        )
        if not evidence:
            return _report_lookup_unavailable(
                requested_report_id, requested_event_id, "no_verified_indexed_report_match",
            )
        report_lookup = _report_lookup_summary(requested_report_id, requested_event_id, evidence)
    else:
        evidence = [item for item in evidence if not _non_general_report_evidence_item(item)]

    if not dify_configured(A1_AGENT_ID):
        if isinstance(report_lookup, Mapping):
            return _local_report_lookup_result(report_lookup, evidence)
        return None
    p6_dynamic: dict[str, Any] | None = None
    p6_request = _p6_request(query, context)
    if p6_request is not None:
        if p6_request.get("status") == "requested":
            try:
                p6_result = await lookup_dynamic_slope_unit(
                    p6_request["slope_unit_id"],
                    scenario=p6_request["scenario"],
                    snapshot_id=p6_request.get("snapshot_id"),
                )
            except Exception as exc:
                p6_result = {"status": "unavailable", "reason": type(exc).__name__}
            p6_dynamic = _p6_prompt_payload(
                p6_result,
                slope_unit_id=p6_request["slope_unit_id"],
                scenario=p6_request["scenario"],
                requested_snapshot_id=p6_request.get("snapshot_id"),
            )
        else:
            p6_dynamic = {
                **p6_request,
                "execution_engine": "p6_dynamic_query_api",
                "official_warning_allowed": False,
                "permitted_use": "候选筛查（不得用于官方预警）",
                "disclaimer": "未取得可用的 P6 H/R 候选结果；不得推断或补造 H/R 值。",
            }
    # The published legacy app defaults its graph lookup switch to "on"; force
    # it off so Dify Cloud does not call the old private Geo-RAG endpoint. The
    # adapter has already retrieved Yichang evidence and includes it in query.
    inputs: dict[str, Any] = {"Feature_Toggle": "off"}
    result = await run_agent(
        A1_AGENT_ID,
        inputs=inputs,
        user=str(context.get("dify_user") or context.get("user_id") or context.get("user") or "geo-guard-a1"),
        query=_chatflow_query(query, evidence, context, p6_dynamic),
        conversation_id=context.get("conversation_id"),
    )
    normalised = _normalise(result)
    if p6_dynamic is not None:
        normalised["outputs"]["p6_dynamic"] = p6_dynamic
    if isinstance(report_lookup, Mapping):
        normalised["outputs"]["report_lookup"] = report_lookup
        normalised["outputs"]["report_evidence"] = evidence
    return normalised
