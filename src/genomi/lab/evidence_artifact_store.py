"""Persistence for versioned investigation plans and briefs."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, ContextManager, Protocol

from .models import JsonObject, compact_json, required_text, row_dict, utc_now


class _ArtifactStore(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def atomic_write(self) -> ContextManager[None]: ...

    def validate_plan(self, investigation_id: str, plan: JsonObject) -> None: ...

    def validate_brief(self, investigation_id: str, brief: JsonObject) -> None: ...

    def create_evidence_snapshot(
        self, investigation_id: str, *, reason: object, force_new: bool = False
    ) -> JsonObject: ...


class EvidenceArtifactStoreMixin:
    """Write user-reviewed plans, acceptances, and brief versions."""

    def commit_plan(
        self: _ArtifactStore,
        investigation_id: str,
        plan: JsonObject,
    ) -> JsonObject:
        self.validate_plan(investigation_id, plan)
        with self._connect() as connection:
            target = connection.execute(
                "SELECT patient_molecular_snapshot_id FROM investigations "
                "WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            if target is None:
                raise KeyError(investigation_id)
            current = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM plan_versions "
                "WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            version = int(current["version"]) + 1
            plan_id = f"plan-{uuid.uuid4().hex}"
            connection.execute(
                "INSERT INTO plan_versions(plan_version_id, investigation_id, "
                "patient_molecular_snapshot_id, version, plan_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    plan_id,
                    investigation_id,
                    target["patient_molecular_snapshot_id"],
                    version,
                    compact_json(plan),
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM plan_versions WHERE plan_version_id = ?", (plan_id,)
            ).fetchone()
        return row_dict(row)

    def accept_plan(
        self: _ArtifactStore,
        investigation_id: str,
        *,
        plan_version_id: object,
        user_id: object,
        workspace_session_id: object,
        plan_sha256: object,
        approved: object,
    ) -> JsonObject:
        """Record acceptance of the exact current investigation plan."""

        if approved is not True:
            raise ValueError("plan acceptance requires explicit approval")
        plan_version = required_text(plan_version_id, "plan_version_id", 200)
        user = required_text(user_id, "user_id", 300)
        session = required_text(workspace_session_id, "workspace_session_id", 300)
        supplied_hash = required_text(plan_sha256, "plan_sha256", 128)
        with self._connect() as connection:
            investigation = connection.execute(
                "SELECT user_id, patient_molecular_snapshot_id FROM investigations "
                "WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            if investigation is None:
                raise KeyError(investigation_id)
            if str(investigation["user_id"]) != user:
                raise ValueError("the plan does not belong to the current Genomi user")
            current = connection.execute(
                "SELECT * FROM plan_versions WHERE investigation_id = ? "
                "AND patient_molecular_snapshot_id IS ? ORDER BY version DESC LIMIT 1",
                (
                    investigation_id,
                    investigation["patient_molecular_snapshot_id"],
                ),
            ).fetchone()
            if current is None or str(current["plan_version_id"]) != plan_version:
                raise ValueError(
                    "only the current molecular-context plan can be accepted"
                )
            expected_hash = hashlib.sha256(
                str(current["plan_json"]).encode("utf-8")
            ).hexdigest()
            if supplied_hash != expected_hash:
                raise ValueError("the plan changed after it was reviewed")
            existing = connection.execute(
                "SELECT * FROM plan_acceptances WHERE plan_version_id = ?",
                (plan_version,),
            ).fetchone()
            if existing is not None:
                saved = row_dict(existing)
                if any(
                    saved.get(key) != value
                    for key, value in {
                        "investigation_id": investigation_id,
                        "user_id": user,
                        "plan_sha256": supplied_hash,
                    }.items()
                ):
                    raise ValueError("the saved plan acceptance does not match")
                return saved
            acceptance_id = f"plan-acceptance-{uuid.uuid4().hex}"
            connection.execute(
                "INSERT INTO plan_acceptances(plan_acceptance_id, plan_version_id, "
                "investigation_id, user_id, workspace_session_id, plan_sha256, accepted_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    acceptance_id,
                    plan_version,
                    investigation_id,
                    user,
                    session,
                    supplied_hash,
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM plan_acceptances WHERE plan_acceptance_id = ?",
                (acceptance_id,),
            ).fetchone()
        return row_dict(row)

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
