"use strict";

import { array, elements, empty, formatTime, friendly, isObject, node, text } from "./render-dom.js";
import {
  citedEvidenceRecords,
  claimSourceFamilies,
  claimTraceDetails,
  evidenceCurrencyNotes,
  evidenceHeadline,
  evidenceReadiness,
  evidenceWarnings,
  sourceRecordList,
} from "./render-evidence.js";

export function renderBriefs(versions, investigation = {}, profile = {}) {
  elements.briefVersionCount.textContent = versions.length
    ? `${versions.length} ${versions.length === 1 ? "version" : "versions"}`
    : "No versions";
  if (!versions.length) {
    elements.briefList.replaceChildren(node("p", "The underlying agent has not published a brief yet.", "empty-row"));
    return;
  }
  const evidenceById = new Map(
    array(investigation.evidence_records).map((record) => [text(record.evidence_record_id), record])
  );
  const hypothesesById = new Map(
    array(investigation.hypotheses).map((record) => [text(record.hypothesis_id), record])
  );
  const profileByRevisionId = new Map(
    array(profile.observations).map((record) => [text(record.observation_revision_id), record])
  );
  const artifactsById = new Map(
    array(profile.source_artifacts).map((record) => [text(record.artifact_id), record])
  );
  elements.briefList.replaceChildren(...versions.map((version, index) => {
    const brief = isObject(version.brief) ? version.brief : {};
    const details = document.createElement("details");
    details.className = "brief-version";
    const currentBriefVersionId = isObject(investigation.current_brief_version)
      ? text(investigation.current_brief_version.brief_version_id)
      : "";
    const current = currentBriefVersionId === text(version.brief_version_id);
    details.open = current;
    const summary = document.createElement("summary");
    const title = document.createElement("span");
    title.append(
      node("strong", text(brief.title) || "Investigation Brief"),
      node(
        "small",
        `Version ${text(version.version) || index + 1} · ${current ? "Current basis" : "Historical basis"} · ${formatTime(text(version.created_at))}`
      )
    );
    const stage = friendly(text(brief.clinical_stage)) || "Clinical stage not recorded";
    const stageBadge = node("span", stage, "brief-stage");
    stageBadge.setAttribute("aria-label", `Clinical stage: ${stage}`);
    summary.append(title, stageBadge);
    const body = node("div", "", "brief-body");
    const claims = array(brief.claims);
    const anchoredEntries = briefAnchoredEntries(brief);
    if (current) {
      body.append(renderBriefActions(details, investigation, version));
    }
    body.append(briefSection(
      "Question and scope",
      [
        `Question: ${text(investigation.question) || "The investigation question was not included."}`,
        `Scope: ${text(investigation.disease_scope) || "No narrower disease scope was supplied."}`,
      ],
      "brief-question-scope"
    ));
    body.append(renderTimeline(
      brief,
      evidenceById,
      profileByRevisionId,
      artifactsById
    ));
    body.append(renderBriefAxes(brief));
    if (brief.summary) body.append(node("p", text(brief.summary), "brief-summary"));
    body.append(renderClaimSection(
      "What was observed",
      claims.filter((claim) => text(claim.claim_role) === "observation"),
      evidenceById,
      "No research observations were included in this version."
    ));
    body.append(renderClaimSection(
      "What the observations could mean",
      claims.filter((claim) => text(claim.claim_role) === "candidate_hypothesis"),
      evidenceById,
      "No candidate interpretation was included in this version."
    ));
    body.append(renderEvidenceClaimSection(anchoredEntries, evidenceById));
    body.append(renderGapsAndConflicts(brief, anchoredEntries, evidenceById, hypothesesById));
    body.append(renderLimitsSection(brief, claims, evidenceById));
    body.append(briefSection(
      "Clinical or laboratory confirmation needed",
      array(brief.confirmation_needs),
      "brief-confirmation",
      "No specific confirmation request was included in this version."
    ));
    body.append(renderClinicianQuestions(brief, evidenceById, hypothesesById));
    body.append(renderPatientRecordReferences(
      anchoredEntries,
      profileByRevisionId,
      artifactsById
    ));
    body.append(renderCurrencyAndChanges(brief, anchoredEntries, evidenceById, version));
    details.append(summary, body);
    return details;
  }));
}

