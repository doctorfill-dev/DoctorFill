"""
Les 21 dossiers d'évaluation, de bout en bout, par l'API HTTP — modèle simulé.

Chaque dossier de `eval/dossiers/` (PDF réels, 4 à 7 documents) est soumis à
/process-form avec le script de non-régression lui-même (`eval/regression.py`),
contre l'application en mémoire. OCR, embeddings et LLM sont simulés ; le
« modèle » répond la vérité terrain dérivée des scénarios (`eval/truth.py`).

Ce que ça garantit à chaque merge, pour chaque formulaire du catalogue :
- le dossier traverse tout le pipeline sans erreur (upload, OCR, synthèse,
  extraction, remplissage, /fields, /download) ;
- une valeur juste en sortie du modèle arrive juste dans /fields *et* dans le
  PDF livré — normalisation, options, destinataire cantonal compris ;
- le script de non-régression note 100 % un modèle parfait, et détecte une
  valeur fausse, une valeur inventée et une non-réponse (sinon il ne
  protégerait de rien sur le DGX).

Ce qu'il ne garantit pas : la qualité du vrai modèle. C'est le rôle de
`eval/regression.py` contre le backend réel (voir docs/wiki/Tests.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app as orchestrator
import extraction
from core.fields import normalize_value, prepare_fields
from tests import fakes
from tests.form_factory import build_hybrid_form, read_acroform

EVAL_DIR = Path(__file__).resolve().parents[3] / "eval"
sys.path.insert(0, str(EVAL_DIR))

import regression  # noqa: E402
import truth  # noqa: E402

FORMS = sorted(truth.load_scenarios())


class DossierServices:
    """OCR rendant le markdown du dossier, LLM répondant la vérité terrain."""

    def __init__(self):
        self.form_id = ""
        self.answers: dict[str, str] = {}
        self.fail_ocr = False

    def use(self, form_id: str, corrupt: set[str] = frozenset(),
            extra: dict[str, str] | None = None) -> None:
        """`corrupt` : champs répondus faux ; `extra` : réponses hors vérité terrain."""
        self.form_id = form_id
        expected = truth.derive_truth(form_id)
        self.answers = {fid: ("valeur fausse" if fid in corrupt else exp.expected)
                        for fid, exp in expected.items()}
        self.answers.update(extra or {})

    def handler(self, request):
        path = request.url.path
        if path.endswith("/extract"):
            if self.fail_ocr:
                return httpx.Response(500, json={"detail": "échec"})
            name = fakes.uploaded_filename(request)
            md = (truth.DOSSIERS_DIR / self.form_id / name).with_suffix(".md")
            return httpx.Response(200, json={"markdown": md.read_text(encoding="utf-8")})
        if path.endswith("/embed"):
            return fakes.embed_response(request)
        if path.endswith("/rerank"):
            return fakes.rerank_response(request)
        if fakes.is_synthesis(request):
            return fakes.completion({"patient": {}, "diagnostics": [], "incapacites_travail": []})
        return fakes.completion({fid: {"value": self.answers.get(fid, ""), "source_quote": ""}
                                 for fid in fakes.schema_ids(request)})


@pytest.fixture(scope="module")
def form_pdfs(tmp_path_factory):
    """Un PDF hybride de test par formulaire, construit une fois pour le module."""
    root = tmp_path_factory.mktemp("catalogue")
    for form_id in FORMS:
        build_hybrid_form(truth.load_template(form_id), root / "forms" / f"Form_{form_id}.pdf")
    return root / "forms"


@pytest.fixture
def api(form_pdfs, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "template").symlink_to(truth.TEMPLATES_DIR, target_is_directory=True)
    (tmp_path / "forms").symlink_to(form_pdfs, target_is_directory=True)
    monkeypatch.setattr(orchestrator, "VALID_FORM_IDS", set(FORMS))
    services = DossierServices()
    fakes.install(monkeypatch, lambda request: services.handler(request))
    return TestClient(orchestrator.app), services


def _no_wait(_seconds: float) -> None:
    return None


@pytest.mark.parametrize("form_id", FORMS)
def test_dossier_fits_the_full_context_mode(form_id):
    docs = truth.dossier_documents(form_id)
    assert docs, "dossier vide"
    assert extraction.estimate_tokens(extraction.full_documents_text(docs)) <= extraction.FULL_CONTEXT_MAX_TOKENS


@pytest.mark.parametrize("form_id", FORMS)
def test_perfect_model_scores_perfectly_through_the_api(api, form_id):
    client, services = api
    services.use(form_id)
    result = regression.run_form(client, form_id, truth.dossier_pdfs(form_id), sleep=_no_wait)

    assert result["status"] == "completed", result.get("message")
    assert result["errors"] == 0
    wrong = [d for d in result["details"] if not d["match"]]
    assert result["truth_fields"] >= 5
    assert not wrong, wrong[:3]
    assert result["invented"] == 0 and result["non_answers"] == 0 and result["non_answers_erased"] == 0

    # Le PDF livré porte les mêmes valeurs que /fields.
    job = orchestrator.JOBS[result["job_id"]]
    pdf = client.get(f"/download/{result['job_id']}", params={"token": job["token"]})
    assert pdf.status_code == 200
    out = Path(job["file_path"])
    acro = read_acroform(out)
    template = truth.load_template(form_id)
    by_id = {str(f["id"]): f for f in template["fields"] if "id" in f}
    for fid, exp in truth.derive_truth(form_id).items():
        field = by_id[fid]
        written = acro.get(field["acroform_name"])
        assert written is not None and truth.matches(exp.expected, normalize_value(written, field),
                                                     exp.tolerance), \
            f"{fid} ({field['name']}) : attendu {exp.expected!r}, PDF {written!r}"


def test_regression_gate_detects_a_wrong_value_and_a_failed_job(api, tmp_path):
    client, services = api
    form_id = "LCA_IncapaciteTravail"
    baseline = tmp_path / "baseline.json"
    argv = ["--forms", form_id, "--baseline", str(baseline), "--parallel", "1"]

    services.use(form_id)
    assert regression.main(argv + ["--update-baseline"], client=client) == 0
    reference = json.loads(baseline.read_text(encoding="utf-8"))
    assert reference["forms"][form_id]["accuracy"] == 1.0

    assert regression.main(argv, client=client) == 0

    # Deux valeurs fausses : au-delà de la tolérance d'un champ, la porte se ferme.
    corrupt = set(sorted(truth.derive_truth(form_id))[:2])
    services.use(form_id, corrupt=corrupt)
    report = tmp_path / "report.md"
    assert regression.main(argv + ["--report", str(report)], client=client) == 1
    assert "❌" in report.read_text(encoding="utf-8")

    # Des valeurs dans les périodes d'incapacité que le dossier n'atteste pas.
    absent = truth.derive_absent(form_id)
    services.use(form_id, extra={fid: "50" for fid in absent})
    assert regression.main(argv + ["--report", str(report)], client=client) == 1
    assert "valeur(s) inventée(s)" in report.read_text(encoding="utf-8")

    services.fail_ocr = True
    assert regression.main(argv, client=client) == 2


def test_non_answers_are_counted_even_once_erased(api):
    """Effacées par la normalisation, les non-réponses restent comptées : c'est ce
    qui distingue un champ vidé de son bruit d'un champ que le modèle ne trouve plus."""
    client, services = api
    form_id = "LCA_IncapaciteTravail"
    truth_ids = set(truth.derive_truth(form_id)) | set(truth.derive_absent(form_id))
    others = [str(f["id"]) for f in prepare_fields(truth.load_template(form_id))
              if str(f["id"]) not in truth_ids and not f.get("type")][:3]
    services.use(form_id, extra={fid: "Non mentionné dans le dossier" for fid in others})
    result = regression.run_form(client, form_id, truth.dossier_pdfs(form_id), sleep=_no_wait)

    assert result["non_answers_erased"] == 3
    assert result["non_answers"] == 0                      # rien de tel dans le PDF
    assert result["correct"] == result["truth_fields"]


