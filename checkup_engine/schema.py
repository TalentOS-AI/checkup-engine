"""Tiny validator for the subset of JSON Schema used by report_schema.json (no dependencies)."""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA = json.loads((Path(__file__).parent / "report_schema.json").read_text(encoding="utf-8"))
_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool,
          "null": type(None)}


def _check(value, schema, path, errors):
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
        return
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        ok = any(isinstance(value, _TYPES[x]) and not (x in ("integer", "number") and isinstance(value, bool))
                 for x in types)
        if not ok:
            errors.append(f"{path}: expected {t}, got {type(value).__name__}")
            return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing '{key}'")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                _check(value[key], sub, f"{path}.{key}", errors)
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: too many items")
        if "items" in schema:
            for i, item in enumerate(value):
                _check(item, schema["items"], f"{path}[{i}]", errors)


def validate(report: dict) -> list[str]:
    """Return a list of error strings (empty list = valid)."""
    errors: list[str] = []
    _check(report, SCHEMA, "$", errors)
    return errors
