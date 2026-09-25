"""Préparation des champs et normalisation des valeurs (core/fields.py)."""

import json
from pathlib import Path

import pytest

from core.fields import (
    batch_fields,
    collect_form_values,
    contextualize,
    extractable_fields,
    is_blank_default,
    normalize_date,
    normalize_value,
    prepare_fields,
    resolve_option,
    retrieval_text,
)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "template"


# --- Presets -----------------------------------------------------------------

@pytest.mark.parametrize("field, expected", [
    ({"type": "bool", "preset": "/Off"}, True),
    ({"type": "bool", "preset": "/On"}, False),
    ({"type": "int", "preset": "0"}, True),
    ({"type": "int", "preset": "/0"}, False),
    ({"type": "choice", "preset": "non", "options": ["non", "oui"]}, True),
    ({"type": "choice", "preset": "0", "options": ["non", "oui (= Major RF)"],
      "option_values": ["0", "1"]}, True),
    ({"type": "choice", "preset": "1", "options": ["non", "oui"], "option_values": ["0", "1"]}, False),
    ({"type": "choice", "preset": "LAA", "options": ["LAMal", "LCA", "LAA"]}, False),
    ({"preset": "IV-Stelle Kanton Bern"}, False),
])
def test_blank_default(field, expected):
    assert is_blank_default(field) is expected


def test_extractable_fields_keeps_blank_checkboxes_and_authoritative_presets_out():
    template = {"fields": [
        {"comments": "Section 1"},
        {"id": "1.1", "question": "Urgent ?", "type": "bool", "preset": "/Off"},
        {"id": "1.2", "question": "Régime ?", "type": "choice", "preset": "LAA",
         "options": ["LAA", "LCA"]},
        {"id": "1.3", "question": "Adresse office ?", "preset": "Office AI"},
        {"id": "1.4", "question": "", "computed": "x"},
        {"id": "1.5", "question": "Nom ?"},
    ]}
    assert [f["id"] for f in extractable_fields(template)] == ["1.1", "1.5"]


def test_catalogue_exposes_blank_checkboxes():
    """Les 79 cases vierges du catalogue sont désormais soumises au modèle."""
    template = json.loads((TEMPLATE_DIR / "Form_Adressage_Angiologie.json").read_text(encoding="utf-8"))
    ids = {f["id"] for f in extractable_fields(template)}
    urgency = next(f for f in template["fields"] if f.get("name") == "appointmentUrgency")
    assert urgency["id"] in ids


# --- Questions univoques -------------------------------------------------------

def _period_fields():
    base = "topmostSubform/page1/unemployabilityS1Struct"
    fields = []
    for i, suffix in enumerate(["", "[1]", "[2]"]):
        fields.append({"id": f"1.{10 + 2 * i}", "question": "Quelle est la date de début de la période concernée ?",
                       "xml_path": f"{base}{suffix}/beginDate", "type": "date"})
        fields.append({"id": f"1.{11 + 2 * i}", "question": "Quel est le pourcentage indiqué ?",
                       "xml_path": f"{base}{suffix}/percentageNum", "type": "percent"})
    return fields


def test_repeated_questions_get_occurrence_context():
    prepared = contextualize(_period_fields() + [
        {"id": "2.1", "question": "Quelle est la date de début de la période concernée ?",
         "xml_path": "topmostSubform/page1/treatmentS1Struct/beginDate"},
        {"id": "2.2", "question": "Quel est le nom du patient ?",
         "xml_path": "topmostSubform/page1/patientS1Address/lastName"},
    ])
    by_id = {f["id"]: f for f in prepared}
    assert "période d'incapacité de travail n°1 sur 3" in by_id["1.10"]["prompt_question"]
    assert "période d'incapacité de travail n°3 sur 3" in by_id["1.14"]["prompt_question"]
    # Même question, autre structure : pas de numérotation partagée.
    assert "Contexte : traitement." in by_id["2.1"]["prompt_question"]
    # Question unique : inchangée.
    assert by_id["2.2"]["prompt_question"] == "Quel est le nom du patient ?"
    assert by_id["1.10"]["retrieval_query"].endswith("période d'incapacité de travail")


