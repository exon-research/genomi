from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from collections.abc import Iterable
from typing import Any

from ....retrieval import semantic as retrieval_semantic

DRUG_TARGET_PRIORITIZATION_SCHEMA_VERSION = "genomi-drug-target-prioritization-v1"
DISEASE_DRUG_TARGET_RETRIEVAL_SCHEMA_VERSION = "genomi-disease-clinical-drug-targets-v1"
OPENTARGETS_GRAPHQL_API_URL = "https://api.platform.opentargets.org/api/v4/graphql"
OPENTARGETS_DISEASE_SEARCH_LIMIT = 3
TOKEN_RE = re.compile(r"[a-z0-9]+")
LOW_INFORMATION_TOKENS = {
    "a",
    "an",
    "and",
    "are",
    "associated",
    "by",
    "disease",
    "drug",
    "gene",
    "genes",
    "in",
    "is",
    "of",
    "or",
    "target",
    "targets",
    "the",
    "to",
    "with",
}
DRUG_TARGET_SOURCE_IDS = {"chembl", "drugbank", "pharmaprojects"}
DRUG_TARGET_SOURCE_TOKENS = {
    "chembl",
    "drugbank",
    "pharmaprojects",
    "target",
    "targets",
    "moa",
    "mechanism",
    "bioactivity",
    "binding",
    "inhibitor",
    "agonist",
    "antagonist",
    "program",
    "drug",
}
ASSOCIATION_ONLY_SOURCE_TOKENS = {"opentargets", "gwas-catalog", "association", "associations", "tractability"}
CLINICAL_STAGE_RANK = {
    "APPROVED": 100,
    "PHASE_4": 90,
    "PHASE_3": 80,
    "PHASE_2": 70,
    "PHASE_1": 60,
    "EARLY_PHASE_1": 50,
    "PRECLINICAL": 20,
}


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _canonical_phrase(value: Any) -> str:
    return " ".join(_meaningful_tokens(value))


def _tokens(value: Any) -> list[str]:
    return TOKEN_RE.findall(str(value or "").casefold())


def _meaningful_tokens(value: Any) -> list[str]:
    return [token for token in _tokens(value) if len(token) > 1 and token not in LOW_INFORMATION_TOKENS]


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _dedupe(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
    return output


def _record_digest(record: dict[str, Any]) -> str:
    payload = json.dumps(record, sort_keys=True, default=str)
    return "record-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _normalize_gene(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_genes(values: Iterable[Any]) -> list[str]:
    return _dedupe([_normalize_gene(value) for value in values if _normalize_gene(value)])


def _normalize_terms(values: Iterable[Any]) -> list[str]:
    return _dedupe([_canonical_phrase(value) for value in values if _canonical_phrase(value)])


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen = set()
    for record in records:
        key = (record.get("source_url"), record.get("source_title"), record.get("finding"), tuple(record.get("genes") or []), tuple(record.get("drugs") or []))
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output


def _dedupe_dicts(values: Iterable[dict[str, Any]], *, key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for value in values:
        key = tuple(json.dumps(value.get(field), sort_keys=True, default=str) for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _clinical_stage_rank(stage: Any) -> int:
    text = _clean_text(stage).upper().replace(" ", "_")
    if text in CLINICAL_STAGE_RANK:
        return CLINICAL_STAGE_RANK[text]
    match = re.search(r"PHASE[_ ]?(\d)", text)
    if match:
        return CLINICAL_STAGE_RANK.get(f"PHASE_{match.group(1)}", 0)
    return 0


def _fetch_opentargets_graphql(api_url: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        api_url,
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "genomi/0.1"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("errors"):
        raise ValueError(str(payload["errors"]))
    return payload


def _field_matches(query_value: str, verified_value: str) -> bool:
    query = set(_meaningful_tokens(query_value))
    value = set(_meaningful_tokens(verified_value))
    if not query or not value:
        return False
    return query <= value or value <= query or _canonical_phrase(query_value) == _canonical_phrase(verified_value)


def _value_supported_by_text(value: str, source_text: str) -> bool:
    value_tokens = set(_meaningful_tokens(value))
    source_tokens = set(_meaningful_tokens(source_text))
    if not value_tokens:
        return False
    return value_tokens <= source_tokens or _canonical_phrase(value) in _canonical_phrase(source_text)


def _any_field_matches(query_value: str, values: Iterable[str]) -> bool:
    return any(_field_matches(query_value, value) for value in values)


def _context_token_overlap(query: dict[str, Any], text: str) -> list[str]:
    query_tokens: set[str] = set()
    for value in (query.get("drug"), query.get("drug_class"), query.get("indication"), query.get("mechanism")):
        query_tokens.update(_meaningful_tokens(value))
    return sorted(query_tokens & set(_meaningful_tokens(text)))


def _first_semantic_text(semantic: retrieval_semantic.SemanticContext, *entity_types: str) -> str:
    texts = retrieval_semantic.entity_texts(semantic, *entity_types)
    return _clean_text(texts[0]) if texts else ""
