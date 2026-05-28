from __future__ import annotations

import csv
import gzip
import re
import urllib.error
import urllib.parse
from collections.abc import Iterable
from typing import Any

from .client import _call_fetch_bytes
from .text_utils import (
    _clean_text,
    _flatten_strings,
    _https_url,
    _normalize_genes,
    _table_key,
    _value_supported_by_text,
)

_URL_RE = re.compile(r"(?:https?|ftp)://[^\s\"'<>]+", flags=re.I)
_HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']", flags=re.I)
_GENE_SPLIT_RE = re.compile(r"[,;|/ ]+")
_TEXT_TABLE_SUFFIXES = (
    ".txt",
    ".txt.gz",
    ".tsv",
    ".tsv.gz",
    ".tab",
    ".tab.gz",
    ".csv",
    ".csv.gz",
    ".soft",
    ".soft.gz",
)
_RAW_OR_BINARY_SUFFIXES = (
    ".tar",
    ".tar.gz",
    ".tgz",
    ".zip",
    ".rar",
    ".7z",
    ".cel",
    ".cel.gz",
    ".fastq",
    ".fastq.gz",
    ".fq",
    ".fq.gz",
    ".bam",
    ".sam",
    ".cram",
    ".sra",
    ".idat",
    ".idat.gz",
    ".tif",
    ".tiff",
    ".jpg",
    ".jpeg",
    ".png",
    ".xlsx",
    ".xls",
)
_GENE_COLUMN_ALIASES = (
    "gene",
    "genes",
    "symbol",
    "gene symbol",
    "gene_symbol",
    "official symbol",
    "official_symbol",
    "target",
    "target gene",
    "target_gene",
    "target gene symbol",
    "target_gene_symbol",
)
_FIELD_ALIASES = {
    "organism": ("organism", "species", "taxon"),
    "cell_line": ("cell_line", "cell line", "cell", "model", "cellline"),
    "perturbation": ("perturbation", "treatment", "condition", "library", "library_methodology"),
    "assay": ("assay", "screen", "readout", "method"),
    "phenotype": ("phenotype", "trait", "effect", "readout", "endpoint"),
}


def _consider_download_candidate(
    candidate: dict[str, Any],
    *,
    query: dict[str, Any],
    hit: dict[str, Any],
    genes: list[str],
    fetch_bytes: Any,
    max_download_bytes: int,
    max_decompressed_bytes: int,
    limit: int,
) -> dict[str, Any]:
    url = candidate["url"]
    skip_reason = _skip_reason_for_url(url)
    if skip_reason:
        candidate.update({"status": "skipped", "skip_reason": skip_reason})
        return {"candidate": candidate, "source_records": []}
    try:
        data = _call_fetch_bytes(fetch_bytes, url, max_bytes=max_download_bytes + 1)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        candidate.update({"status": "skipped", "skip_reason": "download_failed", "error": str(exc)})
        return {"candidate": candidate, "source_records": []}
    candidate["downloaded_bytes"] = len(data)
    if len(data) > max_download_bytes:
        candidate.update({"status": "skipped", "skip_reason": "oversized_compressed_file"})
        return {"candidate": candidate, "source_records": []}
    try:
        text = _decode_table_bytes(data, url=url, max_decompressed_bytes=max_decompressed_bytes)
    except ValueError as exc:
        candidate.update({"status": "skipped", "skip_reason": str(exc)})
        return {"candidate": candidate, "source_records": []}
    records = _source_records_from_table_text(text, candidate=candidate, hit=hit, query=query, genes=genes, limit=limit)
    if not records:
        candidate.update({"status": "skipped", "skip_reason": "unparsable_or_no_candidate_gene_rows"})
        return {"candidate": candidate, "source_records": []}
    candidate.update({"status": "used", "source_record_count": len(records)})
    return {"candidate": candidate, "source_records": records}


