from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ....active_genome_index.active_genome_index import (
    default_active_genome_index_path,
    read_header_from_active_genome_index,
)
from ....active_genome_index.active_genome_index import (
    connect_existing as connect_active_genome_index_existing,
)
from ._common import JsonObject, _size


def _input_preflight(vcf_path: Path, *, scan_records: int = 100) -> JsonObject:
    # Self-sufficient: read the header and a record sample from the structured
    # Active Genome Index alone — never the intake or the canonical bgzip.
    active_genome_index_path = default_active_genome_index_path(vcf_path)
    if not Path(active_genome_index_path).exists():
        return {
            "schema": "genomi-pharmcat-input-preflight-v1",
            "status": "requires_active_genome_index",
            "input": {"hidden_intake_source": True, "size_bytes": _size(vcf_path)},
            "warnings": [
                "No Active Genome Index for this intake source; run genomi.parse_source first so PharmCAT preflight can read the Active Genome Index.",
            ],
        }
    stats: dict[str, int] = {
        "records_scanned": 0,
        "records_with_gt": 0,
        "records_with_dp": 0,
        "records_with_gq": 0,
        "pass_records": 0,
        "non_pass_filter_records": 0,
        "variant_records": 0,
        "indel_records": 0,
        "symbolic_alt_records": 0,
        "chr_prefixed_record_chroms": 0,
        "bare_record_chroms": 0,
    }
    format_keys: set[str] = set()
    filters: dict[str, int] = {}
    header = None
    try:
        with connect_active_genome_index_existing(active_genome_index_path) as connection:
            header = read_header_from_active_genome_index(connection)
            rows = connection.execute(
                """
                select chrom, ref, alt, filter, is_variant, format, genotype, depth, genotype_quality
                from records
                order by chrom_sort, pos, offset, sample_index
                limit ?
                """,
                (scan_records,),
            ).fetchall()
        for row in rows:
            chrom = str(row["chrom"])
            filt = str(row["filter"])
            alts = [a for a in str(row["alt"] or "").split(",") if a not in ("", ".")]
            stats["records_scanned"] += 1
            stats["variant_records"] += int(bool(row["is_variant"]))
            stats["pass_records"] += int(filt.upper() == "PASS")
            stats["non_pass_filter_records"] += int(filt.upper() not in {"PASS", "."})
            stats["chr_prefixed_record_chroms"] += int(chrom.lower().startswith("chr"))
            stats["bare_record_chroms"] += int(not chrom.lower().startswith("chr"))
            stats["symbolic_alt_records"] += int(any(_is_symbolic_alt(alt) for alt in alts))
            stats["indel_records"] += int(_is_indel_record(str(row["ref"]), alts))
            filters[filt or "."] = filters.get(filt or ".", 0) + 1
            for key in str(row["format"]).split(":") if row["format"] else []:
                if key:
                    format_keys.add(key)
            stats["records_with_gt"] += int(bool(row["genotype"]))
            stats["records_with_dp"] += int(row["depth"] is not None)
            stats["records_with_gq"] += int(row["genotype_quality"] is not None)
    except (OSError, ValueError, sqlite3.Error) as exc:
        return {
            "schema": "genomi-pharmcat-input-preflight-v1",
            "status": "header_unavailable" if header is None else "scan_unavailable",
            "input": {"hidden_intake_source": True, "size_bytes": _size(vcf_path)},
            "header": _header_preflight(header) if header is not None else None,
            "warnings": [str(exc)],
        }

    warnings = []
    if not header.samples:
        warnings.append("VCF has no sample columns; PharmCAT sample calling needs genotype columns.")
    if stats["records_scanned"] and not stats["records_with_gt"]:
        warnings.append("Scanned records did not include GT sample fields.")
    if header.first_meta_value("reference") is None and header.first_meta_value("referenceInfo") is None:
        warnings.append("VCF header is missing reference assembly metadata.")
    if stats["non_pass_filter_records"]:
        warnings.append("Scanned records include non-PASS filters; review QUAL and FILTER fields separately for sample quality context.")
    if _chrom_style_from_header_or_records(header, stats) != "chr_prefixed":
        warnings.append('PharmCAT expects CHROM values in "chr##" format; use the PharmCAT preprocessor when needed.')
    if stats["indel_records"] or stats["symbolic_alt_records"]:
        warnings.append("Scanned records include indels or symbolic ALT records; confirm PharmCAT normalization requirements before synthesis.")
    requirement_checks = _pharmcat_requirement_checks(header, stats)
    return {
        "schema": "genomi-pharmcat-input-preflight-v1",
        "status": "completed",
        "input": {
            "hidden_intake_source": True,
            "size_bytes": _size(vcf_path),
            "suffix": _vcf_suffix(vcf_path),
            "compressed": any(str(vcf_path).lower().endswith(suffix) for suffix in (".gz", ".bgz")),
        },
        "header": _header_preflight(header),
        "scan_record_limit": scan_records,
        "scan_summary": stats,
        "format_keys_observed": sorted(format_keys),
        "filters_observed": filters,
        "pharmcat_requirement_checks": requirement_checks,
        "warnings": warnings,
        "semantics": [
            "Preflight summarizes local VCF structure without exposing the raw intake path.",
            "PharmCAT coverage sufficiency is judged from execution artifacts; inspect missing PGx positions after execution.",
            "PharmCAT expects GRCh38, GT sample fields, required PGx positions, normalized representation, and chr-prefixed chromosome names.",
        ],
    }


