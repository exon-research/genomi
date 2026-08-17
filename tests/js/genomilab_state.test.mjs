import assert from "node:assert/strict";
import test from "node:test";

import { InvestigationSession, PortalState } from "../../src/genomi/lab/static/portal-state.js";
import { createProfileEntityLookup } from "../../src/genomi/lab/static/profile-entities.js";
import {
  genomicScopeDescription,
  investigationEventTitle,
  renderContextCandidate,
  visibleInvestigationEvents,
} from "../../src/genomi/lab/static/render.js";
import { elements } from "../../src/genomi/lab/static/render-dom.js";

class TestElement {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this.hidden = false;
    this.textContent = "";
    this.disabled = false;
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
  }
}

test("authorization preview renders bounded context counts", () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    createElement: (tagName) => new TestElement(tagName),
  };
  elements.contextPreview = new TestElement("section");
  elements.contextPreviewPurpose = new TestElement("p");
  elements.contextPreviewList = new TestElement("dl");
  elements.contextApproveButton = new TestElement("button");

  try {
    renderContextCandidate(
      {
        purpose: "Investigate a synthetic immune phenotype",
        observation_revision_ids: ["observation-revision-1"],
        artifact_ids: ["artifact-1"],
        specimen_ids: ["specimen-1", "specimen-2"],
        assay_ids: [],
        agi_snapshot_id: "agi-snapshot-1",
        genomic_scope: {
          operation: "variant.find_gene_variants",
          genome_build: "GRCh38",
          gene_count_limit: 10,
          passing_filters_only: true,
          per_gene_limit: 100,
        },
        modality_coverage: [{modality: "phenotype", coverage_state: "observed"}],
        authorization_scope: {},
      },
      [{
        observation_revision_id: "observation-revision-1",
        label: "Synthetic immune phenotype",
        modality: "phenotype",
        assertion_status: "present",
        verification_state: "user_confirmed",
      }]
    );

    assert.equal(elements.contextPreview.hidden, false);
    const values = elements.contextPreviewList.children
      .filter((child) => child.tagName === "dd")
      .map((child) => child.textContent);
    assert.ok(values.includes("1 record: artifact-1"));
    assert.ok(values.includes("2 specimens: specimen-1, specimen-2"));
    assert.ok(values.includes("None"));
    assert.ok(values.some((value) => value.includes("1–10 named candidate genes")));
    assert.ok(values.some((value) => value.includes("specialists cannot access the genome")));
    assert.equal(elements.contextApproveButton.textContent, "Authorize research context");
    assert.equal(elements.contextApproveButton.disabled, false);
  } finally {
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
  }
});

test("candidate-gene scope is patient-readable and keeps fixed privacy limits visible", () => {
  const description = genomicScopeDescription({
    operation: "variant.find_gene_variants",
    genome_build: "GRCh38",
    gene_count_limit: 10,
    passing_filters_only: true,
    per_gene_limit: 100,
  });

  assert.match(description, /GRCh38/);
  assert.match(description, /1–10 named candidate genes/);
  assert.match(description, /passing calls only/);
  assert.match(description, /specialists cannot access the genome/);
});

test("demo presentation hides setup authorization events while standard portal retains them", () => {
  const events = [
    {event_type: "investigation_created"},
    {event_type: "context_approval_required"},
    {event_type: "context_authorized"},
    {event_type: "specialist_board_formed"},
  ];

  assert.deepEqual(visibleInvestigationEvents(events, false), events);
  assert.deepEqual(
    visibleInvestigationEvents(events, true).map((event) => event.event_type),
    ["investigation_created", "specialist_board_formed"],
  );
  assert.equal(investigationEventTitle("plan_accepted", true), "Plan committed");
  assert.equal(investigationEventTitle("plan_accepted", false), "Plan Accepted");
});

test("opening another investigation invalidates all old request ownership", () => {
  const session = new InvestigationSession();
  const first = session.beginOpen("investigation-1");
  const firstInvestigationLoad = session.beginInvestigationLoad(first);
  const firstPreview = session.beginContextPreview();
  const firstReconnect = session.beginReconnect(first);

  const second = session.beginOpen("investigation-2");

  assert.equal(session.isCurrent(first), false);
  assert.equal(session.isCurrentInvestigationLoad(firstInvestigationLoad), false);
  assert.equal(session.isCurrentContextPreview(firstPreview), false);
  assert.equal(session.isCurrentReconnect(firstReconnect), false);
  assert.equal(session.isCurrent(second), true);
});

test("only the newest same-investigation response may replace displayed state", () => {
  const session = new InvestigationSession();
  const openRequest = session.beginOpen("investigation-1");
  const older = session.beginInvestigationLoad(openRequest);
  const newer = session.beginInvestigationLoad(openRequest);

  assert.equal(session.acceptInvestigationLoad(newer, {title: "newer"}), true);
  assert.equal(session.acceptInvestigationLoad(older, {title: "older"}), false);
  assert.deepEqual(session.investigation, {title: "newer"});
});

