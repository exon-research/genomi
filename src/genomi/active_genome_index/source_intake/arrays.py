from __future__ import annotations

import csv
import sqlite3
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from ...runtime.paths import (
    run_evidence_db_path_for_source,
    run_evidence_dir_for_source,
    run_output_path_for_source,
    run_project_dir_for_source,
    run_reference_dir_for_source,
    run_work_dir_for_source,
    sample_slug_from_source,
    shared_evidence_db_path,
)
from ..array_genotypes import ARRAY_NO_CALLS, SUPPORTED_ARRAY_BASES
from ..active_genome_index import SCHEMA_VERSION, _chrom_sort
from ..active_genome_index import connect as connect_active_genome_index
from .agi_store import (
    SOURCE_PARSE_SCHEMA,
    JsonObject,
    _array_record_row,
    _cached_array_active_genome_index_if_usable,
    _create_source_query_indexes,
    _init_source_evidence_db,
    _insert_source_active_genome_index_metadata,
    _insert_source_record_batch,
    _insert_source_stat_rows,
    _mark_source_active_genome_index_completed,
    _reset_source_active_genome_index_schema,
)
from .detection import (
    SourceDetection,
    detect_source,
)
from .text_io import _clean_array_chrom, _effective_array_build, _open_text_source


def _array_record_stats(*, total: int, called: int, no_call: int, rsid_count: int) -> JsonObject:
    return {
        "total_records": total,
        "variant_records": 0,
        "reference_records": 0,
        "pass_records": called,
        "fail_records": no_call,
        "no_call_records": no_call,
        "array_call_records": called,
        "array_no_call_records": no_call,
        "rsid_records": rsid_count,
    }


def _iter_23andme_rows(handle: TextIO) -> Iterator[JsonObject]:
    for line in handle:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        columns = text.split("\t")
        if columns[:4] == ["rsid", "chromosome", "position", "genotype"]:
            continue
        if len(columns) < 4:
            continue
        rsid, chrom, pos_text, genotype = columns[:4]
        try:
            pos = int(pos_text)
        except ValueError:
            continue
        yield {
            "rsid": rsid.strip(),
            "chrom": _clean_array_chrom(chrom),
            "pos": pos,
            "genotype": genotype.strip().upper(),
        }


def _iter_ancestrydna_rows(handle: TextIO) -> Iterator[JsonObject]:
    for line in handle:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        columns = text.split("\t")
        if columns[:5] == ["rsid", "chromosome", "position", "allele1", "allele2"]:
            continue
        if len(columns) < 5:
            continue
        rsid, chrom, pos_text, allele1, allele2 = columns[:5]
        try:
            pos = int(pos_text)
        except ValueError:
            continue
        genotype = f"{allele1.strip()}{allele2.strip()}".upper()
        yield {
            "rsid": rsid.strip(),
            "chrom": _clean_array_chrom(chrom),
            "pos": pos,
            "genotype": genotype,
        }


# ---------------------------------------------------------------------------
# Consumer-array parsers.
#
# These providers share one observation model: one row per assayed SNP with a
# plus-strand observed genotype. Provider-specific row readers handle delimiter
# and banner differences; AGI storage and downstream contracts stay shared.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ConsumerArraySpec:
    row_iterator: Callable[[TextIO], Iterator[JsonObject]]


def _iter_myheritage_rows(handle: TextIO) -> Iterator[JsonObject]:
    reader = csv.reader(handle)
    for columns in reader:
        if not columns or not columns[0]:
            continue
        if columns[0].startswith("#"):
            continue
        if columns[:4] == ["RSID", "CHROMOSOME", "POSITION", "RESULT"]:
            continue
        if len(columns) < 4:
            continue
        rsid, chrom, pos_text, genotype = (value.strip() for value in columns[:4])
        try:
            pos = int(pos_text)
        except ValueError:
            continue
        yield {
            "rsid": rsid,
            "chrom": _clean_array_chrom(chrom),
            "pos": pos,
            "genotype": genotype.upper(),
        }


def _iter_livingdna_rows(handle: TextIO) -> Iterator[JsonObject]:
    for line in handle:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        columns = text.split("\t")
        if columns[:4] == ["rsid", "chromosome", "position", "genotype"]:
            continue
        if len(columns) < 4:
            continue
        rsid, chrom, pos_text, genotype = (value.strip() for value in columns[:4])
        try:
            pos = int(pos_text)
        except ValueError:
            continue
        yield {
            "rsid": rsid,
            "chrom": _clean_array_chrom(chrom),
            "pos": pos,
            "genotype": genotype.upper(),
        }


_CONSUMER_ARRAY_SPECS: dict[str, _ConsumerArraySpec] = {
    "23andme": _ConsumerArraySpec(
        row_iterator=_iter_23andme_rows,
    ),
    "ancestrydna": _ConsumerArraySpec(
        row_iterator=_iter_ancestrydna_rows,
    ),
    "myheritage": _ConsumerArraySpec(
        row_iterator=_iter_myheritage_rows,
    ),
    "ftdna": _ConsumerArraySpec(
        row_iterator=_iter_myheritage_rows,  # identical CSV shape, no comment block
    ),
    "livingdna": _ConsumerArraySpec(
        row_iterator=_iter_livingdna_rows,
    ),
}

SUPPORTED_CONSUMER_ARRAY_FORMATS = frozenset(_CONSUMER_ARRAY_SPECS)


