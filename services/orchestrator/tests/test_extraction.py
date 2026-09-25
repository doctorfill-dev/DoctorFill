"""Découpage, contexte et appel LLM résilient (extraction.py)."""

import asyncio
import json

import httpx
import pytest

import extraction
from extraction import (
    build_rag_context,
    chunk_document,
    extract_batch,
    full_documents_text,
    parse_response,
    response_schema,
)
from prompts import build_batch_extraction_messages

URL = "http://vllm.test/v1"


# --- Découpage ------------------------------------------------------------------

def test_every_chunk_carries_its_source():
    md = ("# Fiche\n\nÉtablie le 09.04.2026.\n\n## Identité\n\n- Nom : DUPONT\n\n"
          "## Médecin traitant\n\n" + " ".join(f"mot{i}" for i in range(700)))
    chunks = chunk_document("01_fiche.pdf", md, max_words=300, overlap=50, min_words=10)
    assert all(c.startswith("[Source : 01_fiche.pdf") for c in chunks)
    assert any("Médecin traitant" in c.splitlines()[0] for c in chunks[1:])
    assert max(len(c.split()) for c in chunks) <= 300 + 10


def test_text_layer_pages_are_labelled_and_small_sections_merged():
    md = "## Page 1\n\nCourt.\n\n## Page 2\n\n" + " ".join(["texte"] * 80)
    chunks = chunk_document("scan.pdf", md, min_words=40)
    assert chunks[0].startswith("[Source : scan.pdf — page 1]")
    assert "## Page" not in chunks[0]
    assert chunks[-1].startswith("[Source : scan.pdf — page 2]")


def test_full_documents_text_is_stable():
    docs = [{"filename": "b.pdf", "markdown": "B"}, {"filename": "a.pdf", "markdown": "A"},
            {"filename": "c.pdf", "markdown": "  "}]
    assert full_documents_text(docs) == "=== DOCUMENT : a.pdf ===\nA\n\n=== DOCUMENT : b.pdf ===\nB"


def test_rag_context_interleaves_and_respects_budget():
    chunks = {"1": ["a1 " * 30, "a2 " * 30, "a3 " * 30], "2": ["b1 " * 30, "b2 " * 30]}
    fields = [{"id": "1"}, {"id": "2"}]
    context = build_rag_context(fields, chunks, budget_tokens=10_000)
    order = [block.split()[0] for block in context.split("\n\n---\n\n")]
    assert order == ["a1", "b1", "a2", "b2", "a3"]
    small = build_rag_context(fields, chunks, budget_tokens=70)
    assert [b.split()[0] for b in small.split("\n\n---\n\n")] == ["a1", "b1"]


# --- Lecture de la réponse ---------------------------------------------------------

FIELDS = [{"id": "1.1", "question": "Nom ?"}, {"id": "1.2", "question": "Prénom ?"},
          {"id": "1.3", "question": "Sexe ?", "type": "choice", "options": ["M", "F"]}]


def test_parse_response_is_tolerant():
    content = json.dumps({"[1.1]": {"value": "DUPONT", "source_quote": "Nom : DUPONT"},
                          "1.2": "Jean", "1.3": {"valeur": ["F"]}})
    parsed = parse_response("Voici :\n" + content, FIELDS)
    assert parsed["1.1"] == {"value": "DUPONT", "source_quote": "Nom : DUPONT"}
    assert parsed["1.2"] == {"value": "Jean", "source_quote": ""}
    assert parsed["1.3"]["value"] == "F"


def test_parse_response_unwraps_single_envelope():
    content = json.dumps({"champs": {"1.1": {"value": "X", "source_quote": ""}}})
    assert parse_response(content, FIELDS)["1.1"]["value"] == "X"


def test_schema_constrains_ids_and_choices():
    schema = response_schema(FIELDS)
    assert schema["required"] == ["1.1", "1.2", "1.3"]
    assert schema["properties"]["1.3"]["properties"]["value"]["enum"] == ["M", "F", ""]


def test_prompt_puts_shared_context_first():
    messages = build_batch_extraction_messages(FIELDS[:1], '{"patient": {}}', "DOCS", full_documents=True)
    user = messages[1]["content"]
    assert user.index("SYNTHÈSE") < user.index("DOCUMENTS DU DOSSIER") < user.index("CHAMPS À EXTRAIRE")
    assert '"..."' not in user


