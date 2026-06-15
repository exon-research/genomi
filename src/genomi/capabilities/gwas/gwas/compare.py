from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import quote

from ....evidence.candidate_evidence import (
    apply_evidence_view,
    evidence_view,
)
from ....evidence.task_profiles import (
    GWAS_GENE_PRIORITIZATION,
    GWAS_VARIANT_PRIORITIZATION,
)
from ....retrieval import semantic as retrieval_semantic
from ....runtime.handoff import evidence_context
from .constants import (
    GWAS_CATALOG_API_URL,
    GWAS_CATALOG_PROJECTION,
    GWAS_CATALOG_SOURCE_URL,
    GWAS_CATALOG_V2_API_URL,
    GWAS_GENE_FIELD_EVIDENCE_INTENT,
    GWAS_MAX_ASSOCIATION_LIMIT,
    GWAS_MAX_EMITTED_ASSOCIATIONS,
)
from .parsing import (
    _association_record,
    _causal_gene_task_text,
    _dedupe_gene_records,
    _explicit_gwas_gene_field_task_text,
    _fetch_gwas_catalog_records,
    _fetch_gwas_efo_traits,
    _fetch_json,
    _gene_association_record,
)
from .phenotype_match import (
    _gwas_semantic_usage,
    _semantic_trait_queries,
)
from .ranking import (
    _candidate_matrix,
    _gene_candidate_matrix,
    _gene_selection_warnings,
    _selection_warnings,
)
from .text_utils import (
    _best_pvalue,
    _clean_text,
    _embedded_list,
    _normalize_genes,
    _normalize_rsids,
    _pvalue_sort_value,
)


