"""Bounded candidate-gene Active Genome Index capability for GenomiLab."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .genomic_scope import (
    GENE_VARIANT_MATCH_BASIS,
    GENE_VARIANT_MAX_GENES,
    GENE_VARIANT_OPERATION,
    GENE_VARIANT_PER_GENE_LIMIT,
    InvestigationAgiAuthorizationError,
    normalize_candidate_gene_symbols,
)
from .models import JsonObject, compact_json


@dataclass(frozen=True, slots=True)
class CandidateGeneScanCall:
    """One validated Lab request and its core/evidence projections."""

    core_params: JsonObject
    evidence_context: JsonObject


def build_candidate_gene_scan_catalog_entry(
    snapshot: JsonObject,
    investigation: JsonObject,
) -> JsonObject | None:
    """Advertise the scan only for its exact approved policy and live context."""

    scope = snapshot.get("genomic_scope")
    if not isinstance(scope, dict) or scope.get("operation") != GENE_VARIANT_OPERATION:
        return None
    specialist_ids = _specialist_ids(investigation.get("specialist_board"))
    profile_revision_ids = _unique_strings(snapshot.get("observation_revision_ids"))
    evidence_record_ids = _unique_strings(
        [
            record.get("evidence_record_id")
            for record in investigation.get("current_evidence_records") or []
            if isinstance(record, dict)
        ]
    )
    available = bool(
        specialist_ids
        and profile_revision_ids
        and snapshot.get("agi_id")
        and snapshot.get("agi_snapshot_id")
    )
    return {
        "available": available,
        "request_contract": {
            "required_fields": [
                "genes",
                "agi_id",
                "agi_snapshot_id",
                "genome_build",
                "per_gene_limit",
                "candidate_set_lineage",
            ],
            "optional_fields": [],
            "fields": {
                "genes": {
                    "type": "unique_gene_symbol_array",
                    "minimum_items": 1,
                    "maximum_items": GENE_VARIANT_MAX_GENES,
                    "canonical_form": "uppercase_gene_symbol",
                },
                "agi_id": {"fixed_value": snapshot.get("agi_id")},
                "agi_snapshot_id": {
                    "fixed_value": snapshot.get("agi_snapshot_id")
                },
                "genome_build": {"fixed_value": scope.get("genome_build")},
                "per_gene_limit": {
                    "fixed_value": GENE_VARIANT_PER_GENE_LIMIT
                },
                "candidate_set_lineage": {
                    "type": "object",
                    "required_fields": [
                        "specialist_id",
                        "profile_revision_ids",
                        "evidence_record_ids",
                    ],
                    "specialist_id_allowed_values": specialist_ids,
                    "profile_revision_id_allowed_values": profile_revision_ids,
                    "evidence_record_id_allowed_values": evidence_record_ids,
                },
            },
        },
        "scope": {
            "patient_molecular_snapshot_id": snapshot.get(
                "patient_molecular_snapshot_id"
            ),
            "agi_id": snapshot.get("agi_id"),
            "agi_snapshot_id": snapshot.get("agi_snapshot_id"),
            "genome_build": scope.get("genome_build"),
            "gene_count_limit": GENE_VARIANT_MAX_GENES,
            "passing_filters_only": True,
            "per_gene_limit": GENE_VARIANT_PER_GENE_LIMIT,
            "match_basis": GENE_VARIANT_MATCH_BASIS,
        },
        "candidate_set_fingerprint": {
            "algorithm": "sha256",
            "result_field": "candidate_set_sha256",
            "covers": [
                "candidate_genes",
                "candidate_set_lineage",
                "patient_molecular_snapshot_id",
                "agi_id",
                "agi_snapshot_id",
                "genome_build",
            ],
        },
        "execution_boundary": {
            "execution_owner": "main_investigator",
            "specialist_active_genome_index_access": False,
        },
        **(
            {}
            if available
            else {
                "unavailable_reason": (
                    "candidate_gene_scan_requires_persistent_specialist_lineage"
                )
            }
        ),
    }


def validate_candidate_gene_scan_request(
    parameters: object,
    catalog_entry: object,
) -> CandidateGeneScanCall:
    """Bind the actual candidate set to its approved AGI and source lineage."""

    contract = (
        catalog_entry.get("request_contract")
        if isinstance(catalog_entry, dict) and catalog_entry.get("available") is True
        else None
    )
    scope = catalog_entry.get("scope") if isinstance(catalog_entry, dict) else None
    if not isinstance(contract, dict) or not isinstance(scope, dict):
        raise ValueError("candidate-gene scan capability contract is unavailable")
    if not isinstance(parameters, dict):
        raise ValueError("capability parameters must be an object")
    required = set(contract.get("required_fields") or [])
    if set(parameters) != required:
        raise ValueError(
            "candidate-gene scan parameters must match the exact typed contract"
        )
    try:
        genes = normalize_candidate_gene_symbols(parameters.get("genes"))
    except InvestigationAgiAuthorizationError as exc:
        raise ValueError(str(exc)) from exc

    fields = contract.get("fields")
    if not isinstance(fields, dict):
        raise ValueError("candidate-gene scan field contract is unavailable")
    for field in ("agi_id", "agi_snapshot_id", "genome_build", "per_gene_limit"):
        field_contract = fields.get(field)
        fixed_value = (
            field_contract.get("fixed_value")
            if isinstance(field_contract, dict)
            else None
        )
        if parameters.get(field) != fixed_value:
            raise ValueError(
                f"candidate-gene scan {field} does not match the approved context"
            )

    lineage = parameters.get("candidate_set_lineage")
    if not isinstance(lineage, dict) or set(lineage) != {
        "specialist_id",
        "profile_revision_ids",
        "evidence_record_ids",
    }:
        raise ValueError(
            "candidate_set_lineage requires exactly specialist_id, profile_revision_ids, and evidence_record_ids"
        )
    lineage_contract = fields.get("candidate_set_lineage")
    if not isinstance(lineage_contract, dict):
        raise ValueError("candidate-set lineage contract is unavailable")
    specialist_id = str(lineage.get("specialist_id") or "").strip()
    if specialist_id not in set(
        lineage_contract.get("specialist_id_allowed_values") or []
    ):
        raise ValueError(
            "candidate-set lineage must name a persistent investigation specialist"
        )
    profile_ids = _validated_id_selection(
        lineage.get("profile_revision_ids"),
        allowed=lineage_contract.get("profile_revision_id_allowed_values"),
        field="profile_revision_ids",
        non_empty=True,
    )
    evidence_ids = _validated_id_selection(
        lineage.get("evidence_record_ids"),
        allowed=lineage_contract.get("evidence_record_id_allowed_values"),
        field="evidence_record_ids",
        non_empty=False,
    )
    canonical_lineage = {
        "specialist_id": specialist_id,
        "profile_revision_ids": profile_ids,
        "evidence_record_ids": evidence_ids,
    }
    fingerprint_payload = {
        "candidate_genes": genes,
        "candidate_set_lineage": canonical_lineage,
        "patient_molecular_snapshot_id": scope.get(
            "patient_molecular_snapshot_id"
        ),
        "agi_id": scope.get("agi_id"),
        "agi_snapshot_id": scope.get("agi_snapshot_id"),
        "genome_build": scope.get("genome_build"),
    }
    candidate_set_sha256 = hashlib.sha256(
        compact_json(fingerprint_payload).encode("utf-8")
    ).hexdigest()
    return CandidateGeneScanCall(
        core_params={
            "genes": genes,
            "agi_id": str(scope["agi_id"]),
            "genome_build": str(scope["genome_build"]),
            "per_gene_limit": GENE_VARIANT_PER_GENE_LIMIT,
        },
        evidence_context={
            **fingerprint_payload,
            "candidate_set_sha256": candidate_set_sha256,
            "passing_filters_only": True,
            "per_gene_limit": GENE_VARIANT_PER_GENE_LIMIT,
            "match_basis": GENE_VARIANT_MATCH_BASIS,
            "execution_owner": "main_investigator",
            "specialist_active_genome_index_access": False,
        },
    )


def _specialist_ids(value: object) -> list[str]:
    members = value.get("members") if isinstance(value, dict) else None
    if not isinstance(members, list):
        return []
    return sorted(
        _unique_strings(
            [
                item.get("specialist_id")
                for item in members
                if isinstance(item, dict)
            ]
        )
    )


def _unique_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            str(item).strip()
            for item in value
            if isinstance(item, str) and item.strip()
        )
    )


def _validated_id_selection(
    value: object,
    *,
    allowed: object,
    field: str,
    non_empty: bool,
) -> list[str]:
    selected = _unique_strings(value)
    if not isinstance(value, list) or len(selected) != len(value):
        raise ValueError(f"candidate-set lineage {field} must be a unique string array")
    if non_empty and not selected:
        raise ValueError(f"candidate-set lineage {field} must not be empty")
    allowed_values = set(_unique_strings(allowed))
    if not set(selected).issubset(allowed_values):
        raise ValueError(
            f"candidate-set lineage {field} exceeds the approved investigation context"
        )
    return selected


__all__ = [
    "CandidateGeneScanCall",
    "build_candidate_gene_scan_catalog_entry",
    "validate_candidate_gene_scan_request",
]