# --- Appel résilient ---------------------------------------------------------------

def _completion(payload, finish_reason="stop"):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)},
                                                  "finish_reason": finish_reason}]})


def _ids(request):
    body = json.loads(request.content)
    fmt = body.get("response_format", {})
    if fmt.get("type") == "json_schema":
        return list(fmt["json_schema"]["schema"]["properties"])
    return [line.split("]")[0].split("[")[1] for line in body["messages"][1]["content"].splitlines()
            if line.startswith("• [")]


def _run(handler, fields, builder=None):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await extract_batch(client, URL, "model", fields,
                                       builder or (lambda b, s: build_batch_extraction_messages(b, None, "ctx")),
                                       asyncio.Semaphore(4))
    return asyncio.run(go())


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(extraction, "_schema_supported", True)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)


async def _no_sleep(*_args, **_kwargs):
    return None


def test_truncated_batch_is_split_not_lost():
    calls = []

    def handler(request):
        ids = _ids(request)
        calls.append(ids)
        if len(ids) > 1:
            return _completion({}, finish_reason="length")
        return _completion({ids[0]: {"value": f"v{ids[0]}", "source_quote": ""}})

    results = _run(handler, FIELDS)
    assert [r["result"]["value"] for r in results] == ["v1.1", "v1.2", "v1.3"]
    assert calls[0] == ["1.1", "1.2", "1.3"]


def test_context_overflow_shrinks_context_for_single_field():
    scales = []

    def builder(batch, scale):
        scales.append(scale)
        return build_batch_extraction_messages(batch, None, "ctx")

    def handler(request):
        if scales[-1] >= 1.0:
            return httpx.Response(400, text="This model's maximum context length is 32768 tokens.")
        return _completion({"1.1": {"value": "ok", "source_quote": ""}})

    results = _run(handler, FIELDS[:1], builder)
    assert results[0]["result"]["value"] == "ok"
    assert scales[0] == 1.0 and scales[-1] < 1.0


def test_missing_ids_are_asked_again():
    seen = []

    def handler(request):
        ids = _ids(request)
        seen.append(ids)
        return _completion({ids[0]: {"value": "A", "source_quote": ""}})

    results = _run(handler, FIELDS[:2])
    assert seen == [["1.1", "1.2"], ["1.2"]]
    assert all("result" in r for r in results)


def test_schema_refusal_falls_back_to_json_object():
    formats = []

    def handler(request):
        fmt = json.loads(request.content)["response_format"]["type"]
        formats.append(fmt)
        if fmt == "json_schema":
            return httpx.Response(400, text="Unsupported response_format json_schema")
        return _completion({"1.1": {"value": "B", "source_quote": ""}})

    results = _run(handler, FIELDS[:1])
    assert formats == ["json_schema", "json_object"]
    assert results[0]["result"]["value"] == "B"


def test_server_errors_are_retried_then_reported_per_field():
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(503, text="overloaded")

    results = _run(handler, FIELDS[:2])
    assert all(r.get("error") == "extraction_failed" for r in results)
    # 3 essais sur le lot, puis 3 sur chacune des deux moitiés.
    assert len(attempts) == 9


def test_client_errors_are_not_retried():
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(422, text="bad request")

    results = _run(handler, FIELDS[:1])
    assert results[0]["error"] == "extraction_failed"
    assert len(attempts) == 1


def test_context_overflow_shrinks_instead_of_splitting():
    seen = []

    def builder(batch, scale):
        seen.append(([f["id"] for f in batch], scale))
        return build_batch_extraction_messages(batch, None, "ctx")

    def handler(request):
        if seen[-1][1] > 0.25:
            return httpx.Response(400, text="maximum context length exceeded")
        return _completion({i: {"value": "v", "source_quote": ""} for i in seen[-1][0]})

    results = _run(handler, FIELDS[:2], builder)
    assert all("result" in r for r in results)
    assert [ids for ids, _ in seen] == [["1.1", "1.2"]] * 3
    assert [scale for _, scale in seen] == [1.0, 0.5, 0.25]
