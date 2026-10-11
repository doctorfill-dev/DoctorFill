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
