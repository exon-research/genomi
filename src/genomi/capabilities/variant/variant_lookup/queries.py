from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from ....active_genome_index.active_genome_index import ActiveGenomeIndexReader
from ....active_genome_index.record_kinds import RECORD_KIND_REFERENCE_BLOCK
from ....runtime.sqlite_support import connect_readonly_sqlite
from .parsing import _chrom_aliases, _dedupe_records, _target_key

JsonObject = dict[str, Any]


def _query_active_genome_index(
    reader: ActiveGenomeIndexReader,
    *,
    run: JsonObject,
    selection: str,
    target: JsonObject,
    include_fail: bool,
    limit: int,
    warnings: list[str],
) -> list[JsonObject]:
    try:
        target_type = target["target_type"]
        pass_only = not include_fail
        if target_type == "rsid":
            return _enrich_active_genome_index_records(
                reader.query_rsid(str(target["rsid"]), limit=limit, pass_only=pass_only),
                run=run,
                selection=selection,
                target=target,
            )
        if target_type == "allele":
            rows: list[JsonObject] = []
            for chrom_value in _chrom_aliases(str(target["chrom"])):
                rows.extend(
                    reader.query_variant(
                        chrom_value,
                        int(target["pos"]),
                        str(target["ref"]),
                        str(target["alt"]),
                        limit=limit,
                        pass_only=pass_only,
                    )
                )
            if not rows:
                # Allele not observed as a variant call. For gVCF inputs the
                # site may be covered by a reference block. Keep that as raw
                # sample context only; genotype_support/callability owns any
                # negative or homozygous-reference claim.
                for chrom_value in _chrom_aliases(str(target["chrom"])):
                    reference_rows = [
                        row
                        for row in reader.query_region(
                            chrom_value,
                            int(target["pos"]),
                            int(target["pos"]),
                            variants_only=False,
                            pass_only=pass_only,
                            limit=limit,
                        )
                        if row.get("record_kind") == RECORD_KIND_REFERENCE_BLOCK
                    ]
                    rows.extend(reference_rows)
            return _dedupe_records(
                _enrich_active_genome_index_records(rows, run=run, selection=selection, target=target),
                ("agi_id", "chrom", "pos", "ref", "alt", "rsid", "genotype", "filter"),
            )
        if target_type == "locus":
            rows = []
            for chrom_value in _chrom_aliases(str(target["chrom"])):
                rows.extend(
                    reader.query_region(
                        chrom_value,
                        int(target["pos"]),
                        int(target["pos"]),
                        variants_only=False,
                        pass_only=pass_only,
                        limit=limit,
                    )
                )
            return _dedupe_records(
                _enrich_active_genome_index_records(rows, run=run, selection=selection, target=target),
                ("agi_id", "chrom", "pos", "ref", "alt", "rsid", "genotype", "filter"),
            )
        if target_type == "region":
            rows = []
            for chrom_value in _chrom_aliases(str(target["chrom"])):
                rows.extend(
                    reader.query_region(
                        chrom_value,
                        int(target["start"]),
                        int(target["end"]),
                        variants_only=False,
                        pass_only=pass_only,
                        limit=limit,
                    )
                )
            return _dedupe_records(
                _enrich_active_genome_index_records(rows, run=run, selection=selection, target=target),
                ("agi_id", "chrom", "pos", "ref", "alt", "rsid", "genotype", "filter"),
            )
    except sqlite3.Error as exc:
        warnings.append(f"Could not query Active Genome Index {run.get('agi_id')}: {exc}")
    return []


def _enrich_active_genome_index_records(
    rows: list[JsonObject],
    *,
    run: JsonObject,
    selection: str,
    target: JsonObject,
) -> list[JsonObject]:
    output: list[JsonObject] = []
    for record in rows:
        row = dict(record)
        row["agi_id"] = run.get("agi_id")
        row["sample_slug"] = run.get("sample_slug")
        row["source_format"] = run.get("source_format")
        row["source_kind"] = run.get("source_kind")
        row["selection"] = selection
        row["target"] = _target_key(target)
        output.append(row)
    return output


def _query_clinvar_rsid(
    path: Path,
    label: str,
    rsid: str,
    *,
    genome_build: str,
    limit: int,
    warnings: list[str],
) -> list[JsonObject]:
    sql = """
        select cr.rsid, cv.chrom, cv.pos, cv.ref, cv.alt, cv.genome_build, cv.clinvar_id, cv.allele_id,
               cv.clinical_significance, cv.review_status, cv.conditions, cv.gene_info,
               cv.hgvs, cv.source_version, cv.imported_at
        from clinvar_variant_rsids as cr
        join clinvar_variants as cv
          on cv.rowid = cr.variant_rowid
         and cv.genome_build = cr.genome_build
        where cr.genome_build = ? and cr.rsid = ?
        order by cv.imported_at desc, cv.chrom, cv.pos
        limit ?
    """
    return _query_public_rows(path, label, sql, [genome_build, rsid, limit], warnings=warnings)


