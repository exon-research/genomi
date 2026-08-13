from __future__ import annotations

import unittest

from genomi.lab.server import _INVESTIGATION_ACTION_ROUTE


class GenomiLabEvidenceHTTPContractTests(unittest.TestCase):
    def test_portal_cannot_initiate_provider_evidence_outside_harness_request(self) -> None:
        investigation = "investigation-acde1234"
        for action in (
            "evidence-preview",
            "evidence-approval",
            "evidence-retrieve",
        ):
            with self.subTest(action=action):
                matched = _INVESTIGATION_ACTION_ROUTE.fullmatch(
                    f"/api/v1/investigations/{investigation}/{action}"
                )
                self.assertIsNone(matched)

        continuation = _INVESTIGATION_ACTION_ROUTE.fullmatch(
            f"/api/v1/investigations/{investigation}/capability-execute"
        )
        self.assertIsNotNone(continuation)
        assert continuation is not None
        self.assertEqual(
            continuation.groups(), (investigation, "capability-execute")
        )


if __name__ == "__main__":
    unittest.main()
