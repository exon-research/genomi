from __future__ import annotations

import unittest
from typing import Any

from genomi.lab.harness import HarnessDynamicToolCall, SimulatedHarnessAdapter
from genomi.lab.harness_tool_boundary import HarnessToolBoundary
from genomi.lab.service import GenomiLabService, LabError


class _BoundCommandStore:
    def __init__(self, *, plan: dict[str, Any]) -> None:
        self.plan = plan
        self.required_receipts = 0
        self.binding: dict[str, object] = {
            "binding_id": "binding-planning",
            "investigation_id": "investigation-a",
            "command_id": "command-planning",
            "host_id": "simulated-harness",
            "task_id": "planning-thread",
            "run_id": "planning-turn",
            "harness_status": "waiting",
            "harness_revision": 1,
        }

    def harness_command(self, command_id: str) -> dict[str, object]:
        return {
            "command_id": command_id,
            "investigation_id": "investigation-a",
            "workspace_session_id": "session-a",
            "user_id": "user-a",
            "operation": "replace_task_binding",
            "command_state": "dispatching",
            "disclosure_receipt_id": "receipt-a",
        }

    def outbound_disclosure_receipt(self, receipt_id: str) -> dict[str, object]:
        assert receipt_id == "receipt-a"
        return {
            "disclosure_receipt_id": receipt_id,
            "data_categories": ["accepted_investigation_plan", "molecular_profile_slice"],
            "payload": {
                "approved_context": {
                    "accepted_plan": {
                        "plan_version_id": "plan-a",
                        "plan_sha256": "a" * 64,
                        "plan": self.plan,
                    },
                    "private_context_authority": {
                        "patient_molecular_snapshot_id": "snapshot-a",
                        "consent_receipt_id": "consent-a",
                    },
                },
                "command_context": {
                    "task_id": "planning-thread",
                    "run_id": "planning-turn",
                    "current_binding_revision": 1,
                    "expected_revision": 1,
                },
            },
        }

    def active_harness_binding(self, investigation_id: str) -> dict[str, object]:
        assert investigation_id == "investigation-a"
        return dict(self.binding)

    def harness_job_for_command(self, _command_id: str) -> None:
        return None

    def bind_harness_task(
        self,
        investigation_id: str,
        *,
        command_id: object,
        host_id: object,
        task_id: object,
        run_id: object,
        harness_status: object,
        harness_revision: int,
    ) -> dict[str, object]:
        self.binding = {
            "binding_id": "binding-execution",
            "investigation_id": investigation_id,
            "command_id": command_id,
            "host_id": host_id,
            "task_id": task_id,
            "run_id": run_id,
            "harness_status": harness_status,
            "harness_revision": harness_revision,
        }
        return dict(self.binding)

    def require_outbound_disclosure(self, *_args: object, **_kwargs: object) -> None:
        self.required_receipts += 1

    def get_profile_snapshot(self, snapshot_id: str) -> dict[str, object]:
        assert snapshot_id == "snapshot-a"
        return {"patient_molecular_snapshot_id": snapshot_id}


