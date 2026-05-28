from __future__ import annotations

import csv
import io
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

from ...retrieval import hybrid as retrieval_hybrid
from ...retrieval import index as retrieval_index
from ...retrieval import semantic as retrieval_semantic
from . import source_context

JsonObject = dict[str, Any]
USER_AGENT = "Genomi PRS/0.1"
DEFAULT_LIMIT = 20
PRS_FIELD_WEIGHTS = {
    "identity": 5.0,
    "trait": 8.0,
    "ontology": 6.0,
    "name": 3.0,
    "method": 1.2,
    "publication": 0.8,
    "ancestry": 0.6,
    "metadata": 0.5,
}


class SourceUnavailable(RuntimeError):
    def __init__(self, source: str, message: str):
        super().__init__(message)
        self.source = source
        self.message = message


def normalize_pgs_id(value: str | None) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if text.startswith("PGS") and len(text) == 9 and text[3:].isdigit():
        return text
    if text.isdigit():
        return f"PGS{int(text):06d}"
    return text


def score_rest_url(pgs_id: str) -> str:
    return f"{source_context.PGS_CATALOG_REST}/score/{normalize_pgs_id(pgs_id)}"


def get_score_metadata(pgs_id: str) -> JsonObject:
    clean_id = normalize_pgs_id(pgs_id)
    if not clean_id:
        return _invalid_input("pgs_id is required")
    try:
        metadata = _fetch_json(score_rest_url(clean_id))
    except SourceUnavailable as exc:
        return _source_unavailable(exc)
    return {
        "schema": "genomi-prs-score-metadata-v1",
        "status": "completed",
        "pgs_id": clean_id,
        "metadata": _score_summary(metadata),
        "raw_metadata": metadata,
        "source_urls": {
            **source_context.source_urls(),
            "score_rest": score_rest_url(clean_id),
            "score_page": f"https://www.pgscatalog.org/score/{clean_id}/",
        },
        "limitations": source_context.limitations(),
    }


def search_scores(
    *,
    query: str | None = None,
    trait: str | None = None,
    pgs_id: str | None = None,
    efo_id: str | None = None,
    limit: int = DEFAULT_LIMIT,
    semantic_context: object = None,
) -> JsonObject:
    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    if pgs_id:
        exact = get_score_metadata(pgs_id)
        payload = {
            "schema": "genomi-prs-score-search-v1",
            "status": exact.get("status", "source_unavailable"),
            "query": _query_payload(query=query, trait=trait, pgs_id=pgs_id, efo_id=efo_id, limit=limit),
            "results": [exact["metadata"]] if exact.get("status") == "completed" else [],
            "source_urls": source_context.source_urls(),
            "source_status": exact.get("source_status"),
            "limitations": source_context.limitations(),
        }
        if semantic.has_hints:
            payload["semantic_context"] = retrieval_semantic.term_usage_payload(
                semantic,
                term_misses=[
                    {"text": text, "status": "ignored_for_exact_identifier", "reason": "pgs_id is exact"}
                    for text in retrieval_semantic.search_terms(semantic)
                ],
                streams=retrieval_semantic.retrieval_streams(
                    raw_query=semantic.raw_query or query,
                    host_terms=retrieval_semantic.search_terms(semantic),
                    exact_ids=[pgs_id],
                ),
            )
        return payload

    try:
        rows = _fetch_score_metadata_rows()
    except SourceUnavailable as exc:
        cached = _search_cached_score_index(
            query=query,
            trait=trait,
            efo_id=efo_id,
            limit=limit,
            semantic=semantic,
            source_status={"source": exc.source, "error": exc.message},
        )
        if cached is not None:
            return cached
        return _source_unavailable(exc, schema="genomi-prs-score-search-v1")

    refresh_result = refresh_score_search_index(rows)
    search_result = _search_score_rows(
        rows,
        query=query,
        trait=trait,
        efo_id=efo_id,
        limit=limit,
        semantic=semantic,
        index_path=Path(refresh_result["index_path"]),
    )
    selected = search_result["results"]
    return {
        "schema": "genomi-prs-score-search-v1",
        "status": "completed",
        "query": _query_payload(query=query, trait=trait, pgs_id=pgs_id, efo_id=efo_id, limit=limit),
        "source": {
            "name": "PGS Catalog bulk score metadata",
            "url": source_context.PGS_CATALOG_METADATA_CSV,
            "row_count_consulted": len(rows),
        },
        "retrieval": search_result["retrieval"],
        "semantic_context": search_result["semantic_context"],
        "results": selected,
        "summary": {
            "matched_count": search_result["matched_count"],
            "returned_count": len(selected),
        },
        "source_urls": source_context.source_urls(),
        "limitations": source_context.limitations(),
        "next_actions": _search_next_actions(selected),
    }


