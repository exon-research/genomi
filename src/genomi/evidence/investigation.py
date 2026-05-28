from __future__ import annotations

from pathlib import Path
from typing import Any

from ..runtime.external import utc_now
from .sources import evidence_source_catalog
from .store import query_research_findings

INVESTIGATION_PACKET_SCHEMA_VERSION = "genomi-investigation-packet-v1"


def prepare_investigation_packet(
    evidence_db: str | Path,
    target_type: str,
    *,
    gene: str | None = None,
    drug: str | None = None,
    condition: str | None = None,
    topic: str | None = None,
    chrom: str | None = None,
    pos: int | None = None,
    ref: str | None = None,
    alt: str | None = None,
    genome_build: str = "GRCh38",
    source_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Build a target-centric evidence packet for the agent after it has inferred intent."""
    stored_research = query_research_findings(
        evidence_db,
        target_type,
        gene=gene,
        drug=drug,
        condition=condition,
        topic=topic,
        chrom=chrom,
        pos=pos,
        ref=ref,
        alt=alt,
        genome_build=genome_build,
        limit=limit,
    )
    source_catalog = evidence_source_catalog(target_type=target_type, source_id=source_id)
    target = _target_from_query(stored_research["query"])
    available_operations = _available_operations(target, evidence_db=Path(evidence_db))
    return {
        "schema": INVESTIGATION_PACKET_SCHEMA_VERSION,
        "purpose": (
            "Target-centric packet for an agent that has already inferred the user's intent. "
            "The packet exposes stored evidence, relevant public sources, available Genomi operations, "
            "and the JSON shape for recording external findings."
        ),
        "target": target,
        "stored_research": stored_research,
        "source_catalog": source_catalog,
        "available_operations": available_operations,
        "record_research_template": _record_research_template(target),
        "evidence_options": _evidence_options(stored_research, source_catalog),
    }


def _target_from_query(query: dict[str, Any]) -> dict[str, Any]:
    keys = ["target_type", "target_id", "gene", "drug", "condition", "topic", "chrom", "pos", "ref", "alt", "genome_build"]
    return {key: query.get(key) for key in keys if query.get(key) is not None}


def _available_operations(target: dict[str, Any], *, evidence_db: Path) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = [
        {
            "name": "query stored reviewed research",
            "tool": "research.query",
            "params": _query_research_params(target, evidence_db=evidence_db),
            "relevance": "stored reviewed evidence for this target",
        },
        {
            "name": "list relevant evidence sources",
            "tool": "research.list_sources",
            "params": {"target_type": str(target["target_type"])},
            "relevance": "public source catalog for this target type",
        },
        {
            "name": "search stored reviewed research",
            "tool": "research.search",
            "params": {"db": str(evidence_db), "query": _target_search_text(target)},
            "relevance": "nearby stored reviewed evidence",
        },
        {
            "name": "store focused web/database finding",
            "tool": "research.record",
            "params": {"db": str(evidence_db), "input": "finding.json", "scope": "shared"},
            "relevance": "write-back for reviewed source findings",
        },
    ]
    target_type = target["target_type"]
    if target_type == "variant":
        allele_args = [str(target["chrom"]), str(target["pos"]), str(target["ref"]), str(target["alt"])]
        actions.insert(
            0,
            {
                "name": "gather exact variant evidence",
                "tool": "variant.gather_allele_context",
                "params": {"db": str(evidence_db), "chrom": allele_args[0], "pos": int(allele_args[1]), "ref": allele_args[2], "alt": allele_args[3]},
                "relevance": "exact variant evidence packet",
            },
        )
        actions.append(
            {
                "name": "fetch missing gnomAD population evidence",
                "tool": "gnomad.fetch_population_frequency",
                "params": {"db": str(evidence_db), "chrom": allele_args[0], "pos": int(allele_args[1]), "ref": allele_args[2], "alt": allele_args[3]},
                "relevance": "public population frequency lookup",
            }
        )
    elif target_type == "gene":
        actions.insert(
            0,
            {
                "name": "gather gene evidence",
                "tool": "variant.gather_gene_context",
                "params": {"db": str(evidence_db), "gene": str(target["gene"])},
                "relevance": "gene-level ClinVar, sample-match, and stored source evidence",
            },
        )
    return actions


def _query_research_params(target: dict[str, Any], *, evidence_db: Path) -> dict[str, Any]:
    params: dict[str, Any] = {"db": str(evidence_db), "target_type": str(target["target_type"])}
    for key in ("gene", "drug", "condition", "topic", "chrom", "pos", "ref", "alt", "genome_build"):
        value = target.get(key)
        if value is not None:
            params[key] = value
    return params


def _target_search_text(target: dict[str, Any]) -> str:
    for key in ("gene", "drug", "condition", "topic"):
        if target.get(key):
            return str(target[key])
    if target["target_type"] == "variant":
        return " ".join(str(target[key]) for key in ("chrom", "pos", "ref", "alt") if target.get(key) is not None)
    return str(target.get("target_id") or target["target_type"])


def _record_research_template(target: dict[str, Any]) -> dict[str, Any]:
    target_payload = {
        key: target[key]
        for key in ("gene", "drug", "condition", "topic", "chrom", "pos", "ref", "alt", "genome_build")
        if key in target
    }
    target_payload["type"] = target["target_type"]
    return {
        "target": target_payload,
        "source": {
            "title": "",
            "url": "",
            "type": "",
            "published_at": "",
            "accessed_at": utc_now(),
        },
        "searched_query": "",
        "finding": {
            "text": "",
            "summary": "",
            "type": "",
        },
        "captured_by": "agent",
    }


def _evidence_options(stored_research: dict[str, Any], source_catalog: dict[str, Any]) -> list[str]:
    options: list[dict[str, Any]] = [
        {
            "component": "source_scope_selection",
            "state": "available",
            "inputs": ["target", "source_catalog"],
        }
    ]
    if int(stored_research.get("count") or 0) == 0:
        options.append({"component": "stored_research", "state": "absent", "available_operation": "research.record"})
    else:
        options.append({"component": "stored_research", "state": "present", "available_operation": "research.query"})
    if int((source_catalog.get("summary") or {}).get("source_count") or 0) == 0:
        options.append({"component": "source_catalog", "state": "no_mapped_sources", "available_operation": "research.record"})
    return options
