from __future__ import annotations

import unittest

from genomi.lab.harness import (
    BindingStatus,
    HarnessArtifactKind,
    HarnessJobState,
    HarnessOperation,
    ResumeTaskRunPayload,
    SimulatedHarnessAdapter,
    InstalledCodexAppServerAdapter,
)
from genomi.lab.harness_codex_background import CodexBackgroundController
from genomi.lab.harness_events import HarnessResponse, TaskRunResult
from genomi.lab.harness_types import HarnessCommand

from tests.test_genomilab_harness_adapter import _bound_command, _start_command


class CodexBackgroundControllerTests(unittest.TestCase):
    def test_terminal_job_handles_are_bounded_after_durable_completion(self) -> None:
        controller = CodexBackgroundController(
            1, terminal_job_retention=2, cancellation_retention=2
        )
        completed: list[str] = []
        submissions = []

        for index in range(3):
            command = _start_command(command_id=f"bounded-job-{index}")
            submission = controller.dispatch(
                command,
                submission_callback=submissions.append,
                identity_callback=lambda _identity: None,
                completion_callback=lambda job_id, _state, _response: completed.append(
                    job_id
                ),
                execute=lambda _command: _successful_response(_command),
                failure_response=lambda _job: self.fail("execution did not fail"),
            )
            terminal = controller.wait_for_background_job(
                submission.job_id, timeout_seconds=1
            )
            self.assertIsNotNone(terminal)
            assert terminal is not None
            self.assertEqual(terminal.state, HarnessJobState.COMPLETED)

        self.assertEqual(len(completed), 3)
        self.assertEqual(len(submissions), 3)
        self.assertEqual(controller.job_count, 2)
        self.assertIsNone(controller.background_job(completed[0]))
        self.assertIsNotNone(controller.background_job(completed[-1]))

    def test_cancellation_results_and_close_state_are_bounded(self) -> None:
        controller = CodexBackgroundController(
            1, terminal_job_retention=2, cancellation_retention=2
        )
        for index in range(3):
            command = _start_command(command_id=f"cancel-cache-{index}")
            response = _successful_response(command)
            controller.remember_cancellation(
                command.command_id, f"fingerprint-{index}", response
            )

        self.assertEqual(controller.cancellation_count, 2)
        self.assertIsNone(controller.cached_cancellation("cancel-cache-0"))
        self.assertIsNotNone(controller.cached_cancellation("cancel-cache-2"))

        controller.close()

        self.assertEqual(controller.job_count, 0)
        self.assertEqual(controller.cancellation_count, 0)


class HarnessAdapterLifecycleWindowTests(unittest.TestCase):
    def test_inactive_investigations_expire_as_one_correlation_unit(self) -> None:
        adapter = SimulatedHarnessAdapter(
            replay_window=2, investigation_window=2
        )

        first = adapter.start_task_run(
            _start_command(command_id="window-first", investigation_id="window-1")
        )
        adapter.start_task_run(
            _start_command(command_id="window-second", investigation_id="window-2")
        )
        adapter.start_task_run(
            _start_command(command_id="window-third", investigation_id="window-3")
        )

        self.assertNotIn("window-1", adapter._bindings)  # noqa: SLF001
        self.assertNotIn("window-first", adapter._command_cache)  # noqa: SLF001
        self.assertEqual(
            adapter.replay_events("window-1", after_cursor=0).events, ()
        )
        assert first.result is not None
        rehydrated = adapter.resume_task_run(
            _bound_command(
                HarnessOperation.RESUME_TASK_RUN,
                command_id="window-first-resume",
                investigation_id="window-1",
                task_id=first.result.task_id,
                run_id=first.result.run_id,
                expected_revision=1,
                latest_event_cursor=first.result.latest_cursor,
                payload=ResumeTaskRunPayload(
                    "Continue the approved investigation.",
                    artifact_kind=HarnessArtifactKind.PLAN,
                ),
            )
        )
        self.assertTrue(rehydrated.ok, rehydrated.error)

    def test_command_window_preserves_replay_correlations_then_expires_old_entries(
        self,
    ) -> None:
        adapter = SimulatedHarnessAdapter(replay_window=2, command_window=2)
        started = adapter.start_task_run(_start_command(command_id="command-window-0"))
        assert started.result is not None
        current = started.result

        for index in range(1, 4):
            response = adapter.resume_task_run(
                _bound_command(
                    HarnessOperation.RESUME_TASK_RUN,
                    command_id=f"command-window-{index}",
                    task_id=current.task_id,
                    run_id=current.run_id,
                    expected_revision=index,
                    latest_event_cursor=current.latest_cursor,
                    payload=ResumeTaskRunPayload(
                        "Continue the approved investigation.",
                        artifact_kind=HarnessArtifactKind.PLAN,
                    ),
                )
            )
            self.assertTrue(response.ok, response.error)
            assert response.result is not None
            current = response.result

        self.assertNotIn("command-window-0", adapter._command_cache)  # noqa: SLF001
        self.assertEqual(
            set(adapter._command_cache),  # noqa: SLF001
            {"command-window-2", "command-window-3"},
        )

    def test_installed_adapter_exposes_bounded_lifecycle_without_internal_maps(
        self,
    ) -> None:
        adapter = InstalledCodexAppServerAdapter(
            "/opt/codex/bin/codex",
            host_version="codex 9.9.9",
            processing_destination="remote: OpenAI Codex service",
            terminal_job_retention=2,
            cancellation_retention=2,
        )

        self.assertEqual(adapter.background_job_count, 0)
        self.assertEqual(adapter.background_cancellation_count, 0)

        adapter.close()

        self.assertEqual(adapter.background_job_count, 0)
        self.assertEqual(adapter.background_cancellation_count, 0)


def _successful_response(command: HarnessCommand) -> HarnessResponse:
    return HarnessResponse(
        command.command_id,
        command.operation,
        1,
        1,
        result=TaskRunResult(
            "codex-thread-test",
            "codex-turn-test",
            BindingStatus.RUNNING,
            None,
            None,
            0,
        ),
    )


if __name__ == "__main__":
    unittest.main()
