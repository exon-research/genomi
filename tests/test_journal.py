from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.operations import OperationError, call_operation, list_operations
from genomi.runtime import context as runtime_context


class JournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._home_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._home_tmp.cleanup)
        self._cwd_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._cwd_tmp.cleanup)
        self._previous_cwd = os.getcwd()
        os.chdir(self._cwd_tmp.name)
        self.addCleanup(os.chdir, self._previous_cwd)
        self.genomi_home = Path(self._home_tmp.name) / "genomi-home"
        self._env = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(self.genomi_home),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._env.start()
        self.addCleanup(self._env.stop)

    def approve_agi_access(self) -> None:
        vcf = Path("journal-sample.vcf")
        if not vcf.exists():
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n",
                encoding="utf-8",
            )
        if not call_operation("genomi.describe_context").get("active_agi_id"):
            call_operation("genomi.parse_source", {"source": str(vcf)})
        call_operation(
            "active_genome_index.approve_access",
            {"approved_by_user": True, "reason": "test approved Active Genome Index access"},
        )

    def test_appending_session_and_project_entries_creates_notebooks(self) -> None:
        session = call_operation(
            "journal.append_entry",
            {
                "scope": "session",
                "entry_type": "observation",
                "content": "APOE evidence needs a source refresh.",
                "tags": ["apoe", "triage"],
                "target": {"gene": "APOE"},
            },
        )
        project = call_operation(
            "journal.append_entry",
            {
                "scope": "project",
                "entry_type": "plan",
                "content": "Use public target evidence before any report wording.",
                "tags": ["workflow"],
            },
        )

        self.assertEqual(session["notebook"]["scope"], "session")
        self.assertEqual(project["notebook"]["scope"], "project")
        self.assertEqual(session["entry"]["decision_status"], "unresolved")
        self.assertTrue(session["entry"]["entry_id"].startswith("entry_"))
        self.assertTrue(project["entry"]["entry_id"].startswith("entry_"))

    def test_evidence_links_preserve_traceability_fields(self) -> None:
        created = call_operation(
            "journal.append_entry",
            {
                "scope": "session",
                "entry_type": "decision",
                "content": "Use the GWAS Catalog comparator for the LDL variant question.",
                "decision_status": "supported",
                "evidence_links": [
                    {
                        "operation": "gwas.compare_variant_associations",
                        "evidence_id": "GCST-1",
                        "coverage_state": "covered",
                        "input_digest": "in-digest",
                        "output_digest": "out-digest",
                        "source_url": "https://example.test/gwas",
                    }
                ],
            },
        )

        linked = call_operation(
            "journal.append_entry",
            {
                "entry_id": created["entry"]["entry_id"],
                "evidence_links": [
                    {
                        "operation": "research.build_target_packet",
                        "evidence_id": "packet-1",
                        "finding_id": "finding-1",
                        "coverage_state": "partial",
                        "input_digest": "packet-in",
                        "output_digest": "packet-out",
                    }
                ],
            },
        )

        by_operation = {link["operation"]: link for link in linked["entry"]["evidence_links"]}
        self.assertEqual(by_operation["gwas.compare_variant_associations"]["evidence_id"], "GCST-1")
        self.assertEqual(by_operation["gwas.compare_variant_associations"]["coverage_state"], "covered")
        self.assertEqual(by_operation["gwas.compare_variant_associations"]["input_digest"], "in-digest")
        self.assertEqual(by_operation["gwas.compare_variant_associations"]["output_digest"], "out-digest")
        self.assertEqual(by_operation["research.build_target_packet"]["finding_id"], "finding-1")

    def test_project_journal_rejects_private_sample_evidence_links(self) -> None:
        with self.assertRaises(OperationError) as raised:
            call_operation(
                "journal.append_entry",
                {
                    "scope": "project",
                    "entry_type": "observation",
                    "content": "Sample callability was checked.",
                    "evidence_links": [
                        {
                            "operation": "active_genome_index.classify_genotype_support",
                            "evidence_id": "sample-support-1",
                        }
                    ],
                },
            )
        self.assertEqual(raised.exception.code, "private_evidence_not_allowed")

    def test_session_private_links_require_approval(self) -> None:
        with self.assertRaises(OperationError) as raised:
            call_operation(
                "journal.append_entry",
                {
                    "scope": "session",
                    "entry_type": "observation",
                    "content": "Sample callability was checked.",
                    "evidence_links": [{"operation": "active_genome_index.classify_genotype_support"}],
                },
            )
        self.assertEqual(raised.exception.code, "active_genome_index_approval_required")

        self.approve_agi_access()
        result = call_operation(
            "journal.append_entry",
            {
                "scope": "session",
                "entry_type": "observation",
                "content": "Sample callability was checked.",
                "evidence_links": [{"operation": "active_genome_index.classify_genotype_support", "evidence_id": "support-1"}],
            },
        )
        self.assertEqual(result["entry"]["evidence_links"][0]["evidence_id"], "support-1")

    def test_amendments_append_without_overwriting_original_entry(self) -> None:
        created = call_operation(
            "journal.append_entry",
            {
                "entry_type": "summary",
                "content": "Initial summary mentions BRCA1 only.",
                "decision_status": "unsupported",
            },
        )
        amended = call_operation(
            "journal.append_entry",
            {
                "entry_id": created["entry"]["entry_id"],
                "amendment_type": "correction",
                "content": "The summary should mention BRCA2 as an unresolved follow-up.",
                "rationale": "Later source review added a second target.",
            },
        )

        self.assertEqual(amended["entry"]["content"], "Initial summary mentions BRCA1 only.")
        self.assertEqual(len(amended["entry"]["amendments"]), 1)
        self.assertEqual(amended["entry"]["amendments"][0]["amendment_type"], "correction")

    def test_search_returns_entries_by_token_tag_target_and_type(self) -> None:
        call_operation(
            "journal.append_entry",
            {
                "entry_type": "hypothesis",
                "content": "APOE lipid evidence may conflict with dementia framing.",
                "tags": ["lipids", "apoe"],
                "target": {"gene": "APOE", "phenotype": "LDL cholesterol"},
                "decision_status": "unresolved",
            },
        )
        call_operation(
            "journal.append_entry",
            {
                "entry_type": "protocol_note",
                "content": "Use pharmacogenomics review for clopidogrel.",
                "tags": ["pgx"],
                "target": {"drug": "clopidogrel"},
            },
        )

        token = call_operation("journal.search_entries", {"text": "dementia"})
        tag = call_operation("journal.search_entries", {"tag": "apoe"})
        target = call_operation("journal.search_entries", {"target": {"gene": "APOE"}})
        typed = call_operation("journal.search_entries", {"entry_type": "protocol_note"})

        self.assertEqual(token["count"], 1)
        self.assertEqual(tag["count"], 1)
        self.assertEqual(target["count"], 1)
        self.assertEqual(typed["entries"][0]["target"]["drug"], "clopidogrel")

    def test_search_uses_host_semantic_terms_as_retrieval_hints(self) -> None:
        call_operation(
            "journal.append_entry",
            {
                "entry_type": "protocol_note",
                "content": "Use pharmacogenomics review for clopidogrel after PCI.",
                "tags": ["pgx"],
                "target": {"drug": "clopidogrel"},
            },
        )

        result = call_operation(
            "journal.search_entries",
            {
                "query": "blood thinner after stent",
                "semantic_context": {
                    "raw_query": "blood thinner after stent",
                    "host_expansions": ["clopidogrel", "CYP2C19 antiplatelet response"],
                    "host_entities": [{"text": "clopidogrel", "type": "drug"}],
                },
            },
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["entries"][0]["target"]["drug"], "clopidogrel")
        self.assertIn("clopidogrel", {item["text"] for item in result["semantic_context"]["term_matches"]})

    def test_summary_groups_investigation_state(self) -> None:
        call_operation("journal.append_entry", {"entry_type": "observation", "content": "Observation A", "decision_status": "unsupported"})
        call_operation("journal.append_entry", {"entry_type": "decision", "content": "Decision A", "decision_status": "supported", "evidence_links": [{"operation": "research.build_target_packet"}]})
        call_operation("journal.append_entry", {"entry_type": "contradiction", "content": "Contradiction A", "decision_status": "unresolved"})
        call_operation("journal.append_entry", {"entry_type": "unresolved_question", "content": "Question A"})

        summary = call_operation("journal.summarize")

        self.assertEqual(summary["entry_count"], 4)
        self.assertEqual(summary["summary"]["key_observations"][0]["content"], "Observation A")
        self.assertEqual(summary["summary"]["decisions"][0]["content"], "Decision A")
        self.assertEqual(summary["summary"]["contradictions"][0]["content"], "Contradiction A")
        self.assertTrue(summary["summary"]["unresolved_questions"])
        self.assertEqual(summary["summary"]["most_used_evidence_sources"][0]["source"], "research.build_target_packet")

    def test_export_returns_memos_shaped_json_without_memos_and_omits_private_links(self) -> None:
        self.approve_agi_access()
        call_operation(
            "journal.append_entry",
            {
                "entry_type": "decision",
                "content": "Keep private sample evidence in session journal only.",
                "decision_status": "supported",
                "evidence_links": [
                    {"operation": "active_genome_index.classify_genotype_support", "evidence_id": "private-support"},
                    {"operation": "research.build_target_packet", "evidence_id": "public-packet"},
                ],
            },
        )
        call_operation("active_genome_index.revoke_access")

        artifact = call_operation("journal.export_memory")

        self.assertEqual(artifact["schema"], "genomi-journal-memory-artifact-v1")
        self.assertEqual(artifact["format"], "memos-compatible-json")
        self.assertEqual(artifact["memories"][0]["memory_type"], "decision_memory")
        metadata = artifact["memories"][0]["metadata"]
        self.assertEqual(metadata["private_evidence_omitted_count"], 1)
        self.assertEqual(metadata["evidence_links"][0]["evidence_id"], "public-packet")

    def test_mutation_responses_redact_private_links_after_access_revoke(self) -> None:
        self.approve_agi_access()
        created = call_operation(
            "journal.append_entry",
            {
                "entry_type": "decision",
                "content": "Private evidence is linked while access is approved.",
                "decision_status": "supported",
                "evidence_links": [
                    {
                        "operation": "active_genome_index.classify_genotype_support",
                        "evidence_id": "private-support",
                        "linked_payload": {"sample": "NA12878"},
                    }
                ],
            },
        )
        call_operation("active_genome_index.revoke_access")

        amended = call_operation(
            "journal.append_entry",
            {
                "entry_id": created["entry"]["entry_id"],
                "content": "Correction after access was revoked.",
                "evidence_links": [{"operation": "research.build_target_packet", "evidence_id": "public-packet"}],
            },
        )

        amended_text = json.dumps(amended, sort_keys=True)
        self.assertNotIn("private-support", amended_text)
        self.assertNotIn("NA12878", amended_text)
        self.assertTrue(amended["entry"]["evidence_links"][0]["private_evidence_omitted"])
        self.assertEqual(amended["entry"]["evidence_links"][1]["evidence_id"], "public-packet")

    def test_operation_metadata_exposes_journal_namespace(self) -> None:
        default_names = {tool["name"] for tool in list_operations()}
        self.assertIn("journal.append_entry", default_names)
        self.assertIn("journal.search_entries", default_names)

        by_name = {tool["name"]: tool for tool in list_operations()}
        append = by_name["journal.append_entry"]["annotations"]
        search = by_name["journal.search_entries"]["annotations"]
        export = by_name["journal.export_memory"]["annotations"]

        self.assertEqual(append["area"], "journal")
        self.assertEqual(search["area"], "journal")
        self.assertEqual(export["area"], "journal")
        self.assertEqual(append["operationScope"], "write")
        self.assertTrue(append["mutating"])
        self.assertEqual(append["privacyScope"], "local_private")
        self.assertEqual(append["toolCapability"], "journal")
        self.assertEqual(append["discoveryRole"], "entry_tool")
        self.assertEqual(search["operationScope"], "read")
        self.assertFalse(search["mutating"])
        self.assertEqual(search["discoveryRole"], "entry_tool")
        self.assertEqual(export["operationScope"], "read")
        self.assertFalse(export["mutating"])


if __name__ == "__main__":
    unittest.main()
