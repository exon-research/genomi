from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from .helpers import (
    _chrom_lookup_values,
    _gene_symbols,
    _has_strict_pathogenic_component,
    _json_object,
)
from .connection import (
    _ensure_schema,
    _read_metadata,
    connect_evidence,
)



def query_clinvar(
    evidence_db: str | Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    genome_build: str = "GRCh38",
    limit: int = 20,
) -> dict[str, Any]:
    with connect_evidence(evidence_db) as connection:
        _ensure_schema(connection)
        rows = [
            dict(row)
            for row in connection.execute(
                """
                select chrom, pos, ref, alt, genome_build, clinvar_id, allele_id,
                       clinical_significance, review_status, conditions, gene_info,
                       hgvs, source_path, source_version, imported_at
                from clinvar_variants
                where chrom = ? and pos = ? and ref = ? and alt = ? and genome_build = ?
                order by imported_at desc
                limit ?
                """,
                (chrom, pos, ref, alt, genome_build, limit),
            )
        ]
    return {
        "query": {
            "source": "clinvar",
            "chrom": chrom,
            "pos": pos,
            "ref": ref,
            "alt": alt,
            "genome_build": genome_build,
        },
        "count": len(rows),
        "records": rows,
    }


def query_sample_qc(
    evidence_db: str | Path,
    *,
    genome_build: str = "GRCh38",
    limit: int = 10,
) -> dict[str, Any]:
    with connect_evidence(evidence_db) as connection:
        _ensure_schema(connection)
        rows = [
            _sample_qc_row(row)
            for row in connection.execute(
                """
                select sample_id, vcf_path, genome_build, input_type, has_reference_blocks,
                       has_depth, has_genotype_quality, absence_claims_allowed,
                       summary_json, evidence_boundaries_json, created_at
                from sample_qc
                where genome_build = ?
                order by created_at desc
                limit ?
                """,
                (genome_build, limit),
            )
        ]
    return {
        "query": {
            "source": "sample_qc",
            "genome_build": genome_build,
        },
        "count": len(rows),
        "latest": rows[0] if rows else None,
        "records": rows,
    }


def query_genotype_support(
    evidence_db: str | Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    genome_build: str = "GRCh38",
    limit: int = 10,
) -> dict[str, Any]:
    with connect_evidence(evidence_db) as connection:
        _ensure_schema(connection)
        rows = [
            _genotype_support_row(row)
            for row in connection.execute(
                """
                select vcf_path, chrom, pos, ref, alt, genome_build, support_status,
                       evidence_class, genotype, zygosity, depth, genotype_quality,
                       filter, raw_json, created_at
                from genotype_support
                where chrom = ? and pos = ? and ref = ? and alt = ? and genome_build = ?
                order by created_at desc
                limit ?
                """,
                (chrom, pos, ref, alt, genome_build, limit),
            )
        ]
    return {
        "query": {
            "source": "genotype_support",
            "chrom": chrom,
            "pos": pos,
            "ref": ref,
            "alt": alt,
            "genome_build": genome_build,
        },
        "count": len(rows),
        "latest": rows[0] if rows else None,
        "records": rows,
    }


def query_region_callability_for_locus(
    evidence_db: str | Path,
    chrom: str,
    pos: int,
    *,
    genome_build: str = "GRCh38",
    limit: int = 10,
) -> dict[str, Any]:
    with connect_evidence(evidence_db) as connection:
        _ensure_schema(connection)
        rows = [
            _region_callability_row(row)
            for row in connection.execute(
                """
                select vcf_path, region, chrom, start, end, genome_build, callability_status,
                       covered_fraction, can_support_negative_claim, evidence_class,
                       raw_json, created_at
                from region_callability
                where chrom = ? and start <= ? and end >= ? and genome_build = ?
                order by can_support_negative_claim desc, (end - start) asc, created_at desc
                limit ?
                """,
                (chrom, pos, pos, genome_build, limit),
            )
        ]
    return {
        "query": {
            "source": "region_callability",
            "chrom": chrom,
            "pos": pos,
            "genome_build": genome_build,
        },
        "count": len(rows),
        "best": rows[0] if rows else None,
        "records": rows,
    }


def _query_clinvar_exact_rows(
    connection: sqlite3.Connection,
    *,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    genome_build: str,
    limit: int,
) -> list[sqlite3.Row]:
    chrom_values = _chrom_lookup_values(chrom)
    chrom_placeholders = ", ".join("?" for _chrom in chrom_values)
    return connection.execute(
        f"""
        select chrom, pos, ref, alt, genome_build, clinvar_id, allele_id,
               clinical_significance, review_status, conditions, gene_info,
               hgvs, source_path, source_version, imported_at
        from clinvar_variants
        where chrom in ({chrom_placeholders}) and pos = ? and ref = ? and alt = ? and genome_build = ?
        order by imported_at desc
        limit ?
        """,
        (*chrom_values, pos, ref, alt, genome_build, limit),
    ).fetchall()


