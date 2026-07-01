from __future__ import annotations

from .. import pgx_requirements
from ._common import JsonObject, _dedupe


def _source_availability(
    *,
    clinpgx_result: JsonObject,
    pgxdb_result: JsonObject,
    fda_result: JsonObject,
    stored_research: JsonObject,
    live_public_evidence_count: int,
    stored_source_evidence_count: int,
) -> JsonObject:
    sources = [
        _source_availability_item(
            source_id="clinpgx",
            result=clinpgx_result,
            evidence_count=(
                int(clinpgx_result.get("summary", {}).get("guideline_annotation_count") or 0)
                + int(clinpgx_result.get("summary", {}).get("clinical_annotation_count") or 0)
                + int(clinpgx_result.get("summary", {}).get("label_annotation_count") or 0)
            ),
        ),
        _source_availability_item(
            source_id="pgxdb",
            result=pgxdb_result,
            evidence_count=(
                int(pgxdb_result.get("summary", {}).get("pgx_record_count") or 0)
                + int(pgxdb_result.get("summary", {}).get("medication_scoped_gene_drug_record_count") or 0)
            ),
        ),
        _source_availability_item(
            source_id="fda_pgx",
            result=fda_result,
            evidence_count=(
                int(fda_result.get("summary", {}).get("biomarker_labeling_count") or 0)
                + int(fda_result.get("summary", {}).get("association_count") or 0)
            ),
        ),
    ]
    unavailable = [source for source in sources if source["availability"] == "unavailable"]
    warnings = [source for source in sources if source["warning_count"]]
    if unavailable and not live_public_evidence_count and not stored_source_evidence_count:
        status = "source_unavailable_no_evidence"
    elif unavailable:
        status = "partial_source_unavailable"
    elif warnings:
        status = "source_evidence_available_with_warnings" if live_public_evidence_count or stored_source_evidence_count else "queried_no_source_evidence_with_warnings"
    elif live_public_evidence_count or stored_source_evidence_count:
        status = "source_evidence_available"
    else:
        status = "queried_no_source_evidence"
    return {
        "status": status,
        "live_public_evidence_count": live_public_evidence_count,
        "stored_source_evidence_count": stored_source_evidence_count,
        "stored_research_status": stored_research.get("status"),
        "sources": sources,
        "unavailable_source_count": len(unavailable),
        "warning_source_count": len(warnings),
    }


def _source_availability_item(*, source_id: str, result: JsonObject, evidence_count: int) -> JsonObject:
    warnings = list(result.get("warnings") or [])
    status = str(result.get("status") or "unknown")
    if status == "source_unavailable":
        availability = "unavailable"
    elif evidence_count and warnings:
        availability = "evidence_available_with_warnings"
    elif warnings:
        availability = "unavailable"
    elif status.startswith("no_matching") or evidence_count == 0:
        availability = "queried_no_records"
    else:
        availability = "evidence_available"
    return {
        "source_id": source_id,
        "status": status,
        "availability": availability,
        "evidence_count": evidence_count,
        "warning_count": len(warnings),
        "raw_call_count": len(result.get("raw_calls") or []),
    }


def _medication_review_status(*, source_evidence_count: int, source_availability: JsonObject) -> str:
    if source_evidence_count:
        return "completed"
    if source_availability.get("status") == "source_unavailable_no_evidence":
        return "source_unavailable"
    return "no_public_pgx_evidence"


def _unanswered_answer_components(*, evidence_components: JsonObject, clinical_context_requested: bool) -> list[JsonObject]:
    unanswered = []
    for item in evidence_components.get("items") or []:
        component_id = str(item.get("id") or "")
        state = str(item.get("state") or "")
        if component_id == "clinical_context" and not clinical_context_requested:
            continue
        if _component_has_evidence(state):
            continue
        unanswered.append(
            {
                "component": component_id,
                "state": state,
                "missing_inputs": list(item.get("missing_inputs") or []),
            }
        )
    return unanswered


