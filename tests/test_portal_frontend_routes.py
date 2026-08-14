from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


class PortalFrontendRouteModelTests(unittest.TestCase):
    def test_frame_bundle_action_is_attached_to_chat_header(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"
        html = (root / "portal.html").read_text(encoding="utf-8")
        portal = (root / "portal.js").read_text(encoding="utf-8")

        self.assertIn('id="frame-bundle"', html)
        self.assertIn('data-testid="genomi-frame-download-bundle"', html)
        self.assertIn("function updateFrameBundleAction()", portal)
        self.assertIn("api.frameBundleUrl(state.project.project_id, state.frameId", portal)

    def test_frame_bundle_url_uses_project_scoped_download_route(self) -> None:
        api_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_api.js").as_uri()
        script = textwrap.dedent(
            f"""
            const api = await import({api_url!r});
            const result = {{
              endpoint: api.frameBundleEndpoint('proj 1', 'frame/1'),
              url: api.frameBundleUrl('proj 1', 'frame/1', 'http://127.0.0.1:8767/projects/proj 1'),
              empty: api.frameBundleEndpoint('', 'frame/1')
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["endpoint"], "/api/projects/proj%201/frames/frame%2F1/bundle")
        self.assertEqual(result["url"], "http://127.0.0.1:8767/api/projects/proj%201/frames/frame%2F1/bundle")
        self.assertEqual(result["empty"], "")

    def test_import_project_file_posts_to_project_artifact_import_route(self) -> None:
        api_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_api.js").as_uri()
        script = textwrap.dedent(
            f"""
            const api = await import({api_url!r});
            globalThis.document = {{
              querySelector: () => ({{ getAttribute: () => 'csrf-token' }})
            }};
            globalThis.fetch = async (path, options) => ({{
              ok: true,
              json: async () => ({{
                path,
                method: options.method,
                headers: options.headers,
                body: JSON.parse(options.body)
              }})
            }});
            const result = await api.importProjectFile('proj 1', {{
              filename: 'lab notes.csv',
              contentType: 'text/csv',
              contentBase64: 'YSxi'
            }});
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["path"], "/api/projects/proj%201/artifacts/import")
        self.assertEqual(result["method"], "POST")
        self.assertEqual(result["headers"]["content-type"], "application/json")
        self.assertEqual(result["headers"]["x-genomi-csrf"], "csrf-token")
        self.assertEqual(result["body"]["filename"], "lab notes.csv")

    def test_api_errors_preserve_status_and_error_code(self) -> None:
        api_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_api.js").as_uri()
        script = textwrap.dedent(
            f"""
            const api = await import({api_url!r});
            globalThis.fetch = async () => ({{
              ok: false,
              status: 404,
              json: async () => ({{ error: {{ code: 'not_found', message: 'project not found' }} }})
            }});
            let result = null;
            try {{
              await api.loadProject('proj_missing');
            }} catch (error) {{
              result = {{
                name: error.name,
                message: error.message,
                status: error.status,
                code: error.code,
                isNotFound: api.isNotFoundError(error)
              }};
            }}
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["name"], "PortalApiError")
        self.assertEqual(result["message"], "project not found")
        self.assertEqual(result["status"], 404)
        self.assertEqual(result["code"], "not_found")
        self.assertTrue(result["isNotFound"])

    def test_active_context_api_posts_to_project_route(self) -> None:
        api_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_api.js").as_uri()
        script = textwrap.dedent(
            f"""
            const api = await import({api_url!r});
            globalThis.document = {{
              querySelector: () => ({{ getAttribute: () => 'csrf-token' }})
            }};
            globalThis.fetch = async (path, options = {{}}) => ({{
              ok: true,
              json: async () => ({{
                path,
                method: options.method || 'GET',
                headers: options.headers || {{}},
                body: options.body ? JSON.parse(options.body) : null
              }})
            }});
            const posted = await api.updateActiveContext('proj 1', {{
              workspaceSection: 'artifact-workspace',
              artifactId: 'art 1'
            }});
            const loaded = await api.loadActiveContext('proj 1');
            process.stdout.write(JSON.stringify({{ posted, loaded }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["posted"]["path"], "/api/projects/proj%201/active-context")
        self.assertEqual(result["posted"]["method"], "POST")
        self.assertEqual(result["posted"]["headers"]["x-genomi-csrf"], "csrf-token")
        self.assertEqual(result["posted"]["body"]["workspaceSection"], "artifact-workspace")
        self.assertEqual(result["loaded"]["path"], "/api/projects/proj%201/active-context")
        self.assertEqual(result["loaded"]["method"], "GET")

    def test_active_context_client_debounces_payloads_and_returns_latest_serial(self) -> None:
        active_context_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_active_context_client.js").as_uri()
        script = textwrap.dedent(
            f"""
            const activeContext = await import({active_context_url!r});
            const timers = [];
            const fakeWindow = {{
              location: {{
                pathname: '/projects/proj%201/artifacts/art%201',
                search: '?version=ver%201',
                hash: '#artifact-workspace',
                href: 'http://127.0.0.1:8767/projects/proj%201/artifacts/art%201?version=ver%201#artifact-workspace'
              }},
              setTimeout: (callback, delay) => {{
                const timer = {{ callback, delay, cleared: false }};
                timers.push(timer);
                return timer;
              }},
              clearTimeout: (timer) => {{
                if (timer) timer.cleared = true;
              }}
            }};
            const fakeDocument = {{
              querySelector: (selector) => {{
                if (selector === '[data-nav-target].active') {{
                  return {{ getAttribute: () => 'artifact-workspace' }};
                }}
                if (selector === '[data-nav-target="artifact-workspace"]') {{
                  return {{ textContent: 'Artifact workspace' }};
                }}
                if (selector === '[data-artifact-tab].active') {{
                  return {{
                    textContent: 'Origin chat1',
                    querySelector: (childSelector) => childSelector === 'span' ? {{ textContent: 'Origin chat' }} : null
                  }};
                }}
                return null;
              }}
            }};
            const state = {{
              project: {{ project_id: 'proj 1' }},
              activeWorkspaceSection: '',
              frameId: 'frame 1',
              activeArtifactId: 'art 1',
              activeArtifactVersionId: 'ver 1',
              activeArtifactTabId: 'messages'
            }};
            const artifact = {{ id: 'art 1', title: 'Raw title' }};
            const immediateCalls = [];
            const immediateClient = activeContext.createActiveContextClient({{
              api: {{
                updateActiveContext: async (projectId, payload) => {{
                  immediateCalls.push({{ projectId, payload }});
                  return {{ projectId, payload }};
                }}
              }},
              state,
              activeArtifact: () => artifact,
              artifactPreviewModel: (item, baseUrl) => ({{ title: item.title + ' via ' + baseUrl }}),
              windowRef: fakeWindow,
              documentRef: fakeDocument
            }});
            const payload = immediateClient.payload();
            immediateClient.schedule();
            immediateClient.schedule();
            timers[1].callback();
            await Promise.resolve();

            const pendingCalls = [];
            const resolvers = [];
            const serialClient = activeContext.createActiveContextClient({{
              api: {{
                updateActiveContext: (projectId, payload) => {{
                  pendingCalls.push({{ projectId, payload }});
                  return new Promise((resolve) => resolvers.push(resolve));
                }}
              }},
              state,
              activeArtifact: () => artifact,
              artifactPreviewModel: (item) => ({{ title: item.title }}),
              windowRef: fakeWindow,
              documentRef: fakeDocument
            }});
            const first = serialClient.syncNow();
            const second = serialClient.syncNow();
            resolvers[1]({{ serial: 'second' }});
            const secondResult = await second;
            resolvers[0]({{ serial: 'first' }});
            const firstResult = await first;

            process.stdout.write(JSON.stringify({{
              payload,
              timerCount: timers.length,
              firstTimerCleared: timers[0].cleared,
              secondTimerDelay: timers[1].delay,
              immediateCallCount: immediateCalls.length,
              scheduledPayload: immediateCalls[0] && immediateCalls[0].payload,
              pendingCallCount: pendingCalls.length,
              firstResult,
              secondResult
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["payload"]["route"], "/projects/proj%201/artifacts/art%201?version=ver%201#artifact-workspace")
        self.assertEqual(result["payload"]["workspaceSection"], "artifact-workspace")
        self.assertEqual(result["payload"]["panel"], "Artifact workspace")
        self.assertEqual(result["payload"]["frameId"], "frame 1")
        self.assertEqual(result["payload"]["artifactId"], "art 1")
        self.assertEqual(result["payload"]["artifactVersionId"], "ver 1")
        self.assertEqual(result["payload"]["artifactTabId"], "messages")
        self.assertEqual(result["payload"]["artifactTabLabel"], "Origin chat")
        self.assertIn("Raw title via http://127.0.0.1:8767/projects/proj%201/artifacts/art%201", result["payload"]["artifactTitle"])
        self.assertEqual(result["timerCount"], 2)
        self.assertTrue(result["firstTimerCleared"])
        self.assertEqual(result["secondTimerDelay"], 120)
        self.assertEqual(result["immediateCallCount"], 1)
        self.assertEqual(result["scheduledPayload"]["artifactId"], "art 1")
        self.assertEqual(result["pendingCallCount"], 2)
        self.assertIsNone(result["firstResult"])
        self.assertEqual(result["secondResult"]["serial"], "second")

    def test_prompt_suggestion_api_posts_selected_context_to_server_contract(self) -> None:
        api_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_api.js").as_uri()
        script = textwrap.dedent(
            f"""
            const api = await import({api_url!r});
            globalThis.document = {{
              querySelector: () => ({{ getAttribute: () => 'csrf-token' }})
            }};
            globalThis.fetch = async (path, options = {{}}) => ({{
              ok: true,
              json: async () => ({{
                path,
                method: options.method || 'GET',
                headers: options.headers || {{}},
                body: options.body ? JSON.parse(options.body) : null
              }})
            }});
            const result = await api.suggestPrompt({{
              selectedEvidence: [
                {{ context_kind: 'result_nodes', source_operation: 'variant.resolve', prompt_text: 'Variant row' }}
              ]
            }});
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["path"], "/api/prompt/suggestion")
        self.assertEqual(result["method"], "POST")
        self.assertEqual(result["headers"]["x-genomi-csrf"], "csrf-token")
        self.assertEqual(result["body"]["selectedEvidence"][0]["context_kind"], "result_nodes")

    def test_parses_and_builds_project_frame_artifact_routes(self) -> None:
        route_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifact_route_model.js").as_uri()
        script = textwrap.dedent(
            f"""
            const routes = await import({route_url!r});
            const result = {{
              project: routes.parsePortalRoute('/projects/proj%201'),
              frame: routes.parsePortalRoute('/projects/proj%201/frames/frame%2F1'),
              frameHighlight: routes.parsePortalRoute('/projects/proj%201/frames/frame%2F1?highlight_run=run%201#hash'),
              frameHighlightStep: routes.parsePortalRoute('/projects/proj%201/frames/frame%2F1?highlight_run=run%201&highlight_step=run%201%3Aartifact%3A9#hash'),
              frameHighlightFromSearch: routes.parsePortalRoute('/projects/proj%201/frames/frame%2F1', '?highlight_run=run%202'),
              frameHighlightStepFromSearch: routes.parsePortalRoute('/projects/proj%201/frames/frame%2F1', '?highlight_run=run%202&highlight_step=run%202%3Astdout%3A3'),
              artifact: routes.parsePortalRoute('/projects/proj%201/artifacts/art%2F1'),
              version: routes.parsePortalRoute('/projects/proj%201/artifacts/art%2F1/versions/ver%201?ignored=true#hash'),
              versionTab: routes.parsePortalRoute('/projects/proj%201/artifacts/art%2F1/versions/ver%201?artifact_tab=runtime#hash'),
              artifactTabFromSearch: routes.parsePortalRoute('/projects/proj%201/artifacts/art%2F1', '?artifact_tab=messages'),
              unknown: routes.parsePortalRoute('/projects/proj%201/artifacts/art%2F1/extra'),
              projectPath: routes.projectRoutePath('proj 1'),
              framePath: routes.frameRoutePath('proj 1', 'frame/1'),
              frameHighlightPath: routes.frameRoutePath('proj 1', 'frame/1', 'run 1'),
              frameHighlightStepPath: routes.frameRoutePath('proj 1', 'frame/1', 'run 1', 'run 1:artifact:9'),
              artifactPath: routes.artifactRoutePath('proj 1', 'art/1'),
              versionPath: routes.artifactRoutePath('proj 1', 'art/1', 'ver 1'),
              versionTabPath: routes.artifactRoutePath('proj 1', 'art/1', 'ver 1', 'runtime'),
              artifactUrl: routes.artifactWorkspaceUrl('proj 1', 'art/1', '', 'http://localhost:8767/projects/proj 1'),
              versionUrl: routes.artifactWorkspaceUrl('proj 1', 'art/1', 'ver 1', 'http://localhost:8767/projects/proj 1'),
              versionTabUrl: routes.artifactWorkspaceUrl('proj 1', 'art/1', 'ver 1', 'http://localhost:8767/projects/proj 1', 'runtime')
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["project"], {"kind": "project", "projectId": "proj 1"})
        self.assertEqual(result["frame"], {"kind": "frame", "projectId": "proj 1", "frameId": "frame/1"})
        self.assertEqual(
            result["frameHighlight"],
            {"kind": "frame", "projectId": "proj 1", "frameId": "frame/1", "highlightRunId": "run 1"},
        )
        self.assertEqual(
            result["frameHighlightStep"],
            {
                "kind": "frame",
                "projectId": "proj 1",
                "frameId": "frame/1",
                "highlightRunId": "run 1",
                "highlightStepId": "run 1:artifact:9",
            },
        )
        self.assertEqual(
            result["frameHighlightFromSearch"],
            {"kind": "frame", "projectId": "proj 1", "frameId": "frame/1", "highlightRunId": "run 2"},
        )
        self.assertEqual(
            result["frameHighlightStepFromSearch"],
            {
                "kind": "frame",
                "projectId": "proj 1",
                "frameId": "frame/1",
                "highlightRunId": "run 2",
                "highlightStepId": "run 2:stdout:3",
            },
        )
        self.assertEqual(result["artifact"], {"kind": "artifact", "projectId": "proj 1", "artifactId": "art/1"})
        self.assertEqual(
            result["version"],
            {"kind": "artifact_version", "projectId": "proj 1", "artifactId": "art/1", "versionId": "ver 1"},
        )
        self.assertEqual(
            result["versionTab"],
            {
                "kind": "artifact_version",
                "projectId": "proj 1",
                "artifactId": "art/1",
                "versionId": "ver 1",
                "artifactTabId": "runtime",
            },
        )
        self.assertEqual(
            result["artifactTabFromSearch"],
            {"kind": "artifact", "projectId": "proj 1", "artifactId": "art/1", "artifactTabId": "messages"},
        )
        self.assertEqual(result["unknown"], {})
        self.assertEqual(result["projectPath"], "/projects/proj%201")
        self.assertEqual(result["framePath"], "/projects/proj%201/frames/frame%2F1")
        self.assertEqual(result["frameHighlightPath"], "/projects/proj%201/frames/frame%2F1?highlight_run=run%201")
        self.assertEqual(
            result["frameHighlightStepPath"],
            "/projects/proj%201/frames/frame%2F1?highlight_run=run%201&highlight_step=run%201%3Aartifact%3A9",
        )
        self.assertEqual(result["artifactPath"], "/projects/proj%201/artifacts/art%2F1")
        self.assertEqual(result["versionPath"], "/projects/proj%201/artifacts/art%2F1/versions/ver%201")
        self.assertEqual(
            result["versionTabPath"],
            "/projects/proj%201/artifacts/art%2F1/versions/ver%201?artifact_tab=runtime",
        )
        self.assertEqual(result["artifactUrl"], "http://localhost:8767/projects/proj%201/artifacts/art%2F1")
        self.assertEqual(
            result["versionUrl"],
            "http://localhost:8767/projects/proj%201/artifacts/art%2F1/versions/ver%201",
        )
        self.assertEqual(
            result["versionTabUrl"],
            "http://localhost:8767/projects/proj%201/artifacts/art%2F1/versions/ver%201?artifact_tab=runtime",
        )

    def test_resolves_route_artifact_selection_from_artifact_lists(self) -> None:
        route_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifact_route_model.js").as_uri()
        script = textwrap.dedent(
            f"""
            const routes = await import({route_url!r});
            const artifacts = [
              {{ id: 'art_hidden', previewable: false }},
              {{ id: 'art_route', previewable: true }},
              {{ id: 'art_fallback', previewable: true }}
            ];
            const isPreviewableArtifact = (artifact) => artifact.previewable === true;
            const routeSelection = routes.resolveArtifactRouteSelection({{
              route: routes.parsePortalRoute('/projects/proj_1/artifacts/art_route/versions/ver_2'),
              projectId: 'proj_1',
              artifacts,
              activeArtifactId: 'art_fallback',
              activeArtifactVersionId: 'ver_old',
              activeArtifactTabId: 'messages',
              isPreviewableArtifact
            }});
            const currentSelection = routes.resolveArtifactRouteSelection({{
              route: routes.parsePortalRoute('/projects/proj_1'),
              projectId: 'proj_1',
              artifacts,
              activeArtifactId: 'art_fallback',
              activeArtifactVersionId: 'ver_old',
              activeArtifactTabId: 'messages',
              isPreviewableArtifact
            }});
            const fallbackSelection = routes.resolveArtifactRouteSelection({{
              route: routes.parsePortalRoute('/projects/proj_1/artifacts/missing_artifact/versions/ver_missing'),
              projectId: 'proj_1',
              artifacts,
              activeArtifactId: 'missing_artifact',
              activeArtifactVersionId: 'ver_missing',
              isPreviewableArtifact
            }});
            const wrongProjectSelection = routes.resolveArtifactRouteSelection({{
              route: routes.parsePortalRoute('/projects/other/artifacts/art_route/versions/ver_2'),
              projectId: 'proj_1',
              artifacts,
              activeArtifactId: '',
              activeArtifactVersionId: '',
              isPreviewableArtifact
            }});
            process.stdout.write(JSON.stringify({{
              routeSelection,
              currentSelection,
              fallbackSelection,
              wrongProjectSelection
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["routeSelection"]["artifactId"], "art_route")
        self.assertEqual(result["routeSelection"]["artifactVersionId"], "ver_2")
        self.assertEqual(result["routeSelection"]["selectionSource"], "route")
        self.assertFalse(result["routeSelection"]["normalizeToProject"])
        self.assertEqual(result["currentSelection"]["artifactId"], "art_fallback")
        self.assertEqual(result["currentSelection"]["artifactVersionId"], "ver_old")
        self.assertEqual(result["currentSelection"]["artifactTabId"], "messages")
        self.assertEqual(result["currentSelection"]["selectionSource"], "current")
        self.assertIsNone(result["fallbackSelection"]["artifactId"])
        self.assertIsNone(result["fallbackSelection"]["artifactVersionId"])
        self.assertEqual(result["fallbackSelection"]["selectionSource"], "none")
        self.assertTrue(result["fallbackSelection"]["normalizeToProject"])
        self.assertIsNone(result["wrongProjectSelection"]["artifactId"])
        self.assertEqual(result["wrongProjectSelection"]["selectionSource"], "none")
        self.assertFalse(result["wrongProjectSelection"]["normalizeToProject"])

    def test_validates_requested_version_after_detail_hydration(self) -> None:
        route_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifact_route_model.js").as_uri()
        script = textwrap.dedent(
            f"""
            const routes = await import({route_url!r});
            const detail = {{
              id: 'art_1',
              selected_version_id: 'stale',
              versions: [
                {{ version_id: 'ver_latest' }},
                {{ version_id: 'ver_old' }}
              ]
            }};
            const valid = routes.validateRequestedArtifactVersion(detail, 'ver_old');
            const invalid = routes.validateRequestedArtifactVersion(detail, 'ver_missing');
            const unrequested = routes.validateRequestedArtifactVersion(detail, '');
            const selectedArtifact = routes.artifactWithSelectedVersion(detail, 'ver_old');
            const missingSelectedArtifact = routes.artifactWithSelectedVersion(detail, 'ver_missing');
            process.stdout.write(JSON.stringify({{
              valid,
              invalid,
              unrequested,
              selectedArtifact,
              missingSelectedArtifact,
              emptyArtifact: routes.artifactWithSelectedVersion(null, 'ver_old')
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertTrue(result["valid"]["valid"])
        self.assertFalse(result["valid"]["shouldNormalizeToArtifact"])
        self.assertEqual(result["valid"]["selectedVersionId"], "ver_old")
        self.assertEqual(result["valid"]["artifact"]["selected_version_id"], "ver_old")
        self.assertFalse(result["invalid"]["valid"])
        self.assertTrue(result["invalid"]["shouldNormalizeToArtifact"])
        self.assertNotIn("selected_version_id", result["invalid"]["artifact"])
        self.assertTrue(result["unrequested"]["valid"])
        self.assertEqual(result["unrequested"]["artifact"]["selected_version_id"], "stale")
        self.assertEqual(result["selectedArtifact"]["selected_version_id"], "ver_old")
        self.assertNotIn("selected_version_id", result["missingSelectedArtifact"])
        self.assertIsNone(result["emptyArtifact"])


def _run_node_json(test_case: unittest.TestCase, script: str):
    node = shutil.which("node")
    test_case.assertIsNotNone(node, "node is required for frontend route model tests")
    completed = subprocess.run(
        [str(node), "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


if __name__ == "__main__":
    unittest.main()
