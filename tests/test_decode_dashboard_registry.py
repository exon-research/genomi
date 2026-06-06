from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.active_genome_index.active_genome_index import create_active_genome_index
from genomi.capabilities.decode import dashboard as decode_dashboard
from genomi.evidence import init_evidence_db
from genomi.operations import (
    OperationError,
    call_operation,
)
from genomi.runtime import context as runtime_context
from genomi.runtime.sqlite_support import connect_sqlite

_DECODE_BUILDER_PATCH = (
    "genomi.operations.registry.handlers_screen_journal."
    "decode_evidence_builder.build_dashboard_evidence"
)


def _extract_evidence(html: str) -> dict:
    marker = "window.__GENOMI_DASHBOARD__"
    assignment_index = html.find(marker)
    assert assignment_index >= 0, "no __GENOMI_DASHBOARD__ block in HTML"
    json_start = html.find("{", assignment_index)
    assert json_start >= 0, "no __GENOMI_DASHBOARD__ object in HTML"
    parsed, _end = json.JSONDecoder().raw_decode(html[json_start:].replace("<\\/", "</"))
    assert isinstance(parsed, dict), "__GENOMI_DASHBOARD__ is not an object"
    return parsed


def _replace_evidence(html: str, evidence: dict) -> str:
    marker = "window.__GENOMI_DASHBOARD__"
    assignment_index = html.find(marker)
    assert assignment_index >= 0, "no __GENOMI_DASHBOARD__ block in HTML"
    json_start = html.find("{", assignment_index)
    assert json_start >= 0, "no __GENOMI_DASHBOARD__ object in HTML"
    _parsed, json_end = json.JSONDecoder().raw_decode(html[json_start:].replace("<\\/", "</"))
    blob = json.dumps(evidence, ensure_ascii=False).replace("</", "<\\/")
    return html[:json_start] + blob + html[json_start + json_end:]


def _panel_keys(payload: dict) -> set[str]:
    return {key for key in payload if key in decode_dashboard.PANEL_KEYS}


NAV_LABELS = (
    "Overview",
    "Variants",
    "Pharmacogenomics",
    "Risk Scores",
    "Ancestry",
    "Nutrigenomics",
    "Journal",
)


class RegistryGatingTests(unittest.TestCase):
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

    def test_active_genome_required(self) -> None:
        with self.assertRaises(OperationError) as ctx:
            call_operation(
                "decode.render_dashboard",
                {},
            )
        self.assertEqual(ctx.exception.code, "active_genome_index_required")

    def test_render_through_registry_with_active_genome(self) -> None:
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
                index = wd_path / "sample.active-genome-index.sqlite"
                evidence_db = wd_path / "evidence.sqlite"
                create_active_genome_index(vcf, index)
                init_evidence_db(evidence_db)
                runtime_context.set_active_agi_from_source(
                    vcf,
                    status="parsed",
                    operation_result={
                        "sample_slug": "sample",
                        "agi_intake_source_path": str(vcf),
                        "evidence_db": str(evidence_db),
                        "work_dir": str(wd_path),
                        "outputs": {"agi_path": str(index)},
                    },
                )
                call_operation(
                    "active_genome_index.approve_access",
                    {"approved_by_user": True, "reason": "test"},
                )
                out = wd_path / "dash.html"
                built = {
                    "status": "completed",
                    "render_params": {"evidence": {"overview": {"sampleId": "ACTIVE", "variantCount": 1}}},
                    "panels_ready": ["overview"],
                    "panels_empty": [],
                    "panels_blocked": [],
                    "panel_states": [{"panel": "overview", "status": "data_returned"}],
                }
                with mock.patch(_DECODE_BUILDER_PATCH, return_value=built):
                    result = call_operation("decode.render_dashboard", {"output": str(out)})
                self.assertEqual(result["status"], "completed")
                self.assertTrue(out.is_file())
                self.assertIn("evidence_envelope", result)
            finally:
                os.chdir(previous)

    def test_render_through_registry_enforces_agi_readiness(self) -> None:
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
                index = wd_path / "sample.active-genome-index.sqlite"
                evidence_db = wd_path / "evidence.sqlite"
                create_active_genome_index(vcf, index)
                init_evidence_db(evidence_db)
                with connect_sqlite(index) as connection:
                    connection.execute(
                        "update metadata set value = ? where key = 'active_genome_index_complete'",
                        (json.dumps(False),),
                    )
                    connection.execute(
                        "update metadata set value = ? where key = 'active_genome_index_build_status'",
                        (json.dumps("in_progress"),),
                    )
                    connection.commit()
                runtime_context.set_active_agi_from_source(
                    vcf,
                    status="parsed",
                    operation_result={
                        "sample_slug": "sample",
                        "agi_intake_source_path": str(vcf),
                        "evidence_db": str(evidence_db),
                        "work_dir": str(wd_path),
                        "outputs": {"agi_path": str(index)},
                    },
                )
                call_operation(
                    "active_genome_index.approve_access",
                    {"approved_by_user": True, "reason": "test"},
                )

                with self.assertRaises(OperationError) as ctx:
                    call_operation(
                        "decode.render_dashboard",
                        {"output": str(wd_path / "dash.html")},
                    )
                self.assertEqual(ctx.exception.code, "active_genome_index_incomplete")
            finally:
                os.chdir(previous)
