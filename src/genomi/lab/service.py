"""GenomiLab application boundary for the current Genomi user."""

from __future__ import annotations

import secrets
import threading
from contextlib import ExitStack, contextmanager
from typing import Callable
from collections.abc import Iterator

from ..operations import OperationError, call_operation
from .agi_authority import (
    AgiAuthorizationHandle,
    InvestigationAgiAuthorizationError,
    execution_context_for_investigation_authorization,
    revoke_investigation_agi_authorization,
    revoke_investigation_agi_authorizations_for_session,
)
from .authorization_candidate_receipts import AuthorizationCandidateReceiptIssuer
from .models import JsonObject
from .context_candidate_receipts import ContextCandidateReceiptIssuer
from .encrypted_sqlite import (
    EncryptedSQLiteError,
    EncryptedSQLiteLockTimeoutError,
)
from .esm_transport import BiohubESMTransport
from .evidence_service import EvidenceApplicationMixin
from .harness import (
    HarnessAdapter,
    InstalledCodexAppServerAdapter,
)
from .harness_service import HarnessApplicationMixin
from .harness_tool_boundary import HarnessToolBoundary
from .investigation_capabilities import (
    InvestigationCapabilityMixin,
    _HARNESS_CAPABILITY_EXECUTION_AUTHORITY,
)
from .investigation_authorization import InvestigationAuthorizationApplication
from .investigation_authorized_flow import InvestigationAuthorizedFlowMixin
from .portal_context import PortalContextApplicationMixin
from .paperclip_adapter import PaperclipAdapter
from .paperclip_transport import GxlPaperclipTransport
from .profile_context_application import ProfileContextApplication
from .proto_transport import ModalProtoTransport
from .provider_connections import ProviderConnectionError, ProviderConnections
from .provider_credentials import (
    OSKeyringProviderCredentialStore,
    PROVIDER_IDS,
    ProviderCredentialError,
    provider_credential_lock,
)
from .provider_policy import DeploymentAuthorization, PatientDataContract
from .service_errors import LabError, patient_safe_operation_message
from .store import GenomiLabStore
from .user_authority import CurrentUserAuthorityMixin
from .workspace_application import WorkspaceApplication, genome_metadata


