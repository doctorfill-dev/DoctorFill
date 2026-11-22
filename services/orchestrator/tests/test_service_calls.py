"""
Appels aux services internes (OCR, embeddings, rerank) et entretien des fichiers de jobs.

Les reprises sont proportionnées à la cause (voir _ocr_document et _tei_post) :
un service qui redémarre mérite plusieurs essais, un PDF refusé aucun, un OCR
trop long un seul. Ces règles ne se voient qu'en panne ; on les rejoue ici avec
un transport httpx scripté, sans réseau ni attente réelle.

La purge, elle, protège les dossiers patients : ce qui expire doit disparaître
du disque, ce qui tourne encore ne doit pas être touché.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import httpx
import pytest

import app as orchestrator
import stats
from core.provenance import SourceIndex
from tests import fakes


# --- Outils ----------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Délais demandés entre deux essais, enregistrés au lieu d'être attendus."""
    delays: list = []

    async def _sleep(delay, *_a, **_k):
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    return delays


def ok(payload):
    return lambda: httpx.Response(200, json=payload)


def status(code):
    return lambda: httpx.Response(code, text="erreur fictive")


def fail(exc_type):
    def _raise():
        raise exc_type("panne fictive")
    return _raise


class Script:
    """Réponses successives d'un service simulé ; la dernière se répète."""

    def __init__(self, *steps):
        self.steps = steps
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return self.steps[min(len(self.calls), len(self.steps)) - 1]()


def _run(handler, call):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await call(client)
    return asyncio.run(go())


# --- OCR -------------------------------------------------------------------------------

@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "doc_fictif.pdf"
    path.write_bytes(b"%PDF-1.4 document fictif")
    return path


def _ocr(script, pdf):
    return _run(script, lambda client: orchestrator._ocr_document(client, pdf))


def test_ocr_returns_the_markdown(pdf, sleeps):
    script = Script(ok({"markdown": "# Texte fictif", "status": "success"}))
    assert _ocr(script, pdf) == "# Texte fictif"
    request = script.calls[0]
    assert request.method == "POST" and request.url.path == "/extract"
    assert fakes.uploaded_filename(request) == "doc_fictif.pdf"
    assert sleeps == []


@pytest.mark.parametrize("payload", [{"markdown": None}, {}])
def test_ocr_without_markdown_is_empty_text(pdf, payload):
    assert _ocr(Script(ok(payload)), pdf) == ""


def test_ocr_rejected_pdf_is_not_retried(pdf, sleeps):
    script = Script(status(422))
    with pytest.raises(httpx.HTTPStatusError):
        _ocr(script, pdf)
    assert len(script.calls) == 1 and sleeps == []


def test_ocr_server_error_is_retried_once(pdf, sleeps):
    script = Script(status(500))
    with pytest.raises(httpx.HTTPStatusError):
        _ocr(script, pdf)
    assert len(script.calls) == 2 and sleeps == [5]


def test_ocr_server_error_then_success(pdf):
    script = Script(status(503), ok({"markdown": "texte"}))
    assert _ocr(script, pdf) == "texte"
    assert len(script.calls) == 2


@pytest.mark.parametrize("exc_type", [httpx.ReadTimeout, httpx.RemoteProtocolError])
def test_ocr_slow_or_broken_answer_is_retried_once(pdf, sleeps, exc_type):
    # Un OCR de dix minutes rejoué cinq fois, c'est une heure perdue.
    script = Script(fail(exc_type))
    with pytest.raises(exc_type):
        _ocr(script, pdf)
    assert len(script.calls) == 2 and sleeps == [5]


@pytest.mark.parametrize("exc_type", [httpx.ConnectError, httpx.ConnectTimeout])
def test_ocr_unreachable_service_is_retried_five_times(pdf, sleeps, exc_type):
    # Service en redémarrage : attentes croissantes, cinq essais au total.
    script = Script(fail(exc_type))
    with pytest.raises(exc_type):
        _ocr(script, pdf)
    assert len(script.calls) == orchestrator.MAX_OCR_RETRIES == 5
    assert sleeps == [10, 20, 30, 40]


def test_ocr_dropped_connection_is_retried_with_short_delays(pdf, sleeps):
    script = Script(fail(httpx.ReadError))
    with pytest.raises(httpx.ReadError):
        _ocr(script, pdf)
    assert len(script.calls) == 5 and sleeps == [2, 4, 6, 8]


