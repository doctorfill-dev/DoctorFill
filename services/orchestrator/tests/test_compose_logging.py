"""
services/docker-compose.yml : journaux des conteneurs bornés (#32, audit S7).

Sans options de journalisation, Docker garde les journaux de chaque conteneur
sans limite de taille ni de durée.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


@pytest.fixture(scope="module")
def services():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def test_every_service_rotates_its_logs(services):
    for name, service in services.items():
        logging_conf = service.get("logging") or {}
        options = logging_conf.get("options") or {}
        assert logging_conf.get("driver") == "json-file", name
        assert options.get("max-size"), name
        assert options.get("max-file"), name


def test_ocr_cache_expires_with_the_jobs(services):
    env = services["marker_ocr"].get("environment") or {}
    assert "OCR_CACHE_TTL_SECONDS" in env
    assert "JOB_RETENTION_SECONDS" in str(env["OCR_CACHE_TTL_SECONDS"])
