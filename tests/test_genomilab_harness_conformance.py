"""Host-neutral contract tests shared by every GenomiLab harness adapter."""

from __future__ import annotations

import itertools
import json
import subprocess
import threading
import unittest
from typing import Any, Mapping

from genomi.lab.harness import (
    BindingStatus,
    CancelTaskWorkPayload,
    CancellationOutcome,
    HarnessArtifactKind,
    HarnessCommand,
    HarnessErrorCode,
    HarnessEvent,
    HarnessEventKind,
    HarnessEventStatus,
    HarnessOperation,
    InstalledCodexAppServerAdapter,
    PROTOCOL_VERSION,
    ReplayStatus,
    ResumeTaskRunPayload,
    SimulatedHarnessAdapter,
    StartTaskRunPayload,
)
from genomi.lab.harness_adapter import HostArtifact


_THREAD_IDS = itertools.count(1)


class _ContractCodexTransport:
    """Protocol-faithful app-server transport with deterministic host output."""

    def __init__(self, *_: Any) -> None:
        self.sent: list[dict[str, Any]] = []
        self.pending: list[dict[str, Any]] = []
        self.thread_id = f"contract-codex-thread-{next(_THREAD_IDS)}"
        self.closed = False

    def send(self, message: Any) -> None:
        request = dict(message)
        self.sent.append(request)
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}
        if method == "initialize":
            self.pending.append(
                {"id": request_id, "result": {"userAgent": "codex-contract"}}
            )
        elif method == "thread/start":
            self.pending.append(
                {"id": request_id, "result": {"thread": {"id": self.thread_id}}}
            )
        elif method == "thread/resume":
            self.thread_id = str(params["threadId"])
            self.pending.append(
                {"id": request_id, "result": {"thread": {"id": self.thread_id}}}
            )
        elif method == "turn/start":
            turn_id = f"contract-turn-{request_id}"
            self.pending.extend(
                [
                    {"id": request_id, "result": {"turn": {"id": turn_id}}},
                    {
                        "method": "turn/completed",
                        "params": {
                            "threadId": self.thread_id,
                            "turn": {
                                "id": turn_id,
                                "status": "completed",
                                "items": [
                                    {
                                        "type": "agentMessage",
                                        "id": f"message-{turn_id}",
                                        "text": json.dumps(
                                            _artifact_for_schema(params["outputSchema"])
                                        ),
                                        "phase": "final_answer",
                                        "memoryCitation": None,
                                    }
                                ],
                            },
                        },
                    },
                ]
            )

    def receive(self, timeout_seconds: float) -> dict[str, Any]:
        if not self.pending:
            raise subprocess.TimeoutExpired("contract-codex", timeout_seconds)
        return self.pending.pop(0)

    def close(self) -> None:
        self.closed = True


class _FailingContractCodexTransport(_ContractCodexTransport):
    def send(self, message: Any) -> None:
        request = dict(message)
        if request.get("method") != "turn/start":
            super().send(request)
            return
        self.sent.append(request)
        request_id = request["id"]
        turn_id = f"contract-failed-turn-{request_id}"
        self.pending.extend(
            [
                {"id": request_id, "result": {"turn": {"id": turn_id}}},
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": self.thread_id,
                        "turn": {
                            "id": turn_id,
                            "status": "failed",
                            "items": [],
                        },
                    },
                },
            ]
        )


