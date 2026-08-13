"use strict";

import {
  array,
  collectElements,
  elements,
  empty,
  exactValue,
  formatTime,
  friendly,
  hideAlert,
  isObject,
  node,
  replaceDefinitions,
  setActivity,
  setBusy,
  shortId,
  showAlert,
  text,
} from "./render-dom.js";
import { renderBriefs } from "./render-brief.js";
import {
  contextDisclosureDescription,
  coverageDescription,
  evidenceHeadline,
  evidenceReadiness,
  evidenceTraceDetails,
  observationDescription,
  renderEvidence,
  renderHypotheses,
  sourceRecordList,
} from "./render-evidence.js";
import {
  hideObservationEditor,
  renderCompactRecords,
  renderObservationEditor,
  renderProfile,
} from "./render-profile.js";

export {
  collectElements,
  elements,
  hideAlert,
  hideObservationEditor,
  renderObservationEditor,
  setActivity,
  setBusy,
  showAlert,
};

export function renderBootstrap(payload, selectedInvestigationId = "") {
  const ready = payload.status === "ready" && isObject(payload.workspace);
  elements.setupState.hidden = ready;
  elements.researchDesk.hidden = !ready;
  elements.versionLabel.textContent = payload.version ? `GenomiLab ${payload.version}` : "GenomiLab";
  if (!ready) return;
  renderWorkspace(payload.workspace, selectedInvestigationId);
}

export function renderWorkspace(workspace, selectedInvestigationId = "") {
  const profile = isObject(workspace.profile) ? workspace.profile : {};
  const genome = isObject(profile.genome) ? profile.genome : null;
  const observations = array(profile.observations);
  const investigations = array(workspace.investigations);
  const genomeReady = Boolean(genome && ["query_ready", "ready", "complete", "completed"].includes(text(genome.readiness)));
  elements.currentUserName.textContent = text(workspace.display_name) || "Current Genomi user";
  elements.currentUserId.textContent = text(workspace.user_id);
  elements.genomeStatus.textContent = genomeReady
    ? "Active Genome Index ready"
    : genome ? "Genome setup is not complete" : "Genome setup needed in Genomi";
  elements.genomeStatus.classList.toggle("is-ready", genomeReady);
  elements.genomeDetail.textContent = genome
    ? [text(genome.genome_build), friendly(text(genome.readiness)), shortId(text(genome.agi_snapshot_id))].filter(Boolean).join(" · ")
    : "GenomiLab uses the genome already linked to this Genomi user. It never asks for another VCF.";
  elements.profileSummary.textContent = observations.length
    ? `${observations.length} reviewed profile ${observations.length === 1 ? "observation" : "observations"}`
    : "Start by adding the health or molecular context relevant to your question.";
  renderProfile(profile);
  renderInvestigations(investigations, selectedInvestigationId);
  renderAttention(workspace.attention);
  renderEvidenceLibrary(array(workspace.evidence_library));
  renderPrivacyActivity(workspace.privacy_activity);
}

function renderAttention(attentionValue) {
  const attention = isObject(attentionValue) ? attentionValue : {};
  elements.attentionPlanReviews.textContent = String(Number(attention.plan_reviews) || 0);
  elements.attentionProviderApprovals.textContent = String(Number(attention.provider_approvals) || 0);
  elements.attentionRunningJobs.textContent = String(Number(attention.running_jobs) || 0);
  elements.attentionNewEvidence.textContent = String(Number(attention.new_evidence_records) || 0);
  elements.attentionCompletedBriefs.textContent = String(Number(attention.completed_briefs) || 0);
}

