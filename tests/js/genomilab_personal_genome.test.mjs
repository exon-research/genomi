import assert from "node:assert/strict";
import test from "node:test";

import {
  personalGenomeFindingPresentation,
  renderEvidence,
  sourceRecordList,
} from "../../src/genomi/lab/static/render-evidence.js";
import { elements } from "../../src/genomi/lab/static/render-dom.js";

class TestElement {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this.className = "";
    this.textContent = "";
  }

  append(...children) { this.children.push(...children); }
  prepend(...children) { this.children.unshift(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute() {}
}

function descendants(root) {
  return [root, ...root.children.flatMap(descendants)];
}

const evidence = {
  status: "variants_found",
  query: {
    genome_build: "GRCh38",
    consulted_genes: ["CTLA4", "LRBA", "PIK3CD", "NFKB1", "TNFRSF13B"],
  },
  coverage: {truncated: false},
  gene_results: [
    {gene: "CTLA4", coverage_state: "data_returned", returned_variant_count: 1},
    {gene: "LRBA", coverage_state: "in_scope_empty", returned_variant_count: 0},
  ],
  variants: [{
    chrom: "2",
    pos: 203870704,
    rsid: "rs2469719303",
    ref: "G",
    alt: "C",
    filter: "PASS",
    genotype: "0/1",
    matched_candidate_genes: ["CTLA4"],
  }],
};

test("personal-genome projection exposes the bounded CTLA4 locus and consulted scope", () => {
  const result = personalGenomeFindingPresentation(evidence);
  assert.equal(result.visible, true);
  assert.deepEqual(result.variants, [{
    title: "CTLA4 · rs2469719303",
    details: "GRCh38 · 2:203870704 · G>C · Genotype 0/1 · Filter PASS",
  }]);
  assert.deepEqual(result.noHitGenes, ["LRBA"]);
  assert.equal(result.truncated, false);
});

test("demo personal-genome card renders the variant without empty unavailable-source noise", () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    body: {dataset: {presentation: "demo"}},
    createElement: (tagName) => new TestElement(tagName),
  };
  elements.evidenceCount = new TestElement("span");
  elements.evidenceLedger = new TestElement("div");
  try {
    renderEvidence([{
      evidence_record_id: "evidence-ctla4",
      patient_molecular_snapshot_id: "snapshot-current",
      source_family: "personal_genome",
      operation: "variant.find_gene_variants",
      created_at: "2026-08-15T12:00:00Z",
      evidence,
      evidence_envelope: {
        finding_state: "evidence_present",
        answer_readiness: "needs_clinical_confirmation",
        negative_inference: {allowed: false},
      },
    }], "snapshot-current");
    const copy = descendants(elements.evidenceLedger)
      .map((item) => item.textContent)
      .filter(Boolean)
      .join("\n");
    assert.match(copy, /CTLA4 · rs2469719303/);
    assert.match(copy, /2:203870704 · G>C · Genotype 0\/1/);
    assert.match(copy, /Consulted candidate genes: CTLA4, LRBA, PIK3CD, NFKB1, TNFRSF13B/);
    assert.doesNotMatch(copy, /No source-level record was retained/);
    assert.doesNotMatch(copy, /Unavailable sources/);
  } finally {
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
  }
});

test("demo presentation omits blocked live-route noise from a successful fixture replay", () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    body: {dataset: {presentation: "demo"}},
    createElement: (tagName) => new TestElement(tagName),
  };
  elements.evidenceCount = new TestElement("span");
  elements.evidenceLedger = new TestElement("div");
  try {
    renderEvidence([{
      evidence_record_id: "evidence-paperclip-replay",
      patient_molecular_snapshot_id: "snapshot-current",
      source_family: "literature",
      operation: "public_evidence.retrieve",
      evidence: {
        provider: "fixture",
        access_mode: "fixture",
        status: "data_returned",
        coverage: {consulted: ["Curated Paperclip evidence replay"]},
        records: [],
      },
      evidence_envelope: {
        finding_state: "evidence_present",
        answer_readiness: "needs_clinical_confirmation",
        coverage: {unavailable_sources: ["paperclip"]},
        negative_inference: {allowed: false},
      },
    }], "snapshot-current");
    const copy = descendants(elements.evidenceLedger)
      .map((item) => item.textContent)
      .filter(Boolean)
      .join("\n");
    assert.match(copy, /Curated Paperclip evidence replay/);
    assert.doesNotMatch(copy, /Unavailable sources/);
  } finally {
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
  }
});

test("demo presentation retains unavailable-source state for an unsuccessful fixture result", () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    body: {dataset: {presentation: "demo"}},
    createElement: (tagName) => new TestElement(tagName),
  };
  elements.evidenceCount = new TestElement("span");
  elements.evidenceLedger = new TestElement("div");
  try {
    renderEvidence([{
      evidence_record_id: "evidence-fixture-failure",
      patient_molecular_snapshot_id: "snapshot-current",
      source_family: "literature",
      operation: "public_evidence.retrieve",
      evidence: {
        provider: "fixture",
        access_mode: "fixture",
        status: "source_unavailable",
        records: [],
      },
      evidence_envelope: {
        finding_state: "not_assessed",
        answer_readiness: "not_answer_ready",
        coverage: {unavailable_sources: ["paperclip"]},
        negative_inference: {allowed: false},
      },
    }], "snapshot-current");
    const copy = descendants(elements.evidenceLedger)
      .map((item) => item.textContent)
      .filter(Boolean)
      .join("\n");
    assert.match(copy, /Unavailable sources/);
    assert.match(copy, /paperclip/);
  } finally {
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
  }
});

test("ordinary source records retain supporting-passage semantics", () => {
  const originalDocument = globalThis.document;
  globalThis.document = {createElement: (tagName) => new TestElement(tagName)};
  try {
    const rendered = sourceRecordList({records: [{
      source_id: "PMID:123",
      title: "A live source record",
      excerpt: "A retained excerpt.",
      supporting_spans: ["A supporting passage."],
      provenance: {source_license: {status: "not_provided"}},
    }]});
    const copy = descendants(rendered)
      .map((item) => item.textContent)
      .filter(Boolean)
      .join("\n");
    assert.match(copy, /Supporting passage/);
    assert.doesNotMatch(copy, /Curated source summary/);
    assert.doesNotMatch(copy, /Interpretation limit/);
  } finally {
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
  }
});
