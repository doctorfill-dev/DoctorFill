"""
Identité, cloisonnement et journal d'audit (issue 36, audit S1, S9, S10, S16).

- un job d'un médecin répond 404 à tout autre utilisateur, de son cabinet ou
  d'un autre, sur les 12 routes de job (dont /fields en écriture et /validate,
  issue 37), même avec le bon jeton de job ;
- toute requête sans identité est refusée, quelle que soit la configuration ;
- un jeton OIDC expiré, mal signé, d'un autre émetteur ou d'une autre audience
  reçoit 401 ;
- le service refuse de démarrer sans authentification configurée ;
- chaque action laisse une ligne d'audit, sans nom de fichier ni valeur.

Fournisseur d'identité simulé : une paire de clés RSA créée pour les tests.
Identités et données fictives uniquement.
"""

from __future__ import annotations

import json
import logging
import time
import uuid

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import app as orchestrator
import audit
import auth
from tests import fakes

pytestmark = pytest.mark.real_auth

ISSUER = "https://idp.example.org"
AUDIENCE = "doctorfill-test"
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

A_USER, A_CABINET = "medecin-a@example.org", "cabinet-1"
B_USER, B_CABINET = "medecin-b@example.org", "cabinet-2"
JOB_TOKEN = "jeton-de-job-test"
TRAP_FILENAME = "Patient_Test_1970_rapport.pdf"


def make_token(user: str = A_USER, cabinet: str | None = A_CABINET, *, key=SIGNING_KEY,
               issuer: str = ISSUER, audience: str = AUDIENCE, expires_in: int = 300) -> str:
    now = int(time.time())
    claims = {"sub": user, "iss": issuer, "aud": audience, "iat": now, "exp": now + expires_in}
    if cabinet is not None:
        claims["cabinet_id"] = cabinet
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def oidc(monkeypatch):
    """OIDC configuré, clés du fournisseur simulé."""
    monkeypatch.setattr(auth, "settings", auth.AuthSettings(
        oidc_issuer=ISSUER, oidc_audience=AUDIENCE, oidc_jwks_url=ISSUER + "/jwks"))
    monkeypatch.setattr(auth, "key_resolver", lambda token: SIGNING_KEY.public_key())
    return TestClient(orchestrator.app)


@pytest.fixture
def audit_lines():
    """Lignes du journal d'audit émises pendant le test, décodées."""
    lines: list[dict] = []

    class Collect(logging.Handler):
        def emit(self, record):
            lines.append(json.loads(record.getMessage()))

    handler = Collect()
    audit.logger.addHandler(handler)
    yield lines
    audit.logger.removeHandler(handler)


@pytest.fixture
def job_of_a(tmp_path, monkeypatch) -> str:
    """Un job terminé du médecin A (cabinet 1)."""
    job_id = uuid.uuid4().hex
    pdf = tmp_path / "output.pdf"
    pdf.write_bytes(b"%PDF-1.4 formulaire de test")
    monkeypatch.setitem(orchestrator.JOBS, job_id, {
        "status": "completed", "token": JOB_TOKEN,
        "owner": {"user_id": A_USER, "cabinet_id": A_CABINET},
        "form_id": "Test", "_form_id": "Test", "file_path": str(pdf),
        # Non validé (issue 37) : /download sert l'aperçu.
        "preview_path": str(pdf),
        "_template_fields": [], "_debug_results": [],
        "_debug_synthesis": {"patient": {"nom": "Patient Test"}},
        "started_at": time.time(), "completed_at": time.time(),
    })
    return job_id


# Les 12 routes de job : (méthode, chemin, corps JSON).
def job_routes(job_id: str) -> list[tuple[str, str, dict | None]]:
    return [
        ("GET", f"/status/{job_id}", None),
        ("GET", f"/fields/{job_id}", None),
        ("POST", "/chat", {"job_id": job_id, "message": "Diagnostic ?"}),
        ("GET", f"/synthesis/{job_id}", None),
        ("POST", f"/synthesis/{job_id}/generate", None),
        ("POST", f"/synthesis/{job_id}/update", {"synthesis": {"patient": {}}}),
        ("POST", f"/synthesis/{job_id}/refine", {"instruction": "Corriger"}),
        ("POST", f"/rerun/{job_id}", None),
        ("GET", f"/download/{job_id}", None),
        ("GET", f"/debug/{job_id}", None),
        # Issue 37 : décisions du médecin et validation.
        ("POST", f"/fields/{job_id}", {"corrections": [{"id": "1.1", "action": "edit", "value": "Test"}]}),
        ("POST", f"/validate/{job_id}", None),
    ]


# --- Cloisonnement ------------------------------------------------------------------------

@pytest.mark.parametrize("other_user, other_cabinet", [(B_USER, B_CABINET), (B_USER, A_CABINET)],
                         ids=["autre-cabinet", "meme-cabinet"])
