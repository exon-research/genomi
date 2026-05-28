from __future__ import annotations

import csv
import io
import urllib.parse
import zipfile
from typing import Any

from .constants import TOKEN_RE
from .helpers import (
    _candidate_label_matches,
    _clean_text,
    _go_aspect_relationship,
    _go_evidence_class,
    _normalise_label,
    _normalize_chembl_id,
    _normalize_kegg_compound_id,
    _normalize_relationship_type,
    _safe_float,
    _strip_markup,
    _url,
)


def _quickgo_search(entity_name: str, *, quickgo_api_base: str, fetch_json: Any) -> list[dict[str, Any]]:
    payload = fetch_json(
        _url(
            quickgo_api_base,
            "/ontology/go/search",
            {"query": entity_name, "limit": "10"},
        )
    )
    results = payload.get("results") or []
    candidates: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, dict) or result.get("isObsolete"):
            continue
        candidates.append(
            {
                "source": "goa",
                "entity_type": "go_term",
                "entity_id": _clean_text(result.get("id")),
                "name": _clean_text(result.get("name")),
                "aspect": _clean_text(result.get("aspect")),
                "definition": _clean_text((result.get("definition") or {}).get("text") if isinstance(result.get("definition"), dict) else ""),
            }
        )
    return [candidate for candidate in candidates if candidate["entity_id"] and candidate["name"]]


def _quickgo_term_by_id(entity_id: str, *, quickgo_api_base: str, fetch_json: Any) -> dict[str, Any] | None:
    payload = fetch_json(_url(quickgo_api_base, f"/ontology/go/terms/{urllib.parse.quote(entity_id, safe=':')}", {}))
    results = payload.get("results") or []
    if not results:
        return None
    result = results[0]
    if not isinstance(result, dict) or result.get("isObsolete"):
        return None
    return {
        "source": "goa",
        "entity_type": "go_term",
        "entity_id": _clean_text(result.get("id") or entity_id),
        "name": _clean_text(result.get("name") or entity_id),
        "aspect": _clean_text(result.get("aspect")),
        "definition": _clean_text((result.get("definition") or {}).get("text") if isinstance(result.get("definition"), dict) else ""),
    }


def _goa_gene_relationship_records(
    resolved: dict[str, Any],
    *,
    taxon_id: str,
    relationship_types: list[str],
    quickgo_api_base: str,
    fetch_json: Any,
    limit: int,
) -> list[dict[str, Any]]:
    payload = fetch_json(
        _url(
            quickgo_api_base,
            "/annotation/search",
            {
                "goId": resolved["entity_id"],
                "taxonId": taxon_id,
                "geneProductType": "protein",
                "limit": str(max(1, limit)),
            },
        )
    )
    requested_relationships = {_normalize_relationship_type(item) for item in relationship_types if _clean_text(item)}
    records: list[dict[str, Any]] = []
    for result in payload.get("results") or []:
        if not isinstance(result, dict):
            continue
        symbol = _clean_text(result.get("symbol")).upper()
        if not symbol:
            continue
        relationship_type = _normalize_relationship_type(result.get("qualifier") or _go_aspect_relationship(result.get("goAspect")))
        if requested_relationships and relationship_type not in requested_relationships:
            continue
        records.append(
            {
                "source": "QuickGO GOA",
                "source_record_id": _clean_text(result.get("id")),
                "entity": {
                    "entity_type": "go_term",
                    "entity_id": resolved["entity_id"],
                    "name": resolved["name"],
                    "aspect": resolved.get("aspect"),
                },
                "gene": symbol,
                "gene_product_id": _clean_text(result.get("geneProductId")),
                "relationship_type": relationship_type,
                "evidence_code": _clean_text(result.get("goEvidence") or result.get("evidenceCode")),
                "evidence_class": _go_evidence_class(result.get("goEvidence")),
                "assigned_by": _clean_text(result.get("assignedBy")),
                "reference": _clean_text(result.get("reference")),
                "taxon_id": result.get("taxonId"),
                "raw_source": "quickgo_annotation",
            }
        )
    return records


