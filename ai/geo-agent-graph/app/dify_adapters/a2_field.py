"""A2 bridge for the GEO识图-多图汇总 Chatflow and its Yichang YAML copy.

The DSL has no custom Start variables: pass field context through ``query`` and
uploaded images through ``files``/``sys.files``. After importing and publishing
the copy, a real smoke must verify those inputs and outputs ``aiReportDetail``,
``aiRiskLabel``, and ``aiVisionProps``; this module does not imply deployment.
"""

from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import re
from pathlib import PurePosixPath
from typing import Any

import httpx

from ..config import settings
from ..dify_client import _api_url, dify_configured, run_agent, upload_file
from ..dify_registry import get_dify_app

_AGENT_ID = "A2"
_IMAGE_LIMIT = 3
_IMAGE_SIZE_LIMIT = 10 * 1024 * 1024
_IMAGE_TOTAL_SIZE_LIMIT = _IMAGE_LIMIT * _IMAGE_SIZE_LIMIT
_EXTENSION_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
_MIME_EXTENSIONS = {value: key for key, value in _EXTENSION_MIME_TYPES.items()}


def _photo_upload_items(data: dict[str, Any], photo_refs: list[Any]) -> tuple[list[Any], str | None]:
    """Require byte-bearing uploads aligned with refs; refs alone are never file bytes."""
    if "photo_uploads" not in data:
        return [], "source_bytes_unavailable"

    uploads = data.get("photo_uploads")
    if not isinstance(uploads, list) or len(uploads) != len(photo_refs):
        return [], "source_bytes_unavailable"
    for index, (upload, reference) in enumerate(zip(uploads, photo_refs)):
        if (
            not isinstance(upload, dict)
            or isinstance(upload.get("index"), bool)
            or upload.get("index") != index
            or upload.get("reference") != reference
        ):
            return [], "photo_upload_mismatch"
    return uploads, None


def _local_result(status: str, *, error: str | None = None) -> dict[str, Any]:
    return {
        "execution_engine": "local",
        "status": status,
        "analysis_status": "pending_visual_model",
        "outputs": {},
        "uploaded_file_ids": [],
        "trace_id": None,
        "task_id": None,
        "workflow_run_id": None,
        "conversation_id": None,
        "error": error,
    }


async def _image_upload_contract_status() -> str | None:
    """Return a local pending reason unless the published API allows image uploads."""
    app = get_dify_app(_AGENT_ID)
    try:
        async with httpx.AsyncClient(timeout=settings.dify_timeout_seconds) as client:
            response = await client.get(
                _api_url(settings.dify_base_url, "/v1/parameters"),
                headers={"Authorization": f"Bearer {app.api_key}"},
            )
            response.raise_for_status()
            parameters = response.json()
    except (httpx.HTTPError, ValueError):
        return "dify_parameters_unavailable"

    if not isinstance(parameters, dict):
        return "dify_parameters_unavailable"
    file_upload = parameters.get("file_upload")
    if not isinstance(file_upload, dict):
        return "dify_parameters_unavailable"
    image = file_upload.get("image")
    if not isinstance(image, dict):
        return "dify_parameters_unavailable"

    allowed_types = file_upload.get("allowed_file_types")
    allowed_methods = file_upload.get("allowed_file_upload_methods")
    image_methods = image.get("transfer_methods")
    if (
        file_upload.get("enabled") is True
        and image.get("enabled") is True
        and isinstance(allowed_types, list)
        and "image" in allowed_types
        and isinstance(allowed_methods, list)
        and "local_file" in allowed_methods
        and isinstance(image_methods, list)
        and "local_file" in image_methods
    ):
        return None
    return "image_input_not_enabled"