def test_a_job_is_invisible_to_anyone_but_its_owner(oidc, job_of_a, other_user, other_cabinet, audit_lines):
    headers = {**bearer(make_token(other_user, other_cabinet)), "X-Job-Token": JOB_TOKEN}
    for method, path, body in job_routes(job_of_a):
        resp = oidc.request(method, path, headers=headers, json=body)
        assert resp.status_code == 404, (method, path, resp.status_code)
    # Rien n'a été modifié ni lancé par ces appels.
    job = orchestrator.JOBS[job_of_a]
    assert job["status"] == "completed" and job["_debug_synthesis"] == {"patient": {"nom": "Patient Test"}}
    assert "validation" not in job and "final_path" not in job
    assert len(audit_lines) == len(job_routes(job_of_a)) == 12
    assert all(line["result"] == "not_found" and line["user_id"] == other_user for line in audit_lines)


def test_the_owner_reads_the_job_with_the_job_token(oidc, job_of_a):
    headers = {**bearer(make_token()), "X-Job-Token": JOB_TOKEN}
    for path in (f"/status/{job_of_a}", f"/fields/{job_of_a}", f"/synthesis/{job_of_a}",
                 f"/download/{job_of_a}", f"/debug/{job_of_a}"):
        assert oidc.get(path, headers=headers).status_code == 200, path


def test_the_owner_still_needs_the_job_token(oidc, job_of_a):
    # Octets non ASCII : compare_digest refuse une chaîne non ASCII (TypeError, donc 500).
    for headers in ({}, {"X-Job-Token": "faux"}, {"X-Job-Token": "jéton".encode("utf-8")}):
        resp = oidc.get(f"/fields/{job_of_a}", headers={**bearer(make_token()), **headers})
        assert resp.status_code == 403
    # Dans l'URL, le jeton n'est plus lu (journaux d'accès).
    resp = oidc.get(f"/fields/{job_of_a}", headers=bearer(make_token()), params={"token": JOB_TOKEN})
    assert resp.status_code == 403


def test_status_requires_the_job_token(oidc, job_of_a):
    """/status renvoyait progression et avertissements (noms de fichiers) sans jeton."""
    assert oidc.get(f"/status/{job_of_a}", headers=bearer(make_token())).status_code == 403


# --- Requêtes sans identité ----------------------------------------------------------------

def _protected_routes():
    return [r for r in orchestrator.app.routes
            if isinstance(r, APIRoute) and r.path != "/health"]


def test_every_route_but_health_depends_on_authentication():
    routes = _protected_routes()
    assert len(routes) >= 13
    for route in routes:
        calls = [d.call for d in route.dependant.dependencies]
        assert auth.current_principal in calls, route.path


def _call_every_route(client: TestClient, headers: dict) -> dict[str, int]:
    seen = {}
    for route in _protected_routes():
        path = route.path.replace("{job_id}", uuid.uuid4().hex)
        for method in route.methods:
            seen[f"{method} {route.path}"] = client.request(method, path, headers=headers).status_code
    return seen


@pytest.mark.parametrize("settings, expected", [
    (auth.AuthSettings(), 503),                                    # rien de configuré : fermé
    (auth.AuthSettings(api_key="cle-de-test"), 403),               # clé partagée transitoire
    (auth.AuthSettings(oidc_issuer=ISSUER, oidc_audience=AUDIENCE, oidc_jwks_url=ISSUER + "/jwks"), 401),
], ids=["non-configure", "cle-partagee", "oidc"])
def test_requests_without_credentials_are_refused_whatever_the_configuration(monkeypatch, settings, expected):
    monkeypatch.setattr(auth, "settings", settings)
    monkeypatch.setattr(auth, "key_resolver", lambda token: SIGNING_KEY.public_key())
    seen = _call_every_route(TestClient(orchestrator.app), {})
    assert seen and all(code == expected for code in seen.values()), seen


@pytest.mark.parametrize("token", [
    make_token(expires_in=-120),                       # expiré (au-delà de la tolérance)
    make_token(key=OTHER_KEY),                         # signé par une autre clé
    make_token(issuer="https://autre-idp.example.org"),
    make_token(audience="autre-application"),
    jwt.encode({"sub": A_USER, "iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 300,
                "cabinet_id": A_CABINET}, key=None, algorithm="none"),
    "pas-un-jeton",
], ids=["expire", "mauvaise-signature", "autre-emetteur", "autre-audience", "alg-none", "illisible"])
def test_invalid_oidc_tokens_get_401(oidc, token):
    resp = oidc.get("/forms", headers=bearer(token))
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_a_token_without_cabinet_is_refused(oidc):
    assert oidc.get("/forms", headers=bearer(make_token(cabinet=None))).status_code == 403


def test_a_valid_token_is_accepted(oidc):
    assert oidc.get("/forms", headers=bearer(make_token())).status_code == 200


