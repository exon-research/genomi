"""Deterministic in-memory harness used for protocol conformance."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .brief_provenance import derive_brief_modality_badges
from .disease_relation_contract import REGISTER_DISEASE_RELATION
from .harness_adapter import (
    HarnessAdapter,
    HarnessDynamicToolCall,
    HostArtifact,
    HostInvocationUnavailable,
    HostTraceEvent,
)
from .harness_transport import PROTOCOL_VERSION
from .harness_types import (
    HarnessArtifactKind,
    HarnessCapabilityManifest,
    HarnessCommand,
    HarnessEventKind,
    HarnessEventStatus,
    HarnessOperation,
)
from .hypothesis_contract import GAP_KINDS


class SimulatedHarnessAdapter(HarnessAdapter):
    def __init__(
        self,
        *,
        adapter_id: str = "simulated-harness",
        unavailable_operations: Sequence[HarnessOperation] = (),
        replay_window: int = 1_000,
        investigation_window: int = 128,
        command_window: int | None = None,
    ) -> None:
        unavailable = {HarnessOperation(value) for value in unavailable_operations}
        operations = tuple(
            operation for operation in HarnessOperation if operation not in unavailable
        )
        super().__init__(
            HarnessCapabilityManifest(
                adapter_id=adapter_id,
                host_kind="simulated",
                host_version="1",
                available=True,
                supported_protocol_versions=(PROTOCOL_VERSION,),
                supported_operations=operations,
                event_streaming=True,
                event_replay=True,
                artifact_kinds=tuple(HarnessArtifactKind),
                agent_delegation_planning=True,
                agent_delegation_event_reporting=True,
                background_job_attach=False,
                background_job_cancel=False,
                approved_context_delivery=True,
                workspace_session_persistence="adapter_process",
                execution_location="local_test_process",
            ),
            replay_window=replay_window,
            investigation_window=investigation_window,
            command_window=command_window,
        )

    def _produce_artifact(
        self,
        artifact_kind: HarnessArtifactKind,
        command: HarnessCommand,
        instruction: str,
        approved_context: Mapping[str, Any],
        *,
        resume_task_id: str | None,
    ) -> HostArtifact:
        if artifact_kind == HarnessArtifactKind.PLAN:
            steps, roles, requests, approvals = _plan_components(approved_context)
            artifact: Mapping[str, Any] = {
                "summary": (
                    "Investigate: Could the approved molecular profile and current "
                    "evidence help explain the reported condition?"
                ),
                "steps": steps,
                "proposed_agent_roles": roles,
                "capability_requests": requests,
                "required_approvals": approvals,
            }
        elif artifact_kind == HarnessArtifactKind.EXECUTION_REPORT:
            accepted_plan = approved_context.get("accepted_plan")
            plan = (
                accepted_plan.get("plan")
                if isinstance(accepted_plan, Mapping)
                else None
            )
            requests = (
                plan.get("capability_requests") if isinstance(plan, Mapping) else None
            )
            if not isinstance(requests, (list, tuple)):
                raise HostInvocationUnavailable(
                    "the simulated harness received no exact accepted plan"
                )
            task_id = resume_task_id or self._generated_id(
                "sim-task", command.command_id
            )
            turn_id = self._generated_id("sim-turn", command.command_id)
            request_results: list[dict[str, Any]] = []
            traces: list[HostTraceEvent] = []
            for index, request in enumerate(requests):
                if not isinstance(request, Mapping):
                    raise ValueError("accepted plan capability request must be an object")
                request_id = str(request.get("id") or "")
                capability = str(request.get("capability") or "")
                result = self._invoke_dynamic_tool_handler(
                    HarnessDynamicToolCall(
                        command_id=command.command_id,
                        investigation_id=command.investigation_id,
                        thread_id=task_id,
                        turn_id=turn_id,
                        call_id=f"simulated-call-{index + 1}",
                        capability=capability,
                        request_id=request_id,
                    )
                )
                status = str(result.get("status") or "completed")
                request_results.append(
                    {
                        "request_id": request_id,
                        "capability": capability,
                        "status": status,
                    }
                )
                traces.append(
                    HostTraceEvent(
                        HarnessEventKind.APPROVAL_REQUIRED
                        if status == "approval_required"
                        else HarnessEventKind.EVIDENCE_RETURNED,
                        HarnessEventStatus.WAITING
                        if status == "approval_required"
                        else HarnessEventStatus.COMPLETED,
                        {
                            "call_id": f"simulated-call-{index + 1}",
                            "capability": capability,
                            "request_id": request_id,
                            "result_status": status,
                        },
                    )
                )
            return HostArtifact(
                artifact_kind,
                {
                    "summary": "The installed harness invoked the exact accepted plan requests.",
                    "request_results": request_results,
                },
                task_id,
                turn_id,
                tuple(traces),
                True,
            )
        else:
            evidence_records = _usable_evidence_records(
                approved_context.get("evidence_records")
            )
            evidence_ids = _record_ids(evidence_records, "evidence_record_id")
            revision_ids = _profile_revision_ids(approved_context)
            has_exact_anchor = bool(evidence_ids or revision_ids)
            hypotheses = approved_context.get("hypotheses")
            hypothesis_ids = _hypothesis_ids(hypotheses, gaps=False)
            gap_ids = _hypothesis_ids(hypotheses, gaps=True)
            anchor_statement = (
                "The approved record contains an observation for research review."
            )
            if not evidence_ids and not revision_ids:
                revision_ids = ["uncommittable-simulated-profile-anchor"]
                anchor_statement = (
                    "The approved record contains an observation that lacks a "
                    "committable patient anchor."
                )
            if hypothesis_ids:
                matching = _matching_hypothesis(hypotheses, hypothesis_ids[0])
                if matching is not None:
                    evidence_ids = [
                        str(value)
                        for value in matching.get("evidence_record_ids") or []
                    ]
                    revision_ids = [
                        str(value)
                        for value in matching.get("profile_revision_ids") or []
                    ]
                    anchor_statement = str(
                        matching.get("statement")
                        or "The reported finding remains a research candidate."
                    )
            claims = [
                {
                    "statement": anchor_statement,
                    "claim_role": (
                        "candidate_hypothesis" if hypothesis_ids else "observation"
                    ),
                    "evidence_record_ids": evidence_ids,
                    "profile_revision_ids": revision_ids,
                }
            ]
            if gap_ids:
                matching_gap = _matching_hypothesis(hypotheses, gap_ids[0])
                if matching_gap is not None:
                    claims.append(
                        {
                            "statement": (
                                "Evidence gap: Independent clinical confirmation "
                                "remains an open requirement."
                            ),
                            "claim_role": "limitation",
                            "evidence_record_ids": [
                                str(value)
                                for value in matching_gap.get("evidence_record_ids")
                                or []
                            ],
                            "profile_revision_ids": [
                                str(value)
                                for value in matching_gap.get("profile_revision_ids")
                                or []
                            ],
                        }
                    )
            profile = approved_context.get("molecular_profile")
            observations = (
                profile.get("observations") if isinstance(profile, Mapping) else None
            )
            if not has_exact_anchor:
                modality_badges: list[str] = []
            else:
                modality_badges = derive_brief_modality_badges(
                    claims,
                    evidence_records=evidence_records,
                    profile_records=(
                        observations
                        if isinstance(observations, (list, tuple))
                        else ()
                    ),
                )
            artifact = {
                "title": "Proposed investigation brief",
                "summary": (
                    "The reported finding remains a research candidate."
                    if hypothesis_ids
                    else "The approved record remains a research observation."
                ),
                "clinical_stage": (
                    "candidate_hypothesis" if hypothesis_ids else "research_observation"
                ),
                "modality_badges": modality_badges,
                "claims": claims,
                "hypothesis_ids": hypothesis_ids,
                "gap_ids": gap_ids,
                "confirmation_needs": [],
                "professional_questions": [],
                "clinical_boundary": "Research support only; this is not a diagnosis or treatment decision.",
                "change_summary": "Initial simulated draft.",
            }
        task_id = resume_task_id or self._generated_id("sim-task", command.command_id)
        return HostArtifact(artifact_kind, artifact, task_id)


def _plan_components(
    approved_context: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    catalog = approved_context.get("capability_catalog")
    catalog = catalog if isinstance(catalog, Mapping) else {}
    profile = approved_context.get("molecular_profile")
    profile = profile if isinstance(profile, Mapping) else None
    evidence_records = _usable_evidence_records(
        approved_context.get("evidence_records")
    )
    steps: list[dict[str, Any]] = []
    roles: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    approvals: list[str] = []

    def add_step(
        *,
        step_id: str,
        title: str,
        rationale: str,
        capability: str,
        role: str,
        objective: str,
        parameters: dict[str, Any] | None,
        private: bool,
        external: bool,
    ) -> None:
        steps.append(
            {
                "id": step_id,
                "title": title,
                "rationale": rationale,
                "capabilities": [capability],
                "proposed_agent_role": role,
                "requires_private_context": private,
                "requires_external_provider": external,
            }
        )
        roles.append(
            {
                "role": role,
                "objective": objective,
                "assigned_step_ids": [step_id],
            }
        )
        if parameters is not None:
            requests.append(
                {
                    "id": f"request-{step_id}",
                    "step_id": step_id,
                    "assigned_agent_role": role,
                    "capability": capability,
                    "parameters": parameters,
                }
            )

    profile_available = bool(
        isinstance(catalog.get("investigation.project_profile"), Mapping)
        and catalog["investigation.project_profile"].get("available")
    )
    add_step(
        step_id="profile",
        title="Review the approved molecular profile",
        rationale="Keep the investigation grounded in the exact patient-approved slice.",
        capability="investigation.project_profile",
        role="patient_context_reviewer",
        objective="Review only the approved profile slice and its limitations.",
        parameters={} if profile_available else None,
        private=True,
        external=False,
    )
    if not profile_available:
        approvals.append("private_context")

    variant_entry = catalog.get("genomi.variant.resolve")
    if isinstance(variant_entry, Mapping) and variant_entry.get("available"):
        variant_params = variant_entry.get("parameters")
        if isinstance(variant_params, Mapping) and _has_exact_variant_target(
            variant_params
        ):
            add_step(
                step_id="personal-genome",
                title="Check the exact reported variant in Genomi",
                rationale="Confirm only the approved targeted genome observation and coverage.",
                capability="genomi.variant.resolve",
                role="genome_evidence_reviewer",
                objective="Retrieve exact-scope personal-genome evidence from Genomi.",
                parameters=dict(variant_params),
                private=True,
                external=False,
            )

    disease_scope = str(approved_context.get("disease_scope") or "").strip()
    if disease_scope and profile is not None and not evidence_records:
        add_step(
            step_id="public-evidence",
            title="Search disease-mechanism evidence",
            rationale="Add a separately sourced literature stream without collapsing its prior.",
            capability="public_evidence.retrieve",
            role="literature_evidence_reviewer",
            objective="Retrieve cited public mechanism evidence through the GenomiLab gateway.",
            parameters={
                "operation": "search",
                "query": disease_scope,
                "query_terms": [disease_scope],
                "filters": {},
                "source_family": "literature",
                "purpose": "Investigate disease relevance against the approved molecular profile",
            },
            private=False,
            external=True,
        )
        approvals.append("external_evidence_disclosure")

    relation_records = [
        record
        for record in evidence_records
        if record.get("operation") == REGISTER_DISEASE_RELATION
    ]
    relation_entry = catalog.get(REGISTER_DISEASE_RELATION)
    if (
        profile is not None
        and not relation_records
        and isinstance(relation_entry, Mapping)
        and relation_entry.get("available") is True
    ):
        exact_templates = relation_entry.get("exact_request_templates")
        selected_template = next(
            (
                template
                for template in exact_templates or []
                if isinstance(template, Mapping)
                and template.get("direction") == "supports"
            ),
            None,
        )
        if selected_template is not None:
            add_step(
                step_id="disease-relation",
                title="Link public disease evidence to the exact molecular finding",
                rationale=(
                    "Create the typed, local relation required before a patient "
                    "overlap can become a candidate mechanism."
                ),
                capability=REGISTER_DISEASE_RELATION,
                role="disease_relation_reviewer",
                objective=(
                    "Bind one public evidence prior to the exact approved patient "
                    "finding without sending patient anchors to the provider."
                ),
                parameters=dict(selected_template),
                private=True,
                external=False,
            )

    hypothesis_entry = catalog.get("investigation.register_hypothesis")
    candidate_bases = (
        hypothesis_entry.get("candidate_mechanism_relation_anchors")
        if isinstance(hypothesis_entry, Mapping)
        else None
    )
    candidate_basis = next(
        (
            item
            for item in candidate_bases or []
            if isinstance(item, Mapping)
            and isinstance(item.get("evidence_record_id"), str)
            and item.get("evidence_record_id")
            in {record.get("evidence_record_id") for record in relation_records}
        ),
        None,
    )
    if profile is not None and candidate_basis is not None:
        revision_ids = _string_values(candidate_basis.get("profile_revision_ids"))
        candidate_templates = hypothesis_entry.get("exact_request_templates")
        candidate_template = next(
            (
                item
                for item in candidate_templates or []
                if isinstance(item, Mapping)
                and _string_values(item.get("profile_revision_ids")) == revision_ids
            ),
            None,
        )
        gap_entry = catalog.get("investigation.register_gap")
        gap_template = next(
            (
                item
                for item in (
                    gap_entry.get("exact_request_templates")
                    if isinstance(gap_entry, Mapping)
                    else []
                )
                if isinstance(item, Mapping)
                and _string_values(item.get("profile_revision_ids")) == revision_ids
            ),
            None,
        )
        if candidate_template is None or gap_template is None:
            return steps, roles, requests, sorted(set(approvals))
        add_step(
            step_id="hypothesis",
            title="Register a traceable candidate mechanism",
            rationale="Keep harness reasoning separate from source evidence and patient facts.",
            capability="investigation.register_hypothesis",
            role="mechanism_synthesizer",
            objective="Propose a bounded mechanism using immutable evidence and profile anchors.",
            parameters=dict(candidate_template),
            private=True,
            external=False,
        )
        add_step(
            step_id="gap",
            title="Register unresolved confirmation needs",
            rationale="Preserve what the investigation cannot yet establish.",
            capability="investigation.register_gap",
            role="evidence_gap_reviewer",
            objective="Record missing clinical confirmation and phenotype review.",
            parameters=dict(gap_template),
            private=True,
            external=False,
        )
    return steps, roles, requests, sorted(set(approvals))


def _has_exact_variant_target(parameters: Mapping[str, Any]) -> bool:
    has_rsid = isinstance(parameters.get("rsid"), str) and bool(parameters.get("rsid"))
    has_any_allele = any(
        parameters.get(key) not in (None, "") for key in ("chrom", "pos", "ref", "alt")
    )
    has_exact_allele = all(
        parameters.get(key) not in (None, "") for key in ("chrom", "pos", "ref", "alt")
    )
    return has_rsid != has_exact_allele and not (
        has_any_allele and not has_exact_allele
    )


def _record_ids(value: object, key: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [
        str(record[key])
        for record in value
        if isinstance(record, Mapping) and isinstance(record.get(key), str)
    ]


def _string_values(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _usable_evidence_records(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    usable_findings = {"evidence_present", "true_negative_supported"}
    usable_readiness = {
        "answer_supported",
        "scoped_answer_only",
        "needs_clinical_confirmation",
    }
    result: list[Mapping[str, Any]] = []
    for record in value:
        if not isinstance(record, Mapping):
            continue
        envelope = record.get("evidence_envelope")
        if not isinstance(envelope, Mapping):
            continue
        if (
            envelope.get("finding_state") in usable_findings
            and envelope.get("answer_readiness") in usable_readiness
        ):
            result.append(record)
    return result


def _hypothesis_ids(value: object, *, gaps: bool) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for record in value:
        if not isinstance(record, Mapping):
            continue
        identifier = record.get("hypothesis_id")
        is_gap = record.get("kind") in GAP_KINDS
        if isinstance(identifier, str) and is_gap is gaps:
            result.append(identifier)
    return result


def _matching_hypothesis(value: object, hypothesis_id: str) -> Mapping[str, Any] | None:
    if not isinstance(value, (list, tuple)):
        return None
    for record in value:
        if isinstance(record, Mapping) and record.get("hypothesis_id") == hypothesis_id:
            return record
    return None


def _profile_revision_ids(approved_context: Mapping[str, Any]) -> list[str]:
    profile = approved_context.get("molecular_profile")
    if not isinstance(profile, Mapping):
        return []
    explicit_ids = profile.get("observation_revision_ids")
    if isinstance(explicit_ids, (list, tuple)):
        return [str(value) for value in explicit_ids if isinstance(value, str)]
    observations = profile.get("observations")
    return _record_ids(observations, "observation_revision_id")
