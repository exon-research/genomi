from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from ...runtime.external import file_metadata, matching_manifest, utc_now
from ...runtime.handoff import evidence_context
from ...retrieval import hybrid as retrieval_hybrid
from ...retrieval import semantic as retrieval_semantic

from .constants import (
    EVIDENCE_SCHEMA_VERSION,
    RESEARCH_FINDING_TEXT_MAX_CHARS,
    RESEARCH_SCOPES,
    RESEARCH_TARGET_TYPES,
    research_target_type_choices,
)
from .helpers import (
    _json_object,
)
from .connection import (
    _ensure_schema,
    _insert_research_batch,
    _upsert_metadata,
    connect_evidence,
)



def record_research_findings(evidence_db: str | Path, payload: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    """Persist reviewed source findings captured by the agent or an isolated subagent."""
    evidence_db = Path(evidence_db)
    findings = _research_findings_from_payload(payload)
    if not findings:
        raise ValueError("at least one research finding is required")

    captured_at = utc_now()
    records = [_normalize_research_finding(finding, captured_at=captured_at) for finding in findings]
    finding_ids = [record["finding_id"] for record in records]

    with connect_evidence(evidence_db, attach_shared=False) as connection:
        _ensure_schema(connection)
        existing_ids = {
            row["finding_id"]
            for row in connection.execute(
                f"""
                select finding_id
                from research_findings
                where finding_id in ({', '.join('?' for _ in finding_ids)})
                """,
                finding_ids,
            )
        }
        _insert_research_batch(connection, [_research_record_to_row(record) for record in records])
        _upsert_metadata(connection, "schema_version", EVIDENCE_SCHEMA_VERSION)
        connection.commit()

    inserted = len([finding_id for finding_id in finding_ids if finding_id not in existing_ids])
    return {
        "status": "completed",
        "evidence_db": str(evidence_db),
        "inserted_findings": inserted,
        "updated_findings": len(records) - inserted,
        "finding_text_max_chars": RESEARCH_FINDING_TEXT_MAX_CHARS,
        "findings": [_public_research_record(record) for record in records],
        "evidence_options": _record_research_options(records),
        "notes": [
            "Reviewed source findings were stored for later evidence gathering.",
            "finding.text is intended to be a short exact source excerpt.",
            "Use source_accessed_at when the user asks whether source context is current.",
        ],
    }


def query_research_findings(
    evidence_db: str | Path,
    target_type: str,
    *,
    gene: str | None = None,
    drug: str | None = None,
    condition: str | None = None,
    topic: str | None = None,
    chrom: str | None = None,
    pos: int | None = None,
    ref: str | None = None,
    alt: str | None = None,
    genome_build: str = "GRCh38",
    scope: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    target = _normalize_research_target(
        {
            "type": target_type,
            "gene": gene,
            "drug": drug,
            "condition": condition,
            "topic": topic,
            "chrom": chrom,
            "pos": pos,
            "ref": ref,
            "alt": alt,
            "genome_build": genome_build,
        }
    )
    where = "target_type = ? and target_id = ?"
    params: list[Any] = [target["target_type"], target["target_id"]]
    normalized_scope = _normalize_research_scope(scope) if scope is not None else None
    if normalized_scope is not None:
        where += " and research_scope = ?"
        params.append(normalized_scope)
    params.append(limit)
    with connect_evidence(evidence_db) as connection:
        _ensure_schema(connection)
        rows = [
            _public_research_record(dict(row))
            for row in connection.execute(
                f"""
                select finding_id, target_type, target_id, chrom, pos, ref, alt, gene,
                       drug, condition, topic, genome_build, research_scope,
                       source_title, source_url, source_type, source_published_at,
                       source_accessed_at, searched_query, finding_text, finding_summary,
                       finding_type, captured_by, captured_at, raw_json
                from research_findings
                where {where}
                order by source_accessed_at desc, captured_at desc, source_title
                limit ?
                """,
                params,
            )
        ]
    return {
        "query": {
            "source": "research_findings",
            "target_type": target["target_type"],
            "target_id": target["target_id"],
            "gene": target["gene"],
            "drug": target["drug"],
            "condition": target["condition"],
            "topic": target["topic"],
            "chrom": target["chrom"],
            "pos": target["pos"],
            "ref": target["ref"],
            "alt": target["alt"],
            "genome_build": target["genome_build"],
            "scope": normalized_scope,
        },
        "count": len(rows),
        "records": rows,
        "freshness": _research_freshness_summary(rows),
        "notes": [
            "These are reviewed source excerpts for the selected target.",
            "Use source dates when the user asks whether newer pages, papers, or database updates may exist.",
        ],
    }


def search_research_findings(
    evidence_db: str | Path,
    query: str,
    *,
    target_type: str | None = None,
    scope: str | None = None,
    limit: int = 50,
    semantic_context: object = None,
) -> dict[str, Any]:
    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    tokens = [token.casefold() for token in query.split() if token.strip()]
    if not tokens and not semantic.has_hints:
        raise ValueError("research.search query must contain at least one token")
    if target_type is not None:
        target_type = target_type.strip().lower()
        if target_type not in RESEARCH_TARGET_TYPES:
            raise ValueError(
                "research target type must be one of "
                + ", ".join(repr(target_type) for target_type in research_target_type_choices())
            )
    search_columns = [
        "target_id",
        "gene",
        "drug",
        "condition",
        "topic",
        "source_title",
        "source_url",
        "searched_query",
        "finding_text",
        "finding_summary",
        "finding_type",
    ]
    where_parts: list[str] = []
    params: list[Any] = []
    if target_type is not None:
        where_parts.append("target_type = ?")
        params.append(target_type)
    normalized_scope = _normalize_research_scope(scope) if scope is not None else None
    if normalized_scope is not None:
        where_parts.append("research_scope = ?")
        params.append(normalized_scope)
    with connect_evidence(evidence_db) as connection:
        _ensure_schema(connection)
        rows = [
            _public_research_record(dict(row))
            for row in connection.execute(
                f"""
                select finding_id, target_type, target_id, chrom, pos, ref, alt, gene,
                       drug, condition, topic, genome_build, research_scope, source_title, source_url,
                       source_type, source_published_at, source_accessed_at, searched_query,
                       finding_text, finding_summary, finding_type, captured_by, captured_at, raw_json
                from research_findings
                {f"where {' and '.join(where_parts)}" if where_parts else ""}
                order by source_accessed_at desc, captured_at desc, source_title
                """,
                params,
            )
        ]
    documents = [_research_retrieval_document(record) for record in rows]
    retrieval_queries = _research_retrieval_queries(query=query, semantic=semantic)
    search_result = retrieval_hybrid.search(
        documents=documents,
        queries=retrieval_queries,
        field_weights={
            "target": 4.0,
            "source": 2.0,
            "finding": 3.0,
            "metadata": 1.0,
        },
        limit=limit,
    )
    selected = [hit.payload for hit in search_result["hits"]]
    semantic_usage = _research_semantic_usage(semantic, hits=list(search_result["hits"]), query=query)
    return {
        "query": {
            "source": "research_findings",
            "search": query,
            "tokens": tokens,
            "target_type": target_type,
            "scope": normalized_scope,
            "limit": limit,
        },
        "count": len(selected),
        "records": selected,
        "retrieval": {
            **search_result["diagnostics"],
            "retrieval_streams": semantic_usage["retrieval_streams"],
        },
        "semantic_context": semantic_usage,
        "notes": [
            "Search uses local reviewed research fields and host semantic terms as retrieval inputs.",
            "Use research.query or gathering tools before making target-specific claims.",
        ],
    }


def _research_retrieval_document(record: dict[str, Any]) -> retrieval_hybrid.RetrievalDocument:
    target = record.get("target") if isinstance(record.get("target"), dict) else {}
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    finding = record.get("finding") if isinstance(record.get("finding"), dict) else {}
    fields = {
        "target": " ".join(str(value or "") for value in target.values()),
        "source": " ".join(str(source.get(key) or "") for key in ("title", "url", "type")),
        "finding": " ".join(str(finding.get(key) or "") for key in ("type", "text", "summary")),
        "metadata": " ".join(str(record.get(key) or "") for key in ("captured_by", "captured_at")),
    }
    return retrieval_hybrid.RetrievalDocument(
        doc_id=str(record.get("finding_id") or _record_digest(record)),
        fields=fields,
        payload=record,
        facets={
            "target_type": [str(target.get("type") or record.get("target_type") or "")],
            "scope": [str(record.get("research_scope") or "")],
        },
    )


def _research_retrieval_queries(*, query: str, semantic: retrieval_semantic.SemanticContext) -> list[retrieval_hybrid.RetrievalQuery]:
    queries: list[retrieval_hybrid.RetrievalQuery] = []
    if query:
        queries.append(retrieval_hybrid.RetrievalQuery(text=query, stream="query", weight=1.0))
    if semantic.raw_query and semantic.raw_query != query:
        queries.append(retrieval_hybrid.RetrievalQuery(text=semantic.raw_query, stream="semantic:raw_query", weight=1.0))
    for index, text in enumerate(retrieval_semantic.search_terms(semantic), start=1):
        queries.append(retrieval_hybrid.RetrievalQuery(text=text, stream=f"semantic:host_term:{index}", weight=0.7))
    return queries


def _research_semantic_usage(
    semantic: retrieval_semantic.SemanticContext,
    *,
    hits: list[retrieval_hybrid.RetrievalHit],
    query: str,
) -> dict[str, Any]:
    term_matches: list[dict[str, Any]] = []
    term_misses: list[dict[str, Any]] = []
    terms = retrieval_semantic.search_terms(semantic)
    for index, text in enumerate(terms, start=1):
        stream = f"semantic:host_term:{index}"
        matched = [hit.doc_id for hit in hits if any(str(detail.get("stream") or "") == stream for detail in hit.streams)]
        if matched:
            term_matches.append(
                {
                    "text": text,
                    "status": "hit",
                    "match_type": "matched_stored_reviewed_research_fields",
                    "matched_record_ids": matched[:5],
                }
            )
        else:
            term_misses.append({"text": text, "status": "miss"})
    return retrieval_semantic.term_usage_payload(
        semantic,
        term_matches=term_matches,
        term_misses=term_misses,
        streams=retrieval_semantic.retrieval_streams(
            raw_query=semantic.raw_query or query,
            host_terms=terms,
        ),
    )


def _research_findings_from_payload(payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("research payload must be a JSON object or list")
    findings = payload.get("findings")
    if findings is None:
        return [payload]
    if not isinstance(findings, list):
        raise ValueError("research payload field 'findings' must be a list")
    return findings


def _normalize_research_finding(item: dict[str, Any], *, captured_at: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("each research finding must be an object")
    target = _normalize_research_target(item.get("target") or item)
    source = item.get("source") or {}
    finding = item.get("finding") or {}

    source_title = _required_research_string(source, item, "title", "source_title")
    source_url = _required_research_string(source, item, "url", "source_url")
    if not (source_url.startswith("https://") or source_url.startswith("http://")):
        raise ValueError("source.url must start with http:// or https://")

    finding_text = _required_research_string(finding, item, "text", "finding_text")
    if len(finding_text) > RESEARCH_FINDING_TEXT_MAX_CHARS:
        raise ValueError(
            f"finding.text must be <= {RESEARCH_FINDING_TEXT_MAX_CHARS} characters; "
            "store a short exact excerpt, not the full source text"
        )
    normalized = {
        **target,
        "research_scope": _normalize_research_scope(item.get("scope") or item.get("research_scope")),
        "source_title": source_title,
        "source_url": source_url,
        "source_type": _optional_research_string(source, item, "type", "source_type"),
        "source_published_at": _optional_research_string(source, item, "published_at", "source_published_at"),
        "source_accessed_at": _optional_research_string(source, item, "accessed_at", "source_accessed_at") or captured_at,
        "searched_query": item.get("searched_query") or item.get("query"),
        "finding_text": finding_text,
        "finding_summary": finding.get("summary") or item.get("finding_summary"),
        "finding_type": finding.get("type") or item.get("finding_type"),
        "captured_by": item.get("captured_by") or "agent",
        "captured_at": captured_at,
        "raw_json": json.dumps(item, sort_keys=True),
    }
    normalized["finding_id"] = item.get("finding_id") or _research_finding_id(normalized)
    return normalized


def _normalize_research_target(raw: dict[str, Any]) -> dict[str, Any]:
    target_type = str(raw.get("type") or raw.get("target_type") or "").strip().lower()
    if target_type not in RESEARCH_TARGET_TYPES:
        raise ValueError(
            "research target type must be one of "
            + ", ".join(repr(target_type) for target_type in research_target_type_choices())
        )
    genome_build = str(raw.get("genome_build") or "GRCh38")
    if target_type == "gene":
        gene = str(raw.get("gene") or "").strip().upper()
        if not gene:
            raise ValueError("gene research target requires gene")
        return {
            "target_type": "gene",
            "target_id": f"gene:{gene}",
            "chrom": None,
            "pos": None,
            "ref": None,
            "alt": None,
            "gene": gene,
            "drug": None,
            "condition": None,
            "topic": None,
            "genome_build": genome_build,
        }

    if target_type in {"drug", "condition", "topic"}:
        value = _target_text_value(raw, target_type)
        return {
            "target_type": target_type,
            "target_id": f"{target_type}:{_target_text_key(value)}",
            "chrom": None,
            "pos": None,
            "ref": None,
            "alt": None,
            "gene": None,
            "drug": value if target_type == "drug" else None,
            "condition": value if target_type == "condition" else None,
            "topic": value if target_type == "topic" else None,
            "genome_build": None,
        }

    chrom = str(raw.get("chrom") or "").strip()
    ref = str(raw.get("ref") or "").strip()
    alt = str(raw.get("alt") or "").strip()
    if not chrom or not ref or not alt:
        raise ValueError("variant research target requires chrom, pos, ref, and alt")
    try:
        pos = int(raw.get("pos"))
    except (TypeError, ValueError) as exc:
        raise ValueError("variant research target requires integer pos") from exc
    gene_raw = raw.get("gene")
    gene = str(gene_raw).strip().upper() if gene_raw else None
    return {
        "target_type": "variant",
        "target_id": f"variant:{genome_build}:{chrom}-{pos}-{ref}-{alt}",
        "chrom": chrom,
        "pos": pos,
        "ref": ref,
        "alt": alt,
        "gene": gene,
        "drug": None,
        "condition": None,
        "topic": None,
        "genome_build": genome_build,
    }


def _target_text_value(raw: dict[str, Any], field: str) -> str:
    value = str(raw.get(field) or raw.get("name") or raw.get("target") or "").strip()
    value = " ".join(value.split())
    if not value:
        raise ValueError(f"{field} research target requires {field}")
    return value


def _target_text_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _normalize_research_scope(raw: Any) -> str:
    value = str(raw or "shared").strip().lower()
    aliases = {
        "public": "shared",
        "reusable": "shared",
        "shared_public": "shared",
        "user": "private",
        "personal": "private",
        "user_private": "private",
    }
    value = aliases.get(value, value)
    if value not in RESEARCH_SCOPES:
        raise ValueError("research scope must be 'shared' or 'private'")
    return value


def _required_research_string(primary: dict[str, Any], fallback: dict[str, Any], primary_key: str, fallback_key: str) -> str:
    value = primary.get(primary_key)
    if value is None:
        value = fallback.get(fallback_key)
    value = str(value).strip() if value is not None else ""
    if not value:
        raise ValueError(f"research finding requires {primary_key} / {fallback_key}")
    return value


def _optional_research_string(primary: dict[str, Any], fallback: dict[str, Any], primary_key: str, fallback_key: str) -> str | None:
    value = primary.get(primary_key)
    if value is None:
        value = fallback.get(fallback_key)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _research_finding_id(record: dict[str, Any]) -> str:
    identity = {
        "target_id": record["target_id"],
        "source_url": record["source_url"],
        "finding_text": " ".join(record["finding_text"].split()),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
    return f"research:{digest[:24]}"


def _research_record_to_row(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record["finding_id"],
        record["target_type"],
        record["target_id"],
        record["chrom"],
        record["pos"],
        record["ref"],
        record["alt"],
        record["gene"],
        record["drug"],
        record["condition"],
        record["topic"],
        record["genome_build"],
        record["research_scope"],
        record["source_title"],
        record["source_url"],
        record["source_type"],
        record["source_published_at"],
        record["source_accessed_at"],
        record["searched_query"],
        record["finding_text"],
        record["finding_summary"],
        record["finding_type"],
        record["captured_by"],
        record["captured_at"],
        record["raw_json"],
    )


def _public_research_record(record: dict[str, Any]) -> dict[str, Any]:
    raw = _json_object(record.get("raw_json"))
    source = {
        "title": record["source_title"],
        "url": record["source_url"],
        "type": record.get("source_type"),
        "published_at": record.get("source_published_at"),
        "accessed_at": record["source_accessed_at"],
    }
    source.update(_public_research_source_extras(record.get("raw_json")))
    return {
        "finding_id": record["finding_id"],
        "target": {
            "type": record["target_type"],
            "id": record["target_id"],
            "chrom": record.get("chrom"),
            "pos": record.get("pos"),
            "ref": record.get("ref"),
            "alt": record.get("alt"),
            "gene": record.get("gene"),
            "drug": record.get("drug"),
            "condition": record.get("condition"),
            "topic": record.get("topic"),
            "genome_build": record.get("genome_build"),
        },
        "source": source,
        "scope": record.get("research_scope") or record.get("scope") or "shared",
        "finding": {
            "text": record["finding_text"],
            "summary": record.get("finding_summary"),
            "type": record.get("finding_type"),
        },
        "searched_query": record.get("searched_query"),
        "captured_by": record["captured_by"],
        "captured_at": record["captured_at"],
        **_public_research_verification_extras(raw),
    }


def _public_research_verification_extras(raw: dict[str, Any]) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    for key in ("verified_fields", "support_spans", "verification_status"):
        value = raw.get(key)
        if value is not None and value != [] and value != {}:
            extras[key] = value
    return extras


def _public_research_source_extras(raw_json: object) -> dict[str, Any]:
    raw = _json_object(raw_json)
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    extras: dict[str, Any] = {}
    for key in (
        "source_id",
        "artifact",
        "artifact_metadata",
        "pmid",
        "citation",
        "citations",
        "api_url",
        "swagger_url",
        "biomarkers_url",
        "associations_url",
    ):
        value = source.get(key)
        if value is not None and value != []:
            extras[key] = value
    return extras


def _record_research_options(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for record in records:
        if record["target_type"] == "variant":
            key = ("variant", record["chrom"], record["pos"], record["ref"], record["alt"], record["genome_build"])
            if key in seen:
                continue
            seen.add(key)
            options.append(
                {
                    "component": "variant_reviewed_source_context",
                    "state": "stored_research_available",
                    "available_operation": "variant.gather_allele_context",
                    "target_type": "variant",
                    "target": {
                        "chrom": record["chrom"],
                        "pos": record["pos"],
                        "ref": record["ref"],
                        "alt": record["alt"],
                        "genome_build": record["genome_build"],
                    },
                    "evidence_context": evidence_context(
                        "research",
                        reason="Recorded variant research must be consumed by a refreshed gather-allele result.",
                    ),
                }
            )
        elif record["target_type"] == "gene":
            key = ("gene", record["gene"], record["genome_build"])
            if key in seen:
                continue
            seen.add(key)
            options.append(
                {
                    "component": "gene_reviewed_source_context",
                    "state": "stored_research_available",
                    "available_operation": "variant.gather_gene_context",
                    "target_type": "gene",
                    "target": {"gene": record["gene"], "genome_build": record["genome_build"]},
                    "evidence_context": evidence_context(
                        "research",
                        reason="Recorded gene research must be consumed by refreshed gene or variant context before interpretation.",
                    ),
                }
            )
        elif record["target_type"] in {"drug", "condition", "topic"}:
            key = (record["target_type"], record["target_id"])
            if key in seen:
                continue
            seen.add(key)
            options.append(
                {
                    "component": f"{record['target_type']}_reviewed_source_context",
                    "state": "stored_research_available",
                    "available_operation": "research.query",
                    "target_type": record["target_type"],
                    "target_id": record["target_id"],
                    "evidence_context": evidence_context(
                        "research",
                        reason="Recorded topic/drug/condition research must be queried and attached to structured claims before reporting.",
                    ),
                }
            )
    return options


def _research_freshness_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "status": "no_reviewed_sources",
            "latest_upstream_checked": False,
            "note": "No reviewed source findings exist for this target.",
        }
    accessed_at = sorted(
        source["accessed_at"]
        for record in records
        for source in [record["source"]]
        if source.get("accessed_at")
    )
    return {
        "status": "reviewed_sources_available",
        "latest_upstream_checked": False,
        "latest_source_accessed_at": accessed_at[-1] if accessed_at else None,
        "source_count": len({record["source"]["url"] for record in records}),
        "note": (
            "Reviewed source evidence is available for this target. "
            "Use source dates when the user asks for latest interpretation."
        ),
    }


def _research_evidence_for_variant(
    evidence_db: str | Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    genome_build: str,
    gene_symbols: list[str],
) -> dict[str, Any]:
    exact_variant = query_research_findings(
        evidence_db,
        "variant",
        chrom=chrom,
        pos=pos,
        ref=ref,
        alt=alt,
        genome_build=genome_build,
        limit=20,
    )
    genes = {
        gene: query_research_findings(
            evidence_db,
            "gene",
            gene=gene,
            genome_build=genome_build,
            limit=20,
        )
        for gene in gene_symbols
    }
    return {
        "exact_variant": exact_variant,
        "genes": genes,
    }
