"""Tamper-evident result receipts and receipt-only evidence capture."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from ..evidence import envelope as canonical_evidence_envelope
from .models import JsonObject, compact_json, required_text, row_dict, utc_now
from .orchestrator_support import (
    OrchestratorStoreContract,
    advance_investigation_revision,
    command_replay,
    json_sha256,
    require_cycle,
    require_investigation_revision,
    save_command,
)


def durable_genomi_result_receipt_id(receipt_token: object) -> str:
    """Derive the durable identity for one opaque process receipt token."""

    token = required_text(receipt_token, "result_receipt_id", 500)
    return f"genomi-result-receipt-{json_sha256({'process_receipt': token})}"


def _object(value: object, field: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return dict(value)


def _verified_receipt(row: object, *, provider: bool = False) -> JsonObject:
    value = row_dict(row)
    if provider:
        signed = {
            "provider": value["provider"],
            "result_kind": value["result_kind"],
            "operation": value["operation"],
            "exact_result": value["exact_result"],
            "exact_result_sha256": value["exact_result_sha256"],
            "specialist_assignment_id": value["specialist_assignment_id"],
            "specialist_brief_id": value["specialist_brief_id"],
            "specialist_brief_payload_sha256": value["specialist_brief_payload_sha256"],
            "disclosure_receipt_id": value.get("disclosure_receipt_id"),
            "provider_provenance": value["provider_provenance"],
            "issued_at": value["issued_at"],
        }
    else:
        signed = {
            key: value.get(key)
            for key in (
                "operation", "params", "presented_result", "presented_result_sha256",
                "evidence_envelope", "defaults_applied", "coverage", "source_provenance",
                "workspace_session_id", "user_id", "investigation_id",
                "patient_molecular_snapshot_id", "consent_receipt_id", "agi_id",
                "agi_snapshot_id", "issued_at",
            )
        }
    if json_sha256(signed) != value["receipt_sha256"]:
        raise ValueError("stored result receipt failed its integrity check")
    payload = value["exact_result"] if provider else value["presented_result"]
    expected = value["exact_result_sha256"] if provider else value["presented_result_sha256"]
    if json_sha256(payload) != expected:
        raise ValueError("stored result payload failed its integrity check")
    return value


def _validate_capturable_provider_result(receipt: JsonObject) -> None:
    """Admit only completed, data-returned provider results to durable state."""

    operation = str(receipt.get("operation") or "")
    provider = str(receipt.get("provider") or "")
    result = _object(receipt.get("exact_result"), "exact_result")
    if result.get("status") != "completed":
        raise ValueError("only completed provider results can be captured")
    envelope = _object(result.get("evidence_envelope"), "evidence_envelope")
    canonical_evidence_envelope.validate(envelope)
    if envelope.get("operation") != operation:
        raise ValueError("provider result envelope operation does not match its receipt")
    if envelope.get("finding_state") != canonical_evidence_envelope.EVIDENCE_PRESENT:
        raise ValueError("only data-returned provider results can be captured")
    if provider == "paperclip" and operation != "paperclip.retrieve_document_evidence":
        raise ValueError(
            "Paperclip search results are discovery-only; capture line-pinned document evidence"
        )
    if provider == "paperclip" and not (
        isinstance(result.get("excerpts"), list) and result["excerpts"]
    ):
        raise ValueError("captured Paperclip evidence requires line-pinned excerpts")


class ResultReceiptStoreMixin:
    """Issue immutable receipts internally and capture only verified receipts."""

    def issue_genomi_result_receipt(
        self: OrchestratorStoreContract,
        *,
        operation: object,
        params: object,
        presented_result: object,
        investigation_id: object = None,
        workspace_session_id: object = None,
        receipt_token: object = None,
    ) -> str:
        operation_value = required_text(operation, "operation", 300)
        params_value = _object(params, "params")
        result = _object(presented_result, "presented_result")
        # The embedding Main Orchestrator binds this argument in the issuer
        # closure.  Evidence-operation parameters are never identity authority.
        target_id = required_text(investigation_id, "investigation_id", 300)
        envelope = _object(result.get("evidence_envelope"), "evidence_envelope")
        canonical_evidence_envelope.validate(envelope)
        with self._connect() as connection:
            investigation = connection.execute(
                "SELECT * FROM investigations WHERE investigation_id = ?", (target_id,)
            ).fetchone()
            context = connection.execute(
                "SELECT * FROM orchestrator_investigation_contexts WHERE investigation_id = ?",
                (target_id,),
            ).fetchone()
        if investigation is None or context is None:
            raise ValueError("result receipt requires an active Lab investigation")
        session = str(workspace_session_id or context["workspace_session_id"])
        if session != str(context["workspace_session_id"]):
            raise ValueError("result receipt session does not match the investigation")
        inv = row_dict(investigation)
        consent_id = inv.get("active_consent_receipt_id")
        agi_id = None
        agi_snapshot_id = None
        if consent_id:
            with self._connect() as connection:
                consent = connection.execute(
                    "SELECT agi_id, agi_snapshot_id FROM consent_receipts WHERE consent_receipt_id = ? AND revoked_at IS NULL",
                    (consent_id,),
                ).fetchone()
            if consent is None:
                raise ValueError("private result receipt requires live investigation consent")
            agi_id, agi_snapshot_id = consent["agi_id"], consent["agi_snapshot_id"]
        issued_at = utc_now()
        result_hash = json_sha256(result)
        signed = {
            "operation": operation_value,
            "params": params_value,
            "presented_result": result,
            "presented_result_sha256": result_hash,
            "evidence_envelope": envelope,
            "defaults_applied": result.get("defaults_applied") or {},
            "coverage": result.get("coverage") or {},
            "source_provenance": result.get("source_provenance") or result.get("provenance") or {},
            "workspace_session_id": session,
            "user_id": inv["user_id"],
            "investigation_id": target_id,
            "patient_molecular_snapshot_id": inv.get("patient_molecular_snapshot_id"),
            "consent_receipt_id": consent_id,
            "agi_id": agi_id,
            "agi_snapshot_id": agi_snapshot_id,
            "issued_at": issued_at,
        }
        receipt_hash = json_sha256(signed)
        receipt_id = (
            durable_genomi_result_receipt_id(receipt_token)
            if receipt_token is not None
            else f"genomi-result-receipt-{uuid.uuid4().hex}"
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO genomi_result_receipts(result_receipt_id, operation, params_json, "
                "presented_result_json, presented_result_sha256, evidence_envelope_json, "
                "defaults_applied_json, coverage_json, source_provenance_json, workspace_session_id, "
                "user_id, investigation_id, patient_molecular_snapshot_id, consent_receipt_id, "
                "agi_id, agi_snapshot_id, receipt_sha256, issued_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    receipt_id, operation_value, compact_json(params_value), compact_json(result),
                    result_hash, compact_json(signed["evidence_envelope"]),
                    compact_json(signed["defaults_applied"]), compact_json(signed["coverage"]),
                    compact_json(signed["source_provenance"]), session, inv["user_id"], target_id,
                    inv.get("patient_molecular_snapshot_id"), consent_id, agi_id, agi_snapshot_id,
                    receipt_hash, issued_at,
                ),
            )
        return receipt_id

    def get_genomi_result_receipt(self: OrchestratorStoreContract, result_receipt_id: object) -> JsonObject:
        identifier = required_text(result_receipt_id, "result_receipt_id", 300)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM genomi_result_receipts WHERE result_receipt_id = ?", (identifier,)
            ).fetchone()
        if row is None:
            raise KeyError(identifier)
        return _verified_receipt(row)

    def capture_evidence_result(
        self: OrchestratorStoreContract,
        investigation_id: str,
        *,
        cycle_id: object,
        result_receipt_id: object,
        purpose: object,
        command_id: object,
        expected_revision: object,
    ) -> JsonObject:
        receipt_id = required_text(result_receipt_id, "result_receipt_id", 300)
        purpose_value = required_text(purpose, "purpose", 2_000)
        request = {"cycle_id": cycle_id, "result_receipt_id": receipt_id, "purpose": purpose_value, "expected_revision": expected_revision}
        command, request_hash, replay = command_replay(
            self, investigation_id=investigation_id, operation="lab.capture_evidence_result",
            command_id=command_id, request=request,
        )
        if replay is not None:
            return replay
        with self.atomic_write():
            investigation = require_investigation_revision(self, investigation_id, expected_revision)
            cycle = require_cycle(self, investigation_id, cycle_id)
            receipt = self.get_genomi_result_receipt(receipt_id)
            if receipt["investigation_id"] != investigation_id:
                raise ValueError("result receipt belongs to another investigation")
            if receipt.get("patient_molecular_snapshot_id") != investigation.get("patient_molecular_snapshot_id"):
                raise ValueError("result receipt belongs to a different profile snapshot")
            if receipt.get("consent_receipt_id") != investigation.get("active_consent_receipt_id"):
                raise ValueError("result receipt consent is no longer current")
            if receipt.get("captured_at"):
                raise ValueError("result receipt was already captured")
            source_family = str(receipt["operation"]).split(".", 1)[0]
            evidence = self.commit_evidence(
                investigation_id,
                source_family=source_family,
                operation=receipt["operation"],
                evidence=receipt["presented_result"],
                deduplication_key=f"result-receipt:{receipt_id}",
                expected_consent_receipt_id=receipt.get("consent_receipt_id"),
            )
            now = utc_now()
            with self._connect() as connection:
                capture_id = f"captured-evidence-result-{uuid.uuid4().hex}"
                connection.execute(
                    "INSERT INTO captured_evidence_results(captured_evidence_result_id, result_receipt_id, "
                    "evidence_record_id, investigation_id, cycle_id, captured_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (capture_id, receipt_id, evidence["evidence_record_id"], investigation_id, cycle["cycle_id"], now),
                )
                connection.execute("UPDATE genomi_result_receipts SET captured_at = ? WHERE result_receipt_id = ?", (now, receipt_id))
            snapshot = self.create_evidence_snapshot(investigation_id, reason=purpose_value)
            with self._connect() as connection:
                revision_row = connection.execute("SELECT domain_revision FROM investigations WHERE investigation_id = ?", (investigation_id,)).fetchone()
            response = {"evidence_record": evidence, "evidence_snapshot": snapshot, "domain_revision": int(revision_row["domain_revision"])}
            save_command(self, command_id=command, investigation_id=investigation_id, operation="lab.capture_evidence_result", request_sha256=request_hash, response=response)
        return response

    def issue_provider_result_receipt(
        self: OrchestratorStoreContract,
        *, provider: object, result_kind: object, operation: object, exact_result: object,
        specialist_assignment_id: object, specialist_brief_id: object,
        provider_provenance: object,
    ) -> str:
        provider_value = required_text(provider, "provider", 100)
        kind = required_text(result_kind, "result_kind", 100)
        if kind not in {"public_source_evidence", "research_artifact"}:
            raise ValueError("unsupported provider result kind")
        expected_kind = (
            "public_source_evidence"
            if provider_value == "paperclip"
            else "research_artifact"
            if provider_value in {"biohub-esm", "proto"}
            else None
        )
        if expected_kind is None or kind != expected_kind:
            raise ValueError(
                "provider result kind does not match the fixed provider evidence policy"
            )
        operation_value = required_text(operation, "operation", 300)
        result = _object(exact_result, "exact_result")
        provenance = _object(provider_provenance, "provider_provenance")
        assignment_id = required_text(
            specialist_assignment_id, "specialist_assignment_id", 300
        )
        brief_id = required_text(specialist_brief_id, "specialist_brief_id", 300)
        with self._connect() as connection:
            brief = connection.execute("SELECT * FROM specialist_briefs WHERE specialist_brief_id = ?", (brief_id,)).fetchone()
            assignment = connection.execute(
                "SELECT * FROM specialist_assignments "
                "WHERE specialist_assignment_id = ? AND specialist_brief_id = ?",
                (assignment_id, brief_id),
            ).fetchone()
        if brief is None:
            raise ValueError("specialist brief not found")
        if assignment is None or str(assignment["state"]) != "completed":
            raise ValueError(
                "provider result receipts require the completed matching assignment"
            )
        expected_provider = {
            "public_literature": "paperclip",
            "protein_model_research": "biohub-esm",
            "experiment_design": "proto",
        }.get(str(brief["execution_policy"]))
        if provider_value != expected_provider:
            raise ValueError(
                "provider does not match the specialist brief execution policy"
            )
        issued_at = utc_now()
        result_hash = json_sha256(result)
        signed = {
            "provider": provider_value, "result_kind": kind, "operation": operation_value,
            "exact_result": result, "exact_result_sha256": result_hash,
            "specialist_assignment_id": assignment_id,
            "specialist_brief_id": brief_id,
            "specialist_brief_payload_sha256": brief["outbound_payload_sha256"],
            "disclosure_receipt_id": brief["disclosure_receipt_id"],
            "provider_provenance": provenance, "issued_at": issued_at,
        }
        receipt_hash = json_sha256(signed)
        receipt_id = f"provider-result-receipt-{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO provider_result_receipts(provider_result_receipt_id, provider, result_kind, "
                "operation, exact_result_json, exact_result_sha256, specialist_assignment_id, specialist_brief_id, "
                "specialist_brief_payload_sha256, disclosure_receipt_id, provider_provenance_json, "
                "receipt_sha256, issued_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (receipt_id, provider_value, kind, operation_value, compact_json(result), result_hash,
                 assignment_id, brief_id, brief["outbound_payload_sha256"], brief["disclosure_receipt_id"],
                 compact_json(provenance), receipt_hash, issued_at),
            )
        return receipt_id

    def capture_provider_result(
        self: OrchestratorStoreContract,
        investigation_id: str,
        *, cycle_id: object, assignment_id: object, specialist_brief_id: object,
        provider_result_receipt_id: object, purpose: object, command_id: object,
        expected_revision: object,
    ) -> JsonObject:
        assignment = required_text(assignment_id, "assignment_id", 300)
        brief_id = required_text(specialist_brief_id, "specialist_brief_id", 300)
        receipt_id = required_text(provider_result_receipt_id, "provider_result_receipt_id", 300)
        purpose_value = required_text(purpose, "purpose", 2_000)
        request = {"cycle_id": cycle_id, "assignment_id": assignment, "specialist_brief_id": brief_id, "provider_result_receipt_id": receipt_id, "purpose": purpose_value, "expected_revision": expected_revision}
        command, request_hash, replay = command_replay(self, investigation_id=investigation_id, operation="lab.capture_provider_result", command_id=command_id, request=request)
        if replay is not None:
            return replay
        with self.atomic_write():
            require_investigation_revision(self, investigation_id, expected_revision)
            cycle = require_cycle(self, investigation_id, cycle_id)
            with self._connect() as connection:
                assignment_row = connection.execute("SELECT * FROM specialist_assignments WHERE specialist_assignment_id = ? AND investigation_id = ?", (assignment, investigation_id)).fetchone()
                receipt_row = connection.execute("SELECT * FROM provider_result_receipts WHERE provider_result_receipt_id = ?", (receipt_id,)).fetchone()
            if assignment_row is None or assignment_row["cycle_id"] != cycle["cycle_id"] or assignment_row["specialist_brief_id"] != brief_id or assignment_row["state"] != "completed":
                raise ValueError("assignment and specialist brief do not match this cycle")
            if receipt_row is None:
                raise ValueError("provider result receipt not found")
            receipt = _verified_receipt(receipt_row, provider=True)
            _validate_capturable_provider_result(receipt)
            if receipt["specialist_assignment_id"] != assignment or receipt["specialist_brief_id"] != brief_id or receipt.get("captured_at"):
                raise ValueError("provider result receipt is not capturable for this brief")
            evidence = None
            artifact = None
            if receipt["result_kind"] == "public_source_evidence":
                evidence = self.commit_evidence(
                    investigation_id, source_family=receipt["provider"], operation=receipt["operation"],
                    evidence=receipt["exact_result"], deduplication_key=f"provider-receipt:{receipt_id}",
                    expected_disclosure_receipt_id=receipt.get("disclosure_receipt_id"),
                )
            else:
                artifact_id = f"research-artifact-{uuid.uuid4().hex}"
                with self._connect() as connection:
                    connection.execute(
                        "INSERT INTO research_artifacts(research_artifact_id, investigation_id, cycle_id, specialist_assignment_id, "
                        "provider_result_receipt_id, provider, artifact_kind, artifact_json, provenance_json, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (artifact_id, investigation_id, cycle["cycle_id"], assignment, receipt_id, receipt["provider"],
                         receipt["operation"], compact_json(receipt["exact_result"]), compact_json(receipt["provider_provenance"]), utc_now()),
                    )
                    artifact = row_dict(connection.execute("SELECT * FROM research_artifacts WHERE research_artifact_id = ?", (artifact_id,)).fetchone())
            now = utc_now()
            with self._connect() as connection:
                capture_id = f"captured-provider-result-{uuid.uuid4().hex}"
                connection.execute(
                    "INSERT INTO captured_provider_results(captured_provider_result_id, provider_result_receipt_id, investigation_id, cycle_id, "
                    "specialist_assignment_id, evidence_record_id, research_artifact_id, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (capture_id, receipt_id, investigation_id, cycle["cycle_id"], assignment,
                     evidence.get("evidence_record_id") if evidence else None,
                     artifact.get("research_artifact_id") if artifact else None, now),
                )
                connection.execute("UPDATE provider_result_receipts SET captured_at = ? WHERE provider_result_receipt_id = ?", (now, receipt_id))
            snapshot = self.create_evidence_snapshot(investigation_id, reason=purpose_value) if evidence else None
            with self._connect() as connection:
                if not evidence:
                    revision = advance_investigation_revision(self, investigation_id)
                else:
                    revision = int(connection.execute("SELECT domain_revision FROM investigations WHERE investigation_id = ?", (investigation_id,)).fetchone()["domain_revision"])
            response = {"evidence_record": evidence, "research_artifact": artifact, "evidence_snapshot": snapshot, "domain_revision": revision}
            save_command(self, command_id=command, investigation_id=investigation_id, operation="lab.capture_provider_result", request_sha256=request_hash, response=response)
        return response


__all__ = ["ResultReceiptStoreMixin", "durable_genomi_result_receipt_id"]
