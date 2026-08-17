import assert from "node:assert/strict";
import test from "node:test";

class TestElement {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this.className = "";
    this.textContent = "";
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
  }
}

globalThis.document = {
  createElement(tagName) {
    return new TestElement(tagName);
  },
};

const {renderResearchArtifacts} = await import(
  "../../src/genomi/lab/static/render-research-artifacts.js"
);
const {elements} = await import("../../src/genomi/lab/static/render-dom.js");

function visibleText(element) {
  return [element.textContent, ...element.children.flatMap((child) => visibleText(child))]
    .filter(Boolean);
}

test("unverified host research artifacts retain their execution boundary", () => {
  elements.researchArtifactCount = new TestElement();
  elements.researchArtifactLedger = new TestElement();

  renderResearchArtifacts([{
    system: "esm",
    round_number: 3,
    origin: "host_supplied_unverified",
    artifact_kind: "esm_nonclinical_comparison",
    research_envelope: {scientific_execution_status: "not_verified"},
    artifact: {
      method: {name: "imported_masked_marginal_comparison", version: "1"},
      model: {name: "External ESM output", version: "1"},
      input: {gene: "GENE1", protein_substitution: "R42W"},
      output: {metric: "imported score", delta: -0.75},
      provenance: {
        execution_class: "host_supplied_unverified",
        execution_location: "not_verified",
        network_access: "not_verified",
        source_label: "Host-imported ESM output",
      },
    },
  }]);

  const card = elements.researchArtifactLedger.children[0];
  const text = visibleText(card);
  const definitionLabels = card.children[2].children
    .filter((child) => child.tagName === "dt")
    .map((child) => child.textContent);

  assert.equal(elements.researchArtifactCount.textContent, "1 artifact");
  assert.ok(text.some((value) => value.includes("not verified scientific or provider execution")));
  assert.ok(text.includes("Nonclinical · non-evidence"));
  assert.ok(text.includes("Host-imported ESM output"));
  assert.equal(definitionLabels.includes("Execution"), true);
  assert.equal(text.includes("Not Verified · Not Verified"), true);
});

test("verified research artifacts keep the strong nonclinical boundary and execution facts", () => {
  elements.researchArtifactCount = new TestElement();
  elements.researchArtifactLedger = new TestElement();

  renderResearchArtifacts([{
    system: "genomi",
    round_number: 3,
    origin: "verified_scientific_operation",
    artifact_kind: "genomi_sequence_substitution_verification",
    research_envelope: {scientific_execution_status: "verified_local_execution"},
    artifact: {
      method: {name: "sequence substitution verification", version: "1"},
      model: {name: "deterministic rule set", version: "1"},
      input: {gene: "GENE1", protein_substitution: "R42W"},
      output: {
        protein_substitution_verified: true,
        reference_residue: "R",
        position: 42,
        alternate_residue: "W",
      },
      provenance: {
        execution_class: "verified_scientific_operation",
        execution_location: "local",
        network_access: "disabled",
        source_label: "Genomi sequence verifier",
      },
    },
  }]);

  const card = elements.researchArtifactLedger.children[0];
  const text = visibleText(card);
  const definitionLabels = card.children[2].children
    .filter((child) => child.tagName === "dt")
    .map((child) => child.textContent);

  assert.ok(text.some((value) => value.includes("verified local scientific operation")));
  assert.ok(text.includes("Nonclinical · non-evidence"));
  assert.ok(definitionLabels.includes("Execution"));
  assert.ok(text.includes("Local · Disabled"));
});
