"""
Évaluation de la qualité en CI, sans exposer ni le backend ni les valeurs (issue 39, audit S12).

- le job `eval` ne tourne jamais dans un pipeline de MR, et pas sur la machine
  qui traite les dossiers ;
- la clé d'API vient de l'environnement, jamais d'un argument (visible dans `ps`) ;
- avec `--no-values`, ni le rapport ni le JSON ne contiennent une valeur
  attendue ou extraite ;
- des seuils par catégorie ferment la porte, référence ou pas.

Dossiers d'évaluation fictifs uniquement (eval/dossiers/).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app as orchestrator
from tests import fakes
from tests.form_factory import build_hybrid_form
# Importé en premier : ce module place eval/ dans sys.path.
from tests.test_eval_dossiers import DossierServices
import regression  # noqa: E402
import truth  # noqa: E402

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[3]
CI_FILE = REPO / ".gitlab-ci.yml"
FAKE_VALUE = "Patient Test Valeur Fausse"
FORM_ID = "LAA_MoyensAuxiliaires"           # un seul dossier pour ce formulaire


@pytest.fixture(scope="module")
def eval_job():
    return yaml.safe_load(CI_FILE.read_text(encoding="utf-8"))["eval"]


@pytest.fixture
def eval_api(tmp_path, monkeypatch):
    """L'orchestrateur en mémoire, un seul formulaire, modèle simulé (voir test_eval_dossiers)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "template").symlink_to(truth.TEMPLATES_DIR, target_is_directory=True)
    (tmp_path / "forms").mkdir()
    build_hybrid_form(truth.load_template(FORM_ID), tmp_path / "forms" / f"Form_{FORM_ID}.pdf")
    monkeypatch.setattr(orchestrator, "VALID_FORM_IDS", {FORM_ID})
    services = DossierServices()
    fakes.install(monkeypatch, lambda request: services.handler(request))
    return TestClient(orchestrator.app), services


# --- Le job de CI -------------------------------------------------------------------------

def test_eval_job_never_runs_in_a_merge_request_pipeline(eval_job):
    rules = eval_job["rules"]
    first = rules[0]
    assert "merge_request_event" in first.get("if", "") and first.get("when") == "never"
    for rule in rules:
        if rule.get("when") == "never":
            continue
        # Toute règle qui lance le job est conditionnée à la branche par défaut ou
        # à un tag protégé, et manuelle.
        condition = rule.get("if", "")
        assert "CI_DEFAULT_BRANCH" in condition or "CI_COMMIT_REF_PROTECTED" in condition, rule
        assert rule.get("when") == "manual", rule


def test_eval_job_does_not_use_the_production_runner(eval_job):
    assert "dgx" not in [str(t).lower() for t in eval_job.get("tags", [])]
    assert eval_job.get("tags"), "un runner dédié, désigné par son tag"


def test_eval_job_keeps_the_key_out_of_arguments_and_values_out_of_logs(eval_job):
    script = "\n".join(eval_job["script"])
    assert "--api-key" not in script
    assert "--no-values" in script
    assert "after_script" not in eval_job          # plus de `cat report.md`
    # L'adresse du backend est une variable protégée du projet, pas une valeur du dépôt.
    assert "EVAL_API" not in (eval_job.get("variables") or {})


# --- La clé d'API -------------------------------------------------------------------------

def test_api_key_argument_is_refused():
    with pytest.raises(SystemExit):
        regression.main(["--api-key", "cle-de-test"])


def test_api_key_is_read_from_the_environment(monkeypatch, capsys):
    monkeypatch.setenv("DOCTORFILL_API_KEY", "cle-de-test")
    seen = {}

    class FakeClient:
        def __init__(self, *args, headers=None, **kwargs):
            seen.update(headers or {})

        def get(self, *args, **kwargs):
            raise httpx.ConnectError("injoignable")

    monkeypatch.setattr(regression.httpx, "Client", FakeClient)
    assert regression.main(["--api", "http://backend.invalid:8080", "--forms", FORM_ID]) == 2
    assert seen.get("X-API-Key") == "cle-de-test"
    # Ni la clé ni l'adresse du backend dans la sortie du job.
    err = capsys.readouterr()
    assert "cle-de-test" not in err.out + err.err
    assert "backend.invalid" not in err.out + err.err


# --- Rapport sans valeurs -----------------------------------------------------------------

