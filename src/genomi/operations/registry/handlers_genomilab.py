"""Host-neutral GenomiLab record operations in the existing MCP process."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from contextlib import contextmanager
from typing import Callable, Iterator

from ...lab.store import GenomiLabStore
from ...runtime.context import context_authority_lock, context_scope, describe_context
from .application_model import (
    INTEGER,
    STRING,
    STRING_ARRAY,
    ApplicationOperation,
    object_schema,
)
from .errors import JsonObject, OperationError
from .evidence_result_receipts import (
    EVIDENCE_RESULT_RECEIPTS,
    EvidenceResultReceiptError,
)

PORTAL_PROJECT_ENV = "GENOMILAB_PORTAL_PROJECT_ID"
PORTAL_FRAME_ENV = "GENOMILAB_PORTAL_FRAME_ID"


def _genomilab_describe_workspace(_: JsonObject) -> JsonObject:
    return _with_current_user(_describe_workspace)


def _genomilab_list_investigations(_: JsonObject) -> JsonObject:
    return _with_current_user(
        lambda store, user_id, _session: {
            "status": "ready",
            "investigations": [
                _investigation_summary(item)
                for item in store.list_investigations(user_id)
            ],
        }
    )


def _genomilab_read_investigation(params: JsonObject) -> JsonObject:
    investigation_id = _required(params, "investigation_id")
    return _with_current_user(
        lambda store, user_id, _session: store.list_investigation_board(
            user_id, investigation_id
        )
    )


def _genomilab_start_investigation(params: JsonObject) -> JsonObject:
    project_id, frame_id = _portal_scope()
    question = _required(params, "question")
    command_id = _required(params, "command_id")
    disease_scope = _optional(params, "disease_scope")

    def start(store: GenomiLabStore, user_id: str, _session: str) -> JsonObject:
        _ensure_workspace(store, user_id)
        result = store.start_portal_investigation(
            user_id,
            question=question,
            disease_scope=disease_scope,
            portal_project_id=project_id,
            frame_id=frame_id,
            command_id=command_id,
        )
        return {"status": "ready", **result}

    return _with_current_user(start)


def _genomilab_start_cycle(params: JsonObject) -> JsonObject:
    investigation_id = _required(params, "investigation_id")
    return _with_current_user(
        lambda store, user_id, _session: {
            "status": "active",
            "cycle": store.start_cycle(
                user_id,
                investigation_id=investigation_id,
                objective=_required(params, "objective"),
                command_id=_required(params, "command_id"),
                patient_molecular_snapshot_id=_optional(
                    params, "patient_molecular_snapshot_id"
                ),
                expected_revision=_required_int(params, "expected_revision"),
            ),
        }
    )


def _genomilab_preview_profile_access(params: JsonObject) -> JsonObject:
    return _with_current_user(
        lambda store, user_id, _session: {
            "status": "candidate",
            "profile_access": store.profile_snapshot_candidate(
                user_id,
                investigation_id=_required(params, "investigation_id"),
                purpose=_required(params, "purpose"),
                observation_revision_ids=_string_list(
                    params, "observation_revision_ids"
                ),
            ),
        }
    )


def _genomilab_approve_profile_access(params: JsonObject) -> JsonObject:
    if params.get("approved") is not True:
        raise OperationError(
            "invalid_params",
            "approved must be true after the exact preview is reviewed",
        )
    command_id = _required(params, "command_id")
    payload = {
        key: params.get(key)
        for key in (
            "investigation_id",
            "purpose",
            "observation_revision_ids",
            "candidate_sha256",
            "refresh",
            "expected_base_patient_molecular_snapshot_id",
            "approved",
        )
    }

    def approve(store: GenomiLabStore, user_id: str, session_id: str) -> JsonObject:
        with store.atomic_write():
            prior = store.get_investigation_command(
                user_id,
                operation="approve_profile_access",
                command_id=command_id,
                payload=payload,
            )
            if prior is not None:
                snapshot = store.get_profile_snapshot(
                    str(prior["patient_molecular_snapshot_id"])
                )
                snapshot["consent_receipt_id"] = prior["consent_receipt_id"]
                return {"status": "approved", "profile_access": snapshot}
            snapshot = store.create_profile_snapshot(
                user_id,
                workspace_session_id=session_id,
                investigation_id=_required(params, "investigation_id"),
                purpose=_required(params, "purpose"),
                observation_revision_ids=_string_list(
                    params, "observation_revision_ids"
                ),
                candidate_sha256=_required(params, "candidate_sha256"),
                approved=True,
                refresh=bool(params.get("refresh", False)),
                expected_base_patient_molecular_snapshot_id=_optional(
                    params, "expected_base_patient_molecular_snapshot_id"
                ),
            )
            store.record_investigation_command(
                user_id,
                operation="approve_profile_access",
                command_id=command_id,
                payload=payload,
                result={
                    "patient_molecular_snapshot_id": snapshot[
                        "patient_molecular_snapshot_id"
                    ],
                    "consent_receipt_id": snapshot["consent_receipt_id"],
                },
            )
        return {"status": "approved", "profile_access": snapshot}

    return _with_current_user(approve)


def _genomilab_revoke_profile_access(params: JsonObject) -> JsonObject:
    investigation_id = _required(params, "investigation_id")
    command_id = _required(params, "command_id")
    expected_revision = _required_int(params, "expected_revision")
    payload = {
        "investigation_id": investigation_id,
        "expected_revision": expected_revision,
    }

    def revoke(store: GenomiLabStore, user_id: str, _session: str) -> JsonObject:
        with store.atomic_write():
            prior = store.get_investigation_command(
                user_id,
                operation="revoke_profile_access",
                command_id=command_id,
                payload=payload,
            )
            if prior is not None:
                return {"status": "revoked", **prior}
            investigation = _owned_investigation(store, user_id, investigation_id)
            receipt_id = str(investigation.get("active_consent_receipt_id") or "")
            if not receipt_id:
                raise ValueError("the investigation has no active profile approval")
            store.set_investigation_status(
                investigation_id,
                "paused_private_context",
                expected_revision=expected_revision,
            )
            revoked = store.revoke_consent(receipt_id)
            result = {
                "investigation_id": investigation_id,
                "consent_receipt_id": receipt_id,
                "consent_revoked": revoked,
            }
            store.record_investigation_command(
                user_id,
                operation="revoke_profile_access",
                command_id=command_id,
                payload=payload,
                result=result,
            )
        return {"status": "revoked", **result}

    return _with_current_user(revoke)


def _genomilab_read_approved_profile(params: JsonObject) -> JsonObject:
    investigation_id = _required(params, "investigation_id")

    def read(store: GenomiLabStore, user_id: str, session_id: str) -> JsonObject:
        investigation = _owned_investigation(store, user_id, investigation_id)
        snapshot_id = str(investigation.get("patient_molecular_snapshot_id") or "")
        receipt_id = str(investigation.get("active_consent_receipt_id") or "")
        if not snapshot_id or not receipt_id:
            raise ValueError("profile access has not been approved")
        receipt = store.consent_receipt(receipt_id)
        if (
            receipt.get("revoked_at")
            or receipt.get("workspace_session_id") != session_id
            or receipt.get("user_id") != user_id
            or receipt.get("investigation_id") != investigation_id
            or receipt.get("patient_molecular_snapshot_id") != snapshot_id
        ):
            raise ValueError(
                "profile access must be approved for this project/frame session"
            )
        return {
            "status": "approved",
            "profile": store.project_investigation_profile(investigation_id),
            "patient_molecular_snapshot_id": snapshot_id,
        }

    return _with_current_user(read)


def _genomilab_list_profile_updates(params: JsonObject) -> JsonObject:
    investigation_id = _required(params, "investigation_id")

    def updates(store: GenomiLabStore, user_id: str, _session: str) -> JsonObject:
        investigation = _owned_investigation(store, user_id, investigation_id)
        return {
            "status": "ready",
            "investigation_id": investigation_id,
            "profile_snapshot_history": investigation.get("profile_snapshot_history")
            or [],
            "refresh_lifecycle": investigation.get("refresh_lifecycle") or {},
        }

    return _with_current_user(updates)


def _genomilab_ingest_report(params: JsonObject) -> JsonObject:
    encoded = _required(params, "content_base64")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise OperationError(
            "invalid_params", "content_base64 must be valid base64"
        ) from exc
    command_id = _required(params, "command_id")
    payload = {
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "source_type": _required(params, "source_type"),
        "title": _required(params, "title"),
        "media_type": _required(params, "media_type"),
        "source_identifier": _optional(params, "source_identifier"),
        "issued_at": _optional(params, "issued_at"),
    }

    def ingest(store: GenomiLabStore, user_id: str, _session: str) -> JsonObject:
        _ensure_workspace(store, user_id)
        with store.atomic_write():
            prior = store.get_investigation_command(
                user_id,
                operation="ingest_report",
                command_id=command_id,
                payload=payload,
            )
            if prior is not None:
                workspace = store.get_workspace(user_id)
                artifact = next(
                    (
                        item
                        for item in workspace["profile"].get("source_artifacts") or []
                        if item.get("artifact_id") == prior.get("artifact_id")
                    ),
                    None,
                )
                if artifact is None:
                    raise KeyError(str(prior.get("artifact_id") or ""))
                metadata = artifact.get("metadata") or {}
                return {
                    "status": "stored",
                    "report": {
                        **artifact,
                        "content_stored": True,
                        "byte_size": metadata.get("byte_size"),
                    },
                }
            artifact = store.ingest_report(
                user_id,
                content=content,
                source_type=payload["source_type"],
                title=payload["title"],
                media_type=payload["media_type"],
                source_identifier=payload["source_identifier"],
                issued_at=payload["issued_at"],
            )
            store.record_investigation_command(
                user_id,
                operation="ingest_report",
                command_id=command_id,
                payload=payload,
                result={"artifact_id": artifact["artifact_id"]},
            )
        return {"status": "stored", "report": artifact}

    return _with_current_user(ingest)


def _genomilab_propose_report_facts(params: JsonObject) -> JsonObject:
    proposals = params.get("proposals")
    if not isinstance(proposals, list) or not all(
        isinstance(item, dict) for item in proposals
    ):
        raise OperationError("invalid_params", "proposals must be an object array")
    return _with_current_user(
        lambda store, user_id, _session: {
            "status": "review_required",
            "proposals": store.propose_report_facts(
                user_id,
                artifact_id=_required(params, "artifact_id"),
                proposals=proposals,
                command_id=_required(params, "command_id"),
            ),
        }
    )


def _genomilab_review_report_facts(params: JsonObject) -> JsonObject:
    decisions = params.get("decisions")
    if not isinstance(decisions, list) or not all(
        isinstance(item, dict) for item in decisions
    ):
        raise OperationError("invalid_params", "decisions must be an object array")
    command_id = _required(params, "command_id")
    reviewed_by = _required(params, "reviewed_by")
    payload = {"decisions": decisions, "reviewed_by": reviewed_by}

    def review(store: GenomiLabStore, user_id: str, _session: str) -> JsonObject:
        with store.atomic_write():
            prior = store.get_investigation_command(
                user_id,
                operation="review_report_facts",
                command_id=command_id,
                payload=payload,
            )
            if prior is not None:
                proposal_ids = set(prior.get("proposal_ids") or [])
                reviewed = [
                    item
                    for item in store.list_report_fact_proposals(user_id)
                    if item.get("proposal_id") in proposal_ids
                ]
                return {"status": "reviewed", "proposals": reviewed}
            reviewed = store.review_report_facts(
                user_id, decisions=decisions, reviewed_by=reviewed_by
            )
            store.record_investigation_command(
                user_id,
                operation="review_report_facts",
                command_id=command_id,
                payload=payload,
                result={"proposal_ids": [item["proposal_id"] for item in reviewed]},
            )
        return {"status": "reviewed", "proposals": reviewed}

    return _with_current_user(review)


def _genomilab_prepare_specialist_packet(params: JsonObject) -> JsonObject:
    return _with_current_user(
        lambda store, user_id, session_id: {
            "status": "prepared",
            "packet": store.prepare_specialist_packet(
                user_id,
                workspace_session_id=session_id,
                investigation_id=_required(params, "investigation_id"),
                cycle_id=_required(params, "cycle_id"),
                specialist_role=_required(params, "specialist_role"),
                projection_kind=_required(params, "projection_kind"),
                objective=_required(params, "objective"),
                selected_profile_fact_ids=_string_list(
                    params, "selected_profile_fact_ids"
                ),
                selected_evidence_ids=_string_list(params, "selected_evidence_ids"),
                allowed_provider=_required(params, "allowed_provider"),
                purpose=_required(params, "purpose"),
                command_id=_required(params, "command_id"),
                expected_revision=_required_int(params, "expected_revision"),
            ),
        }
    )


def _genomilab_register_specialist(params: JsonObject) -> JsonObject:
    return _with_current_user(
        lambda store, user_id, _session: {
            "status": "reported",
            "assignment": store.register_panel_assignment(
                user_id,
                investigation_id=_required(params, "investigation_id"),
                cycle_id=_required(params, "cycle_id"),
                packet_id=_required(params, "packet_id"),
                specialist_role=_required(params, "specialist_role"),
                agent_profile=_required(params, "agent_profile"),
                objective=_required(params, "objective"),
                native_subagent_id=_optional(params, "native_subagent_id"),
                status=_optional(params, "status") or "proposed",
                command_id=_required(params, "command_id"),
                expected_revision=_required_int(params, "expected_revision"),
            ),
            "progress_source": "reported_by_main_agent",
        }
    )


def _genomilab_record_specialist_result(params: JsonObject) -> JsonObject:
    finding = params.get("finding")
    if not isinstance(finding, dict):
        raise OperationError("invalid_params", "finding must be an object")
    return _with_current_user(
        lambda store, user_id, _session: {
            "status": "reported",
            "finding": store.record_specialist_finding(
                user_id,
                investigation_id=_required(params, "investigation_id"),
                cycle_id=_required(params, "cycle_id"),
                assignment_id=_required(params, "assignment_id"),
                finding=finding,
                evidence_record_ids=_string_list(params, "evidence_record_ids"),
                status=_optional(params, "status") or "recorded",
                command_id=_required(params, "command_id"),
                expected_revision=_required_int(params, "expected_revision"),
            ),
            "record_kind": "specialist_analysis",
            "progress_source": "reported_by_main_agent",
        }
    )


def _genomilab_record_research_artifact(params: JsonObject) -> JsonObject:
    artifact = params.get("artifact")
    if not isinstance(artifact, dict):
        raise OperationError("invalid_params", "artifact must be an object")
    return _with_current_user(
        lambda store, user_id, _session: {
            "status": "recorded",
            "research_artifact": store.record_research_artifact(
                user_id,
                investigation_id=_required(params, "investigation_id"),
                cycle_id=_required(params, "cycle_id"),
                provider=_required(params, "provider"),
                artifact_kind=_required(params, "artifact_kind"),
                artifact=artifact,
                source_evidence_ids=_string_list(params, "source_evidence_ids"),
                command_id=_required(params, "command_id"),
                expected_revision=_required_int(params, "expected_revision"),
            ),
            "nonclinical": True,
            "hypothesis_effect": "none",
        }
    )


def _genomilab_record_evidence_reference(params: JsonObject) -> JsonObject:
    return _with_current_user(
        lambda store, user_id, _session: {
            "status": "recorded",
            "evidence_reference": store.record_evidence_reference(
                user_id,
                investigation_id=_required(params, "investigation_id"),
                cycle_id=_required(params, "cycle_id"),
                evidence_record_id=_required(params, "evidence_record_id"),
                relationship=_required(params, "relationship"),
                command_id=_required(params, "command_id"),
                expected_revision=_required_int(params, "expected_revision"),
            ),
        }
    )


def _genomilab_capture_evidence_result(params: JsonObject) -> JsonObject:
    investigation_id = _required(params, "investigation_id")
    cycle_id = _required(params, "cycle_id")
    receipt_id = _required(params, "result_receipt_id")
    relationship = _required(params, "relationship")
    command_id = _required(params, "command_id")
    expected_revision = _required_int(params, "expected_revision")
    payload = {
        "investigation_id": investigation_id,
        "cycle_id": cycle_id,
        "result_receipt_id": receipt_id,
        "relationship": relationship,
        "expected_revision": expected_revision,
    }

    def capture(store: GenomiLabStore, user_id: str, session_id: str) -> JsonObject:
        with store.atomic_write():
            prior = store.get_investigation_command(
                user_id,
                operation="capture_evidence_result",
                command_id=command_id,
                payload=payload,
            )
            if prior is not None:
                investigation = _owned_investigation(store, user_id, investigation_id)
                evidence = next(
                    (
                        item
                        for item in investigation.get("evidence_records") or []
                        if item.get("evidence_record_id")
                        == prior.get("evidence_record_id")
                    ),
                    None,
                )
                return {"status": "captured", "evidence_record": evidence}

            cycle = store.get_cycle(cycle_id)
            if (
                cycle.get("user_id") != user_id
                or cycle.get("investigation_id") != investigation_id
                or int(cycle.get("revision") or 0) != expected_revision
            ):
                raise ValueError("investigation cycle revision conflict")
            try:
                receipt = EVIDENCE_RESULT_RECEIPTS.resolve(
                    receipt_id, session_id=session_id
                )
            except EvidenceResultReceiptError as exc:
                raise OperationError(
                    "invalid_evidence_result_receipt", str(exc)
                ) from exc
            result = receipt["result"]
            if not isinstance(result, dict) or not isinstance(
                result.get("evidence_envelope"), dict
            ):
                raise ValueError(
                    "the receipt does not contain canonical Genomi evidence"
                )
            operation = str(receipt["operation"])
            evidence = {
                **result,
                "lab_capture": {
                    "relationship": relationship,
                    "source_operation": operation,
                    "capture_boundary": "opaque_current_session_result_receipt",
                },
            }
            investigation = _owned_investigation(store, user_id, investigation_id)
            evidence_record = store.commit_evidence(
                investigation_id,
                source_family=_evidence_source_family(operation, result),
                operation=operation,
                evidence=evidence,
                deduplication_key=f"captured:{receipt_id}",
                expected_consent_receipt_id=(
                    investigation.get("active_consent_receipt_id")
                    if _result_uses_private_genome(result)
                    else None
                ),
            )
            reference = store.record_evidence_reference(
                user_id,
                investigation_id=investigation_id,
                cycle_id=cycle_id,
                evidence_record_id=evidence_record["evidence_record_id"],
                relationship=relationship,
                command_id=f"{command_id}:reference",
                expected_revision=expected_revision,
            )
            store.record_investigation_command(
                user_id,
                operation="capture_evidence_result",
                command_id=command_id,
                payload=payload,
                result={
                    "evidence_record_id": evidence_record["evidence_record_id"],
                    "investigation_evidence_reference_id": reference[
                        "investigation_evidence_reference_id"
                    ],
                },
            )
        return {
            "status": "captured",
            "evidence_record": evidence_record,
            "evidence_reference": reference,
        }

    return _with_current_user(capture)


def _genomilab_create_evidence_snapshot(params: JsonObject) -> JsonObject:
    investigation_id = _required(params, "investigation_id")
    cycle_id = _required(params, "cycle_id")
    command_id = _required(params, "command_id")
    expected_revision = _required_int(params, "expected_revision")
    reason = _required(params, "reason")
    payload = {
        "investigation_id": investigation_id,
        "cycle_id": cycle_id,
        "reason": reason,
        "expected_revision": expected_revision,
        "force_new": bool(params.get("force_new", False)),
    }

    def create(store: GenomiLabStore, user_id: str, _session: str) -> JsonObject:
        with store.atomic_write():
            prior = store.get_investigation_command(
                user_id,
                operation="create_evidence_snapshot",
                command_id=command_id,
                payload=payload,
            )
            if prior is not None:
                investigation = _owned_investigation(store, user_id, investigation_id)
                snapshot = next(
                    (
                        item
                        for item in investigation.get("evidence_snapshots") or []
                        if item.get("evidence_snapshot_id")
                        == prior.get("evidence_snapshot_id")
                    ),
                    None,
                )
                return {"status": "created", "evidence_snapshot": snapshot}
            cycle = store.get_cycle(cycle_id)
            if (
                cycle.get("user_id") != user_id
                or cycle.get("investigation_id") != investigation_id
                or int(cycle.get("revision") or 0) != expected_revision
            ):
                raise ValueError("investigation cycle revision conflict")
            snapshot = store.create_evidence_snapshot(
                investigation_id,
                reason=reason,
                force_new=bool(params.get("force_new", False)),
            )
            event = store.append_investigation_work_event(
                user_id,
                investigation_id=investigation_id,
                cycle_id=cycle_id,
                event_type="evidence_snapshot_created",
                summary="The main agent pinned an immutable evidence snapshot",
                details={"evidence_snapshot_id": snapshot["evidence_snapshot_id"]},
                command_id=f"{command_id}:event",
                expected_revision=expected_revision,
            )
            store.record_investigation_command(
                user_id,
                operation="create_evidence_snapshot",
                command_id=command_id,
                payload=payload,
                result={"evidence_snapshot_id": snapshot["evidence_snapshot_id"]},
            )
        return {
            "status": "created",
            "evidence_snapshot": snapshot,
            "work_event": event,
        }

    return _with_current_user(create)


def _genomilab_revise_hypothesis(params: JsonObject) -> JsonObject:
    investigation_id = _required(params, "investigation_id")
    cycle_id = _required(params, "cycle_id")
    expected_revision = _required_int(params, "expected_revision")
    command_id = _required(params, "command_id")
    payload = {
        key: params.get(key)
        for key in (
            "investigation_id",
            "cycle_id",
            "kind",
            "title",
            "statement",
            "status",
            "supersedes_hypothesis_id",
            "parent_logical_hypothesis_id",
            "evidence_record_ids",
            "profile_revision_ids",
            "expected_revision",
        )
    }

    def revise(store: GenomiLabStore, user_id: str, _session: str) -> JsonObject:
        with store.atomic_write():
            prior = store.get_investigation_command(
                user_id,
                operation="revise_hypothesis",
                command_id=command_id,
                payload=payload,
            )
            if prior is not None:
                investigation = _owned_investigation(store, user_id, investigation_id)
                hypothesis = next(
                    (
                        item
                        for item in investigation.get("hypotheses") or []
                        if item.get("hypothesis_id") == prior.get("hypothesis_id")
                    ),
                    None,
                )
                return {"status": "recorded", "hypothesis": hypothesis}
            cycle = store.get_cycle(cycle_id)
            if (
                cycle.get("user_id") != user_id
                or cycle.get("investigation_id") != investigation_id
            ):
                raise KeyError(cycle_id)
            if int(cycle.get("revision") or 0) != expected_revision:
                raise ValueError("investigation cycle revision conflict")
            hypothesis = store.commit_hypothesis(
                investigation_id,
                kind=_required(params, "kind"),
                title=_optional(params, "title"),
                statement=_required(params, "statement"),
                status=_optional(params, "status") or "candidate",
                evidence_record_ids=_string_list(params, "evidence_record_ids"),
                profile_revision_ids=_string_list(params, "profile_revision_ids"),
                supersedes_hypothesis_id=_optional(params, "supersedes_hypothesis_id"),
                parent_logical_hypothesis_id=_optional(
                    params, "parent_logical_hypothesis_id"
                ),
            )
            event = store.append_investigation_work_event(
                user_id,
                investigation_id=investigation_id,
                cycle_id=cycle_id,
                event_type="hypothesis_revised",
                summary="The main agent recorded a hypothesis revision",
                details={
                    "hypothesis_id": hypothesis["hypothesis_id"],
                    "logical_hypothesis_id": hypothesis["logical_hypothesis_id"],
                    "status": hypothesis["status"],
                },
                command_id=f"{command_id}:event",
                expected_revision=expected_revision,
            )
            store.record_investigation_command(
                user_id,
                operation="revise_hypothesis",
                command_id=command_id,
                payload=payload,
                result={
                    "hypothesis_id": hypothesis["hypothesis_id"],
                    "work_event_id": event["work_event_id"],
                },
            )
        return {
            "status": "recorded",
            "hypothesis": hypothesis,
            "work_event": event,
        }

    return _with_current_user(revise)


def _genomilab_publish_brief(params: JsonObject) -> JsonObject:
    brief = params.get("brief")
    if not isinstance(brief, dict):
        raise OperationError("invalid_params", "brief must be an object")
    investigation_id = _required(params, "investigation_id")
    cycle_id = _required(params, "cycle_id")
    expected_revision = _required_int(params, "expected_revision")
    command_id = _required(params, "command_id")
    payload = {
        "investigation_id": investigation_id,
        "cycle_id": cycle_id,
        "expected_revision": expected_revision,
        "brief": brief,
    }

    def publish(store: GenomiLabStore, user_id: str, _session: str) -> JsonObject:
        with store.atomic_write():
            prior = store.get_investigation_command(
                user_id,
                operation="publish_brief",
                command_id=command_id,
                payload=payload,
            )
            if prior is not None:
                investigation = _owned_investigation(store, user_id, investigation_id)
                saved = next(
                    (
                        item
                        for item in investigation.get("brief_versions") or []
                        if item.get("brief_version_id") == prior.get("brief_version_id")
                    ),
                    None,
                )
                return {"status": "published", "brief_version": saved}
            cycle = store.get_cycle(cycle_id)
            if (
                cycle.get("user_id") != user_id
                or cycle.get("investigation_id") != investigation_id
            ):
                raise KeyError(cycle_id)
            if int(cycle.get("revision") or 0) != expected_revision:
                raise ValueError("investigation cycle revision conflict")
            version = store.commit_brief(investigation_id, brief)
            store.record_investigation_command(
                user_id,
                operation="publish_brief",
                command_id=command_id,
                payload=payload,
                result={"brief_version_id": version["brief_version_id"]},
            )
        return {"status": "published", "brief_version": version}

    return _with_current_user(publish)


def _genomilab_record_information_gap(params: JsonObject) -> JsonObject:
    return _cycle_text_result(
        params,
        "gap",
        lambda store, user_id: store.record_information_gap(
            user_id,
            investigation_id=_required(params, "investigation_id"),
            cycle_id=_required(params, "cycle_id"),
            description=_required(params, "description"),
            importance=_optional(params, "importance"),
            command_id=_required(params, "command_id"),
            expected_revision=_required_int(params, "expected_revision"),
        ),
    )


def _genomilab_record_patient_question(params: JsonObject) -> JsonObject:
    return _cycle_text_result(
        params,
        "patient_question",
        lambda store, user_id: store.record_patient_question(
            user_id,
            investigation_id=_required(params, "investigation_id"),
            cycle_id=_required(params, "cycle_id"),
            question=_required(params, "question"),
            rationale=_optional(params, "rationale"),
            command_id=_required(params, "command_id"),
            expected_revision=_required_int(params, "expected_revision"),
        ),
    )


def _genomilab_record_recommended_next_step(params: JsonObject) -> JsonObject:
    return _cycle_text_result(
        params,
        "recommended_next_step",
        lambda store, user_id: store.record_recommended_next_step(
            user_id,
            investigation_id=_required(params, "investigation_id"),
            cycle_id=_required(params, "cycle_id"),
            recommendation=_required(params, "recommendation"),
            rationale=_optional(params, "rationale"),
            priority=_optional(params, "priority") or "medium",
            command_id=_required(params, "command_id"),
            expected_revision=_required_int(params, "expected_revision"),
        ),
    )


def _genomilab_complete_cycle(params: JsonObject) -> JsonObject:
    return _with_current_user(
        lambda store, user_id, _session: {
            "status": "completed",
            "cycle": store.complete_cycle(
                user_id,
                cycle_id=_required(params, "cycle_id"),
                command_id=_required(params, "command_id"),
                expected_revision=_required_int(params, "expected_revision"),
            ),
        }
    )


def _describe_workspace(
    store: GenomiLabStore, user_id: str, _session_id: str
) -> JsonObject:
    try:
        workspace = store.get_workspace(user_id)
    except KeyError:
        return {
            "status": "setup_required",
            "profile": {"observation_count": 0},
            "investigations": [],
            "portal_binding": None,
        }
    investigations = store.list_investigations(user_id)
    binding = None
    project_id = os.environ.get(PORTAL_PROJECT_ENV, "").strip()
    frame_id = os.environ.get(PORTAL_FRAME_ENV, "").strip()
    if project_id and frame_id:
        try:
            binding = store.get_investigation_binding(
                project_id, frame_id, user_id=user_id
            )
        except KeyError:
            pass
    return {
        "status": "ready",
        "profile": {
            "observation_count": len(workspace["profile"].get("observations") or []),
            "source_artifact_count": len(
                workspace["profile"].get("source_artifacts") or []
            ),
        },
        "investigations": [_investigation_summary(item) for item in investigations],
        "portal_binding": binding,
    }


def _investigation_summary(value: JsonObject) -> JsonObject:
    return {
        key: value.get(key)
        for key in (
            "investigation_id",
            "question",
            "disease_scope",
            "status",
            "domain_revision",
            "updated_at",
        )
    }


def _cycle_text_result(
    _params: JsonObject,
    key: str,
    action: Callable[[GenomiLabStore, str], JsonObject],
) -> JsonObject:
    return _with_current_user(
        lambda store, user_id, _session: {
            "status": "recorded",
            key: action(store, user_id),
        }
    )


def _with_current_user(
    action: Callable[[GenomiLabStore, str, str], JsonObject],
) -> JsonObject:
    try:
        with _authorized_store() as (store, user_id, session_id):
            return action(store, user_id, session_id)
    except OperationError:
        raise
    except KeyError as exc:
        raise OperationError("genomilab_record_not_found", str(exc)) from exc
    except ValueError as exc:
        raise OperationError("invalid_genomilab_request", str(exc)) from exc


@contextmanager
def _authorized_store() -> Iterator[tuple[GenomiLabStore, str, str]]:
    with context_authority_lock():
        context = describe_context()
        user_id = str(context.get("active_user_id") or "").strip()
        if not user_id:
            raise OperationError(
                "genomi_user_required",
                "Select the project user before using GenomiLab records.",
            )
        scope = context_scope()
        session_id = str(scope.get("id") or "").strip()
        if not session_id:
            raise OperationError(
                "genomilab_session_required",
                "GenomiLab requires the stable project/frame session boundary.",
            )
        store = GenomiLabStore()

        def require_same_user() -> None:
            current = str(describe_context().get("active_user_id") or "").strip()
            if current != user_id:
                raise ValueError("the active project user changed during the operation")

        with store.current_user_authority_guard(require_same_user):
            yield store, user_id, session_id


def _ensure_workspace(store: GenomiLabStore, user_id: str) -> None:
    try:
        store.get_workspace(user_id)
    except KeyError:
        store.open_workspace(user_id)


def _owned_investigation(
    store: GenomiLabStore, user_id: str, investigation_id: str
) -> JsonObject:
    investigation = store.get_investigation(investigation_id)
    if str(investigation.get("user_id") or "") != user_id:
        raise KeyError(investigation_id)
    return investigation


def _portal_scope() -> tuple[str, str]:
    project_id = os.environ.get(PORTAL_PROJECT_ENV, "").strip()
    frame_id = os.environ.get(PORTAL_FRAME_ENV, "").strip()
    if not project_id or not frame_id:
        raise OperationError(
            "genomilab_portal_scope_required",
            "Start investigations from a GenomiLab Research workspace conversation.",
        )
    return project_id, frame_id


def _required(params: JsonObject, key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OperationError("invalid_params", f"{key} is required")
    return value.strip()


def _optional(params: JsonObject, key: str) -> str | None:
    value = params.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise OperationError("invalid_params", f"{key} must be a string")
    return value.strip() or None


def _required_int(params: JsonObject, key: str) -> int:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise OperationError("invalid_params", f"{key} must be a positive integer")
    return value


def _optional_int(params: JsonObject, key: str) -> int | None:
    if params.get(key) is None:
        return None
    return _required_int(params, key)


def _evidence_source_family(operation: str, result: JsonObject) -> str:
    if _result_uses_private_genome(result):
        return "active_genome_index"
    namespace = operation.split(".", 1)[0].strip()
    return namespace or "genomi"


def _result_uses_private_genome(value: object) -> bool:
    private_keys = {
        "agi_id",
        "agi_snapshot_id",
        "active_agi_id",
        "active_genome_index",
        "active_genome_index_readiness",
    }
    if isinstance(value, dict):
        if private_keys.intersection(value):
            return True
        return any(_result_uses_private_genome(item) for item in value.values())
    if isinstance(value, list):
        return any(_result_uses_private_genome(item) for item in value)
    return False


def _string_list(params: JsonObject, key: str) -> list[str]:
    value = params.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise OperationError("invalid_params", f"{key} must be a string array")
    return [item.strip() for item in value]


def _props(*names: str) -> JsonObject:
    result: JsonObject = {}
    for name in names:
        result[name] = INTEGER if name == "expected_revision" else STRING
    return result


def _write_schema(*names: str, required: tuple[str, ...]) -> JsonObject:
    return object_schema(_props(*names), required=required)


GENOMILAB_OPERATIONS: tuple[ApplicationOperation, ...] = (
    ApplicationOperation(
        "lab.describe_workspace",
        _genomilab_describe_workspace,
        "Describe the current project/frame-bound GenomiLab workspace without exposing raw profile data.",
        object_schema({}),
        produces=("genomilab_workspace",),
    ),
    ApplicationOperation(
        "lab.list_investigations",
        _genomilab_list_investigations,
        "List investigations owned by the active project user.",
        object_schema({}),
        produces=("investigation_summaries",),
    ),
    ApplicationOperation(
        "lab.read_investigation",
        _genomilab_read_investigation,
        "Read the recorded investigation board for the active project user.",
        object_schema({"investigation_id": STRING}, required=("investigation_id",)),
        produces=("investigation_board",),
    ),
    ApplicationOperation(
        "lab.start_investigation",
        _genomilab_start_investigation,
        "Idempotently start and bind an investigation to the current portal project and frame.",
        object_schema(
            {"question": STRING, "disease_scope": STRING, "command_id": STRING},
            required=("question", "command_id"),
        ),
        mutating=True,
        produces=("investigation", "portal_binding"),
    ),
    ApplicationOperation(
        "lab.start_cycle",
        _genomilab_start_cycle,
        "Idempotently start a host-neutral investigation cycle.",
        _write_schema(
            "investigation_id",
            "objective",
            "patient_molecular_snapshot_id",
            "expected_revision",
            "command_id",
            required=(
                "investigation_id",
                "objective",
                "expected_revision",
                "command_id",
            ),
        ),
        mutating=True,
        produces=("investigation_cycle",),
    ),
    ApplicationOperation(
        "lab.preview_profile_access",
        _genomilab_preview_profile_access,
        "Preview the exact stored profile facts proposed for this investigation.",
        object_schema(
            {
                "investigation_id": STRING,
                "purpose": STRING,
                "observation_revision_ids": STRING_ARRAY,
            },
            required=(
                "investigation_id",
                "purpose",
                "observation_revision_ids",
            ),
        ),
        produces=("profile_access_candidate",),
    ),
    ApplicationOperation(
        "lab.approve_profile_access",
        _genomilab_approve_profile_access,
        "Approve the exact previewed profile snapshot for this project/frame session.",
        object_schema(
            {
                "investigation_id": STRING,
                "purpose": STRING,
                "observation_revision_ids": STRING_ARRAY,
                "candidate_sha256": STRING,
                "approved": {"type": "boolean"},
                "refresh": {"type": "boolean", "default": False},
                "expected_base_patient_molecular_snapshot_id": STRING,
                "command_id": STRING,
            },
            required=(
                "investigation_id",
                "purpose",
                "observation_revision_ids",
                "candidate_sha256",
                "approved",
                "command_id",
            ),
        ),
        mutating=True,
        produces=("profile_snapshot", "consent_receipt"),
    ),
    ApplicationOperation(
        "lab.revoke_profile_access",
        _genomilab_revoke_profile_access,
        "Revoke the investigation's active profile approval for this session.",
        _write_schema(
            "investigation_id",
            "expected_revision",
            "command_id",
            required=("investigation_id", "expected_revision", "command_id"),
        ),
        mutating=True,
        produces=("revoked_profile_access",),
    ),
    ApplicationOperation(
        "lab.read_approved_profile",
        _genomilab_read_approved_profile,
        "Read only the exact profile snapshot approved for this investigation session.",
        object_schema({"investigation_id": STRING}, required=("investigation_id",)),
        produces=("approved_profile",),
    ),
    ApplicationOperation(
        "lab.list_profile_updates",
        _genomilab_list_profile_updates,
        "List immutable profile snapshots and deltas for this investigation.",
        object_schema({"investigation_id": STRING}, required=("investigation_id",)),
        produces=("profile_snapshot_updates",),
    ),
    ApplicationOperation(
        "lab.ingest_report",
        _genomilab_ingest_report,
        "Store report bytes inside the authenticated encrypted Lab container and return only redacted metadata.",
        object_schema(
            {
                "content_base64": STRING,
                "source_type": STRING,
                "title": STRING,
                "media_type": STRING,
                "source_identifier": STRING,
                "issued_at": STRING,
                "command_id": STRING,
            },
            required=(
                "content_base64",
                "source_type",
                "title",
                "media_type",
                "command_id",
            ),
        ),
        mutating=True,
        produces=("encrypted_report_record",),
    ),
    ApplicationOperation(
        "lab.propose_report_facts",
        _genomilab_propose_report_facts,
        "Record extracted report facts as proposals that cannot enter the patient profile before review.",
        object_schema(
            {
                "artifact_id": STRING,
                "proposals": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                },
                "command_id": STRING,
            },
            required=("artifact_id", "proposals", "command_id"),
        ),
        mutating=True,
        produces=("report_fact_proposals",),
    ),
    ApplicationOperation(
        "lab.review_report_facts",
        _genomilab_review_report_facts,
        "Accept, edit, or reject proposed report facts before creating immutable profile observations.",
        object_schema(
            {
                "decisions": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                },
                "reviewed_by": STRING,
                "command_id": STRING,
            },
            required=("decisions", "reviewed_by", "command_id"),
        ),
        mutating=True,
        produces=("reviewed_report_facts", "profile_observations"),
    ),
    ApplicationOperation(
        "lab.prepare_specialist_packet",
        _genomilab_prepare_specialist_packet,
        "Validate stored IDs and persist an exact minimized specialist disclosure packet.",
        object_schema(
            {
                **_props(
                    "investigation_id",
                    "cycle_id",
                    "specialist_role",
                    "projection_kind",
                    "objective",
                    "allowed_provider",
                    "purpose",
                    "expected_revision",
                    "command_id",
                ),
                "selected_profile_fact_ids": STRING_ARRAY,
                "selected_evidence_ids": STRING_ARRAY,
            },
            required=(
                "investigation_id",
                "cycle_id",
                "specialist_role",
                "projection_kind",
                "objective",
                "selected_profile_fact_ids",
                "selected_evidence_ids",
                "allowed_provider",
                "purpose",
                "expected_revision",
                "command_id",
            ),
        ),
        mutating=True,
        produces=("specialist_packet", "disclosure_receipt"),
    ),
    ApplicationOperation(
        "lab.register_specialist",
        _genomilab_register_specialist,
        "Record specialist assignment status reported by the main agent.",
        _write_schema(
            "investigation_id",
            "cycle_id",
            "packet_id",
            "specialist_role",
            "agent_profile",
            "objective",
            "native_subagent_id",
            "status",
            "expected_revision",
            "command_id",
            required=(
                "investigation_id",
                "cycle_id",
                "packet_id",
                "specialist_role",
                "agent_profile",
                "objective",
                "expected_revision",
                "command_id",
            ),
        ),
        mutating=True,
        produces=("panel_assignment",),
    ),
    ApplicationOperation(
        "lab.record_specialist_result",
        _genomilab_record_specialist_result,
        "Record specialist analysis separately from source evidence.",
        object_schema(
            {
                **_props(
                    "investigation_id",
                    "cycle_id",
                    "assignment_id",
                    "status",
                    "expected_revision",
                    "command_id",
                ),
                "finding": {"type": "object", "additionalProperties": True},
                "evidence_record_ids": STRING_ARRAY,
            },
            required=(
                "investigation_id",
                "cycle_id",
                "assignment_id",
                "finding",
                "evidence_record_ids",
                "expected_revision",
                "command_id",
            ),
        ),
        mutating=True,
        produces=("specialist_finding",),
    ),
    ApplicationOperation(
        "lab.record_research_artifact",
        _genomilab_record_research_artifact,
        "Record a typed nonclinical ESM, Proto, or Genomi sequence artifact without changing the patient hypothesis board.",
        object_schema(
            {
                **_props(
                    "investigation_id",
                    "cycle_id",
                    "provider",
                    "artifact_kind",
                    "expected_revision",
                    "command_id",
                ),
                "artifact": {"type": "object", "additionalProperties": True},
                "source_evidence_ids": STRING_ARRAY,
            },
            required=(
                "investigation_id",
                "cycle_id",
                "provider",
                "artifact_kind",
                "artifact",
                "source_evidence_ids",
                "expected_revision",
                "command_id",
            ),
        ),
        mutating=True,
        produces=("nonclinical_research_artifact",),
    ),
    ApplicationOperation(
        "lab.record_evidence_reference",
        _genomilab_record_evidence_reference,
        "Attach one stored evidence record to the current investigation cycle.",
        _write_schema(
            "investigation_id",
            "cycle_id",
            "evidence_record_id",
            "relationship",
            "expected_revision",
            "command_id",
            required=(
                "investigation_id",
                "cycle_id",
                "evidence_record_id",
                "relationship",
                "expected_revision",
                "command_id",
            ),
        ),
        mutating=True,
        produces=("investigation_evidence_reference",),
    ),
    ApplicationOperation(
        "lab.capture_evidence_result",
        _genomilab_capture_evidence_result,
        "Capture an exact current-session Genomi result by opaque receipt and attach it to the investigation cycle.",
        _write_schema(
            "investigation_id",
            "cycle_id",
            "result_receipt_id",
            "relationship",
            "expected_revision",
            "command_id",
            required=(
                "investigation_id",
                "cycle_id",
                "result_receipt_id",
                "relationship",
                "expected_revision",
                "command_id",
            ),
        ),
        mutating=True,
        produces=("evidence_record", "investigation_evidence_reference"),
    ),
    ApplicationOperation(
        "lab.create_evidence_snapshot",
        _genomilab_create_evidence_snapshot,
        "Pin the current evidence ledger and approved molecular context for longitudinal synthesis.",
        object_schema(
            {
                **_props(
                    "investigation_id",
                    "cycle_id",
                    "reason",
                    "expected_revision",
                    "command_id",
                ),
                "force_new": {"type": "boolean", "default": False},
            },
            required=(
                "investigation_id",
                "cycle_id",
                "reason",
                "expected_revision",
                "command_id",
            ),
        ),
        mutating=True,
        produces=("evidence_snapshot",),
    ),
    ApplicationOperation(
        "lab.revise_hypothesis",
        _genomilab_revise_hypothesis,
        "Persist an evidence-anchored hypothesis revision for this cycle.",
        object_schema(
            {
                **_props(
                    "investigation_id",
                    "cycle_id",
                    "kind",
                    "title",
                    "statement",
                    "status",
                    "supersedes_hypothesis_id",
                    "parent_logical_hypothesis_id",
                    "expected_revision",
                    "command_id",
                ),
                "evidence_record_ids": STRING_ARRAY,
                "profile_revision_ids": STRING_ARRAY,
            },
            required=(
                "investigation_id",
                "cycle_id",
                "kind",
                "statement",
                "evidence_record_ids",
                "profile_revision_ids",
                "expected_revision",
                "command_id",
            ),
        ),
        mutating=True,
        produces=("hypothesis_version",),
    ),
    ApplicationOperation(
        "lab.record_information_gap",
        _genomilab_record_information_gap,
        "Record missing information without presenting it as negative evidence.",
        _write_schema(
            "investigation_id",
            "cycle_id",
            "description",
            "importance",
            "expected_revision",
            "command_id",
            required=(
                "investigation_id",
                "cycle_id",
                "description",
                "expected_revision",
                "command_id",
            ),
        ),
        mutating=True,
        produces=("information_gap",),
    ),
    ApplicationOperation(
        "lab.record_patient_question",
        _genomilab_record_patient_question,
        "Record a question for the patient to answer in the existing chat.",
        _write_schema(
            "investigation_id",
            "cycle_id",
            "question",
            "rationale",
            "expected_revision",
            "command_id",
            required=(
                "investigation_id",
                "cycle_id",
                "question",
                "expected_revision",
                "command_id",
            ),
        ),
        mutating=True,
        produces=("patient_question",),
    ),
    ApplicationOperation(
        "lab.record_recommended_next_step",
        _genomilab_record_recommended_next_step,
        "Record an informational next step reported by the main agent.",
        _write_schema(
            "investigation_id",
            "cycle_id",
            "recommendation",
            "rationale",
            "priority",
            "expected_revision",
            "command_id",
            required=(
                "investigation_id",
                "cycle_id",
                "recommendation",
                "expected_revision",
                "command_id",
            ),
        ),
        mutating=True,
        produces=("recommended_next_step",),
    ),
    ApplicationOperation(
        "lab.complete_cycle",
        _genomilab_complete_cycle,
        "Idempotently complete the active investigation cycle at its expected revision.",
        _write_schema(
            "cycle_id",
            "expected_revision",
            "command_id",
            required=("cycle_id", "expected_revision", "command_id"),
        ),
        mutating=True,
        produces=("investigation_cycle",),
    ),
    ApplicationOperation(
        "lab.publish_brief",
        _genomilab_publish_brief,
        "Publish an immutable evidence-anchored Investigation Brief version.",
        object_schema(
            {
                "investigation_id": STRING,
                "cycle_id": STRING,
                "brief": {"type": "object", "additionalProperties": True},
                "expected_revision": INTEGER,
                "command_id": STRING,
            },
            required=(
                "investigation_id",
                "cycle_id",
                "brief",
                "expected_revision",
                "command_id",
            ),
        ),
        mutating=True,
        produces=("brief_version",),
    ),
)


__all__ = ["GENOMILAB_OPERATIONS"]
