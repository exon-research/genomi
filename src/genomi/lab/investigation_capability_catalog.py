"""Catalog projection from one approved investigation context."""

from __future__ import annotations

from typing import Protocol

from .candidate_gene_capability import build_candidate_gene_scan_catalog_entry
from .capability_registry import (
    GENOMI_VARIANT_FIND_GENE_VARIANTS,
    GENOMI_VARIANT_RESOLVE,
    PROFILE_PROJECT,
    PUBLIC_EVIDENCE_RETRIEVE,
    REGISTER_GAP,
    REGISTER_HYPOTHESIS,
    capability_definition,
)
from .disease_evidence_capabilities import (
    PUBLIC_EVIDENCE_SOURCE_PRIORS,
    build_local_disease_evidence_catalog,
)
from .disease_evidence_external import (
    build_external_evidence_catalog,
    external_evidence_route_available,
)
from .disease_relation_contract import (
    REGISTER_DISEASE_RELATION,
    disease_relation_parameter_contract,
    eligible_public_context_source,
    eligible_public_relation_source,
    supporting_relation_anchor_ids,
)
from .hypothesis_contract import (
    GAP_KINDS,
    build_case_narrative_contract,
    case_anchor_terms,
    case_narrative_schema_metadata,
)
from .investigation_capability_support import (
    _disease_relation_request_templates,
    _exact_variant_parameters,
    _usable_personal_genome_evidence_ids,
)
from .models import JsonObject


class ProfileSnapshotStore(Protocol):
    def get_profile_snapshot(self, snapshot_id: str) -> JsonObject: ...


class CapabilityCatalogApplication(Protocol):
    store: ProfileSnapshotStore

    def investigation(self, investigation_id: str) -> JsonObject: ...
    def investigation_profile(self, investigation_id: str) -> JsonObject: ...
    def evidence_capability_manifest(self) -> JsonObject: ...


