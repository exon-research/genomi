from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from typing import Any

from ....retrieval import semantic as retrieval_semantic
from .text_utils import (
    _clean_text,
    _extract_accessions,
    _flatten_strings,
    _https_url,
)

GEO_QUERY_SCHEMA_VERSION = "genomi-functional-genomics-geo-query-v1"
NCBI_EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_GEO_FTP_BASE = "https://ftp.ncbi.nlm.nih.gov/geo"
NCBI_API_KEY_ENV = "NCBI_API_KEY"
NCBI_EMAIL_ENV = "NCBI_EMAIL"
NCBI_TOOL_ENV = "NCBI_TOOL"
DEFAULT_NCBI_TOOL = "genomi"
MAX_DOWNLOAD_BYTES = 5_000_000
MAX_DECOMPRESSED_BYTES = 20_000_000
MAX_CANDIDATE_FILES = 8


def _parse_esearch_ids(payload: Any) -> list[str]:
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("<"):
            root = ET.fromstring(text)
            return [_clean_text(node.text) for node in root.findall(".//Id") if _clean_text(node.text)]
        payload = json.loads(text)
    if isinstance(payload, list):
        return [str(item) for item in payload if str(item or "").strip()]
    if not isinstance(payload, dict):
        return []
    result = payload.get("esearchresult") or payload.get("eSearchResult") or payload.get("result") or payload
    ids = result.get("idlist") or result.get("IdList") or result.get("ids") or []
    return [str(item) for item in ids if str(item or "").strip()]


def _parse_esummary_hits(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("<"):
            return _parse_esummary_xml(text)
        payload = json.loads(text)
    if not isinstance(payload, dict):
        return []
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    uids = result.get("uids") or result.get("Uids") or []
    hits: list[dict[str, Any]] = []
    if isinstance(uids, list):
        for uid in uids:
            row = result.get(str(uid))
            if isinstance(row, dict):
                hits.append(_normalize_geo_hit(row, uid=str(uid)))
    if not hits:
        for key, row in result.items():
            if key in {"uids", "Uids"} or not isinstance(row, dict):
                continue
            hits.append(_normalize_geo_hit(row, uid=str(row.get("uid") or key)))
    return [hit for hit in hits if hit.get("uid") or hit.get("accession")]


def _parse_esummary_xml(text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(text)
    hits: list[dict[str, Any]] = []
    for docsum in root.findall(".//DocSum"):
        row: dict[str, Any] = {}
        uid = _clean_text(docsum.findtext("Id"))
        for item in docsum.findall("Item"):
            name = _clean_text(item.attrib.get("Name"))
            if not name:
                continue
            row[name] = _xml_item_value(item)
        hits.append(_normalize_geo_hit(row, uid=uid))
    return [hit for hit in hits if hit.get("uid") or hit.get("accession")]


def _xml_item_value(item: ET.Element) -> Any:
    children = list(item)
    if not children:
        return _clean_text(item.text)
    values = [_xml_item_value(child) for child in children]
    return [value for value in values if value]


def _normalize_geo_hit(row: dict[str, Any], *, uid: str) -> dict[str, Any]:
    lower = {str(key).casefold(): value for key, value in row.items()}
    text_values = " ".join(_flatten_strings(row))
    accession = _clean_text(
        lower.get("accession")
        or lower.get("geoaccession")
        or lower.get("gse")
        or lower.get("gsm")
        or lower.get("gds")
    )
    if not accession:
        accessions = _extract_accessions(text_values)
        accession = accessions[0] if accessions else ""
    title = _clean_text(lower.get("title") or lower.get("gdstitle") or lower.get("entrytitle") or lower.get("name"))
    summary = _clean_text(lower.get("summary") or lower.get("description") or lower.get("abstract"))
    organism = _clean_text(lower.get("taxon") or lower.get("organism") or lower.get("taxonname"))
    gds_type = _clean_text(lower.get("gdstype") or lower.get("entrytype") or lower.get("type"))
    ftp_link = _clean_text(lower.get("ftplink") or lower.get("ftp_link"))
    source_url = f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={accession}" if accession else ""
    return {
        "uid": _clean_text(row.get("uid") or uid),
        "accession": accession,
        "title": title,
        "summary": summary,
        "organism": organism,
        "geo_type": gds_type,
        "ftp_link": _https_url(ftp_link) if ftp_link else "",
        "source_url": source_url,
        "raw_metadata": row,
    }


def _dedupe_geo_hits(hits: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        key = (str(hit.get("accession") or ""), str(hit.get("uid") or ""))
        if key in seen:
            continue
        seen.add(key)
        output.append(hit)
    return output


def _geo_search_term(query: dict[str, Any]) -> str:
    accessions = _extract_accessions(" ".join(str(query.get(key) or "") for key in ("accession", "context")))
    if accessions:
        return " OR ".join(f"{accession}[ACCN]" for accession in accessions)
    parts = [
        query.get("context"),
        query.get("organism"),
        query.get("cell_line"),
        query.get("perturbation"),
        query.get("assay"),
        query.get("phenotype"),
        " ".join(str(item) for item in query.get("semantic_context_terms") or []),
    ]
    term = " ".join(str(part or "").strip() for part in parts if str(part or "").strip())
    return term or "functional genomics perturbation screen"


def _eutils_url(base: str, endpoint: str, params: dict[str, Any]) -> str:
    return base.rstrip("/") + "/" + endpoint.lstrip("/") + "?" + urllib.parse.urlencode(
        {key: value for key, value in params.items() if value not in (None, "")}
    )


def _ncbi_params(params: dict[str, Any], *, api_key: str | None, email: str | None, tool: str | None) -> dict[str, Any]:
    output = dict(params)
    output["api_key"] = _clean_text(api_key or os.environ.get(NCBI_API_KEY_ENV))
    output["email"] = _clean_text(email or os.environ.get(NCBI_EMAIL_ENV))
    output["tool"] = _clean_text(tool or os.environ.get(NCBI_TOOL_ENV) or DEFAULT_NCBI_TOOL)
    return output


def _fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "genomi/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"Accept": "text/html,text/plain,*/*", "User-Agent": "genomi/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _fetch_bytes(url: str, *, max_bytes: int = MAX_DOWNLOAD_BYTES + 1) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "text/plain,application/gzip,*/*", "User-Agent": "genomi/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            return b"\0" * (max_bytes + 1)
        return response.read(max_bytes + 1)


def _call_fetch_bytes(fetcher: Any, url: str, *, max_bytes: int) -> bytes:
    try:
        data = fetcher(url, max_bytes=max_bytes)
    except TypeError:
        data = fetcher(url)
    if not isinstance(data, bytes):
        raise ValueError("download did not return bytes")
    return data


def _semantic_geo_fields(semantic: retrieval_semantic.SemanticContext) -> dict[str, str]:
    return {
        "organism": _first_semantic_text(semantic, "organism", "species"),
        "cell_line": _first_semantic_text(semantic, "cell_line", "cell_type", "model"),
        "perturbation": _first_semantic_text(semantic, "perturbation", "screen_method", "assay_method"),
        "assay": _first_semantic_text(semantic, "assay", "readout"),
        "phenotype": _first_semantic_text(semantic, "phenotype", "trait", "condition"),
    }


def _first_semantic_text(semantic: retrieval_semantic.SemanticContext, *entity_types: str) -> str:
    texts = retrieval_semantic.entity_texts(semantic, *entity_types)
    return _clean_text(texts[0]) if texts else ""
