from __future__ import annotations

import csv
import re
import urllib.error
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ....runtime.libraries import manager as library_manager
from ....runtime.paths import genomi_data_root

from ._base import (
    HPO_DISEASE_ANNOTATION_URL,
    HPO_GENE_ANNOTATION_URL,
    HPO_ID_RE,
    PRIMARY_GENE_DISEASE_CLASSIFICATIONS,
    _any_field_matches,
    _clean_text,
    _dedupe,
    _disease_id,
    _extract_disease_ids,
    _normalize_disease_ids,
    _normalize_diseases,
    _normalize_gene,
    _normalize_genes,
    _normalize_hpo_ids,
    _strip_disease_ids,
)


def retrieve_primary_gene_disease_associations(
    *,
    genes: Iterable[str],
    gencc_file: str | Path | None = None,
    download_gencc: bool = True,
    classifications: Iterable[str] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    normalized_genes = _normalize_genes(genes or [])
    if not normalized_genes:
        raise ValueError("phenotype.retrieve_gene_disease_associations requires genes")
    allowed_classifications = _normalize_classifications(classifications or PRIMARY_GENE_DISEASE_CLASSIFICATIONS)
    try:
        gencc_path = _resolve_gencc_file(
            gencc_file=gencc_file,
            download_gencc=download_gencc,
        )
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return _primary_gene_disease_response(
            genes=normalized_genes,
            classifications=allowed_classifications,
            status="source_unavailable",
            coverage_state="out_of_scope_for_input",
            associations=[],
            source_file=None,
            source_coverage={
                "sources_consulted_and_empty": [],
                "sources_consulted_but_unavailable": [{"source": "GenCC submissions TSV", "error": str(exc)}],
                "sources_not_integrated": ["OMIM gene map", "Orphanet gene-disease primary association export"],
            },
        )
    if gencc_path is None:
        if gencc_file is None and not download_gencc:
            request = library_manager.missing_request(
                "gencc",
                intent=f"primary gene-disease associations for {', '.join(normalized_genes[:5])}",
                operation="phenotype.retrieve_gene_disease_associations",
            )
            response = _primary_gene_disease_response(
                genes=normalized_genes,
                classifications=allowed_classifications,
                status=request["status"],
                coverage_state="out_of_scope_for_input",
                associations=[],
                source_file=None,
                source_coverage={
                    "sources_consulted_and_empty": [],
                    "sources_consulted_but_unavailable": [{"source": "GenCC submissions TSV", "error": "gencc library is not installed"}],
                    "sources_not_integrated": ["OMIM gene map", "Orphanet gene-disease primary association export"],
                },
            )
            response.update(
                {
                    "tool_will_work": False,
                    "missing_library": request["missing_library"],
                    "how_it_helps": request["how_it_helps"],
                    "ask_user": request["ask_user"],
                    "library_install_request": request,
                }
            )
            return response
        return _primary_gene_disease_response(
            genes=normalized_genes,
            classifications=allowed_classifications,
            status="source_not_available",
            coverage_state="out_of_scope_for_input",
            associations=[],
            source_file=None,
            source_coverage={
                "sources_consulted_and_empty": [],
                "sources_consulted_but_unavailable": [],
                "sources_not_integrated": ["GenCC submissions TSV", "OMIM gene map", "Orphanet gene-disease primary association export"],
            },
        )
    associations = _gencc_primary_gene_disease_associations(
        gencc_path,
        normalized_genes,
        allowed_classifications=allowed_classifications,
        limit=max(1, int(limit or 100)),
    )
    status = "completed" if associations else "no_primary_gene_disease_associations"
    coverage_state = "data_returned" if associations else "in_scope_empty"
    return _primary_gene_disease_response(
        genes=normalized_genes,
        classifications=allowed_classifications,
        status=status,
        coverage_state=coverage_state,
        associations=associations,
        source_file=str(gencc_path),
        source_coverage={
            "sources_consulted_and_empty": [] if associations else ["GenCC submissions TSV"],
            "sources_consulted_but_unavailable": [],
            "sources_not_integrated": ["OMIM gene map", "Orphanet gene-disease primary association export"],
        },
    )


def _hpo_gene_annotation_context(
    query: dict[str, Any],
    *,
    use_hpo_annotations: bool,
    download_hpo_annotations: bool,
    hpo_gene_file: str | Path | None,
    limit: int,
) -> dict[str, Any]:
    if not use_hpo_annotations:
        return {"status": "not_requested", "source_records": [], "error": None}
    if not query.get("hpo_ids"):
        return {"status": "not_applicable_no_hpo_ids", "source_records": [], "error": None}
    if hpo_gene_file is None and not download_hpo_annotations and not _default_hpo_gene_file().exists():
        return _library_install_annotation_context(
            "hpo",
            intent=f"HPO phenotype-to-gene matching for {', '.join(query.get('genes') or [])}",
            operation="phenotype.compare_gene_hpo_evidence",
            queried_hpo_ids=query.get("hpo_ids") or [],
        )
    try:
        annotation_path = _resolve_hpo_gene_file(
            hpo_gene_file=hpo_gene_file,
            download_hpo_annotations=download_hpo_annotations,
        )
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return {"status": "unavailable", "source_records": [], "error": str(exc)}
    if annotation_path is None:
        return {"status": "missing_local_annotation_file", "source_records": [], "error": None}
    try:
        records = _hpo_records_for_query(annotation_path, query, limit=max(1, int(limit or 25)))
    except OSError as exc:
        return {"status": "unavailable", "source_records": [], "error": str(exc)}
    return {
        "status": "searched",
        "source_records": records,
        "error": None,
        "annotation_file": str(annotation_path),
        "matched_record_count": len(records),
        "queried_hpo_ids": query.get("hpo_ids") or [],
    }


def _hpo_disease_annotation_context(
    query: dict[str, Any],
    *,
    use_hpo_annotations: bool,
    download_hpo_annotations: bool,
    hpo_disease_file: str | Path | None,
    use_primary_gene_disease: bool,
    download_primary_gene_disease: bool,
    gencc_file: str | Path | None,
    limit: int,
) -> dict[str, Any]:
    if not use_hpo_annotations:
        return {"status": "not_requested", "source_records": [], "error": None}
    if not query.get("hpo_ids"):
        return {"status": "not_applicable_no_hpo_ids", "source_records": [], "error": None}
    if hpo_disease_file is None and not download_hpo_annotations and not _default_hpo_disease_file().exists():
        return _library_install_annotation_context(
            "hpo",
            intent="HPO disease phenotype matching for supplied diseases or gene-derived disease candidates",
            operation="phenotype.compare_disease_evidence",
            queried_hpo_ids=query.get("hpo_ids") or [],
        )
    try:
        disease_path = _resolve_public_annotation_file(
            annotation_file=hpo_disease_file,
            cache_name="phenotype.hpoa",
            download_annotations=download_hpo_annotations,
        )
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return {"status": "unavailable", "source_records": [], "error": str(exc)}
    if disease_path is None:
        return {"status": "missing_local_disease_annotation_file", "source_records": [], "error": None}
    try:
        needs_primary_gene_disease = bool(query.get("genes")) and not bool(query.get("candidate_diseases"))
        primary_context = _primary_gene_disease_context(
            query.get("genes") or [],
            use_primary_gene_disease=use_primary_gene_disease,
            download_primary_gene_disease=download_primary_gene_disease,
            gencc_file=gencc_file,
            limit=max(1, int(limit or 25)),
        ) if needs_primary_gene_disease else {
            "status": "not_applicable_supplied_candidates" if query.get("candidate_diseases") else "not_applicable_no_genes",
            "associations": [],
            "coverage_state": "out_of_scope_for_input",
        }
        if needs_primary_gene_disease and primary_context.get("coverage_state") == "out_of_scope_for_input":
            return {
                "status": "primary_gene_disease_source_unavailable",
                "source_records": [],
                "error": primary_context.get("error"),
                "annotation_file": str(disease_path),
                "primary_gene_disease_evidence": primary_context,
                "matched_record_count": 0,
                "queried_hpo_ids": query.get("hpo_ids") or [],
            }
        gene_disease_index = _primary_gene_disease_index(primary_context.get("associations") or [])
        if needs_primary_gene_disease and not gene_disease_index:
            records = []
        elif gene_disease_index:
            records = _hpo_disease_records_for_query(
                disease_path,
                query,
                gene_disease_index=gene_disease_index,
                limit=max(1, int(limit or 25)),
            )
        else:
            records = _hpo_disease_records_for_query(
                disease_path,
                query,
                gene_disease_index={},
                limit=max(1, int(limit or 25)),
            )
    except OSError as exc:
        return {"status": "unavailable", "source_records": [], "error": str(exc)}
    return {
        "status": "searched",
        "source_records": records,
        "error": None,
        "annotation_file": str(disease_path),
        "primary_gene_disease_evidence": primary_context,
        "matched_record_count": len(records),
        "queried_hpo_ids": query.get("hpo_ids") or [],
    }


def _resolve_hpo_gene_file(
    *,
    hpo_gene_file: str | Path | None,
    download_hpo_annotations: bool,
) -> Path | None:
    return _resolve_public_annotation_file(
        annotation_file=hpo_gene_file,
        cache_name="phenotype_to_genes.txt",
        download_annotations=download_hpo_annotations,
    )


def _default_hpo_gene_file() -> Path:
    return genomi_data_root() / "resources" / "hpo" / "phenotype_to_genes.txt"


def _default_hpo_disease_file() -> Path:
    return genomi_data_root() / "resources" / "hpo" / "phenotype.hpoa"


def _library_install_annotation_context(
    library: str,
    *,
    intent: str,
    operation: str,
    queried_hpo_ids: list[str],
) -> dict[str, Any]:
    request = library_manager.missing_request(library, intent=intent, operation=operation)
    return {
        "status": request["status"],
        "source_records": [],
        "error": None,
        "matched_record_count": 0,
        "queried_hpo_ids": queried_hpo_ids,
        "tool_will_work": False,
        "library_install_request": request,
        "missing_library": request["missing_library"],
        "how_it_helps": request["how_it_helps"],
        "ask_user": request["ask_user"],
    }


def _materialize_annotation(
    *,
    cache_path: Path,
    library: str,
    download: bool,
) -> Path | None:
    """Resolve a registry-managed annotation cache. A present file is returned
    with no network round-trip (the runtime hot path); when ``download`` is set
    (the installer / explicit fetch), the central manager is the single code
    path that fetches it — agents reach uninstalled libraries via the install
    request, not a silent download."""
    if cache_path.exists():
        return cache_path
    if not download:
        return None
    library_manager.refresh(library)
    return cache_path if cache_path.exists() else None


def _resolve_public_annotation_file(
    *,
    annotation_file: str | Path | None,
    cache_name: str,
    download_annotations: bool,
) -> Path | None:
    if annotation_file:
        path = Path(annotation_file).expanduser()
        return path if path.exists() else None
    return _materialize_annotation(
        cache_path=genomi_data_root() / "resources" / "hpo" / cache_name,
        library="hpo",
        download=download_annotations,
    )


def _resolve_gencc_file(
    *,
    gencc_file: str | Path | None,
    download_gencc: bool,
) -> Path | None:
    if gencc_file:
        path = Path(gencc_file).expanduser()
        return path if path.exists() else None
    return _materialize_annotation(
        cache_path=genomi_data_root() / "resources" / "gencc" / "gencc-submissions.tsv",
        library="gencc",
        download=download_gencc,
    )


def _primary_gene_disease_context(
    genes: Iterable[str],
    *,
    use_primary_gene_disease: bool,
    download_primary_gene_disease: bool,
    gencc_file: str | Path | None,
    limit: int,
) -> dict[str, Any]:
    if not use_primary_gene_disease:
        return {
            "status": "not_requested",
            "coverage_state": "out_of_scope_for_input",
            "associations": [],
            "source_coverage": {
                "sources_consulted_and_empty": [],
                "sources_consulted_but_unavailable": [],
                "sources_not_integrated": ["GenCC submissions TSV"],
            },
        }
    return retrieve_primary_gene_disease_associations(
        genes=genes,
        gencc_file=gencc_file,
        download_gencc=download_primary_gene_disease,
        limit=limit,
    )


def _primary_gene_disease_response(
    *,
    genes: list[str],
    classifications: list[str],
    status: str,
    coverage_state: str,
    associations: list[dict[str, Any]],
    source_file: str | None,
    source_coverage: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "genomi-primary-gene-disease-associations-v1",
        "status": status,
        "coverage_state": coverage_state,
        "agent_decision_required": True,
        "query": {
            "genes": genes,
            "classifications": classifications,
        },
        "associations": associations,
        "associations_by_gene": _group_associations_by_gene(associations),
        "coverage": {
            "source": "GenCC submissions TSV",
            "source_file": source_file,
            "genes_queried": len(genes),
            "association_count": len(associations),
        },
        "source_coverage": source_coverage,
        "decision_boundary": (
            "This operation retrieves primary gene-disease associations from declared sources. "
            "It does not diagnose, rank phenotypes, or ingest agent-located evidence."
        ),
        "telemetry": {
            "tool_family": "gene_disease",
            "returned_answer": False,
            "agent_decision_required": True,
            "records_examined": len(associations),
            "candidate_records_found": len(associations),
        },
    }


def _group_associations_by_gene(associations: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for association in associations:
        grouped.setdefault(str(association.get("gene") or ""), []).append(association)
    return grouped


def _gencc_primary_gene_disease_associations(
    path: Path,
    genes: list[str],
    *,
    allowed_classifications: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    requested = {gene.upper() for gene in _normalize_genes(genes)}
    allowed = {classification.casefold() for classification in allowed_classifications}
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _iter_gencc_rows(path):
        gene = _normalize_gene(row.get("gene_symbol"))
        if not gene or gene not in requested:
            continue
        classification = _clean_text(row.get("classification_title"))
        if classification.casefold() not in allowed:
            continue
        disease_name = _clean_text(row.get("disease_title") or row.get("submitted_as_disease_name") or row.get("disease_original_title"))
        identifiers = _gencc_disease_identifiers(row)
        if not disease_name or not identifiers:
            continue
        inheritance = _clean_text(row.get("moi_title") or row.get("submitted_as_moi_name"))
        primary_identifier = next((identifier for identifier in identifiers if identifier.startswith("OMIM:")), identifiers[0])
        key = (gene, primary_identifier, inheritance.casefold())
        association = grouped.setdefault(
            key,
            {
                "gene": gene,
                "disease_name": disease_name,
                "disease_identifiers": identifiers,
                "classification": classification,
                "classifications": [],
                "mode_of_inheritance": inheritance,
                "submitters": [],
                "source": "GenCC",
                "source_url": _clean_text(row.get("submitted_as_public_report_url")) or "https://thegencc.org/",
                "source_urls": [],
                "pmids": [],
                "submitted_as_date": _clean_text(row.get("submitted_as_date")),
                "record_ids": [],
                "record_id": _clean_text(row.get("sgc_id") or row.get("uuid") or f"gencc:{gene}:{disease_name}"),
                "enumeration_scope": "primary_gene_disease_index",
            }
        )
        association["disease_identifiers"] = _dedupe([*association["disease_identifiers"], *identifiers])
        association["classifications"] = _dedupe([*association["classifications"], classification])
        if _classification_priority(classification) < _classification_priority(association.get("classification")):
            association["classification"] = classification
        submitter = _clean_text(row.get("submitter_title") or row.get("submitted_as_submitter_name"))
        if submitter:
            association["submitters"] = _dedupe([*association["submitters"], submitter])
        source_url = _clean_text(row.get("submitted_as_public_report_url")) or "https://thegencc.org/"
        association["source_urls"] = _dedupe([*association["source_urls"], source_url])
        association["pmids"] = _dedupe([*association["pmids"], *_split_pmids(row.get("submitted_as_pmids"))])
        record_id = _clean_text(row.get("sgc_id") or row.get("uuid") or f"gencc:{gene}:{disease_name}")
        association["record_ids"] = _dedupe([*association["record_ids"], record_id])
    associations = sorted(
        grouped.values(),
        key=lambda item: (
            item.get("gene", ""),
            _classification_priority(item.get("classification")),
            item.get("disease_name", "").casefold(),
            item.get("mode_of_inheritance", "").casefold(),
        ),
    )
    return associations[:limit]


def _iter_gencc_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            yield {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}


def _gencc_disease_identifiers(row: dict[str, str]) -> list[str]:
    identifiers: list[str] = []
    for key in ("disease_curie", "disease_original_curie", "submitted_as_disease_id"):
        value = _clean_text(row.get(key))
        if not value:
            continue
        identifiers.extend(_normalize_disease_ids([value]))
    return _dedupe(identifiers)


def _normalize_classifications(classifications: Iterable[str]) -> list[str]:
    values = [_clean_text(item) for item in classifications if _clean_text(item)]
    return values or list(PRIMARY_GENE_DISEASE_CLASSIFICATIONS)


def _classification_priority(classification: Any) -> int:
    order = {"definitive": 0, "strong": 1}
    return order.get(_clean_text(classification).casefold(), 10)


def _split_pmids(value: Any) -> list[str]:
    text = _clean_text(value)
    if not text:
        return []
    return _dedupe(re.findall(r"PMID:?\s*(\d+)", text, flags=re.I) or re.findall(r"\b\d{5,}\b", text))


def _primary_gene_disease_index(associations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for association in associations:
        gene = _normalize_gene(association.get("gene"))
        disease_name = _clean_text(association.get("disease_name"))
        for disease_id in _normalize_disease_ids(association.get("disease_identifiers") or []):
            item = index.setdefault(disease_id, {"genes": [], "association_types": [], "sources": [], "disease_name": disease_name})
            item["genes"] = _dedupe([*item["genes"], gene])
            item["association_types"] = _dedupe([*item["association_types"], association.get("classification")])
            item["sources"] = _dedupe([*item["sources"], "GenCC"])
            item["enumeration_scope"] = "primary_gene_disease_index"
    return index


def _hpo_records_for_query(path: Path, query: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    requested_ids = {str(item).upper() for item in query.get("hpo_ids") or []}
    candidate_genes = {str(item).upper() for item in query.get("genes") or []}
    records: list[dict[str, Any]] = []
    for row in _iter_hpo_gene_rows(path):
        hpo_id = str(row.get("hpo_id") or "").upper()
        gene = str(row.get("gene") or "").upper()
        if not hpo_id or not gene:
            continue
        if hpo_id not in requested_ids:
            continue
        if candidate_genes and gene not in candidate_genes:
            continue
        phenotype_name = _clean_text(row.get("phenotype") or hpo_id)
        finding = f"HPO annotation links {gene} to {hpo_id} {phenotype_name}."
        records.append(
            {
                "record_id": f"hpo:{gene}:{hpo_id}",
                "source_id": "hpo",
                "source_type": "HPO phenotype-gene annotation",
                "source_title": "Human Phenotype Ontology phenotype-to-gene annotations",
                "source_url": HPO_GENE_ANNOTATION_URL,
                "finding": finding,
                "genes": [gene],
                "phenotypes": [phenotype_name],
                "hpo_ids": [hpo_id],
                "verified_fields": {
                    "genes": [gene],
                    "phenotypes": [phenotype_name],
                    "hpo_ids": [hpo_id],
                },
                "support_spans": [
                    {"field": "gene", "value": gene, "source_text": finding},
                    {"field": "hpo_id", "value": hpo_id, "source_text": finding},
                ],
            }
        )
        if len(records) >= limit * max(1, len(candidate_genes) or 1):
            break
    return records


def _iter_hpo_gene_rows(path: Path) -> Iterable[dict[str, str]]:
    header: list[str] | None = None
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            lower_cols = [col.strip().lower() for col in cols]
            if header is None and any(name in lower_cols for name in ("hpo-id", "hpo_id", "hpo term id", "hpo term name", "entrez-gene-symbol", "gene_symbol")):
                header = lower_cols
                continue
            parsed = _parse_hpo_gene_row(cols, header)
            if parsed:
                yield parsed


def _parse_hpo_gene_row(cols: list[str], header: list[str] | None) -> dict[str, str] | None:
    if header:
        by_name = {name: cols[index] for index, name in enumerate(header) if index < len(cols)}
        hpo_id = by_name.get("hpo-id") or by_name.get("hpo_id") or by_name.get("hpo term id")
        phenotype_name = by_name.get("hpo-name") or by_name.get("hpo_name") or by_name.get("hpo term name")
        gene = by_name.get("entrez-gene-symbol") or by_name.get("gene_symbol") or by_name.get("gene symbol")
        if hpo_id and gene:
            return {"hpo_id": hpo_id, "phenotype": phenotype_name or hpo_id, "gene": gene}
    hpo_index = next((index for index, value in enumerate(cols) if HPO_ID_RE.fullmatch(value.strip())), None)
    if hpo_index is None:
        return None
    if hpo_index == 0 and len(cols) >= 4:
        return {"hpo_id": cols[0], "phenotype": cols[1], "gene": cols[3]}
    if hpo_index == 2 and len(cols) >= 4:
        return {"hpo_id": cols[2], "phenotype": cols[3], "gene": cols[1]}
    if len(cols) >= 4:
        gene = cols[1] if hpo_index >= 3 else cols[-1]
        phenotype = cols[hpo_index + 1] if hpo_index + 1 < len(cols) else cols[hpo_index]
        return {"hpo_id": cols[hpo_index], "phenotype": phenotype, "gene": gene}
    return None


def _hpo_disease_records_for_query(
    path: Path,
    query: dict[str, Any],
    *,
    gene_disease_index: dict[str, dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    requested_hpo_ids = {str(item).upper() for item in query.get("hpo_ids") or []}
    candidate_values = list(query.get("candidate_diseases") or [])
    candidate_ids = set(_extract_disease_ids(candidate_values))
    candidate_names = _normalize_diseases(_strip_disease_ids(value) for value in candidate_values)
    gene_disease_ids = set(gene_disease_index)
    aggregate: dict[str, dict[str, Any]] = {}
    has_structural_filter = bool(candidate_ids or candidate_names or gene_disease_ids)
    for row in _iter_hpo_disease_rows(path):
        disease_id = _disease_id(row.get("disease_id"))
        disease_name = _clean_text(row.get("disease_name"))
        hpo_id = str(row.get("hpo_id") or "").upper()
        if not disease_id or not disease_name or not hpo_id:
            continue
        if gene_disease_ids and disease_id not in gene_disease_ids:
            continue
        if candidate_ids and disease_id not in candidate_ids:
            continue
        if candidate_names and not (disease_id in candidate_ids or _any_field_matches(disease_name, candidate_names)):
            continue
        if not has_structural_filter and requested_hpo_ids and hpo_id not in requested_hpo_ids:
            continue
        item = aggregate.setdefault(
            disease_id,
            {
                "disease_id": disease_id,
                "disease_name": disease_name,
                "hpo_ids": [],
                "matched_hpo_ids": [],
                "references": [],
                "genes": gene_disease_index.get(disease_id, {}).get("genes", []),
                "association_types": gene_disease_index.get(disease_id, {}).get("association_types", []),
                "enumeration_scope": gene_disease_index.get(disease_id, {}).get("enumeration_scope"),
            },
        )
        item["hpo_ids"] = _normalize_hpo_ids([*item["hpo_ids"], hpo_id])
        if hpo_id in requested_hpo_ids:
            item["matched_hpo_ids"] = _normalize_hpo_ids([*item["matched_hpo_ids"], hpo_id])
        item["references"] = _dedupe([*item["references"], _clean_text(row.get("reference"))])

    ranked = sorted(
        aggregate.values(),
        key=lambda item: (
            -_hpo_match_density(item),
            -len(item["matched_hpo_ids"]),
            len(item["hpo_ids"]) or 10**9,
            item["disease_name"].casefold(),
        ),
    )
    if requested_hpo_ids:
        ranked = [item for item in ranked if item["matched_hpo_ids"]]
    return [_hpo_disease_source_record(item) for item in ranked[: max(1, limit)]]


def _hpo_match_density(item: dict[str, Any]) -> float:
    profile_count = len(item.get("hpo_ids") or [])
    if not profile_count:
        return 0.0
    return len(item.get("matched_hpo_ids") or []) / profile_count


def _iter_hpo_disease_rows(path: Path) -> Iterable[dict[str, str]]:
    header: list[str] | None = None
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            lower_cols = [col.strip().lower().replace("-", "_") for col in cols]
            if header is None and {"database_id", "disease_name", "hpo_id"} <= set(lower_cols):
                header = lower_cols
                continue
            parsed = _parse_hpo_disease_row(cols, header)
            if parsed:
                yield parsed


def _parse_hpo_disease_row(cols: list[str], header: list[str] | None) -> dict[str, str] | None:
    if header:
        by_name = {name: cols[index] for index, name in enumerate(header) if index < len(cols)}
        qualifier = _clean_text(by_name.get("qualifier")).upper()
        if qualifier == "NOT":
            return None
        disease_id = by_name.get("database_id") or by_name.get("disease_id")
        disease_name = by_name.get("disease_name") or by_name.get("disease")
        hpo_id = by_name.get("hpo_id") or by_name.get("hpo_term_id")
        if disease_id and disease_name and hpo_id:
            return {
                "disease_id": disease_id,
                "disease_name": disease_name,
                "hpo_id": hpo_id,
                "reference": by_name.get("reference", ""),
            }
    if len(cols) >= 4:
        if _clean_text(cols[2]).upper() == "NOT":
            return None
        return {"disease_id": cols[0], "disease_name": cols[1], "hpo_id": cols[3], "reference": cols[4] if len(cols) > 4 else ""}
    return None


def _hpo_disease_source_record(item: dict[str, Any]) -> dict[str, Any]:
    disease = item["disease_name"]
    disease_id = item["disease_id"]
    hpo_ids = item["hpo_ids"]
    matched_hpo_ids = item["matched_hpo_ids"]
    genes = item.get("genes") or []
    gene_text = f" and gene(s) {', '.join(genes)}" if genes else ""
    match_text = f" Matched requested HPO IDs: {', '.join(matched_hpo_ids)}." if matched_hpo_ids else ""
    finding = f"HPO disease annotation links {disease} ({disease_id}){gene_text} to {len(hpo_ids)} HPO phenotype terms.{match_text}"
    support_spans = [
        {"field": "disease", "value": disease, "source_text": finding},
        {"field": "disease_id", "value": disease_id, "source_text": finding},
    ]
    support_spans.extend({"field": "gene", "value": gene, "source_text": finding} for gene in genes)
    support_spans.extend({"field": "hpo_id", "value": hpo_id, "source_text": finding} for hpo_id in matched_hpo_ids)
    return {
        "record_id": f"hpo:disease:{disease_id}",
        "source_id": "hpo",
        "source_type": "HPO disease phenotype annotation",
        "source_title": "Human Phenotype Ontology disease annotations",
        "source_url": HPO_DISEASE_ANNOTATION_URL,
        "finding": finding,
        "genes": genes,
        "diseases": [disease],
        "disease_ids": [disease_id],
        "phenotypes": matched_hpo_ids,
        "hpo_ids": hpo_ids,
        "verified_fields": {
            "genes": genes,
            "diseases": [disease],
            "disease_ids": [disease_id],
            "phenotypes": matched_hpo_ids,
            "hpo_ids": hpo_ids,
        },
        "support_spans": support_spans,
        "hpo_annotation_profile": {
            "matched_hpo_ids": matched_hpo_ids,
            "profile_hpo_count": len(hpo_ids),
            "association_types": item.get("association_types") or [],
            "enumeration_scope": item.get("enumeration_scope"),
            "references": [ref for ref in item.get("references") or [] if ref][:5],
        },
    }
