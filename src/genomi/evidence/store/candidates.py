from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any
from ...runtime.external import file_metadata, matching_manifest, utc_now
from ...runtime.handoff import evidence_context
from .. import envelope as _env
from ..candidate_evidence import (
    DIRECT_SOURCE_MATCH,
    NEGATIVE_OR_CONFLICTING_EVIDENCE,
    answerability_for_lane,
    apply_evidence_view,
    evidence_support_level_for_score,
    empty_lanes,
    evidence_view,
    lane,
)
from ..task_profiles import CLINVAR_CANDIDATE_SCAN

from .constants import (
    CANDIDATE_EVIDENCE_GROUPS,
    CANDIDATE_RULE_SET_VERSION,
)
from .helpers import (
    _iter_jsonl,
)
from .connection import (
    _ensure_schema,
    _population_cache_identity,
    _private_sample_context_identity,
    connect_evidence,
)
from .candidate_scoring import (
    _available_evidence_group_summary,
    _build_candidate,
    _candidate_bucket_summary,
    _candidate_buckets,
    _candidate_inventory_sort_key,
    _candidate_is_selected,
    _enrich_candidate_population,
    _normalize_candidate_evidence_groups,
    _ordered_bucket_counts,
    _ordered_candidate_evidence_group_counts,
)
from .candidate_groups import build_candidate_review_groups
from .clinvar_match_provenance import (
    MATCH_BASIS_CONSUMER_ARRAY_ALLELE_INFERENCE,
    MATCH_BASIS_EXACT_ALLELE,
    MATCH_BASIS_LIFTOVER_EXACT_ALLELE,
    MATCH_BASIS_LIFTOVER_MULTIALLELIC_ALT,
    MATCH_BASIS_MULTIALLELIC_ALT,
    match_basis_from_record,
)



