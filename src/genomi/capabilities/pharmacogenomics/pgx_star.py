from __future__ import annotations

import json
import re
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any

from ..variant import variant_lookup

JsonObject = dict[str, Any]
PGX_STAR_CALL_SCHEMA = "genomi-pgx-star-allele-call-v1"
PGX_MARKER_DEFINITION_SCHEMA = "genomi-pgx-marker-definition-catalog-v1"
PGX_MARKER_DEFINITION_RESOURCE = ("data", "star_marker_definitions.json")
_STAR_CATALOG_CACHE: dict[str, Any] | None = None


def marker_definition_catalog() -> dict[str, Any]:
    global _STAR_CATALOG_CACHE
    if _STAR_CATALOG_CACHE is None:
        resource = importlib_resources.files(__package__).joinpath(*PGX_MARKER_DEFINITION_RESOURCE)
        payload = json.loads(resource.read_text(encoding="utf-8"))
        if payload.get("schema") != PGX_MARKER_DEFINITION_SCHEMA or not isinstance(payload.get("definition_sets"), list):
            raise RuntimeError("PGx marker definition data has an unsupported schema")
        _STAR_CATALOG_CACHE = payload
    return dict(_STAR_CATALOG_CACHE)


def marker_definitions_by_gene() -> dict[str, dict[str, Any]]:
    return {
        str(definition["gene"]).upper(): definition
        for definition in marker_definition_catalog()["definition_sets"]
        if isinstance(definition, dict) and definition.get("gene")
    }


STAR_DEFINITIONS: dict[str, dict[str, Any]] = marker_definitions_by_gene()


def implemented_marker_definition_genes() -> list[str]:
    return sorted(STAR_DEFINITIONS)


def call_star_alleles(
    *,
    gene: str,
    genome_build: str = "GRCh38",
    db: str | Path | None = None,
    shared_db: str | Path | None = None,
    include_active_genome_index: bool = True,
    include_known_active_genome_indexes: bool = False,
    include_fail: bool = False,
    limit: int = 20,
) -> JsonObject:
    gene_symbol = str(gene or "").strip().upper()
    if not gene_symbol:
        return {
            "schema": PGX_STAR_CALL_SCHEMA,
            "ok": False,
            "status": "needs_pharmacogene",
            "gene": None,
            "implemented_marker_definition_genes": implemented_marker_definition_genes(),
            "missing_inputs": ["gene"],
        }
    definition = STAR_DEFINITIONS.get(gene_symbol)
    if definition is None:
        return {
            "schema": PGX_STAR_CALL_SCHEMA,
            "ok": False,
            "status": "unsupported_gene",
            "gene": gene_symbol,
            "implemented_marker_definition_genes": implemented_marker_definition_genes(),
    }
    if not include_active_genome_index and not include_known_active_genome_indexes and db is None:
        marker_calls = [_marker_without_sample_context({**marker, "gene": gene_symbol}) for marker in definition["markers"]]
        return {
            "schema": PGX_STAR_CALL_SCHEMA,
            "ok": False,
            "status": "no_sample_context",
            "gene": gene_symbol,
            "genome_build": genome_build,
            "definition_set": definition["definition_set"],
            "definition_scope": definition.get("definition_scope", marker_definition_catalog().get("curation_scope")),
            "marker_calls": marker_calls,
            "called_star_alleles": [],
            "diplotype": _no_sample_diplotype(gene_symbol),
            "traceability": {
                "definition_sources": definition["sources"],
                "marker_definitions": definition["markers"],
            },
            "warnings": [],
            "missing_inputs": ["active_genome_index", "agi_id", "known_diplotype", "known_phenotype", "known_activity_score"],
        }

    marker_calls = []
    warnings: list[str] = []
    for marker in definition["markers"]:
        marker = {**marker, "gene": gene_symbol}
        lookup = variant_lookup.lookup_variant(
            rsid=marker["rsid"],
            genome_build=genome_build,
            db=db,
            shared_db=shared_db,
            include_active_genome_index=include_active_genome_index,
            include_known_active_genome_indexes=include_known_active_genome_indexes,
            include_fail=include_fail,
            limit=limit,
        )
        marker_calls.append(_marker_call(marker, lookup))
        warnings.extend(str(item) for item in lookup.get("warnings") or [])

    diplotype = _infer_cyp2c19(marker_calls, definition)
    return {
        "schema": PGX_STAR_CALL_SCHEMA,
        "ok": True,
        "status": "completed",
        "gene": gene_symbol,
        "genome_build": genome_build,
        "definition_set": definition["definition_set"],
        "definition_scope": definition.get("definition_scope", marker_definition_catalog().get("curation_scope")),
        "marker_calls": marker_calls,
        "called_star_alleles": _called_star_alleles(marker_calls),
        "diplotype": diplotype,
        "traceability": {
            "definition_sources": definition["sources"],
            "marker_definitions": definition["markers"],
        },
        "warnings": sorted(set(warnings)),
    }


def _marker_without_sample_context(marker: JsonObject) -> JsonObject:
    return {
        **marker,
        "evidence_status": "no_active_genome_index_selected",
        "effect_allele_count": 0,
        "sample_calls": [],
        "lookup_summary": {
            "sample_match_count": 0,
            "public_context_keys": [],
        },
    }


