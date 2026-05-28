from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ...research import intent_research
from ._common import JsonObject, _compact_selected_fields, _dedupe, _normalize_gene


def _stored_research_context(
    *,
    db: str | Path | None,
    shared_db: str | Path | None,
    drug: str | None,
    gene: str | None,
    genes: list[str] | None,
    rsid: str | None,
    genome_build: str,
    include_stored_research: bool,
    limit: int,
) -> JsonObject:
    if not include_stored_research:
        return {"status": "disabled", "query_count": 0, "record_count": 0, "records": []}
    targets = _stored_research_targets(drug=drug, gene=gene, genes=genes, rsid=rsid, genome_build=genome_build)
    stores = _stored_research_stores(db=db, shared_db=shared_db)
    if not stores:
        return {
            "status": "no_evidence_store_selected",
            "query_count": len(targets),
            "record_count": 0,
            "records": [],
            "traceability": {"stores": []},
        }
    records: list[JsonObject] = []
    queries: list[JsonObject] = []
    warnings: list[JsonObject] = []
    per_query_limit = max(1, min(limit, 10))
    for store in stores:
        for target in targets:
            query = {"store": store["scope"], **target}
            try:
                result = intent_research.query_reviewed_research(
                    store["path"],
                    target["target_type"],
                    drug=target.get("drug"),
                    gene=target.get("gene"),
                    topic=target.get("topic"),
                    genome_build=target.get("genome_build") or genome_build,
                    limit=per_query_limit,
                )
            except (OSError, ValueError, sqlite3.Error) as exc:
                warnings.append({"store": store["scope"], "target": target, "message": str(exc)})
                continue
            queries.append({**query, "count": int(result.get("count") or 0)})
            for record in result.get("records") or []:
                compact = _compact_stored_research_record(record, store=store["scope"])
                if compact:
                    records.append(compact)
    records = _dedupe_stored_research(records)[: max(1, min(limit, 25))]
    return {
        "status": "completed" if records else "no_stored_pgx_research",
        "query_count": len(queries),
        "record_count": len(records),
        "queries": queries,
        "records": records,
        "warnings": warnings,
        "traceability": {
            "stores": [store["scope"] for store in stores],
            "targets": targets,
        },
    }


def _stored_research_stores(*, db: str | Path | None, shared_db: str | Path | None) -> list[JsonObject]:
    stores = []
    seen: set[str] = set()
    for scope, path in (("private", db), ("shared", shared_db)):
        if not path:
            continue
        expanded = Path(path).expanduser()
        if not expanded.is_file():
            continue
        key = str(expanded.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        stores.append({"scope": scope, "path": expanded})
    return stores


def _stored_research_targets(*, drug: str | None, gene: str | None, genes: list[str] | None, rsid: str | None, genome_build: str) -> list[JsonObject]:
    targets: list[JsonObject] = []
    if drug:
        targets.append({"target_type": "drug", "drug": drug, "genome_build": genome_build})
    normalized_genes = _dedupe([item for item in [_normalize_gene(gene), *[_normalize_gene(item) for item in genes or []]] if item])
    for target_gene in normalized_genes:
        targets.append({"target_type": "gene", "gene": target_gene, "genome_build": genome_build})
    topic_parts = [value for value in (drug, gene, rsid, "pharmacogenomic") if value]
    if len(topic_parts) > 1:
        targets.append({"target_type": "topic", "topic": " ".join(topic_parts), "genome_build": genome_build})
    return targets


def _compact_stored_research_record(record: JsonObject, *, store: str) -> JsonObject:
    finding = record.get("finding") if isinstance(record.get("finding"), dict) else {}
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    target = record.get("target") if isinstance(record.get("target"), dict) else {}
    text = finding.get("text") or finding.get("summary")
    if not text:
        return {}
    return {
        "store": store,
        "target": _compact_selected_fields(target, ("type", "drug", "gene", "topic", "genome_build")),
        "source": _compact_selected_fields(
            source,
            ("title", "url", "type", "accessed_at", "published_at", "artifact", "artifact_metadata"),
        ),
        "finding": _compact_selected_fields(finding, ("type", "text", "summary")),
        "captured_by": record.get("captured_by"),
        "captured_at": record.get("captured_at"),
    }


def _dedupe_stored_research(records: list[JsonObject]) -> list[JsonObject]:
    seen = set()
    deduped = []
    for record in records:
        key = json.dumps(
            {
                "store": record.get("store"),
                "target": record.get("target"),
                "source": record.get("source"),
                "finding": record.get("finding"),
            },
            sort_keys=True,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped
