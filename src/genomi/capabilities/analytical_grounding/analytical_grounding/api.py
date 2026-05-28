from __future__ import annotations

import urllib.error
from pathlib import Path
from typing import Any

from ....retrieval import semantic as retrieval_semantic
from .. import entity_relationships
from .cell_markers import _retrieve_hpa_cell_type_markers, _retrieve_table_cell_type_markers
from .constants import (
    CELL_TYPE_MARKERS_SCHEMA_VERSION,
    HPA_API_BASE,
    HPA_TSV_DOWNLOAD_BASE,
    KEGG_REST_API_BASE,
    NOT_INTEGRATED_CELL_MARKER_SOURCES,
    NOT_INTEGRATED_PATHWAY_SOURCES,
    NOT_INTEGRATED_REGION_SOURCES,
    REACTOME_CONTENT_SERVICE_BASE,
    REGION_FEATURE_ANNOTATION_SCHEMA_VERSION,
    SUPPORTED_CELL_MARKER_SOURCES,
)
from .helpers import (
    _clean_text,
    _fetch_bytes,
    _fetch_json,
    _fetch_text,
    _feature_order_key,
    _dominant_feature_class,
    _looks_like_pathway_identifier,
    _nearest_tss,
    _normalize_assembly,
    _normalize_cell_marker_source,
    _normalize_source,
    _region_query,
)
from .library import (
    default_encode_ccre_bed_path,
    default_gencode_gtf_path,
    default_marker_table_path,
    installed_analytical_library_path,
    _cell_marker_library_for_source,
)
from .pathways import (
    _retrieve_kegg_pathway_members,
    _retrieve_msigdb_hallmark_members,
    _retrieve_reactome_pathway_members,
)
from .regions import _read_encode_ccre_bed, _read_gencode_gtf
from .responses import (
    _cell_marker_capability_contract,
    _cell_marker_empty,
    _cell_marker_source_label,
    _library_install_response,
    _pathway_empty,
    _pathway_source_candidates,
    _pathway_source_for_target,
    _pathway_source_label,
    _region_capability_contract,
    _region_empty,
    _source_coverage,
)


def retrieve_pathway_member_genes(
    *,
    pathway_id_or_name: str | None = None,
    pathway_id: str | None = None,
    pathway_name: str | None = None,
    source: str | None = None,
    species: str | None = entity_relationships.DEFAULT_SPECIES,
    limit: int = 500,
    reactome_api_base: str = REACTOME_CONTENT_SERVICE_BASE,
    kegg_api_base: str = KEGG_REST_API_BASE,
    msigdb_gmt: str | Path | None = None,
    msigdb_gmt_url: str | None = None,
    msigdb_version: str | None = None,
    fetch_json: Any | None = None,
    fetch_text: Any | None = None,
    semantic_context: object = None,
) -> dict[str, Any]:
    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    raw_target = _clean_text(pathway_id_or_name or pathway_id or pathway_name)
    target = _semantic_lookup_target(
        raw_target,
        semantic,
        entity_types=("pathway", "gene_set", "biological_process"),
        exact_target=_looks_like_pathway_identifier(raw_target),
    )
    query = {
        "pathway_id_or_name": target,
        "pathway_id": _clean_text(pathway_id),
        "pathway_name": _clean_text(pathway_name),
        "source": _normalize_source(source),
        "species": _clean_text(species) or entity_relationships.DEFAULT_SPECIES,
        "limit": max(1, int(limit or 500)),
    }
    if not target:
        raise ValueError("pathway.retrieve_members requires pathway_id_or_name, pathway_id, or pathway_name")
    source_key = _pathway_source_for_target(target, query["source"])
    if source_key == "unsupported":
        return _pathway_empty(
            status="unsupported_source",
            coverage_status="out_of_scope_for_input",
            query=query,
            empty_reason=f"Unsupported source: {query['source']}",
        )
    if source_key == "source_required":
        return _pathway_empty(
            status="source_required",
            coverage_status="out_of_scope_for_input",
            query=query,
            empty_reason="Free-text pathway lookup requires source, or a controlled Reactome/KEGG/MSigDB identifier.",
            resolution_candidates=_pathway_source_candidates(),
        )
    text_fetcher = fetch_text or _fetch_text
    json_fetcher = fetch_json or _fetch_json
    if source_key == "msigdb_hallmark" and not msigdb_gmt and not msigdb_gmt_url:
        msigdb_gmt = installed_analytical_library_path("msigdb-hallmark")
    try:
        if source_key == "reactome":
            result = _retrieve_reactome_pathway_members(
                target=target,
                query=query,
                limit=max(1, int(limit or 500)),
                reactome_api_base=reactome_api_base,
                fetch_json=json_fetcher,
            )
            return _with_lookup_semantic_usage(result, semantic, target, source="Reactome", record_key="pathway")
        if source_key == "kegg":
            result = _retrieve_kegg_pathway_members(
                target=target,
                query=query,
                limit=max(1, int(limit or 500)),
                kegg_api_base=kegg_api_base,
                fetch_text=text_fetcher,
            )
            return _with_lookup_semantic_usage(result, semantic, target, source="KEGG PATHWAY", record_key="pathway")
        result = _retrieve_msigdb_hallmark_members(
            target=target,
            query=query,
            limit=max(1, int(limit or 500)),
            gmt_path=msigdb_gmt,
            gmt_url=msigdb_gmt_url,
            version=msigdb_version,
            fetch_text=text_fetcher,
        )
        return _with_lookup_semantic_usage(result, semantic, target, source="MSigDB Hallmark", record_key="pathway")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
        return _pathway_empty(
            status="source_unavailable",
            coverage_status="out_of_scope_for_input",
            query=query,
            empty_reason="A declared pathway membership source was unavailable.",
            source_coverage=_source_coverage(
                "out_of_scope_for_input",
                consulted=[],
                unavailable=[{"source": _pathway_source_label(source_key), "error": str(exc)}],
                not_integrated=NOT_INTEGRATED_PATHWAY_SOURCES,
            ),
        )


