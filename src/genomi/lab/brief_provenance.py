"""Deterministic provenance metadata for traceable investigation briefs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any


ALLOWED_MODALITY_BADGES = frozenset(
    {
        "personal_genome",
        "public_source",
        "reported_record",
        "computational_model_prediction",
        "patient_report",
        "clinical_record",
        "laboratory_assay",
    }
)


def derive_brief_modality_badges(
    claims: Sequence[Mapping[str, Any]],
    *,
    evidence_records: Iterable[Mapping[str, Any]],
    profile_records: Iterable[Mapping[str, Any]],
) -> list[str]:
    """Derive exact display badges from the records selected by brief claims."""

    evidence_by_id = {
        str(record["evidence_record_id"]): record
        for record in evidence_records
        if isinstance(record.get("evidence_record_id"), str)
        and record["evidence_record_id"]
    }
    profile_by_id = {
        str(record["observation_revision_id"]): record
        for record in profile_records
        if isinstance(record.get("observation_revision_id"), str)
        and record["observation_revision_id"]
    }
    selected_evidence_ids: set[str] = set()
    selected_profile_ids: set[str] = set()
    for claim in claims:
        selected_evidence_ids.update(
            value
            for value in claim.get("evidence_record_ids") or []
            if isinstance(value, str) and value
        )
        selected_profile_ids.update(
            value
            for value in claim.get("profile_revision_ids") or []
            if isinstance(value, str) and value
        )

    missing_evidence = selected_evidence_ids - evidence_by_id.keys()
    if missing_evidence:
        raise ValueError(
            "brief claim evidence_record_ids must belong to the approved evidence context"
        )
    missing_profile = selected_profile_ids - profile_by_id.keys()
    if missing_profile:
        raise ValueError(
            "brief claim profile_revision_ids must belong to the pinned profile context"
        )

    badges: set[str] = set()
    for identifier in selected_profile_ids:
        record = profile_by_id[identifier]
        source_class = str(record.get("source_class") or "")
        if source_class in {"patient_reported", "caregiver_reported"}:
            badges.add("patient_report")
        elif source_class == "issued_record":
            badges.add("reported_record")
        elif source_class == "clinician_entered":
            badges.add("clinical_record")
        elif source_class == "model_extracted":
            badges.add("computational_model_prediction")
        if record.get("assay_id"):
            badges.add("laboratory_assay")

    for identifier in selected_evidence_ids:
        source_family = str(evidence_by_id[identifier].get("source_family") or "")
        if source_family == "personal_genome":
            badges.add("personal_genome")
        elif source_family in {"model", "computational_model"}:
            badges.add("computational_model_prediction")
        elif source_family:
            badges.add("public_source")
    return sorted(badges)
