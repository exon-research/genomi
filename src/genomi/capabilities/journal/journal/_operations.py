from __future__ import annotations

from ....runtime import context as runtime_context
from ....retrieval import hybrid as retrieval_hybrid
from ....retrieval import semantic as retrieval_semantic

from ._constants import (
    CLAIM_LIKE_ENTRY_TYPES,
    JOURNAL_SCHEMA,
    MEMORY_ARTIFACT_SCHEMA,
    JournalError,
    JsonObject,
)
from ._helpers import (
    _all_matching_entries,
    _assert_links_allowed,
    _compact_entry,
    _connect,
    _ensure_notebook,
    _entry_matches,
    _hydrate_entry,
    _include_private_evidence,
    _init_schema,
    _insert_link,
    _is_private_evidence_link,
    _journal_retrieval_document,
    _json_dumps,
    _locate_entry,
    _memory_type,
    _most_used_evidence_sources,
    _new_id,
    _normalize_decision_status,
    _normalize_link,
    _normalize_tags,
    _normalize_target,
    _notebook_for_entry,
    _now,
    _optional_text,
    _public_notebook,
    _required_text,
    _selected_scopes,
    _tokens,
    _validate_amendment_type,
    _validate_entry_type,
    _validate_scope,
    journal_db_path,
)


def append_entry(
    *,
    scope: str | None = None,
    entry_type: str | None = None,
    content: str | None = None,
    title: str | None = None,
    tags: object = None,
    target: object = None,
    evidence_links: list[JsonObject] | None = None,
    decision_status: str | None = None,
    created_by: str | None = None,
    entry_id: str | None = None,
    amendment_type: str | None = None,
    rationale: str | None = None,
) -> JsonObject:
    normalized_links = [_normalize_link(link) for link in (evidence_links or [])]

    if entry_id not in (None, ""):
        return _append_to_existing_entry(
            entry_id=_required_text(entry_id, "entry_id"),
            scope=scope,
            evidence_links=normalized_links,
            amendment_content=content,
            amendment_type=amendment_type,
            rationale=rationale,
        )

    selected_scope = _validate_scope(scope)
    normalized_type = _validate_entry_type(entry_type)
    _assert_links_allowed(selected_scope, normalized_links)
    normalized_status = _normalize_decision_status(decision_status)
    warnings: list[str] = []
    if normalized_type in CLAIM_LIKE_ENTRY_TYPES and not normalized_links and normalized_status is None:
        normalized_status = "unresolved"
        warnings.append("Claim-like entry had no evidence links; decision_status was set to unresolved.")

    entry_id = _new_id("entry")
    now = _now()
    path = journal_db_path(selected_scope)
    with _connect(path) as connection:
        _init_schema(connection)
        notebook = _ensure_notebook(connection, selected_scope)
        connection.execute(
            """
            insert into journal_entries(
              entry_id, notebook_id, entry_type, title, content, decision_status,
              target_json, tags_json, created_by, created_at, updated_at, superseded_by
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null)
            """,
            (
                entry_id,
                notebook["notebook_id"],
                normalized_type,
                _optional_text(title),
                _required_text(content, "content"),
                normalized_status,
                _json_dumps(_normalize_target(target)),
                _json_dumps(_normalize_tags(tags)),
                _optional_text(created_by) or "host_agent",
                now,
                now,
            ),
        )
        for link in normalized_links:
            _insert_link(connection, entry_id, link, now)
        entry = _hydrate_entry(connection, entry_id, include_private_evidence=_include_private_evidence())

    return {
        "schema": JOURNAL_SCHEMA,
        "status": "completed",
        "journal_scope": selected_scope,
        "notebook": _public_notebook(notebook),
        "entry": entry,
        "warnings": warnings,
    }


