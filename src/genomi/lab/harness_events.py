"""Harness results, events, and ephemeral ordered replay transport."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from .harness_transport import (
    PROTOCOL_VERSION,
    frozen_json_object,
    required_identifier,
    required_text,
    safe_json_dumps,
    safe_json_value,
)
from .harness_types import (
    BindingStatus,
    CancellationOutcome,
    HarnessArtifactKind,
    HarnessErrorCode,
    HarnessEventKind,
    HarnessEventStatus,
    HarnessOperation,
    ReplayStatus,
)


@dataclass(frozen=True, slots=True)
class AgentStartedPayload:
    agent_id: str
    role: str
    assigned_step_id: str

    def __post_init__(self) -> None:
        for name in ("agent_id", "role", "assigned_step_id"):
            object.__setattr__(
                self, name, required_identifier(getattr(self, name), name)
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "assigned_step_id": self.assigned_step_id,
        }


@dataclass(frozen=True, slots=True)
class AgentProgressPayload:
    agent_id: str
    assigned_step_id: str
    progress: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "agent_id", required_identifier(self.agent_id, "agent_id")
        )
        object.__setattr__(
            self,
            "assigned_step_id",
            required_identifier(self.assigned_step_id, "assigned_step_id"),
        )
        object.__setattr__(
            self, "progress", required_text(self.progress, "progress", 2_000)
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "agent_id": self.agent_id,
            "assigned_step_id": self.assigned_step_id,
            "progress": self.progress,
        }


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    artifact_id: str
    kind: HarnessArtifactKind
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", required_identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(self, "kind", HarnessArtifactKind(self.kind))
        if not isinstance(self.sha256, str) or len(self.sha256) != 64:
            raise ValueError("sha256 must be a hexadecimal SHA-256 digest")
        try:
            int(self.sha256, 16)
        except ValueError as exc:
            raise ValueError("sha256 must be a hexadecimal SHA-256 digest") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind.value,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class HarnessEvent:
    event_id: str
    kind: HarnessEventKind
    workspace_session_id: str
    host_id: str
    task_id: str
    run_id: str
    investigation_id: str
    user_id: str
    cursor: int
    correlation_id: str
    status: HarnessEventStatus
    timestamp: str
    payload: Mapping[str, Any]
    proposed_artifacts: tuple[ArtifactReference, ...] = ()
    job_id: str | None = None
    protocol_version: str = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", HarnessEventKind(self.kind))
        object.__setattr__(self, "status", HarnessEventStatus(self.status))
        for name in (
            "event_id",
            "workspace_session_id",
            "host_id",
            "task_id",
            "run_id",
            "investigation_id",
            "user_id",
            "correlation_id",
            "protocol_version",
        ):
            object.__setattr__(
                self, name, required_identifier(getattr(self, name), name)
            )
        if self.job_id is not None:
            object.__setattr__(
                self, "job_id", required_identifier(self.job_id, "job_id")
            )
        if (
            not isinstance(self.cursor, int)
            or isinstance(self.cursor, bool)
            or self.cursor < 1
        ):
            raise ValueError("cursor must be a positive integer")
        timestamp = required_text(self.timestamp, "timestamp", 100)
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be an ISO-8601 date-time") from exc
        if parsed_timestamp.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "payload", frozen_json_object(self.payload, "payload"))
        object.__setattr__(self, "proposed_artifacts", tuple(self.proposed_artifacts))
        _validate_typed_event_payload(self.kind, self.status, self.payload)

    def to_dict(self) -> dict[str, Any]:
        return safe_json_value(
            {
                "protocol_version": self.protocol_version,
                "event_id": self.event_id,
                "kind": self.kind,
                "workspace_session_id": self.workspace_session_id,
                "host_id": self.host_id,
                "task_id": self.task_id,
                "run_id": self.run_id,
                "investigation_id": self.investigation_id,
                "user_id": self.user_id,
                "cursor": self.cursor,
                "correlation_id": self.correlation_id,
                "job_id": self.job_id,
                "status": self.status,
                "timestamp": self.timestamp,
                "payload": self.payload,
                "proposed_artifacts": [
                    reference.to_dict() for reference in self.proposed_artifacts
                ],
            }
        )


@dataclass(frozen=True, slots=True)
class HarnessProtocolError:
    code: HarnessErrorCode
    message: str
    retryable: bool
    current_revision: int
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", HarnessErrorCode(self.code))
        object.__setattr__(
            self, "message", required_text(self.message, "message", 2_000)
        )
        object.__setattr__(self, "details", frozen_json_object(self.details, "details"))
        if not isinstance(self.retryable, bool):
            raise ValueError("retryable must be a boolean")
        if not isinstance(self.current_revision, int) or self.current_revision < 0:
            raise ValueError("current_revision must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return safe_json_value(
            {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "current_revision": self.current_revision,
                "details": self.details,
            }
        )


@dataclass(frozen=True, slots=True)
class TaskRunResult:
    task_id: str
    run_id: str
    binding_status: BindingStatus
    proposed_artifact: Mapping[str, Any] | None
    proposed_artifact_reference: ArtifactReference | None
    latest_cursor: int
    replaced_task_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "task_id", required_identifier(self.task_id, "task_id")
        )
        object.__setattr__(self, "run_id", required_identifier(self.run_id, "run_id"))
        object.__setattr__(self, "binding_status", BindingStatus(self.binding_status))
        if not isinstance(self.latest_cursor, int) or self.latest_cursor < 0:
            raise ValueError("latest_cursor must be a non-negative integer")
        if self.replaced_task_id is not None:
            object.__setattr__(
                self,
                "replaced_task_id",
                required_identifier(self.replaced_task_id, "replaced_task_id"),
            )
        if self.proposed_artifact is not None:
            object.__setattr__(
                self,
                "proposed_artifact",
                frozen_json_object(self.proposed_artifact, "proposed_artifact"),
            )

    def to_dict(self) -> dict[str, Any]:
        return safe_json_value(
            {
                "task_id": self.task_id,
                "run_id": self.run_id,
                "binding_status": self.binding_status,
                "proposed_artifact": self.proposed_artifact,
                "proposed_artifact_reference": (
                    self.proposed_artifact_reference.to_dict()
                    if self.proposed_artifact_reference
                    else None
                ),
                "latest_cursor": self.latest_cursor,
                "replaced_task_id": self.replaced_task_id,
            }
        )


@dataclass(frozen=True, slots=True)
class CancellationResult:
    outcome: CancellationOutcome
    task_id: str
    run_id: str | None
    external_jobs_confirmed_cancelled: bool
    latest_cursor: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", CancellationOutcome(self.outcome))
        object.__setattr__(
            self, "task_id", required_identifier(self.task_id, "task_id")
        )
        if self.run_id is not None:
            object.__setattr__(
                self, "run_id", required_identifier(self.run_id, "run_id")
            )
        if not isinstance(self.external_jobs_confirmed_cancelled, bool):
            raise ValueError("external_jobs_confirmed_cancelled must be a boolean")
        if not isinstance(self.latest_cursor, int) or self.latest_cursor < 0:
            raise ValueError("latest_cursor must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return safe_json_value(
            {
                "outcome": self.outcome,
                "task_id": self.task_id,
                "run_id": self.run_id,
                "external_jobs_confirmed_cancelled": self.external_jobs_confirmed_cancelled,
                "latest_cursor": self.latest_cursor,
            }
        )


HarnessResult = TaskRunResult | CancellationResult


@dataclass(frozen=True, slots=True)
class HarnessResponse:
    command_id: str
    operation: HarnessOperation
    accepted_revision: int | None
    current_revision: int
    result: HarnessResult | None = None
    error: HarnessProtocolError | None = None
    protocol_version: str = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "command_id", required_identifier(self.command_id, "command_id")
        )
        object.__setattr__(self, "operation", HarnessOperation(self.operation))
        object.__setattr__(
            self,
            "protocol_version",
            required_identifier(self.protocol_version, "protocol_version"),
        )
        if (self.result is None) == (self.error is None):
            raise ValueError("harness response requires exactly one of result or error")
        if not isinstance(self.current_revision, int) or self.current_revision < 0:
            raise ValueError("current_revision must be a non-negative integer")
        if self.accepted_revision is not None and (
            not isinstance(self.accepted_revision, int) or self.accepted_revision < 0
        ):
            raise ValueError("accepted_revision must be a non-negative integer")

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        return safe_json_value(
            {
                "protocol_version": self.protocol_version,
                "command_id": self.command_id,
                "operation": self.operation,
                "accepted_revision": self.accepted_revision,
                "current_revision": self.current_revision,
                "result": self.result.to_dict() if self.result else None,
                "error": self.error.to_dict() if self.error else None,
            }
        )


@dataclass(frozen=True, slots=True)
class EventAcceptance:
    accepted: bool
    duplicate: bool
    cursor: int | None
    error: HarnessProtocolError | None = None


@dataclass(frozen=True, slots=True)
class EventReplay:
    status: ReplayStatus
    events: tuple[HarnessEvent, ...]
    after_cursor: int
    earliest_available_cursor: int
    latest_cursor: int

    def to_dict(self) -> dict[str, Any]:
        return safe_json_value(
            {
                "status": self.status,
                "events": [event.to_dict() for event in self.events],
                "after_cursor": self.after_cursor,
                "earliest_available_cursor": self.earliest_available_cursor,
                "latest_cursor": self.latest_cursor,
            }
        )


class HarnessEventBuffer:
    """Ephemeral ordered/deduplicated transport buffer with cursor replay."""

    def __init__(self, *, replay_window: int = 1_000) -> None:
        if replay_window < 1:
            raise ValueError("replay_window must be positive")
        self._replay_window = replay_window
        self._events: dict[str, list[HarnessEvent]] = {}
        self._cursor_floors: dict[str, int] = {}
        self._event_fingerprints: dict[str, str] = {}
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)

    def latest_cursor(self, investigation_id: str) -> int:
        with self._lock:
            events = self._events.get(investigation_id, [])
            return (
                events[-1].cursor
                if events
                else self._cursor_floors.get(investigation_id, 0)
            )

    def seed_cursor(self, investigation_id: str, cursor: int) -> None:
        """Recover a durable cursor without fabricating a replayable event."""

        if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0:
            raise ValueError("cursor must be a non-negative integer")
        with self._lock:
            if self._events.get(investigation_id):
                return
            self._cursor_floors[investigation_id] = max(
                self._cursor_floors.get(investigation_id, 0), cursor
            )

    def existing_event(self, event: HarnessEvent) -> EventAcceptance | None:
        """Classify an existing event ID without accepting new event content."""

        fingerprint = safe_json_dumps(event.to_dict())
        with self._lock:
            existing = self._event_fingerprints.get(event.event_id)
        if existing is None:
            return None
        if existing == fingerprint:
            return EventAcceptance(True, True, event.cursor)
        return EventAcceptance(
            False,
            False,
            None,
            HarnessProtocolError(
                HarnessErrorCode.EVENT_ID_COLLISION,
                "event_id was already used for different event content",
                False,
                0,
                {"event_id": event.event_id},
            ),
        )

    def append(self, event: HarnessEvent) -> EventAcceptance:
        fingerprint = safe_json_dumps(event.to_dict())
        with self._lock:
            existing = self._event_fingerprints.get(event.event_id)
            if existing is not None:
                if existing == fingerprint:
                    return EventAcceptance(True, True, event.cursor)
                return EventAcceptance(
                    False,
                    False,
                    None,
                    HarnessProtocolError(
                        HarnessErrorCode.EVENT_ID_COLLISION,
                        "event_id was already used for different event content",
                        False,
                        0,
                        {"event_id": event.event_id},
                    ),
                )
            current = self._events.setdefault(event.investigation_id, [])
            if current:
                first = current[0]
                expected_identity = (
                    first.protocol_version,
                    first.host_id,
                    first.user_id,
                )
                received_identity = (
                    event.protocol_version,
                    event.host_id,
                    event.user_id,
                )
                if received_identity != expected_identity:
                    return EventAcceptance(
                        False,
                        False,
                        None,
                        HarnessProtocolError(
                            HarnessErrorCode.INVALID_EVENT,
                            "event identity does not match the investigation event stream",
                            False,
                            0,
                        ),
                    )
            expected_cursor = (
                current[-1].cursor + 1
                if current
                else self._cursor_floors.get(event.investigation_id, 0) + 1
            )
            if event.cursor != expected_cursor:
                return EventAcceptance(
                    False,
                    False,
                    None,
                    HarnessProtocolError(
                        HarnessErrorCode.EVENT_ORDER_CONFLICT,
                        "event cursor is not the next monotonic investigation cursor",
                        True,
                        0,
                        {
                            "expected_cursor": expected_cursor,
                            "received_cursor": event.cursor,
                        },
                    ),
                )
            current.append(event)
            self._event_fingerprints[event.event_id] = fingerprint
            if len(current) > self._replay_window:
                expired = current[: len(current) - self._replay_window]
                del current[: len(expired)]
                for expired_event in expired:
                    self._event_fingerprints.pop(expired_event.event_id, None)
            self._changed.notify_all()
            return EventAcceptance(True, False, event.cursor)

    def clear(self) -> None:
        """Release all session-owned replay and deduplication state."""

        with self._lock:
            self._events.clear()
            self._cursor_floors.clear()
            self._event_fingerprints.clear()
            self._changed.notify_all()

    def discard_investigation(self, investigation_id: str) -> None:
        """Expire one complete process-local replay/correlation window."""

        with self._lock:
            expired = self._events.pop(investigation_id, ())
            for event in expired:
                self._event_fingerprints.pop(event.event_id, None)
            self._cursor_floors.pop(investigation_id, None)
            self._changed.notify_all()

    def correlation_ids(self, investigation_id: str) -> frozenset[str]:
        """Return command IDs still referenced by the replayable event window."""

        with self._lock:
            return frozenset(
                event.correlation_id
                for event in self._events.get(investigation_id, ())
            )

    def wait_for_cursor(
        self,
        investigation_id: str,
        *,
        after_cursor: int,
        timeout_seconds: float,
    ) -> bool:
        """Wait until a real accepted event advances the transport cursor."""

        if not isinstance(after_cursor, int) or isinstance(after_cursor, bool):
            raise ValueError("after_cursor must be an integer")
        if after_cursor < 0:
            raise ValueError("after_cursor must be non-negative")
        if not isinstance(timeout_seconds, (int, float)) or isinstance(
            timeout_seconds, bool
        ):
            raise ValueError("timeout_seconds must be a number")
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        with self._changed:
            if self.latest_cursor(investigation_id) > after_cursor:
                return True
            self._changed.wait_for(
                lambda: self.latest_cursor(investigation_id) > after_cursor,
                timeout=float(timeout_seconds),
            )
            return self.latest_cursor(investigation_id) > after_cursor

    def replay(self, investigation_id: str, *, after_cursor: int) -> EventReplay:
        if (
            not isinstance(after_cursor, int)
            or isinstance(after_cursor, bool)
            or after_cursor < 0
        ):
            raise ValueError("after_cursor must be a non-negative integer")
        with self._lock:
            events = tuple(self._events.get(investigation_id, ()))
            cursor_floor = self._cursor_floors.get(investigation_id, 0)
        earliest = events[0].cursor if events else 0
        latest = events[-1].cursor if events else cursor_floor
        if not events and (
            (cursor_floor and after_cursor < cursor_floor)
            or (not cursor_floor and after_cursor > 0)
        ):
            return EventReplay(
                ReplayStatus.SNAPSHOT_REQUIRED,
                (),
                after_cursor,
                earliest,
                latest,
            )
        if events and after_cursor < earliest - 1:
            return EventReplay(
                ReplayStatus.SNAPSHOT_REQUIRED,
                (),
                after_cursor,
                earliest,
                latest,
            )
        return EventReplay(
            ReplayStatus.EVENTS,
            tuple(event for event in events if event.cursor > after_cursor),
            after_cursor,
            earliest,
            latest,
        )


def _validate_typed_event_payload(
    kind: HarnessEventKind,
    status: HarnessEventStatus,
    payload: Mapping[str, Any],
) -> None:
    if kind == HarnessEventKind.AGENT_STARTED:
        expected_fields = {"agent_id", "role", "assigned_step_id"}
        if status != HarnessEventStatus.RUNNING or set(payload) != expected_fields:
            raise ValueError("agent_started requires a running AgentStartedPayload")
        AgentStartedPayload(**dict(payload))
    elif kind == HarnessEventKind.AGENT_PROGRESS:
        expected_fields = {"agent_id", "assigned_step_id", "progress"}
        if status != HarnessEventStatus.RUNNING or set(payload) != expected_fields:
            raise ValueError("agent_progress requires a running AgentProgressPayload")
        AgentProgressPayload(**dict(payload))
    elif kind == HarnessEventKind.JOB_IN_PROGRESS:
        if status != HarnessEventStatus.RUNNING or set(payload) != {"host_state"}:
            raise ValueError("job_in_progress requires a running host_state")
        required_identifier(payload.get("host_state"), "host_state")
    elif kind == HarnessEventKind.CANCELLED:
        if status != HarnessEventStatus.CANCELLED or set(payload) != {
            "external_jobs_confirmed_cancelled"
        }:
            raise ValueError("cancelled requires its confirmed cancellation scope")
        if not isinstance(payload.get("external_jobs_confirmed_cancelled"), bool):
            raise ValueError("external_jobs_confirmed_cancelled must be a boolean")
