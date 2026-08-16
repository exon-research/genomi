"""Semantic identity for Main-extracted reusable health-profile facts."""

from __future__ import annotations

from collections.abc import Mapping

from .models import JsonObject, normalize_reported_variant


IdentityKey = tuple[str, ...]

_LABEL_TOKEN_EQUIVALENTS = {
    "frequent": "recurrent",
    "frequently": "recurrent",
    "recurring": "recurrent",
    "repeated": "recurrent",
}
_SINGULAR_EXCEPTIONS = frozenset(
    {"analysis", "diagnosis", "illness", "status"}
)


def extracted_fact_identity_keys(
    fact: Mapping[str, object],
) -> frozenset[IdentityKey]:
    """Return conservative identifiers that survive extraction phrasing drift."""

    modality = _normalized_text(fact.get("modality"))
    source_class = _normalized_text(
        fact.get("source_class") or "model_extracted"
    )
    base = (modality, source_class)
    normalized_code = _normalized_text(fact.get("normalized_code"))
    if normalized_code:
        return frozenset({("normalized_code", *base, normalized_code)})

    reported_variant = fact.get("reported_variant")
    if modality in {"reported_germline_finding", "reported_somatic_finding"}:
        reported_variant, _ = normalize_reported_variant(
            reported_variant
            or fact.get("original_wording")
            or fact.get("label")
            or ""
        )
        if reported_variant:
            return frozenset(
                {("reported_variant", *base, _normalized_text(reported_variant))}
            )

    keys: set[IdentityKey] = set()
    label = _normalized_label(fact.get("label"))
    if label:
        keys.add(("label", *base, label))
    wording = _normalized_text(
        fact.get("original_wording") or fact.get("label")
    )
    if wording:
        keys.add(("original_wording", *base, wording))
    return frozenset(keys)


def extracted_facts_share_identity(
    left: Mapping[str, object], right: Mapping[str, object]
) -> bool:
    """Return whether two records conservatively describe the same stated fact."""

    left_time = _normalized_text(left.get("onset_or_event_time"))
    right_time = _normalized_text(right.get("onset_or_event_time"))
    if left_time and right_time and left_time != right_time:
        return False
    left_keys = extracted_fact_identity_keys(left)
    return bool(
        left_keys
        and left_keys.intersection(extracted_fact_identity_keys(right))
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
    for observation in observations:
        if observation.get("source_class") != "model_extracted":
            unique.append(observation)
            continue
        if any(
            extracted_facts_share_identity(observation, current)
            for current in unique
            if current.get("source_class") == "model_extracted"
        ):
            continue
        unique.append(observation)
    return unique


def _normalized_text(value: object) -> str:
    text = str(value or "").strip().casefold()
    return " ".join(
        "".join(character if character.isalnum() else " " for character in text)
        .split()
    )


def _normalized_label(value: object) -> str:
    tokens = []
    for token in _normalized_text(value).split():
        token = _LABEL_TOKEN_EQUIVALENTS.get(token, token)
        if (
            token.endswith("s")
            and len(token) > 4
            and token not in _SINGULAR_EXCEPTIONS
        ):
            token = token[:-1]
        tokens.append(token)
    return " ".join(tokens)


__all__ = [
    "extracted_fact_content",
    "extracted_fact_identity_keys",
    "extracted_facts_share_identity",
    "unique_current_profile_observations",
]
