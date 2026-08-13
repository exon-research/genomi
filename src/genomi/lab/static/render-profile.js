"use strict";

import { createProfileEntityLookup } from "./profile-entities.js";
import {
  appendDefinition,
  array,
  elements,
  empty,
  formatTime,
  friendly,
  isObject,
  node,
  text,
  timestamp,
} from "./render-dom.js";

export function renderProfile(profile) {
  const artifacts = array(profile.source_artifacts);
  const specimens = array(profile.specimens);
  const assays = array(profile.assays);
  const coverage = array(profile.modality_coverage);
  const history = array(profile.observation_history);
  const observations = array(profile.observations);
  const lookup = createProfileEntityLookup({artifacts, specimens, assays});
  elements.profileVersionCount.textContent = history.length
    ? `${history.length} saved observation ${history.length === 1 ? "revision" : "revisions"}. Superseded revisions remain in local history.`
    : "No profile revisions yet.";
  renderProfileSelectors(artifacts, specimens, assays);
  renderObservationHistory(history, observations, lookup);
  renderCompactRecords(
    elements.sourceArtifactList,
    artifacts,
    "No source records yet.",
    (item) => [
      text(item.title) || "Untitled source record",
      [friendly(text(item.source_type)), text(item.source_identifier), formatTime(text(item.issued_at))].filter(Boolean).join(" · "),
    ]
  );
  renderCompactRecords(
    elements.specimenList,
    specimens,
    "No specimens yet.",
    (item) => [
      friendly(text(item.specimen_type)) || "Specimen",
      [text(item.body_site), friendly(text(item.tumor_normal_role)), formatTime(text(item.collected_at))].filter(Boolean).join(" · "),
      profileEntityFacts([
        ["Source record", profileArtifactLabel(lookup, item.artifact_id)],
      ]),
    ]
  );
  renderCompactRecords(
    elements.assayList,
    assays,
    "No assays yet.",
    (item) => [
      friendly(text(item.assay_type)) || "Molecular assay",
      [text(item.laboratory), text(item.platform), text(item.genome_build)].filter(Boolean).join(" · "),
      profileEntityFacts([
        ["Specimen", profileSpecimenLabel(lookup, item.specimen_id)],
        ["Source record", profileArtifactLabel(
          lookup,
          item.artifact_id || linkedSpecimenArtifactId(lookup, item.specimen_id)
        )],
        ["Examined", reportedDescription(item.assay_scope)],
        ["Detection limits", reportedDescription(item.detection_limits)],
      ]),
    ]
  );
  renderCompactRecords(
    elements.coverageList,
    coverage,
    "No modality coverage recorded.",
    (item) => [
      friendly(text(item.modality)) || "Profile modality",
      friendly(text(item.coverage_state)) || "Coverage not recorded",
    ]
  );
  renderObservations(observations, lookup);
}

function profileArtifactLabel(lookup, value) {
  const artifact = lookup.artifact(value);
  return artifact ? text(artifact.title) || friendly(text(artifact.source_type)) : "";
}

function profileSpecimenLabel(lookup, value) {
  const specimen = lookup.specimen(value);
  return specimen
    ? [friendly(text(specimen.specimen_type)) || "Specimen", text(specimen.body_site)].filter(Boolean).join(" · ")
    : "";
}

function profileAssayLabel(lookup, value) {
  const assay = lookup.assay(value);
  return assay
    ? [friendly(text(assay.assay_type)) || "Molecular assay", text(assay.laboratory)].filter(Boolean).join(" · ")
    : "";
}

function linkedSpecimenArtifactId(lookup, value) {
  const specimen = lookup.specimen(value);
  return specimen ? text(specimen.artifact_id) : "";
}

function reportedDescription(value) {
  if (typeof value === "string") return value.trim();
  if (!isObject(value)) return "";
  return text(value.reported_description || value.description).trim();
}

function profileEntityFacts(definitions) {
  const visible = definitions.filter(([_label, value]) => text(value));
  if (!visible.length) return null;
  const facts = node("dl", "", "profile-entity-facts");
  visible.forEach(([label, value]) => appendDefinition(facts, label, text(value)));
  return facts;
}

function renderProfileSelectors(artifacts, specimens, assays) {
  const artifactSelects = [
    elements.observationArtifact,
    elements.observationEditArtifact,
    elements.specimenArtifact,
    elements.assayArtifact,
  ];
  artifactSelects.forEach((select) => populateEntitySelect(
    select,
    artifacts,
    "artifact_id",
    (item) => [text(item.title) || "Untitled source record", text(item.source_identifier)].filter(Boolean).join(" · "),
    "No linked source record"
  ));
  [elements.observationSpecimen, elements.observationEditSpecimen, elements.assaySpecimen].forEach((select) => populateEntitySelect(
    select,
    specimens,
    "specimen_id",
    (item) => [friendly(text(item.specimen_type)) || "Specimen", text(item.body_site), friendly(text(item.tumor_normal_role))].filter(Boolean).join(" · "),
    "No linked specimen"
  ));
  [elements.observationAssay, elements.observationEditAssay].forEach((select) => populateEntitySelect(
    select,
    assays,
    "assay_id",
    (item) => [friendly(text(item.assay_type)) || "Molecular assay", text(item.laboratory)].filter(Boolean).join(" · "),
    "No linked assay"
  ));
}

function populateEntitySelect(target, records, idField, describe, placeholder) {
  const previousValue = target.value;
  const placeholderOption = node("option", placeholder);
  placeholderOption.value = "";
  const options = records.map((record) => {
    const option = node("option", describe(record));
    option.value = text(record[idField]);
    return option;
  }).filter((option) => option.value);
  target.replaceChildren(placeholderOption, ...options);
  target.value = options.some((option) => option.value === previousValue) ? previousValue : "";
}

