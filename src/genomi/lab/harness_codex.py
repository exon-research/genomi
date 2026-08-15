"""Installed Codex app-server adapter for the host-neutral harness contract."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from .harness_artifacts import (
    artifact_schema as _artifact_schema,
    decode_wire_artifact as _decode_wire_artifact,
    validate_artifact as _validate_harness_artifact,
)
from .harness_adapter import (
    HarnessAdapter,
    HostArtifact,
    HostInvocationUnavailable,
    HostTraceEvent,
)
from .harness_background import (
    HarnessCompletionCallback,
    HarnessIdentityCallback,
    HarnessJobState,
    HarnessJobSubmission,
    HarnessSubmissionCallback,
)
from .harness_codex_background import (
    CodexBackgroundController,
    _CodexBackgroundJob,
    codex_background_job_id,
)
from .harness_codex_configuration import CodexRequestBuilder
from .harness_events import CancellationResult, HarnessEvent, HarnessResponse
from .harness_transport import (
    PROTOCOL_VERSION,
    required_identifier,
    safe_json_dumps,
    safe_json_value,
)
from .harness_types import (
    CancellationOutcome,
    HarnessErrorCode,
    HarnessArtifactKind,
    HarnessCapabilityManifest,
    HarnessCommand,
    HarnessEventKind,
    HarnessEventStatus,
    HarnessOperation,
)

from .harness_dynamic_tools import dynamic_tools as _dynamic_tools
from .harness_codex_protocol import (
    TransportFactory,
    _AppServerSession,
    _JsonLineTransport,
    _StdioJsonLineTransport,
    _TurnCollector,
)
from .harness_codex_host import (
    processing_destination as validate_processing_destination,
    sanitized_host_environment,
)


class InstalledCodexAppServerAdapter(HarnessAdapter):
    """Drive the installed Codex agent harness through its app-server protocol."""

    def __init__(
        self,
        executable_path: str | None,
        *,
        host_version: str | None = None,
        processing_destination: str | None = None,
        unavailable_reason: str | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        transport_factory: TransportFactory | None = None,
        timeout_seconds: int = 300,
        replay_window: int = 1_000,
        investigation_window: int = 128,
        command_window: int | None = None,
        terminal_job_retention: int = 128,
        cancellation_retention: int = 256,
    ) -> None:
        destination = validate_processing_destination(processing_destination)
        if executable_path and host_version and destination is None:
            unavailable_reason = (
                unavailable_reason
                or "Codex processing destination was not explicitly declared by the host"
            )
        available = bool(executable_path and host_version and destination)
        operations = (
            (
                HarnessOperation.START_TASK_RUN,
                HarnessOperation.RESUME_TASK_RUN,
                HarnessOperation.SEND_TASK_MESSAGE,
                HarnessOperation.CANCEL_TASK_WORK,
                HarnessOperation.REPLACE_TASK_BINDING,
            )
            if available
            else ()
        )
        super().__init__(
            HarnessCapabilityManifest(
                adapter_id="codex-app-server",
                host_kind="codex_app_server",
                host_version=host_version,
                available=available,
                supported_protocol_versions=(PROTOCOL_VERSION,),
                supported_operations=operations,
                event_streaming=available,
                event_replay=available,
                artifact_kinds=tuple(HarnessArtifactKind) if available else (),
                agent_delegation_planning=available,
                agent_delegation_event_reporting=available,
                background_job_attach=available,
                background_job_cancel=available,
                approved_context_delivery=available,
                workspace_session_persistence=(
                    "codex_thread_history" if available else "unavailable"
                ),
                execution_location=destination if available else "unavailable",
                unavailable_reason=unavailable_reason,
            ),
            replay_window=replay_window,
            investigation_window=investigation_window,
            command_window=command_window,
        )
        self._executable_path = executable_path
        self._runner = runner or subprocess.run
        self._transport_factory = transport_factory or _StdioJsonLineTransport
        self._timeout_seconds = timeout_seconds
        self._transport_context = threading.local()
        self._codex_requests = CodexRequestBuilder(executable_path)
        self._background = CodexBackgroundController(
            timeout_seconds,
            terminal_job_retention=terminal_job_retention,
            cancellation_retention=cancellation_retention,
        )

    @property
    def background_job_count(self) -> int:
        """Retained process-local Codex job handles."""

        return self._background.job_count

    @property
    def background_cancellation_count(self) -> int:
        """Retained process-local cancellation results."""

        return self._background.cancellation_count

    def close(self) -> None:
        super().close()
        self._background.close()

    @classmethod
    def discover(
        cls,
        executable_name: str = "codex",
        *,
        which: Callable[[str], str | None] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        transport_factory: TransportFactory | None = None,
        timeout_seconds: int = 300,
        processing_destination: str | None = None,
    ) -> InstalledCodexAppServerAdapter:
        which_function = which or shutil.which
        run_function = runner or subprocess.run
        executable_path = which_function(executable_name)
        if not executable_path:
            return cls(
                None,
                unavailable_reason="Codex is not installed or is not on PATH",
                runner=run_function,
                transport_factory=transport_factory,
                timeout_seconds=timeout_seconds,
                processing_destination=processing_destination,
            )
        try:
            version_result = run_function(
                [executable_path, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                env=sanitized_host_environment(),
            )
            app_server_help = run_function(
                [executable_path, "app-server", "--help"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                env=sanitized_host_environment(),
            )
        except (OSError, subprocess.SubprocessError):
            version_result = subprocess.CompletedProcess([], 1, "", "")
            app_server_help = subprocess.CompletedProcess([], 1, "", "")
        if version_result.returncode != 0:
            reason = "Codex version discovery failed"
            version = None
        elif (
            app_server_help.returncode != 0
            or "--stdio" not in app_server_help.stdout
            or "generate-json-schema" not in app_server_help.stdout
        ):
            reason = "Codex lacks the required app-server stdio protocol"
            version = None
        else:
            reason = None
            version = (
                version_result.stdout.strip().splitlines()[0]
                if version_result.stdout.strip()
                else "unknown"
            )
        adapter = cls(
            executable_path if version else None,
            host_version=version[:120] if version else None,
            unavailable_reason=reason,
            runner=run_function,
            transport_factory=transport_factory,
            timeout_seconds=timeout_seconds,
            processing_destination=(
                processing_destination
                or os.environ.get("GENOMILAB_CODEX_PROCESSING_DESTINATION")
            ),
        )
        if adapter.manifest.available:
            try:
                adapter._probe_protocol()
            except (OSError, subprocess.SubprocessError, ValueError):
                return cls(
                    None,
                    unavailable_reason="Codex app-server protocol handshake failed",
                    runner=run_function,
                    transport_factory=transport_factory,
                    timeout_seconds=timeout_seconds,
                    processing_destination=processing_destination,
                )
        return adapter

    def _probe_protocol(self) -> None:
        if not self._executable_path:
            raise HostInvocationUnavailable(
                "Codex app-server capability is unavailable"
            )
        with tempfile.TemporaryDirectory(prefix="genomilab-codex-probe-") as codex_home:
            environment = sanitized_host_environment(codex_home=codex_home)
            transport = self._transport_factory(
                self._app_server_command(), environment, min(self._timeout_seconds, 15)
            )
            try:
                _AppServerSession(
                    transport, min(self._timeout_seconds, 15)
                ).initialize()
            finally:
                transport.close()

    def dispatch_background(
        self,
        command: HarnessCommand,
        *,
        submission_callback: HarnessSubmissionCallback,
        identity_callback: HarnessIdentityCallback,
        completion_callback: HarnessCompletionCallback,
    ) -> HarnessJobSubmission:
        if command.operation == HarnessOperation.CANCEL_TASK_WORK:
            raise ValueError("cancellation is a confirmed foreground control request")
        if not self.manifest.background_job_attach:
            raise HostInvocationUnavailable(
                "Codex app-server background turns are unavailable"
            )
        if not self.manifest.supports(command.operation):
            raise HostInvocationUnavailable(
                f"{command.operation.value} is unavailable from Codex app-server"
            )
        return self._background.dispatch(
            command,
            submission_callback=submission_callback,
            identity_callback=identity_callback,
            completion_callback=completion_callback,
            execute=self._execute_background_command,
            failure_response=self._background_failure_response,
        )

    def background_job(self, job_id: str) -> HarnessJobSubmission | None:
        return self._background.background_job(job_id)

    def retry_background_completion(
        self, job_id: str
    ) -> HarnessJobSubmission | None:
        return self._background.retry_completion(job_id)

    def wait_for_background_job(
        self, job_id: str, *, timeout_seconds: float
    ) -> HarnessJobSubmission | None:
        return self._background.wait_for_background_job(
            job_id, timeout_seconds=timeout_seconds
        )

    def _execute_background_command(self, command: HarnessCommand) -> HarnessResponse:
        operation = {
            HarnessOperation.START_TASK_RUN: self.start_task_run,
            HarnessOperation.RESUME_TASK_RUN: self.resume_task_run,
            HarnessOperation.SEND_TASK_MESSAGE: self.send_task_message,
            HarnessOperation.REPLACE_TASK_BINDING: self.replace_task_binding,
        }[command.operation]
        return operation(command)

    def _background_failure_response(
        self, job: _CodexBackgroundJob
    ) -> HarnessResponse:
        return self._error_response(
            job.command,
            HarnessErrorCode.HOST_EXECUTION_FAILED,
            "the installed harness background turn failed",
            retryable=True,
            details={"job_id": job.job_id},
        )

    def cancel_task_work(self, command: HarnessCommand) -> HarnessResponse:
        if command.operation != HarnessOperation.CANCEL_TASK_WORK:
            raise ValueError("expected cancel_task_work command")
        fingerprint = safe_json_dumps(command.to_dict())
        cached = self._background.cached_cancellation(command.command_id)
        if cached is not None:
            if cached[0] == fingerprint:
                return cached[1]
            return self._error_response(
                command,
                HarnessErrorCode.INVALID_COMMAND,
                "command_id was already used for different command content",
                retryable=False,
            )
        has_related_jobs, job = self._background.cancellation_target(command)
        if has_related_jobs and job is None:
            response = self._error_response(
                command,
                HarnessErrorCode.BINDING_CONFLICT,
                "cancellation identity does not match the active harness work",
                retryable=False,
            )
        else:
            response = self._cancel_background_turn(command, job)
        self._background.remember_cancellation(
            command.command_id, fingerprint, response
        )
        return response

    def _cancel_background_turn(
        self, command: HarnessCommand, job: _CodexBackgroundJob | None
    ) -> HarnessResponse:
        if not self.manifest.background_job_cancel:
            return self._cancellation_response(
                command, None, CancellationOutcome.NOT_CANCELLABLE
            )
        if job is None:
            return self._cancellation_response(
                command, None, CancellationOutcome.NOT_CANCELLABLE
            )
        with job.changed:
            if command.expected_revision != job.command.expected_revision + 1:
                return self._error_response(
                    command,
                    HarnessErrorCode.REVISION_CONFLICT,
                    "expected revision does not match the running harness turn",
                    retryable=True,
                    details={
                        "expected_revision": command.expected_revision,
                        "current_revision": job.command.expected_revision + 1,
                    },
                )
            if job.state == HarnessJobState.COMPLETED:
                return self._cancellation_response(
                    command, job, CancellationOutcome.ALREADY_COMPLETED
                )
            if job.state == HarnessJobState.CANCELLED:
                return self._cancellation_response(
                    command, job, CancellationOutcome.NOT_CANCELLABLE
                )
            if job.state == HarnessJobState.FAILED:
                return self._cancellation_response(
                    command, job, CancellationOutcome.FAILED
                )
            if (
                job.session is None
                or job.thread_id is None
                or job.run_id is None
                or job.state != HarnessJobState.RUNNING
            ):
                return self._cancellation_response(
                    command, job, CancellationOutcome.NOT_CANCELLABLE
                )
            if job.interrupt_request_id is None:
                job.interrupt_request_id = job.session.send_request(
                    "turn/interrupt",
                    {"threadId": job.thread_id, "turnId": job.run_id},
                )
            job.changed.wait_for(
                lambda: job.turn_status in {"completed", "interrupted", "failed"}
                or job.interrupt_error,
                timeout=min(10.0, float(self._timeout_seconds)),
            )
            if job.turn_status == "interrupted":
                job.state = HarnessJobState.CANCELLED
                if not job.cancel_event_emitted:
                    self._append_background_event(
                        command,
                        job,
                        HarnessEventKind.CANCELLED,
                        HarnessEventStatus.CANCELLED,
                        {"external_jobs_confirmed_cancelled": False},
                    )
                    job.cancel_event_emitted = True
                return self._cancellation_response(
                    command, job, CancellationOutcome.CANCELLED
                )
            if job.turn_status == "completed":
                return self._cancellation_response(
                    command, job, CancellationOutcome.ALREADY_COMPLETED
                )
            return self._cancellation_response(command, job, CancellationOutcome.FAILED)

    def _cancellation_response(
        self,
        command: HarnessCommand,
        job: _CodexBackgroundJob | None,
        outcome: CancellationOutcome,
    ) -> HarnessResponse:
        task_id = job.task_id if job is not None and job.task_id else command.task_id
        if not task_id:
            task_id = f"unassigned-{codex_background_job_id(command.command_id)}"
        revision = command.expected_revision + (
            1 if outcome == CancellationOutcome.CANCELLED else 0
        )
        result = CancellationResult(
            outcome,
            task_id,
            job.run_id if job is not None else command.run_id,
            False,
            self._events.latest_cursor(command.investigation_id),
        )
        return HarnessResponse(
            command.command_id,
            command.operation,
            revision,
            revision,
            result=result,
        )

    def _produce_artifact(
        self,
        artifact_kind: HarnessArtifactKind,
        command: HarnessCommand,
        instruction: str,
        approved_context: Mapping[str, Any],
        *,
        resume_task_id: str | None,
    ) -> HostArtifact:
        if not self._executable_path or not self.manifest.available:
            raise HostInvocationUnavailable(
                self.manifest.unavailable_reason
                or "Codex app-server capability is unavailable"
            )
        schema = _artifact_schema(artifact_kind, approved_context)
        capability_by_tool, dynamic_tools, _tool_contract_digest = _dynamic_tools(
            approved_context if artifact_kind == HarnessArtifactKind.EXECUTION_REPORT else {}
        )
        current_catalog = approved_context.get("capability_catalog")
        current_catalog = (
            current_catalog if isinstance(current_catalog, Mapping) else {}
        )
        with tempfile.TemporaryDirectory(
            prefix="genomilab-harness-"
        ) as temporary_directory:
            directory = Path(temporary_directory)
            transport = self._transport_factory(
                self._app_server_command(),
                sanitized_host_environment(),
                self._timeout_seconds,
            )
            self._transport_context.transport = transport
            session = _AppServerSession(transport, self._timeout_seconds)
            try:
                session.initialize()
                if resume_task_id is None:
                    started = session.request(
                        "thread/start",
                        self._codex_requests.thread_start(directory, dynamic_tools),
                    )
                    thread = started.get("thread")
                    if not isinstance(thread, Mapping):
                        raise ValueError("thread/start did not return a thread")
                    thread_id = required_identifier(thread.get("id"), "thread_id")
                    host_task_id = thread_id
                else:
                    thread_id = required_identifier(resume_task_id, "thread_id")
                    session.request(
                        "thread/resume",
                        self._codex_requests.thread_resume(thread_id, directory),
                    )
                    host_task_id = resume_task_id
                collector = _TurnCollector(
                    self,
                    command,
                    capability_by_tool,
                    current_catalog,
                    thread_id,
                )
                turn_result = session.request(
                    "turn/start",
                    self._codex_requests.turn_start(
                        thread_id,
                        artifact_kind,
                        command,
                        instruction,
                        approved_context,
                        schema,
                        capability_by_tool,
                    ),
                    collector.observe,
                )
                turn = turn_result.get("turn")
                if not isinstance(turn, Mapping):
                    raise ValueError("turn/start did not return a turn")
                collector.turn_id = required_identifier(turn.get("id"), "turn_id")
                self._activate_background_turn(
                    command,
                    host_task_id,
                    thread_id,
                    collector.turn_id,
                    session,
                    transport,
                )
                deadline = time.monotonic() + self._timeout_seconds
                while not collector.completed:
                    collector.observe(transport.receive(deadline - time.monotonic()))
                if collector.failed or not collector.final_message:
                    raise subprocess.SubprocessError(
                        "Codex app-server turn did not complete successfully"
                    )
                artifact = safe_json_value(json.loads(collector.final_message))
                if not isinstance(artifact, dict):
                    raise ValueError("Codex structured artifact must be an object")
                artifact = _decode_wire_artifact(
                    artifact_kind, artifact, approved_context=approved_context
                )
                self._validate_artifact(
                    artifact_kind, artifact, approved_context=approved_context
                )
                if artifact_kind == HarnessArtifactKind.EXECUTION_REPORT:
                    accepted_plan = approved_context.get("accepted_plan")
                    plan = (
                        accepted_plan.get("plan")
                        if isinstance(accepted_plan, Mapping)
                        else None
                    )
                    expected_requests = (
                        plan.get("capability_requests")
                        if isinstance(plan, Mapping)
                        else None
                    )
                    if not _is_sequence(expected_requests):
                        raise ValueError(
                            "execution report requires the exact accepted plan"
                        )
                    assert collector.dynamic_call_results is not None
                    expected_pairs = {
                        (str(item.get("id") or ""), str(item.get("capability") or ""))
                        for item in expected_requests
                        if isinstance(item, Mapping)
                    }
                    observed_pairs = {
                        (item["request_id"], item["capability"])
                        for item in collector.dynamic_call_results
                    }
                    reported_pairs = {
                        (str(item["request_id"]), str(item["capability"]))
                        for item in artifact["request_results"]
                    }
                    if (
                        len(collector.dynamic_call_results) != len(expected_pairs)
                        or observed_pairs != expected_pairs
                        or reported_pairs != expected_pairs
                    ):
                        raise ValueError(
                            "execution report must exactly match all accepted-plan tool calls"
                        )
                    observed_by_pair = {
                        (item["request_id"], item["capability"]): item["status"]
                        for item in collector.dynamic_call_results
                    }
                    if any(
                        item["status"]
                        != observed_by_pair[(item["request_id"], item["capability"])]
                        for item in artifact["request_results"]
                    ):
                        raise ValueError(
                            "execution report statuses must match dynamic tool results"
                        )
                assert collector.turn_id is not None and collector.traces is not None
                return HostArtifact(
                    artifact_kind,
                    artifact,
                    host_task_id,
                    collector.turn_id,
                    tuple(collector.traces),
                    True,
                )
            finally:
                self._transport_context.transport = None
                transport.close()

    def _current_background_job(
        self, command: HarnessCommand
    ) -> _CodexBackgroundJob | None:
        return self._background.current_job(command)

    def _activate_background_turn(
        self,
        command: HarnessCommand,
        host_task_id: str,
        thread_id: str,
        turn_id: str,
        session: _AppServerSession,
        transport: _JsonLineTransport,
    ) -> None:
        job = self._background.activate_turn(
            command,
            host_task_id,
            thread_id,
            turn_id,
            session,
            transport,
        )
        if job is None:
            return
        self._append_background_event(
            command,
            job,
            HarnessEventKind.JOB_IN_PROGRESS,
            HarnessEventStatus.RUNNING,
            {"host_state": "turn_started"},
        )

    def _publish_background_trace(
        self, command: HarnessCommand, trace: HostTraceEvent
    ) -> bool:
        job = self._current_background_job(command)
        if job is None or job.task_id is None or job.run_id is None:
            return False
        self._append_background_event(
            command, job, trace.kind, trace.status, trace.payload
        )
        return True

    def _append_background_event(
        self,
        command: HarnessCommand,
        job: _CodexBackgroundJob,
        kind: HarnessEventKind,
        status: HarnessEventStatus,
        payload: Mapping[str, Any],
    ) -> HarnessEvent:
        if job.task_id is None or job.run_id is None:
            raise ValueError(
                "background event requires confirmed host task and turn IDs"
            )
        event = HarnessEvent(
            event_id=f"event-{os.urandom(16).hex()}",
            kind=kind,
            workspace_session_id=command.workspace_session_id,
            host_id=self.manifest.adapter_id,
            task_id=job.task_id,
            run_id=job.run_id,
            investigation_id=command.investigation_id,
            user_id=command.user_id,
            cursor=self._events.latest_cursor(command.investigation_id) + 1,
            correlation_id=command.command_id,
            job_id=job.job_id,
            status=status,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            payload=payload,
        )
        accepted = self._events.append(event)
        if not accepted.accepted:
            raise RuntimeError("adapter generated a non-monotonic background event")
        return event

    def _observe_background_protocol_message(
        self, command: HarnessCommand, message: Mapping[str, Any]
    ) -> bool:
        observed = self._background.observe_interrupt_response(command, message)
        if observed:
            return True
        parent_command = getattr(self._transport_context, "command", None)
        return bool(
            isinstance(parent_command, HarnessCommand)
            and self._background.observe_interrupt_response(parent_command, message)
        )

    def _note_background_turn_completed(
        self,
        command: HarnessCommand,
        thread_id: str,
        turn_id: str,
        turn_status: str,
    ) -> None:
        self._background.note_turn_completed(
            command, thread_id, turn_id, turn_status
        )

    def _send_app_server_error(self, request_id: object, message: str) -> None:
        transport = getattr(self._transport_context, "transport", None)
        if transport is None:
            raise HostInvocationUnavailable("Codex app-server transport is not active")
        transport.send(
            {
                "id": request_id,
                "error": {"code": -32601, "message": message},
            }
        )

    def _send_dynamic_tool_result(
        self, request_id: object, result: Mapping[str, Any], *, success: bool
    ) -> None:
        transport = getattr(self._transport_context, "transport", None)
        if transport is None:
            raise HostInvocationUnavailable("Codex app-server transport is not active")
        transport.send(
            {
                "id": request_id,
                "result": {
                    "contentItems": [
                        {"type": "inputText", "text": safe_json_dumps(result)}
                    ],
                    "success": bool(success),
                },
            }
        )

    def _app_server_command(self) -> list[str]:
        if not self._executable_path:
            raise HostInvocationUnavailable(
                "Codex app-server capability is unavailable"
            )
        return self._codex_requests.app_server_command()

    _validate_artifact = staticmethod(_validate_harness_artifact)


def _is_sequence(value: object) -> bool:
    return isinstance(value, (list, tuple))
