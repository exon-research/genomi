from __future__ import annotations

import json
from unittest import mock

from genomi.interfaces import (
    portal_conversation_reviews,
    portal_run_events,
    portal_run_service,
    portal_runs,
    portal_store,
)

from tests.support.runtime.genomi import GenomiRuntimeTestCase


class PortalConversationReviewTests(GenomiRuntimeTestCase):
    def test_review_prompt_is_bounded_and_names_message_sources(self) -> None:
        messages = [
            {"id": "msg_user", "role": "user", "text": "Which gene contains rs429358?"},
            {
                "id": "msg_tool",
                "role": "tool",
                "event": {"type": "tool_result", "name": "variant.resolve", "content": "APOE public evidence"},
            },
            {"id": "msg_answer", "role": "assistant", "text": "rs429358 is in APOE."},
        ]

        source = portal_conversation_reviews.source_messages(messages)
        prompt = portal_conversation_reviews.review_prompt(source)

        self.assertEqual([item["role"] for item in source], ["user", "work_step", "assistant"])
        self.assertIn("[message_id=msg_answer] ASSISTANT", prompt)
        self.assertIn("factual consistency", prompt)
        self.assertIn("Return exactly one JSON object", prompt)
        self.assertNotIn("/Users/", prompt)

    def test_completed_review_normalizes_findings_and_rejects_unknown_message_refs(self) -> None:
        review = portal_conversation_reviews.completed_review(
            review_run_id="review_1",
            output=json.dumps(
                {
                    "state": "clear",
                    "summary": "One claim needs qualification.",
                    "findings": [
                        {
                            "verdict": "warning",
                            "claim": "The answer implies clinical certainty.",
                            "evidence": "The transcript contains only public variant evidence.",
                            "recommendation": "State the evidence boundary.",
                            "source_message_id": "msg_answer",
                        },
                        {
                            "verdict": "pass",
                            "claim": "Unknown message reference is ignored.",
                            "source_message_id": "msg_private",
                        },
                    ],
                }
            ),
            source_message_ids=["msg_answer"],
            started_at="2026-07-10T00:00:00+00:00",
            completed_at="2026-07-10T00:00:01+00:00",
        )
        public = portal_conversation_reviews.public_review(review)

        assert public is not None
        self.assertEqual(public["state"], "findings")
        self.assertEqual(public["check_count"], 2)
        self.assertEqual(public["findings"][0]["source_ref"]["message_id"], "msg_answer")
        self.assertNotIn("source_ref", public["findings"][1])
        self.assertNotIn("source_message_ids", public)

    def test_unreadable_reviewer_output_is_inconclusive(self) -> None:
        review = portal_conversation_reviews.completed_review(
            review_run_id="review_1",
            output="not structured output",
            source_message_ids=[],
            started_at="start",
            completed_at="end",
        )

        self.assertEqual(review["state"], "inconclusive")
        self.assertEqual(review["summary"], "Reviewer returned an unreadable result.")
        self.assertEqual(review["findings"], [])

    def test_frame_review_lifecycle_does_not_add_a_fake_conversation_turn(self) -> None:
        project = portal_store.create_project(name="Reviewer lifecycle")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Which gene contains rs429358?",
            agent_id="codex",
        )
        assert frame is not None
        portal_store.finish_frame(str(frame["id"]), status="completed", output="rs429358 is in APOE.")
        before = portal_store.list_frame_messages(str(frame["id"]))

        with mock.patch("genomi.interfaces.portal_run_service._start_run_thread", lambda run: None):
            response = portal_run_service.start_frame_review(
                frame_id=str(frame["id"]),
                project_id=str(project["project_id"]),
                agent_id="codex",
            )

        assert response is not None
        self.addCleanup(portal_run_events.discard_run, response["runId"])
        run = portal_run_events.get_run(response["runId"])
        assert run is not None
        self.assertEqual(run.kind, "conversation_review")
        self.assertEqual(response["review"]["state"], "verifying")
        self.assertEqual(portal_store.list_frame_messages(str(frame["id"]))["total"], before["total"])

        presentation = portal_runs.ConversationReviewRunPresentation(run)
        presentation.handle_agent_event(
            {
                "type": "text_delta",
                "delta": json.dumps(
                    {
                        "state": "clear",
                        "summary": "The reviewed answer matches the supplied evidence.",
                        "findings": [],
                    }
                ),
            }
        )
        presentation.complete_success()

        after = portal_store.list_frame_messages(str(frame["id"]))
        self.assertEqual(after["total"], before["total"])
        self.assertEqual(after["reviews"][-1]["status"], "completed")
        self.assertEqual(after["reviews"][-1]["state"], "clear")
        self.assertEqual(after["reviews"][-1]["summary"], "The reviewed answer matches the supplied evidence.")

    def test_review_requires_a_completed_assistant_answer(self) -> None:
        project = portal_store.create_project(name="No answer")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Review rs429358",
            agent_id="codex",
        )
        assert frame is not None

        result = portal_run_service.start_frame_review(
            frame_id=str(frame["id"]),
            project_id=str(project["project_id"]),
            agent_id="codex",
        )

        self.assertEqual(result, {"status": "no_answer"})

    def test_stale_review_is_terminalized_after_restart(self) -> None:
        project = portal_store.create_project(name="Interrupted review")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Review rs429358",
            agent_id="codex",
        )
        assert frame is not None
        portal_store.finish_frame(str(frame["id"]), status="completed", output="rs429358 is in APOE.")
        source = portal_store.frame_review_source_messages(str(frame["id"]))
        pending = portal_store.begin_frame_review(
            str(frame["id"]),
            project_id=str(project["project_id"]),
            review_run_id="review_stale",
            source_message_ids=[item["message_id"] for item in source],
        )
        assert pending is not None

        changed = portal_store.reconcile_stale_conversation_reviews(known_run_ids=set())
        status = portal_store.persisted_run_status("review_stale")
        reviews = portal_store.list_frame_messages(str(frame["id"]))["reviews"]

        self.assertEqual(changed, [{"frame_id": frame["id"], "review_run_id": "review_stale"}])
        self.assertEqual(status["kind"], "conversation_review")
        self.assertEqual(status["status"], "failed")
        self.assertTrue(status["terminal"])
        self.assertEqual(reviews[-1]["state"], "inconclusive")
        self.assertIn("server restart", reviews[-1]["error"])
