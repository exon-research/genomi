"""The specialist-lane contract shared by every portal host driver.

Codex and Claude stream different protocols, but the portal reads the same
specialist lane out of both: which Lab operations carry assignment lifecycle
records, how an assignment record is found inside a host's nested tool result,
what bounded progress a running child may show, which provider receipts a
terminal child message actually returned, and why a child that produced nothing
ended the way it did.  Those rules are portal contract, not host protocol, so
they live here once and each host session translates only its own protocol into
them.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]

# One stable `<typed_state>:<imperative_directive>` code per terminal specialist
# state.  The code is what the host agent acts on; the case facts (how many
# provider calls the child made, what its budget was, which policy it ran under)
# stay in adjacent fields of the same lifecycle update.
SPECIALIST_COMPLETED = "specialist_returned_analysis:capture_its_provider_receipts"
SPECIALIST_RETURNED_NO_ANALYSIS = (
    "specialist_returned_no_analysis:reassign_a_narrower_question"
)
SPECIALIST_RUN_DID_NOT_COMPLETE = (
    "specialist_run_did_not_complete:reassign_or_record_information_gap"
)
SPECIALIST_PROVIDER_UNAVAILABLE = (
    "specialist_provider_unavailable:retry_later_or_record_information_gap"
)
SPECIALIST_POLICY_VIOLATION = (
    "specialist_policy_violation:discard_this_specialist_result"
)

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


def allowed_operations(policy: str) -> frozenset[str]:
    """Return the provider operations the named security profile authorizes."""

    return _policy_profiles().get(policy, _EMPTY_PROFILE)["allowed_operations"]


def provider_call_budget(policy: str) -> int:
    """Return the provider-call bound the named security profile authorizes."""

    return _policy_profiles().get(policy, _EMPTY_PROFILE)["max_provider_calls"]


def terminal_specialist_update(
    specialist: JsonObject,
    *,
    agent_id: str,
    run_completed: bool,
    violated: bool,
    message: str,
) -> JsonObject:
    """Build the one lifecycle update every host emits when a child ends.

    A specialist that delivered nothing must still say why, so the update always
    carries a typed guidance code plus the counted work behind it.  ``status``
    is ``completed`` only when the child both finished and returned an analysis;
    a finished child with nothing to show has not done its job.  Prose that a
    person reads is the portal's job, not this contract's.
    """

    delivered = run_completed and not violated and bool(message)
    policy = str(specialist.get("execution_policy") or "")
    update: JsonObject = {
        "agent_id": agent_id,
        "task_name": str(specialist.get("task_name") or agent_id),
        "status": "completed" if delivered else "failed",
        "guidance": _terminal_guidance(
            specialist,
            delivered=delivered,
            run_completed=run_completed,
            violated=violated,
        ),
        "provider_calls": int(specialist.get("provider_calls") or 0),
    }
    if policy:
        update["execution_policy"] = policy
        update["provider_call_budget"] = provider_call_budget(policy)
    assignment_id = str(specialist.get("assignment_id") or "")
    if assignment_id:
        update["assignment_id"] = assignment_id
    if message:
        update["message"] = message
    return update


def _terminal_guidance(
    specialist: JsonObject,
    *,
    delivered: bool,
    run_completed: bool,
    violated: bool,
) -> str:
    if violated:
        return SPECIALIST_POLICY_VIOLATION
    if delivered:
        return SPECIALIST_COMPLETED
    if int(specialist.get("provider_errors") or 0) > 0:
        return SPECIALIST_PROVIDER_UNAVAILABLE
    if not run_completed:
        return SPECIALIST_RUN_DID_NOT_COMPLETE
    return SPECIALIST_RETURNED_NO_ANALYSIS


@lru_cache(maxsize=1)
def _policy_profiles() -> dict[str, JsonObject]:
    """Read the canonical packaged security profiles.

    The lane is imported by thin protocol adapters, so it reads the manifest
    resource directly rather than importing the Lab package and initializing the
    Lab store and operations registry behind a stream parser.
    """

    path = Path(__file__).resolve().parents[1] / "lab" / "specialist_policies.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    profiles = manifest.get("profiles") if isinstance(manifest, dict) else None
    if not isinstance(profiles, list):
        return {}
    policies: dict[str, JsonObject] = {}
    for profile in profiles:
        if not isinstance(profile, dict):
            return {}
        policy_id = profile.get("id")
        operations = profile.get("allowed_operations")
        budget = profile.get("max_provider_calls")
        if (
            not isinstance(policy_id, str)
            or policy_id in policies
            or not isinstance(operations, list)
            or any(not isinstance(operation, str) for operation in operations)
            or not isinstance(budget, int)
            or isinstance(budget, bool)
        ):
            return {}
        policies[policy_id] = {
            "allowed_operations": frozenset(operations),
            "max_provider_calls": budget,
        }
    return policies


_EMPTY_PROFILE: JsonObject = {
    "allowed_operations": frozenset(),
    "max_provider_calls": 0,
}


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
    "SPECIALIST_COMPLETED",
    "SPECIALIST_POLICY_VIOLATION",
    "SPECIALIST_PROVIDER_UNAVAILABLE",
    "SPECIALIST_RETURNED_NO_ANALYSIS",
    "SPECIALIST_RUN_DID_NOT_COMPLETE",
    "allowed_operations",
    "assignment_records",
    "merged_assignment",
    "observed_result_receipt_ids",
    "progress_message",
    "provider_call_budget",
    "terminal_specialist_update",
]
