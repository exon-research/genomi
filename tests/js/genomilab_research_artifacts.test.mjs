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

test("precomputed research artifacts render as concise illustrative demo results", () => {
  elements.researchArtifactCount = new TestElement();
  elements.researchArtifactLedger = new TestElement();

  renderResearchArtifacts([{
    system: "esm",
    round_number: 3,
    origin: "precomputed_fixture",
    artifact_kind: "esm_nonclinical_comparison",
    research_envelope: {scientific_execution_status: "precomputed_fixture"},
    artifact: {
      method: {name: "illustrative_masked_marginal_comparison", version: "1"},
      model: {name: "ESM illustrative demo result", version: "1"},
      input: {gene: "CTLA4", protein_substitution: "Q76H"},
      output: {metric: "illustrative score", delta: -0.75},
      provenance: {
        execution_class: "precomputed_fixture",
        execution_location: "not_verified",
        network_access: "not_verified",
        source_label: "GenomiLab ESM demonstration dataset",
      },
    },
  }]);

  const card = elements.researchArtifactLedger.children[0];
  const text = visibleText(card);
  const definitionLabels = card.children[2].children
    .filter((child) => child.tagName === "dt")
    .map((child) => child.textContent);

  assert.equal(elements.researchArtifactCount.textContent, "1 artifact");
  assert.ok(text.includes("Illustrative demo result"));
  assert.ok(text.includes("Illustrative demo result · nonclinical · not used as evidence"));
  assert.ok(text.includes("GenomiLab ESM demonstration dataset"));
  assert.equal(definitionLabels.includes("Execution"), false);
  assert.equal(text.includes("Not Verified · Not Verified"), false);
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
      input: {gene: "CTLA4", protein_substitution: "Q76H"},
      output: {
        protein_substitution_verified: true,
        reference_residue: "Q",
        position: 76,
        alternate_residue: "H",
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
