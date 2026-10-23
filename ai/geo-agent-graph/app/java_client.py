"""Narrow client for the existing Java task API."""

import httpx

from .config import settings


async def create_reviewed_task(task: dict, *, human_approved: bool) -> dict:
    if human_approved is not True:
        return {"status": "awaiting_human_approval", "task_id": None}
    if not settings.java_backend_base_url or not settings.java_backend_bearer_token:
        return {"status": "java_api_not_configured", "task_id": None}

    headers = {"Authorization": f"Bearer {settings.java_backend_bearer_token}"}
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        response = await client.post(
            f"{settings.java_backend_base_url.rstrip('/')}/dizai/taskDistList",
            json=task,
        )
        response.raise_for_status()
        payload = response.json()

    if payload.get("code") != 200 or not isinstance(payload.get("data"), int):
        return {"status": "java_api_rejected", "task_id": None, "message": payload.get("msg")}
    return {"status": "created", "task_id": payload["data"]}


async def lookup_business_record(record_type: str, record_id: str | int) -> dict:
    if record_type not in {"task", "report"}:
        return {"status": "unsupported_record_type", "record": None}
    identifier = str(record_id)
    if not identifier.isdigit() or int(identifier) <= 0:
        return {"status": "invalid_java_record_id", "record": None}
    if not settings.java_backend_base_url or not settings.java_backend_bearer_token:
        return {"status": "java_api_not_configured", "record": None}

    headers = {"Authorization": f"Bearer {settings.java_backend_bearer_token}"}
    base = settings.java_backend_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        path = f"/dizai/taskDistList/{identifier}" if record_type == "task" else f"/dizai/reportDisaster/{identifier}"
        response = await client.get(f"{base}{path}")
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 200:
            return {"status": "java_api_rejected", "record": None, "message": result.get("msg")}
        record = result.get("data")
        if record_type == "task":
            feedback_response = await client.get(f"{base}/v1/tasks/feedbacks", params={"taskId": identifier})
            feedback_response.raise_for_status()
            feedback_result = feedback_response.json()
            feedbacks = feedback_result.get("data", []) if feedback_result.get("code") == 200 else []
            return {"status": "found" if record is not None else "not_found", "record": record,
                    "feedbacks": feedbacks, "feedback_status": "read" if feedback_result.get("code") == 200 else "unavailable"}
    return {"status": "found" if record is not None else "not_found", "record": record}


async def list_task_feedback(task_id: str | int) -> dict:
    identifier = str(task_id)
    if not identifier.isdigit() or int(identifier) <= 0:
        return {"status": "invalid_java_task_id", "task_id": None, "feedbacks": []}
    if not settings.java_backend_base_url or not settings.java_backend_bearer_token:
        return {"status": "java_api_not_configured", "task_id": int(identifier), "feedbacks": []}

    headers = {"Authorization": f"Bearer {settings.java_backend_bearer_token}"}
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        response = await client.get(
            f"{settings.java_backend_base_url.rstrip('/')}/v1/tasks/feedbacks",
            params={"taskId": identifier},
        )
        response.raise_for_status()
        result = response.json()
    if result.get("code") != 200:
        return {"status": "java_api_rejected", "task_id": int(identifier), "feedbacks": []}
    return {"status": "read", "task_id": int(identifier), "feedbacks": result.get("data", [])}


async def submit_reviewed_task_feedback(task_id: str | int, feedback: dict, *, human_approved: bool) -> dict:
    if human_approved is not True:
        return {"status": "awaiting_human_approval", "task_id": None, "readback": None}
    identifier = str(task_id)
    if not identifier.isdigit() or int(identifier) <= 0:
        return {"status": "invalid_java_task_id", "task_id": None, "readback": None}
    if not isinstance(feedback, dict) or feedback.get("status") is None:
        return {"status": "explicit_feedback_status_required", "task_id": int(identifier), "readback": None}
    if not str(feedback.get("textRecord") or "").strip() and not feedback.get("photos"):
        return {"status": "feedback_text_or_oss_photo_required", "task_id": int(identifier), "readback": None}
    if not settings.java_backend_base_url or not settings.java_backend_bearer_token:
        return {"status": "java_api_not_configured", "task_id": int(identifier), "readback": None}

    body = {**feedback, "taskId": int(identifier)}
    headers = {"Authorization": f"Bearer {settings.java_backend_bearer_token}"}
    base = settings.java_backend_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        response = await client.post(f"{base}/v1/tasks/submit", json=body)
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 200:
            return {"status": "java_api_rejected", "task_id": int(identifier), "message": result.get("msg"), "readback": None}
        readback = await client.get(f"{base}/v1/tasks/feedbacks", params={"taskId": identifier})
        readback.raise_for_status()
        readback_result = readback.json()

    histories = readback_result.get("data", []) if readback_result.get("code") == 200 else []
    expected_text = str(body.get("textRecord") or "").strip()
    expected_photos = [str(item) for item in body.get("photos", []) if item not in (None, "")]
    confirmed = any(
        str(item.get("taskId")) == identifier
        and (not expected_text or expected_text in str(item.get("textRecord", item.get("remark", ""))))
        and (not expected_photos or all(photo in str(item.get("scenePhoto", "")) for photo in expected_photos))
        for item in histories if isinstance(item, dict)
    )
    return {
        "status": "submitted_readback_confirmed" if confirmed else "submitted_readback_unverified",
        "task_id": int(identifier),
        "feedback_id": next((item.get("id") for item in histories if confirmed and str(item.get("taskId")) == identifier), None),
        "readback": "confirmed" if confirmed else "not_confirmed",
    }
