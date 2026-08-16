from __future__ import annotations

import copy
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from jsonschema import ValidationError, validate

from genomi.lab import operations as lab_operations
from genomi.lab.store import GenomiLabStore
from genomi.operations import OperationError
from genomi.operations.registry.table import call_operation, list_operations
from genomi.runtime import context as runtime_context


CLINICAL_BOUNDARY = (
    "Research support only; this is not a diagnosis or treatment decision."
)


class LabPublishBriefContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(Path(self._temporary_home.name) / "home"),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "lab-publish-brief-contract-tests",
                "GENOMI_MCP_BACKGROUND": "0",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)

    def test_publish_schema_rejects_incomplete_or_unanchored_briefs(self) -> None:
        schema = self._publish_schema()
        valid = {
            "investigation_id": "investigation-example",
            "cycle_id": "cycle-example",
            "brief": {
                "title": "Clinician discussion brief",
                "summary": "Current observations support a bounded discussion.",
                "claims": [
                    {
                        "statement": "The current profile records two reported observations.",
                        "evidence_record_ids": [],
                        "profile_revision_ids": ["observation-revision-example"],
                    }
                ],
                "hypothesis_ids": ["logical-hypothesis-example"],
                "gap_ids": ["logical-hypothesis-gap"],
                "confirmation_needs": ["Independent clinical assessment"],
                "professional_questions": [
                    "Which clinical measurements would help distinguish the alternatives?"
                ],
                "clinical_boundary": CLINICAL_BOUNDARY,
            },
            "command_id": "publish-example",
            "expected_revision": 4,
        }
        validate(instance=valid, schema=schema)

        missing_boundary = copy.deepcopy(valid)
        del missing_boundary["brief"]["clinical_boundary"]
        with self.assertRaises(ValidationError):
            validate(instance=missing_boundary, schema=schema)

        unanchored = copy.deepcopy(valid)
        unanchored["brief"]["claims"][0]["profile_revision_ids"] = []
        with self.assertRaises(ValidationError):
            validate(instance=unanchored, schema=schema)

        wrong_boundary = copy.deepcopy(valid)
        wrong_boundary["brief"]["clinical_boundary"] = "For diagnosis."
        with self.assertRaises(ValidationError):
            validate(instance=wrong_boundary, schema=schema)

    def test_genomi_invoke_publishes_the_declared_clinician_brief_shape(self) -> None:
        store = GenomiLabStore()
        store.open_workspace("user-a", "Synthetic user")
        created = store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question=(
                "Could persistent exercise-associated fatigue and disrupted sleep "
                "have a shared explanation?"
            ),
            command_id="create-investigation",
        )
        investigation_id = str(created["investigation"]["investigation_id"])
        updated = store.update_health_profile(
            "user-a",
            investigation_id,
            workspace_session_id="session-a",
            facts=[
                {
                    "modality": "phenotype",
                    "label": "Exercise-associated fatigue",
                    "original_wording": "I remain unusually tired after ordinary exercise.",
                },
                {
                    "modality": "phenotype",
                    "label": "Disrupted sleep",
                    "original_wording": "My sleep has been repeatedly interrupted.",
                },
            ],
            purpose="Record the reported observations",
            command_id="update-profile",
            expected_revision=1,
        )
        cycle = store.create_investigation_cycle(
            investigation_id,
            purpose="Assess shared and independent explanations",
            command_id="create-cycle",
            expected_revision=updated["domain_revision"],
        )
        cycle_id = str(cycle["cycle"]["cycle_id"])
        candidate = store.create_hypothesis(
            investigation_id,
            cycle_id=cycle_id,
            statement=(
                "The two reported patterns may share a physiological explanation."
            ),
            status="open",
            profile_snapshot_id=None,
            evidence_snapshot_id=None,
            supporting_evidence_record_ids=[],
            contradicting_evidence_record_ids=[],
            contextual_evidence_record_ids=[],
            unresolved_gaps=["Objective clinical measurements have not been reviewed"],
            revision_rationale="Keep a shared explanation open for comparison.",
            category="shared_explanation",
            command_id="create-shared-hypothesis",
            expected_revision=cycle["domain_revision"],
        )

        @contextmanager
        def authorized_store():
            yield store, "user-a", "session-a"

        with mock.patch.object(
            lab_operations, "_authorized_store", authorized_store
        ):
            with self.assertRaisesRegex(
                OperationError, "must describe missing or unresolved information"
            ):
                call_operation(
                    "genomi.invoke",
                    {
                        "tool": "lab.create_information_gap",
                        "params": {
                            "investigation_id": investigation_id,
                            "cycle_id": cycle_id,
                            "statement": (
                                "The two reported patterns share one explanation."
                            ),
                            "status": "open",
                            "revision_rationale": "Attempt a non-gap assertion.",
                            "command_id": "reject-non-gap-assertion",
                            "expected_revision": candidate["domain_revision"],
                        },
                    },
                )
            gap = call_operation(
                "genomi.invoke",
                {
                    "tool": "lab.create_information_gap",
                    "params": {
                        "investigation_id": investigation_id,
                        "cycle_id": cycle_id,
                        "statement": (
                            "Objective evidence distinguishing shared from "
                            "independent explanations remains unavailable."
                        ),
                        "status": "open",
                        "revision_rationale": (
                            "Record the unresolved comparison explicitly."
                        ),
                        "command_id": "create-information-gap",
                        "expected_revision": candidate["domain_revision"],
                    },
                },
            )
            revised_gap = call_operation(
                "genomi.invoke",
                {
                    "tool": "lab.revise_information_gap",
                    "params": {
                        "investigation_id": investigation_id,
                        "logical_information_gap_id": gap[
                            "information_gap_version"
                        ]["logical_information_gap_id"],
                        "cycle_id": cycle_id,
                        "statement": (
                            "Independent clinical assessment and objective "
                            "measurements remain unavailable."
                        ),
                        "status": "open",
                        "revision_rationale": (
                            "Clarify the evidence needed to close the gap."
                        ),
                        "command_id": "revise-information-gap",
                        "expected_revision": gap["domain_revision"],
                    },
                },
            )
            with self.assertRaisesRegex(
                OperationError, "requires a new current profile or evidence snapshot"
            ):
                call_operation(
                    "genomi.invoke",
                    {
                        "tool": "lab.revise_information_gap",
                        "params": {
                            "investigation_id": investigation_id,
                            "logical_information_gap_id": gap[
                                "information_gap_version"
                            ]["logical_information_gap_id"],
                            "cycle_id": cycle_id,
                            "statement": (
                                "Whether the patterns share an explanation remains "
                                "to be determined."
                            ),
                            "status": "resolved",
                            "revision_rationale": (
                                "Attempt resolution without new assessed information."
                            ),
                            "command_id": "resolve-gap-without-new-information",
                            "expected_revision": revised_gap["domain_revision"],
                        },
                    },
                )
        revised_candidate = store.revise_hypothesis(
            investigation_id,
            logical_hypothesis_id=candidate["hypothesis_version"][
                "logical_hypothesis_id"
            ],
            cycle_id=cycle_id,
            statement=(
                "The two reported patterns remain a shared research hypothesis."
            ),
            status="open",
            profile_snapshot_id=None,
            evidence_snapshot_id=None,
            supporting_evidence_record_ids=[],
            contradicting_evidence_record_ids=[],
            contextual_evidence_record_ids=[],
            unresolved_gaps=["Objective clinical measurements have not been reviewed"],
            revision_rationale="Carry the current shared explanation forward.",
            category="shared_explanation",
            command_id="revise-shared-hypothesis",
            expected_revision=revised_gap["domain_revision"],
        )
        current_cycle = store.create_investigation_cycle(
            investigation_id,
            purpose="Prepare the current clinician discussion brief",
            prior_cycle_id=cycle_id,
            command_id="create-current-cycle",
            expected_revision=revised_candidate["domain_revision"],
        )
        current_cycle_id = str(current_cycle["cycle"]["cycle_id"])
        fact_ids = list(updated["source_fact_ids"])
        candidate_id = str(
            candidate["hypothesis_version"]["logical_hypothesis_id"]
        )
        gap_id = str(
            gap["information_gap_version"]["logical_information_gap_id"]
        )
        brief = {
            "title": "Clinician discussion brief",
            "summary": (
                "Two reported observations are documented while shared and "
                "independent explanations remain open."
            ),
            "claims": [
                {
                    "statement": (
                        "The current profile records exercise-associated fatigue "
                        "and disrupted sleep."
                    ),
                    "evidence_record_ids": [],
                    "profile_revision_ids": fact_ids,
                }
            ],
            "hypothesis_ids": [candidate_id],
            "gap_ids": [gap_id],
            "confirmation_needs": [
                "Independent clinical assessment and objective measurements",
                "Characterize the unresolved observation from source records",
                "Complete or rebuild the approved evidence index",
            ],
            "professional_questions": [
                "Which clinical measurements would best distinguish shared from independent explanations?",
                "Do the verified measurements support a clinically significant laboratory defect?",
            ],
            "clinical_boundary": CLINICAL_BOUNDARY,
        }
        params = {
            "investigation_id": investigation_id,
            "cycle_id": current_cycle_id,
            "brief": brief,
            "command_id": "publish-clinician-brief",
            "expected_revision": current_cycle["domain_revision"],
        }
        validate(instance=params, schema=self._publish_schema())

        with mock.patch.object(
            lab_operations, "_authorized_store", authorized_store
        ):
            stale_cycle = {**params, "cycle_id": cycle_id, "command_id": "stale-cycle"}
            with self.assertRaisesRegex(OperationError, "current investigation cycle"):
                call_operation(
                    "genomi.invoke",
                    {"tool": "lab.publish_brief", "params": stale_cycle},
                )

            stale_reference = copy.deepcopy(params)
            stale_reference["brief"]["hypothesis_ids"] = [
                candidate["hypothesis_version"]["hypothesis_version_id"]
            ]
            stale_reference["command_id"] = "stale-hypothesis-version"
            with self.assertRaisesRegex(OperationError, "current logical hypotheses"):
                call_operation(
                    "genomi.invoke",
                    {"tool": "lab.publish_brief", "params": stale_reference},
                )

            stale_gap = copy.deepcopy(params)
            stale_gap["brief"]["gap_ids"] = [
                gap["information_gap_version"]["information_gap_version_id"]
            ]
            stale_gap["command_id"] = "stale-information-gap-version"
            with self.assertRaisesRegex(OperationError, "current information gaps"):
                call_operation(
                    "genomi.invoke",
                    {"tool": "lab.publish_brief", "params": stale_gap},
                )

            hypothesis_as_gap = copy.deepcopy(params)
            hypothesis_as_gap["brief"]["hypothesis_ids"] = []
            hypothesis_as_gap["brief"]["gap_ids"] = [candidate_id]
            hypothesis_as_gap["command_id"] = "reject-hypothesis-as-gap"
            with self.assertRaisesRegex(OperationError, "current information gaps"):
                call_operation(
                    "genomi.invoke",
                    {"tool": "lab.publish_brief", "params": hypothesis_as_gap},
                )

            unknown_gap = copy.deepcopy(params)
            unknown_gap["brief"]["gap_ids"] = ["logical-information-gap-unknown"]
            unknown_gap["command_id"] = "unknown-gap-reference"
            with self.assertRaisesRegex(OperationError, "current information gaps"):
                call_operation(
                    "genomi.invoke",
                    {"tool": "lab.publish_brief", "params": unknown_gap},
                )

            stale_evidence = copy.deepcopy(params)
            stale_evidence["brief"]["claims"][0]["evidence_record_ids"] = [
                "evidence-record-not-in-current-snapshot"
            ]
            stale_evidence["command_id"] = "stale-evidence-anchor"
            with self.assertRaisesRegex(OperationError, "current evidence snapshot"):
                call_operation(
                    "genomi.invoke",
                    {"tool": "lab.publish_brief", "params": stale_evidence},
                )

            incomplete = copy.deepcopy(params)
            del incomplete["brief"]["professional_questions"]
            incomplete["command_id"] = "incomplete-brief"
            with self.assertRaisesRegex(OperationError, "complete clinician brief shape"):
                call_operation(
                    "genomi.invoke",
                    {"tool": "lab.publish_brief", "params": incomplete},
                )

            unsafe = copy.deepcopy(params)
            unsafe["brief"]["claims"][0]["statement"] = (
                "The evidence establishes the diagnosis and requires treatment."
            )
            unsafe["command_id"] = "unsafe-clinical-claim"
            with self.assertRaises(OperationError) as caught:
                call_operation(
                    "genomi.invoke",
                    {"tool": "lab.publish_brief", "params": unsafe},
                )
            self._assert_actionable_narrative_rejection(
                caught.exception, field="brief claim statement"
            )

            directive_title = copy.deepcopy(params)
            directive_title["brief"]["title"] = (
                "Start immunoglobulin replacement therapy: clinician brief"
            )
            directive_title["command_id"] = "unsafe-brief-title"
            with self.assertRaises(OperationError) as caught:
                call_operation(
                    "genomi.invoke",
                    {"tool": "lab.publish_brief", "params": directive_title},
                )
            self._assert_actionable_narrative_rejection(
                caught.exception, field="brief.title", span="Start immunoglobulin"
            )

            descriptive_title = copy.deepcopy(params)
            descriptive_title["brief"]["title"] = (
                "Exercise-associated fatigue with disrupted sleep and "
                "pre-treatment observations: cycle 1 evidence review"
            )
            descriptive_title["command_id"] = "descriptive-brief-title"
            descriptive = call_operation(
                "genomi.invoke",
                {"tool": "lab.publish_brief", "params": descriptive_title},
            )
            self.assertEqual(
                descriptive["brief_version"]["brief"]["title"],
                descriptive_title["brief"]["title"],
            )
            params = copy.deepcopy(params)
            params["expected_revision"] = descriptive["domain_revision"]

            result = call_operation(
                "genomi.invoke",
                {"tool": "lab.publish_brief", "params": params},
            )

        self.assertEqual(result["dispatched_tool"], "lab.publish_brief")
        self.assertEqual(result["brief_version"]["version"], 2)
        self.assertEqual(result["brief_version"]["brief"], brief)
        with mock.patch.object(
            lab_operations, "_authorized_store", authorized_store
        ):
            current = call_operation(
                "genomi.invoke",
                {
                    "tool": "lab.read_investigation",
                    "params": {"investigation_id": investigation_id},
                },
            )
            history = call_operation(
                "genomi.invoke",
                {
                    "tool": "lab.read_investigation",
                    "params": {
                        "investigation_id": investigation_id,
                        "include_history": True,
                    },
                },
            )
        self.assertEqual(len(current["information_gap_versions"]), 1)
        self.assertEqual(
            current["information_gap_versions"][0]["information_gap_version_id"],
            revised_gap["information_gap_version"]["information_gap_version_id"],
        )
        self.assertEqual(len(history["information_gap_versions"]), 2)

    def _assert_actionable_narrative_rejection(
        self, error: OperationError, *, field: str, span: str | None = None
    ) -> None:
        """A rejected narrative names the offending text, once, in typed fields."""

        payload = error.to_json(operation="lab.publish_brief")
        envelope = payload["evidence_envelope"]
        self.assertEqual(
            envelope["guidance"],
            [
                "narrative_asserts_diagnosis_or_directs_care:"
                "rewrite_rejected_text_as_descriptive_research_wording"
            ],
        )
        self.assertEqual(envelope["observations"]["rejected_field"], field)
        rejected_text = envelope["observations"]["rejected_text"]
        self.assertTrue(rejected_text)
        if span is not None:
            self.assertIn(span, rejected_text)
        self.assertEqual(
            envelope["next_actions"],
            [
                {
                    "action": "rewrite_narrative_text",
                    "field": field,
                    "rejected_text": rejected_text,
                }
            ],
        )
        notes = envelope["notes"]
        self.assertEqual(notes.count(error.message), 1)
        self.assertEqual(len(notes), len(set(notes)))

    @staticmethod
    def _publish_schema() -> dict[str, object]:
        focused = {
            tool["name"]: tool for tool in list_operations(capability="lab")
        }
        return focused["lab.publish_brief"]["inputSchema"]


if __name__ == "__main__":
    unittest.main()
