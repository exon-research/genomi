"""Exact outbound-disclosure receipts for harness and provider boundaries."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, ContextManager, Protocol

from .models import (
    QUESTION_MAX,
    JsonObject,
    compact_json,
    required_text,
    row_dict,
    utc_now,
    validate_private_payload,
)


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def _require_workspace(self, user_id: str) -> None: ...


def disclosure_payload_sha256(payload: JsonObject) -> str:
    validate_private_payload(payload)
    return hashlib.sha256(compact_json(payload).encode("utf-8")).hexdigest()


class ApprovalStoreMixin:
    """Durable, session-scoped and payload-exact outbound approvals."""

    def create_outbound_disclosure_receipt(
        self: _StoreContract,
        user_id: str,
        *,
        workspace_session_id: object,
        investigation_id: object,
        recipient_kind: object,
        recipient_id: object,
        purpose: object,
        destination: object,
        data_categories: object,
        payload: JsonObject,
        policy_versions: object = None,
        approved: object = False,
    ) -> JsonObject:
        self._require_workspace(user_id)
        if approved is not True:
            raise ValueError("explicit approval is required for outbound disclosure")
        if not isinstance(data_categories, list) or not data_categories:
            raise ValueError("data_categories must be a non-empty array")
        categories = sorted(
            {required_text(value, "data_category", 120) for value in data_categories}
        )
        if policy_versions is not None and not isinstance(policy_versions, dict):
            raise ValueError("policy_versions must be an object")
        validate_private_payload(policy_versions)
        payload_hash = disclosure_payload_sha256(payload)
        receipt_id = f"disclosure-{uuid.uuid4().hex}"
        with self._connect() as connection:
            target = connection.execute(
                "SELECT user_id FROM investigations WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            if target is None or str(target["user_id"]) != user_id:
                raise ValueError("investigation_id must belong to the current user")
            connection.execute(
                """
                INSERT INTO outbound_disclosure_receipts(
                    disclosure_receipt_id, workspace_session_id, user_id,
                    investigation_id, recipient_kind, recipient_id, purpose,
                    destination, data_categories_json, payload_json,
                    payload_sha256, policy_versions_json, approved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    required_text(workspace_session_id, "workspace_session_id", 200),
                    user_id,
                    required_text(investigation_id, "investigation_id", 200),
                    required_text(recipient_kind, "recipient_kind", 80),
                    required_text(recipient_id, "recipient_id", 200),
                    required_text(purpose, "purpose", QUESTION_MAX),
                    required_text(destination, "destination", 300),
                    compact_json(categories),
                    compact_json(payload),
                    payload_hash,
                    compact_json(policy_versions)
                    if policy_versions is not None
                    else None,
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM outbound_disclosure_receipts "
                "WHERE disclosure_receipt_id = ?",
                (receipt_id,),
            ).fetchone()
        return row_dict(row)

    def require_outbound_disclosure(
        self: _StoreContract,
        disclosure_receipt_id: str,
        *,
        workspace_session_id: str,
        user_id: str,
        investigation_id: str,
        recipient_kind: str,
        recipient_id: str,
        purpose: str,
        destination: str,
        data_categories: list[str],
        payload: JsonObject,
        policy_versions: JsonObject | None,
    ) -> JsonObject:
        categories = sorted(
            {required_text(value, "data_category", 120) for value in data_categories}
        )
        if not categories:
            raise ValueError("data_categories must be a non-empty array")
        if policy_versions is not None and not isinstance(policy_versions, dict):
            raise ValueError("policy_versions must be an object")
        validate_private_payload(policy_versions)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM outbound_disclosure_receipts "
                "WHERE disclosure_receipt_id = ?",
                (disclosure_receipt_id,),
            ).fetchone()
        if row is None:
            raise ValueError("outbound disclosure receipt not found")
        receipt = row_dict(row)
        expected = {
            "workspace_session_id": workspace_session_id,
            "user_id": user_id,
            "investigation_id": investigation_id,
            "recipient_kind": recipient_kind,
            "recipient_id": recipient_id,
            "purpose": required_text(purpose, "purpose", QUESTION_MAX),
            "destination": required_text(destination, "destination", 300),
            "data_categories": categories,
            "payload_sha256": disclosure_payload_sha256(payload),
            "policy_versions": policy_versions,
        }
        if receipt.get("revoked_at") or any(
            receipt.get(key) != value for key, value in expected.items()
        ):
            raise ValueError("outbound disclosure approval does not match this request")
        return receipt

    def outbound_disclosure_receipt(
        self: _StoreContract, disclosure_receipt_id: str
    ) -> JsonObject:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM outbound_disclosure_receipts "
                "WHERE disclosure_receipt_id = ?",
                (disclosure_receipt_id,),
            ).fetchone()
        if row is None:
            raise KeyError(disclosure_receipt_id)
        return row_dict(row)

    def active_outbound_disclosure_receipt_ids(
        self: _StoreContract,
        *,
        workspace_session_id: object,
        user_id: object,
        investigation_id: object,
        recipient_kind: object,
        recipient_id: object,
        payload_sha256: object,
    ) -> list[str]:
        """Find active receipts matching one exact disclosure identity."""

        session = required_text(
            workspace_session_id, "workspace_session_id", 200
        )
        user = required_text(user_id, "user_id", 300)
        investigation = required_text(
            investigation_id, "investigation_id", 200
        )
        kind = required_text(recipient_kind, "recipient_kind", 80)
        recipient = required_text(recipient_id, "recipient_id", 200)
        payload_hash = required_text(payload_sha256, "payload_sha256", 128)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT disclosure_receipt_id FROM outbound_disclosure_receipts "
                "WHERE workspace_session_id = ? AND user_id = ? "
                "AND investigation_id = ? AND recipient_kind = ? "
                "AND recipient_id = ? AND payload_sha256 = ? "
                "AND revoked_at IS NULL ORDER BY approved_at DESC",
                (
                    session,
                    user,
                    investigation,
                    kind,
                    recipient,
                    payload_hash,
                ),
            ).fetchall()
        return [str(row["disclosure_receipt_id"]) for row in rows]

    def revoke_outbound_disclosure(
        self: _StoreContract, disclosure_receipt_id: str
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE outbound_disclosure_receipts SET revoked_at = ? "
                "WHERE disclosure_receipt_id = ? AND revoked_at IS NULL",
                (utc_now(), disclosure_receipt_id),
            )
        return bool(cursor.rowcount)

    def revoke_session_disclosures(
        self: _StoreContract, workspace_session_id: str
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE outbound_disclosure_receipts SET revoked_at = ? "
                "WHERE workspace_session_id = ? AND revoked_at IS NULL",
                (utc_now(), workspace_session_id),
            )
        return int(cursor.rowcount)

    def workspace_activity(
        self: _StoreContract, user_id: str
    ) -> JsonObject:
        """Return a payload-free audit view for the current user's portal."""

        self._require_workspace(user_id)
        with self._connect() as connection:
            consents = connection.execute(
                "SELECT consent_receipt_id, investigation_id, purpose, "
                "patient_molecular_snapshot_id, agi_id, agi_snapshot_id, "
                "approved_at, revoked_at FROM consent_receipts WHERE user_id = ? "
                "ORDER BY approved_at DESC",
                (user_id,),
            ).fetchall()
            disclosures = connection.execute(
                "SELECT disclosure_receipt_id, investigation_id, recipient_kind, "
                "recipient_id, purpose, destination, data_categories_json, "
                "payload_sha256, approved_at, revoked_at "
                "FROM outbound_disclosure_receipts WHERE user_id = ? "
                "ORDER BY approved_at DESC",
                (user_id,),
            ).fetchall()
            plan_acceptances = connection.execute(
                "SELECT plan_acceptance_id, plan_version_id, investigation_id, "
                "plan_sha256, accepted_at FROM plan_acceptances WHERE user_id = ? "
                "ORDER BY accepted_at DESC",
                (user_id,),
            ).fetchall()
        return {
            "context_approvals": [row_dict(row) for row in consents],
            "outbound_disclosures": [row_dict(row) for row in disclosures],
            "plan_acceptances": [row_dict(row) for row in plan_acceptances],
            "payloads_included": False,
        }
