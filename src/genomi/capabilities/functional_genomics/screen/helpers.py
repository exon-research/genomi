from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Iterable
from typing import Any

from ....retrieval import semantic as retrieval_semantic

SCREEN_EXPERIMENT_RECORDS_SCHEMA_VERSION = "genomi-functional-genomics-perturbation-records-v1"
BIOGRID_ORCS_API_BASE = "https://orcsws.thebiogrid.org"
BIOGRID_ORCS_ACCESS_KEY_ENV = "BIOGRID_ORCS_ACCESS_KEY"
DEPMAP_CRISPR_GENE_EFFECT_URL_ENV = "DEPMAP_CRISPR_GENE_EFFECT_URL"
DEPMAP_MODEL_URL_ENV = "DEPMAP_MODEL_URL"
SUPPORTED_NATIVE_SCREEN_SOURCES = {
    "biogrid_orcs": "BioGRID ORCS perturbation screen and score endpoints.",
    "depmap": "DepMap public CRISPR gene effect release tables.",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SCREEN_SOURCE_TOKENS = {
    "crispr",
    "screen",
    "perturb",
    "perturbation",
    "sirna",
    "shrna",
    "rnai",
    "knockout",
    "knockdown",
    "resistance",
    "sensitivity",
    "viability",
}
_LOW_INFORMATION_CONTEXT_TOKENS = {
    "and",
    "after",
    "an",
    "best",
    "cell",
    "cells",
    "from",
    "gene",
    "genes",
    "human",
    "identify",
    "in",
    "is",
    "line",
    "most",
    "promising",
    "screen",
    "the",
    "to",
    "top",
    "was",
    "with",
    "which",
}


def _semantic_screen_fields(semantic: retrieval_semantic.SemanticContext) -> dict[str, str]:
    return {
        "organism": _first_semantic_text(semantic, "organism", "species"),
        "cell_line": _first_semantic_text(semantic, "cell_line", "cell_type", "model"),
        "perturbation": _first_semantic_text(semantic, "perturbation", "screen_method", "assay_method"),
        "assay": _first_semantic_text(semantic, "assay", "readout"),
        "phenotype": _first_semantic_text(semantic, "phenotype", "trait", "condition"),
    }


def _first_semantic_text(semantic: retrieval_semantic.SemanticContext, *entity_types: str) -> str:
    texts = retrieval_semantic.entity_texts(semantic, *entity_types)
    return _clean_text(texts[0]) if texts else ""


def _screen_record_context_values(records: Iterable[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for record in records:
        values.extend(str(item) for item in record.get("genes") or [])
        for key in ("organism", "cell_line", "perturbation", "assay", "phenotype"):
            if record.get(key):
                values.append(str(record.get(key)))
        verified = record.get("verification", {}).get("verified_fields", {})
        if isinstance(verified, dict):
            for key in ("genes", "organism", "cell_line", "perturbation", "assay", "phenotype"):
                raw = verified.get(key)
                if isinstance(raw, list):
                    values.extend(str(item) for item in raw)
                elif raw:
                    values.append(str(raw))
    return _dedupe_text(values)


def _dedupe_text(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _screen_semantic_usage(
    semantic: retrieval_semantic.SemanticContext,
    records: Iterable[dict[str, Any]],
    query: dict[str, Any],
) -> dict[str, Any]:
    return retrieval_semantic.term_usage_payload(
        semantic,
        term_matches=retrieval_semantic.matched_terms(
            semantic,
            _screen_record_context_values(records),
            match_type="matched_functional_genomics_source_record_field",
            source="functional genomics source records",
        ),
        streams=retrieval_semantic.retrieval_streams(
            raw_query=semantic.raw_query,
            host_terms=retrieval_semantic.search_terms(semantic),
            exact_ids=query.get("genes") or [],
            source_native_filters=[
                str(query.get(key))
                for key in ("context", "organism", "cell_line", "perturbation", "assay", "phenotype")
                if query.get(key)
            ],
        ),
    )


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _tokens(value: str) -> list[str]:
    return _TOKEN_RE.findall(value.casefold())


def _meaningful_tokens(value: str) -> list[str]:
    return [
        token
        for token in _tokens(value)
        if len(token) > 1 and token not in _LOW_INFORMATION_CONTEXT_TOKENS
    ]


def _normalize_genes(genes: Iterable[str]) -> list[str]:
    seen = set()
    normalized: list[str] = []
    for gene in genes:
        cleaned = str(gene or "").strip().upper()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _normalize_sources(sources: Iterable[str]) -> list[str]:
    output = []
    seen = set()
    for source in sources:
        value = _clean_text(source).casefold().replace("-", "_")
        if value in {"biogrid", "orcs", "biogrid_orcs"}:
            value = "biogrid_orcs"
        elif value in {"depmap", "achilles"}:
            value = "depmap"
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _normalize_gene(gene: Any) -> str:
    return _clean_text(gene).upper()


def _canonical(value: Any) -> str:
    return "".join(_tokens(_clean_text(value)))


def _organism_id(organism: str | None) -> str:
    text = _clean_text(organism).casefold()
    if not text or "human" in text or text in {"homo sapiens", "9606"}:
        return "9606"
    if "mouse" in text or "mus musculus" in text or text == "10090":
        return "10090"
    return text


def _orcs_library_methodology(value: str) -> str:
    tokens = set(_tokens(value))
    if {"activation", "crispra"} & tokens:
        return "activation"
    if {"inhibition", "crispri"} & tokens:
        return "inhibition"
    if {"knockout", "ko", "crispr", "cas9"} & tokens:
        return "knockout"
    if {"rnai", "shrna", "sirna", "knockdown"} & tokens:
        return "knockdown"
    return ""


def _json_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "records", "screens", "results", "orcs", "items"):
        values = payload.get(key)
        if isinstance(values, list):
            return [item for item in values if isinstance(item, dict)]
    if all(isinstance(value, dict) for value in payload.values()):
        return [value for value in payload.values() if isinstance(value, dict)]
    return []


def _first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key in row and _clean_text(row.get(key)):
            return _clean_text(row.get(key))
    lower = {str(key).casefold(): value for key, value in row.items()}
    for key in keys:
        value = lower.get(key.casefold())
        if _clean_text(value):
            return _clean_text(value)
    return ""


def _first_score(row: dict[str, Any]) -> float | None:
    preferred_keys = [
        "SCORE",
        "score",
        "SCORE.1",
        "score.1",
        "Score.1",
        "EFFECT",
        "effect",
        "LOG2FC",
        "log2fc",
    ]
    for key in preferred_keys:
        score = _as_float(row.get(key))
        if score is not None:
            return score
    for key, value in row.items():
        if "score" in str(key).casefold() or "effect" in str(key).casefold():
            score = _as_float(value)
            if score is not None:
                return score
    return None


def _as_float(value: Any) -> float | None:
    try:
        text = _clean_text(value)
        if not text or text.casefold() in {"na", "nan", "none", "null"}:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _url(base: str, path: str, params: dict[str, Any]) -> str:
    url = base.rstrip("/") + "/" + path.lstrip("/")
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value})
    return url + ("?" + query if query else "")


def _fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "genomi/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_text(url_or_path: str) -> str:
    if "://" not in url_or_path:
        with open(url_or_path, encoding="utf-8") as handle:
            return handle.read()
    request = urllib.request.Request(url_or_path, headers={"Accept": "text/csv,text/plain,*/*", "User-Agent": "genomi/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read().decode("utf-8")
