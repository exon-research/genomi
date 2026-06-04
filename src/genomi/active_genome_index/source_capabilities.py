from __future__ import annotations

from typing import Any

from .source_intake.dispatch import (
    SUPPORTED_SEQUENCING_SOURCE_FORMATS,
    SUPPORTED_VARIANT_CALLSET_FORMATS,
)

JsonObject = dict[str, Any]

SEQUENCE_DERIVED_AGI_FORMATS = frozenset(
    SUPPORTED_VARIANT_CALLSET_FORMATS | SUPPORTED_SEQUENCING_SOURCE_FORMATS
)


def agi_source_format_has_sequence_variant_context(value: object) -> bool:
    """Return whether an AGI source format can carry coordinate allele context."""
    return str(value or "").strip().lower() in SEQUENCE_DERIVED_AGI_FORMATS


def agi_record_has_sequence_variant_context(record: JsonObject) -> bool:
    return agi_source_format_has_sequence_variant_context(record.get("agi_source_format"))
