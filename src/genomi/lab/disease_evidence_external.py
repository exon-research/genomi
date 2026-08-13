"""Source-specific public-evidence capabilities behind GenomiLab's gateway."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import JsonObject, required_text, validate_private_payload


INHERITANCE_CONSEQUENCE_EVIDENCE = "public_evidence.retrieve_inheritance_consequence"
EXPRESSION_QTL_EVIDENCE = "public_evidence.retrieve_expression_qtl"
PERTURBATION_EVIDENCE = "public_evidence.retrieve_perturbation"
UNIPROT_EVIDENCE = "public_evidence.retrieve_uniprot"
PDB_EVIDENCE = "public_evidence.retrieve_pdb"
BIOMARKER_DRUG_EVIDENCE = "public_evidence.retrieve_biomarker_drug"
REGULATORY_EVIDENCE = "public_evidence.retrieve_regulatory"
TRIAL_EVIDENCE = "public_evidence.retrieve_trial"


@dataclass(frozen=True)
class ExternalEvidenceSpec:
    source_family: str
    source_prior: str
    evidence_domain: str
    operations: tuple[str, ...]


EXTERNAL_EVIDENCE_SPECS: dict[str, ExternalEvidenceSpec] = {
    INHERITANCE_CONSEQUENCE_EVIDENCE: ExternalEvidenceSpec(
        "literature",
        "published_inheritance_and_variant_consequence_reports",
        "inheritance_segregation_and_variant_transcript_consequence",
        ("search", "lookup", "read_extract", "verify_claim"),
    ),
    EXPRESSION_QTL_EVIDENCE: ExternalEvidenceSpec(
        "literature",
        "published_expression_eqtl_sqtl_reports",
        "tissue_cell_expression_eqtl_and_sqtl",
        ("search", "lookup", "read_extract", "verify_claim"),
    ),
    PERTURBATION_EVIDENCE: ExternalEvidenceSpec(
        "literature",
        "published_perturbation_and_screen_reports",
        "perturbation_screen_and_functional_experiment",
        ("search", "lookup", "read_extract", "verify_claim"),
    ),
    UNIPROT_EVIDENCE: ExternalEvidenceSpec(
        "uniprot",
        "curated_uniprot_protein_record",
        "protein_function_isoform_and_feature_annotation",
        ("search", "lookup", "read_extract", "verify_claim"),
    ),
    PDB_EVIDENCE: ExternalEvidenceSpec(
        "pdb",
        "experimental_pdb_structure_record",
        "experimental_protein_structure_context",
        ("search", "lookup", "read_extract"),
    ),
    BIOMARKER_DRUG_EVIDENCE: ExternalEvidenceSpec(
        "chembl",
        "chembl_bioactivity_and_drug_target_record",
        "biomarker_drug_target_and_bioactivity",
        ("search", "lookup", "read_extract", "verify_claim"),
    ),
    REGULATORY_EVIDENCE: ExternalEvidenceSpec(
        "regulatory",
        "dated_regulatory_record",
        "regulatory_status_and_approved_indication_evidence",
        ("search", "lookup", "read_extract", "verify_claim"),
    ),
    TRIAL_EVIDENCE: ExternalEvidenceSpec(
        "trial_registry",
        "trial_registration_not_trial_result",
        "trial_possibility_and_registered_eligibility_fields",
        ("search", "lookup", "read_extract"),
    ),
}
EXTERNAL_DISEASE_EVIDENCE_CAPABILITIES = frozenset(EXTERNAL_EVIDENCE_SPECS)

_RAW_SEQUENCE = re.compile(r"(?<![A-Za-z])[ACGTUN]{30,}(?![A-Za-z])", re.I)
_RAW_PROTEIN_SEQUENCE = re.compile(
    r"(?<![A-Za-z])[ACDEFGHIKLMNPQRSTVWY]{40,}(?![A-Za-z])"
)
_PRIVATE_PATH_OR_ID = re.compile(
    r"(?:file://|/(?:Users|home|private|var|tmp)/|"
    r"\.(?:vcf|gvcf|bam|cram|fastq)(?:\.gz)?\b|"
    r"(?:observation-revision|molecular-snapshot|consent|agi-snapshot)-[a-z0-9-]+)",
    re.I,
)


def build_external_evidence_catalog(
    profile_revision_ids: object,
    evidence_manifest: object,
) -> JsonObject:
    """Declare every source prior and whether a configured route can serve it."""

    anchors = _text_array(profile_revision_ids, "profile_revision_ids")
    routed_families = _routed_source_families(evidence_manifest)
    catalog: JsonObject = {}
    for capability, spec in EXTERNAL_EVIDENCE_SPECS.items():
        route_available = spec.source_family in routed_families
        catalog[capability] = {
            "available": bool(anchors and route_available),
            "request_contract": {
                "required_fields": [
                    "profile_revision_ids",
                    "operation",
                    "query",
                    "query_terms",
                    "filters",
                    "purpose",
                ],
                "optional_fields": [],
                "fields": {
                    "profile_revision_ids": {
                        "type": "unique_string_array",
                        "minimum_items": 1,
                        "allowed_values": anchors,
                    },
                    "operation": {
                        "type": "string",
                        "allowed_values": list(spec.operations),
                    },
                    "query": {
                        "type": "public_biomedical_string",
                        "maximum_length": 4_000,
                    },
                    "query_terms": {
                        "type": "unique_public_biomedical_string_array",
                        "minimum_items": 1,
                        "item_maximum_length": 1_000,
                    },
                    "filters": {
                        "type": "public_string_map",
                        "reserved_fields": ["evidence_domain"],
                    },
                    "purpose": {
                        "type": "investigation_purpose_string",
                        "maximum_length": 500,
                    },
                },
            },
            "fixed_source_family": spec.source_family,
            "evidence_domain": spec.evidence_domain,
            "source_prior": spec.source_prior,
            **(
                {}
                if route_available
                else {"unavailable_reason": "no_authorized_or_fixture_source_route"}
            ),
        }
    return catalog


def validate_external_evidence_request(
    capability: str,
    parameters: object,
    catalog_entry: object,
) -> JsonObject:
    """Return the provider payload after removing local-only patient anchors."""

    spec = EXTERNAL_EVIDENCE_SPECS.get(capability)
    if spec is None:
        raise ValueError("unsupported external disease-evidence capability")
    if not isinstance(parameters, dict):
        raise ValueError("capability parameters must be an object")
    contract = (
        catalog_entry.get("request_contract")
        if isinstance(catalog_entry, dict) and catalog_entry.get("available") is True
        else None
    )
    if not isinstance(contract, dict):
        raise ValueError("external disease-evidence capability is unavailable")
    _validate_request_fields(parameters, contract)
    validate_private_payload(parameters)
    anchors = _text_array(
        parameters.get("profile_revision_ids"), "profile_revision_ids"
    )
    eligible = set(_field_allowed_values(contract, "profile_revision_ids"))
    if not anchors or not set(anchors).issubset(eligible):
        raise ValueError("profile anchors must belong to the approved pinned snapshot")
    operation = required_text(parameters.get("operation"), "operation", 100)
    allowed_operations = _field_allowed_values(contract, "operation")
    if operation not in allowed_operations or operation not in spec.operations:
        raise ValueError("operation is not allowed for this public source prior")
    query = _safe_egress_text(parameters.get("query"), "query", 4_000)
    terms = _text_array(parameters.get("query_terms"), "query_terms")
    if not terms:
        raise ValueError("query_terms cannot be empty")
    safe_terms = [_safe_egress_text(term, "query_term", 1_000) for term in terms]
    filters = _public_filters(parameters.get("filters"))
    purpose = _safe_egress_text(parameters.get("purpose"), "purpose", 500)
    return {
        "operation": operation,
        "query": query,
        "query_terms": safe_terms,
        "filters": {
            **filters,
            "evidence_domain": spec.evidence_domain,
        },
        "source_family": spec.source_family,
        "purpose": purpose,
    }


def _routed_source_families(manifest: object) -> set[str]:
    if not isinstance(manifest, dict):
        return set()
    routed = {
        str(item)
        for item in manifest.get("fixture_source_families") or []
        if isinstance(item, str)
    }
    for route in manifest.get("direct_sources") or []:
        if isinstance(route, dict) and isinstance(route.get("source_family"), str):
            routed.add(str(route["source_family"]))
    paperclip = manifest.get("paperclip")
    if isinstance(paperclip, dict) and paperclip.get("live_state") == "authorized":
        # Provider policy still evaluates the exact family at call time.  The
        # catalog advertises the route; a deployment-scope mismatch fails closed.
        routed.update(spec.source_family for spec in EXTERNAL_EVIDENCE_SPECS.values())
    return routed


def _public_filters(value: object) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError("filters must be an object")
    result: JsonObject = {}
    for raw_key, raw_value in value.items():
        key = required_text(raw_key, "filter name", 100)
        if key == "evidence_domain":
            raise ValueError("evidence_domain is fixed by the capability")
        result[key] = _safe_egress_text(raw_value, f"filters.{key}", 1_000)
    return result


def _safe_egress_text(value: object, field: str, maximum: int) -> str:
    text = required_text(value, field, maximum)
    if _RAW_SEQUENCE.search(text):
        raise ValueError(f"{field} cannot contain raw nucleotide sequence")
    if _RAW_PROTEIN_SEQUENCE.search(text):
        raise ValueError(f"{field} cannot contain raw protein sequence")
    if _PRIVATE_PATH_OR_ID.search(text):
        raise ValueError(
            f"{field} cannot contain local paths or private record identifiers"
        )
    return text


def _text_array(value: object, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be an array")
    result = [required_text(item, field, 1_000) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f"{field} cannot contain duplicates")
    return result


def _validate_request_fields(parameters: JsonObject, contract: JsonObject) -> None:
    required = contract.get("required_fields")
    optional = contract.get("optional_fields")
    if not isinstance(required, list) or not isinstance(optional, list):
        raise ValueError("external disease-evidence request contract is malformed")
    allowed = {*required, *optional}
    if not set(required).issubset(parameters) or not set(parameters).issubset(allowed):
        raise ValueError(
            "external disease-evidence request fields do not match the typed contract"
        )


def _field_allowed_values(contract: JsonObject, field: str) -> list[str]:
    fields = contract.get("fields")
    field_contract = fields.get(field) if isinstance(fields, dict) else None
    allowed = (
        field_contract.get("allowed_values")
        if isinstance(field_contract, dict)
        else None
    )
    if not isinstance(allowed, list):
        raise ValueError(f"{field} allowed values are unavailable")
    return _text_array(allowed, field)


__all__ = [
    "BIOMARKER_DRUG_EVIDENCE",
    "EXPRESSION_QTL_EVIDENCE",
    "EXTERNAL_DISEASE_EVIDENCE_CAPABILITIES",
    "EXTERNAL_EVIDENCE_SPECS",
    "INHERITANCE_CONSEQUENCE_EVIDENCE",
    "PDB_EVIDENCE",
    "PERTURBATION_EVIDENCE",
    "REGULATORY_EVIDENCE",
    "TRIAL_EVIDENCE",
    "UNIPROT_EVIDENCE",
    "build_external_evidence_catalog",
    "validate_external_evidence_request",
]
