"""Exact subjects derived from one active investigation authorization."""

from __future__ import annotations

import hashlib
from typing import Any, ContextManager, Protocol

from .authorization_store import (
    AUTHORIZATION_SUBJECT_KINDS,
    AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
    AUTHORIZATION_SUBJECT_PLAN_ACCEPTANCE,
    _sha256_digest,
)
from .models import (
    JsonObject,
    compact_json,
    required_text,
    row_dict,
    stable_id,
    utc_now,
    validate_private_payload,
)


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def _require_active_authorization(
        self, connection: Any, receipt: JsonObject
    ) -> None: ...


class InvestigationAuthorizationDerivationStoreMixin:
    """Persist and revalidate exact disclosures and accepted plans."""

    def derive_investigation_authorization_subject(
        self: _StoreContract,
        authorization_receipt_id: object,
        *,
        subject_kind: object,
        subject_id: object,
    ) -> JsonObject:
        receipt_id = required_text(
            authorization_receipt_id, "authorization_receipt_id", 200
        )
        kind = _subject_kind(subject_kind)
        identifier = required_text(subject_id, "authorization subject_id", 300)
        subject_column = _subject_id_column(kind)
        with self._connect() as connection:
            receipt_row = connection.execute(
                "SELECT * FROM investigation_authorization_receipts "
                "WHERE authorization_receipt_id = ?",
                (receipt_id,),
            ).fetchone()
            if receipt_row is None:
                raise ValueError("investigation authorization receipt not found")
            authorization = row_dict(receipt_row)
            self._require_active_authorization(connection, authorization)
            _subject, fingerprint = _authorization_subject(
                connection, authorization, kind, identifier
            )
            existing_row = connection.execute(
                "SELECT * FROM investigation_authorization_derivations "
                f"WHERE {subject_column} = ?",
                (identifier,),
            ).fetchone()
            if existing_row is not None:
                existing = _derivation_view(existing_row)
                if (
                    existing.get("authorization_receipt_id") != receipt_id
                    or existing.get("subject_fingerprint") != fingerprint
                ):
                    raise ValueError(
                        "authorization subject is already linked to a different receipt"
                    )
                return existing
            derivation_id = stable_id(
                "authorization-derivation",
                receipt_id,
                kind,
                identifier,
                fingerprint,
            )
            connection.execute(
                "INSERT INTO investigation_authorization_derivations("
                "authorization_derivation_id, authorization_receipt_id, "
                f"{subject_column}, subject_fingerprint, derived_at"
                ") VALUES (?, ?, ?, ?, ?)",
                (
                    derivation_id,
                    receipt_id,
                    identifier,
                    fingerprint,
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM investigation_authorization_derivations "
                "WHERE authorization_derivation_id = ?",
                (derivation_id,),
            ).fetchone()
        return _derivation_view(row)

    def require_investigation_authorization_subject(
        self: _StoreContract,
        authorization_receipt_id: object,
        *,
        subject_kind: object,
        subject_id: object,
    ) -> JsonObject:
        receipt_id = required_text(
            authorization_receipt_id, "authorization_receipt_id", 200
        )
        kind = _subject_kind(subject_kind)
        identifier = required_text(subject_id, "authorization subject_id", 300)
        subject_column = _subject_id_column(kind)
        with self._connect() as connection:
            receipt_row = connection.execute(
                "SELECT * FROM investigation_authorization_receipts "
                "WHERE authorization_receipt_id = ?",
                (receipt_id,),
            ).fetchone()
            if receipt_row is None:
                raise ValueError("investigation authorization receipt not found")
            authorization = row_dict(receipt_row)
            self._require_active_authorization(connection, authorization)
            subject, fingerprint = _authorization_subject(
                connection, authorization, kind, identifier
            )
            derivation_row = connection.execute(
                "SELECT * FROM investigation_authorization_derivations "
                f"WHERE {subject_column} = ?",
                (identifier,),
            ).fetchone()
            if derivation_row is None:
                raise ValueError(
                    "subject is not derived from this investigation authorization"
                )
            derivation = _derivation_view(derivation_row)
            if (
                derivation.get("authorization_receipt_id") != receipt_id
                or derivation.get("subject_fingerprint") != fingerprint
            ):
                raise ValueError(
                    "subject derivation does not match this investigation authorization"
                )
            return _authorization_bundle(authorization, derivation, subject)

    def investigation_authorization_for_subject(
        self: _StoreContract,
        *,
        subject_kind: object,
        subject_id: object,
    ) -> JsonObject | None:
        """Discover and revalidate the active authority behind one subject."""

        kind = _subject_kind(subject_kind)
        identifier = required_text(subject_id, "authorization subject_id", 300)
        subject_column = _subject_id_column(kind)
        with self._connect() as connection:
            derivation_row = connection.execute(
                "SELECT * FROM investigation_authorization_derivations "
                f"WHERE {subject_column} = ?",
                (identifier,),
            ).fetchone()
            if derivation_row is None:
                return None
            derivation = _derivation_view(derivation_row)
            authorization_row = connection.execute(
                "SELECT * FROM investigation_authorization_receipts "
                "WHERE authorization_receipt_id = ?",
                (derivation["authorization_receipt_id"],),
            ).fetchone()
            if authorization_row is None:
                raise ValueError(
                    "subject derivation lost its investigation authorization"
                )
            authorization = row_dict(authorization_row)
            self._require_active_authorization(connection, authorization)
            subject, fingerprint = _authorization_subject(
                connection, authorization, kind, identifier
            )
            if derivation.get("subject_fingerprint") != fingerprint:
                raise ValueError(
                    "subject derivation does not match this investigation authorization"
                )
            return _authorization_bundle(authorization, derivation, subject)


def _authorization_bundle(
    authorization: JsonObject,
    derivation: JsonObject,
    subject: JsonObject,
) -> JsonObject:
    return {
        "authorization": authorization,
        "derivation": derivation,
        "subject": subject,
    }


def _derivation_view(row: object) -> JsonObject:
    record = row_dict(row)
    disclosure_id = record.pop("disclosure_receipt_id", None)
    plan_acceptance_id = record.pop("plan_acceptance_id", None)
    if disclosure_id is not None:
        record["subject_kind"] = AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE
        record["subject_id"] = disclosure_id
    elif plan_acceptance_id is not None:
        record["subject_kind"] = AUTHORIZATION_SUBJECT_PLAN_ACCEPTANCE
        record["subject_id"] = plan_acceptance_id
    else:
        raise ValueError("authorization derivation has no typed subject")
    return record


def _subject_id_column(subject_kind: str) -> str:
    if subject_kind == AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE:
        return "disclosure_receipt_id"
    return "plan_acceptance_id"


def _authorization_subject(
    connection: Any,
    authorization: JsonObject,
    subject_kind: str,
    subject_id: str,
) -> tuple[JsonObject, str]:
    if subject_kind == AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE:
        return _outbound_disclosure_subject(
            connection, authorization, subject_id
        )
    return _plan_acceptance_subject(connection, authorization, subject_id)


def _outbound_disclosure_subject(
    connection: Any,
    authorization: JsonObject,
    subject_id: str,
) -> tuple[JsonObject, str]:
    row = connection.execute(
        "SELECT * FROM outbound_disclosure_receipts "
        "WHERE disclosure_receipt_id = ?",
        (subject_id,),
    ).fetchone()
    if row is None:
        raise ValueError("outbound disclosure subject not found")
    subject = row_dict(row)
    if subject.get("revoked_at") is not None:
        raise ValueError("outbound disclosure subject is revoked")
    harness_scope = authorization["authorization_scope"]["harness"]
    expected = {
        "workspace_session_id": authorization["workspace_session_id"],
        "user_id": authorization["user_id"],
        "investigation_id": authorization["investigation_id"],
        "recipient_kind": "installed_harness",
        "recipient_id": harness_scope["recipient_id"],
        "destination": harness_scope["destination"],
    }
    if any(subject.get(key) != value for key, value in expected.items()):
        raise ValueError(
            "outbound disclosure subject belongs to different authorization scope"
        )
    stored_fingerprint = _sha256_digest(
        subject.get("payload_sha256"), "outbound disclosure payload_sha256"
    )
    fingerprint = _json_sha256(
        subject.get("payload"), "outbound disclosure payload"
    )
    if fingerprint != stored_fingerprint:
        raise ValueError("outbound disclosure subject integrity failed")
    return subject, fingerprint


def _plan_acceptance_subject(
    connection: Any,
    authorization: JsonObject,
    subject_id: str,
) -> tuple[JsonObject, str]:
    row = connection.execute(
        "SELECT acceptance.*, "
        "plan.patient_molecular_snapshot_id AS subject_patient_molecular_snapshot_id, "
        "plan.plan_json AS subject_plan_json, "
        "(SELECT current_plan.plan_version_id FROM plan_versions AS current_plan "
        "WHERE current_plan.investigation_id = acceptance.investigation_id "
        "AND current_plan.patient_molecular_snapshot_id "
        "IS plan.patient_molecular_snapshot_id "
        "ORDER BY current_plan.version DESC LIMIT 1) "
        "AS current_plan_version_id "
        "FROM plan_acceptances AS acceptance "
        "JOIN plan_versions AS plan "
        "ON plan.plan_version_id = acceptance.plan_version_id "
        "WHERE acceptance.plan_acceptance_id = ?",
        (subject_id,),
    ).fetchone()
    if row is None:
        raise ValueError("plan acceptance subject not found")
    subject = row_dict(row)
    expected = {
        "workspace_session_id": authorization["workspace_session_id"],
        "user_id": authorization["user_id"],
        "investigation_id": authorization["investigation_id"],
        "subject_patient_molecular_snapshot_id": authorization[
            "patient_molecular_snapshot_id"
        ],
        "current_plan_version_id": subject["plan_version_id"],
    }
    if any(subject.get(key) != value for key, value in expected.items()):
        raise ValueError(
            "plan acceptance subject is not the current accepted authorization context"
        )
    stored_fingerprint = _sha256_digest(
        subject.get("plan_sha256"), "plan acceptance plan_sha256"
    )
    fingerprint = _json_sha256(subject.get("subject_plan"), "accepted plan")
    if fingerprint != stored_fingerprint:
        raise ValueError("plan acceptance subject integrity failed")
    return subject, fingerprint


def _json_sha256(value: object, field: str) -> str:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    validate_private_payload(value)
    return hashlib.sha256(compact_json(value).encode("utf-8")).hexdigest()


def _subject_kind(value: object) -> str:
    kind = required_text(value, "authorization subject_kind", 80)
    if kind not in AUTHORIZATION_SUBJECT_KINDS:
        raise ValueError("unsupported investigation authorization subject kind")
    return kind


__all__ = ["InvestigationAuthorizationDerivationStoreMixin"]
