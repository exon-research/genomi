"""Fail-closed policy contracts for GenomiLab evidence providers.

This module owns authorization and request-lineage policy only. Provider
execution and result normalization live in :mod:`genomi.lab.evidence_gateway`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Mapping


PAPERCLIP_PROVIDER = "paperclip"
PAPERCLIP_CONNECTION_PROBE_QUERY = "TP53"
PAPERCLIP_CONNECTION_PROBE_PURPOSE = "Verify public Paperclip connection"


class SourceFamily(str, Enum):
    LITERATURE = "literature"
    REGULATORY = "regulatory"
    TRIAL_REGISTRY = "trial_registry"
    UNIPROT = "uniprot"
    PDB = "pdb"
    CHEMBL = "chembl"


class AccessMode(str, Enum):
    LIVE_PROVIDER = "live_provider"
    DIRECT_PRIMARY_SOURCE = "direct_primary_source"
    FIXTURE = "fixture"


class QueryOrigin(str, Enum):
    """Lineage declaration used to enforce the patient-data egress gate."""

    PUBLIC_ONLY = "public_only"
    PATIENT_CONTEXT_DERIVED = "patient_context_derived"


class EvidenceDataClass(str, Enum):
    """Exact outbound data class evaluated against provider agreements."""

    PUBLIC_QUERY = "public_query"
    PATIENT_INFLUENCED_PUBLIC_EVIDENCE_QUERY = (
        "patient_influenced_public_evidence_query"
    )


class ProviderPolicyState(str, Enum):
    ALLOWED = "allowed"
    BLOCKED_MISSING_DEPLOYMENT_AUTHORIZATION = (
        "blocked_missing_deployment_authorization"
    )
    BLOCKED_DEPLOYMENT_SCOPE = "blocked_deployment_scope"
    BLOCKED_DEPLOYMENT_OPERATION_SCOPE = "blocked_deployment_operation_scope"
    BLOCKED_DEPLOYMENT_DATA_CLASS_SCOPE = "blocked_deployment_data_class_scope"
    BLOCKED_DEPLOYMENT_PURPOSE_SCOPE = "blocked_deployment_purpose_scope"
    BLOCKED_DEPLOYMENT_NOT_YET_EFFECTIVE = "blocked_deployment_not_yet_effective"
    BLOCKED_DEPLOYMENT_EXPIRED = "blocked_deployment_expired"
    BLOCKED_DEPLOYMENT_REVOKED = "blocked_deployment_revoked"
    BLOCKED_MISSING_PATIENT_DATA_CONTRACT = "blocked_missing_patient_data_contract"
    BLOCKED_PATIENT_DATA_CONTRACT_SCOPE = "blocked_patient_data_contract_scope"
    BLOCKED_PATIENT_DATA_CONTRACT_OPERATION_SCOPE = (
        "blocked_patient_data_contract_operation_scope"
    )
    BLOCKED_PATIENT_DATA_CONTRACT_DATA_CLASS_SCOPE = (
        "blocked_patient_data_contract_data_class_scope"
    )
    BLOCKED_PATIENT_DATA_CONTRACT_PURPOSE_SCOPE = (
        "blocked_patient_data_contract_purpose_scope"
    )
    BLOCKED_PATIENT_DATA_CONTRACT_NOT_YET_EFFECTIVE = (
        "blocked_patient_data_contract_not_yet_effective"
    )
    BLOCKED_PATIENT_DATA_CONTRACT_EXPIRED = "blocked_patient_data_contract_expired"
    BLOCKED_PATIENT_DATA_CONTRACT_REVOKED = "blocked_patient_data_contract_revoked"
    BLOCKED_REQUEST_OPERATION_MISMATCH = "blocked_request_operation_mismatch"
    BLOCKED_MISSING_EXACT_DISCLOSURE_APPROVAL = (
        "blocked_missing_exact_disclosure_approval"
    )
    BLOCKED_MISSING_EXACT_EGRESS_APPROVAL = "blocked_missing_exact_egress_approval"


class AuthorizationBasis(str, Enum):
    WRITTEN_PROVIDER_AUTHORIZATION = "written_provider_authorization"
    DOCUMENTED_LEGAL_DETERMINATION = "documented_legal_determination"


def required_text(value: object, field: str, maximum: int = 4_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    if any(ord(character) < 32 and character not in "\t\n\r" for character in text):
        raise ValueError(f"{field} contains unsupported control characters")
    return text


def provider_name(value: object) -> str:
    return required_text(value, "provider", 100).lower()


def operation_name(value: object) -> str:
    return required_text(value, "operation", 100).lower()


def current_policy_time() -> datetime:
    return datetime.now(timezone.utc)


def _policy_time(value: object, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _optional_policy_time(value: object, field: str) -> datetime | None:
    return None if value is None else _policy_time(value, field)


def _operations(values: Iterable[object]) -> frozenset[str]:
    return frozenset(operation_name(value) for value in values)


def _purposes(values: Iterable[object]) -> frozenset[str]:
    return frozenset(required_text(value, "permitted_purpose", 500) for value in values)


def _data_classes(values: Iterable[object]) -> frozenset[EvidenceDataClass]:
    return frozenset(EvidenceDataClass(value) for value in values)


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _query_terms(values: Iterable[object], *, query: str) -> tuple[str, ...]:
    terms = tuple(
        dict.fromkeys(required_text(value, "query_term", 1_000) for value in values)
    )
    return terms or (query,)


def _filters(values: object) -> tuple[tuple[str, str], ...]:
    if values in (None, (), {}):
        return ()
    if isinstance(values, Mapping):
        items = values.items()
    else:
        try:
            items = tuple(values)  # type: ignore[arg-type]
        except TypeError as exc:
            raise ValueError("filters must be an object") from exc
    normalized: dict[str, str] = {}
    for raw_key, raw_value in items:
        key = required_text(raw_key, "filter name", 100)
        normalized[key] = required_text(raw_value, f"filters.{key}", 1_000)
    return tuple(sorted(normalized.items()))


@dataclass(frozen=True)
class EvidenceRequest:
    query: str
    source_family: SourceFamily
    purpose: str
    operation: str
    patient_influenced: bool = False
    query_terms: tuple[str, ...] = ()
    filters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        query = required_text(self.query, "query")
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "purpose", required_text(self.purpose, "purpose", 500))
        object.__setattr__(self, "operation", operation_name(self.operation))
        if not isinstance(self.source_family, SourceFamily):
            object.__setattr__(self, "source_family", SourceFamily(self.source_family))
        if not isinstance(self.patient_influenced, bool):
            raise ValueError("patient_influenced must be a boolean")
        object.__setattr__(
            self,
            "query_terms",
            _query_terms(self.query_terms, query=query),
        )
        object.__setattr__(self, "filters", _filters(self.filters))

    @property
    def data_class(self) -> EvidenceDataClass:
        return (
            EvidenceDataClass.PATIENT_INFLUENCED_PUBLIC_EVIDENCE_QUERY
            if self.patient_influenced
            else EvidenceDataClass.PUBLIC_QUERY
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "query_terms": list(self.query_terms),
            "filters": dict(self.filters),
            "source_family": self.source_family.value,
            "purpose": self.purpose,
            "operation": self.operation,
            "data_class": self.data_class.value,
            "patient_influenced": self.patient_influenced,
        }


@dataclass(frozen=True)
class DeploymentAuthorization:
    provider: str
    authorization_id: str
    basis: AuthorizationBasis
    permitted_source_families: frozenset[SourceFamily]
    permitted_operations: frozenset[str]
    permitted_purposes: frozenset[str]
    permitted_data_classes: frozenset[EvidenceDataClass]
    effective_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    policy_version_id: str
    aup_version_id: str
    terms_version_id: str
    privacy_version_id: str
    live_use_authorized: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", provider_name(self.provider))
        object.__setattr__(
            self,
            "authorization_id",
            required_text(self.authorization_id, "authorization_id", 200),
        )
        if not isinstance(self.basis, AuthorizationBasis):
            object.__setattr__(self, "basis", AuthorizationBasis(self.basis))
        object.__setattr__(
            self,
            "permitted_source_families",
            frozenset(SourceFamily(item) for item in self.permitted_source_families),
        )
        object.__setattr__(
            self, "permitted_operations", _operations(self.permitted_operations)
        )
        object.__setattr__(
            self, "permitted_purposes", _purposes(self.permitted_purposes)
        )
        object.__setattr__(
            self, "permitted_data_classes", _data_classes(self.permitted_data_classes)
        )
        effective_at = _policy_time(self.effective_at, "effective_at")
        expires_at = _policy_time(self.expires_at, "expires_at")
        if expires_at <= effective_at:
            raise ValueError("expires_at must be after effective_at")
        object.__setattr__(self, "effective_at", effective_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(
            self, "revoked_at", _optional_policy_time(self.revoked_at, "revoked_at")
        )
        for field in (
            "policy_version_id",
            "aup_version_id",
            "terms_version_id",
            "privacy_version_id",
        ):
            object.__setattr__(
                self, field, required_text(getattr(self, field), field, 200)
            )
        if not isinstance(self.live_use_authorized, bool):
            raise ValueError("live_use_authorized must be a boolean")


@dataclass(frozen=True)
class PatientDataContract:
    provider: str
    contract_id: str
    permitted_source_families: frozenset[SourceFamily]
    permitted_operations: frozenset[str]
    permitted_purposes: frozenset[str]
    permitted_data_classes: frozenset[EvidenceDataClass]
    effective_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    policy_version_id: str
    aup_version_id: str
    terms_version_id: str
    privacy_version_id: str
    patient_influenced_data_authorized: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", provider_name(self.provider))
        object.__setattr__(
            self, "contract_id", required_text(self.contract_id, "contract_id", 200)
        )
        object.__setattr__(
            self,
            "permitted_source_families",
            frozenset(SourceFamily(item) for item in self.permitted_source_families),
        )
        object.__setattr__(
            self, "permitted_operations", _operations(self.permitted_operations)
        )
        object.__setattr__(
            self, "permitted_purposes", _purposes(self.permitted_purposes)
        )
        object.__setattr__(
            self, "permitted_data_classes", _data_classes(self.permitted_data_classes)
        )
        effective_at = _policy_time(self.effective_at, "effective_at")
        expires_at = _policy_time(self.expires_at, "expires_at")
        if expires_at <= effective_at:
            raise ValueError("expires_at must be after effective_at")
        object.__setattr__(self, "effective_at", effective_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(
            self, "revoked_at", _optional_policy_time(self.revoked_at, "revoked_at")
        )
        for field in (
            "policy_version_id",
            "aup_version_id",
            "terms_version_id",
            "privacy_version_id",
        ):
            object.__setattr__(
                self, field, required_text(getattr(self, field), field, 200)
            )
        if not isinstance(self.patient_influenced_data_authorized, bool):
            raise ValueError("patient_influenced_data_authorized must be a boolean")


@dataclass(frozen=True)
class DisclosureApproval:
    provider: str
    approval_id: str
    request_fingerprint: str
    approved: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.approved, bool):
            raise ValueError("approved must be a boolean")
        object.__setattr__(self, "provider", provider_name(self.provider))
        object.__setattr__(
            self, "approval_id", required_text(self.approval_id, "approval_id", 200)
        )
        fingerprint = required_text(
            self.request_fingerprint, "request_fingerprint", 64
        ).lower()
        if len(fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in fingerprint
        ):
            raise ValueError("request_fingerprint must be a SHA-256 hex digest")
        object.__setattr__(self, "request_fingerprint", fingerprint)


@dataclass(frozen=True)
class ProviderPolicyDecision:
    state: ProviderPolicyState

    def __post_init__(self) -> None:
        if not isinstance(self.state, ProviderPolicyState):
            object.__setattr__(self, "state", ProviderPolicyState(self.state))

    @property
    def allowed(self) -> bool:
        return self.state is ProviderPolicyState.ALLOWED

    def to_dict(self) -> dict[str, object]:
        return {"state": self.state.value, "allowed": self.allowed}


def disclosure_fingerprint(provider: str, request: EvidenceRequest) -> str:
    """Bind an approval to the provider, operation, and complete request payload."""

    material = json.dumps(
        {
            "provider": provider_name(provider),
            **request.to_dict(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def live_provider_policy_binding(
    provider: str,
    request: EvidenceRequest,
    *,
    deployment_authorization: DeploymentAuthorization | None,
    patient_data_contract: PatientDataContract | None,
) -> dict[str, object]:
    """Return the exact versioned policy identity pinned in disclosure receipts."""

    normalized_provider = provider_name(provider)
    binding: dict[str, object] = {
        "provider": normalized_provider,
        "operation": request.operation,
        "data_class": request.data_class.value,
    }
    if deployment_authorization is None:
        binding["deployment_authorization_state"] = "missing"
    else:
        binding.update(
            _authorization_binding(
                "deployment",
                authorization_provider=deployment_authorization.provider,
                authorization_id=deployment_authorization.authorization_id,
                basis=deployment_authorization.basis.value,
                source_families=deployment_authorization.permitted_source_families,
                operations=deployment_authorization.permitted_operations,
                purposes=deployment_authorization.permitted_purposes,
                data_classes=deployment_authorization.permitted_data_classes,
                effective_at=deployment_authorization.effective_at,
                expires_at=deployment_authorization.expires_at,
                revoked_at=deployment_authorization.revoked_at,
                policy_version_id=deployment_authorization.policy_version_id,
                aup_version_id=deployment_authorization.aup_version_id,
                terms_version_id=deployment_authorization.terms_version_id,
                privacy_version_id=deployment_authorization.privacy_version_id,
                enabled=deployment_authorization.live_use_authorized,
            )
        )
    if request.patient_influenced:
        if patient_data_contract is None:
            binding["patient_data_contract_state"] = "missing"
        else:
            binding.update(
                _authorization_binding(
                    "patient_data",
                    authorization_provider=patient_data_contract.provider,
                    authorization_id=patient_data_contract.contract_id,
                    basis="independent_patient_data_contract",
                    source_families=patient_data_contract.permitted_source_families,
                    operations=patient_data_contract.permitted_operations,
                    purposes=patient_data_contract.permitted_purposes,
                    data_classes=patient_data_contract.permitted_data_classes,
                    effective_at=patient_data_contract.effective_at,
                    expires_at=patient_data_contract.expires_at,
                    revoked_at=patient_data_contract.revoked_at,
                    policy_version_id=patient_data_contract.policy_version_id,
                    aup_version_id=patient_data_contract.aup_version_id,
                    terms_version_id=patient_data_contract.terms_version_id,
                    privacy_version_id=patient_data_contract.privacy_version_id,
                    enabled=patient_data_contract.patient_influenced_data_authorized,
                )
            )
    return binding


def _authorization_binding(
    prefix: str,
    *,
    authorization_provider: str,
    authorization_id: str,
    basis: str,
    source_families: frozenset[SourceFamily],
    operations: frozenset[str],
    purposes: frozenset[str],
    data_classes: frozenset[EvidenceDataClass],
    effective_at: datetime,
    expires_at: datetime,
    revoked_at: datetime | None,
    policy_version_id: str,
    aup_version_id: str,
    terms_version_id: str,
    privacy_version_id: str,
    enabled: bool,
) -> dict[str, object]:
    scope = {
        "source_families": sorted(item.value for item in source_families),
        "operations": sorted(operations),
        "purposes": sorted(purposes),
        "data_classes": sorted(item.value for item in data_classes),
        "enabled": enabled,
    }
    scope_sha256 = hashlib.sha256(
        json.dumps(scope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    identifier_key = (
        "deployment_authorization_id"
        if prefix == "deployment"
        else "patient_data_contract_id"
    )
    return {
        identifier_key: authorization_id,
        f"{prefix}_provider": authorization_provider,
        f"{prefix}_authorization_basis": basis,
        f"{prefix}_policy_version_id": policy_version_id,
        f"{prefix}_aup_version_id": aup_version_id,
        f"{prefix}_terms_version_id": terms_version_id,
        f"{prefix}_privacy_version_id": privacy_version_id,
        f"{prefix}_effective_at": _timestamp(effective_at),
        f"{prefix}_expires_at": _timestamp(expires_at),
        f"{prefix}_revoked_at": _timestamp(revoked_at),
        f"{prefix}_scope_sha256": scope_sha256,
    }


def evaluate_live_provider_request(
    provider: str,
    request: EvidenceRequest,
    *,
    operation: str,
    current_time: datetime,
    deployment_authorization: DeploymentAuthorization | None,
    patient_data_contract: PatientDataContract | None = None,
    disclosure_approval: DisclosureApproval | None = None,
) -> ProviderPolicyDecision:
    """Fail closed unless every gate required for this exact live call passes."""

    normalized_provider = provider_name(provider)
    normalized_operation = operation_name(operation)
    now = _policy_time(current_time, "current_time")
    if normalized_operation != request.operation:
        return ProviderPolicyDecision(
            ProviderPolicyState.BLOCKED_REQUEST_OPERATION_MISMATCH
        )
    if (
        deployment_authorization is None
        or not deployment_authorization.live_use_authorized
        or deployment_authorization.provider != normalized_provider
    ):
        return ProviderPolicyDecision(
            ProviderPolicyState.BLOCKED_MISSING_DEPLOYMENT_AUTHORIZATION
        )
    deployment_lifecycle = deployment_authorization_lifecycle_state(
        deployment_authorization, now
    )
    if deployment_lifecycle is not None:
        return ProviderPolicyDecision(deployment_lifecycle)
    if request.source_family not in deployment_authorization.permitted_source_families:
        return ProviderPolicyDecision(ProviderPolicyState.BLOCKED_DEPLOYMENT_SCOPE)
    if normalized_operation not in deployment_authorization.permitted_operations:
        return ProviderPolicyDecision(
            ProviderPolicyState.BLOCKED_DEPLOYMENT_OPERATION_SCOPE
        )
    if request.data_class not in deployment_authorization.permitted_data_classes:
        return ProviderPolicyDecision(
            ProviderPolicyState.BLOCKED_DEPLOYMENT_DATA_CLASS_SCOPE
        )
    if request.purpose not in deployment_authorization.permitted_purposes:
        return ProviderPolicyDecision(
            ProviderPolicyState.BLOCKED_DEPLOYMENT_PURPOSE_SCOPE
        )
    if not request.patient_influenced:
        return ProviderPolicyDecision(ProviderPolicyState.ALLOWED)
    if (
        patient_data_contract is None
        or not patient_data_contract.patient_influenced_data_authorized
        or patient_data_contract.provider != normalized_provider
        or patient_data_contract.contract_id
        == deployment_authorization.authorization_id
    ):
        return ProviderPolicyDecision(
            ProviderPolicyState.BLOCKED_MISSING_PATIENT_DATA_CONTRACT
        )
    patient_contract_lifecycle = patient_data_contract_lifecycle_state(
        patient_data_contract, now
    )
    if patient_contract_lifecycle is not None:
        return ProviderPolicyDecision(patient_contract_lifecycle)
    if request.source_family not in patient_data_contract.permitted_source_families:
        return ProviderPolicyDecision(
            ProviderPolicyState.BLOCKED_PATIENT_DATA_CONTRACT_SCOPE
        )
    if normalized_operation not in patient_data_contract.permitted_operations:
        return ProviderPolicyDecision(
            ProviderPolicyState.BLOCKED_PATIENT_DATA_CONTRACT_OPERATION_SCOPE
        )
    if request.data_class not in patient_data_contract.permitted_data_classes:
        return ProviderPolicyDecision(
            ProviderPolicyState.BLOCKED_PATIENT_DATA_CONTRACT_DATA_CLASS_SCOPE
        )
    if request.purpose not in patient_data_contract.permitted_purposes:
        return ProviderPolicyDecision(
            ProviderPolicyState.BLOCKED_PATIENT_DATA_CONTRACT_PURPOSE_SCOPE
        )
    if (
        disclosure_approval is None
        or not disclosure_approval.approved
        or disclosure_approval.provider != normalized_provider
        or disclosure_approval.request_fingerprint
        != disclosure_fingerprint(normalized_provider, request)
    ):
        return ProviderPolicyDecision(
            ProviderPolicyState.BLOCKED_MISSING_EXACT_DISCLOSURE_APPROVAL
        )
    return ProviderPolicyDecision(ProviderPolicyState.ALLOWED)


def evaluate_paperclip_connection_probe(
    *,
    deployment_authorization: DeploymentAuthorization | None,
    current_time: datetime,
) -> ProviderPolicyDecision:
    """Evaluate the exact fixed public query used to verify Paperclip access."""

    request = EvidenceRequest(
        query=PAPERCLIP_CONNECTION_PROBE_QUERY,
        source_family=SourceFamily.LITERATURE,
        purpose=PAPERCLIP_CONNECTION_PROBE_PURPOSE,
        operation="search",
    )
    return evaluate_live_provider_request(
        PAPERCLIP_PROVIDER,
        request,
        operation="search",
        current_time=current_time,
        deployment_authorization=deployment_authorization,
    )


def evaluate_paperclip_patient_route(
    *,
    source_family: SourceFamily,
    operation: str,
    deployment_authorization: DeploymentAuthorization | None,
    patient_data_contract: PatientDataContract | None,
    current_time: datetime,
) -> ProviderPolicyDecision:
    """Evaluate one advertised patient-investigation route before disclosure."""

    shared_purposes = (
        deployment_authorization.permitted_purposes.intersection(
            patient_data_contract.permitted_purposes
        )
        if deployment_authorization is not None and patient_data_contract is not None
        else deployment_authorization.permitted_purposes
        if deployment_authorization is not None
        else frozenset()
    )
    request = EvidenceRequest(
        query="GenomiLab patient-evidence route",
        source_family=source_family,
        purpose=(
            min(shared_purposes) if shared_purposes else "No shared provider purpose"
        ),
        operation=operation,
        patient_influenced=True,
    )
    return evaluate_live_provider_request(
        PAPERCLIP_PROVIDER,
        request,
        operation=operation,
        current_time=current_time,
        deployment_authorization=deployment_authorization,
        patient_data_contract=patient_data_contract,
    )


def paperclip_patient_route_eligible(decision: ProviderPolicyDecision) -> bool:
    """Return whether only the per-query disclosure gate remains for a route."""

    return decision.state in {
        ProviderPolicyState.ALLOWED,
        ProviderPolicyState.BLOCKED_MISSING_EXACT_DISCLOSURE_APPROVAL,
    }


def deployment_authorization_lifecycle_state(
    authorization: DeploymentAuthorization, current_time: datetime
) -> ProviderPolicyState | None:
    """Return the temporal deployment block, or ``None`` while active."""

    now = _policy_time(current_time, "current_time")
    if authorization.revoked_at is not None and now >= authorization.revoked_at:
        return ProviderPolicyState.BLOCKED_DEPLOYMENT_REVOKED
    if now < authorization.effective_at:
        return ProviderPolicyState.BLOCKED_DEPLOYMENT_NOT_YET_EFFECTIVE
    if now >= authorization.expires_at:
        return ProviderPolicyState.BLOCKED_DEPLOYMENT_EXPIRED
    return None


def patient_data_contract_lifecycle_state(
    contract: PatientDataContract, current_time: datetime
) -> ProviderPolicyState | None:
    """Return the temporal patient-contract block, or ``None`` while active."""

    now = _policy_time(current_time, "current_time")
    if contract.revoked_at is not None and now >= contract.revoked_at:
        return ProviderPolicyState.BLOCKED_PATIENT_DATA_CONTRACT_REVOKED
    if now < contract.effective_at:
        return ProviderPolicyState.BLOCKED_PATIENT_DATA_CONTRACT_NOT_YET_EFFECTIVE
    if now >= contract.expires_at:
        return ProviderPolicyState.BLOCKED_PATIENT_DATA_CONTRACT_EXPIRED
    return None


@dataclass(frozen=True)
class EvidenceRoute:
    provider: str
    access_mode: AccessMode
    available: bool
    policy: ProviderPolicyDecision

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", provider_name(self.provider))
        if not isinstance(self.access_mode, AccessMode):
            object.__setattr__(self, "access_mode", AccessMode(self.access_mode))


def select_preferred_evidence_route(
    routes: Iterable[EvidenceRoute],
) -> EvidenceRoute | None:
    """Prefer an allowed Paperclip route, then direct sources, then fixtures."""

    eligible = [route for route in routes if route.available and route.policy.allowed]
    if not eligible:
        return None
    priorities = {
        (PAPERCLIP_PROVIDER, AccessMode.LIVE_PROVIDER): 0,
        ("", AccessMode.DIRECT_PRIMARY_SOURCE): 1,
        ("", AccessMode.FIXTURE): 2,
    }

    def priority(route: EvidenceRoute) -> tuple[int, str]:
        exact = priorities.get((route.provider, route.access_mode))
        if exact is not None:
            return exact, route.provider
        return priorities.get(("", route.access_mode), 3), route.provider

    return min(eligible, key=priority)
