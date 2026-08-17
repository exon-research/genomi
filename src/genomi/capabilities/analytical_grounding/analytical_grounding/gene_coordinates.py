from __future__ import annotations

from pathlib import Path
from typing import Any

from .helpers import (
    _clean_chrom,
    _open_text,
    _parse_gtf_attributes,
    _safe_int,
)


JsonObject = dict[str, Any]

_CANONICAL_CHROMS = frozenset(
    [*(str(value) for value in range(1, 23)), "X", "Y", "MT"]
)


def resolve_gencode_gene_intervals(
    gencode_gtf: str | Path,
    genes: list[str],
    *,
    genome_build: str,
) -> JsonObject:
    """Resolve exact human gene symbols to canonical GENCODE gene intervals.

    The GTF is scanned once for the complete bounded candidate set. Alternative
    contigs are deliberately excluded, while distinct canonical intervals for
    the same symbol (for example pseudoautosomal copies) are preserved.
    """

    requested_genes = _normalized_gene_symbols(genes)
    requested_by_key = {gene.casefold(): gene for gene in requested_genes}
    intervals_by_gene: dict[str, list[JsonObject]] = {
        gene: [] for gene in requested_genes
    }
    seen: set[tuple[object, ...]] = set()

    with _open_text(Path(gencode_gtf)) as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 9:
                continue
            raw_chrom, source, feature_type, raw_start, raw_end, _, strand, _, attrs = (
                parts[:9]
            )
            if feature_type != "gene":
                continue
            attr_map = _parse_gtf_attributes(attrs)
            source_symbol = str(
                attr_map.get("gene_name") or attr_map.get("gene") or ""
            ).strip()
            requested_symbol = requested_by_key.get(source_symbol.casefold())
            if requested_symbol is None:
                continue
            chrom = _canonical_chrom(raw_chrom)
            start = _safe_int(raw_start)
            end = _safe_int(raw_end)
            if not chrom or start is None or end is None or start < 1 or end < start:
                continue
            gene_id = str(attr_map.get("gene_id") or "").strip()
            key = (requested_symbol, gene_id, chrom, start, end, strand)
            if key in seen:
                continue
            seen.add(key)
            interval_id = f"GENCODE:{gene_id or requested_symbol}:{chrom}:{start}-{end}"
            intervals_by_gene[requested_symbol].append(
                {
                    "interval_id": interval_id,
                    "gene": requested_symbol,
                    "gene_symbol": source_symbol,
                    "gene_id": gene_id,
                    "gene_type": str(attr_map.get("gene_type") or "").strip(),
                    "chrom": chrom,
                    "start": start,
                    "end": end,
                    "strand": strand,
                    "genome_build": genome_build,
                    "source": source or "GENCODE",
                }
            )

    intervals: list[JsonObject] = []
    resolved_genes: list[str] = []
    unresolved_genes: list[str] = []
    for gene in requested_genes:
        gene_intervals = sorted(
            intervals_by_gene[gene],
            key=lambda item: (
                _chrom_sort_key(str(item["chrom"])),
                int(item["start"]),
                int(item["end"]),
                str(item["gene_id"]),
            ),
        )
        if gene_intervals:
            resolved_genes.append(gene)
            intervals.extend(gene_intervals)
        else:
            unresolved_genes.append(gene)

    return {
        "requested_genes": requested_genes,
        "resolved_genes": resolved_genes,
        "unresolved_genes": unresolved_genes,
        "intervals": intervals,
    }


def _normalized_gene_symbols(genes: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in genes:
        gene = str(value or "").strip().upper()
        if not gene:
            continue
        key = gene.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(gene)
    return normalized


def _canonical_chrom(value: object) -> str:
    chrom = _clean_chrom(value)
    if chrom == "M":
        chrom = "MT"
    return chrom if chrom in _CANONICAL_CHROMS else ""


def _chrom_sort_key(chrom: str) -> tuple[int, str]:
    if chrom.isdigit():
        return int(chrom), ""
    return {"X": (23, ""), "Y": (24, ""), "MT": (25, "")}.get(
        chrom,
        (99, chrom),
    )
