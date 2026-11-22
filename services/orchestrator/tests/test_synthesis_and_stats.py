"""
Synthèse médicale (medical_synthesis.py) et repères de durée (stats.py).

La synthèse a un repli à chaque étape : directe → hiérarchique → fusion
déterministe, et None en dernier recours pour que le pipeline continue. Le
modèle est simulé par un transport httpx ; les dossiers sont fictifs.

stats.py ne conserve que des durées : on vérifie aussi qu'aucune donnée de
dossier n'y entre.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

import medical_synthesis as ms
import stats
from tests import fakes

URL = "http://llm.invalid/v1"


# --- Lecture de la réponse ----------------------------------------------------------------

def test_json_is_found_inside_surrounding_text():
    assert ms._extract_json_from_response('Voici :\n{"patient": {"nom": "FICTIF"}}\nFin.') == \
        {"patient": {"nom": "FICTIF"}}


@pytest.mark.parametrize("text", ["pas de JSON", "[1, 2]", "} à l'envers {", "{ tronqué", "{1}"])
def test_unreadable_answers_raise(text):
    with pytest.raises(ValueError):
        ms._extract_json_from_response(text)


def test_token_estimate_is_conservative():
    assert ms.estimate_tokens("") == 1
    assert ms.estimate_tokens("abc" * 10) == 11


# --- Appel au modèle ------------------------------------------------------------------------

class LLM:
    """Modèle simulé : une réponse par appel, la dernière se répète."""

    def __init__(self, *answers):
        self.answers = answers
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        answer = self.answers[min(len(self.requests), len(self.answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, int):
            return httpx.Response(answer, text="erreur fictive")
        if isinstance(answer, tuple):           # (contenu, finish_reason)
            return httpx.Response(200, json={"choices": [{"message": {"content": answer[0]},
                                                          "finish_reason": answer[1]}]})
        return fakes.completion(answer)


def _call(monkeypatch, llm: LLM, **kwargs):
    fakes.install(monkeypatch, llm)
    return asyncio.run(ms._call_llm("système", "utilisateur", URL, "modele-fictif", **kwargs))


def test_call_returns_the_content_and_asks_for_json(monkeypatch):
    llm = LLM({"ok": True})
    assert json.loads(_call(monkeypatch, llm, max_tokens=123)) == {"ok": True}
    sent = llm.requests[0]
    assert sent["response_format"] == {"type": "json_object"} and sent["max_tokens"] == 123
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]


def test_call_with_empty_content(monkeypatch):
    assert _call(monkeypatch, LLM((None, "stop"))) == ""


@pytest.mark.parametrize("answer", [400, ("{ tronqué", "length")])
def test_window_overflow_and_truncation_are_not_retried(monkeypatch, answer):
    llm = LLM(answer)
    with pytest.raises(ms._Unrecoverable):
        _call(monkeypatch, llm)
    assert len(llm.requests) == 1


def test_transient_errors_are_retried_once(monkeypatch):
    llm = LLM(503, {"ok": True})
    assert json.loads(_call(monkeypatch, llm)) == {"ok": True}
    network = LLM(httpx.ConnectError("panne fictive"), {"ok": True})
    assert json.loads(_call(monkeypatch, network)) == {"ok": True}
    assert len(llm.requests) == len(network.requests) == 2


def test_persistent_server_error_is_raised(monkeypatch):
    llm = LLM(503)
    with pytest.raises(httpx.HTTPStatusError):
        _call(monkeypatch, llm)
    assert len(llm.requests) == ms.MAX_SYNTHESIS_RETRIES == 2


# --- Stratégies ------------------------------------------------------------------------------

DOCS = [{"filename": "b_consultation.pdf", "markdown": "Consultation fictive du 01.02.2026."},
        {"filename": "a_fiche.pdf", "markdown": "Nom : FICTIF. Prénom : Alice."},
        {"filename": "c_vide.pdf", "markdown": "   "}]


class Router:
    """Répond selon l'étape (synthèse directe, résumé par document, fusion)."""

    def __init__(self, direct, summary, merge):
        self.direct, self.summary, self.merge = direct, summary, merge
        self.steps: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        if system == ms.SYSTEM_PROMPT_SYNTHESIS:
            self.steps.append("direct")
            answer = self.direct(user)
        elif system == ms.SYSTEM_PROMPT_PER_DOC_SUMMARY:
            self.steps.append("résumé")
            answer = self.summary(user)
        else:
            assert system == ms.SYSTEM_PROMPT_MERGE_SUMMARIES
            self.steps.append("fusion")
            answer = self.merge(user)
        return httpx.Response(answer) if isinstance(answer, int) else fakes.completion(answer)


