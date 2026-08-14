from __future__ import annotations

from typing import Any

from . import portal_turns

JsonObject = dict[str, Any]
ARTIFACT_PRESENTATION_SCHEMA = "genomi_portal_artifact_presentation"


def artifact_presentation(artifact: JsonObject) -> JsonObject:
    family, category = _artifact_family(artifact)
    copy = _surface_copy(family)
    return {
        "schema": ARTIFACT_PRESENTATION_SCHEMA,
        "family": family,
        "category": category,
        "surface_copy": copy,
    }


def _artifact_family(artifact: JsonObject) -> tuple[str, str]:
    kind = _clean(artifact.get("kind")).lower()
    renderer = _clean(artifact.get("renderer")).lower()
    operation = _clean(artifact.get("operation")).lower()
    if kind == "evidence_packet" or renderer == "evidence_packet" or operation == "research.build_target_packet":
        return "evidence_report", "evidence"
    if kind == "decode_dashboard" or renderer == "decode_dashboard" or operation == "decode.render_dashboard":
        return "legacy_report", "report"
    if kind == "project_file" or renderer == "project_file" or operation == "portal.import_file":
        return "file", "file"
    return "artifact", "other"


def _surface_copy(family: str) -> JsonObject:
    if family == "evidence_report":
        return {
            "noun": "report",
            "summary_noun": "report summary",
            "selected_item": "evidence item",
            "selected_items": "evidence items",
            "selected_heading": "Selected evidence",
            "selected_group": "Evidence report",
            "use_label": "Use report",
            "ask_label": "Ask about report",
            "draft_label": "Draft from report",
            "open_label": "Open report",
            "label_prefix": "Evidence report",
            "prompt_intro_prefix": "Selected evidence report",
            "context_kind": "evidence_report",
            "node_context_prefix": "Evidence report",
        }
    if family == "legacy_report":
        return {
            "noun": "report",
            "summary_noun": "report summary",
            "selected_item": "report item",
            "selected_items": "report items",
            "selected_heading": "Selected report items",
            "selected_group": "Report",
            "use_label": "Use report",
            "ask_label": "Ask about report",
            "draft_label": "Draft from report",
            "open_label": "Open report",
            "label_prefix": "Report",
            "prompt_intro_prefix": "Selected report",
            "context_kind": "report",
            "node_context_prefix": "Report",
        }
    if family == "file":
        return {
            "noun": "file",
            "summary_noun": "file summary",
            "selected_item": "file item",
            "selected_items": "file items",
            "selected_heading": "Selected file items",
            "selected_group": "File",
            "use_label": "Use file",
            "ask_label": "Ask about file",
            "draft_label": "Draft from file",
            "open_label": "Open file",
            "label_prefix": "File",
            "prompt_intro_prefix": "Selected file",
            "context_kind": "file",
            "node_context_prefix": "File",
        }
    return {
        "noun": "result",
        "summary_noun": "result summary",
        "selected_item": "artifact item",
        "selected_items": "artifact items",
        "selected_heading": "Selected artifact items",
        "selected_group": "Artifact",
        "use_label": "Use artifact",
        "ask_label": "Ask about artifact",
        "draft_label": "Draft from artifact",
        "open_label": "Open artifact",
        "label_prefix": "Artifact",
        "prompt_intro_prefix": "Selected artifact",
        "context_kind": "result",
        "node_context_prefix": "Artifact details",
    }


def _clean(value: Any) -> str:
    return portal_turns.prompt_safe_text(str(value or "")).strip()