def _append_to_existing_entry(
    *,
    entry_id: str,
    scope: str | None,
    evidence_links: list[JsonObject],
    amendment_content: str | None,
    amendment_type: str | None,
    rationale: str | None = None,
) -> JsonObject:
    normalized_type = _validate_amendment_type(amendment_type)
    has_amendment = amendment_content not in (None, "")
    if not has_amendment and not evidence_links:
        raise JournalError("invalid_params", "Provide content and/or evidence_links when entry_id is supplied.")
    located = _locate_entry(_required_text(entry_id, "entry_id"), scope=scope)
    if located is None:
        raise JournalError("not_found", f"Journal entry not found: {entry_id}")
    selected_scope, path = located
    _assert_links_allowed(selected_scope, evidence_links)
    now = _now()
    amendment: JsonObject | None = None
    with _connect(path) as connection:
        _init_schema(connection)
        if has_amendment:
            amendment_id = _new_id("amendment")
            connection.execute(
                """
                insert into journal_amendments(amendment_id, entry_id, amendment_type, content, rationale, created_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    amendment_id,
                    entry_id,
                    normalized_type,
                    _required_text(amendment_content, "content"),
                    _optional_text(rationale),
                    now,
                ),
            )
            amendment = {
                "amendment_id": amendment_id,
                "entry_id": entry_id,
                "amendment_type": normalized_type,
                "content": amendment_content,
                "rationale": rationale,
                "created_at": now,
            }
        for link in evidence_links:
            _insert_link(connection, entry_id, link, now)
        connection.execute("update journal_entries set updated_at = ? where entry_id = ?", (now, entry_id))
        entry = _hydrate_entry(connection, entry_id, include_private_evidence=_include_private_evidence())
        notebook = _notebook_for_entry(connection, entry_id)
    result: JsonObject = {
        "schema": JOURNAL_SCHEMA,
        "status": "completed",
        "journal_scope": selected_scope,
        "notebook": _public_notebook(notebook),
        "entry": entry,
    }
    if amendment is not None:
        result["amendment"] = amendment
    return result


def search_entries(
    *,
    scope: str | None = None,
    text: str | None = None,
    target: object = None,
    tag: str | None = None,
    tags: object = None,
    entry_type: str | None = None,
    limit: int = 25,
    semantic_context: object = None,
) -> JsonObject:
    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    selected_scopes = _selected_scopes(scope)
    normalized_type = _validate_entry_type(entry_type) if entry_type else None
    requested_tags = _normalize_tags(tags)
    if tag:
        requested_tags.append(tag)
    requested_tags = sorted(set(requested_tags))
    normalized_target = _normalize_target(target) if target not in (None, "") else None
    tokens = _tokens(text or "")
    filter_tokens = [] if semantic.has_hints else tokens
    entries: list[JsonObject] = []
    for selected_scope in selected_scopes:
        path = journal_db_path(selected_scope)
        if not path.exists():
            continue
        with _connect(path) as connection:
            _init_schema(connection)
            for row in connection.execute("select entry_id from journal_entries order by created_at desc"):
                entry = _hydrate_entry(connection, row["entry_id"], include_private_evidence=runtime_context.agi_access_approved())
                if _entry_matches(entry, entry_type=normalized_type, tags=requested_tags, target=normalized_target, tokens=filter_tokens):
                    entries.append(entry)
    entries.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    selected_limit = max(1, int(limit or 25))
    retrieval_payload: JsonObject | None = None
    semantic_usage = retrieval_semantic.term_usage_payload(
        semantic,
        streams=retrieval_semantic.retrieval_streams(
            raw_query=semantic.raw_query or text,
            host_terms=retrieval_semantic.search_terms(semantic),
            private_metadata=runtime_context.agi_access_approved(),
        ),
    )
    if semantic.has_hints:
        semantic_entries = _semantic_journal_entries(
            entries,
            text=text,
            semantic=semantic,
            limit=selected_limit,
        )
        entries = semantic_entries["entries"]
        retrieval_payload = semantic_entries["retrieval"]
        semantic_usage = semantic_entries["semantic_context"]
    return {
        "schema": JOURNAL_SCHEMA,
        "status": "completed",
        "query": {
            "scope": scope or "session_and_project",
            "text": text,
            "target": normalized_target,
            "tags": requested_tags,
            "entry_type": normalized_type,
            "limit": selected_limit,
        },
        "count": min(len(entries), selected_limit),
        "total_matches": len(entries),
        "entries": entries[:selected_limit],
        **({"retrieval": retrieval_payload} if retrieval_payload is not None else {}),
        "semantic_context": semantic_usage,
    }


def summarize_notebook(*, scope: str | None = None, limit: int = 8) -> JsonObject:
    entries = _all_matching_entries(scope)
    selected_limit = max(1, int(limit or 8))
    observations = [entry for entry in entries if entry["entry_type"] == "observation"]
    decisions = [entry for entry in entries if entry["entry_type"] == "decision"]
    contradictions = [entry for entry in entries if entry["entry_type"] == "contradiction"]
    unresolved = [
        entry
        for entry in entries
        if entry["entry_type"] == "unresolved_question" or entry.get("decision_status") in {"unresolved", "unsupported"}
    ]
    return {
        "schema": JOURNAL_SCHEMA,
        "status": "completed",
        "scope": scope or "session_and_project",
        "entry_count": len(entries),
        "summary": {
            "key_observations": [_compact_entry(entry) for entry in observations[:selected_limit]],
            "decisions": [_compact_entry(entry) for entry in decisions[:selected_limit]],
            "contradictions": [_compact_entry(entry) for entry in contradictions[:selected_limit]],
            "unresolved_questions": [_compact_entry(entry) for entry in unresolved[:selected_limit]],
            "most_used_evidence_sources": _most_used_evidence_sources(entries, selected_limit),
        },
    }


def export_memory_artifact(*, scope: str | None = None, include_private_evidence: bool = False) -> JsonObject:
    if include_private_evidence and not runtime_context.agi_access_approved():
        raise JournalError(
            "active_genome_index_approval_required",
            "Explicit Active Genome Index access approval is required before exporting private evidence links.",
        )
    entries = _all_matching_entries(scope, include_private_evidence=include_private_evidence)
    memories = []
    private_omitted = 0
    for entry in entries:
        public_links = []
        omitted_for_entry = 0
        for link in entry.get("evidence_links") or []:
            if link.get("private_evidence_omitted"):
                omitted_for_entry += 1
                continue
            if _is_private_evidence_link(link) and not include_private_evidence:
                omitted_for_entry += 1
                continue
            public_links.append(link)
        private_omitted += omitted_for_entry
        memory_type = _memory_type(entry, public_links)
        memories.append(
            {
                "memory_id": entry["entry_id"],
                "memory_type": memory_type,
                "text": entry.get("content"),
                "metadata": {
                    "scope": entry.get("scope"),
                    "entry_type": entry.get("entry_type"),
                    "title": entry.get("title"),
                    "decision_status": entry.get("decision_status"),
                    "target": entry.get("target") or {},
                    "tags": entry.get("tags") or [],
                    "evidence_links": public_links,
                    "private_evidence_omitted_count": omitted_for_entry,
                    "created_at": entry.get("created_at"),
                    "updated_at": entry.get("updated_at"),
                },
            }
        )
    return {
        "schema": MEMORY_ARTIFACT_SCHEMA,
        "status": "completed",
        "format": "memos-compatible-json",
        "generated_at": _now(),
        "scope": scope or "session_and_project",
        "privacy": {
            "private_evidence_included": include_private_evidence,
            "private_evidence_omitted_count": private_omitted,
            "rule": "Private evidence links are omitted unless explicitly requested and approved for this session.",
        },
        "memories": memories,
    }


def journal_inventory() -> JsonObject:
    session_path = journal_db_path("session")
    project_path = journal_db_path("project")
    return {
        "session_journal": {
            "type": "sqlite",
            "exists": session_path.exists(),
            "privacy_scope": "session_private_or_public_target_notes",
        },
        "project_journal": {
            "type": "sqlite",
            "exists": project_path.exists(),
            "privacy_scope": "public_target_scoped_notes",
        },
    }


def _semantic_journal_entries(
    entries: list[JsonObject],
    *,
    text: str | None,
    semantic: retrieval_semantic.SemanticContext,
    limit: int,
) -> JsonObject:
    documents = [_journal_retrieval_document(entry) for entry in entries]
    queries: list[retrieval_hybrid.RetrievalQuery] = []
    if text:
        queries.append(retrieval_hybrid.RetrievalQuery(text=text, stream="query", weight=1.0))
    if semantic.raw_query and semantic.raw_query != text:
        queries.append(retrieval_hybrid.RetrievalQuery(text=semantic.raw_query, stream="semantic:raw_query", weight=1.0))
    terms = retrieval_semantic.search_terms(semantic)
    for index, term in enumerate(terms, start=1):
        queries.append(retrieval_hybrid.RetrievalQuery(text=term, stream=f"semantic:host_term:{index}", weight=0.7))
    result = retrieval_hybrid.search(
        documents=documents,
        queries=queries,
        field_weights={"title": 2.0, "content": 3.0, "target": 2.0, "tags": 1.0, "evidence": 0.5},
        limit=limit,
    )
    term_matches: list[JsonObject] = []
    term_misses: list[JsonObject] = []
    for index, term in enumerate(terms, start=1):
        stream = f"semantic:host_term:{index}"
        matched = [hit.doc_id for hit in result["hits"] if any(str(detail.get("stream") or "") == stream for detail in hit.streams)]
        if matched:
            term_matches.append(
                {
                    "text": term,
                    "status": "hit",
                    "match_type": "matched_journal_entry_fields",
                    "matched_entry_ids": matched[:5],
                }
            )
        else:
            term_misses.append({"text": term, "status": "miss"})
    return {
        "entries": [hit.payload for hit in result["hits"]],
        "retrieval": {
            **result["diagnostics"],
            "retrieval_streams": retrieval_semantic.retrieval_streams(
                raw_query=semantic.raw_query or text,
                host_terms=terms,
                private_metadata=runtime_context.agi_access_approved(),
            ),
        },
        "semantic_context": retrieval_semantic.term_usage_payload(
            semantic,
            term_matches=term_matches,
            term_misses=term_misses,
            streams=retrieval_semantic.retrieval_streams(
                raw_query=semantic.raw_query or text,
                host_terms=terms,
                private_metadata=runtime_context.agi_access_approved(),
            ),
        ),
    }