function renderBriefAxes(brief) {
  const section = node("section", "", "brief-axes");
  const modalityAxis = node("div", "", "brief-axis");
  modalityAxis.append(node("span", "Evidence-source badges (separate from clinical stage)", "brief-axis-label"));
  const badges = node("div", "", "modality-badges");
  const values = array(brief.modality_badges);
  if (values.length) {
    badges.append(...values.map((value) => node("span", friendly(text(value)), "modality-badge")));
  } else {
    badges.append(node("span", "No evidence-source badges recorded", "modality-badge modality-badge-empty"));
  }
  modalityAxis.append(badges);
  section.append(modalityAxis);
  return section;
}

function renderBriefActions(details, investigation, version) {
  const actions = node("div", "", "brief-actions");
  actions.id = "brief-export-actions";
  const printButton = node("button", "Print / Save PDF", "secondary-button brief-print-button");
  printButton.type = "button";
  printButton.addEventListener("click", () => printDoctorBrief(details));
  const downloadButton = node("button", "Download doctor brief (.html)", "secondary-button brief-download-button");
  downloadButton.type = "button";
  downloadButton.addEventListener("click", () => {
    downloadDoctorBrief(details, investigation, version);
  });
  actions.append(printButton, downloadButton);
  return actions;
}

function renderTimeline(brief, evidenceById, profileByRevisionId, artifactsById) {
  const section = node("section", "", "brief-section brief-timeline");
  section.append(node("h4", "Chronology that changed the investigation"));
  const list = node("ol", "", "brief-timeline-list");
  const entries = array(brief.timeline);
  if (!entries.length) {
    list.append(empty("No grounded chronology was included in this version."));
  } else {
    list.append(...entries.map((entry) => {
      const item = node("li", "", "brief-timeline-entry");
      const citedObservations = array(entry.profile_revision_ids)
        .map((id) => profileByRevisionId.get(text(id)))
        .filter(Boolean);
      const citedRecords = array(entry.evidence_record_ids)
        .map((id) => evidenceById.get(text(id)))
        .filter(Boolean);
      const labels = citedObservations.map((observation) => {
        const artifact = artifactsById.get(text(observation.artifact_id));
        const date = artifact && text(artifact.issued_at);
        return [date, text(observation.label)].filter(Boolean).join(" — ");
      }).filter(Boolean);
      const evidenceLabels = citedRecords.map((record) => {
        const evidence = isObject(record.evidence) ? record.evidence : {};
        const envelope = isObject(record.evidence_envelope)
          ? record.evidence_envelope
          : isObject(evidence.evidence_envelope) ? evidence.evidence_envelope : {};
        return evidenceHeadline(envelope, record);
      }).filter(Boolean);
      item.append(
        node(
          "strong",
          labels.join("; ") || evidenceLabels.join("; ") || text(entry.statement) || "Grounded chronology entry"
        ),
        node("p", text(entry.statement) || "Chronology statement not recorded."),
        node("span", anchorDescription(entry)),
        claimTraceDetails(entry)
      );
      return item;
    }));
  }
  section.append(list);
  return section;
}

function renderClaimSection(title, claims, evidenceById, emptyMessage) {
  const section = node("section", "", "brief-section");
  section.append(node("h4", title));
  const list = node("ol", "", "brief-claims");
  if (claims.length) {
    list.append(...claims.map((claim) => briefClaim(claim, evidenceById)));
  } else {
    list.append(empty(emptyMessage));
  }
  section.append(list);
  return section;
}
function briefClaim(claim, evidenceById) {
  const item = document.createElement("li");
  const sources = claimSourceFamilies(claim, evidenceById);
  item.append(
    node("strong", text(claim.statement) || "Untitled research statement"),
    node("span", [anchorDescription(claim), sources].filter(Boolean).join(" · ")),
    claimTraceDetails(claim)
  );
  return item;
}

