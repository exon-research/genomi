"""Typed artifact categories for GenomiLab investigation records."""

from __future__ import annotations

from enum import Enum


class AgentArtifactKind(str, Enum):
    """Durable domain artifacts accepted from the current underlying agent."""

    PLAN = "plan"
    EXECUTION_REPORT = "execution_report"
    BRIEF_DRAFT = "brief_draft"


__all__ = ["AgentArtifactKind"]
