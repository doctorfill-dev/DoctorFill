"""
Chaque champ de chaque formulaire du catalogue atteint le PDF, dans les deux couches.

Pour les 21 formulaires : on simule une réponse du modèle pour tous les champs
extraits — sous une forme réaliste, à normaliser (date ISO, « Oui », « 50 % »,
libellé d'option) — puis on remplit un PDF hybride de même structure avec le
code de production. Un champ que le template décrit mais que le remplissage ne
retrouve pas (chemin XFA, nom AcroForm, état de case, valeur d'export) fait
échouer le test : c'est exactement la régression silencieuse qu'un template
régénéré ou une modification de core/ pourrait introduire.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import app as orchestrator
from core.fields import is_recipient_field, prepare_fields
from tests.form_factory import build_hybrid_form, read_acroform, read_datasets, widget_kind

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "template"
FORMS = sorted(p.stem.removeprefix("Form_") for p in TEMPLATE_DIR.glob("Form_*.json"))


def _answer(field: dict) -> tuple[str, str, str]:
    """(réponse du modèle, valeur XFA attendue, /V AcroForm attendue) pour un champ."""
    kind = field.get("type")
    options, values = field.get("options") or [], field.get("option_values") or []
    widget = widget_kind(field)
    if kind == "date":
        return "2026-03-15", "15.03.2026", "15.03.2026"
    if kind == "percent":
        return "50 %", "50", "50"
    if kind == "int":
        return "12 séances", "12", "12"
    if kind == "sex":
        return "féminin", "F", "F"
    if kind == "bool":
        on = options[0] if options else "1"
        return "Oui", on, "/On" if widget == "checkbox" else "/1"
    if kind == "choice" and options:
        label = options[-1]
        if widget == "radio":
            return label, values[-1], f"/{values[-1]}"
        return label, label, label
    value = f"Valeur {field['id']}"
    return value, value, value


@pytest.mark.parametrize("form_id", FORMS)
def test_every_field_reaches_both_layers(form_id, tmp_path, monkeypatch):
    template = json.loads((TEMPLATE_DIR / f"Form_{form_id}.json").read_text(encoding="utf-8"))
    monkeypatch.chdir(tmp_path)
    build_hybrid_form(template, tmp_path / "forms" / f"Form_{form_id}.pdf")

    fields = prepare_fields(template)
    results, expected_xfa, expected_acro = [], {}, {}
    for field in fields:
        answer, xfa_value, acro_value = _answer(field)
        results.append({"id": field["id"], "result": {"value": answer, "source_quote": ""}})
        expected_xfa[field["xml_path"]] = xfa_value
        expected_acro[field["acroform_name"]] = acro_value

    # Canton : une valeur de la table pour exercer le destinataire cantonal.
    table = template.get("_recipient_by_canton") or {}
    canton_field = next((f for f in fields if f.get("name") == "treatmentCanton"), None)
    if table and canton_field:
        canton = "NE" if "NE" in table else sorted(table)[0]
        next(r for r in results if r["id"] == canton_field["id"])["result"]["value"] = canton
        expected_xfa[canton_field["xml_path"]] = expected_acro[canton_field["acroform_name"]] = canton
        for name, value in table[canton].items():
            for f in template["fields"]:
                if f.get("name") == name and is_recipient_field(f):
                    expected_xfa[f["xml_path"]] = expected_acro[f["acroform_name"]] = value

    output, form_type = orchestrator._fill_pdf("test", form_id, template, results, tmp_path)
    assert form_type == "hybrid"

    datasets = read_datasets(output, list(expected_xfa))
    acroform = read_acroform(output)
    missing_xfa = {p: (v, datasets.get(p)) for p, v in expected_xfa.items()
                   if v and datasets.get(p) != v}
    missing_acro = {n: (v, acroform.get(n)) for n, v in expected_acro.items()
                    if v and acroform.get(n) != v}
    assert not missing_xfa, f"{len(missing_xfa)} champ(s) XFA non écrits : {list(missing_xfa.items())[:5]}"
    assert not missing_acro, f"{len(missing_acro)} champ(s) AcroForm non écrits : {list(missing_acro.items())[:5]}"
    assert len(fields) > 0
