from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any
from ...runtime.external import file_metadata, matching_manifest, utc_now
from ...runtime.handoff import evidence_context

from .candidate_inventory_payload import (
    DEFAULT_RETURNED_CANDIDATE_LIMIT,
    MATERIALIZED_CANDIDATE_LIMIT,
    MAX_RETURNED_CANDIDATE_LIMIT,
    _build_inventory_payload,
    _host_selected_candidates,
    _inventory_selection,
    _returned_inventory_from_materialized,
)
from .constants import (
    CANDIDATE_RULE_SET_VERSION,
    DEFAULT_CANDIDATE_EVIDENCE_GROUPS,
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
    _build_candidate,
    _candidate_buckets,
    _candidate_inventory_sort_key,
    _candidate_is_selected,
    _enrich_candidate_population,
    _normalize_candidate_evidence_groups,
    _ordered_candidate_evidence_group_counts,
)
from .clinvar_match_provenance import (
    MATCH_BASIS_CONSUMER_ARRAY_ALLELE_INFERENCE,
    MATCH_BASIS_EXACT_ALLELE,
    MATCH_BASIS_LIFTOVER_EXACT_ALLELE,
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
    limit: int = DEFAULT_RETURNED_CANDIDATE_LIMIT,
    offset: int = 0,
    gene: str | None = None,
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
    if limit > MAX_RETURNED_CANDIDATE_LIMIT:
        raise ValueError(f"limit must be <= {MAX_RETURNED_CANDIDATE_LIMIT}")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    selected_gene = str(gene).strip().upper() if gene not in (None, "") else None
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
        "materialized_candidate_limit": MATERIALIZED_CANDIDATE_LIMIT,
        # `gene` and `evidence_groups` select what this call returns; the
        # materialized inventory always covers every ClinVar evidence group so
        # one narrow request cannot overwrite the shared file with its slice.
        "materialized_evidence_groups": list(DEFAULT_CANDIDATE_EVIDENCE_GROUPS),
        "rule_set_version": CANDIDATE_RULE_SET_VERSION,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        if not force:
            cached = matching_manifest(manifest_path, cache_expected, required_paths=[output])
            if cached is not None:
                materialized_payload = json.loads(output.read_text(encoding="utf-8"))
                payload = _returned_inventory_from_materialized(
                    materialized_payload,
                    genome_build=genome_build,
                    population_source=population_source,
                    population=population,
                    selected_evidence_groups=selected_evidence_groups,
                    selected_gene=selected_gene,
                    default_groups_applied=evidence_groups is None,
                    limit=limit,
                    offset=offset,
                )
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
    materialized_candidates: list[dict[str, Any]] = []
    for group in grouped.values():
        candidate = _build_candidate(
            group,
            evidence_db_path=None,
            genome_build=genome_build,
            population_source=population_source,
            population=population,
        )
        all_candidates.append(candidate)
        if _candidate_is_selected(
            candidate, selected_evidence_groups=list(DEFAULT_CANDIDATE_EVIDENCE_GROUPS)
        ):
            materialized_candidates.append(candidate)

    for candidate in materialized_candidates:
        _enrich_candidate_population(
            candidate,
            evidence_db_path=evidence_db_path,
            genome_build=genome_build,
            population_source=population_source,
            population=population,
        )

    for candidate in materialized_candidates:
        candidate["buckets"] = _candidate_buckets(candidate)

    materialized_candidates.sort(key=_candidate_inventory_sort_key)
    candidates = _host_selected_candidates(
        materialized_candidates,
        selected_evidence_groups=selected_evidence_groups,
        selected_gene=selected_gene,
    )
    available_evidence_group_counts: Counter[str] = Counter()
    for candidate in all_candidates:
        available_evidence_group_counts.update(candidate["evidence_groups"])
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
    match_totals = {
        "total_match_records": total_match_records,
        "total_match_variants": len(grouped),
        "total_exact_match_variants": total_exact_allele_match_variants,
        "total_exact_allele_match_variants": total_exact_allele_match_variants,
        "total_consumer_array_inferred_match_variants": total_consumer_array_inferred_match_variants,
        "match_basis_counts": match_basis_counts.most_common(),
        "available_evidence_group_counts": _ordered_candidate_evidence_group_counts(
            available_evidence_group_counts
        ),
        "clinical_significance_counts": clinical_significance.most_common(),
        "review_status_counts": review_status.most_common(),
    }

    if output is not None and manifest_path is not None:
        materialized_payload = _build_inventory_payload(
            emitted_candidates=materialized_candidates[:MATERIALIZED_CANDIDATE_LIMIT],
            selected_candidates=materialized_candidates,
            available_evidence_group_counts=available_evidence_group_counts,
            selection=_inventory_selection(
                genome_build=genome_build,
                population_source=population_source,
                population=population,
                selected_gene=None,
                selected_evidence_groups=list(DEFAULT_CANDIDATE_EVIDENCE_GROUPS),
                default_groups_applied=True,
                available_evidence_group_counts=available_evidence_group_counts,
            ),
            match_totals=match_totals,
            matches_path=matches_path,
            output=output,
            genome_build=genome_build,
            population_source=population_source,
            population=population,
            offset=0,
            limit=MATERIALIZED_CANDIDATE_LIMIT,
        )
        output.write_text(json.dumps(materialized_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest = {
            **cache_expected,
            "created_at_utc": utc_now(),
            "output_metadata": file_metadata(output),
            "summary": materialized_payload["summary"],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    payload = _build_inventory_payload(
        emitted_candidates=candidates[offset : offset + limit],
        selected_candidates=candidates,
        available_evidence_group_counts=available_evidence_group_counts,
        selection=_inventory_selection(
            genome_build=genome_build,
            population_source=population_source,
            population=population,
            selected_gene=selected_gene,
            selected_evidence_groups=selected_evidence_groups,
            default_groups_applied=evidence_groups is None,
            available_evidence_group_counts=available_evidence_group_counts,
        ),
        match_totals=match_totals,
        matches_path=matches_path,
        output=output,
        genome_build=genome_build,
        population_source=population_source,
        population=population,
        offset=offset,
        limit=limit,
    )
    if output is not None and manifest_path is not None:
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


