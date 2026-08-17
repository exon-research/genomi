"""JSON-safe primitives for the GenomiLab artifact boundary."""

from __future__ import annotations

import json
import math
import re
from enum import Enum
from typing import Any, Mapping


MAX_ARTIFACT_BYTES = 1_000_000
MAX_ARTIFACT_DEPTH = 20
MAX_ARTIFACT_STRING = 200_000

_FORBIDDEN_ARTIFACT_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization_header",
        "authorization",
        "bearer",
        "bearer_token",
        "client_secret",
        "cookie",
        "credentials",
        "headers",
        "http_headers",
        "password",
        "private_key",
        "provider_credentials",
        "refresh_token",
        "secret",
        "set_cookie",
        "session_cookie",
        "token",
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
        "consumer_genotype_file",
        "consumer_genotype_path",
        "consumer_array_file",
        "consumer_array_path",
        "source_path",
        "file_path",
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
_FORBIDDEN_GENOME_KEY_TOKENS = (
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
_FORBIDDEN_SECRET_SUFFIXES = (
    "_access_token",
    "_api_key",
    "_api_token",
    "_credentials",
    "_password",
    "_private_key",
    "_refresh_token",
    "_secret",
    "_token",
    "_token_id",
    "_token_secret",
)


def _safe_json(value: object, *, path: tuple[str, ...] = (), depth: int = 0) -> Any:
    if depth > MAX_ARTIFACT_DEPTH:
        raise ValueError("artifact payload exceeds the maximum nesting depth")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Enum):
        return _safe_json(value.value, path=path, depth=depth)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("artifact payload contains a non-finite number")
        return value
    if isinstance(value, str):
        if len(value) > MAX_ARTIFACT_STRING:
            raise ValueError("artifact payload contains an oversized string")
        if any(
            ord(character) < 32 and character not in "\t\n\r" for character in value
        ):
            raise ValueError(
                "artifact payload contains unsupported control characters"
            )
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str) or not raw_key:
                raise ValueError("artifact object keys must be non-empty strings")
            if len(raw_key) > 200:
                raise ValueError("artifact object key is too long")
            snake_key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw_key.strip())
            normalized_key = re.sub(r"[^a-z0-9]+", "_", snake_key.lower()).strip("_")
            if (
                normalized_key in _FORBIDDEN_ARTIFACT_KEYS
                or any(
                    token in normalized_key for token in _FORBIDDEN_GENOME_KEY_TOKENS
                )
                or normalized_key.endswith(_FORBIDDEN_SECRET_SUFFIXES)
            ):
                raise ValueError(
                    f"{'.'.join((*path, raw_key))} is not safe for the artifact boundary"
                )
            result[raw_key] = _safe_json(item, path=(*path, raw_key), depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_json(item, path=path, depth=depth + 1) for item in value]
    raise ValueError(
        f"artifact payload contains unsupported type: {type(value).__name__}"
    )


def safe_json_value(value: object) -> Any:
    """Validate, detach, size-limit, and return one JSON-compatible value."""

    detached = _safe_json(value)
    encoded = json.dumps(
        detached, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    if len(encoded.encode("utf-8")) > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact payload exceeds the maximum encoded size")
    return detached
