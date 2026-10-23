"""Small server-side Dify API client for the Yichang agents."""

import json
import re
import time
import uuid
from typing import Any

import httpx

from .config import settings
from .dify_registry import DifyApp, dify_configured, get_dify_app

_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?(?:</think\s*>|$)", re.IGNORECASE | re.DOTALL)


def _strip_think_blocks(value: Any) -> Any:
    if isinstance(value, str):
        return _THINK_BLOCK.sub("", value).strip()
    if isinstance(value, dict):
        return {key: _strip_think_blocks(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_strip_think_blocks(item) for item in value]
    return value


def _api_route(app_mode: str) -> str:
    mode = app_mode.strip().lower().replace("_", "-")
    if mode in {"advanced-chat", "chatflow", "chat"}:
        return "/v1/chat-messages"
    if mode == "workflow":
        return "/v1/workflows/run"
    raise ValueError(f"Unsupported Dify app mode: {app_mode}")


def _api_url(base_url: str, route: str) -> str:
    base = base_url.rstrip("/")
    if base.lower().endswith("/v1"):
        base = base[:-3]
    return f"{base}{route}"


def _parse_sse_lines(lines: list[str], app_mode: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    data_lines: list[str] = []

    def flush() -> None:
        if not data_lines:
            return
        raw = "\n".join(data_lines)
        data_lines.clear()
        if raw == "[DONE]":
            return
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return
        if isinstance(event, dict):
            events.append(event)

    for line in lines:
        if not line:
            flush()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    flush()

    result: dict[str, Any] = {}
    answer_chunks: list[str] = []
    for event in events:
        event_type = event.get("event")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        result.update({key: value for key, value in event.items() if key != "data"})
        if event_type == "message" and isinstance(event.get("answer"), str):
            answer_chunks.append(event["answer"])
        if event_type in {"workflow_finished", "message_end"}:
            result.update(data)
        if event_type == "error":
            result["stream_error"] = data or event
    if answer_chunks:
        result["answer"] = "".join(answer_chunks)
    if app_mode.strip().lower() == "workflow" and result.get("id"):
        result.setdefault("workflow_run_id", result["id"])
    return result


class DifyClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    @staticmethod
    def _headers(app: DifyApp) -> dict[str, str]:
        return {"Authorization": f"Bearer {app.api_key}"}

    @staticmethod
    def _request_body(
        app: DifyApp,
        *,
        inputs: dict[str, Any],
        user: str,
        query: str | None,
        conversation_id: str | None,
        files: list[dict[str, Any]] | None,
        response_mode: str,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"inputs": inputs, "response_mode": response_mode, "user": user}
        if _api_route(app.app_mode) == "/v1/chat-messages":
            body["query"] = query if query is not None else json.dumps(inputs, ensure_ascii=False)
            if conversation_id:
                body["conversation_id"] = conversation_id
            if files:
                body["files"] = files
        return body

    @staticmethod
    def _normalise(
        app: DifyApp,
        response: dict[str, Any],
        *,
        trace_id: str,
        duration_ms: int,
        stream_mode: bool,
    ) -> dict[str, Any]:
        data = response.get("data") if isinstance(response.get("data"), dict) else response
        outputs = data.get("outputs") if isinstance(data.get("outputs"), dict) else {}
        outputs = _strip_think_blocks(outputs)
        answer = _strip_think_blocks(data.get("answer") or response.get("answer"))
        error = response.get("stream_error") or response.get("error")
        status = "error" if error else str(data.get("status") or "completed")
        return {
            "agent_id": app.agent_id,
            "execution_engine": "dify",
            "dify_app": app.app_name,
            "app_name": app.app_name,
            "app_mode": app.app_mode,
            "app_role": app.app_role,
            "registry_id": app.registry_id,
            "status": status,
            "outputs": outputs,
            "response": answer if answer is not None else outputs,
            "conversation_id": data.get("conversation_id") or response.get("conversation_id"),
            "task_id": data.get("task_id") or response.get("task_id"),
            "workflow_run_id": (
                data.get("workflow_run_id")
                or response.get("workflow_run_id")
                or (data.get("id") if app.app_mode.strip().lower() == "workflow" else None)
            ),
            "message_id": data.get("message_id") or response.get("message_id"),
            "duration_ms": duration_ms,
            "trace_id": trace_id,
            "error": error,
            "streaming_aggregated": stream_mode,
        }

    async def run(
        self,
        app: DifyApp,
        *,
        base_url: str,
        inputs: dict[str, Any],
        user: str,
        query: str | None = None,
        conversation_id: str | None = None,
        files: list[dict[str, Any]] | None = None,
        timeout: float = 60.0,
        response_mode: str = "blocking",
    ) -> dict[str, Any]:
        trace_id = str(uuid.uuid4())
        started = time.perf_counter()
        stream_mode = response_mode.strip().lower() == "streaming"
        try:
            route = _api_route(app.app_mode)
            if response_mode not in {"blocking", "streaming"}:
                raise ValueError("DIFY_RESPONSE_MODE must be blocking or streaming")
            body = self._request_body(
                app,
                inputs=inputs,
                user=user,
                query=query,
                conversation_id=conversation_id,
                files=files,
                response_mode=response_mode,
            )
            url = _api_url(base_url, route)
            async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
                if stream_mode:
                    async with client.stream("POST", url, headers=self._headers(app), json=body) as response:
                        response.raise_for_status()
                        lines = [line async for line in response.aiter_lines()]
                        payload = _parse_sse_lines(lines, app.app_mode)
                else:
                    response = await client.post(url, headers=self._headers(app), json=body)
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError("Dify returned a non-object JSON response")
            return self._normalise(
                app,
                payload,
                trace_id=trace_id,
                duration_ms=int((time.perf_counter() - started) * 1000),
                stream_mode=stream_mode,
            )
        except (httpx.HTTPError, ValueError) as exc:
            status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            dify_error_code = None
            error_message = f"{type(exc).__name__}: {str(exc)[:300]}"
            if isinstance(exc, httpx.HTTPStatusError):
                try:
                    error_payload = exc.response.json()
                except ValueError:
                    error_payload = None
                if isinstance(error_payload, dict):
                    dify_error_code = error_payload.get("code")
                    detail = error_payload.get("message")
                    if isinstance(detail, str) and detail.strip():
                        error_message = f"{error_message}; Dify {dify_error_code or 'error'}: {detail.strip()[:240]}"
            return {
                "agent_id": app.agent_id,
                "execution_engine": "dify",
                "dify_app": app.app_name,
                "app_name": app.app_name,
                "app_mode": app.app_mode,
                "app_role": app.app_role,
                "registry_id": app.registry_id,
                "status": "error",
                "outputs": {},
                "response": None,
                "conversation_id": conversation_id,
                "task_id": None,
                "workflow_run_id": None,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "trace_id": trace_id,
                "http_status": status_code,
                "dify_error_code": dify_error_code,
                "error": error_message,
                "streaming_aggregated": stream_mode,
            }

    async def upload_file(
        self,
        app: DifyApp,
        *,
        base_url: str,
        filename: str,
        content: bytes,
        mime_type: str,
        user: str,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        trace_id = str(uuid.uuid4())
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
                response = await client.post(
                    _api_url(base_url, "/v1/files/upload"),
                    headers=self._headers(app),
                    data={"user": user},
                    files={"file": (filename, content, mime_type)},
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Dify returned a non-object upload response")
            return {
                "agent_id": app.agent_id,
                "execution_engine": "dify",
                "dify_app": app.app_name,
                "app_mode": app.app_mode,
                "app_role": app.app_role,
                "registry_id": app.registry_id,
                "status": "completed",
                "file_id": payload.get("id") or payload.get("upload_file_id"),
                "filename": payload.get("name") or filename,
                "trace_id": trace_id,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "error": None,
            }
        except (httpx.HTTPError, ValueError) as exc:
            status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            return {
                "agent_id": app.agent_id,
                "execution_engine": "dify",
                "dify_app": app.app_name,
                "app_mode": app.app_mode,
                "app_role": app.app_role,
                "registry_id": app.registry_id,
                "status": "error",
                "file_id": None,
                "trace_id": trace_id,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "http_status": status_code,
                "error": f"{type(exc).__name__}: {str(exc)[:400]}",
            }


async def run_agent(
    agent_id: str,
    *,
    inputs: dict[str, Any],
    user: str,
    query: str | None = None,
    conversation_id: str | None = None,
    files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    app = get_dify_app(agent_id)
    if not dify_configured(agent_id):
        return {
            "agent_id": app.agent_id,
            "execution_engine": "local",
            "dify_app": app.app_name,
            "app_name": app.app_name,
            "app_mode": app.app_mode,
            "app_role": app.app_role,
            "registry_id": app.registry_id,
            "status": "not_configured",
            "outputs": {},
            "response": None,
            "conversation_id": conversation_id,
            "task_id": None,
            "workflow_run_id": None,
            "duration_ms": 0,
            "trace_id": str(uuid.uuid4()),
            "error": "Dify base URL or this agent's server-side API key is not configured",
        }
    return await DifyClient().run(
        app,
        base_url=settings.dify_base_url,
        inputs=inputs,
        user=user,
        query=query,
        conversation_id=conversation_id,
        files=files,
        timeout=settings.dify_timeout_seconds,
        response_mode=settings.dify_response_mode,
    )


async def upload_file(
    agent_id: str,
    *,
    filename: str,
    content: bytes,
    mime_type: str,
    user: str,
) -> dict[str, Any]:
    app = get_dify_app(agent_id)
    if not dify_configured(agent_id):
        return {
            "agent_id": app.agent_id,
            "execution_engine": "local",
            "dify_app": app.app_name,
            "app_mode": app.app_mode,
            "app_role": app.app_role,
            "registry_id": app.registry_id,
            "status": "not_configured",
            "file_id": None,
            "trace_id": str(uuid.uuid4()),
            "duration_ms": 0,
            "error": "Dify base URL or this agent's server-side API key is not configured",
        }
    return await DifyClient().upload_file(
        app,
        base_url=settings.dify_base_url,
        filename=filename,
        content=content,
        mime_type=mime_type,
        user=user,
        timeout=settings.dify_timeout_seconds,
    )
