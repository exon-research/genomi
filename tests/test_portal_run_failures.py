from __future__ import annotations

import unittest
from pathlib import Path

from genomi.interfaces import portal_run_events, portal_run_failures, portal_store
from tests.support.runtime.genomi import IsolatedGenomiHomeTestCase

_CODEX_USAGE_LIMIT_ERROR = (
    'Host-agent stream failed: {"message": "You\'ve hit your usage limit. Visit '
    "https://example.invalid/settings/usage to purchase more credits or try again at "
    'Aug 20th, 2026 8:18 AM.", "codexErrorInfo": "usageLimitExceeded", "additionalDetails": null}'
)


class RunFailureClassificationTests(unittest.TestCase):
    def test_usage_limit_payload_becomes_an_actionable_sentence(self) -> None:
        failure = portal_run_failures.classify_run_failure(_CODEX_USAGE_LIMIT_ERROR)

        self.assertEqual(failure.reason, "assistant_usage_limit_reached")
        self.assertEqual(
            failure.headline,
            "Your assistant ran out of usage allowance, so this turn stopped before any research was done.",
        )
        self.assertEqual(
            failure.detail,
            "You've hit your usage limit. Visit https://example.invalid/settings/usage to purchase more "
            "credits or try again at Aug 20th, 2026 8:18 AM.",
        )
        self.assertEqual(
            failure.next_steps,
            (
                "Wait until your assistant's allowance resets, then ask again.",
                "Switch to another local assistant under Workspace details → Local assistant, then ask again.",
                "Your question and attached records stay in this conversation, so nothing needs to be re-entered.",
            ),
        )
        text = failure.message_text()
        self.assertTrue(text.startswith(failure.headline))
        self.assertIn("What you can do:", text)
        self.assertEqual(_machinery_tokens(text), [])

    def test_missing_assistant_and_generic_crash_stay_readable(self) -> None:
        unavailable = portal_run_failures.classify_run_failure("Unsupported or unavailable agent: codex")
        started = portal_run_failures.classify_run_failure("Assistant run could not be started: thread unavailable")
        generic = portal_run_failures.classify_run_failure(
            "Host-agent stream failed: RuntimeError('broken pipe')\nTraceback (most recent call last):"
        )
        canceled = portal_run_failures.classify_run_failure("Run canceled.", status="canceled")

        self.assertEqual(unavailable.reason, "assistant_unavailable")
        self.assertEqual(started.reason, "assistant_unavailable")
        self.assertEqual(unavailable.headline, "Genomi could not start a local assistant for this turn.")
        self.assertEqual(generic.reason, "assistant_stopped_unexpectedly")
        self.assertEqual(generic.headline, "The assistant stopped before it could answer this question.")
        self.assertEqual(generic.detail, "")
        self.assertEqual(canceled.reason, "run_stopped_by_you")
        for failure in (unavailable, started, generic, canceled):
            self.assertTrue(failure.next_steps)
            self.assertEqual(_machinery_tokens(failure.message_text()), [])


class FailedConversationOutcomeTests(IsolatedGenomiHomeTestCase):
    def test_failed_turn_leaves_an_actionable_answer_in_the_conversation(self) -> None:
        project = portal_store.create_project(name="Failed turn")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Could my Crohn's and infections be connected?",
            agent_id="codex",
        )
        assert frame is not None
        portal_store.attach_run(frame["id"], run_id="run_1", agent_id="codex")

        finished = portal_store.finish_frame(
            frame["id"],
            status="failed",
            output="",
            error=_CODEX_USAGE_LIMIT_ERROR,
            run_id="run_1",
        )

        assert finished is not None
        self.assertEqual(finished["status"], "failed")
        self.assertEqual(
            finished["output_data"]["error"],
            "Your assistant ran out of usage allowance, so this turn stopped before any research was done.",
        )
        messages = portal_store.list_frame_messages(frame["id"])["messages"]
        assistant = [message for message in messages if message.get("role") == "assistant"]
        self.assertEqual(len(assistant), 1)
        self.assertEqual(assistant[0]["stream_status"], "failed")
        self.assertEqual(assistant[0]["run_id"], "run_1")
        self.assertIn("ran out of usage allowance", assistant[0]["text"])
        self.assertIn("What you can do:", assistant[0]["text"])
        self.assertEqual(_machinery_tokens(assistant[0]["text"]), [])

    def test_a_failed_turn_that_already_answered_keeps_the_assistant_answer(self) -> None:
        project = portal_store.create_project(name="Partial answer")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Review rs429358",
            agent_id="codex",
        )
        assert frame is not None
        portal_store.attach_run(frame["id"], run_id="run_2", agent_id="codex")

        portal_store.finish_frame(
            frame["id"],
            status="failed",
            output="APOE rs429358 is a public variant record.",
            error=_CODEX_USAGE_LIMIT_ERROR,
            run_id="run_2",
        )

        messages = portal_store.list_frame_messages(frame["id"])["messages"]
        assistant = [message for message in messages if message.get("role") == "assistant"]
        self.assertEqual(len(assistant), 1)
        self.assertEqual(assistant[0]["text"], "APOE rs429358 is a public variant record.")


class RunEndEventTests(unittest.TestCase):
    def test_terminal_run_stream_reports_the_reader_facing_failure(self) -> None:
        run = portal_run_events.create_run(kind="project_request", message="Review my records", agent_id="codex")
        self.addCleanup(portal_run_events.discard_run, run.id)

        run.finish("failed", error=_CODEX_USAGE_LIMIT_ERROR)

        end = run.events[-1]
        self.assertEqual(end.event, "end")
        self.assertEqual(end.data["status"], "failed")
        self.assertIn("ran out of usage allowance", end.data["error"])
        self.assertIn("What you can do:", end.data["error"])
        self.assertEqual(_machinery_tokens(str(end.data["error"])), [])
        self.assertEqual(run.error, _CODEX_USAGE_LIMIT_ERROR)

    def test_successful_run_stream_reports_no_failure_text(self) -> None:
        run = portal_run_events.create_run(kind="project_request", message="Review my records", agent_id="codex")
        self.addCleanup(portal_run_events.discard_run, run.id)

        run.finish("succeeded")

        end = run.events[-1]
        self.assertEqual(end.data, {"status": "succeeded", "error": None})


class FailedRunRenderingTests(unittest.TestCase):
    def test_conversation_renders_the_run_failure_as_assistant_text(self) -> None:
        portal = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "if (data.status !== 'succeeded' && data.error) messageSurface.appendText(body, answerBreak(body) + data.error);",
            portal,
        )
        self.assertIn("function answerBreak(body) {", portal)


def _machinery_tokens(text: str) -> list[str]:
    return [token for token in ("{", "}", "codexErrorInfo", "Traceback", "RuntimeError") if token in text]
