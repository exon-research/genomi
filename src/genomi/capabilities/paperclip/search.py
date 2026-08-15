from __future__ import annotations

import json
import os
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
    "proteins/uniprot",
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
        "--json",
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
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError):
        return _unavailable(query_scope, "invalid_response")

    records = [_normalize_record(row) for row in _rows(payload)]
    records = [row for row in records if row]
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
    return {
        "status": status,
        "provider": "paperclip",
        "query": clean_query,
        "sources": list(selected_sources),
        "records": records,
        "evidence_envelope": envelope,
    }


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


def _normalize_record(row: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "record_id": ("id", "paper_id", "document_id", "pmcid", "pmid", "doi"),
        "title": ("title",),
        "authors": ("authors", "author"),
        "year": ("year", "publication_year", "published"),
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
    return normalized
