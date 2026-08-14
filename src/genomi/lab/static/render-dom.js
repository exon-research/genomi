"use strict";

export const elements = {};

const REQUIRED_ELEMENT_IDS = [
  "global-alert", "global-alert-message", "alert-dismiss", "setup-state", "research-desk",
  "current-user-name", "current-user-id", "genome-status", "genome-detail", "profile-summary",
  "manage-genome-button", "attention-plan-reviews", "attention-provider-approvals",
  "attention-running-jobs", "attention-new-evidence", "attention-completed-briefs",
  "observation-form", "observation-list", "observation-count", "observation-artifact",
  "observation-specimen", "observation-assay", "observation-source-note", "observation-record-assertion",
  "observation-editor", "observation-edit-form", "observation-edit-modality",
  "observation-edit-label", "observation-edit-assertion-status", "observation-edit-artifact", "observation-edit-record-assertion",
  "observation-edit-specimen", "observation-edit-assay", "observation-edit-link-help",
  "observation-edit-reported-variant", "observation-edit-gene", "observation-edit-cancel",
  "source-artifact-form", "source-artifact-file", "specimen-form", "specimen-artifact",
  "assay-form", "assay-specimen", "assay-artifact", "assay-link-help",
  "source-artifact-list", "specimen-list", "assay-list", "coverage-list", "profile-version-count",
  "observation-history-list", "question-form", "question",
  "evidence-library-count", "evidence-library-list", "context-activity-list",
  "research-tools", "integrations-summary", "integration-list",
  "disclosure-activity-list", "plan-activity-list",
  "disease-scope", "investigation-list", "investigation-count", "activity-status", "version-label",
  "investigation-detail", "detail-close", "detail-title", "detail-scope", "detail-status",
  "harness-name", "harness-location", "harness-capability", "harness-disclosure",
  "plan-summary", "plan-list", "progress-summary", "context-state", "context-preview",
  "plan-review-status", "plan-review-actions", "plan-accept-button", "plan-change-form",
  "plan-change-message", "plan-change-button",
  "context-observation-selector", "context-selection-help", "context-observation-list",
  "context-preview-purpose", "context-preview-list", "context-preview-button",
  "context-refresh-preview-button", "context-approve-button", "context-revoke-button", "harness-binding-state",
  "harness-preview-button", "resume-preview-button", "replace-harness-button", "cancel-harness-button",
  "harness-message-form", "harness-message", "message-preview-button", "harness-outbound-preview",
  "harness-outbound-destination", "harness-outbound-details", "harness-approve-button",
  "reconnect-events-button", "event-status", "event-list", "evidence-count", "evidence-ledger",
  "capability-approval-list", "hypothesis-list", "gap-list", "brief-version-count", "brief-list",
];

export function requiredElementIds() {
  return [...REQUIRED_ELEMENT_IDS];
}

export function collectElements() {
  REQUIRED_ELEMENT_IDS.forEach((id) => {
    const result = document.getElementById(id);
    if (!result) throw new Error(`Required portal element is missing: ${id}`);
    elements[toPropertyName(id)] = result;
  });
  elements.observationSubmit = elements.observationForm.querySelector("button[type='submit']");
  elements.observationEditSubmit = elements.observationEditForm.querySelector("button[type='submit']");
  elements.sourceArtifactSubmit = elements.sourceArtifactForm.querySelector("button[type='submit']");
  elements.specimenSubmit = elements.specimenForm.querySelector("button[type='submit']");
  elements.assaySubmit = elements.assayForm.querySelector("button[type='submit']");
  elements.questionSubmit = elements.questionForm.querySelector("button[type='submit']");
}

export function showAlert(message, kind = "error") {
  elements.globalAlert.hidden = false;
  elements.globalAlert.dataset.kind = kind;
  elements.globalAlertMessage.textContent = message;
}

export function hideAlert() {
  elements.globalAlert.hidden = true;
  elements.globalAlertMessage.textContent = "";
}

export function setActivity(message) {
  elements.activityStatus.textContent = String(message || "Ready.");
}

export function setBusy(button, busy, label) {
  if (busy) {
    button.dataset.idleLabel = button.textContent;
    button.disabled = true;
    button.textContent = label;
    return;
  }
  button.disabled = false;
  if (button.dataset.idleLabel) button.textContent = button.dataset.idleLabel;
  delete button.dataset.idleLabel;
}

export function appendDefinition(target, label, value) {
  target.append(node("dt", label), node("dd", value));
}

export function replaceDefinitions(target, definitions) {
  const children = [];
  definitions.forEach(([label, value, kind]) => {
    children.push(node("dt", label));
    const description = document.createElement("dd");
    if (kind === "exact") {
      description.append(node("pre", value, "exact-payload"));
    } else {
      description.textContent = value;
    }
    children.push(description);
  });
  target.replaceChildren(...children);
}

export function countDescription(value, noun) {
  const items = array(value);
  if (!items.length) return "None";
  return `${items.length} ${items.length === 1 ? noun : `${noun}s`}: ${items.map(text).join(", ")}`;
}

export function exactValue(value) {
  if (value === undefined) return "Not provided";
  try {
    return JSON.stringify(value, null, 2);
  } catch (_error) {
    return text(value);
  }
}

export function formatTime(value) {
  if (!value) return "Time not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {dateStyle: "medium", timeStyle: "short"});
}

export function timestamp(value) {
  const parsed = new Date(text(value)).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function array(value) {
  return Array.isArray(value) ? value : [];
}

export function isObject(value) {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

export function empty(message) {
  return node("li", message, "empty-row");
}

export function node(tag, value, className = "") {
  const result = document.createElement(tag);
  result.textContent = value;
  if (className) result.className = className;
  return result;
}

export function text(value) {
  return value === null || value === undefined ? "" : String(value);
}

export function friendly(value) {
  return value ? value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()) : "";
}

export function shortId(value) {
  if (!value) return "";
  return value.startsWith("task-") ? value : value.slice(-12);
}

function toPropertyName(id) {
  return id.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
}
