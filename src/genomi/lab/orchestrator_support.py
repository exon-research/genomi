"""Shared validation and idempotency helpers for orchestrator-owned writes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, ContextManager, Protocol

from .models import JsonObject, compact_json, required_text, row_dict, utc_now


class OrchestratorStoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def atomic_write(self) -> ContextManager[None]: ...

    def commit_evidence(self, investigation_id: str, **kwargs: Any) -> JsonObject: ...


def json_sha256(value: object) -> str:
    return hashlib.sha256(compact_json(value).encode("utf-8")).hexdigest()


def unique_ids(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    identifiers = [required_text(item, field, 300) for item in value]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{field} must not contain duplicates")
    return identifiers


def json_object(value: object, field: str, *, required: bool = True) -> JsonObject | None:
    if value is None and not required:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return dict(value)


def json_array(value: object, field: str) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return list(value)


def command_replay(
    store: OrchestratorStoreContract,
    *,
    investigation_id: str,
    operation: str,
    command_id: object,
    request: object,
) -> tuple[str, str, JsonObject | None]:
    command = required_text(command_id, "command_id", 300)
    request_hash = json_sha256(request)
    with store._connect() as connection:
        row = connection.execute(
            "SELECT * FROM orchestrator_commands WHERE command_id = ?",
            (command,),
        ).fetchone()
    if row is None:
        return command, request_hash, None
    saved = row_dict(row)
    if any(
        saved.get(field) != expected
        for field, expected in {
            "investigation_id": investigation_id,
            "operation": operation,
            "request_sha256": request_hash,
        }.items()
    ):
        raise ValueError("command_id was already used for a different request")
    response = saved.get("response")
    if not isinstance(response, dict):
        raise ValueError("saved command response is invalid")
    return command, request_hash, response


def save_command(
    store: OrchestratorStoreContract,
    *,
    command_id: str,
    investigation_id: str,
    operation: str,
    request_sha256: str,
    response: JsonObject,
) -> None:
    with store._connect() as connection:
        connection.execute(
            "INSERT INTO orchestrator_commands(command_id, investigation_id, operation, "
            "request_sha256, response_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                command_id,
                investigation_id,
                operation,
                request_sha256,
                compact_json(response),
                utc_now(),
            ),
        )


def require_investigation_revision(
    store: OrchestratorStoreContract,
    investigation_id: str,
    expected_revision: object,
) -> JsonObject:
    if isinstance(expected_revision, bool):
        raise ValueError("expected_revision must be an integer")
    try:
        expected = int(expected_revision)
    except (TypeError, ValueError) as exc:
        raise ValueError("expected_revision must be an integer") from exc
    with store._connect() as connection:
        row = connection.execute(
            "SELECT * FROM investigations WHERE investigation_id = ?",
            (investigation_id,),
        ).fetchone()
    if row is None:
        raise KeyError(investigation_id)
    investigation = row_dict(row)
    if int(investigation["domain_revision"]) != expected:
        raise ValueError("investigation revision conflict")
    return investigation


def advance_investigation_revision(
    store: OrchestratorStoreContract,
    investigation_id: str,
) -> int:
    with store._connect() as connection:
        connection.execute(
            "UPDATE investigations SET domain_revision = domain_revision + 1, updated_at = ? "
            "WHERE investigation_id = ?",
            (utc_now(), investigation_id),
        )
        row = connection.execute(
            "SELECT domain_revision FROM investigations WHERE investigation_id = ?",
            (investigation_id,),
        ).fetchone()
    if row is None:
        raise KeyError(investigation_id)
    return int(row["domain_revision"])


def require_cycle(
    store: OrchestratorStoreContract,
    investigation_id: str,
    cycle_id: object,
) -> JsonObject:
    identifier = required_text(cycle_id, "cycle_id", 300)
    with store._connect() as connection:
        row = connection.execute(
            "SELECT * FROM investigation_cycles WHERE cycle_id = ? AND investigation_id = ?",
            (identifier, investigation_id),
        ).fetchone()
    if row is None:
        raise ValueError("cycle_id must belong to this investigation")
    return row_dict(row)


def resolve_current_snapshot_fact_ids(
    store: OrchestratorStoreContract,
    investigation: Mapping[str, Any],
    fact_ids: list[str] | None,
) -> list[str]:
    snapshot_id = investigation.get("patient_molecular_snapshot_id")
    if not snapshot_id:
        if fact_ids:
            raise ValueError("patient facts require an approved profile snapshot")
        return []
    with store._connect() as connection:
        row = connection.execute(
            "SELECT observation_revision_ids_json FROM profile_snapshots "
            "WHERE patient_molecular_snapshot_id = ? AND investigation_id = ?",
            (snapshot_id, investigation["investigation_id"]),
        ).fetchone()
    if row is None:
        raise ValueError("the current profile snapshot is unavailable")
    snapshot_fact_ids = json.loads(str(row["observation_revision_ids_json"]))
    if not isinstance(snapshot_fact_ids, list) or not all(
        isinstance(item, str) for item in snapshot_fact_ids
    ):
        raise ValueError("the current profile snapshot is invalid")
    if fact_ids is None:
        return snapshot_fact_ids
    allowed = set(snapshot_fact_ids)
    if not set(fact_ids).issubset(allowed):
        raise ValueError("source fact IDs must belong to the current approved profile snapshot")
    return fact_ids


__all__ = [
    "OrchestratorStoreContract",
    "advance_investigation_revision",
    "command_replay",
    "json_array",
    "json_object",
    "json_sha256",
    "resolve_current_snapshot_fact_ids",
    "require_cycle",
    "require_investigation_revision",
    "save_command",
    "unique_ids",
]
