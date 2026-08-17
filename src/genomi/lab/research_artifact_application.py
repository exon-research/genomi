"""Host-facing application boundary for nonclinical research operations."""

from __future__ import annotations

from typing import Any, Protocol

from .models import JsonObject, required_text
from .research_artifact_contract import (
    HOST_SUBMISSION_ORIGINS,
    RESEARCH_ARTIFACT_USE_BOUNDARY,
    VERIFIED_SCIENTIFIC_OPERATION,
)
from .research_scientific_operations import (
    ESMScientificExecutor,
    ProtoScientificExecutor,
    ResearchScientificOperationUnavailable,
    SCIENTIFIC_OPERATION_USE_BOUNDARY,
    run_esm_substitution_artifact,
    run_proto_blinded_design_artifact,
    scientific_operations_manifest,
    verify_sequence_substitution_artifact,
)
from .service_errors import LabError


class _ResearchArtifactApplication(Protocol):
    store: Any
    _esm_scientific_executor: ESMScientificExecutor | None
    _proto_scientific_executor: ProtoScientificExecutor | None

    def _require_specialist_board(self, investigation_id: str) -> JsonObject: ...

    def _require_investigation_authorization(
        self, investigation_id: str, *, intent: str, receipt: JsonObject | None = None
    ) -> JsonObject: ...