function renderEvidenceLibrary(records) {
  elements.evidenceLibraryCount.textContent = String(records.length);
  if (!records.length) {
    elements.evidenceLibraryList.replaceChildren(node("p", "No evidence has been saved yet.", "empty-row"));
    return;
  }
  const bySource = new Map();
  records.forEach((record) => {
    const source = friendly(text(record.source_family)) || "Other source";
    if (!bySource.has(source)) bySource.set(source, []);
    bySource.get(source).push(record);
  });
  elements.evidenceLibraryList.replaceChildren(...[...bySource].map(([source, sourceRecords]) => {
    const group = node("section", "", "evidence-library-group");
    group.append(node("h3", `${source} (${sourceRecords.length})`));
    const list = node("ul", "", "record-list");
    list.append(...sourceRecords.map((record) => {
      const evidence = isObject(record.evidence) ? record.evidence : {};
      const envelope = isObject(record.evidence_envelope) ? record.evidence_envelope : {};
      const item = node("li", "", "record compact-record");
      const copy = document.createElement("div");
      copy.append(
        node("strong", evidenceHeadline(envelope, record)),
        node("span", `${text(record.investigation_question) || "Investigation"} · ${evidenceReadiness(envelope)}`),
        sourceRecordList(evidence),
        evidenceTraceDetails(record, evidence)
      );
      item.append(copy);
      return item;
    }));
    group.append(list);
    return group;
  }));
}

function renderPrivacyActivity(activityValue) {
  const activity = isObject(activityValue) ? activityValue : {};
  renderCompactRecords(
    elements.contextActivityList,
    array(activity.context_approvals),
    "No private context approvals yet.",
    (item) => [
      item.revoked_at ? "Private context revoked" : "Private context approved",
      [formatTime(text(item.approved_at)), item.agi_snapshot_id ? "Targeted genome context included" : "Profile context only"].filter(Boolean).join(" · "),
    ]
  );
  renderCompactRecords(
    elements.disclosureActivityList,
    array(activity.outbound_disclosures),
    "No outbound disclosures yet.",
    (item) => [
      `${friendly(text(item.recipient_kind)) || "Recipient"}: ${text(item.recipient_id) || "not named"}`,
      [friendly(text(item.destination)), array(item.data_categories).map((value) => friendly(text(value))).join(", "), item.revoked_at ? "Revoked" : "Approved"].filter(Boolean).join(" · "),
    ]
  );
  renderCompactRecords(
    elements.planActivityList,
    array(activity.plan_acceptances),
    "No accepted plans yet.",
    (item) => [
      "Investigation plan accepted",
      `${formatTime(text(item.accepted_at))} · ${shortId(text(item.plan_version_id))}`,
    ]
  );
}

export function renderInvestigations(investigations, selectedInvestigationId = "") {
  elements.investigationCount.textContent = String(investigations.length);
  if (!investigations.length) {
    elements.investigationList.replaceChildren(empty("No disease investigations yet."));
    return;
  }
  const rows = investigations.map((investigation) => {
    const item = node("li", "", "investigation-row");
    const button = node("button", "", "investigation-open");
    button.type = "button";
    button.dataset.investigationId = text(investigation.investigation_id);
    button.setAttribute("aria-current", text(investigation.investigation_id) === selectedInvestigationId ? "true" : "false");
    const copy = document.createElement("span");
    copy.className = "investigation-copy";
    copy.append(
      node("strong", text(investigation.question) || "Disease investigation"),
      node("span", [text(investigation.disease_scope), friendly(text(investigation.status))].filter(Boolean).join(" · "))
    );
    button.append(copy, node("span", "Open →", "open-label"));
    item.append(button);
    return item;
  });
  elements.investigationList.replaceChildren(...rows);
}

