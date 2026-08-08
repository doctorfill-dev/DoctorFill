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

from core.appearance import build_appearance

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

        # Champ terminal : /FT le désigne comme un vrai champ de formulaire.
        # On l'enregistre même sans /V — un formulaire vierge n'en a pas, et les
        # omettre rendait invisibles tous les champs à remplir.
        v = obj.get("/V")
        if full_name and (obj.get("/FT") is not None or v is not None):
            result[full_name] = str(v) if v is not None else ""

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

# Drapeaux /Ff, numérotés à partir de 1 dans la spec PDF.
_FF_RADIO = 1 << 15        # bit 16
_FF_PUSHBUTTON = 1 << 16   # bit 17


def _checkbox_on_state(field_obj: pikepdf.Object) -> pikepdf.Name:
    """
    Détermine le nom de l'état « coché » d'une case.

    Les widgets medForms n'ont pas de /AP, donc on ne peut pas lire l'état depuis
    les apparences. On tente /AP puis /Opt, et on retombe sur /On — la convention
    des formulaires générés par Designer — plutôt que sur /Yes.
    """
    ap = field_obj.get("/AP")
    if ap is not None:
        normal = ap.get("/N")
        if normal is not None:
            for key in normal.keys():
                if key != "/Off":
                    return pikepdf.Name(key)
    return pikepdf.Name("/On")


def _normalize_acroform_value(value: Any, on_state: pikepdf.Name | None) -> pikepdf.Object:
    """Convertit une valeur Python en objet pikepdf pour /V."""
    if on_state is not None:
        s = str(value).strip().lower() if value is not None else ""
        return on_state if s in _CHECKBOX_TRUTHY else pikepdf.Name("/Off")
    if value is None:
        return pikepdf.String("")
    return pikepdf.String(str(value))


def _is_checkbox(field_obj: pikepdf.Object) -> bool:
    """
    Détecte si un champ est une case à cocher.

    /Ff est absent sur la grande majorité des cases medForms (une case n'a aucun
    drapeau à poser) : son absence signifie donc « ni radio ni pushbutton », pas
    « pas une case ». Traiter l'absence comme un échec écrivait une chaîne dans
    un champ qui attend un /Name.
    """
    ft = field_obj.get("/FT")
    if ft is None or str(ft) != "/Btn":
        return False
    ff = field_obj.get("/Ff")
    if ff is None:
        return True
    flags = int(ff)
    return not (flags & _FF_PUSHBUTTON) and not (flags & _FF_RADIO)


def _is_radio(field_obj: pikepdf.Object) -> bool:
    """Détecte un groupe de boutons radio (bouton portant le drapeau /Radio)."""
    ft = field_obj.get("/FT")
    if ft is None or str(ft) != "/Btn":
        return False
    return bool(int(field_obj.get("/Ff") or 0) & _FF_RADIO)


def _radio_states(field_obj: pikepdf.Object) -> dict[str, pikepdf.Object]:
    """État « coché » → widget correspondant, pour chaque bouton du groupe."""
    states: dict[str, pikepdf.Object] = {}
    for kid in (field_obj.get("/Kids") or []):
        obj = kid.get_object() if hasattr(kid, "get_object") else kid
        ap = obj.get("/AP")
        normal = ap.get("/N") if ap is not None else None
        if normal is None:
            continue
        for key in normal.keys():
            if key != "/Off":
                states[key] = obj
                break
    return states


def _fill_radio(field_obj: pikepdf.Object, value: Any) -> bool:
    """
    Coche le bouton dont l'état correspond à `value`.

    Un groupe radio n'accepte qu'un /Name choisi parmi les états de ses boutons
    (medForms exporte « 0 », « 1 », …). Y écrire une chaîne peignait le libellé
    brut dans chacun des boutons, qui apparaissaient tous cochés.

    Returns:
        True si un bouton correspond, False si la valeur est hors du groupe.
    """
    states = _radio_states(field_obj)
    wanted = f"/{str(value).strip()}"
    if wanted not in states:
        return False
    field_obj["/V"] = pikepdf.Name(wanted)
    for state, widget in states.items():
        widget["/AS"] = pikepdf.Name(state if state == wanted else "/Off")
    return True


