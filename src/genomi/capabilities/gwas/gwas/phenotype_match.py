from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ....evidence.candidate_evidence import (
    EXACT_TRAIT_MATCH,
    NEARBY_TRAIT_MATCH,
)
from ....retrieval import semantic as retrieval_semantic
from .text_utils import _clean_text, _meaningful_tokens


def _association_traits(association: dict[str, Any]) -> list[str]:
    embedded = association.get("_embedded") if isinstance(association.get("_embedded"), dict) else {}
    traits: list[str] = []
    for trait in embedded.get("efoTraits") or []:
        if isinstance(trait, dict):
            text = _clean_text(trait.get("trait"))
            if text:
                traits.append(text)
    return traits


def _phenotype_match(phenotype: str, trait_texts: Iterable[str]) -> dict[str, Any]:
    query_tokens = set(_meaningful_tokens(phenotype))
    best_score = 0
    best_trait = None
    best_tokens: list[str] = []
    best_lane = None
    best_reason = "no meaningful phenotype-token overlap"
    for trait in trait_texts:
        trait_tokens = set(_meaningful_tokens(trait))
        overlap = sorted(query_tokens & trait_tokens)
        exact_phrase = bool(phenotype and (phenotype in trait or trait in phenotype))
        exact_token_match = bool(len(query_tokens) > 1 and query_tokens.issubset(trait_tokens))
        if exact_phrase or exact_token_match:
            score = 100 + len(overlap)
            evidence_lane = EXACT_TRAIT_MATCH
            reason = "query phenotype exactly matched GWAS trait text"
        elif overlap:
            score = 20 + len(overlap)
            evidence_lane = NEARBY_TRAIT_MATCH
            reason = "query phenotype shares meaningful tokens with GWAS trait text"
        else:
            score = 0
            evidence_lane = None
            reason = "no meaningful phenotype-token overlap"
        if score > best_score:
            best_score = score
            best_trait = trait
            best_tokens = overlap
            best_lane = evidence_lane
            best_reason = reason
    return {
        "score": best_score,
        "evidence_lane": best_lane,
        "matched_trait": best_trait,
        "matched_tokens": best_tokens,
        "reason": best_reason,
    }


def _best_phenotype_match(phenotype_queries: Iterable[str], trait_texts: Iterable[str]) -> dict[str, Any]:
    traits = list(trait_texts)
    best: dict[str, Any] | None = None
    for query in phenotype_queries:
        match = _phenotype_match(_clean_text(query), traits)
        match["query_text"] = _clean_text(query)
        if best is None or int(match.get("score") or 0) > int(best.get("score") or 0):
            best = match
    return best or _phenotype_match("", traits)


def _semantic_trait_queries(semantic: retrieval_semantic.SemanticContext, phenotype: str) -> list[str]:
    queries = retrieval_semantic.query_texts(
        semantic,
        raw_query=phenotype,
        entity_types=("trait", "phenotype", "condition", "trait_or_condition", "disease"),
        max_terms=8,
    )
    if not queries:
        queries = [phenotype]
    return [_clean_text(query) for query in queries if _clean_text(query)]


def _gwas_semantic_usage(
    semantic: retrieval_semantic.SemanticContext,
    *,
    matched_records: Iterable[dict[str, Any]],
    exact_ids: Iterable[str],
    source_filters: Iterable[str],
) -> dict[str, Any]:
    matched_queries = [
        str((record.get("phenotype_match") or {}).get("query_text") or "")
        for record in matched_records
        if int((record.get("phenotype_match") or {}).get("score") or 0) > 0
    ]
    return retrieval_semantic.term_usage_payload(
        semantic,
        term_matches=retrieval_semantic.matched_terms(
            semantic,
            matched_queries,
            match_type="matched_gwas_catalog_trait_or_source_record",
            source="GWAS Catalog",
        ),
        streams=retrieval_semantic.retrieval_streams(
            raw_query=semantic.raw_query,
            host_terms=retrieval_semantic.search_terms(semantic),
            exact_ids=exact_ids,
            source_native_filters=source_filters,
        ),
    )
