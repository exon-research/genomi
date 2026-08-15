"""Current-user workspace and molecular-profile application service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .. import __version__
from .models import JsonObject, validate_private_payload
from .service_errors import LabError
from .store import GenomiLabStore


_PATIENT_SOURCE_ARTIFACT_FIELDS = frozenset(
    {"content_sha256", "source_type", "title", "source_identifier", "issued_at"}
)
_PATIENT_SPECIMEN_FIELDS = frozenset(
    {
        "artifact_id",
        "specimen_type",
        "body_site",
        "collected_at",
        "disease_state",
        "tumor_normal_role",
    }
)
_PATIENT_ASSAY_FIELDS = frozenset(
    {
        "specimen_id",
        "artifact_id",
        "assay_type",
        "laboratory",
        "platform",
        "pipeline",
        "genome_build",
        "assay_scope",
        "detection_limits",
    }
)


def genome_metadata(context: JsonObject) -> JsonObject | None:
    active = context.get("active_genome_index")
    if not isinstance(active, dict) or not context.get("active_agi_id"):
        return None
    readiness = active.get("active_genome_index_readiness")
    return {
        "agi_id": context.get("active_agi_id"),
        "agi_snapshot_id": active.get("agi_snapshot_id"),
        "genome_build": active.get("genome_build"),
        "readiness": (
            readiness.get("status")
            if isinstance(readiness, dict)
            else active.get("status")
        ),
        "access_approved": bool(
            (context.get("active_genome_index_access") or {}).get("approved")
            if isinstance(context.get("active_genome_index_access"), dict)
            else False
        ),
    }


@dataclass(frozen=True, slots=True)
class WorkspaceApplication:
    """Own profile authoring and investigation navigation for one local user."""

    store: GenomiLabStore
    session_id: str
    describe_context: Callable[[], JsonObject]
    current_context: Callable[[], tuple[JsonObject, str]]
    bind_user: Callable[[str], None]
    unbind_user: Callable[[], None]
    genome_metadata: Callable[[JsonObject], JsonObject | None]
    active_context_receipt: Callable[[JsonObject, JsonObject], JsonObject]
    harness_manifest: Callable[[], JsonObject]
    evidence_manifest: Callable[[], JsonObject]
    integration_manifest: Callable[[], JsonObject]

    def bootstrap(self) -> JsonObject:
        context = self.describe_context()
        user = context.get("active_user")
        user_id = str(context.get("active_user_id") or "").strip()
        if not user_id or not isinstance(user, dict):
            self.unbind_user()
            return {
                "status": "setup_required",
                "code": "genomi_user_required",
                "workspace": None,
                "product": "GenomiLab",
                "version": __version__,
                "setup": {
                    "owner": "Genomi",
                    "action": (
                        "Create or select the local user in Genomi, then reopen "
                        "GenomiLab."
                    ),
                },
            }
        self.bind_user(user_id)
        workspace = self.store.open_workspace(user_id, user.get("nickname"))
        workspace["profile"]["genome"] = self.genome_metadata(context)
        investigation_views = self.store.list_investigations(user_id)
        workspace["investigations"] = investigation_views
        workspace["evidence_library"] = [
            {
                **record,
                "investigation_id": investigation["investigation_id"],
                "investigation_question": investigation["question"],
            }
            for investigation in investigation_views
            for record in investigation.get("evidence_records") or []
            if isinstance(record, dict)
        ]
        workspace["privacy_activity"] = self.store.workspace_activity(user_id)
        workspace["attention"] = self._attention(investigation_views)
        integrations = self.integration_manifest()
        provider_connections = integrations.get("provider_connections")
        by_provider = {
            str(item.get("provider")): item
            for item in (
                provider_connections if isinstance(provider_connections, list) else []
            )
            if isinstance(item, dict)
        }
        return {
            "status": "ready",
            "product": "GenomiLab",
            "version": __version__,
            "mode": "local_research_workspace",
            "workspace": workspace,
            "capabilities": {
                "molecular_profile": "available",
                "disease_investigation": "available",
                "installed_harness": self.harness_manifest(),
                "collaboration": "capability_unavailable",
                "public_evidence": self.evidence_manifest(),
                "research_tools": integrations,
                "proto": by_provider.get("proto", "capability_unavailable"),
                "esm": by_provider.get("biohub-esm", "capability_unavailable"),
            },
            "privacy": {
                "processing": (
                    "local_unless_a_disclosed_harness_or_provider_is_selected"
                ),
                "session_consent_required": True,
                "raw_genome_owner": "Genomi",
            },
        }

    @staticmethod
    def _attention(investigations: list[JsonObject]) -> JsonObject:
        return {
            "plan_reviews": sum(
                1
                for investigation in investigations
                if isinstance(investigation.get("current_plan_version"), dict)
                and investigation["current_plan_version"].get("review_status")
                == "proposed"
            ),
            "provider_approvals": sum(
                1
                for investigation in investigations
                for execution in investigation.get("current_capability_executions")
                or []
                if isinstance(execution, dict)
                and execution.get("status") == "approval_required"
            ),
            "running_jobs": sum(
                1
                for investigation in investigations
                for execution in investigation.get("current_capability_executions")
                or []
                if isinstance(execution, dict)
                and execution.get("status") == "in_progress"
            ),
            "completed_briefs": sum(
                1
                for investigation in investigations
                if investigation.get("current_brief_version")
            ),
            "new_evidence_records": sum(
                len(investigation.get("current_evidence_records") or [])
                for investigation in investigations
            ),
        }

    def molecular_profile(self) -> JsonObject:
        context, user_id = self.current_context()
        workspace = self.store.open_workspace(
            user_id,
            (context.get("active_user") or {}).get("nickname")
            if isinstance(context.get("active_user"), dict)
            else None,
        )
        profile = dict(workspace["profile"])
        profile["genome"] = self.genome_metadata(context)
        return profile

    def add_profile_observation(self, payload: JsonObject) -> JsonObject:
        _, user_id = self.current_context()
        try:
            validate_private_payload(payload)
            safe_payload = self._patient_observation_payload(payload, user_id=user_id)
            return self.store.add_profile_observation(user_id, safe_payload)
        except KeyError as exc:
            raise LabError(
                "genomi_user_required",
                "Select the current user in Genomi before adding molecular context.",
                http_status=409,
            ) from exc
        except ValueError as exc:
            raise LabError("invalid_profile_observation", str(exc)) from exc

    def review_or_supersede_observation(
        self, observation_revision_id: str, payload: JsonObject
    ) -> JsonObject:
        _, user_id = self.current_context()
        try:
            validate_private_payload(payload)
            prior = self.store.get_profile_observation(user_id, observation_revision_id)
            safe_payload = self._patient_observation_payload(
                payload, user_id=user_id, prior=prior
            )
            return self.store.review_or_supersede_observation(
                user_id, observation_revision_id, safe_payload
            )
        except KeyError as exc:
            raise LabError(
                "observation_not_found",
                "Profile observation not found.",
                http_status=404,
            ) from exc
        except ValueError as exc:
            raise LabError("invalid_profile_observation", str(exc)) from exc

    def _patient_observation_payload(
        self,
        payload: object,
        *,
        user_id: str,
        prior: JsonObject | None = None,
    ) -> JsonObject:
        """Canonicalize patient-authored provenance at the trusted boundary."""

        if not isinstance(payload, dict):
            raise ValueError("profile observation must be an object")
        protected_fields = {
            "assertion_author",
            "reviewed_by",
            "normalized_code",
            "normalization_provenance",
            "logical_observation_id",
            "supersedes_revision_id",
            "assay_scope",
            "detection_limits",
            "source_locator",
        }
        supplied_protected = set(payload) & protected_fields
        if supplied_protected:
            raise ValueError(
                "patient profile writes cannot set protected provenance fields: "
                + ", ".join(sorted(supplied_protected))
            )
        source_class = payload.get("source_class")
        if source_class not in (None, "patient_reported", "issued_record"):
            raise ValueError(
                "the patient API accepts only patient_reported or issued_record sources"
            )
        verification_state = payload.get("verification_state")
        if verification_state not in (None, "user_confirmed"):
            raise ValueError(
                "the patient API records patient review only; clinical or record "
                "confirmation requires a separate authenticated workflow"
            )
        result = dict(payload)
        if isinstance(prior, dict) and (
            prior.get("source_class") == "clinician_entered"
            or prior.get("assertion_author") == "clinician"
            or prior.get("verification_state") == "clinician_confirmed"
        ):
            result["source_class"] = "patient_reported"
        effective_source_class = (
            result.get("source_class")
            or (prior.get("source_class") if isinstance(prior, dict) else None)
            or "patient_reported"
        )
        effective_artifact_id = (
            result.get("artifact_id")
            if "artifact_id" in result
            else prior.get("artifact_id")
            if isinstance(prior, dict)
            else None
        )
        if effective_source_class == "issued_record" and not effective_artifact_id:
            raise ValueError(
                "issued_record observations must link to a saved source record"
            )
        if effective_source_class == "issued_record":
            entities = self.store.list_profile_entities(user_id)
            artifact = next(
                (
                    item
                    for item in entities.get("source_artifacts") or []
                    if item.get("artifact_id") == effective_artifact_id
                ),
                None,
            )
            if not isinstance(artifact, dict) or artifact.get("source_type") not in {
                "issued_report",
                "laboratory_report",
                "pathology_report",
                "clinical_note",
            }:
                raise ValueError(
                    "issued_record observations must link to an issued medical record"
                )
        result.update(
            {
                "source_class": effective_source_class,
                "assertion_author": "patient",
                "verification_state": "user_confirmed",
                "reviewed_by": f"patient:{user_id}",
            }
        )
        return result

    def add_source_artifact(self, payload: JsonObject) -> JsonObject:
        return self._add_profile_entity(
            payload,
            allowed_fields=_PATIENT_SOURCE_ARTIFACT_FIELDS,
            entity="source artifact",
            error_code="invalid_source_artifact",
            add=self.store.add_source_artifact,
        )

    def add_specimen(self, payload: JsonObject) -> JsonObject:
        return self._add_profile_entity(
            payload,
            allowed_fields=_PATIENT_SPECIMEN_FIELDS,
            entity="specimen",
            error_code="invalid_specimen",
            add=self.store.add_specimen,
        )

    def add_assay(self, payload: JsonObject) -> JsonObject:
        return self._add_profile_entity(
            payload,
            allowed_fields=_PATIENT_ASSAY_FIELDS,
            entity="assay",
            error_code="invalid_assay",
            add=self.store.add_assay,
        )

    def _add_profile_entity(
        self,
        payload: JsonObject,
        *,
        allowed_fields: frozenset[str],
        entity: str,
        error_code: str,
        add: Callable[[str, JsonObject], JsonObject],
    ) -> JsonObject:
        _, user_id = self.current_context()
        try:
            self._validate_patient_entity_payload(
                payload, allowed_fields=allowed_fields, entity=entity
            )
            return add(user_id, payload)
        except ValueError as exc:
            raise LabError(error_code, str(exc)) from exc

    @staticmethod
    def _validate_patient_entity_payload(
        payload: object, *, allowed_fields: frozenset[str], entity: str
    ) -> None:
        if not isinstance(payload, dict):
            raise ValueError(f"{entity} must be an object")
        validate_private_payload(payload)
        unexpected = set(payload) - allowed_fields
        if unexpected:
            raise ValueError(
                f"unsupported {entity} fields: " + ", ".join(sorted(unexpected))
            )

    def create_investigation(self, payload: JsonObject) -> JsonObject:
        _, user_id = self.current_context()
        try:
            validate_private_payload(payload)
            unexpected = set(payload) - {"question", "disease_scope"}
            if unexpected:
                raise ValueError(
                    "unsupported investigation fields: " + ", ".join(sorted(unexpected))
                )
            return self.store.create_investigation(
                user_id,
                question=payload.get("question"),
                disease_scope=payload.get("disease_scope"),
            )
        except (KeyError, ValueError) as exc:
            raise LabError("invalid_investigation", str(exc)) from exc

    def investigation(self, investigation_id: str) -> JsonObject:
        _, user_id = self.current_context()
        try:
            investigation = self.store.get_investigation(investigation_id)
        except KeyError as exc:
            raise LabError(
                "investigation_not_found", "Investigation not found.", http_status=404
            ) from exc
        if str(investigation.get("user_id")) != user_id:
            raise LabError(
                "investigation_not_found", "Investigation not found.", http_status=404
            )
        investigation["private_context_status"] = self._private_context_status(
            investigation
        )
        return investigation

    def _private_context_status(self, investigation: JsonObject) -> str:
        snapshot_id = str(investigation.get("patient_molecular_snapshot_id") or "")
        if not snapshot_id:
            return "not_approved"
        try:
            snapshot = self.store.get_profile_snapshot(snapshot_id)
            receipt = self.active_context_receipt(investigation, snapshot)
        except KeyError:
            return "invalid"
        if (
            receipt.get("revoked_at")
            or receipt.get("workspace_session_id") != self.session_id
            or receipt.get("user_id") != investigation.get("user_id")
            or receipt.get("investigation_id") != investigation.get("investigation_id")
            or receipt.get("patient_molecular_snapshot_id") != snapshot_id
        ):
            return "renewal_required"
        return "approved_for_session"

    def list_investigations(self) -> list[JsonObject]:
        _, user_id = self.current_context()
        return self.store.list_investigations(user_id)

    def accepted_current_plan(self, investigation_id: str) -> JsonObject:
        investigation = self.investigation(investigation_id)
        current = investigation.get("current_plan_version")
        if not isinstance(current, dict) or current.get("review_status") != "accepted":
            raise LabError(
                "plan_acceptance_required",
                "Review and accept the current harness plan before its capabilities run.",
                http_status=409,
            )
        return investigation

    def accept_current_plan(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        unexpected = set(payload) - {"plan_version_id", "plan_sha256", "approved"}
        if unexpected:
            raise LabError(
                "invalid_plan_acceptance",
                "Plan acceptance contains unsupported fields.",
            )
        investigation = self.investigation(investigation_id)
        current = investigation.get("current_plan_version")
        if not isinstance(current, dict):
            raise LabError(
                "harness_plan_required",
                "The installed harness must propose a plan before it can be accepted.",
                http_status=409,
            )
        try:
            with self.store.atomic_write():
                acceptance = self.store.accept_plan(
                    investigation_id,
                    plan_version_id=payload.get("plan_version_id"),
                    user_id=investigation["user_id"],
                    workspace_session_id=self.session_id,
                    plan_sha256=payload.get("plan_sha256"),
                    approved=payload.get("approved"),
                )
                if current.get("review_status") == "accepted":
                    updated = investigation
                else:
                    next_status = (
                        "awaiting_harness_execution"
                        if investigation.get("patient_molecular_snapshot_id")
                        else "awaiting_context_approval"
                    )
                    updated = self.store.set_investigation_status(
                        investigation_id, next_status
                    )
        except (KeyError, ValueError) as exc:
            raise LabError(
                "invalid_plan_acceptance", str(exc), http_status=409
            ) from exc
        return {
            "status": "accepted",
            "plan_acceptance": acceptance,
            "plan_version": updated.get("current_plan_version"),
            "capability_results": [],
            "investigation_status": updated.get("status"),
            "next_harness_action": (
                {
                    "operation": "replace_task_binding",
                    "artifact_kind": "execution_report",
                    "instruction": "Execute the exact accepted investigation plan.",
                    "reason": (
                        "Create a request-scoped harness task after explicit plan "
                        "acceptance."
                    ),
                    "requires_outbound_disclosure_approval": True,
                }
                if investigation.get("patient_molecular_snapshot_id")
                and (current.get("plan") or {}).get("capability_requests")
                else None
            ),
        }

    def investigation_profile(self, investigation_id: str) -> JsonObject:
        try:
            return self.approved_investigation_profile(investigation_id)
        except ValueError as exc:
            raise LabError(
                "private_context_required", str(exc), http_status=409
            ) from exc

    def approved_investigation_profile(self, investigation_id: str) -> JsonObject:
        investigation = self.investigation(investigation_id)
        snapshot_id = str(investigation.get("patient_molecular_snapshot_id") or "")
        if not snapshot_id:
            raise LabError(
                "private_context_required",
                "Approve the investigation's molecular context first.",
                http_status=409,
            )
        snapshot = self.store.get_profile_snapshot(snapshot_id)
        receipt = self.active_context_receipt(investigation, snapshot)
        expected = {
            "workspace_session_id": self.session_id,
            "user_id": investigation["user_id"],
            "investigation_id": investigation_id,
            "patient_molecular_snapshot_id": snapshot_id,
        }
        if receipt.get("revoked_at") or any(
            receipt.get(key) != value for key, value in expected.items()
        ):
            raise LabError(
                "private_context_renewal_required",
                "Approve this molecular-profile context again for the current workspace session.",
                http_status=409,
            )
        return self.store.project_investigation_profile(investigation_id)