def build_investigation_capability_catalog(
    application: CapabilityCatalogApplication, investigation_id: str
) -> JsonObject:
    investigation = application.investigation(investigation_id)
    disease_scope = str(
        investigation.get("disease_scope") or investigation.get("question") or ""
    ).strip()
    candidate_relation_anchors = [
        {
            "evidence_record_id": str(record["evidence_record_id"]),
            "profile_revision_ids": anchors,
        }
        for record in investigation.get("current_evidence_records") or []
        if isinstance(record, dict)
        and isinstance(record.get("evidence_record_id"), str)
        and (
            anchors := supporting_relation_anchor_ids(
                record, disease_scope=disease_scope
            )
        )
        is not None
    ]
    personal_genome_evidence_ids = _usable_personal_genome_evidence_ids(
        investigation.get("current_evidence_records")
    )
    current_evidence_ids = [
        str(record["evidence_record_id"])
        for record in investigation.get("current_evidence_records") or []
        if isinstance(record, dict)
        and isinstance(record.get("evidence_record_id"), str)
        and record["evidence_record_id"]
    ]
    snapshot_id = investigation.get("patient_molecular_snapshot_id")
    snapshot = (
        application.store.get_profile_snapshot(str(snapshot_id))
        if snapshot_id
        else None
    )
    molecular_profile = (
        application.investigation_profile(investigation_id)
        if snapshot_id
        else {}
    )
    profile_revision_ids = [
        str(value)
        for value in (snapshot or {}).get("observation_revision_ids") or []
        if isinstance(value, str) and value
    ]
    case_narrative_contract = build_case_narrative_contract(
        disease_scope=investigation.get("disease_scope"),
        molecular_profile=molecular_profile,
        evidence_records=investigation.get("current_evidence_records") or [],
    )
    statement_contract = case_narrative_schema_metadata(case_narrative_contract)
    has_case_narrative_anchor = bool(statement_contract.get("anchors"))
    hypothesis_kinds = ["working_hypothesis", "counterevidence", "uncertainty"]
    if candidate_relation_anchors:
        hypothesis_kinds.insert(0, "candidate_mechanism")
    evidence_manifest = application.evidence_capability_manifest()
    public_evidence_parameters: JsonObject = {
        "operation": "search",
        "query": disease_scope,
        "query_terms": [disease_scope],
        "filters": {},
        "source_family": "literature",
        "purpose": (
            "Investigate disease relevance against the approved molecular profile"
        ),
    }
    public_evidence_available = external_evidence_route_available(
        evidence_manifest,
        **public_evidence_parameters,
    )
    catalog: JsonObject = {
        PROFILE_PROJECT: {
            "available": bool(investigation.get("patient_molecular_snapshot_id")),
            "parameters": {},
        },
        PUBLIC_EVIDENCE_RETRIEVE: {
            "available": public_evidence_available,
            "parameters": public_evidence_parameters,
            "source_capabilities": evidence_manifest,
            "source_priors": PUBLIC_EVIDENCE_SOURCE_PRIORS,
            **(
                {}
                if public_evidence_available
                else {"unavailable_reason": "no_route_accepts_exact_public_request"}
            ),
        },
        REGISTER_DISEASE_RELATION: {
            "available": any(
                eligible_public_context_source(record)
                for record in investigation.get("current_evidence_records") or []
                if isinstance(record, dict)
            )
            and bool(investigation.get("patient_molecular_snapshot_id")),
            "parameters": {
                **disease_relation_parameter_contract(),
                "disease_scope": investigation.get("disease_scope")
                or investigation.get("question"),
                "eligible_source_evidence_record_ids": [
                    str(record["evidence_record_id"])
                    for record in investigation.get("current_evidence_records") or []
                    if isinstance(record, dict)
                    and isinstance(record.get("evidence_record_id"), str)
                    and eligible_public_relation_source(record)
                ],
                "eligible_context_source_evidence_record_ids": [
                    str(record["evidence_record_id"])
                    for record in investigation.get("current_evidence_records") or []
                    if isinstance(record, dict)
                    and isinstance(record.get("evidence_record_id"), str)
                    and eligible_public_context_source(record)
                ],
                "eligible_profile_revision_ids": [],
            },
        },
        REGISTER_HYPOTHESIS: {
            "available": has_case_narrative_anchor
            and bool(profile_revision_ids or current_evidence_ids),
            "request_contract": {
                "required_fields": [
                    "kind",
                    "statement",
                    "evidence_record_ids",
                    "profile_revision_ids",
                    "status",
                ],
                "optional_fields": ["supersedes_hypothesis_id"],
                "allowed_kind_values": hypothesis_kinds,
                "allowed_status_values": [
                    "candidate",
                    "supported",
                    "weakened",
                    "rejected",
                ],
                "fields": {
                    "statement": statement_contract,
                    "evidence_record_ids": {
                        "type": "unique_string_array",
                        "allowed_values": current_evidence_ids,
                    },
                    "profile_revision_ids": {
                        "type": "unique_string_array",
                        "allowed_values": profile_revision_ids,
                    },
                },
                "narrative_kind_by_kind": {
                    "working_hypothesis": "hypothesis_working",
                    "candidate_mechanism": "hypothesis_candidate_mechanism",
                    "counterevidence": "hypothesis_counterevidence",
                    "uncertainty": "hypothesis_uncertainty",
                },
                "cross_field_requirements": [
                    {
                        "at_least_one_non_empty": [
                            "evidence_record_ids",
                            "profile_revision_ids",
                        ]
                    },
                    {
                        "when": {"kind": ["working_hypothesis"]},
                        "require_empty": ["evidence_record_ids"],
                        "require_non_empty": ["profile_revision_ids"],
                    },
                    {
                        "when": {
                            "kind": [
                                "candidate_mechanism",
                                "counterevidence",
                            ]
                        },
                        "require_non_empty": [
                            "evidence_record_ids",
                            "profile_revision_ids",
                        ],
                    },
                ],
            },
            "candidate_mechanism_relation_anchors": candidate_relation_anchors,
            "anchored_request_cases": [
                {
                    "kind": "candidate_mechanism",
                    "evidence_record_ids": [
                        *personal_genome_evidence_ids,
                        anchor["evidence_record_id"],
                    ],
                    "profile_revision_ids": list(anchor["profile_revision_ids"]),
                    "status": "candidate",
                }
                for anchor in candidate_relation_anchors
                if case_anchor_terms(
                    statement_contract,
                    profile_revision_ids=anchor["profile_revision_ids"],
                    evidence_record_ids=[
                        *personal_genome_evidence_ids,
                        anchor["evidence_record_id"],
                    ],
                )
            ]
            + [
                {
                    "kind": "working_hypothesis",
                    "evidence_record_ids": [],
                    "profile_revision_ids": [profile_revision_id],
                    "status": "candidate",
                }
                for profile_revision_id in profile_revision_ids
                if case_anchor_terms(
                    statement_contract,
                    profile_revision_ids=[profile_revision_id],
                    evidence_record_ids=[],
                )
            ]
            if has_case_narrative_anchor
            else [],
            **(
                {}
                if has_case_narrative_anchor
                else {"unavailable_reason": "no_eligible_case_narrative_anchor"}
            ),
        },
        REGISTER_GAP: {
            "available": bool(investigation.get("patient_molecular_snapshot_id"))
            and has_case_narrative_anchor,
            "request_contract": {
                "required_fields": [
                    "kind",
                    "statement",
                    "evidence_record_ids",
                    "profile_revision_ids",
                    "status",
                ],
                "optional_fields": ["supersedes_hypothesis_id"],
                "allowed_kind_values": sorted(GAP_KINDS),
                "allowed_status_values": ["open", "resolved"],
                "fields": {
                    "statement": statement_contract,
                    "evidence_record_ids": {
                        "type": "unique_string_array",
                        "allowed_values": current_evidence_ids,
                    },
                    "profile_revision_ids": {
                        "type": "unique_string_array",
                        "allowed_values": profile_revision_ids,
                    },
                },
                "narrative_kind_by_kind": {
                    "evidence_gap": "hypothesis_gap",
                    "confirmation_requirement": "hypothesis_gap",
                },
                "cross_field_requirements": [
                    {
                        "at_least_one_non_empty": [
                            "evidence_record_ids",
                            "profile_revision_ids",
                        ]
                    }
                ],
            },
            "anchored_request_cases": [
                {
                    "kind": "confirmation_requirement",
                    "evidence_record_ids": [
                        *personal_genome_evidence_ids,
                        anchor["evidence_record_id"],
                    ],
                    "profile_revision_ids": list(anchor["profile_revision_ids"]),
                    "status": "open",
                }
                for anchor in candidate_relation_anchors
                if case_anchor_terms(
                    statement_contract,
                    profile_revision_ids=anchor["profile_revision_ids"],
                    evidence_record_ids=[
                        *personal_genome_evidence_ids,
                        anchor["evidence_record_id"],
                    ],
                )
            ]
            if has_case_narrative_anchor
            else [],
            **(
                {}
                if has_case_narrative_anchor
                else {"unavailable_reason": "no_eligible_case_narrative_anchor"}
            ),
        },
    }
    if snapshot_id:
        relation_entry = catalog[REGISTER_DISEASE_RELATION]
        relation_parameters = relation_entry.get("parameters")
        if isinstance(relation_parameters, dict):
            relation_parameters["eligible_profile_revision_ids"] = list(
                snapshot.get("observation_revision_ids") or []
            )
            relation_entry["exact_request_templates"] = (
                _disease_relation_request_templates(
                    disease_scope=disease_scope,
                    molecular_profile=molecular_profile,
                    relation_source_evidence_record_ids=relation_parameters[
                        "eligible_source_evidence_record_ids"
                    ],
                    context_source_evidence_record_ids=relation_parameters[
                        "eligible_context_source_evidence_record_ids"
                    ],
                    source_family_by_evidence_record_id={
                        str(record["evidence_record_id"]): str(
                            record.get("source_family") or ""
                        )
                        for record in investigation.get("current_evidence_records")
                        or []
                        if isinstance(record, dict)
                        and isinstance(record.get("evidence_record_id"), str)
                    },
                )
            )
            relation_entry["available"] = bool(
                relation_entry["exact_request_templates"]
            )
        scope = (snapshot or {}).get("genomic_scope")
        variant_parameters = _exact_variant_parameters(scope)
        if variant_parameters is not None:
            catalog[GENOMI_VARIANT_RESOLVE] = {
                "available": True,
                "parameters": variant_parameters,
            }
        candidate_gene_entry = build_candidate_gene_scan_catalog_entry(
            snapshot or {}, investigation
        )
        if candidate_gene_entry is not None:
            catalog[GENOMI_VARIANT_FIND_GENE_VARIANTS] = candidate_gene_entry
        catalog.update(build_local_disease_evidence_catalog(molecular_profile))
        catalog.update(
            build_external_evidence_catalog(
                snapshot.get("observation_revision_ids") or [],
                application.evidence_capability_manifest(),
            )
        )
    for capability, entry in catalog.items():
        if isinstance(entry, dict):
            entry["privacy"] = capability_definition(capability).privacy
    return catalog
