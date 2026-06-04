from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from ...active_genome_index.array_genotypes import called_genotype_tokens
from .constants import (
    ASSOCIATION_CLINSIG,
    BENIGN_CLINSIG,
    CANDIDATE_EVIDENCE_GROUPS,
    CANDIDATE_EVIDENCE_GROUP_DESCRIPTIONS,
    CLINVAR_CANDIDATE_BUCKETS,
    CLINVAR_CANDIDATE_BUCKET_DESCRIPTIONS,
    CONFLICTING_CLINSIG,
    DEFAULT_CANDIDATE_EVIDENCE_GROUPS,
    DRUG_RESPONSE_CLINSIG,
    HIGH_REVIEW_STATUS,
    LOW_REVIEW_STATUS,
    POPULATION_COMMON_AF_THRESHOLD,
    POPULATION_RARE_AF_THRESHOLD,
    POPULATION_TAGS,
    VUS_CLINSIG,
    candidate_evidence_group_choices,
)
from .helpers import (
    _clinical_significance_components,
    _gene_symbols,
    _has_strict_pathogenic_component,
    _optional_int_value,
    _ordered_unique,
)
from .clinvar_query import (
    query_genotype_support,
)
from .clinvar_match_provenance import (
    MATCH_BASIS_CONSUMER_ARRAY_ALLELE_INFERENCE,
    MATCH_BASIS_EXACT_ALLELE,
    match_basis_from_record,
    match_kind_from_record,
)
from .population import (
    _population_freshness_summary,
    query_population_frequency,
    summarize_population_frequency,
)



def _build_candidate(
    group: dict[str, Any],
    *,
    evidence_db_path: Path | None,
    genome_build: str,
    population_source: str | None,
    population: str | None,
) -> dict[str, Any]:
    sample = dict(group["sample_variant"])
    candidate_allele = dict(group.get("candidate_allele") or _allele_identity(sample))
    records = group["records"]
    clinvar_records = [item.get("clinvar") or {} for item in records]
    match_provenance = _candidate_match_provenance(records)
    clinical_significance: Counter[str] = Counter(
        record.get("clinical_significance") or "missing" for record in clinvar_records
    )
    review_status: Counter[str] = Counter(record.get("review_status") or "missing" for record in clinvar_records)
    genes = sorted(
        {
            gene
            for record in clinvar_records
            for gene in _gene_symbols(record.get("gene_info") or "")
        }
    )
    conditions = _ordered_unique(record.get("conditions") for record in clinvar_records if record.get("conditions"))
    clinvar_ids = _ordered_unique(record.get("clinvar_id") for record in clinvar_records if record.get("clinvar_id"))
    tags = _candidate_tags(clinical_significance, review_status)
    evidence_groups = _candidate_evidence_groups(clinical_significance)
    population_evidence = _candidate_population_evidence(
        evidence_db_path,
        candidate_allele,
        genome_build=genome_build,
        population_source=population_source,
        population=population,
    )
    tags = _with_population_tags(tags, population_evidence)
    clinvar_triage_score = _clinvar_triage_score(clinical_significance, review_status)
    genotype_support = _candidate_private_genotype_support(
        evidence_db_path,
        candidate_allele,
        genome_build=genome_build,
    )
    candidate = {
        "candidate_allele": candidate_allele,
        "variant": {
            "chrom": sample.get("chrom"),
            "pos": sample.get("pos"),
            "ref": sample.get("ref"),
            "alt": sample.get("alt"),
            "id": sample.get("id"),
            "filter": sample.get("filter"),
            "genotype": sample.get("genotype"),
            "depth": sample.get("depth"),
            "genotype_quality": sample.get("genotype_quality"),
            "record_kind": sample.get("record_kind"),
            "observed_alleles": sample.get("observed_alleles"),
            "match_basis": match_provenance["primary_match_basis"],
            "match_kind": match_provenance["primary_match_kind"],
            "source_format": match_provenance.get("primary_source_format"),
            "source_record_ref": sample.get("source_record_ref"),
            "source_record_alt": sample.get("source_record_alt"),
            "source_record_format": sample.get("source_record_format") or sample.get("format"),
            "source_record_record_kind": sample.get("source_record_record_kind"),
            "source_record_observed_alleles": sample.get("source_record_observed_alleles"),
        },
        "genes": genes,
        "clinvar": {
            "match_records": len(records),
            "clinical_significance_counts": clinical_significance.most_common(),
            "review_status_counts": review_status.most_common(),
            "clinvar_ids": clinvar_ids[:20],
            "conditions": conditions[:20],
            "match_basis_counts": match_provenance["match_basis_counts"],
            "match_kind_counts": match_provenance["match_kind_counts"],
            "source_format_counts": match_provenance["source_format_counts"],
            "source_record_format_counts": match_provenance["source_record_format_counts"],
        },
        "match_provenance": match_provenance,
        "genotype_support": genotype_support,
        "population_evidence": population_evidence,
        "evidence_groups": evidence_groups,
        "tags": tags,
        "clinvar_triage_score": clinvar_triage_score,
        "decision_points": _candidate_decision_points(
            tags,
            population_evidence,
            genotype_support,
            match_provenance=match_provenance,
        ),
    }
    return candidate


