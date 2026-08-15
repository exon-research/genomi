"""Canonical validation for evidence-grounded Genomi Lab briefs."""

from __future__ import annotations

from typing import Collection

from .brief_provenance import ALLOWED_MODALITY_BADGES
from .models import (
    QUESTION_MAX,
    JsonObject,
    compact_json,
    required_text,
    validate_private_payload,
)
from .research_narrative import validate_research_narrative


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
def validate_brief_artifact(
    brief: JsonObject,
    *,
    allowed_modality_badges: Collection[str] | None = None,
) -> None:
    validate_private_payload(brief)
    if str(brief.get("clinical_stage") or "") not in AGENT_CLINICAL_STAGES:
        raise ValueError(
            "research briefs may use only research_observation or candidate_hypothesis; "
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
        validate_research_narrative(
            claim.get("statement"),
            "brief claim",
            kind={
                "observation": "claim_observation",
                "candidate_hypothesis": "claim_candidate_hypothesis",
                "counterevidence": "claim_counterevidence",
                "limitation": "claim_limitation",
            }[claim_role],
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
    for field in (
        "hypothesis_ids",
        "gap_ids",
        "confirmation_needs",
        "professional_questions",
    ):
        values = brief.get(field)
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value.strip() for value in values
        ):
            raise ValueError(f"brief {field} must be an array of identifiers or text")
        if field in {"hypothesis_ids", "gap_ids"} and len(values) != len(set(values)):
            raise ValueError(f"brief {field} cannot contain duplicates")
    if brief.get("clinical_boundary") != BRIEF_CLINICAL_BOUNDARY:
        raise ValueError("brief clinical_boundary must preserve the GenomiLab boundary")
    validate_research_narrative(title, "brief title", kind="brief_title")
    validate_research_narrative(summary, "brief summary", kind="brief_summary")
    validate_research_narrative(
        brief.get("change_summary"),
        "brief change_summary",
        kind="change_summary",
    )
    for value in brief["confirmation_needs"]:
        validate_research_narrative(
            value, "brief confirmation need", kind="confirmation_need"
        )
    for value in brief["professional_questions"]:
        validate_research_narrative(
            value, "brief professional question", kind="professional_question"
        )
