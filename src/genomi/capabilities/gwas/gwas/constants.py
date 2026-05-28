from __future__ import annotations

import re

GWAS_CATALOG_API_URL = "https://www.ebi.ac.uk/gwas/rest/api"
GWAS_CATALOG_V2_API_URL = "https://www.ebi.ac.uk/gwas/rest/api/v2"
GWAS_CATALOG_PROJECTION = "associationByEfoTrait"
GWAS_CATALOG_SOURCE_URL = "https://www.ebi.ac.uk/gwas/"
GWAS_MAX_ASSOCIATION_LIMIT = 500
# Each emitted association record carries study metadata, mapped/reported
# genes, traits, and a record_research_payload — at ~6 KB per record the
# previous cap of 100 produced ~500 KB results that overflowed agent
# tool-result limits. 25 ranked associations is enough for downstream review
# and keeps the result agent-readable.
GWAS_MAX_EMITTED_ASSOCIATIONS = 25
GWAS_GENE_FIELD_EVIDENCE_INTENT = "gwas_catalog_gene_field_evidence"
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LOW_INFORMATION_TRAIT_TOKENS = {
    "and",
    "association",
    "disease",
    "for",
    "of",
    "response",
    "serum",
    "trait",
}
_TRAIT_TOKEN_ALIASES = {
    "concentration": "level",
    "concentrations": "level",
    "level": "level",
    "levels": "level",
    "measurement": "level",
    "measurements": "level",
}
_CAUSAL_GENE_REQUEST_TERMS = (
    "causal gene",
    "causative gene",
    "effector gene",
    "likely causal",
    "putative causal",
    "causal at",
    "causal within",
    "causal for",
    "causal locus",
    "target gene",
    "driver gene",
)
_LOCUS_GENE_REQUEST_TERMS = (
    "within a locus",
    "within the locus",
    "at a locus",
    "at the locus",
    "trait-associated locus",
    "risk locus",
    "locus for this trait",
    "gene within",
)
_EXPLICIT_GWAS_GENE_FIELD_TERMS = (
    "gwas catalog reported gene",
    "gwas catalog mapped gene",
    "reported gene field",
    "reported_gene",
    "reported_genes",
    "mapped gene field",
    "mapped_gene",
    "mapped_genes",
    "source gene field",
    "gwas catalog gene field",
    "gwas catalog association evidence",
)
