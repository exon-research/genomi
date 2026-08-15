"""Main-Orchestrator-owned immutable hypothesis threads."""

from __future__ import annotations

import json
import uuid

from .models import JsonObject, compact_json, optional_text, required_text, row_dict, utc_now
from .orchestrator_support import (
    OrchestratorStoreContract,
    advance_investigation_revision,
    command_replay,
    require_cycle,
    require_investigation_revision,
    save_command,
    unique_ids,
)


_STATUSES = frozenset({"open", "strengthened", "weakened", "retained", "rejected", "resolved"})


class OrchestratorHypothesisStoreMixin:
    def create_hypothesis(
        self: OrchestratorStoreContract,
        investigation_id: str,
        *, cycle_id: object, statement: object, status: object,
        profile_snapshot_id: object, evidence_snapshot_id: object,
        supporting_evidence_record_ids: object, contradicting_evidence_record_ids: object,
        contextual_evidence_record_ids: object, unresolved_gaps: object,
        revision_rationale: object, command_id: object, expected_revision: object,
        parent_hypothesis_id: object = None, category: object = None,
    ) -> JsonObject:
        if status != "open":
            raise ValueError("a new hypothesis must have status=open")
        logical_id = f"logical-hypothesis-{uuid.uuid4().hex}"
        return self._write_orchestrator_hypothesis(
            investigation_id, logical_hypothesis_id=logical_id, create_thread=True,
            cycle_id=cycle_id, statement=statement, status=status,
            profile_snapshot_id=profile_snapshot_id, evidence_snapshot_id=evidence_snapshot_id,
            supporting_evidence_record_ids=supporting_evidence_record_ids,
            contradicting_evidence_record_ids=contradicting_evidence_record_ids,
            contextual_evidence_record_ids=contextual_evidence_record_ids,
            unresolved_gaps=unresolved_gaps, revision_rationale=revision_rationale,
            command_id=command_id, expected_revision=expected_revision,
            parent_hypothesis_id=parent_hypothesis_id, category=category,
            operation="lab.create_hypothesis",
        )

    def revise_hypothesis(
        self: OrchestratorStoreContract,
        investigation_id: str,
        *, logical_hypothesis_id: object, cycle_id: object, statement: object, status: object,
        profile_snapshot_id: object, evidence_snapshot_id: object,
        supporting_evidence_record_ids: object, contradicting_evidence_record_ids: object,
        contextual_evidence_record_ids: object, unresolved_gaps: object,
        revision_rationale: object, command_id: object, expected_revision: object,
        parent_hypothesis_id: object = None, category: object = None,
    ) -> JsonObject:
        logical_id = required_text(logical_hypothesis_id, "logical_hypothesis_id", 300)
        return self._write_orchestrator_hypothesis(
            investigation_id, logical_hypothesis_id=logical_id, create_thread=False,
            cycle_id=cycle_id, statement=statement, status=status,
            profile_snapshot_id=profile_snapshot_id, evidence_snapshot_id=evidence_snapshot_id,
            supporting_evidence_record_ids=supporting_evidence_record_ids,
            contradicting_evidence_record_ids=contradicting_evidence_record_ids,
            contextual_evidence_record_ids=contextual_evidence_record_ids,
            unresolved_gaps=unresolved_gaps, revision_rationale=revision_rationale,
            command_id=command_id, expected_revision=expected_revision,
            parent_hypothesis_id=parent_hypothesis_id, category=category,
            operation="lab.revise_hypothesis",
        )

    def _write_orchestrator_hypothesis(
        self: OrchestratorStoreContract,
        investigation_id: str,
        *, logical_hypothesis_id: str, create_thread: bool, cycle_id: object,
        statement: object, status: object, profile_snapshot_id: object,
        evidence_snapshot_id: object, supporting_evidence_record_ids: object,
        contradicting_evidence_record_ids: object, contextual_evidence_record_ids: object,
        unresolved_gaps: object, revision_rationale: object, command_id: object,
        expected_revision: object, parent_hypothesis_id: object, category: object,
        operation: str,
    ) -> JsonObject:
        statement_value = required_text(statement, "statement", 8_000)
        status_value = required_text(status, "status", 80)
        if status_value not in _STATUSES:
            raise ValueError("unsupported hypothesis status")
        profile_id = optional_text(profile_snapshot_id, "profile_snapshot_id", 300)
        evidence_snapshot = optional_text(evidence_snapshot_id, "evidence_snapshot_id", 300)
        supporting = unique_ids(supporting_evidence_record_ids, "supporting_evidence_record_ids")
        contradicting = unique_ids(contradicting_evidence_record_ids, "contradicting_evidence_record_ids")
        contextual = unique_ids(contextual_evidence_record_ids, "contextual_evidence_record_ids")
        if set(supporting) & set(contradicting) or set(supporting) & set(contextual) or set(contradicting) & set(contextual):
            raise ValueError("an evidence record may have only one hypothesis role")
        gaps = unique_ids(unresolved_gaps, "unresolved_gaps")
        rationale = required_text(revision_rationale, "revision_rationale", 4_000)
        parent_id = optional_text(parent_hypothesis_id, "parent_hypothesis_id", 300)
        category_value = optional_text(category, "category", 300)
        request = {
            "logical_hypothesis_id": logical_hypothesis_id, "cycle_id": cycle_id,
            "statement": statement_value, "status": status_value,
            "profile_snapshot_id": profile_id, "evidence_snapshot_id": evidence_snapshot,
            "supporting_evidence_record_ids": supporting,
            "contradicting_evidence_record_ids": contradicting,
            "contextual_evidence_record_ids": contextual, "unresolved_gaps": gaps,
            "revision_rationale": rationale, "parent_hypothesis_id": parent_id,
            "category": category_value, "expected_revision": expected_revision,
        }
        command, request_hash, replay = command_replay(
            self, investigation_id=investigation_id, operation=operation,
            command_id=command_id, request=request,
        )
        if replay is not None:
            return replay
        with self.atomic_write():
            investigation = require_investigation_revision(self, investigation_id, expected_revision)
            cycle = require_cycle(self, investigation_id, cycle_id)
            if profile_id != investigation.get("patient_molecular_snapshot_id"):
                raise ValueError("profile_snapshot_id must be the investigation's current snapshot")
            if evidence_snapshot != investigation.get("evidence_snapshot_id"):
                raise ValueError("evidence_snapshot_id must be the investigation's current evidence snapshot")
            all_evidence = supporting + contradicting + contextual
            patient_fact_ids: list[str] = []
            with self._connect() as connection:
                if profile_id:
                    snapshot = connection.execute(
                        "SELECT observation_revision_ids_json FROM profile_snapshots WHERE patient_molecular_snapshot_id = ?",
                        (profile_id,),
                    ).fetchone()
                    if snapshot is None:
                        raise ValueError("profile snapshot not found")
                    patient_fact_ids = list(json.loads(str(snapshot["observation_revision_ids_json"])))
                if evidence_snapshot:
                    snapshot = connection.execute(
                        "SELECT evidence_record_ids_json FROM evidence_snapshots WHERE evidence_snapshot_id = ? AND investigation_id = ?",
                        (evidence_snapshot, investigation_id),
                    ).fetchone()
                    if snapshot is None:
                        raise ValueError("evidence snapshot not found")
                    allowed = set(json.loads(str(snapshot["evidence_record_ids_json"])))
                    if not set(all_evidence).issubset(allowed):
                        raise ValueError("hypothesis evidence must belong to the selected evidence snapshot")
                elif all_evidence:
                    raise ValueError("hypothesis evidence requires an evidence snapshot")
                if create_thread:
                    if parent_id:
                        parent = connection.execute(
                            "SELECT 1 FROM orchestrator_hypothesis_threads WHERE logical_hypothesis_id = ? AND investigation_id = ?",
                            (parent_id, investigation_id),
                        ).fetchone()
                        if parent is None:
                            raise ValueError("parent hypothesis belongs to another investigation")
                    connection.execute(
                        "INSERT INTO orchestrator_hypothesis_threads(logical_hypothesis_id, investigation_id, parent_logical_hypothesis_id, category, created_at) VALUES (?, ?, ?, ?, ?)",
                        (logical_hypothesis_id, investigation_id, parent_id, category_value, utc_now()),
                    )
                    prior = None
                    version = 1
                else:
                    thread = connection.execute(
                        "SELECT * FROM orchestrator_hypothesis_threads WHERE logical_hypothesis_id = ? AND investigation_id = ?",
                        (logical_hypothesis_id, investigation_id),
                    ).fetchone()
                    if thread is None:
                        raise ValueError("logical hypothesis not found")
                    prior = connection.execute(
                        "SELECT * FROM orchestrator_hypothesis_versions WHERE logical_hypothesis_id = ? ORDER BY version DESC LIMIT 1",
                        (logical_hypothesis_id,),
                    ).fetchone()
                    if prior is None:
                        raise ValueError("logical hypothesis has no current version")
                    version = int(prior["version"]) + 1
                version_id = f"hypothesis-version-{uuid.uuid4().hex}"
                assessment = None
                if prior is not None and status_value != prior["status"]:
                    prior_facts = set(json.loads(str(prior["patient_fact_ids_json"])))
                    prior_evidence = set(json.loads(str(prior["supporting_evidence_record_ids_json"])))
                    prior_evidence.update(json.loads(str(prior["contradicting_evidence_record_ids_json"])))
                    prior_evidence.update(json.loads(str(prior["contextual_evidence_record_ids_json"])))
                    newly_assessed_facts = sorted(set(patient_fact_ids) - prior_facts)
                    newly_assessed_evidence = sorted(set(all_evidence) - prior_evidence)
                    if not newly_assessed_facts and not newly_assessed_evidence:
                        raise ValueError("a status change requires newly assessed patient facts or captured evidence")
                    if newly_assessed_evidence:
                        placeholders = ",".join("?" for _ in newly_assessed_evidence)
                        model_rows = connection.execute(
                            f"SELECT source_family FROM evidence_records WHERE evidence_record_id IN ({placeholders})",
                            tuple(newly_assessed_evidence),
                        ).fetchall()
                        if any(str(item["source_family"]).lower() in {"model", "computational_model", "esm", "biohub-esm", "proto", "specialist"} for item in model_rows):
                            raise ValueError("model or specialist output cannot independently change patient hypothesis status")
                    assessment = {
                        "new_patient_fact_ids": newly_assessed_facts,
                        "new_evidence_record_ids": newly_assessed_evidence,
                    }
                connection.execute(
                    "INSERT INTO orchestrator_hypothesis_versions(hypothesis_version_id, logical_hypothesis_id, investigation_id, cycle_id, "
                    "patient_molecular_snapshot_id, evidence_snapshot_id, supersedes_hypothesis_version_id, version, statement, status, "
                    "patient_fact_ids_json, supporting_evidence_record_ids_json, contradicting_evidence_record_ids_json, "
                    "contextual_evidence_record_ids_json, unresolved_gaps_json, revision_rationale, patient_specific_assessment_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (version_id, logical_hypothesis_id, investigation_id, cycle["cycle_id"], profile_id, evidence_snapshot,
                     prior["hypothesis_version_id"] if prior is not None else None, version, statement_value, status_value,
                     compact_json(patient_fact_ids), compact_json(supporting), compact_json(contradicting), compact_json(contextual),
                     compact_json(gaps), rationale, compact_json(assessment) if assessment is not None else None, utc_now()),
                )
                row = connection.execute("SELECT * FROM orchestrator_hypothesis_versions WHERE hypothesis_version_id = ?", (version_id,)).fetchone()
            revision = advance_investigation_revision(self, investigation_id)
            response = {"hypothesis_version": row_dict(row), "domain_revision": revision}
            save_command(self, command_id=command, investigation_id=investigation_id, operation=operation, request_sha256=request_hash, response=response)
        return response


__all__ = ["OrchestratorHypothesisStoreMixin"]
