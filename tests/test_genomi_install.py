from __future__ import annotations

from unittest import mock

from genomi.active_genome_index.active_genome_index import (
    connect_existing,
    create_active_genome_index,
)
from genomi.active_genome_index._agi_schema import _upsert_metadata
from genomi.interfaces.cli import build_parser
from genomi.operations import call_operation
from genomi.runtime import context as runtime_context

from _genomi_runtime_helpers import GenomiRuntimeTestCase


def _register_stale_genome(home, *, stored_schema: int = 1):
    """Build a real index, mark its stored schema stale, and register it."""
    vcf = home / "stale.vcf"
    vcf.parent.mkdir(parents=True, exist_ok=True)
    vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS\n"
        "1\t100\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
    )
    index = vcf.with_suffix(".sqlite")
    create_active_genome_index(vcf, index)
    with connect_existing(index) as connection:
        _upsert_metadata(connection, "schema_version", stored_schema)
        connection.commit()
    runtime_context.set_active_genome_index(
        vcf, status="parsed", active_genome_index_path=index, genome_build="GRCh38"
    )
    return vcf, index


class GenomiInstallTests(GenomiRuntimeTestCase):
    def test_bare_install_defaults_to_everything(self) -> None:
        # `genomi install` / `genomi update` with no flags updates everything:
        # libraries default to 'everything'; runtime update and reparse-stale
        # are unconditional in the operation, not flags.
        args = build_parser().parse_args(["install"])
        self.assertEqual(args.libraries, "everything")
        self.assertFalse(args.force)

    def test_update_is_a_cli_alias_of_install_not_a_separate_command(self) -> None:
        install = build_parser().parse_args(["install", "--libraries", "everything"])
        update = build_parser().parse_args(["update", "--libraries", "everything"])
        # Same handler, same defaults — a true alias, not a duplicate command.
        self.assertIs(update.func, install.func)
        self.assertEqual(build_parser().parse_args(["update"]).libraries, "everything")

    def test_cli_install_requests_everything(self) -> None:
        # The command front door forwards the library selection; runtime update,
        # reindex, and reparse-stale are unconditional in the operation, so the
        # CLI no longer passes (now-removed) skip flags.
        captured: dict[str, object] = {}

        def _capture(operation: str, params: dict[str, object]) -> dict[str, object]:
            captured["operation"] = operation
            captured["params"] = params
            return {"status": "completed"}

        args = build_parser().parse_args(["update"])
        with mock.patch("genomi.interfaces.cli.call_operation", _capture):
            args.func(args)

        self.assertEqual(captured["operation"], "genomi.install")
        params = captured["params"]
        self.assertEqual(params["libraries"], "everything")
        self.assertNotIn("update_runtime", params)
        self.assertNotIn("reparse_stale", params)

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

    def test_install_persists_response_profile_without_context_disclosure(self) -> None:
        result = call_operation("genomi.install", {"response_profile": "expert"})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["install"]["status"], "completed")
        self.assertEqual(result["active_response_profile"]["id"], "expert")
        self.assertEqual(result["install_scope"]["updates"][0], "genomi_home_setup")
        # The operation always attempts the runtime pull; here the runtime is
        # not a git checkout (base test default), so it reports "unmanaged".
        self.assertEqual(result["runtime_update"]["status"], "unmanaged")

    def test_library_inventory_points_to_genomi_install_command(self) -> None:
        result = call_operation("genomi.install", {})
        commands = [item["install_command"] for item in result["library_inventory"]["libraries"]]

        self.assertTrue(commands)
        self.assertTrue(all(command.startswith("genomi install --libraries ") for command in commands))

    def test_operation_always_reparses_and_attempts_runtime_update(self) -> None:
        # No skip flags: a bare operation call reparses stale genomes and
        # attempts the runtime update. There is no way to call the operation
        # and have it silently skip those steps.
        vcf, _index = _register_stale_genome(self.genomi_home)
        with mock.patch(
            "genomi.runtime.background_jobs.start_operation_job",
            return_value={"job_id": "job-x", "job_path": "/tmp/job-x.json"},
        ):
            result = call_operation("genomi.install", {})
        self.assertEqual(result["reparse"]["stale"], 1)
        self.assertEqual(result["reparse"]["launched"][0]["source"], str(vcf))
        # Runtime pull was attempted (unmanaged here — not a git checkout).
        self.assertEqual(result["runtime_update"]["status"], "unmanaged")

    def test_reparse_stale_launches_background_job_per_genome(self) -> None:
        vcf, _index = _register_stale_genome(self.genomi_home)

        launched: list[tuple[str, dict]] = []

        def _fake_start(operation: str, params: dict) -> dict:
            launched.append((operation, params))
            return {"job_id": "job-x", "job_path": "/tmp/job-x.json"}

        with mock.patch(
            "genomi.runtime.background_jobs.start_operation_job", side_effect=_fake_start
        ):
            result = call_operation("genomi.install", {})

        reparse = result["reparse"]
        self.assertEqual(reparse["stale"], 1)
        self.assertEqual(len(reparse["launched"]), 1)
        self.assertEqual(reparse["launched"][0]["source"], str(vcf))
        self.assertEqual(launched, [("genomi.parse_source", {"source": str(vcf), "force": True})])

    def test_reparse_skips_genome_whose_source_is_gone(self) -> None:
        vcf, _index = _register_stale_genome(self.genomi_home)
        vcf.unlink()  # source no longer available — cannot rebuild

        with mock.patch("genomi.runtime.background_jobs.start_operation_job") as start:
            result = call_operation("genomi.install", {})

        start.assert_not_called()
        reparse = result["reparse"]
        self.assertEqual(reparse["stale"], 1)
        self.assertEqual(reparse["launched"], [])
        self.assertEqual(reparse["skipped"][0]["reason"], "source_unavailable")

    def test_skip_env_suppresses_runtime_git_pull(self) -> None:
        # The gate's whole reason for existing: a non-git distribution sets it so
        # `genomi update` never tries to git pull.
        with mock.patch.dict("os.environ", {"GENOMI_SKIP_RUNTIME_GIT_PULL": "1"}):
            result = call_operation(
                "genomi.install", {}
            )
        runtime_update = result["runtime_update"]
        self.assertEqual(runtime_update["status"], "skipped")
        self.assertFalse(runtime_update["restart_required"])
        self.assertIn("GENOMI_SKIP_RUNTIME_GIT_PULL", runtime_update["message"])

    def test_legacy_runtime_update_env_still_suppresses_git_pull(self) -> None:
        # Backward-compat: an existing install that set the retired command env
        # must not suddenly start pulling.
        with mock.patch.dict("os.environ", {"GENOMI_RUNTIME_UPDATE": "anything"}):
            result = call_operation(
                "genomi.install", {}
            )
        self.assertEqual(result["runtime_update"]["status"], "skipped")
        self.assertIn("GENOMI_RUNTIME_UPDATE", result["runtime_update"]["message"])


