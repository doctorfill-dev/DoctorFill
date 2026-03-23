"""
core/acroform.py — Détection, lecture et remplissage de formulaires AcroForm.

Gère trois cas :
- XFA pur         : délégué aux modules extract/fill/inject existants
- AcroForm pur    : remplissage via pikepdf (champs /Fields)
- Hybride XFA+AcroForm : priorité XFA, fallback AcroForm pour les champs manquants
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pikepdf
from pypdf import PdfReader

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Détection du type de formulaire
# ---------------------------------------------------------------------------

FormType = str  # "xfa" | "acroform" | "hybrid" | "none"


def detect_form_type(pdf_path: str | Path) -> FormType:
    """
    Détecte le type de formulaire PDF.

    Returns:
        "xfa"      : formulaire XFA pur (pas de /Fields AcroForm utilisables)
        "acroform" : formulaire AcroForm pur (pas de /XFA)
        "hybrid"   : contient à la fois /XFA et des /Fields AcroForm
        "none"     : pas de formulaire interactif
    """
    reader = PdfReader(str(pdf_path))
    try:
        root = reader.trailer["/Root"]
    except Exception:
        return "none"

    if "/AcroForm" not in root:
        return "none"

    acroform = root["/AcroForm"]
    has_xfa = "/XFA" in acroform
    has_fields = "/Fields" in acroform and len(acroform["/Fields"]) > 0

    if has_xfa and has_fields:
        return "hybrid"
    if has_xfa:
        return "xfa"
    if has_fields:
        return "acroform"
    return "none"


# ---------------------------------------------------------------------------
# Lecture des champs AcroForm (pour inspection / debug)
# ---------------------------------------------------------------------------

def _get_field_name(field_obj: pikepdf.Object) -> str | None:
    """Retourne le nom complet d'un champ AcroForm (en remontant les parents)."""
    parts = []
    obj = field_obj
    while True:
        t = obj.get("/T")
        if t is not None:
            parts.append(str(t))
        parent = obj.get("/Parent")
        if parent is None:
            break
        obj = parent.get_object() if hasattr(parent, "get_object") else parent
    parts.reverse()
    return ".".join(parts) if parts else None


def _collect_fields(
    fields_array: pikepdf.Array,
    result: dict[str, Any],
    parent_name: str = "",
) -> None:
    """Parcourt récursivement le tableau /Fields et collecte nom → valeur."""
    for ref in fields_array:
        try:
            obj = ref.get_object() if hasattr(ref, "get_object") else ref
        except Exception:
            continue

        t = obj.get("/T")
        name_part = str(t) if t is not None else ""
        full_name = f"{parent_name}.{name_part}" if parent_name and name_part else (name_part or parent_name)

        # Champ feuille : a une valeur /V
        v = obj.get("/V")
        if v is not None and full_name:
            result[full_name] = str(v)

        # Champ parent : descendre dans /Kids
        kids = obj.get("/Kids")
        if kids is not None:
            _collect_fields(kids, result, full_name)


def extract_acroform_field_names(pdf_path: str | Path) -> dict[str, str]:
    """
    Extrait tous les champs AcroForm avec leurs valeurs actuelles.

    Returns:
        dict de field_name -> valeur courante (str vide si non rempli)
    """
    pdf = pikepdf.open(str(pdf_path))
    try:
        acroform = pdf.Root.get("/AcroForm")
        if acroform is None:
            return {}
        fields = acroform.get("/Fields")
        if fields is None:
            return {}
        result: dict[str, str] = {}
        _collect_fields(fields, result)
        return result
    finally:
        pdf.close()


# ---------------------------------------------------------------------------
# Remplissage AcroForm
# ---------------------------------------------------------------------------

_CHECKBOX_TRUTHY = {"on", "true", "1", "yes", "y", "x", "checked", "oui"}


def _normalize_acroform_value(value: Any, is_checkbox: bool) -> pikepdf.Object:
    """Convertit une valeur Python en objet pikepdf pour /V."""
    if is_checkbox:
        s = str(value).strip().lower() if value is not None else ""
        return pikepdf.Name("/Yes") if s in _CHECKBOX_TRUTHY else pikepdf.Name("/Off")
    if value is None:
        return pikepdf.String("")
    return pikepdf.String(str(value))


def _is_checkbox(field_obj: pikepdf.Object) -> bool:
    """Détecte si un champ est une case à cocher."""
    ft = field_obj.get("/FT")
    if ft is not None and str(ft) == "/Btn":
        ff = field_obj.get("/Ff")
        if ff is not None:
            # Bit 17 = Pushbutton, bit 16 = Radio
            # Si aucun de ces bits → checkbox
            flags = int(ff)
            return not (flags & (1 << 16)) and not (flags & (1 << 15))
    return False


def _fill_fields_recursive(
    fields_array: pikepdf.Array,
    values_by_name: dict[str, str],
    parent_name: str = "",
    filled: set[str] | None = None,
) -> None:
    """Remplit récursivement les champs AcroForm."""
    if filled is None:
        filled = set()

    for ref in fields_array:
        try:
            obj = ref.get_object() if hasattr(ref, "get_object") else ref
        except Exception:
            continue

        t = obj.get("/T")
        name_part = str(t) if t is not None else ""
        full_name = f"{parent_name}.{name_part}" if parent_name and name_part else (name_part or parent_name)

        # Champ feuille : le remplir si on a une valeur pour lui
        if full_name in values_by_name and full_name not in filled:
            value = values_by_name[full_name]
            checkbox = _is_checkbox(obj)
            obj["/V"] = _normalize_acroform_value(value, checkbox)
            # Supprimer l'apparence calculée pour forcer le viewer à la recalculer
            if "/AP" in obj:
                del obj["/AP"]
            filled.add(full_name)
            logger.debug("AcroForm fill: %s = %r", full_name, value)

        # Champ parent : descendre dans /Kids
        kids = obj.get("/Kids")
        if kids is not None:
            _fill_fields_recursive(kids, values_by_name, full_name, filled)


def fill_acroform(
    input_pdf: str | Path,
    values_by_name: dict[str, Any],
    output_pdf: str | Path,
) -> set[str]:
    """
    Remplit les champs AcroForm d'un PDF par nom de champ.

    Args:
        input_pdf: PDF source
        values_by_name: dict field_name -> valeur
        output_pdf: PDF de sortie

    Returns:
        Ensemble des noms de champs effectivement remplis
    """
    pdf = pikepdf.open(str(input_pdf))
    try:
        acroform = pdf.Root.get("/AcroForm")
        if acroform is None:
            raise ValueError("PDF ne contient pas d'AcroForm")

        # Activer NeedAppearances pour que les viewers régénèrent les apparences
        acroform["/NeedAppearances"] = pikepdf.Boolean(True)

        fields = acroform.get("/Fields")
        if fields is None:
            raise ValueError("AcroForm sans /Fields")

        filled: set[str] = set()
        _fill_fields_recursive(fields, {k: v for k, v in values_by_name.items()}, filled=filled)

        output_path = Path(output_pdf)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pdf.save(str(output_path))

        logger.info("AcroForm: %d/%d champs remplis → %s", len(filled), len(values_by_name), output_path)
        return filled

    finally:
        pdf.close()
