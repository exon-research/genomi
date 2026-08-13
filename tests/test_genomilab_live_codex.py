"""Opt-in real Codex app-server verification for the GenomiLab vertical slice.

Run explicitly; this test uses the installed Codex model service and is never a
substitute for the deterministic adapter/conformance suites.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from genomi.lab.harness import (
    BindingStatus,
    CancelTaskWorkPayload,
    CancellationOutcome,
    HarnessCommand,
    HarnessErrorCode,
    HarnessEventKind,
    HarnessOperation,
    InstalledCodexAppServerAdapter,
    StartTaskRunPayload,
)
from genomi.lab import harness_codex as codex_transport
from genomi.lab.provider_policy import SourceFamily
from genomi.lab.service import GenomiLabService
from genomi.lab.store import GenomiLabStore
from genomi.operations import call_operation
from genomi.lab import agi_authority as investigation_access

from tests.genomilab_support import TEST_LAB_KEY_PROVIDER
from tests.support.runtime.genomi import GenomiRuntimeTestCase
from tests import test_genomilab_e2e as e2e_support


CODEX_BINARY = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
PROCESSING_DESTINATION = "remote: OpenAI Codex service"


class _TracingTransport:
    """Expose only protocol identities/statuses for an explicitly synthetic run."""

    def __init__(
        self,
        command: list[str],
        environment: dict[str, str],
        timeout_seconds: int,
    ) -> None:
        self._inner = codex_transport._StdioJsonLineTransport(  # noqa: SLF001
            command, environment, timeout_seconds
        )

    def send(self, message: dict[str, object]) -> None:
        method = message.get("method")
        if method != "initialized":
            params = message.get("params")
            params = params if isinstance(params, dict) else {}
            dynamic_tools = params.get("dynamicTools")
            dynamic_tools = dynamic_tools if isinstance(dynamic_tools, list) else []
            registered_tools = [
                tool.get("name")
                for namespace in dynamic_tools
                if isinstance(namespace, dict)
                for tool in namespace.get("tools") or []
                if isinstance(tool, dict)
            ]
            print(
                "GENOMILAB_LIVE_PROTOCOL_SEND "
                + json.dumps(
                    {
                        "id": message.get("id"),
                        "method": method,
                        "dynamic_namespace_count": len(dynamic_tools),
                        "registered_tools": registered_tools,
                        "tool": params.get("tool"),
                        "tool_request_id": (params.get("arguments") or {}).get(
                            "request_id"
                        )
                        if isinstance(params.get("arguments"), dict)
                        else None,
                        "artifact_has_output_schema": "outputSchema" in params,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        self._inner.send(message)

    def receive(self, timeout_seconds: float) -> dict[str, Any]:
        try:
            message = self._inner.receive(timeout_seconds)
        except Exception as exc:
            print(
                "GENOMILAB_LIVE_PROTOCOL_EXCEPTION " + repr(exc), flush=True
            )
            raise
        method = message.get("method")
        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        arguments = params.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        item = params.get("item")
        item = item if isinstance(item, dict) else {}
        turn = params.get("turn")
        turn = turn if isinstance(turn, dict) else {}
        if "id" in message or method in {
            "item/started",
            "item/completed",
            "turn/completed",
        }:
            print(
                "GENOMILAB_LIVE_PROTOCOL_RECV "
                + json.dumps(
                    {
                        "id": message.get("id"),
                        "method": method,
                        "error": message.get("error"),
                        "result_keys": sorted((message.get("result") or {}).keys())
                        if isinstance(message.get("result"), dict)
                        else [],
                        "item_type": item.get("type"),
                        "item_status": item.get("status"),
                        "turn_id": turn.get("id"),
                        "turn_status": turn.get("status"),
                        "turn_error": turn.get("error"),
                        "turn_keys": sorted(turn),
                        "turn_item_types": [
                            candidate.get("type")
                            for candidate in turn.get("items") or []
                            if isinstance(candidate, dict)
                        ],
                        "params_error": params.get("error"),
                        "params_keys": sorted(params),
                        "server_tool": params.get("tool"),
                        "server_tool_request_id": arguments.get("request_id"),
                        "server_call_id": params.get("callId"),
                        "server_thread_id": params.get("threadId"),
                        "server_turn_id": params.get("turnId"),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        return message

    def close(self) -> None:
        self._inner.close()


class LiveCodexVerticalSliceTests(GenomiRuntimeTestCase):
    """Exercise real model planning, exact-request execution, and synthesis."""

    _public_evidence_fixture = staticmethod(
        e2e_support.GenomiLabEndToEndTests._public_evidence_fixture
    )
    _intake_current_user = (
        e2e_support.GenomiLabEndToEndTests._intake_current_user
    )
    _add_molecular_profile = (
        e2e_support.GenomiLabEndToEndTests._add_molecular_profile
    )
    _approve_patient_context = (
        e2e_support.GenomiLabEndToEndTests._approve_patient_context
    )

    def setUp(self) -> None:
        if os.environ.get("GENOMILAB_RUN_LIVE_CODEX") != "1":
            self.skipTest("set GENOMILAB_RUN_LIVE_CODEX=1 for the real model test")
        if os.environ.get("GENOMILAB_CODEX_PROCESSING_DESTINATION") != (
            PROCESSING_DESTINATION
        ):
            self.fail("the exact remote Codex processing destination is required")
        if not CODEX_BINARY.is_file():
            self.fail(f"installed Codex binary is missing: {CODEX_BINARY}")
        super().setUp()
        investigation_access._reset_investigation_agi_authorization_epoch_for_testing()
        self.addCleanup(
            investigation_access._reset_investigation_agi_authorization_epoch_for_testing
        )
        self.store_path = self.genomi_home / "lab" / "genomilab-live-codex.sqlite3"
        self.adapter = InstalledCodexAppServerAdapter.discover(
            executable_name=str(CODEX_BINARY),
            which=lambda value: value,
            timeout_seconds=900,
            processing_destination=PROCESSING_DESTINATION,
            transport_factory=_TracingTransport,
        )
        self.assertTrue(
            self.adapter.manifest.available,
            self.adapter.manifest.unavailable_reason,
        )
        self.service = GenomiLabService(
            store=GenomiLabStore(
                self.store_path, key_provider=TEST_LAB_KEY_PROVIDER
            ),
            session_id="live-codex-synthetic-session",
            operation_call=call_operation,
            harness_adapter=self.adapter,
        )
        self.service.configure_evidence_gateway(
            fixtures={SourceFamily.LITERATURE: self._public_evidence_fixture()}
        )
        self.addCleanup(self.service.close)

    def _await_terminal(
        self, stage: str, submitted: dict[str, object]
    ) -> dict[str, object]:
        if submitted.get("status") != "in_progress":
            self._emit_stage(stage, submitted, None)
            return submitted
        job_id = str(submitted["job_id"])
        terminal = self.adapter.wait_for_background_job(
            job_id, timeout_seconds=900
        )
        self.assertIsNotNone(terminal)
        assert terminal is not None
        self.assertIn(terminal.state.value, {"completed", "failed"})
        deadline = time.monotonic() + 10
        durable = self.service.store.harness_job(job_id)
        while (
            isinstance(durable, dict)
            and durable.get("terminal_response") is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)
            durable = self.service.store.harness_job(job_id)
        self.assertIsInstance(durable, dict)
        assert durable is not None
        response = durable.get("terminal_response")
        self.assertIsInstance(response, dict, durable)
        assert isinstance(response, dict)
        self._emit_stage(stage, response, durable)
        self.assertEqual(response.get("status"), "accepted", response)
        return response

    def _emit_stage(
        self,
        stage: str,
        response: dict[str, object],
        durable_job: dict[str, object] | None,
    ) -> None:
        binding = response.get("binding")
        binding = binding if isinstance(binding, dict) else {}
        artifact = response.get("committed_artifact")
        artifact = artifact if isinstance(artifact, dict) else {}
        report = artifact.get("report")
        report = report if isinstance(report, dict) else {}
        artifact_kind = (
            artifact.get("kind")
            or ("plan" if isinstance(artifact.get("plan"), dict) else None)
            or ("brief_draft" if isinstance(artifact.get("brief"), dict) else None)
        )
        print(
            "GENOMILAB_LIVE_STAGE "
            + json.dumps(
                {
                    "stage": stage,
                    "status": response.get("status"),
                    "job_id": (durable_job or {}).get("job_id"),
                    "job_state": (durable_job or {}).get("job_state"),
                    "command_id": response.get("command_id"),
                    "thread_id": binding.get("task_id"),
                    "turn_id": binding.get("run_id"),
                    "artifact_kind": artifact_kind,
                    "request_results": report.get("request_results"),
                    "capability_result_count": len(
                        response.get("capability_results") or []
                    ),
                    "error": (response.get("harness_response") or {}).get("error")
                    if isinstance(response.get("harness_response"), dict)
                    else None,
                    "frozen_command": True,
                },
                sort_keys=True,
            ),
            flush=True,
        )

    def _approved_harness_call(
        self,
        investigation_id: str,
        *,
        stage: str,
        command_id: str,
        operation: str,
        artifact_kind: str,
        instruction: str | None = None,
        reason: str | None = None,
    ) -> dict[str, object]:
        preview = self.service.harness_disclosure_candidate(
            investigation_id,
            operation=operation,
            instruction=instruction,
            artifact_kind=artifact_kind,
            reason=reason,
            command_id=command_id,
        )
        self.assertEqual(preview["status"], "approval_required")
        command_context = preview["payload"]["command_context"]
        request: dict[str, object] = {
            "approved": True,
            "payload_sha256": preview["payload_sha256"],
            "command_id": command_context["command_id"],
            "expected_revision": command_context["expected_revision"],
        }
        if instruction is not None:
            request["message"] = instruction
        if reason is not None:
            request["reason"] = reason
        if operation == "start_task_run":
            submitted = self.service.start_investigation(
                investigation_id, request
            )
        elif operation == "send_task_message":
            request["artifact_kind"] = artifact_kind
            submitted = self.service.send_investigation_message(
                investigation_id, request
            )
        elif operation == "replace_task_binding":
            request["artifact_kind"] = artifact_kind
            submitted = self.service.replace_harness_binding(
                investigation_id, request
            )
        else:
            self.fail(f"unsupported live operation: {operation}")
        if submitted.get("status") == "in_progress":
            if operation == "start_task_run":
                duplicate = self.service.start_investigation(
                    investigation_id, dict(request)
                )
            elif operation == "send_task_message":
                duplicate = self.service.send_investigation_message(
                    investigation_id, dict(request)
                )
            else:
                duplicate = self.service.replace_harness_binding(
                    investigation_id, dict(request)
                )
            self.assertEqual(duplicate.get("job_id"), submitted.get("job_id"))
            self.assertEqual(duplicate.get("command_id"), command_id)
        return self._await_terminal(stage, submitted)

    def _accept_and_execute(
        self,
        investigation_id: str,
        *,
        stage: str,
        command_id: str,
        operation: str,
        instruction: str | None = None,
        reason: str | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        planned = self._approved_harness_call(
            investigation_id,
            stage=f"{stage}_planning",
            command_id=command_id,
            operation=operation,
            instruction=instruction,
            artifact_kind="plan",
            reason=reason,
        )
        current = self.service.investigation(investigation_id)[
            "current_plan_version"
        ]
        before_acceptance = self.service.investigation(investigation_id)
        self.assertEqual(before_acceptance["current_capability_executions"], [])
        evidence_ids_before_acceptance = [
            item["evidence_record_id"]
            for item in before_acceptance["current_evidence_records"]
        ]
        hypothesis_ids_before_acceptance = [
            item["hypothesis_id"]
            for item in before_acceptance["current_hypotheses"]
        ]
        accepted = self.service.accept_current_plan(
            investigation_id,
            {
                "approved": True,
                "plan_version_id": current["plan_version_id"],
                "plan_sha256": current["plan_sha256"],
            },
        )
        self.assertEqual(accepted["capability_results"], [])
        after_acceptance = self.service.investigation(investigation_id)
        self.assertEqual(after_acceptance["current_capability_executions"], [])
        self.assertEqual(
            [
                item["evidence_record_id"]
                for item in after_acceptance["current_evidence_records"]
            ],
            evidence_ids_before_acceptance,
        )
        self.assertEqual(
            [
                item["hypothesis_id"]
                for item in after_acceptance["current_hypotheses"]
            ],
            hypothesis_ids_before_acceptance,
        )
        action = accepted.get("next_harness_action")
        self.assertIsInstance(action, dict, accepted)
        assert isinstance(action, dict)
        executed = self._approved_harness_call(
            investigation_id,
            stage=f"{stage}_execution",
            command_id=f"{command_id}-execution",
            operation=str(action["operation"]),
            instruction=str(action["instruction"]),
            artifact_kind=str(action["artifact_kind"]),
            reason=str(action["reason"]),
        )
        return planned, executed

    def test_real_codex_cancel_running_turn_and_reject_stale_revision(self) -> None:
        command = HarnessCommand(
            operation=HarnessOperation.START_TASK_RUN,
            workspace_session_id="live-codex-cancel-session",
            command_id="live-codex-cancel-start",
            user_id="synthetic-live-cancel-user",
            investigation_id="synthetic-live-cancel-investigation",
            expected_revision=0,
            payload=StartTaskRunPayload(
                "Propose a tool-free investigation plan and delegate an independent review.",
                {
                    "disease_scope": "Synthetic cancellation condition",
                    "capability_catalog": {},
                },
            ),
        )
        submissions: list[object] = []
        identities: list[object] = []
        completions: list[object] = []
        submitted = self.adapter.dispatch_background(
            command,
            submission_callback=submissions.append,
            identity_callback=identities.append,
            completion_callback=lambda job_id, state, response: completions.append(
                (job_id, state, response)
            ),
        )
        duplicate = self.adapter.dispatch_background(
            command,
            submission_callback=submissions.append,
            identity_callback=identities.append,
            completion_callback=lambda *_: None,
        )
        self.assertEqual(duplicate.job_id, submitted.job_id)

        deadline = time.monotonic() + 30
        running = self.adapter.background_job(submitted.job_id)
        while (
            running is not None
            and (not running.task_id or not running.run_id)
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
            running = self.adapter.background_job(submitted.job_id)
        self.assertIsNotNone(running)
        assert running is not None
        self.assertIsNotNone(running.task_id)
        self.assertIsNotNone(running.run_id)

        activity_deadline = time.monotonic() + 90
        events = self.adapter.replay_events(
            command.investigation_id, after_cursor=0
        ).events
        while (
            not any(event.kind == HarnessEventKind.AGENT_STARTED for event in events)
            and time.monotonic() < activity_deadline
        ):
            time.sleep(0.05)
            events = self.adapter.replay_events(
                command.investigation_id, after_cursor=0
            ).events
        self.assertTrue(
            any(event.kind == HarnessEventKind.AGENT_STARTED for event in events),
            "live Codex turn never emitted an agent_started event before cancellation",
        )

        def cancel_command(*, command_id: str, expected_revision: int) -> HarnessCommand:
            return HarnessCommand(
                operation=HarnessOperation.CANCEL_TASK_WORK,
                workspace_session_id=command.workspace_session_id,
                command_id=command_id,
                user_id=command.user_id,
                investigation_id=command.investigation_id,
                task_id=running.task_id,
                run_id=running.run_id,
                binding_status=BindingStatus.RUNNING,
                latest_event_cursor=0,
                current_binding_revision=1,
                expected_revision=expected_revision,
                payload=CancelTaskWorkPayload("Synthetic user cancelled live work."),
            )

        stale = self.adapter.cancel_task_work(
            cancel_command(command_id="live-codex-cancel-stale", expected_revision=0)
        )
        self.assertFalse(stale.ok)
        self.assertIsNotNone(stale.error)
        assert stale.error is not None
        self.assertEqual(stale.error.code, HarnessErrorCode.REVISION_CONFLICT)
        self.assertEqual(stale.error.details["current_revision"], 1)

        exact_cancel = cancel_command(
            command_id="live-codex-cancel-confirmed", expected_revision=1
        )
        cancelled = self.adapter.cancel_task_work(exact_cancel)
        cancelled_duplicate = self.adapter.cancel_task_work(exact_cancel)
        self.assertTrue(cancelled.ok, cancelled.error)
        self.assertEqual(cancelled_duplicate, cancelled)
        self.assertIsNotNone(cancelled.result)
        assert cancelled.result is not None
        self.assertEqual(cancelled.result.outcome, CancellationOutcome.CANCELLED)
        terminal = self.adapter.wait_for_background_job(
            submitted.job_id, timeout_seconds=30
        )
        self.assertIsNotNone(terminal)
        assert terminal is not None
        self.assertEqual(terminal.state.value, "cancelled")
        self.assertEqual(len(completions), 1)
        events = self.adapter.replay_events(
            command.investigation_id, after_cursor=0
        ).events
        self.assertEqual(events[-1].kind, HarnessEventKind.CANCELLED)
        self.assertEqual(
            [event.cursor for event in events],
            sorted({event.cursor for event in events}),
        )
        print(
            "GENOMILAB_LIVE_CANCEL_SUMMARY "
            + json.dumps(
                {
                    "job_id": submitted.job_id,
                    "thread_id": running.task_id,
                    "turn_id": running.run_id,
                    "stale_error": stale.error.code.value,
                    "outcome": cancelled.result.outcome.value,
                    "event_types": [event.kind.value for event in events],
                    "exact_cancel_idempotent": cancelled_duplicate == cancelled,
                },
                sort_keys=True,
            ),
            flush=True,
        )

    def test_real_codex_synthetic_disease_investigation_vertical_slice(self) -> None:
        parsed, context = self._intake_current_user(
            e2e_support.PATIENT_A_VCF,
            nickname="Synthetic live Codex patient",
            source_name="synthetic-live-codex.vcf",
        )
        self.service.bootstrap_workspace()
        records = self._add_molecular_profile(self.service)
        investigation = self.service.create_investigation(
            {
                "question": (
                    "Investigate the synthetic neuromuscular condition using the "
                    "approved molecular profile. First propose exact requests for "
                    "investigation.project_profile, genomi.variant.resolve, and "
                    "public_evidence.retrieve when the catalog permits them."
                ),
                "disease_scope": "Synthetic neuromuscular condition",
            }
        )
        investigation_id = str(investigation["investigation_id"])
        snapshot = self._approve_patient_context(
            self.service, investigation_id, records
        )

        if os.environ.get("GENOMILAB_LIVE_STOP_AFTER_PLAN") == "1":
            planned = self._approved_harness_call(
                investigation_id,
                stage="evidence_planning",
                command_id="live-codex-evidence-plan",
                operation="start_task_run",
                artifact_kind="plan",
            )
            plan = planned["committed_artifact"]["plan"]
            events = self.service.replay_investigation_events(investigation_id)[
                "events"
            ]
            event_types = [event["event_type"] for event in events]
            self.assertIn("agent_started", event_types)
            print(
                "GENOMILAB_LIVE_PLANNING_SUMMARY "
                + json.dumps(
                    {
                        "investigation_id": investigation_id,
                        "patient_molecular_snapshot_id": snapshot[
                            "patient_molecular_snapshot_id"
                        ],
                        "plan_version_id": self.service.investigation(
                            investigation_id
                        )["current_plan_version"]["plan_version_id"],
                        "requested_capabilities": [
                            item["capability"]
                            for item in plan["capability_requests"]
                        ],
                        "event_counts": {
                            kind: event_types.count(kind)
                            for kind in sorted(set(event_types))
                        },
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            return

        evidence_plan, evidence_execution = self._accept_and_execute(
            investigation_id,
            stage="evidence",
            command_id="live-codex-evidence-plan",
            operation="start_task_run",
        )
        evidence_requests = {
            item["capability"]
            for item in evidence_plan["committed_artifact"]["plan"][
                "capability_requests"
            ]
        }
        self.assertEqual(
            evidence_requests,
            {
                "investigation.project_profile",
                "genomi.variant.resolve",
                "public_evidence.retrieve",
            },
        )
        self.assertEqual(len(evidence_execution["capability_results"]), 3)
        after_evidence = self.service.investigation(investigation_id)
        evidence_request_ids = {
            item["id"]
            for item in evidence_plan["committed_artifact"]["plan"][
                "capability_requests"
            ]
        }
        self.assertEqual(
            {
                item["request_id"]
                for item in after_evidence["current_capability_executions"]
            },
            evidence_request_ids,
        )
        self.assertTrue(
            all(
                len(item["attempts"]) == 1
                for item in after_evidence["current_capability_executions"]
            )
        )
        personal_records = [
            item
            for item in after_evidence["current_evidence_records"]
            if item["source_family"] == "personal_genome"
            and item["operation"] == "variant.resolve"
        ]
        literature_records = [
            item
            for item in after_evidence["current_evidence_records"]
            if item["source_family"] == "literature"
        ]
        self.assertEqual(len(personal_records), 1)
        self.assertEqual(len(literature_records), 1)

        relation_plan, relation_execution = self._accept_and_execute(
            investigation_id,
            stage="relation",
            command_id="live-codex-relation-plan",
            operation="replace_task_binding",
            instruction=(
                "Create a fresh tool-free plan with exactly one request for "
                "investigation.register_disease_relation, linking the eligible "
                "public evidence to the exact reported molecular finding."
            ),
            reason="Plan the typed relation after evidence was committed.",
        )
        self.assertEqual(
            [
                item["capability"]
                for item in relation_plan["committed_artifact"]["plan"][
                    "capability_requests"
                ]
            ],
            ["investigation.register_disease_relation"],
        )
        self.assertEqual(len(relation_execution["capability_results"]), 1)
        after_relation = self.service.investigation(investigation_id)
        self.assertEqual(
            len(
                [
                    item
                    for item in after_relation["current_evidence_records"]
                    if item["operation"]
                    == "investigation.register_disease_relation"
                ]
            ),
            1,
        )

        synthesis_plan, synthesis_execution = self._accept_and_execute(
            investigation_id,
            stage="synthesis",
            command_id="live-codex-synthesis-plan",
            operation="replace_task_binding",
            instruction=(
                "Create a fresh tool-free plan with exactly two requests: one "
                "investigation.register_hypothesis candidate mechanism grounded "
                "in the eligible relation and one investigation.register_gap for "
                "clinical confirmation."
            ),
            reason="Plan bounded synthesis after the relation was committed.",
        )
        self.assertEqual(
            {
                item["capability"]
                for item in synthesis_plan["committed_artifact"]["plan"][
                    "capability_requests"
                ]
            },
            {"investigation.register_hypothesis", "investigation.register_gap"},
        )
        self.assertEqual(len(synthesis_execution["capability_results"]), 2)

        brief = self._approved_harness_call(
            investigation_id,
            stage="brief",
            command_id="live-codex-brief",
            operation="send_task_message",
            instruction=(
                "Draft a patient-friendly traceable research brief from the "
                "approved profile, evidence, candidate, and gap. Preserve the "
                "required clinical boundary."
            ),
            artifact_kind="brief_draft",
        )
        self.assertEqual(brief["committed_artifact"]["version"], 1)
        self.assertEqual(
            brief["committed_artifact"]["brief"]["clinical_boundary"],
            "Research support only; this is not a diagnosis or treatment decision.",
        )

        saved = self.service.investigation(investigation_id)
        events = self.service.replay_investigation_events(investigation_id)[
            "events"
        ]
        event_types = [event["event_type"] for event in events]
        self.assertIn("agent_started", event_types)
        self.assertGreaterEqual(event_types.count("evidence_returned"), 6)
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(len(saved["current_evidence_records"]), 3)
        self.assertEqual(len(saved["current_hypotheses"]), 2)
        self.assertIsNotNone(saved["current_brief_version"])
        self.assertEqual(len(saved["plan_versions"]), 3)
        self.assertEqual(len(saved["capability_executions"]), 6)
        self.assertEqual(
            len(
                {
                    (item["plan_version_id"], item["request_id"])
                    for item in saved["capability_executions"]
                }
            ),
            6,
        )
        self.assertTrue(
            all(len(item["attempts"]) == 1 for item in saved["capability_executions"])
        )
        self.assertEqual(
            len(
                {
                    item["evidence_record_id"]
                    for item in saved["current_evidence_records"]
                }
            ),
            3,
        )
        self.assertEqual(len(saved["brief_versions"]), 1)
        summary: dict[str, Any] = {
            "binary": str(CODEX_BINARY),
            "host_version": self.adapter.manifest.host_version,
            "processing_destination": self.adapter.manifest.execution_location,
            "user_id": context["active_user_id"],
            "agi_id": parsed["active_genome_index"]["agi_id"],
            "agi_snapshot_id": parsed["active_genome_index"]["agi_snapshot_id"],
            "investigation_id": investigation_id,
            "patient_molecular_snapshot_id": snapshot[
                "patient_molecular_snapshot_id"
            ],
            "plan_version_count": len(saved["plan_versions"]),
            "capability_execution_count": len(saved["capability_executions"]),
            "evidence_record_ids": [
                item["evidence_record_id"]
                for item in saved["current_evidence_records"]
            ],
            "hypothesis_ids": [
                item["hypothesis_id"] for item in saved["current_hypotheses"]
            ],
            "brief_version_id": saved["current_brief_version"][
                "brief_version_id"
            ],
            "event_counts": {
                kind: event_types.count(kind) for kind in sorted(set(event_types))
            },
            "binding_ids": [
                item["binding_id"] for item in saved["harness_bindings"]
            ],
        }
        print(
            "GENOMILAB_LIVE_SUMMARY "
            + json.dumps(summary, sort_keys=True),
            flush=True,
        )
