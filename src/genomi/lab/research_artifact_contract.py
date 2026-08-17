"""Strict, research-only contracts for mechanistic computation artifacts.

Research artifacts are immutable records of a bounded scientific computation or
of a host-supplied fixture.  They are deliberately a different record type from
GenomiLab evidence: an artifact cannot support a hypothesis, enter a clinical
brief, or change answer-readiness.  Stored inputs contain identifiers and
digests, never a protein sequence or raw genome material.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from .artifact_payload import safe_json_value
from .models import JsonObject, required_text, validate_private_payload


ESM_NONCLINICAL_COMPARISON = "esm_nonclinical_comparison"
PROTO_BLINDED_EXPERIMENTAL_DESIGN = "proto_blinded_experimental_design"
GENOMI_SEQUENCE_SUBSTITUTION_VERIFICATION = (
    "genomi_sequence_substitution_verification"
)
RESEARCH_ARTIFACT_KINDS = frozenset(
    {
        ESM_NONCLINICAL_COMPARISON,
        PROTO_BLINDED_EXPERIMENTAL_DESIGN,
        GENOMI_SEQUENCE_SUBSTITUTION_VERIFICATION,
    }
)

PRECOMPUTED_FIXTURE = "precomputed_fixture"
HOST_SUPPLIED_UNVERIFIED = "host_supplied_unverified"
VERIFIED_SCIENTIFIC_OPERATION = "verified_scientific_operation"
RESEARCH_ARTIFACT_ORIGINS = frozenset(
    {
        PRECOMPUTED_FIXTURE,
        HOST_SUPPLIED_UNVERIFIED,
        VERIFIED_SCIENTIFIC_OPERATION,
    }
)
HOST_SUBMISSION_ORIGINS = frozenset(
    {PRECOMPUTED_FIXTURE, HOST_SUPPLIED_UNVERIFIED}
)

_SUBSTITUTION_RE = re.compile(r"^([A-Z])([1-9][0-9]*)([A-Z])$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:+-]{0,199}$")
_READOUT_RE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
_CANONICAL_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
_ARM_CLASSES = frozenset(
    {
        "wild_type_reference",
        "test_variant",
        "assay_negative_control",
        "functional_loss_control",
    }
)

RESEARCH_ARTIFACT_USE_BOUNDARY: JsonObject = {
    "nonclinical": True,
    "record_class": "nonclinical_research_artifact",
    "eligible_as_evidence_record": False,
    "eligible_for_hypothesis_support": False,
    "eligible_for_brief_claim": False,
    "eligible_for_answer_readiness": False,
    "eligible_for_active_genome_index_ingestion": False,
    "eligible_for_treatment_content": False,
    "eligible_for_clinician_export": False,
}


def _object_schema(required: tuple[str, ...], properties: JsonObject) -> JsonObject:
    return {
        "type": "object",
        "required": list(required),
        "properties": properties,
        "additionalProperties": False,
    }


_VERSIONED_COMPONENT_SCHEMA = _object_schema(
    ("name", "version"),
    {
        "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "version": {"type": "string", "minLength": 1, "maxLength": 200},
    },
)

_PROVENANCE_SCHEMA = _object_schema(
    (
        "execution_class",
        "execution_location",
        "network_access",
        "source_label",
        "source_version",
        "source_record_id",
    ),
    {
        "execution_class": {
            "type": "string",
            "enum": sorted(RESEARCH_ARTIFACT_ORIGINS),
        },
        "execution_location": {
            "type": "string",
            "enum": ["local", "not_verified"],
        },
        "network_access": {
            "type": "string",
            "enum": ["disabled", "not_verified"],
        },
        "source_label": {"type": "string", "minLength": 1, "maxLength": 300},
        "source_version": {"type": "string", "minLength": 1, "maxLength": 200},
        "source_record_id": {"type": "string", "minLength": 1, "maxLength": 300},
    },
)

_SEQUENCE_DIGEST_INPUT_PROPERTIES: JsonObject = {
    "gene": {"type": "string", "minLength": 1, "maxLength": 80},
    "transcript_accession": {"type": "string", "minLength": 1, "maxLength": 200},
    "protein_accession": {"type": "string", "minLength": 1, "maxLength": 200},
    "protein_substitution": {
        "type": "string",
        "pattern": "^[A-Z][1-9][0-9]*[A-Z]$",
    },
    "reference_sequence_sha256": {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$",
    },
    "alternate_sequence_sha256": {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$",
    },
}

_ESM_INPUT_SCHEMA = _object_schema(
    tuple(_SEQUENCE_DIGEST_INPUT_PROPERTIES),
    dict(_SEQUENCE_DIGEST_INPUT_PROPERTIES),
)
_ESM_OUTPUT_SCHEMA = _object_schema(
    ("metric", "reference_score", "alternate_score", "delta"),
    {
        "metric": {"type": "string", "minLength": 1, "maxLength": 200},
        "reference_score": {"type": "number"},
        "alternate_score": {"type": "number"},
        "delta": {"type": "number"},
    },
)

_PROTO_INPUT_SCHEMA = _object_schema(
    (
        "gene",
        "protein_accession",
        "protein_substitution",
        "objective",
        "required_arm_classes",
        "readouts",
    ),
    {
        "gene": {"type": "string", "minLength": 1, "maxLength": 80},
        "protein_accession": {"type": "string", "minLength": 1, "maxLength": 200},
        "protein_substitution": {
            "type": "string",
            "pattern": "^[A-Z][1-9][0-9]*[A-Z]$",
        },
        "objective": {"type": "string", "minLength": 1, "maxLength": 500},
        "required_arm_classes": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "uniqueItems": True,
            "items": {"type": "string", "enum": sorted(_ARM_CLASSES)},
        },
        "readouts": {
            "type": "array",
            "minItems": 2,
            "maxItems": 10,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "pattern": "^[a-z][a-z0-9_]{0,99}$",
            },
        },
    },
)
_PROTO_OUTPUT_SCHEMA = _object_schema(
    ("blinded_arm_labels", "quality_controls", "analysis_plan"),
    {
        "blinded_arm_labels": {
            "type": "array",
            "minItems": 4,
            "maxItems": 12,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1, "maxLength": 40},
        },
        "quality_controls": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "analysis_plan": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        },
    },
)

_GENOMI_INPUT_SCHEMA = _object_schema(
    (
        "gene",
        "transcript_accession",
        "protein_accession",
        "coding_change",
        "protein_substitution",
        "reference_sequence_sha256",
        "alternate_sequence_sha256",
    ),
    {
        **_SEQUENCE_DIGEST_INPUT_PROPERTIES,
        "coding_change": {"type": "string", "minLength": 1, "maxLength": 200},
    },
)
_GENOMI_OUTPUT_SCHEMA = _object_schema(
    (
        "position",
        "reference_residue",
        "alternate_residue",
        "protein_substitution_verified",
    ),
    {
        "position": {"type": "integer", "minimum": 1},
        "reference_residue": {"type": "string", "pattern": "^[A-Z]$"},
        "alternate_residue": {"type": "string", "pattern": "^[A-Z]$"},
        "protein_substitution_verified": {"type": "boolean", "const": True},
    },
)


def _artifact_schema(
    artifact_kind: str, input_schema: JsonObject, output_schema: JsonObject
) -> JsonObject:
    return _object_schema(
        ("artifact_kind", "method", "model", "input", "output", "provenance"),
        {
            "artifact_kind": {"type": "string", "const": artifact_kind},
            "method": _VERSIONED_COMPONENT_SCHEMA,
            "model": _VERSIONED_COMPONENT_SCHEMA,
            "input": input_schema,
            "output": output_schema,
            "provenance": _PROVENANCE_SCHEMA,
        },
    )


_ESM_ARTIFACT_SCHEMA = _artifact_schema(
    ESM_NONCLINICAL_COMPARISON, _ESM_INPUT_SCHEMA, _ESM_OUTPUT_SCHEMA
)
_PROTO_ARTIFACT_SCHEMA = _artifact_schema(
    PROTO_BLINDED_EXPERIMENTAL_DESIGN, _PROTO_INPUT_SCHEMA, _PROTO_OUTPUT_SCHEMA
)
_GENOMI_ARTIFACT_SCHEMA = _artifact_schema(
    GENOMI_SEQUENCE_SUBSTITUTION_VERIFICATION,
    _GENOMI_INPUT_SCHEMA,
    _GENOMI_OUTPUT_SCHEMA,
)


def research_artifact_submission_input_schema() -> JsonObject:
    """Return the exact MCP input schema for host-submitted artifacts."""

    return _object_schema(
        (
            "investigation_id",
            "round_id",
            "deduplication_key",
            "origin",
            "artifact",
        ),
        {
            "investigation_id": {"type": "string", "minLength": 1},
            "round_id": {"type": "string", "minLength": 1},
            "deduplication_key": {
                "type": "string",
                "minLength": 1,
                "maxLength": 300,
            },
            "origin": {
                "type": "string",
                "enum": sorted(HOST_SUBMISSION_ORIGINS),
            },
            "artifact": {
                "oneOf": [
                    _ESM_ARTIFACT_SCHEMA,
                    _PROTO_ARTIFACT_SCHEMA,
                    _GENOMI_ARTIFACT_SCHEMA,
                ]
            },
        },
    )


def sequence_substitution_verification_input_schema() -> JsonObject:
    """Return the transient-input contract for local Genomi verification."""

    return _object_schema(
        (
            "investigation_id",
            "round_id",
            "deduplication_key",
            "gene",
            "transcript_accession",
            "protein_accession",
            "coding_change",
            "protein_substitution",
            "public_reference_protein_sequence",
            "reference_source_label",
            "reference_source_version",
            "reference_source_record_id",
        ),
        {
            "investigation_id": {"type": "string", "minLength": 1},
            "round_id": {"type": "string", "minLength": 1},
            "deduplication_key": {"type": "string", "minLength": 1, "maxLength": 300},
            "gene": {"type": "string", "minLength": 1, "maxLength": 80},
            "transcript_accession": {"type": "string", "minLength": 1, "maxLength": 200},
            "protein_accession": {"type": "string", "minLength": 1, "maxLength": 200},
            "coding_change": {"type": "string", "minLength": 1, "maxLength": 200},
            "protein_substitution": {
                "type": "string",
                "pattern": "^[A-Z][1-9][0-9]*[A-Z]$",
            },
            "public_reference_protein_sequence": {
                "type": "string",
                "minLength": 1,
                "maxLength": 10_000,
                "pattern": "^[ACDEFGHIKLMNPQRSTVWY]+$",
            },
            "reference_source_label": {"type": "string", "minLength": 1, "maxLength": 300},
            "reference_source_version": {"type": "string", "minLength": 1, "maxLength": 200},
            "reference_source_record_id": {"type": "string", "minLength": 1, "maxLength": 300},
        },
    )


def esm_substitution_analysis_input_schema() -> JsonObject:
    return _object_schema(
        (
            "investigation_id",
            "round_id",
            "deduplication_key",
            "sequence_verification_artifact_id",
            "public_reference_protein_sequence",
        ),
        {
            "investigation_id": {"type": "string", "minLength": 1},
            "round_id": {"type": "string", "minLength": 1},
            "deduplication_key": {"type": "string", "minLength": 1, "maxLength": 300},
            "sequence_verification_artifact_id": {"type": "string", "minLength": 1},
            "public_reference_protein_sequence": {
                "type": "string",
                "minLength": 1,
                "maxLength": 10_000,
                "pattern": "^[ACDEFGHIKLMNPQRSTVWY]+$",
            },
        },
    )


def proto_blinded_design_input_schema() -> JsonObject:
    return _object_schema(
        (
            "investigation_id",
            "round_id",
            "deduplication_key",
            "sequence_verification_artifact_id",
            "objective",
            "required_arm_classes",
            "readouts",
        ),
        {
            "investigation_id": {"type": "string", "minLength": 1},
            "round_id": {"type": "string", "minLength": 1},
            "deduplication_key": {"type": "string", "minLength": 1, "maxLength": 300},
            "sequence_verification_artifact_id": {"type": "string", "minLength": 1},
            "objective": {"type": "string", "minLength": 1, "maxLength": 500},
            "required_arm_classes": _PROTO_INPUT_SCHEMA["properties"]["required_arm_classes"],
            "readouts": _PROTO_INPUT_SCHEMA["properties"]["readouts"],
        },
    )


def normalize_research_artifact(
    *,
    origin: object,
    artifact: object,
    allowed_origins: frozenset[str] = RESEARCH_ARTIFACT_ORIGINS,
) -> tuple[str, str, JsonObject]:
    """Validate and detach one research artifact without accepting raw sequence."""

    origin_value = required_text(origin, "origin", 80)
    if origin_value not in allowed_origins:
        raise ValueError("origin is not permitted for this research-artifact route")
    detached = safe_json_value(artifact)
    if not isinstance(detached, dict):
        raise ValueError("artifact must be an object")
    validate_private_payload(detached)
    kind = required_text(detached.get("artifact_kind"), "artifact_kind", 100)
    if kind == ESM_NONCLINICAL_COMPARISON:
        normalized = _normalize_esm_artifact(detached)
    elif kind == PROTO_BLINDED_EXPERIMENTAL_DESIGN:
        normalized = _normalize_proto_artifact(detached)
    elif kind == GENOMI_SEQUENCE_SUBSTITUTION_VERIFICATION:
        normalized = _normalize_genomi_artifact(detached)
    else:
        raise ValueError("unsupported research artifact kind")
    provenance = normalized["provenance"]
    if provenance["execution_class"] != origin_value:
        raise ValueError("artifact provenance execution_class must equal origin")
    if origin_value == VERIFIED_SCIENTIFIC_OPERATION:
        if (
            provenance["execution_location"] != "local"
            or provenance["network_access"] != "disabled"
        ):
            raise ValueError(
                "verified patient-workflow computation must be local with network access disabled"
            )
    elif (
        provenance["execution_location"] != "not_verified"
        or provenance["network_access"] != "not_verified"
    ):
        raise ValueError(
            "unverified or fixture provenance cannot claim an execution location"
        )
    return kind, origin_value, normalized


def _normalize_esm_artifact(value: Mapping[str, Any]) -> JsonObject:
    _require_exact_fields(value, tuple(_ESM_ARTIFACT_SCHEMA["properties"]), "ESM research artifact")
    input_value = _normalize_sequence_digest_input(value.get("input"))
    output_value = _mapping(value.get("output"), "output")
    _require_exact_fields(
        output_value, tuple(_ESM_OUTPUT_SCHEMA["properties"]), "ESM output"
    )
    reference_score = _finite_number(output_value.get("reference_score"), "reference_score")
    alternate_score = _finite_number(output_value.get("alternate_score"), "alternate_score")
    delta = _finite_number(output_value.get("delta"), "delta")
    if not math.isclose(delta, alternate_score - reference_score, rel_tol=1e-7, abs_tol=1e-7):
        raise ValueError("delta must equal alternate_score minus reference_score")
    return {
        "artifact_kind": ESM_NONCLINICAL_COMPARISON,
        "method": _normalize_versioned_component(value.get("method"), "method"),
        "model": _normalize_versioned_component(value.get("model"), "model"),
        "input": input_value,
        "output": {
            "metric": required_text(output_value.get("metric"), "metric", 200),
            "reference_score": reference_score,
            "alternate_score": alternate_score,
            "delta": delta,
        },
        "provenance": _normalize_provenance(value.get("provenance")),
    }


def _normalize_proto_artifact(value: Mapping[str, Any]) -> JsonObject:
    _require_exact_fields(value, tuple(_PROTO_ARTIFACT_SCHEMA["properties"]), "Proto research artifact")
    input_value = _mapping(value.get("input"), "input")
    _require_exact_fields(
        input_value, tuple(_PROTO_INPUT_SCHEMA["properties"]), "Proto input"
    )
    arm_classes = _text_array(
        input_value.get("required_arm_classes"),
        "required_arm_classes",
        minimum=4,
        maximum=4,
        item_maximum=80,
    )
    if set(arm_classes) != _ARM_CLASSES:
        raise ValueError("required_arm_classes must contain the four fixed control classes")
    readouts = _identifier_array(
        input_value.get("readouts"), "readouts", minimum=2, maximum=10
    )
    output_value = _mapping(value.get("output"), "output")
    _require_exact_fields(
        output_value, tuple(_PROTO_OUTPUT_SCHEMA["properties"]), "Proto output"
    )
    return {
        "artifact_kind": PROTO_BLINDED_EXPERIMENTAL_DESIGN,
        "method": _normalize_versioned_component(value.get("method"), "method"),
        "model": _normalize_versioned_component(value.get("model"), "model"),
        "input": {
            "gene": _identifier(input_value.get("gene"), "gene"),
            "protein_accession": _identifier(input_value.get("protein_accession"), "protein_accession"),
            "protein_substitution": _substitution(input_value.get("protein_substitution")),
            "objective": required_text(input_value.get("objective"), "objective", 500),
            "required_arm_classes": arm_classes,
            "readouts": readouts,
        },
        "output": {
            "blinded_arm_labels": _text_array(
                output_value.get("blinded_arm_labels"), "blinded_arm_labels", minimum=4, maximum=12, item_maximum=40
            ),
            "quality_controls": _text_array(
                output_value.get("quality_controls"), "quality_controls", minimum=1, maximum=20, item_maximum=500
            ),
            "analysis_plan": _text_array(
                output_value.get("analysis_plan"), "analysis_plan", minimum=1, maximum=20, item_maximum=500
            ),
        },
        "provenance": _normalize_provenance(value.get("provenance")),
    }


def _normalize_genomi_artifact(value: Mapping[str, Any]) -> JsonObject:
    _require_exact_fields(value, tuple(_GENOMI_ARTIFACT_SCHEMA["properties"]), "Genomi research artifact")
    input_value = _mapping(value.get("input"), "input")
    _require_exact_fields(
        input_value, tuple(_GENOMI_INPUT_SCHEMA["properties"]), "Genomi input"
    )
    sequence_input = _normalize_sequence_digest_input(input_value)
    output_value = _mapping(value.get("output"), "output")
    _require_exact_fields(
        output_value, tuple(_GENOMI_OUTPUT_SCHEMA["properties"]), "Genomi output"
    )
    reference, position, alternate = _substitution_parts(
        sequence_input["protein_substitution"]
    )
    if output_value.get("protein_substitution_verified") is not True:
        raise ValueError("protein_substitution_verified must be true")
    if (
        output_value.get("position") != position
        or output_value.get("reference_residue") != reference
        or output_value.get("alternate_residue") != alternate
    ):
        raise ValueError("Genomi output must match the normalized substitution")
    return {
        "artifact_kind": GENOMI_SEQUENCE_SUBSTITUTION_VERIFICATION,
        "method": _normalize_versioned_component(value.get("method"), "method"),
        "model": _normalize_versioned_component(value.get("model"), "model"),
        "input": {
            **sequence_input,
            "coding_change": required_text(input_value.get("coding_change"), "coding_change", 200),
        },
        "output": {
            "position": position,
            "reference_residue": reference,
            "alternate_residue": alternate,
            "protein_substitution_verified": True,
        },
        "provenance": _normalize_provenance(value.get("provenance")),
    }


def research_artifact_envelope(
    *, artifact_kind: str, system: str, origin: str
) -> JsonObject:
    """Return a non-evidence envelope that has no answer-readiness field."""

    scientific_execution = {
        PRECOMPUTED_FIXTURE: "precomputed_fixture",
        HOST_SUPPLIED_UNVERIFIED: "not_verified",
        VERIFIED_SCIENTIFIC_OPERATION: "verified_local_execution",
    }[origin]
    if origin != VERIFIED_SCIENTIFIC_OPERATION:
        provider_execution = "not_verified"
    elif system == "genomi":
        provider_execution = "not_applicable_local_genomi"
    else:
        provider_execution = "verified_by_scientific_adapter"
    return {
        "record_class": "nonclinical_research_artifact",
        "artifact_kind": artifact_kind,
        "system": system,
        "clinical_evidence_status": "ineligible",
        "answer_readiness_effect": "none",
        "scientific_execution_status": scientific_execution,
        "provider_execution_status": provider_execution,
        "use_boundary": dict(RESEARCH_ARTIFACT_USE_BOUNDARY),
    }


def research_artifact_view(record: Mapping[str, Any]) -> JsonObject:
    """Present research-only status first and preserve exact round linkage."""

    return {
        "research_envelope": dict(record.get("research_envelope") or {}),
        "research_artifact_id": record.get("research_artifact_id"),
        "investigation_id": record.get("investigation_id"),
        "patient_molecular_snapshot_id": record.get("patient_molecular_snapshot_id"),
        "round_id": record.get("round_id"),
        **({"round_number": record.get("round_number")} if record.get("round_number") is not None else {}),
        "artifact_kind": record.get("artifact_kind"),
        "system": record.get("system"),
        "origin": record.get("origin"),
        "deduplication_key": record.get("deduplication_key"),
        "content_sha256": record.get("content_sha256"),
        "artifact": dict(record.get("artifact") or {}),
        "use_boundary": dict(RESEARCH_ARTIFACT_USE_BOUNDARY),
        "created_at": record.get("created_at"),
    }


def research_artifact_system(artifact_kind: str) -> str:
    if artifact_kind == ESM_NONCLINICAL_COMPARISON:
        return "esm"
    if artifact_kind == PROTO_BLINDED_EXPERIMENTAL_DESIGN:
        return "proto"
    if artifact_kind == GENOMI_SEQUENCE_SUBSTITUTION_VERIFICATION:
        return "genomi"
    raise ValueError("unsupported research artifact kind")


def canonical_public_reference_sequence(value: object) -> str:
    sequence = required_text(value, "public_reference_protein_sequence", 10_000).upper()
    if any(residue not in _CANONICAL_AMINO_ACIDS for residue in sequence):
        raise ValueError(
            "public_reference_protein_sequence must contain canonical amino-acid letters only"
        )
    return sequence


def substitution_parts(value: object) -> tuple[str, int, str]:
    return _substitution_parts(_substitution(value))


def _normalize_sequence_digest_input(value: object) -> JsonObject:
    item = _mapping(value, "input")
    required_fields = tuple(_SEQUENCE_DIGEST_INPUT_PROPERTIES)
    allowed = set(required_fields) | {"coding_change"}
    if not set(item).issubset(allowed) or not set(required_fields).issubset(item):
        raise ValueError(
            "sequence input must contain gene, transcript_accession, protein_accession, protein_substitution, reference_sequence_sha256, and alternate_sequence_sha256"
        )
    return {
        "gene": _identifier(item.get("gene"), "gene"),
        "transcript_accession": _identifier(item.get("transcript_accession"), "transcript_accession"),
        "protein_accession": _identifier(item.get("protein_accession"), "protein_accession"),
        "protein_substitution": _substitution(item.get("protein_substitution")),
        "reference_sequence_sha256": _sha256(item.get("reference_sequence_sha256"), "reference_sequence_sha256"),
        "alternate_sequence_sha256": _sha256(item.get("alternate_sequence_sha256"), "alternate_sequence_sha256"),
    }


def _normalize_versioned_component(value: object, field: str) -> JsonObject:
    item = _mapping(value, field)
    _require_exact_fields(item, ("name", "version"), field)
    return {
        "name": required_text(item.get("name"), f"{field}.name", 200),
        "version": required_text(item.get("version"), f"{field}.version", 200),
    }


def _normalize_provenance(value: object) -> JsonObject:
    item = _mapping(value, "provenance")
    fields = tuple(_PROVENANCE_SCHEMA["properties"])
    _require_exact_fields(item, fields, "provenance")
    execution_class = required_text(item.get("execution_class"), "execution_class", 80)
    if execution_class not in RESEARCH_ARTIFACT_ORIGINS:
        raise ValueError("unsupported provenance execution_class")
    execution_location = required_text(item.get("execution_location"), "execution_location", 80)
    if execution_location not in {"local", "not_verified"}:
        raise ValueError("unsupported provenance execution_location")
    network_access = required_text(item.get("network_access"), "network_access", 80)
    if network_access not in {"disabled", "not_verified"}:
        raise ValueError("unsupported provenance network_access")
    return {
        "execution_class": execution_class,
        "execution_location": execution_location,
        "network_access": network_access,
        "source_label": required_text(item.get("source_label"), "source_label", 300),
        "source_version": required_text(item.get("source_version"), "source_version", 200),
        "source_record_id": required_text(item.get("source_record_id"), "source_record_id", 300),
    }


def _require_exact_fields(value: Mapping[str, Any], fields: tuple[str, ...], label: str) -> None:
    if set(value) != set(fields):
        raise ValueError(f"{label} must contain exactly: {', '.join(fields)}")


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _identifier(value: object, field: str) -> str:
    identifier = required_text(value, field, 200)
    if not _IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"{field} contains unsupported characters")
    return identifier


def _sha256(value: object, field: str) -> str:
    digest = required_text(value, field, 64).lower()
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return digest


def _substitution(value: object) -> str:
    substitution = required_text(value, "protein_substitution", 80).upper()
    match = _SUBSTITUTION_RE.fullmatch(substitution)
    if match is None or match.group(1) not in _CANONICAL_AMINO_ACIDS or match.group(3) not in _CANONICAL_AMINO_ACIDS:
        raise ValueError("protein_substitution must use one-letter protein notation such as Q76H")
    if match.group(1) == match.group(3):
        raise ValueError("protein_substitution must change the amino acid")
    return substitution


def _substitution_parts(value: str) -> tuple[str, int, str]:
    match = _SUBSTITUTION_RE.fullmatch(value)
    if match is None:
        raise ValueError("invalid protein substitution")
    return match.group(1), int(match.group(2)), match.group(3)


def _text_array(
    value: object,
    field: str,
    *,
    minimum: int,
    maximum: int,
    item_maximum: int,
) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{field} must contain between {minimum} and {maximum} items")
    result = [required_text(item, field, item_maximum) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f"{field} must contain unique items")
    return result


def _identifier_array(
    value: object, field: str, *, minimum: int, maximum: int
) -> list[str]:
    result = _text_array(
        value, field, minimum=minimum, maximum=maximum, item_maximum=100
    )
    if any(not _READOUT_RE.fullmatch(item) for item in result):
        raise ValueError(f"{field} must contain lowercase underscore identifiers")
    return result


__all__ = [
    "ESM_NONCLINICAL_COMPARISON",
    "GENOMI_SEQUENCE_SUBSTITUTION_VERIFICATION",
    "HOST_SUBMISSION_ORIGINS",
    "HOST_SUPPLIED_UNVERIFIED",
    "PRECOMPUTED_FIXTURE",
    "PROTO_BLINDED_EXPERIMENTAL_DESIGN",
    "RESEARCH_ARTIFACT_KINDS",
    "RESEARCH_ARTIFACT_ORIGINS",
    "RESEARCH_ARTIFACT_USE_BOUNDARY",
    "VERIFIED_SCIENTIFIC_OPERATION",
    "canonical_public_reference_sequence",
    "esm_substitution_analysis_input_schema",
    "normalize_research_artifact",
    "proto_blinded_design_input_schema",
    "research_artifact_envelope",
    "research_artifact_submission_input_schema",
    "research_artifact_system",
    "research_artifact_view",
    "sequence_substitution_verification_input_schema",
    "substitution_parts",
]
