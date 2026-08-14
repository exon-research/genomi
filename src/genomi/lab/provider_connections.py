"""Redacted setup and verification state for optional research providers."""

from __future__ import annotations

import threading
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable

from .evidence_types import EvidenceStatus, ProviderTransportError
from .provider_credentials import (
    BIOHUB_ESM_PROVIDER_ID,
    PAPERCLIP_PROVIDER_ID,
    PROVIDER_IDS,
    PROTO_PROVIDER_ID,
    OSKeyringProviderCredentialStore,
    ProviderCredentialCorruptError,
    ProviderCredentialError,
    ProviderCredentialSnapshot,
    ProviderCredentialStoreUnavailableError,
    ProviderCredentialValidationError,
    ProviderId,
)
from .provider_policy import (
    DeploymentAuthorization,
    PatientDataContract,
    ProviderPolicyDecision,
    SourceFamily,
    evaluate_paperclip_connection_probe,
    evaluate_paperclip_patient_route,
    paperclip_patient_route_eligible,
)


PaperclipProbe = Callable[[str], None]
BiohubESMProbe = Callable[[str], None]
ProtoProbe = Callable[[str, str, str], None]
Clock = Callable[[], datetime]


class ProviderConnectionError(RuntimeError):
    """Patient-safe integration setup failure."""

    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True)
class _ProviderSpec:
    provider: ProviderId
    execution_location: str
    use_scope: str
    policy_state: str
    operations: tuple[str, ...]
    verification_kind: str
    verification_may_consume_credits: bool = False
    verification_available: bool = True


_SPECS = {
    PAPERCLIP_PROVIDER_ID: _ProviderSpec(
        provider=PAPERCLIP_PROVIDER_ID,
        execution_location="remote",
        use_scope="public_evidence",
        policy_state="blocked_missing_deployment_authorization",
        operations=("search", "lookup"),
        verification_kind="fixed_public_search",
        verification_may_consume_credits=True,
    ),
    BIOHUB_ESM_PROVIDER_ID: _ProviderSpec(
        provider=BIOHUB_ESM_PROVIDER_ID,
        execution_location="remote",
        use_scope="public_or_synthetic_protein",
        policy_state="requires_pinned_safe_esm_runtime",
        operations=(),
        verification_kind="not_available_until_pinned_safe_transport",
        verification_available=False,
    ),
    PROTO_PROVIDER_ID: _ProviderSpec(
        provider=PROTO_PROVIDER_ID,
        execution_location="remote",
        use_scope="expert_non_patient_only",
        policy_state="requires_proto_runtime_and_expert_mode",
        operations=(),
        verification_kind="not_available_until_pinned_proto_runtime",
        verification_available=False,
    ),
}


