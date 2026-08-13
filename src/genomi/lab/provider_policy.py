"""Fail-closed policy contracts for GenomiLab evidence providers.

This module owns authorization and request-lineage policy only. Provider
execution and result normalization live in :mod:`genomi.lab.evidence_gateway`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


PAPERCLIP_PROVIDER = "paperclip"


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


class ProviderPolicyState(str, Enum):
    ALLOWED = "allowed"
    BLOCKED_MISSING_DEPLOYMENT_AUTHORIZATION = (
        "blocked_missing_deployment_authorization"
    )
    BLOCKED_DEPLOYMENT_SCOPE = "blocked_deployment_scope"
    BLOCKED_MISSING_PATIENT_DATA_CONTRACT = (
        "blocked_missing_patient_data_contract"
    )
    BLOCKED_PATIENT_DATA_CONTRACT_SCOPE = (
        "blocked_patient_data_contract_scope"
    )
    BLOCKED_MISSING_EXACT_DISCLOSURE_APPROVAL = (
        "blocked_missing_exact_disclosure_approval"
    )
    BLOCKED_MISSING_EXACT_EGRESS_APPROVAL = (
        "blocked_missing_exact_egress_approval"
    )


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


def _query_terms(values: Iterable[object], *, query: str) -> tuple[str, ...]:
    terms = tuple(dict.fromkeys(required_text(value, "query_term", 1_000) for value in values))
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
    patient_influenced: bool = False
    query_terms: tuple[str, ...] = ()
    filters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        query = required_text(self.query, "query")
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "purpose", required_text(self.purpose, "purpose", 500))
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

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "query_terms": list(self.query_terms),
            "filters": dict(self.filters),
            "source_family": self.source_family.value,
            "purpose": self.purpose,
            "patient_influenced": self.patient_influenced,
        }


@dataclass(frozen=True)
class DeploymentAuthorization:
    provider: str
    authorization_id: str
    basis: AuthorizationBasis
    permitted_source_families: frozenset[SourceFamily]
    live_use_authorized: bool = True

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


@dataclass(frozen=True)
class PatientDataContract:
    provider: str
    contract_id: str
    permitted_source_families: frozenset[SourceFamily]
    patient_influenced_data_authorized: bool = True

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


@dataclass(frozen=True)
class DisclosureApproval:
    provider: str
    approval_id: str
    request_fingerprint: str
    approved: bool = True

    def __post_init__(self) -> None:
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
    """Bind an approval to the exact provider and complete request payload."""

    material = json.dumps(
        {"provider": provider_name(provider), **request.to_dict()},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def evaluate_live_provider_request(
    provider: str,
    request: EvidenceRequest,
    *,
    deployment_authorization: DeploymentAuthorization | None,
    patient_data_contract: PatientDataContract | None = None,
    disclosure_approval: DisclosureApproval | None = None,
) -> ProviderPolicyDecision:
    """Fail closed unless every gate required for this exact live call passes."""

    normalized_provider = provider_name(provider)
    if (
        deployment_authorization is None
        or not deployment_authorization.live_use_authorized
        or deployment_authorization.provider != normalized_provider
    ):
        return ProviderPolicyDecision(
            ProviderPolicyState.BLOCKED_MISSING_DEPLOYMENT_AUTHORIZATION
        )
    if request.source_family not in deployment_authorization.permitted_source_families:
        return ProviderPolicyDecision(ProviderPolicyState.BLOCKED_DEPLOYMENT_SCOPE)
    if not request.patient_influenced:
        return ProviderPolicyDecision(ProviderPolicyState.ALLOWED)
    if (
        patient_data_contract is None
        or not patient_data_contract.patient_influenced_data_authorized
        or patient_data_contract.provider != normalized_provider
        or patient_data_contract.contract_id == deployment_authorization.authorization_id
    ):
        return ProviderPolicyDecision(
            ProviderPolicyState.BLOCKED_MISSING_PATIENT_DATA_CONTRACT
        )
    if request.source_family not in patient_data_contract.permitted_source_families:
        return ProviderPolicyDecision(
            ProviderPolicyState.BLOCKED_PATIENT_DATA_CONTRACT_SCOPE
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
