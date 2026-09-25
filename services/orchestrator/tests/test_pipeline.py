"""
Pipeline complet, services simulés : OCR → embeddings → synthèse → extraction →
remplissage, puis re-run et chat.

Le transport httpx remplace marker, TEI et vLLM ; le formulaire est un vrai PDF
AcroForm (tests/pdf_factory.py) et le remplissage passe par le code de
production. Ce qui est vérifié, c'est l'enchaînement : qu'un document illisible
n'emporte pas le job, que le re-run écrive les mêmes champs dérivés que le
premier passage, que le dossier soit transmis en entier quand il tient.
"""

import asyncio
import json
import re
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app as orchestrator
import medical_synthesis
from tests import fakes
from tests.pdf_factory import make_acroform, read_fields

DOCS = {
    "01_fiche.pdf": (
        "# Fiche administrative\n\n## Identité\n\n- Nom : DUPONT\n- Prénom : Jeanne\n"
        "- Date de naissance : 02.02.1985\n- Canton : Neuchâtel (NE)\n\n"
        "## Contexte\n\nConsultation en urgence pour lombalgie aiguë, patiente hospitalisée."
    ),
    "02_consultation.pdf": (
        "# Consultation du 09.04.2026\n\nLombalgie aiguë (M54.5). Incapacité de travail à 100 % "
        "du 09.04.2026 au 30.04.2026."
    ),
    "03_scan_illisible.pdf": None,  # le service OCR échoue sur celui-ci
}

# Réponses du « modèle » : ce qu'un LLM rendrait, écarts de format compris.
LLM_ANSWERS = {
    "1.1": {"value": "NE", "source_quote": "Canton : Neuchâtel (NE)"},
    "1.2": {"value": "DUPONT", "source_quote": "Nom : DUPONT"},
    "1.3": {"value": "1985-02-02", "source_quote": "Date de naissance : 02.02.1985"},
    "1.4": {"value": "Oui", "source_quote": "Consultation en urgence"},
    "1.5": {"value": "oui", "source_quote": "patiente hospitalisée"},
    "1.6": {"value": "Non mentionné", "source_quote": ""},
}

SYNTHESIS = {"patient": {"nom": "DUPONT", "prenom": "Jeanne"}, "diagnostics": [],
             "incapacites_travail": [], "canton_traitement": "NE"}


def _template():
    return {
        "_reviewed": True,
        "_recipient_by_canton": {"NE": {"recipientBlock": "Office AI du canton de Neuchâtel"},
                                 "VD": {"recipientBlock": "Office AI du canton de Vaud"}},
        "fields": [
            {"comments": "Section 1"},
            {"id": "1.1", "name": "treatmentCanton", "question": "Canton de traitement ?",
             "type": "choice", "options": ["NE", "VD"], "acroform_name": "treatmentCanton"},
            {"id": "1.2", "name": "lastName", "question": "Nom du patient ?", "acroform_name": "lastName"},
            {"id": "1.3", "name": "birthDate", "question": "Date de naissance ? [format : JJ.MM.AAAA]",
             "type": "date", "acroform_name": "birthDate"},
            {"id": "1.4", "name": "urgent", "question": "Consultation urgente ? Répondre par oui ou non.",
             "type": "bool", "options": ["On", "Off"], "preset": "/Off", "acroform_name": "urgent"},
            {"id": "1.5", "name": "ask4Hospitalization", "question": "Hospitalisé ? Répondre par oui ou non.",
             "type": "choice", "options": ["non", "oui"], "option_values": ["0", "1"], "preset": "0",
             "acroform_name": "ask4Hospitalization"},
            {"id": "1.6", "name": "email", "question": "E-mail du patient ?", "acroform_name": "email"},
            {"id": "1.7", "name": "insurance", "question": "Régime ?", "type": "choice",
             "options": ["LAA", "LCA"], "preset": "LAA", "acroform_name": "insurance"},
            {"id": "2.1", "name": "recipientBlock", "acroform_name": "recipientBlock", "computed": ""},
            {"id": "2.2", "name": "footer", "acroform_name": "footer", "computed": "DoctorFill — test"},
        ],
    }


