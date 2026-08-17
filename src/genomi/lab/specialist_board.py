"""Host-owned specialist-board monitoring for GenomiLab investigations."""

from __future__ import annotations

import re
from typing import Any, Protocol

from .models import JsonObject, required_text, validate_private_payload
from .service_errors import LabError


SPECIALIST_BOARD_FORMED_EVENT = "specialist_board_formed"
SPECIALIST_PROGRESS_REPORTED_EVENT = "specialist_progress_reported"
SPECIALIST_REPORT_RECORDED_EVENT = "specialist_report_recorded"
SPECIALIST_BOARD_MIN_MEMBERS = 2
SPECIALIST_BOARD_MAX_MEMBERS = 5
SPECIALIST_ROLE_MAX = 80
SPECIALIST_TASK_MAX = 300
SPECIALIST_CURRENT_WORK_MAX = 300
SPECIALIST_PROGRESS_STATUSES = frozenset({"working", "blocked", "completed"})

_SPECIALIST_ID_RE = re.compile(
    r"^specialist-[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?$"
)
_CHAIR: JsonObject = {
    "role": "main_agent",
    "responsibility": (
        "patient_interaction_and_active_genome_index_context_owner"
    ),
}


class _SpecialistBoardApplication(Protocol):
    store: Any

    def investigation(self, investigation_id: str) -> JsonObject: ...

    def _require_investigation_authorization(
        self, investigation_id: str, *, intent: str, receipt: JsonObject | None = None
    ) -> JsonObject: ...


def _specialist_id(value: object) -> str:
    specialist_id = required_text(value, "specialist_id", 80)
    if not _SPECIALIST_ID_RE.fullmatch(specialist_id):
        raise ValueError(
            "specialist_id must be a board-local identifier beginning with "
            "'specialist-' and containing only lowercase letters, numbers, "
            "underscores, or hyphens"
        )
    return specialist_id


def _single_line_text(value: object, field: str, maximum: int) -> str:
    text = required_text(value, field, maximum)
    if "\n" in text or "\r" in text:
        raise ValueError(f"{field} must be a single-line monitoring label")
    return text


def canonical_specialists(value: object) -> list[JsonObject]:
    if not isinstance(value, list) or len(value) < SPECIALIST_BOARD_MIN_MEMBERS:
        raise ValueError(
            f"specialists must contain at least {SPECIALIST_BOARD_MIN_MEMBERS} members"
        )
    if len(value) > SPECIALIST_BOARD_MAX_MEMBERS:
        raise ValueError(
            f"specialists must contain at most {SPECIALIST_BOARD_MAX_MEMBERS} members"
        )
    members: list[JsonObject] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "specialist_id",
            "role",
            "task",
        }:
            raise ValueError(
                "each specialist must contain exactly specialist_id, role, and task"
            )
        specialist_id = _specialist_id(item.get("specialist_id"))
        if specialist_id in seen:
            raise ValueError("specialist_id values must be unique within the board")
        seen.add(specialist_id)
        member = {
            "specialist_id": specialist_id,
            "role": _single_line_text(
                item.get("role"), "specialist role", SPECIALIST_ROLE_MAX
            ),
            "task": _single_line_text(
                item.get("task"), "specialist task", SPECIALIST_TASK_MAX
            ),
            "status": "assigned",
            "current_work": None,
        }
        validate_private_payload(member)
        members.append(member)
    return sorted(members, key=lambda member: str(member["specialist_id"]))


def canonical_specialist_progress(
    *, specialist_id: object, status: object, current_work: object
) -> JsonObject:
    status_value = required_text(status, "specialist status", 20).lower()
    if status_value not in SPECIALIST_PROGRESS_STATUSES:
        raise ValueError(
            "specialist status must be one of: "
            + ", ".join(sorted(SPECIALIST_PROGRESS_STATUSES))
        )
    progress = {
        "specialist_id": _specialist_id(specialist_id),
        "status": status_value,
        "current_work": _single_line_text(
            current_work, "current_work", SPECIALIST_CURRENT_WORK_MAX
        ),
    }
    validate_private_payload(progress)
    return progress