def evidence_summary(evidence_db: str | Path) -> dict[str, Any]:
    with connect_evidence(evidence_db) as connection:
        _ensure_schema(connection)
        metadata = _read_metadata(connection)
        clinvar_count = connection.execute("select count(*) as records from clinvar_variants").fetchone()["records"]
        gene_link_count = connection.execute("select count(*) as records from clinvar_variant_genes").fetchone()["records"]
        population_count = connection.execute("select count(*) as records from population_frequencies").fetchone()["records"]
        research_count = connection.execute("select count(*) as records from research_findings").fetchone()["records"]
        sample_qc_count = connection.execute("select count(*) as records from sample_qc").fetchone()["records"]
        genotype_support_count = connection.execute("select count(*) as records from genotype_support").fetchone()["records"]
        callability_count = connection.execute("select count(*) as records from region_callability").fetchone()["records"]
        population_sources = [
            dict(row)
            for row in connection.execute(
                """
                select source, source_version, genome_build, population, count(*) as records
                from population_frequencies
                group by source, source_version, genome_build, population
                order by source, population
                """
            )
        ]
    return {
        "evidence_db": str(evidence_db),
        "metadata": metadata,
        "tables": {
            "clinvar_variants": clinvar_count,
            "clinvar_variant_genes": gene_link_count,
            "population_frequencies": population_count,
            "research_findings": research_count,
            "sample_qc": sample_qc_count,
            "genotype_support": genotype_support_count,
            "region_callability": callability_count,
        },
        "population_sources": population_sources,
    }


def _sample_qc_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "source": "private_db",
        "table": "sample_qc",
        "sample_id": row["sample_id"],
        "vcf_path": row["vcf_path"],
        "genome_build": row["genome_build"],
        "input_type": row["input_type"],
        "has_reference_blocks": bool(row["has_reference_blocks"]),
        "has_depth": bool(row["has_depth"]),
        "has_genotype_quality": bool(row["has_genotype_quality"]),
        "absence_claims_allowed": bool(row["absence_claims_allowed"]),
        "summary": _json_object(row["summary_json"]),
        "evidence_boundaries": _json_object(row["evidence_boundaries_json"]),
        "created_at": row["created_at"],
    }


def _genotype_support_row(row: sqlite3.Row) -> dict[str, Any]:
    raw = _json_object(row["raw_json"])
    accepted = raw.get("accepted_report_evidence_classes")
    if not isinstance(accepted, list):
        accepted = ["sample_observation", "genotype_support_supported"] if row["support_status"] == "supported" else []
    return {
        "source": "private_db",
        "table": "genotype_support",
        "vcf_path": row["vcf_path"],
        "chrom": row["chrom"],
        "pos": row["pos"],
        "ref": row["ref"],
        "alt": row["alt"],
        "genome_build": row["genome_build"],
        "support_status": row["support_status"],
        "evidence_class": row["evidence_class"],
        "accepted_report_evidence_classes": accepted,
        "sample_observation": raw.get("sample_observation")
        or {
            "genotype": row["genotype"],
            "zygosity": row["zygosity"],
            "depth": row["depth"],
            "genotype_quality": row["genotype_quality"],
            "filter": row["filter"],
        },
        "evidence_boundaries": raw.get("evidence_boundaries"),
        "created_at": row["created_at"],
    }


def _region_callability_row(row: sqlite3.Row) -> dict[str, Any]:
    raw = _json_object(row["raw_json"])
    accepted = raw.get("accepted_report_evidence_classes")
    if not isinstance(accepted, list):
        accepted = ["reference_inference_or_assay_completeness"] if row["can_support_negative_claim"] else []
    return {
        "source": "private_db",
        "table": "region_callability",
        "vcf_path": row["vcf_path"],
        "region": row["region"],
        "chrom": row["chrom"],
        "start": row["start"],
        "end": row["end"],
        "genome_build": row["genome_build"],
        "callability_status": row["callability_status"],
        "covered_fraction": row["covered_fraction"],
        "can_support_negative_or_reference_claim": bool(row["can_support_negative_claim"]),
        "evidence_class": row["evidence_class"],
        "accepted_report_evidence_classes": accepted,
        "evidence_boundaries": raw.get("evidence_boundaries"),
        "created_at": row["created_at"],
    }


