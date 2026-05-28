from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from ...runtime.handoff import evidence_context

from .helpers import (
    _gene_symbols,
)
from .connection import (
    _ensure_schema,
    _read_metadata,
    connect_evidence,
)
from .clinvar_query import (
    _clinvar_gene_summary,
    _sample_gene_matches,
    query_clinvar,
    query_genotype_support,
    query_region_callability_for_locus,
    query_sample_qc,
)
from .population import (
    query_population_frequency,
    summarize_population_frequency,
)
from .research import (
    _research_evidence_for_variant,
    query_research_findings,
)



def gather_variant_evidence(
    evidence_db: str | Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    matches_path: str | Path | None = None,
    genome_build: str = "GRCh38",
    population_source: str | None = None,
    population: str | None = None,
    clinvar_limit: int = 20,
    population_limit: int = 20,
    sample_limit: int = 20,
) -> dict[str, Any]:
    clinvar = query_clinvar(
        evidence_db,
        chrom,
        pos,
        ref,
        alt,
        genome_build=genome_build,
        limit=clinvar_limit,
    )
    population_frequency = query_population_frequency(
        evidence_db,
        chrom,
        pos,
        ref,
        alt,
        genome_build=genome_build,
        source=population_source,
        population=population,
        limit=population_limit,
    )
    population_frequency_for_summary = population_frequency
    if population_limit < 500:
        population_frequency_for_summary = query_population_frequency(
            evidence_db,
            chrom,
            pos,
            ref,
            alt,
            genome_build=genome_build,
            source=population_source,
            population=population,
            limit=500,
        )
    sample_matches = None
    if matches_path is not None:
        sample_matches = _sample_variant_matches(
            chrom,
            pos,
            ref,
            alt,
            Path(matches_path),
            limit=sample_limit,
        )
    sample_qc = query_sample_qc(evidence_db, genome_build=genome_build, limit=5)
    genotype_support = query_genotype_support(
        evidence_db,
        chrom,
        pos,
        ref,
        alt,
        genome_build=genome_build,
        limit=10,
    )
    region_callability = query_region_callability_for_locus(
        evidence_db,
        chrom,
        pos,
        genome_build=genome_build,
        limit=10,
    )

    gene_symbols = sorted(
        {
            symbol
            for record in clinvar["records"]
            for symbol in _gene_symbols(record.get("gene_info") or "")
        }
    )
    research_evidence = _research_evidence_for_variant(
        evidence_db,
        chrom,
        pos,
        ref,
        alt,
        genome_build=genome_build,
        gene_symbols=gene_symbols,
    )
    return {
        "action": {
            "name": "gather-allele",
            "purpose": "Gather exact evidence for one normalized allele before the agent interprets it.",
            "result_type": "sample observation, ClinVar records, public population comparison, reviewed sources, and evidence-context guidance",
            "scope": [
                "gathers variant evidence for agent synthesis",
                "uses one-sample evidence within zygosity/QC limits",
                "refreshes reviewed source context through the Journal source-review workflow",
            ],
        },
        "query": {
            "chrom": chrom,
            "pos": pos,
            "ref": ref,
            "alt": alt,
            "genome_build": genome_build,
        },
        "sample_observation": sample_matches,
        "private_sample_context": {
            "sample_qc": sample_qc,
            "genotype_support": genotype_support,
            "region_callability": region_callability,
            "source_of_truth": (
                "Use these private Stage 1 rows before treating sample observations as personal evidence. "
                "Run active_genome_index.classify_genotype_support for this allele when genotype_support.latest is missing. "
                "Use a callable region_callability row for negative/reference claims."
            ),
        },
        "curated_evidence": {
            "clinvar": clinvar,
            "gene_symbols": gene_symbols,
        },
        "public_population_compare": population_frequency,
        "public_population_summary": summarize_population_frequency(population_frequency_for_summary),
        "research_evidence": research_evidence,
        "comparison_scope": {
            "sample_only": [
                "genotype, depth, genotype quality, filter status, and exact allele observed in this VCF",
            ],
            "public_population": [
                "aggregate allele frequencies imported from public datasets such as gnomAD, ALFA, or 1000 Genomes",
            ],
            "curated_evidence": [
                "ClinVar assertions and gene-level evidence",
            ],
            "not_available_from_one_vcf": [
                "de novo status",
                "family segregation",
                "case/control enrichment inside a private cohort",
                "reliable cis/trans phase for separate heterozygous variants unless the VCF itself is phased",
            ],
        },
        "notes": [
            "This action gathers evidence only; the agent or a downstream reviewer must interpret it in context.",
            "Population rows are public aggregate comparisons.",
            "Empty population results mean the local public population store has no matching row for the exact normalized allele.",
            "Use source versions and access dates when currentness matters to the user's question.",
            "If current source context matters, gather reviewed source evidence before interpretation.",
        ],
        "evidence_options": _variant_evidence_options(
            chrom,
            pos,
            ref,
            alt,
            gene_symbols,
            population_frequency,
            research_evidence,
            genotype_support,
        ),
    }


