from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from genomi.lab.setup import DEMO_USER_ID, run_lab_setup
from genomi.lab.store import GenomiLabStore, default_store_path


class GenomiLabSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.temporary = Path(self._temporary.name)
        self.data_root = self.temporary / "genomi"
        self.skill_parent = self.temporary / "host-skills"
        self.skill_parent.mkdir()

    def _run(self, **options: object) -> dict[str, object]:
        return run_lab_setup(
            root=self.data_root,
            host_skill_parents=[self.skill_parent],
            **options,
        )

    def test_check_is_read_only_when_setup_has_not_run(self) -> None:
        before = sorted(
            path.relative_to(self.temporary) for path in self.temporary.rglob("*")
        )
        result = self._run(check=True)
        after = sorted(
            path.relative_to(self.temporary) for path in self.temporary.rglob("*")
        )

        self.assertEqual(result["mode"], "check")
        self.assertTrue(result["read_only"])
        self.assertEqual(result["status"], "needs_setup")
        self.assertEqual(after, before)

    def test_setup_reconciles_normal_skill_and_creates_private_local_store(
        self,
    ) -> None:
        result = self._run()

        self.assertEqual(result["status"], "completed")
        skill_link = self.skill_parent / "genomi-genomilab"
        self.assertTrue(skill_link.is_symlink())
        database = default_store_path(self.data_root)
        key_files = list((database.parent / ".keys").glob("*.key"))
        self.assertTrue(database.is_file())
        self.assertEqual(len(key_files), 1)
        self.assertEqual(stat.S_IMODE(database.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(key_files[0].stat().st_mode), 0o600)

    def test_demo_is_idempotent_and_records_three_ctla4_cycles(self) -> None:
        first = self._run(demo=True)
        second = self._run(demo=True)

        first_demo = first["demo"]
        second_demo = second["demo"]
        self.assertEqual(first_demo["cycle_ids"], second_demo["cycle_ids"])
        self.assertEqual(first_demo["fixture"], "ctla4")
        self.assertTrue(first_demo["synthetic"])
        self.assertEqual(first_demo["clinical_use"], "prohibited")
        self.assertEqual(len(first_demo["cycle_ids"]), 3)
        self.assertEqual(len(first_demo["profile_snapshot_ids"]), 4)
        self.assertEqual(
            first_demo["agi_fixture"]["classification"],
            "variant of uncertain significance",
        )
        self.assertFalse(first_demo["live_agents_started"])
        self.assertFalse(first_demo["external_providers_contacted"])

        store = GenomiLabStore(default_store_path(self.data_root))
        board = store.list_investigation_board(
            DEMO_USER_ID, str(first_demo["investigation_id"])
        )
        self.assertEqual(
            [cycle["status"] for cycle in board["cycles"]],
            ["completed", "completed", "completed"],
        )
        self.assertEqual(len(board["assignments"]), 11)
        self.assertEqual(len(board["findings"]), 11)
        self.assertEqual(len(board["research_artifacts"]), 3)
        self.assertEqual(len(board["patient_questions"]), 5)
        self.assertEqual(len(board["information_gaps"]), 3)
        self.assertTrue(board["brief"])
        current = {item["title"]: item for item in board["current_hypotheses"]}
        self.assertEqual(
            current["CTLA4-related immune dysregulation"]["status"],
            "strengthened",
        )
        self.assertEqual(
            current["Impaired CTLA4 function despite normal staining"]["status"],
            "strengthened",
        )
        self.assertEqual(
            current["Medication-related immune suppression"]["status"],
            "retained",
        )
        self.assertEqual(
            current["Primary antibody deficiency with another cause"]["status"],
            "retained",
        )
        self.assertEqual(current["Other immune or genetic causes"]["status"], "open")
        self.assertTrue(
            all(
                item["progress_source"] == "reported_by_main_agent"
                for item in board["assignments"]
            )
        )

    def test_setup_and_record_surfaces_do_not_disclose_local_key_material(self) -> None:
        result = self._run(demo="ctla4")
        store = GenomiLabStore(default_store_path(self.data_root))
        board = store.list_investigation_board(
            DEMO_USER_ID, str(result["demo"]["investigation_id"])
        )
        workspace = store.get_workspace(DEMO_USER_ID)
        key_file = next(
            (default_store_path(self.data_root).parent / ".keys").glob("*.key")
        )
        key_hex = key_file.read_bytes().hex()
        presented = json.dumps(
            {"setup": result, "workspace": workspace, "board": board},
            sort_keys=True,
        )

        self.assertEqual(
            result["components"]["storage"]["local_threat_model"], "private_posix_user"
        )
        self.assertNotIn("key_directory", result["components"]["storage"])
        self.assertNotIn(str(key_file), presented)
        self.assertNotIn(key_hex, presented)


if __name__ == "__main__":
    unittest.main()
