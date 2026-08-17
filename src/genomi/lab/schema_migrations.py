"""Idempotent startup upgrades for durable GenomiLab domain invariants."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from .investigation_event_store import (
    INVESTIGATION_EVENT_PAYLOAD_MAX_BYTES,
    _encode_payload,
)
from .models import JsonObject, stable_id
from .schema import SCHEMA_SQL


_REVISION_PREFIX = "observation-revision-"
_LOGICAL_PREFIX = "observation-"
_LEGACY_HARNESS_TABLES = (
    "harness_events",
    "harness_jobs",
    "harness_bindings",
    "harness_commands",
)
_LEGACY_HARNESS_INDEXES = (
    "idx_harness_events_investigation_sequence",
    "idx_harness_commands_investigation_created",
    "idx_harness_jobs_investigation_created",
    "idx_harness_bindings_one_active",
)
_LEGACY_MONITORING_EVENT_TYPES = frozenset(
    {
        "plan_proposed",
        "approval_required",
        "agent_started",
        "agent_progress",
        "evidence_returned",
        "capability_execution_completed",
        "source_unavailable",
        "job_in_progress",
        "needs_user_input",
        "brief_completed",
        "brief_updated",
        "cancelled",
        "failed",
    }
)
_LEGACY_DOMAIN_TEXT_FIELDS = frozenset(
    {
        "approval_kind",
        "artifact_kind",
        "brief_version_id",
        "capability",
        "evidence_record_id",
        "plan_version_id",
        "request_id",
        "source_family",
        "source_id",
    }
)
_LEGACY_DOMAIN_INTEGER_FIELDS = frozenset(
    {"evidence_count", "version", "warning_count"}
)
_LEGACY_DOMAIN_BOOLEAN_FIELDS = frozenset({"retry_reused"})
_LEGACY_DOMAIN_TEXT_ARRAY_FIELDS = frozenset({"evidence_record_ids"})
_LEGACY_DOMAIN_STATUSES = frozenset(
    {
        "approval_required",
        "awaiting_approval",
        "blocked",
        "cancelled",
        "completed",
        "failed",
        "in_progress",
        "needs_user_input",
        "running",
        "unavailable",
    }
)
_LEGACY_EVENT_REQUIRED_COLUMNS = frozenset(
    {
        "event_id",
        "investigation_id",
        "sequence",
        "event_type",
        "payload_json",
        "created_at",
    }
)


def repair_observation_logical_roots(connection: Any) -> None:
    """Give every observation chain one root-derived logical identity.

    Earlier workspaces allowed a caller to supply ``logical_observation_id`` for
    a new root.  Two roots could therefore claim the same logical observation.
    Re-keying every existing chain from its root revision both repairs that
    ambiguity and prepares the store for the durable insert/index invariants in
    the current schema.  Observation revision IDs remain unchanged, so pinned
    profile snapshots and investigation evidence keep their exact anchors.
    """

    table = connection.execute(
        "SELECT 1 FROM sqlite_schema "
        "WHERE type = 'table' AND name = 'molecular_observations'"
    ).fetchone()
    if table is None:
        return

    rows = connection.execute(
        "SELECT observation_revision_id, user_id, supersedes_revision_id "
        "FROM molecular_observations ORDER BY created_at, observation_revision_id"
    ).fetchall()
    if not rows:
        return

    by_id = {str(row["observation_revision_id"]): row for row in rows}
    children: dict[str, list[str]] = {}
    roots: list[Any] = []
    for row in rows:
        supersedes = str(row["supersedes_revision_id"] or "")
        if supersedes:
            children.setdefault(supersedes, []).append(
                str(row["observation_revision_id"])
            )
        else:
            roots.append(row)

    for root in roots:
        root_revision_id = str(root["observation_revision_id"])
        user_id = str(root["user_id"])
        logical_id = _root_logical_observation_id(user_id, root_revision_id)
        pending = [root_revision_id]
        visited: set[str] = set()
        while pending:
            revision_id = pending.pop()
            if revision_id in visited:
                continue
            visited.add(revision_id)
            row = by_id.get(revision_id)
            if row is None or str(row["user_id"]) != user_id:
                continue
            connection.execute(
                "UPDATE molecular_observations SET logical_observation_id = ? "
                "WHERE observation_revision_id = ? "
                "AND logical_observation_id <> ?",
                (logical_id, revision_id, logical_id),
            )
            pending.extend(children.get(revision_id, ()))


def upgrade_lab_schema(connection: Any) -> None:
    """Converge a new or existing workspace on the current positive contract.

    The Lab database is application state rather than a versioned exchange
    artifact. Startup therefore repairs known durable invariants and installs
    the current idempotent tables, indexes, and triggers without classifying or
    rejecting the workspace by a schema-version number.
    """

    repair_observation_logical_roots(connection)
    replace_empty_draft_research_artifact_table(connection)
    connection.executescript(SCHEMA_SQL)
    migrate_legacy_harness_persistence(connection)


def replace_empty_draft_research_artifact_table(connection: Any) -> None:
    """Replace the unreleased, unlinked draft ledger with the current contract.

    The first development draft of this table had no round identity and stored
    an evidence envelope even though these records are explicitly non-evidence.
    There is no truthful way to infer a round or missing execution provenance
    for an existing row.  Empty draft tables can be replaced automatically;
    non-empty ones stop the upgrade instead of silently fabricating metadata.
    """

    columns = _table_columns(connection, "research_artifacts")
    if not columns or {
        "round_id",
        "research_envelope_json",
    }.issubset(columns):
        return
    row = connection.execute(
        "SELECT COUNT(*) AS row_count FROM research_artifacts"
    ).fetchone()
    if row is not None and int(row["row_count"]) > 0:
        raise RuntimeError(
            "the draft research-artifact ledger contains unlinked records and "
            "cannot be upgraded without inventing round or provenance metadata"
        )
    connection.execute("DROP TRIGGER IF EXISTS research_artifacts_immutable")
    connection.execute("DROP TRIGGER IF EXISTS research_artifacts_delete_immutable")
    connection.execute("DROP INDEX IF EXISTS idx_research_artifacts_investigation_profile")
    connection.execute("DROP TABLE research_artifacts")


def migrate_legacy_harness_persistence(connection: Any) -> None:
    """Preserve safe monitoring history, then remove the embedded-harness store.

    The host-owned application has no runtime reader for the former harness
    transport tables.  On first open, useful events are copied into the
    host-neutral investigation timeline after applying the current payload
    boundary.  Command responses, jobs, bindings, transport correlation data,
    malformed events, and unsafe payloads are deliberately not retained.
    """

    if _table_columns(connection, "harness_events") >= (
        _LEGACY_EVENT_REQUIRED_COLUMNS
    ):
        rows = connection.execute(
            "SELECT event_id, investigation_id, sequence, event_type, "
            "payload_json, created_at FROM harness_events "
            "ORDER BY investigation_id, sequence, created_at, event_id"
        ).fetchall()
        next_sequences: dict[str, int] = {}
        for row in rows:
            translated = _translate_legacy_harness_event(row)
            if translated is None:
                continue
            investigation_id = translated["investigation_id"]
            if not _investigation_exists(connection, investigation_id):
                continue
            event_id = stable_id(
                "investigation-event",
                "legacy-embedded-harness",
                investigation_id,
                translated["legacy_event_id"],
            )
            existing = connection.execute(
                "SELECT 1 FROM investigation_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if existing is not None:
                continue
            sequence = next_sequences.get(investigation_id)
            if sequence is None:
                latest = connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) AS latest_sequence "
                    "FROM investigation_events WHERE investigation_id = ?",
                    (investigation_id,),
                ).fetchone()
                sequence = int(latest["latest_sequence"]) + 1
            connection.execute(
                "INSERT INTO investigation_events("
                "event_id, investigation_id, sequence, event_type, "
                "payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    investigation_id,
                    sequence,
                    translated["event_type"],
                    translated["payload_json"],
                    translated["created_at"],
                ),
            )
            next_sequences[investigation_id] = sequence + 1

    for index_name in _LEGACY_HARNESS_INDEXES:
        connection.execute(f'DROP INDEX IF EXISTS "{index_name}"')
    for table_name in _LEGACY_HARNESS_TABLES:
        connection.execute(f'DROP TABLE IF EXISTS "{table_name}"')


def _translate_legacy_harness_event(row: Any) -> JsonObject | None:
    event_type = row["event_type"]
    if not isinstance(event_type, str) or event_type not in (
        _LEGACY_MONITORING_EVENT_TYPES
    ):
        return None
    investigation_id = row["investigation_id"]
    if not isinstance(investigation_id, str) or not investigation_id.strip():
        return None
    created_at = _legacy_timestamp(row["created_at"])
    if created_at is None:
        return None
    raw_payload = row["payload_json"]
    if not isinstance(raw_payload, str) or len(raw_payload.encode("utf-8")) > (
        INVESTIGATION_EVENT_PAYLOAD_MAX_BYTES * 4
    ):
        return None
    try:
        parsed = json.loads(raw_payload, parse_constant=_reject_json_constant)
    except (TypeError, ValueError, RecursionError):
        return None
    if not isinstance(parsed, dict):
        return None
    nested = parsed.get("payload")
    details = _legacy_domain_details(nested if isinstance(nested, dict) else parsed)
    if not details:
        return None
    status = parsed.get("status")
    if (
        isinstance(status, str)
        and status.strip().lower() in _LEGACY_DOMAIN_STATUSES
    ):
        details.setdefault("status", status.strip().lower())
    details["history_origin"] = "legacy_embedded_harness"
    try:
        encoded = _encode_payload(details)
    except (TypeError, ValueError, RecursionError):
        return None
    legacy_event_id = str(row["event_id"] or "").strip()
    if not legacy_event_id:
        legacy_event_id = hashlib.sha256(
            "\x1f".join(
                (
                    investigation_id,
                    str(row["sequence"]),
                    event_type,
                    created_at,
                    raw_payload,
                )
            ).encode("utf-8")
        ).hexdigest()
    return {
        "legacy_event_id": legacy_event_id,
        "investigation_id": investigation_id,
        "event_type": event_type,
        "payload_json": encoded,
        "created_at": created_at,
    }


def _legacy_domain_details(value: JsonObject) -> JsonObject:
    """Keep flat typed domain metadata; discard old host-transport payloads."""

    details: JsonObject = {}
    for field in _LEGACY_DOMAIN_TEXT_FIELDS:
        item = value.get(field)
        if (
            isinstance(item, str)
            and item.strip()
            and len(item) <= 300
            and not any(ord(character) < 32 for character in item)
        ):
            details[field] = item.strip()
    for field in _LEGACY_DOMAIN_INTEGER_FIELDS:
        item = value.get(field)
        if (
            isinstance(item, int)
            and not isinstance(item, bool)
            and 0 <= item <= 1_000_000
        ):
            details[field] = item
    for field in _LEGACY_DOMAIN_BOOLEAN_FIELDS:
        item = value.get(field)
        if isinstance(item, bool):
            details[field] = item
    for field in _LEGACY_DOMAIN_TEXT_ARRAY_FIELDS:
        item = value.get(field)
        if not isinstance(item, list) or len(item) > 100:
            continue
        items = []
        for entry in item:
            if (
                not isinstance(entry, str)
                or not entry.strip()
                or len(entry) > 300
                or any(ord(character) < 32 for character in entry)
            ):
                items = []
                break
            items.append(entry.strip())
        if items:
            details[field] = items
    return details


def _table_columns(connection: Any, table_name: str) -> frozenset[str]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    if exists is None:
        return frozenset()
    return frozenset(
        str(row["name"])
        for row in connection.execute(
            f'PRAGMA table_info("{table_name}")'
        ).fetchall()
    )


def _investigation_exists(connection: Any, investigation_id: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM investigations WHERE investigation_id = ?",
            (investigation_id,),
        ).fetchone()
        is not None
    )


def _legacy_timestamp(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > 100:
        return None
    timestamp = value.strip()
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp if parsed.tzinfo is not None else None


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant: {value}")


def _root_logical_observation_id(user_id: str, revision_id: str) -> str:
    if revision_id.startswith(_REVISION_PREFIX):
        suffix = revision_id.removeprefix(_REVISION_PREFIX)
        if suffix:
            return f"{_LOGICAL_PREFIX}{suffix}"
    digest = hashlib.sha256(
        f"{user_id}\x1f{revision_id}".encode("utf-8")
    ).hexdigest()[:24]
    return f"{_LOGICAL_PREFIX}{digest}"


__all__ = [
    "migrate_legacy_harness_persistence",
    "repair_observation_logical_roots",
    "upgrade_lab_schema",
]
