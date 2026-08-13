from __future__ import annotations

import json
import unittest
from typing import Any

from genomi.lab.harness import (
    AgentProgressPayload,
    AgentStartedPayload,
    ArtifactReference,
    CancelTaskWorkPayload,
    CancellationOutcome,
    HarnessArtifactKind,
    BindingStatus,
    HarnessCommand,
    HarnessErrorCode,
    HarnessEvent,
    HarnessEventKind,
    HarnessEventStatus,
    HarnessOperation,
    PROTOCOL_VERSION,
    ReplayStatus,
    ReplaceTaskBindingPayload,
    ResumeTaskRunPayload,
    SendTaskMessagePayload,
    SimulatedHarnessAdapter,
    StartTaskRunPayload,
    safe_json_dumps,
)


def _start_command(
    *,
    command_id: str = "command-start",
    investigation_id: str = "investigation-a",
    approved_context: dict[str, Any] | None = None,
) -> HarnessCommand:
    return HarnessCommand(
        operation=HarnessOperation.START_TASK_RUN,
        workspace_session_id="session-a",
        command_id=command_id,
        user_id="user-a",
        investigation_id=investigation_id,
        expected_revision=0,
        payload=StartTaskRunPayload(
            "Investigate whether the molecular profile informs this condition",
            approved_context
            or {
                "patient_molecular_snapshot_id": "snapshot-a",
                "observation_revision_ids": ["observation-a"],
            },
        ),
    )


def _bound_command(
    operation: HarnessOperation,
    *,
    command_id: str,
    task_id: str,
    run_id: str,
    expected_revision: int,
    payload: Any,
    binding_status: BindingStatus = BindingStatus.WAITING,
    latest_event_cursor: int = 1,
    current_binding_revision: int | None = None,
    investigation_id: str = "investigation-a",
) -> HarnessCommand:
    return HarnessCommand(
        operation=operation,
        workspace_session_id="session-a",
        command_id=command_id,
        user_id="user-a",
        investigation_id=investigation_id,
        task_id=task_id,
        run_id=run_id,
        binding_status=binding_status,
        latest_event_cursor=latest_event_cursor,
        current_binding_revision=(
            expected_revision
            if current_binding_revision is None
            else current_binding_revision
        ),
        expected_revision=expected_revision,
        payload=payload,
    )