export function renderInvestigation(investigation, harnessManifest = {}, observations = []) {
  elements.investigationDetail.hidden = false;
  elements.detailTitle.textContent = text(investigation.question) || "Disease investigation";
  elements.detailScope.textContent = text(investigation.disease_scope) || "No narrower disease scope was supplied.";
  elements.detailStatus.textContent = friendly(text(investigation.status)) || "Created";

  const bindings = array(investigation.harness_bindings);
  const binding = [...bindings].reverse().find((item) => item.binding_state === "active") || null;
  renderHarnessIdentity(harnessManifest, binding);
  renderPlan(investigation.current_plan_version, array(investigation.harness_events));
  renderContextState(investigation);
  renderContextObservationSelection(investigation, observations);
  renderHarnessState(binding, harnessManifest);
  renderEvents({events: array(investigation.harness_events)});
  renderEvidence(
    array(investigation.evidence_records),
    text(investigation.patient_molecular_snapshot_id)
  );
  renderCapabilityApprovals(array(investigation.current_capability_executions));
  renderHypotheses(
    array(investigation.hypotheses),
    text(investigation.patient_molecular_snapshot_id)
  );
  renderBriefs(array(investigation.brief_versions), investigation);
  hideContextCandidate();
  hideOutboundPreview();
}

function renderContextObservationSelection(investigation, observations) {
  const investigationId = text(investigation.investigation_id);
  const previousInvestigationId = text(
    elements.contextObservationList.dataset.investigationId
  );
  const previousInputs = [...elements.contextObservationList.querySelectorAll(
    "input[name='context_observation_revision_id']"
  )];
  const preserveSelection = previousInvestigationId === investigationId
    && previousInputs.length > 0;
  const previousSelection = new Set(
    previousInputs.filter((input) => input.checked).map((input) => text(input.value))
  );
  const activeSnapshotId = text(investigation.patient_molecular_snapshot_id);
  const pinnedSnapshot = array(investigation.profile_snapshot_history).find(
    (item) => text(item.patient_molecular_snapshot_id) === activeSnapshotId
  );
  const pinnedIds = new Set(array(pinnedSnapshot && pinnedSnapshot.observation_revision_ids).map(text));
  elements.contextSelectionHelp.textContent = pinnedSnapshot
    ? "Checked observations are the starting selection for Compare latest profile. Review and renew keeps the exact pinned selection."
    : "Select at least one current observation. Only checked observations can enter this investigation's approved profile context.";
  if (!observations.length) {
    elements.contextObservationList.dataset.investigationId = investigationId;
    elements.contextObservationList.replaceChildren(
      empty("Add a profile observation before approving private context.")
    );
    return;
  }
  const rows = observations.map((observation) => {
    const revisionId = text(observation.observation_revision_id);
    const item = node("li", "", "context-observation-option");
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = "context_observation_revision_id";
    input.value = revisionId;
    input.checked = preserveSelection
      ? previousSelection.has(revisionId)
      : Boolean(pinnedSnapshot && pinnedIds.has(revisionId));
    const copy = document.createElement("span");
    copy.append(
      node("strong", text(observation.label) || "Untitled observation"),
      node(
        "small",
        [
          friendly(text(observation.modality)),
          friendly(text(observation.assertion_status)),
          friendly(text(observation.verification_state)),
          pinnedIds.has(revisionId) ? "Pinned now" : "Current profile",
        ].filter(Boolean).join(" · ")
      )
    );
    label.append(input, copy);
    item.append(label);
    return item;
  });
  elements.contextObservationList.dataset.investigationId = investigationId;
  elements.contextObservationList.replaceChildren(...rows);
}

export function closeInvestigation() {
  elements.investigationDetail.hidden = true;
  elements.contextObservationList.dataset.investigationId = "";
  hideContextCandidate();
  hideOutboundPreview();
}