def _reactome_search(entity_name: str, *, species: str, reactome_api_base: str, fetch_json: Any) -> list[dict[str, Any]]:
    payload = fetch_json(
        _url(
            reactome_api_base,
            "/search/query",
            {"query": entity_name, "species": species, "types": "Pathway", "pageSize": "10"},
        )
    )
    results: list[dict[str, Any]] = []
    for group in payload.get("results") or []:
        for entry in group.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            if _clean_text(entry.get("exactType") or entry.get("type")) != "Pathway":
                continue
            species_values = entry.get("species") if isinstance(entry.get("species"), list) else []
            if species and species not in species_values:
                continue
            results.append(
                {
                    "source": "reactome",
                    "entity_type": "pathway",
                    "entity_id": _clean_text(entry.get("stId") or entry.get("id")),
                    "name": _strip_markup(entry.get("name")),
                    "species": species_values,
                    "summation": _strip_markup(entry.get("summation")),
                }
            )
    return [candidate for candidate in results if candidate["entity_id"] and candidate["name"]]


def _reactome_pathway_by_id(entity_id: str, *, reactome_api_base: str, fetch_json: Any) -> dict[str, Any] | None:
    payload = fetch_json(_url(reactome_api_base, f"/data/query/{urllib.parse.quote(entity_id, safe=':-')}", {}))
    if not isinstance(payload, dict):
        return None
    if _clean_text(payload.get("schemaClass")) not in {"Pathway", "TopLevelPathway"} and _clean_text(payload.get("className")) not in {"Pathway", "TopLevelPathway"}:
        # Some ContentService responses omit schemaClass for pathways; displayName is still safe to surface.
        pass
    return {
        "source": "reactome",
        "entity_type": "pathway",
        "entity_id": _clean_text(payload.get("stId") or payload.get("stIdVersion") or entity_id),
        "name": _clean_text(payload.get("displayName") or payload.get("name") or entity_id),
        "species": [_clean_text((payload.get("species") or {}).get("displayName") if isinstance(payload.get("species"), dict) else "")],
        "summation": _clean_text(" ".join(item.get("text", "") for item in payload.get("summation", []) if isinstance(item, dict))),
    }


def _reactome_gene_relationship_records(
    resolved: dict[str, Any],
    *,
    relationship_types: list[str],
    reactome_api_base: str,
    fetch_json: Any,
    limit: int,
) -> list[dict[str, Any]]:
    requested_relationships = {_normalize_relationship_type(item) for item in relationship_types if _clean_text(item)}
    payload = fetch_json(_url(reactome_api_base, f"/data/participants/{urllib.parse.quote(resolved['entity_id'], safe=':-')}", {}))
    records: list[dict[str, Any]] = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        for gene in _reactome_genes_from_participant(item):
            relationship_type = "pathway_participant"
            if requested_relationships and relationship_type not in requested_relationships:
                continue
            records.append(
                {
                    "source": "Reactome ContentService",
                    "source_record_id": str(item.get("peDbId") or item.get("dbId") or ""),
                    "entity": {
                        "entity_type": "pathway",
                        "entity_id": resolved["entity_id"],
                        "name": resolved["name"],
                    },
                    "gene": gene["gene"],
                    "gene_product_id": gene.get("gene_product_id") or "",
                    "relationship_type": relationship_type,
                    "evidence_code": "reactome_curated_or_inferred",
                    "evidence_class": "curated_pathway_membership",
                    "assigned_by": "Reactome",
                    "reference": gene.get("reference_url") or "",
                    "raw_source": "reactome_participant",
                }
            )
            if len(records) >= limit:
                return records
    return records


