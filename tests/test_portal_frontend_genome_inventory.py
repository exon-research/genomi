from __future__ import annotations

import json
import textwrap
import unittest
from pathlib import Path

from tests.test_portal_frontend_artifact_library import _dom_shim_script, _run_node_json


class PortalFrontendGenomeInventoryTests(unittest.TestCase):
    def test_genome_inventory_model_projects_research_identity(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_genome_inventory.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const inventory = await import({module_url!r});
            const model = inventory.genomeInventoryModel({{
              active: {{ agi_id: 'agi_1', user_id: 'user_alex' }},
              users: [{{ user_id: 'user_alex', nickname: 'Alex', active_agi_id: 'agi_1', agi_ids: ['agi_1'], active: true }}],
              genomes: [{{
                agi_id: 'agi_1',
                display_name: 'Alex genome',
                active: true,
                users: [{{ user_id: 'user_alex', nickname: 'Alex', active: true }}],
                genome_build: 'GRCh38',
                source: {{ format: 'vcf' }},
                readiness: {{ status: 'completed', complete: true, variants_ready: true, snapshot_bound: true }}
              }}]
            }});
            process.stdout.write(JSON.stringify(model));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["summary"], "1 genome · 1 profile")
        self.assertEqual(result["genomes"][0]["title"], "Alex genome")
        self.assertEqual(result["genomes"][0]["summary"], "GRCh38 · VCF · Profile: Alex")
        self.assertNotIn("Active", result["genomes"][0]["badges"])
        self.assertNotIn("query-ready", json.dumps(result))
        self.assertEqual(result["genomes"][0]["userId"], "user_alex")

    def test_active_genome_header_prefers_inventory_identity_over_generic_context(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_genome_inventory.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const inventory = await import({module_url!r});
            const header = inventory.activeGenomeHeaderModel({{
              active: {{ agi_id: 'agi_1', user_id: 'user_alex' }},
              users: [{{ user_id: 'user_alex', nickname: 'Alex', active_agi_id: 'agi_1', active: true }}],
              genomes: [{{
                agi_id: 'agi_1',
                display_name: 'Alex genome',
                active: true,
                users: [{{ user_id: 'user_alex', nickname: 'Alex', active: true }}],
                genome_build: 'GRCh38',
                source: {{ format: 'vcf' }},
                readiness: {{ status: 'completed', complete: true, variants_ready: true, snapshot_bound: true }}
              }}]
            }}, {{
              status: 'ready',
              title: 'Genome ready',
              subtitle: 'Genome data is available in this session'
            }});
            process.stdout.write(JSON.stringify(header));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["title"], "Alex genome")
        self.assertEqual(result["displayTitle"], "Active genome: Alex genome")
        self.assertIn("GRCh38 · VCF", result["subtitle"])
        self.assertNotIn("query-ready", json.dumps(result))
        self.assertIn("Open to switch or add genomes", result["subtitle"])
        self.assertTrue(result["canSwitch"])
        self.assertEqual(result["switchLabel"], "Switch")
        self.assertEqual(result["addLabel"], "Add genome")
        self.assertNotEqual(result["title"], "Genome ready")

    def test_active_genome_header_replaces_generic_inventory_title_with_genome_identity(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_genome_inventory.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const inventory = await import({module_url!r});
            const header = inventory.activeGenomeHeaderModel({{
              active: {{ agi_id: 'agi_1', user_id: 'user_alex' }},
              users: [{{ user_id: 'user_alex', nickname: 'Alex', active_agi_id: 'agi_1', active: true }}],
              genomes: [{{
                agi_id: 'agi_1',
                display_name: 'Genome ready',
                active: true,
                users: [{{ user_id: 'user_alex', nickname: 'Alex', active: true }}],
                genome_build: 'GRCh38',
                source: {{ format: 'vcf' }},
                readiness: {{ status: 'completed', complete: true, variants_ready: true, snapshot_bound: true }}
              }}]
            }}, {{
              status: 'ready',
              title: 'Genome ready'
            }});
            process.stdout.write(JSON.stringify(header));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["title"], "GRCh38 · VCF genome")
        self.assertEqual(result["displayTitle"], "Active genome: GRCh38 · VCF genome")
        self.assertIn("GRCh38 · VCF", result["subtitle"])
        self.assertNotIn("query-ready", json.dumps(result))
        self.assertNotEqual(result["title"], "Genome ready")

    def test_active_genome_header_uses_context_identity_when_inventory_has_not_loaded(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_genome_inventory.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const inventory = await import({module_url!r});
            const header = inventory.activeGenomeHeaderModel({{
              status: 'completed',
              genomes: [],
              users: []
            }}, {{
              status: 'ready',
              title: 'Genome ready',
              subtitle: 'Genome data is available in this session',
              identity: {{
                summaryLabel: 'GRCh38 · VCF · query-ready',
                shortId: 'agi_1',
                subtitle: 'Active genome: Alex genome · GRCh38 · VCF · query-ready'
              }}
            }});
            process.stdout.write(JSON.stringify(header));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["title"], "GRCh38 · VCF genome")
        self.assertEqual(result["displayTitle"], "Active genome: GRCh38 · VCF genome")
        self.assertEqual(result["subtitle"], "Active genome: Alex genome · GRCh38 · VCF")
        self.assertNotIn("query-ready", json.dumps(result))
        self.assertNotEqual(result["title"], "Genome ready")

    def test_active_genome_header_uses_active_id_when_rows_have_not_loaded(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_genome_inventory.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const inventory = await import({module_url!r});
            const header = inventory.activeGenomeHeaderModel({{
              status: 'completed',
              active: {{
                agi_id: 'genome-sha256-b7eca11debe2505f39fa089e62da89dd7cccd2888f2b1b98e3f80ee2fcf7c5a1',
                user_id: 'user_alex'
              }},
              genomes: [],
              users: []
            }}, {{
              status: 'ready',
              title: 'Genome ready',
              subtitle: 'Genome data is available in this session'
            }});
            process.stdout.write(JSON.stringify(header));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["title"], "genome-sha...")
        self.assertEqual(result["displayTitle"], "Active genome: genome-sha...")
        self.assertEqual(result["switchLabel"], "Switch")
        self.assertEqual(result["addLabel"], "Add genome")
        self.assertTrue(result["canSwitch"])
        self.assertNotIn("Genome ready", json.dumps(result))

    def test_registered_genomes_without_project_binding_offer_choose_not_switch(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_genome_inventory.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const inventory = await import({module_url!r});
            const header = inventory.activeGenomeHeaderModel({{
              status: 'completed',
              active: {{}},
              genomes: [{{ agi_id: 'agi_1', display_name: 'Alex genome' }}],
              users: []
            }}, {{
              status: 'empty',
              title: 'No genome loaded'
            }});
            process.stdout.write(JSON.stringify(header));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["title"], "Choose active genome")
        self.assertEqual(result["displayTitle"], "Choose active genome")
        self.assertEqual(result["switchLabel"], "Choose")
        self.assertTrue(result["canSwitch"])

    def test_genome_inventory_render_selects_inactive_genome(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_genome_inventory.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const inventory = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('div');
            const selected = [];
            const add = [];
            inventory.renderGenomeInventory(container, {
              active: { agi_id: 'agi_1', user_id: 'user_alex' },
              users: [{ user_id: 'user_alex', nickname: 'Alex', active_agi_id: 'agi_1', agi_ids: ['agi_1'], active: true }],
              genomes: [
                {
                  agi_id: 'agi_1',
                  display_name: 'Alex genome',
                  active: true,
                  users: [{ user_id: 'user_alex', nickname: 'Alex', active: true }],
                  genome_build: 'GRCh38',
                  source: { format: 'vcf' },
                  readiness: { status: 'completed', complete: true, snapshot_bound: true }
                },
                {
                  agi_id: 'agi_2',
                  display_name: 'Taylor genome',
                  active: false,
                  users: [{ user_id: 'user_taylor', nickname: 'Taylor', active: false }],
                  genome_build: 'GRCh37',
                  source: { format: '23andme' },
                  readiness: { status: 'completed', complete: true, snapshot_bound: true }
                }
              ]
            }, {
              onSelectGenome: (payload) => selected.push(payload),
              onAddGenome: () => add.push('add')
            });
            const rows = container.querySelectorAll('[data-testid="genomi-genome-inventory-row"]');
            const select = container.querySelector('[data-testid="genomi-genome-select"]');
            const addButton = container.querySelector('.genome-inventory-head button');
            if (select) select.eventListeners.click[0]();
            if (addButton) addButton.eventListeners.click[0]();
            process.stdout.write(JSON.stringify({
              testId: container.getAttribute('data-testid'),
              rowCount: rows.length,
              firstRowClass: rows[0] && rows[0].className,
              secondTitle: rows[1] && rows[1].querySelector('strong').textContent,
              selected,
              add
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["testId"], "genomi-genome-inventory")
        self.assertEqual(result["rowCount"], 2)
        self.assertIn("active", result["firstRowClass"])
        self.assertEqual(result["secondTitle"], "Taylor genome")
        self.assertEqual(result["selected"], [{"userId": "user_taylor", "agiId": "agi_2"}])
        self.assertEqual(result["add"], ["add"])

    def test_incomplete_genome_cannot_be_selected_and_offers_rebuild(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_genome_inventory.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const inventory = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('div');
            const selected = [];
            const rebuild = [];
            const payload = {
              active: { agi_id: 'agi_legacy', user_id: 'user_alex' },
              users: [{ user_id: 'user_alex', nickname: 'Alex', active_agi_id: 'agi_legacy', active: true }],
              genomes: [{
                agi_id: 'agi_legacy',
                display_name: 'Alex genome',
                active: true,
                users: [{ user_id: 'user_alex', nickname: 'Alex', active: true }],
                genome_build: 'GRCh38',
                source: { format: 'gvcf' },
                readiness: { status: 'needs_reparse', complete: false, snapshot_bound: false }
              }]
            };
            inventory.renderGenomeInventory(container, payload, {
              onSelectGenome: (selection) => selected.push(selection),
              onAddGenome: () => rebuild.push('rebuild')
            });
            const select = container.querySelector('[data-testid="genomi-genome-select"]');
            const rebuildButton = container.querySelector('[data-testid="genomi-genome-rebuild"]');
            if (rebuildButton) rebuildButton.eventListeners.click[0]();
            process.stdout.write(JSON.stringify({
              model: inventory.genomeInventoryModel(payload),
              header: inventory.activeGenomeHeaderModel(payload),
              hasSelect: Boolean(select),
              rebuildLabel: rebuildButton && rebuildButton.textContent,
              selected,
              rebuild
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertFalse(result["model"]["genomes"][0]["queryReady"])
        self.assertEqual(result["header"]["status"], "needs_rebuild")
        self.assertIn("needs rebuilding", result["header"]["subtitle"])
        self.assertFalse(result["hasSelect"])
        self.assertEqual(result["rebuildLabel"], "Add source to rebuild")
        self.assertEqual(result["selected"], [])
        self.assertEqual(result["rebuild"], ["rebuild"])

    def test_genome_inventory_render_distinguishes_error_from_empty_library(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_genome_inventory.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const inventory = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('div');
            inventory.renderGenomeInventory(container, {
              status: 'error',
              error: 'Genome service unavailable',
              genomes: [],
              users: []
            });
            const empty = container.querySelector('.genome-inventory-empty');
            process.stdout.write(JSON.stringify({
              className: empty.className,
              title: empty.querySelector('strong').textContent,
              message: empty.querySelector('span').textContent
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertIn("warning", result["className"])
        self.assertEqual(result["title"], "Genome list unavailable")
        self.assertEqual(result["message"], "Genome service unavailable")


if __name__ == "__main__":
    unittest.main()
