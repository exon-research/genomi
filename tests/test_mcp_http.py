from __future__ import annotations

import http.client
import io
import json
import os
import re
import socket
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from genomi.interfaces import mcp
from genomi.interfaces import portal_assets
from genomi.interfaces import portal_project_events
from genomi.interfaces import portal_run_events
from genomi.interfaces import portal_store
from genomi.interfaces import portal_workspaces

_PRIVATE_PATH_RE = re.compile(r"(?:/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes|~)(?:/|$)")
_PRIVATE_KEYS = {
    "context_file",
    "registry_file",
    "agi_path",
    "dashboard_path",
    "shared_evidence_db",
    "artifact_path",
    "path",
    "result",
}


class MCPHTTPTests(unittest.TestCase):
    def test_health_endpoint_reports_http_transport(self) -> None:
        with _running_server() as address:
            status, payload = _request_json("GET", address, "/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["server"], "genomi")
        self.assertEqual(payload["transport"], "http")
        self.assertEqual(payload["mcp_endpoint"], "/mcp")
        self.assertEqual(payload["portal_endpoint"], "/")

    def test_http_serve_fails_when_port_is_occupied(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            port = int(occupied.getsockname()[1])
            stderr = io.StringIO()

            result = mcp.serve_http(host="127.0.0.1", port=port, stderr=stderr)

        self.assertEqual(result, 1)
        self.assertIn("portal port unavailable", stderr.getvalue())
        self.assertIn("pass --port", stderr.getvalue())

    def test_http_serve_can_open_workspace_browser(self) -> None:
        class StoppingServer:
            server_address = ("127.0.0.1", 8768)
            closed = False

            def serve_forever(self) -> None:
                raise KeyboardInterrupt

            def server_close(self) -> None:
                self.closed = True

        server = StoppingServer()
        stderr = io.StringIO()
        with mock.patch.object(mcp, "make_http_server", return_value=server), mock.patch.object(
            mcp.webbrowser,
            "open",
        ) as open_browser:
            result = mcp.serve_http(host="127.0.0.1", port=8768, open_browser=True, stderr=stderr)

        self.assertEqual(result, 0)
        self.assertTrue(server.closed)
        open_browser.assert_called_once_with("http://127.0.0.1:8768/")
        self.assertIn("starting GenomiLab workspace", stderr.getvalue())
        self.assertIn("http://127.0.0.1:8768/mcp", stderr.getvalue())

    def test_root_endpoint_serves_portal_workspace(self) -> None:
        with _running_server() as address:
            status, headers, body = _request_raw("GET", address, "/")

        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])
        text = body.decode("utf-8")
        self.assertIn("<title>GenomiLab</title>", text)
        self.assertIn("Inquiry", text)
        self.assertIn("Conversations", text)
        self.assertIn("frame-list", text)
        self.assertIn('<button id="send" class="primary" type="submit">Send</button>', text)
        self.assertIn('name="genomi-csrf-token"', text)
        self.assertNotIn("fonts.googleapis.com", text)

        self.assertIn("/assets/portal.css", text)
        self.assertIn("/assets/portal_selection_states.css", text)
        self.assertIn("/assets/portal_artifact_actions.css", text)
        self.assertIn("/assets/portal_prompt_context.css", text)
        self.assertIn("/assets/portal.js", text)
        self.assertIn('data-genomi-portal-css', text)
        self.assertIn(".app {", text)
        self.assertIn(".artifact-action-menu", text)
        self.assertIn(".prompt-context {", text)
        self.assertIn('data-nav-target="tool-launcher"', text)
        self.assertIn('id="tool-launcher-list"', text)
        self.assertIn('id="tool-inspector"', text)
        self.assertIn('data-nav-target="genome-index"', text)
        self.assertIn('id="context-summary"', text)
        self.assertIn('id="genome-inventory"', text)
        self.assertIn('id="artifact-workspace"', text)
        self.assertIn('id="workspace-files"', text)
        self.assertIn('id="artifact-import-file"', text)
        self.assertIn("Import file", text)
        self.assertIn('type="module"', text)

    def test_lab_portal_exchanges_one_time_launch_token_for_api_session(self) -> None:
        server = mcp.make_http_server(
            "127.0.0.1", 0, portal_session_auth=True
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        address = server.server_address
        origin = f"http://{address[0]}:{address[1]}"
        try:
            status, _, _ = _request_raw("GET", address, "/api/projects")
            self.assertEqual(status, 401)

            status, response_headers, body = _request_raw(
                "POST",
                address,
                "/api/session",
                json.dumps(
                    {"launch_token": server.portal_launch_token}
                ).encode("utf-8"),
                {"Content-Type": "application/json", "Origin": origin},
            )
            self.assertEqual(status, 200)
            session_token = json.loads(body)["session_token"]
            session_cookie = response_headers["set-cookie"].split(";", 1)[0]
            self.assertEqual(
                session_cookie, f"genomi_portal_session={session_token}"
            )
            self.assertIn("HttpOnly", response_headers["set-cookie"])
            self.assertIn("SameSite=Strict", response_headers["set-cookie"])

            status, _, _ = _request_raw(
                "GET",
                address,
                "/api/projects",
                headers={"X-Genomi-Session": session_token},
            )
            self.assertEqual(status, 200)

            status, _, _ = _request_raw(
                "GET",
                address,
                "/api/projects",
                headers={"Cookie": session_cookie},
            )
            self.assertEqual(status, 200)

            status, _, _ = _request_raw(
                "POST",
                address,
                "/api/session",
                json.dumps(
                    {"launch_token": server.portal_launch_token}
                ).encode("utf-8"),
                {"Content-Type": "application/json", "Origin": origin},
            )
            self.assertEqual(status, 401)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_project_deep_link_serves_portal_workspace(self) -> None:
        with _running_server() as address:
            status, headers, body = _request_raw("GET", address, "/projects/proj_test")

        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])
        text = body.decode("utf-8")
        self.assertIn("<title>GenomiLab</title>", text)
        self.assertIn("/assets/portal.js", text)
        self.assertIn('data-nav-target="artifact-workspace"', text)

    def test_project_frame_deep_link_serves_portal_workspace(self) -> None:
        with _running_server() as address:
            status, headers, body = _request_raw("GET", address, "/projects/proj_test/frames/frame_test")

        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])
        text = body.decode("utf-8")
        self.assertIn("<title>GenomiLab</title>", text)
        self.assertIn("/assets/portal.js", text)

    def test_project_artifact_deep_link_serves_portal_workspace(self) -> None:
        with _running_server() as address:
            status, headers, body = _request_raw("GET", address, "/projects/proj_test/artifacts/art_test")

        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])
        text = body.decode("utf-8")
        self.assertIn("<title>GenomiLab</title>", text)
        self.assertIn("/assets/portal.js", text)
        self.assertIn('id="artifact-workspace"', text)
        self.assertIn('id="genomi-starter-cards" type="application/json"', text)
        self.assertIn('data-source-operation="genomi.parse_source"', text)
        self.assertIn('data-source-operation="research.build_target_packet"', text)
        self.assertIn('data-source-operation="variant.resolve"', text)

    def test_project_artifact_version_deep_link_serves_portal_workspace(self) -> None:
        with _running_server() as address:
            status, headers, body = _request_raw("GET", address, "/projects/proj_test/artifacts/art_test/versions/ver_test")

        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])
        text = body.decode("utf-8")
        self.assertIn("<title>GenomiLab</title>", text)
        self.assertIn("/assets/portal.js", text)
        self.assertIn('id="artifact-workspace"', text)

    def test_start_route_is_not_a_portal_entrypoint(self) -> None:
        with _running_server() as address:
            status, _headers, _body = _request_raw("GET", address, "/start")

        self.assertEqual(status, 404)

    def test_root_endpoint_fails_when_portal_css_asset_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            template = Path(tmp) / "portal.html"
            template.write_text(
                '<!doctype html><title>GenomiLab</title><link rel="stylesheet" href="/assets/missing.css">'
                '<style data-genomi-portal-css>{PORTAL_INLINE_CSS}</style>',
                encoding="utf-8",
            )
            with mock.patch.object(portal_assets, "_TEMPLATE_PATH", template):
                with _running_server() as address:
                    status, _headers, _body = _request_raw("GET", address, "/")

        self.assertEqual(status, 500)

    def test_portal_state_error_response_omits_local_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            state_path = Path(tmp) / "portal" / "state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text("{not json", encoding="utf-8")
            with _running_server() as address:
                status, payload = _request_json("GET", address, "/api/projects")

        self.assertEqual(status, 500)
        self.assertEqual(payload["error"], {"code": "portal_state_error", "message": "Portal state is unavailable."})
        _assert_public_payload(payload)

    def test_project_active_context_endpoint_returns_prompt_safe_visible_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Active Context"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]

                status, payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/active-context",
                    {
                        "route": f"/projects/{project_id}/artifacts/art_1?path=/Users/matthewzmd/private.json",
                        "workspaceSection": "artifact-workspace",
                        "panel": "Artifacts",
                        "artifactId": "art_1",
                        "artifactTitle": "CYP2C19 report",
                    },
                )
                self.assertEqual(status, 200)

                status, fetched = _request_json("GET", address, f"/api/projects/{project_id}/active-context")

        self.assertEqual(status, 200)
        self.assertEqual(payload["active_context"]["workspace_section"], "artifact-workspace")
        self.assertEqual(fetched["active_context"]["panel"], "Artifacts")
        self.assertEqual(fetched["active_context"]["artifact_title"], "CYP2C19 report")
        _assert_public_payload(payload)
        _assert_public_payload(fetched)

    def test_portal_genome_selection_is_isolated_between_projects(self) -> None:
        inventory = {
            "status": "completed",
            "active": {"agi_id": "agi_global", "user_id": "user_global"},
            "users": [
                {"user_id": "user_a", "nickname": "Subject A", "active_agi_id": "agi_a", "agi_ids": ["agi_a"]},
                {"user_id": "user_b", "nickname": "Subject B", "active_agi_id": "agi_b", "agi_ids": ["agi_b"]},
            ],
            "active_genome_indexes": [
                {"agi_id": "agi_a", "names": {"display": "Subject A genome"}, "users": [{"user_id": "user_a", "nickname": "Subject A"}]},
                {"agi_id": "agi_b", "names": {"display": "Subject B genome"}, "users": [{"user_id": "user_b", "nickname": "Subject B"}]},
            ],
        }
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}),
            mock.patch("genomi.interfaces.portal_genomes.call_operation", return_value=inventory),
            _running_server() as address,
        ):
            status, first = _request_json("POST", address, "/api/projects", {"name": "Subject A"})
            self.assertEqual(status, 201)
            status, second = _request_json("POST", address, "/api/projects", {"name": "Subject B"})
            self.assertEqual(status, 201)
            first_id = first["project"]["project_id"]
            second_id = second["project"]["project_id"]

            status, selected = _request_json(
                "POST",
                address,
                "/api/genomes/select",
                {"projectId": first_id, "agiId": "agi_a"},
            )
            self.assertEqual(status, 200)
            status, first_inventory = _request_json("GET", address, f"/api/genomes?projectId={first_id}")
            self.assertEqual(status, 200)
            status, second_inventory = _request_json("GET", address, f"/api/genomes?projectId={second_id}")
            self.assertEqual(status, 200)
            status, first_context = _request_json("GET", address, f"/api/context?projectId={first_id}")
            self.assertEqual(status, 200)
            status, second_context = _request_json("GET", address, f"/api/context?projectId={second_id}")

        self.assertEqual(status, 200)
        self.assertEqual(selected["selection"]["access"]["scope"], "portal_project")
        self.assertEqual(first_inventory["active"]["agi_id"], "agi_a")
        self.assertEqual(second_inventory["active"]["agi_id"], "")
        self.assertTrue(first_context["context"]["active_genome_index_access"]["approved"])
        self.assertEqual(first_context["context"]["active_genome_index_access"]["scope"], "portal_project")
        self.assertFalse(second_context["context"]["active_genome_index_access"]["approved"])
        self.assertFalse(second_context["context"]["has_active_genome_index"])

    def test_portal_static_logo_endpoint(self) -> None:
        with _running_server() as address:
            status, headers, body = _request_raw("GET", address, "/assets/genomi-logo-transparent.png")

        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "image/png")
        self.assertGreater(len(body), 100)

    def test_portal_static_app_assets(self) -> None:
        assets = [
            (name, "text/css" if name.endswith(".css") else "javascript")
            for name in portal_assets.template_asset_names()
        ]
        asset_names = [name for name, _content_type in assets]
        self.assertIn("portal.css", asset_names)
        self.assertIn("portal_selection_states.css", asset_names)
        self.assertIn("portal_artifact_actions.css", asset_names)
        self.assertIn("portal_prompt_context.css", asset_names)
        self.assertIn("portal.js", asset_names)
        self.assertIn("portal_genome_inventory.js", asset_names)
        self.assertIn("portal_messages.js", asset_names)
        self.assertIn("portal_starter_cards.js", asset_names)
        self.assertIn("portal_selected_evidence.js", asset_names)
        with _running_server() as address:
            fetched = {
                name: _request_raw("GET", address, f"/assets/{name}")
                for name, _content_type in assets
            }

        for name, content_type in assets:
            status, headers, body = fetched[name]
            self.assertEqual(status, 200, name)
            self.assertIn(content_type, headers["content-type"], name)
            self.assertGreater(len(body), 50, name)

    def test_portal_agents_endpoint_reports_detected_host_agents(self) -> None:
        with _running_server() as address:
            status, payload = _request_json("GET", address, "/api/agents")

        self.assertEqual(status, 200)
        agents = payload["agents"]
        self.assertTrue(any(agent["id"] == "claude" for agent in agents))
        self.assertTrue(all("available" in agent for agent in agents))
        self.assertTrue(all("runnable" in agent for agent in agents))
        self.assertTrue(
            all(
                set(agent) == {"id", "label", "command", "summary", "available", "runnable", "status"}
                for agent in agents
            )
        )

    def test_portal_json_api_is_same_origin_and_uses_public_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            with _running_server() as address:
                status, headers, body = _request_raw("GET", address, "/api/context")

        self.assertEqual(status, 200)
        self.assertNotIn("access-control-allow-origin", headers)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(set(payload), {"genomiVersion", "context", "mcp"})
        self.assertEqual(
            set(payload["context"]),
            {
                "status",
                "error",
                "has_active_genome_index",
                "context_policy",
                "active_genome_index_access",
                "active_genome_index",
                "active_genome_index_registry",
                "selection_source",
                "default_auto_selected",
                "context_axes",
                "active_response_profile",
            },
        )
        _assert_public_payload(payload)

    def test_portal_genome_inventory_api_lists_and_selects_genomes(self) -> None:
        inventory = {
            "status": "completed",
            "active": {"agi_id": "agi_1", "user_id": "user_alex"},
            "summary": {"genome_count": 2, "profile_count": 1},
            "users": [],
            "genomes": [],
        }
        selected = {
            "status": "completed",
            "selection": {"active_agi_id": "agi_2", "access": {"approved": True, "scope": "portal_project"}},
            "inventory": inventory,
        }
        with mock.patch("genomi.interfaces.portal_genomes.genome_inventory_payload", return_value=inventory), mock.patch(
            "genomi.interfaces.portal_genomes.select_active_genome",
            return_value=selected,
        ) as select:
            with _running_server() as address:
                status, payload = _request_json("GET", address, "/api/genomes")
                project_status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Genome project"})
                project_id = project_payload["project"]["project_id"]
                select_status, select_payload = _request_json(
                    "POST",
                    address,
                    "/api/genomes/select",
                    {"projectId": project_id, "agiId": "agi_2"},
                )

        self.assertEqual(status, 200)
        self.assertEqual(payload["summary"]["genome_count"], 2)
        self.assertEqual(project_status, 201)
        self.assertEqual(select_status, 200)
        self.assertEqual(select_payload["selection"]["active_agi_id"], "agi_2")
        select.assert_called_once_with({"projectId": project_id, "agiId": "agi_2"}, project_id=project_id)

    def test_portal_tools_endpoint_uses_operation_discovery(self) -> None:
        with _running_server() as address:
            status, payload = _request_json("GET", address, "/api/tools?namespace=genomi")

        self.assertEqual(status, 200)
        tools_by_name = {tool["name"]: tool for tool in payload["tools"]}
        tool_names = list(tools_by_name)
        self.assertIn("genomi.install", tool_names)
        self.assertEqual(tools_by_name["genomi.install"]["annotations"]["portalLabel"], "Genomi Install")

    def test_portal_source_lookups_endpoint_returns_curated_cards(self) -> None:
        with _running_server() as address:
            status, payload = _request_json("GET", address, "/api/source-lookups")

        self.assertEqual(status, 200)
        self.assertEqual(payload["surface"], "source_lookup_setup")
        tools_by_name = {tool["name"]: tool for tool in payload["sourceLookups"]}
        self.assertIn("genomi.parse_source", tools_by_name)
        self.assertIn("genomi.search_indexes", tools_by_name)
        self.assertIn("variant.resolve", tools_by_name)
        self.assertIn("research.build_target_packet", tools_by_name)
        self.assertNotIn("genomi.install", tools_by_name)
        self.assertNotIn("genomi.check_libraries", tools_by_name)
        self.assertNotIn("inputSchema", tools_by_name["variant.resolve"])
        self.assertEqual(tools_by_name["genomi.parse_source"]["sourceLookup"]["displayLabel"], "Add genome file")
        self.assertEqual(tools_by_name["genomi.search_indexes"]["sourceLookup"]["displayLabel"], "Search public sources")
        self.assertEqual(tools_by_name["variant.resolve"]["sourceLookup"]["displayLabel"], "Variant lookup")
        self.assertEqual(
            [field["label"] for field in tools_by_name["genomi.parse_source"]["sourceLookup"]["request"]["fields"][:3]],
            ["Genome source", "Genome build", "Reference FASTA"],
        )
        self.assertEqual(
            [field["label"] for field in tools_by_name["genomi.search_indexes"]["sourceLookup"]["request"]["fields"][:2]],
            ["Search text", "Index source"],
        )
        self.assertEqual(
            tools_by_name["genomi.parse_source"]["sourceLookup"]["request"]["ui"]["fieldGroups"][0],
            {
                "id": "genome_details",
                "label": "Genome details",
                "className": "tool-request-source-limits",
                "bodyClassName": "tool-request-source-limits-body",
                "collapsed": True,
                "parameters": ["genome_build", "reference_fasta", "user_nickname", "set_default_user"],
            },
        )
        self.assertEqual(
            tools_by_name["genomi.search_indexes"]["sourceLookup"]["request"]["ui"]["fieldGroups"][0],
            {
                "id": "source_limits",
                "label": "Source limits",
                "className": "tool-request-source-limits",
                "bodyClassName": "tool-request-source-limits-body",
                "collapsed": True,
                "parameters": ["source", "limit"],
            },
        )
        self.assertEqual(
            tools_by_name["variant.resolve"]["sourceLookup"]["request"]["ui"]["fieldGroups"][0],
            {
                "id": "variant_details",
                "label": "Other variant formats and source limits",
                "className": "tool-request-source-limits",
                "bodyClassName": "tool-request-source-limits-body",
                "collapsed": True,
                "parameters": [
                    "query",
                    "chrom",
                    "pos",
                    "ref",
                    "alt",
                    "region",
                    "genome_build",
                    "include_active_genome_index",
                ],
            },
        )
        target_packet_request = tools_by_name["research.build_target_packet"]["sourceLookup"]["request"]
        self.assertEqual(
            target_packet_request["ui"]["guidedControls"][0]["options"],
            [
                {"value": "condition", "label": "Condition"},
                {"value": "drug", "label": "Medication"},
                {"value": "gene", "label": "Gene"},
                {"value": "topic", "label": "Topic"},
                {"value": "variant", "label": "Variant"},
            ],
        )
        self.assertEqual(
            target_packet_request["ui"]["fieldGroups"][0],
            {
                "id": "source_limits",
                "label": "Source limits",
                "className": "tool-request-source-limits",
                "bodyClassName": "tool-request-source-limits-body",
                "collapsed": True,
                "parameters": ["genome_build", "limit"],
            },
        )
        self.assertIn("Updates workspace", tools_by_name["genomi.parse_source"]["sourceLookup"]["badges"])
        self.assertNotIn("Write", tools_by_name["genomi.parse_source"]["sourceLookup"]["badges"])
        variant_boundary = next(
            section
            for section in tools_by_name["variant.resolve"]["sourceLookup"]["sections"]
            if section["title"] == "Boundary"
        )["nodes"]
        self.assertNotIn("Operation scope", [node["label"] for node in variant_boundary])
        self.assertIn(
            {"label": "Operation ID", "value": "variant.resolve"},
            next(
                section
                for section in tools_by_name["variant.resolve"]["sourceLookup"]["technicalSections"]
                if section["title"] == "Operation"
            )["nodes"],
        )
        self.assertIn(
            {"label": "Workspace effect", "value": "Read"},
            next(
                section
                for section in tools_by_name["variant.resolve"]["sourceLookup"]["technicalSections"]
                if section["title"] == "Operation"
            )["nodes"],
        )
        user_facing_payload = json.dumps(
            [
                tool["sourceLookup"]
                for tool in payload["sourceLookups"]
            ]
        )
        self.assertNotRegex(user_facing_payload, r"\b[Ss]ource checks?\b|\b[Pp]repare\b|\b[Pp]reparation\b")
        self.assertNotIn("Check evidence libraries", user_facing_payload)
        self.assertNotIn("public metadata indexes", user_facing_payload)
        _assert_public_payload(payload)

    def test_portal_evidence_source_attach_endpoint_owns_chat_handoff(self) -> None:
        with _running_server() as address:
            status, payload = _request_json(
                "POST",
                address,
                "/api/evidence-sources/attach",
                {
                    "operationId": "research.build_target_packet",
                    "params": {
                        "target_type": "topic",
                        "topic": "rs429358",
                        "unknown": "SHOULD_NOT_LEAK",
                    },
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["surface"], "evidence_source_handoff")
        self.assertEqual(payload["evidenceSource"]["displayLabel"], "Target evidence report")
        self.assertEqual(payload["params"], {"target_type": "topic", "topic": "rs429358"})
        self.assertNotIn("SHOULD_NOT_LEAK", json.dumps(payload))
        self.assertEqual(payload["missingRequiredInputs"], [])
        self.assertIn("Use Target evidence report as the evidence source if it fits my question.", payload["prompt"])
        self.assertIn("Target type: topic; Topic: rs429358", payload["prompt"])
        packet = payload["selectedEvidence"][0]
        self.assertEqual(packet["label"], "Evidence source: Target evidence report")
        self.assertEqual(packet["context_kind"], "tool_request")
        self.assertEqual(packet["source_operation"], "research.build_target_packet")
        self.assertIn(
            {"label": "Inputs provided", "text": "Inputs provided: Target type: topic; Topic: rs429358"},
            packet["selected_nodes"],
        )
        _assert_public_payload(payload)

    def test_portal_evidence_source_attach_reports_missing_condition_inputs(self) -> None:
        with _running_server() as address:
            status, payload = _request_json(
                "POST",
                address,
                "/api/evidence-sources/attach",
                {"operationId": "research.build_target_packet", "params": {"target_type": "gene"}},
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["missingRequiredInputs"], ["gene"])
        self.assertIn("Ask me for: Gene.", payload["prompt"])
        self.assertIn(
            {"label": "Missing required inputs", "text": "Missing required inputs: Gene"},
            payload["packet"]["selected_nodes"],
        )
        self.assertNotRegex(json.dumps(payload), r"\b[Ss]ource checks?\b|\b[Pp]repare\b|\b[Pp]reparation\b")

    def test_portal_does_not_expose_generic_operation_endpoint(self) -> None:
        with _running_server() as address:
            status, _headers, _body = _request_raw(
                "POST",
                address,
                "/api/operation",
                json.dumps({"operation": "genomi.describe_context", "params": {}}).encode("utf-8"),
                _portal_post_headers(address),
            )

        self.assertEqual(status, 404)

    def test_portal_run_create_requires_project_context(self) -> None:
        with _running_server() as address:
            status, _headers, _body = _request_raw(
                "POST",
                address,
                "/api/runs",
                json.dumps({"message": "Resolve rs429358", "agentId": "codex"}).encode("utf-8"),
                _portal_post_headers(address),
            )

        self.assertEqual(status, 400)

    def test_portal_post_requires_json_same_origin_and_csrf_token(self) -> None:
        with _running_server() as address:
            status, payload = _request_json("POST", address, "/api/projects", {"name": "Token OK"})
            missing_status, missing_payload = _request_json(
                "POST",
                address,
                "/api/projects",
                {"name": "No token"},
                include_portal_token=False,
            )
            wrong_origin_headers = _portal_post_headers(address)
            wrong_origin_headers["Origin"] = "http://evil.example"
            wrong_status, wrong_headers, wrong_body = _request_raw(
                "POST",
                address,
                "/api/projects",
                json.dumps({"name": "Wrong origin"}).encode("utf-8"),
                wrong_origin_headers,
            )
            media_headers = _portal_post_headers(address)
            media_headers["Content-Type"] = "text/plain"
            media_status, media_headers_out, media_body = _request_raw(
                "POST",
                address,
                "/api/projects",
                b"name=Wrong media",
                media_headers,
            )

        self.assertEqual(status, 201)
        self.assertEqual(payload["project"]["name"], "Token OK")
        self.assertEqual(missing_status, 403)
        self.assertEqual(missing_payload["error"]["code"], "csrf_required")
        self.assertEqual(wrong_status, 403)
        self.assertEqual(json.loads(wrong_body.decode("utf-8"))["error"]["code"], "forbidden_origin")
        self.assertNotIn("access-control-allow-origin", wrong_headers)
        self.assertEqual(media_status, 415)
        self.assertEqual(json.loads(media_body.decode("utf-8"))["error"]["code"], "unsupported_media_type")
        self.assertNotIn("access-control-allow-origin", media_headers_out)

    def test_portal_rejects_untrusted_host_before_serving_token_or_post(self) -> None:
        with _running_server() as address:
            get_status, _get_headers, _get_body = _request_raw(
                "GET",
                address,
                "/",
                headers={"Host": f"attacker.example:{address[1]}"},
            )
            post_status, _post_headers, _post_body = _request_raw(
                "POST",
                address,
                "/api/projects",
                json.dumps({"name": "Attacker"}).encode("utf-8"),
                {
                    "Host": f"attacker.example:{address[1]}",
                    "Origin": f"http://attacker.example:{address[1]}",
                    "Content-Type": "application/json",
                    "X-Genomi-CSRF": "attacker-token",
                },
            )

        self.assertEqual(get_status, 403)
        self.assertEqual(post_status, 403)

    def test_portal_rejects_non_loopback_client_before_serving_routes(self) -> None:
        with mock.patch.object(mcp._GenomiMCPHTTPRequestHandler, "_portal_client_allowed", return_value=False):
            with _running_server() as address:
                root_status, _root_headers, _root_body = _request_raw("GET", address, "/")
                asset_status, _asset_headers, _asset_body = _request_raw("GET", address, "/assets/portal.js")
                api_status, _api_headers, _api_body = _request_raw("GET", address, "/api/context")
                post_status, _post_headers, _post_body = _request_raw(
                    "POST",
                    address,
                    "/api/projects",
                    json.dumps({"name": "Remote"}).encode("utf-8"),
                    {"Content-Type": "application/json"},
                )
                mcp_status, mcp_payload = _request_json(
                    "POST",
                    address,
                    "/mcp",
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                )

        self.assertEqual(root_status, 403)
        self.assertEqual(asset_status, 403)
        self.assertEqual(api_status, 403)
        self.assertEqual(post_status, 403)
        self.assertEqual(mcp_status, 200)
        self.assertEqual(mcp_payload["result"]["serverInfo"]["name"], "genomi")

    def test_portal_loopback_address_check_rejects_non_loopback_ips(self) -> None:
        self.assertTrue(mcp._is_loopback_host("127.0.0.1"))
        self.assertTrue(mcp._is_loopback_host("::1"))
        self.assertTrue(mcp._is_loopback_host("::ffff:127.0.0.1"))
        self.assertFalse(mcp._is_loopback_host("203.0.113.10"))
        self.assertFalse(mcp._is_loopback_host("example.com"))

    def test_frame_lookup_project_query_rejects_cross_project_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            project = portal_store.create_project(name="One")
            other = portal_store.create_project(name="Two")
            frame = portal_store.create_frame(
                project_id=project["project_id"],
                request="Resolve rs429358",
                agent_id="codex",
            )
            assert frame is not None

            with _running_server() as address:
                ok_status, ok_payload = _request_json(
                    "GET",
                    address,
                    f"/api/frames/{frame['id']}?projectId={project['project_id']}",
                )
                bad_status, bad_payload = _request_json(
                    "GET",
                    address,
                    f"/api/frames/{frame['id']}?projectId={other['project_id']}",
                )

        self.assertEqual(ok_status, 200)
        self.assertEqual(ok_payload["id"], frame["id"])
        _assert_public_payload(ok_payload)
        self.assertEqual(bad_status, 404)
        self.assertEqual(bad_payload["error"]["code"], "not_found")

    def test_project_request_creates_persistent_frame_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}), mock.patch(
            "genomi.interfaces.portal_runs.run_agent", lambda run: None
        ), mock.patch("genomi.interfaces.portal_agents.default_agent_id", return_value="codex"):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Portal Test"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]

                status, frame_payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/request",
                    {
                        "message": "Resolve rs429358",
                        "selectedEvidence": [{"id": "ev-1", "label": "ClinVar node", "text": "ClinVar: hit"}],
                    },
                )
                self.assertEqual(status, 202)
                frame_id = frame_payload["frameId"]

                status, messages = _request_json("GET", address, f"/api/frames/{frame_id}/messages")
                self.assertEqual(status, 200)

                status, frames = _request_json("GET", address, f"/api/projects/{project_id}/frames")

        self.assertEqual(status, 200)
        self.assertEqual(messages["total"], 1)
        self.assertEqual(messages["messages"][0]["role"], "user")
        self.assertEqual(messages["messages"][0]["text"], "Resolve rs429358")
        self.assertEqual(messages["messages"][0]["selected_evidence"][0]["label"], "ClinVar node")
        self.assertEqual(messages["messages"][0]["selected_evidence"][0]["prompt_text"], "ClinVar: hit")
        self.assertEqual(frames["project_id"], project_id)
        self.assertEqual(frames["frames"][0]["id"], frame_id)
        self.assertEqual(frames["frames"][0]["request"], "Resolve rs429358")
        self.assertEqual(frames["frames"][0]["title"], "Resolve rs429358")

    def test_project_conversation_rename_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}), mock.patch(
            "genomi.interfaces.portal_runs.run_agent", lambda run: None
        ), mock.patch("genomi.interfaces.portal_agents.default_agent_id", return_value="codex"):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Rename API"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]
                status, frame_payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/request",
                    {"message": "Resolve rs429358"},
                )
                self.assertEqual(status, 202)
                frame_id = frame_payload["frameId"]

                status, renamed = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/frames/{frame_id}/rename",
                    {"title": "APOE evidence review"},
                )
                frames_status, frames = _request_json("GET", address, f"/api/projects/{project_id}/frames")

        self.assertEqual(status, 200)
        self.assertEqual(frames_status, 200)
        self.assertEqual(renamed["frame"]["title"], "APOE evidence review")
        self.assertEqual(frames["frames"][0]["title"], "APOE evidence review")

    def test_run_create_starts_project_frame_and_followup_message(self) -> None:
        run_modes: list[str] = []

        def _finish_run(run: object) -> None:
            run_modes.append(str(getattr(run, "genome_context_mode")))
            run_id = str(getattr(run, "id"))
            frame_id = str(getattr(run, "frame_id"))
            portal_store.finish_frame(frame_id, status="completed", output="Evidence summary.", run_id=run_id)
            run.finish("succeeded")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}), mock.patch(
            "genomi.interfaces.portal_run_service._start_run_thread", _finish_run
        ), mock.patch("genomi.interfaces.portal_agents.default_agent_id", return_value="codex"):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Run API"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]

                status, first_payload = _request_json(
                    "POST",
                    address,
                    "/api/runs",
                    {
                        "projectId": project_id,
                        "message": "Review CYP2C19 evidence",
                        "genomeContextMode": "public",
                        "selectedEvidence": [{"id": "ev-1", "label": "Medication", "text": "clopidogrel"}],
                    },
                )
                self.assertEqual(status, 202)
                frame_id = first_payload["frameId"]

                status, followup_payload = _request_json(
                    "POST",
                    address,
                    "/api/runs",
                    {
                        "project_id": project_id,
                        "frame_id": frame_id,
                        "message": "What evidence changed?",
                        "genome_context_mode": "auto",
                    },
                )
                self.assertEqual(status, 202)

                status, messages = _request_json("GET", address, f"/api/frames/{frame_id}/messages")

        self.assertEqual(followup_payload["frameId"], frame_id)
        self.assertNotEqual(first_payload["runId"], followup_payload["runId"])
        self.assertEqual(status, 200)
        self.assertEqual([message["role"] for message in messages["messages"]], ["user", "assistant", "user", "assistant"])
        user_messages = [message for message in messages["messages"] if message["role"] == "user"]
        assistant_messages = [message for message in messages["messages"] if message["role"] == "assistant"]
        self.assertEqual([message["text"] for message in user_messages], ["Review CYP2C19 evidence", "What evidence changed?"])
        self.assertEqual(user_messages[0]["selected_evidence"][0]["prompt_text"], "clopidogrel")
        self.assertEqual([message["text"] for message in assistant_messages], ["Evidence summary.", "Evidence summary."])
        self.assertEqual(run_modes, ["public", "auto"])

    def test_run_create_new_frame_records_selected_material_handoff(self) -> None:
        def _finish_run(run: object) -> None:
            run_id = str(getattr(run, "id"))
            frame_id = str(getattr(run, "frame_id"))
            portal_store.finish_frame(frame_id, status="completed", output="Focused answer.", run_id=run_id)
            run.finish("succeeded")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}), mock.patch(
            "genomi.interfaces.portal_run_service._start_run_thread", _finish_run
        ), mock.patch("genomi.interfaces.portal_agents.default_agent_id", return_value="codex"):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Run handoff"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]

                status, first_payload = _request_json(
                    "POST",
                    address,
                    "/api/runs",
                    {"projectId": project_id, "message": "Build an APOE report"},
                )
                self.assertEqual(status, 202)

                status, focused_payload = _request_json(
                    "POST",
                    address,
                    "/api/runs",
                    {
                        "projectId": project_id,
                        "sourceFrameId": first_payload["frameId"],
                        "startedFromSelectedMaterial": True,
                        "message": "Use this report as context.",
                        "selectedEvidence": [
                            {
                                "id": "file-1",
                                "label": "Project file: reports/apoe.md",
                                "text": "APOE report excerpt",
                            }
                        ],
                    },
                )
                self.assertEqual(status, 202)

                status, frames = _request_json("GET", address, f"/api/projects/{project_id}/frames")
                messages_status, messages = _request_json("GET", address, f"/api/frames/{focused_payload['frameId']}/messages")

        by_id = {frame["id"]: frame for frame in frames["frames"]}
        self.assertEqual(status, 200)
        self.assertEqual(messages_status, 200)
        self.assertEqual(set(by_id), {first_payload["frameId"], focused_payload["frameId"]})
        self.assertEqual(by_id[focused_payload["frameId"]]["started_from"]["summary"], "Started from Project file: reports/apoe.md")
        self.assertEqual(by_id[focused_payload["frameId"]]["started_from"]["material_count"], 1)
        self.assertEqual(messages["messages"][0]["selected_evidence"][0]["label"], "Project file: reports/apoe.md")
        self.assertNotIn("source_frame_id", json.dumps(by_id[focused_payload["frameId"]]["started_from"]))
        _assert_public_payload(frames)
        _assert_public_payload(messages)

    def test_run_cancel_uses_run_service_state_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}), mock.patch(
            "genomi.interfaces.portal_run_service._start_run_thread", lambda run: None
        ):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Cancel API"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]

                status, run_payload = _request_json(
                    "POST",
                    address,
                    "/api/runs",
                    {
                        "projectId": project_id,
                        "message": "Build a cancelable report",
                        "agentId": "codex",
                    },
                )
                self.assertEqual(status, 202)
                run_id = run_payload["runId"]

                cancel_status, cancel_payload = _request_json("POST", address, f"/api/runs/{run_id}/cancel", {})
                terminal_status, terminal_payload = _request_json("POST", address, f"/api/runs/{run_id}/cancel", {})
                missing_status, missing_payload = _request_json("POST", address, "/api/runs/missing-run/cancel", {})

        self.assertEqual(cancel_status, 200)
        self.assertEqual(cancel_payload["ok"], True)
        self.assertEqual(cancel_payload["run"]["status"], "canceled")
        self.assertTrue(cancel_payload["run"]["terminal"])
        self.assertEqual(terminal_status, 409)
        self.assertEqual(terminal_payload["error"]["code"], "run_terminal")
        self.assertEqual(terminal_payload["run"]["status"], "canceled")
        self.assertEqual(missing_status, 404)
        self.assertEqual(missing_payload["error"]["code"], "not_found")
        portal_run_events.discard_run(run_id)

    def test_run_permission_approval_route_retries_from_portal(self) -> None:
        result = {
            "status": "running",
            "runId": "retry_run_1",
            "frameId": "frame_1",
            "rootFrameId": "frame_1",
            "approvedTool": "mcp__genomi__genomi_describe_context",
        }
        with mock.patch(
            "genomi.interfaces.portal_run_service.approve_run_permission_and_retry",
            return_value=result,
        ) as approve:
            with _running_server() as address:
                status, payload = _request_json(
                    "POST",
                    address,
                    "/api/runs/source_run_1/approve-permission",
                    {"permission": {"tool": "mcp__genomi__genomi_describe_context"}},
                )
                missing_token_status, missing_token_payload = _request_json(
                    "POST",
                    address,
                    "/api/runs/source_run_2/approve-permission",
                    {"permission": {"tool": "mcp__genomi__genomi_describe_context"}},
                    include_portal_token=False,
                )

        self.assertEqual(status, 202)
        self.assertEqual(payload["runId"], "retry_run_1")
        self.assertEqual(payload["approvedTool"], "mcp__genomi__genomi_describe_context")
        approve.assert_called_once_with(
            run_id="source_run_1",
            permission={"tool": "mcp__genomi__genomi_describe_context"},
        )
        self.assertEqual(missing_token_status, 403)
        self.assertEqual(missing_token_payload["error"]["code"], "csrf_required")

    def test_run_result_package_returns_public_workspace_handoff(self) -> None:
        def _finish_run(run: object) -> None:
            run.emit("agent", {"type": "diagnostic", "name": "package_test", "message": "ready from /Users/private"})
            run_id = str(getattr(run, "id"))
            frame_id = str(getattr(run, "frame_id"))
            portal_store.finish_frame(frame_id, status="completed", output="Evidence summary.", run_id=run_id)
            run.finish("succeeded")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}), mock.patch(
            "genomi.interfaces.portal_run_service._start_run_thread", _finish_run
        ), mock.patch(
            "genomi.interfaces.portal_context.prompt_context_payload",
            return_value={"activeGenomeIndex": {"available": False, "accessApproved": False}},
        ):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Package API"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]
                workspace = portal_workspaces.ensure_project_workspace(project_id)
                (workspace / "reports").mkdir(parents=True, exist_ok=True)
                (workspace / "reports" / "summary.txt").write_text("APOE evidence\n", encoding="utf-8")

                status, run_payload = _request_json(
                    "POST",
                    address,
                    "/api/runs",
                    {
                        "projectId": project_id,
                        "message": "Build an APOE evidence report",
                        "agentId": "codex",
                        "selectedEvidence": [{"id": "ev-1", "label": "Variant", "text": "rs429358"}],
                    },
                )
                self.assertEqual(status, 202)
                run_id = run_payload["runId"]
                frame_id = run_payload["frameId"]
                artifact = portal_store.add_artifact_from_bytes(
                    project_id,
                    kind="evidence_report",
                    renderer="markdown",
                    title="APOE evidence report",
                    operation="variant.resolve",
                    result={"status": "completed", "source": "/Users/private/result"},
                    original_filename="apoe.md",
                    content_type="text/markdown",
                    body=b"# APOE evidence\n",
                    frame_id=frame_id,
                    summary={"finding": "APOE evidence"},
                )
                self.assertIsNotNone(artifact)

                status, package = _request_json("GET", address, f"/api/runs/{run_id}/result-package")

        self.assertEqual(status, 200)
        self.assertEqual(package["schema"], "genomi_portal_run_result_package")
        self.assertEqual(package["run"]["id"], run_id)
        self.assertEqual(package["run"]["status"], "succeeded")
        self.assertTrue(package["run"]["terminal"])
        self.assertEqual(package["project"]["project_id"], project_id)
        self.assertEqual(package["frame"]["id"], frame_id)
        self.assertEqual(package["messages"]["total"], 2)
        self.assertEqual(package["messages"]["messages"][0]["text"], "Build an APOE evidence report")
        self.assertEqual(package["messages"]["messages"][0]["selected_evidence"][0]["prompt_text"], "rs429358")
        self.assertEqual(package["artifacts"]["count"], 1)
        self.assertEqual(package["artifacts"]["items"][0]["artifact"]["title"], "APOE evidence report")
        self.assertEqual(package["workspace_files"]["summary"]["total_files"], 1)
        self.assertEqual(package["workspace_files"]["files"][0]["relative_path"], "reports/summary.txt")
        self.assertTrue(package["events"]["available"])
        self.assertTrue(any(item["event"] == "agent" for item in package["events"]["items"]))
        self.assertEqual(package["genome_context"]["activeGenomeIndex"]["available"], False)
        _assert_public_payload(package)

    def test_run_event_page_returns_bounded_sanitized_events(self) -> None:
        def _finish_run(run: object) -> None:
            run.emit("agent", {"type": "diagnostic", "name": "event_page_test", "message": "ready from /Users/private"})
            run_id = str(getattr(run, "id"))
            frame_id = str(getattr(run, "frame_id"))
            portal_store.finish_frame(frame_id, status="completed", output="Evidence summary.", run_id=run_id)
            run.finish("succeeded")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}), mock.patch(
            "genomi.interfaces.portal_run_service._start_run_thread", _finish_run
        ):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Event Page API"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]
                status, run_payload = _request_json(
                    "POST",
                    address,
                    "/api/runs",
                    {
                        "projectId": project_id,
                        "message": "Build an event page report",
                        "agentId": "codex",
                    },
                )
                self.assertEqual(status, 202)
                run_id = run_payload["runId"]
                status, first_page = _request_json("GET", address, f"/api/runs/{run_id}/event-page?limit=1")
                next_after = first_page["next_after_event_id"]
                next_status, next_page = _request_json("GET", address, f"/api/runs/{run_id}/event-page?after_event_id={next_after}&limit=10")
                missing_status, missing_page = _request_json("GET", address, "/api/runs/missing-run/event-page")

        self.assertEqual(status, 200)
        self.assertEqual(first_page["schema"], "genomi_portal_run_event_page")
        self.assertEqual(first_page["run_id"], run_id)
        self.assertEqual(first_page["source"], "durable_log")
        self.assertEqual(first_page["returned"], 1)
        self.assertTrue(first_page["truncated"])
        self.assertEqual(next_status, 200)
        self.assertEqual(next_page["after_event_id"], next_after)
        self.assertFalse(next_page["truncated"])
        self.assertTrue(any(item["event"] == "agent" for item in next_page["items"]))
        self.assertEqual(missing_status, 404)
        self.assertEqual(missing_page["error"]["code"], "not_found")
        _assert_public_payload(first_page)
        _assert_public_payload(next_page)

    def test_terminal_run_event_stream_replays_logged_end_after_restart(self) -> None:
        def _finish_run(run: object) -> None:
            run.emit("agent", {"type": "diagnostic", "name": "replay_test", "message": "ready"})
            run_id = str(getattr(run, "id"))
            frame_id = str(getattr(run, "frame_id"))
            portal_store.finish_frame(frame_id, status="completed", output="Evidence summary.", run_id=run_id)
            run.finish("succeeded")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}), mock.patch(
            "genomi.interfaces.portal_run_service._start_run_thread", _finish_run
        ):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Replay API"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]
                status, run_payload = _request_json(
                    "POST",
                    address,
                    "/api/runs",
                    {
                        "projectId": project_id,
                        "message": "Build an evidence report",
                        "agentId": "codex",
                    },
                )
                self.assertEqual(status, 202)
                run_id = run_payload["runId"]
                portal_run_events.discard_run(run_id)

                connection = http.client.HTTPConnection(address[0], address[1], timeout=5)
                try:
                    connection.request("GET", f"/api/runs/{run_id}/events?after=2")
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    event = _read_sse_event(response)
                finally:
                    connection.close()

        self.assertEqual(event["id"], "3")
        self.assertEqual(event["event"], "end")
        self.assertEqual(event["data"], {"status": "succeeded", "error": None})

    def test_project_workspace_files_endpoint_lists_relative_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            project = portal_store.create_project(name="Workspace Files")
            workspace = portal_workspaces.ensure_project_workspace(project["project_id"])
            (workspace / "reports").mkdir(parents=True, exist_ok=True)
            (workspace / "reports" / "apoe.txt").write_text("APOE report\n", encoding="utf-8")

            with _running_server() as address:
                status, payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project['project_id']}/workspace/files",
                )

        self.assertEqual(status, 200)
        self.assertEqual(payload["summary"]["total_files"], 1)
        self.assertEqual(payload["files"][0]["relative_path"], "reports/apoe.txt")
        self.assertNotIn(str(workspace), str(payload))
        _assert_public_payload(payload)

    def test_project_workspace_file_preview_endpoint_returns_bounded_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            project = portal_store.create_project(name="Workspace File Preview")
            workspace = portal_workspaces.ensure_project_workspace(project["project_id"])
            (workspace / "reports").mkdir(parents=True, exist_ok=True)
            (workspace / "reports" / "apoe.txt").write_text("APOE report\n", encoding="utf-8")

            with _running_server() as address:
                status, payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project['project_id']}/workspace/file-preview?path=reports%2Fapoe.txt",
                )
                missing_status, missing_payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project['project_id']}/workspace/file-preview",
                )
                escaped_status, escaped_payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project['project_id']}/workspace/file-preview?path=..%2Foutside.txt",
                )
                not_found_status, not_found_payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project['project_id']}/workspace/file-preview?path=reports%2Fmissing.txt",
                )

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["preview_kind"], "text")
        self.assertEqual(payload["relative_path"], "reports/apoe.txt")
        self.assertIn("APOE report", payload["text"])
        self.assertEqual(missing_status, 400)
        self.assertEqual(missing_payload["status"], "missing_path")
        self.assertEqual(missing_payload["error"]["code"], "missing_path")
        self.assertEqual(escaped_status, 400)
        self.assertEqual(escaped_payload["status"], "path_escape")
        self.assertEqual(escaped_payload["error"]["code"], "path_escape")
        self.assertEqual(not_found_status, 404)
        self.assertEqual(not_found_payload["status"], "not_found")
        self.assertEqual(not_found_payload["error"]["code"], "not_found")
        _assert_public_payload(payload)
        _assert_public_payload(missing_payload)
        _assert_public_payload(escaped_payload)
        _assert_public_payload(not_found_payload)

    def test_project_workspace_document_endpoint_streams_pdf_inside_project_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            project = portal_store.create_project(name="Workspace Document Preview")
            workspace = portal_workspaces.ensure_project_workspace(project["project_id"])
            (workspace / "papers").mkdir(parents=True, exist_ok=True)
            pdf_body = b"%PDF-1.4\n% Genomi test PDF\n"
            (workspace / "papers" / "review.pdf").write_bytes(pdf_body)
            (workspace / "papers" / "notes.txt").write_text("notes\n", encoding="utf-8")

            with _running_server() as address:
                preview_status, preview_payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project['project_id']}/workspace/file-preview?path=papers%2Freview.pdf",
                )
                file_status, file_headers, file_body = _request_raw(
                    "GET",
                    address,
                    f"/api/projects/{project['project_id']}/workspace/file?path=papers%2Freview.pdf",
                )
                text_status, text_payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project['project_id']}/workspace/file?path=papers%2Fnotes.txt",
                )
                escaped_status, escaped_payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project['project_id']}/workspace/file?path=..%2Foutside.pdf",
                )

        self.assertEqual(preview_status, 200)
        self.assertEqual(preview_payload["preview_kind"], "document")
        self.assertEqual(file_status, 200)
        self.assertEqual(file_headers["content-type"], "application/pdf")
        self.assertEqual(file_headers["content-disposition"], 'inline; filename="review-pdf"')
        self.assertEqual(file_body, pdf_body)
        self.assertEqual(text_status, 415)
        self.assertEqual(text_payload["error"]["code"], "unsupported_type")
        self.assertEqual(escaped_status, 400)
        self.assertEqual(escaped_payload["error"]["code"], "path_escape")
        _assert_public_payload(preview_payload)
        _assert_public_payload(text_payload)
        _assert_public_payload(escaped_payload)

    def test_project_events_endpoint_streams_workspace_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            project = portal_store.create_project(name="Evented")
            project_id = str(project["project_id"])
            self.addCleanup(portal_project_events.discard_project_events, project_id, root=tmp)

            with _running_server() as address:
                connection = http.client.HTTPConnection(address[0], address[1], timeout=5)
                try:
                    connection.request("GET", f"/api/projects/{project_id}/events")
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertIn("text/event-stream", response.getheader("content-type", ""))
                    ready = _read_sse_event(response)
                    self.assertEqual(ready["event"], "ready")

                    frame = portal_store.create_frame(
                        project_id=project_id,
                        request="Resolve rs429358",
                        agent_id="codex",
                    )
                    assert frame is not None
                    frame_event = _read_sse_until(response, "frame_changed")
                    messages_event = _read_sse_until(response, "messages_changed")
                    project_event = _read_sse_until(response, "project_changed")
                finally:
                    connection.close()

        self.assertEqual(frame_event["data"]["project_id"], project_id)
        self.assertEqual(frame_event["data"]["frame_id"], frame["id"])
        self.assertEqual(frame_event["data"]["reason"], "created")
        self.assertEqual(messages_event["data"]["project_id"], project_id)
        self.assertEqual(messages_event["data"]["frame_id"], frame["id"])
        self.assertEqual(messages_event["data"]["reason"], "created")
        self.assertEqual(project_event["data"]["project_id"], project_id)
        self.assertEqual(project_event["data"]["reason"], "frame_created")
        _assert_public_payload(frame_event["data"])
        _assert_public_payload(messages_event["data"])
        _assert_public_payload(project_event["data"])

    def test_project_artifact_render_route_requires_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Portal Test"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]

                status, payload = _request_json("POST", address, f"/api/projects/{project_id}/artifacts/render", {})

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "missing_renderer")

    def test_project_artifact_render_route_persists_decode_artifact(self) -> None:
        captured: dict[str, object] = {}

        def _fake_call(operation: str, params: dict[str, object]) -> dict[str, object]:
            captured["operation"] = operation
            captured["params"] = params
            output = str(params["output"])
            with open(output, "w", encoding="utf-8") as handle:
                handle.write("<!doctype html><title>Dashboard</title>")
            return {
                "status": "completed",
                "dashboard_path": output,
                "panels_rendered": ["clinvar"],
                "panels_empty": ["prs"],
                "serve": {"status": "running", "url": "http://127.0.0.1:9000/dashboard.html"},
            }

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}), mock.patch(
            "genomi.interfaces.portal_artifact_renderers.call_operation", side_effect=_fake_call
        ):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Portal Test"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]

                status, render_payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/artifacts/render",
                    {"renderer": "decode_dashboard"},
                )
                self.assertEqual(status, 202)
                self.assertIn("runId", render_payload)
                status, run_status = _request_json("GET", address, f"/api/runs/{render_payload['runId']}")
                self.assertEqual(status, 200)
                self.assertEqual(run_status["kind"], "artifact_render")
                self.assertNotIn("agentId", run_status)

                status, artifacts = _wait_for_project_artifacts(address, project_id)

        self.assertEqual(captured["operation"], "decode.render_dashboard")
        self.assertIn(f"portal/artifacts/{project_id}/dashboard.html", str(captured["params"]["output"]))
        self.assertEqual(status, 200)
        self.assertEqual(artifacts["artifacts"][0]["kind"], "decode_dashboard")
        self.assertEqual(artifacts["artifacts"][0]["renderer"], "decode_dashboard")
        self.assertEqual(artifacts["artifacts"][0]["title"], "Genomi Report")
        self.assertEqual(artifacts["artifacts"][0]["summary"]["panels_rendered"], ["clinvar"])
        self.assertEqual(artifacts["artifacts"][0]["summary_lines"][:3], ["completed", "1 section rendered", "1 empty"])
        self.assertEqual(artifacts["artifacts"][0]["open_label"], "Open report")
        self.assertEqual(artifacts["artifacts"][0]["operation"], "decode.render_dashboard")
        artifact_id = artifacts["artifacts"][0]["id"]
        self.assertEqual(artifacts["artifacts"][0]["url"], "http://127.0.0.1:9000/dashboard.html")
        self.assertEqual(artifacts["artifacts"][0]["preview_url"], f"/api/projects/{project_id}/artifacts/{artifact_id}/file")
        self.assertTrue(artifacts["artifacts"][0]["latest_version_id"].startswith("ver_"))
        self.assertEqual(artifacts["artifacts"][0]["version_count"], 1)
        self.assertEqual(artifacts["artifacts"][0]["latest_version"]["content_type"], "text/html")
        self.assertTrue(artifacts["artifacts"][0]["latest_version"]["checksum"].startswith("sha256:"))
        _assert_public_payload(artifacts)

    def test_project_dashboard_artifact_file_can_be_served_by_portal(self) -> None:
        captured: dict[str, object] = {}

        def _fake_call(operation: str, params: dict[str, object]) -> dict[str, object]:
            captured["operation"] = operation
            captured["params"] = params
            output = str(params["output"])
            with open(output, "w", encoding="utf-8") as handle:
                handle.write("<!doctype html><title>Dashboard</title>")
            return {
                "status": "completed",
                "dashboard_path": output,
                "panels_rendered": ["clinvar"],
                "panels_empty": [],
            }

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}), mock.patch(
            "genomi.interfaces.portal_artifact_renderers.call_operation", side_effect=_fake_call
        ):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Portal Test"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]

                status, render_payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/artifacts/render",
                    {"renderer": "decode_dashboard"},
                )
                self.assertEqual(status, 202)
                self.assertIn("runId", render_payload)
                status, artifacts = _wait_for_project_artifacts(address, project_id)
                self.assertEqual(status, 200)
                artifact_url = artifacts["artifacts"][0]["preview_url"]

                status, headers, body = _request_raw("GET", address, artifact_url)

        self.assertEqual(captured["operation"], "decode.render_dashboard")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])
        csp = headers["content-security-policy"]
        self.assertIn("sandbox", csp)
        self.assertIn("allow-scripts", csp)
        self.assertNotIn("allow-same-origin", csp)
        self.assertIn("connect-src 'none'", csp)
        self.assertIn("form-action 'none'", csp)
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertIn(b"<title>Dashboard</title>", body)

    def test_project_artifact_render_route_persists_evidence_packet_artifact(self) -> None:
        captured: list[tuple[str, dict[str, object]]] = []

        def _fake_call(operation: str, params: dict[str, object]) -> dict[str, object]:
            captured.append((operation, dict(params)))
            topic = str(params.get("topic") or "unknown")
            return {
                "purpose": "Target-centric packet for a focused evidence review.",
                "target": {"target_type": "topic", "target_id": f"topic:{topic}", "topic": topic},
                "stored_research": {"count": 0, "records": []},
                "source_catalog": {
                    "summary": {"source_count": 5},
                    "sources": [
                        {"source_id": "clinvar", "title": "ClinVar", "best_for": "Variant assertions"},
                        {"source_id": "gwas_catalog", "title": "GWAS Catalog", "best_for": "Trait associations"},
                    ],
                },
                "available_operations": [
                    {"name": "list sources", "tool": "research.list_sources", "relevance": "source catalog"},
                    {"name": "record finding", "tool": "research.record", "relevance": "write-back"},
                ],
                "evidence_options": [
                    {"component": "stored_research", "state": "absent", "available_operation": "research.record"}
                ],
                "evidence_envelope": {
                    "operation": "research.build_target_packet",
                    "headline": "research.build_target_packet: evidence_present · scoped_answer_only",
                    "finding_state": "evidence_present",
                    "answer_readiness": "scoped_answer_only",
                },
            }

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}), mock.patch(
            "genomi.interfaces.portal_artifact_renderers.call_operation", side_effect=_fake_call
        ):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Portal Test"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]

                status, render_payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/artifacts/render",
                    {"renderer": "evidence_packet", "target_type": "topic", "topic": "rs429358", "limit": 3},
                )
                self.assertEqual(status, 202)
                status, artifacts = _wait_for_project_artifacts(address, project_id)
                self.assertEqual(status, 200)
                first_artifact = artifacts["artifacts"][0]

                status, render_payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/artifacts/render",
                    {
                        "renderer": "evidence_packet",
                        "target": {"target_type": "topic", "topic": "CYP2C19"},
                        "limit": 4,
                    },
                )
                self.assertEqual(status, 202)
                status, artifacts = _wait_for_project_artifacts(address, project_id, count=2)
                self.assertEqual(status, 200)
                by_title = {artifact["title"]: artifact for artifact in artifacts["artifacts"]}
                second_artifact = by_title["Evidence report: CYP2C19"]
                first_status, first_headers, first_body = _request_raw("GET", address, first_artifact["preview_url"])
                second_status, second_headers, second_body = _request_raw("GET", address, second_artifact["preview_url"])
                artifact_detail_status, artifact_detail = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project_id}/artifacts/{first_artifact['id']}",
                )
                versions_status, versions_payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project_id}/artifacts/{first_artifact['id']}/versions",
                )
                first_stored = portal_store.get_artifact(first_artifact["id"])
                second_stored = portal_store.get_artifact(second_artifact["id"])
                assert first_stored is not None
                assert second_stored is not None
                version_id = first_stored["latest_version_id"]
                first_version = portal_store.get_artifact_version(version_id)
                second_version = portal_store.get_artifact_version(second_stored["latest_version_id"])
                version_status, version_payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project_id}/artifacts/{first_artifact['id']}/versions/{version_id}",
                )
                version_file_status, version_file_headers, version_file_body = _request_raw(
                    "GET",
                    address,
                    f"/api/projects/{project_id}/artifacts/{first_artifact['id']}/versions/{version_id}/file",
                )
                script_bundle_status, script_bundle_headers, script_bundle_body = _request_raw(
                    "GET",
                    address,
                    f"/api/projects/{project_id}/artifacts/{first_artifact['id']}/versions/{version_id}/script-bundle",
                )
                review_run_status, review_run_payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/artifacts/{first_artifact['id']}/versions/{version_id}/review-runs",
                    {},
                )
                reviewed_version_status, reviewed_version_payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project_id}/artifacts/{first_artifact['id']}/versions/{version_id}",
                )
                missing_review_status, missing_review_payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/artifacts/{first_artifact['id']}/versions/ver_missing/review-runs",
                    {},
                )

        self.assertEqual(captured[0][0], "research.build_target_packet")
        self.assertEqual(captured[0][1]["target_type"], "topic")
        self.assertEqual(captured[0][1]["topic"], "rs429358")
        self.assertEqual(captured[0][1]["limit"], 3)
        self.assertEqual(captured[1][0], "research.build_target_packet")
        self.assertEqual(captured[1][1]["target_type"], "topic")
        self.assertEqual(captured[1][1]["topic"], "CYP2C19")
        self.assertEqual(captured[1][1]["limit"], 4)
        assert first_version is not None
        assert second_version is not None
        self.assertNotIn("path", first_stored)
        self.assertNotIn("result", first_stored)
        self.assertNotIn("latest_version", first_stored)
        self.assertNotIn("path", first_version)
        self.assertNotEqual(first_version["filename"], second_version["filename"])
        self.assertNotEqual(first_version["filename"], "evidence-packet.html")
        self.assertTrue(first_stored["latest_version_id"].startswith("ver_"))
        self.assertEqual(first_stored["version_count"], 1)
        artifact = first_artifact
        self.assertEqual(artifact["kind"], "evidence_packet")
        self.assertEqual(artifact["renderer"], "evidence_packet")
        self.assertEqual(artifact["operation"], "research.build_target_packet")
        self.assertEqual(artifact["title"], "Evidence report: rs429358")
        self.assertEqual(artifact["summary"]["source_catalog"]["summary"]["source_count"], 5)
        self.assertEqual(len(artifact["summary"]["available_operations"]), 2)
        self.assertEqual(artifact["summary"]["stored_research"]["count"], 0)
        self.assertEqual(artifact["summary_lines"][:3], ["Evidence present", "5 sources", "0 stored findings"])
        self.assertEqual(artifact["open_label"], "Open report")
        self.assertEqual(artifact["latest_version_id"], first_stored["latest_version_id"])
        self.assertEqual(artifact["version_count"], 1)
        self.assertEqual(artifact["latest_version"]["content_type"], "text/html")
        self.assertTrue(artifact["latest_version"]["checksum"].startswith("sha256:"))
        self.assertEqual(
            artifact["latest_version"]["file_url"],
            f"/api/projects/{project_id}/artifacts/{first_artifact['id']}/versions/{first_stored['latest_version_id']}/file",
        )
        self.assertEqual(first_status, 200)
        self.assertIn("text/html", first_headers["content-type"])
        self.assertIn(b"Evidence report: rs429358", first_body)
        self.assertIn(b"topic:rs429358", first_body)
        self.assertNotIn(b"Evidence report: CYP2C19", first_body)
        self.assertIn(b"<span>Sources</span><strong>5</strong>", first_body)
        self.assertIn(b"ClinVar", first_body)
        self.assertEqual(second_status, 200)
        self.assertIn("text/html", second_headers["content-type"])
        self.assertIn(b"Evidence report: CYP2C19", second_body)
        self.assertNotIn(b"Evidence report: rs429358", second_body)
        self.assertEqual(artifact_detail_status, 200)
        self.assertEqual(artifact_detail["id"], first_artifact["id"])
        self.assertEqual(artifact_detail["latest_version_id"], first_stored["latest_version_id"])
        self.assertEqual(versions_status, 200)
        self.assertEqual(versions_payload["latest_version_id"], first_stored["latest_version_id"])
        self.assertEqual([item["version_id"] for item in versions_payload["versions"]], [first_stored["latest_version_id"]])
        self.assertEqual(version_status, 200)
        self.assertEqual(version_payload["version_id"], first_stored["latest_version_id"])
        self.assertEqual(version_payload["artifact_id"], first_artifact["id"])
        self.assertEqual(version_payload["content_type"], "text/html")
        self.assertTrue(version_payload["checksum"].startswith("sha256:"))
        self.assertNotIn("environment", artifact)
        self.assertNotIn("environment", artifact["latest_version"])
        self.assertEqual(artifact_detail["environment"]["operation"], "research.build_target_packet")
        self.assertEqual(version_payload["environment"]["operation"], "research.build_target_packet")
        self.assertEqual(versions_payload["versions"][0]["environment"], version_payload["environment"])
        self.assertIn("python_version", version_payload["environment"]["runtime"])
        self.assertIn("library_count", version_payload["environment"]["libraries"]["summary"])
        self.assertEqual(version_payload["file_url"], f"/api/projects/{project_id}/artifacts/{first_artifact['id']}/versions/{version_id}/file")
        self.assertNotIn("path", version_payload)
        self.assertEqual(version_file_status, 200)
        self.assertIn("text/html", version_file_headers["content-type"])
        self.assertIn(b"Evidence report: rs429358", version_file_body)
        self.assertNotIn(b"Evidence report: CYP2C19", version_file_body)
        self.assertEqual(script_bundle_status, 200)
        self.assertIn("application/zip", script_bundle_headers["content-type"])
        self.assertIn("-rebuild.zip", script_bundle_headers["content-disposition"])
        with zipfile.ZipFile(io.BytesIO(script_bundle_body)) as archive:
            script_names = archive.namelist()
            script_manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            script_recipe = json.loads(archive.read("rebuild-recipe.json").decode("utf-8"))
            rebuild_script = archive.read("rebuild.sh").decode("utf-8")
        self.assertEqual({"manifest.json", "rebuild-recipe.json", "rebuild.sh", "README.md"}, set(script_names))
        self.assertEqual(script_manifest["schema"], "genomi_portal_artifact_script_bundle")
        self.assertEqual(script_manifest["version_id"], version_id)
        self.assertEqual(script_recipe["status"], "ready")
        self.assertIn("genomi call research.build_target_packet", rebuild_script)
        self.assertEqual(review_run_status, 201)
        self.assertEqual(review_run_payload["review_run"]["kind"], "artifact_review_run")
        self.assertEqual(review_run_payload["review_run"]["status"], "completed")
        self.assertEqual(review_run_payload["review_run"]["version_id"], version_id)
        self.assertEqual(review_run_payload["review_run"]["check_status"], review_run_payload["version"]["review"]["status"])
        self.assertEqual(reviewed_version_status, 200)
        self.assertEqual(len(reviewed_version_payload["review"]["review_runs"]), 1)
        self.assertEqual(reviewed_version_payload["review"]["review_runs"][0]["status"], "completed")
        self.assertEqual(reviewed_version_payload["review"]["review_runs"][0]["check_status"], reviewed_version_payload["review"]["status"])
        self.assertEqual(missing_review_status, 404)
        self.assertEqual(missing_review_payload["error"]["message"], "artifact version not found")
        _assert_public_payload(artifacts)
        _assert_public_payload(artifact_detail)
        _assert_public_payload(versions_payload)
        _assert_public_payload(version_payload)
        _assert_public_payload(review_run_payload)
        _assert_public_payload(reviewed_version_payload)
        _assert_public_payload(script_manifest)
        _assert_public_payload(script_recipe)
        _assert_public_payload(rebuild_script)

    def test_project_artifact_render_route_fails_evidence_packet_without_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Portal Test"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]

                status, render_payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/artifacts/render",
                    {"renderer": "evidence_packet"},
                )
                self.assertEqual(status, 202)
                status, run_status = _wait_for_run_status(address, render_payload["runId"], "failed")
                self.assertEqual(status, 200)
                status, artifacts = _request_json("GET", address, f"/api/projects/{project_id}/artifacts")

        self.assertEqual(run_status["status"], "failed")
        self.assertIn("target_type is required", run_status["error"])
        self.assertEqual(status, 200)
        self.assertEqual(artifacts["artifacts"], [])

    def test_mcp_endpoint_reuses_initialize_handler(self) -> None:
        request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}

        with _running_server() as address:
            status, payload = _request_json("POST", address, "/mcp?view=default", request)

        self.assertEqual(status, 200)
        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["id"], 1)
        self.assertEqual(payload["result"]["serverInfo"]["name"], "genomi")
        self.assertEqual(payload["result"]["capabilities"], {"tools": {}})

    def test_initialized_notification_returns_accepted_without_body(self) -> None:
        request = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}

        with _running_server() as address:
            status, payload = _request_json("POST", address, "/mcp", request)

        self.assertEqual(status, 202)
        self.assertIsNone(payload)


