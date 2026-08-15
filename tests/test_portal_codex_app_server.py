from __future__ import annotations

import io
import json
import unittest
from unittest import mock

from genomi.interfaces import (
    portal_codex_app_server,
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
        )

        self.assertEqual(events, [{"type": "text_delta", "delta": "Live "}, {"type": "text_delta", "delta": "answer"}])
        requests = [json.loads(line) for line in sent.getvalue().splitlines()]
        self.assertEqual([request["method"] for request in requests], ["initialize", "initialized", "thread/start", "turn/start"])
        self.assertNotIn("jsonrpc", requests[0])
        self.assertEqual(requests[-1]["params"]["input"], [{"type": "text", "text": "Research CTLA4"}])
        self.assertNotIn("params", requests[1])
        self.assertEqual(requests[2]["params"]["runtimeWorkspaceRoots"], ["/tmp/workspace"])
        self.assertEqual(requests[2]["params"]["approvalPolicy"], "on-request")
        self.assertEqual(requests[2]["params"]["sandbox"], "workspace-write")

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


class CodexAppServerPortalRunTests(unittest.TestCase):
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

        self.assertEqual(commands, [["/usr/bin/codex", "app-server"], ["/usr/bin/codex", "exec", "--json"]])
        self.assertTrue(app_process.terminated)
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.output, "Fallback answer")


if __name__ == "__main__":
    unittest.main()
