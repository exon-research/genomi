"""Semantic identity for Main-extracted reusable health-profile facts."""

from __future__ import annotations

from collections.abc import Mapping

from .models import JsonObject, normalize_reported_variant


def extracted_fact_identity(fact: Mapping[str, object]) -> tuple[str, str, str]:
    """Identify one stated fact independently of its generated record IDs."""

    return (
        _normalized_text(fact.get("modality")),
        _normalized_text(fact.get("original_wording") or fact.get("label")),
        _normalized_text(fact.get("source_class") or "model_extracted"),
    )


def extracted_fact_content(fact: Mapping[str, object]) -> JsonObject:
    """Project stored and incoming facts onto the same semantic content."""

    modality = _normalized_text(fact.get("modality"))
    original_wording = str(
        fact.get("original_wording") or fact.get("label") or ""
    ).strip()
    reported_variant = fact.get("reported_variant")
    if modality in {"reported_germline_finding", "reported_somatic_finding"}:
        reported_variant, _ = normalize_reported_variant(
            reported_variant or original_wording
        )

    def text(field: str) -> str | None:
        value = fact.get(field)
        return str(value).strip() if value not in (None, "") else None

    return {
        "modality": modality,
        "label": str(fact.get("label") or original_wording).strip(),
        "original_wording": original_wording,
        "assertion_status": _normalized_text(
            fact.get("assertion_status") or "present"
        ),
        "verification_state": _normalized_text(
            fact.get("verification_state") or "unreviewed"
        ),
        "source_class": _normalized_text(
            fact.get("source_class") or "model_extracted"
        ),
        "assertion_author": _normalized_text(
            fact.get("assertion_author") or "model"
        ),
        "coverage_state": _normalized_text(
            fact.get("coverage_state") or "observed"
        ),
        "normalized_code": text("normalized_code"),
        "value": fact.get("value"),
        "onset_or_event_time": text("onset_or_event_time"),
        "reported_variant": reported_variant,
        "gene": text("gene"),
        "reported_classification": text("reported_classification"),
    }


def unique_current_profile_observations(
    observations: list[JsonObject],
) -> list[JsonObject]:
    """Keep one current model-extracted revision for each stated fact identity."""

    unique: list[JsonObject] = []
    seen: set[tuple[str, str, str]] = set()
    for observation in observations:
        if observation.get("source_class") != "model_extracted":
            unique.append(observation)
            continue
        identity = extracted_fact_identity(observation)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(observation)
    return unique


def _normalized_text(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


__all__ = [
    "extracted_fact_content",
    "extracted_fact_identity",
    "unique_current_profile_observations",
]
