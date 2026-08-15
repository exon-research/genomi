"""Minimized specialist packets and reported investigation-panel records."""

from __future__ import annotations

import hashlib
from typing import Any, ContextManager, Protocol

from .investigation_record_support import (
    advance_cycle,
    command_parts,
    command_result,
    require_cycle,
    require_investigation,
)
from .models import (
    JsonObject,
    compact_json,
    optional_text,
    required_text,
    row_dict,
    stable_id,
    utc_now,
    validate_private_payload,
)


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def _require_workspace(self, user_id: str) -> None: ...

    def get_investigation(self, investigation_id: str) -> JsonObject: ...


class InvestigationPanelStoreMixin:
    """Persist work explicitly reported by the main agent, never live telemetry."""

    def prepare_specialist_packet(
        self: _StoreContract,
        user_id: str,
        *,
        workspace_session_id: object,
        investigation_id: object,
        cycle_id: object,
        specialist_role: object,
        projection_kind: object,
        objective: object,
        selected_profile_fact_ids: object,
        selected_evidence_ids: object,
        allowed_provider: object,
        purpose: object,
        command_id: object,
        expected_revision: int,
    ) -> JsonObject:
        self._require_workspace(user_id)
        investigation = required_text(investigation_id, "investigation_id", 200)
        cycle = required_text(cycle_id, "cycle_id", 200)
        role = required_text(specialist_role, "specialist_role", 160)
        projection = required_text(projection_kind, "projection_kind", 100)
        allowed_projections = {
            "public_source_result",
            "main_agent_genomic_summary",
            "clinical_timeline_projection",
            "phenotype_projection",
            "computational_model_input",
            "claim_and_counterevidence_projection",
        }
        if projection not in allowed_projections:
            raise ValueError("unsupported specialist projection_kind")
        objective_value = required_text(objective, "objective", 2000)
        purpose_value = required_text(purpose, "purpose", 1000)
        session = required_text(workspace_session_id, "workspace_session_id", 300)
        provider = required_text(allowed_provider, "allowed_provider", 100)
        if provider not in {"none", "host_native", "demo_fixture"}:
            raise ValueError("allowed_provider is deferred in host-neutral v1")
        fact_ids = _string_ids(selected_profile_fact_ids, "selected_profile_fact_ids")
        evidence_ids = _string_ids(selected_evidence_ids, "selected_evidence_ids")
        payload = {
            "user_id": user_id,
            "investigation_id": investigation,
            "cycle_id": cycle,
            "specialist_role": role,
            "projection_kind": projection,
            "objective": objective_value,
            "selected_profile_fact_ids": fact_ids,
            "selected_evidence_ids": evidence_ids,
            "allowed_provider": provider,
            "purpose": purpose_value,
        }
        validate_private_payload(payload)
        command, fingerprint = command_parts(command_id, payload)
        with self._connect() as connection:
            prior = command_result(
                connection,
                table="specialist_packets",
                command_id=command,
                fingerprint=fingerprint,
            )
            if prior is not None:
                return prior
            target = require_investigation(connection, investigation, user_id)
            require_cycle(
                connection,
                cycle_id=cycle,
                investigation_id=investigation,
                user_id=user_id,
                expected_revision=expected_revision,
            )
            snapshot_id = str(target["patient_molecular_snapshot_id"] or "")
            consent_id = str(target["active_consent_receipt_id"] or "")
            if not snapshot_id or not consent_id:
                raise ValueError(
                    "approved profile access is required before preparing a packet"
                )
            consent = connection.execute(
                "SELECT * FROM consent_receipts WHERE consent_receipt_id = ?",
                (consent_id,),
            ).fetchone()
            if (
                consent is None
                or consent["revoked_at"]
                or str(consent["workspace_session_id"]) != session
                or str(consent["user_id"]) != user_id
                or str(consent["investigation_id"] or "") != investigation
                or str(consent["patient_molecular_snapshot_id"] or "") != snapshot_id
            ):
                raise ValueError(
                    "profile access is not approved for this project/frame session"
                )
            snapshot = connection.execute(
                "SELECT * FROM profile_snapshots WHERE patient_molecular_snapshot_id = ? AND user_id = ?",
                (snapshot_id, user_id),
            ).fetchone()
            if snapshot is None:
                raise ValueError("approved profile snapshot was not found")
            approved_fact_ids = set(
                row_dict(snapshot).get("observation_revision_ids") or []
            )
            if not set(fact_ids).issubset(approved_fact_ids):
                raise ValueError(
                    "selected profile facts must belong to the approved snapshot"
                )
            facts = _selected_facts(connection, user_id, fact_ids)
            evidence = _selected_evidence(connection, investigation, evidence_ids)
            if (
                projection in {"public_source_result", "computational_model_input"}
                and facts
            ):
                raise ValueError(f"{projection} cannot include patient profile facts")
            if projection == "main_agent_genomic_summary":
                _validate_genomic_summary_projection(evidence)
            packet = {
                "specialist_role": role,
                "projection_kind": projection,
                "objective": objective_value,
                "purpose": purpose_value,
                "allowed_provider": provider,
                "profile_facts": facts,
                "evidence_references": evidence,
                "privacy_limits": [
                    "No raw genome or Active Genome Index rows",
                    "No raw reports, storage paths, credentials, or direct identifiers",
                    "Request additional context through the main agent",
                ],
            }
            validate_private_payload(packet)
            packet_id = stable_id("specialist-packet", command)
            receipt_id = stable_id("specialist-disclosure", command)
            packet_hash = hashlib.sha256(
                compact_json(packet).encode("utf-8")
            ).hexdigest()
            now = utc_now()
            connection.execute(
                "INSERT INTO outbound_disclosure_receipts("
                "disclosure_receipt_id, workspace_session_id, user_id, investigation_id, "
                "recipient_kind, recipient_id, purpose, destination, data_categories_json, "
                "payload_json, payload_sha256, policy_versions_json, approved_at) "
                "VALUES (?, ?, ?, ?, 'specialist', ?, ?, 'host_native_specialist', ?, ?, ?, ?, ?)",
                (
                    receipt_id,
                    session,
                    user_id,
                    investigation,
                    role,
                    purpose_value,
                    compact_json([projection]),
                    compact_json(packet),
                    packet_hash,
                    compact_json({"genomilab_packet": "host_neutral_v1"}),
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO specialist_packets("
                "packet_id, investigation_id, cycle_id, user_id, specialist_role, projection_kind, objective, "
                "allowed_provider, purpose, selected_profile_fact_ids_json, "
                "selected_evidence_ids_json, packet_json, payload_sha256, disclosure_receipt_id, "
                "command_id, command_fingerprint, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    packet_id,
                    investigation,
                    cycle,
                    user_id,
                    role,
                    projection,
                    objective_value,
                    provider,
                    purpose_value,
                    compact_json(fact_ids),
                    compact_json(evidence_ids),
                    compact_json(packet),
                    packet_hash,
                    receipt_id,
                    command,
                    fingerprint,
                    now,
                ),
            )
            advance_cycle(connection, cycle)
            row = connection.execute(
                "SELECT * FROM specialist_packets WHERE packet_id = ?", (packet_id,)
            ).fetchone()
        return row_dict(row)

    def record_research_artifact(
        self: _StoreContract,
        user_id: str,
        *,
        investigation_id: object,
        cycle_id: object,
        provider: object,
        artifact_kind: object,
        artifact: object,
        source_evidence_ids: object,
        command_id: object,
        expected_revision: int,
    ) -> JsonObject:
        investigation = required_text(investigation_id, "investigation_id", 200)
        cycle = required_text(cycle_id, "cycle_id", 200)
        provider_value = required_text(provider, "provider", 100)
        if provider_value not in {"biohub-esm", "proto", "genomi-sequence"}:
            raise ValueError("unsupported research artifact provider")
        kind = required_text(artifact_kind, "artifact_kind", 160)
        if not isinstance(artifact, dict):
            raise ValueError("artifact must be an object")
        validate_private_payload(artifact)
        evidence_ids = _string_ids(source_evidence_ids, "source_evidence_ids")
        payload = {
            "user_id": user_id,
            "investigation_id": investigation,
            "cycle_id": cycle,
            "provider": provider_value,
            "artifact_kind": kind,
            "artifact": artifact,
            "source_evidence_ids": evidence_ids,
            "nonclinical": True,
        }
        command, fingerprint = command_parts(command_id, payload)
        with self._connect() as connection:
            prior = command_result(
                connection,
                table="research_artifacts",
                command_id=command,
                fingerprint=fingerprint,
            )
            if prior is not None:
                return prior
            require_investigation(connection, investigation, user_id)
            require_cycle(
                connection,
                cycle_id=cycle,
                investigation_id=investigation,
                user_id=user_id,
                expected_revision=expected_revision,
            )
            _selected_evidence(connection, investigation, evidence_ids)
            artifact_id = stable_id("research-artifact", command)
            connection.execute(
                "INSERT INTO research_artifacts(research_artifact_id, investigation_id, "
                "cycle_id, user_id, provider, artifact_kind, nonclinical, artifact_json, "
                "source_evidence_ids_json, command_id, command_fingerprint, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
                (
                    artifact_id,
                    investigation,
                    cycle,
                    user_id,
                    provider_value,
                    kind,
                    compact_json(
                        {
                            **artifact,
                            "nonclinical": True,
                            "hypothesis_effect": "none",
                        }
                    ),
                    compact_json(evidence_ids),
                    command,
                    fingerprint,
                    utc_now(),
                ),
            )
            advance_cycle(connection, cycle)
            row = connection.execute(
                "SELECT * FROM research_artifacts WHERE research_artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        return row_dict(row)

    def register_panel_assignment(
        self: _StoreContract,
        user_id: str,
        *,
        investigation_id: object,
        cycle_id: object,
        packet_id: object,
        specialist_role: object,
        agent_profile: object,
        objective: object,
        command_id: object,
        native_subagent_id: object = None,
        status: object = "proposed",
        expected_revision: int,
    ) -> JsonObject:
        investigation = required_text(investigation_id, "investigation_id", 200)
        cycle = required_text(cycle_id, "cycle_id", 200)
        packet = required_text(packet_id, "packet_id", 200)
        role = required_text(specialist_role, "specialist_role", 160)
        profile = required_text(agent_profile, "agent_profile", 160)
        objective_value = required_text(objective, "objective", 2000)
        subagent = optional_text(native_subagent_id, "native_subagent_id", 300)
        status_value = required_text(status, "status", 80)
        if status_value not in {
            "proposed",
            "spawned",
            "completed",
            "failed",
            "cancelled",
        }:
            raise ValueError("unsupported assignment status")
        payload = {
            "user_id": user_id,
            "investigation_id": investigation,
            "cycle_id": cycle,
            "packet_id": packet,
            "specialist_role": role,
            "agent_profile": profile,
            "objective": objective_value,
            "native_subagent_id": subagent,
            "status": status_value,
        }
        command, fingerprint = command_parts(command_id, payload)
        now = utc_now()
        with self._connect() as connection:
            prior = command_result(
                connection,
                table="panel_assignments",
                command_id=command,
                fingerprint=fingerprint,
            )
            if prior is not None:
                return prior
            require_investigation(connection, investigation, user_id)
            require_cycle(
                connection,
                cycle_id=cycle,
                investigation_id=investigation,
                user_id=user_id,
                expected_revision=expected_revision,
            )
            packet_row = connection.execute(
                "SELECT * FROM specialist_packets WHERE packet_id = ?", (packet,)
            ).fetchone()
            if (
                packet_row is None
                or str(packet_row["user_id"]) != user_id
                or str(packet_row["investigation_id"]) != investigation
                or str(packet_row["cycle_id"]) != cycle
                or str(packet_row["specialist_role"]) != role
            ):
                raise ValueError("packet_id must belong to this assignment scope")
            assignment_id = stable_id("panel-assignment", command)
            started_at = (
                now if status_value in {"spawned", "completed", "failed"} else None
            )
            completed_at = (
                now if status_value in {"completed", "failed", "cancelled"} else None
            )
            connection.execute(
                "INSERT INTO panel_assignments(assignment_id, investigation_id, cycle_id, "
                "packet_id, user_id, specialist_role, agent_profile, objective, "
                "native_subagent_id, status, command_id, command_fingerprint, started_at, "
                "completed_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    assignment_id,
                    investigation,
                    cycle,
                    packet,
                    user_id,
                    role,
                    profile,
                    objective_value,
                    subagent,
                    status_value,
                    command,
                    fingerprint,
                    started_at,
                    completed_at,
                    now,
                ),
            )
            advance_cycle(connection, cycle)
            row = connection.execute(
                "SELECT * FROM panel_assignments WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
        result = row_dict(row)
        result["progress_source"] = "reported_by_main_agent"
        return result

    def record_specialist_finding(
        self: _StoreContract,
        user_id: str,
        *,
        investigation_id: object,
        cycle_id: object,
        assignment_id: object,
        finding: object,
        evidence_record_ids: object,
        command_id: object,
        status: object = "recorded",
        expected_revision: int,
    ) -> JsonObject:
        investigation = required_text(investigation_id, "investigation_id", 200)
        cycle = required_text(cycle_id, "cycle_id", 200)
        assignment = required_text(assignment_id, "assignment_id", 200)
        if not isinstance(finding, dict):
            raise ValueError("finding must be an object")
        validate_private_payload(finding)
        evidence_ids = _string_ids(evidence_record_ids, "evidence_record_ids")
        status_value = required_text(status, "status", 80)
        if status_value not in {"recorded", "accepted", "rejected"}:
            raise ValueError("unsupported finding status")
        payload = {
            "user_id": user_id,
            "investigation_id": investigation,
            "cycle_id": cycle,
            "assignment_id": assignment,
            "finding": finding,
            "evidence_record_ids": evidence_ids,
            "status": status_value,
        }
        command, fingerprint = command_parts(command_id, payload)
        with self._connect() as connection:
            prior = command_result(
                connection,
                table="specialist_findings",
                command_id=command,
                fingerprint=fingerprint,
            )
            if prior is not None:
                return prior
            require_investigation(connection, investigation, user_id)
            require_cycle(
                connection,
                cycle_id=cycle,
                investigation_id=investigation,
                user_id=user_id,
                expected_revision=expected_revision,
            )
            assignment_row = connection.execute(
                "SELECT * FROM panel_assignments WHERE assignment_id = ?", (assignment,)
            ).fetchone()
            if (
                assignment_row is None
                or str(assignment_row["user_id"]) != user_id
                or str(assignment_row["investigation_id"]) != investigation
                or str(assignment_row["cycle_id"]) != cycle
            ):
                raise ValueError("assignment_id must belong to this cycle")
            _selected_evidence(connection, investigation, evidence_ids)
            finding_id = stable_id("specialist-finding", command)
            connection.execute(
                "INSERT INTO specialist_findings(finding_id, investigation_id, cycle_id, "
                "assignment_id, user_id, finding_json, evidence_record_ids_json, status, "
                "command_id, command_fingerprint, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    finding_id,
                    investigation,
                    cycle,
                    assignment,
                    user_id,
                    compact_json(finding),
                    compact_json(evidence_ids),
                    status_value,
                    command,
                    fingerprint,
                    utc_now(),
                ),
            )
            advance_cycle(connection, cycle)
            row = connection.execute(
                "SELECT * FROM specialist_findings WHERE finding_id = ?", (finding_id,)
            ).fetchone()
        result = row_dict(row)
        result["record_kind"] = "specialist_analysis"
        result["progress_source"] = "reported_by_main_agent"
        return result

    def record_information_gap(
        self: _StoreContract,
        user_id: str,
        *,
        investigation_id: object,
        cycle_id: object,
        description: object,
        command_id: object,
        importance: object = None,
        expected_revision: int,
    ) -> JsonObject:
        return self._record_cycle_text(
            table="information_gaps",
            id_column="gap_id",
            id_prefix="information-gap",
            text_column="description",
            text=description,
            optional_column="importance",
            optional_value=importance,
            initial_status="open",
            user_id=user_id,
            investigation_id=investigation_id,
            cycle_id=cycle_id,
            command_id=command_id,
            expected_revision=expected_revision,
        )

    def record_evidence_reference(
        self: _StoreContract,
        user_id: str,
        *,
        investigation_id: object,
        cycle_id: object,
        evidence_record_id: object,
        relationship: object,
        command_id: object,
        expected_revision: int,
    ) -> JsonObject:
        investigation = required_text(investigation_id, "investigation_id", 200)
        cycle = required_text(cycle_id, "cycle_id", 200)
        evidence_id = required_text(evidence_record_id, "evidence_record_id", 200)
        relationship_value = required_text(relationship, "relationship", 100)
        if relationship_value not in {
            "supports",
            "contradicts",
            "context",
            "uncertain",
        }:
            raise ValueError("unsupported evidence relationship")
        payload = {
            "user_id": user_id,
            "investigation_id": investigation,
            "cycle_id": cycle,
            "evidence_record_id": evidence_id,
            "relationship": relationship_value,
        }
        command, fingerprint = command_parts(command_id, payload)
        with self._connect() as connection:
            prior = command_result(
                connection,
                table="investigation_evidence_references",
                command_id=command,
                fingerprint=fingerprint,
            )
            if prior is not None:
                return prior
            require_investigation(connection, investigation, user_id)
            require_cycle(
                connection,
                cycle_id=cycle,
                investigation_id=investigation,
                user_id=user_id,
                expected_revision=expected_revision,
            )
            _selected_evidence(connection, investigation, [evidence_id])
            reference_id = stable_id("investigation-evidence-reference", command)
            connection.execute(
                "INSERT INTO investigation_evidence_references("
                "investigation_evidence_reference_id, investigation_id, cycle_id, "
                "user_id, evidence_record_id, relationship, command_id, "
                "command_fingerprint, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    reference_id,
                    investigation,
                    cycle,
                    user_id,
                    evidence_id,
                    relationship_value,
                    command,
                    fingerprint,
                    utc_now(),
                ),
            )
            advance_cycle(connection, cycle)
            row = connection.execute(
                "SELECT * FROM investigation_evidence_references "
                "WHERE investigation_evidence_reference_id = ?",
                (reference_id,),
            ).fetchone()
        return row_dict(row)

    def record_patient_question(
        self: _StoreContract,
        user_id: str,
        *,
        investigation_id: object,
        cycle_id: object,
        question: object,
        command_id: object,
        rationale: object = None,
        expected_revision: int,
    ) -> JsonObject:
        return self._record_cycle_text(
            table="patient_questions",
            id_column="patient_question_id",
            id_prefix="patient-question",
            text_column="question",
            text=question,
            optional_column="rationale",
            optional_value=rationale,
            initial_status="open",
            user_id=user_id,
            investigation_id=investigation_id,
            cycle_id=cycle_id,
            command_id=command_id,
            expected_revision=expected_revision,
        )

    def record_recommended_next_step(
        self: _StoreContract,
        user_id: str,
        *,
        investigation_id: object,
        cycle_id: object,
        recommendation: object,
        command_id: object,
        rationale: object = None,
        priority: object = "medium",
        expected_revision: int,
    ) -> JsonObject:
        investigation = required_text(investigation_id, "investigation_id", 200)
        cycle = required_text(cycle_id, "cycle_id", 200)
        recommendation_value = required_text(recommendation, "recommendation", 2000)
        rationale_value = optional_text(rationale, "rationale", 2000)
        priority_value = required_text(priority, "priority", 80)
        if priority_value not in {"low", "medium", "high"}:
            raise ValueError("priority must be low, medium, or high")
        payload = {
            "user_id": user_id,
            "investigation_id": investigation,
            "cycle_id": cycle,
            "recommendation": recommendation_value,
            "rationale": rationale_value,
            "priority": priority_value,
        }
        command, fingerprint = command_parts(command_id, payload)
        with self._connect() as connection:
            prior = command_result(
                connection,
                table="recommended_next_steps",
                command_id=command,
                fingerprint=fingerprint,
            )
            if prior is not None:
                return prior
            require_investigation(connection, investigation, user_id)
            require_cycle(
                connection,
                cycle_id=cycle,
                investigation_id=investigation,
                user_id=user_id,
                expected_revision=expected_revision,
            )
            next_step_id = stable_id("recommended-next-step", command)
            connection.execute(
                "INSERT INTO recommended_next_steps(next_step_id, investigation_id, cycle_id, "
                "user_id, recommendation, rationale, priority, status, command_id, "
                "command_fingerprint, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?)",
                (
                    next_step_id,
                    investigation,
                    cycle,
                    user_id,
                    recommendation_value,
                    rationale_value,
                    priority_value,
                    command,
                    fingerprint,
                    utc_now(),
                ),
            )
            advance_cycle(connection, cycle)
            row = connection.execute(
                "SELECT * FROM recommended_next_steps WHERE next_step_id = ?",
                (next_step_id,),
            ).fetchone()
        return row_dict(row)

    def append_investigation_work_event(
        self: _StoreContract,
        user_id: str,
        *,
        investigation_id: object,
        cycle_id: object,
        event_type: object,
        summary: object,
        command_id: object,
        details: object = None,
        expected_revision: int,
    ) -> JsonObject:
        investigation = required_text(investigation_id, "investigation_id", 200)
        cycle = required_text(cycle_id, "cycle_id", 200)
        event = required_text(event_type, "event_type", 100)
        summary_value = required_text(summary, "summary", 2000)
        details_value = details or {}
        if not isinstance(details_value, dict):
            raise ValueError("details must be an object")
        validate_private_payload(details_value)
        payload = {
            "user_id": user_id,
            "investigation_id": investigation,
            "cycle_id": cycle,
            "event_type": event,
            "summary": summary_value,
            "details": details_value,
        }
        command, fingerprint = command_parts(command_id, payload)
        with self._connect() as connection:
            prior = command_result(
                connection,
                table="investigation_work_events",
                command_id=command,
                fingerprint=fingerprint,
            )
            if prior is not None:
                return prior
            require_investigation(connection, investigation, user_id)
            require_cycle(
                connection,
                cycle_id=cycle,
                investigation_id=investigation,
                user_id=user_id,
                expected_revision=expected_revision,
            )
            sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 AS value FROM investigation_work_events WHERE cycle_id = ?",
                    (cycle,),
                ).fetchone()["value"]
            )
            event_id = stable_id("work-event", command)
            connection.execute(
                "INSERT INTO investigation_work_events(work_event_id, investigation_id, cycle_id, "
                "user_id, event_type, summary, details_json, command_id, command_fingerprint, "
                "sequence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    investigation,
                    cycle,
                    user_id,
                    event,
                    summary_value,
                    compact_json(details_value),
                    command,
                    fingerprint,
                    sequence,
                    utc_now(),
                ),
            )
            advance_cycle(connection, cycle)
            row = connection.execute(
                "SELECT * FROM investigation_work_events WHERE work_event_id = ?",
                (event_id,),
            ).fetchone()
        result = row_dict(row)
        result["progress_source"] = "reported_by_main_agent"
        return result

    def list_investigation_board(
        self: _StoreContract, user_id: str, investigation_id: object
    ) -> JsonObject:
        investigation = required_text(investigation_id, "investigation_id", 200)
        result = self.get_investigation(investigation)
        if str(result.get("user_id") or "") != user_id:
            raise KeyError(investigation)
        with self._connect() as connection:
            target = require_investigation(connection, investigation, user_id)
            binding = connection.execute(
                "SELECT * FROM investigation_portal_bindings WHERE investigation_id = ?",
                (investigation,),
            ).fetchone()
            result.update(row_dict(target))
            result["binding"] = row_dict(binding) if binding is not None else None
            for key, table, order in (
                ("cycles", "investigation_cycles", "cycle_number"),
                ("packets", "specialist_packets", "created_at"),
                ("assignments", "panel_assignments", "created_at"),
                ("findings", "specialist_findings", "created_at"),
                ("research_artifacts", "research_artifacts", "created_at"),
                (
                    "evidence_references",
                    "investigation_evidence_references",
                    "created_at",
                ),
                ("information_gaps", "information_gaps", "created_at"),
                ("patient_questions", "patient_questions", "created_at"),
                ("recommended_next_steps", "recommended_next_steps", "created_at"),
                ("work_events", "investigation_work_events", "sequence"),
            ):
                rows = connection.execute(
                    f"SELECT * FROM {table} WHERE investigation_id = ? ORDER BY {order}",
                    (investigation,),
                ).fetchall()
                items = [row_dict(row) for row in rows]
                if key in {"assignments", "findings", "work_events"}:
                    for item in items:
                        item["progress_source"] = "reported_by_main_agent"
                if key == "findings":
                    for item in items:
                        item["record_kind"] = "specialist_analysis"
                result[key] = items
        result["progress_source"] = "reported_by_main_agent"
        return result

    def _record_cycle_text(
        self: _StoreContract,
        *,
        table: str,
        id_column: str,
        id_prefix: str,
        text_column: str,
        text: object,
        optional_column: str,
        optional_value: object,
        initial_status: str,
        user_id: str,
        investigation_id: object,
        cycle_id: object,
        command_id: object,
        expected_revision: int,
    ) -> JsonObject:
        allowed = {
            ("information_gaps", "gap_id", "description", "importance"),
            ("patient_questions", "patient_question_id", "question", "rationale"),
        }
        if (table, id_column, text_column, optional_column) not in allowed:
            raise ValueError("unsupported cycle record")
        investigation = required_text(investigation_id, "investigation_id", 200)
        cycle = required_text(cycle_id, "cycle_id", 200)
        text_value = required_text(text, text_column, 2000)
        extra = optional_text(optional_value, optional_column, 2000)
        payload = {
            "user_id": user_id,
            "investigation_id": investigation,
            "cycle_id": cycle,
            text_column: text_value,
            optional_column: extra,
        }
        command, fingerprint = command_parts(command_id, payload)
        with self._connect() as connection:
            prior = command_result(
                connection, table=table, command_id=command, fingerprint=fingerprint
            )
            if prior is not None:
                return prior
            require_investigation(connection, investigation, user_id)
            require_cycle(
                connection,
                cycle_id=cycle,
                investigation_id=investigation,
                user_id=user_id,
                expected_revision=expected_revision,
            )
            record_id = stable_id(id_prefix, command)
            connection.execute(
                f"INSERT INTO {table}({id_column}, investigation_id, cycle_id, user_id, "
                f"{text_column}, {optional_column}, status, command_id, command_fingerprint, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record_id,
                    investigation,
                    cycle,
                    user_id,
                    text_value,
                    extra,
                    initial_status,
                    command,
                    fingerprint,
                    utc_now(),
                ),
            )
            advance_cycle(connection, cycle)
            row = connection.execute(
                f"SELECT * FROM {table} WHERE {id_column} = ?", (record_id,)
            ).fetchone()
        return row_dict(row)


