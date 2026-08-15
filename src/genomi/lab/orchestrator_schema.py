"""Durable schema for the Main-Orchestrator GenomiLab contract.

The objects here are private orchestrator state, de-identified specialist
disclosures, or tamper-evident evidence receipts. No external-agent or
subprocess state belongs in this schema.
"""

from __future__ import annotations

from typing import Any


ORCHESTRATOR_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS orchestrator_commands (
    command_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS investigation_cycles (
    cycle_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    prior_cycle_id TEXT UNIQUE REFERENCES investigation_cycles(cycle_id),
    patient_molecular_snapshot_id TEXT REFERENCES profile_snapshots(patient_molecular_snapshot_id),
    evidence_snapshot_id TEXT REFERENCES evidence_snapshots(evidence_snapshot_id),
    public_only INTEGER NOT NULL CHECK (public_only IN (0, 1)),
    purpose TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(investigation_id, ordinal)
);
CREATE TABLE IF NOT EXISTS orchestrator_investigation_contexts (
    investigation_id TEXT PRIMARY KEY REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    workspace_session_id TEXT NOT NULL,
    public_only INTEGER NOT NULL CHECK (public_only IN (0, 1)),
    created_by_command_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS specialist_brief_derivations (
    specialist_brief_derivation_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    cycle_id TEXT NOT NULL REFERENCES investigation_cycles(cycle_id) ON DELETE CASCADE,
    execution_policy TEXT NOT NULL CHECK (execution_policy IN (
        'reasoning_only', 'public_literature',
        'protein_model_research', 'experiment_design'
    )),
    source_fact_ids_json TEXT NOT NULL,
    public_evidence_record_ids_json TEXT NOT NULL,
    patient_molecular_snapshot_id TEXT REFERENCES profile_snapshots(patient_molecular_snapshot_id),
    consent_receipt_id TEXT REFERENCES consent_receipts(consent_receipt_id),
    rationale TEXT NOT NULL,
    purpose TEXT NOT NULL,
    outbound_payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS specialist_briefs (
    specialist_brief_id TEXT PRIMARY KEY,
    specialist_brief_derivation_id TEXT NOT NULL UNIQUE REFERENCES specialist_brief_derivations(specialist_brief_derivation_id) ON DELETE CASCADE,
    execution_policy TEXT NOT NULL,
    policy_sha256 TEXT NOT NULL,
    outbound_payload_json TEXT NOT NULL,
    outbound_payload_sha256 TEXT NOT NULL,
    disclosure_receipt_id TEXT REFERENCES outbound_disclosure_receipts(disclosure_receipt_id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS specialist_assignments (
    specialist_assignment_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    cycle_id TEXT NOT NULL REFERENCES investigation_cycles(cycle_id) ON DELETE CASCADE,
    specialist_brief_id TEXT NOT NULL REFERENCES specialist_briefs(specialist_brief_id),
    specialist_role TEXT NOT NULL,
    execution_policy TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('proposed', 'spawned', 'completed', 'failed', 'cancelled')),
    native_agent_id TEXT,
    specialist_analysis_id TEXT,
    revision INTEGER NOT NULL CHECK (revision > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS specialist_assignment_events (
    specialist_assignment_event_id TEXT PRIMARY KEY,
    specialist_assignment_id TEXT NOT NULL REFERENCES specialist_assignments(specialist_assignment_id) ON DELETE CASCADE,
    from_state TEXT,
    to_state TEXT NOT NULL,
    assignment_revision INTEGER NOT NULL CHECK (assignment_revision > 0),
    reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(specialist_assignment_id, assignment_revision)
);
CREATE TABLE IF NOT EXISTS specialist_analyses (
    specialist_analysis_id TEXT PRIMARY KEY,
    specialist_assignment_id TEXT NOT NULL UNIQUE REFERENCES specialist_assignments(specialist_assignment_id) ON DELETE CASCADE,
    general_analysis_json TEXT NOT NULL,
    uncertainty_json TEXT NOT NULL,
    alternatives_json TEXT NOT NULL,
    gaps_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS genomi_result_receipts (
    result_receipt_id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    params_json TEXT NOT NULL,
    presented_result_json TEXT NOT NULL,
    presented_result_sha256 TEXT NOT NULL,
    evidence_envelope_json TEXT NOT NULL,
    defaults_applied_json TEXT NOT NULL,
    coverage_json TEXT NOT NULL,
    source_provenance_json TEXT NOT NULL,
    workspace_session_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES workspaces(user_id) ON DELETE CASCADE,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    patient_molecular_snapshot_id TEXT REFERENCES profile_snapshots(patient_molecular_snapshot_id),
    consent_receipt_id TEXT REFERENCES consent_receipts(consent_receipt_id),
    agi_id TEXT,
    agi_snapshot_id TEXT,
    receipt_sha256 TEXT NOT NULL UNIQUE,
    issued_at TEXT NOT NULL,
    captured_at TEXT
);
CREATE TABLE IF NOT EXISTS captured_evidence_results (
    captured_evidence_result_id TEXT PRIMARY KEY,
    result_receipt_id TEXT NOT NULL UNIQUE REFERENCES genomi_result_receipts(result_receipt_id),
    evidence_record_id TEXT NOT NULL UNIQUE REFERENCES evidence_records(evidence_record_id),
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    cycle_id TEXT NOT NULL REFERENCES investigation_cycles(cycle_id),
    captured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_result_receipts (
    provider_result_receipt_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    result_kind TEXT NOT NULL CHECK (result_kind IN ('public_source_evidence', 'research_artifact')),
    operation TEXT NOT NULL,
    exact_result_json TEXT NOT NULL,
    exact_result_sha256 TEXT NOT NULL,
    specialist_assignment_id TEXT NOT NULL REFERENCES specialist_assignments(specialist_assignment_id),
    specialist_brief_id TEXT NOT NULL REFERENCES specialist_briefs(specialist_brief_id),
    specialist_brief_payload_sha256 TEXT NOT NULL,
    disclosure_receipt_id TEXT REFERENCES outbound_disclosure_receipts(disclosure_receipt_id),
    provider_provenance_json TEXT NOT NULL,
    receipt_sha256 TEXT NOT NULL UNIQUE,
    issued_at TEXT NOT NULL,
    captured_at TEXT
);
CREATE TABLE IF NOT EXISTS research_artifacts (
    research_artifact_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    cycle_id TEXT NOT NULL REFERENCES investigation_cycles(cycle_id),
    specialist_assignment_id TEXT NOT NULL REFERENCES specialist_assignments(specialist_assignment_id),
    provider_result_receipt_id TEXT NOT NULL UNIQUE REFERENCES provider_result_receipts(provider_result_receipt_id),
    provider TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS captured_provider_results (
    captured_provider_result_id TEXT PRIMARY KEY,
    provider_result_receipt_id TEXT NOT NULL UNIQUE REFERENCES provider_result_receipts(provider_result_receipt_id),
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    cycle_id TEXT NOT NULL REFERENCES investigation_cycles(cycle_id),
    specialist_assignment_id TEXT NOT NULL REFERENCES specialist_assignments(specialist_assignment_id),
    evidence_record_id TEXT REFERENCES evidence_records(evidence_record_id),
    research_artifact_id TEXT REFERENCES research_artifacts(research_artifact_id),
    captured_at TEXT NOT NULL,
    CHECK ((evidence_record_id IS NOT NULL AND research_artifact_id IS NULL)
        OR (evidence_record_id IS NULL AND research_artifact_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS orchestrator_hypothesis_threads (
    logical_hypothesis_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    parent_logical_hypothesis_id TEXT REFERENCES orchestrator_hypothesis_threads(logical_hypothesis_id),
    category TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orchestrator_hypothesis_versions (
    hypothesis_version_id TEXT PRIMARY KEY,
    logical_hypothesis_id TEXT NOT NULL REFERENCES orchestrator_hypothesis_threads(logical_hypothesis_id) ON DELETE CASCADE,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    cycle_id TEXT NOT NULL REFERENCES investigation_cycles(cycle_id),
    patient_molecular_snapshot_id TEXT REFERENCES profile_snapshots(patient_molecular_snapshot_id),
    evidence_snapshot_id TEXT REFERENCES evidence_snapshots(evidence_snapshot_id),
    supersedes_hypothesis_version_id TEXT UNIQUE REFERENCES orchestrator_hypothesis_versions(hypothesis_version_id),
    version INTEGER NOT NULL CHECK (version > 0),
    statement TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'strengthened', 'weakened', 'retained', 'rejected', 'resolved')),
    patient_fact_ids_json TEXT NOT NULL,
    supporting_evidence_record_ids_json TEXT NOT NULL,
    contradicting_evidence_record_ids_json TEXT NOT NULL,
    contextual_evidence_record_ids_json TEXT NOT NULL,
    unresolved_gaps_json TEXT NOT NULL,
    revision_rationale TEXT NOT NULL,
    patient_specific_assessment_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(logical_hypothesis_id, version)
);
CREATE INDEX IF NOT EXISTS idx_cycles_investigation ON investigation_cycles(investigation_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_specialist_briefs_cycle ON specialist_brief_derivations(cycle_id, created_at);
CREATE INDEX IF NOT EXISTS idx_specialist_assignments_cycle ON specialist_assignments(cycle_id, created_at);
CREATE INDEX IF NOT EXISTS idx_orchestrator_hypotheses_investigation ON orchestrator_hypothesis_threads(investigation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_orchestrator_hypothesis_versions_thread ON orchestrator_hypothesis_versions(logical_hypothesis_id, version);
CREATE TRIGGER IF NOT EXISTS specialist_brief_derivations_immutable BEFORE UPDATE ON specialist_brief_derivations BEGIN SELECT RAISE(ABORT, 'specialist brief derivations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS specialist_briefs_immutable BEFORE UPDATE ON specialist_briefs BEGIN SELECT RAISE(ABORT, 'specialist briefs are immutable'); END;
CREATE TRIGGER IF NOT EXISTS specialist_analyses_immutable BEFORE UPDATE ON specialist_analyses BEGIN SELECT RAISE(ABORT, 'specialist analyses are immutable'); END;
CREATE TRIGGER IF NOT EXISTS orchestrator_hypothesis_threads_immutable BEFORE UPDATE ON orchestrator_hypothesis_threads BEGIN SELECT RAISE(ABORT, 'hypothesis threads are immutable'); END;
CREATE TRIGGER IF NOT EXISTS orchestrator_hypothesis_versions_immutable BEFORE UPDATE ON orchestrator_hypothesis_versions BEGIN SELECT RAISE(ABORT, 'hypothesis versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS genomi_result_receipts_content_immutable BEFORE UPDATE ON genomi_result_receipts
WHEN NEW.result_receipt_id IS NOT OLD.result_receipt_id OR NEW.operation IS NOT OLD.operation
  OR NEW.params_json IS NOT OLD.params_json OR NEW.presented_result_json IS NOT OLD.presented_result_json
  OR NEW.presented_result_sha256 IS NOT OLD.presented_result_sha256 OR NEW.evidence_envelope_json IS NOT OLD.evidence_envelope_json
  OR NEW.defaults_applied_json IS NOT OLD.defaults_applied_json OR NEW.coverage_json IS NOT OLD.coverage_json
  OR NEW.source_provenance_json IS NOT OLD.source_provenance_json OR NEW.workspace_session_id IS NOT OLD.workspace_session_id
  OR NEW.user_id IS NOT OLD.user_id OR NEW.investigation_id IS NOT OLD.investigation_id
  OR NEW.patient_molecular_snapshot_id IS NOT OLD.patient_molecular_snapshot_id OR NEW.consent_receipt_id IS NOT OLD.consent_receipt_id
  OR NEW.agi_id IS NOT OLD.agi_id OR NEW.agi_snapshot_id IS NOT OLD.agi_snapshot_id
  OR NEW.receipt_sha256 IS NOT OLD.receipt_sha256 OR NEW.issued_at IS NOT OLD.issued_at
  OR OLD.captured_at IS NOT NULL OR NEW.captured_at IS NULL
BEGIN SELECT RAISE(ABORT, 'Genomi result receipt content is immutable'); END;
CREATE TRIGGER IF NOT EXISTS provider_result_receipts_content_immutable BEFORE UPDATE ON provider_result_receipts
WHEN NEW.provider_result_receipt_id IS NOT OLD.provider_result_receipt_id OR NEW.provider IS NOT OLD.provider
  OR NEW.result_kind IS NOT OLD.result_kind OR NEW.operation IS NOT OLD.operation
  OR NEW.exact_result_json IS NOT OLD.exact_result_json OR NEW.exact_result_sha256 IS NOT OLD.exact_result_sha256
  OR NEW.specialist_assignment_id IS NOT OLD.specialist_assignment_id OR NEW.specialist_brief_id IS NOT OLD.specialist_brief_id
  OR NEW.specialist_brief_payload_sha256 IS NOT OLD.specialist_brief_payload_sha256
  OR NEW.disclosure_receipt_id IS NOT OLD.disclosure_receipt_id OR NEW.provider_provenance_json IS NOT OLD.provider_provenance_json
  OR NEW.receipt_sha256 IS NOT OLD.receipt_sha256 OR NEW.issued_at IS NOT OLD.issued_at
  OR OLD.captured_at IS NOT NULL OR NEW.captured_at IS NULL
BEGIN SELECT RAISE(ABORT, 'provider result receipt content is immutable'); END;
"""


def install_orchestrator_schema(connection: Any) -> None:
    """Install the current Main-Orchestrator contract idempotently."""

    connection.executescript(ORCHESTRATOR_SCHEMA_SQL)


__all__ = ["ORCHESTRATOR_SCHEMA_SQL", "install_orchestrator_schema"]
