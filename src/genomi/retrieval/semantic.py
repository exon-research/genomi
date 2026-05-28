from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

JsonObject = dict[str, Any]

SEMANTIC_CONTEXT_SCHEMA = "genomi-semantic-context-v1"
SEMANTIC_RETRIEVAL_SCHEMA = "genomi-semantic-retrieval"
MAX_EXPANSIONS = 12
MAX_ENTITIES = 12
MAX_TEXT_LENGTH = 160


@dataclass(frozen=True)
class SemanticContext:
    raw_query: str | None
    host_expansions: tuple[str, ...]
    host_entities: tuple[JsonObject, ...]
    ignored_hints: tuple[JsonObject, ...]

    @property
    def has_hints(self) -> bool:
        return bool(self.raw_query or self.host_expansions or self.host_entities or self.ignored_hints)

    def as_json(self) -> JsonObject:
        return {
            "schema": SEMANTIC_CONTEXT_SCHEMA,
            "raw_query": self.raw_query,
            "host_expansions": list(self.host_expansions),
            "host_entities": [dict(item) for item in self.host_entities],
            "ignored_hints": [dict(item) for item in self.ignored_hints],
        }


def parse_semantic_context(value: object) -> SemanticContext:
    if value in (None, ""):
        return SemanticContext(raw_query=None, host_expansions=(), host_entities=(), ignored_hints=())
    if not isinstance(value, dict):
        return SemanticContext(
            raw_query=None,
            host_expansions=(),
            host_entities=(),
            ignored_hints=({"field": "semantic_context", "reason": "semantic_context must be an object"},),
        )

    ignored: list[JsonObject] = []
    raw_query = _clean_text(value.get("raw_query"))
    if value.get("raw_query") not in (None, "") and raw_query is None:
        ignored.append({"field": "raw_query", "reason": "raw_query must be non-empty text"})

    expansions: list[str] = []
    raw_expansions = value.get("host_expansions")
    if raw_expansions in (None, ""):
        raw_expansions = []
    if not isinstance(raw_expansions, list):
        ignored.append({"field": "host_expansions", "reason": "host_expansions must be an array"})
        raw_expansions = []
    for index, item in enumerate(raw_expansions):
        text = _clean_text(item)
        if text is None:
            ignored.append({"field": "host_expansions", "index": index, "reason": "expansion must be non-empty text"})
            continue
        if _dedupe_key(text) in {_dedupe_key(existing) for existing in expansions}:
            continue
        if len(expansions) >= MAX_EXPANSIONS:
            ignored.append({"field": "host_expansions", "index": index, "reason": "expansion limit exceeded"})
            continue
        expansions.append(text)

    entities: list[JsonObject] = []
    raw_entities = value.get("host_entities")
    if raw_entities in (None, ""):
        raw_entities = []
    if not isinstance(raw_entities, list):
        ignored.append({"field": "host_entities", "reason": "host_entities must be an array"})
        raw_entities = []
    entity_keys: set[tuple[str, str]] = set()
    for index, item in enumerate(raw_entities):
        if not isinstance(item, dict):
            ignored.append({"field": "host_entities", "index": index, "reason": "entity must be an object"})
            continue
        text = _clean_text(item.get("text"))
        entity_type = _clean_text(item.get("type"))
        if text is None:
            ignored.append({"field": "host_entities", "index": index, "reason": "entity text must be non-empty"})
            continue
        key = (_dedupe_key(text), _dedupe_key(entity_type or ""))
        if key in entity_keys:
            continue
        if len(entities) >= MAX_ENTITIES:
            ignored.append({"field": "host_entities", "index": index, "reason": "entity limit exceeded"})
            continue
        entity_keys.add(key)
        record: JsonObject = {"text": text}
        if entity_type:
            record["type"] = entity_type
        entities.append(record)

    return SemanticContext(
        raw_query=raw_query,
        host_expansions=tuple(expansions),
        host_entities=tuple(entities),
        ignored_hints=tuple(ignored),
    )


def search_terms(context: SemanticContext, *, entity_types: Iterable[str] | None = None) -> list[str]:
    allowed = {_dedupe_key(item) for item in entity_types or []}
    texts: list[str] = []
    for text in context.host_expansions:
        _append_unique(texts, text)
    for entity in context.host_entities:
        entity_type = _dedupe_key(entity.get("type") or "")
        if allowed and entity_type not in allowed:
            continue
        _append_unique(texts, str(entity.get("text") or ""))
    return texts


def entity_texts(context: SemanticContext, *entity_types: str) -> list[str]:
    allowed = {_dedupe_key(item) for item in entity_types}
    texts: list[str] = []
    for entity in context.host_entities:
        if _dedupe_key(entity.get("type") or "") not in allowed:
            continue
        _append_unique(texts, str(entity.get("text") or ""))
    return texts


