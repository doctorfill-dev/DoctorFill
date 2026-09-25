"""
Services simulés (marker, TEI, vLLM) derrière un transport httpx.

Tout client httpx.AsyncClient créé pendant un test — par l'orchestrateur comme
par medical_synthesis — passe par le handler installé, sans réseau.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Callable

import httpx

Handler = Callable[[httpx.Request], httpx.Response]


def hashed_vector(text: str, dim: int = 32) -> list[float]:
    """Embedding déterministe par sac de mots, suffisant pour ordonner des extraits."""
    vec = [0.0] * dim
    for word in re.findall(r"\w+", text.lower()):
        vec[hash(word) % dim] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


def embed_response(request: httpx.Request) -> httpx.Response:
    texts = json.loads(request.content)["texts"]
    return httpx.Response(200, json={"embeddings": [hashed_vector(t) for t in texts]})


def rerank_response(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    query = set(re.findall(r"\w+", payload["query"].lower()))
    scored = [{"document": d, "score": len(query & set(re.findall(r"\w+", d.lower()))) / 10}
              for d in payload["documents"]]
    return httpx.Response(200, json={"results": sorted(scored, key=lambda r: -r["score"])})


def completion(content: str | dict) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    return httpx.Response(200, json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}]})


def uploaded_filename(request: httpx.Request) -> str:
    return re.search(r'filename="([^"]+)"', request.content.decode("latin-1")).group(1)


def schema_ids(request: httpx.Request) -> list[str]:
    """IDs demandés par un appel d'extraction (schéma JSON de la réponse)."""
    body = json.loads(request.content)
    return list(body["response_format"]["json_schema"]["schema"]["properties"])


def is_synthesis(request: httpx.Request) -> bool:
    return "médecin expert" in json.loads(request.content)["messages"][0]["content"]


def install(monkeypatch, handler: Handler) -> None:
    """Route tout httpx.AsyncClient vers `handler` et neutralise les attentes de reprise."""
    real_client = httpx.AsyncClient

    class MockedClient(real_client):
        def __init__(self, *args, **kwargs):
            kwargs.pop("limits", None)
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    async def _no_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(httpx, "AsyncClient", MockedClient)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
