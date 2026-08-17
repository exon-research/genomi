from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.runtime import background_jobs
from genomi.runtime import context as runtime_context
from genomi.runtime.private_storage import (
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    UnsafePrivateStoragePathError,
    atomic_write_private_text,
    ensure_private_directory,
)

from tests.support.runtime.genomi import GenomiRuntimeTestCase


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@unittest.skipUnless(os.name == "posix", "private POSIX modes require a POSIX filesystem")
class PrivateRuntimeStorageTests(GenomiRuntimeTestCase):
    def test_context_registry_and_owned_directories_are_private(self) -> None:
        registry = runtime_context.save_registry({"agis": {}, "users": {}})
        context = runtime_context.save_context({"active_agi_id": None, "agis": {}})

        self.assertIsInstance(registry, dict)
        self.assertIsInstance(context, dict)
        registry_file = runtime_context.registry_path()
        context_file = runtime_context.context_path()
        self.assertEqual(_mode(registry_file), PRIVATE_FILE_MODE)
        self.assertEqual(_mode(context_file), PRIVATE_FILE_MODE)

        current = context_file.parent
        while True:
            self.assertEqual(_mode(current), PRIVATE_DIRECTORY_MODE, current)
            if current == self.genomi_home:
                break
            current = current.parent

        # Re-saving hardens owned paths that predate the private-storage
        # contract instead of preserving their broader modes.
        self.genomi_home.chmod(0o755)
        registry_file.chmod(0o644)
        runtime_context.save_registry(registry)
        self.assertEqual(_mode(self.genomi_home), PRIVATE_DIRECTORY_MODE)
        self.assertEqual(_mode(registry_file), PRIVATE_FILE_MODE)

    def test_context_save_refuses_symlink_target(self) -> None:
        self.genomi_home.mkdir(mode=0o700, parents=True)
        victim = Path(self._home_tmp.name) / "victim.json"
        victim.write_text('{"untouched": true}\n', encoding="utf-8")
        target = runtime_context.context_path(self.genomi_home)
        target.symlink_to(victim)

        with self.assertRaises(UnsafePrivateStoragePathError):
            runtime_context.save_context({"active_agi_id": None, "agis": {}}, root=self.genomi_home)

        self.assertEqual(victim.read_text(encoding="utf-8"), '{"untouched": true}\n')
        self.assertTrue(target.is_symlink())

    def test_atomic_failure_preserves_previous_file_and_cleans_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "private"
            target = root / "state.json"
            atomic_write_private_text(target, "before\n", private_root=root)

            with (
                mock.patch("genomi.runtime.private_storage.os.replace", side_effect=OSError("replace failed")),
                self.assertRaisesRegex(OSError, "replace failed"),
            ):
                atomic_write_private_text(target, "after\n", private_root=root)

            self.assertEqual(target.read_text(encoding="utf-8"), "before\n")
            self.assertEqual(list(root.glob(f".{target.name}.*.tmp")), [])

    def test_background_job_and_log_are_private(self) -> None:
        job_root = background_jobs.jobs_dir()
        job_root.mkdir(mode=0o755, parents=True)
        existing_log = job_root / "private-job.log"
        existing_log.write_bytes(b"previous output\n")
        existing_log.chmod(0o644)

        process = mock.Mock(pid=43210)
        with (
            mock.patch.object(background_jobs, "_new_job_id", return_value="private-job"),
            mock.patch.object(background_jobs.subprocess, "Popen", return_value=process),
        ):
            job = background_jobs.start_operation_job("genomi.list_resources", {})

        job_file = Path(job["job_path"])
        log_file = Path(job["log_path"])
        self.assertEqual(_mode(self.genomi_home), PRIVATE_DIRECTORY_MODE)
        self.assertEqual(_mode(job_root), PRIVATE_DIRECTORY_MODE)
        self.assertEqual(_mode(job_file), PRIVATE_FILE_MODE)
        self.assertEqual(_mode(log_file), PRIVATE_FILE_MODE)
        self.assertEqual(job["status"], "running")

    def test_background_log_symlink_is_refused(self) -> None:
        job_root = background_jobs.jobs_dir()
        ensure_private_directory(job_root, private_root=self.genomi_home)
        victim = Path(self._home_tmp.name) / "victim.log"
        victim.write_bytes(b"untouched\n")
        (job_root / "linked-job.log").symlink_to(victim)

        with (
            mock.patch.object(background_jobs, "_new_job_id", return_value="linked-job"),
            mock.patch.object(background_jobs.subprocess, "Popen") as popen,
            self.assertRaises(UnsafePrivateStoragePathError),
        ):
            background_jobs.start_operation_job("genomi.list_resources", {})

        popen.assert_not_called()
        self.assertEqual(victim.read_bytes(), b"untouched\n")

    def test_background_job_directory_symlink_is_refused(self) -> None:
        self.genomi_home.mkdir(mode=0o700, parents=True)
        outside = Path(self._home_tmp.name) / "outside-jobs"
        outside.mkdir()
        background_jobs.jobs_dir().symlink_to(outside, target_is_directory=True)

        with self.assertRaises(UnsafePrivateStoragePathError):
            background_jobs.start_operation_job("genomi.list_resources", {})


if __name__ == "__main__":
    unittest.main()
