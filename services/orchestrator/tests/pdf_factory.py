"""
Fabrique de formulaires PDF minimaux pour les tests.

Les PDF medForms ne sont pas versionnés (voir .gitignore) : on construit un
AcroForm équivalent — champs texte, case à cocher sans /AP comme chez medForms,
liste de choix à options [export, libellé] — avec pikepdf.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name, String

_FF_COMBO = 1 << 17


def make_acroform(path: Path, fields: list[tuple[str, str, dict]]) -> Path:
    """
    Args:
        fields: (nom, type, options) avec type ∈ {"text", "checkbox", "combo"} ;
            pour "combo", options["opt"] liste des paires (export, libellé).
    """
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    page = pdf.pages[0]
    helv = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1,
                                        BaseFont=Name.Helvetica, Encoding=Name.WinAnsiEncoding))
    zadb = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.ZapfDingbats))

    widgets = []
    y = 800
    for name, kind, options in fields:
        widget = Dictionary(Type=Name.Annot, Subtype=Name.Widget, T=String(name),
                            Rect=Array([50, y - 18, 400, y]), P=page.obj,
                            DA=String("/Helv 0 Tf 0 g"))
        if kind == "text":
            widget.FT = Name.Tx
        elif kind == "checkbox":
            widget.FT = Name.Btn
            widget.V = Name.Off
            widget.AS = Name.Off
        elif kind == "combo":
            widget.FT = Name.Ch
            widget.Ff = _FF_COMBO
            widget.Opt = Array([Array([String(e), String(d)]) for e, d in options["opt"]])
        widgets.append(pdf.make_indirect(widget))
        y -= 30

    page.obj.Annots = Array(widgets)
    pdf.Root.AcroForm = Dictionary(Fields=Array(widgets), DR=Dictionary(Font=Dictionary(Helv=helv, ZaDb=zadb)),
                                   DA=String("/Helv 0 Tf 0 g"))
    pdf.save(str(path))
    return path


def read_fields(path: Path) -> dict[str, dict]:
    """Nom → {V, AS, has_ap, ap_text} de chaque champ d'un PDF rempli."""
    out = {}
    with pikepdf.open(str(path)) as pdf:
        for field in pdf.Root.AcroForm.Fields:
            ap = field.get("/AP")
            ap_text = ""
            if ap is not None and isinstance(ap.get("/N"), pikepdf.Stream):
                ap_text = ap.N.read_bytes().decode("latin-1")
            out[str(field.T)] = {
                "V": str(field.get("/V")) if field.get("/V") is not None else None,
                "AS": str(field.get("/AS")) if field.get("/AS") is not None else None,
                "has_ap": ap is not None,
                "ap_text": ap_text,
            }
    return out