def _candidate_match_provenance(records: list[dict[str, Any]]) -> dict[str, Any]:
    match_basis: Counter[str] = Counter(match_basis_from_record(item) for item in records)
    match_kind: Counter[str] = Counter(match_kind_from_record(item) for item in records)
    source_formats: Counter[str] = Counter(
        source_format for item in records if (source_format := _record_source_format(item))
    )
    source_record_formats: Counter[str] = Counter(
        source_format for item in records if (source_format := _record_source_record_format(item))
    )
    primary_match_basis = _primary_counter_value(match_basis) or MATCH_BASIS_EXACT_ALLELE
    return {
        "primary_match_basis": primary_match_basis,
        "primary_match_kind": _primary_counter_value(match_kind) or primary_match_basis,
        "primary_source_format": _primary_counter_value(source_formats),
        "match_basis_counts": match_basis.most_common(),
        "match_kind_counts": match_kind.most_common(),
        "source_format_counts": source_formats.most_common(),
        "source_record_format_counts": source_record_formats.most_common(),
    }


def _record_source_format(item: dict[str, Any]) -> str | None:
    sample = item.get("sample_variant") if isinstance(item.get("sample_variant"), dict) else {}
    provenance = item.get("match_provenance") if isinstance(item.get("match_provenance"), dict) else {}
    source_record = provenance.get("source_record") if isinstance(provenance.get("source_record"), dict) else {}
    source_format = (
        item.get("source_format")
        or sample.get("source_format")
        or provenance.get("source_format")
        or source_record.get("source_format")
    )
    return str(source_format) if source_format else None


def _record_source_record_format(item: dict[str, Any]) -> str | None:
    sample = item.get("sample_variant") if isinstance(item.get("sample_variant"), dict) else {}
    provenance = item.get("match_provenance") if isinstance(item.get("match_provenance"), dict) else {}
    source_record = provenance.get("source_record") if isinstance(provenance.get("source_record"), dict) else {}
    source_format = sample.get("source_record_format") or sample.get("format") or source_record.get("format")
    return str(source_format) if source_format else None


