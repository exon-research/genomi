import assert from "node:assert/strict";
import test from "node:test";

import {
  renderSpecialistBoard,
  specialistBoardPresentation,
} from "../../src/genomi/lab/static/render-specialist-board.js";
import { elements } from "../../src/genomi/lab/static/render-dom.js";

class TestElement {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this.className = "";
    this.hidden = false;
    this.textContent = "";
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
  }
}

test("formed specialist board presents each scoped assignment and current work", () => {
  const presentation = specialistBoardPresentation({
    status: "formed",
    chair: {
      role: "main_agent",
      responsibility: "patient_interaction_and_active_genome_index_context_owner",
    },
    members: [
      {
        specialist_id: "specialist-phenotype",
        role: "Phenotype specialist",
        task: "Normalize the patient phenotype",
        status: "in_progress",
        current_work: "Comparing reported findings with HPO terms",
      },
      {
        specialist_id: "specialist-literature",
        role: "Literature specialist",
        task: "Review public disease evidence",
        status: "assigned",
        current_work: "Waiting for the phenotype summary",
      },
    ],
  });

  assert.equal(presentation.visible, true);
  assert.equal(presentation.statusLabel, "Board formed");
  assert.match(presentation.chairBoundary, /main agent is board chair/);
  assert.match(presentation.chairBoundary, /Active Genome Index context/);
  assert.equal(presentation.currentRound, null);
  assert.deepEqual(presentation.members, [
    {
      specialistId: "specialist-phenotype",
      role: "Phenotype specialist",
      task: "Normalize the patient phenotype",
      status: "in_progress",
      currentWork: "Comparing reported findings with HPO terms",
      report: null,
    },
    {
      specialistId: "specialist-literature",
      role: "Literature specialist",
      task: "Review public disease evidence",
      status: "assigned",
      currentWork: "Waiting for the phenotype summary",
      report: null,
    },
  ]);
});

test("current round projection drives the exact roster and completed reports", () => {
  const boardMembers = [
    ["specialist-one", "Evidence specialist"],
    ["specialist-two", "Phenotype specialist"],
    ["specialist-three", "Counterevidence specialist"],
  ].map(([specialist_id, role]) => ({
    specialist_id,
    role,
    task: "Stale board assignment",
    status: "assigned",
    current_work: null,
  }));
  const presentation = specialistBoardPresentation(
    {status: "formed", members: boardMembers},
    {
      round_number: 2,
      focus_question: "Which evidence resolves the current uncertainty?",
      status: "in_progress",
      patient_molecular_snapshot_id: "must-not-render-snapshot",
      members: [
        {
          specialist_id: "specialist-one",
          role: "Evidence specialist",
          task: "Anchor the strongest evidence",
          status: "completed",
          current_work: null,
          report: {
            report_id: "must-not-render-report-id",
            raw_genome_sequence: "must-not-render-genome",
            report: {
              findings: [{
                statement: "One evidence record supports the bounded claim.",
                stance: "supports",
                evidence_record_ids: ["private-evidence-anchor"],
                profile_revision_ids: ["private-profile-anchor"],
              }],
              gaps: [{
                question: "Does an orthogonal assay reproduce the result?",
                evidence_record_ids: [],
                profile_revision_ids: [],
              }],
            },
          },
        },
        {
          specialist_id: "specialist-two",
          role: "Phenotype specialist",
          task: "Review phenotype concordance",
          status: "working",
          current_work: "Comparing the approved observations",
          report: {
            report: {
              findings: [{
                statement: "This unfinished report must not render.",
                evidence_record_ids: ["private-unfinished-anchor"],
                profile_revision_ids: [],
              }],
              gaps: [],
            },
          },
        },
        {
          specialist_id: "specialist-three",
          role: "Counterevidence specialist",
          task: "Search for evidence that weighs against the claim",
          status: "blocked",
          current_work: "Waiting for a source to become available",
        },
      ],
    }
  );

  assert.equal(presentation.statusLabel, "Board working");
  assert.deepEqual(presentation.currentRound, {
    label: "Round 2",
    focusQuestion: "Which evidence resolves the current uncertainty?",
  });
  assert.equal(presentation.members.length, 3);
  assert.deepEqual(
    presentation.members.map(({specialistId, task, status}) => ({specialistId, task, status})),
    [
      {
        specialistId: "specialist-one",
        task: "Anchor the strongest evidence",
        status: "completed",
      },
      {
        specialistId: "specialist-two",
        task: "Review phenotype concordance",
        status: "working",
      },
      {
        specialistId: "specialist-three",
        task: "Search for evidence that weighs against the claim",
        status: "blocked",
      },
    ]
  );
  assert.equal(
    presentation.members[0].currentWork,
    "Completed the assigned work."
  );
  assert.deepEqual(presentation.members[0].report, {
    anchoredFindings: [{
      statement: "One evidence record supports the bounded claim.",
      stance: "supports",
      anchorLabel: "Anchored to 1 evidence record and 1 profile revision",
    }],
    openGaps: [{
      question: "Does an orthogonal assay reproduce the result?",
      anchorLabel: "",
    }],
  });
  assert.equal(presentation.members[1].report, null);
  const renderedProjection = JSON.stringify(presentation);
  for (const privateValue of [
    "must-not-render-snapshot",
    "must-not-render-report-id",
    "must-not-render-genome",
    "private-evidence-anchor",
    "private-profile-anchor",
    "private-unfinished-anchor",
    "This unfinished report must not render.",
  ]) {
    assert.doesNotMatch(renderedProjection, new RegExp(privateValue));
  }
});

