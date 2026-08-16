"""Canonical investigations and approved molecular-profile projection."""

from __future__ import annotations

import uuid
from typing import Any, ContextManager, Protocol

from .models import (
    QUESTION_MAX,
    JsonObject,
    optional_text,
    required_text,
    row_dict,
    utc_now,
)


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def _require_workspace(self, user_id: str) -> None: ...

    def get_investigation(self, investigation_id: str) -> JsonObject: ...

    def get_profile_snapshot(self, snapshot_id: str) -> JsonObject: ...


class InvestigationStoreMixin:
    """Investigation lifecycle and pinned-profile projection persistence."""

    def create_investigation(
        self: _StoreContract,
        user_id: str,
        *,
        question: object,
        disease_scope: object = None,
    ) -> JsonObject:
        self._require_workspace(user_id)
        question_value = required_text(question, "question", QUESTION_MAX)
        investigation_id = f"investigation-{uuid.uuid4().hex}"
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO investigations(
                    investigation_id, user_id, question, disease_scope, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?)
                """,
                (
                    investigation_id,
                    user_id,
                    question_value,
                    optional_text(disease_scope, "disease_scope", QUESTION_MAX),
                    now,
                    now,
                ),
            )
        return self.get_investigation(investigation_id)

    def get_investigation(self: _StoreContract, investigation_id: str) -> JsonObject:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM investigations WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(investigation_id)
        return row_dict(row)

    def list_investigations(self: _StoreContract, user_id: str) -> list[JsonObject]:
        self._require_workspace(user_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM investigations WHERE user_id = ? "
                "ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [row_dict(row) for row in rows]

    def set_investigation_status(
        self: _StoreContract,
        investigation_id: str,
        status: object,
        *,
        expected_revision: int | None = None,
    ) -> JsonObject:
        allowed = {
            "awaiting_context_approval",
            "approved",
            "running",
            "needs_user_input",
            "paused_private_context",
            "completed",
            "cancelled",
            "failed",
        }
        status_value = required_text(status, "status", 80)
        if status_value not in allowed:
            raise ValueError("unsupported investigation status")
        with self._connect() as connection:
            current = connection.execute(
                "SELECT domain_revision FROM investigations WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            if current is None:
                raise KeyError(investigation_id)
            if expected_revision is not None and int(current["domain_revision"]) != int(
                expected_revision
            ):
                raise ValueError("investigation revision conflict")
            connection.execute(
                "UPDATE investigations SET status = ?, domain_revision = domain_revision + 1, "
                "updated_at = ? WHERE investigation_id = ?",
                (status_value, utc_now(), investigation_id),
            )
        return self.get_investigation(investigation_id)

    def project_investigation_profile(
        self: _StoreContract, investigation_id: str
    ) -> JsonObject:
        investigation = self.get_investigation(investigation_id)
        snapshot_id = investigation.get("patient_molecular_snapshot_id")
        if not snapshot_id:
            raise ValueError(
                "the investigation has no approved molecular-profile snapshot"
            )
        snapshot = self.get_profile_snapshot(str(snapshot_id))
        revision_ids = list(snapshot.get("observation_revision_ids") or [])
        artifact_ids = list(snapshot.get("artifact_ids") or [])
        specimen_ids = list(snapshot.get("specimen_ids") or [])
        assay_ids = list(snapshot.get("assay_ids") or [])
        with self._connect() as connection:
            rows = []
            if revision_ids:
                placeholders = ",".join("?" for _ in revision_ids)
                rows = connection.execute(
                    f"SELECT * FROM molecular_observations WHERE user_id = ? "
                    f"AND observation_revision_id IN ({placeholders})",
                    (investigation["user_id"], *revision_ids),
                ).fetchall()
            artifacts = self._rows_for_ids(
                connection,
                table="source_artifacts",
                identifier_column="artifact_id",
                identifiers=artifact_ids,
                user_id=str(investigation["user_id"]),
            )
            specimens = self._rows_for_ids(
                connection,
                table="specimens",
                identifier_column="specimen_id",
                identifiers=specimen_ids,
                user_id=str(investigation["user_id"]),
            )
            assays = self._rows_for_ids(
                connection,
                table="assays",
                identifier_column="assay_id",
                identifiers=assay_ids,
                user_id=str(investigation["user_id"]),
            )
        by_id = {str(row["observation_revision_id"]): row_dict(row) for row in rows}
        missing_revision_ids = sorted(set(revision_ids) - set(by_id))
        if missing_revision_ids:
            raise ValueError(
                "approved profile snapshot references missing observation revisions: "
                + ", ".join(missing_revision_ids)
            )
        return {
            "investigation_id": investigation_id,
            "patient_molecular_snapshot_id": snapshot_id,
            "user_id": investigation["user_id"],
            "agi_id": snapshot.get("agi_id"),
            "agi_snapshot_id": snapshot.get("agi_snapshot_id"),
            "observations": [by_id[revision_id] for revision_id in revision_ids],
            "source_artifacts": [row_dict(row) for row in artifacts],
            "specimens": [row_dict(row) for row in specimens],
            "assays": [row_dict(row) for row in assays],
            "modality_coverage": list(snapshot.get("modality_coverage") or []),
        }

    @staticmethod
    def _rows_for_ids(
        connection: Any,
        *,
        table: str,
        identifier_column: str,
        identifiers: list[str],
        user_id: str,
    ) -> list[Any]:
        allowed = {
            ("source_artifacts", "artifact_id"),
            ("specimens", "specimen_id"),
            ("assays", "assay_id"),
        }
        if (table, identifier_column) not in allowed:
            raise ValueError("unsupported profile projection entity")
        if not identifiers:
            return []
        placeholders = ",".join("?" for _ in identifiers)
        rows = list(
            connection.execute(
                f"SELECT * FROM {table} WHERE user_id = ? "
                f"AND {identifier_column} IN ({placeholders})",
                (user_id, *identifiers),
            ).fetchall()
        )
        returned_ids = {str(row[identifier_column]) for row in rows}
        missing_ids = sorted(set(identifiers) - returned_ids)
        if missing_ids:
            raise ValueError(
                f"approved profile snapshot references missing {table}: "
                + ", ".join(missing_ids)
            )
        by_id = {str(row[identifier_column]): row for row in rows}
        return [by_id[identifier] for identifier in identifiers]
