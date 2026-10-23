import asyncio

import httpx

from .config import settings
from .yichang_contract import YICHANG_KB_IDS


async def retrieve(query: str, top_k: int | None = None, knowledge_base_ids: tuple[str, ...] | None = None) -> dict:
    payload = {
        "query": query,
        "search_mode": "hybrid",
        "final_top_k": top_k or settings.rag_top_k,
        "recall_top_k": max(settings.rag_top_k, top_k or settings.rag_top_k),
    }
    if knowledge_base_ids is None:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{settings.rag_base_url.rstrip('/')}/api/v1/retrieve", json=payload)
            response.raise_for_status()
            return response.json()

    requested = tuple(dict.fromkeys(knowledge_base_ids))
    if not requested or any(kb_id not in YICHANG_KB_IDS for kb_id in requested):
        raise ValueError("Yichang retrieval is limited to the configured three knowledge bases")

    async with httpx.AsyncClient(timeout=60) as client:
        async def retrieve_one(kb_id: str) -> dict:
            response = await client.post(
                f"{settings.rag_base_url.rstrip('/')}/api/v1/retrieve",
                json={**payload, "filters": {"knowledge_base_id": kb_id}},
            )
            response.raise_for_status()
            return response.json()

        responses = await asyncio.gather(*(retrieve_one(kb_id) for kb_id in requested))

    by_base = {}
    for kb_id, result in zip(requested, responses, strict=True):
        by_base[kb_id] = result

    # Interleave each KB's ranked results so one library cannot silently dominate
    # evidence from the other two; keep the source KB attached to every citation.
    ranked = []
    max_count = max((len(result.get("evidences", [])) for result in responses), default=0)
    for index in range(max_count):
        for kb_id, result in by_base.items():
            evidences = result.get("evidences", [])
            if index < len(evidences):
                ranked.append({**evidences[index], "knowledge_base_id": kb_id})

    final_top_k = payload["final_top_k"]
    return {
        "query": query,
        "evidences": ranked[:final_top_k],
        "retrieval": {
            "mode": "yichang_three_kb",
            "knowledge_base_ids": list(requested),
            "per_knowledge_base": {
                kb_id: result.get("retrieval", {}) for kb_id, result in by_base.items()
            },
        },
        "timing_ms": {
            key: sum(float(result.get("timing_ms", {}).get(key, 0) or 0) for result in responses)
            for key in {name for result in responses for name in result.get("timing_ms", {})}
        },
        "usage": {"per_knowledge_base": {kb_id: result.get("usage", {}) for kb_id, result in by_base.items()}},
        "final_context": "\n\n".join(result.get("final_context", "") for result in responses if result.get("final_context")),
    }


async def retrieve_yichang(query: str, top_k: int | None = None) -> dict:
    return await retrieve(query, top_k=top_k, knowledge_base_ids=YICHANG_KB_IDS)
