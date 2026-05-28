from __future__ import annotations

from typing import Any

JsonObject = dict[str, Any]

JOURNAL_SCHEMA = "genomi-journal-v1"
MEMORY_ARTIFACT_SCHEMA = "genomi-journal-memory-artifact-v1"
JOURNAL_DB_NAME = "journal.sqlite"
JOURNALS_DIR_NAME = "journals"

ENTRY_TYPES = {
    "observation",
    "hypothesis",
    "decision",
    "contradiction",
    "unresolved_question",
    "protocol_note",
    "plan",
    "summary",
}
CLAIM_LIKE_ENTRY_TYPES = {"observation", "hypothesis", "decision", "contradiction", "summary"}
DECISION_STATUSES = {"supported", "unresolved", "unsupported", "superseded"}
AMENDMENT_TYPES = {"correction", "clarification", "supersession", "note"}

PRIVATE_SCOPE_MARKERS = {
    "active_genome_index",
    "active_genome_index_private_scope",
    "local_private",
    "personal",
    "personal_dna",
    "private",
    "sample",
    "sample_context",
}
PRIVATE_OPERATION_PREFIXES = (
    "active_genome_index.",
)
PRIVATE_OPERATIONS = {
    "pharmacogenomics.import_pharmcat_artifacts",
    "pharmacogenomics.preflight_pharmcat",
    "pharmacogenomics.prepare_outside_call_tsv",
    "pharmacogenomics.run_pharmcat",
    "pharmacogenomics.validate_outside_call_tsv",
}
PRIVATE_PAYLOAD_KEYS = {
    "active_genome_index",
    "active_agi_id",
    "agi_id",
    "candidate_inventory",
    "genotype",
    "matches",
    "sample",
    "sample_id",
    "sample_presence_context",
    "vcf",
}


class JournalError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