def _completed(returncode: int = 0, stdout: str = "", stderr: str = ""):
    import subprocess

    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _git_pull_sequence(*, before: str, after: str, dep_diff: str = "pyproject.toml"):
    """side_effect for handlers_admin._git simulating a clean, fast-forward pull.

    `dep_diff` is the `git diff --name-only` output for the dependency-manifest
    probe that runs after a code-changing pull (empty string = nothing changed).
    """
    responses = iter(
        [
            _completed(stdout=""),          # status --porcelain (clean tree)
            _completed(stdout=before),      # rev-parse HEAD (before)
            _completed(stdout="Updated."),  # pull --ff-only
            _completed(stdout=after),       # rev-parse HEAD (after)
            _completed(stdout=dep_diff),    # diff --name-only -- <manifests>
        ]
    )
    return lambda *args, **kwargs: next(responses)


class GenomiRuntimeDependencySyncTests(GenomiRuntimeTestCase):
    def test_manifest_changing_pull_reconciles_deps_with_pip(self) -> None:
        # A pull that moves HEAD and changes a dependency manifest reconciles
        # deps against the running interpreter — pulled code can otherwise
        # import a package that isn't present.
        from genomi.operations.registry import handlers_admin

        calls: list[list[str]] = []

        def _fake_run(command, **kwargs):
            calls.append(command)
            return _completed(stdout="Successfully installed genomi")

        with mock.patch.object(handlers_admin, "_reparse_stale_genomes", return_value=None), \
             mock.patch.object(handlers_admin, "_runtime_git_repo", return_value=handlers_admin.Path("/tmp/genomi-repo")), \
             mock.patch.object(handlers_admin, "_git", side_effect=_git_pull_sequence(before="aaa", after="bbb")), \
             mock.patch.object(handlers_admin.subprocess, "run", side_effect=_fake_run):
            result = call_operation(
                "genomi.install", {}
            )

        sync = result["runtime_update"]["dependency_sync"]
        self.assertEqual(sync["status"], "completed")
        self.assertEqual(sync["tool"], "pip")
        # Targets the running interpreter, editable, from the repo root.
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:4], [handlers_admin.sys.executable, "-m", "pip", "install"])
        self.assertIn("-e", calls[0])
        self.assertIn("/tmp/genomi-repo", calls[0])

    def test_pull_without_manifest_change_skips_reconcile(self) -> None:
        # Code changed but no dependency manifest did → no installer runs (we
        # don't assume/invoke a package manager when there's nothing to sync).
        from genomi.operations.registry import handlers_admin

        with mock.patch.object(handlers_admin, "_reparse_stale_genomes", return_value=None), \
             mock.patch.object(handlers_admin, "_runtime_git_repo", return_value=handlers_admin.Path("/tmp/genomi-repo")), \
             mock.patch.object(handlers_admin, "_git", side_effect=_git_pull_sequence(before="aaa", after="bbb", dep_diff="")), \
             mock.patch.object(handlers_admin.subprocess, "run", side_effect=AssertionError("no installer must run")):
            result = call_operation(
                "genomi.install", {}
            )

        sync = result["runtime_update"]["dependency_sync"]
        self.assertEqual(sync["status"], "skipped")

    def test_no_op_pull_does_not_reconcile(self) -> None:
        # HEAD unchanged → nothing pulled → no dependency probe at all.
        from genomi.operations.registry import handlers_admin

        with mock.patch.object(handlers_admin, "_reparse_stale_genomes", return_value=None), \
             mock.patch.object(handlers_admin, "_runtime_git_repo", return_value=handlers_admin.Path("/tmp/genomi-repo")), \
             mock.patch.object(handlers_admin, "_git", side_effect=_git_pull_sequence(before="aaa", after="aaa")), \
             mock.patch.object(handlers_admin.subprocess, "run", side_effect=AssertionError("no installer must run")):
            result = call_operation(
                "genomi.install", {}
            )

        runtime_update = result["runtime_update"]
        self.assertFalse(runtime_update["changed"])
        self.assertNotIn("dependency_sync", runtime_update)

    def test_no_usable_installer_is_non_fatal_action_required(self) -> None:
        # PEP 668 base interpreter with no pip and no uv: the update must not
        # abort; it reports action_required with a tool-neutral hint.
        from genomi.operations.registry import handlers_admin

        def _fake_run(command, **kwargs):
            return _completed(returncode=1, stderr="No module named pip")

        with mock.patch.object(handlers_admin, "_reparse_stale_genomes", return_value=None), \
             mock.patch.object(handlers_admin, "_runtime_git_repo", return_value=handlers_admin.Path("/tmp/genomi-repo")), \
             mock.patch.object(handlers_admin, "_git", side_effect=_git_pull_sequence(before="aaa", after="bbb")), \
             mock.patch.object(handlers_admin.shutil, "which", return_value=None), \
             mock.patch.object(handlers_admin.subprocess, "run", side_effect=_fake_run):
            result = call_operation(
                "genomi.install", {}
            )

        self.assertEqual(result["status"], "completed")  # update did not abort
        sync = result["runtime_update"]["dependency_sync"]
        self.assertEqual(sync["status"], "action_required")
        self.assertIn("pip install -e", sync["hint"])