def test_repeated_siblings_without_known_struct():
    prepared = contextualize([
        {"id": "1.1", "question": "Téléphone du patient ?", "xml_path": "t/p/patientS1Address/phone"},
        {"id": "1.2", "question": "Téléphone du patient ?", "xml_path": "t/p/patientS1Address/phone[1]"},
    ])
    assert "occurrence n°1 sur 2" in prepared[0]["prompt_question"]
    assert "occurrence n°2 sur 2" in prepared[1]["prompt_question"]


def test_prefixed_diagnosis_structs_share_numbering():
    prepared = contextualize([
        {"id": f"4.{i}", "question": "Quel est le libellé du diagnostic posé ?",
         "xml_path": f"t/page1/{p}diagnosisS1Struct/name"}
        for i, p in enumerate("abde", start=1)
    ])
    assert "diagnostic n°4 sur 4" in prepared[3]["prompt_question"]


def test_retrieval_text_drops_format_instructions():
    q = "Quel est le canton ? Répondre UNIQUEMENT par deux lettres (ex. : NE, VD, GE)."
    assert retrieval_text(q) == "Quel est le canton ?"
    assert retrieval_text("Date ? [format : JJ.MM.AAAA]") == "Date ?"


def test_batches_keep_repeated_structures_together():
    fields = contextualize(
        [{"id": f"1.{i}", "question": f"Q{i} ?", "xml_path": f"t/p/f{i}"} for i in range(1, 4)]
        + _period_fields()
    )
    batches = batch_fields(fields, max_batch_size=2)
    period_batch = next(b for b in batches if any(f["id"] == "1.10" for f in b))
    assert {f["id"] for f in period_batch} == {f["id"] for f in _period_fields()}
    assert all(len(b) <= 2 for b in batches if b is not period_batch)


def test_every_catalogue_form_prepares_and_batches():
    for path in sorted(TEMPLATE_DIR.glob("Form_*.json")):
        template = json.loads(path.read_text(encoding="utf-8"))
        fields = prepare_fields(template)
        batches = batch_fields(fields)
        assert sorted(f["id"] for b in batches for f in b) == sorted(f["id"] for f in fields), path.name
        assert all(len(b) <= 32 for b in batches), path.name


# --- Valeurs ------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "Non mentionné", "non précisé dans les documents", "N/A", "null", "...", "…", "Inconnu",
    "<nom>", "JJ.MM.AAAA", "756.XXXX.XXXX.XX", "Information non disponible", "-",
])
def test_null_like_answers_become_empty(raw):
    assert normalize_value(raw, {}) == ""


@pytest.mark.parametrize("raw", ["non", "Aucun", "Aucune allergie connue", "x"])
def test_real_answers_survive(raw):
    assert normalize_value(raw, {}) == raw


@pytest.mark.parametrize("raw, expected", [
    ("2025-03-15", "15.03.2025"),
    ("15/3/2025", "15.03.2025"),
    ("15 mars 2025", "15.03.2025"),
    ("1er février 2024", "01.02.2024"),
    ("dès le 07.04.2026", "07.04.2026"),
    ("du 01.01.2025 au 31.01.2025", "du 01.01.2025 au 31.01.2025"),
    ("31.02.2025", "31.02.2025"),
])
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected


@pytest.mark.parametrize("raw, kind, expected", [
    ("Oui", "bool", "oui"), ("On", "bool", "oui"), ("1", "bool", "oui"),
    ("Non, pas d'urgence", "bool", "non"), ("peut-être", "bool", ""),
    ("Madame", "sex", "F"), ("Monsieur", "sex", "M"), ("masculin", "sex", "M"),
    ("50 %", "percent", "50"), ("12 séances", "int", "12"),
    (["Lombalgie", "HTA"], None, "Lombalgie\nHTA"), (42.0, None, "42"), (True, None, "oui"),
])
def test_normalize_value_by_type(raw, kind, expected):
    assert normalize_value(raw, {"type": kind}) == expected


