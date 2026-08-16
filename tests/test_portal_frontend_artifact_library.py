from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


class PortalFrontendArtifactLibraryTests(unittest.TestCase):
    def test_artifact_library_model_filters_searches_and_tracks_layout(self) -> None:
        model_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_artifact_library_model.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const library = await import({model_url!r});
            const artifacts = [
              {{
                id: 'art_evidence',
                project_id: 'proj_1',
                kind: 'evidence_packet',
                renderer: 'evidence_packet',
                title: 'Evidence report: rs429358',
                operation: 'research.build_target_packet',
                summary_lines: ['evidence_present', '20 sources'],
                preview_url: '/api/projects/proj_1/artifacts/art_evidence/file',
                starred: true,
                origin_context: {{ frame_id: 'frame_1', run_ids: ['run_1'] }}
              }},
              {{
                id: 'art_dashboard',
                project_id: 'proj_1',
                kind: 'decode_dashboard',
                renderer: 'decode_dashboard',
                title: 'Decode dashboard',
                operation: 'decode.render_dashboard',
                summary_lines: ['completed'],
                preview_url: '/api/projects/proj_1/artifacts/art_dashboard/file',
                origin_context: {{ frame_id: 'frame_1', run_ids: ['run_1'] }}
              }},
              {{
                id: 'art_file',
                project_id: 'proj_1',
                kind: 'project_file',
                renderer: 'project_file',
                title: 'lab-notes.csv',
                operation: 'portal.import_file',
                summary_lines: ['Imported file', 'lab-notes.csv'],
                latest_version: {{
                  version_id: 'ver_file',
                  project_id: 'proj_1',
                  artifact_id: 'art_file',
                  content_type: 'text/csv'
                }}
              }},
              {{
                id: 'art_note',
                project_id: 'proj_1',
                kind: 'note',
                renderer: 'markdown',
                title: 'Lab note',
                status: 'completed',
                summary_lines: ['plain markdown note'],
                hidden: true
              }}
            ];
            const baseUrl = 'http://127.0.0.1:8767/projects/proj_1';
            const all = library.artifactLibraryModel(artifacts, {{ baseUrl }});
            const query = library.artifactLibraryModel(artifacts, {{ baseUrl, query: 'rs429358 sources' }});
            const evidence = library.artifactLibraryModel(artifacts, {{ baseUrl, filter: 'evidence' }});
            const starred = library.artifactLibraryModel(artifacts, {{ baseUrl, filter: 'starred' }});
            const previewable = library.artifactLibraryModel(artifacts, {{ baseUrl, filter: 'previewable' }});
            const hidden = library.artifactLibraryModel(artifacts, {{ baseUrl, filter: 'hidden' }});
            const files = library.artifactLibraryModel(artifacts, {{ baseUrl, filter: 'file' }});
            const compact = library.artifactLibraryModel(artifacts, {{ baseUrl, layout: 'compact' }});
            const standalone = library.artifactRecordsOutsideWorkspaceFiles(artifacts, {{
              files: [{{ relative_path: 'lab-notes.csv', artifact_id: null }}]
            }});
            process.stdout.write(JSON.stringify({{
              all,
              allIds: all.artifacts.map((artifact) => artifact.id),
              queryIds: query.artifacts.map((artifact) => artifact.id),
              evidenceIds: evidence.artifacts.map((artifact) => artifact.id),
              starredIds: starred.artifacts.map((artifact) => artifact.id),
              previewableIds: previewable.artifacts.map((artifact) => artifact.id),
              hiddenIds: hidden.artifacts.map((artifact) => artifact.id),
              fileIds: files.artifacts.map((artifact) => artifact.id),
              filterLabels: Object.fromEntries(all.filters.map((item) => [item.key, item.label])),
              allGroups: all.groups.map((group) => [group.key, group.label, group.summary, group.artifacts.map((artifact) => artifact.id)]),
              fileGroups: files.groups.map((group) => [group.key, group.label, group.summary, group.artifacts.map((artifact) => artifact.id)]),
              hiddenGroups: hidden.groups.map((group) => [group.key, group.label, group.summary, group.artifacts.map((artifact) => artifact.id)]),
              compactLayout: compact.layout,
              activeLayoutLabels: compact.layouts.filter((item) => item.active).map((item) => item.label),
              standaloneIds: standalone.map((artifact) => artifact.id)
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["all"]["totalCount"], 4)
        self.assertEqual(result["all"]["shownCount"], 3)
        self.assertEqual(result["all"]["summary"], "3 of 4 items")
        self.assertEqual(
            {item["key"]: item["count"] for item in result["all"]["filters"]},
            {"all": 3, "starred": 1, "previewable": 3, "hidden": 1, "evidence": 1, "report": 1, "file": 1, "other": 0},
        )
        self.assertEqual(result["allIds"], ["art_evidence", "art_dashboard", "art_file"])
        self.assertEqual(result["queryIds"], ["art_evidence"])
        self.assertEqual(result["evidenceIds"], ["art_evidence"])
        self.assertEqual(result["starredIds"], ["art_evidence"])
        self.assertEqual(result["previewableIds"], ["art_evidence", "art_dashboard", "art_file"])
        self.assertEqual(result["hiddenIds"], ["art_note"])
        self.assertEqual(result["fileIds"], ["art_file"])
        self.assertEqual(result["filterLabels"]["report"], "Reports")
        self.assertEqual(
            result["allGroups"],
            [
                ["uploads", "Your uploads", "1 uploaded file", ["art_file"]],
                ["generated_turn_1", "Created in assistant turn", "2 artifacts from this assistant turn", ["art_evidence", "art_dashboard"]],
            ],
        )
        self.assertEqual(result["fileGroups"], [["uploads", "Your uploads", "1 uploaded file", ["art_file"]]])
        self.assertEqual(result["hiddenGroups"], [["hidden", "Hidden items", "1 hidden item", ["art_note"]]])
        self.assertEqual(result["compactLayout"], "compact")
        self.assertEqual(result["activeLayoutLabels"], ["Compact"])
        self.assertEqual(result["standaloneIds"], ["art_evidence", "art_dashboard", "art_note"])

    def test_artifact_action_menu_model_exposes_object_actions(self) -> None:
        actions_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_artifact_actions.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const actions = await import({actions_url!r});
            __DOM_SHIM__

            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            globalThis.window = {{ location: {{ href: 'http://127.0.0.1:8767/projects/proj_1' }} }};
            const readyReproduction = {{
              status: 'ready',
              kind: 'operation_rebuild_recipe',
              operation: 'research.build_target_packet',
              renderer: 'evidence_packet',
              params: {{ target_type: 'topic', topic: 'rs429358' }},
              params_redacted: false,
              script: 'genomi call research.build_target_packet --params "{{}}"',
              commands: [{{ label: 'Genomi operation', language: 'shell', command: 'genomi call research.build_target_packet --params "{{}}"' }}],
              limitations: []
            }};
            const redactedReproduction = {{
              ...readyReproduction,
              status: 'partial_private_parameters_redacted',
              params_redacted: true,
              script: ''
            }};
            const versionReview = {{
              kind: 'artifact_version_review',
              status: 'warning',
              generated_at: '2026-07-04T10:00:00Z',
              check_count: 2,
              counts: {{ passed: 1, warning: 1, failed: 0, not_applicable: 0 }},
              checks: [
                {{ check_id: 'artifact_file_snapshot', title: 'Artifact file snapshot', status: 'passed', severity: 'info', summary: 'Immutable artifact file metadata is attached.' }},
                {{ check_id: 'rebuild_recipe', title: 'Rebuild recipe', status: 'warning', severity: 'warning', summary: 'Private parameters were redacted.' }}
              ]
            }};
            const baseArtifact = {{
              id: 'art_1',
              project_id: 'proj_1',
              title: 'Evidence report',
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              latest_version_id: 'ver_1',
              latest_version: {{ version_id: 'ver_1', reproduction: readyReproduction, review: versionReview }},
              versions: [{{ version_id: 'ver_1', reproduction: readyReproduction, review: versionReview }}],
              versions_loaded: true,
              url: '/api/projects/proj_1/artifacts/art_1/file',
              preview_url: '/api/projects/proj_1/artifacts/art_1/file'
            }};
            const redactedArtifact = {{
              ...baseArtifact,
              id: 'art_private',
              latest_version: {{ version_id: 'ver_private', reproduction: redactedReproduction }},
              versions: [{{ version_id: 'ver_private', reproduction: redactedReproduction }}]
            }};
            const runningArtifact = {{
              ...baseArtifact,
              latest_version: {{
                ...baseArtifact.latest_version,
                review: {{
                  ...versionReview,
                  review_runs: [
                    {{
                      kind: 'artifact_review_run',
                      review_run_id: 'pending',
                      status: 'running',
                      check_status: 'running',
                      started_at: '2026-07-04T12:00:00Z',
                      version_id: 'ver_1',
                      summary: 'Review checks are running for this artifact version.'
                    }}
                  ]
                }}
              }},
              versions: [{{
                ...baseArtifact.versions[0],
                review: {{
                  ...versionReview,
                  review_runs: [
                    {{
                      kind: 'artifact_review_run',
                      review_run_id: 'pending',
                      status: 'running',
                      check_status: 'running',
                      started_at: '2026-07-04T12:00:00Z',
                      version_id: 'ver_1',
                      summary: 'Review checks are running for this artifact version.'
                    }}
                  ]
                }}
              }}]
            }};
            const requestedActions = [];
            const requestedReviewRuns = [];
            const onArtifactAction = (_artifact, request) => requestedActions.push(request.action);
            const onArtifactReviewRun = (artifact) => requestedReviewRuns.push(artifact.id);
            const visibleModel = actions.artifactActionMenuModel({{
              artifact: baseArtifact,
              options: {{ onArtifactAction, onArtifactReviewRun, baseUrl: 'http://127.0.0.1:8767/projects/proj_1' }}
            }});
            const alreadyMarkedModel = actions.artifactActionMenuModel({{
              artifact: {{ ...baseArtifact, starred: true, hidden: true }},
              options: {{ onArtifactAction, baseUrl: 'http://127.0.0.1:8767/projects/proj_1' }}
            }});
            const visible = visibleModel.map((action) => [action.id, action.label, action.testId]);
            const alreadyMarked = alreadyMarkedModel.map((action) => [action.id, action.label, action.testId]);
            const visibleById = Object.fromEntries(visibleModel.map((action) => [action.id, action]));
            const markedById = Object.fromEntries(alreadyMarkedModel.map((action) => [action.id, action]));
            visibleById.star.run();
            visibleById.hide.run();
            visibleById.rename.run();
            visibleById.delete.run();
            visibleById.run_review_checks.run();
            markedById.star.run();
            markedById.hide.run();
            const stateActionChecks = ['star', 'unstar', 'hide', 'unhide', 'rename', 'delete'].map((action) => [
              action,
              actions.isArtifactStateAction(action)
            ]);
            const rendered = actions.renderArtifactActionMenu({{
              artifact: baseArtifact,
              options: {{ onArtifactAction, onArtifactReviewRun, baseUrl: 'http://127.0.0.1:8767/projects/proj_1' }}
            }});
            const renderedExport = rendered.querySelector('[data-testid="genomi-artifact-export-metadata"]');
            const renderedReviewRun = rendered.querySelector('[data-testid="genomi-artifact-run-review-checks"]');
            const renderedScript = rendered.querySelector('[data-testid="genomi-artifact-download-script-bundle"]');
            const renderedBundle = rendered.querySelector('[data-testid="genomi-artifact-download-bundle"]');
            const renderedOpen = rendered.querySelector('[data-testid="genomi-artifact-open"]');
            const redactedModel = actions.artifactActionMenuModel({{
              artifact: redactedArtifact,
              options: {{ baseUrl: 'http://127.0.0.1:8767/projects/proj_1' }}
            }});
            const runningReviewAction = actions.artifactActionMenuModel({{
              artifact: runningArtifact,
              options: {{ onArtifactReviewRun, baseUrl: 'http://127.0.0.1:8767/projects/proj_1' }}
            }}).find((action) => action.id === 'run_review_checks');
            process.stdout.write(JSON.stringify({{
              visible,
              alreadyMarked,
              requestedActions,
              requestedReviewRuns,
              stateActionChecks,
              exportMetadata: {{
                href: visibleById.export_metadata.href,
                kind: visibleById.export_metadata.kind,
                hasDownload: Object.prototype.hasOwnProperty.call(visibleById.export_metadata, 'download')
              }},
              downloadBundle: {{
                href: visibleById.download_bundle.href,
                kind: visibleById.download_bundle.kind,
                hasDownload: Object.prototype.hasOwnProperty.call(visibleById.download_bundle, 'download')
              }},
              downloadScriptBundle: {{
                href: visibleById.download_script_bundle.href,
                kind: visibleById.download_script_bundle.kind,
                hasDownload: Object.prototype.hasOwnProperty.call(visibleById.download_script_bundle, 'download')
              }},
              renderedExport: {{
                tagName: renderedExport.tagName,
                href: renderedExport.href,
                target: renderedExport.target || '',
                rel: renderedExport.rel || '',
                download: renderedExport.download || ''
              }},
              renderedReviewRun: {{
                tagName: renderedReviewRun.tagName,
                textContent: renderedReviewRun.textContent,
                type: renderedReviewRun.type || ''
              }},
              renderedScript: {{
                tagName: renderedScript.tagName,
                href: renderedScript.href,
                target: renderedScript.target || '',
                rel: renderedScript.rel || '',
                download: renderedScript.download || ''
              }},
              renderedBundle: {{
                tagName: renderedBundle.tagName,
                href: renderedBundle.href,
                target: renderedBundle.target || '',
                rel: renderedBundle.rel || '',
                download: renderedBundle.download || ''
              }},
              renderedOpen: {{
                tagName: renderedOpen.tagName,
                href: renderedOpen.href,
                target: renderedOpen.target || '',
                rel: renderedOpen.rel || '',
                download: renderedOpen.download || ''
              }},
              redactedActionIds: redactedModel.map((action) => action.id),
              runningReviewAction: {{
                label: runningReviewAction.label,
                disabled: runningReviewAction.disabled,
                hasRunHandler: typeof runningReviewAction.run === 'function'
              }}
            }}));
            """
        ).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertIn(["star", "Star", "genomi-artifact-toggle-star"], result["visible"])
        self.assertIn(["rename", "Rename", "genomi-artifact-rename"], result["visible"])
        self.assertIn(["hide", "Hide", "genomi-artifact-toggle-hidden"], result["visible"])
        self.assertIn(["run_review_checks", "Run review checks", "genomi-artifact-run-review-checks"], result["visible"])
        self.assertIn(["export_metadata", "Download technical metadata", "genomi-artifact-export-metadata"], result["visible"])
        self.assertIn(["download_script_bundle", "Download rebuild script", "genomi-artifact-download-script-bundle"], result["visible"])
        self.assertIn(["download_bundle", "Download artifact bundle", "genomi-artifact-download-bundle"], result["visible"])
        self.assertIn(["delete", "Delete", "genomi-artifact-delete"], result["visible"])
        self.assertEqual(
            result["runningReviewAction"],
            {"label": "Checking review...", "disabled": True, "hasRunHandler": False},
        )
        self.assertIn(["star", "Unstar", "genomi-artifact-toggle-star"], result["alreadyMarked"])
        self.assertIn(["hide", "Unhide", "genomi-artifact-toggle-hidden"], result["alreadyMarked"])
        self.assertEqual(result["requestedActions"], ["star", "hide", "rename", "delete", "unstar", "unhide"])
        self.assertEqual(result["requestedReviewRuns"], ["art_1"])
        self.assertEqual(
            result["exportMetadata"],
            {
                "href": "http://127.0.0.1:8767/api/projects/proj_1/artifacts/art_1/metadata",
                "kind": "download",
                "hasDownload": False,
            },
        )
        self.assertEqual(
            result["downloadBundle"],
            {
                "href": "http://127.0.0.1:8767/api/projects/proj_1/artifacts/art_1/bundle",
                "kind": "download",
                "hasDownload": False,
            },
        )
        self.assertEqual(
            result["downloadScriptBundle"],
            {
                "href": "http://127.0.0.1:8767/api/projects/proj_1/artifacts/art_1/versions/ver_1/script-bundle",
                "kind": "download",
                "hasDownload": False,
            },
        )
        self.assertEqual(
            result["renderedExport"],
            {
                "tagName": "a",
                "href": "http://127.0.0.1:8767/api/projects/proj_1/artifacts/art_1/metadata",
                "target": "",
                "rel": "",
                "download": "",
            },
        )
        self.assertEqual(
            result["renderedBundle"],
            {
                "tagName": "a",
                "href": "http://127.0.0.1:8767/api/projects/proj_1/artifacts/art_1/bundle",
                "target": "",
                "rel": "",
                "download": "",
            },
        )
        self.assertEqual(
            result["renderedReviewRun"],
            {
                "tagName": "button",
                "textContent": "Run review checks",
                "type": "button",
            },
        )
        self.assertEqual(
            result["renderedScript"],
            {
                "tagName": "a",
                "href": "http://127.0.0.1:8767/api/projects/proj_1/artifacts/art_1/versions/ver_1/script-bundle",
                "target": "",
                "rel": "",
                "download": "",
            },
        )
        self.assertEqual(
            result["renderedOpen"],
            {
                "tagName": "a",
                "href": "/api/projects/proj_1/artifacts/art_1/versions/ver_1/file",
                "target": "_blank",
                "rel": "noopener noreferrer",
                "download": "",
            },
        )
        self.assertEqual(
            dict(result["stateActionChecks"]),
            {"star": True, "unstar": True, "hide": True, "unhide": True, "rename": False, "delete": False},
        )
        self.assertNotIn("download_script_bundle", result["redactedActionIds"])

    def test_artifact_library_no_match_keeps_toolbar_visible(self) -> None:
        artifacts_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_artifacts.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const artifacts = await import(__ARTIFACTS_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            globalThis.window = { location: { href: 'http://127.0.0.1:8767/projects/proj_1' } };
            const container = document.createElement('div');
            artifacts.renderArtifacts(container, [{
              id: 'art_evidence',
              project_id: 'proj_1',
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              title: 'Evidence report: rs429358',
              operation: 'research.build_target_packet',
              summary_lines: ['evidence_present'],
              preview_url: '/api/projects/proj_1/artifacts/art_evidence/file'
            }], {
              baseUrl: window.location.href,
              query: 'missing'
            });
            const toolbar = container.querySelector('[data-testid="genomi-artifact-library-toolbar"]');
            const search = container.querySelector('[data-testid="genomi-artifact-search"]');
            const cards = container.querySelectorAll('[data-testid="genomi-artifact-card"]');
            const noticeTitle = container.querySelector('.artifact-card strong');
            process.stdout.write(JSON.stringify({
              hasToolbar: Boolean(toolbar),
              searchValue: search ? search.value : '',
              matchedCardCount: cards.length,
              noticeTitle: noticeTitle ? noticeTitle.textContent : ''
            }));
            """
        ).replace("__ARTIFACTS_URL__", json.dumps(artifacts_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertTrue(result["hasToolbar"])
        self.assertEqual(result["searchValue"], "missing")
        self.assertEqual(result["matchedCardCount"], 0)
        self.assertEqual(result["noticeTitle"], "No matching library items")

    def test_artifact_library_card_surfaces_review_status(self) -> None:
        artifacts_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_artifacts.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const artifacts = await import(__ARTIFACTS_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            globalThis.window = { location: { href: 'http://127.0.0.1:8767/projects/proj_1' } };
            const container = document.createElement('div');
            artifacts.renderArtifacts(container, [{
              id: 'art_reviewed',
              project_id: 'proj_1',
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              title: 'Evidence report: rs429358',
              operation: 'research.build_target_packet',
              preview_url: '/api/projects/proj_1/artifacts/art_reviewed/file',
              latest_version: {
                version_id: 'ver_reviewed',
                project_id: 'proj_1',
                artifact_id: 'art_reviewed',
                review: {
                  kind: 'artifact_version_review',
                  status: 'warning',
                  check_count: 2,
                  counts: { passed: 1, warning: 1, failed: 0 },
                  checks: [
                    { check_id: 'artifact_file_snapshot', title: 'Artifact file snapshot', status: 'passed' },
                    { check_id: 'rebuild_recipe', title: 'Rebuild recipe', status: 'warning' }
                  ]
                }
              },
              versions: [{
                version_id: 'ver_reviewed',
                project_id: 'proj_1',
                artifact_id: 'art_reviewed',
                review: {
                  kind: 'artifact_version_review',
                  status: 'warning',
                  check_count: 2,
                  counts: { passed: 1, warning: 1, failed: 0 },
                  checks: [
                    { check_id: 'artifact_file_snapshot', title: 'Artifact file snapshot', status: 'passed' },
                    { check_id: 'rebuild_recipe', title: 'Rebuild recipe', status: 'warning' }
                  ]
                }
              }]
            }], { baseUrl: window.location.href });
            const badge = container.querySelector('[data-testid="genomi-artifact-review-status"]');
            process.stdout.write(JSON.stringify({
              className: badge ? badge.className : '',
              label: badge ? badge.querySelector('span').textContent : '',
              value: badge ? badge.querySelector('strong').textContent : '',
              title: badge ? badge.title : ''
            }));
            """
        ).replace("__ARTIFACTS_URL__", json.dumps(artifacts_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertIn("warning", result["className"])
        self.assertEqual(result["label"], "Review")
        self.assertEqual(result["value"], "warnings")
        self.assertEqual(result["title"], "2 checks · 1 warning")

    def test_artifact_library_renders_uploads_separately_from_generated_artifacts(self) -> None:
        artifacts_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_artifacts.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const artifacts = await import(__ARTIFACTS_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            globalThis.window = { location: { href: 'http://127.0.0.1:8767/projects/proj_1' } };
            const container = document.createElement('div');
            artifacts.renderArtifacts(container, [
              {
                id: 'art_evidence',
                project_id: 'proj_1',
                kind: 'evidence_packet',
                renderer: 'evidence_packet',
                title: 'Evidence report: rs429358',
                operation: 'research.build_target_packet',
                preview_url: '/api/projects/proj_1/artifacts/art_evidence/file',
                origin_context: { frame_id: 'frame_1', run_ids: ['run_1'] }
              },
              {
                id: 'art_dashboard',
                project_id: 'proj_1',
                kind: 'decode_dashboard',
                renderer: 'decode_dashboard',
                title: 'Decode dashboard',
                operation: 'decode.render_dashboard',
                preview_url: '/api/projects/proj_1/artifacts/art_dashboard/file',
                origin_context: { frame_id: 'frame_1', run_ids: ['run_2'] }
              },
              {
                id: 'art_file',
                project_id: 'proj_1',
                kind: 'project_file',
                renderer: 'project_file',
                title: 'lab-notes.csv',
                operation: 'portal.import_file',
                latest_version: {
                  version_id: 'ver_file',
                  project_id: 'proj_1',
                  artifact_id: 'art_file',
                  content_type: 'text/csv'
                }
              },
              {
                id: 'art_produced_file',
                project_id: 'proj_1',
                kind: 'project_file',
                renderer: 'project_file',
                title: 'reports/apoe.txt',
                operation: 'portal.agent_file',
                latest_version: {
                  version_id: 'ver_produced_file',
                  project_id: 'proj_1',
                  artifact_id: 'art_produced_file',
                  content_type: 'text/plain'
                }
              }
            ], { baseUrl: window.location.href });
            const groupsShell = container.querySelector('[data-testid="genomi-artifact-library-groups"]');
            const groups = container.querySelectorAll('[data-testid="genomi-artifact-library-group"]').map((group) => ({
              key: group.getAttribute('data-artifact-group'),
              title: group.querySelector('.artifact-library-group-head strong').textContent,
              summary: group.querySelector('.artifact-library-group-head span').textContent,
              cards: group.querySelectorAll('[data-testid="genomi-artifact-card"]').map((card) => card.dataset.artifactId)
            }));
            process.stdout.write(JSON.stringify({
              hasGroupsShell: Boolean(groupsShell),
              groups
            }));
            """
        ).replace("__ARTIFACTS_URL__", json.dumps(artifacts_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertTrue(result["hasGroupsShell"])
        self.assertEqual(
            result["groups"],
            [
                {
                    "key": "uploads",
                    "title": "Your uploads",
                    "summary": "1 uploaded file",
                    "cards": ["art_file"],
                },
                {
                    "key": "produced_files",
                    "title": "Produced files",
                    "summary": "1 produced file",
                    "cards": ["art_produced_file"],
                },
                {
                    "key": "generated_turn_1",
                    "title": "Created in assistant turn 1",
                    "summary": "1 artifact from this assistant turn",
                    "cards": ["art_evidence"],
                },
                {
                    "key": "generated_turn_2",
                    "title": "Created in assistant turn 2",
                    "summary": "1 artifact from this assistant turn",
                    "cards": ["art_dashboard"],
                },
            ],
        )

    def test_preview_renders_html_artifacts_in_iframe_and_project_text_files_inline(self) -> None:
        artifacts_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_artifacts.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const artifacts = await import(__ARTIFACTS_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            globalThis.window = { location: { href: 'http://127.0.0.1:8767/projects/proj_1' } };
            globalThis.fetch = async (url) => ({
              ok: true,
              text: async () => String(url).includes('markdown')
                ? '# APOE note\\n\\n**rs429358** is coding.\\n\\n| Source | Finding |\\n|---|---|\\n| dbSNP | APOE |\\n'
                : 'gene,score\\nAPOE,0.91\\n'
            });
            const htmlContainer = document.createElement('div');
            artifacts.renderArtifactPreview(htmlContainer, {
              id: 'art_html',
              project_id: 'proj_1',
              kind: 'evidence_packet',
              renderer: 'evidence_packet',
              title: 'Evidence report',
              operation: 'research.build_target_packet',
              preview_url: '/api/projects/proj_1/artifacts/art_html/file',
              latest_version: {
                version_id: 'ver_html',
                project_id: 'proj_1',
                artifact_id: 'art_html',
                content_type: 'text/html'
              }
            }, { baseUrl: window.location.href, onUseContext: () => {} });
            const fileContainer = document.createElement('div');
            artifacts.renderArtifactPreview(fileContainer, {
              id: 'art_file',
              project_id: 'proj_1',
              kind: 'project_file',
              renderer: 'project_file',
              title: 'lab-notes.csv',
              operation: 'portal.import_file',
              preview_url: '/api/projects/proj_1/artifacts/art_file/file',
              latest_version: {
                version_id: 'ver_file',
                project_id: 'proj_1',
                artifact_id: 'art_file',
                content_type: 'text/csv'
              }
            }, { baseUrl: window.location.href, onUseContext: () => {} });
            const markdownContainer = document.createElement('div');
            artifacts.renderArtifactPreview(markdownContainer, {
              id: 'art_markdown',
              project_id: 'proj_1',
              kind: 'project_file',
              renderer: 'project_file',
              title: 'reports/apoe.md',
              operation: 'portal.agent_file',
              preview_url: '/api/projects/proj_1/artifacts/art_markdown/file',
              latest_version: {
                version_id: 'ver_markdown',
                project_id: 'proj_1',
                artifact_id: 'art_markdown',
                content_type: 'text/markdown'
              }
            }, { baseUrl: window.location.href, onUseContext: () => {} });
            await new Promise((resolve) => setTimeout(resolve, 0));
            const htmlIframe = htmlContainer.querySelector('[data-testid="genomi-artifact-preview-frame"]');
            const htmlInline = htmlContainer.querySelector('[data-testid="genomi-artifact-file-preview"]');
            const fileIframe = fileContainer.querySelector('[data-testid="genomi-artifact-preview-frame"]');
            const fileInline = fileContainer.querySelector('[data-testid="genomi-artifact-file-preview"]');
            const markdownArticle = markdownContainer.querySelector('[data-testid="genomi-workspace-file-markdown-preview"]');
            process.stdout.write(JSON.stringify({
              htmlIframe: Boolean(htmlIframe),
              htmlInline: Boolean(htmlInline),
              fileIframe: Boolean(fileIframe),
              fileInline: Boolean(fileInline),
              fileText: fileInline ? fileInline.textContent : '',
              markdownArticle: Boolean(markdownArticle),
              markdownHeading: markdownArticle ? markdownArticle.querySelector('h2 span').textContent : '',
              markdownStrong: markdownArticle ? markdownArticle.querySelector('p strong').textContent : '',
              markdownCells: markdownArticle ? markdownArticle.querySelectorAll('td').map((cell) => cell.querySelector('span').textContent) : [],
              markdownTabs: markdownContainer.querySelectorAll('.artifact-tab span').map((tab) => tab.textContent)
            }));
            """
        ).replace("__ARTIFACTS_URL__", json.dumps(artifacts_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertTrue(result["htmlIframe"])
        self.assertFalse(result["htmlInline"])
        self.assertFalse(result["fileIframe"])
        self.assertTrue(result["fileInline"])
        self.assertEqual(result["fileText"], "gene,score\nAPOE,0.91\n")
        self.assertTrue(result["markdownArticle"])
        self.assertEqual(result["markdownHeading"], "APOE note")
        self.assertEqual(result["markdownStrong"], "rs429358")
        self.assertEqual(result["markdownCells"], ["dbSNP", "APOE"])
        self.assertEqual(result["markdownTabs"], ["Preview", "File details"])


def _run_node_json(test_case: unittest.TestCase, script: str):
    node = shutil.which("node")
    test_case.assertIsNotNone(node, "node is required for frontend artifact library tests")
    completed = subprocess.run(
        [str(node), "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _dom_shim_script() -> str:
    return r"""
class ClassList {
  constructor(element) { this.element = element; }
  items() { return String(this.element.className || '').split(/\s+/).filter(Boolean); }
  set(items) { this.element.className = [...new Set(items)].join(' '); }
  add(...names) { this.set([...this.items(), ...names.filter(Boolean)]); }
  remove(...names) { this.set(this.items().filter((item) => !names.includes(item))); }
  contains(name) { return this.items().includes(name); }
  toggle(name, force) {
    const shouldAdd = force === undefined ? !this.contains(name) : Boolean(force);
    if (shouldAdd) this.add(name);
    else this.remove(name);
    return shouldAdd;
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
    this.value = '';
    this.classList = new ClassList(this);
  }
  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  append(...nodes) {
    nodes.forEach((node) => this.appendChild(node));
  }
  replaceChildren(...nodes) {
    this.children = [];
    this.textContent = '';
    nodes.forEach((node) => this.appendChild(node));
  }
  closest(selector) {
    let node = this;
    while (node) {
      if (matches(node, selector)) return node;
      node = node.parentNode;
    }
    return null;
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
  const parts = String(selector || '').trim().split(/\s+/).filter(Boolean);
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
  const attr = String(selector || '').match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
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
  const tags = /<\/?[^>]+>/g;
  const stack = [root];
  let match;
  while ((match = tags.exec(html))) {
    const token = match[0];
    if (/^<\//.test(token)) {
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
    if (!/\/>$/.test(token) && !['br', 'hr', 'img', 'input', 'link', 'meta'].includes(child.tagName)) {
      stack.push(child);
    }
  }
}
"""


if __name__ == "__main__":
    unittest.main()
