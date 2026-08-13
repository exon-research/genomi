"""Shared lifecycle and concurrency contract for GenomiLab harness adapters."""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import uuid
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .harness_background import (
    HarnessCompletionCallback,
    HarnessIdentityCallback,
    HarnessJobSubmission,
    HarnessSubmissionCallback,
)

from .harness_events import (
    ArtifactReference,
    CancellationResult,
    EventAcceptance,
    EventReplay,
    HarnessEvent,
    HarnessEventBuffer,
    HarnessProtocolError,
    HarnessResponse,
    TaskRunResult,
)
from .harness_transport import (
    frozen_json_object,
    required_identifier,
    safe_json_dumps,
    safe_json_value,
    utc_now,
)
from .harness_types import (
    BindingStatus,
    CancellationOutcome,
    HarnessArtifactKind,
    HarnessCapabilityManifest,
    HarnessCommand,
    HarnessErrorCode,
    HarnessEventKind,
    HarnessEventStatus,
    HarnessOperation,
    ReplaceTaskBindingPayload,
    ResumeTaskRunPayload,
    SendTaskMessagePayload,
    StartTaskRunPayload,
)


@dataclass(slots=True)
class _Binding:
    workspace_session_id: str
    user_id: str
    investigation_id: str
    task_id: str
    run_id: str
    revision: int
    status: BindingStatus


@dataclass(frozen=True, slots=True)
class HostArtifact:
    artifact_kind: HarnessArtifactKind
    artifact: Mapping[str, Any]
    host_task_id: str | None = None
    host_run_id: str | None = None
    trace_events: tuple[HostTraceEvent, ...] = ()
    trace_events_complete: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_kind", HarnessArtifactKind(self.artifact_kind)
        )
        object.__setattr__(
            self,
            "artifact",
            frozen_json_object(self.artifact, "artifact"),
        )
        if self.host_task_id is not None:
            object.__setattr__(
                self,
                "host_task_id",
                required_identifier(self.host_task_id, "host_task_id"),
            )
        if self.host_run_id is not None:
            object.__setattr__(
                self,
                "host_run_id",
                required_identifier(self.host_run_id, "host_run_id"),
            )
        object.__setattr__(self, "trace_events", tuple(self.trace_events))
        if not isinstance(self.trace_events_complete, bool):
            raise ValueError("trace_events_complete must be a boolean")


@dataclass(frozen=True, slots=True)
class HostTraceEvent:
    """A truthful host notification normalized before identity is attached."""

    kind: HarnessEventKind
    status: HarnessEventStatus
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", HarnessEventKind(self.kind))
        object.__setattr__(self, "status", HarnessEventStatus(self.status))
        object.__setattr__(
            self,
            "payload",
            frozen_json_object(self.payload, "trace_event.payload"),
        )


@dataclass(frozen=True, slots=True)
class HarnessDynamicToolCall:
    """Identity-only request for an already validated GenomiLab plan capability."""

    command_id: str
    investigation_id: str
    thread_id: str
    turn_id: str
    call_id: str
    capability: str
    request_id: str

    def __post_init__(self) -> None:
        for name in (
            "command_id",
            "investigation_id",
            "thread_id",
            "turn_id",
            "call_id",
            "capability",
            "request_id",
        ):
            object.__setattr__(
                self, name, required_identifier(getattr(self, name), name)
            )


DynamicToolHandler = Callable[[HarnessDynamicToolCall], Mapping[str, Any]]


class HostInvocationUnavailable(RuntimeError):
    pass


