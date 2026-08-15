from __future__ import annotations

import json
from unittest import mock

from genomi.interfaces import portal_project_genomes, portal_store
from genomi.runtime.context import agi_access_status, active_agi_record
from genomi.runtime.context.storage import load_context

from tests.support.runtime.genomi import GenomiRuntimeTestCase


class PortalProjectGenomesTests(GenomiRuntimeTestCase):
    def test_project_context_contains_only_binding_and_project_grant(self) -> None:
        project = portal_store.create_project(name="Subject A")
        portal_store.bind_project_genome(
            project["project_id"],
            agi_id="agi_subject_a",
            user_id="user_subject_a",
        )

        path = portal_project_genomes.ensure_project_context(project["project_id"])
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["active_agi_id"], "agi_subject_a")
        self.assertEqual(payload["active_user_id"], "user_subject_a")
        self.assertFalse(payload["default_user_auto_selection"])
        self.assertEqual(payload["agi_access"]["agi_subject_a"]["scope"], "portal_project")
        self.assertEqual(payload["agis"], {})
        self.assertNotIn("agi_path", json.dumps(payload))
        self.assertNotIn("source", json.dumps(payload))

    def test_empty_project_context_blocks_default_user_auto_selection(self) -> None:
        project = portal_store.create_project(name="Public-only workspace")
        path = portal_project_genomes.ensure_project_context(project["project_id"])
        registry = {
            "default_user_id": "user_default",
            "users": {
                "user_default": {
                    "user_id": "user_default",
                    "default": True,
                    "active_agi_id": "agi_default",
                    "agi_ids": ["agi_default"],
                }
            },
            "agis": {"agi_default": {"agi_id": "agi_default"}},
        }

        with mock.patch.dict("os.environ", {"GENOMI_CONTEXT": str(path)}, clear=False):
            context = load_context()
        with (
            mock.patch("genomi.runtime.context.agi_selection.load_registry", return_value=registry),
            mock.patch("genomi.runtime.context.agi_access.load_registry", return_value=registry),
        ):
            self.assertIsNone(active_agi_record(context))
            self.assertFalse(agi_access_status("agi_default", context=context, registry=registry)["approved"])

    def test_projects_keep_independent_genome_bindings(self) -> None:
        first = portal_store.create_project(name="Subject A")
        second = portal_store.create_project(name="Subject B")

        portal_store.bind_project_genome(first["project_id"], agi_id="agi_a")
        portal_store.bind_project_genome(second["project_id"], agi_id="agi_b")

        first_context = json.loads(portal_project_genomes.ensure_project_context(first["project_id"]).read_text(encoding="utf-8"))
        second_context = json.loads(portal_project_genomes.ensure_project_context(second["project_id"]).read_text(encoding="utf-8"))

        self.assertEqual(first_context["active_agi_id"], "agi_a")
        self.assertEqual(second_context["active_agi_id"], "agi_b")
        self.assertEqual(set(first_context["agi_access"]), {"agi_a"})
        self.assertEqual(set(second_context["agi_access"]), {"agi_b"})
        self.assertNotIn("genome_binding", portal_store.get_project(first["project_id"]))


if __name__ == "__main__":
    import unittest

    unittest.main()
