from __future__ import annotations

from .. import entity_relationships
from ....retrieval import semantic as retrieval_semantic
from ....runtime.paths import genomi_data_root
from .api import (
    retrieve_canonical_markers,
    retrieve_pathway_member_genes,
    retrieve_region_feature_annotation,
    _semantic_lookup_target,
    _with_lookup_semantic_usage,
)
from .cell_markers import (
    _retrieve_hpa_cell_type_markers,
    _retrieve_table_cell_type_markers,
)
from .constants import (
    CELL_TYPE_MARKERS_SCHEMA_VERSION,
    HPA_API_BASE,
    HPA_TSV_DOWNLOAD_BASE,
    KEGG_REST_API_BASE,
    NOT_INTEGRATED_CELL_MARKER_SOURCES,
    NOT_INTEGRATED_PATHWAY_SOURCES,
    NOT_INTEGRATED_REGION_SOURCES,
    PATHWAY_MEMBER_GENES_SCHEMA_VERSION,
    REACTOME_CONTENT_SERVICE_BASE,
    REGION_FEATURE_ANNOTATION_SCHEMA_VERSION,
    SUPPORTED_CELL_MARKER_SOURCES,
    SUPPORTED_PATHWAY_SOURCES,
    SUPPORTED_REGION_ASSEMBLIES,
)
from .helpers import (
    _ccre_class,
    _cell_marker_source_label,
    _clean_chrom,
    _clean_text,
    _dominant_feature_class,
    _feature_order_key,
    _feature_priority,
    _fetch_bytes,
    _fetch_json,
    _fetch_text,
    _first_present,
    _is_reactome_id,
    _kegg_gene_symbol,
    _looks_like_pathway_identifier,
    _nearest_tss,
    _normalise_label,
    _normalize_assembly,
    _normalize_cell_marker_source,
    _normalize_kegg_pathway_id,
    _normalize_source,
    _open_text,
    _overlap_bp,
    _parse_gmt,
    _parse_gtf_attributes,
    _parse_kegg_flat_entry,
    _parse_kegg_links,
    _parse_kegg_pathway_find,
    _pathway_source_label,
    _read_marker_table,
    _read_marker_table_text,
    _region_query,
    _row_matches_species,
    _safe_int,
    _same_chrom,
    _table_cell_type_value,
    _table_gene_value,
    _url,
    _validated_region,
)
from .library import (
    analytical_library_path,
    default_encode_ccre_bed_path,
    default_gencode_gtf_path,
    default_marker_table_path,
    installed_analytical_library_path,
    _cell_marker_library_for_source,
)
from .pathways import (
    _resolve_kegg_pathway,
    _retrieve_kegg_pathway_members,
    _retrieve_msigdb_hallmark_members,
    _retrieve_reactome_pathway_members,
)
from .regions import _read_encode_ccre_bed, _read_gencode_gtf
from .responses import (
    _cell_marker_capability_contract,
    _cell_marker_empty,
    _cell_marker_response,
    _dedupe_markers,
    _dedupe_members,
    _library_install_response,
    _marker_from_hpa_record,
    _member_from_relationship_record,
    _pathway_capability_contract,
    _pathway_empty,
    _pathway_response,
    _pathway_source_candidates,
    _pathway_source_for_target,
    _region_capability_contract,
    _region_empty,
    _source_coverage,
)
