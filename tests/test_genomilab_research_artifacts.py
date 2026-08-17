from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from importlib import resources
from pathlib import Path
from typing import Any
from unittest import mock

from genomi.interfaces.mcp import handle_request
from genomi.lab.research_artifact_contract import (
    ESM_NONCLINICAL_COMPARISON,
    GENOMI_SEQUENCE_SUBSTITUTION_VERIFICATION,
    PRECOMPUTED_FIXTURE,
    PROTO_BLINDED_EXPERIMENTAL_DESIGN,
    research_artifact_submission_input_schema,
)
from genomi.lab.service import GenomiLabService, LabError
from genomi.lab.store import GenomiLabStore
from genomi.operations import TOOL_CATALOG_OPERATIONS
from tests.genomilab_support import (
    TEST_LAB_KEY_PROVIDER,
    synthetic_ready_agi_context,
)


REFERENCE_SEQUENCE = "A" * 75 + "Q" + "A" * 40


class _CurrentContext:
    def __call__(
        self,
        operation: str,
        params: dict[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        del params
        if operation == "genomi.describe_context":
            return synthetic_ready_agi_context(
                "research-artifact-user", "Research Artifact Patient"
            )
        if operation == "active_genome_index.revoke_access":
            return {"status": "revoked"}
        raise AssertionError(f"unexpected operation: {operation}")


def _esm_executor(request: dict[str, Any]) -> dict[str, Any]:
    assert request["reference_sequence"] == REFERENCE_SEQUENCE
    assert request["alternate_sequence"][75] == "H"
    assert request["required_execution_location"] == "local"
    assert request["required_network_access"] == "disabled"
    return {
        "method": {
            "name": "masked_marginal_substitution_comparison",
            "version": "1",
        },
        "model": {"name": "ESMC-600M", "version": "2024-12"},
        "output": {
            "metric": "masked_marginal_log_probability",
            "reference_score": -1.0,
            "alternate_score": -1.75,
            "delta": -0.75,
        },
        "provenance": {
            "execution_location": "local",
            "network_access": "disabled",
            "source_label": "test ESM scientific executor",
            "source_version": "executor-1",
            "source_record_id": "esm-run-001",
        },
    }


def _proto_executor(request: dict[str, Any]) -> dict[str, Any]:
    assert request["protein_substitution"] == "Q76H"
    assert request["required_execution_location"] == "local"
    assert request["required_network_access"] == "disabled"
    return {
        "method": {
            "name": "blinded_control_design",
            "version": "1",
        },
        "model": {"name": "Proto", "version": "fixture-2026-08"},
        "output": {
            "blinded_arm_labels": ["Arm A", "Arm B", "Arm C", "Arm D"],
            "quality_controls": ["Prespecify assay acceptance criteria."],
            "analysis_plan": [
                "Compare abundance and ligand-removal readouts separately."
            ],
        },
        "provenance": {
            "execution_location": "local",
            "network_access": "disabled",
            "source_label": "test Proto scientific executor",
            "source_version": "executor-1",
            "source_record_id": "proto-run-001",
        },
    }


class GenomiLabResearchArtifactTests(unittest.TestCase):
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
        self.service = GenomiLabService(
            store=GenomiLabStore(self.store_path, key_provider=TEST_LAB_KEY_PROVIDER),
            session_id="research-artifact-session",
            operation_call=_CurrentContext(),
            agent_host_id="research-artifact-host",
            agent_processing_destination="current research artifact test host",
            esm_scientific_executor=_esm_executor,
            proto_scientific_executor=_proto_executor,
        )
        self.addCleanup(self.service.close)
        self.service.bootstrap_workspace()
        self.observation = self.service.add_profile_observation(
            {
                "modality": "condition",
                "label": "Synthetic immune dysregulation",
                "assertion_status": "present",
                "source_class": "patient_reported",
                "verification_state": "user_confirmed",
            }
        )
        investigation = self.service.create_investigation(
            {
                "question": "Could these immune findings be connected?",
                "disease_scope": "Synthetic immune dysregulation",
            }
        )
        self.investigation_id = str(investigation["investigation_id"])
        self.specialists = [
            {
                "specialist_id": "specialist-computation",
                "role": "Computational specialist",
                "task": "Review a nonclinical comparison artifact",
            },
            {
                "specialist_id": "specialist-experiment",
                "role": "Experimental-design specialist",
                "task": "Review a blinded design artifact",
            },
        ]
        self.service.form_agent_specialist_board(
            self.investigation_id, specialists=self.specialists
        )
        prepared = self.service.prepare_agent_authorization(
            self.investigation_id,
            purpose="Review nonclinical research artifacts",
            observation_revision_ids=[self.observation["observation_revision_id"]],
        )
        candidate = prepared["candidate"]
        self.service.authorize_investigation_context(
            self.investigation_id,
            {
                key: value
                for key, value in candidate.items()
                if key
                not in {
                    "status",
                    "requires_explicit_approval",
                    "user_id",
                    "investigation_id",
                }
            }
            | {"approved": True},
        )
        plan = self.service.submit_agent_plan(
            self.investigation_id,
            focus_question="Can the Q76H mechanism be sharpened nonclinically?",
            specialist_assignments=[
                {
                    "specialist_id": item["specialist_id"],
                    "task": item["task"],
                }
                for item in self.specialists
            ],
            requests=[
                {
                    "id": "project-research-profile",
                    "capability": "investigation.project_profile",
                    "parameters": {},
                }
            ],
        )
        self.round_id = str(plan["investigation_round"]["round_id"])

    @staticmethod
    def _fixture_provenance() -> dict[str, str]:
        return {
            "execution_class": PRECOMPUTED_FIXTURE,
            "execution_location": "not_verified",
            "network_access": "not_verified",
            "source_label": "curated demo fixture",
            "source_version": "2026-08",
            "source_record_id": "fixture-record-001",
        }

    @classmethod
    def _esm_artifact(cls, *, alternate_score: float = -1.75) -> dict[str, object]:
        return {
            "artifact_kind": ESM_NONCLINICAL_COMPARISON,
            "method": {"name": "masked_marginal_comparison", "version": "1"},
            "model": {"name": "ESMC fixture", "version": "2024-12"},
            "input": {
                "gene": "CTLA4",
                "transcript_accession": "NM_005214.5",
                "protein_accession": "NP_005205.2",
                "protein_substitution": "Q76H",
                "reference_sequence_sha256": "a" * 64,
                "alternate_sequence_sha256": "b" * 64,
            },
            "output": {
                "metric": "masked_marginal_log_probability",
                "reference_score": -1.0,
                "alternate_score": alternate_score,
                "delta": alternate_score + 1.0,
            },
            "provenance": cls._fixture_provenance(),
        }

    @classmethod
    def _proto_artifact(cls) -> dict[str, object]:
        return {
            "artifact_kind": PROTO_BLINDED_EXPERIMENTAL_DESIGN,
            "method": {"name": "blinded_control_design", "version": "1"},
            "model": {"name": "Proto fixture", "version": "2026-08"},
            "input": {
                "gene": "CTLA4",
                "protein_accession": "NP_005205.2",
                "protein_substitution": "Q76H",
                "objective": "Separate CTLA4 abundance from ligand removal.",
                "required_arm_classes": [
                    "wild_type_reference",
                    "test_variant",
                    "assay_negative_control",
                    "functional_loss_control",
                ],
                "readouts": ["ctla4_abundance", "cd80_cd86_ligand_removal"],
            },
            "output": {
                "blinded_arm_labels": ["Arm A", "Arm B", "Arm C", "Arm D"],
                "quality_controls": ["Prespecify assay acceptance criteria."],
                "analysis_plan": [
                    "Compare abundance and ligand-removal readouts separately."
                ],
            },
            "provenance": cls._fixture_provenance(),
        }

    def _verify_sequence(self) -> dict[str, Any]:
        return self.service.verify_agent_sequence_substitution(
            self.investigation_id,
            round_id=self.round_id,
            deduplication_key="genomi-q76h-verification",
            gene="CTLA4",
            transcript_accession="NM_005214.5",
            protein_accession="NP_005205.2",
            coding_change="c.228G>C",
            protein_substitution="Q76H",
            public_reference_protein_sequence=REFERENCE_SEQUENCE,
            reference_source_label="NCBI RefSeq",
            reference_source_version="2026-08",
            reference_source_record_id="NP_005205.2",
        )

    def _mcp_call(self, operation: str, arguments: dict[str, object]) -> dict[str, Any]:
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

    def test_direct_host_tools_submit_and_read_without_execution_claim(self) -> None:
        submitted = self._mcp_call(
            "genomilab.submit_research_artifact",
            {
                "investigation_id": self.investigation_id,
                "round_id": self.round_id,
                "deduplication_key": "mcp-esm-artifact",
                "origin": PRECOMPUTED_FIXTURE,
                "artifact": self._esm_artifact(),
            },
        )
        self.assertEqual(submitted["provider_execution"], "not_verified")
        self.assertEqual(submitted["scientific_execution"], "not_verified")

        listed = self._mcp_call(
            "genomilab.list_research_artifacts",
            {"investigation_id": self.investigation_id},
        )
        self.assertEqual(listed["research_artifact_count"], 1)
        artifact = listed["research_artifacts"][0]
        self.assertEqual(artifact["round_id"], self.round_id)
        self.assertEqual(artifact["round_number"], 1)
        self.assertEqual(
            artifact["research_envelope"]["answer_readiness_effect"], "none"
        )
        self.assertNotIn("answer_readiness", artifact["research_envelope"])

    def test_host_submits_separate_versioned_nonclinical_artifacts(self) -> None:
        esm = self.service.submit_agent_research_artifact(
            self.investigation_id,
            round_id=self.round_id,
            deduplication_key="round-1-esm-q76h",
            origin=PRECOMPUTED_FIXTURE,
            artifact=self._esm_artifact(),
        )
        proto = self.service.submit_agent_research_artifact(
            self.investigation_id,
            round_id=self.round_id,
            deduplication_key="round-1-proto-design",
            origin=PRECOMPUTED_FIXTURE,
            artifact=self._proto_artifact(),
        )

        self.assertEqual(esm["research_artifact"]["system"], "esm")
        self.assertEqual(proto["research_artifact"]["system"], "proto")
        self.assertEqual(
            esm["research_artifact"]["artifact"]["method"]["version"], "1"
        )
        self.assertFalse(
            esm["research_artifact"]["use_boundary"][
                "eligible_for_answer_readiness"
            ]
        )
        self.assertEqual(
            esm["research_artifact"]["research_envelope"][
                "provider_execution_status"
            ],
            "not_verified",
        )

    def test_scientific_operations_verify_run_and_persist_without_sequences(self) -> None:
        genomi = self._verify_sequence()["research_artifact"]
        self.assertEqual(genomi["system"], "genomi")
        self.assertEqual(
            genomi["artifact_kind"], GENOMI_SEQUENCE_SUBSTITUTION_VERIFICATION
        )
        self.assertEqual(
            genomi["artifact"]["output"]["protein_substitution_verified"], True
        )

        esm = self.service.run_agent_esm_substitution_analysis(
            self.investigation_id,
            round_id=self.round_id,
            deduplication_key="esm-scientific-q76h",
            sequence_verification_artifact_id=genomi["research_artifact_id"],
            public_reference_protein_sequence=REFERENCE_SEQUENCE,
        )
        proto = self.service.run_agent_proto_blinded_experiment_design(
            self.investigation_id,
            round_id=self.round_id,
            deduplication_key="proto-scientific-q76h",
            sequence_verification_artifact_id=genomi["research_artifact_id"],
            objective="Separate CTLA4 abundance from ligand-removal function.",
            required_arm_classes=[
                "wild_type_reference",
                "test_variant",
                "assay_negative_control",
                "functional_loss_control",
            ],
            readouts=["ctla4_abundance", "cd80_cd86_ligand_removal"],
        )
        self.assertEqual(esm["status"], "completed")
        self.assertEqual(proto["status"], "completed")
        self.assertEqual(esm["scientific_execution"], "verified_local_execution")
        self.assertEqual(
            esm["research_artifact"]["artifact"]["model"],
            {"name": "ESMC-600M", "version": "2024-12"},
        )
        self.assertEqual(
            proto["research_artifact"]["artifact"]["provenance"][
                "source_record_id"
            ],
            "proto-run-001",
        )

        serialized = json.dumps(
            self.service.list_agent_research_artifacts(self.investigation_id)
        )
        self.assertNotIn(REFERENCE_SEQUENCE, serialized)
        self.assertIn(hashlib.sha256(REFERENCE_SEQUENCE.encode("ascii")).hexdigest(), serialized)
        self.assertEqual(
            self.service.list_agent_research_artifacts(self.investigation_id)[
                "research_artifact_count"
            ],
            3,
        )

    def test_missing_scientific_executor_is_explicit_and_creates_no_artifact(self) -> None:
        genomi = self._verify_sequence()["research_artifact"]
        self.service._esm_scientific_executor = None
        result = self.service.run_agent_esm_substitution_analysis(
            self.investigation_id,
            round_id=self.round_id,
            deduplication_key="unavailable-esm",
            sequence_verification_artifact_id=genomi["research_artifact_id"],
            public_reference_protein_sequence=REFERENCE_SEQUENCE,
        )
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(
            result["unavailable_state"], "esm_scientific_executor_not_configured"
        )
        self.assertIsNone(result["research_artifact"])
        self.assertEqual(
            self.service.list_agent_research_artifacts(self.investigation_id)[
                "research_artifact_count"
            ],
            1,
        )
        tools = self.service.list_agent_research_tools()
        self.assertEqual(
            tools["scientific_operations"][
                "genomilab.run_esm_substitution_analysis"
            ]["availability"],
            "unavailable",
        )
        self.assertEqual(
            tools["usage_boundary"]["biohub-esm-connection"],
            "connection_check_does_not_execute_scientific_analysis",
        )

    def test_submission_is_idempotent_but_identity_is_immutable(self) -> None:
        first = self.service.submit_agent_research_artifact(
            self.investigation_id,
            round_id=self.round_id,
            deduplication_key="stable-esm-artifact",
            origin=PRECOMPUTED_FIXTURE,
            artifact=self._esm_artifact(),
        )
        retry = self.service.submit_agent_research_artifact(
            self.investigation_id,
            round_id=self.round_id,
            deduplication_key="stable-esm-artifact",
            origin=PRECOMPUTED_FIXTURE,
            artifact=self._esm_artifact(),
        )
        self.assertTrue(retry["retry_reused"])
        self.assertEqual(
            retry["research_artifact"]["research_artifact_id"],
            first["research_artifact"]["research_artifact_id"],
        )

        with self.assertRaises(LabError) as collision:
            self.service.submit_agent_research_artifact(
                self.investigation_id,
                round_id=self.round_id,
                deduplication_key="stable-esm-artifact",
                origin=PRECOMPUTED_FIXTURE,
                artifact=self._esm_artifact(alternate_score=-2.0),
            )
        self.assertEqual(collision.exception.code, "invalid_research_artifact")

    def test_database_guards_block_artifact_update_and_delete(self) -> None:
        submitted = self.service.submit_agent_research_artifact(
            self.investigation_id,
            round_id=self.round_id,
            deduplication_key="immutable-esm-artifact",
            origin=PRECOMPUTED_FIXTURE,
            artifact=self._esm_artifact(),
        )["research_artifact"]
        artifact_id = submitted["research_artifact_id"]

        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "research artifacts are immutable"
        ):
            with self.service.store._connect() as connection:
                connection.execute(
                    "UPDATE research_artifacts SET origin = ? WHERE research_artifact_id = ?",
                    ("host_supplied_unverified", artifact_id),
                )
        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "research artifacts are immutable"
        ):
            with self.service.store._connect() as connection:
                connection.execute(
                    "DELETE FROM research_artifacts WHERE research_artifact_id = ?",
                    (artifact_id,),
                )

    def test_reopen_installs_the_current_ledger_for_an_existing_workspace(self) -> None:
        with self.service.store._connect() as connection:
            connection.execute("DROP TRIGGER research_artifacts_immutable")
            connection.execute("DROP TRIGGER research_artifacts_delete_immutable")
            connection.execute("DROP TABLE research_artifacts")

        reopened = GenomiLabStore(self.store_path, key_provider=TEST_LAB_KEY_PROVIDER)
        indexes = reopened.indexes_for("research_artifacts")
        self.assertIn("idx_research_artifacts_investigation_profile", indexes)
        with reopened._connect() as connection:
            columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(research_artifacts)"
                ).fetchall()
            }
            triggers = {
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type = 'trigger' AND tbl_name = 'research_artifacts'"
                ).fetchall()
            }
        self.assertIn("round_id", columns)
        self.assertIn("research_envelope_json", columns)
        self.assertEqual(
            triggers,
            {
                "research_artifacts_immutable",
                "research_artifacts_delete_immutable",
            },
        )

    def test_artifact_ids_cannot_anchor_evidence_hypotheses_or_briefs(self) -> None:
        before = self.service.investigation(self.investigation_id)
        artifact = self.service.submit_agent_research_artifact(
            self.investigation_id,
            round_id=self.round_id,
            deduplication_key="excluded-esm-artifact",
            origin=PRECOMPUTED_FIXTURE,
            artifact=self._esm_artifact(),
        )["research_artifact"]
        artifact_id = str(artifact["research_artifact_id"])
        observation_id = str(self.observation["observation_revision_id"])

        investigation = self.service.investigation(self.investigation_id)
        self.assertEqual(investigation["evidence_records"], [])
        self.assertEqual(investigation["current_evidence_records"], [])
        self.assertEqual(investigation["hypotheses"], [])
        self.assertEqual(investigation["brief_versions"], [])
        self.assertEqual(
            investigation["evidence_snapshot_id"], before["evidence_snapshot_id"]
        )
        self.assertEqual(
            investigation["current_hypotheses"], before["current_hypotheses"]
        )
        self.assertEqual(
            investigation["current_brief_version"], before["current_brief_version"]
        )

        with self.assertRaisesRegex(ValueError, "evidence claim anchors"):
            self.service.store._validate_claim_anchors(
                self.investigation_id,
                evidence_record_ids=[artifact_id],
                profile_revision_ids=[observation_id],
            )
        with self.assertRaisesRegex(ValueError, "evidence claim anchors"):
            self.service.store.commit_hypothesis(
                self.investigation_id,
                kind="uncertainty",
                statement="Evidence gap: Independent clinical confirmation remains open.",
                evidence_record_ids=[artifact_id],
                profile_revision_ids=[observation_id],
            )

        inspected = self.service.inspect_agent_investigation(self.investigation_id)
        brief_schema = inspected["brief_authoring"]["brief_schema"]
        allowed_evidence = brief_schema["properties"]["claims"]["items"][
            "properties"
        ]["evidence_record_ids"]["items"].get("enum", [])
        self.assertNotIn(artifact_id, allowed_evidence)
        self.assertNotIn(artifact_id, json.dumps(inspected["capability_catalog"]))

    def test_contract_rejects_execution_claims_and_raw_sequence_storage(self) -> None:
        artifact = self._esm_artifact()
        artifact["provenance"]["execution_class"] = "verified_scientific_operation"  # type: ignore[index]
        artifact["provenance"]["execution_location"] = "local"  # type: ignore[index]
        artifact["provenance"]["network_access"] = "disabled"  # type: ignore[index]
        with self.assertRaises(LabError) as claimed_execution:
            self.service.submit_agent_research_artifact(
                self.investigation_id,
                round_id=self.round_id,
                deduplication_key="claimed-execution",
                origin="verified_scientific_operation",
                artifact=artifact,
            )
        self.assertEqual(
            claimed_execution.exception.code, "invalid_research_artifact"
        )

        unsafe = self._esm_artifact()
        unsafe["raw_sequence"] = "MKT"
        with self.assertRaises(LabError) as raw_sequence:
            self.service.submit_agent_research_artifact(
                self.investigation_id,
                round_id=self.round_id,
                deduplication_key="unsafe-sequence",
                origin=PRECOMPUTED_FIXTURE,
                artifact=unsafe,
            )
        self.assertEqual(raw_sequence.exception.code, "invalid_research_artifact")

    def test_direct_tool_catalog_exposes_scientific_operation_contracts(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
            transport="stdio",
        )
        assert response is not None
        tools = {item["name"]: item for item in response["result"]["tools"]}
        expected = {
            "genomilab.submit_research_artifact",
            "genomilab.verify_sequence_substitution",
            "genomilab.run_esm_substitution_analysis",
            "genomilab.run_proto_blinded_experiment_design",
            "genomilab.list_research_artifacts",
        }
        self.assertTrue(expected.issubset(tools))
        submit_schema = tools["genomilab.submit_research_artifact"]["inputSchema"]
        expected_submit_schema = research_artifact_submission_input_schema()
        self.assertEqual(submit_schema, expected_submit_schema)
        self.assertEqual(
            TOOL_CATALOG_OPERATIONS["genomilab.submit_research_artifact"][
                "input_schema"
            ],
            expected_submit_schema,
        )
        self.assertIn("round_id", submit_schema["required"])
        variants = submit_schema["properties"]["artifact"]["oneOf"]
        self.assertEqual(
            {item["properties"]["artifact_kind"]["const"] for item in variants},
            {
                ESM_NONCLINICAL_COMPARISON,
                PROTO_BLINDED_EXPERIMENTAL_DESIGN,
                GENOMI_SEQUENCE_SUBSTITUTION_VERIFICATION,
            },
        )

    def test_portal_projects_artifacts_in_separate_round_bound_panel(self) -> None:
        static = resources.files("genomi.lab").joinpath("static")
        html = static.joinpath("index.html").read_text(encoding="utf-8")
        renderer = static.joinpath("render.js").read_text(encoding="utf-8")
        artifact_renderer = static.joinpath("render-research-artifacts.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="research-artifact-ledger"', html)
        self.assertIn("connection checks never count as scientific execution", html)
        self.assertIn(
            "renderResearchArtifacts(investigation.current_research_artifacts)",
            renderer,
        )
        self.assertIn("Nonclinical · non-evidence", artifact_renderer)
        self.assertIn("Illustrative demo result", artifact_renderer)
        self.assertIn(
            "Illustrative demo result · nonclinical · not used as evidence",
            artifact_renderer,
        )
        self.assertIn('isFixture ? ""', artifact_renderer)
        self.assertIn("answer-readiness", artifact_renderer)
        self.assertIn("Genomi sequence-substitution verification", artifact_renderer)
        self.assertNotIn("fetch(", artifact_renderer)


if __name__ == "__main__":
    unittest.main()
