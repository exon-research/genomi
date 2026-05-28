from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ...evidence import connect_evidence, init_evidence_db
from ...runtime.external import file_metadata
from ...runtime.paths import (
    run_evidence_dir_for_source,
    run_project_dir_for_source,
    run_reference_dir_for_source,
    run_work_dir_for_source,
    sample_slug_from_source,
)
from ..active_genome_index import SCHEMA_VERSION, _chrom_sort
from ..active_genome_index import connect as connect_active_genome_index
from .detection import SourceDetection

JsonObject = dict[str, Any]
SOURCE_PARSE_SCHEMA = "genomi-source-parse-v1"


def _array_record_row(
    row: JsonObject,
    *,
    row_index: int,
    is_called: bool,
    sample_name: str,
    source_format: str,
) -> tuple[Any, ...]:
    genotype = row["genotype"]
    return (
        row["chrom"],
        _chrom_sort(row["chrom"]),
        int(row["pos"]),
        int(row["pos"]),
        row["rsid"] or None,
        0,
        sample_name,
        json.dumps([]),
        json.dumps({"source_format": source_format, "coordinate_semantics": "plus_strand_grch37"}),
        "N",
        genotype if is_called else ".",
        None,
        "PASS" if is_called else "NO_CALL",
        int(is_called),
        "GT_ARRAY",
        genotype,
        genotype,
        None,
        None,
        row_index,
        0,
    )


def _reset_source_active_genome_index_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        pragma page_size = 16384;
        pragma journal_mode = off;
        pragma synchronous = off;
        pragma temp_store = memory;

        drop table if exists metadata;
        drop table if exists stats;
        drop table if exists spans;
        drop table if exists records;

        create table metadata (
            key text primary key,
            value text not null
        );

        create table stats (
            key text primary key,
            value text not null
        );

        create table records (
            chrom text not null,
            chrom_sort integer not null,
            pos integer not null,
            end integer not null,
            rsid text,
            sample_index integer not null default 0,
            sample_name text,
            info_genes text,
            info text,
            ref text not null,
            alt text not null,
            qual text,
            filter text not null,
            is_variant integer not null,
            format text,
            sample text,
            genotype text,
            depth integer,
            genotype_quality integer,
            offset integer not null,
            line_length integer not null
        );

        create table spans (
            chrom text not null,
            chrom_sort integer not null,
            pos integer not null,
            end integer not null,
            offset integer not null,
            sample_index integer not null default 0
        );
        """
    )


def _create_source_query_indexes(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        create index records_rsid_idx on records(rsid) where rsid is not null;
        create index records_region_idx on records(chrom, pos, end);
        create index records_variant_idx on records(chrom, pos, ref, alt) where is_variant = 1;
        create index records_export_idx on records(is_variant, filter, chrom_sort, pos) where is_variant = 1;
        create index records_offset_sample_idx on records(offset, sample_index);
        create index spans_region_idx on spans(chrom, pos, end);
        """
    )


def _insert_source_active_genome_index_metadata(
    connection: sqlite3.Connection,
    source_path: Path,
    *,
    detection: SourceDetection,
    genome_build: str,
    max_records: int | None,
) -> None:
    values = {
        "schema_version": SCHEMA_VERSION,
        "source": str(source_path),
        "source_metadata": file_metadata(source_path),
        "source_format": detection.source_format,
        "source_kind": detection.source_kind,
        "source_member": detection.member_name,
        "genome_build": genome_build,
        "max_records": max_records,
        "record_semantics": {
            "ref": "N placeholder for genotype-array sources",
            "alt": "observed genotype string for genotype-array sources",
            "depth": None,
            "genotype_quality": None,
        },
    }
    connection.executemany(
        "insert into metadata(key, value) values(?, ?)",
        [(key, json.dumps(value, sort_keys=True)) for key, value in values.items()],
    )


def _insert_source_stat_rows(connection: sqlite3.Connection, stats: JsonObject) -> None:
    connection.executemany("insert into stats(key, value) values(?, ?)", [(key, str(value)) for key, value in stats.items()])


def _insert_source_record_batch(connection: sqlite3.Connection, batch: Iterable[tuple[Any, ...]]) -> None:
    connection.executemany(
        """
        insert into records(
            chrom, chrom_sort, pos, end, rsid, sample_index, sample_name, info_genes, info, ref, alt, qual, filter,
            is_variant, format, sample, genotype, depth, genotype_quality, offset, line_length
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        list(batch),
    )


def _cached_array_active_genome_index_if_usable(
    source_path: Path,
    active_genome_index_path: Path,
    *,
    detection: SourceDetection,
    source_format: str,
    genome_build: str,
    max_records: int | None,
) -> JsonObject | None:
    if not active_genome_index_path.exists():
        return None
    try:
        with connect_active_genome_index(active_genome_index_path) as connection:
            metadata = {row["key"]: json.loads(row["value"]) for row in connection.execute("select key, value from metadata")}
            stats = {row["key"]: int(row["value"]) for row in connection.execute("select key, value from stats")}
    except (sqlite3.Error, ValueError, json.JSONDecodeError):
        return None
    if metadata.get("schema_version") != SCHEMA_VERSION:
        return None
    if metadata.get("source") != str(source_path):
        return None
    if metadata.get("source_format") != source_format:
        return None
    if metadata.get("source_member") != detection.member_name:
        return None
    if metadata.get("genome_build") != genome_build:
        return None
    if metadata.get("max_records") != max_records:
        return None
    expected_metadata = file_metadata(source_path)
    actual_metadata = metadata.get("source_metadata") or {}
    if actual_metadata != expected_metadata:
        return None
    return {
        "status": "cached",
        "source": str(source_path),
        "source_format": source_format,
        "active_genome_index_path": str(active_genome_index_path),
        "schema_version": SCHEMA_VERSION,
        "genome_build": genome_build,
        "stats": stats,
    }


def _init_source_evidence_db(
    evidence_db: Path,
    source_path: Path,
    *,
    source_format: str,
    source_evidence_db: str | Path | None,
    shared_evidence_db: str | Path | None,
) -> None:
    init_evidence_db(evidence_db)
    metadata = {
        "workflow_model": "journal-source-review-report",
        "run_sample_slug": sample_slug_from_source(source_path, source_format=source_format),
        "run_source_path": str(source_path),
        "run_source_format": source_format,
        "run_project_dir": str(run_project_dir_for_source(source_path, source_format=source_format)),
        "run_work_dir": str(run_work_dir_for_source(source_path, source_format=source_format)),
        "run_evidence_dir": str(run_evidence_dir_for_source(source_path, source_format=source_format)),
        "run_reference_dir": str(run_reference_dir_for_source(source_path, source_format=source_format)),
        "source_evidence_db": str(source_evidence_db) if source_evidence_db is not None else None,
        "shared_evidence_db": str(shared_evidence_db) if shared_evidence_db is not None else None,
    }
    with connect_evidence(evidence_db, attach_shared=False) as connection:
        for key, value in metadata.items():
            connection.execute(
                """
                insert into metadata(key, value) values(?, ?)
                on conflict(key) do update set value = excluded.value
                """,
                (key, json.dumps(value, sort_keys=True)),
            )
        connection.commit()
