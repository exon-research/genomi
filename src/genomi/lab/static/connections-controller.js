"use strict";

import { apiRequest, postJson } from "./api.js";
import { setFormBusy } from "./form-controls.js";
import {
  integrationCredentialPayload,
  integrationProviderIds,
  renderConnections,
} from "./render-connections.js";
import { elements, setActivity, setBusy, showAlert } from "./render.js";

const INTEGRATIONS_PATH = "/api/v1/integrations";
const PROVIDERS = new Set(integrationProviderIds());
const ACTIONS = new Set(["verify", "disconnect"]);

export function createConnectionsController() {
  function bind() {
    elements.integrationList.addEventListener("submit", handleConnect);
    elements.integrationList.addEventListener("click", handleAction);
  }

  async function load({announceFailure = false} = {}) {
    try {
      renderConnections(await apiRequest(INTEGRATIONS_PATH));
    } catch (error) {
      renderConnections({status: "unavailable", integrations: []});
      if (announceFailure) {
        showAlert(error.message || "Optional research-tool connections could not be checked.");
      }
    }
  }

  async function handleConnect(event) {
    const form = event.target.closest("form[data-integration-connect]");
    if (!form || !elements.integrationList.contains(form)) return;
    event.preventDefault();
    const provider = String(form.dataset.integrationConnect || "");
    if (!PROVIDERS.has(provider) || !form.reportValidity()) return;
    const submit = form.querySelector("button[type='submit']");
    if (!submit) return;
    const payload = integrationCredentialPayload(provider, form);
    if (!payload) return;
    let connected = false;
    setFormBusy(form, submit, true, "Saving securely…");
    setActivity("Saving this research-tool credential securely…");
    try {
      const response = await postJson(`${INTEGRATIONS_PATH}/${provider}/connect`, payload);
      connected = true;
      announceConnectionResult(response && response.integration);
    } catch (error) {
      showAlert(error.message || "The credential could not be saved securely.");
      setActivity("Research-tool connection needs attention.");
    } finally {
      form.reset();
      setFormBusy(form, submit, false);
    }
    await load({announceFailure: connected});
  }

  function handleAction(event) {
    const button = event.target.closest("button[data-integration-action]");
    if (!button || !elements.integrationList.contains(button) || button.disabled) return;
    const provider = String(button.dataset.integrationProvider || "");
    const action = String(button.dataset.integrationAction || "");
    if (!PROVIDERS.has(provider) || !ACTIONS.has(action)) return;
    if (action === "disconnect" && !window.confirm(
      "Disconnect this research tool and remove its saved credentials from secure local storage?"
    )) return;
    void performAction(button, provider, action);
  }

  async function performAction(button, provider, action) {
    const disconnecting = action === "disconnect";
    let completed = false;
    setBusy(button, true, disconnecting ? "Disconnecting…" : "Checking…");
    setActivity(disconnecting ? "Removing saved research-tool credentials…" : "Checking research-tool connection…");
    try {
      const response = await postJson(
        `${INTEGRATIONS_PATH}/${provider}/${action}`,
        disconnecting ? {confirmed: true} : {}
      );
      if (disconnecting) {
        const integration = response && response.integration;
        const disconnected = integration
          && integration.connection_state === "not_configured"
          && integration.credential_state === "missing";
        if (disconnected) {
          showAlert("Research tool disconnected.", "success");
          setActivity("Research tool disconnected.");
        } else {
          showAlert("The saved credential is still present. This research tool remains configured.");
          setActivity("Research-tool connection remains configured.");
        }
      } else {
        announceConnectionResult(response && response.integration);
      }
      completed = true;
    } catch (error) {
      showAlert(error.message || (disconnecting
        ? "The research tool could not be disconnected."
        : "The connection could not be checked."));
      setActivity("Research-tool connection needs attention.");
    } finally {
      setBusy(button, false, "");
    }
    await load({announceFailure: completed});
  }

  return Object.freeze({bind, load});
}

function announceConnectionResult(integration) {
  const state = String(integration && integration.connection_state || "");
  if (state === "ready") {
    const provider = String(integration && integration.provider || "");
    if (provider === "paperclip") {
      showAlert(
        "Paperclip API key checked. The check sent only TP53 to PMC with a limit of 1, never the patient's profile. It enables no general public search; patient-investigation authorization is shown separately below.",
        "success"
      );
      setActivity("Paperclip API key checked.");
      return;
    }
    const operations = Array.isArray(integration && integration.investigation_operations)
      ? integration.investigation_operations
      : [];
    showAlert(
      operations.length
        ? "Connection checked. Enabled operations and use limits are shown below."
        : "Credential and connection checked. No GenomiLab research operation was enabled.",
      "success"
    );
    setActivity("Research-tool connection checked.");
    return;
  }
  if (state === "verification_unavailable") {
    const provider = String(integration && integration.provider || "");
    const name = provider === "biohub-esm" ? "Biohub ESM" : "Proto";
    showAlert(`Credential saved, but ${name} verification and use are not enabled yet.`);
    setActivity(`${name} remains unavailable in this workspace.`);
    return;
  }
  if (state === "configured_unverified") {
    const provider = String(integration && integration.provider || "");
    const message = provider === "biohub-esm"
      ? "Credential saved securely. Run the disclosed fixed synthetic encode check when ready; it may use credits and never sends a patient sequence."
      : provider === "paperclip"
        ? "Credential saved securely. When ready, run the fixed public API check: TP53 in PMC, limit 1. It may use credits and never sends the patient's profile."
        : "Credential saved securely. Check the Modal account and exact environment when ready; no Proto tool will run.";
    showAlert(message, "success");
    setActivity("Research-tool credential saved; use is not enabled.");
    return;
  }
  const message = state === "authentication_failed"
    ? "Credential saved, but the provider did not accept it."
    : state === "environment_not_found"
      ? "Modal accepted the credential, but the named environment was not found."
      : state === "quota_exceeded"
        ? "Credential accepted, but the provider reports insufficient credits or quota."
        : state === "rate_limited"
          ? "Credential accepted, but the provider rate limit prevented this check."
          : state === "timeout"
            ? "The provider did not finish the connection check in time."
            : state === "source_unavailable"
              ? "Credential saved, but the provider service or its response contract is unavailable."
              : state === "runtime_unavailable"
                ? "Credential saved, but this provider runtime is not installed."
                : "Credential saved, but the provider connection could not be verified.";
  showAlert(message);
  setActivity("Research-tool connection needs attention.");
}