def _marker_call(marker: JsonObject, lookup: JsonObject) -> JsonObject:
    matches = lookup.get("sample_context", {}).get("matches") or []
    sample_calls = []
    total_effect_count = 0
    called = False
    for match in matches:
        call = _sample_marker_call(match, marker["effect_allele"])
        sample_calls.append(call)
        if call["called"]:
            called = True
            total_effect_count += call["effect_allele_count"]
    if total_effect_count:
        evidence_status = "observed_effect_allele"
    elif called:
        evidence_status = "observed_reference_or_other_allele"
    else:
        evidence_status = "not_observed_in_active_genome_index"
    return {
        **marker,
        "evidence_status": evidence_status,
        "effect_allele_count": total_effect_count,
        "sample_calls": sample_calls,
        "lookup_summary": {
            "sample_match_count": int(lookup.get("sample_context", {}).get("count") or 0),
            "public_context_keys": sorted((lookup.get("public_context") or {}).keys()),
        },
    }


def _sample_marker_call(match: JsonObject, effect_allele: str) -> JsonObject:
    alleles = _observed_alleles(match)
    effect_count = sum(1 for allele in alleles if allele == effect_allele.upper())
    return {
        "called": bool(alleles),
        "observed_alleles": alleles,
        "effect_allele_count": effect_count,
        "genotype": match.get("genotype"),
        "chrom": match.get("chrom"),
        "pos": match.get("pos"),
        "ref": match.get("ref"),
        "alt": match.get("alt"),
        "filter": match.get("filter"),
        "source_format": match.get("source_format"),
        "agi_id": match.get("agi_id"),
    }


def _observed_alleles(match: JsonObject) -> list[str]:
    genotype = str(match.get("genotype") or "").strip().upper()
    ref = str(match.get("ref") or "").strip().upper()
    alts = [item.strip().upper() for item in str(match.get("alt") or "").split(",") if item.strip()]
    if re.fullmatch(r"[0-9.]+([/|][0-9.]+)*", genotype):
        alleles = []
        for token in re.split(r"[/|]", genotype):
            if token in {"", "."}:
                continue
            try:
                index = int(token)
            except ValueError:
                continue
            if index == 0 and ref:
                alleles.append(ref)
            elif index > 0 and index <= len(alts):
                alleles.append(alts[index - 1])
        return alleles
    letter_tokens = re.findall(r"[ACGT]", genotype)
    if letter_tokens:
        return letter_tokens
    return []


def _called_star_alleles(marker_calls: list[JsonObject]) -> list[JsonObject]:
    alleles = []
    for call in marker_calls:
        for _ in range(int(call.get("effect_allele_count") or 0)):
            alleles.append(
                {
                    "gene": call.get("gene"),
                    "star_allele": call["star_allele"],
                    "function": call["function"],
                    "support": call["evidence_status"],
                    "rsid": call["rsid"],
                }
            )
    return alleles


def _no_sample_diplotype(gene: str) -> JsonObject:
    return {
        "gene": gene,
        "possible_diplotype": None,
        "predicted_phenotype": None,
        "marker_support_status": "no_sample_context",
        "limitations": [
            "Marker definitions are available as public context.",
            "Sample diplotype and phenotype require an Active Genome Index or another explicit sample PGx call.",
            "Clinical medication actionability uses drug-specific guideline context and clinician review.",
        ],
    }


def _infer_cyp2c19(marker_calls: list[JsonObject], definition: JsonObject) -> JsonObject:
    observed_statuses = {"observed_effect_allele", "observed_reference_or_other_allele"}
    observed_all_markers = all(call["evidence_status"] in observed_statuses for call in marker_calls)
    no_function = sum(int(call.get("effect_allele_count") or 0) for call in marker_calls if call["function"] == "no_function")
    increased = sum(int(call.get("effect_allele_count") or 0) for call in marker_calls if call["function"] == "increased_function")
    allele_tokens = [allele["star_allele"] for allele in _called_star_alleles(marker_calls)]
    if observed_all_markers and len(allele_tokens) < 2:
        allele_tokens.extend([definition["normal_function_allele"]] * (2 - len(allele_tokens)))
    if not allele_tokens:
        allele_tokens = []
    phenotype = None
    marker_support_status = "marker_evidence_only"
    if observed_all_markers:
        marker_support_status = "common_marker_subset_observed"
        if no_function >= 2:
            phenotype = "poor_metabolizer"
        elif no_function == 1:
            phenotype = "intermediate_metabolizer"
        elif increased >= 2:
            phenotype = "ultrarapid_metabolizer"
        elif increased == 1:
            phenotype = "rapid_metabolizer"
        else:
            phenotype = "normal_metabolizer"
    return {
        "gene": definition.get("gene"),
        "possible_diplotype": "/".join(allele_tokens) if allele_tokens else None,
        "predicted_phenotype": phenotype,
        "marker_support_status": marker_support_status,
        "limitations": [
            "This call uses a small marker subset intended for evidence triage.",
            "Reference or *1 assignment uses observed reference calls across the definition set or another validated caller.",
            "Clinical medication actionability uses drug-specific guideline context and clinician review.",
        ],
    }
