"""End-to-end contract test: Genomi emits one valid envelope contract.

This file does NOT exercise each operation with real data — that would require
fixtures spanning every public source. Instead, it stubs each handler with a
minimal representative result and asserts:

  1. call_operation auto-attaches an `evidence_envelope` if the handler does
     not emit one, for every op in EVIDENCE_PRODUCING_OPERATIONS.
  2. The attached envelope passes envelope.validate.
  3. Handlers that DO emit an envelope (risk, variant, pgx, etc.) are not
     stripped or overwritten — the explicit envelope is preserved.
  4. Non-evidence ops (e.g. genomi.list_resources) are passed through
     unchanged with no envelope auto-attached.
  5. Every registered operation gets the same envelope guidance for failure-like
     results, so tools do not invent one-off prose or policy fields.
"""

from __future__ import annotations

import unittest
from typing import Any

from genomi import operations as ops
from genomi.evidence import envelope as env

from tests.support.runtime.genomi import GenomiRuntimeTestCase


class DispatchEnvelopeContractTests(GenomiRuntimeTestCase):
    def _call_with_stub(self, name: str, stub_result: dict[str, Any]) -> dict[str, Any]:
        """Replace the registered handler with a stub, dispatch, restore."""
        operation = ops.get_operation(name)
        new = ops.Operation(
            name=operation.name,
            description=operation.description,
            input_schema=operation.input_schema,
            handler=lambda _params, _stub=stub_result: dict(_stub),
            skill=operation.skill,
            area=operation.area,
            requires=operation.requires,
            produces=operation.produces,
            context_optional=operation.context_optional,
            privacy_scope=operation.privacy_scope,
            operation_scope=operation.operation_scope,
            mutating=operation.mutating,
            external_io=operation.external_io,
            data_access=operation.data_access,
            agi_need=operation.agi_need,
        )
        ops._OPERATION_BY_NAME[name] = new
        try:
            return ops.call_operation(name, {})
        finally:
            ops._OPERATION_BY_NAME[name] = operation

    def test_every_evidence_op_gets_envelope_with_positive_result(self) -> None:
        for name in sorted(ops.EVIDENCE_PRODUCING_OPERATIONS):
            with self.subTest(op=name):
                result = self._call_with_stub(
                    name,
                    {
                        "status": "completed",
                        "summary": {"record_count": 3},
                    },
                )
                envelope = result.get("evidence_envelope")
                self.assertIsInstance(envelope, dict, f"{name} did not receive an envelope")
                env.validate(envelope)
                self.assertEqual(envelope["operation"], name)
                # positive-count stub should yield evidence_present
                self.assertEqual(envelope["finding_state"], env.EVIDENCE_PRESENT)
                self.assertEqual(envelope["answer_readiness"], env.SCOPED_ANSWER_ONLY)

    def test_every_evidence_op_with_zero_count_yields_scoped_empty(self) -> None:
        for name in sorted(ops.EVIDENCE_PRODUCING_OPERATIONS):
            with self.subTest(op=name):
                result = self._call_with_stub(
                    name,
                    {"status": "no_matching_records", "summary": {"record_count": 0}},
                )
                envelope = result["evidence_envelope"]
                env.validate(envelope)
                self.assertEqual(envelope["finding_state"], env.NOT_OBSERVED_IN_CONSULTED_SCOPE)
                self.assertEqual(envelope["answer_readiness"], env.SCOPED_ANSWER_ONLY)
                self.assertFalse(envelope["negative_inference"]["allowed"])

    def test_source_unavailable_yields_not_assessed(self) -> None:
        for name in sorted(ops.EVIDENCE_PRODUCING_OPERATIONS):
            with self.subTest(op=name):
                result = self._call_with_stub(
                    name,
                    {"status": "source_unavailable"},
                )
                envelope = result["evidence_envelope"]
                env.validate(envelope)
                self.assertEqual(envelope["finding_state"], env.NOT_ASSESSED)
                self.assertEqual(envelope["answer_readiness"], env.CANNOT_ANSWER_YET)
                self.assertIn("source_unavailable:retry_or_use_alternate_source", envelope["guidance"])

    def test_every_operation_failure_like_result_gets_same_envelope_guidance(self) -> None:
        for name in sorted(ops._OPERATION_BY_NAME):
            with self.subTest(op=name):
                result = self._call_with_stub(
                    name,
                    {
                        "status": "invalid_params",
                        "message": "missing required input",
                        "summary": {},
                    },
                )
                envelope = result.get("evidence_envelope")
                self.assertIsInstance(envelope, dict, f"{name} did not receive failure guidance")
                env.validate(envelope)
                self.assertEqual(envelope["operation"], name)
                self.assertEqual(envelope["finding_state"], env.NOT_ASSESSED)
                self.assertEqual(envelope["answer_readiness"], env.CANNOT_ANSWER_YET)
                self.assertIn("invalid_input:fix_params_before_retry", envelope["guidance"])

    def test_existing_envelope_is_preserved(self) -> None:
        # Choose any evidence op; the dispatcher must not overwrite an
        # envelope a handler already produced.
        name = "phenotype.plan_risk_investigation"
        custom = env.evidence_present(
            operation=name,
            observations={"observation_count": 1},
        )
        result = self._call_with_stub(
            name,
            {"status": "completed", "evidence_envelope": custom, "summary": {"record_count": 0}},
        )
        self.assertEqual(result["evidence_envelope"], custom)

    def test_non_evidence_op_has_no_auto_envelope(self) -> None:
        # genomi.list_resources is metadata-only and not in the evidence allowlist.
        result = self._call_with_stub(
            "genomi.list_resources",
            {"status": "completed", "summary": {"record_count": 7}},
        )
        self.assertNotIn("evidence_envelope", result)

    def test_nested_evidence_counts_yield_evidence_present(self) -> None:
        # variant.gather_gene_context returns no top-level status or count; its
        # counts live nested inside per-source summaries. The classifier must
        # look one level down so partial-but-useful gene context is not stamped
        # not_assessed/cannot_answer_yet.
        result = self._call_with_stub(
            "variant.gather_gene_context",
            {
                "query": {"gene": "APOE", "genome_build": "GRCh37"},
                "clinvar_gene": {"total_records": 42, "compact_records": []},
                "sample_matches": {"total_records": 3, "records": []},
                "research_evidence": {"record_count": 0},
            },
        )
        envelope = result["evidence_envelope"]
        env.validate(envelope)
        self.assertEqual(envelope["finding_state"], env.EVIDENCE_PRESENT)
        self.assertEqual(envelope["answer_readiness"], env.SCOPED_ANSWER_ONLY)

    def test_data_returned_with_capability_specific_counts_yields_evidence_present(self) -> None:
        result = self._call_with_stub(
            "pathway.retrieve_members",
            {
                "status": "pathway_members_found",
                "coverage_state": "data_returned",
                "coverage": {"returned_member_count": 2},
                "members": [{"gene_symbol": "OTC"}, {"gene_symbol": "CPS1"}],
            },
        )
        envelope = result["evidence_envelope"]
        env.validate(envelope)
        self.assertEqual(envelope["finding_state"], env.EVIDENCE_PRESENT)
        self.assertEqual(envelope["answer_readiness"], env.SCOPED_ANSWER_ONLY)
        self.assertEqual(envelope["observations"]["coverage_state"], "data_returned")
        self.assertEqual(envelope["observations"]["returned_member_count"], 2)

    def test_metadata_only_found_status_does_not_assert_evidence(self) -> None:
        result = self._call_with_stub(
            "functional_genomics.query_geo",
            {
                "status": "geo_metadata_found",
                "coverage_state": "metadata_only",
                "summary": {"record_count": 0, "geo_hit_count": 1},
                "geo_hits": [{"accession": "GSE12345"}],
            },
        )
        envelope = result["evidence_envelope"]
        env.validate(envelope)
        self.assertEqual(envelope["finding_state"], env.NOT_ASSESSED)
        self.assertEqual(envelope["answer_readiness"], env.CANNOT_ANSWER_YET)
        self.assertEqual(envelope["observations"]["coverage_state"], "metadata_only")

    def test_nested_zero_counts_do_not_assert_evidence(self) -> None:
        # When every nested summary is empty, the op must not claim evidence.
        result = self._call_with_stub(
            "variant.gather_gene_context",
            {
                "query": {"gene": "APOE", "genome_build": "GRCh37"},
                "clinvar_gene": {"total_records": 0, "compact_records": []},
                "sample_matches": {"total_records": 0, "records": []},
                "research_evidence": {"record_count": 0},
            },
        )
        envelope = result["evidence_envelope"]
        env.validate(envelope)
        self.assertNotEqual(envelope["finding_state"], env.EVIDENCE_PRESENT)

    def test_allowlist_only_names_known_operations(self) -> None:
        known = set(ops._OPERATION_BY_NAME.keys())
        for name in ops.EVIDENCE_PRODUCING_OPERATIONS:
            self.assertIn(name, known, f"EVIDENCE_PRODUCING_OPERATIONS references unknown op {name!r}")

    def test_evidence_operation_metadata_advertises_envelope(self) -> None:
        for tool in ops.all_operations():
            produces = tool["annotations"].get("produces") or []
            with self.subTest(op=tool["name"]):
                if tool["name"] in ops.EVIDENCE_PRODUCING_OPERATIONS:
                    self.assertIn("evidence_envelope", produces)
                else:
                    self.assertNotIn("evidence_envelope", produces)


if __name__ == "__main__":
    unittest.main()
