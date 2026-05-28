from __future__ import annotations

from .vcf import parse_info
from .vcf import parse_sample
from collections.abc import Iterable
from pathlib import Path
from typing import Any
import json
import sqlite3
from ._agi_readiness import ensure_active_genome_index_complete
from ._agi_schema import connect_existing_readonly, default_active_genome_index_path


def query_rsid(vcf_path: str | Path, rsid: str, active_genome_index_path: str | Path | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    active_genome_index_path = Path(active_genome_index_path) if active_genome_index_path is not None else default_active_genome_index_path(vcf_path)
    return query_rsid_filtered(vcf_path, rsid, active_genome_index_path, limit=limit, pass_only=False)

def query_rsid_filtered(
    vcf_path: str | Path,
    rsid: str,
    active_genome_index_path: str | Path | None = None,
    *,
    limit: int = 50,
    pass_only: bool = False,
) -> list[dict[str, Any]]:
    active_genome_index_path = Path(active_genome_index_path) if active_genome_index_path is not None else default_active_genome_index_path(vcf_path)
    sql = "select offset, sample_index from records where rsid = ?"
    params: list[Any] = [rsid]
    if pass_only:
        sql += " and filter = 'PASS'"
    sql += " order by chrom_sort, pos limit ?"
    params.append(limit)
    return _query_offsets(vcf_path, active_genome_index_path, sql, params)

def query_variant(
    vcf_path: str | Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    active_genome_index_path: str | Path | None = None,
    *,
    limit: int = 50,
    pass_only: bool = False,
) -> list[dict[str, Any]]:
    active_genome_index_path = Path(active_genome_index_path) if active_genome_index_path is not None else default_active_genome_index_path(vcf_path)
    sql = """
        select offset, sample_index from records
        where chrom = ? and pos = ? and ref = ? and alt = ?
    """
    params: list[Any] = [chrom, pos, ref, alt]
    if pass_only:
        sql += " and filter = 'PASS'"
    sql += " order by chrom_sort, pos limit ?"
    params.append(limit)
    return _query_offsets(vcf_path, active_genome_index_path, sql, params)

def query_region(
    vcf_path: str | Path,
    chrom: str,
    start: int,
    end: int,
    active_genome_index_path: str | Path | None = None,
    *,
    variants_only: bool = False,
    pass_only: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    active_genome_index_path = Path(active_genome_index_path) if active_genome_index_path is not None else default_active_genome_index_path(vcf_path)
    if start == end:
        return _query_point_region(
            vcf_path,
            active_genome_index_path,
            chrom,
            start,
            variants_only=variants_only,
            pass_only=pass_only,
            limit=limit,
        )
    sql = """
        select offset, sample_index from records
        where chrom = ? and pos <= ? and end >= ?
    """
    params: list[Any] = [chrom, end, start]
    if variants_only:
        sql += " and is_variant = 1"
    if pass_only:
        sql += " and filter = 'PASS'"
    sql += " order by chrom_sort, pos limit ?"
    params.append(limit)
    return _query_offsets(vcf_path, active_genome_index_path, sql, params)

def coverage_query(
    vcf_path: str | Path,
    chrom: str,
    start: int,
    end: int,
    active_genome_index_path: str | Path | None = None,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    records = query_region(vcf_path, chrom, start, end, active_genome_index_path, variants_only=False, limit=limit)
    covered_segments: list[tuple[int, int]] = []
    for record in records:
        if record["filter"] != "PASS":
            continue
        segment_start = max(start, int(record["pos"]))
        segment_end = min(end, int(record["end"]))
        if segment_start <= segment_end:
            covered_segments.append((segment_start, segment_end))
    merged = _merge_segments(covered_segments)
    covered_bases = sum(segment_end - segment_start + 1 for segment_start, segment_end in merged)
    requested_bases = end - start + 1
    return {
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

def _query_offsets(
    vcf_path: str | Path,
    active_genome_index_path: str | Path,
    sql: str,
    params: Iterable[Any],
) -> list[dict[str, Any]]:
    ensure_active_genome_index_complete(active_genome_index_path)
    with connect_existing_readonly(active_genome_index_path) as connection:
        offsets = [
            (int(row["offset"]), _row_sample_index(row))
            for row in _execute_offset_query(connection, sql, params)
        ]
    return _records_from_active_genome_index_offsets(active_genome_index_path, offsets)

def _query_point_region(
    vcf_path: str | Path,
    active_genome_index_path: Path,
    chrom: str,
    pos: int,
    *,
    variants_only: bool,
    pass_only: bool,
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []

    exact_sql = """
        select offset, sample_index, chrom_sort, pos, end
        from records
        where chrom = ? and pos = ?
    """
    exact_params: list[Any] = [chrom, pos]
    if variants_only:
        exact_sql += " and is_variant = 1"
    if pass_only:
        exact_sql += " and filter = 'PASS'"
    exact_sql += " order by chrom_sort, pos limit ?"
    exact_params.append(limit)

    offset_rows: list[tuple[int, int, int, int, int]] = []
    with connect_existing_readonly(active_genome_index_path) as connection:
        offset_rows.extend(_offset_rows(_execute_offset_query(connection, exact_sql, exact_params)))
        remaining = limit - len(offset_rows)
        if remaining > 0:
            offset_rows.extend(
                _point_spanning_offset_rows(
                    connection,
                    chrom,
                    pos,
                    variants_only=variants_only,
                    pass_only=pass_only,
                    limit=remaining,
                )
            )

    offset_rows = _dedupe_offset_rows(offset_rows)
    offset_rows.sort(key=lambda item: (item[2], item[3], item[0], item[1]))
    return _records_from_active_genome_index_offsets(
        active_genome_index_path,
        [(offset, sample_index) for offset, sample_index, _chrom_sort_value, _pos, _end in offset_rows[:limit]],
    )

def _point_spanning_offset_rows(
    connection: sqlite3.Connection,
    chrom: str,
    pos: int,
    *,
    variants_only: bool,
    pass_only: bool,
    limit: int,
) -> list[tuple[int, int, int, int, int]]:
    rows = _point_spanning_offset_rows_from_spans(
        connection,
        chrom,
        pos,
        variants_only=variants_only,
        pass_only=pass_only,
        limit=limit,
    )
    if rows is not None:
        return rows
    return _point_spanning_offset_rows_from_records(
        connection,
        chrom,
        pos,
        variants_only=variants_only,
        pass_only=pass_only,
        limit=limit,
    )

def _point_spanning_offset_rows_from_spans(
    connection: sqlite3.Connection,
    chrom: str,
    pos: int,
    *,
    variants_only: bool,
    pass_only: bool,
    limit: int,
) -> list[tuple[int, int, int, int, int]] | None:
    sql = """
        select r.offset, r.sample_index, r.chrom_sort, r.pos, r.end
        from spans s
        join records r on r.offset = s.offset and r.sample_index = s.sample_index
        where s.chrom = ? and s.pos < ? and s.end >= ?
    """
    params: list[Any] = [chrom, pos, pos]
    if variants_only:
        sql += " and r.is_variant = 1"
    if pass_only:
        sql += " and r.filter = 'PASS'"
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
    chrom: str,
    pos: int,
    *,
    variants_only: bool,
    pass_only: bool,
    limit: int,
) -> list[tuple[int, int, int, int, int]]:
    covering_sql = """
        select offset, sample_index, chrom_sort, pos, end
        from records
        where chrom = ? and pos < ?
    """
    covering_params: list[Any] = [chrom, pos]
    if variants_only:
        covering_sql += " and is_variant = 1"
    if pass_only:
        covering_sql += " and filter = 'PASS'"
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

def _records_from_active_genome_index_offsets(active_genome_index_path: str | Path, offsets: Iterable[tuple[int, int]]) -> list[dict[str, Any]]:
    records = []
    with connect_existing_readonly(active_genome_index_path) as connection:
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
        "ref": row["ref"],
        "alt": alt,
        "alts": [value for value in str(alt or "").split(",") if value],
        "qual": None if row["qual"] == "." else row["qual"],
        "filter": row["filter"],
        "is_variant": bool(row["is_variant"]),
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
    except json.JSONDecodeError:
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
