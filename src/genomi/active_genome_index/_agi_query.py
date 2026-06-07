from __future__ import annotations

from .vcf import parse_info
from .vcf import parse_sample
from collections.abc import Iterable
from pathlib import Path
from typing import Any
import json
import sqlite3
from ._agi_readiness import ensure_active_genome_index_complete
from ._agi_schema import connect_existing_readonly
from .filtering import is_passing_filter, passing_filter_sql
from .record_kinds import is_reference_block_record


def query_rsid(agi_path: str | Path, rsid: str, *, limit: int = 50) -> list[dict[str, Any]]:
    return query_rsid_filtered(agi_path, rsid, limit=limit, pass_only=False)

def query_rsid_filtered(
    agi_path: str | Path,
    rsid: str,
    *,
    limit: int = 50,
    pass_only: bool = False,
) -> list[dict[str, Any]]:
    agi_path = Path(agi_path)
    sql = "select offset, sample_index from records where rsid = ?"
    params: list[Any] = [rsid]
    if pass_only:
        sql += f" and {passing_filter_sql()}"
    sql += " order by chrom_sort, pos limit ?"
    params.append(limit)
    return _query_offsets(agi_path, sql, params)

def query_variant(
    agi_path: str | Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    limit: int = 50,
    pass_only: bool = False,
) -> list[dict[str, Any]]:
    agi_path = Path(agi_path)
    chrom_values = _chrom_query_values(chrom)
    chrom_placeholders = ", ".join("?" for _ in chrom_values)
    sql = """
        select offset, sample_index from records
        where chrom in ({chrom_placeholders}) and pos = ? and ref = ? and alt = ? and is_variant = 1
    """.format(chrom_placeholders=chrom_placeholders)
    params: list[Any] = [*chrom_values, pos, ref, alt]
    if pass_only:
        sql += f" and {passing_filter_sql()}"
    sql += " order by chrom_sort, pos limit ?"
    params.append(limit)
    return _query_offsets(agi_path, sql, params)

