"""
XFA Extraction - Extract XFA datasets from PDF.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from pypdf import PdfReader


class PDFNoXFAError(RuntimeError):
    """PDF does not contain XFA data."""
    pass


def extract_xfa_packets(pdf_path: str | Path) -> Dict[str, str]:
    """
    Extract all XFA packets from a PDF.

    Returns:
        Dict of packet_name -> xml_content
    """
    reader = PdfReader(str(pdf_path))

    try:
        root = reader.trailer["/Root"]
    except Exception as e:
        raise RuntimeError(f"Corrupted PDF (no /Root): {e}") from e

    if "/AcroForm" not in root:
        raise PDFNoXFAError("No /AcroForm in PDF")

    acroform = root["/AcroForm"]

    if "/XFA" not in acroform:
        raise PDFNoXFAError("No XFA in PDF (classic AcroForm document?)")

    xfa = acroform["/XFA"]

    if not isinstance(xfa, list):
        raise PDFNoXFAError("Unexpected XFA format (expected list)")

    packets: Dict[str, str] = {}
    for i in range(0, len(xfa), 2):
        name = str(xfa[i])
        try:
            stream = xfa[i + 1].get_object()
            data = stream.get_data()
            text = data.decode("utf-8", errors="ignore")
            packets[name] = text
        except Exception:
            continue

    return packets


def extract_xfa_datasets(
    pdf_path: str | Path,
    output_xml: str | Path
) -> str:
    """
    Extract XFA datasets packet and save to file.

    Args:
        pdf_path: Input PDF path
        output_xml: Output XML path

    Returns:
        Path to output XML file
    """
    pdf_path = Path(pdf_path)
    output_xml = Path(output_xml)

    packets = extract_xfa_packets(pdf_path)

    datasets_xml = packets.get("datasets", "")
    if not datasets_xml:
        raise ValueError("No 'datasets' section found in XFA")

    output_xml.parent.mkdir(parents=True, exist_ok=True)
    output_xml.write_text(datasets_xml, encoding="utf-8")

    return str(output_xml)
