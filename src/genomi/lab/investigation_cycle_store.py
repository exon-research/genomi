"""Portal binding and bounded investigation-cycle persistence."""

from __future__ import annotations

from typing import Any, ContextManager, Protocol

from .investigation_record_support import (
    command_parts,
    command_result,
    require_cycle,
    require_investigation,
)
from .models import (
    QUESTION_MAX,
    JsonObject,
    compact_json,
    optional_text,
    required_text,
    row_dict,
    stable_id,
    utc_now,
    validate_private_payload,
)


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...
    def _require_workspace(self, user_id: str) -> None: ...
    def atomic_write(self) -> ContextManager[None]: ...
    def create_investigation(
        self, user_id: str, *, question: object, disease_scope: object = None
    ) -> JsonObject: ...


class InvestigationCycleStoreMixin:
    """Host-neutral portal identity and cycle lifecycle records."""

    def get_investigation_command(
        self: _StoreContract,
        user_id: str,
        *,
        operation: object,
        command_id: object,
        payload: JsonObject,
    ) -> JsonObject | None:
        operation_value = required_text(operation, "operation", 160)
        command, fingerprint = command_parts(command_id, payload)
        with self._connect() as connection:
            row = command_result(
                connection,
                table="investigation_commands",
                command_id=command,
                fingerprint=fingerprint,
            )
        if row is None:
            return None
        if (
            str(row.get("user_id") or "") != user_id
            or str(row.get("operation") or "") != operation_value
        ):
            raise ValueError("command_id belongs to a different operation or user")
        return row.get("result") or {}

    def record_investigation_command(
        self: _StoreContract,
        user_id: str,
        *,
        operation: object,
        command_id: object,
        payload: JsonObject,
        result: JsonObject,
    ) -> JsonObject:
        operation_value = required_text(operation, "operation", 160)
        command, fingerprint = command_parts(command_id, payload)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO investigation_commands(command_id, user_id, operation, "
                "command_fingerprint, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    command,
                    user_id,
                    operation_value,
                    fingerprint,
                    compact_json(result),
                    utc_now(),
                ),
            )
        return result

    def start_portal_investigation(
        self: _StoreContract,
        user_id: str,
        *,
        question: object,
        disease_scope: object,
        portal_project_id: object,
        frame_id: object,
        command_id: object,
    ) -> JsonObject:
        self._require_workspace(user_id)
        question_value = required_text(question, "question", QUESTION_MAX)
        disease_value = optional_text(disease_scope, "disease_scope", QUESTION_MAX)
        project = required_text(portal_project_id, "portal_project_id", 200)
        frame_key = required_text(frame_id, "frame_id", 200)
        payload = {
            "user_id": user_id,
            "question": question_value,
            "disease_scope": disease_value,
            "portal_project_id": project,
            "frame_id": frame_key,
        }
        command, fingerprint = command_parts(command_id, payload)
        with self.atomic_write():
            with self._connect() as connection:
                prior = command_result(
                    connection,
                    table="investigation_commands",
                    command_id=command,
                    fingerprint=fingerprint,
                )
                if prior is not None:
                    result = prior.get("result") or {}
                    investigation = connection.execute(
                        "SELECT * FROM investigations WHERE investigation_id = ?",
                        (result.get("investigation_id"),),
                    ).fetchone()
                    binding = connection.execute(
                        "SELECT * FROM investigation_portal_bindings WHERE binding_id = ?",
                        (result.get("binding_id"),),
                    ).fetchone()
                    return {
                        "investigation": row_dict(investigation),
                        "binding": row_dict(binding),
                    }
            investigation = self.create_investigation(
                user_id,
                question=question_value,
                disease_scope=disease_value,
            )
            binding = self.bind_investigation_portal(
                user_id,
                investigation_id=investigation["investigation_id"],
                portal_project_id=project,
                frame_id=frame_key,
                frame={"project_id": project, "frame_id": frame_key},
                command_id=f"{command}:binding",
            )
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO investigation_commands(command_id, user_id, operation, "
                    "command_fingerprint, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        command,
                        user_id,
                        "start_investigation",
                        fingerprint,
                        compact_json(
                            {
                                "investigation_id": investigation["investigation_id"],
                                "binding_id": binding["binding_id"],
                            }
                        ),
                        utc_now(),
                    ),
                )
        return {"investigation": investigation, "binding": binding}

    def bind_investigation_portal(
        self: _StoreContract,
        user_id: str,
        *,
        investigation_id: object,
        portal_project_id: object,
        frame_id: object,
        frame: object,
        command_id: object,
        expected_revision: int | None = None,
    ) -> JsonObject:
        self._require_workspace(user_id)
        project = required_text(portal_project_id, "portal_project_id", 200)
        frame_key = required_text(frame_id, "frame_id", 200)
        if not isinstance(frame, dict):
            raise ValueError("frame must be an object")
        validate_private_payload(frame)
        investigation = required_text(investigation_id, "investigation_id", 200)
        payload = {
            "user_id": user_id,
            "investigation_id": investigation,
            "portal_project_id": project,
            "frame_id": frame_key,
            "frame": frame,
        }
        command, fingerprint = command_parts(command_id, payload)
        now = utc_now()
        with self._connect() as connection:
            existing_command = command_result(
                connection,
                table="investigation_portal_bindings",
                command_id=command,
                fingerprint=fingerprint,
            )
            if existing_command is not None:
                return existing_command
            target = require_investigation(connection, investigation, user_id)
            existing = connection.execute(
                "SELECT * FROM investigation_portal_bindings WHERE investigation_id = ?",
                (investigation,),
            ).fetchone()
            if existing is not None:
                if expected_revision is not None and int(existing["revision"]) != int(
                    expected_revision
                ):
                    raise ValueError("investigation binding revision conflict")
                raise ValueError("investigation already has a portal binding")
            if expected_revision is not None and int(target["domain_revision"]) != int(
                expected_revision
            ):
                raise ValueError("investigation revision conflict")
            binding_id = stable_id("portal-binding", user_id, project, frame_key)
            connection.execute(
                "INSERT INTO investigation_portal_bindings(binding_id, investigation_id, user_id, portal_project_id, frame_id, frame_json, command_id, command_fingerprint, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    binding_id,
                    investigation,
                    user_id,
                    project,
                    frame_key,
                    compact_json(frame),
                    command,
                    fingerprint,
                    now,
                    now,
                ),
            )
            connection.execute(
                "UPDATE investigations SET domain_revision = domain_revision + 1, updated_at = ? WHERE investigation_id = ?",
                (now, investigation),
            )
            row = connection.execute(
                "SELECT * FROM investigation_portal_bindings WHERE binding_id = ?",
                (binding_id,),
            ).fetchone()
        return row_dict(row)

    def get_investigation_binding(
        self: _StoreContract,
        portal_project_id: object,
        frame_id: object,
        *,
        user_id: str | None = None,
    ) -> JsonObject:
        project = required_text(portal_project_id, "portal_project_id", 200)
        frame_key = required_text(frame_id, "frame_id", 200)
        with self._connect() as connection:
            if user_id is None:
                rows = connection.execute(
                    "SELECT * FROM investigation_portal_bindings WHERE portal_project_id = ? AND frame_id = ?",
                    (project, frame_key),
                ).fetchall()
                if len(rows) > 1:
                    raise ValueError(
                        "user_id is required for an ambiguous portal frame"
                    )
                row = rows[0] if rows else None
            else:
                row = connection.execute(
                    "SELECT * FROM investigation_portal_bindings WHERE user_id = ? AND portal_project_id = ? AND frame_id = ?",
                    (user_id, project, frame_key),
                ).fetchone()
        if row is None:
            raise KeyError(f"{project}:{frame_key}")
        return row_dict(row)

    def start_cycle(
        self: _StoreContract,
        user_id: str,
        *,
        investigation_id: object,
        objective: object,
        command_id: object,
        patient_molecular_snapshot_id: object = None,
        expected_revision: int | None = None,
    ) -> JsonObject:
        self._require_workspace(user_id)
        investigation = required_text(investigation_id, "investigation_id", 200)
        objective_value = required_text(objective, "objective", QUESTION_MAX)
        snapshot_id = optional_text(
            patient_molecular_snapshot_id, "patient_molecular_snapshot_id", 200
        )
        payload = {
            "user_id": user_id,
            "investigation_id": investigation,
            "objective": objective_value,
            "patient_molecular_snapshot_id": snapshot_id,
        }
        command, fingerprint = command_parts(command_id, payload)
        now = utc_now()
        with self._connect() as connection:
            prior = command_result(
                connection,
                table="investigation_cycles",
                command_id=command,
                fingerprint=fingerprint,
            )
            if prior is not None:
                return prior
            target = require_investigation(connection, investigation, user_id)
            if expected_revision is not None and int(target["domain_revision"]) != int(
                expected_revision
            ):
                raise ValueError("investigation revision conflict")
            active = connection.execute(
                "SELECT cycle_id FROM investigation_cycles WHERE investigation_id = ? AND status = 'active'",
                (investigation,),
            ).fetchone()
            if active is not None:
                raise ValueError("investigation already has an active cycle")
            selected_snapshot = snapshot_id or optional_text(
                target["patient_molecular_snapshot_id"],
                "patient_molecular_snapshot_id",
                200,
            )
            if selected_snapshot:
                owned = connection.execute(
                    "SELECT 1 FROM profile_snapshots WHERE patient_molecular_snapshot_id = ? AND user_id = ?",
                    (selected_snapshot, user_id),
                ).fetchone()
                if owned is None:
                    raise ValueError(
                        "patient_molecular_snapshot_id must belong to the current user"
                    )
            number = int(
                connection.execute(
                    "SELECT COALESCE(MAX(cycle_number), 0) + 1 AS value FROM investigation_cycles WHERE investigation_id = ?",
                    (investigation,),
                ).fetchone()["value"]
            )
            cycle_id = stable_id("investigation-cycle", investigation, number)
            connection.execute(
                "INSERT INTO investigation_cycles(cycle_id, investigation_id, user_id, cycle_number, objective, patient_molecular_snapshot_id, status, command_id, command_fingerprint, created_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                (
                    cycle_id,
                    investigation,
                    user_id,
                    number,
                    objective_value,
                    selected_snapshot,
                    command,
                    fingerprint,
                    now,
                ),
            )
            connection.execute(
                "UPDATE investigations SET status = 'running', domain_revision = domain_revision + 1, updated_at = ? WHERE investigation_id = ?",
                (now, investigation),
            )
            row = connection.execute(
                "SELECT * FROM investigation_cycles WHERE cycle_id = ?", (cycle_id,)
            ).fetchone()
        return row_dict(row)

    def get_cycle(self: _StoreContract, cycle_id: object) -> JsonObject:
        cycle = required_text(cycle_id, "cycle_id", 200)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM investigation_cycles WHERE cycle_id = ?", (cycle,)
            ).fetchone()
        if row is None:
            raise KeyError(cycle)
        return row_dict(row)

    def complete_cycle(
        self: _StoreContract,
        user_id: str,
        *,
        cycle_id: object,
        command_id: object,
        expected_revision: int,
    ) -> JsonObject:
        cycle = required_text(cycle_id, "cycle_id", 200)
        payload = {"user_id": user_id, "cycle_id": cycle, "status": "completed"}
        command, fingerprint = command_parts(command_id, payload)
        now = utc_now()
        with self._connect() as connection:
            prior = command_result(
                connection,
                table="investigation_work_events",
                command_id=command,
                fingerprint=fingerprint,
            )
            if prior is not None:
                completed = connection.execute(
                    "SELECT * FROM investigation_cycles WHERE cycle_id = ?", (cycle,)
                ).fetchone()
                return row_dict(completed)
            row = connection.execute(
                "SELECT * FROM investigation_cycles WHERE cycle_id = ?", (cycle,)
            ).fetchone()
            if row is None or str(row["user_id"]) != user_id:
                raise ValueError("cycle_id must belong to the current user")
            require_cycle(
                connection,
                cycle_id=cycle,
                investigation_id=str(row["investigation_id"]),
                user_id=user_id,
                expected_revision=expected_revision,
            )
            # Completion is itself idempotent through a durable command row. A
            # cycle's start command is retained in the cycle row, so completion
            # uses a work event as its command receipt.
            sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 AS value FROM investigation_work_events WHERE cycle_id = ?",
                    (cycle,),
                ).fetchone()["value"]
            )
            event_id = stable_id("work-event", command)
            connection.execute(
                "INSERT INTO investigation_work_events(work_event_id, investigation_id, cycle_id, user_id, event_type, summary, details_json, command_id, command_fingerprint, sequence, created_at) VALUES (?, ?, ?, ?, 'cycle_completed', 'Investigation cycle completed', '{}', ?, ?, ?, ?)",
                (
                    event_id,
                    row["investigation_id"],
                    cycle,
                    user_id,
                    command,
                    fingerprint,
                    sequence,
                    now,
                ),
            )
            connection.execute(
                "UPDATE investigation_cycles SET status = 'completed', revision = revision + 1, completed_at = ? WHERE cycle_id = ?",
                (now, cycle),
            )
            result = connection.execute(
                "SELECT * FROM investigation_cycles WHERE cycle_id = ?", (cycle,)
            ).fetchone()
        return row_dict(result)


__all__ = ["InvestigationCycleStoreMixin"]
