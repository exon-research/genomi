"""Patient-authorized transitions for a host-owned investigation."""

from __future__ import annotations

from .models import JsonObject


class InvestigationAuthorizedFlowMixin:
    """Authorize private context and continue exact Genomi capability work.

    Claude, Codex, or another MCP host owns planning and every host-task
    lifecycle operation.  This mixin contains only GenomiLab domain
    transitions and checks of resumable evidence-provider jobs.
    """

    def investigation_authorization_candidate(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        return self._investigation_authorizations.candidate(
            investigation_id, payload
        )

    def authorize_investigation_context(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        with self._operation_lock:
            return self._investigation_authorizations.authorize_context(
                investigation_id, payload
            )

    def _require_investigation_authorization(
        self,
        investigation_id: str,
        *,
        intent: str,
        receipt: JsonObject | None = None,
    ) -> JsonObject:
        return self._investigation_authorizations.require_current(
            investigation_id, intent=intent, receipt=receipt
        )

    def approve_and_continue_capability(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        """Run the exact provider request the patient just approved."""

        with self._operation_lock:
            self._require_specialist_board(investigation_id)
            self._require_investigation_authorization(
                investigation_id, intent="resume"
            )
            result = self._continue_agent_capability_after_approval(
                investigation_id, payload
            )
            return self._record_capability_result_event(
                investigation_id, payload, result
            )

    def check_capability_request(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        """Check one persisted Genomi/provider job without resuming a host task."""

        with self._operation_lock:
            self._require_specialist_board(investigation_id)
            self._require_investigation_authorization(
                investigation_id, intent="resume"
            )
            result = self._check_agent_capability_job(
                investigation_id, payload
            )
            return self._record_capability_result_event(
                investigation_id, payload, result
            )

    def _record_capability_result_event(
        self,
        investigation_id: str,
        request: JsonObject,
        result: JsonObject,
    ) -> JsonObject:
        request_id = str(
            result.get("request_id") or request.get("request_id") or ""
        )
        capability = str(result.get("capability") or "")
        result_status = str(result.get("status") or "failed")
        event_status = (
            result_status
            if result_status in {"in_progress", "approval_required"}
            else "completed"
            if result_status
            in {
                "committed",
                "completed",
                "projected",
                "registered",
                "data_returned",
            }
            else "failed"
        )
        already_committed = any(
            event.get("event_type") == "request_state_changed"
            and (event.get("payload") or {}).get("request_id") == request_id
            and (event.get("payload") or {}).get("capability") == capability
            and (event.get("payload") or {}).get("status") == event_status
            for event in self.store.replay_investigation_events(investigation_id)
        )
        if not already_committed:
            self._append_agent_event(
                investigation_id,
                "request_state_changed",
                {
                    "request_id": request_id,
                    "capability": capability,
                    "status": event_status,
                },
            )
        return {**result, "execution_owner": "underlying_agent"}


__all__ = ["InvestigationAuthorizedFlowMixin"]
