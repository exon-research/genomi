from __future__ import annotations

import importlib
import re
import unittest
from pathlib import Path

from genomi.runtime.handoff import SKILL_PATH, STAGE_CONTRACTS

REPO_ROOT = Path(__file__).resolve().parents[1]


def _package_data_packages() -> list[str]:
    packages: list[str] = []
    in_package_data = False
    for line in (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "[tool.setuptools.package-data]":
            in_package_data = True
            continue
        if in_package_data and stripped.startswith("["):
            break
        if not in_package_data or not stripped or stripped.startswith("#"):
            continue
        match = re.match(r'^"(?P<package>[^"]+)"\s*=\s*\[', stripped)
        if match:
            packages.append(match.group("package"))
    return packages


def _skill_heading_anchors() -> dict[str, str]:
    anchors: dict[str, str] = {}
    for line in (REPO_ROOT / SKILL_PATH).read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#+\s+(?P<title>.+?)\s*$", line)
        if not match:
            continue
        title = match.group("title")
        slug = re.sub(r"[^\w\s-]", "", title.lower())
        slug = re.sub(r"\s+", "-", slug.strip())
        anchors[f"#{slug}"] = title
    return anchors


class RuntimeContractTests(unittest.TestCase):
    def test_package_data_entries_reference_importable_packages(self) -> None:
        for package in _package_data_packages():
            with self.subTest(package=package):
                importlib.import_module(package)

    def test_handoff_stage_contracts_reference_current_root_skill_sections(self) -> None:
        anchors = _skill_heading_anchors()
        for stage_id, contract in STAGE_CONTRACTS.items():
            with self.subTest(stage_id=stage_id):
                self.assertIn(contract["anchor"], anchors)
                self.assertEqual(contract["section"], anchors[contract["anchor"]])


if __name__ == "__main__":
    unittest.main()
