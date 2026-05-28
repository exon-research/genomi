"""Operation entry points for the nutrigenomics capability.

Four retrieval verbs, all returning records over declared curated data.
None of them recommend diets, prescribe supplements, or interpret intent.
"""
from __future__ import annotations

from typing import Any

from ...retrieval import semantic as retrieval_semantic
from . import catalog, source_context

JsonObject = dict[str, Any]


_VALID_EVIDENCE_TIERS = ("established", "probable", "emerging")


def list_domains() -> JsonObject:
    """Return the declared nutrigenomic domains plus evidence-tier summaries."""
    return {
        "capability": source_context.CAPABILITY_ID,
        "schema": source_context.SCHEMA_VERSION,
        "domains": catalog.domain_summary(),
        "out_of_scope_by_construction": list(source_context.OUT_OF_SCOPE_BY_CONSTRUCTION),
        "boundary_note": source_context.BOUNDARY_NOTE,
        "coverage_status": "data_returned",
    }


def build_source_context() -> JsonObject:
    """Return capability provenance, label definitions, and method limitations."""
    return source_context.build_source_context()


def retrieve_domain_markers(
    *,
    domain_id: str | None = None,
    min_evidence_tier: str = "established",
    semantic_context: object = None,
) -> JsonObject:
    """Return curated marker records for a declared nutrigenomic domain."""
    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    requested_domain_id = domain_id
    domain_id = _resolve_domain_id(domain_id, semantic)
    if not domain_id or not isinstance(domain_id, str):
        response = _empty(
            status="domain_id_required",
            coverage_status="out_of_scope_for_input",
            empty_reason="domain_id is required. Call nutrigenomics.list_domains to browse declared domains.",
            extra={"declared_domains": list(source_context.DOMAIN_DEFINITIONS.keys())},
        )
        return _with_semantic_usage(response, semantic, requested_domain_id, None)
    if domain_id in source_context.OUT_OF_SCOPE_BY_CONSTRUCTION:
        response = _empty(
            status="domain_out_of_scope_by_construction",
            coverage_status="out_of_scope_for_input",
            empty_reason=(
                f"Domain '{domain_id}' is out of scope by construction. The nutrigenomics "
                "capability does not return records for this domain — there is no replicated "
                "single-marker evidence base for this question."
            ),
            extra={
                "declared_domains": list(source_context.DOMAIN_DEFINITIONS.keys()),
                "out_of_scope_by_construction": list(source_context.OUT_OF_SCOPE_BY_CONSTRUCTION),
            },
        )
        return _with_semantic_usage(response, semantic, requested_domain_id, domain_id)
    if domain_id not in source_context.DOMAIN_DEFINITIONS:
        response = _empty(
            status="unknown_domain",
            coverage_status="out_of_scope_for_input",
            empty_reason=f"Domain '{domain_id}' is not in the declared domain list.",
            extra={"declared_domains": list(source_context.DOMAIN_DEFINITIONS.keys())},
        )
        return _with_semantic_usage(response, semantic, requested_domain_id, None)

    tier = (min_evidence_tier or "established").lower()
    if tier not in _VALID_EVIDENCE_TIERS:
        response = _empty(
            status="invalid_evidence_tier",
            coverage_status="out_of_scope_for_input",
            empty_reason=f"min_evidence_tier must be one of {_VALID_EVIDENCE_TIERS}.",
        )
        return _with_semantic_usage(response, semantic, requested_domain_id, domain_id)

    records = catalog.domain_records(domain_id, min_evidence_tier=tier)
    definition = source_context.DOMAIN_DEFINITIONS[domain_id]
    if not records:
        response = {
            "capability": source_context.CAPABILITY_ID,
            "schema": source_context.SCHEMA_VERSION,
            "domain": {"id": domain_id, **definition},
            "min_evidence_tier_applied": tier,
            "markers": [],
            "coverage_status": "in_scope_empty",
            "empty_reason": (
                f"Domain '{domain_id}' is declared and in scope, but no curated records meet "
                f"min_evidence_tier='{tier}'. Loosen the tier or extend the catalogue."
            ),
            "boundary_note": source_context.BOUNDARY_NOTE,
        }
        return _with_semantic_usage(response, semantic, requested_domain_id, domain_id)

    response = {
        "capability": source_context.CAPABILITY_ID,
        "schema": source_context.SCHEMA_VERSION,
        "domain": {"id": domain_id, **definition},
        "min_evidence_tier_applied": tier,
        "markers": records,
        "coverage_status": "data_returned",
        "boundary_note": source_context.BOUNDARY_NOTE,
        "composition_hints": {
            "population_frequency": "gnomad.fetch_population_frequency",
            "primary_gwas_effects": "gwas.compare_variant_associations",
            "genome_scanning": (
                "active_genome_index.classify_genotype_support with the variant coordinates "
                "from each record"
            ),
        },
    }
    return _with_semantic_usage(response, semantic, requested_domain_id, domain_id)


