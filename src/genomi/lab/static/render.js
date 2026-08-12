"use strict";

export const elements = {};

export function collectElements() {
  const ids = [
    "local-status", "local-status-text", "global-alert", "global-alert-message", "alert-dismiss",
    "profile-select", "create-profile-panel", "create-profile-form", "profile-name", "empty-create-button",
    "no-profile-state", "profile-workspace", "workspace-title", "profile-meta", "version-label",
    "genome-readiness-pill", "consent-readiness-pill", "tracker-context", "tracker-genome",
    "tracker-finding", "tracker-investigate", "context-step", "genome-step", "finding-step",
    "investigate-step", "context-step-state", "genome-step-state", "finding-step-state",
    "investigate-step-state", "investigation-question", "health-fact-form", "fact-count",
    "health-fact-list", "genome-ready-card", "genome-ready-detail", "genome-upload-form",
    "genome-file", "file-picker-title", "file-picker-help", "upload-limit-label", "upload-button",
    "upload-progress-wrap", "upload-progress", "upload-status", "finding-form", "finding-count",
    "finding-list", "consent-form", "consent-purpose", "consent-approved", "consent-status",
    "consent-button", "copy-question-button", "investigation-form", "investigation-finding",
    "investigation-button", "run-readiness-title", "run-readiness-detail", "investigation-count",
    "investigation-list", "brief-section", "brief-title", "brief-question", "brief-observation-text",
    "brief-finding", "brief-health-context", "confirmation-list", "brief-boundary", "brief-evidence",
    "activity-status",
  ];
  ids.forEach((id) => {
    const node = document.getElementById(id);
    if (!node) throw new Error(`Required portal element is missing: ${id}`);
    elements[toPropertyName(id)] = node;
  });
  elements.createProfileButton = elements.createProfileForm.querySelector("button[type='submit']");
  elements.healthFactButton = elements.healthFactForm.querySelector("button[type='submit']");
  elements.findingButton = elements.findingForm.querySelector("button[type='submit']");
}

export function renderProductMetadata(payload) {
  const version = stringValue(payload.version);
  elements.versionLabel.textContent = version
    ? `GenomiLab ${version} · developer preview`
    : "GenomiLab developer preview";
  const intake = isObject(payload.intake) ? payload.intake : {};
  const maximum = numberValue(intake.maximum_bytes);
  if (maximum > 0) elements.uploadLimitLabel.textContent = `Maximum file size: ${formatBytes(maximum)}.`;
}

export function renderProfileOptions(profiles, currentProfileId, uploading) {
  const fragment = document.createDocumentFragment();
  if (!profiles.length) {
    fragment.append(createOption("", "No profiles yet"));
  } else {
    profiles.forEach((profile) => {
      const id = stringValue(profile.profile_id);
      if (id) fragment.append(createOption(id, stringValue(profile.display_name) || "Unnamed workspace"));
    });
  }
  elements.profileSelect.replaceChildren(fragment);
  elements.profileSelect.disabled = profiles.length === 0 || uploading;
  if (currentProfileId && profileIdInList(currentProfileId, profiles)) {
    elements.profileSelect.value = currentProfileId;
  }
}

