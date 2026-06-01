from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ....evidence import search_research_findings
from ....runtime.libraries import registry as _library_registry
from ....retrieval import semantic as retrieval_semantic

PHENOTYPE_NORMALIZATION_SCHEMA_VERSION = "genomi-phenotype-normalization-v1"
PHENOTYPE_PRIORITIZATION_SCHEMA_VERSION = "genomi-phenotype-prioritization-v1"
# Source URLs live only in the central registry; these names expose them as the
# documented defaults for the phenotype operations and for record provenance.
HPO_GENE_ANNOTATION_URL = _library_registry.get("hpo").source.urls[0]
HPO_DISEASE_ANNOTATION_URL = _library_registry.get("hpo").source.urls[1]
GENCC_SUBMISSIONS_URL = _library_registry.get("gencc").source.urls[0]
PRIMARY_GENE_DISEASE_CLASSIFICATIONS = ("Definitive", "Strong")
HPO_ID_RE = re.compile(r"\bHP:\d{7}\b", flags=re.I)
TOKEN_RE = re.compile(r"[a-z0-9]+")
LOW_INFORMATION_TOKENS = {
    "a",
    "an",
    "and",
    "are",
    "by",
    "disease",
    "gene",
    "genes",
    "has",
    "have",
    "in",
    "is",
    "of",
    "or",
    "patient",
    "patients",
    "phenotype",
    "syndrome",
    "the",
    "to",
    "with",
}
RARE_DISEASE_SOURCE_TOKENS = {
    "hpo",
    "mondo",
    "orphanet",
    "omim",
    "orpha",
    "genereviews",
    "gencc",
    "clingen",
    "malacards",
    "genecards",
    "rare",
    "mendelian",
    "ontology",
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


def _normalize_diseases(values: Iterable[Any]) -> list[str]:
    return _dedupe([_clean_text(value) for value in values if _clean_text(value)])


def _normalize_disease_ids(values: Iterable[Any]) -> list[str]:
    return _dedupe([identifier for value in values if (identifier := _disease_id(value))])


def _extract_disease_ids(values: Iterable[Any]) -> list[str]:
    return _normalize_disease_ids(values)


def _disease_id(value: Any) -> str:
    text = _clean_text(value)
    match = re.search(r"\b(OMIM|ORPHA|ORPHANET|DECIPHER|MONDO|HP):\d+\b", text, flags=re.I)
    if not match:
        return ""
    prefix, number = match.group(1).upper(), match.group(0).split(":", 1)[1]
    if prefix == "ORPHANET":
        prefix = "ORPHA"
    return f"{prefix}:{number}"


def _strip_disease_ids(value: Any) -> str:
    return re.sub(r"\b(?:OMIM|ORPHA|ORPHANET|DECIPHER|MONDO|HP):\d+\b", "", _clean_text(value), flags=re.I).strip(" ,;()")


def _normalize_terms(values: Iterable[Any]) -> list[str]:
    return _dedupe([_canonical_phrase(value) for value in values if _canonical_phrase(value)])


def _normalize_hpo_ids(values: Iterable[Any]) -> list[str]:
    output = []
    for value in values:
        for match in HPO_ID_RE.findall(str(value or "")):
            output.append(match.upper())
    return _dedupe(output)


def _first_hpo_id(value: Any) -> str | None:
    match = HPO_ID_RE.search(str(value or ""))
    return match.group(0).upper() if match else None


def _field_matches(query_value: str, verified_value: str) -> bool:
    query = set(_meaningful_tokens(query_value))
    value = set(_meaningful_tokens(verified_value))
    if not query or not value:
        return False
    return query <= value or value <= query or _canonical_phrase(query_value) == _canonical_phrase(verified_value)


def _value_supported_by_text(value: str, source_text: str) -> bool:
    if not value or not source_text:
        return False
    if HPO_ID_RE.fullmatch(value.strip()):
        return value.upper() in source_text.upper()
    value_tokens = set(_meaningful_tokens(value))
    source_tokens = set(_meaningful_tokens(source_text))
    if not value_tokens:
        return False
    return value_tokens <= source_tokens or _canonical_phrase(value) in _canonical_phrase(source_text)


def _any_field_matches(query_value: str, values: Iterable[str]) -> bool:
    return any(_field_matches(query_value, value) for value in values)


def _context_token_overlap(query: dict[str, Any], text: str) -> list[str]:
    query_tokens: set[str] = set()
    for value in [*(query.get("phenotypes") or []), *(query.get("hpo_ids") or []), query.get("condition")]:
        query_tokens.update(_meaningful_tokens(value))
    text_tokens = set(_meaningful_tokens(text))
    return sorted(query_tokens & text_tokens)


def _source_family(source_id: str, source_type: str, text: str) -> str:
    tokens = set(_tokens(" ".join([source_id, source_type, text])))
    if tokens & {"hpo", "mondo", "ontology"}:
        return "ontology_source"
    if tokens & RARE_DISEASE_SOURCE_TOKENS:
        return "rare_disease_source"
    if tokens & {"literature", "pubmed", "pmid", "doi"}:
        return "literature_source"
    return "source_record"


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen = set()
    for record in records:
        key = (record.get("source_url"), record.get("source_title"), record.get("finding"), tuple(record.get("genes") or []), tuple(record.get("diseases") or []), tuple(record.get("disease_ids") or []))
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output


def _record_text(record: dict[str, Any]) -> str:
    return " ".join(str(record.get(key) or "") for key in ("text", "finding", "title", "source_type", "source_title"))


def _verification_status(verified_fields: dict[str, Any], support_spans: list[dict[str, str]]) -> str:
    if any(verified_fields.get(key) for key in ("genes", "diseases", "disease_ids", "phenotypes", "hpo_ids")) and support_spans:
        return "verified"
    if any(verified_fields.get(key) for key in ("genes", "diseases", "disease_ids", "phenotypes", "hpo_ids")) or support_spans:
        return "partially_verified"
    return "unverified"


def _verification_limitations(query: dict[str, Any], verified_fields: dict[str, Any], source_url: Any) -> list[str]:
    limitations = []
    if not source_url:
        limitations.append("source_url_missing")
    if (query.get("phenotypes") or query.get("hpo_ids")) and not (verified_fields.get("phenotypes") or verified_fields.get("hpo_ids")):
        limitations.append("requested_phenotype_not_source_verified")
    if query.get("condition") and not verified_fields.get("diseases"):
        limitations.append("requested_condition_not_source_verified")
    return limitations


def _verified_field_text(verified_fields: dict[str, Any]) -> str:
    chunks: list[str] = []
    for value in verified_fields.values():
        if isinstance(value, list):
            chunks.extend(str(item) for item in value)
        else:
            chunks.append(str(value))
    return " ".join(chunks)


def _hpo_public_summary(context: dict[str, Any]) -> dict[str, Any]:
    primary = context.get("primary_gene_disease_evidence") if isinstance(context.get("primary_gene_disease_evidence"), dict) else {}
    return {
        "status": context.get("status"),
        "queried_hpo_ids": context.get("queried_hpo_ids") or [],
        "matched_record_count": context.get("matched_record_count", 0),
        "annotation_file_available": bool(context.get("annotation_file")),
        "primary_gene_disease_evidence": {
            "status": primary.get("status"),
            "coverage_state": primary.get("coverage_state"),
            "association_count": len(primary.get("associations") or []),
            "source_coverage": primary.get("source_coverage"),
        } if primary else None,
        "error": context.get("error"),
        "tool_will_work": context.get("tool_will_work"),
        "missing_library": context.get("missing_library"),
        "how_it_helps": context.get("how_it_helps"),
        "ask_user": context.get("ask_user"),
        "library_install_request": context.get("library_install_request"),
    }


def _collect_terms(*, text: str | None, terms: Iterable[str] | None) -> list[str]:
    values: list[str] = []
    if terms is not None:
        values.extend(str(term) for term in terms)
    if text:
        parts = re.split(r"[,;\n]+", text)
        values.extend(part.strip() for part in parts if part.strip())
    return _dedupe(values)


def _phenotype_term_usage(semantic: retrieval_semantic.SemanticContext) -> dict[str, Any]:
    term_matches: list[dict[str, Any]] = []
    term_misses: list[dict[str, Any]] = []
    for text in retrieval_semantic.search_terms(semantic, entity_types=("phenotype", "trait_or_condition")):
        hpo_ids = _normalize_hpo_ids([text])
        if hpo_ids:
            term_matches.append(
                {
                    "text": text,
                    "status": "hit",
                    "match_type": "exact_hpo_identifier",
                    "matched_ids": hpo_ids,
                }
            )
        else:
            term_misses.append({"text": text, "status": "miss"})
    return retrieval_semantic.term_usage_payload(
        semantic,
        term_matches=term_matches,
        term_misses=term_misses,
        streams=retrieval_semantic.retrieval_streams(
            raw_query=semantic.raw_query,
            host_terms=retrieval_semantic.search_terms(semantic, entity_types=("phenotype", "trait_or_condition")),
            exact_ids=[identifier for item in term_matches for identifier in item.get("matched_ids", [])],
        ),
    )


def _stored_search_queries(query_terms: Iterable[str | None]) -> list[str]:
    queries = []
    for value in query_terms:
        text = _clean_text(value)
        if not text:
            continue
        tokens = text.split()
        queries.append(" ".join(tokens[:6]))
    return _dedupe(queries)


def _prepare_source_records(
    source_records: Iterable[dict[str, Any]] | None,
    *,
    stored_records: list[dict[str, Any]],
    annotation_records: list[dict[str, Any]] | None = None,
    query: dict[str, Any],
) -> list[dict[str, Any]]:
    records = [
        _normalize_source_record(record, source_origin="provided_source_record", query=query)
        for record in (source_records or [])
        if isinstance(record, dict)
    ]
    records.extend(
        _normalize_source_record(record, source_origin="public_annotation_source", query=query)
        for record in (annotation_records or [])
    )
    records.extend(_normalize_source_record(_stored_research_to_source_record(record), source_origin="stored_reviewed_research", query=query) for record in stored_records)
    return _dedupe_records(records)


def _normalize_source_record(record: dict[str, Any], *, source_origin: str, query: dict[str, Any]) -> dict[str, Any]:
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    finding = record.get("finding") if isinstance(record.get("finding"), dict) else {}
    verified_fields = _verified_fields(record)
    support_spans = _valid_support_spans(record)
    verified_fields = _merge_verified_fields(verified_fields, _verified_fields_from_spans(support_spans))
    text = _clean_text(
        " ".join(
            str(item or "")
            for item in (
                record.get("text"),
                record.get("snippet"),
                record.get("abstract"),
                finding.get("text"),
                finding.get("summary"),
            )
        )
    )
    title = _clean_text(record.get("title") or source.get("title") or record.get("source_title"))
    source_type = _clean_text(record.get("source_type") or source.get("type") or record.get("type"))
    source_id = _clean_text(record.get("source_id") or source.get("source_id"))
    source_title = _clean_text(record.get("source_title") or source.get("title") or title)
    source_url = record.get("source_url") or source.get("url") or record.get("url")
    source_text = " ".join([text, title, source_type, source_title, source_id, _verified_field_text(verified_fields)])
    normalized = {
        **record,
        "record_id": str(record.get("record_id") or record.get("finding_id") or record.get("id") or _record_digest(record)),
        "source_title": source_title or title or "source record",
        "source_url": source_url,
        "source_type": source_type,
        "source_id": source_id,
        "title": title,
        "text": text,
        "finding": _clean_text(record.get("finding") if not isinstance(record.get("finding"), dict) else finding.get("text") or finding.get("summary")),
        "genes": _normalize_genes([*_as_list(record.get("genes")), record.get("gene"), *(verified_fields.get("genes") or [])]),
        "diseases": _normalize_diseases(
            [
                *_as_list(record.get("diseases")),
                *_as_list(record.get("conditions")),
                record.get("disease"),
                record.get("condition"),
                *(verified_fields.get("diseases") or []),
            ]
        ),
        "disease_ids": _normalize_disease_ids([*_as_list(record.get("disease_ids")), record.get("disease_id"), *(verified_fields.get("disease_ids") or [])]),
        "phenotypes": _normalize_terms(
            [
                *_as_list(record.get("phenotypes")),
                *_as_list(record.get("phenotype_terms")),
                record.get("phenotype"),
                *(verified_fields.get("phenotypes") or []),
            ]
        ),
        "hpo_ids": _normalize_hpo_ids([*_as_list(record.get("hpo_ids")), *_as_list(record.get("hpo_id")), *(verified_fields.get("hpo_ids") or [])]),
    }
    normalized["verification"] = {
        "status": _verification_status(verified_fields, support_spans),
        "source_origin": source_origin,
        "source_family": _source_family(source_id, source_type, source_text),
        "verified_fields": verified_fields,
        "support_spans": support_spans,
        "query_context_support": _query_context_support(query, verified_fields, source_text),
        "limitations": _verification_limitations(query, verified_fields, source_url),
    }
    return normalized


def _verified_fields(record: dict[str, Any]) -> dict[str, Any]:
    raw = record.get("verified_fields")
    if not isinstance(raw, dict):
        raw = {}
    genes = _normalize_genes([*_as_list(raw.get("genes")), raw.get("gene")])
    diseases = _normalize_diseases([*_as_list(raw.get("diseases")), *_as_list(raw.get("conditions")), raw.get("disease"), raw.get("condition")])
    disease_ids = _normalize_disease_ids([*_as_list(raw.get("disease_ids")), raw.get("disease_id"), raw.get("database_id")])
    phenotypes = _normalize_terms([*_as_list(raw.get("phenotypes")), *_as_list(raw.get("phenotype_terms")), raw.get("phenotype")])
    hpo_ids = _normalize_hpo_ids([*_as_list(raw.get("hpo_ids")), raw.get("hpo_id")])
    output: dict[str, Any] = {}
    if genes:
        output["genes"] = genes
    if diseases:
        output["diseases"] = diseases
    if disease_ids:
        output["disease_ids"] = disease_ids
    if phenotypes:
        output["phenotypes"] = phenotypes
    if hpo_ids:
        output["hpo_ids"] = hpo_ids
    return output


def _valid_support_spans(record: dict[str, Any]) -> list[dict[str, str]]:
    spans = record.get("support_spans")
    if not isinstance(spans, list):
        return []
    valid: list[dict[str, str]] = []
    for span in spans:
        if not isinstance(span, dict):
            continue
        field = _clean_text(span.get("field")).lower()
        value = _clean_text(span.get("value"))
        source_text = _clean_text(span.get("source_text") or span.get("text") or span.get("excerpt"))
        if field not in {"gene", "genes", "disease", "diseases", "condition", "conditions", "disease_id", "disease_ids", "database_id", "phenotype", "phenotypes", "phenotype_terms", "hpo_id", "hpo_ids"}:
            continue
        if not value or not source_text:
            continue
        if not (_value_supported_by_text(value, source_text) or HPO_ID_RE.fullmatch(value) or _disease_id(value)):
            continue
        normalized_field = {
            "gene": "genes",
            "disease": "diseases",
            "condition": "diseases",
            "conditions": "diseases",
            "disease_id": "disease_ids",
            "database_id": "disease_ids",
            "phenotype": "phenotypes",
            "phenotype_terms": "phenotypes",
            "hpo_id": "hpo_ids",
        }.get(field, field)
        valid.append({"field": normalized_field, "value": value, "source_text": source_text})
    return valid


def _verified_fields_from_spans(spans: list[dict[str, str]]) -> dict[str, Any]:
    fields: dict[str, list[str]] = {"genes": [], "diseases": [], "disease_ids": [], "phenotypes": [], "hpo_ids": []}
    for span in spans:
        fields.setdefault(span["field"], []).append(span["value"])
    return {
        "genes": _normalize_genes(fields.get("genes", [])),
        "diseases": _normalize_diseases(fields.get("diseases", [])),
        "disease_ids": _normalize_disease_ids(fields.get("disease_ids", [])),
        "phenotypes": _normalize_terms(fields.get("phenotypes", [])),
        "hpo_ids": _normalize_hpo_ids(fields.get("hpo_ids", [])),
    }


def _merge_verified_fields(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {
        "genes": _normalize_genes([*(left.get("genes") or []), *(right.get("genes") or [])]),
        "diseases": _normalize_diseases([*(left.get("diseases") or []), *(right.get("diseases") or [])]),
        "disease_ids": _normalize_disease_ids([*(left.get("disease_ids") or []), *(right.get("disease_ids") or [])]),
        "phenotypes": _normalize_terms([*(left.get("phenotypes") or []), *(right.get("phenotypes") or [])]),
        "hpo_ids": _normalize_hpo_ids([*(left.get("hpo_ids") or []), *(right.get("hpo_ids") or [])]),
    }


def _stored_records(
    evidence_db: str | Path | None,
    *,
    query_terms: Iterable[str | None],
    search_stored_research: bool,
    limit: int,
) -> list[dict[str, Any]]:
    if evidence_db is None or not search_stored_research:
        return []
    records: list[dict[str, Any]] = []
    remaining = max(0, int(limit or 25))
    for query in _stored_search_queries(query_terms):
        if remaining <= 0:
            break
        try:
            result = search_research_findings(evidence_db, query, scope="shared", limit=remaining)
        except (OSError, ValueError, sqlite3.Error):
            continue
        for record in result.get("records") or []:
            if isinstance(record, dict):
                records.append(record)
                remaining -= 1
                if remaining <= 0:
                    break
    return records


def _stored_research_to_source_record(record: dict[str, Any]) -> dict[str, Any]:
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    finding = record.get("finding") if isinstance(record.get("finding"), dict) else {}
    target = record.get("target") if isinstance(record.get("target"), dict) else {}
    raw = {
        "record_id": record.get("finding_id"),
        "genes": [target.get("gene")] if target.get("gene") else [],
        "diseases": [target.get("condition")] if target.get("condition") else [],
        "source_title": source.get("title"),
        "source_url": source.get("url"),
        "source_type": source.get("type"),
        "source_id": source.get("source_id"),
        "finding": finding.get("text") or finding.get("summary"),
        "finding_type": finding.get("type"),
        "searched_query": record.get("searched_query"),
        "captured_by": record.get("captured_by"),
        "captured_at": record.get("captured_at"),
    }
    for key in ("verified_fields", "support_spans", "verification_status"):
        if key in record:
            raw[key] = record[key]
    return raw


def _query_context_support(query: dict[str, Any], verified_fields: dict[str, Any], source_text: str) -> dict[str, str]:
    support: dict[str, str] = {}
    verified_hpo = {str(item).upper() for item in verified_fields.get("hpo_ids") or []}
    for hpo_id in query.get("hpo_ids") or []:
        support[f"hpo:{hpo_id}"] = "verified_hpo" if hpo_id.upper() in verified_hpo else ("mentioned_unverified" if hpo_id.upper() in source_text.upper() else "not_supported")
    verified_terms = verified_fields.get("phenotypes") or []
    for term in query.get("phenotypes") or []:
        support[f"phenotype:{term}"] = "verified_term" if _any_field_matches(term, verified_terms) else ("mentioned_unverified" if _value_supported_by_text(term, source_text) else "not_supported")
    condition = query.get("condition")
    if condition:
        diseases = verified_fields.get("diseases") or []
        support[f"condition:{condition}"] = "verified_condition" if _any_field_matches(condition, diseases) else ("mentioned_unverified" if _value_supported_by_text(condition, source_text) else "not_supported")
    return support
