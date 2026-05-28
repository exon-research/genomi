from __future__ import annotations

from pathlib import Path
from typing import Any

from .context import (
    _build_variant_envelope,
    _public_context,
    _sample_context,
    _support_context,
    _target_inventory,
    _unanswered_components,
)
from .parsing import (
    _clean_allele,
    _clean_chrom,
    _dedupe_targets,
    _effective_genome_build,
    _inferred_allele_targets,
    _int_or_none,
    _normalize_rsid,
    _resolve_targets,
)
from .runs import _selected_evidence_dbs, _selected_runs

JsonObject = dict[str, Any]


def lookup_variant(
    *,
    query: str | None = None,
    rsid: str | None = None,
    chrom: str | None = None,
    pos: int | str | None = None,
    ref: str | None = None,
    alt: str | None = None,
    region: str | None = None,
    genome_build: str = "GRCh38",
    db: str | Path | None = None,
    shared_db: str | Path | None = None,
    agi_id: str | None = None,
    include_active_genome_index: bool = True,
    include_known_active_genome_indexes: bool = False,
    include_fail: bool = False,
    limit: int = 20,
) -> JsonObject:
    """Return deterministic facts for flexible variant-like input.

    This operation is deliberately read-only. It searches parsed Active Genome Index records
    and existing evidence stores; external APIs and evidence writes remain
    separate tools selected by the host agent.
    """

    bounded_limit = max(1, min(int(limit or 20), 200))
    effective_build = _effective_genome_build(genome_build)
    warnings: list[str] = []
    targets = _resolve_targets(
        query=query,
        rsid=rsid,
        chrom=chrom,
        pos=pos,
        ref=ref,
        alt=alt,
        region=region,
        genome_build=effective_build,
        warnings=warnings,
    )
    runs = _selected_runs(
        agi_id=agi_id,
        include_active_genome_index=include_active_genome_index,
        include_known_active_genome_indexes=include_known_active_genome_indexes,
        warnings=warnings,
    )
    evidence_dbs = _selected_evidence_dbs(
        db=db,
        shared_db=shared_db,
        runs=[run for run, _selection in runs],
    )

    public_context = _public_context(targets, evidence_dbs=evidence_dbs, genome_build=effective_build, limit=bounded_limit, warnings=warnings)
    inferred_targets = _inferred_allele_targets(public_context, genome_build=effective_build)
    all_targets = _dedupe_targets([*targets, *inferred_targets])
    sample_context = _sample_context(
        all_targets,
        runs=runs,
        include_fail=include_fail,
        limit=bounded_limit,
        warnings=warnings,
    )
    support_context = _support_context(
        all_targets,
        runs=runs,
        evidence_dbs=evidence_dbs,
        genome_build=effective_build,
        limit=bounded_limit,
        warnings=warnings,
    )
    target_inventory = _target_inventory(
        targets=all_targets,
        sample_context=sample_context,
        public_context=public_context,
        support_context=support_context,
    )
    unanswered_components = _unanswered_components(
        targets=all_targets,
        sample_context=sample_context,
        public_context=public_context,
        support_context=support_context,
    )

    query_scope = {
        "text": query,
        "rsid": _normalize_rsid(rsid) if rsid else None,
        "chrom": _clean_chrom(chrom) if chrom else None,
        "pos": _int_or_none(pos),
        "ref": _clean_allele(ref) if ref else None,
        "alt": _clean_allele(alt) if alt else None,
        "region": region,
        "genome_build": effective_build,
        "agi_id": agi_id,
        "include_active_genome_index": include_active_genome_index,
        "include_known_active_genome_indexes": include_known_active_genome_indexes,
        "include_fail": include_fail,
        "limit": bounded_limit,
    }
    variant_env = _build_variant_envelope(
        targets=all_targets,
        sample_context=sample_context,
        public_context=public_context,
        support_context=support_context,
        unanswered_components=unanswered_components,
        query_scope=query_scope,
    )
    return {
        "schema": "genomi-variant-lookup-v1",
        "query": query_scope,
        "resolved_targets": all_targets,
        "sample_context": sample_context,
        "public_context": public_context,
        "support_context": support_context,
        "target_inventory": target_inventory,
        "unanswered_answer_components": unanswered_components,
        "warnings": warnings,
        "evidence_envelope": variant_env,
    }