function renderObservationHistory(history, currentObservations, lookup) {
  if (!history.length) {
    elements.observationHistoryList.replaceChildren(node("p", "No observation revisions yet.", "empty-row"));
    return;
  }
  const currentIds = new Set(currentObservations.map((item) => text(item.observation_revision_id)));
  const grouped = new Map();
  history.forEach((revision) => {
    const logicalId = text(revision.logical_observation_id) || text(revision.observation_revision_id);
    if (!grouped.has(logicalId)) grouped.set(logicalId, []);
    grouped.get(logicalId).push(revision);
  });
  const groups = [...grouped.values()].map((revisions) => revisions.sort(
    (left, right) => timestamp(right.created_at) - timestamp(left.created_at)
  )).sort((left, right) => timestamp(right[0] && right[0].created_at) - timestamp(left[0] && left[0].created_at));
  elements.observationHistoryList.replaceChildren(...groups.map((revisions) => {
    const latest = revisions[0] || {};
    const group = node("details", "", "revision-group");
    const summary = node(
      "summary",
      `${text(latest.label) || "Untitled observation"} · ${revisions.length} ${revisions.length === 1 ? "revision" : "revisions"}`
    );
    const list = node("ol", "", "revision-list");
    list.append(...revisions.map((revision) => {
      const isCurrent = currentIds.has(text(revision.observation_revision_id));
      const item = node("li", "", "revision-row");
      const copy = document.createElement("div");
      copy.append(
        node("strong", text(revision.label) || "Untitled observation"),
        node("span", [
          friendly(text(revision.modality)),
          friendly(text(revision.assertion_status)),
          formatTime(text(revision.created_at)),
        ].filter(Boolean).join(" · ")),
        observationTrace(revision, lookup)
      );
      item.append(copy, node("span", isCurrent ? "Current" : "Superseded", `revision-state${isCurrent ? " is-current" : ""}`));
      return item;
    }));
    group.append(summary, list);
    return group;
  }));
}

export function renderCompactRecords(target, records, emptyMessage, describe) {
  if (!records.length) {
    target.replaceChildren(empty(emptyMessage));
    return;
  }
  target.replaceChildren(...records.map((record) => {
    const [title, detail, extra] = describe(record);
    const item = node("li", "", "record compact-record");
    const copy = document.createElement("div");
    copy.append(node("strong", title), node("span", detail || "No additional details"));
    if (extra) copy.append(extra);
    item.append(copy);
    return item;
  }));
}

function renderObservations(observations, lookup) {
  elements.observationCount.textContent = String(observations.length);
  if (!observations.length) {
    elements.observationList.replaceChildren(empty("No profile observations yet."));
    return;
  }
  const rows = observations.map((observation) => {
    const item = node("li", "", "record");
    const copy = document.createElement("div");
    copy.append(
      node("strong", text(observation.label) || "Untitled observation"),
      node("span", [friendly(text(observation.modality)), friendly(text(observation.assertion_status)), friendly(text(observation.verification_state))].filter(Boolean).join(" · ")),
      observationTrace(observation, lookup)
    );
    const actions = node("div", "", "record-actions");
    actions.append(node("span", friendly(text(observation.coverage_state)) || "Observed", "tag"));
    const review = node("button", "Review / correct", "tertiary-button observation-review-button");
    review.type = "button";
    review.dataset.observationRevisionId = text(observation.observation_revision_id);
    actions.append(review);
    item.append(copy, actions);
    return item;
  });
  elements.observationList.replaceChildren(...rows);
}

export function renderObservationEditor(observation) {
  elements.observationEditModality.textContent = `Type: ${friendly(text(observation.modality)) || "Observation"}`;
  elements.observationEditLabel.value = text(observation.label);
  elements.observationEditAssertionStatus.value = text(observation.assertion_status) || "present";
  elements.observationEditRecordAssertion.checked = text(observation.source_class) === "issued_record";
  setSelectValue(elements.observationEditArtifact, observation.artifact_id);
  setSelectValue(elements.observationEditSpecimen, observation.specimen_id);
  setSelectValue(elements.observationEditAssay, observation.assay_id);
  elements.observationEditReportedVariant.value = text(observation.reported_variant);
  elements.observationEditGene.value = text(observation.gene);
  elements.observationEditor.hidden = false;
  elements.observationEditLabel.focus();
}

export function hideObservationEditor() {
  elements.observationEditor.hidden = true;
  elements.observationEditForm.reset();
  elements.observationEditModality.textContent = "";
  elements.observationEditLinkHelp.textContent = "Review the linked evidence before saving this correction.";
}

function setSelectValue(target, value) {
  const candidate = text(value);
  target.value = [...target.options].some((option) => option.value === candidate) ? candidate : "";
}

function observationTrace(observation, lookup) {
  const details = document.createElement("details");
  details.className = "record-trace";
  details.append(node("summary", "View source and immutable revision"));
  const facts = node("dl", "", "record-trace-facts");
  appendDefinition(facts, "Profile revision", text(observation.observation_revision_id) || "Not recorded");
  appendDefinition(
    facts,
    "Source",
    text(observation.source_identifier) || friendly(text(observation.source_class)) || "Not recorded"
  );
  if (observation.artifact_id) {
    appendDefinition(facts, "Source record", profileArtifactLabel(lookup, observation.artifact_id) || "Linked source record");
  }
  if (observation.specimen_id) {
    appendDefinition(facts, "Specimen", profileSpecimenLabel(lookup, observation.specimen_id) || "Linked specimen");
  }
  if (observation.assay_id) {
    appendDefinition(facts, "Assay", profileAssayLabel(lookup, observation.assay_id) || "Linked assay");
  }
  details.append(facts);
  return details;
}