def retrieve_canonical_markers(
    *,
    cell_type_id_or_name: str | None = None,
    cell_type_id: str | None = None,
    cell_type_name: str | None = None,
    source: str | None = "hpa",
    species: str | None = entity_relationships.DEFAULT_SPECIES,
    marker_table: str | Path | None = None,
    limit: int = 100,
    hpa_api_base: str = HPA_API_BASE,
    hpa_download_base: str = HPA_TSV_DOWNLOAD_BASE,
    fetch_json: Any | None = None,
    fetch_bytes: Any | None = None,
    semantic_context: object = None,
) -> dict[str, Any]:
    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    raw_target = _clean_text(cell_type_id_or_name or cell_type_id or cell_type_name)
    target = _semantic_lookup_target(
        raw_target,
        semantic,
        entity_types=("cell_type", "cell", "tissue"),
        exact_target=bool(cell_type_id),
    )
    source_key = _normalize_cell_marker_source(source)
    query = {
        "cell_type_id_or_name": target,
        "cell_type_id": _clean_text(cell_type_id),
        "cell_type_name": _clean_text(cell_type_name),
        "source": source_key,
        "species": _clean_text(species) or entity_relationships.DEFAULT_SPECIES,
        "limit": max(1, int(limit or 100)),
    }
    if not target:
        raise ValueError("cell_type.retrieve_markers requires cell_type_id_or_name, cell_type_id, or cell_type_name")
    if source_key not in SUPPORTED_CELL_MARKER_SOURCES:
        return _cell_marker_empty(
            status="unsupported_source",
            coverage_status="out_of_scope_for_input",
            query=query,
            empty_reason=f"Unsupported source: {source_key}",
        )
    if source_key != "hpa" and not marker_table:
        marker_table = default_marker_table_path(source_key)
    try:
        if source_key == "hpa":
            result = _retrieve_hpa_cell_type_markers(
                target=target,
                query=query,
                limit=max(1, int(limit or 100)),
                hpa_api_base=hpa_api_base,
                hpa_download_base=hpa_download_base,
                fetch_json=fetch_json or _fetch_json,
                fetch_bytes=fetch_bytes or _fetch_bytes,
            )
            return _with_lookup_semantic_usage(result, semantic, target, source="Human Protein Atlas", record_key="cell_type")
        if not marker_table:
            library = _cell_marker_library_for_source(source_key)
            if library:
                return _library_install_response(
                    schema=CELL_TYPE_MARKERS_SCHEMA_VERSION,
                    query=query,
                    capability=_cell_marker_capability_contract(),
                    library=library,
                    intent=f"{_cell_marker_source_label(source_key)} marker lookup for {target}",
                    operation="cell_type.retrieve_markers",
                    source_label=_cell_marker_source_label(source_key),
                    not_integrated=NOT_INTEGRATED_CELL_MARKER_SOURCES,
                )
            return _cell_marker_empty(
                status="source_table_required",
                coverage_status="out_of_scope_for_input",
                query=query,
                empty_reason=(
                    f"{SUPPORTED_CELL_MARKER_SOURCES[source_key]} Pass marker_table with the official exported table "
                    "to retrieve markers from this source."
                ),
                source_coverage=_source_coverage(
                    "out_of_scope_for_input",
                    consulted=[],
                    unavailable=[{"source": _cell_marker_source_label(source_key), "error": "marker_table was not supplied"}],
                    not_integrated=NOT_INTEGRATED_CELL_MARKER_SOURCES,
                ),
            )
        result = _retrieve_table_cell_type_markers(
            target=target,
            source_key=source_key,
            query=query,
            marker_table=Path(marker_table),
            limit=max(1, int(limit or 100)),
        )
        return _with_lookup_semantic_usage(result, semantic, target, source=_cell_marker_source_label(source_key), record_key="cell_type")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
        return _cell_marker_empty(
            status="source_unavailable",
            coverage_status="out_of_scope_for_input",
            query=query,
            empty_reason="A declared cell-type marker source was unavailable.",
            source_coverage=_source_coverage(
                "out_of_scope_for_input",
                consulted=[],
                unavailable=[{"source": _cell_marker_source_label(source_key), "error": str(exc)}],
                not_integrated=NOT_INTEGRATED_CELL_MARKER_SOURCES,
            ),
        )