def query_region(
    agi_path: str | Path,
    chrom: str,
    start: int,
    end: int,
    *,
    variants_only: bool = False,
    pass_only: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    agi_path = Path(agi_path)
    ensure_active_genome_index_complete(agi_path)
    chrom_values = _chrom_query_values(chrom)
    if start == end:
        return _query_point_region(
            agi_path,
            chrom_values,
            start,
            variants_only=variants_only,
            pass_only=pass_only,
            limit=limit,
        )
    chrom_placeholders = ", ".join("?" for _ in chrom_values)
    sql = """
        select offset, sample_index from records
        where chrom in ({chrom_placeholders}) and pos <= ? and end >= ?
    """.format(chrom_placeholders=chrom_placeholders)
    params: list[Any] = [*chrom_values, end, start]
    if variants_only:
        sql += " and is_variant = 1"
    if pass_only:
        sql += f" and {passing_filter_sql()}"
    sql += " order by chrom_sort, pos limit ?"
    params.append(limit)
    return _query_offsets(agi_path, sql, params)

def coverage_query(
    agi_path: str | Path,
    chrom: str,
    start: int,
    end: int,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    records = query_region(agi_path, chrom, start, end, variants_only=False, limit=limit)
    covered_segments: list[tuple[int, int]] = []
    for record in records:
        if not is_passing_filter(record.get("filter")) or not is_reference_block_record(record):
            continue
        segment_start = max(start, int(record["pos"]))
        segment_end = min(end, int(record["end"]))
        if segment_start <= segment_end:
            covered_segments.append((segment_start, segment_end))
    merged = _merge_segments(covered_segments)
    covered_bases = sum(segment_end - segment_start + 1 for segment_start, segment_end in merged)
    requested_bases = end - start + 1
    result: dict[str, Any] = {
        "chrom": chrom,
        "start": start,
        "end": end,
        "requested_bases": requested_bases,
        "covered_bases": covered_bases,
        "covered_fraction": covered_bases / requested_bases if requested_bases else 0,
        "segments": [{"start": left, "end": right} for left, right in merged],
        "records": records,
        "truncated": len(records) >= limit,
    }
    # reference_pending is stamped once, centrally, by the dispatch chokepoint
    # (operations.registry.table) for reference-dependent operations — not here,
    # so there is a single source of truth.
    return result

def _query_offsets(
    agi_path: str | Path,
    sql: str,
    params: Iterable[Any],
) -> list[dict[str, Any]]:
    ensure_active_genome_index_complete(agi_path)
    with connect_existing_readonly(agi_path) as connection:
        offsets = [
            (int(row["offset"]), _row_sample_index(row))
            for row in _execute_offset_query(connection, sql, params)
        ]
    return _records_from_active_genome_index_offsets(agi_path, offsets)

def _query_point_region(
    agi_path: Path,
    chrom_values: list[str],
    pos: int,
    *,
    variants_only: bool,
    pass_only: bool,
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []

    chrom_placeholders = ", ".join("?" for _ in chrom_values)
    exact_sql = """
        select offset, sample_index, chrom_sort, pos, end
        from records
        where chrom in ({chrom_placeholders}) and pos = ?
    """.format(chrom_placeholders=chrom_placeholders)
    exact_params: list[Any] = [*chrom_values, pos]
    if variants_only:
        exact_sql += " and is_variant = 1"
    if pass_only:
        exact_sql += f" and {passing_filter_sql()}"
    exact_sql += " order by chrom_sort, pos limit ?"
    exact_params.append(limit)

    offset_rows: list[tuple[int, int, int, int, int]] = []
    with connect_existing_readonly(agi_path) as connection:
        offset_rows.extend(_offset_rows(_execute_offset_query(connection, exact_sql, exact_params)))
        remaining = limit - len(offset_rows)
        if remaining > 0:
            offset_rows.extend(
                _point_spanning_offset_rows(
                    connection,
                    chrom_values,
                    pos,
                    variants_only=variants_only,
                    pass_only=pass_only,
                    limit=remaining,
                )
            )

    offset_rows = _dedupe_offset_rows(offset_rows)
    offset_rows.sort(key=lambda item: (item[2], item[3], item[0], item[1]))
    return _records_from_active_genome_index_offsets(
        agi_path,
        [(offset, sample_index) for offset, sample_index, _chrom_sort_value, _pos, _end in offset_rows[:limit]],
    )

def _point_spanning_offset_rows(
    connection: sqlite3.Connection,
    chrom_values: list[str],
    pos: int,
    *,
    variants_only: bool,
    pass_only: bool,
    limit: int,
) -> list[tuple[int, int, int, int, int]]:
    rows = _point_spanning_offset_rows_from_spans(
        connection,
        chrom_values,
        pos,
        variants_only=variants_only,
        pass_only=pass_only,
        limit=limit,
    )
    if rows is not None:
        return rows
    return _point_spanning_offset_rows_from_records(
        connection,
        chrom_values,
        pos,
        variants_only=variants_only,
        pass_only=pass_only,
        limit=limit,
    )

def _point_spanning_offset_rows_from_spans(
    connection: sqlite3.Connection,
    chrom_values: list[str],
    pos: int,
    *,
    variants_only: bool,
    pass_only: bool,
    limit: int,
) -> list[tuple[int, int, int, int, int]] | None:
    chrom_placeholders = ", ".join("?" for _ in chrom_values)
    sql = """
        select r.offset, r.sample_index, r.chrom_sort, r.pos, r.end
        from spans s
        join records r on r.offset = s.offset and r.sample_index = s.sample_index
        where s.chrom in ({chrom_placeholders}) and s.pos < ? and s.end >= ?
    """.format(chrom_placeholders=chrom_placeholders)
    params: list[Any] = [*chrom_values, pos, pos]
    if variants_only:
        sql += " and r.is_variant = 1"
    if pass_only:
        sql += f" and {passing_filter_sql('r.filter')}"
    sql += " order by s.pos desc limit ?"
    params.append(limit)
    try:
        return _offset_rows(_execute_offset_query(connection, sql, params))
    except sqlite3.OperationalError as exc:
        if "no such table: spans" in str(exc):
            return None
        raise

def _point_spanning_offset_rows_from_records(
    connection: sqlite3.Connection,
    chrom_values: list[str],
    pos: int,
    *,
    variants_only: bool,
    pass_only: bool,
    limit: int,
) -> list[tuple[int, int, int, int, int]]:
    chrom_placeholders = ", ".join("?" for _ in chrom_values)
    covering_sql = """
        select offset, sample_index, chrom_sort, pos, end
        from records
        where chrom in ({chrom_placeholders}) and pos < ?
    """.format(chrom_placeholders=chrom_placeholders)
    covering_params: list[Any] = [*chrom_values, pos]
    if variants_only:
        covering_sql += " and is_variant = 1"
    if pass_only:
        covering_sql += f" and {passing_filter_sql()}"
    covering_sql += " order by pos desc limit ?"
    covering_params.append(max(limit, 25))
    return [
        row
        for row in _offset_rows(_execute_offset_query(connection, covering_sql, covering_params))
        if row[4] >= pos
    ][:limit]

def _offset_rows(rows: Iterable[sqlite3.Row]) -> list[tuple[int, int, int, int, int]]:
    return [
        (
            int(row["offset"]),
            _row_sample_index(row),
            int(row["chrom_sort"]),
            int(row["pos"]),
            int(row["end"]),
        )
        for row in rows
    ]

def _execute_offset_query(
    connection: sqlite3.Connection,
    sql: str,
    params: Iterable[Any],
) -> list[sqlite3.Row]:
    try:
        return list(connection.execute(sql, tuple(params)))
    except sqlite3.OperationalError as exc:
        if "sample_index" not in str(exc):
            raise
        return list(connection.execute(sql.replace(", sample_index", ""), tuple(params)))


def _chrom_query_values(chrom: str) -> list[str]:
    value = str(chrom)
    aliases = [value]
    if value.startswith("chr"):
        bare = value[3:]
        aliases.append("MT" if bare == "M" else bare)
    else:
        aliases.append("chrM" if value == "MT" else f"chr{value}")
    if value == "M":
        aliases.extend(["MT", "chrM"])
    return list(dict.fromkeys(aliases))


def _dedupe_offset_rows(offset_rows: list[tuple[int, int, int, int, int]]) -> list[tuple[int, int, int, int, int]]:
    seen: set[tuple[int, int]] = set()
    output = []
    for row in offset_rows:
        key = (row[0], row[1])
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output

def _records_from_active_genome_index_offsets(agi_path: str | Path, offsets: Iterable[tuple[int, int]]) -> list[dict[str, Any]]:
    records = []
    with connect_existing_readonly(agi_path) as connection:
        for offset, sample_index in offsets:
            row = connection.execute(
                """
                select *
                from records
                where offset = ? and sample_index = ?
                limit 1
                """,
                (offset, sample_index),
            ).fetchone()
            if row is not None:
                records.append(_index_record_to_dict(row))
    return records

def _index_record_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    ref = None if row["ref"] == "." else row["ref"]
    alt = None if row["alt"] == "." else row["alt"]
    info_genes = _json_list(row["info_genes"]) if _row_has_key(row, "info_genes") else []
    info_raw = row["info"] if _row_has_key(row, "info") else ""
    format_raw = row["format"] if _row_has_key(row, "format") else ""
    sample_raw = row["sample"] if _row_has_key(row, "sample") else ""
    payload: dict[str, Any] = {
        "chrom": row["chrom"],
        "pos": int(row["pos"]),
        "end": int(row["end"]),
        "id": row["rsid"],
        "rsid": row["rsid"],
        "ref": ref,
        "alt": alt,
        "alts": [value for value in str(alt or "").split(",") if value],
        "qual": None if row["qual"] == "." else row["qual"],
        "filter": row["filter"],
        "is_variant": bool(row["is_variant"]),
        "record_kind": str(row["record_kind"]),
        "observed_alleles": _json_list(row["observed_alleles"]),
        "sample_name": row["sample_name"] if _row_has_key(row, "sample_name") else None,
        "sample_index": _row_sample_index(row),
        "genotype": row["genotype"],
        "depth": row["depth"],
        "genotype_quality": row["genotype_quality"],
        "sample": parse_sample(str(format_raw or ""), str(sample_raw or "")),
        "sample_raw": sample_raw,
        "info": parse_info(str(info_raw or "")),
        "info_raw": info_raw,
        "format": str(format_raw or "").split(":") if format_raw else [],
        "format_raw": format_raw,
        "info_genes": info_genes,
        "variant_key": f"{row['chrom']}:{row['pos']}:{row['ref']}:{row['alt']}",
        "offset": int(row["offset"]),
        "line_length": int(row["line_length"]),
    }
    return payload

def _row_has_key(row: sqlite3.Row, key: str) -> bool:
    return key in row.keys()  # noqa: SIM118 — sqlite3.Row iteration yields values, .keys() yields column names

def _json_list(value: Any) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _row_sample_index(row: sqlite3.Row) -> int:
    try:
        return int(row["sample_index"] or 0)
    except (IndexError, KeyError, TypeError, ValueError):
        return 0

def _merge_segments(segments: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not segments:
        return []
    segments = sorted(segments)
    merged = [segments[0]]
    for start, end in segments[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 1:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged
