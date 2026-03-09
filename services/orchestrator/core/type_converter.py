"""
Type Converter - Converts RAG responses to proper field values.

Handles dates, booleans, checkboxes, and other type conversions.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class TypeConverter:
    """
    Converts RAG response values to proper types for form filling.
    """

    # Truthy values for boolean conversion
    TRUTHY = {"oui", "yes", "true", "1", "on", "x", "checked", "vrai"}
    FALSY = {"non", "no", "false", "0", "off", "", "faux"}

    # Date format patterns
    DATE_PATTERNS = [
        # DD.MM.YYYY (Swiss format)
        (r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$', '{0}.{1}.{2}'),
        # DD/MM/YYYY
        (r'^(\d{1,2})/(\d{1,2})/(\d{4})$', '{0}.{1}.{2}'),
        # DD-MM-YYYY
        (r'^(\d{1,2})-(\d{1,2})-(\d{4})$', '{0}.{1}.{2}'),
        # YYYY-MM-DD (ISO)
        (r'^(\d{4})-(\d{2})-(\d{2})$', '{2}.{1}.{0}'),
    ]

    def convert(
        self,
        value: Any,
        field_type: str,
        field_id: Optional[str] = None
    ) -> str:
        """
        Convert a value to the appropriate type.

        Args:
            value: Value to convert
            field_type: Target type (str, bool, int, date, etc.)
            field_id: Optional field ID for context

        Returns:
            Converted string value
        """
        if value is None:
            return ""

        field_type = field_type.lower()

        if field_type in ("bool", "boolean", "checkbox"):
            return self._convert_boolean(value)
        elif field_type == "date":
            return self._convert_date(value)
        elif field_type in ("int", "integer", "number"):
            return self._convert_number(value)
        elif field_type == "percent":
            return self._convert_percent(value)
        else:
            return str(value).strip()

    def convert_for_xfa(
        self,
        value: Any,
        field_type: str,
        is_checkbox: bool = False
    ) -> str:
        """
        Convert value specifically for XFA form filling.

        Args:
            value: Value to convert
            field_type: Field type
            is_checkbox: Whether field is a checkbox (uses On/Off)

        Returns:
            XFA-compatible string value
        """
        if value is None:
            return ""

        if is_checkbox:
            return self._to_on_off(value)

        return self.convert(value, field_type)

    def _convert_boolean(self, value: Any) -> str:
        """Convert to boolean string (oui/non)."""
        if isinstance(value, bool):
            return "oui" if value else "non"

        if isinstance(value, (int, float)):
            return "oui" if value != 0 else "non"

        if value is None:
            return "non"

        s = str(value).strip().lower()

        if s in self.TRUTHY:
            return "oui"
        if s in self.FALSY:
            return "non"

        # Default
        return "non"

    def _to_on_off(self, value: Any) -> str:
        """Convert to On/Off for XFA checkboxes."""
        if isinstance(value, bool):
            return "On" if value else "Off"

        if isinstance(value, (int, float)):
            return "On" if value != 0 else "Off"

        if value is None:
            return "Off"

        s = str(value).strip()

        # Already On/Off
        if s in ("On", "Off"):
            return s

        s_lower = s.lower()

        if s_lower in self.TRUTHY:
            return "On"
        if s_lower in self.FALSY:
            return "Off"

        return "Off"

    def _convert_date(self, value: Any) -> str:
        """Convert to DD.MM.YYYY date format."""
        if not value:
            return ""

        s = str(value).strip()

        # Try each pattern
        for pattern, output_format in self.DATE_PATTERNS:
            match = re.match(pattern, s)
            if match:
                groups = match.groups()
                # Pad day and month
                day = groups[0].zfill(2) if len(groups[0]) <= 2 else groups[0]
                month = groups[1].zfill(2) if len(groups[1]) <= 2 else groups[1]

                if len(groups) == 3:
                    year = groups[2]
                    return f"{day}.{month}.{year}"

        # Return as-is if no pattern matched
        return s

    def _convert_number(self, value: Any) -> str:
        """Convert to number string."""
        if value is None:
            return ""

        if isinstance(value, (int, float)):
            if isinstance(value, float) and value.is_integer():
                return str(int(value))
            return str(value)

        s = str(value).strip()

        # Try to parse as number
        try:
            num = float(s.replace(',', '.'))
            if num.is_integer():
                return str(int(num))
            return str(num)
        except ValueError:
            pass

        # Extract digits if string contains text
        digits = re.sub(r'[^\d.,]', '', s)
        if digits:
            try:
                num = float(digits.replace(',', '.'))
                if num.is_integer():
                    return str(int(num))
                return str(num)
            except ValueError:
                pass

        return s

    def _convert_percent(self, value: Any) -> str:
        """Convert to percentage (integer 0-100)."""
        if value is None:
            return ""

        s = str(value).strip()

        # Remove % sign
        s = s.replace('%', '').strip()

        try:
            num = float(s.replace(',', '.'))
            return str(int(round(num)))
        except ValueError:
            return s

    def batch_convert(
        self,
        values: Dict[str, Any],
        field_types: Dict[str, str],
        checkbox_paths: Optional[List[str]] = None
    ) -> Dict[str, str]:
        """
        Convert a batch of values.

        Args:
            values: Dict of field_id -> value
            field_types: Dict of field_id -> type
            checkbox_paths: List of paths that are checkboxes

        Returns:
            Dict of field_id -> converted value
        """
        checkbox_set = set(checkbox_paths or [])
        converted = {}

        for field_id, value in values.items():
            field_type = field_types.get(field_id, "str")
            is_checkbox = field_id in checkbox_set

            if is_checkbox:
                converted[field_id] = self._to_on_off(value)
            else:
                converted[field_id] = self.convert(value, field_type, field_id)

        return converted
