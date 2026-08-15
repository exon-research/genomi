from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from genomi.capabilities.decode.panel_adapters import normalize_pgx_panel
from genomi.capabilities.pharmacogenomics.pharmcat import run_pharmcat
from genomi.operations import call_operation
from genomi.runtime import context as runtime_context

from tests.pharmcat_test_support import (
    _escaped_header_vcf_text,
    _REAL_JAVA_RUNTIME_AVAILABLE,
    _REAL_PHARMCAT_JAR,
)


@unittest.skipUnless(
    _REAL_PHARMCAT_JAR and _REAL_JAVA_RUNTIME_AVAILABLE,
    "real PharmCAT jar integration requires a managed pharmcat.jar (or PHARMCAT_JAR) and java",
)
class RealPharmCATJarTests(unittest.TestCase):
    """Run the genuine PharmCAT jar against a realistic escaped-quote header.

    This is the only coverage that exercises the actual failure mode: a real
    consumer/WGS header with bcftools backslash escapes parsed by PharmCAT's own
    Java parser. A regression in header sanitization fails here with PharmCAT's
    "character to be escaped is missing" parse error.
    """

    def setUp(self) -> None:
        self._home_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._home_tmp.cleanup)
        self._env = patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(Path(self._home_tmp.name) / "genomi-home"),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "",
                "GENOMI_MCP_BACKGROUND": "0",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_real_jar_parses_escaped_quote_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "escaped.vcf"
            vcf.write_text(_escaped_header_vcf_text(), encoding="utf-8")
            parsed = call_operation("genomi.parse_source", {"source": str(vcf)})
            agi_path = Path(parsed["outputs"]["agi_path"])
            output = Path(tmp) / "pharmcat"

            result = run_pharmcat(
                agi_path=agi_path,
                output_dir=output,
                base_filename="escaped",
                mode="jar",
                pharmcat_jar=_REAL_PHARMCAT_JAR,
                timeout_seconds=600,
            )

            # The matcher input must be backslash-free, and PharmCAT must get past
            # metadata parsing — i.e. NOT the "character to be escaped" crash.
            input_header = [
                line
                for line in (output / "escaped.pharmcat-input.vcf").read_text(encoding="utf-8").splitlines()
                if line.startswith("##")
            ]
            self.assertNotIn("\\", "\n".join(input_header))

        stderr_tail = (result.get("execution") or {}).get("stderr_tail") or ""
        self.assertNotIn("character to be escaped", stderr_tail)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["execution"]["returncode"], 0, result)
        self.assertTrue(result["interpretation_readiness"]["has_report_artifact"], result)

        # Guard the real-format calls-only parse and dashboard adaptation path.
        calls = result["artifacts"]["calls_only"]
        for row in calls["rows"]:
            self.assertIn("Gene", row, result)
        normalize_pgx_panel(result)


if __name__ == "__main__":
    unittest.main()
