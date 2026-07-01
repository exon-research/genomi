from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from ...active_genome_index.array_genotypes import called_genotype_tokens
from .constants import DEFAULT_CANDIDATE_EVIDENCE_GROUPS, POPULATION_TAGS

JsonObject = dict[str, Any]

CANDIDATE_REVIEW_GROUP_POLICY_ID = "clinvar_candidate_review_groups_v1"
ALL_CLINVAR_REVIEW_EVIDENCE_GROUPS = tuple(DEFAULT_CANDIDATE_EVIDENCE_GROUPS)
REVIEW_GROUP_TYPE_ORDER = (
    "carrier_relevance",
    "observed_condition",
    "uncertain_or_conflicting",
    "drug_response",
    "risk_association",
    "benign_or_counterevidence",
    "quality_or_population_context",
)
MISSING_INTERPRETATION_GATE_STATES = frozenset(
    {"missing", "not_checked", "needed", "required", "mixed_missing", "mixed_not_checked"}
)
_QUALITY_TAGS = {
    "population_evidence_not_checked",
    "needs_public_population_evidence",
    "population_frequency_common",
    "population_homozygotes_present",
    "population_frequency_context_needed",
    "quality_or_low_call_support_context",
}


def build_candidate_review_groups(candidates: list[JsonObject]) -> JsonObject:
    grouped: dict[tuple[str, str | None, str | None], list[JsonObject]] = {}
    for candidate in candidates:
        for group_type in _review_group_types(candidate):
            for gene in _candidate_genes(candidate):
                for condition in _candidate_conditions(candidate):
                    grouped.setdefault((group_type, gene, condition), []).append(candidate)

    groups = [
        _build_group(group_type, gene, condition, group_candidates)
        for (group_type, gene, condition), group_candidates in grouped.items()
    ]
    groups.sort(key=_group_sort_key)
    return {
        "policy_id": CANDIDATE_REVIEW_GROUP_POLICY_ID,
        "group_count": len(groups),
        "groups": groups,
        "group_counts_by_type": review_group_counts_by_type(groups),
    }


def _build_group(
    group_type: str,
    gene: str | None,
    condition: str | None,
    candidates: list[JsonObject],
) -> JsonObject:
    candidate_ids = sorted({_candidate_id(candidate) for candidate in candidates})
    clinical_significance_counts: Counter[str] = Counter()
    review_status_counts: Counter[str] = Counter()
    evidence_groups: set[str] = set()
    zygosity_counts: Counter[str] = Counter()
    match_basis_counts: Counter[str] = Counter()
    population_flags: set[str] = set()
    for candidate in candidates:
        clinvar = candidate.get("clinvar") if isinstance(candidate.get("clinvar"), dict) else {}
        clinical_significance_counts.update(_counter_items(clinvar.get("clinical_significance_counts")))
        review_status_counts.update(_counter_items(clinvar.get("review_status_counts")))
        evidence_groups.update(str(item) for item in candidate.get("evidence_groups") or [] if item)
        zygosity_counts[_zygosity(candidate)] += 1
        provenance = candidate.get("match_provenance") if isinstance(candidate.get("match_provenance"), dict) else {}
        match_basis_counts.update(_counter_items(provenance.get("match_basis_counts") or clinvar.get("match_basis_counts")))
        population_flags.update(str(tag) for tag in candidate.get("tags") or [] if tag in POPULATION_TAGS or tag in _QUALITY_TAGS)
    group = {
        "group_type": group_type,
        "gene": gene,
        "condition": condition,
        "candidate_ids": candidate_ids,
        "clinical_significance_counts": _counter_list(clinical_significance_counts),
        "review_status_counts": _counter_list(review_status_counts),
        "evidence_groups": sorted(evidence_groups),
        "zygosity_counts": _counter_list(zygosity_counts),
        "match_basis_counts": _counter_list(match_basis_counts),
        "population_flags": sorted(population_flags),
        "interpretation_gates": _interpretation_gates(group_type, candidates),
    }
    group["group_id"] = _group_id(group)
    return group


def _review_group_types(candidate: JsonObject) -> list[str]:
    evidence_groups = set(candidate.get("evidence_groups") or [])
    buckets = set(candidate.get("buckets") or [])
    tags = set(candidate.get("tags") or [])
    group_types: list[str] = []
    if "clinvar_p_lp" in evidence_groups:
        if buckets & {"heterozygous_p_lp_context_needed", "low_penetrance_or_carrier_context"}:
            group_types.append("carrier_relevance")
        else:
            group_types.append("observed_condition")
    if evidence_groups & {"clinvar_conflicting", "clinvar_vus"}:
        group_types.append("uncertain_or_conflicting")
    if "clinvar_drug_response" in evidence_groups:
        group_types.append("drug_response")
    if "clinvar_risk_association_protective" in evidence_groups:
        group_types.append("risk_association")
    if "clinvar_benign" in evidence_groups:
        group_types.append("benign_or_counterevidence")
    if tags & (POPULATION_TAGS | _QUALITY_TAGS) or buckets & {
        "needs_population_evidence",
        "population_common_context",
        "population_rare_context",
        "quality_or_low_call_support_context",
    }:
        group_types.append("quality_or_population_context")
    return _ordered_group_types(group_types)