@dataclass(frozen=True, repr=False)
class ProviderConnectionSnapshot:
    """Exact credential and session-verification state for local compensation."""

    provider: ProviderId
    credential: ProviderCredentialSnapshot
    verification: tuple[str, str | None, str] | None

    def __repr__(self) -> str:
        return (
            "ProviderConnectionSnapshot("
            f"provider={self.provider!r}, configured={self.credential._encoded is not None}, "
            "redacted=True)"
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


class ProviderConnections:
    """Keep credentials in Keychain and expose only safe setup state."""

    def __init__(
        self,
        *,
        credential_store: OSKeyringProviderCredentialStore,
        paperclip_probe: PaperclipProbe,
        biohub_esm_probe: BiohubESMProbe,
        proto_probe: ProtoProbe,
        paperclip_deployment_authorization: DeploymentAuthorization | None = None,
        paperclip_patient_data_contract: PatientDataContract | None = None,
        paperclip_routes: Mapping[SourceFamily | str, Sequence[object]] | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        self.credential_store = credential_store
        self._paperclip_probe = paperclip_probe
        self._biohub_esm_probe = biohub_esm_probe
        self._proto_probe = proto_probe
        self._paperclip_authorization = paperclip_deployment_authorization
        self._paperclip_patient_data_contract = paperclip_patient_data_contract
        self._paperclip_routes = _normalized_paperclip_routes(paperclip_routes)
        self._clock = clock
        self._lock = threading.RLock()
        self._verification: dict[ProviderId, tuple[str, str | None, str]] = {}

    def list_integrations(
        self, *, reconciliation_providers: Collection[str] = ()
    ) -> dict[str, object]:
        reconciliation_required = frozenset(reconciliation_providers)
        return {
            "status": "ready",
            "integrations": [
                self.integration(
                    provider,
                    reconciliation_required=provider in reconciliation_required,
                )
                for provider in PROVIDER_IDS
            ],
        }

    def integration(
        self, provider: str, *, reconciliation_required: bool = False
    ) -> dict[str, object]:
        provider_id = self._provider(provider)
        try:
            loaded = self.credential_store.get_with_revision(provider_id)
        except ProviderCredentialCorruptError:
            manifest = self._manifest(
                provider_id,
                configured=False,
                credential_state="corrupt",
                connection_state="credential_corrupt",
                last_verified_at=None,
            )
            return (
                self._mark_reconciliation_required(manifest)
                if reconciliation_required
                else manifest
            )
        except ProviderCredentialError:
            manifest = self._manifest(
                provider_id,
                configured=False,
                credential_state="unavailable",
                connection_state="credential_store_unavailable",
                last_verified_at=None,
            )
            return (
                self._mark_reconciliation_required(manifest)
                if reconciliation_required
                else manifest
            )
        configured = loaded is not None
        credential_revision = loaded[1] if loaded is not None else None
        with self._lock:
            verification = self._verification.get(provider_id)
        if verification is not None and verification[2] == credential_revision:
            state, verified_at, _revision = verification
        else:
            state, verified_at = "configured_unverified", None
        if not configured:
            state, verified_at = "not_configured", None
        elif (
            provider_id == PAPERCLIP_PROVIDER_ID
            and not self._paperclip_probe_authorized()
        ):
            state, verified_at = "configured_unverified", None
        manifest = self._manifest(
            provider_id,
            configured=configured,
            connection_state=state,
            last_verified_at=verified_at,
        )
        return (
            self._mark_reconciliation_required(manifest)
            if reconciliation_required
            else manifest
        )

    def connect(
        self, provider: str, credentials: Mapping[str, object]
    ) -> dict[str, object]:
        provider_id = self._provider(provider)
        with self._lock:
            try:
                self.credential_store.replace(provider_id, credentials)
            except ProviderCredentialValidationError as exc:
                raise ProviderConnectionError(
                    "invalid_integration_credentials",
                    "Enter every required credential field and no additional fields.",
                ) from exc
            except ProviderCredentialStoreUnavailableError as exc:
                raise ProviderConnectionError(
                    "credential_store_unavailable",
                    "The operating system's secure credential store is unavailable.",
                    http_status=503,
                ) from exc
            self._verification.pop(provider_id, None)
        return self.integration(provider_id)

    def verify(self, provider: str) -> dict[str, object]:
        provider_id = self._provider(provider)
        if (
            provider_id == PAPERCLIP_PROVIDER_ID
            and not self._paperclip_probe_authorized()
        ):
            return self.integration(provider_id)
        try:
            with self._lock:
                loaded = self.credential_store.get_with_revision(provider_id)
        except ProviderCredentialError as exc:
            raise ProviderConnectionError(
                "credential_store_unavailable",
                "The operating system's secure credential store is unavailable.",
                http_status=503,
            ) from exc
        if loaded is None:
            raise ProviderConnectionError(
                "integration_not_configured",
                "Connect this research tool before checking it.",
                http_status=409,
            )
        credentials, credential_revision = loaded
        if not _SPECS[provider_id].verification_available:
            with self._lock:
                self._verification[provider_id] = (
                    "verification_unavailable",
                    None,
                    credential_revision,
                )
            return self.integration(provider_id)
        try:
            if provider_id == PAPERCLIP_PROVIDER_ID:
                self._paperclip_probe(credentials["api_key"])
            else:
                self._biohub_esm_probe(credentials["api_token"])
        except ProviderTransportError as exc:
            state = {
                EvidenceStatus.AUTHENTICATION_FAILED: "authentication_failed",
                EvidenceStatus.SOURCE_UNAVAILABLE: "runtime_unavailable",
            }.get(exc.status, "unreachable")
        except (TimeoutError, ConnectionError, OSError):
            state = "unreachable"
        except Exception:
            state = "unreachable"
        else:
            state = "ready"
        verified_at = _timestamp(self._clock())
        with self._lock:
            try:
                current = self.credential_store.get_with_revision(provider_id)
            except ProviderCredentialError:
                current = None
            if current is None or current[1] != credential_revision:
                self._verification.pop(provider_id, None)
            else:
                self._verification[provider_id] = (
                    state,
                    verified_at,
                    credential_revision,
                )
        return self.integration(provider_id)

    def disconnect(self, provider: str, *, confirmed: bool) -> dict[str, object]:
        provider_id = self._provider(provider)
        if confirmed is not True:
            raise ProviderConnectionError(
                "disconnect_confirmation_required",
                "Explicit confirmation is required before removing saved credentials.",
            )
        with self._lock:
            try:
                self.credential_store.delete(provider_id)
            except ProviderCredentialError as exc:
                raise ProviderConnectionError(
                    "credential_store_unavailable",
                    "The operating system's secure credential store is unavailable.",
                    http_status=503,
                ) from exc
            self._verification.pop(provider_id, None)
        return self.integration(provider_id)

    def verified_secret(self, provider: str, field: str) -> str:
        """Return a secret only when the current exact credential was verified."""

        provider_id = self._provider(provider)
        if (
            provider_id == PAPERCLIP_PROVIDER_ID
            and not self._paperclip_probe_authorized()
        ):
            return ""
        with self._lock:
            try:
                loaded = self.credential_store.get_with_revision(provider_id)
            except ProviderCredentialError:
                return ""
            verification = self._verification.get(provider_id)
            if (
                loaded is None
                or verification is None
                or verification[0] != "ready"
                or verification[2] != loaded[1]
            ):
                return ""
            return loaded[0].get(field, "")

    def transaction_snapshot(self, provider: str) -> ProviderConnectionSnapshot:
        """Capture exact local state before a command with external side effects."""

        provider_id = self._provider(provider)
        with self._lock:
            try:
                credential = self.credential_store.capture_snapshot(provider_id)
            except ProviderCredentialError as exc:
                raise ProviderConnectionError(
                    "credential_store_unavailable",
                    "The operating system's secure credential store is unavailable.",
                    http_status=503,
                ) from exc
            return ProviderConnectionSnapshot(
                provider=provider_id,
                credential=credential,
                verification=self._verification.get(provider_id),
            )

    def restore_transaction_snapshot(
        self,
        snapshot: ProviderConnectionSnapshot,
        *,
        expected_current: ProviderConnectionSnapshot | None = None,
    ) -> None:
        """Compensate a command whose durable final audit write did not commit."""

        if not isinstance(snapshot, ProviderConnectionSnapshot):
            raise ProviderConnectionError(
                "provider_connection_reconciliation_required",
                "Research-tool connection state could not be reconciled.",
                http_status=503,
            )
        with self._lock:
            try:
                self.credential_store.restore_snapshot(
                    snapshot.credential,
                    expected_current=(
                        expected_current.credential
                        if expected_current is not None
                        else None
                    ),
                )
            except ProviderCredentialError as exc:
                raise ProviderConnectionError(
                    "provider_connection_reconciliation_required",
                    "Research-tool connection state could not be reconciled.",
                    http_status=503,
                ) from exc
            if snapshot.verification is None:
                self._verification.pop(snapshot.provider, None)
            else:
                self._verification[snapshot.provider] = snapshot.verification

    def capability_manifest(
        self, *, reconciliation_providers: Collection[str] = ()
    ) -> dict[str, object]:
        return {
            "provider_connections": self.list_integrations(
                reconciliation_providers=reconciliation_providers
            )["integrations"]
        }

    def close(self) -> None:
        with self._lock:
            self._verification.clear()

    def mark_reconciliation_required(self, provider: str) -> None:
        """Prevent an indeterminate command from retaining a ready secret."""

        provider_id = self._provider(provider)
        with self._lock:
            self._verification.pop(provider_id, None)

    @staticmethod
    def _provider(provider: str) -> ProviderId:
        if provider not in _SPECS:
            raise ProviderConnectionError(
                "invalid_integration",
                "This research-tool connection is not supported.",
                http_status=404,
            )
        return provider  # type: ignore[return-value]

    def _paperclip_probe_authorized(self) -> bool:
        return evaluate_paperclip_connection_probe(
            deployment_authorization=self._paperclip_authorization,
            current_time=self._clock(),
        ).allowed

    def _policy_state(self, provider: ProviderId) -> str:
        if provider == PAPERCLIP_PROVIDER_ID:
            return self._paperclip_policy_state()
        return _SPECS[provider].policy_state

    def _paperclip_policy_state(self) -> str:
        decisions = self._paperclip_route_decisions()
        if any(paperclip_patient_route_eligible(item) for item in decisions):
            return "authorized"
        if decisions:
            return decisions[0].state.value
        baseline = evaluate_paperclip_patient_route(
            source_family=SourceFamily.LITERATURE,
            operation="search",
            deployment_authorization=self._paperclip_authorization,
            patient_data_contract=self._paperclip_patient_data_contract,
            current_time=self._clock(),
        )
        return (
            "authorized_unavailable"
            if paperclip_patient_route_eligible(baseline)
            else baseline.state.value
        )

    def _paperclip_route_decisions(self) -> tuple[ProviderPolicyDecision, ...]:
        now = self._clock()
        return tuple(
            evaluate_paperclip_patient_route(
                source_family=family,
                operation=operation,
                deployment_authorization=self._paperclip_authorization,
                patient_data_contract=self._paperclip_patient_data_contract,
                current_time=now,
            )
            for family, operations in self._paperclip_routes.items()
            for operation in operations
        )

    def _paperclip_available_operations(self) -> tuple[str, ...]:
        now = self._clock()
        routed_operations = {
            operation
            for family, operations in self._paperclip_routes.items()
            for operation in operations
            if paperclip_patient_route_eligible(
                evaluate_paperclip_patient_route(
                    source_family=family,
                    operation=operation,
                    deployment_authorization=self._paperclip_authorization,
                    patient_data_contract=self._paperclip_patient_data_contract,
                    current_time=now,
                )
            )
        }
        return tuple(
            operation
            for operation in _SPECS[PAPERCLIP_PROVIDER_ID].operations
            if operation in routed_operations
        )

    def _manifest(
        self,
        provider: ProviderId,
        *,
        configured: bool,
        credential_state: str | None = None,
        connection_state: str,
        last_verified_at: str | None,
    ) -> dict[str, object]:
        spec = _SPECS[provider]
        operations = (
            list(self._paperclip_available_operations())
            if provider == PAPERCLIP_PROVIDER_ID and connection_state == "ready"
            else []
        )
        verification_available = spec.verification_available and (
            provider != PAPERCLIP_PROVIDER_ID or self._paperclip_probe_authorized()
        )
        return {
            "provider": provider,
            "connection_state": connection_state,
            "credential_state": credential_state
            or ("stored" if configured else "missing"),
            "execution_location": spec.execution_location,
            "policy_state": self._policy_state(provider),
            "available_operations": operations,
            "last_verified_at": last_verified_at,
            "use_scope": spec.use_scope,
            "verification_kind": spec.verification_kind,
            "verification_may_consume_credits": (spec.verification_may_consume_credits),
            "verification_available": verification_available,
        }

    @staticmethod
    def _mark_reconciliation_required(
        manifest: dict[str, object],
    ) -> dict[str, object]:
        return {
            **manifest,
            "connection_state": "reconciliation_required",
            "available_operations": [],
            "last_verified_at": None,
        }


def _normalized_paperclip_routes(
    routes: Mapping[SourceFamily | str, Sequence[object]] | None,
) -> dict[SourceFamily, tuple[str, ...]]:
    if routes is None:
        return {}
    allowed_operations = frozenset(_SPECS[PAPERCLIP_PROVIDER_ID].operations)
    normalized: dict[SourceFamily, tuple[str, ...]] = {}
    for family, operations in routes.items():
        source_family = SourceFamily(family)
        operation_names = tuple(
            dict.fromkeys(
                value
                for operation in operations
                if (value := _operation_name(operation)) in allowed_operations
            )
        )
        normalized[source_family] = operation_names
    return normalized


def _operation_name(operation: object) -> str:
    value = operation.value if isinstance(operation, Enum) else operation
    return value if isinstance(value, str) else ""
