from __future__ import annotations

import io
import json
import os
import unittest
from unittest import mock

from genomi.interfaces import (
    portal_agents,
    portal_claude_runtime,
    portal_claude_stream,
    portal_run_events,
    portal_runs,
)
from genomi.runtime import context


ORCHESTRATOR_TEXT = json.dumps(
    {
        "type": "assistant",
        "message": {
            "model": "claude-opus-5",
            "id": "msg_011Ce67pfqHY475m7DhAQV6u",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "I'll spawn the reasoning_only subagent."}],
        },
        "parent_tool_use_id": None,
        "session_id": "4e03042a-8376-405c-b8ae-97b3c128d786",
    }
)
AGENT_SPAWN = json.dumps(
    {
        "type": "assistant",
        "message": {
            "id": "msg_011Ce67pfqHY475m7DhAQV6u",
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_01Q9NEFLrToVJ5grGjGaab22",
                    "name": "Agent",
                    "input": {
                        "subagent_type": "public_literature",
                        "description": "CTLA4 literature review",
                        "prompt": "Review public literature for CTLA4 immune dysregulation.",
                        "run_in_background": False,
                    },
                    "caller": {"type": "direct"},
                }
            ],
        },
        "parent_tool_use_id": None,
    }
)
TASK_STARTED = json.dumps(
    {
        "type": "system",
        "subtype": "task_started",
        "task_id": "a5651591ae9299c63",
        "tool_use_id": "toolu_01Q9NEFLrToVJ5grGjGaab22",
        "description": "CTLA4 literature review",
        "subagent_type": "public_literature",
        "task_type": "local_agent",
        "prompt": "Review public literature for CTLA4 immune dysregulation.",
        "session_id": "4e03042a-8376-405c-b8ae-97b3c128d786",
    }
)
CHILD_TEXT = json.dumps(
    {
        "type": "assistant",
        "message": {
            "id": "msg_011Ce67pvbYK4FJhbCWbxR3S",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "CHILD ONLY analysis prose."}],
        },
        "parent_tool_use_id": "toolu_01Q9NEFLrToVJ5grGjGaab22",
        "subagent_type": "public_literature",
        "task_description": "CTLA4 literature review",
    }
)
TASK_UPDATED = json.dumps(
    {
        "type": "system",
        "subtype": "task_updated",
        "task_id": "a5651591ae9299c63",
        "patch": {"status": "completed", "end_time": 1786869209680},
    }
)
RECEIPT_ID = "result-receipt-abcdefghijklmnopqrstuvwxyz012345"
TASK_NOTIFICATION = json.dumps(
    {
        "type": "system",
        "subtype": "task_notification",
        "task_id": "a5651591ae9299c63",
        "tool_use_id": "toolu_01Q9NEFLrToVJ5grGjGaab22",
        "status": "completed",
        "output_file": "/tmp/tasks/a5651591ae9299c63.output",
        "summary": f"CTLA4 literature reviewed. Provider receipt: {RECEIPT_ID}",
        "usage": {"total_tokens": 784, "tool_uses": 1, "duration_ms": 2373},
    }
)
TOOL_USE_RESULT = json.dumps(
    {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "tool_use_id": "toolu_01Q9NEFLrToVJ5grGjGaab22",
                    "type": "tool_result",
                    "content": [
                        {
                            "type": "text",
                            "text": f"CTLA4 literature reviewed. Provider receipt: {RECEIPT_ID}",
                        },
                        {
                            "type": "text",
                            "text": "agentId: a5651591ae9299c63 (use SendMessage with to: 'a5651591ae9299c63')",
                        },
                    ],
                }
            ],
        },
        "parent_tool_use_id": None,
        "tool_use_result": {
            "status": "completed",
            "prompt": "Review public literature for CTLA4 immune dysregulation.",
            "agentId": "a5651591ae9299c63",
            "agentType": "public_literature",
            "content": [
                {
                    "type": "text",
                    "text": f"CTLA4 literature reviewed. Provider receipt: {RECEIPT_ID}",
                }
            ],
            "resolvedModel": "claude-opus-5[1m]",
            "totalDurationMs": 2374,
            "totalTokens": 869,
            "totalToolUseCount": 1,
        },
    }
)
TERMINAL_RESULT = json.dumps(
    {
        "is_error": False,
        "duration_api_ms": 11073,
        "num_turns": 2,
        "stop_reason": "end_turn",
        "session_id": "4e03042a-8376-405c-b8ae-97b3c128d786",
        "total_cost_usd": 0.09119875,
        "permission_denials": [],
        "terminal_reason": "completed",
        "subtype": "success",
        "result": "CTLA4 is an inhibitory T-cell receptor.",
        "type": "result",
        "duration_ms": 10057,
    }
)


