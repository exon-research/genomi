"""Persistence for versioned investigation briefs."""

from __future__ import annotations

import uuid
from typing import Any, ContextManager, Protocol

from .models import JsonObject, compact_json, row_dict, utc_now


class _ArtifactStore(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def atomic_write(self) -> ContextManager[None]: ...

    def validate_brief(self, investigation_id: str, brief: JsonObject) -> None: ...

    def create_evidence_snapshot(
        self, investigation_id: str, *, reason: object, force_new: bool = False
    ) -> JsonObject: ...


class EvidenceArtifactStoreMixin:
    """Write evidence-pinned brief versions."""

    def commit_brief(
        self: _ArtifactStore, investigation_id: str, brief: JsonObject
    ) -> JsonObject:
        with self.atomic_write():
            self.validate_brief(investigation_id, brief)
            evidence_snapshot = self.create_evidence_snapshot(
                investigation_id, reason="brief_evidence_basis"
            )
            with self._connect() as connection:
                investigation = connection.execute(
                    "SELECT patient_molecular_snapshot_id FROM investigations "
                    "WHERE investigation_id = ?",
                    (investigation_id,),
                ).fetchone()
                if investigation is None:
                    raise KeyError(investigation_id)
                current = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) AS version FROM brief_versions "
                    "WHERE investigation_id = ?",
                    (investigation_id,),
                ).fetchone()
                version = int(current["version"]) + 1
                brief_id = f"brief-{uuid.uuid4().hex}"
                prior_row = connection.execute(
                    "SELECT * FROM brief_versions WHERE investigation_id = ? "
                    "ORDER BY version DESC LIMIT 1",
                    (investigation_id,),
                ).fetchone()
                prior = row_dict(prior_row) if prior_row is not None else None
                prior_evidence_ids: set[str] = set()
                if prior is not None and prior.get("evidence_snapshot_id"):
                    prior_evidence_row = connection.execute(
                        "SELECT evidence_record_ids_json FROM evidence_snapshots "
                        "WHERE evidence_snapshot_id = ?",
                        (prior["evidence_snapshot_id"],),
                    ).fetchone()
                    if prior_evidence_row is not None:
                        prior_evidence_ids = set(
                            row_dict(prior_evidence_row).get("evidence_record_ids")
                            or []
                        )
                current_evidence_ids = set(
                    evidence_snapshot.get("evidence_record_ids") or []
                )
                diff = self._brief_version_diff(
                    prior,
                    brief,
                    patient_molecular_snapshot_id=str(
                        investigation["patient_molecular_snapshot_id"] or ""
                    ),
                    evidence_snapshot_id=str(
                        evidence_snapshot["evidence_snapshot_id"]
                    ),
                    prior_evidence_ids=prior_evidence_ids,
                    current_evidence_ids=current_evidence_ids,
                )
                connection.execute(
                    "INSERT INTO brief_versions(brief_version_id, investigation_id, "
                    "version, patient_molecular_snapshot_id, evidence_snapshot_id, "
                    "prior_brief_version_id, diff_json, brief_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        brief_id,
                        investigation_id,
                        version,
                        investigation["patient_molecular_snapshot_id"],
                        evidence_snapshot["evidence_snapshot_id"],
                        prior.get("brief_version_id") if prior is not None else None,
                        compact_json(diff),
                        compact_json(brief),
                        utc_now(),
                    ),
                )
                connection.execute(
                    "UPDATE investigations SET status = 'completed', "
                    "domain_revision = domain_revision + 1, updated_at = ? "
                    "WHERE investigation_id = ?",
                    (utc_now(), investigation_id),
                )
                row = connection.execute(
                    "SELECT * FROM brief_versions WHERE brief_version_id = ?",
                    (brief_id,),
                ).fetchone()
        return row_dict(row)

    @staticmethod
    def _brief_version_diff(
        prior: JsonObject | None,
        brief: JsonObject,
        *,
        patient_molecular_snapshot_id: str,
        evidence_snapshot_id: str,
        prior_evidence_ids: set[str],
        current_evidence_ids: set[str],
    ) -> JsonObject:
        prior_brief = prior.get("brief") if prior is not None else None
        if not isinstance(prior_brief, dict):
            prior_brief = {}

        def changed_ids(field: str) -> JsonObject:
            old = set(prior_brief.get(field) or [])
            new = set(brief.get(field) or [])
            return {"added": sorted(new - old), "removed": sorted(old - new)}

        return {
            "patient_molecular_snapshot": {
                "from": prior.get("patient_molecular_snapshot_id")
                if prior is not None
                else None,
                "to": patient_molecular_snapshot_id,
                "changed": prior is not None
                and prior.get("patient_molecular_snapshot_id")
                != patient_molecular_snapshot_id,
            },
            "evidence_snapshot": {
                "from": prior.get("evidence_snapshot_id")
                if prior is not None
                else None,
                "to": evidence_snapshot_id,
                "changed": prior is not None
                and prior.get("evidence_snapshot_id") != evidence_snapshot_id,
                "evidence_record_ids": {
                    "added": sorted(current_evidence_ids - prior_evidence_ids),
                    "removed": sorted(prior_evidence_ids - current_evidence_ids),
                },
            },
            "clinical_stage_changed": bool(prior_brief)
            and prior_brief.get("clinical_stage") != brief.get("clinical_stage"),
            "modality_badges": changed_ids("modality_badges"),
            "hypothesis_ids": changed_ids("hypothesis_ids"),
            "gap_ids": changed_ids("gap_ids"),
        }
