from __future__ import annotations

import csv
import io
import os
import urllib.error
import urllib.parse
from collections.abc import Iterable
from typing import Any

from ....retrieval import semantic as retrieval_semantic
from .helpers import (
    BIOGRID_ORCS_ACCESS_KEY_ENV,
    BIOGRID_ORCS_API_BASE,
    DEPMAP_CRISPR_GENE_EFFECT_URL_ENV,
    DEPMAP_MODEL_URL_ENV,
    SCREEN_EXPERIMENT_RECORDS_SCHEMA_VERSION,
    SUPPORTED_NATIVE_SCREEN_SOURCES,
    _as_float,
    _canonical,
    _clean_text,
    _fetch_json,
    _fetch_text,
    _first_score,
    _first_text,
    _json_records,
    _normalize_gene,
    _normalize_genes,
    _normalize_sources,
    _organism_id,
    _orcs_library_methodology,
    _screen_semantic_usage,
    _semantic_screen_fields,
    _url,
)


def retrieve_public_screen_records(
    *,
    context: str,
    genes: Iterable[str],
    organism: str | None = None,
    cell_line: str | None = None,
    perturbation: str | None = None,
    assay: str | None = None,
    phenotype: str | None = None,
    sources: Iterable[str] | None = None,
    biogrid_orcs_access_key: str | None = None,
    biogrid_orcs_api_base: str = BIOGRID_ORCS_API_BASE,
    depmap_gene_effect_url: str | None = None,
    depmap_model_url: str | None = None,
    fetch_json: Any | None = None,
    fetch_text: Any | None = None,
    limit: int = 100,
    semantic_context: object = None,
) -> dict[str, Any]:
    """Retrieve native public screen records from declared screen data sources."""

    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    semantic_fields = _semantic_screen_fields(semantic)
    normalized_genes = _normalize_genes(genes)
    if not normalized_genes:
        raise ValueError("functional_genomics.retrieve_perturbation_records requires candidate genes")
    query = {
        "context": _clean_text(context),
        "genes": normalized_genes,
        "organism": _clean_text(organism) or semantic_fields.get("organism", ""),
        "cell_line": _clean_text(cell_line) or semantic_fields.get("cell_line", ""),
        "perturbation": _clean_text(perturbation) or semantic_fields.get("perturbation", ""),
        "assay": _clean_text(assay) or semantic_fields.get("assay", ""),
        "phenotype": _clean_text(phenotype) or semantic_fields.get("phenotype", ""),
        "semantic_context_terms": retrieval_semantic.search_terms(semantic),
    }
    requested_sources = _normalize_sources(sources or SUPPORTED_NATIVE_SCREEN_SOURCES)
    unsupported = [source for source in requested_sources if source not in SUPPORTED_NATIVE_SCREEN_SOURCES]
    if unsupported:
        return _public_screen_response(
            query=query,
            requested_sources=requested_sources,
            source_records=[],
            status="unsupported_source",
            coverage_state="out_of_scope_for_input",
            sources_consulted=[],
            sources_consulted_and_empty=[],
            sources_consulted_but_unavailable=[],
            empty_reason=f"Unsupported functional-genomics perturbation source(s): {', '.join(unsupported)}",
        )

    json_fetcher = fetch_json or _fetch_json
    text_fetcher = fetch_text or _fetch_text
    records: list[dict[str, Any]] = []
    consulted: list[str] = []
    consulted_empty: list[str] = []
    unavailable: list[dict[str, str]] = []
    return_limit = max(1, int(limit or 100))

    if "biogrid_orcs" in requested_sources:
        access_key = _clean_text(biogrid_orcs_access_key or os.environ.get(BIOGRID_ORCS_ACCESS_KEY_ENV))
        if not access_key:
            unavailable.append({"source": "BioGRID ORCS", "error": f"missing {BIOGRID_ORCS_ACCESS_KEY_ENV}"})
        else:
            try:
                orcs_records = _retrieve_biogrid_orcs_screen_records(
                    query=query,
                    access_key=access_key,
                    api_base=biogrid_orcs_api_base,
                    fetch_json=json_fetcher,
                    limit=return_limit,
                )
                consulted.append("BioGRID ORCS")
                if orcs_records:
                    records.extend(orcs_records)
                else:
                    consulted_empty.append("BioGRID ORCS")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
                unavailable.append({"source": "BioGRID ORCS", "error": str(exc)})

    if "depmap" in requested_sources:
        gene_effect_url = _clean_text(depmap_gene_effect_url or os.environ.get(DEPMAP_CRISPR_GENE_EFFECT_URL_ENV))
        model_url = _clean_text(depmap_model_url or os.environ.get(DEPMAP_MODEL_URL_ENV))
        if not gene_effect_url:
            unavailable.append({"source": "DepMap CRISPR gene effect", "error": f"missing {DEPMAP_CRISPR_GENE_EFFECT_URL_ENV}"})
        else:
            try:
                depmap_records = _retrieve_depmap_crispr_records(
                    query=query,
                    gene_effect_url=gene_effect_url,
                    model_url=model_url or None,
                    fetch_text=text_fetcher,
                    limit=return_limit,
                )
                consulted.append("DepMap CRISPR gene effect")
                if depmap_records:
                    records.extend(depmap_records)
                else:
                    consulted_empty.append("DepMap CRISPR gene effect")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError, csv.Error) as exc:
                unavailable.append({"source": "DepMap CRISPR gene effect", "error": str(exc)})

    records = _dedupe_native_records(records)
    records = _sort_native_records(records)[:return_limit]
    if records:
        status = "screen_records_found"
        coverage_state = "data_returned"
        empty_reason = None
    elif consulted or consulted_empty:
        status = "no_matching_screen_records"
        coverage_state = "in_scope_empty"
        empty_reason = "Native functional-genomics perturbation sources were consulted but returned no records for the supplied genes and context."
    else:
        status = "perturbation_sources_unavailable"
        coverage_state = "out_of_scope_for_input"
        empty_reason = "No native functional-genomics perturbation source could be queried for this input."
    return _public_screen_response(
        query=query,
        requested_sources=requested_sources,
        source_records=records,
        status=status,
        coverage_state=coverage_state,
        sources_consulted=consulted,
        sources_consulted_and_empty=consulted_empty,
        sources_consulted_but_unavailable=unavailable,
        empty_reason=empty_reason,
        semantic_context=semantic,
    )