def _synthesize(monkeypatch, router, docs=DOCS):
    fakes.install(monkeypatch, router)
    return asyncio.run(ms.run_medical_synthesis(docs, URL, "modele-fictif"))


def _summary_of(user: str) -> dict:
    name = "a_fiche.pdf" if "a_fiche.pdf" in user else "b_consultation.pdf"
    return {"patient": {"nom": "FICTIF"}, "diagnostics": [{"description": f"dx {name}"}]}


def test_nothing_to_synthesize(monkeypatch):
    router = Router(lambda u: {}, lambda u: {}, lambda u: {})
    assert _synthesize(monkeypatch, router, []) is None
    assert _synthesize(monkeypatch, router, [{"filename": "x.pdf", "markdown": " "}]) is None
    assert router.steps == []


def test_small_dossier_is_synthesized_in_one_call(monkeypatch):
    prompts = []

    def direct(user):
        prompts.append(user)
        return {"patient": {"nom": "FICTIF"}, "diagnostics": []}

    router = Router(direct, lambda u: 500, lambda u: 500)
    assert _synthesize(monkeypatch, router) == {"patient": {"nom": "FICTIF"}, "diagnostics": []}
    assert router.steps == ["direct"]
    # Ordre stable (par nom de fichier), documents vides écartés.
    assert prompts[0].index("a_fiche.pdf") < prompts[0].index("b_consultation.pdf")
    assert "c_vide.pdf" not in prompts[0]


def test_unreadable_direct_answer_falls_back_to_summaries_and_merge(monkeypatch):
    merged = {"patient": {"nom": "FICTIF"}, "diagnostics": [{"description": "fusionné"}]}
    router = Router(lambda u: "pas du JSON", _summary_of, lambda u: merged)
    assert _synthesize(monkeypatch, router) == merged
    assert router.steps[0] == "direct"
    assert sorted(router.steps[1:]) == ["fusion", "résumé", "résumé"]


def test_a_single_summary_needs_no_merge(monkeypatch):
    router = Router(lambda u: 400, _summary_of, lambda u: pytest.fail("pas de fusion attendue"))
    result = _synthesize(monkeypatch, router, DOCS[1:2])
    assert result["document"] == "a_fiche.pdf"
    assert router.steps == ["direct", "résumé"]


def test_failed_summaries_mean_no_synthesis(monkeypatch):
    router = Router(lambda u: 400, lambda u: 400, lambda u: 400)
    assert _synthesize(monkeypatch, router) is None


def test_large_dossier_skips_the_direct_call_and_merges_deterministically(monkeypatch):
    # Seuil abaissé : le dossier « déborde », et les résumés aussi.
    monkeypatch.setattr(ms, "MAX_DIRECT_TOKENS", 5)
    router = Router(lambda u: pytest.fail("pas d'appel direct attendu"), _summary_of,
                    lambda u: pytest.fail("fusion par le modèle impossible"))
    result = _synthesize(monkeypatch, router)
    assert router.steps == ["résumé", "résumé"]
    assert sorted(d["description"] for d in result["diagnostics"]) == ["dx a_fiche.pdf", "dx b_consultation.pdf"]
    assert all(d["document_source"] for d in result["diagnostics"])


