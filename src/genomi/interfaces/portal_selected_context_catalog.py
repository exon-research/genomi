from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from . import portal_turns

GENERIC_PROMPT = (
    "Use the included evidence to answer my message. Preserve provenance, source limits, and genome privacy boundaries."
)
SELECTED_CONTEXT_CATALOG_JS_PATH = Path(__file__).with_name("templates") / "portal_selected_context_catalog.js"


@dataclass(frozen=True)
class SelectedContextCopy:
    kind_label: str
    ask_label: str
    draft_label: str
    selected_item_noun: str
    selected_item_plural_noun: str
    summary_included_label: str
    prompt_group_label: str = ""
    source_request: bool = False
    ask_enabled: bool = True
    draft_enabled: bool = True


_DEFAULT_COPY = SelectedContextCopy(
    kind_label="Evidence",
    ask_label="Ask about evidence",
    draft_label="Draft question",
    selected_item_noun="evidence item",
    selected_item_plural_noun="evidence items",
    summary_included_label="Summary included",
)
_ARTIFACT_COPY = SelectedContextCopy(
    kind_label="Artifact",
    ask_label="Ask about artifact",
    draft_label="Draft from artifact",
    selected_item_noun="artifact item",
    selected_item_plural_noun="artifact items",
    summary_included_label="Artifact summary included",
)
_EVIDENCE_COPY = SelectedContextCopy(
    kind_label="Evidence",
    ask_label="Ask about evidence",
    draft_label="Draft from evidence",
    selected_item_noun="evidence item",
    selected_item_plural_noun="evidence items",
    summary_included_label="Summary included",
)
_SOURCE_COPY = SelectedContextCopy(
    kind_label="Evidence source",
    ask_label="Ask with source",
    draft_label="Draft question",
    selected_item_noun="source detail",
    selected_item_plural_noun="source details",
    summary_included_label="Evidence source included",
    prompt_group_label="selected Genomi evidence source",
    source_request=True,
)

SELECTED_CONTEXT_COPY: dict[str, SelectedContextCopy] = {
    "artifact": _ARTIFACT_COPY,
    "result": _ARTIFACT_COPY,
    "evidence_panel": replace(_EVIDENCE_COPY, prompt_group_label="selected Genomi evidence"),
    "evidence_report": replace(
        _EVIDENCE_COPY,
        summary_included_label="Evidence report summary included",
        prompt_group_label="selected Genomi evidence report",
    ),
    "result_nodes": replace(_EVIDENCE_COPY, prompt_group_label="selected Genomi result facts"),
    "genome_context": SelectedContextCopy(
        kind_label="Active genome",
        ask_label="",
        draft_label="",
        selected_item_noun="genome fact",
        selected_item_plural_noun="genome facts",
        summary_included_label="Active genome included",
        ask_enabled=False,
        draft_enabled=False,
    ),
    "review_finding": SelectedContextCopy(
        kind_label="Review finding",
        ask_label="Continue from finding",
        draft_label="Draft correction",
        selected_item_noun="review detail",
        selected_item_plural_noun="review details",
        summary_included_label="Review finding included",
    ),
    "tool_request": _SOURCE_COPY,
    "tool_intent": _SOURCE_COPY,
    "work_trace": SelectedContextCopy(
        kind_label="Work trail",
        ask_label="Ask about this work",
        draft_label="Draft follow-up",
        selected_item_noun="work step",
        selected_item_plural_noun="work steps",
        summary_included_label="Summary included",
    ),
    "workspace_file": SelectedContextCopy(
        kind_label="Project file",
        ask_label="Ask about file",
        draft_label="Draft from file",
        selected_item_noun="file detail",
        selected_item_plural_noun="file details",
        summary_included_label="File summary included",
        prompt_group_label="selected project file",
    ),
    "default": _DEFAULT_COPY,
}

RESULT_GROUP_KIND_ORDER = ("evidence_report", "result_nodes", "evidence_panel")
PRIORITY_PROMPTS = {
    "artifact": (
        "Review this Genomi artifact. Keep its provenance, source limits, and evidence state visible, "
        "then identify the next useful evidence step."
    ),
    "evidence_ledger": (
        "Use this Genomi evidence map to decide the next focused evidence step. Treat the map as reusable current "
        "recorded evidence, preserve source priors, and state which entries support a claim, need re-checking, or remain out of scope."
    ),
    "work_trace": (
        "Use this work trail to continue from what has already been attempted. Treat the trail as provenance "
        "for assistant work and evidence-source requests, preserve source limits, and report what supports the answer, what failed or "
        "needs re-checking, and what remains out of scope."
    ),
    "workspace_file": (
        "Use this project file as selected research material. Preserve its file identity, visible excerpt, provenance limits, "
        "and genome privacy boundaries; answer from the selected file details and say when the file preview is insufficient."
    ),
    "genome_context": (
        "Use this active genome only as the current-session boundary. Preserve genome privacy limits, identify "
        "the smallest relevant Genomi evidence step, and avoid sample-specific claims unless the selected evidence explicitly supports them."
    ),
}
PRIORITY_PROMPT_KIND_ORDER = ("artifact", "evidence_ledger", "work_trace", "workspace_file", "genome_context")


