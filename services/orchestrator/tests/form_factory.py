"""
PDF hybrides XFA + AcroForm construits à partir d'un template du catalogue.

Les PDF medForms ne sont pas versionnés. Pour vérifier en CI que chaque champ de
chaque formulaire atteint le PDF, on reconstruit un formulaire de même structure :

- couche AcroForm : arbre de champs issu des `acroform_name` (y compris les noms
  échappés « Block_2\\.1 » et les nœuds « #area[0] », scindés comme le fait le
  producteur des vrais PDF) ; case à cocher pour `bool`, groupe radio pour un
  `choice` à valeurs d'export, liste déroulante pour les autres `choice` ;
- couche XFA : packet `datasets` avec un nœud par `xml_path`, frères indexés
  compris (`phone[1]`, `unemployabilityS1Struct[2]`).

Le remplissage passe ensuite par le code de production (`_fill_pdf`) : détection
« hybrid », injection XFA puis AcroForm.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name, String

from core.extract import extract_xfa_packets
from core.fill import _find

_FF_RADIO = 1 << 15
_FF_NO_TOGGLE_OFF = 1 << 14
_FF_COMBO = 1 << 17
_XFA_DATA_NS = "http://www.xfa.org/schema/xfa-data/1.0/"
_SEGMENT = re.compile(r"^(.*?)(?:\[(\d+)\])?$")


def widget_kind(field: dict) -> str:
    """Type de widget AcroForm qu'un champ du template reçoit dans le PDF de test."""
    kind = field.get("type")
    options, values = field.get("options") or [], field.get("option_values") or []
    if kind == "bool":
        return "checkbox" if options else "checkbox_ap"
    if kind == "choice" and options and len(values) == len(options):
        return "radio"
    if kind == "choice" and options:
        return "combo"
    return "text"


def _state_stream(pdf: pikepdf.Pdf) -> pikepdf.Stream:
    return pikepdf.Stream(pdf, b"q Q")


def _datasets_xml(fields: list[dict]) -> bytes:
    ET.register_namespace("xfa", _XFA_DATA_NS)
    root = ET.Element(f"{{{_XFA_DATA_NS}}}datasets")
    data = ET.SubElement(root, f"{{{_XFA_DATA_NS}}}data")
    for field in fields:
        node = data
        for segment in [s for s in field["xml_path"].split("/") if s]:
            tag, index = _SEGMENT.match(segment).groups()
            index = int(index or 0)
            siblings = [c for c in node if c.tag == tag]
            while len(siblings) <= index:
                siblings.append(ET.SubElement(node, tag))
            node = siblings[index]
        if field.get("type") == "bool" and (field.get("options") or [None])[-1] == "Off":
            node.text = "Off"
    return ET.tostring(root, encoding="utf-8")


def build_hybrid_form(template: dict, path: Path) -> Path:
    """Écrit le formulaire de test d'un template et le retourne."""
    fields = [f for f in template["fields"] if "id" in f and f.get("acroform_name")]
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    page = pdf.pages[0]
    helv = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1,
                                        BaseFont=Name.Helvetica, Encoding=Name.WinAnsiEncoding))
    zadb = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.ZapfDingbats))

    top: list = []
    nodes: dict[str, pikepdf.Object] = {}
    annots: list = []

    def container(parts: list[str]) -> pikepdf.Object | None:
        """Nœud intermédiaire pour le chemin `parts`, créé au besoin."""
        if not parts:
            return None
        key = ".".join(parts)
        if key not in nodes:
            parent = container(parts[:-1])
            node = pdf.make_indirect(Dictionary(T=String(parts[-1]), Kids=Array()))
            if parent is None:
                top.append(node)
            else:
                node.Parent = parent
                parent.Kids.append(node)
            nodes[key] = node
        return nodes[key]

    def widget(**entries) -> pikepdf.Object:
        obj = pdf.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Widget,
                                           Rect=Array([40, 40, 300, 58]), P=page.obj, **entries))
        annots.append(obj)
        return obj

    for field in fields:
        parts = field["acroform_name"].split(".")
        parent = container(parts[:-1])
        kind = widget_kind(field)
        if kind == "radio":
            leaf = pdf.make_indirect(Dictionary(T=String(parts[-1]), FT=Name.Btn,
                                                Ff=_FF_RADIO | _FF_NO_TOGGLE_OFF, Kids=Array()))
            for value in field["option_values"]:
                kid = widget(AS=Name.Off, Parent=leaf, AP=Dictionary(N=Dictionary({
                    f"/{value}": _state_stream(pdf), "/Off": _state_stream(pdf)})))
                leaf.Kids.append(kid)
        elif kind == "checkbox":
            leaf = widget(T=String(parts[-1]), FT=Name.Btn, V=Name.Off, AS=Name.Off)
        elif kind == "checkbox_ap":
            # Case dessinée par Designer, état coché « /1 » (AI_ReadaptationRente).
            leaf = widget(T=String(parts[-1]), FT=Name.Btn, AS=Name.Off,
                          AP=Dictionary(N=Dictionary({"/1": _state_stream(pdf), "/Off": _state_stream(pdf)})))
        elif kind == "combo":
            leaf = widget(T=String(parts[-1]), FT=Name.Ch, Ff=_FF_COMBO, DA=String("/Helv 0 Tf 0 g"),
                          Opt=Array([String(o) for o in field["options"]]))
        else:
            leaf = widget(T=String(parts[-1]), FT=Name.Tx, DA=String("/Helv 0 Tf 0 g"))
        if parent is None:
            top.append(leaf)
        else:
            leaf.Parent = parent
            parent.Kids.append(leaf)

    datasets = pdf.make_stream(_datasets_xml(fields))
    page.obj.Annots = Array(annots)
    pdf.Root.AcroForm = Dictionary(Fields=Array(top), DA=String("/Helv 0 Tf 0 g"),
                                   DR=Dictionary(Font=Dictionary(Helv=helv, ZaDb=zadb)),
                                   XFA=Array([String("datasets"), datasets]))
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(str(path))
    return path


# ---------------------------------------------------------------------------
# Relecture
# ---------------------------------------------------------------------------

def read_acroform(path: Path) -> dict[str, str | None]:
    """Nom complet → /V (texte, ou nom d'état pour un bouton) de chaque champ terminal."""
    values: dict[str, str | None] = {}

    def walk(objs, prefix: str) -> None:
        for obj in objs:
            t = obj.get("/T")
            name = f"{prefix}.{t}" if prefix and t is not None else (str(t) if t is not None else prefix)
            if obj.get("/FT") is not None:
                v = obj.get("/V")
                values[name] = str(v) if v is not None else None
                continue
            if obj.get("/Kids") is not None:
                walk(obj.Kids, name)

    with pikepdf.open(str(path)) as pdf:
        walk(pdf.Root.AcroForm.Fields, "")
    return values


def read_datasets(path: Path, xml_paths: list[str]) -> dict[str, str | None]:
    """xml_path → texte du nœud dans le packet datasets du PDF rempli."""
    import defusedxml.ElementTree as DET

    root = DET.fromstring(extract_xfa_packets(path)["datasets"].encode("utf-8"))
    out = {}
    for xml_path in xml_paths:
        node = _find(root, xml_path)
        out[xml_path] = None if node is None else (node.text or "")
    return out
