"""Genome-build resolution utilities.

ClinVar/reference-FASTA materialization, freshness tracking, and the FASTA
gunzip+faidx transform now live in the central library manager
(``genomi.runtime.libraries``); only build inference/normalization remains here.
"""

from __future__ import annotations

from pathlib import Path

from ..active_genome_index.vcf import read_header


def resolve_genome_build(vcf: str | Path, requested: str | None) -> str:
    requested_normalized = (requested or "auto").strip()
    if requested_normalized.lower() not in {"", "auto"}:
        return _normalize_genome_build(requested_normalized)
    return infer_genome_build_from_vcf(vcf) or "GRCh38"


def infer_genome_build_from_vcf(vcf: str | Path) -> str | None:
    try:
        header = read_header(vcf)
    except Exception:
        return None
    text = " ".join(
        value or ""
        for value in [
            header.first_meta_value("reference"),
            header.first_meta_value("referenceInfo"),
            header.first_meta_value("assembly"),
        ]
    ).lower()
    if any(token in text for token in ["grch37", "hg19", "g1k.37", "b37"]):
        return "GRCh37"
    if any(token in text for token in ["grch38", "hg38", "grch38.p", "b38"]):
        return "GRCh38"
    contigs = header.contigs()
    if contigs and any(contig.startswith("chr") for contig in contigs[:24]):
        return "GRCh38"
    return None


def _normalize_genome_build(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"grch37", "hg19", "37"}:
        return "GRCh37"
    if normalized in {"grch38", "hg38", "38"}:
        return "GRCh38"
    raise ValueError(f"unsupported genome build for static dependencies: {value}")
