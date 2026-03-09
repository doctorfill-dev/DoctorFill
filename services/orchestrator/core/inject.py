"""
XFA Inject - Re-inject datasets into PDF.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf


def _remove_xml_declaration(xml_data: bytes) -> bytes:
    """Remove XML declaration and BOM from XML data."""
    # Remove BOM
    if xml_data.startswith(b"\xef\xbb\xbf"):
        xml_data = xml_data[3:]

    # Remove XML declaration
    if b"<?xml" in xml_data:
        idx = xml_data.find(b"?>")
        if idx != -1:
            xml_data = xml_data[idx + 2:].lstrip()

    return xml_data


def inject_datasets(
    input_pdf: str | Path,
    datasets_xml: str | Path,
    output_pdf: str | Path
) -> None:
    """
    Inject datasets XML into PDF.

    Args:
        input_pdf: Original PDF form path
        datasets_xml: Filled datasets XML path
        output_pdf: Output PDF path
    """
    # Read datasets
    datasets_path = Path(datasets_xml)
    datasets_data = datasets_path.read_bytes()
    datasets_data = _remove_xml_declaration(datasets_data)

    # Open PDF
    pdf = pikepdf.open(str(input_pdf))

    try:
        xfa = pdf.Root["/AcroForm"]["/XFA"]

        if isinstance(xfa, pikepdf.Array):
            # Find and update datasets packet
            for i in range(0, len(xfa), 2):
                if str(xfa[i]) == "datasets":
                    xfa[i + 1].write(datasets_data)
                    break
            else:
                raise ValueError("datasets packet not found in XFA array")
        else:
            raise ValueError("Unexpected XFA format")

        # Save output
        output_path = Path(output_pdf)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pdf.save(str(output_path))

    finally:
        pdf.close()