class FakeServices:
    """Marker, TEI et vLLM derrière un seul transport httpx."""

    def __init__(self):
        self.extraction_prompts: list[str] = []
        self.ocr_calls: dict[str, int] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/extract"):
            body = request.content.decode("latin-1")
            name = re.search(r'filename="([^"]+)"', body).group(1)
            self.ocr_calls[name] = self.ocr_calls.get(name, 0) + 1
            if DOCS[name] is None:
                return httpx.Response(500, json={"detail": "Erreur lors de l'extraction du PDF."})
            return httpx.Response(200, json={"markdown": DOCS[name], "status": "success"})
        if path.endswith("/embed"):
            return fakes.embed_response(request)
        if path.endswith("/rerank"):
            return fakes.rerank_response(request)
        if path.endswith("/chat/completions"):
            body = json.loads(request.content)
            system = body["messages"][0]["content"]
            if "médecin expert" in system:
                content = json.dumps(SYNTHESIS)
            else:
                self.extraction_prompts.append(body["messages"][1]["content"])
                ids = list(body["response_format"]["json_schema"]["schema"]["properties"])
                content = json.dumps({i: LLM_ANSWERS[i] for i in ids})
            return httpx.Response(200, json={"choices": [{"message": {"content": content},
                                                          "finish_reason": "stop"}]})
        return httpx.Response(404)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Répertoire de travail de l'orchestrateur : template/, forms/, dossiers uploadés."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "template").mkdir()
    (tmp_path / "forms").mkdir()
    (tmp_path / "template" / "Form_Test.json").write_text(json.dumps(_template()), encoding="utf-8")
    make_acroform(tmp_path / "forms" / "Form_Test.pdf", [
        ("treatmentCanton", "combo", {"opt": [("NE", "NE"), ("VD", "VD")]}),
        ("lastName", "text", {}), ("birthDate", "text", {}), ("urgent", "checkbox", {}),
        ("ask4Hospitalization", "combo", {"opt": [("0", "non"), ("1", "oui")]}),
        ("email", "text", {}), ("insurance", "text", {}), ("recipientBlock", "text", {}),
        ("footer", "text", {}),
    ])
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    for name in DOCS:
        (uploads / name).write_bytes(b"%PDF-1.4 " + name.encode())

    services = FakeServices()
    # Résolu à chaque requête : un test peut remplacer services.handler en cours de route.
    fakes.install(monkeypatch, lambda request: services.handler(request))
    monkeypatch.setattr(orchestrator, "VALID_FORM_IDS", {"Test"})
    return tmp_path, uploads, services


def _start_job(tmp_path: Path, uploads: Path) -> str:
    job_id = f"test{time.time_ns():x}"
    orchestrator.JOBS[job_id] = {"status": "pending", "progress": 0, "token": "secret",
                                 "started_at": time.time()}
    tmp_dir = tmp_path / "job"
    tmp_dir.mkdir(exist_ok=True)
    asyncio.run(orchestrator.run_pipeline_task(job_id, "Test", tmp_dir, sorted(uploads.glob("*.pdf"))))
    return job_id


def test_pipeline_fills_form_and_survives_unreadable_document(workspace):
    tmp_path, uploads, services = workspace
    job_id = _start_job(tmp_path, uploads)
    job = orchestrator.JOBS[job_id]

    assert job["status"] == "completed", job.get("message")
    assert any("03_scan_illisible.pdf" in w for w in job["warnings"])
    # Une erreur 5xx de l'OCR est rejouée une fois, pas cinq.
    assert services.ocr_calls["03_scan_illisible.pdf"] == 2

    # Dossier court : transmis en entier, identique pour tous les lots.
    assert services.extraction_prompts
    assert all("DOCUMENTS DU DOSSIER (texte intégral)" in p for p in services.extraction_prompts)
    assert all("=== DOCUMENT : 01_fiche.pdf ===" in p for p in services.extraction_prompts)
    # Le preset d'éditeur n'est pas soumis ; la case vierge et la question oui/non le sont.
    asked = "\n".join(services.extraction_prompts)
    assert "[1.7]" not in asked and "[1.4]" in asked and "[1.5]" in asked

    fields = read_fields(Path(job["file_path"]))
    assert fields["lastName"]["V"] == "DUPONT"
    assert fields["birthDate"]["V"] == "02.02.1985"          # date ISO normalisée
    assert fields["urgent"]["V"] == "/On"                     # « Oui » coche la case
    assert fields["ask4Hospitalization"]["V"] == "1"          # libellé → valeur d'export
    assert fields["email"]["V"] is None                       # « Non mentionné » n'est pas écrit
    assert fields["recipientBlock"]["V"] == "Office AI du canton de Neuchâtel"
    assert fields["footer"]["V"] == "DoctorFill — test"

    results = {r["id"]: r["result"] for r in job["_debug_results"]}
    assert results["1.3"]["value"] == "02.02.1985" and results["1.3"]["raw_value"] == "1985-02-02"
    assert results["1.6"]["value"] == ""
    assert results["1.2"]["grounding"] == "verified"
    assert results["1.4"]["grounding"] == "inferred"          # « oui » : justifié par la citation seule


