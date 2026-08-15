from __future__ import annotations

import json
import unittest
from unittest import mock

from genomi.interfaces import portal_genomes


class PortalGenomesTests(unittest.TestCase):
    def test_genome_inventory_payload_hides_paths_and_keeps_switch_identity(self) -> None:
        raw_inventory = {
            "status": "completed",
            "active": {"agi_id": "agi_active", "user_id": "user_alex", "selection_source": "default_user_auto_select"},
            "users": [
                {
                    "user_id": "user_alex",
                    "nickname": "Alex",
                    "default": True,
                    "active_agi_id": "agi_active",
                    "agi_ids": ["agi_active"],
                }
            ],
            "active_genome_indexes": [
                {
                    "agi_id": "agi_active",
                    "sample_slug": "alex-vcf",
                    "names": {"display": "Alex genome", "sample_slug": "alex-vcf"},
                    "source": {"format": "vcf", "kind": "local_path", "provider": "Genomi"},
                    "source_references": [{"kind": "local_path", "value": "/Users/matthewzmd/private/source.vcf"}],
                    "status": "parsed",
                    "genome_build": "GRCh38",
                    "digitized": True,
                    "active_genome_index_readiness": {"status": "completed", "complete": True, "variants_ready": True},
                    "users": [{"user_id": "user_alex", "nickname": "Alex", "default": True, "active": True}],
                }
            ],
        }

        with mock.patch("genomi.interfaces.portal_genomes.call_operation", return_value=raw_inventory) as call:
            payload = portal_genomes.genome_inventory_payload()

        self.assertEqual(call.call_args.args, ("active_genome_index.list", {}))
        self.assertEqual(payload["summary"], {"genome_count": 1, "profile_count": 1})
        self.assertEqual(payload["genomes"][0]["display_name"], "Alex genome")
        self.assertEqual(payload["genomes"][0]["source"]["format"], "vcf")
        self.assertTrue(payload["genomes"][0]["active"])
        self.assertTrue(payload["users"][0]["active"])
        text = json.dumps(payload)
        self.assertNotIn("/Users", text)
        self.assertNotIn("source_references", text)

    def test_select_active_genome_binds_only_the_requested_portal_project(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_call(operation: str, params: dict[str, object] | None = None) -> dict[str, object]:
            payload = params or {}
            calls.append((operation, payload))
            if operation == "active_genome_index.list":
                return {
                    "status": "completed",
                    "active": {"agi_id": "agi_other", "user_id": "user_other"},
                    "users": [{"user_id": "user_alex", "nickname": "Alex", "active_agi_id": "agi_alex", "agi_ids": ["agi_alex"]}],
                    "active_genome_indexes": [{"agi_id": "agi_alex", "users": [{"user_id": "user_alex", "nickname": "Alex"}]}],
                }
            raise AssertionError(operation)

        with (
            mock.patch("genomi.interfaces.portal_genomes.call_operation", side_effect=fake_call),
            mock.patch("genomi.interfaces.portal_genomes.portal_store.get_project", return_value={"project_id": "proj_alex"}),
            mock.patch("genomi.interfaces.portal_genomes.portal_store.bind_project_genome", return_value={"agi_id": "agi_alex"}) as bind,
            mock.patch("genomi.interfaces.portal_genomes.portal_store.project_genome_binding", return_value={"agi_id": "agi_alex"}),
            mock.patch("genomi.interfaces.portal_genomes.portal_project_genomes.ensure_project_context") as ensure_context,
        ):
            payload = portal_genomes.select_active_genome(
                {"userId": "user_alex", "agiId": "agi_alex"},
                project_id="proj_alex",
            )

        self.assertTrue(calls)
        self.assertEqual({operation for operation, _params in calls}, {"active_genome_index.list"})
        bind.assert_called_once_with(
            "proj_alex",
            agi_id="agi_alex",
            user_id="user_alex",
        )
        ensure_context.assert_called_once_with("proj_alex")
        self.assertEqual(payload["selection"]["active_agi_id"], "agi_alex")
        self.assertTrue(payload["selection"]["access"]["approved"])
        self.assertEqual(payload["selection"]["access"]["scope"], "portal_project")

    def test_project_inventory_ignores_the_global_active_genome(self) -> None:
        raw_inventory = {
            "status": "completed",
            "active": {"agi_id": "agi_global", "user_id": "user_global"},
            "users": [
                {"user_id": "user_global", "nickname": "Global", "active_agi_id": "agi_global", "agi_ids": ["agi_global"]},
                {"user_id": "user_project", "nickname": "Project", "active_agi_id": "agi_project", "agi_ids": ["agi_project"]},
            ],
            "active_genome_indexes": [
                {"agi_id": "agi_global", "names": {"display": "Global genome"}, "users": [{"user_id": "user_global", "nickname": "Global", "active": True}]},
                {"agi_id": "agi_project", "names": {"display": "Project genome"}, "users": [{"user_id": "user_project", "nickname": "Project", "active": False}]},
            ],
        }

        with (
            mock.patch("genomi.interfaces.portal_genomes.call_operation", return_value=raw_inventory),
            mock.patch("genomi.interfaces.portal_genomes.portal_store.project_genome_binding", return_value={"agi_id": "agi_project"}),
        ):
            payload = portal_genomes.genome_inventory_payload("proj_1")

        self.assertEqual(payload["active"], {"agi_id": "agi_project", "user_id": "user_project", "selection_source": "portal_project"})
        by_id = {item["agi_id"]: item for item in payload["genomes"]}
        self.assertFalse(by_id["agi_global"]["active"])
        self.assertTrue(by_id["agi_project"]["active"])
        self.assertTrue(by_id["agi_project"]["users"][0]["active"])

    def test_select_active_genome_rejects_a_user_who_does_not_own_it(self) -> None:
        inventory = {
            "status": "completed",
            "users": [
                {"user_id": "user-a", "nickname": "A", "agi_ids": ["agi-a"]},
                {"user_id": "user-b", "nickname": "B", "agi_ids": ["agi-b"]},
            ],
            "active_genome_indexes": [
                {"agi_id": "agi-a", "users": [{"user_id": "user-a"}]},
                {"agi_id": "agi-b", "users": [{"user_id": "user-b"}]},
            ],
        }
        with (
            mock.patch(
                "genomi.interfaces.portal_genomes.call_operation",
                return_value=inventory,
            ),
            mock.patch(
                "genomi.interfaces.portal_genomes.portal_store.get_project",
                return_value={"project_id": "proj-a"},
            ),
            mock.patch(
                "genomi.interfaces.portal_genomes.portal_store.bind_project_genome"
            ) as bind,
            self.assertRaisesRegex(
                portal_genomes.OperationError,
                "does not own the selected Active Genome Index",
            ),
        ):
            portal_genomes.select_active_genome(
                {"agiId": "agi-a", "userId": "user-b"},
                project_id="proj-a",
            )

        bind.assert_not_called()


if __name__ == "__main__":
    unittest.main()
