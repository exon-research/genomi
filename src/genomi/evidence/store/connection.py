from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from ...runtime.external import file_metadata, matching_manifest, utc_now
from ...runtime.sqlite_support import (
    LONG_WRITE_BUSY_TIMEOUT_SECONDS,
    connect_readonly_sqlite,
    connect_sqlite,
)

from .constants import (
    EVIDENCE_SCHEMA_VERSION,
    RESEARCH_FINDING_COLUMNS,
    SHARED_EVIDENCE_ALIAS,
    SHARED_EVIDENCE_TABLES,
    SQLITE_BUSY_TIMEOUT_SECONDS,
)



def connect_evidence(path: str | Path, *, attach_shared: bool = True) -> sqlite3.Connection:
    # WAL lets concurrent readers (e.g. classify_region_callability while
    # match_clinvar_variants is still writing) coexist with a single writer
    # instead of immediately failing with "database is locked". The busy
    # timeout above absorbs the brief checkpoint windows.
    connection = connect_sqlite(
        path,
        timeout_seconds=SQLITE_BUSY_TIMEOUT_SECONDS,
        create_parent=True,
        wal=True,
    )
    if attach_shared:
        _attach_linked_shared_evidence(connection, Path(path))
    return connection


def init_evidence_db(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect_evidence(path) as connection:
        _ensure_schema(connection)
        _upsert_metadata(connection, "schema_version", EVIDENCE_SCHEMA_VERSION)
        connection.commit()
    return {
        "evidence_db": str(path),
        "schema_version": EVIDENCE_SCHEMA_VERSION,
    }


def _attach_linked_shared_evidence(connection: sqlite3.Connection, evidence_db: Path) -> None:
    shared_path = _linked_shared_evidence_path(connection, evidence_db)
    if shared_path is None:
        return
    connection.execute(f"attach database ? as {SHARED_EVIDENCE_ALIAS}", (str(shared_path.resolve()),))


def _linked_shared_evidence_path(connection: sqlite3.Connection, evidence_db: Path) -> Path | None:
    if not evidence_db.exists():
        return None
    try:
        metadata_rows = connection.execute("select key, value from main.metadata").fetchall()
    except sqlite3.OperationalError:
        return None
    metadata = {row["key"]: json.loads(row["value"]) for row in metadata_rows}
    for key in ("source_evidence_db", "shared_evidence_db"):
        value = metadata.get(key)
        if not value:
            continue
        candidate = Path(str(value))
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        if candidate.exists() and candidate.resolve() != evidence_db.resolve():
            return candidate
    return None


def _install_linked_shared_views(connection: sqlite3.Connection) -> None:
    if not _has_attached_shared_evidence(connection):
        return
    for table in SHARED_EVIDENCE_TABLES:
        if not _attached_table_exists(connection, table):
            continue
        connection.execute(f"drop view if exists temp.{table}")
        connection.execute(
            f"""
            create temp view {table} as
            select rowid, * from main.{table}
            union all
            select rowid, * from {SHARED_EVIDENCE_ALIAS}.{table}
            """
        )
    if _attached_table_exists(connection, "research_findings") and _main_table_exists(connection, "research_findings"):
        shared_columns = ", ".join(f"shared.{column}" for column in RESEARCH_FINDING_COLUMNS)
        local_columns = ", ".join(f"local.{column}" for column in RESEARCH_FINDING_COLUMNS)
        connection.execute("drop view if exists temp.research_findings")
        connection.execute(
            f"""
            create temp view research_findings as
            select {local_columns}
            from main.research_findings as local
            union all
            select {shared_columns}
            from {SHARED_EVIDENCE_ALIAS}.research_findings as shared
            where shared.research_scope = 'shared'
              and not exists (
                select 1
                from main.research_findings as local
                where local.finding_id = shared.finding_id
              )
            """
        )


def _drop_linked_shared_views(connection: sqlite3.Connection) -> None:
    for table in (*SHARED_EVIDENCE_TABLES, "research_findings"):
        connection.execute(f"drop view if exists temp.{table}")


def _has_attached_shared_evidence(connection: sqlite3.Connection) -> bool:
    return any(row["name"] == SHARED_EVIDENCE_ALIAS for row in connection.execute("pragma database_list"))


def _attached_table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        f"select 1 from {SHARED_EVIDENCE_ALIAS}.sqlite_master where type = 'table' and name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _main_table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "select 1 from main.sqlite_master where type = 'table' and name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _read_metadata(connection: sqlite3.Connection) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if _has_attached_shared_evidence(connection) and _attached_table_exists(connection, "metadata"):
        metadata.update(
            {
                row["key"]: json.loads(row["value"])
                for row in connection.execute(
                    f"""
                    select key, value from {SHARED_EVIDENCE_ALIAS}.metadata
                    where key like 'clinvar_%'
                       or key like 'population_%'
                       or key like 'gnomad_%'
                       or key = 'schema_version'
                    """
                )
            }
        )
    metadata.update(
        {
            row["key"]: json.loads(row["value"])
            for row in connection.execute("select key, value from main.metadata")
        }
    )
    return metadata


def _clinvar_cache_identity(connection: sqlite3.Connection) -> dict[str, Any]:
    metadata = _read_metadata(connection)
    record_count = connection.execute("select count(*) as records from clinvar_variants").fetchone()["records"]
    return {
        "schema_version": metadata.get("schema_version"),
        "source": metadata.get("clinvar_source"),
        "source_version": metadata.get("clinvar_source_version"),
        "genome_build": metadata.get("clinvar_genome_build"),
        "max_records": metadata.get("clinvar_max_records"),
        "record_count": record_count,
    }


def _population_cache_identity(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in connection.execute(
            """
            select source, source_version, genome_build, population,
                   count(*) as records, max(imported_at) as latest_imported_at
            from population_frequencies
            group by source, source_version, genome_build, population
            order by source, source_version, genome_build, population
            """
        )
    ]
    return {
        "schema_version": _read_metadata(connection).get("schema_version"),
        "sources": rows,
    }


def _private_sample_context_identity(connection: sqlite3.Connection) -> dict[str, Any]:
    tables: dict[str, dict[str, Any]] = {}
    for table in ("sample_qc", "genotype_support", "region_callability"):
        row = connection.execute(
            f"select count(*) as records, max(created_at) as latest_created_at from {table}"
        ).fetchone()
        tables[table] = {
            "records": int(row["records"] or 0),
            "latest_created_at": row["latest_created_at"],
        }
    return {
        "schema_version": _read_metadata(connection).get("schema_version"),
        "tables": tables,
    }


def _ensure_schema(connection: sqlite3.Connection) -> None:
    _drop_linked_shared_views(connection)
    connection.executescript(
        """
        create table if not exists metadata (
            key text primary key,
            value text not null
        );

        create table if not exists clinvar_variants (
            chrom text not null,
            pos integer not null,
            ref text not null,
            alt text not null,
            genome_build text not null,
            clinvar_id text,
            allele_id text,
            clinical_significance text,
            review_status text,
            conditions text,
            gene_info text,
            hgvs text,
            raw_info_json text not null,
            source_path text not null,
            source_version text,
            imported_at text not null
        );

        create index if not exists clinvar_variant_idx
          on clinvar_variants(chrom, pos, ref, alt, genome_build);
        create index if not exists clinvar_id_idx
          on clinvar_variants(clinvar_id);

        create table if not exists clinvar_variant_genes (
            gene_symbol text not null,
            variant_rowid integer not null,
            genome_build text not null,
            primary key (gene_symbol, variant_rowid)
        );
        create index if not exists clinvar_variant_genes_gene_idx
          on clinvar_variant_genes(gene_symbol, genome_build);

        create table if not exists clinvar_variant_rsids (
            rsid text not null,
            variant_rowid integer not null,
            genome_build text not null,
            primary key (rsid, variant_rowid)
        );
        create index if not exists clinvar_variant_rsids_rsid_idx
          on clinvar_variant_rsids(rsid, genome_build);

        create table if not exists population_frequencies (
            chrom text not null,
            pos integer not null,
            ref text not null,
            alt text not null,
            genome_build text not null,
            source text not null,
            source_version text,
            population text not null,
            allele_count integer,
            allele_number integer,
            allele_frequency real,
            homozygote_count integer,
            raw_info_json text not null,
            source_path text not null,
            imported_at text not null
        );
        create index if not exists population_frequency_variant_idx
          on population_frequencies(chrom, pos, ref, alt, genome_build);
        create index if not exists population_frequency_source_idx
          on population_frequencies(source, population, genome_build);

        create table if not exists research_findings (
            finding_id text primary key,
            target_type text not null,
            target_id text not null,
            chrom text,
            pos integer,
            ref text,
            alt text,
            gene text,
            drug text,
            condition text,
            topic text,
            genome_build text,
            research_scope text not null default 'shared',
            source_title text not null,
            source_url text not null,
            source_type text,
            source_published_at text,
            source_accessed_at text not null,
            searched_query text,
            finding_text text not null,
            finding_summary text,
            finding_type text,
            captured_by text not null,
            captured_at text not null,
            raw_json text not null
        );
        create index if not exists research_findings_target_idx
          on research_findings(target_type, target_id, genome_build);
        create index if not exists research_findings_url_idx
          on research_findings(source_url);

        create table if not exists sample_qc (
            sample_id text not null,
            vcf_path text not null,
            genome_build text not null,
            input_type text not null,
            has_reference_blocks integer not null,
            has_depth integer not null,
            has_genotype_quality integer not null,
            absence_claims_allowed integer not null,
            summary_json text not null,
            evidence_boundaries_json text not null,
            created_at text not null,
            primary key (vcf_path, genome_build)
        );

        create table if not exists genotype_support (
            vcf_path text not null,
            chrom text not null,
            pos integer not null,
            ref text not null,
            alt text not null,
            genome_build text not null,
            support_status text not null,
            evidence_class text not null,
            genotype text,
            zygosity text,
            depth integer,
            genotype_quality integer,
            filter text,
            raw_json text not null,
            created_at text not null,
            primary key (vcf_path, chrom, pos, ref, alt, genome_build)
        );
        create index if not exists genotype_support_variant_idx
          on genotype_support(chrom, pos, ref, alt, genome_build);

        create table if not exists region_callability (
            vcf_path text not null,
            region text not null,
            chrom text not null,
            start integer not null,
            end integer not null,
            genome_build text not null,
            callability_status text not null,
            covered_fraction real not null,
            can_support_negative_claim integer not null,
            evidence_class text not null,
            raw_json text not null,
            created_at text not null,
            primary key (vcf_path, region, genome_build)
        );
        create index if not exists region_callability_region_idx
          on region_callability(chrom, start, end, genome_build);
        """
    )
    _ensure_research_finding_columns(connection)
    _upsert_metadata(connection, "schema_version", EVIDENCE_SCHEMA_VERSION)
    _install_linked_shared_views(connection)


def _ensure_research_finding_columns(connection: sqlite3.Connection) -> None:
    existing = {
        str(row["name"])
        for row in connection.execute("pragma table_info(research_findings)")
    }
    for column in ("drug", "condition", "topic"):
        if column not in existing:
            connection.execute(f"alter table research_findings add column {column} text")
    if "research_scope" not in existing:
        connection.execute("alter table research_findings add column research_scope text not null default 'shared'")


def _upsert_metadata(connection: sqlite3.Connection, key: str, value: Any) -> None:
    connection.execute(
        """
        insert into metadata(key, value) values(?, ?)
        on conflict(key) do update set value = excluded.value
        """,
        (key, json.dumps(value, sort_keys=True)),
    )


def _clinvar_import_cache(
    connection: sqlite3.Connection,
    evidence_db: Path,
    clinvar_vcf: Path,
    genome_build: str,
    source_version: str | None,
    max_records: int | None,
) -> dict[str, Any] | None:
    metadata = {
        row["key"]: json.loads(row["value"])
        for row in connection.execute("select key, value from metadata where key like 'clinvar_%'")
    }
    if not metadata:
        return None
    if metadata.get("clinvar_source") != file_metadata(clinvar_vcf):
        return None
    if metadata.get("clinvar_source_version") != source_version:
        return None
    if metadata.get("clinvar_genome_build") != genome_build:
        return None
    if "clinvar_max_records" in metadata and metadata.get("clinvar_max_records") != max_records:
        return None

    row = connection.execute("select count(*) as records from clinvar_variants").fetchone()
    inserted = int(row["records"])
    if inserted == 0:
        return None
    return {
        "status": "cached",
        "evidence_db": str(evidence_db),
        "source": str(clinvar_vcf),
        "source_version": source_version,
        "genome_build": genome_build,
        "scanned_records": inserted,
        "inserted_alleles": inserted,
    }


def _insert_clinvar_batch(connection: sqlite3.Connection, batch: list[tuple[Any, ...]]) -> None:
    connection.executemany(
        """
        insert into main.clinvar_variants(
            chrom, pos, ref, alt, genome_build, clinvar_id, allele_id,
            clinical_significance, review_status, conditions, gene_info,
            hgvs, raw_info_json, source_path, source_version, imported_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        batch,
    )


def _insert_gene_index_batch(connection: sqlite3.Connection, batch: list[tuple[str, int, str]]) -> None:
    connection.executemany(
        """
        insert or ignore into main.clinvar_variant_genes(gene_symbol, variant_rowid, genome_build)
        values (?, ?, ?)
        """,
        batch,
    )


def _insert_rsid_index_batch(connection: sqlite3.Connection, batch: list[tuple[str, int, str]]) -> None:
    connection.executemany(
        """
        insert or ignore into main.clinvar_variant_rsids(rsid, variant_rowid, genome_build)
        values (?, ?, ?)
        """,
        batch,
    )


def _insert_population_batch(connection: sqlite3.Connection, batch: list[tuple[Any, ...]]) -> None:
    connection.executemany(
        """
        insert into main.population_frequencies(
            chrom, pos, ref, alt, genome_build, source, source_version, population,
            allele_count, allele_number, allele_frequency, homozygote_count,
            raw_info_json, source_path, imported_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        batch,
    )


def _insert_research_batch(connection: sqlite3.Connection, batch: list[tuple[Any, ...]]) -> None:
    connection.executemany(
        """
        insert into main.research_findings(
            finding_id, target_type, target_id, chrom, pos, ref, alt, gene,
            drug, condition, topic, genome_build, research_scope, source_title, source_url, source_type, source_published_at,
            source_accessed_at, searched_query, finding_text, finding_summary,
            finding_type, captured_by, captured_at, raw_json
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(finding_id) do update set
            target_type = excluded.target_type,
            target_id = excluded.target_id,
            chrom = excluded.chrom,
            pos = excluded.pos,
            ref = excluded.ref,
            alt = excluded.alt,
            gene = excluded.gene,
            drug = excluded.drug,
            condition = excluded.condition,
            topic = excluded.topic,
            genome_build = excluded.genome_build,
            research_scope = excluded.research_scope,
            source_title = excluded.source_title,
            source_url = excluded.source_url,
            source_type = excluded.source_type,
            source_published_at = excluded.source_published_at,
            source_accessed_at = excluded.source_accessed_at,
            searched_query = excluded.searched_query,
            finding_text = excluded.finding_text,
            finding_summary = excluded.finding_summary,
            finding_type = excluded.finding_type,
            captured_by = excluded.captured_by,
            captured_at = excluded.captured_at,
            raw_json = excluded.raw_json
        """,
        batch,
    )