def test_both_mechanisms_are_required_when_both_are_configured(monkeypatch):
    monkeypatch.setattr(auth, "settings", auth.AuthSettings(
        api_key="cle-de-test", oidc_issuer=ISSUER, oidc_audience=AUDIENCE, oidc_jwks_url=ISSUER + "/jwks"))
    monkeypatch.setattr(auth, "key_resolver", lambda token: SIGNING_KEY.public_key())
    client = TestClient(orchestrator.app)
    assert client.get("/forms", headers=bearer(make_token())).status_code == 403
    assert client.get("/forms", headers={"X-API-Key": "cle-de-test"}).status_code == 401
    assert client.get("/forms", headers={**bearer(make_token()), "X-API-Key": "cle-de-test"}).status_code == 200


# --- Démarrage fermé par défaut -------------------------------------------------------------

def test_startup_fails_without_authentication(monkeypatch):
    monkeypatch.setattr(auth, "settings", auth.AuthSettings())
    with pytest.raises(auth.AuthConfigError):
        with TestClient(orchestrator.app):
            pass


@pytest.mark.parametrize("settings", [
    auth.AuthSettings(),
    auth.AuthSettings(oidc_issuer=ISSUER),                              # OIDC incomplet
    auth.AuthSettings(oidc_issuer=ISSUER, oidc_audience=AUDIENCE),
])
def test_incomplete_configuration_is_rejected(settings):
    with pytest.raises(auth.AuthConfigError):
        auth.check_settings(settings)


def test_settings_are_read_from_the_environment():
    settings = auth.AuthSettings.from_env({"OIDC_ISSUER": ISSUER, "OIDC_AUDIENCE": AUDIENCE,
                                           "OIDC_JWKS_URL": ISSUER + "/jwks", "OIDC_CABINET_CLAIM": "groupe"})
    auth.check_settings(settings)
    assert settings.oidc_enabled and settings.cabinet_claim == "groupe" and not settings.api_key


def test_swagger_is_disabled_by_default():
    client = TestClient(orchestrator.app)
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


# --- Quota par utilisateur -----------------------------------------------------------------

def test_active_jobs_are_limited_per_user(oidc, monkeypatch):
    monkeypatch.setattr(orchestrator, "VALID_FORM_IDS", {"Test"})
    for _ in range(orchestrator.MAX_ACTIVE_JOBS_PER_USER):
        monkeypatch.setitem(orchestrator.JOBS, uuid.uuid4().hex, {
            "status": "processing", "owner": {"user_id": A_USER, "cabinet_id": A_CABINET}})
    files = {"report_files": ("a.pdf", b"%PDF-1.4", "application/pdf")}
    resp = oidc.post("/process-form", headers=bearer(make_token()), files=files, data={"form_id": "Test"})
    assert resp.status_code == 429


# --- Journal d'audit -----------------------------------------------------------------------

def test_every_action_is_audited_without_file_names_or_values(oidc, job_of_a, tmp_path, monkeypatch,
                                                              audit_lines):
    # Création : le pipeline échoue tout de suite (services simulés en panne), seul
    # compte ici ce que la création laisse au journal.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(orchestrator, "VALID_FORM_IDS", {"Test"})
    fakes.install(monkeypatch, lambda request: httpx.Response(500))
    files = {"report_files": (TRAP_FILENAME, b"%PDF-1.4 Patient Test", "application/pdf")}
    created = oidc.post("/process-form", headers=bearer(make_token()), files=files, data={"form_id": "Test"})
    assert created.status_code == 200
    new_job = created.json()["job_id"]
    orchestrator.JOBS.pop(new_job, None)

    headers = {**bearer(make_token()), "X-Job-Token": JOB_TOKEN}
    for path in (f"/fields/{job_of_a}", f"/synthesis/{job_of_a}", f"/download/{job_of_a}"):
        assert oidc.get(path, headers=headers).status_code == 200
    oidc.post(f"/synthesis/{job_of_a}/update", headers=headers, json={"synthesis": {"patient": {}}})
    oidc.get(f"/fields/{job_of_a}", headers={**bearer(make_token()), "X-Job-Token": "faux"})

    actions = [(line["action"], line["result"]) for line in audit_lines]
    assert actions == [("job.create", "ok"), ("fields.read", "ok"), ("synthesis.read", "ok"),
                       # Job non validé (issue 37) : l'aperçu, journalisé comme tel.
                       ("pdf.preview", "ok"), ("synthesis.update", "ok"), ("fields.read", "denied")]
    first = audit_lines[0]
    assert first["user_id"] == A_USER and first["cabinet_id"] == A_CABINET and first["auth"] == "oidc"
    assert first["form_id"] == "Test" and first["job_id"] == new_job
    assert all(line["job_id"] == job_of_a for line in audit_lines[1:])
    dumped = json.dumps(audit_lines, ensure_ascii=False)
    assert TRAP_FILENAME not in dumped and "Patient" not in dumped and JOB_TOKEN not in dumped
    assert set(first) == {"ts", "user_id", "cabinet_id", "auth", "action", "form_id", "job_id", "result"}


def test_an_unknown_job_id_is_not_copied_into_the_audit_log(oidc, audit_lines):
    oidc.get("/status/../../etc", headers=bearer(make_token()))
    oidc.get("/status/pas-un-identifiant", headers=bearer(make_token()))
    assert [line["job_id"] for line in audit_lines] == ["invalide"]
