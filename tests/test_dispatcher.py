"""genomi.invoke dispatcher contract tests.

The dispatcher is the only MCP-side path from the base tools list to
capability tools. These tests assert its positive behaviours: successful
dispatch into capability handlers, structured errors for unknown tools or
base-tool misuse, and parameter validation forwarded from the underlying
tool's schema.
"""

from __future__ import annotations

import unittest

from genomi.operations import OperationError, call_operation


class GenomiInvokeDispatcherTests(unittest.TestCase):
    def test_invoke_dispatches_to_capability_tool(self) -> None:
        # A well-formed dispatch should reach the underlying handler and
        # surface its validation errors (we use missing params so the
        # underlying handler complains, but we should see THAT error rather
        # than an invoke-layer error).
        with self.assertRaises(OperationError) as raised:
            call_operation(
                "genomi.invoke",
                {"tool": "gnomad.fetch_population_frequency", "params": {}},
            )
        # Underlying tool's own validation should fire — not the dispatcher's.
        self.assertEqual(raised.exception.code, "invalid_params")
        self.assertNotEqual(raised.exception.code, "unknown_tool")
        self.assertNotEqual(raised.exception.code, "tool_not_dispatchable")

    def test_invoke_rejects_unknown_tool_name(self) -> None:
        with self.assertRaises(OperationError) as raised:
            call_operation(
                "genomi.invoke",
                {"tool": "fakecap.no_such_op", "params": {}},
            )
        self.assertEqual(raised.exception.code, "unknown_tool")
        self.assertIn("Anthropic Skills", raised.exception.message)

    def test_invoke_rejects_base_capability_tool(self) -> None:
        # Base tools (genomi.* / journal.*) are in tools/list directly and
        # must not be reached through the dispatcher.
        for name in ("genomi.list_resources", "journal.append_entry"):
            with self.subTest(tool=name):
                with self.assertRaises(OperationError) as raised:
                    call_operation("genomi.invoke", {"tool": name, "params": {}})
                self.assertEqual(raised.exception.code, "tool_not_dispatchable")
                self.assertIn("base tool", raised.exception.message)

    def test_invoke_rejects_missing_or_malformed_arguments(self) -> None:
        for bad_params in (
            {},
            {"tool": ""},
            {"tool": "gnomad.fetch_population_frequency"},
            {"params": {}},
            {"tool": 123, "params": {}},
            {"tool": "gnomad.fetch_population_frequency", "params": "not-an-object"},
        ):
            with self.subTest(params=bad_params):
                with self.assertRaises(OperationError) as raised:
                    call_operation("genomi.invoke", bad_params)
                self.assertEqual(raised.exception.code, "invalid_params")


if __name__ == "__main__":
    unittest.main()