class _HeldContractCodexTransport(_ContractCodexTransport):
    def __init__(self, *_: Any) -> None:
        super().__init__()
        self.turn_started = threading.Event()
        self.interrupt_requested = threading.Event()
        self._condition = threading.Condition()
        self._interrupt_reply_sent = False
        self.turn_id = "contract-held-turn"

    def send(self, message: Any) -> None:
        request = dict(message)
        method = request.get("method")
        if method not in {"turn/start", "turn/interrupt"}:
            super().send(request)
            return
        self.sent.append(request)
        if method == "turn/start":
            self.pending.append(
                {"id": request["id"], "result": {"turn": {"id": self.turn_id}}}
            )
            self.turn_started.set()
            return
        self.interrupt_requested.set()
        with self._condition:
            self._condition.notify_all()

    def receive(self, timeout_seconds: float) -> dict[str, Any]:
        if self.pending:
            return self.pending.pop(0)
        with self._condition:
            self._condition.wait_for(
                self.interrupt_requested.is_set,
                timeout=max(0.0, timeout_seconds),
            )
        if not self.interrupt_requested.is_set():
            raise subprocess.TimeoutExpired("contract-held-codex", timeout_seconds)
        interrupt = next(
            item for item in self.sent if item.get("method") == "turn/interrupt"
        )
        if not self._interrupt_reply_sent:
            self._interrupt_reply_sent = True
            return {"id": interrupt["id"], "result": {}}
        return {
            "method": "turn/completed",
            "params": {
                "threadId": self.thread_id,
                "turn": {
                    "id": self.turn_id,
                    "status": "interrupted",
                    "items": [],
                },
            },
        }


class _FailingSimulatedHarnessAdapter(SimulatedHarnessAdapter):
    def _produce_artifact(
        self,
        artifact_kind: HarnessArtifactKind,
        command: HarnessCommand,
        instruction: str,
        approved_context: Mapping[str, Any],
        *,
        resume_task_id: str | None,
    ) -> HostArtifact:
        raise ValueError("synthetic host failure")


def _artifact_for_schema(schema: dict[str, Any]) -> dict[str, Any]:
    required = set(schema.get("required") or [])
    if "capability_requests" in required:
        return {
            "summary": "Synthetic host-neutral plan.",
            "steps": [],
            "proposed_agent_roles": [],
            "capability_requests": [],
            "required_approvals": [],
        }
    if "request_results" in required:
        return {
            "summary": "Synthetic host-neutral execution report.",
            "request_results": [],
        }
    return {
        "title": "Synthetic host-neutral brief",
        "summary": "Synthetic contract output.",
        "clinical_stage": "research_observation",
        "modality_badges": ["patient_report"],
        "claims": [
            {
                "statement": "This is a synthetic contract observation.",
                "claim_role": "observation",
                "evidence_record_ids": [],
                "profile_revision_ids": ["synthetic-profile-revision"],
            }
        ],
        "hypothesis_ids": [],
        "gap_ids": [],
        "confirmation_needs": [],
        "professional_questions": [],
        "clinical_boundary": (
            "Research support only; this is not a diagnosis or treatment decision."
        ),
        "change_summary": "Synthetic contract draft.",
    }


def _start_command(
    *,
    command_id: str = "contract-start",
    approved_context: dict[str, Any] | None = None,
    protocol_version: str = PROTOCOL_VERSION,
) -> HarnessCommand:
    return HarnessCommand(
        operation=HarnessOperation.START_TASK_RUN,
        workspace_session_id="contract-session",
        command_id=command_id,
        user_id="contract-user",
        investigation_id="contract-investigation",
        expected_revision=0,
        protocol_version=protocol_version,
        payload=StartTaskRunPayload(
            "Investigate an explicitly synthetic condition.",
            approved_context or {},
        ),
    )


def _bound_command(
    operation: HarnessOperation,
    *,
    command_id: str,
    task_id: str,
    run_id: str,
    expected_revision: int,
    latest_cursor: int,
    payload: Any,
    user_id: str = "contract-user",
    workspace_session_id: str = "contract-session",
    binding_status: BindingStatus = BindingStatus.WAITING,
) -> HarnessCommand:
    return HarnessCommand(
        operation=operation,
        workspace_session_id=workspace_session_id,
        command_id=command_id,
        user_id=user_id,
        investigation_id="contract-investigation",
        task_id=task_id,
        run_id=run_id,
        binding_status=binding_status,
        latest_event_cursor=latest_cursor,
        current_binding_revision=expected_revision,
        expected_revision=expected_revision,
        payload=payload,
    )


