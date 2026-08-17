"""Canonical validation for agent-authored GenomiLab artifacts."""

from __future__ import annotations

from typing import Collection

from .brief_provenance import ALLOWED_MODALITY_BADGES
from .hypothesis_contract import case_anchor_terms
from .models import (
    QUESTION_MAX,
    JsonObject,
    compact_json,
    required_text,
    validate_private_payload,
)
from .research_narrative import (
    validate_clinician_question,
    validate_research_narrative,
)


AGENT_CLINICAL_STAGES = {"research_observation", "candidate_hypothesis"}
BRIEF_CLINICAL_BOUNDARY = (
    "Research support only; this is not a diagnosis or treatment decision."
)
CLAIM_ROLES = {
    "observation",
    "candidate_hypothesis",
    "counterevidence",
    "limitation",
}
TIMELINE_ENTRY_FIELDS = {
    "statement",
    "evidence_record_ids",
    "profile_revision_ids",
}
CLINICIAN_QUESTION_FIELDS = {
    "question",
    "evidence_record_ids",
    "profile_revision_ids",
    "hypothesis_ids",
    "gap_ids",
}


def validate_plan_artifact(plan: JsonObject) -> None:
    validate_private_payload(plan)
    validate_research_narrative(
        plan.get("summary"), "plan summary", kind="plan_summary"
    )
    roles = plan.get("proposed_agent_roles")
    if roles is not None:
        if not isinstance(roles, list):
            raise ValueError("proposed_agent_roles must be an array")
        for role in roles:
            if not isinstance(role, dict):
                raise ValueError("every proposed agent role must be an object")
            required_text(role.get("role"), "proposed agent role", 200)
            if role.get("objective") is not None:
                validate_research_narrative(
                    role.get("objective"),
                    "proposed agent objective",
                    kind="plan_role_objective",
                )
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("plan steps must be a non-empty array")
    step_by_id: dict[str, JsonObject] = {}
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("every plan step must be an object")
        step_id = required_text(step.get("id"), "plan step id", 200)
        if step_id in step_by_id:
            raise ValueError("plan step identifiers must be unique")
        step_by_id[step_id] = step
        validate_research_narrative(
            step.get("title"), "plan step title", kind="plan_step_title"
        )
        if step.get("rationale") is not None:
            validate_research_narrative(
                step.get("rationale"),
                "plan step rationale",
                kind="plan_step_rationale",
            )
        capabilities = step.get("capabilities")
        if not isinstance(capabilities, list) or not all(
            isinstance(value, str) and value.strip() for value in capabilities
        ):
            raise ValueError("plan step capabilities must be an array of names")
    requests = plan.get("capability_requests")
    if not isinstance(requests, list):
        raise ValueError("plan capability_requests must be an array")
    request_ids: set[str] = set()
    for request in requests:
        if not isinstance(request, dict):
            raise ValueError("every capability request must be an object")
        request_id = required_text(request.get("id"), "capability request id", 200)
        if request_id in request_ids:
            raise ValueError("capability request identifiers must be unique")
        request_ids.add(request_id)
        step_id = required_text(request.get("step_id"), "capability step id", 200)
        role = required_text(
            request.get("assigned_agent_role"), "capability agent role", 200
        )
        capability = required_text(request.get("capability"), "capability", 200)
        parameters = request.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError("capability parameters must be an object")
        step = step_by_id.get(step_id)
        if step is None or capability not in step["capabilities"]:
            raise ValueError("capability request must reference a declaring plan step")
        if role != step.get("proposed_agent_role"):
            raise ValueError("capability request role must match its plan step")


