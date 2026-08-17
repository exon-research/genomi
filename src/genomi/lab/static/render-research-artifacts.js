"use strict";

import {
  array,
  elements,
  friendly,
  isObject,
  node,
  shortId,
  text,
} from "./render-dom.js";

export function renderResearchArtifacts(recordsValue) {
  const records = array(recordsValue);
  elements.researchArtifactCount.textContent = `${records.length} ${records.length === 1 ? "artifact" : "artifacts"}`;
  if (!records.length) {
    elements.researchArtifactLedger.replaceChildren(
      node("p", "No nonclinical research artifacts have been submitted.", "empty-row")
    );
    return;
  }
  elements.researchArtifactLedger.replaceChildren(
    ...records.map(researchArtifactCard)
  );
}

function researchArtifactCard(record) {
  const artifact = isObject(record?.artifact) ? record.artifact : {};
  const envelope = isObject(record?.research_envelope) ? record.research_envelope : {};
  const card = node("article", "", "evidence-record research-artifact-record");
  const heading = node("header", "", "evidence-record-heading");
  const identity = document.createElement("div");
  const round = Number(record?.round_number) > 0
    ? `Round ${Number(record.round_number)}`
    : shortId(text(record?.round_id)) || "Round not recorded";
  identity.append(
    node("strong", artifactTitle(record)),
    node(
      "p",
      `${friendly(text(record?.system)) || "Research system"} · ${round} · ${artifactOrigin(record)}`
    )
  );
  heading.append(
    identity,
    node("span", artifactState(envelope), "evidence-state evidence-state-empty")
  );
  card.append(
    heading,
    node(
      "p",
      executionBoundary(envelope),
      "negative-inference negative-inference-not-allowed"
    ),
    artifactFacts(record, artifact)
  );
  return card;
}

function executionBoundary(envelope) {
  const status = text(envelope.scientific_execution_status);
  if (status === "verified_local_execution") {
    return "This artifact records a verified local scientific operation with exact provenance. It remains nonclinical and cannot support hypotheses, brief claims, answer-readiness, treatment content, or clinician export.";
  }
  return "This host-supplied artifact is not verified scientific or provider execution. It cannot support hypotheses, brief claims, answer-readiness, treatment content, or clinician export.";
}

function artifactOrigin(record) {
  return friendly(text(record?.origin)) || "Origin not recorded";
}

function artifactState(_envelope) {
  return "Nonclinical · non-evidence";
}

function artifactTitle(record) {
  if (text(record?.artifact_kind) === "esm_nonclinical_comparison") {
    return "ESM reference-versus-substitution comparison";
  }
  if (text(record?.artifact_kind) === "proto_blinded_experimental_design") {
    return "Proto blinded experimental-design draft";
  }
  if (text(record?.artifact_kind) === "genomi_sequence_substitution_verification") {
    return "Genomi sequence-substitution verification";
  }
  return friendly(text(record?.artifact_kind)) || "Research artifact";
}

function artifactFacts(record, artifact) {
  const method = isObject(artifact.method) ? artifact.method : {};
  const model = isObject(artifact.model) ? artifact.model : {};
  const input = isObject(artifact.input) ? artifact.input : {};
  const output = isObject(artifact.output) ? artifact.output : {};
  const provenance = isObject(artifact.provenance) ? artifact.provenance : {};
  const facts = node("dl", "", "evidence-facts");
  const definitions = [
    ["Method", versioned(method)],
    ["Model / rule set", versioned(model)],
    ...kindFacts(text(record?.artifact_kind), input, output),
    ["Execution", [friendly(text(provenance.execution_location)), friendly(text(provenance.network_access))].filter(Boolean).join(" · ")],
    ["Provenance", [text(provenance.source_label), text(provenance.source_version), text(provenance.source_record_id)].filter(Boolean).join(" · ")],
    ["Input digest", shortId(text(input.reference_sequence_sha256))],
    ["Output digest", shortId(text(input.alternate_sequence_sha256))],
  ].filter(([, value]) => Boolean(value));
  definitions.forEach(([label, value]) => {
    facts.append(node("dt", label), node("dd", value));
  });
  return facts;
}

function kindFacts(kind, input, output) {
  if (kind === "esm_nonclinical_comparison") {
    return [
      ["Input", sequenceInput(input)],
      ["Metric", text(output.metric)],
      ["Reference score", text(output.reference_score)],
      ["Alternate score", text(output.alternate_score)],
      ["Delta", text(output.delta)],
    ];
  }
  if (kind === "proto_blinded_experimental_design") {
    return [
      ["Input", sequenceInput(input)],
      ["Objective", text(input.objective)],
      ["Required arm classes", array(input.required_arm_classes).map((value) => friendly(text(value))).join(", ")],
      ["Separate readouts", array(input.readouts).map((value) => friendly(text(value))).join(", ")],
      ["Blinded arms", array(output.blinded_arm_labels).map(text).join(", ")],
      ["Quality controls", array(output.quality_controls).map(text).join(" · ")],
      ["Analysis plan", array(output.analysis_plan).map(text).join(" · ")],
    ];
  }
  return [
    ["Input", sequenceInput(input)],
    ["Coding descriptor", text(input.coding_change)],
    ["Verification", output.protein_substitution_verified === true
      ? `Reference ${text(output.reference_residue)} at position ${text(output.position)} → ${text(output.alternate_residue)} verified`
      : "Not verified"],
  ];
}

function sequenceInput(input) {
  return [
    text(input.gene),
    text(input.transcript_accession),
    text(input.protein_accession),
    text(input.protein_substitution),
  ].filter(Boolean).join(" · ");
}

function versioned(component) {
  return [text(component.name), text(component.version)].filter(Boolean).join(" · ");
}