def _decode_photo(item: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(item, dict):
        return None, None

    content = item.get("content")
    mime_from_data_uri = None
    if not isinstance(content, bytes):
        content = item.get("bytes")
    if not isinstance(content, bytes):
        encoded = item.get("content_base64") or item.get("data_uri")
        if not isinstance(encoded, str) or not encoded:
            return None, None
        match = re.fullmatch(r"data:(image/[A-Za-z0-9.+-]+);base64,(.+)", encoded, re.DOTALL)
        if match:
            mime_from_data_uri, encoded = match.groups()
        if len(encoded) > (_IMAGE_SIZE_LIMIT * 4 // 3 + 8):
            return None, "photo_exceeds_dify_limit"
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return None, "invalid_photo_base64"

    if not content:
        return None, "empty_photo"
    if len(content) > _IMAGE_SIZE_LIMIT:
        return None, "photo_exceeds_dify_limit"

    filename = item.get("filename") or item.get("name") or "field-photo"
    filename = PurePosixPath(str(filename).replace("\\", "/")).name
    extension = PurePosixPath(filename).suffix.lower()
    mime_type = item.get("mime_type") or item.get("mimeType") or mime_from_data_uri
    if not isinstance(mime_type, str) or not mime_type.strip():
        mime_type = _EXTENSION_MIME_TYPES.get(extension) or mimetypes.guess_type(filename)[0]
    mime_type = str(mime_type or "").strip().lower()
    if mime_type == "image/jpg":
        mime_type = "image/jpeg"
    if mime_type not in _MIME_EXTENSIONS:
        return None, "unsupported_photo_type"
    if extension and _EXTENSION_MIME_TYPES.get(extension) != mime_type:
        return None, "photo_filename_type_mismatch"
    if not extension:
        extension = _MIME_EXTENSIONS[mime_type]
        filename = f"{filename}{extension}"

    return {"filename": filename, "content": content, "mime_type": mime_type}, None


def _parse_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    text = value.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _vision_outputs(run_result: dict[str, Any]) -> dict[str, Any]:
    candidates = [run_result.get("outputs"), run_result.get("response")]
    for candidate in candidates:
        parsed = _parse_object(candidate)
        nested_response = _parse_object(parsed.get("responseJson"))
        if nested_response:
            parsed = {**parsed, **nested_response}
        if not all(key in parsed for key in ("aiReportDetail", "aiRiskLabel", "aiVisionProps")):
            final_json = _parse_object(parsed.get("finalJson"))
            if final_json:
                parsed.setdefault("aiReportDetail", final_json.get("描述"))
        report = parsed.get("aiReportDetail")
        label = parsed.get("aiRiskLabel")
        props = parsed.get("aiVisionProps")
        if isinstance(report, str) and isinstance(label, str) and isinstance(props, dict):
            result = {
                "aiReportDetail": report,
                "aiRiskLabel": label,
                "aiVisionProps": props,
            }
            risk_level = parsed.get("aiRiskLevel")
            if (
                isinstance(risk_level, int)
                and not isinstance(risk_level, bool)
                and 1 <= risk_level <= 4
            ):
                result["aiRiskLevel"] = risk_level
            final_json_value = parsed.get("finalJson")
            if isinstance(final_json_value, str):
                result["finalJson"] = final_json_value
            response_json_value = parsed.get("responseJson")
            if not isinstance(response_json_value, str) and isinstance(candidate, str):
                response_json_value = candidate
            if isinstance(response_json_value, str):
                result["responseJson"] = response_json_value
            return result
    return {}


def _chat_query(
    *,
    narrative: str,
    admin_area: str | None,
    gps: dict[str, float] | None,
    visit_time: str | None,
    hazard_point_id: Any,
    slope_unit_id: Any,
    source_kind: str,
    is_simulated: bool,
    data_source: str,
) -> str:
    context = {
        "现场文字": narrative or None,
        "行政区": admin_area,
        "GPS": gps,
        "巡查时间": visit_time,
        "隐患点编号": hazard_point_id,
        "斜坡单元编号": slope_unit_id,
        "来源类型": source_kind,
        "是否模拟数据": is_simulated,
        "数据来源": data_source,
    }
    return "现场险情图文信息：\n" + json.dumps(context, ensure_ascii=False)


async def run_a2_field_vision(
    data: dict[str, Any],
    *,
    photo_refs: list[Any],
    narrative: str,
    admin_area: str | None,
    gps: dict[str, float] | None,
    visit_time: str | None,
    hazard_point_id: Any,
    slope_unit_id: Any,
    correlation_id: str,
    source_kind: str,
    is_simulated: bool,
    data_source: str,
) -> dict[str, Any]:
    """Upload byte-bearing photo refs, then call the A2 Chatflow with verified file IDs."""
    if not photo_refs:
        result = _local_result("not_applicable")
        result["analysis_status"] = "not_configured"
        return result
    if not dify_configured(_AGENT_ID):
        return _local_result("not_configured", error="Dify A2 is not configured")
    if len(photo_refs) > _IMAGE_LIMIT:
        return _local_result(
            "photo_count_exceeds_workflow_limit",
            error=f"GEO识图-多图汇总 accepts at most {_IMAGE_LIMIT} images",
        )

    source_items, source_error = _photo_upload_items(data, photo_refs)
    if source_error:
        error = (
            "photo_uploads must supply one server-readable image payload for each photo_ref"
            if source_error == "source_bytes_unavailable"
            else "Photo upload payload does not match the durable references"
        )
        return _local_result(source_error, error=error)
    if len(source_items) != len(photo_refs):
        return _local_result("source_bytes_unavailable", error="Photo references and upload sources do not match")

    upload_sources = []
    for item in source_items:
        source, error = _decode_photo(item)
        if error:
            return _local_result(error, error=error)
        if source is None:
            return _local_result(
                "source_bytes_unavailable",
                error="Each photo_uploads item must include server-readable image bytes",
            )
        upload_sources.append(source)

    total_size = sum(len(source["content"]) for source in upload_sources)
    if total_size > _IMAGE_TOTAL_SIZE_LIMIT:
        return _local_result(
            "photo_payload_exceeds_dify_limit",
            error="Photo payload exceeds the total Dify upload limit",
        )

    contract_status = await _image_upload_contract_status()
    if contract_status:
        error = (
            "Published Dify A2 parameters do not enable local image input"
            if contract_status == "image_input_not_enabled"
            else "Unable to read the published Dify A2 input parameters"
        )
        return _local_result(contract_status, error=error)

    user = str(data.get("user_id") or correlation_id)
    file_ids: list[str] = []
    for source in upload_sources:
        uploaded = await upload_file(
            _AGENT_ID,
            filename=source["filename"],
            content=source["content"],
            mime_type=source["mime_type"],
            user=user,
        )
        file_id = uploaded.get("file_id") if isinstance(uploaded, dict) else None
        if isinstance(uploaded, dict) and uploaded.get("execution_engine") == "local":
            return {
                "execution_engine": "local",
                "status": uploaded.get("status") or "not_configured",
                "analysis_status": "pending_visual_model",
                "outputs": {},
                "uploaded_file_ids": file_ids,
                "trace_id": uploaded.get("trace_id"),
                "task_id": None,
                "workflow_run_id": None,
                "conversation_id": None,
                "error": uploaded.get("error"),
            }
        if not isinstance(file_id, str) or not file_id.strip() or uploaded.get("status") != "completed":
            return {
                "execution_engine": uploaded.get("execution_engine", "dify") if isinstance(uploaded, dict) else "dify",
                "status": "error",
                "analysis_status": "pending_visual_model",
                "outputs": {},
                "uploaded_file_ids": file_ids,
                "trace_id": uploaded.get("trace_id") if isinstance(uploaded, dict) else None,
                "task_id": None,
                "workflow_run_id": None,
                "conversation_id": None,
                "error": (
                    uploaded.get("error", "Dify file upload returned no file id")
                    if isinstance(uploaded, dict)
                    else "Dify file upload returned an invalid response"
                ),
            }
        file_ids.append(file_id.strip())

    # The export has no custom Start variables; its iteration reads the built-in sys.files.
    files = [
        {"type": "image", "transfer_method": "local_file", "upload_file_id": file_id}
        for file_id in file_ids
    ]
    conversation_id = data.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        conversation_id = None
    # Send the remaining field context through the real Chatflow input sys.query.
    run_result = await run_agent(
        _AGENT_ID,
        inputs={},
        user=user,
        query=_chat_query(
            narrative=narrative,
            admin_area=admin_area,
            gps=gps,
            visit_time=visit_time,
            hazard_point_id=hazard_point_id,
            slope_unit_id=slope_unit_id,
            source_kind=source_kind,
            is_simulated=is_simulated,
            data_source=data_source,
        ),
        conversation_id=conversation_id,
        files=files,
    )
    if not isinstance(run_result, dict):
        return {
            "execution_engine": "dify",
            "status": "error",
            "analysis_status": "pending_visual_model",
            "outputs": {},
            "uploaded_file_ids": file_ids,
            "trace_id": None,
            "task_id": None,
            "workflow_run_id": None,
            "conversation_id": conversation_id,
            "error": "Dify returned an invalid response",
        }

    status = str(run_result.get("status") or "error")
    base = {
        "execution_engine": run_result.get("execution_engine") or "dify",
        "status": status,
        "analysis_status": "pending_visual_model",
        "outputs": {},
        "uploaded_file_ids": file_ids,
        "trace_id": run_result.get("trace_id"),
        "task_id": run_result.get("task_id"),
        "workflow_run_id": run_result.get("workflow_run_id"),
        "conversation_id": run_result.get("conversation_id") or conversation_id,
        "error": run_result.get("error"),
    }
    if base["execution_engine"] != "dify":
        base["status"] = status or "not_configured"
        return base
    if status != "completed":
        return base

    outputs = _vision_outputs(run_result)
    if not outputs:
        base["status"] = "invalid_output"
        base["error"] = "Dify A2 response is missing aiReportDetail, aiRiskLabel, or aiVisionProps"
        return base
    base["analysis_status"] = "completed_dify"
    base["output_verification_status"] = "unverified"
    base["outputs"] = outputs
    return base