def compare_gwas_variant_evidence(
    phenotype: str,
    variants: Iterable[str],
    *,
    api_url: str = GWAS_CATALOG_API_URL,
    association_limit: int = 200,
    timeout: int = 30,
    fetch_json: Callable[[str], dict[str, Any]] | None = None,
    semantic_context: object = None,
) -> dict[str, Any]:
    """Rank candidate rsIDs by GWAS Catalog associations for the requested phenotype."""
    normalized_phenotype = _clean_text(phenotype)
    if not normalized_phenotype:
        raise ValueError("phenotype is required")
    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    phenotype_queries = _semantic_trait_queries(semantic, normalized_phenotype)
    rsids = _normalize_rsids(variants)
    if not rsids:
        raise ValueError("at least one rsID variant is required")
    if association_limit < 1:
        raise ValueError("association_limit must be positive")
    association_limit = min(int(association_limit), GWAS_MAX_ASSOCIATION_LIMIT)

    fetch = fetch_json or (lambda url: _fetch_json(url, timeout=timeout))
    api_base = api_url.rstrip("/")
    matches: list[dict[str, Any]] = []
    matches_by_variant: dict[str, list[dict[str, Any]]] = {}
    variant_summaries: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for rsid in rsids:
        url = (
            f"{api_base}/singleNucleotidePolymorphisms/{quote(rsid)}/associations"
            f"?projection={quote(GWAS_CATALOG_PROJECTION)}&size={association_limit}"
        )
        try:
            response = fetch(url)
        except urllib.error.HTTPError as exc:
            errors.append({"variant": rsid, "url": url, "error": f"HTTP {exc.code}"})
            response = {}
        except urllib.error.URLError as exc:
            errors.append({"variant": rsid, "url": url, "error": str(exc.reason)})
            response = {}
        except TimeoutError as exc:
            errors.append({"variant": rsid, "url": url, "error": str(exc)})
            response = {}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            errors.append({"variant": rsid, "url": url, "error": f"parse error: {exc}"})
            response = {}
        except OSError as exc:
            errors.append({"variant": rsid, "url": url, "error": f"I/O error: {exc}"})
            response = {}

        associations = _embedded_list(response, "associations")
        variant_matches = [
            _association_record(rsid, assoc, normalized_phenotype, phenotype_queries=phenotype_queries)
            for assoc in associations
        ]
        matches_by_variant[rsid] = variant_matches
        scored_matches = [match for match in variant_matches if match["phenotype_match"]["score"] > 0]
        matches.extend(scored_matches)
        variant_summaries.append(
            {
                "variant": rsid,
                "queried_url": url,
                "association_count": len(associations),
                "phenotype_match_count": len(scored_matches),
                "best_pvalue": _best_pvalue(variant_matches),
                "best_phenotype_pvalue": _best_pvalue(scored_matches),
            }
        )

    ranked = sorted(
        matches,
        key=lambda match: (
            -int(match["phenotype_match"]["score"]),
            _pvalue_sort_value(match.get("pvalue")),
            match["variant"],
            match.get("association_id") or "",
        ),
    )
    top = ranked[0] if ranked else None
    emitted_ranked = ranked[:GWAS_MAX_EMITTED_ASSOCIATIONS]
    candidate_matrix = _candidate_matrix(rsids, matches_by_variant)
    selected_candidate = next((candidate for candidate in candidate_matrix if candidate["rank"] == 1), None)
    decision_policy = {
        "policy_id": "gwas_variant_candidate_matrix_v1",
        "ranking_order": [
            "evidence lane strength",
            "p-value inside the same evidence lane",
            "candidate identifier for deterministic tie-breaking",
        ],
        "rule": "Exact GWAS Catalog trait/source matches outrank nearby trait or pathway plausibility. P-value is a tie-breaker within the same evidence lane.",
    }
    warnings = _selection_warnings(selected_candidate, candidate_matrix)
    status = "completed"
    coverage_state = "data_returned"
    if errors and len(errors) == len(rsids) and not ranked:
        status = "source_unavailable"
        coverage_state = "source_unavailable"
    elif not ranked:
        status = "no_matching_gwas_associations"
        coverage_state = "in_scope_empty"
    view = evidence_view(
        task_profile=GWAS_VARIANT_PRIORITIZATION,
        query={
            "phenotype": normalized_phenotype,
            "variants": rsids,
            "association_limit_per_variant": association_limit,
        },
        candidate_matrix=candidate_matrix,
        top_observed_candidate=selected_candidate,
        evidence_policy=decision_policy,
        warnings=warnings,
        coverage_state=coverage_state,
    )
    result = {
        "status": status,
        "source": {
            "id": "gwas_catalog",
            "title": "GWAS Catalog",
            "url": GWAS_CATALOG_SOURCE_URL,
            "api_url": api_base,
            "projection": GWAS_CATALOG_PROJECTION,
        },
        "query": {
            "phenotype": normalized_phenotype,
            "variants": rsids,
            "association_limit_per_variant": association_limit,
        },
        "summary": {
            "variant_count": len(rsids),
            "association_count": sum(int(item["association_count"]) for item in variant_summaries),
            "matched_association_count": len(ranked),
            "emitted_association_count": len(emitted_ranked),
            "ranked_associations_truncated": len(ranked) > len(emitted_ranked),
            "variants_with_phenotype_match": sum(1 for item in variant_summaries if item["phenotype_match_count"]),
            "top_variant": top["variant"] if top else None,
            "top_observed_candidate": selected_candidate["candidate_id"] if selected_candidate else None,
            "top_observed_support_level": selected_candidate["evidence_support_level"] if selected_candidate else "none",
        },
        "variant_summaries": variant_summaries,
        "task_profile": GWAS_VARIANT_PRIORITIZATION.to_dict(),
        "decision_policy": decision_policy,
        "top_association": top,
        "top_record_research_payload": top.get("record_research_payload") if top else None,
        "ranked_associations": emitted_ranked,
        "errors": errors,
    }
    if semantic.has_hints:
        result["query"]["semantic_trait_queries"] = phenotype_queries
        result["semantic_context"] = _gwas_semantic_usage(
            semantic,
            matched_records=ranked,
            exact_ids=rsids,
            source_filters=[normalized_phenotype],
        )
    apply_evidence_view(result, view, operation="gwas.compare_variant_associations")
    if top:
        result["evidence_context"] = evidence_context(
            "research",
            reason="GWAS association candidates are compared; record selected reviewed findings or gather genotype support before user-facing interpretation.",
            commands=[
                "genomi call active_genome_index.classify_genotype_support --params '{\"agi_path\":\"<agi.sqlite>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
                "genomi call research.record --params '{\"db\":\"<evidence.sqlite>\",\"input\":\"<finding.json>\",\"scope\":\"shared\"}'",
            ],
        )
    return result