class _running_server:
    def __enter__(self) -> tuple[str, int]:
        self.server = mcp.make_http_server("127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.server.server_address

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


def _request_json(
    method: str,
    address: tuple[str, int],
    path: str,
    payload: object | None = None,
    *,
    include_portal_token: bool = True,
) -> tuple[int, object | None]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if body is not None and method.upper() == "POST" and not path.startswith("/mcp") and include_portal_token:
        headers.update(_portal_post_headers(address))
    connection = http.client.HTTPConnection(address[0], address[1], timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        parsed = json.loads(data.decode("utf-8")) if data else None
        return response.status, parsed
    finally:
        connection.close()


def _request_raw(
    method: str,
    address: tuple[str, int],
    path: str,
    payload: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection(address[0], address[1], timeout=5)
    try:
        connection.request(method, path, body=payload, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        headers = {key.lower(): value for key, value in response.getheaders()}
        return response.status, headers, data
    finally:
        connection.close()


def _portal_post_headers(address: tuple[str, int]) -> dict[str, str]:
    status, _headers, body = _request_raw("GET", address, "/")
    if status != 200:
        raise AssertionError(f"portal root returned {status}")
    text = body.decode("utf-8")
    match = re.search(r'name="genomi-csrf-token" content="([^"]+)"', text)
    if not match:
        raise AssertionError("portal root did not include csrf token")
    origin = f"http://{address[0]}:{address[1]}"
    return {
        "Content-Type": "application/json",
        "Origin": origin,
        "X-Genomi-CSRF": match.group(1),
    }


def _wait_for_project_artifacts(address: tuple[str, int], project_id: str, *, count: int = 1) -> tuple[int, object]:
    deadline = time.time() + 5
    last_status = 0
    last_payload: object = None
    while time.time() < deadline:
        last_status, last_payload = _request_json("GET", address, f"/api/projects/{project_id}/artifacts")
        artifacts = last_payload.get("artifacts") if isinstance(last_payload, dict) else None
        if isinstance(artifacts, list) and len(artifacts) >= count:
            return last_status, last_payload
        time.sleep(0.05)
    return last_status, last_payload


def _wait_for_run_status(address: tuple[str, int], run_id: str, expected_status: str) -> tuple[int, object]:
    deadline = time.time() + 5
    last_status = 0
    last_payload: object = None
    while time.time() < deadline:
        last_status, last_payload = _request_json("GET", address, f"/api/runs/{run_id}")
        if isinstance(last_payload, dict) and last_payload.get("status") == expected_status:
            return last_status, last_payload
        time.sleep(0.05)
    return last_status, last_payload


def _read_sse_until(response: http.client.HTTPResponse, expected_event: str) -> dict[str, object]:
    deadline = time.time() + 5
    while time.time() < deadline:
        event = _read_sse_event(response)
        if event["event"] == expected_event:
            return event
    raise AssertionError(f"SSE event {expected_event!r} was not received")


def _read_sse_event(response: http.client.HTTPResponse) -> dict[str, object]:
    event = "message"
    data_lines: list[str] = []
    event_id = ""
    deadline = time.time() + 5
    while time.time() < deadline:
        raw = response.readline()
        if raw == b"":
            raise AssertionError("SSE stream ended before event")
        line = raw.decode("utf-8").rstrip("\n")
        if line.endswith("\r"):
            line = line[:-1]
        if line == "":
            if data_lines or event != "message":
                data = "\n".join(data_lines)
                return {
                    "id": event_id,
                    "event": event,
                    "data": json.loads(data) if data else {},
                }
            continue
        if line.startswith(":"):
            continue
        field, _sep, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "id":
            event_id = value
        elif field == "event":
            event = value
        elif field == "data":
            data_lines.append(value)
    raise AssertionError("timed out waiting for SSE event")


def _assert_public_payload(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in _PRIVATE_KEYS:
                raise AssertionError(f"private key leaked: {key}")
            _assert_public_payload(child)
    elif isinstance(value, list):
        for child in value:
            _assert_public_payload(child)
    elif isinstance(value, str) and _PRIVATE_PATH_RE.search(value):
        raise AssertionError(f"private path leaked: {value}")
