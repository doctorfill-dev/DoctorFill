"""
services/docker-compose.yml : aucun port publié hors de la boucle locale
(issue 33, audit S6).

"8080:8080" publie l'API sur toutes les interfaces de la machine, IPv6
comprise. Seul le reverse proxy (ou le relais) de la machine doit la joindre.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
LOOPBACK = ("127.0.0.1", "::1", "[::1]")


def _services():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def _published(services):
    for name, service in services.items():
        for port in service.get("ports") or []:
            yield name, port


def _host_ip(port) -> str:
    if isinstance(port, dict):                # syntaxe longue
        return str(port.get("host_ip", ""))
    text = str(port)
    # "IP:hôte:conteneur" ; "hôte:conteneur" ou "conteneur" seuls = toutes les interfaces.
    return text.rsplit(":", 2)[0] if text.count(":") >= 2 else ""


def test_published_ports_are_bound_to_loopback():
    published = list(_published(_services()))
    assert published, "l'orchestrateur doit rester joignable par la machine elle-même"
    for name, port in published:
        assert _host_ip(port) in LOOPBACK, f"{name} : port {port} publié sur toutes les interfaces"


def test_only_the_orchestrator_publishes_a_port():
    assert {name for name, _ in _published(_services())} == {"orchestrator"}
