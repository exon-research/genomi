"use strict";

import {
  appendDefinition, array, elements, empty, formatTime, friendly, isObject, node, replaceDefinitions, text,
} from "./render-dom.js";

export function renderEvidence(records, activeProfileSnapshotId = "") {
  const currentCount = records.filter(
    (record) => text(record.patient_molecular_snapshot_id) === activeProfileSnapshotId
  ).length;
  const historicalCount = records.length - currentCount;
  elements.evidenceCount.textContent = historicalCount
    ? `${currentCount} current · ${historicalCount} historical`
    : `${records.length} ${records.length === 1 ? "record" : "records"}`;
  if (!records.length) {
    elements.evidenceLedger.replaceChildren(node("p", "No evidence has been committed yet.", "empty-row"));
    return;
  }
  const groups = new Map();
  records.forEach((record) => {
    const family = text(record.source_family) || "other_source";
    const current = groups.get(family) || [];
    current.push(record);
    groups.set(family, current);
  });
  const sections = [...groups.entries()].map(([family, familyRecords]) => {
    const section = node("section", "", "evidence-source");
    const heading = document.createElement("header");
    heading.append(
      node("h4", friendly(family)),
      node("span", String(familyRecords.length), "source-count")
    );
    const list = node("ul", "", "evidence-list");
    const items = familyRecords.map((record) => {
      const historical = Boolean(activeProfileSnapshotId)
        && text(record.patient_molecular_snapshot_id) !== activeProfileSnapshotId;
      const evidence = isObject(record.evidence) ? record.evidence : {};
      const envelope = isObject(record.evidence_envelope)
        ? record.evidence_envelope
        : isObject(evidence.evidence_envelope) ? evidence.evidence_envelope : {};
      const item = node("li", "", "evidence-record");
      const heading = document.createElement("div");
      heading.className = "evidence-record-heading";
      const headingCopy = document.createElement("div");
      headingCopy.append(
        node("strong", evidenceHeadline(envelope, record)),
        node(
          "p",
          [
            friendly(text(record.operation)) || "Evidence lookup",
            historical ? "Historical — prior profile context" : "Current profile context",
          ].join(" · ")
        )
      );
      const state = evidenceFindingState(envelope, evidence);
      heading.append(headingCopy, node("span", state.label, `evidence-state evidence-state-${state.kind}`));

      const status = evidenceStatus(envelope, evidence);
      const coverage = evidenceCoverage(envelope, evidence);
      const facts = node("dl", "", "evidence-facts");
      appendDefinition(facts, "Finding state", state.detail);
      appendDefinition(facts, "Answer readiness", evidenceReadiness(envelope));
      appendDefinition(facts, "Retrieval status", status);
      appendDefinition(facts, "Consulted scope", coverage.consulted);
      appendDefinition(facts, "No-match terms", coverage.misses);
      appendDefinition(facts, "Unavailable sources", coverage.unavailable);
      if (coverage.failures !== "None recorded") {
        appendDefinition(facts, "Source problems", coverage.failures);
      }

      const negative = evidenceNegativeInference(envelope);
      const negativeNote = node("p", negative.message, `negative-inference negative-inference-${negative.kind}`);
      negativeNote.prepend(node("strong", "Negative-inference limit: "));
      const trace = node("p", `Immutable evidence record: ${text(record.evidence_record_id) || "not recorded"} · committed ${formatTime(text(record.created_at))}`, "record-trace-line");
      const personalGenome = renderPersonalGenomeFindings(evidence);
      item.append(
        heading,
        facts,
        personalGenome || sourceRecordList(evidence),
        negativeNote,
        trace,
      );
      return item;
    });
    list.append(...items);
    section.append(heading, list);
    return section;
  });
  elements.evidenceLedger.replaceChildren(...sections);
}

