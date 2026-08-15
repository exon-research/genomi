"""Host-neutral ``lab.*`` operation functions.

This is the narrow bridge between the public operation registry and the
local Lab SQLite store. It derives user/session authority from the current Genomi
runtime context and never accepts either identity from operation parameters.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from ..operations.registry.errors import JsonObject, OperationError
from ..operations.registry.evidence_result_receipts import (
    EVIDENCE_RESULT_RECEIPTS,
)
from ..runtime.context import context_authority_lock, context_scope, describe_context
from .result_receipts import durable_genomi_result_receipt_id
from .store import GenomiLabStore


@contextmanager
def _authorized_store() -> Iterator[tuple[GenomiLabStore, str, str]]:
    with context_authority_lock():
        context = describe_context()
        user_id = str(context.get("active_user_id") or "").strip()
        if not user_id:
            raise OperationError(
                "genomi_user_required",
                "Select the Lab workspace user before using Lab operations.",
            )
        session_id = str(context_scope().get("id") or "").strip()
        if not session_id:
            raise OperationError(
                "lab_session_required",
                "Lab operations require the current workspace session boundary.",
            )
        store = GenomiLabStore()

        def require_same_user() -> None:
            current = str(describe_context().get("active_user_id") or "").strip()
            if current != user_id:
                raise ValueError("the active Lab workspace user changed during the operation")

        with store.current_user_authority_guard(require_same_user):
            yield store, user_id, session_id
def _run(action: Callable[[GenomiLabStore, str, str], JsonObject]) -> JsonObject:
    try:
        with _authorized_store() as (store, user_id, session_id):
            result = action(store, user_id, session_id)
    except OperationError:
        raise
    except KeyError as exc:
        raise OperationError("lab_record_not_found", str(exc)) from exc
    except ValueError as exc:
        raise OperationError("invalid_lab_request", str(exc)) from exc
    if not isinstance(result, dict):
        raise OperationError(
            "invalid_lab_operation_result", "The Lab store returned a non-object result."
        )
    return result


def _owned(store: GenomiLabStore, user_id: str, investigation_id: str) -> None:
    investigation = store.get_investigation(investigation_id)
    if str(investigation.get("user_id") or "") != user_id:
        raise KeyError(investigation_id)


def _required(params: JsonObject, field: str) -> str:
    value = params.get(field)
    if not isinstance(value, str) or not value.strip():
        raise OperationError("invalid_params", f"{field} is required")
    return value.strip()


def _invoke_store_operation(method_name: str, params: JsonObject) -> JsonObject:
    investigation_id = _required(params, "investigation_id")

    def invoke(store: GenomiLabStore, user_id: str, session_id: str) -> JsonObject:
        _owned(store, user_id, investigation_id)
        method = getattr(store, method_name, None)
        if not callable(method):
            raise OperationError(
                "lab_operation_unavailable",
                f"The Lab store does not implement {method_name!r}.",
            )
        kwargs = {key: value for key, value in params.items() if key != "investigation_id"}
        if method_name == "prepare_specialist_brief":
            kwargs["workspace_session_id"] = session_id
        return method(investigation_id, **kwargs)

    return _run(invoke)


def create_investigation(params: JsonObject) -> JsonObject:
    def create(store: GenomiLabStore, user_id: str, session_id: str) -> JsonObject:
        try:
            store.get_workspace(user_id)
        except KeyError:
            store.open_workspace(user_id)
        return store.create_lab_investigation(
            user_id,
            workspace_session_id=session_id,
            question=params.get("question"),
            disease_scope=params.get("disease_scope"),
            public_only=params.get("public_only", False),
            approved_profile_context=None,
            command_id=params.get("command_id"),
        )

    return _run(create)


def update_health_profile(params: JsonObject) -> JsonObject:
    investigation_id = _required(params, "investigation_id")

    def update(store: GenomiLabStore, user_id: str, session_id: str) -> JsonObject:
        _owned(store, user_id, investigation_id)
        context = describe_context()
        active = context.get("active_genome_index")
        access = context.get("active_genome_index_access")
        selected_agi_context = None
        if (
            isinstance(active, dict)
            and isinstance(access, dict)
            and access.get("approved") is True
        ):
            agi_id = str(context.get("active_agi_id") or active.get("agi_id") or "")
            agi_snapshot_id = str(active.get("agi_snapshot_id") or "")
            if not agi_id or not agi_snapshot_id:
                raise OperationError(
                    "invalid_selected_active_genome_index",
                    "The selected approved Active Genome Index has no immutable snapshot binding.",
                )
            selected_agi_context = {
                "access_approved": True,
                "agi_id": agi_id,
                "agi_snapshot_id": agi_snapshot_id,
            }
        return store.update_health_profile(
            user_id,
            investigation_id,
            workspace_session_id=session_id,
            facts=params.get("facts"),
            purpose=params.get("purpose"),
            selected_agi_context=selected_agi_context,
            command_id=params.get("command_id"),
            expected_revision=params.get("expected_revision"),
        )

    return _run(update)


def read_investigation(params: JsonObject) -> JsonObject:
    investigation_id = _required(params, "investigation_id")

    def read(store: GenomiLabStore, user_id: str, _session_id: str) -> JsonObject:
        _owned(store, user_id, investigation_id)
        return {
            "status": "ready",
            **store.read_orchestrator_investigation(
                investigation_id,
                include_history=bool(params.get("include_history", False)),
            ),
        }

    return _run(read)


def create_cycle(params: JsonObject) -> JsonObject:
    investigation_id = _required(params, "investigation_id")

    def create(store: GenomiLabStore, user_id: str, _session_id: str) -> JsonObject:
        _owned(store, user_id, investigation_id)
        return store.create_investigation_cycle(
            investigation_id,
            purpose=params.get("purpose"),
            patient_molecular_snapshot_id=params.get("profile_snapshot_id"),
            prior_cycle_id=params.get("prior_cycle_id"),
            public_only=params.get("public_only", False),
            command_id=params.get("command_id"),
            expected_revision=params.get("expected_revision"),
        )

    return _run(create)


def create_hypothesis(params: JsonObject) -> JsonObject:
    return _invoke_store_operation(
        "create_hypothesis",
        {
            **params,
            "profile_snapshot_id": params.get("profile_snapshot_id"),
            "evidence_snapshot_id": params.get("evidence_snapshot_id"),
        },
    )


def revise_hypothesis(params: JsonObject) -> JsonObject:
    return _invoke_store_operation(
        "revise_hypothesis",
        {
            **params,
            "profile_snapshot_id": params.get("profile_snapshot_id"),
            "evidence_snapshot_id": params.get("evidence_snapshot_id"),
        },
    )


def prepare_specialist_brief(params: JsonObject) -> JsonObject:
    investigation_id = _required(params, "investigation_id")

    def prepare(store: GenomiLabStore, user_id: str, session_id: str) -> JsonObject:
        _owned(store, user_id, investigation_id)
        return store.prepare_specialist_brief(
            investigation_id,
            cycle_id=params.get("cycle_id"),
            specialist_role=params.get("specialist_role"),
            execution_policy=params.get("execution_policy"),
            research_question=params.get("research_question"),
            public_concepts=params.get("public_concepts"),
            abstract_relations=params.get("abstract_event_relations"),
            public_evidence_record_ids=params.get("public_evidence_record_ids"),
            source_fact_ids=params.get("source_fact_ids"),
            rationale=params.get("purpose"),
            purpose=params.get("purpose"),
            workspace_session_id=session_id,
            command_id=params.get("command_id"),
            expected_revision=params.get("expected_revision"),
        )
    return _run(prepare)


def create_specialist_assignment(params: JsonObject) -> JsonObject:
    return _invoke_store_operation("create_specialist_assignment", params)


def transition_specialist_assignment(params: JsonObject) -> JsonObject:
    investigation_id = _required(params, "investigation_id")
    assignment_id = _required(params, "assignment_id")

    def transition(store: GenomiLabStore, user_id: str, _session_id: str) -> JsonObject:
        _owned(store, user_id, investigation_id)
        with store._connect() as connection:
            assignment = connection.execute(
                "SELECT revision FROM specialist_assignments "
                "WHERE specialist_assignment_id = ? AND investigation_id = ?",
                (assignment_id, investigation_id),
            ).fetchone()
        if assignment is None:
            raise KeyError(assignment_id)
        failure = params.get("failure")
        reason = None
        if isinstance(failure, dict):
            reason = str(failure.get("message") or failure.get("code") or "") or None
        return store.transition_specialist_assignment(
            investigation_id,
            specialist_assignment_id=assignment_id,
            to_state=params.get("to_state"),
            assignment_expected_revision=int(assignment["revision"]),
            command_id=params.get("command_id"),
            expected_revision=params.get("expected_revision"),
            native_agent_id=params.get("native_agent_id"),
            reason=reason,
            analysis=(
                {
                    "general_analysis": params.get("general_finding"),
                    "uncertainty": [],
                    "alternatives": [],
                    "gaps": [],
                }
                if params.get("general_finding") is not None
                else None
            ),
        )

    return _run(transition)


def capture_evidence_result(params: JsonObject) -> JsonObject:
    investigation_id = _required(params, "investigation_id")
    process_receipt_id = _required(params, "result_receipt_id")

    def capture(store: GenomiLabStore, user_id: str, session_id: str) -> JsonObject:
        _owned(store, user_id, investigation_id)
        durable_receipt_id = durable_genomi_result_receipt_id(process_receipt_id)
        capture_args = {
            "cycle_id": params.get("cycle_id"),
            "result_receipt_id": durable_receipt_id,
            "purpose": params.get("purpose"),
            "command_id": params.get("command_id"),
            "expected_revision": params.get("expected_revision"),
        }
        try:
            store.get_genomi_result_receipt(durable_receipt_id)
        except KeyError:
            def persist(resolved: JsonObject) -> JsonObject:
                with store.atomic_write():
                    issued = store.issue_genomi_result_receipt(
                        operation=resolved.get("operation"),
                        params=resolved.get("params"),
                        presented_result=resolved.get("result"),
                        investigation_id=investigation_id,
                        workspace_session_id=session_id,
                        receipt_token=process_receipt_id,
                    )
                    if issued != durable_receipt_id:
                        raise ValueError("durable result receipt identity mismatch")
                    return store.capture_evidence_result(
                        investigation_id, **capture_args
                    )

            return EVIDENCE_RESULT_RECEIPTS.redeem(
                process_receipt_id,
                session_id=session_id,
                consumer=persist,
            )
        return store.capture_evidence_result(investigation_id, **capture_args)

    return _run(capture)


def capture_provider_result(params: JsonObject) -> JsonObject:
    return _invoke_store_operation("capture_provider_result", params)


def publish_brief(params: JsonObject) -> JsonObject:
    return _invoke_store_operation("publish_brief", params)


__all__ = [
    "capture_evidence_result",
    "capture_provider_result",
    "create_cycle",
    "create_hypothesis",
    "create_investigation",
    "create_specialist_assignment",
    "prepare_specialist_brief",
    "publish_brief",
    "read_investigation",
    "revise_hypothesis",
    "transition_specialist_assignment",
    "update_health_profile",
]
