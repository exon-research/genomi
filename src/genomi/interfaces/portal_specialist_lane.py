"""The specialist-lane contract shared by every portal host driver.

Codex and Claude stream different protocols, but the portal reads the same
specialist lane out of both: which Lab operations carry assignment lifecycle
records, how an assignment record is found inside a host's nested tool result,
what bounded progress a running child may show, and which provider receipts a
terminal child message actually returned.  Those rules are portal contract, not
host protocol, so they live here once and each host session translates only its
own protocol into them.
"""

from __future__ import annotations

import json
import re
from typing import Any

JsonObject = dict[str, Any]

# Lab operations whose results carry specialist assignment lifecycle records.
LAB_ASSIGNMENT_OPERATIONS = frozenset(
    {
        "lab.create_specialist_assignment",
        "lab.read_investigation",
        "lab.transition_specialist_assignment",
    }
)
ASSIGNMENT_STATES = frozenset(
    {"proposed", "spawned", "completed", "failed", "cancelled"}
)
# Assignment states that can still take ownership of a newly started child. A
# continuation is normally recorded as spawned before its follow-up turn begins,
# so both live states can own a child; terminal states never can.
BINDABLE_ASSIGNMENT_STATES = frozenset({"proposed", "spawned"})

_RESULT_RECEIPT_PATTERN = re.compile(r"result-receipt-[A-Za-z0-9_-]{24,128}")
_NESTED_RESULT_KEYS = (
    "structuredContent",
    "structured_content",
    "result",
    "payload",
    "content",
    "text",
)
_MAX_RESULT_DEPTH = 5


def observed_result_receipt_ids(message: str) -> list[str]:
    """Return the provider receipt ids a child's terminal message stated."""

    return sorted(set(_RESULT_RECEIPT_PATTERN.findall(str(message or ""))))


def progress_message(operation: str) -> str:
    """Describe a running child's authorized operation without leaking results."""

    if operation == "paperclip.search_biomedical":
        return "Searching public biomedical literature"
    if operation == "paperclip.retrieve_document_evidence":
        return "Reading line-pinned public evidence"
    if operation.startswith("biohub."):
        return "Running the bounded BioHub analysis"
    if operation.startswith("proto."):
        return "Running the bounded Proto analysis"
    return "Running the authorized specialist operation"


def assignment_records(value: Any, depth: int = 0) -> list[JsonObject]:
    """Collect assignment records from a host's nested tool-result payload.

    Hosts wrap the same Lab result in different envelopes — MCP content lists,
    JSON-encoded text, app-server item results — so the lane walks the nesting
    rather than depending on one host's shape.
    """

    if depth > _MAX_RESULT_DEPTH:
        return []
    if isinstance(value, str):
        try:
            return assignment_records(json.loads(value), depth + 1)
        except (json.JSONDecodeError, ValueError):
            return []
    if isinstance(value, list):
        records: list[JsonObject] = []
        for child in value:
            records.extend(assignment_records(child, depth + 1))
        return records
    if not isinstance(value, dict):
        return []
    records = []
    assignment = value.get("assignment")
    if isinstance(assignment, dict):
        records.append(assignment)
    listed = value.get("specialist_assignments")
    if isinstance(listed, list):
        records.extend(item for item in listed if isinstance(item, dict))
    if records:
        return records
    for key in _NESTED_RESULT_KEYS:
        if key not in value:
            continue
        found = assignment_records(value[key], depth + 1)
        if found:
            return found
    return []


def merged_assignment(existing: JsonObject, record: JsonObject) -> JsonObject | None:
    """Normalize one observed assignment record into lane state, or reject it."""

    assignment_id = str(record.get("specialist_assignment_id") or "")
    policy = str(record.get("execution_policy") or "")
    state = str(record.get("state") or "")
    if not assignment_id or not policy or state not in ASSIGNMENT_STATES:
        return None
    return {
        **existing,
        "assignment_id": assignment_id,
        "execution_policy": policy,
        "specialist_brief_id": str(
            record.get("specialist_brief_id")
            or existing.get("specialist_brief_id")
            or ""
        ),
        "specialist_role": str(
            record.get("specialist_role") or existing.get("specialist_role") or ""
        ),
        "state": state,
    }


__all__ = [
    "ASSIGNMENT_STATES",
    "BINDABLE_ASSIGNMENT_STATES",
    "LAB_ASSIGNMENT_OPERATIONS",
    "assignment_records",
    "merged_assignment",
    "observed_result_receipt_ids",
    "progress_message",
]
