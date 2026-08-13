"""Approved-profile projection for local disease-evidence capabilities."""

from __future__ import annotations

import re
from typing import Any

from .models import JsonObject


PHENOTYPE_NORMALIZE = "genomi.phenotype.normalize_terms"
GENE_DISEASE_ASSOCIATIONS = "genomi.phenotype.retrieve_gene_disease_associations"
PHENOTYPE_GENE_COMPARE = "genomi.phenotype.compare_gene_hpo_evidence"
PATHWAY_MEMBERS = "genomi.pathway.retrieve_members"

LOCAL_DISEASE_EVIDENCE_CAPABILITIES = frozenset(
    {
        PHENOTYPE_NORMALIZE,
        GENE_DISEASE_ASSOCIATIONS,
        PHENOTYPE_GENE_COMPARE,
        PATHWAY_MEMBERS,
    }
)
GENCC_CLASSIFICATIONS = ("Definitive", "Strong")

PUBLIC_EVIDENCE_SOURCE_PRIORS: JsonObject = {
    "literature": {
        "prior": "published_or_prepublication_document_evidence",
        "supports": [
            "disease_mechanism",
            "inheritance_or_segregation_report",
            "variant_or_transcript_consequence_report",
            "expression_or_qtl_report",
            "pathway_or_perturbation_report",
            "protein_function_report",
            "biomarker_or_drug_report",
        ],
    },
    "regulatory": {
        "prior": "dated_regulatory_record",
        "supports": ["regulatory_status", "approved_indication_evidence"],
    },
    "trial_registry": {
        "prior": "trial_registration_not_trial_result",
        "supports": ["trial_possibility", "registered_eligibility_fields"],
    },
    "uniprot": {
        "prior": "curated_protein_record",
        "supports": ["protein_function", "isoform_and_feature_annotation"],
    },
    "pdb": {
        "prior": "experimental_structure_record",
        "supports": ["protein_structure_context"],
    },
    "chembl": {
        "prior": "bioactivity_and_drug_target_record",
        "supports": ["drug_target", "bioactivity", "biomarker_context"],
    },
}

_REVIEWED_STATES = frozenset(
    {"user_confirmed", "record_confirmed", "clinician_confirmed"}
)
_PHENOTYPE_MODALITIES = frozenset({"condition", "phenotype"})


