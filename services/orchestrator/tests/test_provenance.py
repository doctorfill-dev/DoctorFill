"""
Rattachement d'une valeur extraite à son texte source (core/provenance.py).

C'est le signal de confiance que voit le clinicien : chaque verdict doit dire
vrai. Une valeur inventée ne doit pas passer pour attestée, une citation
recomposée ne doit pas valoir preuve, un texte produit par le modèle (la
synthèse) ne doit jamais suffire à « vérifier » une valeur.

Documents fictifs ; patiente « FICTIF Alice », ville « Testville ».
"""

from __future__ import annotations

import pytest

from core.provenance import (
    ATTESTED,
    INFERRED,
    NOT_CHECKABLE,
    UNVERIFIED,
    VERIFIED,
    SourceIndex,
    _date_variants,
    ground_value,
    normalize,
)

FICHE = (
    "## Page 1\n\n"
    "Fiche administrative fictive.\n"
    "Nom : FICTIF\n"
    "Prénom : Alice\n\n"
    "## Page 2\n\n"
    "Née le 15 mars 1985 à Testville.\n"
    "Complica tion post-opératoire sans gravité.\n"
)


@pytest.fixture
def index():
    return SourceIndex([{"filename": "01_fiche.pdf", "markdown": FICHE},
                        {"filename": "02_vide.pdf", "markdown": ""}])


# --- Normalisation ---------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("  Évaluation: 756.1234 ", "evaluation 756 1234"),   # ponctuation → espace, nombres non soudés
    ("Née à Genève", "nee a geneve"),
    ("---", ""),
    ("", ""),
])
def test_normalize(text, expected):
    assert normalize(text) == expected


@pytest.mark.parametrize("value, contains", [
    ("15.03.2025", ["15.03.2025", "15 mars 2025"]),
    ("2025-03-15", ["15.03.2025", "15 mars 2025"]),
    ("3/4/2025", ["03.04.2025", "3.4.2025", "3 avril 2025"]),
])
def test_date_variants(value, contains):
    variants = _date_variants(value)
    for form in contains:
        assert form in variants


@pytest.mark.parametrize("value", ["15.13.2025", "32.01.2025", "texte", "2025"])
def test_no_variants_for_impossible_or_non_dates(value):
    assert _date_variants(value) == []


# --- Recherche -------------------------------------------------------------------------

def test_find_returns_document_page_and_match(index):
    hit = index.find("FICTIF")
    assert hit["document"] == "01_fiche.pdf" and hit["page"] == 1
    assert hit["match"] == "FICTIF" and hit["derived"] is False
    assert "##" not in hit["excerpt"]

    later = index.find("15 mars 1985")
    assert later["page"] == 2 and later["match"] == "15 mars 1985"


def test_short_values_need_word_boundaries():
    index = SourceIndex([{"filename": "a.pdf", "markdown": "Né en 1950."}])
    assert index.find("50") is None
    assert index.find("1950") is not None


def test_words_split_by_the_text_layer_are_found(index):
    hit = index.find("complication post-opératoire")
    assert hit is not None
    assert hit["match"] == "Complica tion post-opératoire"


def test_nothing_to_look_for(index):
    assert index.find("!!!") is None
    assert index.find("absent du dossier") is None


def test_documents_without_pages_or_name():
    index = SourceIndex([{"markdown": "Nom : FICTIF"}])
    hit = index.find("FICTIF")
    assert hit["document"] == "document" and hit["page"] is None
    assert hit["excerpt"] == "Nom : FICTIF"


def test_excerpt_is_marked_when_cut():
    text = "x " * 200 + "CIBLE" + " y" * 200
    hit = SourceIndex([{"filename": "long.pdf", "markdown": text}]).find("CIBLE")
    assert hit["excerpt"].startswith("… ") and hit["excerpt"].endswith(" …")
    assert "CIBLE" in hit["excerpt"]


# --- Verdicts --------------------------------------------------------------------------

def test_value_inside_a_real_quote_is_verified(index):
    result = ground_value("FICTIF", "Nom : FICTIF", index)
    assert result["grounding"] == VERIFIED and result["quote_verified"] is True
    assert result["source_document"] == "01_fiche.pdf" and result["source_page"] == 1
    assert result["source_match"] == "Nom : FICTIF"


def test_date_written_in_words_is_verified(index):
    result = ground_value("15.03.1985", "Née le 15 mars 1985", index)
    assert result["grounding"] == VERIFIED and result["source_page"] == 2


def test_value_found_elsewhere_than_the_quote_is_attested(index):
    invented_quote = ground_value("FICTIF", "Patiente hospitalisée en urgence", index)
    assert invented_quote["grounding"] == ATTESTED and invented_quote["quote_verified"] is False
    assert invented_quote["source_page"] == 1

    other_line = ground_value("Alice", "Nom : FICTIF", index)
    assert other_line["grounding"] == ATTESTED and other_line["quote_verified"] is True


def test_reformulation_backed_by_a_real_quote_is_inferred(index):
    result = ground_value("Patiente en bonne santé générale", "Nom : FICTIF", index)
    assert result["grounding"] == INFERRED
    assert result["source_document"] == "01_fiche.pdf"


def test_invented_value_and_quote_are_unverified(index):
    result = ground_value("MARTIN", "Nom : MARTIN", index)
    assert result == {"quote_verified": False, "grounding": UNVERIFIED}


def test_one_letter_values_cannot_be_checked(index):
    assert ground_value("F", "Prénom : Alice", index)["grounding"] == NOT_CHECKABLE
    assert ground_value("F", "", index)["grounding"] == UNVERIFIED


def test_chosen_answers_rely_on_the_quote_only(index):
    # « NE » figure dans bien des mots : seule la citation compte.
    assert ground_value("NE", "Nom : FICTIF", index, literal=False)["grounding"] == INFERRED
    assert ground_value("oui", "citation inventée de toutes pièces", index,
                        literal=False)["grounding"] == UNVERIFIED


def test_a_recomposed_quote_caps_the_verdict(index):
    # Seule la moitié « Nom : FICTIF » existe : la citation n'est pas reprise telle quelle.
    quote = "Nom : FICTIF; Adresse : Rue Imaginaire 99"
    result = ground_value("FICTIF", quote, index)
    assert result["quote_verified"] is True and result["grounding"] == ATTESTED

    # Le numéro de rue inventé ne devient pas « vérifié » grâce à la moitié réelle.
    street = ground_value("Rue Imaginaire 99", quote, index)
    assert street["grounding"] == INFERRED


def test_too_short_quote_is_ignored(index):
    result = ground_value("FICTIF", "Nom", index)
    assert result["quote_verified"] is False and result["grounding"] == ATTESTED


def test_the_synthesis_never_verifies_a_value():
    synthesis = {"filename": "synthèse médicale", "markdown": "Diagnostic : entorse fictive", "derived": True}
    only_synthesis = SourceIndex([{"filename": "a.pdf", "markdown": "Consultation fictive."}], [synthesis])
    result = ground_value("entorse fictive", "Diagnostic : entorse fictive", only_synthesis)
    assert result["grounding"] == INFERRED and result["source_document"] == "synthèse médicale"

    # Le même texte dans un vrai document l'emporte sur la synthèse.
    both = SourceIndex([{"filename": "a.pdf", "markdown": "Diagnostic : entorse fictive"}], [synthesis])
    result = ground_value("entorse fictive", "Diagnostic : entorse fictive", both)
    assert result["grounding"] == VERIFIED and result["source_document"] == "a.pdf"
