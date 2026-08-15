"""Validation and API-view helpers for GenomiLab domain records."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

JsonObject = dict[str, Any]

DISPLAY_NAME_MAX = 120
OBSERVATION_LABEL_MAX = 500
QUESTION_MAX = 2_000
SOURCE_LABEL_MAX = 200

OBSERVATION_MODALITIES = frozenset(
    {
        "condition",
        "phenotype",
        "family_history",
        "medication",
        "exposure",
        "measurement",
        "procedure",
        "allergy",
        "reported_germline_finding",
        "reported_somatic_finding",
        "pathology",
        "biomarker",
        "specimen",
        "assay",
    }
)
ASSERTION_STATUSES = frozenset({"present", "absent", "unknown"})
VERIFICATION_STATES = frozenset(
    {"unreviewed", "user_confirmed", "record_confirmed", "clinician_confirmed"}
)
SOURCE_CLASSES = frozenset(
    {"patient_reported", "caregiver_reported", "issued_record", "clinician_entered", "model_extracted"}
)
ASSERTION_AUTHORS = frozenset(
    {"patient", "caregiver", "clinician", "imported_record", "model"}
)
COVERAGE_STATES = frozenset(
    {
        "observed",
        "explicitly_not_detected_within_declared_assay_scope",
        "not_measured",
        "not_provided",
        "unavailable",
        "out_of_scope",
    }
)

RSID_RE = re.compile(r"^rs[0-9]+$", re.IGNORECASE)
EXACT_VARIANT_RE = re.compile(
    r"^(?:chr)?(?:[1-9]|1[0-9]|2[0-2]|X|Y|MT|M):[1-9][0-9]*:[ACGTN]+:[ACGTN]+$",
    re.IGNORECASE,
)

_FORBIDDEN_PRIVATE_KEYS = frozenset(
    {
        "vcf",
        "gvcf",
        "bam",
        "cram",
        "fastq",
        "genome_file",
        "genome_path",
        "genome_source",
        "genome_bundle",
        "genome_upload",
        "genome_content",
        "genome_data",
        "genome_records",
        "variant_callset_file",
        "alignment_file",
        "sequencing_source",
        "consumer_genotype_file",
        "consumer_genotype_path",
        "consumer_array_file",
        "consumer_array_path",
        "source_path",
        "agi_path",
        "agi_file",
        "agi_db",
        "agi_database",
        "agi_rows",
        "agi_records",
        "active_genome_index_path",
        "active_genome_index_file",
        "active_genome_index_rows",
        "raw_agi_rows",
        "raw_sequence",
    }
)

_GENOME_SOURCE_KEY_TOKENS = (
    "vcf",
    "gvcf",
    "fastq",
    "cram",
    "genome_source",
    "genome_path",
    "genome_file",
    "genome_bundle",
    "genome_upload",
    "genome_content",
    "genome_data",
    "genome_records",
    "bam_file",
    "bam_path",
    "alignment_file",
    "sequencing_source",
    "consumer_genotype_file",
    "consumer_genotype_path",
    "consumer_array_file",
    "consumer_array_path",
    "agi_path",
    "agi_file",
    "agi_db",
    "agi_database",
    "agi_rows",
    "agi_records",
    "active_genome_index_path",
    "active_genome_index_file",
    "active_genome_index_rows",
    "raw_sequence",
)


def _canonical_private_key(value: object) -> str:
    text = str(value).strip()
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def required_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    if any(ord(character) < 32 and character not in "\t\n\r" for character in text):
        raise ValueError(f"{field} contains unsupported control characters")
    return text


def optional_text(value: object, field: str, maximum: int) -> str | None:
    if value in (None, ""):
        return None
    return required_text(value, field, maximum)


def choice(value: object, field: str, choices: frozenset[str]) -> str:
    text = required_text(value, field, 80).lower()
    if text not in choices:
        raise ValueError(f"{field} must be one of: {', '.join(sorted(choices))}")
    return text


def row_dict(row: sqlite3.Row | None) -> JsonObject:
    if row is None:
        return {}
    result = {str(key): row[key] for key in row.keys()}
    for key in tuple(result):
        if not key.endswith("_json"):
            continue
        raw = result.pop(key)
        result[key.removesuffix("_json")] = json.loads(raw) if raw else None
    return result


def stable_id(prefix: str, *parts: object) -> str:
    material = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(material).hexdigest()[:24]}"


def validate_private_payload(payload: object) -> None:
    """Reject raw-genome material at the GenomiLab application boundary."""

    def walk(value: object, path: tuple[str, ...]) -> Iterable[tuple[tuple[str, ...], object]]:
        if isinstance(value, dict):
            for raw_key, item in value.items():
                key = _canonical_private_key(raw_key)
                next_path = (*path, key)
                yield next_path, item
                yield from walk(item, next_path)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item, path)

    for path, value in walk(payload, ()):
        key = path[-1]
        if key in _FORBIDDEN_PRIVATE_KEYS or any(
            token in key for token in _GENOME_SOURCE_KEY_TOKENS
        ):
            raise ValueError(f"{key} is owned by Genomi and is not accepted by GenomiLab")
        if key == "sequence" and not (
            isinstance(value, int) and not isinstance(value, bool)
        ):
            raise ValueError("sequence content is owned by Genomi and is not accepted by GenomiLab")
        if key in {"file", "path", "rows"} and any(
            token in path for token in ("genome", "agi", "active_genome_index")
        ):
            raise ValueError(f"{'.'.join(path)} is not accepted by GenomiLab")
        if isinstance(value, (bytes, bytearray, memoryview)):
            raise ValueError("binary genome or report data is not accepted by this operation")


def redacted_private_payload(payload: object) -> object:
    """Detach a result while removing storage paths and raw-genome material.

    Genomi evidence envelopes are retained byte-for-byte as JSON values; only
    forbidden application-boundary fields elsewhere in the result are removed.
    """

    def redact(value: object, path: tuple[str, ...]) -> object:
        if isinstance(value, dict):
            result: JsonObject = {}
            for raw_key, item in value.items():
                key = str(raw_key)
                normalized = _canonical_private_key(key)
                next_path = (*path, normalized)
                if normalized in _FORBIDDEN_PRIVATE_KEYS or any(
                    token in normalized for token in _GENOME_SOURCE_KEY_TOKENS
                ):
                    continue
                if normalized == "sequence" and not (
                    isinstance(item, int) and not isinstance(item, bool)
                ):
                    continue
                if normalized in {"file", "path", "rows"} and any(
                    token in next_path
                    for token in ("genome", "agi", "active_genome_index")
                ):
                    continue
                result[key] = redact(item, next_path)
            return result
        if isinstance(value, (list, tuple)):
            return [redact(item, path) for item in value]
        if isinstance(value, (bytes, bytearray, memoryview)):
            raise ValueError("binary data is not accepted by the GenomiLab domain store")
        return value

    return redact(payload, ())


def normalize_reported_variant(value: object) -> tuple[str, str]:
    variant = required_text(value, "reported_variant", SOURCE_LABEL_MAX)
    if RSID_RE.fullmatch(variant):
        return variant.lower(), "rsid_ready"
    if EXACT_VARIANT_RE.fullmatch(variant):
        return variant, "exact_genomic_allele_ready"
    return variant, "needs_review"


def compact_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
