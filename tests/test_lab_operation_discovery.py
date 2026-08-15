from __future__ import annotations

import unittest

from genomi.operations.registry.execution import OperationExecutionContext
from genomi.operations.registry.table import call_operation, list_operations


class LabOperationDiscoveryTest(unittest.TestCase):
    def test_lab_is_focused_and_evidence_invoke_gets_host_receipt(self) -> None:
        default_names = {tool["name"] for tool in list_operations()}
        self.assertFalse(any(name.startswith("lab.") for name in default_names))

        focused = list_operations(capability="lab")
        names = {tool["name"] for tool in focused}
        self.assertEqual(
            names,
            {
                "lab.create_investigation",
                "lab.create_specialist_assignment",
                "lab.read_investigation",
                "lab.create_cycle",
                "lab.create_hypothesis",
                "lab.revise_hypothesis",
                "lab.prepare_specialist_brief",
                "lab.transition_specialist_assignment",
                "lab.update_health_profile",
                "lab.capture_evidence_result",
                "lab.capture_provider_result",
                "lab.publish_brief",
            },
        )
        self.assertTrue(
            all(tool["annotations"]["toolCapability"] == "lab" for tool in focused)
        )
        capture = next(
            tool for tool in focused if tool["name"] == "lab.capture_evidence_result"
        )
        self.assertIn("result_receipt_id", capture["inputSchema"]["required"])

        issued: dict[str, object] = {}

        def issue(**payload: object) -> str:
            issued.update(payload)
            return "result-receipt-test"

        params = {
            "tool": "phenotype.normalize_terms",
            "params": {"text": "ataxia"},
        }
        result = call_operation(
            "genomi.invoke",
            params,
            execution_context=OperationExecutionContext(
                operation="genomi.invoke",
                params=params,
                evidence_result_receipt_issuer=issue,
            ),
        )
        self.assertEqual(result["result_receipt_id"], "result-receipt-test")
        self.assertEqual(issued["operation"], "phenotype.normalize_terms")
        self.assertEqual(issued["params"], {"text": "ataxia"})
        self.assertNotIn("result_receipt_id", issued["presented_result"])


if __name__ == "__main__":
    unittest.main()