def _evidence_state(
    *,
    source_evidence_count: int,
    sample_evidence_count: int,
    live_public_evidence_count: int,
    stored_source_evidence_count: int,
    sample_match_count: int,
    star_marker_match_count: int,
    stored_sample_evidence_count: int,
    known_sample_pgx_evidence_count: int,
    user_sample_evidence_count: int,
    pharmcat_sample_pgx_evidence_count: int,
    technical_support_count: int,
    sequencing_sample_match_count: int,
    source_availability: JsonObject,
    sample_context_requested: bool,
    clinical_context: JsonObject,
    unanswered_answer_components: list[JsonObject],
) -> JsonObject:
    return {
        "has_public_pgx_evidence": bool(source_evidence_count),
        "has_live_public_pgx_evidence": bool(live_public_evidence_count),
        "has_stored_source_evidence": bool(stored_source_evidence_count),
        "has_sample_evidence": bool(sample_evidence_count),
        "has_active_genome_variant_match": bool(sample_match_count),
        "has_star_marker_evidence": bool(star_marker_match_count),
        "has_stored_sample_evidence": bool(stored_sample_evidence_count),
        "has_known_sample_pgx_evidence": bool(known_sample_pgx_evidence_count),
        "has_user_provided_sample_evidence": bool(user_sample_evidence_count),
        "has_pharmcat_sample_pgx_matrix_evidence": bool(pharmcat_sample_pgx_evidence_count),
        "has_genotype_support": bool(technical_support_count),
        "has_sequencing_sample_signal": bool(sequencing_sample_match_count),
        "sample_context_requested": sample_context_requested,
        "source_evidence_count": source_evidence_count,
        "live_public_evidence_count": live_public_evidence_count,
        "stored_source_evidence_count": stored_source_evidence_count,
        "sample_evidence_count": sample_evidence_count,
        "sample_match_count": sample_match_count,
        "star_marker_match_count": star_marker_match_count,
        "stored_sample_evidence_count": stored_sample_evidence_count,
        "known_sample_pgx_evidence_count": known_sample_pgx_evidence_count,
        "user_provided_sample_evidence_count": user_sample_evidence_count,
        "pharmcat_sample_pgx_matrix_evidence_count": pharmcat_sample_pgx_evidence_count,
        "technical_support_count": technical_support_count,
        "sequencing_sample_match_count": sequencing_sample_match_count,
        "source_availability_status": source_availability.get("status"),
        "unresolved_components": unanswered_answer_components,
        "clinical_context_missing": list(clinical_context.get("missing") or []),
        "clinical_boundary": "informational_evidence_review_requires_clinician_or_pharmacist_confirmation",
    }


def _component_has_evidence(state: str) -> bool:
    return state in {
        "present",
        "available",
        "complete",
        "provided",
        "observed",
        "stored",
        "user_provided",
        "known_sample",
        "pharmcat_sample",
        "not_requested",
    }


