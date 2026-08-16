"""Clinician brief publication and consolidated investigation reads."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from .models import JsonObject, compact_json, row_dict, utc_now
from .orchestrator_brief_validation import validate_orchestrator_brief
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
            cycle = require_cycle(self, investigation_id, cycle_id)
            validate_orchestrator_brief(self, investigation, cycle, brief_value)
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
            information_gaps = connection.execute(
                "SELECT version.* FROM information_gap_versions AS version "
                "WHERE version.investigation_id = ? "
                + (
                    "ORDER BY version.created_at"
                    if include_history
                    else "AND version.version = (SELECT MAX(latest.version) "
                    "FROM information_gap_versions AS latest WHERE "
                    "latest.logical_information_gap_id = "
                    "version.logical_information_gap_id) ORDER BY version.created_at"
                ),
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
            "information_gap_versions": [row_dict(row) for row in information_gaps],
            "specialist_assignments": [row_dict(row) for row in assignments],
            "evidence_snapshots": [row_dict(row) for row in snapshots],
            "brief_versions": [row_dict(row) for row in briefs],
        }


__all__ = ["OrchestratorBriefStoreMixin"]
