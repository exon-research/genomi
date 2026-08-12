"""Patient-facing Investigation Brief assembly."""

from __future__ import annotations

from .models import JsonObject


def build_investigation_brief(
    *,
    profile: JsonObject,
    finding: JsonObject,
    question: str,
    evidence: JsonObject,
) -> JsonObject:
    sample_context = evidence.get("sample_context")
    count = (
        int(sample_context.get("count") or 0)
        if isinstance(sample_context, dict)
        else 0
    )
    if count:
        observation = (
            f"A matching record for {finding['variant']} was observed in this profile's "
            "Active Genome Index."
        )
    else:
        observation = (
            f"No matching record for {finding['variant']} was returned from the consulted "
            "Active Genome Index scope. This is not a clinical negative result."
        )
    return {
        "status": "research_observation",
        "title": f"Investigation brief: {finding['variant']}",
        "question": question,
        "profile": {
            "profile_id": profile["profile_id"],
            "display_name": profile["display_name"],
        },
        "reported_finding": {
            "variant": finding["variant"],
            "gene": finding.get("gene"),
            "reported_classification": finding.get("reported_classification"),
            "source_label": finding.get("source_label"),
            "normalization_state": finding["normalization_state"],
        },
        "observation": observation,
        "health_context": [
            {
                "kind": fact["kind"],
                "label": fact["label"],
                "assertion_status": fact["assertion_status"],
                "verification_state": fact["verification_state"],
            }
            for fact in profile.get("health_facts", [])
            if isinstance(fact, dict)
        ],
        "evidence": {
            "operation": "variant.resolve",
            "evidence_envelope": evidence.get("evidence_envelope"),
            "defaults_applied": evidence.get("defaults_applied"),
            "sample_context": sample_context,
            "public_context": {
                key: evidence.get(key)
                for key in (
                    "variant",
                    "population",
                    "clinvar",
                    "observations",
                    "coverage",
                )
                if evidence.get(key) is not None
            },
        },
        "mechanism": None,
        "confirmation_needed": [
            "Confirm the variant and zygosity in a clinical laboratory before making medical decisions.",
            "Have a qualified clinician or genetic counselor interpret the finding with the full phenotype and family history.",
            "A reported classification is not independently validated by this brief.",
        ],
        "clinical_boundary": (
            "Research support only. This brief is not a diagnosis or treatment recommendation."
        ),
    }