def test_combine_summaries_keeps_everything():
    combined = ms._combine_summaries([
        {"document": "a.pdf", "patient": {"nom": "FICTIF", "prenom": ""},
         "diagnostics": [{"description": "dx A"}, "texte libre"],
         "traitements": ["traitement A"], "dates_cles": {"accident": "01.01.2026"},
         "dates_importantes": ["01.01.2026"], "pronostic": "favorable", "canton_traitement": "VD"},
        {"document": "b.pdf", "patient": {"nom": "AUTRE", "prenom": "Alice"},
         "diagnostics": [{"description": "dx B", "document_source": "b-p2.pdf"}],
         "incapacites_travail": [{"taux": "100"}], "medecins": [{"nom": "Dr Fictif"}],
         "dates_cles": {"accident": "02.02.2026", "reprise": "01.03.2026"},
         "dates_importantes": ["02.02.2026"], "pronostic": "réservé", "canton_traitement": "NE"},
    ])
    assert combined["patient"] == {"nom": "FICTIF", "prenom": "Alice"}
    assert combined["diagnostics"] == [{"description": "dx A", "document_source": "a.pdf"}, "texte libre",
                                       {"description": "dx B", "document_source": "b-p2.pdf"}]
    assert combined["incapacites_travail"] == [{"taux": "100", "document_source": "b.pdf"}]
    assert combined["traitements"] == ["traitement A"] and combined["medecins"] == [{"nom": "Dr Fictif"}]
    assert combined["dates_cles"] == {"accident": "01.01.2026", "reprise": "01.03.2026"}
    assert combined["dates_importantes"] == ["01.01.2026", "02.02.2026"]
    assert combined["pronostic"] == "favorable\nréservé"
    assert combined["canton_traitement"] == "VD"


def test_combine_nothing():
    combined = ms._combine_summaries([{}])
    assert combined["pronostic"] is None and combined["diagnostics"] == []


def test_split_document_without_paragraphs_cuts_hard():
    text = "a" * 100
    parts = ms._split_document("doc.pdf", text, max_tokens=10)
    assert [name for name, _ in parts] == [f"doc.pdf (partie {i}/4)" for i in range(1, 5)]
    assert "".join(part for _, part in parts) == text
    assert ms._split_document("court.pdf", "court", max_tokens=10) == [("court.pdf", "court")]


# --- Durées -----------------------------------------------------------------------------

@pytest.fixture
def runs_file(tmp_path, monkeypatch):
    monkeypatch.setattr(stats, "STATS_DIR", tmp_path / "stats")
    monkeypatch.setattr(stats, "RUNS_FILE", tmp_path / "stats" / "pipeline_runs.jsonl")
    monkeypatch.setattr(stats, "RECENT_WINDOW", 2)
    return tmp_path / "stats" / "pipeline_runs.jsonl"


def test_no_run_yet(runs_file):
    assert stats.summary() == {"runs": 0, "average_seconds": None, "recent_average_seconds": None,
                               "average_seconds_per_document": None, "last_seconds": None}


def test_summary_global_and_per_form(runs_file):
    stats.record_run("A", 1, 10.04)
    stats.record_run("A", 2, 20.0)
    stats.record_run("B", 3, 60.0)
    assert stats.summary() == {"runs": 3, "average_seconds": 30.0, "recent_average_seconds": 40.0,
                               "average_seconds_per_document": 15.0, "last_seconds": 60.0}
    assert stats.summary("A") == {"runs": 2, "average_seconds": 15.0, "recent_average_seconds": 15.0,
                                  "average_seconds_per_document": 10.0, "last_seconds": 20.0}
    assert stats.summary("Inconnu")["runs"] == 0


def test_only_durations_are_stored(runs_file):
    stats.record_run("A", 2, 12.34)
    [entry] = [json.loads(line) for line in runs_file.read_text(encoding="utf-8").splitlines()]
    assert set(entry) == {"ts", "form_id", "documents", "seconds"}
    assert entry["seconds"] == 12.3 and entry["documents"] == 2


def test_damaged_lines_are_skipped(runs_file):
    stats.record_run("A", 1, 10.0)
    with runs_file.open("a", encoding="utf-8") as handle:
        handle.write('{"form_id": "A", "sec\n\n{"form_id": "A", "seconds": "lent"}\n')
    stats.record_run("A", 0, 30.0)
    summary = stats.summary("A")
    assert summary["runs"] == 2 and summary["average_seconds"] == 20.0


def test_runs_without_documents_have_no_per_document_figure(runs_file):
    stats.record_run("C", 0, 5.0)
    assert stats.summary()["average_seconds_per_document"] is None


def test_an_unwritable_stats_directory_never_fails_the_job(tmp_path, monkeypatch):
    blocker = tmp_path / "un_fichier"
    blocker.write_text("pas un dossier", encoding="utf-8")
    monkeypatch.setattr(stats, "STATS_DIR", blocker)
    monkeypatch.setattr(stats, "RUNS_FILE", blocker / "pipeline_runs.jsonl")
    stats.record_run("A", 1, 10.0)        # ne lève pas
    assert stats.summary()["runs"] == 0