def query_texts(
    context: SemanticContext,
    *,
    raw_query: str | None = None,
    entity_types: Iterable[str] | None = None,
    include_raw_query: bool = True,
    max_terms: int = 8,
) -> list[str]:
    texts: list[str] = []
    if include_raw_query:
        _append_unique(texts, raw_query or context.raw_query or "")
    for text in search_terms(context, entity_types=entity_types):
        _append_unique(texts, text)
    return texts[: max(1, int(max_terms or 8))]


def matched_terms(
    context: SemanticContext,
    matched_texts: Iterable[str],
    *,
    match_type: str,
    source: str,
) -> list[JsonObject]:
    matched = {_dedupe_key(text) for text in matched_texts}
    records: list[JsonObject] = []
    for text in search_terms(context):
        if _dedupe_key(text) in matched:
            records.append(
                {
                    "text": text,
                    "status": "hit",
                    "match_type": match_type,
                    "source": source,
                }
            )
    return records


def retrieval_streams(
    *,
    raw_query: str | None = None,
    host_terms: Iterable[str] = (),
    local_vocabulary: Iterable[str] = (),
    exact_ids: Iterable[str] = (),
    source_native_filters: Iterable[str] = (),
    private_metadata: bool = False,
) -> list[JsonObject]:
    streams: list[JsonObject] = []
    if raw_query:
        streams.append({"stream": "raw_query", "text": raw_query})
    for text in host_terms:
        if str(text or "").strip():
            streams.append({"stream": "host_term", "text": str(text).strip(), "strength": "search_term"})
    for text in local_vocabulary:
        if str(text or "").strip():
            streams.append({"stream": "local_vocabulary", "text": str(text).strip(), "strength": "trusted_local_vocabulary"})
    for text in exact_ids:
        if str(text or "").strip():
            streams.append({"stream": "exact_id", "text": str(text).strip(), "strength": "exact_identifier"})
    for text in source_native_filters:
        if str(text or "").strip():
            streams.append({"stream": "source_native_filter", "text": str(text).strip(), "strength": "trusted_source_field"})
    if private_metadata:
        streams.append({"stream": "private_metadata", "strength": "requires_active_genome_index_approval"})
    return streams


def term_usage_payload(
    context: SemanticContext,
    *,
    term_matches: Iterable[object] = (),
    term_misses: Iterable[object] = (),
    streams: Iterable[JsonObject] = (),
) -> JsonObject:
    matches = [_term_record(item, default_status="hit") for item in term_matches]
    misses = [_term_record(item, default_status="miss") for item in term_misses]
    if not misses:
        matched_keys = {_dedupe_key(item.get("text")) for item in matches}
        for text in search_terms(context):
            if _dedupe_key(text) not in matched_keys:
                misses.append({"text": text, "status": "miss"})
    return {
        "schema": SEMANTIC_RETRIEVAL_SCHEMA,
        "raw_query": context.raw_query,
        "host_expansions": list(context.host_expansions),
        "host_entities": [dict(item) for item in context.host_entities],
        "term_matches": matches,
        "term_misses": misses,
        "ignored_hints": [dict(item) for item in context.ignored_hints],
        "retrieval_streams": [dict(item) for item in streams],
        "retrieval_boundary": "Host-provided terms are retrieval inputs. term_matches are source/retrieval hits; term_misses are no-hit terms in the consulted scope, not negative evidence.",
    }


def classify_terms(
    context: SemanticContext,
    verifier: Callable[[str], JsonObject | None],
) -> tuple[list[JsonObject], list[JsonObject]]:
    matched: list[JsonObject] = []
    unmatched: list[JsonObject] = []
    for text in search_terms(context):
        verified = verifier(text)
        if verified:
            matched.append({"text": text, "status": "hit", **verified})
        else:
            unmatched.append({"text": text, "status": "miss"})
    return matched, unmatched


def _term_record(value: object, *, default_status: str) -> JsonObject:
    if isinstance(value, dict):
        text = _clean_text(value.get("text"))
        record = {str(key): item for key, item in value.items() if item is not None}
        if text is not None:
            record["text"] = text
        record.setdefault("status", "hit" if record.get("match_type") else default_status)
        return record
    return {"text": str(value), "status": default_status}


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.strip().split())
    if not text:
        return None
    if len(text) > MAX_TEXT_LENGTH:
        return None
    return text


def _append_unique(values: list[str], text: str) -> None:
    clean = _clean_text(text)
    if clean is None:
        return
    key = _dedupe_key(clean)
    if key not in {_dedupe_key(value) for value in values}:
        values.append(clean)


def _dedupe_key(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())