def test_ocr_service_back_after_a_restart(pdf, sleeps):
    script = Script(fail(httpx.ConnectError), fail(httpx.ConnectError), ok({"markdown": "texte"}))
    assert _ocr(script, pdf) == "texte"
    assert len(script.calls) == 3 and sleeps == [10, 20]


# --- TEI : embeddings et rerank ----------------------------------------------------------

def _tei(script):
    return _run(script, lambda client: orchestrator._tei_post(client, "/embed", {"texts": ["a"]}, timeout=1.0))


def test_tei_server_errors_are_retried(sleeps):
    script = Script(status(503), status(502), ok({"embeddings": [[0.1]]}))
    assert _tei(script) == {"embeddings": [[0.1]]}
    assert len(script.calls) == 3 and sleeps == [2, 4]


def test_tei_gives_up_after_three_server_errors(sleeps):
    script = Script(status(503))
    with pytest.raises(httpx.HTTPStatusError):
        _tei(script)
    assert len(script.calls) == 3


def test_tei_client_error_is_not_retried(sleeps):
    script = Script(status(413))
    with pytest.raises(httpx.HTTPStatusError):
        _tei(script)
    assert len(script.calls) == 1 and sleeps == []


def test_tei_transient_network_errors_are_retried(sleeps):
    script = Script(fail(httpx.ConnectError), ok({"embeddings": []}))
    assert _tei(script) == {"embeddings": []}
    timeout = Script(fail(httpx.ReadTimeout))
    with pytest.raises(httpx.ReadTimeout):
        _tei(timeout)
    assert len(timeout.calls) == 3


def test_embeddings_are_fetched_in_order_by_batches():
    sizes = []

    def handler(request):
        texts = json.loads(request.content)["texts"]
        sizes.append(len(texts))
        return httpx.Response(200, json={"embeddings": [[float(len(t))] for t in texts]})

    texts = ["a", "bb", "ccc", "dddd", "eeeee"]
    result = _run(handler, lambda c: orchestrator.fetch_embeddings_batched(c, texts, batch_size=2))
    assert result == [[1.0], [2.0], [3.0], [4.0], [5.0]]
    assert sizes == [2, 2, 1]


def test_question_embeddings_are_cached_per_form_and_content(monkeypatch):
    monkeypatch.setattr(orchestrator, "_QUESTION_EMB_CACHE", {})
    script = Script(lambda: httpx.Response(200, json={"embeddings": [[0.5]]}))

    def fetch(form_id, questions):
        return _run(script, lambda c: orchestrator.fetch_question_embeddings(c, form_id, questions))

    assert fetch("FormA", ["Nom ?"]) == [[0.5]]
    assert fetch("FormA", ["Nom ?"]) == [[0.5]]
    assert len(script.calls) == 1                     # deuxième appel : cache
    fetch("FormA", ["Nom du patient ?"])              # template modifié : recalcul
    fetch("FormB", ["Nom ?"])                         # autre formulaire : recalcul
    assert len(script.calls) == 3


def test_rerank_with_and_without_semaphore():
    script = Script(ok({"results": [{"document": "b", "score": 0.9}, {"document": "a", "score": 0.1}]}))

    async def both(client):
        guarded = await orchestrator.fetch_rerank(client, "q", ["a", "b"], rerank_sem=asyncio.Semaphore(1))
        plain = await orchestrator.fetch_rerank(client, "q", ["a", "b"])
        return guarded, plain

    guarded, plain = _run(script, both)
    assert guarded == plain and guarded[0]["document"] == "b"
    assert all(r.url.path == "/rerank" for r in script.calls)


# --- Recherche d'extraits ----------------------------------------------------------------

@pytest.fixture
def collection(monkeypatch):
    monkeypatch.setattr(orchestrator, "_QUESTION_EMB_CACHE", {})
    monkeypatch.setattr(orchestrator, "RETRIEVAL_TOP_K", 2)
    name = f"col_test_{time.time_ns():x}"
    docs = ["Nom : FICTIF", "Canton : Testland", "Diagnostic fictif : entorse de la cheville"]
    col = orchestrator.chroma_client.get_or_create_collection(name=name)
    col.add(documents=docs, embeddings=[fakes.hashed_vector(d) for d in docs],
            ids=[f"c{i}" for i in range(len(docs))])
    yield col
    orchestrator.chroma_client.delete_collection(name=name)