def fetch_gene_evidence(
    gene: str,
    evidence_db: str | Path,
    *,
    matches_path: str | Path | None = None,
    genome_build: str = "GRCh38",
    clinvar_limit: int = 50,
    sample_limit: int = 50,
) -> dict[str, Any]:
    gene = gene.strip()
    if not gene:
        raise ValueError("gene is required")
    normalized_gene = gene.upper()
    evidence_db = Path(evidence_db)
    if not evidence_db.exists():
        raise FileNotFoundError(evidence_db)

    with connect_evidence(evidence_db) as connection:
        _ensure_schema(connection)
        metadata = _read_metadata(connection)
        clinvar_summary = _clinvar_gene_summary(
            connection,
            normalized_gene,
            genome_build=genome_build,
            limit=clinvar_limit,
        )

    sample_matches = None
    if matches_path is not None:
        sample_matches = _sample_gene_matches(
            normalized_gene,
            Path(matches_path),
            limit=sample_limit,
        )
    research_evidence = query_research_findings(
        evidence_db,
        "gene",
        gene=normalized_gene,
        genome_build=genome_build,
        limit=clinvar_limit,
    )

    return {
        "action": {
            "name": "gather-gene",
            "purpose": "Gather ClinVar gene context, sample-specific matches, and reviewed source context before the agent answers a gene-level question.",
            "result_type": "gene-level ClinVar summary, sample matches, reviewed sources, links, and evidence-context guidance",
            "scope": [
                "gathers gene context after the agent selects the gene",
                "summarizes gene-level sample and ClinVar context",
                "refreshes reviewed source context through the Journal source-review workflow",
            ],
        },
        "query": {
            "gene": normalized_gene,
            "genome_build": genome_build,
        },
        "sources": {
            "evidence_db": str(evidence_db),
            "matches_path": str(matches_path) if matches_path is not None else None,
            "clinvar_source": metadata.get("clinvar_source"),
            "clinvar_source_version": metadata.get("clinvar_source_version"),
            "clinvar_genome_build": metadata.get("clinvar_genome_build"),
        },
        "clinvar_gene": clinvar_summary,
        "sample_matches": sample_matches,
        "research_evidence": research_evidence,
        "links": {
            "clinvar_gene_search": f"https://www.ncbi.nlm.nih.gov/clinvar/?term={normalized_gene}%5Bgene%5D",
            "ncbi_gene_search": f"https://www.ncbi.nlm.nih.gov/gene/?term={normalized_gene}%5BGene%20Name%5D%20AND%20Homo%20sapiens%5BOrganism%5D",
            "clinvar_submission_review_status": "https://www.ncbi.nlm.nih.gov/clinvar/docs/review_status/",
        },
        "notes": [
            "This is evidence retrieval for host-agent interpretation and medical-context wording.",
            "ClinVar gene matching uses exact gene symbols parsed from GENEINFO, not substring matching.",
            "Compact ClinVar records are ordered by clinical-significance category and review status for review convenience.",
            "If current source context matters, gather reviewed source evidence before interpretation.",
        ],
        "evidence_options": _gene_evidence_options(normalized_gene, sample_matches, research_evidence),
    }


