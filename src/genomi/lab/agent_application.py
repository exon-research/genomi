"""Host-owned GenomiLab investigation application boundary.

The underlying Claude, Codex, or other MCP host owns conversation and task
lifecycle.  This module exposes only durable GenomiLab domain transitions:
private-context authorization, exact plans, capability requests, hypotheses,
and patient-facing briefs.
"""

from __future__ import annotations

from typing import Any, Protocol

from .authorization_store import (
    AUTHORIZATION_SUBJECT_PLAN_ACCEPTANCE,
)
from .capability_registry import capability_definition
from .agent_artifacts import (
    DEFAULT_BRIEF_TITLE,
    artifact_schema,
    brief_case_narrative_contract,
    decode_wire_artifact,
    validate_artifact,
)
from .artifact_types import AgentArtifactKind
from .investigation_capabilities import _AGENT_CAPABILITY_EXECUTION_AUTHORITY
from .investigation_rounds import canonical_round_definition
from .models import JsonObject, required_text
from .narrative_contract import NarrativeStatementId, narrative_text
from .service_errors import LabError
from .specialist_board import specialist_board_handle


class _AgentApplication(Protocol):
    store: Any
    session_id: str
    _workspace: Any

    def bootstrap_workspace(self) -> JsonObject: ...

    def molecular_profile(self) -> JsonObject: ...

    def create_investigation(
        self,
        payload: JsonObject,
        *,
        investigation_event_type: str | None = None,
    ) -> JsonObject: ...

    def investigation(self, investigation_id: str) -> JsonObject: ...

    def _approved_investigation_profile(
        self, investigation_id: str
    ) -> JsonObject: ...

    def investigation_authorization_candidate(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject: ...

    def _require_investigation_authorization(
        self, investigation_id: str, *, intent: str, receipt: JsonObject | None = None
    ) -> JsonObject: ...

    def _execute_agent_capability_request(
        self, investigation_id: str, payload: JsonObject, *, _authority: object
    ) -> JsonObject: ...

    def _check_agent_capability_job(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject: ...

    def add_profile_observation(self, payload: JsonObject) -> JsonObject: ...

    def review_or_supersede_observation(
        self, observation_revision_id: str, payload: JsonObject
    ) -> JsonObject: ...

    def integrations(self) -> JsonObject: ...

    def research_scientific_operations_manifest(self) -> JsonObject: ...

    def revoke_private_context(self, investigation_id: str) -> JsonObject: ...

    def _require_specialist_board(
        self, investigation_id: str
    ) -> JsonObject: ...


class AgentApplicationMixin:
    """Durable operations called by the current underlying agent host."""

    def open_agent_workspace(self: _AgentApplication) -> JsonObject:
        workspace = self.bootstrap_workspace()
        presented = dict(workspace)
        if workspace.get("status") == "ready":
            presented["workspace"] = self._agent_workspace_view(
                workspace.get("workspace")
            )
        return {
            **presented,
            "execution": {
                "owner": "underlying_agent",
                "task_lifecycle": "owned_by_underlying_agent",
                "portal_role": "patient_onboarding_approval_and_monitoring",
            },
        }

    def create_agent_investigation(
        self: _AgentApplication, payload: JsonObject
    ) -> JsonObject:
        workspace = self.bootstrap_workspace()
        if workspace.get("status") != "ready":
            return workspace
        investigation = self.create_investigation(
            payload, investigation_event_type="investigation_created"
        )
        investigation_id = str(investigation["investigation_id"])
        return {
            "status": "created",
            "investigation": self._agent_investigation_view(investigation_id),
            "next_action": {
                "operation": "genomilab.form_specialist_board",
                "reason": "underlying_agent_should_form_native_specialist_board",
            },
        }

    def inspect_agent_investigation(
        self: _AgentApplication, investigation_id: str
    ) -> JsonObject:
        investigation = self._agent_investigation_view(investigation_id)
        current_plan = investigation.get("current_plan_version")
        current_round = investigation.get("current_round")
        next_actions: list[JsonObject] = []
        state_visible = (
            investigation.get("state_visibility")
            == "authorized_for_current_agent_session"
        )
        specialist_board = investigation.get("specialist_board")
        if not isinstance(specialist_board, dict):
            next_actions.append(
                {
                    "operation": "genomilab.form_specialist_board",
                    "reason": "underlying_agent_should_form_native_specialist_board",
                }
            )
        elif not state_visible:
            next_actions.append(
                {
                    "operation": "genomilab.prepare_authorization",
                    "reason": "patient_context_approval_required",
                }
            )
        elif not isinstance(current_plan, dict):
            next_actions.append(
                {
                    "operation": "genomilab.submit_plan",
                    "reason": "underlying_agent_should_plan_next",
                }
            )
        elif (
            isinstance(current_round, dict)
            and current_round.get("status") != "completed"
        ):
            next_actions.append(
                {
                    "operation": "genomilab.record_specialist_report",
                    "reason": "underlying_agent_should_complete_current_round",
                }
            )
        elif investigation.get("current_brief_version") is None:
            next_actions.append(
                {
                    "operation": "genomilab.submit_brief",
                    "reason": "publish_current_investigation_response_when_ready",
                }
            )
        result: JsonObject = {
            "status": "completed",
            "investigation": investigation,
            "capability_catalog": (
                self.investigation_capability_catalog(investigation_id)
                if state_visible
                else {}
            ),
            "next_actions": next_actions,
        }
        if state_visible:
            brief_context = self._agent_brief_context(
                investigation_id, investigation
            )
            case_narrative_contract = brief_case_narrative_contract(
                brief_context
            )
            result["brief_authoring"] = {
                "available": bool(case_narrative_contract.get("anchors")),
                "brief_title_fallback": DEFAULT_BRIEF_TITLE,
                "brief_schema": artifact_schema(
                    AgentArtifactKind.BRIEF_DRAFT,
                    brief_context,
                ),
                "case_narrative_contract": case_narrative_contract,
                **(
                    {}
                    if case_narrative_contract.get("anchors")
                    else {
                        "unavailable_reason": (
                            "no_eligible_case_narrative_anchor"
                        )
                    }
                ),
            }
        return result

    def prepare_agent_authorization(
        self: _AgentApplication,
        investigation_id: str,
        *,
        observation_revision_ids: list[str] | None = None,
        purpose: str | None = None,
    ) -> JsonObject:
        investigation = self.investigation(investigation_id)
        snapshot_id = str(
            investigation.get("patient_molecular_snapshot_id") or ""
        )
        pinned = (
            self.store.get_profile_snapshot(snapshot_id)
            if snapshot_id
            else None
        )
        profile = self.molecular_profile()
        selected = observation_revision_ids
        use_current_agi = True
        if selected is None and isinstance(pinned, dict):
            selected = [
                str(value)
                for value in pinned.get("observation_revision_ids") or []
            ]
            authorization_purpose = str(pinned.get("purpose") or "").strip()
            use_current_agi = False
        else:
            authorization_purpose = str(
                purpose
                or investigation.get("question")
                or investigation.get("disease_scope")
                or ""
            ).strip()
        if selected is None:
            selected = [
                str(item["observation_revision_id"])
                for item in profile.get("observations") or []
                if isinstance(item, dict) and item.get("observation_revision_id")
            ]
        if not selected:
            raise LabError(
                "molecular_profile_observation_required",
                "Add at least one patient-reported condition, phenotype, or molecular finding before authorizing this investigation.",
                http_status=409,
            )
        candidate = self.investigation_authorization_candidate(
            investigation_id,
            {
                "purpose": authorization_purpose,
                "use_current_agi": use_current_agi,
                "observation_revision_ids": selected,
            },
        )
        with self.store.atomic_write():
            self.store.set_investigation_status(
                investigation_id, "awaiting_context_approval"
            )
            self._append_agent_event(
                investigation_id,
                "context_approval_required",
                {
                    "candidate_sha256": candidate.get("candidate_sha256"),
                    "authorization_scope_sha256": candidate.get(
                        "authorization_scope_sha256"
                    ),
                    "refresh": bool(candidate.get("refresh")),
                },
            )
        return {
            "status": "authorization_required",
            "candidate": candidate,
            "next_action": {
                "owner": "patient_portal",
                "action": "review_and_approve_exact_context",
            },
        }

    def record_agent_patient_observations(
        self: _AgentApplication,
        investigation_id: str,
        observations: list[JsonObject],
    ) -> JsonObject:
        if not isinstance(observations, list) or not observations:
            raise LabError(
                "invalid_profile_observation",
                "Provide at least one patient observation.",
            )
        investigation = self.investigation(investigation_id)
        pinned_revision_ids: list[str] = []
        snapshot_id = str(
            investigation.get("patient_molecular_snapshot_id") or ""
        )
        if snapshot_id:
            snapshot = self.store.get_profile_snapshot(snapshot_id)
            pinned_revision_ids = [
                str(value)
                for value in snapshot.get("observation_revision_ids") or []
            ]
        superseded_revision_ids = {
            str(item.get("supersedes_observation_revision_id"))
            for item in observations
            if isinstance(item, dict)
            and item.get("supersedes_observation_revision_id")
        }
        pinned_revision_ids = [
            value
            for value in pinned_revision_ids
            if value not in superseded_revision_ids
        ]
        written = self._workspace.record_investigation_observations(
            investigation_id,
            observations,
            requires_context_refresh=bool(snapshot_id),
        )
        new_revision_ids = [
            str(item["observation_revision_id"])
            for item in written
            if item.get("observation_revision_id")
        ]
        selected = list(dict.fromkeys([*pinned_revision_ids, *new_revision_ids]))
        authorization = self.prepare_agent_authorization(
            investigation_id,
            observation_revision_ids=selected,
            purpose=str(
                (
                    self.store.get_profile_snapshot(snapshot_id).get("purpose")
                    if snapshot_id
                    else investigation.get("question")
                )
                or investigation.get("question")
            ),
        )
        return {
            "status": "authorization_required",
            "recorded_observations": written,
            "authorization": authorization,
        }

    def submit_agent_plan(
        self: _AgentApplication,
        investigation_id: str,
        *,
        focus_question: str,
        specialist_assignments: list[JsonObject],
        requests: list[JsonObject],
    ) -> JsonObject:
        board = self._require_specialist_board(investigation_id)
        authorization = self._require_investigation_authorization(
            investigation_id, intent="plan"
        )
        try:
            round_definition = canonical_round_definition(
                focus_question=focus_question,
                specialist_assignments=specialist_assignments,
                board=board,
            )
            plan = self._compile_agent_plan(requests=requests)
            self.validate_agent_capability_plan(investigation_id, plan)
        except ValueError as exc:
            raise LabError(
                "invalid_investigation_plan", str(exc), http_status=409
            ) from exc
        before = self.investigation(investigation_id)
        current = before.get("current_plan_version")
        if (
            isinstance(current, dict)
            and current.get("plan") == plan
            and current.get("review_status") == "accepted"
        ):
            current_round = next(
                (
                    item
                    for item in before.get("rounds") or []
                    if isinstance(item, dict)
                    and item.get("plan_version_id")
                    == current.get("plan_version_id")
                ),
                None,
            )
            if isinstance(current_round, dict):
                saved_assignments = [
                    {
                        "specialist_id": item.get("specialist_id"),
                        "task": item.get("task"),
                    }
                    for item in current_round.get("members") or []
                    if isinstance(item, dict)
                ]
                if (
                    current_round.get("focus_question")
                    != round_definition["focus_question"]
                    or saved_assignments
                    != round_definition["specialist_assignments"]
                ):
                    raise LabError(
                        "investigation_round_conflict",
                        "The accepted plan already belongs to a different investigation round definition.",
                        http_status=409,
                    )
                return {
                    "status": "accepted",
                    "plan_version": current,
                    "investigation_round": current_round,
                    "retry_reused": True,
                }
        prior_rounds = [
            item for item in before.get("rounds") or [] if isinstance(item, dict)
        ]
        if prior_rounds and prior_rounds[-1].get("status") != "completed":
            raise LabError(
                "specialist_round_incomplete",
                "Record every assigned specialist report before starting the next investigation round.",
                http_status=409,
            )
        try:
            with self.store.atomic_write():
                if (
                    isinstance(current, dict)
                    and current.get("plan") == plan
                    and current.get("review_status") == "accepted"
                ):
                    committed = current
                    investigation_round = self.store.create_investigation_round(
                        investigation_id,
                        plan_version_id=str(current["plan_version_id"]),
                        focus_question=str(round_definition["focus_question"]),
                        specialist_assignments=list(
                            round_definition["specialist_assignments"]
                        ),
                    )
                    self._append_agent_event(
                        investigation_id,
                        "round_started",
                        {
                            "round_id": investigation_round.get("round_id"),
                            "round_number": investigation_round.get("round_number"),
                            "plan_version_id": current.get("plan_version_id"),
                        },
                    )
                    retry_reused = False
                else:
                    committed = self.store.commit_plan(investigation_id, plan)
                    after_commit = self.store.get_investigation(investigation_id)
                    current = after_commit.get("current_plan_version")
                    if not isinstance(current, dict):
                        raise RuntimeError("plan commit produced no current plan")
                    acceptance = self.store.accept_plan(
                        investigation_id,
                        plan_version_id=current["plan_version_id"],
                        user_id=before["user_id"],
                        workspace_session_id=self.session_id,
                        plan_sha256=current["plan_sha256"],
                        approved=True,
                    )
                    self.store.derive_investigation_authorization_subject(
                        authorization["authorization_receipt_id"],
                        subject_kind=AUTHORIZATION_SUBJECT_PLAN_ACCEPTANCE,
                        subject_id=acceptance["plan_acceptance_id"],
                    )
                    investigation_round = self.store.create_investigation_round(
                        investigation_id,
                        plan_version_id=str(current["plan_version_id"]),
                        focus_question=str(round_definition["focus_question"]),
                        specialist_assignments=list(
                            round_definition["specialist_assignments"]
                        ),
                    )
                    self.store.set_investigation_status(investigation_id, "running")
                    self._append_agent_event(
                        investigation_id,
                        "plan_accepted",
                        {
                            "plan_version_id": committed.get("plan_version_id"),
                            "request_ids": [item["id"] for item in requests],
                            "acceptance_basis": "investigation_authorization",
                            "round_id": investigation_round.get("round_id"),
                            "round_number": investigation_round.get("round_number"),
                        },
                    )
                    retry_reused = False
        except (KeyError, ValueError) as exc:
            raise LabError(
                "invalid_investigation_plan", str(exc), http_status=409
            ) from exc
        refreshed = self.investigation(investigation_id)
        return {
            "status": "accepted",
            "plan_version": refreshed.get("current_plan_version"),
            "investigation_round": refreshed.get("current_round"),
            "retry_reused": retry_reused,
        }

    def execute_agent_request(
        self: _AgentApplication, investigation_id: str, request_id: str
    ) -> JsonObject:
        self._require_specialist_board(investigation_id)
        self._require_investigation_authorization(
            investigation_id, intent="execute_accepted_plan"
        )
        request = required_text(request_id, "request_id", 200)
        return self._execute_agent_capability_request(
            investigation_id,
            {"request_id": request},
            _authority=_AGENT_CAPABILITY_EXECUTION_AUTHORITY,
        )

    def check_agent_request(
        self: _AgentApplication, investigation_id: str, request_id: str
    ) -> JsonObject:
        self._require_specialist_board(investigation_id)
        self._require_investigation_authorization(
            investigation_id, intent="resume"
        )
        investigation = self._accepted_current_plan(investigation_id)
        current = investigation.get("current_plan_version")
        if not isinstance(current, dict):
            raise LabError("plan_acceptance_required", "No accepted plan is active.")
        request = required_text(request_id, "request_id", 200)
        execution = self.store.get_capability_execution(
            investigation_id, str(current["plan_version_id"]), request
        )
        if not isinstance(execution, dict):
            raise LabError(
                "capability_request_not_found",
                "That request has not been executed for the current plan.",
                http_status=404,
            )
        if execution.get("status") != "in_progress":
            return self._capability_job_response(execution)
        return self._check_agent_capability_job(
            investigation_id,
            {
                "request_id": request,
                "job_id": execution.get("job_id"),
                "resume_operation": execution.get("resume_operation"),
                "plan_version_id": current["plan_version_id"],
            },
        )

    def submit_agent_brief(
        self: _AgentApplication, investigation_id: str, brief: JsonObject
    ) -> JsonObject:
        self._require_specialist_board(investigation_id)
        try:
            with self.store.atomic_write():
                self._require_investigation_authorization(
                    investigation_id, intent="user_followup"
                )
                investigation = self._accepted_current_plan(investigation_id)
                current_round = investigation.get("current_round")
                if not isinstance(current_round, dict) or current_round.get(
                    "status"
                ) != "completed":
                    raise LabError(
                        "specialist_round_incomplete",
                        "Record every assigned specialist report before publishing the investigation brief.",
                        http_status=409,
                    )
                context = self._agent_brief_context(
                    investigation_id, investigation
                )
                canonical_brief = decode_wire_artifact(
                    AgentArtifactKind.BRIEF_DRAFT,
                    dict(brief),
                    approved_context=context,
                )
                validate_artifact(
                    AgentArtifactKind.BRIEF_DRAFT,
                    canonical_brief,
                    approved_context=context,
                )
                current = investigation.get("current_brief_version")
                if (
                    isinstance(current, dict)
                    and current.get("brief") == canonical_brief
                ):
                    retry_reused = True
                    committed = current
                else:
                    retry_reused = False
                    committed = self.store.commit_brief(
                        investigation_id, canonical_brief
                    )
                    self._append_agent_event(
                        investigation_id,
                        "brief_published",
                        {
                            "brief_version_id": committed.get("brief_version_id"),
                            "version": committed.get("version"),
                            "prior_brief_version_id": committed.get(
                                "prior_brief_version_id"
                            ),
                        },
                    )
        except (KeyError, ValueError) as exc:
            raise LabError(
                "invalid_investigation_brief", str(exc), http_status=409
            ) from exc
        return {
            "status": "completed",
            "brief_version": committed,
            "investigation_response": self._agent_investigation_view(
                investigation_id
            ),
            "retry_reused": retry_reused,
        }

    def list_agent_research_tools(self: _AgentApplication) -> JsonObject:
        return {
            "status": "completed",
            "research_tools": self.integrations(),
            "scientific_operations": (
                self.research_scientific_operations_manifest()
            ),
            "usage_boundary": {
                "paperclip": "approved_search_and_lookup_when_advertised",
                "biohub-esm-connection": (
                    "connection_check_does_not_execute_scientific_analysis"
                ),
                "proto-connection": (
                    "connection_check_does_not_execute_scientific_analysis"
                ),
                "esm-scientific-operation": (
                    "bounded_local_nonclinical_operation_when_executor_available"
                ),
                "proto-scientific-operation": (
                    "bounded_local_nonclinical_operation_when_executor_available"
                ),
            },
        }

    def replay_investigation_events(
        self: _AgentApplication,
        investigation_id: str,
        *,
        after_sequence: int = 0,
    ) -> JsonObject:
        self.investigation(investigation_id)
        events = self.store.replay_investigation_events(
            investigation_id, after_sequence=max(0, int(after_sequence))
        )
        return {
            "status": "events",
            "events": events,
            "after_sequence": max(0, int(after_sequence)),
            "latest_sequence": max(
                (int(event["sequence"]) for event in events),
                default=max(0, int(after_sequence)),
            ),
            "execution_owner": "underlying_agent",
        }

    def stream_investigation_events(
        self: _AgentApplication,
        investigation_id: str,
        *,
        after_sequence: int,
        timeout_seconds: float = 20.0,
    ) -> JsonObject:
        del timeout_seconds
        return self.replay_investigation_events(
            investigation_id, after_sequence=after_sequence
        )

    def revoke_agent_context(
        self: _AgentApplication, investigation_id: str
    ) -> JsonObject:
        return self.revoke_private_context(investigation_id)

    @staticmethod
    def _compile_agent_plan(*, requests: list[JsonObject]) -> JsonObject:
        if not isinstance(requests, list) or not requests:
            raise LabError(
                "invalid_investigation_plan",
                "An investigation plan requires at least one exact capability request.",
            )
        steps: list[JsonObject] = []
        compiled_requests: list[JsonObject] = []
        seen: set[str] = set()
        for index, item in enumerate(requests, start=1):
            if not isinstance(item, dict) or set(item) != {
                "id",
                "capability",
                "parameters",
            }:
                raise LabError(
                    "invalid_investigation_plan",
                    "Each request requires exactly id, capability, and parameters.",
                )
            request_id = required_text(item.get("id"), "request id", 200)
            if request_id in seen:
                raise LabError(
                    "invalid_investigation_plan",
                    "Plan request identifiers must be unique.",
                )
            seen.add(request_id)
            capability = required_text(item.get("capability"), "capability", 200)
            parameters = item.get("parameters")
            if not isinstance(parameters, dict):
                raise LabError(
                    "invalid_investigation_plan",
                    "Plan request parameters must be an object.",
                )
            try:
                definition = capability_definition(capability)
            except ValueError as exc:
                raise LabError(
                    "invalid_investigation_plan", str(exc), http_status=409
                ) from exc
            step_id = f"agent-step-{index}"
            steps.append(
                {
                    "id": step_id,
                    "title": narrative_text(NarrativeStatementId.PLAN_STEP_TITLE),
                    "rationale": narrative_text(
                        NarrativeStatementId.PLAN_STEP_RATIONALE
                    ),
                    "capabilities": [capability],
                    "proposed_agent_role": "underlying_agent",
                    "requires_private_context": "public" not in definition.privacy,
                    "requires_external_provider": definition.requires_exact_egress_approval,
                }
            )
            compiled_requests.append(
                {
                    "id": request_id,
                    "step_id": step_id,
                    "assigned_agent_role": "underlying_agent",
                    "capability": capability,
                    "parameters": dict(parameters),
                }
            )
        return {
            "summary": narrative_text(NarrativeStatementId.PLAN_SUMMARY),
            "proposed_agent_roles": [
                {
                    "role": "underlying_agent",
                    "objective": narrative_text(
                        NarrativeStatementId.PLAN_ROLE_OBJECTIVE
                    ),
                }
            ],
            "steps": steps,
            "capability_requests": compiled_requests,
        }

    def _append_agent_event(
        self: _AgentApplication,
        investigation_id: str,
        event_type: str,
        payload: JsonObject,
    ) -> None:
        append = getattr(self.store, "append_investigation_event", None)
        if not callable(append):
            raise RuntimeError("investigation event persistence is unavailable")
        append(investigation_id, event_type=event_type, payload=payload)

    def _agent_brief_context(
        self: _AgentApplication,
        investigation_id: str,
        investigation: JsonObject | None = None,
    ) -> JsonObject:
        current = investigation or self.investigation(investigation_id)
        return {
            "disease_scope": current.get("disease_scope"),
            "molecular_profile": self._approved_investigation_profile(
                investigation_id
            ),
            "evidence_records": list(
                current.get("current_evidence_records") or []
            ),
            "hypotheses": list(current.get("current_hypotheses") or []),
        }

    def _agent_investigation_view(
        self: _AgentApplication, investigation_id: str
    ) -> JsonObject:
        """Present domain state only to its currently authorized agent session."""

        investigation = dict(self.investigation(investigation_id))
        try:
            self._require_investigation_authorization(
                investigation_id, intent="resume"
            )
        except LabError:
            withheld: JsonObject = {
                "investigation_id": investigation["investigation_id"],
                "private_context_status": (
                    "renewal_required"
                    if investigation.get("patient_molecular_snapshot_id")
                    else "not_approved"
                ),
                "state_visibility": "withheld_pending_authorization",
            }
            board = investigation.get("specialist_board")
            if isinstance(board, dict):
                withheld["specialist_board"] = specialist_board_handle(board)
            return withheld
        investigation["state_visibility"] = (
            "authorized_for_current_agent_session"
        )
        return investigation

    def _agent_workspace_view(
        self: _AgentApplication, workspace: object
    ) -> JsonObject:
        """Expose setup readiness and authorization-aware investigation handles."""

        source = workspace if isinstance(workspace, dict) else {}
        profile = source.get("profile")
        genome = profile.get("genome") if isinstance(profile, dict) else None
        investigations: list[JsonObject] = []
        for item in source.get("investigations") or []:
            if not isinstance(item, dict) or not item.get("investigation_id"):
                continue
            view = self._agent_investigation_view(
                str(item["investigation_id"])
            )
            investigations.append(
                {
                    "investigation_id": view["investigation_id"],
                    "private_context_status": view["private_context_status"],
                    "state_visibility": view["state_visibility"],
                    **(
                        {"specialist_board": view["specialist_board"]}
                        if isinstance(view.get("specialist_board"), dict)
                        else {}
                    ),
                }
            )
        return {
            "workspace_id": source.get("workspace_id"),
            "active_genome_index": {
                "readiness": (
                    genome.get("readiness") if isinstance(genome, dict) else None
                )
            },
            "profile_onboarding": {
                "observation_count": len(profile.get("observations") or [])
                if isinstance(profile, dict)
                else 0,
                "source_artifact_count": len(
                    profile.get("source_artifacts") or []
                )
                if isinstance(profile, dict)
                else 0,
                "specimen_count": len(profile.get("specimens") or [])
                if isinstance(profile, dict)
                else 0,
                "assay_count": len(profile.get("assays") or [])
                if isinstance(profile, dict)
                else 0,
            },
            "investigations": investigations,
        }


__all__ = ["AgentApplicationMixin"]
