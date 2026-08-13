"""Idempotent startup upgrades for durable GenomiLab domain invariants."""

from __future__ import annotations

import hashlib
from typing import Any

from .schema import SCHEMA_SQL


_REVISION_PREFIX = "observation-revision-"
_LOGICAL_PREFIX = "observation-"


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
    connection.executescript(SCHEMA_SQL)


def _root_logical_observation_id(user_id: str, revision_id: str) -> str:
    if revision_id.startswith(_REVISION_PREFIX):
        suffix = revision_id.removeprefix(_REVISION_PREFIX)
        if suffix:
            return f"{_LOGICAL_PREFIX}{suffix}"
    digest = hashlib.sha256(
        f"{user_id}\x1f{revision_id}".encode("utf-8")
    ).hexdigest()[:24]
    return f"{_LOGICAL_PREFIX}{digest}"


__all__ = ["repair_observation_logical_roots", "upgrade_lab_schema"]