def _evidence_components(
    *,
    selected_drug: str | None,
    atc_code: str | None,
    drugbank_id: str | None,
    source_evidence_count: int,
    live_public_evidence_count: int,
    stored_source_evidence_count: int,
    sample_match_count: int,
    stored_sample_evidence_count: int,
    known_sample_pgx_evidence_count: int,
    user_sample_evidence_count: int,
    pharmcat_sample_pgx_evidence_count: int,
    technical_support_count: int,
    sequencing_sample_match_count: int,
    active_genome_index_context_available: bool,
    star_marker_match_count: int,
    rsid_targets: list[str],
    star_genes: list[str],
    supported_star_marker_coverage: bool,
    sample_context_requested: bool,
    clinpgx_result: JsonObject,
    pgxdb_result: JsonObject,
    fda_result: JsonObject,
    clinical_context: JsonObject,
) -> JsonObject:
    sample_evidence_count = (
        sample_match_count
        + star_marker_match_count
        + stored_sample_evidence_count
        + known_sample_pgx_evidence_count
    )
    target_ready = bool(selected_drug or atc_code or drugbank_id)
    source_classes = list(clinpgx_result.get("clinical_verification", {}).get("public_evidence_classes") or [])
    if int(pgxdb_result.get("summary", {}).get("pgx_record_count") or 0):
        source_classes.append("pgxdb_pharmacogenomic_association")
    if int(pgxdb_result.get("summary", {}).get("medication_scoped_gene_drug_record_count") or 0):
        source_classes.append("pgxdb_gene_drug_context")
    if int(fda_result.get("summary", {}).get("biomarker_labeling_count") or 0):
        source_classes.append("fda_pharmacogenomic_biomarker_labeling")
    if int(fda_result.get("summary", {}).get("association_count") or 0):
        source_classes.append("fda_pharmacogenetic_association")
    if stored_source_evidence_count:
        source_classes.append("stored_reviewed_pgx_source_evidence")
    if stored_sample_evidence_count:
        source_classes.append("stored_private_sample_pgx_evidence")
    if user_sample_evidence_count:
        source_classes.append("user_provided_sample_pgx_evidence")
    if pharmcat_sample_pgx_evidence_count:
        source_classes.append("pharmcat_sample_pgx_matrix_evidence")
    target_selection_state = "present" if target_ready else "missing"
    public_state = "present" if source_evidence_count else "absent"
    if not sample_context_requested:
        sample_target_state = "not_requested"
    else:
        sample_target_state = "present" if rsid_targets or star_genes else "absent"
    if not sample_context_requested:
        sample_state = "not_requested"
    elif sample_evidence_count or supported_star_marker_coverage:
        sample_state = "present"
    elif rsid_targets or star_genes:
        sample_state = "target_selected_without_sample_evidence"
    else:
        sample_state = "no_sample_target"
    if not sample_context_requested:
        technical_state = "not_requested"
    elif technical_support_count:
        technical_state = "present"
    elif sequencing_sample_match_count:
        technical_state = "sample_signal_without_genotype_support"
    elif sample_match_count:
        technical_state = "observed"
    elif user_sample_evidence_count:
        technical_state = "user_provided"
    elif pharmcat_sample_pgx_evidence_count:
        technical_state = "pharmcat_sample"
    elif known_sample_pgx_evidence_count:
        technical_state = "known_sample"
    else:
        technical_state = "absent"
    broad_state = "not_requested" if not sample_context_requested else "available" if active_genome_index_context_available else "absent"
    outside_call_genes = sorted(gene for gene in star_genes if gene in pgx_requirements.OUTSIDE_CALL_GENES)
    items = [
        {
            "id": "medication_target",
            "state": target_selection_state,
            "evidence": {"drug": selected_drug, "atc_code": atc_code, "drugbank_id": drugbank_id},
            "missing_inputs": [] if target_ready else ["drug", "atc_code", "drugbank_id"],
        },
        {
            "id": "public_pgx_evidence",
            "state": public_state,
            "evidence": {
                "count": source_evidence_count,
                "live_public_evidence_count": live_public_evidence_count,
                "stored_source_evidence_count": stored_source_evidence_count,
                "classes": _dedupe(source_classes),
                "clinpgx_summary": clinpgx_result.get("summary"),
                "pgxdb_summary": pgxdb_result.get("summary"),
                "fda_pgx_summary": fda_result.get("summary"),
            },
            "missing_inputs": [] if source_evidence_count else ["reviewed_public_pgx_source_evidence"],
        },
        {
            "id": "sample_target_selection",
            "state": sample_target_state,
            "evidence": {"rsids": rsid_targets, "genes": star_genes},
            "missing_inputs": [] if sample_target_state in {"present", "not_requested"} else ["rsid", "pharmacogene", "haplotype", "diplotype", "phenotype"],
        },
        {
            "id": "sample_variant_or_marker_evidence",
            "state": sample_state,
            "evidence": {
                "variant_match_count": sample_match_count,
                "star_marker_match_count": star_marker_match_count,
                "stored_sample_evidence_count": stored_sample_evidence_count,
                "known_sample_pgx_evidence_count": known_sample_pgx_evidence_count,
                "user_provided_sample_evidence_count": user_sample_evidence_count,
                "pharmcat_sample_pgx_matrix_evidence_count": pharmcat_sample_pgx_evidence_count,
                "supported_star_marker_coverage": supported_star_marker_coverage,
            },
            "missing_inputs": [] if sample_state in {"present", "not_requested"} else ["sample_variant_or_marker_evidence"],
        },
    ]
    if sample_context_requested and outside_call_genes:
        items.append(
            {
                "id": "specialized_pgx_call_evidence",
                "state": "absent",
                "evidence": {
                    "genes": outside_call_genes,
                    "evidence_type": "outside diplotype, phenotype, or activity-score call",
                },
                "missing_inputs": ["specialized_pgx_caller_output", "outside_call_tsv", "known_diplotype", "known_phenotype"],
            }
        )
    items.extend(
        [
            {
                "id": "technical_sample_support",
                "state": technical_state,
                "evidence": {
                    "technical_support_count": technical_support_count,
                    "sequencing_sample_match_count": sequencing_sample_match_count,
                    "known_sample_pgx_evidence_count": known_sample_pgx_evidence_count,
                    "user_provided_sample_evidence_count": user_sample_evidence_count,
                    "pharmcat_sample_pgx_matrix_evidence_count": pharmcat_sample_pgx_evidence_count,
                },
                "missing_inputs": ["genotype_support"] if technical_state == "sample_signal_without_genotype_support" else [],
            },
            {
                "id": "broad_pgx_call_artifact",
                "state": broad_state,
                "evidence": {"artifact_type": "PharmCAT diplotype, phenotype, and recommendation output", "active_genome_index_context_available": active_genome_index_context_available},
                "missing_inputs": [] if broad_state in {"available", "not_requested"} else ["active_genome_index", "existing_pharmcat_artifact"],
            },
            {
                "id": "clinical_context",
                "state": "provided" if clinical_context.get("status") == "provided" else "partial",
                "evidence": {
                    "provided": clinical_context.get("provided") or {},
                    "missing": clinical_context.get("missing") or [],
                    "needed_context": [
                        "indication",
                        "dose",
                        "current medications",
                        "contraindications",
                        "clinician or pharmacist review",
                    ]
                },
                "missing_inputs": list(clinical_context.get("missing") or []),
            },
        ]
    )
    return {
        "items": items,
        "answer_basis": {
            "public_evidence": public_state,
            "personal_sample_evidence": sample_state,
            "technical_sample_support": technical_state,
            "sample_context_requested": sample_context_requested,
            "clinical_boundary": "informational_evidence_review",
        },
    }
