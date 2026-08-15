from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

from ...evidence import envelope as evidence_envelope
from ...runtime.external_credentials import resolve_external_credentials


SUPPORTED_SOURCES = (
    "pmc",
    "biorxiv",
    "medrxiv",
    "arxiv",
    "abstracts",
    "fda",
    "fda/jp",
    "fda/eu",
    "trials",
    "trials/us",
    "trials/eu",
    "trials/jp",
    "trials/cn",
    "proteins",
    "uniprot",
)
DEFAULT_SOURCES = ("pmc", "abstracts")
Runner = Callable[..., subprocess.CompletedProcess[str]]


def search_biomedical(
    *,
    query: str,
    sources: list[str] | None = None,
    limit: int = 10,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    clean_query = query.strip()
    if not clean_query:
        raise ValueError("paperclip.search_biomedical requires query")
    selected_sources = tuple(sources or DEFAULT_SOURCES)
    unsupported = sorted(set(selected_sources) - set(SUPPORTED_SOURCES))
    if unsupported:
        raise ValueError(f"unsupported Paperclip sources: {', '.join(unsupported)}")
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")

    credentials = resolve_external_credentials("paperclip")
    executable = shutil.which("paperclip")
    query_scope = {"query": clean_query, "sources": list(selected_sources)}
    if not credentials.configured or not executable:
        return _unavailable(query_scope, "credential_missing" if not credentials.configured else "client_missing")

    command = [
        executable,
        "search",
        "-s",
        ",".join(selected_sources),
        clean_query,
        "-n",
        str(limit),
    ]
    child_environment = dict(os.environ)
    for unrelated_key in ("BIOHUB_API_KEY", "ESM_API_KEY", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"):
        child_environment.pop(unrelated_key, None)
    child_environment["PAPERCLIP_API_KEY"] = credentials.values["api_key"]
    try:
        completed = runner(
            command,
            env=child_environment,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return _unavailable(query_scope, "request_failed")
    if completed.returncode != 0:
        return _unavailable(query_scope, "request_failed")
    records, result_id, declared_count = _parse_search_output(completed.stdout, selected_sources)
    if not records and declared_count is None:
        return _unavailable(query_scope, "invalid_response")
    coverage = {
        "consulted_sources": [f"paperclip:{source}" for source in selected_sources],
        "source_status": "consulted",
    }
    if records:
        envelope = evidence_envelope.evidence_present(
            operation="paperclip.search_biomedical",
            query_scope=query_scope,
            coverage=coverage,
            observations={"observation_count": len(records)},
            answer_readiness=evidence_envelope.SCOPED_ANSWER_ONLY,
            guidance=["evidence_present:use_as_scoped_public_literature_evidence"],
        )
        status = "completed"
    else:
        envelope = evidence_envelope.empty_consulted_scope(
            operation="paperclip.search_biomedical",
            query_scope=query_scope,
            coverage=coverage,
            guidance=["not_observed_in_consulted_scope:do_not_imply_biomedical_negative"],
        )
        status = "in_scope_empty"
    result = {
        "status": status,
        "provider": "paperclip",
        "query": clean_query,
        "sources": list(selected_sources),
        "records": records,
        "evidence_envelope": envelope,
    }
    if result_id:
        result["result_id"] = result_id
    return result


def _unavailable(query_scope: dict[str, Any], reason_code: str) -> dict[str, Any]:
    return {
        "status": "source_unavailable",
        "provider": "paperclip",
        "reason_code": reason_code,
        "evidence_envelope": evidence_envelope.not_assessed(
            operation="paperclip.search_biomedical",
            reason=reason_code,
            query_scope=query_scope,
            coverage={"consulted_sources": [], "source_status": "unavailable"},
            guidance=["not_assessed:retry_external_source_or_use_another_source"],
        ),
    }


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("results", "records", "papers", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            nested = _rows(value)
            if nested:
                return nested
    return []


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_RESULT_HEADER = re.compile(r"Found\s+(\d+)\s+(?:papers?|records?)\b(?:\s+\[(s_[A-Za-z0-9_-]+)\])?")
_RESULT_ENTRY = re.compile(r"\n(?=\s*\d+\.\s)")
_RESULT_FIRST_LINE = re.compile(r"\s*\d+\.\s+(.+)")
_DISPLAY_SOURCE_LABELS = {
    "pmc",
    "biorxiv",
    "medrxiv",
    "arxiv",
    "abstracts",
    "fda",
    "trials",
    "proteins",
    "uniprot",
}


def _parse_search_output(
    output: str, selected_sources: tuple[str, ...]
) -> tuple[list[dict[str, Any]], str | None, int | None]:
    """Accept both structured responses and Paperclip's documented CLI display."""
    text = _ANSI_ESCAPE.sub("", str(output or "")).strip()
    payload = _decode_json_prefix(text)
    if payload is not None:
        records = [_normalize_record(row) for row in _rows(payload)]
        return [record for record in records if record], _payload_result_id(payload), None

    header = _RESULT_HEADER.search(text)
    declared_count = int(header.group(1)) if header else None
    result_id = header.group(2) if header and header.group(2) else None
    records = [
        record
        for entry in _RESULT_ENTRY.split(text)
        if (record := _parse_display_entry(entry, selected_sources))
    ]
    return records, result_id, declared_count


def _decode_json_prefix(text: str) -> Any:
    try:
        payload, _ = json.JSONDecoder().raw_decode(text.lstrip())
    except (TypeError, json.JSONDecodeError):
        return None
    return payload


def _payload_result_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("result_id") or payload.get("results_id")
    return str(value) if value else None


def _parse_display_entry(
    entry: str, selected_sources: tuple[str, ...]
) -> dict[str, Any]:
    lines = [line.strip() for line in entry.strip().splitlines() if line.strip()]
    if not lines:
        return {}
    first_line = _RESULT_FIRST_LINE.match(lines[0])
    if not first_line:
        return {}
    record: dict[str, Any] = {"title": first_line.group(1).strip()}
    for line in lines[1:]:
        if line.startswith("[") and "saved to" in line:
            continue
        if line.startswith("https://"):
            record.setdefault("url", line)
            doi_marker = "doi.org/"
            if doi_marker in line:
                record.setdefault("doi", line.split(doi_marker, 1)[1])
        elif line.startswith('"'):
            record["abstract"] = line.strip('"')
        elif "·" in line:
            parts = [part.strip() for part in line.split("·")]
            if parts:
                record["record_id"] = parts[0]
            if len(parts) >= 2:
                if parts[1].lower() in _DISPLAY_SOURCE_LABELS:
                    record["source"] = parts[1].lower()
                else:
                    record["journal"] = parts[1]
            if len(parts) >= 3:
                record["published"] = parts[2]
        elif "authors" not in record:
            record["authors"] = line
    record_id = str(record.get("record_id") or "")
    source = _source_from_record_id(record_id)
    if source:
        record["source"] = source
    elif len(selected_sources) == 1:
        record["source"] = selected_sources[0]
    record["collection"] = _collection_from_source(str(record.get("source") or ""))
    return record


def _source_from_record_id(record_id: str) -> str | None:
    if record_id.startswith("PMC"):
        return "pmc"
    if record_id.startswith("bio_"):
        return "biorxiv"
    if record_id.startswith("med_"):
        return "medrxiv"
    if record_id.startswith(("arx_", "arxiv_")):
        return "arxiv"
    if record_id.startswith("fda_"):
        return "fda"
    if record_id.startswith(("tri_", "NCT")):
        return "trials"
    return None


def _collection_from_source(source: str) -> str:
    if source.startswith("fda"):
        return "fda"
    if source.startswith("trials"):
        return "trials"
    if source.startswith("proteins") or source == "uniprot":
        return "proteins"
    return "papers"


def _normalize_record(row: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "record_id": ("id", "paper_id", "document_id", "pmcid", "pmid", "doi"),
        "title": ("title",),
        "authors": ("authors", "author"),
        "year": ("year", "publication_year", "pub_year", "published", "pub_date"),
        "journal": ("journal", "venue"),
        "doi": ("doi",),
        "pmcid": ("pmcid", "pmc_id"),
        "pmid": ("pmid", "pubmed_id"),
        "source": ("source", "database"),
        "url": ("url", "link"),
        "abstract": ("abstract", "snippet", "summary"),
    }
    normalized: dict[str, Any] = {}
    for target, names in aliases.items():
        value = next((row.get(name) for name in names if row.get(name) not in (None, "", [])), None)
        if value is not None:
            normalized[target] = value
    normalized["collection"] = _collection_from_source(str(normalized.get("source") or ""))
    if normalized.get("doi") and not normalized.get("url"):
        normalized["url"] = f"https://doi.org/{normalized['doi']}"
    return normalized