def refresh_score_search_index(rows: list[JsonObject] | None = None) -> JsonObject:
    score_rows = rows if rows is not None else _fetch_score_metadata_rows()
    return retrieval_index.refresh_index(
        retrieval_index.public_index_path("pgs_scores"),
        source="pgs_scores",
        documents=[_retrieval_document_from_row(row) for row in score_rows],
        field_weights=PRS_FIELD_WEIGHTS,
        scope="public",
        provenance={
            "source_id": "pgs_catalog_bulk_score_metadata",
            "source_name": "PGS Catalog bulk score metadata",
            "source_url": source_context.PGS_CATALOG_METADATA_CSV,
        },
    )


def scoring_file_url_from_metadata(metadata: JsonObject, genome_build: str) -> str | None:
    harmonized = metadata.get("ftp_harmonized_scoring_files")
    if isinstance(harmonized, dict):
        build_payload = harmonized.get(_normalize_build(genome_build)) or harmonized.get(genome_build)
        if isinstance(build_payload, dict):
            positions = build_payload.get("positions")
            if positions:
                return str(positions)
    direct = metadata.get("ftp_scoring_file")
    return str(direct) if direct else None


def fetch_rest_metadata(pgs_id: str) -> JsonObject:
    return _fetch_json(score_rest_url(pgs_id))


def source_unavailable_result(exc: SourceUnavailable, *, schema: str) -> JsonObject:
    return _source_unavailable(exc, schema=schema)


def _query_payload(**kwargs: object) -> JsonObject:
    return {key: value for key, value in kwargs.items() if value not in (None, "", [])}


def _search_score_rows(
    rows: list[JsonObject],
    *,
    query: str | None,
    trait: str | None,
    efo_id: str | None,
    limit: int,
    semantic: retrieval_semantic.SemanticContext | None = None,
    index_path: Path | None = None,
) -> JsonObject:
    documents = [_retrieval_document_from_row(row) for row in rows]
    semantic = semantic or retrieval_semantic.parse_semantic_context(None)
    retrieval_queries, query_model = _prs_retrieval_queries(query=query, trait=trait, semantic=semantic)
    required_facets: dict[str, Sequence[str]] = {}
    normalized_efo = _normalize_trait_id(str(efo_id or ""))
    if normalized_efo:
        required_facets["efo_id"] = [normalized_efo]
    if index_path is not None and index_path.exists():
        search_result = retrieval_index.search_index(
            index_path,
            queries=retrieval_queries,
            field_weights=PRS_FIELD_WEIGHTS,
            required_facets=required_facets,
            limit=max(1, int(limit or DEFAULT_LIMIT)),
        )
    else:
        search_result = retrieval_hybrid.search(
            documents=documents,
            queries=retrieval_queries,
            field_weights=PRS_FIELD_WEIGHTS,
            required_facets=required_facets,
            limit=max(1, int(limit or DEFAULT_LIMIT)),
        )
    selected: list[JsonObject] = []
    for hit in search_result["hits"]:
        summary = _score_summary_from_csv(hit.payload)
        summary["retrieval"] = {
            "score": hit.score,
            "streams": list(hit.streams),
        }
        selected.append(summary)
    term_usage = _prs_term_usage(
        semantic,
        query_model=query_model,
        hits=list(search_result["hits"]),
        query=query,
        trait=trait,
        efo_id=efo_id,
        pgs_id=None,
    )
    diagnostics = dict(search_result["diagnostics"])
    diagnostics["semantic_query_model"] = query_model
    diagnostics["query_expansion"] = {"strategy": "none_hardcoded_host_terms_only", "applied": []}
    diagnostics["required_facets"] = required_facets
    diagnostics["retrieval_streams"] = term_usage["retrieval_streams"]
    return {
        "results": selected,
        "matched_count": diagnostics.get("matched_count", len(search_result["hits"])),
        "retrieval": diagnostics,
        "semantic_context": term_usage,
    }


