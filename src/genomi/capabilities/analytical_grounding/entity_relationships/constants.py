from __future__ import annotations

import re

CONTROLLED_ENTITY_RELATIONSHIPS_SCHEMA_VERSION = "genomi-controlled-entity-relationships-v1"
QUICKGO_API_BASE = "https://www.ebi.ac.uk/QuickGO/services"
REACTOME_CONTENT_SERVICE_BASE = "https://reactome.org/ContentService"
KEGG_REST_API_BASE = "https://rest.kegg.jp"
HPA_API_BASE = "https://www.proteinatlas.org/api"
HPA_TSV_DOWNLOAD_BASE = "https://www.proteinatlas.org/download/tsv"
CHEMBL_API_BASE = "https://www.ebi.ac.uk/chembl/api/data"
DEFAULT_TAXON_ID = "9606"
DEFAULT_SPECIES = "Homo sapiens"

SUPPORTED_ENTITY_TYPES = {
    "chemical": "KEGG compound records linked to enzymes and human genes.",
    "cell_type": "Human Protein Atlas single-cell RNA specificity records.",
    "go_term": "Gene Ontology biological process, molecular function, or cellular component terms.",
    "drug": "ChEMBL drug mechanism-of-action target records.",
    "pathway": "Reactome human pathway records.",
    "tissue": "Human Protein Atlas tissue RNA specificity records.",
}
SUPPORTED_SOURCES = {
    "chembl": "ChEMBL molecule, mechanism-of-action, and target records.",
    "goa": "QuickGO Gene Ontology Annotation records.",
    "hpa": "Human Protein Atlas RNA tissue and single-cell specificity records.",
    "kegg": "KEGG COMPOUND, ENZYME, and human GENES records.",
    "reactome": "Reactome ContentService pathway participants.",
}
SOURCE_BY_ENTITY_TYPE = {
    "cell_type": "hpa",
    "chemical": "kegg",
    "drug": "chembl",
    "go_term": "goa",
    "pathway": "reactome",
    "tissue": "hpa",
}
NOT_INTEGRATED_SOURCES = [
    "HMDB metabolite-protein associations",
    "ChEBI chemical ontology relationships",
    "DrugBank drug-target relationships",
    "GTEx direct tissue-specific expression",
    "CellxGene cell-type specificity",
]
CONTROLLED_ID_PREFIXES = {
    "GO:": "go_term",
    "R-HSA-": "pathway",
}
EXPERIMENTAL_GO_EVIDENCE_CODES = {
    "EXP",
    "IDA",
    "IPI",
    "IMP",
    "IGI",
    "IEP",
    "HTP",
    "HDA",
    "HMP",
    "HGI",
    "HEP",
}
TOKEN_RE = re.compile(r"[A-Z0-9][A-Z0-9_.-]*")
TAG_RE = re.compile(r"<[^>]+>")
