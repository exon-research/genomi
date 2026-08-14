import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

from tests.test_portal_frontend_artifact_library import _dom_shim_script


class PortalFrameTraceFrontendTest(unittest.TestCase):
    def test_portal_asset_manifest_serves_frame_trace_module(self) -> None:
        from genomi.interfaces import portal_assets

        self.assertIn("portal_frame_trace.js", portal_assets.template_asset_names())
        self.assertIn("portal_work_trace_controller.js", portal_assets.template_asset_names())

    def test_portal_shell_exposes_work_trace_pane(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"
        html = (root / "portal.html").read_text()

        self.assertIn('data-nav-target="work-trace-pane"', html)
        self.assertIn('id="frame-work-trace"', html)

    def test_work_trace_controller_loads_execution_cells_and_live_records(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"
        controller_url = (root / "portal_work_trace_controller.js").as_uri()
        trace_url = (root / "portal_frame_trace.js").as_uri()
        script = textwrap.dedent(
            f"""
            const controllerModule = await import({controller_url!r});
            const trace = await import({trace_url!r});
            const renders = [];
            const controller = controllerModule.createWorkTraceController({{
              container: {{}},
              api: {{
                loadRunResultPackage: async (runId) => ({{
                  execution_cells: {{
                    run_id: runId,
                    items: [
                      {{
                        id: runId + ':tool:call_1',
                        kind: 'tool',
                        title: 'variant.resolve',
                        operation: 'variant.resolve',
                        status: 'completed',
                        summary: 'Duplicate tool cell',
                        event_ids: [2],
                        event_range: {{ first: 2, last: 2 }},
                        records: []
                      }},
                      {{
                        id: runId + ':stdout:3',
                        kind: 'stdout',
                        title: 'STDOUT',
                        status: 'completed',
                        summary: 'Host agent prepared runtime.',
                        visibility: 'technical',
                        event_ids: [3],
                        event_range: {{ first: 3, last: 3 }},
                        records: [{{ id: 3, event: 'stdout', data: {{ chunk: 'Host agent prepared runtime.' }} }}]
                      }},
                      {{
                        id: runId + ':artifact:4',
                        kind: 'artifact',
                        title: 'Artifact',
                        status: 'completed',
                        summary: 'Evidence report created',
                        event_ids: [4],
                        event_range: {{ first: 4, last: 4 }},
                        records: [{{ id: 4, event: 'artifact', data: {{ title: 'Evidence report created' }} }}]
                      }},
                      {{
                        id: runId + ':run:5',
                        kind: 'run',
                        title: 'Run finished',
                        status: 'succeeded',
                        summary: 'Run finished: succeeded',
                        event_ids: [5],
                        event_range: {{ first: 5, last: 5 }},
                        records: [{{ id: 5, event: 'end', data: {{ status: 'succeeded' }} }}]
                      }}
                    ]
                  }}
                }})
              }},
              renderWorkTrace: (container, messages, options) => {{
                const model = trace.frameWorkTraceModel(messages, options);
                renders.push({{
                  total: model.total,
                  titles: model.steps.map((step) => step.title),
                  kinds: model.steps.map((step) => step.kind),
                  highlightStepId: options.highlightStepId || '',
                  executionCellCount: Array.isArray(options.executionCells) ? options.executionCells.length : 0
                }});
              }}
            }});
            await controller.setFrameMessages('frame_1', {{
              frame_id: 'frame_1',
              messages: [
                {{
                  id: 'msg_call',
                  role: 'tool',
                  frame_id: 'frame_1',
                  run_id: 'run_1',
                  event: {{
                    type: 'tool_call',
                    id: 'call_1',
                    name: 'variant.resolve',
                    input: {{ rsid: 'rs429358' }}
                  }}
                }},
                {{
                  id: 'msg_result',
                  role: 'tool',
                  frame_id: 'frame_1',
                  run_id: 'run_1',
                  event: {{
                    type: 'tool_result',
                    id: 'call_1',
                    content: 'variant.resolve: data_returned',
                    ledger: {{ status: 'completed', summary: 'Public variant evidence returned.' }}
                  }}
                }}
              ]
            }}, {{ highlightStepId: 'run_1:artifact:4' }});
            controller.beginLiveRun('frame_1');
            const tracked = controller.trackLiveToolRecord({{
              scope: {{ frameId: 'frame_1', runId: 'run_live', messageId: 'msg_live' }},
              call: {{
                id: 'tool_live',
                name: 'pharmacogenomics.review_medication',
                input: {{ drug: 'clopidogrel' }}
              }}
            }}, {{ runId: 'run_live' }});
            const ignored = controller.trackLiveToolRecord({{
              scope: {{ frameId: 'frame_1', runId: 'wrong_run', messageId: 'msg_wrong' }},
              call: {{ id: 'tool_wrong', name: 'research.build_target_packet' }}
            }}, {{ runId: 'run_live' }});
            process.stdout.write(JSON.stringify({{
              renderCount: renders.length,
              initial: renders[0],
              loaded: renders[1],
              live: renders[renders.length - 1],
              tracked,
              ignored
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertGreaterEqual(result["renderCount"], 3)
        self.assertEqual(result["initial"]["titles"], ["Variant lookup"])
        self.assertEqual(result["initial"]["executionCellCount"], 0)
        self.assertEqual(result["initial"]["highlightStepId"], "run_1:artifact:4")
        self.assertEqual(result["loaded"]["total"], 3)
        self.assertEqual(result["loaded"]["titles"], ["Variant lookup", "Artifact", "Run finished"])
        self.assertEqual(result["loaded"]["kinds"], ["tool", "artifact", "run"])
        self.assertEqual(result["loaded"]["executionCellCount"], 4)
        self.assertEqual(result["loaded"]["highlightStepId"], "run_1:artifact:4")
        self.assertTrue(result["tracked"])
        self.assertFalse(result["ignored"])
        self.assertIn("Medication-response review", result["live"]["titles"])
        self.assertNotIn("Target evidence report", result["live"]["titles"])

    def test_work_trace_controller_reports_visible_work_only_for_real_steps(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"
        controller_url = (root / "portal_work_trace_controller.js").as_uri()
        script = textwrap.dedent(
            f"""
            const controllerModule = await import({controller_url!r});
            const stateChanges = [];
            const controller = controllerModule.createWorkTraceController({{
              container: {{}},
              api: {{
                loadRunResultPackage: async () => ({{
                  execution_cells: {{
                    run_id: 'run_cells',
                    items: [
                      {{
                        id: 'run_cells:stdout:1',
                        kind: 'stdout',
                        title: 'Diagnostic output',
                        status: 'completed',
                        summary: 'Host agent prepared runtime.',
                        event_ids: [1],
                        event_range: {{ first: 1, last: 1 }},
                        records: []
                      }}
                    ]
                  }}
                }})
              }},
              renderWorkTrace: () => undefined,
              onStateChange: (state) => stateChanges.push(state.hasWork)
            }});
            const initial = controller.hasWork();
            controller.reset();
            const afterReset = controller.hasWork();
            await controller.setFrameMessages('frame_diagnostic', {{
              frame_id: 'frame_diagnostic',
              messages: [
                {{
                  id: 'msg_stdout',
                  role: 'tool',
                  frame_id: 'frame_diagnostic',
                  run_id: '',
                  event: {{ type: 'stdout', chunk: 'prepared runtime' }}
                }}
              ]
            }});
            const afterDiagnosticOnly = controller.hasWork();
            await controller.setFrameMessages('frame_tool', {{
              frame_id: 'frame_tool',
              messages: [
                {{
                  id: 'msg_call',
                  role: 'tool',
                  frame_id: 'frame_tool',
                  run_id: 'run_tool',
                  event: {{
                    type: 'tool_call',
                    id: 'call_1',
                    name: 'variant.resolve',
                    input: {{ rsid: 'rs429358' }}
                  }}
                }}
              ]
            }});
            const afterToolCall = controller.hasWork();
            await controller.setFrameMessages('frame_cells', {{
              frame_id: 'frame_cells',
              messages: [
                {{
                  id: 'msg_run',
                  role: 'tool',
                  frame_id: 'frame_cells',
                  run_id: 'run_cells',
                  event: {{ type: 'end', status: 'succeeded' }}
                }}
              ]
            }});
            const afterExecutionCells = controller.hasWork();
            process.stdout.write(JSON.stringify({{
              initial,
              afterReset,
              afterDiagnosticOnly,
              afterToolCall,
              afterExecutionCells,
              stateChanges
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertFalse(result["initial"])
        self.assertFalse(result["afterReset"])
        self.assertFalse(result["afterDiagnosticOnly"])
        self.assertTrue(result["afterToolCall"])
        self.assertTrue(result["afterExecutionCells"])
        self.assertIn(False, result["stateChanges"])
        self.assertIn(True, result["stateChanges"])

    def test_work_trace_controller_tracks_live_record_for_new_chat_frame(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"
        controller_url = (root / "portal_work_trace_controller.js").as_uri()
        trace_url = (root / "portal_frame_trace.js").as_uri()
        script = textwrap.dedent(
            f"""
            const controllerModule = await import({controller_url!r});
            const trace = await import({trace_url!r});
            const renders = [];
            const controller = controllerModule.createWorkTraceController({{
              container: {{}},
              api: {{ loadRunResultPackage: async () => ({{ execution_cells: {{ items: [] }} }}) }},
              renderWorkTrace: (container, messages, options) => {{
                const model = trace.frameWorkTraceModel(messages, options);
                renders.push({{
                  total: model.total,
                  titles: model.steps.map((step) => step.title)
                }});
              }}
            }});
            controller.reset();
            controller.beginLiveRun('frame_new');
            const tracked = controller.trackLiveToolRecord({{
              scope: {{ frameId: 'frame_new', runId: 'run_new', messageId: 'msg_live' }},
              call: {{
                id: 'tool_live',
                name: 'variant.resolve',
                input: {{ rsid: 'rs429358' }}
              }}
            }}, {{ runId: 'run_new' }});
            process.stdout.write(JSON.stringify({{
              tracked,
              latest: renders[renders.length - 1]
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertTrue(result["tracked"])
        self.assertEqual(result["latest"]["total"], 1)
        self.assertEqual(result["latest"]["titles"], ["Variant lookup"])

    def test_frame_trace_pairs_tool_events_and_exports_safe_summary(self) -> None:
        trace_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_frame_trace.js").as_uri()
        script = textwrap.dedent(
            f"""
            const trace = await import({trace_url!r});
            const canonical = {{
              headline: 'rs429358 public evidence returned',
              status: 'data_returned',
              query: {{ rsid: 'rs429358' }},
              resolved_targets: [{{ rsid: 'rs429358', gene: 'APOE' }}],
              public_context: {{ clinvar_by_rsid: [{{ clinical_significance: 'risk factor' }}] }},
              evidence_envelope: {{
                finding_state: 'data_returned',
                answer_readiness: 'partial_public_evidence',
                guidance: ['public_evidence_returned:preserve_source_prior']
              }},
              presentation_state: 'persisted_redacted'
            }};
            const messages = [
              {{ id: 'msg_user', role: 'user', text: 'Resolve rs429358', frame_id: 'frame_1' }},
              {{
                id: 'msg_call',
                role: 'tool',
                frame_id: 'frame_1',
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
                frame_id: 'frame_1',
                run_id: 'run_1',
                event: {{
                  type: 'tool_result',
                  id: 'tool_1',
                  payload: canonical,
                  content: 'variant.resolve: data_returned',
                  persisted_display_only: true,
                  presentation_state: 'persisted_redacted',
                  ledger: {{
                    status: 'completed',
                    summary: 'Saved redacted public result from /tmp/private/result.json',
                    display_only: true,
                    presentation_state: 'persisted_redacted'
                  }}
                }}
              }},
              {{
                id: 'msg_error',
                role: 'tool',
                frame_id: 'frame_1',
                run_id: 'run_1',
                event: {{
                  type: 'error',
                  id: 'tool_2',
                  name: 'research.build_target_packet',
                  message: 'failed to render /Users/matthewzmd/private/packet.html'
                }}
              }}
            ];
            const liveMessage = trace.frameTraceMessageFromToolRecord({{
              scope: {{ frameId: 'frame_1', runId: 'run_live' }},
              call: {{ id: 'tool_live', name: 'pharmacogenomics.review_medication', input: {{ drug: 'clopidogrel' }} }}
            }});
            const model = trace.frameWorkTraceModel([...messages, liveMessage]);
            const payload = trace.frameTraceSummaryPayload(model);
            const stepPayload = trace.frameTraceStepPayload(model.steps[0], 0);
            const result = {{
              total: model.total,
              status: model.status,
              counts: model.counts,
              first: model.steps[0],
              second: model.steps[1],
              third: model.steps[2],
              payload,
              stepPayload,
              traceLineCount: payload.prompt_text.split('\\n').length
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["status"], "needs_attention")
        self.assertEqual(result["counts"]["errors"], 1)
        self.assertEqual(result["counts"]["running"], 1)
        self.assertEqual(result["first"]["operation"], "variant.resolve")
        self.assertEqual(result["first"]["status"], "completed")
        self.assertEqual(result["first"]["presentationState"], "persisted_redacted")
        self.assertTrue(result["first"]["displayOnly"])
        self.assertEqual(result["first"]["messageIds"], ["msg_call", "msg_result"])
        self.assertEqual(result["second"]["statusClass"], "error")
        self.assertEqual(result["third"]["statusClass"], "running")
        self.assertEqual(result["payload"]["context_kind"], "work_trace")
        self.assertEqual(result["payload"]["source_operation"], "genomi.portal.frame_work_trace")
        self.assertIn("Selected conversation work trail", result["payload"]["prompt_text"])
        self.assertIn("Variant lookup", result["payload"]["prompt_text"])
        self.assertIn("Target evidence report", result["payload"]["prompt_text"])
        self.assertIn("Medication-response review", result["payload"]["prompt_text"])
        self.assertNotIn("variant.resolve", result["payload"]["prompt_text"])
        self.assertNotIn("research.build_target_packet", result["payload"]["prompt_text"])
        self.assertNotIn("pharmacogenomics.review_medication", result["payload"]["prompt_text"])
        self.assertNotIn("/Users", result["payload"]["prompt_text"])
        self.assertNotIn("/tmp/private", result["payload"]["prompt_text"])
        self.assertGreaterEqual(result["traceLineCount"], 4)
        self.assertEqual(result["stepPayload"]["label"], "Work step: Variant lookup")
        self.assertEqual(result["stepPayload"]["context_kind"], "work_trace")
        self.assertEqual(result["stepPayload"]["source_operation"], "variant.resolve")
        self.assertIn("Selected work step: Variant lookup", result["stepPayload"]["prompt_text"])
        self.assertIn("Work trail / Variant lookup", result["stepPayload"]["prompt_text"])
        self.assertNotIn("variant.resolve", result["stepPayload"]["prompt_text"])
        self.assertNotIn("/Users", result["stepPayload"]["prompt_text"])
        self.assertNotIn("/tmp/private", result["stepPayload"]["prompt_text"])

    def test_frame_trace_merges_execution_cells_without_duplicate_tool_steps(self) -> None:
        trace_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_frame_trace.js").as_uri()
        script = textwrap.dedent(
            f"""
            const trace = await import({trace_url!r});
            const rawStdout = 'Host agent prepared runtime at /Users/matthewzmd/private/source.vcf';
            const messages = [
              {{
                id: 'msg_call',
                role: 'tool',
                frame_id: 'frame_1',
                run_id: 'run_1',
                event: {{
                  type: 'tool_call',
                  id: 'call_1',
                  name: 'variant.resolve',
                  input: {{ rsid: 'rs429358' }}
                }}
              }},
              {{
                id: 'msg_result',
                role: 'tool',
                frame_id: 'frame_1',
                run_id: 'run_1',
                event: {{
                  type: 'tool_result',
                  id: 'call_1',
                  content: 'variant.resolve: data_returned',
                  ledger: {{ status: 'completed', summary: 'Public variant evidence returned.' }}
                }}
              }}
            ];
            const model = trace.frameWorkTraceModel(messages, {{
              executionCells: {{
                run_id: 'run_1',
                items: [
                  {{
                    id: 'run_1:tool:call_1',
                    kind: 'tool',
                    title: 'variant.resolve',
                    operation: 'variant.resolve',
                    status: 'completed',
                    summary: 'Duplicate tool cell',
                    event_ids: [2],
                    event_range: {{ first: 2, last: 2 }},
                    records: []
                  }},
                  {{
                    id: 'run_1:stdout:3',
                    kind: 'stdout',
                    title: 'STDOUT',
                    status: 'completed',
                    summary: rawStdout,
                    event_ids: [3],
                    event_range: {{ first: 3, last: 3 }},
                    records: [{{ id: 3, event: 'stdout', data: {{ chunk: rawStdout }} }}]
                  }},
                  {{
                    id: 'run_1:artifact:4',
                    kind: 'artifact',
                    title: 'Artifact',
                    status: 'completed',
                    summary: 'Evidence report created',
                    event_ids: [4],
                    event_range: {{ first: 4, last: 4 }},
                    records: [{{ id: 4, event: 'artifact', data: {{ title: 'Evidence report created' }} }}]
                  }},
                  {{
                    id: 'run_1:run:5',
                    kind: 'run',
                    title: 'Run finished',
                    status: 'succeeded',
                    summary: 'Run finished: succeeded',
                    event_ids: [5],
                    event_range: {{ first: 5, last: 5 }},
                    records: [{{ id: 5, event: 'end', data: {{ status: 'succeeded' }} }}]
                  }}
                ]
              }}
            }});
            const payload = trace.frameTraceSummaryPayload(model);
            process.stdout.write(JSON.stringify({{
              total: model.total,
              counts: model.counts,
              titles: model.steps.map((step) => step.title),
              kinds: model.steps.map((step) => step.kind),
              eventCounts: model.steps.map((step) => (step.eventIds || []).length),
              payloadText: payload.prompt_text
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["counts"]["errors"], 0)
        self.assertEqual(result["titles"], ["Variant lookup", "Artifact", "Run finished"])
        self.assertEqual(result["kinds"], ["tool", "artifact", "run"])
        self.assertEqual(result["eventCounts"], [0, 1, 1])
        self.assertNotIn("Host-agent diagnostic output recorded", result["payloadText"])
        self.assertNotIn("Host agent prepared runtime", result["payloadText"])
        self.assertNotIn("/Users/matthewzmd/private", result["payloadText"])
        self.assertIn("Evidence report created", result["payloadText"])
        self.assertIn("Run finished", result["payloadText"])
        self.assertNotIn("Duplicate tool cell", result["payloadText"])
        self.assertNotIn("variant.resolve", result["payloadText"])

    def test_frame_trace_renders_diagnostic_output_with_public_summary(self) -> None:
        trace_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_frame_trace.js").as_uri()
        script = _dom_shim_script() + textwrap.dedent(
            f"""
            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            const trace = await import({trace_url!r});
            const rawStderr = 'Traceback from /Users/matthewzmd/private/source.vcf';
            const container = document.createElement('div');
            trace.renderFrameWorkTrace(container, [], {{
              executionCells: {{
                run_id: 'run_1',
                items: [
                  {{
                    id: 'run_1:stderr:7',
                    kind: 'stderr',
                    title: 'STDERR',
                    status: 'completed',
                    summary: rawStderr,
                    event_ids: [7],
                    event_range: {{ first: 7, last: 7 }},
                    records: [{{ id: 7, event: 'stderr', data: {{ chunk: rawStderr, kind: 'stderr' }} }}]
                  }}
                ]
              }}
            }});
            const model = trace.frameWorkTraceModel([], {{
              executionCells: {{
                run_id: 'run_1',
                items: [
                  {{
                    id: 'run_1:stderr:7',
                    kind: 'stderr',
                    title: 'STDERR',
                    status: 'completed',
                    summary: rawStderr,
                    event_ids: [7],
                    event_range: {{ first: 7, last: 7 }},
                    records: [{{ id: 7, event: 'stderr', data: {{ chunk: rawStderr, kind: 'stderr' }} }}]
                  }}
                ]
              }}
            }});
            function visibleText(node) {{
              return [node.textContent || '', ...node.children.map((child) => visibleText(child))]
                .filter(Boolean)
                .join(' ')
                .replace(/\\s+/g, ' ')
                .trim();
            }}
            process.stdout.write(JSON.stringify({{
              visibleText: visibleText(container),
              total: model.total
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["total"], 0)
        self.assertIn("No work yet", result["visibleText"])
        self.assertNotIn("Host-agent diagnostic output recorded.", result["visibleText"])
        self.assertNotIn("Traceback", result["visibleText"])
        self.assertNotIn("/Users/matthewzmd/private", result["visibleText"])

    def test_frame_trace_links_artifact_execution_cell_to_artifact_and_chat(self) -> None:
        trace_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_frame_trace.js").as_uri()
        script = _dom_shim_script() + textwrap.dedent(
            f"""
            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            globalThis.window = {{ location: {{ href: 'http://127.0.0.1:8767/projects/proj_1' }} }};
            const trace = await import({trace_url!r});
            const container = document.createElement('div');
            trace.renderFrameWorkTrace(container, [], {{
              baseUrl: window.location.href,
              highlightStepId: 'run_1:artifact:9',
              executionCells: {{
                run_id: 'run_1',
                items: [
                  {{
                    id: 'run_1:artifact:9',
                    kind: 'artifact',
                    title: 'APOE evidence report',
                    status: 'completed',
                    summary: 'APOE evidence report',
                    project_id: 'proj_1',
                    frame_id: 'frame_1',
                    event_ids: [9],
                    event_range: {{ first: 9, last: 9 }},
                    artifact: {{
                      id: 'art_1',
                      project_id: 'proj_1',
                      title: 'APOE evidence report',
                      latest_version_id: 'ver_1',
                      workspace_route: '/projects/proj_1/artifacts/art_1/versions/ver_1'
                    }},
                    records: []
                  }}
                ]
              }}
            }});
            function visibleText(node) {{
              return [node.textContent || '', ...node.children.map((child) => visibleText(child))]
                .filter(Boolean)
                .join(' ')
                .replace(/\\s+/g, ' ')
                .trim();
            }}
            const step = container.querySelector('[data-testid="frame-trace-step"]');
            const artifactLink = step.querySelector('[data-testid="genomi-work-step-open-artifact"]');
            const chatLink = step.querySelector('[data-testid="genomi-work-step-view-chat"]');
            process.stdout.write(JSON.stringify({{
              visibleText: visibleText(step),
              artifactLabel: artifactLink ? visibleText(artifactLink) : '',
              artifactHref: artifactLink ? artifactLink.href : '',
              chatLabel: chatLink ? visibleText(chatLink) : '',
              chatHref: chatLink ? chatLink.href : '',
              workStepId: step.dataset.workStepId,
              highlighted: step.getAttribute('data-highlighted-step'),
              className: step.className
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertIn("APOE evidence report", result["visibleText"])
        self.assertEqual(result["artifactLabel"], "Open artifact")
        self.assertEqual(
            result["artifactHref"],
            "http://127.0.0.1:8767/projects/proj_1/artifacts/art_1/versions/ver_1",
        )
        self.assertEqual(result["chatLabel"], "View in chat")
        self.assertEqual(
            result["chatHref"],
            "http://127.0.0.1:8767/projects/proj_1/frames/frame_1?highlight_run=run_1&highlight_step=run_1%3Aartifact%3A9",
        )
        self.assertEqual(result["workStepId"], "run_1:artifact:9")
        self.assertEqual(result["highlighted"], "true")
        self.assertIn("highlighted", result["className"])

    def test_frame_trace_step_hides_context_packet_actions(self) -> None:
        trace_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_frame_trace.js").as_uri()
        script = _dom_shim_script() + textwrap.dedent(
            f"""
            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            const trace = await import({trace_url!r});
            const container = document.createElement('div');
            trace.renderFrameWorkTrace(container, [
              {{
                id: 'msg_call',
                role: 'tool',
                frame_id: 'frame_1',
                run_id: 'run_1',
                event: {{
                  type: 'tool_call',
                  id: 'call_1',
                  name: 'variant.resolve',
                  input: {{ rsid: 'rs429358' }}
                }}
              }},
              {{
                id: 'msg_result',
                role: 'tool',
                frame_id: 'frame_1',
                run_id: 'run_1',
                event: {{
                  type: 'tool_result',
                  id: 'call_1',
                  name: 'variant.resolve',
                  content: 'variant.resolve: data_returned',
                  ledger: {{ status: 'completed', summary: 'Public variant evidence returned.' }}
                }}
              }}
            ], {{
              onUseContext: () => undefined,
              onAskContext: () => undefined,
              onAskNewContext: () => undefined,
              onDraftContext: () => undefined
            }});
            process.stdout.write(JSON.stringify({{
              useStep: Boolean(container.querySelector('[data-testid="genomi-work-step-use"]')),
              askStep: Boolean(container.querySelector('[data-testid="genomi-work-step-ask"]')),
              askNewStep: Boolean(container.querySelector('[data-testid="genomi-work-step-ask-new"]')),
              draftStep: Boolean(container.querySelector('[data-testid="genomi-work-step-draft"]')),
              visibleText: container.textContent
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertFalse(result["useStep"])
        self.assertFalse(result["askStep"])
        self.assertFalse(result["askNewStep"])
        self.assertFalse(result["draftStep"])
        self.assertNotIn("Use this step", result["visibleText"])
        self.assertNotIn("Ask about step", result["visibleText"])
        self.assertNotIn("Ask in new conversation", result["visibleText"])

    def test_frame_trace_summary_hides_context_packet_actions(self) -> None:
        trace_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_frame_trace.js").as_uri()
        script = _dom_shim_script() + textwrap.dedent(
            f"""
            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            const trace = await import({trace_url!r});
            const container = document.createElement('div');
            trace.renderFrameWorkTrace(container, [
              {{
                id: 'msg_call',
                role: 'tool',
                frame_id: 'frame_1',
                run_id: 'run_1',
                event: {{
                  type: 'tool_call',
                  id: 'call_1',
                  name: 'variant.resolve',
                  input: {{ rsid: 'rs429358' }}
                }}
              }},
              {{
                id: 'msg_result',
                role: 'tool',
                frame_id: 'frame_1',
                run_id: 'run_1',
                event: {{
                  type: 'tool_result',
                  id: 'call_1',
                  name: 'variant.resolve',
                  content: 'variant.resolve: data_returned',
                  ledger: {{ status: 'completed', summary: 'Public variant evidence returned.' }}
                }}
              }}
            ], {{
              onUseContext: () => undefined,
              onAskNewContext: () => undefined
            }});
            process.stdout.write(JSON.stringify({{
              useTrail: Boolean(container.querySelector('[data-testid="genomi-work-trail-use"]')),
              askNewTrail: Boolean(container.querySelector('[data-testid="genomi-work-trail-ask-new"]')),
              visibleText: container.textContent
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertFalse(result["useTrail"])
        self.assertFalse(result["askNewTrail"])
        self.assertNotIn("Use work trail", result["visibleText"])
        self.assertNotIn("Ask in new conversation", result["visibleText"])

    def test_frame_trace_default_badges_hide_event_mechanics(self) -> None:
        trace_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_frame_trace.js").as_uri()
        script = _dom_shim_script() + textwrap.dedent(
            f"""
            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            const trace = await import({trace_url!r});
            const container = document.createElement('div');
            trace.renderFrameWorkTrace(container, [], {{
              executionCells: {{
                run_id: 'run_1',
                items: [
                  {{
                    id: 'run_1:run:5',
                    kind: 'run',
                    status: 'succeeded',
                    event_ids: [5],
                    event_range: {{ first: 5, last: 5 }},
                    records: [{{ id: 5, event: 'end', data: {{ status: 'succeeded' }} }}]
                  }}
                ]
              }}
            }});
            function nodeText(node) {{
              return [node.textContent || '', ...node.children.map((child) => nodeText(child))]
                .filter(Boolean)
                .join(' ')
                .replace(/\\s+/g, ' ')
                .trim();
            }}
            const badgeText = container.querySelector('.frame-trace-badges').children.map((node) => node.textContent).join(' ');
            const technicalText = nodeText(container.querySelector('.frame-trace-technical-details'));
            process.stdout.write(JSON.stringify({{ badgeText, technicalText }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertIn("Assistant update", result["badgeText"])
        self.assertNotIn("event", result["badgeText"].lower())
        self.assertNotIn("Run state", result["badgeText"])
        self.assertIn("Event range", result["technicalText"])

    def test_frame_trace_pairs_result_without_name_by_tool_id(self) -> None:
        trace_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_frame_trace.js").as_uri()
        script = textwrap.dedent(
            f"""
            const trace = await import({trace_url!r});
            const model = trace.frameWorkTraceModel([
              {{
                id: 'msg_call',
                role: 'tool',
                frame_id: 'frame_1',
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
                frame_id: 'frame_1',
                run_id: 'run_1',
                event: {{
                  type: 'tool_result',
                  id: 'tool_1',
                  content: 'data_returned',
                  ledger: {{ status: 'completed' }}
                }}
              }}
            ]);
            process.stdout.write(JSON.stringify({{
              total: model.total,
              counts: model.counts,
              step: model.steps[0]
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["counts"]["running"], 0)
        self.assertEqual(result["step"]["operation"], "variant.resolve")
        self.assertEqual(result["step"]["status"], "completed")
        self.assertEqual(result["step"]["messageIds"], ["msg_call", "msg_result"])

    def test_live_record_bridge_preserves_call_operation_when_result_has_no_name(self) -> None:
        trace_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_frame_trace.js").as_uri()
        script = textwrap.dedent(
            f"""
            const trace = await import({trace_url!r});
            const record = {{
              scope: {{ frameId: 'frame_live', runId: 'run_live', messageId: 'msg_live' }},
              call: {{
                type: 'tool_call',
                id: 'tool_live',
                name: 'variant.resolve',
                input: {{ rsid: 'rs429358' }}
              }},
              result: {{
                id: 'tool_live',
                content: 'data_returned',
                ledger: {{ status: 'completed', summary: 'variant.resolve returned public evidence' }}
              }}
            }};
            const messages = trace.frameTraceMessagesFromToolRecord(record);
            const model = trace.frameWorkTraceModel(messages);
            process.stdout.write(JSON.stringify({{
              recordKey: trace.frameTraceRecordKey(record),
              messageCount: messages.length,
              total: model.total,
              step: model.steps[0]
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["recordKey"], "frame_live:run_live:tool:tool_live")
        self.assertEqual(result["messageCount"], 2)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["step"]["operation"], "variant.resolve")
        self.assertEqual(result["step"]["status"], "completed")
        self.assertEqual(result["step"]["record"]["call"]["input"], {"rsid": "rs429358"})


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
