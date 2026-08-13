"""Typed commands and capability negotiation for harness adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .harness_transport import (
    PROTOCOL_VERSION,
    frozen_json_object,
    required_identifier,
    required_text,
    safe_json_value,
)


class HarnessOperation(str, Enum):
    START_TASK_RUN = "start_task_run"
    RESUME_TASK_RUN = "resume_task_run"
    SEND_TASK_MESSAGE = "send_task_message"
    CANCEL_TASK_WORK = "cancel_task_work"
    REPLACE_TASK_BINDING = "replace_task_binding"


class HarnessArtifactKind(str, Enum):
    PLAN = "plan"
    EXECUTION_REPORT = "execution_report"
    BRIEF_DRAFT = "brief_draft"


class HarnessEventKind(str, Enum):
    PLAN_PROPOSED = "plan_proposed"
    APPROVAL_REQUIRED = "approval_required"
    AGENT_STARTED = "agent_started"
    AGENT_PROGRESS = "agent_progress"
    EVIDENCE_RETURNED = "evidence_returned"
    CAPABILITY_EXECUTION_COMPLETED = "capability_execution_completed"
    SOURCE_UNAVAILABLE = "source_unavailable"
    JOB_IN_PROGRESS = "job_in_progress"
    NEEDS_USER_INPUT = "needs_user_input"
    BRIEF_COMPLETED = "brief_completed"
    BRIEF_UPDATED = "brief_updated"
    CANCELLED = "cancelled"
    FAILED = "failed"


class HarnessEventStatus(str, Enum):
    PROPOSED = "proposed"
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class HarnessErrorCode(str, Enum):
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    REVISION_CONFLICT = "revision_conflict"
    INVALID_COMMAND = "invalid_command"
    INVALID_EVENT = "invalid_event"
    BINDING_NOT_FOUND = "binding_not_found"
    BINDING_CONFLICT = "binding_conflict"
    EVENT_ORDER_CONFLICT = "event_order_conflict"
    EVENT_ID_COLLISION = "event_id_collision"
    HOST_EXECUTION_FAILED = "host_execution_failed"


class CancellationOutcome(str, Enum):
    CANCELLED = "cancelled"
    ALREADY_COMPLETED = "already_completed"
    NOT_CANCELLABLE = "not_cancellable"
    FAILED = "failed"


class ReplayStatus(str, Enum):
    EVENTS = "events"
    SNAPSHOT_REQUIRED = "snapshot_required"


class BindingStatus(str, Enum):
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class HarnessCapabilityManifest:
    adapter_id: str
    host_kind: str
    host_version: str | None
    available: bool
    supported_protocol_versions: tuple[str, ...]
    supported_operations: tuple[HarnessOperation, ...]
    event_streaming: bool
    event_replay: bool
    artifact_kinds: tuple[HarnessArtifactKind, ...]
    agent_delegation_planning: bool
    agent_delegation_event_reporting: bool
    background_job_attach: bool
    background_job_cancel: bool
    approved_context_delivery: bool
    workspace_session_persistence: str
    execution_location: str
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter_id", required_identifier(self.adapter_id, "adapter_id"))
        object.__setattr__(self, "host_kind", required_identifier(self.host_kind, "host_kind"))
        object.__setattr__(
            self,
            "supported_operations",
            tuple(HarnessOperation(value) for value in self.supported_operations),
        )
        object.__setattr__(
            self,
            "artifact_kinds",
            tuple(HarnessArtifactKind(value) for value in self.artifact_kinds),
        )
        if self.available and not self.host_version:
            raise ValueError("available harness requires host_version")
        if not self.available and self.supported_operations:
            raise ValueError("unavailable harness cannot advertise operations")

    def supports(self, operation: HarnessOperation) -> bool:
        return self.available and operation in self.supported_operations

    def to_dict(self) -> dict[str, Any]:
        return safe_json_value(
            {
                "adapter_id": self.adapter_id,
                "host_kind": self.host_kind,
                "host_version": self.host_version,
                "available": self.available,
                "supported_protocol_versions": self.supported_protocol_versions,
                "supported_operations": self.supported_operations,
                "event_streaming": self.event_streaming,
                "event_replay": self.event_replay,
                "event_kinds": tuple(HarnessEventKind),
                "artifact_kinds": self.artifact_kinds,
                "agent_delegation_planning": self.agent_delegation_planning,
                "agent_delegation_event_reporting": self.agent_delegation_event_reporting,
                "background_job_attach": self.background_job_attach,
                "background_job_cancel": self.background_job_cancel,
                "approved_context_delivery": self.approved_context_delivery,
                "workspace_session_persistence": self.workspace_session_persistence,
                "execution_location": self.execution_location,
                "unavailable_reason": self.unavailable_reason,
            }
        )


@dataclass(frozen=True, slots=True)
class StartTaskRunPayload:
    question: str
    approved_context: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "question", required_text(self.question, "question"))
        object.__setattr__(
            self,
            "approved_context",
            frozen_json_object(self.approved_context, "approved_context"),
        )

    def to_dict(self) -> dict[str, Any]:
        return safe_json_value(
            {"question": self.question, "approved_context": self.approved_context}
        )


@dataclass(frozen=True, slots=True)
class ResumeTaskRunPayload:
    instruction: str
    approved_context: Mapping[str, Any] = field(default_factory=dict)
    artifact_kind: HarnessArtifactKind = HarnessArtifactKind.PLAN

    def __post_init__(self) -> None:
        object.__setattr__(self, "instruction", required_text(self.instruction, "instruction"))
        object.__setattr__(
            self,
            "approved_context",
            frozen_json_object(self.approved_context, "approved_context"),
        )
        object.__setattr__(self, "artifact_kind", HarnessArtifactKind(self.artifact_kind))

    def to_dict(self) -> dict[str, Any]:
        return safe_json_value(
            {
                "instruction": self.instruction,
                "approved_context": self.approved_context,
                "artifact_kind": self.artifact_kind,
            }
        )


@dataclass(frozen=True, slots=True)
class SendTaskMessagePayload:
    message: str
    approved_context: Mapping[str, Any] = field(default_factory=dict)
    artifact_kind: HarnessArtifactKind = HarnessArtifactKind.BRIEF_DRAFT

    def __post_init__(self) -> None:
        object.__setattr__(self, "message", required_text(self.message, "message"))
        object.__setattr__(
            self,
            "approved_context",
            frozen_json_object(self.approved_context, "approved_context"),
        )
        object.__setattr__(self, "artifact_kind", HarnessArtifactKind(self.artifact_kind))

    def to_dict(self) -> dict[str, Any]:
        return safe_json_value(
            {
                "message": self.message,
                "approved_context": self.approved_context,
                "artifact_kind": self.artifact_kind,
            }
        )


@dataclass(frozen=True, slots=True)
class CancelTaskWorkPayload:
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.reason is not None:
            object.__setattr__(self, "reason", required_text(self.reason, "reason", 2_000))

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason}


@dataclass(frozen=True, slots=True)
class ReplaceTaskBindingPayload:
    reason: str
    question: str
    approved_context: Mapping[str, Any]
    artifact_kind: HarnessArtifactKind = HarnessArtifactKind.PLAN

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", required_text(self.reason, "reason", 2_000))
        object.__setattr__(self, "question", required_text(self.question, "question"))
        object.__setattr__(
            self,
            "approved_context",
            frozen_json_object(self.approved_context, "approved_context"),
        )
        object.__setattr__(self, "artifact_kind", HarnessArtifactKind(self.artifact_kind))

    def to_dict(self) -> dict[str, Any]:
        return safe_json_value(
            {
                "reason": self.reason,
                "question": self.question,
                "approved_context": self.approved_context,
                "artifact_kind": self.artifact_kind,
            }
        )


HarnessCommandPayload = (
    StartTaskRunPayload
    | ResumeTaskRunPayload
    | SendTaskMessagePayload
    | CancelTaskWorkPayload
    | ReplaceTaskBindingPayload
)

_PAYLOAD_TYPES: dict[HarnessOperation, type[Any]] = {
    HarnessOperation.START_TASK_RUN: StartTaskRunPayload,
    HarnessOperation.RESUME_TASK_RUN: ResumeTaskRunPayload,
    HarnessOperation.SEND_TASK_MESSAGE: SendTaskMessagePayload,
    HarnessOperation.CANCEL_TASK_WORK: CancelTaskWorkPayload,
    HarnessOperation.REPLACE_TASK_BINDING: ReplaceTaskBindingPayload,
}


@dataclass(frozen=True, slots=True)
class HarnessCommand:
    operation: HarnessOperation
    workspace_session_id: str
    command_id: str
    user_id: str
    investigation_id: str
    expected_revision: int
    payload: HarnessCommandPayload
    protocol_version: str = PROTOCOL_VERSION
    task_id: str | None = None
    run_id: str | None = None
    binding_status: BindingStatus | None = None
    latest_event_cursor: int | None = None
    current_binding_revision: int | None = None

    def __post_init__(self) -> None:
        operation = HarnessOperation(self.operation)
        object.__setattr__(self, "operation", operation)
        for name in (
            "protocol_version",
            "workspace_session_id",
            "command_id",
            "user_id",
            "investigation_id",
        ):
            object.__setattr__(self, name, required_identifier(getattr(self, name), name))
        if self.task_id is not None:
            object.__setattr__(self, "task_id", required_identifier(self.task_id, "task_id"))
        if self.run_id is not None:
            object.__setattr__(self, "run_id", required_identifier(self.run_id, "run_id"))
        if self.binding_status is not None:
            object.__setattr__(self, "binding_status", BindingStatus(self.binding_status))
        if self.latest_event_cursor is not None and (
            not isinstance(self.latest_event_cursor, int)
            or isinstance(self.latest_event_cursor, bool)
            or self.latest_event_cursor < 0
        ):
            raise ValueError("latest_event_cursor must be a non-negative integer")
        if self.current_binding_revision is not None and (
            not isinstance(self.current_binding_revision, int)
            or isinstance(self.current_binding_revision, bool)
            or self.current_binding_revision < 0
        ):
            raise ValueError("current_binding_revision must be a non-negative integer")
        if not isinstance(self.expected_revision, int) or isinstance(self.expected_revision, bool):
            raise ValueError("expected_revision must be an integer")
        if self.expected_revision < 0:
            raise ValueError("expected_revision must not be negative")
        expected_payload_type = _PAYLOAD_TYPES[operation]
        if not isinstance(self.payload, expected_payload_type):
            raise ValueError(
                f"{operation.value} requires payload type {expected_payload_type.__name__}"
            )
        if operation == HarnessOperation.START_TASK_RUN and (self.task_id or self.run_id):
            raise ValueError("start_task_run must not supply task_id or run_id")
        if operation == HarnessOperation.START_TASK_RUN and self.binding_status is not None:
            raise ValueError("start_task_run must not supply binding_status")
        if operation == HarnessOperation.START_TASK_RUN and self.latest_event_cursor is not None:
            raise ValueError("start_task_run must not supply latest_event_cursor")
        if operation == HarnessOperation.START_TASK_RUN and self.current_binding_revision is not None:
            raise ValueError("start_task_run must not supply current_binding_revision")
        if operation != HarnessOperation.START_TASK_RUN and (not self.task_id or not self.run_id):
            raise ValueError(f"{operation.value} requires task_id and run_id")
        if operation != HarnessOperation.START_TASK_RUN and self.binding_status is None:
            raise ValueError(f"{operation.value} requires binding_status")
        if operation != HarnessOperation.START_TASK_RUN and self.latest_event_cursor is None:
            raise ValueError(f"{operation.value} requires latest_event_cursor")
        if operation != HarnessOperation.START_TASK_RUN and self.current_binding_revision is None:
            raise ValueError(f"{operation.value} requires current_binding_revision")

    def to_dict(self) -> dict[str, Any]:
        return safe_json_value(
            {
                "protocol_version": self.protocol_version,
                "operation": self.operation,
                "workspace_session_id": self.workspace_session_id,
                "command_id": self.command_id,
                "user_id": self.user_id,
                "investigation_id": self.investigation_id,
                "task_id": self.task_id,
                "run_id": self.run_id,
                "binding_status": self.binding_status,
                "latest_event_cursor": self.latest_event_cursor,
                "current_binding_revision": self.current_binding_revision,
                "expected_revision": self.expected_revision,
                "payload": self.payload.to_dict(),
            }
        )
