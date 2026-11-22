"""
/health: public liveness probe, build details only to an authenticated caller.

Without credentials the endpoint must not reveal version, commit or model;
container healthchecks only need a 200. The frontend (through the Pages proxy)
and the evaluation scripts send the key and still get the details. When
authentication is not configured nothing is detailed: the API is closed by
default (issue 36).
"""

import pytest
from fastapi.testclient import TestClient

import app as orchestrator
import auth

# Real authentication (auth.py), without the test identity of conftest.py.
pytestmark = pytest.mark.real_auth

KEY = "test-key"
DETAIL_FIELDS = {"version", "build", "commit", "built_at", "model", "forms"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "settings", auth.AuthSettings(api_key=KEY))
    return TestClient(orchestrator.app)


def test_health_without_key_is_minimal(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# Non-ASCII bytes used to reach compare_digest as a str and raise a TypeError.
@pytest.mark.parametrize("supplied", [b"wrong", b"", "clé".encode("utf-8")])
def test_health_with_bad_key_is_minimal(client, supplied):
    resp = client.get("/health", headers={"X-API-Key": supplied})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_with_key_has_details(client):
    resp = client.get("/health", headers={"X-API-Key": KEY})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert DETAIL_FIELDS <= body.keys()


def test_health_without_configured_auth_is_minimal(monkeypatch):
    # No API_KEY and no OIDC used to mean "no authentication anywhere".
    monkeypatch.setattr(auth, "settings", auth.AuthSettings())
    resp = TestClient(orchestrator.app).get("/health", headers={"X-API-Key": "anything"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_other_routes_still_require_the_key(client):
    assert client.get("/forms").status_code == 403
    assert client.get("/forms", headers={"X-API-Key": "wrong"}).status_code == 403
    assert client.get("/forms", headers={"X-API-Key": KEY}).status_code == 200
