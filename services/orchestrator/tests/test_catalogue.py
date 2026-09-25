"""
Invariants des 21 templates du catalogue.

Les templates sont régénérés par tools/gen_template.py et retouchés à la main :
chacune de ces règles correspond à un défaut déjà rencontré (identifiants en
double, deux entrées visant le même nœud XFA, options fusionnées avec leurs
valeurs d'export, formulaire publié avec des questions vides…).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import extraction
from core.fields import batch_fields, is_recipient_field, prepare_fields
from prompts import SYSTEM_PROMPT_BATCH_EXTRACT, build_batch_extraction_messages

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "template"
TEMPLATES = {p.stem.removeprefix("Form_"): json.loads(p.read_text(encoding="utf-8"))
             for p in sorted(TEMPLATE_DIR.glob("Form_*.json"))}
KNOWN_TYPES = {None, "date", "bool", "choice", "sex", "percent", "int"}
CANTONS = {"AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU", "NE", "NW",
           "OW", "SG", "SH", "SO", "SZ", "TG", "TI", "UR", "VD", "VS", "ZG", "ZH", "LI"}


def _fields(template: dict) -> list[dict]:
    return [f for f in template["fields"] if "id" in f]


def test_catalogue_is_complete():
    catalogue = (TEMPLATE_DIR.parent / "tools" / "catalog_fr.txt").read_text(encoding="utf-8")
    listed = {line.split()[1] for line in catalogue.splitlines()
              if line.strip() and not line.startswith("#")}
    assert listed == set(TEMPLATES)


@pytest.mark.parametrize("form_id", sorted(TEMPLATES))
def test_identifiers_and_targets_are_unique(form_id):
    fields = _fields(TEMPLATES[form_id])
    for key in ("id", "xml_path", "acroform_name"):
        values = [str(f.get(key)) for f in fields]
        duplicates = {v for v in values if values.count(v) > 1}
        assert not duplicates, f"{key} en double : {sorted(duplicates)[:5]}"
    assert all(re.fullmatch(r"\d+\.\d+", str(f["id"])) for f in fields)
    assert all(f.get("xml_path") and f.get("acroform_name") for f in fields)


@pytest.mark.parametrize("form_id", sorted(TEMPLATES))
def test_published_forms_have_every_question_written(form_id):
    template = TEMPLATES[form_id]
    assert template.get("_reviewed") is True, "formulaire non publié par /forms"
    unwritten = [f["id"] for f in _fields(template)
                 if "computed" not in f and not str(f.get("question") or "").strip()]
    assert not unwritten


@pytest.mark.parametrize("form_id", sorted(TEMPLATES))
def test_field_types_and_options_are_consistent(form_id):
    for f in _fields(TEMPLATES[form_id]):
        assert f.get("type") in KNOWN_TYPES, f["id"]
        options, values = f.get("options") or [], f.get("option_values")
        if values is not None:
            assert len(values) == len(options), f"{f['id']} : libellés et valeurs désalignés"
        if f.get("type") == "choice" and f.get("question") and not f.get("preset"):
            assert options, f"{f['id']} : liste de choix sans options"
        # Libellés suivis de leurs index : deux groupes <items> fusionnés.
        n = len(options) // 2
        assert not (n and not values and options[n:] == [str(i) for i in range(n)]), \
            f"{f['id']} : options fusionnées avec leurs valeurs d'export"


@pytest.mark.parametrize("form_id", sorted(TEMPLATES))
def test_canton_recipients_target_existing_fields(form_id):
    template = TEMPLATES[form_id]
    table = template.get("_recipient_by_canton")
    if not table:
        return
    targets = {f.get("name") for f in _fields(template) if is_recipient_field(f)}
    assert set(table) <= CANTONS
    for canton, entries in table.items():
        assert set(entries) & targets, f"{canton} : aucun champ du destinataire visé"
    canton_fields = [f for f in _fields(template) if f.get("name") == "treatmentCanton"]
    assert canton_fields, "table cantonale sans champ treatmentCanton"
    assert set(table) <= set(canton_fields[0].get("options") or []), "canton de la table non proposé au modèle"


@pytest.mark.parametrize("form_id", sorted(TEMPLATES))
def test_every_batch_fits_the_model_window(form_id):
    """Le plus gros lot, avec la synthèse et le dossier intégral au seuil, tient dans la fenêtre."""
    batches = batch_fields(prepare_fields(TEMPLATES[form_id]))
    synthesis = "x" * 3 * 4000                                   # synthèse de ~4k tokens
    documents = "x" * 3 * extraction.FULL_CONTEXT_MAX_TOKENS     # dossier au seuil du mode intégral
    for batch in batches:
        messages = build_batch_extraction_messages(batch, synthesis, documents, full_documents=True)
        prompt = sum(extraction.estimate_tokens(m["content"]) for m in messages)
        assert prompt + extraction.MAX_TOKENS_EXTRACT <= extraction.LLM_MAX_MODEL_LEN, \
            f"lot {[f['id'] for f in batch][:3]}… : {prompt} tokens de prompt"
    assert extraction.estimate_tokens(SYSTEM_PROMPT_BATCH_EXTRACT) < 2000


def test_no_field_silently_leaves_the_extraction():
    """
    Aucun formulaire ne perd de champs soumis au modèle sans qu'on le décide.

    C'est ainsi que 91 champs avaient disparu : une règle de filtrage trop large,
    sans aucun test pour le remarquer. Une hausse passe ; une baisse voulue se
    reporte dans tests/catalogue_coverage.json.
    """
    snapshot = json.loads((Path(__file__).parent / "catalogue_coverage.json").read_text(encoding="utf-8"))
    current = {form_id: len(prepare_fields(t)) for form_id, t in TEMPLATES.items()}
    lost = {f: (n, current.get(f, 0)) for f, n in snapshot["extractable"].items() if current.get(f, 0) < n}
    assert not lost, f"champs perdus (avant, après) : {lost}"
