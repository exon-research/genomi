from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ...evidence import envelope as _env
from ...runtime.external import utc_now
from ...runtime.libraries import registry as library_registry

PGXDB_API_URL = library_registry.get("pgxdb").source.api_base or ""
PGXDB_TIMEOUT_SECONDS = 20
PGXDB_MAX_LIMIT = 50
PGXDB_MAX_RAW_LIST_ITEMS = 10
PGXDB_MAX_RAW_TEXT_CHARS = 500
PGXDB_MAX_TEXT_CHARS = 1000


def lookup_pgxdb(
    *,
    drug: str | None = None,
    atc_code: str | None = None,
    drugbank_id: str | None = None,
    rsid: str | None = None,
    variant_marker: str | None = None,
    gene: str | None = None,
    include_raw_records: bool = False,
    limit: int = 25,
    api_url: str | None = None,
) -> dict[str, Any]:
    """Fetch targeted PGxDB evidence for a selected public drug/gene/variant target."""

    base_url = _base_url(api_url)
    limit = _bounded_limit(limit)
    target = {
        "drug": _clean(drug),
        "atc_code": _clean(atc_code),
        "drugbank_id": _clean(drugbank_id),
        "rsid": _normalize_rsid(rsid),
        "variant_marker": _clean(variant_marker),
        "gene": _normalize_gene(gene),
    }
    raw_calls: list[dict[str, Any]] = []
    if not any(target.values()):
        return _empty_result(
            base_url,
            target,
            status="invalid_target",
            raw_calls=raw_calls,
            missing_inputs=["drug", "atc_code", "drugbank_id", "rsid", "variant_marker", "gene"],
        )

    resolved_atc = _resolve_atc_codes(
        base_url,
        drug=target["drug"],
        atc_code=target["atc_code"],
        drugbank_id=target["drugbank_id"],
        raw_calls=raw_calls,
        limit=limit,
    )
    pgx_records = _fetch_atc_pgx_records(
        base_url,
        resolved_atc=resolved_atc,
        rsid=target["rsid"],
        drug=target["drug"],
        limit=limit,
        raw_calls=raw_calls,
        include_raw_records=include_raw_records,
    )
    pgx_records = _dedupe_pgx_records(pgx_records)

    gene_drug_records = []
    if target["gene"]:
        gene_drug_records = _fetch_gene_drug_records(
            base_url,
            target["gene"],
            raw_calls=raw_calls,
            limit=limit,
            optional=bool(pgx_records or resolved_atc or target["drugbank_id"] or target["drug"]),
        )
    selected_drugbank_ids = _selected_drugbank_ids(target=target, pgx_records=pgx_records)
    gene_drug_records = _annotate_gene_drug_scope(gene_drug_records, selected_drugbank_ids=selected_drugbank_ids)
    medication_scoped_gene_drug_records = [
        record for record in gene_drug_records if record.get("target_scope") == "selected_medication"
    ]

    variant_records = []
    if target["variant_marker"]:
        variant_records = _fetch_variant_context(base_url, target["variant_marker"], raw_calls=raw_calls, limit=limit)

    record_payloads = _record_research_payloads(
        pgx_records,
        medication_scoped_gene_drug_records=medication_scoped_gene_drug_records,
        variant_records=variant_records,
        target=target,
        source_url=base_url,
    )
    status = "completed"
    if not pgx_records and not gene_drug_records and not variant_records:
        status = "source_unavailable" if _raw_call_errors(raw_calls) else "no_matching_pgxdb_records"

    result = {
        "ok": status in {"completed", "no_matching_pgxdb_records"},
        "status": status,
        "source": _source_metadata(base_url),
        "query": target,
        "resolved_atc_codes": resolved_atc,
        "pgx_records": pgx_records,
        "gene_drug_records": gene_drug_records,
        "medication_scoped_gene_drug_records": medication_scoped_gene_drug_records,
        "variant_context_records": variant_records,
        "record_research_payloads": record_payloads,
        "summary": {
            "pgx_record_count": len(pgx_records),
            "gene_drug_record_count": len(gene_drug_records),
            "medication_scoped_gene_drug_record_count": len(medication_scoped_gene_drug_records),
            "variant_context_record_count": len(variant_records),
            "record_research_payload_count": len(record_payloads),
        },
        "raw_calls": raw_calls,
    }
    raw_errors = _raw_call_errors(raw_calls)
    if raw_errors:
        result["warnings"] = raw_errors
    return _attach_evidence_envelope(result)