def project_specialist_board(
    events: object, *, round_id: str | None = None
) -> JsonObject | None:
    """Derive the current board from committed investigation events."""

    if not isinstance(events, list):
        return None
    members: list[JsonObject] | None = None
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = event.get("event_type")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if event_type == SPECIALIST_BOARD_FORMED_EVENT and members is None:
            candidate = payload.get("members")
            if not isinstance(candidate, list):
                continue
            try:
                members = canonical_specialists(
                    [
                        {
                            "specialist_id": item.get("specialist_id"),
                            "role": item.get("role"),
                            "task": item.get("task"),
                        }
                        for item in candidate
                        if isinstance(item, dict)
                    ]
                )
            except ValueError:
                members = None
            continue
        if event_type != SPECIALIST_PROGRESS_REPORTED_EVENT or members is None:
            continue
        event_round_id = payload.get("round_id")
        if round_id is None and event_round_id is not None:
            continue
        if round_id is not None and event_round_id != round_id:
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
            if member["specialist_id"] == progress["specialist_id"]:
                if member.get("status") != "completed":
                    member["status"] = progress["status"]
                    member["current_work"] = progress["current_work"]
                break
    if members is None:
        return None
    statuses = {str(member["status"]) for member in members}
    if statuses == {"completed"}:
        board_status = "completed"
    elif "working" in statuses:
        board_status = "in_progress"
    elif "blocked" in statuses:
        board_status = "blocked"
    elif "completed" in statuses:
        board_status = "in_progress"
    else:
        board_status = "formed"
    return {
        "status": board_status,
        "execution_owner": "underlying_agent",
        "chair": dict(_CHAIR),
        "members": members,
    }


def _board_assignments(members: object) -> list[JsonObject]:
    if not isinstance(members, list):
        return []
    return [
        {
            "specialist_id": member.get("specialist_id"),
            "role": member.get("role"),
            "task": member.get("task"),
        }
        for member in members
        if isinstance(member, dict)
    ]


def specialist_board_handle(board: JsonObject) -> JsonObject:
    """Return the structural board marker safe before session authorization."""

    members = board.get("members")
    return {
        "status": str(board.get("status") or "formed"),
        "member_count": len(members) if isinstance(members, list) else 0,
        "chair": dict(_CHAIR),
    }