function renderEvidenceClaimSection(claims, evidenceById) {
  const section = node("section", "", "brief-section");
  section.append(node("h4", "Supporting evidence and counterevidence by source"));
  const citedIds = new Set(claims.flatMap((claim) => array(claim.evidence_record_ids).map(text)));
  const records = [...citedIds].map((id) => evidenceById.get(id)).filter(Boolean);
  const supportList = node("ul", "", "brief-evidence-list");
  if (records.length) {
    supportList.append(...records.map((record) => {
      const evidence = isObject(record.evidence) ? record.evidence : {};
      const envelope = isObject(record.evidence_envelope)
        ? record.evidence_envelope
        : isObject(evidence.evidence_envelope) ? evidence.evidence_envelope : {};
      const item = document.createElement("li");
      item.append(
        node("strong", friendly(text(record.source_family)) || "Evidence source"),
        node("span", `${evidenceHeadline(envelope, record)} · ${evidenceReadiness(envelope)}`),
        sourceRecordList(evidence)
      );
      return item;
    }));
  } else {
    supportList.append(empty("No evidence records were cited by this version."));
  }
  section.append(supportList);
  const counterClaims = claims.filter((claim) => text(claim.claim_role) === "counterevidence");
  const counter = node("div", "", "brief-subsection");
  counter.append(node("h5", "Counterevidence"));
  if (counterClaims.length) {
    const list = node("ul", "", "brief-claims");
    list.append(...counterClaims.map((claim) => briefClaim(claim, evidenceById)));
    counter.append(list);
  } else {
    counter.append(node("p", "No counterevidence claim was included in this version.", "brief-empty-copy"));
  }
  section.append(counter);
  return section;
}

function renderGapsAndConflicts(brief, anchoredEntries, evidenceById, hypothesesById) {
  const section = node("section", "", "brief-section brief-caution-section");
  section.append(node("h4", "Conflicts and open evidence gaps"));
  const list = node("ul", "", "brief-notes");
  array(brief.gap_ids).forEach((id) => {
    const gap = hypothesesById.get(text(id));
    list.append(node("li", gap ? text(gap.statement) : `Open gap ${text(id)}`));
  });
  const citedRecords = citedEvidenceRecords(anchoredEntries, evidenceById);
  citedRecords.forEach((record) => {
    evidenceWarnings(record).forEach((warning) => list.append(node("li", warning)));
  });
  if (!list.children.length) {
    list.append(node("li", "No conflicts or open evidence gaps were recorded in this version."));
  }
  section.append(list);
  return section;
}

function renderClinicianQuestions(brief, evidenceById, hypothesesById) {
  const section = node("section", "", "brief-section brief-clinician-questions");
  section.id = "brief-clinician-questions";
  section.append(node("h4", "Questions for the treating immunologist or clinical geneticist"));
  const list = node("ul", "", "brief-question-list");
  const questions = array(brief.clinician_questions);
  if (!questions.length) {
    list.append(empty("No case-specific clinician questions were included in this version."));
  } else {
    list.append(...questions.map((question) => {
      const item = node("li", "", "brief-question-item");
      const sources = claimSourceFamilies(question, evidenceById);
      const linked = [
        ...array(question.hypothesis_ids).map((id) => hypothesesById.get(text(id))),
        ...array(question.gap_ids).map((id) => hypothesesById.get(text(id))),
      ].filter(Boolean).map((record) => text(record.statement)).filter(Boolean);
      item.append(
        node("strong", text(question.question) || "Clinician question not recorded"),
        node("span", [anchorDescription(question), sources].filter(Boolean).join(" · ")),
        claimTraceDetails(question)
      );
      if (linked.length) {
        const linkedDetails = document.createElement("details");
        linkedDetails.className = "brief-question-context";
        linkedDetails.append(node("summary", "Why this question is linked to the case"));
        const linkedList = node("ul", "", "brief-question-links");
        linkedList.append(...linked.map((value) => node("li", value)));
        linkedDetails.append(linkedList);
        item.append(linkedDetails);
      }
      return item;
    }));
  }
  section.append(list);
  return section;
}