def _kegg_compound_search(entity_name: str, *, kegg_api_base: str, fetch_text: Any) -> list[dict[str, Any]]:
    text = fetch_text(_url(kegg_api_base, f"/find/compound/{urllib.parse.quote(entity_name, safe='')}", {}))
    candidates: list[dict[str, Any]] = []
    for line in text.splitlines():
        if "\t" not in line:
            continue
        raw_id, raw_names = line.split("\t", 1)
        aliases = [_clean_text(part) for part in raw_names.split(";") if _clean_text(part)]
        if not aliases:
            continue
        candidates.append(
            {
                "source": "kegg",
                "entity_type": "chemical",
                "entity_id": _normalize_kegg_compound_id(raw_id),
                "name": aliases[0],
                "synonyms": aliases[1:],
            }
        )
    return [candidate for candidate in candidates if candidate["entity_id"] and candidate["name"]]


def _kegg_compound_by_id(entity_id: str, *, kegg_api_base: str, fetch_text: Any) -> dict[str, Any] | None:
    compound_id = _normalize_kegg_compound_id(entity_id)
    if not compound_id:
        return None
    text = fetch_text(_url(kegg_api_base, f"/get/{urllib.parse.quote(compound_id, safe=':')}", {}))
    entry = _parse_kegg_flat_entry(text)
    names = entry.get("NAME") or []
    if not names:
        return None
    return {
        "source": "kegg",
        "entity_type": "chemical",
        "entity_id": compound_id,
        "name": names[0].rstrip(";"),
        "synonyms": [name.rstrip(";") for name in names[1:]],
        "formula": " ".join(entry.get("FORMULA") or []),
    }


def _kegg_gene_relationship_records(
    resolved: dict[str, Any],
    *,
    relationship_types: list[str],
    kegg_api_base: str,
    fetch_text: Any,
    limit: int,
) -> list[dict[str, Any]]:
    requested_relationships = {_normalize_relationship_type(item) for item in relationship_types if _clean_text(item)}
    relationship_type = "enzyme_associated_with"
    if requested_relationships and relationship_type not in requested_relationships:
        return []
    compound_id = _normalize_kegg_compound_id(resolved.get("entity_id"))
    if not compound_id:
        return []
    enzyme_links = _parse_kegg_links(fetch_text(_url(kegg_api_base, f"/link/enzyme/{urllib.parse.quote(compound_id, safe=':')}", {})))
    enzyme_ids = [_clean_text(target) for _, target in enzyme_links if _clean_text(target).startswith("ec:")]
    records: list[dict[str, Any]] = []
    for enzyme_id in enzyme_ids:
        gene_links = _parse_kegg_links(fetch_text(_url(kegg_api_base, f"/link/hsa/{urllib.parse.quote(enzyme_id, safe=':.')}", {})))
        for _, gene_ref in gene_links:
            gene_ref = _clean_text(gene_ref)
            if not gene_ref.startswith("hsa:"):
                continue
            gene_entry = _parse_kegg_flat_entry(fetch_text(_url(kegg_api_base, f"/get/{urllib.parse.quote(gene_ref, safe=':')}", {})))
            gene = _kegg_gene_symbol(gene_entry, gene_ref)
            if not gene:
                continue
            records.append(
                {
                    "source": "KEGG REST",
                    "source_record_id": f"{compound_id}|{enzyme_id}|{gene_ref}",
                    "entity": {
                        "entity_type": "chemical",
                        "entity_id": compound_id,
                        "name": resolved.get("name"),
                    },
                    "gene": gene,
                    "gene_product_id": gene_ref,
                    "relationship_type": relationship_type,
                    "evidence_code": enzyme_id,
                    "evidence_class": "compound_enzyme_gene_link",
                    "assigned_by": "KEGG",
                    "reference": f"https://www.kegg.jp/entry/{gene_ref}",
                    "enzyme": enzyme_id,
                    "raw_source": "kegg_compound_enzyme_gene_link",
                    "limitations": [
                        "KEGG compound-enzyme links do not specify reaction direction; this record does not distinguish production from consumption.",
                    ],
                }
            )
            if len(records) >= limit:
                return records
    return records


