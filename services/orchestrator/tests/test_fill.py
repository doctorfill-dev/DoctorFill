"""Écriture des valeurs dans le PDF : AcroForm, datasets XFA, cases à cocher."""

from core.acroform import fill_acroform
from core.checkbox import normalize_checkboxes
from core.fill import update_datasets
from tests.pdf_factory import make_acroform, read_fields


def test_fill_acroform_text_checkbox_and_choice(tmp_path):
    blank = make_acroform(tmp_path / "blank.pdf", [
        ("lastName", "text", {}),
        ("urgent", "checkbox", {}),
        ("notUrgent", "checkbox", {}),
        ("ask4Hospitalization", "combo", {"opt": [("0", "non"), ("1", "oui")]}),
        ("reason", "combo", {"opt": [("M", "Maladie"), ("A", "Accident")]}),
    ])
    out = tmp_path / "out.pdf"
    filled = fill_acroform(blank, {
        "lastName": "Dupont", "urgent": "1", "notUrgent": "0",
        "ask4Hospitalization": "1", "reason": "Accident",
    }, out)
    assert filled == {"lastName", "urgent", "notUrgent", "ask4Hospitalization", "reason"}

    fields = read_fields(out)
    assert fields["lastName"]["V"] == "Dupont" and "(Dupont) Tj" in fields["lastName"]["ap_text"]
    assert fields["urgent"]["V"] == "/On" and fields["urgent"]["AS"] == "/On"
    assert fields["notUrgent"]["V"] == "/Off" and fields["notUrgent"]["AS"] == "/Off"
    # Export dans /V, libellé à l'écran — dans les deux sens d'appariement.
    assert fields["ask4Hospitalization"]["V"] == "1"
    assert "(oui) Tj" in fields["ask4Hospitalization"]["ap_text"]
    assert fields["reason"]["V"] == "A"
    assert "(Accident) Tj" in fields["reason"]["ap_text"]


def test_update_datasets_keeps_checkbox_states(tmp_path):
    src = tmp_path / "base.xml"
    src.write_text(
        '<xfa:datasets xmlns:xfa="http://www.xfa.org/schema/xfa-data/1.0/"><xfa:data>'
        "<form><page1><urgent>Off</urgent><hosp/><phone/><phone/></page1></form>"
        "</xfa:data></xfa:datasets>", encoding="utf-8")
    dst = tmp_path / "filled.xml"
    fields = [{"xml_path": "form/page1/urgent", "type": "bool"},
              {"xml_path": "form/page1/hosp", "type": "bool"}]
    update_datasets(src, {"form/page1/urgent": "On", "form/page1/hosp": "oui",
                          "form/page1/phone[1]": "079 000 00 00"}, dst, fields)
    xml = dst.read_text(encoding="utf-8")
    # « On » n'est plus ramené à « 0 », « oui » coche la case.
    assert "<urgent>On</urgent>" in xml
    assert "<hosp>1</hosp>" in xml
    assert "<phone /><phone>079 000 00 00</phone>" in xml.replace("<phone/>", "<phone />")


def test_normalize_checkboxes_understands_french():
    values = {"a": "oui", "b": "non", "c": "Dupont"}
    normalize_checkboxes(values, ["a", "b"])
    assert values == {"a": "On", "b": "Off", "c": "Dupont"}