def _clinvar_gene_summary(
    connection: sqlite3.Connection,
    gene: str,
    *,
    genome_build: str,
    limit: int,
) -> dict[str, Any]:
    table_sql, where, params, lookup_mode = _gene_query_parts(connection, gene, genome_build)
    total = int(
        connection.execute(
            f"select count(*) as records from {table_sql} where {where}",
            params,
        ).fetchone()["records"]
    )
    clinical_significance_counts = [
        [row["clinical_significance"] or "missing", int(row["records"])]
        for row in connection.execute(
            f"""
            select cv.clinical_significance as clinical_significance, count(*) as records
            from {table_sql}
            where {where}
            group by cv.clinical_significance
            order by records desc
            """,
            params,
        )
    ]
    review_status_counts = [
        [row["review_status"] or "missing", int(row["records"])]
        for row in connection.execute(
            f"""
            select cv.review_status as review_status, count(*) as records
            from {table_sql}
            where {where}
            group by cv.review_status
            order by records desc
            """,
            params,
        )
    ]
    compact_records = [
        dict(row)
        for row in connection.execute(
            f"""
            select cv.chrom, cv.pos, cv.ref, cv.alt, cv.genome_build, cv.clinvar_id, cv.allele_id,
                   cv.clinical_significance, cv.review_status, cv.conditions, cv.gene_info,
                   cv.hgvs, cv.source_path, cv.source_version, cv.imported_at
            from {table_sql}
            where {where}
            order by
              case
                when cv.clinical_significance in ('Pathogenic', 'Likely_pathogenic', 'Pathogenic/Likely_pathogenic')
                  or cv.clinical_significance glob '*Pathogenic*'
                  or cv.clinical_significance glob '*Likely_pathogenic*' then 0
                when cv.clinical_significance = 'Conflicting_classifications_of_pathogenicity' then 1
                when cv.clinical_significance = 'Uncertain_significance' then 2
                when cv.clinical_significance in ('association', 'risk_factor', 'drug_response') then 3
                when cv.clinical_significance is null then 4
                else 5
              end,
              case
                when cv.review_status = 'practice_guideline' then 0
                when cv.review_status = 'reviewed_by_expert_panel' then 1
                when cv.review_status = 'criteria_provided,_multiple_submitters,_no_conflicts' then 2
                when cv.review_status = 'criteria_provided,_single_submitter' then 3
                when cv.review_status = 'criteria_provided,_conflicting_classifications' then 4
                else 5
              end,
              cv.chrom, cv.pos, cv.ref, cv.alt
            limit ?
            """,
            (*params, limit),
        )
    ]
    return {
        "lookup_mode": lookup_mode,
        "total_records": total,
        "clinical_significance_counts": clinical_significance_counts,
        "review_status_counts": review_status_counts,
        "strict_pathogenic_or_likely_pathogenic_count": sum(
            count
            for significance, count in clinical_significance_counts
            if _has_strict_pathogenic_component(Counter({significance: count}))
        ),
        "compact_record_limit": limit,
        "compact_records": compact_records,
    }


def _sample_gene_matches(gene: str, matches_path: Path, *, limit: int) -> dict[str, Any]:
    if not matches_path.exists():
        raise FileNotFoundError(matches_path)

    total = 0
    clinical_significance: Counter[str] = Counter()
    review_status: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    with matches_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            gene_info = item.get("clinvar", {}).get("gene_info") or ""
            if gene not in _gene_symbols(gene_info):
                continue
            total += 1
            clinvar = item["clinvar"]
            clinical_significance[clinvar.get("clinical_significance") or "missing"] += 1
            review_status[clinvar.get("review_status") or "missing"] += 1
            if len(records) < limit:
                records.append(item)

    return {
        "matches_path": str(matches_path),
        "total_records": total,
        "clinical_significance_counts": clinical_significance.most_common(),
        "review_status_counts": review_status.most_common(),
        "record_limit": limit,
        "records": records,
    }


def _gene_query_parts(
    connection: sqlite3.Connection,
    gene: str,
    genome_build: str,
) -> tuple[str, str, tuple[str, ...], str]:
    indexed_links = int(connection.execute("select count(*) as records from clinvar_variant_genes").fetchone()["records"])
    if indexed_links:
        return (
            "clinvar_variant_genes cg join clinvar_variants cv on cv.rowid = cg.variant_rowid",
            "cg.gene_symbol = ? and cg.genome_build = ? and cv.genome_build = ?",
            (gene, genome_build, genome_build),
            "gene_index",
        )
    return (
        "clinvar_variants cv",
        """
        cv.genome_build = ?
        and cv.gene_info is not null
        and (cv.gene_info like ? or cv.gene_info like ?)
        """,
        (genome_build, f"{gene}:%", f"%|{gene}:%"),
        "gene_info_scan",
    )
