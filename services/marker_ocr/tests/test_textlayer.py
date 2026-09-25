"""
Aiguillage couche texte / OCR (textlayer.py).

Le piège est le faux négatif silencieux : une page scannée rend une chaîne
vide sans erreur. Mal réglé dans un sens, l'OCR tourne pour rien sur tous les
PDF exportés d'un DPI (des minutes par dossier) ; dans l'autre, un scan part
sans texte et le formulaire reste vide.
"""

from pathlib import Path

import pikepdf
from pikepdf import Dictionary, Name

from textlayer import _page_is_usable, extract_text_layer, should_skip_ocr

TEXT = ("Rapport de consultation du 09.04.2026. Patiente DUPONT Jeanne, née le 02.02.1985. "
        "Lombalgie aigue, incapacite de travail a 100 pour cent du 09.04.2026 au 30.04.2026.")


def _pdf(path: Path, pages: list[bool]) -> Path:
    """PDF dont chaque page porte du texte (True) ou n'en porte pas, comme un scan (False)."""
    pdf = pikepdf.new()
    font = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1,
                                        BaseFont=Name.Helvetica, Encoding=Name.WinAnsiEncoding))
    for with_text in pages:
        pdf.add_blank_page(page_size=(595, 842))
        page = pdf.pages[-1]
        if with_text:
            lines = [TEXT[i:i + 70] for i in range(0, len(TEXT), 70)]
            body = "BT /F1 10 Tf 12 TL 50 780 Td " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
            page.obj.Resources = Dictionary(Font=Dictionary(F1=font))
            page.obj.Contents = pdf.make_stream(body.encode("latin-1"))
        else:
            page.obj.Contents = pdf.make_stream(b"0.9 g 50 50 495 742 re f")
    pdf.save(str(path))
    return path


def test_native_text_skips_ocr(tmp_path):
    text, ratio, pages = extract_text_layer(str(_pdf(tmp_path / "dpi.pdf", [True, True, True])))
    assert (ratio, pages) == (1.0, 3)
    assert "## Page 2" in text and "DUPONT Jeanne" in text
    assert should_skip_ocr(ratio, pages)


def test_scanned_document_goes_to_ocr(tmp_path):
    _, ratio, pages = extract_text_layer(str(_pdf(tmp_path / "scan.pdf", [False, False])))
    assert ratio == 0.0 and pages == 2
    assert not should_skip_ocr(ratio, pages)


def test_partly_scanned_document_goes_to_ocr(tmp_path):
    # 3 pages sur 4 : sous le seuil de 80 %, une page manquerait à l'extraction.
    _, ratio, pages = extract_text_layer(str(_pdf(tmp_path / "mixed.pdf", [True, True, True, False])))
    assert ratio == 0.75
    assert not should_skip_ocr(ratio, pages)


def test_broken_font_encoding_is_not_trusted():
    assert _page_is_usable(TEXT * 2)
    assert not _page_is_usable("�" * 10 + TEXT)
    assert not _page_is_usable("trop court")
