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

export function renderBriefs(versions, investigation = {}) {
  elements.briefVersionCount.textContent = versions.length
    ? `${versions.length} ${versions.length === 1 ? "version" : "versions"}`
    : "No versions";
  if (!versions.length) {
    elements.briefList.replaceChildren(node("p", "The harness has not proposed a brief yet.", "empty-row"));
    return;
  }
  const evidenceById = new Map(
    array(investigation.evidence_records).map((record) => [text(record.evidence_record_id), record])
  );
  const hypothesesById = new Map(
    array(investigation.hypotheses).map((record) => [text(record.hypothesis_id), record])
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
    body.append(briefSection(
      "Question and scope",
      [
        `Question: ${text(investigation.question) || "The investigation question was not included."}`,
        `Scope: ${text(investigation.disease_scope) || "No narrower disease scope was supplied."}`,
      ],
      "brief-question-scope"
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
    body.append(renderEvidenceClaimSection(claims, evidenceById));
    body.append(renderGapsAndConflicts(brief, evidenceById, hypothesesById));
    body.append(renderLimitsSection(brief, claims, evidenceById));
    body.append(briefSection(
      "Clinical or laboratory confirmation needed",
      array(brief.confirmation_needs),
      "brief-confirmation",
      "No specific confirmation request was included in this version."
    ));
    body.append(briefSection(
      "Questions for the next professional conversation",
      array(brief.professional_questions),
      "brief-professional-questions",
      "No professional questions were included in this version."
    ));
    body.append(renderCurrencyAndChanges(brief, claims, evidenceById, version));
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

function renderGapsAndConflicts(brief, evidenceById, hypothesesById) {
  const section = node("section", "", "brief-section brief-caution-section");
  section.append(node("h4", "Conflicts, missing evidence, and unavailable sources"));
  const list = node("ul", "", "brief-notes");
  array(brief.gap_ids).forEach((id) => {
    const gap = hypothesesById.get(text(id));
    list.append(node("li", gap ? text(gap.statement) : `Open gap ${text(id)}`));
  });
  const citedRecords = citedEvidenceRecords(brief.claims, evidenceById);
  citedRecords.forEach((record) => {
    evidenceWarnings(record).forEach((warning) => list.append(node("li", warning)));
  });
  if (!list.children.length) {
    list.append(node("li", "No conflicts, evidence gaps, or unavailable sources were recorded in this version."));
  }
  section.append(list);
  return section;
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

function renderCurrencyAndChanges(brief, claims, evidenceById, version) {
  const section = node("section", "", "brief-section");
  section.append(node("h4", "Evidence currency and change history"));
  const list = node("ul", "", "brief-notes");
  list.append(node(
    "li",
    `Harness summary: ${text(brief.change_summary) || "No change summary was recorded."}`
  ));
  persistedBriefDiffNotes(version).forEach((value) => list.append(node("li", value)));
  const currency = citedEvidenceRecords(claims, evidenceById).flatMap(evidenceCurrencyNotes);
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
