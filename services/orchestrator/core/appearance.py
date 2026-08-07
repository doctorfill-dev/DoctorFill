"""
core/appearance.py — Génération des flux d'apparence (/AP) des champs AcroForm.

Pourquoi ce module existe : les widgets des formulaires medForms n'embarquent
aucun /AP. Poser /NeedAppearances et laisser le lecteur régénérer l'apparence
fonctionne dans Acrobat et pdf.js, mais PDFium (Chrome, Edge, Aperçu macOS)
ignore ce drapeau et affiche des champs vides. On construit donc nous-mêmes le
XObject de formulaire de chaque champ rempli, ce qui rend le PDF lisible partout.

Les polices employées (/Helv, /ZaDb) sont celles déjà déclarées dans le
/AcroForm/DR des formulaires medForms.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pikepdf

logger = logging.getLogger(__name__)

# Marge intérieure d'un champ, en points.
PADDING_X = 2.0
PADDING_Y = 2.0

# Bornes de la taille de police en auto-dimensionnement.
MIN_FONT_SIZE = 5.0
MAX_FONT_SIZE = 11.0
DEFAULT_FONT_SIZE = 9.0

# Facteur d'interligne pour les champs multilignes.
LINE_HEIGHT = 1.16

# Largeur moyenne d'un glyphe Helvetica, en fraction de la taille de police.
# Suffisant pour dimensionner et couper le texte sans embarquer les métriques AFM.
AVG_GLYPH_WIDTH = 0.5

_FF_MULTILINE = 1 << 12  # bit 13
_FF_COMB = 1 << 24       # bit 25


def _pdf_escape(text: str) -> bytes:
    """Encode une chaîne pour un littéral PDF `( … )` en WinAnsi."""
    raw = text.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _parse_da(da: str | None) -> tuple[str, float]:
    """Extrait (nom de police, taille) d'une chaîne /DA. Taille 0 = auto."""
    if not da:
        return "Helv", 0.0
    m = re.search(r"/([^\s/]+)\s+([\d.]+)\s+Tf", da)
    if not m:
        return "Helv", 0.0
    try:
        return m.group(1), float(m.group(2))
    except ValueError:
        return m.group(1), 0.0


def _get_da(field_obj: pikepdf.Object, acroform: pikepdf.Object) -> str | None:
    """/DA du champ, sinon celui par défaut de l'AcroForm."""
    for source in (field_obj, acroform):
        da = source.get("/DA")
        if da is not None:
            return str(da)
    return None


def _rect_size(rect: pikepdf.Array) -> tuple[float, float]:
    x0, y0, x1, y1 = (float(v) for v in rect)
    return abs(x1 - x0), abs(y1 - y0)


def _wrap(text: str, max_width: float, font_size: float) -> list[str]:
    """Découpe grossièrement le texte pour tenir dans `max_width`."""
    if font_size <= 0:
        return [text]
    chars_per_line = max(1, int(max_width / (font_size * AVG_GLYPH_WIDTH)))
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for word in paragraph.split(" "):
            candidate = f"{current} {word}".strip()
            if len(candidate) <= chars_per_line or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines


def _autosize(text: str, width: float, height: float, multiline: bool) -> float:
    """Choisit une taille de police qui laisse le texte tenir dans le champ."""
    usable_w = max(1.0, width - 2 * PADDING_X)
    usable_h = max(1.0, height - 2 * PADDING_Y)

    if not multiline:
        by_height = usable_h * 0.72
        by_width = usable_w / (max(1, len(text)) * AVG_GLYPH_WIDTH)
        return max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, by_height, by_width))

    size = MAX_FONT_SIZE
    while size > MIN_FONT_SIZE:
        lines = _wrap(text, usable_w, size)
        if len(lines) * size * LINE_HEIGHT <= usable_h:
            break
        size -= 0.5
    return max(MIN_FONT_SIZE, size)


def _make_xobject(pdf: pikepdf.Pdf, width: float, height: float,
                  content: bytes, resources: pikepdf.Object) -> pikepdf.Object:
    """Crée le Form XObject d'une apparence."""
    stream = pikepdf.Stream(pdf, content)
    stream["/Type"] = pikepdf.Name("/XObject")
    stream["/Subtype"] = pikepdf.Name("/Form")
    stream["/BBox"] = pikepdf.Array([0, 0, width, height])
    stream["/Resources"] = resources
    return stream