export function personalGenomeFindingPresentation(evidenceValue) {
  const evidence = isObject(evidenceValue) ? evidenceValue : {};
  const query = isObject(evidence.query) ? evidence.query : {};
  const coverage = isObject(evidence.coverage) ? evidence.coverage : {};
  const geneResults = array(evidence.gene_results).filter(isObject);
  const consultedGenes = uniqueText([
    ...array(query.consulted_genes),
    ...geneResults
      .filter((row) => text(row.coverage_state) !== "out_of_scope_for_input")
      .map((row) => row.gene),
  ]);
  const noHitGenes = uniqueText(
    geneResults
      .filter((row) => text(row.coverage_state) === "in_scope_empty")
      .map((row) => row.gene),
  );
  const genomeBuild = text(query.genome_build);
  const variants = array(evidence.variants).filter(isObject).map((variant) => {
    const genes = uniqueText(array(variant.matched_candidate_genes));
    const position = [text(variant.chrom), text(variant.pos)].filter(Boolean).join(":");
    const allele = text(variant.ref) && text(variant.alt)
      ? `${text(variant.ref)}>${text(variant.alt)}`
      : "";
    return {
      title: [genes.join(" / "), text(variant.rsid) || "Unregistered variant"].filter(Boolean).join(" · "),
      details: [
        genomeBuild,
        position,
        allele,
        text(variant.genotype) ? `Genotype ${text(variant.genotype)}` : "",
        text(variant.filter) ? `Filter ${text(variant.filter)}` : "",
      ].filter(Boolean).join(" · "),
    };
  });
  return {
    visible: Boolean(variants.length || geneResults.length),
    variants,
    consultedGenes,
    noHitGenes,
    truncated: coverage.truncated === true,
  };
}

function renderPersonalGenomeFindings(evidence) {
  const presentation = personalGenomeFindingPresentation(evidence);
  if (!presentation.visible) return null;
  const section = node("section", "", "personal-genome-findings");
  section.append(node("h5", "Bounded personal-genome findings"));
  if (presentation.variants.length) {
    const list = node("ul", "", "personal-genome-variant-list");
    list.append(...presentation.variants.map((variant) => {
      const item = node("li", "", "personal-genome-variant");
      item.append(node("strong", variant.title), node("span", variant.details));
      return item;
    }));
    section.append(list);
  } else {
    section.append(node("p", "No passing variant was returned in the consulted gene intervals.", "source-record-empty"));
  }
  const scope = [
    presentation.consultedGenes.length
      ? `Consulted candidate genes: ${presentation.consultedGenes.join(", ")}.`
      : "",
    presentation.noHitGenes.length
      ? `No passing variant in consulted scope for ${presentation.noHitGenes.join(", ")}.`
      : "",
    presentation.truncated ? "At least one gene result was truncated." : "",
  ].filter(Boolean).join(" ");
  if (scope) section.append(node("p", scope, "personal-genome-scope"));
  section.append(node(
    "p",
    "The Main Investigator received this bounded Active Genome Index result; specialists did not receive genome rows.",
    "personal-genome-boundary",
  ));
  return section;
}

export function renderHypotheses(records, activeProfileSnapshotId = "") {
  const gapKinds = new Set(["evidence_gap", "confirmation_requirement"]);
  const currentRecords = activeProfileSnapshotId
    ? records.filter(
      (record) => text(record.patient_molecular_snapshot_id) === activeProfileSnapshotId
    )
    : records;
  const supersededIds = new Set(
    currentRecords.map((record) => text(record.supersedes_hypothesis_id)).filter(Boolean)
  );
  const latestRecords = currentRecords.filter(
    (record) => !supersededIds.has(text(record.hypothesis_id))
  );
  const gaps = latestRecords.filter(
    (record) => gapKinds.has(text(record.kind).toLowerCase())
      && text(record.status).toLowerCase() === "open"
  );
  const hypotheses = latestRecords.filter(
    (record) => !gapKinds.has(text(record.kind).toLowerCase())
  );
  renderClaimList(elements.hypothesisList, hypotheses, "No hypotheses yet.", activeProfileSnapshotId);
  renderClaimList(elements.gapList, gaps, "No open gaps recorded yet.", activeProfileSnapshotId);
}

