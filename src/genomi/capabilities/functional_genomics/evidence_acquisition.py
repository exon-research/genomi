from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

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
_SCREEN_CONTEXT_FIELDS = ("organism", "cell_line", "perturbation", "assay", "phenotype")
_LOW_INFORMATION_TOKENS = {
    "and",
    "are",
    "cell",
    "cells",
    "gene",
    "genes",
    "human",
    "in",
    "line",
    "of",
    "or",
    "source",
    "study",
    "the",
    "to",
    "with",
}


def acquire_perturbation_source_records(
    *,
    context: str,
    genes: Iterable[str],
    source_records: Iterable[dict[str, Any]] | None = None,
    stored_research_records: Iterable[dict[str, Any]] | None = None,
    organism: str | None = None,
    cell_line: str | None = None,
    perturbation: str | None = None,
    assay: str | None = None,
    phenotype: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Normalize and verify source records for perturbation-evidence ranking.

    This layer intentionally does not convert generic literature summaries into
    direct perturbation evidence. It separates records whose fields are source-backed
    from unverified agent-supplied notes so downstream ranking can cap evidence
    lanes correctly.
    """

    normalized_genes = _normalize_genes(genes)
    query = _screen_query(
        context=context,
        genes=normalized_genes,
        organism=organism,
        cell_line=cell_line,
        perturbation=perturbation,
        assay=assay,
        phenotype=phenotype,
    )
    inline_records = [
        _normalize_screen_record(record, query=query, candidate_genes=normalized_genes, source_origin="provided_source_record")
        for record in (source_records or [])
        if isinstance(record, dict)
    ]
    stored_records = [
        _normalize_screen_record(
            _stored_research_to_screen_record(record),
            query=query,
            candidate_genes=normalized_genes,
            source_origin="stored_reviewed_research",
        )
        for record in (stored_research_records or [])
        if isinstance(record, dict)
    ]
    records = _dedupe_records([*inline_records, *stored_records])[: max(limit, 0)]
    verified = [record for record in records if record["verification"]["status"] in {"verified", "partially_verified"}]
    direct_ready = [record for record in records if record["verification"]["direct_perturbation_support"]]
    return {
        "schema": "genomi-perturbation-source-acquisition-v1",
        "ok": True,
        "status": _acquisition_status(records, direct_ready, verified),
        "query": query,
        "summary": {
            "candidate_gene_count": len(normalized_genes),
            "source_record_count": len(records),
            "verified_record_count": len(verified),
            "direct_perturbation_source_record_count": len(direct_ready),
            "unverified_record_count": sum(1 for record in records if record["verification"]["status"] == "unverified"),
        },
        "source_records": records,
        "verified_source_records": verified,
        "direct_perturbation_source_records": direct_ready,
        "rejected_or_limited_records": [
            _record_limitation(record)
            for record in records
            if not record["verification"]["direct_perturbation_support"]
        ],
        "source_gaps": _source_gaps(query, records, direct_ready),
        "next_actions": _next_actions(query, direct_ready),
        "acquisition_policy": {
            "policy_id": "perturbation_source_acquisition_v1",
            "direct_support_rule": (
                "A direct perturbation source record must source-verify the candidate gene plus at least one requested "
                "perturbation context field such as cell line, perturbation, assay, or phenotype."
            ),
            "generic_literature_rule": (
                "Generic literature or agent-authored summaries without source spans remain available for plausibility "
                "review but are not direct evidence."
            ),
        },
    }


def extract_screen_table_evidence_records(
    table: str | Path,
    *,
    context: str,
    genes: Iterable[str],
    column_map: dict[str, str] | None = None,
    delimiter: str | None = None,
    source_title: str | None = None,
    source_url: str | None = None,
    source_type: str | None = None,
    organism: str | None = None,
    cell_line: str | None = None,
    perturbation: str | None = None,
    assay: str | None = None,
    phenotype: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Convert a local screen result table into verified source records.

    This is a data adapter, not a selector. It extracts row-level records and
    then uses the same verifier as supplied source records.
    """

    table_path = Path(table).expanduser()
    if not table_path.exists():
        raise FileNotFoundError(str(table_path))
    normalized_genes = _normalize_genes(genes)
    if not normalized_genes:
        raise ValueError("at least one candidate gene is required")
    rows, inferred_delimiter = _read_screen_table(table_path, delimiter=delimiter, limit=limit)
    records = _screen_table_records(
        rows,
        table_path=table_path,
        candidate_genes=normalized_genes,
        column_map=column_map or {},
        source_title=_clean_text(source_title) or table_path.name,
        source_url=source_url,
        source_type=_clean_text(source_type) or "screen result table",
        organism=organism,
        cell_line=cell_line,
        perturbation=perturbation,
        assay=assay,
        phenotype=phenotype,
    )
    acquisition = acquire_perturbation_source_records(
        context=context,
        genes=normalized_genes,
        source_records=records,
        organism=organism,
        cell_line=cell_line,
        perturbation=perturbation,
        assay=assay,
        phenotype=phenotype,
        limit=limit,
    )
    return {
        "schema": "genomi-perturbation-table-evidence-records-v1",
        "ok": True,
        "status": acquisition["status"],
        "table": {
            "path": str(table_path),
            "delimiter": inferred_delimiter,
            "row_count": len(rows),
            "emitted_source_record_count": len(records),
            "skipped_row_count": max(0, len(rows) - len(records)),
        },
        "query": acquisition["query"],
        "summary": acquisition["summary"],
        "source_records": acquisition["source_records"],
        "verified_source_records": acquisition["verified_source_records"],
        "direct_perturbation_source_records": acquisition["direct_perturbation_source_records"],
        "rejected_or_limited_records": acquisition["rejected_or_limited_records"],
        "source_gaps": acquisition["source_gaps"],
        "next_actions": acquisition["next_actions"],
        "acquisition_policy": acquisition["acquisition_policy"],
    }


def normalize_screen_source_record(
    record: dict[str, Any],
    *,
    context: str,
    genes: Iterable[str],
    organism: str | None = None,
    cell_line: str | None = None,
    perturbation: str | None = None,
    assay: str | None = None,
    phenotype: str | None = None,
) -> dict[str, Any]:
    query = _screen_query(
        context=context,
        genes=_normalize_genes(genes),
        organism=organism,
        cell_line=cell_line,
        perturbation=perturbation,
        assay=assay,
        phenotype=phenotype,
    )
    return _normalize_screen_record(record, query=query, candidate_genes=query["genes"], source_origin="provided_source_record")


def verified_context_matches(record: dict[str, Any]) -> list[str]:
    support = record.get("verification", {}).get("context_field_support", {})
    return [field for field in _SCREEN_CONTEXT_FIELDS if support.get(field) == "verified_exact"]


def verified_gene_match(gene: str, record: dict[str, Any]) -> bool:
    gene = str(gene or "").strip().upper()
    if not gene:
        return False
    verified_genes = {
        str(item or "").strip().upper()
        for item in record.get("verification", {}).get("verified_fields", {}).get("genes", [])
    }
    return gene in verified_genes


def direct_perturbation_support(record: dict[str, Any]) -> bool:
    return bool(record.get("verification", {}).get("direct_perturbation_support"))


def _read_screen_table(table_path: Path, *, delimiter: str | None, limit: int) -> tuple[list[dict[str, str]], str]:
    text = table_path.read_text(encoding="utf-8-sig")
    sample = text[:4096]
    if delimiter:
        actual_delimiter = delimiter
    elif table_path.suffix.lower() in {".tsv", ".tab"}:
        actual_delimiter = "\t"
    else:
        try:
            actual_delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
        except csv.Error:
            actual_delimiter = ","
    reader = csv.DictReader(text.splitlines(), delimiter=actual_delimiter)
    rows = []
    for index, row in enumerate(reader):
        if index >= max(limit, 0):
            break
        rows.append({str(key or "").strip(): str(value or "").strip() for key, value in row.items()})
    return rows, actual_delimiter


def _screen_table_records(
    rows: list[dict[str, str]],
    *,
    table_path: Path,
    candidate_genes: list[str],
    column_map: dict[str, str],
    source_title: str,
    source_url: str | None,
    source_type: str,
    organism: str | None,
    cell_line: str | None,
    perturbation: str | None,
    assay: str | None,
    phenotype: str | None,
) -> list[dict[str, Any]]:
    records = []
    for row_number, row in enumerate(rows, start=1):
        row_text = " ".join(str(value) for value in row.values() if value)
        row_genes = _table_row_genes(row, column_map=column_map, candidate_genes=candidate_genes, row_text=row_text)
        matching_genes = [gene for gene in row_genes if gene in candidate_genes]
        if not matching_genes:
            continue
        row_context = {
            "organism": _table_value(row, column_map, "organism", ("organism", "species")) or _clean_text(organism),
            "cell_line": _table_value(row, column_map, "cell_line", ("cell_line", "cell line", "cell", "model")) or _clean_text(cell_line),
            "perturbation": _table_value(row, column_map, "perturbation", ("perturbation", "treatment", "drug", "condition")) or _clean_text(perturbation),
            "assay": _table_value(row, column_map, "assay", ("assay", "screen", "readout")) or _clean_text(assay),
            "phenotype": _table_value(row, column_map, "phenotype", ("phenotype", "trait", "effect", "readout")) or _clean_text(phenotype),
        }
        finding = _table_finding(row, column_map=column_map, genes=matching_genes, source_title=source_title, row_context=row_context)
        support_spans = [{"field": "genes", "value": gene, "source_text": finding} for gene in matching_genes]
        support_spans.extend(
            {"field": field, "value": value, "source_text": finding}
            for field, value in row_context.items()
            if value
        )
        records.append(
            {
                "record_id": f"table:{table_path.name}:{row_number}:{'-'.join(matching_genes)}",
                "genes": matching_genes,
                "source_type": _table_value(row, column_map, "source_type", ("source_type", "type")) or source_type,
                "source_title": _table_value(row, column_map, "source_title", ("source_title", "source", "study", "title")) or source_title,
                "source_url": _table_value(row, column_map, "source_url", ("source_url", "url", "doi", "pmid")) or source_url,
                "finding": finding,
                "table_row": row_number,
                "table_path": str(table_path),
                "verified_fields": {"genes": matching_genes, **{key: value for key, value in row_context.items() if value}},
                "support_spans": support_spans,
                **{key: value for key, value in row_context.items() if value},
            }
        )
    return records


def _table_row_genes(
    row: dict[str, str],
    *,
    column_map: dict[str, str],
    candidate_genes: list[str],
    row_text: str,
) -> list[str]:
    value = _table_value(row, column_map, "gene", ("gene", "genes", "symbol", "gene_symbol", "target", "target_gene"))
    genes = _normalize_genes(_split_table_genes(value))
    if genes:
        return genes
    return [gene for gene in candidate_genes if re.search(rf"\b{re.escape(gene)}\b", row_text, flags=re.I)]


def _table_value(row: dict[str, str], column_map: dict[str, str], field: str, candidates: tuple[str, ...]) -> str:
    mapped = column_map.get(field)
    if mapped and mapped in row:
        return _clean_text(row.get(mapped))
    by_key = {_table_key(key): value for key, value in row.items()}
    for candidate in candidates:
        value = by_key.get(_table_key(candidate))
        if value:
            return _clean_text(value)
    return ""


def _table_finding(
    row: dict[str, str],
    *,
    column_map: dict[str, str],
    genes: list[str],
    source_title: str,
    row_context: dict[str, str],
) -> str:
    finding = _table_value(row, column_map, "finding", ("finding", "result", "description", "summary", "effect"))
    if not finding:
        metrics = [
            f"{key}={value}"
            for key, value in row.items()
            if value and _table_key(key) not in {"gene", "genes", "symbol", "gene symbol", "target", "target gene"}
        ][:8]
        finding = "; ".join(metrics)
    context = "; ".join(f"{key}={value}" for key, value in row_context.items() if value)
    chunks = [f"{', '.join(genes)} appears in {source_title}"]
    if context:
        chunks.append(context)
    if finding:
        chunks.append(finding)
    return "; ".join(chunks)


def _split_table_genes(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;|/]+", value or "") if part.strip()]


def _table_key(value: str) -> str:
    return " ".join(_tokens(value))


def _screen_query(
    *,
    context: str,
    genes: list[str],
    organism: str | None,
    cell_line: str | None,
    perturbation: str | None,
    assay: str | None,
    phenotype: str | None,
) -> dict[str, Any]:
    return {
        "context": _clean_text(context),
        "genes": genes,
        "organism": _clean_text(organism),
        "cell_line": _clean_text(cell_line),
        "perturbation": _clean_text(perturbation),
        "assay": _clean_text(assay),
        "phenotype": _clean_text(phenotype),
    }


def _normalize_screen_record(
    record: dict[str, Any],
    *,
    query: dict[str, Any],
    candidate_genes: list[str],
    source_origin: str,
) -> dict[str, Any]:
    verified_fields = _verified_fields(record)
    support_spans = _valid_support_spans(record)
    span_fields = _verified_fields_from_spans(support_spans)
    verified_fields = _merge_verified_fields(verified_fields, span_fields)
    genes = _record_genes(record, verified_fields=verified_fields)
    text = _clean_text(record.get("text") or record.get("snippet") or record.get("abstract") or "")
    title = _clean_text(record.get("title") or "")
    finding = _clean_text(record.get("finding") or record.get("finding_text") or "")
    source_type = _clean_text(record.get("source_type") or record.get("type") or "")
    source_title = _clean_text(record.get("source_title") or record.get("source") or record.get("title") or "")
    source_url = record.get("source_url") or record.get("url")
    source_text = " ".join(str(item or "") for item in (text, title, finding, source_type, source_title))
    context_support = {
        field: _context_field_support(query.get(field) or "", verified_fields.get(field), source_text)
        for field in _SCREEN_CONTEXT_FIELDS
    }
    verified_gene_hits = _verified_gene_hits(candidate_genes, verified_fields, source_text, support_spans)
    direct_context = [field for field, status in context_support.items() if status == "verified_exact"]
    source_family = _screen_source_family(source_type, f"{source_text} {_verified_field_text(verified_fields)}")
    direct_support = bool(verified_gene_hits and direct_context and source_family == "functional_genomics_perturbation_source")
    status = _verification_status(verified_fields, support_spans, direct_support)
    return {
        **record,
        "record_id": str(record.get("record_id") or record.get("id") or _record_digest(record)),
        "genes": genes,
        "text": text,
        "title": title,
        "finding": finding,
        "source_type": source_type,
        "source_title": source_title,
        "source_url": source_url,
        "cell_line": _clean_text(record.get("cell_line") or ""),
        "perturbation": _clean_text(record.get("perturbation") or ""),
        "assay": _clean_text(record.get("assay") or ""),
        "phenotype": _clean_text(record.get("phenotype") or record.get("readout") or ""),
        "verification": {
            "status": status,
            "source_origin": source_origin,
            "source_family": source_family,
            "verified_fields": verified_fields,
            "verified_gene_hits": verified_gene_hits,
            "context_field_support": context_support,
            "direct_context_fields": direct_context,
            "direct_perturbation_support": direct_support,
            "support_spans": support_spans,
            "limitations": _verification_limitations(
                candidate_genes=candidate_genes,
                verified_gene_hits=verified_gene_hits,
                direct_context=direct_context,
                source_family=source_family,
                source_url=source_url,
            ),
        },
    }


def _stored_research_to_screen_record(record: dict[str, Any]) -> dict[str, Any]:
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    finding = record.get("finding") if isinstance(record.get("finding"), dict) else {}
    target = record.get("target") if isinstance(record.get("target"), dict) else {}
    raw = {
        "record_id": record.get("finding_id"),
        "genes": [target.get("gene")] if target.get("gene") else [],
        "source_title": source.get("title"),
        "source_url": source.get("url"),
        "source_type": source.get("type"),
        "finding": finding.get("text") or finding.get("summary"),
        "finding_type": finding.get("type"),
        "searched_query": record.get("searched_query"),
        "captured_by": record.get("captured_by"),
        "captured_at": record.get("captured_at"),
    }
    for key in ("verified_fields", "support_spans", "verification_status", "retrieval_method"):
        if key in record:
            raw[key] = record[key]
    return raw


def _verified_fields(record: dict[str, Any]) -> dict[str, Any]:
    raw = record.get("verified_fields")
    if not isinstance(raw, dict):
        raw = {}
    output: dict[str, Any] = {}
    for field in (*_SCREEN_CONTEXT_FIELDS, "genes"):
        if field not in raw:
            continue
        if field == "genes":
            output[field] = _normalize_genes(raw.get(field) if isinstance(raw.get(field), list) else [raw.get(field)])
        else:
            output[field] = _clean_text(raw.get(field))
    return {key: value for key, value in output.items() if value}


def _valid_support_spans(record: dict[str, Any]) -> list[dict[str, str]]:
    spans = record.get("support_spans")
    if not isinstance(spans, list):
        return []
    valid = []
    for span in spans:
        if not isinstance(span, dict):
            continue
        field = _clean_text(span.get("field")).lower()
        value = _clean_text(span.get("value"))
        source_text = _clean_text(span.get("source_text") or span.get("text") or span.get("excerpt"))
        if field not in {*_SCREEN_CONTEXT_FIELDS, "genes", "gene"} or not value or not source_text:
            continue
        if not _value_supported_by_text(value, source_text):
            continue
        valid.append(
            {
                "field": "genes" if field == "gene" else field,
                "value": value,
                "source_text": source_text,
            }
        )
    return valid


def _verified_fields_from_spans(spans: list[dict[str, str]]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    genes: list[str] = []
    for span in spans:
        field = span["field"]
        value = span["value"]
        if field == "genes":
            genes.extend(_normalize_genes([value]))
            continue
        fields.setdefault(field, value)
    if genes:
        fields["genes"] = _normalize_genes(genes)
    return fields


def _merge_verified_fields(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if key == "genes":
            merged[key] = _normalize_genes([*(merged.get("genes") or []), *value])
        else:
            merged.setdefault(key, value)
    return merged


def _record_genes(record: dict[str, Any], *, verified_fields: dict[str, Any]) -> list[str]:
    values = record.get("genes", record.get("gene", []))
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        values = []
    return _normalize_genes([*values, *(verified_fields.get("genes") or [])])


def _context_field_support(query_value: str, verified_value: Any, source_text: str) -> str:
    if not query_value:
        return "not_requested"
    values = verified_value if isinstance(verified_value, list) else [verified_value]
    for value in values:
        if value and _field_matches(str(query_value), str(value)):
            return "verified_exact"
    if _value_supported_by_text(query_value, source_text):
        return "mentioned_unverified"
    return "not_supported"


def _verified_gene_hits(
    candidate_genes: list[str],
    verified_fields: dict[str, Any],
    source_text: str,
    support_spans: list[dict[str, str]],
) -> list[str]:
    verified_genes = {gene.upper() for gene in verified_fields.get("genes", [])}
    span_text = " ".join(span["source_text"] for span in support_spans if span["field"] == "genes")
    output = []
    for gene in candidate_genes:
        if gene in verified_genes:
            output.append(gene)
            continue
        text_to_check = span_text or source_text if support_spans else ""
        if text_to_check and re.search(rf"\b{re.escape(gene)}\b", text_to_check, flags=re.I):
            output.append(gene)
    return sorted(set(output))


def _verification_status(
    verified_fields: dict[str, Any],
    support_spans: list[dict[str, str]],
    direct_support: bool,
) -> str:
    if direct_support:
        return "verified"
    if verified_fields or support_spans:
        return "partially_verified"
    return "unverified"


def _verification_limitations(
    *,
    candidate_genes: list[str],
    verified_gene_hits: list[str],
    direct_context: list[str],
    source_family: str,
    source_url: Any,
) -> list[str]:
    limitations = []
    if not source_url:
        limitations.append("source_url_missing")
    if not verified_gene_hits:
        limitations.append("candidate_gene_not_source_verified")
    elif not set(verified_gene_hits) & set(candidate_genes):
        limitations.append("no_requested_candidate_gene_verified")
    if not direct_context:
        limitations.append("requested_perturbation_context_not_source_verified")
    if source_family != "functional_genomics_perturbation_source":
        limitations.append("source_not_functional_genomics_perturbation_family")
    return limitations


def _screen_source_family(source_type: str, text: str) -> str:
    tokens = set(_tokens(f"{source_type} {text}"))
    if tokens & _SCREEN_SOURCE_TOKENS:
        return "functional_genomics_perturbation_source"
    if tokens & {"literature", "pubmed", "pmid", "doi"} or "pubmed" in text.casefold():
        return "literature_source"
    return "source_record"


def _verified_field_text(verified_fields: dict[str, Any]) -> str:
    chunks = []
    for value in verified_fields.values():
        if isinstance(value, list):
            chunks.extend(str(item) for item in value)
        else:
            chunks.append(str(value))
    return " ".join(chunks)


def _field_matches(query_value: str, verified_value: str) -> bool:
    query = _meaningful_tokens(query_value)
    value = _meaningful_tokens(verified_value)
    if not query or not value:
        return False
    query_set = set(query)
    value_set = set(value)
    return query_set <= value_set or value_set <= query_set or bool(query_set & value_set and _canonical(query_value) == _canonical(verified_value))


def _value_supported_by_text(value: str, source_text: str) -> bool:
    value_tokens = set(_meaningful_tokens(value))
    source_tokens = set(_meaningful_tokens(source_text))
    if not value_tokens:
        return False
    return value_tokens <= source_tokens or _canonical(value) in _canonical(source_text)


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    seen = set()
    for record in records:
        key = (
            record.get("source_url"),
            record.get("source_title"),
            tuple(record.get("genes") or []),
            record.get("finding"),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output


def _acquisition_status(
    records: list[dict[str, Any]],
    direct_ready: list[dict[str, Any]],
    verified: list[dict[str, Any]],
) -> str:
    if direct_ready:
        return "direct_source_records_found"
    if verified:
        return "partial_source_records_found"
    if records:
        return "unverified_source_records_only"
    return "no_source_records"


def _record_limitation(record: dict[str, Any]) -> dict[str, Any]:
    verification = record.get("verification", {})
    return {
        "record_id": record.get("record_id"),
        "source_title": record.get("source_title") or record.get("title"),
        "source_url": record.get("source_url"),
        "genes": record.get("genes") or [],
        "verification_status": verification.get("status"),
        "limitations": verification.get("limitations") or [],
    }


def _source_gaps(
    query: dict[str, Any],
    records: list[dict[str, Any]],
    direct_ready: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if direct_ready:
        return []
    missing = ["source_verified_candidate_gene", "source_verified_perturbation_context"]
    requested = [field for field in _SCREEN_CONTEXT_FIELDS if query.get(field)]
    if not records:
        missing.append("source_records")
    return [
        {
            "component": "perturbation_source_records",
            "state": "missing_direct_source_support",
            "missing_inputs": missing,
            "requested_context_fields": requested,
        }
    ]


def _next_actions(query: dict[str, Any], direct_ready: list[dict[str, Any]]) -> list[str]:
    if direct_ready:
        return ["Call functional_genomics.compare_gene_perturbation with direct_perturbation_source_records or verified_source_records."]
    context = ", ".join(str(query.get(field)) for field in ("cell_line", "perturbation", "assay", "phenotype") if query.get(field))
    if context:
        return [
            "Search primary perturbation experiment papers, supplementary tables, GEO/ArrayExpress/DepMap-style source tables, or stored reviewed research for the requested context: "
            + context,
            "Add support_spans or verified_fields showing where the source names the candidate gene and requested perturbation context.",
        ]
    return [
        "Collect primary perturbation records and include support_spans or verified_fields before ranking candidates.",
    ]


def _normalize_genes(genes: Iterable[Any]) -> list[str]:
    seen = set()
    normalized: list[str] = []
    for gene in genes:
        cleaned = str(gene or "").strip().upper()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _record_digest(record: dict[str, Any]) -> str:
    payload = json.dumps(record, sort_keys=True, default=str)
    return "record-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _tokens(value: str) -> list[str]:
    return _TOKEN_RE.findall(str(value or "").casefold())


def _meaningful_tokens(value: str) -> list[str]:
    return [
        token
        for token in _tokens(value)
        if len(token) > 1 and token not in _LOW_INFORMATION_TOKENS
    ]


def _canonical(value: str) -> str:
    return " ".join(_meaningful_tokens(value))
