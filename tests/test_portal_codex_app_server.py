from __future__ import annotations

import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from genomi.interfaces import (
    portal_codex_app_server,
    portal_codex_runtime,
    portal_run_events,
    portal_runs,
)


def _line(payload: object) -> str:
    return json.dumps(payload) + "\n"


class CodexAppServerSessionTests(unittest.TestCase):
    def test_streams_agent_deltas_without_duplicating_completed_message(self) -> None:
        output = io.StringIO(
            "".join(
                [
                    _line({"id": 1, "result": {"userAgent": "codex", "platformFamily": "unix", "platformOs": "macos", "codexHome": "/tmp/codex"}}),
                    _line({"id": 2, "result": {"thread": {"id": "thread-1"}}}),
                    _line({"method": "item/agentMessage/delta", "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "message-1", "delta": "Live "}}),
                    _line({"id": 3, "result": {"turn": {"id": "turn-1"}}}),
                    _line({"method": "item/agentMessage/delta", "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "message-1", "delta": "answer"}}),
                    _line({"method": "item/completed", "params": {"threadId": "thread-1", "turnId": "turn-1", "completedAtMs": 1, "item": {"id": "message-1", "type": "agentMessage", "text": "Live answer"}}}),
                    _line({"method": "turn/completed", "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "items": [], "status": "completed"}}}),
                ]
            )
        )
        sent = io.StringIO()
        events: list[dict[str, object]] = []

        portal_codex_app_server.CodexAppServerSession(sent, output, events.append).run(
            prompt="Research CTLA4",
            cwd="/tmp/workspace",
            genomi_mcp_server={"command": "/python", "args": ["-m", "genomi"]},
        )

        self.assertEqual(events, [{"type": "text_delta", "delta": "Live "}, {"type": "text_delta", "delta": "answer"}])
        requests = [json.loads(line) for line in sent.getvalue().splitlines()]
        self.assertEqual([request["method"] for request in requests], ["initialize", "initialized", "thread/start", "turn/start"])
        self.assertNotIn("jsonrpc", requests[0])
        self.assertEqual(requests[-1]["params"]["input"], [{"type": "text", "text": "Research CTLA4"}])
        self.assertNotIn("params", requests[1])
        self.assertNotIn("runtimeWorkspaceRoots", requests[2]["params"])
        self.assertEqual(requests[2]["params"]["approvalPolicy"], "on-request")
        self.assertEqual(requests[2]["params"]["sandbox"], "workspace-write")
        self.assertEqual(
            requests[2]["params"]["config"]["mcp_servers"]["genomi"],
            {"command": "/python", "args": ["-m", "genomi"]},
        )

    def test_portal_runtime_mcp_config_uses_current_python_and_source_tree(self) -> None:
        config = portal_codex_runtime.genomi_mcp_server_config()

        self.assertEqual(config["args"], ["-m", "genomi", "serve", "--transport", "stdio"])
        self.assertTrue(Path(config["command"]).is_absolute())
        configured_roots = config["env"]["PYTHONPATH"].split(os.pathsep)
        self.assertEqual(
            Path(configured_roots[0]).resolve(),
            Path(portal_codex_runtime.__file__).resolve().parents[2],
        )

    def test_portal_runtime_mcp_config_carries_only_run_scoped_genomi_context(self) -> None:
        environment = {
            "GENOMI_CONTEXT": "/private/project/context.json",
            "GENOMI_CONTEXT_POLICY": "explicit",
            "GENOMI_SESSION_ID": "portal:project:frame",
            "GENOMILAB_PORTAL_PROJECT_ID": "project",
            "GENOMILAB_PORTAL_FRAME_ID": "frame",
            "PAPERCLIP_API_KEY": "paperclip-test-secret",
            "BIOHUB_API_KEY": "biohub-test-secret",
            "ESM_API_KEY": "esm-test-secret",
            "MODAL_TOKEN_ID": "modal-test-id",
            "MODAL_TOKEN_SECRET": "modal-test-secret",
            "UNRELATED_SECRET": "must-not-cross-the-mcp-boundary",
        }
        config = portal_codex_runtime.genomi_mcp_server_config(environment)

        self.assertEqual(
            {
                key: value
                for key, value in config["env"].items()
                if key != "PYTHONPATH"
            },
            {
                "GENOMI_CONTEXT": "/private/project/context.json",
                "GENOMI_CONTEXT_POLICY": "explicit",
                "GENOMI_SESSION_ID": "portal:project:frame",
                "GENOMILAB_PORTAL_PROJECT_ID": "project",
                "GENOMILAB_PORTAL_FRAME_ID": "frame",
                "PAPERCLIP_API_KEY": "paperclip-test-secret",
                "BIOHUB_API_KEY": "biohub-test-secret",
                "ESM_API_KEY": "esm-test-secret",
                "MODAL_TOKEN_ID": "modal-test-id",
                "MODAL_TOKEN_SECRET": "modal-test-secret",
            },
        )
        exec_args = " ".join(portal_codex_runtime.exec_config_args(environment))
        self.assertIn("mcp_servers.genomi.env.GENOMI_CONTEXT", exec_args)
        self.assertIn("mcp_servers.genomi.env.GENOMI_SESSION_ID", exec_args)
        self.assertNotIn("UNRELATED_SECRET", exec_args)

    def test_completed_message_supplies_text_when_no_delta_arrived(self) -> None:
        output = io.StringIO(
            "".join(
                [
                    _line({"id": 1, "result": {}}),
                    _line({"id": 2, "result": {"thread": {"id": "thread-1"}}}),
                    _line({"id": 3, "result": {"turn": {"id": "turn-1"}}}),
                    _line({"method": "item/completed", "params": {"item": {"id": "message-1", "type": "agentMessage", "text": "Final answer"}}}),
                    _line({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "items": [], "status": "completed"}}}),
                ]
            )
        )
        events: list[dict[str, object]] = []

        portal_codex_app_server.CodexAppServerSession(io.StringIO(), output, events.append).run(prompt="Question", cwd="/tmp")

        self.assertEqual(events, [{"type": "text_delta", "delta": "Final answer"}])

    def test_maps_mcp_and_collaboration_items_to_visible_tool_events(self) -> None:
        output = io.StringIO(
            "".join(
                [
                    _line({"id": 1, "result": {}}),
                    _line({"id": 2, "result": {"thread": {"id": "thread-1"}}}),
                    _line({"id": 3, "result": {"turn": {"id": "turn-1"}}}),
                    _line({"method": "item/started", "params": {"item": {"id": "mcp-1", "type": "mcpToolCall", "server": "genomi", "tool": "genomi.invoke", "arguments": {"tool": "variant.resolve"}, "status": "inProgress"}}}),
                    _line({"method": "item/completed", "params": {"item": {"id": "mcp-1", "type": "mcpToolCall", "server": "genomi", "tool": "genomi.invoke", "arguments": {"tool": "variant.resolve"}, "result": {"headline": "data_returned"}, "status": "completed"}}}),
                    _line({"method": "item/started", "params": {"item": {"id": "collab-1", "type": "collabAgentToolCall", "tool": "spawnAgent", "prompt": "Review evidence", "receiverThreadIds": ["specialist-1"], "agentsStates": {"specialist-1": {"status": "running"}}, "status": "inProgress"}}}),
                    _line({"method": "item/completed", "params": {"item": {"id": "collab-1", "type": "collabAgentToolCall", "tool": "spawnAgent", "receiverThreadIds": ["specialist-1"], "agentsStates": {"specialist-1": {"status": "completed"}}, "status": "completed"}}}),
                    _line({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "items": [], "status": "completed"}}}),
                ]
            )
        )
        events: list[dict[str, object]] = []

        portal_codex_app_server.CodexAppServerSession(io.StringIO(), output, events.append).run(prompt="Question", cwd="/tmp")

        self.assertEqual([event["type"] for event in events], ["tool_call", "tool_result", "tool_call", "tool_result"])
        self.assertEqual(events[0]["name"], "genomi.genomi.invoke")
        self.assertEqual(events[1]["content"], {"headline": "data_returned"})
        self.assertEqual(events[2]["name"], "spawn_agent")
        self.assertEqual(events[2]["input"]["agentsStates"]["specialist-1"]["status"], "running")
        self.assertEqual(events[2]["input"]["message"], "Review evidence")
        self.assertEqual(events[2]["input"]["agent_id"], "specialist-1")
        self.assertEqual(events[3]["content"]["agentsStates"]["specialist-1"]["status"], "completed")
        self.assertEqual(events[3]["content"]["updates"], [{"agent_id": "specialist-1", "status": "completed"}])
        self.assertNotIn("status", events[3]["content"])

    def test_native_specialist_protocol_is_isolated_from_main_answer_until_root_completion(self) -> None:
        output = io.StringIO(
            "".join(
                [
                    _line({"id": 1, "result": {}}),
                    _line({"id": 2, "result": {"thread": {"id": "main-thread"}}}),
                    _line({"id": 3, "result": {"turn": {"id": "main-turn"}}}),
                    _line(
                        {
                            "method": "item/started",
                            "params": {
                                "threadId": "main-thread",
                                "turnId": "main-turn",
                                "item": {
                                    "type": "subAgentActivity",
                                    "id": "spawn-native-1",
                                    "kind": "started",
                                    "agentThreadId": "specialist-thread",
                                    "agentPath": "/root/public_literature",
                                },
                            },
                        }
                    ),
                    _line(
                        {
                            "method": "item/completed",
                            "params": {
                                "threadId": "main-thread",
                                "turnId": "main-turn",
                                "item": {
                                    "type": "subAgentActivity",
                                    "id": "spawn-native-1",
                                    "kind": "started",
                                    "agentThreadId": "specialist-thread",
                                    "agentPath": "/root/public_literature",
                                },
                            },
                        }
                    ),
                    _line(
                        {
                            "method": "item/agentMessage/delta",
                            "params": {
                                "threadId": "specialist-thread",
                                "turnId": "specialist-turn",
                                "itemId": "specialist-message",
                                "delta": "SPECIALIST ONLY",
                            },
                        }
                    ),
                    _line(
                        {
                            "method": "item/completed",
                            "params": {
                                "threadId": "specialist-thread",
                                "turnId": "specialist-turn",
                                "item": {
                                    "type": "agentMessage",
                                    "id": "specialist-message",
                                    "text": "SPECIALIST ONLY",
                                    "phase": "final_answer",
                                },
                            },
                        }
                    ),
                    _line(
                        {
                            "method": "turn/completed",
                            "params": {
                                "threadId": "specialist-thread",
                                "turn": {
                                    "id": "specialist-turn",
                                    "items": [
                                        {
                                            "type": "agentMessage",
                                            "id": "specialist-message",
                                            "text": "SPECIALIST ONLY",
                                            "phase": "final_answer",
                                        }
                                    ],
                                    "status": "completed",
                                },
                            },
                        }
                    ),
                    _line(
                        {
                            "method": "item/started",
                            "params": {
                                "threadId": "main-thread",
                                "turnId": "main-turn",
                                "item": {
                                    "id": "wait-1",
                                    "type": "collabAgentToolCall",
                                    "tool": "wait",
                                    "status": "inProgress",
                                    "receiverThreadIds": [],
                                    "agentsStates": {},
                                },
                            },
                        }
                    ),
                    _line(
                        {
                            "method": "item/completed",
                            "params": {
                                "threadId": "main-thread",
                                "turnId": "main-turn",
                                "item": {
                                    "id": "wait-1",
                                    "type": "collabAgentToolCall",
                                    "tool": "wait",
                                    "status": "completed",
                                    "receiverThreadIds": [],
                                    "agentsStates": {},
                                },
                            },
                        }
                    ),
                    _line(
                        {
                            "method": "item/agentMessage/delta",
                            "params": {
                                "threadId": "main-thread",
                                "turnId": "main-turn",
                                "itemId": "main-message",
                                "delta": "MAIN RECEIVED",
                            },
                        }
                    ),
                    _line(
                        {
                            "method": "item/completed",
                            "params": {
                                "threadId": "main-thread",
                                "turnId": "main-turn",
                                "item": {
                                    "type": "agentMessage",
                                    "id": "main-message",
                                    "text": "MAIN RECEIVED",
                                    "phase": "final_answer",
                                },
                            },
                        }
                    ),
                    _line(
                        {
                            "method": "turn/completed",
                            "params": {
                                "threadId": "main-thread",
                                "turn": {"id": "main-turn", "items": [], "status": "completed"},
                            },
                        }
                    ),
                ]
            )
        )
        events: list[dict[str, object]] = []

        portal_codex_app_server.CodexAppServerSession(
            io.StringIO(), output, events.append
        ).run(prompt="Question", cwd="/tmp")

        self.assertEqual(
            [event for event in events if event["type"] == "text_delta"],
            [{"type": "text_delta", "delta": "MAIN RECEIVED"}],
        )
        spawn_call = next(
            event
            for event in events
            if event["type"] == "tool_call" and event["name"] == "spawn_agent"
        )
        self.assertEqual(spawn_call["id"], "spawn-native-1")
        self.assertEqual(spawn_call["input"]["task_name"], "/root/public_literature")
        spawn_result = next(
            event
            for event in events
            if event["type"] == "tool_result" and event["name"] == "spawn_agent"
        )
        self.assertEqual(spawn_result["id"], "spawn-native-1")
        self.assertEqual(
            spawn_result["payload"]["updates"],
            [
                {
                    "agent_id": "/root/public_literature",
                    "task_name": "/root/public_literature",
                    "status": "completed",
                    "message": "SPECIALIST ONLY",
                }
            ],
        )
        self.assertEqual(
            [event["name"] for event in events if event["type"] == "tool_call"],
            ["spawn_agent", "wait_agent"],
        )

    def test_inbound_approval_request_with_colliding_id_is_declined_without_hanging(self) -> None:
        output = io.StringIO(
            "".join(
                [
                    _line({"id": 1, "method": "item/commandExecution/requestApproval", "params": {"command": "git status"}}),
                    _line({"id": 1, "result": {}}),
                    _line({"id": 2, "result": {"thread": {"id": "thread-1"}}}),
                    _line({"id": 3, "result": {"turn": {"id": "turn-1"}}}),
                    _line({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "items": [], "status": "completed"}}}),
                ]
            )
        )
        sent = io.StringIO()
        events: list[dict[str, object]] = []

        portal_codex_app_server.CodexAppServerSession(sent, output, events.append).run(prompt="Question", cwd="/tmp")

        self.assertEqual(events[0]["permission_request"]["tool"], "Bash")
        messages = [json.loads(line) for line in sent.getvalue().splitlines()]
        self.assertIn({"id": 1, "result": {"decision": "decline"}}, messages)

    def test_genomi_mcp_tool_call_is_authorized_by_submitted_portal_turn(self) -> None:
        output = io.StringIO(
            "".join(
                [
                    _line(
                        {
                            "id": 91,
                            "method": "mcpServer/elicitation/request",
                            "params": {
                                "serverName": "genomi",
                                "mode": "form",
                                "message": "Approve Genomi tool call",
                                "requestedSchema": {"type": "object", "properties": {}},
                                "_meta": {
                                    "codex_approval_kind": "mcp_tool_call",
                                    "tool_params": {
                                        "tool": "lab.create_investigation",
                                        "params": {"title": "Immune history review"},
                                    },
                                },
                            },
                        }
                    ),
                    _line({"id": 1, "result": {}}),
                    _line({"id": 2, "result": {"thread": {"id": "thread-1"}}}),
                    _line({"id": 3, "result": {"turn": {"id": "turn-1"}}}),
                    _line({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "items": [], "status": "completed"}}}),
                ]
            )
        )
        sent = io.StringIO()
        events: list[dict[str, object]] = []

        portal_codex_app_server.CodexAppServerSession(sent, output, events.append).run(prompt="Question", cwd="/tmp")

        self.assertEqual(events, [])
        messages = [json.loads(line) for line in sent.getvalue().splitlines()]
        self.assertIn({"id": 91, "result": {"action": "accept", "content": {}}}, messages)


