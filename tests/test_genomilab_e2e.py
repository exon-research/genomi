from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.lab.service import GenomiLabService, LabError
from genomi.lab.store import GenomiLabStore
from genomi.runtime import context as runtime_context


FIXTURE_ROOT = Path(__file__).resolve().parent / "data"
PATIENT_A_VCF = FIXTURE_ROOT / "genomilab_synthetic_patient_a.vcf"
PATIENT_B_VCF = FIXTURE_ROOT / "genomilab_synthetic_patient_b.vcf"


class GenomiLabEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self.genomi_home = Path(self._temporary_home.name) / "genomi-home"
        self.runtime_session_id = "genomilab-e2e-runtime-session"
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(self.genomi_home),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": self.runtime_session_id,
                "GENOMI_MCP_BACKGROUND": "0",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)
        self.store = GenomiLabStore()
        self.services: list[GenomiLabService] = []
        self.service = self._new_service("portal-session-one")
        self.addCleanup(self._close_services)

    def _new_service(self, session_id: str) -> GenomiLabService:
        service = GenomiLabService(store=GenomiLabStore(self.store.path), session_id=session_id)
        self.services.append(service)
        return service

    def _close_services(self) -> None:
        for service in reversed(self.services):
            service.close()

    def _import_fixture(
        self,
        service: GenomiLabService,
        profile_id: str,
        fixture: Path,
    ) -> dict[str, object]:
        data = fixture.read_bytes()
        job = service.start_genome_intake(
            profile_id,
            filename=fixture.name,
            stream=io.BytesIO(data),
            content_length=len(data),
        )
        self.assertEqual(job["status"], "completed")
        profile = service.profile(profile_id)
        self.assertIsNotNone(profile["genome"])
        self.assertFalse(profile["genome_access"]["approved"])
        return profile

    def assert_consent_required(
        self,
        service: GenomiLabService,
        profile_id: str,
        finding_id: str,
    ) -> None:
        with self.assertRaises(LabError) as raised:
            service.run_investigation(
                profile_id,
                {
                    "question": "Is this synthetic reported finding present?",
                    "finding_id": finding_id,
                },
            )
        self.assertEqual(raised.exception.code, "consent_required")
        self.assertEqual(raised.exception.http_status, 403)

    def test_explicit_consent_unlocks_positive_research_brief_not_diagnosis(self) -> None:
        profile = self.service.create_profile("Synthetic patient A")
        profile_id = str(profile["profile_id"])
        health_fact = self.service.add_health_fact(
            profile_id,
            {
                "kind": "condition",
                "label": "Synthetic condition under investigation",
                "assertion_status": "present",
                "onset": "2025",
            },
        )
        finding = self.service.add_reported_finding(
            profile_id,
            {
                "variant": "rs900000001",
                "gene": "SYNTH1",
                "reported_classification": "research finding",
                "source_label": "synthetic report",
            },
        )
        imported = self._import_fixture(self.service, profile_id, PATIENT_A_VCF)
        self.assertEqual(imported["genome_access"]["scope"], "current_portal_session")

        self.assert_consent_required(self.service, profile_id, str(finding["finding_id"]))

        receipt = self.service.approve_genome_access(
            profile_id,
            purpose="Check the synthetic reported finding for this research brief",
        )
        self.assertTrue(receipt["session_only"])
        self.assertEqual(receipt["profile_id"], profile_id)
        self.assertTrue(self.service.profile(profile_id)["genome_access"]["approved"])

        investigation = self.service.run_investigation(
            profile_id,
            {
                "question": "Is the synthetic reported finding present in this profile?",
                "finding_id": finding["finding_id"],
            },
        )

        self.assertEqual(investigation["status"], "completed")
        brief = investigation["brief"]
        self.assertEqual(brief["status"], "research_observation")
        self.assertIn("was observed", brief["observation"])
        self.assertIsNone(brief["mechanism"])
        self.assertIn("not a diagnosis", brief["clinical_boundary"].lower())
        self.assertIn("clinical laboratory", " ".join(brief["confirmation_needed"]).lower())
        self.assertEqual(brief["health_context"][0]["label"], health_fact["label"])

        evidence = brief["evidence"]
        self.assertEqual(evidence["operation"], "variant.resolve")
        self.assertIsInstance(evidence["evidence_envelope"], dict)
        self.assertEqual(evidence["evidence_envelope"]["operation"], "variant.resolve")
        self.assertEqual(evidence["sample_context"]["count"], 1)
        match = evidence["sample_context"]["matches"][0]
        self.assertEqual(match["rsid"], "rs900000001")
        self.assertEqual(match["genotype"], "0/1")
        self.assertNotIn(str(self.genomi_home), json.dumps(investigation))
        self.assertNotIn(str(PATIENT_A_VCF), json.dumps(investigation))

    def test_profiles_remain_isolated_and_switch_or_restart_revokes_consent(self) -> None:
        patient_a = self.service.create_profile("Synthetic patient A")
        patient_b = self.service.create_profile("Synthetic patient B")
        patient_a_id = str(patient_a["profile_id"])
        patient_b_id = str(patient_b["profile_id"])
        finding_a = self.service.add_reported_finding(
            patient_a_id,
            {"variant": "rs900000001", "source_label": "patient A synthetic report"},
        )
        finding_b = self.service.add_reported_finding(
            patient_b_id,
            {"variant": "rs900000002", "source_label": "patient B synthetic report"},
        )
        self.service.add_health_fact(
            patient_a_id,
            {"kind": "condition", "label": "Patient A context"},
        )
        self.service.add_health_fact(
            patient_b_id,
            {"kind": "condition", "label": "Patient B context"},
        )
        profile_a = self._import_fixture(self.service, patient_a_id, PATIENT_A_VCF)
        profile_b = self._import_fixture(self.service, patient_b_id, PATIENT_B_VCF)
        self.assertNotEqual(profile_a["genome"]["agi_id"], profile_b["genome"]["agi_id"])

        stored_a = self.service.profile(patient_a_id)
        stored_b = self.service.profile(patient_b_id)
        self.assertEqual(
            {item["variant"] for item in stored_a["reported_findings"]},
            {"rs900000001"},
        )
        self.assertEqual(
            {item["variant"] for item in stored_b["reported_findings"]},
            {"rs900000002"},
        )
        self.assertEqual(stored_a["health_facts"][0]["label"], "Patient A context")
        self.assertEqual(stored_b["health_facts"][0]["label"], "Patient B context")

        self.service.approve_genome_access(patient_a_id, purpose="Investigate patient A")
        result_a = self.service.run_investigation(
            patient_a_id,
            {"question": "Check patient A", "finding_id": finding_a["finding_id"]},
        )
        matches_a = result_a["brief"]["evidence"]["sample_context"]["matches"]
        self.assertEqual({item["rsid"] for item in matches_a}, {"rs900000001"})

        self.service.activate_profile(patient_b_id)
        self.assertFalse(self.service.profile(patient_a_id)["genome_access"]["approved"])
        self.assert_consent_required(self.service, patient_a_id, str(finding_a["finding_id"]))
        self.assert_consent_required(self.service, patient_b_id, str(finding_b["finding_id"]))

        self.service.approve_genome_access(patient_b_id, purpose="Investigate patient B")
        result_b = self.service.run_investigation(
            patient_b_id,
            {"question": "Check patient B", "finding_id": finding_b["finding_id"]},
        )
        matches_b = result_b["brief"]["evidence"]["sample_context"]["matches"]
        self.assertEqual({item["rsid"] for item in matches_b}, {"rs900000002"})
        self.assertNotIn("rs900000001", json.dumps(result_b["brief"]))
        self.assertFalse(self.service.profile(patient_a_id)["genome_access"]["approved"])

        self.service.close()
        restarted = self._new_service("portal-session-after-restart")
        restarted_profile = restarted.profile(patient_b_id)
        self.assertIsNotNone(restarted_profile["genome"])
        self.assertEqual(
            {item["variant"] for item in restarted_profile["reported_findings"]},
            {"rs900000002"},
        )
        self.assertFalse(restarted_profile["genome_access"]["approved"])
        self.assert_consent_required(restarted, patient_b_id, str(finding_b["finding_id"]))


if __name__ == "__main__":
    unittest.main()