export function renderReadiness(
  profile,
  facts,
  findings,
  investigations,
  genomeReady,
  accessApproved,
  uploadBusy
) {
  elements.genomeReadinessPill.textContent = genomeReady ? "Genome ready" : "Genome not added";
  elements.genomeReadinessPill.classList.toggle("is-ready", genomeReady);
  elements.consentReadinessPill.textContent = accessApproved ? "Session access approved" : "Access not approved";
  elements.consentReadinessPill.classList.toggle("is-ready", accessApproved);

  setStepState(elements.contextStep, elements.trackerContext, facts.length > 0);
  elements.contextStepState.textContent = facts.length ? `${facts.length} added` : "Optional";
  setStepState(elements.genomeStep, elements.trackerGenome, genomeReady);
  elements.genomeStepState.textContent = genomeReady ? "Ready" : "Required";
  setStepState(elements.findingStep, elements.trackerFinding, findings.length > 0);
  elements.findingStepState.textContent = findings.length ? `${findings.length} saved` : "Required";
  const completed = investigations.some((item) => isObject(item) && item.status === "completed");
  setStepState(elements.investigateStep, elements.trackerInvestigate, completed);
  elements.investigateStepState.textContent = completed ? "Complete" : accessApproved ? "Ready" : "Locked";

  elements.genomeReadyCard.hidden = !genomeReady;
  const uploadLabel = genomeReady ? "Replace genome" : "Import genome";
  elements.uploadButton.dataset.defaultLabel = uploadLabel;
  if (!uploadBusy) elements.uploadButton.textContent = uploadLabel;
  if (genomeReady) {
    const build = stringValue(profile.genome.genome_build);
    const readiness = formatIdentifier(profile.genome.readiness || "ready");
    elements.genomeReadyDetail.textContent = build
      ? `${build} · ${readiness} · imported ${formatDate(profile.genome.imported_at)}`
      : `${readiness} · imported ${formatDate(profile.genome.imported_at)}`;
  }

  const statusParts = elements.consentStatus.querySelectorAll("span");
  elements.consentStatus.classList.toggle("is-approved", accessApproved);
  if (statusParts.length >= 2) {
    statusParts[0].textContent = accessApproved ? "✓" : "○";
    statusParts[1].textContent = accessApproved ? "Approved for this session" : "Not approved for this session";
  }
}

export function renderHealthFacts(facts) {
  elements.factCount.textContent = pluralize(facts.length, "fact");
  if (!facts.length) {
    elements.healthFactList.replaceChildren(createListEmpty("No health context added yet."));
    return;
  }
  const rows = facts.map((fact) => {
    const item = document.createElement("li");
    const text = createElement("div", "record-copy");
    text.append(
      createElement("span", "record-primary", stringValue(fact.label) || "Unnamed health fact"),
      createElement(
        "span", "record-secondary",
        [formatIdentifier(fact.kind), formatIdentifier(fact.assertion_status), onsetLabel(fact.onset)]
          .filter(Boolean).join(" · ")
      )
    );
    item.append(text, createElement("span", "record-badge", "User confirmed"));
    return item;
  });
  elements.healthFactList.replaceChildren(...rows);
}

export function renderFindings(findings, preferredFindingId = "") {
  elements.findingCount.textContent = pluralize(findings.length, "finding");
  if (!findings.length) {
    elements.findingList.replaceChildren(createListEmpty("No reported findings added yet."));
    elements.investigationFinding.replaceChildren(createOption("", "Add a reported rsID first"));
    return;
  }
  const rows = [];
  const options = [];
  findings.forEach((finding) => {
    const variant = stringValue(finding.variant) || "Unspecified variant";
    const gene = stringValue(finding.gene);
    const classification = stringValue(finding.reported_classification) || "Classification not provided";
    const source = stringValue(finding.source_label);
    const item = document.createElement("li");
    const text = createElement("div", "record-copy");
    text.append(
      createElement("span", "record-primary", gene ? `${variant} · ${gene}` : variant),
      createElement("span", "record-secondary", [classification, source].filter(Boolean).join(" · "))
    );
    item.append(text, createElement("span", "record-badge", formatNormalization(finding.normalization_state)));
    rows.push(item);
    const id = stringValue(finding.finding_id);
    if (id) options.push(createOption(id, gene ? `${variant} — ${gene}` : variant));
  });
  elements.findingList.replaceChildren(...rows);
  const previous = preferredFindingId || elements.investigationFinding.value;
  elements.investigationFinding.replaceChildren(...options);
  if (previous && options.some((option) => option.value === previous)) {
    elements.investigationFinding.value = previous;
  }
}