def _pharmcat_requirement_checks(header: Any, stats: dict[str, int]) -> list[JsonObject]:
    reference_text = " ".join(
        value
        for value in [
            header.first_meta_value("reference"),
            header.first_meta_value("referenceInfo"),
        ]
        if value
    ).lower()
    sample_count = len(header.samples)
    chrom_style = _chrom_style_from_header_or_records(header, stats)
    return [
        {
            "id": "grch38_assembly",
            "status": "ready" if any(token in reference_text for token in ("grch38", "hg38", "b38")) else "needs_grch38_confirmation",
            "evidence": {
                "reference": header.first_meta_value("reference"),
                "referenceInfo": header.first_meta_value("referenceInfo"),
            },
            "source_url": "https://pharmcat.clinpgx.org/using/VCF-Requirements/",
        },
        {
            "id": "required_columns_and_gt",
            "status": "ready" if sample_count and stats["records_with_gt"] else "needs_sample_gt_fields",
            "evidence": {
                "sample_count": sample_count,
                "records_with_gt": stats["records_with_gt"],
            },
            "source_url": "https://pharmcat.clinpgx.org/using/VCF-Requirements/",
        },
        {
            "id": "required_pgx_positions",
            "status": "requires_missing_pgx_position_review",
            "evidence": {"records_scanned": stats["records_scanned"]},
            "next_evidence": "Inspect pharmacogenomics.run_pharmcat artifacts.missing_pgx_positions after execution.",
            "source_url": "https://pharmcat.clinpgx.org/using/VCF-Requirements/",
        },
        {
            "id": "variant_representation",
            "status": "requires_normalization_review" if stats["indel_records"] or stats["symbolic_alt_records"] else "ready_for_scanned_records",
            "evidence": {
                "indel_records": stats["indel_records"],
                "symbolic_alt_records": stats["symbolic_alt_records"],
            },
            "source_url": "https://pharmcat.clinpgx.org/using/VCF-Requirements/",
        },
        {
            "id": "chromosome_prefix",
            "status": "ready" if chrom_style == "chr_prefixed" else "needs_chr_prefixed_chromosomes",
            "evidence": {"chrom_style": chrom_style},
            "source_url": "https://pharmcat.clinpgx.org/using/VCF-Requirements/",
        },
        {
            "id": "quality_filter_review",
            "status": "ready" if not stats["non_pass_filter_records"] else "review_filtered_records",
            "evidence": {"non_pass_filter_records": stats["non_pass_filter_records"]},
            "source_url": "https://pharmcat.clinpgx.org/using/VCF-Requirements/",
        },
    ]


def _chrom_style_from_header_or_records(header: Any, stats: dict[str, int]) -> str:
    header_style = _contig_style(header.contigs())
    if header_style != "unknown":
        return header_style
    prefixed = stats.get("chr_prefixed_record_chroms", 0)
    bare = stats.get("bare_record_chroms", 0)
    if prefixed and not bare:
        return "chr_prefixed"
    if bare and not prefixed:
        return "bare"
    if bare and prefixed:
        return "mixed"
    return "unknown"


def _is_indel_record(ref: str, alts: list[str]) -> bool:
    return any(not _is_symbolic_alt(alt) and (len(ref) != 1 or len(alt) != 1) for alt in alts)


def _is_symbolic_alt(alt: str) -> bool:
    return alt.startswith("<") or alt in {"*", "."}


def _header_preflight(header: Any) -> JsonObject:
    contigs = header.contigs()
    return {
        "fileformat": header.first_meta_value("fileformat"),
        "reference": header.first_meta_value("reference"),
        "referenceInfo": header.first_meta_value("referenceInfo"),
        "sample_count": len(header.samples),
        "samples": header.samples[:10],
        "contig_count": len(contigs),
        "contigs": contigs[:10],
        "contig_style": _contig_style(contigs),
    }


def _contig_style(contigs: list[str]) -> str:
    if not contigs:
        return "unknown"
    chr_prefixed = sum(1 for contig in contigs if contig.lower().startswith("chr"))
    if chr_prefixed == len(contigs):
        return "chr_prefixed"
    if chr_prefixed == 0:
        return "bare"
    return "mixed"


def _vcf_suffix(path: Path) -> str:
    name = path.name.lower()
    for suffix in (".g.vcf.gz", ".gvcf.gz", ".vcf.gz", ".vcf.bgz", ".g.vcf", ".gvcf", ".vcf"):
        if name.endswith(suffix):
            return suffix
    return path.suffix
