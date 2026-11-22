"""
Lecture et écriture des formulaires PDF : détection, packets XFA, cases à cocher,
injection, et les replis de _fill_pdf.

Les PDF sont construits ici avec pikepdf (les formulaires medForms ne sont pas
versionnés). Les valeurs écrites sont fictives.
"""

from __future__ import annotations

import defusedxml
import pikepdf
import pytest
from pikepdf import Array, Dictionary, String

import app as orchestrator
from core.acroform import detect_form_type, extract_acroform_field_names, fill_acroform
from core.checkbox import discover_checkbox_paths, normalize_checkboxes
from core.extract import PDFNoXFAError, extract_xfa_datasets, extract_xfa_packets
from core.fill import update_datasets
from core.inject import _remove_xml_declaration, inject_datasets
from tests.pdf_factory import make_acroform, read_fields

XFA_NS = "http://www.xfa.org/schema/xfa-data/1.0/"
DATASETS = (f'<xfa:datasets xmlns:xfa="{XFA_NS}"><xfa:data><form1>'
            "<lastName/><urgent>Off</urgent><visits/>"
            "</form1></xfa:data></xfa:datasets>").encode("utf-8")


def make_xfa_pdf(path, datasets: bytes = DATASETS, *, with_datasets: bool = True,
                 xfa_as_stream: bool = False):
    """Formulaire XFA pur : /XFA sans champs AcroForm."""
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    template = pdf.make_stream(b"<template/>")
    if xfa_as_stream:
        xfa = pdf.make_stream(datasets)
    elif with_datasets:
        xfa = Array([String("template"), template, String("datasets"), pdf.make_stream(datasets)])
    else:
        xfa = Array([String("template"), template])
    pdf.Root.AcroForm = Dictionary(Fields=Array(), XFA=xfa)
    pdf.save(str(path))
    return path


def make_plain_pdf(path, acroform: bool = False):
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    if acroform:
        pdf.Root.AcroForm = Dictionary(Fields=Array())
    pdf.save(str(path))
    return path


def add_xfa_stream(path):
    """Ajoute un /XFA en flux unique (et non en packets) à un AcroForm existant."""
    with pikepdf.open(str(path), allow_overwriting_input=True) as pdf:
        pdf.Root.AcroForm.XFA = pdf.make_stream(b"<xdp/>")
        pdf.save(str(path))
    return path


# --- Détection -------------------------------------------------------------------------

def test_detect_form_type(tmp_path):
    assert detect_form_type(make_plain_pdf(tmp_path / "plain.pdf")) == "none"
    assert detect_form_type(make_plain_pdf(tmp_path / "empty.pdf", acroform=True)) == "none"
    assert detect_form_type(make_xfa_pdf(tmp_path / "xfa.pdf")) == "xfa"
    acro = make_acroform(tmp_path / "acro.pdf", [("lastName", "text", {})])
    assert detect_form_type(acro) == "acroform"
    assert detect_form_type(add_xfa_stream(acro)) == "hybrid"


def test_acroform_field_names_include_blank_fields(tmp_path):
    acro = make_acroform(tmp_path / "acro.pdf", [("lastName", "text", {}), ("urgent", "checkbox", {})])
    assert extract_acroform_field_names(acro) == {"lastName": "", "urgent": "/Off"}
    assert extract_acroform_field_names(make_plain_pdf(tmp_path / "plain.pdf")) == {}


# --- Packets XFA -----------------------------------------------------------------------

def test_xfa_packets_are_read(tmp_path):
    packets = extract_xfa_packets(make_xfa_pdf(tmp_path / "xfa.pdf"))
    assert set(packets) == {"template", "datasets"}
    assert packets["datasets"] == DATASETS.decode("utf-8")


@pytest.mark.parametrize("builder", [
    lambda p: make_plain_pdf(p),
    lambda p: make_acroform(p, [("lastName", "text", {})]),
    lambda p: make_xfa_pdf(p, xfa_as_stream=True),
])
def test_no_usable_xfa_is_reported(tmp_path, builder):
    with pytest.raises(PDFNoXFAError):
        extract_xfa_packets(builder(tmp_path / "form.pdf"))


def test_datasets_are_written_to_disk(tmp_path):
    out = tmp_path / "sous" / "dossier" / "base.xml"
    returned = extract_xfa_datasets(make_xfa_pdf(tmp_path / "xfa.pdf"), out)
    assert returned == str(out)
    assert out.read_bytes() == DATASETS


def test_missing_datasets_packet_is_an_error(tmp_path):
    with pytest.raises(ValueError):
        extract_xfa_datasets(make_xfa_pdf(tmp_path / "xfa.pdf", with_datasets=False), tmp_path / "base.xml")


