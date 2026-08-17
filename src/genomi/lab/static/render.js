"use strict";

import {
  array,
  collectElements,
  countDescription,
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
import { renderResearchArtifacts } from "./render-research-artifacts.js";
import { renderSpecialistBoard } from "./render-specialist-board.js";
import {
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
  if (!ready) {
    const setup = isObject(payload.setup) ? payload.setup : {};
    elements.genomiSetupPrompt.textContent = text(setup.action)
      || "Return to the underlying agent. Point it to the local VCF or another supported genome-source path, or ask it to select and finish an existing Active Genome Index. Reopen GenomiLab when the selected index is query-ready.";
    return;
  }
  renderWorkspace(payload.workspace, selectedInvestigationId);
}

export function renderWorkspace(workspace, selectedInvestigationId = "") {
  const profile = isObject(workspace.profile) ? workspace.profile : {};
  const genome = isObject(profile.genome) ? profile.genome : null;
  const observations = array(profile.observations);
  const investigations = array(workspace.investigations);
  const genomeReady = Boolean(genome && ["query_ready", "ready", "complete", "completed", "variants_ready"].includes(text(genome.readiness)));
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
  const authorizations = array(activity.investigation_authorizations);
  const authorizedConsentReceipts = new Set(
    authorizations.map((item) => text(item.consent_receipt_id)).filter(Boolean)
  );
  const contextActivity = [
    ...authorizations.map((item) => ({...item, activity_kind: "investigation_authorization"})),
    ...array(activity.context_approvals)
      .filter((item) => !authorizedConsentReceipts.has(text(item.consent_receipt_id)))
      .map((item) => ({...item, activity_kind: "private_context"})),
  ].sort((left, right) => text(right.approved_at).localeCompare(text(left.approved_at)));
  renderCompactRecords(
    elements.contextActivityList,
    contextActivity,
    "No research authorizations yet.",
    (item) => item.activity_kind === "investigation_authorization"
      ? [
        item.revoked_at ? "Research authorization revoked" : "Research authorized",
        [formatTime(text(item.approved_at)), authorizationScopeDescription(item.authorization_scope)].filter(Boolean).join(" · "),
      ]
      : [
        item.revoked_at ? "Private context revoked" : "Private context included",
        [formatTime(text(item.approved_at)), item.agi_snapshot_id ? "Targeted genome context included" : "Profile context only"].filter(Boolean).join(" · "),
      ]
  );
  renderCompactRecords(
    elements.disclosureActivityList,
    array(activity.outbound_disclosures),
    "No outbound disclosures yet.",
    (item) => [
      `${friendly(text(item.recipient_kind)) || "Recipient"}: ${text(item.recipient_id) || "not named"}`,
      [friendly(text(item.destination)), array(item.data_categories).map((value) => friendly(text(value))).join(", "), item.revoked_at ? "Revoked" : item.authorization_receipt_id ? "Covered by research authorization" : "Exact exception approved"].filter(Boolean).join(" · "),
    ]
  );
  renderCompactRecords(
    elements.planActivityList,
    array(activity.plan_acceptances),
    "No working plans adopted yet.",
    (item) => [
      item.authorization_receipt_id ? "Working plan adopted under research authorization" : "Investigation plan accepted",
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

export function renderInvestigation(investigation, agentManifest = {}, profile = {}) {
  const observations = array(profile.observations);
  elements.investigationDetail.hidden = false;
  elements.detailTitle.textContent = text(investigation.question) || "Disease investigation";
  elements.detailScope.textContent = text(investigation.disease_scope) || "No narrower disease scope was supplied.";
  elements.detailStatus.textContent = friendly(text(investigation.status)) || "Created";

  const events = array(investigation.investigation_events);
  renderAgentIdentity(agentManifest);
  renderPlan(investigation.current_plan_version);
  renderSpecialistBoard(investigation.specialist_board, investigation.current_round);
  renderContextState(investigation);
  renderContextObservationSelection(investigation, observations);
  renderAgentState(investigation, agentManifest);
  renderEvents({events});
  renderEvidence(
    array(investigation.evidence_records),
    text(investigation.patient_molecular_snapshot_id)
  );
  renderResearchArtifacts(investigation.current_research_artifacts);
  renderCapabilityApprovals(array(investigation.current_capability_executions));
  renderHypotheses(
    array(investigation.current_hypotheses),
    text(investigation.patient_molecular_snapshot_id)
  );
  renderBriefs(array(investigation.brief_versions), investigation, profile);
  hideContextCandidate();
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
    ? "Checked observations are the current authorized scope. Compare the latest profile before approving any expansion."
    : "Select at least one current observation. Only checked observations can enter this investigation's research scope.";
  if (!observations.length) {
    elements.contextObservationList.dataset.investigationId = investigationId;
    elements.contextObservationList.replaceChildren(
      empty("Add a profile observation before authorizing research context.")
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
  definitions.push(["Allowed genome scope", genomicScopeDescription(candidate.genomic_scope)]);
  definitions.push(["Profile coverage", coverageDescription(candidate.modality_coverage)]);
  definitions.push(["Routine work covered", authorizationScopeDescription(candidate.authorization_scope)]);
  replaceDefinitions(elements.contextPreviewList, definitions);
  elements.contextApproveButton.textContent = candidate.refresh === true
    ? "Authorize updated research context"
    : "Authorize research context";
  elements.contextApproveButton.disabled = false;
}

export function genomicScopeDescription(value) {
  const scope = isObject(value) ? value : null;
  if (!scope) return "Not included";
  if (text(scope.operation) === "variant.find_gene_variants") {
    return [
      text(scope.genome_build),
      `Main Investigator may check 1–${Number(scope.gene_count_limit) || 10} named candidate genes`,
      scope.passing_filters_only === true ? "passing calls only" : "filter policy not recorded",
      `up to ${Number(scope.per_gene_limit) || 100} records per gene`,
      "specialists cannot access the genome",
    ].filter(Boolean).join(" · ");
  }
  return exactValue(scope);
}

export function hideContextCandidate() {
  elements.contextPreview.hidden = true;
  elements.contextPreviewList.replaceChildren();
}

export function renderEvents(payload) {
  const events = visibleInvestigationEvents(payload.events);
  elements.eventStatus.textContent = events.length
    ? `${events.length} committed ${events.length === 1 ? "update" : "updates"}`
    : "Monitoring · no committed updates";
  if (!events.length) {
    elements.eventList.replaceChildren(empty("No committed investigation activity yet."));
    return;
  }
  const rows = events.map((event) => {
    const details = isObject(event.payload) ? event.payload : {};
    const description = investigationEventDescription(text(event.event_type), details);
    const item = node("li", "", "event-row");
    const marker = node("span", "", "event-marker");
    marker.setAttribute("aria-hidden", "true");
    const copy = document.createElement("div");
    copy.append(
      node("strong", investigationEventTitle(event.event_type)),
      node("p", description),
      node("time", formatTime(text(event.created_at)))
    );
    item.append(marker, copy);
    return item;
  });
  elements.eventList.replaceChildren(...rows);
}

export function investigationEventTitle(eventTypeValue) {
  return friendly(text(eventTypeValue)) || "Investigation activity";
}

export function visibleInvestigationEvents(eventsValue) {
  return array(eventsValue);
}

function investigationEventDescription(eventType, details) {
  if (eventType === "context_approval_required") {
    return details.refresh === true
      ? "Updated patient context is ready for review and approval."
      : "Patient context is ready for review and approval.";
  }
  if (eventType === "context_authorized") {
    return "The exact patient context was authorized for the current agent session.";
  }
  if (eventType === "patient_information_recorded") {
    return details.requires_context_refresh === true
      ? "New patient information was recorded; review the updated context before genome-informed work continues."
      : "New patient information was recorded.";
  }
  if (eventType === "plan_accepted") {
    return `Working plan committed${details.plan_version_id ? ` · ${text(details.plan_version_id)}` : ""}`;
  }
  if (eventType === "specialist_board_formed") {
    const memberCount = Number(details.member_count) || array(details.members).length;
    return memberCount
      ? `Specialist board formed with ${memberCount} ${memberCount === 1 ? "member" : "members"}.`
      : "Specialist board formed.";
  }
  if (eventType === "specialist_progress_reported") {
    const progress = [
      text(details.specialist_id),
      friendly(text(details.status)),
      text(details.current_work),
    ].filter(Boolean).join(" · ");
    return progress || "Specialist progress updated.";
  }
  if (eventType === "request_started" || eventType === "request_state_changed") {
    return [text(details.request_id), friendly(text(details.status)) || "Started"]
      .filter(Boolean)
      .join(" · ");
  }
  if (eventType === "brief_published") {
    return `Investigation brief published${details.version ? ` · version ${text(details.version)}` : ""}`;
  }
  if (eventType === "private_context_revoked") {
    return "Future GenomiLab access to private patient context was revoked.";
  }
  return text(details.summary)
    || text(details.question)
    || friendly(text(details.status))
    || "Investigation update committed";
}

function renderAgentIdentity(manifest) {
  const hostId = text(manifest.agent_session_id);
  elements.agentName.textContent = hostId && hostId !== "underlying-agent"
    ? hostId
    : "Current Claude or Codex agent";
  elements.agentLocation.textContent = manifest.processing_destination
    ? `Task, conversation, and reasoning remain in ${text(manifest.processing_destination)}. GenomiLab stores only its domain records.`
    : "The current agent session owns the task, conversation, planning, and reasoning.";
  const agentOwned = text(manifest.execution_owner) === "underlying_agent";
  elements.agentCapability.textContent = agentOwned ? "Agent-owned" : "Unavailable";
  elements.agentCapability.dataset.available = agentOwned ? "true" : "false";
  elements.agentDisclosure.textContent = agentOwned
    ? "GenomiLab records patient context and committed investigation updates. Continue, redirect, pause, or cancel the task in Claude or Codex."
    : "No underlying agent session is attached. GenomiLab cannot start or control a task from this portal.";
  elements.returnToAgentButton.hidden = !agentOwned;
  elements.returnToAgentButton.title = text(manifest.processing_destination)
    || "Return to the underlying agent";
}

function renderPlan(planVersionValue) {
  const planVersion = isObject(planVersionValue) ? planVersionValue : null;
  const plan = planVersion && isObject(planVersion.plan) ? planVersion.plan : null;
  const steps = plan ? array(plan.steps) : [];
  elements.planReviewStatus.textContent = plan ? "Working plan" : "Waiting for a working plan";
  elements.planReviewStatus.dataset.state = plan ? "active" : "none";
  elements.planSummary.textContent = plan
    ? text(plan.summary) || "Current plan"
    : "The underlying agent has not committed a plan yet.";
  if (!steps.length) {
    elements.planList.replaceChildren(empty("No plan steps yet."));
    elements.progressSummary.textContent = "Waiting for a plan";
    return;
  }
  const rows = steps.map((step, index) => {
    const item = node("li", "", "plan-step");
    const number = node("span", String(index + 1), "plan-number");
    const copy = document.createElement("div");
    const progress = friendly(text(step.status)) || "Planned";
    copy.append(
      node("strong", text(step.title) || `Step ${index + 1}`),
      node("p", array(step.capabilities).map((value) => friendly(text(value))).join(" · ") || "Research step"),
      node("span", progress, "step-progress")
    );
    item.append(number, copy);
    return item;
  });
  elements.planList.replaceChildren(...rows);
  elements.progressSummary.textContent = `${steps.length} planned ${steps.length === 1 ? "step" : "steps"}`;
}

function renderContextState(investigation) {
  const status = text(investigation.private_context_status) || "not_approved";
  const approved = status === "approved_for_session";
  const pinned = Boolean(investigation.patient_molecular_snapshot_id);
  const lifecycle = isObject(investigation.refresh_lifecycle)
    ? friendly(text(investigation.refresh_lifecycle.state))
    : "";
  elements.contextState.textContent = approved
    ? ["Authorized", lifecycle].filter(Boolean).join(" · ")
    : pinned ? "Review access to continue" : "Not authorized";
  elements.contextPreviewButton.textContent = pinned ? "Review current research access" : "Review research access";
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
    const queryTerms = array(payload.query_terms).map((value) => text(value)).filter(Boolean);
    const filters = isObject(payload.filters)
      ? Object.entries(payload.filters).map(([key, value]) => `${friendly(key)}: ${text(value)}`)
      : [];
    const handling = isObject(route.retention_training_state)
      ? route.retention_training_state
      : {};
    const policy = isObject(route.policy_binding) ? route.policy_binding : {};
    copy.append(
      node("strong", `Evidence request: ${friendly(text(payload.source_family)) || "public evidence"}`),
      node("p", text(payload.query) || "The exact query is unavailable."),
      node(
        "span",
        selected
          ? `Provider: ${friendly(selected)} · Destination: ${friendly(text(route.destination)) || "not disclosed"}`
          : "No eligible provider route is currently configured.",
        "record-trace-line"
      ),
      node(
        "span",
        [
          `Operation: ${friendly(text(candidate.payload && candidate.payload.operation)) || "not disclosed"}`,
          `Purpose: ${text(payload.purpose) || "not disclosed"}`,
          `Data: ${friendly(text(payload.data_class)) || "not disclosed"}`,
        ].join(" · "),
        "record-trace-line"
      ),
      node(
        "span",
        `Query terms: ${queryTerms.length ? queryTerms.join(", ") : "none"} · Filters: ${filters.length ? filters.join(", ") : "none"}`,
        "record-trace-line"
      ),
      node(
        "span",
        [
          `Retention: ${friendly(text(handling.retention)) || "not disclosed"}`,
          `Training: ${friendly(text(handling.training)) || "not disclosed"}`,
          policy.patient_data_contract_id
            ? `Patient-data contract: ${shortId(text(policy.patient_data_contract_id))}`
            : "Patient-data contract: not active",
        ].join(" · "),
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
    button.dataset.approvalSha256 = text(candidate.approval_sha256);
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

function renderAgentState(investigation, manifest) {
  if (text(manifest.execution_owner) !== "underlying_agent") {
    elements.agentExecutionState.textContent = "Agent unavailable";
    return;
  }
  const status = text(investigation.status);
  elements.agentExecutionState.textContent = status
    ? `Monitoring · ${friendly(status)}`
    : "Monitoring enabled";
}

function authorizationScopeDescription(value) {
  if (isObject(value)) {
    const summary = text(value.summary);
    if (summary) return summary;
    const activities = array(value.routine_activities).map((item) => friendly(text(item)));
    if (activities.length) return activities.join(", ");
    const agentSession = isObject(value.agent_session) ? value.agent_session : {};
    const destination = text(agentSession.destination);
    const intents = array(agentSession.allowed_intents).map((item) => friendly(text(item)));
    if (destination || intents.length) {
      return [
        destination ? `Current agent session at ${destination}` : "Current agent session",
        intents.length ? intents.join(", ") : "routine investigation work",
      ].join(" · ");
    }
  }
  return "GenomiLab access for planning, local evidence work, replanning, and follow-up investigation updates within this exact context scope.";
}