def _primary_counter_value(counter: Counter[str]) -> str | None:
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def _enrich_candidate_population(
    candidate: dict[str, Any],
    *,
    evidence_db_path: Path | None,
    genome_build: str,
    population_source: str | None,
    population: str | None,
) -> None:
    candidate_allele = _candidate_query_allele(candidate)
    population_evidence = _candidate_population_evidence(
        evidence_db_path,
        candidate_allele,
        genome_build=genome_build,
        population_source=population_source,
        population=population,
    )
    tags = [tag for tag in candidate["tags"] if tag not in POPULATION_TAGS]
    candidate["tags"] = _with_population_tags(tags, population_evidence)
    candidate["population_evidence"] = population_evidence
    genotype_support = _candidate_private_genotype_support(
        evidence_db_path,
        candidate_allele,
        genome_build=genome_build,
    )
    candidate["genotype_support"] = genotype_support
    significance = Counter(dict(candidate["clinvar"]["clinical_significance_counts"]))
    review = Counter(dict(candidate["clinvar"]["review_status_counts"]))
    candidate["clinvar_triage_score"] = _clinvar_triage_score(significance, review)
    candidate["decision_points"] = _candidate_decision_points(
        candidate["tags"],
        population_evidence,
        genotype_support,
        match_provenance=candidate.get("match_provenance") or {},
    )


def _candidate_is_selected(
    candidate: dict[str, Any],
    *,
    selected_evidence_groups: list[str],
) -> bool:
    return bool(set(candidate["evidence_groups"]) & set(selected_evidence_groups))


def _normalize_candidate_evidence_groups(evidence_groups: list[str] | None) -> list[str]:
    requested = evidence_groups if evidence_groups is not None else DEFAULT_CANDIDATE_EVIDENCE_GROUPS
    valid = set(candidate_evidence_group_choices())
    normalized: list[str] = []
    for group in requested:
        group = group.strip()
        if group not in valid:
            raise ValueError(
                f"unknown evidence group {group!r}; expected one of {', '.join(candidate_evidence_group_choices())}"
            )
        if group not in normalized:
            normalized.append(group)
    if not normalized:
        return list(DEFAULT_CANDIDATE_EVIDENCE_GROUPS)
    return normalized


def _candidate_inventory_sort_key(candidate: dict[str, Any]) -> tuple[int, str, int, str, str]:
    variant = _candidate_query_allele(candidate)
    return (
        -int(candidate["clinvar_triage_score"]),
        str(variant.get("chrom")),
        int(variant.get("pos") or 0),
        str(variant.get("ref")),
        str(variant.get("alt")),
    )


def _candidate_tags(clinical_significance: Counter[str], review_status: Counter[str]) -> list[str]:
    tags: list[str] = []
    significance_components = _clinical_significance_components(clinical_significance)
    if _has_strict_pathogenic_component(clinical_significance):
        tags.append("clinvar_strict_p_lp")
    if _has_low_penetrance_component(significance_components):
        tags.append("clinvar_low_penetrance")
    if CONFLICTING_CLINSIG in significance_components:
        tags.append("clinvar_conflicting")
    if VUS_CLINSIG in significance_components:
        tags.append("clinvar_vus")
    if significance_components & ASSOCIATION_CLINSIG:
        tags.append("clinvar_association_or_risk")
    if significance_components & DRUG_RESPONSE_CLINSIG:
        tags.append("clinvar_drug_response")
    if significance_components & BENIGN_CLINSIG:
        tags.append("clinvar_benign_or_likely_benign")
    if any(review_status[status] for status in HIGH_REVIEW_STATUS):
        tags.append("higher_review_status")
    if any(review_status[status] for status in LOW_REVIEW_STATUS):
        tags.append("low_review_status")
    if review_status["criteria_provided,_conflicting_classifications"]:
        tags.append("review_status_conflicting")
    return tags


def _clinvar_triage_score(
    clinical_significance: Counter[str],
    review_status: Counter[str],
) -> int:
    score = 0
    significance_components = _clinical_significance_components(clinical_significance)
    if _has_strict_pathogenic_component(clinical_significance):
        score = max(score, 100)
    if CONFLICTING_CLINSIG in significance_components:
        score = max(score, 75)
    if VUS_CLINSIG in significance_components:
        score = max(score, 55)
    if significance_components & (ASSOCIATION_CLINSIG | DRUG_RESPONSE_CLINSIG):
        score = max(score, 35)
    if significance_components & BENIGN_CLINSIG:
        score = max(score, 10)
    score += max((_review_status_score(status) for status in review_status), default=0)
    return score


