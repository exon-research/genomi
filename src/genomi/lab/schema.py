"""SQLite schema owned by the GenomiLab application."""

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS profiles (
    profile_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    genomi_user_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS health_facts (
    fact_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    assertion_status TEXT NOT NULL,
    onset TEXT,
    source_type TEXT NOT NULL,
    verification_state TEXT NOT NULL,
    supersedes_fact_id TEXT REFERENCES health_facts(fact_id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reported_findings (
    finding_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    variant TEXT NOT NULL,
    gene TEXT,
    reported_classification TEXT,
    source_label TEXT,
    normalization_state TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS genome_assignments (
    profile_id TEXT PRIMARY KEY REFERENCES profiles(profile_id) ON DELETE CASCADE,
    agi_id TEXT NOT NULL UNIQUE,
    genome_build TEXT,
    readiness TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS portal_jobs (
    portal_job_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    genomi_job_id TEXT,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    staged_name TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consent_receipts (
    consent_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    agi_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS investigations (
    investigation_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    finding_id TEXT REFERENCES reported_findings(finding_id),
    question TEXT NOT NULL,
    status TEXT NOT NULL,
    brief_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS health_facts_profile_created
    ON health_facts(profile_id, created_at DESC);
CREATE INDEX IF NOT EXISTS reported_findings_profile_created
    ON reported_findings(profile_id, created_at DESC);
CREATE INDEX IF NOT EXISTS portal_jobs_profile_created
    ON portal_jobs(profile_id, created_at DESC);
CREATE INDEX IF NOT EXISTS consent_profile_session
    ON consent_receipts(profile_id, session_id, revoked_at);
CREATE INDEX IF NOT EXISTS investigations_profile_created
    ON investigations(profile_id, created_at DESC);
PRAGMA optimize;
"""