FIELDS = [{"id": "1.1", "question": "Nom ? Répondre en majuscules.", "retrieval_query": "Nom du patient"},
          {"id": "1.2", "question": "Canton de traitement ?"}]


def _tei_handler(rerank_status: int = 200):
    def handler(request):
        if request.url.path.endswith("/embed"):
            return fakes.embed_response(request)
        if rerank_status != 200:
            return httpx.Response(rerank_status, text="rerank indisponible")
        return fakes.rerank_response(request)
    return handler


def test_retrieve_keeps_the_best_reranked_extracts(collection):
    chunks, scores = _run(_tei_handler(),
                          lambda c: orchestrator._retrieve(c, collection, 3, "FormTest", FIELDS))
    assert set(chunks) == {"1.1", "1.2"}
    assert all(len(v) == 2 for v in chunks.values())
    assert set(scores) == {"1.1", "1.2"} and all(isinstance(s, float) for s in scores.values())


def test_retrieve_keeps_vector_order_when_rerank_is_down(collection):
    chunks, scores = _run(_tei_handler(rerank_status=400),
                          lambda c: orchestrator._retrieve(c, collection, 3, "FormTest", FIELDS))
    assert all(len(v) == 2 for v in chunks.values())
    assert scores == {}


def test_retrieve_on_an_empty_index_asks_nothing():
    script = Script(status(500))
    assert _run(script, lambda c: orchestrator._retrieve(c, None, 0, "FormTest", FIELDS)) == ({}, {})
    assert script.calls == []


# --- Confiance et vues -------------------------------------------------------------------

def test_annotate_confidence_normalises_and_grounds_each_value():
    index = SourceIndex([{"filename": "01_fiche.pdf", "markdown": "Né le 02.02.1985. Nom : FICTIF"}])
    results = [
        {"id": "1.1", "result": {"value": "FICTIF", "source_quote": "Nom : FICTIF"}},
        {"id": "1.2", "result": {"value": "1985-02-02", "source_quote": "Né le 02.02.1985"}},
        {"id": "1.3", "result": {"value": "Non mentionné", "source_quote": "rien"}},
        {"id": "1.4", "error": "extraction_failed"},
        {"id": "1.5", "result": {"value": "oui", "source_quote": "Nom : FICTIF"}},
    ]
    fields_by_id = {"1.1": {}, "1.2": {"type": "date"}, "1.3": {}, "1.5": {"type": "bool"}}
    orchestrator._annotate_confidence(results, index, {"1.1": 0.123456}, fields_by_id)
    by_id = {r["id"]: r for r in results}

    nom = by_id["1.1"]["result"]
    assert nom["rerank_score"] == 0.1235 and nom["grounding"] == "verified"
    assert nom["source_document"] == "01_fiche.pdf" and "raw_value" not in nom

    date = by_id["1.2"]["result"]
    assert date["value"] == "02.02.1985" and date["raw_value"] == "1985-02-02"
    assert date["grounding"] == "verified" and date["rerank_score"] is None

    vide = by_id["1.3"]["result"]
    assert vide["value"] == "" and vide["source_quote"] == "" and "grounding" not in vide

    assert by_id["1.4"] == {"id": "1.4", "error": "extraction_failed"}
    # « oui » est choisi, pas recopié : seule la citation compte.
    assert by_id["1.5"]["result"]["grounding"] == "inferred"


def test_synthesis_is_indexed_as_a_derived_source():
    assert orchestrator._synthesis_as_source(None) == []
    assert orchestrator._synthesis_as_source({}) == []
    [source] = orchestrator._synthesis_as_source({"patient": {"nom": "FICTIF"}})
    assert source["derived"] is True and "FICTIF" in source["markdown"]


def test_template_fields_view_lists_extracted_fields_with_their_section():
    view = orchestrator._template_fields_view({"fields": [
        {"comments": "Section 2"},
        {"id": "2.1", "label": "Nom", "question": "Nom du patient ?"},
        {"id": "2.2", "question": "", "computed": "Pied de page"},
    ]})
    assert [(f["id"], f["label"], f["section"]) for f in view] == [("2.1", "Nom", "2")]


# --- File d'attente ---------------------------------------------------------------------