def _candidate_evidence_groups(clinical_significance: Counter[str]) -> list[str]:
    components = _clinical_significance_components(clinical_significance)
    groups: list[str] = []
    if _has_strict_pathogenic_component(clinical_significance):
        groups.append("clinvar_p_lp")
    if CONFLICTING_CLINSIG in components:
        groups.append("clinvar_conflicting")
    if VUS_CLINSIG in components:
        groups.append("clinvar_vus")
    if components & ASSOCIATION_CLINSIG:
        groups.append("clinvar_risk_association_protective")
    if components & DRUG_RESPONSE_CLINSIG:
        groups.append("clinvar_drug_response")
    if components & BENIGN_CLINSIG:
        groups.append("clinvar_benign")
    return _ordered_candidate_evidence_groups(groups)


def _has_low_penetrance_component(components: set[str]) -> bool:
    return any("low_penetrance" in component.lower() for component in components)


def _review_status_score(status: str) -> int:
    return {
        "practice_guideline": 12,
        "reviewed_by_expert_panel": 10,
        "criteria_provided,_multiple_submitters,_no_conflicts": 8,
        "criteria_provided,_single_submitter": 3,
        "criteria_provided,_conflicting_classifications": 2,
        "no_assertion_criteria_provided": 0,
    }.get(status, 1)


def _candidate_population_evidence(
    evidence_db_path: Path | None,
    sample: dict[str, Any],
    *,
    genome_build: str,
    population_source: str | None,
    population: str | None,
) -> dict[str, Any]:
    if evidence_db_path is None:
        return {
            "status": "not_checked",
            "reason": "no evidence DB was provided",
            "freshness": {
                "status": "not_checked",
                "latest_upstream_checked": False,
                "note": "No evidence DB was provided, so no population-frequency source was checked.",
            },
        }
    query = query_population_frequency(
        evidence_db_path,
        str(sample.get("chrom")),
        int(sample.get("pos")),
        str(sample.get("ref")),
        str(sample.get("alt")),
        genome_build=genome_build,
        source=population_source,
        population=population,
        limit=500,
    )
    records = query["records"]
    if not records:
        return {
            "status": "missing",
            "query": query["query"],
            "record_count": 0,
            "freshness": _population_freshness_summary([]),
        }
    summary = summarize_population_frequency(query)
    return {
        "status": "present",
        "query": query["query"],
        "record_count": summary["record_count"],
        "max_global_allele_frequency": _max_global_allele_frequency(summary["global_rows"]),
        "max_allele_frequency": (
            summary["max_allele_frequency_record"] or {}
        ).get("allele_frequency"),
        "global_rows": summary["global_rows"],
        "homozygote_row_count": summary["homozygote_row_count"],
        "source_counts": summary["source_counts"],
        "freshness": summary["freshness"],
    }


def _candidate_population_tags(population_evidence: dict[str, Any]) -> list[str]:
    status = population_evidence["status"]
    if status == "present":
        tags = ["population_evidence_present"]
        max_global_af = population_evidence.get("max_global_allele_frequency")
        homozygote_rows = int(population_evidence.get("homozygote_row_count") or 0)
        if max_global_af is not None and max_global_af >= POPULATION_COMMON_AF_THRESHOLD:
            tags.append("population_frequency_common")
        if max_global_af is not None and max_global_af <= POPULATION_RARE_AF_THRESHOLD and homozygote_rows == 0:
            tags.append("population_frequency_rare")
        if homozygote_rows:
            tags.append("population_homozygotes_present")
        return tags
    if status == "missing":
        return ["needs_public_population_evidence"]
    return ["population_evidence_not_checked"]


def _with_population_tags(tags: list[str], population_evidence: dict[str, Any]) -> list[str]:
    combined = list(tags)
    combined.extend(_candidate_population_tags(population_evidence))
    tag_set = set(combined)
    disease_like = bool({"clinvar_strict_p_lp", "clinvar_conflicting"} & tag_set)
    if disease_like and {"population_frequency_common", "population_homozygotes_present"} & tag_set:
        combined.append("population_frequency_context_needed")
    return sorted(set(combined))


