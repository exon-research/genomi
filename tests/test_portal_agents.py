from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from genomi.interfaces import portal_agents
from genomi.runtime import context as runtime_context


def _installed(*commands: str):
    return mock.patch(
        "genomi.interfaces.portal_agents.shutil.which",
        side_effect=lambda command: f"/usr/local/bin/{command}" if command in set(commands) else None,
    )


def _host_agent_session(**session_env: str):
    cleared = {name: "" for name in runtime_context.AGENT_SESSION_ENVS}
    return mock.patch.dict(os.environ, {**cleared, **session_env}, clear=False)


class PortalAgentDriverTests(unittest.TestCase):
    def test_the_host_agent_session_environment_names_the_launching_agent(self) -> None:
        with _installed("codex", "claude"), _host_agent_session(CLAUDE_CODE_SESSION_ID="session-1"):
            agents = portal_agents.detect_agents()

            self.assertEqual(portal_agents.bootstrap_agent_id(), "claude")

        with _installed("codex", "claude"), _host_agent_session(CODEX_THREAD_ID="thread-1"):
            self.assertEqual(portal_agents.bootstrap_agent_id(), "codex")

        with _installed("codex", "claude"), _host_agent_session(OPENHARNESS_DATA_DIR="/opt/openharness"):
            self.assertEqual(portal_agents.bootstrap_agent_id(), "opencode")

        with _installed("codex", "claude"), _host_agent_session():
            self.assertEqual(portal_agents.bootstrap_agent_id(), "")

        runnable_ids = [agent["id"] for agent in agents if agent["runnable"]]
        self.assertEqual(runnable_ids, ["codex", "claude"])

    def test_launch_agent_is_kept_only_while_it_can_run_here(self) -> None:
        self.addCleanup(portal_agents.set_launch_agent_id, "")

        with _installed("codex", "claude"):
            portal_agents.set_launch_agent_id("claude")
            self.assertEqual(portal_agents.launch_agent_id(), "claude")

        with _installed("codex"):
            self.assertEqual(portal_agents.launch_agent_id(), "")

    def test_detected_setup_only_agent_is_not_runnable_or_selectable_default(self) -> None:
        def fake_which(command: str) -> str | None:
            if command in {"codex", "gemini", "opencode"}:
                return f"/usr/local/bin/{command}"
            return None

        with mock.patch("genomi.interfaces.portal_agents.shutil.which", side_effect=fake_which), _host_agent_session(
            OPENHARNESS_DATA_DIR="/tmp/openharness"
        ):
            agents = {agent["id"]: agent for agent in portal_agents.detect_agents()}
            invocation = portal_agents.agent_invocation("opencode")
            runnable_ids = portal_agents.runnable_agent_ids()

        self.assertTrue(agents["opencode"]["available"])
        self.assertFalse(agents["opencode"]["runnable"])
        self.assertEqual(agents["opencode"]["status"], "detected_setup_only")
        self.assertTrue(agents["gemini"]["available"])
        self.assertFalse(agents["gemini"]["runnable"])
        self.assertEqual(agents["gemini"]["status"], "detected_setup_only")
        self.assertEqual(
            set(agents["gemini"]),
            {"id", "label", "command", "summary", "available", "runnable", "status"},
        )
        self.assertEqual(
            set(agents["opencode"]),
            {"id", "label", "command", "summary", "available", "runnable", "status"},
        )
        self.assertIsNone(invocation)
        self.assertEqual(runnable_ids, ["codex"])

    def test_driver_registry_owns_stream_contract(self) -> None:
        line = json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "variant.resolve",
                    "arguments": "{\"rsid\":\"rs429358\"}",
                },
            }
        )

        events = portal_agents.agent_events_for_line("codex", line)

        self.assertEqual(events[0]["type"], "tool_call")
        self.assertEqual(events[0]["name"], "variant.resolve")
        self.assertEqual(events[0]["input"], {"rsid": "rs429358"})

    def test_claude_portal_driver_preallows_genomi_mcp_tools(self) -> None:
        with mock.patch("genomi.interfaces.portal_agents.shutil.which", return_value="/usr/local/bin/claude"):
            invocation = portal_agents.agent_invocation("claude")

        assert invocation is not None
        self.assertIn("--allowedTools", invocation)
        self.assertIn("mcp__genomi__*", invocation)
        self.assertNotIn("--dangerously-skip-permissions", invocation)

    def test_claude_portal_driver_adds_one_approved_retry_tool(self) -> None:
        with mock.patch("genomi.interfaces.portal_agents.shutil.which", return_value="/usr/local/bin/claude"):
            invocation = portal_agents.agent_invocation(
                "claude",
                approved_tools=["mcp__genomi__genomi_describe_context", "mcp__genomi__genomi_describe_context"],
            )

        assert invocation is not None
        self.assertIn("--allowedTools", invocation)
        self.assertIn("mcp__genomi__*", invocation)
        self.assertEqual(invocation.count("mcp__genomi__genomi_describe_context"), 1)

    def test_permission_request_from_message_extracts_requested_tool(self) -> None:
        permission = portal_agents.permission_request_from_message(
            "Claude requested permissions to use mcp__genomi__genomi_describe_context, but you haven't granted it yet."
        )

        assert permission is not None
        self.assertEqual(permission["kind"], "host_agent_tool")
        self.assertEqual(permission["tool"], "mcp__genomi__genomi_describe_context")
        self.assertEqual(permission["label"], "Read current Genomi context")

        web_permission = portal_agents.permission_request_from_message(
            "Claude requested permissions to use WebFetch, but you haven't granted it yet."
        )
        assert web_permission is not None
        self.assertEqual(web_permission["label"], "Open a public web page")

        write_permission = portal_agents.permission_request_from_message(
            "Claude requested permissions to write to [redacted local path], but you haven't granted it yet."
        )
        assert write_permission is not None
        self.assertEqual(write_permission["tool"], "Write")
        self.assertEqual(write_permission["label"], "Create or update project files")

    def test_claude_tool_result_error_extracts_permission_request(self) -> None:
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "is_error": True,
                            "content": "Claude requested permissions to use mcp__genomi__genomi_describe_context, but you haven't granted it yet.",
                        }
                    ]
                },
            }
        )

        events = portal_agents.agent_events_for_line("claude", line)

        self.assertEqual(events[0]["type"], "tool_result")
        self.assertTrue(events[0]["isError"])
        self.assertEqual(events[0]["permission_request"]["tool"], "mcp__genomi__genomi_describe_context")

    def test_claude_progress_text_is_work_trail_status(self) -> None:
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "I am checking the public evidence sources now.",
                        }
                    ]
                },
            }
        )

        events = portal_agents.agent_events_for_line("claude", line)

        self.assertEqual(
            events,
            [
                {
                    "type": "diagnostic",
                    "name": "assistant_status",
                    "message": "I am checking the public evidence sources now.",
                }
            ],
        )

    def test_claude_terminal_result_is_visible_answer(self) -> None:
        line = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "result": "rs429358 is in APOE.",
            }
        )

        events = portal_agents.agent_events_for_line("claude", line)

        self.assertEqual(events, [{"type": "text_delta", "delta": "rs429358 is in APOE."}])

    def test_approved_tool_cleaning_rejects_shell_chaining(self) -> None:
        self.assertEqual(portal_agents.clean_approved_tool("Bash(git status); rm -rf /"), "")


if __name__ == "__main__":
    unittest.main()