function renderPatientRecordReferences(anchoredEntries, profileByRevisionId, artifactsById) {
  const section = node("section", "", "brief-section brief-record-references");
  section.append(node("h4", "Original patient record references"));
  const revisionIds = new Set(
    anchoredEntries.flatMap((entry) => array(entry.profile_revision_ids).map(text))
  );
  const observations = [...revisionIds]
    .map((id) => profileByRevisionId.get(id))
    .filter(Boolean);
  const list = node("ul", "", "brief-record-list");
  if (!observations.length) {
    list.append(empty("No patient profile revision was cited by this version."));
  } else {
    list.append(...observations.map((observation) => {
      const item = node("li", "", "brief-record-reference");
      const artifact = artifactsById.get(text(observation.artifact_id));
      item.append(node("strong", text(observation.label) || "Cited profile observation"));
      if (artifact) {
        item.append(node(
          "span",
          [
            text(artifact.title) || "Registered source record",
            friendly(text(artifact.source_type)),
            text(artifact.issued_at) ? `Issued ${text(artifact.issued_at)}` : "",
          ].filter(Boolean).join(" · ")
        ));
        const trace = node("dl", "", "brief-record-trace");
        appendRecordTrace(trace, "Record ID", text(artifact.artifact_id));
        appendRecordTrace(trace, "SHA-256", text(artifact.local_file_sha256));
        appendRecordTrace(trace, "Profile revision", text(observation.observation_revision_id));
        item.append(trace);
      } else {
        item.append(node(
          "span",
          `Profile revision ${text(observation.observation_revision_id) || "not recorded"}; no issued source record was linked.`
        ));
      }
      return item;
    }));
  }
  section.append(list);
  return section;
}

function appendRecordTrace(target, label, value) {
  if (!value) return;
  target.append(node("dt", label), node("dd", value));
}

function renderLimitsSection(brief, claims, evidenceById) {
  const section = node("section", "", "brief-section brief-boundary");
  section.append(node("h4", "What the patient should not conclude"));
  const limitations = claims.filter((claim) => text(claim.claim_role) === "limitation");
  if (limitations.length) {
    const list = node("ul", "", "brief-claims");
    list.append(...limitations.map((claim) => briefClaim(claim, evidenceById)));
    section.append(list);
  }
  section.append(node(
    "p",
    text(brief.clinical_boundary) || "Research support only; this is not a diagnosis or treatment decision.",
    "clinical-boundary"
  ));
  return section;
}

function renderCurrencyAndChanges(brief, anchoredEntries, evidenceById, version) {
  const section = node("section", "", "brief-section");
  section.append(node("h4", "Evidence currency and change history"));
  const list = node("ul", "", "brief-notes");
  list.append(node(
    "li",
    `Agent summary: ${text(brief.change_summary) || "No change summary was recorded."}`
  ));
  persistedBriefDiffNotes(version).forEach((value) => list.append(node("li", value)));
  const currency = citedEvidenceRecords(anchoredEntries, evidenceById).flatMap(evidenceCurrencyNotes);
  if (currency.length) {
    currency.forEach((value) => list.append(node("li", value)));
  } else {
    list.append(node("li", "No source currency check was recorded for cited evidence."));
  }
  list.append(node("li", `Brief saved ${formatTime(text(version.created_at))}.`));
  section.append(list);
  return section;
}

function persistedBriefDiffNotes(version) {
  const diff = isObject(version.diff) ? version.diff : {};
  if (!text(version.prior_brief_version_id)) {
    return ["Saved comparison: this is the first brief version."];
  }

  const notes = [];
  const molecular = isObject(diff.patient_molecular_snapshot)
    ? diff.patient_molecular_snapshot
    : {};
  notes.push(
    molecular.changed
      ? "Saved comparison: the patient molecular profile basis changed since the prior brief."
      : "Saved comparison: the patient molecular profile basis is unchanged since the prior brief."
  );

  const evidence = isObject(diff.evidence_snapshot) ? diff.evidence_snapshot : {};
  const evidenceIds = isObject(evidence.evidence_record_ids)
    ? evidence.evidence_record_ids
    : {};
  const evidenceAdded = array(evidenceIds.added).length;
  const evidenceRemoved = array(evidenceIds.removed).length;
  notes.push(
    `Evidence basis: ${evidenceAdded} ${evidenceAdded === 1 ? "record" : "records"} added and `
      + `${evidenceRemoved} ${evidenceRemoved === 1 ? "record" : "records"} removed.`
  );

  if (diff.clinical_stage_changed === true) {
    notes.push("The research stage label changed since the prior brief.");
  }
  appendTypedDiffNote(notes, diff.modality_badges, "Evidence-source badges");
  appendTypedDiffNote(notes, diff.hypothesis_ids, "Candidate or uncertainty records");
  appendTypedDiffNote(notes, diff.gap_ids, "Open evidence gaps");
  return notes;
}

