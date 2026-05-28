from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

JsonObject = dict[str, Any]

TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
STOPWORDS = {
    "a",
    "about",
    "am",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "can",
    "could",
    "do",
    "does",
    "for",
    "from",
    "go",
    "have",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "should",
    "the",
    "to",
    "what",
    "whether",
    "will",
    "with",
}
RRF_K = 60


@dataclass(frozen=True)
class RetrievalDocument:
    doc_id: str
    fields: Mapping[str, str]
    payload: JsonObject
    facets: Mapping[str, Sequence[str]] | None = None


@dataclass(frozen=True)
class RetrievalQuery:
    text: str
    stream: str
    weight: float = 1.0


@dataclass(frozen=True)
class RetrievalHit:
    doc_id: str
    payload: JsonObject
    score: float
    streams: tuple[JsonObject, ...]


def tokenize(text: object) -> list[str]:
    terms: list[str] = []
    for match in TOKEN_RE.finditer(str(text or "").casefold()):
        token = _stem(match.group(0))
        if len(token) < 2 or token in STOPWORDS:
            continue
        terms.append(token)
    return terms


def search(
    *,
    documents: Iterable[RetrievalDocument],
    queries: Iterable[RetrievalQuery],
    field_weights: Mapping[str, float],
    required_facets: Mapping[str, Sequence[str]] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    docs = _filter_documents_by_facets(list(documents), required_facets or {})
    query_list = [query for query in queries if query.text and query.text.strip() and query.weight > 0]
    if not query_list:
        selected = docs[: max(1, int(limit or 20))]
        return {
            "hits": [
                RetrievalHit(doc_id=doc.doc_id, payload=doc.payload, score=0.0, streams=())
                for doc in selected
            ],
            "diagnostics": {
                "model": "catalog_slice",
                "stream_count": 0,
                "candidate_count": len(docs),
                "matched_count": len(docs),
                "fts5": None,
            },
        }

    fts_result = _fts5_streams(docs, query_list, field_weights, limit=max(limit * 4, 50))
    streams = fts_result["streams"] if fts_result["available"] else _python_bm25_streams(
        docs,
        query_list,
        field_weights,
        limit=max(limit * 4, 50),
    )
    matched_ids = {
        str(item.get("doc_id") or "")
        for stream in streams
        for item in stream.get("ranked") or []
        if item.get("doc_id")
    }
    hits = _fuse_streams(docs, streams, limit=max(1, int(limit or 20)))
    return {
        "hits": hits,
        "diagnostics": {
            "model": "hybrid_bm25_rrf_v1",
            "stream_count": len(streams),
            "candidate_count": len(docs),
            "matched_count": len(matched_ids),
            "fts5": bool(fts_result["available"]),
        },
    }


def fuse_streams(documents: list[RetrievalDocument], streams: list[JsonObject], *, limit: int) -> list[RetrievalHit]:
    return _fuse_streams(documents, streams, limit=limit)


def fts_query(text: str) -> str:
    return _fts_query(text)


def _filter_documents_by_facets(
    documents: list[RetrievalDocument],
    required_facets: Mapping[str, Sequence[str]],
) -> list[RetrievalDocument]:
    if not required_facets:
        return documents
    filtered: list[RetrievalDocument] = []
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
            filtered.append(doc)
    return filtered


def _fts5_streams(
    documents: list[RetrievalDocument],
    queries: list[RetrievalQuery],
    field_weights: Mapping[str, float],
    *,
    limit: int,
) -> dict[str, Any]:
    if not documents:
        return {"available": True, "streams": []}
    fields = _field_order(documents, field_weights)
    if not fields:
        return {"available": False, "streams": []}

    columns = ", ".join(_quote_identifier(field) for field in fields)
    try:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(f"CREATE VIRTUAL TABLE docs USING fts5({columns}, tokenize='unicode61 remove_diacritics 2')")
            placeholders = ", ".join("?" for _ in fields)
            for rowid, doc in enumerate(documents, start=1):
                connection.execute(
                    f"INSERT INTO docs(rowid, {columns}) VALUES (?, {placeholders})",
                    [rowid, *[str(doc.fields.get(field) or "") for field in fields]],
                )
            rank_args = ", ".join(str(float(field_weights.get(field, 1.0))) for field in fields)
            streams: list[JsonObject] = []
            for query in queries:
                fts_query = _fts_query(query.text)
                if not fts_query:
                    continue
                rows = connection.execute(
                    f"SELECT rowid, bm25(docs, {rank_args}) AS rank FROM docs WHERE docs MATCH ? ORDER BY rank LIMIT ?",
                    (fts_query, limit),
                ).fetchall()
                ranked = [
                    {"doc_id": documents[int(row[0]) - 1].doc_id, "rank": index + 1, "raw_score": -float(row[1])}
                    for index, row in enumerate(rows)
                ]
                if ranked:
                    streams.append({"stream": query.stream, "weight": query.weight, "ranked": ranked})
            return {"available": True, "streams": streams}
        finally:
            connection.close()
    except sqlite3.Error:
        return {"available": False, "streams": []}


def _python_bm25_streams(
    documents: list[RetrievalDocument],
    queries: list[RetrievalQuery],
    field_weights: Mapping[str, float],
    *,
    limit: int,
) -> list[JsonObject]:
    indexed: dict[str, dict[str, float]] = {}
    doc_lengths: dict[str, float] = {}
    doc_freq: dict[str, int] = {}
    for doc in documents:
        weighted_terms: dict[str, float] = {}
        for field, value in doc.fields.items():
            weight = float(field_weights.get(field, 1.0))
            if weight <= 0:
                continue
            for term in tokenize(value):
                weighted_terms[term] = weighted_terms.get(term, 0.0) + weight
        indexed[doc.doc_id] = weighted_terms
        doc_lengths[doc.doc_id] = sum(weighted_terms.values())
        for term in weighted_terms:
            doc_freq[term] = doc_freq.get(term, 0) + 1

    total_docs = max(1, len(documents))
    avg_len = sum(doc_lengths.values()) / total_docs if total_docs else 0.0
    streams: list[JsonObject] = []
    for query in queries:
        query_terms = list(dict.fromkeys(tokenize(query.text)))
        if not query_terms:
            continue
        ranked: list[JsonObject] = []
        for doc in documents:
            score = 0.0
            doc_terms = indexed.get(doc.doc_id, {})
            doc_len = doc_lengths.get(doc.doc_id, 0.0)
            for term in query_terms:
                tf = doc_terms.get(term, 0.0)
                if not tf:
                    continue
                df = doc_freq.get(term, 0)
                idf = math.log((total_docs - df + 0.5) / (df + 0.5) + 1.0)
                score += idf * ((tf * 2.2) / (tf + 1.2 * (1 - 0.75 + 0.75 * (doc_len / max(avg_len, 1e-9)))))
            if score > 0:
                ranked.append({"doc_id": doc.doc_id, "raw_score": score})
        ranked.sort(key=lambda item: (-float(item["raw_score"]), str(item["doc_id"])))
        for index, item in enumerate(ranked[:limit]):
            item["rank"] = index + 1
        if ranked:
            streams.append({"stream": query.stream, "weight": query.weight, "ranked": ranked[:limit]})
    return streams


def _fuse_streams(documents: list[RetrievalDocument], streams: list[JsonObject], *, limit: int) -> list[RetrievalHit]:
    by_id = {doc.doc_id: doc for doc in documents}
    scores: dict[str, float] = {}
    stream_details: dict[str, list[JsonObject]] = {}
    for stream in streams:
        stream_name = str(stream.get("stream") or "retrieval")
        weight = float(stream.get("weight") or 1.0)
        for item in stream.get("ranked") or []:
            doc_id = str(item.get("doc_id") or "")
            if doc_id not in by_id:
                continue
            rank = int(item.get("rank") or 10**9)
            contribution = weight * (1.0 / (RRF_K + rank))
            scores[doc_id] = scores.get(doc_id, 0.0) + contribution
            stream_details.setdefault(doc_id, []).append(
                {
                    "stream": stream_name,
                    "rank": rank,
                    "raw_score": item.get("raw_score"),
                    "rrf_contribution": contribution,
                }
            )

    ranked_ids = sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))[:limit]
    return [
        RetrievalHit(
            doc_id=doc_id,
            payload=by_id[doc_id].payload,
            score=scores[doc_id],
            streams=tuple(sorted(stream_details.get(doc_id, []), key=lambda item: str(item.get("stream")))),
        )
        for doc_id in ranked_ids
    ]


def _field_order(documents: list[RetrievalDocument], field_weights: Mapping[str, float]) -> list[str]:
    fields: list[str] = []
    for field in field_weights:
        if field not in fields:
            fields.append(field)
    for doc in documents:
        for field in doc.fields:
            if field not in fields:
                fields.append(field)
    return fields


def _fts_query(text: str) -> str:
    terms = list(dict.fromkeys(tokenize(text)))
    parts: list[str] = []
    for term in terms:
        if len(term) >= 4:
            parts.append(f"{term}*")
        else:
            parts.append(term)
    return " OR ".join(parts)


def _stem(token: str) -> str:
    token = token.casefold()
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("ness") and len(token) > 6:
        return token[:-4]
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def _normalize_facet(value: object) -> str:
    return str(value or "").strip().upper().replace(":", "_")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