export function renderContextCandidate(candidate, observations = []) {
  elements.contextPreview.hidden = false;
  elements.contextPreviewPurpose.textContent = `Purpose: ${text(candidate.purpose) || "Use this context only for this disease investigation."}`;
  const definitions = [];
  const selectedIds = array(candidate.observation_revision_ids).map(text);
  const observationsById = new Map(observations.map((item) => [text(item.observation_revision_id), item]));
  const selectedObservations = selectedIds.map((id) => observationsById.get(id)).filter(Boolean);
  definitions.push([
    "Profile observations",
    selectedObservations.length
      ? selectedObservations.map(observationDescription).join("; ")
      : selectedIds.length ? selectedIds.join(", ") : "None",
  ]);
  definitions.push(["Source records", countDescription(candidate.artifact_ids, "record")]);
  definitions.push(["Specimens", countDescription(candidate.specimen_ids, "specimen")]);
  definitions.push(["Assays", countDescription(candidate.assay_ids, "assay")]);
  definitions.push([
    "Genome",
    candidate.agi_snapshot_id
      ? `Active Genome Index revision ${text(candidate.agi_snapshot_id)} (reference only; no copied genome rows)`
      : "Not included",
  ]);
  definitions.push(["Allowed genome scope", candidate.genomic_scope ? exactValue(candidate.genomic_scope) : "Not included"]);
  definitions.push(["Profile coverage", coverageDescription(candidate.modality_coverage)]);
  replaceDefinitions(elements.contextPreviewList, definitions);
  elements.contextApproveButton.disabled = false;
}

export function hideContextCandidate() {
  elements.contextPreview.hidden = true;
  elements.contextPreviewList.replaceChildren();
}

export function renderOutboundPreview(candidate) {
  const payload = isObject(candidate.payload) ? candidate.payload : {};
  const manifest = isObject(candidate.capability_manifest) ? candidate.capability_manifest : {};
  elements.harnessOutboundPreview.hidden = false;
  elements.harnessOutboundDestination.textContent = [
    `Recipient: ${text(manifest.host_kind) || text(candidate.recipient_id) || "installed harness"}`,
    `Execution location: ${friendly(text(candidate.destination) || text(manifest.execution_location)) || "not disclosed"}`,
  ].join(" · ");
  const definitions = [
    ["Action", friendly(text(payload.operation)) || "Harness work"],
    ["Instruction", text(payload.instruction) || "None"],
    ["Requested output", friendly(text(payload.artifact_kind)) || "Not specified"],
    ["Data categories", array(candidate.data_categories).map((value) => friendly(text(value))).join(", ") || "None"],
    ["Private context", contextDisclosureDescription(payload.approved_context)],
    ["Exact outbound contents", exactValue(payload), "exact"],
  ];
  replaceDefinitions(elements.harnessOutboundDetails, definitions);
  const operation = text(payload.operation);
  elements.harnessApproveButton.textContent = {
    start_task_run: "Approve and start harness",
    resume_task_run: "Approve and resume harness",
    send_task_message: "Approve and send message",
    replace_task_binding: "Approve and replace harness task",
    cancel_task_work: "Approve and cancel harness work",
  }[operation] || "Approve this disclosure";
  elements.harnessApproveButton.disabled = false;
}

export function hideOutboundPreview() {
  elements.harnessOutboundPreview.hidden = true;
  elements.harnessOutboundDetails.replaceChildren();
}

export function renderEvents(payload) {
  const events = array(payload.events);
  elements.eventStatus.textContent = events.length
    ? `${events.length} ${events.length === 1 ? "event" : "events"} connected`
    : "Connected · no events yet";
  if (!events.length) {
    elements.eventList.replaceChildren(empty("No harness events yet."));
    return;
  }
  const rows = events.map((event) => {
    const transport = isObject(event.payload) ? event.payload : {};
    const details = isObject(transport.payload) ? transport.payload : {};
    const description = text(details.progress)
      || text(details.message)
      || text(details.role)
      || friendly(text(transport.status))
      || "Harness activity recorded";
    const item = node("li", "", "event-row");
    const marker = node("span", "", "event-marker");
    marker.setAttribute("aria-hidden", "true");
    const copy = document.createElement("div");
    copy.append(
      node("strong", friendly(text(event.event_type) || text(transport.kind)) || "Harness event"),
      node("p", description),
      node("time", formatTime(text(transport.timestamp) || text(event.created_at)))
    );
    item.append(marker, copy);
    return item;
  });
  elements.eventList.replaceChildren(...rows);
}

