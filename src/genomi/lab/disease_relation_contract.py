"""Typed disease-mechanism relation vocabulary and validation."""

from __future__ import annotations

import math

from ..evidence import envelope as canonical_evidence_envelope
from .models import JsonObject, required_text


REGISTER_DISEASE_RELATION = "investigation.register_disease_relation"
DISEASE_RELATION_RECORD_TYPE = "disease_mechanism_relation"

RELATION_KINDS = frozenset(
    {
        "variant_disease",
        "variant_consequence",
        "gene_disease",
        "phenotype_disease",
        "inheritance_segregation",
        "molecular_feature_disease",
        "molecular_mechanism",
        "gene_expression",
        "expression_qtl",
        "pathway_membership",
        "perturbation_effect",
        "protein_function",
        "drug_target",
        "treatment_biomarker",
        "regulatory_status",
        "trial_relevance",
        "hereditary_predisposition",
    }
)
RELATION_DIRECTIONS = frozenset({"supports", "refutes", "mixed", "context_only"})
CONTEXT_STATES = frozenset({"reported", "not_reported", "not_applicable"})
STRENGTH_STATES = frozenset({"reported", "not_reported"})
UNCERTAINTY_KINDS = frozenset(
    {
        "association_not_causation",
        "clinical_significance_not_established",
        "conflicting_evidence",
        "limited_population_generalizability",
        "mechanism_not_established",
        "source_not_reported",
        "specimen_mismatch",
        "tissue_mismatch",
    }
)
PUBLIC_SOURCE_FAMILIES = frozenset(
    {
        "literature",
        "regulatory",
        "trial_registry",
        "uniprot",
        "pdb",
        "chembl",
        "gencc",
        "hpo",
        "msigdb_hallmark",
    }
)
RELATION_KIND_SOURCE_FAMILIES = {
    "variant_disease": frozenset({"literature"}),
    "variant_consequence": frozenset({"literature", "uniprot"}),
    "gene_disease": frozenset({"literature", "gencc", "hpo"}),
    "phenotype_disease": frozenset({"literature", "hpo"}),
    "inheritance_segregation": frozenset({"literature", "gencc"}),
    "molecular_feature_disease": frozenset({"literature", "uniprot", "pdb", "chembl"}),
    "molecular_mechanism": frozenset(
        {"literature", "uniprot", "pdb", "chembl", "msigdb_hallmark"}
    ),
    "gene_expression": frozenset({"literature", "uniprot"}),
    "expression_qtl": frozenset({"literature"}),
    "pathway_membership": frozenset({"literature", "msigdb_hallmark"}),
    "perturbation_effect": frozenset({"literature"}),
    "protein_function": frozenset({"literature", "uniprot", "pdb"}),
    "drug_target": frozenset({"literature", "chembl"}),
    "treatment_biomarker": frozenset({"literature", "regulatory", "chembl"}),
    "regulatory_status": frozenset({"regulatory"}),
    "trial_relevance": frozenset({"trial_registry"}),
    "hereditary_predisposition": frozenset({"literature", "gencc"}),
}
_WEAK_STANDALONE_DOCUMENT_STATES = frozenset(
    {"abstract_only", "preprint", "trial_registration"}
)

_PARAMETER_FIELDS = frozenset(
    {
        "disease_scope",
        "profile_revision_ids",
        "source_evidence_record_ids",
        "relation_kind",
        "direction",
        "source_supplied_strength",
        "population_context",
        "tissue_context",
        "specimen_context",
        "conflicts",
        "uncertainty",
    }
)
_CONTEXT_FIELDS = frozenset({"state", "description", "source_locator"})
_STRENGTH_FIELDS = frozenset(
    {"state", "scheme", "raw_label", "raw_value", "source_locator"}
)
_CONFLICT_FIELDS = frozenset(
    {"source_evidence_record_id", "direction", "source_locator"}
)


def disease_relation_parameter_contract() -> JsonObject:
    """Return the fixed vocabulary for evidence relation records."""

    return {
        "relation_kind": sorted(RELATION_KINDS),
        "relation_kind_source_families": {
            kind: sorted(source_families)
            for kind, source_families in sorted(RELATION_KIND_SOURCE_FAMILIES.items())
        },
        "direction": sorted(RELATION_DIRECTIONS),
        "source_supplied_strength": {
            "state": sorted(STRENGTH_STATES),
            "required_fields": sorted(_STRENGTH_FIELDS),
        },
        "context": {
            "state": sorted(CONTEXT_STATES),
            "required_fields": sorted(_CONTEXT_FIELDS),
        },
        "conflicts": {
            "direction": ["mixed", "refutes"],
            "required_fields": sorted(_CONFLICT_FIELDS),
        },
        "uncertainty": sorted(UNCERTAINTY_KINDS),
    }


