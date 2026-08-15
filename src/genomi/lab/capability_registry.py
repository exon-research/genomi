"""Canonical definitions for harness-visible GenomiLab capabilities.

The registry is deliberately data-only.  Investigation code owns application
services, while this module owns capability identity, execution family,
approval policy, background-job owner, and dynamic-tool presentation.  Every
surface that needs to classify a capability consults the same definition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from .disease_evidence_catalog import LOCAL_DISEASE_EVIDENCE_CAPABILITIES
from .disease_evidence_external import EXTERNAL_DISEASE_EVIDENCE_CAPABILITIES
from .disease_relation_contract import REGISTER_DISEASE_RELATION


PROFILE_PROJECT = "investigation.project_profile"
GENOMI_VARIANT_RESOLVE = "genomi.variant.resolve"
PUBLIC_EVIDENCE_RETRIEVE = "public_evidence.retrieve"
REGISTER_HYPOTHESIS = "investigation.register_hypothesis"
REGISTER_GAP = "investigation.register_gap"


class CapabilityFamily(StrEnum):
    """Execution and parameter-contract owner for a capability."""

    PROFILE_PROJECTION = "profile_projection"
    GENOMI_VARIANT = "genomi_variant"
    LOCAL_DISEASE_EVIDENCE = "local_disease_evidence"
    PUBLIC_EVIDENCE = "public_evidence"
    SOURCE_PUBLIC_EVIDENCE = "source_public_evidence"
    DISEASE_RELATION = "disease_relation"
    HYPOTHESIS = "hypothesis"
    GAP = "gap"


class BackgroundJobOwner(StrEnum):
    """Service that may resume an in-progress capability result."""

    NONE = "none"
    GENOMI = "genomi"
    PUBLIC_EVIDENCE = "public_evidence"


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    """One immutable harness capability contract."""

    name: str
    family: CapabilityFamily
    privacy: str
    background_job_owner: BackgroundJobOwner = BackgroundJobOwner.NONE
    requires_exact_egress_approval: bool = False

    @property
    def dynamic_tool_description(self) -> str:
        return (
            "Execute one immutable request from the exact accepted GenomiLab "
            f"plan for {self.name}. Arguments cannot change its parameters."
        )


def _definition(
    name: str,
    family: CapabilityFamily,
    privacy: str,
    *,
    background_job_owner: BackgroundJobOwner = BackgroundJobOwner.NONE,
    requires_exact_egress_approval: bool = False,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        name=name,
        family=family,
        privacy=privacy,
        background_job_owner=background_job_owner,
        requires_exact_egress_approval=requires_exact_egress_approval,
    )


_DEFINITIONS = [
    _definition(
        PROFILE_PROJECT,
        CapabilityFamily.PROFILE_PROJECTION,
        "approved_profile_slice_only",
    ),
    _definition(
        GENOMI_VARIANT_RESOLVE,
        CapabilityFamily.GENOMI_VARIANT,
        "exact_genomi_authorization_required",
        background_job_owner=BackgroundJobOwner.GENOMI,
    ),
    _definition(
        PUBLIC_EVIDENCE_RETRIEVE,
        CapabilityFamily.PUBLIC_EVIDENCE,
        "exact_disclosure_approval_before_external_egress",
        background_job_owner=BackgroundJobOwner.PUBLIC_EVIDENCE,
        requires_exact_egress_approval=True,
    ),
    _definition(
        REGISTER_DISEASE_RELATION,
        CapabilityFamily.DISEASE_RELATION,
        "local_domain_only_no_provider_egress",
    ),
    _definition(
        REGISTER_HYPOTHESIS,
        CapabilityFamily.HYPOTHESIS,
        "immutable_ledger_and_profile_anchors_only",
    ),
    _definition(
        REGISTER_GAP,
        CapabilityFamily.GAP,
        "immutable_ledger_and_profile_anchors_only",
    ),
    *(
        _definition(
            name,
            CapabilityFamily.LOCAL_DISEASE_EVIDENCE,
            "approved_profile_terms_local_only",
        )
        for name in sorted(LOCAL_DISEASE_EVIDENCE_CAPABILITIES)
    ),
    *(
        _definition(
            name,
            CapabilityFamily.SOURCE_PUBLIC_EVIDENCE,
            "local_profile_anchors_removed_before_exact_disclosure_and_egress",
            background_job_owner=BackgroundJobOwner.PUBLIC_EVIDENCE,
            requires_exact_egress_approval=True,
        )
        for name in sorted(EXTERNAL_DISEASE_EVIDENCE_CAPABILITIES)
    ),
]

CAPABILITY_DEFINITIONS: Mapping[str, CapabilityDefinition] = MappingProxyType(
    {definition.name: definition for definition in _DEFINITIONS}
)
if len(CAPABILITY_DEFINITIONS) != len(_DEFINITIONS):  # pragma: no cover - import guard
    raise RuntimeError("GenomiLab capability names must be unique")

CAPABILITY_ALLOWLIST = frozenset(CAPABILITY_DEFINITIONS)


def capability_definition(name: str) -> CapabilityDefinition:
    """Return the canonical definition or reject an unknown capability."""

    try:
        return CAPABILITY_DEFINITIONS[name]
    except KeyError as exc:
        raise ValueError("unsupported investigation capability") from exc


__all__ = [
    "BackgroundJobOwner",
    "CAPABILITY_ALLOWLIST",
    "CAPABILITY_DEFINITIONS",
    "CapabilityDefinition",
    "CapabilityFamily",
    "GENOMI_VARIANT_RESOLVE",
    "PROFILE_PROJECT",
    "PUBLIC_EVIDENCE_RETRIEVE",
    "REGISTER_GAP",
    "REGISTER_HYPOTHESIS",
    "capability_definition",
]