def test_choice_option_that_looks_null_is_kept():
    assert normalize_value("Inconnue", {"type": "choice", "options": ["Maladie", "Inconnue"]}) == "Inconnue"


@pytest.mark.parametrize("value, expected", [
    ("oui", "1"), ("Oui", "1"), ("1", "1"), ("non", "0"), ("peut-être", "peut-être"),
])
def test_resolve_option(value, expected):
    field = {"options": ["non", "oui (= Major RF)"], "option_values": ["0", "1"]}
    assert resolve_option(value, field) == expected


def test_collect_form_values_routes_types_and_recipient():
    template = {
        "_recipient_by_canton": {"NE": {"recipientBlock": "Office AI NE", "street": "Espacité 4"}},
        "fields": [
            {"id": "1.1", "name": "treatmentCanton", "type": "choice", "options": ["NE", "VD"],
             "xml_path": "a/treatmentCanton", "acroform_name": "a.treatmentCanton"},
            {"id": "1.2", "name": "urgent", "type": "bool", "options": ["On", "Off"],
             "xml_path": "a/urgent", "acroform_name": "a.urgent"},
            {"id": "1.3", "name": "ask", "type": "choice", "options": ["non", "oui"],
             "option_values": ["0", "1"], "xml_path": "a/ask", "acroform_name": "a.ask"},
            {"id": "1.4", "name": "birthDate", "type": "date", "xml_path": "a/birthDate"},
            {"id": "1.5", "name": "recipientBlock", "xml_path": "a/recipientBlock",
             "acroform_name": "a.recipientBlock"},
            {"id": "1.6", "name": "footer", "computed": "Pied de page", "acroform_name": "a.footer"},
            {"id": "1.7", "name": "remark", "xml_path": "a/remark"},
            {"id": "1.8", "name": "street", "xml_path": "a/patientS1Address/street"},
            {"id": "1.9", "name": "street", "xml_path": "a/insuranceS1Address/street", "preset": "Rue BE"},
        ],
    }
    results = [
        {"id": "1.1", "result": {"value": "NE"}},
        {"id": "1.2", "result": {"value": "oui"}},
        {"id": "1.3", "result": {"value": "oui"}},
        {"id": "1.4", "result": {"value": "2024-02-01"}},
        {"id": "1.7", "result": {"value": "non mentionné"}},
        {"id": "1.8", "result": {"value": "Rue du Lac 12"}},
        {"id": "9.9", "error": "extraction_failed"},
    ]
    xfa, acro = collect_form_values(template, results)
    assert xfa["a/urgent"] == "On" and acro["a.urgent"] == "1"
    assert xfa["a/ask"] == "1" and acro["a.ask"] == "1"
    assert xfa["a/birthDate"] == "01.02.2024"
    assert xfa["a/recipientBlock"] == "Office AI NE"
    assert acro["a.footer"] == "Pied de page"
    assert "a/remark" not in xfa
    # La table cantonale vise le bloc de l'office, pas l'homonyme du patient.
    assert xfa["a/insuranceS1Address/street"] == "Espacité 4"
    assert xfa["a/patientS1Address/street"] == "Rue du Lac 12"


def test_procedure_slots_are_not_numbered_as_diagnoses():
    """Blocs `d`/`e` codés CHOP : interventions, numérotées à part des diagnostics."""
    template = json.loads((TEMPLATE_DIR / "Form_LAA_PriseEnChargeHospitaliere.json").read_text(encoding="utf-8"))
    by_path = {f["xml_path"]: f for f in prepare_fields(template)}
    assert "diagnostic n°2 sur 2" in by_path["topmostSubform/page1/bdiagnosisS1Struct/name"]["prompt_question"]
    procedure = by_path["topmostSubform/page1/ediagnosisS1Struct/code"]
    assert "CHOP" in procedure["question"]
    assert "intervention n°2 sur 2" in procedure["prompt_question"]