export function renderInvestigations(investigations) {
  const completed = investigations.filter((item) => isObject(item) && item.status === "completed");
  elements.investigationCount.textContent = pluralize(completed.length, "brief");
  if (!investigations.length) {
    elements.investigationList.replaceChildren(createListEmpty("No investigations run yet."));
    return;
  }
  const rows = investigations.map((investigation) => {
    const item = document.createElement("li");
    const text = createElement("div", "record-copy");
    text.append(
      createElement("span", "record-primary", stringValue(investigation.question) || "Investigation"),
      createElement(
        "span", "record-secondary",
        `${formatIdentifier(investigation.status)} · ${formatDate(investigation.updated_at)}`
      )
    );
    item.append(text);
    if (isObject(investigation.brief) && investigation.brief.status === "research_observation") {
      const button = createElement("button", "record-action", "View brief");
      button.type = "button";
      button.addEventListener("click", () => {
        renderBrief(investigation.brief);
        elements.briefSection.focus();
      });
      item.append(button);
    } else {
      item.append(createElement("span", "record-badge", formatIdentifier(investigation.status)));
    }
    return item;
  });
  elements.investigationList.replaceChildren(...rows);
}

export function renderBrief(brief) {
  if (!isObject(brief)) {
    elements.briefSection.hidden = true;
    return;
  }
  elements.briefTitle.textContent = stringValue(brief.title) || "Investigation brief";
  elements.briefQuestion.textContent = stringValue(brief.question);
  elements.briefObservationText.textContent = stringValue(brief.observation) || "No research observation was returned.";

  const finding = isObject(brief.reported_finding) ? brief.reported_finding : {};
  const definitionRows = [
    ["Variant", finding.variant], ["Gene", finding.gene],
    ["Reported classification", finding.reported_classification], ["Reported source", finding.source_label],
    ["Normalization", formatNormalization(finding.normalization_state)],
  ];
  const definitions = [];
  definitionRows.forEach(([label, value]) => {
    definitions.push(createElement("dt", "", label));
    definitions.push(createElement("dd", "", stringValue(value) || "Not provided"));
  });
  elements.briefFinding.replaceChildren(...definitions);

  const healthContext = Array.isArray(brief.health_context) ? brief.health_context : [];
  const healthRows = healthContext.length
    ? healthContext.map((fact) => createElement(
        "li", "",
        `${stringValue(fact.label) || "Health fact"} — ${formatIdentifier(fact.kind)}, ${formatIdentifier(fact.assertion_status)}`
      ))
    : [createElement("li", "evidence-empty", "No health facts were included in this brief.")];
  elements.briefHealthContext.replaceChildren(...healthRows);

  const confirmation = Array.isArray(brief.confirmation_needed) ? brief.confirmation_needed : [];
  elements.confirmationList.replaceChildren(...(confirmation.length
    ? confirmation.map((item) => createElement("li", "", stringValue(item)))
    : [createElement("li", "", "Clinical confirmation is required before health decisions.")]));
  elements.briefBoundary.textContent = stringValue(brief.clinical_boundary)
    || "Research support only. This brief is not a diagnosis or treatment recommendation.";
  elements.briefEvidence.replaceChildren(renderStructuredValue(brief.evidence, 0));
  elements.briefSection.hidden = false;
}

function renderStructuredValue(value, depth) {
  if (depth > 7) return createElement("span", "evidence-empty", "Additional nested detail omitted.");
  if (value === null || value === undefined || value === "") {
    return createElement("span", "evidence-empty", "Not available");
  }
  if (Array.isArray(value)) {
    if (!value.length) return createElement("span", "evidence-empty", "None returned");
    const list = document.createElement("ul");
    value.slice(0, 100).forEach((item) => {
      const row = document.createElement("li");
      row.append(renderStructuredValue(item, depth + 1));
      list.append(row);
    });
    if (value.length > 100) {
      list.append(createElement("li", "evidence-empty", `${value.length - 100} additional items omitted.`));
    }
    return list;
  }
  if (isObject(value)) {
    const entries = Object.entries(value);
    if (!entries.length) return createElement("span", "evidence-empty", "No details returned");
    const list = document.createElement("dl");
    entries.slice(0, 100).forEach(([key, item]) => {
      list.append(createElement("dt", "", friendlyKey(key)), appendToElement("dd", renderStructuredValue(item, depth + 1)));
    });
    if (entries.length > 100) {
      list.append(
        createElement("dt", "", "Additional fields"),
        createElement("dd", "evidence-empty", `${entries.length - 100} fields omitted.`)
      );
    }
    return list;
  }
  if (typeof value === "boolean") return document.createTextNode(value ? "Yes" : "No");
  return document.createTextNode(String(value));
}

