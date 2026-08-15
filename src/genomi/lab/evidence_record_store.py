"""Canonical evidence-record ledger persistence and commit guards."""

from __future__ import annotations

import uuid
from typing import Any, ContextManager, Protocol

from ..evidence import envelope as canonical_evidence_envelope
from .disease_relations import validate_reserved_relation_commit
from .models import (
    JsonObject,
    compact_json,
    redacted_private_payload,
    required_text,
    row_dict,
    utc_now,
    validate_private_payload,
)


class EvidenceCommitGuardError(ValueError):
    """A live consent or disclosure precondition changed before commit."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _EvidenceRecordStore(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def _stable_evidence_identity(self, value: object) -> object: ...


class EvidenceRecordStoreMixin:
    """Persist immutable normalized evidence against the current investigation."""

    def commit_evidence(
        self: _EvidenceRecordStore,
        investigation_id: str,
        *,
        source_family: object,
        operation: object,
        evidence: JsonObject,
        deduplication_key: object,
        expected_disclosure_receipt_id: object = None,
        expected_consent_receipt_id: object = None,
        _reserved_operation_token: object = None,
    ) -> JsonObject:
        envelope = evidence.get("evidence_envelope")
        if not isinstance(envelope, dict):
            raise ValueError("evidence must include a canonical evidence_envelope")
        validate_private_payload(envelope)
        canonical_evidence_envelope.validate(envelope)
        sanitized = redacted_private_payload(evidence)
        if not isinstance(sanitized, dict):
            raise ValueError("evidence must be an object")
        validate_private_payload(sanitized)
        source = required_text(source_family, "source_family", 100)
        operation_value = required_text(operation, "operation", 200)
        validate_reserved_relation_commit(operation_value, _reserved_operation_token)
        dedup = required_text(deduplication_key, "deduplication_key", 300)
        expected_disclosure = (
            required_text(
                expected_disclosure_receipt_id,
                "expected_disclosure_receipt_id",
                200,
            )
            if expected_disclosure_receipt_id not in (None, "")
            else None
        )
        expected_consent = (
            required_text(
                expected_consent_receipt_id,
                "expected_consent_receipt_id",
                200,
            )
            if expected_consent_receipt_id not in (None, "")
            else None
        )
        record_id = f"evidence-{uuid.uuid4().hex}"
        envelope = sanitized.get("evidence_envelope")
        evidence_json = compact_json(sanitized)
        evidence_identity_json = compact_json(self._stable_evidence_identity(sanitized))
        envelope_json = compact_json(envelope)
        with self._connect() as connection:
            investigation = connection.execute(
                "SELECT user_id, patient_molecular_snapshot_id, "
                "active_consent_receipt_id FROM investigations "
                "WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            if investigation is None:
                raise KeyError(investigation_id)
            profile_snapshot_id = investigation["patient_molecular_snapshot_id"]
            if expected_disclosure is not None:
                disclosure = connection.execute(
                    "SELECT 1 FROM outbound_disclosure_receipts "
                    "WHERE disclosure_receipt_id = ? AND investigation_id = ? "
                    "AND user_id = ? AND revoked_at IS NULL",
                    (
                        expected_disclosure,
                        investigation_id,
                        investigation["user_id"],
                    ),
                ).fetchone()
                if disclosure is None:
                    raise EvidenceCommitGuardError(
                        "disclosure_revoked",
                        "evidence disclosure was revoked before result commit",
                    )
            if expected_consent is not None:
                consent = connection.execute(
                    "SELECT 1 FROM consent_receipts "
                    "WHERE consent_receipt_id = ? AND investigation_id = ? "
                    "AND user_id = ? AND patient_molecular_snapshot_id IS ? "
                    "AND revoked_at IS NULL",
                    (
                        expected_consent,
                        investigation_id,
                        investigation["user_id"],
                        profile_snapshot_id,
                    ),
                ).fetchone()
                if (
                    consent is None
                    or investigation["active_consent_receipt_id"] != expected_consent
                ):
                    raise EvidenceCommitGuardError(
                        "consent_revoked",
                        "private molecular-context consent changed before result commit",
                    )
            existing = connection.execute(
                "SELECT * FROM evidence_records WHERE investigation_id = ? "
                "AND patient_molecular_snapshot_id IS ? AND deduplication_key = ?",
                (investigation_id, profile_snapshot_id, dedup),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["source_family"]) != source
                    or str(existing["operation"]) != operation_value
                    or compact_json(
                        self._stable_evidence_identity(
                            row_dict(existing).get("evidence") or {}
                        )
                    )
                    != evidence_identity_json
                    or str(existing["evidence_envelope_json"]) != envelope_json
                ):
                    raise ValueError(
                        "evidence deduplication key was reused for different evidence"
                    )
                return row_dict(existing)
            connection.execute(
                """
                INSERT INTO evidence_records(
                    evidence_record_id, investigation_id,
                    patient_molecular_snapshot_id, deduplication_key,
                    source_family, operation, evidence_json,
                    evidence_envelope_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    investigation_id,
                    profile_snapshot_id,
                    dedup,
                    source,
                    operation_value,
                    evidence_json,
                    envelope_json,
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM evidence_records WHERE investigation_id = ? "
                "AND patient_molecular_snapshot_id IS ? AND deduplication_key = ?",
                (investigation_id, profile_snapshot_id, dedup),
            ).fetchone()
        return row_dict(row)
