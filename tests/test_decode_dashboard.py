from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.active_genome_index.active_genome_index import create_active_genome_index
from genomi.capabilities.decode import dashboard as decode_dashboard
from genomi.evidence import init_evidence_db
from genomi.operations import (
    OPERATIONS,
    TOOL_CATALOG,
    OperationError,
    call_operation,
)
from genomi.runtime import context as runtime_context

EVIDENCE_RE = re.compile(
    r"window\.__GENOMI_DASHBOARD__\s*=\s*(\{.*?\})\s*;",
    re.DOTALL,
)


def _extract_evidence(html: str) -> dict:
    match = EVIDENCE_RE.search(html)
    assert match, "no __GENOMI_DASHBOARD__ block in HTML"
    return json.loads(match.group(1).replace("<\\/", "</"))


NAV_LABELS = (
    "Overview",
    "Variants",
    "Pharmacogenomics",
    "Risk Scores",
    "Ancestry",
    "Nutrigenomics",
    "Journal",
)


class RenderDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = Path(self._tmp.name)

    def test_render_full_writes_self_contained_html(self) -> None:
        out = self.tmpdir / "dash.html"
        evidence = {
            "overview": {
                "sampleId": "HG-TEST-01",
                "genomeBuild": "GRCh38",
                "variantCount": 4500000,
            },
            "variants": [
                {"rsid": "rs429358", "gene": "APOE", "chrom": "19", "pos": 44908684,
                 "ref": "T", "alt": "C", "zygosity": "hom",
                 "clinvarSignificance": "risk_factor", "conditionShort": "Alzheimer"},
            ],
        }
        result = decode_dashboard.render_dashboard(
            evidence=evidence, mode="full", output=out
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["mode"], "full")
        self.assertTrue(out.is_file())
        html = out.read_text(encoding="utf-8")
        # Self-contained: inline logo data URL
        self.assertIn("data:image/png;base64,", html)
        # Renders offline: React/ReactDOM/app JS are inlined, no CDN script src,
        # no in-browser Babel, and no placeholders left unresolved.
        self.assertNotIn("unpkg.com", html)
        self.assertNotIn('type="text/babel"', html)
        for placeholder in (
            "__GENOMI_VENDOR_SCRIPTS__",
            "__GENOMI_APP_JS__",
            "__GENOMI_LOGO_DATA_URL__",
            "__GENOMI_EVIDENCE__",
        ):
            self.assertNotIn(placeholder, html)
        self.assertEqual(re.findall(r'<script[^>]+src="https?://', html), [])
        self.assertIn("ReactDOM", html)  # vendored runtime is inlined
        # Evidence blob present and contains keys
        parsed = _extract_evidence(html)
        self.assertEqual(parsed["overview"]["sampleId"], "HG-TEST-01")
        self.assertEqual(parsed["variants"][0]["rsid"], "rs429358")
        # All seven nav labels render
        for label in NAV_LABELS:
            self.assertIn(label, html)
        # Serve hint surfaces a localhost URL + http.server command the agent can run
        serve = result["serve"]
        self.assertEqual(serve["filename"], "dash.html")
        self.assertEqual(serve["directory"], str(out.parent.resolve()))
        self.assertIn("127.0.0.1", serve["url"])
        self.assertTrue(serve["url"].endswith("/dash.html"))
        self.assertIn("python3 -m http.server", serve["command"])
        self.assertIn("--bind 127.0.0.1", serve["command"])

    def test_render_full_empty_panel_placeholders(self) -> None:
        out = self.tmpdir / "dash.html"
        overview = {"sampleId": "HG-TEST-02", "variantCount": 4500000}
        decode_dashboard.render_dashboard(
            evidence={"overview": overview},
            mode="full",
            output=out,
        )
        html = out.read_text(encoding="utf-8")
        # The placeholder string ("Not gathered yet") is in the inlined script
        # exactly once, used by the EmptyPanel component for the missing panels.
        self.assertIn("Not gathered yet", html)
        result = decode_dashboard.render_dashboard(
            evidence={"overview": overview},
            mode="full",
            output=out,
        )
        self.assertEqual(set(result["panels_empty"]), {
            "variants", "variants_all", "pgx", "risk", "ancestry", "nutrigenomics", "journal",
        })
        self.assertEqual(result["panels_rendered"], ["overview"])

    def test_render_update_merges_panels(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {"sampleId": "HG-MERGE", "genomeBuild": "GRCh38",
                             "variantCount": 4500000},
                "variants": [{"rsid": "rs1", "gene": "G1"}],
            },
            mode="full",
            output=out,
        )
        result = decode_dashboard.render_dashboard(
            evidence={"pgx": [{"gene": "CYP2C19", "diplotype": "*1/*2",
                               "phenotype": "Intermediate", "impact": "reduced"}]},
            mode="update",
            output=out,
        )
        self.assertEqual(result["mode"], "update")
        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        # Original overview retained
        self.assertEqual(parsed["overview"]["sampleId"], "HG-MERGE")
        # Variants retained
        self.assertEqual(parsed["variants"][0]["rsid"], "rs1")
        # New pgx merged in
        self.assertEqual(parsed["pgx"][0]["gene"], "CYP2C19")

    def test_normalizes_snake_case_overview(self) -> None:
        """Raw active_genome_index.summarize-style keys map to dashboard schema."""
        out = self.tmpdir / "dash.html"
        result = decode_dashboard.render_dashboard(
            evidence={
                "overview": {
                    "nickname": "matthew",
                    "genome_build": "GRCh38",
                    "active_genome_index_completed_at": "2026-05-25T21:20:00Z",
                    "active_genome_index": {"variant_count": 5_148_321},
                },
            },
            mode="full",
            output=out,
        )
        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        ov = parsed["overview"]
        self.assertEqual(ov["sampleId"], "matthew")
        self.assertEqual(ov["genomeBuild"], "GRCh38")
        self.assertEqual(ov["parsedAt"], "2026-05-25T21:20:00Z")
        self.assertEqual(ov["variantCount"], 5_148_321)
        self.assertIn("overview", result["panels_rendered"])
        self.assertNotIn("overview", result["panels_empty"])

    def test_normalizes_ancestry_nearest_reference_groups(self) -> None:
        """ancestry.estimate_population_context keys map to neighbors[]."""
        out = self.tmpdir / "dash.html"
        result = decode_dashboard.render_dashboard(
            evidence={
                "ancestry": {
                    "nearest_reference_groups": [
                        {"group": "EUR", "score": 0.61},
                        {"group": "AMR", "score": 0.18},
                    ],
                    "markerOverlapQuality": "low",
                    "overlap_fraction": 0.56,
                    "panel_id": "1000g-30x-grch38",
                },
            },
            mode="full",
            output=out,
        )
        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        anc = parsed["ancestry"]
        self.assertEqual(anc["dominantAncestry"], "EUR")
        self.assertEqual(anc["neighbors"][0], {"population": "EUR", "similarity": 0.61})
        self.assertIn("ancestry", result["panels_rendered"])

    def test_supplied_overview_unmappable_raises(self) -> None:
        """A content-bearing panel that maps to no schema field fails loudly."""
        out = self.tmpdir / "dash.html"
        with self.assertRaises(decode_dashboard.DashboardRenderError) as ctx:
            decode_dashboard.render_dashboard(
                evidence={"overview": {"random_unrelated_key": "x"}},
                mode="full",
                output=out,
            )
        self.assertEqual(ctx.exception.code, "panel_schema_mismatch")

    def test_supplied_overview_missing_required_field_raises(self) -> None:
        """Overview with content but no variant count is rejected, not blanked."""
        out = self.tmpdir / "dash.html"
        with self.assertRaises(decode_dashboard.DashboardRenderError) as ctx:
            decode_dashboard.render_dashboard(
                evidence={"overview": {"sampleId": "HG-X", "genomeBuild": "GRCh38"}},
                mode="full",
                output=out,
            )
        self.assertEqual(ctx.exception.code, "panel_schema_mismatch")
        self.assertIn("variantCount", ctx.exception.message)

    def test_normalizes_real_summarize_overview(self) -> None:
        """The actual active_genome_index.summarize nesting maps variantCount.

        summarize puts the count at index.stats.variant_records (two levels
        deep) and the sample name under index.metadata.header.samples — the
        shape that previously rendered a blank "0" stat.
        """
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {
                    "index": {
                        "stats": {"variant_records": 5_151_074,
                                  "pass_records": 11_778_439,
                                  "total_records": 12_410_160},
                        "metadata": {"header": {"samples": ["SQ73VL33"],
                                                "reference": "GRCh38.p13",
                                                "dataSourceType": "WGS"}},
                    },
                },
            },
            mode="full",
            output=out,
        )
        ov = _extract_evidence(out.read_text(encoding="utf-8"))["overview"]
        self.assertEqual(ov["variantCount"], 5_151_074)
        self.assertEqual(ov["sampleId"], "SQ73VL33")
        self.assertEqual(ov["genomeBuild"], "GRCh38.p13")

    def test_supplied_list_panel_wrong_type_raises(self) -> None:
        """A list panel handed a dict fails loudly instead of rendering odd."""
        out = self.tmpdir / "dash.html"
        with self.assertRaises(decode_dashboard.DashboardRenderError) as ctx:
            decode_dashboard.render_dashboard(
                evidence={
                    "overview": {"sampleId": "HG-L", "variantCount": 10},
                    "risk": {"trait": "T2D", "score": 1.0},
                },
                mode="full",
                output=out,
            )
        self.assertEqual(ctx.exception.code, "panel_schema_mismatch")

    def test_overview_renders_panel_highlights_when_panels_have_data(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {
                    "sampleId": "HG-HI",
                    "genomeBuild": "GRCh38",
                    "variantCount": 1000,
                    "parsedAt": "2026-05-25T00:00:00Z",
                },
                "variants": [
                    {"rsid": "rs429358", "gene": "APOE",
                     "clinvarSignificance": "risk_factor"},
                ],
                "pgx": [
                    {"gene": "CYP2C19", "diplotype": "*1/*2",
                     "phenotype": "Intermediate", "impact": "reduced"},
                ],
                "ancestry": {
                    "dominantAncestry": "EUR",
                    "neighbors": [{"population": "EUR", "similarity": 0.9}],
                    "pcaPoints": [{"x": 1, "y": 2, "cluster": "sample"}],
                },
                "journal": [
                    {"kind": "observation", "title": "First note", "ts": "2026-05-24"},
                ],
            },
            mode="full",
            output=out,
        )
        html = out.read_text(encoding="utf-8")
        # Highlight card headers render in the inline script.
        self.assertIn("Top Variants", html)
        self.assertIn("Pharmacogenomics", html)
        self.assertIn("Ancestry", html)
        self.assertIn("Journal", html)

    def test_source_coverage_falls_back_to_alternate_name_keys(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {
                    "sampleId": "HG-SRC",
                    "genomeBuild": "GRCh38",
                    "variantCount": 100,
                    "parsedAt": "2026-05-25T00:00:00Z",
                    "sourceCoverage": [
                        {"label": "ClinVar", "status": "ok"},
                        {"library": "PharmCAT", "status": "ok"},
                    ],
                },
            },
            mode="full",
            output=out,
        )
        html = out.read_text(encoding="utf-8")
        self.assertIn("ClinVar", html)
        self.assertIn("PharmCAT", html)
        parsed = _extract_evidence(html)
        sources = parsed["overview"]["sourceCoverage"]
        self.assertEqual(sources[0]["name"], "ClinVar")
        self.assertEqual(sources[1]["name"], "PharmCAT")

    def test_ancestry_pca_empty_shows_placeholder(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "ancestry": {
                    "dominantAncestry": "EUR",
                    "neighbors": [{"population": "EUR", "similarity": 0.9}],
                },
            },
            mode="full",
            output=out,
        )
        html = out.read_text(encoding="utf-8")
        self.assertIn("No PCA points in evidence", html)

    def test_render_update_missing_file_errors(self) -> None:
        missing = self.tmpdir / "nope" / "dash.html"
        with self.assertRaises(decode_dashboard.DashboardRenderError) as ctx:
            decode_dashboard.render_dashboard(
                evidence={"overview": {"sampleId": "x"}},
                mode="update",
                output=missing,
            )
        self.assertEqual(ctx.exception.code, "dashboard_not_found")


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
                {"evidence": {"overview": {"sampleId": "x"}}, "mode": "full"},
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
                runtime_context.set_active_genome_index(
                    vcf,
                    status="parsed",
                    operation_result={
                        "sample_slug": "sample",
                        "vcf": str(vcf),
                        "evidence_db": str(evidence_db),
                        "work_dir": str(wd_path),
                        "outputs": {"active_genome_index_path": str(index)},
                    },
                )
                call_operation(
                    "active_genome_index.approve_access",
                    {"approved_by_user": True, "reason": "test"},
                )
                out = wd_path / "dash.html"
                result = call_operation(
                    "decode.render_dashboard",
                    {
                        "evidence": {"overview": {"sampleId": "ACTIVE",
                                                  "variantCount": 1}},
                        "mode": "full",
                        "output": str(out),
                    },
                )
                self.assertEqual(result["status"], "completed")
                self.assertTrue(out.is_file())
                self.assertIn("evidence_envelope", result)
            finally:
                os.chdir(previous)


