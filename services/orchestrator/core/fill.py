"""
XFA Fill - Update field values in XFA datasets.
"""

from __future__ import annotations

import logging
import defusedxml.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)


def _local(tag: str) -> str:
    """Extract local name from namespaced tag."""
    return tag.split("}", 1)[-1]


def _iter_children(node: ET.Element, tag: str) -> Iterable[ET.Element]:
    """Iterate children with matching local tag name."""
    for child in node:
        if _local(child.tag) == tag:
            yield child


def _split_segment(segment: str) -> tuple[str, int]:
    """
    Split a path segment into (tag, occurrence index).

    `phone` and `phone[0]` both mean the first occurrence; `phone[1]` the second.
    Sibling fields sharing a name are common in the medForms address blocks.
    """
    if segment.endswith("]") and "[" in segment:
        tag, _, raw = segment.partition("[")
        try:
            return tag, int(raw[:-1])
        except ValueError:
            return segment, 0
    return segment, 0


def _find(root: ET.Element, path: str) -> Optional[ET.Element]:
    """
    Find element by XFA path.

    Searches anywhere in the tree for the first segment, then navigates down
    through children. Segments may carry an occurrence index (`phone[1]`);
    without one the first occurrence is used, as before.
    """
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None

    tag, index = _split_segment(parts[0])
    candidates = [n for n in root.iter() if _local(n.tag) == tag]
    if len(candidates) <= index:
        return None
    candidates = candidates[index:index + 1] if index else candidates

    for part in parts[1:]:
        tag, index = _split_segment(part)
        next_candidates = []
        for node in candidates:
            children = list(_iter_children(node, tag))
            if len(children) > index:
                next_candidates.append(children[index])
        if not next_candidates:
            return None
        candidates = next_candidates

    return candidates[0]


def _normalize_value(value: Any, kind: str) -> str:
    """Normalize value based on type."""
    if value is None:
        return ""

    if kind == "bool":
        return "1" if value in {"1", "true", "True", True} else "0"

    if kind == "int":
        try:
            return str(int(value))
        except (ValueError, TypeError):
            return str(value)

    return str(value)


def _build_type_map(fields: Any) -> Dict[str, str]:
    """Build mapping of path -> type from template fields."""
    type_map: Dict[str, str] = {}

    items = fields.values() if isinstance(fields, dict) else (fields or [])
    for f in items:
        if isinstance(f, dict):
            key = f.get("xml_path") or f.get("path") or f.get("name") or f.get("id")
            if key:
                type_map[key] = f.get("type", "str")

    return type_map


def update_datasets(
    src_xml: str | Path,
    filled_values: Dict[str, Any],
    dst_xml: str | Path,
    template_fields: Any = None,
    overwrite: bool = True,
) -> None:
    """
    Update XFA datasets XML with filled values.

    Args:
        src_xml: Source datasets XML path
        filled_values: Dict of xfa_path -> value
        dst_xml: Destination XML path
        template_fields: Template fields for type information
        overwrite: Whether to overwrite existing values
    """
    tree = ET.parse(src_xml)
    root = tree.getroot()

    type_map = _build_type_map(template_fields) if template_fields else {}

    for path, value in filled_values.items():
        node = _find(root, path)
        if node is None:
            logger.warning("Path not found: %s", path)
            continue

        if not overwrite and (node.text or "").strip():
            continue

        field_type = type_map.get(path, "str")
        node.text = _normalize_value(value, field_type)

    Path(dst_xml).write_bytes(ET.tostring(root, encoding="utf-8"))
    logger.info("Datasets updated: %s", dst_xml)
