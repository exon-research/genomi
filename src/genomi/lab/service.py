"""Narrow application service connecting GenomiLab to Genomi operations."""

from __future__ import annotations

import secrets
import threading
from typing import BinaryIO, Callable

from .. import __version__
from ..interfaces.presentation import present_result
from ..operations import OperationError, call_operation
from ..runtime import background_jobs
from ..runtime.private_storage import ensure_private_directory
from .briefs import build_investigation_brief
from .intake import (
    DEFAULT_UPLOAD_LIMIT_BYTES,
    SUPPORTED_UPLOAD_SUFFIXES,
    stage_vcf_upload,
)
from .service_errors import LabError, patient_safe_operation_message
from .store import GenomiLabStore, JsonObject, lab_root


class GenomiLabService:
    """Portal-owned workflows with no generic operation proxy."""

    def __init__(
        self,
        *,
        store: GenomiLabStore | None = None,
        session_id: str | None = None,
        upload_limit_bytes: int = DEFAULT_UPLOAD_LIMIT_BYTES,
        operation_call: Callable[[str, JsonObject | None], JsonObject] = call_operation,
    ) -> None:
        self.store = store or GenomiLabStore()
        self.session_id = session_id or f"genomilab-{secrets.token_urlsafe(18)}"
        self.upload_limit_bytes = max(1, int(upload_limit_bytes))
        self._call = operation_call
        self._operation_lock = threading.RLock()
        self._closed = False
        self._intake_root = ensure_private_directory(
            lab_root() / "intake", private_root=lab_root()
        )

    def bootstrap(self) -> JsonObject:
        profiles = [self._with_session_state(item) for item in self.store.list_profiles()]
        return {
            "status": "ready",
            "product": "GenomiLab",
            "version": __version__,
            "mode": "developer_preview",
            "active_profile_id": self.store.active_profile_id(),
            "profiles": profiles,
            "privacy": {
                "processing": "local_on_this_device",
                "network_required": False,
                "session_consent_required": True,
                "at_rest_encryption": False,
                "safe_for_identifiable_patient_data": False,
            },
            "intake": {
                "supported": ["VCF", "gVCF"],
                "supported_suffixes": list(SUPPORTED_UPLOAD_SUFFIXES),
                "maximum_bytes": self.upload_limit_bytes,
                "synthetic_or_public_data_only": True,
            },
        }

    def create_profile(self, display_name: object) -> JsonObject:
        return self._with_session_state(self.store.create_profile(display_name))

    def profile(self, profile_id: str) -> JsonObject:
        try:
            profile = self.store.get_profile(profile_id)
        except KeyError as exc:
            raise LabError("profile_not_found", "Patient profile not found.", http_status=404) from exc
        return self._with_session_state(profile)

    def activate_profile(self, profile_id: str) -> JsonObject:
        profile = self.profile(profile_id)
        with self._operation_lock:
            self._revoke_runtime_access()
            genomi_user_id = profile.get("genomi_user_id")
            if genomi_user_id:
                self._safe_call(
                    "active_genome_index.select_user", {"user_id": genomi_user_id}
                )
            else:
                self._safe_call("active_genome_index.clear_selection", {})
            self.store.revoke_session_consents(self.session_id)
            self.store.set_active_profile(profile_id)
        return self.profile(profile_id)

    def add_health_fact(self, profile_id: str, payload: JsonObject) -> JsonObject:
        try:
            return self.store.add_health_fact(
                profile_id,
                kind=payload.get("kind"),
                label=payload.get("label"),
                assertion_status=payload.get("assertion_status", "present"),
                onset=payload.get("onset"),
                source_type="patient_reported",
                verification_state="user_confirmed",
                supersedes_fact_id=payload.get("supersedes_fact_id"),
            )
        except KeyError as exc:
            raise LabError("profile_not_found", "Patient profile not found.", http_status=404) from exc
        except ValueError as exc:
            raise LabError("invalid_health_fact", str(exc)) from exc

    def add_reported_finding(self, profile_id: str, payload: JsonObject) -> JsonObject:
        try:
            return self.store.add_reported_finding(
                profile_id,
                variant=payload.get("variant"),
                gene=payload.get("gene"),
                reported_classification=payload.get("reported_classification"),
                source_label=payload.get("source_label"),
            )
        except KeyError as exc:
            raise LabError("profile_not_found", "Patient profile not found.", http_status=404) from exc
        except ValueError as exc:
            raise LabError("invalid_reported_finding", str(exc)) from exc

    def start_genome_intake(
        self,
        profile_id: str,
        *,
        filename: str,
        stream: BinaryIO,
        content_length: int,
    ) -> JsonObject:
        self.profile(profile_id)
        final_path, staged_name = stage_vcf_upload(
            intake_root=self._intake_root,
            private_root=lab_root(),
            profile_id=profile_id,
            filename=filename,
            stream=stream,
            content_length=content_length,
            upload_limit_bytes=self.upload_limit_bytes,
        )

        job = self.store.create_job(
            profile_id,
            operation="genomi.parse_source",
            status="running",
            staged_name=staged_name,
        )
        params: JsonObject = {
            "source": str(final_path),
            "user_nickname": self._genomi_nickname(profile_id),
            "set_default_user": False,
        }
        if background_jobs.background_enabled():
            try:
                raw_job = background_jobs.start_operation_job("genomi.parse_source", params)
            except Exception as exc:
                self.store.update_job(
                    job["portal_job_id"], status="failed", error_code="parse_job_start_failed"
                )
                raise LabError(
                    "parse_job_start_failed", "Genome intake could not be started.", http_status=500
                ) from exc
            self.store.update_job(
                job["portal_job_id"],
                status="in_progress",
                genomi_job_id=str(raw_job["job_id"]),
            )
            return self.store.get_job(job["portal_job_id"])

        try:
            result = self._safe_call("genomi.parse_source", params)
            self._finalize_parse(profile_id, result)
        except LabError as exc:
            self.store.update_job(
                job["portal_job_id"], status="failed", error_code=exc.code
            )
            raise
        self.store.update_job(job["portal_job_id"], status="completed")
        return self.store.get_job(job["portal_job_id"])

    def poll_job(self, portal_job_id: str) -> JsonObject:
        try:
            internal = self.store.job_internal(portal_job_id)
        except KeyError as exc:
            raise LabError("job_not_found", "Import job not found.", http_status=404) from exc
        if internal["status"] in {"completed", "failed"}:
            return self.store.get_job(portal_job_id)
        genomi_job_id = internal.get("genomi_job_id")
        if not genomi_job_id:
            return self.store.get_job(portal_job_id)
        try:
            raw_job = background_jobs.read_job(job_id=str(genomi_job_id))
        except (OSError, ValueError) as exc:
            self.store.update_job(
                portal_job_id, status="failed", error_code="parse_job_unavailable"
            )
            raise LabError(
                "parse_job_unavailable", "The genome import job is no longer available.", http_status=500
            ) from exc
        status = str(raw_job.get("status") or "in_progress")
        if status == "completed":
            result = raw_job.get("result")
            if not isinstance(result, dict):
                self.store.update_job(
                    portal_job_id, status="failed", error_code="invalid_parse_result"
                )
                raise LabError(
                    "invalid_parse_result", "Genome intake returned an invalid result.", http_status=500
                )
            try:
                self._finalize_parse(str(internal["profile_id"]), result)
            except LabError as exc:
                self.store.update_job(portal_job_id, status="failed", error_code=exc.code)
                raise
            self.store.update_job(portal_job_id, status="completed")
        elif status == "failed":
            error = raw_job.get("error") if isinstance(raw_job.get("error"), dict) else {}
            code = str(error.get("code") or "genome_parse_failed")
            self.store.update_job(portal_job_id, status="failed", error_code=code)
        else:
            self.store.update_job(portal_job_id, status="in_progress")
        return self.store.get_job(portal_job_id)

    def approve_genome_access(self, profile_id: str, *, purpose: object) -> JsonObject:
        profile = self.profile(profile_id)
        genome = profile.get("genome")
        if not isinstance(genome, dict) or not genome.get("agi_id"):
            raise LabError("genome_not_ready", "Import a genome before granting access.", http_status=409)
        purpose_text = str(purpose or "").strip()
        if not purpose_text:
            raise LabError("purpose_required", "Describe what this investigation will check.")
        with self._operation_lock:
            self._revoke_runtime_access()
            if profile.get("genomi_user_id"):
                self._safe_call(
                    "active_genome_index.select_user",
                    {"user_id": profile["genomi_user_id"]},
                )
            self.store.revoke_session_consents(self.session_id)
            self._safe_call(
                "active_genome_index.approve_access",
                {
                    "approved_by_user": True,
                    "agi_id": genome["agi_id"],
                    "reason": purpose_text,
                },
            )
            receipt = self.store.record_consent(
                profile_id,
                agi_id=str(genome["agi_id"]),
                session_id=self.session_id,
                purpose=purpose_text,
            )
            self.store.set_active_profile(profile_id)
        return receipt

    def run_investigation(self, profile_id: str, payload: JsonObject) -> JsonObject:
        profile = self.profile(profile_id)
        genome = profile.get("genome")
        if not isinstance(genome, dict) or not genome.get("agi_id"):
            raise LabError("genome_not_ready", "Import a genome before running this check.", http_status=409)
        if not self.store.has_session_consent(
            profile_id, self.session_id, str(genome["agi_id"])
        ):
            raise LabError(
                "consent_required",
                "Approve this session's genome access before running an investigation.",
                http_status=403,
            )
        try:
            investigation = self.store.create_investigation(
                profile_id,
                question=payload.get("question"),
                finding_id=payload.get("finding_id"),
            )
            finding = self.store.get_finding(str(investigation["finding_id"]))
        except KeyError as exc:
            raise LabError("profile_or_finding_not_found", "Profile or finding not found.", http_status=404) from exc
        except ValueError as exc:
            raise LabError("invalid_investigation", str(exc)) from exc

        params: JsonObject = {"agi_id": genome["agi_id"]}
        normalization = finding.get("normalization_state")
        if normalization == "rsid_ready":
            params["rsid"] = finding["variant"]
        elif normalization == "exact_genomic_allele_ready":
            params["query"] = finding["variant"]
        else:
            self.store.fail_investigation(
                investigation["investigation_id"], "variant_needs_review"
            )
            raise LabError(
                "variant_needs_review",
                "This first release can investigate an rsID or exact chrom:pos:ref:alt allele. Review this finding before continuing.",
                http_status=409,
            )

        try:
            with self._operation_lock:
                result = self._safe_call("variant.resolve", params)
        except LabError as exc:
            self.store.fail_investigation(investigation["investigation_id"], exc.code)
            raise
        presented = present_result("variant.resolve", result)
        brief = build_investigation_brief(
            profile=profile,
            finding=finding,
            question=str(investigation["question"]),
            evidence=presented,
        )
        return self.store.complete_investigation(
            investigation["investigation_id"], brief
        )

    def close(self) -> None:
        if self._closed:
            return
        with self._operation_lock:
            self._revoke_runtime_access()
            self.store.revoke_session_consents(self.session_id)
            self._closed = True

    def _with_session_state(self, profile: JsonObject) -> JsonObject:
        result = dict(profile)
        genome = result.get("genome")
        agi_id = str(genome.get("agi_id") or "") if isinstance(genome, dict) else ""
        result["genome_access"] = {
            "approved": bool(
                agi_id
                and self.store.has_session_consent(result["profile_id"], self.session_id, agi_id)
            ),
            "scope": "current_portal_session",
        }
        return result

    def _finalize_parse(self, profile_id: str, result: JsonObject) -> None:
        active = result.get("active_genome_index")
        if not isinstance(active, dict) or not active.get("agi_id"):
            raise LabError(
                "genome_parse_incomplete",
                "Genome intake did not produce a queryable Active Genome Index.",
                http_status=409,
            )
        agi_id = str(active["agi_id"])
        readiness_value = active.get("active_genome_index_readiness")
        if isinstance(readiness_value, dict):
            readiness = str(readiness_value.get("status") or result.get("status") or "unknown")
        else:
            readiness = str(result.get("status") or "unknown")
        inventory = self._safe_call("active_genome_index.list", {})
        nickname = self._genomi_nickname(profile_id)
        user = next(
            (
                item
                for item in inventory.get("users", [])
                if isinstance(item, dict)
                and (
                    item.get("nickname") == nickname
                    or str(item.get("active_agi_id") or "") == agi_id
                )
            ),
            None,
        )
        if not isinstance(user, dict) or not user.get("user_id"):
            raise LabError(
                "profile_link_failed",
                "The imported genome could not be linked to this profile.",
                http_status=500,
            )
        self.store.link_genomi_user(profile_id, str(user["user_id"]))
        self.store.link_genome(
            profile_id,
            agi_id=agi_id,
            genome_build=(str(active.get("genome_build")) if active.get("genome_build") else None),
            readiness=readiness,
        )
        self._safe_call("active_genome_index.revoke_access", {"agi_id": agi_id})
        self.store.revoke_session_consents(self.session_id)

    def _safe_call(self, operation: str, params: JsonObject | None = None) -> JsonObject:
        try:
            result = self._call(operation, params or {})
        except OperationError as exc:
            status = 403 if exc.code == "approval_required" else 409
            raise LabError(
                exc.code,
                patient_safe_operation_message(exc.code),
                http_status=status,
            ) from exc
        except (OSError, ValueError) as exc:
            raise LabError(
                "operation_failed", "The local Genomi operation could not be completed.", http_status=500
            ) from exc
        if not isinstance(result, dict):
            raise LabError(
                "invalid_operation_result", "Genomi returned an invalid result.", http_status=500
            )
        return result

    def _revoke_runtime_access(self) -> None:
        try:
            self._call("active_genome_index.revoke_access", {})
        except Exception:
            pass

    @staticmethod
    def _genomi_nickname(profile_id: str) -> str:
        return f"GenomiLab {profile_id.removeprefix('patient-')[:12]}"