def _retrieval_document_from_row(row: JsonObject) -> retrieval_hybrid.RetrievalDocument:
    pgs_id = str(row.get("Polygenic Score (PGS) ID") or "")
    mapped_trait_ids = _extract_trait_ids(row.get("Mapped Trait(s) (EFO ID)"))
    fields = {
        "identity": " ".join([pgs_id, str(row.get("PGS Publication (PGP) ID") or "")]),
        "name": str(row.get("PGS Name") or ""),
        "trait": " ".join(
            [
                str(row.get("Reported Trait") or ""),
                str(row.get("Mapped Trait(s) (EFO label)") or ""),
            ]
        ),
        "ontology": " ".join(mapped_trait_ids),
        "method": " ".join(
            [
                str(row.get("PGS Development Method") or ""),
                str(row.get("PGS Development Details/Relevant Parameters") or ""),
            ]
        ),
        "publication": " ".join(
            [
                str(row.get("Publication (PMID)") or ""),
                str(row.get("Publication (doi)") or ""),
            ]
        ),
        "ancestry": " ".join(
            [
                str(row.get("Ancestry Distribution (%) - Source of Variant Associations (GWAS)") or ""),
                str(row.get("Ancestry Distribution (%) - Score Development/Training") or ""),
                str(row.get("Ancestry Distribution (%) - PGS Evaluation") or ""),
            ]
        ),
        "metadata": " ".join(
            [
                str(row.get("Original Genome Build") or ""),
                str(row.get("Type of Variant Weight") or ""),
                str(row.get("Number of Variants") or ""),
            ]
        ),
    }
    return retrieval_hybrid.RetrievalDocument(
        doc_id=pgs_id,
        fields=fields,
        payload=row,
        facets={"efo_id": mapped_trait_ids},
    )


def _prs_retrieval_queries(
    *,
    query: str | None,
    trait: str | None,
    semantic: retrieval_semantic.SemanticContext | None = None,
) -> tuple[list[retrieval_hybrid.RetrievalQuery], JsonObject]:
    queries: list[retrieval_hybrid.RetrievalQuery] = []
    if query and query.strip():
        queries.append(retrieval_hybrid.RetrievalQuery(text=query.strip(), stream="query", weight=1.0))
    if trait and trait.strip():
        queries.append(retrieval_hybrid.RetrievalQuery(text=trait.strip(), stream="trait", weight=1.3))
    if semantic is not None:
        if semantic.raw_query and semantic.raw_query != query and semantic.raw_query != trait:
            queries.append(retrieval_hybrid.RetrievalQuery(text=semantic.raw_query, stream="semantic:raw_query", weight=1.0))
    host_terms: list[JsonObject] = []
    if semantic is not None:
        for index, text in enumerate(
            retrieval_semantic.search_terms(semantic, entity_types=("trait_or_condition", "phenotype", "trait")),
            start=1,
        ):
            stream = f"semantic:host_term:{index}"
            queries.append(retrieval_hybrid.RetrievalQuery(text=text, stream=stream, weight=0.7))
            host_terms.append({"text": text, "stream": stream})
    return queries, {
        "strategy": "host_semantic_terms",
        "host_terms": host_terms,
        "raw_query_streams": [query.stream for query in queries if query.stream in {"query", "trait", "semantic:raw_query"}],
        "hardcoded_synonyms": False,
    }