function appendTypedDiffNote(notes, value, label) {
  const change = isObject(value) ? value : {};
  const added = array(change.added).length;
  const removed = array(change.removed).length;
  if (!added && !removed) return;
  notes.push(
    `${label}: ${added} added and ${removed} removed since the prior brief.`
  );
}

function briefSection(title, values, className, emptyMessage = "Nothing was recorded for this section.") {
  const section = node("section", "", `brief-section ${className}`);
  section.append(node("h4", title));
  const list = node("ul", "", "brief-notes");
  const entries = array(values).map(text).filter(Boolean);
  if (entries.length) {
    list.append(...entries.map((value) => node("li", value)));
  } else {
    list.append(node("li", emptyMessage));
  }
  section.append(list);
  return section;
}

function briefAnchoredEntries(brief) {
  return [
    ...array(brief.claims),
    ...array(brief.timeline),
    ...array(brief.clinician_questions),
  ];
}

function anchorDescription(entry) {
  const evidenceCount = array(entry.evidence_record_ids).length;
  const profileCount = array(entry.profile_revision_ids).length;
  const hypothesisCount = array(entry.hypothesis_ids).length;
  const gapCount = array(entry.gap_ids).length;
  return [
    `${evidenceCount} evidence ${evidenceCount === 1 ? "anchor" : "anchors"}`,
    `${profileCount} profile ${profileCount === 1 ? "anchor" : "anchors"}`,
    hypothesisCount ? `${hypothesisCount} ${hypothesisCount === 1 ? "hypothesis" : "hypotheses"}` : "",
    gapCount ? `${gapCount} ${gapCount === 1 ? "gap" : "gaps"}` : "",
  ].filter(Boolean).join(" · ");
}

function printDoctorBrief(details) {
  const wasOpen = details.open;
  const cleanup = () => {
    details.classList.remove("brief-print-target");
    document.body.classList.remove("doctor-brief-printing");
    details.open = wasOpen;
  };
  details.open = true;
  details.classList.add("brief-print-target");
  document.body.classList.add("doctor-brief-printing");
  globalThis.addEventListener("afterprint", cleanup, {once: true});
  try {
    globalThis.print();
  } catch (error) {
    cleanup();
    throw error;
  }
  globalThis.setTimeout(cleanup, 0);
}

function downloadDoctorBrief(details, investigation, version) {
  const html = buildDoctorBriefHtml(details, investigation, version);
  const blob = new Blob([html], {type: "text/html;charset=utf-8"});
  const objectUrl = globalThis.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = doctorBriefFilename(investigation, version);
  link.rel = "noopener";
  try {
    link.click();
  } finally {
    globalThis.setTimeout(() => globalThis.URL.revokeObjectURL(objectUrl), 0);
  }
}

