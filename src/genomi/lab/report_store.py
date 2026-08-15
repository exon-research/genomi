"""Encrypted report bytes and human-reviewed extracted fact proposals."""

from __future__ import annotations

import hashlib
from typing import Any, ContextManager, Protocol

from .models import (
    JsonObject,
    compact_json,
    row_dict,
    stable_id,
    utc_now,
    validate_private_payload,
)


class _ReportStore(Protocol):
    def _connect(self) -> ContextManager[Any]: ...
    def _require_workspace(self, user_id: str) -> None: ...
    def add_source_artifact(self, user_id: str, payload: JsonObject) -> JsonObject: ...
    def add_profile_observation(
        self, user_id: str, payload: JsonObject
    ) -> JsonObject: ...


class ReportStoreMixin:
    """Keep raw report bytes inside the authenticated encrypted DB container."""

    def ingest_report(
        self: _ReportStore,
        user_id: str,
        *,
        content: bytes,
        source_type: str,
        title: str,
        media_type: str,
        source_identifier: str | None = None,
        issued_at: str | None = None,
    ) -> JsonObject:
        self._require_workspace(user_id)
        if not isinstance(content, bytes) or not content:
            raise ValueError("report content must contain bytes")
        if len(content) > 25 * 1024 * 1024:
            raise ValueError("report content exceeds the 25 MiB local intake limit")
        digest = hashlib.sha256(content).hexdigest()
        artifact = self.add_source_artifact(
            user_id,
            {
                "content_sha256": digest,
                "source_type": source_type,
                "title": title,
                "source_identifier": source_identifier,
                "issued_at": issued_at,
                "metadata": {
                    "media_type": media_type,
                    "byte_size": len(content),
                    "storage": "encrypted_local_container",
                },
            },
        )
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT media_type, byte_size, content_bytes FROM source_artifact_contents "
                "WHERE artifact_id = ?",
                (artifact["artifact_id"],),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO source_artifact_contents(artifact_id, media_type, byte_size, "
                    "content_bytes, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        artifact["artifact_id"],
                        media_type,
                        len(content),
                        content,
                        utc_now(),
                    ),
                )
            elif (
                str(existing["media_type"]) != media_type
                or int(existing["byte_size"]) != len(content)
                or bytes(existing["content_bytes"]) != content
            ):
                raise ValueError(
                    "this report fingerprint is already bound to different content metadata"
                )
        return {**artifact, "content_stored": True, "byte_size": len(content)}

    def read_report_content(
        self: _ReportStore, user_id: str, artifact_id: str
    ) -> tuple[bytes, str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content.content_bytes, content.media_type "
                "FROM source_artifact_contents AS content "
                "JOIN source_artifacts AS artifact ON artifact.artifact_id = content.artifact_id "
                "WHERE content.artifact_id = ? AND artifact.user_id = ?",
                (artifact_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return bytes(row["content_bytes"]), str(row["media_type"])

    def propose_report_facts(
        self: _ReportStore,
        user_id: str,
        *,
        artifact_id: str,
        proposals: list[JsonObject],
        command_id: str,
    ) -> list[JsonObject]:
        if not proposals:
            raise ValueError("at least one proposed report fact is required")
        with self._connect() as connection:
            artifact = connection.execute(
                "SELECT 1 FROM source_artifacts WHERE artifact_id = ? AND user_id = ?",
                (artifact_id, user_id),
            ).fetchone()
            if artifact is None:
                raise KeyError(artifact_id)
            for index, proposal in enumerate(proposals):
                if not isinstance(proposal, dict):
                    raise ValueError("each proposed report fact must be an object")
                validate_private_payload(proposal)
                proposal_id = stable_id("report-fact-proposal", command_id, str(index))
                connection.execute(
                    "INSERT INTO report_fact_proposals(proposal_id, user_id, artifact_id, "
                    "proposal_json, status, created_at) VALUES (?, ?, ?, ?, 'proposed', ?) "
                    "ON CONFLICT(proposal_id) DO NOTHING",
                    (
                        proposal_id,
                        user_id,
                        artifact_id,
                        compact_json(proposal),
                        utc_now(),
                    ),
                )
            rows = connection.execute(
                "SELECT * FROM report_fact_proposals WHERE user_id = ? AND artifact_id = ? "
                "AND proposal_id IN ("
                + ",".join("?" for _ in proposals)
                + ") ORDER BY created_at, proposal_id",
                (
                    user_id,
                    artifact_id,
                    *[
                        stable_id("report-fact-proposal", command_id, str(index))
                        for index in range(len(proposals))
                    ],
                ),
            ).fetchall()
        result = [row_dict(row) for row in rows]
        if [item["proposal"] for item in result] != proposals:
            raise ValueError(
                "command_id was reused for different report fact proposals"
            )
        return result

    def review_report_facts(
        self: _ReportStore,
        user_id: str,
        *,
        decisions: list[JsonObject],
        reviewed_by: str,
    ) -> list[JsonObject]:
        if not decisions:
            raise ValueError("at least one report fact review decision is required")
        reviewed: list[JsonObject] = []
        for decision in decisions:
            if not isinstance(decision, dict):
                raise ValueError("each report fact decision must be an object")
            proposal_id = str(decision.get("proposal_id") or "").strip()
            action = str(decision.get("action") or "").strip()
            if not proposal_id or action not in {"accept", "reject"}:
                raise ValueError(
                    "report fact decisions require proposal_id and accept/reject"
                )
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM report_fact_proposals WHERE proposal_id = ? AND user_id = ?",
                    (proposal_id, user_id),
                ).fetchone()
            if row is None:
                raise KeyError(proposal_id)
            proposal = row_dict(row)
            if proposal["status"] != "proposed":
                if (action == "accept" and proposal["status"] == "accepted") or (
                    action == "reject" and proposal["status"] == "rejected"
                ):
                    reviewed.append(proposal)
                    continue
                raise ValueError("a report fact proposal has already been reviewed")
            observation_id = None
            if action == "accept":
                edited = decision.get("observation")
                if edited is not None and not isinstance(edited, dict):
                    raise ValueError("edited observation must be an object")
                observation = {**proposal["proposal"], **(edited or {})}
                observation.update(
                    {
                        "artifact_id": proposal["artifact_id"],
                        "source_class": "issued_record",
                        "verification_state": "record_confirmed",
                        "assertion_author": "imported_record",
                        "reviewed_by": reviewed_by,
                    }
                )
                saved = self.add_profile_observation(user_id, observation)
                observation_id = saved["observation_revision_id"]
            with self._connect() as connection:
                connection.execute(
                    "UPDATE report_fact_proposals SET status = ?, "
                    "accepted_observation_revision_id = ?, reviewed_at = ? "
                    "WHERE proposal_id = ? AND status = 'proposed'",
                    (
                        "accepted" if action == "accept" else "rejected",
                        observation_id,
                        utc_now(),
                        proposal_id,
                    ),
                )
                updated = connection.execute(
                    "SELECT * FROM report_fact_proposals WHERE proposal_id = ?",
                    (proposal_id,),
                ).fetchone()
            reviewed.append(row_dict(updated))
        return reviewed

    def list_report_fact_proposals(
        self: _ReportStore, user_id: str, artifact_id: str | None = None
    ) -> list[JsonObject]:
        query = "SELECT * FROM report_fact_proposals WHERE user_id = ?"
        params: tuple[object, ...] = (user_id,)
        if artifact_id:
            query += " AND artifact_id = ?"
            params += (artifact_id,)
        query += " ORDER BY created_at, proposal_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [row_dict(row) for row in rows]


__all__ = ["ReportStoreMixin"]
