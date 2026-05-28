from __future__ import annotations

import csv
import sqlite3
from collections import Counter
from collections.abc import Iterator
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
    _reset_source_active_genome_index_schema,
)
from .detection import (
    SourceDetection,
    _detect_23andme,
    _detect_ancestrydna,
    detect_source,
)
from .text_io import _clean_array_chrom, _effective_array_build, _open_text_source


def parse_23andme_source(
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
    detection = detection or _detect_23andme(source_path)
    effective_build = _effective_array_build(genome_build, detection.reference_build)
    project_dir = run_project_dir_for_source(source_path, source_format="23andme")
    work_dir = run_work_dir_for_source(source_path, source_format="23andme")
    evidence_dir = run_evidence_dir_for_source(source_path, source_format="23andme")
    reference_dir = run_reference_dir_for_source(source_path, source_format="23andme")
    db_path = Path(evidence_db) if evidence_db is not None else run_evidence_db_path_for_source(source_path, source_format="23andme")
    shared_db = Path(shared_evidence_db) if shared_evidence_db is not None else shared_evidence_db_path()
    active_genome_index_path = run_output_path_for_source(source_path, "active-genome-index.sqlite", source_format="23andme")
    project_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)

    _init_source_evidence_db(
        db_path,
        source_path,
        source_format="23andme",
        source_evidence_db=source_evidence_db,
        shared_evidence_db=shared_db,
    )
    active_genome_index_result = build_23andme_active_genome_index(
        source_path,
        active_genome_index_path,
        detection=detection,
        genome_build=effective_build,
        force=force,
        max_records=max_records,
    )

    steps: list[JsonObject] = [
        {
            "name": "build-active-genome-index",
            "result": active_genome_index_result,
            "reason": "The 23andMe raw genotype export is digitized into an Active Genome Index.",
        }
    ]

    return {
        "schema": SOURCE_PARSE_SCHEMA,
        "workflow_area": "active-genome-index",
        "status": "completed",
        "source": str(source_path),
        "source_format": "23andme",
        "source_kind": "consumer_genotype_array",
        "source_member": detection.member_name,
        "sample_slug": sample_slug_from_source(source_path, source_format="23andme"),
        "genome_build": effective_build,
        "evidence_db": str(db_path),
        "shared_evidence_db": str(shared_db),
        "project_dir": str(project_dir),
        "work_dir": str(work_dir),
        "evidence_dir": str(evidence_dir),
        "reference_dir": str(reference_dir),
        "outputs": {
            "active_genome_index_path": str(active_genome_index_path),
        },
        "steps": steps,
        "semantics": [
            "23andMe raw genotype data is a SNP-array observation source.",
            "Coordinates are GRCh37 unless the source declares otherwise.",
            "Available sample evidence is plus-strand observed genotype by rsID/locus; sequencing depth, genotype quality, phasing, and reference-block callability require sequencing-derived sources.",
            "Use rsID/locus presence as sample context; use public evidence tools for interpretation.",
            "Public evidence libraries are materialized lazily by focused tools after Active Genome Index creation.",
        ],
    }


def build_23andme_active_genome_index(
    source: str | Path,
    active_genome_index_path: str | Path,
    *,
    detection: SourceDetection | None = None,
    genome_build: str = "GRCh37",
    force: bool = False,
    max_records: int | None = None,
) -> JsonObject:
    source_path = Path(source)
    active_genome_index_file = Path(active_genome_index_path)
    detection = detection or _detect_23andme(source_path)
    if active_genome_index_file.exists() and not force:
        cached = _cached_array_active_genome_index_if_usable(
            source_path,
            active_genome_index_file,
            detection=detection,
            source_format="23andme",
            genome_build=genome_build,
            max_records=max_records,
        )
        if cached is not None:
            return cached
    active_genome_index_file.parent.mkdir(parents=True, exist_ok=True)
    with connect_active_genome_index(active_genome_index_file) as connection:
        _reset_source_active_genome_index_schema(connection)
        _insert_source_active_genome_index_metadata(connection, source_path, detection=detection, genome_build=genome_build, max_records=max_records)
        stats, chromosome_counts = _populate_23andme_records(
            connection,
            source_path,
            detection=detection,
            max_records=max_records,
        )
        _create_source_query_indexes(connection)
        _insert_source_stat_rows(connection, stats)
        connection.commit()
    return {
        "status": "completed",
        "source": str(source_path),
        "source_format": "23andme",
        "active_genome_index_path": str(active_genome_index_file),
        "schema_version": SCHEMA_VERSION,
        "genome_build": genome_build,
        "stats": stats,
        "chromosome_counts": dict(sorted(chromosome_counts.items(), key=lambda item: (_chrom_sort(item[0]), item[0]))),
    }


