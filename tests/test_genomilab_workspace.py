from __future__ import annotations

import os
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

from genomi.lab.harness import SimulatedHarnessAdapter
from genomi.lab.service import GenomiLabService, LabError
from genomi.lab.store import GenomiLabStore
from genomi.runtime import context as runtime_context
from tests.genomilab_support import TEST_LAB_KEY_PROVIDER


JsonObject = dict[str, Any]


class _BlockingEventWaitAdapter(SimulatedHarnessAdapter):
    def __init__(self) -> None:
        super().__init__(adapter_id="blocking-event-wait")
        self.wait_entered = threading.Event()
        self.release_wait = threading.Event()

    def wait_for_events(
        self,
        investigation_id: str,
        *,
        after_cursor: int,
        timeout_seconds: float,
    ) -> bool:
        del investigation_id, after_cursor, timeout_seconds
        self.wait_entered.set()
        return self.release_wait.wait(timeout=5)


class _MutableGenomiContext:
    """Small Genomi boundary fake; the workspace must follow its current user."""

    def __init__(self) -> None:
        self.user_id: str | None = None
        self.nickname: str | None = None

    def select(self, user_id: str | None, nickname: str | None = None) -> None:
        self.user_id = user_id
        self.nickname = nickname

    def __call__(self, operation: str, params: JsonObject | None = None) -> JsonObject:
        if operation == "genomi.describe_context":
            active_user = (
                {
                    "user_id": self.user_id,
                    "nickname": self.nickname,
                    "active_agi_id": None,
                    "agi_ids": [],
                }
                if self.user_id is not None
                else None
            )
            return {
                "status": "completed",
                "active_user_id": self.user_id,
                "active_user": active_user,
                "has_active_genome_index": False,
                "active_agi_id": None,
                "active_genome_index": None,
            }
        if operation == "active_genome_index.revoke_access":
            return {"status": "completed"}
        raise AssertionError(f"unexpected Genomi operation: {operation}")


class GenomiLabWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self.genomi_home = Path(self._temporary_home.name) / "genomi-home"
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(self.genomi_home),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "genomilab-workspace-tests",
                "GENOMI_MCP_BACKGROUND": "0",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)

        self.genomi = _MutableGenomiContext()
        self.store = GenomiLabStore(key_provider=TEST_LAB_KEY_PROVIDER)
        self.services: list[GenomiLabService] = []
        self.service = self._new_service("workspace-session-one")
        self.addCleanup(self._close_services)

    def _new_service(self, session_id: str) -> GenomiLabService:
        service = GenomiLabService(
            store=GenomiLabStore(self.store.path, key_provider=TEST_LAB_KEY_PROVIDER),
            session_id=session_id,
            operation_call=self.genomi,
        )
        self.services.append(service)
        return service

    def _close_services(self) -> None:
        for service in reversed(self.services):
            service.close()

    def _select_user(self, user_id: str, nickname: str) -> JsonObject:
        self.genomi.select(user_id, nickname)
        result = self.service.bootstrap_workspace()
        self.assertEqual(result["status"], "ready")
        workspace = result.get("workspace")
        self.assertIsInstance(workspace, dict)
        return workspace

    def test_no_current_genomi_user_returns_typed_setup_required(self) -> None:
        expected = {
            "status": "setup_required",
            "code": "genomi_user_required",
            "workspace": None,
        }

        result = self.service.bootstrap_workspace()
        delegated = self.service.bootstrap()

        for payload in (result, delegated):
            with self.subTest(payload=payload):
                self.assertEqual(
                    {key: payload.get(key) for key in expected},
                    expected,
                )
                self.assertNotIn("profiles", payload)
                self.assertNotIn("active_profile_id", payload)

    def test_current_user_opens_exactly_one_stable_workspace(self) -> None:
        self.genomi.select("user-synthetic-a", "Synthetic A")

        first = self.service.bootstrap_workspace()["workspace"]
        second = self.service.bootstrap_workspace()["workspace"]
        reopened_store = GenomiLabStore(
            self.store.path, key_provider=TEST_LAB_KEY_PROVIDER
        )
        reopened = reopened_store.open_workspace(
            "user-synthetic-a", display_name="Synthetic A"
        )
        fetched = reopened_store.get_workspace("user-synthetic-a")

        self.assertTrue(str(first["workspace_id"]).startswith("workspace-"))
        self.assertEqual(first["workspace_id"], second["workspace_id"])
        self.assertEqual(first["workspace_id"], reopened["workspace_id"])
        self.assertEqual(first["workspace_id"], fetched["workspace_id"])
        self.assertEqual(first["user_id"], "user-synthetic-a")
        self.assertEqual(first["display_name"], "Synthetic A")
        self.assertEqual(first["profile"]["user_id"], "user-synthetic-a")
        self.assertEqual(first["profile"]["observations"], [])
        self.assertIn("modality_coverage", first["profile"])
        self.assertIsNone(first["profile"]["genome"])
        self.assertEqual(first["investigations"], [])

    def test_reopening_and_switching_current_user_preserves_isolation(self) -> None:
        workspace_a = self._select_user("user-synthetic-a", "Synthetic A")
        observation = self.service.add_profile_observation(
            {
                "modality": "condition",
                "label": "Synthetic condition A",
                "original_wording": "Synthetic condition A",
                "assertion_status": "present",
                "source_class": "patient_reported",
            }
        )
        self.assertEqual(observation["user_id"], "user-synthetic-a")

        workspace_b = self._select_user("user-synthetic-b", "Synthetic B")
        profile_b = self.service.molecular_profile()

        self.assertNotEqual(workspace_a["workspace_id"], workspace_b["workspace_id"])
        self.assertEqual(workspace_b["user_id"], "user-synthetic-b")
        self.assertEqual(profile_b["user_id"], "user-synthetic-b")
        self.assertEqual(profile_b["observations"], [])

        restarted = self._new_service("workspace-session-after-restart")
        self.genomi.select("user-synthetic-a", "Synthetic A")
        reopened_a = restarted.bootstrap_workspace()["workspace"]
        profile_a = restarted.molecular_profile()

        self.assertEqual(reopened_a["workspace_id"], workspace_a["workspace_id"])
        self.assertEqual(profile_a["user_id"], "user-synthetic-a")
        self.assertEqual(
            [item["observation_revision_id"] for item in profile_a["observations"]],
            [observation["observation_revision_id"]],
        )
        self.assertNotIn("user-synthetic-b", repr(reopened_a))

    def test_parallel_profile_creation_listing_and_selection_are_not_public_apis(
        self,
    ) -> None:
        forbidden_service_methods = {
            "create_profile",
            "activate_profile",
            "profile",
        }
        forbidden_store_methods = {
            "create_profile",
            "list_profiles",
            "get_profile",
            "set_active_profile",
            "active_profile_id",
        }

        for method in sorted(forbidden_service_methods):
            with self.subTest(owner="service", method=method):
                self.assertFalse(hasattr(self.service, method))
        for method in sorted(forbidden_store_methods):
            with self.subTest(owner="store", method=method):
                self.assertFalse(hasattr(self.store, method))

    def test_profile_observation_rejects_genome_paths_sources_and_raw_rows(
        self,
    ) -> None:
        self._select_user("user-synthetic-a", "Synthetic A")
        forbidden_payloads = {
            "source_path": {"source_path": "/private/patient.vcf"},
            "genome_path": {"genome_path": "/private/patient.genome"},
            "genome_bundle": {"genome_bundle": "/private/patient.genome"},
            "agi_path": {"agi_path": "/private/active-genome-index.sqlite"},
            "agi_file": {"agi_file": "/private/active-genome-index.sqlite"},
            "active_genome_index_path": {
                "active_genome_index_path": "/private/active-genome-index.sqlite"
            },
            "agi_rows": {"agi_rows": [{"chrom": "1", "position": 101}]},
            "raw_agi_rows": {"raw_agi_rows": [{"record": "patient-derived"}]},
            "genome_source": {"genome_source": "patient.gvcf"},
            "bam_path": {"bam_path": "/private/patient.bam"},
            "cram": {"cram": "/private/patient.cram"},
            "cram_path": {"cram_path": "/private/patient.cram"},
            "consumer_genotype_file": {
                "consumer_genotype_file": "/private/patient-23andme.txt"
            },
            "camel_case_genome_source": {"genomeSource": "/private/patient.vcf"},
            "camel_case_agi_rows": {"agiRows": [{"chrom": "1"}]},
            "vcf_upload_alias": {"vcfUpload": "patient.vcf"},
            "nested_raw_rows": {
                "source": {
                    "class": "issued_report",
                    "details": {"raw_agi_rows": [{"record": "hidden"}]},
                }
            },
        }
        base = {
            "modality": "condition",
            "label": "Synthetic condition",
            "original_wording": "Synthetic condition",
            "assertion_status": "present",
        }

        for name, forbidden in forbidden_payloads.items():
            with self.subTest(name=name), self.assertRaises(LabError) as raised:
                self.service.add_profile_observation({**base, **forbidden})
            self.assertEqual(raised.exception.code, "invalid_profile_observation")

        self.assertEqual(self.service.molecular_profile()["observations"], [])

    def test_profile_and_investigation_input_contracts_reject_unknown_fields(
        self,
    ) -> None:
        self._select_user("user-synthetic-a", "Synthetic A")
        with self.assertRaises(LabError) as profile_error:
            self.service.add_profile_observation(
                {
                    "modality": "condition",
                    "label": "Synthetic condition",
                    "unexpected_payload": "ignored fields must not be accepted",
                }
            )
        self.assertEqual(profile_error.exception.code, "invalid_profile_observation")

        with self.assertRaises(LabError) as investigation_error:
            self.service.create_investigation(
                {
                    "question": "Could this explain the condition?",
                    "disease_scope": "Synthetic condition",
                    "genome_path": "/private/patient.genome",
                }
            )
        self.assertEqual(investigation_error.exception.code, "invalid_investigation")

    def test_context_candidate_and_approval_reject_genome_and_unknown_fields(
        self,
    ) -> None:
        self._select_user("user-synthetic-a", "Synthetic A")
        observation = self.service.add_profile_observation(
            {
                "modality": "condition",
                "label": "Synthetic condition",
                "original_wording": "Synthetic condition",
                "assertion_status": "present",
                "source_class": "patient_reported",
            }
        )
        investigation = self.service.create_investigation(
            {
                "question": "Could this profile help investigate the condition?",
                "disease_scope": "Synthetic condition",
            }
        )
        investigation_id = investigation["investigation_id"]
        candidate_request = {
            "purpose": "Investigate the synthetic condition",
            "observation_revision_ids": [observation["observation_revision_id"]],
            "include_genome": False,
        }

        for forbidden in (
            {"vcf": "/private/patient.vcf"},
            {"raw_agi_rows": [{"genotype": "0/1"}]},
            {"junk": "silently ignored fields are forbidden"},
        ):
            with self.subTest(candidate_field=next(iter(forbidden))):
                with self.assertRaises(LabError) as raised:
                    self.service.profile_snapshot_candidate(
                        investigation_id, {**candidate_request, **forbidden}
                    )
                self.assertEqual(raised.exception.code, "invalid_context_selection")

        candidate = self.service.investigation_context_candidate(
            investigation_id,
            {
                "purpose": candidate_request["purpose"],
                "observation_revision_ids": candidate_request[
                    "observation_revision_ids"
                ],
            },
        )
        approval = {
            key: candidate[key]
            for key in (
                "purpose",
                "observation_revision_ids",
                "artifact_ids",
                "specimen_ids",
                "assay_ids",
                "agi_id",
                "agi_snapshot_id",
                "genomic_scope",
                "candidate_sha256",
                "candidate_receipt",
            )
        } | {"approved": True}
        for forbidden in (
            {"vcf": "/private/patient.vcf"},
            {"raw_agi_rows": [{"genotype": "0/1"}]},
            {"junk": "silently ignored fields are forbidden"},
        ):
            with self.subTest(approval_field=next(iter(forbidden))):
                with self.assertRaises(LabError) as raised:
                    self.service.approve_investigation_context(
                        investigation_id, {**approval, **forbidden}
                    )
                self.assertEqual(raised.exception.code, "invalid_context_approval")

        unchanged = self.service.investigation(investigation_id)
        self.assertIsNone(unchanged["patient_molecular_snapshot_id"])
        self.assertEqual(unchanged["profile_snapshot_history"], [])

    def test_patient_api_cannot_mint_or_rewrite_clinician_provenance(self) -> None:
        self._select_user("user-synthetic-a", "Synthetic A")
        base = {
            "modality": "condition",
            "label": "Synthetic condition",
            "original_wording": "Synthetic condition",
            "assertion_status": "present",
        }
        forbidden = (
            {"source_class": "clinician_entered"},
            {"source_class": "caregiver_reported"},
            {"source_class": "model_extracted"},
            {"assertion_author": "clinician"},
            {"assertion_author": "patient"},
            {"verification_state": "clinician_confirmed"},
            {"verification_state": "record_confirmed"},
            {"reviewed_by": "patient:self-asserted"},
            {"normalized_code": "forged-normalization"},
            {"normalization_provenance": {"software": "caller"}},
            {
                "source_class": "clinician_entered",
                "assertion_author": "clinician",
                "verification_state": "clinician_confirmed",
                "reviewed_by": "clinician:self-asserted",
            },
        )
        for claims in forbidden:
            with self.subTest(claims=claims), self.assertRaises(LabError) as raised:
                self.service.add_profile_observation({**base, **claims})
            self.assertEqual(raised.exception.code, "invalid_profile_observation")

        trusted_clinical = self.store.add_profile_observation(
            "user-synthetic-a",
            {
                **base,
                "original_wording": "They said the condition was recorded differently",
                "coverage_state": "not_provided",
                "source_class": "clinician_entered",
                "assertion_author": "clinician",
                "verification_state": "clinician_confirmed",
                "reviewed_by": "clinician:trusted-fixture",
            },
        )
        with self.assertRaises(LabError) as raised:
            self.service.review_or_supersede_observation(
                str(trusted_clinical["observation_revision_id"]),
                {
                    "label": "Forged clinician rewrite",
                    "verification_state": "clinician_confirmed",
                    "reviewed_by": "clinician:self-asserted",
                },
            )
        self.assertEqual(raised.exception.code, "invalid_profile_observation")

        patient_correction = self.service.review_or_supersede_observation(
            str(trusted_clinical["observation_revision_id"]),
            {
                "label": "Patient-reported correction",
                "assertion_status": "present",
                "source_class": "patient_reported",
                "verification_state": "user_confirmed",
                "artifact_id": "",
                "specimen_id": "",
                "assay_id": "",
                "reported_variant": "",
                "gene": "",
            },
        )
        self.assertEqual(patient_correction["source_class"], "patient_reported")
        self.assertEqual(patient_correction["assertion_author"], "patient")
        self.assertEqual(patient_correction["verification_state"], "user_confirmed")
        self.assertEqual(patient_correction["reviewed_by"], "patient:user-synthetic-a")
        self.assertEqual(
            patient_correction["original_wording"],
            "They said the condition was recorded differently",
        )
        self.assertEqual(patient_correction["coverage_state"], "not_provided")
        self.assertEqual(
            patient_correction["supersedes_revision_id"],
            trusted_clinical["observation_revision_id"],
        )

    def test_patient_profile_writes_require_real_source_links_and_changes(self) -> None:
        self._select_user("user-synthetic-a", "Synthetic A")
        base = {
            "modality": "reported_germline_finding",
            "label": "A reported finding",
            "reported_variant": "rs123",
            "source_class": "issued_record",
        }
        with self.assertRaises(LabError) as missing_source:
            self.service.add_profile_observation(base)
        self.assertEqual(missing_source.exception.code, "invalid_profile_observation")

        artifact = self.service.add_source_artifact(
            {
                "content_sha256": "2" * 64,
                "source_type": "laboratory_report",
                "title": "Patient-supplied report",
            }
        )
        finding = self.service.add_profile_observation(
            {**base, "artifact_id": artifact["artifact_id"]}
        )
        self.assertEqual(finding["assertion_author"], "patient")
        self.assertEqual(finding["verification_state"], "user_confirmed")

        with self.assertRaises(LabError) as no_change:
            self.service.review_or_supersede_observation(
                str(finding["observation_revision_id"]), {}
            )
        self.assertEqual(no_change.exception.code, "invalid_profile_observation")

        for semantically_unchanged in (
            {"label": "  A reported finding  "},
            {"label": None},
        ):
            with (
                self.subTest(update=semantically_unchanged),
                self.assertRaises(LabError) as canonical_no_change,
            ):
                self.service.review_or_supersede_observation(
                    str(finding["observation_revision_id"]),
                    semantically_unchanged,
                )
            self.assertEqual(
                canonical_no_change.exception.code, "invalid_profile_observation"
            )

        corrected = self.service.review_or_supersede_observation(
            str(finding["observation_revision_id"]),
            {"label": "A corrected reported finding"},
        )
        with self.assertRaises(LabError) as stale:
            self.service.review_or_supersede_observation(
                str(finding["observation_revision_id"]),
                {"label": "A second stale correction"},
            )
        self.assertEqual(stale.exception.code, "invalid_profile_observation")
        self.assertEqual(
            corrected["supersedes_revision_id"],
            finding["observation_revision_id"],
        )

    def test_profile_entities_reject_unknown_fields_and_mismatched_sources(
        self,
    ) -> None:
        self._select_user("user-synthetic-a", "Synthetic A")
        entity_calls = (
            (
                self.service.add_source_artifact,
                {
                    "content_sha256": "3" * 64,
                    "source_type": "laboratory_report",
                    "title": "Report",
                    "junk": "not accepted",
                },
                "invalid_source_artifact",
            ),
            (
                self.service.add_source_artifact,
                {
                    "content_sha256": "6" * 64,
                    "source_type": "laboratory_report",
                    "title": "Report",
                    "metadata": {"unreviewed": "not accepted by patient API"},
                },
                "invalid_source_artifact",
            ),
            (
                self.service.add_specimen,
                {"specimen_type": "blood", "junk": "not accepted"},
                "invalid_specimen",
            ),
            (
                self.service.add_specimen,
                {
                    "specimen_type": "blood",
                    "metadata": {"unreviewed": "not accepted by patient API"},
                },
                "invalid_specimen",
            ),
            (
                self.service.add_assay,
                {
                    "assay_type": "panel",
                    "assay_scope": {"description": "synthetic"},
                    "detection_limits": {"description": "synthetic"},
                    "junk": "not accepted",
                },
                "invalid_assay",
            ),
            (
                self.service.add_assay,
                {
                    "assay_type": "panel",
                    "assay_scope": {"description": "synthetic"},
                    "detection_limits": {"description": "synthetic"},
                    "qc": {"status": "patient cannot claim passed"},
                },
                "invalid_assay",
            ),
        )
        for operation, payload, code in entity_calls:
            with self.subTest(code=code), self.assertRaises(LabError) as raised:
                operation(payload)
            self.assertEqual(raised.exception.code, code)

        artifact_a = self.service.add_source_artifact(
            {
                "content_sha256": "4" * 64,
                "source_type": "pathology_report",
                "title": "Pathology A",
            }
        )
        artifact_b = self.service.add_source_artifact(
            {
                "content_sha256": "5" * 64,
                "source_type": "laboratory_report",
                "title": "Laboratory B",
            }
        )
        specimen = self.service.add_specimen(
            {
                "artifact_id": artifact_a["artifact_id"],
                "specimen_type": "tumor tissue",
                "tumor_normal_role": "tumor",
            }
        )
        with self.assertRaises(LabError) as mismatch:
            self.service.add_assay(
                {
                    "artifact_id": artifact_b["artifact_id"],
                    "specimen_id": specimen["specimen_id"],
                    "assay_type": "tumor panel",
                    "assay_scope": {"description": "synthetic"},
                    "detection_limits": {"description": "synthetic"},
                }
            )
        self.assertEqual(mismatch.exception.code, "invalid_assay")

    def test_user_switch_during_profile_read_returns_no_prior_user_data(self) -> None:
        self._select_user("user-synthetic-a", "Synthetic A")
        self.service.add_profile_observation(
            {
                "modality": "condition",
                "label": "Patient A private condition",
                "source_class": "patient_reported",
            }
        )
        entered = threading.Event()
        release = threading.Event()
        original = self.service.store.get_workspace

        def blocked(user_id: str) -> JsonObject:
            result = original(user_id)
            entered.set()
            self.assertTrue(release.wait(timeout=5))
            return result

        self.service.store.get_workspace = blocked  # type: ignore[method-assign]
        outcomes: list[object] = []

        def read_profile() -> None:
            try:
                outcomes.append(self.service.molecular_profile())
            except Exception as exc:  # asserted below
                outcomes.append(exc)

        worker = threading.Thread(target=read_profile)
        worker.start()
        self.assertTrue(entered.wait(timeout=5))
        self.genomi.select("user-synthetic-b", "Synthetic B")
        release.set()
        worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], LabError)
        self.assertEqual(outcomes[0].code, "genomi_user_changed")
        self.assertNotIn("Patient A private condition", repr(outcomes[0]))

    def test_user_switch_during_profile_mutation_rolls_back_commit(self) -> None:
        self._select_user("user-synthetic-a", "Synthetic A")
        entered = threading.Event()
        release = threading.Event()
        original_connect = self.service.store._database.connect

        @contextmanager
        def blocking_connect():  # type: ignore[no-untyped-def]
            with original_connect() as connection:

                def trace(statement: str) -> None:
                    if statement.lstrip().startswith(
                        "INSERT INTO molecular_observations"
                    ):
                        entered.set()
                        self.assertTrue(release.wait(timeout=5))

                connection.set_trace_callback(trace)
                try:
                    yield connection
                finally:
                    connection.set_trace_callback(None)

        self.service.store._database.connect = blocking_connect  # type: ignore[method-assign]
        outcomes: list[object] = []

        def mutate_profile() -> None:
            try:
                outcomes.append(
                    self.service.add_profile_observation(
                        {
                            "modality": "condition",
                            "label": "Must not commit for patient A",
                            "source_class": "patient_reported",
                        }
                    )
                )
            except Exception as exc:  # asserted below
                outcomes.append(exc)

        worker = threading.Thread(target=mutate_profile)
        worker.start()
        self.assertTrue(entered.wait(timeout=5))
        self.genomi.select("user-synthetic-b", "Synthetic B")
        release.set()
        worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertIsInstance(outcomes[0], LabError)
        self.assertEqual(outcomes[0].code, "genomi_user_changed")
        reopened = GenomiLabStore(self.store.path, key_provider=TEST_LAB_KEY_PROVIDER)
        profile_a = reopened.get_workspace("user-synthetic-a")["profile"]
        self.assertNotIn("Must not commit for patient A", repr(profile_a))

        # Subsequent work is bound to B and cannot disclose A's profile.
        profile_b = self.service.molecular_profile()
        self.assertEqual(profile_b["user_id"], "user-synthetic-b")
        self.assertNotIn("Must not commit for patient A", repr(profile_b))

    def test_event_long_poll_does_not_block_other_patient_operations(self) -> None:
        self._select_user("user-synthetic-a", "Synthetic A")
        investigation = self.service.create_investigation(
            {
                "question": "Could this synthetic condition be investigated?",
                "disease_scope": "Synthetic condition",
            }
        )
        adapter = _BlockingEventWaitAdapter()
        self.service.harness_adapter = adapter
        stream_outcomes: list[object] = []

        def stream() -> None:
            try:
                stream_outcomes.append(
                    self.service.stream_investigation_events(
                        str(investigation["investigation_id"]),
                        after_sequence=0,
                        timeout_seconds=5,
                    )
                )
            except Exception as exc:  # asserted below
                stream_outcomes.append(exc)

        stream_worker = threading.Thread(target=stream)
        stream_worker.start()
        self.assertTrue(adapter.wait_entered.wait(timeout=2))

        read_outcomes: list[object] = []
        read_finished = threading.Event()

        def read_profile() -> None:
            try:
                read_outcomes.append(self.service.molecular_profile())
            except Exception as exc:  # asserted below
                read_outcomes.append(exc)
            finally:
                read_finished.set()

        read_worker = threading.Thread(target=read_profile)
        read_worker.start()
        try:
            self.assertTrue(
                read_finished.wait(timeout=1),
                "a long-poll wait held the patient-operation authority lock",
            )
        finally:
            adapter.release_wait.set()
        read_worker.join(timeout=2)
        stream_worker.join(timeout=2)

        self.assertFalse(read_worker.is_alive())
        self.assertFalse(stream_worker.is_alive())
        self.assertEqual(len(read_outcomes), 1)
        self.assertIsInstance(read_outcomes[0], dict)
        self.assertEqual(len(stream_outcomes), 1)
        self.assertIsInstance(stream_outcomes[0], dict)

    def test_user_switch_during_event_wait_returns_no_prior_user_events(self) -> None:
        self._select_user("user-synthetic-a", "Synthetic A")
        investigation = self.service.create_investigation(
            {
                "question": "Patient A private investigation question",
                "disease_scope": "Synthetic condition",
            }
        )
        adapter = _BlockingEventWaitAdapter()
        self.service.harness_adapter = adapter
        outcomes: list[object] = []

        def stream() -> None:
            try:
                outcomes.append(
                    self.service.stream_investigation_events(
                        str(investigation["investigation_id"]),
                        after_sequence=0,
                        timeout_seconds=5,
                    )
                )
            except Exception as exc:  # asserted below
                outcomes.append(exc)

        worker = threading.Thread(target=stream)
        worker.start()
        self.assertTrue(adapter.wait_entered.wait(timeout=2))
        self.genomi.select("user-synthetic-b", "Synthetic B")
        adapter.release_wait.set()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], LabError)
        self.assertEqual(outcomes[0].code, "genomi_user_changed")
        self.assertNotIn("Patient A private investigation question", repr(outcomes[0]))
        profile_b = self.service.molecular_profile()
        self.assertEqual(profile_b["user_id"], "user-synthetic-b")


if __name__ == "__main__":
    unittest.main()