def selected_context_kind(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("context_kind")
    return portal_turns.prompt_safe_text(str(value or "")).strip().lower()


def selected_context_copy(value: Any) -> SelectedContextCopy:
    return SELECTED_CONTEXT_COPY.get(selected_context_kind(value), _DEFAULT_COPY)


def source_request_kinds() -> set[str]:
    return {kind for kind, copy in SELECTED_CONTEXT_COPY.items() if copy.source_request}


def source_request_prompt_label() -> str:
    return _SOURCE_COPY.prompt_group_label


def result_operation_groups() -> list[dict[str, Any]]:
    return [
        {"kind": kind, "label": SELECTED_CONTEXT_COPY[kind].prompt_group_label, "operations": []}
        for kind in RESULT_GROUP_KIND_ORDER
        if SELECTED_CONTEXT_COPY[kind].prompt_group_label
    ]


def selected_context_catalog_js() -> str:
    return "\n".join(
        [
            "import { contextKindValue } from './portal_selected_evidence.js';",
            "",
            "// Generated from src/genomi/interfaces/portal_selected_context_catalog.py.",
            "// Do not edit directly; update the Python catalog and regenerate this asset.",
            "",
            f"export const SELECTED_CONTEXT_FALLBACK_PROMPT = {_js_literal(GENERIC_PROMPT)};",
            "",
            f"const DEFAULT_COPY = {_js_literal(_copy_payload(_DEFAULT_COPY))};",
            "",
            f"const SELECTED_CONTEXT_COPY = {_js_literal(_catalog_payload())};",
            "",
            "export function selectedContextKind(value) {",
            "  return contextKindValue(contextKindInput(value));",
            "}",
            "",
            "export function selectedContextCopy(value) {",
            "  const kind = selectedContextKind(value);",
            "  const selected = SELECTED_CONTEXT_COPY[kind] || DEFAULT_COPY;",
            "  return { ...selected, kind: kind || 'default' };",
            "}",
            "",
            "export function selectedContextSelectedItemNouns(value) {",
            "  const selected = selectedContextCopy(value);",
            "  return {",
            "    singular: selected.selectedItemNoun,",
            "    plural: selected.selectedItemPluralNoun",
            "  };",
            "}",
            "",
            "export function selectedContextSummaryIncludedLabel(value) {",
            "  return selectedContextCopy(value).summaryIncludedLabel;",
            "}",
            "",
            "export function isSelectedContextEvidenceSource(value) {",
            "  return Boolean(selectedContextCopy(value).sourceRequest);",
            "}",
            "",
            "function contextKindInput(value) {",
            "  return value && typeof value === 'object' ? value.context_kind : value;",
            "}",
            "",
        ]
    )


def write_selected_context_catalog_js(path: Path | None = None) -> Path:
    output_path = path or SELECTED_CONTEXT_CATALOG_JS_PATH
    output_path.write_text(selected_context_catalog_js(), encoding="utf-8")
    return output_path


def _copy_payload(copy: SelectedContextCopy) -> dict[str, Any]:
    return {
        "kindLabel": copy.kind_label,
        "askLabel": copy.ask_label,
        "draftLabel": copy.draft_label,
        "selectedItemNoun": copy.selected_item_noun,
        "selectedItemPluralNoun": copy.selected_item_plural_noun,
        "summaryIncludedLabel": copy.summary_included_label,
        "promptGroupLabel": copy.prompt_group_label,
        "sourceRequest": copy.source_request,
        "askEnabled": copy.ask_enabled,
        "draftEnabled": copy.draft_enabled,
    }


def _catalog_payload() -> dict[str, dict[str, Any]]:
    return {kind: _copy_payload(copy) for kind, copy in SELECTED_CONTEXT_COPY.items()}


def _js_literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2)


if __name__ == "__main__":
    write_selected_context_catalog_js()