def test_score_flags_non_answers_and_invented_values():
    exp = truth.Expectation
    payload = [
        {"id": "1.1", "value": "Dupont"},
        {"id": "1.2", "value": "N/A"},                                      # écrite
        {"id": "1.3", "value": "", "raw_value": "non mentionné"},           # effacée
        {"id": "1.4", "value": "021 555 00 00"},                            # inventée
        {"id": "1.5", "value": ""},                                         # vide, comme il faut
    ]
    result = truth.score({"1.1": exp("Dupont", "exact", "patient")}, payload,
                         {"1.4": exp("", "empty", "coordonnees"), "1.5": exp("", "empty", "coordonnees")})
    assert result["accuracy"] == 1.0
    assert (result["non_answers"], result["non_answers_erased"]) == (1, 1)
    assert (result["invented"], result["absent_fields"]) == (1, 2)
    assert result["invented_details"] == [{"id": "1.4", "category": "coordonnees", "extracted": "021 555 00 00"}]


@pytest.mark.parametrize("form_id", FORMS)
def test_absent_fields_are_extracted_and_never_expected(form_id):
    absent = truth.derive_absent(form_id)
    extracted = {str(f["id"]) for f in prepare_fields(truth.load_template(form_id))}
    assert set(absent) <= extracted
    assert not set(absent) & set(truth.derive_truth(form_id))


def test_absent_fields_cover_unattested_incapacity_periods():
    # Deux périodes attestées sur les quatre du formulaire : n°3 et n°4 restent vides.
    absent = truth.derive_absent("LAMal_RapportInitial")
    assert {"4.13", "4.16", "4.19", "4.22"} <= set(absent)
    assert not {"4.4", "4.10"} & set(absent)


def test_gate_flags_invented_values_and_written_non_answers():
    base = {"forms": {"F": {"correct": 10, "truth_fields": 10, "errors": 0,
                            "invented": 0, "non_answers": 0}}}
    ok = {"form": "F", "status": "completed", "correct": 10, "truth_fields": 10, "errors": 0}
    assert regression.compare([{**ok, "invented": 1, "non_answers": 0}], base) == []   # bruit toléré
    assert regression.compare([{**ok, "invented": 2, "non_answers": 0}], base)
    assert regression.compare([{**ok, "invented": 0, "non_answers": 1}], base)
    # Référence antérieure à ces mesures : pas de comparaison.
    old = {"forms": {"F": {"correct": 10, "truth_fields": 10, "errors": 0}}}
    assert regression.compare([{**ok, "invented": 5, "non_answers": 5}], old) == []


def test_gate_tolerates_one_field_of_noise():
    base = {"forms": {"F": {"correct": 10, "truth_fields": 10, "errors": 0}}}
    one_off = [{"form": "F", "status": "completed", "correct": 9, "truth_fields": 10, "errors": 0}]
    assert regression.compare(one_off, base, max_global_drop=0.2) == []
    two_off = [{"form": "F", "status": "completed", "correct": 8, "truth_fields": 10, "errors": 0}]
    assert regression.compare(two_off, base, max_global_drop=0.2)
