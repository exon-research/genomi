"""One-time, session-local approval receipts for private context previews."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field

from .models import JsonObject, compact_json
from .service_errors import LabError
from .store import GenomiLabStore


@dataclass(slots=True)
class ContextCandidateReceiptIssuer:
    store: GenomiLabStore
    session_id: str
    _secret: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    _receipts: dict[str, JsonObject] = field(default_factory=dict)

    def clear(self) -> None:
        self._receipts.clear()

    def discard_investigation(self, investigation_id: str) -> None:
        self._receipts = {
            token: receipt
            for token, receipt in self._receipts.items()
            if receipt.get("investigation_id") != investigation_id
        }

    def issue(self, candidate: JsonObject, *, action: str) -> JsonObject:
        if action not in {"initial", "renewal", "refresh"}:
            raise ValueError("invalid context candidate action")
        receipt_id = f"context-candidate-{secrets.token_urlsafe(24)}"
        receipt = {
            "receipt_id": receipt_id,
            "workspace_session_id": self.session_id,
            "user_id": candidate["user_id"],
            "investigation_id": candidate["investigation_id"],
            "candidate_sha256": candidate["candidate_sha256"],
            "action": action,
            "base_patient_molecular_snapshot_id": str(
                self.store.get_investigation(
                    str(candidate["investigation_id"])
                ).get("patient_molecular_snapshot_id")
                or ""
            ),
        }
        signature = self._signature(receipt)
        token = f"{receipt_id}.{signature}"
        self._receipts[token] = receipt
        return {**candidate, "candidate_receipt": token}

    def validate(
        self,
        *,
        investigation_id: str,
        user_id: str,
        payload: JsonObject,
        current_context: JsonObject,
    ) -> JsonObject:
        token = payload.get("candidate_receipt")
        if not isinstance(token, str) or not token:
            raise LabError(
                "invalid_context_approval",
                "Preview this private context again before approving it.",
                http_status=409,
            )
        receipt = self._receipts.get(token)
        if not isinstance(receipt, dict):
            raise LabError(
                "invalid_context_approval",
                "This private-context preview is missing, expired, or already used.",
                http_status=409,
            )
        try:
            receipt_id, supplied_signature = token.rsplit(".", 1)
        except ValueError as exc:
            raise LabError(
                "invalid_context_approval",
                "This private-context preview receipt is invalid.",
                http_status=409,
            ) from exc
        investigation = self.store.get_investigation(investigation_id)
        pinned_snapshot_id = str(
            investigation.get("patient_molecular_snapshot_id") or ""
        )
        expected_action = (
            "refresh"
            if payload.get("refresh") is True
            else "renewal"
            if pinned_snapshot_id
            else "initial"
        )
        expected = {
            "receipt_id": receipt_id,
            "workspace_session_id": self.session_id,
            "user_id": user_id,
            "investigation_id": investigation_id,
            "candidate_sha256": payload.get("candidate_sha256"),
            "action": expected_action,
            "base_patient_molecular_snapshot_id": pinned_snapshot_id,
        }
        if (
            not hmac.compare_digest(supplied_signature, self._signature(receipt))
            or receipt != expected
        ):
            raise LabError(
                "invalid_context_approval",
                "The approved private context does not match its server-issued preview.",
                http_status=409,
            )
        if expected_action in {"initial", "refresh"}:
            self._validate_current_selection(
                user_id=user_id,
                payload=payload,
                current_context=current_context,
            )
        else:
            pinned = self.store.get_profile_snapshot(pinned_snapshot_id)
            if sorted(payload.get("observation_revision_ids") or []) != sorted(
                pinned.get("observation_revision_ids") or []
            ):
                raise LabError(
                    "invalid_context_approval",
                    "Renewal must preserve the exact pinned profile selection.",
                    http_status=409,
                )
        return receipt

    def _validate_current_selection(
        self,
        *,
        user_id: str,
        payload: JsonObject,
        current_context: JsonObject,
    ) -> None:
        current_revision_ids = {
            str(row["observation_revision_id"])
            for row in self.store.list_profile_observations(
                user_id, current_only=True
            )
        }
        if any(
            revision_id not in current_revision_ids
            for revision_id in payload.get("observation_revision_ids") or []
        ):
            raise LabError(
                "invalid_context_approval",
                (
                    "The selected profile changed after preview. Review the current "
                    "observations again."
                ),
                http_status=409,
            )
        current_active = current_context.get("active_genome_index")
        current_agi_pair = (
            str(current_context.get("active_agi_id") or "") or None,
            (
                str(current_active.get("agi_snapshot_id") or "") or None
                if isinstance(current_active, dict)
                else None
            ),
        )
        approved_agi_pair = (
            str(payload.get("agi_id") or "") or None,
            str(payload.get("agi_snapshot_id") or "") or None,
        )
        if approved_agi_pair not in {(None, None), current_agi_pair}:
            raise LabError(
                "invalid_context_approval",
                (
                    "The current Genomi genome changed after preview. Review the "
                    "private context again."
                ),
                http_status=409,
            )

    def _signature(self, receipt: JsonObject) -> str:
        return hmac.new(
            self._secret,
            compact_json(receipt).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
