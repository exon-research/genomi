from __future__ import annotations

import urllib.error
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from typing import Any

from ....retrieval import semantic as retrieval_semantic
from ..evidence_acquisition import acquire_perturbation_source_records
from .client import (
    DEFAULT_NCBI_TOOL,
    GEO_QUERY_SCHEMA_VERSION,
    MAX_CANDIDATE_FILES,
    MAX_DECOMPRESSED_BYTES,
    MAX_DOWNLOAD_BYTES,
    NCBI_API_KEY_ENV,
    NCBI_EMAIL_ENV,
    NCBI_EUTILS_BASE,
    NCBI_GEO_FTP_BASE,
    NCBI_TOOL_ENV,
    _call_fetch_bytes,
    _dedupe_geo_hits,
    _eutils_url,
    _fetch_bytes,
    _fetch_json,
    _fetch_text,
    _first_semantic_text,
    _geo_search_term,
    _ncbi_params,
    _normalize_geo_hit,
    _parse_esearch_ids,
    _parse_esummary_hits,
    _parse_esummary_xml,
    _semantic_geo_fields,
    _xml_item_value,
)
from .response import _geo_response, _geo_semantic_usage
from .tables import (
    _FIELD_ALIASES,
    _GENE_COLUMN_ALIASES,
    _GENE_SPLIT_RE,
    _HREF_RE,
    _RAW_OR_BINARY_SUFFIXES,
    _TEXT_TABLE_SUFFIXES,
    _URL_RE,
    _best_delimiter,
    _candidate,
    _candidate_file_count,
    _consider_download_candidate,
    _context_value,
    _decode_table_bytes,
    _dedupe_candidates,
    _download_candidates_for_hit,
    _find_header_line,
    _generated_gse_candidates,
    _geo_series_prefix,
    _geo_table_finding,
    _gse_directory_urls,
    _links_from_directory,
    _looks_like_download_candidate,
    _metadata_urls,
    _parse_table_rows,
    _row_genes,
    _row_value,
    _skip_reason_for_url,
    _source_records_from_table_text,
)
from .text_utils import (
    _ACCESSION_RE,
    _LOW_INFORMATION_CONTEXT_TOKENS,
    _TOKEN_RE,
    _canonical,
    _clean_text,
    _dedupe_text,
    _extract_accessions,
    _flatten_strings,
    _https_url,
    _meaningful_tokens,
    _normalize_genes,
    _records_by_gene,
    _table_key,
    _tokens,
    _value_supported_by_text,
)