def _retrieve_biogrid_orcs_screen_records(
    *,
    query: dict[str, str],
    access_key: str,
    api_base: str,
    fetch_json: Any,
    limit: int,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "accesskey": access_key,
        "format": "json",
        "max": min(max(limit, 1), 100),
        "organismID": _organism_id(query.get("organism")),
    }
    if query.get("cell_line"):
        params["cellLine"] = query["cell_line"]
    if query.get("phenotype"):
        params["phenotype"] = query["phenotype"]
    methodology = _orcs_library_methodology(query.get("perturbation") or query.get("context") or "")
    if methodology:
        params["libraryMethodology"] = methodology
    screen_payload = fetch_json(_url(api_base, "/screens/", params))
    screens = _json_records(screen_payload)
    records: list[dict[str, Any]] = []
    for screen_row in screens[: max(1, limit)]:
        screen_id = _first_text(screen_row, "SCREEN_ID", "screen_id", "screenID", "Screen ID", "id")
        if not screen_id:
            continue
        score_payload = fetch_json(
            _url(
                api_base,
                f"/screen/{urllib.parse.quote(screen_id, safe='')}",
                {
                    "accesskey": access_key,
                    "format": "json",
                    "hit": "all",
                    "name": "|".join(query["genes"]),
                },
            )
        )
        for score_row in _json_records(score_payload):
            record = _biogrid_score_record(screen_row, score_row, query=query, screen_id=screen_id)
            if record:
                records.append(record)
    return records


def _retrieve_depmap_crispr_records(
    *,
    query: dict[str, str],
    gene_effect_url: str,
    model_url: str | None,
    fetch_text: Any,
    limit: int,
) -> list[dict[str, Any]]:
    if not _depmap_context_applies(query):
        return []
    model_aliases = _depmap_model_aliases(fetch_text(model_url)) if model_url else {}
    cell_line_query = query.get("cell_line") or query.get("context") or ""
    gene_effect_text = fetch_text(gene_effect_url)
    reader = csv.DictReader(io.StringIO(gene_effect_text))
    if not reader.fieldnames:
        return []
    row_id_field = reader.fieldnames[0]
    gene_columns = {
        _depmap_gene_from_column(column): column
        for column in reader.fieldnames[1:]
        if _depmap_gene_from_column(column) in set(query["genes"])
    }
    if not gene_columns:
        return []
    records: list[dict[str, Any]] = []
    for row in reader:
        row_id = _clean_text(row.get(row_id_field))
        if not _depmap_row_matches_cell_line(row_id, cell_line_query, model_aliases):
            continue
        for gene, column in gene_columns.items():
            score = _as_float(row.get(column))
            if score is None:
                continue
            records.append(_depmap_gene_effect_record(query=query, gene=gene, score=score, row_id=row_id, source_url=gene_effect_url))
        if len(records) >= max(1, limit):
            break
    return records


