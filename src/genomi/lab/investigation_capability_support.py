"""Pure projections and templates used by investigation capabilities."""

from __future__ import annotations

from .genomic_scope import INVESTIGATION_VARIANT_PARAMETER_FIELDS
from .disease_relation_contract import relation_kind_accepts_source_family
from .models import JsonObject, compact_json


def _usable_personal_genome_evidence_ids(value: object) -> list[str]:
    """Return patient-genome records that can participate in a candidate chain."""

    if not isinstance(value, list):
        return []
    usable_readiness = {
        "answer_supported",
        "scoped_answer_only",
        "needs_clinical_confirmation",
    }
    identifiers: list[str] = []
    for record in value:
        if not isinstance(record, dict) or record.get("source_family") != (
            "personal_genome"
        ):
            continue
        evidence_record_id = record.get("evidence_record_id")
        envelope = record.get("evidence_envelope")
        if (
            isinstance(evidence_record_id, str)
            and isinstance(envelope, dict)
            and envelope.get("finding_state") == "evidence_present"
            and envelope.get("answer_readiness") in usable_readiness
        ):
            identifiers.append(evidence_record_id)
    return list(dict.fromkeys(identifiers))


def _disease_relation_request_templates(
    *,
    disease_scope: str,
    molecular_profile: object,
    relation_source_evidence_record_ids: object,
    context_source_evidence_record_ids: object,
    source_family_by_evidence_record_id: object,
) -> list[JsonObject]:
    """Enumerate exact relation shapes while leaving direction to the harness."""

    relation_anchors = _molecular_relation_anchors(molecular_profile)
    relation_source_ids = _text_list(relation_source_evidence_record_ids)
    context_source_ids = _text_list(context_source_evidence_record_ids)
    source_families = (
        source_family_by_evidence_record_id
        if isinstance(source_family_by_evidence_record_id, dict)
        else {}
    )
    if not disease_scope or not relation_anchors or not context_source_ids:
        return []

    templates: list[JsonObject] = []
    for relation_anchor in relation_anchors:
        for source_id in relation_source_ids:
            for direction, uncertainty in (
                (
                    "supports",
                    [
                        "association_not_causation",
                        "clinical_significance_not_established",
                    ],
                ),
                ("refutes", ["clinical_significance_not_established"]),
                (
                    "mixed",
                    [
                        "conflicting_evidence",
                        "clinical_significance_not_established",
                    ],
                ),
            ):
                if not relation_kind_accepts_source_family(
                    relation_anchor["relation_kind"],
                    source_families.get(source_id),
                    direction=direction,
                ):
                    continue
                templates.append(
                    _disease_relation_request_template(
                        disease_scope=disease_scope,
                        profile_revision_ids=relation_anchor["profile_revision_ids"],
                        source_evidence_record_id=source_id,
                        relation_kind=relation_anchor["relation_kind"],
                        direction=direction,
                        uncertainty=uncertainty,
                    )
                )
        for source_id in context_source_ids:
            if not relation_kind_accepts_source_family(
                relation_anchor["relation_kind"],
                source_families.get(source_id),
                direction="context_only",
            ):
                continue
            templates.append(
                _disease_relation_request_template(
                    disease_scope=disease_scope,
                    profile_revision_ids=relation_anchor["profile_revision_ids"],
                    source_evidence_record_id=source_id,
                    relation_kind=relation_anchor["relation_kind"],
                    direction="context_only",
                    uncertainty=[
                        "source_not_reported",
                        "mechanism_not_established",
                        "clinical_significance_not_established",
                    ],
                )
            )
    return templates


def _is_exact_hypothesis_template_case(
    parameters: JsonObject, template: JsonObject
) -> bool:
    """Identify the one canned request shape that requires canned narrative."""

    if "supersedes_hypothesis_id" in parameters:
        return False
    discriminator_fields = (
        "kind",
        "evidence_record_ids",
        "profile_revision_ids",
        "status",
    )
    return all(
        compact_json(parameters.get(field)) == compact_json(template.get(field))
        for field in discriminator_fields
    )


