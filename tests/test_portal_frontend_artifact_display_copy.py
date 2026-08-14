from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


class PortalFrontendArtifactDisplayCopyTests(unittest.TestCase):
    def test_artifact_summary_meta_hides_legacy_raw_operation_headlines(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for frontend module tests")
        display_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_artifact_display_model.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const display = await import({display_url!r});
            const model = display.artifactDisplayModel({{
              id: 'art_legacy_raw',
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              operation: 'research.build_target_packet',
              title: 'Evidence report: rs429358',
              summary_lines: [
                'Evidence present',
                '20 sources',
                '0 stored findings',
                'research.build_target_packet: evidence_present · scoped_answer_only'
              ]
            }});
            process.stdout.write(JSON.stringify({{ meta: model.meta }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["meta"], "Evidence present · 20 sources · 0 stored findings")
        self.assertNotIn("research.build_target_packet", result["meta"])
        self.assertNotIn("scoped_answer_only", result["meta"])


def _run_node_json(testcase: unittest.TestCase, script: str) -> object:
    completed = subprocess.run(
        ["node", "--input-type=module"],
        input=script,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        testcase.fail(f"Node script did not return JSON: {completed.stdout!r}\\nstderr={completed.stderr!r}\\n{exc}")