def _interpretation_gates(group_type: str, candidates: list[JsonObject]) -> JsonObject:
    zygosity_states = {_zygosity(candidate) for candidate in candidates}
    genotype_states = {_genotype_support_state(candidate) for candidate in candidates}
    population_states = {_population_state(candidate) for candidate in candidates}
    review_states = {_source_review_state(candidate) for candidate in candidates}
    return {
        "inheritance": _gate("needed", group_type in {"carrier_relevance", "observed_condition", "uncertain_or_conflicting"}),
        "phase": _gate("needed", group_type in {"carrier_relevance", "observed_condition"}),
        "zygosity": _gate("observed" if zygosity_states - {"unknown"} else "missing", True),
        "genotype_support": _gate(_combined_state(genotype_states), True),
        "population_frequency": _gate(_combined_state(population_states), group_type != "drug_response"),
        "source_review": _gate(_combined_state(review_states), True),
        "clinical_confirmation": _gate("required", True),
    }


def _gate(state: str, required: bool) -> JsonObject:
    return {"state": state, "required": bool(required)}


def _combined_state(states: set[str]) -> str:
    if not states:
        return "missing"
    if len(states) == 1:
        return next(iter(states))
    order = ["missing", "not_checked", "low", "conflicting", "present", "high"]
    for state in order:
        if state in states:
            return "mixed_" + state
    return "mixed"


def _candidate_id(candidate: JsonObject) -> str:
    variant = candidate.get("variant") if isinstance(candidate.get("variant"), dict) else {}
    return "variant:{chrom}-{pos}-{ref}-{alt}".format(
        chrom=variant.get("chrom"),
        pos=variant.get("pos"),
        ref=variant.get("ref"),
        alt=variant.get("alt"),
    )


def _candidate_genes(candidate: JsonObject) -> list[str | None]:
    genes = [str(item).strip().upper() for item in candidate.get("genes") or [] if str(item).strip()]
    return sorted(set(genes)) or [None]


def _candidate_conditions(candidate: JsonObject) -> list[str | None]:
    clinvar = candidate.get("clinvar") if isinstance(candidate.get("clinvar"), dict) else {}
    values = [str(item).strip() for item in clinvar.get("conditions") or [] if str(item).strip()]
    return sorted(set(values)) or [None]


def _zygosity(candidate: JsonObject) -> str:
    variant = candidate.get("variant") if isinstance(candidate.get("variant"), dict) else {}
    genotype = variant.get("genotype")
    if genotype is None:
        return "unknown"
    called = called_genotype_tokens(genotype)
    if not called:
        return "unknown"
    if all(token == "0" for token in called):
        return "reference"
    non_ref = [token for token in called if token != "0"]
    if len(called) >= 2 and len(set(called)) == 1 and non_ref:
        return "homozygous_alternate"
    if len(called) >= 2 and non_ref:
        return "heterozygous"
    return "observed"


def _genotype_support_state(candidate: JsonObject) -> str:
    support = candidate.get("genotype_support") if isinstance(candidate.get("genotype_support"), dict) else {}
    state = str(support.get("support_status") or support.get("status") or "")
    if state in {"present", "strong", "moderate", "weak"}:
        return "present"
    if state in {"not_checked", "missing"}:
        return state
    return "missing"


def _population_state(candidate: JsonObject) -> str:
    population = candidate.get("population_evidence") if isinstance(candidate.get("population_evidence"), dict) else {}
    state = str(population.get("status") or "")
    if state in {"present", "missing", "not_checked"}:
        return state
    return "missing"


def _source_review_state(candidate: JsonObject) -> str:
    tags = set(candidate.get("tags") or [])
    if "higher_review_status" in tags:
        return "high"
    if "review_status_conflicting" in tags:
        return "conflicting"
    if "low_review_status" in tags:
        return "low"
    return "missing"


def _counter_items(value: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not isinstance(value, list):
        return counts
    for item in value:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            key = str(item[0])
            try:
                count = int(item[1])
            except (TypeError, ValueError):
                count = 1
            counts[key] = counts.get(key, 0) + count
    return counts


def _counter_list(counter: Counter[str]) -> list[list[Any]]:
    return [[key, count] for key, count in counter.most_common()]


def review_group_counts_by_type(groups: list[JsonObject]) -> list[list[Any]]:
    counts = Counter(str(group.get("group_type") or "unknown") for group in groups)
    ordered = [[group_type, counts[group_type]] for group_type in REVIEW_GROUP_TYPE_ORDER if counts[group_type]]
    extra = sorted(group_type for group_type in counts if group_type not in REVIEW_GROUP_TYPE_ORDER)
    ordered.extend([[group_type, counts[group_type]] for group_type in extra])
    return ordered


def missing_interpretation_gates(group: JsonObject) -> list[str]:
    gates = group.get("interpretation_gates") if isinstance(group.get("interpretation_gates"), dict) else {}
    return [
        gate
        for gate, state in gates.items()
        if isinstance(state, dict)
        and state.get("required")
        and str(state.get("state") or "") in MISSING_INTERPRETATION_GATE_STATES
    ]


def _ordered_group_types(values: list[str]) -> list[str]:
    order = {value: index for index, value in enumerate(REVIEW_GROUP_TYPE_ORDER)}
    return sorted(set(values), key=lambda value: (order.get(value, len(order)), value))


def _group_sort_key(group: JsonObject) -> tuple[int, str, str, str]:
    order = {value: index for index, value in enumerate(REVIEW_GROUP_TYPE_ORDER)}
    return (
        order.get(str(group.get("group_type")), len(order)),
        str(group.get("gene") or ""),
        str(group.get("condition") or ""),
        str(group.get("group_id") or ""),
    )


def _group_id(group: JsonObject) -> str:
    identity = {
        "group_type": group.get("group_type"),
        "gene": group.get("gene"),
        "condition": group.get("condition"),
        "candidate_ids": group.get("candidate_ids"),
        "evidence_groups": group.get("evidence_groups"),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"clinvar_group_{digest[:16]}"
