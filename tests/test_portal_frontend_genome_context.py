from __future__ import annotations

import json
import textwrap
import unittest
from pathlib import Path

from tests.test_portal_frontend_artifact_library import _dom_shim_script, _run_node_json


class PortalFrontendGenomeContextTests(unittest.TestCase):
    def test_active_genome_is_workspace_context_without_an_extra_include_action(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_genome_context.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const genome = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('div');
            genome.renderGenomeContext(container, {
              has_active_genome_index: true,
              active_genome_index_access: { approved: true, scope: 'current_session' },
              active_genome_index: {
                display_name: 'Alex genome',
                genome_build: 'GRCh38',
                source_format: 'vcf',
                active_genome_index_readiness: { status: 'completed', complete: true, variants_ready: true }
              },
              active_genome_index_registry: { known_agi_count: 1, known_user_count: 1 },
              context_axes: { active_genome_index: { current_state: 'active_accessible', known_agis: 1 } }
            });
            const model = genome.genomeContextViewModel({
              has_active_genome_index: true,
              active_genome_index_access: { approved: true, scope: 'current_session' },
              active_genome_index: {
                display_name: 'Alex genome',
                genome_build: 'GRCh38',
                source_format: 'vcf',
                active_genome_index_readiness: { status: 'completed', complete: true, variants_ready: true }
              },
              active_genome_index_registry: { known_agi_count: 1, known_user_count: 1 },
              context_axes: { active_genome_index: { current_state: 'active_accessible', known_agis: 1 } }
            });
            const button = container.querySelector('[data-testid="genomi-genome-include-active"]');
            process.stdout.write(JSON.stringify({
              buttonText: button && button.textContent,
              model,
              bodyText: container.textContent
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertIsNone(result["buttonText"])
        self.assertFalse(result["model"]["canAttach"])
        self.assertEqual(result["model"]["title"], "Alex genome · GRCh38 · VCF")
        self.assertEqual(result["model"]["subtitle"], "Active genome: Alex genome · GRCh38 · VCF · 1 known genome")
        self.assertIn("Selected for this workspace", json.dumps(result["model"]))
        self.assertIn("Not shared automatically", json.dumps(result["model"]))
        self.assertNotIn("query-ready", json.dumps(result))
        self.assertNotIn("Genome data is available in this session", json.dumps(result["model"]))
        self.assertNotIn("Ask with active genome", result["bodyText"])
        self.assertNotIn("Include active genome", json.dumps(result))
        self.assertNotIn("Include active genome summary", result["bodyText"])
        self.assertNotIn("Include selected genome facts", result["bodyText"])


if __name__ == "__main__":
    unittest.main()
