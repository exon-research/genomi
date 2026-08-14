from __future__ import annotations

import re
from typing import Any

JsonObject = dict[str, Any]

LOCAL_PATH_RE = re.compile(
    r"(?:~|/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes)"
    r"(?:/[^\s\"'<>),;:]+)*"
)
SENSITIVE_PATH_FIELD_RE = re.compile(
    r"([\"']?)(context_file|registry_file|agi_path|dashboard_path|shared_evidence_db)\1\s*[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^,\s}\]]+)",
    re.IGNORECASE,
)
SENSITIVE_FIELD_NAMES = {
    "path",
    "file_path",
    "context_file",
    "registry_file",
    "agi_path",
    "dashboard_path",
    "shared_evidence_db",
}


def prompt_safe_text(value: object) -> str:
    text = str(value or "")

    def replace_field(match: re.Match[str]) -> str:
        key = match.group(2).replace("_", " ")
        return f"{key}: [redacted local path]"

    return LOCAL_PATH_RE.sub("[redacted local path]", SENSITIVE_PATH_FIELD_RE.sub(replace_field, text))


def prompt_safe_value(value: Any, *, max_list_items: int = 32) -> Any:
    if isinstance(value, str):
        return prompt_safe_text(value)
    if isinstance(value, list):
        return [prompt_safe_value(item, max_list_items=max_list_items) for item in value[:max_list_items]]
    if isinstance(value, dict):
        cleaned: JsonObject = {}
        for key, child in value.items():
            clean_key = str(key)
            if clean_key.lower() in SENSITIVE_FIELD_NAMES:
                continue
            cleaned[clean_key] = prompt_safe_value(child, max_list_items=max_list_items)
        return cleaned
    return value