function renderClaimList(target, records, emptyMessage, activeProfileSnapshotId = "") {
  if (!records.length) {
    target.replaceChildren(empty(emptyMessage));
    return;
  }
  target.replaceChildren(...records.map((record) => {
    const historical = Boolean(activeProfileSnapshotId)
      && text(record.patient_molecular_snapshot_id) !== activeProfileSnapshotId;
    const item = node("li", "", "claim-row");
    item.append(
      node("strong", text(record.statement) || "Untitled research statement"),
      node(
        "span",
        [
          friendly(text(record.kind)),
          friendly(text(record.status)),
          historical ? "Historical — prior profile context" : "Current profile context",
        ].filter(Boolean).join(" · ") || "Working item"
      ),
      claimTraceDetails(record)
    );
    return item;
  }));
}

function evidenceFindingState(envelope, evidence) {
  const findingState = text(envelope.finding_state || evidence.finding_state);
  const states = {
    evidence_present: {
      label: "Evidence returned",
      detail: "Evidence was present in the consulted scope.",
      kind: "returned",
    },
    not_observed_in_consulted_scope: {
      label: "No match in scope",
      detail: "Nothing was observed in the sources that were successfully consulted; this is not a broad negative.",
      kind: "empty",
    },
    not_assessed: {
      label: "Not assessed",
      detail: "The evidence question was not assessed, so no biological conclusion can be drawn.",
      kind: "unavailable",
    },
    blocked_missing_library: {
      label: "Source needed",
      detail: "The needed evidence library was unavailable; this is not a negative finding.",
      kind: "blocked",
    },
    materialization_incomplete: {
      label: "Still preparing",
      detail: "Evidence preparation is incomplete and this record is not ready for a conclusion.",
      kind: "running",
    },
    true_negative_supported: {
      label: "Scoped negative supported",
      detail: "A negative finding is supported only within the declared assay and evidence scope.",
      kind: "returned",
    },
  };
  return states[findingState] || {
    label: "State not recorded",
    detail: findingState ? friendly(findingState) : "No canonical finding state was recorded.",
    kind: "unknown",
  };
}

function evidenceStatus(envelope, evidence) {
  const value = text(evidence.status || envelope.status);
  const labels = {
    data_returned: "Evidence returned",
    in_scope_empty: "Search completed; no match in the consulted scope",
    out_of_scope_for_input: "Input was outside this evidence capability's scope",
    blocked_by_policy: "Blocked by the evidence-access policy",
    authentication_failed: "Evidence source authentication failed",
    quota_exceeded: "Evidence source quota was exceeded",
    rate_limited: "Evidence source temporarily rate limited",
    timeout: "Evidence source timed out",
    network_error: "Evidence source network error",
    server_error: "Evidence source server error",
    source_unavailable: "Evidence source unavailable",
    not_found: "Requested source record was not found",
    in_progress: "Evidence work is still in progress",
    completed: "Evidence operation completed",
  };
  return labels[value] || friendly(value) || "Status not recorded";
}

function evidenceCoverage(envelope, evidence) {
  const canonical = isObject(envelope.coverage) ? envelope.coverage : {};
  const provider = isObject(evidence.coverage) ? evidence.coverage : {};
  const consulted = uniqueText([
    ...array(canonical.consulted_sources),
    ...array(canonical.consulted_coverage),
    ...array(provider.consulted),
  ]);
  const misses = uniqueText([...array(canonical.misses), ...array(provider.misses)]);
  const unavailable = uniqueText(array(canonical.unavailable_sources));
  const failureValues = [
    ...array(canonical.failures),
    ...array(provider.partial_failures),
    ...(isObject(evidence.failure) ? [evidence.failure] : []),
  ].map(failureDescription).filter(Boolean);
  return {
    consulted: consulted.length ? consulted.join(", ") : "No consulted source recorded",
    misses: misses.length ? misses.join(", ") : "None recorded",
    unavailable: unavailable.length ? unavailable.join(", ") : "None recorded",
    failures: failureValues.length ? uniqueText(failureValues).join("; ") : "None recorded",
  };
}

