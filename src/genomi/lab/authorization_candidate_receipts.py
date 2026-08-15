"""One-time signed candidates for a GenomiLab investigation authorization."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field

from .models import JsonObject, compact_json
from .service_errors import LabError


def authorization_candidate_payload_sha256(payload: JsonObject) -> str:
    """Hash the exact reviewable fields while excluding transport-only approval."""

    reviewed = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "approved",
            "status",
            "requires_explicit_approval",
            "user_id",
            "investigation_id",
            "authorization_candidate_receipt",
        }
    }
    return hashlib.sha256(compact_json(reviewed).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class AuthorizationCandidateReceiptIssuer:
    """Issue session-local bearer receipts over one combined start sheet."""

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

    def issue(
        self,
        candidate: JsonObject,
        *,
        user_id: str,
        investigation_id: str,
    ) -> JsonObject:
        receipt_id = f"authorization-candidate-{secrets.token_urlsafe(24)}"
        receipt = {
            "receipt_id": receipt_id,
            "workspace_session_id": self.session_id,
            "user_id": user_id,
            "investigation_id": investigation_id,
            "profile_candidate_sha256": candidate.get("candidate_sha256"),
            "authorization_scope_sha256": candidate.get(
                "authorization_scope_sha256"
            ),
            "approval_payload_sha256": authorization_candidate_payload_sha256(
                candidate
            ),
        }
        signature = self._signature(receipt)
        token = f"{receipt_id}.{signature}"
        self._receipts[token] = receipt
        return {**candidate, "authorization_candidate_receipt": token}

    def validate(
        self,
        *,
        investigation_id: str,
        user_id: str,
        payload: JsonObject,
    ) -> JsonObject:
        token = payload.get("authorization_candidate_receipt")
        if not isinstance(token, str) or not token:
            raise LabError(
                "invalid_investigation_authorization",
                "Review the investigation access summary again before starting.",
                http_status=409,
            )
        receipt = self._receipts.get(token)
        if not isinstance(receipt, dict):
            raise LabError(
                "invalid_investigation_authorization",
                "This investigation access summary is missing or expired.",
                http_status=409,
            )
        try:
            receipt_id, supplied_signature = token.rsplit(".", 1)
        except ValueError as exc:
            raise LabError(
                "invalid_investigation_authorization",
                "This investigation authorization receipt is invalid.",
                http_status=409,
            ) from exc
        expected = {
            "receipt_id": receipt_id,
            "workspace_session_id": self.session_id,
            "user_id": user_id,
            "investigation_id": investigation_id,
            "profile_candidate_sha256": payload.get("candidate_sha256"),
            "authorization_scope_sha256": payload.get(
                "authorization_scope_sha256"
            ),
            "approval_payload_sha256": authorization_candidate_payload_sha256(
                payload
            ),
        }
        if (
            not hmac.compare_digest(supplied_signature, self._signature(receipt))
            or receipt != expected
        ):
            raise LabError(
                "invalid_investigation_authorization",
                "The investigation access summary changed after it was reviewed.",
                http_status=409,
            )
        return dict(receipt)

    def _signature(self, receipt: JsonObject) -> str:
        return hmac.new(
            self._secret,
            compact_json(receipt).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


__all__ = [
    "AuthorizationCandidateReceiptIssuer",
    "authorization_candidate_payload_sha256",
]
