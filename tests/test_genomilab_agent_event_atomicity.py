from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from genomi.evidence import envelope as evidence_envelope
from genomi.interfaces.mcp import handle_request
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
                "atomic-event-user", "Atomic Event Patient"
            )
        if operation == "active_genome_index.revoke_access":
            return {"status": "completed"}
        raise AssertionError(f"unexpected Genomi operation: {operation}")


class GenomiLabAgentEventAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        for target, kwargs in (
            (
                "genomi.lab.profile_context_application.issue_investigation_agi_authorization",
                {"return_value": object()},
            ),
            (
                "genomi.lab.profile_context_application.revoke_investigation_agi_authorization",
                {},
            ),
            (
                "genomi.lab.profile_context_application.revoke_investigation_agi_authorizations_for_investigation",
                {},
            ),
            ("genomi.lab.service.revoke_investigation_agi_authorization", {}),
            (
                "genomi.lab.service.revoke_investigation_agi_authorizations_for_session",
                {},
            ),
        ):
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = GenomiLabStore(
            Path(temporary.name) / "genomilab.sqlite3",
            key_provider=TEST_LAB_KEY_PROVIDER,
        )
        self.service = GenomiLabService(
            store=self.store,
            session_id="atomic-event-session",
            operation_call=_ReadyContext(),
            agent_host_id="atomic-event-host",
            agent_processing_destination="Current atomic-event test host",
        )
        self.addCleanup(self.service.close)
        self.assertEqual(self.service.open_agent_workspace()["status"], "ready")
        self.observation = self.service.add_profile_observation(
            {
                "modality": "reported_germline_finding",
                "label": "Synthetic report states rs900000777",
                "original_wording": "Synthetic report states rs900000777",
                "reported_variant": "rs900000777",
                "assertion_status": "present",
                "verification_state": "user_confirmed",
                "source_class": "patient_reported",
            }
        )

    def _reject_event(self, event_type: str) -> None:
        self._allow_events()
        with self.store._connect() as connection:
            connection.execute(
                f"""
                CREATE TRIGGER reject_investigation_event
                BEFORE INSERT ON investigation_events
                WHEN NEW.event_type = '{event_type}'
                BEGIN
                    SELECT RAISE(ABORT, 'synthetic investigation event failure');
                END
                """
            )

    def _allow_events(self) -> None:
        with self.store._connect() as connection:
            connection.execute("DROP TRIGGER IF EXISTS reject_investigation_event")

    def _create_investigation(self) -> str:
        created = self.service.create_agent_investigation(
            {
                "question": "What could explain the synthetic reported symptom?",
                "disease_scope": "Synthetic condition",
            }
        )
        investigation_id = str(created["investigation"]["investigation_id"])
        self.service.form_agent_specialist_board(
            investigation_id,
            specialists=[
                {
                    "specialist_id": "specialist-public-evidence",
                    "role": "Public evidence specialist",
                    "task": "Review public evidence sources",
                },
                {
                    "specialist_id": "specialist-counterevidence",
                    "role": "Counterevidence specialist",
                    "task": "Review limitations and conflicting evidence",
                },
            ],
        )
        return investigation_id

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

    def _accept_profile_plan(self, investigation_id: str) -> None:
        accepted = self.service.submit_agent_plan(
            investigation_id,
            focus_question="What does the approved profile establish?",
            specialist_assignments=[
                {
                    "specialist_id": "specialist-public-evidence",
                    "task": "Review public evidence sources",
                },
                {
                    "specialist_id": "specialist-counterevidence",
                    "task": "Review limitations and conflicting evidence",
                },
            ],
            requests=[
                {
                    "id": "project-profile",
                    "capability": "investigation.project_profile",
                    "parameters": {},
                }
            ],
        )
        self.assertEqual(accepted["status"], "accepted")
        self._complete_round(
            investigation_id, str(accepted["investigation_round"]["round_id"])
        )

    def _complete_round(self, investigation_id: str, round_id: str) -> None:
        report = {
            "findings": [
                {
                    "statement": "The approved profile anchors this synthetic test round.",
                    "stance": "context_only",
                    "evidence_record_ids": [],
                    "profile_revision_ids": [
                        self.observation["observation_revision_id"]
                    ],
                }
            ],
            "gaps": [],
        }
        for specialist_id in (
            "specialist-public-evidence",
            "specialist-counterevidence",
        ):
            self.service.record_agent_specialist_report(
                investigation_id,
                round_id=round_id,
                specialist_id=specialist_id,
                report=report,
            )

    def _brief_wire(self, investigation_id: str) -> dict[str, object]:
        authoring = self.service.inspect_agent_investigation(investigation_id)[
            "brief_authoring"
        ]
        properties = authoring["brief_schema"]["properties"]
        confirmation = properties["confirmation_needs"]
        case_term = str(self.observation["reported_variant"])
        observation_statement = (
            f"Patient observation: The profile records {case_term} as a "
            "research observation."
        )
        return {
            "title": authoring["brief_title_fallback"],
            "summary": observation_statement,
            "clinical_stage": properties["clinical_stage"]["enum"][0],
            "timeline": [],
            "claims": [
                {
                    "statement": observation_statement,
                    "claim_role": "observation",
                    "evidence_record_ids": [],
                    "profile_revision_ids": [
                        self.observation["observation_revision_id"]
                    ],
                }
            ],
            "hypothesis_ids": [],
            "gap_ids": [],
            "confirmation_needs": (
                [confirmation["items"]["enum"][0]]
                if confirmation.get("minItems")
                else []
            ),
            "clinician_questions": [],
            "clinical_boundary": properties["clinical_boundary"]["enum"][0],
            "change_summary": (
                f"Prepared a traceable {case_term} research brief."
            ),
        }

    def _mcp_call(
        self, operation: str, arguments: dict[str, object]
    ) -> dict[str, Any]:
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
                    "params": {"name": operation, "arguments": arguments},
                },
                transport="stdio",
            )
        assert response is not None
        self.assertIsNot(response["result"].get("isError"), True, response)
        return json.loads(response["result"]["content"][0]["text"])

    def test_context_authorization_retry_reuses_one_domain_event(self) -> None:
        investigation_id = self._create_investigation()
        prepared = self.service.prepare_agent_authorization(
            investigation_id,
            observation_revision_ids=[
                str(self.observation["observation_revision_id"])
            ],
        )
        approval = self._approval(prepared["candidate"])

        accepted = self.service.authorize_investigation_context(
            investigation_id, approval
        )
        retried = self.service.authorize_investigation_context(
            investigation_id, approval
        )

        self.assertFalse(accepted["retry_reused"])
        self.assertTrue(retried["retry_reused"])
        events = self.store.get_investigation(investigation_id)[
            "investigation_events"
        ]
        authorized = [
            event for event in events if event["event_type"] == "context_authorized"
        ]
        self.assertEqual(len(authorized), 1)
        self.assertFalse(authorized[0]["payload"]["retry_reused"])

    def test_tampered_agent_authorization_candidate_cannot_commit_context(
        self,
    ) -> None:
        investigation_id = self._create_investigation()
        prepared = self.service.prepare_agent_authorization(
            investigation_id,
            observation_revision_ids=[
                str(self.observation["observation_revision_id"])
            ],
        )
        approval = self._approval(prepared["candidate"])
        approval["purpose"] = "Tampered after patient review"

        with self.assertRaises(LabError) as raised:
            self.service.authorize_investigation_context(
                investigation_id, approval
            )

        self.assertEqual(
            raised.exception.code, "invalid_investigation_authorization"
        )
        investigation = self.store.get_investigation(investigation_id)
        self.assertIsNone(investigation["patient_molecular_snapshot_id"])
        self.assertEqual(
            self.store.workspace_activity("atomic-event-user")[
                "investigation_authorizations"
            ],
            [],
        )

    def test_service_brief_retry_reuses_version_and_changed_brief_versions(
        self,
    ) -> None:
        investigation_id = self._create_investigation()
        self._authorize(investigation_id)
        self._accept_profile_plan(investigation_id)
        wire = self._brief_wire(investigation_id)

        first = self.service.submit_agent_brief(investigation_id, wire)
        retried = self.service.submit_agent_brief(investigation_id, wire)
        changed_wire = {
            **wire,
            "clinician_questions": [
                {
                    "question": (
                        "What clinical evidence is needed to interpret "
                        f"{self.observation['reported_variant']}?"
                    ),
                    "evidence_record_ids": [],
                    "profile_revision_ids": [
                        self.observation["observation_revision_id"]
                    ],
                    "hypothesis_ids": [],
                    "gap_ids": [],
                }
            ],
        }
        changed = self.service.submit_agent_brief(
            investigation_id, changed_wire
        )

        self.assertFalse(first["retry_reused"])
        self.assertTrue(retried["retry_reused"])
        self.assertEqual(
            retried["brief_version"]["brief_version_id"],
            first["brief_version"]["brief_version_id"],
        )
        self.assertFalse(changed["retry_reused"])
        self.assertEqual(changed["brief_version"]["version"], 2)
        self.assertEqual(
            changed["brief_version"]["prior_brief_version_id"],
            first["brief_version"]["brief_version_id"],
        )
        replanned = self.service.submit_agent_plan(
            investigation_id,
            focus_question="What changed after the first brief?",
            specialist_assignments=[
                {
                    "specialist_id": "specialist-public-evidence",
                    "task": "Review public evidence after the first brief",
                },
                {
                    "specialist_id": "specialist-counterevidence",
                    "task": "Review limitations after the first brief",
                },
            ],
            requests=[
                {
                    "id": "project-profile-after-brief",
                    "capability": "investigation.project_profile",
                    "parameters": {},
                }
            ],
        )
        self.assertFalse(replanned["retry_reused"])
        self._complete_round(
            investigation_id,
            str(replanned["investigation_round"]["round_id"]),
        )
        same_brief_new_plan = self.service.submit_agent_brief(
            investigation_id, changed_wire
        )
        self.assertFalse(same_brief_new_plan["retry_reused"])
        self.assertEqual(same_brief_new_plan["brief_version"]["version"], 3)
        investigation = self.store.get_investigation(investigation_id)
        self.assertEqual(len(investigation["brief_versions"]), 3)
        self.assertEqual(
            sum(
                event["event_type"] == "brief_published"
                for event in investigation["investigation_events"]
            ),
            3,
        )

    def test_unsafe_agent_brief_is_rejected_without_version_or_event(self) -> None:
        investigation_id = self._create_investigation()
        self._authorize(investigation_id)
        self._accept_profile_plan(investigation_id)
        unsafe = {
            **self._brief_wire(investigation_id),
            "summary": "This finding is diagnostic.",
        }

        with self.assertRaises(LabError) as raised:
            self.service.submit_agent_brief(investigation_id, unsafe)

        self.assertEqual(raised.exception.code, "invalid_investigation_brief")
        investigation = self.store.get_investigation(investigation_id)
        self.assertEqual(investigation["brief_versions"], [])
        self.assertNotIn(
            "brief_published",
            {
                event["event_type"]
                for event in investigation["investigation_events"]
            },
        )

    def test_mcp_brief_retry_returns_same_published_version(self) -> None:
        investigation_id = self._create_investigation()
        self._authorize(investigation_id)
        self._accept_profile_plan(investigation_id)
        wire = self._brief_wire(investigation_id)

        first = self._mcp_call(
            "genomilab.submit_brief",
            {"investigation_id": investigation_id, "brief": wire},
        )
        retried = self._mcp_call(
            "genomilab.submit_brief",
            {"investigation_id": investigation_id, "brief": wire},
        )

        self.assertFalse(first["retry_reused"])
        self.assertTrue(retried["retry_reused"])
        self.assertEqual(
            retried["brief_version"]["brief_version_id"],
            first["brief_version"]["brief_version_id"],
        )
        investigation = self.store.get_investigation(investigation_id)
        self.assertEqual(len(investigation["brief_versions"]), 1)
        self.assertEqual(
            sum(
                event["event_type"] == "brief_published"
                for event in investigation["investigation_events"]
            ),
            1,
        )

    def test_agent_lifecycle_mutations_roll_back_when_their_event_fails(self) -> None:
        self._reject_event("investigation_created")
        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "synthetic investigation event failure"
        ):
            self._create_investigation()
        self.assertEqual(self.service.list_investigations(), [])

        self._allow_events()
        investigation_id = self._create_investigation()
        self._reject_event("context_approval_required")
        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "synthetic investigation event failure"
        ):
            self.service.prepare_agent_authorization(investigation_id)
        rolled_back = self.store.get_investigation(investigation_id)
        self.assertEqual(rolled_back["status"], "awaiting_plan")
        self.assertNotIn(
            "context_approval_required",
            {item["event_type"] for item in rolled_back["investigation_events"]},
        )

        self._allow_events()
        prepared = self.service.prepare_agent_authorization(investigation_id)
        approval = self._approval(prepared["candidate"])
        self._reject_event("context_authorized")
        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "synthetic investigation event failure"
        ):
            self.service.authorize_investigation_context(
                investigation_id, approval
            )
        rolled_back = self.store.get_investigation(investigation_id)
        self.assertIsNone(rolled_back["patient_molecular_snapshot_id"])
        self.assertEqual(
            self.store.workspace_activity("atomic-event-user")[
                "investigation_authorizations"
            ],
            [],
        )

        self._allow_events()
        self.assertEqual(
            self.service.authorize_investigation_context(
                investigation_id, approval
            )["status"],
            "awaiting_agent_plan",
        )
        self._reject_event("plan_accepted")
        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "synthetic investigation event failure"
        ):
            self._accept_profile_plan(investigation_id)
        rolled_back = self.store.get_investigation(investigation_id)
        self.assertIsNone(rolled_back["current_plan_version"])
        self.assertEqual(rolled_back["status"], "awaiting_plan")

        self._allow_events()
        self._accept_profile_plan(investigation_id)
        self._reject_event("brief_published")
        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "synthetic investigation event failure"
        ):
            self.service.submit_agent_brief(
                investigation_id, self._brief_wire(investigation_id)
            )
        rolled_back = self.store.get_investigation(investigation_id)
        self.assertEqual(rolled_back["brief_versions"], [])
        self.assertEqual(rolled_back["status"], "running")

    def test_patient_information_and_revocation_share_their_event_transaction(
        self,
    ) -> None:
        investigation_id = self._create_investigation()
        self._authorize(investigation_id)
        self._accept_profile_plan(investigation_id)
        before_revision_ids = {
            item["observation_revision_id"]
            for item in self.service.molecular_profile()["observations"]
        }

        self._reject_event("patient_information_recorded")
        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "synthetic investigation event failure"
        ):
            self.service.record_agent_patient_observations(
                investigation_id,
                [
                    {
                        "modality": "phenotype",
                        "label": "Synthetic added symptom",
                        "original_wording": "Synthetic added symptom",
                        "assertion_status": "present",
                        "verification_state": "user_confirmed",
                        "source_class": "patient_reported",
                    }
                ],
            )
        self.assertEqual(
            {
                item["observation_revision_id"]
                for item in self.service.molecular_profile()["observations"]
            },
            before_revision_ids,
        )

        self._allow_events()
        before = self.store.get_investigation(investigation_id)
        consent_id = str(before["active_consent_receipt_id"])
        authorization = self.store.current_investigation_authorization(
            workspace_session_id=self.service.session_id,
            user_id="atomic-event-user",
            investigation_id=investigation_id,
        )
        self._reject_event("private_context_revoked")
        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "synthetic investigation event failure"
        ):
            self.service.revoke_agent_context(investigation_id)
        self.assertIsNone(self.store.consent_receipt(consent_id)["revoked_at"])
        current_authorization = self.store.current_investigation_authorization(
            workspace_session_id=self.service.session_id,
            user_id="atomic-event-user",
            investigation_id=investigation_id,
        )
        self.assertEqual(
            current_authorization["authorization_receipt_id"],
            authorization["authorization_receipt_id"],
        )
        self.assertEqual(
            self.store.get_investigation(investigation_id)["status"], "running"
        )

    def test_capability_and_evidence_writes_never_outpace_monitoring_events(
        self,
    ) -> None:
        investigation_id = self._create_investigation()
        self._authorize(investigation_id)
        self._accept_profile_plan(investigation_id)
        plan_id = str(
            self.store.get_investigation(investigation_id)["current_plan_version"][
                "plan_version_id"
            ]
        )

        self._reject_event("request_started")
        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "synthetic investigation event failure"
        ):
            self.service.execute_agent_request(investigation_id, "project-profile")
        self.assertIsNone(
            self.store.get_capability_execution(
                investigation_id, plan_id, "project-profile"
            )
        )

        self._reject_event("request_state_changed")
        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "synthetic investigation event failure"
        ):
            self.service.execute_agent_request(investigation_id, "project-profile")
        execution = self.store.get_capability_execution(
            investigation_id, plan_id, "project-profile"
        )
        self.assertEqual(execution["status"], "in_progress")
        event_types = [
            event["event_type"]
            for event in self.store.replay_investigation_events(investigation_id)
        ]
        self.assertIn("request_started", event_types)
        self.assertNotIn("request_state_changed", event_types)

        self._reject_event("evidence_committed")
        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "synthetic investigation event failure"
        ):
            self.store.commit_evidence(
                investigation_id,
                source_family="literature",
                operation="atomic.synthetic_evidence",
                evidence={
                    "evidence_envelope": evidence_envelope.evidence_present(
                        operation="atomic.synthetic_evidence"
                    )
                },
                deduplication_key="atomic-event-evidence",
                emit_investigation_event=True,
            )
        self.assertEqual(
            self.store.get_investigation(investigation_id)["evidence_records"], []
        )

        self._reject_event("external_disclosure_approved")
        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "synthetic investigation event failure"
        ):
            self.store.create_outbound_disclosure_receipt(
                "atomic-event-user",
                workspace_session_id=self.service.session_id,
                investigation_id=investigation_id,
                recipient_kind="evidence_provider",
                recipient_id="paperclip",
                purpose="Synthetic evidence lookup",
                destination="paperclip_managed_https_api",
                data_categories=["public_biomedical_query"],
                payload={"query": "synthetic public term"},
                policy_versions={"test": "atomic"},
                approved=True,
                emit_investigation_event=True,
            )
        self.assertEqual(
            self.store.workspace_activity("atomic-event-user")[
                "outbound_disclosures"
            ],
            [],
        )


if __name__ == "__main__":
    unittest.main()
