from __future__ import annotations

from collections.abc import Iterable
from typing import Any

SKILL_PATH = "SKILL.md"

STAGE_CONTRACTS: dict[str, dict[str, str]] = {
    "static": {
        "name": "Active Genome Indexing and library-scoped evidence materialization",
        "section": "Tool Groups",
        "anchor": "#tool-groups",
    },
    "research": {
        "name": "LLM-guided research based on user intent",
        "section": "Intent Research",
        "anchor": "#intent-research",
    },
    "report": {
        "name": "Markdown report with citations",
        "section": "Reporting",
        "anchor": "#reporting",
    },
    "complete": {
        "name": "Workflow complete",
        "section": "Core Contract",
        "anchor": "#core-contract",
    },
}


def evidence_context(
    stage_id: str,
    *,
    reason: str,
    commands: Iterable[str] | None = None,
    when: str | None = None,
) -> dict[str, Any]:
    """Return related skill context for interpreting evidence output."""

    if stage_id not in STAGE_CONTRACTS:
        raise ValueError(f"unknown evidence context {stage_id!r}")
    contract = STAGE_CONTRACTS[stage_id]
    payload: dict[str, Any] = {
        "id": stage_id,
        "name": contract["name"],
        "reason": reason,
        "skill_contract": {
            "path": SKILL_PATH,
            "section": contract["section"],
            "anchor": contract["anchor"],
        },
    }
    if when:
        payload["relevance"] = when
    return payload


def attach_evidence_context(
    payload: dict[str, Any],
    stage_id: str,
    *,
    reason: str,
    commands: Iterable[str] | None = None,
    when: str | None = None,
) -> dict[str, Any]:
    payload["evidence_context"] = evidence_context(stage_id, reason=reason, commands=commands, when=when)
    return payload


def workflow_step(
    name: str,
    result: dict[str, Any],
    stage_id: str,
    *,
    reason: str,
    commands: Iterable[str] | None = None,
    when: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "result": result,
        "evidence_context": evidence_context(stage_id, reason=reason, commands=commands, when=when),
    }