class CodexAppServerPortalRunTests(unittest.TestCase):
    def test_consumer_passes_selected_portal_context_to_nested_genomi_mcp(self) -> None:
        class Process:
            stdin = io.StringIO()
            stdout = io.StringIO()

            def poll(self) -> int:
                return 0

        presentation = mock.Mock()
        environment = {
            "GENOMI_CONTEXT": "/private/project/context.json",
            "GENOMI_CONTEXT_POLICY": "explicit",
            "GENOMI_SESSION_ID": "portal:project:frame",
        }

        with mock.patch.object(
            portal_codex_app_server.CodexAppServerSession,
            "run",
        ) as app_server_run:
            portal_runs._consume_codex_app_server(
                Process(),
                "Question",
                Path("/tmp/workspace"),
                presentation,
                environment,
            )

        nested_environment = app_server_run.call_args.kwargs[
            "genomi_mcp_server"
        ]["env"]
        self.assertEqual(
            nested_environment["GENOMI_CONTEXT"],
            "/private/project/context.json",
        )
        self.assertEqual(
            nested_environment["GENOMI_SESSION_ID"],
            "portal:project:frame",
        )

    def test_live_deltas_are_emitted_in_order_before_terminal_completion(self) -> None:
        run = portal_run_events.create_run(kind="host_agent", agent_id="codex", message="Question")
        self.addCleanup(portal_run_events.discard_run, run.id)
        protocol_output = "".join(
            [
                _line({"id": 1, "result": {}}),
                _line({"id": 2, "result": {"thread": {"id": "thread-live"}}}),
                _line({"id": 3, "result": {"turn": {"id": "turn-live"}}}),
                _line({"method": "item/agentMessage/delta", "params": {"threadId": "thread-live", "turnId": "turn-live", "itemId": "message-live", "delta": "First "}}),
                _line({"method": "item/agentMessage/delta", "params": {"threadId": "thread-live", "turnId": "turn-live", "itemId": "message-live", "delta": "second"}}),
                _line({"method": "item/completed", "params": {"item": {"id": "message-live", "type": "agentMessage", "text": "First second"}}}),
                _line({"method": "turn/completed", "params": {"threadId": "thread-live", "turn": {"id": "turn-live", "items": [], "status": "completed"}}}),
            ]
        )

        class LiveProcess:
            stdin = io.StringIO()
            stdout = io.StringIO(protocol_output)
            stderr = None
            terminated = False

            def poll(self) -> int | None:
                return -15 if self.terminated else None

            def terminate(self) -> None:
                self.terminated = True

            def wait(self, timeout: int | None = None) -> int:
                return -15 if self.terminated else 0

        process = LiveProcess()
        with mock.patch("genomi.interfaces.portal_agents.agent_invocation", return_value=["/usr/bin/codex", "exec", "--json"]), mock.patch(
            "genomi.interfaces.portal_runs.subprocess.Popen", return_value=process
        ), mock.patch("genomi.interfaces.portal_run_logs.append_run_event"):
            portal_runs.run_agent(run)

        agent_events = [event.data for event in run.events if event.event == "agent"]
        deltas = [event for event in agent_events if event.get("type") == "text_delta"]
        self.assertEqual(deltas, [{"type": "text_delta", "delta": "First "}, {"type": "text_delta", "delta": "second"}])
        delta_sequences = [event.id for event in run.events if event.event == "agent" and event.data.get("type") == "text_delta"]
        completed_sequence = next(
            event.id
            for event in run.events
            if event.event == "status" and event.data.get("status") == "succeeded"
        )
        self.assertLess(max(delta_sequences), completed_sequence)
        self.assertEqual(run.output, "First second")
        self.assertEqual(run.status, "succeeded")
        self.assertTrue(process.terminated)

    def test_unavailable_app_server_falls_back_once_and_cleans_up(self) -> None:
        run = portal_run_events.create_run(kind="host_agent", agent_id="codex", message="Question")
        self.addCleanup(portal_run_events.discard_run, run.id)

        class AppProcess:
            stdin = io.StringIO()
            stdout = io.StringIO()
            stderr = None
            terminated = False

            def poll(self) -> int | None:
                return -15 if self.terminated else None

            def terminate(self) -> None:
                self.terminated = True

            def wait(self, timeout: int | None = None) -> int:
                return -15 if self.terminated else 0

        class ExecProcess:
            stdin = io.StringIO()
            stdout = [_line({"type": "item.completed", "item": {"type": "agent_message", "text": "Fallback answer"}})]
            stderr = None

            def poll(self) -> int:
                return 0

            def wait(self, timeout: int | None = None) -> int:
                return 0

        app_process = AppProcess()
        exec_process = ExecProcess()
        commands: list[list[str]] = []

        def fake_popen(command: list[str], **_kwargs: object) -> object:
            commands.append(command)
            return app_process if len(commands) == 1 else exec_process

        with mock.patch("genomi.interfaces.portal_agents.agent_invocation", return_value=["/usr/bin/codex", "exec", "--json"]), mock.patch(
            "genomi.interfaces.portal_runs.subprocess.Popen", side_effect=fake_popen
        ), mock.patch.object(
            portal_codex_app_server.CodexAppServerSession,
            "run",
            side_effect=portal_codex_app_server.CodexAppServerUnavailable("method unavailable"),
        ), mock.patch(
            "genomi.interfaces.portal_run_logs.append_run_event"
        ):
            portal_runs.run_agent(run)

        self.assertEqual(commands[0], ["/usr/bin/codex", "app-server"])
        self.assertEqual(commands[1][:3], ["/usr/bin/codex", "exec", "--json"])
        self.assertIn("mcp_servers.genomi.command", " ".join(commands[1]))
        self.assertTrue(app_process.terminated)
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.output, "Fallback answer")


if __name__ == "__main__":
    unittest.main()
