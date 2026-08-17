from __future__ import annotations

import ast
import fnmatch
import importlib
import re
import unittest
from pathlib import Path

from genomi.operations.catalog import CATALOG_FRAGMENT_FILENAME, CATALOG_FRAGMENT_PACKAGES
from genomi.runtime.handoff import SKILL_PATH, STAGE_CONTRACTS

REPO_ROOT = Path(__file__).resolve().parents[1]


def _package_data() -> dict[str, list[str]]:
    package_data: dict[str, list[str]] = {}
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
        match = re.match(
            r'^"(?P<package>[^"]+)"\s*=\s*(?P<patterns>\[.*\])$',
            stripped,
        )
        if match:
            patterns = ast.literal_eval(match.group("patterns"))
            if isinstance(patterns, list) and all(
                isinstance(item, str) for item in patterns
            ):
                package_data[match.group("package")] = patterns
    return package_data


def _package_data_packages() -> list[str]:
    return list(_package_data())


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

    def test_every_tool_catalog_fragment_is_in_package_data(self) -> None:
        package_data = _package_data()

        for package in CATALOG_FRAGMENT_PACKAGES:
            with self.subTest(package=package):
                patterns = package_data.get(package, [])
                self.assertTrue(
                    any(fnmatch.fnmatch(CATALOG_FRAGMENT_FILENAME, pattern) for pattern in patterns),
                    f"{package}:{CATALOG_FRAGMENT_FILENAME} is loaded at runtime but omitted from package data",
                )

    def test_handoff_stage_contracts_reference_current_root_skill_sections(self) -> None:
        anchors = _skill_heading_anchors()
        for stage_id, contract in STAGE_CONTRACTS.items():
            with self.subTest(stage_id=stage_id):
                self.assertIn(contract["anchor"], anchors)
                self.assertEqual(contract["section"], anchors[contract["anchor"]])


if __name__ == "__main__":
    unittest.main()