function evidenceNegativeInference(envelope) {
  const rule = isObject(envelope.negative_inference) ? envelope.negative_inference : {};
  const required = array(rule.requires).map((value) => friendly(text(value))).filter(Boolean);
  const satisfied = array(rule.satisfied).map((value) => friendly(text(value))).filter(Boolean);
  if (rule.allowed === true) {
    const qualification = [
      required.length ? `required controls: ${required.join(", ")}` : "only the declared scope",
      satisfied.length ? `satisfied controls: ${satisfied.join(", ")}` : "",
    ].filter(Boolean).join("; ");
    return {
      kind: "scoped",
      message: `A negative conclusion is permitted only within this record's declared scope (${qualification}).`,
    };
  }
  const reason = text(rule.reason);
  return {
    kind: "not-allowed",
    message: `${reason ? `${reason}. ` : ""}Do not read this result as evidence that a disease, variant, or publication is absent beyond the stated scope.`,
  };
}

function failureDescription(value) {
  if (typeof value === "string") return friendly(value);
  if (!isObject(value)) return "";
  const status = evidenceStatus({}, {status: value.status});
  return value.retryable === true ? `${status} (retry may help)` : status;
}

export function claimSourceFamilies(claim, evidenceById) {
  const sources = uniqueText(
    array(claim.evidence_record_ids)
      .map((id) => evidenceById.get(text(id)))
      .filter(Boolean)
      .map((record) => friendly(text(record.source_family)))
      .filter(Boolean)
  );
  return sources.length ? `Sources: ${sources.join(", ")}` : "";
}

export function citedEvidenceRecords(claims, evidenceById) {
  const ids = new Set(
    array(claims).flatMap((claim) => array(claim.evidence_record_ids).map(text))
  );
  return [...ids].map((id) => evidenceById.get(id)).filter(Boolean);
}

export function evidenceWarnings(record) {
  const evidence = isObject(record.evidence) ? record.evidence : {};
  const envelope = isObject(record.evidence_envelope)
    ? record.evidence_envelope
    : isObject(evidence.evidence_envelope) ? evidence.evidence_envelope : {};
  const warnings = [];
  const state = text(envelope.finding_state);
  if (state && state !== "evidence_present" && state !== "true_negative_supported") {
    warnings.push(evidenceFindingState(envelope, evidence).detail);
  }
  const coverage = evidenceCoverage(envelope, evidence);
  if (coverage.unavailable !== "None recorded") {
    warnings.push(`Unavailable sources: ${coverage.unavailable}.`);
  }
  if (coverage.failures !== "None recorded") warnings.push(`Source problems: ${coverage.failures}.`);
  array(evidence.records).forEach((sourceRecord) => {
    const provenance = isObject(sourceRecord.provenance) ? sourceRecord.provenance : {};
    const currency = isObject(provenance.source_currency) ? provenance.source_currency : {};
    if (array(currency.conflict_ids).length) {
      warnings.push(`Source ${text(sourceRecord.source_id) || "record"} has recorded conflicts: ${array(currency.conflict_ids).map(text).join(", ")}.`);
    }
    if (array(currency.superseded_by).length) {
      warnings.push(`Source ${text(sourceRecord.source_id) || "record"} may be superseded by ${array(currency.superseded_by).map(text).join(", ")}.`);
    }
  });
  return uniqueText(warnings);
}