def test_rerun_writes_the_same_derived_fields(workspace):
    tmp_path, uploads, services = workspace
    job_id = _start_job(tmp_path, uploads)
    services.extraction_prompts.clear()

    asyncio.run(orchestrator.rerun_pipeline_task(job_id))
    job = orchestrator.JOBS[job_id]
    assert job["status"] == "completed", job.get("message")
    assert job["file_path"].endswith("output_rerun.pdf")
    fields = read_fields(Path(job["file_path"]))
    # Le re-run perdait le destinataire cantonal et les champs calculés.
    assert fields["recipientBlock"]["V"] == "Office AI du canton de Neuchâtel"
    assert fields["footer"]["V"] == "DoctorFill — test"
    assert fields["urgent"]["V"] == "/On"
    assert services.extraction_prompts


def test_job_fails_with_actionable_message_when_nothing_is_readable(workspace, monkeypatch):
    tmp_path, uploads, _ = workspace
    for name in list(DOCS):
        monkeypatch.setitem(DOCS, name, None)
    job_id = _start_job(tmp_path, uploads)
    job = orchestrator.JOBS[job_id]
    assert job["status"] == "failed"
    assert "Aucun texte" in job["message"]


def test_synthesis_failure_does_not_block_extraction(workspace, monkeypatch):
    tmp_path, uploads, _ = workspace

    async def _broken(*_a, **_k):
        return None
    monkeypatch.setattr(orchestrator, "run_medical_synthesis", _broken)
    job_id = _start_job(tmp_path, uploads)
    job = orchestrator.JOBS[job_id]
    assert job["status"] == "completed"
    assert any("Synthèse" in w for w in job["warnings"])


def test_chat_requires_the_job_token(workspace):
    tmp_path, uploads, _ = workspace
    job_id = _start_job(tmp_path, uploads)
    client = TestClient(orchestrator.app)
    resp = client.post("/chat", json={"job_id": job_id, "message": "Diagnostic ?"})
    assert resp.status_code == 403
    status = client.get(f"/status/{job_id}").json()
    assert status["status"] == "completed" and status["warnings"]
    fields = client.get(f"/fields/{job_id}", params={"token": "secret"}).json()["fields"]
    assert {f["id"] for f in fields} >= {"1.4", "1.5"}
    assert client.get(f"/fields/{job_id}", params={"token": "nope"}).status_code == 403


def test_synthesis_falls_back_to_hierarchical(monkeypatch):
    calls = []

    async def fake_call(system, user, url, model, **kwargs):
        calls.append(system)
        if system == medical_synthesis.SYSTEM_PROMPT_SYNTHESIS:
            raise medical_synthesis._Unrecoverable("réponse tronquée")
        if system == medical_synthesis.SYSTEM_PROMPT_PER_DOC_SUMMARY:
            name = re.search(r"DOCUMENT : (.+)", user).group(1)
            return json.dumps({"document": name, "patient": {"nom": "DUPONT"},
                               "diagnostics": [{"description": f"dx {name}"}]})
        raise medical_synthesis._Unrecoverable("fusion impossible")

    monkeypatch.setattr(medical_synthesis, "_call_llm", fake_call)
    result = asyncio.run(medical_synthesis.run_medical_synthesis(
        [{"filename": "b.pdf", "markdown": "texte b"}, {"filename": "a.pdf", "markdown": "texte a"}],
        "http://vllm", "model"))
    # Directe → hiérarchique → fusion déterministe : rien n'est perdu.
    assert [d["description"] for d in result["diagnostics"]] == ["dx a.pdf", "dx b.pdf"]
    assert result["patient"]["nom"] == "DUPONT"
    assert calls[0] == medical_synthesis.SYSTEM_PROMPT_SYNTHESIS


