from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.active_genome_index.active_genome_index import create_active_genome_index
from genomi.capabilities.decode import evidence_builder
from genomi.evidence import init_evidence_db
from genomi.operations import OPERATIONS, TOOL_CATALOG, call_operation
from genomi.runtime import context as runtime_context


def _extract_evidence(html: str) -> dict:
    marker = "window.__GENOMI_DASHBOARD__"
    assignment_index = html.find(marker)
    assert assignment_index >= 0, "no __GENOMI_DASHBOARD__ block in HTML"
    json_start = html.find("{", assignment_index)
    assert json_start >= 0, "no __GENOMI_DASHBOARD__ object in HTML"
    parsed, _end = json.JSONDecoder().raw_decode(html[json_start:].replace("<\\/", "</"))
    assert isinstance(parsed, dict), "__GENOMI_DASHBOARD__ is not an object"
    return parsed


class DecodeDashboardEvidenceBuilderTests(unittest.TestCase):
    def test_builds_render_params_from_existing_operations(self) -> None:
        calls: list[tuple[str, dict]] = []

        def run(operation: str, params: dict) -> dict:
            calls.append((operation, params))
            if operation == "active_genome_index.summarize":
                return {"active_genome_index": {"variant_count": 100}, "nickname": "BUILT"}
            if operation == "clinvar.scan_candidates":
                return {
                    "status": "completed",
                    "input": "/tmp/clinvar.matches.jsonl",
                    "candidate_inventory": [
                        {
                            "variant": {"id": "rs1", "chrom": "1", "pos": 10, "ref": "A", "alt": "G"},
                            "clinvar": {"clinical_significance_counts": [["Pathogenic", 1]]},
                            "genes": ["GENE1"],
                        }
                    ],
                }
            if operation == "pharmacogenomics.run_pharmcat":
                return {"status": "requires_library_install", "missing_library": {"library": "pharmcat"}}
            if operation == "prs.list_imported_scores":
                return {"status": "completed", "scores": [{"pgs_id": "PGS000001"}]}
            if operation == "prs.calculate_score":
                return {
                    "status": "completed",
                    "polygenic_score": {"pgs_id": params["pgs_id"], "reported_trait": "LDL cholesterol"},
                    "sample_qc": {"matched_variant_count": 2, "score_variant_count": 4},
                    "score_result": {"raw_weighted_score": 1.5},
                }
            if operation == "ancestry.estimate_population_context":
                return {"nearest_reference_groups": [{"group": "EUR", "score": 0.9}]}
            if operation == "nutrigenomics.list_domains":
                return {"domains": [{"domain_id": "folate_metabolism"}]}
            if operation == "nutrigenomics.retrieve_domain_markers":
                return {
                    "coverage_status": "data_returned",
                    "markers": [
                        {
                            "domain": "folate_metabolism",
                            "gene": {"symbol": "MTHFR"},
                            "variant": {"rsid": "rs1801133"},
                        }
                    ],
                }
            if operation == "journal.search_entries":
                return {"status": "completed", "entries": [{"title": "Reviewed", "kind": "observation"}]}
            raise AssertionError(f"unexpected operation {operation}")

        result = evidence_builder.build_dashboard_evidence(
            params={"pgx_timeout_seconds": 30, "risk_score_limit": 1},
            run_operation=run,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["render_params"]["variants_all_source"], "/tmp/clinvar.matches.jsonl")
        self.assertIn("overview", result["panels_ready"])
        self.assertIn("variants_all", result["panels_ready"])
        self.assertIn("pgx", result["panels_empty"])
        self.assertIn("pgx", result["panels_blocked"])
        self.assertEqual(result["render_params"]["evidence"]["risk"][0]["polygenic_score"]["pgs_id"], "PGS000001")
        self.assertIn(("pharmacogenomics.run_pharmcat", {"timeout_seconds": 30}), calls)
        self.assertIn(("prs.calculate_score", {"pgs_id": "PGS000001"}), calls)

    def test_catalog_exposes_builder(self) -> None:
        names = {op.name for op in OPERATIONS}
        self.assertIn("decode.build_dashboard_evidence", names)
        decode_capability = TOOL_CATALOG["capabilities"]["decode"]
        self.assertIn("decode.build_dashboard_evidence", decode_capability["entry_operations"])
        self.assertIn("decode.build_dashboard_evidence", decode_capability["operations"])


class DecodeRenderAutoBuildTests(unittest.TestCase):
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

    def test_render_without_evidence_uses_code_owned_builder(self) -> None:
        with tempfile.TemporaryDirectory() as wd:
            wd_path = Path(wd)
            previous = os.getcwd()
            os.chdir(wd_path)
            try:
                vcf = wd_path / "sample.vcf"
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"
                    "10\t94761900\trs4244285\tG\tA\t50\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                    encoding="utf-8",
                )
                agi_path = wd_path / "sample.active-genome-index.sqlite"
                evidence_db = wd_path / "evidence.sqlite"
                create_active_genome_index(vcf, agi_path)
                init_evidence_db(evidence_db)
                runtime_context.set_active_agi_from_source(
                    vcf,
                    status="parsed",
                    operation_result={
                        "sample_slug": "sample",
                        "agi_intake_source_path": str(vcf),
                        "evidence_db": str(evidence_db),
                        "work_dir": str(wd_path),
                        "outputs": {"agi_path": str(agi_path)},
                    },
                )
                call_operation("active_genome_index.approve_access", {"approved_by_user": True, "reason": "test"})
                out = wd_path / "dash.html"
                built = {
                    "status": "completed",
                    "render_params": {"evidence": {"overview": {"sampleId": "BUILT", "variantCount": 1}}},
                    "panels_ready": ["overview"],
                    "panels_empty": ["variants"],
                    "panels_blocked": [],
                    "panel_states": [{"panel": "overview", "status": "data_returned"}],
                }
                with mock.patch(
                    "genomi.operations.registry.handlers_screen_journal.decode_evidence_builder.build_dashboard_evidence",
                    return_value=built,
                ) as build:
                    result = call_operation("decode.render_dashboard", {"mode": "full", "output": str(out)})

                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["evidence_build"]["panels_ready"], ["overview"])
                self.assertEqual(_extract_evidence(out.read_text(encoding="utf-8"))["overview"]["sampleId"], "BUILT")
                build.assert_called_once()
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
