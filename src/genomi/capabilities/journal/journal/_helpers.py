from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ....runtime import context as runtime_context
from ....runtime.paths import genomi_data_root
from ....runtime.sqlite_support import LONG_WRITE_BUSY_TIMEOUT_SECONDS, connect_sqlite
from ....retrieval import hybrid as retrieval_hybrid

from ._constants import (
    AMENDMENT_TYPES,
    DECISION_STATUSES,
    ENTRY_TYPES,
    JOURNALS_DIR_NAME,
    JOURNAL_DB_NAME,
    PRIVATE_OPERATION_PREFIXES,
    PRIVATE_OPERATIONS,
    PRIVATE_PAYLOAD_KEYS,
    PRIVATE_SCOPE_MARKERS,
    JournalError,
    JsonObject,
)


def journal_db_path(scope: str) -> Path:
    selected_scope = _validate_scope(scope)
    if selected_scope == "session":
        return runtime_context.context_path().parent / JOURNAL_DB_NAME
    return genomi_data_root() / JOURNALS_DIR_NAME / "projects" / _workspace_scope_id() / JOURNAL_DB_NAME


def _selected_scopes(scope: str | None) -> list[str]:
    if scope in (None, ""):
        return ["session", "project"]
    return [_validate_scope(scope)]


def _all_matching_entries(scope: str | None, *, include_private_evidence: bool | None = None) -> list[JsonObject]:
    include_private = _include_private_evidence() if include_private_evidence is None else include_private_evidence
    entries: list[JsonObject] = []
    for selected_scope in _selected_scopes(scope):
        path = journal_db_path(selected_scope)
        if not path.exists():
            continue
        with _connect(path) as connection:
            _init_schema(connection)
            for row in connection.execute("select entry_id from journal_entries order by created_at desc"):
                entries.append(_hydrate_entry(connection, row["entry_id"], include_private_evidence=include_private))
    entries.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return entries


def _connect(path: Path) -> sqlite3.Connection:
    return connect_sqlite(
        path,
        timeout_seconds=LONG_WRITE_BUSY_TIMEOUT_SECONDS,
        create_parent=True,
        wal=True,
        foreign_keys=True,
    )


def _include_private_evidence() -> bool:
    return runtime_context.agi_access_approved()


def _init_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        create table if not exists notebooks (
          notebook_id text primary key,
          scope text not null,
          scope_id text not null,
          title text not null,
          privacy_scope text not null,
          created_at text not null,
          updated_at text not null
        );

        create unique index if not exists notebooks_scope_idx on notebooks(scope, scope_id);

        create table if not exists journal_entries (
          entry_id text primary key,
          notebook_id text not null references notebooks(notebook_id) on delete cascade,
          entry_type text not null,
          title text,
          content text not null,
          decision_status text,
          target_json text not null,
          tags_json text not null,
          created_by text not null,
          created_at text not null,
          updated_at text not null,
          superseded_by text
        );

        create index if not exists journal_entries_notebook_idx on journal_entries(notebook_id, created_at);
        create index if not exists journal_entries_type_idx on journal_entries(entry_type);

        create table if not exists journal_evidence_links (
          link_id text primary key,
          entry_id text not null references journal_entries(entry_id) on delete cascade,
          operation text not null,
          evidence_id text,
          finding_id text,
          coverage_state text,
          input_digest text,
          output_digest text,
          source_url text,
          linked_payload_json text not null,
          created_at text not null
        );

        create index if not exists journal_evidence_links_entry_idx on journal_evidence_links(entry_id);
        create index if not exists journal_evidence_links_operation_idx on journal_evidence_links(operation);

        create table if not exists journal_amendments (
          amendment_id text primary key,
          entry_id text not null references journal_entries(entry_id) on delete cascade,
          amendment_type text not null,
          content text not null,
          rationale text,
          created_at text not null
        );

        create index if not exists journal_amendments_entry_idx on journal_amendments(entry_id);
        """
    )


def _ensure_notebook(connection: sqlite3.Connection, scope: str) -> JsonObject:
    scope_id = _scope_id(scope)
    existing = connection.execute(
        "select * from notebooks where scope = ? and scope_id = ?",
        (scope, scope_id),
    ).fetchone()
    if existing is not None:
        return _row_dict(existing)
    now = _now()
    notebook = {
        "notebook_id": _new_id("notebook"),
        "scope": scope,
        "scope_id": scope_id,
        "title": "Genomi Session Journal" if scope == "session" else "Genomi Project Journal",
        "privacy_scope": "session_private_or_public_target_notes" if scope == "session" else "public_target_scoped",
        "created_at": now,
        "updated_at": now,
    }
    connection.execute(
        """
        insert into notebooks(notebook_id, scope, scope_id, title, privacy_scope, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            notebook["notebook_id"],
            notebook["scope"],
            notebook["scope_id"],
            notebook["title"],
            notebook["privacy_scope"],
            notebook["created_at"],
            notebook["updated_at"],
        ),
    )
    return notebook


