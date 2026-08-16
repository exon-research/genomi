"""Main-Orchestrator-owned immutable information-gap threads."""

from __future__ import annotations

import re
import uuid

from .informational_narrative import validate_informational_narrative
from .models import JsonObject, required_text, row_dict, utc_now
from .orchestrator_support import (
    OrchestratorStoreContract,
    advance_investigation_revision,
    command_replay,
    require_cycle,
    require_investigation_revision,
    save_command,
)


_STATUSES = frozenset({"open", "resolved"})
_INFORMATION_GAP_FORM = re.compile(
    r"(?:^\s*(?:whether|what|which|how|when|where|why|who)\b|"
    r"\b(?:unknown|unavailable|missing|unresolved|uncertain|unclear|"
    r"not\s+(?:documented|reviewed|measured|tested|confirmed|known)|"
    r"remains?\s+to\s+be\s+(?:determined|clarified|confirmed|measured|tested|"
    r"reviewed|established))\b)",
    re.IGNORECASE,
)


class InformationGapStoreMixin:
    def create_information_gap(
        self: OrchestratorStoreContract,
        investigation_id: str,
        *,
        cycle_id: object,
        statement: object,
        status: object,
        revision_rationale: object,
        command_id: object,
        expected_revision: object,
    ) -> JsonObject:
        if status != "open":
            raise ValueError("a new information gap must have status=open")
        return self._write_information_gap(
            investigation_id,
            logical_information_gap_id=f"logical-information-gap-{uuid.uuid4().hex}",
            create_thread=True,
            cycle_id=cycle_id,
            statement=statement,
            status=status,
            revision_rationale=revision_rationale,
            command_id=command_id,
            expected_revision=expected_revision,
            operation="lab.create_information_gap",
        )

    def revise_information_gap(
        self: OrchestratorStoreContract,
        investigation_id: str,
        *,
        logical_information_gap_id: object,
        cycle_id: object,
        statement: object,
        status: object,
        revision_rationale: object,
        command_id: object,
        expected_revision: object,
    ) -> JsonObject:
        return self._write_information_gap(
            investigation_id,
            logical_information_gap_id=required_text(
                logical_information_gap_id, "logical_information_gap_id", 300
            ),
            create_thread=False,
            cycle_id=cycle_id,
            statement=statement,
            status=status,
            revision_rationale=revision_rationale,
            command_id=command_id,
            expected_revision=expected_revision,
            operation="lab.revise_information_gap",
        )

    def _write_information_gap(
        self: OrchestratorStoreContract,
        investigation_id: str,
        *,
        logical_information_gap_id: str,
        create_thread: bool,
        cycle_id: object,
        statement: object,
        status: object,
        revision_rationale: object,
        command_id: object,
        expected_revision: object,
        operation: str,
    ) -> JsonObject:
        statement_value = validate_informational_narrative(
            statement, "information gap statement", kind="hypothesis_gap"
        )
        if not _INFORMATION_GAP_FORM.search(statement_value):
            raise ValueError(
                "information gap statement must describe missing or unresolved information"
            )
        status_value = required_text(status, "status", 80)
        if status_value not in _STATUSES:
            raise ValueError("unsupported information gap status")
        rationale = required_text(revision_rationale, "revision_rationale", 4_000)
        request = {
            "logical_information_gap_id": logical_information_gap_id,
            "cycle_id": cycle_id,
            "statement": statement_value,
            "status": status_value,
            "revision_rationale": rationale,
            "expected_revision": expected_revision,
        }
        command, request_hash, replay = command_replay(
            self,
            investigation_id=investigation_id,
            operation=operation,
            command_id=command_id,
            request=request,
        )
        if replay is not None:
            return replay
        with self.atomic_write():
            investigation = require_investigation_revision(
                self, investigation_id, expected_revision
            )
            cycle = require_cycle(self, investigation_id, cycle_id)
            profile_snapshot_id = investigation.get("patient_molecular_snapshot_id")
            evidence_snapshot_id = investigation.get("evidence_snapshot_id")
            with self._connect() as connection:
                latest_cycle = connection.execute(
                    "SELECT cycle_id FROM investigation_cycles "
                    "WHERE investigation_id = ? ORDER BY ordinal DESC LIMIT 1",
                    (investigation_id,),
                ).fetchone()
                if latest_cycle is None or str(latest_cycle["cycle_id"]) != str(
                    cycle["cycle_id"]
                ):
                    raise ValueError(
                        "information gaps must use the current investigation cycle"
                    )
                if cycle.get("patient_molecular_snapshot_id") != profile_snapshot_id:
                    raise ValueError(
                        "information gaps must use the current profile snapshot"
                    )
                if create_thread:
                    connection.execute(
                        "INSERT INTO information_gap_threads("
                        "logical_information_gap_id, investigation_id, created_at) "
                        "VALUES (?, ?, ?)",
                        (logical_information_gap_id, investigation_id, utc_now()),
                    )
                    prior = None
                    version = 1
                else:
                    prior = connection.execute(
                        "SELECT version.* FROM information_gap_threads AS thread "
                        "JOIN information_gap_versions AS version "
                        "ON version.logical_information_gap_id = "
                        "thread.logical_information_gap_id "
                        "WHERE thread.logical_information_gap_id = ? "
                        "AND thread.investigation_id = ? "
                        "ORDER BY version.version DESC LIMIT 1",
                        (logical_information_gap_id, investigation_id),
                    ).fetchone()
                    if prior is None:
                        raise ValueError("logical information gap not found")
                    if status_value != prior["status"] and (
                        prior["patient_molecular_snapshot_id"] == profile_snapshot_id
                        and prior["evidence_snapshot_id"] == evidence_snapshot_id
                    ):
                        raise ValueError(
                            "an information gap status change requires a new current "
                            "profile or evidence snapshot"
                        )
                    version = int(prior["version"]) + 1
                version_id = f"information-gap-version-{uuid.uuid4().hex}"
                connection.execute(
                    "INSERT INTO information_gap_versions("
                    "information_gap_version_id, logical_information_gap_id, "
                    "investigation_id, cycle_id, patient_molecular_snapshot_id, "
                    "evidence_snapshot_id, supersedes_information_gap_version_id, "
                    "version, statement, status, revision_rationale, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        version_id,
                        logical_information_gap_id,
                        investigation_id,
                        cycle["cycle_id"],
                        profile_snapshot_id,
                        evidence_snapshot_id,
                        prior["information_gap_version_id"] if prior is not None else None,
                        version,
                        statement_value,
                        status_value,
                        rationale,
                        utc_now(),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM information_gap_versions "
                    "WHERE information_gap_version_id = ?",
                    (version_id,),
                ).fetchone()
            revision = advance_investigation_revision(self, investigation_id)
            response = {
                "information_gap_version": row_dict(row),
                "domain_revision": revision,
            }
            save_command(
                self,
                command_id=command,
                investigation_id=investigation_id,
                operation=operation,
                request_sha256=request_hash,
                response=response,
            )
        return response


__all__ = ["InformationGapStoreMixin"]
