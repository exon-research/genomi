"""SQLite schema owned by the GenomiLab application domain."""

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE,
    display_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_artifacts (
    artifact_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES workspaces(user_id) ON DELETE CASCADE,
    content_sha256 TEXT NOT NULL,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    source_identifier TEXT,
    issued_at TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, content_sha256)
);
CREATE TABLE IF NOT EXISTS specimens (
    specimen_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES workspaces(user_id) ON DELETE CASCADE,
    artifact_id TEXT REFERENCES source_artifacts(artifact_id),
    specimen_type TEXT NOT NULL,
    body_site TEXT,
    collected_at TEXT,
    disease_state TEXT,
    tumor_normal_role TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assays (
    assay_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES workspaces(user_id) ON DELETE CASCADE,
    specimen_id TEXT REFERENCES specimens(specimen_id),
    artifact_id TEXT REFERENCES source_artifacts(artifact_id),
    assay_type TEXT NOT NULL,
    laboratory TEXT,
    platform TEXT,
    pipeline TEXT,
    genome_build TEXT,
    assay_scope_json TEXT NOT NULL,
    detection_limits_json TEXT NOT NULL,
    qc_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS molecular_observations (
    observation_revision_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES workspaces(user_id) ON DELETE CASCADE,
    logical_observation_id TEXT NOT NULL,
    supersedes_revision_id TEXT REFERENCES molecular_observations(observation_revision_id),
    modality TEXT NOT NULL,
    label TEXT NOT NULL,
    original_wording TEXT NOT NULL,
    assertion_status TEXT NOT NULL,
    verification_state TEXT NOT NULL,
    source_class TEXT NOT NULL,
    assertion_author TEXT NOT NULL,
    reviewed_by TEXT,
    artifact_id TEXT REFERENCES source_artifacts(artifact_id),
    source_identifier TEXT,
    source_locator TEXT,
    coverage_state TEXT NOT NULL,
    normalized_code TEXT,
    value_json TEXT,
    onset_or_event_time TEXT,
    specimen_id TEXT,
    assay_id TEXT,
    reported_variant TEXT,
    gene TEXT,
    reported_classification TEXT,
    normalization_state TEXT,
    normalization_provenance_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, logical_observation_id, observation_revision_id),
    CHECK (
        verification_state <> 'clinician_confirmed'
        OR (
            source_class = 'clinician_entered'
            AND assertion_author = 'clinician'
            AND reviewed_by IS NOT NULL
            AND length(trim(reviewed_by)) > 0
        )
    )
);
CREATE TABLE IF NOT EXISTS modality_coverage (
    user_id TEXT NOT NULL REFERENCES workspaces(user_id) ON DELETE CASCADE,
    modality TEXT NOT NULL,
    coverage_state TEXT NOT NULL,
    assay_scope_json TEXT,
    detection_limits_json TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, modality)
);
CREATE TABLE IF NOT EXISTS profile_snapshots (
    patient_molecular_snapshot_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES workspaces(user_id) ON DELETE CASCADE,
    investigation_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    prior_patient_molecular_snapshot_id TEXT REFERENCES profile_snapshots(patient_molecular_snapshot_id),
    diff_json TEXT NOT NULL,
    purpose TEXT NOT NULL,
    observation_revision_ids_json TEXT NOT NULL,
    artifact_ids_json TEXT NOT NULL,
    specimen_ids_json TEXT NOT NULL,
    assay_ids_json TEXT NOT NULL,
    modality_coverage_json TEXT NOT NULL,
    genomic_scope_json TEXT,
    agi_id TEXT,
    agi_snapshot_id TEXT,
    consent_receipt_id TEXT NOT NULL,
    manifest_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    CHECK ((agi_id IS NULL AND agi_snapshot_id IS NULL) OR
           (agi_id IS NOT NULL AND agi_snapshot_id IS NOT NULL)),
    UNIQUE(investigation_id, version)
);
CREATE TABLE IF NOT EXISTS consent_receipts (
    consent_receipt_id TEXT PRIMARY KEY,
    workspace_session_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES workspaces(user_id) ON DELETE CASCADE,
    investigation_id TEXT NOT NULL,
    patient_molecular_snapshot_id TEXT,
    purpose TEXT NOT NULL,
    observation_revision_ids_json TEXT NOT NULL,
    artifact_ids_json TEXT NOT NULL,
    specimen_ids_json TEXT NOT NULL,
    assay_ids_json TEXT NOT NULL,
    agi_id TEXT,
    agi_snapshot_id TEXT,
    genomic_scope_json TEXT,
    approved_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS outbound_disclosure_receipts (
    disclosure_receipt_id TEXT PRIMARY KEY,
    workspace_session_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES workspaces(user_id) ON DELETE CASCADE,
    investigation_id TEXT NOT NULL,
    recipient_kind TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    destination TEXT NOT NULL,
    data_categories_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    policy_versions_json TEXT,
    approved_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS investigations (
    investigation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES workspaces(user_id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    disease_scope TEXT,
    status TEXT NOT NULL,
    patient_molecular_snapshot_id TEXT REFERENCES profile_snapshots(patient_molecular_snapshot_id),
    active_consent_receipt_id TEXT REFERENCES consent_receipts(consent_receipt_id),
    agi_id TEXT,
    agi_snapshot_id TEXT,
    evidence_snapshot_id TEXT,
    domain_revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence_records (
    evidence_record_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    patient_molecular_snapshot_id TEXT REFERENCES profile_snapshots(patient_molecular_snapshot_id),
    deduplication_key TEXT NOT NULL,
    source_family TEXT NOT NULL,
    operation TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    evidence_envelope_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(investigation_id, patient_molecular_snapshot_id, deduplication_key)
);
CREATE TABLE IF NOT EXISTS hypotheses (
    hypothesis_id TEXT PRIMARY KEY,
    logical_hypothesis_id TEXT NOT NULL,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    patient_molecular_snapshot_id TEXT NOT NULL REFERENCES profile_snapshots(patient_molecular_snapshot_id),
    supersedes_hypothesis_id TEXT REFERENCES hypotheses(hypothesis_id),
    version INTEGER NOT NULL,
    kind TEXT NOT NULL,
    statement TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence_record_ids_json TEXT NOT NULL,
    profile_revision_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(investigation_id, logical_hypothesis_id, version)
);
CREATE TABLE IF NOT EXISTS evidence_snapshots (
    evidence_snapshot_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    patient_molecular_snapshot_id TEXT REFERENCES profile_snapshots(patient_molecular_snapshot_id),
    version INTEGER NOT NULL,
    evidence_record_ids_json TEXT NOT NULL,
    prior_evidence_snapshot_id TEXT REFERENCES evidence_snapshots(evidence_snapshot_id),
    diff_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(investigation_id, version)
);
CREATE TABLE IF NOT EXISTS brief_versions (
    brief_version_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    patient_molecular_snapshot_id TEXT REFERENCES profile_snapshots(patient_molecular_snapshot_id),
    evidence_snapshot_id TEXT REFERENCES evidence_snapshots(evidence_snapshot_id),
    prior_brief_version_id TEXT REFERENCES brief_versions(brief_version_id),
    diff_json TEXT NOT NULL,
    brief_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(investigation_id, version)
);
CREATE INDEX IF NOT EXISTS idx_observations_user_created
    ON molecular_observations(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_observations_user_logical
    ON molecular_observations(user_id, logical_observation_id, created_at DESC);
-- Reopening an existing workspace installs the revision-chain invariant in place.
CREATE UNIQUE INDEX IF NOT EXISTS idx_observations_one_successor
    ON molecular_observations(supersedes_revision_id)
    WHERE supersedes_revision_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_observations_one_root
    ON molecular_observations(user_id, logical_observation_id)
    WHERE supersedes_revision_id IS NULL;
CREATE TRIGGER IF NOT EXISTS molecular_observations_root_identity_insert
BEFORE INSERT ON molecular_observations
WHEN NEW.supersedes_revision_id IS NULL
BEGIN
    SELECT CASE WHEN
        NEW.observation_revision_id NOT GLOB 'observation-revision-*'
        OR length(NEW.observation_revision_id) <= length('observation-revision-')
        OR NEW.logical_observation_id <>
           'observation-' || substr(
               NEW.observation_revision_id,
               length('observation-revision-') + 1
           )
    THEN RAISE(ABORT, 'new observation root has an invalid logical identity') END;
END;
CREATE TRIGGER IF NOT EXISTS molecular_observations_revision_chain_insert
BEFORE INSERT ON molecular_observations
WHEN NEW.supersedes_revision_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
          FROM molecular_observations AS prior
         WHERE prior.observation_revision_id = NEW.supersedes_revision_id
           AND prior.user_id = NEW.user_id
           AND prior.logical_observation_id = NEW.logical_observation_id
    ) THEN RAISE(ABORT, 'revision target must match the same user and logical observation') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1
          FROM molecular_observations AS successor
         WHERE successor.supersedes_revision_id = NEW.supersedes_revision_id
    ) THEN RAISE(ABORT, 'only the current observation revision can be superseded') END;
END;
-- Triggers apply the clinician provenance invariant to pre-existing tables,
-- whose original CREATE TABLE statement cannot gain the new CHECK in place.
CREATE TRIGGER IF NOT EXISTS molecular_observations_clinician_insert
BEFORE INSERT ON molecular_observations
WHEN NEW.verification_state = 'clinician_confirmed'
 AND (
     NEW.source_class <> 'clinician_entered'
     OR NEW.assertion_author <> 'clinician'
     OR NEW.reviewed_by IS NULL
     OR length(trim(NEW.reviewed_by)) = 0
 )
BEGIN
    SELECT RAISE(ABORT, 'clinician-confirmed observation lacks clinician provenance');
END;
CREATE TRIGGER IF NOT EXISTS molecular_observations_issued_source_insert
BEFORE INSERT ON molecular_observations
WHEN NEW.source_class = 'issued_record'
 AND NEW.artifact_id IS NULL
 AND (NEW.source_identifier IS NULL OR length(trim(NEW.source_identifier)) = 0)
BEGIN
    SELECT RAISE(ABORT, 'issued-record observation lacks source provenance');
END;
CREATE TRIGGER IF NOT EXISTS molecular_observations_issued_artifact_insert
BEFORE INSERT ON molecular_observations
WHEN NEW.source_class = 'issued_record'
 AND NEW.artifact_id IS NOT NULL
 AND NOT EXISTS (
     SELECT 1 FROM source_artifacts
      WHERE artifact_id = NEW.artifact_id
        AND user_id = NEW.user_id
        AND source_type IN (
            'issued_report', 'laboratory_report', 'pathology_report', 'clinical_note'
        )
 )
BEGIN
    SELECT RAISE(ABORT, 'issued-record observation lacks an issued medical artifact');
END;
CREATE TRIGGER IF NOT EXISTS molecular_observations_record_confirmation_source_insert
BEFORE INSERT ON molecular_observations
WHEN NEW.verification_state = 'record_confirmed'
 AND NEW.artifact_id IS NULL
 AND (NEW.source_identifier IS NULL OR length(trim(NEW.source_identifier)) = 0)
BEGIN
    SELECT RAISE(ABORT, 'record-confirmed observation lacks source provenance');
END;
-- Revisions and their source entities are content-addressed inputs to approved
-- snapshots. Corrections are new rows; the evidence behind an existing ID may
-- never be rewritten in place. Drop the former partial guards so every existing
-- workspace converges on the complete invariant when it is reopened.
DROP TRIGGER IF EXISTS molecular_observations_revision_identity_immutable;
DROP TRIGGER IF EXISTS molecular_observations_clinician_update;
CREATE TRIGGER IF NOT EXISTS molecular_observations_revision_immutable
BEFORE UPDATE ON molecular_observations
BEGIN
    SELECT RAISE(ABORT, 'observation revisions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS molecular_observations_revision_delete_immutable
BEFORE DELETE ON molecular_observations
BEGIN
    SELECT RAISE(ABORT, 'observation revisions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS source_artifacts_immutable
BEFORE UPDATE ON source_artifacts
BEGIN
    SELECT RAISE(ABORT, 'source artifacts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS source_artifacts_delete_immutable
BEFORE DELETE ON source_artifacts
BEGIN
    SELECT RAISE(ABORT, 'source artifacts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS specimens_immutable
BEFORE UPDATE ON specimens
BEGIN
    SELECT RAISE(ABORT, 'specimens are immutable');
END;
CREATE TRIGGER IF NOT EXISTS specimens_delete_immutable
BEFORE DELETE ON specimens
BEGIN
    SELECT RAISE(ABORT, 'specimens are immutable');
END;
CREATE TRIGGER IF NOT EXISTS assays_immutable
BEFORE UPDATE ON assays
BEGIN
    SELECT RAISE(ABORT, 'assays are immutable');
END;
CREATE TRIGGER IF NOT EXISTS assays_delete_immutable
BEFORE DELETE ON assays
BEGIN
    SELECT RAISE(ABORT, 'assays are immutable');
END;
CREATE INDEX IF NOT EXISTS idx_snapshots_user_created
    ON profile_snapshots(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_investigation_version
    ON profile_snapshots(investigation_id, version);
CREATE INDEX IF NOT EXISTS idx_artifacts_user_created
    ON source_artifacts(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_specimens_user_created
    ON specimens(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assays_user_created
    ON assays(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_consents_session_user
    ON consent_receipts(workspace_session_id, user_id, revoked_at);
CREATE INDEX IF NOT EXISTS idx_disclosures_session_user
    ON outbound_disclosure_receipts(workspace_session_id, user_id, revoked_at);
CREATE INDEX IF NOT EXISTS idx_investigations_user_created
    ON investigations(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_investigation_created
    ON evidence_records(investigation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_evidence_investigation_profile
    ON evidence_records(investigation_id, patient_molecular_snapshot_id, created_at);
CREATE INDEX IF NOT EXISTS idx_evidence_snapshots_investigation_version
    ON evidence_snapshots(investigation_id, version);
CREATE INDEX IF NOT EXISTS idx_hypotheses_logical_version
    ON hypotheses(investigation_id, logical_hypothesis_id, version);
PRAGMA optimize;
"""