def _create_assignment_result(
    call_id: str = "toolu_assignment",
    *,
    policy: str = "public_literature",
    assignment_id: str = "assignment-1",
) -> str:
    return json.dumps(
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "tool_use_id": call_id,
                        "type": "tool_result",
                        "content": json.dumps(
                            {
                                "dispatched_tool": "lab.create_specialist_assignment",
                                "assignment": {
                                    "specialist_assignment_id": assignment_id,
                                    "specialist_brief_id": "brief-1",
                                    "execution_policy": policy,
                                    "specialist_role": "Public-literature reviewer",
                                    "state": "proposed",
                                },
                            }
                        ),
                    }
                ],
            },
            "parent_tool_use_id": None,
        }
    )


def _create_assignment_call(
    call_id: str = "toolu_assignment",
    *,
    policy: str = "public_literature",
) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": call_id,
                        "name": "mcp__genomi__genomi_invoke",
                        "input": {
                            "tool": "lab.create_specialist_assignment",
                            "params": {"execution_policy": policy},
                        },
                    }
                ],
            },
            "parent_tool_use_id": None,
        }
    )


def _child_tool_use(operation: str, *, name: str = "mcp__genomi__genomi_invoke") -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_child_call",
                        "name": name,
                        "input": {"tool": operation, "params": {"query": "CTLA4"}},
                    }
                ],
            },
            "parent_tool_use_id": "toolu_01Q9NEFLrToVJ5grGjGaab22",
            "subagent_type": "public_literature",
        }
    )


def _child_bash() -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_child_bash",
                        "name": "Bash",
                        "input": {"command": "cat /etc/passwd"},
                    }
                ],
            },
            "parent_tool_use_id": "toolu_01Q9NEFLrToVJ5grGjGaab22",
            "subagent_type": "public_literature",
        }
    )


def _events(session: portal_claude_stream.ClaudeStreamSession, *lines: str) -> list[dict]:
    collected: list[dict] = []
    for line in lines:
        collected.extend(session.parse_line(line).events)
    return collected


def _bound_session() -> portal_claude_stream.ClaudeStreamSession:
    session = portal_claude_stream.ClaudeStreamSession(session_id="portal:project:frame")
    _events(session, _create_assignment_call(), _create_assignment_result(), AGENT_SPAWN, TASK_STARTED)
    return session


