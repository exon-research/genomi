from __future__ import annotations

from pathlib import Path

from .. import entity_relationships

PATHWAY_MEMBER_GENES_SCHEMA_VERSION = "genomi-pathway-member-genes-v1"
CELL_TYPE_MARKERS_SCHEMA_VERSION = "genomi-cell-type-canonical-markers-v1"
REGION_FEATURE_ANNOTATION_SCHEMA_VERSION = "genomi-region-feature-annotation-v1"

REACTOME_CONTENT_SERVICE_BASE = entity_relationships.REACTOME_CONTENT_SERVICE_BASE
KEGG_REST_API_BASE = entity_relationships.KEGG_REST_API_BASE
HPA_API_BASE = entity_relationships.HPA_API_BASE
HPA_TSV_DOWNLOAD_BASE = entity_relationships.HPA_TSV_DOWNLOAD_BASE

SUPPORTED_PATHWAY_SOURCES = {
    "reactome": "Reactome human pathway participants.",
    "kegg": "KEGG PATHWAY human pathway membership via KEGG REST.",
    "msigdb_hallmark": "MSigDB Hallmark gene sets supplied as an official GMT export.",
}
SUPPORTED_CELL_MARKER_SOURCES = {
    "hpa": "Human Protein Atlas single-cell RNA specificity records.",
    "cellmarker": "CellMarker marker table supplied as a source export.",
    "panglaodb": "PanglaoDB marker table supplied as a source export.",
    "encode": "ENCODE cell-type annotation marker table supplied as a source export.",
}
SUPPORTED_REGION_ASSEMBLIES = {"GRCH37": "GRCh37", "GRCH38": "GRCh38"}

ANALYTICAL_LIBRARY_RELATIVE_PATHS = {
    "gencode-grch38": Path("reference/gencode/gencode.v49.GRCh38.annotation.gtf.gz"),
    "gencode-grch37": Path("reference/gencode/gencode.v49lift37.GRCh37.annotation.gtf.gz"),
    "encode-ccre-grch38": Path("reference/encode/encode-cCREs.V4.GRCh38.bed.gz"),
    "panglaodb-markers": Path("reference/cell-markers/PanglaoDB_markers_27_Mar_2020.tsv.gz"),
    "cellmarker-human": Path("reference/cell-markers/CellMarker2_human_markers.normalized.tsv"),
    "msigdb-hallmark": Path("reference/msigdb/hallmark.symbols.gmt"),
}

NOT_INTEGRATED_PATHWAY_SOURCES = [
    "WikiPathways",
    "Gene Ontology gene sets outside the focused pathway/member retrievers",
    "user-defined modules",
]
NOT_INTEGRATED_CELL_MARKER_SOURCES = [
    "Azimuth reference annotations",
    "CellTypist models",
    "single-cell atlas free-text cluster labels",
]
NOT_INTEGRATED_REGION_SOURCES = [
    "custom annotation tracks",
    "non-human assemblies",
    "alternative haplotype assemblies beyond declared GRCh37/GRCh38 source files",
]