def _load_install_lib():
    """Load scripts/_install_for_agents_lib.py by path (it isn't an importable package)."""
    import importlib.util
    from pathlib import Path

    import genomi

    repo_root = Path(genomi.__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "_install_for_agents_lib.py"
    spec = importlib.util.spec_from_file_location("_genomi_install_lib_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GenomiShimTests(GenomiRuntimeTestCase):
    def test_shim_does_not_dereference_venv_interpreter_symlink(self) -> None:
        # Regression: a uv/venv python is a symlink to the base interpreter.
        # The shim must point at the venv interpreter as-is; resolving the
        # symlink escapes the venv to a Python without the editable genomi
        # install ("No module named genomi").
        import os

        install_lib = _load_install_lib()

        venv_bin = self.genomi_home / "venv" / "bin"
        venv_bin.mkdir(parents=True, exist_ok=True)
        base_python = self.genomi_home / "base" / "python3"
        base_python.parent.mkdir(parents=True, exist_ok=True)
        base_python.write_text("#!/bin/sh\n", encoding="utf-8")
        venv_python = venv_bin / "python"
        os.symlink(base_python, venv_python)  # venv python -> base interpreter

        with mock.patch.object(install_lib.sys, "executable", str(venv_python)):
            shim = install_lib.install_genomi_command_shim()

        content = shim.read_text(encoding="utf-8")
        self.assertIn(str(venv_python), content)         # venv interpreter kept
        self.assertNotIn(str(base_python), content)      # symlink not followed
