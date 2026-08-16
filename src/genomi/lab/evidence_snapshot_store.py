"""Immutable evidence-ledger snapshot persistence."""

from __future__ import annotations

import uuid
from typing import Any, ContextManager, Protocol

from .models import JsonObject, compact_json, required_text, row_dict, utc_now


class _SnapshotStore(Protocol):
    def _connect(self) -> ContextManager[Any]: ...


class EvidenceSnapshotStoreMixin:
    """Persist and compare immutable evidence-ledger bases."""

    def create_evidence_snapshot(
        self: _SnapshotStore,
        investigation_id: str,
        *,
        reason: object,
        force_new: bool = False,
        advance_revision: bool = True,
    ) -> JsonObject:
        """Pin the exact ledger and molecular context used for synthesis."""

        if not isinstance(force_new, bool):
            raise ValueError("force_new must be a boolean")
        if not isinstance(advance_revision, bool):
            raise ValueError("advance_revision must be a boolean")
        reason_value = required_text(reason, "evidence snapshot reason", 500)
        with self._connect() as connection:
            investigation = connection.execute(
                "SELECT patient_molecular_snapshot_id, evidence_snapshot_id "
                "FROM investigations WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            if investigation is None:
                raise KeyError(investigation_id)
            profile = None
            if investigation["patient_molecular_snapshot_id"]:
                profile = connection.execute(
                    "SELECT agi_id, agi_snapshot_id FROM profile_snapshots "
                    "WHERE patient_molecular_snapshot_id = ?",
                    (investigation["patient_molecular_snapshot_id"],),
                ).fetchone()
            evidence_ids = [
                str(row["evidence_record_id"])
                for row in connection.execute(
                    "SELECT evidence.evidence_record_id FROM evidence_records AS evidence "
                    "WHERE evidence.investigation_id = ? AND ("
                    "evidence.patient_molecular_snapshot_id IS ? "
                    "OR EXISTS ("
                    "SELECT 1 FROM captured_provider_results AS captured "
                    "JOIN provider_result_receipts AS receipt "
                    "ON receipt.provider_result_receipt_id = captured.provider_result_receipt_id "
                    "WHERE captured.evidence_record_id = evidence.evidence_record_id "
                    "AND receipt.result_kind = 'public_source_evidence'"
                    ") OR EXISTS ("
                    "SELECT 1 FROM captured_evidence_results AS captured "
                    "JOIN genomi_result_receipts AS receipt "
                    "ON receipt.result_receipt_id = captured.result_receipt_id "
                    "WHERE captured.evidence_record_id = evidence.evidence_record_id "
                    "AND (receipt.agi_snapshot_id IS NULL "
                    "OR (receipt.agi_id IS ? AND receipt.agi_snapshot_id IS ?))"
                    ")) ORDER BY evidence.created_at, evidence.evidence_record_id",
                    (
                        investigation_id,
                        investigation["patient_molecular_snapshot_id"],
                        profile["agi_id"] if profile is not None else None,
                        profile["agi_snapshot_id"] if profile is not None else None,
                    ),
                ).fetchall()
            ]
            current_snapshot_id = str(investigation["evidence_snapshot_id"] or "")
            if current_snapshot_id and not force_new:
                current = connection.execute(
                    "SELECT * FROM evidence_snapshots WHERE evidence_snapshot_id = ?",
                    (current_snapshot_id,),
                ).fetchone()
                if current is not None:
                    current_value = row_dict(current)
                    if (
                        current_value.get("patient_molecular_snapshot_id")
                        == investigation["patient_molecular_snapshot_id"]
                        and current_value.get("evidence_record_ids") == evidence_ids
                    ):
                        return current_value
            version_row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM evidence_snapshots "
                "WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            version = int(version_row["version"]) + 1
            evidence_snapshot_id = f"evidence-snapshot-{uuid.uuid4().hex}"
            now = utc_now()
            prior = None
            prior_ids: set[str] = set()
            if current_snapshot_id:
                prior = connection.execute(
                    "SELECT * FROM evidence_snapshots WHERE evidence_snapshot_id = ?",
                    (current_snapshot_id,),
                ).fetchone()
                if prior is not None:
                    prior_ids = set(row_dict(prior).get("evidence_record_ids") or [])
            current_ids = set(evidence_ids)
            diff = {
                "evidence_record_ids": {
                    "added": sorted(current_ids - prior_ids),
                    "removed": sorted(prior_ids - current_ids),
                },
                "patient_molecular_snapshot_changed": bool(prior)
                and prior["patient_molecular_snapshot_id"]
                != investigation["patient_molecular_snapshot_id"],
            }
            connection.execute(
                "INSERT INTO evidence_snapshots(evidence_snapshot_id, investigation_id, "
                "patient_molecular_snapshot_id, version, evidence_record_ids_json, "
                "prior_evidence_snapshot_id, diff_json, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    evidence_snapshot_id,
                    investigation_id,
                    investigation["patient_molecular_snapshot_id"],
                    version,
                    compact_json(evidence_ids),
                    current_snapshot_id or None,
                    compact_json(diff),
                    reason_value,
                    now,
                ),
            )
            if advance_revision:
                connection.execute(
                    "UPDATE investigations SET evidence_snapshot_id = ?, "
                    "domain_revision = domain_revision + 1, updated_at = ? "
                    "WHERE investigation_id = ?",
                    (evidence_snapshot_id, now, investigation_id),
                )
            else:
                connection.execute(
                    "UPDATE investigations SET evidence_snapshot_id = ? "
                    "WHERE investigation_id = ?",
                    (evidence_snapshot_id, investigation_id),
                )
            row = connection.execute(
                "SELECT * FROM evidence_snapshots WHERE evidence_snapshot_id = ?",
                (evidence_snapshot_id,),
            ).fetchone()
        return row_dict(row)

    def compare_evidence_snapshots(
        self: _SnapshotStore, older_id: str, newer_id: str
    ) -> JsonObject:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM evidence_snapshots WHERE evidence_snapshot_id IN (?, ?)",
                (older_id, newer_id),
            ).fetchall()
        by_id = {str(row["evidence_snapshot_id"]): row_dict(row) for row in rows}
        if set(by_id) != {older_id, newer_id}:
            raise KeyError("evidence snapshot not found")
        older = by_id[older_id]
        newer = by_id[newer_id]
        if older["investigation_id"] != newer["investigation_id"]:
            raise ValueError("evidence snapshots must belong to one investigation")
        old_ids = set(older.get("evidence_record_ids") or [])
        new_ids = set(newer.get("evidence_record_ids") or [])
        return {
            "investigation_id": older["investigation_id"],
            "older_evidence_snapshot_id": older_id,
            "newer_evidence_snapshot_id": newer_id,
            "evidence_record_ids": {
                "added": sorted(new_ids - old_ids),
                "removed": sorted(old_ids - new_ids),
            },
            "patient_molecular_snapshot_changed": older.get(
                "patient_molecular_snapshot_id"
            )
            != newer.get("patient_molecular_snapshot_id"),
        }

    @staticmethod
    def _stable_evidence_identity(value: object) -> object:
        volatile_keys = {"retrieved_at", "indexed_at", "current_source_checked_at"}
        if isinstance(value, dict):
            return {
                key: EvidenceSnapshotStoreMixin._stable_evidence_identity(item)
                for key, item in value.items()
                if key not in volatile_keys
            }
        if isinstance(value, list):
            return [
                EvidenceSnapshotStoreMixin._stable_evidence_identity(item)
                for item in value
            ]
        return value
