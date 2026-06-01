from __future__ import annotations

from typing import Any

from genomi.capabilities.phenotype.gene_identification import compare_candidate_evidence


def compare_candidate_payload(params: dict[str, Any]) -> dict[str, Any]:
    data = dict(params)
    phenotype_text = data.pop("phenotype", None) or data.pop("phenotype_text", None) or data.pop("text", None)
    phenotype_terms = data.pop("phenotypes", None) or data.pop("terms", None)
    if not phenotype_text and phenotype_terms:
        phenotype_text = "; ".join(str(term) for term in phenotype_terms)
    return compare_candidate_evidence(
        data.pop("db", None),
        phenotype_text=phenotype_text,
        task_text=data.pop("task_text", None) or data.pop("question", None) or data.pop("prompt", None),
        hpo_ids=data.pop("hpo_ids", None),
        genes=data.pop("genes", None),
        drug=data.pop("drug", None),
        drug_class=data.pop("drug_class", None),
        mechanism=data.pop("mechanism", None),
        source_records=data.pop("source_records", None),
        phenotype_source_records=data.pop("phenotype_source_records", None),
        gwas_source_records=data.pop("gwas_source_records", None),
        locus_source_records=data.pop("locus_source_records", None),
        target_source_records=data.pop("target_source_records", None),
        search_stored_research=data.pop("search_stored_research", True),
        use_hpo_annotations=data.pop("use_hpo_annotations", True),
        download_hpo_annotations=data.pop("download_hpo_annotations", False),
        hpo_gene_file=data.pop("hpo_gene_file", None),
        include_gwas=data.pop("include_gwas", True),
        gwas_api_url=data.pop("gwas_api_url", "https://www.ebi.ac.uk/gwas/rest/api/v2"),
        association_limit=data.pop("association_limit", 200),
        use_opentargets=data.pop("use_opentargets", True),
        opentargets_api_url=data.pop("opentargets_api_url", "https://api.platform.opentargets.org/api/v4/graphql"),
        limit=data.pop("limit", 25),
    )
