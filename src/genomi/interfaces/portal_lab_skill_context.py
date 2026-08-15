from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..operations.registry.catalog_meta import TOOL_CATALOG_OPERATIONS


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LAB_SKILL_PATH = _PROJECT_ROOT / "skills" / "lab" / "SKILL.md"


@lru_cache(maxsize=1)
def prompt_section() -> str:
    """Return complete Lab guidance without making the host agent read a file.

    Portal Codex turns run in a project-scoped sandbox.  Reading the installed
    skill symlink from that sandbox can require a host permission prompt, so
    the trusted portal process supplies the focused guidance and compact tool
    contracts as ordinary conversation context instead.
    """

    guidance = _skill_body(_LAB_SKILL_PATH.read_text(encoding="utf-8"))
    operations = {
        name: {
            "description": definition.get("description"),
            "input_schema": definition.get("input_schema"),
        }
        for name, definition in sorted(TOOL_CATALOG_OPERATIONS.items())
        if name.startswith("lab.")
    }
    return (
        "# Focused Genomi Lab capability guidance\n"
        "The portal has already loaded the complete focused Lab guidance below. "
        "Do not read or search for a Lab skill file. Decide semantically whether "
        "this turn needs Lab; the user's exact wording, disease names, and example "
        "prompts are never routing rules.\n\n"
        f"{guidance}\n\n"
        "# Canonical Lab operation contracts\n"
        "The following are the complete supported Lab operations. There is no "
        "lab.help operation. Invoke every operation only by calling the base MCP "
        "tool genomi.invoke with {\"tool\": \"lab.<operation>\", \"params\": {...}}; "
        "never call a lab.* name as a direct MCP tool.\n\n"
        f"{json.dumps(operations, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def _skill_body(document: str) -> str:
    text = document.strip()
    if not text.startswith("---"):
        return text
    _opening, separator, remainder = text.partition("\n---\n")
    return remainder.strip() if separator else text
