"""
Service d'embeddings et de rerank (app.py).

torch et sentence-transformers sont remplacés avant l'import : pas de GPU, pas
de téléchargement de modèle. Les « modèles » simulés sont déterministes —
l'embedding d'un texte vaut [longueur, 1], le score de rerank le nombre de mots
communs avec la requête — ce qui suffit à vérifier l'ordre et le format.
"""

from __future__ import annotations

import sys
import types

import pytest
from fastapi.testclient import TestClient


class _Array(list):
    """Imite le tableau numpy rendu par les modèles (méthode tolist)."""

    def tolist(self):
        return list(self)


class FakeEmbedder:
    def __init__(self, name, device=None):
        self.name, self.device = name, device
        self.calls: list = []

    def encode(self, texts, normalize_embeddings=False):
        self.calls.append({"texts": list(texts), "normalize_embeddings": normalize_embeddings})
        return _Array([[float(len(t)), 1.0] for t in texts])


class FakeReranker:
    def __init__(self, name, device=None):
        self.name, self.device = name, device

    def predict(self, pairs):
        return _Array([float(len(set(q.lower().split()) & set(d.lower().split()))) for q, d in pairs])


def _stub_models() -> None:
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    st = types.ModuleType("sentence_transformers")
    st.SentenceTransformer = FakeEmbedder
    st.CrossEncoder = FakeReranker
    sys.modules.update({"torch": torch, "sentence_transformers": st})


_stub_models()

import app as tei_app  # noqa: E402


@pytest.fixture
def models(monkeypatch):
    embedder = FakeEmbedder("embed-fictif", "cpu")
    monkeypatch.setattr(tei_app, "embedder", embedder)
    monkeypatch.setattr(tei_app, "reranker", FakeReranker("rerank-fictif", "cpu"))
    return embedder


def test_health_before_models_are_loaded(monkeypatch):
    monkeypatch.setattr(tei_app, "embedder", None)
    monkeypatch.setattr(tei_app, "reranker", None)
    body = TestClient(tei_app.app).get("/health").json()
    assert body == {"status": "ok", "service": "tei", "models_loaded": False}


def test_startup_loads_both_models_on_the_available_device(monkeypatch):
    monkeypatch.setattr(tei_app, "embedder", None)
    monkeypatch.setattr(tei_app, "reranker", None)
    with TestClient(tei_app.app) as client:
        assert client.get("/health").json()["models_loaded"] is True
    assert tei_app.embedder.name == tei_app.EMBED_MODEL_NAME
    assert tei_app.reranker.name == tei_app.RERANK_MODEL_NAME
    assert tei_app.embedder.device == tei_app.reranker.device == "cpu"


def test_embed_returns_normalised_vectors_in_order(models):
    resp = TestClient(tei_app.app).post("/embed", json={"texts": ["a", "bb", "ccc"]})
    assert resp.status_code == 200
    assert resp.json() == {"embeddings": [[1.0, 1.0], [2.0, 1.0], [3.0, 1.0]]}
    assert models.calls == [{"texts": ["a", "bb", "ccc"], "normalize_embeddings": True}]


def test_rerank_sorts_by_decreasing_score(models):
    resp = TestClient(tei_app.app).post("/rerank", json={
        "query": "entorse cheville",
        "documents": ["rendez-vous fictif", "entorse de la cheville", "entorse simple"],
    })
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert [r["document"] for r in results] == ["entorse de la cheville", "entorse simple", "rendez-vous fictif"]
    assert [r["score"] for r in results] == [2.0, 1.0, 0.0]


def test_empty_requests_are_answered(models):
    client = TestClient(tei_app.app)
    assert client.post("/embed", json={"texts": []}).json() == {"embeddings": []}
    assert client.post("/rerank", json={"query": "q", "documents": []}).json() == {"results": []}


@pytest.mark.parametrize("route, payload", [
    ("/embed", {"texts": "pas une liste"}),
    ("/embed", {}),
    ("/rerank", {"query": "q"}),
])
def test_malformed_requests_are_rejected(models, route, payload):
    assert TestClient(tei_app.app).post(route, json=payload).status_code == 422
