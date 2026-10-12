"""Dossiers patients de test : un par formulaire du catalogue, plus quelques variantes."""

from .scenarios_ai import SCENARIOS as _AI
from .scenarios_laa import SCENARIOS as _LAA
from .scenarios_autres import SCENARIOS as _AUTRES
from .scenarios_cas import SCENARIOS as _CAS

SCENARIOS = _AI + _LAA + _AUTRES + _CAS

__all__ = ["SCENARIOS"]