@pytest.mark.parametrize("average, expected", [(180.0, "environ 3 min"), (None, "En file d'attente…")])
def test_queued_job_is_told_it_waits(monkeypatch, average, expected):
    table = {"j": {"status": "pending"}}
    monkeypatch.setattr(orchestrator, "JOBS", table)
    monkeypatch.setattr(orchestrator, "_PIPELINE_SEM", asyncio.Semaphore(0))
    monkeypatch.setattr(stats, "summary", lambda form_id=None: {"recent_average_seconds": average})
    orchestrator._announce_queue("j")
    assert table["j"]["status"] == "processing"
    assert expected in table["j"]["message"]


def test_free_slot_means_no_queue_message(monkeypatch):
    table = {"j": {"status": "pending"}}
    monkeypatch.setattr(orchestrator, "JOBS", table)
    monkeypatch.setattr(orchestrator, "_PIPELINE_SEM", asyncio.Semaphore(1))
    orchestrator._announce_queue("j")
    assert table["j"] == {"status": "pending"}


# --- Purge des fichiers -----------------------------------------------------------------

@pytest.fixture
def storage(tmp_path, monkeypatch):
    jobs_dir, debug_dir = tmp_path / "jobs", tmp_path / "debug"
    jobs_dir.mkdir()
    debug_dir.mkdir()
    table: dict = {}
    monkeypatch.setattr(orchestrator, "JOBS", table)
    monkeypatch.setattr(orchestrator, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(orchestrator, "DEBUG_LOG_DIR", debug_dir)
    monkeypatch.setattr(orchestrator, "KEEP_DEBUG_LOGS", False)
    return table, jobs_dir, debug_dir


def _old() -> float:
    return time.time() - orchestrator.JOB_RETENTION_SECONDS - 60


def test_purge_removes_expired_jobs_only(storage):
    table, jobs_dir, debug_dir = storage
    old = _old()
    for jid in ("ancien", "recent", "encours", "echoue"):
        (jobs_dir / jid).mkdir()
    (debug_dir / "journal_echoue").mkdir()
    table["ancien"] = {"status": "completed", "completed_at": old}
    table["recent"] = {"status": "completed", "completed_at": time.time()}
    table["encours"] = {"status": "processing"}
    table["echoue"] = {"status": "failed", "completed_at": old, "_debug_dir": str(debug_dir / "journal_echoue")}
    stray_file = jobs_dir / "fichier_isole.txt"
    stray_file.write_text("fictif", encoding="utf-8")
    os.utime(stray_file, (old, old))

    orchestrator._purge_expired_jobs()

    assert set(table) == {"recent", "encours"}
    assert not (jobs_dir / "ancien").exists() and not (jobs_dir / "echoue").exists()
    assert not (debug_dir / "journal_echoue").exists()
    assert (jobs_dir / "recent").exists() and (jobs_dir / "encours").exists()
    # Seuls des dossiers sont purgés : un fichier isolé n'est pas un job.
    assert stray_file.exists()


def test_debug_logs_survive_when_explicitly_kept(storage, monkeypatch):
    table, _, debug_dir = storage
    monkeypatch.setattr(orchestrator, "KEEP_DEBUG_LOGS", True)
    old = _old()
    kept = debug_dir / "journal_garde"
    kept.mkdir()
    orphan = debug_dir / "20260101_000000_ffffffff"
    orphan.mkdir()
    os.utime(orphan, (old, old))
    table["fini"] = {"status": "completed", "completed_at": old, "_debug_dir": str(kept)}

    orchestrator._purge_expired_jobs()

    assert table == {}
    assert kept.exists() and orphan.exists()


def test_cleanup_loop_survives_a_failed_purge(monkeypatch):
    class _Stop(Exception):
        pass

    ticks: list = []
    purges: list = []

    async def _sleep(delay, *_a, **_k):
        ticks.append(delay)
        if len(ticks) == 3:
            raise _Stop

    def _purge():
        purges.append(1)
        if len(purges) == 1:
            raise OSError("disque fictif plein")

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    monkeypatch.setattr(orchestrator, "_purge_expired_jobs", _purge)
    with pytest.raises(_Stop):
        asyncio.run(orchestrator._cleanup_expired_jobs())
    # Une purge en échec n'arrête pas la boucle : la suivante a lieu.
    assert purges == [1, 1] and ticks == [300, 300, 300]
