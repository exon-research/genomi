from __future__ import annotations

import re
from typing import Any

from ....retrieval import semantic as retrieval_semantic
from ....runtime.libraries import manager as library_manager

JsonObject = dict[str, Any]
_PGXDB_LIBRARY = library_manager.get("pgxdb")
_PGXDB_API_URL = (_PGXDB_LIBRARY.source.api_base or "").rstrip("/")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).strip().split())
    return cleaned or None


def _normalize_rsid(value: str | None) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    token = cleaned.split()[0].split(",")[0].strip()
    return token.lower() if token.lower().startswith("rs") else token


def _normalize_gene(value: str | None) -> str | None:
    cleaned = _clean(value)
    return cleaned.upper() if cleaned else None


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _dedupe_params(items: list[JsonObject]) -> list[JsonObject]:
    import json

    seen = set()
    result = []
    for item in items:
        key = json.dumps(item, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _single_value(values: list[str]) -> str | None:
    unique = _dedupe([value for value in values if value])
    return unique[0] if len(unique) == 1 else None


def _as_dicts(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return [value] if isinstance(value, dict) else []
    return [item for item in value if isinstance(item, dict)]


def _compact_text(value: object, *, max_chars: int = 900) -> str:
    text = " ".join(str(value).split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _compact_selected_fields(record: JsonObject, fields: tuple[str, ...]) -> JsonObject:
    compact: JsonObject = {}
    for key in fields:
        value = record.get(key)
        if value is None or value == "" or value == []:
            continue
        compact[key] = _compact_text(value) if isinstance(value, str) else value
    return compact


def _compact_references(value: object, *, limit: int = 12) -> list[JsonObject]:
    references = []
    for item in _as_dicts(value)[:limit]:
        compact = _compact_selected_fields(
            item,
            ("id", "accession_id", "symbol", "name", "object_class", "resolution"),
        )
        if compact:
            references.append(compact)
    return references


def _pmid_values(value: object) -> list[str]:
    if value is None:
        return []
    values = []
    for token in re.findall(r"\d+", str(value)):
        if token not in values:
            values.append(token)
    return values


def _pmid_citations(value: object) -> list[JsonObject]:
    citations = []
    for pmid in _pmid_values(value):
        citations.append({"type": "pubmed", "id": pmid, "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"})
    return citations


def _literature_citations(value: object) -> list[JsonObject]:
    citations = []
    for item in _as_dicts(value):
        compact = _compact_selected_fields(item, ("id", "title", "pubmed_id", "pmid", "url", "published_at", "_sameAs"))
        if compact:
            citations.append(compact)
    return citations[:8]


def _traceability_status(source_url: object) -> JsonObject:
    return {"status": "source_traceable" if source_url else "missing_source_url"}


def _stable_evidence_source_identity(source: object) -> object:
    if not isinstance(source, dict):
        return source
    volatile = {"accessed_at", "captured_at"}
    return {key: value for key, value in source.items() if key not in volatile}


def _first_reference_name(value: object) -> str | None:
    for item in _as_dicts(value):
        name = item.get("name")
        if name:
            return str(name)
    return None


def _first_reference_symbol(value: object) -> str | None:
    for item in _as_dicts(value):
        symbol = item.get("symbol") or item.get("name")
        if symbol:
            return str(symbol)
    return None


def _pgxdb_record_source_url(record: JsonObject) -> str | None:
    atc = record.get("atc_code")
    if atc:
        return f"{_PGXDB_API_URL}/atc/pgx/{atc}/"
    return _PGXDB_API_URL


def _pgxdb_gene_drug_source_url() -> str:
    return f"{_PGXDB_API_URL}/gene/drug/"


def _clinpgx_source_title(record: JsonObject) -> str:
    evidence_class = record.get("evidence_class")
    if evidence_class == "guideline_annotation":
        return f"ClinPGx {record.get('guideline_source') or ''} guideline annotation".strip()
    if evidence_class == "clinical_annotation":
        return "ClinPGx clinical annotation"
    if evidence_class == "drug_label_annotation":
        return f"ClinPGx {record.get('label_source') or ''} drug label annotation".strip()
    return "ClinPGx pharmacogenomic evidence"


def _compact_clinpgx_record(record: JsonObject, *, text_keys: tuple[str, ...]) -> JsonObject:
    compact = _compact_selected_fields(
        record,
        (
            "id",
            "accession_id",
            "evidence_class",
            "name",
            "display_name",
            "guideline_source",
            "label_source",
            "level_of_evidence",
            "recommendation",
            "dosing_information",
            "alternate_drug_available",
            "testing_level",
            "biomarker_status",
            "source_url",
        ),
    )
    for key in text_keys:
        if record.get(key):
            compact[key] = _compact_text(record.get(key))
    for key in ("related_chemicals", "related_genes", "prescribing_genes", "haplotypes", "diplotypes"):
        values = _compact_references(record.get(key))
        if values:
            compact[key] = values
    if record.get("phenotype_categories"):
        compact["phenotype_categories"] = [str(item) for item in (record.get("phenotype_categories") or [])[:12] if item]
    if record.get("literature"):
        compact["literature"] = [
            _compact_selected_fields(item, ("id", "title", "pubmed_id", "pmid", "url", "published_at", "_sameAs"))
            for item in _as_dicts(record.get("literature"))[:5]
        ]
    return compact


def _compact_pgxdb_record(record: JsonObject) -> JsonObject:
    return _compact_selected_fields(
        record,
        (
            "drugbank_id",
            "drug",
            "atc_code",
            "rsid",
            "variant_or_haplotype",
            "alleles",
            "direction_of_effect",
            "pd_pk_terms",
            "phenotype_category",
            "significance",
            "sentence",
            "pmid",
        ),
    )


def _compact_public_source_result(result: JsonObject) -> JsonObject:
    compact = {
        key: result[key]
        for key in (
            "ok",
            "status",
            "source",
            "query",
            "resolved",
            "resolved_atc_codes",
            "summary",
            "sample_follow_up_targets",
            "clinical_verification",
            "warnings",
        )
        if key in result
    }
    if "guideline_annotations" in result:
        compact["guideline_annotations"] = [
            _compact_clinpgx_record(record, text_keys=("summary", "text_excerpt"))
            for record in result.get("guideline_annotations") or []
        ]
    if "clinical_annotations" in result:
        compact["clinical_annotations"] = [
            _compact_clinpgx_record(record, text_keys=("summary", "text_excerpt"))
            for record in result.get("clinical_annotations") or []
        ]
    if "label_annotations" in result:
        compact["label_annotations"] = [
            _compact_clinpgx_record(record, text_keys=("summary", "prescribing_excerpt", "text_excerpt"))
            for record in result.get("label_annotations") or []
        ]
    if "pgx_records" in result:
        compact["pgx_records"] = [_compact_pgxdb_record(record) for record in result.get("pgx_records") or []]
    if "gene_drug_records" in result:
        compact["gene_drug_records"] = [
            _compact_selected_fields(record, ("gene", "drugbank_id", "actions", "known_action", "interaction_type", "target_scope"))
            for record in result.get("gene_drug_records") or []
        ]
    if "medication_scoped_gene_drug_records" in result:
        compact["medication_scoped_gene_drug_records"] = [
            _compact_selected_fields(record, ("gene", "drugbank_id", "actions", "known_action", "interaction_type", "target_scope"))
            for record in result.get("medication_scoped_gene_drug_records") or []
        ]
    if "variant_context_records" in result:
        compact["variant_context_records"] = [
            _compact_selected_fields(record, ("variant", "rsid", "gene", "source", "source_url", "summary", "pmid"))
            for record in result.get("variant_context_records") or []
        ]
    return compact


def _selected_semantic_target(
    *,
    raw_value: str | None,
    semantic: retrieval_semantic.SemanticContext,
    entity_types: tuple[str, ...],
) -> str | None:
    typed = [
        str(entity.get("text") or "").strip()
        for entity in semantic.host_entities
        if str(entity.get("type") or "").strip().casefold() in {item.casefold() for item in entity_types}
        and str(entity.get("text") or "").strip()
    ]
    if typed and (not raw_value or _looks_like_free_text_target(raw_value)):
        return typed[0]
    return raw_value


def _looks_like_free_text_target(value: str) -> bool:
    tokens = [token for token in re.findall(r"[A-Za-z0-9]+", value) if token]
    return len(tokens) > 2


def _pgx_semantic_usage(
    semantic: retrieval_semantic.SemanticContext,
    *,
    raw_drug: str | None,
    selected_drug: str | None,
    selected_gene: str | None,
    selected_rsid: str | None,
    source_evidence_count: int,
    rsid_targets: list[str],
    star_genes: list[str],
) -> JsonObject:
    terms = retrieval_semantic.search_terms(semantic)
    term_matches: list[JsonObject] = []
    term_misses: list[JsonObject] = []
    selected_targets = {
        str(value or "").casefold()
        for value in [selected_drug, selected_gene, selected_rsid, *rsid_targets, *star_genes]
        if value
    }
    for term in terms:
        key = term.casefold()
        if key in selected_targets and source_evidence_count > 0:
            term_matches.append(
                {
                    "text": term,
                    "status": "hit",
                    "match_type": "matched_public_pgx_source_records",
                    "selected_target": term,
                }
            )
        else:
            term_misses.append({"text": term, "status": "miss"})
    return retrieval_semantic.term_usage_payload(
        semantic,
        term_matches=term_matches,
        term_misses=term_misses,
        streams=retrieval_semantic.retrieval_streams(
            raw_query=semantic.raw_query or raw_drug,
            host_terms=terms,
            exact_ids=[value for value in (selected_gene, selected_rsid) if value],
            source_native_filters=[value for value in (selected_drug, selected_gene, selected_rsid) if value],
        ),
    )