export function buildDoctorBriefHtml(details, investigation = {}, version = {}) {
  const exportDocument = document.implementation.createHTMLDocument("GenomiLab doctor brief");
  exportDocument.documentElement.lang = "en";
  const viewport = exportDocument.createElement("meta");
  viewport.name = "viewport";
  viewport.content = "width=device-width, initial-scale=1";
  const style = exportDocument.createElement("style");
  style.textContent = DOCTOR_BRIEF_EXPORT_CSS;
  exportDocument.head.append(viewport, style);

  const main = exportDocument.createElement("main");
  main.className = "doctor-brief-export";
  const header = exportDocument.createElement("header");
  const brand = exportDocument.createElement("p");
  brand.className = "doctor-brief-brand";
  brand.textContent = "GenomiLab · Doctor brief";
  const heading = exportDocument.createElement("h1");
  heading.textContent = text(investigation.question) || "Investigation brief";
  const metadata = exportDocument.createElement("p");
  metadata.className = "doctor-brief-metadata";
  metadata.textContent = [
    `Version ${text(version.version) || "not recorded"}`,
    `Saved ${formatTime(text(version.created_at))}`,
  ].join(" · ");
  header.append(brand, heading, metadata);

  const clonedBrief = details.cloneNode(true);
  clonedBrief.open = true;
  clonedBrief.classList.add("brief-export-copy");
  clonedBrief.querySelectorAll("details").forEach((item) => {
    item.open = true;
  });
  clonedBrief.querySelectorAll(".brief-actions").forEach((item) => item.remove());
  main.append(header, clonedBrief);
  exportDocument.body.append(main);
  return `<!doctype html>\n${new XMLSerializer().serializeToString(exportDocument.documentElement)}`;
}

function doctorBriefFilename(investigation, version) {
  const question = text(investigation.question)
    .normalize("NFKD")
    .replace(/[^A-Za-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64)
    .toLowerCase() || "investigation";
  const versionLabel = text(version.version).replace(/[^0-9]/g, "") || "current";
  return `genomilab-${question}-v${versionLabel}-doctor-brief.html`;
}

const DOCTOR_BRIEF_EXPORT_CSS = `
:root { color-scheme: light; font-family: Georgia, serif; color: #18312d; background: white; }
body { margin: 0; background: white; }
.doctor-brief-export { max-width: 860px; margin: 0 auto; padding: 40px; }
.doctor-brief-export > header { padding-bottom: 20px; border-bottom: 2px solid #194f47; }
.doctor-brief-brand { margin: 0; color: #24665b; font: 700 12px/1.4 system-ui, sans-serif; letter-spacing: .08em; text-transform: uppercase; }
h1 { margin: 8px 0; font-size: 28px; }
.doctor-brief-metadata { margin: 0; color: #60716d; font: 12px/1.5 system-ui, sans-serif; }
.brief-export-copy { display: block; margin-top: 22px; border: 0; }
.brief-export-copy > summary { display: none; }
.brief-body { padding: 0; }
.brief-section, .brief-axes { padding: 14px 0; border-top: 1px solid #d7e0dd; }
.brief-question-scope { border-top: 0; }
h4 { margin: 0 0 8px; font-size: 16px; }
h5 { margin: 10px 0 6px; font: 700 12px/1.4 system-ui, sans-serif; }
p, li, dd, dt, span, strong, blockquote { overflow-wrap: anywhere; }
p, li, blockquote { font: 13px/1.55 system-ui, sans-serif; }
ol, ul { padding-left: 22px; }
.brief-stage, .modality-badge { display: inline-block; margin: 2px 4px 2px 0; padding: 4px 7px; border: 1px solid #b7d7ce; border-radius: 999px; font: 700 10px/1.3 system-ui, sans-serif; }
.clinical-boundary, .brief-boundary { color: #6f392f; background: #fff6f3; }
.brief-boundary, .brief-caution-section { padding: 12px; border-radius: 8px; }
.brief-caution-section { background: #fdf9f0; }
.claim-trace, .source-records { margin-top: 6px; }
.claim-trace summary { font: 700 11px/1.4 system-ui, sans-serif; }
.source-record-card, .brief-record-reference { margin: 7px 0; padding: 9px; border: 1px solid #d7e0dd; border-radius: 7px; }
.source-link { color: #175b51; }
.brief-record-trace { display: grid; grid-template-columns: auto 1fr; gap: 3px 8px; font: 10px/1.4 ui-monospace, monospace; }
.brief-record-trace dt, .brief-record-trace dd { margin: 0; }
@media print { .doctor-brief-export { max-width: none; padding: 0; } a { color: inherit; } }
`;
