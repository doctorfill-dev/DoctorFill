"""
Service OCR (app.py) : aiguillage couche texte / OCR, cache, nettoyage, erreurs.

marker et ses modèles ne sont pas chargés : les modules `marker.*` sont
remplacés avant l'import de app.py, et l'OCR par une fonction qui rend un
texte fictif. Seuls fastapi, python-multipart, httpx et pypdfium2 sont requis.
"""

from __future__ import annotations

import hashlib
import json
import sys
import types

import pytest
from fastapi.testclient import TestClient


class FakeConverter:
    """Remplace marker.converters.pdf.PdfConverter : pas de modèle, pas de GPU."""

    def __init__(self, artifact_dict=None):
        self.artifact_dict = artifact_dict

    def __call__(self, file_path):
        return "# Texte OCR fictif"


def _stub_marker() -> None:
    modules = {name: types.ModuleType(name) for name in
               ("marker", "marker.converters", "marker.converters.pdf", "marker.models", "marker.output")}
    modules["marker.converters.pdf"].PdfConverter = FakeConverter
    modules["marker.models"].create_model_dict = lambda: {"modeles": "fictifs"}
    modules["marker.output"].text_from_rendered = lambda rendered: (rendered, "md", {})
    sys.modules.update(modules)


_stub_marker()

import app as marker_app  # noqa: E402

REAL_RUN_MARKER = marker_app._run_marker
PDF = b"%PDF-1.4\n% document fictif\n"
NATIVE = "## Page 1\n\nTexte natif fictif, couche texte exploitable."


