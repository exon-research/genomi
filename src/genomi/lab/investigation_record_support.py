"""Shared invariants for host-neutral GenomiLab investigation records."""

from __future__ import annotations

import hashlib
from typing import Any

from .models import JsonObject, compact_json, required_text, row_dict


def command_parts(command_id: object, payload: JsonObject) -> tuple[str, str]:
    command = required_text(command_id, "command_id", 200)
    fingerprint = hashlib.sha256(compact_json(payload).encode("utf-8")).hexdigest()
    return command, fingerprint


def command_result(
    connection: Any,
    *,
    table: str,
    command_id: str,
    fingerprint: str,
) -> JsonObject | None:
    allowed = {
        "investigation_commands",
        "investigation_portal_bindings",
        "investigation_cycles",
        "specialist_packets",
        "panel_assignments",
        "specialist_findings",
        "research_artifacts",
        "investigation_evidence_references",
        "information_gaps",
        "patient_questions",
        "recommended_next_steps",
        "investigation_work_events",
    }
    if table not in allowed:
        raise ValueError("unsupported command table")
    row = connection.execute(
        f"SELECT * FROM {table} WHERE command_id = ?", (command_id,)
    ).fetchone()
    if row is None:
        return None
    if str(row["command_fingerprint"]) != fingerprint:
        raise ValueError("command_id was already used for a different mutation")
    return row_dict(row)


def require_investigation(
    connection: Any, investigation_id: object, user_id: str
) -> Any:
    investigation = required_text(investigation_id, "investigation_id", 200)
    row = connection.execute(
        "SELECT * FROM investigations WHERE investigation_id = ?", (investigation,)
    ).fetchone()
    if row is None or str(row["user_id"]) != user_id:
        raise ValueError("investigation_id must belong to the current user")
    return row


def require_cycle(
    connection: Any,
    *,
    cycle_id: object,
    investigation_id: str,
    user_id: str,
    expected_revision: int | None,
    active: bool = True,
) -> Any:
    cycle = required_text(cycle_id, "cycle_id", 200)
    row = connection.execute(
        "SELECT * FROM investigation_cycles WHERE cycle_id = ?", (cycle,)
    ).fetchone()
    if (
        row is None
        or str(row["investigation_id"]) != investigation_id
        or str(row["user_id"]) != user_id
    ):
        raise ValueError("cycle_id must belong to the current investigation and user")
    if active and str(row["status"]) != "active":
        raise ValueError("investigation cycle is not active")
    if expected_revision is not None and int(row["revision"]) != int(expected_revision):
        raise ValueError("investigation cycle revision conflict")
    return row


def advance_cycle(connection: Any, cycle_id: str) -> None:
    connection.execute(
        "UPDATE investigation_cycles SET revision = revision + 1 WHERE cycle_id = ?",
        (cycle_id,),
    )


__all__ = [
    "advance_cycle",
    "command_parts",
    "command_result",
    "require_cycle",
    "require_investigation",
]