def _public_screen_response(
    *,
    query: dict[str, Any],
    requested_sources: list[str],
    source_records: list[dict[str, Any]],
    status: str,
    coverage_state: str,
    sources_consulted: list[str],
    sources_consulted_and_empty: list[str],
    sources_consulted_but_unavailable: list[dict[str, str]],
    empty_reason: str | None = None,
    semantic_context: retrieval_semantic.SemanticContext | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": SCREEN_EXPERIMENT_RECORDS_SCHEMA_VERSION,
        "status": status,
        "coverage_state": coverage_state,
        "agent_decision_required": True,
        "query": query,
        "capability": {
            "name": "functional_genomics.retrieve_perturbation_records",
            "scope": "Native public screen evidence retrieval for candidate genes and declared experimental context.",
            "supported_sources": SUPPORTED_NATIVE_SCREEN_SOURCES,
        },
        "source_coverage": {
            "coverage_state": coverage_state,
            "sources_requested": requested_sources,
            "sources_consulted": sources_consulted,
            "sources_consulted_and_empty": sources_consulted_and_empty,
            "sources_consulted_but_unavailable": sources_consulted_but_unavailable,
            "sources_not_integrated": [
                "Mendeley, Zenodo, and journal supplementary perturbation table discovery",
                "GEO/ArrayExpress perturbation-table discovery",
            ],
        },
        "coverage": {
            "source_record_count": len(source_records),
            "candidate_gene_count": len(query.get("genes") or []),
        },
    }
    if source_records:
        payload["source_records"] = source_records
        payload["direct_perturbation_source_records"] = source_records
        payload["records_by_gene"] = _records_by_gene(source_records)
    if empty_reason:
        payload["empty_reason"] = empty_reason
    if semantic_context and semantic_context.has_hints:
        payload["semantic_context"] = _screen_semantic_usage(semantic_context, source_records, query)
    return payload


def _biogrid_score_record(screen_row: dict[str, Any], score_row: dict[str, Any], *, query: dict[str, Any], screen_id: str) -> dict[str, Any] | None:
    gene = _normalize_gene(_first_text(score_row, "OFFICIAL_SYMBOL", "official_symbol", "officialSymbol", "name", "gene", "symbol"))
    if not gene or gene not in set(query["genes"]):
        return None
    score = _first_score(score_row)
    title = _first_text(screen_row, "SCREEN_TITLE", "screen_title", "title", "name", "Screen Title") or f"BioGRID ORCS screen {screen_id}"
    source_url = f"https://orcs.thebiogrid.org/Screen/{screen_id}"
    cell_line = _clean_text(query.get("cell_line")) or _first_text(screen_row, "CELL_LINE", "cell_line", "cellLine")
    perturbation = _clean_text(query.get("perturbation")) or _first_text(screen_row, "LIBRARY_METHODOLOGY", "libraryMethodology", "screenType")
    phenotype = _clean_text(query.get("phenotype")) or _first_text(screen_row, "PHENOTYPE", "phenotype", "conditionName")
    score_text = f"; score {score}" if score is not None else ""
    finding = f"{gene} is present in BioGRID ORCS screen {screen_id}{score_text}."
    verified_fields = {"genes": [gene]}
    if cell_line:
        verified_fields["cell_line"] = cell_line
    if perturbation:
        verified_fields["perturbation"] = perturbation
    if phenotype:
        verified_fields["phenotype"] = phenotype
    return {
        "record_id": f"biogrid_orcs:{screen_id}:{gene}",
        "genes": [gene],
        "source_type": "BioGRID ORCS CRISPR screen",
        "source_title": title,
        "source_url": source_url,
        "cell_line": cell_line,
        "perturbation": perturbation,
        "phenotype": phenotype,
        "finding": finding,
        "screen_id": screen_id,
        "screen_score": score,
        "raw_source": {"screen": screen_row, "score": score_row},
        "verified_fields": verified_fields,
        "support_spans": _native_support_spans(gene=gene, cell_line=cell_line, perturbation=perturbation, phenotype=phenotype, source_text=f"{title} {finding}"),
    }


