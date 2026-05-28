from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from genomi.active_genome_index.active_genome_index import create_active_genome_index
from genomi.evidence import init_evidence_db
from genomi.operations import call_operation
from genomi.runtime import context as runtime_context

from _genomi_runtime_helpers import GenomiRuntimeTestCase


class GenomiRuntimeVariantTests(GenomiRuntimeTestCase):
    def test_variant_lookup_reads_shared_clinvar_by_rsid(self) -> None:
        shared_db = self.genomi_home / "shared-evidence.sqlite"
        init_evidence_db(shared_db)
        with sqlite3.connect(shared_db) as connection:
            rowid = connection.execute(
                """
                insert into clinvar_variants(
                    chrom, pos, ref, alt, genome_build, clinvar_id, allele_id,
                    clinical_significance, review_status, conditions, gene_info,
                    hgvs, raw_info_json, source_path, source_version, imported_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "1",
                    123,
                    "A",
                    "G",
                    "GRCh38",
                    "VCV000001",
                    "CA1",
                    "Pathogenic",
                    "reviewed by expert panel",
                    "Example condition",
                    "GENE1:1",
                    "NC_000001.11:g.123A>G",
                    "{}",
                    "clinvar.vcf.gz",
                    "test",
                    "2026-01-01T00:00:00Z",
                ),
            ).lastrowid
            connection.execute(
                "insert into clinvar_variant_rsids(rsid, variant_rowid, genome_build) values (?, ?, ?)",
                ("rs123", rowid, "GRCh38"),
            )

        result = call_operation("variant.resolve", {"query": "What is known about RS123?", "shared_db": str(shared_db)})

        self.assertEqual(result["schema"], "genomi-variant-lookup-v1")
        self.assertEqual(result["resolved_targets"][0]["rsid"], "rs123")
        self.assertEqual(len(result["public_context"]["clinvar_by_rsid"]), 1)
        self.assertEqual(result["public_context"]["clinvar_by_rsid"][0]["clinical_significance"], "Pathogenic")
        self.assertTrue(any(target["target_type"] == "allele" for target in result["resolved_targets"]))

    def test_variant_lookup_questions_cover_missing_target_and_context(self) -> None:
        no_target = call_operation("variant.resolve", {})

        unresolved = {item["component"]: item for item in no_target["unanswered_answer_components"]}
        self.assertEqual(unresolved["target_resolution"]["state"], "missing")
        self.assertIn("query", unresolved["target_resolution"]["missing_inputs"])

        no_context = call_operation("variant.resolve", {"rsid": "rs999999"})

        unanswered = {item["component"]: item for item in no_context["unanswered_answer_components"]}
        self.assertEqual(unanswered["sample_context"]["state"], "unselected")
        self.assertEqual(unanswered["public_context"]["state"], "absent")
        self.assertIn("source_document", unanswered["public_context"]["missing_inputs"])

    def test_variant_lookup_checks_active_and_explicit_known_parsed_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("sample.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n"
                    "1\t100\trs555\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                    encoding="utf-8",
                )
                index = Path("active-genome-index.sqlite")
                create_active_genome_index(vcf, index, reuse_existing=False)
                db = Path("evidence.sqlite")

                call_operation(
                    "active_genome_index.assign_user_genome",
                    {"nickname": "Test user", "source": str(vcf), "active_genome_index_path": str(index), "db": str(db), "genome_build": "GRCh38"},
                )
                active_result = call_operation("variant.resolve", {"rsid": "rs555"})

                self.assertEqual(active_result["sample_context"]["count"], 1)
                self.assertEqual(active_result["sample_context"]["matches"][0]["genotype"], "0/1")
                self.assertNotIn(str(vcf.resolve(strict=False)), json.dumps(active_result))

                agi_id = active_result["sample_context"]["searched_active_genome_indexes"][0]["agi_id"]
                call_operation("active_genome_index.clear_selection")
                public_only = call_operation("variant.resolve", {"rsid": "rs555"})
                self.assertEqual(public_only["sample_context"]["searched_active_genome_indexes"], [])
                self.assertEqual(public_only["sample_context"]["count"], 0)

                call_operation("active_genome_index.approve_access", {"approved_by_user": True, "agi_id": agi_id})
                known_result = call_operation("variant.resolve", {"rsid": "rs555", "agi_id": agi_id})
                self.assertEqual(known_result["sample_context"]["count"], 1)
                self.assertEqual(known_result["sample_context"]["searched_active_genome_indexes"][0]["selection"], "explicit_active_genome_index")
                self.assertNotIn(str(vcf.resolve(strict=False)), json.dumps(known_result))

                all_known = call_operation(
                    "variant.resolve",
                    {"rsid": "rs555", "include_known_active_genome_indexes": True, "include_active_genome_index": False},
                )
                self.assertEqual(all_known["sample_context"]["count"], 1)
                self.assertEqual(all_known["sample_context"]["searched_active_genome_indexes"][0]["selection"], "known_active_genome_index")
                self.assertTrue(all_known["sample_context"]["searched_known_active_genome_indexes"])
            finally:
                os.chdir(previous)

    def test_variant_lookup_marks_incomplete_vcf_index_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("sample.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n"
                    "1\t100\trs555\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                    encoding="utf-8",
                )
                index = Path("active-genome-index.sqlite")
                create_active_genome_index(vcf, index, reuse_existing=False)
                with sqlite3.connect(index) as connection:
                    connection.execute(
                        "update metadata set value = ? where key = 'active_genome_index_complete'",
                        (json.dumps(False),),
                    )
                    connection.commit()

                call_operation(
                    "active_genome_index.assign_user_genome",
                    {"nickname": "Test user", "source": str(vcf), "active_genome_index_path": str(index), "genome_build": "GRCh38"},
                )
                current = call_operation("genomi.describe_context")
                lookup = call_operation("variant.resolve", {"rsid": "rs555"})

                self.assertFalse(current["active_genome_index"]["digitized"])
                self.assertFalse(current["active_genome_index"]["active_genome_index_readiness"]["complete"])
                self.assertEqual(lookup["sample_context"]["count"], 0)
                searched = lookup["sample_context"]["searched_active_genome_indexes"][0]
                self.assertFalse(searched["query_available"])
                self.assertEqual(searched["availability_note"], "completion_marker_missing_or_false")
                self.assertTrue(any("not complete" in warning for warning in lookup["warnings"]))
            finally:
                os.chdir(previous)

    def test_variant_lookup_exact_allele_returns_sample_population_and_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("sample.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n"
                    "1\t100\trs555\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                    encoding="utf-8",
                )
                index = Path("active-genome-index.sqlite")
                create_active_genome_index(vcf, index, reuse_existing=False)
                db = Path("evidence.sqlite")
                init_evidence_db(db)
                with sqlite3.connect(db) as connection:
                    connection.execute(
                        """
                        insert into population_frequencies(
                            chrom, pos, ref, alt, genome_build, source, source_version,
                            population, allele_count, allele_number, allele_frequency,
                            homozygote_count, raw_info_json, source_path, imported_at
                        )
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "1",
                            100,
                            "A",
                            "G",
                            "GRCh38",
                            "gnomad_r4",
                            "test",
                            "global",
                            4,
                            1000,
                            0.004,
                            0,
                            "{}",
                            "gnomad.vcf.gz",
                            "2026-01-01T00:00:00Z",
                        ),
                    )
                    connection.execute(
                        """
                        insert into genotype_support(
                            vcf_path, chrom, pos, ref, alt, genome_build, support_status,
                            evidence_class, genotype, zygosity, depth, genotype_quality,
                            filter, raw_json, created_at
                        )
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(vcf.resolve(strict=False)),
                            "1",
                            100,
                            "A",
                            "G",
                            "GRCh38",
                            "supported",
                            "sample_observation",
                            "0/1",
                            "heterozygous",
                            31,
                            99,
                            "PASS",
                            "{}",
                            "2026-01-01T00:00:00Z",
                        ),
                    )

                call_operation(
                    "active_genome_index.assign_user_genome",
                    {"nickname": "Test user", "source": str(vcf), "active_genome_index_path": str(index), "db": str(db), "genome_build": "GRCh38"},
                )
                result = call_operation("variant.resolve", {"query": "chr1:100:A:G"})

                self.assertEqual(result["sample_context"]["count"], 1)
                self.assertEqual(result["sample_context"]["matches"][0]["rsid"], "rs555")
                self.assertEqual(len(result["public_context"]["population_frequencies"]), 1)
                self.assertEqual(result["public_context"]["population_frequencies"][0]["allele_frequency"], 0.004)
                self.assertEqual(len(result["support_context"]["genotype_support"]), 1)
                self.assertEqual(result["support_context"]["genotype_support"][0]["support_status"], "supported")
                self.assertNotIn(str(vcf.resolve(strict=False)), json.dumps(result))
            finally:
                os.chdir(previous)

    def test_resources_list_exposes_public_resources_without_active_indexes(self) -> None:
        result = call_operation("genomi.list_resources")

        self.assertEqual(result["schema"], "genomi-resource-catalog-v1")
        self.assertIn("resource_groups", result)
        self.assertIn("source_adapters", [group["id"] for group in result["resource_groups"]])
        self.assertNotIn("active_genome_index", [group["id"] for group in result["resource_groups"]])
        resource_groups = {group["id"]: group for group in result["resource_groups"]}
        self.assertIn("pharmacogenomics", resource_groups)
        pgx_resources = {resource["id"]: resource for resource in resource_groups["pharmacogenomics"]["resources"]}
        self.assertEqual(pgx_resources["pgx_capability_inventory"]["capabilities"]["schema"], "genomi-pgx-capabilities-v1")
        self.assertIn("broad_vcf_pgx_calling", pgx_resources["pgx_capability_inventory"]["capabilities"]["capability_axes"])
        self.assertIn("source_catalog", result)
        self.assertIn("context_policy", result)
        self.assertFalse(result["context_policy"]["active_genome_index_context_listed"])
        self.assertNotIn("context", result)
        self.assertNotIn("context_axes", result)
        self.assertNotIn("known_active_genome_indexes", result)

        vcf = Path("sample.vcf")
        vcf.write_text(
            "##fileformat=VCFv4.2\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n",
            encoding="utf-8",
        )
        set_result = call_operation("active_genome_index.assign_user_genome", {"nickname": "Test user", "source": str(vcf)})
        hidden = call_operation("genomi.list_resources")
        hidden_text = json.dumps(hidden)
        self.assertNotIn(set_result["context"]["active_agi_id"], hidden_text)
        self.assertNotIn("active_genome_index", [group["id"] for group in hidden["resource_groups"]])

    def test_sources_list_exposes_agent_review_contracts(self) -> None:
        result = call_operation("research.list_sources", {"target_type": "drug"})
        by_id = {source["source_id"]: source for source in result["sources"]}

        self.assertIn("pgxdb", by_id)
        self.assertIn("pharmgkb", by_id)
        self.assertIn("cpic", by_id)
        self.assertEqual(by_id["pgxdb"]["agent_contract"]["query_mode"], "implemented_operation")
        self.assertTrue(by_id["pgxdb"]["agent_contract"]["use_implemented_adapter_first"])
        self.assertEqual(by_id["pharmgkb"]["agent_contract"]["query_mode"], "implemented_operation")
        self.assertTrue(by_id["pharmgkb"]["agent_contract"]["use_implemented_adapter_first"])
        self.assertIn("pharmacogenomics.fetch_clinpgx", by_id["cpic"]["agent_contract"]["available_operations"])
        self.assertNotIn("operation_sequence", by_id["cpic"]["agent_contract"])
        self.assertIn("DrugBank ID", by_id["pgxdb"]["agent_contract"]["public_target_inputs"])

    def test_direct_public_evidence_tools_remain_available_without_vcf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                current = call_operation("genomi.describe_context")
                self.assertFalse(current["has_active_genome_index"])

                packet = call_operation("research.build_target_packet", {"target_type": "topic", "topic": "rs429358"})
                self.assertEqual(packet["target"]["target_type"], "topic")
                self.assertEqual(packet["target"]["topic"], "rs429358")
                self.assertIn("stored_research", packet)
                self.assertIn("source_catalog", packet)
            finally:
                os.chdir(previous)

    def test_parsed_context_hides_intake_vcf_path_from_agent_runtime(self) -> None:
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
                index = Path(".genomi-data/na12878/work/active-genome-index.sqlite")
                matches = Path(".genomi-data/na12878/work/clinvar.matches.jsonl")
                evidence_db = Path(".genomi-data/na12878/evidence/evidence.sqlite")
                index.parent.mkdir(parents=True, exist_ok=True)
                create_active_genome_index(vcf, index)
                for path in (matches, evidence_db):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("", encoding="utf-8")
                runtime_context.set_active_genome_index(
                    vcf,
                    status="parsed",
                    operation_result={
                        "sample_slug": "na12878",
                        "vcf": str(vcf),
                        "evidence_db": str(evidence_db),
                        "outputs": {"active_genome_index_path": str(index), "clinvar_matches": str(matches)},
                    },
                )

                current = call_operation("genomi.describe_context")
                active = current["active_genome_index"]
                self.assertTrue(active["digitized"])
                self.assertNotIn("vcf", active)
                self.assertTrue(active["intake_source"]["hidden_after_digitization"])
                self.assertNotIn(str(vcf.resolve()), json.dumps(current))
            finally:
                os.chdir(previous)

if __name__ == "__main__":
    import unittest

    unittest.main()