def _query_clinvar_allele(path: Path, label: str, target: JsonObject, *, limit: int, warnings: list[str]) -> list[JsonObject]:
    sql = """
        select chrom, pos, ref, alt, genome_build, clinvar_id, allele_id,
               clinical_significance, review_status, conditions, gene_info,
               hgvs, source_version, imported_at
        from clinvar_variants
        where chrom = ? and pos = ? and ref = ? and alt = ? and genome_build = ?
        order by imported_at desc
        limit ?
    """
    return _query_public_rows(
        path,
        label,
        sql,
        [target["chrom"], target["pos"], target["ref"], target["alt"], target.get("genome_build") or "GRCh38", limit],
        warnings=warnings,
    )


def _query_clinvar_locus(
    path: Path,
    label: str,
    chrom: str,
    pos: int,
    *,
    genome_build: str,
    limit: int,
    warnings: list[str],
) -> list[JsonObject]:
    sql = """
        select chrom, pos, ref, alt, genome_build, clinvar_id, allele_id,
               clinical_significance, review_status, conditions, gene_info,
               hgvs, source_version, imported_at
        from clinvar_variants
        where chrom = ? and pos = ? and genome_build = ?
        order by imported_at desc
        limit ?
    """
    return _query_public_rows(path, label, sql, [chrom, pos, genome_build, limit], warnings=warnings)


def _query_clinvar_region(
    path: Path,
    label: str,
    chrom: str,
    start: int,
    end: int,
    *,
    genome_build: str,
    limit: int,
    warnings: list[str],
) -> list[JsonObject]:
    sql = """
        select chrom, pos, ref, alt, genome_build, clinvar_id, allele_id,
               clinical_significance, review_status, conditions, gene_info,
               hgvs, source_version, imported_at
        from clinvar_variants
        where chrom = ? and pos between ? and ? and genome_build = ?
        order by pos, imported_at desc
        limit ?
    """
    return _query_public_rows(path, label, sql, [chrom, start, end, genome_build, limit], warnings=warnings)


def _query_population_allele(path: Path, label: str, target: JsonObject, *, limit: int, warnings: list[str]) -> list[JsonObject]:
    sql = """
        select chrom, pos, ref, alt, genome_build, source, source_version,
               population, allele_count, allele_number, allele_frequency,
               homozygote_count, imported_at
        from population_frequencies
        where chrom = ? and pos = ? and ref = ? and alt = ? and genome_build = ?
        order by source, case when population = 'global' then 0 else 1 end, population
        limit ?
    """
    return _query_public_rows(
        path,
        label,
        sql,
        [target["chrom"], target["pos"], target["ref"], target["alt"], target.get("genome_build") or "GRCh38", limit],
        warnings=warnings,
    )


def _query_research_variant(path: Path, label: str, target: JsonObject, *, limit: int, warnings: list[str]) -> list[JsonObject]:
    target_id = f"variant:{target.get('genome_build') or 'GRCh38'}:{target['chrom']}-{target['pos']}-{target['ref']}-{target['alt']}"
    return _query_research_by_target_id(path, label, target_type="variant", target_id=target_id, limit=limit, warnings=warnings)


def _query_research_topic(path: Path, label: str, topic: str, *, limit: int, warnings: list[str]) -> list[JsonObject]:
    target_id = "topic:" + " ".join(topic.casefold().split())
    return _query_research_by_target_id(path, label, target_type="topic", target_id=target_id, limit=limit, warnings=warnings)


def _query_research_by_target_id(
    path: Path,
    label: str,
    *,
    target_type: str,
    target_id: str,
    limit: int,
    warnings: list[str],
) -> list[JsonObject]:
    sql = """
        select finding_id, target_type, target_id, chrom, pos, ref, alt, gene, drug, condition, topic,
               genome_build, research_scope, source_title, source_url, source_type, source_published_at,
               source_accessed_at, searched_query, finding_text, finding_summary, finding_type,
               captured_by, captured_at
        from research_findings
        where target_type = ? and target_id = ?
        order by source_accessed_at desc, captured_at desc, source_title
        limit ?
    """
    return _query_public_rows(path, label, sql, [target_type, target_id, limit], warnings=warnings)


def _query_public_rows(path: Path, label: str, sql: str, params: list[Any], *, warnings: list[str]) -> list[JsonObject]:
    if not path.exists():
        return []
    try:
        with _connect_readonly(path) as connection:
            table_match = re.search(r"\bfrom\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql)
            if table_match and not _table_exists(connection, table_match.group(1)):
                return []
            rows = [dict(row) for row in connection.execute(sql, params)]
    except sqlite3.Error as exc:
        warnings.append(f"Could not query evidence store {label}: {exc}")
        return []
    for row in rows:
        row["evidence_store"] = label
    return rows


def _connect_readonly(path: Path) -> sqlite3.Connection:
    # Absorb brief contention windows when a build commit overlaps with a
    # read. Without this, a reader can race a writer's transaction boundary
    # and fail with "database is locked" even when the build is otherwise
    # well-behaved.
    return connect_readonly_sqlite(path)


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "select 1 from sqlite_master where type in ('table', 'view') and name = ?",
        (name,),
    ).fetchone()
    return row is not None
