"""
textlayer.py — Extraction rapide de la couche texte native d'un PDF.

La plupart des documents médicaux exportés d'un DPI portent déjà une couche
texte : la relire coûte quelques millisecondes par page, contre une à deux
secondes pour un passage OCR complet. Ce module décide si cette couche est
exploitable et, le cas échéant, évite entièrement l'OCR.

Le piège classique est le faux négatif silencieux : sur une page scannée, un
extracteur natif renvoie une chaîne vide sans lever d'erreur. On raisonne donc
sur un score par page, pas sur un booléen.
"""

from __future__ import annotations

import logging
import re

import pypdfium2 as pdfium

logger = logging.getLogger(__name__)

# En dessous de ce nombre de caractères, une page est considérée comme non
# textuelle (page de garde, image pleine page, scan).
MIN_CHARS_PER_PAGE = 120

# Proportion de caractères de remplacement (U+FFFD) au-delà de laquelle la
# couche texte est jugée corrompue — typique d'un encodage de police cassé.
MAX_REPLACEMENT_RATIO = 0.02

# Part minimale de pages exploitables pour se passer de l'OCR.
MIN_USABLE_PAGE_RATIO = 0.8

_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def _clean(text: str) -> str:
    text = _WHITESPACE.sub(" ", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


def _page_is_usable(text: str) -> bool:
    if len(text.strip()) < MIN_CHARS_PER_PAGE:
        return False
    if not text:
        return False
    return text.count("�") / len(text) <= MAX_REPLACEMENT_RATIO


def extract_text_layer(pdf_path: str) -> tuple[str, float, int]:
    """
    Lit la couche texte native d'un PDF.

    Returns:
        (markdown, ratio de pages exploitables, nombre de pages)
        Le markdown porte un titre par page pour donner des points d'ancrage au
        découpage sémantique en aval, qui segmente sur les en-têtes.
    """
    doc = pdfium.PdfDocument(pdf_path)
    try:
        pages: list[str] = []
        usable = 0
        for index, page in enumerate(doc):
            textpage = page.get_textpage()
            try:
                raw = textpage.get_text_bounded() or ""
            finally:
                textpage.close()
            cleaned = _clean(raw)
            if _page_is_usable(cleaned):
                usable += 1
            pages.append(f"## Page {index + 1}\n\n{cleaned}")
        total = len(pages)
        if total == 0:
            return "", 0.0, 0
        return "\n\n".join(pages), usable / total, total
    finally:
        doc.close()


def should_skip_ocr(ratio: float, pages: int) -> bool:
    """Décide si la couche texte suffit à se passer de l'OCR."""
    return pages > 0 and ratio >= MIN_USABLE_PAGE_RATIO
