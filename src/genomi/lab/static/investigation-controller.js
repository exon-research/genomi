"use strict";

import { apiRequest, postJson, waitForEvents } from "./api.js";
import {
  closeInvestigation,
  elements,
  hideContextCandidate,
  renderContextCandidate,
  renderEvents,
  renderInvestigation,
  renderWorkspace,
  setActivity,
  setBusy,
  showAlert,
} from "./render.js";

export function createInvestigationController({state, session, synchronizeProfile}) {
  function bind() {
    elements.investigationList.addEventListener("click", handleInvestigationSelection);
    elements.detailClose.addEventListener("click", close);
    elements.contextPreviewButton.addEventListener("click", () => void previewPrivateContext());
    elements.contextRefreshPreviewButton.addEventListener(
      "click", () => void previewPrivateContext({refresh: true})
    );
    elements.contextApproveButton.addEventListener("click", () => void authorizeContext());
    elements.contextObservationList.addEventListener("change", invalidateContextCandidate);
    elements.contextRevokeButton.addEventListener("click", () => void revokePrivateContext());
    elements.reconnectEventsButton.addEventListener("click", () => void reconnectEvents());
    elements.capabilityApprovalList.addEventListener("click", handleCapabilityApproval);
    elements.returnToAgentButton.addEventListener("click", returnToUnderlyingAgent);
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
    closeInvestigation();
    if (state.workspace()) renderWorkspace(state.workspace());
    elements.investigationList.scrollIntoView({block: "start"});
    setActivity("Investigation closed. Research Desk ready.");
  }

  async function open(
    investigationId,
    {focus = true, authorizationCandidate = null} = {}
  ) {
    const openRequest = session.beginOpen(investigationId);
    const investigationLoad = session.beginInvestigationLoad(openRequest);
    hideContextCandidate();
    setActivity("Opening the investigation and reconnecting its activity…");
    try {
      const investigation = await apiRequest(pathFor(investigationId));
      if (!session.acceptInvestigationLoad(investigationLoad, investigation)) return;
      renderCurrentInvestigation();
      if (authorizationCandidate) {
        displayAuthorizationHandoff(investigationId, authorizationCandidate);
      }
      if (state.workspace()) renderWorkspace(state.workspace(), investigationId);
      await reconnectEvents({announce: false, openRequest});
      if (!session.isCurrent(openRequest)) return;
      startEventStream();
      if (focus) {
        elements.investigationDetail.scrollIntoView({block: "start"});
        elements.investigationDetail.focus({preventScroll: true});
      }
      setActivity(
        authorizationCandidate
          ? "Exact research access is ready for your review."
          : "Investigation open."
      );
    } catch (error) {
      if (!session.isCurrent(openRequest)) return;
      showAlert(error.message || "The investigation could not be opened.");
      setActivity("Investigation unavailable.");
    }
  }

  function displayAuthorizationHandoff(investigationId, candidate) {
    if (
      !candidate
      || candidate.investigation_id !== investigationId
      || !candidate.authorization_candidate_receipt
      || !candidate.authorization_scope
    ) {
      throw new Error("The prepared research authorization handoff is incomplete.");
    }
    const previewRequest = session.beginContextPreview();
    if (!session.acceptContextCandidate(previewRequest, candidate)) {
      throw new Error("The prepared research authorization handoff expired.");
    }
    const selectedIds = new Set(
      Array.isArray(candidate.observation_revision_ids)
        ? candidate.observation_revision_ids.map(String)
        : []
    );
    elements.contextObservationList.querySelectorAll(
      "input[name='context_observation_revision_id']"
    ).forEach((input) => {
      input.checked = selectedIds.has(String(input.value || ""));
    });
    renderContextCandidate(session.contextCandidate, profileObservations());
  }

  function returnToUnderlyingAgent() {
    const manifest = state.underlyingAgentManifest();
    const destination = String(
      manifest.processing_destination || "the underlying agent"
    );
    try {
      if (globalThis.opener && !globalThis.opener.closed) {
        globalThis.opener.focus();
      }
      globalThis.close();
    } catch (_error) {
      // Browsers may prevent a page they did not create from closing itself.
    }
    showAlert(
      `Return to ${destination} to continue, redirect, pause, or cancel the task. You can close this portal tab if it remains open.`,
      "success"
    );
    setActivity("Return to the underlying agent to continue the investigation.");
  }

  function invalidateContextCandidate() {
    session.invalidateContextSelection();
    hideContextCandidate();
    setActivity("Profile selection changed. Review the updated research access before authorizing it.");
  }

  function discardContextCandidate() {
    session.discardContextCandidate();
    hideContextCandidate();
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
    setActivity("Preparing the exact research authorization…");
    try {
      const candidatePayload = {
        purpose: pinned
          ? pinned.purpose
          : `Investigate: ${String(investigation.question || "disease question")}`,
        use_current_agi: useCurrentAgi,
      };
      if (!pinned) candidatePayload.observation_revision_ids = selectedObservationRevisionIds;
      const candidate = await postJson(
        session.path("/authorization-candidate"),
        candidatePayload
      );
      if (!candidate || !candidate.authorization_candidate_receipt || !candidate.authorization_scope) {
        throw new Error("The research authorization preview is incomplete.");
      }
      const preparedCandidate = useCurrentAgi && investigation.patient_molecular_snapshot_id
        ? {...candidate, refresh: true}
        : candidate;
      if (!session.acceptContextCandidate(previewRequest, preparedCandidate)) {
        if (session.isCurrent(previewRequest.open)) {
          setActivity("The profile selection changed while research access was prepared. Review it again.");
        }
        return;
      }
      renderContextCandidate(session.contextCandidate, profileObservations());
      setActivity(
        useCurrentAgi
          ? "Updated research access is ready for review. Nothing has changed yet."
          : "Research access is ready for review. Nothing has been shared with the agent yet."
      );
    } catch (error) {
      if (!session.isCurrentContextPreview(previewRequest)) return;
      showAlert(error.message || "Research access could not be prepared.");
    } finally {
      setBusy(sourceButton, false, "");
    }
  }

  async function authorizeContext() {
    if (!session.contextCandidate) return;
    const authorizationCandidate = session.contextCandidate;
    if (!authorizationCandidate.authorization_candidate_receipt) {
      showAlert("Review research access again before authorizing the context.");
      return;
    }
    const openRequest = session.openRequest();
    setBusy(elements.contextApproveButton, true, "Authorizing…");
    setActivity("Authorizing the exact profile and genome scope for the current agent session…");
    try {
      const authorization = {...authorizationCandidate};
      delete authorization.status;
      delete authorization.requires_explicit_approval;
      delete authorization.user_id;
      delete authorization.investigation_id;
      authorization.approved = true;
      await postJson(session.path("/authorize-context"), authorization);
      if (!session.isCurrent(openRequest)) return;
      const selectionChangedWhileAuthorizing = session.contextCandidate !== authorizationCandidate;
      discardContextCandidate();
      showAlert(
        selectionChangedWhileAuthorizing
          ? "The reviewed scope was authorized. Newer selection changes were not included; review them separately if you want to expand access."
          : "Research context authorized. Continue the investigation in your Claude or Codex conversation; this portal will monitor committed updates.",
        "success"
      );
      await reloadCurrentInvestigation(openRequest);
      await reconnectEvents({announce: false, openRequest});
      if (session.isCurrent(openRequest)) {
        setActivity("Research context is available to the current agent session. Monitoring committed investigation activity.");
      }
    } catch (error) {
      if (session.isCurrent(openRequest) && session.contextCandidate === authorizationCandidate) {
        showAlert(error.message || "The research context could not be authorized.");
      }
    } finally {
      setBusy(elements.contextApproveButton, false, "");
    }
  }

  async function revokePrivateContext() {
    if (!session.investigation) return;
    if (!window.confirm("Revoke future GenomiLab access to this investigation's private profile and genome context? This does not stop or cancel the Claude or Codex task.")) return;
    setBusy(elements.contextRevokeButton, true, "Revoking…");
    try {
      await postJson(session.path("/revoke-context"), {});
      discardContextCandidate();
      showAlert("Future GenomiLab private-context access revoked. Stored evidence remains in the ledger; manage or cancel the agent task in Claude or Codex.", "success");
      await reloadCurrentInvestigation();
    } catch (error) {
      showAlert(error.message || "Research access could not be revoked.");
    } finally {
      setBusy(elements.contextRevokeButton, false, "");
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
    const approvalSha256 = String(button.dataset.approvalSha256 || "");
    if (!requestId || !provider || !payloadSha256 || !approvalSha256) {
      showAlert("This evidence approval preview is incomplete. Ask the agent to prepare it again.");
      return;
    }
    setBusy(button, true, "Retrieving…");
    setActivity("Retrieving the exactly approved evidence through the GenomiLab gateway…");
    try {
      const result = await postJson(session.path("/capability-execute"), {
        request_id: requestId,
        approved: true,
        recipient_provider: provider,
        payload_sha256: payloadSha256,
        approval_sha256: approvalSha256,
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
          : "Evidence committed. The research team will assess it within the current authorization."
      );
    } catch (error) {
      showAlert(error.message || "The approved evidence request could not be completed.");
    } finally {
      setBusy(button, false, "");
    }
  }

  async function reconnectEvents({
    announce = true,
    restartStream = announce,
    openRequest = session.openRequest(),
  } = {}) {
    if (!openRequest.investigationId || !session.isCurrent(openRequest)) return;
    const reconnectRequest = session.beginReconnect(openRequest);
    setBusy(elements.reconnectEventsButton, true, "Refreshing…");
    if (announce) setActivity("Refreshing committed investigation activity…");
    try {
      const eventPayload = await apiRequest(session.path("/events"));
      if (!session.isCurrentReconnect(reconnectRequest)) return;
      renderEvents(eventPayload);
      session.eventSequence = latestEventSequence(eventPayload.events);
      if (restartStream) startEventStream();
      if (announce) setActivity("Committed investigation activity refreshed.");
    } catch (error) {
      if (!session.isCurrentReconnect(reconnectRequest)) return;
      elements.eventStatus.textContent = "Refresh needed";
      if (announce) showAlert(error.message || "Investigation activity could not be refreshed.");
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
        } else {
          await waitForNextActivityPoll(stream.controller.signal);
        }
      } catch (error) {
        if (stream.controller.signal.aborted) return;
        elements.eventStatus.textContent = "Refresh needed";
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
    renderInvestigation(session.investigation, state.underlyingAgentManifest(), state.profile());
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

function waitForNextActivityPoll(signal, delayMilliseconds = 1000) {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const onAbort = () => {
      clearTimeout(timeout);
      resolve();
    };
    const timeout = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, delayMilliseconds);
    signal.addEventListener("abort", onAbort, {once: true});
  });
}