def query_geo_datasets(
    *,
    context: str,
    genes: Iterable[str] | None = None,
    organism: str | None = None,
    cell_line: str | None = None,
    perturbation: str | None = None,
    assay: str | None = None,
    phenotype: str | None = None,
    accession: str | None = None,
    limit: int = 25,
    semantic_context: object = None,
    ncbi_api_key: str | None = None,
    ncbi_email: str | None = None,
    ncbi_tool: str | None = None,
    eutils_base: str = NCBI_EUTILS_BASE,
    geo_ftp_base: str = NCBI_GEO_FTP_BASE,
    fetch_json: Any | None = None,
    fetch_text: Any | None = None,
    fetch_bytes: Any | None = None,
    max_download_bytes: int = MAX_DOWNLOAD_BYTES,
    max_decompressed_bytes: int = MAX_DECOMPRESSED_BYTES,
) -> dict[str, Any]:
    """Search NCBI GEO metadata and bounded public table files.

    The returned source records are intentionally routed through the same
    perturbation source-record verifier as local tables and native screen
    sources. Metadata hits by themselves never become direct evidence.
    """

    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    semantic_fields = _semantic_geo_fields(semantic)
    normalized_genes = _normalize_genes(genes or [])
    query = {
        "context": _clean_text(context),
        "genes": normalized_genes,
        "organism": _clean_text(organism) or semantic_fields.get("organism", ""),
        "cell_line": _clean_text(cell_line) or semantic_fields.get("cell_line", ""),
        "perturbation": _clean_text(perturbation) or semantic_fields.get("perturbation", ""),
        "assay": _clean_text(assay) or semantic_fields.get("assay", ""),
        "phenotype": _clean_text(phenotype) or semantic_fields.get("phenotype", ""),
        "accession": _clean_text(accession),
        "semantic_context_terms": retrieval_semantic.search_terms(semantic),
    }
    return_limit = max(1, int(limit or 25))
    json_fetcher = fetch_json or _fetch_json
    text_fetcher = fetch_text or _fetch_text
    bytes_fetcher = fetch_bytes or _fetch_bytes
    download_candidates: list[dict[str, Any]] = []
    unavailable: list[dict[str, str]] = []
    consulted: list[str] = []

    try:
        search_payload = json_fetcher(
            _eutils_url(
                eutils_base,
                "esearch.fcgi",
                _ncbi_params(
                    {
                        "db": "gds",
                        "retmode": "json",
                        "retmax": str(return_limit),
                        "term": _geo_search_term(query),
                    },
                    api_key=ncbi_api_key,
                    email=ncbi_email,
                    tool=ncbi_tool,
                ),
            )
        )
        ids = _parse_esearch_ids(search_payload)[:return_limit]
        consulted.append("NCBI GEO")
        summary_payload: Any = {"result": {"uids": []}}
        if ids:
            summary_payload = json_fetcher(
                _eutils_url(
                    eutils_base,
                    "esummary.fcgi",
                    _ncbi_params(
                        {
                            "db": "gds",
                            "retmode": "json",
                            "id": ",".join(ids),
                        },
                        api_key=ncbi_api_key,
                        email=ncbi_email,
                        tool=ncbi_tool,
                    ),
                )
            )
        geo_hits = _dedupe_geo_hits(_parse_esummary_hits(summary_payload))[:return_limit]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        unavailable.append({"source": "NCBI GEO", "error": str(exc)})
        return _geo_response(
            query=query,
            geo_hits=[],
            download_candidates=[],
            source_records=[],
            acquisition=None,
            status="source_unavailable",
            coverage_state="source_unavailable",
            consulted=consulted,
            unavailable=unavailable,
            semantic_context=semantic,
        )

    raw_source_records: list[dict[str, Any]] = []
    if normalized_genes:
        for hit in geo_hits:
            remaining_files = MAX_CANDIDATE_FILES - _candidate_file_count(download_candidates)
            if remaining_files <= 0:
                break
            for candidate in _download_candidates_for_hit(
                hit,
                geo_ftp_base=geo_ftp_base,
                fetch_text=text_fetcher,
                limit=remaining_files,
            ):
                record = _consider_download_candidate(
                    candidate,
                    query=query,
                    hit=hit,
                    genes=normalized_genes,
                    fetch_bytes=bytes_fetcher,
                    max_download_bytes=max_download_bytes,
                    max_decompressed_bytes=max_decompressed_bytes,
                    limit=max(1, return_limit - len(raw_source_records)),
                )
                download_candidates.append(record["candidate"])
                raw_source_records.extend(record["source_records"])
                if len(raw_source_records) >= return_limit:
                    break
            if len(raw_source_records) >= return_limit:
                break

    acquisition: dict[str, Any] | None = None
    source_records: list[dict[str, Any]]
    if normalized_genes:
        acquisition = acquire_perturbation_source_records(
            context=query["context"],
            genes=normalized_genes,
            source_records=raw_source_records,
            organism=query["organism"],
            cell_line=query["cell_line"],
            perturbation=query["perturbation"],
            assay=query["assay"],
            phenotype=query["phenotype"],
            limit=return_limit,
        )
        source_records = [record for record in acquisition.get("source_records", []) if isinstance(record, dict)]
    else:
        source_records = []

    if source_records:
        status = "geo_source_records_found"
        coverage_state = "data_returned"
    elif geo_hits:
        status = "geo_metadata_found"
        coverage_state = "metadata_only"
    else:
        status = "no_matching_geo_records"
        coverage_state = "in_scope_empty"

    return _geo_response(
        query=query,
        geo_hits=geo_hits,
        download_candidates=download_candidates,
        source_records=source_records,
        acquisition=acquisition,
        status=status,
        coverage_state=coverage_state,
        consulted=consulted,
        unavailable=unavailable,
        semantic_context=semantic,
    )


def geo_advantage_applies(value: str | None, accession: str | None = None) -> bool:
    text = f"{value or ''} {accession or ''}"
    if _extract_accessions(text):
        return True
    tokens = set(_tokens(text))
    if tokens & {"geo", "gds"} or "ncbi geo" in text.casefold():
        return True
    discovery_terms = {
        "public",
        "published",
        "dataset",
        "datasets",
        "supplementary",
        "supplemental",
        "matrix",
        "table",
        "tables",
        "accession",
        "study",
    }
    perturbation_terms = {
        "screen",
        "screens",
        "crispr",
        "rnai",
        "shrna",
        "sirna",
        "knockout",
        "knockdown",
        "perturbation",
        "dependency",
        "viability",
        "resistance",
        "sensitivity",
    }
    return bool((tokens & discovery_terms) and (tokens & perturbation_terms))


def source_name_is_geo(value: str) -> bool:
    cleaned = _clean_text(value).casefold().replace("-", "_")
    return cleaned in {"geo", "ncbi_geo", "gds", "geo_datasets"}
