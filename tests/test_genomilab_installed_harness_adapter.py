from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from typing import Any

from genomi.lab.harness import (
    CancelTaskWorkPayload,
    CancellationOutcome,
    HarnessArtifactKind,
    BindingStatus,
    HarnessEventKind,
    HarnessOperation,
    HarnessDynamicToolCall,
    InstalledCodexAppServerAdapter,
    ReplaceTaskBindingPayload,
    ResumeTaskRunPayload,
    SimulatedHarnessAdapter,
)
from genomi.lab import harness_codex as codex_adapter
from genomi.lab.harness_artifacts import BRIEF_SCHEMA


from tests.genomilab_harness_adapter_support import (
    _BlockingAppServerTransport,
    _FakeAppServerTransport,
    _app_server_runner,
    _completed_turn,
    _plan_artifact,
)
from tests.test_genomilab_harness_adapter import _bound_command, _start_command

class InstalledCodexAppServerAdapterTests(unittest.TestCase):
    def _adapter_with_transports(
        self, transports: list[_FakeAppServerTransport]
    ) -> InstalledCodexAppServerAdapter:
        def factory(*_: Any) -> _FakeAppServerTransport:
            if not transports:
                raise AssertionError("unexpected transport creation")
            return transports.pop(0)

        return InstalledCodexAppServerAdapter(
            "/opt/codex/bin/codex",
            host_version="codex 9.9.9",
            processing_destination="remote: OpenAI Codex service",
            transport_factory=factory,
            timeout_seconds=2,
        )

    def test_discovery_handshakes_without_a_model_turn(self) -> None:
        calls: list[list[str]] = []
        handshake = _FakeAppServerTransport(
            [{"$reply": "initialize", "result": {"userAgent": "codex-test"}}]
        )

        def runner(
            command: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return _app_server_runner(command, **kwargs)

        adapter = InstalledCodexAppServerAdapter.discover(
            which=lambda _: "/opt/codex/bin/codex",
            runner=runner,
            transport_factory=lambda *_: handshake,
            processing_destination="remote: OpenAI Codex service",
        )

        self.assertEqual(
            calls,
            [
                ["/opt/codex/bin/codex", "--version"],
                ["/opt/codex/bin/codex", "app-server", "--help"],
            ],
        )
        self.assertTrue(adapter.manifest.available)
        self.assertEqual(adapter.manifest.adapter_id, "codex-app-server")
        self.assertEqual(adapter.manifest.host_kind, "codex_app_server")
        self.assertTrue(adapter.manifest.event_streaming)
        self.assertTrue(adapter.manifest.event_replay)
        self.assertTrue(adapter.manifest.agent_delegation_event_reporting)
        self.assertTrue(adapter.manifest.background_job_attach)
        self.assertTrue(adapter.manifest.background_job_cancel)
        self.assertTrue(handshake.closed)
        self.assertEqual(handshake.sent[0]["method"], "initialize")
        self.assertEqual(handshake.sent[1], {"method": "initialized"})

    def test_brief_wire_schema_omits_deterministic_modality_metadata(self) -> None:
        schema = codex_adapter._artifact_schema(  # noqa: SLF001
            HarnessArtifactKind.BRIEF_DRAFT
        )
        self.assertNotIn("modality_badges", schema["properties"])
        self.assertNotIn("modality_badges", schema["required"])
        self.assertNotIn("const", schema["properties"]["clinical_boundary"])
        self.assertNotIn("uniqueItems", schema["properties"]["claims"])

    def test_brief_wire_schema_exposes_exact_typed_hypothesis_and_gap_ids(self) -> None:
        schema = codex_adapter._artifact_schema(  # noqa: SLF001
            HarnessArtifactKind.BRIEF_DRAFT,
            {
                "evidence_records": [
                    {
                        "evidence_record_id": "evidence-a",
                        "source_family": "literature",
                    },
                    {
                        "evidence_record_id": "evidence-b",
                        "source_family": "personal_genome",
                    },
                ],
                "molecular_profile": {
                    "observations": [
                        {
                            "observation_revision_id": "observation-a",
                            "source_class": "issued_record",
                        },
                        {
                            "observation_revision_id": "observation-b",
                            "source_class": "patient_reported",
                        },
                    ]
                },
                "hypotheses": [
                    {
                        "hypothesis_id": "hypothesis-candidate",
                        "kind": "candidate_mechanism",
                    },
                    {
                        "hypothesis_id": "hypothesis-confirmation",
                        "kind": "confirmation_requirement",
                    },
                    {
                        "hypothesis_id": "hypothesis-gap",
                        "kind": "evidence_gap",
                    },
                ]
            },
        )

        self.assertEqual(
            schema["properties"]["hypothesis_ids"]["items"]["enum"],
            ["hypothesis-candidate"],
        )
        self.assertEqual(
            schema["properties"]["gap_ids"]["items"]["enum"],
            ["hypothesis-confirmation", "hypothesis-gap"],
        )
        self.assertEqual(
            schema["properties"]["claims"]["items"]["properties"]["claim_role"][
                "enum"
            ],
            ["observation", "candidate_hypothesis", "limitation"],
        )
        claim_properties = schema["properties"]["claims"]["items"]["properties"]
        self.assertEqual(
            claim_properties["evidence_record_ids"]["items"]["enum"],
            ["evidence-a", "evidence-b"],
        )
        self.assertEqual(
            claim_properties["profile_revision_ids"]["items"]["enum"],
            ["observation-a", "observation-b"],
        )
        self.assertNotIn(
            "enum", BRIEF_SCHEMA["properties"]["gap_ids"]["items"]
        )

    def test_brief_wire_schema_closes_empty_and_one_sided_typed_id_sets(self) -> None:
        empty = codex_adapter._artifact_schema(  # noqa: SLF001
            HarnessArtifactKind.BRIEF_DRAFT, {}
        )
        self.assertEqual(empty["properties"]["hypothesis_ids"]["maxItems"], 0)
        self.assertEqual(empty["properties"]["gap_ids"]["maxItems"], 0)
        empty_claim = empty["properties"]["claims"]["items"]["properties"]
        self.assertEqual(empty_claim["evidence_record_ids"]["maxItems"], 0)
        self.assertEqual(empty_claim["profile_revision_ids"]["maxItems"], 0)
        self.assertEqual(
            empty["properties"]["claims"]["items"]["properties"]["claim_role"][
                "enum"
            ],
            ["observation", "limitation"],
        )

        counterevidence_only = codex_adapter._artifact_schema(  # noqa: SLF001
            HarnessArtifactKind.BRIEF_DRAFT,
            {
                "hypotheses": [
                    {
                        "hypothesis_id": "hypothesis-counterevidence",
                        "kind": "counterevidence",
                    }
                ]
            },
        )
        self.assertEqual(
            counterevidence_only["properties"]["hypothesis_ids"]["items"]["enum"],
            ["hypothesis-counterevidence"],
        )
        self.assertEqual(counterevidence_only["properties"]["gap_ids"]["maxItems"], 0)
        self.assertEqual(
            counterevidence_only["properties"]["claims"]["items"]["properties"][
                "claim_role"
            ]["enum"],
            ["observation", "counterevidence", "limitation"],
        )

    def test_local_brief_validation_enforces_context_typed_ids_and_claim_roles(
        self,
    ) -> None:
        context = {
            "evidence_records": [
                {
                    "evidence_record_id": "evidence-a",
                    "source_family": "literature",
                }
            ],
            "molecular_profile": {
                "observations": [
                    {
                        "observation_revision_id": "observation-a",
                        "source_class": "issued_record",
                    }
                ]
            },
            "hypotheses": [
                {
                    "hypothesis_id": "hypothesis-candidate",
                    "kind": "candidate_mechanism",
                },
                {
                    "hypothesis_id": "hypothesis-confirmation",
                    "kind": "confirmation_requirement",
                },
            ]
        }
        brief = {
            "title": "Synthetic brief",
            "summary": "Synthetic summary",
            "clinical_stage": "candidate_hypothesis",
            "modality_badges": ["public_source", "reported_record"],
            "claims": [
                {
                    "statement": "A bounded candidate is recorded.",
                    "claim_role": "candidate_hypothesis",
                    "evidence_record_ids": ["evidence-a"],
                    "profile_revision_ids": ["observation-a"],
                }
            ],
            "hypothesis_ids": ["hypothesis-candidate"],
            "gap_ids": ["hypothesis-confirmation"],
            "confirmation_needs": [],
            "professional_questions": [],
            "clinical_boundary": (
                "Research support only; this is not a diagnosis or treatment decision."
            ),
            "change_summary": "Initial brief.",
        }
        InstalledCodexAppServerAdapter._validate_artifact(  # noqa: SLF001
            HarnessArtifactKind.BRIEF_DRAFT, brief, context
        )

        swapped = {**brief, "gap_ids": ["hypothesis-candidate"]}
        with self.assertRaisesRegex(ValueError, "approved typed set"):
            InstalledCodexAppServerAdapter._validate_artifact(  # noqa: SLF001
                HarnessArtifactKind.BRIEF_DRAFT, swapped, context
            )

        unsupported_role = {
            **brief,
            "claims": [{**brief["claims"][0], "claim_role": "counterevidence"}],
        }
        with self.assertRaisesRegex(ValueError, "claim_role"):
            InstalledCodexAppServerAdapter._validate_artifact(  # noqa: SLF001
                HarnessArtifactKind.BRIEF_DRAFT, unsupported_role, context
            )

        unsupported_anchor = {
            **brief,
            "claims": [
                {
                    **brief["claims"][0],
                    "evidence_record_ids": ["evidence-outside-context"],
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "outside the approved context"):
            InstalledCodexAppServerAdapter._validate_artifact(  # noqa: SLF001
                HarnessArtifactKind.BRIEF_DRAFT, unsupported_anchor, context
            )

    def test_brief_wire_decode_derives_exact_badges_without_labeling_agent_inference(
        self,
    ) -> None:
        context = {
            "evidence_records": [
                {
                    "evidence_record_id": "evidence-relation",
                    "source_family": "literature",
                }
            ],
            "molecular_profile": {
                "observations": [
                    {
                        "observation_revision_id": "observation-finding",
                        "source_class": "issued_record",
                        "assay_id": "assay-a",
                    }
                ]
            },
            "hypotheses": [
                {
                    "hypothesis_id": "hypothesis-agent-inference",
                    "kind": "candidate_mechanism",
                }
            ],
        }
        wire = {
            "title": "Synthetic brief",
            "summary": "A candidate inference remains bounded research support.",
            "clinical_stage": "candidate_hypothesis",
            "claims": [
                {
                    "statement": "Model inference: this remains a candidate mechanism.",
                    "claim_role": "candidate_hypothesis",
                    "evidence_record_ids": ["evidence-relation"],
                    "profile_revision_ids": ["observation-finding"],
                }
            ],
            "hypothesis_ids": ["hypothesis-agent-inference"],
            "gap_ids": [],
            "confirmation_needs": [],
            "professional_questions": [],
            "clinical_boundary": (
                "Research support only; this is not a diagnosis or treatment decision."
            ),
            "change_summary": "Initial brief.",
        }

        decoded = codex_adapter._decode_wire_artifact(  # noqa: SLF001
            HarnessArtifactKind.BRIEF_DRAFT,
            wire,
            approved_context=context,
        )

        self.assertEqual(
            decoded["modality_badges"],
            ["laboratory_assay", "public_source", "reported_record"],
        )
        self.assertEqual(decoded["title"], wire["title"])
        self.assertEqual(decoded["claims"], wire["claims"])
        self.assertEqual(decoded["summary"], wire["summary"])
        self.assertEqual(decoded["confirmation_needs"], wire["confirmation_needs"])
        self.assertNotIn("computational_model_prediction", decoded["modality_badges"])

    def test_brief_wire_decode_does_not_replace_harness_reasoning(self) -> None:
        wire = {
            "title": "Proposed investigation brief",
            "summary": "The approved record remains a research observation.",
            "clinical_stage": "research_observation",
            "claims": [
                {
                    "statement": (
                        "Source evidence: The source evidence records a research observation."
                    ),
                    "claim_role": "observation",
                    "evidence_record_ids": ["evidence-source"],
                    "profile_revision_ids": [],
                }
            ],
            "hypothesis_ids": [],
            "gap_ids": [],
            "confirmation_needs": [],
            "professional_questions": ["Is this diagnostic?"],
            "clinical_boundary": (
                "Research support only; this is not a diagnosis or treatment decision."
            ),
            "change_summary": "Prepared a traceable research brief.",
        }
        decoded = codex_adapter._decode_wire_artifact(  # noqa: SLF001
            HarnessArtifactKind.BRIEF_DRAFT,
            wire,
            approved_context={
                "evidence_records": [
                    {
                        "evidence_record_id": "evidence-source",
                        "source_family": "literature",
                    }
                ]
            },
        )

        self.assertEqual(
            {key: decoded[key] for key in wire},
            wire,
        )
        self.assertEqual(decoded["modality_badges"], ["public_source"])

    def test_brief_wire_decode_labels_selected_model_evidence(self) -> None:
        context = {
            "evidence_records": [
                {
                    "evidence_record_id": "evidence-model",
                    "source_family": "computational_model",
                }
            ]
        }
        wire = {
            "title": "Synthetic model brief",
            "summary": "A model output was recorded.",
            "clinical_stage": "research_observation",
            "claims": [
                {
                    "statement": "A computational result was recorded.",
                    "claim_role": "observation",
                    "evidence_record_ids": ["evidence-model"],
                    "profile_revision_ids": [],
                }
            ],
            "hypothesis_ids": [],
            "gap_ids": [],
            "confirmation_needs": [],
            "professional_questions": [],
            "clinical_boundary": (
                "Research support only; this is not a diagnosis or treatment decision."
            ),
            "change_summary": "Initial brief.",
        }

        decoded = codex_adapter._decode_wire_artifact(  # noqa: SLF001
            HarnessArtifactKind.BRIEF_DRAFT,
            wire,
            approved_context=context,
        )

        self.assertEqual(
            decoded["modality_badges"], ["computational_model_prediction"]
        )

    def test_simulated_brief_classifies_confirmation_requirement_as_gap(self) -> None:
        context = {
            "hypotheses": [
                {
                    "hypothesis_id": "hypothesis-confirmation",
                    "kind": "confirmation_requirement",
                    "evidence_record_ids": [],
                    "profile_revision_ids": ["observation-a"],
                }
            ],
            "molecular_profile": {
                "observations": [
                    {"observation_revision_id": "observation-a"}
                ]
            },
        }
        host_artifact = SimulatedHarnessAdapter()._produce_artifact(  # noqa: SLF001
            HarnessArtifactKind.BRIEF_DRAFT,
            _start_command(approved_context=context),
            "Summarize the bounded record.",
            context,
            resume_task_id=None,
        )

        self.assertEqual(list(host_artifact.artifact["hypothesis_ids"]), [])
        self.assertEqual(
            list(host_artifact.artifact["gap_ids"]), ["hypothesis-confirmation"]
        )

    def test_plan_boundary_sentence_does_not_create_cross_sentence_false_positive(
        self,
    ) -> None:
        plan = _plan_artifact()
        plan["summary"] = (
            "The plan uses the unchanged supports template. "
            "No diagnosis or treatment conclusion is made."
        )
        plan["capability_requests"][0]["parameters"] = {}

        InstalledCodexAppServerAdapter._validate_artifact(  # noqa: SLF001
            HarnessArtifactKind.PLAN,
            plan,
        )

    def test_missing_destination_or_binary_is_unavailable(self) -> None:
        handshake = _FakeAppServerTransport(
            [{"$reply": "initialize", "result": {"userAgent": "codex-test"}}]
        )
        without_destination = InstalledCodexAppServerAdapter.discover(
            which=lambda _: "/opt/codex/bin/codex",
            runner=_app_server_runner,
            transport_factory=lambda *_: handshake,
        )
        missing = InstalledCodexAppServerAdapter.discover(which=lambda _: None)
        self.assertFalse(without_destination.manifest.available)
        self.assertIn(
            "destination", without_destination.manifest.unavailable_reason or ""
        )
        self.assertFalse(missing.manifest.available)

    def test_planning_turn_is_tool_free_and_preserves_real_delegation(
        self,
    ) -> None:
        plan = _plan_artifact()
        transport = _FakeAppServerTransport(
            [
                {"$reply": "initialize", "result": {"userAgent": "codex-test"}},
                {
                    "$reply": "thread/start",
                    "result": {"thread": {"id": "codex-thread-a"}},
                },
                {"$reply": "turn/start", "result": {"turn": {"id": "turn-a"}}},
                {
                    "method": "item/started",
                    "params": {
                        "threadId": "codex-thread-a",
                        "turnId": "turn-a",
                        "item": {
                            "type": "collabAgentToolCall",
                            "id": "collab-a",
                            "tool": "spawnAgent",
                            "status": "inProgress",
                            "senderThreadId": "codex-thread-a",
                            "receiverThreadIds": ["codex-subagent-a"],
                            "prompt": "Review limitations",
                            "model": None,
                            "reasoningEffort": None,
                            "agentsStates": {},
                        },
                    },
                },
                _completed_turn("turn-a", plan),
            ]
        )
        adapter = self._adapter_with_transports([transport])
        command = _start_command(
            approved_context={
                "capability_catalog": {
                    "investigation.project_profile": {
                        "available": True,
                        "parameters": {},
                    },
                    "not.available": {"available": False},
                }
            }
        )

        response = adapter.start_task_run(command)

        self.assertTrue(
            response.ok,
            response.error.to_dict() if response.error is not None else response,
        )
        assert response.result is not None
        self.assertEqual(response.result.task_id, "codex-thread-a")
        self.assertEqual(response.result.run_id, "turn-a")
        self.assertEqual(
            response.result.proposed_artifact["capability_requests"][0]["parameters"],
            {},
        )
        start = next(
            item for item in transport.sent if item.get("method") == "thread/start"
        )
        params = start["params"]
        self.assertEqual(params["approvalPolicy"], "never")
        self.assertEqual(params["sandbox"], "read-only")
        self.assertEqual(params["runtimeWorkspaceRoots"], [])
        self.assertEqual(params["environments"], [])
        self.assertEqual(params["dynamicTools"], [])
        turn = next(
            item for item in transport.sent if item.get("method") == "turn/start"
        )
        parameter_schema = turn["params"]["outputSchema"]["properties"][
            "capability_requests"
        ]["items"]["properties"]["parameters"]
        self.assertEqual(parameter_schema["type"], "string")
        command_line = adapter._app_server_command()
        for disabled in (
            "shell_tool",
            "unified_exec",
            "browser_use",
            "apps",
            "plugins",
        ):
            self.assertIn(disabled, command_line)
        replay = adapter.replay_events("investigation-a", after_cursor=0)
        self.assertEqual(
            [event.kind for event in replay.events],
            [HarnessEventKind.AGENT_STARTED, HarnessEventKind.PLAN_PROPOSED],
        )

    def test_dynamic_tool_routes_identity_only_and_preserves_approval_required(
        self,
    ) -> None:
        plan = _plan_artifact()
        execution_report = {
            "summary": "The exact accepted request was paused for approval.",
            "request_results": [
                {
                    "request_id": "request-profile",
                    "capability": "investigation.project_profile",
                    "status": "approval_required",
                }
            ],
        }
        planning_transport = _FakeAppServerTransport(
            [
                {"$reply": "initialize", "result": {"userAgent": "codex-test"}},
                {
                    "$reply": "thread/start",
                    "result": {"thread": {"id": "codex-thread-planning"}},
                },
                {"$reply": "turn/start", "result": {"turn": {"id": "turn-planning"}}},
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "codex-thread-planning",
                        "turn": {
                            "id": "turn-planning",
                            "status": "completed",
                            "items": [
                                {
                                    "type": "agentMessage",
                                    "id": "message-planning",
                                    "text": json.dumps(plan),
                                    "phase": "final_answer",
                                    "memoryCitation": None,
                                }
                            ],
                        },
                    },
                },
            ]
        )
        transport = _FakeAppServerTransport(
            [
                {"$reply": "initialize", "result": {"userAgent": "codex-test"}},
                {
                    "$reply": "thread/start",
                    "result": {"thread": {"id": "codex-thread-a"}},
                },
                {"$reply": "turn/start", "result": {"turn": {"id": "turn-a"}}},
                {
                    "method": "item/tool/call",
                    "id": 99,
                    "params": {
                        "threadId": "codex-thread-a",
                        "turnId": "turn-a",
                        "callId": "tool-call-a",
                        "namespace": "genomilab",
                        "tool": "investigation__project_profile",
                        "arguments": {"request_id": "request-profile"},
                    },
                },
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "codex-thread-a",
                        "turn": {
                            "id": "turn-a",
                            "status": "completed",
                            "items": [
                                {
                                    "type": "agentMessage",
                                    "id": "message-execution",
                                    "text": json.dumps(execution_report),
                                    "phase": "final_answer",
                                    "memoryCitation": None,
                                }
                            ],
                        },
                    },
                },
            ]
        )
        adapter = self._adapter_with_transports([planning_transport, transport])
        received: list[HarnessDynamicToolCall] = []

        def handler(call: HarnessDynamicToolCall) -> dict[str, Any]:
            received.append(call)
            return {
                "status": "approval_required",
                "candidate": {"payload_sha256": "a" * 64},
            }

        adapter.bind_dynamic_tool_handler(handler)
        started = adapter.start_task_run(_start_command())
        self.assertTrue(started.ok)
        assert started.result is not None
        response = adapter.replace_task_binding(
            _bound_command(
                HarnessOperation.REPLACE_TASK_BINDING,
                command_id="command-execute",
                task_id=started.result.task_id,
                run_id=started.result.run_id,
                expected_revision=1,
                payload=ReplaceTaskBindingPayload(
                    "Execute the accepted plan in a request-scoped task.",
                    "Execute the exact accepted request.",
                    {
                        "accepted_plan": {
                            "plan_version_id": "plan-a",
                            "plan_sha256": "a" * 64,
                            "plan_acceptance_id": "acceptance-a",
                            "accepted_at": "2026-08-12T00:00:00+00:00",
                            "patient_molecular_snapshot_id": "snapshot-a",
                            "plan": plan,
                        },
                        "capability_catalog": {
                            "investigation.project_profile": {
                                "available": True,
                                "parameters": {},
                            }
                        },
                    },
                    HarnessArtifactKind.EXECUTION_REPORT,
                ),
            )
        )

        self.assertTrue(response.ok)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].request_id, "request-profile")
        self.assertEqual(received[0].capability, "investigation.project_profile")
        tool_reply = next(item for item in transport.sent if item.get("id") == 99)
        self.assertTrue(tool_reply["result"]["success"])
        tool_payload = json.loads(tool_reply["result"]["contentItems"][0]["text"])
        self.assertEqual(tool_payload["status"], "approval_required")
        replay = adapter.replay_events("investigation-a", after_cursor=0)
        self.assertIn(
            HarnessEventKind.APPROVAL_REQUIRED,
            [event.kind for event in replay.events],
        )

    def test_current_catalog_can_evolve_without_replacing_the_codex_thread(
        self,
    ) -> None:
        first_transport = _FakeAppServerTransport(
            [
                {"$reply": "initialize", "result": {}},
                {
                    "$reply": "thread/start",
                    "result": {"thread": {"id": "codex-thread-a"}},
                },
                {"$reply": "turn/start", "result": {"turn": {"id": "turn-a"}}},
                _completed_turn("turn-a", _plan_artifact()),
            ]
        )
        second_transport = _FakeAppServerTransport(
            [
                {"$reply": "initialize", "result": {}},
                {
                    "$reply": "thread/resume",
                    "result": {"thread": {"id": "codex-thread-a"}},
                },
                {"$reply": "turn/start", "result": {"turn": {"id": "turn-b"}}},
                _completed_turn("turn-b", _plan_artifact()),
            ]
        )
        adapter = self._adapter_with_transports([first_transport, second_transport])
        started = adapter.start_task_run(
            _start_command(
                approved_context={
                    "capability_catalog": {
                        "investigation.project_profile": {"available": True}
                    }
                }
            )
        )
        assert started.result is not None
        resumed = adapter.resume_task_run(
            _bound_command(
                HarnessOperation.RESUME_TASK_RUN,
                command_id="changed-catalog",
                task_id=started.result.task_id,
                run_id=started.result.run_id,
                expected_revision=1,
                payload=ResumeTaskRunPayload(
                    "Continue the disease investigation with the updated current capability catalog",
                    {"capability_catalog": {"different": {"available": True}}},
                ),
            )
        )
        self.assertTrue(resumed.ok, resumed.error)
        assert resumed.result is not None
        self.assertEqual(resumed.result.task_id, started.result.task_id)
        self.assertEqual(resumed.result.run_id, "turn-b")
        resume_request = next(
            item
            for item in second_transport.sent
            if item.get("method") == "thread/resume"
        )
        self.assertEqual(resume_request["params"]["threadId"], "codex-thread-a")

    def test_background_turn_streams_real_identity_and_confirms_interrupt(self) -> None:
        transport = _BlockingAppServerTransport(
            [
                {"$reply": "initialize", "result": {}},
                {
                    "$reply": "thread/start",
                    "result": {"thread": {"id": "codex-thread-a"}},
                },
                {"$reply": "turn/start", "result": {"turn": {"id": "turn-a"}}},
            ]
        )
        adapter = self._adapter_with_transports([transport])
        identities = []
        completions = []
        command = _start_command(command_id="command-background")

        submitted = adapter.dispatch_background(
            command,
            submission_callback=lambda _submission: None,
            identity_callback=identities.append,
            completion_callback=lambda job_id, state, response: completions.append(
                (job_id, state, response)
            ),
        )
        self.assertIn(submitted.state.value, {"queued", "running"})
        self.assertTrue(transport.turn_started.wait(1))
        running = adapter.background_job(submitted.job_id)
        assert running is not None
        self.assertEqual(running.state.value, "running")
        self.assertEqual(running.task_id, "codex-thread-a")
        self.assertEqual(running.run_id, "turn-a")
        self.assertTrue(
            adapter.wait_for_events(
                "investigation-a", after_cursor=0, timeout_seconds=1
            )
        )
        replay = adapter.replay_events("investigation-a", after_cursor=0)
        self.assertEqual(replay.events[0].kind, HarnessEventKind.JOB_IN_PROGRESS)
        self.assertEqual(replay.events[0].job_id, submitted.job_id)

        cancelled = adapter.cancel_task_work(
            _bound_command(
                HarnessOperation.CANCEL_TASK_WORK,
                command_id="command-cancel-background",
                task_id="codex-thread-a",
                run_id="turn-a",
                expected_revision=1,
                binding_status=BindingStatus.RUNNING,
                payload=CancelTaskWorkPayload("User requested cancellation"),
            )
        )
        self.assertTrue(cancelled.ok)
        assert cancelled.result is not None
        self.assertEqual(cancelled.result.outcome, CancellationOutcome.CANCELLED)
        self.assertTrue(transport.interrupt_requested.is_set())
        terminal = adapter.wait_for_background_job(submitted.job_id, timeout_seconds=1)
        assert terminal is not None
        self.assertEqual(terminal.state.value, "cancelled")
        self.assertEqual(len(identities), 1)
        self.assertEqual(len(completions), 1)
        interrupt = next(
            item for item in transport.sent if item.get("method") == "turn/interrupt"
        )
        self.assertEqual(
            interrupt["params"],
            {"threadId": "codex-thread-a", "turnId": "turn-a"},
        )
        replay = adapter.replay_events("investigation-a", after_cursor=0)
        self.assertEqual(
            [event.kind for event in replay.events],
            [HarnessEventKind.JOB_IN_PROGRESS, HarnessEventKind.CANCELLED],
        )

    def test_installed_binary_app_server_handshake_without_live_model(self) -> None:
        executable = shutil.which("codex")
        if executable is None:
            candidate = "/Applications/ChatGPT.app/Contents/Resources/codex"
            executable = candidate if os.path.isfile(candidate) else None
        if executable is None:
            self.skipTest("installed Codex binary is unavailable")
        adapter = InstalledCodexAppServerAdapter.discover(
            executable_name=executable,
            which=lambda value: value,
            processing_destination="remote: OpenAI Codex service",
            timeout_seconds=20,
        )
        self.assertTrue(
            adapter.manifest.available,
            adapter.manifest.unavailable_reason,
        )
        self.assertEqual(adapter.manifest.host_kind, "codex_app_server")