def _search_cached_score_index(
    *,
    query: str | None,
    trait: str | None,
    efo_id: str | None,
    limit: int,
    semantic: retrieval_semantic.SemanticContext,
    source_status: JsonObject,
) -> JsonObject | None:
    index_path = retrieval_index.public_index_path("pgs_scores")
    if not index_path.exists():
        return None
    docs = retrieval_index.load_documents(index_path)
    if not docs:
        return None
    rows = [doc.payload for doc in docs]
    search_result = _search_score_rows(
        rows,
        query=query,
        trait=trait,
        efo_id=efo_id,
        limit=limit,
        semantic=semantic,
        index_path=index_path,
    )
    return {
        "schema": "genomi-prs-score-search-v1",
        "status": "completed_from_cached_index",
        "query": _query_payload(query=query, trait=trait, efo_id=efo_id, limit=limit),
        "source": {
            "name": "PGS Catalog bulk score metadata cached retrieval index",
            "url": source_context.PGS_CATALOG_METADATA_CSV,
            "row_count_consulted": len(rows),
            "source_status": source_status,
        },
        "retrieval": search_result["retrieval"],
        "semantic_context": search_result["semantic_context"],
        "results": search_result["results"],
        "summary": {
            "matched_count": search_result["matched_count"],
            "returned_count": len(search_result["results"]),
        },
        "source_urls": source_context.source_urls(),
        "limitations": [
            *source_context.limitations(),
            "Search used a cached local retrieval index because the current PGS Catalog metadata source was unavailable.",
        ],
        "next_actions": _search_next_actions(search_result["results"]),
    }


def _prs_term_usage(
    semantic: retrieval_semantic.SemanticContext,
    *,
    query_model: JsonObject,
    hits: list[retrieval_hybrid.RetrievalHit],
    query: str | None,
    trait: str | None,
    efo_id: str | None,
    pgs_id: str | None,
) -> JsonObject:
    term_matches: list[JsonObject] = []
    term_misses: list[JsonObject] = []
    term_streams = {
        str(item.get("text") or ""): str(item.get("stream") or "")
        for item in query_model.get("host_terms") or []
        if isinstance(item, dict)
    }
    for text in retrieval_semantic.search_terms(semantic):
        stream = term_streams.get(text)
        matched_hits = [
            hit
            for hit in hits
            if stream and any(str(detail.get("stream") or "") == stream for detail in hit.streams)
        ]
        if matched_hits:
            term_matches.append(
                {
                    "text": text,
                    "status": "hit",
                    "match_type": "matched_source_index_fields",
                    "source": "PGS Catalog retrieval index",
                    "matched_record_ids": [hit.doc_id for hit in matched_hits[:5]],
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
            host_terms=retrieval_semantic.search_terms(semantic),
            exact_ids=[value for value in (pgs_id, efo_id) if value],
            source_native_filters=[efo_id] if efo_id else [],
        ),
    )


def _normalize_trait_id(value: str) -> str:
    return value.strip().upper().replace(":", "_")


def _extract_trait_ids(value: object) -> list[str]:
    text = str(value or "")
    ids = [_normalize_trait_id(match.group(0)) for match in re.finditer(r"EFO[:_][0-9]+", text, flags=re.I)]
    if ids:
        return list(dict.fromkeys(ids))
    return [_normalize_trait_id(part) for part in re.split(r"[;,|\s]+", text) if _normalize_trait_id(part)]


def _score_summary(metadata: JsonObject) -> JsonObject:
    publication = metadata.get("publication") if isinstance(metadata.get("publication"), dict) else {}
    return {
        "pgs_id": metadata.get("id"),
        "name": metadata.get("name"),
        "reported_trait": metadata.get("trait_reported") or metadata.get("reported_trait"),
        "mapped_traits": metadata.get("trait_efo") or metadata.get("mapped_traits"),
        "original_genome_build": metadata.get("genome_build"),
        "variant_count": metadata.get("variants_number"),
        "weight_type": metadata.get("weight_type"),
        "publication": {
            "pgp_id": publication.get("id"),
            "title": publication.get("title"),
            "doi": publication.get("doi"),
            "pmid": publication.get("PMID") or publication.get("pmid"),
            "journal": publication.get("journal"),
            "first_author": publication.get("firstauthor"),
            "date_publication": publication.get("date_publication"),
        },
        "matches_publication": metadata.get("matches_publication"),
        "ftp_scoring_file": metadata.get("ftp_scoring_file"),
        "ftp_harmonized_scoring_files": metadata.get("ftp_harmonized_scoring_files"),
        "ancestry_distribution": {
            "development": metadata.get("samples_variants"),
            "training": metadata.get("samples_training"),
            "evaluation": metadata.get("samples_evaluation"),
        },
    }