def _text_appearance(pdf: pikepdf.Pdf, value: str, width: float, height: float,
                     font_name: str, font_size: float, multiline: bool,
                     quadding: int, resources: pikepdf.Object) -> pikepdf.Object:
    """Apparence d'un champ texte (mono- ou multiligne)."""
    if font_size <= 0:
        font_size = _autosize(value, width, height, multiline)

    usable_w = max(1.0, width - 2 * PADDING_X)
    lines = _wrap(value, usable_w, font_size) if multiline else [value.replace("\n", " ")]

    if multiline:
        start_y = height - PADDING_Y - font_size
    else:
        # Centrage vertical approché sur la hauteur de capitale d'Helvetica.
        start_y = (height - font_size * 0.72) / 2.0

    body = bytearray()
    for i, line in enumerate(lines):
        if quadding in (1, 2):
            line_w = len(line) * font_size * AVG_GLYPH_WIDTH
            free = max(0.0, usable_w - line_w)
            x = PADDING_X + (free / 2.0 if quadding == 1 else free)
        else:
            x = PADDING_X
        y = start_y - i * font_size * LINE_HEIGHT
        if y < -font_size:
            break
        body += b"1 0 0 1 %.2f %.2f Tm (%s) Tj\n" % (x, y, _pdf_escape(line))

    content = (
        b"/Tx BMC\nq\nBT\n/%s %.2f Tf\n0 g\n%s ET\nQ\nEMC\n"
        % (_pdf_escape(font_name), font_size, bytes(body))
    )
    return _make_xobject(pdf, width, height, content, resources)


def _checkbox_appearance(pdf: pikepdf.Pdf, width: float, height: float,
                         resources: pikepdf.Object) -> pikepdf.Object:
    """Apparence « cochée » : une coche ZapfDingbats centrée."""
    size = max(MIN_FONT_SIZE, min(width, height) * 0.8)
    x = (width - size * 0.78) / 2.0
    y = (height - size * 0.72) / 2.0
    content = (
        b"/Tx BMC\nq\nBT\n/ZaDb %.2f Tf\n0 g\n1 0 0 1 %.2f %.2f Tm (4) Tj\nET\nQ\nEMC\n"
        % (size, x, y)
    )
    return _make_xobject(pdf, width, height, content, resources)


def _off_appearance(pdf: pikepdf.Pdf, width: float, height: float,
                    resources: pikepdf.Object) -> pikepdf.Object:
    """Apparence « décochée » : vide, mais présente pour que le lecteur ait les deux états."""
    return _make_xobject(pdf, width, height, b"/Tx BMC\nEMC\n", resources)


def _widgets_of(field_obj: pikepdf.Object) -> list[pikepdf.Object]:
    """
    Retourne les annotations widget d'un champ.

    Un champ peut être fusionné avec son unique widget (il porte alors /Rect),
    ou déléguer à des /Kids.
    """
    if field_obj.get("/Rect") is not None:
        return [field_obj]
    kids = field_obj.get("/Kids")
    if kids is None:
        return []
    widgets = []
    for kid in kids:
        obj = kid.get_object() if hasattr(kid, "get_object") else kid
        if obj.get("/Rect") is not None:
            widgets.append(obj)
    return widgets


def build_appearance(pdf: pikepdf.Pdf, acroform: pikepdf.Object,
                     field_obj: pikepdf.Object, value: Any,
                     on_state: pikepdf.Name | None) -> bool:
    """
    Construit et attache le /AP des widgets d'un champ rempli.

    Args:
        on_state: pour une case à cocher, le nom de l'état coché ; None pour un champ texte.

    Returns:
        True si au moins une apparence a été écrite.
    """
    resources = acroform.get("/DR")
    if resources is None:
        logger.warning("AcroForm sans /DR — apparences non générées")
        return False

    widgets = _widgets_of(field_obj)
    if not widgets:
        return False

    da = _get_da(field_obj, acroform)
    font_name, font_size = _parse_da(da)
    flags = int(field_obj.get("/Ff") or 0)
    multiline = bool(flags & _FF_MULTILINE)
    quadding = int(field_obj.get("/Q") or 0)

    written = False
    for widget in widgets:
        try:
            width, height = _rect_size(widget["/Rect"])
        except Exception:
            continue
        if width <= 0 or height <= 0:
            continue

        if on_state is not None:
            checked = str(field_obj.get("/V") or "/Off") == str(on_state)
            existing = widget.get("/AP")
            has_on_state = (
                existing is not None
                and existing.get("/N") is not None
                and str(on_state) in existing["/N"].keys()
            )
            if not has_on_state:
                # Aucune apparence fournie par le formulaire : on dessine la coche.
                widget["/AP"] = pdf.make_indirect(pikepdf.Dictionary(N=pikepdf.Dictionary()))
                widget["/AP"]["/N"][str(on_state)] = _checkbox_appearance(pdf, width, height, resources)
                widget["/AP"]["/N"]["/Off"] = _off_appearance(pdf, width, height, resources)
            # /AS désigne l'état affiché ; sans lui le lecteur retombe sur /Off.
            widget["/AS"] = on_state if checked else pikepdf.Name("/Off")
        else:
            text = "" if value is None else str(value)
            if not text:
                continue
            widget["/AP"] = pdf.make_indirect(pikepdf.Dictionary(
                N=_text_appearance(pdf, text, width, height, font_name,
                                   font_size, multiline, quadding, resources)
            ))
        written = True

    return written
