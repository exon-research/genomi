"""Illustrative ESM/Proto result fixtures backed by demonstration datasets."""

from __future__ import annotations

from .constants import JsonObject


def esm_precomputed_fixture(sequence_input: JsonObject) -> JsonObject:
    """Build an illustrative ESM-shaped card from Genomi's sequence digests."""

    return {
        "artifact_kind": "esm_nonclinical_comparison",
        "method": {
            "name": "illustrative_masked_marginal_comparison",
            "version": "fixture-contract-1",
        },
        "model": {
            "name": "ESM illustrative demo result",
            "version": "fixture-2026-08-15",
        },
        "input": {
            key: sequence_input[key]
            for key in (
                "gene",
                "transcript_accession",
                "protein_accession",
                "protein_substitution",
                "reference_sequence_sha256",
                "alternate_sequence_sha256",
            )
        },
        "output": {
            "metric": "illustrative_masked_marginal_log_probability",
            "reference_score": -1.0,
            "alternate_score": -1.75,
            "delta": -0.75,
        },
        "provenance": {
            "execution_class": "precomputed_fixture",
            "execution_location": "not_verified",
            "network_access": "not_verified",
            "source_label": "GenomiLab ESM demonstration dataset",
            "source_version": "1",
            "source_record_id": "esm-precomputed-demo-q76h-001",
        },
    }


def proto_precomputed_fixture(sequence_input: JsonObject) -> JsonObject:
    """Build an illustrative Proto-shaped design card."""

    return {
        "artifact_kind": "proto_blinded_experimental_design",
        "method": {
            "name": "illustrative_blinded_control_design",
            "version": "fixture-contract-1",
        },
        "model": {
            "name": "Proto illustrative demo result",
            "version": "fixture-2026-08-15",
        },
        "input": {
            "gene": sequence_input["gene"],
            "protein_accession": sequence_input["protein_accession"],
            "protein_substitution": sequence_input["protein_substitution"],
            "objective": "Separate CTLA4 abundance from CD80 and CD86 ligand-removal function.",
            "required_arm_classes": [
                "wild_type_reference",
                "test_variant",
                "assay_negative_control",
                "functional_loss_control",
            ],
            "readouts": ["ctla4_abundance", "cd80_cd86_ligand_removal"],
        },
        "output": {
            "blinded_arm_labels": ["Arm A", "Arm B", "Arm C", "Arm D"],
            "quality_controls": [
                "Prespecify assay acceptance criteria.",
                "Measure abundance and ligand removal separately.",
            ],
            "analysis_plan": [
                "Compare blinded wild-type, Q76H, assay-negative, and functional-loss arms.",
                "Interpret repeatability before unblinding the test-variant arm.",
            ],
        },
        "provenance": {
            "execution_class": "precomputed_fixture",
            "execution_location": "not_verified",
            "network_access": "not_verified",
            "source_label": "GenomiLab Proto demonstration dataset",
            "source_version": "1",
            "source_record_id": "proto-precomputed-demo-q76h-001",
        },
    }
