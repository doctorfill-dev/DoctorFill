"""
services/docker-compose.yml : seul l'orchestrateur reçoit le fichier .env
(issue 36, audit S17).

Le .env porte la clé d'API et la configuration d'authentification. Un service
qui n'en a pas besoin (TEI, OCR, vLLM) ne doit pas les avoir dans son
environnement.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
SECRET_NAMES = ("API_KEY", "OIDC", "TOKEN", "SECRET", "PASSWORD")


def _services():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def test_only_the_orchestrator_reads_the_env_file():
    readers = {name for name, service in _services().items() if service.get("env_file")}
    assert readers == {"orchestrator"}


def test_tei_gets_only_its_model_names():
    env = _services()["tei"].get("environment") or {}
    assert set(env) == {"EMBED_MODEL_NAME", "RERANK_MODEL_NAME"}


def test_no_other_service_is_given_a_secret():
    for name, service in _services().items():
        if name == "orchestrator":
            continue
        env = service.get("environment") or {}
        keys = env if isinstance(env, dict) else [str(item).split("=", 1)[0] for item in env]
        for key in keys:
            assert not any(word in str(key).upper() for word in SECRET_NAMES), f"{name} : {key}"
