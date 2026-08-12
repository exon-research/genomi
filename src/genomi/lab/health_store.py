"""Patient-entered health facts and reported-finding persistence."""

from __future__ import annotations

import uuid
from typing import Any, ContextManager, Protocol

from .models import (
    ASSERTION_STATUSES,
    EXACT_VARIANT_RE,
    FACT_LABEL_MAX,
    HEALTH_FACT_KINDS,
    RSID_RE,
    SOURCE_LABEL_MAX,
    VERIFICATION_STATES,
    JsonObject,
    choice,
    optional_text,
    required_text,
    row_dict,
    utc_now,
)


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def _require_profile(self, profile_id: str) -> None: ...


class HealthRecordStoreMixin:
    """Methods mixed into ``GenomiLabStore`` for health-record ownership."""

    def add_health_fact(
        self: _StoreContract,
        profile_id: str,
        *,
        kind: object,
        label: object,
        assertion_status: object = "present",
        onset: object = None,
        source_type: object = "patient_reported",
        verification_state: object = "user_confirmed",
        supersedes_fact_id: object = None,
    ) -> JsonObject:
        self._require_profile(profile_id)
        kind_value = choice(kind, "kind", HEALTH_FACT_KINDS)
        label_value = required_text(label, "label", FACT_LABEL_MAX)
        assertion_value = choice(assertion_status, "assertion_status", ASSERTION_STATUSES)
        verification_value = choice(
            verification_state, "verification_state", VERIFICATION_STATES
        )
        source_value = required_text(source_type, "source_type", SOURCE_LABEL_MAX)
        onset_value = optional_text(onset, "onset", SOURCE_LABEL_MAX)
        supersedes_value = optional_text(
            supersedes_fact_id, "supersedes_fact_id", SOURCE_LABEL_MAX
        )
        if supersedes_value:
            with self._connect() as connection:
                previous = connection.execute(
                    "SELECT profile_id FROM health_facts WHERE fact_id = ?",
                    (supersedes_value,),
                ).fetchone()
            if previous is None or previous["profile_id"] != profile_id:
                raise ValueError("supersedes_fact_id must name a fact in this profile")
        fact_id = f"fact-{uuid.uuid4().hex}"
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO health_facts(
                    fact_id, profile_id, kind, label, assertion_status, onset,
                    source_type, verification_state, supersedes_fact_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact_id,
                    profile_id,
                    kind_value,
                    label_value,
                    assertion_value,
                    onset_value,
                    source_value,
                    verification_value,
                    supersedes_value,
                    now,
                ),
            )
            connection.execute(
                "UPDATE profiles SET updated_at = ? WHERE profile_id = ?",
                (now, profile_id),
            )
            row = connection.execute(
                "SELECT * FROM health_facts WHERE fact_id = ?", (fact_id,)
            ).fetchone()
        return row_dict(row)

    def add_reported_finding(
        self: _StoreContract,
        profile_id: str,
        *,
        variant: object,
        gene: object = None,
        reported_classification: object = None,
        source_label: object = None,
    ) -> JsonObject:
        self._require_profile(profile_id)
        variant_value = required_text(variant, "variant", SOURCE_LABEL_MAX)
        if RSID_RE.fullmatch(variant_value):
            variant_value = variant_value.lower()
            normalization_state = "rsid_ready"
        elif EXACT_VARIANT_RE.fullmatch(variant_value):
            normalization_state = "exact_genomic_allele_ready"
        else:
            normalization_state = "needs_review"
        finding_id = f"finding-{uuid.uuid4().hex}"
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO reported_findings(
                    finding_id, profile_id, variant, gene, reported_classification,
                    source_label, normalization_state, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    finding_id,
                    profile_id,
                    variant_value,
                    optional_text(gene, "gene", 80),
                    optional_text(
                        reported_classification,
                        "reported_classification",
                        SOURCE_LABEL_MAX,
                    ),
                    optional_text(source_label, "source_label", SOURCE_LABEL_MAX),
                    normalization_state,
                    now,
                ),
            )
            connection.execute(
                "UPDATE profiles SET updated_at = ? WHERE profile_id = ?",
                (now, profile_id),
            )
            row = connection.execute(
                "SELECT * FROM reported_findings WHERE finding_id = ?", (finding_id,)
            ).fetchone()
        return row_dict(row)

    def get_finding(self: _StoreContract, finding_id: str) -> JsonObject:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM reported_findings WHERE finding_id = ?",
                (finding_id,),
            ).fetchone()
        if row is None:
            raise KeyError(finding_id)
        return row_dict(row)
