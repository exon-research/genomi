from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.runtime import host_skills


def _make_source(root: Path, capabilities: list[str]) -> Path:
    """Build a fake Genomi checkout: an umbrella SKILL.md plus capability dirs.

    Also seeds a ``conventions`` dir (excluded by name) and a ``no-skill`` dir
    (excluded for lacking SKILL.md) so the source-selection rules are exercised.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text("# genomi umbrella\n", encoding="utf-8")
    skills = root / "skills"
    skills.mkdir()
    for name in capabilities:
        cap = skills / name
        cap.mkdir()
        (cap / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    # Excluded: in the skip set even though it has a SKILL.md.
    conventions = skills / "conventions"
    conventions.mkdir()
    (conventions / "SKILL.md").write_text("# conventions\n", encoding="utf-8")
    # Excluded: a directory without a SKILL.md.
    (skills / "no-skill").mkdir()
    return root


class ReconcileHostSkillLinksTests(unittest.TestCase):
    def test_creates_umbrella_and_capability_links_and_excludes_non_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _make_source(tmp_path / "checkout", ["decode", "clinvar"])
            host = tmp_path / "host" / "skills"

            result = host_skills.reconcile_host_skill_links(source, parents=[host])

            self.assertEqual(result["status"], "completed")
            self.assertTrue((host / "genomi").is_symlink())
            self.assertEqual((host / "genomi").resolve(), source.resolve())
            self.assertEqual((host / "genomi-decode").resolve(), (source / "skills" / "decode").resolve())
            self.assertEqual((host / "genomi-clinvar").resolve(), (source / "skills" / "clinvar").resolve())
            # Excluded sources do not get links.
            self.assertFalse((host / "genomi-conventions").exists())
            self.assertFalse((host / "genomi-no-skill").exists())
            # 1 umbrella + 2 capabilities created, nothing repaired.
            self.assertEqual(result["summary"]["created"], 3)
            self.assertEqual(result["summary"]["repaired"], 0)
            self.assertEqual(result["summary"]["removed_orphaned"], 0)

    def test_idempotent_second_run_leaves_everything_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _make_source(tmp_path / "checkout", ["decode"])
            host = tmp_path / "host" / "skills"

            host_skills.reconcile_host_skill_links(source, parents=[host])
            second = host_skills.reconcile_host_skill_links(source, parents=[host])

            self.assertEqual(second["summary"]["created"], 0)
            self.assertEqual(second["summary"]["repaired"], 0)
            self.assertEqual(second["summary"]["ok"], 2)  # umbrella + decode

    def test_repairs_dangling_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _make_source(tmp_path / "checkout", ["decode"])
            host = tmp_path / "host" / "skills"
            host.mkdir(parents=True)
            # Pre-create the exact failure this change fixes: a link into a
            # checkout path that no longer exists.
            stale_target = tmp_path / "old" / "checkout"
            (host / "genomi").symlink_to(stale_target, target_is_directory=True)
            self.assertTrue((host / "genomi").is_symlink())
            self.assertFalse((host / "genomi").exists())  # dangling

            result = host_skills.reconcile_host_skill_links(source, parents=[host])

            self.assertEqual((host / "genomi").resolve(), source.resolve())
            self.assertTrue((host / "genomi").exists())
            self.assertEqual(result["summary"]["repaired"], 1)
            repaired = result["host_dirs"][0]["repaired"][0]
            self.assertEqual(repaired["name"], "genomi")
            self.assertEqual(repaired["previous_target"], str(stale_target))

    def test_repairs_stale_link_pointing_at_wrong_existing_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _make_source(tmp_path / "checkout", ["decode"])
            host = tmp_path / "host" / "skills"
            host.mkdir(parents=True)
            wrong = tmp_path / "elsewhere"
            wrong.mkdir()
            (host / "genomi-decode").symlink_to(wrong, target_is_directory=True)

            result = host_skills.reconcile_host_skill_links(source, parents=[host])

            self.assertEqual(
                (host / "genomi-decode").resolve(), (source / "skills" / "decode").resolve()
            )
            self.assertEqual(result["summary"]["repaired"], 1)

    def test_non_symlink_conflict_is_skipped_without_force_and_replaced_with_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _make_source(tmp_path / "checkout", ["decode"])
            host = tmp_path / "host" / "skills"
            host.mkdir(parents=True)
            # A real directory squatting on the umbrella link name.
            (host / "genomi").mkdir()

            without_force = host_skills.reconcile_host_skill_links(source, parents=[host])
            self.assertFalse((host / "genomi").is_symlink())
            self.assertEqual(without_force["summary"]["skipped_conflict"], 1)
            self.assertEqual(without_force["host_dirs"][0]["skipped_conflict"], ["genomi"])

            with_force = host_skills.reconcile_host_skill_links(source, parents=[host], force=True)
            self.assertTrue((host / "genomi").is_symlink())
            self.assertEqual((host / "genomi").resolve(), source.resolve())
            self.assertEqual(with_force["summary"]["skipped_conflict"], 0)

    def test_removes_orphaned_genomi_capability_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _make_source(tmp_path / "checkout", ["decode"])
            host = tmp_path / "host" / "skills"
            host.mkdir(parents=True)
            old_target = tmp_path / "old-checkout" / "skills" / "removed"
            (host / "genomi-removed").symlink_to(old_target, target_is_directory=True)
            unrelated_target = tmp_path / "custom"
            unrelated_target.mkdir()
            (host / "custom-skill").symlink_to(unrelated_target, target_is_directory=True)
            (host / "genomi-not-a-link").mkdir()

            result = host_skills.reconcile_host_skill_links(source, parents=[host])

            self.assertFalse((host / "genomi-removed").is_symlink())
            self.assertTrue((host / "custom-skill").is_symlink())
            self.assertTrue((host / "genomi-not-a-link").is_dir())
            self.assertEqual(result["summary"]["removed_orphaned"], 1)
            removed = result["host_dirs"][0]["removed_orphaned"][0]
            self.assertEqual(removed["name"], "genomi-removed")
            self.assertEqual(removed["previous_target"], str(old_target))

    def test_source_without_skill_md_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bogus = tmp_path / "not-a-checkout"
            bogus.mkdir()
            host = tmp_path / "host" / "skills"

            result = host_skills.reconcile_host_skill_links(bogus, parents=[host])

            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "source_skill_not_found")
            self.assertFalse(host.exists())

    def test_only_existing_default_parents_are_targeted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _make_source(tmp_path / "checkout", ["decode"])
            existing = tmp_path / "present" / "skills"
            existing.mkdir(parents=True)
            missing = tmp_path / "absent" / "skills"

            with mock.patch.object(
                host_skills,
                "DEFAULT_HOST_SKILL_PARENTS",
                (existing, missing),
            ):
                result = host_skills.reconcile_host_skill_links(source)  # parents=None

            self.assertEqual(result["summary"]["host_dir_count"], 1)
            self.assertTrue((existing / "genomi").is_symlink())
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