def _source_records_from_table_text(
    text: str,
    *,
    candidate: dict[str, Any],
    hit: dict[str, Any],
    query: dict[str, Any],
    genes: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    rows = _parse_table_rows(text, limit=max(limit * 20, 200))
    if not rows:
        return []
    records: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows, start=1):
        row_text = " ".join(str(value) for value in row.values() if value)
        row_genes = _row_genes(row, candidate_genes=genes, row_text=row_text)
        matching_genes = [gene for gene in row_genes if gene in genes]
        if not matching_genes:
            continue
        source_text = " ".join(
            str(value or "")
            for value in (
                hit.get("title"),
                hit.get("summary"),
                hit.get("organism"),
                candidate.get("filename"),
                row_text,
            )
        )
        row_context = {
            field: _context_value(field, row=row, query=query, hit=hit, source_text=source_text)
            for field in ("organism", "cell_line", "perturbation", "assay", "phenotype")
        }
        source_title = hit.get("title") or hit.get("accession") or "NCBI GEO dataset"
        finding = _geo_table_finding(
            genes=matching_genes,
            source_title=str(source_title),
            row=row,
            row_context=row_context,
            filename=str(candidate.get("filename") or ""),
        )
        support_source_text = " ".join([source_text, finding])
        verified_fields: dict[str, Any] = {"genes": matching_genes}
        support_spans = [
            {"field": "genes", "value": gene, "source_text": support_source_text}
            for gene in matching_genes
        ]
        for field, value in row_context.items():
            if value and _value_supported_by_text(value, support_source_text):
                verified_fields[field] = value
                support_spans.append({"field": field, "value": value, "source_text": support_source_text})
        accession = str(hit.get("accession") or hit.get("uid") or "geo")
        records.append(
            {
                "record_id": f"geo:{accession}:{candidate.get('filename') or 'table'}:{row_number}:{'-'.join(matching_genes)}",
                "genes": matching_genes,
                "source_type": "NCBI GEO perturbation screen table",
                "source_title": str(source_title),
                "source_url": candidate.get("url") or hit.get("source_url"),
                "finding": finding,
                "geo_accession": hit.get("accession"),
                "geo_uid": hit.get("uid"),
                "download_url": candidate.get("url"),
                "table_row": row_number,
                "verified_fields": verified_fields,
                "support_spans": support_spans,
                **{field: value for field, value in row_context.items() if value},
            }
        )
        if len(records) >= limit:
            break
    return records


def _parse_table_rows(text: str, *, limit: int) -> list[dict[str, str]]:
    lines = [line.lstrip("\ufeff") for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    matrix_begin = next((idx for idx, line in enumerate(lines) if line.startswith("!series_matrix_table_begin")), None)
    if matrix_begin is not None:
        lines = lines[matrix_begin + 1 :]
    header_index, delimiter = _find_header_line(lines)
    if header_index is None or not delimiter:
        return []
    reader = csv.DictReader(lines[header_index:], delimiter=delimiter)
    rows: list[dict[str, str]] = []
    for index, row in enumerate(reader):
        if index >= max(limit, 0):
            break
        if not row:
            continue
        rows.append({str(key or "").strip(): str(value or "").strip() for key, value in row.items()})
    return rows


def _find_header_line(lines: list[str]) -> tuple[int | None, str | None]:
    for index, line in enumerate(lines[:250]):
        if line.startswith("!") and not line.startswith("!series_matrix_table_begin"):
            continue
        delimiter = _best_delimiter(line)
        if not delimiter:
            continue
        try:
            columns = next(csv.reader([line], delimiter=delimiter))
        except csv.Error:
            continue
        normalized = {_table_key(column) for column in columns}
        if normalized & {_table_key(alias) for alias in _GENE_COLUMN_ALIASES}:
            return index, delimiter
    return None, None


def _best_delimiter(line: str) -> str | None:
    counts = {delimiter: line.count(delimiter) for delimiter in ("\t", ",", ";")}
    delimiter, count = max(counts.items(), key=lambda item: item[1])
    return delimiter if count > 0 else None


def _download_candidates_for_hit(
    hit: dict[str, Any],
    *,
    geo_ftp_base: str,
    fetch_text: Any,
    limit: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for url in _metadata_urls(hit):
        candidates.append(_candidate(url, hit=hit, origin="geo_metadata_url"))
    accession = str(hit.get("accession") or "")
    if accession.upper().startswith("GSE"):
        candidates.extend(_generated_gse_candidates(accession, geo_ftp_base=geo_ftp_base))
        for directory_url in _gse_directory_urls(accession, geo_ftp_base=geo_ftp_base):
            try:
                listing = fetch_text(directory_url)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                continue
            for url in _links_from_directory(listing, base_url=directory_url):
                candidates.append(_candidate(url, hit=hit, origin="geo_ftp_directory_listing"))
    return _dedupe_candidates(candidates)[: max(limit, 0)]


def _candidate(url: str, *, hit: dict[str, Any], origin: str) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(_https_url(url))
    filename = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1])
    return {
        "accession": hit.get("accession"),
        "uid": hit.get("uid"),
        "url": _https_url(url),
        "filename": filename,
        "origin": origin,
        "status": "considered",
    }


def _generated_gse_candidates(accession: str, *, geo_ftp_base: str) -> list[dict[str, Any]]:
    prefix = _geo_series_prefix(accession)
    accession = accession.upper()
    base = geo_ftp_base.rstrip("/")
    matrix = f"{base}/series/{prefix}/{accession}/matrix/{accession}_series_matrix.txt.gz"
    return [
        {
            "accession": accession,
            "url": matrix,
            "filename": f"{accession}_series_matrix.txt.gz",
            "origin": "geo_ftp_series_matrix",
            "status": "considered",
        }
    ]


