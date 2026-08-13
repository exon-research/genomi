from __future__ import annotations

import inspect
import json
import pickle
import stat
from pathlib import Path
from unittest import mock

from genomi.active_genome_index.active_genome_index import create_active_genome_index
from genomi.operations import all_operations, call_operation
from genomi.operations.registry.errors import OperationError
from genomi.operations.registry.execution import current_execution_context
from genomi.runtime import context as runtime_context
from genomi.lab import agi_authority as investigation_access

from tests.support.runtime.genomi import GenomiRuntimeTestCase


class GenomiLabAuthorizationTests(GenomiRuntimeTestCase):
    def setUp(self) -> None:
        super().setUp()
        investigation_access._reset_investigation_agi_authorization_epoch_for_testing()
        self.addCleanup(
            investigation_access._reset_investigation_agi_authorization_epoch_for_testing
        )
        self.vcf = self.genomi_home / "patient.vcf"
        self.vcf.parent.mkdir(parents=True, exist_ok=True)
        self.vcf.write_text(
            "##fileformat=VCFv4.2\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tPatient\n"
            "1\t100\trs900000001\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n"
            "1\t200\trs900000002\tC\tT\t.\tPASS\t.\tGT:DP:GQ\t1/1:28:80\n",
            encoding="utf-8",
        )
        self.agi_path = self.genomi_home / "patient.agi.sqlite"
        create_active_genome_index(
            self.vcf,
            self.agi_path,
            genome_build="GRCh38",
            reuse_existing=False,
        )
        call_operation(
            "active_genome_index.assign_user_genome",
            {
                "nickname": "Synthetic patient",
                "source": str(self.vcf),
                "agi_path": str(self.agi_path),
                "genome_build": "GRCh38",
            },
        )
        context = call_operation("genomi.describe_context")
        self.user_id = str(context["active_user_id"])
        self.agi_id = str(context["active_agi_id"])
        self.agi_snapshot_id = str(
            context["active_genome_index"]["agi_snapshot_id"]
        )

    def _issue(
        self,
        *,
        scope: dict[str, object] | None = None,
        workspace_session_id: str = "workspace-session-a",
    ) -> investigation_access.AgiAuthorizationHandle:
        return investigation_access.issue_investigation_agi_authorization(
            workspace_session_id=workspace_session_id,
            user_id=self.user_id,
            investigation_id="investigation-a",
            patient_molecular_snapshot_id="molecular-snapshot-a",
            consent_receipt_id="consent-a",
            agi_id=self.agi_id,
            agi_snapshot_id=self.agi_snapshot_id,
            purpose="Investigate the synthetic condition",
            genomic_scope=scope
            or {"operation": "variant.resolve", "rsid": "rs900000001"},
        )

    def _authorized(
        self,
        operation: str,
        params: dict[str, object],
        handle: object,
    ) -> dict[str, object]:
        try:
            execution_context = (
                investigation_access.execution_context_for_investigation_authorization(
                    handle,  # type: ignore[arg-type]
                    operation=operation,
                    params=params,
                )
            )
        except investigation_access.InvestigationAgiAuthorizationError as exc:
            raise OperationError(exc.code, str(exc)) from exc
        return call_operation(
            operation,
            params,
            execution_context=execution_context,
        )

    def test_exact_rsid_read_uses_authorized_reader_without_chat_grant(self) -> None:
        call_operation("active_genome_index.revoke_access", {})
        handle = self._issue()

        with mock.patch(
            "genomi.capabilities.variant.variant_lookup.context.open_reader",
            side_effect=AssertionError(
                "the exact investigation path must use the boundary reader"
            ),
        ):
            result = self._authorized(
                "variant.resolve",
                {"rsid": "rs900000001"},
                handle,
            )

        self.assertEqual(result["sample_context"]["count"], 1)
        self.assertEqual(
            result["sample_context"]["matches"][0]["genotype"], "0/1"
        )
        self.assertEqual(
            result["sample_context"]["searched_active_genome_indexes"][0][
                "selection"
            ],
            "investigation_authorization",
        )
        binding = result["authorization_binding"]
        self.assertEqual(binding["workspace_session_id"], "workspace-session-a")
        self.assertEqual(binding["user_id"], self.user_id)
        self.assertEqual(binding["investigation_id"], "investigation-a")
        self.assertEqual(
            binding["patient_molecular_snapshot_id"], "molecular-snapshot-a"
        )
        self.assertEqual(binding["consent_receipt_id"], "consent-a")
        self.assertEqual(binding["agi_id"], self.agi_id)
        self.assertEqual(binding["agi_snapshot_id"], self.agi_snapshot_id)
        self.assertEqual(binding["genomic_scope"]["rsid"], "rs900000001")
        serialized = json.dumps(binding)
        for forbidden in (
            "token",
            "epoch",
            "process_id",
            "agi_path",
            str(self.agi_path),
            str(self.vcf),
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertIsNone(
            current_execution_context()
        )
        ordinary = call_operation(
            "variant.resolve", {"rsid": "rs900000001"}
        )
        self.assertEqual(ordinary["sample_context"]["count"], 0)
        self.assertNotIn("authorization_binding", ordinary)

    def test_exact_allele_read_is_bound_to_all_four_allele_fields(self) -> None:
        handle = self._issue(
            scope={
                "operation": "variant.resolve",
                "chrom": "chr1",
                "pos": 100,
                "ref": "a",
                "alt": "g",
                "genome_build": "GRCh38",
            }
        )
        result = self._authorized(
            "variant.resolve",
            {
                "chrom": "1",
                "pos": 100,
                "ref": "A",
                "alt": "G",
                "genome_build": "GRCh38",
            },
            handle,
        )
        self.assertEqual(result["sample_context"]["count"], 1)
        self.assertEqual(
            result["authorization_binding"]["genomic_scope"],
            {
                "operation": "variant.resolve",
                "genome_build": "GRCh38",
                "include_fail": False,
                "limit": 20,
                "chrom": "1",
                "pos": 100,
                "ref": "A",
                "alt": "G",
            },
        )

        with self.assertRaises(OperationError) as raised:
            self._authorized(
                "variant.resolve",
                {"chrom": "1", "pos": 100, "ref": "A", "alt": "T"},
                handle,
            )
        self.assertEqual(
            raised.exception.code,
            "investigation_agi_authorization_scope_mismatch",
        )

    def test_scope_rejects_other_targets_operations_and_widening(self) -> None:
        handle = self._issue()
        cases = [
            (
                "variant.resolve",
                {"rsid": "rs900000002"},
            ),
            (
                "variant.resolve",
                {"query": "rs900000001"},
            ),
            (
                "variant.resolve",
                {"rsid": "rs900000001", "include_fail": True},
            ),
            (
                "variant.resolve",
                {
                    "rsid": "rs900000001",
                    "include_known_active_genome_indexes": True,
                },
            ),
            ("genomi.describe_context", {}),
        ]
        for operation, params in cases:
            with self.subTest(operation=operation, params=params):
                with self.assertRaises(OperationError) as raised:
                    self._authorized(operation, params, handle)
                self.assertEqual(
                    raised.exception.code,
                    "investigation_agi_authorization_scope_mismatch",
                )
                self.assertIsNone(
                    current_execution_context()
                )

    def test_chat_grant_cannot_replace_a_valid_exact_handle(self) -> None:
        call_operation(
            "active_genome_index.approve_access",
            {"approved_by_user": True, "agi_id": self.agi_id},
        )
        with self.assertRaises(OperationError) as raised:
            self._authorized(
                "variant.resolve",
                {"rsid": "rs900000001"},
                object(),
            )
        self.assertEqual(
            raised.exception.code, "invalid_investigation_agi_authorization"
        )

    def test_revocation_session_revocation_and_process_epoch_fail_closed(self) -> None:
        revoked = self._issue()
        self.assertTrue(
            investigation_access.revoke_investigation_agi_authorization(revoked)
        )
        self.assertFalse(
            investigation_access.revoke_investigation_agi_authorization(revoked)
        )
        with self.assertRaises(OperationError) as raised:
            self._authorized(
                "variant.resolve",
                {"rsid": "rs900000001"},
                revoked,
            )
        self.assertEqual(
            raised.exception.code, "investigation_agi_authorization_revoked"
        )

        session_handle = self._issue(workspace_session_id="close-me")
        other_handle = self._issue(workspace_session_id="keep-me")
        self.assertEqual(
            investigation_access.revoke_investigation_agi_authorizations_for_session(
                "close-me"
            ),
            1,
        )
        with self.assertRaises(OperationError) as raised:
            self._authorized(
                "variant.resolve",
                {"rsid": "rs900000001"},
                session_handle,
            )
        self.assertEqual(
            raised.exception.code, "investigation_agi_authorization_revoked"
        )
        self.assertEqual(
            self._authorized(
                "variant.resolve",
                {"rsid": "rs900000001"},
                other_handle,
            )["sample_context"]["count"],
            1,
        )

        stale = self._issue()
        investigation_access._reset_investigation_agi_authorization_epoch_for_testing()
        with self.assertRaises(OperationError) as raised:
            self._authorized(
                "variant.resolve",
                {"rsid": "rs900000001"},
                stale,
            )
        self.assertEqual(
            raised.exception.code,
            "investigation_agi_authorization_process_mismatch",
        )

    def test_investigation_refresh_revokes_prior_sessions_but_preserves_new_handle(
        self,
    ) -> None:
        prior_a = self._issue(workspace_session_id="workspace-session-a")
        prior_b = self._issue(workspace_session_id="workspace-session-b")
        replacement = self._issue(workspace_session_id="workspace-session-c")

        revoked = (
            investigation_access.revoke_investigation_agi_authorizations_for_investigation(
                user_id=self.user_id,
                investigation_id="investigation-a",
                except_handle=replacement,
            )
        )
        self.assertEqual(revoked, 2)
        for prior in (prior_a, prior_b):
            with self.assertRaises(OperationError) as raised:
                self._authorized(
                    "variant.resolve",
                    {"rsid": "rs900000001"},
                    prior,
                )
            self.assertEqual(
                raised.exception.code,
                "investigation_agi_authorization_revoked",
            )
        result = self._authorized(
            "variant.resolve",
            {"rsid": "rs900000001"},
            replacement,
        )
        self.assertEqual(
            result["authorization_binding"]["workspace_session_id"],
            "workspace-session-c",
        )

    def test_user_change_invalidates_handle_but_current_revision_change_does_not(self) -> None:
        handle = self._issue()
        call_operation(
            "active_genome_index.assign_user_genome",
            {
                "nickname": "Another user",
                "source": str(self.vcf),
                "agi_id": self.agi_id,
            },
        )
        with self.assertRaises(OperationError) as raised:
            self._authorized(
                "variant.resolve",
                {"rsid": "rs900000001"},
                handle,
            )
        self.assertEqual(
            raised.exception.code,
            "investigation_agi_authorization_context_mismatch",
        )

        call_operation(
            "active_genome_index.select_user", {"user_id": self.user_id}
        )
        handle = self._issue()
        registry = runtime_context.load_registry()
        registry["agis"][self.agi_id]["agi_snapshot_id"] = "agi-snapshot-replaced"
        runtime_context.save_registry(registry)
        result = self._authorized(
            "variant.resolve",
            {"rsid": "rs900000001"},
            handle,
        )
        self.assertEqual(result["sample_context"]["count"], 1)

        registry = runtime_context.load_registry()
        registry["agi_revisions"].pop(self.agi_snapshot_id)
        runtime_context.save_registry(registry)
        with self.assertRaises(OperationError) as raised:
            self._authorized(
                "variant.resolve",
                {"rsid": "rs900000001"},
                handle,
            )
        self.assertEqual(
            raised.exception.code,
            "investigation_agi_authorization_context_mismatch",
        )

    def test_same_logical_agi_rebuild_preserves_pinned_revision(self) -> None:
        issued_before_rebuild = self._issue()
        initial_registry = runtime_context.load_registry()
        initial_revision = initial_registry["agi_revisions"][
            self.agi_snapshot_id
        ]
        initial_revision_path = str(initial_revision["agi_path"])
        self.assertNotEqual(initial_revision_path, str(self.agi_path))
        self.assertTrue(Path(initial_revision_path).is_file())
        self.assertFalse(
            bool(Path(initial_revision_path).stat().st_mode & stat.S_IWUSR)
        )

        create_active_genome_index(
            self.vcf,
            self.agi_path,
            genome_build="GRCh38",
            reuse_existing=False,
        )
        call_operation(
            "active_genome_index.assign_user_genome",
            {
                "user_id": self.user_id,
                "source": str(self.vcf),
                "agi_path": str(self.agi_path),
                "genome_build": "GRCh38",
            },
        )

        rebuilt_context = call_operation("genomi.describe_context")
        rebuilt_snapshot_id = str(rebuilt_context["active_agi_snapshot_id"])
        self.assertNotEqual(rebuilt_snapshot_id, self.agi_snapshot_id)
        rebuilt_registry = runtime_context.load_registry()
        self.assertEqual(
            rebuilt_registry["agis"][self.agi_id]["agi_snapshot_id"],
            rebuilt_snapshot_id,
        )
        self.assertEqual(
            set(rebuilt_registry["agi_revisions"]),
            {self.agi_snapshot_id, rebuilt_snapshot_id},
        )
        self.assertEqual(
            rebuilt_registry["agi_revisions"][self.agi_snapshot_id]["agi_path"],
            initial_revision_path,
        )
        self.assertTrue(Path(initial_revision_path).is_file())

        for handle in (issued_before_rebuild, self._issue()):
            result = self._authorized(
                "variant.resolve",
                {"rsid": "rs900000001"},
                handle,
            )
            self.assertEqual(result["sample_context"]["count"], 1)
            self.assertEqual(
                result["authorization_binding"]["agi_snapshot_id"],
                self.agi_snapshot_id,
            )

        inventory = call_operation("active_genome_index.list")
        logical = next(
            item
            for item in inventory["active_genome_indexes"]
            if item["agi_id"] == self.agi_id
        )
        self.assertEqual(logical["revision_count"], 2)
        self.assertEqual(
            {item["agi_snapshot_id"] for item in logical["revisions"]},
            {self.agi_snapshot_id, rebuilt_snapshot_id},
        )
        self.assertEqual(
            [item["agi_snapshot_id"] for item in logical["revisions"] if item["current"]],
            [rebuilt_snapshot_id],
        )

    def test_revocation_during_read_blocks_result_disclosure_and_resets_context(self) -> None:
        handle = self._issue()

        def revoke_before_result(**_: object) -> dict[str, object]:
            investigation_access.revoke_investigation_agi_authorization(handle)
            return {"sample_context": {"count": 1}}

        with mock.patch(
            "genomi.operations.registry.handlers_vcf_variant.variant_lookup.lookup_variant",
            side_effect=revoke_before_result,
        ):
            with self.assertRaises(OperationError) as raised:
                self._authorized(
                    "variant.resolve",
                    {"rsid": "rs900000001"},
                    handle,
                )
        self.assertEqual(
            raised.exception.code, "investigation_agi_authorization_revoked"
        )
        self.assertIsNone(
            current_execution_context()
        )

    def test_handle_is_opaque_python_only_and_not_in_tool_catalog(self) -> None:
        handle = self._issue()
        self.assertEqual(repr(handle), "<AgiAuthorizationHandle opaque>")
        with self.assertRaises(TypeError):
            pickle.dumps(handle)
        with self.assertRaises(TypeError):
            investigation_access.AgiAuthorizationHandle(object())

        names = {definition["name"] for definition in all_operations()}
        self.assertNotIn("issue_investigation_agi_authorization", names)
        self.assertNotIn("revoke_investigation_agi_authorization", names)
        signature = inspect.signature(call_operation)
        self.assertNotIn("authorization", signature.parameters)
        self.assertEqual(
            signature.parameters["execution_context"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        variant_definition = next(
            definition
            for definition in all_operations()
            if definition["name"] == "variant.resolve"
        )
        self.assertNotIn(
            "execution_context", variant_definition["inputSchema"]["properties"]
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
