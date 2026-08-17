"""Durable authorization receipts for one GenomiLab investigation session.

The parent receipt records the patient's approved local research boundary. Exact
outbound disclosures and plan acceptances remain owned by their canonical
tables; a separate immutable derivation row records when one of those subjects
was authorized under the parent boundary.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, ContextManager, Protocol

from .models import (
    JsonObject,
    compact_json,
    optional_text,
    required_text,
    row_dict,
    utc_now,
    validate_private_payload,
)


AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE = "outbound_disclosure"
AUTHORIZATION_SUBJECT_PLAN_ACCEPTANCE = "plan_acceptance"
AUTHORIZATION_SUBJECT_KINDS = frozenset(
    {
        AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
        AUTHORIZATION_SUBJECT_PLAN_ACCEPTANCE,
    }
)
INVESTIGATION_AUTHORIZATION_INTENTS = frozenset(
    {"plan", "execute_accepted_plan", "user_followup", "resume"}
)


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def _require_workspace(self, user_id: str) -> None: ...


def canonical_investigation_authorization_scope(value: object) -> JsonObject:
    """Validate and canonicalize the initial local research boundary."""

    if not isinstance(value, dict) or set(value) != {"agent_session", "providers"}:
        raise ValueError(
            "authorization_scope must contain exactly agent_session and providers"
        )
    agent_session = value.get("agent_session")
    if not isinstance(agent_session, dict) or set(agent_session) != {
        "recipient_id",
        "destination",
        "allowed_intents",
    }:
        raise ValueError(
            "authorization_scope.agent_session must contain exactly recipient_id, "
            "destination, and allowed_intents"
        )
    raw_intents = agent_session.get("allowed_intents")
    if not isinstance(raw_intents, list) or not raw_intents:
        raise ValueError("authorization_scope agent-session intents must be non-empty")
    if any(not isinstance(intent, str) or not intent.strip() for intent in raw_intents):
        raise ValueError("authorization_scope agent-session intents must be strings")
    intents = sorted({intent.strip() for intent in raw_intents})
    if len(intents) != len(raw_intents):
        raise ValueError("authorization_scope agent-session intents must be unique")
    unknown = set(intents) - INVESTIGATION_AUTHORIZATION_INTENTS
    if unknown:
        raise ValueError(
            "unsupported investigation authorization intents: "
            + ", ".join(sorted(unknown))
        )
    if set(intents) != INVESTIGATION_AUTHORIZATION_INTENTS:
        raise ValueError(
            "the initial investigation authorization must include exactly the "
            "routine investigation intents"
        )
    providers = value.get("providers")
    if providers != []:
        raise ValueError(
            "provider authorization is not part of the initial investigation scope"
        )
    scope = {
        "agent_session": {
            "recipient_id": required_text(
                agent_session.get("recipient_id"), "agent-session recipient_id", 200
            ),
            "destination": required_text(
                agent_session.get("destination"), "agent-session destination", 300
            ),
            "allowed_intents": intents,
        },
        "providers": [],
    }
    validate_private_payload(scope)
    return scope


def investigation_authorization_scope_sha256(scope: object) -> str:
    """Return the canonical digest shared by candidates and durable receipts."""

    canonical = canonical_investigation_authorization_scope(scope)
    return hashlib.sha256(compact_json(canonical).encode("utf-8")).hexdigest()


class InvestigationAuthorizationStoreMixin:
    """Persistence and exact subject linkage for investigation authorization."""

    def create_investigation_authorization(
        self: _StoreContract,
        user_id: str,
        *,
        workspace_session_id: object,
        investigation_id: object,
        patient_molecular_snapshot_id: object,
        consent_receipt_id: object,
        authorization_scope: object,
        candidate_receipt_sha256: object,
        supersedes_authorization_receipt_id: object = None,
        approved: object = False,
    ) -> JsonObject:
        """Create one immutable receipt or return its exact idempotent replay."""

        if approved is not True:
            raise ValueError(
                "explicit approval is required for investigation authorization"
            )
        user = required_text(user_id, "user_id", 300)
        session = required_text(
            workspace_session_id, "workspace_session_id", 200
        )
        investigation = required_text(
            investigation_id, "investigation_id", 200
        )
        snapshot = required_text(
            patient_molecular_snapshot_id,
            "patient_molecular_snapshot_id",
            200,
        )
        consent = required_text(consent_receipt_id, "consent_receipt_id", 200)
        scope = canonical_investigation_authorization_scope(authorization_scope)
        scope_sha256 = investigation_authorization_scope_sha256(scope)
        candidate_sha256 = _sha256_digest(
            candidate_receipt_sha256, "candidate_receipt_sha256"
        )
        supersedes = optional_text(
            supersedes_authorization_receipt_id,
            "supersedes_authorization_receipt_id",
            200,
        )
        self._require_workspace(user)

        with self._connect() as connection:
            existing_row = connection.execute(
                "SELECT * FROM investigation_authorization_receipts "
                "WHERE candidate_receipt_sha256 = ?",
                (candidate_sha256,),
            ).fetchone()
            if existing_row is not None:
                existing = row_dict(existing_row)
                expected = {
                    "workspace_session_id": session,
                    "user_id": user,
                    "investigation_id": investigation,
                    "patient_molecular_snapshot_id": snapshot,
                    "consent_receipt_id": consent,
                    "authorization_scope": scope,
                    "authorization_scope_sha256": scope_sha256,
                    "candidate_receipt_sha256": candidate_sha256,
                }
                if supersedes is not None:
                    expected["supersedes_authorization_receipt_id"] = supersedes
                if any(existing.get(key) != value for key, value in expected.items()):
                    raise ValueError(
                        "candidate receipt digest is already bound to different authorization"
                    )
                return existing

            self._require_context_binding(
                connection,
                workspace_session_id=session,
                user_id=user,
                investigation_id=investigation,
                patient_molecular_snapshot_id=snapshot,
                consent_receipt_id=consent,
            )
            current_row = connection.execute(
                "SELECT * FROM investigation_authorization_receipts "
                "WHERE investigation_id = ? AND revoked_at IS NULL",
                (investigation,),
            ).fetchone()
            current = row_dict(current_row) if current_row is not None else None
            if current is not None:
                current_id = str(current["authorization_receipt_id"])
                if supersedes is None and any(
                    current.get(key) != value
                    for key, value in {
                        "workspace_session_id": session,
                        "user_id": user,
                        "investigation_id": investigation,
                        "patient_molecular_snapshot_id": snapshot,
                        "consent_receipt_id": consent,
                    }.items()
                ):
                    # A newly approved candidate may replace authority stranded
                    # by an unclean session exit or a renewed profile consent.
                    # The prior receipt remains immutable and the inferred link
                    # is recorded on the replacement.
                    supersedes = current_id
                elif supersedes != current_id:
                    raise ValueError(
                        "the current investigation authorization must be explicitly superseded"
                    )
            if supersedes is not None:
                prior_row = connection.execute(
                    "SELECT * FROM investigation_authorization_receipts "
                    "WHERE authorization_receipt_id = ?",
                    (supersedes,),
                ).fetchone()
                if prior_row is None:
                    raise ValueError("superseded investigation authorization not found")
                prior = row_dict(prior_row)
                if prior.get("user_id") != user or prior.get(
                    "investigation_id"
                ) != investigation:
                    raise ValueError(
                        "superseded authorization belongs to different investigation context"
                    )

            approved_at = utc_now()
            if current is not None:
                connection.execute(
                    "UPDATE investigation_authorization_receipts SET revoked_at = ? "
                    "WHERE authorization_receipt_id = ? AND revoked_at IS NULL",
                    (approved_at, current["authorization_receipt_id"]),
                )
            authorization_receipt_id = f"investigation-authorization-{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO investigation_authorization_receipts(
                    authorization_receipt_id, workspace_session_id, user_id,
                    investigation_id, patient_molecular_snapshot_id,
                    consent_receipt_id, authorization_scope_json,
                    authorization_scope_sha256, candidate_receipt_sha256,
                    approved_at, supersedes_authorization_receipt_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    authorization_receipt_id,
                    session,
                    user,
                    investigation,
                    snapshot,
                    consent,
                    compact_json(scope),
                    scope_sha256,
                    candidate_sha256,
                    approved_at,
                    supersedes,
                ),
            )
            row = connection.execute(
                "SELECT * FROM investigation_authorization_receipts "
                "WHERE authorization_receipt_id = ?",
                (authorization_receipt_id,),
            ).fetchone()
        return row_dict(row)

    def find_investigation_authorization(
        self: _StoreContract,
        *,
        workspace_session_id: object,
        user_id: object,
        investigation_id: object,
        candidate_receipt_sha256: object,
    ) -> JsonObject | None:
        session = required_text(
            workspace_session_id, "workspace_session_id", 200
        )
        user = required_text(user_id, "user_id", 300)
        investigation = required_text(
            investigation_id, "investigation_id", 200
        )
        candidate_sha256 = _sha256_digest(
            candidate_receipt_sha256, "candidate_receipt_sha256"
        )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM investigation_authorization_receipts "
                "WHERE workspace_session_id = ? AND user_id = ? "
                "AND investigation_id = ? AND candidate_receipt_sha256 = ?",
                (session, user, investigation, candidate_sha256),
            ).fetchone()
        return row_dict(row) if row is not None else None

    def current_investigation_authorization(
        self: _StoreContract,
        *,
        workspace_session_id: object,
        user_id: object,
        investigation_id: object,
    ) -> JsonObject | None:
        session = required_text(
            workspace_session_id, "workspace_session_id", 200
        )
        user = required_text(user_id, "user_id", 300)
        investigation = required_text(
            investigation_id, "investigation_id", 200
        )
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT authorization.*
                  FROM investigation_authorization_receipts AS authorization
                  JOIN investigations AS investigation
                    ON investigation.investigation_id = authorization.investigation_id
                  JOIN consent_receipts AS consent
                    ON consent.consent_receipt_id = authorization.consent_receipt_id
                 WHERE authorization.workspace_session_id = ?
                   AND authorization.user_id = ?
                   AND authorization.investigation_id = ?
                   AND authorization.revoked_at IS NULL
                   AND consent.revoked_at IS NULL
                   AND investigation.user_id = authorization.user_id
                   AND investigation.patient_molecular_snapshot_id =
                       authorization.patient_molecular_snapshot_id
                   AND investigation.active_consent_receipt_id =
                       authorization.consent_receipt_id
                """,
                (session, user, investigation),
            ).fetchone()
            if row is None:
                return None
            receipt = row_dict(row)
            self._require_active_authorization(connection, receipt)
            return receipt

    def require_investigation_authorization(
        self: _StoreContract,
        authorization_receipt_id: object,
        *,
        workspace_session_id: object,
        user_id: object,
        investigation_id: object,
        patient_molecular_snapshot_id: object,
        consent_receipt_id: object,
        authorization_scope: object = None,
    ) -> JsonObject:
        receipt_id = required_text(
            authorization_receipt_id, "authorization_receipt_id", 200
        )
        expected = {
            "workspace_session_id": required_text(
                workspace_session_id, "workspace_session_id", 200
            ),
            "user_id": required_text(user_id, "user_id", 300),
            "investigation_id": required_text(
                investigation_id, "investigation_id", 200
            ),
            "patient_molecular_snapshot_id": required_text(
                patient_molecular_snapshot_id,
                "patient_molecular_snapshot_id",
                200,
            ),
            "consent_receipt_id": required_text(
                consent_receipt_id, "consent_receipt_id", 200
            ),
        }
        expected_scope = (
            canonical_investigation_authorization_scope(authorization_scope)
            if authorization_scope is not None
            else None
        )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM investigation_authorization_receipts "
                "WHERE authorization_receipt_id = ?",
                (receipt_id,),
            ).fetchone()
            if row is None:
                raise ValueError("investigation authorization receipt not found")
            receipt = row_dict(row)
            if any(receipt.get(key) != value for key, value in expected.items()):
                raise ValueError(
                    "investigation authorization does not match this context"
                )
            if expected_scope is not None and receipt.get(
                "authorization_scope"
            ) != expected_scope:
                raise ValueError(
                    "investigation authorization does not match this scope"
                )
            self._require_active_authorization(connection, receipt)
            return receipt

    def revoke_investigation_authorization(
        self: _StoreContract, authorization_receipt_id: object
    ) -> bool:
        receipt_id = required_text(
            authorization_receipt_id, "authorization_receipt_id", 200
        )
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE investigation_authorization_receipts SET revoked_at = ? "
                "WHERE authorization_receipt_id = ? AND revoked_at IS NULL",
                (utc_now(), receipt_id),
            )
        return bool(cursor.rowcount)

    def revoke_session_investigation_authorizations(
        self: _StoreContract, workspace_session_id: object
    ) -> int:
        session = required_text(
            workspace_session_id, "workspace_session_id", 200
        )
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE investigation_authorization_receipts SET revoked_at = ? "
                "WHERE workspace_session_id = ? AND revoked_at IS NULL",
                (utc_now(), session),
            )
        return int(cursor.rowcount)

    def revoke_investigation_authorizations(
        self: _StoreContract, investigation_id: object
    ) -> int:
        investigation = required_text(
            investigation_id, "investigation_id", 200
        )
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE investigation_authorization_receipts SET revoked_at = ? "
                "WHERE investigation_id = ? AND revoked_at IS NULL",
                (utc_now(), investigation),
            )
        return int(cursor.rowcount)

    @staticmethod
    def _require_context_binding(
        connection: Any,
        *,
        workspace_session_id: str,
        user_id: str,
        investigation_id: str,
        patient_molecular_snapshot_id: str,
        consent_receipt_id: str,
    ) -> None:
        investigation = connection.execute(
            "SELECT user_id, patient_molecular_snapshot_id, "
            "active_consent_receipt_id FROM investigations "
            "WHERE investigation_id = ?",
            (investigation_id,),
        ).fetchone()
        if (
            investigation is None
            or str(investigation["user_id"]) != user_id
            or str(investigation["patient_molecular_snapshot_id"] or "")
            != patient_molecular_snapshot_id
            or str(investigation["active_consent_receipt_id"] or "")
            != consent_receipt_id
        ):
            raise ValueError(
                "investigation authorization context is not current"
            )
        snapshot = connection.execute(
            "SELECT user_id, investigation_id FROM profile_snapshots "
            "WHERE patient_molecular_snapshot_id = ?",
            (patient_molecular_snapshot_id,),
        ).fetchone()
        if (
            snapshot is None
            or str(snapshot["user_id"]) != user_id
            or str(snapshot["investigation_id"]) != investigation_id
        ):
            raise ValueError(
                "investigation authorization snapshot does not match"
            )
        consent = connection.execute(
            "SELECT * FROM consent_receipts WHERE consent_receipt_id = ?",
            (consent_receipt_id,),
        ).fetchone()
        if (
            consent is None
            or consent["revoked_at"] is not None
            or str(consent["workspace_session_id"]) != workspace_session_id
            or str(consent["user_id"]) != user_id
            or str(consent["investigation_id"]) != investigation_id
            or str(consent["patient_molecular_snapshot_id"] or "")
            != patient_molecular_snapshot_id
        ):
            raise ValueError(
                "investigation authorization consent does not match"
            )

    def _require_active_authorization(
        self: _StoreContract, connection: Any, receipt: JsonObject
    ) -> None:
        if receipt.get("revoked_at") is not None:
            raise ValueError("investigation authorization is revoked")
        self._require_scope_integrity(receipt)
        self._require_context_binding(
            connection,
            workspace_session_id=str(receipt["workspace_session_id"]),
            user_id=str(receipt["user_id"]),
            investigation_id=str(receipt["investigation_id"]),
            patient_molecular_snapshot_id=str(
                receipt["patient_molecular_snapshot_id"]
            ),
            consent_receipt_id=str(receipt["consent_receipt_id"]),
        )

    @staticmethod
    def _require_scope_integrity(receipt: JsonObject) -> None:
        scope = receipt.get("authorization_scope")
        if investigation_authorization_scope_sha256(scope) != receipt.get(
            "authorization_scope_sha256"
        ):
            raise ValueError("investigation authorization scope integrity failed")

def _sha256_digest(value: object, field: str) -> str:
    digest = required_text(value, field, 64).lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{field} must be a SHA-256 hex digest")
    return digest


__all__ = [
    "AUTHORIZATION_SUBJECT_KINDS",
    "AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE",
    "AUTHORIZATION_SUBJECT_PLAN_ACCEPTANCE",
    "INVESTIGATION_AUTHORIZATION_INTENTS",
    "InvestigationAuthorizationStoreMixin",
    "canonical_investigation_authorization_scope",
    "investigation_authorization_scope_sha256",
]
