"""
Configuration commune des tests de l'orchestrateur.

Les tests tournent sans GPU ni service : OCR, TEI et vLLM sont simulés par un
transport httpx (voir test_pipeline.py). Seuls pikepdf, pypdf et chromadb —
dépendances de l'orchestrateur — sont requis.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ORCHESTRATOR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ORCHESTRATOR_DIR))

# Avant l'import de app : ses répertoires de travail sont créés au chargement.
_scratch = Path(tempfile.mkdtemp(prefix="doctorfill-tests-"))
os.environ.setdefault("DEBUG_LOG_DIR", str(_scratch / "debug"))
os.environ.setdefault("STATS_DIR", str(_scratch / "stats"))
os.environ.setdefault("JOBS_DIR", str(_scratch / "jobs"))
os.environ.setdefault("API_KEY", "")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import pytest  # noqa: E402

# Identité des tests : un médecin fictif d'un cabinet fictif. Les routes
# protégées la reçoivent sans authentification réelle, sauf pour les tests
# marqués `real_auth` (test_auth.py), qui passent par auth.py.
TEST_USER = "medecin-test@example.org"
TEST_CABINET = "cabinet-test"


def pytest_configure(config):
    config.addinivalue_line("markers", "real_auth: authentification réelle, sans identité de test injectée")


@pytest.fixture(autouse=True)
def _test_principal(request):
    if request.node.get_closest_marker("real_auth"):
        yield None
        return
    import app as orchestrator
    import auth
    principal = auth.Principal(user_id=TEST_USER, cabinet_id=TEST_CABINET, method="oidc")
    orchestrator.app.dependency_overrides[auth.current_principal] = lambda: principal
    yield principal
    orchestrator.app.dependency_overrides.pop(auth.current_principal, None)