def build_local_disease_evidence_catalog(profile: object) -> JsonObject:
    """Build executable request contracts from one approved profile slice."""

    observations = (
        profile.get("observations")
        if isinstance(profile, dict) and isinstance(profile.get("observations"), list)
        else []
    )
    anchors: list[JsonObject] = []
    for raw in observations:
        if not isinstance(raw, dict):
            continue
        revision_id = _clean(raw.get("observation_revision_id"))
        if (
            not revision_id
            or raw.get("verification_state") not in _REVIEWED_STATES
            or raw.get("assertion_status") != "present"
        ):
            continue
        modality = _clean(raw.get("modality"))
        phenotype = (
            _clean(raw.get("original_wording") or raw.get("label"))
            if modality in _PHENOTYPE_MODALITIES
            else ""
        )
        normalized_code = _clean(raw.get("normalized_code")).upper()
        hpo_id = (
            normalized_code if re.fullmatch(r"HP:[0-9]{7}", normalized_code) else ""
        )
        gene = _clean(raw.get("gene")).upper()
        anchors.append(
            {
                "profile_revision_id": revision_id,
                "modality": modality,
                **({"phenotype": phenotype} if phenotype else {}),
                **({"hpo_id": hpo_id} if hpo_id else {}),
                **({"gene": gene} if gene else {}),
            }
        )

    phenotype_anchors = [
        anchor for anchor in anchors if anchor.get("phenotype") or anchor.get("hpo_id")
    ]
    gene_anchors = [anchor for anchor in anchors if anchor.get("gene")]
    all_ids = [str(anchor["profile_revision_id"]) for anchor in anchors]
    phenotype_ids = [str(anchor["profile_revision_id"]) for anchor in phenotype_anchors]
    gene_ids = [str(anchor["profile_revision_id"]) for anchor in gene_anchors]
    phenotype_values = _unique(
        str(anchor["phenotype"])
        for anchor in phenotype_anchors
        if anchor.get("phenotype")
    )
    hpo_ids = _unique(
        str(anchor["hpo_id"]) for anchor in phenotype_anchors if anchor.get("hpo_id")
    )
    genes = _unique(
        str(anchor["gene"]) for anchor in gene_anchors if anchor.get("gene")
    )

    return {
        PHENOTYPE_NORMALIZE: {
            "available": bool(phenotype_anchors),
            "request_contract": _request_contract(
                ["profile_revision_ids", "phenotypes", "hpo_ids"],
                {
                    "profile_revision_ids": _allowed_array(
                        phenotype_ids, non_empty=True
                    ),
                    "phenotypes": _allowed_array(phenotype_values),
                    "hpo_ids": _allowed_array(hpo_ids),
                },
                selection_bindings=phenotype_anchors,
                cross_field_requirements=[
                    {"at_least_one_non_empty": ["phenotypes", "hpo_ids"]}
                ],
            ),
            "source_prior": "profile_terms_for_local_hpo_normalization",
        },
        GENE_DISEASE_ASSOCIATIONS: {
            "available": bool(gene_anchors),
            "request_contract": _request_contract(
                ["profile_revision_ids", "genes", "classifications", "limit"],
                {
                    "profile_revision_ids": _allowed_array(gene_ids, non_empty=True),
                    "genes": _allowed_array(genes, non_empty=True),
                    "classifications": _allowed_array(
                        list(GENCC_CLASSIFICATIONS), non_empty=True
                    ),
                    "limit": _integer_contract(1, 100, suggested=25),
                },
                selection_bindings=gene_anchors,
            ),
            "source_prior": "gencc_gene_disease_validity",
        },
        PHENOTYPE_GENE_COMPARE: {
            "available": bool(phenotype_anchors and gene_anchors),
            "request_contract": _request_contract(
                [
                    "profile_revision_ids",
                    "phenotypes",
                    "hpo_ids",
                    "genes",
                    "limit",
                ],
                {
                    "profile_revision_ids": _allowed_array(
                        _unique([*phenotype_ids, *gene_ids]), non_empty=True
                    ),
                    "phenotypes": _allowed_array(phenotype_values),
                    "hpo_ids": _allowed_array(hpo_ids),
                    "genes": _allowed_array(genes, non_empty=True),
                    "limit": _integer_contract(1, 100, suggested=25),
                },
                selection_bindings=_anchors_by_revision(
                    [*phenotype_anchors, *gene_anchors]
                ),
                cross_field_requirements=[
                    {"at_least_one_non_empty": ["phenotypes", "hpo_ids"]},
                    {"non_empty": ["genes"]},
                ],
            ),
            "source_prior": "hpo_gene_annotation",
        },
        PATHWAY_MEMBERS: {
            "available": bool(all_ids),
            "request_contract": _request_contract(
                ["profile_revision_ids", "pathway_id_or_name", "source", "limit"],
                {
                    "profile_revision_ids": _allowed_array(all_ids, non_empty=True),
                    "pathway_id_or_name": {
                        "type": "string",
                        "pattern": "^HALLMARK_[A-Z0-9_]+$",
                    },
                    "source": {
                        "type": "string",
                        "fixed_value": "msigdb_hallmark",
                    },
                    "limit": _integer_contract(1, 500, suggested=100),
                },
            ),
            "source_prior": "msigdb_hallmark_membership",
        },
    }


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _unique(values: Any) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _anchors_by_revision(anchors: list[JsonObject]) -> list[JsonObject]:
    merged: dict[str, JsonObject] = {}
    for anchor in anchors:
        revision_id = str(anchor["profile_revision_id"])
        merged.setdefault(revision_id, {}).update(anchor)
    return list(merged.values())


def _request_contract(
    required_fields: list[str],
    fields: JsonObject,
    *,
    selection_bindings: list[JsonObject] | None = None,
    cross_field_requirements: list[JsonObject] | None = None,
) -> JsonObject:
    contract: JsonObject = {
        "required_fields": list(required_fields),
        "optional_fields": [],
        "fields": fields,
    }
    if selection_bindings is not None:
        contract["selection_bindings"] = selection_bindings
    if cross_field_requirements is not None:
        contract["cross_field_requirements"] = cross_field_requirements
    return contract


def _allowed_array(values: list[str], *, non_empty: bool = False) -> JsonObject:
    return {
        "type": "unique_string_array",
        "minimum_items": 1 if non_empty else 0,
        "allowed_values": list(values),
    }


def _integer_contract(minimum: int, maximum: int, *, suggested: int) -> JsonObject:
    return {
        "type": "integer",
        "minimum": minimum,
        "maximum": maximum,
        "suggested_value": suggested,
    }


__all__ = [
    "GENCC_CLASSIFICATIONS",
    "GENE_DISEASE_ASSOCIATIONS",
    "LOCAL_DISEASE_EVIDENCE_CAPABILITIES",
    "PATHWAY_MEMBERS",
    "PHENOTYPE_GENE_COMPARE",
    "PHENOTYPE_NORMALIZE",
    "PUBLIC_EVIDENCE_SOURCE_PRIORS",
    "build_local_disease_evidence_catalog",
]
