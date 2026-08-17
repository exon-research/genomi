from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class GenomiLabAgentGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.focused_guide = (
            REPO_ROOT / "skills" / "genomilab" / "SKILL.md"
        ).read_text(encoding="utf-8")

    def test_new_investigation_requires_a_host_native_specialist_board(self) -> None:
        for expected in (
            "For every new investigation, act as chair and form 2–5 native host subagents",
            "adaptive, non-overlapping domain roles",
            "Give each specialist an explicit\nrole and bounded task",
            "`genomilab.form_specialist_board` before submitting a plan",
        ):
            self.assertIn(expected, self.focused_guide)

    def test_chair_and_specialist_private_context_boundaries_are_explicit(self) -> None:
        for expected in (
            "The chair alone owns the patient conversation, authorization, all private AGI\nreads",
            "minimum approved evidence needed for their task",
            "Specialists return their analysis to the chair",
            "they never read the AGI\ndirectly, interact with the portal",
        ):
            self.assertIn(expected, self.focused_guide)

    def test_resume_and_monitoring_use_the_durable_board_contract(self) -> None:
        normalized_guide = " ".join(self.focused_guide.split())
        for expected in (
            "Treat its pre-authorization `specialist_board` as a structural redacted marker only: board existence plus `status` and `member_count`; a static chair description may also appear",
            "If that marker says a board exists, do not call `genomilab.form_specialist_board` again",
            "Renew current-session authorization",
            "After `private_context_status` is `approved_for_session`, inspect again; only then read and reuse the full specialist IDs, roles, tasks, and current-work states",
            "`genomilab.report_specialist_progress` with the current `round_id` only at meaningful work milestones",
            "`genomilab.record_specialist_report` to commit that round's findings and gaps",
            "The portal monitors only these committed board milestones",
        ):
            self.assertIn(expected, normalized_guide)

    def test_default_agent_surface_lists_board_operations(self) -> None:
        root_guide = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`genomilab.form_specialist_board`", root_guide)
        self.assertIn("`genomilab.report_specialist_progress`", root_guide)
        self.assertIn("`genomilab.record_specialist_report`", root_guide)

    def test_private_lab_session_reset_is_scoped_to_local_stdio_mcp(self) -> None:
        normalized_guide = " ".join(self.focused_guide.split())
        self.assertIn(
            "Each local stdio MCP `initialize` handshake is a new GenomiLab agent session",
            normalized_guide,
        )
        self.assertIn(
            "HTTP MCP initialization is public-tools-only and cannot create or replace the private GenomiLab runtime",
            normalized_guide,
        )

    def test_product_contract_requires_board_before_plan_acceptance(self) -> None:
        product = (REPO_ROOT / "GENOMILAB_PRODUCT_DEFINITION.md").read_text(
            encoding="utf-8"
        )
        for expected in (
            "**ARCH-013:** For each new investigation",
            "**INV-009:** A new investigation SHALL have exactly one board of 2–5 native",
            "before its canonical\n  plan is accepted",
            "**INV-010:** Specialists SHALL receive public questions or only the minimum",
        ):
            self.assertIn(expected, product)

    def test_generated_agent_context_includes_specialist_board_guidance(self) -> None:
        llms_full = (REPO_ROOT / "llms-full.txt").read_text(encoding="utf-8")
        normalized_llms_full = " ".join(llms_full.split())
        self.assertIn("## Inlined: `skills/genomilab/SKILL.md`", llms_full)
        self.assertIn("## Chair the specialist board", llms_full)
        self.assertIn("`genomilab.form_specialist_board`", llms_full)
        self.assertIn("`genomilab.report_specialist_progress`", llms_full)
        self.assertIn("`genomilab.record_specialist_report`", llms_full)
        self.assertIn(
            "Treat its pre-authorization `specialist_board` as a structural redacted marker only: board existence plus `status` and `member_count`",
            normalized_llms_full,
        )
        self.assertIn(
            "After `private_context_status` is `approved_for_session`, inspect again; only then read and reuse the full specialist IDs",
            normalized_llms_full,
        )


if __name__ == "__main__":
    unittest.main()
