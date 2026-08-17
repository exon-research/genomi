from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from genomi.lab import agi_authority as investigation_access
from genomi.lab.provider_policy import SourceFamily
from genomi.lab.service import GenomiLabService
from genomi.lab.store import GenomiLabStore
from genomi.operations import call_operation

from tests.genomilab_support import TEST_LAB_KEY_PROVIDER
from tests.support.runtime.genomi import GenomiRuntimeTestCase


FIXTURE_ROOT = Path(__file__).resolve().parent / "data"
PATIENT_A_VCF = FIXTURE_ROOT / "genomilab_synthetic_patient_a.vcf"
PATIENT_B_VCF = FIXTURE_ROOT / "genomilab_synthetic_patient_b.vcf"


class GenomiLabEndToEndCase(GenomiRuntimeTestCase):
    """Shared product-boundary fixture for focused GenomiLab E2E suites."""

    def setUp(self) -> None:
        super().setUp()
        investigation_access._reset_investigation_agi_authorization_epoch_for_testing()
        self.addCleanup(
            investigation_access._reset_investigation_agi_authorization_epoch_for_testing
        )
        self.store_path = self.genomi_home / "lab" / "genomilab-e2e.sqlite3"
        self.services: list[GenomiLabService] = []
        self.service = self._new_service("workspace-session-a")
        self.addCleanup(self._close_services)

    @staticmethod
    def _public_evidence_fixture() -> dict[str, object]:
        return {
            "status": "data_returned",
            "source_family": "literature",
            "coverage": {"consulted": ["Synthetic indexed literature"]},
            "records": [
                {
                    "source_id": "PMID:SYNTHETIC-E2E",
                    "identifiers": {"pmid": "SYNTHETIC-E2E"},
                    "title": "Synthetic variant-disease mechanism report",
                    "excerpt": (
                        "In this synthetic benchmark, rs900000001 in SYNTH1 was "
                        "reported with the synthetic neuromuscular condition."
                    ),
                    "supporting_spans": [
                        "The synthetic benchmark reports rs900000001 in SYNTH1 "
                        "with the synthetic neuromuscular condition."
                    ],
                    "source_document_state": "peer_reviewed_publication",
                    "source_uri": "https://pubmed.ncbi.nlm.nih.gov/999999999/",
                    "publication_date": "2026-07-01",
                    "source_license": {
                        "status": "test_fixture",
                        "short_excerpt_storage_permitted": True,
                    },
                }
            ],
        }

    def _new_service(self, session_id: str) -> GenomiLabService:
        service = GenomiLabService(
            store=GenomiLabStore(self.store_path, key_provider=TEST_LAB_KEY_PROVIDER),
            session_id=session_id,
            operation_call=call_operation,
            agent_host_id="synthetic-e2e-host",
            agent_processing_destination="current synthetic E2E host",
        )
        service.configure_evidence_gateway(
            fixtures={SourceFamily.LITERATURE: self._public_evidence_fixture()}
        )
        self.services.append(service)
        return service

    def _close_services(self) -> None:
        for service in reversed(self.services):
            service.close()

    def _intake_current_user(
        self, fixture: Path, *, nickname: str, source_name: str
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Use Genomi's normal source intake; GenomiLab never receives the VCF."""

        source = self.genomi_home / "patient-sources" / source_name
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture, source)
        parsed = call_operation(
            "genomi.parse_source",
            {
                "source": str(source),
                "user_nickname": nickname,
                "genome_build": "GRCh38",
            },
        )
        self.assertEqual(parsed["status"], "completed")
        context = call_operation("genomi.describe_context")
        self.assertEqual(context["active_user"]["nickname"], nickname)
        self.assertEqual(
            context["active_agi_id"],
            parsed["active_genome_index"]["agi_id"],
        )
        self.assertEqual(
            context["active_genome_index"]["agi_snapshot_id"],
            parsed["active_genome_index"]["agi_snapshot_id"],
        )
        return parsed, context

    def _add_molecular_profile(
        self, service: GenomiLabService
    ) -> dict[str, dict[str, object]]:
        report_content = b"synthetic issued molecular laboratory report"
        artifact = service.add_source_artifact(
            {
                "content_sha256": hashlib.sha256(report_content).hexdigest(),
                "source_type": "laboratory_report",
                "title": "Synthetic germline panel report",
                "source_identifier": "SYNTH-REPORT-A",
                "issued_at": "2026-01-15",
            }
        )
        specimen = service.add_specimen(
            {
                "artifact_id": artifact["artifact_id"],
                "specimen_type": "blood",
                "tumor_normal_role": "germline",
                "collected_at": "2026-01-10",
            }
        )
        assay = service.add_assay(
            {
                "artifact_id": artifact["artifact_id"],
                "specimen_id": specimen["specimen_id"],
                "assay_type": "targeted germline panel",
                "laboratory": "Synthetic laboratory",
                "genome_build": "GRCh38",
                "assay_scope": {"genes": ["SYNTH1", "SYNTH2"]},
                "detection_limits": {"minimum_depth": 20},
            }
        )
        condition = service.add_profile_observation(
            {
                "modality": "condition",
                "label": "Synthetic neuromuscular condition",
                "original_wording": "Synthetic neuromuscular condition",
                "assertion_status": "present",
                "verification_state": "user_confirmed",
                "source_class": "patient_reported",
            }
        )
        phenotype = service.add_profile_observation(
            {
                "modality": "phenotype",
                "label": "Intermittent muscle weakness",
                "original_wording": "Episodes of muscle weakness",
                "assertion_status": "present",
                "verification_state": "user_confirmed",
                "source_class": "patient_reported",
            }
        )
        finding = service.add_profile_observation(
            {
                "modality": "reported_germline_finding",
                "label": "Report states rs900000001",
                "original_wording": "rs900000001 was reported",
                "reported_variant": "rs900000001",
                "gene": "SYNTH1",
                "reported_classification": "research finding",
                "assertion_status": "present",
                "verification_state": "user_confirmed",
                "source_class": "issued_record",
                "artifact_id": artifact["artifact_id"],
                "specimen_id": specimen["specimen_id"],
                "assay_id": assay["assay_id"],
            }
        )
        return {
            "artifact": artifact,
            "specimen": specimen,
            "assay": assay,
            "condition": condition,
            "phenotype": phenotype,
            "finding": finding,
        }

    def _approve_patient_context(
        self,
        service: GenomiLabService,
        investigation_id: str,
        records: dict[str, dict[str, object]],
    ) -> dict[str, object]:
        observation_ids = [
            records[key]["observation_revision_id"]
            for key in ("condition", "phenotype", "finding")
        ]
        candidate = service.investigation_context_candidate(
            investigation_id,
            {
                "purpose": "Investigate disease using the patient's approved molecular profile",
                "observation_revision_ids": observation_ids,
            },
        )
        self.assertEqual(candidate["status"], "candidate")
        self.assertEqual(
            candidate["artifact_ids"], [records["artifact"]["artifact_id"]]
        )
        self.assertEqual(
            candidate["specimen_ids"], [records["specimen"]["specimen_id"]]
        )
        self.assertEqual(candidate["assay_ids"], [records["assay"]["assay_id"]])
        approved = service._approve_context_for_conformance(
            investigation_id,
            {
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
            }
            | {"approved": True},
        )
        self._record_conformance_authorization(
            service, investigation_id, candidate
        )
        self.assertEqual(
            approved["private_genome_access"], "authorized_for_exact_scope"
        )
        return approved

    @staticmethod
    def _record_conformance_authorization(
        service: GenomiLabService,
        investigation_id: str,
        candidate: dict[str, object],
    ) -> None:
        context = service.investigation(investigation_id)
        _, user_id = service._current_context()
        service.store.create_investigation_authorization(
            user_id,
            workspace_session_id=service.session_id,
            investigation_id=investigation_id,
            patient_molecular_snapshot_id=context["patient_molecular_snapshot_id"],
            consent_receipt_id=context["active_consent_receipt_id"],
            authorization_scope=(
                service._investigation_authorizations._authorization_scope()
            ),
            candidate_receipt_sha256=hashlib.sha256(
                f"{service.session_id}:{candidate['candidate_receipt']}".encode(
                    "utf-8"
                )
            ).hexdigest(),
            approved=True,
        )
