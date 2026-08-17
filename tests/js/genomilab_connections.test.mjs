import assert from "node:assert/strict";
import test from "node:test";

import { integrationPresentation } from "../../src/genomi/lab/static/render-connections.js";

test("Paperclip API-key onboarding stays available without patient-use authorization", () => {
  const missing = integrationPresentation("paperclip", {
    connection_state: "not_configured",
    credential_state: "missing",
    policy_state: "blocked_missing_deployment_authorization",
    verification_available: true,
    investigation_operations: [],
    investigation_routes: [],
    investigation_purposes: [],
  });

  assert.equal(missing.canEnterCredentials, true);
  assert.equal(missing.canVerify, false);
  assert.equal(
    missing.policyLabel,
    "Patient investigations: GXL investigation authorization required"
  );

  const saved = integrationPresentation("paperclip", {
    connection_state: "configured_unverified",
    credential_state: "stored",
    policy_state: "blocked_missing_deployment_authorization",
    verification_available: true,
    investigation_operations: [],
    investigation_routes: [],
    investigation_purposes: [],
  });

  assert.equal(saved.canEnterCredentials, true);
  assert.equal(saved.canVerify, true);
  assert.equal(saved.connectionLabel, "Saved, not checked");

  const checked = integrationPresentation("paperclip", {
    connection_state: "ready",
    credential_state: "stored",
    policy_state: "blocked_missing_deployment_authorization",
    verification_available: true,
    investigation_operations: [],
    investigation_routes: [],
    investigation_purposes: [],
  });

  assert.equal(checked.connectionLabel, "Paperclip API key checked");
  assert.deepEqual(checked.investigationOperations, []);
  assert.deepEqual(checked.investigationRoutes, []);
  assert.match(checked.operationSummary, /enables no general public-evidence operation/);
  assert.match(checked.operationSummary, /routes are not enabled by the API key/);

  const policyLabels = new Map([
    [
      "blocked_deployment_expired",
      "Patient investigations: GXL investigation authorization expired",
    ],
    [
      "blocked_deployment_operation_scope",
      "Patient investigations: GXL authorization does not cover an available operation",
    ],
    [
      "blocked_deployment_purpose_scope",
      "Patient investigations: GXL authorization does not cover an investigation purpose",
    ],
    [
      "blocked_patient_data_contract_purpose_scope",
      "Patient investigations: Patient-data agreement does not cover an investigation purpose",
    ],
  ]);
  for (const [policyState, expected] of policyLabels) {
    const presentation = integrationPresentation("paperclip", {
      connection_state: "ready",
      credential_state: "stored",
      policy_state: policyState,
      investigation_operations: [],
      investigation_routes: [],
      investigation_purposes: [],
    });
    assert.equal(presentation.policyLabel, expected);
  }
});