def _fill_fields_recursive(
    pdf: pikepdf.Pdf,
    acroform: pikepdf.Object,
    fields_array: pikepdf.Array,
    values_by_name: dict[str, str],
    parent_name: str = "",
    filled: set[str] | None = None,
) -> None:
    """Remplit récursivement les champs AcroForm et génère leurs apparences."""
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

        # Un groupe radio se remplit d'un bloc : ses boutons sont des widgets, pas
        # des champs, et n'ont pas de /T. Descendre dedans leur ferait hériter du
        # nom du parent et les remplirait un à un comme des champs texte.
        if _is_radio(obj):
            if full_name in values_by_name and full_name not in filled:
                value = values_by_name[full_name]
                if _fill_radio(obj, value):
                    filled.add(full_name)
                    logger.debug("AcroForm fill: %s = %r", full_name, value)
                else:
                    logger.debug("Radio %s : %r hors des états du groupe", full_name, value)
            continue

        # Champ feuille : le remplir si on a une valeur pour lui
        if full_name in values_by_name and full_name not in filled:
            value = values_by_name[full_name]
            on_state = _checkbox_on_state(obj) if _is_checkbox(obj) else None
            obj["/V"] = _normalize_acroform_value(value, on_state)
            # On construit l'apparence nous-mêmes : PDFium n'honore pas /NeedAppearances.
            try:
                build_appearance(pdf, acroform, obj, value, on_state)
            except Exception as exc:
                logger.warning("Apparence non générée pour %s : %s", full_name, exc)
            filled.add(full_name)
            logger.debug("AcroForm fill: %s = %r", full_name, value)

        # Champ parent : descendre dans /Kids
        kids = obj.get("/Kids")
        if kids is not None:
            _fill_fields_recursive(pdf, acroform, kids, values_by_name, full_name, filled)


def _strip_usage_rights(pdf: pikepdf.Pdf) -> None:
    """
    Retire la signature de droits d'usage étendus (/Perms/UR3).

    Les formulaires medForms sont Reader-extended : toute réécriture invalide
    cette signature et Acrobat affiche un bandeau d'avertissement. Comme on ne
    peut pas la conserver valide, autant la supprimer proprement.
    """
    perms = pdf.Root.get("/Perms")
    if perms is not None and "/UR3" in perms:
        del perms["/UR3"]
        if len(perms.keys()) == 0:
            del pdf.Root["/Perms"]
        logger.debug("Signature UR3 retirée (invalidée par le remplissage)")


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
    # allow_overwriting_input : en hybride, input_pdf et output_pdf sont le même
    # fichier (sortie de l'injection XFA reprise comme source)
    pdf = pikepdf.open(str(input_pdf), allow_overwriting_input=True)
    try:
        acroform = pdf.Root.get("/AcroForm")
        if acroform is None:
            raise ValueError("PDF ne contient pas d'AcroForm")

        # On génère les apparences nous-mêmes (voir core/appearance.py), donc on
        # désactive NeedAppearances : le laisser actif pousse les lecteurs à
        # redessiner *tous* les champs, y compris ceux qu'on n'a pas touchés, ce
        # qui décale la typographie d'origine du formulaire.
        acroform["/NeedAppearances"] = pikepdf.Boolean(False)

        fields = acroform.get("/Fields")
        if fields is None:
            raise ValueError("AcroForm sans /Fields")

        filled: set[str] = set()
        _fill_fields_recursive(pdf, acroform, fields,
                               {k: v for k, v in values_by_name.items()}, filled=filled)

        _strip_usage_rights(pdf)

        output_path = Path(output_pdf)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pdf.save(str(output_path))

        logger.info("AcroForm: %d/%d champs remplis → %s", len(filled), len(values_by_name), output_path)
        return filled

    finally:
        pdf.close()