class SimulatedHarnessConformanceTests(unittest.TestCase):
    """The same behavioral contract runs against independently named hosts."""

    def adapters(self, *, replay_window: int = 20) -> list[SimulatedHarnessAdapter]:
        return [
            SimulatedHarnessAdapter(
                adapter_id="simulated-alpha", replay_window=replay_window
            ),
            SimulatedHarnessAdapter(
                adapter_id="simulated-beta", replay_window=replay_window
            ),
        ]

    def test_manifest_declares_the_host_neutral_contract(self) -> None:
        for adapter in self.adapters():
            with self.subTest(adapter=adapter.manifest.adapter_id):
                manifest = adapter.capability_manifest()
                self.assertTrue(manifest.available)
                self.assertEqual(
                    manifest.supported_protocol_versions, (PROTOCOL_VERSION,)
                )
                self.assertEqual(
                    set(manifest.supported_operations), set(HarnessOperation)
                )
                self.assertTrue(manifest.event_streaming)
                self.assertTrue(manifest.event_replay)
                self.assertEqual(set(manifest.artifact_kinds), set(HarnessArtifactKind))
                self.assertTrue(manifest.agent_delegation_planning)
                self.assertTrue(manifest.agent_delegation_event_reporting)
                self.assertTrue(manifest.approved_context_delivery)
                self.assertFalse(manifest.background_job_attach)
                self.assertFalse(manifest.background_job_cancel)
                self.assertEqual(
                    set(manifest.to_dict()["event_kinds"]),
                    {kind.value for kind in HarnessEventKind},
                )

    def test_start_is_idempotent_and_command_id_collision_is_typed(self) -> None:
        for adapter in self.adapters():
            with self.subTest(adapter=adapter.manifest.adapter_id):
                command = _start_command()
                first = adapter.start_task_run(command)
                duplicate = adapter.start_task_run(command)

                self.assertTrue(first.ok)
                self.assertEqual(first, duplicate)
                self.assertEqual(first.accepted_revision, 1)
                self.assertEqual(first.current_revision, 1)
                self.assertIsNotNone(first.result)
                assert first.result is not None
                self.assertEqual(first.result.binding_status.value, "waiting")
                self.assertEqual(
                    first.result.proposed_artifact["proposed_agent_roles"][0]["role"],
                    "patient_context_reviewer",
                )
                self.assertEqual(first.result.latest_cursor, 1)
                self.assertEqual(
                    len(
                        adapter.replay_events("investigation-a", after_cursor=0).events
                    ),
                    1,
                )
                proposal_event = adapter.replay_events(
                    "investigation-a", after_cursor=0
                ).events[0]
                self.assertEqual(
                    proposal_event.payload,
                    {
                        "artifact_kind": "plan",
                        "artifact_reference": (
                            first.result.proposed_artifact_reference.to_dict()
                        ),
                    },
                )
                self.assertNotIn("artifact", proposal_event.payload)

                collision = adapter.start_task_run(
                    _start_command(
                        command_id=command.command_id,
                        approved_context={
                            "patient_molecular_snapshot_id": "different-snapshot"
                        },
                    )
                )
                self.assertFalse(collision.ok)
                assert collision.error is not None
                self.assertEqual(collision.error.code, HarnessErrorCode.INVALID_COMMAND)
                self.assertEqual(collision.current_revision, 1)

    def test_resume_send_and_replace_use_expected_revisions_and_task_binding(
        self,
    ) -> None:
        for adapter in self.adapters():
            with self.subTest(adapter=adapter.manifest.adapter_id):
                started = adapter.start_task_run(_start_command())
                assert started.result is not None
                original_task_id = started.result.task_id

                stale = adapter.resume_task_run(
                    _bound_command(
                        HarnessOperation.RESUME_TASK_RUN,
                        command_id="command-stale",
                        task_id=original_task_id,
                        run_id=started.result.run_id,
                        expected_revision=0,
                        payload=ResumeTaskRunPayload("Continue planning"),
                    )
                )
                self.assertFalse(stale.ok)
                assert stale.error is not None
                self.assertEqual(stale.error.code, HarnessErrorCode.REVISION_CONFLICT)
                self.assertEqual(stale.error.current_revision, 1)

                wrong_run = adapter.resume_task_run(
                    HarnessCommand(
                        operation=HarnessOperation.RESUME_TASK_RUN,
                        workspace_session_id="session-a",
                        command_id="command-wrong-run",
                        user_id="user-a",
                        investigation_id="investigation-a",
                        task_id=original_task_id,
                        run_id="different-run",
                        binding_status=BindingStatus.WAITING,
                        latest_event_cursor=1,
                        current_binding_revision=1,
                        expected_revision=1,
                        payload=ResumeTaskRunPayload("Continue planning"),
                    )
                )
                self.assertFalse(wrong_run.ok)
                assert wrong_run.error is not None
                self.assertEqual(
                    wrong_run.error.code, HarnessErrorCode.BINDING_CONFLICT
                )

                resumed = adapter.resume_task_run(
                    _bound_command(
                        HarnessOperation.RESUME_TASK_RUN,
                        command_id="command-resume",
                        task_id=original_task_id,
                        run_id=started.result.run_id,
                        expected_revision=1,
                        payload=ResumeTaskRunPayload("Revise the proposed plan"),
                    )
                )
                self.assertTrue(resumed.ok)
                self.assertEqual(resumed.current_revision, 2)
                assert resumed.result is not None
                self.assertEqual(resumed.result.task_id, original_task_id)

                completed = adapter.send_task_message(
                    _bound_command(
                        HarnessOperation.SEND_TASK_MESSAGE,
                        command_id="command-message",
                        task_id=original_task_id,
                        run_id=resumed.result.run_id,
                        binding_status=resumed.result.binding_status,
                        expected_revision=2,
                        payload=SendTaskMessagePayload(
                            "Draft the evidence-linked brief"
                        ),
                    )
                )
                self.assertTrue(completed.ok)
                self.assertEqual(completed.current_revision, 3)
                assert completed.result is not None
                self.assertEqual(completed.result.binding_status.value, "completed")
                self.assertEqual(
                    completed.result.proposed_artifact_reference.kind,
                    HarnessArtifactKind.BRIEF_DRAFT,
                )

                replaced = adapter.replace_task_binding(
                    _bound_command(
                        HarnessOperation.REPLACE_TASK_BINDING,
                        command_id="command-replace",
                        task_id=original_task_id,
                        run_id=completed.result.run_id,
                        binding_status=completed.result.binding_status,
                        expected_revision=3,
                        payload=ReplaceTaskBindingPayload(
                            "The installed host session was intentionally replaced",
                            "Replan the same canonical investigation",
                            {"patient_molecular_snapshot_id": "snapshot-a"},
                        ),
                    )
                )
                self.assertTrue(replaced.ok)
                self.assertEqual(replaced.current_revision, 4)
                assert replaced.result is not None
                self.assertEqual(replaced.result.replaced_task_id, original_task_id)
                self.assertNotEqual(replaced.result.task_id, original_task_id)

                old_binding_command = adapter.send_task_message(
                    _bound_command(
                        HarnessOperation.SEND_TASK_MESSAGE,
                        command_id="command-old-binding",
                        task_id=original_task_id,
                        run_id=replaced.result.run_id,
                        expected_revision=4,
                        payload=SendTaskMessagePayload(
                            "This must not reach the old task"
                        ),
                    )
                )
                self.assertFalse(old_binding_command.ok)
                assert old_binding_command.error is not None
                self.assertEqual(
                    old_binding_command.error.code, HarnessErrorCode.BINDING_CONFLICT
                )

    def test_cancellation_reports_only_confirmed_scope(self) -> None:
        for adapter in self.adapters():
            with self.subTest(adapter=adapter.manifest.adapter_id):
                started = adapter.start_task_run(_start_command())
                assert started.result is not None
                cancelled = adapter.cancel_task_work(
                    _bound_command(
                        HarnessOperation.CANCEL_TASK_WORK,
                        command_id="command-cancel",
                        task_id=started.result.task_id,
                        run_id=started.result.run_id,
                        expected_revision=1,
                        payload=CancelTaskWorkPayload("Patient stopped this work"),
                    )
                )
                self.assertTrue(cancelled.ok)
                assert cancelled.result is not None
                self.assertEqual(
                    cancelled.result.outcome, CancellationOutcome.CANCELLED
                )
                self.assertFalse(cancelled.result.external_jobs_confirmed_cancelled)
                self.assertEqual(cancelled.current_revision, 2)
                replay = adapter.replay_events("investigation-a", after_cursor=1)
                self.assertEqual(replay.events[0].kind, HarnessEventKind.CANCELLED)

                second = adapter.cancel_task_work(
                    _bound_command(
                        HarnessOperation.CANCEL_TASK_WORK,
                        command_id="command-cancel-again",
                        task_id=started.result.task_id,
                        run_id=cancelled.result.run_id,
                        binding_status=BindingStatus.CANCELLED,
                        expected_revision=2,
                        payload=CancelTaskWorkPayload(),
                    )
                )
                self.assertTrue(second.ok)
                assert second.result is not None
                self.assertEqual(
                    second.result.outcome, CancellationOutcome.NOT_CANCELLABLE
                )
                self.assertEqual(second.current_revision, 2)

    def test_event_deduplication_ordering_and_expired_replay_window(self) -> None:
        for adapter in self.adapters(replay_window=2):
            with self.subTest(adapter=adapter.manifest.adapter_id):
                started = adapter.start_task_run(_start_command())
                assert started.result is not None
                first_event = adapter.replay_events(
                    "investigation-a", after_cursor=0
                ).events[0]
                duplicate = adapter.accept_host_event(first_event)
                self.assertTrue(duplicate.accepted)
                self.assertTrue(duplicate.duplicate)

                collision = HarnessEvent(
                    event_id=first_event.event_id,
                    kind=HarnessEventKind.AGENT_PROGRESS,
                    workspace_session_id=first_event.workspace_session_id,
                    host_id=first_event.host_id,
                    task_id=first_event.task_id,
                    run_id=first_event.run_id,
                    investigation_id=first_event.investigation_id,
                    user_id=first_event.user_id,
                    cursor=first_event.cursor,
                    correlation_id="different-command",
                    status=HarnessEventStatus.RUNNING,
                    timestamp=first_event.timestamp,
                    payload={
                        "agent_id": "agent-a",
                        "assigned_step_id": "step-1",
                        "progress": "different",
                    },
                )
                rejected_collision = adapter.accept_host_event(collision)
                self.assertFalse(rejected_collision.accepted)
                assert rejected_collision.error is not None
                self.assertEqual(
                    rejected_collision.error.code,
                    HarnessErrorCode.EVENT_ID_COLLISION,
                )

                out_of_order = HarnessEvent(
                    event_id="event-out-of-order",
                    kind=HarnessEventKind.AGENT_PROGRESS,
                    workspace_session_id="session-a",
                    host_id=adapter.manifest.adapter_id,
                    task_id=started.result.task_id,
                    run_id=started.result.run_id,
                    investigation_id="investigation-a",
                    user_id="user-a",
                    cursor=3,
                    correlation_id="command-start",
                    status=HarnessEventStatus.RUNNING,
                    timestamp="2026-08-12T00:00:00+00:00",
                    payload={
                        "agent_id": "agent-a",
                        "assigned_step_id": "step-1",
                        "progress": "too soon",
                    },
                )
                rejected_order = adapter.accept_host_event(out_of_order)
                self.assertFalse(rejected_order.accepted)
                assert rejected_order.error is not None
                self.assertEqual(
                    rejected_order.error.code,
                    HarnessErrorCode.EVENT_ORDER_CONFLICT,
                )

                cross_user = HarnessEvent(
                    event_id="event-cross-user",
                    kind=HarnessEventKind.AGENT_PROGRESS,
                    workspace_session_id="session-a",
                    host_id=adapter.manifest.adapter_id,
                    task_id=started.result.task_id,
                    run_id=started.result.run_id,
                    investigation_id="investigation-a",
                    user_id="user-b",
                    cursor=2,
                    correlation_id="command-start",
                    status=HarnessEventStatus.RUNNING,
                    timestamp="2026-08-12T00:00:00+00:00",
                    payload={
                        "agent_id": "agent-a",
                        "assigned_step_id": "step-1",
                        "progress": "must not cross users",
                    },
                )
                rejected_identity = adapter.accept_host_event(cross_user)
                self.assertFalse(rejected_identity.accepted)
                assert rejected_identity.error is not None
                self.assertEqual(
                    rejected_identity.error.code, HarnessErrorCode.INVALID_EVENT
                )

                resume_one = adapter.resume_task_run(
                    _bound_command(
                        HarnessOperation.RESUME_TASK_RUN,
                        command_id="command-resume-one",
                        task_id=started.result.task_id,
                        run_id=started.result.run_id,
                        expected_revision=1,
                        payload=ResumeTaskRunPayload("First revision"),
                    )
                )
                self.assertTrue(resume_one.ok)
                resume_two = adapter.resume_task_run(
                    _bound_command(
                        HarnessOperation.RESUME_TASK_RUN,
                        command_id="command-resume-two",
                        task_id=started.result.task_id,
                        run_id=resume_one.result.run_id,
                        expected_revision=2,
                        payload=ResumeTaskRunPayload("Second revision"),
                    )
                )
                self.assertTrue(resume_two.ok)

                expired = adapter.replay_events("investigation-a", after_cursor=0)
                self.assertEqual(expired.status, ReplayStatus.SNAPSHOT_REQUIRED)
                self.assertEqual(expired.events, ())
                self.assertEqual(expired.earliest_available_cursor, 2)
                replay = adapter.replay_events("investigation-a", after_cursor=1)
                self.assertEqual(replay.status, ReplayStatus.EVENTS)
                self.assertEqual([event.cursor for event in replay.events], [2, 3])

    def test_host_reported_delegation_is_distinct_from_the_proposed_plan(self) -> None:
        adapter = SimulatedHarnessAdapter()
        started = adapter.start_task_run(_start_command())
        assert started.result is not None
        started_payload = AgentStartedPayload(
            "agent-a", "patient_context_reviewer", "step-1"
        )
        agent_started = HarnessEvent(
            event_id="event-agent-started",
            kind=HarnessEventKind.AGENT_STARTED,
            workspace_session_id="session-a",
            host_id=adapter.manifest.adapter_id,
            task_id=started.result.task_id,
            run_id=started.result.run_id,
            investigation_id="investigation-a",
            user_id="user-a",
            cursor=2,
            correlation_id="command-start",
            status=HarnessEventStatus.RUNNING,
            timestamp="2026-08-12T00:00:00+00:00",
            payload=started_payload.to_dict(),
        )
        progress_payload = AgentProgressPayload(
            "agent-a", "step-1", "Reviewing approved context"
        )
        progress = HarnessEvent(
            event_id="event-agent-progress",
            kind=HarnessEventKind.AGENT_PROGRESS,
            workspace_session_id="session-a",
            host_id=adapter.manifest.adapter_id,
            task_id=started.result.task_id,
            run_id=started.result.run_id,
            investigation_id="investigation-a",
            user_id="user-a",
            cursor=3,
            correlation_id="command-start",
            status=HarnessEventStatus.RUNNING,
            timestamp="2026-08-12T00:01:00+00:00",
            payload=progress_payload.to_dict(),
        )

        self.assertTrue(adapter.accept_host_event(agent_started).accepted)
        self.assertTrue(adapter.accept_host_event(progress).accepted)
        replay = adapter.replay_events("investigation-a", after_cursor=1)
        self.assertEqual(
            [event.kind for event in replay.events],
            [HarnessEventKind.AGENT_STARTED, HarnessEventKind.AGENT_PROGRESS],
        )

    def test_host_event_correlation_cannot_cross_investigations(self) -> None:
        adapter = SimulatedHarnessAdapter()
        first = adapter.start_task_run(_start_command())
        second = adapter.start_task_run(
            _start_command(
                command_id="command-start-b", investigation_id="investigation-b"
            )
        )
        assert first.result is not None and second.result is not None
        forged = HarnessEvent(
            event_id="event-cross-investigation-correlation",
            kind=HarnessEventKind.AGENT_STARTED,
            workspace_session_id="session-a",
            host_id=adapter.manifest.adapter_id,
            task_id=first.result.task_id,
            run_id=first.result.run_id,
            investigation_id="investigation-a",
            user_id="user-a",
            cursor=2,
            correlation_id="command-start-b",
            status=HarnessEventStatus.RUNNING,
            timestamp="2026-08-12T00:00:00+00:00",
            payload=AgentStartedPayload(
                "agent-a", "patient_context_reviewer", "step-1"
            ).to_dict(),
        )

        rejected = adapter.accept_host_event(forged)
        self.assertFalse(rejected.accepted)
        assert rejected.error is not None
        self.assertEqual(rejected.error.code, HarnessErrorCode.INVALID_EVENT)

    def test_host_event_correlation_cannot_reuse_a_stale_run_command(self) -> None:
        adapter = SimulatedHarnessAdapter()
        started = adapter.start_task_run(_start_command())
        assert started.result is not None
        resumed = adapter.resume_task_run(
            _bound_command(
                HarnessOperation.RESUME_TASK_RUN,
                command_id="command-resume-current-run",
                task_id=started.result.task_id,
                run_id=started.result.run_id,
                expected_revision=1,
                payload=ResumeTaskRunPayload("Create a new run"),
            )
        )
        assert resumed.result is not None
        stale_correlation = HarnessEvent(
            event_id="event-stale-run-correlation",
            kind=HarnessEventKind.AGENT_STARTED,
            workspace_session_id="session-a",
            host_id=adapter.manifest.adapter_id,
            task_id=resumed.result.task_id,
            run_id=resumed.result.run_id,
            investigation_id="investigation-a",
            user_id="user-a",
            cursor=3,
            correlation_id="command-start",
            status=HarnessEventStatus.RUNNING,
            timestamp="2026-08-12T00:00:00+00:00",
            payload=AgentStartedPayload(
                "agent-a", "patient_context_reviewer", "step-1"
            ).to_dict(),
        )

        rejected = adapter.accept_host_event(stale_correlation)
        self.assertFalse(rejected.accepted)
        assert rejected.error is not None
        self.assertEqual(rejected.error.code, HarnessErrorCode.INVALID_EVENT)

    def test_fresh_adapter_rehydrates_domain_binding_and_requires_snapshot_for_old_cursor(
        self,
    ) -> None:
        first_adapter = SimulatedHarnessAdapter(adapter_id="simulated-restart")
        started = first_adapter.start_task_run(_start_command())
        assert started.result is not None
        restarted_adapter = SimulatedHarnessAdapter(adapter_id="simulated-restart")
        resumed = restarted_adapter.resume_task_run(
            _bound_command(
                HarnessOperation.RESUME_TASK_RUN,
                command_id="command-after-restart",
                task_id=started.result.task_id,
                run_id=started.result.run_id,
                expected_revision=1,
                payload=ResumeTaskRunPayload("Continue after host adapter restart"),
            )
        )
        self.assertTrue(resumed.ok, resumed.error)
        self.assertEqual(resumed.current_revision, 2)
        assert resumed.result is not None
        self.assertEqual(resumed.result.latest_cursor, 2)
        replayed_after_restart = restarted_adapter.replay_events(
            "investigation-a", after_cursor=1
        )
        self.assertEqual([event.cursor for event in replayed_after_restart.events], [2])
        for received_revision in (0, 999):
            stale_adapter = SimulatedHarnessAdapter(adapter_id="simulated-restart")
            stale = stale_adapter.resume_task_run(
                _bound_command(
                    HarnessOperation.RESUME_TASK_RUN,
                    command_id=f"command-stale-restart-{received_revision}",
                    task_id=started.result.task_id,
                    run_id=started.result.run_id,
                    expected_revision=received_revision,
                    current_binding_revision=1,
                    payload=ResumeTaskRunPayload("Must conflict"),
                )
            )
            self.assertFalse(stale.ok)
            assert stale.error is not None
            self.assertEqual(stale.error.code, HarnessErrorCode.REVISION_CONFLICT)
            self.assertEqual(stale.current_revision, 1)
        empty_replay = SimulatedHarnessAdapter().replay_events(
            "investigation-from-before-restart", after_cursor=5
        )
        self.assertEqual(empty_replay.status, ReplayStatus.SNAPSHOT_REQUIRED)

    def test_replace_can_rebind_a_new_workspace_session_without_resetting_investigation_cursor(
        self,
    ) -> None:
        adapter = SimulatedHarnessAdapter()
        started = adapter.start_task_run(_start_command())
        assert started.result is not None
        replacement = HarnessCommand(
            operation=HarnessOperation.REPLACE_TASK_BINDING,
            workspace_session_id="session-b",
            command_id="command-rebind-new-session",
            user_id="user-a",
            investigation_id="investigation-a",
            task_id=started.result.task_id,
            run_id=started.result.run_id,
            binding_status=started.result.binding_status,
            latest_event_cursor=started.result.latest_cursor,
            current_binding_revision=1,
            expected_revision=1,
            payload=ReplaceTaskBindingPayload(
                "The application session restarted",
                "Continue the same canonical investigation",
                {"patient_molecular_snapshot_id": "snapshot-a"},
            ),
        )

        replaced = adapter.replace_task_binding(replacement)
        self.assertTrue(replaced.ok)
        assert replaced.result is not None
        self.assertEqual(replaced.result.latest_cursor, 2)
        events = adapter.replay_events("investigation-a", after_cursor=0).events
        self.assertEqual(
            [event.workspace_session_id for event in events],
            ["session-a", "session-b"],
        )

    def test_fresh_adapter_preserves_terminal_domain_binding_status(self) -> None:
        first_adapter = SimulatedHarnessAdapter(adapter_id="simulated-terminal-restart")
        started = first_adapter.start_task_run(_start_command())
        assert started.result is not None
        completed = first_adapter.send_task_message(
            _bound_command(
                HarnessOperation.SEND_TASK_MESSAGE,
                command_id="command-complete-before-restart",
                task_id=started.result.task_id,
                run_id=started.result.run_id,
                expected_revision=1,
                payload=SendTaskMessagePayload("Complete the brief"),
            )
        )
        assert completed.result is not None
        restarted_after_completion = SimulatedHarnessAdapter(
            adapter_id="simulated-terminal-restart"
        )
        cancel_completed = restarted_after_completion.cancel_task_work(
            _bound_command(
                HarnessOperation.CANCEL_TASK_WORK,
                command_id="command-cancel-completed-after-restart",
                task_id=completed.result.task_id,
                run_id=completed.result.run_id,
                binding_status=BindingStatus.COMPLETED,
                latest_event_cursor=completed.result.latest_cursor,
                expected_revision=2,
                payload=CancelTaskWorkPayload(),
            )
        )
        assert cancel_completed.result is not None
        self.assertEqual(
            cancel_completed.result.outcome,
            CancellationOutcome.ALREADY_COMPLETED,
        )

        cancelled_adapter = SimulatedHarnessAdapter(
            adapter_id="simulated-cancelled-restart"
        )
        cancelled_start = cancelled_adapter.start_task_run(
            _start_command(investigation_id="investigation-cancelled")
        )
        assert cancelled_start.result is not None
        cancelled = cancelled_adapter.cancel_task_work(
            _bound_command(
                HarnessOperation.CANCEL_TASK_WORK,
                command_id="command-cancel-before-restart",
                task_id=cancelled_start.result.task_id,
                run_id=cancelled_start.result.run_id,
                expected_revision=1,
                investigation_id="investigation-cancelled",
                payload=CancelTaskWorkPayload(),
            )
        )
        assert cancelled.result is not None
        restarted_after_cancel = SimulatedHarnessAdapter(
            adapter_id="simulated-cancelled-restart"
        )
        rejected_resume = restarted_after_cancel.resume_task_run(
            _bound_command(
                HarnessOperation.RESUME_TASK_RUN,
                command_id="command-resume-cancelled-after-restart",
                task_id=cancelled.result.task_id,
                run_id=cancelled.result.run_id,
                binding_status=BindingStatus.CANCELLED,
                latest_event_cursor=2,
                current_binding_revision=2,
                expected_revision=2,
                investigation_id="investigation-cancelled",
                payload=ResumeTaskRunPayload("This must require replacement"),
            )
        )
        self.assertFalse(rejected_resume.ok)
        assert rejected_resume.error is not None
        self.assertEqual(rejected_resume.error.code, HarnessErrorCode.BINDING_CONFLICT)

    def test_disabled_operation_returns_capability_unavailable(self) -> None:
        adapter = SimulatedHarnessAdapter(
            unavailable_operations=(HarnessOperation.RESUME_TASK_RUN,)
        )
        started = adapter.start_task_run(_start_command())
        assert started.result is not None
        response = adapter.resume_task_run(
            _bound_command(
                HarnessOperation.RESUME_TASK_RUN,
                command_id="command-disabled-resume",
                task_id=started.result.task_id,
                run_id=started.result.run_id,
                binding_status=started.result.binding_status,
                latest_event_cursor=started.result.latest_cursor,
                current_binding_revision=1,
                expected_revision=1,
                payload=ResumeTaskRunPayload("Continue"),
            )
        )
        self.assertFalse(response.ok)
        assert response.error is not None
        self.assertEqual(response.error.code, HarnessErrorCode.CAPABILITY_UNAVAILABLE)
        self.assertEqual(response.error.details["capability"], "resume_task_run")

    def test_transport_serialization_rejects_secrets_raw_genome_and_unsafe_values(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "not safe for harness transport"):
            StartTaskRunPayload("Question", {"api_key": "must-never-cross"})
        with self.assertRaisesRegex(ValueError, "not safe for harness transport"):
            StartTaskRunPayload("Question", {"paperclip API key": "must-never-cross"})
        with self.assertRaisesRegex(ValueError, "not safe for harness transport"):
            StartTaskRunPayload(
                "Question", {"headers": {"Authorization": "Bearer secret"}}
            )
        with self.assertRaisesRegex(ValueError, "not safe for harness transport"):
            StartTaskRunPayload("Question", {"accessToken": "must-never-cross"})
        with self.assertRaisesRegex(ValueError, "not safe for harness transport"):
            StartTaskRunPayload("Question", {"rawSequence": "ACGT"})
        with self.assertRaisesRegex(ValueError, "not safe for harness transport"):
            StartTaskRunPayload("Question", {"agi_rows": [{"position": 1}]})
        with self.assertRaisesRegex(ValueError, "non-finite"):
            StartTaskRunPayload("Question", {"measurement": float("nan")})
        with self.assertRaisesRegex(ValueError, "unsupported type"):
            safe_json_dumps({"value": object()})

        payload = StartTaskRunPayload(
            "Question",
            {"nested": {"evidence_ids": ["evidence-a"]}},
        )
        with self.assertRaises(TypeError):
            payload.approved_context["nested"]["new"] = "mutation"  # type: ignore[index]
        self.assertEqual(
            payload.to_dict()["approved_context"]["nested"]["evidence_ids"],
            ["evidence-a"],
        )

        reference = ArtifactReference(
            "artifact-a",
            HarnessArtifactKind.PLAN,
            "a" * 64,
        )
        serialized = safe_json_dumps(reference.to_dict())
        self.assertEqual(json.loads(serialized)["kind"], "plan")