def extract_clinvar_candidates(
    matches_path: str | Path,
    evidence_db: str | Path | None = None,
    output_path: str | Path | None = None,
    *,
    genome_build: str = "GRCh38",
    population_source: str | None = None,
    population: str | None = None,
    limit: int = 200,
    evidence_groups: list[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    matches_path = Path(matches_path)
    if not matches_path.exists():
        raise FileNotFoundError(matches_path)
    evidence_db_path = Path(evidence_db) if evidence_db is not None else None
    if evidence_db_path is not None and not evidence_db_path.exists():
        raise FileNotFoundError(evidence_db_path)
    if limit < 1:
        raise ValueError("limit must be >= 1")
    selected_evidence_groups = _normalize_candidate_evidence_groups(evidence_groups)
    population_identity = None
    private_sample_context_identity = None
    if evidence_db_path is not None:
        with connect_evidence(evidence_db_path) as connection:
            _ensure_schema(connection)
            population_identity = _population_cache_identity(connection)
            private_sample_context_identity = _private_sample_context_identity(connection)

    output = Path(output_path) if output_path is not None else None
    manifest_path = Path(f"{output}.genomi-manifest.json") if output is not None else None
    cache_expected = {
        "step": "extract_clinvar_candidates",
        "input": file_metadata(matches_path),
        "evidence_db": str(evidence_db_path) if evidence_db_path is not None else None,
        "population_evidence": population_identity,
        "private_sample_context": private_sample_context_identity,
        "output": str(output) if output is not None else None,
        "genome_build": genome_build,
        "population_source": population_source,
        "population": population,
        "limit": limit,
        "selected_evidence_groups": selected_evidence_groups,
        "rule_set_version": CANDIDATE_RULE_SET_VERSION,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        if not force:
            cached = matching_manifest(manifest_path, cache_expected, required_paths=[output])
            if cached is not None:
                payload = json.loads(output.read_text(encoding="utf-8"))
                payload["status"] = "cached"
                payload["manifest_path"] = str(manifest_path)
                payload.setdefault(
                    "evidence_context",
                    evidence_context(
                        "research",
                        reason="Candidate inventory is static evidence for agent-selected target research.",
                        commands=[
                            "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
                            "genomi call research.build_target_packet --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"topic\",\"topic\":\"<topic>\"}'",
                        ],
                    ),
                )
                return payload

    grouped: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    total_match_records = 0
    for item in _iter_jsonl(matches_path):
        total_match_records += 1
        sample = item.get("sample_variant") or {}
        candidate_allele = _candidate_allele_from_match(item, sample)
        key = (
            str(candidate_allele.get("chrom")),
            int(candidate_allele.get("pos") or 0),
            str(candidate_allele.get("ref")),
            str(candidate_allele.get("alt")),
        )
        group = grouped.setdefault(
            key,
            {
                "candidate_allele": candidate_allele,
                "sample_variant": sample,
                "records": [],
            },
        )
        group["records"].append(item)

    all_candidates: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for group in grouped.values():
        candidate = _build_candidate(
            group,
            evidence_db_path=None,
            genome_build=genome_build,
            population_source=population_source,
            population=population,
        )
        all_candidates.append(candidate)
        if _candidate_is_selected(candidate, selected_evidence_groups=selected_evidence_groups):
            candidates.append(candidate)

    for candidate in candidates:
        _enrich_candidate_population(
            candidate,
            evidence_db_path=evidence_db_path,
            genome_build=genome_build,
            population_source=population_source,
            population=population,
        )

    for candidate in candidates:
        candidate["buckets"] = _candidate_buckets(candidate)

    candidates.sort(key=_candidate_inventory_sort_key)
    emitted_candidates = candidates[:limit]
    tag_counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    available_evidence_group_counts: Counter[str] = Counter()
    for candidate in all_candidates:
        available_evidence_group_counts.update(candidate["evidence_groups"])
    for candidate in candidates:
        tag_counts.update(candidate["tags"])
        bucket_counts.update(candidate["buckets"])
    clinical_significance: Counter[str] = Counter()
    review_status: Counter[str] = Counter()
    match_basis_counts: Counter[str] = Counter()
    for group in grouped.values():
        for item in group["records"]:
            clinvar = item.get("clinvar") or {}
            clinical_significance[clinvar.get("clinical_significance") or "missing"] += 1
            review_status[clinvar.get("review_status") or "missing"] += 1
            match_basis_counts[match_basis_from_record(item)] += 1
    total_exact_allele_match_variants = _candidate_count_by_match_basis(
        all_candidates,
        {MATCH_BASIS_EXACT_ALLELE, MATCH_BASIS_LIFTOVER_EXACT_ALLELE},
    )
    total_consumer_array_inferred_match_variants = _candidate_count_by_match_basis(
        all_candidates,
        {MATCH_BASIS_CONSUMER_ARRAY_ALLELE_INFERENCE},
    )
    candidate_evidence = _clinvar_candidate_evidence_view(
        emitted_candidates,
        genome_build=genome_build,
        selected_evidence_groups=selected_evidence_groups,
        population_source=population_source,
        population=population,
    )
    candidate_review_groups = build_candidate_review_groups(candidates)

    payload = {
        "status": "completed",
        "input": str(matches_path),
        "output": str(output) if output is not None else None,
        "rule_set_version": CANDIDATE_RULE_SET_VERSION,
        "action": {
            "name": "build-candidate-inventory",
            "purpose": "Build source-derived candidate inventory from provenance-marked ClinVar matches so the agent can inspect evidence lenses and decide what facts are missing for the user's question.",
            "result_type": "deterministic candidate inventory with selected candidates, all available ClinVar evidence lenses, bucket summaries, and evidence-context guidance",
            "scope": [
                "builds source-derived candidate evidence lenses",
                "keeps user-intent selection with the host agent",
                "feeds clinical interpretation and current source review performed by later tools",
            ],
        },
        "selection": {
            "genome_build": genome_build,
            "population_source": population_source,
            "population": population,
            "limit": limit,
            "selected_evidence_groups": selected_evidence_groups,
            "default_groups_applied": evidence_groups is None,
            "not_selected_evidence_groups": [
                group
                for group, _description in CANDIDATE_EVIDENCE_GROUPS
                if group not in set(selected_evidence_groups)
                and available_evidence_group_counts[group]
            ],
        },
        "available_evidence_groups": _available_evidence_group_summary(available_evidence_group_counts),
        "summary": {
            "total_match_records": total_match_records,
            "total_match_variants": len(grouped),
            "total_exact_match_variants": total_exact_allele_match_variants,
            "total_exact_allele_match_variants": total_exact_allele_match_variants,
            "total_consumer_array_inferred_match_variants": total_consumer_array_inferred_match_variants,
            "selected_candidate_variants": len(candidates),
            "emitted_candidate_variants": len(emitted_candidates),
            "truncated": len(candidates) > limit,
            "match_basis_counts": match_basis_counts.most_common(),
            "available_evidence_group_counts": _ordered_candidate_evidence_group_counts(
                available_evidence_group_counts
            ),
            "tag_counts": tag_counts.most_common(),
            "bucket_counts": _ordered_bucket_counts(bucket_counts),
            "clinical_significance_counts": clinical_significance.most_common(),
            "review_status_counts": review_status.most_common(),
        },
        "candidate_buckets": _candidate_bucket_summary(candidates, emitted_candidates),
        "evidence_options": _candidate_inventory_options(
            selected_evidence_groups,
            available_evidence_group_counts,
            emitted_candidates,
        ),
        "evidence_context": evidence_context(
            "research",
            reason="Candidate inventory is static evidence; the agent chooses the target and continues in intent research when source context is needed.",
            commands=[
                "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
                "genomi call research.build_target_packet --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"topic\",\"topic\":\"<topic>\"}'",
            ],
        ),
        "notes": [
            "This command builds a deterministic candidate inventory for host-agent clinical-context interpretation.",
            "User questions are open-ended and belong to the agent's reasoning; evidence lenses are source-derived filters, not intent presets.",
            "candidate_buckets are evidence summary groups, not diagnoses.",
            "clinvar_triage_score is only a ClinVar evidence-strength display aid, not a clinical priority score.",
            "Use match_basis_counts and each candidate's match_provenance before treating a ClinVar hit as an exact VCF allele observation.",
            "summary.total_exact_match_variants counts exact allele provenance only; use summary.total_match_variants for all provenance-marked matches.",
            "Population frequency tags are facts for the agent to interpret against user intent; clinvar_triage_score remains a ClinVar evidence-strength display aid.",
            "Missing population evidence means run a population evidence tool if the candidate is worth investigating.",
        ],
        "candidate_inventory": emitted_candidates,
        "candidate_review_groups": candidate_review_groups,
    }
    apply_evidence_view(
        payload,
        candidate_evidence,
        operation="clinvar.scan_candidates",
        personal_context=_env._personal_context(uses_personal_dna=True, source="clinvar_matches"),
    )
    if output is not None and manifest_path is not None:
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest = {
            **cache_expected,
            "created_at_utc": utc_now(),
            "output_metadata": file_metadata(output),
            "summary": payload["summary"],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        payload["manifest_path"] = str(manifest_path)
    return payload


def _candidate_count_by_match_basis(candidates: list[dict[str, Any]], match_bases: set[str]) -> int:
    count = 0
    for candidate in candidates:
        candidate_bases = {
            str(basis)
            for basis, _count in ((candidate.get("match_provenance") or {}).get("match_basis_counts") or [])
        }
        if candidate_bases & match_bases:
            count += 1
    return count


def _candidate_allele_from_match(item: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    provenance = item.get("match_provenance")
    inferred = provenance.get("inferred_clinvar_allele") if isinstance(provenance, dict) else None
    if isinstance(inferred, dict):
        return {
            "chrom": inferred.get("chrom"),
            "pos": inferred.get("pos"),
            "ref": inferred.get("ref"),
            "alt": inferred.get("alt"),
        }
    clinvar = item.get("clinvar")
    if isinstance(clinvar, dict):
        return {
            "chrom": clinvar.get("chrom") or sample.get("chrom"),
            "pos": clinvar.get("pos") or sample.get("pos"),
            "ref": clinvar.get("ref") or sample.get("ref"),
            "alt": clinvar.get("alt") or sample.get("alt"),
        }
    return {
        "chrom": sample.get("chrom"),
        "pos": sample.get("pos"),
        "ref": sample.get("ref"),
        "alt": sample.get("alt"),
    }


def _clinvar_candidate_evidence_view(
    candidates: list[dict[str, Any]],
    *,
    genome_build: str,
    selected_evidence_groups: list[str],
    population_source: str | None,
    population: str | None,
) -> dict[str, Any]:
    matrix = [_clinvar_candidate_matrix_row(candidate, rank=index + 1) for index, candidate in enumerate(candidates)]
    selected = matrix[0] if matrix else None
    decision_policy = {
        "policy_id": "clinvar_candidate_scan_v1",
        "ranking_order": [
            "ClinVar evidence group selected for review",
            "ClinVar triage evidence strength",
            "variant coordinate for deterministic tie-breaking",
        ],
        "rule": (
            "Provenance-marked ClinVar/sample matches create direct candidate evidence lanes for review. "
            "The lane ranks review targets; it is not a diagnosis or clinical-priority score."
        ),
    }
    warnings = []
    if not matrix:
        warnings.append("no_clinvar_candidate_matches:selected_evidence_groups_empty")
    return evidence_view(
        task_profile=CLINVAR_CANDIDATE_SCAN,
        query={
            "genome_build": genome_build,
            "selected_evidence_groups": selected_evidence_groups,
            "population_source": population_source,
            "population": population,
        },
        candidate_matrix=matrix,
        top_observed_candidate=selected,
        evidence_policy=decision_policy,
        warnings=warnings,
    )


def _clinvar_candidate_matrix_row(candidate: dict[str, Any], *, rank: int) -> dict[str, Any]:
    clinvar = candidate.get("clinvar") or {}
    variant = candidate.get("variant") or {}
    candidate_id = _variant_candidate_id(variant)
    score = min(1.0, max(0.0, float(candidate.get("clinvar_triage_score") or 0) / 120.0))
    best_lane = DIRECT_SOURCE_MATCH if clinvar.get("clinvar_ids") else NEGATIVE_OR_CONFLICTING_EVIDENCE
    lanes = empty_lanes()
    lanes[best_lane] = lane(
        best_lane,
        status="present",
        score=score,
        source="ClinVar",
        matched_text=_clinvar_candidate_matched_text(candidate),
        source_id=", ".join(str(item) for item in (clinvar.get("clinvar_ids") or [])[:5]) or None,
        note=_clinvar_match_lane_note(candidate),
    )
    return {
        "candidate_id": candidate_id,
        "candidate_type": "variant",
        "rank": rank,
        "score": score,
        "evidence_support_level": evidence_support_level_for_score(score),
        "answerability": answerability_for_lane(best_lane),
        "best_evidence_lane": best_lane,
        "evidence_lanes": lanes,
        "supporting_evidence": [
            {
                "source": "ClinVar",
                "clinvar_ids": clinvar.get("clinvar_ids") or [],
                "clinical_significance_counts": clinvar.get("clinical_significance_counts") or [],
                "review_status_counts": clinvar.get("review_status_counts") or [],
                "conditions": clinvar.get("conditions") or [],
                "genes": candidate.get("genes") or [],
                "population_evidence": candidate.get("population_evidence") or {},
                "genotype_support": candidate.get("genotype_support") or {},
                "match_provenance": candidate.get("match_provenance") or {},
                "match_basis_counts": clinvar.get("match_basis_counts") or [],
                "source_format_counts": clinvar.get("source_format_counts") or [],
                "source_record_format_counts": clinvar.get("source_record_format_counts") or [],
                "agi_record_format_counts": clinvar.get("agi_record_format_counts") or [],
            }
        ],
        "counter_evidence": _clinvar_counter_evidence(candidate),
        "why_not_selected": [] if rank == 1 else ["Lower deterministic ClinVar candidate triage rank than the selected review target."],
    }


def _variant_candidate_id(variant: dict[str, Any]) -> str:
    return "variant:{chrom}-{pos}-{ref}-{alt}".format(
        chrom=variant.get("chrom"),
        pos=variant.get("pos"),
        ref=variant.get("ref"),
        alt=variant.get("alt"),
    )


def _clinvar_match_lane_note(candidate: dict[str, Any]) -> str:
    match_bases = {
        str(basis)
        for basis, _count in ((candidate.get("match_provenance") or {}).get("match_basis_counts") or [])
    }
    if MATCH_BASIS_CONSUMER_ARRAY_ALLELE_INFERENCE in match_bases:
        return "candidate includes consumer-array allele inference from an observed genotype string; do not describe it as an exact VCF allele match"
    if MATCH_BASIS_LIFTOVER_EXACT_ALLELE in match_bases:
        return "candidate is an exact sample allele match after liftover to the ClinVar cache build"
    if MATCH_BASIS_LIFTOVER_MULTIALLELIC_ALT in match_bases:
        return "candidate is a selected alternate allele from a multiallelic sample record after liftover"
    if MATCH_BASIS_MULTIALLELIC_ALT in match_bases:
        return "candidate is a selected alternate allele from a multiallelic sample record"
    return "candidate is an exact sample allele match to ClinVar records"


def _clinvar_candidate_matched_text(candidate: dict[str, Any]) -> str:
    clinvar = candidate.get("clinvar") or {}
    significance = ", ".join(f"{label}:{count}" for label, count in (clinvar.get("clinical_significance_counts") or [])[:3])
    genes = ", ".join(candidate.get("genes") or [])
    variant = candidate.get("variant") or {}
    return f"{_variant_candidate_id(variant)} {genes} {significance}".strip()


def _clinvar_counter_evidence(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    counter: list[dict[str, Any]] = []
    tags = set(candidate.get("tags") or [])
    if "clinvar_conflicting" in tags or "review_status_conflicting" in tags:
        counter.append({"type": "conflicting_classification", "note": "ClinVar records include conflicting classification context."})
    if "population_frequency_common" in tags or "population_homozygotes_present" in tags:
        counter.append({"type": "population_tension", "note": "Public population evidence may downgrade disease-style interpretation."})
    if "clinvar_benign_or_likely_benign" in tags:
        counter.append({"type": "benign_classification", "note": "ClinVar includes benign or likely benign classification context."})
    return counter


def _candidate_inventory_options(
    selected_evidence_groups: list[str],
    available_evidence_group_counts: Counter[str],
    emitted_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence_options: list[dict[str, Any]] = []
    not_selected = [
        group
        for group, _description in CANDIDATE_EVIDENCE_GROUPS
        if group not in set(selected_evidence_groups) and available_evidence_group_counts[group]
    ]
    if not_selected:
        evidence_options.append(
            {
                "component": "candidate_inventory_lens",
                "state": "additional_source_groups_available",
                "available_operation": "clinvar.scan_candidates",
                "available_values": not_selected,
                "evidence_context": evidence_context(
                    "static",
                    reason="Rebuilding a source-derived candidate inventory is deterministic static annotation work.",
                ),
            }
        )
    if emitted_candidates:
        first = emitted_candidates[0]["variant"]
        options = ["--fetch-missing-gnomad"]
        if emitted_candidates[0].get("population_evidence", {}).get("status") == "present":
            options = []
        evidence_options.append(
            {
                "component": "selected_candidate_evidence",
                "state": "available_for_target_scoped_lookup",
                "available_operation": "variant.gather_allele_context",
                "target": {"chrom": first.get("chrom"), "pos": first.get("pos"), "ref": first.get("ref"), "alt": first.get("alt")},
                "options": options,
                "evidence_context": evidence_context(
                    "research",
                    reason="Selected candidate alleles move from static inventory into target-scoped research gathering.",
                ),
            }
        )
    if emitted_candidates:
        evidence_options.append(
            {
                "component": "selected_candidate_reviewed_source_context",
                "state": "may_be_needed_for_interpretation",
                "available_operations": ["research.record", "variant.gather_allele_context", "variant.gather_gene_context"],
                "evidence_context": evidence_context(
                    "research",
                    reason="Focused Journal source-review findings must be stored before candidate interpretation or reporting.",
                ),
            }
        )
    elif not not_selected:
        evidence_options.append(
            {
                "component": "candidate_inventory",
                "state": "no_candidates_selected",
                "evidence_boundary": "No candidates were selected in the chosen ClinVar match inventory lenses.",
                "evidence_context": evidence_context(
                    "research",
                    reason="No static candidates were selected; any further answer or broader target decision belongs in intent research.",
                ),
            }
        )
    return evidence_options