@pytest.fixture
def service(tmp_path, monkeypatch):
    """Service isolé : cache et dossier d'upload temporaires, OCR enregistré."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(marker_app, "OCR_CACHE", {})
    monkeypatch.setattr(marker_app, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(marker_app, "UPLOAD_DIR", str(uploads))
    monkeypatch.setattr(marker_app, "FORCE_OCR", False)
    ocr_calls: list = []

    def fake_marker(path):
        ocr_calls.append(path)
        return "# Texte OCR fictif"

    monkeypatch.setattr(marker_app, "_run_marker", fake_marker)
    return TestClient(marker_app.app), ocr_calls, uploads


def _text_layer(monkeypatch, result=(NATIVE, 1.0, 1), error: Exception | None = None) -> list:
    calls: list = []

    def fake(path):
        calls.append(path)
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(marker_app, "extract_text_layer", fake)
    return calls


def _upload(client, name="rapport.pdf", content=PDF):
    return client.post("/extract", files={"file": (name, content, "application/pdf")})


def test_health(service):
    client, _, _ = service
    assert client.get("/health").json() == {"status": "ok", "service": "marker_ocr"}


def test_marker_conversion_returns_its_text():
    assert REAL_RUN_MARKER("fictif.pdf") == "# Texte OCR fictif"


@pytest.mark.parametrize("name", ["image.png", "rapport.pdf.exe", "sans_extension"])
def test_only_pdf_names_are_accepted(service, name):
    client, ocr_calls, uploads = service
    resp = _upload(client, name)
    assert resp.status_code == 400
    assert list(uploads.iterdir()) == [] and ocr_calls == []


def test_native_text_layer_skips_ocr(service, monkeypatch):
    client, ocr_calls, uploads = service
    _text_layer(monkeypatch)
    resp = _upload(client, "../../Rapport.PDF")
    assert resp.status_code == 200
    body = resp.json()
    assert body["markdown"] == NATIVE and body["mode"] == "text_layer"
    assert body["status"] == "success" and body["cached"] is False
    assert ocr_calls == []
    # Le fichier temporaire est supprimé une fois traité.
    assert list(uploads.iterdir()) == []


def test_scanned_document_goes_to_ocr(service, monkeypatch):
    client, ocr_calls, uploads = service
    _text_layer(monkeypatch, result=("## Page 1\n\n", 0.0, 2))
    body = _upload(client).json()
    assert body["mode"] == "ocr" and body["markdown"] == "# Texte OCR fictif"
    assert len(ocr_calls) == 1
    assert ocr_calls[0].startswith(str(uploads)) and ocr_calls[0].endswith(".pdf")
    assert list(uploads.iterdir()) == []


def test_unreadable_text_layer_falls_back_to_ocr(service, monkeypatch):
    client, ocr_calls, _ = service
    _text_layer(monkeypatch, error=RuntimeError("couche texte illisible (fictif)"))
    assert _upload(client).json()["mode"] == "ocr"
    assert len(ocr_calls) == 1


def test_forced_ocr_ignores_the_text_layer(service, monkeypatch):
    client, ocr_calls, _ = service
    layer_calls = _text_layer(monkeypatch)
    monkeypatch.setattr(marker_app, "FORCE_OCR", True)
    assert _upload(client).json()["mode"] == "ocr"
    assert layer_calls == [] and len(ocr_calls) == 1


def test_same_content_is_served_from_cache(service, monkeypatch, tmp_path):
    client, ocr_calls, _ = service
    _text_layer(monkeypatch, result=("", 0.0, 1))
    first = _upload(client, "a.pdf").json()
    second = _upload(client, "autre_nom.pdf").json()
    assert first["cached"] is False and second["cached"] is True
    assert second["markdown"] == first["markdown"] and second["mode"] == "ocr"
    assert len(ocr_calls) == 1

    entry = tmp_path / "cache" / f"{hashlib.sha256(PDF).hexdigest()}.json"
    assert json.loads(entry.read_text(encoding="utf-8"))["markdown"] == "# Texte OCR fictif"


def test_disk_cache_survives_a_restart(service, monkeypatch):
    client, ocr_calls, _ = service
    _text_layer(monkeypatch, result=("", 0.0, 1))
    _upload(client)
    monkeypatch.setattr(marker_app, "OCR_CACHE", {})      # redémarrage : mémoire vide
    assert _upload(client).json()["cached"] is True
    assert len(ocr_calls) == 1
    assert hashlib.sha256(PDF).hexdigest() in marker_app.OCR_CACHE


def test_corrupted_cache_entry_is_ignored(service, monkeypatch, tmp_path):
    client, ocr_calls, _ = service
    _text_layer(monkeypatch, result=("", 0.0, 1))
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"{hashlib.sha256(PDF).hexdigest()}.json").write_text("{ tronqué", encoding="utf-8")
    assert _upload(client).json()["cached"] is False
    assert len(ocr_calls) == 1


def test_memory_cache_is_bounded(service, monkeypatch):
    client, _, _ = service
    _text_layer(monkeypatch)
    monkeypatch.setattr(marker_app, "MAX_CACHE_SIZE", 1)
    _upload(client, content=PDF + b"1")
    _upload(client, content=PDF + b"2")
    assert list(marker_app.OCR_CACHE) == [hashlib.sha256(PDF + b"2").hexdigest()]


def test_unwritable_disk_cache_keeps_the_memory_cache(service, monkeypatch, tmp_path):
    client, _, _ = service
    _text_layer(monkeypatch)
    blocker = tmp_path / "pas_un_dossier"
    blocker.write_text("fichier", encoding="utf-8")
    monkeypatch.setattr(marker_app, "CACHE_DIR", blocker)
    assert _upload(client).status_code == 200
    assert hashlib.sha256(PDF).hexdigest() in marker_app.OCR_CACHE


def test_ocr_failure_is_a_generic_500(service, monkeypatch):
    client, _, uploads = service
    _text_layer(monkeypatch, result=("", 0.0, 1))

    def broken(path):
        raise RuntimeError("détail interne fictif : /chemin/modele")

    monkeypatch.setattr(marker_app, "_run_marker", broken)
    resp = _upload(client)
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Erreur lors de l'extraction du PDF."}
    assert "chemin" not in resp.text
    assert list(uploads.iterdir()) == []
    assert marker_app.OCR_CACHE == {}