def _gse_directory_urls(accession: str, *, geo_ftp_base: str) -> list[str]:
    prefix = _geo_series_prefix(accession)
    accession = accession.upper()
    base = geo_ftp_base.rstrip("/")
    return [
        f"{base}/series/{prefix}/{accession}/matrix/",
        f"{base}/series/{prefix}/{accession}/suppl/",
    ]


def _geo_series_prefix(accession: str) -> str:
    match = re.match(r"^(GSE)(\d+)$", accession.upper())
    if not match:
        return accession.upper()
    number = match.group(2)
    if len(number) <= 3:
        return "GSEnnn"
    return f"GSE{number[:-3]}nnn"


def _links_from_directory(text: str, *, base_url: str) -> list[str]:
    urls: list[str] = []
    for href in _HREF_RE.findall(text):
        if href in {"../", "./"}:
            continue
        urls.append(urllib.parse.urljoin(base_url, href))
    return urls


def _metadata_urls(hit: dict[str, Any]) -> list[str]:
    raw = hit.get("raw_metadata") if isinstance(hit.get("raw_metadata"), dict) else {}
    values = [str(hit.get("ftp_link") or "")]
    values.extend(_flatten_strings(raw))
    urls: list[str] = []
    for value in values:
        urls.extend(_URL_RE.findall(value))
    return [_https_url(url.rstrip(".,;")) for url in urls if _looks_like_download_candidate(url)]


def _looks_like_download_candidate(url: str) -> bool:
    lowered = urllib.parse.unquote(url).casefold()
    return lowered.endswith(_TEXT_TABLE_SUFFIXES) or lowered.endswith(_RAW_OR_BINARY_SUFFIXES)


def _skip_reason_for_url(url: str) -> str:
    lowered = urllib.parse.unquote(urllib.parse.urlparse(url).path).casefold()
    filename = lowered.rsplit("/", 1)[-1]
    if filename.endswith(_RAW_OR_BINARY_SUFFIXES) or "_raw.tar" in filename or filename.endswith("_raw.tar.gz"):
        return "raw_archive_or_binary_file"
    if not filename.endswith(_TEXT_TABLE_SUFFIXES):
        return "not_bounded_text_table"
    return ""


def _decode_table_bytes(data: bytes, *, url: str, max_decompressed_bytes: int) -> str:
    raw = data
    if url.casefold().endswith(".gz") or data.startswith(b"\x1f\x8b"):
        try:
            raw = gzip.decompress(data)
        except OSError as exc:
            raise ValueError("unparsable_compressed_file") from exc
    if len(raw) > max_decompressed_bytes:
        raise ValueError("oversized_decompressed_file")
    if b"\x00" in raw[:4096]:
        raise ValueError("binary_file")
    text = raw.decode("utf-8-sig", errors="replace")
    if not text.strip():
        raise ValueError("empty_file")
    return text


def _row_genes(row: dict[str, str], *, candidate_genes: list[str], row_text: str) -> list[str]:
    for key, value in row.items():
        if _table_key(key) in {_table_key(alias) for alias in _GENE_COLUMN_ALIASES}:
            genes = _normalize_genes(part for part in _GENE_SPLIT_RE.split(value) if part)
            if genes:
                return genes
    return [gene for gene in candidate_genes if re.search(rf"\b{re.escape(gene)}\b", row_text, flags=re.I)]


def _context_value(
    field: str,
    *,
    row: dict[str, str],
    query: dict[str, Any],
    hit: dict[str, Any],
    source_text: str,
) -> str:
    row_value = _row_value(row, _FIELD_ALIASES[field])
    if row_value:
        return row_value
    for value in (query.get(field), hit.get(field), hit.get("organism") if field == "organism" else None):
        text = _clean_text(value)
        if text and _value_supported_by_text(text, source_text):
            return text
    return ""


def _row_value(row: dict[str, str], aliases: tuple[str, ...]) -> str:
    by_key = {_table_key(key): value for key, value in row.items()}
    for alias in aliases:
        value = by_key.get(_table_key(alias))
        if value:
            return _clean_text(value)
    return ""


def _geo_table_finding(
    *,
    genes: list[str],
    source_title: str,
    row: dict[str, str],
    row_context: dict[str, str],
    filename: str,
) -> str:
    metrics = [
        f"{key}={value}"
        for key, value in row.items()
        if value and _table_key(key) not in {_table_key(alias) for alias in _GENE_COLUMN_ALIASES}
    ][:8]
    context = "; ".join(f"{key}={value}" for key, value in row_context.items() if value)
    chunks = [f"{', '.join(genes)} appears in GEO table {filename or source_title}"]
    if context:
        chunks.append(context)
    if metrics:
        chunks.append("; ".join(metrics))
    return "; ".join(chunks)


def _candidate_file_count(candidates: Iterable[dict[str, Any]]) -> int:
    return sum(1 for item in candidates if item.get("url"))


def _dedupe_candidates(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = str(candidate.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        output.append(candidate)
    return output