class _HarnessAdapterConformanceContract:
    """These tests are inherited unchanged by each concrete adapter fixture."""

    def make_adapter(
        self, *, replay_window: int = 20, fail_host: bool = False
    ) -> Any:
        raise NotImplementedError

    def make_cancellable_work(self) -> tuple[Any, tuple[str, str, int]]:
        adapter = self.make_adapter()
        started = adapter.start_task_run(_start_command())
        self.assertTrue(started.ok, started.error)
        result = started.result
        return adapter, (result.task_id, result.run_id, result.latest_cursor)

    def assert_no_cancel_side_effect(self) -> None:
        return

    def assert_cancel_side_effect(self) -> None:
        return

    def test_manifest_exposes_the_required_host_neutral_contract(self) -> None:
        adapter = self.make_adapter()
        manifest = adapter.capability_manifest()
        self.assertTrue(manifest.available)
        self.assertEqual(manifest.supported_protocol_versions, (PROTOCOL_VERSION,))
        self.assertEqual(set(manifest.supported_operations), set(HarnessOperation))
        self.assertEqual(set(manifest.artifact_kinds), set(HarnessArtifactKind))
        self.assertTrue(manifest.event_streaming)
        self.assertTrue(manifest.event_replay)
        self.assertTrue(manifest.approved_context_delivery)

    def test_start_is_idempotent_and_command_collisions_are_typed(self) -> None:
        adapter = self.make_adapter()
        command = _start_command()
        first = adapter.start_task_run(command)
        duplicate = adapter.start_task_run(command)
        self.assertTrue(first.ok, first.error)
        self.assertEqual(first, duplicate)
        self.assertEqual(first.current_revision, 1)
        self.assertEqual(
            len(adapter.replay_events("contract-investigation", after_cursor=0).events),
            1,
        )

        collision = adapter.start_task_run(
            _start_command(
                command_id=command.command_id,
                approved_context={"synthetic_context": "changed"},
            )
        )
        self.assertFalse(collision.ok)
        self.assertEqual(collision.error.code, HarnessErrorCode.INVALID_COMMAND)
        self.assertEqual(collision.current_revision, 1)

    def test_revision_and_binding_identity_are_enforced(self) -> None:
        adapter = self.make_adapter()
        started = adapter.start_task_run(_start_command())
        self.assertTrue(started.ok, started.error)
        result = started.result
        self.assertIsNotNone(result)

        stale = adapter.resume_task_run(
            _bound_command(
                HarnessOperation.RESUME_TASK_RUN,
                command_id="contract-stale",
                task_id=result.task_id,
                run_id=result.run_id,
                expected_revision=0,
                latest_cursor=result.latest_cursor,
                payload=ResumeTaskRunPayload("Synthetic stale resume."),
            )
        )
        self.assertFalse(stale.ok)
        self.assertEqual(stale.error.code, HarnessErrorCode.REVISION_CONFLICT)

        wrong_user = adapter.resume_task_run(
            _bound_command(
                HarnessOperation.RESUME_TASK_RUN,
                command_id="contract-wrong-user",
                task_id=result.task_id,
                run_id=result.run_id,
                expected_revision=1,
                latest_cursor=result.latest_cursor,
                payload=ResumeTaskRunPayload("Synthetic cross-user resume."),
                user_id="different-user",
            )
        )
        self.assertFalse(wrong_user.ok)
        self.assertEqual(wrong_user.error.code, HarnessErrorCode.BINDING_CONFLICT)

        resumed = adapter.resume_task_run(
            _bound_command(
                HarnessOperation.RESUME_TASK_RUN,
                command_id="contract-resume",
                task_id=result.task_id,
                run_id=result.run_id,
                expected_revision=1,
                latest_cursor=result.latest_cursor,
                payload=ResumeTaskRunPayload("Synthetic valid resume."),
            )
        )
        self.assertTrue(resumed.ok, resumed.error)
        self.assertEqual(resumed.current_revision, 2)

    def test_event_identity_ordering_deduplication_and_replay_window(self) -> None:
        adapter = self.make_adapter(replay_window=2)
        started = adapter.start_task_run(_start_command())
        self.assertTrue(started.ok, started.error)
        result = started.result
        event = adapter.replay_events(
            "contract-investigation", after_cursor=0
        ).events[0]
        duplicate = adapter.accept_host_event(event)
        self.assertTrue(duplicate.accepted)
        self.assertTrue(duplicate.duplicate)

        collision = HarnessEvent(
            event_id=event.event_id,
            kind=HarnessEventKind.AGENT_PROGRESS,
            workspace_session_id=event.workspace_session_id,
            host_id=event.host_id,
            task_id=event.task_id,
            run_id=event.run_id,
            investigation_id=event.investigation_id,
            user_id=event.user_id,
            cursor=event.cursor,
            correlation_id=event.correlation_id,
            status=HarnessEventStatus.RUNNING,
            timestamp=event.timestamp,
            payload={
                "agent_id": "contract-agent",
                "assigned_step_id": "contract-step",
                "progress": "Different content under the same event identifier.",
            },
        )
        rejected = adapter.accept_host_event(collision)
        self.assertFalse(rejected.accepted)
        self.assertEqual(rejected.error.code, HarnessErrorCode.EVENT_ID_COLLISION)

        out_of_order = HarnessEvent(
            event_id="contract-out-of-order",
            kind=HarnessEventKind.AGENT_PROGRESS,
            workspace_session_id=event.workspace_session_id,
            host_id=event.host_id,
            task_id=event.task_id,
            run_id=event.run_id,
            investigation_id=event.investigation_id,
            user_id=event.user_id,
            cursor=event.cursor + 2,
            correlation_id=event.correlation_id,
            status=HarnessEventStatus.RUNNING,
            timestamp=event.timestamp,
            payload={
                "agent_id": "contract-agent",
                "assigned_step_id": "contract-step",
                "progress": "This event skipped a cursor.",
            },
        )
        rejected_order = adapter.accept_host_event(out_of_order)
        self.assertFalse(rejected_order.accepted)
        self.assertEqual(
            rejected_order.error.code,
            HarnessErrorCode.EVENT_ORDER_CONFLICT,
        )

        first_resume = adapter.resume_task_run(
            _bound_command(
                HarnessOperation.RESUME_TASK_RUN,
                command_id="contract-replay-1",
                task_id=result.task_id,
                run_id=result.run_id,
                expected_revision=1,
                latest_cursor=result.latest_cursor,
                payload=ResumeTaskRunPayload("Synthetic replay step one."),
            )
        )
        self.assertTrue(first_resume.ok, first_resume.error)
        second_result = first_resume.result
        second_resume = adapter.resume_task_run(
            _bound_command(
                HarnessOperation.RESUME_TASK_RUN,
                command_id="contract-replay-2",
                task_id=second_result.task_id,
                run_id=second_result.run_id,
                expected_revision=2,
                latest_cursor=second_result.latest_cursor,
                payload=ResumeTaskRunPayload("Synthetic replay step two."),
            )
        )
        self.assertTrue(second_resume.ok, second_resume.error)
        expired = adapter.replay_events(
            "contract-investigation", after_cursor=0
        )
        self.assertEqual(expired.status, ReplayStatus.SNAPSHOT_REQUIRED)
        self.assertEqual(expired.events, ())
        expired_replay = adapter.accept_host_event(event)
        self.assertFalse(expired_replay.accepted)
        self.assertFalse(expired_replay.duplicate)
        self.assertIn(
            expired_replay.error.code,
            {
                HarnessErrorCode.INVALID_EVENT,
                HarnessErrorCode.EVENT_ORDER_CONFLICT,
            },
        )

    def test_unsupported_protocol_is_a_typed_error(self) -> None:
        adapter = self.make_adapter()
        response = adapter.start_task_run(
            _start_command(protocol_version="genomilab.harness.unsupported")
        )
        self.assertFalse(response.ok)
        self.assertEqual(response.error.code, HarnessErrorCode.CAPABILITY_UNAVAILABLE)
        self.assertEqual(response.current_revision, 0)

    def test_host_execution_failure_is_typed_and_does_not_create_state(self) -> None:
        adapter = self.make_adapter(fail_host=True)
        response = adapter.start_task_run(_start_command())
        self.assertFalse(response.ok)
        self.assertEqual(response.error.code, HarnessErrorCode.HOST_EXECUTION_FAILED)
        self.assertEqual(response.current_revision, 0)
        self.assertEqual(
            adapter.replay_events(
                "contract-investigation", after_cursor=0
            ).events,
            (),
        )

    def test_cancellation_checks_identity_and_is_idempotent(self) -> None:
        adapter, binding = self.make_cancellable_work()
        task_id, run_id, latest_cursor = binding

        wrong_identity = adapter.cancel_task_work(
            _bound_command(
                HarnessOperation.CANCEL_TASK_WORK,
                command_id="contract-cross-user-cancel",
                task_id=task_id,
                run_id=run_id,
                expected_revision=1,
                latest_cursor=latest_cursor,
                payload=CancelTaskWorkPayload("Synthetic unauthorized cancellation."),
                user_id="different-user",
                workspace_session_id="different-session",
            )
        )
        self.assertFalse(wrong_identity.ok)
        self.assertEqual(
            wrong_identity.error.code,
            HarnessErrorCode.BINDING_CONFLICT,
        )
        self.assert_no_cancel_side_effect()

        command = _bound_command(
            HarnessOperation.CANCEL_TASK_WORK,
            command_id="contract-cancel",
            task_id=task_id,
            run_id=run_id,
            expected_revision=1,
            latest_cursor=latest_cursor,
            payload=CancelTaskWorkPayload("Synthetic authorized cancellation."),
        )
        cancelled = adapter.cancel_task_work(command)
        duplicate = adapter.cancel_task_work(command)
        self.assertTrue(cancelled.ok, cancelled.error)
        self.assertEqual(cancelled, duplicate)
        self.assertEqual(cancelled.result.outcome, CancellationOutcome.CANCELLED)
        self.assertEqual(cancelled.current_revision, 2)
        self.assert_cancel_side_effect()


