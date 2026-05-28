"""Parity test: every operation in a tool_catalog.json fragment must have a
matching `### <op_name>` subsection in the skill markdown that the op's
`skill` field points at.

This is a permanent drift guard. It catches:
- tool_catalog ops missing from skill markdown
- skill markdown subsections whose op has been deleted from the catalog
- typos in op_name between the two sources

The test does NOT validate the prose content — it only validates structural
parity (presence of headings). Prose quality is a human-review concern.
"""
from __future__ import annotations

import json
import unittest
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR_PREFIX = "skills/"


def _collect_ops_by_skill() -> dict[str, set[str]]:
    """Group every op_name by the skill doc it declares in `skill` field."""
    by_skill: dict[str, set[str]] = defaultdict(set)
    for catalog_path in sorted(REPO_ROOT.glob("src/genomi/**/tool_catalog.json")):
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        for op_name, op in (catalog.get("operations") or {}).items():
            skill = (op or {}).get("skill", "")
            if not isinstance(skill, str) or not skill.startswith(SKILL_DIR_PREFIX):
                continue
            by_skill[skill].add(op_name)
    return by_skill


def _skill_subsection_op_names(skill_path: Path) -> set[str]:
    """Return all `### <op_name>` subsection headings in a skill markdown file."""
    headings: set[str] = set()
    if not skill_path.exists():
        return headings
    for line in skill_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            heading = line[4:].strip()
            # Op names look like `namespace.action`; ignore narrative headings
            # that happen to start with `### ` but have no dot.
            if "." in heading:
                headings.add(heading)
    return headings


class SkillToolSectionParityTests(unittest.TestCase):
    """For each capability, the skill doc must have a `### <op_name>` per op."""

    def test_every_catalog_op_has_a_skill_doc_subsection(self) -> None:
        by_skill = _collect_ops_by_skill()
        self.assertGreater(len(by_skill), 0, "no skill-doc-targeted ops found")
        problems: list[str] = []
        for skill_rel, expected_ops in sorted(by_skill.items()):
            skill_path = REPO_ROOT / skill_rel
            if not skill_path.exists():
                problems.append(f"missing skill doc: {skill_rel}")
                continue
            present = _skill_subsection_op_names(skill_path)
            missing = expected_ops - present
            if missing:
                problems.append(
                    f"{skill_rel} is missing `### <op>` subsection for: "
                    + ", ".join(sorted(missing))
                )
        self.assertEqual(problems, [], msg="\n  ".join(["skill/catalog drift:", *problems]))

    def test_no_orphan_op_subsections_in_skill_docs(self) -> None:
        """A skill doc must not carry `### <op_name>` for an op that no
        tool_catalog.json declares — those are stale rows from a deleted op.
        """
        all_known_ops: set[str] = set()
        for catalog_path in sorted(REPO_ROOT.glob("src/genomi/**/tool_catalog.json")):
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            all_known_ops.update((catalog.get("operations") or {}).keys())

        problems: list[str] = []
        for skill_path in sorted(REPO_ROOT.glob("skills/**/SKILL.md")):
            for heading in _skill_subsection_op_names(skill_path):
                if heading not in all_known_ops:
                    problems.append(
                        f"{skill_path.relative_to(REPO_ROOT)} has orphan "
                        f"`### {heading}` — no tool_catalog.json declares it"
                    )
        self.assertEqual(problems, [], msg="\n  ".join(["orphan op subsections:", *problems]))


if __name__ == "__main__":
    unittest.main()
