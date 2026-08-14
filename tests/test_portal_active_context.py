from __future__ import annotations

from genomi.interfaces import portal_active_context

from tests.support.runtime.genomi import GenomiRuntimeTestCase


class PortalActiveContextTests(GenomiRuntimeTestCase):
    def test_active_context_is_prompt_safe_non_authoritative_orientation(self) -> None:
        context = portal_active_context.update_project_active_context(
            "proj_active",
            {
                "route": "/projects/proj_active/artifacts/art_1?path=/Users/matthewzmd/private.json",
                "workspaceSection": "artifact-workspace",
                "panel": "Artifacts",
                "frameId": "frame_1",
                "artifactId": "art_1",
                "artifactVersionId": "ver_1",
                "artifactTabId": "evidence",
                "artifactTitle": "CYP2C19 report",
            },
        )

        stored = portal_active_context.active_context_for_project("proj_active")
        prompt = portal_active_context.active_context_prompt_section(stored)

        self.assertEqual(context["workspace_section"], "artifact-workspace")
        self.assertEqual(stored["artifact_title"], "CYP2C19 report")
        self.assertIn("# Current visible portal view", prompt)
        self.assertIn("non-authoritative orientation only", prompt)
        self.assertIn("- Panel: Artifacts", prompt)
        self.assertIn("- Visible artifact: CYP2C19 report", prompt)
        self.assertIn("- Visible artifact tab: Evidence report", prompt)
        self.assertNotIn("art_1", prompt)
        self.assertNotIn("ver_1", prompt)
        self.assertNotIn("frame_1", prompt)
        self.assertNotIn("/projects/", prompt)
        self.assertNotIn("/Users", prompt)
        self.assertNotIn("updated_at_epoch", stored)

    def test_missing_or_cleared_context_returns_none(self) -> None:
        portal_active_context.update_project_active_context("proj_clear", {"panel": "Evidence map"})
        portal_active_context.clear_project_active_context("proj_clear")

        self.assertIsNone(portal_active_context.active_context_for_project("proj_clear"))
        self.assertEqual(portal_active_context.active_context_prompt_section(None), "")
