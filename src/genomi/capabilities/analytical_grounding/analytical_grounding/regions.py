from __future__ import annotations

from pathlib import Path
from typing import Any

from .helpers import (
    _ccre_class,
    _clean_chrom,
    _clean_text,
    _open_text,
    _overlap_bp,
    _parse_gtf_attributes,
    _safe_int,
    _same_chrom,
)


def _read_gencode_gtf(path: Path, chrom: str, start: int, end: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    features: list[dict[str, Any]] = []
    tss_records: list[dict[str, Any]] = []
    with _open_text(path) as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 9:
                continue
            rec_chrom, source, feature_type, raw_start, raw_end, _, strand, _, attrs = parts[:9]
            if not _same_chrom(rec_chrom, chrom):
                continue
            rec_start = _safe_int(raw_start)
            rec_end = _safe_int(raw_end)
            if rec_start is None or rec_end is None:
                continue
            attr_map = _parse_gtf_attributes(attrs)
            gene_symbol = attr_map.get("gene_name") or attr_map.get("gene") or ""
            feature_id = attr_map.get("transcript_id") or attr_map.get("gene_id") or attr_map.get("exon_id") or f"{rec_chrom}:{rec_start}-{rec_end}"
            if feature_type == "gene":
                tss_records.append(
                    {
                        "feature_id": feature_id,
                        "gene_symbol": gene_symbol,
                        "tss": rec_start if strand != "-" else rec_end,
                        "source": source or "GENCODE",
                    }
                )
            overlap = _overlap_bp(start, end, rec_start, rec_end)
            if overlap <= 0:
                continue
            features.append(
                {
                    "feature_type": feature_type,
                    "feature_id": feature_id,
                    "gene_symbol": gene_symbol,
                    "overlap_bp": overlap,
                    "source": "GENCODE",
                    "source_detail": source,
                    "chrom": _clean_chrom(rec_chrom),
                    "start": rec_start,
                    "end": rec_end,
                    "strand": strand,
                    "attributes": {
                        key: value
                        for key, value in attr_map.items()
                        if key in {"gene_id", "gene_name", "gene_type", "transcript_id", "transcript_type"}
                    },
                }
            )
    return features, tss_records


def _read_encode_ccre_bed(path: Path, chrom: str, start: int, end: int) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    with _open_text(path) as handle:
        for line in handle:
            if not line.strip() or line.startswith(("#", "track ", "browser ")):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3 or not _same_chrom(parts[0], chrom):
                continue
            bed_start = _safe_int(parts[1])
            bed_end = _safe_int(parts[2])
            if bed_start is None or bed_end is None:
                continue
            rec_start = bed_start + 1
            rec_end = bed_end
            overlap = _overlap_bp(start, end, rec_start, rec_end)
            if overlap <= 0:
                continue
            feature_id = _clean_text(parts[3]) if len(parts) > 3 else f"{parts[0]}:{rec_start}-{rec_end}"
            ccre_class = _ccre_class(parts)
            features.append(
                {
                    "feature_type": ccre_class,
                    "feature_id": feature_id,
                    "overlap_bp": overlap,
                    "source": "ENCODE cCRE",
                    "chrom": _clean_chrom(parts[0]),
                    "start": rec_start,
                    "end": rec_end,
                }
            )
    return features