class SpecialistBoardApplicationMixin:
    """Record native-host subagent assignments without controlling subagents."""

    def form_agent_specialist_board(
        self: _SpecialistBoardApplication,
        investigation_id: str,
        *,
        specialists: list[JsonObject],
    ) -> JsonObject:
        self.investigation(investigation_id)
        try:
            members = canonical_specialists(specialists)
        except ValueError as exc:
            raise LabError("invalid_specialist_board", str(exc)) from exc
        with self.store.atomic_write():
            events = self.store.replay_investigation_events(investigation_id)
            existing = project_specialist_board(events)
            authorization_active = False
            if isinstance(existing, dict):
                try:
                    self._require_investigation_authorization(
                        investigation_id, intent="resume"
                    )
                except LabError:
                    board = specialist_board_handle(existing)
                else:
                    authorization_active = True
                    if _board_assignments(
                        existing.get("members")
                    ) != _board_assignments(members):
                        raise LabError(
                            "specialist_board_already_formed",
                            (
                                "This investigation already has a different "
                                "specialist board."
                            ),
                            http_status=409,
                        )
                    board = existing
                retry_reused = True
            else:
                self.store.append_investigation_event(
                    investigation_id,
                    event_type=SPECIALIST_BOARD_FORMED_EVENT,
                    payload={
                        "execution_owner": "underlying_agent",
                        "chair": dict(_CHAIR),
                        "members": members,
                    },
                )
                board = project_specialist_board(
                    self.store.replay_investigation_events(investigation_id)
                )
                if not isinstance(board, dict):
                    raise RuntimeError("specialist board event produced no projection")
                try:
                    self._require_investigation_authorization(
                        investigation_id, intent="resume"
                    )
                except LabError:
                    pass
                else:
                    authorization_active = True
                retry_reused = False
        return {
            "status": "formed",
            "specialist_board": board,
            "execution_owner": "underlying_agent",
            "task_lifecycle": "owned_by_underlying_agent",
            "retry_reused": retry_reused,
            "next_action": {
                "operation": (
                    "genomilab.submit_plan"
                    if authorization_active
                    else "genomilab.prepare_authorization"
                ),
                "reason": (
                    "underlying_agent_should_plan_next"
                    if authorization_active
                    else "patient_context_approval_required"
                ),
            },
        }

    def report_agent_specialist_progress(
        self: _SpecialistBoardApplication,
        investigation_id: str,
        *,
        round_id: str,
        specialist_id: str,
        status: str,
        current_work: str,
    ) -> JsonObject:
        investigation = self.investigation(investigation_id)
        try:
            progress = canonical_specialist_progress(
                specialist_id=specialist_id,
                status=status,
                current_work=current_work,
            )
        except ValueError as exc:
            raise LabError("invalid_specialist_progress", str(exc)) from exc

        with self.store.atomic_write():
            events = self.store.replay_investigation_events(investigation_id)
            board = project_specialist_board(events)
            if not isinstance(board, dict):
                raise LabError(
                    "specialist_board_required",
                    "Form the specialist board before reporting specialist progress.",
                    http_status=409,
                )
            self._require_investigation_authorization(
                investigation_id, intent="resume"
            )
            current_round = investigation.get("current_round")
            if not isinstance(current_round, dict):
                raise LabError(
                    "specialist_round_required",
                    "Submit an investigation round before reporting specialist progress.",
                    http_status=409,
                )
            if str(current_round.get("round_id")) != str(round_id):
                raise LabError(
                    "specialist_round_conflict",
                    "Specialist progress can be reported only for the current investigation round.",
                    http_status=409,
                )
            member = next(
                (
                    item
                    for item in current_round["members"]
                    if item["specialist_id"] == progress["specialist_id"]
                ),
                None,
            )
            if not isinstance(member, dict):
                raise LabError(
                    "specialist_not_found",
                    "That specialist is not part of this investigation board.",
                    http_status=404,
                )
            if (
                member.get("status") == progress["status"]
                and member.get("current_work") == progress["current_work"]
            ):
                retry_reused = True
                board = investigation.get("specialist_board")
                if not isinstance(board, dict):
                    raise RuntimeError(
                        "specialist progress retry produced no board projection"
                    )
            elif member.get("status") == "completed":
                raise LabError(
                    "specialist_progress_conflict",
                    "A completed specialist assignment cannot be reopened or changed.",
                    http_status=409,
                )
            else:
                self.store.append_investigation_event(
                    investigation_id,
                    event_type=SPECIALIST_PROGRESS_REPORTED_EVENT,
                    payload={"round_id": str(round_id), **progress},
                )
                refreshed = self.investigation(investigation_id)
                current_round = refreshed.get("current_round")
                board = refreshed.get("specialist_board")
                if not isinstance(board, dict) or not isinstance(
                    current_round, dict
                ):
                    raise RuntimeError(
                        "specialist progress event produced no projection"
                    )
                retry_reused = False
        return {
            "status": "recorded",
            "specialist_board": board,
            "investigation_round": current_round,
            "execution_owner": "underlying_agent",
            "task_lifecycle": "owned_by_underlying_agent",
            "retry_reused": retry_reused,
        }

    def record_agent_specialist_report(
        self: _SpecialistBoardApplication,
        investigation_id: str,
        *,
        round_id: str,
        specialist_id: str,
        report: JsonObject,
    ) -> JsonObject:
        from .investigation_rounds import (
            SPECIALIST_REPORT_USE_BOUNDARY,
            canonical_specialist_report,
        )

        investigation = self.investigation(investigation_id)
        try:
            specialist = _specialist_id(specialist_id)
            canonical_report = canonical_specialist_report(report)
        except ValueError as exc:
            raise LabError("invalid_specialist_report", str(exc)) from exc
        with self.store.atomic_write():
            self._require_investigation_authorization(
                investigation_id, intent="resume"
            )
            current_round = investigation.get("current_round")
            if not isinstance(current_round, dict):
                raise LabError(
                    "specialist_round_required",
                    "Submit an investigation round before recording specialist reports.",
                    http_status=409,
                )
            if str(current_round.get("round_id")) != str(round_id):
                raise LabError(
                    "specialist_round_conflict",
                    "Specialist reports can be recorded only for the current investigation round.",
                    http_status=409,
                )
            member = next(
                (
                    item
                    for item in current_round.get("members") or []
                    if isinstance(item, dict)
                    and item.get("specialist_id") == specialist
                ),
                None,
            )
            if not isinstance(member, dict):
                raise LabError(
                    "specialist_not_found",
                    "That specialist is not assigned to this investigation round.",
                    http_status=404,
                )
            existing = member.get("report")
            if isinstance(existing, dict):
                if existing.get("report") != canonical_report:
                    raise LabError(
                        "specialist_report_conflict",
                        "A different specialist report is already committed for this round.",
                        http_status=409,
                    )
                committed = existing
                retry_reused = True
            else:
                try:
                    committed, store_reused = self.store.commit_specialist_round_report(
                        investigation_id,
                        round_id=str(round_id),
                        specialist_id=specialist,
                        report=canonical_report,
                    )
                except (KeyError, ValueError) as exc:
                    raise LabError(
                        "invalid_specialist_report", str(exc), http_status=409
                    ) from exc
                if not store_reused:
                    self.store.append_investigation_event(
                        investigation_id,
                        event_type=SPECIALIST_REPORT_RECORDED_EVENT,
                        payload={
                            "round_id": str(round_id),
                            "specialist_id": specialist,
                            "report_id": committed.get("report_id"),
                            "finding_count": len(canonical_report["findings"]),
                            "gap_count": len(canonical_report["gaps"]),
                        },
                    )
                retry_reused = store_reused
            refreshed = self.investigation(investigation_id)
            current_round = refreshed.get("current_round")
            board = refreshed.get("specialist_board")
            if not isinstance(board, dict) or not isinstance(current_round, dict):
                raise RuntimeError("specialist report produced no round projection")
        return {
            "status": "recorded",
            "specialist_report": {
                **committed,
                "use_boundary": dict(SPECIALIST_REPORT_USE_BOUNDARY),
            },
            "specialist_board": board,
            "investigation_round": current_round,
            "execution_owner": "underlying_agent",
            "task_lifecycle": "owned_by_underlying_agent",
            "retry_reused": retry_reused,
        }

    def _require_specialist_board(
        self: _SpecialistBoardApplication, investigation_id: str
    ) -> JsonObject:
        investigation = self.investigation(investigation_id)
        board = investigation.get("specialist_board")
        if not isinstance(board, dict):
            raise LabError(
                "specialist_board_required",
                "Form the specialist board before continuing this investigation.",
                http_status=409,
            )
        return board


__all__ = [
    "SPECIALIST_BOARD_FORMED_EVENT",
    "SPECIALIST_BOARD_MAX_MEMBERS",
    "SPECIALIST_BOARD_MIN_MEMBERS",
    "SPECIALIST_CURRENT_WORK_MAX",
    "SPECIALIST_PROGRESS_REPORTED_EVENT",
    "SPECIALIST_REPORT_RECORDED_EVENT",
    "SPECIALIST_PROGRESS_STATUSES",
    "SPECIALIST_ROLE_MAX",
    "SPECIALIST_TASK_MAX",
    "SpecialistBoardApplicationMixin",
    "canonical_specialist_progress",
    "canonical_specialists",
    "project_specialist_board",
    "specialist_board_handle",
]