def _variant_evidence_options(
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    gene_symbols: list[str],
    population_frequency: dict[str, Any],
    research_evidence: dict[str, Any],
    genotype_support: dict[str, Any],
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    support = (genotype_support or {}).get("latest")
    if support is None:
        options.append(
            {
                "component": "sample_genotype_support",
                "state": "missing",
                "available_operation": "active_genome_index.classify_genotype_support",
                "target": {"chrom": chrom, "pos": pos, "ref": ref, "alt": alt},
                "missing_evidence": "deterministic genotype-support status for the sample observation",
                "evidence_context": evidence_context(
                    "static",
                    reason="Observed sample alleles need deterministic genotype-support rows before personal interpretation.",
                ),
            }
        )
    elif support.get("support_status") != "supported":
        options.append(
            {
                "component": "sample_genotype_support",
                "state": str(support.get("support_status") or "limited"),
                "available_operation": "active_genome_index.classify_genotype_support",
                "target": {"chrom": chrom, "pos": pos, "ref": ref, "alt": alt},
                "evidence_boundary": "Only support_status=supported contributes genotype_support_supported evidence.",
                "current_support_status": support.get("support_status"),
                "evidence_context": evidence_context(
                    "static",
                    reason="Weak, unknown, no-call, or not-observed genotype support is a sample-evidence limitation for host-agent synthesis.",
                ),
            }
        )
    if int(population_frequency.get("count") or 0) == 0:
        options.append(
            {
                "component": "public_population_frequency",
                "state": "missing",
                "available_operation": "gnomad.fetch_population_frequency",
                "target": {"chrom": chrom, "pos": pos, "ref": ref, "alt": alt},
                "missing_evidence": "public population evidence for this exact normalized allele",
                "evidence_context": evidence_context(
                    "static",
                    reason="Missing public population evidence is deterministic static-source work before research interpretation continues.",
                ),
            }
        )
    exact_research_count = int((research_evidence.get("exact_variant") or {}).get("count") or 0)
    gene_research_missing = [
        gene
        for gene, evidence in (research_evidence.get("genes") or {}).items()
        if int(evidence.get("count") or 0) == 0
    ]
    if exact_research_count == 0 or gene_research_missing:
        options.append(
            {
                "component": "reviewed_source_context",
                "state": "missing_or_incomplete",
                "available_operations": ["research.record", "variant.gather_allele_context"],
                "focused_research_scopes": _focused_research_scope_suggestions(
                    chrom,
                    pos,
                    ref,
                    alt,
                    gene_symbols,
                    exact_research_count,
                    gene_research_missing,
                ),
                "evidence_context": evidence_context(
                    "research",
                    reason="Current source context must be reviewed and written back before interpretation.",
                ),
            }
        )
    options.append(
        {
            "component": "variant_evidence_packet",
            "state": "available",
            "evidence_boundaries": [
                "Medical language is informational.",
                "De novo status needs family or segregation evidence.",
                "Cis/trans phase needs phased sample data.",
            ],
            "evidence_context": evidence_context(
                "research",
                reason="Gathered evidence can be interpreted within the research contract or rendered from agent-selected report claims.",
            ),
        }
    )
    return options


def _gene_evidence_options(
    gene: str,
    sample_matches: dict[str, Any] | None,
    research_evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    sample_records = int((sample_matches or {}).get("total_records") or 0)
    if sample_records:
        options.append(
            {
                "component": "gene_sample_observations",
                "state": "sample_variants_present",
                "available_operation": "variant.gather_allele_context",
                "evidence_boundary": "Gene-level context does not replace variant-level evidence for a selected observed allele.",
                "evidence_context": evidence_context(
                    "research",
                    reason="Specific allele interpretation needs refreshed variant context.",
                ),
            }
        )
    if int(research_evidence.get("count") or 0) == 0:
        options.append(
            {
                "component": "gene_reviewed_source_context",
                "state": "missing",
                "available_operations": ["research.record", "variant.gather_gene_context"],
                "focused_research_scope": {
                    "scope": "gene_context",
                    "target": {"type": "gene", "gene": gene},
                    "research_focus": "Current gene-disease mechanism, inheritance, and evidence-validity context relevant to the user's inquiry.",
                },
                "evidence_context": evidence_context(
                    "research",
                    reason="Gene source review must be written back and gathered before interpretation.",
                ),
            }
        )
    options.append(
        {
            "component": "gene_evidence_packet",
            "state": "available",
            "evidence_boundary": "Gene-level facts and variant-level facts remain separate evidence components.",
            "evidence_context": evidence_context(
                "research",
                reason="Gene evidence can be interpreted inside the research contract or rendered from agent-selected report claims.",
            ),
        }
    )
    return options


def _focused_research_scope_suggestions(
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    gene_symbols: list[str],
    exact_research_count: int,
    gene_research_missing: list[str],
) -> list[dict[str, Any]]:
    scopes: list[dict[str, Any]] = []
    if exact_research_count == 0:
        scopes.append(
            {
                "scope": "variant_assertion",
                "target": {"type": "variant", "chrom": chrom, "pos": pos, "ref": ref, "alt": alt},
                "research_focus": "Current official or primary-source evidence about this exact normalized allele.",
            }
        )
    for gene in gene_research_missing:
        scopes.append(
            {
                "scope": "gene_context",
                "target": {"type": "gene", "gene": gene},
                "research_focus": "Current gene-disease mechanism, inheritance, and evidence-validity context relevant to interpreting selected alleles in this gene.",
            }
        )
    return scopes


def _sample_variant_matches(
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    matches_path: Path,
    *,
    limit: int,
) -> dict[str, Any]:
    if not matches_path.exists():
        raise FileNotFoundError(matches_path)

    total = 0
    records: list[dict[str, Any]] = []
    with matches_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            sample = item.get("sample_variant", {})
            if (
                sample.get("chrom") != chrom
                or sample.get("pos") != pos
                or sample.get("ref") != ref
                or sample.get("alt") != alt
            ):
                continue
            total += 1
            if len(records) < limit:
                records.append(item)
    return {
        "matches_path": str(matches_path),
        "total_records": total,
        "record_limit": limit,
        "records": records,
    }
