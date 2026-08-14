"use strict";

import { array, formatTime, isObject, node, text } from "./render-dom.js";

export const INTEGRATION_DEFINITIONS = Object.freeze([
  Object.freeze({
    provider: "paperclip",
    name: "GXL Paperclip",
    description: "Use only the typed public-evidence routes authorized for this installation.",
    boundary: "Remote public-evidence service. Patient-influenced use additionally requires an independent patient-data agreement, plus a preview and approval for every query.",
    fields: Object.freeze([
      Object.freeze({name: "api_key", label: "Paperclip API key", secret: true, maximum: 4096}),
    ]),
  }),
  Object.freeze({
    provider: "biohub-esm",
    name: "Biohub ESM",
    description: "Check Biohub's ESM encode endpoint with one fixed synthetic amino-acid alphabet for a future protein-analysis workflow.",
    boundary: "The disclosed check is remote and may use API credits. It sends only GenomiLab's fixed 20-residue synthetic alphabet as JSON—never a patient-derived sequence—and enables no patient-investigation operation.",
    fields: Object.freeze([
      Object.freeze({name: "api_token", label: "Biohub API token", secret: true, maximum: 4096}),
    ]),
    resources: Object.freeze([
      Object.freeze({label: "Create or manage API key", url: "/official/biohub-api-keys"}),
      Object.freeze({label: "Terms", url: "/official/biohub-terms"}),
      Object.freeze({label: "Privacy", url: "/official/biohub-privacy"}),
      Object.freeze({label: "Model limitations", url: "/official/biohub-limitations"}),
    ]),
  }),
  Object.freeze({
    provider: "proto",
    name: "Proto prerequisite (Modal)",
    description: "Check the Modal account and exact environment that would host a future reviewed Proto expert workflow.",
    boundary: "The check authenticates to Modal and lists environments. It does not deploy, start, or run a Proto tool, and it enables no patient-investigation operation.",
    fields: Object.freeze([
      Object.freeze({name: "modal_token_id", label: "Modal token ID", secret: true, maximum: 500}),
      Object.freeze({name: "modal_token_secret", label: "Modal token secret", secret: true, maximum: 4096}),
      Object.freeze({name: "modal_environment", label: "Modal environment", secret: false, maximum: 200, placeholder: "Example: genomilab-research"}),
    ]),
  }),
]);

const CONNECTION_LABELS = Object.freeze({
  not_configured: "Not connected",
  configured_unverified: "Saved, not checked",
  ready: "Connected",
  authentication_failed: "Key not accepted",
  unreachable: "Could not check",
  runtime_unavailable: "Provider runtime not installed",
  source_unavailable: "Provider service or response unavailable",
  verification_unavailable: "Verification not available",
  quota_exceeded: "Credits or quota unavailable",
  rate_limited: "Provider rate limit reached",
  timeout: "Connection check timed out",
  environment_not_found: "Modal environment not found",
  credential_corrupt: "Saved credential needs replacement",
  credential_store_unavailable: "Secure storage unavailable",
  reconciliation_required: "Saved connection needs confirmation",
});

const POLICY_LABELS = Object.freeze({
  allowed: "Available when relevant",
  authorized: "Available when relevant",
  hard_disabled: "Use is not enabled",
  authorized_unavailable: "Connected service unavailable",
  blocked_missing_deployment_authorization: "Product authorization required",
  blocked_deployment_scope: "Product authorization does not cover an available route",
  blocked_missing_patient_data_contract: "Patient-data agreement required",
  blocked_patient_data_contract_scope: "Patient-data agreement does not cover an available route",
  blocked_missing_exact_disclosure_approval: "Per-request approval required",
  disabled: "Use is not enabled",
  unavailable: "Not available in this workspace",
  requires_expert_research_mode: "Expert research mode required",
  refused_patient_workflow_sequence_design: "Not available in patient investigations",
  refused_patient_sequence_remote: "Patient-derived sequences stay local",
  connection_only_no_product_operation: "Connection only; no enabled operation",
  requires_pinned_safe_esm_runtime: "Reviewed ESM runtime required",
  requires_proto_runtime_and_expert_mode: "Future expert workflow only",
  task_not_validated: "Validation required before use",
});

const SCOPE_LABELS = Object.freeze({
  public_evidence: "Public evidence",
  fixed_synthetic_connection_probe: "Fixed synthetic connection check only",
  modal_prerequisite_only: "Modal prerequisite check only",
});

const SOURCE_FAMILY_LABELS = Object.freeze({
  literature: "literature",
  regulatory: "regulatory",
  trial_registry: "trial registry",
});

