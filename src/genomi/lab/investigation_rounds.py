"""Validation and projections for explicit specialist investigation rounds."""

from __future__ import annotations

from .models import JsonObject, required_text, validate_private_payload
from .specialist_board import (
    SPECIALIST_PROGRESS_REPORTED_EVENT,
    _single_line_text,
    _specialist_id,
    canonical_specialist_progress,
)


ROUND_FOCUS_QUESTION_MAX = 1_000
ROUND_REPORT_ITEM_MAX = 2_000
ROUND_REPORT_ITEMS_MAX = 50
SPECIALIST_REPORT_STANCES = frozenset(
    {"supports", "weighs_against", "mixed", "context_only"}
)
SPECIALIST_REPORT_USE_BOUNDARY: JsonObject = {
    "eligible_as_evidence_record": False,
    "eligible_for_hypothesis_support": False,
    "eligible_for_brief_claim": False,
    "diagnostic_conclusion": False,
    "treatment_recommendation": False,
}


def specialist_report_submission_input_schema() -> JsonObject:
    """Return the exact MCP contract for one specialist round report."""

    def anchor_array() -> JsonObject:
        return {
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1, "maxLength": 200},
        }

    finding_schema: JsonObject = {
        "type": "object",
        "properties": {
            "statement": {
                "type": "string",
                "minLength": 1,
                "maxLength": ROUND_REPORT_ITEM_MAX,
            },
            "stance": {
                "type": "string",
                "enum": sorted(SPECIALIST_REPORT_STANCES),
            },
            "evidence_record_ids": anchor_array(),
            "profile_revision_ids": anchor_array(),
        },
        "required": [
            "statement",
            "stance",
            "evidence_record_ids",
            "profile_revision_ids",
        ],
        "anyOf": [
            {"properties": {"evidence_record_ids": {"minItems": 1}}},
            {"properties": {"profile_revision_ids": {"minItems": 1}}},
        ],
        "additionalProperties": False,
    }
    gap_schema: JsonObject = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "minLength": 1,
                "maxLength": ROUND_REPORT_ITEM_MAX,
            },
            "evidence_record_ids": anchor_array(),
            "profile_revision_ids": anchor_array(),
        },
        "required": [
            "question",
            "evidence_record_ids",
            "profile_revision_ids",
        ],
        "additionalProperties": False,
    }
    report_schema: JsonObject = {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "maxItems": ROUND_REPORT_ITEMS_MAX,
                "items": finding_schema,
            },
            "gaps": {
                "type": "array",
                "maxItems": ROUND_REPORT_ITEMS_MAX,
                "items": gap_schema,
            },
        },
        "required": ["findings", "gaps"],
        "anyOf": [
            {"properties": {"findings": {"minItems": 1}}},
            {"properties": {"gaps": {"minItems": 1}}},
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "investigation_id": {"type": "string", "minLength": 1},
            "round_id": {"type": "string", "minLength": 1},
            "specialist_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 80,
                "pattern": (
                    "^specialist-[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?$"
                ),
            },
            "report": report_schema,
        },
        "required": [
            "investigation_id",
            "round_id",
            "specialist_id",
            "report",
        ],
        "additionalProperties": False,
    }


def canonical_round_definition(
    *,
    focus_question: object,
    specialist_assignments: object,
    board: JsonObject,
) -> JsonObject:
    focus = _single_line_text(
        focus_question, "focus_question", ROUND_FOCUS_QUESTION_MAX
    )
    if not isinstance(specialist_assignments, list):
        raise ValueError("specialist_assignments must be an array")
    board_members = board.get("members")
    if not isinstance(board_members, list) or not board_members:
        raise ValueError("the investigation specialist board is unavailable")
    board_ids = {
        str(item.get("specialist_id"))
        for item in board_members
        if isinstance(item, dict) and item.get("specialist_id")
    }
    assignments: list[JsonObject] = []
    seen: set[str] = set()
    for item in specialist_assignments:
        if not isinstance(item, dict) or set(item) != {"specialist_id", "task"}:
            raise ValueError(
                "each round specialist assignment must contain exactly specialist_id and task"
            )
        specialist_id = _specialist_id(item.get("specialist_id"))
        if specialist_id in seen:
            raise ValueError("specialist_id values must be unique within a round")
        seen.add(specialist_id)
        assignments.append(
            {
                "specialist_id": specialist_id,
                "task": _single_line_text(item.get("task"), "specialist task", 300),
            }
        )
    if seen != board_ids:
        raise ValueError(
            "each investigation-board specialist must receive exactly one round assignment"
        )
    result = {
        "focus_question": focus,
        "specialist_assignments": sorted(
            assignments, key=lambda item: str(item["specialist_id"])
        ),
    }
    validate_private_payload(result)
    return result


def canonical_specialist_report(value: object) -> JsonObject:
    if not isinstance(value, dict) or set(value) != {"findings", "gaps"}:
        raise ValueError("report must contain exactly findings and gaps")
    findings_value = value.get("findings")
    gaps_value = value.get("gaps")
    if not isinstance(findings_value, list) or not isinstance(gaps_value, list):
        raise ValueError("report findings and gaps must be arrays")
    if len(findings_value) > ROUND_REPORT_ITEMS_MAX:
        raise ValueError(
            f"report findings must contain at most {ROUND_REPORT_ITEMS_MAX} items"
        )
    if len(gaps_value) > ROUND_REPORT_ITEMS_MAX:
        raise ValueError(
            f"report gaps must contain at most {ROUND_REPORT_ITEMS_MAX} items"
        )
    if not findings_value and not gaps_value:
        raise ValueError("a specialist report requires at least one finding or gap")

    findings = [canonical_round_finding(item) for item in findings_value]
    gaps = [canonical_round_gap(item) for item in gaps_value]
    result = {"findings": findings, "gaps": gaps}
    validate_private_payload(result)
    return result


