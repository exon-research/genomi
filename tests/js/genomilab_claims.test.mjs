import assert from "node:assert/strict";
import test from "node:test";

import { renderHypotheses } from "../../src/genomi/lab/static/render-evidence.js";
import { elements } from "../../src/genomi/lab/static/render-dom.js";

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

test("hypothesis and open-gap views show only latest current records", () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    createElement: (tagName) => new TestElement(tagName),
  };
  elements.hypothesisList = new TestElement("ul");
  elements.gapList = new TestElement("ul");

  try {
    renderHypotheses([
      {
        hypothesis_id: "hypothesis-old",
        logical_hypothesis_id: "thread-1",
        patient_molecular_snapshot_id: "snapshot-current",
        kind: "candidate_mechanism",
        status: "candidate",
        statement: "Older hypothesis",
      },
      {
        hypothesis_id: "hypothesis-current",
        logical_hypothesis_id: "thread-1",
        supersedes_hypothesis_id: "hypothesis-old",
        patient_molecular_snapshot_id: "snapshot-current",
        kind: "candidate_mechanism",
        status: "supported",
        statement: "Current hypothesis",
      },
      {
        hypothesis_id: "gap-open",
        patient_molecular_snapshot_id: "snapshot-current",
        kind: "evidence_gap",
        status: "open",
        statement: "Still needs testing",
      },
      {
        hypothesis_id: "gap-resolved",
        patient_molecular_snapshot_id: "snapshot-current",
        kind: "confirmation_requirement",
        status: "resolved",
        statement: "Already resolved",
      },
      {
        hypothesis_id: "hypothesis-historical",
        patient_molecular_snapshot_id: "snapshot-old",
        kind: "uncertainty",
        status: "candidate",
        statement: "Historical hypothesis",
      },
    ], "snapshot-current");

    assert.equal(elements.hypothesisList.children.length, 1);
    assert.equal(
      elements.hypothesisList.children[0].children[0].textContent,
      "Current hypothesis"
    );
    assert.equal(elements.gapList.children.length, 1);
    assert.equal(
      elements.gapList.children[0].children[0].textContent,
      "Still needs testing"
    );
  } finally {
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
  }
});
