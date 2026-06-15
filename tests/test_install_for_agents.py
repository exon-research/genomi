from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.runtime.libraries import registry
from genomi.runtime.libraries.manager import inventory as library_inventory
from genomi.runtime.libraries.manager import missing_request as library_install_request
from genomi.runtime.libraries.manager import status as library_status

# Catalog facts now live only in the central registry.
DEFAULT_LIBRARIES = list(registry.default_everything())
MANUAL_SOURCE_LIBRARIES = frozenset(
    spec.id for spec in registry.all_specs() if spec.manual_source_required
)

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "install_for_agents.py"
SPEC = importlib.util.spec_from_file_location("install_for_agents", SCRIPT_PATH)
assert SPEC is not None
install_for_agents = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(install_for_agents)


class InstallForAgentsTests(unittest.TestCase):
    def test_parse_library_selection_accepts_exact_purposes(self) -> None:
        self.assertEqual(
            install_for_agents.parse_library_selection("everything"),
            DEFAULT_LIBRARIES,
        )
        self.assertEqual(
            install_for_agents.parse_library_selection("setup-only"),
            [],
        )
        self.assertEqual(
            install_for_agents.parse_library_selection("common-questions"),
            ["clinvar-grch38", "hpo", "gencc", "pgs-catalog-score-metadata"],
        )
        self.assertEqual(
            install_for_agents.parse_library_selection("medication-response"),
            ["clinvar-grch38", "hpo", "gencc", "pharmcat"],
        )
        self.assertEqual(
            install_for_agents.parse_library_selection("ancestry-context"),
            ["ancestry-1000g-30x-grch38", "ancestry-1000g-30x-grch37"],
        )
        self.assertEqual(
            install_for_agents.parse_library_selection("sequence-and-regions"),
            ["clinvar-grch38", "reference-grch38", "gencode-grch38", "encode-ccre-grch38"],
        )
        self.assertEqual(
            install_for_agents.parse_library_selection("cell-and-tissue"),
            ["panglaodb-markers", "cellmarker-human"],
        )
        self.assertIn("gencode-grch38", DEFAULT_LIBRARIES)
        self.assertIn("cellmarker-human", DEFAULT_LIBRARIES)
        manual_download_overlap = set(DEFAULT_LIBRARIES) & MANUAL_SOURCE_LIBRARIES
        self.assertEqual(manual_download_overlap, set())
        # The ancestry panel is now a ~3 MB tarball download from the
        # genomi-ancestry-panel release plus a small derived GRCh37 panel;
        # no longer an opt-in heavy build.
        self.assertIn("ancestry-1000g-30x-grch38", DEFAULT_LIBRARIES)
        self.assertIn("ancestry-1000g-30x-grch37", DEFAULT_LIBRARIES)

    def test_parse_library_selection_accepts_exact_library_ids(self) -> None:
        self.assertEqual(
            install_for_agents.parse_library_selection("clinvar-grch38,hpo,gencc"),
            ["clinvar-grch38", "hpo", "gencc"],
        )
        self.assertEqual(
            install_for_agents.parse_library_selection("ancestry-1000g-30x-grch38"),
            ["ancestry-1000g-30x-grch38"],
        )

    def test_empty_library_selection_requires_explicit_choice(self) -> None:
        with self.assertRaises(SystemExit):
            install_for_agents.parse_library_selection("")

    def test_non_tty_requires_explicit_library_selection(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            install_for_agents.resolve_library_selection(None)
        self.assertIn("--libraries", str(raised.exception))

    def test_host_skill_install_prints_generic_invocation_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            host_skill_dirs = [
                Path(tmp) / "host-a" / "skills",
                Path(tmp) / "host-b" / "skills",
            ]
            args = [
                "--libraries",
                "setup-only",
                "--skip-package",
                "--skip-verify",
            ]
            for skill_dir in host_skill_dirs:
                args.extend(["--host-skill-dir", str(skill_dir)])
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"GENOMI_HOME": str(Path(tmp) / "genomi-home")}),
                contextlib.redirect_stdout(output),
            ):
                result = install_for_agents.main(args)
            self.assertEqual(result, 0)
            for skill_dir in host_skill_dirs:
                self.assertTrue((skill_dir / "genomi").is_symlink(), str(skill_dir))
                self.assertEqual((skill_dir / "genomi").resolve(), install_for_agents.REPO_ROOT)
                self.assertTrue((skill_dir / "genomi" / "SKILL.md").is_file())
                self.assertTrue((skill_dir / "genomi-decode").is_symlink(), str(skill_dir))
                self.assertTrue((skill_dir / "genomi-decode" / "SKILL.md").is_file())
            text = output.getvalue()
            for expected in [
                "Host skill invocation:",
                "controlled by the active host",
                "list installed skills",
                "Do not assume /genomi works in every host.",
                "/genomi decode (Codex: $genomi-decode)",
            ]:
                self.assertIn(expected, text)

    def test_install_guide_names_bgzip_linux_package_and_codex_decode_skill(self) -> None:
        guide = (Path(__file__).resolve().parents[1] / "INSTALL_FOR_AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Genomi's VCF/gVCF parse path requires `bgzip`", guide)
        self.assertIn("On Linux, install the `tabix`", guide)
        self.assertIn("`/genomi decode`", guide)
        self.assertIn("Codex is the\n   exception: use **`$genomi-decode`**", guide)

    def test_installer_creates_stable_genomi_command_shim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "genomi-home"
            resolved_home = home.resolve(strict=False)
            with mock.patch.dict(os.environ, {"GENOMI_HOME": str(home)}):
                shim = install_for_agents.install_genomi_command_shim()

            self.assertEqual(shim, resolved_home / "bin" / "genomi")
            self.assertTrue(shim.is_file())
            self.assertTrue(os.access(shim, os.X_OK))
            text = shim.read_text(encoding="utf-8")
            self.assertIn(f"GENOMI_HOME={resolved_home}", text)
            self.assertIn("export GENOMI_HOME", text)
            self.assertIn("-m genomi", text)

    def test_installer_default_home_uses_xdg_data_home_without_genomi_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xdg_home = Path(tmp) / "xdg-data"
            expected_home = (xdg_home / "genomi").resolve(strict=False)
            with (
                mock.patch.dict(os.environ, {"HOME": str(Path(tmp) / "home"), "XDG_DATA_HOME": str(xdg_home)}),
                mock.patch("genomi.runtime.paths.sys.platform", "darwin"),
            ):
                os.environ.pop("GENOMI_HOME", None)
                shim = install_for_agents.install_genomi_command_shim()

            self.assertEqual(shim, expected_home / "bin" / "genomi")
            text = shim.read_text(encoding="utf-8")
            self.assertIn(f"GENOMI_HOME={expected_home}", text)

    def test_genomi_command_shim_preserves_explicit_genomi_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "genomi-home"
            override = Path(tmp) / "override-home"
            with mock.patch.dict(os.environ, {"GENOMI_HOME": str(home)}):
                shim = install_for_agents.install_genomi_command_shim()

            env = os.environ.copy()
            env["GENOMI_HOME"] = str(override)
            result = subprocess.run(
                [str(shim), "call", "genomi.describe_context", "--params", "{}"],
                env={**env, "GENOMI_CLI": "1"},
                text=True,
                capture_output=True,
                check=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["active_genome_index"], None)
            self.assertEqual(payload["users"], [])

    def test_main_verifies_through_stable_genomi_command_shim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "genomi-home"
            resolved_home = home.resolve(strict=False)
            with (
                mock.patch.dict(os.environ, {"GENOMI_HOME": str(home)}),
                mock.patch.object(install_for_agents, "run"),
                mock.patch.object(install_for_agents, "install_libraries"),
                mock.patch.object(install_for_agents, "install_host_agent_skill"),
                mock.patch.object(install_for_agents, "_verify") as verify,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = install_for_agents.main(["--libraries", "setup-only"])

            self.assertEqual(result, 0)
            verify.assert_called_once()
            self.assertEqual(verify.call_args.args[1], [str(resolved_home / "bin" / "genomi"), "tools"])

    def test_install_into_populated_home_does_not_abort(self) -> None:
        # A populated GENOMI_HOME must not block a fill-the-gap install: the
        # per-library installers skip what already exists, so main() should run
        # to completion (downloading only what's missing) without --force.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "genomi-home"
            for child in ("resources", "reference", "tools"):
                (home / child).mkdir(parents=True)
                (home / child / "existing.bin").write_text("cached", encoding="utf-8")

            with (
                mock.patch.dict(os.environ, {"GENOMI_HOME": str(home)}),
                mock.patch.object(install_for_agents, "run"),
                mock.patch.object(install_for_agents, "install_libraries") as install_libraries,
                mock.patch.object(install_for_agents, "install_host_agent_skill"),
                mock.patch.object(install_for_agents, "_verify"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = install_for_agents.main(["--libraries", "everything"])

            self.assertEqual(result, 0)
            install_libraries.assert_called_once()

    def test_parse_args_accepts_genome_source_import_flags(self) -> None:
        args = install_for_agents.parse_args(
            [
                "--libraries",
                "ancestry-1000g-30x-grch38",
                "--genome-source",
                "/tmp/sample.vcf",
                "--user-nickname",
                "Default user",
                "--set-default-user",
            ]
        )
        self.assertEqual(args.genome_source, "/tmp/sample.vcf")
        self.assertEqual(args.user_nickname, "Default user")
        self.assertTrue(args.set_default_user)

    def test_genome_import_calls_parse_source_with_core_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.vcf"
            source.write_text("##fileformat=VCFv4.2\n", encoding="utf-8")
            args = install_for_agents.parse_args(
                [
                    "--genome-source",
                    str(source),
                    "--user-nickname",
                    "MT",
                    "--set-default-user",
                ]
            )

            with (
                mock.patch.object(install_for_agents, "_load_existing_users", return_value=[]),
                mock.patch("genomi.operations.call_operation") as call_operation,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                call_operation.return_value = {
                    "status": "completed",
                    "active_genome_index": {"agi_id": "agi-test"},
                }
                install_for_agents.configure_genome_source(args)

            self.assertEqual(call_operation.call_args.args[0], "genomi.parse_source")
            self.assertEqual(
                call_operation.call_args.args[1],
                {
                    "source": str(source),
                    "user_nickname": "MT",
                    "set_default_user": True,
                },
            )

    def test_user_nickname_defaults_late_for_unambiguous_import(self) -> None:
        args = install_for_agents.parse_args(["--genome-source", "/tmp/sample.vcf"])
        self.assertIsNone(args.user_nickname)
        nickname = install_for_agents.resolve_genome_source_user_nickname(
            args.user_nickname,
            existing_users=[],
        )
        self.assertEqual(nickname, "Default user")

    def test_existing_users_require_explicit_assignment_without_tty(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            install_for_agents.resolve_genome_source_user_nickname(
                None,
                existing_users=[{"nickname": "Alex", "user_id": "user-alex"}],
            )
        self.assertIn("--user-nickname", str(raised.exception))

    def test_library_status_reports_install_guidance_without_personal_context(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}),
        ):
            status = library_status("clinvar-grch38")
            request = library_install_request(
                "clinvar-grch38",
                intent="ClinVar candidate triage",
                operation="clinvar.match_variants",
                genome_build="GRCh38",
            )
            inventory = library_inventory()
            ancestry = library_status("ancestry-1000g-30x-grch38")

        self.assertFalse(status["installed"])
        self.assertEqual(status["status"], "not_installed")
        self.assertIn("--libraries clinvar-grch38", status["install_command"])
        self.assertEqual(request["status"], "requires_library_install")
        self.assertIn("question", request["ask_user"])
        self.assertIn("ClinVar candidate triage", request["how_it_helps"])
        self.assertGreaterEqual(inventory["summary"]["library_count"], 1)
        self.assertFalse(ancestry["installed"])
        self.assertIn("reference/ancestry/1000g_30x_grch38/manifest.json", ancestry["required_paths"][0])
        self.assertIn("--libraries ancestry-1000g-30x-grch38", ancestry["install_command"])


if __name__ == "__main__":
    unittest.main()
