from __future__ import annotations

import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest import mock

from genomi.runtime import skill_assets


class _PackagedDistribution:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.files = [PurePosixPath("../../../share/genomi/SKILL.md")]

    def locate_file(self, _entry: PurePosixPath) -> Path:
        return self.root / "SKILL.md"


class SkillAssetTests(unittest.TestCase):
    def test_source_checkout_exposes_root_and_focused_genomilab_skills(self) -> None:
        root = skill_assets.source_checkout_skill_root()

        self.assertIsNotNone(root)
        assert root is not None
        self.assertTrue((root / "SKILL.md").is_file())
        focused = skill_assets.skill_document_path(
            "skills/genomilab/SKILL.md",
            preferred_root=root,
        )
        self.assertIsNotNone(focused)
        assert focused is not None
        self.assertIn("# GenomiLab Research Desk", focused.read_text(encoding="utf-8"))

    def test_packaged_distribution_resolves_the_installed_skill_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "share" / "genomi"
            focused = root / "skills" / "genomilab"
            focused.mkdir(parents=True)
            (root / "SKILL.md").write_text("# Genomi\n", encoding="utf-8")
            (focused / "SKILL.md").write_text(
                "# GenomiLab Research Desk\n",
                encoding="utf-8",
            )
            distribution = _PackagedDistribution(root)

            with mock.patch.object(
                skill_assets.importlib_metadata,
                "distribution",
                return_value=distribution,
            ):
                resolved = skill_assets.packaged_skill_root()

            self.assertEqual(resolved, root.resolve())
            self.assertEqual(
                skill_assets.skill_document_path(
                    "skills/genomilab/SKILL.md",
                    preferred_root=resolved,
                ),
                (focused / "SKILL.md").resolve(),
            )

    def test_pip_target_layout_resolves_share_tree_without_metadata_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "installed"
            module_path = target / "genomi" / "runtime" / "skill_assets.py"
            focused = target / "share" / "genomi" / "skills" / "genomilab"
            focused.mkdir(parents=True)
            (focused.parents[1] / "SKILL.md").write_text(
                "# Genomi\n",
                encoding="utf-8",
            )
            (focused / "SKILL.md").write_text(
                "# GenomiLab Research Desk\n",
                encoding="utf-8",
            )
            distribution = _PackagedDistribution(target)
            distribution.files = []

            with mock.patch.object(skill_assets, "__file__", str(module_path)), \
                 mock.patch.object(
                     skill_assets.importlib_metadata,
                     "distribution",
                     return_value=distribution,
                 ), \
                 mock.patch.object(
                     skill_assets.sysconfig,
                     "get_path",
                     return_value=str(Path(tmp) / "wrong-prefix"),
                 ):
                resolved = skill_assets.packaged_skill_root()

            self.assertEqual(resolved, (target / "share" / "genomi").resolve())

    def test_skill_document_resolution_rejects_path_traversal(self) -> None:
        self.assertIsNone(skill_assets.skill_document_path("../SKILL.md"))


if __name__ == "__main__":
    unittest.main()
