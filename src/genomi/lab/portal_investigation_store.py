"""Canonical persisted investigation state used by the portal board."""

from __future__ import annotations

from typing import Any, ContextManager, Protocol

from .models import JsonObject, row_dict


class _PortalInvestigationStore(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def read_orchestrator_investigation(
        self, investigation_id: str, *, include_history: bool = False
    ) -> JsonObject: ...


class PortalInvestigationStoreMixin:
    """Complete the orchestrator read with board-visible durable records."""

    def read_portal_investigation(
        self: _PortalInvestigationStore,
        investigation_id: str,
        *,
        include_history: bool = True,
    ) -> JsonObject:
        view = self.read_orchestrator_investigation(
            investigation_id, include_history=include_history
        )
        with self._connect() as connection:
            evidence_records = connection.execute(
                "SELECT * FROM evidence_records WHERE investigation_id = ? "
                "ORDER BY created_at",
                (investigation_id,),
            ).fetchall()
            research_artifacts = connection.execute(
                "SELECT * FROM research_artifacts WHERE investigation_id = ? "
                "ORDER BY created_at",
                (investigation_id,),
            ).fetchall()
            specialist_analyses = connection.execute(
                "SELECT analysis.* FROM specialist_analyses AS analysis "
                "JOIN specialist_assignments AS assignment ON "
                "assignment.specialist_assignment_id = "
                "analysis.specialist_assignment_id "
                "WHERE assignment.investigation_id = ? ORDER BY analysis.created_at",
                (investigation_id,),
            ).fetchall()
        return {
            **view,
            "evidence_records": [row_dict(row) for row in evidence_records],
            "research_artifacts": [row_dict(row) for row in research_artifacts],
            "specialist_analyses": [row_dict(row) for row in specialist_analyses],
        }


__all__ = ["PortalInvestigationStoreMixin"]