export function evidenceCurrencyNotes(record) {
  const evidence = isObject(record.evidence) ? record.evidence : {};
  const notes = [];
  array(evidence.records).forEach((sourceRecord) => {
    const provenance = isObject(sourceRecord.provenance) ? sourceRecord.provenance : {};
    const currency = isObject(provenance.source_currency) ? provenance.source_currency : {};
    const source = text(sourceRecord.source_id) || text(provenance.original_source_id) || "Source record";
    const checked = text(currency.current_source_checked_at);
    if (checked) notes.push(`${source}: current source checked ${formatTime(checked)}.`);
    const correction = text(currency.correction_status);
    const retraction = text(currency.retraction_status);
    if (correction || retraction) {
      notes.push(`${source}: correction status ${friendly(correction) || "not recorded"}; retraction status ${friendly(retraction) || "not recorded"}.`);
    }
  });
  return uniqueText(notes);
}

function uniqueText(values) {
  return [...new Set(values.map(text).filter(Boolean))];
}

export function claimTraceDetails(claim) {
  const details = document.createElement("details");
  details.className = "claim-trace";
  details.append(node("summary", "View evidence trace"));
  const list = node("ul", "", "claim-trace-list");
  const evidenceIds = array(claim.evidence_record_ids).map(text).filter(Boolean);
  const profileIds = array(claim.profile_revision_ids).map(text).filter(Boolean);
  const hypothesisIds = array(claim.hypothesis_ids).map(text).filter(Boolean);
  const gapIds = array(claim.gap_ids).map(text).filter(Boolean);
  evidenceIds.forEach((id) => list.append(node("li", `Evidence record: ${id}`)));
  profileIds.forEach((id) => list.append(node("li", `Profile revision: ${id}`)));
  hypothesisIds.forEach((id) => list.append(node("li", `Hypothesis: ${id}`)));
  gapIds.forEach((id) => list.append(node("li", `Evidence gap: ${id}`)));
  if (!evidenceIds.length && !profileIds.length && !hypothesisIds.length && !gapIds.length) {
    list.append(node("li", "No immutable evidence or profile anchor was recorded."));
  }
  details.append(list);
  return details;
}

export function evidenceTraceDetails(record, evidence) {
  const details = document.createElement("details");
  details.className = "trace-details";
  details.append(node("summary", "View source and immutable revision"));
  const list = node("dl", "", "preview-list");
  replaceDefinitions(list, [
    ["Evidence record", text(record.evidence_record_id) || "Not recorded"],
    ["Operation", text(record.operation) || "Not recorded"],
    ["Saved", formatTime(text(record.created_at))],
    ["Retrieval status", friendly(text(evidence.status)) || "Not recorded"],
  ]);
  details.append(list, sourceRecordList(evidence));
  return details;
}

export function sourceRecordList(evidence) {
  const section = node("section", "", "source-records");
  const records = array(evidence.records);
  if (!records.length) {
    section.append(node("p", "No source-level record was retained for this evidence result.", "source-record-empty"));
    return section;
  }
  section.append(node("h5", records.length === 1 ? "Primary source" : "Primary sources"));
  const list = node("ul", "", "source-record-list");
  list.append(...records.map(sourceRecordItem));
  section.append(list);
  return section;
}

function sourceRecordItem(sourceRecord) {
  const item = node("li", "", "source-record-card");
  const provenance = isObject(sourceRecord.provenance) ? sourceRecord.provenance : {};
  const titleValue = trustedEvidenceText(sourceRecord.title) || text(sourceRecord.source_id) || "Untitled source record";
  const safeUri = safeHttpUrl(provenance.original_source_uri);
  const title = safeUri ? safeSourceLink(titleValue, safeUri) : node("strong", titleValue);
  const meta = uniqueText([
    sourceIdentifierDescription(sourceRecord.identifiers),
    friendly(text(sourceRecord.source_document_state)),
    text(provenance.publication_date) ? `Source date ${text(provenance.publication_date)}` : "",
    text(provenance.original_source_version) ? `Version ${text(provenance.original_source_version)}` : "",
  ]);
  const header = node("div", "", "source-record-heading");
  header.append(title);
  if (meta.length) header.append(node("span", meta.join(" · ")));
  item.append(header);

  const excerpt = trustedEvidenceText(sourceRecord.excerpt);
  if (excerpt) item.append(node("blockquote", excerpt, "source-excerpt"));
  const spans = uniqueText(array(sourceRecord.supporting_spans).map(trustedEvidenceText));
  if (spans.length) {
    const spanList = node("ul", "", "supporting-span-list");
    spanList.append(...spans.map((span) => node("li", span)));
    item.append(
      node("strong", "Supporting passage", "supporting-span-label"),
      spanList
    );
  }
  return item;
}

