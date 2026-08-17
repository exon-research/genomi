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
    consulted_genes: ["GENE1", "GENE2"],
  },
  coverage: {truncated: false},
  gene_results: [
    {gene: "GENE1", coverage_state: "data_returned", returned_variant_count: 1},
    {gene: "GENE2", coverage_state: "in_scope_empty", returned_variant_count: 0},
  ],
  variants: [{
    chrom: "1",
    pos: 12345,
    rsid: "rs123",
    ref: "A",
    alt: "G",
    filter: "PASS",
    genotype: "0/1",
    matched_candidate_genes: ["GENE1"],
  }],
};

test("personal-genome projection exposes the bounded locus and consulted scope", () => {
  const result = personalGenomeFindingPresentation(evidence);
  assert.equal(result.visible, true);
  assert.deepEqual(result.variants, [{
    title: "GENE1 · rs123",
    details: "GRCh38 · 1:12345 · A>G · Genotype 0/1 · Filter PASS",
  }]);
  assert.deepEqual(result.noHitGenes, ["GENE2"]);
  assert.equal(result.truncated, false);
});

test("personal-genome card renders the variant and complete retrieval state", () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    createElement: (tagName) => new TestElement(tagName),
  };
  elements.evidenceCount = new TestElement("span");
  elements.evidenceLedger = new TestElement("div");
  try {
    renderEvidence([{
      evidence_record_id: "evidence-gene1",
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
    assert.match(copy, /GENE1 · rs123/);
    assert.match(copy, /1:12345 · A>G · Genotype 0\/1/);
    assert.match(copy, /Consulted candidate genes: GENE1, GENE2/);
    assert.match(copy, /Unavailable sources/);
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
