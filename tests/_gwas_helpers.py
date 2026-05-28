"""Shared fake-data builders for the GWAS test suite.

This module is intentionally NOT named ``test_*`` so pytest does not collect
it as a test module. The builders are imported by ``test_gwas.py`` and
``test_gwas_gene.py``.
"""

from __future__ import annotations


def _association(
    rsid: str,
    trait: str,
    pvalue: float,
    risk_allele: str,
    gene: str,
    accession: str,
    association_id: str,
) -> dict:
    return {
        "pvalue": pvalue,
        "riskFrequency": "NR",
        "loci": [
            {
                "strongestRiskAlleles": [{"riskAlleleName": risk_allele}],
                "authorReportedGenes": [{"geneName": gene}],
            }
        ],
        "snps": [
            {
                "rsId": rsid,
                "genomicContexts": [
                    {
                        "gene": {"geneName": gene},
                    }
                ],
            }
        ],
        "study": {
            "accessionId": accession,
            "diseaseTrait": {"trait": trait},
            "initialSampleSize": "100 cases",
            "publicationInfo": {
                "pubmedId": "123",
                "publicationDate": "2025-01-01",
                "publication": "Example Journal",
                "title": "Example GWAS",
                "author": {"fullname": "Researcher A"},
            },
        },
        "_links": {"self": {"href": f"https://www.ebi.ac.uk/gwas/rest/api/associations/{association_id}"}},
    }


def _v2_association(trait: str, gene: str, pvalue: float, association_id: str) -> dict:
    return {
        "association_id": association_id,
        "p_value": pvalue,
        "pvalue_mantissa": 9,
        "pvalue_exponent": -10,
        "reported_trait": [trait],
        "efo_traits": [{"efo_trait": trait, "efo_id": "EFO_0004340"}],
        "mapped_genes": [gene],
        "accession_id": f"GCST{association_id}",
        "pubmed_id": "123",
        "_links": {"self": {"href": f"https://www.ebi.ac.uk/gwas/rest/api/v2/associations/{association_id}"}},
    }
