from __future__ import annotations

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
_UNIPROT_ACCESSION = re.compile(
    r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})\Z"
)
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
    records, result_ids, declared_count = _parse_search_output(completed.stdout, selected_sources)
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
            guidance=["evidence_present:use_only_for_public_source_discovery"],
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
    if result_ids:
        result["result_ids"] = result_ids
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


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
# Every source family prints a result header, numbered entries, and a
# saved-result footer that both carry the reusable `s_...` result handle.
_RESULT_HEADER = re.compile(r"^Found\s+(\d+)\s+\w+\b\s*(?:\[(s_[A-Za-z0-9_-]+)\])?")
_RESULT_FOOTER = re.compile(r"^\[[^\]]*\bsaved to\s+(s_[A-Za-z0-9_-]+)\]$")
_ENTRY_START = re.compile(r"^\d+\.\s+(.+)$")
# Paperclip's own document handle, the id `paperclip cat /<collection>/<id>` takes.
_DOCUMENT_HANDLE = re.compile(r"[a-z]{2,6}_[A-Za-z0-9.]{4,}\Z")
_PUBLISHED = re.compile(r"\d{4}(?:-\d{2}(?:-\d{2})?)?\Z")
_PROTEIN_LENGTH = re.compile(r"\d+\s*aa\Z")
_METADATA_SEPARATOR = "·"
_SECTION_MARKER = "§"
_DISPLAY_SOURCE_LABELS = {
    "pmc",
    "biorxiv",
    "medrxiv",
    "arxiv",
    "abstracts",
    "proteins",
    "uniprot",
}
# The handle prefix routes the document, so it also fixes the read collection.
# Non-US regulatory documents carry `tri_` handles and are read under /trials/.
_HANDLE_COLLECTIONS = {
    "fda_": "fda",
    "tri_": "trials",
    "bio_": "papers",
    "med_": "papers",
    "arx_": "papers",
    "oa_": "papers",
    "PMC": "papers",
}
# `tri_` is shared by trials/*, fda/jp, and fda/eu, so it names no single source.
_HANDLE_SOURCES = {
    "fda_": "fda",
    "bio_": "biorxiv",
    "med_": "medrxiv",
    "arx_": "arxiv",
    "oa_": "abstracts",
    "PMC": "pmc",
}
_SOURCE_COLLECTIONS = {
    "pmc": "papers",
    "biorxiv": "papers",
    "medrxiv": "papers",
    "arxiv": "papers",
    "abstracts": "papers",
    "fda": "fda",
    "fda/jp": "trials",
    "fda/eu": "trials",
    "trials": "trials",
    "trials/us": "trials",
    "trials/eu": "trials",
    "trials/jp": "trials",
    "trials/cn": "trials",
    "proteins": "proteins",
    "uniprot": "proteins",
}


def _parse_search_output(
    output: str, selected_sources: tuple[str, ...]
) -> tuple[list[dict[str, Any]], list[str], int | None]:
    """Parse Paperclip's CLI display, the only shape `paperclip search` emits."""
    records: list[dict[str, Any]] = []
    result_ids: list[str] = []
    declared_count: int | None = None
    entry_lines: list[str] = []

    def flush() -> None:
        nonlocal entry_lines
        if entry_lines:
            record = _parse_display_entry(entry_lines, selected_sources=selected_sources)
            if record:
                records.append(record)
        entry_lines = []

    def remember(result_id: str | None) -> None:
        if result_id and result_id not in result_ids:
            result_ids.append(result_id)

    for raw_line in _ANSI_ESCAPE.sub("", str(output or "")).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if header := _RESULT_HEADER.match(line):
            flush()
            declared_count = (declared_count or 0) + int(header.group(1))
            remember(header.group(2))
            continue
        if footer := _RESULT_FOOTER.match(line):
            flush()
            remember(footer.group(1))
            continue
        if _ENTRY_START.match(line):
            flush()
            entry_lines = [line]
            continue
        if entry_lines:
            entry_lines.append(line)
    flush()
    return records, result_ids, declared_count