def canonical_round_finding(value: object) -> JsonObject:
    required_fields = {
        "statement",
        "stance",
        "evidence_record_ids",
        "profile_revision_ids",
    }
    if not isinstance(value, dict) or set(value) != required_fields:
        raise ValueError(
            "each finding must contain exactly statement, stance, evidence_record_ids, and profile_revision_ids"
        )
    stance = required_text(value.get("stance"), "finding stance", 40).lower()
    if stance not in SPECIALIST_REPORT_STANCES:
        raise ValueError(
            "finding stance must be one of: "
            + ", ".join(sorted(SPECIALIST_REPORT_STANCES))
        )
    evidence_ids = _canonical_id_array(
        value.get("evidence_record_ids"), "evidence_record_ids"
    )
    profile_ids = _canonical_id_array(
        value.get("profile_revision_ids"), "profile_revision_ids"
    )
    if not evidence_ids and not profile_ids:
        raise ValueError(
            "each specialist finding requires an exact evidence or profile anchor"
        )
    return {
        "statement": required_text(
            value.get("statement"), "finding statement", ROUND_REPORT_ITEM_MAX
        ),
        "stance": stance,
        "evidence_record_ids": evidence_ids,
        "profile_revision_ids": profile_ids,
    }


def canonical_round_gap(value: object) -> JsonObject:
    required_fields = {"question", "evidence_record_ids", "profile_revision_ids"}
    if not isinstance(value, dict) or set(value) != required_fields:
        raise ValueError(
            "each gap must contain exactly question, evidence_record_ids, and profile_revision_ids"
        )
    return {
        "question": required_text(
            value.get("question"), "gap question", ROUND_REPORT_ITEM_MAX
        ),
        "evidence_record_ids": _canonical_id_array(
            value.get("evidence_record_ids"), "evidence_record_ids"
        ),
        "profile_revision_ids": _canonical_id_array(
            value.get("profile_revision_ids"), "profile_revision_ids"
        ),
    }


def _canonical_id_array(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    result: list[str] = []
    for item in value:
        identifier = required_text(item, field, 200)
        if identifier in result:
            raise ValueError(f"{field} must not contain duplicate identifiers")
        result.append(identifier)
    return sorted(result)


def project_investigation_round(
    round_record: JsonObject,
    *,
    board: JsonObject,
    events: list[JsonObject],
) -> JsonObject:
    """Combine immutable round records with append-only progress events."""

    round_id = str(round_record.get("round_id") or "")
    assignments = {
        str(item.get("specialist_id")): item
        for item in round_record.get("specialist_assignments") or []
        if isinstance(item, dict) and item.get("specialist_id")
    }
    reports = {
        str(item.get("specialist_id")): item
        for item in round_record.get("specialist_reports") or []
        if isinstance(item, dict) and item.get("specialist_id")
    }
    members: list[JsonObject] = []
    for member in board.get("members") or []:
        if not isinstance(member, dict):
            continue
        specialist_id = str(member.get("specialist_id") or "")
        assignment = assignments.get(specialist_id)
        if not isinstance(assignment, dict):
            continue
        members.append(
            {
                "specialist_id": specialist_id,
                "role": member.get("role"),
                "task": assignment.get("task"),
                "status": "assigned",
                "current_work": None,
                **(
                    {
                        "report": {
                            **reports[specialist_id],
                            "use_boundary": dict(SPECIALIST_REPORT_USE_BOUNDARY),
                        }
                    }
                    if specialist_id in reports
                    else {}
                ),
            }
        )

    for event in events:
        if (
            not isinstance(event, dict)
            or event.get("event_type") != SPECIALIST_PROGRESS_REPORTED_EVENT
        ):
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("round_id") != round_id:
            continue
        try:
            progress = canonical_specialist_progress(
                specialist_id=payload.get("specialist_id"),
                status=payload.get("status"),
                current_work=payload.get("current_work"),
            )
        except ValueError:
            continue
        for member in members:
            if member["specialist_id"] != progress["specialist_id"]:
                continue
            if member.get("status") != "completed":
                member["status"] = progress["status"]
                member["current_work"] = progress["current_work"]
            break

    for member in members:
        if "report" in member:
            member["status"] = "completed"

    statuses = {str(member.get("status")) for member in members}
    if members and all("report" in member for member in members):
        status = "completed"
    elif "blocked" in statuses:
        status = "blocked"
    elif statuses.intersection({"working", "completed"}):
        status = "in_progress"
    else:
        status = "planned"
    return {
        key: value
        for key, value in round_record.items()
        if key not in {"specialist_assignments", "specialist_reports"}
    } | {
        "status": status,
        "members": members,
        "report_count": len(reports),
    }


def project_investigation_rounds(
    round_records: list[JsonObject],
    *,
    board: JsonObject | None,
    events: list[JsonObject],
) -> list[JsonObject]:
    if not isinstance(board, dict):
        return []
    return [
        project_investigation_round(item, board=board, events=events)
        for item in round_records
    ]


__all__ = [
    "ROUND_FOCUS_QUESTION_MAX",
    "ROUND_REPORT_ITEM_MAX",
    "ROUND_REPORT_ITEMS_MAX",
    "SPECIALIST_REPORT_STANCES",
    "SPECIALIST_REPORT_USE_BOUNDARY",
    "canonical_round_definition",
    "canonical_specialist_report",
    "project_investigation_round",
    "project_investigation_rounds",
    "specialist_report_submission_input_schema",
]
