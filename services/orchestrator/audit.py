"""
Journal d'audit : qui a fait quoi, sur quel job, avec quel résultat (issue 36).

Une ligne JSON par action, sur un journal séparé des journaux applicatifs :
horodatage, utilisateur, cabinet, mode d'authentification, action, formulaire,
job, résultat. **Jamais** de nom de fichier, de valeur de champ, de message
du chat ni de texte de dossier.

AUDIT_LOG_PATH : fichier du journal (une ligne par action). Sans lui, la
sortie standard du conteneur. Durée de conservation : à fixer dans l'issue 32.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone

LOGGER_NAME = "doctorfill.audit"
logger = logging.getLogger(LOGGER_NAME)

# Un identifiant de job valide (uuid4 en hexadécimal). Toute autre valeur vient
# de l'appelant et n'est pas recopiée telle quelle.
_JOB_ID = re.compile(r"[0-9a-f]{32}")


def configure(path: str | None = None) -> None:
    """Branche le journal sur son fichier (ou la sortie standard). Idempotent."""
    if getattr(logger, "_doctorfill_configured", False):
        return
    path = os.getenv("AUDIT_LOG_PATH", "") if path is None else path
    handler: logging.Handler = logging.FileHandler(path, encoding="utf-8") if path \
        else logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # Ni mêlé aux journaux applicatifs, ni dupliqué par le logger racine.
    logger.propagate = False
    logger._doctorfill_configured = True  # type: ignore[attr-defined]


def _job_ref(job_id: str | None) -> str | None:
    if job_id is None:
        return None
    return job_id if _JOB_ID.fullmatch(job_id) else "invalide"


def record(principal, action: str, *, job_id: str | None = None, form_id: str | None = None,
           result: str = "ok", field_id: str | None = None) -> None:
    """
    Une action au journal.

    `principal` : l'appelant (auth.Principal), ou None s'il n'a pas pu être identifié.
    `result` : ok, denied (jeton de job invalide), not_found (job inconnu ou
    d'un autre cabinet), refused (refus métier : quota, formulaire inconnu…).
    `field_id` : identifiant du champ du gabarit (« 1.2 »), pour les décisions
    du médecin (issue 37). Jamais sa valeur. N'apparaît que s'il est donné ;
    l'appelant ne passe qu'un identifiant présent dans le gabarit.
    """
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user_id": getattr(principal, "user_id", None),
        "cabinet_id": getattr(principal, "cabinet_id", None),
        "auth": getattr(principal, "method", None),
        "action": action,
        "form_id": form_id,
        "job_id": _job_ref(job_id),
        "result": result,
    }
    if field_id is not None:
        entry["field_id"] = field_id
    logger.info(json.dumps(entry, ensure_ascii=False, sort_keys=True))