class ClaudeSpecialistLaneTests(unittest.TestCase):
    def test_orchestrator_text_stays_in_the_work_trail_and_result_is_the_answer(self) -> None:
        session = portal_claude_stream.ClaudeStreamSession()

        events = _events(session, ORCHESTRATOR_TEXT, TERMINAL_RESULT)

        self.assertEqual(
            events,
            [
                {
                    "type": "diagnostic",
                    "name": "assistant_status",
                    "message": "I'll spawn the reasoning_only subagent.",
                },
                {"type": "text_delta", "delta": "CTLA4 is an inhibitory T-cell receptor."},
            ],
        )

    def test_spawned_child_binds_to_the_assignment_its_policy_names(self) -> None:
        session = portal_claude_stream.ClaudeStreamSession(session_id="portal:project:frame")

        events = _events(
            session,
            _create_assignment_call(),
            _create_assignment_result(),
            AGENT_SPAWN,
            TASK_STARTED,
        )

        assignment_call = events[0]
        self.assertEqual(assignment_call["name"], "mcp__genomi__genomi_invoke")
        spawn = next(event for event in events if event.get("name") == "spawn_agent")
        self.assertEqual(
            spawn,
            {
                "type": "tool_call",
                "id": "toolu_01Q9NEFLrToVJ5grGjGaab22",
                "name": "spawn_agent",
                "input": {
                    "agent_id": "a5651591ae9299c63",
                    "task_name": "CTLA4 literature review",
                    "assignment_id": "assignment-1",
                    "execution_policy": "public_literature",
                    "specialist_role": "Public-literature reviewer",
                },
            },
        )

    def test_subagent_type_disambiguates_two_proposed_assignments(self) -> None:
        session = portal_claude_stream.ClaudeStreamSession(session_id="portal:project:frame")

        events = _events(
            session,
            _create_assignment_call("toolu_a", policy="experiment_design"),
            _create_assignment_result("toolu_a", policy="experiment_design", assignment_id="assignment-proto"),
            _create_assignment_call("toolu_b", policy="public_literature"),
            _create_assignment_result("toolu_b", policy="public_literature", assignment_id="assignment-lit"),
            AGENT_SPAWN,
            TASK_STARTED,
        )

        spawn = next(event for event in events if event.get("name") == "spawn_agent")
        self.assertEqual(spawn["input"]["assignment_id"], "assignment-lit")
        self.assertEqual(spawn["input"]["execution_policy"], "public_literature")

    def test_two_proposed_assignments_for_one_policy_report_ambiguous_binding(self) -> None:
        session = portal_claude_stream.ClaudeStreamSession(session_id="portal:project:frame")

        events = _events(
            session,
            _create_assignment_call("toolu_a"),
            _create_assignment_result("toolu_a", assignment_id="assignment-1"),
            _create_assignment_call("toolu_b"),
            _create_assignment_result("toolu_b", assignment_id="assignment-2"),
            AGENT_SPAWN,
            TASK_STARTED,
            _child_tool_use("paperclip.search_biomedical"),
        )

        spawn = next(event for event in events if event.get("name") == "spawn_agent")
        self.assertNotIn("assignment_id", spawn["input"])
        violation = next(
            event for event in events if event.get("name") == "specialist_policy_violation"
        )
        self.assertEqual(violation["message"], "specialist_policy_binding_ambiguous")

    def test_child_without_any_assignment_reports_missing_binding(self) -> None:
        session = portal_claude_stream.ClaudeStreamSession(session_id="portal:project:frame")

        events = _events(
            session,
            AGENT_SPAWN,
            TASK_STARTED,
            _child_tool_use("paperclip.search_biomedical"),
        )

        violation = next(
            event for event in events if event.get("name") == "specialist_policy_violation"
        )
        self.assertEqual(violation["message"], "specialist_policy_binding_missing")
        self.assertEqual(violation["payload"]["agent_id"], "a5651591ae9299c63")
        self.assertEqual(violation["payload"]["status"], "failed")

    def test_child_text_never_becomes_answer_text_or_a_top_level_tool_call(self) -> None:
        session = _bound_session()

        events = _events(session, CHILD_TEXT, _child_tool_use("paperclip.search_biomedical"))

        self.assertEqual([event for event in events if event["type"] == "text_delta"], [])
        self.assertEqual([event for event in events if event["type"] == "tool_call"], [])
        self.assertEqual(
            events,
            [
                {
                    "type": "tool_result",
                    "id": "specialist-progress:toolu_child_call",
                    "name": "specialist_progress",
                    "isError": False,
                    "content": "Searching public biomedical literature",
                    "payload": {
                        "updates": [
                            {
                                "agent_id": "a5651591ae9299c63",
                                "task_name": "CTLA4 literature review",
                                "status": "running",
                                "message": "Searching public biomedical literature",
                                "assignment_id": "assignment-1",
                            }
                        ]
                    },
                }
            ],
        )

    def test_completed_child_emits_the_spawn_agent_lifecycle_result(self) -> None:
        session = _bound_session()

        with mock.patch.object(
            portal_claude_stream.EVIDENCE_RESULT_RECEIPTS, "authorize_specialist_result"
        ):
            events = _events(session, CHILD_TEXT, TASK_UPDATED, TASK_NOTIFICATION, TOOL_USE_RESULT)

        result = next(event for event in events if event.get("name") == "spawn_agent")
        self.assertEqual(result["type"], "tool_result")
        self.assertEqual(result["id"], "toolu_01Q9NEFLrToVJ5grGjGaab22")
        self.assertFalse(result["isError"])
        self.assertEqual(result["payload"]["status"], "completed")
        self.assertEqual(
            result["payload"]["updates"],
            [
                {
                    "agent_id": "a5651591ae9299c63",
                    "task_name": "CTLA4 literature review",
                    "status": "completed",
                    "assignment_id": "assignment-1",
                    "message": f"CTLA4 literature reviewed. Provider receipt: {RECEIPT_ID}",
                }
            ],
        )
        self.assertEqual(
            result["payload"]["agentsStates"]["a5651591ae9299c63"]["status"], "completed"
        )

    def test_terminal_child_message_authorizes_only_its_observed_provider_receipt(self) -> None:
        session = _bound_session()

        with mock.patch.object(
            portal_claude_stream.EVIDENCE_RESULT_RECEIPTS, "authorize_specialist_result"
        ) as authorize:
            _events(session, TASK_NOTIFICATION, TOOL_USE_RESULT)

        authorize.assert_called_once_with(
            RECEIPT_ID,
            session_id="portal:project:frame",
            specialist_assignment_id="assignment-1",
            specialist_brief_id="brief-1",
            native_agent_id="a5651591ae9299c63",
            execution_policy="public_literature",
        )

    def test_policy_violating_child_is_reported_and_its_receipts_are_refused(self) -> None:
        session = _bound_session()

        with mock.patch.object(
            portal_claude_stream.EVIDENCE_RESULT_RECEIPTS, "authorize_specialist_result"
        ) as authorize:
            events = _events(session, _child_bash(), TASK_NOTIFICATION, TOOL_USE_RESULT)

        violation = next(
            event for event in events if event.get("name") == "specialist_policy_violation"
        )
        self.assertEqual(
            violation,
            {
                "type": "error",
                "name": "specialist_policy_violation",
                "message": "specialist_policy_forbids_Bash",
                "payload": {
                    "agent_id": "a5651591ae9299c63",
                    "assignment_id": "assignment-1",
                    "execution_policy": "public_literature",
                    "status": "failed",
                },
            },
        )
        authorize.assert_not_called()
        spawn_result = next(event for event in events if event.get("name") == "spawn_agent")
        self.assertTrue(spawn_result["isError"])
        self.assertEqual(spawn_result["payload"]["status"], "failed")

    def test_operation_outside_the_policy_is_a_violation(self) -> None:
        session = _bound_session()

        with mock.patch.object(
            portal_claude_stream.EVIDENCE_RESULT_RECEIPTS, "authorize_specialist_result"
        ) as authorize:
            events = _events(
                session,
                _child_tool_use("proto.run_tool"),
                TASK_NOTIFICATION,
                TOOL_USE_RESULT,
            )

        violation = next(
            event for event in events if event.get("name") == "specialist_policy_violation"
        )
        self.assertEqual(violation["message"], "specialist_policy_operation_not_allowed")
        authorize.assert_not_called()

    def test_permission_denials_become_a_portal_permission_request(self) -> None:
        session = portal_claude_stream.ClaudeStreamSession()
        denied = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "permission_denials": [
                    {
                        "tool_name": "Bash",
                        "tool_use_id": "toolu_01Fo92b47N56NKf8FkqkuKq1",
                        "tool_input": {
                            "command": "curl -s https://example.com | head -c 20",
                            "description": "Fetch example.com",
                        },
                    }
                ],
                "result": "Bash is blocked in this session.",
            }
        )

        events = _events(session, denied)

        self.assertEqual(
            events[0],
            {
                "type": "error",
                "name": "host_agent_permission_request",
                "message": "Claude requested permission to use Bash.",
                "permission_request": {
                    "kind": "host_agent_tool",
                    "tool": "Bash",
                    "label": "Shell command",
                },
            },
        )
        self.assertEqual(events[1], {"type": "text_delta", "delta": "Bash is blocked in this session."})

    def test_continued_specialist_completes_on_its_task_notification(self) -> None:
        session = _bound_session()
        with mock.patch.object(
            portal_claude_stream.EVIDENCE_RESULT_RECEIPTS, "authorize_specialist_result"
        ):
            _events(session, TASK_NOTIFICATION, TOOL_USE_RESULT)
        follow_up_receipt = "result-receipt-zyxwvutsrqponmlkjihgfedcba987654"
        send_message = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_01SVUVSnka1jYzMPM259wx74",
                            "name": "SendMessage",
                            "input": {
                                "to": "a5651591ae9299c63",
                                "summary": "Re-run key literature retrievals for receipts",
                                "message": "Same brief, same policy.",
                            },
                        }
                    ],
                },
                "parent_tool_use_id": None,
            }
        )
        continued_task_started = json.dumps(
            {
                "type": "system",
                "subtype": "task_started",
                "task_id": "a5651591ae9299c63",
                "tool_use_id": "toolu_01SVUVSnka1jYzMPM259wx74",
                "description": "CTLA4 literature review",
                "subagent_type": "public_literature",
                "task_type": "local_agent",
                "prompt": "Same brief, same policy.",
            }
        )
        resume_ack = json.dumps(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "tool_use_id": "toolu_01SVUVSnka1jYzMPM259wx74",
                            "type": "tool_result",
                            "content": "Resuming agent a565159",
                        }
                    ],
                },
                "parent_tool_use_id": None,
                "tool_use_result": {
                    "success": True,
                    "message": "Resuming agent a565159",
                    "resumedAgentId": "a5651591ae9299c63",
                    "pin": {},
                },
            }
        )
        continued_notification = json.dumps(
            {
                "type": "system",
                "subtype": "task_notification",
                "task_id": "a5651591ae9299c63",
                "tool_use_id": "toolu_01SVUVSnka1jYzMPM259wx74",
                "status": "completed",
                "summary": f"Second pass. Provider receipt: {follow_up_receipt}",
            }
        )

        with mock.patch.object(
            portal_claude_stream.EVIDENCE_RESULT_RECEIPTS, "authorize_specialist_result"
        ) as authorize:
            events = _events(
                session,
                _create_assignment_call("toolu_second_assignment"),
                _create_assignment_result(
                    "toolu_second_assignment", assignment_id="assignment-2"
                ),
                send_message,
                continued_task_started,
                resume_ack,
                continued_notification,
            )

        # The resume acknowledgement is not the child's terminal result.
        self.assertEqual(
            [event["id"] for event in events if event["type"] == "tool_result" and event["name"] is None],
            ["toolu_second_assignment"],
        )
        completion = next(
            event
            for event in events
            if event.get("name") == "spawn_agent" and event["type"] == "tool_result"
        )
        self.assertEqual(completion["id"], "toolu_01SVUVSnka1jYzMPM259wx74")
        self.assertEqual(completion["payload"]["status"], "completed")
        self.assertEqual(
            completion["payload"]["updates"][0]["assignment_id"], "assignment-2"
        )
        authorize.assert_called_once_with(
            follow_up_receipt,
            session_id="portal:project:frame",
            specialist_assignment_id="assignment-2",
            specialist_brief_id="brief-1",
            native_agent_id="a5651591ae9299c63",
            execution_policy="public_literature",
        )

    def test_replayed_user_text_is_not_presented_as_host_work(self) -> None:
        session = portal_claude_stream.ClaudeStreamSession()
        replayed = json.dumps(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "My original question."}],
                },
                "parent_tool_use_id": None,
            }
        )

        self.assertEqual(_events(session, replayed), [])

    def test_each_run_owns_its_specialist_state(self) -> None:
        first = portal_agents.new_stream_adapter("claude", session_id="portal:a:1")
        second = portal_agents.new_stream_adapter("claude", session_id="portal:b:2")

        self.assertIsNot(first, second)
        self.assertEqual(first.session_id, "portal:a:1")
        self.assertEqual(second.session_id, "portal:b:2")
        _events(first, _create_assignment_call(), _create_assignment_result(), AGENT_SPAWN, TASK_STARTED)
        second_events = _events(second, AGENT_SPAWN, TASK_STARTED)
        spawn = next(event for event in second_events if event.get("name") == "spawn_agent")
        self.assertNotIn("assignment_id", spawn["input"])


