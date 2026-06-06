from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from genomi.active_genome_index.source_intake import SUPPORTED_SOURCE_FORMATS
from genomi.capabilities.decode import dashboard as decode_dashboard
from genomi.operations import TOOL_CATALOG, call_operation

from tests.support.active_genome_index.source_fixture_inventory import (
    SEQUENCING_SOURCE_FIXTURE_FORMATS,
    SOURCE_FIXTURE_INVENTORY,
)
from tests.support.matrix.capability_contract import (
    COVERAGE_OPERATION_CLASSES,
    EXTERNAL_SOURCE_CAPABILITIES,
    EXTERNAL_SOURCE_EXECUTABLE_CELLS,
    EXTERNAL_SOURCE_EXECUTABLE_OPERATIONS,
    EXTERNAL_SOURCE_OPERATION_RATIONALES,
    MatrixCaseContext,
    PUBLIC_DETERMINISTIC_CAPABILITIES,
    PUBLIC_DETERMINISTIC_OPERATION_CASES,
    PUBLIC_DETERMINISTIC_OPERATIONS,
    PUBLIC_DETERMINISTIC_SOURCE_INVARIANT_CELLS,
    SOURCE_FORMAT_MATRIX_CAPABILITIES,
    SOURCE_FORMAT_MATRIX_CAPABILITY_CELLS,
    SOURCE_FORMAT_MATRIX_CELLS,
    SOURCE_FORMAT_MATRIX_OPERATIONS,
    SOURCE_FORMAT_MATRIX_SOURCE_FORMATS,
    SOURCE_FORMAT_SUPPORT_EXECUTABLE_CELLS,
    SOURCE_FORMAT_SUPPORT_EXECUTABLE_OPERATIONS,
    SOURCE_FORMAT_SUPPORT_OPERATION_RATIONALES,
    STATEFUL_RUNTIME_CAPABILITIES,
    STATEFUL_RUNTIME_EXECUTABLE_CELLS,
    STATEFUL_RUNTIME_EXECUTABLE_OPERATIONS,
    STATEFUL_RUNTIME_OPERATION_RATIONALES,
)
from tests.support.matrix.result_states import (
    DECODE_COVERAGE_STATE_CELLS,
    DECODE_DATA_RETURNED_CASES,
    DECODE_DATA_RETURNED_CELLS,
    DECODE_NATIVE_STATUS_CELLS,
    DECODE_PGX_STATUS_CELLS,
    DECODE_PRS_STATUS_CELLS,
    DECODE_RESULT_STATE_CASES,
    DECODE_RESULT_STATE_CELLS,
    DECODE_RESULT_STATE_OPERATION,
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

    def test_source_format_matrix_declares_every_supported_runtime_format(self) -> None:
        self.assertEqual(SOURCE_FORMAT_MATRIX_SOURCE_FORMATS, set(SUPPORTED_SOURCE_FORMATS))

    def test_source_fixture_inventory_covers_every_supported_runtime_format(self) -> None:
        fixture_formats = {spec.expected_format for spec in SOURCE_FIXTURE_INVENTORY}
        fixture_formats |= set(SEQUENCING_SOURCE_FIXTURE_FORMATS.values())
        self.assertEqual(fixture_formats, SOURCE_FORMAT_MATRIX_SOURCE_FORMATS)

    def test_source_fixture_inventory_has_direct_genome_extension_case(self) -> None:
        direct_genome_cases = [
            spec for spec in SOURCE_FIXTURE_INVENTORY
            if spec.expected_format == "genome" and spec.case_id == "genome"
        ]
        self.assertEqual(len(direct_genome_cases), 1)
        self.assertEqual(direct_genome_cases[0].writer_method, "_write_genome_text_source")

    def test_source_fixture_inventory_case_ids_are_unique(self) -> None:
        case_ids = [spec.case_id for spec in SOURCE_FIXTURE_INVENTORY]
        case_ids.extend(SEQUENCING_SOURCE_FIXTURE_FORMATS)
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_source_format_matrix_cells_are_complete_products(self) -> None:
        self.assertEqual(
            SOURCE_FORMAT_MATRIX_CAPABILITY_CELLS,
            {
                (source_format, capability)
                for source_format in SOURCE_FORMAT_MATRIX_SOURCE_FORMATS
                for capability in SOURCE_FORMAT_MATRIX_CAPABILITIES
            },
        )
        self.assertEqual(
            SOURCE_FORMAT_MATRIX_CELLS,
            {
                (source_format, operation)
                for source_format in SOURCE_FORMAT_MATRIX_SOURCE_FORMATS
                for operation in SOURCE_FORMAT_MATRIX_OPERATIONS
            },
        )
        self.assertEqual(
            PUBLIC_DETERMINISTIC_SOURCE_INVARIANT_CELLS,
            {
                (source_format, operation)
                for source_format in SOURCE_FORMAT_MATRIX_SOURCE_FORMATS
                for operation in PUBLIC_DETERMINISTIC_OPERATIONS
            },
        )
        self.assertEqual(
            SOURCE_FORMAT_SUPPORT_EXECUTABLE_CELLS,
            {
                (source_format, operation)
                for source_format in SOURCE_FORMAT_MATRIX_SOURCE_FORMATS
                for operation in SOURCE_FORMAT_SUPPORT_EXECUTABLE_OPERATIONS
            },
        )
        self.assertEqual(
            EXTERNAL_SOURCE_EXECUTABLE_CELLS,
            {
                (source_format, operation)
                for source_format in SOURCE_FORMAT_MATRIX_SOURCE_FORMATS
                for operation in EXTERNAL_SOURCE_EXECUTABLE_OPERATIONS
            },
        )
        self.assertEqual(
            STATEFUL_RUNTIME_EXECUTABLE_CELLS,
            {
                (source_format, operation)
                for source_format in SOURCE_FORMAT_MATRIX_SOURCE_FORMATS
                for operation in STATEFUL_RUNTIME_EXECUTABLE_OPERATIONS
            },
        )

    def test_decode_result_state_matrix_cells_are_complete_products(self) -> None:
        self.assertEqual(
            DECODE_RESULT_STATE_CELLS,
            DECODE_NATIVE_STATUS_CELLS
            | DECODE_COVERAGE_STATE_CELLS
            | DECODE_PGX_STATUS_CELLS
            | DECODE_PRS_STATUS_CELLS,
        )
        self.assertEqual(DECODE_RESULT_STATE_OPERATION, "decode.render_dashboard")
        self.assertIn(DECODE_RESULT_STATE_OPERATION, TOOL_CATALOG["operations"])
        self.assertEqual(
            DECODE_DATA_RETURNED_CELLS,
            {
                (DECODE_RESULT_STATE_OPERATION, panel, mode)
                for panel in decode_dashboard.PANEL_KEYS
                for mode in ("full", "update")
            },
        )

    def test_executable_source_support_operations_are_source_support_operations(self) -> None:
        self.assertLessEqual(SOURCE_FORMAT_SUPPORT_EXECUTABLE_OPERATIONS, set(SOURCE_FORMAT_SUPPORT_OPERATION_RATIONALES))

    def test_executable_external_operations_are_external_source_operations(self) -> None:
        self.assertEqual(EXTERNAL_SOURCE_EXECUTABLE_OPERATIONS, set(EXTERNAL_SOURCE_OPERATION_RATIONALES))

    def test_executable_stateful_runtime_operations_are_stateful_runtime_operations(self) -> None:
        self.assertLessEqual(STATEFUL_RUNTIME_EXECUTABLE_OPERATIONS, set(STATEFUL_RUNTIME_OPERATION_RATIONALES))

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

    def test_decode_result_state_cases_execute_their_declared_cells(self) -> None:
        seen_cells: set[tuple[str, str, str, str, str]] = set()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for case in DECODE_RESULT_STATE_CASES:
                with self.subTest(cell=case.cell):
                    case.run(root)
                    seen_cells.add(case.cell)

        self.assertEqual(seen_cells, DECODE_RESULT_STATE_CELLS)

    def test_decode_data_returned_cases_render_their_declared_panels(self) -> None:
        seen_cells: set[tuple[str, str, str]] = set()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for case in DECODE_DATA_RETURNED_CASES:
                with self.subTest(cell=case.cell):
                    case.run(root)
                    seen_cells.add(case.cell)

        self.assertEqual(seen_cells, DECODE_DATA_RETURNED_CELLS)

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
