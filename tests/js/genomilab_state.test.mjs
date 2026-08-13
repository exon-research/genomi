import assert from "node:assert/strict";
import test from "node:test";

import { InvestigationSession, PortalState } from "../../src/genomi/lab/static/portal-state.js";
import { createProfileEntityLookup } from "../../src/genomi/lab/static/profile-entities.js";

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

test("a plan action cannot preview harness work for another investigation", () => {
  const session = new InvestigationSession();
  const acceptedPlanOpen = session.beginOpen("investigation-1");
  session.beginOpen("investigation-2");
  const currentPreview = session.beginOutboundPreview();

  assert.equal(session.beginOutboundPreview(acceptedPlanOpen), null);
  assert.equal(session.isCurrentOutboundPreview(currentPreview), true);
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

test("only the newest outbound preview may become approvable", () => {
  const session = new InvestigationSession();
  session.beginOpen("investigation-1");
  const first = session.beginOutboundPreview();
  const second = session.beginOutboundPreview();

  assert.equal(session.acceptOutboundCandidate(first, {payload_sha256: "old"}), false);
  assert.equal(session.acceptOutboundCandidate(second, {payload_sha256: "current"}), true);
  assert.equal(session.outboundCandidate.payload_sha256, "current");

  session.discardOutboundCandidate();
  assert.equal(session.outboundCandidate, null);
  assert.equal(session.isCurrentOutboundPreview(second), false);
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

test("portal state reads profile and harness records through one boundary", () => {
  const state = new PortalState();
  const request = state.beginWorkspaceRequest();
  state.acceptBootstrap(request, {
    workspace: {profile: {observations: [{label: "Observed"}]}},
    capabilities: {installed_harness: {host_kind: "codex"}},
  });

  assert.deepEqual(state.profileRecords("observations"), [{label: "Observed"}]);
  assert.deepEqual(state.profileRecords("missing"), []);
  assert.equal(state.harnessManifest().host_kind, "codex");
});

test("a stale workspace response cannot replace newer patient state", () => {
  const state = new PortalState();
  const older = state.beginWorkspaceRequest();
  const newer = state.beginWorkspaceRequest();

  assert.equal(state.acceptBootstrap(older, {workspace: {user_id: "old"}}), false);
  assert.equal(state.acceptBootstrap(newer, {workspace: {user_id: "current"}}), true);
  assert.equal(state.workspace().user_id, "current");
});