def _disease_relation_request_template(
    *,
    disease_scope: str,
    profile_revision_ids: list[str],
    source_evidence_record_id: str,
    relation_kind: str,
    direction: str,
    uncertainty: list[str],
) -> JsonObject:
    unreported_context = {
        "state": "not_reported",
        "description": None,
        "source_locator": None,
    }
    return {
        "disease_scope": disease_scope,
        "profile_revision_ids": list(profile_revision_ids),
        "source_evidence_record_ids": [source_evidence_record_id],
        "relation_kind": relation_kind,
        "direction": direction,
        "source_supplied_strength": {
            "state": "not_reported",
            "scheme": None,
            "raw_label": None,
            "raw_value": None,
            "source_locator": None,
        },
        "population_context": dict(unreported_context),
        "tissue_context": dict(unreported_context),
        "specimen_context": dict(unreported_context),
        "conflicts": [],
        "uncertainty": list(uncertainty),
    }


def _molecular_relation_anchors(molecular_profile: object) -> list[JsonObject]:
    if not isinstance(molecular_profile, dict):
        return []
    observations = molecular_profile.get("observations")
    if not isinstance(observations, list):
        return []
    relation_kind_by_modality = {
        "reported_germline_finding": "variant_disease",
        "reported_somatic_finding": "variant_disease",
        "biomarker": "molecular_feature_disease",
    }
    return [
        {
            "profile_revision_ids": [str(observation["observation_revision_id"])],
            "relation_kind": relation_kind_by_modality[str(observation["modality"])],
        }
        for observation in observations
        if isinstance(observation, dict)
        and observation.get("modality") in relation_kind_by_modality
        and isinstance(observation.get("observation_revision_id"), str)
        and observation["observation_revision_id"]
    ]


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(item for item in value if isinstance(item, str) and item))


def _exact_variant_parameters(scope: object) -> JsonObject | None:
    """Project a canonical snapshot scope into exact variant.resolve parameters."""

    if not isinstance(scope, dict) or scope.get("operation") != "variant.resolve":
        return None
    if any(
        str(key) not in {"operation", *INVESTIGATION_VARIANT_PARAMETER_FIELDS}
        for key in scope
    ):
        return None
    rsid = scope.get("rsid")
    has_rsid = isinstance(rsid, str) and bool(rsid)
    has_any_allele = any(
        scope.get(key) not in (None, "") for key in ("chrom", "pos", "ref", "alt")
    )
    has_exact_allele = all(
        scope.get(key) not in (None, "") for key in ("chrom", "pos", "ref", "alt")
    )
    if has_rsid == has_exact_allele or (has_any_allele and not has_exact_allele):
        return None
    return {
        key: value
        for key, value in scope.items()
        if key in INVESTIGATION_VARIANT_PARAMETER_FIELDS
    }


def _background_job_metadata(result: JsonObject) -> JsonObject | None:
    """Extract one typed resumable job from a capability or its provider result."""

    candidates = [result]
    provider_result = result.get("provider_result")
    if isinstance(provider_result, dict):
        candidates.append(provider_result)
    for candidate in candidates:
        if candidate.get("status") != "in_progress":
            continue
        job_id = candidate.get("job_id")
        resume_operation = candidate.get("resume_operation")
        check = candidate.get("check")
        if isinstance(check, dict):
            resume_operation = resume_operation or check.get("operation")
            params = check.get("params")
            if isinstance(params, dict):
                job_id = job_id or params.get("job_id")
        if not isinstance(job_id, str) or not job_id.strip():
            return None
        if not isinstance(resume_operation, str) or not resume_operation.strip():
            return None
        metadata: JsonObject = {
            "job_id": job_id.strip(),
            "resume_operation": resume_operation.strip(),
        }
        poll = candidate.get("poll_after_seconds")
        if isinstance(poll, int) and not isinstance(poll, bool) and poll > 0:
            metadata["poll_after_seconds"] = poll
        return metadata
    return None