export function renderConnections(payload) {
  const records = connectionRecords(payload);
  const byProvider = new Map(records.map((record) => [text(record.provider), record]));
  const savedCount = INTEGRATION_DEFINITIONS.filter(
    (definition) => text((byProvider.get(definition.provider) || {}).credential_state) === "stored"
  ).length;
  const enabledCount = INTEGRATION_DEFINITIONS.filter(
    (definition) => array((byProvider.get(definition.provider) || {}).available_operations).length > 0
  ).length;
  const unavailable = text(payload && payload.status) === "unavailable";

  const summary = document.getElementById("integrations-summary");
  const list = document.getElementById("integration-list");
  if (!summary || !list) return;
  summary.textContent = unavailable
    ? "Connections unavailable"
    : `${savedCount} of ${INTEGRATION_DEFINITIONS.length} credentials saved · ${enabledCount} investigation connection enabled`;
  if (unavailable) summary.dataset.available = "false";
  else delete summary.dataset.available;
  list.setAttribute("aria-busy", "false");
  if (unavailable) {
    list.replaceChildren(node(
      "p",
      "Research-tool connection state could not be loaded. No credentials can be changed until it is available.",
      "empty-row"
    ));
    return;
  }
  list.replaceChildren(
    ...INTEGRATION_DEFINITIONS.map((definition) => integrationCard(
      definition,
      byProvider.get(definition.provider) || {}
    ))
  );
}

function integrationCard(definition, record) {
  const state = connectionState(record);
  const credentialState = text(record.credential_state);
  const credentialPresent = credentialState === "stored" || credentialState === "corrupt";
  const policyState = text(record.policy_state) || "unavailable";
  const operations = array(record.available_operations)
    .map((operation) => text(operation))
    .filter(Boolean);
  const routes = availableRoutes(record.available_routes);
  const purposes = array(record.available_purposes)
    .map((purpose) => text(purpose))
    .filter(Boolean);
  const card = node("article", "", "integration-card");
  card.dataset.integrationProvider = definition.provider;

  const heading = document.createElement("header");
  const title = document.createElement("div");
  title.append(node("h3", definition.name), node("p", definition.description));
  const states = node("div", "", "integration-state-stack");
  const connection = node(
    "span",
    state === "ready" && operations.length === 0
      ? "Credential checked"
      : CONNECTION_LABELS[state] || "Connection needs attention",
    "integration-state"
  );
  connection.dataset.state = state;
  const policy = node(
    "span",
    POLICY_LABELS[policyState] || policyFallback(policyState),
    "integration-policy-state"
  );
  policy.dataset.state = policyState;
  states.append(connection, policy);
  heading.append(title, states);

  const facts = node("p", "", "integration-facts");
  const location = text(record.execution_location) === "local" ? "Runs locally" : "Runs remotely";
  const scope = SCOPE_LABELS[text(record.use_scope)] || "Use is limited by the policy shown above";
  const verified = record.last_verified_at
    ? `Last checked ${formatTime(text(record.last_verified_at))}`
    : "Not checked in this session";
  facts.textContent = `${location} · ${scope} · ${verified}`;

  const boundary = node("p", definition.boundary, "integration-card-boundary");
  const operationSummary = node("p", operationSummaryText({
    provider: definition.provider,
    state,
    operations,
    routes,
    purposes,
  }), "integration-operation-summary");
  card.append(heading, facts, boundary, operationSummary);
  if (array(definition.resources).length) {
    const resources = node("p", "", "integration-card-boundary");
    resources.append("Official resources: ");
    array(definition.resources).forEach((resource, index) => {
      if (index) resources.append(" · ");
      const link = document.createElement("a");
      link.href = text(resource.url);
      link.textContent = text(resource.label);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      resources.append(link);
    });
    card.append(resources);
  }
  if (state === "reconciliation_required") {
    card.append(node(
      "p",
      record.verification_available === true && credentialPresent
        ? record.verification_may_consume_credits === true
          ? "A previous setup change was interrupted, so GenomiLab will not use this connection. The interrupted check may already have used credits, and another check may use more. Run it only when ready, replace the saved credentials, or disconnect the tool."
          : "A previous setup change was interrupted, so GenomiLab will not use this connection. Run the connection check, replace the saved credentials, or disconnect the tool to confirm its current state."
        : "A previous setup change was interrupted, so GenomiLab will not use this connection. Replace the saved credentials or confirm that the tool is disconnected.",
      "integration-card-boundary"
    ));
  }
  const canEnterCredentials = state !== "credential_store_unavailable"
    && (definition.provider !== "paperclip"
      || record.verification_available === true
      || credentialPresent);
  if (canEnterCredentials) {
    const details = document.createElement("details");
    details.className = "integration-connect-details";
    details.open = !credentialPresent || credentialState === "corrupt";
    details.append(node(
      "summary",
      credentialPresent ? "Replace saved credentials" : "Connect this tool"
    ));
    details.append(connectionForm(definition));
    card.append(details);
  } else if (definition.provider === "paperclip") {
    card.append(node(
      "p",
      "The installation owner must first configure documented Paperclip product authorization. An API key cannot establish that permission.",
      "integration-card-boundary"
    ));
  }
  if (state === "ready" || credentialPresent || state === "reconciliation_required") {
    const actions = node("div", "", "integration-actions");
    if (credentialState === "stored" && record.verification_available !== false) {
      actions.append(actionButton(
        definition.provider,
        "verify",
        verificationActionLabel(definition.provider),
        "secondary-button"
      ));
    }
    actions.append(
      actionButton(
        definition.provider,
        "disconnect",
        state === "reconciliation_required" && !credentialPresent
          ? "Confirm disconnected"
          : "Disconnect",
        "danger-button"
      )
    );
    card.append(actions);
  }
  return card;
}

