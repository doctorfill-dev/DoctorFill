"""
Jeton de job non ASCII et erreurs du chat.

1. Un jeton de job contenant des caractères non ASCII faisait lever TypeError à
   secrets.compare_digest : les routes répondaient 500 au lieu de 403.
2. Sur erreur du LLM, /chat renvoyait au navigateur le texte brut de
   l'exception, qui contient l'URL interne du LLM ([SEC-10]).

Données fictives uniquement ; aucun réseau (transport httpx simulé).
"""

from __future__ import annotations

import logging
import secrets

import httpx
import pytest
from fastapi.testclient import TestClient

import app as orchestrator
from tests import fakes

JOB_ID = "jobfictif0001"
TOKEN = "jeton-fictif-123"
# URL fictive du LLM : elle ne doit jamais atteindre le navigateur.
LLM_URL = "http://llm-interne.invalid:8000/v1"
QUESTION = "Quel est le diagnostic de FICTIF Alice, née le 02.02.1985 ?"

NON_ASCII_TOKENS = [
    "jéton",
    TOKEN + "é",            # bon préfixe, puis un caractère accentué
    "é" * len(TOKEN),       # même longueur en caractères
    "🔑",
    "Testville-Genève",
]


@pytest.fixture
def job(tmp_path, monkeypatch):
    """Un job terminé, avec son PDF, ses champs et sa synthèse (fictifs)."""
    pdf = tmp_path / "output.pdf"
    pdf.write_bytes(b"%PDF-1.4 fictif")
    monkeypatch.setitem(orchestrator.JOBS, JOB_ID, {
        "status": "completed",
        "progress": 100,
        "token": TOKEN,
        "file_path": str(pdf),
        "_template_fields": [{"id": "1.1", "label": "Nom", "question": "Nom du patient ?"}],
        "_debug_results": [{"id": "1.1", "result": {"value": "FICTIF Alice"}}],
        "_debug_synthesis": {"patient": "FICTIF Alice", "ville": "Testville"},
    })
    monkeypatch.setattr(orchestrator, "VLLM_URL", LLM_URL)
    return JOB_ID


@pytest.fixture
def client():
    return TestClient(orchestrator.app)


def _call(client: TestClient, route: str, job_id: str, token: str) -> httpx.Response:
    """Appelle une route protégée par le jeton de job, là où elle l'attend."""
    if route == "fields":
        return client.get(f"/fields/{job_id}", params={"token": token})
    if route == "download":
        return client.get(f"/download/{job_id}", params={"token": token})
    if route == "debug":
        return client.get(f"/debug/{job_id}", params={"token": token})
    if route == "synthesis":
        return client.get(f"/synthesis/{job_id}", params={"token": token})
    if route == "synthesis/generate":
        return client.post(f"/synthesis/{job_id}/generate", params={"token": token})
    if route == "synthesis/update":
        return client.post(f"/synthesis/{job_id}/update", json={"token": token, "synthesis": {"a": 1}})
    if route == "synthesis/refine":
        return client.post(f"/synthesis/{job_id}/refine", json={"token": token, "instruction": "Plus court."})
    if route == "rerun":
        return client.post(f"/rerun/{job_id}", params={"token": token})
    if route == "chat":
        return client.post("/chat", json={"job_id": job_id, "message": "Bonjour", "token": token})
    raise AssertionError(route)


ROUTES = ["fields", "download", "debug", "synthesis", "synthesis/generate",
          "synthesis/update", "synthesis/refine", "rerun", "chat"]


# --- 1. Jeton de job non ASCII -------------------------------------------------------------

@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("token", NON_ASCII_TOKENS)
def test_non_ascii_job_token_is_refused_like_a_wrong_one(job, client, route, token):
    wrong = _call(client, route, job, "faux-jeton")
    resp = _call(client, route, job, token)
    assert wrong.status_code == 403
    # Même réponse qu'un mauvais jeton : rien ne distingue les deux cas.
    assert resp.status_code == 403, resp.text
    assert resp.json() == wrong.json() == {"detail": "Token invalide."}


@pytest.mark.parametrize("route", ["fields", "download", "debug", "synthesis", "synthesis/update"])
def test_the_right_token_still_opens_the_job(job, client, route):
    assert _call(client, route, job, TOKEN).status_code == 200


def test_job_token_is_compared_as_bytes_in_constant_time(monkeypatch):
    seen = []
    real = secrets.compare_digest

    def spy(a, b):
        seen.append((type(a), type(b)))
        return real(a, b)

    monkeypatch.setattr(secrets, "compare_digest", spy)
    assert orchestrator._job_token_matches(TOKEN, TOKEN)
    assert not orchestrator._job_token_matches("jéton", TOKEN)
    assert not orchestrator._job_token_matches("\ud800", TOKEN)
    # Toujours compare_digest (temps constant), toujours sur des octets.
    assert seen == [(bytes, bytes)] * 3


# --- 2. Erreurs du chat : message générique, détail dans les journaux --------------------

def _llm_answers_500(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/chat/completions"):
        return httpx.Response(500, text="erreur interne du LLM")
    return httpx.Response(404)


def _llm_unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(f"Connexion impossible à {request.url}", request=request)


def _llm_breaks_with_patient_data(request: httpx.Request) -> httpx.Response:
    # Une erreur quelconque dont le texte contiendrait des données du dossier.
    raise RuntimeError(f"réponse illisible : {QUESTION}")


@pytest.mark.parametrize("handler", [_llm_answers_500, _llm_unreachable, _llm_breaks_with_patient_data])
def test_chat_error_sends_a_generic_message(job, client, monkeypatch, caplog, handler):
    fakes.install(monkeypatch, handler)
    caplog.set_level(logging.INFO)

    resp = client.post("/chat", json={"job_id": job, "message": QUESTION, "token": TOKEN,
                                      "history": [{"role": "user", "content": "FICTIF Alice, Testville"}]})

    assert resp.status_code == 200          # flux SSE déjà ouvert : l'erreur passe dans le flux
    body = resp.text
    assert orchestrator.CHAT_ERROR_MESSAGE in body
    # Rien d'interne vers le navigateur : ni URL, ni hôte, ni texte d'exception.
    for leaked in (LLM_URL, "llm-interne", "/chat/completions", "500 Internal", "Connexion impossible",
                   "RuntimeError", "illisible"):
        assert leaked not in body, leaked

    # Le détail reste côté serveur, sans donnée personnelle.
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any(f"[chat/{job[:8]}]" in m for m in errors), errors
    for message in errors:
        assert "FICTIF Alice" not in message
        assert "02.02.1985" not in message
        assert "Testville" not in message


def test_chat_http_error_is_logged_with_its_status(job, client, monkeypatch, caplog):
    fakes.install(monkeypatch, _llm_answers_500)
    caplog.set_level(logging.INFO)
    client.post("/chat", json={"job_id": job, "message": QUESTION, "token": TOKEN})
    errors = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    # Utile pour diagnostiquer : le type d'erreur et le code HTTP du LLM.
    assert "HTTPStatusError" in errors and "500" in errors