def _hpa_entity_search(
    entity_name: str,
    *,
    entity_type: str,
    hpa_download_base: str,
    fetch_bytes: Any,
) -> list[dict[str, Any]]:
    allowed_types = [entity_type] if entity_type in {"tissue", "cell_type"} else ["tissue", "cell_type"]
    candidates: list[dict[str, Any]] = []
    for candidate_type in allowed_types:
        for row in _hpa_controlled_entity_rows(candidate_type, hpa_download_base=hpa_download_base, fetch_bytes=fetch_bytes):
            name = _clean_text(row.get("Tissue") or row.get("Cell type"))
            if not name:
                continue
            candidate: dict[str, Any] = {
                "source": "hpa",
                "entity_type": candidate_type,
                "entity_id": "",
                "name": name,
            }
            if candidate_type == "tissue":
                candidate["organ"] = _clean_text(row.get("Organ"))
            else:
                candidate["cell_type_group"] = _clean_text(row.get("Cell type group"))
                candidate["cell_type_class"] = _clean_text(row.get("Cell type class"))
            candidates.append(candidate)
    if not entity_name:
        return candidates
    exact = [candidate for candidate in candidates if _candidate_label_matches(candidate, entity_name)]
    if exact:
        return exact
    query_norm = _normalise_label(entity_name)
    return [candidate for candidate in candidates if query_norm and query_norm in _normalise_label(candidate.get("name"))][:10]


def _hpa_controlled_entity_rows(entity_type: str, *, hpa_download_base: str, fetch_bytes: Any) -> list[dict[str, str]]:
    if entity_type == "tissue":
        filename = "rna_tissue_consensus_tissues.tsv.zip"
    elif entity_type == "cell_type":
        filename = "rna_single_cell_type_cell_types.tsv.zip"
    else:
        return []
    data = fetch_bytes(_url(hpa_download_base, f"/{filename}", {}))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        if not names:
            return []
        with archive.open(names[0]) as handle:
            text = handle.read().decode("utf-8")
    return [dict(row) for row in csv.DictReader(io.StringIO(text), delimiter="\t")]


def _hpa_gene_relationship_records(
    resolved: dict[str, Any],
    *,
    relationship_types: list[str],
    hpa_api_base: str,
    fetch_json: Any,
    limit: int,
) -> list[dict[str, Any]]:
    entity_type = resolved.get("entity_type")
    if entity_type not in {"tissue", "cell_type"}:
        return []
    requested_relationships = {_normalize_relationship_type(item) for item in relationship_types if _clean_text(item)}
    query_name = _clean_text(resolved.get("name"))
    if not query_name:
        return []
    category_field = "tissue_category_rna" if entity_type == "tissue" else "cell_type_category_rna"
    category_values = (
        "Tissue enriched,Group enriched,Tissue enhanced"
        if entity_type == "tissue"
        else "Cell type enriched,Group enriched,Cell type enhanced"
    )
    payload = fetch_json(
        _url(
            hpa_api_base,
            "/search_download.php",
            {
                "search": f"{category_field}:{query_name};{category_values}",
                "format": "json",
                "columns": "g,gs,eg,gd,rnats,rnatd,rnatss,rnatsm,rnascs,rnascd,rnascss,rnascsm",
                "compress": "no",
            },
        )
    )
    records: list[dict[str, Any]] = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        gene = _clean_text(item.get("Gene")).upper()
        ensembl = _clean_text(item.get("Ensembl"))
        if not gene:
            continue
        if entity_type == "tissue":
            specificity = _clean_text(item.get("RNA tissue specificity"))
            distribution = _clean_text(item.get("RNA tissue distribution"))
            score = _safe_float(item.get("RNA tissue specificity score"))
            expression = _hpa_expression_for_entity(item.get("RNA tissue specific nTPM"), query_name)
            relationship_type = _hpa_tissue_relationship_type(specificity)
            evidence_class = "hpa_tissue_rna_specificity"
            expression_unit = "nTPM"
        else:
            specificity = _clean_text(item.get("RNA single cell type specificity"))
            distribution = _clean_text(item.get("RNA single cell type distribution"))
            score = _safe_float(item.get("RNA single cell type specificity score"))
            expression = _hpa_expression_for_entity(item.get("RNA single cell type specific nCPM"), query_name)
            relationship_type = _hpa_cell_type_relationship_type(specificity)
            evidence_class = "hpa_single_cell_type_rna_specificity"
            expression_unit = "nCPM"
        if requested_relationships and relationship_type not in requested_relationships:
            continue
        records.append(
            {
                "source": "Human Protein Atlas",
                "source_record_id": f"{ensembl or gene}|{query_name}",
                "entity": {
                    "entity_type": entity_type,
                    "entity_id": "",
                    "name": query_name,
                },
                "gene": gene,
                "gene_product_id": ensembl,
                "gene_description": _clean_text(item.get("Gene description")),
                "gene_synonyms": [_clean_text(value) for value in item.get("Gene synonym") or [] if _clean_text(value)],
                "relationship_type": relationship_type,
                "evidence_code": specificity,
                "evidence_class": evidence_class,
                "assigned_by": "Human Protein Atlas",
                "reference": f"https://www.proteinatlas.org/{urllib.parse.quote(ensembl or gene, safe='')}",
                "expression": {
                    "entity_name": query_name,
                    "value": expression,
                    "unit": expression_unit,
                    "distribution": distribution,
                },
                "specificity": specificity,
                "specificity_score": score,
                "raw_source": "hpa_search_download",
                "limitations": [
                    "Human Protein Atlas RNA specificity records describe expression enrichment, not causal mechanism.",
                ],
            }
        )
        if len(records) >= limit:
            break
    return records