def _populate_23andme_records(
    connection: sqlite3.Connection,
    source_path: Path,
    *,
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
        for row_index, row in enumerate(_iter_23andme_rows(handle), start=1):
            if max_records is not None and total >= max_records:
                break
            total += 1
            genotype = row["genotype"]
            chrom = row["chrom"]
            chrom_counts[chrom] += 1
            if row["rsid"].lower().startswith("rs"):
                rsid_count += 1
            is_called = genotype not in {"", "--", "00", "NN"}
            if is_called:
                called += 1
            else:
                no_call += 1
            batch.append(
                _array_record_row(
                    row,
                    row_index=row_index,
                    is_called=is_called,
                    sample_name="23andMe",
                    source_format="23andme",
                )
            )
            if len(batch) >= 50_000:
                _insert_source_record_batch(connection, batch)
                connection.commit()
                batch.clear()
    if batch:
        _insert_source_record_batch(connection, batch)
    return (
        {
            "total_records": total,
            "variant_records": called,
            "reference_records": no_call,
            "pass_records": called,
            "fail_records": no_call,
            "rsid_records": rsid_count,
        },
        chrom_counts,
    )


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


def parse_ancestrydna_source(
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
    detection = detection or _detect_ancestrydna(source_path)
    effective_build = _effective_array_build(genome_build, detection.reference_build)
    project_dir = run_project_dir_for_source(source_path, source_format="ancestrydna")
    work_dir = run_work_dir_for_source(source_path, source_format="ancestrydna")
    evidence_dir = run_evidence_dir_for_source(source_path, source_format="ancestrydna")
    reference_dir = run_reference_dir_for_source(source_path, source_format="ancestrydna")
    db_path = Path(evidence_db) if evidence_db is not None else run_evidence_db_path_for_source(source_path, source_format="ancestrydna")
    shared_db = Path(shared_evidence_db) if shared_evidence_db is not None else shared_evidence_db_path()
    active_genome_index_path = run_output_path_for_source(source_path, "active-genome-index.sqlite", source_format="ancestrydna")
    project_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)

    _init_source_evidence_db(
        db_path,
        source_path,
        source_format="ancestrydna",
        source_evidence_db=source_evidence_db,
        shared_evidence_db=shared_db,
    )
    active_genome_index_result = build_ancestrydna_active_genome_index(
        source_path,
        active_genome_index_path,
        detection=detection,
        genome_build=effective_build,
        force=force,
        max_records=max_records,
    )

    steps: list[JsonObject] = [
        {
            "name": "build-active-genome-index",
            "result": active_genome_index_result,
            "reason": "The AncestryDNA raw genotype export is digitized into an Active Genome Index.",
        }
    ]

    return {
        "schema": SOURCE_PARSE_SCHEMA,
        "workflow_area": "active-genome-index",
        "status": "completed",
        "source": str(source_path),
        "source_format": "ancestrydna",
        "source_kind": "consumer_genotype_array",
        "source_member": detection.member_name,
        "sample_slug": sample_slug_from_source(source_path, source_format="ancestrydna"),
        "genome_build": effective_build,
        "evidence_db": str(db_path),
        "shared_evidence_db": str(shared_db),
        "project_dir": str(project_dir),
        "work_dir": str(work_dir),
        "evidence_dir": str(evidence_dir),
        "reference_dir": str(reference_dir),
        "outputs": {
            "active_genome_index_path": str(active_genome_index_path),
        },
        "steps": steps,
        "semantics": [
            "AncestryDNA raw genotype data is a SNP-array observation source.",
            "Coordinates are GRCh37 unless the source declares otherwise.",
            "Available sample evidence is plus-strand observed genotype by rsID/locus; sequencing depth, genotype quality, phasing, and reference-block callability require sequencing-derived sources.",
            "Use rsID/locus presence as sample context; use public evidence tools for interpretation.",
            "Public evidence libraries are materialized lazily by focused tools after Active Genome Index creation.",
        ],
    }


def build_ancestrydna_active_genome_index(
    source: str | Path,
    active_genome_index_path: str | Path,
    *,
    detection: SourceDetection | None = None,
    genome_build: str = "GRCh37",
    force: bool = False,
    max_records: int | None = None,
) -> JsonObject:
    source_path = Path(source)
    active_genome_index_file = Path(active_genome_index_path)
    detection = detection or _detect_ancestrydna(source_path)
    if active_genome_index_file.exists() and not force:
        cached = _cached_array_active_genome_index_if_usable(
            source_path,
            active_genome_index_file,
            detection=detection,
            source_format="ancestrydna",
            genome_build=genome_build,
            max_records=max_records,
        )
        if cached is not None:
            return cached
    active_genome_index_file.parent.mkdir(parents=True, exist_ok=True)
    with connect_active_genome_index(active_genome_index_file) as connection:
        _reset_source_active_genome_index_schema(connection)
        _insert_source_active_genome_index_metadata(connection, source_path, detection=detection, genome_build=genome_build, max_records=max_records)
        stats, chromosome_counts = _populate_ancestrydna_records(
            connection,
            source_path,
            detection=detection,
            max_records=max_records,
        )
        _create_source_query_indexes(connection)
        _insert_source_stat_rows(connection, stats)
        connection.commit()
    return {
        "status": "completed",
        "source": str(source_path),
        "source_format": "ancestrydna",
        "active_genome_index_path": str(active_genome_index_file),
        "schema_version": SCHEMA_VERSION,
        "genome_build": genome_build,
        "stats": stats,
        "chromosome_counts": dict(sorted(chromosome_counts.items(), key=lambda item: (_chrom_sort(item[0]), item[0]))),
    }


def _populate_ancestrydna_records(
    connection: sqlite3.Connection,
    source_path: Path,
    *,
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
        for row_index, row in enumerate(_iter_ancestrydna_rows(handle), start=1):
            if max_records is not None and total >= max_records:
                break
            total += 1
            genotype = row["genotype"]
            chrom = row["chrom"]
            chrom_counts[chrom] += 1
            if row["rsid"].lower().startswith("rs"):
                rsid_count += 1
            is_called = genotype not in {"", "--", "00", "NN"} and "0" not in genotype and "-" not in genotype
            if is_called:
                called += 1
            else:
                no_call += 1
            batch.append(
                _array_record_row(
                    row,
                    row_index=row_index,
                    is_called=is_called,
                    sample_name="AncestryDNA",
                    source_format="ancestrydna",
                )
            )
            if len(batch) >= 50_000:
                _insert_source_record_batch(connection, batch)
                connection.commit()
                batch.clear()
    if batch:
        _insert_source_record_batch(connection, batch)
    return (
        {
            "total_records": total,
            "variant_records": called,
            "reference_records": no_call,
            "pass_records": called,
            "fail_records": no_call,
            "rsid_records": rsid_count,
        },
        chrom_counts,
    )


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
# MyHeritage / FamilyTreeDNA / Living DNA consumer-array parsers.
#
# These three providers ship raw genotype exports that share the same logical
# shape as the 23andMe and AncestryDNA exports — one row per assayed SNP with
# a plus-strand genotype on GRCh37 coordinates — but use distinct delimiters,
# quoting, and comment conventions. We dispatch to a single
# `parse_consumer_array_source` entry point keyed on the detected
# source_format so each provider gets its own run-layout directory,
# `consumer_genotype_array` semantics, and Active Genome Index.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ConsumerArraySpec:
    source_format: str
    provider_label: str
    sample_name: str
    row_iterator: Any  # Callable[[TextIO], Iterator[JsonObject]]
    semantics: tuple[str, ...]


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
    "myheritage": _ConsumerArraySpec(
        source_format="myheritage",
        provider_label="MyHeritage",
        sample_name="MyHeritage",
        row_iterator=_iter_myheritage_rows,
        semantics=(
            "MyHeritage raw genotype data is a SNP-array observation source.",
            "Coordinates are GRCh37 unless the source declares otherwise.",
            "Available sample evidence is plus-strand observed genotype by rsID/locus; sequencing depth, genotype quality, phasing, and reference-block callability require sequencing-derived sources.",
            "Use rsID/locus presence as sample context; use public evidence tools for interpretation.",
            "Public evidence libraries are materialized lazily by focused tools after Active Genome Index creation.",
        ),
    ),
    "ftdna": _ConsumerArraySpec(
        source_format="ftdna",
        provider_label="FamilyTreeDNA",
        sample_name="FamilyTreeDNA",
        row_iterator=_iter_myheritage_rows,  # identical CSV shape, no comment block
        semantics=(
            "FamilyTreeDNA Family Finder raw genotype data is a SNP-array observation source.",
            "Coordinates are GRCh37 unless the source declares otherwise.",
            "Available sample evidence is plus-strand observed genotype by rsID/locus; sequencing depth, genotype quality, phasing, and reference-block callability require sequencing-derived sources.",
            "Use rsID/locus presence as sample context; use public evidence tools for interpretation.",
            "Public evidence libraries are materialized lazily by focused tools after Active Genome Index creation.",
        ),
    ),
    "livingdna": _ConsumerArraySpec(
        source_format="livingdna",
        provider_label="Living DNA",
        sample_name="LivingDNA",
        row_iterator=_iter_livingdna_rows,
        semantics=(
            "Living DNA raw genotype data is a SNP-array observation source.",
            "Coordinates are GRCh37 unless the source declares otherwise.",
            "Available sample evidence is plus-strand observed genotype by rsID/locus; sequencing depth, genotype quality, phasing, and reference-block callability require sequencing-derived sources.",
            "Use rsID/locus presence as sample context; use public evidence tools for interpretation.",
            "Public evidence libraries are materialized lazily by focused tools after Active Genome Index creation.",
        ),
    ),
}


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
    fmt = spec.source_format
    effective_build = _effective_array_build(genome_build, detection.reference_build)
    project_dir = run_project_dir_for_source(source_path, source_format=fmt)
    work_dir = run_work_dir_for_source(source_path, source_format=fmt)
    evidence_dir = run_evidence_dir_for_source(source_path, source_format=fmt)
    reference_dir = run_reference_dir_for_source(source_path, source_format=fmt)
    db_path = Path(evidence_db) if evidence_db is not None else run_evidence_db_path_for_source(source_path, source_format=fmt)
    shared_db = Path(shared_evidence_db) if shared_evidence_db is not None else shared_evidence_db_path()
    active_genome_index_path = run_output_path_for_source(source_path, "active-genome-index.sqlite", source_format=fmt)
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
    active_genome_index_result = _build_consumer_array_active_genome_index(
        source_path,
        active_genome_index_path,
        spec=spec,
        detection=detection,
        genome_build=effective_build,
        force=force,
        max_records=max_records,
    )
    steps: list[JsonObject] = [
        {
            "name": "build-active-genome-index",
            "result": active_genome_index_result,
            "reason": f"The {spec.provider_label} raw genotype export is digitized into an Active Genome Index.",
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
        "outputs": {"active_genome_index_path": str(active_genome_index_path)},
        "steps": steps,
        "semantics": list(spec.semantics),
    }


def _build_consumer_array_active_genome_index(
    source_path: Path,
    active_genome_index_path: Path,
    *,
    spec: _ConsumerArraySpec,
    detection: SourceDetection,
    genome_build: str,
    force: bool,
    max_records: int | None,
) -> JsonObject:
    if active_genome_index_path.exists() and not force:
        cached = _cached_array_active_genome_index_if_usable(
            source_path,
            active_genome_index_path,
            detection=detection,
            source_format=spec.source_format,
            genome_build=genome_build,
            max_records=max_records,
        )
        if cached is not None:
            return cached
    active_genome_index_path.parent.mkdir(parents=True, exist_ok=True)
    with connect_active_genome_index(active_genome_index_path) as connection:
        _reset_source_active_genome_index_schema(connection)
        _insert_source_active_genome_index_metadata(connection, source_path, detection=detection, genome_build=genome_build, max_records=max_records)
        stats, chromosome_counts = _populate_consumer_array_records(
            connection,
            source_path,
            spec=spec,
            detection=detection,
            max_records=max_records,
        )
        _create_source_query_indexes(connection)
        _insert_source_stat_rows(connection, stats)
        connection.commit()
    return {
        "status": "completed",
        "source": str(source_path),
        "source_format": spec.source_format,
        "active_genome_index_path": str(active_genome_index_path),
        "schema_version": SCHEMA_VERSION,
        "genome_build": genome_build,
        "stats": stats,
        "chromosome_counts": dict(sorted(chromosome_counts.items(), key=lambda item: (_chrom_sort(item[0]), item[0]))),
    }


def _populate_consumer_array_records(
    connection: sqlite3.Connection,
    source_path: Path,
    *,
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
            is_called = genotype not in {"", "--", "00", "NN"} and "0" not in genotype and "-" not in genotype
            if is_called:
                called += 1
            else:
                no_call += 1
            batch.append(
                _array_record_row(
                    row,
                    row_index=row_index,
                    is_called=is_called,
                    sample_name=spec.sample_name,
                    source_format=spec.source_format,
                )
            )
            if len(batch) >= 50_000:
                _insert_source_record_batch(connection, batch)
                connection.commit()
                batch.clear()
    if batch:
        _insert_source_record_batch(connection, batch)
    return (
        {
            "total_records": total,
            "variant_records": called,
            "reference_records": no_call,
            "pass_records": called,
            "fail_records": no_call,
            "rsid_records": rsid_count,
        },
        chrom_counts,
    )