def compare_gwas_gene_evidence(
    phenotype: str,
    genes: Iterable[str],
    *,
    api_url: str = GWAS_CATALOG_V2_API_URL,
    association_limit: int = 200,
    timeout: int = 30,
    source_records: Iterable[dict[str, Any]] | None = None,
    fetch_json: Callable[[str], dict[str, Any]] | None = None,
    task_text: str | None = None,
    evidence_intent: str | None = None,
    semantic_context: object = None,
) -> dict[str, Any]:
    """Rank candidate genes by GWAS Catalog trait associations."""
    normalized_phenotype = _clean_text(phenotype)
    if not normalized_phenotype:
        raise ValueError("phenotype is required")
    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    phenotype_queries = _semantic_trait_queries(semantic, normalized_phenotype)
    candidate_genes = _normalize_genes(genes)
    if not candidate_genes:
        raise ValueError("at least one candidate gene is required")
    association_limit = min(max(1, int(association_limit or 200)), GWAS_MAX_ASSOCIATION_LIMIT)
    if _causal_gene_task_text(task_text) and not _explicit_gwas_gene_field_task_text(task_text):
        return _wrong_gwas_gene_evidence_regime(
            normalized_phenotype,
            candidate_genes,
            association_limit=association_limit,
            task_text=task_text,
            evidence_intent=evidence_intent,
        )
    errors: list[dict[str, str]] = []
    if source_records is not None:
        records = [
            _gene_association_record(
                record,
                normalized_phenotype,
                source_origin="provided_source_record",
                phenotype_queries=phenotype_queries,
            )
            for record in source_records
            if isinstance(record, dict)
        ]
        source_status = "provided_source_records"
        queried_url = None
    else:
        api_base = api_url.rstrip("/")
        fetch = fetch_json or (lambda url: _fetch_json(url, timeout=timeout))
        trait_search_urls = [
            f"{api_base}/efo-traits?efo_trait={quote(query)}&size={min(10, association_limit)}"
            for query in phenotype_queries
        ]
        queried_urls = list(dict.fromkeys(trait_search_urls))
        queried_url = queried_urls[0]
        raw_records: list[dict[str, Any]] = []
        seen_efo_ids: set[str] = set()
        for trait_search_url in trait_search_urls:
            trait_records = _fetch_gwas_efo_traits(trait_search_url, fetch=fetch, errors=errors)
            for trait in trait_records:
                efo_id = str(trait.get("efo_id") or "").strip()
                if not efo_id or efo_id in seen_efo_ids:
                    continue
                seen_efo_ids.add(efo_id)
                queried_urls.append(
                    f"{api_base}/associations?efo_id={quote(efo_id)}&show_child_trait=true&size={association_limit}"
                )
        queried_urls.extend(
            f"{api_base}/associations?mapped_gene={quote(gene)}&size={association_limit}"
            for gene in candidate_genes
        )
        for url in queried_urls[1:]:
            raw_records.extend(_fetch_gwas_catalog_records(url, fetch=fetch, errors=errors))
        records = [
            _gene_association_record(
                record,
                normalized_phenotype,
                source_origin="gwas_catalog_api",
                phenotype_queries=phenotype_queries,
            )
            for record in raw_records
        ]
        records = _dedupe_gene_records(records)
        source_status = "queried_gwas_catalog"
    matrix = _gene_candidate_matrix(candidate_genes, records)
    selected = next((candidate for candidate in matrix if candidate["rank"] == 1), None)
    decision_policy = {
        "policy_id": "gwas_gene_candidate_matrix_v1",
        "ranking_order": [
            "exact GWAS trait match with the candidate in the author-reported gene field",
            "nearby GWAS trait match naming the candidate gene",
            "candidate named in a stronger GWAS Catalog source gene field: reported_genes before mapped_genes before generic extracted genes",
            "p-value within the same evidence lane and source gene field",
            "candidate identifier for deterministic tie-breaking",
        ],
        "rule": "This is GWAS Catalog gene-field evidence. Mapped-gene support is not causal-gene assignment; phenotype.retrieve_trait_gene_records retrieves native trait-to-gene evidence from integrated public sources.",
    }
    warnings = _gene_selection_warnings(selected, matrix)
    status = "completed"
    coverage_state = "data_returned"
    if errors and not any(row["score"] > 0 for row in matrix):
        status = "source_unavailable"
        coverage_state = "source_unavailable"
    elif not any(row["score"] > 0 for row in matrix):
        status = "no_matching_gwas_gene_associations"
        coverage_state = "in_scope_empty"
    view = evidence_view(
        task_profile=GWAS_GENE_PRIORITIZATION,
        query={
            "phenotype": normalized_phenotype,
            "genes": candidate_genes,
            "association_limit": association_limit,
        },
        candidate_matrix=matrix,
        top_observed_candidate=selected,
        evidence_policy=decision_policy,
        warnings=warnings,
        coverage_state=coverage_state,
    )
    result = {
        "status": status,
        "source": {
            "id": "gwas_catalog",
            "title": "GWAS Catalog",
            "url": GWAS_CATALOG_SOURCE_URL,
            "api_url": api_url.rstrip("/"),
            "queried_url": queried_url,
            "queried_urls": queried_urls if source_records is None else [],
        },
        "query": {"phenotype": normalized_phenotype, "genes": candidate_genes, "association_limit": association_limit},
        "summary": {
            "gene_count": len(candidate_genes),
            "association_record_count": len(records),
            "source_status": source_status,
            "top_observed_candidate": selected["candidate_id"] if selected else None,
            "top_observed_support_level": selected["evidence_support_level"] if selected else "none",
        },
        "association_records": records[:GWAS_MAX_EMITTED_ASSOCIATIONS],
        "task_profile": GWAS_GENE_PRIORITIZATION.to_dict(),
        "decision_policy": decision_policy,
        "errors": errors,
        "routing_contract": {
            "evidence_intent": evidence_intent,
            "accepted_intent": GWAS_GENE_FIELD_EVIDENCE_INTENT,
            "not_for": ["causal_gene_at_locus", "effector_gene_selection", "drug_target_or_mechanism_selection"],
            "use_instead": "phenotype.retrieve_trait_gene_records",
        },
    }
    if semantic.has_hints:
        result["query"]["semantic_trait_queries"] = phenotype_queries
        result["semantic_context"] = _gwas_semantic_usage(
            semantic,
            matched_records=records,
            exact_ids=candidate_genes,
            source_filters=[normalized_phenotype],
        )
    apply_evidence_view(result, view, operation="gwas.compare_gene_associations")
    return result