def _empty_result(
    base_url: str,
    target: dict[str, Any],
    *,
    status: str,
    raw_calls: list[dict[str, Any]],
    missing_inputs: list[str],
) -> dict[str, Any]:
    result = {
        "ok": False,
        "status": status,
        "source": _source_metadata(base_url),
        "query": target,
        "resolved_atc_codes": [],
        "pgx_records": [],
        "gene_drug_records": [],
        "medication_scoped_gene_drug_records": [],
        "variant_context_records": [],
        "record_research_payloads": [],
        "summary": {
            "pgx_record_count": 0,
            "gene_drug_record_count": 0,
            "medication_scoped_gene_drug_record_count": 0,
            "variant_context_record_count": 0,
            "record_research_payload_count": 0,
        },
        "raw_calls": raw_calls,
        "unanswered_answer_components": [
            {
                "component": "public_pgxdb_target",
                "state": "missing",
                "missing_inputs": missing_inputs,
            }
        ],
    }
    return _attach_evidence_envelope(result)


def _attach_evidence_envelope(result: dict[str, Any]) -> dict[str, Any]:
    result["evidence_envelope"] = _pgxdb_evidence_envelope(result)
    return result


def _pgxdb_evidence_envelope(result: dict[str, Any]) -> dict[str, Any]:
    operation = "pharmacogenomics.fetch_pgxdb"
    target = dict(result.get("query") or {})
    summary = dict(result.get("summary") or {})
    raw_calls = result.get("raw_calls") or []
    status = str(result.get("status") or "")
    observations = {
        "status": status,
        "pgx_record_count": summary.get("pgx_record_count", 0),
        "gene_drug_record_count": summary.get("gene_drug_record_count", 0),
        "medication_scoped_gene_drug_record_count": summary.get("medication_scoped_gene_drug_record_count", 0),
        "variant_context_record_count": summary.get("variant_context_record_count", 0),
    }
    coverage = {
        "libraries": [{"library": "pgxdb", "state": "failed" if status == "source_unavailable" else "installed"}],
        "consulted_sources": ["pgxdb"] if raw_calls and status != "source_unavailable" else [],
        "unavailable_sources": ["pgxdb"] if status == "source_unavailable" else [],
        "materialization": [],
    }
    if status == "invalid_target":
        return _env.not_assessed(
            operation=operation,
            reason="Missing PGxDB public target.",
            query_scope=target,
            coverage=coverage,
            observations=observations,
            next_actions=[
                {
                    "action": "provide_public_pgxdb_target",
                    "missing_inputs": ["drug", "atc_code", "drugbank_id", "rsid", "variant_marker", "gene"],
                }
            ],
            guidance=["target_missing:provide_drug_gene_or_variant"],
        )
    if status == "source_unavailable":
        return _env.not_assessed(
            operation=operation,
            reason="PGxDB source lookup was unavailable.",
            query_scope=target,
            coverage=coverage,
            observations=observations,
            next_actions=[
                {
                    "action": "use_alternate_pgx_source_or_retry",
                    "operations": [
                        "pharmacogenomics.fetch_clinpgx",
                        "pharmacogenomics.fetch_fda_labels",
                    ],
                }
            ],
            guidance=["source_unavailable:retry_or_use_other_pgx_sources"],
        )
    if target.get("rsid") and not result.get("resolved_atc_codes") and not target.get("drugbank_id") and not target.get("drug") and not target.get("atc_code"):
        return _env.not_assessed(
            operation=operation,
            reason="PGxDB association lookup needs medication scope for rsID-only input.",
            query_scope=target,
            coverage=coverage,
            observations=observations,
            next_actions=[
                {
                    "action": "provide_medication_context",
                    "missing_inputs": ["drug", "drugbank_id", "atc_code"],
                    "reason_code": "pgxdb_association_requires_medication_scope",
                }
            ],
            guidance=[
                "scope_missing:pgxdb_requires_medication_context",
                "negative_inference_disallowed:do_not_treat_as_no_pgx_evidence",
            ],
        )
    if status == "no_matching_pgxdb_records":
        return _env.empty_consulted_scope(
            operation=operation,
            query_scope=target,
            coverage=coverage,
            observations=observations,
            next_actions=[
                {
                    "action": "try_alternate_pgx_source",
                    "operations": [
                        "pharmacogenomics.fetch_clinpgx",
                        "pharmacogenomics.fetch_fda_labels",
                    ],
                }
            ],
            guidance=[
                "not_observed_in_consulted_scope:pgxdb_no_records_for_target",
                "negative_inference_disallowed:check_other_pgx_sources",
            ],
        )
    return _env.evidence_present(
        operation=operation,
        query_scope=target,
        coverage=coverage,
        observations=observations,
        answer_readiness=_env.SCOPED_ANSWER_ONLY,
        next_actions=[
            {
                "action": "check_sample_support_before_personal_statement",
                "operation": "variant.resolve",
                "target_fields": ["rsid", "variant_marker", "gene"],
            }
        ],
        guidance=[
            "pgxdb_evidence_present:public_pgx_context_only",
            "sample_context:check_genotype_separately",
        ],
    )


