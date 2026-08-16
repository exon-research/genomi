from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

from genomi.interfaces import portal_assets, portal_starter_cards
from tests.test_portal_frontend_artifact_library import _dom_shim_script

_PRIVATE_PROMPT_RE = re.compile(r"(?:context_file|registry_file|agi_path|/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes|~)")


class PortalFrontendAssetTests(unittest.TestCase):
    def test_operation_display_labels_are_user_facing(self) -> None:
        labels_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_operation_labels.js").as_uri()
        script = textwrap.dedent(
            f"""
            const labels = await import({labels_url!r});
            const result = {{
              variant: labels.operationDisplayLabel('variant.resolve'),
              targetPacket: labels.operationDisplayLabel('research.build_target_packet'),
              genomeState: labels.operationDisplayLabel('genomi.describe_context'),
              unknown: labels.operationDisplayLabel('gwas.compare_gene_associations'),
              freeText: labels.operationDisplayLabel('loose note'),
              freeform: labels.operationDisplayLabel('tool from /opt/homebrew/bin/codex'),
              unsafeFallback: labels.operationDisplayLabel('tool from /opt/homebrew/bin/codex', 'tool from /opt/homebrew/bin/codex'),
              unsafeListFallback: labels.operationListDisplayLabel(['loose note'], 'tool from /opt/homebrew/bin/codex'),
              list: labels.operationListDisplayLabel(['variant.resolve', 'pharmacogenomics.review_medication'])
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["variant"], "Variant lookup")
        self.assertEqual(result["targetPacket"], "Target evidence report")
        self.assertEqual(result["genomeState"], "Active genome")
        self.assertEqual(result["unknown"], "GWAS Compare Gene Associations")
        self.assertEqual(result["freeText"], "Research step")
        self.assertEqual(result["freeform"], "Research step")
        self.assertEqual(result["unsafeFallback"], "Research step")
        self.assertEqual(result["unsafeListFallback"], "Research step")
        self.assertEqual(result["list"], "Variant lookup, Medication-response review")

    def test_tool_input_summary_hides_paths_and_version_ids(self) -> None:
        details_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_tool_details.js").as_uri()
        script = textwrap.dedent(
            f"""
            const details = await import({details_url!r});
            const result = {{
              pathOnly: details.toolInputSummary({{
                path: '/Users/matthewzmd/private/source.vcf',
                file_path: '/tmp/private/report.json',
                version_id: 'ver_private',
                operation: 'variant.resolve'
              }}),
              command: details.toolInputSummary({{ command: 'cat /Users/matthewzmd/private/source.vcf' }}),
              query: details.toolInputSummary({{ query: 'rs429358', path: '/Users/matthewzmd/private/source.vcf' }})
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["pathOnly"], "Variant lookup")
        self.assertIn("[redacted local path]", result["command"])
        self.assertEqual(result["query"], "rs429358")
        _assert_public_payload(result)

    def test_context_display_model_uses_safe_source_label_for_invalid_operation(self) -> None:
        prompt_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_prompt_context_model.js").as_uri()
        script = textwrap.dedent(
            f"""
            const prompt = await import({prompt_url!r});
            const result = prompt.contextDisplayModel({{
              label: 'Selected material',
              source_operation: 'tool from /opt/homebrew/bin/codex',
              summary: 'Visible material'
            }});
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["source"], "Research step")
        self.assertNotIn("tool from", result["source"])
        self.assertNotIn("/opt", result["source"])
        _assert_public_payload(result)

    def test_submit_turn_posts_canonical_run_request(self) -> None:
        api_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_api.js").as_uri()
        script = textwrap.dedent(
            f"""
            const calls = [];
            globalThis.document = {{
              querySelector() {{
                return {{ getAttribute() {{ return 'csrf-token'; }} }};
              }}
            }};
            globalThis.fetch = async (path, options = {{}}) => {{
              calls.push({{ path, method: options.method, headers: options.headers, body: options.body }});
              return {{
                ok: true,
                async json() {{ return {{ runId: 'run_1', frameId: 'frame_1' }}; }}
              }};
            }};
            const api = await import({api_url!r});
            await api.submitTurn({{
              projectId: 'proj_1',
              frameId: 'frame_1',
              message: 'Review CYP2C19 evidence',
              genomeContextMode: 'public',
              selectedEvidence: [{{ id: 'ev_1', label: 'Medication', text: 'clopidogrel' }}]
            }});
            await api.submitTurn({{
              projectId: 'proj_1',
              message: 'Start a focused file review',
              selectedEvidence: [{{ id: 'file_1', label: 'Project file', context_kind: 'workspace_file' }}]
            }});
            process.stdout.write(JSON.stringify(calls));
            """
        )

        result = _run_node_json(self, script)
        body = json.loads(result[0]["body"])
        focused_body = json.loads(result[1]["body"])

        self.assertEqual(result[0]["path"], "/api/runs")
        self.assertEqual(result[0]["method"], "POST")
        self.assertEqual(result[0]["headers"]["x-genomi-csrf"], "csrf-token")
        self.assertEqual(body["projectId"], "proj_1")
        self.assertEqual(body["frameId"], "frame_1")
        self.assertEqual(body["message"], "Review CYP2C19 evidence")
        self.assertEqual(body["genomeContextMode"], "public")
        self.assertNotIn("agentId", body)
        self.assertEqual(body["selectedEvidence"][0]["text"], "clopidogrel")
        self.assertEqual(focused_body["projectId"], "proj_1")
        self.assertEqual(focused_body["message"], "Start a focused file review")
        self.assertNotIn("frameId", focused_body)
        self.assertNotIn("genomeContextMode", focused_body)
        self.assertEqual(focused_body["selectedEvidence"][0]["context_kind"], "workspace_file")

    def test_local_assistant_panel_says_which_assistant_this_workspace_uses(self) -> None:
        runtime_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_runtime_status.js").as_uri()
        script = textwrap.dedent(
            """
            const runtime = await import(__MODULE_URL__);
            __DOM_SHIM__
            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const agents = [
              { id: 'codex', label: 'Codex CLI', runnable: true, available: true, last_run_failure: 'assistant_usage_limit_reached' },
              { id: 'claude', label: 'Claude Code', runnable: true, available: true },
              { id: 'gemini', label: 'Gemini CLI', runnable: false, available: true },
              { id: 'opencode', label: 'OpenCode', runnable: false, available: false }
            ];
            const bootstrap = { state: 'ready', source: 'bootstrap_host_agent', active_agent_id: 'claude', active_label: 'Claude Code', selected_agent_id: '' };
            const chosen = { state: 'ready', source: 'workspace_choice', active_agent_id: 'codex', active_label: 'Codex CLI', selected_agent_id: 'codex' };
            const gone = { state: 'workspace_choice_unavailable', source: '', active_agent_id: '', active_label: '', unavailable_label: 'Claude Code' };
            const launched = { state: 'ready', source: 'launch_option', active_agent_id: 'claude', active_label: 'Claude Code', selected_agent_id: '' };
            const onlyOne = { state: 'ready', source: 'only_runnable', active_agent_id: 'claude', active_label: 'Claude Code', selected_agent_id: '' };
            const survivor = { state: 'ready', source: 'only_one_working_here', active_agent_id: 'claude', active_label: 'Claude Code', selected_agent_id: '' };
            const undecided = { state: 'choice_required', source: '', active_agent_id: '', active_label: '', selected_agent_id: '' };
            const selections = [];
            const target = document.createElement('div');
            runtime.renderAssistantChoice(target, { agents, assistant: bootstrap }, { onSelect: (id) => selections.push(id) });
            const readText = (node) => [node.textContent, ...node.children.map(readText)].filter(Boolean).join(' ');
            const rows = target.querySelectorAll('[data-runtime-state]').map((row) => ({
              testid: row.getAttribute('data-testid'),
              state: row.getAttribute('data-runtime-state'),
              text: readText(row)
            }));
            const inputs = target.querySelectorAll('input').map((input) => ({
              type: input.type,
              name: input.name,
              value: input.value,
              checked: Boolean(input.checked),
              disabled: Boolean(input.disabled)
            }));
            const codexInput = target.querySelectorAll('input').find((input) => input.value === 'codex');
            codexInput.eventListeners.change.forEach((handler) => handler());
            const geminiInput = target.querySelectorAll('input').find((input) => input.value === 'gemini');
            geminiInput.eventListeners.change.forEach((handler) => handler());
            const emptyTarget = document.createElement('div');
            runtime.renderAssistantChoice(emptyTarget, { agents: [], assistant: {} });
            const undecidedTarget = document.createElement('div');
            runtime.renderAssistantChoice(undecidedTarget, { agents, assistant: undecided });
            process.stdout.write(JSON.stringify({
              bootstrapLabel: runtime.assistantSummaryLabel(bootstrap, agents),
              chosenLabel: runtime.assistantSummaryLabel(chosen, agents),
              goneLabel: runtime.assistantSummaryLabel(gone, agents),
              missingLabel: runtime.assistantSummaryLabel({ state: 'none_available' }, []),
              legend: target.querySelector('legend').textContent,
              launchedLabel: runtime.assistantSummaryLabel(launched, agents),
              onlyOneLabel: runtime.assistantSummaryLabel(onlyOne, agents),
              survivorLabel: runtime.assistantSummaryLabel(survivor, agents),
              undecidedLabel: runtime.assistantSummaryLabel(undecided, agents),
              workingLabel: runtime.assistantWorkingLabel(bootstrap),
              workingLabelUnknown: runtime.assistantWorkingLabel({}),
              undecidedLegend: undecidedTarget.querySelector('legend').textContent,
              undecidedChecked: undecidedTarget.querySelectorAll('input').filter((input) => input.checked).length,
              rows,
              inputs,
              selections,
              emptyText: readText(emptyTarget)
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(runtime_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["bootstrapLabel"], "Using Claude Code - the assistant that started GenomiLab")
        self.assertEqual(result["chosenLabel"], "Using Codex CLI - chosen for this workspace")
        # The streaming placeholder names the assistant actually running the
        # turn, so a workspace never claims a different one.
        self.assertEqual(result["workingLabel"], "Claude Code is working\u2026")
        self.assertEqual(result["workingLabelUnknown"], "Your assistant is working\u2026")
        self.assertEqual(result["launchedLabel"], "Using Claude Code - named with --agent when GenomiLab started")
        self.assertEqual(result["onlyOneLabel"], "Using Claude Code - the only assistant installed here")
        self.assertEqual(
            result["survivorLabel"],
            "Using Claude Code - the only installed assistant that has not failed in this workspace",
        )
        self.assertEqual(result["undecidedLabel"], "Choose which local assistant this workspace uses")
        self.assertEqual(result["undecidedLegend"], "Choose the assistant for this workspace")
        self.assertEqual(result["undecidedChecked"], 0)
        self.assertEqual(result["goneLabel"], "Claude Code is not available here - choose another below")
        self.assertEqual(result["missingLabel"], "No local assistant available")
        self.assertEqual(result["legend"], "Assistant for this workspace")
        self.assertEqual(
            result["inputs"],
            [
                {"type": "radio", "name": "workspace-assistant", "value": "codex", "checked": False, "disabled": False},
                {"type": "radio", "name": "workspace-assistant", "value": "claude", "checked": True, "disabled": False},
                {"type": "radio", "name": "workspace-assistant", "value": "gemini", "checked": False, "disabled": True},
                {"type": "radio", "name": "workspace-assistant", "value": "opencode", "checked": False, "disabled": True},
            ],
        )
        self.assertEqual(result["selections"], ["codex"])
        self.assertEqual(
            [row["testid"] for row in result["rows"]],
            [
                "genomi-assistant-option-codex",
                "genomi-assistant-option-claude",
                "genomi-assistant-option-gemini",
                "genomi-assistant-option-opencode",
            ],
        )
        self.assertEqual([row["state"] for row in result["rows"]], ["runnable", "runnable", "unavailable", "unavailable"])
        self.assertIn("Installed", result["rows"][0]["text"])
        self.assertIn("In use: the assistant that started GenomiLab.", result["rows"][1]["text"])
        self.assertIn("Last turn here stopped: usage allowance reached.", result["rows"][0]["text"])
        self.assertIn("Not supported yet", result["rows"][2]["text"])
        self.assertIn("Genomi has no verified driver for this assistant yet.", result["rows"][2]["text"])
        self.assertIn("Not installed", result["rows"][3]["text"])
        self.assertIn("Genomi did not find this assistant on this machine.", result["rows"][3]["text"])
        self.assertEqual(result["emptyText"], "No local assistant available.")

    def test_tool_catalog_models_source_lookup_detail(self) -> None:
        catalog_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_tool_catalog.js").as_uri()
        script = textwrap.dedent(
            f"""
            const catalog = await import({catalog_url!r});
            const tool = {{
              name: 'variant.resolve',
              description: 'Resolve rsid using /Users/matthewzmd/private/cache when supplied.',
              sourceLookup: {{
                name: 'variant.resolve',
                operationId: 'variant.resolve',
                displayLabel: 'Variant evidence lookup',
                area: 'variant',
                description: 'Resolve rsid using public variant sources.',
                badges: ['Metadata only', '1 required input'],
                request: {{
                  requiredInputs: ['rsid'],
                  fields: [
                    {{ name: 'rsid', label: 'rsID', required: true, type: 'string', summary: 'dbSNP rsid' }},
                    {{ name: 'genome_build', label: 'Genome build', type: 'string', defaultValue: 'GRCh38', defaultHint: 'GRCh38', summary: 'Use when known.' }}
                  ]
                }},
                sections: [
                  {{ title: 'Required inputs', nodes: [{{ label: 'rsID', value: 'dbSNP rsid' }}] }}
                ],
                technicalSections: [
                  {{ title: 'Default assumptions if omitted', nodes: [
                    {{ label: 'include_private_metadata', value: 'false' }},
                    {{ label: 'genome_build', value: 'GRCh38' }}
                  ] }},
                  {{ title: 'Output shape', nodes: [
                    {{ label: 'variant_resolution', value: 'tool output' }},
                    {{ label: 'evidence_envelope', value: 'tool output' }}
                  ] }},
                  {{ title: 'Dependencies', nodes: [
                    {{ label: 'External network', value: 'dbSNP' }}
                  ] }}
                ]
              }}
            }};
            const result = {{
              visible: catalog.visibleTools([tool, {{ name: 'genomi.install' }}]).map((item) => item.name),
              detail: catalog.toolInspectorModel(tool),
              legacyExports: {{
                toolPrompt: typeof catalog.toolPrompt,
                toolIntentPayload: typeof catalog.toolIntentPayload,
                toolRequestPrompt: typeof catalog.toolRequestPrompt,
                toolRequestPayload: typeof catalog.toolRequestPayload
              }}
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["visible"], ["variant.resolve"])
        self.assertEqual(result["detail"]["name"], "variant.resolve")
        self.assertEqual(result["detail"]["operationId"], "variant.resolve")
        self.assertEqual(result["detail"]["displayLabel"], "Variant evidence lookup")
        self.assertIn("rsid", result["detail"]["requiredInputs"])
        self.assertIn(
            {"label": "include_private_metadata", "value": "false"},
            result["detail"]["defaults"],
        )
        self.assertIn(
            {"label": "genome_build", "value": "GRCh38"},
            result["detail"]["defaults"],
        )
        self.assertIn(
            {"label": "variant_resolution", "value": "tool output"},
            next(section for section in result["detail"]["technicalSections"] if section["title"] == "Output shape")["nodes"],
        )
        self.assertTrue(any("External network" in item for item in result["detail"]["dependencies"]))
        self.assertEqual(
            result["legacyExports"],
            {
                "toolPrompt": "undefined",
                "toolIntentPayload": "undefined",
                "toolRequestPrompt": "undefined",
                "toolRequestPayload": "undefined",
            },
        )
        _assert_public_payload(result)

    def test_genome_context_models_attach_public_context(self) -> None:
        context_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_genome_context.js").as_uri()
        context_source = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_genome_context.js").read_text(
            encoding="utf-8"
        )
        script = textwrap.dedent(
            f"""
            const context = await import({context_url!r});
            const runtime = {{
              genomiVersion: '0.1.0',
              context: {{
                status: 'available',
                has_active_genome_index: true,
                context_policy: {{ mode: 'explicit', implicit_artifact_selection: false }},
                active_genome_index_access: {{ approved: true, scope: 'persistent_default' }},
                active_genome_index: {{
                  status: 'parsed',
                  genome_build: 'GRCh38',
                  source_type: 'vcf',
                  active_genome_index_readiness: {{
                    status: 'completed',
                    complete: true,
                    variants_ready: false
                  }}
                }},
                active_genome_index_registry: {{
                  known_agi_count: 3,
                  known_user_count: 2,
                  resume_requires: 'Explicit approval required'
                }},
                selection_source: 'default_user_auto_select',
                default_auto_selected: true,
                context_axes: {{ active_genome_index: {{ current_state: 'active_accessible', known_agis: 3 }} }},
                active_response_profile: {{ id: 'eli5', label: 'Explain to me like I am 5' }}
              }},
              mcp: {{ endpoint: '/mcp', transport: 'streamable-http' }}
            }};
            const selectedRoot = {{
              querySelectorAll: () => [
                {{ dataset: {{ label: 'Current genome / Build', context: 'Active genome / Current genome / Build: GRCh38', value: 'GRCh38' }} }},
                {{ dataset: {{ label: 'Private leak', context: 'context_file=/Users/matthewzmd/.genomi/context.json', value: '/tmp/private.txt' }} }}
              ]
            }};
            const noAgi = {{
              context: {{
                status: 'available',
                has_active_genome_index: false,
                context_policy: {{ mode: 'explicit' }},
                active_genome_index_access: {{ approved: false }},
                active_genome_index_registry: {{ known_agi_count: 0, known_user_count: 0 }}
              }},
              mcp: {{ endpoint: '/mcp', transport: 'streamable-http' }}
            }};
            const approvalRequired = {{
              context: {{
                status: 'available',
                has_active_genome_index: true,
                context_policy: {{ mode: 'explicit' }},
                active_genome_index_access: {{ approved: false, scope: 'current_session' }},
                active_genome_index: {{
                  status: 'parsed',
                  genome_build: 'GRCh38',
                  active_genome_index_readiness: {{ status: 'completed', complete: true }}
                }},
                active_genome_index_registry: {{ known_agi_count: 1, known_user_count: 1 }},
                context_axes: {{ active_genome_index: {{ current_state: 'approval_required' }} }}
              }},
              mcp: {{ endpoint: '/mcp', transport: 'streamable-http' }}
            }};
            const incompleteAgi = {{
              context: {{
                status: 'available',
                has_active_genome_index: true,
                context_policy: {{ mode: 'explicit' }},
                active_genome_index_access: {{ approved: true, scope: 'current_session' }},
                active_genome_index: {{
                  status: 'parsing',
                  genome_build: 'GRCh38',
                  active_genome_index_readiness: {{ status: 'in_progress', complete: false }}
                }},
                active_genome_index_registry: {{ known_agi_count: 1, known_user_count: 1 }},
                context_axes: {{ active_genome_index: {{ current_state: 'parsing' }} }}
              }},
              mcp: {{ endpoint: '/mcp', transport: 'streamable-http' }}
            }};
            const unknownReadinessAgi = {{
              context: {{
                status: 'available',
                has_active_genome_index: true,
                context_policy: {{ mode: 'explicit' }},
                active_genome_index_access: {{ approved: true, scope: 'current_session' }},
                active_genome_index: {{
                  status: 'parsed',
                  genome_build: 'GRCh38'
                }},
                active_genome_index_registry: {{ known_agi_count: 1, known_user_count: 1 }},
                context_axes: {{ active_genome_index: {{ current_state: 'active_accessible' }} }}
              }},
              mcp: {{ endpoint: '/mcp', transport: 'streamable-http' }}
            }};
            const result = {{
              model: context.genomeContextViewModel(runtime),
              payload: context.genomeContextPayload(runtime),
              selectedPayload: context.genomeContextPayloadForSelection(runtime, selectedRoot),
              noAgi: context.genomeContextViewModel(noAgi),
              approvalRequired: context.genomeContextViewModel(approvalRequired),
              incompleteAgi: context.genomeContextViewModel(incompleteAgi),
              unknownReadinessAgi: context.genomeContextViewModel(unknownReadinessAgi)
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["model"]["title"], "GRCh38 · VCF genome")
        self.assertEqual(result["model"]["status"], "ready")
        self.assertFalse(result["model"]["canAttach"])
        self.assertEqual(result["model"]["identity"]["summaryLabel"], "GRCh38 · VCF")
        self.assertNotIn("Genome accessible", result["model"]["badges"])
        self.assertIn("Selected for this workspace", result["model"]["badges"])
        self.assertIn("Current genome", [section["title"] for section in result["model"]["sections"]])
        self.assertIn("Available genomes", [section["title"] for section in result["model"]["sections"]])
        self.assertIn("Privacy boundary", [section["title"] for section in result["model"]["sections"]])
        self.assertNotIn("Response profile", [section["title"] for section in result["model"]["sections"]])
        self.assertEqual(result["payload"]["label"], "Active genome: GRCh38 · VCF genome")
        self.assertEqual(result["payload"]["source_operation"], "genomi.describe_context")
        self.assertIn("Active genome / Current genome / Build: GRCh38", result["payload"]["prompt_text"])
        self.assertIn("Active genome / Privacy boundary / Other workspaces: Not shared automatically", result["payload"]["prompt_text"])
        self.assertIn("Active genome / Privacy boundary / This workspace: Selected for this workspace", result["payload"]["prompt_text"])
        self.assertNotIn("persistent_default", json.dumps(result["model"]))
        self.assertNotIn("default_user_auto_select", json.dumps(result["model"]))
        self.assertNotIn("default_user_auto_select", result["payload"]["prompt_text"])
        self.assertNotIn("Selected by", result["payload"]["prompt_text"])
        self.assertIn("Selected active genome facts", result["selectedPayload"]["prompt_text"])
        self.assertIn("Active genome / Current genome / Build: GRCh38", result["selectedPayload"]["prompt_text"])
        _assert_public_payload(result["payload"])
        _assert_public_payload(result["selectedPayload"])
        self.assertEqual(result["noAgi"]["title"], "Choose a genome")
        self.assertEqual(result["noAgi"]["status"], "empty")
        self.assertFalse(result["noAgi"]["canAttach"])
        self.assertIn("Choose one", result["noAgi"]["actionHint"])
        self.assertEqual(result["approvalRequired"]["title"], "Choose this genome for the workspace")
        self.assertEqual(result["approvalRequired"]["status"], "blocked")
        self.assertFalse(result["approvalRequired"]["canAttach"])
        self.assertIn("Available genomes", result["approvalRequired"]["actionHint"])
        self.assertEqual(result["approvalRequired"]["badges"], ["Not selected"])
        self.assertEqual(result["incompleteAgi"]["title"], "GRCh38 genome")
        self.assertEqual(result["incompleteAgi"]["status"], "ready")
        self.assertFalse(result["incompleteAgi"]["canAttach"])
        self.assertEqual(result["incompleteAgi"]["actionHint"], "")
        self.assertNotIn("Genome incomplete", result["incompleteAgi"]["badges"])
        self.assertEqual(result["unknownReadinessAgi"]["title"], "GRCh38 genome")
        self.assertEqual(result["unknownReadinessAgi"]["status"], "ready")
        self.assertFalse(result["unknownReadinessAgi"]["canAttach"])
        self.assertEqual(result["unknownReadinessAgi"]["actionHint"], "")
        self.assertNotIn("Check readiness", result["unknownReadinessAgi"]["badges"])
        self.assertNotIn("query-ready", json.dumps(result))
        self.assertIn("sectionEl(sectionModel, { selectable: model.canAttach })", context_source)
        self.assertIn("options.selectable ? nodeButton(sectionModel.title, item) : nodeRow(item)", context_source)

    def test_live_result_actions_can_submit_selected_context(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"
        html = portal_assets._portal_html("test-csrf-token")
        portal = (root / "portal.js").read_text()
        genomilab = (root / "portal_genomilab.js").read_text()
        messages = (root / "portal_messages.js").read_text()
        starter_cards = (root / "portal_starter_cards.js").read_text()
        operation_labels = (root / "portal_operation_labels.js").read_text()
        result_renderers = (root / "portal_result_renderers.js").read_text()
        evidence_panel = (root / "portal_evidence_panel.js").read_text()
        artifacts = (root / "portal_artifacts.js").read_text()
        artifact_actions = (root / "portal_artifact_actions.js").read_text()
        genome_context = (root / "portal_genome_context.js").read_text()
        selection_actions = (root / "portal_selection_actions.js").read_text()
        prompt_context = (root / "portal_prompt_context.js").read_text()
        api = (root / "portal_api.js").read_text()
        portal_css = (root / "portal.css").read_text()
        tool_catalog = (root / "portal_tool_catalog.js").read_text()
        tool_request_builder = (root / "portal_tool_request_builder.js").read_text()
        refresh_url = (root / "portal_message_refresh.js").as_uri()
        script = textwrap.dedent(
            f"""
            const refresh = await import({refresh_url!r});
            const result = {{
              currentFrame: refresh.shouldReloadFrameMessages({{ frame_id: 'frame_1' }}, {{ frameId: 'frame_1' }}),
              otherFrame: refresh.shouldReloadFrameMessages({{ frame_id: 'frame_2' }}, {{ frameId: 'frame_1' }}),
              missingFrame: refresh.shouldReloadFrameMessages({{}}, {{ frameId: 'frame_1' }}),
              liveFrame: refresh.shouldReloadFrameMessages({{ frame_id: 'frame_1' }}, {{ frameId: 'frame_1', liveMessageFrameId: 'frame_1' }}),
              activeRun: refresh.shouldReloadFrameMessages({{ frame_id: 'frame_1' }}, {{ frameId: 'frame_1', activeRun: {{ frameId: 'frame_1' }} }}),
              otherActiveRun: refresh.shouldReloadFrameMessages({{ frame_id: 'frame_1' }}, {{ frameId: 'frame_1', activeRun: {{ frameId: 'frame_2' }} }})
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertIn('id="prompt-context"', html)
        self.assertNotIn('class="genome-context-mode"', html)
        self.assertNotIn('name="genome-context-mode"', html)
        self.assertNotIn('Use active genome when relevant', html)
        self.assertIn('id="context-summary-action"', html)
        self.assertIn('id="context-detail"', html)
        self.assertIn('id="add-genome"', html)
        self.assertIn('id="switch-genome"', html)
        self.assertIn('<details class="rail-card runtime-card">', html)
        self.assertIn('<summary>Local assistant</summary>', html)
        self.assertIn('id="workspace-search"', html)
        self.assertIn('<details class="pane-menu">', html)
        self.assertIn('<summary>More</summary>', html)
        self.assertIn('data-nav-target="artifact-workspace"', html)
        self.assertIn('id="artifact-back"', html)
        self.assertIn('id="artifact-preview" class="artifact-preview" hidden', html)
        self.assertIn("function renderArtifactWorkspaceMode()", portal)
        self.assertIn("$('artifact-back').addEventListener('click', closeArtifactPreview)", portal)
        self.assertIn("const frameIdToOpen = route.frameId || savedFrameIdForProject(projectId);", portal)
        self.assertIn('<nav class="nav" data-workspace-nav>', html)
        self.assertIn('<details class="advanced-nav">', html)
        self.assertIn('<summary>Workspace details</summary>', html)
        advanced_nav = html.split('<details class="advanced-nav">', 1)[1].split('</details>', 1)[0]
        self.assertIn('data-evidence-ledger-nav data-nav-target="evidence-ledger-pane"', advanced_nav)
        self.assertIn('data-nav-target="evidence-ledger-pane"', advanced_nav)
        self.assertIn('data-nav-target="work-trace-pane">Work trail</button>', advanced_nav)
        self.assertIn('data-nav-target="genome-index">Active genome</button>', advanced_nav)
        self.assertIn('<nav class="mobile-nav" data-workspace-nav aria-label="Workspace sections">', html)
        mobile_nav = html.split('<nav class="mobile-nav"', 1)[1].split('</nav>', 1)[0]
        self.assertIn(
            'data-mobile-work-trace-nav data-nav-target="work-trace-pane" hidden>Work trail</button>',
            mobile_nav,
        )
        self.assertIn(
            'data-mobile-source-nav data-nav-target="tool-launcher" hidden>Evidence sources</button>',
            mobile_nav,
        )
        self.assertIn('data-evidence-ledger-nav data-nav-target="evidence-ledger-pane"', mobile_nav)
        source_handoff_assets = "\n".join([html, tool_catalog, tool_request_builder])
        self.assertIn('data-starter-card-id="investigate-health-question"', html)
        self.assertIn('data-starter-card-id="review-a-medication"', html)
        self.assertIn('data-source-operation="genomi.parse_source"', html)
        self.assertIn("portal_starter_cards.js", messages)
        self.assertNotIn('data-source-operation="genomi.parse_source"', messages)
        self.assertNotIn('{"target_type":"topic"}', messages)
        self.assertNotIn('{"rsid":"rs429358"}', messages)
        self.assertNotIn("Plan public evidence", html)
        self.assertNotIn("Plan public evidence", messages)
        self.assertIn("Choose an evidence source to use in chat.", source_handoff_assets)
        self.assertIn("Add any details you know. Genomi will preserve source limits and ask for missing details in chat.", source_handoff_assets)
        self.assertIn("Include source", source_handoff_assets)
        self.assertIn("Ask now", source_handoff_assets)
        self.assertNotIn("Use in chat", source_handoff_assets)
        self.assertNotIn("Draft question", source_handoff_assets)
        self.assertIn("async function openSourceSuggestion(button)", portal)
        self.assertIn("sourceSuggestionParams(button)", portal)
        self.assertIn("markStarterSourceUnavailable(button", portal)
        source_click_block = portal.split("if (button.getAttribute('data-source-operation'))", 1)[1].split("return;", 1)[0]
        self.assertNotIn("promptContext.setPromptText", source_click_block)
        self.assertIn("markStarterSourceUnavailable", source_click_block)
        self.assertIn("initialParams: activeTool ? evidenceSourceParamsFor(activeTool) : {}", portal)
        self.assertIn("welcomeMessageMarkup(model = portalStarterModel())", starter_cards)
        self.assertIn('data-testid="genomi-chat-welcome"', starter_cards)
        self.assertIn("list.querySelector('[data-testid=\"genomi-chat-welcome\"]')", messages)
        self.assertNotIn("research.build_target_packet", tool_request_builder)
        self.assertNotIn("Attach source", source_handoff_assets)
        self.assertNotIn("attach this source", source_handoff_assets)
        self.assertNotIn("attach to your next question", source_handoff_assets)
        self.assertNotIn("Attach public", source_handoff_assets)
        self.assertNotIn("Source checks", source_handoff_assets)
        self.assertNotIn("Source check", source_handoff_assets)
        self.assertNotIn("Prepare", source_handoff_assets)
        self.assertNotIn("Preparation", source_handoff_assets)
        self.assertIn('id="work-trace-pane" class="pane" data-nav-section="work-trace-pane" hidden', html)
        self.assertIn('id="genome-index" class="pane" data-nav-section="genome-index" hidden', html)
        self.assertIn('id="tool-launcher" class="pane" data-nav-section="tool-launcher" hidden', html)
        intake = html.split('<section class="genomilab-intake"', 1)[1].split('</section>', 1)[0]
        self.assertEqual(intake.count('<button'), 1)
        self.assertIn('data-nav-target="genome-index"', intake)
        self.assertIn('Active genome', intake)
        self.assertIn('Ask in your own words', intake)
        self.assertNotIn('data-genomilab-open', html)
        self.assertNotIn('id="patient-context-pane"', html)
        self.assertNotIn('id="research-connections-pane"', html)
        self.assertIn('id="genomilab-case-board"', html)
        self.assertIn("await loadBoard();", genomilab)
        self.assertNotIn("loadGenomiLabProfile", genomilab)
        self.assertNotIn("loadGenomiLabIntegrations", genomilab)
        self.assertIn(
            "new Set(['evidence-ledger-pane', 'work-trace-pane', 'genome-index', 'tool-launcher'])",
            portal,
        )
        self.assertIn("document.querySelectorAll('[data-workspace-nav]').forEach", portal)
        self.assertIn("document.querySelectorAll('[data-evidence-ledger-nav]').forEach", portal)
        self.assertIn("onStateChange: updateWorkspaceDetailNavVisibility", portal)
        self.assertIn("function updateWorkspaceDetailNavVisibility()", portal)
        self.assertIn("document.querySelectorAll('[data-mobile-work-trace-nav]').forEach", portal)
        self.assertIn("document.querySelectorAll('[data-mobile-source-nav]').forEach", portal)
        self.assertIn("nav.hidden = !hasWorkTrace && state.activeWorkspaceSection !== 'work-trace-pane';", portal)
        self.assertIn("nav.hidden = state.activeWorkspaceSection !== 'tool-launcher';", portal)
        self.assertNotIn('id="evidence-ledger-nav"', html)
        self.assertIn("pane.hidden = !hasEvidence || state.activeWorkspaceSection !== 'evidence-ledger-pane'", portal)
        self.assertIn("function revealWorkspaceSection(target, section)", portal)
        self.assertIn("document.body.dataset.activeWorkspaceSection = state.activeWorkspaceSection;", portal)
        self.assertIn("document.body.dataset.activeWorkspaceSection = target;", portal)
        self.assertIn(".main { grid-template-rows: auto auto minmax(0, 1fr); }", portal_css)
        self.assertIn(".chat { display: grid; grid-template-rows: auto auto minmax(0, 1fr) auto auto;", portal_css)
        self.assertIn("display: flex;\n    align-items: center;\n    gap: 8px;", portal_css)
        self.assertIn('body[data-active-workspace-section="research-workspace"] .right-stack { display: none; }', portal_css)
        self.assertIn('body[data-active-workspace-section]:not([data-active-workspace-section="research-workspace"]) #research-workspace { display: none; }', portal_css)
        self.assertIn('body[data-active-workspace-section="artifact-workspace"] .right-stack > .pane:not(#artifact-workspace)', portal_css)
        self.assertIn('body[data-active-workspace-section="genome-index"] .right-stack > .pane:not(#genome-index)', portal_css)
        self.assertIn('id="workspace-files"', html)
        self.assertIn('href="/assets/portal_evidence_sources.css"', html)
        self.assertIn('href="/assets/portal_selection_states.css"', html)
        self.assertIn('href="/assets/portal_artifact_actions.css"', html)
        self.assertIn('href="/assets/portal_prompt_context.css"', html)
        self.assertIn("portal_evidence_sources.css", portal_assets.template_asset_names())
        self.assertIn("portal_selection_states.css", portal_assets.template_asset_names())
        self.assertIn("portal_artifact_actions.css", portal_assets.template_asset_names())
        self.assertIn("portal_prompt_context.css", portal_assets.template_asset_names())
        self.assertIn("portal_artifact_preview.js", portal_assets.template_asset_names())
        self.assertIn("portal_active_context_client.js", portal_assets.template_asset_names())
        self.assertIn("portal_workspace_files.js", portal_assets.template_asset_names())
        self.assertIn("portal_genome_inventory.js", portal_assets.template_asset_names())
        self.assertIn("portal_selection_actions.js", portal_assets.template_asset_names())
        self.assertIn("portal_starter_cards.js", portal_assets.template_asset_names())
        self.assertIn("frame.title || frame.display_request || frame.displayRequest || frame.request", portal)
        self.assertIn('id="conversation-search"', html)
        self.assertIn('id="conversation-title"', html)
        self.assertIn('id="conversation-rename"', html)
        self.assertIn("function renderConversationIdentity()", portal)
        self.assertIn("api.renameConversation(state.project.project_id, frame.id, title)", portal)
        self.assertIn("state.conversationSearchQuery", portal)
        self.assertIn("createWorkspaceFileController", portal)
        self.assertIn("onViewContext: viewWorkspaceFileContext", portal)
        self.assertIn("function viewWorkspaceFileContext(originContext)", portal)
        self.assertIn("createActiveContextClient", portal)
        self.assertNotIn("activeContextTimer", portal)
        self.assertNotIn("activeContextSerial", portal)
        self.assertNotIn("run the next focused Genomi evidence step", portal)
        self.assertNotIn("evidence-envelope limits", portal)
        self.assertIn("loadProjectWorkspaceFiles", portal)
        self.assertIn("onAskContext: askPromptContext", portal)
        self.assertIn("function askPromptContext(context)", portal)
        self.assertIn("onAskNewContext: askPromptContextInNewConversation", portal)
        self.assertIn("onAskNewFile: askPromptContextInNewConversation", portal)
        self.assertIn("function askPromptContextInNewConversation(context)", portal)
        self.assertIn("onAskNewConversation: askSelectedEvidenceInNewConversation", portal)
        self.assertIn("function askSelectedEvidenceInNewConversation(contexts, options = {})", portal)
        self.assertIn("function includeGenomeContext(context)", portal)
        self.assertIn("onIncludeGenome: includeGenomeContext", portal)
        self.assertIn("promptContext.askWith(context)", portal)
        self.assertIn("promptContext.askNewWith(context)", portal)
        self.assertIn("const attached = promptContext.add(text)", portal)
        self.assertIn("if (attached) activateWorkspaceSection('research-workspace', { replaceHash: false })", portal)
        self.assertIn("promptContext.draftWith(context)", portal)
        self.assertIn(".then((attached) =>", portal)
        self.assertIn("'aria-label', 'Attached to next message'", prompt_context)
        self.assertIn("'data-testid', 'prompt-context-card'", prompt_context)
        self.assertIn("remove.className = 'prompt-context-remove'", prompt_context)
        self.assertNotIn("prompt-context-ask-context", prompt_context)
        self.assertNotIn("prompt-context-ask-new-context", prompt_context)
        self.assertNotIn("prompt-context-draft-context", prompt_context)
        self.assertIn("'genomi-artifact-start-conversation'", artifact_actions)
        self.assertIn("options.onAskNewContext(artifactContextPayload(artifact))", artifact_actions)
        self.assertIn("export { renderArtifactPreview } from './portal_artifact_preview.js'", artifacts)
        self.assertIn("async function attachEvidenceSourceRequest(tool, params = {})", portal)
        self.assertIn("api.attachEvidenceSource(evidenceSourceOperationId(tool), params || {})", portal)
        self.assertIn("async function askToolRequest(tool, params)", portal)
        self.assertIn("onAskRequest: askToolRequest", portal)
        self.assertIn("toolCatalogLoadPromise", portal)
        self.assertIn("async function runToolCatalogLoad()", portal)
        self.assertIn("if (state.toolCatalogStatus === 'loading' && state.toolCatalogLoadPromise)", portal)
        self.assertIn("state.activeToolName = null;", portal)
        self.assertNotIn("state.activeToolName = state.tools[0] && state.tools[0].name", portal)
        self.assertIn("function frameStatusLabel(status)", portal)
        self.assertIn("function frameMessageCountLabel(count)", portal)
        self.assertIn("String(project.name || '').trim() || 'Research workspace'", portal)
        self.assertNotIn("state.project.name + ' · ' + state.project.project_id", portal)
        self.assertNotIn("(frame.agent_id || 'agent')", portal)
        self.assertIn(
            "async function submitTurnDraft({ message, selectedEvidence, presentationKind = '', forceNewFrame = false, onSuccess, onError })",
            portal,
        )
        self.assertNotIn("function selectedGenomeContextMode()", portal)
        self.assertNotIn("selectedGenomeContextMode()", portal)
        self.assertIn("messageSurface.addMessage('user', cleanMessage, contexts, {", portal)
        self.assertIn("presentationKind: effectivePresentationKind", portal)
        self.assertIn("const sourceFrameId = forceNewFrame ? state.frameId : '';", portal)
        self.assertIn("startedFromSelectedMaterial: Boolean(forceNewFrame && startedFromSelectedMaterial)", portal)
        self.assertIn("function frameDetailText(frame)", portal)
        self.assertIn("frame.started_from", portal)
        self.assertIn("sourceFrameId, startedFromSelectedMaterial, message", api)
        self.assertIn("genomeContextMode", api)
        self.assertIn("...(genomeContextMode ? { genomeContextMode } : {})", api)
        self.assertIn("...(sourceFrameId ? { sourceFrameId } : {})", api)
        self.assertIn("...(startedFromSelectedMaterial ? { startedFromSelectedMaterial: true } : {})", api)
        self.assertLess(
            portal.index("const sourceFrameId = forceNewFrame ? state.frameId : '';"),
            portal.index("if (forceNewFrame) newChat();"),
        )
        self.assertIn('id="agent-list"', html)
        self.assertIn("portal_runtime_status.js", portal_assets.template_asset_names())
        self.assertIn("renderAssistantChoice($('agent-list')", portal)
        self.assertIn("api.selectWorkspaceAssistant(projectId, agentId)", portal)

        self.assertIn("submitTurnDraft({ message, selectedEvidence }).catch", portal)
        self.assertIn("if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;", portal)
        self.assertIn("$('composer').requestSubmit();", portal)
        self.assertIn("data.type === 'diagnostic' || data.type === 'tool_call'", portal)
        self.assertNotIn("messageSurface.appendText(body, '\\\\n[' + data.name + ']\\\\n')", portal)
        self.assertNotIn("host_agent_stdout", portal)
        self.assertNotIn("host_agent_stderr", portal)
        self.assertNotIn("messageSurface.addToolEvent('diagnostic'", portal)
        self.assertNotIn("messageSurface.appendText(body, '\\\\nstderr: ' + data.chunk)", portal)
        self.assertIn("function diagnosticRecordModel(events)", messages)
        self.assertIn("function isOnlyGenomeContext(contexts)", portal)
        self.assertIn("focusGenomeQuestionComposer();", portal)
        self.assertIn("async function openGenomeSourceTool()", portal)
        self.assertIn("function focusGenomeInventory()", portal)
        self.assertIn("async function selectGenomeFromInventory(selection)", portal)
        self.assertIn("api.selectGenome(state.project.project_id, selection)", portal)
        self.assertIn("await loadProjectGenomeContext()", portal)
        self.assertIn("activateWorkspaceSection('genome-index')", portal)
        self.assertIn("showEvidenceSourceUnavailable(", portal)
        self.assertIn("activateWorkspaceSection('tool-launcher')", portal)
        self.assertIn("workspaceSearchQuery", portal)
        self.assertIn("messageSurface.reset();", portal)
        self.assertIn("promptContext.clear();", portal)
        self.assertIn("await api.selectProject(cleanProjectId);\n      clearWorkspaceState();", portal)
        self.assertIn("Showing ' + String(visibleProjects.length) + ' of ' + String(matches.length)", portal)
        self.assertNotIn("Use this genome source for this workspace", portal)
        self.assertNotIn('The evidence source "', portal)
        self.assertNotIn("Include active genome", genome_context)
        self.assertNotIn("genomi-genome-include-active", genome_context)
        self.assertNotIn("Ask with active genome", genome_context)
        self.assertNotIn("genomi-genome-ask-with-active", genome_context)
        self.assertNotIn("Include active genome summary", genome_context)
        self.assertNotIn("Include selected genome facts", genome_context)
        self.assertIn(".genome-topbar-control {\n    width: 100%;\n    flex-wrap: wrap;", portal_css)
        self.assertIn(".genome-status-button {\n    flex: 1 1 100%;", portal_css)
        self.assertIn(".genome-topbar-action {\n    flex: 1 1 calc(50% - 4px);", portal_css)
        self.assertIn("Ask a genetics question. Genomi will use the approved active genome only when it is relevant.", portal)
        self.assertIn("function diagnosticRecordKey(scope = {})", messages)
        self.assertIn("if (kind === 'diagnostic')", messages)
        self.assertIn("record.kind = 'diagnostic';", messages)
        self.assertNotIn("host_agent_diagnostics", messages)
        self.assertNotIn("host_agent_diagnostics", operation_labels)
        self.assertTrue(result["currentFrame"])
        self.assertFalse(result["otherFrame"])
        self.assertFalse(result["missingFrame"])
        self.assertFalse(result["liveFrame"])
        self.assertFalse(result["activeRun"])
        self.assertTrue(result["otherActiveRun"])
        self.assertIn("state.liveMessageFrameId = frameId", portal)
        self.assertIn("onAskContext", messages)
        self.assertIn("onAskNewContext", messages)
        self.assertIn("onAskNewContext: askPromptContextInNewConversation", portal)
        self.assertIn("onDraftContext", messages)
        self.assertIn("onDraftContext: draftPromptContext", portal)
        self.assertNotIn("data-action=\"ask-selected\"", messages)
        self.assertNotIn("data-action=\"draft-selected\"", messages)
        self.assertNotIn("assistantEvidenceChecklistSelectionModel", messages)
        self.assertNotIn("assistantEvidenceChecklistModel", messages)
        self.assertNotIn("Evidence I would inspect", messages)
        self.assertNotIn("message-evidence-checklist", messages)
        self.assertIn("renderToolDetails(details, record", messages)
        self.assertIn("messageSurface.renderStoredMessages(", portal)
        self.assertNotIn("state.frameMessages", portal)
        self.assertIn("function renderMessageArtifacts()", portal)
        self.assertIn("messageSurface.renderInlineArtifacts(state.artifacts", portal)
        self.assertIn("renderMessageArtifacts();", portal)
        self.assertIn("renderInlineArtifacts", messages)
        self.assertIn("message-artifact-strip", messages)
        self.assertIn("if (plan.items.length) list.innerHTML = '';", messages)
        self.assertIn("heading: 'Generated'", (root / "portal_artifacts.js").read_text())
        self.assertIn("if (!options.keepArtifactOpen) clearArtifactSelection();", portal)
        self.assertNotIn("state.frameMessages.forEach(messageSurface.renderStoredMessage)", portal)
        self.assertIn("genomi-result-ask-selected", result_renderers)
        self.assertIn("options.onAskContext(selectedEvidencePayload(panel, model, record))", result_renderers)
        self.assertIn("genomi-result-ask-new-selected", result_renderers)
        self.assertIn("options.onAskNewContext(selectedEvidencePayload(panel, model, record))", result_renderers)
        self.assertIn("genomi-result-draft-selected", result_renderers)
        self.assertIn("options.onDraftContext(selectedEvidencePayload(panel, model, record))", result_renderers)
        self.assertIn("selectionActionLabels(", result_renderers)
        self.assertIn("genomi-evidence-ask-selected", evidence_panel)
        self.assertIn("options.onAskContext(selectedEvidencePayload(panel, normalized, record, toolName))", evidence_panel)
        self.assertIn("genomi-evidence-ask-new-selected", evidence_panel)
        self.assertIn("options.onAskNewContext(selectedEvidencePayload(panel, normalized, record, toolName))", evidence_panel)
        self.assertIn("genomi-evidence-draft-selected", evidence_panel)
        self.assertIn("options.onDraftContext(selectedEvidencePayload(panel, normalized, record, toolName))", evidence_panel)
        self.assertIn("selectionActionLabels(", evidence_panel)
        self.assertIn("Ask about selection", selection_actions)
        self.assertIn("Draft from selection", selection_actions)

    def test_starter_cards_render_from_server_model(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"
        starter_url = (root / "portal_starter_cards.js").as_uri()
        model = portal_starter_cards.welcome_model()
        rendered_html = portal_assets._portal_html("test-csrf-token")

        self.assertEqual(
            [card["id"] for card in model["cards"]],
            ["investigate-health-question", "review-a-medication", "add-genome"],
        )
        self.assertEqual(
            [card["label"] for card in model["cards"]],
            ["Investigate a health question", "Review a medication", "Add your genome"],
        )
        self.assertEqual(
            [card.get("sourceOperation", "") for card in model["cards"]],
            ["", "", "genomi.parse_source"],
        )
        self.assertTrue(model["cards"][0]["prompt"].strip())
        self.assertTrue(model["cards"][1]["prompt"].strip())
        self.assertIn('id="genomi-starter-cards" type="application/json"', rendered_html)
        self.assertIn('data-starter-card-id="investigate-health-question"', rendered_html)
        self.assertIn('data-source-operation="genomi.parse_source"', rendered_html)
        self.assertNotIn("Use this genome source for this workspace", rendered_html)
        self.assertIn("closest('[data-source-operation], [data-prompt]')", (root / "portal.js").read_text())

        script = textwrap.dedent(
            f"""
            const starter = await import({starter_url!r});
            globalThis.document = {{
              getElementById(id) {{
                return id === 'genomi-starter-cards'
                  ? {{ textContent: {json.dumps(json.dumps(model))} }}
                  : null;
              }}
            }};
            const markup = starter.welcomeMessageMarkup();
            process.stdout.write(JSON.stringify({{
              cardCount: (markup.match(/class="suggestion-chip"/g) || []).length,
              parseSource: markup.includes('data-source-operation="genomi.parse_source"'),
              investigate: markup.includes('data-starter-card-id="investigate-health-question"'),
              medication: markup.includes('data-starter-card-id="review-a-medication"'),
              promptAttrs: (markup.match(/data-prompt=/g) || []).length,
              rawGenomePrompt: markup.includes('Use this genome source for this workspace')
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["cardCount"], 3)
        self.assertTrue(result["parseSource"])
        self.assertTrue(result["investigate"])
        self.assertTrue(result["medication"])
        self.assertEqual(result["promptAttrs"], 2)
        self.assertFalse(result["rawGenomePrompt"])

    def test_source_starter_unavailable_state_is_visible(self) -> None:
        starter_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_starter_cards.js").as_uri()
        script = textwrap.dedent(
            f"""
            class Element {{
              constructor(tagName) {{
                this.tagName = String(tagName || '').toLowerCase();
                this.children = [];
                this.attributes = {{}};
                this.dataset = {{}};
                this.textContent = '';
              }}
              appendChild(child) {{
                this.children.push(child);
                return child;
              }}
              setAttribute(name, value) {{
                const text = String(value || '');
                this.attributes[name] = text;
                if (name.startsWith('data-')) this.dataset[dataKey(name.slice(5))] = text;
              }}
              getAttribute(name) {{
                return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
              }}
              removeAttribute(name) {{
                delete this.attributes[name];
                if (name.startsWith('data-')) delete this.dataset[dataKey(name.slice(5))];
              }}
              querySelector(selector) {{
                if (selector === '[data-starter-card-detail]') {{
                  return this.children.find((child) => child.getAttribute && child.getAttribute('data-starter-card-detail') !== null) || null;
                }}
                if (selector === 'span') return this.children.find((child) => child.tagName === 'span') || null;
                return null;
              }}
            }}
            function dataKey(name) {{
              return name.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
            }}
            const starter = await import({starter_url!r});
            const button = new Element('button');
            const detail = new Element('span');
            detail.setAttribute('data-starter-card-detail', '');
            detail.textContent = 'Choose a gene, variant, drug, condition, or topic to review.';
            button.appendChild(detail);

            starter.setStarterCardPending(button);
            const pending = {{
              state: button.dataset.sourceState,
              detail: detail.textContent,
              live: button.getAttribute('aria-live')
            }};
            starter.markStarterSourceUnavailable(button, 'Catalog request failed');
            const unavailable = {{
              state: button.dataset.sourceState,
              detail: detail.textContent,
              live: button.getAttribute('aria-live'),
              flag: detail.getAttribute('data-source-unavailable')
            }};
            starter.clearStarterCardState(button);
            const cleared = {{
              state: button.dataset.sourceState || '',
              detail: detail.textContent,
              live: button.getAttribute('aria-live') || '',
              flag: detail.getAttribute('data-source-unavailable') || ''
            }};
            process.stdout.write(JSON.stringify({{ pending, unavailable, cleared }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["pending"]["state"], "loading")
        self.assertEqual(result["pending"]["detail"], "Opening evidence source...")
        self.assertEqual(result["pending"]["live"], "polite")
        self.assertEqual(result["unavailable"]["state"], "unavailable")
        self.assertIn("Evidence source unavailable. Catalog request failed", result["unavailable"]["detail"])
        self.assertEqual(result["unavailable"]["live"], "polite")
        self.assertEqual(result["unavailable"]["flag"], "true")
        self.assertEqual(result["cleared"]["state"], "")
        self.assertEqual(result["cleared"]["detail"], "Choose a gene, variant, drug, condition, or topic to review.")
        self.assertEqual(result["cleared"]["live"], "")
        self.assertEqual(result["cleared"]["flag"], "")

    def test_evidence_source_styles_live_in_focused_asset(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"
        html = (root / "portal.html").read_text()
        portal_css = (root / "portal.css").read_text()
        evidence_source_css = (root / "portal_evidence_sources.css").read_text()

        self.assertIn('href="/assets/portal_evidence_sources.css"', html)
        self.assertIn("portal_evidence_sources.css", portal_assets.template_asset_names())
        self.assertIn(".tool-launcher-list", evidence_source_css)
        self.assertIn(".tool-inspector-card", evidence_source_css)
        self.assertIn(".tool-request-builder", evidence_source_css)
        self.assertIn(".tool-request-guided-targets", evidence_source_css)
        self.assertIn(".target-type-chip.active", evidence_source_css)
        self.assertIn(".tool-request-source-limits", evidence_source_css)
        self.assertIn(".tool-request-field textarea", evidence_source_css)
        self.assertIn(".tool-inspector-empty.warning", evidence_source_css)
        self.assertIn("@media (max-width: 640px)", evidence_source_css)
        self.assertNotIn(".tool-launcher-list", portal_css)
        self.assertNotIn(".tool-inspector-card", portal_css)
        self.assertNotIn(".tool-request-builder", portal_css)

    def test_stored_run_replay_attaches_diagnostic_to_matching_assistant_run(self) -> None:
        messages_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_messages.js").as_uri()
        script = textwrap.dedent(
            f"""
            const messages = await import({messages_url!r});
            const plan = messages.storedMessageReplayPlan([
              {{ id: 'user-1', role: 'user', text: 'Review rs429358' }},
              {{
                id: 'tool-1',
                role: 'tool',
                run_id: 'run-1',
                event: {{ type: 'diagnostic', name: 'host_agent_context_load', message: 'loaded skill' }}
              }},
              {{ id: 'assistant-1', role: 'assistant', run_id: 'run-1', text: 'Answer text' }}
            ]);
            process.stdout.write(JSON.stringify(plan));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["assistantRunIds"], ["run-1"])
        self.assertEqual(result["items"][1]["assistantRunId"], "run-1")
        self.assertEqual(result["items"][2]["assistantRunId"], "")

    def test_message_surface_aggregates_diagnostics_as_collapsed_work_detail(self) -> None:
        messages_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_messages.js").as_uri()
        script = textwrap.dedent(
            f"""
            class ClassList {{
              constructor(element) {{ this.element = element; }}
              items() {{ return String(this.element.className || '').split(/\\s+/).filter(Boolean); }}
              set(items) {{ this.element.className = [...new Set(items)].join(' '); }}
              add(...names) {{ this.set([...this.items(), ...names.filter(Boolean)]); }}
              remove(...names) {{ this.set(this.items().filter((item) => !names.includes(item))); }}
              contains(name) {{ return this.items().includes(name); }}
              toggle(name, force) {{
                const active = force === undefined ? !this.contains(name) : Boolean(force);
                if (active) this.add(name);
                else this.remove(name);
                return active;
              }}
            }}

            class Element {{
              constructor(tagName) {{
                this.tagName = String(tagName || '').toLowerCase();
                this.children = [];
                this.parentNode = null;
                this.attributes = {{}};
                this.dataset = {{}};
                this.eventListeners = {{}};
                this.className = '';
                this._textContent = '';
                this.hidden = false;
                this.scrollHeight = 100;
                this.scrollTop = 0;
                this.classList = new ClassList(this);
              }}
              set textContent(value) {{ this._textContent = String(value || ''); }}
              get textContent() {{ return this._textContent + this.children.map((child) => child.textContent).join(''); }}
              appendChild(child) {{
                child.parentNode = this;
                this.children.push(child);
                return child;
              }}
              setAttribute(name, value) {{
                const text = String(value);
                this.attributes[name] = text;
                if (name === 'class') this.className = text;
                if (name === 'id') this.id = text;
                if (name.startsWith('data-')) this.dataset[dataKey(name.slice(5))] = text;
              }}
              getAttribute(name) {{
                if (name === 'class') return this.className;
                return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
              }}
              addEventListener(type, handler) {{
                this.eventListeners[type] = this.eventListeners[type] || [];
                this.eventListeners[type].push(handler);
              }}
              closest(selector) {{
                let node = this;
                while (node) {{
                  if (matches(node, selector)) return node;
                  node = node.parentNode;
                }}
                return null;
              }}
              querySelector(selector) {{ return this.querySelectorAll(selector)[0] || null; }}
              querySelectorAll(selector) {{ return querySelectorAll(this, selector); }}
              set innerHTML(value) {{
                this.children = [];
                this._textContent = '';
                parseHtml(String(value || ''), this);
              }}
              get innerHTML() {{ return ''; }}
            }}

            function dataKey(name) {{
              return name.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
            }}

            function descendants(node) {{
              const found = [];
              node.children.forEach((child) => {{
                found.push(child);
                found.push(...descendants(child));
              }});
              return found;
            }}

            function querySelectorAll(root, selector) {{
              const parts = String(selector || '').trim().split(/\\s+/).filter(Boolean);
              let current = [root];
              parts.forEach((part) => {{
                const next = [];
                current.forEach((node) => {{
                  descendants(node).forEach((child) => {{
                    if (matches(child, part)) next.push(child);
                  }});
                }});
                current = next;
              }});
              return current;
            }}

            function matches(element, selector) {{
              const attr = String(selector || '').match(/^\\[([^=\\]]+)(?:="([^"]*)")?\\]$/);
              if (attr) {{
                const value = element.getAttribute(attr[1]);
                return attr[2] === undefined ? value !== null : value === attr[2];
              }}
              const pieces = String(selector || '').split('.');
              const tag = pieces[0];
              if (tag && tag !== element.tagName) return false;
              return pieces.slice(1).every((name) => element.classList.contains(name));
            }}

            function parseHtml(html, root) {{
              const tokenPattern = /<\\/?[^>]+>|[^<]+/g;
              const stack = [root];
              let match;
              while ((match = tokenPattern.exec(html))) {{
                const token = match[0];
                if (!token.startsWith('<')) {{
                  const text = token.replace(/\\s+/g, ' ').trim();
                  if (text) stack[stack.length - 1].textContent += text;
                  continue;
                }}
                if (/^<\\//.test(token)) {{
                  if (stack.length > 1) stack.pop();
                  continue;
                }}
                const parsed = token.match(/^<([a-zA-Z0-9-]+)([^>]*)>/);
                if (!parsed) continue;
                const child = new Element(parsed[1]);
                const attrs = parsed[2] || '';
                const attrPattern = /([a-zA-Z0-9:-]+)(?:="([^"]*)")?/g;
                let attr;
                while ((attr = attrPattern.exec(attrs))) child.setAttribute(attr[1], attr[2] || '');
                stack[stack.length - 1].appendChild(child);
                if (!/\\/>$/.test(token) && !['br', 'hr', 'img', 'input', 'link', 'meta'].includes(child.tagName)) {{
                  stack.push(child);
                }}
              }}
            }}

            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            Object.defineProperty(globalThis, 'navigator', {{
              value: {{ clipboard: {{ writeText() {{}} }} }},
              configurable: true
            }});

            const messages = await import({messages_url!r});
            const list = document.createElement('div');
            let diagnosticRecord = null;
            const surface = messages.createMessageSurface({{
              list,
              onToolRecord(record) {{
                if (record && record.kind === 'diagnostic') {{
                  diagnosticRecord = {{
                    kind: record.kind,
                    hasResult: Boolean(record.result),
                    eventCount: record.diagnostic && record.diagnostic.events.length,
                    firstMessage: record.diagnostic && record.diagnostic.events[0] && record.diagnostic.events[0].message
                  }};
                }}
              }}
            }});
            surface.addMessage(
              'user',
              'Internal genome-boundary prompt wording may change.',
              [{{ label: 'Active genome: GRCh38 · VCF genome', context_kind: 'genome_context', prompt_text: 'Active genome / Current genome / Build: GRCh38' }}],
              {{ presentationKind: 'genome_context_control' }}
            );
            surface.addMessage(
              'assistant',
              'Internal acknowledgement wording may change.',
              [],
              {{ presentationKind: 'genome_context_acknowledgement' }}
            );
            surface.addMessage(
              'assistant',
              "I've registered the constraints, but there isn't yet a specific genomic question to act on.",
              []
            );
            surface.addMessage(
              'user',
              'Internal selected-material prompt wording may change.',
              [{{
                label: 'ClinVar evidence',
                context_kind: 'evidence_panel',
                prompt_text: 'ClinVar result',
                message_presentation_kind: 'selected_material_control'
              }}]
            );
            surface.addMessage(
              'user',
              'Continue with the attached material.',
              [{{ label: 'Untyped evidence', context_kind: 'evidence_panel', prompt_text: 'Untyped result' }}]
            );
            const visibleBubbles = list.querySelectorAll('.message .body').map((node) => node.textContent);
            surface.renderStoredMessages([
              {{ id: 'tool-1', role: 'tool', frame_id: 'frame_1', run_id: 'run_1', event: {{ type: 'diagnostic', name: 'host_agent_context_load', message: 'loaded skill from /Users/matthewzmd/private/SKILL.md' }} }},
              {{ id: 'tool-2', role: 'tool', frame_id: 'frame_1', run_id: 'run_1', event: {{ type: 'diagnostic', name: 'spawn_agent', message: 'started' }} }},
              {{ id: 'assistant-1', role: 'assistant', frame_id: 'frame_1', run_id: 'run_1', text: 'Answer text' }}
            ]);
            const stack = list.querySelector('.tool-stack');
            const chip = list.querySelector('.tool-chip');
            const diagnosticDetail = chip && chip.querySelector('.tool-details') && chip.querySelector('.tool-details').textContent;
            const collapsedAfterDiagnostics = Boolean(stack && stack.classList.contains('collapsed'));
            const hiddenAfterDiagnostics = Boolean(stack && stack.hidden);
            const workSummaryAfterDiagnostics = stack && stack.querySelector('.tool-stack-summary') && stack.querySelector('.tool-stack-summary').textContent;
            const runMessage = stack && stack.closest('.message.assistant');
            surface.addToolEvent(
              'tool_call',
              {{ id: 'tool-call-1', name: 'variant.resolve', input: {{ rsid: 'rs429358' }} }},
              runMessage,
              {{ frameId: 'frame_1', runId: 'run_1' }}
            );
            const chips = list.querySelectorAll('.tool-chip');
            const toolChip = chips[1];
            const toolTitleAfterCall = toolChip && toolChip.querySelector('.tool-title') && toolChip.querySelector('.tool-title').textContent;
            surface.addToolEvent(
              'tool_result',
              {{
                id: 'tool-call-1',
                name: 'genomi.invoke',
                payload: {{
                  evidence_envelope: {{
                    operation: 'gwas.compare_variant_associations',
                    headline: 'gwas.compare_variant_associations: data_returned',
                    answer_readiness: 'scoped_answer_only',
                    finding_state: 'data_returned'
                  }}
                }},
                portal_presentation: {{
                  schema: 'genomi_portal_result_presentation',
                  operation: 'gwas.compare_variant_associations',
                  kind: 'candidate_evidence',
                  kicker: 'Variant association evidence',
                  title: 'LDL cholesterol / rs111 / rs222',
                  summary: 'gwas.compare_variant_associations: data_returned',
                  lanes: [{{
                    title: 'Candidate comparison',
                    nodes: [{{ label: '#1 rs111', summary: 'support high', context: 'Candidate comparison / #1 rs111: support high', value: {{ candidate_id: 'rs111' }} }}]
                  }}]
                }}
              }},
              runMessage,
              {{ frameId: 'frame_1', runId: 'run_1' }}
            );
            process.stdout.write(JSON.stringify({{
              chipCount: chips.length,
              collapsed: collapsedAfterDiagnostics,
              hiddenAfterDiagnostics,
              collapsedAfterTool: Boolean(stack && stack.classList.contains('collapsed')),
              hiddenAfterTool: Boolean(stack && stack.hidden),
              title: chip && chip.querySelector('.tool-title') && chip.querySelector('.tool-title').textContent,
              summary: chip && chip.querySelector('.tool-summary') && chip.querySelector('.tool-summary').textContent,
              detail: diagnosticDetail,
              diagnosticRecord,
              visibleBubbles,
              toolTitle: toolTitleAfterCall,
              toolTitleAfterResult: toolChip && toolChip.querySelector('.tool-title') && toolChip.querySelector('.tool-title').textContent,
              workSummary: workSummaryAfterDiagnostics,
              workSummaryAfterTool: stack && stack.querySelector('.tool-stack-summary') && stack.querySelector('.tool-stack-summary').textContent
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["chipCount"], 2)
        self.assertTrue(result["collapsed"])
        self.assertTrue(result["hiddenAfterDiagnostics"])
        self.assertFalse(result["collapsedAfterTool"])
        self.assertFalse(result["hiddenAfterTool"])
        self.assertEqual(result["title"], "Assistant status notes")
        self.assertEqual(result["summary"], "2 status updates recorded")
        self.assertEqual(result["diagnosticRecord"]["kind"], "diagnostic")
        self.assertFalse(result["diagnosticRecord"]["hasResult"])
        self.assertEqual(result["diagnosticRecord"]["eventCount"], 2)
        self.assertNotIn("/Users", result["diagnosticRecord"]["firstMessage"])
        self.assertIn("[redacted local path]", result["diagnosticRecord"]["firstMessage"])
        self.assertNotIn("/Users", result["detail"])
        self.assertIn("[redacted local path]", result["detail"])
        genome_user_bubble = next(
            bubble for bubble in result["visibleBubbles"] if "Active genome selected:" in bubble
        )
        genome_assistant_bubble = next(
            bubble for bubble in result["visibleBubbles"] if "Ask a genetics question" in bubble
        )
        self.assertEqual(genome_user_bubble, "Active genome selected: GRCh38 · VCF genome.")
        self.assertNotIn("Using", genome_user_bubble)
        self.assertNotIn("current-session boundary", genome_user_bubble)
        self.assertNotIn("registered the constraints", genome_assistant_bubble)
        self.assertNotIn("there isn't yet a specific genomic question", genome_assistant_bubble)
        self.assertIn("registered the constraints", result["visibleBubbles"][2])
        self.assertTrue(result["visibleBubbles"][3].startswith("Use the included evidence."))
        self.assertTrue(result["visibleBubbles"][4].startswith("Continue with the attached material."))
        self.assertEqual(result["toolTitle"], "Variant lookup")
        self.assertEqual(result["toolTitleAfterResult"], "GWAS Compare Variant Associations")
        self.assertEqual(result["workSummary"], "Waiting for assistant work")
        self.assertEqual(result["workSummaryAfterTool"], "1 done")

    def test_message_surface_replays_generic_genome_ready_as_specific_context(self) -> None:
        messages_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_messages.js").as_uri()
        script = _dom_shim_script() + textwrap.dedent(
            f"""
            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            const messages = await import({messages_url!r});
            const list = document.createElement('div');
            const surface = messages.createMessageSurface({{ list }});
            surface.renderStoredMessages([{{
              role: 'user',
              text: 'Internal genome-boundary prompt wording may change.',
              selected_evidence: [{{
                label: 'Genome state: Genome ready',
                context_kind: 'genome_context',
                selected_nodes: [
                  {{ label: 'Current genome / Build', value: 'GRCh38' }},
                  {{ label: 'Current genome / Readiness', value: 'completed' }}
                ],
                message_presentation_kind: 'genome_context_control'
              }}]
            }}, {{
              role: 'assistant',
              text: 'Internal acknowledgement wording may change.'
            }}]);
            const bubbles = list.querySelectorAll('.message .body');
            const assistantAnswer = list.querySelector('.message-answer-text p span');
            process.stdout.write(JSON.stringify({{
              text: bubbles[0] ? bubbles[0].textContent : '',
              assistantText: assistantAnswer ? assistantAnswer.textContent : ''
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["text"], "Active genome selected: GRCh38 genome.")
        self.assertEqual(
            result["assistantText"],
            "Ask a genetics question when you want to use the approved active genome.",
        )
        self.assertNotIn("Genome ready", result["text"])

    def test_message_surface_renders_assistant_markdown_semantically(self) -> None:
        messages_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_messages.js").as_uri()
        script = _dom_shim_script() + textwrap.dedent(
            f"""
            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            const messages = await import({messages_url!r});
            const list = document.createElement('div');
            const surface = messages.createMessageSurface({{ list }});
            surface.addMessage('assistant', '**Reviewed**\\n\\n- Coding variant\\n- Public evidence only');
            const answer = list.querySelector('[data-testid="genomi-assistant-answer"]');
            process.stdout.write(JSON.stringify({{
              strong: answer && answer.querySelector('strong') ? answer.querySelector('strong').textContent : '',
              items: answer ? answer.querySelectorAll('li span').map((item) => item.textContent) : []
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["strong"], "Reviewed")
        self.assertEqual(result["items"], ["Coding variant", "Public evidence only"])

    def test_message_surface_hides_implicit_genome_mode(self) -> None:
        messages_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_messages.js").as_uri()
        script = _dom_shim_script() + textwrap.dedent(
            f"""
            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            const messages = await import({messages_url!r});
            const liveList = document.createElement('div');
            const liveSurface = messages.createMessageSurface({{ list: liveList }});
            liveSurface.addMessage('user', 'Review CYP2C19 evidence', [], {{ genomeContextMode: 'public' }});
            const storedList = document.createElement('div');
            const storedSurface = messages.createMessageSurface({{ list: storedList }});
            storedSurface.renderStoredMessages([
              {{ id: 'm1', role: 'user', text: 'Review my APOE context', genome_context_mode: 'auto' }}
            ]);
            const result = {{
              liveBadge: Boolean(liveList.querySelector('.message-genome-mode')),
              liveBody: liveList.querySelector('.message .body').textContent,
              storedBadge: Boolean(storedList.querySelector('.message-genome-mode')),
              storedBody: storedList.querySelector('.message .body').textContent
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertFalse(result["liveBadge"])
        self.assertFalse(result["storedBadge"])
        self.assertNotIn("genomeContextMode", result["liveBody"])
        self.assertNotIn("genome_context_mode", result["storedBody"])

    def test_message_surface_hides_technical_tool_wrappers_and_promotes_recovered_operation(self) -> None:
        messages_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_messages.js").as_uri()
        script = _dom_shim_script() + textwrap.dedent(
            f"""
            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            Object.defineProperty(globalThis, 'navigator', {{
              value: {{ clipboard: {{ writeText() {{}} }} }},
              configurable: true
            }});
            const messages = await import({messages_url!r});
            const list = document.createElement('div');
            const surface = messages.createMessageSurface({{ list }});
            surface.addMessage('assistant', 'Done', []);
            const parent = list.querySelector('.message.assistant');
            surface.addToolEvent(
              'tool_call',
              {{ id: 'call_mcp', name: 'mcp__genomi__genomi_invoke', input: {{ tool: 'pharmacogenomics.review_medication' }} }},
              parent,
              {{ frameId: 'frame_1', runId: 'run_1' }}
            );
            surface.addToolEvent(
              'tool_result',
              {{ id: 'call_mcp', name: 'mcp__genomi__genomi_invoke', content: '[{{"tool_name":"mcp__genomi__genomi_invoke","type":"tool_reference"}}]' }},
              parent,
              {{ frameId: 'frame_1', runId: 'run_1' }}
            );
            surface.addToolEvent(
              'tool_call',
              {{ id: 'call_bash', name: 'Bash', input: {{ command: 'recover headline' }} }},
              parent,
              {{ frameId: 'frame_1', runId: 'run_1' }}
            );
            surface.addToolEvent(
              'tool_result',
              {{ id: 'call_bash', name: 'Bash', content: 'pharmacogenomics.review_medication: evidence_present · scoped_answer_only' }},
              parent,
              {{ frameId: 'frame_1', runId: 'run_1' }}
            );
            const chips = list.querySelectorAll('.tool-chip');
            const visibleChips = chips.filter((chip) => !chip.hidden);
            const stack = list.querySelector('.tool-stack');
            const result = {{
              chipCount: chips.length,
              visibleTitles: visibleChips.map((chip) => chip.querySelector('.tool-title').textContent),
              visibleSummaries: visibleChips.map((chip) => chip.querySelector('.tool-summary').textContent),
              stackHidden: Boolean(stack && stack.hidden),
              stackSummary: stack && stack.querySelector('.tool-stack-summary') && stack.querySelector('.tool-stack-summary').textContent
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["chipCount"], 2)
        self.assertEqual(result["visibleTitles"], ["Medication-response review"])
        self.assertEqual(
            result["visibleSummaries"],
            ["pharmacogenomics.review_medication: evidence_present · scoped_answer_only"],
        )
        self.assertFalse(result["stackHidden"])
        self.assertEqual(result["stackSummary"], "1 done")

    def test_message_surface_renders_permission_result_as_approval_card(self) -> None:
        messages_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_messages.js").as_uri()
        script = _dom_shim_script() + textwrap.dedent(
            f"""
            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            Object.defineProperty(globalThis, 'navigator', {{
              value: {{ clipboard: {{ writeText() {{}} }} }},
              configurable: true
            }});
            const messages = await import({messages_url!r});
            const list = document.createElement('div');
            let approved = null;
            const surface = messages.createMessageSurface({{
              list,
              onApprovePermission: (record) => {{
                approved = {{
                  runId: record.scope.runId,
                  tool: record.result.permission_request.tool
                }};
                return Promise.resolve('retry-run');
              }}
            }});
            surface.addMessage('assistant', 'I need access.', []);
            const parent = list.querySelector('.message.assistant');
            surface.addToolEvent(
              'tool_result',
              {{
                id: 'tool-permission',
                name: 'mcp__genomi__genomi_describe_context',
                isError: true,
                content: "Claude requested permissions to use mcp__genomi__genomi_describe_context, but you haven't granted it yet.",
                permission_request: {{
                  kind: 'host_agent_tool',
                  tool: 'mcp__genomi__genomi_describe_context',
                  label: 'Read current Genomi context'
                }}
              }},
              parent,
              {{ frameId: 'frame_1', runId: 'run_permission' }}
            );
            surface.addToolEvent(
              'diagnostic',
              {{ type: 'diagnostic', name: 'assistant_status', message: 'Waiting for approval' }},
              parent,
              {{ frameId: 'frame_1', runId: 'run_permission' }}
            );
            surface.addToolEvent(
              'tool_result',
              {{
                id: 'tool-permission-duplicate',
                isError: true,
                permission_request: {{
                  kind: 'host_agent_tool',
                  tool: 'mcp__external__lookup',
                  label: 'Use an external connector'
                }}
              }},
              parent,
              {{ frameId: 'frame_1', runId: 'run_permission' }}
            );
            const chip = list.querySelector('.tool-chip');
            const approveButton = chip.querySelector('.primary-action');
            const approveTestId = approveButton.getAttribute('data-testid');
            const handler = approveButton.eventListeners.click[0];
            await handler({{ stopPropagation() {{}} }});
            const fallbackList = document.createElement('div');
            const fallbackSurface = messages.createMessageSurface({{ list: fallbackList }});
            fallbackSurface.addMessage('assistant', 'I need access.', []);
            const fallbackParent = fallbackList.querySelector('.message.assistant');
            fallbackSurface.addToolEvent(
              'tool_result',
              {{
                id: 'tool-canonical-generic',
                isError: true,
                permission_request: {{
                  kind: 'host_agent_tool',
                  tool: 'mcp__genomi__genomi_describe_context',
                  label: 'MCP tool'
                }}
              }},
              fallbackParent,
              {{ frameId: 'frame_1', runId: 'run_generic_legacy' }}
            );
            fallbackSurface.addToolEvent(
              'tool_result',
              {{
                id: 'tool-malformed-legacy',
                isError: true,
                permission_request: {{
                  kind: 'host_agent_tool',
                  tool: 'mcp__private__sensitive_operation'
                }}
              }},
              fallbackParent,
              {{ frameId: 'frame_1', runId: 'run_generic' }}
            );
            const fallbackChips = fallbackList.querySelectorAll('.tool-chip');
            process.stdout.write(JSON.stringify({{
              hidden: Boolean(chip.hidden),
              permissionCardCount: list.querySelectorAll('.permission-request').length,
              title: chip.querySelector('.tool-title').textContent,
              summary: chip.querySelector('.tool-summary').textContent,
              detailTitle: chip.querySelector('strong').textContent,
              explanation: chip.querySelector('p').textContent,
              approveDisabled: Boolean(approveButton.disabled),
              approveText: approveButton.textContent,
              approveTestId,
              stackSummary: list.querySelector('.tool-stack-summary').textContent,
              stackCollapsed: list.querySelector('.tool-stack').classList.contains('collapsed'),
              cardOpen: chip.classList.contains('open'),
              canonicalGenericLabel: fallbackChips[0].querySelector('.tool-summary').textContent,
              malformedFallbackLabel: fallbackChips[1].querySelector('.tool-summary').textContent,
              approved
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertFalse(result["hidden"])
        self.assertEqual(result["permissionCardCount"], 1)
        self.assertEqual(result["title"], "Permission needed")
        self.assertEqual(result["summary"], "Read current Genomi context")
        self.assertEqual(result["approveTestId"], "genomi-permission-approve")
        self.assertFalse(result["stackCollapsed"])
        self.assertTrue(result["cardOpen"])
        self.assertEqual(result["detailTitle"], "Read current Genomi context")
        self.assertEqual(result["canonicalGenericLabel"], "MCP tool")
        self.assertEqual(result["malformedFallbackLabel"], "Assistant permission")
        self.assertNotIn("sensitive_operation", result["malformedFallbackLabel"])
        self.assertNotIn("mcp__genomi__", result["explanation"])
        self.assertIn("Access allowed", result["explanation"])
        self.assertEqual(result["stackSummary"], "1 error")
        self.assertTrue(result["approveDisabled"])
        self.assertEqual(result["approveText"], "Allowed for this workspace")
        self.assertEqual(
            result["approved"],
            {"runId": "run_permission", "tool": "mcp__genomi__genomi_describe_context"},
        )

    def test_message_surface_focus_run_falls_back_to_tool_only_work_group(self) -> None:
        messages_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_messages.js").as_uri()
        script = textwrap.dedent(
            f"""
            class ClassList {{
              constructor(element) {{ this.element = element; }}
              items() {{ return String(this.element.className || '').split(/\\s+/).filter(Boolean); }}
              set(items) {{ this.element.className = [...new Set(items)].join(' '); }}
              add(...names) {{ this.set([...this.items(), ...names.filter(Boolean)]); }}
              remove(...names) {{ this.set(this.items().filter((item) => !names.includes(item))); }}
              contains(name) {{ return this.items().includes(name); }}
              toggle(name, force) {{
                const active = force === undefined ? !this.contains(name) : Boolean(force);
                if (active) this.add(name);
                else this.remove(name);
                return active;
              }}
            }}

            class Element {{
              constructor(tagName) {{
                this.tagName = String(tagName || '').toLowerCase();
                this.children = [];
                this.parentNode = null;
                this.attributes = {{}};
                this.dataset = {{}};
                this.eventListeners = {{}};
                this.className = '';
                this.textContent = '';
                this.hidden = false;
                this.scrollHeight = 100;
                this.scrollTop = 0;
                this.scrolled = false;
                this.classList = new ClassList(this);
              }}
              appendChild(child) {{
                child.parentNode = this;
                this.children.push(child);
                return child;
              }}
              setAttribute(name, value) {{
                const text = String(value);
                this.attributes[name] = text;
                if (name === 'class') this.className = text;
                if (name === 'id') this.id = text;
                if (name.startsWith('data-')) this.dataset[dataKey(name.slice(5))] = text;
              }}
              getAttribute(name) {{
                if (name === 'class') return this.className;
                return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
              }}
              removeAttribute(name) {{
                delete this.attributes[name];
                if (name.startsWith('data-')) delete this.dataset[dataKey(name.slice(5))];
              }}
              addEventListener(type, handler) {{
                this.eventListeners[type] = this.eventListeners[type] || [];
                this.eventListeners[type].push(handler);
              }}
              closest(selector) {{
                let node = this;
                while (node) {{
                  if (matches(node, selector)) return node;
                  node = node.parentNode;
                }}
                return null;
              }}
              querySelector(selector) {{ return this.querySelectorAll(selector)[0] || null; }}
              querySelectorAll(selector) {{ return querySelectorAll(this, selector); }}
              scrollIntoView() {{ this.scrolled = true; }}
              set innerHTML(value) {{
                this.children = [];
                this.textContent = '';
                parseHtml(String(value || ''), this);
              }}
              get innerHTML() {{ return ''; }}
            }}

            function dataKey(name) {{
              return name.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
            }}

            function descendants(node) {{
              const found = [];
              node.children.forEach((child) => {{
                found.push(child);
                found.push(...descendants(child));
              }});
              return found;
            }}

            function querySelectorAll(root, selector) {{
              const parts = String(selector || '').trim().split(/\\s+/).filter(Boolean);
              let current = [root];
              parts.forEach((part) => {{
                const next = [];
                current.forEach((node) => {{
                  descendants(node).forEach((child) => {{
                    if (matches(child, part)) next.push(child);
                  }});
                }});
                current = next;
              }});
              return current;
            }}

            function matches(element, selector) {{
              const attr = String(selector || '').match(/^\\[([^=\\]]+)(?:="([^"]*)")?\\]$/);
              if (attr) {{
                const value = element.getAttribute(attr[1]);
                return attr[2] === undefined ? value !== null : value === attr[2];
              }}
              const pieces = String(selector || '').split('.');
              const tag = pieces[0];
              if (tag && tag !== element.tagName) return false;
              return pieces.slice(1).every((name) => element.classList.contains(name));
            }}

            function parseHtml(html, root) {{
              const tags = /<\\/?[^>]+>/g;
              const stack = [root];
              let match;
              while ((match = tags.exec(html))) {{
                const token = match[0];
                if (/^<\\//.test(token)) {{
                  if (stack.length > 1) stack.pop();
                  continue;
                }}
                const parsed = token.match(/^<([a-zA-Z0-9-]+)([^>]*)>/);
                if (!parsed) continue;
                const child = new Element(parsed[1]);
                const attrs = parsed[2] || '';
                const attrPattern = /([a-zA-Z0-9:-]+)(?:="([^"]*)")?/g;
                let attr;
                while ((attr = attrPattern.exec(attrs))) child.setAttribute(attr[1], attr[2] || '');
                stack[stack.length - 1].appendChild(child);
                if (!/\\/>$/.test(token) && !['br', 'hr', 'img', 'input', 'link', 'meta'].includes(child.tagName)) {{
                  stack.push(child);
                }}
              }}
            }}

            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            Object.defineProperty(globalThis, 'navigator', {{
              value: {{ clipboard: {{ writeText() {{}} }} }},
              configurable: true
            }});

            const messages = await import({messages_url!r});
            const assistantList = document.createElement('div');
            const assistantSurface = messages.createMessageSurface({{ list: assistantList }});
            assistantSurface.renderStoredMessages([
              {{ id: 'tool-1', role: 'tool', frame_id: 'frame_1', run_id: 'run_assistant', event: {{ type: 'tool_call', name: 'variant.resolve', input: {{ rsid: 'rs429358' }} }} }},
              {{ id: 'assistant-1', role: 'assistant', frame_id: 'frame_1', run_id: 'run_assistant', text: 'Done' }}
            ]);
            const assistantHighlighted = assistantSurface.focusRun('run_assistant');
            const assistantMessage = assistantList.querySelector('.message.run-highlight');
            const assistantStack = assistantList.querySelector('.tool-stack.run-highlight');

            const toolOnlyList = document.createElement('div');
            const toolOnlySurface = messages.createMessageSurface({{ list: toolOnlyList }});
            toolOnlySurface.renderStoredMessages([
              {{ id: 'tool-only-1', role: 'tool', frame_id: 'frame_1', run_id: 'run_tool_only', event: {{ type: 'tool_call', name: 'decode.render_dashboard', input: {{ artifact: 'dashboard' }} }} }}
            ]);
            const toolOnlyHighlighted = toolOnlySurface.focusRun('run_tool_only');
            const toolOnlyMessage = toolOnlyList.querySelector('.message.run-highlight');
            const toolOnlyStack = toolOnlyList.querySelector('.tool-stack.run-highlight');

            process.stdout.write(JSON.stringify({{
              assistantHighlighted,
              assistantMessageHighlighted: Boolean(assistantMessage),
              assistantStackHighlighted: Boolean(assistantStack),
              assistantMessageRun: assistantMessage && assistantMessage.dataset.highlightedRun,
              toolOnlyHighlighted,
              toolOnlyMessageHighlighted: Boolean(toolOnlyMessage),
              toolOnlyStackHighlighted: Boolean(toolOnlyStack),
              toolOnlyStackRun: toolOnlyStack && toolOnlyStack.dataset.highlightedRun,
              toolOnlyStackScrolled: Boolean(toolOnlyStack && toolOnlyStack.scrolled)
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertTrue(result["assistantHighlighted"])
        self.assertTrue(result["assistantMessageHighlighted"])
        self.assertTrue(result["assistantStackHighlighted"])
        self.assertEqual(result["assistantMessageRun"], "run_assistant")
        self.assertTrue(result["toolOnlyHighlighted"])
        self.assertFalse(result["toolOnlyMessageHighlighted"])
        self.assertTrue(result["toolOnlyStackHighlighted"])
        self.assertEqual(result["toolOnlyStackRun"], "run_tool_only")
        self.assertTrue(result["toolOnlyStackScrolled"])

    def test_message_tool_work_group_summary_is_counts_first(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"
        messages_url = (root / "portal_messages.js").as_uri()
        frame_trace = (root / "portal_frame_trace.js").read_text()
        css = (root / "portal.css").read_text()
        script = textwrap.dedent(
            f"""
            const messages = await import({messages_url!r});
            process.stdout.write(JSON.stringify({{
              empty: messages.toolWorkGroupSummary([]),
              running: messages.toolWorkGroupSummary(['running']),
              mixed: messages.toolWorkGroupSummary(['done', 'completed', 'running', 'error', 'error']),
              emptyPayload: messages.toolWorkGroupContextPayload([]),
              payload: messages.toolWorkGroupContextPayload([
                {{
                  scope: {{ frameId: 'frame_1', runId: 'run_1', messageId: 'msg_tool' }},
                  call: {{ id: 'tool_1', name: 'variant.resolve', input: {{ rsid: 'rs429358' }} }},
                  result: {{
                    id: 'tool_1',
                    name: 'variant.resolve',
                    content: 'variant.resolve result from /tmp/private/result.json',
                    ledger: {{ status: 'completed', summary: 'completed from /Users/matthewzmd/private/source.vcf' }}
                  }}
                }}
              ]),
              diagnosticPayload: messages.toolWorkGroupContextPayload([
                {{
                  kind: 'diagnostic',
                  scope: {{ frameId: 'frame_1', runId: 'run_1', messageId: 'msg_tool' }},
                  diagnostic: {{
                    events: [
                      {{ type: 'diagnostic', name: 'spawn_agent', message: 'started from /Users/matthewzmd/private/context.json' }}
                    ]
                  }}
                }}
              ])
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["empty"]["title"], "0 work steps")
        self.assertEqual(result["empty"]["status"], "running")
        self.assertEqual(result["empty"]["summary"], "Waiting for assistant work")
        self.assertEqual(result["running"]["title"], "1 work step")
        self.assertEqual(result["running"]["summary"], "1 running")
        self.assertEqual(result["mixed"]["total"], 5)
        self.assertEqual(result["mixed"]["done"], 2)
        self.assertEqual(result["mixed"]["running"], 1)
        self.assertEqual(result["mixed"]["errors"], 2)
        self.assertEqual(result["mixed"]["status"], "error")
        self.assertEqual(result["mixed"]["summary"], "2 done · 1 running · 2 errors")
        self.assertIsNone(result["emptyPayload"])
        self.assertEqual(result["payload"]["context_kind"], "work_trace")
        self.assertEqual(result["payload"]["label"], "Message work trail")
        self.assertEqual(result["payload"]["source_operation"], "genomi.portal.message_work_trace")
        self.assertIn("Selected conversation work trail", result["payload"]["prompt_text"])
        self.assertIn("Variant lookup", result["payload"]["prompt_text"])
        self.assertNotIn("variant.resolve", result["payload"]["prompt_text"])
        self.assertNotIn("/tmp/private", result["payload"]["prompt_text"])
        self.assertNotIn("/Users", result["payload"]["prompt_text"])
        self.assertEqual(result["diagnosticPayload"]["context_kind"], "work_trace")
        self.assertEqual(result["diagnosticPayload"]["label"], "Message work trail")
        self.assertIn("Assistant status notes", result["diagnosticPayload"]["prompt_text"])
        self.assertIn("[redacted local path]", result["diagnosticPayload"]["prompt_text"])
        self.assertNotIn("host_agent_diagnostics", result["diagnosticPayload"]["prompt_text"])
        self.assertNotIn("/Users", result["diagnosticPayload"]["prompt_text"])
        messages_source = (root / "portal_messages.js").read_text()
        self.assertIn('data-testid="tool-group-header"', messages_source)
        self.assertNotIn('data-action="use-work"', messages_source)
        self.assertNotIn('data-action="ask-work"', messages_source)
        self.assertNotIn('data-action="ask-new-work"', messages_source)
        self.assertNotIn("genomi-work-trail-ask-new", frame_trace)
        self.assertNotIn("genomi-work-step-ask-new", frame_trace)
        self.assertNotIn("Use work trail", frame_trace)
        self.assertNotIn("Ask about work trail", frame_trace)
        self.assertIn(".tool-stack.collapsed .tool-stack-items", css)

    def test_message_work_group_hides_context_packet_actions(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"
        messages_url = (root / "portal_messages.js").as_uri()
        script = _dom_shim_script() + textwrap.dedent(
            f"""
            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            let askedNew = null;
            const messages = await import({messages_url!r});
            const list = document.createElement('div');
            const surface = messages.createMessageSurface({{
              list,
              onAskNewContext: (payload) => {{ askedNew = payload; }}
            }});
            surface.addToolEvent('tool_call', {{
              id: 'tool_1',
              name: 'variant.resolve',
              input: {{ rsid: 'rs429358' }}
            }}, null, {{ frameId: 'frame_1', runId: 'run_1', messageId: 'msg_call' }});
            surface.addToolEvent('tool_result', {{
              id: 'tool_1',
              name: 'variant.resolve',
              content: 'variant.resolve: data_returned',
              ledger: {{ status: 'completed', summary: 'Public variant evidence returned.' }}
            }}, null, {{ frameId: 'frame_1', runId: 'run_1', messageId: 'msg_result' }});
            const button = list.querySelector('[data-action="ask-new-work"]');
            process.stdout.write(JSON.stringify({{
              hasAskNewWork: Boolean(button),
              hasUseWork: Boolean(list.querySelector('[data-action="use-work"]')),
              hasAskWork: Boolean(list.querySelector('[data-action="ask-work"]')),
              payload: askedNew,
              visibleText: list.textContent
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertFalse(result["hasAskNewWork"])
        self.assertFalse(result["hasUseWork"])
        self.assertFalse(result["hasAskWork"])
        self.assertIsNone(result["payload"])
        self.assertNotIn("Use work trail", result["visibleText"])
        self.assertNotIn("Ask about work trail", result["visibleText"])
        self.assertNotIn("Ask in new conversation", result["visibleText"])

    def test_portal_frame_open_path_prepares_messages_before_committing_navigation(self) -> None:
        portal = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal.js").read_text()

        self.assertIn("async function prepareFrameOpen(frameId)", portal)
        self.assertIn("const messages = await api.loadFrameMessages(cleanFrameId, state.project.project_id);", portal)
        self.assertIn("function commitFrameOpen(frameId, messagesPayload, options = {})", portal)
        self.assertIn("const prepared = await prepareFrameOpen(frameId);", portal)
        self.assertIn("commitFrameOpen(prepared.frame.id, prepared.messages, options);", portal)
        self.assertIn("setFrameRoute(frameId, { highlightRunId: options.highlightRunId, highlightStepId: options.highlightStepId });", portal)
        self.assertIn("if (options.activateWorkTrace || options.highlightStepId) activateWorkspaceSection('work-trace-pane');", portal)
        self.assertIn("if (options.highlightRunId) highlightFrameRun(options.highlightRunId);", portal)
        self.assertIn("openFrame(frame.id).catch", portal)
        self.assertIn("const highlightRunId = artifactOriginHighlightRunId(originContext);", portal)
        self.assertIn("const highlightStepId = artifactOriginHighlightStepId(originContext);", portal)
        self.assertIn("const producingRunId = String((originContext && originContext.producingRunId) || '').trim();", portal)
        self.assertIn("if (producingRunId) return producingRunId;", portal)
        self.assertIn("activateResearch: Boolean(highlightRunId && !highlightStepId)", portal)
        self.assertIn("activateWorkTrace: Boolean(highlightStepId)", portal)
        self.assertIn("highlightStepId", portal)
        self.assertIn("function artifactOriginHighlightStepId(originContext)", portal)
        self.assertLess(
            portal.index("const prepared = await prepareFrameOpen(frameId);"),
            portal.index("commitFrameOpen(prepared.frame.id, prepared.messages, options);"),
        )
        self.assertLess(
            portal.index("const messages = await api.loadFrameMessages(cleanFrameId, state.project.project_id);"),
            portal.index("function commitFrameOpen(frameId, messagesPayload, options = {})"),
        )
        messages = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_messages.js").read_text()
        css = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal.css").read_text()
        self.assertIn("function focusRun(runId)", messages)
        self.assertIn("data-testid', 'genomi-message-run-highlight'", messages)
        self.assertIn("firstToolStackForRun(clean)", messages)
        self.assertIn(".message.run-highlight", css)
        self.assertNotIn("window.setTimeout(() => messageSurface.focusRun(runId), 60);", portal)
        self.assertNotIn("await loadFrameMessages(frameId);", portal)

    def test_assistant_prose_does_not_create_context_and_typed_context_still_routes(self) -> None:
        messages_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_messages.js").as_uri()
        prompt_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_prompt_context.js").as_uri()
        script = textwrap.dedent(
            f"""
            const messages = await import({messages_url!r});
            const prompt = await import({prompt_url!r});
            const assistantAnswer = [
              'CYP2C19 affects clopidogrel activation.',
              '',
              'Evidence I would inspect:',
              '',
              '- CPIC and PharmGKB recommendations.',
              '- CYP2C19 star allele definitions.'
            ].join('\\n');
            const result = {{
              assistantChecklistParser: typeof messages.assistantEvidenceChecklistModel,
              assistantChecklistPayload: typeof messages.assistantEvidenceChecklistPayload,
              assistantAnswer,
              resultNodePrompt: prompt.suggestedPromptForContexts([{{
                context_kind: 'result_nodes',
                label: 'rs429358',
                source_operation: 'variant.resolve',
                selected_nodes: [{{ label: 'ClinVar row', text: 'ClinVar row: rs429358 risk_factor' }}]
              }}]),
              multiResultPrompt: prompt.suggestedPromptForContexts([
                {{
                  context_kind: 'result_nodes',
                  label: 'rs429358',
                  source_operation: 'variant.resolve',
                  selected_nodes: [{{ label: 'ClinVar row', text: 'ClinVar row: rs429358 risk_factor' }}]
                }},
                {{
                  context_kind: 'evidence_panel',
                  label: 'clopidogrel',
                  source_operation: 'pharmacogenomics.review_medication',
                  selected_nodes: [{{ label: 'CPIC row', text: 'CPIC row: CYP2C19 poor metabolizer' }}]
                }}
              ]),
              genomeContextPrompt: prompt.suggestedPromptForContexts([{{
                context_kind: 'genome_context',
                label: 'Active genome',
                source_operation: 'genomi.describe_context',
                selected_nodes: [{{ label: 'Genome build', text: 'Genome build: GRCh38' }}]
              }}]),
              artifactPrompt: prompt.suggestedPromptForContexts([{{
                context_kind: 'report',
                label: 'Report: Genomi Report',
                source_operation: 'decode.render_dashboard',
                prompt_text: 'Selected report: Genomi Report',
                selected_nodes: [{{ label: 'Section state', text: 'Section state: ancestry blocked' }}]
              }}]),
              artifactAskWith: await (async () => {{
                let submitted = null;
                let focused = 0;
                const promptEl = {{
                  value: '',
                  focus: () => {{ focused += 1; }}
                }};
                const controller = prompt.createPromptContextController({{
                  prompt: promptEl,
                  storageKey: '',
                  onSuggestPrompt: async (items) => 'Server prompt for ' + items.map((item) => item.context_kind).join(','),
                  onAskSelected: (items) => {{ submitted = items; }}
                }});
                await controller.askWith({{
                  context_kind: 'report',
                  label: 'Report: Genomi Report',
                  source_operation: 'decode.render_dashboard',
                  prompt_text: 'Selected report: Genomi Report',
                  selected_nodes: [{{ label: 'Section state', text: 'Section state: ancestry blocked' }}]
                }});
                return {{
                  promptValue: promptEl.value,
                  submittedCount: submitted ? submitted.length : 0,
                  submittedLabel: submitted && submitted[0] && submitted[0].label,
                  submittedKind: submitted && submitted[0] && submitted[0].context_kind,
                  submittedNodes: submitted && submitted[0] && submitted[0].selected_nodes.length,
                  focused
                }};
              }})(),
              defaultContextPrompt: prompt.suggestedPromptForContexts([{{ label: 'Loose note', source_operation: 'portal.note' }}])
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["assistantChecklistParser"], "undefined")
        self.assertEqual(result["assistantChecklistPayload"], "undefined")
        self.assertIn("Evidence I would inspect", result["assistantAnswer"])
        self.assertEqual(
            result["resultNodePrompt"],
            "Use the included evidence to answer my message. Preserve provenance, source limits, and genome privacy boundaries.",
        )
        self.assertEqual(result["multiResultPrompt"], result["resultNodePrompt"])
        self.assertEqual(result["genomeContextPrompt"], "")
        self.assertEqual(result["artifactPrompt"], result["resultNodePrompt"])
        self.assertNotIn("selected Genomi result facts", result["artifactPrompt"])
        self.assertEqual(result["artifactAskWith"]["promptValue"], "Server prompt for report")
        self.assertEqual(result["artifactAskWith"]["submittedCount"], 1)
        self.assertEqual(result["artifactAskWith"]["submittedLabel"], "Report: Genomi Report")
        self.assertEqual(result["artifactAskWith"]["submittedKind"], "report")
        self.assertEqual(result["artifactAskWith"]["submittedNodes"], 1)
        self.assertGreaterEqual(result["artifactAskWith"]["focused"], 1)
        self.assertIn("genome privacy boundaries", result["defaultContextPrompt"])

    def test_tool_result_context_payload_routes_evidence_node_selections_as_evidence_panel(self) -> None:
        presentation_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_tool_result_presentation.js").as_uri()
        script = textwrap.dedent(
            f"""
            const presentation = await import({presentation_url!r});
            const payload = {{
              headline: 'variant.resolve: data_returned',
              query: {{ rsid: 'rs429358' }},
              resolved_targets: [{{ rsid: 'rs429358', resolution_status: 'identifier' }}],
              public_context: {{ clinvar_by_rsid: [{{ rsid: 'rs429358', clinical_significance: 'risk_factor' }}] }},
              evidence_envelope: {{
                finding_state: 'data_returned',
                answer_readiness: 'answer_supported',
                guidance: ['data_returned:use_variant_evidence'],
                coverage: {{ consulted_libraries: ['dbSNP', 'ClinVar'] }},
                observations: {{ variant: 'rs429358' }}
              }}
            }};
            const record = {{
              call: {{ id: 'call_variant', name: 'variant.resolve' }},
              result: {{ id: 'result_variant', name: 'variant.resolve', payload }}
            }};
            const evidenceNode = {{
              className: 'evidence-node selected',
              dataset: {{
                label: 'Coverage from /Users/matthewzmd/.genomi/private.json',
                context: 'Coverage: context_file=/Users/matthewzmd/.genomi/context.json',
                value: '/tmp/private-coverage.json'
              }}
            }};
            const resultNode = {{
              className: 'result-node selected',
              dataset: {{
                label: 'ClinVar row',
                context: 'ClinVar records: rs429358 risk_factor',
                value: 'risk_factor'
              }}
            }};
            function rootFor(nodes) {{
              return {{
                querySelectorAll: (selector) => nodes.filter((node) => {{
                  const className = node.className || '';
                  if (selector.includes('.evidence-node') && className.includes('evidence-node')) return true;
                  if (selector.includes('.result-node') && className.includes('result-node')) return true;
                  return false;
                }})
              }};
            }}
            const result = {{
              evidenceOnly: presentation.toolResultContextPayload(record, rootFor([evidenceNode])),
              mixed: presentation.toolResultContextPayload(record, rootFor([resultNode, evidenceNode])),
              resultOnly: presentation.toolResultContextPayload(record, rootFor([resultNode]))
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["evidenceOnly"]["context_kind"], "evidence_panel")
        self.assertIn("Selected evidence from Variant lookup", result["evidenceOnly"]["prompt_text"])
        self.assertNotIn("Selected evidence from variant.resolve", result["evidenceOnly"]["prompt_text"])
        self.assertEqual(result["evidenceOnly"]["finding_state"], "data_returned")
        self.assertEqual(result["evidenceOnly"]["answer_readiness"], "answer_supported")
        self.assertIn("[redacted local path]", result["evidenceOnly"]["prompt_text"])
        self.assertEqual(result["mixed"]["context_kind"], "evidence_panel")
        self.assertIn("Selected evidence from Variant lookup", result["mixed"]["prompt_text"])
        self.assertIn("ClinVar records: rs429358 risk_factor", result["mixed"]["prompt_text"])
        self.assertEqual(result["resultOnly"]["context_kind"], "result_nodes")
        self.assertIn("Selected result", result["resultOnly"]["prompt_text"])
        self.assertNotIn("Selected evidence from", result["resultOnly"]["prompt_text"])
        _assert_public_payload(result["evidenceOnly"])
        _assert_public_payload(result["mixed"])
        _assert_public_payload(result["resultOnly"])

    def test_evidence_renderer_is_canonical_envelope_first(self) -> None:
        module_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_evidence.js").as_uri()
        trace_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_result_trace.js").as_uri()
        messages_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_messages.js").as_uri()
        prompt_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_prompt_context.js").as_uri()
        presentation_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_tool_result_presentation.js").as_uri()
        renderers_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_result_renderers.js").as_uri()
        selected_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_selected_evidence.js").as_uri()
        details_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_tool_details.js").as_uri()
        script = textwrap.dedent(
            f"""
            const mod = await import({module_url!r});
            const trace = await import({trace_url!r});
            const messages = await import({messages_url!r});
            const prompt = await import({prompt_url!r});
            const presentation = await import({presentation_url!r});
            const renderers = await import({renderers_url!r});
            const selected = await import({selected_url!r});
            const details = await import({details_url!r});
            const canonical = {{
              headline: 'variant.resolve: data_returned',
              status: 'completed',
              evidence_envelope: {{
                finding_state: 'data_returned',
                answer_readiness: 'answer_supported',
                guidance: ['data_returned:use_variant_evidence'],
                coverage: {{ consulted_libraries: ['dbSNP', 'ClinVar'] }},
                observations: {{ variant: 'rs429358' }}
              }},
              coverage: {{ top_level_duplicate: 'not evidence authority' }},
              observations: {{ top_level_duplicate: 'not evidence authority' }},
              next_actions: ['top-level action must not duplicate envelope authority'],
              steps: [{{ status: 'queried', operation: 'variant.resolve' }}],
              sources: [{{ source_id: 'dbsnp', status: 'hit' }}],
              presented_trace: {{
                steps: [{{ status: 'queried', operation: 'variant.resolve' }}],
                sources: [{{ source_id: 'dbsnp', status: 'hit' }}]
              }},
              defaults_applied: {{ assembly: 'GRCh38' }}
            }};
            const nonEnvelope = {{ headline: 'plain headline', defaults_applied: {{ assembly: 'GRCh38' }} }};
            const wrapped = {{ content: [{{ type: 'text', text: JSON.stringify(canonical) }}] }};
            const variantPayload = {{
              headline: 'variant.resolve: data_returned',
              query: {{ rsid: 'rs429358', genome_build: 'GRCh38' }},
              resolved_targets: [{{ target_type: 'rsid', rsid: 'rs429358', resolution_status: 'identifier' }}],
              public_context: {{ clinvar_by_rsid: [{{ rsid: 'rs429358', gene_info: 'APOE:348', clinical_significance: 'risk_factor' }}] }},
              sample_context: {{ count: 0, matches: [] }},
              support_context: {{ genotype_support: [{{ source: 'active_genome_index_reader', status: 'supported' }}] }},
              evidence_envelope: canonical.evidence_envelope
            }};
            const variantServerPresentation = {{
              schema: 'genomi_portal_result_presentation',
              source: 'server',
              operation: 'variant.resolve',
              kind: 'variant',
              kicker: 'Variant evidence map',
              title: 'rs429358',
              summary: 'variant.resolve: data_returned',
              evidenceEnvelope: canonical.evidence_envelope,
              metrics: [
                {{ label: 'Resolved', value: 1 }},
                {{ label: 'ClinVar', value: 1 }},
                {{ label: 'Support', value: 1 }},
                {{ label: 'Answer boundary', value: 'Answer supported' }},
                {{ label: 'Evidence support', value: 'Data returned' }}
              ],
              lanes: [
                {{
                  title: 'Resolved targets',
                  nodes: [{{
                    label: 'rs429358',
                    summary: 'identifier',
                    context: 'Resolved targets / rs429358: identifier',
                    value: {{ rsid: 'rs429358', resolution_status: 'identifier' }}
                  }}]
                }},
                {{
                  title: 'ClinVar records',
                  nodes: [{{
                    label: 'rs429358 · APOE:348',
                    summary: 'risk_factor',
                    context: 'ClinVar records / rs429358 · APOE:348: risk_factor',
                    value: {{ rsid: 'rs429358', gene_info: 'APOE:348', clinical_significance: 'risk_factor' }}
                  }}]
                }},
                {{
                  title: 'Genotype support',
                  nodes: [{{
                    label: 'active genome index reader',
                    summary: 'supported',
                    context: 'Genotype support / active genome index reader: supported',
                    value: {{ source: 'active_genome_index_reader', status: 'supported' }}
                  }}]
                }},
                {{
                  title: 'Coverage and limits',
                  selectable: false,
                  nodes: [
                    {{
                      label: 'Coverage: Consulted Libraries',
                      summary: 'dbSNP, ClinVar',
                      context: 'Coverage and limits / Coverage: Consulted Libraries: dbSNP, ClinVar',
                      value: {{ consulted_libraries: ['dbSNP', 'ClinVar'] }},
                      selectable: false
                    }},
                    {{
                      label: 'Observations: Variant',
                      summary: 'rs429358',
                      context: 'Coverage and limits / Observations: Variant: rs429358',
                      value: {{ variant: 'rs429358' }},
                      selectable: false
                    }}
                  ]
                }}
              ]
            }};
            const pgxPayload = {{
              headline: 'pharmacogenomics.review_medication: evidence_present',
              query: {{ drug: 'clopidogrel' }},
              medication_review_matrix: {{ rows: [{{ drug: 'clopidogrel', gene: 'CYP2C19', row_type: 'source_row', phenotype: 'poor metabolizer' }}] }},
              evidence_matrix: {{ item_count: 2, role_counts: {{ public_source: 1, sample_follow_up: 1 }} }},
              sample_evidence: {{ star_allele_call_count: 1, star_gene_targets: [{{ symbol: 'CYP2C19', name: 'cytochrome P450 2C19' }}] }},
              evidence_envelope: canonical.evidence_envelope
            }};
            const gwasVariantPayload = {{
              headline: 'gwas.compare_variant_associations: data_returned',
              query: {{ phenotype: 'LDL cholesterol', variants: ['rs111', 'rs222'] }},
              summary: {{ top_observed_candidate: 'rs111', top_observed_support_level: 'high' }},
              evidence_view: {{
                query: {{ phenotype: 'LDL cholesterol', variants: ['rs111', 'rs222'] }},
                coverage_state: 'data_returned',
                evidence_state: 'decision_grade_evidence',
                agent_decision_required: true,
                evidence_policy: {{ policy_id: 'source_local_candidate_ranking' }},
                coverage: {{
                  candidate_count: 2,
                  ranked_candidate_count: 2,
                  top_observed_candidate: 'rs111',
                  top_observed_support_level: 'high'
                }},
                candidate_matrix: [
                  {{
                    candidate_id: 'rs111',
                    candidate_type: 'rsid',
                    rank: 1,
                    score: 0.92,
                    evidence_support_level: 'high',
                    answerability: 'direct_source_supported',
                    best_evidence_lane: 'direct_source_match',
                    best_pvalue: '1e-9',
                    supporting_evidence: [
                      {{
                        candidate_id: 'rs111',
                        trait: 'LDL cholesterol',
                        pvalue: '1e-9',
                        source_id: 'GCST000001',
                        study: 'GWAS Catalog'
                      }}
                    ]
                  }},
                  {{
                    candidate_id: 'rs222',
                    candidate_type: 'rsid',
                    rank: 2,
                    score: 0.41,
                    evidence_support_level: 'low',
                    answerability: 'adjacent_source_supported',
                    best_evidence_lane: 'nearby_trait_match',
                    supporting_evidence: []
                  }}
                ],
                rankings: [],
                warnings: ['Population-level associations are not individual diagnosis.']
              }},
              evidence_envelope: canonical.evidence_envelope
            }};
            const phenotypePayload = {{
              headline: 'phenotype.compare_gene_hpo_evidence: data_returned',
              query: {{ phenotype_text: 'ataxia and seizures', hpo_ids: ['HP:0001251'], genes: ['PNKP', 'SPG7'] }},
              evidence_view: {{
                query: {{ phenotype_text: 'ataxia and seizures', hpo_ids: ['HP:0001251'], genes: ['PNKP', 'SPG7'] }},
                coverage_state: 'data_returned',
                evidence_state: 'decision_grade_evidence',
                agent_decision_required: true,
                evidence_policy: {{ policy_id: 'phenotype_gene_source_ranking' }},
                coverage: {{ candidate_count: 2, ranked_candidate_count: 1, top_observed_candidate: 'PNKP', top_observed_support_level: 'medium' }},
                candidate_matrix: [
                  {{
                    candidate_id: 'PNKP',
                    candidate_type: 'gene_symbol',
                    rank: 1,
                    score: 0.68,
                    evidence_support_level: 'medium',
                    answerability: 'direct_source_supported',
                    best_evidence_lane: 'ontology_synonym_match',
                    supporting_evidence: [{{ candidate_id: 'PNKP', phenotype: 'ataxia', source_id: 'HPO:PNKP' }}]
                  }},
                  {{
                    candidate_id: 'SPG7',
                    candidate_type: 'gene_symbol',
                    rank: null,
                    score: 0,
                    evidence_support_level: 'none',
                    answerability: 'not_supported',
                    supporting_evidence: []
                  }}
                ],
                rankings: []
              }},
              evidence_envelope: canonical.evidence_envelope
            }};
            const screenPayload = {{
              headline: 'functional_genomics.compare_gene_perturbation: data_returned',
              query: {{ context: 'CRISPR dependency screen', phenotype: 'cell viability', genes: ['MYC'] }},
              evidence_view: {{
                query: {{ context: 'CRISPR dependency screen', phenotype: 'cell viability', genes: ['MYC'] }},
                coverage_state: 'data_returned',
                evidence_state: 'decision_grade_evidence',
                agent_decision_required: true,
                evidence_policy: {{ policy_id: 'screen_source_ranking' }},
                coverage: {{ candidate_count: 1, ranked_candidate_count: 1, top_observed_candidate: 'MYC', top_observed_support_level: 'high' }},
                candidate_matrix: [
                  {{
                    candidate_id: 'MYC',
                    candidate_type: 'gene_symbol',
                    rank: 1,
                    score: 0.94,
                    evidence_support_level: 'high',
                    answerability: 'direct_source_supported',
                    best_evidence_lane: 'direct_source_match',
                    supporting_evidence: [{{ candidate_id: 'MYC', phenotype: 'cell viability', source_id: 'DepMap:MYC' }}]
                  }}
                ],
                rankings: []
              }},
              evidence_envelope: canonical.evidence_envelope
            }};
            const contextPayload = {{
              status: 'available',
              has_active_genome_index: true,
              context_policy: {{ mode: 'explicit', implicit_artifact_selection: false }},
              active_genome_index_access: {{ approved: true, scope: 'current_session' }},
              active_genome_index: {{
                status: 'parsed',
                genome_build: 'GRCh38',
                source_type: 'vcf',
                active_genome_index_readiness: {{ status: 'completed', complete: true, variants_ready: false }}
              }},
              active_genome_index_registry: {{ known_agi_count: 2, known_user_count: 1 }},
              selection_source: 'current_chat',
              default_auto_selected: false,
              context_axes: {{ active_genome_index: {{ current_state: 'active_accessible', known_agis: 2 }} }},
              active_response_profile: {{ id: 'expert', label: 'Expert' }}
            }};
            const disposeCustomRenderer = renderers.registerGenomiResultRenderer('custom.evidence_view', (payload, operation, normalized) => ({{
              kind: 'custom',
              operation,
              kicker: 'Custom evidence view',
              title: payload.headline || 'Custom',
              summary: normalized.headline || 'Custom summary',
              evidenceEnvelope: normalized.envelope,
              metrics: [{{ label: 'Nodes', value: 1 }}],
              lanes: [{{
                title: 'Custom lane',
                nodes: [{{ label: 'Custom node', summary: 'Custom summary', context: 'Custom node: ok', value: {{ ok: true }} }}]
              }}]
            }}));
            const customView = renderers.genomiResultViewModel({{
              call: {{ name: 'custom.evidence_view' }},
              result: {{ payload: canonical }}
            }});
            const registeredAfterCustom = renderers.registeredGenomiResultRendererOperations();
            disposeCustomRenderer();
            const customViewAfterDispose = renderers.genomiResultViewModel({{
              call: {{ name: 'custom.evidence_view' }},
              result: {{ payload: canonical }}
            }});
            const registeredBuiltIns = renderers.registeredGenomiResultRendererOperations();
            const variantRecord = {{
              call: {{ id: 'call_variant', name: 'variant.resolve' }},
              result: {{
                id: 'result_variant',
                name: 'variant.resolve',
                payload: variantPayload,
                portal_presentation: variantServerPresentation
              }}
            }};
            const variantPersistedPresentation = {{
              ...variantServerPresentation,
              metrics: variantServerPresentation.metrics.filter((item) => item.label !== 'Support'),
              lanes: variantServerPresentation.lanes.filter((item) => item.title !== 'Genotype support'),
              notice: {{
                title: 'Persisted redacted history',
                text: 'This saved view includes only persisted public lanes. Private/sample and support sections were omitted; re-check the tool before using evidence.'
              }}
            }};
            const persistedRecord = {{
              call: {{ id: 'call_persisted', name: 'variant.resolve', persisted_display_only: true, ledger: {{ display_only: true, presentation_state: 'persisted_redacted' }} }},
              result: {{ id: 'result_persisted', name: 'variant.resolve', payload: {{
                ...variantPayload,
                presentation_state: 'persisted_redacted'
              }}, portal_presentation: variantPersistedPresentation, persisted_display_only: true, presentation_state: 'persisted_redacted', ledger: {{ display_only: true, presentation_state: 'persisted_redacted' }} }}
            }};
            const persistedPresentedResult = presentation.toolResultPresentation(persistedRecord);
            const variantViewForSearch = renderers.genomiResultViewModel(variantRecord);
            const result = {{
              canonical: mod.hasCanonicalEvidenceEnvelope(canonical),
              nonEnvelope: mod.hasCanonicalEvidenceEnvelope(nonEnvelope),
              context: mod.evidenceContextForPayload(canonical, 'variant.resolve'),
              evidencePanelFallbackPacket: mod.evidenceSelectedPacketForPayload(canonical, 'variant.resolve'),
              evidencePanelSelectedPacket: mod.evidenceSelectedPacketForPayload(canonical, 'variant.resolve', [
                {{ label: 'Remaining node', text: 'Remaining beta evidence' }}
              ]),
              traceKeys: trace.resultTraceEntries(canonical).map((entry) => entry.key),
              ignoredTopLevelTraceKeys: trace.resultTraceEntries({{ steps: [{{ status: 'queried' }}] }}).map((entry) => entry.key),
              promptSafeText: selected.promptSafeText('agi_path: "/Users/matthewzmd/.genomi/private.sqlite" and context_file=/tmp/context.json'),
              selectedPayload: selected.selectedEvidencePayload({{
                label: 'Sensitive context',
                sourceOperation: 'genomi.describe_context',
                evidenceEnvelope: {{ finding_state: 'browser_should_not_send' }},
                selectedNodes: [{{ label: 'AGI', text: 'registry_file: "/Users/matthewzmd/.genomi/registry.json"' }}]
              }}),
              selectedPayloadSensitiveStrings: selected.selectedEvidencePayload({{
                label: 'Result at /Users/matthewzmd/.genomi/result.json',
                sourceOperation: 'tool from /opt/homebrew/bin/codex',
                toolCallId: 'call-/tmp/private-call',
                toolResultId: 'result-/var/folders/private-result',
                selectedNodes: [
                  {{
                    label: 'Node at /Users/matthewzmd/.genomi/node.json',
                    text: 'context_file=/Users/matthewzmd/.genomi/context.json',
                    value: '/tmp/value.txt'
                  }}
                ],
                promptIntro: 'Intro from /Applications/private.app'
              }}),
              evidenceTrayModel: prompt.contextDisplayModel({{
                label: 'Sensitive context',
                source_operation: 'variant.resolve',
                summary: 'Evidence from /tmp/private/result.json',
                selected_nodes: [
                  {{ label: 'ClinVar', text: 'ClinVar node' }},
                  {{ label: 'AGI', text: 'registry_file: "/Users/matthewzmd/.genomi/registry.json"' }}
                ],
                finding_state: 'data_returned'
              }}),
              evidenceTrayNodes: prompt.contextNodes({{
                selected_nodes: [
                  {{ label: 'ClinVar', text: 'ClinVar node' }},
                  {{ label: 'AGI', text: 'registry_file: "/Users/matthewzmd/.genomi/registry.json"' }}
                ]
              }}),
              evidenceTrayPacketText: prompt.packetPromptText({{
                prompt_text: 'Selected context_file: "/Users/matthewzmd/.genomi/context.json" with ClinVar evidence'
              }}),
              rebuiltEvidenceTrayPacket: prompt.rebuildContextItemWithNodes({{
                id: 'ctx-two',
                label: 'Two node packet',
                source_operation: 'variant.resolve',
                summary: 'Removed alpha evidence and remaining beta evidence',
                prompt_text: 'Selected packet\\n- Removed alpha evidence\\n- Remaining beta evidence',
                selected_nodes: [
                  {{ label: 'Alpha', text: 'Removed alpha evidence' }},
                  {{ label: 'Beta', text: 'Remaining beta evidence' }}
                ]
              }}, [
                {{ label: 'Beta', text: 'Remaining beta evidence' }}
              ]),
              serializedEvidenceTray: prompt.serializeContextItems([
                {{
                  id: 'ctx-persist',
                  label: 'Context at /Users/matthewzmd/.genomi/private.json',
                  context_kind: 'result_nodes',
                  source_operation: 'variant.resolve',
                  finding_state: 'data_returned',
                  summary: 'Summary from /tmp/private/result.json',
                  selected_nodes: [
                    {{ label: 'ClinVar', text: 'ClinVar node' }},
                    {{ label: 'AGI', text: 'context_file=/Users/matthewzmd/.genomi/context.json' }}
                  ],
                  evidence_envelope: {{ finding_state: 'browser_payload_should_not_persist' }}
                }}
              ]),
              parsedEvidenceTray: prompt.parseStoredContextItems(prompt.serializeContextItems([
                {{
                  id: 'ctx-persist',
                  label: 'Context at /Users/matthewzmd/.genomi/private.json',
                  context_kind: 'result_nodes',
                  source_operation: 'variant.resolve',
                  finding_state: 'data_returned',
                  selected_nodes: [
                    {{ label: 'AGI', text: 'context_file=/Users/matthewzmd/.genomi/context.json' }}
                  ],
                  evidence_envelope: {{ finding_state: 'browser_payload_should_not_persist' }}
                }}
              ])),
              messageSurfaceExport: typeof messages.createMessageSurface,
              hostBridge: messages.hostBridgeModel(
                {{ id: 'codex', label: 'Codex CLI from /opt/homebrew/bin/codex', runnable: true }},
                [{{ label: 'ClinVar node' }}, {{ label: 'Active genome' }}]
              ),
              emptyHostBridge: messages.hostBridgeModel(
                {{ id: 'codex', label: 'Codex CLI from /opt/homebrew/bin/codex', runnable: true }},
                []
              ),
              promptControllerExport: typeof prompt.createPromptContextController,
              summary: mod.toolResultSummary({{ isError: false, content: 'truncated preview', payload: canonical }}),
              extractedFromPayload: mod.extractPresentedPayload({{ result: {{ content: 'truncated preview', payload: canonical }} }}).headline,
              variantView: variantViewForSearch,
              variantViewLaneTitles: variantViewForSearch.lanes.map((lane) => lane.title),
              variantViewMetricLabels: variantViewForSearch.metrics.filter(Boolean).map((item) => item.label),
              variantEvidenceStateLabels: (variantViewForSearch.lanes.find((lane) => lane.title === 'Coverage and limits') || {{ nodes: [] }}).nodes.map((node) => node.label),
              variantEvidenceStateSelectable: (variantViewForSearch.lanes.find((lane) => lane.title === 'Coverage and limits') || {{}}).selectable,
              variantEvidenceStateNodeSelectability: (variantViewForSearch.lanes.find((lane) => lane.title === 'Coverage and limits') || {{ nodes: [] }}).nodes.map((node) => node.selectable),
              variantPresentation: presentation.toolResultPresentation({{
                ...variantRecord,
                call: {{ ...variantRecord.call, id: null }},
                result: {{ ...variantRecord.result, id: null }}
              }}),
              genericEnvelopePresentation: presentation.toolResultPresentation({{
                call: {{ name: 'custom.no_renderer' }},
                result: {{ payload: canonical }}
              }}),
              variantSearchAll: renderers.resultSearchModel(variantViewForSearch),
              variantSearchClinvar: renderers.resultSearchModel(variantViewForSearch, 'clinvar'),
              variantSearchMissing: renderers.resultSearchModel(variantViewForSearch, 'zzzz-no-hit'),
              rawVariantView: renderers.genomiResultViewModel({{ call: {{ name: 'variant.resolve' }}, result: {{ payload: variantPayload }} }}),
              rawPgxView: renderers.genomiResultViewModel({{ call: {{ name: 'pharmacogenomics.review_medication' }}, result: {{ payload: pgxPayload }} }}),
              gwasVariantView: renderers.genomiResultViewModel({{ call: {{ name: 'gwas.compare_variant_associations' }}, result: {{ payload: gwasVariantPayload }} }}),
              gwasVariantSearch: renderers.resultSearchModel(renderers.genomiResultViewModel({{ call: {{ name: 'gwas.compare_variant_associations' }}, result: {{ payload: gwasVariantPayload }} }}), 'GCST000001'),
              phenotypeView: renderers.genomiResultViewModel({{ call: {{ name: 'phenotype.compare_gene_hpo_evidence' }}, result: {{ payload: phenotypePayload }} }}),
              screenView: renderers.genomiResultViewModel({{ call: {{ name: 'functional_genomics.compare_gene_perturbation' }}, result: {{ payload: screenPayload }} }}),
              contextView: renderers.genomiResultViewModel({{ call: {{ name: 'genomi.describe_context' }}, result: {{ payload: contextPayload }} }}),
              customView,
              customViewAfterDispose,
              registeredAfterCustom,
              registeredBuiltIns,
              variantWithoutEnvelope: renderers.genomiResultViewModel({{
                call: {{ name: 'variant.resolve' }},
                result: {{ payload: {{ resolved_targets: [{{ rsid: 'rs429358' }}] }} }}
              }}),
              fieldGuessedPgx: renderers.genomiResultViewModel({{
                call: {{ name: 'research.build_target_packet' }},
                result: {{ payload: pgxPayload }}
              }}),
              persistedPresentedResult,
              currentFollowUp: presentation.toolResultFollowUpRequest({{
                call: {{ id: 'call_current', name: 'variant.resolve' }},
                result: {{ id: 'result_current', name: 'variant.resolve', payload: variantPayload, portal_presentation: variantServerPresentation }}
              }}),
              persistedFollowUp: presentation.toolResultFollowUpRequest(persistedRecord),
              currentToolAction: details.toolFollowUpActionModel({{
                call: {{ id: 'call_current', name: 'variant.resolve' }},
                result: {{ id: 'result_current', name: 'variant.resolve', payload: variantPayload, portal_presentation: variantServerPresentation }}
              }}),
              persistedToolAction: details.toolFollowUpActionModel(persistedRecord),
              persistedPresentedContext: presentation.toolResultContextPayload(persistedRecord),
              persistedPresentedMetricLabels: persistedPresentedResult.resultModel.metrics.filter(Boolean).map((item) => item.label),
              persistedPresentedLaneTitles: persistedPresentedResult.resultModel.lanes.map((item) => item.title),
              persistedEvidencePacket: mod.evidenceSelectedPacketForPayload({{ ...variantPayload, presentation_state: 'persisted_redacted' }}, 'variant.resolve'),
              evidencePanelInspector: mod.evidencePanelSelectionInspectorModel([
                {{
                  dataset: {{
                    label: 'Guidance from /Users/matthewzmd/.genomi/private.json',
                    context: 'Guidance: context_file=/Users/matthewzmd/.genomi/context.json',
                    value: '/tmp/private-guidance.json'
                  }}
                }}
              ]),
              resultSelectionInspector: renderers.resultSelectionInspectorModel([
                {{
                  dataset: {{
                    label: 'ClinVar row from /Users/matthewzmd/.genomi/private.json',
                    lane: 'ClinVar records',
                    context: 'ClinVar records / APOE: context_file=/Users/matthewzmd/.genomi/context.json',
                    value: '/tmp/private-row.json'
                  }}
                }}
              ])
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertTrue(result["canonical"])
        self.assertFalse(result["nonEnvelope"])
        self.assertIn("Selected evidence from Variant lookup", result["context"])
        self.assertNotIn("Selected evidence from variant.resolve", result["context"])
        self.assertEqual(result["context"], result["evidencePanelFallbackPacket"]["prompt_text"])
        self.assertIn("Remaining beta evidence", result["evidencePanelSelectedPacket"]["prompt_text"])
        self.assertNotIn("Removed alpha evidence", result["evidencePanelSelectedPacket"]["prompt_text"])
        self.assertIn("Answer readiness: answer_supported", result["context"])
        self.assertNotIn("Trace Steps", result["context"])
        self.assertNotIn("not evidence authority", result["context"])
        self.assertIn("steps", result["traceKeys"])
        self.assertIn("sources", result["traceKeys"])
        self.assertEqual(result["ignoredTopLevelTraceKeys"], [])
        self.assertNotIn("evidence_envelope", result["traceKeys"])
        self.assertNotIn("defaults_applied", result["traceKeys"])
        self.assertNotIn("coverage", result["traceKeys"])
        self.assertNotIn("observations", result["traceKeys"])
        self.assertNotIn("next_actions", result["traceKeys"])
        _assert_public_prompt_text(result["promptSafeText"])
        _assert_public_prompt_text(result["selectedPayload"]["prompt_text"])
        self.assertNotIn("evidence_envelope", result["selectedPayload"])
        _assert_public_payload(result["selectedPayloadSensitiveStrings"])
        _assert_public_prompt_text(result["evidenceTrayModel"]["preview"])
        self.assertEqual(result["evidenceTrayModel"]["source"], "Variant lookup")
        self.assertEqual(result["evidenceTrayModel"]["nodeCount"], 2)
        self.assertEqual(result["evidenceTrayModel"]["envelopeState"], "data_returned")
        self.assertEqual(result["evidenceTrayNodes"][0]["label"], "ClinVar")
        self.assertEqual(result["evidenceTrayNodes"][0]["text"], "ClinVar node")
        _assert_public_prompt_text(result["evidenceTrayNodes"][1]["text"])
        _assert_public_prompt_text(result["evidenceTrayPacketText"])
        self.assertNotIn("prompt_text", result["rebuiltEvidenceTrayPacket"])
        self.assertEqual(result["rebuiltEvidenceTrayPacket"]["selected_nodes"][0]["text"], "Remaining beta evidence")
        self.assertIn("Remaining beta evidence", result["rebuiltEvidenceTrayPacket"]["summary"])
        self.assertNotIn("Removed alpha evidence", result["rebuiltEvidenceTrayPacket"]["summary"])
        _assert_public_prompt_text(result["serializedEvidenceTray"])
        self.assertNotIn("evidence_envelope", result["serializedEvidenceTray"])
        self.assertEqual(result["parsedEvidenceTray"][0]["source_operation"], "variant.resolve")
        self.assertEqual(result["parsedEvidenceTray"][0]["context_kind"], "result_nodes")
        self.assertEqual(result["parsedEvidenceTray"][0]["finding_state"], "data_returned")
        self.assertNotIn("prompt_text", result["parsedEvidenceTray"][0])
        self.assertEqual(result["parsedEvidenceTray"][0]["selected_nodes"][0]["text"], "context file: [redacted local path]")
        _assert_public_payload(result["parsedEvidenceTray"])
        self.assertNotIn("evidence_envelope", result["parsedEvidenceTray"][0])
        self.assertEqual(result["messageSurfaceExport"], "function")
        self.assertEqual(result["hostBridge"]["id"], "codex")
        self.assertEqual(result["hostBridge"]["packetCount"], 2)
        self.assertIn("2 included items", result["hostBridge"]["summary"])
        self.assertEqual(result["hostBridge"]["status"], "ready")
        self.assertIn("[redacted local path]", result["hostBridge"]["label"])
        _assert_public_payload(result["hostBridge"])
        self.assertIsNone(result["emptyHostBridge"])
        self.assertEqual(result["promptControllerExport"], "function")
        self.assertEqual(result["summary"], "variant.resolve: data_returned")
        self.assertEqual(result["extractedFromPayload"], "variant.resolve: data_returned")
        self.assertEqual(result["variantView"]["kind"], "variant")
        self.assertEqual(result["variantView"]["title"], "rs429358")
        self.assertIn("ClinVar records", result["variantViewLaneTitles"])
        self.assertIn("Coverage and limits", result["variantViewLaneTitles"])
        self.assertIn("Answer boundary", result["variantViewMetricLabels"])
        self.assertIn("Evidence support", result["variantViewMetricLabels"])
        self.assertNotIn("How to use this: Use limit 1", result["variantEvidenceStateLabels"])
        self.assertIn("Coverage: Consulted Libraries", result["variantEvidenceStateLabels"])
        self.assertFalse(result["variantEvidenceStateSelectable"])
        self.assertTrue(result["variantEvidenceStateNodeSelectability"])
        self.assertTrue(all(value is False for value in result["variantEvidenceStateNodeSelectability"]))
        self.assertEqual(result["variantPresentation"]["primaryPanelKind"], "result_view")
        self.assertTrue(result["variantPresentation"]["canRenderResult"])
        self.assertTrue(result["variantPresentation"]["canRenderEvidence"])
        self.assertEqual(result["genericEnvelopePresentation"]["primaryPanelKind"], "evidence")
        self.assertFalse(result["genericEnvelopePresentation"]["canRenderResult"])
        self.assertTrue(result["genericEnvelopePresentation"]["canRenderEvidence"])
        self.assertTrue(result["variantSearchAll"]["visible"])
        self.assertEqual(result["variantSearchAll"]["totalNodes"], 5)
        self.assertEqual(result["variantSearchAll"]["matchingNodes"], 5)
        self.assertEqual(result["variantSearchAll"]["summary"], "5 items")
        self.assertEqual(result["variantSearchClinvar"]["matchingNodes"], 2)
        self.assertEqual(result["variantSearchClinvar"]["summary"], "2 of 5 shown")
        self.assertEqual(
            {lane["title"]: lane["matching"] for lane in result["variantSearchClinvar"]["lanes"]},
            {"Resolved targets": 0, "ClinVar records": 1, "Genotype support": 0, "Coverage and limits": 1},
        )
        self.assertTrue(result["variantSearchMissing"]["empty"])
        self.assertEqual(result["variantSearchMissing"]["summary"], "0 of 5 shown")
        self.assertTrue(all(lane["matching"] == 0 for lane in result["variantSearchMissing"]["lanes"]))
        self.assertIsNone(result["rawVariantView"])
        self.assertIsNone(result["rawPgxView"])
        self.assertIsNone(result["gwasVariantView"])
        self.assertEqual(result["gwasVariantSearch"]["matchingNodes"], 0)
        self.assertIsNone(result["phenotypeView"])
        self.assertIsNone(result["screenView"])
        self.assertEqual(result["contextView"]["kind"], "context")
        self.assertEqual(result["contextView"]["title"], "GRCh38 · VCF genome")
        self.assertEqual(result["contextView"]["summary"], "GRCh38 · VCF · 2 known genomes")
        self.assertIn("Build", [metric["label"] for metric in result["contextView"]["metrics"]])
        self.assertIn("Current genome", [lane["title"] for lane in result["contextView"]["lanes"]])
        self.assertEqual(result["customView"]["kind"], "custom")
        self.assertEqual(result["customView"]["operation"], "custom.evidence_view")
        self.assertIn("custom.evidence_view", result["registeredAfterCustom"])
        self.assertIsNone(result["customViewAfterDispose"])
        self.assertNotIn("variant.resolve", result["registeredBuiltIns"])
        self.assertNotIn("pharmacogenomics.review_medication", result["registeredBuiltIns"])
        self.assertNotIn("gwas.compare_variant_associations", result["registeredBuiltIns"])
        self.assertNotIn("gwas.compare_gene_associations", result["registeredBuiltIns"])
        self.assertNotIn("phenotype.compare_gene_hpo_evidence", result["registeredBuiltIns"])
        self.assertNotIn("phenotype.compare_disease_evidence", result["registeredBuiltIns"])
        self.assertNotIn("phenotype.compare_drug_target_evidence", result["registeredBuiltIns"])
        self.assertNotIn("phenotype.plan_risk_investigation", result["registeredBuiltIns"])
        self.assertNotIn("functional_genomics.compare_gene_perturbation", result["registeredBuiltIns"])
        self.assertNotIn("clinvar.scan_candidates", result["registeredBuiltIns"])
        self.assertNotIn("research.build_target_packet", result["registeredBuiltIns"])
        self.assertIsNone(result["variantWithoutEnvelope"])
        self.assertIsNone(result["fieldGuessedPgx"])
        self.assertTrue(result["persistedPresentedResult"]["displayOnly"])
        self.assertEqual(result["persistedPresentedResult"]["presentationState"], "persisted_redacted")
        self.assertTrue(result["persistedPresentedResult"]["canRenderResult"])
        self.assertFalse(result["persistedPresentedResult"]["canRenderEvidence"])
        self.assertFalse(result["persistedPresentedResult"]["canAttach"])
        self.assertEqual(result["persistedPresentedResult"]["kind"], "persisted_redacted")
        self.assertEqual(result["currentFollowUp"]["selectedEvidence"][0]["context_kind"], "result_nodes")
        self.assertEqual(result["currentFollowUp"]["selectedEvidence"][0]["source_operation"], "variant.resolve")
        self.assertEqual(result["currentToolAction"]["label"], "Ask follow-up")
        self.assertEqual(result["currentToolAction"]["followUp"]["selectedEvidence"], result["currentFollowUp"]["selectedEvidence"])
        self.assertEqual(result["persistedFollowUp"]["selectedEvidence"][0]["context_kind"], "work_trace")
        self.assertEqual(result["persistedFollowUp"]["selectedEvidence"][0]["source_operation"], "variant.resolve")
        self.assertEqual(result["persistedFollowUp"]["presentationState"], "persisted_redacted")
        self.assertEqual(result["persistedToolAction"]["label"], "Re-check evidence")
        self.assertEqual(result["persistedToolAction"]["followUp"]["selectedEvidence"], result["persistedFollowUp"]["selectedEvidence"])
        self.assertEqual(result["persistedPresentedResult"]["resultModel"]["notice"]["title"], "Persisted redacted history")
        self.assertIn("Resolved", result["persistedPresentedMetricLabels"])
        self.assertIn("ClinVar", result["persistedPresentedMetricLabels"])
        self.assertNotIn("Sample hits", result["persistedPresentedMetricLabels"])
        self.assertNotIn("Support", result["persistedPresentedMetricLabels"])
        self.assertIn("ClinVar records", result["persistedPresentedLaneTitles"])
        self.assertNotIn("Sample context", result["persistedPresentedLaneTitles"])
        self.assertNotIn("Genotype support", result["persistedPresentedLaneTitles"])
        self.assertIsNone(result["persistedPresentedContext"])
        self.assertIsNone(result["persistedEvidencePacket"])
        self.assertEqual(result["resultSelectionInspector"]["count"], 1)
        self.assertEqual(result["resultSelectionInspector"]["nodes"][0]["lane"], "ClinVar records")
        self.assertIn("[redacted local path]", result["resultSelectionInspector"]["nodes"][0]["text"])
        _assert_public_payload(result["resultSelectionInspector"])
        self.assertEqual(result["evidencePanelInspector"]["count"], 1)
        self.assertEqual(result["evidencePanelInspector"]["nodes"][0]["label"], "Guidance from [redacted local path]")
        self.assertIn("[redacted local path]", result["evidencePanelInspector"]["nodes"][0]["text"])
        self.assertIn("[redacted local path]", result["evidencePanelInspector"]["nodes"][0]["value"])
        _assert_public_payload(result["evidencePanelInspector"])

    def test_evidence_ledger_models_keep_display_only_history_non_attachable(self) -> None:
        ledger_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_evidence_ledger.js").as_uri()
        script = textwrap.dedent(
            f"""
            const ledger = await import({ledger_url!r});
            const canonical = {{
              headline: 'variant.resolve: data_returned',
              status: 'completed',
              evidence_envelope: {{
                finding_state: 'data_returned',
                answer_readiness: 'answer_supported',
                guidance: ['data_returned:use_variant_evidence'],
                coverage: {{ consulted_libraries: ['dbSNP', 'ClinVar'] }},
                observations: {{ variant: 'rs429358' }}
              }}
            }};
            const variantPersistedPresentation = {{
              schema: 'genomi_portal_result_presentation',
              source: 'server',
              operation: 'variant.resolve',
              kind: 'variant',
              kicker: 'Variant evidence map',
              title: 'rs429358',
              summary: 'variant.resolve: data_returned',
              evidenceEnvelope: canonical.evidence_envelope,
              metrics: [
                {{ label: 'Resolved', value: 1 }},
                {{ label: 'ClinVar', value: 1 }}
              ],
              lanes: [
                {{
                  title: 'Resolved targets',
                  nodes: [{{
                    label: 'rs429358',
                    summary: 'identifier',
                    context: 'Resolved targets / rs429358: identifier',
                    value: {{ rsid: 'rs429358', resolution_status: 'identifier' }}
                  }}]
                }},
                {{
                  title: 'ClinVar records',
                  nodes: [{{
                    label: 'rs429358',
                    summary: 'risk_factor',
                    context: 'ClinVar records / rs429358: risk_factor',
                    value: {{ rsid: 'rs429358', clinical_significance: 'risk_factor' }}
                  }}]
                }}
              ],
              notice: {{
                title: 'Persisted redacted history',
                text: 'This saved view includes only persisted public lanes. Private/sample and support sections were omitted; re-check the tool before using evidence.'
              }}
            }};
            const currentRecord = {{
              call: {{ id: 'call_variant', name: 'variant.resolve', input: {{ rsid: 'rs429358' }} }},
              result: {{ id: 'call_variant', name: 'variant.resolve', payload: canonical }}
            }};
            const contextRecord = {{
              call: {{ id: 'call_context', name: 'genomi.describe_context', input: {{}} }},
              result: {{
                id: 'result_context',
                name: 'genomi.describe_context',
                payload: {{
                  status: 'available',
                  has_active_genome_index: true,
                  context_policy: {{ mode: 'explicit' }},
                  active_genome_index_access: {{ approved: true, scope: 'current_session' }},
                  active_genome_index: {{
                    status: 'parsed',
                    genome_build: 'GRCh38',
                    active_genome_index_readiness: {{ status: 'completed', complete: true, variants_ready: false }}
                  }},
                  active_genome_index_registry: {{ known_agi_count: 2, known_user_count: 1 }},
                  selection_source: 'current_chat',
                  context_axes: {{ active_genome_index: {{ current_state: 'active_accessible', known_agis: 2 }} }},
                  active_response_profile: {{ id: 'expert', label: 'Expert' }}
                }}
              }}
            }};
            const displayOnlyRecord = {{
              scope: {{ frameId: 'frame_1', runId: 'run_1' }},
              result: {{
                id: 'call_1',
                name: 'variant.resolve',
                persisted_display_only: true,
                content: 'variant.resolve: data_returned',
                ledger: {{
                  operation: 'variant.resolve',
                  status: 'completed',
                  summary: 'variant.resolve: data_returned',
                  answer_readiness: 'answer_supported',
                  finding_state: 'data_returned',
                  display_only: true
                }}
              }}
            }};
            const displayOnlyPayloadRecord = {{
              scope: {{ frameId: 'frame_1', runId: 'run_1' }},
              call: {{
                id: 'call_2',
                name: 'variant.resolve',
                persisted_display_only: true,
                ledger: {{ display_only: true, presentation_state: 'persisted_redacted' }}
              }},
              result: {{
                id: 'call_2',
                name: 'variant.resolve',
                persisted_display_only: true,
                presentation_state: 'persisted_redacted',
                ledger: {{
                  operation: 'variant.resolve',
                  status: 'completed',
                  summary: 'variant.resolve: data_returned',
                  answer_readiness: 'answer_supported',
                  finding_state: 'data_returned',
                  presentation_state: 'persisted_redacted',
                  display_only: true
                }},
                payload: {{
                  ...canonical,
                  presentation_state: 'persisted_redacted',
                  query: {{ rsid: 'rs429358' }},
                  resolved_targets: [{{ rsid: 'rs429358', resolution_status: 'identifier' }}],
                  public_context: {{ clinvar_by_rsid: [{{ rsid: 'rs429358', clinical_significance: 'risk_factor' }}] }}
                }},
                portal_presentation: variantPersistedPresentation
              }}
            }};
            const entries = [
              ledger.ledgerEntryModel(currentRecord),
              ledger.ledgerEntryModel(contextRecord),
              ledger.ledgerEntryModel(displayOnlyRecord),
              ledger.ledgerEntryModel({{ call: {{ id: 'running', name: 'variant.resolve' }} }}),
              ledger.ledgerEntryModel({{ result: {{ id: 'error', name: 'variant.resolve', isError: true, content: 'failed' }} }})
            ];
            const result = {{
              ledgerEntry: ledger.ledgerEntryModel(currentRecord),
              ledgerDetail: ledger.ledgerDetailModel(currentRecord),
              ledgerFollowUp: ledger.ledgerFollowUpPrompt(currentRecord),
              ledgerFollowUpRequest: ledger.ledgerFollowUpRequest(currentRecord),
              ledgerContext: ledger.ledgerContextPayload(currentRecord),
              ledgerSelectedNodePayload: ledger.ledgerContextPayload(currentRecord, {{
                querySelectorAll: () => [
                  {{ dataset: {{ label: 'Coverage / Libraries', context: 'Coverage / Libraries: dbSNP', value: 'dbSNP' }} }}
                ]
              }}),
              ledgerContextDetail: ledger.ledgerDetailModel(contextRecord),
              ledgerContextPayload: ledger.ledgerContextPayload(contextRecord, {{
                querySelectorAll: () => [
                  {{ dataset: {{ label: 'Current genome / Build', context: 'Active genome / Current genome / Build: GRCh38', value: 'GRCh38' }} }}
                ]
              }}),
              ledgerReusableFilter: ledger.filterLedgerEntries(entries, 'reusable').map((entry) => entry.operation),
              ledgerRunningFilter: ledger.filterLedgerEntries(entries, 'running').map((entry) => entry.operation),
              ledgerErrorFilter: ledger.filterLedgerEntries(entries, 'errors').map((entry) => entry.operation),
              ledgerSummary: ledger.ledgerSummaryPayload(entries),
              ledgerRedacted: ledger.ledgerEntryModel({{
                call: {{ id: 'call_shell', name: 'bash', input: {{ command: 'cat /Users/matthewzmd/private.txt' }} }},
                result: {{ id: 'call_shell', name: 'bash', content: 'Wrote result to /Users/matthewzmd/private/result.json' }}
              }}),
              ledgerDisplayOnly: ledger.ledgerEntryModel(displayOnlyRecord),
              ledgerDisplayOnlyDetail: ledger.ledgerDetailModel(displayOnlyRecord),
              ledgerDisplayOnlyFollowUp: ledger.ledgerFollowUpPrompt(displayOnlyRecord),
              ledgerDisplayOnlyContext: ledger.ledgerContextPayload(displayOnlyRecord),
              ledgerRedactedPayload: ledger.ledgerEntryModel(displayOnlyPayloadRecord),
              ledgerRedactedPayloadDetail: ledger.ledgerDetailModel(displayOnlyPayloadRecord),
              ledgerRedactedPayloadFollowUp: ledger.ledgerFollowUpPrompt(displayOnlyPayloadRecord),
              ledgerRedactedPayloadFollowUpRequest: ledger.ledgerFollowUpRequest(displayOnlyPayloadRecord),
              ledgerRedactedPayloadContext: ledger.ledgerContextPayload(displayOnlyPayloadRecord)
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["ledgerEntry"]["operation"], "variant.resolve")
        self.assertEqual(result["ledgerEntry"]["answerReadiness"], "answer_supported")
        self.assertEqual(result["ledgerEntry"]["findingState"], "data_returned")
        self.assertIn("call_variant", result["ledgerEntry"]["key"])
        self.assertTrue(result["ledgerDetail"]["canRenderEvidence"])
        self.assertTrue(result["ledgerDetail"]["canAttach"])
        self.assertTrue(result["ledgerDetail"]["hasCanonicalEnvelope"])
        self.assertFalse(result["ledgerDetail"]["displayOnly"])
        self.assertIn("Selected evidence from Variant lookup", result["ledgerFollowUp"])
        self.assertNotIn("Selected evidence from variant.resolve", result["ledgerFollowUp"])
        self.assertEqual(result["ledgerFollowUpRequest"]["operation"], "variant.resolve")
        self.assertEqual(result["ledgerFollowUpRequest"]["selectedEvidence"][0]["prompt_text"], result["ledgerFollowUp"])
        self.assertEqual(result["ledgerFollowUpRequest"]["selectedEvidence"][0]["context_kind"], "evidence_panel")
        self.assertIn("variant.resolve", result["ledgerContext"]["source_operation"])
        self.assertIn("Selected evidence from Variant lookup", result["ledgerContext"]["prompt_text"])
        self.assertNotIn("Selected evidence from variant.resolve", result["ledgerContext"]["prompt_text"])
        self.assertNotIn("evidence_envelope", result["ledgerContext"])
        self.assertIn("Coverage / Libraries: dbSNP", result["ledgerSelectedNodePayload"]["prompt_text"])
        self.assertIn("Selected evidence", result["ledgerSelectedNodePayload"]["prompt_text"])
        self.assertNotIn("Selected Variant evidence map", result["ledgerSelectedNodePayload"]["prompt_text"])
        self.assertTrue(result["ledgerContextDetail"]["canRenderResult"])
        self.assertFalse(result["ledgerContextDetail"]["hasCanonicalEnvelope"])
        self.assertTrue(result["ledgerContextDetail"]["canAttach"])
        self.assertEqual(result["ledgerContextPayload"]["source_operation"], "genomi.describe_context")
        self.assertEqual(result["ledgerContextPayload"]["tool_call_id"], "call_context")
        self.assertEqual(result["ledgerContextPayload"]["tool_result_id"], "result_context")
        self.assertIn("Active genome / Current genome / Build: GRCh38", result["ledgerContextPayload"]["prompt_text"])
        self.assertEqual(result["ledgerReusableFilter"], ["variant.resolve"])
        self.assertEqual(result["ledgerRunningFilter"], ["variant.resolve"])
        self.assertEqual(result["ledgerErrorFilter"], ["variant.resolve"])
        self.assertEqual(result["ledgerSummary"]["label"], "Current evidence summary")
        self.assertIn("Selected current evidence summary", result["ledgerSummary"]["prompt_text"])
        self.assertIn("Variant lookup", result["ledgerSummary"]["prompt_text"])
        self.assertNotIn("variant.resolve", result["ledgerSummary"]["prompt_text"])
        self.assertNotIn("genomi.describe_context", result["ledgerSummary"]["prompt_text"])
        self.assertNotIn("display-only", result["ledgerSummary"]["prompt_text"].lower())
        _assert_public_payload(result["ledgerSummary"])
        _assert_public_prompt_text(result["ledgerRedacted"]["summary"])
        self.assertEqual(result["ledgerDisplayOnly"]["answerReadiness"], "answer_supported")
        self.assertEqual(result["ledgerDisplayOnly"]["findingState"], "data_returned")
        self.assertIn("frame_1:run_1:call_1", result["ledgerDisplayOnly"]["key"])
        self.assertFalse(result["ledgerDisplayOnlyDetail"]["canRenderEvidence"])
        self.assertFalse(result["ledgerDisplayOnlyDetail"]["canAttach"])
        self.assertFalse(result["ledgerDisplayOnlyDetail"]["hasCanonicalEnvelope"])
        self.assertTrue(result["ledgerDisplayOnlyDetail"]["displayOnly"])
        self.assertIn("Selected saved evidence to re-check", result["ledgerDisplayOnlyFollowUp"])
        self.assertIn("Variant lookup", result["ledgerDisplayOnlyFollowUp"])
        self.assertNotIn("workflow event", result["ledgerDisplayOnlyFollowUp"].lower())
        self.assertIsNone(result["ledgerDisplayOnlyContext"])
        self.assertEqual(result["ledgerRedactedPayload"]["presentationState"], "persisted_redacted")
        self.assertEqual(result["ledgerRedactedPayloadDetail"]["reuseKind"], "persisted_redacted")
        self.assertTrue(result["ledgerRedactedPayloadDetail"]["canRenderResult"])
        self.assertFalse(result["ledgerRedactedPayloadDetail"]["canRenderEvidence"])
        self.assertFalse(result["ledgerRedactedPayloadDetail"]["canAttach"])
        self.assertTrue(result["ledgerRedactedPayloadDetail"]["hasCanonicalEnvelope"])
        self.assertTrue(result["ledgerRedactedPayloadDetail"]["displayOnly"])
        self.assertIn("Selected saved evidence to re-check", result["ledgerRedactedPayloadFollowUp"])
        self.assertIn("Variant lookup", result["ledgerRedactedPayloadFollowUp"])
        self.assertNotIn("workflow event", result["ledgerRedactedPayloadFollowUp"].lower())
        self.assertEqual(result["ledgerRedactedPayloadFollowUpRequest"]["presentationState"], "persisted_redacted")
        self.assertEqual(
            result["ledgerRedactedPayloadFollowUpRequest"]["selectedEvidence"][0]["label"],
            "Saved evidence: Variant lookup",
        )
        self.assertEqual(result["ledgerRedactedPayloadFollowUpRequest"]["selectedEvidence"][0]["prompt_text"], result["ledgerRedactedPayloadFollowUp"])
        self.assertEqual(result["ledgerRedactedPayloadFollowUpRequest"]["selectedEvidence"][0]["context_kind"], "work_trace")
        self.assertIsNone(result["ledgerRedactedPayloadContext"])


def _run_node_json(test_case: unittest.TestCase, script: str):
    if shutil.which("node") is None:
        test_case.skipTest("node is required for frontend module tests")
    completed = subprocess.run(
        ["node", "--input-type=module"],
        input=script,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return json.loads(completed.stdout)


def _assert_public_prompt_text(text: str) -> None:
    if _PRIVATE_PROMPT_RE.search(text):
        raise AssertionError(f"private prompt text leaked: {text}")


def _assert_public_payload(value) -> None:
    if isinstance(value, dict):
        for child in value.values():
            _assert_public_payload(child)
    elif isinstance(value, list):
        for child in value:
            _assert_public_payload(child)
    elif isinstance(value, str):
        _assert_public_prompt_text(value)


if __name__ == "__main__":
    unittest.main()
