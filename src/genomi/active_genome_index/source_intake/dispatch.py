from __future__ import annotations

from pathlib import Path

from ..active_genome_index import SCHEMA_VERSION
from .agi_store import SOURCE_PARSE_SCHEMA, JsonObject
from .arrays import (
    parse_23andme_source,
    parse_ancestrydna_source,
    parse_consumer_array_source,
)
from .detection import detect_source
from .sequencing import parse_bam_source, parse_fastq_source
from .vcf import _parse_vcf_active_genome_index


def parse_source(
    source: str | Path,
    *,
    evidence_db: str | Path | None = None,
    source_evidence_db: str | Path | None = None,
    shared_evidence_db: str | Path | None = None,
    reference_fasta: str | Path | None = None,
    auto_reference_fasta: bool = True,
    genome_build: str = "auto",
    force: bool = False,
    max_records: int | None = None,
    parallel_workers: int | None = None,
) -> JsonObject:
    source_path = Path(source)
    detection = detect_source(source_path)
    if detection.source_format in {"vcf", "gvcf"}:
        result = _parse_vcf_active_genome_index(
            source_path,
            detection=detection,
            evidence_db=evidence_db,
            source_evidence_db=source_evidence_db,
            shared_evidence_db=shared_evidence_db,
            genome_build=genome_build,
            force=force,
            max_records=max_records,
            parallel_workers=parallel_workers,
        )
        result["schema"] = SOURCE_PARSE_SCHEMA
        result["source_format"] = detection.source_format
        result["source_kind"] = detection.source_kind
        result["source"] = str(source_path)
        result["vcf"] = str(source_path)
        return result
    if detection.source_format == "bam":
        return parse_bam_source(
            source_path,
            detection=detection,
            evidence_db=evidence_db,
            source_evidence_db=source_evidence_db,
            shared_evidence_db=shared_evidence_db,
            reference_fasta=reference_fasta,
            auto_reference_fasta=auto_reference_fasta,
            genome_build=genome_build,
            force=force,
            max_records=max_records,
            parallel_workers=parallel_workers,
        )
    if detection.source_format == "23andme":
        return parse_23andme_source(
            source_path,
            detection=detection,
            evidence_db=evidence_db,
            source_evidence_db=source_evidence_db,
            shared_evidence_db=shared_evidence_db,
            genome_build=genome_build,
            force=force,
            max_records=max_records,
        )
    if detection.source_format == "ancestrydna":
        return parse_ancestrydna_source(
            source_path,
            detection=detection,
            evidence_db=evidence_db,
            source_evidence_db=source_evidence_db,
            shared_evidence_db=shared_evidence_db,
            genome_build=genome_build,
            force=force,
            max_records=max_records,
        )
    if detection.source_format in {"myheritage", "ftdna", "livingdna"}:
        return parse_consumer_array_source(
            source_path,
            detection=detection,
            evidence_db=evidence_db,
            source_evidence_db=source_evidence_db,
            shared_evidence_db=shared_evidence_db,
            genome_build=genome_build,
            force=force,
            max_records=max_records,
        )
    if detection.source_format == "fastq":
        return parse_fastq_source(
            source_path,
            detection=detection,
            evidence_db=evidence_db,
            source_evidence_db=source_evidence_db,
            shared_evidence_db=shared_evidence_db,
            reference_fasta=reference_fasta,
            auto_reference_fasta=auto_reference_fasta,
            genome_build=genome_build,
            force=force,
            max_records=max_records,
            parallel_workers=parallel_workers,
        )
    raise ValueError(f"unsupported source format: {detection.source_format}")
