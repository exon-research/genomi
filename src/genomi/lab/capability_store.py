"""Durable, exactly-once claims for agent-selected capability work."""

from __future__ import annotations

import uuid
from typing import Any, ContextManager, Protocol

from .models import JsonObject, compact_json, required_text, row_dict, utc_now


CAPABILITY_EXECUTION_STATUSES = frozenset(
    {"in_progress", "approval_required", "completed", "failed"}
)
CAPABILITY_RETRY_OPERATION = "genomilab.capability.execute"


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def append_investigation_event(
        self,
        investigation_id: str,
        *,
        event_type: object,
        payload: JsonObject,
    ) -> JsonObject: ...

    def _append_investigation_event(
        self,
        connection: Any,
        investigation_id: str,
        *,
        event_type: object,
        payload: JsonObject,
    ) -> JsonObject: ...


class CapabilityExecutionStoreMixin:
    """Own execution and attempt state around an external side-effect boundary."""

    def get_capability_execution(
        self: _StoreContract,
        investigation_id: str,
        plan_version_id: str,
        request_id: str,
    ) -> JsonObject | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM capability_executions WHERE investigation_id = ? "
                "AND plan_version_id = ? AND request_id = ?",
                (investigation_id, plan_version_id, request_id),
            ).fetchone()
            if row is None:
                return None
            attempts = connection.execute(
                "SELECT * FROM capability_execution_attempts "
                "WHERE capability_execution_id = ? ORDER BY attempt_number",
                (row["capability_execution_id"],),
            ).fetchall()
        return self._execution_view(row, attempts)

    def claim_capability_execution(
        self: _StoreContract,
        *,
        investigation_id: object,
        plan_version_id: object,
        consent_receipt_id: object,
        request_id: object,
        capability: object,
        request_fingerprint: object,
        attempt_fingerprint: object,
        attempt_kind: str,
        approval_provider: object = None,
        approval_payload_sha256: object = None,
        event_type: object = None,
        event_payload: JsonObject | None = None,
    ) -> JsonObject:
        """Atomically create an in-progress attempt before its side effect runs."""

        investigation = required_text(investigation_id, "investigation_id", 200)
        plan_version = required_text(plan_version_id, "plan_version_id", 200)
        consent_receipt = required_text(
            consent_receipt_id, "consent_receipt_id", 200
        )
        request = required_text(request_id, "request_id", 200)
        capability_value = required_text(capability, "capability", 200)
        request_hash = required_text(request_fingerprint, "request_fingerprint", 128)
        attempt_hash = required_text(attempt_fingerprint, "attempt_fingerprint", 128)
        if attempt_kind not in {"initial", "approval_continuation"}:
            raise ValueError("unsupported capability attempt kind")
        provider = (
            required_text(approval_provider, "approval_provider", 200)
            if approval_provider not in (None, "")
            else None
        )
        payload_hash = (
            required_text(approval_payload_sha256, "approval_payload_sha256", 128)
            if approval_payload_sha256 not in (None, "")
            else None
        )
        if attempt_kind == "initial" and (
            provider is not None or payload_hash is not None
        ):
            raise ValueError(
                "initial capability attempts cannot carry provider approval"
            )
        if attempt_kind == "approval_continuation" and (
            provider is None or payload_hash is None
        ):
            raise ValueError(
                "approval continuation requires an exact provider and payload hash"
            )
        if (event_type is None) != (event_payload is None):
            raise ValueError("capability claim event type and payload must be supplied together")

        now = utc_now()
        with self._connect() as connection:
            self._require_current_capability_authority(
                connection,
                investigation_id=investigation,
                plan_version_id=plan_version,
                consent_receipt_id=consent_receipt,
            )
            existing = connection.execute(
                "SELECT * FROM capability_executions WHERE investigation_id = ? "
                "AND plan_version_id = ? AND request_id = ?",
                (investigation, plan_version, request),
            ).fetchone()
            if existing is None:
                if attempt_kind != "initial":
                    raise ValueError(
                        "approval continuation requires a prior approval-required attempt"
                    )
                execution_id = f"capability-execution-{uuid.uuid4().hex}"
                attempt_number = 1
                job_id = f"capability-job-{uuid.uuid4().hex}"
                running = self._claimed_result(job_id)
                connection.execute(
                    "INSERT INTO capability_executions("
                    "capability_execution_id, investigation_id, plan_version_id, "
                    "consent_receipt_id, request_id, capability, request_fingerprint, status, result_json, "
                    "claim_job_id, job_id, resume_operation, poll_after_seconds, active_attempt_number, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'in_progress', "
                    "?, ?, ?, ?, 1, ?, ?, ?)",
                    (
                        execution_id,
                        investigation,
                        plan_version,
                        consent_receipt,
                        request,
                        capability_value,
                        request_hash,
                        compact_json(running),
                        job_id,
                        job_id,
                        CAPABILITY_RETRY_OPERATION,
                        attempt_number,
                        now,
                        now,
                    ),
                )
            else:
                if (
                    str(existing["request_fingerprint"]) != request_hash
                    or str(existing["capability"]) != capability_value
                    or str(existing["consent_receipt_id"]) != consent_receipt
                ):
                    raise ValueError(
                        "capability request id was reused with different parameters"
                    )
                execution_id = str(existing["capability_execution_id"])
                same_attempt = connection.execute(
                    "SELECT 1 FROM capability_execution_attempts "
                    "WHERE capability_execution_id = ? AND attempt_fingerprint = ?",
                    (execution_id, attempt_hash),
                ).fetchone()
                if same_attempt is not None:
                    row, attempts = self._execution_rows(connection, execution_id)
                    result = self._execution_view(row, attempts)
                    result["claimed"] = False
                    return result
                if (
                    attempt_kind != "approval_continuation"
                    or str(existing["status"]) != "approval_required"
                ):
                    raise ValueError(
                        "capability request id was reused with a different execution attempt"
                    )
                attempt_number = int(existing["active_attempt_number"]) + 1
                job_id = f"capability-job-{uuid.uuid4().hex}"
                running = self._claimed_result(job_id)
                connection.execute(
                    "UPDATE capability_executions SET status = 'in_progress', "
                    "result_json = ?, claim_job_id = ?, job_id = ?, resume_operation = ?, "
                    "poll_after_seconds = 1, active_attempt_number = ?, updated_at = ? "
                    "WHERE capability_execution_id = ? AND status = 'approval_required'",
                    (
                        compact_json(running),
                        job_id,
                        job_id,
                        CAPABILITY_RETRY_OPERATION,
                        attempt_number,
                        now,
                        execution_id,
                    ),
                )

            attempt_id = f"capability-attempt-{uuid.uuid4().hex}"
            connection.execute(
                "INSERT INTO capability_execution_attempts("
                "capability_attempt_id, capability_execution_id, attempt_number, "
                "attempt_kind, attempt_fingerprint, approval_provider, "
                "approval_payload_sha256, status, result_json, claim_job_id, job_id, "
                "resume_operation, poll_after_seconds, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'in_progress', ?, ?, ?, ?, 1, ?)",
                (
                    attempt_id,
                    execution_id,
                    attempt_number,
                    attempt_kind,
                    attempt_hash,
                    provider,
                    payload_hash,
                    compact_json(running),
                    job_id,
                    job_id,
                    CAPABILITY_RETRY_OPERATION,
                    now,
                ),
            )
            if event_type is not None and event_payload is not None:
                self._append_investigation_event(
                    connection,
                    investigation,
                    event_type=event_type,
                    payload=event_payload,
                )
            row, attempts = self._execution_rows(connection, execution_id)
        result = self._execution_view(row, attempts)
        result["claimed"] = True
        return result

    def finish_capability_execution(
        self: _StoreContract,
        capability_execution_id: str,
        *,
        attempt_number: int,
        claimed_job_id: str,
        status: str,
        result: JsonObject,
        job_id: object = None,
        resume_operation: object = None,
        poll_after_seconds: object = None,
        event_type: object = None,
        event_payload: JsonObject | None = None,
    ) -> JsonObject:
        """Finish the currently claimed attempt or attach its resumable job."""

        if status not in CAPABILITY_EXECUTION_STATUSES:
            raise ValueError("unsupported capability execution status")
        if not isinstance(result, dict):
            raise ValueError("capability execution result must be an object")
        execution_id = required_text(
            capability_execution_id, "capability_execution_id", 200
        )
        claimed_job = required_text(claimed_job_id, "claimed_job_id", 200)
        next_job = (
            required_text(job_id, "job_id", 500) if job_id not in (None, "") else None
        )
        next_operation = (
            required_text(resume_operation, "resume_operation", 200)
            if resume_operation not in (None, "")
            else None
        )
        poll = int(poll_after_seconds) if poll_after_seconds is not None else None
        if status == "in_progress":
            if next_job is None or next_operation is None:
                raise ValueError(
                    "in-progress capability execution requires job_id and resume_operation"
                )
            if poll is not None and poll <= 0:
                raise ValueError("poll_after_seconds must be positive")
        elif any(value is not None for value in (next_job, next_operation, poll)):
            raise ValueError(
                "background-job fields require in-progress capability execution"
            )
        if (event_type is None) != (event_payload is None):
            raise ValueError("capability finish event type and payload must be supplied together")
        finished_at = None if status == "in_progress" else utc_now()
        now = utc_now()
        with self._connect() as connection:
            current = connection.execute(
                "SELECT * FROM capability_executions WHERE capability_execution_id = ?",
                (execution_id,),
            ).fetchone()
            if current is None:
                raise KeyError(execution_id)
            self._require_current_capability_authority(
                connection,
                investigation_id=str(current["investigation_id"]),
                plan_version_id=str(current["plan_version_id"]),
                consent_receipt_id=str(current["consent_receipt_id"]),
            )
            attempt = connection.execute(
                "SELECT * FROM capability_execution_attempts "
                "WHERE capability_execution_id = ? AND attempt_number = ?",
                (execution_id, int(attempt_number)),
            ).fetchone()
            if attempt is None:
                raise KeyError(f"{execution_id}:{attempt_number}")
            if int(current["active_attempt_number"]) != int(attempt_number):
                raise ValueError("capability attempt is no longer active")
            if str(attempt["claim_job_id"] or "") != claimed_job:
                raise ValueError("capability attempt claim does not match")
            if str(attempt["status"]) != "in_progress":
                existing = row_dict(attempt)
                if existing.get("status") != status or existing.get("result") != result:
                    raise ValueError("finished capability attempt result changed")
                row, attempts = self._execution_rows(connection, execution_id)
                return self._execution_view(row, attempts)
            effective_job = next_job
            effective_operation = next_operation
            effective_poll = poll
            if (
                status != "in_progress"
                and str(current["resume_operation"] or "")
                not in {"", CAPABILITY_RETRY_OPERATION}
            ):
                # Retain the exact upstream job binding as immutable provenance
                # so a repeated check after completion can be answered from the
                # ledger without calling the owner again.
                effective_job = str(current["job_id"])
                effective_operation = str(current["resume_operation"])
                effective_poll = None
            connection.execute(
                "UPDATE capability_execution_attempts SET status = ?, result_json = ?, "
                "job_id = ?, resume_operation = ?, poll_after_seconds = ?, "
                "finished_at = ? WHERE capability_execution_id = ? "
                "AND attempt_number = ? AND status = 'in_progress'",
                (
                    status,
                    compact_json(result),
                    effective_job,
                    effective_operation,
                    effective_poll,
                    finished_at,
                    execution_id,
                    int(attempt_number),
                ),
            )
            connection.execute(
                "UPDATE capability_executions SET status = ?, result_json = ?, "
                "job_id = ?, resume_operation = ?, poll_after_seconds = ?, updated_at = ? "
                "WHERE capability_execution_id = ? AND active_attempt_number = ?",
                (
                    status,
                    compact_json(result),
                    effective_job,
                    effective_operation,
                    effective_poll,
                    now,
                    execution_id,
                    int(attempt_number),
                ),
            )
            if event_type is not None and event_payload is not None:
                self._append_investigation_event(
                    connection,
                    str(current["investigation_id"]),
                    event_type=event_type,
                    payload=event_payload,
                )
            row, attempts = self._execution_rows(connection, execution_id)
        return self._execution_view(row, attempts)

    def reconcile_capability_execution(
        self: _StoreContract,
        capability_execution_id: str,
        *,
        expected_job_id: str,
    ) -> JsonObject:
        """Terminally mark an unresolved local dispatch without re-running it."""

        execution_id = required_text(
            capability_execution_id, "capability_execution_id", 200
        )
        job_id = required_text(expected_job_id, "expected_job_id", 500)
        result: JsonObject = {
            "status": "capability_dispatch_outcome_unknown",
            "retry_safe": False,
            "requires_manual_reconciliation": True,
            "message": (
                "Capability dispatch was interrupted after its durable claim. "
                "GenomiLab did not execute it again."
            ),
        }
        now = utc_now()
        with self._connect() as connection:
            current = connection.execute(
                "SELECT * FROM capability_executions WHERE capability_execution_id = ?",
                (execution_id,),
            ).fetchone()
            if current is None:
                raise KeyError(execution_id)
            if str(current["status"]) != "in_progress":
                row, attempts = self._execution_rows(connection, execution_id)
                return self._execution_view(row, attempts)
            if str(current["job_id"] or "") != job_id:
                raise ValueError("capability execution job does not match")
            if str(current["resume_operation"] or "") != CAPABILITY_RETRY_OPERATION:
                raise ValueError(
                    "an upstream background job must be resumed through its declared operation"
                )
            attempt_number = int(current["active_attempt_number"])
            attempt = connection.execute(
                "SELECT * FROM capability_execution_attempts "
                "WHERE capability_execution_id = ? AND attempt_number = ?",
                (execution_id, attempt_number),
            ).fetchone()
            if attempt is None:
                raise KeyError(f"{execution_id}:{attempt_number}")
            if str(attempt["claim_job_id"] or "") != job_id:
                raise ValueError("capability attempt claim does not match")
            updated_attempt = connection.execute(
                "UPDATE capability_execution_attempts SET status = 'failed', "
                "result_json = ?, job_id = NULL, resume_operation = NULL, "
                "poll_after_seconds = NULL, finished_at = ? "
                "WHERE capability_execution_id = ? AND attempt_number = ? "
                "AND status = 'in_progress' AND job_id = ? "
                "AND resume_operation = ?",
                (
                    compact_json(result),
                    now,
                    execution_id,
                    attempt_number,
                    job_id,
                    CAPABILITY_RETRY_OPERATION,
                ),
            )
            if updated_attempt.rowcount != 1:
                raise ValueError("capability execution changed before reconciliation")
            updated_execution = connection.execute(
                "UPDATE capability_executions SET status = 'failed', result_json = ?, "
                "job_id = NULL, resume_operation = NULL, poll_after_seconds = NULL, "
                "updated_at = ? WHERE capability_execution_id = ? "
                "AND active_attempt_number = ? AND status = 'in_progress' "
                "AND job_id = ? AND resume_operation = ?",
                (
                    compact_json(result),
                    now,
                    execution_id,
                    attempt_number,
                    job_id,
                    CAPABILITY_RETRY_OPERATION,
                ),
            )
            if updated_execution.rowcount != 1:
                raise ValueError("capability execution changed before reconciliation")
            row, attempts = self._execution_rows(connection, execution_id)
        return self._execution_view(row, attempts)

    @staticmethod
    def _require_current_capability_authority(
        connection: Any,
        *,
        investigation_id: str,
        plan_version_id: str,
        consent_receipt_id: str,
    ) -> None:
        investigation = connection.execute(
            "SELECT user_id, patient_molecular_snapshot_id, "
            "active_consent_receipt_id FROM investigations "
            "WHERE investigation_id = ?",
            (investigation_id,),
        ).fetchone()
        if investigation is None:
            raise KeyError(investigation_id)
        snapshot_id = investigation["patient_molecular_snapshot_id"]
        current_plan = connection.execute(
            "SELECT plan_version_id FROM plan_versions "
            "WHERE investigation_id = ? AND patient_molecular_snapshot_id IS ? "
            "ORDER BY version DESC LIMIT 1",
            (investigation_id, snapshot_id),
        ).fetchone()
        accepted = (
            connection.execute(
                "SELECT 1 FROM plan_acceptances WHERE plan_version_id = ? "
                "AND investigation_id = ? AND user_id = ?",
                (
                    plan_version_id,
                    investigation_id,
                    investigation["user_id"],
                ),
            ).fetchone()
            if current_plan is not None
            and str(current_plan["plan_version_id"]) == plan_version_id
            else None
        )
        if accepted is None:
            raise ValueError(
                "capability result no longer belongs to the current accepted plan"
            )
        consent = connection.execute(
            "SELECT 1 FROM consent_receipts WHERE consent_receipt_id = ? "
            "AND investigation_id = ? AND user_id = ? "
            "AND patient_molecular_snapshot_id IS ? AND revoked_at IS NULL",
            (
                consent_receipt_id,
                investigation_id,
                investigation["user_id"],
                snapshot_id,
            ),
        ).fetchone()
        if (
            consent is None
            or investigation["active_consent_receipt_id"] != consent_receipt_id
        ):
            raise ValueError(
                "capability result no longer belongs to the active molecular-context consent"
            )

    @staticmethod
    def _claimed_result(job_id: str) -> JsonObject:
        return {
            "status": "in_progress",
            "job_id": job_id,
            "resume_operation": CAPABILITY_RETRY_OPERATION,
            "poll_after_seconds": 1,
        }

    @staticmethod
    def _execution_rows(connection: Any, execution_id: str) -> tuple[Any, list[Any]]:
        row = connection.execute(
            "SELECT * FROM capability_executions WHERE capability_execution_id = ?",
            (execution_id,),
        ).fetchone()
        if row is None:
            raise KeyError(execution_id)
        attempts = connection.execute(
            "SELECT * FROM capability_execution_attempts "
            "WHERE capability_execution_id = ? ORDER BY attempt_number",
            (execution_id,),
        ).fetchall()
        return row, attempts

    @staticmethod
    def _execution_view(row: Any, attempts: list[Any]) -> JsonObject:
        result = row_dict(row)
        result["attempts"] = [row_dict(attempt) for attempt in attempts]
        return result