test("specialist board stays hidden until formation state exists", () => {
  assert.deepEqual(specialistBoardPresentation(undefined), {
    visible: false,
    statusLabel: "Not formed",
    chairBoundary: "The main agent remains board chair and the Active Genome Index context owner. Specialists receive scoped roles and assignments; this view only monitors their work.",
    currentRound: null,
    members: [],
  });
  assert.equal(
    specialistBoardPresentation({status: "not_formed", members: []}).visible,
    false
  );

  const forming = specialistBoardPresentation({status: "forming", members: []});
  assert.equal(forming.visible, true);
  assert.equal(forming.statusLabel, "Board forming");
  assert.deepEqual(forming.members, []);

  const blocked = specialistBoardPresentation({status: "blocked", members: []});
  assert.equal(blocked.visible, true);
  assert.equal(blocked.statusLabel, "Board blocked");
});

test("specialist board renderer displays round monitoring and completed reports", () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    createElement: (tagName) => new TestElement(tagName),
  };
  elements.specialistBoard = new TestElement("section");
  elements.specialistBoardStatus = new TestElement("span");
  elements.specialistBoardChair = new TestElement("p");
  elements.specialistBoardList = new TestElement("ul");

  try {
    renderSpecialistBoard(
      {
        status: "in_progress",
        chair: {
          role: "main_agent",
          responsibility: "patient_interaction_and_active_genome_index_context_owner",
        },
        members: [{
          specialist_id: "specialist-genetics",
          role: "Genetics specialist",
          task: "Stale board assignment",
          status: "assigned",
          current_work: null,
        }],
      },
      {
        round_number: 4,
        focus_question: "What evidence remains before synthesis?",
        status: "completed",
        members: [{
          specialist_id: "specialist-genetics",
          role: "Genetics specialist",
          task: "Review inherited-disease evidence",
          status: "completed",
          current_work: "Completed the variant-level review",
          report: {
            report: {
              findings: [{
                statement: "The cited record supports a context-only finding.",
                stance: "context_only",
                evidence_record_ids: ["evidence-private-id"],
                profile_revision_ids: [],
              }],
              gaps: [{
                question: "Functional confirmation remains open.",
                evidence_record_ids: [],
                profile_revision_ids: [],
              }],
            },
          },
        }],
      }
    );

    assert.equal(elements.specialistBoard.hidden, false);
    assert.equal(elements.specialistBoardStatus.textContent, "Board completed");
    const chairText = descendantText(elements.specialistBoardChair);
    assert.match(chairText, /owns patient interaction/);
    assert.match(chairText, /Round 4/);
    assert.match(chairText, /What evidence remains before synthesis?/);
    assert.equal(elements.specialistBoardList.children.length, 1);
    const [memberRow] = elements.specialistBoardList.children;
    assert.equal(memberRow.tagName, "li");
    assert.equal(memberRow.children[0].children[0].children[0].textContent, "Genetics specialist");
    assert.equal(memberRow.children[0].children[1].textContent, "Completed");
    assert.equal(memberRow.children[1].textContent, "Completed the variant-level review");
    assert.equal(memberRow.children[2].textContent, "Assignment: Review inherited-disease evidence");
    const reportText = descendantText(memberRow.children[3]);
    assert.match(reportText, /Completed report/);
    assert.match(reportText, /Anchored findings/);
    assert.match(reportText, /The cited record supports a context-only finding./);
    assert.match(reportText, /Context Only/);
    assert.match(reportText, /Anchored to 1 evidence record/);
    assert.match(reportText, /Open gaps/);
    assert.match(reportText, /Functional confirmation remains open./);
    assert.doesNotMatch(reportText, /evidence-private-id/);

    renderSpecialistBoard(null);
    assert.equal(elements.specialistBoard.hidden, true);
    assert.equal(elements.specialistBoardList.children[0].textContent, "The specialist board has not been formed.");
  } finally {
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
  }
});

function descendantText(value) {
  if (!value || typeof value !== "object") return String(value || "");
  return [value.textContent, ...value.children.map(descendantText)]
    .filter(Boolean)
    .join(" ");
}
