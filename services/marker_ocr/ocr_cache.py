"""
Cache OCR en mémoire, borné en taille et en durée.

Le texte d'un document médical est une donnée de santé. Le cache ne doit donc
pas vivre plus longtemps que le job qui l'a produit : chaque entrée expire après
`ttl_seconds` (par défaut la rétention des jobs de l'orchestrateur, 1 h).

Il n'écrit plus rien sur disque. L'ancienne version gardait un JSON par
document, texte intégral, dans le volume des modèles, sans aucune purge.
`purge_legacy_disk_cache` supprime ces fichiers au démarrage du service.
"""

from __future__ import annotations

import logging
import re
import time
from collections import OrderedDict
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# Ancien emplacement du cache disque (dans le volume des modèles marker).
LEGACY_CACHE_DIR = Path("/root/.cache/datalab/doctorfill_ocr")

# Nom d'une entrée de l'ancien cache : empreinte SHA-256 du PDF, en hexadécimal.
_LEGACY_ENTRY = re.compile(r"^[0-9a-f]{64}\.json$")


class OcrCache:
    """Résultats OCR par empreinte du PDF, en mémoire seulement."""

    def __init__(self, max_entries: int, ttl_seconds: float,
                 clock: Callable[[], float] = time.monotonic):
        self.max_entries = max(0, int(max_entries))
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, dict]] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return self.max_entries > 0 and self.ttl_seconds > 0

    def __len__(self) -> int:
        return len(self._entries)

    def purge_expired(self) -> int:
        """Supprime les entrées expirées. Retourne leur nombre."""
        now = self._clock()
        expired = [key for key, (stored_at, _) in self._entries.items()
                   if now - stored_at >= self.ttl_seconds]
        for key in expired:
            del self._entries[key]
        return len(expired)

    def get(self, content_hash: str) -> dict | None:
        self.purge_expired()
        entry = self._entries.get(content_hash)
        return dict(entry[1]) if entry is not None else None

    def put(self, content_hash: str, payload: dict) -> None:
        if not self.enabled:
            return
        self.purge_expired()
        self._entries.pop(content_hash, None)
        while len(self._entries) >= self.max_entries:
            self._entries.popitem(last=False)
        # La date d'origine ne change pas sur un « hit » : une entrée relue sans
        # cesse expire quand même.
        self._entries[content_hash] = (self._clock(), dict(payload))

    def clear(self) -> None:
        self._entries.clear()


def purge_legacy_disk_cache(directory: Path = LEGACY_CACHE_DIR) -> int:
    """
    Supprime les entrées de l'ancien cache disque.

    Seuls les fichiers `<sha256>.json` sont touchés : le dossier est dans le
    volume des modèles, rien d'autre ne doit en disparaître. Retourne le nombre
    de fichiers supprimés.
    """
    if not directory.is_dir():
        return 0
    removed = 0
    for entry in directory.iterdir():
        if not _LEGACY_ENTRY.match(entry.name) or not entry.is_file():
            continue
        try:
            entry.unlink()
            removed += 1
        except OSError as exc:
            logger.warning("Ancien cache OCR : suppression impossible (%s)", type(exc).__name__)
    try:
        directory.rmdir()          # seulement s'il est vide
    except OSError:
        pass
    return removed