export function resetFilePicker() {
  elements.genomeFile.setCustomValidity("");
  elements.filePickerTitle.textContent = "Choose a VCF or gVCF";
  elements.filePickerHelp.textContent = "Uncompressed .vcf, .g.vcf, or .gvcf";
}

export function showUploadProgress(message, complete) {
  elements.uploadProgressWrap.hidden = false;
  elements.uploadStatus.textContent = message;
  if (complete) elements.uploadProgress.value = 100;
  else elements.uploadProgress.removeAttribute("value");
}

export function setLocalStatus(message, status) {
  elements.localStatusText.textContent = message;
  elements.localStatus.classList.toggle("is-ready", status === "ready");
  elements.localStatus.classList.toggle("is-error", status === "error");
}

export function setActivity(message) {
  elements.activityStatus.textContent = message;
}

export function showAlert(message, kind) {
  elements.globalAlertMessage.textContent = message;
  elements.globalAlert.classList.toggle("is-success", kind === "success");
  elements.globalAlert.classList.toggle("is-error", kind === "error");
  elements.globalAlert.hidden = false;
}

export function hideAlert() {
  elements.globalAlert.hidden = true;
  elements.globalAlert.classList.remove("is-success", "is-error");
  elements.globalAlertMessage.textContent = "";
}

export function showError(error, prefix) {
  const message = error instanceof Error ? error.message : "An unexpected local error occurred.";
  showAlert(`${prefix}: ${message}`, "error");
}

export function profileIdInList(candidate, profiles) {
  const id = stringValue(candidate);
  return profiles.some((profile) => isObject(profile) && profile.profile_id === id) ? id : "";
}

export function formatDate(value) {
  const raw = stringValue(value);
  if (!raw) return "date unavailable";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "date unavailable";
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  }).format(date);
}

export function formatBytes(value) {
  const bytes = numberValue(value);
  if (bytes < 1024) return `${bytes} bytes`;
  const units = ["KiB", "MiB", "GiB"];
  let amount = bytes;
  let unit = "bytes";
  for (let index = 0; index < units.length && amount >= 1024; index += 1) {
    amount /= 1024;
    unit = units[index];
  }
  return `${amount.toFixed(amount >= 10 ? 0 : 1)} ${unit}`;
}

export function stringValue(value) {
  return typeof value === "string" ? value : value === null || value === undefined ? "" : String(value);
}

export function numberValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

export function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function setStepState(card, tracker, complete) {
  card.classList.toggle("is-complete", complete);
  tracker.classList.toggle("is-complete", complete);
  const number = tracker.querySelector("span");
  if (!number) return;
  if (!number.dataset.stepNumber) number.dataset.stepNumber = number.textContent;
  number.textContent = complete ? "✓" : number.dataset.stepNumber;
}

function createElement(tagName, className = "", text = "") {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (text !== "") node.textContent = String(text);
  return node;
}

function appendToElement(tagName, child) {
  const node = document.createElement(tagName);
  node.append(child);
  return node;
}

function createOption(value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  return option;
}

function createListEmpty(message) {
  return createElement("li", "list-empty", message);
}

function formatIdentifier(value) {
  const text = stringValue(value).replaceAll("_", " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "Unknown";
}

function formatNormalization(value) {
  const labels = {
    rsid_ready: "rsID ready",
    exact_genomic_allele_ready: "Allele ready",
    needs_review: "Needs review",
  };
  return labels[stringValue(value)] || formatIdentifier(value);
}

function friendlyKey(key) {
  const labels = {
    answer_readiness: "Answer readiness", defaults_applied: "Defaults applied",
    evidence_envelope: "Evidence envelope", finding_state: "Finding state",
    negative_inference: "Negative-inference boundary", public_context: "Public context",
    query_scope: "Query scope", sample_context: "Personal genome context",
  };
  return labels[key] || formatIdentifier(key);
}

function onsetLabel(value) {
  const onset = stringValue(value);
  return onset ? `Onset: ${onset}` : "";
}

function pluralize(count, singular) {
  return `${count} ${count === 1 ? singular : `${singular}s`}`;
}

function toPropertyName(id) {
  return id.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
}
