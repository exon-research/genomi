"""Typed, reusable patient-visible narrative statements.

Agent-facing schemas, runtime validation, and deterministic capability templates
all consume this registry.  The identifier is the domain value; text is its
presentation.  This prevents independent allowlists from drifting while the
wire format remains plain JSON text.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class NarrativeStatementId(StrEnum):
    PLAN_SUMMARY = "plan.summary.review_current_evidence"
    PLAN_STEP_TITLE = "plan.step.review_evidence"
    PLAN_STEP_RATIONALE = "plan.step.assess_approved_evidence"
    PLAN_ROLE_OBJECTIVE = "plan.role.review_approved_evidence"
    EXECUTION_SUMMARY = "execution.summary.exact_requests_executed"
    BRIEF_SUMMARY_OBSERVATION = "brief.summary.research_observation"
    BRIEF_SUMMARY_CANDIDATE = "brief.summary.candidate_with_confirmation_gap"
    BRIEF_CHANGE_SUMMARY = "brief.change.prepared_traceable_brief"
    BRIEF_CLINICAL_BOUNDARY = "brief.boundary.research_support_only"
    CONFIRMATION_NEED = "brief.confirmation.independent_clinical"
    QUESTION_DIAGNOSTIC = "brief.question.diagnostic"
    QUESTION_ACTIONABLE = "brief.question.actionable"
    QUESTION_ACTIONABILITY_EVIDENCE = "brief.question.actionability_evidence"
    QUESTION_INDEPENDENT_TESTING = "brief.question.independent_testing"
    CLAIM_PATIENT_REPORTED_PHENOTYPE = "claim.observation.patient_reported_phenotype"
    CLAIM_PATIENT_REPORTED_CONDITION = "claim.observation.patient_reported_condition"
    CLAIM_ISSUED_RECORD_FINDING = "claim.observation.issued_record_finding"
    CLAIM_MATCHING_GENOTYPE = "claim.observation.matching_genotype"
    CLAIM_REGISTERED_RELATION = "claim.observation.registered_relation"
    CLAIM_SOURCE_RESEARCH_OBSERVATION = "claim.observation.source_research"
    CLAIM_PROFILE_RESEARCH_OBSERVATION = "claim.observation.profile_research"
    CLAIM_CANDIDATE_MECHANISM = "claim.candidate.mechanism"
    CLAIM_COUNTEREVIDENCE = "claim.counterevidence.source"
    CLAIM_CONFIRMATION_GAP = "claim.limitation.confirmation_gap"


@dataclass(frozen=True, slots=True)
class NarrativeStatement:
    statement_id: NarrativeStatementId
    text: str
    kinds: frozenset[str]
    claim_role: str | None = None


def _statement(
    statement_id: NarrativeStatementId,
    text: str,
    *kinds: str,
    claim_role: str | None = None,
) -> NarrativeStatement:
    return NarrativeStatement(statement_id, text, frozenset(kinds), claim_role)


_CANDIDATE_MECHANISM_TEXT = (
    "Model inference: The finding may contribute to the reported condition, but "
    "this remains only a candidate hypothesis; causality, mechanism, and clinical "
    "significance are unestablished."
)
_CONFIRMATION_GAP_TEXT = (
    "Evidence gap: Independent clinical confirmation remains an open requirement."
)

_STATEMENTS = (
    _statement(
        NarrativeStatementId.PLAN_SUMMARY,
        "Review the current evidence plan.",
        "plan_summary",
    ),
    _statement(
        NarrativeStatementId.PLAN_STEP_TITLE,
        "Review evidence.",
        "plan_step_title",
    ),
    _statement(
        NarrativeStatementId.PLAN_STEP_RATIONALE,
        "Use the approved evidence to assess the hypothesis.",
        "plan_step_rationale",
    ),
    _statement(
        NarrativeStatementId.PLAN_ROLE_OBJECTIVE,
        "Review approved evidence.",
        "plan_role_objective",
    ),
    _statement(
        NarrativeStatementId.EXECUTION_SUMMARY,
        "The exact accepted requests were executed.",
        "execution_summary",
    ),
    _statement(
        NarrativeStatementId.BRIEF_SUMMARY_OBSERVATION,
        "The approved record remains a research observation.",
        "brief_summary",
    ),
    _statement(
        NarrativeStatementId.BRIEF_SUMMARY_CANDIDATE,
        f"{_CANDIDATE_MECHANISM_TEXT} {_CONFIRMATION_GAP_TEXT}",
        "brief_summary",
    ),
    _statement(
        NarrativeStatementId.BRIEF_CHANGE_SUMMARY,
        "Prepared a traceable research brief.",
        "change_summary",
    ),
    _statement(
        NarrativeStatementId.BRIEF_CLINICAL_BOUNDARY,
        "Research support only; this is not a diagnosis or treatment decision.",
        "assertion",
    ),
    _statement(
        NarrativeStatementId.CONFIRMATION_NEED,
        "The finding requires independent clinical confirmation.",
        "confirmation_need",
    ),
    _statement(
        NarrativeStatementId.QUESTION_DIAGNOSTIC,
        "Is this diagnostic?",
        "professional_question",
    ),
    _statement(
        NarrativeStatementId.QUESTION_ACTIONABLE,
        "Is this medically actionable?",
        "professional_question",
    ),
    _statement(
        NarrativeStatementId.QUESTION_ACTIONABILITY_EVIDENCE,
        "What evidence would determine whether this is medically actionable?",
        "professional_question",
    ),
    _statement(
        NarrativeStatementId.QUESTION_INDEPENDENT_TESTING,
        "Can independent testing prove or exclude the diagnosis?",
        "professional_question",
    ),
    _statement(
        NarrativeStatementId.CLAIM_PATIENT_REPORTED_PHENOTYPE,
        "Patient-reported observation: The profile records the phenotype as patient-reported.",
        "claim_observation",
        claim_role="observation",
    ),
    _statement(
        NarrativeStatementId.CLAIM_PATIENT_REPORTED_CONDITION,
        "Patient-reported observation: The profile records the condition as patient-reported.",
        "claim_observation",
        claim_role="observation",
    ),
    _statement(
        NarrativeStatementId.CLAIM_ISSUED_RECORD_FINDING,
        "Patient record observation: An issued laboratory record reports the finding as a research finding.",
        "claim_observation",
        claim_role="observation",
    ),
    _statement(
        NarrativeStatementId.CLAIM_MATCHING_GENOTYPE,
        "Source evidence: The scoped sample evidence contains a matching genotype record.",
        "claim_observation",
        claim_role="observation",
    ),
    _statement(
        NarrativeStatementId.CLAIM_REGISTERED_RELATION,
        "Source evidence: The registered relation records a variant-disease association.",
        "claim_observation",
        claim_role="observation",
    ),
    _statement(
        NarrativeStatementId.CLAIM_SOURCE_RESEARCH_OBSERVATION,
        "Source evidence: The source evidence records a research observation.",
        "claim_observation",
        claim_role="observation",
    ),
    _statement(
        NarrativeStatementId.CLAIM_PROFILE_RESEARCH_OBSERVATION,
        "Patient observation: The profile records a research observation.",
        "claim_observation",
        claim_role="observation",
    ),
    _statement(
        NarrativeStatementId.CLAIM_CANDIDATE_MECHANISM,
        _CANDIDATE_MECHANISM_TEXT,
        "claim_candidate_hypothesis",
        "hypothesis_candidate_mechanism",
        claim_role="candidate_hypothesis",
    ),
    _statement(
        NarrativeStatementId.CLAIM_COUNTEREVIDENCE,
        "Counterevidence: The source evidence weighs against the candidate.",
        "claim_counterevidence",
        "hypothesis_counterevidence",
        claim_role="counterevidence",
    ),
    _statement(
        NarrativeStatementId.CLAIM_CONFIRMATION_GAP,
        _CONFIRMATION_GAP_TEXT,
        "claim_limitation",
        "hypothesis_gap",
        claim_role="limitation",
    ),
)

NARRATIVE_STATEMENTS: Mapping[NarrativeStatementId, NarrativeStatement] = (
    MappingProxyType({statement.statement_id: statement for statement in _STATEMENTS})
)
_BY_TEXT = MappingProxyType({statement.text: statement for statement in _STATEMENTS})
if len(_BY_TEXT) != len(_STATEMENTS):  # pragma: no cover - import-time guard
    raise RuntimeError("canonical narrative statement text must be unique")


def narrative_text(statement_id: NarrativeStatementId) -> str:
    return NARRATIVE_STATEMENTS[statement_id].text


def narrative_texts(
    *, kind: str | None = None, claim_role: str | None = None
) -> list[str]:
    return [
        statement.text
        for statement in _STATEMENTS
        if (kind is None or kind in statement.kinds)
        and (claim_role is None or statement.claim_role == claim_role)
    ]


def declared_narrative(text: str, kind: str) -> NarrativeStatement | None:
    statement = _BY_TEXT.get(text)
    if statement is None or kind not in statement.kinds:
        return None
    return statement


__all__ = [
    "NARRATIVE_STATEMENTS",
    "NarrativeStatement",
    "NarrativeStatementId",
    "declared_narrative",
    "narrative_text",
    "narrative_texts",
]
