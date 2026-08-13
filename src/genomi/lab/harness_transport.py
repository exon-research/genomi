"""JSON-safe transport primitives for the GenomiLab harness boundary."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


PROTOCOL_VERSION = "genomilab.harness.v1"
MAX_TRANSPORT_BYTES = 1_000_000
MAX_TRANSPORT_DEPTH = 20
MAX_TRANSPORT_STRING = 200_000

_FORBIDDEN_TRANSPORT_KEYS = frozenset(
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
    "_credentials",
    "_password",
    "_private_key",
    "_refresh_token",
    "_secret",
    "_token",
)


def required_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    text = value.strip()
    if len(text) > 240:
        raise ValueError(f"{field_name} must be at most 240 characters")
    if any(ord(character) < 32 for character in text):
        raise ValueError(f"{field_name} contains unsupported control characters")
    return text


def required_text(
    value: object,
    field_name: str,
    maximum: int = MAX_TRANSPORT_STRING,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{field_name} must be at most {maximum} characters")
    if any(ord(character) < 32 and character not in "\t\n\r" for character in text):
        raise ValueError(f"{field_name} contains unsupported control characters")
    return text


def _safe_json(value: object, *, path: tuple[str, ...] = (), depth: int = 0) -> Any:
    if depth > MAX_TRANSPORT_DEPTH:
        raise ValueError("transport payload exceeds the maximum nesting depth")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Enum):
        return _safe_json(value.value, path=path, depth=depth)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("transport payload contains a non-finite number")
        return value
    if isinstance(value, str):
        if len(value) > MAX_TRANSPORT_STRING:
            raise ValueError("transport payload contains an oversized string")
        if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
            raise ValueError("transport payload contains unsupported control characters")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str) or not raw_key:
                raise ValueError("transport object keys must be non-empty strings")
            if len(raw_key) > 200:
                raise ValueError("transport object key is too long")
            snake_key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw_key.strip())
            normalized_key = re.sub(r"[^a-z0-9]+", "_", snake_key.lower()).strip("_")
            if (
                normalized_key in _FORBIDDEN_TRANSPORT_KEYS
                or any(token in normalized_key for token in _FORBIDDEN_GENOME_KEY_TOKENS)
                or normalized_key.endswith(_FORBIDDEN_SECRET_SUFFIXES)
            ):
                raise ValueError(f"{'.'.join((*path, raw_key))} is not safe for harness transport")
            result[raw_key] = _safe_json(item, path=(*path, raw_key), depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_json(item, path=path, depth=depth + 1) for item in value]
    raise ValueError(f"transport payload contains unsupported type: {type(value).__name__}")


def safe_json_value(value: object) -> Any:
    """Validate, detach, size-limit, and return one JSON-compatible value."""

    detached = _safe_json(value)
    encoded = json.dumps(detached, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) > MAX_TRANSPORT_BYTES:
        raise ValueError("transport payload exceeds the maximum encoded size")
    return detached


def safe_json_dumps(value: object) -> str:
    return json.dumps(
        safe_json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def frozen_json_object(value: object, field_name: str) -> Mapping[str, Any]:
    detached = safe_json_value(value)
    if not isinstance(detached, dict):
        raise ValueError(f"{field_name} must be an object")
    frozen = _freeze_json(detached)
    assert isinstance(frozen, Mapping)
    return frozen


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
