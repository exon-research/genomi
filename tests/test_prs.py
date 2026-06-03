from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.active_genome_index.active_genome_index import create_active_genome_index, default_active_genome_index_path
from genomi.capabilities.prs import harmonize as prs_harmonize
from genomi.capabilities.prs import pgs_catalog as prs_pgs_catalog
from genomi.capabilities.prs import scorer as prs_scorer
from genomi.operations import OperationError, call_operation, list_operations
from genomi.runtime import context as runtime_context
from genomi.runtime.liftover import chain_file_path, liftover_preflight


class PolygenicScoreCapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._home_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._home_tmp.cleanup)
        self.genomi_home = Path(self._home_tmp.name) / "genomi-home"
        self._env = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(self.genomi_home),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "",
                "GENOMI_MCP_BACKGROUND": "0",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_public_tools_do_not_require_personal_approval(self) -> None:
        source_context = call_operation("prs.build_source_context")
        imported = call_operation("prs.list_imported_scores")

        self.assertEqual(source_context["status"], "completed")
        self.assertIn("raw weighted score", " ".join(source_context["method_boundaries"]["does"]).lower())
        self.assertEqual(imported["status"], "completed")
        self.assertEqual(imported["score_count"], 0)

    def test_search_scores_uses_host_semantic_terms_without_hardcoded_synonyms(self) -> None:
        rows = [
            self._pgs_metadata_row(
                pgs_id="PGS001987",
                name="portability-PLR_M_less_hair",
                reported_trait="Hair/balding pattern",
                mapped_trait_labels="balding measurement",
                mapped_trait_ids="EFO_0007825",
                variant_count="23692",
            ),
            self._pgs_metadata_row(
                pgs_id="PGS900010",
                name="lipids-ldl",
                reported_trait="LDL cholesterol",
                mapped_trait_labels="low density lipoprotein cholesterol measurement",
                mapped_trait_ids="EFO_0004611",
            ),
            self._pgs_metadata_row(
                pgs_id="PGS900011",
                name="hair-color",
                reported_trait="Hair color",
                mapped_trait_labels="hair color measurement",
                mapped_trait_ids="EFO_0007824",
            ),
        ]

        with mock.patch.object(prs_pgs_catalog, "_fetch_score_metadata_rows", return_value=rows):
            result = call_operation(
                "prs.search_scores",
                {
                    "query": "will I go bald",
                    "limit": 3,
                    "semantic_context": {
                        "raw_query": "will I go bald",
                        "host_expansions": ["male pattern baldness", "androgenetic alopecia", "hair loss"],
                        "host_entities": [
                            {"text": "androgenetic alopecia", "type": "trait_or_condition"}
                        ],
                    },
                },
            )

        self.assertEqual(result["status"], "completed")
        self.assertIn(result["retrieval"]["model"], {"hybrid_bm25_rrf_v1", "persistent_sqlite_fts5_bm25_rrf_v1"})
        self.assertFalse(result["retrieval"]["semantic_query_model"]["hardcoded_synonyms"])
        self.assertEqual(result["results"][0]["pgs_id"], "PGS001987")
        self.assertEqual(result["results"][0]["mapped_trait_ids"], "EFO_0007825")
        semantic_context = result["semantic_context"]
        self.assertEqual(semantic_context["schema"], "genomi-semantic-retrieval")
        self.assertEqual(
            {
                "schema",
                "raw_query",
                "host_expansions",
                "host_entities",
                "term_matches",
                "term_misses",
                "ignored_hints",
                "retrieval_streams",
                "retrieval_boundary",
            },
            set(semantic_context),
        )
        matches = {item["text"] for item in semantic_context["term_matches"]}
        misses = {item["text"] for item in semantic_context["term_misses"]}
        self.assertIn("male pattern baldness", matches)
        self.assertIn("androgenetic alopecia", misses)
        self.assertTrue(all(item["status"] == "hit" for item in semantic_context["term_matches"]))
        self.assertTrue(all(item["status"] in {"miss", "ignored_for_exact_identifier"} for item in semantic_context["term_misses"]))

    def test_search_scores_filters_by_efo_trait_id(self) -> None:
        rows = [
            self._pgs_metadata_row(
                pgs_id="PGS001987",
                reported_trait="Hair/balding pattern",
                mapped_trait_labels="balding measurement",
                mapped_trait_ids="EFO_0007825",
            ),
            self._pgs_metadata_row(
                pgs_id="PGS900010",
                reported_trait="LDL cholesterol",
                mapped_trait_labels="low density lipoprotein cholesterol measurement",
                mapped_trait_ids="EFO_0004611",
            ),
        ]

        with mock.patch.object(prs_pgs_catalog, "_fetch_score_metadata_rows", return_value=rows):
            result = call_operation("prs.search_scores", {"efo_id": "EFO:0007825", "limit": 5})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"]["matched_count"], 1)
        self.assertEqual([item["pgs_id"] for item in result["results"]], ["PGS001987"])

    def test_search_scores_refreshes_public_retrieval_index(self) -> None:
        rows = [
            self._pgs_metadata_row(
                pgs_id="PGS001987",
                reported_trait="Hair/balding pattern",
                mapped_trait_labels="balding measurement",
                mapped_trait_ids="EFO_0007825",
            )
        ]

        with mock.patch.object(prs_pgs_catalog, "_fetch_score_metadata_rows", return_value=rows):
            call_operation("prs.search_scores", {"query": "balding", "limit": 1})

        listed = call_operation("genomi.search_indexes", {"source": "pgs_scores", "query": "balding"})
        self.assertEqual(listed["search_results"][0]["source"], "pgs_scores")
        self.assertEqual(listed["search_results"][0]["hits"][0]["doc_id"], "PGS001987")

    def test_private_tools_require_approval_for_existing_active_context(self) -> None:
        vcf = Path(self._home_tmp.name) / "sample.vcf"
        runtime_context.set_active_genome_index(
            vcf,
            status="parsed",
            active_genome_index_path=vcf.with_suffix(".sqlite"),
            genome_build="GRCh38",
        )

        with self.assertRaises(OperationError) as raised:
            call_operation("prs.calculate_score", {"pgs_id": "PGS900001"})
        self.assertEqual(raised.exception.code, "active_genome_index_approval_required")

    def test_supplied_source_returns_requires_score_import_with_defaults(self) -> None:
        result = call_operation("prs.calculate_score", {"source": "sample.vcf", "pgs_id": "PGS900001"})

        self.assertEqual(result["status"], "requires_score_import")
        self.assertTrue(result["personal_context"]["uses_personal_dna"])
        self.assertEqual(result["missing_library"]["library"], "PGS900001")
        self.assertEqual(result["missing_library"]["status"], "not_installed")
        self.assertIn("genomi call prs.import_scoring_file", result["ask_user"]["install_command"])
        self.assertIn("PGS900001", result["ask_user"]["question"])
        envelope = result["evidence_envelope"]
        self.assertEqual(envelope["finding_state"], "blocked_missing_library")
        self.assertEqual(envelope["answer_readiness"], "needs_user_install")
        self.assertEqual(envelope["coverage"]["libraries"][0]["library"], "PGS900001")
        self.assertIn("genomi call prs.import_scoring_file", envelope["coverage"]["libraries"][0]["install_command"])
        defaults = {item["parameter"]: item for item in result["defaults_applied"]}
        self.assertEqual(defaults["genome_build"]["value"], "GRCh38")
        self.assertTrue(defaults["skip_ambiguous_palindromic"]["value"])

    def test_discovery_registers_all_prs_handlers(self) -> None:
        tools = {tool["name"]: tool for tool in list_operations(capability="polygenic-score")}

        self.assertEqual(
            set(tools),
            {
                "prs.search_scores",
                "prs.fetch_score_metadata",
                "prs.import_scoring_file",
                "prs.list_imported_scores",
                "prs.check_score_overlap",
                "prs.calculate_score",
                "prs.build_source_context",
            },
        )
        self.assertEqual(tools["prs.calculate_score"]["annotations"]["discoveryRole"], "entry_tool")
        self.assertEqual(tools["prs.calculate_score"]["annotations"]["privacyScope"], "local_private_prs_score")
        self.assertIn("pgs_catalog_ftp", tools["prs.import_scoring_file"]["annotations"]["externalIO"])

    def test_local_scoring_file_import_overlap_and_score(self) -> None:
        scoring_file = self._write_scoring_file()
        imported = call_operation(
            "prs.import_scoring_file",
            {"pgs_id": "PGS900001", "scoring_file": str(scoring_file), "genome_build": "GRCh38"},
        )
        vcf = self._write_indexed_vcf("sample.vcf")

        self.assertEqual(imported["status"], "completed")
        self.assertEqual(imported["score_cache"]["variant_count"], 4)
        with self._tiny_thresholds():
            overlap = call_operation("prs.check_score_overlap", {"source": str(vcf), "pgs_id": "PGS900001"})
            score = call_operation("prs.calculate_score", {"source": str(vcf), "pgs_id": "PGS900001"})

        self.assertEqual(overlap["schema"], "genomi-prs-overlap-v1")
        self.assertEqual(overlap["status"], "score_ready")
        self.assertEqual(overlap["sample_qc"]["matched_variant_count"], 4)
        self.assertEqual(overlap["sample_qc"]["missing_variant_count"], 0)
        self.assertEqual(score["schema"], "genomi-prs-score-v1")
        self.assertEqual(score["status"], "completed")
        self.assertAlmostEqual(score["score_result"]["raw_weighted_score"], 2.0)
        self.assertEqual(score["score_result"]["calibration"]["status"], "not_provided")
        self.assertIn("not an absolute risk", " ".join(score["limitations"]).lower())
        self.assertTrue(score["personal_context"]["uses_personal_dna"])

    def test_calibration_uses_only_supplied_parameters(self) -> None:
        scoring_file = self._write_scoring_file()
        call_operation("prs.import_scoring_file", {"pgs_id": "PGS900001", "scoring_file": str(scoring_file)})
        vcf = self._write_indexed_vcf("sample_calibrated.vcf")

        with self._tiny_thresholds():
            result = call_operation(
                "prs.calculate_score",
                {"source": str(vcf), "pgs_id": "PGS900001", "score_mean": 1.0, "score_sd": 0.5},
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["score_result"]["calibration"]["status"], "standardized_from_supplied_parameters")
        self.assertAlmostEqual(result["score_result"]["calibration"]["z_score"], 2.0)
        self.assertIn("user-supplied", result["score_result"]["calibration"]["meaning"])

    def test_cross_build_score_without_liftover_chains_prompts_install(self) -> None:
        # GRCh38 score against a GRCh37 sample, but liftover-chains library is
        # not installed in the tmp GENOMI_HOME — the runtime must surface the
        # liftover-chains install prompt rather than silently producing the
        # wrong result.
        scoring_file = self._write_scoring_file()
        imported = call_operation(
            "prs.import_scoring_file",
            {"pgs_id": "PGS900001", "scoring_file": str(scoring_file), "genome_build": "GRCh38"},
        )
        vcf = self._write_indexed_vcf("sample_grch37.vcf")
        runtime_context.set_active_genome_index(
            vcf,
            status="parsed",
            active_genome_index_path=default_active_genome_index_path(vcf),
            genome_build="GRCh37",
        )
        runtime_context.approve_agi_access(reason="test approved Active Genome Index access")

        result = call_operation("prs.check_score_overlap", {"score_dir": imported["score_cache"]["score_dir"]})

        self.assertEqual(result["status"], "requires_library_install")
        self.assertEqual(result["missing_library"]["library"], "liftover-chains")
        self.assertEqual(result["score_genome_build"], "GRCh38")
        self.assertEqual(result["sample_genome_build"], "GRCh37")
        self.assertEqual(result["polygenic_score"]["pgs_id"], "PGS900001")

    def test_cross_build_score_with_chains_but_missing_pyliftover_prompts_install(self) -> None:
        scoring_file = self._write_scoring_file()
        imported = call_operation(
            "prs.import_scoring_file",
            {"pgs_id": "PGS900001", "scoring_file": str(scoring_file), "genome_build": "GRCh38"},
        )
        vcf = self._write_indexed_vcf("sample_grch37_missing_pyliftover.vcf")
        runtime_context.set_active_genome_index(
            vcf,
            status="parsed",
            active_genome_index_path=default_active_genome_index_path(vcf),
            genome_build="GRCh37",
        )
        runtime_context.approve_agi_access(reason="test approved Active Genome Index access")
        self._write_fake_liftover_chains()

        with mock.patch("genomi.runtime.liftover.importlib.import_module", side_effect=ImportError("missing pyliftover")):
            result = call_operation("prs.check_score_overlap", {"score_dir": imported["score_cache"]["score_dir"]})

        self.assertEqual(result["status"], "requires_library_install")
        self.assertEqual(result["reason"], "missing_python_dependency")
        self.assertEqual(result["missing_library"]["library"], "pyliftover")
        self.assertEqual(result["score_genome_build"], "GRCh38")
        self.assertEqual(result["sample_genome_build"], "GRCh37")
        self.assertEqual(result["polygenic_score"]["pgs_id"], "PGS900001")
        self.assertEqual(result["evidence_envelope"]["finding_state"], "blocked_missing_library")
        self.assertEqual(result["evidence_envelope"]["coverage"]["libraries"][0]["library"], "pyliftover")

    def test_cross_build_score_with_liftover_chains_lifts_variants(self) -> None:
        # Same scenario but with the real UCSC chain files linked into the
        # test GENOMI_HOME. The scoring file declares GRCh38 coordinates for
        # APOE rs429358 and rs7412; the AGI on GRCh37 carries those SNPs at
        # their GRCh37 coordinates. The runtime must lift the score variants
        # onto GRCh37 and match them in the Active Genome Index, completing the calculation.
        if not self._link_real_liftover_chains():
            self.skipTest("liftover setup not available on this host")
        from genomi.capabilities.prs import harmonize as prs_harmonize

        prs_harmonize.get_liftover.cache_clear()

        scoring_file = Path(self._home_tmp.name) / "PGS900099_hmPOS_GRCh38.txt"
        # rs429358: GRCh38 chr19:44908684 -> GRCh37 chr19:45411941
        # rs7412:   GRCh38 chr19:44908822 -> GRCh37 chr19:45412079
        scoring_file.write_text(
            "\n".join(
                [
                    "#pgs_id=PGS900099",
                    "hm_chr\thm_pos\trsID\teffect_allele\tother_allele\teffect_weight",
                    "19\t44908684\trs429358\tC\tT\t0.5",
                    "19\t44908822\trs7412\tT\tC\t1.0",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        imported = call_operation(
            "prs.import_scoring_file",
            {"pgs_id": "PGS900099", "scoring_file": str(scoring_file), "genome_build": "GRCh38"},
        )

        # Build a tiny GRCh37 AGI that carries both APOE SNPs at their
        # GRCh37 coordinates so the lifted score variants find matches.
        vcf = Path(self._home_tmp.name) / "sample_apoe_grch37.vcf"
        vcf.write_text(
            "\n".join(
                [
                    "##fileformat=VCFv4.2",
                    '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                    "19\t45411941\trs429358\tT\tC\t.\tPASS\t.\tGT\t0/1",
                    "19\t45412079\trs7412\tC\tT\t.\tPASS\t.\tGT\t0/0",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        create_active_genome_index(vcf, parallel_workers=1, reuse_existing=False)
        runtime_context.set_active_genome_index(
            vcf,
            status="parsed",
            active_genome_index_path=default_active_genome_index_path(vcf),
            genome_build="GRCh37",
        )
        runtime_context.approve_agi_access(reason="test approved Active Genome Index access")

        with self._tiny_thresholds(min_variants=1, min_fraction=0.10):
            result = call_operation(
                "prs.calculate_score",
                {"score_dir": imported["score_cache"]["score_dir"]},
            )

        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["sample_qc"]["genome_build"], "GRCh37")
        self.assertEqual(result["sample_qc"]["score_genome_build"], "GRCh38")
        liftover = result["sample_qc"]["liftover"]
        self.assertEqual(liftover["source_build"], "GRCh38")
        self.assertEqual(liftover["target_build"], "GRCh37")
        self.assertEqual(liftover["lifted_variant_count"], 2)
        self.assertEqual(liftover["dropped_variant_count"], 0)
        self.assertEqual(result["sample_qc"]["matched_variant_count"], 2)

    def test_cross_build_liftover_drops_are_excluded_in_variant_accounting(self) -> None:
        scoring_file = self._write_scoring_file()
        imported = call_operation(
            "prs.import_scoring_file",
            {"pgs_id": "PGS900001", "scoring_file": str(scoring_file), "genome_build": "GRCh38"},
        )
        vcf = self._write_indexed_vcf("sample_grch37_liftover_drops.vcf")
        runtime_context.set_active_genome_index(
            vcf,
            status="parsed",
            active_genome_index_path=default_active_genome_index_path(vcf),
            genome_build="GRCh37",
        )
        runtime_context.approve_agi_access(reason="test approved Active Genome Index access")

        class FakeLifter:
            def lift_position_full(self, chrom: str, pos: int) -> tuple[str, int, str] | None:
                if pos == 200:
                    return None
                if pos == 300:
                    return str(chrom), pos, "-"
                return str(chrom), pos, "+"

        with (
            mock.patch.object(prs_scorer, "liftover_preflight", return_value={"status": "available"}),
            mock.patch.object(prs_harmonize, "get_liftover", return_value=FakeLifter()),
            self._tiny_thresholds(min_variants=1, min_fraction=0.10),
        ):
            result = call_operation(
                "prs.calculate_score",
                {"score_dir": imported["score_cache"]["score_dir"]},
            )

        self.assertEqual(result["status"], "completed", result)
        sample_qc = result["sample_qc"]
        self.assertEqual(sample_qc["score_variant_count"], 4)
        self.assertEqual(sample_qc["matched_variant_count"], 2)
        self.assertEqual(sample_qc["missing_variant_count"], 0)
        self.assertEqual(sample_qc["excluded_variant_count"], 2)
        self.assertEqual(sample_qc["accounted_variant_count"], 4)
        self.assertEqual(sample_qc["unaccounted_variant_count"], 0)
        self.assertEqual(sample_qc["overaccounted_variant_count"], 0)
        self.assertTrue(sample_qc["accounting_complete"])
        self.assertEqual(sample_qc["excluded_reasons"]["liftover_unmapped"], 1)
        self.assertEqual(sample_qc["excluded_reasons"]["liftover_strand_flipped"], 1)
        self.assertEqual(sample_qc["liftover"]["dropped_variant_count"], 2)
        self.assertEqual(sample_qc["liftover"]["dropped_reasons"], {"unmapped": 1, "strand_flipped": 1})
        accounting = result["variant_accounting"]
        self.assertEqual(accounting["accounted_variant_count"], 4)
        self.assertEqual(accounting["excluded_count"], 2)
        excluded_reasons = {item["reason"] for item in accounting["excluded_examples"]}
        self.assertEqual(excluded_reasons, {"liftover_unmapped", "liftover_strand_flipped"})

    def _link_real_liftover_chains(self) -> bool:
        from genomi.runtime.paths import DEFAULT_GENOMI_HOME

        real_chain_dir = DEFAULT_GENOMI_HOME / "resources" / "liftover"
        chains = [
            real_chain_dir / "hg38ToHg19.over.chain.gz",
            real_chain_dir / "hg19ToHg38.over.chain.gz",
        ]
        if not all(path.exists() for path in chains):
            return False
        target_dir = self.genomi_home / "resources" / "liftover"
        target_dir.mkdir(parents=True, exist_ok=True)
        for chain in chains:
            link = target_dir / chain.name
            if not link.exists():
                link.symlink_to(chain)
        return liftover_preflight("GRCh38", "GRCh37", root=self.genomi_home)["status"] == "available"

    def _write_fake_liftover_chains(self) -> None:
        for source_build, target_build in (("GRCh38", "GRCh37"), ("GRCh37", "GRCh38")):
            path = chain_file_path(source_build, target_build, root=self.genomi_home)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")

    def test_low_overlap_blocks_default_score_calculation(self) -> None:
        scoring_file = self._write_scoring_file()
        call_operation("prs.import_scoring_file", {"pgs_id": "PGS900001", "scoring_file": str(scoring_file)})
        vcf = self._write_indexed_vcf("sample_partial.vcf", include_positions={100})

        with self._tiny_thresholds(min_variants=2, min_fraction=0.75):
            result = call_operation("prs.calculate_score", {"source": str(vcf), "pgs_id": "PGS900001"})

        self.assertEqual(result["status"], "insufficient_overlap")
        self.assertIsNone(result["score_result"])
        self.assertFalse(result["sample_qc"]["calculation_allowed"])

    def test_harmonization_does_not_count_third_allele_as_reference_homozygous(self) -> None:
        connection = self._memory_prs_index()
        self._insert_prs_record(connection, pos=100, ref="A", alt="G", genotype="0/1")
        variant = self._score_variant(pos=100, effect_allele="C", other_allele="A")

        result = prs_harmonize.dosage_for_variant(connection, variant)

        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["reason"], "genotype_allele_outside_score_alleles")

    def test_harmonization_allows_reference_block_zero_dosage(self) -> None:
        connection = self._memory_prs_index()
        self._insert_prs_record(connection, pos=100, ref="A", alt=".", genotype="0/0")
        variant = self._score_variant(pos=100, effect_allele="C", other_allele="A")

        result = prs_harmonize.dosage_for_variant(connection, variant)

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["effect_allele_dosage"], 0.0)
        self.assertEqual(result["match_type"], "reference_homozygous_inferred")

    def test_array_harmonization_counts_effect_without_other_allele(self) -> None:
        connection = self._memory_prs_index()
        self._insert_array_prs_record(connection, pos=100, genotype="AG")
        variant = self._score_variant(pos=100, effect_allele="G", other_allele="")

        result = prs_harmonize.dosage_for_variant(connection, variant)

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["effect_allele_dosage"], 1.0)
        self.assertEqual(result["match_type"], "consumer_array_letter_count")

    def test_array_harmonization_counts_zero_without_other_allele(self) -> None:
        connection = self._memory_prs_index()
        self._insert_array_prs_record(connection, pos=100, genotype="AA")
        variant = self._score_variant(pos=100, effect_allele="G", other_allele="")

        result = prs_harmonize.dosage_for_variant(connection, variant)

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["effect_allele_dosage"], 0.0)
        self.assertEqual(result["match_type"], "consumer_array_letter_count")

    def test_array_harmonization_rejects_third_allele_with_complete_score_model(self) -> None:
        connection = self._memory_prs_index()
        self._insert_array_prs_record(connection, pos=100, genotype="AG")
        variant = self._score_variant(pos=100, effect_allele="G", other_allele="T")

        result = prs_harmonize.dosage_for_variant(connection, variant)

        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["reason"], "genotype_allele_outside_score_alleles")

    def _write_scoring_file(self) -> Path:
        path = Path(self._home_tmp.name) / "PGS900001_hmPOS_GRCh38.txt"
        path.write_text(
            "\n".join(
                [
                    "#pgs_id=PGS900001",
                    "#pgs_name=SYNTHETIC",
                    "#reported_trait=Synthetic common trait",
                    "hm_chr\thm_pos\trsID\teffect_allele\tother_allele\teffect_weight",
                    "1\t100\trs1\tC\tA\t0.5",
                    "1\t200\trs2\tG\tT\t1.0",
                    "1\t300\trs3\tG\tA\t-0.25",
                    "1\t400\trs4\tT\tC\t2.0",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def _pgs_metadata_row(
        self,
        *,
        pgs_id: str,
        name: str = "score",
        reported_trait: str,
        mapped_trait_labels: str,
        mapped_trait_ids: str,
        variant_count: str = "10",
    ) -> dict[str, str]:
        return {
            "Polygenic Score (PGS) ID": pgs_id,
            "PGS Name": name,
            "Reported Trait": reported_trait,
            "Mapped Trait(s) (EFO label)": mapped_trait_labels,
            "Mapped Trait(s) (EFO ID)": mapped_trait_ids,
            "PGS Development Method": "",
            "PGS Development Details/Relevant Parameters": "",
            "Original Genome Build": "GRCh38",
            "Number of Variants": variant_count,
            "Number of Interaction Terms": "0",
            "Type of Variant Weight": "effect_weight",
            "PGS Publication (PGP) ID": "PGP000001",
            "Publication (PMID)": "34995502",
            "Publication (doi)": "10.1016/j.ajhg.2021.11.008",
            "Score and results match the original publication": "true",
            "Ancestry Distribution (%) - Source of Variant Associations (GWAS)": "",
            "Ancestry Distribution (%) - Score Development/Training": "",
            "Ancestry Distribution (%) - PGS Evaluation": "",
            "FTP link": "",
            "Release Date": "",
            "License/Terms of Use": "",
        }

    def _write_indexed_vcf(self, name: str, *, include_positions: set[int] | None = None) -> Path:
        include_positions = include_positions or {100, 200, 300, 400}
        rows = [
            (100, "rs1", "A", "C", "1/1"),
            (200, "rs2", "G", "T", "0/1"),
            (300, "rs3", "A", "G", "0/0"),
            (400, "rs4", "C", "T", "0/0"),
        ]
        vcf = Path(self._home_tmp.name) / name
        lines = [
            "##fileformat=VCFv4.2",
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
        ]
        for pos, rsid, ref, alt, gt in rows:
            if pos not in include_positions:
                continue
            lines.append(f"1\t{pos}\t{rsid}\t{ref}\t{alt}\t.\tPASS\t.\tGT\t{gt}")
        vcf.write_text("\n".join(lines) + "\n", encoding="utf-8")
        create_active_genome_index(vcf, parallel_workers=1, reuse_existing=False)
        return vcf

    def _memory_prs_index(self) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            create table records (
                chrom text not null,
                chrom_sort integer not null,
                pos integer not null,
                end integer not null,
                ref text not null,
                alt text not null,
                filter text not null,
                format text,
                genotype text not null,
                offset integer not null,
                sample_index integer not null
            );
            create table spans (
                chrom text not null,
                chrom_sort integer not null,
                pos integer not null,
                end integer not null,
                offset integer not null,
                sample_index integer not null
            );
            """
        )
        return connection

    def _insert_prs_record(
        self,
        connection: sqlite3.Connection,
        *,
        pos: int,
        ref: str,
        alt: str,
        genotype: str,
    ) -> None:
        connection.execute(
            """
            insert into records(chrom, chrom_sort, pos, end, ref, alt, filter, format, genotype, offset, sample_index)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("1", 1, pos, pos, ref, alt, "PASS", "GT", genotype, pos, 0),
        )

    def _insert_array_prs_record(
        self,
        connection: sqlite3.Connection,
        *,
        pos: int,
        genotype: str,
    ) -> None:
        connection.execute(
            """
            insert into records(chrom, chrom_sort, pos, end, ref, alt, filter, format, genotype, offset, sample_index)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("1", 1, pos, pos, "N", genotype, "PASS", "GT_ARRAY", genotype, pos, 0),
        )

    def _score_variant(self, *, pos: int, effect_allele: str, other_allele: str) -> dict[str, object]:
        return {
            "variant_index": 0,
            "variant_id": f"1:{pos}:{other_allele}:{effect_allele}",
            "rsid": "rs-test",
            "chrom": "1",
            "pos": pos,
            "effect_allele": effect_allele,
            "other_allele": other_allele,
            "effect_weight": 1.0,
            "harmonized": True,
            "palindromic": False,
        }

    def _tiny_thresholds(self, *, min_variants: int = 1, min_fraction: float = 0.10):
        return mock.patch.multiple(
            prs_scorer,
            MIN_SCORE_VARIANTS=min_variants,
            MIN_OVERLAP_FRACTION=min_fraction,
            MODERATE_OVERLAP_FRACTION=0.50,
            HIGH_OVERLAP_FRACTION=0.90,
        )


if __name__ == "__main__":
    unittest.main()