def _max_global_allele_frequency(global_rows: list[dict[str, Any]]) -> float | None:
    values = [
        row.get("allele_frequency")
        for row in global_rows
        if row.get("allele_frequency") is not None
    ]
    return max(values) if values else None


def _candidate_buckets(candidate: dict[str, Any]) -> list[str]:
    tags = set(candidate["tags"])
    components = _clinical_significance_components(
        Counter(dict(candidate["clinvar"]["clinical_significance_counts"]))
    )
    buckets: list[str] = []
    has_p_lp = "clinvar_strict_p_lp" in tags
    if has_p_lp and "higher_review_status" in tags:
        buckets.append("clinvar_p_lp_high_review")
    elif has_p_lp:
        buckets.append("clinvar_p_lp_low_or_missing_review")
    if has_p_lp and "population_frequency_context_needed" in tags:
        buckets.append("clinvar_p_lp_population_context_needed")
    if has_p_lp and "clinvar_low_penetrance" in tags:
        buckets.append("low_penetrance_or_carrier_context")
    if has_p_lp and _is_heterozygous_genotype(candidate["variant"].get("genotype")):
        buckets.append("heterozygous_p_lp_context_needed")
    if "clinvar_conflicting" in tags:
        buckets.append("clinvar_conflicting")
    if "clinvar_vus" in tags:
        buckets.append("clinvar_vus")
    if "drug_response" in components:
        buckets.append("drug_response")
    if components & {"association", "risk_factor", "protective"}:
        buckets.append("risk_factor_or_association")
    if "needs_public_population_evidence" in tags:
        buckets.append("needs_population_evidence")
    if "population_frequency_common" in tags:
        buckets.append("population_common_context")
    if "population_frequency_rare" in tags:
        buckets.append("population_rare_context")
    if _candidate_quality_context_needed(candidate):
        buckets.append("quality_or_low_call_support_context")
    return _ordered_bucket_names(buckets)


def _ordered_bucket_counts(bucket_counts: Counter[str]) -> list[list[Any]]:
    ordered = [[bucket, bucket_counts[bucket]] for bucket in _bucket_order() if bucket_counts[bucket]]
    extra = sorted(bucket for bucket in bucket_counts if bucket not in CLINVAR_CANDIDATE_BUCKET_DESCRIPTIONS)
    ordered.extend([[bucket, bucket_counts[bucket]] for bucket in extra])
    return ordered


def _ordered_candidate_evidence_groups(groups: list[str]) -> list[str]:
    order = {group: index for index, (group, _description) in enumerate(CANDIDATE_EVIDENCE_GROUPS)}
    return sorted(set(groups), key=lambda group: (order.get(group, len(order)), group))


def _ordered_candidate_evidence_group_counts(group_counts: Counter[str]) -> list[list[Any]]:
    ordered = [
        [group, group_counts[group]]
        for group, _description in CANDIDATE_EVIDENCE_GROUPS
        if group_counts[group]
    ]
    extra = sorted(group for group in group_counts if group not in CANDIDATE_EVIDENCE_GROUP_DESCRIPTIONS)
    ordered.extend([[group, group_counts[group]] for group in extra])
    return ordered


