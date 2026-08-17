from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from genomi.evidence import envelope as evidence_envelope
from genomi.lab.service import GenomiLabService, LabError
from genomi.lab.store import GenomiLabStore

from tests.genomilab_support import (
    TEST_LAB_KEY_PROVIDER,
    synthetic_ready_agi_context,
)


class _ReadyPatientContext:
    def __call__(
        self, operation: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        del params
        if operation == "genomi.describe_context":
            return synthetic_ready_agi_context(
                "agent-read-security-user", "Agent Read Security Patient"
            )
        if operation == "active_genome_index.revoke_access":
            return {"status": "completed"}
        raise AssertionError(f"unexpected Genomi operation: {operation}")


class GenomiLabAgentReadSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        # These tests exercise session-bound read visibility, not the AGI
        # artifact authority. Keep the path-free synthetic context isolated
        # from the developer machine's live Genomi registry.
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
        self.context = _ReadyPatientContext()
        self.services: list[GenomiLabService] = []
        self.origin = self._service(
            session_id="origin-workspace-session",
            host_id="mcp-origin-agent",
            destination="Origin local agent destination",
        )
        self.addCleanup(self._close_services)

    def _service(
        self, *, session_id: str, host_id: str, destination: str
    ) -> GenomiLabService:
        service = GenomiLabService(
            store=GenomiLabStore(
                self.store_path, key_provider=TEST_LAB_KEY_PROVIDER
            ),
            session_id=session_id,
            operation_call=self.context,
            agent_host_id=host_id,
            agent_processing_destination=destination,
        )
        self.services.append(service)
        return service

    def _close_services(self) -> None:
        for service in reversed(self.services):
            service.close()

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

    def _seed_authorized_history(self) -> tuple[str, str]:
        self.assertEqual(self.origin.bootstrap_workspace()["status"], "ready")
        observation = self.origin.add_profile_observation(
            {
                "modality": "phenotype",
                "label": "Sensitive patient phenotype",
                "original_wording": "Sensitive patient phenotype",
                "assertion_status": "present",
                "verification_state": "user_confirmed",
                "source_class": "patient_reported",
            }
        )
        created = self.origin.create_agent_investigation(
            {
                "question": "Could the sensitive patient phenotype be explained?",
                "disease_scope": "Sensitive disease scope",
            }
        )
        investigation_id = str(created["investigation"]["investigation_id"])
        prepared = self.origin.prepare_agent_authorization(
            investigation_id,
            observation_revision_ids=[
                str(observation["observation_revision_id"])
            ],
        )
        self.assertEqual(
            prepared["candidate"]["purpose"],
            "Could the sensitive patient phenotype be explained?",
        )
        authorized = self.origin.authorize_investigation_context(
            investigation_id, self._approval(prepared["candidate"])
        )
        self.assertEqual(authorized["status"], "awaiting_agent_plan")

        evidence = self.origin.store.commit_evidence(
            investigation_id,
            source_family="literature",
            operation="security.synthetic_evidence",
            evidence={
                "evidence_envelope": evidence_envelope.evidence_present(
                    operation="security.synthetic_evidence"
                ),
                "records": [
                    {
                        "title": "Sensitive evidence history marker",
                        "rsid": "rs900000003",
                    }
                ],
            },
            deduplication_key="agent-read-security-evidence",
        )
        self.origin.store.commit_hypothesis(
            investigation_id,
            kind="evidence_gap",
            statement=(
                "Evidence gap: Independent confirmation for rs900000003 remains "
                "an open requirement."
            ),
            evidence_record_ids=[str(evidence["evidence_record_id"])],
            profile_revision_ids=[
                str(observation["observation_revision_id"])
            ],
            status="open",
        )
        return investigation_id, str(observation["observation_revision_id"])

    def _assert_withheld_handle(
        self, view: dict[str, Any], investigation_id: str
    ) -> None:
        self.assertEqual(
            view,
            {
                "investigation_id": investigation_id,
                "private_context_status": "renewal_required",
                "state_visibility": "withheld_pending_authorization",
            },
        )

    def test_fresh_agent_session_sees_only_handle_until_reauthorized(self) -> None:
        investigation_id, observation_revision_id = (
            self._seed_authorized_history()
        )
        origin_view = self.origin.inspect_agent_investigation(investigation_id)
        self.assertEqual(
            origin_view["investigation"]["state_visibility"],
            "authorized_for_current_agent_session",
        )
        self.assertIn(
            "Sensitive evidence history marker", json.dumps(origin_view)
        )
        origin_handle = self.origin.open_agent_workspace()["workspace"][
            "investigations"
        ][0]
        self.assertEqual(
            origin_handle,
            {
                "investigation_id": investigation_id,
                "private_context_status": "approved_for_session",
                "state_visibility": "authorized_for_current_agent_session",
            },
        )
        self.assertNotIn(
            "Sensitive evidence history marker", json.dumps(origin_handle)
        )

        fresh = self._service(
            session_id="fresh-workspace-session",
            host_id="mcp-fresh-agent",
            destination="Fresh local agent destination",
        )
        opened = fresh.open_agent_workspace()
        self.assertEqual(
            set(opened["workspace"]),
            {
                "workspace_id",
                "active_genome_index",
                "profile_onboarding",
                "investigations",
            },
        )
        self.assertTrue(
            str(opened["workspace"]["workspace_id"]).startswith("workspace-")
        )
        self.assertEqual(
            opened["workspace"]["active_genome_index"],
            {"readiness": "completed"},
        )
        self.assertEqual(
            opened["workspace"]["profile_onboarding"],
            {
                "observation_count": 1,
                "source_artifact_count": 0,
                "specimen_count": 0,
                "assay_count": 0,
            },
        )
        self.assertEqual(len(opened["workspace"]["investigations"]), 1)
        self._assert_withheld_handle(
            opened["workspace"]["investigations"][0], investigation_id
        )

        inspected = fresh.inspect_agent_investigation(investigation_id)
        self._assert_withheld_handle(inspected["investigation"], investigation_id)
        self.assertEqual(inspected["capability_catalog"], {})
        self.assertEqual(
            inspected["next_actions"],
            [
                {
                    "operation": "genomilab.form_specialist_board",
                    "reason": "underlying_agent_should_form_native_specialist_board",
                }
            ],
        )
        serialized = json.dumps({"opened": opened, "inspected": inspected})
        self.assertNotIn("Sensitive patient phenotype", serialized)
        self.assertNotIn("Sensitive evidence history marker", serialized)

        unrelated = self.origin.add_profile_observation(
            {
                "modality": "phenotype",
                "label": "Unrelated later profile fact",
                "original_wording": "Unrelated later profile fact",
                "assertion_status": "present",
                "verification_state": "user_confirmed",
                "source_class": "patient_reported",
            }
        )
        prepared = fresh.prepare_agent_authorization(investigation_id)
        self.assertEqual(
            prepared["candidate"]["observation_revision_ids"],
            [observation_revision_id],
        )
        self.assertNotIn(
            unrelated["observation_revision_id"],
            prepared["candidate"]["observation_revision_ids"],
        )
        self.assertNotIn("refresh", prepared["candidate"])
        fresh.authorize_investigation_context(
            investigation_id, self._approval(prepared["candidate"])
        )
        visible = fresh.inspect_agent_investigation(investigation_id)[
            "investigation"
        ]
        self.assertEqual(
            visible["state_visibility"],
            "authorized_for_current_agent_session",
        )
        self.assertGreaterEqual(len(visible["profile_snapshot_history"]), 1)
        self.assertEqual(len(visible["evidence_records"]), 1)
        self.assertEqual(len(visible["hypotheses"]), 1)
        self.assertIn("Sensitive evidence history marker", json.dumps(visible))

    def test_changed_destination_cannot_reuse_same_session_read_authority(
        self,
    ) -> None:
        investigation_id, _ = self._seed_authorized_history()
        changed_destination = self._service(
            session_id="origin-workspace-session",
            host_id="mcp-different-agent",
            destination="Different local agent destination",
        )

        inspected = changed_destination.inspect_agent_investigation(
            investigation_id
        )

        self._assert_withheld_handle(inspected["investigation"], investigation_id)
        self.assertEqual(inspected["capability_catalog"], {})

    def test_mixed_patient_observation_batch_rolls_back_every_write(self) -> None:
        self.assertEqual(self.origin.bootstrap_workspace()["status"], "ready")
        created = self.origin.create_agent_investigation(
            {"question": "Could new patient information refine the investigation?"}
        )
        investigation_id = str(created["investigation"]["investigation_id"])

        with self.assertRaises(LabError) as raised:
            self.origin.record_agent_patient_observations(
                investigation_id,
                [
                    {
                        "modality": "phenotype",
                        "label": "Transient first observation",
                        "original_wording": "Transient first observation",
                        "assertion_status": "present",
                        "verification_state": "user_confirmed",
                        "source_class": "patient_reported",
                    },
                    {
                        "modality": "invalid_modality",
                        "label": "Invalid second observation",
                        "original_wording": "Invalid second observation",
                        "assertion_status": "present",
                        "verification_state": "user_confirmed",
                        "source_class": "patient_reported",
                    },
                ],
            )

        self.assertEqual(raised.exception.code, "invalid_profile_observation")
        self.assertEqual(self.origin.molecular_profile()["observations"], [])


if __name__ == "__main__":
    unittest.main()