def _result_with_values() -> dict:
    return {
        "form": "F", "status": "completed", "correct": 1, "truth_fields": 2, "accuracy": 0.5,
        "filled": 3, "fields": 4, "fill_rate": 0.75, "invented": 1, "absent_fields": 1, "non_answers": 1,
        "non_answers_erased": 0, "errors": 0, "pdf_mismatches": 1, "seconds": 10.0,
        "warnings": ["Document illisible, ignoré : Patient_Test_scan.pdf"],
        "details": [
            {"id": "1.1", "category": "patient", "expected": "Patient Test", "extracted": "Patient Test",
             "match": True, "status": "ok"},
            {"id": "1.2", "category": "patient", "expected": "01.01.1970", "extracted": FAKE_VALUE,
             "match": False, "status": "wrong"},
        ],
        "invented_details": [{"id": "2.1", "category": "patient", "extracted": FAKE_VALUE}],
        "non_answer_details": [{"id": "2.2", "extracted": "non mentionné pour Patient Test"}],
        "pdf_details": [{"id": "1.2", "category": "patient", "fields": FAKE_VALUE, "pdf": "Patient Test"}],
    }


def test_report_without_values_keeps_scores_and_field_ids():
    report = regression.report_markdown([_result_with_values()], ["F : 1/2 champs justes"], None,
                                        no_values=True)
    assert "Patient" not in report
    assert "01.01.1970" not in report
    assert "| F | 1/2 |" in report
    assert "| F | 1.2 | patient | wrong |" in report
    assert "| patient | 1/2 | 50.0% | — |" in report
    # Sans l'option, le rapport détaillé reste disponible en local.
    assert FAKE_VALUE in regression.report_markdown([_result_with_values()], [], None)


def test_json_without_values_keeps_counts_and_field_ids():
    stripped = regression.strip_values(_result_with_values())
    dumped = json.dumps(stripped, ensure_ascii=False)
    assert "Patient" not in dumped and "01.01.1970" not in dumped
    assert stripped["correct"] == 1 and stripped["warnings_count"] == 1
    assert [d["id"] for d in stripped["details"]] == ["1.1", "1.2"]
    assert stripped["details"][1] == {"id": "1.2", "category": "patient", "match": False, "status": "wrong"}


def test_no_values_artifacts_contain_no_value_of_the_synthetic_dossier(eval_api, tmp_path):
    """Recherche de chaque valeur connue du dossier dans les artefacts : aucune occurrence."""
    client, services = eval_api
    expected = truth.derive_truth(FORM_ID)
    services.use(FORM_ID, corrupt=set(sorted(expected)[:2]))
    report, results = tmp_path / "report.md", tmp_path / "results.json"
    argv = ["--forms", FORM_ID, "--baseline", str(tmp_path / "absent.json"), "--parallel", "1",
            "--no-values", "--report", str(report), "--json", str(results)]
    assert regression.main(argv, client=client) in (0, 1)

    artifacts = report.read_text(encoding="utf-8") + results.read_text(encoding="utf-8")
    assert "valeur fausse" not in artifacts
    known = [e.expected for e in expected.values() if len(str(e.expected)) >= 6]
    assert known, "le dossier doit avoir des valeurs assez longues pour être cherchées"
    for value in known:
        assert str(value) not in artifacts, f"valeur du dossier dans les artefacts : {value!r}"


# --- Seuils par catégorie -----------------------------------------------------------------

def test_category_below_its_threshold_is_a_regression():
    baseline = {"thresholds": {"categories": {"patient": 0.98, "medecin": 0.5}}}
    problems = regression.compare([_result_with_values()], baseline)
    assert any("catégorie patient" in p for p in problems)
    assert not any("catégorie medecin" in p for p in problems)      # aucune donnée : pas jugée


def test_update_keeps_hand_set_thresholds():
    previous = {"thresholds": {"categories": {"patient": 0.98}}}
    new = regression.baseline_from([_result_with_values()], {"build": "test"}, previous)
    assert new["thresholds"] == previous["thresholds"]
    assert new["categories"]["patient"] == {"correct": 1, "total": 2, "accuracy": 0.5}


def test_repository_baseline_has_a_threshold_for_every_category():
    baseline = json.loads(regression.BASELINE_PATH.read_text(encoding="utf-8"))
    thresholds = regression.category_thresholds(baseline)
    categories = {e.category for dossier in truth.load_scenarios() for e in truth.derive_truth(dossier).values()}
    assert categories <= set(thresholds), categories - set(thresholds)
    assert all(0 < t <= 1 for t in thresholds.values())