class ClaudeRuntimeBindingTests(unittest.TestCase):
    def test_runtime_args_bind_only_this_portal_genomi_server(self) -> None:
        args = portal_claude_runtime.runtime_args(
            {"GENOMI_SESSION_ID": "portal:project:frame", "UNRELATED_SECRET": "no"}
        )

        self.assertIn("--strict-mcp-config", args)
        servers = json.loads(args[args.index("--mcp-config") + 1])
        genomi = servers["mcpServers"]["genomi"]
        self.assertEqual(genomi["args"], ["-m", "genomi", "serve", "--transport", "stdio"])
        self.assertEqual(genomi["env"]["GENOMI_SESSION_ID"], "portal:project:frame")
        self.assertNotIn("UNRELATED_SECRET", genomi["env"])

    def test_every_specialist_policy_becomes_a_tool_scoped_claude_subagent(self) -> None:
        definitions = portal_claude_runtime.specialist_agent_definitions()

        self.assertEqual(
            set(definitions),
            {
                "reasoning_only",
                "public_literature",
                "protein_model_research",
                "experiment_design",
            },
        )
        self.assertEqual(definitions["reasoning_only"]["tools"], [])
        self.assertEqual(
            definitions["public_literature"]["tools"],
            ["mcp__genomi__genomi_invoke"],
        )
        self.assertIn(
            "paperclip.search_biomedical", definitions["public_literature"]["description"]
        )
        self.assertIn("public_literature", definitions["public_literature"]["prompt"])
        self.assertIn(
            "paperclip.retrieve_document_evidence",
            definitions["public_literature"]["prompt"],
        )

    def test_command_keeps_the_variadic_allowed_tools_list_last(self) -> None:
        command = portal_claude_runtime.command_with_runtime(
            ["/usr/local/bin/claude", "-p", "--allowedTools", "mcp__genomi__*", "Task"],
            {},
        )

        self.assertEqual(command[0], "/usr/local/bin/claude")
        self.assertEqual(command[-3:], ["--allowedTools", "mcp__genomi__*", "Task"])
        self.assertIn("--agents", command)
        self.assertLess(command.index("--agents"), command.index("--allowedTools"))