def _insert_link(connection: sqlite3.Connection, entry_id: str, link: JsonObject, now: str) -> None:
    connection.execute(
        """
        insert into journal_evidence_links(
          link_id, entry_id, operation, evidence_id, finding_id, coverage_state,
          input_digest, output_digest, source_url, linked_payload_json, created_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _new_id("link"),
            entry_id,
            link["operation"],
            link.get("evidence_id"),
            link.get("finding_id"),
            link.get("coverage_state"),
            link.get("input_digest"),
            link.get("output_digest"),
            link.get("source_url"),
            _json_dumps(link.get("linked_payload") or {}),
            now,
        ),
    )


def _locate_entry(entry_id: str, *, scope: str | None = None) -> tuple[str, Path] | None:
    for selected_scope in _selected_scopes(scope):
        path = journal_db_path(selected_scope)
        if not path.exists():
            continue
        with _connect(path) as connection:
            _init_schema(connection)
            row = connection.execute("select entry_id from journal_entries where entry_id = ?", (entry_id,)).fetchone()
            if row is not None:
                return selected_scope, path
    return None


def _hydrate_entry(connection: sqlite3.Connection, entry_id: str, *, include_private_evidence: bool) -> JsonObject:
    row = connection.execute(
        """
        select journal_entries.*, notebooks.scope, notebooks.scope_id, notebooks.privacy_scope as notebook_privacy_scope
        from journal_entries
        join notebooks on notebooks.notebook_id = journal_entries.notebook_id
        where journal_entries.entry_id = ?
        """,
        (entry_id,),
    ).fetchone()
    if row is None:
        raise JournalError("not_found", f"Journal entry not found: {entry_id}")
    entry = _row_dict(row)
    links = [
        _link_response(_row_dict(link_row), include_private_evidence=include_private_evidence)
        for link_row in connection.execute(
            "select * from journal_evidence_links where entry_id = ? order by created_at asc",
            (entry_id,),
        )
    ]
    amendments = [
        _row_dict(amendment_row)
        for amendment_row in connection.execute(
            "select * from journal_amendments where entry_id = ? order by created_at asc",
            (entry_id,),
        )
    ]
    return {
        "entry_id": entry["entry_id"],
        "notebook_id": entry["notebook_id"],
        "scope": entry["scope"],
        "scope_id": entry["scope_id"],
        "entry_type": entry["entry_type"],
        "title": entry.get("title"),
        "content": entry["content"],
        "decision_status": entry.get("decision_status"),
        "target": _json_loads(entry["target_json"], {}),
        "tags": _json_loads(entry["tags_json"], []),
        "created_by": entry["created_by"],
        "created_at": entry["created_at"],
        "updated_at": entry["updated_at"],
        "superseded_by": entry.get("superseded_by"),
        "evidence_links": links,
        "amendments": amendments,
    }


def _notebook_for_entry(connection: sqlite3.Connection, entry_id: str) -> JsonObject:
    row = connection.execute(
        """
        select notebooks.*
        from notebooks
        join journal_entries on journal_entries.notebook_id = notebooks.notebook_id
        where journal_entries.entry_id = ?
        """,
        (entry_id,),
    ).fetchone()
    if row is None:
        raise JournalError("not_found", f"Journal entry not found: {entry_id}")
    return _row_dict(row)


def _link_response(link: JsonObject, *, include_private_evidence: bool) -> JsonObject:
    payload = _json_loads(link.get("linked_payload_json"), {})
    response = {
        "link_id": link["link_id"],
        "entry_id": link["entry_id"],
        "operation": link["operation"],
        "evidence_id": link.get("evidence_id"),
        "finding_id": link.get("finding_id"),
        "coverage_state": link.get("coverage_state"),
        "input_digest": link.get("input_digest"),
        "output_digest": link.get("output_digest"),
        "source_url": link.get("source_url"),
        "linked_payload": payload,
        "created_at": link["created_at"],
    }
    if _is_private_evidence_link(response) and not include_private_evidence:
        return {
            "link_id": link["link_id"],
            "entry_id": link["entry_id"],
            "operation": link["operation"],
            "private_evidence_omitted": True,
            "created_at": link["created_at"],
        }
    return _drop_none(response)


def _normalize_link(link: JsonObject) -> JsonObject:
    if not isinstance(link, dict):
        raise JournalError("invalid_params", "Evidence links must be objects.")
    operation = _required_text(link.get("operation"), "operation")
    payload: JsonObject = {}
    linked_payload = link.get("linked_payload")
    if isinstance(linked_payload, dict):
        payload.update(linked_payload)
    known = {
        "operation",
        "evidence_id",
        "finding_id",
        "coverage_state",
        "input_digest",
        "output_digest",
        "source_url",
        "linked_payload",
    }
    for key, value in link.items():
        if key not in known:
            payload[key] = value
    return _drop_none(
        {
            "operation": operation,
            "evidence_id": _optional_text(link.get("evidence_id")),
            "finding_id": _optional_text(link.get("finding_id")),
            "coverage_state": _optional_text(link.get("coverage_state")),
            "input_digest": _optional_text(link.get("input_digest")),
            "output_digest": _optional_text(link.get("output_digest")),
            "source_url": _optional_text(link.get("source_url")),
            "linked_payload": payload,
        }
    )


def _assert_links_allowed(scope: str, links: list[JsonObject]) -> None:
    private_links = [link for link in links if _is_private_evidence_link(link)]
    if not private_links:
        return
    if scope == "project":
        raise JournalError("private_evidence_not_allowed", "Project journals cannot store private/sample evidence links in v1.")
    if not runtime_context.agi_access_approved():
        raise JournalError(
            "active_genome_index_approval_required",
            "Explicit Active Genome Index access approval is required before linking private/sample evidence in a session journal.",
        )


def _is_private_evidence_link(link: JsonObject) -> bool:
    operation = str(link.get("operation") or "").lower()
    if operation in PRIVATE_OPERATIONS or any(operation.startswith(prefix) for prefix in PRIVATE_OPERATION_PREFIXES):
        return True
    payload = link.get("linked_payload") if isinstance(link.get("linked_payload"), dict) else {}
    for key in ("privacy_scope", "evidence_scope", "scope", "data_scope", "source_scope"):
        value = str(link.get(key) or payload.get(key) or "").strip().lower()
        if value in PRIVATE_SCOPE_MARKERS:
            return True
    if any(key in payload for key in PRIVATE_PAYLOAD_KEYS):
        return True
    return _contains_private_marker(payload)


def _contains_private_marker(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in PRIVATE_PAYLOAD_KEYS:
                return True
            if _contains_private_marker(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_private_marker(item) for item in value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        return lowered in PRIVATE_SCOPE_MARKERS
    return False


def _entry_matches(
    entry: JsonObject,
    *,
    entry_type: str | None,
    tags: list[str],
    target: JsonObject | None,
    tokens: list[str],
) -> bool:
    if entry_type and entry.get("entry_type") != entry_type:
        return False
    entry_tags = {str(tag).lower() for tag in entry.get("tags") or []}
    if tags and not {tag.lower() for tag in tags}.issubset(entry_tags):
        return False
    if target is not None and not _target_matches(entry.get("target") or {}, target):
        return False
    if tokens:
        haystack = " ".join(
            [
                str(entry.get("title") or ""),
                str(entry.get("content") or ""),
                json.dumps(entry.get("target") or {}, sort_keys=True),
                json.dumps(entry.get("tags") or [], sort_keys=True),
                json.dumps(entry.get("evidence_links") or [], sort_keys=True),
            ]
        ).lower()
        if not all(token in haystack for token in tokens):
            return False
    return True


def _journal_retrieval_document(entry: JsonObject) -> retrieval_hybrid.RetrievalDocument:
    return retrieval_hybrid.RetrievalDocument(
        doc_id=str(entry.get("entry_id") or ""),
        fields={
            "title": str(entry.get("title") or ""),
            "content": str(entry.get("content") or ""),
            "target": json.dumps(entry.get("target") or {}, sort_keys=True),
            "tags": " ".join(str(tag) for tag in entry.get("tags") or []),
            "evidence": json.dumps(entry.get("evidence_links") or [], sort_keys=True),
        },
        payload=entry,
        facets={"entry_type": [str(entry.get("entry_type") or "")], "scope": [str(entry.get("scope") or "")]},
    )


def _target_matches(entry_target: JsonObject, requested: JsonObject) -> bool:
    for key, value in requested.items():
        if key not in entry_target:
            return False
        if str(entry_target.get(key)).lower() != str(value).lower():
            return False
    return True


def _most_used_evidence_sources(entries: list[JsonObject], limit: int) -> list[JsonObject]:
    counter: Counter[str] = Counter()
    labels: dict[str, JsonObject] = {}
    for entry in entries:
        for link in entry.get("evidence_links") or []:
            if link.get("private_evidence_omitted"):
                continue
            if link.get("source_url"):
                key = f"url:{link['source_url']}"
                labels[key] = {"source_type": "source_url", "source": link["source_url"]}
            else:
                key = f"operation:{link.get('operation')}"
                labels[key] = {"source_type": "operation", "source": link.get("operation")}
            counter[key] += 1
    return [{**labels[key], "count": count} for key, count in counter.most_common(limit)]


def _compact_entry(entry: JsonObject) -> JsonObject:
    return {
        "entry_id": entry.get("entry_id"),
        "entry_type": entry.get("entry_type"),
        "title": entry.get("title"),
        "content": entry.get("content"),
        "decision_status": entry.get("decision_status"),
        "target": entry.get("target") or {},
        "tags": entry.get("tags") or [],
        "evidence_link_count": len(entry.get("evidence_links") or []),
        "created_at": entry.get("created_at"),
    }


def _memory_type(entry: JsonObject, links: list[JsonObject]) -> str:
    if entry.get("entry_type") == "decision":
        return "decision_memory"
    if links:
        return "tool_trajectory_memory"
    return "notebook_memory"


def _validate_scope(scope: str | None) -> str:
    selected = str(scope or "session").strip().lower()
    if selected not in {"session", "project"}:
        raise JournalError("invalid_params", "scope must be session or project.")
    return selected


def _validate_entry_type(entry_type: str | None) -> str:
    selected = str(entry_type or "").strip().lower()
    if selected not in ENTRY_TYPES:
        raise JournalError("invalid_params", f"entry_type must be one of: {', '.join(sorted(ENTRY_TYPES))}.")
    return selected


def _validate_amendment_type(amendment_type: str | None) -> str:
    selected = str(amendment_type or "correction").strip().lower()
    if selected not in AMENDMENT_TYPES:
        raise JournalError("invalid_params", f"amendment_type must be one of: {', '.join(sorted(AMENDMENT_TYPES))}.")
    return selected


def _normalize_decision_status(status: str | None) -> str | None:
    if status in (None, ""):
        return None
    selected = str(status).strip().lower()
    if selected not in DECISION_STATUSES:
        raise JournalError("invalid_params", f"decision_status must be one of: {', '.join(sorted(DECISION_STATUSES))}.")
    return selected


def _normalize_tags(tags: object) -> list[str]:
    if tags in (None, ""):
        return []
    if isinstance(tags, str):
        values = [piece.strip() for piece in tags.split(",")]
    elif isinstance(tags, list):
        values = [str(item).strip() for item in tags]
    else:
        raise JournalError("invalid_params", "tags must be an array of strings or a comma-separated string.")
    return sorted({value for value in values if value})


def _normalize_target(target: object) -> JsonObject:
    if target in (None, ""):
        return {}
    if isinstance(target, dict):
        return {str(key): value for key, value in target.items() if value not in (None, "")}
    return {"text": str(target)}


def _scope_id(scope: str) -> str:
    if scope == "session":
        return str(runtime_context.context_scope().get("id") or "session")
    return _workspace_scope_id()


def _workspace_scope_id() -> str:
    return "workspace-" + _digest(Path.cwd().expanduser().resolve(strict=False))


def _public_notebook(notebook: JsonObject) -> JsonObject:
    return {
        "notebook_id": notebook.get("notebook_id"),
        "scope": notebook.get("scope"),
        "scope_id": notebook.get("scope_id"),
        "title": notebook.get("title"),
        "privacy_scope": notebook.get("privacy_scope"),
        "created_at": notebook.get("created_at"),
        "updated_at": notebook.get("updated_at"),
    }


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _tokens(text: str) -> list[str]:
    return [token for token in "".join(character.lower() if character.isalnum() else " " for character in text).split() if token]


def _required_text(value: object, key: str) -> str:
    if value is None or value == "":
        raise JournalError("invalid_params", f"{key} is required.")
    return str(value)


def _optional_text(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _json_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _json_loads(value: object, default: object) -> Any:
    if not isinstance(value, str) or not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _row_dict(row: sqlite3.Row) -> JsonObject:
    return {key: row[key] for key in row.keys()}  # noqa: SIM118 — sqlite3.Row iteration yields values, .keys() yields column names


def _drop_none(value: JsonObject) -> JsonObject:
    return {key: item for key, item in value.items() if item is not None}


def _digest(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
