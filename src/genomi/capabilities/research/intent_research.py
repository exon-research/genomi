from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ...evidence import (
    default_evidence_path,
    fetch_gene_evidence,
    gather_variant_evidence,
    init_evidence_db,
    query_research_findings,
    record_research_findings,
    research_scope_choices,
    research_target_type_choices,
    search_research_findings,
)
from ...evidence.investigation import prepare_investigation_packet
from ...evidence.sources import evidence_source_catalog
from ...runtime.handoff import attach_evidence_context, evidence_context
from ...runtime.paths import (
    enclosing_work_dir,
    run_output_path,
    shared_evidence_db_path,
)
from ..functional_genomics.evidence_acquisition import (
    acquire_perturbation_source_records,
)
from ..functional_genomics.geo import (
    geo_advantage_applies,
    query_geo_datasets,
    source_name_is_geo,
)
from ..functional_genomics.screen import (
    compare_screen_experiment_evidence,
    retrieve_public_screen_records,
)
from ..gwas.gwas import compare_gwas_gene_evidence, compare_gwas_variant_evidence
from ..phenotype.risk import prepare_risk_investigation

WORKFLOW_AREA_ID = "research"
WORKFLOW_AREA_NAME = "LLM-guided research based on user intent"


def workflow_contract() -> dict[str, Any]:
    return {
        "id": WORKFLOW_AREA_ID,
        "name": WORKFLOW_AREA_NAME,
        "purpose": (
            "Start after the relevant Active Genome Index lookup or focused evidence tool has structured the needed "
            "facts. The agent maps the user's natural-language request to a public target, gathers local target "
            "context, reviews current sources only when needed, and records source-backed findings with an "
            "explicit shared/private scope."
        ),
        "target_types": research_target_type_choices(),
        "research_scopes": {
            "shared": "Reusable public-target knowledge such as a gene guideline, variant assertion, or drug guideline.",
            "private": "User-specific interpretation, combination effects, medications, phenotype, family history, or other personal context.",
        },
        "primary_outputs": [
            "target evidence packet",
            "gathered variant/gene context",
            "GWAS phenotype candidate-variant evidence",
            "functional-genomics perturbation candidate gene matrices",
            "stored reviewed research findings",
            "rare disease and cancer risk investigation guidance",
        ],
        "hands_off_to": "host-agent synthesis",
    }


def source_catalog(target_type: str | None = None, source_id: str | None = None) -> dict[str, Any]:
    payload = evidence_source_catalog(target_type=target_type, source_id=source_id)
    payload["workflow_area"] = WORKFLOW_AREA_ID
    payload["evidence_context"] = evidence_context(
        "research",
        reason="Use the source catalog to choose target-specific packets, focused review, and reviewed-source write-back.",
        commands=[
            "genomi call research.build_target_packet --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"gene\",\"gene\":\"<gene>\"}'",
            "genomi call research.record --params '{\"db\":\"<evidence.sqlite>\",\"input\":\"<finding.json>\",\"scope\":\"shared\"}'",
        ],
    )
    return payload