def relation_kind_accepts_source_family(
    relation_kind: object,
    source_family: object,
    *,
    direction: object,
) -> bool:
    """Mirror the commit-time source-prior gate for catalog template generation."""

    kind = str(relation_kind or "")
    family = str(source_family or "")
    relation_direction = str(direction or "")
    if relation_direction not in RELATION_DIRECTIONS:
        return False
    if family not in RELATION_KIND_SOURCE_FAMILIES.get(kind, frozenset()):
        return False
    return family != "trial_registry" or (
        kind == "trial_relevance" and relation_direction == "context_only"
    )


def validate_disease_relation_parameters(parameters: object) -> JsonObject:
    """Validate and detach the local relation request without inferring fields."""

    if not isinstance(parameters, dict) or set(parameters) != _PARAMETER_FIELDS:
        raise ValueError(
            "disease-relation request fields do not match the typed contract"
        )
    return {
        "disease_scope": required_text(
            parameters["disease_scope"], "disease_scope", 2_000
        ),
        "profile_revision_ids": _unique_text_array(
            parameters["profile_revision_ids"], "profile_revision_ids", empty=False
        ),
        "source_evidence_record_ids": _unique_text_array(
            parameters["source_evidence_record_ids"],
            "source_evidence_record_ids",
            empty=False,
        ),
        "relation_kind": _enum(
            parameters["relation_kind"], "relation_kind", RELATION_KINDS
        ),
        "direction": _enum(parameters["direction"], "direction", RELATION_DIRECTIONS),
        "source_supplied_strength": _validate_strength(
            parameters["source_supplied_strength"]
        ),
        "population_context": _validate_context(
            parameters["population_context"], "population_context"
        ),
        "tissue_context": _validate_context(
            parameters["tissue_context"], "tissue_context"
        ),
        "specimen_context": _validate_context(
            parameters["specimen_context"], "specimen_context"
        ),
        "conflicts": _validate_conflicts(parameters["conflicts"]),
        "uncertainty": _unique_enum_array(
            parameters["uncertainty"], "uncertainty", UNCERTAINTY_KINDS
        ),
    }


def eligible_public_relation_source(record: JsonObject) -> bool:
    """Whether a record can support/refute a disease relation."""

    if not eligible_public_context_source(record):
        return False
    evidence = record.get("evidence")
    source_records = evidence.get("records") if isinstance(evidence, dict) else None
    if isinstance(source_records, list) and source_records:
        declared_document_states = {
            str(item.get("source_document_state") or "")
            for item in source_records
            if isinstance(item, dict) and item.get("source_document_state")
        }
        if declared_document_states and declared_document_states.issubset(
            _WEAK_STANDALONE_DOCUMENT_STATES
        ):
            return False
    return True


def eligible_public_context_source(record: JsonObject) -> bool:
    """Whether a record may ground a context-only, non-claim relation."""

    if str(record.get("source_family") or "") not in PUBLIC_SOURCE_FAMILIES:
        return False
    if record.get("operation") == REGISTER_DISEASE_RELATION:
        return False
    evidence = record.get("evidence")
    if isinstance(evidence, dict):
        if evidence.get("may_raise_answer_readiness") is False:
            return False
        envelope_value = evidence.get("evidence_envelope")
        observations = (
            envelope_value.get("observations")
            if isinstance(envelope_value, dict)
            else None
        )
        if (
            evidence.get("model_verification") is not None
            and isinstance(observations, dict)
            and observations.get("independent_clinical_claim_ready") is False
        ):
            return False
    envelope = record.get("evidence_envelope")
    return (
        isinstance(envelope, dict)
        and envelope.get("finding_state")
        == (canonical_evidence_envelope.EVIDENCE_PRESENT)
        and envelope.get("answer_readiness")
        in {
            canonical_evidence_envelope.ANSWER_SUPPORTED,
            canonical_evidence_envelope.SCOPED_ANSWER_ONLY,
            canonical_evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
        }
    )


def is_qualifying_supporting_relation(
    record: JsonObject,
    *,
    disease_scope: str,
    exact_profile_revision_ids: set[str],
) -> bool:
    """Apply the shared candidate/brief relation predicate to a ledger row."""

    anchors = supporting_relation_anchor_ids(record, disease_scope=disease_scope)
    return anchors is not None and set(anchors) == exact_profile_revision_ids


def disease_relation_direction(record: JsonObject) -> str | None:
    """Return the validated direction of one committed relation ledger row."""

    if record.get("operation") != REGISTER_DISEASE_RELATION:
        return None
    evidence = record.get("evidence")
    if not isinstance(evidence, dict) or evidence.get("record_type") != (
        DISEASE_RELATION_RECORD_TYPE
    ):
        return None
    try:
        normalized = validate_disease_relation_parameters(
            evidence.get("disease_relation")
        )
    except ValueError:
        return None
    return str(normalized["direction"])


