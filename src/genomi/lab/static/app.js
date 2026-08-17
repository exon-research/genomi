"use strict";

import { apiRequest, initializePortalSession } from "./api.js";
import { createConnectionsController } from "./connections-controller.js";
import { createInvestigationController } from "./investigation-controller.js";
import { PortalState, InvestigationSession } from "./portal-state.js";
import { createProfileController } from "./profile-controller.js";
import {
  closeInvestigation,
  collectElements,
  elements,
  hideAlert,
  renderBootstrap,
  setActivity,
  showAlert,
} from "./render.js";

const state = new PortalState();
const session = new InvestigationSession();
const sessionStartup = initializePortalSession().then(
  () => ({error: null}),
  (error) => ({error})
);
let profileController;
let investigationController;
let connectionsController;

document.addEventListener("DOMContentLoaded", () => void initialize());

async function initialize() {
  collectElements();
  elements.alertDismiss.addEventListener("click", hideAlert);
  profileController = createProfileController({state, refresh});
  connectionsController = createConnectionsController();
  investigationController = createInvestigationController({
    state,
    session,
    synchronizeProfile: () => profileController.synchronizeFormState(),
  });
  profileController.bind();
  connectionsController.bind();
  investigationController.bind();
  const {error} = await sessionStartup;
  if (error) {
    showAlert(error.message || "Open GenomiLab from its launch link.");
    setActivity("Workspace unavailable.");
    return;
  }
  await refresh();
  await connectionsController.load();
}

async function refresh() {
  const workspaceRequest = state.beginWorkspaceRequest();
  setActivity("Opening your local Research Desk…");
  try {
    const bootstrap = await apiRequest("/api/v1/bootstrap");
    if (!state.acceptBootstrap(workspaceRequest, bootstrap)) return;
    const investigations = bootstrap.workspace && Array.isArray(bootstrap.workspace.investigations)
      ? bootstrap.workspace.investigations
      : [];
    const selectedStillBelongsToWorkspace = investigations.some(
      (item) => String(item.investigation_id || "") === session.investigationId
    );
    if (session.investigationId && !selectedStillBelongsToWorkspace) {
      session.close();
      closeInvestigation();
    }
    renderBootstrap(bootstrap, session.investigationId);
    if (bootstrap.status === "ready") profileController.synchronizeFormState();
    const authorizationHandoff = state.authorizationHandoff();
    if (bootstrap.status === "ready" && authorizationHandoff) {
      await investigationController.open(
        authorizationHandoff.investigation_id,
        {
          focus: true,
          authorizationCandidate: authorizationHandoff.authorization_candidate,
        }
      );
    } else if (bootstrap.status === "ready" && session.investigationId) {
      await investigationController.open(session.investigationId, {focus: false});
    }
    setActivity(bootstrap.status === "ready" ? "Research Desk ready." : "Waiting for Genomi user setup.");
  } catch (error) {
    if (!state.isCurrentWorkspaceRequest(workspaceRequest)) return;
    showAlert(error.message || "GenomiLab could not open the local workspace.");
    setActivity("Workspace unavailable.");
  }
}