class ClaudePortalRunTests(unittest.TestCase):
    def test_portal_binds_the_session_the_child_genomi_runtime_computes(self) -> None:
        environment = {
            "GENOMI_CONTEXT": "/private/project/context.json",
            "GENOMI_SESSION_ID": "portal:project:frame",
        }

        with mock.patch.dict(os.environ, environment, clear=False):
            self.assertEqual(
                context.context_scope()["id"],
                context.environment_scope_id(environment),
            )

    def test_claude_run_streams_answer_text_through_a_run_scoped_adapter(self) -> None:
        run = portal_run_events.create_run(
            kind="host_agent", agent_id="claude", message="Question"
        )
        self.addCleanup(portal_run_events.discard_run, run.id)

        class ClaudeProcess:
            stdin = io.StringIO()
            stdout = [ORCHESTRATOR_TEXT + "\n", TERMINAL_RESULT + "\n"]
            stderr = None

            def poll(self) -> int:
                return 0

            def wait(self, timeout: int | None = None) -> int:
                return 0

        commands: list[list[str]] = []

        def fake_popen(command: list[str], **_kwargs: object) -> object:
            commands.append(command)
            return ClaudeProcess()

        with mock.patch(
            "genomi.interfaces.portal_agents.agent_invocation",
            return_value=[
                "/usr/local/bin/claude",
                "-p",
                "--allowedTools",
                "mcp__genomi__*",
                "Task",
            ],
        ), mock.patch(
            "genomi.interfaces.portal_runs.subprocess.Popen", side_effect=fake_popen
        ), mock.patch(
            "genomi.interfaces.portal_run_logs.append_run_event"
        ):
            portal_runs.run_agent(run)

        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.output, "CTLA4 is an inhibitory T-cell receptor.")
        self.assertIn("--strict-mcp-config", commands[0])
        servers = json.loads(commands[0][commands[0].index("--mcp-config") + 1])
        self.assertIn("genomi", servers["mcpServers"])
        agents = json.loads(commands[0][commands[0].index("--agents") + 1])
        self.assertIn("public_literature", agents)
        self.assertEqual(commands[0][-3:], ["--allowedTools", "mcp__genomi__*", "Task"])


class ClaudeDriverInvocationTests(unittest.TestCase):
    def test_driver_streams_subagent_text_and_reports_denied_tools(self) -> None:
        with mock.patch(
            "genomi.interfaces.portal_agents.shutil.which",
            return_value="/usr/local/bin/claude",
        ):
            invocation = portal_agents.agent_invocation("claude", approved_tools=["WebSearch"])

        assert invocation is not None
        self.assertIn("--forward-subagent-text", invocation)
        self.assertEqual(
            invocation[invocation.index("--permission-mode") + 1], "dontAsk"
        )
        self.assertEqual(
            invocation[invocation.index("--allowedTools") + 1 :],
            ["mcp__genomi__*", "Task", "WebSearch"],
        )


if __name__ == "__main__":
    unittest.main()
