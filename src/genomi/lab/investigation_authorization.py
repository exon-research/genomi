"""One patient authorization for routine GenomiLab investigation work."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable

from .authorization_candidate_receipts import AuthorizationCandidateReceiptIssuer
from .authorization_store import (
    INVESTIGATION_AUTHORIZATION_INTENTS,
    investigation_authorization_scope_sha256,
)
from .models import JsonObject
from .service_errors import LabError
from .store import GenomiLabStore


_AUTHORIZATION_APPROVAL_FIELDS = frozenset(
    {
        "purpose",
        "observation_revision_ids",
        "artifact_ids",
        "specimen_ids",
        "assay_ids",
        "modality_coverage",
        "agi_id",
        "agi_snapshot_id",
        "genomic_scope",
        "candidate_sha256",
        "candidate_receipt",
        "refresh",
        "authorization_scope",
        "authorization_scope_sha256",
        "authorization_candidate_receipt",
        "approved",
    }
)
_AUTHORIZATION_ONLY_FIELDS = frozenset(
    {
        "modality_coverage",
        "authorization_scope",
        "authorization_scope_sha256",
        "authorization_candidate_receipt",
    }
)


@dataclass(slots=True)
class InvestigationAuthorizationApplication:
    """Compile, commit, and revalidate the Research Desk start authorization."""

    store: GenomiLabStore
    session_id: str
    current_context: Callable[[], tuple[JsonObject, str]]
    investigation: Callable[[str], JsonObject]
    context_candidate: Callable[[str, JsonObject], JsonObject]
    approve_context: Callable[..., JsonObject]
    harness_manifest: Callable[[], JsonObject]
    ensure_planning_started: Callable[[str, JsonObject], JsonObject]
    candidate_receipts: AuthorizationCandidateReceiptIssuer

    def candidate(
        self, investigation_id: str, selection: JsonObject
    ) -> JsonObject:
        context_candidate = self.context_candidate(investigation_id, selection)
        investigation = self.investigation(investigation_id)
        _, user_id = self.current_context()
        scope = self._authorization_scope()
        candidate = {
            **context_candidate,
            "status": "authorization_required",
            "requires_explicit_approval": True,
            "authorization_scope": scope,
            "authorization_scope_sha256": (
                investigation_authorization_scope_sha256(scope)
            ),
        }
        if (
            investigation.get("patient_molecular_snapshot_id")
            and selection.get("use_current_agi") is True
        ):
            candidate["refresh"] = True
        return self.candidate_receipts.issue(
            candidate,
            user_id=user_id,
            investigation_id=investigation_id,
        )

    def authorize_and_start(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        self._validate_approval_payload(payload)
        if payload.get("approved") is not True:
            raise LabError(
                "investigation_authorization_required",
                "Authorize the reviewed investigation access before starting.",
                http_status=409,
            )
        _, user_id = self.current_context()
        self.candidate_receipts.validate(
            investigation_id=investigation_id,
            user_id=user_id,
            payload=payload,
        )
        token = str(payload["authorization_candidate_receipt"])
        candidate_receipt_sha256 = hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()
        existing = self.store.find_investigation_authorization(
            workspace_session_id=self.session_id,
            user_id=user_id,
            investigation_id=investigation_id,
            candidate_receipt_sha256=candidate_receipt_sha256,
        )
        if isinstance(existing, dict):
            authorization = self.require_current(
                investigation_id, intent="plan", receipt=existing
            )
            harness = self.ensure_planning_started(
                investigation_id, authorization
            )
            return {
                "status": harness.get("status", "accepted"),
                "authorization": authorization,
                "context": self.store.get_profile_snapshot(
                    str(authorization["patient_molecular_snapshot_id"])
                ),
                "harness": harness,
                "retry_reused": True,
            }

        scope = payload.get("authorization_scope")
        if not isinstance(scope, dict) or (
            investigation_authorization_scope_sha256(scope)
            != payload.get("authorization_scope_sha256")
        ):
            raise LabError(
                "invalid_investigation_authorization",
                "The investigation authorization scope changed after review.",
                http_status=409,
            )
        if scope != self._authorization_scope():
            raise LabError(
                "investigation_authorization_changed",
                "The installed harness changed. Review investigation access again.",
                http_status=409,
            )
        prior = self.store.current_investigation_authorization(
            workspace_session_id=self.session_id,
            user_id=user_id,
            investigation_id=investigation_id,
        )

        def create_authorization(claims: JsonObject) -> JsonObject:
            return self.store.create_investigation_authorization(
                user_id,
                workspace_session_id=self.session_id,
                investigation_id=investigation_id,
                patient_molecular_snapshot_id=claims[
                    "patient_molecular_snapshot_id"
                ],
                consent_receipt_id=claims["consent_receipt_id"],
                authorization_scope=scope,
                candidate_receipt_sha256=candidate_receipt_sha256,
                supersedes_authorization_receipt_id=(
                    prior.get("authorization_receipt_id")
                    if isinstance(prior, dict)
                    else None
                ),
                approved=True,
            )

        context_payload = {
            key: value
            for key, value in payload.items()
            if key not in _AUTHORIZATION_ONLY_FIELDS
        }
        context_result = self.approve_context(
            investigation_id,
            context_payload,
            authorization_before_commit=create_authorization,
        )
        authorization = context_result.get("investigation_authorization")
        if not isinstance(authorization, dict):
            raise RuntimeError(
                "profile context committed without its investigation authorization"
            )
        authorization = self.require_current(
            investigation_id, intent="plan", receipt=authorization
        )
        harness = self.ensure_planning_started(investigation_id, authorization)
        return {
            "status": harness.get("status", "accepted"),
            "authorization": authorization,
            "context": context_result,
            "harness": harness,
            "retry_reused": False,
        }

    def require_current(
        self,
        investigation_id: str,
        *,
        intent: str,
        receipt: JsonObject | None = None,
    ) -> JsonObject:
        if intent not in INVESTIGATION_AUTHORIZATION_INTENTS:
            raise LabError(
                "investigation_authorization_scope_expansion_required",
                "This action is outside the current investigation authorization.",
                http_status=409,
            )
        investigation = self.investigation(investigation_id)
        _, user_id = self.current_context()
        authorization = receipt or self.store.current_investigation_authorization(
            workspace_session_id=self.session_id,
            user_id=user_id,
            investigation_id=investigation_id,
        )
        if not isinstance(authorization, dict):
            raise LabError(
                "investigation_authorization_required",
                "Review and authorize this investigation before continuing.",
                http_status=409,
            )
        scope = self._authorization_scope()
        try:
            required = self.store.require_investigation_authorization(
                authorization["authorization_receipt_id"],
                workspace_session_id=self.session_id,
                user_id=user_id,
                investigation_id=investigation_id,
                patient_molecular_snapshot_id=investigation.get(
                    "patient_molecular_snapshot_id"
                ),
                consent_receipt_id=investigation.get("active_consent_receipt_id"),
                authorization_scope=scope,
            )
        except (KeyError, ValueError) as exc:
            raise LabError(
                "investigation_authorization_expired",
                "The investigation access changed. Review and authorize it again.",
                http_status=409,
            ) from exc
        allowed = (
            (required.get("authorization_scope") or {})
            .get("harness", {})
            .get("allowed_intents", [])
        )
        if intent not in allowed:
            raise LabError(
                "investigation_authorization_scope_expansion_required",
                "This action is outside the current investigation authorization.",
                http_status=409,
            )
        return required

    def _authorization_scope(self) -> JsonObject:
        manifest = self.harness_manifest()
        recipient_id = str(manifest.get("adapter_id") or "").strip()
        destination = str(manifest.get("execution_location") or "").strip()
        if not recipient_id or not destination:
            raise LabError(
                "harness_unavailable",
                "The installed agent harness is not available.",
                http_status=409,
            )
        return {
            "harness": {
                "recipient_id": recipient_id,
                "destination": destination,
                "allowed_intents": sorted(INVESTIGATION_AUTHORIZATION_INTENTS),
            },
            "providers": [],
        }

    @staticmethod
    def _validate_approval_payload(payload: JsonObject) -> None:
        unexpected = set(payload) - _AUTHORIZATION_APPROVAL_FIELDS
        if unexpected:
            raise LabError(
                "invalid_investigation_authorization",
                "Investigation authorization contains unsupported fields.",
            )


__all__ = ["InvestigationAuthorizationApplication"]