def _depmap_gene_effect_record(*, query: dict[str, Any], gene: str, score: float, row_id: str, source_url: str) -> dict[str, Any]:
    cell_line = _clean_text(query.get("cell_line")) or row_id
    perturbation = _clean_text(query.get("perturbation")) or "CRISPR knockout"
    phenotype = _clean_text(query.get("phenotype")) or "dependency"
    source_title = "DepMap public CRISPR gene effect"
    finding = f"{gene} has DepMap CRISPR gene effect {score:g} in {cell_line}."
    verified_fields = {"genes": [gene], "cell_line": cell_line, "perturbation": perturbation, "phenotype": phenotype}
    return {
        "record_id": f"depmap:{row_id}:{gene}",
        "genes": [gene],
        "source_type": "DepMap CRISPR screen",
        "source_title": source_title,
        "source_url": source_url,
        "cell_line": cell_line,
        "perturbation": perturbation,
        "phenotype": phenotype,
        "finding": finding,
        "screen_score": score,
        "score_direction": "more_negative_is_stronger_dependency",
        "verified_fields": verified_fields,
        "support_spans": _native_support_spans(gene=gene, cell_line=cell_line, perturbation=perturbation, phenotype=phenotype, source_text=f"{source_title} {finding}"),
    }


def _native_support_spans(*, gene: str, cell_line: str, perturbation: str, phenotype: str, source_text: str) -> list[dict[str, str]]:
    spans = [{"field": "genes", "value": gene, "source_text": source_text}]
    for field, value in (("cell_line", cell_line), ("perturbation", perturbation), ("phenotype", phenotype)):
        if value:
            spans.append({"field": field, "value": value, "source_text": source_text})
    return spans


def _depmap_model_aliases(model_text: str) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    reader = csv.DictReader(io.StringIO(model_text))
    if not reader.fieldnames:
        return aliases
    for row in reader:
        model_id = _clean_text(row.get("ModelID") or row.get("model_id") or row.get("DepMap_ID") or row.get("depmap_id"))
        values = [
            row.get("ModelID"),
            row.get("model_id"),
            row.get("DepMap_ID"),
            row.get("depmap_id"),
            row.get("CellLineName"),
            row.get("cell_line_name"),
            row.get("CCLEName"),
            row.get("stripped_cell_line_name"),
            row.get("StrippedCellLineName"),
        ]
        normalized = {_canonical(value) for value in values if _clean_text(value)}
        if model_id and normalized:
            aliases[_canonical(model_id)] = normalized
    return aliases


def _depmap_row_matches_cell_line(row_id: str, cell_line_query: str, model_aliases: dict[str, set[str]]) -> bool:
    if not cell_line_query:
        return True
    row_key = _canonical(row_id)
    query_key = _canonical(cell_line_query)
    aliases = model_aliases.get(row_key, set()) | {row_key}
    return query_key in aliases or any(query_key in alias or alias in query_key for alias in aliases)


def _depmap_context_applies(query: dict[str, str]) -> bool:
    text = " ".join(str(query.get(field) or "") for field in ("context", "perturbation", "assay", "phenotype")).casefold()
    if not text.strip():
        return True
    return not (any(token in text for token in ("drug resistance", "toxin", "overexpression", "activation")) and not any(token in text for token in ("crispr", "knockout", "dependency", "essentiality", "viability")))


def _depmap_gene_from_column(column: str) -> str:
    text = _clean_text(column)
    if not text:
        return ""
    return _normalize_gene(text.split(" (", 1)[0].split("(", 1)[0])


def _sort_native_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(record: dict[str, Any]) -> tuple[int, float, str, str]:
        source_type = str(record.get("source_type") or "")
        score = _as_float(record.get("screen_score"))
        if "DepMap" in source_type:
            score_key = score if score is not None else 0.0
        else:
            score_key = -(abs(score) if score is not None else 0.0)
        return (
            0 if "DepMap" in source_type or "BioGRID ORCS" in source_type else 1,
            score_key,
            str(record.get("genes") or ""),
            str(record.get("record_id") or ""),
        )

    return sorted(records, key=key)


def _dedupe_native_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    seen = set()
    for record in records:
        key = (record.get("record_id"), tuple(record.get("genes") or []), record.get("source_url"))
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output


def _records_by_gene(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        for gene in record.get("genes") or []:
            grouped.setdefault(gene, []).append(record)
    return grouped