def retrieve_variant_records(*, rsid: str | None = None) -> JsonObject:
    """Return any nutrigenomic records that reference a given variant."""
    if not rsid or not isinstance(rsid, str):
        return _empty(
            status="rsid_required",
            coverage_status="out_of_scope_for_input",
            empty_reason="rsid is required (e.g. 'rs1801133').",
        )
    cleaned = rsid.strip()
    if not cleaned.lower().startswith("rs"):
        return _empty(
            status="invalid_rsid",
            coverage_status="out_of_scope_for_input",
            empty_reason="Variant identifier must be an rsID (e.g. 'rs1801133').",
        )

    records = catalog.variant_records(cleaned)
    if not records:
        return {
            "capability": source_context.CAPABILITY_ID,
            "schema": source_context.SCHEMA_VERSION,
            "variant": {"rsid": cleaned},
            "records": [],
            "coverage_status": "in_scope_empty",
            "empty_reason": (
                f"Variant '{cleaned}' is not in the nutrigenomic catalogue. The catalogue is "
                "intentionally small; absence is not evidence of negligible effect."
            ),
            "consulted_domains": list(source_context.DOMAIN_DEFINITIONS.keys()),
            "boundary_note": source_context.BOUNDARY_NOTE,
        }

    return {
        "capability": source_context.CAPABILITY_ID,
        "schema": source_context.SCHEMA_VERSION,
        "variant": {"rsid": cleaned},
        "records": records,
        "coverage_status": "data_returned",
        "boundary_note": source_context.BOUNDARY_NOTE,
    }


def _empty(
    *,
    status: str,
    coverage_status: str,
    empty_reason: str,
    extra: JsonObject | None = None,
) -> JsonObject:
    response: JsonObject = {
        "capability": source_context.CAPABILITY_ID,
        "schema": source_context.SCHEMA_VERSION,
        "status": status,
        "coverage_status": coverage_status,
        "empty_reason": empty_reason,
        "boundary_note": source_context.BOUNDARY_NOTE,
    }
    if extra:
        response.update(extra)
    return response


def _resolve_domain_id(domain_id: str | None, semantic: retrieval_semantic.SemanticContext) -> str | None:
    direct = str(domain_id or "").strip()
    if direct in source_context.DOMAIN_DEFINITIONS or direct in source_context.OUT_OF_SCOPE_BY_CONSTRUCTION:
        return direct
    for text in [direct, *retrieval_semantic.search_terms(semantic, entity_types=("domain", "nutrigenomic_domain", "trait_or_condition", "phenotype"))]:
        resolved = _match_declared_domain(text)
        if resolved:
            return resolved
    return direct or None


def _match_declared_domain(text: str | None) -> str | None:
    normalized = _norm(text)
    if not normalized:
        return None
    for domain_id, definition in source_context.DOMAIN_DEFINITIONS.items():
        values = [
            domain_id,
            definition.get("label"),
            definition.get("scope"),
            *(definition.get("downstream_traits") or []),
        ]
        if normalized in {_norm(value) for value in values}:
            return domain_id
    return None


def _with_semantic_usage(
    response: JsonObject,
    semantic: retrieval_semantic.SemanticContext,
    requested_domain_id: str | None,
    resolved_domain_id: str | None,
) -> JsonObject:
    if not semantic.has_hints:
        return response
    matched = [resolved_domain_id]
    if resolved_domain_id and resolved_domain_id in source_context.DOMAIN_DEFINITIONS:
        definition = source_context.DOMAIN_DEFINITIONS[resolved_domain_id]
        matched.extend([definition.get("label"), *(definition.get("downstream_traits") or [])])
    response["semantic_context"] = retrieval_semantic.term_usage_payload(
        semantic,
        term_matches=retrieval_semantic.matched_terms(
            semantic,
            matched,
            match_type="matched_declared_nutrigenomics_domain",
            source="Genomi nutrigenomics domain catalogue",
        ),
        streams=retrieval_semantic.retrieval_streams(
            raw_query=semantic.raw_query,
            host_terms=retrieval_semantic.search_terms(semantic),
            source_native_filters=[value for value in (requested_domain_id, resolved_domain_id) if value],
        ),
    )
    return response


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().replace("_", " ").replace("-", " ").split())
