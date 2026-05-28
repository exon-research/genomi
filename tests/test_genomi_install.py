from __future__ import annotations

from unittest import mock

from genomi.interfaces.cli import build_parser
from genomi.operations import call_operation

from _genomi_runtime_helpers import GenomiRuntimeTestCase


class GenomiInstallTests(GenomiRuntimeTestCase):
    def test_bare_install_defaults_to_setup_only_update(self) -> None:
        # `genomi install` with no flags is the "just update Genomi" path: it
        # must parse (no required --libraries) and default to setup-only so it
        # updates the runtime without touching reference libraries.
        args = build_parser().parse_args(["install"])
        self.assertEqual(args.libraries, "setup-only")
        self.assertFalse(args.force)

    def test_update_is_a_cli_alias_of_install_not_a_separate_command(self) -> None:
        install = build_parser().parse_args(["install", "--libraries", "everything"])
        update = build_parser().parse_args(["update", "--libraries", "everything"])
        # Same handler, same defaults — a true alias, not a duplicate command.
        self.assertIs(update.func, install.func)
        self.assertEqual(build_parser().parse_args(["update"]).libraries, "setup-only")

    def test_no_separate_update_tool_and_install_description_covers_update(self) -> None:
        from genomi.operations.registry.table import OPERATIONS

        by_name = {op.name: op for op in OPERATIONS}
        # The alias lives in wording, not a duplicate MCP tool.
        self.assertNotIn("genomi.update", by_name)
        description = by_name["genomi.install"].tool_definition()["description"]
        self.assertIn("update", description.lower())
        # A bare update call must be valid: libraries is not a required field.
        self.assertNotIn(
            "libraries",
            by_name["genomi.install"].tool_definition()["inputSchema"].get("required", []),
        )

    def test_setup_only_install_persists_response_profile_without_context_disclosure(self) -> None:
        result = call_operation("genomi.install", {"libraries": "setup-only", "response_profile": "expert"})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["install"]["status"], "skipped")
        self.assertEqual(result["active_response_profile"]["id"], "expert")
        self.assertEqual(result["install_scope"]["updates"][0], "genomi_home_setup")
        self.assertEqual(result["runtime_update"]["status"], "unconfigured")

    def test_library_inventory_points_to_genomi_install_command(self) -> None:
        result = call_operation("genomi.install", {"libraries": "setup-only"})
        commands = [item["install_command"] for item in result["library_inventory"]["libraries"]]

        self.assertTrue(commands)
        self.assertTrue(all(command.startswith("genomi install --libraries ") for command in commands))

    def test_packaged_runtime_reports_external_update_provider(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "GENOMI_RUNTIME_UPDATE": "external:Install a newer package.",
            },
        ):
            result = call_operation("genomi.install", {"libraries": "setup-only"})

        runtime_update = result["runtime_update"]
        self.assertEqual(runtime_update["status"], "external")
        self.assertEqual(runtime_update["provider"], "external")
        self.assertEqual(runtime_update["message"], "Install a newer package.")
