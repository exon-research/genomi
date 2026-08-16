from __future__ import annotations

import re

from ....runtime.libraries import manager as library_manager

QUICKGO_API_BASE = library_manager.api_base("quickgo")
REACTOME_CONTENT_SERVICE_BASE = library_manager.api_base("reactome")
KEGG_REST_API_BASE = library_manager.api_base("kegg")
HPA_API_BASE = library_manager.api_base("hpa")
HPA_TSV_DOWNLOAD_BASE = library_manager.source_url("hpa")
CHEMBL_API_BASE = library_manager.api_base("chembl")
UNIPROT_API_BASE = library_manager.api_base("uniprot")
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
