"""Clinician brief publication and consolidated investigation reads."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping

from .artifact_validation import BRIEF_CLINICAL_BOUNDARY
from .models import JsonObject, compact_json, required_text, row_dict, utc_now, validate_private_payload
from .orchestrator_support import (
    OrchestratorStoreContract,
    command_replay,
    require_cycle,
    require_investigation_revision,
    save_command,
)


class OrchestratorBriefStoreMixin:
    def publish_brief(
        self: OrchestratorStoreContract,
        investigation_id: str,
        *, cycle_id: object, brief: object, command_id: object, expected_revision: object,
    ) -> JsonObject:
        if not isinstance(brief, Mapping):
            raise ValueError("brief must be an object")
        brief_value = dict(brief)
        request = {"cycle_id": cycle_id, "brief": brief_value, "expected_revision": expected_revision}
        command, request_hash, replay = command_replay(
            self, investigation_id=investigation_id, operation="lab.publish_brief",
            command_id=command_id, request=request,
        )
        if replay is not None:
            return replay
        with self.atomic_write():
            investigation = require_investigation_revision(self, investigation_id, expected_revision)
            require_cycle(self, investigation_id, cycle_id)
            self._validate_orchestrator_brief(investigation, brief_value)
            evidence_snapshot = self.create_evidence_snapshot(
                investigation_id, reason="clinician_brief_evidence_basis"
            )
            with self._connect() as connection:
                prior = connection.execute(
                    "SELECT * FROM brief_versions WHERE investigation_id = ? ORDER BY version DESC LIMIT 1",
                    (investigation_id,),
                ).fetchone()
                version = int(prior["version"]) + 1 if prior is not None else 1
                brief_version_id = f"brief-{uuid.uuid4().hex}"
                diff = {
                    "prior_brief_version_id": prior["brief_version_id"] if prior is not None else None,
                    "profile_snapshot_id": investigation.get("patient_molecular_snapshot_id"),
                    "evidence_snapshot_id": evidence_snapshot["evidence_snapshot_id"],
                }
                connection.execute(
                    "INSERT INTO brief_versions(brief_version_id, investigation_id, version, "
                    "patient_molecular_snapshot_id, evidence_snapshot_id, prior_brief_version_id, "
                    "diff_json, brief_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (brief_version_id, investigation_id, version,
                     investigation.get("patient_molecular_snapshot_id"), evidence_snapshot["evidence_snapshot_id"],
                     prior["brief_version_id"] if prior is not None else None,
                     compact_json(diff), compact_json(brief_value), utc_now()),
                )
                connection.execute(
                    "UPDATE investigations SET domain_revision = domain_revision + 1, updated_at = ? WHERE investigation_id = ?",
                    (utc_now(), investigation_id),
                )
                published = row_dict(connection.execute(
                    "SELECT * FROM brief_versions WHERE brief_version_id = ?", (brief_version_id,)
                ).fetchone())
                revision = int(connection.execute(
                    "SELECT domain_revision FROM investigations WHERE investigation_id = ?", (investigation_id,)
                ).fetchone()["domain_revision"])
            response = {"brief_version": published, "domain_revision": revision}
            save_command(self, command_id=command, investigation_id=investigation_id,
                         operation="lab.publish_brief", request_sha256=request_hash, response=response)
        return response

    def _validate_orchestrator_brief(
        self: OrchestratorStoreContract, investigation: Mapping[str, object], brief: JsonObject
    ) -> None:
        validate_private_payload(brief)
        required_text(brief.get("title"), "brief.title", 500)
        required_text(brief.get("summary"), "brief.summary", 10_000)
        if brief.get("clinical_boundary") != BRIEF_CLINICAL_BOUNDARY:
            raise ValueError("brief must preserve the informational clinical boundary")
        claims = brief.get("claims")
        if not isinstance(claims, list) or not claims:
            raise ValueError("brief.claims must be a non-empty array")
        evidence_ids: set[str] = set()
        fact_ids: set[str] = set()
        for claim in claims:
            if not isinstance(claim, Mapping):
                raise ValueError("every brief claim must be an object")
            required_text(claim.get("statement"), "brief claim statement", 8_000)
            for field, target in (("evidence_record_ids", evidence_ids), ("profile_revision_ids", fact_ids)):
                values = claim.get(field) or []
                if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
                    raise ValueError(f"brief claim {field} must be an array of identifiers")
                target.update(values)
            if not (claim.get("evidence_record_ids") or claim.get("profile_revision_ids")):
                raise ValueError("every brief claim must cite captured evidence or approved patient facts")
        with self._connect() as connection:
            if evidence_ids:
                placeholders = ",".join("?" for _ in evidence_ids)
                found = connection.execute(
                    f"SELECT evidence_record_id FROM evidence_records WHERE investigation_id = ? AND evidence_record_id IN ({placeholders})",
                    (investigation["investigation_id"], *sorted(evidence_ids)),
                ).fetchall()
                if {str(row["evidence_record_id"]) for row in found} != evidence_ids:
                    raise ValueError("brief cites evidence outside this investigation")
            if fact_ids:
                snapshot_id = investigation.get("patient_molecular_snapshot_id")
                if not snapshot_id:
                    raise ValueError("brief patient facts require an approved profile snapshot")
                snapshot = connection.execute(
                    "SELECT observation_revision_ids_json FROM profile_snapshots WHERE patient_molecular_snapshot_id = ?",
                    (snapshot_id,),
                ).fetchone()
                allowed = set(json.loads(str(snapshot["observation_revision_ids_json"]))) if snapshot else set()
                if not fact_ids.issubset(allowed):
                    raise ValueError("brief cites facts outside the current approved profile snapshot")
            for identifier in brief.get("hypothesis_ids") or []:
                if not isinstance(identifier, str):
                    raise ValueError("brief hypothesis_ids must be strings")
                exists = connection.execute(
                    "SELECT 1 FROM orchestrator_hypothesis_threads AS thread LEFT JOIN orchestrator_hypothesis_versions AS version "
                    "ON version.logical_hypothesis_id = thread.logical_hypothesis_id "
                    "WHERE thread.investigation_id = ? AND (thread.logical_hypothesis_id = ? OR version.hypothesis_version_id = ?)",
                    (investigation["investigation_id"], identifier, identifier),
                ).fetchone()
                if exists is None:
                    raise ValueError("brief cites an unknown hypothesis")

    def read_orchestrator_investigation(
        self: OrchestratorStoreContract, investigation_id: str, *, include_history: bool = False
    ) -> JsonObject:
        if not isinstance(include_history, bool):
            raise ValueError("include_history must be a boolean")
        with self._connect() as connection:
            investigation_row = connection.execute(
                "SELECT * FROM investigations WHERE investigation_id = ?", (investigation_id,)
            ).fetchone()
            if investigation_row is None:
                raise KeyError(investigation_id)
            context_row = connection.execute(
                "SELECT * FROM orchestrator_investigation_contexts WHERE investigation_id = ?", (investigation_id,)
            ).fetchone()
            cycles = connection.execute(
                "SELECT * FROM investigation_cycles WHERE investigation_id = ? ORDER BY ordinal", (investigation_id,)
            ).fetchall()
            hypotheses = connection.execute(
                "SELECT version.* FROM orchestrator_hypothesis_versions AS version "
                "WHERE version.investigation_id = ? "
                + ("ORDER BY version.created_at" if include_history else
                   "AND version.version = (SELECT MAX(latest.version) FROM orchestrator_hypothesis_versions AS latest WHERE latest.logical_hypothesis_id = version.logical_hypothesis_id) ORDER BY version.created_at"),
                (investigation_id,),
            ).fetchall()
            assignments = connection.execute(
                "SELECT * FROM specialist_assignments WHERE investigation_id = ? ORDER BY created_at", (investigation_id,)
            ).fetchall()
            briefs = connection.execute(
                "SELECT * FROM brief_versions WHERE investigation_id = ? "
                + ("ORDER BY version" if include_history else "ORDER BY version DESC LIMIT 1"),
                (investigation_id,),
            ).fetchall()
            snapshots = connection.execute(
                "SELECT * FROM evidence_snapshots WHERE investigation_id = ? "
                + ("ORDER BY version" if include_history else "ORDER BY version DESC LIMIT 1"),
                (investigation_id,),
            ).fetchall()
        return {
            "investigation": row_dict(investigation_row),
            "context": row_dict(context_row) if context_row is not None else None,
            "cycles": [row_dict(row) for row in cycles],
            "hypothesis_versions": [row_dict(row) for row in hypotheses],
            "specialist_assignments": [row_dict(row) for row in assignments],
            "evidence_snapshots": [row_dict(row) for row in snapshots],
            "brief_versions": [row_dict(row) for row in briefs],
        }


__all__ = ["OrchestratorBriefStoreMixin"]
