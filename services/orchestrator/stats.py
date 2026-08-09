"""
stats.py — Durées des pipelines menés à terme.

Seule donnée que DoctorFill conserve d'une exécution à l'autre : la durée, le
formulaire visé et le nombre de documents. Aucun contenu de dossier, aucune
identité, rien qui touche au patient.

Deux usages : afficher au clinicien à quoi s'attendre pendant qu'il patiente, et
donner un repère de performance. Une dérive du temps moyen signale une
régression avant que quiconque s'en plaigne.

Les exécutions en échec ne sont pas comptées : leur durée ne dit rien du coût
d'un dossier traité, et les inclure fausserait la moyenne vers le bas.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Monté en volume (voir docker-compose) : sans quoi l'historique disparaît au
# premier redéploiement, ce qui est précisément ce qu'on veut éviter.
STATS_DIR = Path(os.getenv("STATS_DIR", "/data/stats"))
RUNS_FILE = STATS_DIR / "pipeline_runs.jsonl"

# Fenêtre de la moyenne « récente », en nombre d'exécutions. La moyenne globale
# encaisse mal un changement de matériel ou de modèle ; celle-ci le suit.
RECENT_WINDOW = 20

_lock = threading.Lock()


def record_run(form_id: str, documents: int, seconds: float) -> None:
    """Enregistre une exécution terminée. N'échoue jamais l'appelant."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "form_id": form_id,
        "documents": documents,
        "seconds": round(seconds, 1),
    }
    try:
        with _lock:
            STATS_DIR.mkdir(parents=True, exist_ok=True)
            with RUNS_FILE.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        # Une statistique perdue ne doit jamais faire échouer un job abouti.
        logger.warning("Durée non enregistrée : %s", exc)


def _load() -> list[dict[str, Any]]:
    try:
        with RUNS_FILE.open(encoding="utf-8") as handle:
            runs = []
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    runs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # ligne tronquée par un arrêt brutal : on l'ignore
            return runs
    except OSError:
        return []


def summary(form_id: str | None = None) -> dict[str, Any]:
    """
    Repères de durée, éventuellement restreints à un formulaire.

    Returns:
        runs, average_seconds, recent_average_seconds, average_seconds_per_document,
        last_seconds — tous nuls tant qu'aucune exécution n'a abouti.
    """
    runs = _load()
    if form_id:
        runs = [r for r in runs if r.get("form_id") == form_id]
    durations = [r["seconds"] for r in runs if isinstance(r.get("seconds"), (int, float))]
    if not durations:
        return {"runs": 0, "average_seconds": None, "recent_average_seconds": None,
                "average_seconds_per_document": None, "last_seconds": None}

    documents = sum(r.get("documents") or 0 for r in runs)
    recent = durations[-RECENT_WINDOW:]
    return {
        "runs": len(durations),
        "average_seconds": round(sum(durations) / len(durations), 1),
        "recent_average_seconds": round(sum(recent) / len(recent), 1),
        "average_seconds_per_document": round(sum(durations) / documents, 1) if documents else None,
        "last_seconds": durations[-1],
    }