def test_long_documents_are_split_for_summaries():
    text = "\n\n".join(f"Paragraphe {i} " + "mot " * 200 for i in range(60))
    parts = medical_synthesis._split_document("long.pdf", text, max_tokens=2000)
    assert len(parts) > 1
    assert parts[0][0] == f"long.pdf (partie 1/{len(parts)})"
    assert "".join(p for _, p in parts).replace("\n", "") == text.replace("\n", "")


def test_expired_jobs_take_their_debug_logs_with_them(workspace):
    tmp_path, uploads, _ = workspace
    job_id = _start_job(tmp_path, uploads)
    debug_dir = Path(orchestrator.JOBS[job_id]["_debug_dir"])
    assert (debug_dir / "markdown" / "01_fiche.md").exists()
    orchestrator.JOBS[job_id]["completed_at"] = time.time() - orchestrator.JOB_RETENTION_SECONDS - 1
    orchestrator._purge_expired_jobs()
    assert job_id not in orchestrator.JOBS
    assert not debug_dir.exists()


def test_embedding_outage_degrades_instead_of_failing(workspace, monkeypatch):
    tmp_path, uploads, services = workspace
    real = services.handler

    def handler(request):
        if request.url.path.endswith("/embed"):
            return httpx.Response(503, text="TEI down")
        return real(request)
    monkeypatch.setattr(services, "handler", handler)

    job_id = _start_job(tmp_path, uploads)
    job = orchestrator.JOBS[job_id]
    assert job["status"] == "completed", job.get("message")
    assert any("Recherche sémantique" in w for w in job["warnings"])
    assert read_fields(Path(job["file_path"]))["lastName"]["V"] == "DUPONT"


def test_field_error_warning_is_recomputed_on_each_pass():
    job = {"warnings": ["Document illisible, ignoré : x.pdf"]}
    orchestrator._record_field_errors(job, [{"id": "1.1", "error": "extraction_failed"}, {"id": "1.2"}])
    assert job["warnings"][-1].startswith("1 champ(s)")
    orchestrator._record_field_errors(job, [{"id": "1.1", "result": {}}])
    assert job["warnings"] == ["Document illisible, ignoré : x.pdf"]


def test_retrieval_outage_on_large_dossier_degrades(workspace, monkeypatch):
    """Dossier au-delà du mode intégral, TEI tombé au moment d'encoder les questions."""
    tmp_path, uploads, services = workspace
    import extraction
    monkeypatch.setattr(extraction, "FULL_CONTEXT_MAX_TOKENS", 10)

    async def _down(*_a, **_k):
        raise httpx.ConnectError("TEI down")
    monkeypatch.setattr(orchestrator, "fetch_question_embeddings", _down)

    job_id = _start_job(tmp_path, uploads)
    job = orchestrator.JOBS[job_id]
    assert job["status"] == "completed", job.get("message")
    assert any("début du dossier" in w for w in job["warnings"])
    assert "EXTRAITS DE DOCUMENTS" in services.extraction_prompts[0]
    assert read_fields(Path(job["file_path"]))["lastName"]["V"] == "DUPONT"


def test_orphan_files_from_before_a_restart_are_purged(tmp_path, monkeypatch):
    import os
    jobs_dir, debug_dir = tmp_path / "jobs", tmp_path / "debug"
    monkeypatch.setattr(orchestrator, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(orchestrator, "DEBUG_LOG_DIR", debug_dir)
    old = time.time() - orchestrator.JOB_RETENTION_SECONDS - 60
    stale = [jobs_dir / ("a" * 32), debug_dir / "20260101_000000_aaaaaaaa"]
    fresh = jobs_dir / ("b" * 32)
    active = debug_dir / "20260101_000000_cccccccc"
    for d in stale + [fresh, active]:
        (d / "markdown").mkdir(parents=True)
    for d in stale + [active]:
        os.utime(d, (old, old))
    monkeypatch.setitem(orchestrator.JOBS, "c" * 32, {"status": "processing", "_debug_dir": str(active)})

    orchestrator._purge_orphan_files()
    assert not any(d.exists() for d in stale)
    assert fresh.exists() and active.exists()
