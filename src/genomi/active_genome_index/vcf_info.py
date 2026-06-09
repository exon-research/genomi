from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

_RAW_INFO_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_INFO_KEY_INVALID_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_WHITESPACE_RE = re.compile(r"\s")
_STRUCTURAL_INFO_CHARS = set('"{}[]')
_INFO_VALUE_SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"


def format_vcf_info(value: Any) -> str:
    """Return a VCF INFO field from AGI metadata or raw VCF INFO text."""
    if value in (None, "", "."):
        return "."
    if isinstance(value, str):
        stripped = value.strip()
        if stripped in ("", "."):
            return "."
        parsed = _json_object(stripped)
        if parsed is not None:
            return _format_vcf_info_mapping(parsed)
        if _is_raw_vcf_info(stripped):
            return stripped
        return f"GENOMI_INFO={format_vcf_info_value(stripped)}"
    if isinstance(value, Mapping):
        return _format_vcf_info_mapping(value)
    return f"GENOMI_INFO={format_vcf_info_value(value)}"


def format_vcf_info_value(value: Any) -> str:
    if value is None:
        return "."
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Mapping):
        value = json.dumps(value, sort_keys=True, separators=(",", ":"))
    elif isinstance(value, (list, tuple, set)):
        items = value if not isinstance(value, set) else sorted(value, key=str)
        return ",".join(format_vcf_info_value(item) for item in items)
    text = str(value)
    if text == "":
        return "."
    return quote(text, safe=_INFO_VALUE_SAFE)


def _json_object(text: str) -> Mapping[str, Any] | None:
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _format_vcf_info_mapping(value: Mapping[Any, Any]) -> str:
    parts: list[str] = []
    for raw_key, raw_value in sorted(value.items(), key=lambda item: str(item[0])):
        key = _format_vcf_info_key(raw_key)
        if raw_value is None or raw_value == "":
            continue
        if isinstance(raw_value, bool):
            if raw_value:
                parts.append(key)
            continue
        parts.append(f"{key}={format_vcf_info_value(raw_value)}")
    return ";".join(parts) or "."


def _format_vcf_info_key(value: Any) -> str:
    key = _INFO_KEY_INVALID_RE.sub("_", str(value).strip()).strip("_")
    if not key:
        return "GENOMI_INFO"
    return key


def _is_raw_vcf_info(text: str) -> bool:
    if _WHITESPACE_RE.search(text):
        return False
    if any(char in text for char in _STRUCTURAL_INFO_CHARS):
        return False
    for item in text.split(";"):
        if not item:
            return False
        key = item.split("=", 1)[0]
        if not _RAW_INFO_KEY_RE.fullmatch(key):
            return False
    return True