def _hpa_expression_for_entity(values: Any, entity_name: str) -> float | None:
    if not isinstance(values, dict):
        return None
    target = _normalise_label(entity_name)
    for key, value in values.items():
        if _normalise_label(key) == target:
            return _safe_float(value)
    return None


def _hpa_tissue_relationship_type(specificity: str) -> str:
    return {
        "Tissue enriched": "tissue_enriched_expression",
        "Group enriched": "tissue_group_enriched_expression",
        "Tissue enhanced": "tissue_enhanced_expression",
    }.get(specificity, "tissue_expression")


def _hpa_cell_type_relationship_type(specificity: str) -> str:
    return {
        "Cell type enriched": "cell_type_enriched_expression",
        "Group enriched": "cell_type_group_enriched_expression",
        "Cell type enhanced": "cell_type_enhanced_expression",
    }.get(specificity, "cell_type_expression")


def _chembl_molecule_search(entity_name: str, *, chembl_api_base: str, fetch_json: Any) -> list[dict[str, Any]]:
    if not entity_name:
        return []
    payload = fetch_json(
        _url(
            chembl_api_base,
            "/molecule/search.json",
            {"q": entity_name, "limit": "10"},
        )
    )
    candidates = [_chembl_molecule_entity(item) for item in payload.get("molecules") or [] if isinstance(item, dict)]
    return [candidate for candidate in candidates if candidate.get("entity_id")]


def _chembl_molecule_by_id(entity_id: str, *, chembl_api_base: str, fetch_json: Any) -> dict[str, Any] | None:
    chembl_id = _normalize_chembl_id(entity_id)
    if not chembl_id:
        return None
    payload = fetch_json(_url(chembl_api_base, f"/molecule/{urllib.parse.quote(chembl_id, safe='')}.json", {}))
    if not isinstance(payload, dict) or not _clean_text(payload.get("molecule_chembl_id")):
        return None
    return _chembl_molecule_entity(payload)


def _chembl_molecule_entity(payload: dict[str, Any]) -> dict[str, Any]:
    molecule_id = _normalize_chembl_id(payload.get("molecule_chembl_id"))
    hierarchy = payload.get("molecule_hierarchy") if isinstance(payload.get("molecule_hierarchy"), dict) else {}
    synonyms = _chembl_molecule_synonyms(payload.get("molecule_synonyms") or [])
    pref_name = _clean_text(payload.get("pref_name"))
    return {
        "source": "chembl",
        "entity_type": "drug",
        "entity_id": molecule_id,
        "name": pref_name or molecule_id,
        "synonyms": synonyms,
        "parent_molecule_chembl_id": _normalize_chembl_id((hierarchy or {}).get("parent_chembl_id")),
        "active_molecule_chembl_id": _normalize_chembl_id((hierarchy or {}).get("active_chembl_id")),
        "max_phase": _safe_float(payload.get("max_phase")),
        "first_approval": payload.get("first_approval"),
        "therapeutic_flag": payload.get("therapeutic_flag"),
        "molecule_type": _clean_text(payload.get("molecule_type")),
    }


