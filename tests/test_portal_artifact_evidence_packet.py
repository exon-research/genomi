from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

from tests.support.runtime.genomi import GenomiRuntimeTestCase

_PRIVATE_PROMPT_RE = re.compile(
    r"(?:context_file|registry_file|agi_path|/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes|~)"
)


class PortalArtifactEvidencePacketTests(GenomiRuntimeTestCase):
    def test_evidence_report_html_normalizes_internal_packet_language(self) -> None:
        from genomi.interfaces import portal_evidence_packet_artifacts

        with self.subTest("legacy purpose copy"):
            payload = {
                "purpose": "Target-centric packet for an agent that has already inferred the user's intent.",
                "target": {"target_id": "topic:rs429358", "topic": "rs429358"},
                "evidence_envelope": {"finding_state": "evidence_present", "answer_readiness": "scoped_answer_only"},
                "source_catalog": {"sources": []},
                "stored_research": {"count": 0},
                "available_operations": [],
                "evidence_options": [],
            }
            path = Path(self.id().replace(".", "_") + ".html")
            try:
                portal_evidence_packet_artifacts.write_evidence_packet_html(path, payload)
                html = path.read_text(encoding="utf-8")
            finally:
                path.unlink(missing_ok=True)

        self.assertIn("Evidence report: rs429358", html)
        self.assertIn("Target-centric evidence report for an agent", html)
        self.assertNotIn("Target-centric packet", html)

    def test_evidence_packet_artifact_summary_includes_server_presentation(self) -> None:
        from genomi.interfaces import portal_evidence_packet_artifacts, portal_store

        project = portal_store.create_project(name="Evidence report")
        payload = {
            "headline": "research.build_target_packet: evidence_present",
            "purpose": "Target-centric evidence report for focused Genomi research.",
            "target": {"target_type": "topic", "topic": "rs429358", "target_id": "topic:rs429358"},
            "source_catalog": {
                "summary": {"source_count": 1},
                "sources": [
                    {
                        "source_id": "gwas_catalog",
                        "title": "GWAS Catalog",
                        "evidence_types": ["trait_association"],
                    }
                ],
            },
            "stored_research": {"count": 0, "records": []},
            "available_operations": [
                {
                    "tool": "research.build_target_packet",
                    "params": {
                        "topic": "rs429358",
                        "shared_evidence_db": "/Users/matthewzmd/private/evidence.sqlite",
                    },
                }
            ],
            "evidence_options": [{"component": "source_scope_selection", "state": "available"}],
            "evidence_envelope": {
                "operation": "research.build_target_packet",
                "headline": "research.build_target_packet: evidence_present",
                "answer_readiness": "scoped_answer_only",
                "finding_state": "evidence_present",
                "coverage": {"source_count": 1},
            },
        }

        artifact = portal_evidence_packet_artifacts.add_evidence_packet_artifact(
            project["project_id"],
            payload,
        )
        public = portal_store.list_project_artifacts(project["project_id"])["artifacts"][0]
        presentation = public["summary"]["portal_presentation"]
        serialized = json.dumps(public["summary"], sort_keys=True)

        self.assertEqual(artifact["kind"], "evidence_packet")
        self.assertEqual(public["summary_lines"], ["Evidence present", "1 source", "0 stored findings"])
        self.assertNotIn("research.build_target_packet", json.dumps(public["summary_lines"]))
        self.assertEqual(presentation["operation"], "research.build_target_packet")
        self.assertEqual(presentation["kind"], "target_packet")
        self.assertEqual(
            [lane["title"] for lane in presentation["lanes"]],
            ["Target", "Source catalog", "Evidence readiness", "Coverage and limits"],
        )
        self.assertEqual(public["summary"]["available_operations"][0]["params"], {"topic": "rs429358"})
        self.assertNotRegex(serialized, _PRIVATE_PROMPT_RE)

    def test_evidence_packet_state_prefers_server_presentation_lanes(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for frontend module tests")
        state_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_artifact_state_adapters.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const stateAdapters = await import({state_url!r});
            const artifact = {{
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              operation: 'research.build_target_packet',
              summary: {{
                headline: 'raw fallback headline',
                target: {{ target_type: 'topic', topic: 'rs429358' }},
                source_catalog: {{
                  summary: {{ source_count: 1 }},
                  sources: [{{ source_id: 'raw', title: 'Raw fallback source' }}]
                }},
                stored_research: {{ count: 0, records: [] }},
                evidence_envelope: {{
                  answer_readiness: 'raw_boundary',
                  finding_state: 'raw_support'
                }}
              }},
              portal_presentation: {{
                schema: 'genomi_portal_result_presentation',
                source: 'server',
                operation: 'research.build_target_packet',
                kind: 'target_packet',
                kicker: 'Target evidence report',
                title: 'rs429358',
                summary: 'Server-owned evidence report state.',
                metrics: [
                  {{ label: 'Sources', value: 9 }},
                  {{ label: 'Server-only metric', value: 'present' }}
                ],
                lanes: [{{
                  title: 'Target',
                  nodes: [{{
                    label: 'rs429358',
                    summary: 'topic',
                    value: {{ target_type: 'topic', topic: 'rs429358' }}
                  }}]
                }}, {{
                  title: 'Source catalog',
                  nodes: [{{
                    label: 'server · Canonical source',
                    summary: 'server lane summary',
                    value: {{ source_id: 'server', title: 'Canonical source' }}
                  }}]
                }}, {{
                  title: 'Evidence readiness',
                  selectable: false,
                  nodes: [{{
                    label: 'Source scope selection',
                    summary: 'Available',
                    value: {{ component: 'source_scope_selection', state: 'available' }}
                  }}]
                }}]
              }}
            }};
            const state = stateAdapters.artifactStateModel(artifact);
            process.stdout.write(JSON.stringify({{
              title: state.title,
              metrics: state.metrics,
              sectionTitles: state.sections.map((section) => section.title),
              sourceLabel: state.sections.find((section) => section.title === 'Source catalog').nodes[0].label,
              readinessValue: state.sections.find((section) => section.title === 'Evidence readiness').nodes[0].value
            }}));
            """
        )

        completed = subprocess.run(
            ["node", "--input-type=module"],
            input=script,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["title"], "Evidence report state")
        self.assertEqual(result["metrics"][0], {"label": "Target", "value": "rs429358"})
        self.assertIn({"label": "Sources", "value": 9}, result["metrics"])
        self.assertIn({"label": "Server-only metric", "value": "present"}, result["metrics"])
        self.assertEqual(result["sectionTitles"], ["Target", "Source catalog", "Evidence readiness"])
        self.assertEqual(result["sourceLabel"], "server · Canonical source")
        self.assertEqual(result["readinessValue"], {"component": "source_scope_selection", "state": "available"})
        self.assertNotIn("Raw fallback source", json.dumps(result))

    def test_evidence_packet_artifact_reuses_target_packet_model_with_neutral_review_brief(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for frontend module tests")
        artifacts_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifacts.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const artifacts = await import({artifacts_url!r});
            const targetOperation = 'research.build_target_packet';
            const evidenceEnvelope = {{
              headline: 'research.build_target_packet: evidence_present',
              finding_state: 'evidence_present',
              answer_readiness: 'scoped_answer_only'
            }};
            const summary = {{
              headline: evidenceEnvelope.headline,
              purpose: 'Target-centric evidence report for a focused evidence review.',
              target: {{ target_type: 'topic', target_id: 'topic:rs429358', topic: 'rs429358' }},
              stored_research: {{ count: 0, records: [] }},
              source_catalog: {{
                summary: {{ source_count: 2 }},
                sources: [
                  {{ source_id: 'clinvar', title: 'ClinVar', best_for: 'Variant assertions' }},
                  {{ source_id: 'gwas_catalog', title: 'GWAS Catalog', best_for: 'Trait associations' }}
                ]
              }},
              defaults_applied: [
                {{ parameter: 'genome_build', source: 'tool_default', value: 'GRCh38' }}
              ],
              available_operations: [
                {{ name: 'list sources', tool: 'research.list_sources', relevance: 'source catalog' }},
                {{ name: 'record finding', tool: 'research.record', relevance: 'write-back' }}
              ],
              evidence_options: [
                {{ component: 'stored_research', state: 'absent', available_operation: 'research.record' }}
              ],
              evidence_envelope: evidenceEnvelope,
              portal_presentation: {{
                schema: 'genomi_portal_result_presentation',
                source: 'server',
                operation: targetOperation,
                kind: 'target_packet',
                kicker: 'Target evidence report',
                title: 'rs429358',
                summary: 'Target-centric evidence report for a focused evidence review.',
                evidenceEnvelope,
                metrics: [
                  {{ label: 'Sources', value: 2 }},
                  {{ label: 'Stored findings', value: 0 }},
                  {{ label: 'Answer boundary', value: 'Scoped answer only' }},
                  {{ label: 'Evidence support', value: 'Evidence present' }}
                ],
                lanes: [
                  {{
                    title: 'Target',
                    nodes: [{{ label: 'rs429358', summary: 'Topic', value: {{ target_type: 'topic', topic: 'rs429358' }} }}]
                  }},
                  {{
                    title: 'Source catalog',
                    nodes: [
                      {{ label: 'clinvar · ClinVar', summary: 'Variant assertions', value: {{ source_id: 'clinvar', title: 'ClinVar' }} }},
                      {{ label: 'gwas_catalog · GWAS Catalog', summary: 'Trait associations', value: {{ source_id: 'gwas_catalog', title: 'GWAS Catalog' }} }}
                    ]
                  }},
                  {{
                    title: 'Evidence readiness',
                    selectable: false,
                    nodes: [{{ label: 'Stored research', summary: 'Absent', value: {{ component: 'stored_research', state: 'absent' }} }}]
                  }},
                  {{
                    title: 'Coverage and limits',
                    selectable: false,
                    nodes: [{{ label: 'Coverage: source count', summary: '2', value: {{ section: 'Coverage', label: 'source count', value: 2 }} }}]
                  }}
                ]
              }}
            }};
            const versionReview = {{
              kind: 'artifact_version_review',
              status: 'warning',
              generated_at: '2026-07-01T12:00:00.000Z',
              check_count: 3,
              counts: {{ passed: 2, warning: 1, failed: 0, not_applicable: 0 }},
              checks: [
                {{
                  check_id: 'artifact_file_snapshot',
                  title: 'Artifact file snapshot',
                  status: 'passed',
                  severity: 'info',
                  summary: 'Immutable artifact file metadata is attached to this version.'
                }},
                {{
                  check_id: 'rebuild_recipe',
                  title: 'Rebuild recipe',
                  status: 'warning',
                  severity: 'warning',
                  summary: 'The rebuild recipe is partial because private parameters were redacted.'
                }},
                {{
                  check_id: 'public_payload_safety',
                  title: 'Public payload safety',
                  status: 'passed',
                  severity: 'info',
                  summary: 'No private local-path fields were present in the reviewed public payload.',
                  observed: {{ redacted: false }}
                }}
              ],
              review_runs: [
                {{
                  kind: 'artifact_review_run',
                  review_run_id: 'rev_private_transport_id',
                  status: 'completed',
                  check_status: 'warning',
                  completed_at: '2026-07-01T12:05:00.000Z',
                  check_count: 3,
                  counts: {{ passed: 2, warning: 1, failed: 0, not_applicable: 0 }},
                  summary: 'Deterministic artifact checks completed for this result version.'
                }}
              ],
              limitations: ['These are deterministic artifact and evidence-boundary checks, not clinical validation.']
            }};
            const artifact = {{
              id: 'art_packet',
              project_id: 'proj_1',
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              title: 'Evidence report: topic:rs429358',
              status: 'completed',
              operation: targetOperation,
              created_at: '2026-07-01T12:00:00.000Z',
              updated_at: '2026-07-01T12:01:00.000Z',
              summary_lines: ['Evidence present', '2 sources', '0 stored findings'],
              summary,
              latest_version_id: 'ver_packet',
              version_count: 1,
              preview_url: '/api/projects/proj_1/artifacts/art_packet/versions/ver_packet/file',
              open_label: 'Open report',
              latest_version: {{
                version_id: 'ver_packet',
                project_id: 'proj_1',
                artifact_id: 'art_packet',
                file_url: '/api/projects/proj_1/artifacts/art_packet/versions/ver_packet/file',
                reproduction: {{
                  status: 'ready',
                  kind: 'operation_rebuild_recipe',
                  artifact_family: 'evidence_report',
                  tool: targetOperation,
                  operation: targetOperation,
                  renderer: 'evidence_packet',
                  params: {{ target_type: 'topic', topic: 'rs429358', limit: 6 }},
                  params_redacted: false,
                  commands: [
                    {{
                      label: 'Genomi operation',
                      language: 'shell',
                      command: 'genomi call research.build_target_packet --params ' + JSON.stringify({{ target_type: 'topic', topic: 'rs429358', limit: 6 }}),
                      purpose: 'Recreate the operation result JSON used by the portal renderer.'
                    }}
                  ],
                  script: 'genomi call research.build_target_packet --params ' + JSON.stringify({{ target_type: 'topic', topic: 'rs429358', limit: 6 }}),
	                host_agent: {{
                    tool: targetOperation,
                    params: {{ target_type: 'topic', topic: 'rs429358', limit: 6 }},
                    instruction: 'Ask the host agent to call this Genomi operation through MCP.'
                  }},
                  limitations: ['Does not replay the host-agent reasoning turn.']
                }},
                review: versionReview
              }},
	              origin_context: {{ frame_id: 'frame_packet', message_ids_count: 2, run_ids: ['run_packet'] }}
            }};
            const state = artifacts.artifactStateModel(artifact);
            const review = artifacts.artifactReviewBriefModel(artifact);
            const reviewState = artifacts.artifactReviewStateModel(artifact);
            const runtime = artifacts.artifactRuntimeModel(artifact);
            const reproduction = artifacts.artifactReproductionModel(artifact);
            const payload = artifacts.artifactReviewBriefPayload(artifact);
            const tabs = artifacts.artifactProvenanceTabsModel(artifact, 'http://127.0.0.1:8768/projects/proj');
            const view = artifacts.artifactProvenanceViewModel(artifact, 'http://127.0.0.1:8768/projects/proj');
            const evidenceTab = view.tabs.find((tab) => tab.id === 'evidence');
            const reviewTab = view.tabs.find((tab) => tab.id === 'review');
            const actionLabels = artifacts.artifactActionMenuModel({{
              artifact,
              model: artifacts.artifactDisplayModel(artifact),
              mode: 'preview',
              tabs: view.allTabs,
              options: {{ onActivateTab: () => undefined }}
            }}).map((action) => action.label);
            const result = {{
              stateTitle: state.title,
              stateMetricLabels: state.metrics.map((metric) => metric.label),
              stateSectionTitles: state.sections.map((section) => section.title),
              stateSourceLabel: state.sections.find((section) => section.title === 'Source catalog').nodes[0].label,
              evidenceTabLabel: evidenceTab.label,
              evidenceTabBadge: evidenceTab.badge,
              evidenceTabTitle: evidenceTab.model.title,
              evidenceTabSectionTitles: evidenceTab.model.sections.map((section) => section.title),
              actionLabels,
              reviewTitle: review.title,
              reviewInstruction: review.nodes.find((node) => node.label === 'Review instruction').value,
              reviewNodeLabels: review.nodes.map((node) => node.label),
              reviewStateStatus: reviewState.status,
              reviewStateSections: reviewState.sections.map((section) => section.title),
              reviewRunHistory: reviewState.sections
                .find((section) => section.title === 'Check run history')
                .nodes[0],
              reviewSafetyObserved: reviewState.sections
                .find((section) => section.title === 'Version checks')
                .nodes.find((node) => node.label === 'Public payload safety').value.observed,
              reviewTabBadge: reviewTab.badge,
              reviewTabSections: reviewTab.model.sections.map((section) => section.title),
              runtimeDefaultLabel: runtime.sections.find((section) => section.title === 'Defaults applied').nodes[0].label,
              runtimeDefaultSummary: runtime.sections.find((section) => section.title === 'Defaults applied').nodes[0].summary,
              reproductionTitle: reproduction.title,
              reproductionCodeBlocks: reproduction.codeBlocks,
              reproductionTechnicalCommand: reproduction.technical.codeBlocks[0].code,
              reproductionInputCoverage: reproduction.sections.find((section) => section.title === 'Rebuild readiness').nodes.find((node) => node.label === 'Input coverage').value,
              reproductionSectionTitles: reproduction.sections.map((section) => section.title),
              payload,
              tabs
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        completed = subprocess.run(
            ["node", "--input-type=module"],
            input=script,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["stateTitle"], "Evidence report state")
        self.assertEqual(
            result["stateMetricLabels"],
            ["Target", "Sources", "Stored findings", "Answer boundary", "Evidence support"],
        )
        self.assertEqual(
            result["stateSectionTitles"],
            ["Target", "Source catalog", "Evidence readiness", "Coverage and limits"],
        )
        self.assertEqual(result["stateSourceLabel"], "clinvar · ClinVar")
        self.assertEqual(result["evidenceTabLabel"], "Evidence report")
        self.assertEqual(result["evidenceTabBadge"], "")
        self.assertEqual(result["evidenceTabTitle"], "Evidence report state")
        self.assertEqual(
            result["evidenceTabSectionTitles"],
            ["Target", "Source catalog", "Evidence readiness", "Coverage and limits"],
        )
        self.assertNotIn("Open evidence report", result["actionLabels"])
        self.assertNotIn("Open artifact details", result["actionLabels"])
        self.assertNotIn("Open result details", result["actionLabels"])
        self.assertEqual(result["reviewTitle"], "Artifact review summary: Evidence report: topic:rs429358")
        self.assertEqual(
            result["reviewInstruction"],
            "Use the artifact provenance, source details, and review state to identify what is supported, missing, blocked, and worth following up.",
        )
        self.assertEqual(result["reviewStateStatus"], "warning")
        self.assertEqual(result["reviewSafetyObserved"], {"redacted": False})
        self.assertEqual(result["reviewRunHistory"]["label"], "Check run 1")
        self.assertIn("completed · warning", result["reviewRunHistory"]["summary"])
        self.assertNotIn("rev_private_transport_id", json.dumps(result["reviewRunHistory"]))
        self.assertEqual(result["reviewTabBadge"], "1 warning")
        self.assertIn("Version checks", result["reviewStateSections"])
        self.assertIn("Check run history", result["reviewStateSections"])
        self.assertIn("Version checks", result["reviewTabSections"])
        self.assertIn("Source detail section / Source coverage", result["reviewNodeLabels"])
        self.assertIn("Version review section / Version checks", result["reviewNodeLabels"])
        self.assertEqual(result["runtimeDefaultLabel"], "genome_build")
        self.assertEqual(result["runtimeDefaultSummary"], "GRCh38")
        self.assertEqual(result["reproductionTitle"], "Rebuild recipe: Evidence report: topic:rs429358")
        self.assertEqual(result["reproductionCodeBlocks"], [])
        self.assertIn("genomi call research.build_target_packet", result["reproductionTechnicalCommand"])
        self.assertEqual(result["reproductionInputCoverage"], "Exact public inputs")
        self.assertEqual(result["reproductionSectionTitles"], ["Rebuild readiness", "Public inputs", "Rebuild limits"])
        self.assertIn("State section / Source catalog", result["reviewNodeLabels"])
        self.assertIn("State metric / Answer boundary", result["reviewNodeLabels"])
        state_review_labels = [label for label in result["reviewNodeLabels"] if label.startswith("State ")]
        self.assertTrue(state_review_labels)
        self.assertTrue(all(label.startswith(("State metric / ", "State section / ")) for label in state_review_labels))
        self.assertIn("Artifact review / State section / Source catalog", result["payload"]["prompt_text"])
        self.assertIn("Artifact review / State metric / Answer boundary", result["payload"]["prompt_text"])
        self.assertEqual(result["tabs"]["defaultTab"], "preview")
        self.assertNotIn("technical", [tab["id"] for tab in result["tabs"]["tabs"]])
        self.assertIn("technical", [tab["id"] for tab in result["tabs"]["secondaryTabs"]])
        self.assertIn("technical", [tab["id"] for tab in result["tabs"]["allTabs"]])
        self.assertIn("review", [tab["id"] for tab in result["tabs"]["tabs"]])
        self.assertIn("rebuild", [tab["id"] for tab in result["tabs"]["tabs"]])
        self.assertNotIn("code", [tab["id"] for tab in result["tabs"]["tabs"]])
        self.assertNotIn("runtime", [tab["id"] for tab in result["tabs"]["tabs"]])
        self.assertNotIn("state", [tab["id"] for tab in result["tabs"]["tabs"]])
        _assert_public_payload(result["payload"])

    def test_reproduction_model_renders_partial_recipe_without_private_command_values(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for frontend module tests")
        artifacts_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifacts.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const artifacts = await import({artifacts_url!r});
            const artifact = {{
              id: 'art_redacted',
              project_id: 'proj_1',
              title: 'Evidence report: rs429358',
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              operation: 'research.build_target_packet',
              latest_version_id: 'ver_redacted',
              latest_version: {{
                version_id: 'ver_redacted',
                project_id: 'proj_1',
                artifact_id: 'art_redacted',
                reproduction: {{
                  status: 'partial_private_parameters_redacted',
                  kind: 'operation_rebuild_recipe',
                  artifact_family: 'evidence_report',
                  operation: 'research.build_target_packet',
                  renderer: 'evidence_packet',
                  params: {{
                    topic: 'rs429358',
                    agi_path: '/Users/matthewzmd/private/genome.sqlite',
                    nested: {{ dashboard_path: '/tmp/dashboard.html', public: 'kept' }}
                  }},
                  params_redacted: true,
                  commands: [
                    {{ command: 'genomi call research.build_target_packet --shared_evidence_db /tmp/evidence.sqlite', arbitrary: 'hidden' }}
                  ],
                  script: 'genomi call research.build_target_packet --dashboard_path /tmp/dashboard.html',
                  host_agent: {{
                    tool: 'research.build_target_packet',
                    params: {{ topic: 'rs429358', shared_evidence_db: '/tmp/evidence.sqlite' }},
                    instruction: 'Use agi_path=/Users/matthewzmd/private/genome.sqlite before rerun.',
                    arbitrary: '/Users/matthewzmd/private/host-agent.txt'
                  }},
                  limitations: ['Original command used dashboard_path=/tmp/dashboard.html.'],
                  arbitrary: '/Users/matthewzmd/private/top-level.txt'
                }}
              }}
            }};
            const model = artifacts.artifactReproductionModel(artifact);
            process.stdout.write(JSON.stringify({{
              status: model.status,
              metricStatus: model.metrics.find((metric) => metric.label === 'Recipe state').value,
              codeBlocks: model.codeBlocks,
              inputCoverage: model.sections.find((section) => section.title === 'Rebuild readiness').nodes.find((node) => node.label === 'Input coverage').value,
              paramsValue: model.sections.find((section) => section.title === 'Public inputs').nodes.map((node) => node.value),
              hostAgentValue: model.technical.sections.find((section) => section.title === 'Host-agent handoff').nodes.map((node) => node.value),
              serialized: JSON.stringify(model)
            }}));
            """
        )

        completed = subprocess.run(
            ["node", "--input-type=module"],
            input=script,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["status"], "partial_private_parameters_redacted")
        self.assertEqual(result["metricStatus"], "Private inputs redacted")
        self.assertEqual(result["codeBlocks"], [])
        self.assertEqual(result["inputCoverage"], "Private inputs redacted")
        self.assertIn({"public": "kept"}, result["paramsValue"])
        self.assertNotIn("arbitrary", result["serialized"])
        self.assertNotIn("commands", result["serialized"])
        _assert_public_payload(json.loads(result["serialized"]))

    def test_reproduction_model_does_not_fallback_to_latest_recipe_for_selected_version(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for frontend module tests")
        artifacts_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifacts.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const artifacts = await import({artifacts_url!r});
            const latestRecipe = {{
              status: 'ready',
              kind: 'operation_rebuild_recipe',
              artifact_family: 'evidence_report',
              operation: 'research.build_target_packet',
              renderer: 'evidence_packet',
              params: {{ target_type: 'topic', topic: 'rs429358' }},
              params_redacted: false,
              commands: [{{ label: 'Genomi operation', language: 'shell', command: 'genomi call research.build_target_packet --params "{{}}"', purpose: 'Rebuild latest.' }}],
              script: 'genomi call research.build_target_packet --params "{{}}"',
              host_agent: {{ tool: 'research.build_target_packet', params: {{ target_type: 'topic', topic: 'rs429358' }} }},
              limitations: []
            }};
            const baseArtifact = {{
              id: 'art_versions',
              project_id: 'proj_1',
              title: 'Evidence report: rs429358',
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              operation: 'research.build_target_packet',
              latest_version_id: 'ver_latest',
              versions_loaded: true,
              reproduction: latestRecipe,
              versions: [
                {{ version_id: 'ver_latest', project_id: 'proj_1', artifact_id: 'art_versions', reproduction: latestRecipe }},
                {{ version_id: 'ver_old', project_id: 'proj_1', artifact_id: 'art_versions' }}
              ]
            }};
            const latest = artifacts.artifactReproductionModel(baseArtifact);
            const selectedOld = artifacts.artifactReproductionModel({{ ...baseArtifact, selected_version_id: 'ver_old' }});
            process.stdout.write(JSON.stringify({{
              latestStatus: latest && latest.status,
              selectedOld
            }}));
            """
        )

        completed = subprocess.run(
            ["node", "--input-type=module"],
            input=script,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["latestStatus"], "ready")
        self.assertIsNone(result["selectedOld"])

    def test_review_model_does_not_fallback_to_latest_checks_for_selected_version(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for frontend module tests")
        artifacts_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifacts.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const artifacts = await import({artifacts_url!r});
            const latestReview = {{
              kind: 'artifact_version_review',
              status: 'passed',
              generated_at: '2026-07-01T12:00:00.000Z',
              check_count: 1,
              counts: {{ passed: 1, warning: 0, failed: 0, not_applicable: 0 }},
              checks: [
                {{
                  check_id: 'artifact_file_snapshot',
                  title: 'Artifact file snapshot',
                  status: 'passed',
                  severity: 'info',
                  summary: 'Immutable artifact file metadata is attached to this version.'
                }}
              ],
              limitations: []
            }};
            const baseArtifact = {{
              id: 'art_versions',
              project_id: 'proj_1',
              title: 'Evidence report: rs429358',
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              operation: 'research.build_target_packet',
              latest_version_id: 'ver_latest',
              versions_loaded: true,
              review: latestReview,
              versions: [
                {{ version_id: 'ver_latest', project_id: 'proj_1', artifact_id: 'art_versions', review: latestReview }},
                {{ version_id: 'ver_old', project_id: 'proj_1', artifact_id: 'art_versions' }}
              ]
            }};
            const latest = artifacts.artifactReviewStateModel(baseArtifact);
            const selectedOld = artifacts.artifactReviewStateModel({{ ...baseArtifact, selected_version_id: 'ver_old' }});
            const selectedBrief = artifacts.artifactReviewBriefModel({{ ...baseArtifact, selected_version_id: 'ver_old' }});
            process.stdout.write(JSON.stringify({{
              latestStatus: latest && latest.status,
              selectedOld,
              selectedBriefLabels: selectedBrief.nodes.map((node) => node.label)
            }}));
            """
        )

        completed = subprocess.run(
            ["node", "--input-type=module"],
            input=script,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["latestStatus"], "passed")
        self.assertIsNone(result["selectedOld"])
        self.assertNotIn("Version review section / Version checks", result["selectedBriefLabels"])


def _assert_public_payload(value) -> None:
    if isinstance(value, dict):
        for child in value.values():
            _assert_public_payload(child)
    elif isinstance(value, list):
        for child in value:
            _assert_public_payload(child)
    elif isinstance(value, str) and _PRIVATE_PROMPT_RE.search(value):
        raise AssertionError(f"private prompt text leaked: {value}")


if __name__ == "__main__":
    unittest.main()
