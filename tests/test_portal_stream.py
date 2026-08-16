from __future__ import annotations

import json
import unittest

from genomi.interfaces import portal_agents


class PortalStreamTests(unittest.TestCase):
    def test_claude_tool_use_stream_event_becomes_tool_card_event(self) -> None:
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "variant.resolve",
                            "input": {"rsid": "rs429358"},
                        },
                        {"type": "text", "text": "I will check the variant."},
                    ]
                },
            }
        )

        events = portal_agents.agent_events_for_line("claude", line)

        self.assertEqual(events[0]["type"], "tool_call")
        self.assertEqual(events[0]["id"], "toolu_1")
        self.assertEqual(events[0]["name"], "variant.resolve")
        self.assertEqual(events[0]["input"], {"rsid": "rs429358"})
        # The terminal `result` line is the single source of answer text, so
        # streamed assistant prose stays in the work trail.
        self.assertEqual(
            events[1],
            {
                "type": "diagnostic",
                "name": "assistant_status",
                "message": "I will check the variant.",
            },
        )

    def test_tool_result_stream_event_stays_structured(self) -> None:
        line = json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "{\"status\":\"completed\"}",
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
                    "type": "tool_result",
                    "id": "toolu_1",
                    "name": None,
                    "isError": False,
                    "content": "{\"status\":\"completed\"}",
                    "payload": {"status": "completed"},
                }
            ],
        )

    def test_claude_adapter_does_not_scrape_arbitrary_nested_tool_like_json(self) -> None:
        line = json.dumps(
            {
                "type": "metadata",
                "payload": {
                    "tool_use_id": "toolu_1",
                    "content": "{\"status\":\"completed\"}",
                },
            }
        )

        events = portal_agents.agent_events_for_line("claude", line)
        parsed = portal_agents.parse_agent_line("claude", line)

        self.assertEqual(events, [])
        self.assertEqual(parsed.kind, "ignored_structured_event")
        self.assertIsNone(parsed.stdout)

    def test_tool_result_keeps_full_structured_payload_beside_truncated_preview(self) -> None:
        result = {
            "headline": "variant.resolve: data_returned",
            "status": "completed",
            "evidence_envelope": {"finding_state": "data_returned", "answer_readiness": "answer_supported"},
            "long_field": "x" * 6000,
        }
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": json.dumps(result),
                },
            }
        )

        events = portal_agents.agent_events_for_line("codex", line)

        self.assertEqual(events[0]["type"], "tool_result")
        self.assertEqual(events[0]["payload"]["evidence_envelope"]["finding_state"], "data_returned")
        self.assertEqual(len(events[0]["payload"]["long_field"]), 6000)
        self.assertLessEqual(len(events[0]["content"]), 4003)

    def test_codex_function_call_event_becomes_tool_card_event(self) -> None:
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

        self.assertEqual(
            events,
            [
                {
                    "type": "tool_call",
                    "id": "call_1",
                    "name": "variant.resolve",
                    "input": {"rsid": "rs429358"},
                }
            ],
        )

    def test_codex_function_output_event_becomes_tool_result(self) -> None:
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": {"status": "completed"},
                },
            }
        )

        events = portal_agents.agent_events_for_line("codex", line)

        self.assertEqual(events[0]["type"], "tool_result")
        self.assertEqual(events[0]["id"], "call_1")
        self.assertEqual(events[0]["content"], "{\"status\":\"completed\"}")

    def test_codex_agent_message_event_becomes_text_delta(self) -> None:
        line = json.dumps({"type": "agent_message", "message": "I checked the variant."})

        events = portal_agents.agent_events_for_line("codex", line)

        self.assertEqual(events, [{"type": "text_delta", "delta": "I checked the variant."}])

    def test_codex_skill_load_dump_becomes_diagnostic_not_answer_delta(self) -> None:
        line = json.dumps(
            {
                "type": "agent_message",
                "message": "Base directory for this skill: /Users/matthewzmd/.codex/skills/genomi\n# Genomi\n## Goal\n...",
            }
        )

        events = portal_agents.agent_events_for_line("codex", line)

        self.assertEqual(events[0]["type"], "diagnostic")
        self.assertEqual(events[0]["name"], "host_agent_context_load")
        self.assertIn("Base directory for this skill", events[0]["message"])
        self.assertNotIn("delta", events[0])

    def test_codex_non_json_skill_load_dump_uses_diagnostic_classification(self) -> None:
        parsed = portal_agents.parse_agent_line(
            "codex",
            "Base directory for this skill: /Users/matthewzmd/.codex/skills/genomi\n",
        )

        self.assertEqual(parsed.kind, "events")
        self.assertIsNone(parsed.stdout)
        self.assertEqual(parsed.events[0]["type"], "diagnostic")
        self.assertEqual(parsed.events[0]["name"], "host_agent_context_load")
        self.assertNotIn("delta", parsed.events[0])

    def test_gemini_tool_call_event_becomes_tool_card_event(self) -> None:
        line = json.dumps(
            {
                "type": "function_call",
                "id": "fn_1",
                "function_name": "variant.resolve",
                "arguments": {"rsid": "rs429358"},
            }
        )

        events = portal_agents.agent_events_for_line("gemini", line)

        self.assertEqual(
            events,
            [
                {
                    "type": "tool_call",
                    "id": "fn_1",
                    "name": "variant.resolve",
                    "input": {"rsid": "rs429358"},
                }
            ],
        )

    def test_unknown_agent_keeps_plain_text_fallback(self) -> None:
        events = portal_agents.agent_events_for_line("custom", "plain output\n")

        self.assertEqual(events, [{"type": "text_delta", "delta": "plain output\n"}])


if __name__ == "__main__":
    unittest.main()
