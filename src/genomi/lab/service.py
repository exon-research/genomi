"""GenomiLab application boundary for the current Genomi user."""

from __future__ import annotations

import secrets
import threading
from typing import Callable

from ..operations import OperationError, call_operation
from .agi_authority import (
    AgiAuthorizationHandle,
    InvestigationAgiAuthorizationError,
    execution_context_for_investigation_authorization,
    revoke_investigation_agi_authorization,
    revoke_investigation_agi_authorizations_for_session,
)
from .models import JsonObject
from .context_candidate_receipts import ContextCandidateReceiptIssuer
from .evidence_service import EvidenceApplicationMixin
from .harness import HarnessAdapter, InstalledCodexAppServerAdapter
from .harness_service import HarnessApplicationMixin
from .harness_tool_boundary import HarnessToolBoundary
from .investigation_capabilities import (
    InvestigationCapabilityMixin,
    _HARNESS_CAPABILITY_EXECUTION_AUTHORITY,
)
from .portal_context import PortalContextApplicationMixin
from .profile_context_application import ProfileContextApplication
from .service_errors import LabError, patient_safe_operation_message
from .store import GenomiLabStore
from .user_authority import CurrentUserAuthorityMixin
from .workspace_application import WorkspaceApplication, genome_metadata


class GenomiLabService(
    CurrentUserAuthorityMixin,
    PortalContextApplicationMixin,
    InvestigationCapabilityMixin,
    EvidenceApplicationMixin,
    HarnessApplicationMixin,
):
    """Current-user application service; the portal never talks to Genomi directly."""

    def __init__(
        self,
        *,
        store: GenomiLabStore | None = None,
        session_id: str | None = None,
        operation_call: Callable[..., JsonObject] = call_operation,
        harness_adapter: HarnessAdapter | None = None,
    ) -> None:
        self._initialize_current_user_authority()
        self.store = store or GenomiLabStore()
        self.session_id = session_id or f"genomilab-{secrets.token_urlsafe(18)}"
        self._call = operation_call
        self._uses_runtime_context_authority_lock = operation_call is call_operation
        self._operation_lock = threading.RLock()
        self._closed = False
        self._bound_user_id: str | None = None
        self._agi_authorizations: dict[str, AgiAuthorizationHandle] = {}
        self._context_candidates = ContextCandidateReceiptIssuer(
            self.store, self.session_id
        )
        self.harness_adapter = (
            harness_adapter or InstalledCodexAppServerAdapter.discover()
        )
        self._workspace = WorkspaceApplication(
            store=self.store,
            session_id=self.session_id,
            describe_context=lambda: self._safe_call("genomi.describe_context", {}),
            current_context=self._current_context,
            bind_user=self._bind_current_user,
            unbind_user=self._unbind_current_user,
            genome_metadata=genome_metadata,
            active_context_receipt=self._active_context_receipt,
            harness_manifest=self.harness_capability_manifest,
            evidence_manifest=self.evidence_capability_manifest,
        )
        self._harness_tools = HarnessToolBoundary(
            store=self.store,
            session_id=self.session_id,
            harness_adapter=self.harness_adapter,
            current_context=self._current_context,
            accepted_plan=self._accepted_current_plan,
            active_context_receipt=self._active_context_receipt,
            execute_request=lambda investigation_id, request: (
                self._execute_harness_capability_request(
                    investigation_id,
                    request,
                    _authority=_HARNESS_CAPABILITY_EXECUTION_AUTHORITY,
                )
            ),
        )
        self._profile_context = ProfileContextApplication(
            store=self.store,
            session_id=self.session_id,
            current_context=self._current_context,
            investigation=self.investigation,
            accepted_plan=self._accepted_current_plan,
            active_receipt=self._active_context_receipt,
            authorized_call=self._safe_authorized_call,
            safe_call=self._safe_call,
            candidate_receipts=self._context_candidates,
            authorizations=self._agi_authorizations,
        )
        self.harness_adapter.bind_dynamic_tool_handler(
            self._execute_guarded_harness_capability
        )

    def _execute_guarded_harness_capability(self, call: object) -> JsonObject:
        """Apply the service-wide user epoch to adapter-thread tool callbacks."""

        return self._run_current_user_operation(
            self._execute_bound_harness_capability, call
        )

    def _execute_bound_harness_capability(self, call: object) -> JsonObject:
        """Route app-server tools through the canonical durable plan executor."""
        return self._harness_tools.execute(call)

    def _accepted_current_plan(self, investigation_id: str) -> JsonObject:
        return self._workspace.accepted_current_plan(investigation_id)

    def bootstrap(self) -> JsonObject:
        return self.bootstrap_workspace()

    def bootstrap_workspace(self) -> JsonObject:
        return self._workspace.bootstrap()

    def molecular_profile(self) -> JsonObject:
        return self._workspace.molecular_profile()

    def add_profile_observation(self, payload: JsonObject) -> JsonObject:
        return self._workspace.add_profile_observation(payload)

    def review_or_supersede_observation(
        self, observation_revision_id: str, payload: JsonObject
    ) -> JsonObject:
        return self._workspace.review_or_supersede_observation(
            observation_revision_id, payload
        )

    def add_source_artifact(self, payload: JsonObject) -> JsonObject:
        return self._workspace.add_source_artifact(payload)

    def add_specimen(self, payload: JsonObject) -> JsonObject:
        return self._workspace.add_specimen(payload)

    def add_assay(self, payload: JsonObject) -> JsonObject:
        return self._workspace.add_assay(payload)

    def create_investigation(self, payload: JsonObject) -> JsonObject:
        return self._workspace.create_investigation(payload)

    def investigation(self, investigation_id: str) -> JsonObject:
        return self._workspace.investigation(investigation_id)

    def list_investigations(self) -> list[JsonObject]:
        return self._workspace.list_investigations()

    def accept_current_plan(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        return self._workspace.accept_current_plan(investigation_id, payload)

    def investigation_profile(self, investigation_id: str) -> JsonObject:
        return self._workspace.investigation_profile(investigation_id)

    def _approved_investigation_profile(self, investigation_id: str) -> JsonObject:
        return self._workspace.approved_investigation_profile(investigation_id)

    def profile_snapshot_candidate(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        """Build the exact molecular-profile context proposed for approval."""

        return self._profile_context.profile_snapshot_candidate(
            investigation_id, payload
        )

    def compare_investigation_context(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        return self.compare_investigation_context_candidate(investigation_id, payload)

    def approve_investigation_context(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        return self._profile_context.approve(investigation_id, payload)

    def invoke_investigation_genome(
        self,
        investigation_id: str,
        *,
        operation: str,
        params: JsonObject,
        expected_plan_version_id: str | None = None,
        expected_consent_receipt_id: str | None = None,
    ) -> JsonObject:
        return self._profile_context.invoke_genome(
            investigation_id,
            operation=operation,
            params=params,
            expected_plan_version_id=expected_plan_version_id,
            expected_consent_receipt_id=expected_consent_receipt_id,
        )

    def check_investigation_genome_job(
        self,
        investigation_id: str,
        *,
        job_id: str,
        resume_operation: str,
        expected_plan_version_id: str,
        expected_consent_receipt_id: str,
    ) -> JsonObject:
        return self._profile_context.check_genome_job(
            investigation_id,
            job_id=job_id,
            resume_operation=resume_operation,
            expected_plan_version_id=expected_plan_version_id,
            expected_consent_receipt_id=expected_consent_receipt_id,
        )

    def _require_investigation_genome_context(
        self, investigation_id: str
    ) -> tuple[JsonObject, AgiAuthorizationHandle]:
        return self._profile_context.require_genome_context(investigation_id)

    def revoke_private_context(self, investigation_id: str) -> JsonObject:
        investigation = self.investigation(investigation_id)
        snapshot_id = investigation.get("patient_molecular_snapshot_id")
        revoked_receipt = False
        if snapshot_id:
            receipt_id = str(investigation.get("active_consent_receipt_id") or "")
            if receipt_id:
                revoked_receipt = self.store.revoke_consent(receipt_id)
        handle = self._agi_authorizations.pop(investigation_id, None)
        revoked_handle = (
            revoke_investigation_agi_authorization(handle)
            if handle is not None
            else False
        )
        self.store.set_investigation_status(investigation_id, "paused_private_context")
        return {
            "status": "revoked",
            "investigation_id": investigation_id,
            "consent_revoked": revoked_receipt,
            "runtime_authorization_revoked": revoked_handle,
        }

    def close(self) -> None:
        if self._closed:
            return
        with self._operation_lock:
            self._revoke_runtime_access()
            self.store.revoke_session_consents(self.session_id)
            self.store.revoke_session_disclosures(self.session_id)
            self._context_candidates.clear()
            self._closed = True
            self.harness_adapter.close()

    def _current_context(self) -> tuple[JsonObject, str]:
        context = self._safe_call("genomi.describe_context", {})
        user_id = str(context.get("active_user_id") or "").strip()
        if not user_id:
            self._unbind_current_user()
            raise LabError(
                "genomi_user_required",
                "Create or select the current user in Genomi first.",
                http_status=409,
            )
        self._bind_current_user(user_id)
        return context, user_id

    def _bind_current_user(self, user_id: str) -> None:
        if self._bound_user_id and self._bound_user_id != user_id:
            self._revoke_runtime_access()
            self._context_candidates.clear()
            self.store.revoke_session_consents(self.session_id)
            self.store.revoke_session_disclosures(self.session_id)
        self._bound_user_id = user_id

    def _unbind_current_user(self) -> None:
        if self._bound_user_id:
            self._revoke_runtime_access()
            self._context_candidates.clear()
            self.store.revoke_session_consents(self.session_id)
            self.store.revoke_session_disclosures(self.session_id)
        self._bound_user_id = None

    def _safe_call(
        self, operation: str, params: JsonObject | None = None
    ) -> JsonObject:
        try:
            result = self._call(operation, params or {})
        except OperationError as exc:
            status = 403 if exc.code.endswith("approval_required") else 409
            raise LabError(
                exc.code, patient_safe_operation_message(exc.code), http_status=status
            ) from exc
        except (OSError, ValueError) as exc:
            raise LabError(
                "operation_failed",
                "The local Genomi operation could not be completed.",
                http_status=500,
            ) from exc
        if not isinstance(result, dict):
            raise LabError(
                "invalid_operation_result",
                "Genomi returned an invalid result.",
                http_status=500,
            )
        return result

    def _safe_authorized_call(
        self,
        operation: str,
        params: JsonObject,
        handle: AgiAuthorizationHandle,
    ) -> JsonObject:
        try:
            execution_context = execution_context_for_investigation_authorization(
                handle, operation=operation, params=params
            )
            result = self._call(
                operation, params, execution_context=execution_context
            )
        except InvestigationAgiAuthorizationError as exc:
            raise LabError(exc.code, str(exc), http_status=403) from exc
        except OperationError as exc:
            raise LabError(
                exc.code, patient_safe_operation_message(exc.code), http_status=409
            ) from exc
        if not isinstance(result, dict):
            raise LabError(
                "invalid_operation_result",
                "Genomi returned an invalid result.",
                http_status=500,
            )
        return result

    def _active_context_receipt(
        self, investigation: JsonObject, snapshot: JsonObject
    ) -> JsonObject:
        receipt_id = str(investigation.get("active_consent_receipt_id") or "")
        if not receipt_id:
            raise KeyError("active consent receipt is missing")
        receipt = self.store.consent_receipt(receipt_id)
        exact_fields = (
            "user_id",
            "investigation_id",
            "patient_molecular_snapshot_id",
            "purpose",
            "observation_revision_ids",
            "artifact_ids",
            "specimen_ids",
            "assay_ids",
            "agi_id",
            "agi_snapshot_id",
            "genomic_scope",
        )
        expected = {
            **snapshot,
            "investigation_id": investigation.get("investigation_id"),
            "patient_molecular_snapshot_id": snapshot.get(
                "patient_molecular_snapshot_id"
            ),
        }
        if any(receipt.get(field) != expected.get(field) for field in exact_fields):
            raise KeyError("active consent receipt does not match the pinned snapshot")
        return receipt

    def _issue_context_candidate_receipt(
        self,
        candidate: JsonObject,
        *,
        action: str,
    ) -> JsonObject:
        return self._context_candidates.issue(candidate, action=action)

    def _revoke_runtime_access(self) -> None:
        revoke_investigation_agi_authorizations_for_session(self.session_id)
        self._agi_authorizations.clear()
        try:
            self._call("active_genome_index.revoke_access", {})
        except Exception:
            pass
