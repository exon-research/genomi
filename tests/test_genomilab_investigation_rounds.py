from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from genomi.lab.service import GenomiLabService
from genomi.lab.service_errors import LabError
from genomi.lab.store import GenomiLabStore

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
                "investigation-round-user", "Investigation Round Patient"
            )
        if operation == "active_genome_index.revoke_access":
            return {"status": "completed"}
        raise AssertionError(f"unexpected Genomi operation: {operation}")


class GenomiLabInvestigationRoundTests(unittest.TestCase):
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
        self.store = GenomiLabStore(self.store_path, key_provider=TEST_LAB_KEY_PROVIDER)
        self.service = GenomiLabService(
            store=self.store,
            session_id="investigation-round-session",
            operation_call=_ReadyContext(),
        )
        self.addCleanup(self.service.close)
        self.assertEqual(self.service.open_agent_workspace()["status"], "ready")
        self.observation = self.service.add_profile_observation(
            {
                "modality": "condition",
                "label": "Synthetic immune condition",
                "source_class": "patient_reported",
                "verification_state": "user_confirmed",
            }
        )
        created = self.service.create_agent_investigation(
            {
                "question": "Could these synthetic immune findings be connected?",
                "disease_scope": "Synthetic immune condition",
            }
        )
        self.investigation_id = str(created["investigation"]["investigation_id"])
        self.service.form_agent_specialist_board(
            self.investigation_id, specialists=self._specialists()
        )
        prepared = self.service.prepare_agent_authorization(
            self.investigation_id,
            observation_revision_ids=[str(self.observation["observation_revision_id"])],
        )
        self.service.authorize_investigation_context(
            self.investigation_id, self._approval(prepared["candidate"])
        )

    @staticmethod
    def _specialists() -> list[dict[str, str]]:
        return [
            {
                "specialist_id": "specialist-timeline",
                "role": "Timeline specialist",
                "task": "Reconstruct the clinical timeline",
            },
            {
                "specialist_id": "specialist-phenotype",
                "role": "Phenotype specialist",
                "task": "Compare the approved phenotype pattern",
            },
            {
                "specialist_id": "specialist-variant",
                "role": "Variant specialist",
                "task": "Review approved variant evidence",
            },
            {
                "specialist_id": "specialist-literature",
                "role": "Literature specialist",
                "task": "Review public literature",
            },
            {
                "specialist_id": "specialist-skeptic",
                "role": "Evidence skeptic",
                "task": "Review conflicts and alternative explanations",
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

    def _assignments(self, round_number: int) -> list[dict[str, str]]:
        return [
            {
                "specialist_id": item["specialist_id"],
                "task": f"Round {round_number}: {item['task']}",
            }
            for item in self._specialists()
        ]

    def _submit_round(self, round_number: int) -> dict[str, Any]:
        return self.service.submit_agent_plan(
            self.investigation_id,
            focus_question=f"What should round {round_number} resolve?",
            specialist_assignments=self._assignments(round_number),
            requests=[
                {
                    "id": f"project-profile-round-{round_number}",
                    "capability": "investigation.project_profile",
                    "parameters": {},
                }
            ],
        )

    def _report(self, round_id: str, specialist_id: str) -> dict[str, Any]:
        return self.service.record_agent_specialist_report(
            self.investigation_id,
            round_id=round_id,
            specialist_id=specialist_id,
            report={
                "findings": [
                    {
                        "statement": "The approved profile anchors this specialist review.",
                        "stance": "context_only",
                        "evidence_record_ids": [],
                        "profile_revision_ids": [
                            self.observation["observation_revision_id"]
                        ],
                    }
                ],
                "gaps": [
                    {
                        "question": "What additional evidence would resolve this specialist's uncertainty?",
                        "evidence_record_ids": [],
                        "profile_revision_ids": [
                            self.observation["observation_revision_id"]
                        ],
                    }
                ],
            },
        )

    def _complete_round(self, round_id: str) -> None:
        for specialist in self._specialists():
            self._report(round_id, specialist["specialist_id"])

    def test_five_persistent_specialists_are_reused_across_rounds(self) -> None:
        first = self._submit_round(1)
        first_round = first["investigation_round"]
        first_round_id = str(first_round["round_id"])
        self.assertEqual(first_round["round_number"], 1)
        self.assertEqual(first_round["status"], "planned")
        self.assertEqual(first_round["round_number"], first["plan_version"]["version"])
        self.assertEqual(len(first_round["members"]), 5)

        with self.assertRaises(LabError) as raised:
            self._submit_round(2)
        self.assertEqual(raised.exception.code, "specialist_round_incomplete")

        self._complete_round(first_round_id)
        completed_first = self.service.investigation(self.investigation_id)[
            "current_round"
        ]
        self.assertEqual(completed_first["status"], "completed")
        self.assertEqual(completed_first["report_count"], 5)

        second = self._submit_round(2)
        second_round = second["investigation_round"]
        second_round_id = str(second_round["round_id"])
        self.assertEqual(second_round["round_number"], 2)
        self.assertEqual(second_round["prior_round_id"], first_round_id)
        self.assertEqual(
            {item["specialist_id"] for item in first_round["members"]},
            {item["specialist_id"] for item in second_round["members"]},
        )
        self.assertTrue(
            all(
                str(item["task"]).startswith("Round 2:")
                for item in second_round["members"]
            )
        )

        with self.assertRaises(LabError) as raised:
            self.service.report_agent_specialist_progress(
                self.investigation_id,
                round_id=first_round_id,
                specialist_id="specialist-timeline",
                status="working",
                current_work="Trying to reopen the prior round",
            )
        self.assertEqual(raised.exception.code, "specialist_round_conflict")

        progress = self.service.report_agent_specialist_progress(
            self.investigation_id,
            round_id=second_round_id,
            specialist_id="specialist-timeline",
            status="working",
            current_work="Reviewing the second-round timeline",
        )
        self.assertEqual(progress["investigation_round"]["status"], "in_progress")

        self._complete_round(second_round_id)
        investigation = self.service.investigation(self.investigation_id)
        self.assertEqual(len(investigation["rounds"]), 2)
        self.assertEqual(investigation["current_round"]["status"], "completed")

    def test_specialist_reports_are_anchored_idempotent_and_immutable(self) -> None:
        started = self._submit_round(1)
        round_id = str(started["investigation_round"]["round_id"])
        first = self._report(round_id, "specialist-timeline")
        retried = self._report(round_id, "specialist-timeline")
        self.assertFalse(first["retry_reused"])
        self.assertTrue(retried["retry_reused"])
        self.assertEqual(
            first["specialist_report"]["report_id"],
            retried["specialist_report"]["report_id"],
        )

        with self.assertRaises(LabError) as raised:
            self.service.record_agent_specialist_report(
                self.investigation_id,
                round_id=round_id,
                specialist_id="specialist-phenotype",
                report={
                    "findings": [
                        {
                            "statement": "This cites evidence outside the round.",
                            "stance": "supports",
                            "evidence_record_ids": ["evidence-not-in-round"],
                            "profile_revision_ids": [],
                        }
                    ],
                    "gaps": [],
                },
            )
        self.assertEqual(raised.exception.code, "invalid_specialist_report")

        report_id = str(first["specialist_report"]["report_id"])
        with self.store._connect() as connection:
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "specialist round reports are immutable"
            ):
                connection.execute(
                    "UPDATE specialist_round_reports SET report_json = '{}' "
                    "WHERE report_id = ?",
                    (report_id,),
                )
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "investigation rounds are immutable"
            ):
                connection.execute(
                    "UPDATE investigation_rounds SET focus_question = 'changed' "
                    "WHERE round_id = ?",
                    (round_id,),
                )

    def test_specialist_report_and_monitoring_event_commit_atomically(self) -> None:
        started = self._submit_round(1)
        round_id = str(started["investigation_round"]["round_id"])
        with self.store._connect() as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_specialist_report_event
                BEFORE INSERT ON investigation_events
                WHEN NEW.event_type = 'specialist_report_recorded'
                BEGIN
                    SELECT RAISE(ABORT, 'synthetic specialist report event failure');
                END
                """
            )

        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "synthetic specialist report event failure"
        ):
            self._report(round_id, "specialist-timeline")

        current_round = self.store.get_investigation(self.investigation_id)[
            "current_round"
        ]
        self.assertEqual(current_round["report_count"], 0)
        self.assertNotIn(
            "specialist_report_recorded",
            {
                event["event_type"]
                for event in self.store.replay_investigation_events(
                    self.investigation_id
                )
            },
        )

    def test_round_details_are_withheld_before_new_session_authorization(self) -> None:
        started = self._submit_round(1)
        round_id = str(started["investigation_round"]["round_id"])
        self._complete_round(round_id)
        fresh = GenomiLabService(
            store=GenomiLabStore(self.store_path, key_provider=TEST_LAB_KEY_PROVIDER),
            session_id="investigation-round-fresh-session",
            operation_call=_ReadyContext(),
        )
        self.addCleanup(fresh.close)
        self.assertEqual(fresh.open_agent_workspace()["status"], "ready")

        inspected = fresh.inspect_agent_investigation(self.investigation_id)

        investigation = inspected["investigation"]
        self.assertEqual(
            investigation["state_visibility"], "withheld_pending_authorization"
        )
        self.assertNotIn("rounds", investigation)
        self.assertNotIn("current_round", investigation)
        self.assertEqual(investigation["specialist_board"]["member_count"], 5)
        serialized = json.dumps(inspected)
        self.assertNotIn("What should round 1 resolve?", serialized)
        self.assertNotIn("The approved profile anchors", serialized)


if __name__ == "__main__":
    unittest.main()