class HarnessAdapter(ABC):
    """Abstract protocol adapter; durable domain state belongs elsewhere."""

    def __init__(
        self,
        manifest: HarnessCapabilityManifest,
        *,
        replay_window: int = 1_000,
        investigation_window: int = 128,
        command_window: int | None = None,
    ) -> None:
        if (
            isinstance(investigation_window, bool)
            or not isinstance(investigation_window, int)
            or investigation_window < 1
        ):
            raise ValueError("investigation_window must be a positive integer")
        command_window = replay_window if command_window is None else command_window
        if (
            isinstance(command_window, bool)
            or not isinstance(command_window, int)
            or command_window < replay_window
        ):
            raise ValueError("command_window must be at least replay_window")
        self._manifest = manifest
        self._events = HarnessEventBuffer(replay_window=replay_window)
        self._investigation_window = investigation_window
        self._command_window = command_window
        self._investigations: OrderedDict[str, None] = OrderedDict()
        self._bindings: OrderedDict[str, _Binding] = OrderedDict()
        self._command_cache: OrderedDict[
            str, tuple[str, HarnessResponse, HarnessCommand]
        ] = OrderedDict()
        self._dynamic_tool_handler: DynamicToolHandler | None = None
        self._lock = threading.RLock()

    @property
    def manifest(self) -> HarnessCapabilityManifest:
        return self._manifest

    def capability_manifest(self) -> HarnessCapabilityManifest:
        return self._manifest

    def start_task_run(self, command: HarnessCommand) -> HarnessResponse:
        return self._execute(command, HarnessOperation.START_TASK_RUN)

    def resume_task_run(self, command: HarnessCommand) -> HarnessResponse:
        return self._execute(command, HarnessOperation.RESUME_TASK_RUN)

    def send_task_message(self, command: HarnessCommand) -> HarnessResponse:
        return self._execute(command, HarnessOperation.SEND_TASK_MESSAGE)

    def cancel_task_work(self, command: HarnessCommand) -> HarnessResponse:
        return self._execute(command, HarnessOperation.CANCEL_TASK_WORK)

    def replace_task_binding(self, command: HarnessCommand) -> HarnessResponse:
        return self._execute(command, HarnessOperation.REPLACE_TASK_BINDING)

    def replay_events(self, investigation_id: str, *, after_cursor: int) -> EventReplay:
        return self._events.replay(investigation_id, after_cursor=after_cursor)

    def wait_for_events(
        self,
        investigation_id: str,
        *,
        after_cursor: int,
        timeout_seconds: float,
    ) -> bool:
        """Wait for the adapter's truthful event stream to advance."""

        return self._events.wait_for_cursor(
            investigation_id,
            after_cursor=after_cursor,
            timeout_seconds=timeout_seconds,
        )

    def close(self) -> None:
        """Release ephemeral state owned by this adapter session."""

        with self._lock:
            self._investigations.clear()
            self._bindings.clear()
            self._command_cache.clear()
            self._events.clear()

    def dispatch_background(
        self,
        command: HarnessCommand,
        *,
        submission_callback: HarnessSubmissionCallback,
        identity_callback: HarnessIdentityCallback,
        completion_callback: HarnessCompletionCallback,
    ) -> HarnessJobSubmission:
        """Start a host-owned turn without blocking the application request.

        Adapters advertise this only when the host has a truthful attachable
        background lifecycle.  The default deliberately refuses instead of
        wrapping a synchronous adapter in a pretend job.
        """

        raise HostInvocationUnavailable(
            "the installed harness does not expose attachable background work"
        )

    def background_job(self, job_id: str) -> HarnessJobSubmission | None:
        """Return a job only while this adapter instance still owns its lifecycle.

        A durable GenomiLab job row is not proof that a newly created adapter can
        still observe or interrupt the host turn.  Background-capable adapters
        must override this method with their truthful live ownership state.
        """

        del job_id
        return None

    def retry_background_completion(
        self, job_id: str
    ) -> HarnessJobSubmission | None:
        """Retry an owned terminal job's durable completion acknowledgement.

        The base adapter has no process-local completion callback to replay.
        Background-capable adapters override this when they can retry only the
        persistence callback without executing the agent turn again.
        """

        return self.background_job(job_id)

    def accept_host_event(self, event: HarnessEvent) -> EventAcceptance:
        """Normalize/test a host event before the application consumes it."""

        existing = self._events.existing_event(event)
        if existing is not None:
            return existing
        if (
            event.protocol_version not in self.manifest.supported_protocol_versions
            or event.host_id != self.manifest.adapter_id
        ):
            binding = self._bindings.get(event.investigation_id)
            return EventAcceptance(
                False,
                False,
                None,
                HarnessProtocolError(
                    HarnessErrorCode.INVALID_EVENT,
                    "event protocol or host identity does not match this adapter",
                    False,
                    binding.revision if binding else 0,
                ),
            )
        with self._lock:
            binding = self._bindings.get(event.investigation_id)
            cached_command = self._command_cache.get(event.correlation_id)
            correlated_command = cached_command[2] if cached_command else None
            correlated_result = cached_command[1].result if cached_command else None
            if (
                binding is None
                or event.workspace_session_id != binding.workspace_session_id
                or event.user_id != binding.user_id
                or event.task_id != binding.task_id
                or event.run_id != binding.run_id
                or correlated_command is None
                or correlated_command.investigation_id != event.investigation_id
                or correlated_command.user_id != event.user_id
                or correlated_command.workspace_session_id
                != event.workspace_session_id
                or correlated_result is None
                or correlated_result.task_id != event.task_id
                or correlated_result.run_id != event.run_id
            ):
                return EventAcceptance(
                    False,
                    False,
                    None,
                    HarnessProtocolError(
                        HarnessErrorCode.INVALID_EVENT,
                        "event identity is not bound to an accepted harness command",
                        False,
                        binding.revision if binding else 0,
                    ),
                )
            self._touch_investigation(event.investigation_id)
            return self._events.append(event)

    def bind_dynamic_tool_handler(self, handler: DynamicToolHandler | None) -> None:
        """Bind the application-owned validated capability gateway.

        The adapter receives no patient store or provider credential.  The
        application callback remains responsible for current-plan validation,
        current-snapshot authorization, disclosure approval, and durable
        idempotency.
        """

        if handler is not None and not callable(handler):
            raise TypeError("dynamic tool handler must be callable")
        with self._lock:
            self._dynamic_tool_handler = handler

    def _invoke_dynamic_tool_handler(
        self, call: HarnessDynamicToolCall
    ) -> Mapping[str, Any]:
        handler = self._dynamic_tool_handler
        if handler is None:
            raise HostInvocationUnavailable(
                "the GenomiLab capability gateway is not bound to this harness"
            )
        result = handler(call)
        if not isinstance(result, Mapping):
            raise ValueError("dynamic tool handler must return an object")
        normalized = safe_json_value(result)
        if not isinstance(normalized, dict):
            raise ValueError("dynamic tool handler must return an object")
        return normalized

    @abstractmethod
    def _produce_artifact(
        self,
        artifact_kind: HarnessArtifactKind,
        command: HarnessCommand,
        instruction: str,
        approved_context: Mapping[str, Any],
        *,
        resume_task_id: str | None,
    ) -> HostArtifact:
        raise NotImplementedError

    def _execute(
        self, command: HarnessCommand, expected: HarnessOperation
    ) -> HarnessResponse:
        if command.operation != expected:
            raise ValueError(f"expected {expected.value} command")
        fingerprint = safe_json_dumps(command.to_dict())
        with self._lock:
            self._touch_investigation(command.investigation_id)
            cached = self._command_cache.get(command.command_id)
            if cached is not None:
                self._command_cache.move_to_end(command.command_id)
                if cached[0] == fingerprint:
                    return cached[1]
                return self._error_response(
                    command,
                    HarnessErrorCode.INVALID_COMMAND,
                    "command_id was already used for different command content",
                    retryable=False,
                )
            if (
                command.protocol_version
                not in self.manifest.supported_protocol_versions
            ):
                response = self._error_response(
                    command,
                    HarnessErrorCode.CAPABILITY_UNAVAILABLE,
                    "protocol version is not supported by this harness adapter",
                    retryable=False,
                    details={"capability": command.protocol_version},
                )
            elif not self.manifest.supports(command.operation):
                response = self._error_response(
                    command,
                    HarnessErrorCode.CAPABILITY_UNAVAILABLE,
                    f"{command.operation.value} is not available from the installed harness",
                    retryable=False,
                    details={"capability": command.operation.value},
                )
            else:
                response = self._dispatch(command)
            self._remember_command(command, fingerprint, response)
            return response

    def _touch_investigation(self, investigation_id: str) -> None:
        self._investigations[investigation_id] = None
        self._investigations.move_to_end(investigation_id)
        while len(self._investigations) > self._investigation_window:
            expired_id, _ = self._investigations.popitem(last=False)
            self._bindings.pop(expired_id, None)
            for command_id, (_, _, cached_command) in tuple(
                self._command_cache.items()
            ):
                if cached_command.investigation_id == expired_id:
                    self._command_cache.pop(command_id, None)
            self._events.discard_investigation(expired_id)

    def _refresh_command_window(self, investigation_id: str) -> None:
        """Prune commands only after the matching replay window has advanced."""

        protected = self._events.correlation_ids(investigation_id)
        same_investigation = [
            command_id
            for command_id, (_, _, cached_command) in self._command_cache.items()
            if cached_command.investigation_id == investigation_id
        ]
        while len(same_investigation) > self._command_window:
            expired_id = next(
                (
                    command_id
                    for command_id in same_investigation
                    if command_id not in protected
                ),
                None,
            )
            if expired_id is None:
                break
            self._command_cache.pop(expired_id, None)
            same_investigation.remove(expired_id)

    def _remember_command(
        self,
        command: HarnessCommand,
        fingerprint: str,
        response: HarnessResponse,
    ) -> None:
        self._command_cache[command.command_id] = (fingerprint, response, command)
        self._command_cache.move_to_end(command.command_id)
        self._refresh_command_window(command.investigation_id)

    def _dispatch(self, command: HarnessCommand) -> HarnessResponse:
        binding = self._bindings.get(command.investigation_id)
        if binding is None and command.operation != HarnessOperation.START_TASK_RUN:
            binding = self._rehydrate_binding(command)
            self._bindings[command.investigation_id] = binding
            self._events.seed_cursor(
                command.investigation_id,
                command.latest_event_cursor or 0,
            )
        current_revision = binding.revision if binding else 0
        if command.expected_revision != current_revision:
            return self._error_response(
                command,
                HarnessErrorCode.REVISION_CONFLICT,
                "expected revision does not match the current harness binding revision",
                retryable=True,
                details={
                    "expected_revision": command.expected_revision,
                    "current_revision": current_revision,
                },
            )
        if command.operation == HarnessOperation.START_TASK_RUN:
            return self._start(command, binding)
        if binding is None:
            return self._error_response(
                command,
                HarnessErrorCode.BINDING_NOT_FOUND,
                "no harness binding exists for this investigation",
                retryable=False,
            )
        mismatch = self._binding_mismatch(
            command,
            binding,
            allow_session_rebind=command.operation
            == HarnessOperation.REPLACE_TASK_BINDING,
        )
        if mismatch:
            return mismatch
        if command.operation == HarnessOperation.CANCEL_TASK_WORK:
            return self._cancel(command, binding)
        if command.operation == HarnessOperation.REPLACE_TASK_BINDING:
            return self._replace(command, binding)
        if binding.status in {BindingStatus.CANCELLED, BindingStatus.FAILED}:
            return self._error_response(
                command,
                HarnessErrorCode.BINDING_CONFLICT,
                f"binding is {binding.status.value} and must be replaced",
                retryable=False,
            )
        return self._continue(command, binding)

    def _start(
        self, command: HarnessCommand, binding: _Binding | None
    ) -> HarnessResponse:
        if binding is not None:
            return self._error_response(
                command,
                HarnessErrorCode.BINDING_CONFLICT,
                "an investigation binding already exists; resume or replace it",
                retryable=False,
            )
        payload = command.payload
        assert isinstance(payload, StartTaskRunPayload)
        produced = self._try_produce(
            HarnessArtifactKind.PLAN,
            command,
            payload.question,
            payload.approved_context,
            resume_task_id=None,
        )
        if isinstance(produced, HarnessResponse):
            return produced
        task_id = produced.host_task_id or self._generated_id(
            "task", command.command_id
        )
        run_id = produced.host_run_id or self._generated_id("run", command.command_id)
        binding = _Binding(
            command.workspace_session_id,
            command.user_id,
            command.investigation_id,
            task_id,
            run_id,
            1,
            BindingStatus.WAITING,
        )
        self._bindings[command.investigation_id] = binding
        return self._artifact_response(command, binding, produced)

    def _continue(self, command: HarnessCommand, binding: _Binding) -> HarnessResponse:
        if command.operation == HarnessOperation.RESUME_TASK_RUN:
            payload = command.payload
            assert isinstance(payload, ResumeTaskRunPayload)
            artifact_kind = payload.artifact_kind
            instruction = payload.instruction
            approved_context = payload.approved_context
        else:
            payload = command.payload
            assert isinstance(payload, SendTaskMessagePayload)
            artifact_kind = payload.artifact_kind
            instruction = payload.message
            approved_context = payload.approved_context
        produced = self._try_produce(
            artifact_kind,
            command,
            instruction,
            approved_context,
            resume_task_id=binding.task_id,
        )
        if isinstance(produced, HarnessResponse):
            return produced
        binding.revision += 1
        binding.run_id = produced.host_run_id or self._generated_id(
            "run", command.command_id
        )
        binding.status = (
            BindingStatus.COMPLETED
            if artifact_kind == HarnessArtifactKind.BRIEF_DRAFT
            else BindingStatus.WAITING
        )
        return self._artifact_response(command, binding, produced)

    def _cancel(self, command: HarnessCommand, binding: _Binding) -> HarnessResponse:
        if binding.status == BindingStatus.COMPLETED:
            outcome = CancellationOutcome.ALREADY_COMPLETED
        elif binding.status == BindingStatus.CANCELLED:
            outcome = CancellationOutcome.NOT_CANCELLABLE
        else:
            outcome = CancellationOutcome.CANCELLED
            binding.revision += 1
            binding.status = BindingStatus.CANCELLED
            self._emit(
                command,
                binding,
                HarnessEventKind.CANCELLED,
                HarnessEventStatus.CANCELLED,
                {"external_jobs_confirmed_cancelled": False},
            )
        result = CancellationResult(
            outcome,
            binding.task_id,
            binding.run_id,
            False,
            self._events.latest_cursor(command.investigation_id),
        )
        return HarnessResponse(
            command.command_id,
            command.operation,
            binding.revision,
            binding.revision,
            result=result,
        )

    def _replace(self, command: HarnessCommand, binding: _Binding) -> HarnessResponse:
        payload = command.payload
        assert isinstance(payload, ReplaceTaskBindingPayload)
        previous_task_id = binding.task_id
        produced = self._try_produce(
            payload.artifact_kind,
            command,
            payload.question,
            payload.approved_context,
            resume_task_id=None,
        )
        if isinstance(produced, HarnessResponse):
            return produced
        binding.task_id = produced.host_task_id or self._generated_id(
            "task", command.command_id
        )
        binding.run_id = produced.host_run_id or self._generated_id(
            "run", command.command_id
        )
        binding.workspace_session_id = command.workspace_session_id
        binding.revision += 1
        binding.status = BindingStatus.WAITING
        return self._artifact_response(
            command,
            binding,
            produced,
            replaced_task_id=previous_task_id,
        )

    def _try_produce(
        self,
        artifact_kind: HarnessArtifactKind,
        command: HarnessCommand,
        instruction: str,
        approved_context: Mapping[str, Any],
        *,
        resume_task_id: str | None,
    ) -> HostArtifact | HarnessResponse:
        try:
            produced = self._produce_artifact(
                artifact_kind,
                command,
                instruction,
                approved_context,
                resume_task_id=resume_task_id,
            )
            if produced.artifact_kind != artifact_kind:
                raise ValueError(
                    "host returned a different artifact kind than requested"
                )
            return produced
        except HostInvocationUnavailable as exc:
            return self._error_response(
                command,
                HarnessErrorCode.CAPABILITY_UNAVAILABLE,
                str(exc),
                retryable=True,
                details={"capability": artifact_kind.value},
            )
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
            return self._error_response(
                command,
                HarnessErrorCode.HOST_EXECUTION_FAILED,
                "the installed harness did not return a valid structured artifact",
                retryable=True,
                details={"artifact_kind": artifact_kind.value},
            )

    def _artifact_response(
        self,
        command: HarnessCommand,
        binding: _Binding,
        produced: HostArtifact,
        *,
        replaced_task_id: str | None = None,
    ) -> HarnessResponse:
        artifact = safe_json_value(produced.artifact)
        encoded = safe_json_dumps(artifact)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        reference = ArtifactReference(
            f"proposed-{produced.artifact_kind.value}-{digest[:24]}",
            produced.artifact_kind,
            digest,
        )
        streamed_events = self._events.replay(
            command.investigation_id,
            after_cursor=command.latest_event_cursor or 0,
        )
        streamed_fingerprints = {
            (
                event.kind,
                event.status,
                safe_json_dumps(event.payload),
            )
            for event in streamed_events.events
        }
        for trace in produced.trace_events:
            fingerprint = (
                trace.kind,
                trace.status,
                safe_json_dumps(trace.payload),
            )
            if fingerprint not in streamed_fingerprints:
                self._emit(
                    command,
                    binding,
                    trace.kind,
                    trace.status,
                    trace.payload,
                )
        if produced.artifact_kind == HarnessArtifactKind.PLAN:
            event_kind = HarnessEventKind.PLAN_PROPOSED
            event_status = HarnessEventStatus.PROPOSED
            if (
                self.manifest.agent_delegation_event_reporting
                and not produced.trace_events_complete
            ):
                for request in artifact.get("capability_requests") or []:
                    if not isinstance(request, dict):
                        continue
                    agent_id = f"agent-{hashlib.sha256(str(request.get('id') or '').encode()).hexdigest()[:16]}"
                    step_id = str(request.get("step_id") or "")
                    role = str(request.get("assigned_agent_role") or "")
                    if not step_id or not role:
                        continue
                    self._emit(
                        command,
                        binding,
                        HarnessEventKind.AGENT_STARTED,
                        HarnessEventStatus.RUNNING,
                        {
                            "agent_id": agent_id,
                            "role": role,
                            "assigned_step_id": step_id,
                        },
                    )
                    self._emit(
                        command,
                        binding,
                        HarnessEventKind.AGENT_PROGRESS,
                        HarnessEventStatus.RUNNING,
                        {
                            "agent_id": agent_id,
                            "assigned_step_id": step_id,
                            "progress": "Selected a typed GenomiLab capability request for domain validation and execution.",
                        },
                    )
        elif produced.artifact_kind == HarnessArtifactKind.EXECUTION_REPORT:
            event_kind = HarnessEventKind.CAPABILITY_EXECUTION_COMPLETED
            event_status = HarnessEventStatus.COMPLETED
        else:
            event_kind = HarnessEventKind.BRIEF_COMPLETED
            event_status = HarnessEventStatus.COMPLETED
        event = self._emit(
            command,
            binding,
            event_kind,
            event_status,
            {
                "artifact_kind": produced.artifact_kind.value,
                "artifact_reference": reference.to_dict(),
            },
            (reference,),
        )
        result = TaskRunResult(
            binding.task_id,
            binding.run_id,
            binding.status,
            artifact,
            reference,
            event.cursor,
            replaced_task_id,
        )
        return HarnessResponse(
            command.command_id,
            command.operation,
            binding.revision,
            binding.revision,
            result=result,
        )

    def _emit(
        self,
        command: HarnessCommand,
        binding: _Binding,
        kind: HarnessEventKind,
        status: HarnessEventStatus,
        payload: Mapping[str, Any],
        references: tuple[ArtifactReference, ...] = (),
    ) -> HarnessEvent:
        cursor = self._events.latest_cursor(command.investigation_id) + 1
        event = HarnessEvent(
            event_id=f"event-{uuid.uuid4().hex}",
            kind=kind,
            workspace_session_id=command.workspace_session_id,
            host_id=self.manifest.adapter_id,
            task_id=binding.task_id,
            run_id=binding.run_id,
            investigation_id=command.investigation_id,
            user_id=command.user_id,
            cursor=cursor,
            correlation_id=command.command_id,
            status=status,
            timestamp=utc_now(),
            payload=payload,
            proposed_artifacts=references,
        )
        accepted = self._events.append(event)
        if not accepted.accepted:
            raise RuntimeError("adapter generated a non-monotonic event")
        self._refresh_command_window(command.investigation_id)
        return event

    def _binding_mismatch(
        self,
        command: HarnessCommand,
        binding: _Binding,
        *,
        allow_session_rebind: bool = False,
    ) -> HarnessResponse | None:
        expected_identity = (
            binding.user_id,
            binding.task_id,
        )
        received_identity = (
            command.user_id,
            command.task_id,
        )
        run_matches = command.run_id is None or command.run_id == binding.run_id
        session_matches = (
            allow_session_rebind
            or command.workspace_session_id == binding.workspace_session_id
        )
        if expected_identity == received_identity and run_matches and session_matches:
            return None
        return self._error_response(
            command,
            HarnessErrorCode.BINDING_CONFLICT,
            "command identity does not match the active investigation binding",
            retryable=False,
        )

    def _error_response(
        self,
        command: HarnessCommand,
        code: HarnessErrorCode,
        message: str,
        *,
        retryable: bool,
        details: Mapping[str, Any] | None = None,
    ) -> HarnessResponse:
        binding = self._bindings.get(command.investigation_id)
        current_revision = binding.revision if binding else 0
        error = HarnessProtocolError(
            code,
            message,
            retryable,
            current_revision,
            details or {},
        )
        return HarnessResponse(
            command.command_id,
            command.operation,
            None,
            current_revision,
            error=error,
        )

    @staticmethod
    def _generated_id(prefix: str, command_id: str) -> str:
        digest = hashlib.sha256(command_id.encode("utf-8")).hexdigest()[:24]
        return f"{prefix}-{digest}"

    @staticmethod
    def _rehydrate_binding(command: HarnessCommand) -> _Binding:
        """Recover ephemeral transport state from a domain-authoritative command."""

        if not command.task_id or not command.run_id:
            raise ValueError("bound command is missing task_id or run_id")
        return _Binding(
            command.workspace_session_id,
            command.user_id,
            command.investigation_id,
            command.task_id,
            command.run_id,
            command.current_binding_revision or 0,
            command.binding_status or BindingStatus.WAITING,
        )
