"""
Validation champ par champ avant toute sortie du PDF (issue 37, audit S15).

Le modèle propose, le médecin dispose. Tant qu'un médecin identifié n'a pas
validé le formulaire, seul un aperçu marqué « NON VALIDÉ » sur chaque page
peut sortir de DoctorFill.

- Un champ **à confirmer** : valeur non tracée (`unverified`), déduite
  (`inferred`), sans verdict, ou champ en erreur. La validation est refusée
  tant qu'il en reste un qui n'est ni confirmé, ni corrigé, ni vidé.
- Une correction garde la valeur du modèle (`model_value`, posée à la
  première correction) à côté de celle du médecin (`value`). Les champs de
  provenance (citation, document, page, verdict) restent ceux du modèle : ils
  décrivent `model_value`, pas la valeur saisie.
- Chaque décision porte `review` : action, utilisateur, horodatage. Le
  journal d'audit reçoit les mêmes faits, sans la valeur.

Ce module n'appelle pas le modèle et n'accède pas au réseau : fonctions sur
les résultats d'extraction, plus le filigrane de l'aperçu (pikepdf).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pikepdf
from pikepdf import Dictionary, Name

from core.fields import normalize_value

AWAITING = "awaiting_validation"
VALIDATED = "validated"

ACTIONS = ("confirm", "edit", "clear")

# Verdicts de provenance qui exigent l'accord explicite du médecin. Un champ en
# erreur en exige un aussi (needs_review). `attested` et `not_checkable` n'y
# sont pas, selon l'issue 37 : les ajouter ici si la relecture clinique le demande.
NEEDS_REVIEW_GROUNDINGS = frozenset({"unverified", "inferred"})

MAX_VALUE_CHARS = 2000
MAX_CORRECTIONS = 500

PREVIEW_MARK = "NON VALIDÉ"
PREVIEW_BANNER = "APERÇU NON VALIDÉ — ne pas transmettre"


class CorrectionError(ValueError):
    """Correction refusée ; le message peut être montré à l'utilisateur (il ne cite aucune valeur)."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_state() -> dict[str, Any]:
    """État d'un job dont les valeurs viennent de changer : à valider."""
    return {"state": AWAITING, "validated_by": None, "validated_at": None}


def state_of(job: dict) -> dict[str, Any]:
    """État de validation d'un job ; un job sans état (antérieur à l'issue 37) n'est pas validé."""
    return job.get("validation") or new_state()


def is_validated(job: dict) -> bool:
    return state_of(job).get("state") == VALIDATED


def needs_review(result: dict) -> bool:
    """Le champ doit être confirmé, corrigé ou vidé avant la validation."""
    if not result or result.get("review"):
        return False
    if "error" in result:
        return True
    payload = result.get("result")
    if not isinstance(payload, dict) or not str(payload.get("value") or "").strip():
        return False
    grounding = payload.get("grounding")
    return grounding is None or grounding in NEEDS_REVIEW_GROUNDINGS


def pending_fields(results: list[dict]) -> list[str]:
    """Identifiants des champs qui attendent encore le médecin, dans l'ordre du formulaire."""
    return [str(r.get("id")) for r in results if needs_review(r)]


def _checked_value(value: str | None, field: dict) -> str:
    """Valeur saisie, normalisée comme celles du modèle (normalize_value)."""
    if value is None:
        raise CorrectionError("Une correction doit porter une valeur.")
    if len(value) > MAX_VALUE_CHARS:
        raise CorrectionError(f"Valeur trop longue (max {MAX_VALUE_CHARS} caractères).")
    normalized = normalize_value(value, field)
    kind = field.get("type")
    if kind == "bool" and value.strip() and not normalized:
        raise CorrectionError("Réponse attendue : oui ou non.")
    options = field.get("options") or []
    if kind == "choice" and normalized and options and normalized not in options:
        raise CorrectionError("Valeur hors des options du formulaire.")
    return normalized


def apply_correction(result: dict, field: dict, action: str, value: str | None,
                     user_id: str, at: str | None = None) -> None:
    """
    Applique une décision du médecin à un résultat d'extraction (modifié en place).

    confirm : la valeur actuelle est juste (ou le champ reste vide) ;
    edit : la valeur devient `value`, normalisée ;
    clear : le champ est vidé.
    """
    if action not in ACTIONS:
        raise CorrectionError("Action inconnue (confirm, edit ou clear).")
    if action in ("edit", "clear"):
        new_value = "" if action == "clear" else _checked_value(value, field)
        payload = result.get("result")
        if not isinstance(payload, dict):
            # Champ en erreur : le modèle n'avait rien rendu.
            payload = result["result"] = {"value": "", "source_quote": ""}
        payload.setdefault("model_value", str(payload.get("value") or ""))
        payload["value"] = new_value
    result["review"] = {"action": action, "user_id": user_id, "at": at or now_iso()}


def watermark_preview(src: Path, dst: Path) -> Path:
    """
    Copie `src` vers `dst` en marquant chaque page « NON VALIDÉ ».

    Le marquage est dessiné dans le contenu de chaque page (texte en contour
    sur la diagonale, bandeau en haut) et repris dans le titre du document.
    Limite connue : un lecteur qui affiche le formulaire XFA plutôt que les
    pages PDF (Acrobat, formulaires dynamiques) peut ne pas montrer le
    filigrane ; le nom du fichier et le titre le disent quand même.
    """
    with pikepdf.open(src) as pdf:
        font = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1,
                                            BaseFont=Name.Helvetica, Encoding=Name.WinAnsiEncoding))
        mark = PREVIEW_MARK.encode("cp1252")
        banner = PREVIEW_BANNER.encode("cp1252")
        for page in pdf.pages:
            res_name = str(page.add_resource(font, Name.Font, prefix="DFPreview")).lstrip("/").encode("ascii")
            x0, y0, x1, y1 = (float(v) for v in page.mediabox)
            width, height = x1 - x0, y1 - y0
            size = max(24.0, min(width, height) / 9)
            overlay = b"".join([
                b"Q\nq\n0.85 0.1 0.1 RG 0.85 0.1 0.1 rg 1.5 w\n",
                # Diagonale en contour (1 Tr) : les valeurs restent lisibles dessous.
                b"BT /%s %.1f Tf 1 Tr 0.7071 0.7071 -0.7071 0.7071 %.1f %.1f Tm (%s) Tj ET\n"
                % (res_name, size, x0 + width * 0.18, y0 + height * 0.30, mark),
                b"BT /%s 10 Tf 0 Tr 1 0 0 1 %.1f %.1f Tm (%s) Tj ET\n"
                % (res_name, x0 + 24, y1 - 18, banner),
                b"Q\n",
            ])
            # Le contenu d'origine est isolé (q … Q) : son état graphique ne
            # déplace ni ne masque le marquage.
            page.contents_add(pdf.make_stream(b"q\n"), prepend=True)
            page.contents_add(pdf.make_stream(overlay))
        pdf.docinfo["/Title"] = "DoctorFill - aperçu NON VALIDÉ"
        pdf.save(dst)
    return dst
