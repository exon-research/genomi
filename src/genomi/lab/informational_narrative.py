"""Open-vocabulary narrative validation at the informational clinical boundary."""

from __future__ import annotations

from . import narrative_safety_patterns as _safety
from .models import QUESTION_MAX, required_text
from .research_narrative import NarrativeKind, _unsafe_narrative


INFORMATIONAL_CLINICAL_BOUNDARY = (
    "Research support only; this is not a diagnosis or treatment decision."
)


def validate_informational_narrative(
    value: object,
    field: str,
    *,
    kind: NarrativeKind = "assertion",
) -> str:
    """Reject clinical conclusions without constraining evidence-specific wording."""

    text = required_text(value, field, QUESTION_MAX)
    rejected = _unsafe_narrative(text, kind=kind)
    if rejected is None and kind == "brief_title":
        rejected = _safety.unsafe_title_span(text)
    if rejected is not None:
        raise _safety.NarrativeSafetyError(field, rejected)
    if kind == "confirmation_need" and not _safety._CONFIRMATION_FORM.search(text):
        raise ValueError(f"{field} must describe a confirmation or evidence need")
    if kind == "professional_question":
        stripped = text.strip().lstrip('"\'\u201c\u2018')
        if not text.rstrip().endswith("?") or not _safety._INTERROGATIVE.match(
            stripped
        ):
            raise ValueError(f"{field} must be a genuine professional question")
        if _safety._INTERNAL_QUESTION_UNIT.search(text.rstrip()[:-1]):
            raise ValueError(f"{field} must contain exactly one professional question")
    return text


__all__ = ["INFORMATIONAL_CLINICAL_BOUNDARY", "validate_informational_narrative"]