function trustedEvidenceText(value) {
  if (typeof value === "string") return value;
  return isObject(value) ? text(value.text) : "";
}

function sourceIdentifierDescription(value) {
  if (!isObject(value)) return "";
  return Object.entries(value)
    .map(([name, identifier]) => `${friendly(text(name))}: ${text(identifier)}`)
    .filter((entry) => !entry.endsWith(": "))
    .join(" · ");
}

export function safeHttpUrl(value) {
  const candidate = text(value).trim();
  if (!candidate) return "";
  try {
    const parsed = new URL(candidate);
    return ["http:", "https:"].includes(parsed.protocol) &&
      parsed.hostname &&
      !isLocalSourceHost(parsed.hostname)
      ? parsed.href
      : "";
  } catch (_error) {
    return "";
  }
}

function isLocalSourceHost(value) {
  const hostname = String(value).toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  if (
    hostname === "localhost" ||
    hostname.endsWith(".localhost") ||
    hostname.endsWith(".local") ||
    hostname === "0.0.0.0" ||
    hostname === "::1"
  ) {
    return true;
  }
  const ipv4 = hostname.match(/^(\d{1,3})(?:\.\d{1,3}){3}$/);
  if (ipv4 && Number(ipv4[1]) === 127) return true;
  return hostname.startsWith("::ffff:127.") || hostname.startsWith("::ffff:7f");
}

function safeSourceLink(label, href) {
  const link = node("a", label, "source-link");
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.referrerPolicy = "no-referrer";
  return link;
}

export function observationDescription(observation) {
  return [
    text(observation.label),
    friendly(text(observation.modality)),
    friendly(text(observation.assertion_status)),
    friendly(text(observation.verification_state)),
  ].filter(Boolean).join(" — ");
}

export function coverageDescription(value) {
  const coverage = array(value);
  if (!coverage.length) return "No coverage statements included";
  return coverage.map((item) => [friendly(text(item.modality)), friendly(text(item.coverage_state))].filter(Boolean).join(": ")).join("; ");
}

export function contextDisclosureDescription(value) {
  const context = isObject(value) ? value : {};
  const profile = isObject(context.molecular_profile) ? context.molecular_profile : null;
  if (!profile) return "No private molecular-profile context";
  const count = array(profile.observations).length;
  const genome = profile.agi_snapshot_id ? ` and genome revision ${text(profile.agi_snapshot_id)}` : "";
  return `${count} included profile ${count === 1 ? "observation" : "observations"}${genome}`;
}

export function evidenceHeadline(envelope, record) {
  if (typeof envelope.headline === "string") return envelope.headline;
  if (isObject(envelope.headline)) {
    return text(envelope.headline.summary) || text(envelope.headline.state) || "Evidence record";
  }
  return friendly(text(record.source_family)) || "Evidence record";
}

export function evidenceReadiness(envelope) {
  return friendly(text(envelope.answer_readiness) || text(envelope.status) || text(envelope.state)) || "Review evidence details";
}

function anchorDescription(claim) {
  const evidenceCount = array(claim.evidence_record_ids).length;
  const profileCount = array(claim.profile_revision_ids).length;
  return `${evidenceCount} evidence ${evidenceCount === 1 ? "anchor" : "anchors"} · ${profileCount} profile ${profileCount === 1 ? "anchor" : "anchors"}`;
}
