"""Bounded local scientific-operation adapters for the research side panel."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import Any

from .models import JsonObject, required_text
from .research_artifact_contract import (
    ESM_NONCLINICAL_COMPARISON,
    GENOMI_SEQUENCE_SUBSTITUTION_VERIFICATION,
    PROTO_BLINDED_EXPERIMENTAL_DESIGN,
    VERIFIED_SCIENTIFIC_OPERATION,
    canonical_public_reference_sequence,
    normalize_research_artifact,
    substitution_parts,
)


ESMScientificExecutor = Callable[[JsonObject], Mapping[str, Any]]
ProtoScientificExecutor = Callable[[JsonObject], Mapping[str, Any]]

GENOMI_SEQUENCE_METHOD = {
    "name": "reference_protein_substitution_check",
    "version": "1",
}
GENOMI_SEQUENCE_MODEL = {
    "name": "genomi_deterministic_sequence_rules",
    "version": "1",
}

SCIENTIFIC_OPERATION_USE_BOUNDARY: JsonObject = {
    "nonclinical": True,
    "patient_workflow_mode": "bounded_mechanistic_research",
    "clinical_evidence_status": "ineligible",
    "answer_readiness_effect": "none",
    "diagnostic_conclusion": False,
    "variant_classification": False,
    "treatment_recommendation": False,
    "provider_connection_check_counts_as_execution": False,
}


class ResearchScientificOperationUnavailable(RuntimeError):
    """A scientific executor is absent or cannot truthfully run the request."""

    def __init__(self, state: str) -> None:
        super().__init__(state)
        self.state = required_text(state, "unavailable_state", 200)


def verify_sequence_substitution_artifact(
    *,
    gene: object,
    transcript_accession: object,
    protein_accession: object,
    coding_change: object,
    protein_substitution: object,
    public_reference_protein_sequence: object,
    reference_source_label: object,
    reference_source_version: object,
    reference_source_record_id: object,
) -> tuple[JsonObject, str]:
    """Verify one intended substitution against a transient public sequence."""

    sequence = canonical_public_reference_sequence(
        public_reference_protein_sequence
    )
    reference_residue, position, alternate_residue = substitution_parts(
        protein_substitution
    )
    if position > len(sequence):
        raise ValueError("protein_substitution position exceeds the reference sequence")
    if sequence[position - 1] != reference_residue:
        raise ValueError(
            "protein_substitution reference residue does not match the supplied public reference sequence"
        )
    alternate_sequence = (
        sequence[: position - 1] + alternate_residue + sequence[position:]
    )
    artifact = {
        "artifact_kind": GENOMI_SEQUENCE_SUBSTITUTION_VERIFICATION,
        "method": dict(GENOMI_SEQUENCE_METHOD),
        "model": dict(GENOMI_SEQUENCE_MODEL),
        "input": {
            "gene": required_text(gene, "gene", 80),
            "transcript_accession": required_text(
                transcript_accession, "transcript_accession", 200
            ),
            "protein_accession": required_text(
                protein_accession, "protein_accession", 200
            ),
            "coding_change": required_text(coding_change, "coding_change", 200),
            "protein_substitution": required_text(
                protein_substitution, "protein_substitution", 80
            ).upper(),
            "reference_sequence_sha256": _sequence_sha256(sequence),
            "alternate_sequence_sha256": _sequence_sha256(alternate_sequence),
        },
        "output": {
            "position": position,
            "reference_residue": reference_residue,
            "alternate_residue": alternate_residue,
            "protein_substitution_verified": True,
        },
        "provenance": {
            "execution_class": VERIFIED_SCIENTIFIC_OPERATION,
            "execution_location": "local",
            "network_access": "disabled",
            "source_label": required_text(
                reference_source_label, "reference_source_label", 300
            ),
            "source_version": required_text(
                reference_source_version, "reference_source_version", 200
            ),
            "source_record_id": required_text(
                reference_source_record_id, "reference_source_record_id", 300
            ),
        },
    }
    _kind, _origin, normalized = normalize_research_artifact(
        origin=VERIFIED_SCIENTIFIC_OPERATION,
        artifact=artifact,
        allowed_origins=frozenset({VERIFIED_SCIENTIFIC_OPERATION}),
    )
    return normalized, alternate_sequence


def run_esm_substitution_artifact(
    *,
    executor: ESMScientificExecutor | None,
    verification_artifact: JsonObject,
    public_reference_protein_sequence: object,
) -> JsonObject:
    if executor is None:
        raise ResearchScientificOperationUnavailable(
            "esm_scientific_executor_not_configured"
        )
    reference_sequence = canonical_public_reference_sequence(
        public_reference_protein_sequence
    )
    verification_input = _verification_input(verification_artifact)
    if _sequence_sha256(reference_sequence) != verification_input.get(
        "reference_sequence_sha256"
    ):
        raise ValueError(
            "the supplied public reference sequence does not match the Genomi verification artifact"
        )
    reference_residue, position, alternate_residue = substitution_parts(
        verification_input.get("protein_substitution")
    )
    if position > len(reference_sequence) or reference_sequence[
        position - 1
    ] != reference_residue:
        raise ValueError(
            "the supplied public reference sequence no longer supports the verified substitution"
        )
    alternate_sequence = (
        reference_sequence[: position - 1]
        + alternate_residue
        + reference_sequence[position:]
    )
    if _sequence_sha256(alternate_sequence) != verification_input.get(
        "alternate_sequence_sha256"
    ):
        raise ValueError(
            "the derived alternate sequence does not match the Genomi verification artifact"
        )
    request = {
        "gene": verification_input["gene"],
        "transcript_accession": verification_input["transcript_accession"],
        "protein_accession": verification_input["protein_accession"],
        "protein_substitution": verification_input["protein_substitution"],
        "reference_sequence": reference_sequence,
        "alternate_sequence": alternate_sequence,
        "required_execution_location": "local",
        "required_network_access": "disabled",
    }
    result = _executor_result(executor(request), "ESM")
    artifact = {
        "artifact_kind": ESM_NONCLINICAL_COMPARISON,
        "method": result["method"],
        "model": result["model"],
        "input": dict(verification_input),
        "output": result["output"],
        "provenance": {
            "execution_class": VERIFIED_SCIENTIFIC_OPERATION,
            **result["provenance"],
        },
    }
    _kind, _origin, normalized = normalize_research_artifact(
        origin=VERIFIED_SCIENTIFIC_OPERATION,
        artifact=artifact,
        allowed_origins=frozenset({VERIFIED_SCIENTIFIC_OPERATION}),
    )
    return normalized


def run_proto_blinded_design_artifact(
    *,
    executor: ProtoScientificExecutor | None,
    verification_artifact: JsonObject,
    objective: object,
    required_arm_classes: object,
    readouts: object,
) -> JsonObject:
    if executor is None:
        raise ResearchScientificOperationUnavailable(
            "proto_scientific_executor_not_configured"
        )
    verification_input = _verification_input(verification_artifact)
    request = {
        "gene": verification_input["gene"],
        "protein_accession": verification_input["protein_accession"],
        "protein_substitution": verification_input["protein_substitution"],
        "objective": objective,
        "required_arm_classes": required_arm_classes,
        "readouts": readouts,
        "required_execution_location": "local",
        "required_network_access": "disabled",
    }
    result = _executor_result(executor(request), "Proto")
    artifact = {
        "artifact_kind": PROTO_BLINDED_EXPERIMENTAL_DESIGN,
        "method": result["method"],
        "model": result["model"],
        "input": {
            "gene": verification_input["gene"],
            "protein_accession": verification_input["protein_accession"],
            "protein_substitution": verification_input["protein_substitution"],
            "objective": objective,
            "required_arm_classes": required_arm_classes,
            "readouts": readouts,
        },
        "output": result["output"],
        "provenance": {
            "execution_class": VERIFIED_SCIENTIFIC_OPERATION,
            **result["provenance"],
        },
    }
    _kind, _origin, normalized = normalize_research_artifact(
        origin=VERIFIED_SCIENTIFIC_OPERATION,
        artifact=artifact,
        allowed_origins=frozenset({VERIFIED_SCIENTIFIC_OPERATION}),
    )
    return normalized


def scientific_operations_manifest(
    *,
    esm_executor: ESMScientificExecutor | None,
    proto_executor: ProtoScientificExecutor | None,
) -> JsonObject:
    return {
        "genomilab.verify_sequence_substitution": {
            "availability": "available",
            "execution_location": "local",
            "network_access": "disabled",
            "operation_kind": "deterministic_sequence_verification",
        },
        "genomilab.run_esm_substitution_analysis": {
            "availability": (
                "available" if esm_executor is not None else "unavailable"
            ),
            "unavailable_state": (
                None
                if esm_executor is not None
                else "esm_scientific_executor_not_configured"
            ),
            "execution_location": "local",
            "network_access": "disabled",
            "operation_kind": "protein_model_substitution_comparison",
        },
        "genomilab.run_proto_blinded_experiment_design": {
            "availability": (
                "available" if proto_executor is not None else "unavailable"
            ),
            "unavailable_state": (
                None
                if proto_executor is not None
                else "proto_scientific_executor_not_configured"
            ),
            "execution_location": "local",
            "network_access": "disabled",
            "operation_kind": "blinded_experimental_design",
        },
    }


def _verification_input(artifact: JsonObject) -> JsonObject:
    if artifact.get("artifact_kind") != GENOMI_SEQUENCE_SUBSTITUTION_VERIFICATION:
        raise ValueError(
            "sequence_verification_artifact_id must identify a Genomi sequence verification"
        )
    payload = artifact.get("artifact")
    if not isinstance(payload, dict):
        raise ValueError("the Genomi sequence verification artifact is unavailable")
    output = payload.get("output")
    if not isinstance(output, dict) or output.get(
        "protein_substitution_verified"
    ) is not True:
        raise ValueError("the Genomi artifact does not verify the substitution")
    input_value = payload.get("input")
    if not isinstance(input_value, dict):
        raise ValueError("the Genomi verification input is unavailable")
    return dict(input_value)


def _executor_result(value: object, label: str) -> JsonObject:
    if not isinstance(value, Mapping) or set(value) != {
        "method",
        "model",
        "output",
        "provenance",
    }:
        raise ValueError(
            f"{label} scientific executor must return exactly method, model, output, and provenance"
        )
    provenance = value.get("provenance")
    if not isinstance(provenance, Mapping) or set(provenance) != {
        "execution_location",
        "network_access",
        "source_label",
        "source_version",
        "source_record_id",
    }:
        raise ValueError(f"{label} scientific executor returned invalid provenance")
    if (
        provenance.get("execution_location") != "local"
        or provenance.get("network_access") != "disabled"
    ):
        raise ValueError(
            f"{label} scientific executor must attest local, network-disabled execution"
        )
    return {
        "method": dict(value["method"]) if isinstance(value.get("method"), Mapping) else value.get("method"),
        "model": dict(value["model"]) if isinstance(value.get("model"), Mapping) else value.get("model"),
        "output": dict(value["output"]) if isinstance(value.get("output"), Mapping) else value.get("output"),
        "provenance": dict(provenance),
    }


def _sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


__all__ = [
    "ESMScientificExecutor",
    "ProtoScientificExecutor",
    "ResearchScientificOperationUnavailable",
    "SCIENTIFIC_OPERATION_USE_BOUNDARY",
    "run_esm_substitution_artifact",
    "run_proto_blinded_design_artifact",
    "scientific_operations_manifest",
    "verify_sequence_substitution_artifact",
]
