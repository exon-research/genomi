from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.active_genome_index import dosage as agi_dosage
from genomi.capabilities.prs import scorer as prs_scorer
from genomi.capabilities.prs import scoring_files as prs_scoring_files
from genomi.operations import call_operation
from genomi.runtime import context as runtime_context
from genomi.runtime.libraries import manager as library_manager

from _prs_contract_helpers import insert_prs_record, memory_prs_index, score_variant


class _FakeAgiReader:
    agi_path = Path("/tmp/fake.agi.sqlite")
    genome_build = "GRCh38"


class _UnsupportedBuildAgiReader:
    agi_path = Path("/tmp/fake-chm13.agi.sqlite")
    genome_build = "CHM13"


class PrsScoreCacheContractTests(unittest.TestCase):
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

    def test_import_scoring_file_rejects_unsupported_genome_build(self) -> None:
        result = call_operation(
            "prs.import_scoring_file",
            {"pgs_id": "PGS900001", "genome_build": "CHM13"},
        )

        self.assertEqual(result["status"], "out_of_scope_for_input")
        self.assertEqual(result["coverage_status"], "out_of_scope_for_input")
        self.assertEqual(result["genome_build"], "CHM13")
        self.assertEqual(result["supported_genome_builds"], ["GRCh37", "GRCh38"])
        self.assertEqual(result["next_actions"][0]["action"], "choose_supported_genome_build")

    def test_validate_score_cache_rejects_unsupported_manifest_build(self) -> None:
        score_dir = Path(self._home_tmp.name) / "score-cache"
        score_dir.mkdir()
        (score_dir / "manifest.json").write_text(
            json.dumps({"pgs_id": "PGS900002", "genome_build": "CHM13", "variant_count": 1}) + "\n",
            encoding="utf-8",
        )

        validation = prs_scoring_files.validate_score_cache(score_dir)

        self.assertFalse(validation["valid"])
        self.assertEqual(validation["reason"], "unsupported_genome_build")
        self.assertEqual(validation["genome_build"], "CHM13")
        self.assertEqual(validation["supported_genome_builds"], ["GRCh37", "GRCh38"])

    def test_list_imported_scores_skips_invalid_cache_manifest(self) -> None:
        score_dir = library_manager.prs_scoring_file_dir("PGS900891", "GRCh38")
        score_dir.mkdir(parents=True)
        (score_dir / "manifest.json").write_text(
            json.dumps({"pgs_id": "PGS900891", "genome_build": "GRCh38", "variant_count": 1}) + "\n",
            encoding="utf-8",
        )

        result = call_operation("prs.list_imported_scores")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["score_count"], 0)
        self.assertEqual(result["scores"], [])

    def test_collect_score_context_reports_unsupported_cached_manifest_build(self) -> None:
        score_dir = Path(self._home_tmp.name) / "unsupported-score"
        score_dir.mkdir()
        (score_dir / "manifest.json").write_text(
            json.dumps({"pgs_id": "PGS900003", "genome_build": "CHM13", "variant_count": 1}) + "\n",
            encoding="utf-8",
        )

        result = prs_scorer.collect_score_context(
            object(),  # AGI reader is not consulted when score cache scope is invalid.
            score_dir=score_dir,
            genome_build="GRCh38",
            operation="prs.calculate_score",
        )

        self.assertEqual(result["status"], "out_of_scope_for_input")
        self.assertEqual(result["score_dir"], str(score_dir))
        self.assertEqual(result["evidence_envelope"]["finding_state"], "not_assessed")
        self.assertEqual(result["evidence_envelope"]["answer_readiness"], "cannot_answer_yet")
        self.assertEqual(
            result["evidence_envelope"]["observations"]["supported_genome_builds"],
            ["GRCh37", "GRCh38"],
        )

    def test_collect_score_context_rejects_sample_build_mismatch_before_cache_lookup(self) -> None:
        result = prs_scorer.collect_score_context(
            _FakeAgiReader(),
            pgs_id="PGS900004",
            genome_build="GRCh37",
            operation="prs.calculate_score",
        )

        self.assertEqual(result["status"], "out_of_scope_for_input")
        self.assertEqual(result["requested_genome_build"], "GRCh37")
        self.assertEqual(result["active_genome_index_genome_build"], "GRCh38")
        self.assertEqual(
            result["evidence_envelope"]["guidance"],
            ["out_of_scope_for_input:use_active_genome_index_genome_build"],
        )
        self.assertEqual(result["next_actions"][0]["action"], "use_active_genome_index_build")

    def test_collect_score_context_rejects_unsupported_active_agi_build(self) -> None:
        result = prs_scorer.collect_score_context(
            _UnsupportedBuildAgiReader(),
            pgs_id="PGS900004",
            genome_build="GRCh38",
            operation="prs.calculate_score",
        )

        self.assertEqual(result["status"], "out_of_scope_for_input")
        self.assertEqual(result["active_genome_index_genome_build"], "CHM13")
        self.assertEqual(result["evidence_envelope"]["query_scope"]["genome_build"], "CHM13")

    def test_vcf_harmonization_preserves_no_call_reason(self) -> None:
        connection = memory_prs_index()
        insert_prs_record(connection, pos=100, ref="A", alt="G", genotype="./.")
        variant = score_variant(pos=100, effect_allele="G", other_allele="A")

        result = agi_dosage.dosage_for_variant(connection, variant)

        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["reason"], "no_call")


if __name__ == "__main__":
    unittest.main()