def retrieve_region_feature_annotation(
    *,
    chrom: str | None = None,
    start: int | str | None = None,
    end: int | str | None = None,
    assembly: str | None = None,
    region: str | None = None,
    gencode_gtf: str | Path | None = None,
    encode_ccre_bed: str | Path | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    explicit_gencode = gencode_gtf is not None
    explicit_encode = encode_ccre_bed is not None
    assembly_label = _normalize_assembly(assembly)
    if assembly_label and not gencode_gtf:
        gencode_gtf = default_gencode_gtf_path(assembly_label)
    if assembly_label and not encode_ccre_bed:
        encode_ccre_bed = default_encode_ccre_bed_path(assembly_label)
    parsed = _region_query(chrom=chrom, start=start, end=end, region=region)
    query = {
        "chrom": parsed.get("chrom"),
        "start": parsed.get("start"),
        "end": parsed.get("end"),
        "assembly": assembly_label or _clean_text(assembly),
        "region": _clean_text(region),
        "gencode_gtf": str(gencode_gtf) if gencode_gtf else "",
        "encode_ccre_bed": str(encode_ccre_bed) if encode_ccre_bed else "",
        "limit": max(1, int(limit or 100)),
    }
    if parsed.get("error"):
        return _region_empty(
            status="invalid_interval",
            coverage_status="out_of_scope_for_input",
            query=query,
            empty_reason=parsed["error"],
        )
    if not assembly_label:
        return _region_empty(
            status="unsupported_assembly",
            coverage_status="out_of_scope_for_input",
            query=query,
            empty_reason="assembly must be GRCh37 or GRCh38.",
        )
    if not gencode_gtf and not encode_ccre_bed:
        if not explicit_gencode and not explicit_encode:
            interval = query.get("region") or f"{query.get('chrom')}:{query.get('start')}-{query.get('end')}"
            return _library_install_response(
                schema=REGION_FEATURE_ANNOTATION_SCHEMA_VERSION,
                query={**query, "assembly": assembly_label},
                capability=_region_capability_contract(),
                library=f"gencode-{assembly_label.lower()}",
                intent=f"region feature annotation for {interval}",
                operation="region.retrieve_features",
                source_label="GENCODE GTF",
                not_integrated=NOT_INTEGRATED_REGION_SOURCES,
                additional_missing_libraries=["encode-ccre-grch38"] if assembly_label == "GRCh38" else [],
            )
        return _region_empty(
            status="source_files_required",
            coverage_status="out_of_scope_for_input",
            query=query,
            empty_reason="Provide gencode_gtf, encode_ccre_bed, or both. Region annotation does not use undeclared/custom tracks.",
            source_coverage=_source_coverage(
                "out_of_scope_for_input",
                consulted=[],
                unavailable=[
                    {"source": "GENCODE GTF", "error": "gencode_gtf was not supplied"},
                    {"source": "ENCODE cCRE BED", "error": "encode_ccre_bed was not supplied"},
                ],
                not_integrated=NOT_INTEGRATED_REGION_SOURCES,
            ),
        )

    region_chrom = str(parsed["chrom"])
    region_start = int(parsed["start"])
    region_end = int(parsed["end"])
    return_limit = max(1, int(limit or 100))
    features: list[dict[str, Any]] = []
    tss_candidates: list[dict[str, Any]] = []
    consulted: list[str] = []
    unavailable: list[dict[str, str]] = []

    if gencode_gtf:
        try:
            gencode_records, tss_records = _read_gencode_gtf(Path(gencode_gtf), region_chrom, region_start, region_end)
            features.extend(gencode_records)
            tss_candidates.extend(tss_records)
            consulted.append("GENCODE GTF")
        except OSError as exc:
            unavailable.append({"source": "GENCODE GTF", "error": str(exc)})
    if encode_ccre_bed:
        try:
            features.extend(_read_encode_ccre_bed(Path(encode_ccre_bed), region_chrom, region_start, region_end))
            consulted.append("ENCODE cCRE BED")
        except OSError as exc:
            unavailable.append({"source": "ENCODE cCRE BED", "error": str(exc)})

    features = sorted(features, key=_feature_order_key)[:return_limit]
    nearest_tss = _nearest_tss(tss_candidates, region_start, region_end)
    if not features and not nearest_tss and unavailable:
        return _region_empty(
            status="source_unavailable",
            coverage_status="out_of_scope_for_input",
            query={**query, "assembly": assembly_label},
            empty_reason="One or more declared annotation files could not be read, so Genomi cannot report a clean in-scope empty result.",
            source_coverage=_source_coverage(
                "out_of_scope_for_input",
                consulted=consulted,
                unavailable=unavailable,
                not_integrated=NOT_INTEGRATED_REGION_SOURCES,
            ),
        )
    coverage_status = "data_returned" if features or nearest_tss else "in_scope_empty"
    status = "feature_annotations_found" if coverage_status == "data_returned" else "no_feature_annotations"
    response: dict[str, Any] = {
        "schema": REGION_FEATURE_ANNOTATION_SCHEMA_VERSION,
        "coverage_status": coverage_status,
        "coverage_state": coverage_status,
        "status": status,
        "agent_decision_required": True,
        "query": {**query, "assembly": assembly_label},
        "capability": _region_capability_contract(),
        "features": features,
        "classification": {
            "dominant_feature_class": _dominant_feature_class(features),
            "distance_to_nearest_TSS": nearest_tss.get("distance_bp") if nearest_tss else None,
            "nearest_tss_gene": nearest_tss.get("gene_symbol") if nearest_tss else "",
            "nearest_tss_feature_id": nearest_tss.get("feature_id") if nearest_tss else "",
            "nearest_tss_position": nearest_tss.get("tss") if nearest_tss else None,
        },
        "coverage": {
            "returned_feature_count": len(features),
            "consulted_source_count": len(set(consulted)),
            "unavailable_source_count": len(unavailable),
        },
        "source_coverage": _source_coverage(
            coverage_status,
            consulted=consulted,
            unavailable=unavailable,
            not_integrated=NOT_INTEGRATED_REGION_SOURCES,
        ),
    }
    if not features and not nearest_tss:
        response["empty_reason"] = "Declared annotation files were searched for this interval, but no overlapping feature or GENCODE TSS record was found."
    return response


def _semantic_lookup_target(
    raw_target: str,
    semantic: retrieval_semantic.SemanticContext,
    *,
    entity_types: tuple[str, ...],
    exact_target: bool,
) -> str:
    if exact_target:
        return raw_target
    terms = retrieval_semantic.search_terms(semantic, entity_types=entity_types)
    return _clean_text(terms[0]) if terms else raw_target


def _with_lookup_semantic_usage(
    result: dict[str, Any],
    semantic: retrieval_semantic.SemanticContext,
    target: str,
    *,
    source: str,
    record_key: str,
) -> dict[str, Any]:
    if not semantic.has_hints:
        return result
    record = result.get(record_key) if isinstance(result.get(record_key), dict) else {}
    matched = [target, record.get("id"), record.get("name"), record.get("display_name")]
    result["semantic_context"] = retrieval_semantic.term_usage_payload(
        semantic,
        term_matches=retrieval_semantic.matched_terms(
            semantic,
            matched,
            match_type=f"matched_{record_key}_source_record",
            source=source,
        ),
        streams=retrieval_semantic.retrieval_streams(
            raw_query=semantic.raw_query,
            host_terms=retrieval_semantic.search_terms(semantic),
            source_native_filters=[target],
        ),
    )
    return result
