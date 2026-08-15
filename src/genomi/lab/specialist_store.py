"""De-identified specialist briefs and assignment lifecycle persistence."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping

from .models import JsonObject, compact_json, required_text, row_dict, utc_now
from .orchestrator_support import (
    OrchestratorStoreContract,
    advance_investigation_revision,
    command_replay,
    json_sha256,
    require_current_snapshot_facts,
    require_cycle,
    require_investigation_revision,
    save_command,
    unique_ids,
)
from .specialist_policies import (
    EXPECTED_CONNECTORS,
    policy_manifest,
    policy_manifest_sha256,
)
from .specialist_validation import (
    build_outbound_specialist_brief,
    validate_specialist_brief,
)


_TRANSITIONS = {
    "proposed": frozenset({"spawned", "cancelled"}),
    "spawned": frozenset({"completed", "failed", "cancelled"}),
}
_PRIVATE_SOURCE_FAMILIES = frozenset(
    {"personal_genome", "patient_record", "patient_profile", "model", "computational_model"}
)


class SpecialistStoreMixin:
    def prepare_specialist_brief(
        self: OrchestratorStoreContract,
        investigation_id: str,
        *,
        cycle_id: object,
        specialist_role: object,
        execution_policy: object,
        research_question: object,
        public_concepts: object,
        abstract_relations: object,
        public_evidence_record_ids: object,
        source_fact_ids: object,
        rationale: object,
        purpose: object,
        workspace_session_id: object,
        command_id: object,
        expected_revision: object,
    ) -> JsonObject:
        policy_id = required_text(execution_policy, "execution_policy", 100)
        if policy_id not in EXPECTED_CONNECTORS:
            raise ValueError("unsupported specialist execution policy")
        role = required_text(specialist_role, "specialist_role", 300)
        question = required_text(research_question, "research_question", 4_000)
        rationale_value = required_text(rationale, "rationale", 4_000)
        purpose_value = required_text(purpose, "purpose", 2_000)
        session = required_text(workspace_session_id, "workspace_session_id", 300)
        fact_ids = unique_ids(source_fact_ids, "source_fact_ids")
        evidence_ids = unique_ids(
            public_evidence_record_ids, "public_evidence_record_ids"
        )
        request = {
            "cycle_id": cycle_id,
            "specialist_role": role,
            "execution_policy": policy_id,
            "research_question": question,
            "public_concepts": public_concepts,
            "abstract_relations": abstract_relations,
            "public_evidence_record_ids": evidence_ids,
            "source_fact_ids": fact_ids,
            "rationale": rationale_value,
            "purpose": purpose_value,
            "workspace_session_id": session,
            "expected_revision": expected_revision,
        }
        command, request_hash, replay = command_replay(
            self,
            investigation_id=investigation_id,
            operation="lab.prepare_specialist_brief",
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
            require_current_snapshot_facts(self, investigation, fact_ids)
            public_evidence = self._specialist_public_evidence(
                investigation_id, evidence_ids
            )
            forbidden = self._specialist_forbidden_texts(investigation, fact_ids)
            outbound = build_outbound_specialist_brief(
                specialist_role=role,
                execution_policy=policy_id,
                research_question=question,
                public_concepts=public_concepts,
                abstract_relations=abstract_relations,
                public_evidence=public_evidence,
            )
            profile = next(
                item
                for item in policy_manifest()["profiles"]
                if item["id"] == policy_id
            )
            validate_specialist_brief(outbound, policy=profile, forbidden_texts=forbidden)
            payload_hash = json_sha256(outbound)
            derivation_id = f"specialist-brief-derivation-{uuid.uuid4().hex}"
            brief_id = f"specialist-brief-{uuid.uuid4().hex}"
            disclosure_id = f"disclosure-{uuid.uuid4().hex}"
            now = utc_now()
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO outbound_disclosure_receipts(disclosure_receipt_id, "
                    "workspace_session_id, user_id, investigation_id, recipient_kind, recipient_id, "
                    "purpose, destination, data_categories_json, payload_json, payload_sha256, "
                    "policy_identity_json, approved_at) VALUES (?, ?, ?, ?, 'specialist', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        disclosure_id,
                        session,
                        investigation["user_id"],
                        investigation_id,
                        role,
                        purpose_value,
                        f"native_specialist:{policy_id}",
                        compact_json(["deidentified_public_research_brief"]),
                        compact_json(outbound),
                        payload_hash,
                        compact_json({
                            "specialist_policy": profile.get("id"),
                            "policy_sha256": policy_manifest_sha256(),
                        }),
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO specialist_brief_derivations(specialist_brief_derivation_id, "
                    "investigation_id, cycle_id, execution_policy, source_fact_ids_json, "
                    "public_evidence_record_ids_json, patient_molecular_snapshot_id, consent_receipt_id, "
                    "rationale, purpose, outbound_payload_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        derivation_id,
                        investigation_id,
                        cycle["cycle_id"],
                        policy_id,
                        compact_json(fact_ids),
                        compact_json(evidence_ids),
                        investigation.get("patient_molecular_snapshot_id"),
                        investigation.get("active_consent_receipt_id"),
                        rationale_value,
                        purpose_value,
                        payload_hash,
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO specialist_briefs(specialist_brief_id, specialist_brief_derivation_id, "
                    "execution_policy, policy_sha256, outbound_payload_json, outbound_payload_sha256, "
                    "disclosure_receipt_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (brief_id, derivation_id, policy_id, policy_manifest_sha256(), compact_json(outbound), payload_hash, disclosure_id, now),
                )
            revision = advance_investigation_revision(self, investigation_id)
            response = {
                "specialist_brief_id": brief_id,
                "internal_derivation": {
                    "specialist_brief_derivation_id": derivation_id,
                    "investigation_id": investigation_id,
                    "cycle_id": cycle["cycle_id"],
                    "source_fact_ids": fact_ids,
                    "outbound_payload_sha256": payload_hash,
                },
                "outbound_brief": outbound,
                "disclosure_receipt_id": disclosure_id,
                "domain_revision": revision,
            }
            save_command(
                self,
                command_id=command,
                investigation_id=investigation_id,
                operation="lab.prepare_specialist_brief",
                request_sha256=request_hash,
                response=response,
            )
        return response

    def create_specialist_assignment(
        self: OrchestratorStoreContract,
        investigation_id: str,
        *,
        cycle_id: object,
        specialist_brief_id: object,
        command_id: object,
        expected_revision: object,
    ) -> JsonObject:
        brief_id = required_text(specialist_brief_id, "specialist_brief_id", 300)
        request = {"cycle_id": cycle_id, "specialist_brief_id": brief_id, "expected_revision": expected_revision}
        command, request_hash, replay = command_replay(
            self, investigation_id=investigation_id,
            operation="lab.create_specialist_assignment", command_id=command_id, request=request
        )
        if replay is not None:
            return replay
        with self.atomic_write():
            require_investigation_revision(self, investigation_id, expected_revision)
            cycle = require_cycle(self, investigation_id, cycle_id)
            with self._connect() as connection:
                brief = connection.execute(
                    "SELECT brief.*, derivation.investigation_id, derivation.cycle_id "
                    "FROM specialist_briefs AS brief JOIN specialist_brief_derivations AS derivation "
                    "ON derivation.specialist_brief_derivation_id = brief.specialist_brief_derivation_id "
                    "WHERE brief.specialist_brief_id = ?",
                    (brief_id,),
                ).fetchone()
                if brief is None or str(brief["investigation_id"]) != investigation_id or str(brief["cycle_id"]) != cycle["cycle_id"]:
                    raise ValueError("specialist_brief_id must belong to this cycle")
                outbound = json.loads(str(brief["outbound_payload_json"]))
                assignment_id = f"specialist-assignment-{uuid.uuid4().hex}"
                now = utc_now()
                connection.execute(
                    "INSERT INTO specialist_assignments(specialist_assignment_id, investigation_id, cycle_id, "
                    "specialist_brief_id, specialist_role, execution_policy, state, revision, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'proposed', 1, ?, ?)",
                    (assignment_id, investigation_id, cycle["cycle_id"], brief_id, outbound["specialist_role"], brief["execution_policy"], now, now),
                )
                connection.execute(
                    "INSERT INTO specialist_assignment_events(specialist_assignment_event_id, specialist_assignment_id, "
                    "from_state, to_state, assignment_revision, created_at) VALUES (?, ?, NULL, 'proposed', 1, ?)",
                    (f"specialist-assignment-event-{uuid.uuid4().hex}", assignment_id, now),
                )
                assignment = row_dict(connection.execute("SELECT * FROM specialist_assignments WHERE specialist_assignment_id = ?", (assignment_id,)).fetchone())
            revision = advance_investigation_revision(self, investigation_id)
            response = {"assignment": assignment, "domain_revision": revision}
            save_command(self, command_id=command, investigation_id=investigation_id, operation="lab.create_specialist_assignment", request_sha256=request_hash, response=response)
        return response

    def transition_specialist_assignment(
        self: OrchestratorStoreContract,
        investigation_id: str,
        *,
        specialist_assignment_id: object,
        to_state: object,
        assignment_expected_revision: object,
        command_id: object,
        expected_revision: object,
        native_agent_id: object = None,
        reason: object = None,
        analysis: object = None,
    ) -> JsonObject:
        assignment_id = required_text(specialist_assignment_id, "specialist_assignment_id", 300)
        target = required_text(to_state, "to_state", 80)
        request = {
            "specialist_assignment_id": assignment_id, "to_state": target,
            "assignment_expected_revision": assignment_expected_revision,
            "expected_revision": expected_revision, "native_agent_id": native_agent_id,
            "reason": reason, "analysis": analysis,
        }
        command, request_hash, replay = command_replay(
            self, investigation_id=investigation_id,
            operation="lab.transition_specialist_assignment", command_id=command_id, request=request
        )
        if replay is not None:
            return replay
        with self.atomic_write():
            require_investigation_revision(self, investigation_id, expected_revision)
            with self._connect() as connection:
                row = connection.execute("SELECT * FROM specialist_assignments WHERE specialist_assignment_id = ? AND investigation_id = ?", (assignment_id, investigation_id)).fetchone()
                if row is None:
                    raise ValueError("specialist assignment not found")
                current = str(row["state"])
                if target not in _TRANSITIONS.get(current, frozenset()):
                    raise ValueError(f"invalid specialist assignment transition: {current} -> {target}")
                if int(row["revision"]) != int(assignment_expected_revision):
                    raise ValueError("specialist assignment revision conflict")
                if target == "spawned" and not native_agent_id:
                    raise ValueError("spawned assignments require native_agent_id")
                analysis_id = None
                if target == "completed":
                    if not isinstance(analysis, Mapping):
                        raise ValueError("completed assignments require a general specialist analysis")
                    analysis_id = f"specialist-analysis-{uuid.uuid4().hex}"
                    connection.execute(
                        "INSERT INTO specialist_analyses(specialist_analysis_id, specialist_assignment_id, "
                        "general_analysis_json, uncertainty_json, alternatives_json, gaps_json, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            analysis_id, assignment_id,
                            compact_json(dict(analysis)),
                            compact_json(analysis.get("uncertainty") or []),
                            compact_json(analysis.get("alternatives") or []),
                            compact_json(analysis.get("gaps") or []), utc_now(),
                        ),
                    )
                next_revision = int(row["revision"]) + 1
                now = utc_now()
                connection.execute(
                    "UPDATE specialist_assignments SET state = ?, native_agent_id = COALESCE(?, native_agent_id), "
                    "specialist_analysis_id = ?, revision = ?, updated_at = ? "
                    "WHERE specialist_assignment_id = ?",
                    (target, native_agent_id, analysis_id, next_revision, now, assignment_id),
                )
                connection.execute(
                    "INSERT INTO specialist_assignment_events(specialist_assignment_event_id, specialist_assignment_id, "
                    "from_state, to_state, assignment_revision, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (f"specialist-assignment-event-{uuid.uuid4().hex}", assignment_id, current, target, next_revision, reason, now),
                )
                assignment = row_dict(connection.execute("SELECT * FROM specialist_assignments WHERE specialist_assignment_id = ?", (assignment_id,)).fetchone())
                specialist_analysis = row_dict(connection.execute("SELECT * FROM specialist_analyses WHERE specialist_analysis_id = ?", (analysis_id,)).fetchone()) if analysis_id else None
            revision = advance_investigation_revision(self, investigation_id)
            response = {"assignment": assignment, "specialist_analysis": specialist_analysis, "domain_revision": revision}
            save_command(self, command_id=command, investigation_id=investigation_id, operation="lab.transition_specialist_assignment", request_sha256=request_hash, response=response)
        return response

    def _specialist_public_evidence(self: OrchestratorStoreContract, investigation_id: str, evidence_ids: list[str]) -> list[JsonObject]:
        if not evidence_ids:
            return []
        placeholders = ",".join("?" for _ in evidence_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM evidence_records WHERE investigation_id = ? AND evidence_record_id IN ({placeholders})",
                (investigation_id, *evidence_ids),
            ).fetchall()
        by_id = {str(row["evidence_record_id"]): row_dict(row) for row in rows}
        if set(by_id) != set(evidence_ids):
            raise ValueError("public evidence records must belong to this investigation")
        projected = []
        for identifier in evidence_ids:
            record = by_id[identifier]
            if str(record.get("source_family") or "").lower() in _PRIVATE_SOURCE_FAMILIES:
                raise ValueError("specialist briefs may cite only public evidence records")
            evidence = record.get("evidence") or {}
            candidates = evidence.get("records") if isinstance(evidence, dict) else None
            if not isinstance(candidates, list):
                candidates = []
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                projection = {key: item[key] for key in ("source", "title", "uri", "summary", "doi", "pmid", "accession") if item.get(key)}
                if projection:
                    projected.append(projection)
            if not candidates:
                projected.append({"source": record["source_family"], "title": record["operation"]})
        return projected

    def _specialist_forbidden_texts(self: OrchestratorStoreContract, investigation: Mapping[str, object], fact_ids: list[str]) -> list[str]:
        forbidden = [str(investigation.get("user_id") or ""), str(investigation.get("question") or "")]
        with self._connect() as connection:
            workspace = connection.execute("SELECT display_name FROM workspaces WHERE user_id = ?", (investigation["user_id"],)).fetchone()
            if workspace and workspace["display_name"]:
                forbidden.append(str(workspace["display_name"]))
            if fact_ids:
                placeholders = ",".join("?" for _ in fact_ids)
                rows = connection.execute(
                    f"SELECT original_wording, label, source_identifier, source_locator FROM molecular_observations WHERE observation_revision_id IN ({placeholders})",
                    tuple(fact_ids),
                ).fetchall()
                for row in rows:
                    forbidden.extend(str(row[key] or "") for key in row.keys())
        forbidden.extend(fact_ids)
        return [item for item in forbidden if item]


__all__ = ["SpecialistStoreMixin"]