def _string_ids(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    ids = [required_text(item, field, 200) for item in value]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{field} must not contain duplicates")
    return ids


def _selected_facts(
    connection: Any, user_id: str, fact_ids: list[str]
) -> list[JsonObject]:
    if not fact_ids:
        return []
    placeholders = ",".join("?" for _ in fact_ids)
    rows = connection.execute(
        f"SELECT * FROM molecular_observations WHERE user_id = ? AND observation_revision_id IN ({placeholders})",
        (user_id, *fact_ids),
    ).fetchall()
    by_id = {str(row["observation_revision_id"]): row_dict(row) for row in rows}
    if set(by_id) != set(fact_ids):
        raise ValueError("selected profile facts must belong to the current user")
    return [
        {
            "fact_id": fact_id,
            "modality": by_id[fact_id].get("modality"),
            "label": by_id[fact_id].get("label"),
            "original_wording": by_id[fact_id].get("original_wording"),
            "verification_state": by_id[fact_id].get("verification_state"),
            "source_class": by_id[fact_id].get("source_class"),
        }
        for fact_id in fact_ids
    ]


def _selected_evidence(
    connection: Any, investigation_id: str, evidence_ids: list[str]
) -> list[JsonObject]:
    if not evidence_ids:
        return []
    placeholders = ",".join("?" for _ in evidence_ids)
    rows = connection.execute(
        f"SELECT * FROM evidence_records WHERE investigation_id = ? AND evidence_record_id IN ({placeholders})",
        (investigation_id, *evidence_ids),
    ).fetchall()
    by_id = {str(row["evidence_record_id"]): row_dict(row) for row in rows}
    if set(by_id) != set(evidence_ids):
        raise ValueError("selected evidence must belong to the current investigation")
    return [
        {
            "evidence_record_id": evidence_id,
            "source_family": by_id[evidence_id].get("source_family"),
            "operation": by_id[evidence_id].get("operation"),
            "evidence_envelope": by_id[evidence_id].get("evidence_envelope"),
        }
        for evidence_id in evidence_ids
    ]


def _validate_genomic_summary_projection(evidence: list[JsonObject]) -> None:
    if not evidence:
        raise ValueError("main_agent_genomic_summary requires stored evidence")
    serialized = compact_json(evidence).lower()
    if "q76h" in serialized or "gln76his" in serialized:
        if "uncertain" not in serialized or "confirm" not in serialized:
            raise ValueError(
                "a Q76H genomic summary must preserve uncertain-classification and confirmation qualifiers"
            )


__all__ = ["InvestigationPanelStoreMixin"]
