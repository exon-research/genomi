from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from genomi.operations import TOOL_CATALOG, call_operation

from _capability_matrix_contract import (
    COVERAGE_OPERATION_CLASSES,
    EXTERNAL_SOURCE_CAPABILITIES,
    EXTERNAL_SOURCE_OPERATION_RATIONALES,
    MatrixCaseContext,
    PUBLIC_DETERMINISTIC_CAPABILITIES,
    PUBLIC_DETERMINISTIC_OPERATION_CASES,
    PUBLIC_DETERMINISTIC_OPERATIONS,
    SOURCE_FORMAT_MATRIX_CAPABILITIES,
    SOURCE_FORMAT_MATRIX_OPERATIONS,
    SOURCE_FORMAT_SUPPORT_OPERATION_RATIONALES,
    STATEFUL_RUNTIME_CAPABILITIES,
    STATEFUL_RUNTIME_OPERATION_RATIONALES,
)


class CapabilityMatrixContractTests(unittest.TestCase):
    """Keep the end-to-end capability matrix explicit as the catalog grows."""

    def test_every_catalog_capability_has_a_matrix_lane(self) -> None:
        classified = (
            SOURCE_FORMAT_MATRIX_CAPABILITIES
            | PUBLIC_DETERMINISTIC_CAPABILITIES
            | EXTERNAL_SOURCE_CAPABILITIES
            | STATEFUL_RUNTIME_CAPABILITIES
        )
        self.assertEqual(set(TOOL_CATALOG["capabilities"]), classified)

    def test_source_format_matrix_operations_are_current_catalog_operations(self) -> None:
        operations = set(TOOL_CATALOG["operations"])
        for operation in SOURCE_FORMAT_MATRIX_OPERATIONS:
            with self.subTest(operation=operation):
                self.assertIn(operation, operations)

    def test_every_catalog_operation_has_one_explicit_coverage_class(self) -> None:
        catalog_operations = set(TOOL_CATALOG["operations"])
        classified_operations = set().union(*COVERAGE_OPERATION_CLASSES)
        self.assertEqual(catalog_operations, classified_operations)
        for left_index, left in enumerate(COVERAGE_OPERATION_CLASSES):
            for right in COVERAGE_OPERATION_CLASSES[left_index + 1 :]:
                self.assertFalse(left & right)

    def test_source_format_matrix_operations_stay_assigned_to_source_matrix_capabilities(self) -> None:
        operation_capabilities = _operation_capabilities()
        for operation in SOURCE_FORMAT_MATRIX_OPERATIONS:
            with self.subTest(operation=operation):
                self.assertIn(operation_capabilities[operation], SOURCE_FORMAT_MATRIX_CAPABILITIES)

        for capability in SOURCE_FORMAT_MATRIX_CAPABILITIES:
            covered_operations = {
                operation
                for operation in TOOL_CATALOG["capabilities"][capability]["operations"]
                if operation in SOURCE_FORMAT_MATRIX_OPERATIONS
            }
            with self.subTest(capability=capability):
                self.assertTrue(covered_operations, f"{capability} has no source-format matrix operation")

    def test_public_deterministic_operation_cases_execute_their_declared_operations(self) -> None:
        seen_operations: set[str] = set()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = MatrixCaseContext(Path(tmp))
            for case in PUBLIC_DETERMINISTIC_OPERATION_CASES:
                with self.subTest(operation=case.operation):
                    result = call_operation(case.operation, case.params(ctx))
                    case.assert_result(result, ctx)
                    seen_operations.add(case.operation)

        self.assertEqual(seen_operations, PUBLIC_DETERMINISTIC_OPERATIONS)

    def test_public_deterministic_cases_are_current_catalog_operations(self) -> None:
        operations = set(TOOL_CATALOG["operations"])
        case_operations = [case.operation for case in PUBLIC_DETERMINISTIC_OPERATION_CASES]
        self.assertEqual(len(case_operations), len(set(case_operations)))
        for case in PUBLIC_DETERMINISTIC_OPERATION_CASES:
            with self.subTest(operation=case.operation):
                self.assertIn(case.operation, operations)
                self.assertEqual(case.lane, "public_deterministic")
        self.assertEqual(set(case_operations), PUBLIC_DETERMINISTIC_OPERATIONS)

    def test_non_executable_lanes_have_explicit_rationales(self) -> None:
        self.assertEqual(set(SOURCE_FORMAT_SUPPORT_OPERATION_RATIONALES), _source_format_support_operations())
        self.assertEqual(set(EXTERNAL_SOURCE_OPERATION_RATIONALES), _external_source_operations())
        self.assertEqual(set(STATEFUL_RUNTIME_OPERATION_RATIONALES), _stateful_runtime_operations())
        for operation, rationale in {
            **SOURCE_FORMAT_SUPPORT_OPERATION_RATIONALES,
            **EXTERNAL_SOURCE_OPERATION_RATIONALES,
            **STATEFUL_RUNTIME_OPERATION_RATIONALES,
        }.items():
            with self.subTest(operation=operation):
                self.assertIsInstance(rationale, str)
                self.assertGreaterEqual(len(rationale.split()), 3)


def _operation_capabilities() -> dict[str, str]:
    return {
        operation: capability
        for capability, definition in TOOL_CATALOG["capabilities"].items()
        for operation in definition["operations"]
    }


def _source_format_support_operations() -> set[str]:
    return set(COVERAGE_OPERATION_CLASSES[1])


def _external_source_operations() -> set[str]:
    return set(COVERAGE_OPERATION_CLASSES[3])


def _stateful_runtime_operations() -> set[str]:
    return set(COVERAGE_OPERATION_CLASSES[4])


if __name__ == "__main__":
    unittest.main()