class SimulatedHarnessAdapterConformanceTests(
    _HarnessAdapterConformanceContract, unittest.TestCase
):
    def make_adapter(
        self, *, replay_window: int = 20, fail_host: bool = False
    ) -> SimulatedHarnessAdapter:
        adapter_type = (
            _FailingSimulatedHarnessAdapter
            if fail_host
            else SimulatedHarnessAdapter
        )
        return adapter_type(
            adapter_id="contract-simulated",
            replay_window=replay_window,
        )


class InstalledCodexAdapterConformanceTests(
    _HarnessAdapterConformanceContract, unittest.TestCase
):
    def make_adapter(
        self, *, replay_window: int = 20, fail_host: bool = False
    ) -> InstalledCodexAppServerAdapter:
        return InstalledCodexAppServerAdapter(
            "/synthetic/codex",
            host_version="codex-contract",
            processing_destination="remote: synthetic Codex contract fixture",
            transport_factory=(
                _FailingContractCodexTransport
                if fail_host
                else _ContractCodexTransport
            ),
            timeout_seconds=2,
            replay_window=replay_window,
        )

    def make_cancellable_work(
        self,
    ) -> tuple[InstalledCodexAppServerAdapter, tuple[str, str, int]]:
        self.held_transport = _HeldContractCodexTransport()
        adapter = InstalledCodexAppServerAdapter(
            "/synthetic/codex",
            host_version="codex-contract",
            processing_destination="remote: synthetic Codex contract fixture",
            transport_factory=lambda *_: self.held_transport,
            timeout_seconds=2,
        )
        identities = []
        adapter.dispatch_background(
            _start_command(),
            submission_callback=lambda _submission: None,
            identity_callback=identities.append,
            completion_callback=lambda *_: None,
        )
        self.assertTrue(self.held_transport.turn_started.wait(1))
        self.assertEqual(len(identities), 1)
        identity = identities[0]
        replay = adapter.replay_events(
            "contract-investigation", after_cursor=0
        )
        return adapter, (
            identity.task_id,
            identity.run_id,
            replay.latest_cursor,
        )

    def assert_no_cancel_side_effect(self) -> None:
        self.assertFalse(self.held_transport.interrupt_requested.is_set())

    def assert_cancel_side_effect(self) -> None:
        self.assertTrue(self.held_transport.interrupt_requested.is_set())


if __name__ == "__main__":
    unittest.main()