class GenomiLabService(
    CurrentUserAuthorityMixin,
    PortalContextApplicationMixin,
    InvestigationCapabilityMixin,
    EvidenceApplicationMixin,
    InvestigationAuthorizedFlowMixin,
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
        provider_credential_store: OSKeyringProviderCredentialStore | None = None,
        paperclip_deployment_authorization: DeploymentAuthorization | None = None,
        paperclip_patient_data_contract: PatientDataContract | None = None,
        paperclip_transport: GxlPaperclipTransport | None = None,
        biohub_esm_transport: BiohubESMTransport | None = None,
        proto_transport: ModalProtoTransport | None = None,
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
        self._authorization_candidates = AuthorizationCandidateReceiptIssuer(
            self.session_id
        )
        self.harness_adapter = (
            harness_adapter or InstalledCodexAppServerAdapter.discover()
        )
        self._paperclip_transport = paperclip_transport or GxlPaperclipTransport()
        self._biohub_esm_transport = biohub_esm_transport or BiohubESMTransport()
        self._proto_transport = proto_transport or ModalProtoTransport()
        self._provider_credentials = (
            provider_credential_store or OSKeyringProviderCredentialStore()
        )
        self._provider_connection_lock = threading.RLock()
        self.provider_connections = ProviderConnections(
            credential_store=self._provider_credentials,
            paperclip_probe=self._paperclip_transport.probe,
            biohub_esm_probe=self._biohub_esm_transport.probe,
            proto_probe=self._proto_transport.probe,
            paperclip_deployment_authorization=paperclip_deployment_authorization,
            paperclip_patient_data_contract=paperclip_patient_data_contract,
            paperclip_routes=self._paperclip_transport.supported_routes,
        )
        self.configure_evidence_gateway(
            paperclip_adapter=PaperclipAdapter(
                deployment_authorization=paperclip_deployment_authorization,
                patient_data_contract=paperclip_patient_data_contract,
                secret_provider=self._paperclip_secret,
                credential_configured=self._paperclip_credential_configured,
                live_transport=self._paperclip_transport,
                live_routes=self._paperclip_transport.supported_routes,
                connection_ready=self._paperclip_connection_ready,
            )
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
            integration_manifest=self._provider_connection_manifest,
        )
        self._harness_tools = HarnessToolBoundary(
            store=self.store,
            session_id=self.session_id,
            harness_adapter=self.harness_adapter,
            current_context=self._current_context,
            accepted_plan=self._accepted_current_plan,
            active_context_receipt=self._active_context_receipt,
            require_authorized_disclosure=(
                self._require_authorized_harness_disclosure
            ),
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
        self._investigation_authorizations = InvestigationAuthorizationApplication(
            store=self.store,
            session_id=self.session_id,
            current_context=self._current_context,
            investigation=self.investigation,
            context_candidate=self.investigation_context_candidate,
            approve_context=self._profile_context.approve,
            harness_manifest=self.harness_capability_manifest,
            ensure_planning_started=self._ensure_authorized_planning_started,
            candidate_receipts=self._authorization_candidates,
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

    def integrations(self) -> JsonObject:
        with self._provider_connection_scope(PROVIDER_IDS):
            return self.provider_connections.list_integrations(
                reconciliation_providers=(
                    self._provider_connection_reconciliation_providers()
                )
            )

    def _provider_connection_manifest(self) -> JsonObject:
        with self._provider_connection_scope(PROVIDER_IDS):
            return self.provider_connections.capability_manifest(
                reconciliation_providers=(
                    self._provider_connection_reconciliation_providers()
                )
            )

    def _provider_connection_reconciliation_providers(self) -> tuple[str, ...]:
        try:
            return self.store.provider_connection_reconciliation_providers()
        except Exception as exc:
            raise LabError(
                "provider_connection_audit_unavailable",
                "Research-tool state is unavailable because its local audit could not be read.",
                http_status=503,
            ) from exc

    @contextmanager
    def _provider_connection_scope(self, providers: tuple[str, ...]) -> Iterator[None]:
        """Hold provider account locks before exposing or changing connection state."""

        requested = frozenset(providers)
        ordered = tuple(provider for provider in PROVIDER_IDS if provider in requested)
        locks = ExitStack()
        try:
            try:
                for provider in ordered:
                    locks.enter_context(provider_credential_lock(provider))
            except EncryptedSQLiteLockTimeoutError as exc:
                raise LabError(
                    "provider_connection_busy",
                    "This research-tool connection is busy in another GenomiLab process. Try again shortly.",
                    http_status=503,
                ) from exc
            except (EncryptedSQLiteError, OSError) as exc:
                raise LabError(
                    "provider_connection_lock_unavailable",
                    "Research-tool connection state is temporarily unavailable.",
                    http_status=503,
                ) from exc
            with self._provider_connection_lock:
                yield
        finally:
            locks.close()

    def connect_integration(self, provider: str, payload: JsonObject) -> JsonObject:
        return self._provider_connection_call(
            "connect", provider, self.provider_connections.connect, provider, payload
        )

    def verify_integration(self, provider: str) -> JsonObject:
        return self._provider_connection_call(
            "verify", provider, self.provider_connections.verify, provider
        )

    def disconnect_integration(self, provider: str, *, confirmed: bool) -> JsonObject:
        return self._provider_connection_call(
            "disconnect",
            provider,
            self.provider_connections.disconnect,
            provider,
            confirmed=confirmed,
        )

    def _provider_connection_call(
        self,
        action: str,
        provider: str,
        operation: Callable[..., JsonObject],
        *args: object,
        **kwargs: object,
    ) -> JsonObject:
        with self._provider_connection_scope((provider,)):
            try:
                command_id = self.store.begin_provider_connection_command(
                    workspace_session_id=self.session_id,
                    provider=provider,
                    action=action,
                )
            except Exception as exc:
                raise LabError(
                    "provider_connection_audit_unavailable",
                    "Research-tool setup is unavailable because its local audit could not be started.",
                    http_status=503,
                ) from exc
            try:
                snapshot = self.provider_connections.transaction_snapshot(provider)
            except ProviderConnectionError as exc:
                failure = {
                    "provider": provider,
                    "status": "failed",
                    "error_code": exc.code,
                }
                self._finalize_provider_connection_command(
                    command_id, provider, action, failure
                )
                raise LabError(
                    exc.code,
                    str(exc),
                    http_status=exc.http_status,
                ) from exc
            try:
                result = operation(*args, **kwargs)
            except ProviderConnectionError as exc:
                try:
                    current = self.provider_connections.transaction_snapshot(provider)
                except ProviderConnectionError as snapshot_exc:
                    self.provider_connections.mark_reconciliation_required(provider)
                    failure = {
                        "provider": provider,
                        "status": "reconciliation_required",
                        "error_code": "provider_connection_reconciliation_required",
                    }
                    self._finalize_provider_connection_command(
                        command_id, provider, action, failure
                    )
                    raise LabError(
                        "provider_connection_reconciliation_required",
                        "Research-tool connection state requires reconciliation with its recorded intent.",
                        http_status=503,
                    ) from snapshot_exc
                try:
                    self.provider_connections.restore_transaction_snapshot(
                        snapshot,
                        expected_current=current,
                    )
                except ProviderConnectionError as restore_exc:
                    if (
                        restore_exc.code
                        == "provider_connection_reconciliation_required"
                    ):
                        self.provider_connections.mark_reconciliation_required(provider)
                    failure = {
                        "provider": provider,
                        "status": (
                            "reconciliation_required"
                            if restore_exc.code
                            == "provider_connection_reconciliation_required"
                            else "failed"
                        ),
                        "error_code": restore_exc.code,
                    }
                    self._finalize_provider_connection_command(
                        command_id, provider, action, failure
                    )
                    raise LabError(
                        restore_exc.code,
                        str(restore_exc),
                        http_status=restore_exc.http_status,
                    ) from restore_exc
                failure = {
                    "provider": provider,
                    "status": "failed",
                    "error_code": exc.code,
                }
                self._finalize_provider_connection_command(
                    command_id, provider, action, failure
                )
                raise LabError(
                    exc.code,
                    str(exc),
                    http_status=exc.http_status,
                ) from exc
            post_command_snapshot = None
            try:
                post_command_snapshot = self.provider_connections.transaction_snapshot(
                    provider
                )
                self.store.finalize_provider_connection_command(
                    command_id=command_id,
                    workspace_session_id=self.session_id,
                    provider=provider,
                    action=action,
                    result=result,
                )
            except Exception as exc:
                if post_command_snapshot is None:
                    self.provider_connections.mark_reconciliation_required(provider)
                    failure = {
                        "provider": provider,
                        "status": "reconciliation_required",
                        "error_code": "provider_connection_reconciliation_required",
                    }
                    self._finalize_provider_connection_command(
                        command_id, provider, action, failure
                    )
                    raise LabError(
                        "provider_connection_reconciliation_required",
                        "Research-tool connection state requires reconciliation with its recorded intent.",
                        http_status=503,
                    ) from exc
                try:
                    self.provider_connections.restore_transaction_snapshot(
                        snapshot,
                        expected_current=post_command_snapshot,
                    )
                except ProviderConnectionError as restore_exc:
                    raise LabError(
                        restore_exc.code,
                        str(restore_exc),
                        http_status=restore_exc.http_status,
                    ) from restore_exc
                raise LabError(
                    "provider_connection_audit_unavailable",
                    "Research-tool setup was not completed because its local audit could not be finalized.",
                    http_status=503,
                ) from exc
            return {**result, "connection_command_id": command_id}

    def _finalize_provider_connection_command(
        self,
        command_id: str,
        provider: str,
        action: str,
        result: JsonObject,
    ) -> None:
        try:
            self.store.finalize_provider_connection_command(
                command_id=command_id,
                workspace_session_id=self.session_id,
                provider=provider,
                action=action,
                result=result,
            )
        except Exception as exc:
            raise LabError(
                "provider_connection_audit_unavailable",
                "Research-tool setup failed and its local audit could not be finalized.",
                http_status=503,
            ) from exc

    def _paperclip_credential_configured(self) -> bool:
        with self._provider_connection_scope(("paperclip",)):
            try:
                return self._provider_credentials.has("paperclip")
            except ProviderCredentialError:
                return False

    def _paperclip_secret(self) -> str:
        with self._provider_connection_scope(("paperclip",)):
            if "paperclip" in self._provider_connection_reconciliation_providers():
                return ""
            return self.provider_connections.verified_paperclip_api_key()

    def _paperclip_connection_ready(self) -> bool:
        with self._provider_connection_scope(("paperclip",)):
            if "paperclip" in self._provider_connection_reconciliation_providers():
                return False
            return (
                self.provider_connections.integration("paperclip").get(
                    "connection_state"
                )
                == "ready"
            )

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

    def _accept_plan_for_conformance(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        """Exercise exact plan persistence in internal tests only."""

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

    def _approve_context_for_conformance(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        """Exercise context persistence in internal tests only."""

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
        revoked_authorizations = self.store.revoke_investigation_authorizations(
            investigation_id
        )
        self._authorization_candidates.discard_investigation(investigation_id)
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
            "investigation_authorizations_revoked": revoked_authorizations,
        }

    def close(self) -> None:
        if self._closed:
            return
        with self._operation_lock:
            self._revoke_runtime_access()
            self.store.revoke_session_consents(self.session_id)
            self.store.revoke_session_disclosures(self.session_id)
            self.store.revoke_session_investigation_authorizations(self.session_id)
            self._context_candidates.clear()
            self._authorization_candidates.clear()
            self.provider_connections.close()
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
            self._authorization_candidates.clear()
            self.store.revoke_session_consents(self.session_id)
            self.store.revoke_session_disclosures(self.session_id)
            self.store.revoke_session_investigation_authorizations(self.session_id)
        self._bound_user_id = user_id

    def _unbind_current_user(self) -> None:
        if self._bound_user_id:
            self._revoke_runtime_access()
            self._context_candidates.clear()
            self._authorization_candidates.clear()
            self.store.revoke_session_consents(self.session_id)
            self.store.revoke_session_disclosures(self.session_id)
            self.store.revoke_session_investigation_authorizations(self.session_id)
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
            result = self._call(operation, params, execution_context=execution_context)
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
