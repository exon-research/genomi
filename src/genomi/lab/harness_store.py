"""Durable harness command, task-binding, and event persistence."""

from __future__ import annotations

import uuid
from typing import Any, ContextManager, Protocol

from .models import (
    JsonObject,
    compact_json,
    optional_text,
    required_text,
    row_dict,
    utc_now,
    validate_private_payload,
)


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...


def _binding_matches_prior(
    binding: JsonObject | None,
    *,
    task_id: str | None,
    run_id: str | None,
    revision: int,
) -> bool:
    return bool(
        binding is not None
        and task_id is not None
        and binding.get("task_id") == task_id
        and binding.get("run_id") == run_id
        and int(binding.get("harness_revision", -1)) == revision
    )


class HarnessStoreMixin:
    """Harness command, binding, and ordered-event persistence."""

    def bind_harness_task(
        self: _StoreContract,
        investigation_id: str,
        *,
        command_id: object,
        host_id: object,
        task_id: object = None,
        run_id: object = None,
        harness_status: object = "waiting",
        harness_revision: int = 0,
    ) -> JsonObject:
        command = required_text(command_id, "command_id", 200)
        host = required_text(host_id, "host_id", 200)
        harness_status_value = required_text(harness_status, "harness_status", 80)
        if int(harness_revision) < 0:
            raise ValueError("harness_revision must not be negative")
        now = utc_now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM harness_bindings WHERE command_id = ?", (command,)
            ).fetchone()
            if existing is not None:
                if str(existing["investigation_id"]) != investigation_id:
                    raise ValueError(
                        "command_id is already bound to another investigation"
                    )
                return row_dict(existing)
            connection.execute(
                "UPDATE harness_bindings SET binding_state = 'replaced', updated_at = ? "
                "WHERE investigation_id = ? AND binding_state = 'active'",
                (now, investigation_id),
            )
            binding_id = f"binding-{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO harness_bindings(
                    binding_id, investigation_id, command_id, host_id, task_id,
                    run_id, binding_state, harness_status, harness_revision,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (
                    binding_id,
                    investigation_id,
                    command,
                    host,
                    optional_text(task_id, "task_id", 300),
                    optional_text(run_id, "run_id", 300),
                    harness_status_value,
                    int(harness_revision),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM harness_bindings WHERE binding_id = ?", (binding_id,)
            ).fetchone()
        return row_dict(row)

    def update_harness_binding(
        self: _StoreContract,
        binding_id: str,
        *,
        task_id: object,
        run_id: object = None,
        harness_status: object,
        harness_revision: int,
    ) -> JsonObject:
        if int(harness_revision) < 0:
            raise ValueError("harness_revision must not be negative")
        with self._connect() as connection:
            current = connection.execute(
                "SELECT harness_revision FROM harness_bindings WHERE binding_id = ? "
                "AND binding_state = 'active'",
                (binding_id,),
            ).fetchone()
            if current is None:
                raise KeyError(binding_id)
            if int(harness_revision) < int(current["harness_revision"]):
                raise ValueError("harness binding revision is stale")
            connection.execute(
                "UPDATE harness_bindings SET task_id = ?, run_id = ?, "
                "harness_status = ?, harness_revision = ?, updated_at = ? "
                "WHERE binding_id = ?",
                (
                    required_text(task_id, "task_id", 300),
                    optional_text(run_id, "run_id", 300),
                    required_text(harness_status, "harness_status", 80),
                    int(harness_revision),
                    utc_now(),
                    binding_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM harness_bindings WHERE binding_id = ?",
                (binding_id,),
            ).fetchone()
        return row_dict(row)

    def attach_and_bind_harness_job_identity(
        self: _StoreContract,
        *,
        job_id: object,
        command_id: object,
        investigation_id: object,
        user_id: object,
        host_id: object,
        operation: object,
        expected_revision: int,
        prior_task_id: object = None,
        prior_run_id: object = None,
        task_id: object,
        run_id: object,
    ) -> JsonObject:
        """Atomically attach a host identity without superseding newer work."""

        job = required_text(job_id, "job_id", 200)
        command = required_text(command_id, "command_id", 200)
        investigation = required_text(investigation_id, "investigation_id", 200)
        user = required_text(user_id, "user_id", 300)
        host = required_text(host_id, "host_id", 200)
        operation_value = required_text(operation, "operation", 100)
        if operation_value not in {
            "start_task_run",
            "resume_task_run",
            "send_task_message",
            "replace_task_binding",
        }:
            raise ValueError("operation cannot attach a background harness identity")
        if int(expected_revision) < 0:
            raise ValueError("expected_revision must not be negative")
        expected = int(expected_revision)
        target_revision = expected + 1
        prior_task = optional_text(prior_task_id, "prior_task_id", 300)
        prior_run = optional_text(prior_run_id, "prior_run_id", 300)
        task = required_text(task_id, "task_id", 300)
        run = required_text(run_id, "run_id", 300)
        now = utc_now()

        with self._connect() as connection:
            saved_command = connection.execute(
                "SELECT * FROM harness_commands WHERE command_id = ?", (command,)
            ).fetchone()
            if (
                saved_command is None
                or str(saved_command["investigation_id"]) != investigation
                or str(saved_command["user_id"]) != user
                or str(saved_command["operation"]) != operation_value
                or str(saved_command["command_state"]) != "dispatching"
                or saved_command["response_json"] is not None
            ):
                raise ValueError("harness identity command is no longer dispatching")

            saved_job = connection.execute(
                "SELECT * FROM harness_jobs WHERE job_id = ?", (job,)
            ).fetchone()
            if (
                saved_job is None
                or str(saved_job["command_id"]) != command
                or str(saved_job["investigation_id"]) != investigation
                or str(saved_job["user_id"]) != user
                or str(saved_job["host_id"]) != host
                or str(saved_job["job_state"]) not in {"queued", "running"}
                or saved_job["terminal_response_json"] is not None
                or saved_job["task_id"] not in (None, task)
                or saved_job["run_id"] not in (None, run)
            ):
                raise ValueError("harness identity job is stale or changed")

            active = connection.execute(
                "SELECT * FROM harness_bindings WHERE investigation_id = ? "
                "AND binding_state = 'active'",
                (investigation,),
            ).fetchone()
            active_value = row_dict(active) if active is not None else None
            if operation_value == "start_task_run":
                if active_value is None:
                    binding_id = f"binding-{uuid.uuid4().hex}"
                    connection.execute(
                        "INSERT INTO harness_bindings(binding_id, investigation_id, "
                        "command_id, host_id, task_id, run_id, binding_state, "
                        "harness_status, harness_revision, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, 'active', 'running', ?, ?, ?)",
                        (
                            binding_id,
                            investigation,
                            command,
                            host,
                            task,
                            run,
                            target_revision,
                            now,
                            now,
                        ),
                    )
                elif not (
                    active_value.get("command_id") == command
                    and active_value.get("host_id") == host
                    and active_value.get("task_id") == task
                    and active_value.get("run_id") == run
                    and int(active_value.get("harness_revision", -1))
                    == target_revision
                ):
                    raise ValueError("harness start identity was superseded")
                else:
                    binding_id = str(active_value["binding_id"])
            elif operation_value == "replace_task_binding":
                if active_value is not None and active_value.get("command_id") == command:
                    if not (
                        active_value.get("host_id") == host
                        and active_value.get("task_id") == task
                        and active_value.get("run_id") == run
                        and int(active_value.get("harness_revision", -1))
                        == target_revision
                    ):
                        raise ValueError("replacement harness identity changed")
                    binding_id = str(active_value["binding_id"])
                else:
                    if not _binding_matches_prior(
                        active_value,
                        task_id=prior_task,
                        run_id=prior_run,
                        revision=expected,
                    ):
                        raise ValueError("replacement harness identity was superseded")
                    assert active_value is not None
                    cursor = connection.execute(
                        "UPDATE harness_bindings SET binding_state = 'replaced', "
                        "updated_at = ? WHERE binding_id = ? AND binding_state = 'active' "
                        "AND task_id = ? AND run_id IS ? AND harness_revision = ?",
                        (
                            now,
                            active_value["binding_id"],
                            prior_task,
                            prior_run,
                            expected,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError("replacement harness identity lost its prior binding")
                    binding_id = f"binding-{uuid.uuid4().hex}"
                    connection.execute(
                        "INSERT INTO harness_bindings(binding_id, investigation_id, "
                        "command_id, host_id, task_id, run_id, binding_state, "
                        "harness_status, harness_revision, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, 'active', 'running', ?, ?, ?)",
                        (
                            binding_id,
                            investigation,
                            command,
                            host,
                            task,
                            run,
                            target_revision,
                            now,
                            now,
                        ),
                    )
            else:
                result_already_bound = bool(
                    active_value is not None
                    and active_value.get("task_id") == task
                    and active_value.get("run_id") == run
                    and int(active_value.get("harness_revision", -1))
                    == target_revision
                )
                if not result_already_bound:
                    if not _binding_matches_prior(
                        active_value,
                        task_id=prior_task,
                        run_id=prior_run,
                        revision=expected,
                    ):
                        raise ValueError("harness identity was superseded")
                    assert active_value is not None
                    cursor = connection.execute(
                        "UPDATE harness_bindings SET task_id = ?, run_id = ?, "
                        "harness_status = 'running', harness_revision = ?, updated_at = ? "
                        "WHERE binding_id = ? AND binding_state = 'active' "
                        "AND task_id = ? AND run_id IS ? AND harness_revision = ?",
                        (
                            task,
                            run,
                            target_revision,
                            now,
                            active_value["binding_id"],
                            prior_task,
                            prior_run,
                            expected,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError("harness identity lost its prior binding")
                assert active_value is not None
                binding_id = str(active_value["binding_id"])

            connection.execute(
                "UPDATE harness_jobs SET task_id = ?, run_id = ?, job_state = 'running', "
                "updated_at = ? WHERE job_id = ?",
                (task, run, now, job),
            )
            binding = connection.execute(
                "SELECT * FROM harness_bindings WHERE binding_id = ?", (binding_id,)
            ).fetchone()
            attached_job = connection.execute(
                "SELECT * FROM harness_jobs WHERE job_id = ?", (job,)
            ).fetchone()
        return {"binding": row_dict(binding), "job": row_dict(attached_job)}

    def reject_harness_job_identity(
        self: _StoreContract,
        *,
        job_id: str,
        command_id: str,
        investigation_id: str,
        user_id: str,
        response: JsonObject,
    ) -> JsonObject:
        """Terminally quarantine a stale identity callback without rebinding."""

        validate_private_payload(response)
        with self._connect() as connection:
            command = connection.execute(
                "SELECT * FROM harness_commands WHERE command_id = ?", (command_id,)
            ).fetchone()
            job = connection.execute(
                "SELECT * FROM harness_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if (
                command is None
                or job is None
                or str(command["investigation_id"]) != investigation_id
                or str(command["user_id"]) != user_id
                or str(job["command_id"]) != command_id
                or str(job["investigation_id"]) != investigation_id
                or str(job["user_id"]) != user_id
            ):
                raise ValueError("stale harness identity does not match its durable job")
            if command["response_json"] is None:
                connection.execute(
                    "UPDATE harness_commands SET command_state = 'failed', "
                    "response_json = ?, updated_at = ? WHERE command_id = ? "
                    "AND command_state = 'dispatching' AND response_json IS NULL",
                    (compact_json(response), utc_now(), command_id),
                )
            if job["terminal_response_json"] is None:
                connection.execute(
                    "UPDATE harness_jobs SET job_state = 'failed', "
                    "terminal_response_json = ?, updated_at = ? WHERE job_id = ? "
                    "AND job_state IN ('queued', 'running') "
                    "AND terminal_response_json IS NULL",
                    (compact_json(response), utc_now(), job_id),
                )
            saved_command = connection.execute(
                "SELECT * FROM harness_commands WHERE command_id = ?", (command_id,)
            ).fetchone()
            saved_job = connection.execute(
                "SELECT * FROM harness_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return {"command": row_dict(saved_command), "job": row_dict(saved_job)}

    def active_harness_binding(
        self: _StoreContract, investigation_id: str
    ) -> JsonObject | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM harness_bindings WHERE investigation_id = ? "
                "AND binding_state = 'active'",
                (investigation_id,),
            ).fetchone()
        return row_dict(row) if row is not None else None

    def harness_command(self: _StoreContract, command_id: str) -> JsonObject | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM harness_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        return row_dict(row) if row is not None else None

    def begin_harness_job(
        self: _StoreContract,
        *,
        job_id: object,
        command_id: object,
        investigation_id: object,
        user_id: object,
        host_id: object,
    ) -> JsonObject:
        """Persist an attachable job before returning control to the portal."""

        job = required_text(job_id, "job_id", 200)
        command = required_text(command_id, "command_id", 200)
        investigation = required_text(investigation_id, "investigation_id", 200)
        user = required_text(user_id, "user_id", 300)
        host = required_text(host_id, "host_id", 200)
        now = utc_now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM harness_jobs WHERE job_id = ? OR command_id = ?",
                (job, command),
            ).fetchone()
            if existing is not None:
                saved = row_dict(existing)
                if any(
                    saved.get(key) != value
                    for key, value in {
                        "job_id": job,
                        "command_id": command,
                        "investigation_id": investigation,
                        "user_id": user,
                        "host_id": host,
                    }.items()
                ):
                    raise ValueError("harness job identity collision")
                return saved
            claimed = connection.execute(
                "SELECT investigation_id, user_id, command_state "
                "FROM harness_commands WHERE command_id = ?",
                (command,),
            ).fetchone()
            if (
                claimed is None
                or str(claimed["investigation_id"]) != investigation
                or str(claimed["user_id"]) != user
                or str(claimed["command_state"]) != "dispatching"
            ):
                raise ValueError("harness job requires its exact dispatched command")
            connection.execute(
                "INSERT INTO harness_jobs(job_id, command_id, investigation_id, "
                "user_id, host_id, job_state, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)",
                (job, command, investigation, user, host, now, now),
            )
            row = connection.execute(
                "SELECT * FROM harness_jobs WHERE job_id = ?", (job,)
            ).fetchone()
        return row_dict(row)

    def attach_harness_job_identity(
        self: _StoreContract,
        job_id: str,
        *,
        task_id: object,
        run_id: object,
    ) -> JsonObject:
        task = required_text(task_id, "task_id", 300)
        run = required_text(run_id, "run_id", 300)
        with self._connect() as connection:
            current = connection.execute(
                "SELECT task_id, run_id, job_state FROM harness_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if current is None:
                raise KeyError(job_id)
            if current["task_id"] not in (None, task) or current["run_id"] not in (
                None,
                run,
            ):
                raise ValueError("harness job host identity changed")
            if str(current["job_state"]) not in {"queued", "running"}:
                raise ValueError("terminal harness job cannot attach new identity")
            connection.execute(
                "UPDATE harness_jobs SET task_id = ?, run_id = ?, "
                "job_state = 'running', updated_at = ? WHERE job_id = ?",
                (task, run, utc_now(), job_id),
            )
            row = connection.execute(
                "SELECT * FROM harness_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return row_dict(row)

    def complete_harness_job(
        self: _StoreContract,
        job_id: str,
        *,
        job_state: object,
        response: JsonObject,
    ) -> JsonObject:
        state = required_text(job_state, "job_state", 80)
        if state not in {"completed", "cancelled", "failed"}:
            raise ValueError("job_state must be terminal")
        validate_private_payload(response)
        with self._connect() as connection:
            current = connection.execute(
                "SELECT * FROM harness_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if current is None:
                raise KeyError(job_id)
            saved = row_dict(current)
            if saved.get("terminal_response") is not None:
                if (
                    saved.get("job_state") != state
                    or saved.get("terminal_response") != response
                ):
                    raise ValueError("terminal harness job result changed")
                return saved
            connection.execute(
                "UPDATE harness_jobs SET job_state = ?, terminal_response_json = ?, "
                "updated_at = ? WHERE job_id = ?",
                (state, compact_json(response), utc_now(), job_id),
            )
            row = connection.execute(
                "SELECT * FROM harness_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return row_dict(row)

    def harness_job(self: _StoreContract, job_id: str) -> JsonObject | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM harness_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return row_dict(row) if row is not None else None

    def harness_job_for_command(
        self: _StoreContract, command_id: str
    ) -> JsonObject | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM harness_jobs WHERE command_id = ?", (command_id,)
            ).fetchone()
        return row_dict(row) if row is not None else None

    def harness_completion_is_durable(
        self: _StoreContract,
        *,
        job_id: object,
        command_id: object,
        investigation_id: object,
        workspace_session_id: object,
        user_id: object,
        operation: object,
    ) -> bool:
        """Confirm matching terminal records without decoding their private payload."""

        job = required_text(job_id, "job_id", 200)
        command = required_text(command_id, "command_id", 200)
        investigation = required_text(
            investigation_id, "investigation_id", 200
        )
        workspace_session = required_text(
            workspace_session_id, "workspace_session_id", 200
        )
        user = required_text(user_id, "user_id", 300)
        operation_value = required_text(operation, "operation", 100)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM harness_jobs AS j "
                "JOIN harness_commands AS c ON c.command_id = j.command_id "
                "WHERE j.job_id = ? AND c.command_id = ? "
                "AND c.investigation_id = ? AND j.investigation_id = ? "
                "AND c.workspace_session_id = ? AND c.user_id = ? AND j.user_id = ? "
                "AND c.operation = ? AND c.command_state IN ('completed', 'failed') "
                "AND j.job_state IN ('completed', 'cancelled', 'failed') "
                "AND c.response_json IS NOT NULL "
                "AND j.terminal_response_json = c.response_json",
                (
                    job,
                    command,
                    investigation,
                    investigation,
                    workspace_session,
                    user,
                    user,
                    operation_value,
                ),
            ).fetchone()
        return row is not None

    def active_harness_job(
        self: _StoreContract, investigation_id: str
    ) -> JsonObject | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM harness_jobs WHERE investigation_id = ? "
                "AND job_state IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1",
                (investigation_id,),
            ).fetchone()
        return row_dict(row) if row is not None else None

    def begin_harness_command(
        self: _StoreContract,
        *,
        command_id: object,
        investigation_id: object,
        workspace_session_id: object,
        user_id: object,
        operation: object,
        command_fingerprint: object,
        disclosure_receipt_id: object = None,
    ) -> JsonObject:
        """Durably claim a command ID before any harness side effect."""

        command = required_text(command_id, "command_id", 200)
        investigation = required_text(investigation_id, "investigation_id", 200)
        session = required_text(workspace_session_id, "workspace_session_id", 200)
        user = required_text(user_id, "user_id", 300)
        operation_value = required_text(operation, "operation", 100)
        fingerprint = required_text(command_fingerprint, "command_fingerprint", 128)
        receipt = optional_text(disclosure_receipt_id, "disclosure_receipt_id", 200)
        expected = {
            "investigation_id": investigation,
            "workspace_session_id": session,
            "user_id": user,
            "operation": operation_value,
            "command_fingerprint": fingerprint,
        }
        now = utc_now()
        with self._connect() as connection:
            target = connection.execute(
                "SELECT user_id FROM investigations WHERE investigation_id = ?",
                (investigation,),
            ).fetchone()
            if target is None or str(target["user_id"]) != user:
                raise ValueError("investigation_id must belong to the current user")
            existing = connection.execute(
                "SELECT * FROM harness_commands WHERE command_id = ?",
                (command,),
            ).fetchone()
            if existing is not None:
                saved = row_dict(existing)
                if any(saved.get(key) != value for key, value in expected.items()):
                    raise ValueError("harness command_id collision")
                saved["duplicate"] = True
                return saved
            connection.execute(
                """
                INSERT INTO harness_commands(
                    command_id, investigation_id, workspace_session_id, user_id,
                    operation, command_fingerprint, command_state,
                    disclosure_receipt_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'accepted', ?, ?, ?)
                """,
                (
                    command,
                    investigation,
                    session,
                    user,
                    operation_value,
                    fingerprint,
                    receipt,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM harness_commands WHERE command_id = ?",
                (command,),
            ).fetchone()
        result = row_dict(row)
        result["duplicate"] = False
        return result

    def complete_harness_command(
        self: _StoreContract,
        command_id: str,
        response: JsonObject,
        *,
        succeeded: bool,
    ) -> JsonObject:
        """Persist the canonical portal response after domain commits finish."""

        validate_private_payload(response)
        state = "completed" if succeeded else "failed"
        with self._connect() as connection:
            current = connection.execute(
                "SELECT command_state, response_json FROM harness_commands "
                "WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            if current is None:
                raise KeyError(command_id)
            if current["response_json"] is not None:
                existing = row_dict(
                    connection.execute(
                        "SELECT * FROM harness_commands WHERE command_id = ?",
                        (command_id,),
                    ).fetchone()
                )
                if existing.get("response") != response:
                    raise ValueError("completed harness command response changed")
                return existing
            connection.execute(
                "UPDATE harness_commands SET command_state = ?, response_json = ?, "
                "updated_at = ? WHERE command_id = ?",
                (state, compact_json(response), utc_now(), command_id),
            )
            row = connection.execute(
                "SELECT * FROM harness_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        return row_dict(row)

    def reconcile_interrupted_harness_command(
        self: _StoreContract,
        command_id: str,
        response: JsonObject,
    ) -> JsonObject:
        """Terminally record a dispatch whose external outcome is unknown.

        Once a command crosses the dispatch boundary, repeating it could create
        duplicate harness work.  An unexpected adapter failure or process
        interruption therefore resolves the durable command to a failed,
        non-retryable response instead of moving it back to ``approved``.
        """

        validate_private_payload(response)
        with self._connect() as connection:
            current = connection.execute(
                "SELECT command_state, response_json FROM harness_commands "
                "WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            if current is None:
                raise KeyError(command_id)
            if current["response_json"] is not None:
                row = connection.execute(
                    "SELECT * FROM harness_commands WHERE command_id = ?",
                    (command_id,),
                ).fetchone()
                return row_dict(row)
            if str(current["command_state"]) != "dispatching":
                raise ValueError(
                    "only a dispatching harness command can be reconciled as interrupted"
                )
            connection.execute(
                "UPDATE harness_commands SET command_state = 'failed', "
                "response_json = ?, updated_at = ? WHERE command_id = ? "
                "AND command_state = 'dispatching' AND response_json IS NULL",
                (compact_json(response), utc_now(), command_id),
            )
            row = connection.execute(
                "SELECT * FROM harness_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        return row_dict(row)

    def attach_harness_command_disclosure(
        self: _StoreContract,
        command_id: str,
        disclosure_receipt_id: str,
    ) -> JsonObject:
        with self._connect() as connection:
            current = connection.execute(
                "SELECT disclosure_receipt_id, command_state FROM harness_commands "
                "WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            if current is None:
                raise KeyError(command_id)
            existing = current["disclosure_receipt_id"]
            if existing is not None and str(existing) != disclosure_receipt_id:
                raise ValueError("harness command disclosure is already bound")
            if str(current["command_state"]) != "accepted":
                raise ValueError("only an accepted harness command can bind disclosure")
            connection.execute(
                "UPDATE harness_commands SET disclosure_receipt_id = ?, "
                "command_state = 'approved', updated_at = ? "
                "WHERE command_id = ?",
                (disclosure_receipt_id, utc_now(), command_id),
            )
            row = connection.execute(
                "SELECT * FROM harness_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        return row_dict(row)

    def claim_harness_command_dispatch(
        self: _StoreContract, command_id: str
    ) -> JsonObject:
        """Mark the irreversible harness-call boundary exactly once."""

        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE harness_commands SET command_state = 'dispatching', "
                "updated_at = ? WHERE command_id = ? AND command_state = 'approved'",
                (utc_now(), command_id),
            )
            if not cursor.rowcount:
                current = connection.execute(
                    "SELECT command_state FROM harness_commands WHERE command_id = ?",
                    (command_id,),
                ).fetchone()
                if current is None:
                    raise KeyError(command_id)
                raise ValueError("harness command is not ready for dispatch")
            row = connection.execute(
                "SELECT * FROM harness_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        return row_dict(row)

    def commit_harness_event(
        self: _StoreContract,
        investigation_id: str,
        binding_id: str,
        *,
        event_id: object,
        sequence: object = None,
        event_type: object,
        payload: JsonObject,
    ) -> JsonObject:
        validate_private_payload(payload)
        event = required_text(event_id, "event_id", 200)
        event_type_value = required_text(event_type, "event_type", 100)
        with self._connect() as connection:
            binding = connection.execute(
                "SELECT investigation_id FROM harness_bindings WHERE binding_id = ?",
                (binding_id,),
            ).fetchone()
            if binding is None or str(binding["investigation_id"]) != investigation_id:
                raise ValueError("binding_id must belong to the investigation")
            existing = connection.execute(
                "SELECT * FROM harness_events WHERE event_id = ?", (event,)
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["investigation_id"]) != investigation_id
                    or str(existing["binding_id"]) != binding_id
                    or str(existing["event_type"]) != event_type_value
                    or str(existing["payload_json"]) != compact_json(payload)
                    or (
                        sequence is not None
                        and int(existing["sequence"]) != int(sequence)
                    )
                ):
                    raise ValueError("event_id collision")
                return row_dict(existing)
            expected = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
                "FROM harness_events WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            expected_sequence = int(expected["next_sequence"])
            if sequence is None:
                sequence_value = expected_sequence
            else:
                try:
                    sequence_value = int(sequence)
                except (TypeError, ValueError) as exc:
                    raise ValueError("sequence must be an integer") from exc
            if sequence_value < 1:
                raise ValueError("sequence must be positive")
            if sequence_value != expected_sequence:
                raise ValueError("harness event sequence is stale or out of order")
            connection.execute(
                """
                INSERT INTO harness_events(
                    event_id, investigation_id, binding_id, sequence,
                    event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event,
                    investigation_id,
                    binding_id,
                    sequence_value,
                    event_type_value,
                    compact_json(payload),
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM harness_events WHERE event_id = ?", (event,)
            ).fetchone()
        return row_dict(row)

    def replay_harness_events(
        self: _StoreContract, investigation_id: str, *, after_sequence: int = 0
    ) -> list[JsonObject]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM harness_events WHERE investigation_id = ? AND sequence > ? "
                "ORDER BY sequence",
                (investigation_id, max(0, int(after_sequence))),
            ).fetchall()
        return [row_dict(row) for row in rows]
