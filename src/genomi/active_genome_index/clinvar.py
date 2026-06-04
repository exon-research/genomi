from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .reader import ActiveGenomeIndexReader


JsonObject = dict[str, Any]


def stage_clinvar_match_records(
    reader: ActiveGenomeIndexReader,
    connection: sqlite3.Connection,
    *,
    pass_only: bool,
    max_records: int | None,
) -> JsonObject:
    """Materialize the AGI rows ClinVar matching may read into temp tables."""

    reader.ensure_ready()
    alias = "_agi_clinvar_source"
    reader.attach_to(connection, alias)
    try:
        _ensure_ready_for_clinvar_match(connection, alias, reader.agi_path)
        connection.executescript(
            """
            drop table if exists temp.selected_active_genome_index_records;
            create temp table selected_active_genome_index_records (
                record_rowid integer not null,
                chrom text not null,
                chrom_sort integer,
                pos integer not null,
                rsid text,
                ref text,
                alt text,
                qual text,
                filter text,
                info text,
                sample_index integer,
                sample_name text,
                format text,
                genotype text,
                depth integer,
                genotype_quality integer,
                record_kind text,
                observed_alleles text
            );
            create index selected_active_genome_index_records_locus_idx
                on selected_active_genome_index_records(chrom, pos);
            """
        )
        sql = f"""
            insert into temp.selected_active_genome_index_records (
                record_rowid, chrom, chrom_sort, pos, rsid, ref, alt, qual, filter,
                info, sample_index, sample_name, format, genotype, depth,
                genotype_quality, record_kind, observed_alleles
            )
            select rowid, chrom, chrom_sort, pos, rsid, ref, alt, qual, filter,
                   info, sample_index, sample_name, format, genotype, depth,
                   genotype_quality, record_kind, observed_alleles
            from {alias}.records
            where record_kind in ('variant_call', 'array_call')
        """
        connection.execute(sql)
        skipped_non_pass = 0
        if pass_only:
            row = connection.execute(
                """
                select count(*) as skipped_non_pass
                from temp.selected_active_genome_index_records
                where filter not in ('PASS', '.')
                """
            ).fetchone()
            skipped_non_pass = int(row["skipped_non_pass"] or 0)
        connection.commit()
        return {"source_format": _source_format(connection, alias), "skipped_non_pass": skipped_non_pass}
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.execute(f"detach database {alias}")


def _ensure_ready_for_clinvar_match(connection: sqlite3.Connection, alias: str, agi_path: Path) -> None:
    stats_count = connection.execute(f"select count(*) from {alias}.stats").fetchone()[0]
    index_names = {
        str(row["name"])
        for row in connection.execute(
            f"""
            select name
            from {alias}.sqlite_master
            where type = 'index' and tbl_name = 'records'
            """
        )
    }
    required_indexes = {"records_export_idx", "records_variant_idx"}
    missing_indexes = sorted(required_indexes - index_names)
    if stats_count == 0 or missing_indexes:
        details = []
        if stats_count == 0:
            details.append("missing stats rows")
        if missing_indexes:
            details.append(f"missing query indexes: {', '.join(missing_indexes)}")
        raise RuntimeError(
            f"Active Genome Index is incomplete for ClinVar refresh ({agi_path}): "
            f"{'; '.join(details)}. Rebuild the Active Genome Index from the source genome file once."
        )


def _source_format(connection: sqlite3.Connection, alias: str) -> str | None:
    try:
        row = connection.execute(f"select value from {alias}.metadata where key = 'source_format'").fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    try:
        parsed = json.loads(str(row["value"]))
    except (TypeError, json.JSONDecodeError):
        parsed = row["value"]
    return str(parsed) if parsed else None
