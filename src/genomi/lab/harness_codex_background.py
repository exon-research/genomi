"""Bounded process-local lifecycle for Codex app-server background turns.

GenomiLab's durable store owns job and command history.  This controller keeps
only live ownership handles plus a small terminal window needed for immediate
attach, wait, cancellation, and retry behavior inside one adapter process.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Mapping

from .harness_adapter import HostInvocationUnavailable
from .harness_background import (
    HarnessCompletionCallback,
    HarnessIdentityCallback,
    HarnessJobIdentity,
    HarnessJobState,
    HarnessJobSubmission,
    HarnessSubmissionCallback,
)
from .harness_codex_protocol import _AppServerSession, _JsonLineTransport
from .harness_events import HarnessResponse
from .harness_transport import safe_json_dumps
from .harness_types import HarnessCommand


_DEFAULT_ACTIVE_JOB_LIMIT = 64
_DEFAULT_TERMINAL_JOB_RETENTION = 128
_DEFAULT_CANCELLATION_RETENTION = 256


@dataclass(slots=True)
class _CodexBackgroundJob:
    job_id: str
    fingerprint: str
    command: HarnessCommand
    identity_callback: HarnessIdentityCallback
    completion_callback: HarnessCompletionCallback
    state: HarnessJobState = HarnessJobState.QUEUED
    task_id: str | None = None
    run_id: str | None = None
    thread_id: str | None = None
    session: _AppServerSession | None = None
    transport: _JsonLineTransport | None = None
    turn_status: str | None = None
    interrupt_request_id: int | None = None
    interrupt_acknowledged: bool = False
    interrupt_error: bool = False
    cancel_event_emitted: bool = False
    response: HarnessResponse | None = None
    completion_acknowledged: bool = False
    completion_lock: threading.Lock = field(default_factory=threading.Lock)
    terminal: threading.Event = field(default_factory=threading.Event)
    changed: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock())
    )

    def submission(self) -> HarnessJobSubmission:
        with self.changed:
            return HarnessJobSubmission(
                self.job_id,
                self.state,
                self.task_id,
                self.run_id,
            )


BackgroundExecution = Callable[[HarnessCommand], HarnessResponse]
BackgroundFailureResponse = Callable[[_CodexBackgroundJob], HarnessResponse]


class CodexBackgroundController:
    """Own live Codex turns and a bounded window of terminal process state."""

    def __init__(
        self,
        timeout_seconds: int,
        *,
        active_job_limit: int = _DEFAULT_ACTIVE_JOB_LIMIT,
        terminal_job_retention: int = _DEFAULT_TERMINAL_JOB_RETENTION,
        cancellation_retention: int = _DEFAULT_CANCELLATION_RETENTION,
    ) -> None:
        for name, value in (
            ("active_job_limit", active_job_limit),
            ("terminal_job_retention", terminal_job_retention),
            ("cancellation_retention", cancellation_retention),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self._timeout_seconds = timeout_seconds
        self._active_job_limit = active_job_limit
        self._terminal_job_retention = terminal_job_retention
        self._cancellation_retention = cancellation_retention
        self._jobs: dict[str, _CodexBackgroundJob] = {}
        self._command_ids: dict[str, str] = {}
        self._terminal_job_ids: OrderedDict[str, None] = OrderedDict()
        self._cancel_cache: OrderedDict[
            str, tuple[str, HarnessResponse]
        ] = OrderedDict()
        self._lock = threading.RLock()
        self._current = threading.local()
        self._closed = False

    @property
    def job_count(self) -> int:
        """Number of retained process-local job handles, for diagnostics/tests."""

        with self._lock:
            return len(self._jobs)

    @property
    def cancellation_count(self) -> int:
        """Number of retained process-local cancellation results."""

        with self._lock:
            return len(self._cancel_cache)

    def close(self) -> None:
        """Close live transports and drop every process-local lookup handle."""

        with self._lock:
            self._closed = True
            jobs = tuple(self._jobs.values())
            transports = tuple(
                {
                    id(job.transport): job.transport
                    for job in jobs
                    if job.transport is not None
                }.values()
            )
            self._jobs.clear()
            self._command_ids.clear()
            self._terminal_job_ids.clear()
            self._cancel_cache.clear()
        for job in jobs:
            with job.changed:
                job.session = None
                job.transport = None
                job.changed.notify_all()
        for transport in transports:
            transport.close()

    def dispatch(
        self,
        command: HarnessCommand,
        *,
        submission_callback: HarnessSubmissionCallback,
        identity_callback: HarnessIdentityCallback,
        completion_callback: HarnessCompletionCallback,
        execute: BackgroundExecution,
        failure_response: BackgroundFailureResponse,
    ) -> HarnessJobSubmission:
        fingerprint = safe_json_dumps(command.to_dict())
        job_id = codex_background_job_id(command.command_id)
        with self._lock:
            if self._closed:
                raise HostInvocationUnavailable("Codex background controller is closed")
            existing_job_id = self._command_ids.get(command.command_id)
            if existing_job_id is not None:
                existing = self._jobs[existing_job_id]
                if existing.fingerprint != fingerprint:
                    raise ValueError(
                        "command_id was already used for different harness work"
                    )
                return existing.submission()
            active_jobs = sum(
                not job.completion_acknowledged for job in self._jobs.values()
            )
            if active_jobs >= self._active_job_limit:
                raise HostInvocationUnavailable(
                    "Codex background job capacity is currently full"
                )
            job = _CodexBackgroundJob(
                job_id,
                fingerprint,
                command,
                identity_callback,
                completion_callback,
            )
            self._jobs[job_id] = job
            self._command_ids[command.command_id] = job_id
        try:
            submission_callback(job.submission())
            worker = threading.Thread(
                target=self._run_job,
                args=(job, execute, failure_response),
                name=f"genomilab-{job_id}",
                daemon=True,
            )
            worker.start()
        except Exception:
            # Durable submission or thread launch can fail before host work exists.
            # Remove the process-local claim so a safe retry is not trapped behind
            # a queued tombstone.
            self._remove_if_owned(job)
            raise
        with job.changed:
            job.changed.wait_for(
                lambda: job.state != HarnessJobState.QUEUED,
                timeout=min(0.25, float(self._timeout_seconds)),
            )
        return job.submission()

    def background_job(self, job_id: str) -> HarnessJobSubmission | None:
        with self._lock:
            job = self._jobs.get(job_id)
        return job.submission() if job is not None else None

    def retry_completion(self, job_id: str) -> HarnessJobSubmission | None:
        """Retry only durable completion for an already executed terminal turn."""

        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        with job.changed:
            terminal = job.state in {
                HarnessJobState.COMPLETED,
                HarnessJobState.CANCELLED,
                HarnessJobState.FAILED,
            }
        if terminal:
            self._acknowledge_completion(job)
        return job.submission()

    def wait_for_background_job(
        self, job_id: str, *, timeout_seconds: float
    ) -> HarnessJobSubmission | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        job.terminal.wait(max(0.0, float(timeout_seconds)))
        return job.submission()

    def current_job(self, command: HarnessCommand) -> _CodexBackgroundJob | None:
        job_id = getattr(self._current, "job_id", None)
        if not isinstance(job_id, str):
            return None
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.command.command_id != command.command_id:
            return None
        return job

    def job_for_command(self, command: HarnessCommand) -> _CodexBackgroundJob | None:
        """Resolve an owned job from a caller thread by its exact command."""

        with self._lock:
            job_id = self._command_ids.get(command.command_id)
            job = self._jobs.get(job_id) if job_id is not None else None
        if job is None or job.command != command:
            return None
        return job

    def activate_turn(
        self,
        command: HarnessCommand,
        host_task_id: str,
        thread_id: str,
        turn_id: str,
        session: _AppServerSession,
        transport: _JsonLineTransport,
    ) -> _CodexBackgroundJob | None:
        job = self.current_job(command)
        if job is None:
            return None
        with self._lock:
            if self._closed or self._jobs.get(job.job_id) is not job:
                return None
            identity = HarnessJobIdentity(job.job_id, host_task_id, turn_id)
            with job.changed:
                job.task_id = host_task_id
                job.run_id = turn_id
                job.thread_id = thread_id
                job.session = session
                job.transport = transport
                job.state = HarnessJobState.RUNNING
                job.changed.notify_all()
        job.identity_callback(identity)
        return job

    def cancellation_target(
        self, command: HarnessCommand
    ) -> tuple[bool, _CodexBackgroundJob | None]:
        with self._lock:
            related_jobs = [
                job
                for job in self._jobs.values()
                if job.command.investigation_id == command.investigation_id
                or (
                    job.task_id == command.task_id
                    and job.run_id == command.run_id
                )
            ]
            candidates = [
                job
                for job in related_jobs
                if job.command.investigation_id == command.investigation_id
                and job.command.workspace_session_id == command.workspace_session_id
                and job.command.user_id == command.user_id
                and job.command.protocol_version == command.protocol_version
                and job.task_id == command.task_id
                and job.run_id == command.run_id
            ]
        return bool(related_jobs), candidates[-1] if candidates else None

    def cached_cancellation(
        self, command_id: str
    ) -> tuple[str, HarnessResponse] | None:
        with self._lock:
            cached = self._cancel_cache.get(command_id)
            if cached is not None:
                self._cancel_cache.move_to_end(command_id)
            return cached

    def remember_cancellation(
        self, command_id: str, fingerprint: str, response: HarnessResponse
    ) -> None:
        with self._lock:
            if self._closed:
                return
            self._cancel_cache[command_id] = (fingerprint, response)
            self._cancel_cache.move_to_end(command_id)
            while len(self._cancel_cache) > self._cancellation_retention:
                self._cancel_cache.popitem(last=False)

    def observe_interrupt_response(
        self, command: HarnessCommand, message: Mapping[str, object]
    ) -> bool:
        job = self.current_job(command)
        if job is None:
            return False
        request_id = message.get("id")
        with job.changed:
            if request_id != job.interrupt_request_id:
                return False
            if "error" in message:
                job.interrupt_error = True
            elif "result" in message:
                job.interrupt_acknowledged = True
            else:
                return False
            job.changed.notify_all()
        return True

    def note_turn_completed(
        self,
        command: HarnessCommand,
        thread_id: str,
        turn_id: str,
        turn_status: str,
    ) -> None:
        job = self.current_job(command)
        if (
            job is None
            or job.thread_id != thread_id
            or not turn_id
            or job.run_id != turn_id
        ):
            return
        with job.changed:
            job.turn_status = turn_status
            if turn_status == "interrupted":
                job.state = HarnessJobState.CANCELLED
            elif turn_status == "failed":
                job.state = HarnessJobState.FAILED
            job.changed.notify_all()

    def _run_job(
        self,
        job: _CodexBackgroundJob,
        execute: BackgroundExecution,
        failure_response: BackgroundFailureResponse,
    ) -> None:
        self._current.job_id = job.job_id
        response: HarnessResponse | None = None
        try:
            try:
                response = execute(job.command)
                with job.changed:
                    job.response = response
                    if job.turn_status == "interrupted":
                        job.state = HarnessJobState.CANCELLED
                    elif response.ok:
                        job.state = HarnessJobState.COMPLETED
                    else:
                        job.state = HarnessJobState.FAILED
                    job.changed.notify_all()
            except Exception:
                response = failure_response(job)
                with job.changed:
                    job.response = response
                    job.state = (
                        HarnessJobState.CANCELLED
                        if job.turn_status == "interrupted"
                        else HarnessJobState.FAILED
                    )
                    job.changed.notify_all()
            assert response is not None
            self._acknowledge_completion(job)
        except Exception:
            # The completed host turn remains owned locally. A request retry can
            # replay only its durable completion callback; it must never execute
            # the agent turn again.
            pass
        finally:
            with job.changed:
                job.session = None
                job.transport = None
                job.changed.notify_all()
            job.terminal.set()
            self._current.job_id = None

    def _acknowledge_completion(self, job: _CodexBackgroundJob) -> None:
        """Persist one terminal result and retain it only after acknowledgement."""

        with job.completion_lock:
            with job.changed:
                if job.completion_acknowledged:
                    return
                response = job.response
                state = job.state
            if response is None or state not in {
                HarnessJobState.COMPLETED,
                HarnessJobState.CANCELLED,
                HarnessJobState.FAILED,
            }:
                raise RuntimeError("Codex background completion is not terminal")
            # A normal return is the application's explicit acknowledgement that
            # the exact command and job are both durable and terminal.
            job.completion_callback(job.job_id, state, response)
            with job.changed:
                job.completion_acknowledged = True
                job.changed.notify_all()
        self._remember_terminal(job)

    def _remember_terminal(self, job: _CodexBackgroundJob) -> None:
        with self._lock:
            if self._closed or self._jobs.get(job.job_id) is not job:
                return
            self._terminal_job_ids[job.job_id] = None
            self._terminal_job_ids.move_to_end(job.job_id)
            while len(self._terminal_job_ids) > self._terminal_job_retention:
                old_job_id, _ = self._terminal_job_ids.popitem(last=False)
                old_job = self._jobs.get(old_job_id)
                if old_job is None or not old_job.completion_acknowledged:
                    continue
                self._jobs.pop(old_job_id, None)
                if self._command_ids.get(old_job.command.command_id) == old_job_id:
                    self._command_ids.pop(old_job.command.command_id, None)

    def _remove_if_owned(self, job: _CodexBackgroundJob) -> None:
        with self._lock:
            if self._jobs.get(job.job_id) is job:
                self._jobs.pop(job.job_id, None)
            if self._command_ids.get(job.command.command_id) == job.job_id:
                self._command_ids.pop(job.command.command_id, None)


def codex_background_job_id(command_id: str) -> str:
    digest = hashlib.sha256(command_id.encode("utf-8")).hexdigest()[:24]
    return f"harness-job-{digest}"
