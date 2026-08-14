import { contextKindValue } from './portal_selected_evidence.js';

// Generated from src/genomi/interfaces/portal_selected_context_catalog.py.
// Do not edit directly; update the Python catalog and regenerate this asset.

export const SELECTED_CONTEXT_FALLBACK_PROMPT = "Use the included evidence to answer my message. Preserve provenance, source limits, and genome privacy boundaries.";

const DEFAULT_COPY = {
  "kindLabel": "Evidence",
  "askLabel": "Ask about evidence",
  "draftLabel": "Draft question",
  "selectedItemNoun": "evidence item",
  "selectedItemPluralNoun": "evidence items",
  "summaryIncludedLabel": "Summary included",
  "promptGroupLabel": "",
  "sourceRequest": false,
  "askEnabled": true,
  "draftEnabled": true
};

const SELECTED_CONTEXT_COPY = {
  "artifact": {
    "kindLabel": "Artifact",
    "askLabel": "Ask about artifact",
    "draftLabel": "Draft from artifact",
    "selectedItemNoun": "artifact item",
    "selectedItemPluralNoun": "artifact items",
    "summaryIncludedLabel": "Artifact summary included",
    "promptGroupLabel": "",
    "sourceRequest": false,
    "askEnabled": true,
    "draftEnabled": true
  },
  "result": {
    "kindLabel": "Artifact",
    "askLabel": "Ask about artifact",
    "draftLabel": "Draft from artifact",
    "selectedItemNoun": "artifact item",
    "selectedItemPluralNoun": "artifact items",
    "summaryIncludedLabel": "Artifact summary included",
    "promptGroupLabel": "",
    "sourceRequest": false,
    "askEnabled": true,
    "draftEnabled": true
  },
  "evidence_panel": {
    "kindLabel": "Evidence",
    "askLabel": "Ask about evidence",
    "draftLabel": "Draft from evidence",
    "selectedItemNoun": "evidence item",
    "selectedItemPluralNoun": "evidence items",
    "summaryIncludedLabel": "Summary included",
    "promptGroupLabel": "selected Genomi evidence",
    "sourceRequest": false,
    "askEnabled": true,
    "draftEnabled": true
  },
  "evidence_report": {
    "kindLabel": "Evidence",
    "askLabel": "Ask about evidence",
    "draftLabel": "Draft from evidence",
    "selectedItemNoun": "evidence item",
    "selectedItemPluralNoun": "evidence items",
    "summaryIncludedLabel": "Evidence report summary included",
    "promptGroupLabel": "selected Genomi evidence report",
    "sourceRequest": false,
    "askEnabled": true,
    "draftEnabled": true
  },
  "result_nodes": {
    "kindLabel": "Evidence",
    "askLabel": "Ask about evidence",
    "draftLabel": "Draft from evidence",
    "selectedItemNoun": "evidence item",
    "selectedItemPluralNoun": "evidence items",
    "summaryIncludedLabel": "Summary included",
    "promptGroupLabel": "selected Genomi result facts",
    "sourceRequest": false,
    "askEnabled": true,
    "draftEnabled": true
  },
  "genome_context": {
    "kindLabel": "Active genome",
    "askLabel": "",
    "draftLabel": "",
    "selectedItemNoun": "genome fact",
    "selectedItemPluralNoun": "genome facts",
    "summaryIncludedLabel": "Active genome included",
    "promptGroupLabel": "",
    "sourceRequest": false,
    "askEnabled": false,
    "draftEnabled": false
  },
  "review_finding": {
    "kindLabel": "Review finding",
    "askLabel": "Continue from finding",
    "draftLabel": "Draft correction",
    "selectedItemNoun": "review detail",
    "selectedItemPluralNoun": "review details",
    "summaryIncludedLabel": "Review finding included",
    "promptGroupLabel": "",
    "sourceRequest": false,
    "askEnabled": true,
    "draftEnabled": true
  },
  "tool_request": {
    "kindLabel": "Evidence source",
    "askLabel": "Ask with source",
    "draftLabel": "Draft question",
    "selectedItemNoun": "source detail",
    "selectedItemPluralNoun": "source details",
    "summaryIncludedLabel": "Evidence source included",
    "promptGroupLabel": "selected Genomi evidence source",
    "sourceRequest": true,
    "askEnabled": true,
    "draftEnabled": true
  },
  "tool_intent": {
    "kindLabel": "Evidence source",
    "askLabel": "Ask with source",
    "draftLabel": "Draft question",
    "selectedItemNoun": "source detail",
    "selectedItemPluralNoun": "source details",
    "summaryIncludedLabel": "Evidence source included",
    "promptGroupLabel": "selected Genomi evidence source",
    "sourceRequest": true,
    "askEnabled": true,
    "draftEnabled": true
  },
  "work_trace": {
    "kindLabel": "Work trail",
    "askLabel": "Ask about this work",
    "draftLabel": "Draft follow-up",
    "selectedItemNoun": "work step",
    "selectedItemPluralNoun": "work steps",
    "summaryIncludedLabel": "Summary included",
    "promptGroupLabel": "",
    "sourceRequest": false,
    "askEnabled": true,
    "draftEnabled": true
  },
  "workspace_file": {
    "kindLabel": "Project file",
    "askLabel": "Ask about file",
    "draftLabel": "Draft from file",
    "selectedItemNoun": "file detail",
    "selectedItemPluralNoun": "file details",
    "summaryIncludedLabel": "File summary included",
    "promptGroupLabel": "selected project file",
    "sourceRequest": false,
    "askEnabled": true,
    "draftEnabled": true
  },
  "default": {
    "kindLabel": "Evidence",
    "askLabel": "Ask about evidence",
    "draftLabel": "Draft question",
    "selectedItemNoun": "evidence item",
    "selectedItemPluralNoun": "evidence items",
    "summaryIncludedLabel": "Summary included",
    "promptGroupLabel": "",
    "sourceRequest": false,
    "askEnabled": true,
    "draftEnabled": true
  }
};

export function selectedContextKind(value) {
  return contextKindValue(contextKindInput(value));
}

export function selectedContextCopy(value) {
  const kind = selectedContextKind(value);
  const selected = SELECTED_CONTEXT_COPY[kind] || DEFAULT_COPY;
  return { ...selected, kind: kind || 'default' };
}

export function selectedContextSelectedItemNouns(value) {
  const selected = selectedContextCopy(value);
  return {
    singular: selected.selectedItemNoun,
    plural: selected.selectedItemPluralNoun
  };
}

export function selectedContextSummaryIncludedLabel(value) {
  return selectedContextCopy(value).summaryIncludedLabel;
}

export function isSelectedContextEvidenceSource(value) {
  return Boolean(selectedContextCopy(value).sourceRequest);
}

function contextKindInput(value) {
  return value && typeof value === 'object' ? value.context_kind : value;
}
