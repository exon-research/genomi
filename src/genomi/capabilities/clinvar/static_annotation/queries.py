from __future__ import annotations

from pathlib import Path
from typing import Any

from ....active_genome_index.genotype_qc import (
    assess_genotype_support,
    assess_region_callability,
    assess_sample_qc,
)
from ....active_genome_index.active_genome_index import (
    coverage_query,
    default_active_genome_index_path,
    active_genome_index_summary,
    query_region,
    query_rsid_filtered,
    query_variant,
)
from ....active_genome_index.vcf import parse_region
from ....evidence import (
    default_evidence_path,
    evidence_summary,
    query_clinvar,
    query_population_frequency,
)
from ....runtime.handoff import attach_evidence_context, evidence_context

from ._helpers import (
    WORKFLOW_AREA_ID,
    default_static_outputs,
    workflow_contract,
)


def run_static_sample_qc(
    vcf: str | Path,
    *,
    evidence_db: str | Path | None = None,
    active_genome_index_path: str | Path | None = None,
    output: str | Path | None = None,
    genome_build: str = "auto",
    scan_records: int = 1000,
) -> dict[str, Any]:
    return assess_sample_qc(
        vcf,
        active_genome_index_path=active_genome_index_path,
        evidence_db=evidence_db,
        output=output,
        genome_build=genome_build,
        scan_records=scan_records,
    )


def run_static_genotype_support(
    vcf: str | Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    evidence_db: str | Path | None = None,
    active_genome_index_path: str | Path | None = None,
    output: str | Path | None = None,
    genome_build: str = "auto",
    reference_fasta: str | Path | None = None,
    min_depth: int = 10,
    min_genotype_quality: int = 20,
) -> dict[str, Any]:
    return assess_genotype_support(
        vcf,
        chrom,
        pos,
        ref,
        alt,
        active_genome_index_path=active_genome_index_path,
        evidence_db=evidence_db,
        output=output,
        genome_build=genome_build,
        reference_fasta=reference_fasta,
        min_depth=min_depth,
        min_genotype_quality=min_genotype_quality,
    )


def run_static_callability(
    vcf: str | Path,
    region: str,
    *,
    evidence_db: str | Path | None = None,
    active_genome_index_path: str | Path | None = None,
    output: str | Path | None = None,
    genome_build: str = "auto",
    min_depth: int = 10,
    min_covered_fraction: float = 0.95,
    limit: int = 5000,
) -> dict[str, Any]:
    return assess_region_callability(
        vcf,
        region,
        active_genome_index_path=active_genome_index_path,
        evidence_db=evidence_db,
        output=output,
        genome_build=genome_build,
        min_depth=min_depth,
        min_covered_fraction=min_covered_fraction,
        limit=limit,
    )


def query_static_variant(
    vcf: str | Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    active_genome_index_path: str | Path | None = None,
    pass_only: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    records = query_variant(vcf, chrom, pos, ref, alt, Path(active_genome_index_path) if active_genome_index_path else default_active_genome_index_path(vcf), pass_only=pass_only, limit=limit)
    return {
        "workflow_area": WORKFLOW_AREA_ID,
        "query": {"type": "variant", "chrom": chrom, "pos": pos, "ref": ref, "alt": alt},
        "count": len(records),
        "records": records,
        "evidence_context": evidence_context(
            "research",
            reason="Variant query output is local sample context for source-backed interpretation.",
            commands=[
                "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
            ],
        ),
    }


def query_static_region(
    vcf: str | Path,
    region: str,
    *,
    active_genome_index_path: str | Path | None = None,
    variants_only: bool = False,
    pass_only: bool = True,
    limit: int = 200,
) -> dict[str, Any]:
    chrom, start, end = parse_region(region)
    records = query_region(
        vcf,
        chrom,
        start,
        end,
        Path(active_genome_index_path) if active_genome_index_path else default_active_genome_index_path(vcf),
        variants_only=variants_only,
        pass_only=pass_only,
        limit=limit,
    )
    return {
        "workflow_area": WORKFLOW_AREA_ID,
        "query": {"type": "region", "region": region},
        "count": len(records),
        "records": records,
        "evidence_context": evidence_context(
            "research",
            reason="Region query output is local sample context for target selection and source-backed interpretation.",
            commands=[
                "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
            ],
        ),
    }


def query_static_rsid(
    vcf: str | Path,
    rsid: str,
    *,
    active_genome_index_path: str | Path | None = None,
    pass_only: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    records = query_rsid_filtered(vcf, rsid, Path(active_genome_index_path) if active_genome_index_path else default_active_genome_index_path(vcf), pass_only=pass_only, limit=limit)
    return {
        "workflow_area": WORKFLOW_AREA_ID,
        "query": {"type": "rsid", "rsid": rsid},
        "count": len(records),
        "records": records,
        "evidence_context": evidence_context(
            "research",
            reason="rsID query output is local sample context for interpretation or claim-status assessment.",
            commands=[
                "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
                "genomi call research.build_target_packet --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"variant\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
            ],
        ),
    }


def query_static_coverage(
    vcf: str | Path,
    region: str,
    *,
    active_genome_index_path: str | Path | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    chrom, start, end = parse_region(region)
    payload = coverage_query(vcf, chrom, start, end, Path(active_genome_index_path) if active_genome_index_path else default_active_genome_index_path(vcf), limit=limit)
    payload["workflow_area"] = WORKFLOW_AREA_ID
    return attach_evidence_context(
        payload,
        "research",
        reason="Coverage/callability context is a static input for target-specific claim assessment.",
        commands=[
            "genomi call variant.gather_gene_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"gene\":\"<gene>\"}'",
        ],
    )


def static_db_lookup(
    evidence_db: str | Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    genome_build: str = "GRCh38",
) -> dict[str, Any]:
    return {
        "workflow_area": WORKFLOW_AREA_ID,
        "clinvar": query_clinvar(evidence_db, chrom, pos, ref, alt, genome_build=genome_build),
        "population": query_population_frequency(evidence_db, chrom, pos, ref, alt, genome_build=genome_build),
        "evidence_context": evidence_context(
            "research",
            reason="Static DB lookup output is structured evidence for source-backed interpretation.",
            commands=[
                "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
            ],
        ),
    }


def summarize_static_state(vcf: str | Path, *, evidence_db: str | Path | None = None) -> dict[str, Any]:
    db_path = Path(evidence_db) if evidence_db is not None else default_evidence_path(vcf)
    return {
        "workflow_area": WORKFLOW_AREA_ID,
        "contract": workflow_contract(),
        "active_genome_index": active_genome_index_summary(default_active_genome_index_path(vcf)) if default_active_genome_index_path(vcf).exists() else None,
        "evidence": evidence_summary(db_path) if db_path.exists() else None,
        "outputs": default_static_outputs(vcf),
        "evidence_context": evidence_context(
            "research",
            reason="Static state is summarized for user-intent target research.",
            commands=["genomi call research.build_target_packet --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"gene\",\"gene\":\"<gene>\"}'"],
        ),
    }
