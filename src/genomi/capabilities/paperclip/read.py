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


COLLECTIONS = ("papers", "fda", "trials")
Runner = Callable[..., subprocess.CompletedProcess[str]]
_DOCUMENT_ID = re.compile(r"^[A-Za-z0-9_.:-]+$")
_LINE = re.compile(r"^L(\d+):(.*)$")
_METADATA_ALIASES = {
    "external_id": ("identifier",),
    "title": ("title", "tradename"),
    "authors": ("authors", "author"),
    "published": ("pub_date", "pub_year", "publication_date", "year", "publication_year"),
    "journal": ("journal", "venue"),
    "doi": ("doi",),
    "pmcid": ("pmc_id", "pmcid"),
    "pmid": ("pmid", "pubmed_id"),
    "source": ("source", "database", "source_type"),
    "url": ("url", "link", "public_url"),
    "abstract": ("abstract", "snippet", "summary"),
}


def retrieve_document_evidence(
    *,
    document_id: str,
    collection: str,
    patterns: list[str],
    max_excerpts: int = 8,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    clean_id = document_id.strip()
    clean_collection = collection.strip().lower()
    clean_patterns = [pattern.strip() for pattern in patterns if pattern.strip()]
    if not clean_id or not _DOCUMENT_ID.fullmatch(clean_id):
        raise ValueError("paperclip.retrieve_document_evidence requires a public document_id")
    if clean_collection not in COLLECTIONS:
        raise ValueError(f"unsupported Paperclip collection: {collection}")
    if not 1 <= len(clean_patterns) <= 5:
        raise ValueError("patterns must contain between 1 and 5 terms")
    if any(len(pattern) > 160 for pattern in clean_patterns):
        raise ValueError("each evidence pattern must be at most 160 characters")
    if not 1 <= max_excerpts <= 20:
        raise ValueError("max_excerpts must be between 1 and 20")

    query_scope = {
        "document_id": clean_id,
        "collection": clean_collection,
        "patterns": clean_patterns,
    }
    credentials = resolve_external_credentials("paperclip")
    executable = shutil.which("paperclip")
    if not credentials.configured or not executable:
        reason = "credential_missing" if not credentials.configured else "client_missing"
        return _unavailable(query_scope, reason)

    child_environment = dict(os.environ)
    for unrelated_key in ("BIOHUB_API_KEY", "ESM_API_KEY", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"):
        child_environment.pop(unrelated_key, None)
    child_environment["PAPERCLIP_API_KEY"] = credentials.values["api_key"]
    document_root = f"/{clean_collection}/{clean_id}"
    metadata_result = _run(
        runner,
        [executable, "cat", f"{document_root}/meta.json"],
        child_environment,
    )
    if metadata_result is None:
        return _unavailable(query_scope, "metadata_request_failed")
    metadata_payload = _decode_json_prefix(metadata_result.stdout)
    if not isinstance(metadata_payload, dict):
        return _unavailable(query_scope, "invalid_metadata_response")

    literal_pattern = "(" + "|".join(re.escape(pattern) for pattern in clean_patterns) + ")"
    evidence_result = _run(
        runner,
        [
            executable,
            "grep",
            literal_pattern,
            f"{document_root}/content.lines",
            "-m",
            str(max_excerpts),
        ],
        child_environment,
    )
    if evidence_result is None:
        return _unavailable(query_scope, "evidence_request_failed")

    excerpts = _parse_excerpts(
        evidence_result.stdout,
        collection=clean_collection,
        document_id=clean_id,
    )
    document = _normalize_document(metadata_payload)
    # The handle the caller read is the addressable id, and the one the
    # excerpt citation URLs point at.
    document["record_id"] = clean_id
    document["collection"] = clean_collection
    coverage = {
        "consulted_sources": [f"paperclip:{clean_collection}/{clean_id}"],
        "source_status": "consulted",
    }
    if excerpts:
        envelope = evidence_envelope.evidence_present(
            operation="paperclip.retrieve_document_evidence",
            query_scope=query_scope,
            coverage=coverage,
            observations={"observation_count": len(excerpts)},
            answer_readiness=evidence_envelope.SCOPED_ANSWER_ONLY,
            guidance=["evidence_present:anchor_claims_to_line_pinned_public_source"],
        )
        status = "completed"
    else:
        envelope = evidence_envelope.empty_consulted_scope(
            operation="paperclip.retrieve_document_evidence",
            query_scope=query_scope,
            coverage=coverage,
            guidance=["not_observed_in_consulted_scope:do_not_imply_biomedical_negative"],
        )
        status = "in_scope_empty"
    return {
        "status": status,
        "provider": "paperclip",
        "document": document,
        "excerpts": excerpts,
        "evidence_envelope": envelope,
    }


def _decode_json_prefix(text: str) -> Any:
    """Paperclip `cat` prints JSON followed by a timing trailer."""
    try:
        payload, _ = json.JSONDecoder().raw_decode(str(text or "").lstrip())
    except (TypeError, json.JSONDecodeError):
        return None
    return payload


def _normalize_document(row: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for target, names in _METADATA_ALIASES.items():
        value = next((row.get(name) for name in names if row.get(name) not in (None, "", [])), None)
        if value is not None:
            normalized[target] = value if target != "published" else str(value)
    if normalized.get("doi") and not normalized.get("url"):
        normalized["url"] = f"https://doi.org/{normalized['doi']}"
    return normalized


def _run(
    runner: Runner,
    command: list[str],
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str] | None:
    try:
        completed = runner(
            command,
            env=environment,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed if completed.returncode == 0 else None


def _parse_excerpts(
    output: str,
    *,
    collection: str,
    document_id: str,
) -> list[dict[str, Any]]:
    excerpts: list[dict[str, Any]] = []
    for line in str(output or "").splitlines():
        match = _LINE.match(line.strip())
        if not match:
            continue
        line_number = int(match.group(1))
        excerpts.append(
            {
                "line_start": line_number,
                "line_end": line_number,
                "text": match.group(2).strip(),
                "citation_url": (
                    f"https://paperclip.gxl.ai/citations/{collection}/{document_id}#L{line_number}"
                ),
            }
        )
    return excerpts


def _unavailable(query_scope: dict[str, Any], reason_code: str) -> dict[str, Any]:
    return {
        "status": "source_unavailable",
        "provider": "paperclip",
        "reason_code": reason_code,
        "evidence_envelope": evidence_envelope.not_assessed(
            operation="paperclip.retrieve_document_evidence",
            reason=reason_code,
            query_scope=query_scope,
            coverage={"consulted_sources": [], "source_status": "unavailable"},
            guidance=["not_assessed:retry_external_source_or_use_another_source"],
        ),
    }