def _chembl_molecule_synonyms(values: list[Any]) -> list[str]:
    synonyms: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        for key in ("molecule_synonym", "synonyms"):
            synonym = _clean_text(value.get(key))
            if synonym and synonym not in synonyms:
                synonyms.append(synonym)
    return synonyms


def _chembl_drug_gene_relationship_records(
    resolved: dict[str, Any],
    *,
    relationship_types: list[str],
    chembl_api_base: str,
    fetch_json: Any,
    limit: int,
) -> list[dict[str, Any]]:
    requested_relationships = {_normalize_relationship_type(item) for item in relationship_types if _clean_text(item)}
    relationship_type = "drug_target_mechanism"
    if requested_relationships and relationship_type not in requested_relationships:
        return []
    molecule_ids = [
        _normalize_chembl_id(resolved.get("parent_molecule_chembl_id")),
        _normalize_chembl_id(resolved.get("active_molecule_chembl_id")),
        _normalize_chembl_id(resolved.get("entity_id")),
    ]
    records: list[dict[str, Any]] = []
    for molecule_id in [item for index, item in enumerate(molecule_ids) if item and item not in molecule_ids[:index]]:
        mechanisms = _chembl_mechanisms_for_molecule(molecule_id, chembl_api_base=chembl_api_base, fetch_json=fetch_json, limit=max(1, limit))
        for mechanism in mechanisms:
            target_id = _normalize_chembl_id(mechanism.get("target_chembl_id"))
            if not target_id:
                continue
            target = _chembl_target_by_id(target_id, chembl_api_base=chembl_api_base, fetch_json=fetch_json)
            for component in _chembl_target_gene_components(target):
                records.append(
                    {
                        "source": "ChEMBL",
                        "source_record_id": f"{molecule_id}|{mechanism.get('mec_id') or mechanism.get('record_id')}|{target_id}|{component['gene']}",
                        "entity": {
                            "entity_type": "drug",
                            "entity_id": resolved.get("entity_id"),
                            "name": resolved.get("name"),
                            "parent_molecule_chembl_id": resolved.get("parent_molecule_chembl_id") or "",
                        },
                        "gene": component["gene"],
                        "gene_product_id": component.get("accession") or "",
                        "gene_description": component.get("description") or "",
                        "relationship_type": relationship_type,
                        "evidence_code": _clean_text(mechanism.get("action_type") or mechanism.get("mechanism_of_action")),
                        "evidence_class": "chembl_drug_mechanism_target",
                        "assigned_by": "ChEMBL",
                        "reference": f"https://www.ebi.ac.uk/chembl/compound_report_card/{molecule_id}/",
                        "mechanism": {
                            "mechanism_of_action": _clean_text(mechanism.get("mechanism_of_action")),
                            "action_type": _clean_text(mechanism.get("action_type")),
                            "direct_interaction": mechanism.get("direct_interaction"),
                            "molecular_mechanism": mechanism.get("molecular_mechanism"),
                            "disease_efficacy": mechanism.get("disease_efficacy"),
                            "max_phase": mechanism.get("max_phase"),
                            "target_chembl_id": target_id,
                            "target_name": _clean_text((target or {}).get("pref_name")),
                            "target_type": _clean_text((target or {}).get("target_type")),
                            "target_organism": _clean_text((target or {}).get("organism")),
                            "mechanism_refs": _chembl_mechanism_refs(mechanism.get("mechanism_refs") or []),
                        },
                        "raw_source": "chembl_mechanism_target",
                        "limitations": [
                            "ChEMBL mechanism records describe curated drug-target mechanism relationships; they do not establish disease-specific efficacy unless disease context is supplied by another capability.",
                        ],
                    }
                )
                if len(records) >= limit:
                    return records
    return records


