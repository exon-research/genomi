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


class PortalFrontendResultPresentationTest(unittest.TestCase):
    def test_frontend_prefers_server_result_presentation(self) -> None:
        renderers_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_result_renderers.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const renderers = await import({renderers_url!r});
            const record = {{
              call: {{ id: 'call_1', name: 'variant.resolve' }},
              result: {{
                id: 'result_1',
                name: 'variant.resolve',
                payload: {{
                  query: {{ rsid: 'rs429358' }},
                  resolved_targets: [{{ rsid: 'rs429358' }}],
                  evidence_envelope: {{
                    operation: 'variant.resolve',
                    headline: 'Browser fallback should not win',
                    answer_readiness: 'answer_supported',
                    finding_state: 'data_returned'
                  }}
                }},
                portal_presentation: {{
                  schema: 'genomi_portal_result_presentation',
                  source: 'server',
                  operation: 'variant.resolve',
                  kind: 'variant',
                  kicker: 'Server-owned variant view',
                  title: 'rs429358 server title',
                  summary: 'Server-owned summary',
                  evidenceEnvelope: {{
                    answer_readiness: 'answer_supported',
                    finding_state: 'data_returned'
                  }},
                  metrics: [{{ label: 'Resolved', value: 9 }}],
                  lanes: [{{
                    title: 'Server lane',
                    nodes: [{{
                      label: 'Server node',
                      summary: 'server node summary',
                      context: 'Server lane / Server node: server node summary',
                      value: {{ rsid: 'rs429358', note: 'server-owned' }}
                    }}]
                  }}]
                }}
              }}
            }};
            const model = renderers.genomiResultViewModel(record);
            const selected = renderers.genomiResultContextPayload(record, null, {{ resultModel: model }});
            process.stdout.write(JSON.stringify({{
              model,
              selected,
              search: renderers.resultSearchModel(model, 'server-owned')
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["model"]["kicker"], "Server-owned variant view")
        self.assertEqual(result["model"]["title"], "rs429358 server title")
        self.assertEqual(result["model"]["metrics"], [{"label": "Resolved", "value": 9}])
        self.assertEqual(result["model"]["lanes"][0]["title"], "Server lane")
        self.assertEqual(result["model"]["lanes"][0]["nodes"][0]["label"], "Server node")
        self.assertEqual(result["search"]["matchingNodes"], 1)
        self.assertIn("Server node", result["selected"]["prompt_text"])
        self.assertNotIn("Browser fallback should not win", json.dumps(result))
        self.assertIsNone(_PRIVATE_PROMPT_RE.search(json.dumps(result)))

    def test_tool_result_summary_prefers_server_presentation_over_raw_payload_headline(self) -> None:
        presentation_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_tool_result_presentation.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const presentation = await import({presentation_url!r});
            const result = {{
              content: 'Target evidence report for rs429358',
              ledger: {{ summary: 'Target evidence report for rs429358' }},
              payload: {{
                headline: 'research.build_target_packet: evidence_present',
                evidence_envelope: {{
                  operation: 'research.build_target_packet',
                  headline: 'research.build_target_packet: evidence_present'
                }}
              }},
              portal_presentation: {{
                schema: 'genomi_portal_result_presentation',
                source: 'server',
                operation: 'research.build_target_packet',
                kind: 'target_packet',
                kicker: 'Target evidence report',
                title: 'rs429358',
                summary: 'Target-centric evidence report for focused Genomi research.',
                lanes: []
              }}
            }};
            process.stdout.write(JSON.stringify({{
              summary: presentation.toolResultSummary(result)
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["summary"], "Target-centric evidence report for focused Genomi research.")
        self.assertNotIn("research.build_target_packet", result["summary"])

    def test_serialized_payloads_never_become_a_work_step_summary(self) -> None:
        # These are verbatim summaries the work trail showed a reader: a
        # numbered file listing, a leading line number before JSON, and an MCP
        # content envelope. A step's one line says what happened; the payload
        # belongs in the expanded technical detail.
        presentation_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_tool_result_presentation.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const presentation = await import({presentation_url!r});
            const blobs = [
              '1590- 1 1591- ] 1592- ], 1593- "population_flags": [ 1594- "needs_public_population_evidence"',
              '1 {{ 2 "headline": "clinvar.scan_candidates: evidence_present", 3 "evidence_envelope"',
              '[{{"text":"{{\\n \\"dispatched_tool\\": \\"lab.create_investigation\\"}}"}}]'
            ];
            const readable = [
              'No matches found',
              'CTLA4 literature reviewed across four cohorts.'
            ];
            process.stdout.write(JSON.stringify({{
              blobs: blobs.map((content) => presentation.toolResultSummary({{ content }})),
              readable: readable.map((content) => presentation.toolResultSummary({{ content }}))
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["blobs"], ["completed", "completed", "completed"])
        self.assertEqual(
            result["readable"],
            ["No matches found", "CTLA4 literature reviewed across four cohorts."],
        )

    def test_source_operation_contract_is_shared_by_result_renderers_and_tool_presentation(self) -> None:
        helper_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_result_presentation_model.js"
        ).as_uri()
        presentation_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_tool_result_presentation.js"
        ).as_uri()
        renderers_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_result_renderers.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const helper = await import({helper_url!r});
            const presentation = await import({presentation_url!r});
            const renderers = await import({renderers_url!r});
            const record = {{
              call: {{ id: 'call_invoke', name: 'genomi.invoke' }},
              result: {{
                id: 'result_target',
                payload: {{
                  target: {{ target_type: 'topic', topic: 'rs429358' }},
                  evidence_envelope: {{ operation: 'research.build_target_packet' }}
                }},
                portal_presentation: {{
                  schema: 'genomi_portal_result_presentation',
                  source: 'server',
                  operation: 'research.build_target_packet',
                  kind: 'target_packet',
                  kicker: 'Target evidence report',
                  title: 'rs429358',
                  summary: 'Server-owned target evidence report.',
                  lanes: [{{
                    title: 'Target',
                    nodes: [{{
                      label: 'rs429358',
                      summary: 'topic',
                      value: {{ target_type: 'topic', topic: 'rs429358' }}
                    }}]
                  }}]
                }}
              }}
            }};
            const model = renderers.genomiResultViewModel(record);
            process.stdout.write(JSON.stringify({{
              helperOperation: helper.sourceOperation(record),
              presentationOperation: presentation.sourceOperation(record),
              modelOperation: model.operation,
              modelTitle: model.title
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["helperOperation"], "research.build_target_packet")
        self.assertEqual(result["presentationOperation"], "research.build_target_packet")
        self.assertEqual(result["modelOperation"], "research.build_target_packet")
        self.assertEqual(result["modelTitle"], "rs429358")

    def test_frontend_prefers_server_pgx_result_presentation(self) -> None:
        renderers_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_result_renderers.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const renderers = await import({renderers_url!r});
            const record = {{
              call: {{ id: 'call_pgx', name: 'pharmacogenomics.review_medication' }},
              result: {{
                id: 'result_pgx',
                name: 'pharmacogenomics.review_medication',
                payload: {{
                  headline: 'Browser PGx fallback should not win',
                  query: {{ drug: 'clopidogrel' }},
                  medication_review_matrix: {{ rows: [{{ drug: 'clopidogrel', gene: 'CYP2C19' }}] }},
                  evidence_matrix: {{ item_count: 1 }},
                  evidence_envelope: {{
                    operation: 'pharmacogenomics.review_medication',
                    headline: 'Browser PGx fallback should not win',
                    answer_readiness: 'scoped_answer_only',
                    finding_state: 'data_returned'
                  }}
                }},
                portal_presentation: {{
                  schema: 'genomi_portal_result_presentation',
                  source: 'server',
                  operation: 'pharmacogenomics.review_medication',
                  kind: 'pgx',
                  kicker: 'Server-owned medication matrix',
                  title: 'clopidogrel / CYP2C19 server title',
                  summary: 'Server-owned PGx summary',
                  evidenceEnvelope: {{
                    answer_readiness: 'scoped_answer_only',
                    finding_state: 'data_returned'
                  }},
                  metrics: [{{ label: 'Rows', value: 7 }}],
                  lanes: [{{
                    title: 'Server medication lane',
                    nodes: [{{
                      label: 'Server PGx row',
                      summary: 'server PGx row summary',
                      context: 'Server medication lane / Server PGx row: server PGx row summary',
                      value: {{ drug: 'clopidogrel', gene: 'CYP2C19' }}
                    }}]
                  }}]
                }}
              }}
            }};
            const model = renderers.genomiResultViewModel(record);
            const selected = renderers.genomiResultContextPayload(record, null, {{ resultModel: model }});
            process.stdout.write(JSON.stringify({{ model, selected }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["model"]["kicker"], "Server-owned medication matrix")
        self.assertEqual(result["model"]["title"], "clopidogrel / CYP2C19 server title")
        self.assertEqual(result["model"]["metrics"], [{"label": "Rows", "value": 7}])
        self.assertEqual(result["model"]["lanes"][0]["title"], "Server medication lane")
        self.assertIn("Server PGx row", result["selected"]["prompt_text"])
        self.assertNotIn("Browser PGx fallback should not win", json.dumps(result))
        self.assertIsNone(_PRIVATE_PROMPT_RE.search(json.dumps(result)))

    def test_frontend_prefers_server_candidate_evidence_presentation(self) -> None:
        renderers_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_result_renderers.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const renderers = await import({renderers_url!r});
            const record = {{
              call: {{ id: 'call_gwas', name: 'gwas.compare_variant_associations' }},
              result: {{
                id: 'result_gwas',
                name: 'gwas.compare_variant_associations',
                payload: {{
                  headline: 'Browser candidate fallback should not win',
                  query: {{ phenotype: 'LDL cholesterol', variants: ['rs111', 'rs222'] }},
                  evidence_view: {{
                    candidate_matrix: [{{ candidate_id: 'browser_fallback_candidate' }}]
                  }},
                  evidence_envelope: {{
                    operation: 'gwas.compare_variant_associations',
                    headline: 'Browser candidate fallback should not win',
                    answer_readiness: 'scoped_answer_only',
                    finding_state: 'data_returned'
                  }}
                }},
                portal_presentation: {{
                  schema: 'genomi_portal_result_presentation',
                  source: 'server',
                  operation: 'gwas.compare_variant_associations',
                  kind: 'candidate_evidence',
                  kicker: 'Server-owned candidate evidence',
                  title: 'LDL cholesterol / rs111 / rs222',
                  summary: 'Server-owned candidate summary',
                  evidenceEnvelope: {{
                    answer_readiness: 'scoped_answer_only',
                    finding_state: 'data_returned'
                  }},
                  metrics: [{{ label: 'Candidates', value: 2 }}],
                  lanes: [{{
                    title: 'Candidate comparison',
                    nodes: [{{
                      label: '#1 rs111',
                      summary: 'support high',
                      context: 'Candidate comparison / #1 rs111: support high',
                      value: {{ candidate_id: 'rs111' }}
                    }}]
                  }}, {{
                    title: 'Coverage and limits',
                    selectable: false,
                    nodes: [{{
                      label: 'Coverage: Consulted libraries',
                      summary: 'GWAS Catalog',
                      context: 'Coverage and limits / Coverage: Consulted libraries: GWAS Catalog',
                      value: {{ consulted_libraries: ['GWAS Catalog'] }},
                      selectable: false
                    }}]
                  }}]
                }}
              }}
            }};
            const model = renderers.genomiResultViewModel(record);
            const selected = renderers.genomiResultContextPayload(record, null, {{ resultModel: model }});
            process.stdout.write(JSON.stringify({{
              model,
              selected,
              search: renderers.resultSearchModel(model, 'rs111')
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["model"]["kicker"], "Server-owned candidate evidence")
        self.assertEqual(result["model"]["title"], "LDL cholesterol / rs111 / rs222")
        self.assertEqual(result["model"]["metrics"], [{"label": "Candidates", "value": 2}])
        self.assertEqual(result["model"]["lanes"][0]["title"], "Candidate comparison")
        self.assertFalse(result["model"]["lanes"][1]["selectable"])
        self.assertEqual(result["search"]["matchingNodes"], 1)
        self.assertIn("#1 rs111", result["selected"]["prompt_text"])
        self.assertNotIn("browser_fallback_candidate", json.dumps(result))
        self.assertNotIn("Browser candidate fallback should not win", json.dumps(result))
        self.assertIsNone(_PRIVATE_PROMPT_RE.search(json.dumps(result)))

    def test_candidate_payload_without_server_presentation_has_no_candidate_fallback_lanes(self) -> None:
        renderers_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_result_renderers.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const renderers = await import({renderers_url!r});
            const record = {{
              call: {{ id: 'call_gwas', name: 'gwas.compare_variant_associations' }},
              result: {{
                id: 'result_gwas',
                name: 'gwas.compare_variant_associations',
                payload: {{
                  headline: 'candidate fallback should not render',
                  evidence_view: {{
                    candidate_matrix: [{{ candidate_id: 'browser_fallback_candidate', rank: 1 }}]
                  }},
                  evidence_envelope: {{
                    operation: 'gwas.compare_variant_associations',
                    headline: 'candidate fallback should not render',
                    answer_readiness: 'scoped_answer_only',
                    finding_state: 'data_returned'
                  }}
                }}
              }}
            }};
            const model = renderers.genomiResultViewModel(record);
            process.stdout.write(JSON.stringify({{
              model,
              registered: renderers.registeredGenomiResultRendererOperations()
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertIsNone(result["model"])
        self.assertNotIn("gwas.compare_variant_associations", result["registered"])

    def test_no_selection_follow_up_prefers_server_result_lanes(self) -> None:
        presentation_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_tool_result_presentation.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const presentation = await import({presentation_url!r});
            const record = {{
              call: {{ id: 'call_1', name: 'variant.resolve' }},
              result: {{
                id: 'result_1',
                name: 'variant.resolve',
                payload: {{
                  evidence_envelope: {{
                    operation: 'variant.resolve',
                    headline: 'Generic envelope text should not win',
                    answer_readiness: 'answer_supported',
                    finding_state: 'data_returned'
                  }}
                }},
                portal_presentation: {{
                  schema: 'genomi_portal_result_presentation',
                  source: 'server',
                  operation: 'variant.resolve',
                  kind: 'variant',
                  kicker: 'Server-owned variant view',
                  title: 'rs429358 server title',
                  summary: 'Server-owned result summary',
                  evidenceEnvelope: {{
                    answer_readiness: 'answer_supported',
                    finding_state: 'data_returned'
                  }},
                  lanes: [{{
                    title: 'Server lane',
                    nodes: [{{
                      label: 'Server node',
                      summary: 'server node summary',
                      context: 'Server lane / Server node: server node summary',
                      value: {{ rsid: 'rs429358', note: 'server-owned' }}
                    }}]
                  }}]
                }}
              }}
            }};
            const followUp = presentation.toolResultFollowUpRequest(record);
            process.stdout.write(JSON.stringify(followUp));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["selectedEvidence"][0]["context_kind"], "result_nodes")
        self.assertIn("Server node", result["selectedEvidence"][0]["prompt_text"])
        self.assertNotIn("Generic envelope text should not win", json.dumps(result))

    def test_malformed_server_presentation_drops_bad_lanes_and_nodes(self) -> None:
        renderers_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_result_renderers.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const renderers = await import({renderers_url!r});
            const record = {{
              call: {{ id: 'call_1', name: 'variant.resolve' }},
              result: {{
                id: 'result_1',
                name: 'variant.resolve',
                payload: {{ status: 'completed' }},
                portal_presentation: {{
                  schema: 'genomi_portal_result_presentation',
                  source: 'server',
                  operation: 'variant.resolve',
                  kind: 'variant',
                  kicker: 'Server-owned variant view',
                  title: 'rs429358 server title',
                  summary: 'Server-owned summary',
                  lanes: [
                    {{
                      nodes: [{{
                        label: 'Node under missing lane title',
                        summary: 'should be dropped',
                        value: {{ raw: 'missing lane title raw value' }}
                      }}]
                    }},
                    {{
                      title: 'Server lane',
                      nodes: [
                        {{
                          label: 'Valid server node',
                          summary: 'valid summary',
                          context: 'Server lane / Valid server node: valid summary',
                          value: {{ ok: true }}
                        }},
                        {{
                          summary: 'missing label should be dropped',
                          value: {{ raw: 'missing label raw value' }}
                        }},
                        {{
                          label: 'Missing summary should be dropped',
                          value: {{ raw: 'missing summary raw value' }}
                        }}
                      ]
                    }}
                  ]
                }}
              }}
            }};
            const model = renderers.genomiResultViewModel(record);
            process.stdout.write(JSON.stringify(model));
            """
        )

        result = _run_node_json(self, script)
        serialized = json.dumps(result)

        self.assertEqual([lane["title"] for lane in result["lanes"]], ["Server lane"])
        self.assertEqual([node["label"] for node in result["lanes"][0]["nodes"]], ["Valid server node"])
        self.assertNotIn("Result lane", serialized)
        self.assertNotIn("Evidence item", serialized)
        self.assertNotIn("missing lane title raw value", serialized)
        self.assertNotIn("missing label raw value", serialized)
        self.assertNotIn("missing summary raw value", serialized)

    def test_result_toolbar_selects_filtered_visible_evidence(self) -> None:
        renderers_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_result_renderers.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const renderers = await import(__RENDERERS_URL__);
            __DOM_SHIM__

            let used = null;
            let askedNew = null;
            const record = {
              call: { id: 'call_variant', name: 'variant.resolve' },
              result: {
                id: 'result_variant',
                name: 'variant.resolve',
                payload: { status: 'ok' },
                portal_presentation: {
                  schema: 'genomi_portal_result_presentation',
                  operation: 'variant.resolve',
                  kicker: 'Variant evidence',
                  title: 'rs429358 evidence',
                  summary: 'Selectable evidence lanes',
                  lanes: [
                    {
                      title: 'ClinVar records',
                      nodes: [
                        {
                          label: 'ClinVar APOE',
                          summary: 'risk factor',
                          context: 'ClinVar records / ClinVar APOE: risk factor',
                          value: { source: 'ClinVar', gene: 'APOE' }
                        },
                        {
                          label: 'ClinVar APOB',
                          summary: 'benign',
                          context: 'ClinVar records / ClinVar APOB: benign',
                          value: { source: 'ClinVar', gene: 'APOB' }
                        }
                      ]
                    },
                    {
                      title: 'GWAS catalog',
                      nodes: [
                        {
                          label: 'GCST000001',
                          summary: 'LDL association',
                          context: 'GWAS catalog / GCST000001: LDL association',
                          value: { source: 'GWAS', study: 'GCST000001' }
                        }
                      ]
                    },
                    {
                      title: 'Coverage and limits',
                      selectable: false,
                      nodes: [
                        {
                          label: 'Coverage',
                          summary: 'public sources only',
                          context: 'Coverage and limits / Coverage: public sources only',
                          value: { scope: 'public' }
                        }
                      ]
                    }
                  ]
                }
              }
            };
            const panel = renderers.renderGenomiResultPanel(record, {
              onUseContext: (context) => { used = context; },
              onAskNewContext: (context) => { askedNew = context; }
            });
            const toolbar = panel.querySelector('.genomi-result-toolbar');
            const search = panel.querySelector('[data-testid="genomi-result-search"]');
            const selectShown = panel.querySelector('[data-toolbar-action="select-shown"]');
            const clearSelected = panel.querySelector('[data-toolbar-action="clear-selected"]');
            const useButton = panel.querySelector('[data-action="use"]');
            const askNewButton = panel.querySelector('[data-testid="genomi-result-ask-new-selected"]');
            const initial = {
              summary: toolbar.querySelector('strong').textContent,
              visibleSelectable: toolbar.dataset.visibleSelectableCount,
              selected: toolbar.dataset.selectedCount,
              selectShownDisabled: selectShown.disabled,
              clearSelectedDisabled: clearSelected.disabled,
              useLabel: useButton.textContent,
              askNewLabel: askNewButton.textContent
            };
            search.value = 'clinvar';
            search.dispatchEvent({ type: 'input' });
            const afterSearch = {
              summary: toolbar.querySelector('strong').textContent,
              visibleSelectable: toolbar.dataset.visibleSelectableCount,
              selected: toolbar.dataset.selectedCount,
              visibleLabels: [...panel.querySelectorAll('.result-node')]
                .filter((node) => node.dataset.selectable === 'true' && !node.hidden)
                .map((node) => node.dataset.label)
            };
            selectShown.click();
            const afterSelect = {
              selected: toolbar.dataset.selectedCount,
              clearSelectedDisabled: clearSelected.disabled,
              useLabel: useButton.textContent,
              selectedLabels: [...panel.querySelectorAll('.result-node')]
                .filter((node) => node.classList.contains('selected'))
                .map((node) => node.dataset.label),
              inspectorText: panel.querySelector('.genomi-result-inspector').textContent
            };
            askNewButton.click();
            useButton.click();
            clearSelected.click();
            const afterClear = {
              selected: toolbar.dataset.selectedCount,
              clearSelectedDisabled: clearSelected.disabled,
              useLabel: useButton.textContent,
              inspectorHidden: panel.querySelector('.genomi-result-inspector').hidden
            };
            process.stdout.write(JSON.stringify({ initial, afterSearch, afterSelect, afterClear, used, askedNew }));
            """
        ).replace("__RENDERERS_URL__", json.dumps(renderers_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["initial"]["summary"], "4 items")
        self.assertEqual(result["initial"]["visibleSelectable"], "3")
        self.assertEqual(result["initial"]["selected"], "0")
        self.assertFalse(result["initial"]["selectShownDisabled"])
        self.assertTrue(result["initial"]["clearSelectedDisabled"])
        self.assertEqual(result["initial"]["useLabel"], "Use view")
        self.assertEqual(result["initial"]["askNewLabel"], "Ask in new conversation")
        self.assertEqual(result["afterSearch"]["summary"], "2 of 4 shown")
        self.assertEqual(result["afterSearch"]["visibleSelectable"], "2")
        self.assertEqual(result["afterSearch"]["selected"], "0")
        self.assertEqual(result["afterSearch"]["visibleLabels"], ["ClinVar APOE", "ClinVar APOB"])
        self.assertEqual(result["afterSelect"]["selected"], "2")
        self.assertFalse(result["afterSelect"]["clearSelectedDisabled"])
        self.assertEqual(result["afterSelect"]["useLabel"], "Use selected result")
        self.assertEqual(result["afterSelect"]["selectedLabels"], ["ClinVar APOE", "ClinVar APOB"])
        self.assertIn("ClinVar APOE", result["afterSelect"]["inspectorText"])
        self.assertEqual(len(result["used"]["selected_nodes"]), 2)
        self.assertIn("ClinVar APOE", result["used"]["prompt_text"])
        self.assertIn("ClinVar APOB", result["used"]["prompt_text"])
        self.assertNotIn("GCST000001", result["used"]["prompt_text"])
        self.assertEqual(len(result["askedNew"]["selected_nodes"]), 2)
        self.assertIn("ClinVar APOE", result["askedNew"]["prompt_text"])
        self.assertIn("ClinVar APOB", result["askedNew"]["prompt_text"])
        self.assertNotIn("GCST000001", result["askedNew"]["prompt_text"])
        self.assertEqual(result["afterClear"]["selected"], "0")
        self.assertTrue(result["afterClear"]["clearSelectedDisabled"])
        self.assertEqual(result["afterClear"]["useLabel"], "Use view")
        self.assertTrue(result["afterClear"]["inspectorHidden"])
        self.assertIsNone(_PRIVATE_PROMPT_RE.search(json.dumps(result)))

    def test_evidence_panel_can_start_new_conversation_from_selected_node(self) -> None:
        evidence_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_evidence_panel.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const evidence = await import(__EVIDENCE_URL__);
            __DOM_SHIM__

            let askedNew = null;
            const record = {
              call: { id: 'call_1', name: 'variant.resolve' },
              result: {
                id: 'result_1',
                name: 'variant.resolve',
                payload: {
                  status: 'completed',
                  evidence_envelope: {
                    headline: 'rs429358 public evidence',
                    answer_readiness: 'answer_supported',
                    finding_state: 'data_returned',
                    coverage: { libraries: ['ClinVar', 'dbSNP'] },
                    observations: { variant: 'rs429358', gene: 'APOE' },
                    next_actions: ['Review active genome only after approval']
                  }
                }
              }
            };
            const panel = evidence.renderEvidencePanel(record, {
              onAskNewContext: (context) => { askedNew = context; }
            });
            const node = panel.querySelector('.evidence-node');
            const askNew = panel.querySelector('[data-testid="genomi-evidence-ask-new-selected"]');
            node.click();
            askNew.click();
            process.stdout.write(JSON.stringify({
              buttonText: askNew.textContent,
              selectedLabel: askedNew.selected_nodes[0].label,
              prompt: askedNew.prompt_text,
              sourceOperation: askedNew.source_operation
            }));
            """
        ).replace("__EVIDENCE_URL__", json.dumps(evidence_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["buttonText"], "Ask in new conversation")
        self.assertEqual(result["sourceOperation"], "variant.resolve")
        self.assertEqual(result["selectedLabel"], "Libraries")
        self.assertIn("ClinVar", result["prompt"])
        self.assertNotIn("Review active genome only after approval", result["prompt"])
        self.assertIsNone(_PRIVATE_PROMPT_RE.search(json.dumps(result)))


def _run_node_json(testcase: unittest.TestCase, script: str) -> dict:
    node = shutil.which("node")
    if node is None:
        testcase.skipTest("node is not installed")
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return json.loads(completed.stdout)


def _dom_shim_script() -> str:
    return textwrap.dedent(
        """
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
            this._textContent = '';
            this.hidden = false;
            this.disabled = false;
            this.value = '';
            this.placeholder = '';
            this.classList = new ClassList(this);
          }
          set textContent(value) { this._textContent = String(value || ''); }
          get textContent() { return this._textContent + this.children.map((child) => child.textContent).join(''); }
          appendChild(child) {
            child.parentNode = this;
            this.children.push(child);
            return child;
          }
          insertBefore(child, before) {
            child.parentNode = this;
            const index = this.children.indexOf(before);
            if (index < 0) this.children.push(child);
            else this.children.splice(index, 0, child);
            return child;
          }
          remove() {
            if (!this.parentNode) return;
            this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
            this.parentNode = null;
          }
          setAttribute(name, value) {
            const text = String(value);
            this.attributes[name] = text;
            if (name === 'class') this.className = text;
            if (name === 'id') this.id = text;
            if (name === 'placeholder') this.placeholder = text;
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
          dispatchEvent(event) {
            (this.eventListeners[event.type] || []).forEach((handler) => handler({
              ...event,
              preventDefault() {},
              stopPropagation() {}
            }));
          }
          click() { this.dispatchEvent({ type: 'click' }); }
          focus() {}
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
            this._textContent = '';
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
          const alternatives = String(selector || '').split(',').map((item) => item.trim()).filter(Boolean);
          if (alternatives.length > 1) return [...new Set(alternatives.flatMap((item) => querySelectorAll(root, item)))];
          const parts = alternatives[0] ? alternatives[0].split(/\\s+/).filter(Boolean) : [];
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
          const attrs = [...String(selector || '').matchAll(/\\[([^=\\]]+)(?:="([^"]*)")?\\]/g)];
          const selectorWithoutAttrs = String(selector || '').replace(/\\[[^\\]]+\\]/g, '');
          const pieces = selectorWithoutAttrs.split('.').filter((item, index) => item || index > 0);
          const tag = pieces[0] && !selectorWithoutAttrs.startsWith('.') ? pieces[0] : '';
          const classes = selectorWithoutAttrs.startsWith('.') ? pieces.filter(Boolean) : pieces.slice(1);
          if (tag && tag !== element.tagName) return false;
          if (!classes.every((name) => element.classList.contains(name))) return false;
          return attrs.every((attr) => {
            const value = element.getAttribute(attr[1]);
            return attr[2] === undefined ? value !== null : value === attr[2];
          });
        }

        function parseHtml(html, root) {
          const tokenPattern = /<\\/?[^>]+>|[^<]+/g;
          const stack = [root];
          let match;
          while ((match = tokenPattern.exec(html))) {
            const token = match[0];
            if (!token.startsWith('<')) {
              const text = token.replace(/\\s+/g, ' ').trim();
              if (text) stack[stack.length - 1].textContent += text;
              continue;
            }
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
            if (!/\\/>$/.test(token) && !['br', 'hr', 'img', 'input', 'link', 'meta'].includes(child.tagName)) stack.push(child);
          }
        }

        globalThis.document = { createElement: (tagName) => new Element(tagName) };
        Object.defineProperty(globalThis, 'navigator', {
          value: { clipboard: { writeText() {} } },
          configurable: true
        });
        """
    )


if __name__ == "__main__":
    unittest.main()