class HarnessDynamicToolBoundaryTests(unittest.TestCase):
    def test_capability_identity_and_active_authority_are_checked_before_execution(
        self,
    ) -> None:
        plan = {
            "capability_requests": [
                {
                    "id": "request-profile",
                    "capability": "investigation.project_profile",
                }
            ]
        }
        store = _BoundCommandStore(plan=plan)
        adapter = SimulatedHarnessAdapter(adapter_id="simulated-harness")
        investigation = {
            "investigation_id": "investigation-a",
            "user_id": "user-a",
            "patient_molecular_snapshot_id": "snapshot-a",
            "plan": plan,
            "current_plan_version": {
                "review_status": "accepted",
                "plan_version_id": "plan-a",
                "plan_sha256": "a" * 64,
                "plan": plan,
            },
        }

        def active_context_receipt(
            _investigation: object, _snapshot: object
        ) -> dict[str, object]:
            return {
                "consent_receipt_id": "consent-a",
                "workspace_session_id": "session-a",
                "patient_molecular_snapshot_id": "snapshot-a",
                "revoked_at": None,
            }

        executions: list[tuple[str, object]] = []
        authorization_checks: list[tuple[str, str, str]] = []
        authorization_active = True

        def require_authorized_disclosure(
            investigation_id: str, receipt_id: str, intent: str
        ) -> dict[str, object]:
            authorization_checks.append((investigation_id, receipt_id, intent))
            if not authorization_active:
                raise ValueError("parent investigation authorization is revoked")
            return {"authorization_receipt_id": "authorization-a"}

        def execute(
            investigation_id: str,
            payload: object,
            *,
            _authority: object,
        ) -> dict[str, object]:
            self.assertIsNotNone(_authority)
            executions.append((investigation_id, payload))
            return {
                "status": "completed",
                "capability": "investigation.project_profile",
            }

        boundary = HarnessToolBoundary(
            store=store,
            session_id="session-a",
            harness_adapter=adapter,
            current_context=lambda: ({}, "user-a"),
            accepted_plan=lambda _investigation_id: investigation,
            active_context_receipt=active_context_receipt,
            require_authorized_disclosure=require_authorized_disclosure,
            execute_request=lambda investigation_id, payload: execute(
                investigation_id,
                payload,
                _authority=object(),
            ),
        )
        mismatched = HarnessDynamicToolCall(
            command_id="command-a",
            investigation_id="investigation-a",
            thread_id="thread-a",
            turn_id="turn-a",
            call_id="call-a",
            capability="genomi.variant.resolve",
            request_id="request-profile",
        )

        with self.assertRaisesRegex(ValueError, "exactly match"):
            boundary.execute(mismatched)
        self.assertEqual(executions, [])

        matched = HarnessDynamicToolCall(
            command_id="command-b",
            investigation_id="investigation-a",
            thread_id="thread-a",
            turn_id="turn-b",
            call_id="call-b",
            capability="investigation.project_profile",
            request_id="request-profile",
        )
        result = boundary.execute(matched)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            executions,
            [("investigation-a", {"request_id": "request-profile"})],
        )
        self.assertEqual(
            authorization_checks[-1],
            ("investigation-a", "receipt-a", "execute_accepted_plan"),
        )
        self.assertEqual(store.required_receipts, 2)

        authorization_active = False
        with self.assertRaisesRegex(ValueError, "authorization is revoked"):
            boundary.execute(matched)
        self.assertEqual(len(executions), 1)
        authorization_active = True

        wrong_turn = HarnessDynamicToolCall(
            command_id="command-b",
            investigation_id="investigation-a",
            thread_id="thread-a",
            turn_id="turn-other",
            call_id="call-other",
            capability="investigation.project_profile",
            request_id="request-profile",
        )
        with self.assertRaisesRegex(ValueError, "disclosed binding"):
            boundary.execute(wrong_turn)
        self.assertEqual(len(executions), 1)

        store.outbound_disclosure_receipt = lambda _receipt_id: {  # type: ignore[method-assign]
            **_BoundCommandStore(plan=plan).outbound_disclosure_receipt("receipt-a"),
            "payload": {
                "approved_context": {
                    "accepted_plan": {
                        "plan_version_id": "plan-other",
                        "plan_sha256": "b" * 64,
                        "plan": plan,
                    }
                }
            },
        }
        with self.assertRaisesRegex(ValueError, "exact accepted plan"):
            boundary.execute(matched)
        self.assertEqual(len(executions), 1)

    def test_capability_execution_has_no_public_service_bypass(self) -> None:
        service = object.__new__(GenomiLabService)
        self.assertFalse(hasattr(service, "execute_harness_capability_request"))
        with self.assertRaisesRegex(LabError, "approved harness execution task"):
            service._execute_harness_capability_request(
                "investigation-a",
                {"request_id": "request-a"},
                _authority=object(),
            )


if __name__ == "__main__":
    unittest.main()