def _chembl_mechanisms_for_molecule(molecule_id: str, *, chembl_api_base: str, fetch_json: Any, limit: int) -> list[dict[str, Any]]:
    payload = fetch_json(
        _url(
            chembl_api_base,
            "/mechanism.json",
            {"molecule_chembl_id": molecule_id, "limit": str(max(1, limit))},
        )
    )
    return [item for item in payload.get("mechanisms") or [] if isinstance(item, dict)]


def _chembl_target_by_id(target_id: str, *, chembl_api_base: str, fetch_json: Any) -> dict[str, Any]:
    payload = fetch_json(_url(chembl_api_base, f"/target/{urllib.parse.quote(target_id, safe='')}.json", {}))
    return payload if isinstance(payload, dict) else {}


def _chembl_target_gene_components(target: dict[str, Any]) -> list[dict[str, str]]:
    components: list[dict[str, str]] = []
    if _clean_text(target.get("organism")) != "Homo sapiens":
        return components
    for component in target.get("target_components") or []:
        if not isinstance(component, dict):
            continue
        gene = _chembl_component_gene_symbol(component)
        if not gene:
            continue
        components.append(
            {
                "gene": gene,
                "accession": _clean_text(component.get("accession")),
                "description": _clean_text(component.get("component_description")),
            }
        )
    return components


def _chembl_component_gene_symbol(component: dict[str, Any]) -> str:
    for synonym in component.get("target_component_synonyms") or []:
        if not isinstance(synonym, dict):
            continue
        if _clean_text(synonym.get("syn_type")) == "GENE_SYMBOL":
            symbol = _clean_text(synonym.get("component_synonym")).upper()
            if symbol:
                return symbol
    return ""


def _chembl_mechanism_refs(values: list[Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        ref = {
            "ref_type": _clean_text(value.get("ref_type")),
            "ref_id": _clean_text(value.get("ref_id")),
            "ref_url": _clean_text(value.get("ref_url")),
        }
        if any(ref.values()):
            refs.append(ref)
    return refs


def _parse_kegg_links(text: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for line in text.splitlines():
        if "\t" not in line:
            continue
        source, target = line.split("\t", 1)
        links.append((_clean_text(source), _clean_text(target)))
    return links


def _parse_kegg_flat_entry(text: str) -> dict[str, list[str]]:
    entry: dict[str, list[str]] = {}
    current_key = ""
    for line in text.splitlines():
        if not line.strip():
            continue
        key = line[:12].strip()
        value = line[12:].strip()
        if key:
            current_key = key
            entry.setdefault(current_key, []).append(value)
        elif current_key:
            entry.setdefault(current_key, []).append(value)
    return entry


def _kegg_gene_symbol(entry: dict[str, list[str]], gene_ref: str) -> str:
    symbol_values = entry.get("SYMBOL") or []
    for value in symbol_values:
        first = _clean_text(value.split(",", 1)[0]).upper()
        if first:
            return first
    return _clean_text(gene_ref.split(":", 1)[-1]).upper()


def _reactome_genes_from_participant(item: dict[str, Any]) -> list[dict[str, str]]:
    genes: list[dict[str, str]] = []
    for ref in item.get("refEntities") or []:
        if not isinstance(ref, dict):
            continue
        display = _clean_text(ref.get("displayName"))
        identifier = _clean_text(ref.get("identifier"))
        symbol = _gene_symbol_from_reactome_ref(display)
        if not symbol:
            continue
        genes.append(
            {
                "gene": symbol,
                "gene_product_id": _clean_text(ref.get("stId") or identifier),
                "reference_url": _clean_text(ref.get("url")),
            }
        )
    return genes


def _gene_symbol_from_reactome_ref(display: str) -> str:
    clean = _clean_text(display)
    if not clean:
        return ""
    candidate = clean.split()[-1].upper()
    if candidate in {"HOMO", "SAPIENS"}:
        return ""
    if TOKEN_RE.fullmatch(candidate) and not candidate.startswith(("ENSG", "P", "Q")):
        return candidate
    return ""
