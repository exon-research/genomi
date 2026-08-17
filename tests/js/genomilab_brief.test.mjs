import assert from "node:assert/strict";
import test from "node:test";

import { renderBriefs } from "../../src/genomi/lab/static/render-brief.js";
import { elements } from "../../src/genomi/lab/static/render-dom.js";

class TestElement {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this.className = "";
    this.textContent = "";
    this.attributes = new Map();
    this.listeners = new Map();
    this.open = false;
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  addEventListener(name, handler) {
    this.listeners.set(name, handler);
  }
}

function descendants(root) {
  return [root, ...root.children.flatMap(descendants)];
}

test("current doctor brief renders grounded chronology, clinician questions, record references, and export actions", () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    createElement: (tagName) => new TestElement(tagName),
  };
  elements.briefVersionCount = new TestElement("span");
  elements.briefList = new TestElement("div");

  const evidenceId = "evidence-paperclip-1";
  const revisionId = "observation-revision-1";
  const version = {
    brief_version_id: "brief-version-1",
    version: 1,
    created_at: "2026-08-15T12:00:00Z",
    brief: {
      title: "Proposed investigation brief",
      summary: "The approved record remains a research observation.",
      clinical_stage: "research_observation",
      timeline: [{
        statement: "Patient observation: The profile records a research observation.",
        evidence_record_ids: [],
        profile_revision_ids: [revisionId],
      }],
      claims: [{
        statement: "Patient observation: The profile records a research observation.",
        claim_role: "observation",
        evidence_record_ids: [evidenceId],
        profile_revision_ids: [revisionId],
      }],
      hypothesis_ids: [],
      gap_ids: [],
      confirmation_needs: ["Independent clinical confirmation"],
      clinician_questions: [{
        question: "Would a qualified CTLA4 transendocytosis assay help distinguish normal staining from impaired function in this case?",
        evidence_record_ids: [evidenceId],
        profile_revision_ids: [revisionId],
        hypothesis_ids: ["hypothesis-1"],
        gap_ids: [],
      }],
      modality_badges: ["reported_record", "public_source"],
      clinical_boundary: "Research support only; this is not a diagnosis or treatment decision.",
      change_summary: "Prepared a traceable research brief.",
    },
  };
  const investigation = {
    question: "Could these immune problems be connected?",
    disease_scope: "Immune dysregulation",
    current_brief_version: version,
    hypotheses: [{
      hypothesis_id: "hypothesis-1",
      statement: "Working hypothesis: checkpoint-pathway immune dysregulation.",
    }],
    evidence_records: [{
      evidence_record_id: evidenceId,
      source_family: "literature",
      operation: "paperclip.search",
      evidence: {
        records: [{
          source_id: "PMID:123",
          title: "CTLA4 transendocytosis study",
          provenance: {
            original_source_uri: "https://pubmed.ncbi.nlm.nih.gov/123/",
            publication_date: "2026-07-01",
            source_license: {status: "curated_short_paraphrase_demo_fixture"},
          },
          excerpt: "Curated summary of the public source.",
          supporting_spans: ["This does not establish Q76H causality."],
        }],
      },
    }],
  };
  const profile = {
    observations: [{
      observation_revision_id: revisionId,
      label: "Pneumonia before the first biologic",
      artifact_id: "artifact-pneumonia",
    }],
    source_artifacts: [{
      artifact_id: "artifact-pneumonia",
      title: "Pneumonia hospital record",
      source_type: "issued_report",
      issued_at: "2018-02-03",
      local_file_sha256: "abc123",
    }],
  };

  try {
    renderBriefs([version], investigation, profile);
    const nodes = descendants(elements.briefList);
    const copy = nodes.map((item) => item.textContent).filter(Boolean).join("\n");
    const buttons = nodes.filter((item) => item.tagName === "button");
    const sourceLink = nodes.find((item) => item.tagName === "a");
    const questionContext = nodes.find((item) => item.className === "brief-question-context");

    assert.match(copy, /Chronology that changed the investigation/);
    assert.match(copy, /Pneumonia before the first biologic/);
    assert.match(copy, /Would a qualified CTLA4 transendocytosis assay/);
    assert.match(copy, /Pneumonia hospital record/);
    assert.match(copy, /abc123/);
    assert.match(copy, /Source date 2026-07-01/);
    assert.match(copy, /Curated source summary/);
    assert.match(copy, /Interpretation limit/);
    assert.equal(questionContext?.tagName, "details");
    assert.equal(questionContext?.open, false);
    assert.doesNotMatch(copy, /Conflicts, missing evidence, and unavailable sources/);
    assert.deepEqual(
      buttons.map((button) => button.textContent),
      ["Print / Save PDF", "Download doctor brief (.html)"]
    );
    assert.equal(sourceLink.href, "https://pubmed.ncbi.nlm.nih.gov/123/");
    assert.equal(sourceLink.rel, "noopener noreferrer");
  } finally {
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
  }
});
