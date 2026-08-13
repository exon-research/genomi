from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping
from unittest import mock

from genomi.lab.encrypted_sqlite import StaticEncryptionKeyProvider
from genomi.lab.harness import (
    HarnessArtifactKind,
    HarnessEventKind,
    HarnessEventStatus,
    SimulatedHarnessAdapter,
)
from genomi.lab.harness_adapter import HostArtifact
from genomi.lab.service import GenomiLabService
from genomi.lab.store import GenomiLabStore


class _CurrentUserOperations:
    def __call__(
        self,
        operation: str,
        params: dict[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        del params
        if operation == "genomi.describe_context":
            return {
                "active_user_id": "artifact-quarantine-user",
                "active_user": {"nickname": "Artifact quarantine user"},
                "active_agi_id": None,
                "active_genome_index": None,
            }
        if operation == "active_genome_index.revoke_access":
            return {"status": "revoked"}
        raise AssertionError(f"unexpected operation: {operation}")


class _LegacyLeakyUnsafeBriefAdapter(SimulatedHarnessAdapter):
    """Model an older/custom adapter that still embeds its artifact in events."""

    sentinel = "UNSAFE_BRIEF_ARTIFACT_SENTINEL"

    def __init__(self) -> None:
        super().__init__(adapter_id="legacy-leaky-artifact-adapter")
        self._latest_artifact: Mapping[str, Any] | None = None
        self.unsafe_execution_summary: str | None = None
        self.execution_status_override: str | None = None

    def _produce_artifact(  # type: ignore[override]
        self,
        artifact_kind: HarnessArtifactKind,
        command: Any,
        instruction: str,
        approved_context: Mapping[str, Any],
        *,
        resume_task_id: str | None,
    ) -> HostArtifact:
        produced = super()._produce_artifact(
            artifact_kind,
            command,
            instruction,
            approved_context,
            resume_task_id=resume_task_id,
        )
        artifact = dict(produced.artifact)
        if artifact_kind == HarnessArtifactKind.BRIEF_DRAFT:
            artifact["summary"] = (
                f"{self.sentinel}: the patient has a confirmed diagnosis."
            )
            artifact["clinical_stage"] = "diagnosis"
        elif artifact_kind == HarnessArtifactKind.EXECUTION_REPORT:
            if self.unsafe_execution_summary is not None:
                artifact["summary"] = self.unsafe_execution_summary
            request_results = list(artifact.get("request_results") or [])
            if self.execution_status_override is not None and request_results:
                request_results[0] = {
                    **dict(request_results[0]),
                    "status": self.execution_status_override,
                }
                artifact["request_results"] = request_results
        self._latest_artifact = artifact
        return HostArtifact(
            artifact_kind,
            artifact,
            produced.host_task_id,
            produced.host_run_id,
            produced.trace_events,
            produced.trace_events_complete,
        )

    def _emit(  # type: ignore[override]
        self,
        command: Any,
        binding: Any,
        kind: HarnessEventKind,
        status: HarnessEventStatus,
        payload: Mapping[str, Any],
        references: tuple[Any, ...] = (),
    ) -> Any:
        if kind in {
            HarnessEventKind.PLAN_PROPOSED,
            HarnessEventKind.CAPABILITY_EXECUTION_COMPLETED,
            HarnessEventKind.BRIEF_COMPLETED,
        }:
            payload = dict(payload)
            payload["artifact"] = self._latest_artifact
            payload["artifact_reference"] = {
                "kind": kind.value,
                "artifact": self._latest_artifact,
            }
        return super()._emit(
            command,
            binding,
            kind,
            status,
            payload,
            references,
        )


class _ReportWithoutCapabilityCallsAdapter(SimulatedHarnessAdapter):
    """Return a complete-looking report without crossing the capability gateway."""

    def __init__(self) -> None:
        super().__init__(adapter_id="report-without-capability-calls")

    def _produce_artifact(  # type: ignore[override]
        self,
        artifact_kind: HarnessArtifactKind,
        command: Any,
        instruction: str,
        approved_context: Mapping[str, Any],
        *,
        resume_task_id: str | None,
    ) -> HostArtifact:
        if artifact_kind != HarnessArtifactKind.EXECUTION_REPORT:
            return super()._produce_artifact(
                artifact_kind,
                command,
                instruction,
                approved_context,
                resume_task_id=resume_task_id,
            )
        accepted_plan = approved_context.get("accepted_plan")
        plan = accepted_plan.get("plan") if isinstance(accepted_plan, Mapping) else None
        requests = (
            plan.get("capability_requests") if isinstance(plan, Mapping) else None
        )
        if not isinstance(requests, (list, tuple)):
            raise ValueError("test adapter requires an accepted plan")
        return HostArtifact(
            artifact_kind,
            {
                "summary": "The exact accepted requests were executed.",
                "request_results": [
                    {
                        "request_id": request["id"],
                        "capability": request["capability"],
                        "status": "completed",
                    }
                    for request in requests
                ],
            },
            resume_task_id or self._generated_id("sim-task", command.command_id),
            self._generated_id("sim-turn", command.command_id),
            (),
            True,
        )


class GenomiLabHarnessArtifactQuarantineTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.adapter = _LegacyLeakyUnsafeBriefAdapter()
        self.service = GenomiLabService(
            store=GenomiLabStore(
                Path(temporary.name) / "genomilab.sqlite3",
                key_provider=StaticEncryptionKeyProvider(b"q" * 32),
            ),
            session_id="artifact-quarantine-session",
            operation_call=_CurrentUserOperations(),
            harness_adapter=self.adapter,
        )
        self.addCleanup(self.service.close)
        self.service.bootstrap_workspace()
        observation = self.service.add_profile_observation(
            {
                "modality": "condition",
                "label": "Synthetic condition",
                "original_wording": "Synthetic condition",
                "source_class": "patient_reported",
                "verification_state": "user_confirmed",
            }
        )
        investigation = self.service.create_investigation(
            {
                "question": "Could the molecular profile inform this condition?",
                "disease_scope": "Synthetic condition",
            }
        )
        self.investigation_id = str(investigation["investigation_id"])
        candidate = self.service.investigation_context_candidate(
            self.investigation_id,
            {
                "purpose": "Investigate the synthetic condition",
                "observation_revision_ids": [observation["observation_revision_id"]],
            },
        )
        self.service.approve_investigation_context(
            self.investigation_id,
            {
                key: candidate[key]
                for key in (
                    "purpose",
                    "observation_revision_ids",
                    "artifact_ids",
                    "specimen_ids",
                    "assay_ids",
                    "agi_id",
                    "agi_snapshot_id",
                    "genomic_scope",
                    "candidate_sha256",
                    "candidate_receipt",
                )
            }
            | {"approved": True},
        )

    def _approved_call(
        self,
        *,
        command_id: str,
        operation: str,
        artifact_kind: str,
        instruction: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        preview = self.service.harness_disclosure_candidate(
            self.investigation_id,
            command_id=command_id,
            operation=operation,
            artifact_kind=artifact_kind,
            instruction=instruction,
            reason=reason,
        )
        request: dict[str, Any] = {
            "approved": True,
            "payload_sha256": preview["payload_sha256"],
            "command_id": command_id,
            "expected_revision": preview["payload"]["command_context"][
                "expected_revision"
            ],
        }
        if instruction is not None:
            request["message"] = instruction
        if reason is not None:
            request["reason"] = reason
        if operation == "start_task_run":
            return self.service.start_investigation(self.investigation_id, request)
        request["artifact_kind"] = artifact_kind
        return self.service.replace_harness_binding(self.investigation_id, request)

    def test_rejected_unsafe_brief_is_quarantined_from_durable_event_replay(
        self,
    ) -> None:
        planned = self._approved_call(
            command_id="artifact-quarantine-plan",
            operation="start_task_run",
            artifact_kind="plan",
        )
        self.assertEqual(planned["status"], "accepted")
        current_plan = self.service.investigation(self.investigation_id)[
            "current_plan_version"
        ]
        self.service.accept_current_plan(
            self.investigation_id,
            {
                "approved": True,
                "plan_version_id": current_plan["plan_version_id"],
                "plan_sha256": current_plan["plan_sha256"],
            },
        )

        rejected = self._approved_call(
            command_id="artifact-quarantine-brief",
            operation="replace_task_binding",
            artifact_kind="brief_draft",
            instruction="Draft an evidence-linked research brief for review.",
            reason="Use the accepted plan in a fresh synthesis task.",
        )

        self.assertEqual(rejected["status"], "artifact_rejected")
        self.assertIsNone(rejected["committed_artifact"])
        investigation = self.service.investigation(self.investigation_id)
        self.assertEqual(investigation["brief_versions"], [])
        self.assertIsNone(investigation["brief"])

        replayed = self.service.replay_investigation_events(self.investigation_id)[
            "events"
        ]
        self.assertIn("brief_completed", {event["event_type"] for event in replayed})
        serialized_payloads = json.dumps(
            [event["payload"] for event in replayed], sort_keys=True
        )
        self.assertNotIn(self.adapter.sentinel, serialized_payloads)
        brief_event = next(
            event for event in replayed if event["event_type"] == "brief_completed"
        )
        self.assertNotIn("artifact", brief_event["payload"]["payload"])
        self.assertEqual(
            brief_event["payload"]["payload"]["artifact_kind"], "brief_draft"
        )

    def _accept_generated_plan(self, *, command_suffix: str) -> None:
        planned = self._approved_call(
            command_id=f"artifact-quarantine-plan-{command_suffix}",
            operation="start_task_run",
            artifact_kind="plan",
        )
        self.assertEqual(planned["status"], "accepted")
        current_plan = self.service.investigation(self.investigation_id)[
            "current_plan_version"
        ]
        self.service.accept_current_plan(
            self.investigation_id,
            {
                "approved": True,
                "plan_version_id": current_plan["plan_version_id"],
                "plan_sha256": current_plan["plan_sha256"],
            },
        )

    def _install_adapter(self, adapter: SimulatedHarnessAdapter) -> None:
        self.adapter = adapter  # type: ignore[assignment]
        self.service.harness_adapter = adapter
        adapter.bind_dynamic_tool_handler(
            self.service._execute_guarded_harness_capability
        )

    def _execute_accepted_plan(self, *, command_suffix: str) -> dict[str, Any]:
        return self._approved_call(
            command_id=f"artifact-quarantine-execution-{command_suffix}",
            operation="replace_task_binding",
            artifact_kind="execution_report",
            instruction="Execute the exact accepted requests.",
            reason="Run the separately approved investigation execution task.",
        )

    def test_execution_report_requires_each_persisted_capability_execution(
        self,
    ) -> None:
        self._install_adapter(_ReportWithoutCapabilityCallsAdapter())
        self._accept_generated_plan(command_suffix="unattested")

        rejected = self._execute_accepted_plan(command_suffix="unattested")

        self.assertEqual(rejected["status"], "artifact_rejected")
        self.assertIsNone(rejected["committed_artifact"])
        self.assertIn("persisted capability execution", rejected["artifact_error"])
        investigation = self.service.investigation(self.investigation_id)
        self.assertEqual(investigation["current_capability_executions"], [])

    def test_execution_report_status_must_match_persisted_result(self) -> None:
        self._accept_generated_plan(command_suffix="status-mismatch")
        self.adapter.execution_status_override = "in_progress"

        rejected = self._execute_accepted_plan(command_suffix="status-mismatch")

        self.assertEqual(rejected["status"], "artifact_rejected")
        self.assertIsNone(rejected["committed_artifact"])
        self.assertIn("status does not match", rejected["artifact_error"])
        investigation = self.service.investigation(self.investigation_id)
        self.assertTrue(investigation["current_capability_executions"])

    def test_execution_report_accepts_completed_and_approval_required_rows(
        self,
    ) -> None:
        self._accept_generated_plan(command_suffix="attested-terminal")

        accepted = self._execute_accepted_plan(command_suffix="attested-terminal")

        self.assertEqual(accepted["status"], "accepted")
        statuses = {
            item["status"]
            for item in accepted["committed_artifact"]["report"]["request_results"]
        }
        self.assertEqual(statuses, {"completed", "approval_required"})
        self.assertEqual(
            len(accepted["capability_results"]),
            len(
                self.service.investigation(self.investigation_id)[
                    "current_capability_executions"
                ]
            ),
        )

    def test_execution_report_accepts_attested_in_progress_row(self) -> None:
        self._accept_generated_plan(command_suffix="attested-background")
        original_execute = self.service._execute_capability_request

        def execute_with_background(
            investigation_id: str,
            request: dict[str, Any],
            *,
            approval: dict[str, Any] | None,
            expected_plan_version_id: str | None = None,
            expected_consent_receipt_id: str | None = None,
        ) -> dict[str, Any]:
            if request.get("capability") == "investigation.project_profile":
                return {
                    "status": "in_progress",
                    "job_id": "synthetic-profile-job",
                    "resume_operation": "synthetic.profile.check",
                    "poll_after_seconds": 1,
                }
            return original_execute(
                investigation_id,
                request,
                approval=approval,
                expected_plan_version_id=expected_plan_version_id,
                expected_consent_receipt_id=expected_consent_receipt_id,
            )

        with mock.patch.object(
            self.service,
            "_execute_capability_request",
            side_effect=execute_with_background,
        ):
            accepted = self._execute_accepted_plan(command_suffix="attested-background")

        self.assertEqual(accepted["status"], "accepted")
        statuses = {
            item["status"]
            for item in accepted["committed_artifact"]["report"]["request_results"]
        }
        self.assertEqual(statuses, {"in_progress", "approval_required"})
        persisted_statuses = {
            item["status"]
            for item in self.service.investigation(self.investigation_id)[
                "current_capability_executions"
            ]
        }
        self.assertEqual(persisted_statuses, {"in_progress", "approval_required"})

    def test_execution_report_summary_rejects_diagnostic_claim_at_commit_boundary(
        self,
    ) -> None:
        self._accept_generated_plan(command_suffix="diagnosis")
        self.adapter.unsafe_execution_summary = (
            "The evidence confirms the patient's diagnosis."
        )

        rejected = self._approved_call(
            command_id="artifact-quarantine-execution-diagnosis",
            operation="replace_task_binding",
            artifact_kind="execution_report",
            instruction="Execute the exact accepted requests.",
            reason="Run the separately approved investigation execution task.",
        )

        self.assertEqual(rejected["status"], "artifact_rejected")
        self.assertIsNone(rejected["committed_artifact"])
        self.assertIn("diagnosis or treatment directive", rejected["artifact_error"])

    def test_execution_report_summary_rejects_treatment_directive_at_commit_boundary(
        self,
    ) -> None:
        self._accept_generated_plan(command_suffix="treatment")
        self.adapter.unsafe_execution_summary = (
            "The patient should start treatment immediately."
        )

        rejected = self._approved_call(
            command_id="artifact-quarantine-execution-treatment",
            operation="replace_task_binding",
            artifact_kind="execution_report",
            instruction="Execute the exact accepted requests.",
            reason="Run the separately approved investigation execution task.",
        )

        self.assertEqual(rejected["status"], "artifact_rejected")
        self.assertIsNone(rejected["committed_artifact"])
        self.assertIn("diagnosis or treatment directive", rejected["artifact_error"])


if __name__ == "__main__":
    unittest.main()