# --- Injection -------------------------------------------------------------------------

def test_injected_datasets_replace_the_original(tmp_path):
    src = make_xfa_pdf(tmp_path / "xfa.pdf")
    filled = tmp_path / "filled.xml"
    filled.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n'
                       + DATASETS.replace(b"<lastName/>", b"<lastName>FICTIF</lastName>"))
    out = tmp_path / "sortie" / "out.pdf"
    inject_datasets(src, filled, out)
    datasets = extract_xfa_packets(out)["datasets"]
    assert "<lastName>FICTIF</lastName>" in datasets
    assert not datasets.startswith("<?xml")
    # Le packet template n'est pas touché.
    assert extract_xfa_packets(out)["template"] == "<template/>"


@pytest.mark.parametrize("kwargs", [{"with_datasets": False}, {"xfa_as_stream": True}])
def test_injection_without_a_datasets_packet_fails(tmp_path, kwargs):
    src = make_xfa_pdf(tmp_path / "xfa.pdf", **kwargs)
    filled = tmp_path / "filled.xml"
    filled.write_bytes(DATASETS)
    with pytest.raises(ValueError):
        inject_datasets(src, filled, tmp_path / "out.pdf")


@pytest.mark.parametrize("raw, expected", [
    (b'\xef\xbb\xbf<?xml version="1.0"?>\n<a/>', b"<a/>"),
    (b'<?xml version="1.0" encoding="UTF-8"?><a>x</a>', b"<a>x</a>"),
    (b"<a/>", b"<a/>"),
])
def test_xml_declaration_and_bom_are_removed(raw, expected):
    assert _remove_xml_declaration(raw) == expected


# --- Cases à cocher -------------------------------------------------------------------

def test_checkboxes_are_discovered_by_their_on_off_value(tmp_path):
    xml = tmp_path / "base.xml"
    xml.write_text(
        f'<xfa:datasets xmlns:xfa="{XFA_NS}"><xfa:data><form1>'
        "<urgent>Off</urgent><hosp>On</hosp><hosp>Off</hosp><lastName>FICTIF</lastName>"
        "<block><nested>Off</nested></block><empty/>"
        "</form1></xfa:data></xfa:datasets>", encoding="utf-8")
    # Conteneurs XFA ignorés, doublons retirés, ordre du document conservé.
    assert discover_checkbox_paths(xml) == ["form1/urgent", "form1/hosp", "form1/block/nested"]


def test_checkbox_discovery_does_not_resolve_external_entities(tmp_path):
    xml = tmp_path / "base.xml"
    xml.write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE root [<!ENTITY ext SYSTEM "file:///chemin/inexistant/fictif.txt">]>\n'
        "<root><a>&ext;</a><b>On</b></root>", encoding="utf-8")
    assert discover_checkbox_paths(xml) == ["root/b"]


@pytest.mark.parametrize("value, expected", [
    (True, "On"), (False, "Off"), (1, "On"), (0, "Off"), (None, "Off"),
    ("On", "On"), ("Off", "Off"), ("oui", "On"), ("Coché", "On"), ("x", "On"),
    ("non", "Off"), ("", "Off"), ("peut-être", "Off"),
])
def test_checkbox_values_are_normalised(value, expected):
    values = {"form1/cb": value, "form1/text": "FICTIF"}
    normalize_checkboxes(values, ["form1/cb", "form1/absent"])
    assert values == {"form1/cb": expected, "form1/text": "FICTIF"}


# --- Mise à jour des datasets ------------------------------------------------------------

def _datasets_file(tmp_path, body: str):
    path = tmp_path / "base.xml"
    path.write_text(f'<xfa:datasets xmlns:xfa="{XFA_NS}"><xfa:data><form1>{body}'
                    "</form1></xfa:data></xfa:datasets>", encoding="utf-8")
    return path


def test_update_datasets_types_paths_and_overwrite(tmp_path):
    src = _datasets_file(tmp_path, "<lastName>Ancien</lastName><visits/><note/><phone/><phone/>")
    dst = tmp_path / "filled.xml"
    fields = [{"xml_path": "form1/visits", "type": "int"}, {"name": "form1/note", "type": "int"}]
    update_datasets(src, {"form1/lastName": "FICTIF", "form1/visits": "12", "form1/note": "douze",
                          "form1/phone[1]": "000 000 00 00", "form1/absent": "ignoré"}, dst, fields)
    xml = dst.read_text(encoding="utf-8")
    assert "<lastName>FICTIF</lastName>" in xml
    assert "<visits>12</visits>" in xml
    assert "<note>douze</note>" in xml          # « int » illisible : gardé tel quel
    assert "<phone>000 000 00 00</phone>" in xml
    assert "absent" not in xml and "ignoré" not in xml

    kept = tmp_path / "kept.xml"
    update_datasets(src, {"form1/lastName": "FICTIF", "form1/note": "x"}, kept, overwrite=False)
    xml = kept.read_text(encoding="utf-8")
    assert "<lastName>Ancien</lastName>" in xml and "<note>x</note>" in xml