def supporting_relation_anchor_ids(
    record: JsonObject, *, disease_scope: str
) -> list[str] | None:
    """Return exact anchors only for a validated, supportive local relation."""

    if record.get("operation") != REGISTER_DISEASE_RELATION:
        return None
    if str(record.get("source_family") or "") not in PUBLIC_SOURCE_FAMILIES:
        return None
    evidence = record.get("evidence")
    if not isinstance(evidence, dict) or evidence.get("record_type") != (
        DISEASE_RELATION_RECORD_TYPE
    ):
        return None
    try:
        normalized = validate_disease_relation_parameters(
            evidence.get("disease_relation")
        )
    except ValueError:
        return None
    envelope = record.get("evidence_envelope")
    if not (
        normalized["direction"] == "supports"
        and normalized["disease_scope"] == disease_scope
        and isinstance(envelope, dict)
        and envelope.get("finding_state")
        == canonical_evidence_envelope.EVIDENCE_PRESENT
        and envelope.get("answer_readiness")
        == canonical_evidence_envelope.NEEDS_CLINICAL_CONFIRMATION
    ):
        return None
    return list(normalized["profile_revision_ids"])


def _enum(value: object, field: str, allowed: frozenset[str]) -> str:
    text = required_text(value, field, 100)
    if text not in allowed:
        raise ValueError(f"{field} must use the declared disease-relation vocabulary")
    return text


def _unique_text_array(value: object, field: str, *, empty: bool) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    result = [required_text(item, field, 1_000) for item in value]
    if not empty and not result:
        raise ValueError(f"{field} cannot be empty")
    if len(set(result)) != len(result):
        raise ValueError(f"{field} cannot contain duplicates")
    return result


def _unique_enum_array(value: object, field: str, allowed: frozenset[str]) -> list[str]:
    result = _unique_text_array(value, field, empty=True)
    if any(item not in allowed for item in result):
        raise ValueError(f"{field} must use the declared disease-relation vocabulary")
    return result


def _validate_context(value: object, field: str) -> JsonObject:
    if not isinstance(value, dict) or set(value) != _CONTEXT_FIELDS:
        raise ValueError(f"{field} fields do not match the typed context contract")
    state = _enum(value["state"], f"{field}.state", CONTEXT_STATES)
    description = value["description"]
    source_locator = value["source_locator"]
    if state == "reported":
        description = required_text(description, f"{field}.description", 4_000)
        source_locator = required_text(source_locator, f"{field}.source_locator", 1_000)
    elif description is not None or source_locator is not None:
        raise ValueError(
            f"{field} cannot carry source details when its state is {state}"
        )
    return {
        "state": state,
        "description": description,
        "source_locator": source_locator,
    }


def _validate_strength(value: object) -> JsonObject:
    if not isinstance(value, dict) or set(value) != _STRENGTH_FIELDS:
        raise ValueError(
            "source_supplied_strength fields do not match the typed contract"
        )
    state = _enum(value["state"], "source_supplied_strength.state", STRENGTH_STATES)
    scheme = value["scheme"]
    raw_label = value["raw_label"]
    raw_value = value["raw_value"]
    source_locator = value["source_locator"]
    if state == "not_reported":
        if any(
            item is not None for item in (scheme, raw_label, raw_value, source_locator)
        ):
            raise ValueError(
                "source_supplied_strength cannot carry details when not reported"
            )
    else:
        scheme = required_text(scheme, "source_supplied_strength.scheme", 500)
        source_locator = required_text(
            source_locator, "source_supplied_strength.source_locator", 1_000
        )
        if raw_label is not None:
            raw_label = required_text(
                raw_label, "source_supplied_strength.raw_label", 1_000
            )
        if isinstance(raw_value, bool) or (
            raw_value is not None and not isinstance(raw_value, (str, int, float))
        ):
            raise ValueError(
                "source_supplied_strength.raw_value must be a string, number, or null"
            )
        if isinstance(raw_value, float) and not math.isfinite(raw_value):
            raise ValueError("source_supplied_strength.raw_value must be finite")
        if isinstance(raw_value, str):
            raw_value = required_text(
                raw_value, "source_supplied_strength.raw_value", 1_000
            )
        if raw_label is None and raw_value is None:
            raise ValueError(
                "reported source_supplied_strength requires a raw label or value"
            )
    return {
        "state": state,
        "scheme": scheme,
        "raw_label": raw_label,
        "raw_value": raw_value,
        "source_locator": source_locator,
    }


def _validate_conflicts(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        raise ValueError("conflicts must be an array")
    result: list[JsonObject] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != _CONFLICT_FIELDS:
            raise ValueError("conflict fields do not match the typed contract")
        evidence_id = required_text(
            item["source_evidence_record_id"],
            "conflicts.source_evidence_record_id",
            1_000,
        )
        if evidence_id in seen:
            raise ValueError("conflicts cannot cite the same evidence record twice")
        seen.add(evidence_id)
        direction = required_text(item["direction"], "conflicts.direction", 100)
        if direction not in {"mixed", "refutes"}:
            raise ValueError("conflicts.direction must be mixed or refutes")
        result.append(
            {
                "source_evidence_record_id": evidence_id,
                "direction": direction,
                "source_locator": required_text(
                    item["source_locator"], "conflicts.source_locator", 1_000
                ),
            }
        )
    return result