def _score_summary_from_csv(row: JsonObject) -> JsonObject:
    return {
        "pgs_id": row.get("Polygenic Score (PGS) ID"),
        "name": row.get("PGS Name"),
        "reported_trait": row.get("Reported Trait"),
        "mapped_trait_labels": row.get("Mapped Trait(s) (EFO label)"),
        "mapped_trait_ids": row.get("Mapped Trait(s) (EFO ID)"),
        "development_method": row.get("PGS Development Method"),
        "development_details": row.get("PGS Development Details/Relevant Parameters"),
        "original_genome_build": row.get("Original Genome Build"),
        "variant_count": _maybe_int(row.get("Number of Variants")),
        "interaction_terms": _maybe_int(row.get("Number of Interaction Terms")),
        "weight_type": row.get("Type of Variant Weight"),
        "publication": {
            "pgp_id": row.get("PGS Publication (PGP) ID"),
            "pmid": row.get("Publication (PMID)"),
            "doi": row.get("Publication (doi)"),
        },
        "matches_publication": row.get("Score and results match the original publication"),
        "ancestry_distribution": {
            "source_gwas": row.get("Ancestry Distribution (%) - Source of Variant Associations (GWAS)"),
            "development_training": row.get("Ancestry Distribution (%) - Score Development/Training"),
            "evaluation": row.get("Ancestry Distribution (%) - PGS Evaluation"),
        },
        "ftp_scoring_file": row.get("FTP link"),
        "release_date": row.get("Release Date"),
        "license_terms": row.get("License/Terms of Use"),
    }


def _search_next_actions(results: list[JsonObject]) -> list[JsonObject]:
    if not results:
        return [{"action": "try_broader_trait_or_pgs_id"}]
    first = results[0].get("pgs_id")
    return [
        {"action": "inspect_score_metadata", "operation": "prs.fetch_score_metadata", "pgs_id": first},
        {"action": "import_scoring_file", "operation": "prs.import_scoring_file", "pgs_id": first, "genome_build": "GRCh38"},
    ]


def _fetch_score_metadata_rows() -> list[JsonObject]:
    text = _fetch_text(source_context.PGS_CATALOG_METADATA_CSV)
    with io.StringIO(text) as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _fetch_json(url: str) -> JsonObject:
    text = _fetch_text(url)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise SourceUnavailable(url, "PGS Catalog returned non-object JSON")
    return payload


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceUnavailable(url, str(exc)) from exc


def _source_unavailable(exc: SourceUnavailable, *, schema: str = "genomi-prs-score-metadata-v1") -> JsonObject:
    return {
        "schema": schema,
        "status": "source_unavailable",
        "source_status": {"source": exc.source, "error": exc.message},
        "source_urls": source_context.source_urls(),
        "results": [],
        "limitations": source_context.limitations(),
        "next_actions": [{"action": "retry_later_or_supply_local_scoring_file"}],
    }


def _invalid_input(message: str) -> JsonObject:
    return {
        "schema": "genomi-prs-score-metadata-v1",
        "status": "invalid_params",
        "message": message,
        "source_urls": source_context.source_urls(),
    }


def _normalize_build(genome_build: str) -> str:
    lowered = str(genome_build or "").strip().lower()
    if lowered in {"grch38", "hg38", "38"}:
        return "GRCh38"
    if lowered in {"grch37", "hg19", "37"}:
        return "GRCh37"
    return str(genome_build or "").strip()


def _maybe_int(value: object) -> int | None:
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
