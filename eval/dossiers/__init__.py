"""Dossiers patients de test, un par formulaire du catalogue."""

from .scenarios_ai import SCENARIOS as _AI
from .scenarios_laa import SCENARIOS as _LAA
from .scenarios_autres import SCENARIOS as _AUTRES

SCENARIOS = _AI + _LAA + _AUTRES

__all__ = ["SCENARIOS"]
