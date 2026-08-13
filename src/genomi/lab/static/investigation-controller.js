"use strict";

import { apiRequest, postJson, waitForEvents } from "./api.js";
import { setFormBusy } from "./form-controls.js";
import {
  closeInvestigation,
  elements,
  hideContextCandidate,
  hideOutboundPreview,
  renderContextCandidate,
  renderEvents,
  renderInvestigation,
  renderOutboundPreview,
  renderWorkspace,
  setActivity,
  setBusy,
  showAlert,
} from "./render.js";

export function createInvestigationController({state, session, refresh, synchronizeProfile}) {
  function bind() {
    elements.questionForm.addEventListener("submit", handleQuestion);
    elements.investigationList.addEventListener("click", handleInvestigationSelection);
    elements.detailClose.addEventListener("click", close);
    elements.contextPreviewButton.addEventListener("click", () => void previewPrivateContext());
    elements.contextRefreshPreviewButton.addEventListener(
      "click", () => void previewPrivateContext({refresh: true})
    );
    elements.contextApproveButton.addEventListener("click", () => void approvePrivateContext());
    elements.contextObservationList.addEventListener("change", invalidateContextCandidate);
    elements.contextRevokeButton.addEventListener("click", () => void revokePrivateContext());
    elements.planAcceptButton.addEventListener("click", () => void acceptCurrentPlan());
    elements.planChangeForm.addEventListener("submit", handlePlanChangePreview);
    elements.harnessPreviewButton.addEventListener(
      "click", () => void previewHarness("start_task_run")
    );
    elements.resumePreviewButton.addEventListener("click", () => void previewHarness(
      "resume_task_run",
      "Replan this investigation from the latest approved molecular profile, committed evidence, and open gaps.",
      "",
      "plan"
    ));
    elements.replaceHarnessButton.addEventListener("click", () => void previewHarness(
      "replace_task_binding",
      "",
      "Replace the current installed-harness task while preserving this GenomiLab investigation.",
      "plan"
    ));
    elements.harnessMessageForm.addEventListener("submit", handleHarnessMessagePreview);
    elements.harnessApproveButton.addEventListener("click", () => void approveHarnessDisclosure());
    elements.cancelHarnessButton.addEventListener("click", () => void cancelHarnessWork());
    elements.reconnectEventsButton.addEventListener("click", () => void reconnectEvents());
    elements.capabilityApprovalList.addEventListener("click", handleCapabilityApproval);
  }

  async function handleQuestion(event) {
    event.preventDefault();
    if (!elements.questionForm.reportValidity()) return;
    setFormBusy(elements.questionForm, elements.questionSubmit, true, "Creating…");
    setActivity("Creating a durable disease investigation…");
    try {
      const created = await postJson("/api/v1/investigations", {
        question: elements.question.value.trim(),
        disease_scope: elements.diseaseScope.value.trim() || undefined,
      });
      elements.questionForm.reset();
      session.beginOpen(String(created.investigation_id || ""));
      showAlert("Investigation created. Review what will be sent before starting the installed harness.", "success");
      await refresh();
    } catch (error) {
      showAlert(error.message || "The investigation could not be created.");
    } finally {
      setFormBusy(elements.questionForm, elements.questionSubmit, false);
    }
  }

  function handleInvestigationSelection(event) {
    const button = event.target.closest("button[data-investigation-id]");
    if (!button || !elements.investigationList.contains(button)) return;
    const investigationId = String(button.dataset.investigationId || "");
    if (investigationId) void open(investigationId, {focus: true});
  }

  function close() {
    session.close();
    hideContextCandidate();
    hideOutboundPreview();
    closeInvestigation();
    if (state.workspace()) renderWorkspace(state.workspace());
    elements.investigationList.scrollIntoView({block: "start"});
    setActivity("Investigation closed. Research Desk ready.");
  }

  async function open(investigationId, {focus = true} = {}) {
    const openRequest = session.beginOpen(investigationId);
    const investigationLoad = session.beginInvestigationLoad(openRequest);
    hideContextCandidate();
    hideOutboundPreview();
    setActivity("Opening the investigation and reconnecting its activity…");
    try {
      const investigation = await apiRequest(pathFor(investigationId));
      if (!session.acceptInvestigationLoad(investigationLoad, investigation)) return;
      renderCurrentInvestigation();
      if (state.workspace()) renderWorkspace(state.workspace(), investigationId);
      await reconnectEvents({announce: false, openRequest});
      if (!session.isCurrent(openRequest)) return;
      startEventStream();
      if (focus) {
        elements.investigationDetail.scrollIntoView({block: "start"});
        elements.investigationDetail.focus({preventScroll: true});
      }
      setActivity("Investigation open.");
    } catch (error) {
      if (!session.isCurrent(openRequest)) return;
      showAlert(error.message || "The investigation could not be opened.");
      setActivity("Investigation unavailable.");
    }
  }

  function invalidateContextCandidate() {
    session.invalidateContextSelection();
    hideContextCandidate();
    setActivity("Profile selection changed. Preview the exact private context again before approval.");
  }

  function discardContextCandidate() {
    session.discardContextCandidate();
    hideContextCandidate();
  }

  function discardOutboundCandidate() {
    session.discardOutboundCandidate();
    hideOutboundPreview();
  }

  async function previewPrivateContext({refresh: useCurrentAgi = false} = {}) {
    const investigation = session.investigation;
    if (!investigation) return;
    const previewRequest = session.beginContextPreview();
    hideContextCandidate();
    const sourceButton = useCurrentAgi
      ? elements.contextRefreshPreviewButton
      : elements.contextPreviewButton;
    const pinned = !useCurrentAgi ? pinnedProfileSnapshot() : null;
    const selectedObservationRevisionIds = pinned ? [] : selectedContextObservationRevisionIds();
    if (!pinned && !selectedObservationRevisionIds.length) {
      showAlert("Select at least one profile observation for this investigation.");
      const firstObservation = elements.contextObservationList.querySelector("input");
      if (firstObservation) firstObservation.focus();
      return;
    }
    setBusy(sourceButton, true, "Preparing preview…");
    setActivity("Preparing the exact private context preview…");
    try {
      const candidatePayload = {
        purpose: pinned
          ? pinned.purpose
          : `Investigate: ${String(investigation.question || "disease question")}`,
        use_current_agi: useCurrentAgi,
      };
      if (!pinned) candidatePayload.observation_revision_ids = selectedObservationRevisionIds;
      let preparedCandidate;
      let comparisonStatus = "";
      if (useCurrentAgi && investigation.patient_molecular_snapshot_id) {
        const compared = await postJson(session.path("/context-compare"), candidatePayload);
        preparedCandidate = {...compared.candidate, refresh: true};
        comparisonStatus = String(compared.status || "");
      } else {
        preparedCandidate = await postJson(session.path("/context-candidate"), candidatePayload);
      }
      if (!session.acceptContextCandidate(previewRequest, preparedCandidate)) {
        if (session.isCurrent(previewRequest.open)) {
          setActivity("The profile selection changed while the preview was prepared. Preview it again.");
        }
        return;
      }
      if (comparisonStatus) {
        showAlert(
          comparisonStatus === "changed"
            ? "The latest profile differs from the pinned context. Approving will create a new immutable context version."
            : "The latest profile matches the pinned context; approval will only renew this session.",
          "success"
        );
      }
      renderContextCandidate(session.contextCandidate, profileObservations());
      setActivity("Private context preview ready. Nothing has been approved yet.");
    } catch (error) {
      if (!session.isCurrentContextPreview(previewRequest)) return;
      showAlert(error.message || "The private context preview could not be prepared.");
    } finally {
      setBusy(sourceButton, false, "");
    }
  }

  async function approvePrivateContext() {
    if (!session.contextCandidate) return;
    const approvedCandidate = session.contextCandidate;
    const openRequest = session.openRequest();
    setBusy(elements.contextApproveButton, true, "Approving…");
    setActivity("Recording consent for exactly the previewed context…");
    try {
      const approval = {...approvedCandidate};
      delete approval.status;
      delete approval.requires_explicit_approval;
      delete approval.user_id;
      delete approval.investigation_id;
      approval.approved = true;
      const approvedContext = await postJson(session.path("/context-approval"), approval);
      if (!session.isCurrent(openRequest)) return;
      const selectionChangedWhileApproving = session.contextCandidate !== approvedCandidate;
      discardContextCandidate();
      showAlert(
        selectionChangedWhileApproving
          ? "The exact context you approved was saved. Selection changes made while it was being saved were not included; compare the latest profile before replanning."
          : approvedContext.context_change === "profile_refreshed"
          ? "A new immutable profile context was approved. Replan to refresh evidence and the brief."
          : "Private context approved for this investigation and local session.",
        "success"
      );
      await reloadCurrentInvestigation();
      setActivity("Private context approved. Use Replan with approved context so the harness can choose targeted capabilities.");
    } catch (error) {
      if (session.isCurrent(openRequest) && session.contextCandidate === approvedCandidate) {
        showAlert(error.message || "The private context could not be approved.");
      }
    } finally {
      setBusy(elements.contextApproveButton, false, "");
    }
  }

  async function revokePrivateContext() {
    if (!session.investigation) return;
    if (!window.confirm("Revoke this investigation's private molecular-profile access for the current session?")) return;
    setBusy(elements.contextRevokeButton, true, "Revoking…");
    try {
      await postJson(session.path("/revoke-context"), {});
      discardContextCandidate();
      showAlert("Private context access revoked. Stored evidence remains in the investigation ledger.", "success");
      await reloadCurrentInvestigation();
    } catch (error) {
      showAlert(error.message || "Private context access could not be revoked.");
    } finally {
      setBusy(elements.contextRevokeButton, false, "");
    }
  }

  async function previewHarness(
    operation,
    instruction = "",
    reason = "",
    artifactKind = "",
    openRequest = session.openRequest()
  ) {
    if (!session.investigation || !session.isCurrent(openRequest)) return false;
    const previewRequest = session.beginOutboundPreview(openRequest);
    if (!previewRequest) return false;
    hideOutboundPreview();
    const button = {
      start_task_run: elements.harnessPreviewButton,
      resume_task_run: elements.resumePreviewButton,
      replace_task_binding: elements.replaceHarnessButton,
      cancel_task_work: elements.cancelHarnessButton,
    }[operation] || elements.resumePreviewButton;
    setBusy(button, true, "Preparing preview…");
    setActivity("Preparing the exact outbound harness disclosure…");
    try {
      const candidate = await postJson(`${pathFor(openRequest.investigationId)}/harness-preview`, {
        operation,
        instruction: instruction || undefined,
        reason: reason || undefined,
        artifact_kind: artifactKind || (operation === "start_task_run" ? "plan" : "brief_draft"),
      });
      if (!session.acceptOutboundCandidate(previewRequest, candidate)) return false;
      renderOutboundPreview(candidate);
      setActivity("Outbound preview ready. Nothing has been sent to the harness yet.");
      return true;
    } catch (error) {
      if (session.isCurrentOutboundPreview(previewRequest)) {
        showAlert(error.message || "The harness disclosure preview could not be prepared.");
      }
      return false;
    } finally {
      setBusy(button, false, "");
    }
  }

  function handleHarnessMessagePreview(event) {
    event.preventDefault();
    if (!elements.harnessMessageForm.reportValidity()) return;
    void previewHarnessMessage(elements.harnessMessage.value.trim());
  }

  function handlePlanChangePreview(event) {
    event.preventDefault();
    if (!elements.planChangeForm.reportValidity()) return;
    void previewHarnessMessage(
      elements.planChangeMessage.value.trim(),
      "plan",
      elements.planChangeButton
    );
  }

  async function previewHarnessMessage(
    message,
    artifactKind = "brief_draft",
    sourceButton = elements.messagePreviewButton
  ) {
    if (!session.investigation) return;
    const previewRequest = session.beginOutboundPreview();
    hideOutboundPreview();
    setBusy(sourceButton, true, "Preparing preview…");
    setActivity("Preparing the exact message disclosure…");
    try {
      const candidate = await postJson(session.path("/harness-preview"), {
        operation: "send_task_message",
        instruction: message,
        artifact_kind: artifactKind,
      });
      if (!session.acceptOutboundCandidate(previewRequest, candidate)) return;
      renderOutboundPreview(candidate);
      setActivity("Message preview ready. It has not been sent.");
    } catch (error) {
      if (session.isCurrentOutboundPreview(previewRequest)) {
        showAlert(error.message || "The message disclosure preview could not be prepared.");
      }
    } finally {
      setBusy(sourceButton, false, "");
    }
  }

  async function acceptCurrentPlan() {
    const investigation = session.investigation;
    if (!investigation || !investigation.current_plan_version) return;
    const openRequest = session.openRequest();
    const planVersion = investigation.current_plan_version;
    if (String(planVersion.review_status || "") === "accepted") return;
    setBusy(elements.planAcceptButton, true, "Accepting…");
    setActivity("Recording acceptance of the exact plan shown above…");
    try {
      const result = await postJson(`${pathFor(openRequest.investigationId)}/plan-accept`, {
        approved: true,
        plan_version_id: planVersion.plan_version_id,
        plan_sha256: planVersion.plan_sha256,
      });
      if (!session.isCurrent(openRequest)) return;
      if (result.status !== "accepted") throw new Error("The plan could not be accepted.");
      showAlert(
        "Plan accepted. Review the separate harness execution disclosure before any capability runs.",
        "success"
      );
      if (!await reloadCurrentInvestigation(openRequest)) return;
      const next = result.next_harness_action;
      if (next && next.requires_outbound_disclosure_approval) {
        const previewed = await previewHarness(
          next.operation,
          next.instruction,
          next.reason,
          next.artifact_kind,
          openRequest
        );
        if (!previewed || !session.isCurrent(openRequest)) return;
        setActivity("Plan accepted. The exact harness execution disclosure is ready for your review; nothing has run yet.");
      } else {
        setActivity("Plan accepted. No capability request is ready to run yet.");
      }
    } catch (error) {
      if (session.isCurrent(openRequest)) {
        showAlert(error.message || "The plan could not be accepted.");
      }
    } finally {
      if (session.isCurrent(openRequest)) setBusy(elements.planAcceptButton, false, "");
    }
  }

  async function approveHarnessDisclosure() {
    const candidate = session.outboundCandidate;
    if (!candidate || !candidate.payload) return;
    const openRequest = session.openRequest();
    const operation = String(candidate.payload.operation || "");
    const endpoint = {
      start_task_run: "/start",
      resume_task_run: "/resume",
      send_task_message: "/messages",
      replace_task_binding: "/replace-harness",
      cancel_task_work: "/cancel",
    }[operation];
    if (!endpoint) {
      showAlert("This harness action is not supported by the Research Desk.");
      return;
    }
    setBusy(elements.harnessApproveButton, true, "Sending approved disclosure…");
    setActivity("Sending exactly the approved payload to the installed harness…");
    try {
      const payload = {
        approved: true,
        payload_sha256: candidate.payload_sha256,
        command_id: candidate.payload.command_context.command_id,
        expected_revision: candidate.payload.command_context.expected_revision,
        instruction: candidate.payload.instruction,
        artifact_kind: candidate.payload.artifact_kind,
        reason: candidate.payload.reason,
      };
      const result = await postJson(`${session.path()}${endpoint}`, payload);
      if (!session.isCurrent(openRequest)) return;
      if (!["accepted", "in_progress"].includes(result.status)) {
        throw new Error(result.artifact_error || result.message || "The harness response was not accepted.");
      }
      const previewChangedWhileSending = session.outboundCandidate !== candidate;
      discardOutboundCandidate();
      if (operation === "send_task_message") {
        elements.harnessMessageForm.reset();
        elements.planChangeForm.reset();
      }
      showAlert(
        previewChangedWhileSending
          ? "The approved harness action was accepted. A newer preview prepared while it was sending is now stale and was cleared."
          : result.status === "in_progress"
          ? "The installed harness is working in the background. Live progress is connected."
          : "The approved disclosure was accepted by the installed harness.",
        "success"
      );
      await reloadCurrentInvestigation();
      await reconnectEvents({announce: false});
    } catch (error) {
      if (session.isCurrent(openRequest) && session.outboundCandidate === candidate) {
        showAlert(error.message || "The installed harness did not accept the approved action.");
      }
    } finally {
      setBusy(elements.harnessApproveButton, false, "");
    }
  }

  async function handleCapabilityApproval(event) {
    const button = event.target.closest("button[data-capability-request-id]");
    if (!button || !elements.capabilityApprovalList.contains(button) || button.disabled) return;
    const requestId = String(button.dataset.capabilityRequestId || "");
    const planVersionId = String(button.dataset.planVersionId || "");
    const action = String(button.dataset.capabilityAction || "approve");
    if (action === "check") {
      const jobId = String(button.dataset.jobId || "");
      const resumeOperation = String(button.dataset.resumeOperation || "");
      if (!requestId || !planVersionId || !jobId || !resumeOperation) {
        showAlert("This recorded background job is incomplete and cannot be checked safely.");
        return;
      }
      setBusy(button, true, "Checking…");
      setActivity("Checking the exact recorded capability job without repeating its original request…");
      try {
        const result = await postJson(session.path("/capability-check"), {
          request_id: requestId,
          plan_version_id: planVersionId,
          job_id: jobId,
          resume_operation: resumeOperation,
        });
        if (result.status === "failed") {
          throw new Error(result.result && result.result.message || "The background capability job failed.");
        }
        showAlert(
          result.status === "in_progress"
            ? "The recorded capability job is still running."
            : "The recorded capability job finished and its result was committed.",
          "success"
        );
        await reloadCurrentInvestigation();
      } catch (error) {
        showAlert(error.message || "The recorded capability job could not be checked.");
      } finally {
        setBusy(button, false, "");
      }
      return;
    }
    const provider = String(button.dataset.recipientProvider || "");
    const payloadSha256 = String(button.dataset.payloadSha256 || "");
    if (!requestId || !provider || !payloadSha256) {
      showAlert("This evidence approval preview is incomplete. Ask the harness to replan.");
      return;
    }
    if (!window.confirm("Approve exactly the displayed public-evidence query and destination?")) return;
    setBusy(button, true, "Retrieving…");
    setActivity("Retrieving the exactly approved evidence through the GenomiLab gateway…");
    try {
      const result = await postJson(session.path("/capability-execute"), {
        request_id: requestId,
        approved: true,
        recipient_provider: provider,
        payload_sha256: payloadSha256,
      });
      if (!["completed", "in_progress"].includes(result.status)) {
        throw new Error(result.result && result.result.message || "The evidence request did not complete.");
      }
      showAlert(
        result.status === "in_progress"
          ? "Evidence retrieval is running as the exact recorded provider job."
          : "Evidence retrieved and committed to the source-separated ledger.",
        "success"
      );
      await reloadCurrentInvestigation();
      setActivity(
        result.status === "in_progress"
          ? "Provider work recorded. Use Check recorded job; the original query will not be submitted again."
          : "Evidence committed. Ask the harness to replan and assess it against the molecular profile."
      );
    } catch (error) {
      showAlert(error.message || "The approved evidence request could not be completed.");
    } finally {
      setBusy(button, false, "");
    }
  }

  async function cancelHarnessWork() {
    if (!session.investigation) return;
    if (!window.confirm("Ask the installed harness to cancel this investigation's current background work?")) return;
    await previewHarness(
      "cancel_task_work",
      "",
      "Cancelled by the local user from the GenomiLab Research Desk."
    );
  }

  async function reconnectEvents({
    announce = true,
    restartStream = announce,
    openRequest = session.openRequest(),
  } = {}) {
    if (!openRequest.investigationId || !session.isCurrent(openRequest)) return;
    const reconnectRequest = session.beginReconnect(openRequest);
    setBusy(elements.reconnectEventsButton, true, "Reconnecting…");
    if (announce) setActivity("Reconnecting the harness event stream…");
    try {
      const eventPayload = await apiRequest(session.path("/events"));
      if (!session.isCurrentReconnect(reconnectRequest)) return;
      renderEvents(eventPayload);
      session.eventSequence = latestEventSequence(eventPayload.events);
      if (restartStream) startEventStream();
      if (announce) setActivity("Harness events reconnected.");
    } catch (error) {
      if (!session.isCurrentReconnect(reconnectRequest)) return;
      elements.eventStatus.textContent = "Reconnect needed";
      if (announce) showAlert(error.message || "Harness events could not be reconnected.");
    } finally {
      if (session.isCurrentReconnect(reconnectRequest)) {
        setBusy(elements.reconnectEventsButton, false, "");
      }
    }
  }

  function startEventStream() {
    const stream = session.replaceEventStream();
    void followEventStream(stream);
  }

  async function followEventStream(stream) {
    while (session.ownsEventStream(stream)) {
      try {
        const payload = await waitForEvents(
          session.path("/event-stream"),
          session.eventSequence,
          stream.controller.signal
        );
        if (!session.ownsEventStream(stream)) return;
        if (Array.isArray(payload.events) && payload.events.length) {
          session.eventSequence = latestEventSequence(payload.events, session.eventSequence);
          const replay = await apiRequest(session.path("/events"));
          if (!session.ownsEventStream(stream)) return;
          renderEvents(replay);
          await reloadCurrentInvestigation();
        }
      } catch (error) {
        if (stream.controller.signal.aborted) return;
        elements.eventStatus.textContent = "Reconnect needed";
        return;
      }
    }
  }

  function latestEventSequence(events, fallback = 0) {
    return (Array.isArray(events) ? events : []).reduce(
      (latest, event) => Math.max(latest, Number(event && event.sequence) || 0),
      Number(fallback) || 0
    );
  }

  async function reloadCurrentInvestigation(openRequest = session.openRequest()) {
    if (!openRequest.investigationId || !session.isCurrent(openRequest)) return false;
    const investigationLoad = session.beginInvestigationLoad(openRequest);
    if (!investigationLoad) return false;
    const workspaceRequest = state.beginWorkspaceRequest();
    const [investigation, workspacePayload] = await Promise.all([
      apiRequest(pathFor(openRequest.investigationId)),
      apiRequest("/api/v1/workspace"),
    ]);
    if (!session.isCurrentInvestigationLoad(investigationLoad)) return false;
    if (!session.acceptInvestigationLoad(investigationLoad, investigation)) return false;
    discardContextCandidate();
    discardOutboundCandidate();
    if (
      workspacePayload
      && workspacePayload.status === "ready"
      && workspacePayload.workspace
      && state.acceptWorkspace(workspaceRequest, workspacePayload)
    ) {
      renderWorkspace(workspacePayload.workspace, session.investigationId);
      synchronizeProfile();
    }
    renderCurrentInvestigation();
    return true;
  }

  function renderCurrentInvestigation() {
    renderInvestigation(session.investigation, state.harnessManifest(), profileObservations());
  }

  function profileObservations() {
    return state.profileRecords("observations");
  }

  function selectedContextObservationRevisionIds() {
    return [...elements.contextObservationList.querySelectorAll(
      "input[name='context_observation_revision_id']:checked"
    )].map((input) => String(input.value || "")).filter(Boolean);
  }

  function pinnedProfileSnapshot() {
    const investigation = session.investigation;
    if (!investigation || !investigation.patient_molecular_snapshot_id) return null;
    const currentId = String(investigation.patient_molecular_snapshot_id);
    const history = Array.isArray(investigation.profile_snapshot_history)
      ? investigation.profile_snapshot_history
      : [];
    return history.find(
      (item) => String(item && item.patient_molecular_snapshot_id || "") === currentId
    ) || null;
  }

  return Object.freeze({bind, close, open});
}

function pathFor(investigationId) {
  return `/api/v1/investigations/${encodeURIComponent(investigationId)}`;
}
