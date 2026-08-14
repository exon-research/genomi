from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


class PortalFrontendArtifactProjectionTests(unittest.TestCase):
    def test_panel_models_share_selected_version_source_details(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for frontend module tests")
        template_root = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"
        environment_url = (template_root / "portal_artifact_environment_model.js").as_uri()
        runtime_url = (template_root / "portal_artifact_runtime_model.js").as_uri()
        reproduction_url = (template_root / "portal_artifact_reproduction_model.js").as_uri()
        script = textwrap.dedent(
            f"""
            const environmentModels = await import({environment_url!r});
            const runtimeModels = await import({runtime_url!r});
            const reproductionModels = await import({reproduction_url!r});
            const latestEnvironment = environmentSnapshot('3.14.3', 1);
            const oldEnvironment = environmentSnapshot('3.13.5', 0);
            const latestSummary = sourceSummary('Latest Source', 'GRCh38', 'latest_only');
            const oldSummary = sourceSummary('Selected Old Source', 'GRCh37', 'old_only');
            const latestReview = review('passed');
            const oldReview = review('warning');
            const latestRecipe = recipe('ready', 'latest');
            const oldRecipe = recipe('ready', 'old');
            const artifact = {{
              id: 'art_versions',
              project_id: 'proj_1',
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              title: 'Evidence report: rs429358',
              status: 'completed',
              operation: 'research.build_target_packet',
              summary: latestSummary,
              environment: latestEnvironment,
              review: latestReview,
              reproduction: latestRecipe,
              latest_version_id: 'ver_latest',
              versions_loaded: true,
              latest_version: {{
                version_id: 'ver_latest',
                project_id: 'proj_1',
                artifact_id: 'art_versions',
                summary: latestSummary,
                environment: latestEnvironment,
                review: latestReview,
                reproduction: latestRecipe
              }},
              versions: [
                {{
                  version_id: 'ver_latest',
                  project_id: 'proj_1',
                  artifact_id: 'art_versions',
                  summary: latestSummary,
                  environment: latestEnvironment,
                  review: latestReview,
                  reproduction: latestRecipe
                }},
                {{
                  version_id: 'ver_old',
                  project_id: 'proj_1',
                  artifact_id: 'art_versions',
                  summary: oldSummary,
                  environment: oldEnvironment,
                  review: oldReview,
                  reproduction: oldRecipe
                }}
              ]
            }};
            const selected = {{ ...artifact, selected_version_id: 'ver_old' }};
            const selectedEnvironment = environmentModels.artifactEnvironmentModel(selected);
            const selectedRuntime = runtimeModels.artifactRuntimeModel(selected);
            const selectedReview = runtimeModels.artifactReviewStateModel(selected);
            const selectedReviewPayload = runtimeModels.artifactReviewBriefPayload(selected);
            const selectedReproduction = reproductionModels.artifactReproductionModel(selected);
            process.stdout.write(JSON.stringify({{
              environmentText: visiblePanelText(selectedEnvironment),
              runtimeText: visiblePanelText(selectedRuntime),
              reviewStatus: selectedReview && selectedReview.status,
              reviewPrompt: selectedReviewPayload.prompt_text,
              reproductionStatus: selectedReproduction && selectedReproduction.status
            }}));

            function sourceSummary(sourceTitle, genomeBuild, sourceId) {{
              return {{
                defaults_applied: [{{ parameter: 'genome_build', source: 'tool_default', value: genomeBuild }}],
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
                      source_id: sourceId,
                      title: sourceTitle,
                      best_for: sourceTitle + ' source coverage'
                    }}
                  ]
                }}
              }};
            }}

            function environmentSnapshot(pythonVersion, missingCount) {{
              return {{
                kind: 'artifact_environment_snapshot',
                status: missingCount ? 'partial' : 'ready',
                runtime: {{ python_version: pythonVersion, python_implementation: 'CPython' }},
                libraries: {{
                  summary: {{
                    library_count: 1,
                    installed_count: missingCount ? 0 : 1,
                    missing_count: missingCount,
                    manual_source_required_count: 0,
                    not_applicable_count: 0
                  }},
                  items: []
                }},
                packages: [],
                limitations: []
              }};
            }}

            function review(status) {{
              return {{
                kind: 'artifact_version_review',
                status,
                check_count: 1,
                counts: {{ passed: status === 'passed' ? 1 : 0, warning: status === 'warning' ? 1 : 0, failed: 0 }},
                checks: [{{ title: 'Version source check', status, severity: status, summary: status + ' selected version' }}],
                limitations: []
              }};
            }}

            function recipe(status, label) {{
              return {{
                status,
                kind: 'operation_rebuild_recipe',
                artifact_family: 'evidence_report',
                operation: 'research.build_target_packet',
                renderer: 'evidence_packet',
                params: {{ target_type: 'topic', topic: 'rs429358', label }},
                params_redacted: false,
                commands: [],
                limitations: []
              }};
            }}

            function visiblePanelText(model) {{
              return JSON.stringify(model).replace(/\\s+/g, ' ');
            }}
            """
        )

        result = _run_node_json(self, script)

        self.assertIn("3.13.5", result["environmentText"])
        self.assertIn("GRCh37", result["environmentText"])
        self.assertIn("Selected Old Source", result["environmentText"])
        self.assertIn("Evidence present", result["environmentText"])
        self.assertIn("Scoped answer only", result["environmentText"])
        self.assertNotIn("3.14.3", result["environmentText"])
        self.assertNotIn("GRCh38", result["environmentText"])
        self.assertNotIn("Latest Source", result["environmentText"])
        self.assertNotIn("evidence_present", result["environmentText"])
        self.assertNotIn("scoped_answer_only", result["environmentText"])
        self.assertIn("Selected Old Source", result["runtimeText"])
        self.assertNotIn("Latest Source", result["runtimeText"])
        self.assertEqual(result["reviewStatus"], "warning")
        self.assertIn("Selected Old Source", result["reviewPrompt"])
        self.assertNotIn("Latest Source", result["reviewPrompt"])
        self.assertEqual(result["reproductionStatus"], "ready")

    def test_panel_models_use_artifact_fallback_only_without_explicit_selection(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for frontend module tests")
        template_root = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"
        environment_url = (template_root / "portal_artifact_environment_model.js").as_uri()
        runtime_url = (template_root / "portal_artifact_runtime_model.js").as_uri()
        reproduction_url = (template_root / "portal_artifact_reproduction_model.js").as_uri()
        script = textwrap.dedent(
            f"""
            const environmentModels = await import({environment_url!r});
            const runtimeModels = await import({runtime_url!r});
            const reproductionModels = await import({reproduction_url!r});
            const artifactLevel = {{
              id: 'art_detail',
              project_id: 'proj_1',
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              title: 'Evidence report: rs429358',
              status: 'completed',
              operation: 'research.build_target_packet',
              summary: {{
                source_catalog: {{
                  summary: {{ source_count: 1 }},
                  sources: [{{ source_id: 'artifact_source', title: 'Artifact Source', best_for: 'artifact fallback' }}]
                }}
              }},
              environment: {{
                kind: 'artifact_environment_snapshot',
                status: 'ready',
                runtime: {{ python_version: '3.12.1' }},
                libraries: {{ summary: {{ library_count: 1, installed_count: 1, missing_count: 0, manual_source_required_count: 0, not_applicable_count: 0 }}, items: [] }},
                packages: [],
                limitations: []
              }},
              review: {{
                kind: 'artifact_version_review',
                status: 'passed',
                counts: {{ passed: 1, warning: 0, failed: 0 }},
                checks: [{{ title: 'Artifact fallback review', status: 'passed', summary: 'artifact fallback review' }}],
                limitations: []
              }},
              reproduction: {{
                status: 'ready',
                kind: 'operation_rebuild_recipe',
                artifact_family: 'evidence_report',
                operation: 'research.build_target_packet',
                renderer: 'evidence_packet',
                params: {{ target_type: 'topic', topic: 'rs429358' }},
                params_redacted: false,
                commands: [],
                limitations: []
              }},
              latest_version_id: 'ver_latest',
              versions_loaded: true,
              latest_version: {{ version_id: 'ver_latest', project_id: 'proj_1', artifact_id: 'art_detail' }},
              versions: [{{ version_id: 'ver_latest', project_id: 'proj_1', artifact_id: 'art_detail' }}]
            }};
            const unresolved = {{
              ...artifactLevel,
              selected_version_id: 'ver_missing',
              versions_loaded: false
            }};
            process.stdout.write(JSON.stringify({{
              fallbackEnvironmentStatus: environmentModels.artifactEnvironmentModel(artifactLevel)?.status,
              fallbackReviewStatus: runtimeModels.artifactReviewStateModel(artifactLevel)?.status,
              fallbackReproductionStatus: reproductionModels.artifactReproductionModel(artifactLevel)?.status,
              fallbackRuntimeText: JSON.stringify(runtimeModels.artifactRuntimeModel(artifactLevel)),
              unresolvedEnvironment: environmentModels.artifactEnvironmentModel(unresolved),
              unresolvedReview: runtimeModels.artifactReviewStateModel(unresolved),
              unresolvedReproduction: reproductionModels.artifactReproductionModel(unresolved)
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["fallbackEnvironmentStatus"], "ready")
        self.assertEqual(result["fallbackReviewStatus"], "passed")
        self.assertEqual(result["fallbackReproductionStatus"], "ready")
        self.assertIn("Artifact Source", result["fallbackRuntimeText"])
        self.assertIsNone(result["unresolvedEnvironment"])
        self.assertIsNone(result["unresolvedReview"])
        self.assertIsNone(result["unresolvedReproduction"])


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
