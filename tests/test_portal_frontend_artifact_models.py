from __future__ import annotations

import json
import re
import subprocess
import textwrap
import unittest
from pathlib import Path

_PRIVATE_PROMPT_RE = re.compile(r"(?:context_file|registry_file|agi_path|/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes|~)")


class PortalFrontendArtifactModelTests(unittest.TestCase):
    def test_artifacts_for_run_uses_origin_run_ids(self) -> None:
        artifacts_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifacts.js").as_uri()
        script = textwrap.dedent(
            f"""
            const artifacts = await import({artifacts_url!r});
            const matched = artifacts.artifactsForRun([
              {{
                id: 'art_match',
                title: 'Matching artifact',
                origin_context: {{ frame_id: 'frame_1', run_ids: ['run_1'] }}
              }},
              {{
                id: 'art_other_run',
                title: 'Other run',
                origin_context: {{ frame_id: 'frame_1', run_ids: ['run_2'] }}
              }},
              {{
                id: 'art_other_frame',
                title: 'Other frame',
                origin_context: {{ frame_id: 'frame_2', run_ids: ['run_1'] }}
              }}
            ], 'frame_1', 'run_1');
            process.stdout.write(JSON.stringify(matched.map((artifact) => artifact.id)));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result, ["art_match"])

    def test_artifact_details_labels_follow_user_facing_artifact_family(self) -> None:
        artifacts_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifacts.js").as_uri()
        script = textwrap.dedent(
            f"""
            const artifacts = await import({artifacts_url!r});
            function labels(artifact) {{
              const provenance = artifacts.artifactProvenanceModel(artifact);
              const tabs = artifacts.artifactProvenanceTabsModel(artifact, 'http://127.0.0.1:8768/projects/proj');
              const evidenceTab = tabs.tabs.find((tab) => tab.id === 'evidence');
              return {{
                title: provenance && provenance.title,
                tabLabel: evidenceTab && evidenceTab.label
              }};
            }}
            const file = labels({{
              id: 'art_file',
              kind: 'project_file',
              renderer: 'project_file',
              title: 'reports/apoe.md',
              status: 'completed',
              preview_url: '/api/projects/proj_1/artifacts/art_file/file'
            }});
            const report = labels({{
              id: 'art_report',
              kind: 'decode_dashboard',
              renderer: 'decode_dashboard',
              title: 'Legacy dashboard',
              status: 'completed',
              preview_url: '/api/projects/proj_1/artifacts/art_report/file'
            }});
            const evidence = labels({{
              id: 'art_evidence',
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              title: 'Evidence report: rs429358',
              status: 'completed',
              preview_url: '/api/projects/proj_1/artifacts/art_evidence/file'
            }});
            const generic = labels({{
              id: 'art_generic',
              kind: 'other',
              renderer: 'blob',
              title: 'Generated object',
              status: 'completed',
              preview_url: '/api/projects/proj_1/artifacts/art_generic/file'
            }});
            process.stdout.write(JSON.stringify({{ file, report, evidence, generic }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["file"], {"title": "File details", "tabLabel": "File details"})
        self.assertEqual(result["report"], {"title": "Report details", "tabLabel": "Report details"})
        self.assertEqual(
            result["evidence"],
            {"title": "Evidence report details", "tabLabel": "Evidence report details"},
        )
        self.assertEqual(result["generic"], {"title": "Artifact details", "tabLabel": "Artifact details"})

    def test_public_artifact_detail_exposes_compact_origin_context(self) -> None:
        from genomi.interfaces import portal_artifact_presenters

        state = {
            "frames": {"frame_1": {"id": "frame_1", "project_id": "proj_1"}},
            "messages": {
                "frame_1": [
                    {"id": "msg_1", "role": "user", "text": "Render context_file=/Users/matthewzmd/private.json"},
                    {"id": "msg_2", "role": "assistant", "text": "Artifact ready"},
                    {"id": "msg_later", "role": "assistant", "text": "Later frame message"},
                ]
            },
            "artifact_versions": {},
        }
        artifact = {
            "id": "art_1",
            "project_id": "proj_1",
            "kind": "evidence_packet",
            "renderer": "evidence_packet",
            "title": "Evidence report",
            "status": "completed",
            "origin": {"frame_id": "frame_1", "message_ids": ["msg_1", "msg_2"]},
        }

        summary = portal_artifact_presenters.public_artifact_summary(artifact, state)
        detail = portal_artifact_presenters.public_artifact_detail(artifact, state)

        self.assertEqual(summary["artifact_presentation"]["schema"], "genomi_portal_artifact_presentation")
        self.assertEqual(summary["artifact_presentation"]["family"], "evidence_report")
        self.assertEqual(summary["artifact_presentation"]["category"], "evidence")
        self.assertEqual(summary["artifact_presentation"]["surface_copy"]["selected_item"], "evidence item")
        self.assertEqual(summary["origin_context"]["frame_id"], "frame_1")
        self.assertEqual(summary["origin_context"]["message_ids_count"], 2)
        self.assertEqual(summary["origin_context"]["run_ids"], [])
        self.assertNotIn("provenance_messages", summary)
        self.assertEqual(detail["origin_context"], {"frame_id": "frame_1", "message_ids_count": 2, "run_ids": []})
        self.assertEqual(detail["provenance_messages"]["frame_id"], "frame_1")
        self.assertEqual(detail["provenance_messages"]["total"], 2)
        self.assertEqual(detail["provenance_messages"]["displayed"], 2)
        self.assertNotIn("Later frame message", json.dumps(detail))
        _assert_public_payload(detail)

    def test_public_artifact_origin_context_prefers_stored_producing_run(self) -> None:
        from genomi.interfaces import portal_artifact_presenters

        state = {
            "frames": {"frame_1": {"id": "frame_1", "project_id": "proj_1"}},
            "messages": {
                "frame_1": [
                    {"id": "msg_old_tool", "role": "tool", "run_id": "run_old", "event": {"type": "diagnostic"}},
                    {"id": "msg_answer", "role": "assistant", "run_id": "run_prod", "text": "Artifact ready"},
                ]
            },
            "artifact_versions": {},
        }
        artifact = {
            "id": "art_1",
            "project_id": "proj_1",
            "kind": "evidence_packet",
            "renderer": "evidence_packet",
            "title": "Evidence report",
            "status": "completed",
            "origin": {
                "frame_id": "frame_1",
                "message_ids": ["msg_old_tool", "msg_answer"],
                "producing_run_id": "run_prod",
                "producing_assistant_message_id": "msg_answer",
            },
        }

        summary = portal_artifact_presenters.public_artifact_summary(artifact, state)

        self.assertEqual(summary["origin_context"]["run_ids"], ["run_prod"])
        self.assertEqual(summary["origin_context"]["producing_run_id"], "run_prod")
        self.assertEqual(summary["origin_context"]["producing_assistant_message_id"], "msg_answer")

    def test_artifact_inspection_api_hydrates_detail_and_versions(self) -> None:
        api_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_api.js").as_uri()
        script = textwrap.dedent(
            f"""
            const api = await import({api_url!r});
            const calls = [];
            globalThis.fetch = async (path) => {{
              calls.push(path);
              if (path === '/api/projects/proj%201/artifacts/art%20dash') {{
                return {{
                  ok: true,
                  json: async () => ({{
                    id: 'art dash',
                    project_id: 'proj 1',
                    title: 'Hydrated artifact',
                    latest_version_id: 'ver_dash'
                  }})
                }};
              }}
              if (path === '/api/projects/proj%201/artifacts/art%20dash/versions') {{
                return {{
                  ok: true,
                  json: async () => ({{
                    project_id: 'proj 1',
                    artifact_id: 'art dash',
                    latest_version_id: 'ver_dash',
                    versions: [
                      {{ version_id: 'ver_dash', project_id: 'proj 1', artifact_id: 'art dash', checksum: 'sha256:abc123' }}
                    ]
                  }})
                }};
              }}
              return {{ ok: false, json: async () => ({{ error: {{ message: 'unexpected ' + path }} }}) }};
            }};
            const result = await api.loadArtifactInspection('proj 1', 'art dash');
            process.stdout.write(JSON.stringify({{ calls, result }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(
            result["calls"],
            ["/api/projects/proj%201/artifacts/art%20dash", "/api/projects/proj%201/artifacts/art%20dash/versions"],
        )
        self.assertTrue(result["result"]["versions_loaded"])
        self.assertEqual(result["result"]["versions"][0]["version_id"], "ver_dash")
        self.assertEqual(result["result"]["latest_version_id"], "ver_dash")

    def test_artifact_models_prefer_immutable_version_urls(self) -> None:
        artifacts_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifacts.js").as_uri()
        script = textwrap.dedent(
            f"""
            const artifacts = await import({artifacts_url!r});
            const nodeValue = (model, label) => {{
              const node = model && Array.isArray(model.nodes) ? model.nodes.find((item) => item.label === label) : null;
              return node ? node.value : null;
            }};
            const latestEnvironment = {{
              kind: 'artifact_environment_snapshot',
              generated_at: '2026-07-01T12:00:00.000Z',
              operation: 'decode.render_dashboard',
              renderer: 'decode_dashboard',
              artifact_kind: 'decode_dashboard',
              host_agent: {{ agent_id: 'codex' }},
              runtime: {{
                genomi_version: '0.1.0',
                python_version: '3.14.3',
                python_implementation: 'CPython',
                system: 'Darwin',
                machine: 'arm64'
              }},
              packages: [
                {{ name: 'genomi', version: '0.1.0', status: 'installed' }},
                {{ name: 'numpy', version: '2.0.0', status: 'installed' }}
              ],
              libraries: {{
                summary: {{ library_count: 2, installed_count: 1, missing_count: 1, manual_source_required_count: 0, not_applicable_count: 0 }},
                items: [
                  {{ library: 'clinvar-grch38', title: 'ClinVar', kind: 'offline', status: 'installed', installed: true, size_class: '~180 MB' }},
                  {{ library: 'hpo', title: 'HPO', kind: 'offline', status: 'not_installed', installed: false, size_class: '~100 MB' }}
                ]
              }},
              limitations: ['Captures the local Genomi portal runtime, not the assistant process.']
            }};
            const oldEnvironment = {{
              ...latestEnvironment,
              generated_at: '2026-06-30T12:00:00.000Z',
              runtime: {{ ...latestEnvironment.runtime, python_version: '3.13.5' }},
              libraries: {{
                summary: {{ library_count: 2, installed_count: 2, missing_count: 0, manual_source_required_count: 0, not_applicable_count: 0 }},
                items: [
                  {{ library: 'clinvar-grch38', title: 'ClinVar', kind: 'offline', status: 'installed', installed: true }},
                  {{ library: 'hpo', title: 'HPO', kind: 'offline', status: 'installed', installed: true }}
                ]
              }}
            }};
            const evidenceEnvironment = {{
              ...latestEnvironment,
              operation: 'research.build_target_packet',
              renderer: 'evidence_packet',
              artifact_kind: 'evidence_packet',
              libraries: {{
                summary: {{ library_count: 1, installed_count: 1, missing_count: 0, manual_source_required_count: 0, not_applicable_count: 0 }},
                items: [
                  {{ library: 'clinvar-grch38', title: 'ClinVar', kind: 'offline', status: 'installed', installed: true }}
                ]
              }}
            }};
            const unavailableEnvironment = {{
              ...latestEnvironment,
              libraries: {{
                summary: {{
                  library_count: 0,
                  installed_count: 0,
                  missing_count: 0,
                  manual_source_required_count: 0,
                  not_applicable_count: 0,
                  status: 'unavailable',
                  error: 'Library inventory unavailable'
                }},
                items: []
              }}
            }};
            const errorEnvironment = {{
              ...latestEnvironment,
              libraries: {{
                summary: {{
                  library_count: 0,
                  installed_count: 0,
                  missing_count: 0,
                  manual_source_required_count: 0,
                  not_applicable_count: 0,
                  status: 'error',
                  error: 'Library inventory failed'
                }},
                items: []
              }}
            }};
            const dashboardArtifact = {{
              id: 'art_dash',
              project_id: 'proj_1',
              kind: 'decode_dashboard',
              renderer: 'decode_dashboard',
              title: 'Genomi Dashboard',
              status: 'completed',
              operation: 'decode.render_dashboard',
              created_at: '2026-07-01T12:00:00.000Z',
              updated_at: '2026-07-01T12:01:00.000Z',
              summary_lines: ['completed', '2 panels rendered', '1 empty'],
              summary: {{
                panels_rendered: ['clinvar', 'pharmacogenomics'],
                panels_empty: ['prs'],
                defaults_applied: {{
                  assembly: 'GRCh38',
                  evidence_scope: 'project'
                }},
                source_catalog: {{
                  summary: {{ source_count: 2, installed_count: 1, unavailable_count: 1, status: 'partial' }},
                  sources: [
                    {{ source_id: 'clinvar', title: 'ClinVar', status: 'installed', best_for: 'Variant assertions' }},
                    {{ source_id: 'gwas_catalog', title: 'GWAS Catalog', status: 'missing', best_for: 'Trait associations' }}
                  ]
                }},
                evidence_envelope: {{
                  finding_state: 'data_returned',
                  answer_readiness: 'scoped_answer_only',
                  scope: {{ active_genome_index: 'session' }},
                  negative_inference: {{ rule: 'do_not_imply_clinical_negative' }}
                }},
                runtime_context: {{
                  response_profile: 'genomi_portal',
                  scratch_path: '/Users/matthewzmd/.genomi/private-run'
                }},
                evidence_build: {{
                  panels_blocked: ['ancestry'],
                  panels_running: ['nutrigenomics'],
                  panels_failed: {{ rare_disease: {{ status: 'failed', reason: 'library unavailable' }} }},
                  panel_states: {{ clinvar: {{ status: 'ready', count: 3 }} }}
                }}
              }},
              url: 'http://127.0.0.1:9000/dashboard.html',
              preview_url: '/api/artifacts/art_dash/file',
              open_label: 'Open dashboard',
              latest_version_id: 'ver_dash',
              version_count: 2,
              versions_loaded: true,
              latest_version: {{
                version_id: 'ver_dash',
                project_id: 'proj_1',
                artifact_id: 'art_dash',
                file_url: '/api/projects/proj_1/artifacts/art_dash/versions/ver_dash/file',
                content_type: 'text/html',
                checksum: 'sha256:abc123',
                size_bytes: 4096,
                filename: 'ver_dash.html',
                environment: latestEnvironment
              }},
              versions: [
                {{
                  version_id: 'ver_dash',
                  project_id: 'proj_1',
                  artifact_id: 'art_dash',
                  file_url: '/api/projects/proj_1/artifacts/art_dash/versions/ver_dash/file',
                  content_type: 'text/html',
                  checksum: 'sha256:abc123',
                  size_bytes: 4096,
                  filename: 'ver_dash.html',
                  environment: latestEnvironment
                }},
                {{
                  version_id: 'ver_old',
                  project_id: 'proj_1',
                  artifact_id: 'art_dash',
                  file_url: '/api/projects/proj_1/artifacts/art_dash/versions/ver_old/file',
                  content_type: 'text/html',
                  checksum: 'sha256:old',
                  size_bytes: 2048,
                  filename: 'ver_old.html',
                  environment: oldEnvironment
                }}
              ],
              origin_context: {{
                frame_id: 'frame_origin',
                message_ids_count: 3,
                run_ids: ['run_1'],
                producing_run_id: 'run_1',
                producing_assistant_message_id: 'msg_assistant'
              }},
              provenance_messages: {{
                frame_id: 'frame_dash',
                total: 3,
                messages: [
                  {{
                    id: 'msg_user',
                    role: 'user',
                    text: 'Review context_file=/Users/matthewzmd/.genomi/private.json',
                    created_at: '2026-07-01T12:00:01.000Z'
                  }},
                  {{
                    id: 'msg_tool',
                    role: 'tool',
                    run_id: 'run_1',
                    event: {{
                      type: 'tool_result',
                      name: 'variant.resolve',
                      content: 'variant.resolve result from /tmp/private.sqlite'
                    }},
                    created_at: '2026-07-01T12:00:02.000Z'
                  }},
                  {{
                    id: 'msg_assistant',
                    role: 'assistant',
                    text: 'Artifact saved.',
                    stream_status: 'completed',
                    created_at: '2026-07-01T12:00:03.000Z'
                  }}
                ]
              }}
            }};
            const legacyArtifact = {{
              id: 'art_1',
              title: 'Genomi Dashboard',
              status: 'completed',
              renderer: 'decode_dashboard',
              operation: 'decode.render_dashboard',
              summary_lines: ['completed', '1 panel rendered'],
              open_label: 'Open dashboard',
              url: 'http://127.0.0.1:9000/dashboard.html',
              preview_url: '/api/artifacts/art_1/file'
            }};
            const legacyEvidenceArtifact = {{
              id: 'art_report_legacy',
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              title: 'Evidence packet: rs429358',
              operation: 'research.build_target_packet',
              open_label: 'Open packet',
              summary_lines: ['evidence_present'],
              url: '/api/projects/proj_1/artifacts/art_report_legacy/file'
            }};
            const serverPresentedArtifact = {{
              id: 'art_server_presented',
              kind: 'note',
              renderer: 'markdown',
              title: 'Evidence packet: server-owned',
              status: 'completed',
              artifact_presentation: {{
                schema: 'genomi_portal_artifact_presentation',
                family: 'evidence_report',
                category: 'evidence',
                surface_copy: {{
                  noun: 'report',
                  summary_noun: 'report summary',
                  use_label: 'Use server report',
                  ask_label: 'Ask server report',
                  draft_label: 'Draft server report',
                  open_label: 'Open server report',
                  selected_item: 'server evidence item',
                  selected_items: 'server evidence items',
                  selected_heading: 'Selected server evidence',
                  selected_group: 'Server evidence report',
                  prompt_intro_prefix: 'Selected server evidence report',
                  context_kind: 'evidence_report',
                  label_prefix: 'Evidence report',
                  node_context_prefix: 'Evidence report'
                }}
              }}
            }};
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
            const versionOwnedArtifact = {{
              id: 'art_version_owned',
              project_id: 'proj_1',
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              title: 'Evidence report: rs429358',
              status: 'completed',
              operation: 'research.build_target_packet',
              latest_version_id: 'ver_latest',
              versions_loaded: true,
              latest_version: {{
                version_id: 'ver_latest',
                project_id: 'proj_1',
                artifact_id: 'art_version_owned',
                file_url: '/api/projects/proj_1/artifacts/art_version_owned/versions/ver_latest/file',
                content_type: 'text/html',
                checksum: 'sha256:latest-owned',
                size_bytes: 512,
                environment: evidenceEnvironment,
                review: latestReview,
                reproduction: latestRecipe
              }},
              versions: [
                {{
                  version_id: 'ver_latest',
                  project_id: 'proj_1',
                  artifact_id: 'art_version_owned',
                  file_url: '/api/projects/proj_1/artifacts/art_version_owned/versions/ver_latest/file',
                  content_type: 'text/html',
                  checksum: 'sha256:latest-owned',
                  size_bytes: 512,
                  environment: evidenceEnvironment,
                  review: latestReview,
                  reproduction: latestRecipe
                }}
              ]
            }};
            const detailHydratedArtifact = {{
              ...versionOwnedArtifact,
              id: 'art_detail_hydrated',
              summary: {{
                defaults_applied: [
                  {{ parameter: 'genome_build', source: 'tool_default', value: 'GRCh38', applies_when_omitted: true }}
                ],
                evidence_envelope: {{
                  finding_state: 'evidence_present',
                  answer_readiness: 'scoped_answer_only',
                  negative_inference: {{ allowed: false }},
                  observations: {{ source_catalog_count: 1 }}
                }},
                source_catalog: {{
                  summary: {{ source_count: 1 }},
                  sources: [
                    {{
                      source_id: 'hpo',
                      title: 'Human Phenotype Ontology',
                      adapter_status: 'implemented_local_normalization',
                      best_for: 'Normalizing phenotype terms and HPO identifiers before disease or gene prioritization.'
                    }}
                  ]
                }}
              }},
              environment: evidenceEnvironment,
              latest_version: {{
                version_id: 'ver_latest',
                project_id: 'proj_1',
                artifact_id: 'art_detail_hydrated',
                file_url: '/api/projects/proj_1/artifacts/art_detail_hydrated/versions/ver_latest/file',
                content_type: 'text/html',
                checksum: 'sha256:latest-owned',
                size_bytes: 512,
                review: latestReview,
                reproduction: latestRecipe
              }},
              versions: [
                {{
                  version_id: 'ver_latest',
                  project_id: 'proj_1',
                  artifact_id: 'art_detail_hydrated',
                  file_url: '/api/projects/proj_1/artifacts/art_detail_hydrated/versions/ver_latest/file',
                  content_type: 'text/html',
                  checksum: 'sha256:latest-owned',
                  size_bytes: 512,
                  review: latestReview,
                  reproduction: latestRecipe
                }}
              ]
            }};
            const unresolvedVersionOwnedArtifact = {{ ...versionOwnedArtifact, selected_version_id: 'ver_missing' }};
            const unavailableEnvironmentArtifact = {{
              ...dashboardArtifact,
              id: 'art_unavailable_env',
              latest_version: {{ ...dashboardArtifact.latest_version, environment: unavailableEnvironment }},
              versions: [{{ ...dashboardArtifact.versions[0], environment: unavailableEnvironment }}]
            }};
            const errorEnvironmentArtifact = {{
              ...dashboardArtifact,
              id: 'art_error_env',
              latest_version: {{ ...dashboardArtifact.latest_version, environment: errorEnvironment }},
              versions: [{{ ...dashboardArtifact.versions[0], environment: errorEnvironment }}]
            }};
            const visibleEnvironmentText = (model) => JSON.stringify({{
              title: model && model.title,
              status: model && model.status,
              metrics: model && model.metrics ? model.metrics.map((item) => [item.label, item.value]) : [],
              sections: model && model.sections ? model.sections.map((section) => ({{
                title: section.title,
                nodes: section.nodes.map((node) => [node.label, node.summary])
              }})) : []
            }});
            const versionedProvenance = artifacts.artifactProvenanceModel(dashboardArtifact);
            const versionedOperationTrace = artifacts.artifactOperationTraceModel(dashboardArtifact);
            const versionOwnedEnvironment = artifacts.artifactEnvironmentModel(versionOwnedArtifact);
            const unavailableEnvironmentModel = artifacts.artifactEnvironmentModel(unavailableEnvironmentArtifact);
            const errorEnvironmentModel = artifacts.artifactEnvironmentModel(errorEnvironmentArtifact);
            const serverPresentedModel = artifacts.artifactDisplayModel(serverPresentedArtifact);
            const result = {{
              versionedDisplay: artifacts.artifactDisplayModel(dashboardArtifact),
              versionedPreview: artifacts.artifactPreviewModel(dashboardArtifact, 'http://127.0.0.1:8768/projects/proj'),
              versionedProvenance,
              versionedProvenanceUrl: nodeValue(versionedProvenance, 'Artifact URL'),
              versionedHistory: nodeValue(versionedProvenance, 'Version history'),
              versionedIds: nodeValue(versionedProvenance, 'Version ids'),
              versionedOperationTrace,
              versionedTraceIds: nodeValue(versionedOperationTrace, 'Version ids'),
              versionedTracePreviewUrl: nodeValue(versionedOperationTrace, 'Preview URL'),
              selectedVersionDisplay: artifacts.artifactDisplayModel({{ ...dashboardArtifact, selected_version_id: 'ver_old' }}),
              selectedVersionPreview: artifacts.artifactPreviewModel({{ ...dashboardArtifact, selected_version_id: 'ver_old' }}, 'http://127.0.0.1:8768/projects/proj'),
              selectedVersionProvenance: artifacts.artifactProvenanceModel({{ ...dashboardArtifact, selected_version_id: 'ver_old' }}),
              selectedVersionRuntime: artifacts.artifactRuntimeModel({{ ...dashboardArtifact, selected_version_id: 'ver_old' }}),
              selectedVersionReviewPayload: artifacts.artifactReviewBriefPayload({{ ...dashboardArtifact, selected_version_id: 'ver_old' }}),
              versionSelector: artifacts.artifactVersionSelectorModel({{ ...dashboardArtifact, selected_version_id: 'ver_old' }}),
              singleVersionSelector: artifacts.artifactVersionSelectorModel(versionOwnedArtifact),
              ignoredMissingSelectedVersion: artifacts.artifactDisplayModel({{ ...dashboardArtifact, selected_version_id: 'ver_missing' }}),
              unresolvedVersionOwnedDisplay: artifacts.artifactDisplayModel(unresolvedVersionOwnedArtifact),
              unresolvedVersionOwnedReview: artifacts.artifactReviewStateModel(unresolvedVersionOwnedArtifact),
              unresolvedVersionOwnedReproduction: artifacts.artifactReproductionModel(unresolvedVersionOwnedArtifact),
              versionOwnedEnvironment,
              detailHydratedEnvironment: artifacts.artifactEnvironmentModel(detailHydratedArtifact),
              detailHydratedEnvironmentVisibleText: visibleEnvironmentText(artifacts.artifactEnvironmentModel(detailHydratedArtifact)),
              detailHydratedTabs: artifacts.artifactProvenanceTabsModel(detailHydratedArtifact, 'http://127.0.0.1:8768/projects/proj'),
              versionOwnedEnvironmentVisibleText: visibleEnvironmentText(versionOwnedEnvironment),
              unavailableEnvironment: unavailableEnvironmentModel,
              unavailableEnvironmentTabBadge: artifacts.artifactProvenanceViewModel(unavailableEnvironmentArtifact, 'http://127.0.0.1:8768/projects/proj').tabs.find((tab) => tab.id === 'environment').badge,
              errorEnvironment: errorEnvironmentModel,
              errorEnvironmentTabBadge: artifacts.artifactProvenanceViewModel(errorEnvironmentArtifact, 'http://127.0.0.1:8768/projects/proj').tabs.find((tab) => tab.id === 'environment').badge,
              artifactModel: artifacts.artifactDisplayModel(legacyArtifact),
              legacyEvidenceModel: artifacts.artifactDisplayModel(legacyEvidenceArtifact),
              serverPresentedModel,
              serverPresentedCopy: artifacts.artifactSurfaceCopy(serverPresentedModel),
              artifactContext: artifacts.artifactContextPayload(legacyArtifact),
              legacyEvidenceContext: artifacts.artifactContextPayload(legacyEvidenceArtifact),
              artifactContextFromAlias: artifacts.artifactContextPayload({{
                id: 'art_2',
                title: 'Rendered review',
                operation: 'decode.render_dashboard',
                summary_lines: ['completed'],
                path: '/tmp/private-dashboard.html'
              }}),
              artifactProvenanceView: artifacts.artifactProvenanceViewModel(dashboardArtifact, 'http://127.0.0.1:8768/projects/proj'),
              artifactTabs: artifacts.artifactProvenanceTabsModel(dashboardArtifact, 'http://127.0.0.1:8768/projects/proj'),
              versionOwnedTabs: artifacts.artifactProvenanceTabsModel(versionOwnedArtifact, 'http://127.0.0.1:8768/projects/proj'),
              artifactEnvironment: artifacts.artifactEnvironmentModel(dashboardArtifact),
              selectedVersionEnvironment: artifacts.artifactEnvironmentModel({{ ...dashboardArtifact, selected_version_id: 'ver_old' }}),
              unresolvedVersionOwnedEnvironment: artifacts.artifactEnvironmentModel(unresolvedVersionOwnedArtifact),
              artifactMessages: artifacts.artifactMessagesModel(dashboardArtifact),
              artifactOriginContext: artifacts.artifactOriginContextModel(dashboardArtifact),
              artifactOriginContextMissing: artifacts.artifactOriginContextModel(legacyArtifact),
              artifactOriginContextMessagesOnly: artifacts.artifactOriginContextModel({{
                provenance_messages: {{
                  frame_id: 'frame_messages_only',
                  total: 1,
                  messages: [{{ id: 'msg_only', role: 'assistant', text: 'Only transcript slice' }}]
                }}
              }}),
              artifactRuntime: artifacts.artifactRuntimeModel(dashboardArtifact),
              artifactState: artifacts.artifactStateModel(dashboardArtifact),
              artifactReviewBrief: artifacts.artifactReviewBriefModel(dashboardArtifact),
              artifactReviewPayload: artifacts.artifactReviewBriefPayload(dashboardArtifact),
              artifactSelectedContext: artifacts.artifactContextForSelection(dashboardArtifact, {{
                querySelectorAll: () => [
                  {{ dataset: {{ label: 'Ancestry section', context: 'Blocked sections / Ancestry: ancestry', value: 'ancestry' }} }}
                ]
              }}),
              artifactSelectionEmpty: artifacts.artifactSelectionModel({{
                querySelectorAll: (selector) => selector === '.artifact-node[data-selectable="true"]' ? [{{}}, {{}}] : []
              }}),
              artifactSelectionSelected: artifacts.artifactSelectionModel({{
                querySelectorAll: (selector) => selector === '.artifact-node[data-selectable="true"]'
                  ? [{{}}, {{}}, {{}}]
                  : selector === '.artifact-node[data-selectable="true"].selected'
                    ? [
                      {{ dataset: {{ label: 'ClinVar section', context: 'Rendered sections / ClinVar: ready', value: 'ready' }} }},
                      {{ dataset: {{ label: 'PRS section', context: 'Empty sections / PRS: in_scope_empty', value: 'in_scope_empty' }} }}
                    ]
                    : []
              }}),
              artifactPreviewLocal: artifacts.artifactPreviewModel({{
                id: 'art_1',
                title: 'Local dashboard',
                url: 'http://127.0.0.1:9000/dashboard.html',
                preview_url: '/api/artifacts/art_1/file',
                summary_lines: ['completed']
              }}, 'http://127.0.0.1:8768/projects/proj/frames/frame'),
              artifactPreviewSameOriginAbsolute: artifacts.artifactPreviewModel({{
                id: 'art_2',
                title: 'Same-origin dashboard',
                url: 'http://127.0.0.1:9000/dashboard.html',
                preview_url: 'http://127.0.0.1:8768/api/artifacts/art_2/file',
                summary_lines: ['completed']
              }}, 'http://127.0.0.1:8768/'),
              artifactPreviewLoopbackDifferentOrigin: artifacts.artifactPreviewModel({{
                id: 'art_3',
                title: 'Different loopback dashboard',
                url: 'http://127.0.0.1:9000/dashboard.html',
                preview_url: 'http://localhost:9000/api/artifacts/art_3/file',
                summary_lines: ['completed']
              }}, 'http://127.0.0.1:8768/'),
              artifactPreviewWrongSameOriginPath: artifacts.artifactPreviewModel({{
                id: 'art_4',
                title: 'Wrong same-origin path',
                preview_url: '/api/context',
                summary_lines: ['completed']
              }}, 'http://127.0.0.1:8768/'),
              artifactPreviewMissingServerPreview: artifacts.artifactPreviewModel({{
                id: 'art_5',
                title: 'Open-only dashboard',
                url: '/api/artifacts/art_5/file',
                summary_lines: ['completed']
              }}, 'http://127.0.0.1:8768/'),
              artifactPreviewExternal: artifacts.artifactPreviewModel({{
                title: 'External dashboard',
                url: 'https://example.com/dashboard.html',
                summary_lines: ['completed']
              }}, 'http://127.0.0.1:8768/')
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )
        result = _run_node_json(self, script)

        version_url = "/api/projects/proj_1/artifacts/art_dash/versions/ver_dash/file"
        version_absolute_url = "http://127.0.0.1:8768/api/projects/proj_1/artifacts/art_dash/versions/ver_dash/file"
        self.assertEqual(result["versionedDisplay"]["url"], version_url)
        self.assertEqual(result["versionedDisplay"]["artifactUrl"], version_url)
        self.assertEqual(result["versionedDisplay"]["previewUrl"], version_url)
        self.assertEqual(result["versionedDisplay"]["latestVersionId"], "ver_dash")
        self.assertEqual(result["versionedDisplay"]["latestVersionFileUrl"], version_url)
        self.assertEqual(result["versionedDisplay"]["selectedVersionId"], "")
        self.assertEqual(result["versionedDisplay"]["selectedVersionFileUrl"], "")
        self.assertEqual(result["versionedDisplay"]["effectiveVersionId"], "ver_dash")
        self.assertEqual(result["versionedDisplay"]["effectiveVersionFileUrl"], version_url)
        self.assertTrue(result["versionedPreview"]["previewable"])
        self.assertEqual(result["versionedPreview"]["previewUrl"], version_absolute_url)
        self.assertIsNone(result["versionedProvenanceUrl"])
        self.assertEqual(result["versionedHistory"], "2 loaded versions")
        self.assertIsNone(result["versionedIds"])
        self.assertEqual(result["versionedTraceIds"], "ver_dash, ver_old")
        self.assertEqual(result["versionedTracePreviewUrl"], version_url)
        selected_version_url = "/api/projects/proj_1/artifacts/art_dash/versions/ver_old/file"
        selected_version_absolute_url = "http://127.0.0.1:8768/api/projects/proj_1/artifacts/art_dash/versions/ver_old/file"
        self.assertEqual(result["selectedVersionDisplay"]["url"], selected_version_url)
        self.assertEqual(result["selectedVersionDisplay"]["artifactUrl"], selected_version_url)
        self.assertEqual(result["selectedVersionDisplay"]["previewUrl"], selected_version_url)
        self.assertEqual(result["selectedVersionDisplay"]["latestVersionId"], "ver_dash")
        self.assertEqual(result["selectedVersionDisplay"]["latestVersionFileUrl"], version_url)
        self.assertEqual(result["selectedVersionDisplay"]["selectedVersionId"], "ver_old")
        self.assertEqual(result["selectedVersionDisplay"]["selectedVersionFileUrl"], selected_version_url)
        self.assertEqual(result["selectedVersionDisplay"]["effectiveVersionId"], "ver_old")
        self.assertEqual(result["selectedVersionDisplay"]["effectiveVersionFileUrl"], selected_version_url)
        self.assertTrue(result["selectedVersionPreview"]["previewable"])
        self.assertEqual(result["selectedVersionPreview"]["previewUrl"], selected_version_absolute_url)
        self.assertEqual(
            next(node["value"] for node in result["selectedVersionProvenance"]["nodes"] if node["label"] == "Selected version"),
            "ver_old",
        )
        self.assertNotIn("Latest version", [node["label"] for node in result["selectedVersionProvenance"]["nodes"]])
        self.assertNotIn("Effective version", [node["label"] for node in result["selectedVersionProvenance"]["nodes"]])
        selected_version_nodes = {
            node["label"]: node["value"]
            for node in next(
                section for section in result["selectedVersionRuntime"]["sections"] if section["title"] == "Artifact version"
            )["nodes"]
        }
        self.assertEqual(selected_version_nodes["Selected version"], "ver_old")
        self.assertEqual(selected_version_nodes["Effective version"], "ver_old")
        self.assertNotIn("Content type", selected_version_nodes)
        self.assertNotIn("Checksum", selected_version_nodes)
        self.assertNotIn("Size", selected_version_nodes)
        self.assertNotIn("sha256:old", result["selectedVersionReviewPayload"]["prompt_text"])
        self.assertNotIn("sha256:abc123", result["selectedVersionReviewPayload"]["prompt_text"])
        self.assertTrue(result["versionSelector"]["visible"])
        self.assertFalse(result["singleVersionSelector"]["visible"])
        self.assertEqual(result["versionSelector"]["value"], "ver_old")
        self.assertEqual(result["versionSelector"]["latestVersionId"], "ver_dash")
        self.assertEqual(result["versionSelector"]["selectedVersionId"], "ver_old")
        self.assertEqual(result["versionSelector"]["versionCount"], 2)
        self.assertEqual([item["value"] for item in result["versionSelector"]["options"]], ["ver_dash", "ver_old"])
        self.assertIn("Latest", result["versionSelector"]["options"][0]["label"])
        self.assertIn("Selected", result["versionSelector"]["options"][1]["label"])
        self.assertNotIn("ver_dash", result["versionSelector"]["options"][0]["label"])
        self.assertNotIn("ver_old", result["versionSelector"]["options"][1]["label"])
        self.assertNotIn("sha256:", result["versionSelector"]["options"][0]["label"])
        self.assertNotIn("sha256:", result["versionSelector"]["options"][1]["label"])
        self.assertEqual(result["ignoredMissingSelectedVersion"]["url"], version_url)
        self.assertEqual(result["ignoredMissingSelectedVersion"]["latestVersionId"], "ver_dash")
        self.assertEqual(result["ignoredMissingSelectedVersion"]["requestedSelectedVersionId"], "ver_missing")
        self.assertEqual(result["ignoredMissingSelectedVersion"]["selectedVersionId"], "")
        self.assertEqual(result["ignoredMissingSelectedVersion"]["resolvedSelectedVersionId"], "")
        self.assertEqual(result["ignoredMissingSelectedVersion"]["effectiveVersionId"], "ver_dash")
        self.assertEqual(
            result["unresolvedVersionOwnedDisplay"]["url"],
            "/api/projects/proj_1/artifacts/art_version_owned/versions/ver_latest/file",
        )
        self.assertEqual(result["unresolvedVersionOwnedDisplay"]["requestedSelectedVersionId"], "ver_missing")
        self.assertEqual(result["unresolvedVersionOwnedDisplay"]["selectedVersionId"], "")
        self.assertEqual(result["unresolvedVersionOwnedDisplay"]["resolvedSelectedVersionId"], "")
        self.assertEqual(result["unresolvedVersionOwnedDisplay"]["effectiveVersionId"], "ver_latest")
        self.assertIsNone(result["unresolvedVersionOwnedReview"])
        self.assertIsNone(result["unresolvedVersionOwnedReproduction"])
        self.assertEqual(result["versionOwnedEnvironment"]["status"], "ready")
        version_owned_context_nodes = {
            node["label"]: node["summary"]
            for node in next(
                section for section in result["versionOwnedEnvironment"]["sections"] if section["title"] == "Artifact context"
            )["nodes"]
        }
        self.assertEqual(version_owned_context_nodes["Family"], "Evidence report")
        self.assertEqual(version_owned_context_nodes["Category"], "Evidence")
        self.assertNotIn("evidence_packet", result["versionOwnedEnvironmentVisibleText"])
        self.assertNotIn("research.build_target_packet", result["versionOwnedEnvironmentVisibleText"])
        self.assertEqual(result["unavailableEnvironment"]["status"], "unavailable")
        self.assertEqual(result["unavailableEnvironmentTabBadge"], "")
        self.assertIn(
            ["Source status", "unavailable"],
            [[metric["label"], metric["value"]] for metric in result["unavailableEnvironment"]["metrics"]],
        )
        self.assertIn(
            "Library inventory unavailable",
            [
                node["summary"]
                for section in result["unavailableEnvironment"]["sections"]
                for node in section["nodes"]
            ],
        )
        self.assertEqual(result["unavailableEnvironmentTabBadge"], "")
        self.assertEqual(result["errorEnvironment"]["status"], "error")
        self.assertEqual(result["errorEnvironmentTabBadge"], "")
        self.assertIn(
            "Library inventory failed",
            [
                node["summary"]
                for section in result["errorEnvironment"]["sections"]
                for node in section["nodes"]
            ],
        )
        self.assertEqual(result["artifactModel"]["meta"], "completed · 1 section rendered")
        self.assertEqual(result["artifactModel"]["family"], "legacy_report")
        self.assertEqual(result["artifactModel"]["category"], "report")
        self.assertEqual(result["artifactModel"]["openLabel"], "Open report")
        self.assertEqual(result["artifactModel"]["url"], "http://127.0.0.1:9000/dashboard.html")
        self.assertEqual(result["artifactModel"]["artifactUrl"], "http://127.0.0.1:9000/dashboard.html")
        self.assertEqual(result["artifactModel"]["previewUrl"], "/api/artifacts/art_1/file")
        self.assertEqual(result["legacyEvidenceModel"]["family"], "evidence_report")
        self.assertEqual(result["legacyEvidenceModel"]["category"], "evidence")
        self.assertEqual(result["legacyEvidenceModel"]["title"], "Evidence report: rs429358")
        self.assertEqual(result["legacyEvidenceModel"]["openLabel"], "Open report")
        self.assertEqual(result["serverPresentedModel"]["family"], "evidence_report")
        self.assertEqual(result["serverPresentedModel"]["category"], "evidence")
        self.assertEqual(result["serverPresentedModel"]["title"], "Evidence packet: server-owned")
        self.assertEqual(result["serverPresentedModel"]["openLabel"], "Open server report")
        self.assertEqual(result["serverPresentedModel"]["kind"], "note")
        self.assertEqual(result["serverPresentedModel"]["renderer"], "markdown")
        self.assertEqual(result["serverPresentedCopy"]["useLabel"], "Use server report")
        self.assertEqual(result["serverPresentedCopy"]["selectedItem"], "server evidence item")
        self.assertEqual(result["serverPresentedCopy"]["selectedHeading"], "Selected server evidence")
        self.assertEqual(result["serverPresentedCopy"]["askLabel"], "Ask server report")
        self.assertEqual(result["legacyEvidenceContext"]["label"], "Evidence report: rs429358")
        self.assertIn("Selected evidence report: rs429358", result["legacyEvidenceContext"]["prompt_text"])
        self.assertEqual(result["artifactContext"]["label"], "Report: Genomi Report")
        self.assertEqual(result["artifactContext"]["source_operation"], "decode.render_dashboard")
        self.assertIn("Status: completed", result["artifactContext"]["prompt_text"])
        self.assertIn("Summary: completed · 1 section rendered", result["artifactContext"]["prompt_text"])
        self.assertNotIn("Artifact id: art_1", result["artifactContext"]["prompt_text"])
        self.assertNotIn("Renderer: decode_dashboard", result["artifactContext"]["prompt_text"])
        self.assertNotIn("Artifact URL: http://127.0.0.1:9000/dashboard.html", result["artifactContext"]["prompt_text"])
        self.assertEqual(result["artifactContextFromAlias"]["source_operation"], "decode.render_dashboard")
        _assert_public_prompt_text(result["artifactContextFromAlias"]["prompt_text"])
        self.assertEqual(result["versionedProvenance"]["title"], "Report details")
        self.assertIn("Latest version", [node["label"] for node in result["versionedProvenance"]["nodes"]])
        self.assertIn("Version history", [node["label"] for node in result["versionedProvenance"]["nodes"]])
        self.assertNotIn("Version checksum", [node["label"] for node in result["versionedProvenance"]["nodes"]])
        self.assertNotIn("Version content type", [node["label"] for node in result["versionedProvenance"]["nodes"]])
        self.assertNotIn("Version size", [node["label"] for node in result["versionedProvenance"]["nodes"]])
        self.assertNotIn("Renderer", [node["label"] for node in result["versionedProvenance"]["nodes"]])
        self.assertNotIn("Source operation", [node["label"] for node in result["versionedProvenance"]["nodes"]])
        self.assertNotIn("Version ids", [node["label"] for node in result["versionedProvenance"]["nodes"]])
        self.assertEqual(result["versionedOperationTrace"]["title"], "Operation trace")
        self.assertIn("Renderer", [node["label"] for node in result["versionedOperationTrace"]["nodes"]])
        self.assertIn("Version ids", [node["label"] for node in result["versionedOperationTrace"]["nodes"]])
        self.assertIn("Preview URL", [node["label"] for node in result["versionedOperationTrace"]["nodes"]])
        self.assertEqual(result["artifactProvenanceView"]["operationTrace"]["title"], "Operation trace")
        self.assertEqual(result["artifactProvenanceView"]["messages"]["title"], "Origin messages")
        self.assertEqual(result["artifactProvenanceView"]["environment"]["title"], "Source limits: Genomi Report")
        self.assertEqual(result["artifactProvenanceView"]["runtime"]["title"], "Source details")
        self.assertEqual(result["artifactProvenanceView"]["state"]["title"], "Report section state")
        self.assertEqual(result["artifactProvenanceView"]["technical"]["title"], "Technical details")
        self.assertEqual(result["artifactTabs"]["defaultTab"], "preview")
        self.assertEqual(
            [tab["id"] for tab in result["artifactTabs"]["tabs"]],
            ["preview", "evidence", "messages", "trace", "environment"],
        )
        self.assertEqual(
            [tab["label"] for tab in result["artifactTabs"]["tabs"]],
            [
                "Preview",
                "Report details",
                "Origin chat",
                "Work trail",
                "Source limits",
            ],
        )
        self.assertNotIn("review", [tab["id"] for tab in result["artifactTabs"]["allTabs"]])
        self.assertNotIn("review", [tab["id"] for tab in result["versionOwnedTabs"]["tabs"]])
        self.assertTrue(all(not tab["badge"] for tab in result["artifactTabs"]["tabs"]))
        self.assertTrue(all(not tab["badge"] for tab in result["versionOwnedTabs"]["tabs"]))
        self.assertEqual(result["detailHydratedEnvironment"]["title"], "Source limits: Evidence report: rs429358")
        self.assertIn("Source limits", [tab["label"] for tab in result["detailHydratedTabs"]["tabs"]])
        self.assertIn("genomi-provenance-tab-environment", [tab["testId"] for tab in result["detailHydratedTabs"]["tabs"]])
        self.assertIn("Normalizing phenotype terms", result["detailHydratedEnvironmentVisibleText"])
        self.assertIn("Not allowed from consulted sources", result["detailHydratedEnvironmentVisibleText"])
        self.assertNotIn("4 fields", result["detailHydratedEnvironmentVisibleText"])
        self.assertNotIn("0 fields", result["detailHydratedEnvironmentVisibleText"])
        self.assertEqual(
            [tab["id"] for tab in result["artifactTabs"]["secondaryTabs"]],
            ["technical"],
        )
        self.assertEqual(
            [tab["label"] for tab in result["artifactTabs"]["secondaryTabs"]],
            ["Technical details"],
        )
        self.assertIn("technical", [tab["id"] for tab in result["artifactTabs"]["allTabs"]])
        self.assertIn("genomi-provenance-tab-messages", [tab["testId"] for tab in result["artifactTabs"]["tabs"]])
        self.assertIn("genomi-provenance-tab-trace", [tab["testId"] for tab in result["artifactTabs"]["tabs"]])
        self.assertIn("genomi-provenance-tab-environment", [tab["testId"] for tab in result["artifactTabs"]["tabs"]])
        self.assertIn("genomi-provenance-tab-technical", [tab["testId"] for tab in result["artifactTabs"]["secondaryTabs"]])
        self.assertEqual(result["artifactEnvironment"]["title"], "Source limits: Genomi Report")
        self.assertEqual(result["artifactEnvironment"]["status"], "partial")
        self.assertNotIn("Genomi", [metric["label"] for metric in result["artifactEnvironment"]["metrics"]])
        self.assertNotIn("Python", [metric["label"] for metric in result["artifactEnvironment"]["metrics"]])
        self.assertNotIn("Runtime", [metric["label"] for metric in result["artifactEnvironment"]["metrics"]])
        self.assertNotIn("Assistant", [metric["label"] for metric in result["artifactEnvironment"]["metrics"]])
        self.assertIn("Source status", [metric["label"] for metric in result["artifactEnvironment"]["metrics"]])
        self.assertIn("Sources", [metric["label"] for metric in result["artifactEnvironment"]["metrics"]])
        self.assertNotIn("Installed", [metric["label"] for metric in result["artifactEnvironment"]["metrics"]])
        self.assertIn("Missing sources", [metric["label"] for metric in result["artifactEnvironment"]["metrics"]])
        self.assertIn("Manual sources", [metric["label"] for metric in result["artifactEnvironment"]["metrics"]])
        self.assertNotIn("Reproducibility summary", [section["title"] for section in result["artifactEnvironment"]["sections"]])
        self.assertIn("Artifact context", [section["title"] for section in result["artifactEnvironment"]["sections"]])
        self.assertNotIn("Result context", [section["title"] for section in result["artifactEnvironment"]["sections"]])
        self.assertIn("Source coverage", [section["title"] for section in result["artifactEnvironment"]["sections"]])
        self.assertIn("Interpretation boundary", [section["title"] for section in result["artifactEnvironment"]["sections"]])
        self.assertIn("Source inventory", [section["title"] for section in result["artifactEnvironment"]["sections"]])
        self.assertNotIn("Python packages", [section["title"] for section in result["artifactEnvironment"]["sections"]])
        self.assertNotIn("Genomi libraries", [section["title"] for section in result["artifactEnvironment"]["sections"]])
        self.assertIn("Source snapshot limits", [section["title"] for section in result["artifactEnvironment"]["sections"]])
        technical_sections = result["artifactProvenanceView"]["technical"]["sections"]
        self.assertIn("Environment details / Python packages", [section["title"] for section in technical_sections])
        self.assertIn("Environment details / Genomi libraries", [section["title"] for section in technical_sections])
        library_nodes = next(
            section for section in technical_sections if section["title"] == "Environment details / Genomi libraries"
        )["nodes"]
        self.assertIn("clinvar-grch38 · ClinVar", [node["label"] for node in library_nodes])
        clinvar_node = next(node for node in library_nodes if node["label"] == "clinvar-grch38 · ClinVar")
        self.assertIn("installed · offline", clinvar_node["summary"])
        self.assertEqual(result["selectedVersionEnvironment"]["status"], "ready")
        selected_runtime_nodes = {
            node["label"]: node["value"]
            for node in next(
                section for section in result["selectedVersionEnvironment"]["technical"]["sections"] if section["title"] == "Software environment"
            )["nodes"]
        }
        self.assertEqual(selected_runtime_nodes["Python version"], "3.13.5")
        self.assertEqual(
            next(metric["value"] for metric in result["selectedVersionEnvironment"]["metrics"] if metric["label"] == "Missing sources"),
            0,
        )
        self.assertIsNone(result["unresolvedVersionOwnedEnvironment"])
        _assert_public_payload(result["artifactEnvironment"])
        self.assertEqual(result["artifactMessages"]["title"], "Origin messages")
        self.assertNotIn("Frame", [metric["label"] for metric in result["artifactMessages"]["metrics"]])
        self.assertEqual(len(result["artifactMessages"]["sections"][0]["nodes"]), 3)
        self.assertIn("context file: [redacted local path]", result["artifactMessages"]["sections"][0]["nodes"][0]["summary"])
        self.assertIn("[redacted local path]", result["artifactMessages"]["sections"][0]["nodes"][1]["summary"])
        _assert_public_payload(result["artifactMessages"])
        self.assertEqual(result["artifactOriginContext"]["frameId"], "frame_origin")
        self.assertEqual(result["artifactOriginContext"]["messageIdsCount"], 3)
        self.assertEqual(result["artifactOriginContext"]["runIds"], ["run_1"])
        self.assertEqual(result["artifactOriginContext"]["producingRunId"], "run_1")
        self.assertEqual(result["artifactOriginContext"]["producingAssistantMessageId"], "msg_assistant")
        self.assertEqual(result["artifactOriginContext"]["summary"], "3 origin messages")
        self.assertIsNone(result["artifactOriginContextMissing"])
        self.assertIsNone(result["artifactOriginContextMessagesOnly"])
        self.assertIn("genomi-provenance-tab-evidence", [tab["testId"] for tab in result["artifactTabs"]["tabs"]])
        self.assertEqual(result["artifactRuntime"]["title"], "Source details")
        self.assertNotIn("Operation", [metric["label"] for metric in result["artifactRuntime"]["metrics"]])
        self.assertNotIn("Renderer", [metric["label"] for metric in result["artifactRuntime"]["metrics"]])
        self.assertIn("Sources", [metric["label"] for metric in result["artifactRuntime"]["metrics"]])
        self.assertIn("Origin boundary", [section["title"] for section in result["artifactRuntime"]["sections"]])
        self.assertIn("Defaults applied", [section["title"] for section in result["artifactRuntime"]["sections"]])
        self.assertIn("Source coverage", [section["title"] for section in result["artifactRuntime"]["sections"]])
        self.assertIn("Interpretation boundary", [section["title"] for section in result["artifactRuntime"]["sections"]])
        self.assertIn("Artifact version", [section["title"] for section in result["artifactRuntime"]["sections"]])
        self.assertIn("Declared runtime", [section["title"] for section in result["artifactRuntime"]["sections"]])
        _assert_public_payload(result["artifactRuntime"])
        self.assertEqual(result["artifactState"]["title"], "Report section state")
        self.assertIn("Blocked sections", [section["title"] for section in result["artifactState"]["sections"]])
        self.assertIn("Section states", [section["title"] for section in result["artifactState"]["sections"]])
        self.assertEqual(result["artifactReviewBrief"]["title"], "Artifact review summary: Genomi Report")
        self.assertIn("Review instruction", [node["label"] for node in result["artifactReviewBrief"]["nodes"]])
        self.assertIn("Report details / Latest version", [node["label"] for node in result["artifactReviewBrief"]["nodes"]])
        self.assertIn("Report details / Version history", [node["label"] for node in result["artifactReviewBrief"]["nodes"]])
        self.assertNotIn("Report details / Version checksum", [node["label"] for node in result["artifactReviewBrief"]["nodes"]])
        self.assertIn("Source detail section / Source coverage", [node["label"] for node in result["artifactReviewBrief"]["nodes"]])
        self.assertIn("State metric / Blocked", [node["label"] for node in result["artifactReviewBrief"]["nodes"]])
        self.assertIn("State section / Blocked sections", [node["label"] for node in result["artifactReviewBrief"]["nodes"]])
        self.assertEqual(result["artifactReviewPayload"]["label"], "Artifact review summary: Genomi Report")
        self.assertIn("Review this Genomi artifact using the selected review summary", result["artifactReviewPayload"]["prompt_text"])
        self.assertNotIn("sha256:abc123", result["artifactReviewPayload"]["prompt_text"])
        self.assertIn("Artifact review / Source detail section / Source coverage", result["artifactReviewPayload"]["prompt_text"])
        self.assertIn("Artifact review / State section / Blocked sections", result["artifactReviewPayload"]["prompt_text"])
        self.assertIn("ancestry", result["artifactReviewPayload"]["prompt_text"])
        self.assertIn("rare_disease: failed", result["artifactReviewPayload"]["prompt_text"])
        self.assertNotIn("[object Object]", result["artifactReviewPayload"]["prompt_text"])
        _assert_public_payload(result["artifactReviewPayload"])
        self.assertIn("Selected report: Genomi Report", result["artifactSelectedContext"]["prompt_text"])
        self.assertIn("Blocked sections / Ancestry: ancestry", result["artifactSelectedContext"]["prompt_text"])
        self.assertNotIn("Artifact URL:", result["artifactSelectedContext"]["prompt_text"])
        _assert_public_prompt_text(result["artifactSelectedContext"]["prompt_text"])
        self.assertEqual(result["artifactSelectionEmpty"]["mode"], "artifact_summary")
        self.assertEqual(result["artifactSelectionEmpty"]["totalNodes"], 2)
        self.assertEqual(result["artifactSelectionEmpty"]["selectedCount"], 0)
        self.assertEqual(result["artifactSelectionSelected"]["mode"], "selected_nodes")
        self.assertEqual(result["artifactSelectionSelected"]["totalNodes"], 3)
        self.assertEqual(result["artifactSelectionSelected"]["selectedCount"], 2)
        self.assertFalse(result["artifactPreviewLocal"]["previewable"])
        self.assertEqual(result["artifactPreviewLocal"]["reason"], "Preview is limited to Genomi result files")
        self.assertFalse(result["artifactPreviewSameOriginAbsolute"]["previewable"])
        self.assertFalse(result["artifactPreviewLoopbackDifferentOrigin"]["previewable"])
        self.assertFalse(result["artifactPreviewWrongSameOriginPath"]["previewable"])
        self.assertFalse(result["artifactPreviewMissingServerPreview"]["previewable"])
        self.assertFalse(result["artifactPreviewExternal"]["previewable"])

    def test_render_artifact_preview_view_context_uses_origin_contract(self) -> None:
        artifacts_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifacts.js").as_uri()
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

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            globalThis.window = { location: { href: 'http://127.0.0.1:8768/projects/proj_1' } };
            const copied = [];
            Object.defineProperty(globalThis, 'navigator', {
              value: { clipboard: { writeText: (text) => copied.push(text) } },
              configurable: true
            });

            const container = document.createElement('div');
            let received = null;
            const tabChanges = [];
            const artifact = {
              id: 'art_context',
              project_id: 'proj_1',
              selected_version_id: 'ver_selected',
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              title: 'Context artifact',
              status: 'completed',
              operation: 'research.build_target_packet',
              summary_lines: ['completed'],
              versions: [
                { version_id: 'ver_latest', file_url: '/api/projects/proj_1/artifacts/art_context/versions/ver_latest/file' },
                {
                  version_id: 'ver_selected',
                  file_url: '/api/projects/proj_1/artifacts/art_context/versions/ver_selected/file',
                  producing_work_step: {
                    kind: 'artifact_producing_work_step',
                    execution_cell: { id: 'run_view:artifact:9', kind: 'artifact', event_ids: [9] }
                  }
                }
              ],
              selected_version: {
                version_id: 'ver_selected',
                producing_work_step: {
                  kind: 'artifact_producing_work_step',
                  execution_cell: { id: 'run_view:artifact:9', kind: 'artifact', event_ids: [9] }
                }
              },
              origin_context: { frame_id: 'frame_origin', message_ids_count: 2, run_ids: ['run_view'] },
              provenance_messages: {
                frame_id: 'frame_messages_tab',
                total: 1,
                displayed: 1,
                messages: [{ id: 'msg_1', role: 'assistant', text: 'Bounded transcript' }]
              }
            };

            artifacts.renderArtifactPreview(container, artifact, {
              baseUrl: window.location.href,
              activeTabId: 'messages',
              onTabChange: (tabId) => { tabChanges.push(tabId); },
              onUseContext: () => {},
              onViewContext: (originContext, sourceArtifact) => {
                received = { originContext, artifactId: sourceArtifact && sourceArtifact.id };
              }
            });
            const button = container.querySelector('[data-testid="genomi-artifact-view-context"]');
            if (button) button.click();
            const copyButton = container.querySelector('[data-testid="genomi-artifact-copy-link"]');
            if (copyButton) copyButton.click();
            const actionMenu = container.querySelector('[data-testid="genomi-artifact-actions-menu"]');
            const menuLabels = Array.from(container.querySelectorAll('.artifact-menu-item')).map((item) => item.textContent);
            const evidenceButton = container.querySelector('[data-testid="genomi-artifact-menu-evidence"]');
            const technicalButton = container.querySelector('[data-testid="genomi-artifact-menu-technical"]');
            const metadataButton = container.querySelector('[data-testid="genomi-artifact-copy-metadata"]');
            const messagesTab = container.querySelector('[data-testid="genomi-provenance-tab-messages"]');
            const messagesPanel = container.querySelector('[data-artifact-panel="messages"]');
            const messagesTabActiveBeforeClick = messagesTab ? messagesTab.classList.contains('active') : false;
            const messagesPanelVisibleBeforeClick = messagesPanel ? messagesPanel.hidden === false : false;
            const historyChips = Array.from(container.querySelectorAll('[data-testid="genomi-artifact-history-chip"]'));
            const historyChipText = historyChips.map((item) => {
              const strong = item.querySelector('strong');
              const span = item.querySelector('span');
              return [strong && strong.textContent, span && span.textContent].filter(Boolean).join(': ');
            });
            const evidenceTab = container.querySelector('[data-testid="genomi-provenance-tab-evidence"]');
            const versionHistoryChip = historyChips.find((item) => item.textContent.includes('Versions'));
            const versionHistoryChipByChildren = historyChips.find((item) => {
              const strong = item.querySelector('strong');
              return strong && strong.textContent === 'Versions';
            });
            const versionChip = versionHistoryChip || versionHistoryChipByChildren;
            if (versionChip) versionChip.click();
            const evidenceTabActiveAfterHistoryClick = evidenceTab ? evidenceTab.classList.contains('active') : false;
            if (evidenceButton) evidenceButton.click();
            const evidenceTabActiveAfterEvidenceClick = evidenceTab ? evidenceTab.classList.contains('active') : false;
            if (copyButton) copyButton.click();
            if (technicalButton) technicalButton.click();
            const technicalPanel = container.querySelector('[data-artifact-panel="technical"]');
            const copiedLinks = copied.slice();
            if (metadataButton) metadataButton.click();
            const copiedMetadata = copied[copied.length - 1] || '';
            process.stdout.write(JSON.stringify({
              hasActionMenu: Boolean(actionMenu),
              menuLabels,
              hasEvidenceButton: Boolean(evidenceButton),
              hasTechnicalButton: Boolean(technicalButton),
              hasMetadataButton: Boolean(metadataButton),
              hasButton: Boolean(button),
              buttonText: button ? button.textContent : '',
              buttonCount: container.querySelectorAll('[data-testid="genomi-artifact-view-context"]').length,
              hasCopyButton: Boolean(copyButton),
              copyButtonText: copyButton ? copyButton.textContent : '',
              copyButtonUrl: copyButton ? copyButton.dataset.workspaceUrl : '',
              messagesTabActiveBeforeClick,
              messagesPanelVisibleBeforeClick,
              hasHistory: Boolean(container.querySelector('[data-testid="genomi-artifact-history"]')),
              historyChipText,
              evidenceTabActiveAfterHistoryClick,
              evidenceTabActiveAfterEvidenceClick,
              technicalPanelVisibleAfterClick: technicalPanel ? technicalPanel.hidden === false : false,
              visiblePrimaryTabLabels: Array.from(container.querySelectorAll('.artifact-provenance-tabs .artifact-tab')).map((item) => item.textContent),
              tabChanges,
              copiedLinks,
              copiedMetadata,
              received,
              messagesFrame: artifacts.artifactMessagesModel(artifact).frame_id
            }));
            """
        ).replace("__ARTIFACTS_URL__", json.dumps(artifacts_url))

        result = _run_node_json(self, script)

        self.assertTrue(result["hasActionMenu"])
        self.assertNotIn("Use review summary", result["menuLabels"])
        self.assertIn("View in chat", result["menuLabels"])
        self.assertNotIn("Open evidence report details", result["menuLabels"])
        self.assertIn("Advanced technical details", result["menuLabels"])
        self.assertNotIn("Open provenance", result["menuLabels"])
        self.assertIn("Copy link", result["menuLabels"])
        self.assertIn("Copy technical metadata", result["menuLabels"])
        self.assertIn("Open report", result["menuLabels"])
        self.assertFalse(result["hasEvidenceButton"])
        self.assertTrue(result["hasTechnicalButton"])
        self.assertTrue(result["hasMetadataButton"])
        self.assertTrue(result["hasButton"])
        self.assertEqual(result["buttonText"], "View in chat")
        self.assertEqual(result["buttonCount"], 1)
        self.assertTrue(result["hasCopyButton"])
        self.assertEqual(result["copyButtonText"], "Copy link")
        self.assertEqual(
            result["copyButtonUrl"],
            "http://127.0.0.1:8768/projects/proj_1/artifacts/art_context/versions/ver_selected?artifact_tab=messages",
        )
        self.assertTrue(result["messagesTabActiveBeforeClick"])
        self.assertTrue(result["messagesPanelVisibleBeforeClick"])
        self.assertFalse(result["hasHistory"])
        self.assertEqual(result["historyChipText"], [])
        self.assertFalse(result["evidenceTabActiveAfterHistoryClick"])
        self.assertFalse(result["evidenceTabActiveAfterEvidenceClick"])
        self.assertTrue(result["technicalPanelVisibleAfterClick"])
        self.assertFalse(any("Technical details" in label for label in result["visiblePrimaryTabLabels"]))
        self.assertEqual(result["tabChanges"], ["technical"])
        self.assertEqual(
            result["copiedLinks"],
            [
                "http://127.0.0.1:8768/projects/proj_1/artifacts/art_context/versions/ver_selected?artifact_tab=messages",
                "http://127.0.0.1:8768/projects/proj_1/artifacts/art_context/versions/ver_selected?artifact_tab=messages",
            ],
        )
        self.assertIn('"artifact_id": "art_context"', result["copiedMetadata"])
        self.assertIn('"effective_version_id": "ver_selected"', result["copiedMetadata"])
        self.assertEqual(result["messagesFrame"], "frame_messages_tab")
        self.assertEqual(result["received"]["artifactId"], "art_context")
        self.assertEqual(result["received"]["originContext"]["frameId"], "frame_origin")
        self.assertEqual(result["received"]["originContext"]["messageIdsCount"], 2)
        self.assertEqual(result["received"]["originContext"]["runIds"], ["run_view"])
        self.assertEqual(result["received"]["originContext"]["producingRunId"], "")
        self.assertEqual(result["received"]["originContext"]["producingAssistantMessageId"], "")
        self.assertEqual(result["received"]["originContext"]["producingStepId"], "run_view:artifact:9")

    def test_artifact_messages_model_caps_and_sanitizes_transcript(self) -> None:
        messages_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifact_messages.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const messagesModule = await import({messages_url!r});
            const messages = Array.from({{ length: 55 }}, (_item, index) => ({{
              id: 'msg_' + index,
              role: index % 2 ? 'tool' : 'assistant',
              text: index === 0 ? 'Uses context_file=/Users/matthewzmd/.genomi/private.json' : '',
              event: {{
                type: 'tool_result',
                name: 'variant.resolve',
                content: 'result from /tmp/private-' + index + '.sqlite',
                payload: {{
                  nested: {{
                    agi_path: '/Users/matthewzmd/.genomi/raw-' + index + '.sqlite',
                    full: {{ arbitrary: true }}
                  }}
                }},
                ledger: {{
                  status: 'completed',
                  summary: 'variant.resolve completed from /usr/local/bin/tool'
                }}
              }},
              created_at: '2026-07-01T12:00:00.000Z'
            }}));
            const model = messagesModule.artifactMessagesModel({{
              provenance_messages: {{
                frame_id: 'frame_big',
                total: messages.length,
                messages
              }}
            }}, {{ displayLimit: 10 }});
            process.stdout.write(JSON.stringify({{
              title: model.title,
              total: model.total,
              displayed: model.displayed,
              hasMore: model.has_more,
              displayLimit: model.display_limit,
              nodeCount: model.sections[0].nodes.length,
              firstSummary: model.sections[0].nodes[0].summary,
              secondLabel: model.sections[0].nodes[1].label,
              secondValue: model.sections[0].nodes[1].value,
              serialized: JSON.stringify(model)
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["title"], "Origin messages")
        self.assertEqual(result["total"], 55)
        self.assertEqual(result["displayed"], 10)
        self.assertTrue(result["hasMore"])
        self.assertEqual(result["displayLimit"], 10)
        self.assertEqual(result["nodeCount"], 10)
        self.assertIn("context file: [redacted local path]", result["firstSummary"])
        self.assertEqual(result["secondLabel"], "2. Tool / Variant lookup")
        self.assertNotIn("id", result["secondValue"])
        self.assertNotIn("run_id", result["secondValue"])
        self.assertNotIn("event", result["secondValue"])
        self.assertEqual(result["secondValue"]["work_step"], "Variant lookup")
        self.assertEqual(result["secondValue"]["work_status"], "completed")
        self.assertNotIn("arbitrary", result["serialized"])
        _assert_public_payload(json.loads(result["serialized"]))


def _run_node_json(test_case: unittest.TestCase, script: str):
    node = shutil_which_node()
    test_case.assertIsNotNone(node, "node is required for frontend asset tests")
    completed = subprocess.run(
        [str(node), "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def shutil_which_node() -> str | None:
    import shutil

    return shutil.which("node")


def _assert_public_prompt_text(text: str) -> None:
    assert not _PRIVATE_PROMPT_RE.search(text), text
    assert "[redacted local path]" in text or "context_file" not in text, text


def _assert_public_payload(value) -> None:
    encoded = json.dumps(value, sort_keys=True)
    assert not _PRIVATE_PROMPT_RE.search(encoded), encoded
