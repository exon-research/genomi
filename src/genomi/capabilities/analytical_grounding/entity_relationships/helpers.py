from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from typing import Any

from .constants import (
    CONTROLLED_ID_PREFIXES,
    EXPERIMENTAL_GO_EVIDENCE_CODES,
    TAG_RE,
)


def _entity_type_from_id(entity_id: str) -> str:
    cleaned = _clean_text(entity_id)
    if _normalize_chembl_id(cleaned):
        return "drug"
    for prefix, entity_type in CONTROLLED_ID_PREFIXES.items():
        if cleaned.upper().startswith(prefix):
            return entity_type
    if _normalize_kegg_compound_id(cleaned):
        return "chemical"
    return ""


def _normalize_entity_type(value: str | None) -> str:
    cleaned = _clean_text(value).casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "go": "go_term",
        "gene_ontology": "go_term",
        "go_term": "go_term",
        "process": "go_term",
        "function": "go_term",
        "component": "go_term",
        "cell": "cell_type",
        "cell_type": "cell_type",
        "single_cell_type": "cell_type",
        "drug": "drug",
        "pathway": "pathway",
        "reactome": "pathway",
        "compound": "chemical",
        "chemical": "chemical",
        "metabolite": "chemical",
        "small_molecule": "chemical",
        "tissue": "tissue",
    }
    return aliases.get(cleaned, cleaned)


def _normalize_sources(values: list[str]) -> list[str]:
    aliases = {
        "chembl": "chembl",
        "quickgo": "goa",
        "go": "goa",
        "gene_ontology": "goa",
        "goa": "goa",
        "hpa": "hpa",
        "human_protein_atlas": "hpa",
        "reactome": "reactome",
        "kegg": "kegg",
        "kegg_compound": "kegg",
        "compound": "kegg",
    }
    sources: list[str] = []
    for value in values:
        cleaned = _clean_text(value).casefold().replace("-", "_").replace(" ", "_")
        source = aliases.get(cleaned, cleaned)
        if source and source not in sources:
            sources.append(source)
    return sources


def _source_label(source: str) -> str:
    return {
        "chembl": "ChEMBL",
        "goa": "QuickGO Gene Ontology Annotation",
        "hpa": "Human Protein Atlas",
        "kegg": "KEGG REST",
        "reactome": "Reactome ContentService",
    }.get(source, source)


def _same_label(left: Any, right: Any) -> bool:
    return _normalise_label(left) == _normalise_label(right)


def _candidate_label_matches(candidate: dict[str, Any], query: Any) -> bool:
    labels = [candidate.get("name"), *(candidate.get("synonyms") or [])]
    return any(_same_label(label, query) for label in labels)


def _normalise_label(value: Any) -> str:
    return " ".join(_clean_text(value).casefold().replace("-", " ").replace("_", " ").split())


def _normalize_relationship_type(value: Any) -> str:
    cleaned = _clean_text(value).casefold().replace(" ", "_").replace("-", "_")
    aliases = {
        "biological_process": "involved_in",
        "molecular_function": "enables",
        "cellular_component": "located_in",
        "pathway": "pathway_participant",
        "participant": "pathway_participant",
        "enzyme": "enzyme_associated_with",
        "enzyme_association": "enzyme_associated_with",
        "compound_enzyme": "enzyme_associated_with",
        "chemical_enzyme": "enzyme_associated_with",
        "tissue_enriched": "tissue_enriched_expression",
        "tissue_enriched_expression": "tissue_enriched_expression",
        "tissue_group_enriched": "tissue_group_enriched_expression",
        "tissue_group_enriched_expression": "tissue_group_enriched_expression",
        "tissue_enhanced": "tissue_enhanced_expression",
        "tissue_enhanced_expression": "tissue_enhanced_expression",
        "cell_type_enriched": "cell_type_enriched_expression",
        "cell_type_enriched_expression": "cell_type_enriched_expression",
        "cell_type_group_enriched": "cell_type_group_enriched_expression",
        "cell_type_group_enriched_expression": "cell_type_group_enriched_expression",
        "cell_type_enhanced": "cell_type_enhanced_expression",
        "cell_type_enhanced_expression": "cell_type_enhanced_expression",
        "drug_target": "drug_target_mechanism",
        "drug_target_mechanism": "drug_target_mechanism",
        "mechanism_target": "drug_target_mechanism",
    }
    return aliases.get(cleaned, cleaned)


def _normalize_evidence_class(value: Any) -> str:
    cleaned = _clean_text(value).casefold().replace(" ", "_").replace("-", "_")
    aliases = {
        "experiment": "experimental",
        "experimental": "experimental",
        "curated": "curated_or_computational",
        "computational": "curated_or_computational",
        "curated_or_computational": "curated_or_computational",
        "pathway": "curated_pathway_membership",
        "pathway_membership": "curated_pathway_membership",
        "curated_pathway_membership": "curated_pathway_membership",
        "compound_enzyme": "compound_enzyme_gene_link",
        "enzyme_gene": "compound_enzyme_gene_link",
        "compound_enzyme_gene_link": "compound_enzyme_gene_link",
        "hpa_tissue": "hpa_tissue_rna_specificity",
        "hpa_tissue_rna": "hpa_tissue_rna_specificity",
        "hpa_tissue_rna_specificity": "hpa_tissue_rna_specificity",
        "hpa_single_cell": "hpa_single_cell_type_rna_specificity",
        "hpa_cell_type": "hpa_single_cell_type_rna_specificity",
        "hpa_single_cell_type_rna_specificity": "hpa_single_cell_type_rna_specificity",
        "chembl_drug_mechanism": "chembl_drug_mechanism_target",
        "chembl_drug_mechanism_target": "chembl_drug_mechanism_target",
        "drug_mechanism_target": "chembl_drug_mechanism_target",
        "unspecified": "unspecified",
    }
    return aliases.get(cleaned, cleaned)


def _normalize_kegg_compound_id(value: Any) -> str:
    cleaned = _clean_text(value)
    upper = cleaned.upper()
    if upper.startswith("CPD:") or upper.startswith("COMPOUND:"):
        suffix = upper.split(":", 1)[1]
    else:
        suffix = upper
    if re.fullmatch(r"C\d{5}", suffix):
        return f"cpd:{suffix}"
    return ""


def _normalize_chembl_id(value: Any) -> str:
    cleaned = _clean_text(value).upper()
    return cleaned if re.fullmatch(r"CHEMBL\d+", cleaned) else ""


def _go_aspect_relationship(aspect: Any) -> str:
    return {
        "biological_process": "involved_in",
        "molecular_function": "enables",
        "cellular_component": "located_in",
    }.get(_clean_text(aspect).casefold(), "associated_with")


def _go_evidence_class(code: Any) -> str:
    cleaned = _clean_text(code).upper()
    if cleaned in EXPERIMENTAL_GO_EVIDENCE_CODES:
        return "experimental"
    if cleaned:
        return "curated_or_computational"
    return "unspecified"


def _strip_markup(value: Any) -> str:
    return _clean_text(html.unescape(TAG_RE.sub(" ", str(value or ""))))


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _url(base: str, path: str, params: dict[str, str]) -> str:
    url = base.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode({key: value for key, value in params.items() if value})
    return url


def _fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "genomi/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"Accept": "text/plain", "User-Agent": "genomi/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def _fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/octet-stream", "User-Agent": "genomi/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _safe_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