def test_update_datasets_refuses_entity_declarations(tmp_path):
    src = tmp_path / "bomb.xml"
    src.write_text('<!DOCTYPE r [<!ENTITY a "aaaaaaaaaa">]><r><x>&a;</x></r>', encoding="utf-8")
    with pytest.raises(defusedxml.DefusedXmlException):
        update_datasets(src, {"r/x": "FICTIF"}, tmp_path / "out.xml")


# --- AcroForm --------------------------------------------------------------------------

def test_fill_acroform_refuses_a_pdf_without_form(tmp_path):
    with pytest.raises(ValueError):
        fill_acroform(make_plain_pdf(tmp_path / "plain.pdf"), {"x": "y"}, tmp_path / "out.pdf")


def test_fill_acroform_strips_usage_rights_and_ignores_unknown_names(tmp_path):
    src = make_acroform(tmp_path / "form.pdf", [
        ("lastName", "text", {}),
        ("reason", "combo", {"opt": [("M", "Maladie"), ("A", "Accident")]}),
    ])
    with pikepdf.open(str(src), allow_overwriting_input=True) as pdf:
        # Signature de droits d'usage (Reader-extended), fictive.
        pdf.Root.Perms = Dictionary(UR3=Dictionary())
        pdf.save(str(src))

    out = tmp_path / "out.pdf"
    filled = fill_acroform(src, {"lastName": "FICTIF", "reason": "Inconnu", "absent": "x"}, out)
    assert filled == {"lastName", "reason"}
    fields = read_fields(out)
    assert fields["lastName"]["V"] == "FICTIF"
    # Libellé hors des options : écrit tel quel plutôt que de choisir au hasard.
    assert fields["reason"]["V"] == "Inconnu"
    with pikepdf.open(str(out)) as pdf:
        assert "/Perms" not in pdf.Root
        assert bool(pdf.Root.AcroForm.NeedAppearances) is False


# --- _fill_pdf : de bout en bout ------------------------------------------------------

TEMPLATE = {"fields": [
    {"id": "1.1", "name": "lastName", "xml_path": "form1/lastName", "acroform_name": "lastName"},
    {"id": "1.2", "name": "urgent", "type": "bool", "options": ["On", "Off"], "xml_path": "form1/urgent"},
]}
RESULTS = [{"id": "1.1", "result": {"value": "FICTIF"}}, {"id": "1.2", "result": {"value": "oui"}}]


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "forms").mkdir()
    job = tmp_path / "job"
    job.mkdir()
    return tmp_path, job


def test_fill_pdf_writes_a_pure_xfa_form(workdir):
    root, job = workdir
    make_xfa_pdf(root / "forms" / "Form_Xfa.pdf")
    out, kind = orchestrator._fill_pdf("job-fictif", "Xfa", TEMPLATE, RESULTS, job)
    assert kind == "xfa" and out == job / "output.pdf"
    datasets = extract_xfa_packets(out)["datasets"]
    assert "<lastName>FICTIF</lastName>" in datasets
    assert "<urgent>On</urgent>" in datasets

    # Un second passage (re-run) remplace la sortie précédente.
    again, _ = orchestrator._fill_pdf("job-fictif", "Xfa", TEMPLATE, [], job)
    assert again == out
    assert "<lastName/>" in extract_xfa_packets(again)["datasets"].replace("<lastName />", "<lastName/>")


def test_fill_pdf_falls_back_to_acroform_when_xfa_is_unreadable(workdir):
    root, job = workdir
    add_xfa_stream(make_acroform(root / "forms" / "Form_Hybride.pdf", [("lastName", "text", {})]))
    out, kind = orchestrator._fill_pdf("job-fictif", "Hybride", TEMPLATE, RESULTS, job, suffix="_rerun")
    assert kind == "acroform" and out.name == "output_rerun.pdf"
    assert read_fields(out)["lastName"]["V"] == "FICTIF"


def test_fill_pdf_without_template_pdf(workdir):
    _, job = workdir
    with pytest.raises(FileNotFoundError):
        orchestrator._fill_pdf("job-fictif", "Absent", TEMPLATE, RESULTS, job)


def test_fill_pdf_refuses_a_pdf_without_form(workdir):
    root, job = workdir
    make_plain_pdf(root / "forms" / "Form_Plat.pdf")
    with pytest.raises(ValueError):
        orchestrator._fill_pdf("job-fictif", "Plat", TEMPLATE, RESULTS, job)
