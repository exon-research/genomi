from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ...evidence import connect_evidence, init_evidence_db
from ...runtime.external import file_metadata, utc_now
from ...runtime.paths import (
    run_evidence_dir_for_source,
    run_project_dir_for_source,
    run_reference_dir_for_source,
    run_work_dir_for_source,
    sample_slug_from_source,
)
from .._agi_schema import (
    ACTIVE_GENOME_INDEX_BUILD_STATUS_COMPLETED,
    ACTIVE_GENOME_INDEX_BUILD_STATUS_IN_PROGRESS,
    REQUIRED_QUERY_OBJECTS,
)
from ..active_genome_index import ActiveGenomeIndexSchemaTooNew, SCHEMA_VERSION, _chrom_sort
from ..active_genome_index import connect as connect_active_genome_index
from ..record_kinds import (
    ARRAY_FORMAT,
    ARRAY_NO_CALL_FILTER,
    array_record_kind,
)
from .detection import SourceDetection

JsonObject = dict[str, Any]


def _array_record_row(
    row: JsonObject,
    *,
    row_index: int,
    is_called: bool,
    sample_name: str,
    source_format: str,
) -> tuple[Any, ...]:
    genotype = row["genotype"]
    record_kind = array_record_kind(is_called=is_called)
    observed_alleles = list(genotype) if is_called else None
    return (
        row["chrom"],
        _chrom_sort(row["chrom"]),
        int(row["pos"]),
        int(row["pos"]),
        row["rsid"] or None,
        0,
        sample_name,
        json.dumps([]),
        ".",
        ".",
        ".",
        None,
        "PASS" if is_called else ARRAY_NO_CALL_FILTER,
        0,
        ARRAY_FORMAT,
        genotype,
        genotype,
        None,
        None,
        row_index,
        0,
        record_kind,
        json.dumps(observed_alleles, sort_keys=True) if observed_alleles is not None else None,
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
        drop table if exists source_header_lines;

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
            line_length integer not null,
            record_kind text not null,
            observed_alleles text
        );

        create table spans (
            chrom text not null,
            chrom_sort integer not null,
            pos integer not null,
            end integer not null,
            offset integer not null,
            sample_index integer not null default 0
        );

        create table source_header_lines (
            line_number integer primary key,
            line text not null
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
        create index records_record_kind_idx on records(record_kind, chrom, pos);
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
        "active_genome_index_build_status": ACTIVE_GENOME_INDEX_BUILD_STATUS_IN_PROGRESS,
        "active_genome_index_complete": False,
        "active_genome_index_started_at": utc_now(),
        "active_genome_index_completed_at": None,
        "variants_complete": False,
        "reference_complete": None,
    }
    connection.executemany(
        "insert into metadata(key, value) values(?, ?)",
        [(key, json.dumps(value, sort_keys=True)) for key, value in values.items()],
    )
    _insert_source_header_lines(connection, detection=detection)


def _insert_source_header_lines(connection: sqlite3.Connection, *, detection: SourceDetection) -> None:
    source_label = detection.source_format or "consumer_array"
    lines = [
        "##fileformat=VCFv4.2",
        f"##source=Genomi consumer genotype array ({source_label})",
        f"##genomiSourceFormat={source_label}",
        f"##genomiSourceKind={detection.source_kind}",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
    ]
    connection.executemany(
        "insert into source_header_lines(line_number, line) values(?, ?)",
        [(index, line) for index, line in enumerate(lines)],
    )


def _mark_source_active_genome_index_completed(connection: sqlite3.Connection) -> None:
    values = {
        "active_genome_index_build_status": ACTIVE_GENOME_INDEX_BUILD_STATUS_COMPLETED,
        "active_genome_index_complete": True,
        "active_genome_index_completed_at": utc_now(),
        "variants_complete": True,
    }
    connection.executemany(
        """
        insert into metadata(key, value) values(?, ?)
        on conflict(key) do update set value = excluded.value
        """,
        [(key, json.dumps(value, sort_keys=True)) for key, value in values.items()],
    )


def _insert_source_stat_rows(connection: sqlite3.Connection, stats: JsonObject) -> None:
    connection.executemany("insert into stats(key, value) values(?, ?)", [(key, str(value)) for key, value in stats.items()])


def _insert_source_record_batch(connection: sqlite3.Connection, batch: Iterable[tuple[Any, ...]]) -> None:
    connection.executemany(
        """
        insert into records(
            chrom, chrom_sort, pos, end, rsid, sample_index, sample_name, info_genes, info, ref, alt, qual, filter,
            is_variant, format, sample, genotype, depth, genotype_quality, offset, line_length,
            record_kind, observed_alleles
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        list(batch),
    )


def _cached_array_active_genome_index_if_usable(
    source_path: Path,
    agi_path: Path,
    *,
    detection: SourceDetection,
    source_format: str,
    genome_build: str,
    max_records: int | None,
) -> JsonObject | None:
    if not agi_path.exists():
        return None
    try:
        with connect_active_genome_index(agi_path) as connection:
            metadata = {row["key"]: json.loads(row["value"]) for row in connection.execute("select key, value from metadata")}
            stats = {row["key"]: int(row["value"]) for row in connection.execute("select key, value from stats")}
            objects = {
                (row["type"], row["name"])
                for row in connection.execute(
                    """
                    select type, name
                    from sqlite_master
                    where type in ('table', 'index')
                    """
                )
            }
    except (sqlite3.Error, ValueError, json.JSONDecodeError):
        return None
    try:
        stored_schema_version = int(metadata.get("schema_version"))
    except (TypeError, ValueError):
        return None
    if stored_schema_version < SCHEMA_VERSION:
        return None
    if stored_schema_version > SCHEMA_VERSION:
        raise ActiveGenomeIndexSchemaTooNew(
            f"Active Genome Index at {agi_path} has schema_version="
            f"{stored_schema_version}; this Genomi runtime only supports up to "
            f"schema_version={SCHEMA_VERSION}. Upgrade Genomi before reading "
            "this Active Genome Index."
        )
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
    if metadata.get("active_genome_index_build_status") != ACTIVE_GENOME_INDEX_BUILD_STATUS_COMPLETED:
        return None
    if metadata.get("active_genome_index_complete") is not True:
        return None
    if REQUIRED_QUERY_OBJECTS - objects:
        return None
    expected_metadata = file_metadata(source_path)
    actual_metadata = metadata.get("source_metadata") or {}
    if actual_metadata != expected_metadata:
        return None
    return {
        "status": "cached",
        "source": str(source_path),
        "source_format": source_format,
        "agi_path": str(agi_path),
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
