"""Validation and API view helpers for GenomiLab records."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

JsonObject = dict[str, Any]

PROFILE_NAME_MAX = 120
FACT_LABEL_MAX = 500
QUESTION_MAX = 2_000
SOURCE_LABEL_MAX = 200

HEALTH_FACT_KINDS = frozenset(
    {
        "condition",
        "symptom",
        "medication",
        "allergy",
        "measurement",
        "procedure",
        "family_history",
        "exposure",
    }
)
ASSERTION_STATUSES = frozenset({"present", "absent", "unknown"})
VERIFICATION_STATES = frozenset(
    {"unreviewed", "user_confirmed", "record_confirmed", "clinician_confirmed"}
)

RSID_RE = re.compile(r"^rs[0-9]+$", re.IGNORECASE)
EXACT_VARIANT_RE = re.compile(
    r"^(?:chr)?(?:[1-9]|1[0-9]|2[0-2]|X|Y|MT|M):[1-9][0-9]*:[ACGTN]+:[ACGTN]+$",
    re.IGNORECASE,
)


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
    return {str(key): row[key] for key in row.keys()}


def genome_view(row: sqlite3.Row) -> JsonObject | None:
    if not row["agi_id"]:
        return None
    return {
        "agi_id": row["agi_id"],
        "genome_build": row["genome_build"],
        "readiness": row["readiness"],
        "imported_at": row["imported_at"],
    }


def profile_summary(row: sqlite3.Row) -> JsonObject:
    return {
        "profile_id": row["profile_id"],
        "display_name": row["display_name"],
        "genomi_user_id": row["genomi_user_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "health_fact_count": int(row["health_fact_count"] or 0),
        "finding_count": int(row["finding_count"] or 0),
        "investigation_count": int(row["investigation_count"] or 0),
        "genome": genome_view(row),
    }


def investigation_view(row: sqlite3.Row) -> JsonObject:
    result = row_dict(row)
    raw = result.pop("brief_json", None)
    if raw:
        try:
            result["brief"] = json.loads(raw)
        except json.JSONDecodeError:
            result["brief"] = {
                "status": "failed",
                "error": {
                    "code": "invalid_saved_brief",
                    "message": "Saved result is unreadable.",
                },
            }
    else:
        result["brief"] = None
    return result