function renderHarnessIdentity(manifest, binding) {
  const hostKind = friendly(text(manifest.host_kind)) || "Installed agent harness";
  elements.harnessName.textContent = hostKind;
  elements.harnessLocation.textContent = manifest.execution_location
    ? `Agents and reasoning run at: ${friendly(text(manifest.execution_location))}. GenomiLab remains the domain workspace.`
    : "The harness has not disclosed its execution location.";
  const available = manifest.available === true;
  elements.harnessCapability.textContent = available ? "Available" : "Unavailable";
  elements.harnessCapability.dataset.available = available ? "true" : "false";
  elements.harnessDisclosure.textContent = binding
    ? `This investigation is connected to task ${shortId(text(binding.task_id)) || "in the installed harness"}. The web portal displays state and approvals; the harness owns agents and reasoning.`
    : "This web portal displays and approves work. GenomiLab manages the investigation; the disclosed installed harness owns the agents, planning, and reasoning.";
}

function renderPlan(planVersionValue, events) {
  const planVersion = isObject(planVersionValue) ? planVersionValue : null;
  const plan = planVersion && isObject(planVersion.plan) ? planVersion.plan : null;
  const steps = plan ? array(plan.steps) : [];
  const accepted = Boolean(planVersion && text(planVersion.review_status) === "accepted");
  elements.planReviewStatus.textContent = plan
    ? accepted ? "Accepted" : "Your review needed"
    : "No plan to review";
  elements.planReviewStatus.dataset.state = accepted ? "accepted" : plan ? "proposed" : "none";
  elements.planReviewActions.hidden = !plan || accepted;
  elements.planAcceptButton.disabled = !plan || accepted;
  elements.planSummary.textContent = plan
    ? text(plan.summary) || "Current plan"
    : "The installed harness has not proposed a plan yet.";
  if (!steps.length) {
    elements.planList.replaceChildren(empty("No plan steps yet."));
    elements.progressSummary.textContent = "Waiting for a plan";
    return;
  }
  const progressByStep = new Map();
  events.forEach((event) => {
    const transport = isObject(event.payload) ? event.payload : {};
    const progress = isObject(transport.payload) ? transport.payload : {};
    const stepId = text(progress.assigned_step_id);
    if (stepId) progressByStep.set(stepId, text(progress.progress) || friendly(text(transport.status)));
  });
  const rows = steps.map((step, index) => {
    const item = node("li", "", "plan-step");
    const number = node("span", String(index + 1), "plan-number");
    const copy = document.createElement("div");
    const stepId = text(step.id);
    const progress = progressByStep.get(stepId) || friendly(text(step.status)) || "Planned";
    copy.append(
      node("strong", text(step.title) || `Step ${index + 1}`),
      node("p", array(step.capabilities).map((value) => friendly(text(value))).join(" · ") || "Research step"),
      node("span", progress, "step-progress")
    );
    item.append(number, copy);
    return item;
  });
  elements.planList.replaceChildren(...rows);
  elements.progressSummary.textContent = accepted
    ? `${steps.length} accepted ${steps.length === 1 ? "step" : "steps"}`
    : `${steps.length} proposed ${steps.length === 1 ? "step" : "steps"}`;
}

function renderContextState(investigation) {
  const status = text(investigation.private_context_status) || "not_approved";
  const approved = status === "approved_for_session";
  const pinned = Boolean(investigation.patient_molecular_snapshot_id);
  const lifecycle = isObject(investigation.refresh_lifecycle)
    ? friendly(text(investigation.refresh_lifecycle.state))
    : "";
  elements.contextState.textContent = approved
    ? ["Approved for this session", lifecycle].filter(Boolean).join(" · ")
    : pinned ? "Pinned history · approval renewal required" : "Not approved";
  elements.contextPreviewButton.textContent = pinned ? "Review and renew private context" : "Preview private context";
  elements.contextRefreshPreviewButton.hidden = !pinned;
  elements.contextRevokeButton.hidden = !approved;
}