class ResearchArtifactApplicationMixin:
    """Persist research-only artifacts without promoting them into evidence."""

    def submit_agent_research_artifact(
        self: _ResearchArtifactApplication,
        investigation_id: str,
        *,
        round_id: object,
        deduplication_key: object,
        origin: object,
        artifact: object,
    ) -> JsonObject:
        """Persist a fixture or unverified host result; never claim execution."""

        self._require_specialist_board(investigation_id)
        try:
            committed, retry_reused = self._commit_research_artifact(
                investigation_id,
                round_id=round_id,
                deduplication_key=deduplication_key,
                origin=origin,
                artifact=artifact,
                allowed_origins=HOST_SUBMISSION_ORIGINS,
            )
        except (KeyError, ValueError) as exc:
            raise LabError(
                "invalid_research_artifact", str(exc), http_status=409
            ) from exc
        return {
            "status": "completed",
            "research_artifact": committed,
            "retry_reused": retry_reused,
            "scientific_execution": "not_verified",
            "provider_execution": "not_verified",
        }

    def verify_agent_sequence_substitution(
        self: _ResearchArtifactApplication,
        investigation_id: str,
        *,
        round_id: object,
        deduplication_key: object,
        gene: object,
        transcript_accession: object,
        protein_accession: object,
        coding_change: object,
        protein_substitution: object,
        public_reference_protein_sequence: object,
        reference_source_label: object,
        reference_source_version: object,
        reference_source_record_id: object,
    ) -> JsonObject:
        """Verify the exact protein substitution locally and persist only hashes."""

        self._require_specialist_board(investigation_id)
        try:
            artifact, _alternate_sequence = verify_sequence_substitution_artifact(
                gene=gene,
                transcript_accession=transcript_accession,
                protein_accession=protein_accession,
                coding_change=coding_change,
                protein_substitution=protein_substitution,
                public_reference_protein_sequence=(
                    public_reference_protein_sequence
                ),
                reference_source_label=reference_source_label,
                reference_source_version=reference_source_version,
                reference_source_record_id=reference_source_record_id,
            )
            committed, retry_reused = self._commit_research_artifact(
                investigation_id,
                round_id=round_id,
                deduplication_key=deduplication_key,
                origin=VERIFIED_SCIENTIFIC_OPERATION,
                artifact=artifact,
                allowed_origins=frozenset({VERIFIED_SCIENTIFIC_OPERATION}),
            )
        except (KeyError, ValueError) as exc:
            raise LabError(
                "invalid_sequence_substitution", str(exc), http_status=409
            ) from exc
        return {
            "status": "completed",
            "research_artifact": committed,
            "retry_reused": retry_reused,
            "scientific_execution": "verified_local_execution",
            "provider_execution": "not_applicable_local_genomi",
        }

    def run_agent_esm_substitution_analysis(
        self: _ResearchArtifactApplication,
        investigation_id: str,
        *,
        round_id: object,
        deduplication_key: object,
        sequence_verification_artifact_id: object,
        public_reference_protein_sequence: object,
    ) -> JsonObject:
        """Run one allowlisted ESM comparison through a scientific executor."""

        round_identifier = required_text(round_id, "round_id", 200)
        self._require_specialist_board(investigation_id)
        self._require_investigation_authorization(
            investigation_id, intent="user_followup"
        )
        try:
            verification = self._research_verification_artifact(
                investigation_id,
                round_id=round_identifier,
                research_artifact_id=sequence_verification_artifact_id,
            )
            artifact = run_esm_substitution_artifact(
                executor=self._esm_scientific_executor,
                verification_artifact=verification,
                public_reference_protein_sequence=(
                    public_reference_protein_sequence
                ),
            )
        except ResearchScientificOperationUnavailable as exc:
            return self._scientific_operation_unavailable(
                operation="genomilab.run_esm_substitution_analysis",
                round_id=round_identifier,
                state=exc.state,
            )
        except (KeyError, ValueError) as exc:
            raise LabError(
                "invalid_esm_substitution_analysis", str(exc), http_status=409
            ) from exc
        try:
            committed, retry_reused = self._commit_research_artifact(
                investigation_id,
                round_id=round_identifier,
                deduplication_key=deduplication_key,
                origin=VERIFIED_SCIENTIFIC_OPERATION,
                artifact=artifact,
                allowed_origins=frozenset({VERIFIED_SCIENTIFIC_OPERATION}),
            )
        except (KeyError, ValueError) as exc:
            raise LabError(
                "invalid_esm_substitution_analysis", str(exc), http_status=409
            ) from exc
        return self._scientific_operation_completed(
            committed, retry_reused=retry_reused
        )

    def run_agent_proto_blinded_experiment_design(
        self: _ResearchArtifactApplication,
        investigation_id: str,
        *,
        round_id: object,
        deduplication_key: object,
        sequence_verification_artifact_id: object,
        objective: object,
        required_arm_classes: object,
        readouts: object,
    ) -> JsonObject:
        """Run one bounded blinded-design operation through a scientific executor."""

        round_identifier = required_text(round_id, "round_id", 200)
        self._require_specialist_board(investigation_id)
        self._require_investigation_authorization(
            investigation_id, intent="user_followup"
        )
        try:
            verification = self._research_verification_artifact(
                investigation_id,
                round_id=round_identifier,
                research_artifact_id=sequence_verification_artifact_id,
            )
            artifact = run_proto_blinded_design_artifact(
                executor=self._proto_scientific_executor,
                verification_artifact=verification,
                objective=objective,
                required_arm_classes=required_arm_classes,
                readouts=readouts,
            )
        except ResearchScientificOperationUnavailable as exc:
            return self._scientific_operation_unavailable(
                operation="genomilab.run_proto_blinded_experiment_design",
                round_id=round_identifier,
                state=exc.state,
            )
        except (KeyError, ValueError) as exc:
            raise LabError(
                "invalid_proto_blinded_experiment_design",
                str(exc),
                http_status=409,
            ) from exc
        try:
            committed, retry_reused = self._commit_research_artifact(
                investigation_id,
                round_id=round_identifier,
                deduplication_key=deduplication_key,
                origin=VERIFIED_SCIENTIFIC_OPERATION,
                artifact=artifact,
                allowed_origins=frozenset({VERIFIED_SCIENTIFIC_OPERATION}),
            )
        except (KeyError, ValueError) as exc:
            raise LabError(
                "invalid_proto_blinded_experiment_design",
                str(exc),
                http_status=409,
            ) from exc
        return self._scientific_operation_completed(
            committed, retry_reused=retry_reused
        )

    def list_agent_research_artifacts(
        self: _ResearchArtifactApplication, investigation_id: str
    ) -> JsonObject:
        self._require_specialist_board(investigation_id)
        self._require_investigation_authorization(investigation_id, intent="resume")
        artifacts = self.store.list_research_artifacts(
            investigation_id, current_only=True
        )
        return {
            "status": "completed",
            "research_artifacts": artifacts,
            "research_artifact_count": len(artifacts),
            "use_boundary": dict(RESEARCH_ARTIFACT_USE_BOUNDARY),
        }

    def research_scientific_operations_manifest(
        self: _ResearchArtifactApplication,
    ) -> JsonObject:
        return scientific_operations_manifest(
            esm_executor=self._esm_scientific_executor,
            proto_executor=self._proto_scientific_executor,
        )

    def _commit_research_artifact(
        self: _ResearchArtifactApplication,
        investigation_id: str,
        *,
        round_id: object,
        deduplication_key: object,
        origin: object,
        artifact: object,
        allowed_origins: frozenset[str],
    ) -> tuple[JsonObject, bool]:
        with self.store.atomic_write():
            self._require_investigation_authorization(
                investigation_id, intent="user_followup"
            )
            committed, retry_reused = self.store.commit_research_artifact(
                investigation_id,
                round_id=round_id,
                deduplication_key=deduplication_key,
                origin=origin,
                artifact=artifact,
                allowed_origins=allowed_origins,
            )
            if not retry_reused:
                self.store.append_investigation_event(
                    investigation_id,
                    event_type="research_artifact_submitted",
                    payload={
                        "research_artifact_id": committed[
                            "research_artifact_id"
                        ],
                        "round_id": committed["round_id"],
                        "artifact_kind": committed["artifact_kind"],
                        "system": committed["system"],
                        "origin": committed["origin"],
                    },
                )
        return committed, retry_reused

    def _research_verification_artifact(
        self: _ResearchArtifactApplication,
        investigation_id: str,
        *,
        round_id: str,
        research_artifact_id: object,
    ) -> JsonObject:
        identifier = required_text(
            research_artifact_id, "sequence_verification_artifact_id", 200
        )
        artifact = self.store.get_research_artifact(
            investigation_id, identifier
        )
        if artifact.get("round_id") != round_id:
            raise ValueError(
                "sequence verification must belong to the same investigation round"
            )
        return artifact

    @staticmethod
    def _scientific_operation_unavailable(
        *, operation: str, round_id: str, state: str
    ) -> JsonObject:
        return {
            "status": "unavailable",
            "operation": operation,
            "round_id": round_id,
            "unavailable_state": state,
            "research_artifact": None,
            "use_boundary": dict(SCIENTIFIC_OPERATION_USE_BOUNDARY),
        }

    @staticmethod
    def _scientific_operation_completed(
        artifact: JsonObject, *, retry_reused: bool
    ) -> JsonObject:
        return {
            "status": "completed",
            "research_artifact": artifact,
            "retry_reused": retry_reused,
            "scientific_execution": "verified_local_execution",
            "provider_execution": "verified_by_scientific_adapter",
            "use_boundary": dict(SCIENTIFIC_OPERATION_USE_BOUNDARY),
        }


__all__ = ["ResearchArtifactApplicationMixin"]
