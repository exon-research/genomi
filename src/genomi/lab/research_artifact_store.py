"""Immutable persistence for round-bound nonclinical research artifacts."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, ContextManager, Protocol

from .models import JsonObject, compact_json, required_text, row_dict, utc_now
from .research_artifact_contract import (
    normalize_research_artifact,
    research_artifact_envelope,
    research_artifact_system,
    research_artifact_view,
)


class _ResearchArtifactStore(Protocol):
    def _connect(self) -> ContextManager[Any]: ...


class ResearchArtifactStoreMixin:
    """Write-once ledger independent of evidence, hypotheses, and briefs."""

    def commit_research_artifact(
        self: _ResearchArtifactStore,
        investigation_id: str,
        *,
        round_id: object,
        deduplication_key: object,
        origin: object,
        artifact: object,
        allowed_origins: frozenset[str],
    ) -> tuple[JsonObject, bool]:
        investigation = required_text(investigation_id, "investigation_id", 200)
        round_identifier = required_text(round_id, "round_id", 200)
        dedup = required_text(deduplication_key, "deduplication_key", 300)
        artifact_kind, origin_value, normalized = normalize_research_artifact(
            origin=origin,
            artifact=artifact,
            allowed_origins=allowed_origins,
        )
        system = research_artifact_system(artifact_kind)
        artifact_json = compact_json(normalized)
        content_sha256 = hashlib.sha256(
            compact_json(
                {
                    "artifact_kind": artifact_kind,
                    "origin": origin_value,
                    "artifact": normalized,
                }
            ).encode("utf-8")
        ).hexdigest()
        research_envelope = research_artifact_envelope(
            artifact_kind=artifact_kind,
            system=system,
            origin=origin_value,
        )
        research_envelope_json = compact_json(research_envelope)

        with self._connect() as connection:
            investigation_row = connection.execute(
                "SELECT patient_molecular_snapshot_id FROM investigations "
                "WHERE investigation_id = ?",
                (investigation,),
            ).fetchone()
            if investigation_row is None:
                raise KeyError(investigation)
            snapshot_id = investigation_row["patient_molecular_snapshot_id"]
            if not snapshot_id:
                raise ValueError(
                    "a research artifact requires an approved molecular-profile snapshot"
                )
            round_row = connection.execute(
                "SELECT round_id, round_number FROM investigation_rounds "
                "WHERE round_id = ? AND investigation_id = ? "
                "AND patient_molecular_snapshot_id = ?",
                (round_identifier, investigation, snapshot_id),
            ).fetchone()
            if round_row is None:
                raise ValueError(
                    "a research artifact must link to a round in the current approved profile snapshot"
                )
            existing = connection.execute(
                "SELECT * FROM research_artifacts WHERE investigation_id = ? "
                "AND patient_molecular_snapshot_id = ? AND round_id = ? "
                "AND deduplication_key = ?",
                (investigation, snapshot_id, round_identifier, dedup),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["artifact_kind"]) != artifact_kind
                    or str(existing["system"]) != system
                    or str(existing["origin"]) != origin_value
                    or str(existing["content_sha256"]) != content_sha256
                    or str(existing["artifact_json"]) != artifact_json
                    or str(existing["research_envelope_json"])
                    != research_envelope_json
                ):
                    raise ValueError(
                        "research artifact deduplication key was reused for different content"
                    )
                existing_view = row_dict(existing)
                existing_view["round_number"] = int(round_row["round_number"])
                return research_artifact_view(existing_view), True

            research_artifact_id = f"research-artifact-{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO research_artifacts(
                    research_artifact_id, investigation_id,
                    patient_molecular_snapshot_id, round_id, deduplication_key,
                    artifact_kind, system, origin, content_sha256,
                    artifact_json, research_envelope_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    research_artifact_id,
                    investigation,
                    snapshot_id,
                    round_identifier,
                    dedup,
                    artifact_kind,
                    system,
                    origin_value,
                    content_sha256,
                    artifact_json,
                    research_envelope_json,
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT artifacts.*, rounds.round_number "
                "FROM research_artifacts AS artifacts "
                "JOIN investigation_rounds AS rounds "
                "ON rounds.round_id = artifacts.round_id "
                "WHERE artifacts.research_artifact_id = ?",
                (research_artifact_id,),
            ).fetchone()
        return research_artifact_view(row_dict(row)), False

    def get_research_artifact(
        self: _ResearchArtifactStore,
        investigation_id: str,
        research_artifact_id: str,
    ) -> JsonObject:
        investigation = required_text(investigation_id, "investigation_id", 200)
        identifier = required_text(
            research_artifact_id, "research_artifact_id", 200
        )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT artifacts.*, rounds.round_number "
                "FROM research_artifacts AS artifacts "
                "JOIN investigation_rounds AS rounds "
                "ON rounds.round_id = artifacts.round_id "
                "WHERE artifacts.investigation_id = ? "
                "AND artifacts.research_artifact_id = ?",
                (investigation, identifier),
            ).fetchone()
        if row is None:
            raise KeyError(identifier)
        return research_artifact_view(row_dict(row))

    def list_research_artifacts(
        self: _ResearchArtifactStore,
        investigation_id: str,
        *,
        current_only: bool = True,
    ) -> list[JsonObject]:
        investigation = required_text(investigation_id, "investigation_id", 200)
        with self._connect() as connection:
            investigation_row = connection.execute(
                "SELECT patient_molecular_snapshot_id FROM investigations "
                "WHERE investigation_id = ?",
                (investigation,),
            ).fetchone()
            if investigation_row is None:
                raise KeyError(investigation)
            if current_only:
                rows = connection.execute(
                    "SELECT artifacts.*, rounds.round_number "
                    "FROM research_artifacts AS artifacts "
                    "JOIN investigation_rounds AS rounds "
                    "ON rounds.round_id = artifacts.round_id "
                    "WHERE artifacts.investigation_id = ? "
                    "AND artifacts.patient_molecular_snapshot_id IS ? "
                    "ORDER BY rounds.round_number, artifacts.created_at",
                    (
                        investigation,
                        investigation_row["patient_molecular_snapshot_id"],
                    ),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT artifacts.*, rounds.round_number "
                    "FROM research_artifacts AS artifacts "
                    "JOIN investigation_rounds AS rounds "
                    "ON rounds.round_id = artifacts.round_id "
                    "WHERE artifacts.investigation_id = ? "
                    "ORDER BY rounds.round_number, artifacts.created_at",
                    (investigation,),
                ).fetchall()
        return [research_artifact_view(row_dict(row)) for row in rows]


__all__ = ["ResearchArtifactStoreMixin"]