function availableRoutes(value) {
  return array(value)
    .filter(isObject)
    .map((route) => ({
      sourceFamily: text(route.source_family),
      operations: array(route.operations)
        .map((operation) => text(operation))
        .filter(Boolean),
    }))
    .filter((route) => route.sourceFamily && route.operations.length);
}

function operationSummaryText({provider, state, operations, routes, purposes}) {
  if (provider === "paperclip" && routes.length) {
    const routeSummary = routes
      .map((route) => `${SOURCE_FAMILY_LABELS[route.sourceFamily] || route.sourceFamily}: ${route.operations.join(", ")}`)
      .join(" · ");
    const purposeSummary = purposes.length
      ? ` Approved purposes: ${purposes.join("; ")}.`
      : "";
    return `Enabled patient-investigation routes: ${routeSummary}.${purposeSummary} Every query still requires an exact preview and approval.`;
  }
  if (operations.length) {
    return `Enabled patient-investigation operations: ${operations.join(", ")}`;
  }
  return state === "ready"
    ? "Credential and connection checked. No GenomiLab research operation is enabled."
    : "No GenomiLab research operation is enabled by this connection.";
}

function connectionForm(definition) {
  const form = document.createElement("form");
  form.className = "integration-connect-form";
  form.dataset.integrationConnect = definition.provider;
  form.autocomplete = "off";
  definition.fields.forEach((field) => {
    const id = `integration-${definition.provider}-${field.name.replaceAll("_", "-")}`;
    const label = node("label", field.label);
    label.htmlFor = id;
    const input = document.createElement("input");
    input.id = id;
    input.name = field.name;
    input.type = field.secret ? "password" : "text";
    input.required = true;
    input.maxLength = field.maximum;
    input.autocomplete = "off";
    input.autocapitalize = "none";
    input.spellcheck = false;
    if (field.placeholder) input.placeholder = field.placeholder;
    form.append(label, input);
  });
  const help = node(
    "p",
    "Credentials are sent only to this local GenomiLab process and saved in your operating system's secure credential store.",
    "field-help"
  );
  const submit = node("button", "Save securely", "primary-button");
  submit.type = "submit";
  form.append(help, submit);
  return form;
}

function verificationActionLabel(provider) {
  if (provider === "paperclip") return "Run public API check — may use credits";
  if (provider === "biohub-esm") return "Run fixed synthetic encode check — may use credits";
  return "Check Modal account and environment";
}

function actionButton(provider, action, label, className) {
  const button = node("button", label, className);
  button.type = "button";
  button.dataset.integrationProvider = provider;
  button.dataset.integrationAction = action;
  return button;
}

function connectionRecords(payload) {
  const integrations = payload && payload.integrations;
  if (Array.isArray(integrations)) return integrations.filter(isObject);
  if (!isObject(integrations)) return [];
  return Object.entries(integrations)
    .filter(([, value]) => isObject(value))
    .map(([provider, value]) => ({...value, provider}));
}

function connectionState(record) {
  const state = text(record.connection_state) || text(record.status);
  return state || "not_configured";
}

function policyFallback(value) {
  if (value.startsWith("blocked_missing_")) return "Additional approval required";
  if (value.startsWith("requires_")) return "Additional setup required";
  if (value.startsWith("refused_")) return "Not available for this use";
  return "Use permission not established";
}

export function integrationDefinition(provider) {
  return INTEGRATION_DEFINITIONS.find((definition) => definition.provider === provider) || null;
}

export function integrationCredentialPayload(provider, form) {
  const definition = integrationDefinition(provider);
  if (!definition) return null;
  const payload = {};
  definition.fields.forEach((field) => {
    const control = form.elements.namedItem(field.name);
    payload[field.name] = String(control && control.value || "").trim();
  });
  return payload;
}

export function integrationProviderIds() {
  return array(INTEGRATION_DEFINITIONS).map((definition) => definition.provider);
}
