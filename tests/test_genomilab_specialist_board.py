from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from genomi.interfaces.mcp import handle_request
from genomi.interfaces.presentation import present_result
from genomi.lab.investigation_rounds import specialist_report_submission_input_schema
from genomi.lab.service import GenomiLabService
from genomi.lab.service_errors import LabError
from genomi.lab.specialist_board import project_specialist_board
from genomi.lab.store import GenomiLabStore
from genomi.operations import TOOL_CATALOG_OPERATIONS, all_operations

from tests.genomilab_support import (
    TEST_LAB_KEY_PROVIDER,
    synthetic_ready_agi_context,
)


class _ReadyContext:
    def __call__(
        self, operation: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        del params
        if operation == "genomi.describe_context":
            return synthetic_ready_agi_context(
                "specialist-board-user", "Specialist Board Patient"
            )
        if operation == "active_genome_index.revoke_access":
            return {"status": "completed"}
        raise AssertionError(f"unexpected Genomi operation: {operation}")


class GenomiLabSpecialistBoardTests(unittest.TestCase):
    def setUp(self) -> None:
        for target, kwargs in (
            (
                "genomi.lab.profile_context_application."
                "issue_investigation_agi_authorization",
                {"return_value": object()},
            ),
            (
                "genomi.lab.profile_context_application."
                "revoke_investigation_agi_authorization",
                {},
            ),
            (
                "genomi.lab.profile_context_application."
                "revoke_investigation_agi_authorizations_for_investigation",
                {},
            ),
            ("genomi.lab.service.revoke_investigation_agi_authorization", {}),
            (
                "genomi.lab.service."
                "revoke_investigation_agi_authorizations_for_session",
                {},
            ),
        ):
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store_path = Path(temporary.name) / "genomilab.sqlite3"
        self.store = GenomiLabStore(
            self.store_path, key_provider=TEST_LAB_KEY_PROVIDER
        )
        self.service = self._new_service("specialist-board-origin-session")
        self.assertEqual(self.service.open_agent_workspace()["status"], "ready")
        self.observation = self.service.add_profile_observation(
            {
                "modality": "condition",
                "label": "Synthetic board condition",
                "source_class": "patient_reported",
                "verification_state": "user_confirmed",
            }
        )

    def _new_service(self, session_id: str) -> GenomiLabService:
        service = GenomiLabService(
            store=(
                self.store
                if not hasattr(self, "service")
                else GenomiLabStore(
                    self.store_path, key_provider=TEST_LAB_KEY_PROVIDER
                )
            ),
            session_id=session_id,
            operation_call=_ReadyContext(),
            agent_host_id=f"host-{session_id}",
            agent_processing_destination=f"Current host {session_id}",
        )
        self.addCleanup(service.close)
        return service

    def _create(self) -> tuple[str, dict[str, Any]]:
        created = self.service.create_agent_investigation(
            {
                "question": "Which public evidence should be investigated?",
                "disease_scope": "Synthetic board condition",
            }
        )
        return str(created["investigation"]["investigation_id"]), created

    @staticmethod
    def _specialists() -> list[dict[str, str]]:
        return [
            {
                "specialist_id": "specialist-public-evidence",
                "role": "Public evidence specialist",
                "task": "Review relevant public evidence",
            },
            {
                "specialist_id": "specialist-counterevidence",
                "role": "Counterevidence specialist",
                "task": "Review limitations and conflicting evidence",
            },
        ]

    @staticmethod
    def _approval(candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in candidate.items()
            if key
            not in {
                "status",
                "requires_explicit_approval",
                "user_id",
                "investigation_id",
            }
        } | {"approved": True}

    def _form(self, investigation_id: str) -> dict[str, Any]:
        return self.service.form_agent_specialist_board(
            investigation_id, specialists=self._specialists()
        )

    def _authorize(self, investigation_id: str) -> None:
        prepared = self.service.prepare_agent_authorization(
            investigation_id,
            observation_revision_ids=[
                str(self.observation["observation_revision_id"])
            ],
        )
        authorized = self.service.authorize_investigation_context(
            investigation_id, self._approval(prepared["candidate"])
        )
        self.assertEqual(authorized["status"], "awaiting_agent_plan")

    def _start_round(
        self, investigation_id: str, *, request_id: str = "project-profile"
    ) -> str:
        accepted = self.service.submit_agent_plan(
            investigation_id,
            focus_question="What does the approved profile establish for this round?",
            specialist_assignments=[
                {
                    "specialist_id": item["specialist_id"],
                    "task": item["task"],
                }
                for item in self._specialists()
            ],
            requests=[
                {
                    "id": request_id,
                    "capability": "investigation.project_profile",
                    "parameters": {},
                }
            ],
        )
        return str(accepted["investigation_round"]["round_id"])

    def _report(self, investigation_id: str, round_id: str, specialist_id: str):
        return self.service.record_agent_specialist_report(
            investigation_id,
            round_id=round_id,
            specialist_id=specialist_id,
            report={
                "findings": [
                    {
                        "statement": "The approved profile is available for this research round.",
                        "stance": "context_only",
                        "evidence_record_ids": [],
                        "profile_revision_ids": [
                            self.observation["observation_revision_id"]
                        ],
                    }
                ],
                "gaps": [],
            },
        )

    def test_creation_and_plan_enforce_board_first_ordering(self) -> None:
        investigation_id, created = self._create()

        self.assertEqual(
            created["next_action"]["operation"],
            "genomilab.form_specialist_board",
        )
        self.assertEqual(
            self.service.inspect_agent_investigation(investigation_id)[
                "next_actions"
            ][0]["operation"],
            "genomilab.form_specialist_board",
        )
        with self.assertRaises(LabError) as raised:
            self.service.submit_agent_plan(
                investigation_id,
                focus_question="What should this round investigate?",
                specialist_assignments=[
                    {
                        "specialist_id": item["specialist_id"],
                        "task": item["task"],
                    }
                    for item in self._specialists()
                ],
                requests=[
                    {
                        "id": "project-profile",
                        "capability": "investigation.project_profile",
                        "parameters": {},
                    }
                ],
            )
        self.assertEqual(raised.exception.code, "specialist_board_required")

    def test_formation_is_bounded_idempotent_and_event_derived(self) -> None:
        investigation_id, _ = self._create()

        formed = self._form(investigation_id)
        retried = self._form(investigation_id)
        changed = self._specialists()
        changed[0] = {**changed[0], "task": "Use a different assignment"}
        mismatched_retry = self.service.form_agent_specialist_board(
            investigation_id, specialists=changed
        )

        self.assertFalse(formed["retry_reused"])
        self.assertTrue(retried["retry_reused"])
        self.assertTrue(mismatched_retry["retry_reused"])
        self.assertEqual(
            retried["specialist_board"],
            {
                "status": "formed",
                "member_count": 2,
                "chair": {
                    "role": "main_agent",
                    "responsibility": (
                        "patient_interaction_and_active_genome_index_context_owner"
                    ),
                },
            },
        )
        self.assertEqual(
            mismatched_retry["specialist_board"], retried["specialist_board"]
        )
        board = formed["specialist_board"]
        self.assertEqual(board["status"], "formed")
        self.assertEqual(
            board["chair"],
            {
                "role": "main_agent",
                "responsibility": (
                    "patient_interaction_and_active_genome_index_context_owner"
                ),
            },
        )
        self.assertEqual(
            {member["status"] for member in board["members"]}, {"assigned"}
        )
        self.assertTrue(
            all(member["current_work"] is None for member in board["members"])
        )
        investigation = self.store.get_investigation(investigation_id)
        self.assertEqual(investigation["specialist_board"], board)
        board_events = [
            event
            for event in investigation["investigation_events"]
            if event["event_type"] == "specialist_board_formed"
        ]
        self.assertEqual(len(board_events), 1)

        self._authorize(investigation_id)
        authorized_retry = self._form(investigation_id)
        self.assertEqual(authorized_retry["specialist_board"], board)
        self.assertEqual(
            authorized_retry["next_action"]["operation"],
            "genomilab.submit_plan",
        )
        with self.assertRaises(LabError) as raised:
            self.service.form_agent_specialist_board(
                investigation_id, specialists=changed
            )
        self.assertEqual(
            raised.exception.code, "specialist_board_already_formed"
        )

        for invalid in (
            self._specialists()[:1],
            self._specialists()
            + [
                {
                    "specialist_id": f"specialist-extra-{index}",
                    "role": "Additional specialist",
                    "task": "Review another public evidence domain",
                }
                for index in range(4)
            ],
        ):
            other_id, _ = self._create()
            with self.subTest(member_count=len(invalid)):
                with self.assertRaises(LabError) as raised:
                    self.service.form_agent_specialist_board(
                        other_id, specialists=invalid
                    )
                self.assertEqual(raised.exception.code, "invalid_specialist_board")

        authorized_first_id, _ = self._create()
        self._authorize(authorized_first_id)
        authorized_first = self._form(authorized_first_id)
        self.assertEqual(
            authorized_first["next_action"]["operation"],
            "genomilab.submit_plan",
        )

    def test_board_gate_covers_all_post_plan_execution_paths(self) -> None:
        investigation_id, _ = self._create()
        self._authorize(investigation_id)
        plan = self.service._compile_agent_plan(
            requests=[
                {
                    "id": "project-profile",
                    "capability": "investigation.project_profile",
                    "parameters": {},
                }
            ]
        )
        self.service.validate_agent_capability_plan(investigation_id, plan)
        self.store.commit_plan(investigation_id, plan)
        investigation = self.store.get_investigation(investigation_id)
        current = investigation["current_plan_version"]
        self.store.accept_plan(
            investigation_id,
            plan_version_id=current["plan_version_id"],
            user_id=investigation["user_id"],
            workspace_session_id=self.service.session_id,
            plan_sha256=current["plan_sha256"],
            approved=True,
        )

        calls = (
            lambda: self.service.execute_agent_request(
                investigation_id, "project-profile"
            ),
            lambda: self.service.check_agent_request(
                investigation_id, "project-profile"
            ),
            lambda: self.service.submit_agent_brief(investigation_id, {}),
            lambda: self.service.approve_and_continue_capability(
                investigation_id, {"request_id": "project-profile"}
            ),
            lambda: self.service.check_capability_request(
                investigation_id, {"request_id": "project-profile"}
            ),
        )
        for call in calls:
            with self.subTest(call=call):
                with self.assertRaises(LabError) as raised:
                    call()
                self.assertEqual(
                    raised.exception.code, "specialist_board_required"
                )

    def test_progress_requires_board_and_current_authorized_session(self) -> None:
        without_board_id, _ = self._create()
        with self.assertRaises(LabError) as raised:
            self.service.report_agent_specialist_progress(
                without_board_id,
                round_id="round-missing",
                specialist_id="specialist-public-evidence",
                status="working",
                current_work="Reviewing public evidence",
            )
        self.assertEqual(raised.exception.code, "specialist_board_required")

        investigation_id, _ = self._create()
        self._form(investigation_id)
        with self.assertRaises(LabError) as raised:
            self.service.report_agent_specialist_progress(
                investigation_id,
                round_id="round-missing",
                specialist_id="specialist-public-evidence",
                status="working",
                current_work="Reviewing public evidence",
            )
        self.assertEqual(raised.exception.code, "investigation_authorization_required")

        self._authorize(investigation_id)
        fresh = self._new_service("specialist-board-fresh-session")
        with self.assertRaises(LabError) as raised:
            fresh.report_agent_specialist_progress(
                investigation_id,
                round_id="round-missing",
                specialist_id="specialist-public-evidence",
                status="working",
                current_work="Reviewing public evidence",
            )
        self.assertEqual(raised.exception.code, "investigation_authorization_required")

    def test_progress_projection_is_idempotent_and_completed_is_terminal(self) -> None:
        investigation_id, _ = self._create()
        self._form(investigation_id)
        self._authorize(investigation_id)
        round_id = self._start_round(investigation_id)

        first = self.service.report_agent_specialist_progress(
            investigation_id,
            round_id=round_id,
            specialist_id="specialist-public-evidence",
            status="working",
            current_work="Reviewing public evidence",
        )
        retried = self.service.report_agent_specialist_progress(
            investigation_id,
            round_id=round_id,
            specialist_id="specialist-public-evidence",
            status="working",
            current_work="Reviewing public evidence",
        )
        self.assertEqual(first["specialist_board"]["status"], "in_progress")
        self.assertFalse(first["retry_reused"])
        self.assertTrue(retried["retry_reused"])

        self.service.report_agent_specialist_progress(
            investigation_id,
            round_id=round_id,
            specialist_id="specialist-counterevidence",
            status="blocked",
            current_work="Waiting for a public source response",
        )
        blocked = self.service.report_agent_specialist_progress(
            investigation_id,
            round_id=round_id,
            specialist_id="specialist-public-evidence",
            status="completed",
            current_work="Public evidence review completed",
        )
        self.assertEqual(blocked["specialist_board"]["status"], "blocked")
        completed = self.service.report_agent_specialist_progress(
            investigation_id,
            round_id=round_id,
            specialist_id="specialist-counterevidence",
            status="completed",
            current_work="Counterevidence review completed",
        )
        self.assertEqual(completed["specialist_board"]["status"], "in_progress")
        self._report(
            investigation_id, round_id, "specialist-public-evidence"
        )
        reported = self._report(
            investigation_id, round_id, "specialist-counterevidence"
        )
        self.assertEqual(reported["specialist_board"]["status"], "completed")
        with self.assertRaises(LabError) as raised:
            self.service.report_agent_specialist_progress(
                investigation_id,
                round_id=round_id,
                specialist_id="specialist-public-evidence",
                status="working",
                current_work="Attempting to reopen completed work",
            )
        self.assertEqual(raised.exception.code, "specialist_progress_conflict")

        events = self.store.replay_investigation_events(investigation_id)
        progress_events = [
            event
            for event in events
            if event["event_type"] == "specialist_progress_reported"
        ]
        self.assertEqual(len(progress_events), 4)
        self.assertEqual(
            [event["sequence"] for event in events],
            list(range(1, len(events) + 1)),
        )

    def test_projection_keeps_completed_members_terminal(self) -> None:
        specialists = self._specialists()
        events = [
            {
                "event_type": "specialist_board_formed",
                "payload": {"members": specialists},
            },
            {
                "event_type": "specialist_progress_reported",
                "payload": {
                    "specialist_id": "specialist-public-evidence",
                    "status": "completed",
                    "current_work": "Public evidence review completed",
                },
            },
            {
                "event_type": "specialist_progress_reported",
                "payload": {
                    "specialist_id": "specialist-counterevidence",
                    "status": "completed",
                    "current_work": "Counterevidence review completed",
                },
            },
            {
                "event_type": "specialist_progress_reported",
                "payload": {
                    "specialist_id": "specialist-public-evidence",
                    "status": "working",
                    "current_work": "Malformed history tried to reopen work",
                },
            },
        ]

        board = project_specialist_board(events)

        assert board is not None
        self.assertEqual(board["status"], "completed")
        member = next(
            item
            for item in board["members"]
            if item["specialist_id"] == "specialist-public-evidence"
        )
        self.assertEqual(
            member,
            {
                "specialist_id": "specialist-public-evidence",
                "role": "Public evidence specialist",
                "task": "Review relevant public evidence",
                "status": "completed",
                "current_work": "Public evidence review completed",
            },
        )

    def test_board_event_failure_leaves_no_projection(self) -> None:
        investigation_id, _ = self._create()
        with self.store._connect() as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_specialist_board_event
                BEFORE INSERT ON investigation_events
                WHEN NEW.event_type = 'specialist_board_formed'
                BEGIN
                    SELECT RAISE(ABORT, 'synthetic board event failure');
                END
                """
            )

        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "synthetic board event failure"
        ):
            self._form(investigation_id)

        investigation = self.store.get_investigation(investigation_id)
        self.assertIsNone(investigation["specialist_board"])
        self.assertFalse(
            any(
                event["event_type"] == "specialist_board_formed"
                for event in investigation["investigation_events"]
            )
        )

    def test_progress_event_failure_preserves_prior_projection(self) -> None:
        investigation_id, _ = self._create()
        self._form(investigation_id)
        self._authorize(investigation_id)
        round_id = self._start_round(investigation_id)
        working = self.service.report_agent_specialist_progress(
            investigation_id,
            round_id=round_id,
            specialist_id="specialist-public-evidence",
            status="working",
            current_work="Reviewing public evidence",
        )["specialist_board"]
        with self.store._connect() as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_specialist_progress_event
                BEFORE INSERT ON investigation_events
                WHEN NEW.event_type = 'specialist_progress_reported'
                BEGIN
                    SELECT RAISE(ABORT, 'synthetic progress event failure');
                END
                """
            )

        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "synthetic progress event failure"
        ):
            self.service.report_agent_specialist_progress(
                investigation_id,
                round_id=round_id,
                specialist_id="specialist-public-evidence",
                status="blocked",
                current_work="Waiting for another public source",
            )

        self.assertEqual(
            self.store.get_investigation(investigation_id)["specialist_board"],
            working,
        )

    def test_mcp_catalog_and_pre_authorization_presentation_expose_safe_board(
        self,
    ) -> None:
        by_name = {tool["name"]: tool for tool in all_operations()}
        self.assertEqual(
            by_name["genomilab.form_specialist_board"]["inputSchema"][
                "properties"
            ]["specialists"]["minItems"],
            2,
        )
        self.assertEqual(
            by_name["genomilab.form_specialist_board"]["inputSchema"][
                "properties"
            ]["specialists"]["maxItems"],
            5,
        )
        self.assertIn("genomilab.record_specialist_report", by_name)
        expected_report_schema = specialist_report_submission_input_schema()
        self.assertEqual(
            by_name["genomilab.record_specialist_report"]["inputSchema"],
            expected_report_schema,
        )
        self.assertEqual(
            TOOL_CATALOG_OPERATIONS["genomilab.record_specialist_report"][
                "input_schema"
            ],
            expected_report_schema,
        )
        report_schema = expected_report_schema["properties"]["report"]
        self.assertEqual(len(report_schema["anyOf"]), 2)
        finding_schema = report_schema["properties"]["findings"]["items"]
        self.assertEqual(len(finding_schema["anyOf"]), 2)
        self.assertIn(
            "round_id",
            by_name["genomilab.report_specialist_progress"]["inputSchema"][
                "required"
            ],
        )
        self.assertEqual(
            by_name["genomilab.report_specialist_progress"]["inputSchema"][
                "properties"
            ]["status"]["enum"],
            ["working", "blocked", "completed"],
        )

        investigation_id, _ = self._create()
        private_specialists = [
            {
                "specialist_id": "specialist-private-sentinel-a",
                "role": "Private role sentinel A",
                "task": "Private task sentinel A",
            },
            {
                "specialist_id": "specialist-private-sentinel-b",
                "role": "Private role sentinel B",
                "task": "Private task sentinel B",
            },
        ]
        runtime = mock.Mock()
        runtime.service = self.service
        with mock.patch(
            "genomi.operations.registry.handlers_genomilab.current_agent_runtime",
            return_value=runtime,
        ):
            response = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "genomilab.form_specialist_board",
                        "arguments": {
                            "investigation_id": investigation_id,
                            "specialists": private_specialists,
                        },
                    },
                },
                transport="stdio",
            )
        assert response is not None
        self.assertIsNot(response["result"].get("isError"), True, response)
        formed = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(formed["specialist_board"]["status"], "formed")

        fresh = self._new_service("specialist-board-presentation-fresh")
        inspected = fresh.inspect_agent_investigation(investigation_id)
        presented = present_result("genomilab.inspect_investigation", inspected)
        self.assertEqual(
            presented["investigation"]["specialist_board"],
            {
                "status": "formed",
                "member_count": 2,
                "chair": {
                    "role": "main_agent",
                    "responsibility": (
                        "patient_interaction_and_active_genome_index_context_owner"
                    ),
                },
            },
        )
        self.assertEqual(
            presented["next_actions"][0]["operation"],
            "genomilab.prepare_authorization",
        )
        opened = present_result(
            "genomilab.open_workspace", fresh.open_agent_workspace()
        )
        workspace_board = next(
            item["specialist_board"]
            for item in opened["workspace"]["investigations"]
            if item["investigation_id"] == investigation_id
        )
        self.assertEqual(
            workspace_board,
            presented["investigation"]["specialist_board"],
        )
        serialized = json.dumps({"inspected": presented, "opened": opened})
        for private_value in (
            "specialist-private-sentinel-a",
            "Private role sentinel A",
            "Private task sentinel A",
            "specialist-private-sentinel-b",
            "Private role sentinel B",
            "Private task sentinel B",
        ):
            self.assertNotIn(private_value, serialized)

        matched = fresh.form_agent_specialist_board(
            investigation_id, specialists=private_specialists
        )
        changed = [dict(item) for item in private_specialists]
        changed[0]["task"] = "A mismatched private task guess"
        mismatched = fresh.form_agent_specialist_board(
            investigation_id, specialists=changed
        )
        self.assertEqual(matched, mismatched)

        prepared = fresh.prepare_agent_authorization(
            investigation_id,
            observation_revision_ids=[
                str(self.observation["observation_revision_id"])
            ],
        )
        fresh.authorize_investigation_context(
            investigation_id, self._approval(prepared["candidate"])
        )
        authorized = present_result(
            "genomilab.inspect_investigation",
            fresh.inspect_agent_investigation(investigation_id),
        )
        self.assertEqual(
            authorized["investigation"]["specialist_board"],
            formed["specialist_board"],
        )


if __name__ == "__main__":
    unittest.main()