def parse_consumer_array_source(
    source: str | Path,
    *,
    detection: SourceDetection | None = None,
    evidence_db: str | Path | None = None,
    source_evidence_db: str | Path | None = None,
    shared_evidence_db: str | Path | None = None,
    genome_build: str = "auto",
    force: bool = False,
    max_records: int | None = None,
) -> JsonObject:
    source_path = Path(source)
    detection = detection or detect_source(source_path)
    spec = _CONSUMER_ARRAY_SPECS.get(detection.source_format)
    if spec is None:
        raise ValueError(f"no consumer-array spec for source_format: {detection.source_format}")
    fmt = detection.source_format
    effective_build = _effective_array_build(genome_build, detection.reference_build)
    project_dir = run_project_dir_for_source(source_path, source_format=fmt)
    work_dir = run_work_dir_for_source(source_path, source_format=fmt)
    evidence_dir = run_evidence_dir_for_source(source_path, source_format=fmt)
    reference_dir = run_reference_dir_for_source(source_path, source_format=fmt)
    db_path = Path(evidence_db) if evidence_db is not None else run_evidence_db_path_for_source(source_path, source_format=fmt)
    shared_db = Path(shared_evidence_db) if shared_evidence_db is not None else shared_evidence_db_path()
    agi_path = run_output_path_for_source(source_path, "active-genome-index.sqlite", source_format=fmt)
    project_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)

    _init_source_evidence_db(
        db_path,
        source_path,
        source_format=fmt,
        source_evidence_db=source_evidence_db,
        shared_evidence_db=shared_db,
    )
    agi_result = _build_consumer_array_active_genome_index(
        source_path,
        agi_path,
        source_format=fmt,
        spec=spec,
        detection=detection,
        genome_build=effective_build,
        force=force,
        max_records=max_records,
    )
    steps: list[JsonObject] = [
        {
            "name": "build-active-genome-index",
            "result": agi_result,
            "reason": "The consumer genotype-array source is digitized into an Active Genome Index.",
        }
    ]
    return {
        "schema": SOURCE_PARSE_SCHEMA,
        "workflow_area": "active-genome-index",
        "status": "completed",
        "source": str(source_path),
        "source_format": fmt,
        "source_kind": "consumer_genotype_array",
        "source_member": detection.member_name,
        "provider": detection.provider or fmt,
        "sample_slug": sample_slug_from_source(source_path, source_format=fmt),
        "genome_build": effective_build,
        "evidence_db": str(db_path),
        "shared_evidence_db": str(shared_db),
        "project_dir": str(project_dir),
        "work_dir": str(work_dir),
        "evidence_dir": str(evidence_dir),
        "reference_dir": str(reference_dir),
        "outputs": {"agi_path": str(agi_path)},
        "steps": steps,
    }


def _build_consumer_array_active_genome_index(
    source_path: Path,
    agi_path: Path,
    *,
    source_format: str,
    spec: _ConsumerArraySpec,
    detection: SourceDetection,
    genome_build: str,
    force: bool,
    max_records: int | None,
) -> JsonObject:
    if agi_path.exists() and not force:
        cached = _cached_array_active_genome_index_if_usable(
            source_path,
            agi_path,
            detection=detection,
            source_format=source_format,
            genome_build=genome_build,
            max_records=max_records,
        )
        if cached is not None:
            return cached
    agi_path.parent.mkdir(parents=True, exist_ok=True)
    with connect_active_genome_index(agi_path) as connection:
        _reset_source_active_genome_index_schema(connection)
        _insert_source_active_genome_index_metadata(connection, source_path, detection=detection, genome_build=genome_build, max_records=max_records)
        stats, chromosome_counts = _populate_consumer_array_records(
            connection,
            source_path,
            source_format=source_format,
            spec=spec,
            detection=detection,
            max_records=max_records,
        )
        _create_source_query_indexes(connection)
        _insert_source_stat_rows(connection, stats)
        _mark_source_active_genome_index_completed(connection)
        connection.commit()
    return {
        "status": "completed",
        "source": str(source_path),
        "source_format": source_format,
        "agi_path": str(agi_path),
        "schema_version": SCHEMA_VERSION,
        "genome_build": genome_build,
        "stats": stats,
        "chromosome_counts": dict(sorted(chromosome_counts.items(), key=lambda item: (_chrom_sort(item[0]), item[0]))),
    }


def _populate_consumer_array_records(
    connection: sqlite3.Connection,
    source_path: Path,
    *,
    source_format: str,
    spec: _ConsumerArraySpec,
    detection: SourceDetection,
    max_records: int | None,
) -> tuple[JsonObject, Counter[str]]:
    total = 0
    called = 0
    no_call = 0
    rsid_count = 0
    batch: list[tuple[Any, ...]] = []
    chrom_counts: Counter[str] = Counter()
    with _open_text_source(source_path, member_name=detection.member_name) as handle:
        for row_index, row in enumerate(spec.row_iterator(handle), start=1):
            if max_records is not None and total >= max_records:
                break
            total += 1
            genotype = row["genotype"]
            chrom = row["chrom"]
            chrom_counts[chrom] += 1
            if row["rsid"].lower().startswith("rs"):
                rsid_count += 1
            normalized_genotype = str(genotype or "").strip().upper()
            is_called = (
                normalized_genotype not in ARRAY_NO_CALLS
                and "0" not in normalized_genotype
                and "-" not in normalized_genotype
                and all(base in SUPPORTED_ARRAY_BASES for base in normalized_genotype)
            )
            if is_called:
                called += 1
            else:
                no_call += 1
            batch.append(
                _array_record_row(
                    row,
                    row_index=row_index,
                    is_called=is_called,
                    sample_name=detection.provider or source_format,
                    source_format=source_format,
                )
            )
            if len(batch) >= 50_000:
                _insert_source_record_batch(connection, batch)
                connection.commit()
                batch.clear()
    if batch:
        _insert_source_record_batch(connection, batch)
    return (
        _array_record_stats(total=total, called=called, no_call=no_call, rsid_count=rsid_count),
        chrom_counts,
    )
