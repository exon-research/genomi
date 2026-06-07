from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from genomi.interfaces.presentation import present_result
from genomi.operations import OperationError, call_operation
from genomi.runtime import context as runtime_context
from genomi.runtime.paths import sample_slug_from_source

from tests.support.runtime.genomi import (
    GenomiRuntimeTestCase,
)


class GenomiRuntimeContextTests(GenomiRuntimeTestCase):
    def test_gwas_compare_variants_is_direct_tool_not_runtime_plan(self) -> None:
        with mock.patch(
            "genomi.operations.intent_research.compare_gwas_variant_context",
            return_value={
                "query": {"phenotype": "erythritol", "variants": ["rs2000999", "rs6687813"]},
                "rankings": [],
            },
        ):
            result = call_operation(
                "gwas.compare_variant_associations",
                {"phenotype": "erythritol", "variants": ["rs2000999", "rs6687813"]},
            )

        self.assertEqual(result["query"]["phenotype"], "erythritol")
        self.assertEqual(result["query"]["variants"], ["rs2000999", "rs6687813"])
        self.assertIn("rankings", result)

    def test_screen_compare_gene_is_direct_tool_not_runtime_plan(self) -> None:
        with mock.patch(
            "genomi.operations.intent_research.compare_screen_gene_context",
            return_value={
                "query": {"context": "A549 resistance screen", "genes": ["EGFR", "MYC"]},
                "candidate_matrix": [],
            },
        ):
            result = call_operation(
                "functional_genomics.compare_gene_perturbation",
                {"context": "A549 resistance screen", "genes": ["EGFR", "MYC"], "source_records": []},
            )

        self.assertEqual(result["query"]["context"], "A549 resistance screen")
        self.assertEqual(result["query"]["genes"], ["EGFR", "MYC"])
        self.assertIn("candidate_matrix", result)

    def test_standard_presentation_preserves_decision_evidence_scalars(self) -> None:
        result = call_operation(
            "functional_genomics.compare_gene_perturbation",
            {
                "context": "CRISPR knockout phagocytosis screen",
                "genes": ["NHLRC2", "KPNA2"],
                "source_records": [
                    {
                        "record_id": "screen-1",
                        "title": "Genome-wide CRISPR screen identifies NHLRC2",
                        "text": "NHLRC2 was a top hit in a CRISPR knockout screen measuring phagocytosis.",
                        "source_type": "CRISPR screen",
                        "genes": ["NHLRC2"],
                        "verified_fields": {
                            "genes": ["NHLRC2"],
                            "assays": ["phagocytosis"],
                            "perturbations": ["CRISPR knockout"],
                        },
                    }
                ],
            },
        )

        presented = present_result("functional_genomics.compare_gene_perturbation", result)
        self.assertIsNone(presented["decision_evidence"]["top_observed_evidence"])
        top_evidence = presented["decision_evidence"]["ranked_candidate_evidence"][0]

        self.assertEqual(top_evidence["evidence_trace"]["supporting_record_ids"], ["screen-1"])
        self.assertEqual(top_evidence["evidence_trace"]["supporting_evidence_count"], 1)

    def test_parse_presentation_preserves_active_index_agi_metadata(self) -> None:
        presented = present_result(
            "genomi.parse_source",
            {
                "status": "completed",
                "source_format": "vcf",
                "active_genome_index": {
                    "agi_id": "agi-fixture",
                    "sample_slug": "agi-fixture",
                    "status": "parsed",
                    "agi_source_format": "vcf",
                    "agi_source_kind": "variant_callset",
                    "agi_source_member": "sample.vcf",
                    "genome_build": "GRCh38",
                },
            },
        )

        self.assertEqual(
            presented["active_genome_index"],
            {
                "agi_id": "agi-fixture",
                "sample_slug": "agi-fixture",
                "status": "parsed",
                "agi_source_format": "vcf",
                "agi_source_kind": "variant_callset",
                "agi_source_member": "sample.vcf",
                "genome_build": "GRCh38",
            },
        )

    def test_presentation_redacts_paths_inside_envelope_scope_and_notes(self) -> None:
        presented = present_result(
            "region.retrieve_features",
            {
                "status": "needs_input",
                "message": "required file not found: /tmp/genomi/private/jobs/missing.json",
                "evidence_envelope": {
                    "operation": "region.retrieve_features",
                    "headline": "region.retrieve_features: not_assessed · cannot_answer_yet",
                    "finding_state": "not_assessed",
                    "answer_readiness": "cannot_answer_yet",
                    "guidance": ["missing_input:provide_required_context"],
                    "negative_inference": {"allowed": False, "requires": ["library_coverage"], "satisfied": [], "reason": "missing"},
                    "query_scope": {
                        "assembly": "GRCh38",
                        "gencode_gtf": "/tmp/genomi/private/reference/gencode.gtf.gz",
                        "region": "1:1-10",
                    },
                    "notes": ["looked for /tmp/genomi/private/jobs/missing.json"],
                },
            },
        )

        text = json.dumps(presented)
        self.assertNotIn("/tmp/genomi/private", text)
        self.assertNotIn("gencode_gtf", presented["evidence_envelope"].get("query_scope", {}))
        self.assertIn("[omitted_local_path]", text)

    def test_presentation_redaction_preserves_genotype_tokens(self) -> None:
        presented = present_result(
            "active_genome_index.classify_genotype_support",
            {
                "status": "completed",
                "observed_genotype": "1/1",
                "array_genotype": "C/C",
                "message": "Observed 0/1 and C/C; log at /tmp/genomi/private/jobs/missing.json",
                "evidence_boundaries": [
                    "Negative/absence claims still need coverage evidence",
                    "Use genotype/reference blocks cautiously",
                ],
            },
        )

        text = json.dumps(presented)
        self.assertIn("1/1", text)
        self.assertIn("0/1", text)
        self.assertIn("C/C", text)
        self.assertIn("Negative/absence", text)
        self.assertIn("genotype/reference", text)
        self.assertNotIn("/tmp/genomi/private", text)
        self.assertIn("[omitted_local_path]", text)

    def test_context_can_be_empty_or_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                empty = call_operation("genomi.describe_context")
                self.assertFalse(empty["has_active_genome_index"])

                vcf = Path("sample.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n",
                    encoding="utf-8",
                )
                set_result = call_operation("genomi.parse_source", {"source": str(vcf)})
                self.assertEqual(set_result["status"], "completed")
                self.assertTrue(set_result["active_genome_index"]["sample_slug"].startswith("vcf-sha256-"))

                current = call_operation("genomi.describe_context")
                self.assertTrue(current["has_active_genome_index"])
                self.assertEqual(current["active_genome_index"]["sample_slug"], set_result["active_genome_index"]["sample_slug"])

                summary = call_operation("active_genome_index.summarize")
                self.assertIn("outputs", summary)
            finally:
                os.chdir(previous)

    def test_parse_and_describe_context_point_at_agi_skill_when_needed(self) -> None:
        # The AGI selection/approval/interpretation tools are invoke-only, so the
        # two base entry points (parse_source, describe_context) must tell the
        # host to read the active-genome-index skill — but only when AGI work is
        # actually needed.
        def reads_agi_skill(result: dict) -> bool:
            return any(
                a.get("action") == "read_skill" and "active-genome-index" in str(a.get("skill", ""))
                for a in (result.get("next_actions") or [])
            )

        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                # Empty/public-only context: no pointer.
                self.assertFalse(reads_agi_skill(call_operation("genomi.describe_context")))

                vcf = Path("sample.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n",
                    encoding="utf-8",
                )
                # A successful parse always points at the AGI skill.
                self.assertTrue(reads_agi_skill(call_operation("genomi.parse_source", {"source": str(vcf)})))

                # Active + approved (default): no pointer — downstream tools read it directly.
                self.assertFalse(reads_agi_skill(call_operation("genomi.describe_context")))

                # Revoked: genome data exists but isn't approved → pointer (new session
                # asking about own data must read the skill to approve/select).
                call_operation("active_genome_index.revoke_access")
                self.assertTrue(reads_agi_skill(call_operation("genomi.describe_context")))
            finally:
                os.chdir(previous)

    def test_existing_personal_dna_artifacts_require_session_approval_after_revoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("sample.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n",
                    encoding="utf-8",
                )
                call_operation("genomi.parse_source", {"source": str(vcf)})
                current = call_operation("genomi.describe_context")
                self.assertTrue(current["has_active_genome_index"])
                self.assertTrue(current["active_genome_index_access"]["approved"])

                call_operation("active_genome_index.revoke_access")
                current_after_revoke = call_operation("genomi.describe_context")
                self.assertTrue(current_after_revoke["has_active_genome_index"])
                self.assertFalse(current_after_revoke["active_genome_index_access"]["approved"])

                with self.assertRaises(OperationError) as raised:
                    call_operation("active_genome_index.summarize")
                self.assertEqual(raised.exception.code, "active_genome_index_approval_required")

                self.approve_access()
                summary = call_operation("active_genome_index.summarize")
                self.assertIn("outputs", summary)
            finally:
                os.chdir(previous)

    def test_approve_access_by_source_reuses_detected_consumer_array_agi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                raw = Path("genome.txt")
                raw.write_text(
                    "# This data file is generated by 23andMe.\n"
                    "# rsid\tchromosome\tposition\tgenotype\n"
                    "rs1\t1\t100\tAA\n",
                    encoding="utf-8",
                )
                parsed = call_operation("genomi.parse_source", {"source": str(raw)})
                agi_id = parsed["active_genome_index"]["agi_id"]
                self.assertTrue(agi_id.startswith("23andme-sha256-"))

                call_operation("active_genome_index.revoke_access")
                approved = call_operation(
                    "active_genome_index.approve_access",
                    {"approved_by_user": True, "source": str(raw)},
                )

                self.assertEqual(approved["active_agi_id"], agi_id)
                current = call_operation("genomi.describe_context")
                self.assertEqual(current["active_agi_id"], agi_id)
                self.assertEqual(current["active_genome_index"]["agi_source_format"], "23andme")
            finally:
                os.chdir(previous)

    def test_remove_active_genome_index_cleans_registry_users_session_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("sample.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n",
                    encoding="utf-8",
                )
                parsed = call_operation(
                    "genomi.parse_source",
                    {"source": str(vcf), "user_nickname": "Alex", "set_default_user": True},
                )
                agi_id = parsed["active_genome_index"]["agi_id"]
                project_dir = self.genomi_home / agi_id
                self.assertTrue(project_dir.exists())
                listed = call_operation("active_genome_index.list")
                self.assertEqual(listed["active"]["agi_id"], agi_id)
                inventory_agi = next(agi for agi in listed["active_genome_indexes"] if agi["agi_id"] == agi_id)
                self.assertIn("source_content_sha256", inventory_agi["hashes"])
                self.assertEqual(inventory_agi["names"]["user_nicknames"], ["Alex"])
                self.assertEqual(inventory_agi["source_references"][0]["kind"], "local_path")
                self.assertTrue(inventory_agi["source_references"][0]["value"].endswith("/sample.vcf"))
                self.assertTrue(any(user["nickname"] == "Alex" for user in listed["users"]))

                removed = call_operation(
                    "active_genome_index.remove",
                    {"agi_id": agi_id, "confirmed_by_user": True},
                )

                self.assertEqual(removed["removed_count"], 1)
                removed_agi = removed["removed"][0]
                self.assertEqual(removed_agi["agi_id"], agi_id)
                self.assertTrue(removed_agi["removed_from_registry"])
                self.assertTrue(removed_agi["removed_from_session"])
                self.assertGreaterEqual(removed_agi["artifact_cleanup"]["removed_count"], 1)
                self.assertFalse(project_dir.exists())
                current = call_operation("genomi.describe_context")
                self.assertFalse(current["has_active_genome_index"])
                self.assertEqual(current["active_genome_index_registry"]["known_agi_count"], 0)
                users = call_operation("active_genome_index.list")["users"]
                self.assertEqual(users[0]["agi_ids"], [])
                self.assertIsNone(users[0]["active_agi_id"])
            finally:
                os.chdir(previous)

    def test_remove_active_genome_index_requires_explicit_confirmation(self) -> None:
        with self.assertRaises(OperationError) as raised:
            call_operation("active_genome_index.remove", {"agi_id": "missing"})
        self.assertEqual(raised.exception.code, "confirmation_required")

    def test_remove_active_genome_index_requires_exact_target_after_confirmation(self) -> None:
        with self.assertRaises(OperationError) as raised:
            call_operation("active_genome_index.remove", {"confirmed_by_user": True})
        self.assertEqual(raised.exception.code, "invalid_params")

    def test_remove_active_genome_index_by_source_cleans_unregistered_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                raw = Path("half.genome")
                raw.write_text("partial", encoding="utf-8")
                project_dir = self.genomi_home / sample_slug_from_source(raw, source_format="genome")
                project_dir.mkdir(parents=True)
                (project_dir / "work").mkdir()
                (project_dir / "work" / "active-genome-index.sqlite").write_text("partial", encoding="utf-8")

                removed = call_operation(
                    "active_genome_index.remove",
                    {"source": str(raw), "confirmed_by_user": True},
                )

                self.assertEqual(removed["removed"][0]["agi_id"], project_dir.name)
                self.assertFalse(project_dir.exists())
                self.assertFalse(call_operation("genomi.describe_context")["has_active_genome_index"])
            finally:
                os.chdir(previous)

    def test_remove_active_genome_index_does_not_delete_mispointed_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                one = Path("one.vcf")
                two = Path("two.vcf")
                one.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tONE\n",
                    encoding="utf-8",
                )
                two.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tTWO\n",
                    encoding="utf-8",
                )
                first = call_operation("genomi.parse_source", {"source": str(one)})
                second = call_operation("genomi.parse_source", {"source": str(two)})
                first_agi_id = first["active_genome_index"]["agi_id"]
                second_agi_id = second["active_genome_index"]["agi_id"]
                second_project_dir = self.genomi_home / second_agi_id
                self.assertTrue(second_project_dir.exists())

                registry = runtime_context.load_registry()
                registry["agis"][first_agi_id]["project_dir"] = str(second_project_dir)
                runtime_context.save_registry(registry)

                removed = call_operation(
                    "active_genome_index.remove",
                    {"agi_id": first_agi_id, "confirmed_by_user": True},
                )

                self.assertEqual(removed["removed"][0]["agi_id"], first_agi_id)
                self.assertTrue(second_project_dir.exists())
                cleanup_entries = removed["removed"][0]["artifact_cleanup"]["entries"]
                self.assertTrue(any(entry["state"] == "outside_expected_agi_project" for entry in cleanup_entries))
            finally:
                os.chdir(previous)

    def test_known_agis_do_not_auto_activate_without_default_in_another_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_one, tempfile.TemporaryDirectory() as cwd_two:
            previous = os.getcwd()
            try:
                os.chdir(cwd_one)
                vcf = Path("sample.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n",
                    encoding="utf-8",
                )
                set_result = call_operation("genomi.parse_source", {"source": str(vcf), "user_nickname": "Alex"})
                agi_id = set_result["active_genome_index"]["agi_id"]
                listed = call_operation("active_genome_index.list")
                self.assertEqual(listed["users"][0]["nickname"], "Alex")
                renamed = call_operation("active_genome_index.rename_user", {"nickname": "Alex", "new_nickname": "Alex Renamed"})
                self.assertEqual(renamed["user"]["nickname"], "Alex Renamed")
                self.assertTrue(call_operation("genomi.describe_context")["has_active_genome_index"])

                os.chdir(cwd_two)
                current = call_operation("genomi.describe_context")
                self.assertFalse(current["has_active_genome_index"])
                self.assertEqual(current["active_genome_index_registry"]["known_agi_count"], 1)

                resumed = call_operation("active_genome_index.approve_access", {"approved_by_user": True, "agi_id": agi_id})
                self.assertEqual(resumed["active_agi_id"], agi_id)
                by_nickname = call_operation("active_genome_index.select_user", {"nickname": "Alex Renamed"})
                self.assertEqual(by_nickname["context"]["active_agi_id"], agi_id)
                self.assertTrue(call_operation("genomi.describe_context")["has_active_genome_index"])
            finally:
                os.chdir(previous)

    def test_context_current_follows_agent_chat_session_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_one, tempfile.TemporaryDirectory() as cwd_two:
            previous = os.getcwd()
            try:
                with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "chat-one"}):
                    os.chdir(cwd_one)
                    vcf = Path("sample.vcf")
                    vcf.write_text(
                        "##fileformat=VCFv4.2\n"
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n",
                        encoding="utf-8",
                    )
                    set_result = call_operation("genomi.parse_source", {"source": str(vcf)})
                    agi_id = set_result["active_genome_index"]["agi_id"]
                    self.assertTrue(call_operation("genomi.describe_context")["has_active_genome_index"])

                    os.chdir(cwd_two)
                    same_chat = call_operation("genomi.describe_context")
                    self.assertTrue(same_chat["has_active_genome_index"])
                    self.assertEqual(same_chat["active_agi_id"], agi_id)

                with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "chat-two"}):
                    other_chat = call_operation("genomi.describe_context")
                    self.assertFalse(other_chat["has_active_genome_index"])
                    self.assertEqual(other_chat["active_genome_index_registry"]["known_agi_count"], 1)
            finally:
                os.chdir(previous)

    def test_default_user_auto_selects_active_genome_index_across_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_one, tempfile.TemporaryDirectory() as cwd_two:
            previous = os.getcwd()
            try:
                os.chdir(cwd_one)
                vcf = Path("sample.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n",
                    encoding="utf-8",
                )
                selected = call_operation("genomi.parse_source", {"source": str(vcf), "user_nickname": "Default user", "set_default_user": True})
                agi_id = selected["active_genome_index"]["agi_id"]

                os.chdir(cwd_two)
                current = call_operation("genomi.describe_context")
                self.assertTrue(current["has_active_genome_index"])
                self.assertEqual(current["active_agi_id"], agi_id)
                self.assertTrue(current["default_auto_selected"])
                self.assertEqual(current["active_genome_index_access"]["scope"], "persistent_default")
                cleared = call_operation("active_genome_index.clear_default_user")
                self.assertTrue(cleared["cleared_default"])
                self.assertFalse(call_operation("genomi.describe_context")["has_active_genome_index"])
            finally:
                os.chdir(previous)

    def test_vcf_tool_without_context_fails_actionably(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                with self.assertRaises(OperationError) as raised:
                    call_operation("active_genome_index.summarize")
                self.assertEqual(raised.exception.code, "missing_context")
            finally:
                os.chdir(previous)

    def test_non_vcf_evidence_tools_can_use_shared_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                result = call_operation("research.search", {"query": "brca"})
                self.assertEqual(result["query"]["source"], "research_findings")
                self.assertEqual(result["count"], 0)
                self.assertTrue((self.genomi_home / "shared-evidence.sqlite").exists())
            finally:
                os.chdir(previous)

    def test_search_indexes_does_not_search_active_metadata_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.vcf"
            source.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n",
                encoding="utf-8",
            )
            runtime_context.set_active_agi_from_source(
                source,
                status="parsed",
                agi_path=source.with_suffix(".sqlite"),
                genome_build="GRCh38",
            )

            blocked = call_operation(
                "genomi.search_indexes",
                {"query": "GRCh38", "include_private_metadata": True},
            )
            self.assertEqual(blocked["private_metadata"]["status"], "active_genome_index_approval_required")

            runtime_context.approve_agi_access(reason="test approved Active Genome Index metadata access")
            allowed = call_operation(
                "genomi.search_indexes",
                {"query": "GRCh38", "include_private_metadata": True},
            )
            self.assertEqual(allowed["private_metadata"]["status"], "included")
            self.assertEqual(allowed["search_results"][-1]["source"], "active_genome_index_metadata")
            self.assertEqual(allowed["search_results"][-1]["hits"][0]["metadata"]["genome_build"], "GRCh38")

    def test_context_normalization_preserves_canonical_agi_metadata(self) -> None:
        runtime_context.save_context(
            {
                "active_agi_id": "canonical-agi",
                "agis": {
                    "canonical-agi": {
                        "agi_id": "canonical-agi",
                        "sample_slug": "canonical-agi",
                        "status": "parsed",
                        "agi_intake_source_path": "/tmp/canonical-source.vcf",
                        "agi_source_format": "vcf",
                        "agi_source_kind": "variant_callset",
                        "agi_source_member": "canonical-source.vcf",
                        "agi_path": "/tmp/canonical-active-genome-index.sqlite",
                    }
                },
            }
        )

        current = call_operation("genomi.describe_context")
        active = current["active_genome_index"]

        self.assertEqual(active["agi_id"], "canonical-agi")
        self.assertEqual(active["agi_source_format"], "vcf")
        self.assertEqual(active["agi_source_kind"], "variant_callset")
        self.assertEqual(active["agi_source_member"], "canonical-source.vcf")
        self.assertEqual(active["intake_source"]["role"], "ingestion_source_for_digitization")
        self.assertFalse(active["intake_source"]["available_for_rebuild"])

    def test_record_research_accepts_inline_payload_for_shared_evidence(self) -> None:
        payload = {
            "target": {"type": "drug", "drug": "clopidogrel"},
            "source": {
                "title": "CPIC clopidogrel guideline",
                "url": "https://cpicpgx.org/guidelines/",
                "type": "pharmacogenomic_guideline",
            },
            "finding": {
                "type": "clinpgx_guideline_annotation",
                "text": "CPIC clopidogrel and CYP2C19 source context.",
                "summary": "CPIC clopidogrel guidance.",
            },
            "captured_by": "test",
        }

        result = call_operation("research.record", {"payload": payload, "scope": "shared"})
        queried = call_operation("research.query", {"target_type": "drug", "drug": "clopidogrel"})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["scope"], "shared")
        self.assertEqual(result["shared_sync"]["status"], "same_db")
        self.assertEqual(Path(result["evidence_db"]), self.genomi_home / "shared-evidence.sqlite")
        self.assertEqual(queried["count"], 1)
        self.assertEqual(queried["records"][0]["scope"], "shared")
        self.assertEqual(queried["records"][0]["finding"]["type"], "clinpgx_guideline_annotation")

    def test_private_inline_research_requires_private_evidence_db(self) -> None:
        payload = {
            "target": {"type": "gene", "gene": "CYP2C19"},
            "source": {
                "title": "PharmCAT sample PGx call artifact",
                "url": "https://pharmcat.clinpgx.org/",
                "type": "sample_pharmacogenomic_call",
            },
            "finding": {
                "type": "pharmcat_sample_pgx_call",
                "text": "PharmCAT call for CYP2C19; diplotype *1/*2.",
                "summary": "CYP2C19 *1/*2.",
            },
            "captured_by": "test",
        }

        with self.assertRaises(OperationError) as raised:
            call_operation("research.record", {"payload": payload, "scope": "private"})
        self.assertEqual(raised.exception.code, "missing_context")

        with tempfile.TemporaryDirectory() as tmp:
            private_db = Path(tmp) / "private.sqlite"
            result = call_operation(
                "research.record",
                {"db": str(private_db), "payload": payload, "scope": "private", "sync_shared": False},
            )
            queried = call_operation(
                "research.query",
                {"db": str(private_db), "target_type": "gene", "gene": "CYP2C19", "scope": "private"},
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["scope"], "private")
        self.assertEqual(result["shared_sync"]["status"], "disabled")
        self.assertEqual(queried["count"], 1)
        self.assertEqual(queried["records"][0]["scope"], "private")