class DashboardOfflineAssetTests(unittest.TestCase):
    """Guard the offline contract: vendored assets present and compiled JS in sync."""

    _TEMPLATES = (
        Path(decode_dashboard.__file__).resolve().parent / "templates"
    )

    def test_vendored_runtime_assets_present(self) -> None:
        vendor = self._TEMPLATES / "vendor"
        for name in ("react.production.min.js", "react-dom.production.min.js", "dashboard.compiled.js"):
            self.assertTrue((vendor / name).is_file(), f"missing vendored asset {name}")

    def test_template_has_no_cdn_or_runtime_babel(self) -> None:
        shell = (self._TEMPLATES / "shell.html").read_text(encoding="utf-8")
        self.assertNotIn("unpkg.com", shell)
        self.assertNotIn('type="text/babel"', shell)

    def test_compiled_js_matches_jsx_source(self) -> None:
        # Drift guard: dashboard.compiled.js stamps the sha256 of the dashboard.jsx
        # it was built from. If someone edits the JSX without re-running
        # scripts/build_dashboard.py, this fails — no JS toolchain needed here.
        import hashlib

        jsx = (self._TEMPLATES / "dashboard.jsx").read_bytes()
        compiled = (self._TEMPLATES / "vendor" / "dashboard.compiled.js").read_text(encoding="utf-8")
        match = re.search(r"source-sha256:\s*([0-9a-f]{64})", compiled)
        self.assertIsNotNone(match, "compiled JS is missing its source-sha256 header")
        self.assertEqual(
            match.group(1),
            hashlib.sha256(jsx).hexdigest(),
            "dashboard.compiled.js is stale — re-run scripts/build_dashboard.py after editing dashboard.jsx.",
        )


class DashboardCatalogTests(unittest.TestCase):
    def test_dashboard_in_base_catalog(self) -> None:
        names = {op.name for op in OPERATIONS}
        self.assertIn("decode.render_dashboard", names)
        self.assertIn("decode", TOOL_CATALOG["capability_order"])
        self.assertIn("decode", TOOL_CATALOG["namespace_order"])
        self.assertIn("decode", TOOL_CATALOG["capabilities"])
        decode_cap = TOOL_CATALOG["capabilities"]["decode"]
        self.assertIn("decode.render_dashboard", decode_cap["entry_operations"])


if __name__ == "__main__":
    unittest.main()
