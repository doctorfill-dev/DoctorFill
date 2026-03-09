"""
XFA Checkbox Handling.

Discovers checkbox fields and normalizes their values to On/Off.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

from lxml import etree


# ──────────────────────────────────────────────────────────────
# Checkbox Discovery
# ──────────────────────────────────────────────────────────────

def _local_name(tag: str) -> str:
    """Extract local name from namespaced tag."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _build_xpath_path(element: etree._Element) -> str:
    """
    Build XFA-style path from root to element.

    Ignores standard XFA container elements (datasets, data).
    """
    parts: List[str] = []
    current = element

    while current is not None and isinstance(current.tag, str):
        name = _local_name(current.tag)
        # Ignore XFA container elements
        if name not in {"datasets", "data"}:
            parts.append(name)
        current = current.getparent()

    parts.reverse()
    return "/".join(parts)


def discover_checkbox_paths(datasets_xml: str | Path) -> List[str]:
    """
    Discover checkbox field paths from datasets XML.

    Checkboxes are identified by having values of 'On' or 'Off'.

    Args:
        datasets_xml: Path to datasets XML file

    Returns:
        List of XFA paths for checkbox fields
    """
    tree = etree.parse(str(datasets_xml))
    root = tree.getroot()

    candidates: List[str] = []

    # Find all leaf elements with On/Off values
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue

        # Only check leaf elements
        if len(element) == 0:
            text = (element.text or "").strip()
            if text in {"On", "Off"}:
                path = _build_xpath_path(element)
                if path:
                    candidates.append(path)

    # Deduplicate while preserving order
    seen = set()
    unique: List[str] = []
    for path in candidates:
        if path not in seen:
            seen.add(path)
            unique.append(path)

    return unique


# ──────────────────────────────────────────────────────────────
# Checkbox Normalization
# ──────────────────────────────────────────────────────────────

_TRUTHY = {"on", "true", "1", "yes", "y", "x", "checked"}
_FALSY = {"off", "false", "0", "no", "n", ""}


def _to_on_off(value: Any) -> str:
    """Convert any value to On/Off checkbox value."""
    if isinstance(value, bool):
        return "On" if value else "Off"

    if isinstance(value, (int, float)):
        return "On" if value != 0 else "Off"

    if value is None:
        return "Off"

    s = str(value).strip()

    # Already normalized
    if s in ("On", "Off"):
        return s

    # Check truthy/falsy strings
    s_lower = s.lower()
    if s_lower in _TRUTHY:
        return "On"
    if s_lower in _FALSY:
        return "Off"

    # Default fallback
    return "Off"


def normalize_checkboxes(
    values: Dict[str, Any],
    checkbox_paths: Iterable[str]
) -> None:
    """
    Normalize checkbox values to On/Off in place.

    Args:
        values: Dict of XFA paths to values (modified in place)
        checkbox_paths: Paths that are known checkboxes
    """
    for path in checkbox_paths:
        if path in values:
            values[path] = _to_on_off(values[path])