test("a stale investigation cannot supersede a current reload request", () => {
  const session = new InvestigationSession();
  const staleOpen = session.beginOpen("investigation-1");
  const staleLoad = session.beginInvestigationLoad(staleOpen);
  const currentOpen = session.beginOpen("investigation-2");
  const currentLoad = session.beginInvestigationLoad(currentOpen);

  assert.equal(session.beginInvestigationLoad(staleOpen), null);
  assert.equal(session.acceptInvestigationLoad(staleLoad, {title: "stale"}), false);
  assert.equal(session.acceptInvestigationLoad(currentLoad, {title: "current"}), true);
  assert.deepEqual(session.investigation, {title: "current"});
});

test("changing selected profile context rejects an in-flight preview", () => {
  const session = new InvestigationSession();
  session.beginOpen("investigation-1");
  const preview = session.beginContextPreview();

  session.invalidateContextSelection();

  assert.equal(session.acceptContextCandidate(preview, {purpose: "stale"}), false);
  assert.equal(session.contextCandidate, null);
});

test("only the current preview may publish a disclosure candidate", () => {
  const session = new InvestigationSession();
  session.beginOpen("investigation-1");
  const first = session.beginContextPreview();
  const second = session.beginContextPreview();

  assert.equal(session.acceptContextCandidate(first, {purpose: "old"}), false);
  assert.equal(session.acceptContextCandidate(second, {purpose: "current"}), true);
  assert.deepEqual(session.contextCandidate, {purpose: "current"});
});

test("replacing and closing a stream aborts the prior owned request", () => {
  const session = new InvestigationSession();
  session.beginOpen("investigation-1");
  const first = session.replaceEventStream();
  const second = session.replaceEventStream();

  assert.equal(first.controller.signal.aborted, true);
  assert.equal(session.ownsEventStream(first), false);
  assert.equal(session.ownsEventStream(second), true);

  session.close();
  assert.equal(second.controller.signal.aborted, true);
  assert.equal(session.ownsEventStream(second), false);
});

test("profile entity lookup is scoped to the supplied render model", () => {
  const first = createProfileEntityLookup({
    artifacts: [{artifact_id: "artifact-1", title: "First"}],
    specimens: [{specimen_id: "specimen-1"}],
    assays: [{assay_id: "assay-1"}],
  });
  const second = createProfileEntityLookup({
    artifacts: [{artifact_id: "artifact-2", title: "Second"}],
  });

  assert.equal(first.artifact("artifact-1").title, "First");
  assert.equal(second.artifact("artifact-1"), null);
  assert.equal(second.artifact("artifact-2").title, "Second");
});

test("portal state reads profile and underlying-agent records through one boundary", () => {
  const state = new PortalState();
  const request = state.beginWorkspaceRequest();
  state.acceptBootstrap(request, {
    workspace: {profile: {observations: [{label: "Observed"}]}},
    capabilities: {
      underlying_agent: {
        agent_session_id: "mcp-codex",
        processing_destination: "current MCP host (Codex; host-reported identity)",
        execution_owner: "underlying_agent",
      },
    },
  });

  assert.deepEqual(state.profileRecords("observations"), [{label: "Observed"}]);
  assert.deepEqual(state.profileRecords("missing"), []);
  assert.equal(state.underlyingAgentManifest().agent_session_id, "mcp-codex");
  assert.equal(
    state.underlyingAgentManifest().processing_destination,
    "current MCP host (Codex; host-reported identity)",
  );
});

test("portal state accepts only an exact signed agent authorization handoff", () => {
  const state = new PortalState();
  const request = state.beginWorkspaceRequest();
  const candidate = {
    investigation_id: "investigation-1",
    purpose: "Private patient purpose",
    authorization_scope: {agent_session: {}},
    authorization_candidate_receipt: "signed-candidate",
  };
  state.acceptBootstrap(request, {
    workspace: {profile: {}},
    authorization_handoff: {
      kind: "investigation_authorization",
      investigation_id: "investigation-1",
      authorization_candidate: candidate,
    },
  });

  assert.deepEqual(state.authorizationHandoff(), {
    kind: "investigation_authorization",
    investigation_id: "investigation-1",
    authorization_candidate: candidate,
  });

  const staleRequest = state.beginWorkspaceRequest();
  state.acceptBootstrap(staleRequest, {
    workspace: {profile: {}},
    authorization_handoff: {
      kind: "investigation_authorization",
      investigation_id: "investigation-other",
      authorization_candidate: candidate,
    },
  });
  assert.equal(state.authorizationHandoff(), null);
});

test("a stale workspace response cannot replace newer patient state", () => {
  const state = new PortalState();
  const older = state.beginWorkspaceRequest();
  const newer = state.beginWorkspaceRequest();

  assert.equal(state.acceptBootstrap(older, {workspace: {user_id: "old"}}), false);
  assert.equal(state.acceptBootstrap(newer, {workspace: {user_id: "current"}}), true);
  assert.equal(state.workspace().user_id, "current");
});
