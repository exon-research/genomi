from __future__ import annotations

import json
from unittest import mock

from genomi.interfaces import (
    portal_run_events,
    portal_run_logs,
    portal_run_packages,
    portal_run_service,
    portal_state,
    portal_store,
    portal_workspaces,
)
from genomi.operations import OperationError, call_operation, operation_discovery_payload

from tests.support.runtime.genomi import GenomiRuntimeTestCase


class PortalSidecarOperationTests(GenomiRuntimeTestCase):
    def test_portal_run_control_operations_are_in_default_tool_discovery(self) -> None:
        tools = operation_discovery_payload()["tools"]
        tool_names = {tool["name"] for tool in tools}
        start_tool = next(tool for tool in tools if tool["name"] == "genomi.start_portal_run")
        start_properties = start_tool["inputSchema"]["properties"]

        self.assertIn("genomi.start_portal_run", tool_names)
        self.assertIn("genomi.check_portal_run", tool_names)
        self.assertIn("genomi.cancel_portal_run", tool_names)
        self.assertIn("genomi.retrieve_portal_run_event_page", tool_names)
        self.assertIn("genomi.retrieve_portal_run_result_package", tool_names)
        self.assertEqual(start_properties["source_frame_id"]["type"], "string")
        self.assertEqual(start_properties["started_from_selected_material"]["type"], "boolean")

    def test_start_portal_run_uses_default_project_and_persists_selected_context(self) -> None:
        with mock.patch("genomi.interfaces.portal_agents.default_agent_id", return_value="codex"), mock.patch(
            "genomi.interfaces.portal_run_service._start_run_thread", lambda run: None
        ):
            started = call_operation(
                "genomi.start_portal_run",
                {
                    "message": "Review rs429358 evidence",
                    "selected_evidence": [{"id": "ev-1", "label": "Variant", "text": "rs429358"}],
                },
            )

        self.assertEqual(started["schema"], "genomi_portal_run_start")
        self.assertEqual(started["status"], "queued")
        self.assertFalse(started["terminal"])
        self.assertEqual(started["agent_id"], "codex")
        self.assertTrue(started["run_id"])
        self.assertTrue(started["project_id"])
        self.assertTrue(started["frame_id"])
        self.assertEqual(started["workspace"]["owner"], "genomi_webui")
        self.assertEqual(started["workspace"]["storage"], "genomi_home_workspace")
        self.assertEqual(started["workspace"]["path_hint"], f"$GENOMI_HOME/workspace/{started['project_id']}")
        self.assertEqual(started["run"]["workspace"], started["workspace"])
        self.assertEqual(
            [item["operation"] for item in started["next_actions"]],
            [
                "genomi.check_portal_run",
                "genomi.cancel_portal_run",
                "genomi.retrieve_portal_run_event_page",
                "genomi.retrieve_portal_run_result_package",
            ],
        )

        workspace = call_operation("genomi.describe_portal_workspace", {"project_id": started["project_id"]})
        messages = portal_store.list_frame_messages(started["frame_id"])["messages"]
        project_workspace = portal_workspaces.project_workspace_dir(started["project_id"])
        self.assertEqual(workspace["project"]["project_id"], started["project_id"])
        self.assertTrue(project_workspace.is_dir())
        self.assertEqual(workspace["project"]["workspace"]["owner"], "genomi_webui")
        self.assertEqual(workspace["project"]["workspace"]["storage"], "genomi_home_workspace")
        self.assertEqual(workspace["project"]["workspace"]["path_hint"], f"$GENOMI_HOME/workspace/{started['project_id']}")
        self.assertEqual(workspace["frames"]["frames"][0]["id"], started["frame_id"])
        self.assertEqual(messages[0]["text"], "Review rs429358 evidence")
        self.assertEqual(messages[0]["selected_evidence"][0]["prompt_text"], "rs429358")
        self.assertNotIn(str(self.genomi_home), json.dumps(started))
        self.assertNotIn(str(self.genomi_home), json.dumps(workspace))

    def test_start_portal_run_can_start_focused_conversation_from_selected_material(self) -> None:
        with mock.patch("genomi.interfaces.portal_agents.default_agent_id", return_value="codex"), mock.patch(
            "genomi.interfaces.portal_run_service._start_run_thread", lambda run: None
        ):
            first = call_operation("genomi.start_portal_run", {"message": "Build an APOE evidence record"})
            focused = call_operation(
                "genomi.start_portal_run",
                {
                    "project_id": first["project_id"],
                    "message": "Use this file in a fresh conversation.",
                    "source_frame_id": first["frame_id"],
                    "started_from_selected_material": True,
                    "selected_evidence": [
                        {
                            "id": "file-1",
                            "label": "Project file: reports/apoe.md",
                            "text": "APOE report excerpt",
                        }
                    ],
                },
            )

        workspace = call_operation("genomi.describe_portal_workspace", {"project_id": first["project_id"]})
        by_id = {frame["id"]: frame for frame in workspace["frames"]["frames"]}

        self.assertNotEqual(first["frame_id"], focused["frame_id"])
        self.assertEqual(by_id[focused["frame_id"]]["started_from"]["summary"], "Started from Project file: reports/apoe.md")
        self.assertEqual(by_id[focused["frame_id"]]["started_from"]["material_count"], 1)
        self.assertNotIn("source_frame_id", json.dumps(by_id[focused["frame_id"]]["started_from"]))
        self.assertNotIn(str(self.genomi_home), json.dumps(workspace))

    def test_describe_portal_workspace_refreshes_stale_workspace_metadata(self) -> None:
        project = portal_store.create_project(name="Workspace contract")

        def mutate(state: dict[str, object]) -> dict[str, object]:
            stored_project = state["projects"][project["project_id"]]
            stored_project["workspace"] = {
                "scope": "project",
                "workspace_id": project["project_id"],
                "status": "ready",
            }
            return stored_project

        portal_state.mutate_state(mutate)

        workspace = call_operation("genomi.describe_portal_workspace", {"project_id": project["project_id"]})

        self.assertEqual(workspace["project"]["workspace"]["owner"], "genomi_webui")
        self.assertEqual(workspace["project"]["workspace"]["storage"], "genomi_home_workspace")
        self.assertEqual(workspace["project"]["workspace"]["path_hint"], f"$GENOMI_HOME/workspace/{project['project_id']}")
        self.assertNotIn(str(self.genomi_home), json.dumps(workspace))

    def test_start_portal_run_followup_reuses_existing_frame(self) -> None:
        with mock.patch("genomi.interfaces.portal_agents.default_agent_id", return_value="codex"), mock.patch(
            "genomi.interfaces.portal_run_service._start_run_thread", lambda run: None
        ):
            first = call_operation("genomi.start_portal_run", {"message": "Review CYP2C19 evidence"})
            first_run_id = first["run_id"]
            frame_id = first["frame_id"]
            first_run = portal_run_events.get_run(first_run_id)
            assert first_run is not None
            first_run.finish("succeeded")
            portal_store.finish_frame(frame_id, status="completed", output="Initial summary.", run_id=first_run_id)

            followup = call_operation(
                "genomi.start_portal_run",
                {
                    "project_id": first["project_id"],
                    "frame_id": frame_id,
                    "message": "What changed?",
                },
            )

        self.assertEqual(followup["frame_id"], frame_id)
        self.assertEqual(followup["root_frame_id"], first["root_frame_id"])
        self.assertNotEqual(followup["run_id"], first_run_id)
        messages = portal_store.list_frame_messages(frame_id)["messages"]
        self.assertEqual([message["role"] for message in messages], ["user", "assistant", "user"])
        self.assertEqual([message["text"] for message in messages if message["role"] == "user"], ["Review CYP2C19 evidence", "What changed?"])

    def test_check_and_cancel_portal_run_share_active_run_state(self) -> None:
        with mock.patch("genomi.interfaces.portal_agents.default_agent_id", return_value="codex"), mock.patch(
            "genomi.interfaces.portal_run_service._start_run_thread", lambda run: None
        ):
            started = call_operation("genomi.start_portal_run", {"message": "Build an APOE report"})
            checked = call_operation("genomi.check_portal_run", {"run_id": started["run_id"]})
            canceled = call_operation("genomi.cancel_portal_run", {"run_id": started["run_id"]})
            checked_again = call_operation("genomi.check_portal_run", {"run_id": started["run_id"]})
            with self.assertRaises(OperationError) as raised:
                call_operation("genomi.cancel_portal_run", {"run_id": started["run_id"]})

        self.assertEqual(checked["schema"], "genomi_portal_run_status")
        self.assertEqual(checked["status"], "queued")
        self.assertFalse(checked["terminal"])
        self.assertEqual(canceled["schema"], "genomi_portal_run_cancel")
        self.assertEqual(canceled["status"], "canceled")
        self.assertTrue(canceled["terminal"])
        self.assertEqual(checked_again["status"], "canceled")
        self.assertEqual(
            [item["operation"] for item in canceled["next_actions"]],
            ["genomi.retrieve_portal_run_event_page", "genomi.retrieve_portal_run_result_package"],
        )
        self.assertEqual(raised.exception.code, "portal_run_terminal")

    def test_start_portal_run_reports_busy_followup_frame(self) -> None:
        with mock.patch("genomi.interfaces.portal_agents.default_agent_id", return_value="codex"), mock.patch(
            "genomi.interfaces.portal_run_service._start_run_thread", lambda run: None
        ):
            started = call_operation("genomi.start_portal_run", {"message": "Review BRCA1 evidence"})
            with self.assertRaises(OperationError) as raised:
                call_operation(
                    "genomi.start_portal_run",
                    {
                        "project_id": started["project_id"],
                        "frame_id": started["frame_id"],
                        "message": "Follow up before completion",
                    },
                )

        self.assertEqual(raised.exception.code, "portal_frame_busy")

    def test_portal_run_control_reports_missing_run(self) -> None:
        with self.assertRaises(OperationError) as raised:
            call_operation("genomi.check_portal_run", {"run_id": "missing-run"})
        self.assertEqual(raised.exception.code, "portal_run_not_found")

        with self.assertRaises(OperationError) as raised:
            call_operation("genomi.cancel_portal_run", {"run_id": "missing-run"})
        self.assertEqual(raised.exception.code, "portal_run_not_found")

    def test_cancel_portal_run_reports_persisted_terminal_run(self) -> None:
        project = portal_store.create_project(name="Terminal sidecar")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Build terminal run",
            agent_id="codex",
        )
        assert frame is not None
        run_id = "terminal-sidecar-run"
        portal_store.attach_run(str(frame["id"]), run_id=run_id, agent_id="codex")
        portal_store.finish_frame(str(frame["id"]), status="completed", output="Done.", run_id=run_id)

        with self.assertRaises(OperationError) as raised:
            call_operation("genomi.cancel_portal_run", {"run_id": run_id})

        self.assertEqual(raised.exception.code, "portal_run_terminal")

    def test_run_service_cancel_by_id_reports_active_missing_and_terminal(self) -> None:
        project = portal_store.create_project(name="Cancel service")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Build active run",
            agent_id="codex",
        )
        assert frame is not None
        run = portal_run_events.create_run(
            kind="host_agent",
            agent_id="codex",
            message="Build active run",
            project_id=project["project_id"],
            frame_id=str(frame["id"]),
        )
        self.addCleanup(portal_run_events.discard_run, run.id)
        portal_store.attach_run(str(frame["id"]), run_id=run.id, agent_id="codex")

        canceled = portal_run_service.cancel_run_by_id(run.id)
        terminal = portal_run_service.cancel_run_by_id(run.id)
        missing = portal_run_service.cancel_run_by_id("missing-service-run")

        self.assertEqual(canceled.state, "active")
        self.assertEqual(canceled.run_status["status"], "canceled")
        self.assertTrue(canceled.run_status["terminal"])
        self.assertEqual(terminal.state, "terminal")
        self.assertEqual(terminal.run_status["status"], "canceled")
        self.assertEqual(missing.state, "missing")
        self.assertIsNone(missing.run_status)

    def test_retrieve_portal_run_event_page_reads_active_memory_events(self) -> None:
        project = portal_store.create_project(name="Active events")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Build active event page",
            agent_id="codex",
        )
        assert frame is not None
        run = portal_run_events.create_run(
            kind="host_agent",
            agent_id="codex",
            message="Build active event page",
            project_id=project["project_id"],
            frame_id=str(frame["id"]),
        )
        self.addCleanup(portal_run_events.discard_run, run.id)
        self.addCleanup(portal_run_logs.discard_run_log, run.id)
        run.emit("agent", {"type": "diagnostic", "name": "started", "message": f"using {self.genomi_home / 'private.txt'}"})

        page = call_operation("genomi.retrieve_portal_run_event_page", {"run_id": run.id, "limit": 1})
        next_page = call_operation(
            "genomi.retrieve_portal_run_event_page",
            {"run_id": run.id, "after_event_id": page["next_after_event_id"], "limit": 5},
        )

        self.assertEqual(page["schema"], "genomi_portal_run_event_page")
        self.assertEqual(page["run_id"], run.id)
        self.assertEqual(page["source"], "durable_log")
        self.assertEqual(page["limit"], 1)
        self.assertEqual(page["returned"], 1)
        self.assertEqual(page["total"], 2)
        self.assertTrue(page["truncated"])
        self.assertEqual(page["items"][0]["event"], "status")
        self.assertEqual(next_page["after_event_id"], page["next_after_event_id"])
        self.assertEqual(next_page["returned"], 1)
        self.assertFalse(next_page["truncated"])
        self.assertEqual(next_page["items"][0]["event"], "agent")
        self.assertEqual(next_page["items"][0]["project_id"], project["project_id"])
        self.assertEqual(next_page["items"][0]["frame_id"], frame["id"])
        self.assertNotIn(str(self.genomi_home), json.dumps(next_page))

    def test_retrieve_portal_run_event_page_replays_durable_log_after_memory_discard(self) -> None:
        project = portal_store.create_project(name="Durable event page")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Build durable event page",
            agent_id="codex",
        )
        assert frame is not None
        run = portal_run_events.create_run(
            kind="host_agent",
            agent_id="codex",
            message="Build durable event page",
            project_id=project["project_id"],
            frame_id=str(frame["id"]),
        )
        self.addCleanup(portal_run_logs.discard_run_log, run.id)
        portal_store.attach_run(str(frame["id"]), run_id=run.id, agent_id="codex")
        run.emit("agent", {"type": "tool_call", "id": "call_1", "name": "variant.resolve", "input": {"rsid": "rs429358"}})
        portal_store.finish_frame(str(frame["id"]), status="completed", output="Done.", run_id=run.id)
        run.finish("succeeded")
        run_id = run.id
        portal_run_events.discard_run(run_id)

        page = call_operation("genomi.retrieve_portal_run_event_page", {"run_id": run_id, "after_event_id": 1, "limit": 10})

        self.assertEqual(page["source"], "durable_log")
        self.assertEqual(page["run"]["status"], "succeeded")
        self.assertEqual([item["event"] for item in page["items"]], ["agent", "end"])
        self.assertEqual(page["items"][0]["data"]["type"], "tool_call")
        self.assertEqual(page["items"][0]["data"]["name"], "variant.resolve")
        self.assertEqual(page["latest_event_id"], 3)
        self.assertEqual(page["next_after_event_id"], 3)

    def test_retrieve_portal_run_event_page_reports_missing_run(self) -> None:
        with self.assertRaises(OperationError) as raised:
            call_operation("genomi.retrieve_portal_run_event_page", {"run_id": "missing-run"})
        self.assertEqual(raised.exception.code, "portal_run_not_found")

    def test_describe_portal_workspace_returns_public_project_state(self) -> None:
        empty = call_operation("genomi.describe_portal_workspace")
        self.assertEqual(empty["status"], "empty")
        self.assertIsNone(empty["project"])

        project = portal_store.create_project(name="Sidecar workspace")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Review APOE evidence",
            agent_id="codex",
        )
        assert frame is not None
        workspace = portal_workspaces.ensure_project_workspace(project["project_id"])
        (workspace / "reports").mkdir(parents=True, exist_ok=True)
        (workspace / "reports" / "summary.txt").write_text("APOE evidence\n", encoding="utf-8")
        artifact = portal_store.add_artifact_from_bytes(
            project["project_id"],
            kind="evidence_report",
            renderer="markdown",
            title="APOE evidence report",
            operation="variant.resolve",
            result={"status": "completed", "source": str(self.genomi_home / "private.json")},
            original_filename="apoe.md",
            content_type="text/markdown",
            body=b"# APOE evidence\n",
            frame_id=str(frame["id"]),
        )
        self.assertIsNotNone(artifact)

        result = call_operation("genomi.describe_portal_workspace")

        self.assertEqual(result["schema"], "genomi_portal_workspace_summary")
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["project"]["project_id"], project["project_id"])
        self.assertEqual(result["frames"]["frames"][0]["id"], frame["id"])
        self.assertEqual(result["artifacts"]["artifacts"][0]["title"], "APOE evidence report")
        self.assertEqual(result["workspace_files"]["summary"]["total_files"], 1)
        self.assertEqual(result["workspace_files"]["files"][0]["relative_path"], "reports/summary.txt")
        self.assertNotIn(str(self.genomi_home), json.dumps(result))

    def test_retrieve_portal_run_result_package_uses_web_package_contract(self) -> None:
        project = portal_store.create_project(name="Sidecar package")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Build evidence package",
            agent_id="codex",
            selected_evidence=[{"label": "Variant", "text": "rs429358"}],
        )
        assert frame is not None
        run = portal_run_events.create_run(
            kind="host_agent",
            agent_id="codex",
            message="Build evidence package",
            project_id=project["project_id"],
            frame_id=str(frame["id"]),
        )
        self.addCleanup(portal_run_events.discard_run, run.id)
        portal_store.attach_run(str(frame["id"]), run_id=run.id, agent_id="codex")
        portal_store.append_message(str(frame["id"]), role="assistant", text="Evidence summary.", run_id=run.id)
        portal_store.finish_frame(str(frame["id"]), status="completed", output="Evidence summary.", run_id=run.id)
        run.finish("succeeded")

        with mock.patch(
            "genomi.interfaces.portal_context.prompt_context_payload",
            return_value={"activeGenomeIndex": {"available": False, "accessApproved": False}},
        ):
            package = call_operation("genomi.retrieve_portal_run_result_package", {"run_id": run.id})

        self.assertEqual(package["schema"], "genomi_portal_run_result_package")
        self.assertEqual(package["run"]["id"], run.id)
        self.assertEqual(package["run"]["status"], "succeeded")
        self.assertEqual(package["project"]["project_id"], project["project_id"])
        self.assertEqual(package["frame"]["id"], frame["id"])
        self.assertEqual(package["messages"]["total"], 2)
        self.assertEqual(package["messages"]["messages"][0]["selected_evidence"][0]["prompt_text"], "rs429358")
        self.assertTrue(package["events"]["available"])
        self.assertNotIn(str(self.genomi_home), json.dumps(package))

    def test_retrieve_portal_run_result_package_replays_durable_run_events(self) -> None:
        project = portal_store.create_project(name="Durable package")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Build durable evidence package",
            agent_id="codex",
        )
        assert frame is not None
        run = portal_run_events.create_run(
            kind="host_agent",
            agent_id="codex",
            message="Build durable evidence package",
            project_id=project["project_id"],
            frame_id=str(frame["id"]),
        )
        self.addCleanup(portal_run_logs.discard_run_log, run.id)
        portal_store.attach_run(str(frame["id"]), run_id=run.id, agent_id="codex")
        run.emit(
            "agent",
            {
                "type": "tool_result",
                "id": "call_1",
                "name": "variant.resolve",
                "payload": {
                    "status": "completed",
                    "headline": "variant.resolve: data_returned",
                    "path": str(self.genomi_home / "private.sqlite"),
                    "nested": {
                        "registry_file": str(self.genomi_home / "registry.json"),
                        "note": f"read {self.genomi_home / 'nested' / 'private.json'}",
                        "items": [
                            {
                                "agi_path": str(self.genomi_home / "agi.sqlite"),
                                "value": "APOE",
                                "message": "/tmp/private-cache.sqlite",
                            }
                        ],
                    },
                },
                "content": '{"status":"completed"}',
            },
        )
        portal_store.append_message(str(frame["id"]), role="assistant", text="Durable evidence summary.", run_id=run.id)
        portal_store.finish_frame(str(frame["id"]), status="completed", output="Durable evidence summary.", run_id=run.id)
        run.finish("succeeded")
        run_id = run.id
        portal_run_events.discard_run(run_id)

        package = call_operation("genomi.retrieve_portal_run_result_package", {"run_id": run_id})

        self.assertEqual(package["run"]["id"], run_id)
        self.assertEqual(package["run"]["status"], "succeeded")
        self.assertEqual(package["frame"]["id"], frame["id"])
        self.assertTrue(package["events"]["available"])
        self.assertEqual(package["events"]["source"], "durable_log")
        self.assertEqual(package["events"]["limit"], 200)
        self.assertEqual(package["events"]["total"], 3)
        self.assertFalse(package["events"]["truncated"])
        self.assertEqual(package["execution_cells"]["schema"], "genomi_portal_execution_cells")
        self.assertEqual(package["execution_cells"]["run_id"], run_id)
        self.assertEqual(package["execution_cells"]["total"], 2)
        tool_cells = [item for item in package["execution_cells"]["items"] if item["kind"] == "tool"]
        self.assertEqual(len(tool_cells), 1)
        self.assertEqual(tool_cells[0]["id"], f"{run_id}:tool:call_1")
        self.assertEqual(tool_cells[0]["operation"], "variant.resolve")
        self.assertEqual(tool_cells[0]["status"], "completed")
        self.assertEqual(tool_cells[0]["event_range"], {"first": 2, "last": 2})
        self.assertEqual(tool_cells[0]["summary"], "variant.resolve: data_returned")
        agent_items = [item for item in package["events"]["items"] if item["event"] == "agent"]
        self.assertEqual(len(agent_items), 1)
        event = agent_items[0]["data"]
        self.assertEqual(event["type"], "tool_result")
        self.assertEqual(event["id"], "call_1")
        self.assertEqual(event["name"], "variant.resolve")
        self.assertEqual(event["isError"], False)
        self.assertEqual(event["content"], '{"status":"completed"}')
        self.assertEqual(
            event["payload"],
            {
                "status": "completed",
                "headline": "variant.resolve: data_returned",
                "nested": {
                    "note": "read [redacted local path]",
                    "items": [{"value": "APOE", "message": "[redacted local path]"}],
                },
            },
        )
        self.assertEqual(event["portal_presentation"]["schema"], "genomi_portal_result_presentation")
        self.assertEqual(event["portal_presentation"]["source"], "server")
        self.assertEqual(event["portal_presentation"]["operation"], "variant.resolve")
        self.assertTrue(any(item["event"] == "end" for item in package["events"]["items"]))
        self.assertNotIn(str(self.genomi_home), json.dumps(package))

    def test_run_result_package_uses_explicit_root_for_status_and_durable_events(self) -> None:
        root = self.genomi_home / "alternate-root"
        project = portal_store.create_project(name="Rooted package", root=root)
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Build rooted package",
            agent_id="codex",
            root=root,
        )
        assert frame is not None
        run_id = "run_rooted_1"
        portal_store.attach_run(str(frame["id"]), run_id=run_id, agent_id="codex", root=root)
        portal_store.finish_frame(str(frame["id"]), status="completed", output="Rooted summary.", run_id=run_id, root=root)
        portal_run_logs.append_run_event(
            run_id,
            event_id=1,
            event="status",
            timestamp=1.0,
            data={"status": "queued"},
            project_id=project["project_id"],
            frame_id=str(frame["id"]),
            root=root,
        )
        portal_run_logs.append_run_event(
            run_id,
            event_id=2,
            event="end",
            timestamp=2.0,
            data={"status": "succeeded", "error": None},
            project_id=project["project_id"],
            frame_id=str(frame["id"]),
            root=root,
        )

        package = portal_run_packages.run_result_package(run_id, root=root)

        assert package is not None
        self.assertEqual(package["run"]["id"], run_id)
        self.assertEqual(package["run"]["status"], "succeeded")
        self.assertEqual(package["frame"]["id"], frame["id"])
        self.assertEqual(package["events"]["source"], "durable_log")
        self.assertEqual([item["event"] for item in package["events"]["items"]], ["status", "end"])

    def test_retrieve_portal_run_result_package_reports_missing_run(self) -> None:
        with self.assertRaises(OperationError) as raised:
            call_operation("genomi.retrieve_portal_run_result_package", {"run_id": "missing-run"})
        self.assertEqual(raised.exception.code, "portal_run_not_found")