def evidence_packet(
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
    payload = prepare_investigation_packet(
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
        source_id=source_id,
        limit=limit,
    )
    payload["workflow_area"] = WORKFLOW_AREA_ID
    payload["scope_guidance"] = workflow_contract()["research_scopes"]
    payload["evidence_context"] = evidence_context(
        "research",
        reason="The target packet frames local/static/stored context for focused review, write-back, or source gathering when needed.",
        commands=[
            "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
            "genomi call variant.gather_gene_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"gene\":\"<gene>\"}'",
            "genomi call research.record --params '{\"db\":\"<evidence.sqlite>\",\"input\":\"<finding.json>\",\"scope\":\"shared\"}'",
        ],
    )
    return payload


def gather_allele_context(
    evidence_db: str | Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    matches: str | Path | None = None,
    genome_build: str = "GRCh38",
    population_source: str | None = None,
    population: str | None = None,
    clinvar_limit: int = 20,
    population_limit: int = 20,
    sample_limit: int = 20,
) -> dict[str, Any]:
    payload = gather_variant_evidence(
        evidence_db,
        chrom,
        pos,
        ref,
        alt,
        matches_path=matches,
        genome_build=genome_build,
        population_source=population_source,
        population=population,
        clinvar_limit=clinvar_limit,
        population_limit=population_limit,
        sample_limit=sample_limit,
    )
    payload["workflow_area"] = WORKFLOW_AREA_ID
    payload["workflow_boundary"] = (
        "This command gathers already-structured evidence and stored research. If public population "
        "frequency is missing, run gnomad.fetch_population_frequency rather than doing ad hoc web interpretation."
    )
    payload["evidence_context"] = evidence_context(
        "research",
        reason="Variant context is assembled; record any reviewed-source findings before final interpretation.",
        commands=[
            "genomi call research.record --params '{\"db\":\"<evidence.sqlite>\",\"input\":\"<finding.json>\",\"scope\":\"shared\"}'",
        ],
    )
    return payload


def gather_gene_context(
    evidence_db: str | Path,
    gene: str,
    *,
    matches: str | Path | None = None,
    genome_build: str = "GRCh38",
    clinvar_limit: int = 50,
    sample_limit: int = 50,
) -> dict[str, Any]:
    payload = fetch_gene_evidence(
        gene,
        evidence_db,
        matches_path=matches,
        genome_build=genome_build,
        clinvar_limit=clinvar_limit,
        sample_limit=sample_limit,
    )
    payload["workflow_area"] = WORKFLOW_AREA_ID
    payload["evidence_context"] = evidence_context(
        "research",
        reason="Gene context is assembled; record any reviewed-source findings, then reassess claims.",
        commands=[
            "genomi call research.build_target_packet --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"gene\",\"gene\":\"<gene>\"}'",
            "genomi call research.record --params '{\"db\":\"<evidence.sqlite>\",\"input\":\"<finding.json>\",\"scope\":\"shared\"}'",
        ],
    )
    return payload


def compare_gwas_variant_context(
    phenotype: str,
    variants: Iterable[str],
    *,
    association_limit: int = 200,
    api_url: str | None = None,
    semantic_context: object = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"association_limit": association_limit}
    if api_url:
        kwargs["api_url"] = api_url
    if semantic_context is not None:
        kwargs["semantic_context"] = semantic_context
    payload = compare_gwas_variant_evidence(phenotype, variants, **kwargs)
    payload["workflow_area"] = WORKFLOW_AREA_ID
    payload["workflow_boundary"] = (
        "This command queries a public association source for a focused phenotype and candidate rsID list. "
        "Personal sample interpretation uses genotype support from the static stage."
    )
    return payload


def compare_gwas_gene_context(
    phenotype: str,
    genes: Iterable[str],
    *,
    association_limit: int = 200,
    api_url: str | None = None,
    source_records: Iterable[dict[str, Any]] | None = None,
    semantic_context: object = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"association_limit": association_limit}
    if api_url:
        kwargs["api_url"] = api_url
    if source_records is not None:
        kwargs["source_records"] = source_records
    if semantic_context is not None:
        kwargs["semantic_context"] = semantic_context
    payload = compare_gwas_gene_evidence(phenotype, genes, **kwargs)
    payload["workflow_area"] = WORKFLOW_AREA_ID
    payload["workflow_boundary"] = (
        "This command queries or scores public GWAS association records for a focused phenotype and candidate gene list. "
        "It is association evidence, not causal mechanism or personal interpretation."
    )
    return payload


def compare_screen_gene_context(
    *,
    context: str,
    genes: Iterable[str],
    source_records: Iterable[dict[str, Any]] | None = None,
    organism: str | None = None,
    cell_line: str | None = None,
    perturbation: str | None = None,
    assay: str | None = None,
    phenotype: str | None = None,
    semantic_context: object = None,
) -> dict[str, Any]:
    payload = compare_screen_experiment_evidence(
        context=context,
        genes=genes,
        source_records=source_records,
        organism=organism,
        cell_line=cell_line,
        perturbation=perturbation,
        assay=assay,
        phenotype=phenotype,
        semantic_context=semantic_context,
    )
    payload["workflow_area"] = WORKFLOW_AREA_ID
    payload["workflow_boundary"] = (
        "This command ranks candidate genes from supplied source records. The host agent is responsible "
        "for obtaining complete source records through focused source review before relying on the ranking."
    )
    return payload


def find_screen_gene_source_records_context(
    evidence_db: str | Path | None = None,
    *,
    context: str,
    genes: Iterable[str],
    source_records: Iterable[dict[str, Any]] | None = None,
    organism: str | None = None,
    cell_line: str | None = None,
    perturbation: str | None = None,
    assay: str | None = None,
    phenotype: str | None = None,
    search_stored_research: bool = True,
    retrieve_native: bool = True,
    perturbation_sources: Iterable[str] | None = None,
    biogrid_orcs_access_key: str | None = None,
    depmap_gene_effect_url: str | None = None,
    depmap_model_url: str | None = None,
    limit: int = 25,
    semantic_context: object = None,
) -> dict[str, Any]:
    native_retrieval: dict[str, Any] | None = None
    geo_retrieval: dict[str, Any] | None = None
    native_records: list[dict[str, Any]] = []
    geo_records: list[dict[str, Any]] = []
    requested_sources = _normalize_perturbation_sources(perturbation_sources or [])
    source_filter_supplied = bool(requested_sources)
    non_geo_sources = [source for source in requested_sources if not source_name_is_geo(source)]
    geo_requested = any(source_name_is_geo(source) for source in requested_sources)
    if retrieve_native:
        if non_geo_sources or not source_filter_supplied:
            native_retrieval = retrieve_public_screen_records(
                context=context,
                genes=genes,
                organism=organism,
                cell_line=cell_line,
                perturbation=perturbation,
                assay=assay,
                phenotype=phenotype,
                sources=non_geo_sources if source_filter_supplied else None,
                biogrid_orcs_access_key=biogrid_orcs_access_key,
                depmap_gene_effect_url=depmap_gene_effect_url,
                depmap_model_url=depmap_model_url,
                limit=limit,
                semantic_context=semantic_context,
            )
            native_records = [record for record in native_retrieval.get("source_records", []) if isinstance(record, dict)]
    stored_records: list[dict[str, Any]] = []
    if evidence_db is not None and search_stored_research:
        stored_records = _stored_screen_research_records(
            evidence_db,
            context=context,
            genes=genes,
            cell_line=cell_line,
            perturbation=perturbation,
            assay=assay,
            phenotype=phenotype,
            limit=limit,
        )
    payload = acquire_perturbation_source_records(
        context=context,
        genes=genes,
        source_records=[*native_records, *(source_records or [])],
        stored_research_records=stored_records,
        organism=organism,
        cell_line=cell_line,
        perturbation=perturbation,
        assay=assay,
        phenotype=phenotype,
        limit=limit,
    )
    should_query_geo = retrieve_native and not payload.get("direct_perturbation_source_records") and (
        geo_requested or (not source_filter_supplied and geo_advantage_applies(context))
    )
    if should_query_geo:
        geo_retrieval = query_geo_datasets(
            context=context,
            genes=genes,
            organism=organism,
            cell_line=cell_line,
            perturbation=perturbation,
            assay=assay,
            phenotype=phenotype,
            limit=limit,
            semantic_context=semantic_context,
        )
        geo_records = [record for record in geo_retrieval.get("source_records", []) if isinstance(record, dict)]
        if geo_records:
            payload = acquire_perturbation_source_records(
                context=context,
                genes=genes,
                source_records=[*native_records, *geo_records, *(source_records or [])],
                stored_research_records=stored_records,
                organism=organism,
                cell_line=cell_line,
                perturbation=perturbation,
                assay=assay,
                phenotype=phenotype,
                limit=limit,
            )
    payload["workflow_area"] = WORKFLOW_AREA_ID
    payload["workflow_boundary"] = (
        "This command verifies source-record fields for screen-gene ranking. It does not use answer keys "
        "and does not treat unverified agent summaries as direct evidence."
    )
    if native_retrieval is not None:
        payload["native_retrieval"] = native_retrieval
        payload["source_coverage"] = native_retrieval.get("source_coverage")
    if geo_retrieval is not None:
        payload["geo_retrieval"] = geo_retrieval
        payload["source_coverage"] = geo_retrieval.get("source_coverage")
    payload["evidence_context"] = evidence_context(
        "research",
        reason=(
            "Verified source records can be passed to functional_genomics.compare_gene_perturbation; "
            "inspect native retrieval only when source coverage or availability needs review."
        ),
        commands=[
            "genomi call functional_genomics.compare_gene_perturbation --params '{\"context\":\"<perturbation context>\",\"genes\":[\"<GENE>\"]}'",
            "genomi call functional_genomics.retrieve_perturbation_records --params '{\"context\":\"<perturbation context>\",\"genes\":[\"<GENE>\"]}'",
            "genomi call functional_genomics.query_geo --params '{\"context\":\"<GEO/GSE context>\",\"genes\":[\"<GENE>\"]}'",
        ],
    )
    return payload


def answer_screen_gene_context(
    evidence_db: str | Path | None = None,
    *,
    context: str,
    genes: Iterable[str],
    source_records: Iterable[dict[str, Any]] | None = None,
    organism: str | None = None,
    cell_line: str | None = None,
    perturbation: str | None = None,
    assay: str | None = None,
    phenotype: str | None = None,
    search_stored_research: bool = True,
    retrieve_native: bool = True,
    perturbation_sources: Iterable[str] | None = None,
    biogrid_orcs_access_key: str | None = None,
    depmap_gene_effect_url: str | None = None,
    depmap_model_url: str | None = None,
    limit: int = 25,
    semantic_context: object = None,
) -> dict[str, Any]:
    acquisition = find_screen_gene_source_records_context(
        evidence_db,
        context=context,
        genes=genes,
        source_records=source_records,
        organism=organism,
        cell_line=cell_line,
        perturbation=perturbation,
        assay=assay,
        phenotype=phenotype,
        search_stored_research=search_stored_research,
        retrieve_native=retrieve_native,
        perturbation_sources=perturbation_sources,
        biogrid_orcs_access_key=biogrid_orcs_access_key,
        depmap_gene_effect_url=depmap_gene_effect_url,
        depmap_model_url=depmap_model_url,
        limit=limit,
        semantic_context=semantic_context,
    )
    ranking = compare_screen_gene_context(
        context=context,
        genes=genes,
        source_records=acquisition["source_records"],
        organism=organism,
        cell_line=cell_line,
        perturbation=perturbation,
        assay=assay,
        phenotype=phenotype,
        semantic_context=semantic_context,
    )
    ranking["source_acquisition"] = {
        "status": acquisition["status"],
        "summary": acquisition["summary"],
        "source_gaps": acquisition["source_gaps"],
        "next_actions": acquisition["next_actions"],
    }
    if acquisition.get("native_retrieval"):
        ranking["native_retrieval"] = acquisition["native_retrieval"]
        if ranking.get("status") == "no_source_records":
            ranking["coverage_state"] = acquisition["native_retrieval"].get("coverage_state", ranking.get("coverage_state"))
            ranking["source_coverage"] = acquisition["native_retrieval"].get("source_coverage", ranking.get("source_coverage"))
    if acquisition.get("geo_retrieval"):
        ranking["geo_retrieval"] = acquisition["geo_retrieval"]
        ranking["source_coverage"] = acquisition["geo_retrieval"].get("source_coverage", ranking.get("source_coverage"))
        if ranking.get("status") == "no_source_records":
            ranking["coverage_state"] = acquisition["geo_retrieval"].get("coverage_state", ranking.get("coverage_state"))
    ranking["workflow_boundary"] = (
        "This command first verifies source records, then returns candidate evidence. The agent chooses whether "
        "the source evidence supports the requested answer."
    )
    return ranking


def _stored_screen_research_records(
    evidence_db: str | Path,
    *,
    context: str,
    genes: Iterable[str],
    cell_line: str | None,
    perturbation: str | None,
    assay: str | None,
    phenotype: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    remaining = max(limit, 0)
    for query in _screen_research_queries(
        context=context,
        genes=genes,
        cell_line=cell_line,
        perturbation=perturbation,
        assay=assay,
        phenotype=phenotype,
    ):
        if remaining <= 0:
            break
        try:
            payload = search_research_findings(evidence_db, query, target_type="gene", scope="shared", limit=remaining)
        except (OSError, ValueError):
            continue
        for record in payload.get("records") or []:
            if isinstance(record, dict):
                records.append(record)
                remaining -= 1
                if remaining <= 0:
                    break
    return records


def _normalize_perturbation_sources(sources: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for source in sources:
        value = str(source or "").strip().casefold().replace("-", "_")
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _screen_research_queries(
    *,
    context: str,
    genes: Iterable[str],
    cell_line: str | None,
    perturbation: str | None,
    assay: str | None,
    phenotype: str | None,
) -> list[str]:
    context_terms = [
        str(item).strip()
        for item in (cell_line, perturbation, assay, phenotype)
        if str(item or "").strip()
    ]
    output = []
    for gene in genes:
        gene = str(gene or "").strip().upper()
        if not gene:
            continue
        if context_terms:
            output.append(" ".join([gene, *context_terms]))
        output.append(gene)
    if context and context_terms:
        output.append(" ".join(context_terms))
    return output


def risk_investigation_context(
    evidence_db: str | Path,
    *,
    question: str | None = None,
    investigation_type: str = "auto",
    gene: str | None = None,
    genes: Iterable[str] | None = None,
    condition: str | None = None,
    topic: str | None = None,
    matches: str | Path | None = None,
    genome_build: str = "GRCh38",
    limit: int = 25,
    search_stored_research: bool = True,
) -> dict[str, Any]:
    payload = prepare_risk_investigation(
        evidence_db,
        question=question,
        investigation_type=investigation_type,
        gene=gene,
        genes=genes,
        condition=condition,
        topic=topic,
        matches=matches,
        genome_build=genome_build,
        limit=limit,
        search_stored_research=search_stored_research,
    )
    payload["workflow_area"] = WORKFLOW_AREA_ID
    payload["workflow_boundary"] = (
        "This command plans focused rare-disease or cancer-risk evidence review. It does not diagnose, "
        "estimate personal risk, or turn GeneCards-style context into clinical validity by itself."
    )
    payload["evidence_context"] = evidence_context(
        "research",
        reason="Risk investigation guidance is assembled; record reviewed source findings before final interpretation.",
        commands=[
            "genomi call research.list_sources --params '{\"target_type\":\"gene\"}'",
            "genomi call research.record --params '{\"payload\":{...},\"scope\":\"shared\"}'",
            "genomi call variant.gather_gene_context --params '{\"gene\":\"<GENE>\"}'",
        ],
    )
    return payload


def record_reviewed_research(
    evidence_db: str | Path,
    payload: dict[str, Any] | list[dict[str, Any]],
    *,
    scope: str = "shared",
    shared_evidence_db: str | Path | None = None,
    sync_shared: bool = True,
) -> dict[str, Any]:
    scoped_payload = _apply_scope(payload, scope)
    result = record_research_findings(evidence_db, scoped_payload)
    result["workflow_area"] = WORKFLOW_AREA_ID
    result["scope"] = scope
    result["shared_sync"] = _sync_research_to_shared(
        scoped_payload,
        evidence_db=evidence_db,
        shared_evidence_db=shared_evidence_db,
        scope=scope,
        sync_shared=sync_shared,
    )
    return attach_evidence_context(
        result,
        "research",
        reason="Reviewed research is persisted; query stored findings so downstream output consumes stored evidence.",
        commands=[
            "genomi call research.query --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"gene\",\"gene\":\"<gene>\"}'",
        ],
    )


def record_reviewed_research_file(
    evidence_db: str | Path,
    input_path: str | Path,
    *,
    scope: str = "shared",
    shared_evidence_db: str | Path | None = None,
    sync_shared: bool = True,
) -> dict[str, Any]:
    return record_reviewed_research(
        evidence_db,
        json.loads(Path(input_path).read_text(encoding="utf-8")),
        scope=scope,
        shared_evidence_db=shared_evidence_db,
        sync_shared=sync_shared,
    )


def query_reviewed_research(
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
    scope: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    payload = query_research_findings(
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
        scope=scope,
        limit=limit,
    )
    payload["workflow_area"] = WORKFLOW_AREA_ID
    payload["evidence_context"] = evidence_context(
        "research",
        reason="Stored reviewed findings are retrieved; use them to close research gaps before final interpretation.",
        commands=[
            "genomi call research.record --params '{\"db\":\"<evidence.sqlite>\",\"input\":\"<finding.json>\",\"scope\":\"shared\"}'",
        ],
    )
    return payload


def search_reviewed_research(
    evidence_db: str | Path,
    query: str,
    *,
    target_type: str | None = None,
    scope: str | None = None,
    limit: int = 50,
    semantic_context: object = None,
) -> dict[str, Any]:
    payload = search_research_findings(
        evidence_db,
        query,
        target_type=target_type,
        scope=scope,
        limit=limit,
        semantic_context=semantic_context,
    )
    payload["workflow_area"] = WORKFLOW_AREA_ID
    payload["evidence_context"] = evidence_context(
        "research",
        reason="Stored reviewed findings are retrieved for the agent's inspection; use them to close gaps or record more precise findings.",
        commands=[
            "genomi call research.record --params '{\"db\":\"<evidence.sqlite>\",\"input\":\"<finding.json>\",\"scope\":\"shared\"}'",
        ],
    )
    return payload


def default_evidence_db_for_vcf(vcf: str | Path) -> Path:
    return default_evidence_path(vcf)


def _default_output(anchor: str | Path, filename: str) -> Path:
    anchor_path = Path(anchor)
    if enclosing_work_dir(anchor_path) is not None:
        return run_output_path(anchor_path, filename)
    return anchor_path.parent / filename


def _sync_research_to_shared(
    payload: dict[str, Any] | list[dict[str, Any]],
    *,
    evidence_db: str | Path,
    shared_evidence_db: str | Path | None,
    scope: str,
    sync_shared: bool,
) -> dict[str, Any]:
    shared_db = Path(shared_evidence_db) if shared_evidence_db is not None else shared_evidence_db_path()
    if not sync_shared:
        return {
            "status": "disabled",
            "shared_evidence_db": str(shared_db),
            "evidence_context": evidence_context(
                "research",
                reason="Shared sync is disabled; continue in private/user research context.",
                commands=["genomi call research.query --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"gene\",\"gene\":\"<gene>\"}'"],
            ),
        }
    if scope != "shared":
        return {
            "status": "private_not_synced",
            "shared_evidence_db": str(shared_db),
            "evidence_context": evidence_context(
                "research",
                reason="Private research was stored only in the user/run DB; continue with research context.",
                commands=["genomi call research.query --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"gene\",\"gene\":\"<gene>\"}'"],
            ),
        }
    if Path(evidence_db).resolve() == shared_db.resolve():
        return {
            "status": "same_db",
            "shared_evidence_db": str(shared_db),
            "evidence_context": evidence_context(
                "research",
                reason="The active DB is already the shared evidence DB; continue with research context.",
                commands=["genomi call research.query --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"gene\",\"gene\":\"<gene>\"}'"],
            ),
        }
    init_evidence_db(shared_db)
    synced = record_research_findings(shared_db, payload)
    return {
        "status": "completed",
        "shared_evidence_db": str(shared_db),
        "inserted_findings": synced["inserted_findings"],
        "updated_findings": synced["updated_findings"],
        "evidence_context": evidence_context(
            "research",
            reason="Reusable reviewed findings are synced to shared evidence; continue with research context.",
            commands=["genomi call research.query --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"gene\",\"gene\":\"<gene>\"}'"],
        ),
    }


def _apply_scope(payload: dict[str, Any] | list[dict[str, Any]], scope: str) -> dict[str, Any] | list[dict[str, Any]]:
    if scope not in research_scope_choices():
        raise ValueError("scope must be 'shared' or 'private'")
    if isinstance(payload, list):
        return [_apply_scope_to_item(item, scope) for item in payload]
    if not isinstance(payload, dict):
        raise ValueError("research payload must be an object or list")
    if isinstance(payload.get("findings"), list):
        scoped = dict(payload)
        scoped["findings"] = [_apply_scope_to_item(item, scope) for item in payload["findings"]]
        return scoped
    return _apply_scope_to_item(payload, scope)


def _apply_scope_to_item(item: dict[str, Any], scope: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("research finding must be an object")
    scoped = dict(item)
    scoped.setdefault("scope", scope)
    return scoped
