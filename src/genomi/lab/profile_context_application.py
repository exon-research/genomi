"""Private profile snapshot approval and scoped genome execution."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable

from .agi_authority import (
    AgiAuthorizationHandle,
    InvestigationAgiAuthorizationError,
    issue_investigation_agi_authorization,
    revoke_investigation_agi_authorization,
    revoke_investigation_agi_authorizations_for_investigation,
    validate_investigation_agi_authorization_binding,
)
from .context_candidate_receipts import ContextCandidateReceiptIssuer
from .evidence_store import EvidenceCommitGuardError
from .genomic_scope import normalize_investigation_genomic_scope
from .models import JsonObject, compact_json, validate_private_payload
from .service_errors import LabError
from .store import GenomiLabStore


_PROFILE_SNAPSHOT_CANDIDATE_FIELDS = frozenset(
    {
        "purpose",
        "observation_revision_ids",
        "artifact_ids",
        "specimen_ids",
        "assay_ids",
        "include_genome",
        "use_current_agi",
        "genomic_scope",
    }
)
_PROFILE_SNAPSHOT_APPROVAL_FIELDS = frozenset(
    {
        "purpose",
        "observation_revision_ids",
        "artifact_ids",
        "specimen_ids",
        "assay_ids",
        "agi_id",
        "agi_snapshot_id",
        "genomic_scope",
        "candidate_sha256",
        "candidate_receipt",
        "approved",
        "refresh",
    }
)


def require_observation_revision_selection(
    payload: JsonObject, *, error_code: str
) -> list[str]:
    value = payload.get("observation_revision_ids")
    if not isinstance(value, list) or not value:
        raise LabError(
            error_code,
            "Select at least one molecular-profile observation for this investigation.",
        )
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise LabError(
            error_code,
            "Every selected molecular-profile observation must have a valid revision ID.",
        )
    revisions = [item.strip() for item in value]
    if len(revisions) != len(set(revisions)):
        raise LabError(
            error_code,
            "Each molecular-profile observation may be selected only once.",
        )
    return revisions


@dataclass(slots=True)
class ProfileContextApplication:
    store: GenomiLabStore
    session_id: str
    current_context: Callable[[], tuple[JsonObject, str]]
    investigation: Callable[[str], JsonObject]
    accepted_plan: Callable[[str], JsonObject]
    active_receipt: Callable[[JsonObject, JsonObject], JsonObject]
    authorized_call: Callable[[str, JsonObject, AgiAuthorizationHandle], JsonObject]
    safe_call: Callable[[str, JsonObject], JsonObject]
    candidate_receipts: ContextCandidateReceiptIssuer
    authorizations: dict[str, AgiAuthorizationHandle]

    def profile_snapshot_candidate(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        self._validate_payload(
            payload,
            allowed_fields=_PROFILE_SNAPSHOT_CANDIDATE_FIELDS,
            error_code="invalid_context_selection",
            operation="context candidate",
        )
        selected = require_observation_revision_selection(
            payload, error_code="invalid_context_selection"
        )
        context, user_id = self.current_context()
        active = context.get("active_genome_index")
        active_agi_id = str(context.get("active_agi_id") or "") or None
        active_snapshot = (
            str(active.get("agi_snapshot_id") or "") or None
            if isinstance(active, dict)
            else None
        )
        try:
            investigation = self.store.get_investigation(investigation_id)
        except KeyError as exc:
            raise LabError(
                "investigation_not_found", "Investigation not found.", http_status=404
            ) from exc
        current_snapshot_id = str(
            investigation.get("patient_molecular_snapshot_id") or ""
        )
        pinned = (
            self.store.get_profile_snapshot(current_snapshot_id)
            if current_snapshot_id
            else None
        )
        use_current_agi = payload.get("use_current_agi", False)
        if not isinstance(use_current_agi, bool):
            raise LabError(
                "invalid_context_selection", "use_current_agi must be a boolean"
            )
        default_agi_id = (
            active_agi_id
            if use_current_agi or not isinstance(pinned, dict)
            else pinned.get("agi_id")
        )
        default_snapshot = (
            active_snapshot
            if use_current_agi or not isinstance(pinned, dict)
            else pinned.get("agi_snapshot_id")
        )
        include_genome = payload.get("include_genome", bool(default_agi_id))
        if not isinstance(include_genome, bool):
            raise LabError(
                "invalid_context_selection", "include_genome must be a boolean"
            )
        agi_id = default_agi_id if include_genome else None
        agi_snapshot_id = default_snapshot if include_genome else None
        genomic_scope = payload.get("genomic_scope")
        if (
            agi_id
            and genomic_scope is None
            and isinstance(pinned, dict)
            and not use_current_agi
        ):
            genomic_scope = pinned.get("genomic_scope")
        if agi_id:
            scope_context: JsonObject = active if isinstance(active, dict) else {}
            if isinstance(genomic_scope, dict) and genomic_scope.get("genome_build"):
                scope_context = {"genome_build": genomic_scope["genome_build"]}
            genomic_scope = self._normalized_scope(genomic_scope, scope_context)
        try:
            return self.store.profile_snapshot_candidate(
                user_id,
                investigation_id=investigation_id,
                purpose=payload.get("purpose"),
                observation_revision_ids=selected,
                artifact_ids=payload.get("artifact_ids"),
                specimen_ids=payload.get("specimen_ids"),
                assay_ids=payload.get("assay_ids"),
                agi_id=agi_id,
                agi_snapshot_id=agi_snapshot_id,
                genomic_scope=genomic_scope,
            )
        except (KeyError, ValueError) as exc:
            raise LabError("invalid_context_selection", str(exc)) from exc

    def approve(
        self,
        investigation_id: str,
        payload: JsonObject,
        *,
        authorization_before_commit: Callable[[JsonObject], JsonObject] | None = None,
    ) -> JsonObject:
        self._validate_payload(
            payload,
            allowed_fields=_PROFILE_SNAPSHOT_APPROVAL_FIELDS,
            error_code="invalid_context_approval",
            operation="context approval",
        )
        selected = require_observation_revision_selection(
            payload, error_code="invalid_context_approval"
        )
        context, user_id = self.current_context()
        candidate_receipt = self.candidate_receipts.validate(
            investigation_id=investigation_id,
            user_id=user_id,
            payload=payload,
            current_context=context,
        )
        try:
            prior = self.store.get_investigation(investigation_id)
        except KeyError as exc:
            raise LabError(
                "investigation_not_found", "Investigation not found.", http_status=404
            ) from exc
        active = context.get("active_genome_index")
        active_agi_id = str(context.get("active_agi_id") or "") or None
        agi_snapshot_id = (
            str(active.get("agi_snapshot_id") or "") or None
            if isinstance(active, dict)
            else None
        )
        requested_agi_id = payload.get("agi_id", active_agi_id)
        requested_snapshot = payload.get("agi_snapshot_id", agi_snapshot_id)
        genomic_scope = payload.get("genomic_scope")
        if requested_agi_id:
            scope_context: JsonObject = active if isinstance(active, dict) else {}
            if isinstance(genomic_scope, dict) and genomic_scope.get("genome_build"):
                scope_context = {"genome_build": genomic_scope["genome_build"]}
            genomic_scope = self._normalized_scope(genomic_scope, scope_context)
        staged_handle: AgiAuthorizationHandle | None = None
        staged_authorization: JsonObject | None = None
        evidence_snapshot: JsonObject | None = None

        def issue_before_commit(claims: JsonObject) -> None:
            nonlocal staged_authorization, staged_handle
            if requested_agi_id and requested_snapshot:
                staged_handle = issue_investigation_agi_authorization(
                    workspace_session_id=str(claims["workspace_session_id"]),
                    user_id=str(claims["user_id"]),
                    investigation_id=str(claims["investigation_id"]),
                    patient_molecular_snapshot_id=str(
                        claims["patient_molecular_snapshot_id"]
                    ),
                    consent_receipt_id=str(claims["consent_receipt_id"]),
                    agi_id=str(claims["agi_id"]),
                    agi_snapshot_id=str(claims["agi_snapshot_id"]),
                    purpose=str(claims["purpose"]),
                    genomic_scope=claims["genomic_scope"],
                )
            if authorization_before_commit is not None:
                staged_authorization = authorization_before_commit(dict(claims))

        try:
            with self.store.atomic_write():
                snapshot = self.store.create_profile_snapshot(
                    user_id,
                    workspace_session_id=self.session_id,
                    investigation_id=investigation_id,
                    purpose=payload.get("purpose"),
                    observation_revision_ids=selected,
                    artifact_ids=payload.get("artifact_ids"),
                    specimen_ids=payload.get("specimen_ids"),
                    assay_ids=payload.get("assay_ids"),
                    agi_id=requested_agi_id,
                    agi_snapshot_id=requested_snapshot,
                    genomic_scope=genomic_scope,
                    candidate_sha256=payload.get("candidate_sha256"),
                    approved=payload.get("approved"),
                    refresh=payload.get("refresh", False),
                    expected_base_patient_molecular_snapshot_id=(
                        candidate_receipt.get("base_patient_molecular_snapshot_id")
                        or None
                    ),
                    authorization_before_commit=(
                        issue_before_commit
                        if (
                            requested_agi_id
                            and requested_snapshot
                            or authorization_before_commit is not None
                        )
                        else None
                    ),
                )
                if snapshot.get("context_change") == "profile_refreshed":
                    evidence_snapshot = self.store.create_evidence_snapshot(
                        investigation_id,
                        reason="approved_profile_context_refresh",
                        force_new=True,
                    )
                    self.store.set_investigation_status(
                        investigation_id, "awaiting_plan"
                    )
                lifecycle = self.store.get_investigation(investigation_id).get(
                    "refresh_lifecycle"
                )
        except InvestigationAgiAuthorizationError as exc:
            if staged_handle is not None:
                revoke_investigation_agi_authorization(staged_handle)
            raise LabError(exc.code, str(exc), http_status=409) from exc
        except (KeyError, ValueError) as exc:
            if staged_handle is not None:
                revoke_investigation_agi_authorization(staged_handle)
            raise LabError("invalid_context_approval", str(exc)) from exc
        except Exception:
            if staged_handle is not None:
                revoke_investigation_agi_authorization(staged_handle)
            raise
        self.candidate_receipts.discard_investigation(investigation_id)
        if requested_agi_id and requested_snapshot:
            if staged_handle is None:
                raise RuntimeError(
                    "profile snapshot committed without its AGI authorization"
                )
            revoke_investigation_agi_authorizations_for_investigation(
                user_id=user_id,
                investigation_id=investigation_id,
                except_handle=staged_handle,
            )
            self.authorizations.pop(investigation_id, None)
            self.authorizations[investigation_id] = staged_handle
        else:
            revoke_investigation_agi_authorizations_for_investigation(
                user_id=user_id,
                investigation_id=investigation_id,
            )
            self.authorizations.pop(investigation_id, None)
        result = {
            **snapshot,
            "previous_patient_molecular_snapshot_id": prior.get(
                "patient_molecular_snapshot_id"
            ),
            "evidence_snapshot": evidence_snapshot,
            "brief_refresh_required": bool(evidence_snapshot),
            "refresh_lifecycle": lifecycle,
            "private_genome_access": (
                "authorized_for_exact_scope"
                if investigation_id in self.authorizations
                else "not_included"
            ),
        }
        if staged_authorization is not None:
            result["investigation_authorization"] = staged_authorization
        return result

    def invoke_genome(
        self,
        investigation_id: str,
        *,
        operation: str,
        params: JsonObject,
        evidence_context: JsonObject | None = None,
        expected_plan_version_id: str | None = None,
        expected_consent_receipt_id: str | None = None,
    ) -> JsonObject:
        snapshot, handle = self.require_genome_context(investigation_id)
        if (
            expected_plan_version_id is not None
            or expected_consent_receipt_id is not None
        ):
            current = self.accepted_plan(investigation_id)
            current_plan = current.get("current_plan_version")
            current_receipt = self.active_receipt(current, snapshot)
            if (
                not isinstance(current_plan, dict)
                or current_plan.get("plan_version_id") != expected_plan_version_id
                or current_receipt.get("consent_receipt_id")
                != expected_consent_receipt_id
            ):
                raise LabError(
                    "private_context_renewal_required",
                    "The accepted plan or molecular-context consent changed before Genomi ran.",
                    http_status=409,
                )
        if evidence_context is not None:
            if not isinstance(evidence_context, dict):
                raise LabError(
                    "invalid_genome_evidence_context",
                    "Genome evidence context must be an object.",
                    http_status=409,
                )
            try:
                validate_private_payload(evidence_context)
            except ValueError as exc:
                raise LabError(
                    "invalid_genome_evidence_context", str(exc), http_status=409
                ) from exc
        result = self.authorized_call(operation, params, handle)
        if result.get("status") == "in_progress":
            job_id, resume_operation, poll_after = self._background_job_binding(result)
            return {
                "status": "in_progress",
                "job_id": job_id,
                "resume_operation": resume_operation,
                **(
                    {"poll_after_seconds": poll_after}
                    if poll_after is not None
                    else {}
                ),
            }
        committed_result = dict(result)
        if evidence_context is not None:
            committed_result["genomilab_context"] = dict(evidence_context)
        deduplication_key = hashlib.sha256(
            compact_json(
                {
                    "operation": operation,
                    "params": params,
                    "genomilab_context": evidence_context,
                    "agi_snapshot_id": snapshot.get("agi_snapshot_id"),
                }
            ).encode("utf-8")
        ).hexdigest()
        try:
            evidence = self.store.commit_evidence(
                investigation_id,
                source_family="personal_genome",
                operation=operation,
                evidence=committed_result,
                deduplication_key=f"genomi:{deduplication_key}",
                expected_plan_version_id=expected_plan_version_id,
                expected_consent_receipt_id=expected_consent_receipt_id,
                emit_investigation_event=True,
            )
        except EvidenceCommitGuardError as exc:
            raise LabError(
                "private_context_renewal_required"
                if exc.code == "consent_revoked"
                else "capability_plan_superseded",
                "The private molecular context or accepted plan changed before result commit.",
                http_status=409,
            ) from exc
        return {"status": "committed", "evidence_record": evidence}

    def check_genome_job(
        self,
        investigation_id: str,
        *,
        job_id: str,
        resume_operation: str,
        expected_plan_version_id: str,
        expected_consent_receipt_id: str,
    ) -> JsonObject:
        """Poll one Genomi-owned job after revalidating current private access."""

        if resume_operation != "genomi.check_background_job":
            raise LabError(
                "capability_job_binding_mismatch",
                "Genomi genome work can only use its canonical background-job check.",
                http_status=409,
            )
        snapshot, handle = self.require_genome_context(investigation_id)
        try:
            checked = self.safe_call("genomi.check_background_job", {"job_id": job_id})
        except LabError as exc:
            return {
                "status": exc.code,
                "message": exc.message,
                "retry_after_approval": False,
            }
        if str(checked.get("job_id") or "") != job_id:
            raise LabError(
                "capability_job_binding_mismatch",
                "Genomi returned a different background job.",
                http_status=409,
            )
        current_snapshot, current_handle = self.require_genome_context(
            investigation_id
        )
        current_investigation = self.accepted_plan(investigation_id)
        current_plan = current_investigation.get("current_plan_version")
        if (
            not isinstance(current_plan, dict)
            or current_plan.get("plan_version_id") != expected_plan_version_id
            or current_snapshot.get("patient_molecular_snapshot_id")
            != snapshot.get("patient_molecular_snapshot_id")
            or current_handle is not handle
        ):
            raise LabError(
                "capability_plan_superseded",
                "The Genomi result arrived after its approved investigation context changed.",
                http_status=409,
            )
        current_receipt = self.active_receipt(current_investigation, current_snapshot)
        if current_receipt.get("consent_receipt_id") != expected_consent_receipt_id:
            raise LabError(
                "private_context_renewal_required",
                "The Genomi job belongs to a prior molecular-context consent.",
                http_status=409,
            )
        status = str(checked.get("status") or "")
        if status == "in_progress":
            returned_job, returned_operation, poll_after = self._background_job_binding(
                checked
            )
            return {
                "status": "in_progress",
                "job_id": returned_job,
                "resume_operation": returned_operation,
                **(
                    {"poll_after_seconds": poll_after}
                    if poll_after is not None
                    else {}
                ),
            }
        if status != "completed":
            return {
                "status": status or "background_job_failed",
                "background_job": checked,
                "retry_after_approval": False,
            }
        if checked.get("operation") != "variant.resolve":
            raise LabError(
                "capability_job_binding_mismatch",
                "The completed Genomi job does not belong to variant resolution.",
                http_status=409,
            )
        operation_result = checked.get("operation_result")
        if not isinstance(operation_result, dict):
            return {
                "status": "invalid_background_result",
                "message": "Genomi returned no usable result for the completed job.",
                "retry_after_approval": False,
            }
        deduplication_key = hashlib.sha256(
            compact_json(
                {
                    "operation": "variant.resolve",
                    "job_id": job_id,
                    "agi_snapshot_id": snapshot.get("agi_snapshot_id"),
                }
            ).encode("utf-8")
        ).hexdigest()
        try:
            evidence = self.store.commit_evidence(
                investigation_id,
                source_family="personal_genome",
                operation="variant.resolve",
                evidence=operation_result,
                deduplication_key=f"genomi-job:{deduplication_key}",
                expected_plan_version_id=expected_plan_version_id,
                expected_consent_receipt_id=current_receipt["consent_receipt_id"],
                emit_investigation_event=True,
            )
        except EvidenceCommitGuardError as exc:
            raise LabError(
                "private_context_renewal_required"
                if exc.code == "consent_revoked"
                else "capability_plan_superseded",
                "The private molecular context or accepted plan changed before result commit.",
                http_status=409,
            ) from exc
        return {
            "status": "committed",
            "evidence_record": evidence,
            "background_job": checked,
        }

    def require_genome_context(
        self, investigation_id: str
    ) -> tuple[JsonObject, AgiAuthorizationHandle]:
        investigation = self.investigation(investigation_id)
        snapshot_id = str(investigation.get("patient_molecular_snapshot_id") or "")
        if not snapshot_id:
            raise LabError(
                "private_context_required",
                "Approve the investigation's molecular context first.",
                http_status=409,
            )
        snapshot = self.store.get_profile_snapshot(snapshot_id)
        receipt = self.active_receipt(investigation, snapshot)
        if receipt.get("revoked_at") or receipt.get("workspace_session_id") != self.session_id:
            stale = self.authorizations.pop(investigation_id, None)
            if stale is not None:
                try:
                    revoke_investigation_agi_authorization(stale)
                except InvestigationAgiAuthorizationError:
                    pass
            raise LabError(
                "private_context_renewal_required",
                "Approve this private context again for the current workspace session.",
                http_status=409,
            )
        if not (
            snapshot.get("agi_id")
            and snapshot.get("agi_snapshot_id")
            and isinstance(snapshot.get("genomic_scope"), dict)
        ):
            stale = self.authorizations.pop(investigation_id, None)
            if stale is not None:
                revoke_investigation_agi_authorization(stale)
            raise LabError(
                "private_context_required",
                "The approved molecular context does not include a genome query.",
                http_status=409,
            )
        handle = self.authorizations.get(investigation_id)
        if handle is None:
            raise LabError(
                "private_context_renewal_required",
                "Approve this private context again after reopening GenomiLab.",
                http_status=409,
            )
        try:
            binding = validate_investigation_agi_authorization_binding(handle)
        except InvestigationAgiAuthorizationError as exc:
            self.authorizations.pop(investigation_id, None)
            try:
                revoke_investigation_agi_authorization(handle)
            except InvestigationAgiAuthorizationError:
                pass
            raise LabError(exc.code, str(exc), http_status=409) from exc
        expected = {
            "workspace_session_id": self.session_id,
            "user_id": investigation.get("user_id"),
            "investigation_id": investigation_id,
            "patient_molecular_snapshot_id": snapshot_id,
            "consent_receipt_id": receipt.get("consent_receipt_id"),
            "agi_id": snapshot.get("agi_id"),
            "agi_snapshot_id": snapshot.get("agi_snapshot_id"),
            "purpose": snapshot.get("purpose"),
            "genomic_scope": snapshot.get("genomic_scope"),
        }
        if any(binding.get(field) != value for field, value in expected.items()):
            self.authorizations.pop(investigation_id, None)
            revoke_investigation_agi_authorization(handle)
            raise LabError(
                "private_context_renewal_required",
                "Approve this exact molecular-profile genome context again.",
                http_status=409,
            )
        return snapshot, handle

    @staticmethod
    def _background_job_binding(result: JsonObject) -> tuple[str, str, int | None]:
        job_id = str(result.get("job_id") or "").strip()
        resume_operation = str(result.get("resume_operation") or "").strip()
        check = result.get("check")
        if isinstance(check, dict):
            resume_operation = (
                resume_operation or str(check.get("operation") or "").strip()
            )
            params = check.get("params")
            if isinstance(params, dict):
                job_id = job_id or str(params.get("job_id") or "").strip()
        if not job_id or not resume_operation:
            raise LabError(
                "invalid_background_result",
                "Background work did not provide a job ID and resume operation.",
                http_status=409,
            )
        raw_poll = result.get("poll_after_seconds")
        poll_after = (
            int(raw_poll)
            if isinstance(raw_poll, int)
            and not isinstance(raw_poll, bool)
            and raw_poll > 0
            else None
        )
        return job_id, resume_operation, poll_after

    @staticmethod
    def _validate_payload(
        payload: object,
        *,
        allowed_fields: frozenset[str],
        error_code: str,
        operation: str,
    ) -> None:
        if not isinstance(payload, dict):
            raise LabError(error_code, f"The {operation} must be an object.")
        try:
            validate_private_payload(payload)
        except ValueError as exc:
            raise LabError(error_code, str(exc)) from exc
        unexpected = set(payload) - allowed_fields
        if unexpected:
            raise LabError(
                error_code,
                f"The {operation} contains unsupported fields: "
                + ", ".join(sorted(str(field) for field in unexpected)),
            )

    @staticmethod
    def _normalized_scope(value: object, active_agi: JsonObject) -> JsonObject:
        try:
            return normalize_investigation_genomic_scope(
                value,
                default_genome_build=str(active_agi.get("genome_build") or "GRCh38"),
            )
        except InvestigationAgiAuthorizationError as exc:
            raise LabError(exc.code, str(exc)) from exc
