from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

_PRIVATE_PROMPT_RE = re.compile(
    r"(?:context_file|registry_file|agi_path|/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes|~)"
)


class PortalArtifactOriginTraceFrontendTest(unittest.TestCase):
    def test_portal_asset_manifest_serves_artifact_origin_trace_module(self) -> None:
        from genomi.interfaces import portal_assets

        self.assertIn("portal_artifact_origin_trace.js", portal_assets.template_asset_names())
        self.assertIn("portal_artifact_work_trace_controller.js", portal_assets.template_asset_names())

    def test_artifact_origin_trace_reuses_frame_trace_context_node_and_redacts_paths(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"
        artifact_trace_url = (root / "portal_artifact_origin_trace.js").as_uri()
        frame_trace_url = (root / "portal_frame_trace.js").as_uri()
        script = textwrap.dedent(
            f"""
            const artifactTrace = await import({artifact_trace_url!r});
            const frameTrace = await import({frame_trace_url!r});
            const messages = [
              {{
                id: 'msg_call',
                role: 'tool',
                frame_id: 'frame_origin',
                run_id: 'run_1',
                event: {{
                  type: 'tool_call',
                  id: 'tool_1',
                  name: 'variant.resolve',
                  input: {{ rsid: 'rs429358' }},
                  ledger: {{ status: 'running', summary: 'Resolving /Users/matthewzmd/private/source.vcf' }}
                }}
              }},
              {{
                id: 'msg_result',
                role: 'tool',
                frame_id: 'frame_origin',
                run_id: 'run_1',
                event: {{
                  type: 'tool_result',
                  id: 'tool_1',
                  content: 'variant.resolve result from /tmp/private/result.json',
                  persisted_display_only: true,
                  presentation_state: 'persisted_redacted',
                  ledger: {{
                    status: 'completed',
                    summary: 'Saved public result from context_file=/Users/matthewzmd/private/result.json',
                    display_only: true,
                    presentation_state: 'persisted_redacted'
                  }}
                }}
              }}
            ];
            const frameModel = frameTrace.frameWorkTraceModel(messages);
            const expectedNode = frameTrace.frameTraceStepContextNode(frameModel.steps[0], 0, {{ structuredValue: true }});
            const artifactModel = artifactTrace.artifactWorkTraceModel({{
              provenance_messages: {{
                frame_id: 'frame_origin',
                total: messages.length,
                messages
              }}
            }});
            process.stdout.write(JSON.stringify({{
              title: artifactModel.title,
              metrics: artifactModel.metrics,
              node: artifactModel.sections[0].nodes[0],
              expectedNode,
              serialized: JSON.stringify(artifactModel)
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["title"], "Origin work trail")
        self.assertEqual(result["metrics"][0], {"label": "Steps", "value": 1})
        self.assertEqual(result["node"], result["expectedNode"])
        self.assertEqual(result["node"]["label"], "1. Variant lookup")
        self.assertIn("Work trail / Variant lookup", result["node"]["text"])
        self.assertIn("status: completed", result["node"]["summary"])
        self.assertIn("[redacted local path]", result["node"]["summary"])
        _assert_public_payload(result["serialized"])

    def test_artifact_origin_trace_merges_execution_cells_from_producing_run(self) -> None:
        artifact_trace_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifact_origin_trace.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const artifactTrace = await import({artifact_trace_url!r});
            const messages = [
              {{
                id: 'msg_call',
                role: 'tool',
                frame_id: 'frame_origin',
                run_id: 'run_1',
                event: {{
                  type: 'tool_call',
                  id: 'tool_1',
                  name: 'variant.resolve',
                  input: {{ rsid: 'rs429358' }}
                }}
              }},
              {{
                id: 'msg_result',
                role: 'tool',
                frame_id: 'frame_origin',
                run_id: 'run_1',
                event: {{
                  type: 'tool_result',
                  id: 'tool_1',
                  name: 'variant.resolve',
                  content: 'Resolved rs429358',
                  ledger: {{ status: 'completed', summary: 'Variant evidence returned' }}
                }}
              }}
            ];
            const model = artifactTrace.artifactWorkTraceModel({{
              provenance_messages: {{
                frame_id: 'frame_origin',
                total: messages.length,
                messages
              }}
            }}, {{
              executionCells: [
                {{
                  id: 'run_1:tool:tool_1',
                  kind: 'tool',
                  operation: 'variant.resolve',
                  status: 'completed',
                  summary: 'Duplicate tool cell',
                  run_id: 'run_1'
                }},
                {{
                  id: 'run_1:stdout:3',
                  kind: 'stdout',
                  status: 'completed',
                  title: 'STDOUT',
                  summary: 'Host agent prepared runtime.',
                  run_id: 'run_1',
                  event_ids: [3]
                }},
                {{
                  id: 'run_1:artifact:4',
                  kind: 'artifact',
                  status: 'completed',
                  title: 'Artifact',
                  summary: 'Evidence report created.',
                  run_id: 'run_1',
                  event_ids: [4]
                }}
              ]
            }});
            process.stdout.write(JSON.stringify({{
              total: model.metrics.find((item) => item.label === 'Steps').value,
              labels: model.sections[0].nodes.map((node) => node.label),
              values: model.sections[0].nodes.map((node) => node.value)
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["total"], 3)
        self.assertEqual(
            result["labels"],
            ["1. Variant lookup", "2. Diagnostic output", "3. Artifact"],
        )
        self.assertEqual(result["values"][1]["kind"], "stdout")
        self.assertEqual(result["values"][1]["event_count"], 1)

    def test_artifact_origin_trace_starts_with_persisted_producing_work_step(self) -> None:
        artifact_trace_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifact_origin_trace.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const artifactTrace = await import({artifact_trace_url!r});
            const artifact = {{
              id: 'art_apoe',
              project_id: 'proj_1',
              title: 'APOE evidence report',
              kind: 'evidence_packet',
              latest_version_id: 'ver_apoe',
              latest_version: {{
                version_id: 'ver_apoe',
                producing_work_step: {{
                  kind: 'artifact_producing_work_step',
                  title: 'Produced artifact',
                  status: 'completed',
                  summary: 'APOE evidence ready',
                  artifact: {{ title: 'APOE evidence report', kind: 'evidence_packet' }},
                  origin: {{ frame_id: 'frame_1', run_id: 'run_1' }},
                  execution_cell: {{ id: 'run_1:artifact:9', kind: 'artifact', event_ids: [9] }},
                  workspace_route: '/projects/proj_1/frames/frame_1?highlight_run=run_1'
                }}
              }},
              provenance_messages: {{ messages: [] }}
            }};
            const model = artifactTrace.artifactWorkTraceModel(artifact, {{
              executionCells: [
                {{
                  id: 'run_1:stdout:3',
                  kind: 'stdout',
                  status: 'completed',
                  title: 'STDOUT',
                  summary: 'Runtime ready',
                  run_id: 'run_1',
                  event_ids: [3]
                }}
              ]
            }});
            const scoped = artifactTrace.artifactWorkTraceExecutionCells(artifact, []);
            process.stdout.write(JSON.stringify({{
              labels: model.sections[0].nodes.map((node) => node.label),
              summaries: model.sections[0].nodes.map((node) => node.summary),
              values: model.sections[0].nodes.map((node) => node.value),
              scoped
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["labels"], ["1. Produced artifact", "2. Diagnostic output"])
        self.assertIn("APOE evidence ready", result["summaries"][0])
        self.assertEqual(result["values"][0]["kind"], "artifact")
        self.assertEqual(result["values"][0]["run_id"], "run_1")
        self.assertEqual(result["values"][0]["event_count"], 1)
        self.assertEqual(result["scoped"][0]["id"], "run_1:artifact:9")
        self.assertEqual(result["scoped"][0]["event_ids"], [9])
        self.assertEqual(result["scoped"][0]["title"], "Produced artifact")
        self.assertEqual(result["scoped"][0]["artifact"]["workspace_route"], "/projects/proj_1/artifacts/art_apoe/versions/ver_apoe")

    def test_artifact_origin_trace_filters_artifact_cells_to_selected_artifact(self) -> None:
        artifact_trace_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifact_origin_trace.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const artifactTrace = await import({artifact_trace_url!r});
            const executionCells = {{
              run_id: 'run_1',
              items: [
                {{
                  id: 'run_1:stdout:3',
                  kind: 'stdout',
                  status: 'completed',
                  title: 'STDOUT',
                  summary: 'Shared runtime preparation',
                  event_ids: [3]
                }},
                {{
                  id: 'run_1:artifact:4',
                  kind: 'artifact',
                  status: 'completed',
                  title: 'APOE report',
                  summary: 'APOE report created',
                  artifact: {{
                    id: 'art_apoe',
                    project_id: 'proj_1',
                    title: 'APOE report',
                    latest_version_id: 'ver_apoe'
                  }},
                  event_ids: [4]
                }},
                {{
                  id: 'run_1:artifact:5',
                  kind: 'artifact',
                  status: 'completed',
                  title: 'LDL report',
                  summary: 'LDL report created',
                  artifact: {{
                    id: 'art_ldl',
                    project_id: 'proj_1',
                    title: 'LDL report',
                    latest_version_id: 'ver_ldl'
                  }},
                  event_ids: [5]
                }}
              ]
            }};
            const model = artifactTrace.artifactWorkTraceModel({{
              id: 'art_apoe',
              latest_version_id: 'ver_apoe',
              provenance_messages: {{ messages: [] }}
            }}, {{ executionCells }});
            const scoped = artifactTrace.artifactWorkTraceExecutionCells({{
              id: 'art_apoe',
              latest_version_id: 'ver_apoe'
            }}, executionCells);
            process.stdout.write(JSON.stringify({{
              labels: model.sections[0].nodes.map((node) => node.label),
              summaries: model.sections[0].nodes.map((node) => node.summary),
              scopedTitles: scoped.items.map((cell) => cell.title),
              scopedRunId: scoped.run_id
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["labels"], ["1. Diagnostic output", "2. APOE report"])
        self.assertIn("APOE report created", result["summaries"][1])
        self.assertEqual(result["scopedTitles"], ["STDOUT", "APOE report"])
        self.assertEqual(result["scopedRunId"], "run_1")
        self.assertNotIn("LDL report", " ".join(result["summaries"]))

    def test_artifact_work_trace_controller_loads_active_artifact_run_cells(self) -> None:
        controller_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifact_work_trace_controller.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const controllerModule = await import({controller_url!r});
            const loaded = [];
            const updates = [];
            const controller = controllerModule.createArtifactWorkTraceController({{
              api: {{
                loadRunResultPackage: async (runId) => {{
                  loaded.push(runId);
                  return {{
                    execution_cells: {{
                      run_id: runId,
                      items: [
                        {{
                          id: runId + ':stdout:3',
                          kind: 'stdout',
                          status: 'completed',
                          summary: 'Runtime ready'
                        }}
                      ]
                    }}
                  }};
                }}
              }},
              onUpdate: (artifact) => updates.push(artifact.id)
            }});
            const artifact = {{
              id: 'art_1',
              origin_context: {{
                frame_id: 'frame_1',
                producing_run_id: 'run_prod',
                run_ids: ['run_prod', 'run_extra']
              }},
              provenance_messages: {{
                messages: [
                  {{ id: 'msg_1', role: 'assistant', run_id: 'run_from_message', text: 'Artifact ready' }}
                ]
              }}
            }};
            const before = controller.executionCellsFor(artifact);
            const hydrated = await controller.hydrate(artifact);
            const after = controller.executionCellsFor(artifact);
            const secondHydrate = await controller.hydrate(artifact);
            process.stdout.write(JSON.stringify({{
              beforeCount: before.length,
              hydrated,
              secondHydrate,
              loaded,
              updates,
              afterKinds: after.map((cell) => cell.kind),
              afterRunIds: after.map((cell) => cell.run_id),
              runIds: controllerModule.artifactWorkTraceRunIds(artifact)
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["beforeCount"], 0)
        self.assertTrue(result["hydrated"])
        self.assertFalse(result["secondHydrate"])
        self.assertEqual(result["loaded"], ["run_prod", "run_extra", "run_from_message"])
        self.assertEqual(result["updates"], ["art_1"])
        self.assertEqual(result["afterKinds"], ["stdout", "stdout", "stdout"])
        self.assertEqual(result["afterRunIds"], ["run_prod", "run_extra", "run_from_message"])
        self.assertEqual(result["runIds"], ["run_prod", "run_extra", "run_from_message"])

    def test_artifact_work_trace_preserves_producing_run_while_capping_secondary_ids(self) -> None:
        controller_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifact_work_trace_controller.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const controllerModule = await import({controller_url!r});
            const secondaryRunIds = Array.from({{ length: 12 }}, (_item, index) => 'run_secondary_' + index);
            const artifact = {{
              id: 'art_1',
              origin_context: {{
                frame_id: 'frame_1',
                producing_run_id: 'run_producing',
                run_ids: ['run_producing', ...secondaryRunIds.slice(0, 6)]
              }},
              provenance_messages: {{
                messages: secondaryRunIds.slice(6).map((runId, index) => ({{
                  id: 'msg_' + index,
                  role: 'assistant',
                  run_id: runId,
                  text: 'Artifact step'
                }}))
              }}
            }};
            process.stdout.write(JSON.stringify({{
              runIds: controllerModule.artifactWorkTraceRunIds(artifact)
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["runIds"][0], "run_producing")
        self.assertEqual(len(result["runIds"]), 9)
        self.assertEqual(result["runIds"][1:], [f"run_secondary_{index}" for index in range(4, 12)])

    def test_artifact_work_trace_cache_is_scoped_to_project_and_version_and_can_clear(self) -> None:
        controller_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifact_work_trace_controller.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const controllerModule = await import({controller_url!r});
            const loaded = [];
            const controller = controllerModule.createArtifactWorkTraceController({{
              api: {{
                loadRunResultPackage: async (runId) => {{
                  loaded.push(runId);
                  return {{
                    execution_cells: {{
                      run_id: runId,
                      items: [
                        {{
                          id: runId + ':run:' + loaded.length,
                          kind: 'run',
                          status: 'completed',
                          summary: 'Loaded package ' + loaded.length
                        }}
                      ]
                    }}
                  }};
                }}
              }}
            }});
            const baseArtifact = {{
              id: 'art_1',
              project_id: 'proj_a',
              latest_version_id: 'ver_latest',
              origin_context: {{
                frame_id: 'frame_1',
                producing_run_id: 'run_prod',
                run_ids: ['run_prod']
              }}
            }};
            const firstHydrate = await controller.hydrate(baseArtifact);
            const cachedHydrate = await controller.hydrate({{ ...baseArtifact }});
            const selectedVersionHydrate = await controller.hydrate({{
              ...baseArtifact,
              selected_version_id: 'ver_selected'
            }});
            const otherProjectHydrate = await controller.hydrate({{
              ...baseArtifact,
              project_id: 'proj_b'
            }});
            controller.reset({{ clearCache: true }});
            const afterClearHydrate = await controller.hydrate(baseArtifact);
            process.stdout.write(JSON.stringify({{
              firstHydrate,
              cachedHydrate,
              selectedVersionHydrate,
              otherProjectHydrate,
              afterClearHydrate,
              loaded
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertTrue(result["firstHydrate"])
        self.assertFalse(result["cachedHydrate"])
        self.assertTrue(result["selectedVersionHydrate"])
        self.assertTrue(result["otherProjectHydrate"])
        self.assertTrue(result["afterClearHydrate"])
        self.assertEqual(result["loaded"], ["run_prod", "run_prod", "run_prod", "run_prod"])

    def test_rendered_trace_cards_send_step_context(self) -> None:
        artifacts_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifacts.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const artifacts = await import(__ARTIFACTS_URL__);

            class ClassList {
              constructor(element) { this.element = element; }
              items() { return String(this.element.className || '').split(/\\s+/).filter(Boolean); }
              set(items) { this.element.className = [...new Set(items)].join(' '); }
              add(...names) { this.set([...this.items(), ...names.filter(Boolean)]); }
              remove(...names) { this.set(this.items().filter((item) => !names.includes(item))); }
              contains(name) { return this.items().includes(name); }
              toggle(name, force) {
                const active = force === undefined ? !this.contains(name) : Boolean(force);
                if (active) this.add(name);
                else this.remove(name);
                return active;
              }
            }

            class Element {
              constructor(tagName) {
                this.tagName = String(tagName || '').toLowerCase();
                this.children = [];
                this.parentNode = null;
                this.attributes = {};
                this.dataset = {};
                this.eventListeners = {};
                this.className = '';
                this.textContent = '';
                this.hidden = false;
                this.classList = new ClassList(this);
              }
              appendChild(child) {
                child.parentNode = this;
                this.children.push(child);
                return child;
              }
              setAttribute(name, value) {
                const text = String(value);
                this.attributes[name] = text;
                if (name === 'class') this.className = text;
                if (name === 'id') this.id = text;
                if (name.startsWith('data-')) this.dataset[dataKey(name.slice(5))] = text;
              }
              getAttribute(name) {
                if (name === 'class') return this.className;
                return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
              }
              addEventListener(type, handler) {
                this.eventListeners[type] = this.eventListeners[type] || [];
                this.eventListeners[type].push(handler);
              }
              click() {
                (this.eventListeners.click || []).forEach((handler) => handler({
                  preventDefault() {},
                  stopPropagation() {}
                }));
              }
              closest(selector) {
                let node = this;
                while (node) {
                  if (matches(node, selector)) return node;
                  node = node.parentNode;
                }
                return null;
              }
              querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
              querySelectorAll(selector) { return querySelectorAll(this, selector); }
              set innerHTML(value) {
                this.children = [];
                this.textContent = '';
                parseHtml(String(value || ''), this);
              }
              get innerHTML() { return ''; }
            }

            function dataKey(name) {
              return name.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
            }

            function descendants(node) {
              const found = [];
              node.children.forEach((child) => {
                found.push(child);
                found.push(...descendants(child));
              });
              return found;
            }

            function querySelectorAll(root, selector) {
              const parts = String(selector || '').trim().split(/\\s+/).filter(Boolean);
              let current = [root];
              parts.forEach((part) => {
                const next = [];
                current.forEach((node) => {
                  descendants(node).forEach((child) => {
                    if (matches(child, part)) next.push(child);
                  });
                });
                current = next;
              });
              return current;
            }

            function matches(element, selector) {
              const attr = String(selector || '').match(/^\\[([^=\\]]+)(?:="([^"]*)")?\\]$/);
              if (attr) {
                const value = element.getAttribute(attr[1]);
                return attr[2] === undefined ? value !== null : value === attr[2];
              }
              const pieces = String(selector || '').split('.');
              const tag = pieces[0];
              if (tag && tag !== element.tagName) return false;
              return pieces.slice(1).every((name) => element.classList.contains(name));
            }

            function parseHtml(html, root) {
              const tags = /<\\/?[^>]+>/g;
              const stack = [root];
              let match;
              while ((match = tags.exec(html))) {
                const token = match[0];
                if (/^<\\//.test(token)) {
                  if (stack.length > 1) stack.pop();
                  continue;
                }
                const parsed = token.match(/^<([a-zA-Z0-9-]+)([^>]*)>/);
                if (!parsed) continue;
                const child = new Element(parsed[1]);
                const attrs = parsed[2] || '';
                const attrPattern = /([a-zA-Z0-9:-]+)(?:="([^"]*)")?/g;
                let attr;
                while ((attr = attrPattern.exec(attrs))) child.setAttribute(attr[1], attr[2] || '');
                stack[stack.length - 1].appendChild(child);
                if (!/\\/>$/.test(token) && !['br', 'hr', 'img', 'input', 'link', 'meta'].includes(child.tagName)) {
                  stack.push(child);
                }
              }
            }

            function visibleText(node) {
              const own = node.textContent || '';
              return [own, ...node.children.map((child) => visibleText(child))]
                .filter(Boolean)
                .join(' ')
                .replace(/\\s+/g, ' ')
                .trim();
            }

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            globalThis.window = { location: { href: 'http://127.0.0.1:8768/projects/proj_1' } };

            const container = document.createElement('div');
            let received = null;
            const artifact = {
              id: 'art_trace',
              kind: 'decode_dashboard',
              renderer: 'decode_dashboard',
              title: 'Trace artifact',
              status: 'completed',
              operation: 'decode.render_dashboard',
              summary_lines: ['completed'],
              provenance_messages: {
                frame_id: 'frame_origin',
                total: 2,
                messages: [
                  {
                    id: 'msg_call',
                    role: 'tool',
                    frame_id: 'frame_origin',
                    run_id: 'run_1',
                    event: {
                      type: 'tool_call',
                      id: 'tool_1',
                      name: 'variant.resolve',
                      input: { rsid: 'rs429358' }
                    }
                  },
                  {
                    id: 'msg_result',
                    role: 'tool',
                    frame_id: 'frame_origin',
                    run_id: 'run_1',
                    event: {
                      type: 'tool_result',
                      id: 'tool_1',
                      content: 'variant.resolve result from /tmp/private/result.json',
                      ledger: { status: 'completed', summary: 'Saved result from /Users/matthewzmd/private/result.json' }
                    }
                  }
                ]
              }
            };

            artifacts.renderArtifactPreview(container, artifact, {
              baseUrl: window.location.href,
              activeTabId: 'trace',
              onUseContext: (payload) => { received = payload; }
            });
            const tracePanel = container.querySelector('[data-artifact-panel="trace"]');
            const traceTab = container.querySelector('[data-testid="genomi-provenance-tab-trace"]');
            const steps = tracePanel ? tracePanel.querySelectorAll('[data-testid="frame-trace-step"]') : [];
            const step = steps.find((node) => visibleText(node).includes('variant.resolve')) || steps[0];
            const useStep = step ? step.querySelectorAll('button').find((button) => visibleText(button) === 'Use this step') : null;
            process.stdout.write(JSON.stringify({
              hasTracePanel: Boolean(tracePanel),
              traceTabActive: traceTab ? traceTab.classList.contains('active') : false,
              tracePanelVisible: tracePanel ? tracePanel.hidden === false : false,
              traceStepCount: steps.length,
              hasArtifactWorkTrail: Boolean(tracePanel && tracePanel.querySelector('[data-testid="frame-trace-step"]')),
              hasUseStep: Boolean(useStep),
              visibleText: tracePanel ? visibleText(tracePanel) : ''
            }));
            """
        ).replace("__ARTIFACTS_URL__", json.dumps(artifacts_url))

        result = _run_node_json(self, script)

        self.assertTrue(result["hasTracePanel"])
        self.assertTrue(result["traceTabActive"])
        self.assertTrue(result["tracePanelVisible"])
        self.assertTrue(result["hasArtifactWorkTrail"])
        self.assertGreaterEqual(result["traceStepCount"], 1)
        self.assertFalse(result["hasUseStep"])
        self.assertIn("Work that produced this artifact", result["visibleText"])
        self.assertIn("Variant lookup", result["visibleText"])
        self.assertNotIn("Use this step", result["visibleText"])


def _run_node_json(test_case: unittest.TestCase, script: str):
    if shutil.which("node") is None:
        test_case.skipTest("node is required for frontend module tests")
    completed = subprocess.run(
        ["node", "--input-type=module"],
        input=script,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        test_case.fail(completed.stderr)
    return json.loads(completed.stdout)


def _assert_public_payload(value) -> None:
    encoded = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    assert not _PRIVATE_PROMPT_RE.search(encoded), encoded