def _available_evidence_group_summary(group_counts: Counter[str]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for group, description in CANDIDATE_EVIDENCE_GROUPS:
        count = group_counts[group]
        if not count:
            continue
        summary.append(
            {
                "group": group,
                "count": count,
                "description": description,
                "use": (
                    "Use this lens only after the agent has identified a missing evidence fact that this source-derived group can expose."
                ),
                "how_to_select": {
                    "action": "build-candidate-inventory",
                    "option": "--evidence-group",
                    "value": group,
                },
            }
        )
    return summary


def _candidate_bucket_summary(
    candidates: list[dict[str, Any]],
    emitted_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    emitted_keys = {_candidate_identity(candidate): index for index, candidate in enumerate(emitted_candidates)}
    summary: list[dict[str, Any]] = []
    for bucket, description in CLINVAR_CANDIDATE_BUCKETS:
        bucket_candidates = [candidate for candidate in candidates if bucket in candidate["buckets"]]
        if not bucket_candidates:
            continue
        emitted_indices = [
            emitted_keys[_candidate_identity(candidate)]
            for candidate in bucket_candidates
            if _candidate_identity(candidate) in emitted_keys
        ]
        summary.append(
            {
                "bucket": bucket,
                "description": description,
                "count": len(bucket_candidates),
                "emitted_candidate_indices": emitted_indices[:20],
                "example_variants": [
                    _candidate_bucket_example(candidate) for candidate in bucket_candidates[:5]
                ],
            }
        )
    return summary


def _candidate_bucket_example(candidate: dict[str, Any]) -> dict[str, Any]:
    variant = _candidate_query_allele(candidate)
    return {
        "variant": {
            "chrom": variant.get("chrom"),
            "pos": variant.get("pos"),
            "ref": variant.get("ref"),
            "alt": variant.get("alt"),
            "id": variant.get("id"),
            "genotype": variant.get("genotype"),
        },
        "genes": candidate["genes"],
        "clinvar_triage_score": candidate["clinvar_triage_score"],
        "tags": candidate["tags"],
    }


def _candidate_identity(candidate: dict[str, Any]) -> tuple[str, int, str, str]:
    variant = _candidate_query_allele(candidate)
    return (
        str(variant.get("chrom")),
        int(variant.get("pos") or 0),
        str(variant.get("ref")),
        str(variant.get("alt")),
    )


def _candidate_query_allele(candidate: dict[str, Any]) -> dict[str, Any]:
    allele = candidate.get("candidate_allele")
    if isinstance(allele, dict):
        return allele
    return candidate["variant"]


def _allele_identity(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "chrom": record.get("chrom"),
        "pos": record.get("pos"),
        "ref": record.get("ref"),
        "alt": record.get("alt"),
    }


def _ordered_bucket_names(buckets: list[str]) -> list[str]:
    order = {bucket: index for index, bucket in enumerate(_bucket_order())}
    return sorted(set(buckets), key=lambda bucket: (order.get(bucket, len(order)), bucket))


def _bucket_order() -> list[str]:
    return [bucket for bucket, _description in CLINVAR_CANDIDATE_BUCKETS]


def _is_heterozygous_genotype(genotype: Any) -> bool:
    if genotype is None:
        return False
    called = called_genotype_tokens(genotype)
    return len(called) >= 2 and len(set(called)) > 1


def _sample_quality_context_needed(variant: dict[str, Any]) -> bool:
    if str(variant.get("filter") or "") not in {"", "PASS"}:
        return True
    depth = _optional_int_value(variant.get("depth"))
    genotype_quality = _optional_int_value(variant.get("genotype_quality"))
    return (depth is not None and depth < 10) or (genotype_quality is not None and genotype_quality < 20)


def _candidate_quality_context_needed(candidate: dict[str, Any]) -> bool:
    support = candidate.get("genotype_support") if isinstance(candidate.get("genotype_support"), dict) else {}
    support_status = support.get("support_status")
    if support_status and support_status != "supported":
        return True
    return _sample_quality_context_needed(candidate["variant"])


def _candidate_decision_points(
    tags: list[str],
    population_evidence: dict[str, Any],
    genotype_support: dict[str, Any],
    *,
    match_provenance: dict[str, Any],
) -> list[str]:
    decisions = [
        "Decide whether this candidate is worth gathering variant evidence for, based on the user's question and candidate bucket context.",
        f"Use genotype_support status {genotype_support['support_status']} before interpreting this row; weak/unknown/no-call support should be downgraded or blocked.",
        "After gathering evidence, interpret ClinVar significance together with review status, zygosity, inheritance context, and population frequency.",
    ]
    if "clinvar_strict_p_lp" in tags and population_evidence["status"] != "present":
        decisions.append("Because ClinVar has P/LP evidence, the agent should usually gather variant evidence with missing gnomAD population fetch enabled before explaining importance.")
    if population_evidence["status"] == "present":
        decisions.append("Use population evidence according to the user's question; check source dates if currentness matters.")
    if "population_frequency_context_needed" in tags:
        decisions.append("Use population frequency according to the user's intent; common variants can still matter for risk, pharmacogenomics, carrier, or trait questions, while rare-disease interpretation needs inheritance, penetrance, phenotype, and source context.")
    if "population_frequency_rare" in tags:
        decisions.append("Population evidence is rare in public data, but rarity alone does not establish pathogenicity.")
    if "clinvar_vus" in tags:
        decisions.append("Treat VUS as uncertain and decide whether more evidence is worth collecting.")
    if "clinvar_conflicting" in tags:
        decisions.append("Keep conflicting ClinVar assertions visible and inspect the gathered variant evidence.")
    match_bases = {
        str(basis)
        for basis, _count in (match_provenance.get("match_basis_counts") or [])
    }
    if MATCH_BASIS_CONSUMER_ARRAY_ALLELE_INFERENCE in match_bases:
        decisions.append(
            "Treat consumer-array ClinVar hits as allele inference from array genotype strings, "
            "not exact VCF allele observations; confirm the source evidence before clinical use."
        )
    decisions.append("Use family, segregation, and phased sample data for de novo status, segregation, or cis/trans phase.")
    return decisions


def _candidate_private_genotype_support(
    evidence_db_path: Path | None,
    sample: dict[str, Any],
    *,
    genome_build: str,
) -> dict[str, Any]:
    if evidence_db_path is None:
        return _candidate_unclassified_genotype_support("No private evidence DB was available for genotype-support classification.")
    query = query_genotype_support(
        evidence_db_path,
        str(sample.get("chrom")),
        int(sample.get("pos") or 0),
        str(sample.get("ref")),
        str(sample.get("alt")),
        genome_build=genome_build,
        limit=5,
    )
    latest = query.get("latest")
    if not latest:
        return _candidate_unclassified_genotype_support("No private genotype_support row exists for this allele.")
    status = str(latest.get("support_status") or "unknown")
    observation = latest.get("sample_observation") if isinstance(latest.get("sample_observation"), dict) else {}
    return {
        "source": "private_db",
        "support_status": status,
        "evidence_class": latest.get("evidence_class") or _genotype_support_evidence_class(status),
        "reason": observation.get("limitation") or "stored genotype-support result",
        "stage_2_rule": (
            "may be used as sample_observation evidence"
            if status == "supported"
            else "use as limited sample context until stronger sample evidence supports the personal finding"
        ),
        "accepted_report_evidence_classes": latest.get("accepted_report_evidence_classes") or [],
        "stored_support": {
            "status": "available",
            "created_at": latest.get("created_at"),
            "genotype": observation.get("genotype"),
            "zygosity": observation.get("zygosity"),
            "depth": observation.get("depth"),
            "genotype_quality": observation.get("genotype_quality"),
            "filter": observation.get("filter"),
            "evidence_boundaries": latest.get("evidence_boundaries"),
        },
    }


def _candidate_unclassified_genotype_support(reason: str) -> dict[str, Any]:
    return {
        "source": "active_genome_index_reader_not_classified",
        "support_status": "not_checked",
        "evidence_class": "genotype_support_unknown",
        "reason": reason,
        "accepted_report_evidence_classes": [],
        "stored_support": {"status": "missing"},
    }


def _genotype_support_evidence_class(status: str) -> str:
    return {
        "supported": "genotype_support_supported",
        "weak": "genotype_support_weak",
        "unknown": "genotype_support_unknown",
        "no_call": "genotype_support_no_call",
        "not_observed": "genotype_support_not_observed",
    }.get(status, "genotype_support_unknown")