def _parse_display_entry(
    lines: list[str],
    *,
    selected_sources: tuple[str, ...],
) -> dict[str, Any]:
    title = _ENTRY_START.match(lines[0])
    if not title:
        return {}
    record: dict[str, Any] = {"title": title.group(1).strip()}
    metadata_seen = False
    quoted_abstract = False
    abstract_lines: list[str] = []
    for line in lines[1:]:
        if line.startswith("https://"):
            record.setdefault("url", line)
            doi_marker = "doi.org/"
            if doi_marker in line:
                record.setdefault("doi", line.split(doi_marker, 1)[1])
        elif line.startswith('"'):
            record["abstract"] = line.strip('"')
            quoted_abstract = True
        elif not metadata_seen and _UNIPROT_ACCESSION.fullmatch(line.upper()):
            record["record_id"] = line.upper()
            record["accession"] = line.upper()
        elif not metadata_seen and _DOCUMENT_HANDLE.fullmatch(line):
            record["record_id"] = line
        elif not metadata_seen and _METADATA_SEPARATOR in line:
            _apply_metadata_line(record, line)
            metadata_seen = True
        elif not metadata_seen:
            record.setdefault("authors", line)
        elif not quoted_abstract:
            abstract_lines.append(line)
    if abstract_lines and not quoted_abstract:
        record["abstract"] = " ".join(abstract_lines)
    collection = _resolve_collection(record, selected_sources)
    if collection:
        record["collection"] = collection
    source = _resolve_source(record, collection, selected_sources)
    if source:
        record["source"] = source
    return record


def _apply_metadata_line(record: dict[str, Any], line: str) -> None:
    """Read one `a · b · § c` metadata line by part meaning, not by position."""
    free: list[str] = []
    for part in (piece.strip() for piece in line.split(_METADATA_SEPARATOR)):
        if not part:
            continue
        if part.startswith(_SECTION_MARKER):
            section = part[len(_SECTION_MARKER) :].strip()
            if section:
                record["section"] = section
        elif _PUBLISHED.fullmatch(part):
            record["published"] = part
        elif part.lower() in _DISPLAY_SOURCE_LABELS:
            record.setdefault("source", part.lower())
        elif not _PROTEIN_LENGTH.fullmatch(part):
            free.append(part)
    if record.get("accession"):
        if free:
            record["organism"] = free[0]
    elif record.get("record_id"):
        # A handle line already carried the canonical id, so the leading free
        # part is the public registry or application identifier.
        if len(free) >= 2:
            record["external_id"] = free[0]
        if free:
            record["journal"] = free[-1]
    else:
        if free:
            record["record_id"] = free[0]
        if len(free) >= 2:
            record["journal"] = free[1]


def _resolve_collection(
    record: dict[str, Any],
    selected_sources: tuple[str, ...],
) -> str | None:
    handle_collection = _by_handle_prefix(record, _HANDLE_COLLECTIONS)
    if handle_collection:
        return handle_collection
    if record.get("accession"):
        return "proteins"
    collections = {_SOURCE_COLLECTIONS[entry] for entry in selected_sources}
    return collections.pop() if len(collections) == 1 else None


def _resolve_source(
    record: dict[str, Any],
    collection: str | None,
    selected_sources: tuple[str, ...],
) -> str | None:
    if len(selected_sources) == 1:
        return selected_sources[0]
    label = record.get("source")
    if label:
        return str(label)
    prefix_source = _by_handle_prefix(record, _HANDLE_SOURCES)
    if prefix_source:
        return prefix_source
    candidates = [
        entry for entry in selected_sources if _SOURCE_COLLECTIONS[entry] == collection
    ]
    return candidates[0] if len(candidates) == 1 else None


def _by_handle_prefix(record: dict[str, Any], table: dict[str, str]) -> str | None:
    record_id = str(record.get("record_id") or "")
    return next(
        (value for prefix, value in table.items() if record_id.startswith(prefix)),
        None,
    )
