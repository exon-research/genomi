from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any
from ...active_genome_index.vcf import parse_info, parse_sample
from ...runtime.external import file_metadata, matching_manifest, utc_now
from ...runtime.handoff import evidence_context
from ...runtime.paths import run_evidence_db_path, run_output_path

from .constants import (
    SHARED_EVIDENCE_ALIAS,
)
from .helpers import (
    _is_passing_filter,
    _iter_vcf_record_groups,
    _none_if_dot,
)
from .connection import (
    _attached_table_exists,
    _clinvar_cache_identity,
    _ensure_schema,
    _has_attached_shared_evidence,
    connect_evidence,
)
from .clinvar_query import (
    _query_clinvar_exact_rows,
)



def match_clinvar_variants(
    vcf_path: str | Path,
    evidence_db: str | Path,
    output_path: str | Path | None = None,
    *,
    genome_build: str = "GRCh38",
    cache_genome_build: str | None = None,
    pass_only: bool = True,
    max_records: int | None = None,
    max_evidence_per_allele: int = 20,
    progress_every: int | None = None,
    progress: Any = None,
    force: bool = False,
) -> dict[str, Any]:
    cache_build = cache_genome_build or genome_build
    lifter = None
    if cache_build != genome_build:
        # Sample is on one build but only the other build's ClinVar cache is
        # installed. Lift sample positions across so we can still surface
        # ClinVar evidence without requiring a second ~180 MB cache download.
        from ...runtime.liftover import get_liftover  # local import to keep evidence layer light

        lifter = get_liftover(genome_build, cache_build)
    vcf_path = Path(vcf_path)
    evidence_db = Path(evidence_db)
    if not vcf_path.exists():
        raise FileNotFoundError(vcf_path)
    if not evidence_db.exists():
        raise FileNotFoundError(evidence_db)

    output_path = Path(output_path) if output_path is not None else run_output_path(vcf_path, "clinvar.matches.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(f"{output_path}.genomi-manifest.json")
    with connect_evidence(evidence_db) as connection:
        _ensure_schema(connection)
        clinvar_identity = _clinvar_cache_identity(connection)
    cache_expected = {
        "step": "match_clinvar",
        "input_vcf": file_metadata(vcf_path),
        "evidence_db": str(evidence_db),
        "clinvar_evidence": clinvar_identity,
        "output": str(output_path),
        "genome_build": genome_build,
        "cache_genome_build": cache_build,
        "pass_only": pass_only,
        "max_records": max_records,
        "max_evidence_per_allele": max_evidence_per_allele,
    }
    if not force:
        cached = matching_manifest(manifest_path, cache_expected, required_paths=[output_path])
        if cached is not None:
            return {
                "status": "cached",
                "output": str(output_path),
                "manifest_path": str(manifest_path),
                "stats": cached["stats"],
                "evidence_context": evidence_context(
                    "static",
                    reason="ClinVar exact matches can be summarized and scanned into deterministic candidate inventory.",
                    commands=[
                        "genomi call clinvar.scan_candidates --params '{\"matches\":\"<clinvar.matches.jsonl>\"}'",
                    ],
                ),
            }

    scanned_records = 0
    skipped_non_pass = 0
    queried_alleles = 0
    matched_alleles = 0
    written_records = 0
    lifted_alleles = 0
    lift_dropped_alleles = 0
    created_at = utc_now()

    with connect_evidence(evidence_db) as connection, output_path.open("w", encoding="utf-8") as handle:
        _ensure_schema(connection)
        for record, sample_records in _iter_vcf_record_groups(vcf_path):
            if max_records is not None and scanned_records >= max_records:
                break
            scanned_records += 1

            if pass_only and not _is_passing_filter(record["filter"]):
                skipped_non_pass += 1
                continue

            for alt in record["alt"].split(","):
                if alt in ("", "."):
                    continue
                queried_alleles += 1
                query_chrom = record["chrom"]
                query_pos = int(record["pos"])
                lifted = None
                if lifter is not None:
                    lifted = lifter.lift_position_full(query_chrom, query_pos)
                    if lifted is None or lifted[2] != "+":
                        lift_dropped_alleles += 1
                        continue
                    lifted_alleles += 1
                    query_chrom = lifted[0]
                    query_pos = lifted[1]
                rows = _query_clinvar_exact_rows(
                    connection,
                    chrom=query_chrom,
                    pos=query_pos,
                    ref=record["ref"],
                    alt=alt,
                    genome_build=cache_build,
                    limit=max_evidence_per_allele,
                )
                if not rows:
                    continue

                matched_alleles += 1
                for sample_record in sample_records:
                    sample_fields = parse_sample(sample_record.get("format", ""), sample_record.get("sample", ""))
                    for row in rows:
                        payload: dict[str, Any] = {
                            "sample_variant": {
                                "chrom": record["chrom"],
                                "pos": int(record["pos"]),
                                "id": _none_if_dot(record["id"]),
                                "sample_index": sample_record.get("sample_index"),
                                "sample_name": sample_record.get("sample_name"),
                                "ref": record["ref"],
                                "alt": alt,
                                "qual": _none_if_dot(record["qual"]),
                                "filter": record["filter"],
                                "genotype": sample_fields.get("GT"),
                                "depth": sample_fields.get("DP"),
                                "genotype_quality": sample_fields.get("GQ"),
                                "genome_build": genome_build,
                            },
                            "clinvar": dict(row),
                        }
                        if lifter is not None:
                            payload["liftover"] = {
                                "source_build": genome_build,
                                "target_build": cache_build,
                                "lifted_chrom": query_chrom,
                                "lifted_pos": query_pos,
                                "chain": "UCSC pyliftover",
                            }
                        handle.write(json.dumps(payload, sort_keys=True) + "\n")
                        written_records += 1

            if progress_every is not None and progress is not None and scanned_records % progress_every == 0:
                progress(scanned_records, queried_alleles, matched_alleles)

    manifest = {
        "step": "match_clinvar",
        "created_at_utc": created_at,
        "input_vcf": file_metadata(vcf_path),
        "evidence_db": str(evidence_db),
        "clinvar_evidence": clinvar_identity,
        "output": str(output_path),
        "genome_build": genome_build,
        "cache_genome_build": cache_build,
        "pass_only": pass_only,
        "max_records": max_records,
        "max_evidence_per_allele": max_evidence_per_allele,
        "stats": {
            "scanned_records": scanned_records,
            "skipped_non_pass_records": skipped_non_pass,
            "queried_alleles": queried_alleles,
            "matched_alleles": matched_alleles,
            "written_records": written_records,
            "lifted_alleles": lifted_alleles,
            "lift_dropped_alleles": lift_dropped_alleles,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "status": "completed",
        "output": str(output_path),
        "manifest_path": str(manifest_path),
        "stats": manifest["stats"],
        "evidence_context": evidence_context(
            "static",
            reason="ClinVar exact matches can be summarized and scanned into deterministic candidate inventory.",
            commands=[
                "genomi call clinvar.scan_candidates --params '{\"matches\":\"<clinvar.matches.jsonl>\"}'",
            ],
        ),
    }


def match_clinvar_variants_from_active_genome_index(
    active_genome_index_path: str | Path,
    evidence_db: str | Path,
    output_path: str | Path,
    *,
    genome_build: str = "GRCh38",
    cache_genome_build: str | None = None,
    pass_only: bool = True,
    max_records: int | None = None,
    max_evidence_per_allele: int = 20,
    batch_size: int = 25_000,
    force: bool = False,
) -> dict[str, Any]:
    active_genome_index_path = Path(active_genome_index_path)
    evidence_db = Path(evidence_db)
    output_path = Path(output_path)
    if not active_genome_index_path.exists():
        raise FileNotFoundError(active_genome_index_path)
    if not evidence_db.exists():
        raise FileNotFoundError(evidence_db)
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    cache_build = cache_genome_build or genome_build
    cross_build = cache_build != genome_build

    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(f"{output_path}.genomi-manifest.json")
    with connect_evidence(evidence_db) as connection:
        _ensure_schema(connection)
        clinvar_identity = _clinvar_cache_identity(connection)
    cache_expected = {
        "step": "match_clinvar_from_active_genome_index",
        "input_active_genome_index": file_metadata(active_genome_index_path),
        "evidence_db": str(evidence_db),
        "clinvar_evidence": clinvar_identity,
        "output": str(output_path),
        "genome_build": genome_build,
        "cache_genome_build": cache_build,
        "pass_only": pass_only,
        "max_records": max_records,
        "max_evidence_per_allele": max_evidence_per_allele,
        "batch_size": batch_size,
    }
    if not force:
        cached = matching_manifest(manifest_path, cache_expected, required_paths=[output_path])
        if cached is not None:
            return {
                "status": "cached",
                "output": str(output_path),
                "manifest_path": str(manifest_path),
                "stats": cached["stats"],
                "evidence_context": evidence_context(
                    "static",
                    reason="Active Genome Index ClinVar exact matches can be summarized and scanned into deterministic candidate inventory.",
                    commands=[
                        "genomi call clinvar.scan_candidates --params '{\"matches\":\"<clinvar.matches.jsonl>\"}'"
                    ],
                ),
            }

    scanned_records = 0
    skipped_non_pass = 0
    queried_alleles = 0
    matched_alleles = 0
    written_records = 0
    lifted_alleles = 0
    lift_dropped_alleles = 0
    created_at = utc_now()
    with connect_evidence(evidence_db) as evidence_connection, output_path.open("w", encoding="utf-8") as handle:
        _ensure_schema(evidence_connection)
        evidence_connection.execute("attach database ? as sample_active_genome_index", (str(active_genome_index_path),))
        _ensure_active_genome_index_ready_for_clinvar_match(evidence_connection, active_genome_index_path)
        selection_params = (max_records,) if max_records is not None else ()
        stats_row = evidence_connection.execute(
            f"""
            {_selected_active_genome_index_records_cte_sql(pass_only=pass_only, max_records=max_records)}
            select
                count(*) as scanned_records,
                coalesce(
                    sum(
                        case
                            when alt is null or alt in ('', '.') then 0
                            else 1 + length(alt) - length(replace(alt, ',', ''))
                        end
                    ),
                    0
                ) as queried_alleles
            from selected_records
            """,
            selection_params,
        ).fetchone()
        scanned_records = int(stats_row["scanned_records"])
        queried_alleles = int(stats_row["queried_alleles"])

        if cross_build:
            lifted_alleles, lift_dropped_alleles = _populate_lifted_selected_active_genome_index_records_table(
                evidence_connection,
                source_build=genome_build,
                target_build=cache_build,
                pass_only=pass_only,
                max_records=max_records,
            )

        direct_stats = _write_clinvar_active_genome_index_direct_matches(
            evidence_connection,
            handle,
            pass_only=pass_only,
            max_records=max_records,
            genome_build=cache_build,
            max_evidence_per_allele=max_evidence_per_allele,
            cross_build=cross_build,
            sample_build=genome_build,
        )
        matched_alleles += direct_stats["matched_alleles"]
        written_records += direct_stats["written_records"]

    stats = {
        "scanned_records": scanned_records,
        "skipped_non_pass_records": skipped_non_pass,
        "queried_alleles": queried_alleles,
        "matched_alleles": matched_alleles,
        "written_records": written_records,
        "lifted_alleles": lifted_alleles,
        "lift_dropped_alleles": lift_dropped_alleles,
    }
    manifest = {
        **cache_expected,
        "created_at_utc": created_at,
        "output_metadata": file_metadata(output_path),
        "stats": stats,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "status": "completed",
        "input_active_genome_index": str(active_genome_index_path),
        "output": str(output_path),
        "manifest_path": str(manifest_path),
        "stats": stats,
        "clinvar_evidence": clinvar_identity,
        "evidence_context": evidence_context(
            "static",
            reason="Active Genome Index ClinVar exact matches can be summarized and scanned into deterministic candidate inventory.",
            commands=["genomi call clinvar.scan_candidates --params '{\"matches\":\"<clinvar.matches.jsonl>\"}'"],
        ),
    }


def _selected_active_genome_index_records_cte_sql(
    *,
    pass_only: bool,
    max_records: int | None,
    cross_build: bool = False,
) -> str:
    if cross_build:
        # Cross-build mode: chrom/pos in the CTE are already lifted into the
        # cache's build by _populate_lifted_selected_active_genome_index_records_table; the
        # original sample coordinates ride along as sample_chrom_original /
        # sample_pos_original so the writer can keep audit honest.
        return """
            with selected_records as (
                select record_rowid, chrom, chrom_sort, pos, rsid, ref, alt, qual, filter,
                       sample_index, sample_name, genotype, depth, genotype_quality,
                       sample_chrom_original, sample_pos_original
                from temp.lifted_selected_records
            )
        """
    sql = """
            with selected_records as (
                select rowid as record_rowid, chrom, chrom_sort, pos, rsid, ref, alt, qual, filter,
                       sample_index, sample_name, genotype, depth, genotype_quality
                from sample_active_genome_index.records
                where is_variant = 1
        """
    if pass_only:
        sql += " and filter in ('PASS', '.')"
    if max_records is not None:
        sql += " order by chrom_sort, pos, sample_index"
        sql += " limit ?"
    sql += ")"
    return sql


def _populate_lifted_selected_active_genome_index_records_table(
    connection: sqlite3.Connection,
    *,
    source_build: str,
    target_build: str,
    pass_only: bool,
    max_records: int | None,
) -> tuple[int, int]:
    """Stage sample variants into a temp table with lifted coordinates.

    The Active Genome Index SQL path joins sample variants against ClinVar rows
    via (chrom, pos, ref). When the sample is on a different build than the
    cache, lift the (chrom, pos) pairs in Python first and write the lifted
    coordinates into ``temp.lifted_selected_records`` so the rest of the JOIN
    plan can stay shape-identical. Each row also carries the original sample
    coordinates as ``sample_chrom_original`` /
    ``sample_pos_original`` so the match payload can disclose both the
    sample's native coordinate and the lifted lookup coordinate.
    """

    from ...runtime.liftover import get_liftover  # local import keeps evidence layer light

    lifter = get_liftover(source_build, target_build)
    connection.executescript(
        """
        drop table if exists temp.lifted_selected_records;
        create temp table lifted_selected_records (
            record_rowid integer not null,
            sample_chrom_original text not null,
            sample_pos_original integer not null,
            chrom text not null,
            chrom_sort integer,
            pos integer not null,
            rsid text,
            ref text,
            alt text,
            qual text,
            filter text,
            sample_index integer,
            sample_name text,
            genotype text,
            depth integer,
            genotype_quality integer
        );
        create index lifted_selected_records_locus_idx
            on lifted_selected_records(chrom, pos);
        """
    )
    selection_params = (max_records,) if max_records is not None else ()
    source_rows = connection.execute(
        f"""
        {_selected_active_genome_index_records_cte_sql(pass_only=pass_only, max_records=max_records)}
        select * from selected_records
        """,
        selection_params,
    ).fetchall()

    lifted = 0
    dropped = 0
    insert_buffer: list[tuple[Any, ...]] = []
    for row in source_rows:
        sample_chrom = row["chrom"]
        sample_pos = int(row["pos"])
        result = lifter.lift_position_full(sample_chrom, sample_pos)
        if result is None or result[2] != "+":
            dropped += 1
            continue
        lifted_chrom, lifted_pos, _strand = result
        insert_buffer.append(
            (
                int(row["record_rowid"]),
                sample_chrom,
                sample_pos,
                lifted_chrom,
                int(row["chrom_sort"]) if row["chrom_sort"] is not None else None,
                lifted_pos,
                row["rsid"],
                row["ref"],
                row["alt"],
                row["qual"],
                row["filter"],
                row["sample_index"],
                row["sample_name"],
                row["genotype"],
                row["depth"],
                row["genotype_quality"],
            )
        )
        lifted += 1
    if insert_buffer:
        connection.executemany(
            """
            insert into temp.lifted_selected_records (
                record_rowid, sample_chrom_original, sample_pos_original,
                chrom, chrom_sort, pos, rsid, ref, alt, qual, filter,
                sample_index, sample_name, genotype, depth, genotype_quality
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            insert_buffer,
        )
    return lifted, dropped


def _ensure_active_genome_index_ready_for_clinvar_match(connection: sqlite3.Connection, active_genome_index_path: Path) -> None:
    stats_count = connection.execute("select count(*) from sample_active_genome_index.stats").fetchone()[0]
    index_names = {
        str(row["name"])
        for row in connection.execute(
            """
            select name
            from sample_active_genome_index.sqlite_master
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
            f"Active Genome Index is incomplete for ClinVar refresh ({active_genome_index_path}): "
            f"{'; '.join(details)}. Rebuild the Active Genome Index from the source genome file once."
        )


def _write_clinvar_active_genome_index_direct_matches(
    connection: sqlite3.Connection,
    handle: Any,
    *,
    pass_only: bool,
    max_records: int | None,
    genome_build: str,
    max_evidence_per_allele: int,
    cross_build: bool = False,
    sample_build: str | None = None,
) -> dict[str, int]:
    source_selects: list[str] = []
    sample_chrom_style = _selected_active_genome_index_chrom_style(
        connection,
        pass_only=pass_only,
        max_records=max_records,
        cross_build=cross_build,
    )
    for table_name in _clinvar_index_source_tables(connection):
        clinvar_chrom_style = _clinvar_table_chrom_style(connection, table_name, genome_build)
        if clinvar_chrom_style == "empty":
            continue
        for mode in _chrom_match_modes(sample_chrom_style, clinvar_chrom_style):
            chrom_expression = _chrom_match_expression(mode)
            extra_where = "cv.chrom <> r.chrom" if mode == "complement" else None
            source_selects.append(
                _clinvar_index_direct_select_sql(
                    table_name,
                    chrom_expression=chrom_expression,
                    extra_where=extra_where,
                    multiallelic=False,
                    cross_build=cross_build,
                )
            )
            source_selects.append(
                _clinvar_index_direct_select_sql(
                    table_name,
                    chrom_expression=chrom_expression,
                    extra_where=extra_where,
                    multiallelic=True,
                    cross_build=cross_build,
                )
            )
    if not source_selects:
        return {"matched_alleles": 0, "written_records": 0}
    joined_sql = "\nunion all\n".join(source_selects)
    if cross_build:
        # The cross-build CTE reads from a pre-populated temp table that
        # ignores pass_only / max_records; those were already applied while
        # staging the lifted rows.
        selection_params: tuple[Any, ...] = ()
    else:
        selection_params = (max_records,) if max_records is not None else ()
    rows = connection.execute(
        f"""
        {_selected_active_genome_index_records_cte_sql(pass_only=pass_only, max_records=max_records, cross_build=cross_build)},
        clinvar_joined as (
            {joined_sql}
        ),
        ranked as (
            select
                row_number() over (
                    partition by batch_id
                    order by imported_at desc, clinvar_id, allele_id
                ) as evidence_rank,
                *
            from clinvar_joined
        )
        select *
        from ranked
        where evidence_rank <= ?
        order by batch_id, evidence_rank
        """,
        (
            *selection_params,
            *([genome_build] * len(source_selects)),
            max_evidence_per_allele,
        ),
    )
    return _write_clinvar_match_rows(
        handle,
        rows,
        sample_build=sample_build,
        cache_build=genome_build if cross_build else None,
    )


def _clinvar_index_source_tables(connection: sqlite3.Connection) -> list[str]:
    tables = []
    if _table_has_rows(connection, "main.clinvar_variants"):
        tables.append("main.clinvar_variants")
    if _has_attached_shared_evidence(connection) and _attached_table_exists(connection, "clinvar_variants"):
        shared_table = f"{SHARED_EVIDENCE_ALIAS}.clinvar_variants"
        if _table_has_rows(connection, shared_table):
            tables.append(shared_table)
    return tables


def _table_has_rows(connection: sqlite3.Connection, table_name: str) -> bool:
    return connection.execute(f"select 1 from {table_name} limit 1").fetchone() is not None


def _selected_active_genome_index_chrom_style(
    connection: sqlite3.Connection,
    *,
    pass_only: bool,
    max_records: int | None,
    cross_build: bool = False,
) -> str:
    selection_params: tuple[Any, ...] = (
        () if cross_build else ((max_records,) if max_records is not None else ())
    )
    row = connection.execute(
        f"""
        {_selected_active_genome_index_records_cte_sql(pass_only=pass_only, max_records=max_records, cross_build=cross_build)}
        select
            coalesce(sum(case when chrom like 'chr%' then 1 else 0 end), 0) as chr_rows,
            count(*) as total_rows
        from selected_records
        """,
        selection_params,
    ).fetchone()
    return _chrom_style_from_counts(int(row["chr_rows"]), int(row["total_rows"]))


def _clinvar_table_chrom_style(connection: sqlite3.Connection, table_name: str, genome_build: str) -> str:
    row = connection.execute(
        f"""
        select
            coalesce(sum(case when chrom like 'chr%' then 1 else 0 end), 0) as chr_rows,
            count(*) as total_rows
        from {table_name}
        where genome_build = ?
        """,
        (genome_build,),
    ).fetchone()
    return _chrom_style_from_counts(int(row["chr_rows"]), int(row["total_rows"]))


def _chrom_style_from_counts(chr_rows: int, total_rows: int) -> str:
    if total_rows <= 0:
        return "empty"
    if chr_rows <= 0:
        return "bare"
    if chr_rows == total_rows:
        return "chr"
    return "mixed"


def _chrom_match_modes(sample_chrom_style: str, clinvar_chrom_style: str) -> list[str]:
    if sample_chrom_style in ("empty", "mixed") or clinvar_chrom_style == "mixed":
        return ["original", "complement"]
    if sample_chrom_style == clinvar_chrom_style:
        return ["original"]
    return ["complement"]


def _chrom_match_expression(mode: str) -> str:
    if mode == "original":
        return "r.chrom"
    if mode == "complement":
        return "case when substr(r.chrom, 1, 3) = 'chr' then substr(r.chrom, 4) else 'chr' || r.chrom end"
    raise ValueError(f"unknown chromosome match mode: {mode}")


def _clinvar_index_direct_select_sql(
    table_name: str,
    *,
    chrom_expression: str,
    extra_where: str | None = None,
    multiallelic: bool,
    cross_build: bool = False,
) -> str:
    batch_id = "cast(r.record_rowid as text)"
    sample_alt = "r.alt"
    alt_where = "and r.alt not in ('', '.') and instr(r.alt, ',') = 0 and cv.alt = r.alt"
    if multiallelic:
        batch_id = "cast(r.record_rowid as text) || ':' || cv.alt"
        sample_alt = "cv.alt"
        alt_where = "and instr(r.alt, ',') > 0 and instr(',' || r.alt || ',', ',' || cv.alt || ',') > 0"
    where = f"""
              and cv.chrom = {chrom_expression}
              and cv.pos = r.pos
              and cv.ref = r.ref
              and cv.genome_build = ?
        """
    if extra_where is not None:
        where += f" and {extra_where}"
    if cross_build:
        # In cross-build mode r.chrom / r.pos are the lifted coords (used by
        # the JOIN); the sample's native coords ride along on
        # sample_chrom_original / sample_pos_original.
        sample_chrom_select = "r.sample_chrom_original as sample_chrom"
        sample_pos_select = "r.sample_pos_original as sample_pos"
        lifted_columns_select = (
            ", r.chrom as lifted_chrom, r.pos as lifted_pos"
        )
    else:
        sample_chrom_select = "r.chrom as sample_chrom"
        sample_pos_select = "r.pos as sample_pos"
        lifted_columns_select = ", null as lifted_chrom, null as lifted_pos"
    return f"""
            select
                {batch_id} as batch_id,
                {sample_chrom_select},
                {sample_pos_select},
                r.rsid as sample_rsid,
                r.ref as sample_ref,
                {sample_alt} as sample_alt,
                r.qual as sample_qual,
                r.filter as sample_filter,
                r.sample_index as sample_index,
                r.sample_name as sample_name,
                r.genotype as genotype,
                r.depth as depth,
                r.genotype_quality as genotype_quality,
                cv.chrom as chrom,
                cv.pos as pos,
                cv.ref as ref,
                cv.alt as alt,
                cv.genome_build as genome_build,
                cv.clinvar_id as clinvar_id,
                cv.allele_id as allele_id,
                cv.clinical_significance as clinical_significance,
                cv.review_status as review_status,
                cv.conditions as conditions,
                cv.gene_info as gene_info,
                cv.hgvs as hgvs,
                cv.source_path as source_path,
                cv.source_version as source_version,
                cv.imported_at as imported_at
                {lifted_columns_select}
            from selected_records r
            cross join {table_name} as cv indexed by clinvar_variant_idx
            where 1 = 1
              {alt_where}
              {where}
        """


def _create_clinvar_query_table(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        create temp table if not exists clinvar_query_alleles (
            batch_id integer not null,
            lookup_chrom text not null,
            chrom text not null,
            pos integer not null,
            rsid text,
            ref text not null,
            alt text not null,
            qual text,
            filter text not null,
            sample_index integer,
            sample_name text,
            genotype text,
            depth integer,
            genotype_quality integer
        );
        create index if not exists clinvar_query_alleles_lookup_idx
            on clinvar_query_alleles(lookup_chrom, pos, ref, alt);
        """
    )


def _write_clinvar_index_match_batch(
    connection: sqlite3.Connection,
    handle: Any,
    batch: list[tuple[Any, ...]],
    *,
    genome_build: str,
    max_evidence_per_allele: int,
) -> dict[str, int]:
    connection.execute("delete from clinvar_query_alleles")
    connection.executemany(
        """
        insert into clinvar_query_alleles(
            batch_id, lookup_chrom, chrom, pos, rsid, ref, alt, qual, filter,
            sample_index, sample_name, genotype, depth, genotype_quality
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        batch,
    )
    source_selects = [
        _clinvar_index_match_select_sql(table_name)
        for table_name in _clinvar_index_source_tables(connection)
    ]
    if not source_selects:
        return {"matched_alleles": 0, "written_records": 0}
    joined_sql = "\nunion all\n".join(source_selects)
    rows = connection.execute(
        f"""
        with clinvar_joined as (
            {joined_sql}
        ),
        ranked as (
            select
                row_number() over (
                    partition by batch_id
                    order by imported_at desc, clinvar_id, allele_id
                ) as evidence_rank,
                *
            from clinvar_joined
        )
        select *
        from ranked
        where evidence_rank <= ?
        order by batch_id, evidence_rank
        """,
        (*([genome_build] * len(source_selects)), max_evidence_per_allele),
    )
    return _write_clinvar_match_rows(handle, rows)


def _write_clinvar_match_rows(
    handle: Any,
    rows: Iterable[sqlite3.Row],
    *,
    sample_build: str | None = None,
    cache_build: str | None = None,
) -> dict[str, int]:
    matched_batch_ids: set[str] = set()
    written_records = 0
    clinvar_fields = (
        "chrom",
        "pos",
        "ref",
        "alt",
        "genome_build",
        "clinvar_id",
        "allele_id",
        "clinical_significance",
        "review_status",
        "conditions",
        "gene_info",
        "hgvs",
        "source_path",
        "source_version",
        "imported_at",
    )
    row_keys: set[str] | None = None
    for row in rows:
        if row_keys is None:
            row_keys = set(row.keys())
        batch_id = str(row["batch_id"])
        matched_batch_ids.add(batch_id)
        sample_variant: dict[str, Any] = {
            "chrom": row["sample_chrom"],
            "pos": int(row["sample_pos"]),
            "id": row["sample_rsid"],
            "sample_index": row["sample_index"],
            "sample_name": row["sample_name"],
            "ref": row["sample_ref"],
            "alt": row["sample_alt"],
            "qual": row["sample_qual"],
            "filter": row["sample_filter"],
            "genotype": row["genotype"],
            "depth": row["depth"],
            "genotype_quality": row["genotype_quality"],
        }
        if sample_build is not None:
            sample_variant["genome_build"] = sample_build
        payload: dict[str, Any] = {
            "sample_variant": sample_variant,
            "clinvar": {field: row[field] for field in clinvar_fields},
        }
        if (
            cache_build is not None
            and "lifted_chrom" in row_keys
            and row["lifted_chrom"] is not None
            and row["lifted_pos"] is not None
        ):
            payload["liftover"] = {
                "source_build": sample_build,
                "target_build": cache_build,
                "lifted_chrom": row["lifted_chrom"],
                "lifted_pos": int(row["lifted_pos"]),
                "chain": "UCSC pyliftover",
            }
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        written_records += 1

    return {
        "matched_alleles": len(matched_batch_ids),
        "written_records": written_records,
    }


def _clinvar_index_match_select_sql(table_name: str) -> str:
    return f"""
            select
                q.batch_id as batch_id,
                q.chrom as sample_chrom,
                q.pos as sample_pos,
                q.rsid as sample_rsid,
                q.ref as sample_ref,
                q.alt as sample_alt,
                q.qual as sample_qual,
                q.filter as sample_filter,
                q.sample_index as sample_index,
                q.sample_name as sample_name,
                q.genotype as genotype,
                q.depth as depth,
                q.genotype_quality as genotype_quality,
                cv.chrom as chrom,
                cv.pos as pos,
                cv.ref as ref,
                cv.alt as alt,
                cv.genome_build as genome_build,
                cv.clinvar_id as clinvar_id,
                cv.allele_id as allele_id,
                cv.clinical_significance as clinical_significance,
                cv.review_status as review_status,
                cv.conditions as conditions,
                cv.gene_info as gene_info,
                cv.hgvs as hgvs,
                cv.source_path as source_path,
                cv.source_version as source_version,
                cv.imported_at as imported_at
            from clinvar_query_alleles q
            cross join {table_name} as cv indexed by clinvar_variant_idx
            where cv.chrom = q.lookup_chrom
              and cv.pos = q.pos
              and cv.ref = q.ref
              and cv.alt = q.alt
              and cv.genome_build = ?
        """