def _wrong_gwas_gene_evidence_regime(
    phenotype: str,
    genes: list[str],
    *,
    association_limit: int,
    task_text: str | None,
    evidence_intent: str | None,
) -> dict[str, Any]:
    matrix = _gene_candidate_matrix(genes, [])
    decision_policy = {
        "policy_id": "gwas_gene_wrong_evidence_regime_v1",
        "ranking_order": [],
        "rule": (
            "The task wording asks for a causal, effector, target, or locus gene. "
            "GWAS Catalog reported/mapped gene fields are association annotations and should not be used as a causal-gene oracle."
        ),
    }
    warnings = [
        "wrong_evidence_regime:gwas_gene_fields_not_used_for_causal_gene_selection",
        "trait_gene_records_required:retrieve_native_trait_gene_evidence",
    ]
    view = evidence_view(
        task_profile=GWAS_GENE_PRIORITIZATION,
        query={"phenotype": phenotype, "genes": genes, "association_limit": association_limit, "task_text": task_text},
        candidate_matrix=matrix,
        top_observed_candidate=None,
        infer_top_observed_candidate=False,
        evidence_policy=decision_policy,
        warnings=warnings,
        coverage_state="out_of_scope_for_input",
        evidence_state="wrong_evidence_regime",
    )
    result = {
        "status": "wrong_evidence_regime",
        "coverage_state": "out_of_scope_for_input",
        "source": {
            "id": "gwas_catalog",
            "title": "GWAS Catalog",
            "url": GWAS_CATALOG_SOURCE_URL,
            "api_url": GWAS_CATALOG_V2_API_URL,
            "queried_url": None,
            "queried_urls": [],
        },
        "query": {"phenotype": phenotype, "genes": genes, "association_limit": association_limit},
        "summary": {
            "gene_count": len(genes),
            "association_record_count": 0,
            "source_status": "not_queried_wrong_evidence_regime",
            "top_observed_candidate": None,
            "top_observed_support_level": "none",
        },
        "association_records": [],
        "task_profile": GWAS_GENE_PRIORITIZATION.to_dict(),
        "decision_policy": decision_policy,
        "errors": [],
        "routing_hint": {
            "recommended_operation": "phenotype.retrieve_trait_gene_records",
            "reason": "causal or effector gene selection needs native trait-to-gene evidence, not GWAS Catalog gene-field rank alone",
            "minimum_params": {"phenotype": phenotype, "genes": genes, "task_text": task_text or ""},
        },
        "routing_contract": {
            "evidence_intent": evidence_intent,
            "accepted_intent": GWAS_GENE_FIELD_EVIDENCE_INTENT,
            "not_for": ["causal_gene_at_locus", "effector_gene_selection", "drug_target_or_mechanism_selection"],
            "use_instead": "phenotype.retrieve_trait_gene_records",
        },
    }
    apply_evidence_view(result, view, operation="gwas.compare_gene_associations")
    return result
