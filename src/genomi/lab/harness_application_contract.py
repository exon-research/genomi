"""Structural contract shared by GenomiLab harness application components."""

from __future__ import annotations

from typing import Any, Callable, Protocol

from .harness import EventReplay, HarnessAdapter, HarnessCommand, HarnessOperation
from .models import JsonObject


class HarnessApplication(Protocol):
    """Capabilities supplied by the composed GenomiLab application service."""

    store: Any
    session_id: str
    harness_adapter: HarnessAdapter
    _operation_lock: Any
    _current_user_authority_epoch: int
    _closed: bool

    def _current_context(self) -> tuple[JsonObject, str]: ...

    def _run_current_user_operation(
        self, bound_method: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any: ...

    def investigation(self, investigation_id: str) -> JsonObject: ...

    def _approved_investigation_profile(self, investigation_id: str) -> JsonObject: ...

    def _active_context_receipt(
        self, investigation: JsonObject, snapshot: JsonObject
    ) -> JsonObject: ...

    def investigation_capability_catalog(self, investigation_id: str) -> JsonObject: ...

    def validate_harness_capability_plan(
        self, investigation_id: str, plan: JsonObject
    ) -> None: ...

    def _accepted_current_plan(self, investigation_id: str) -> JsonObject: ...

    def _require_investigation_authorization(
        self,
        investigation_id: str,
        *,
        intent: str,
        receipt: JsonObject | None = None,
    ) -> JsonObject: ...

    def _authorization_intent_for_harness_command(
        self, command: HarnessCommand
    ) -> str: ...

    def _continue_authorized_harness_flow(
        self,
        command: HarnessCommand,
        committed: JsonObject,
        *,
        receipt_id: str,
    ) -> None: ...

    def _persisted_capability_result(self, execution: JsonObject) -> JsonObject: ...

    def _accepted_plan_transport_context(
        self, investigation: JsonObject
    ) -> JsonObject: ...

    def _latest_transport_cursor(self, investigation_id: str) -> int: ...

    def _latest_domain_event_sequence(self, investigation_id: str) -> int: ...

    def _commit_pending_harness_events(
        self, investigation_id: str
    ) -> list[JsonObject]: ...

    def _commit_harness_response(
        self,
        command: HarnessCommand,
        response: Any,
        *,
        binding: JsonObject | None,
        replay: EventReplay | None = None,
    ) -> JsonObject: ...

    def _interrupted_dispatch_response(
        self,
        *,
        command_id: str,
        operation: HarnessOperation,
        disclosure_receipt_id: object,
        binding: JsonObject | None,
        dispatch_outcome: str = "unknown",
    ) -> JsonObject: ...

    def _attest_execution_report_to_capability_ledger(
        self,
        investigation_id: str,
        *,
        investigation: JsonObject,
        current_plan: JsonObject,
        artifact: JsonObject,
    ) -> dict[str, JsonObject]: ...


__all__ = ["HarnessApplication"]