def _source_metadata(base_url: str) -> dict[str, Any]:
    return {
        "source_id": "pgxdb",
        "title": "PGxDB",
        "api_url": base_url,
        "swagger_url": "https://pgx-db.org/swagger/",
        "accessed_at": utc_now(),
    }


def _resolve_atc_codes(
    base_url: str,
    *,
    drug: str | None,
    atc_code: str | None,
    drugbank_id: str | None,
    raw_calls: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    if atc_code:
        description = _fetch_atc_description(base_url, atc_code, raw_calls=raw_calls)
        return [{"atc_code": atc_code.upper(), "description": description, "resolution": "input_atc"}]
    if drugbank_id:
        payload = _fetch_json(base_url, f"/drug/atc_code/{drugbank_id}/", raw_calls=raw_calls)
        return [
            {
                "atc_code": _first_present(row, "Atc code", "ATC code", "atc_code"),
                "description": _first_present(row, "Description", "description"),
                "resolution": "drugbank_id",
                "drugbank_id": drugbank_id,
            }
            for row in _first_list(payload)
            if _first_present(row, "Atc code", "ATC code", "atc_code")
        ][:limit]
    if drug:
        payload = _fetch_json(base_url, "/atc/atc_code/CS/", raw_calls=raw_calls)
        normalized = _norm_text(drug)
        matches = []
        for row in _first_list(payload):
            description = str(_first_present(row, "Description", "description") or "")
            if _norm_text(description) == normalized:
                matches.insert(
                    0,
                    {
                        "atc_code": _first_present(row, "ATC code", "Atc code", "atc_code"),
                        "description": description,
                        "resolution": "drug_exact_name",
                    },
                )
            elif normalized in _norm_text(description):
                matches.append(
                    {
                        "atc_code": _first_present(row, "ATC code", "Atc code", "atc_code"),
                        "description": description,
                        "resolution": "drug_name_contains",
                    }
                )
        return [match for match in matches if match.get("atc_code")][:limit]
    return []


def _fetch_atc_description(base_url: str, atc_code: str, *, raw_calls: list[dict[str, Any]]) -> str | None:
    payload = _fetch_json(base_url, f"/atc/description/{atc_code}/", raw_calls=raw_calls)
    if isinstance(payload, dict):
        rows = _first_list(payload)
        if rows:
            return _first_present(rows[0], "Description", "description")
        for value in payload.values():
            if isinstance(value, str):
                return value
    return None


def _fetch_atc_pgx_records(
    base_url: str,
    *,
    resolved_atc: list[dict[str, Any]],
    rsid: str | None,
    drug: str | None,
    limit: int,
    raw_calls: list[dict[str, Any]],
    include_raw_records: bool,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for atc in resolved_atc:
        code = str(atc.get("atc_code") or "")
        if not code:
            continue
        payload = _fetch_json(base_url, f"/atc/pgx/{code}/", raw_calls=raw_calls)
        for row in _first_list(payload):
            if rsid and _normalize_rsid(str(_first_present(row, "Variant_or_Haplotypes") or "")) != rsid:
                continue
            if drug and drug.casefold() not in str(_first_present(row, "Drugname", "Drug name") or "").casefold():
                continue
            records.append(_normalize_pgx_row(row, atc, include_raw_records=include_raw_records))
            if len(records) >= limit:
                return records
    return records


def _fetch_gene_drug_records(
    base_url: str,
    gene: str,
    *,
    raw_calls: list[dict[str, Any]],
    limit: int,
    optional: bool = False,
) -> list[dict[str, Any]]:
    call_start = len(raw_calls)
    payload = _fetch_json(base_url, "/gene/drug/", query={"genename": gene.casefold()}, raw_calls=raw_calls)
    if optional:
        for call in raw_calls[call_start:]:
            if call.get("error"):
                call["optional"] = True
                call["endpoint_role"] = "pgxdb_gene_drug_context"
    records = []
    for row in _first_list(payload):
        normalized = {
            "gene": gene,
            "drugbank_id": _first_present(row, "drug_bankID", "DrugBank identifier", "DrugbankID"),
            "actions": _first_present(row, "actions", "Actions"),
            "known_action": _first_present(row, "known_action", "Known action"),
            "interaction_type": _first_present(row, "interaction_type", "Interaction type"),
            "raw": _compact_raw(row),
        }
        records.append(normalized)
        if len(records) >= limit:
            break
    return records


def _fetch_variant_context(
    base_url: str,
    variant_marker: str,
    *,
    raw_calls: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    records = []
    for endpoint, field in [
        (f"/gene/associateStatictics/{variant_marker}", "association_statistics"),
        (f"/variant/VEPscore/{variant_marker}", "vep_scores"),
    ]:
        payload = _fetch_json(base_url, endpoint, raw_calls=raw_calls)
        rows = _first_list(payload)
        if rows:
            records.append(
                {
                    "type": field,
                    "variant_marker": variant_marker,
                    "records": [_compact_raw(row) for row in rows[:limit]],
                }
            )
        elif isinstance(payload, dict) and payload.get("Results"):
            records.append({"type": field, "variant_marker": variant_marker, "message": payload.get("Results")})
    return records


def _selected_drugbank_ids(*, target: dict[str, Any], pgx_records: list[dict[str, Any]]) -> set[str]:
    selected = set()
    if target.get("drugbank_id"):
        selected.add(_normalize_drugbank_id(target["drugbank_id"]))
    for record in pgx_records:
        drugbank_id = _normalize_drugbank_id(record.get("drugbank_id"))
        if drugbank_id:
            selected.add(drugbank_id)
    return {item for item in selected if item}


def _annotate_gene_drug_scope(records: list[dict[str, Any]], *, selected_drugbank_ids: set[str]) -> list[dict[str, Any]]:
    annotated = []
    for record in records:
        copy = dict(record)
        drugbank_id = _normalize_drugbank_id(copy.get("drugbank_id"))
        if selected_drugbank_ids and drugbank_id in selected_drugbank_ids:
            copy["target_scope"] = "selected_medication"
        elif selected_drugbank_ids:
            copy["target_scope"] = "other_drug_for_gene"
        else:
            copy["target_scope"] = "gene_only"
        annotated.append(copy)
    return annotated


def _normalize_pgx_row(row: dict[str, Any], atc: dict[str, Any], *, include_raw_records: bool) -> dict[str, Any]:
    variant = _first_present(row, "Variant_or_Haplotypes", "variant_or_haplotypes")
    drug = _first_present(row, "Drugname", "Drug name", "drug_name")
    record = {
        "source_id": "pgxdb",
        "atc_code": atc.get("atc_code"),
        "atc_description": atc.get("description"),
        "drugbank_id": _first_present(row, "DrugbankID", "DrugBank identifier", "drug_bankID"),
        "drug": drug,
        "variant_or_haplotype": variant,
        "rsid": _normalize_rsid(str(variant or "")) if str(variant or "").lower().startswith("rs") else None,
        "phenotype_category": _first_present(row, "Phenotype_Category"),
        "significance": _first_present(row, "Significance"),
        "direction_of_effect": _first_present(row, "Direction_of_effect"),
        "pd_pk_terms": _first_present(row, "PD_PK_terms"),
        "alleles": _first_present(row, "Alleles"),
        "p_value": _first_present(row, "P_Value"),
        "biogeographical_groups": _first_present(row, "Biogeographical_Groups"),
        "study_type": _first_present(row, "Study_Type"),
        "pmid": _first_present(row, "PMID"),
        "sentence": _bounded_text(_first_present(row, "Sentence"), PGXDB_MAX_TEXT_CHARS),
        "notes": _bounded_text(_first_present(row, "Notes"), PGXDB_MAX_TEXT_CHARS),
    }
    if include_raw_records:
        record["raw"] = _compact_raw(row)
    return record


def _dedupe_pgx_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for record in records:
        key = (
            str(record.get("rsid") or record.get("variant_or_haplotype") or ""),
            str(record.get("drug") or ""),
            str(record.get("alleles") or ""),
            str(record.get("direction_of_effect") or ""),
            str(record.get("sentence") or record.get("notes") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _record_research_payloads(
    records: list[dict[str, Any]],
    *,
    medication_scoped_gene_drug_records: list[dict[str, Any]] | None = None,
    variant_records: list[dict[str, Any]] | None = None,
    target: dict[str, Any],
    source_url: str,
) -> list[dict[str, Any]]:
    payloads = []
    accessed_at = utc_now()
    for record in records:
        topic = " ".join(
            item
            for item in [
                record.get("rsid") or target.get("rsid") or record.get("variant_or_haplotype"),
                record.get("drug") or target.get("drug"),
                _topic_effect_term(record.get("pd_pk_terms")) or "pharmacogenomic response",
            ]
            if item
        )
        text = str(record.get("sentence") or record.get("notes") or "").strip()
        if not text:
            continue
        payloads.append(
            {
                "target": {"type": "topic", "topic": topic},
                "source": {
                    "source_id": "pgxdb",
                    "title": "PGxDB PharmGKB pharmacogenomics data",
                    "url": _record_url(source_url, record),
                    "type": "pharmacogenomic_database",
                    "api_url": source_url,
                    "swagger_url": "https://pgx-db.org/swagger/",
                    "pmid": record.get("pmid"),
                    "accessed_at": accessed_at,
                },
                "finding": {
                    "type": "pgxdb_pharmacogenomic_association",
                    "text": text,
                    "summary": _summary_from_record(record),
                },
                "searched_query": json.dumps(target, sort_keys=True),
                "captured_by": "genomi call pharmacogenomics.fetch_pgxdb",
            }
        )
    payloads.extend(
        _gene_drug_record_payloads(
            medication_scoped_gene_drug_records or [],
            target=target,
            source_url=source_url,
            accessed_at=accessed_at,
        )
    )
    payloads.extend(
        _variant_context_record_payloads(
            variant_records or [],
            target=target,
            source_url=source_url,
            accessed_at=accessed_at,
        )
    )
    return payloads


def _gene_drug_record_payloads(
    records: list[dict[str, Any]],
    *,
    target: dict[str, Any],
    source_url: str,
    accessed_at: str,
) -> list[dict[str, Any]]:
    payloads = []
    for record in records:
        gene = record.get("gene") or target.get("gene")
        drug = target.get("drug")
        drugbank_id = record.get("drugbank_id") or target.get("drugbank_id")
        topic = " ".join(str(item) for item in (drug or drugbank_id, gene, "PGxDB gene-drug context") if item)
        text = _gene_drug_text(record)
        payloads.append(
            {
                "target": {"type": "drug", "drug": drug, "topic": topic} if drug else {"type": "topic", "topic": topic},
                "source": {
                    "source_id": "pgxdb",
                    "title": "PGxDB gene-drug context",
                    "url": f"{source_url.rstrip('/')}/gene/drug/",
                    "type": "pgxdb_gene_drug_context",
                    "api_url": source_url,
                    "swagger_url": "https://pgx-db.org/swagger/",
                    "accessed_at": accessed_at,
                },
                "finding": {
                    "type": "pgxdb_gene_drug_context",
                    "text": text,
                    "summary": _gene_drug_summary(record),
                },
                "searched_query": json.dumps(target, sort_keys=True),
                "captured_by": "genomi call pharmacogenomics.fetch_pgxdb",
            }
        )
    return payloads


def _variant_context_record_payloads(
    records: list[dict[str, Any]],
    *,
    target: dict[str, Any],
    source_url: str,
    accessed_at: str,
) -> list[dict[str, Any]]:
    payloads = []
    for record in records:
        variant_marker = record.get("variant_marker") or target.get("variant_marker")
        context_type = str(record.get("type") or "variant_context")
        topic = " ".join(str(item) for item in (variant_marker, "PGxDB", context_type) if item)
        payloads.append(
            {
                "target": {"type": "topic", "topic": topic},
                "source": {
                    "source_id": "pgxdb",
                    "title": "PGxDB variant context",
                    "url": _variant_context_url(source_url, record),
                    "type": "pgxdb_variant_context",
                    "api_url": source_url,
                    "swagger_url": "https://pgx-db.org/swagger/",
                    "accessed_at": accessed_at,
                },
                "finding": {
                    "type": "pgxdb_variant_context",
                    "text": _variant_context_text(record),
                    "summary": _variant_context_summary(record),
                },
                "searched_query": json.dumps(target, sort_keys=True),
                "captured_by": "genomi call pharmacogenomics.fetch_pgxdb",
            }
        )
    return payloads


def _summary_from_record(record: dict[str, Any]) -> str:
    pieces = [
        record.get("variant_or_haplotype"),
        record.get("drug"),
        record.get("direction_of_effect"),
        _topic_effect_term(record.get("pd_pk_terms")),
    ]
    return " ".join(str(piece) for piece in pieces if piece and str(piece).lower() != "nan")


def _gene_drug_text(record: dict[str, Any]) -> str:
    pieces = [
        f"PGxDB lists {record.get('gene')} with DrugBank {record.get('drugbank_id')}",
        f"actions: {record.get('actions')}" if record.get("actions") else None,
        f"known_action: {record.get('known_action')}" if record.get("known_action") else None,
        f"interaction_type: {record.get('interaction_type')}" if record.get("interaction_type") else None,
        f"target_scope: {record.get('target_scope')}" if record.get("target_scope") else None,
    ]
    return _bounded_text("; ".join(str(piece) for piece in pieces if piece), PGXDB_MAX_TEXT_CHARS)


def _gene_drug_summary(record: dict[str, Any]) -> str:
    pieces = [
        record.get("gene"),
        record.get("drugbank_id"),
        record.get("actions"),
        record.get("known_action"),
        record.get("interaction_type"),
    ]
    return " ".join(str(piece) for piece in pieces if piece)


def _variant_context_text(record: dict[str, Any]) -> str:
    if record.get("message"):
        return _bounded_text(
            f"PGxDB {record.get('type')} for {record.get('variant_marker')}: {record.get('message')}",
            PGXDB_MAX_TEXT_CHARS,
        )
    row_count = len(record.get("records") or [])
    return _bounded_text(
        f"PGxDB {record.get('type')} for {record.get('variant_marker')} returned {row_count} structured row(s).",
        PGXDB_MAX_TEXT_CHARS,
    )


def _variant_context_summary(record: dict[str, Any]) -> str:
    return " ".join(str(piece) for piece in (record.get("variant_marker"), record.get("type"), record.get("message")) if piece)


def _record_url(source_url: str, record: dict[str, Any]) -> str:
    atc = record.get("atc_code")
    if atc:
        return f"{source_url.rstrip('/')}/atc/pgx/{atc}/"
    return source_url


def _variant_context_url(source_url: str, record: dict[str, Any]) -> str:
    variant_marker = record.get("variant_marker")
    if record.get("type") == "association_statistics" and variant_marker:
        return f"{source_url.rstrip('/')}/gene/associateStatictics/{variant_marker}"
    if record.get("type") == "vep_scores" and variant_marker:
        return f"{source_url.rstrip('/')}/variant/VEPscore/{variant_marker}"
    return source_url


def _fetch_json(
    base_url: str,
    path: str,
    *,
    query: dict[str, str] | None = None,
    raw_calls: list[dict[str, Any]],
) -> Any:
    url = _url(base_url, path, query=query)
    call: dict[str, Any] = {"url": url, "status": None, "attempts": 0}
    raw_calls.append(call)
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "genomi/0.1"})
    for attempt in range(2):
        call["attempts"] = attempt + 1
        try:
            with urllib.request.urlopen(request, timeout=PGXDB_TIMEOUT_SECONDS) as response:
                call["status"] = int(getattr(response, "status", 0) or 0)
                call["content_type"] = response.headers.get("content-type")
                body = response.read()
            return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            call["status"] = exc.code
            call["error"] = f"HTTP {exc.code}"
            if 400 <= exc.code < 500:
                return None
        except urllib.error.URLError as exc:
            call["error"] = f"URL error: {exc.reason}"
        except TimeoutError as exc:
            call["error"] = f"timeout: {exc}"
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            call["error"] = f"parse error: {exc}"
            return None
        except OSError as exc:
            call["error"] = f"I/O error: {exc}"
        if attempt == 0:
            time.sleep(0.5)
    return None


def _url(base_url: str, path: str, *, query: dict[str, str] | None = None) -> str:
    encoded_path = "/".join(urllib.parse.quote(part, safe="/") for part in path.split("/"))
    url = base_url.rstrip("/") + "/" + encoded_path.lstrip("/")
    if query:
        url += "?" + urllib.parse.urlencode({key: value for key, value in query.items() if value})
    return url


def _base_url(value: str | None) -> str:
    return (value or PGXDB_API_URL).rstrip("/")


def _bounded_limit(value: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return 25
    return max(1, min(limit, PGXDB_MAX_LIMIT))


def _first_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for value in payload.values():
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


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


def _normalize_drugbank_id(value: Any) -> str:
    return str(value or "").strip().upper()


def _norm_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _bounded_text(value: Any, max_chars: int) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "...<truncated>"


def _compact_raw(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _compact_raw(item) for key, item in value.items()}
    if isinstance(value, list):
        compacted = [_compact_raw(item) for item in value[:PGXDB_MAX_RAW_LIST_ITEMS]]
        if len(value) > PGXDB_MAX_RAW_LIST_ITEMS:
            compacted.append({"truncated_items": len(value) - PGXDB_MAX_RAW_LIST_ITEMS})
        return compacted
    if isinstance(value, str):
        return _bounded_text(value, PGXDB_MAX_RAW_TEXT_CHARS)
    return value


def _raw_call_errors(raw_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"url": call.get("url"), "status": call.get("status"), "error": call.get("error")}
        for call in raw_calls
        if call.get("error") and not call.get("optional")
    ]


def _topic_effect_term(value: Any) -> str | None:
    text = _clean(str(value)) if value is not None else None
    if not text:
        return None
    normalized = _norm_text(text)
    if normalized in {"response to", "response"}:
        return "pharmacogenomic response"
    return text
