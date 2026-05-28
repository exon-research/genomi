from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..runtime.external import utc_now
from ..runtime.paths import genomi_data_root
from ..runtime.sqlite_support import LONG_WRITE_BUSY_TIMEOUT_SECONDS, connect_sqlite
from . import hybrid

JsonObject = dict[str, Any]
INDEX_SCHEMA = "genomi-retrieval-index-v1"
PUBLIC_INDEX_DIR = ("indexes", "public")
PRIVATE_INDEX_DIR = ("indexes", "private")


def public_index_path(source: str, root: str | Path | None = None) -> Path:
    return genomi_data_root(root).joinpath(*PUBLIC_INDEX_DIR) / f"{_safe_source_name(source)}.sqlite"


def private_index_path(evidence_dir: str | Path, source: str) -> Path:
    return Path(evidence_dir).expanduser() / "indexes" / f"{_safe_source_name(source)}.sqlite"


def refresh_index(
    path: str | Path,
    *,
    source: str,
    documents: Iterable[hybrid.RetrievalDocument],
    field_weights: Mapping[str, float],
    scope: str,
    provenance: Mapping[str, Any] | None = None,
) -> JsonObject:
    docs = list(documents)
    fields = _field_order(docs, field_weights)
    db_path = Path(path).expanduser()
    with connect_sqlite(
        db_path,
        timeout_seconds=LONG_WRITE_BUSY_TIMEOUT_SECONDS,
        create_parent=True,
        wal=True,
        foreign_keys=False,
    ) as connection:
        _reset_schema(connection, fields)
        generated_at = utc_now()
        metadata = {
            "schema": INDEX_SCHEMA,
            "source": source,
            "scope": scope,
            "field_weights": {str(key): float(value) for key, value in field_weights.items()},
            "fields": fields,
            "document_count": len(docs),
            "generated_at": generated_at,
            "provenance": dict(provenance or {}),
        }
        for key, value in metadata.items():
            connection.execute(
                "insert into retrieval_metadata(key, value_json) values (?, ?)",
                (key, _json_dumps(value)),
            )
        columns = ", ".join(_quote_identifier(field) for field in fields)
        placeholders = ", ".join("?" for _ in fields)
        for rowid, doc in enumerate(docs, start=1):
            connection.execute(
                """
                insert into retrieval_documents(
                  rowid, doc_id, payload_json, fields_json, facets_json, provenance_json
                )
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    rowid,
                    doc.doc_id,
                    _json_dumps(doc.payload),
                    _json_dumps(dict(doc.fields)),
                    _json_dumps(dict(doc.facets or {})),
                    _json_dumps(dict(provenance or {})),
                ),
            )
            if fields:
                connection.execute(
                    f"insert into retrieval_fts(rowid, {columns}) values (?, {placeholders})",
                    [rowid, *[str(doc.fields.get(field) or "") for field in fields]],
                )
    return {
        "schema": INDEX_SCHEMA,
        "status": "completed",
        "index_path": str(db_path),
        "source": source,
        "scope": scope,
        "document_count": len(docs),
        "field_count": len(fields),
        "generated_at": generated_at,
        "provenance": dict(provenance or {}),
    }


def search_index(
    path: str | Path,
    *,
    queries: Iterable[hybrid.RetrievalQuery],
    field_weights: Mapping[str, float] | None = None,
    required_facets: Mapping[str, Sequence[str]] | None = None,
    limit: int = 20,
) -> JsonObject:
    db_path = Path(path).expanduser()
    docs = load_documents(db_path)
    if not docs:
        return {
            "hits": [],
            "diagnostics": {
                "model": "persistent_sqlite_fts5_bm25_rrf_v1",
                "index_path": str(db_path),
                "stream_count": 0,
                "candidate_count": 0,
                "matched_count": 0,
                "fts5": None,
            },
        }
    metadata = read_metadata(db_path)
    weights = field_weights or metadata.get("field_weights") or {}
    filtered = _filter_documents_by_facets(docs, required_facets or {})
    query_list = [query for query in queries if query.text and query.text.strip() and query.weight > 0]
    if not query_list:
        return hybrid.search(
            documents=filtered,
            queries=[],
            field_weights=weights,
            required_facets=None,
            limit=limit,
        )

    try:
        streams = _fts5_streams(db_path, query_list, weights, filtered, limit=max(limit * 4, 50))
        fts5_available = True
    except sqlite3.Error:
        streams = []
        fts5_available = False
    if not streams:
        fallback = hybrid.search(
            documents=filtered,
            queries=query_list,
            field_weights=weights,
            required_facets=None,
            limit=limit,
        )
        diagnostics = dict(fallback["diagnostics"])
        diagnostics["index_path"] = str(db_path)
        diagnostics["persistent_index"] = True
        return {"hits": fallback["hits"], "diagnostics": diagnostics}
    hits = hybrid.fuse_streams(filtered, streams, limit=max(1, int(limit or 20)))
    matched_ids = {
        str(item.get("doc_id") or "")
        for stream in streams
        for item in stream.get("ranked") or []
        if item.get("doc_id")
    }
    return {
        "hits": hits,
        "diagnostics": {
            "model": "persistent_sqlite_fts5_bm25_rrf_v1",
            "index_path": str(db_path),
            "stream_count": len(streams),
            "candidate_count": len(filtered),
            "matched_count": len(matched_ids),
            "fts5": fts5_available,
            "persistent_index": True,
        },
    }


def load_documents(path: str | Path) -> list[hybrid.RetrievalDocument]:
    db_path = Path(path).expanduser()
    if not db_path.exists():
        return []
    with connect_sqlite(db_path) as connection:
        _ensure_read_schema(connection)
        rows = connection.execute(
            "select doc_id, payload_json, fields_json, facets_json from retrieval_documents order by rowid"
        ).fetchall()
    return [
        hybrid.RetrievalDocument(
            doc_id=str(row["doc_id"]),
            fields=_json_loads(row["fields_json"], {}),
            payload=_json_loads(row["payload_json"], {}),
            facets=_json_loads(row["facets_json"], {}),
        )
        for row in rows
    ]


def read_metadata(path: str | Path) -> JsonObject:
    db_path = Path(path).expanduser()
    if not db_path.exists():
        return {}
    with connect_sqlite(db_path) as connection:
        _ensure_read_schema(connection)
        rows = connection.execute("select key, value_json from retrieval_metadata").fetchall()
    return {str(row["key"]): _json_loads(row["value_json"], None) for row in rows}


def list_index_files(root: str | Path | None = None) -> list[JsonObject]:
    base = genomi_data_root(root).joinpath(*PUBLIC_INDEX_DIR)
    records: list[JsonObject] = []
    if base.exists():
        for path in sorted(base.glob("*.sqlite")):
            metadata = read_metadata(path)
            records.append(_index_record(path, metadata, default_scope="public"))
    return records


def describe_index(path: str | Path, *, default_scope: str = "public") -> JsonObject:
    db_path = Path(path).expanduser()
    return _index_record(db_path, read_metadata(db_path), default_scope=default_scope)


def _reset_schema(connection: sqlite3.Connection, fields: list[str]) -> None:
    connection.executescript(
        """
        drop table if exists retrieval_metadata;
        drop table if exists retrieval_documents;
        drop table if exists retrieval_fts;

        create table retrieval_metadata (
          key text primary key,
          value_json text not null
        );

        create table retrieval_documents (
          rowid integer primary key,
          doc_id text not null unique,
          payload_json text not null,
          fields_json text not null,
          facets_json text not null,
          provenance_json text not null
        );
        """
    )
    if fields:
        columns = ", ".join(_quote_identifier(field) for field in fields)
        connection.execute(
            f"create virtual table retrieval_fts using fts5({columns}, tokenize='unicode61 remove_diacritics 2')"
        )
    else:
        connection.execute("create virtual table retrieval_fts using fts5(content, tokenize='unicode61 remove_diacritics 2')")


def _ensure_read_schema(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "select name from sqlite_master where type = 'table' and name = 'retrieval_documents'"
    ).fetchone()
    if row is None:
        raise sqlite3.OperationalError("not a Genomi retrieval index")


def _fts5_streams(
    path: Path,
    queries: list[hybrid.RetrievalQuery],
    field_weights: Mapping[str, float],
    documents: list[hybrid.RetrievalDocument],
    *,
    limit: int,
) -> list[JsonObject]:
    if not documents:
        return []
    metadata = read_metadata(path)
    fields = [str(field) for field in metadata.get("fields") or _field_order(documents, field_weights)]
    allowed_rowids = {doc.doc_id for doc in documents}
    doc_id_by_rowid: dict[int, str] = {}
    with connect_sqlite(path) as connection:
        _ensure_read_schema(connection)
        for row in connection.execute("select rowid, doc_id from retrieval_documents"):
            if row["doc_id"] in allowed_rowids:
                doc_id_by_rowid[int(row["rowid"])] = str(row["doc_id"])
        rank_args = ", ".join(str(float(field_weights.get(field, 1.0))) for field in fields)
        streams: list[JsonObject] = []
        for query in queries:
            fts_query = hybrid.fts_query(query.text)
            if not fts_query:
                continue
            if rank_args:
                rows = connection.execute(
                    f"select rowid, bm25(retrieval_fts, {rank_args}) as rank from retrieval_fts where retrieval_fts match ? order by rank limit ?",
                    (fts_query, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "select rowid, bm25(retrieval_fts) as rank from retrieval_fts where retrieval_fts match ? order by rank limit ?",
                    (fts_query, limit),
                ).fetchall()
            ranked = []
            for row in rows:
                doc_id = doc_id_by_rowid.get(int(row["rowid"]))
                if not doc_id:
                    continue
                ranked.append({"doc_id": doc_id, "rank": len(ranked) + 1, "raw_score": -float(row["rank"])})
            if ranked:
                streams.append({"stream": query.stream, "weight": query.weight, "ranked": ranked})
        return streams


def _filter_documents_by_facets(
    documents: list[hybrid.RetrievalDocument],
    required_facets: Mapping[str, Sequence[str]],
) -> list[hybrid.RetrievalDocument]:
    if not required_facets:
        return documents
    selected: list[hybrid.RetrievalDocument] = []
    for doc in documents:
        doc_facets = doc.facets or {}
        keep = True
        for key, required_values in required_facets.items():
            required = {_normalize_facet(value) for value in required_values if _normalize_facet(value)}
            if not required:
                continue
            observed = {_normalize_facet(value) for value in doc_facets.get(key, ()) if _normalize_facet(value)}
            if not observed & required:
                keep = False
                break
        if keep:
            selected.append(doc)
    return selected


def _field_order(documents: list[hybrid.RetrievalDocument], field_weights: Mapping[str, float]) -> list[str]:
    fields: list[str] = []
    for field in field_weights:
        if field not in fields:
            fields.append(str(field))
    for doc in documents:
        for field in doc.fields:
            if field not in fields:
                fields.append(str(field))
    return fields


def _index_record(path: Path, metadata: JsonObject, *, default_scope: str) -> JsonObject:
    return {
        "schema": INDEX_SCHEMA,
        "index_path": str(path),
        "exists": path.exists(),
        "source": metadata.get("source") or path.stem,
        "scope": metadata.get("scope") or default_scope,
        "document_count": metadata.get("document_count", 0),
        "generated_at": metadata.get("generated_at"),
        "provenance": metadata.get("provenance") or {},
    }


def _safe_source_name(source: str) -> str:
    safe = "".join(character.lower() if character.isalnum() else "_" for character in str(source or "").strip())
    safe = "_".join(part for part in safe.split("_") if part)
    return safe or "index"


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _normalize_facet(value: object) -> str:
    return str(value or "").strip().upper().replace(":", "_")


def _json_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _json_loads(value: object, default: Any) -> Any:
    if not isinstance(value, str) or not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