def validate_brief_artifact(
    brief: JsonObject,
    *,
    allowed_modality_badges: Collection[str] | None = None,
    case_narrative_contract: JsonObject | None = None,
    require_case_narrative: bool = False,
    validate_narratives: bool = True,
) -> None:
    validate_private_payload(brief)
    if str(brief.get("clinical_stage") or "") not in AGENT_CLINICAL_STAGES:
        raise ValueError(
            "agent briefs may use only research_observation or candidate_hypothesis; "
            "clinical stages require a separately attributed clinical workflow"
        )
    title = required_text(brief.get("title"), "brief title", 500)
    summary = required_text(brief.get("summary"), "brief summary", QUESTION_MAX)
    badges = brief.get("modality_badges")
    if not isinstance(badges, list) or not all(
        isinstance(value, str) and value.strip() for value in badges
    ):
        raise ValueError("brief modality_badges must be an array of names")
    if not badges or any(value not in ALLOWED_MODALITY_BADGES for value in badges):
        raise ValueError("brief modality_badges must use the declared evidence vocabulary")
    if len(badges) != len(set(badges)):
        raise ValueError("brief modality_badges must be unique")
    if allowed_modality_badges is not None and not set(badges).issubset(
        set(allowed_modality_badges)
    ):
        raise ValueError(
            "brief modality_badges must be supported by the pinned profile or evidence ledger"
        )
    claims = brief.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("brief claims must be a non-empty array")
    claim_fingerprints: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("every brief claim must be an object")
        claim_role = claim.get("claim_role")
        if claim_role not in CLAIM_ROLES:
            raise ValueError("every brief claim requires a declared claim_role")
        if validate_narratives:
            validate_research_narrative(
                claim.get("statement"),
                "brief claim",
                kind={
                    "observation": "claim_observation",
                    "candidate_hypothesis": "claim_candidate_hypothesis",
                    "counterevidence": "claim_counterevidence",
                    "limitation": "claim_limitation",
                }[claim_role],
                case_anchor_terms=(
                    case_anchor_terms(
                        case_narrative_contract,
                        profile_revision_ids=claim.get("profile_revision_ids") or [],
                        evidence_record_ids=claim.get("evidence_record_ids") or [],
                    )
                    if case_narrative_contract is not None
                    else None
                ),
                require_case_anchor=require_case_narrative,
            )
        evidence_ids = claim.get("evidence_record_ids") or []
        revision_ids = claim.get("profile_revision_ids") or []
        if not isinstance(evidence_ids, list) or not isinstance(revision_ids, list):
            raise ValueError("claim anchors must be arrays")
        if not evidence_ids and not revision_ids:
            raise ValueError(
                "every brief claim must cite evidence or a profile observation"
            )
        fingerprint = compact_json(claim)
        if fingerprint in claim_fingerprints:
            raise ValueError("brief claims must be unique")
        claim_fingerprints.add(fingerprint)
    timeline = brief.get("timeline")
    if not isinstance(timeline, list):
        raise ValueError("brief timeline must be an array")
    timeline_fingerprints: set[str] = set()
    for entry in timeline:
        if not isinstance(entry, dict) or set(entry) != TIMELINE_ENTRY_FIELDS:
            raise ValueError("every brief timeline entry must use the exact schema")
        evidence_ids = _anchor_array(
            entry.get("evidence_record_ids"), "brief timeline evidence_record_ids"
        )
        revision_ids = _anchor_array(
            entry.get("profile_revision_ids"), "brief timeline profile_revision_ids"
        )
        if not evidence_ids and not revision_ids:
            raise ValueError(
                "every brief timeline entry must cite evidence or a profile observation"
            )
        if validate_narratives:
            validate_research_narrative(
                entry.get("statement"),
                "brief timeline statement",
                kind="claim_observation",
                case_anchor_terms=(
                    case_anchor_terms(
                        case_narrative_contract,
                        profile_revision_ids=revision_ids,
                        evidence_record_ids=evidence_ids,
                    )
                    if case_narrative_contract is not None
                    else None
                ),
            )
        fingerprint = compact_json(entry)
        if fingerprint in timeline_fingerprints:
            raise ValueError("brief timeline entries must be unique")
        timeline_fingerprints.add(fingerprint)
    for field in (
        "hypothesis_ids",
        "gap_ids",
        "confirmation_needs",
    ):
        values = brief.get(field)
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value.strip() for value in values
        ):
            raise ValueError(f"brief {field} must be an array of identifiers or text")
        if field in {"hypothesis_ids", "gap_ids"} and len(values) != len(set(values)):
            raise ValueError(f"brief {field} cannot contain duplicates")
    clinician_questions = brief.get("clinician_questions")
    if not isinstance(clinician_questions, list):
        raise ValueError("brief clinician_questions must be an array")
    question_fingerprints: set[str] = set()
    for question in clinician_questions:
        if not isinstance(question, dict) or set(question) != CLINICIAN_QUESTION_FIELDS:
            raise ValueError("every clinician question must use the exact schema")
        evidence_ids = _anchor_array(
            question.get("evidence_record_ids"),
            "clinician question evidence_record_ids",
        )
        revision_ids = _anchor_array(
            question.get("profile_revision_ids"),
            "clinician question profile_revision_ids",
        )
        _anchor_array(
            question.get("hypothesis_ids"), "clinician question hypothesis_ids"
        )
        _anchor_array(question.get("gap_ids"), "clinician question gap_ids")
        if not evidence_ids and not revision_ids:
            raise ValueError(
                "every clinician question must cite evidence or a profile observation"
            )
        if validate_narratives:
            validate_clinician_question(
                question.get("question"),
                "brief clinician question",
                case_anchor_terms=(
                    case_anchor_terms(
                        case_narrative_contract,
                        profile_revision_ids=revision_ids,
                        evidence_record_ids=evidence_ids,
                    )
                    if case_narrative_contract is not None
                    else []
                ),
            )
        fingerprint = compact_json(question)
        if fingerprint in question_fingerprints:
            raise ValueError("brief clinician questions must be unique")
        question_fingerprints.add(fingerprint)
    if brief.get("clinical_boundary") != BRIEF_CLINICAL_BOUNDARY:
        raise ValueError("brief clinical_boundary must preserve the GenomiLab boundary")
    if validate_narratives:
        all_case_terms = (
            case_anchor_terms(case_narrative_contract)
            if case_narrative_contract is not None
            else None
        )
        validate_research_narrative(title, "brief title", kind="brief_title")
        validate_research_narrative(
            summary,
            "brief summary",
            kind="brief_summary",
            case_anchor_terms=all_case_terms,
            require_case_anchor=require_case_narrative,
        )
        validate_research_narrative(
            brief.get("change_summary"),
            "brief change_summary",
            kind="change_summary",
            case_anchor_terms=all_case_terms,
            require_case_anchor=require_case_narrative,
        )
        for value in brief["confirmation_needs"]:
            validate_research_narrative(
                value, "brief confirmation need", kind="confirmation_need"
            )


def _anchor_array(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field} must be an array of identifiers")
    if len(value) != len(set(value)):
        raise ValueError(f"{field} cannot contain duplicates")
    return value
