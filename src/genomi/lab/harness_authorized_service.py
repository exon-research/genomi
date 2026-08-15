"""Internal harness dispatch derived from an investigation authorization."""

from __future__ import annotations

from typing import Any

from .harness import HarnessArtifactKind, HarnessOperation
from .models import JsonObject, compact_json, stable_id


_INVESTIGATION_HARNESS_AUTHORITY = object()


def authorized_harness_command_id(
    authorization_receipt_id: str,
    *,
    intent: str,
    operation: HarnessOperation,
    artifact_kind: HarnessArtifactKind,
    command_key: object,
) -> str:
    return stable_id(
        "genomilab-command",
        authorization_receipt_id,
        intent,
        operation.value,
        artifact_kind.value,
        compact_json(command_key),
    )


class AuthorizedHarnessApplicationMixin:
    """Build exact harness receipts without presenting routine work as a new click."""

    def _execute_authorized_harness_command(
        self: Any,
        investigation_id: str,
        *,
        intent: str,
        operation: HarnessOperation,
        artifact_kind: HarnessArtifactKind,
        instruction: str = "",
        reason: str = "",
        command_key: object,
        _authority: object,
    ) -> JsonObject:
        if _authority is not _INVESTIGATION_HARNESS_AUTHORITY:
            raise PermissionError("investigation harness authority is application-owned")
        authorization = self._require_investigation_authorization(
            investigation_id, intent=intent
        )
        authorization_id = str(authorization["authorization_receipt_id"])
        command_id = authorized_harness_command_id(
            authorization_id,
            intent=intent,
            operation=operation,
            artifact_kind=artifact_kind,
            command_key=command_key,
        )
        existing = self.store.harness_command(command_id)
        receipt_id = (
            str(existing.get("disclosure_receipt_id") or "")
            if isinstance(existing, dict)
            else ""
        )
        if receipt_id:
            from .authorization_store import (
                AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
            )

            self.store.derive_investigation_authorization_subject(
                authorization_id,
                subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
                subject_id=receipt_id,
            )
            linked = self.store.require_investigation_authorization_subject(
                authorization_id,
                subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
                subject_id=receipt_id,
            )
            receipt = linked["subject"]
            disclosed = receipt["payload"]
            request = {
                "approved": True,
                "payload_sha256": receipt["payload_sha256"],
                "command_id": command_id,
                "expected_revision": disclosed["command_context"][
                    "expected_revision"
                ],
                "instruction": disclosed.get("instruction"),
                "artifact_kind": disclosed.get("artifact_kind"),
                "reason": disclosed.get("reason"),
            }
            result = self._execute_harness_command(
                investigation_id,
                request,
                operation=operation,
                artifact_kind=artifact_kind,
                authorization_receipt_id=authorization_id,
            )
            self._continue_authorized_harness_result(
                investigation_id,
                intent=intent,
                committed=result,
                receipt_id=receipt_id,
            )
            return result
        # A process may stop after durably reserving the command ID but before
        # attaching its disclosure receipt. Rebuild the same candidate and let
        # the lower command boundary repair that pre-dispatch checkpoint. It
        # will reject the replay if any payload-relevant context has changed.
        candidate = self.harness_disclosure_candidate(
            investigation_id,
            operation=operation.value,
            instruction=instruction or None,
            artifact_kind=artifact_kind.value,
            reason=reason or None,
            command_id=command_id,
        )
        disclosed = candidate["payload"]
        request = {
            "approved": True,
            "payload_sha256": candidate["payload_sha256"],
            "command_id": command_id,
            "expected_revision": disclosed["command_context"]["expected_revision"],
            "instruction": disclosed.get("instruction"),
            "artifact_kind": disclosed.get("artifact_kind"),
            "reason": disclosed.get("reason"),
        }
        result = self._execute_harness_command(
            investigation_id,
            request,
            operation=operation,
            artifact_kind=artifact_kind,
            authorization_receipt_id=authorization_id,
        )
        receipt_id = str(result.get("disclosure_receipt_id") or "")
        if receipt_id:
            self._continue_authorized_harness_result(
                investigation_id,
                intent=intent,
                committed=result,
                receipt_id=receipt_id,
            )
        return result


__all__ = [
    "AuthorizedHarnessApplicationMixin",
    "_INVESTIGATION_HARNESS_AUTHORITY",
    "authorized_harness_command_id",
]