function renderCapabilityApprovals(executions) {
  const pendingApprovals = executions.filter((execution) => {
    const result = isObject(execution.result) ? execution.result : {};
    return text(execution.status) === "approval_required" || text(result.status) === "approval_required";
  });
  const running = executions.filter((execution) => {
    const result = isObject(execution.result) ? execution.result : {};
    return text(execution.status) === "in_progress"
      && text(result.resume_operation) !== "genomilab.capability.execute";
  });
  if (!pendingApprovals.length && !running.length) {
    elements.capabilityApprovalList.replaceChildren();
    return;
  }
  const heading = node("h4", "Agent-requested capability work");
  const intro = node(
    "p",
    "Review exact evidence egress before approval, and reconnect only to the job already recorded for work that is still running.",
    "section-summary"
  );
  const list = node("ul", "", "approval-request-list");
  pendingApprovals.forEach((execution) => {
    const result = isObject(execution.result) ? execution.result : {};
    const candidate = isObject(result.candidate) ? result.candidate : {};
    const routes = array(candidate.routes);
    const selected = text(candidate.selected_provider);
    const route = routes.find((item) => isObject(item) && text(item.provider) === selected) || {};
    const item = node("li", "", "approval-request-row");
    const copy = document.createElement("div");
    const payload = isObject(candidate.payload) && isObject(candidate.payload.request)
      ? candidate.payload.request
      : {};
    copy.append(
      node("strong", `Evidence request: ${friendly(text(payload.source_family)) || "public evidence"}`),
      node("p", text(payload.query) || "The exact query is unavailable."),
      node(
        "span",
        selected
          ? `Provider: ${friendly(selected)} · Destination: ${friendly(text(route.destination)) || "not disclosed"}`
          : "No eligible provider route is currently configured.",
        "record-trace-line"
      )
    );
    const button = node("button", selected ? "Approve exact evidence request" : "Provider unavailable", "secondary-button");
    button.type = "button";
    button.disabled = !selected;
    button.dataset.capabilityAction = "approve";
    button.dataset.capabilityRequestId = text(execution.request_id);
    button.dataset.planVersionId = text(execution.plan_version_id);
    button.dataset.recipientProvider = selected;
    button.dataset.payloadSha256 = text(candidate.payload_sha256);
    item.append(copy, button);
    list.append(item);
  });
  running.forEach((execution) => {
    const result = isObject(execution.result) ? execution.result : {};
    const item = node("li", "", "approval-request-row");
    const copy = document.createElement("div");
    copy.append(
      node("strong", `Background work: ${friendly(text(execution.capability))}`),
      node("p", "The original request will not be submitted again."),
      node(
        "span",
        `Job: ${text(result.job_id)} · Check: ${friendly(text(result.resume_operation))}`,
        "record-trace-line"
      )
    );
    const button = node("button", "Check recorded job", "secondary-button");
    button.type = "button";
    button.dataset.capabilityAction = "check";
    button.dataset.capabilityRequestId = text(execution.request_id);
    button.dataset.planVersionId = text(execution.plan_version_id);
    button.dataset.jobId = text(result.job_id);
    button.dataset.resumeOperation = text(result.resume_operation);
    item.append(copy, button);
    list.append(item);
  });
  elements.capabilityApprovalList.replaceChildren(heading, intro, list);
}

function renderHarnessState(binding, manifest) {
  const available = manifest.available === true;
  const operations = new Set(array(manifest.supported_operations).map(text));
  const started = Boolean(binding);
  elements.harnessBindingState.textContent = started
    ? friendly(text(binding.harness_status)) || "Connected"
    : "Not started";
  elements.harnessPreviewButton.hidden = started;
  elements.harnessPreviewButton.disabled = !available || !operations.has("start_task_run");
  elements.resumePreviewButton.hidden = !started || !operations.has("resume_task_run");
  elements.resumePreviewButton.textContent = "Replan with approved context";
  elements.replaceHarnessButton.hidden = !started || !operations.has("replace_task_binding");
  elements.cancelHarnessButton.hidden = !started || !operations.has("cancel_task_work");
  elements.harnessMessageForm.hidden = !started || !operations.has("send_task_message");
}
