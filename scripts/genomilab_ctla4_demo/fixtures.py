"""Dated public-source replay cards for the synthetic demo."""

from __future__ import annotations

from .constants import JsonObject


_RECORDS = (
    (
        "CLINGEN:CTLA4-CGGV-e79675bd",
        {"database_id": "CGGV:e79675bd"},
        "ClinGen CTLA4 gene-disease validity assertion",
        "ClinGen classifies the CTLA4 disease relationship as definitive with autosomal-dominant loss of function or haploinsufficiency.",
        "This establishes CTLA4 as a disease gene, not Q76H as causal.",
        "structured_database",
        "https://search.clinicalgenome.org/kb/gene-validity/CGGV%3Aassertion_e79675bd-3eef-4925-b4ef-3b7c48734f30-2025-06-04T210000.000Z",
        "2025-06-04",
    ),
    (
        "PMID:29729943",
        {"pmid": "29729943", "pmcid": "PMC6215742"},
        "Phenotype and penetrance in 133 CTLA4 variant carriers",
        "The cohort reported hypogammaglobulinemia, autoimmune cytopenia, respiratory involvement, gastrointestinal involvement, and apparently unaffected carriers.",
        "The cohort supports phenotype overlap and incomplete penetrance, but does not establish Q76H causality.",
        "full_text_peer_reviewed",
        "https://pubmed.ncbi.nlm.nih.gov/29729943/",
        "2018-05-04",
    ),
    (
        "PMID:25367873",
        {"pmid": "25367873", "pmcid": "PMC4512923"},
        "CTLA4 dysfunction in a family with Crohn-like disease",
        "A different CTLA4 variant, Y60C, was associated with severe early-onset Crohn-like disease and impaired CD80 binding.",
        "Evidence from a different variant cannot be transferred to Q76H.",
        "full_text_peer_reviewed",
        "https://pubmed.ncbi.nlm.nih.gov/25367873/",
        "2014-11-03",
    ),
    (
        "CLINVAR:2443104",
        {
            "database_id": "ClinVar Variation ID 2443104",
            "rsid": "rs2469719303",
            "gene": "CTLA4",
            "protein_substitution": "Q76H",
        },
        "ClinVar record for CTLA4 c.228G>C, p.Gln76His",
        "The exact Q76H allele is classified as uncertain significance with one submission and no cited functional study.",
        "The variant remains a VUS; the record is not a pathogenic classification.",
        "structured_database",
        "https://www.ncbi.nlm.nih.gov/clinvar/variation/2443104/",
        "2022-05-23",
    ),
    (
        "PMID:25556904",
        {"pmid": "25556904"},
        "Rituximab-associated hypogammaglobulinemia in autoimmune disease",
        "Baseline immunoglobulin status was associated with later low IgG, so pretreatment measurements are important to the medication timeline.",
        "The paper keeps medication effects open without deciding this case.",
        "peer_reviewed_publication",
        "https://pubmed.ncbi.nlm.nih.gov/25556904/",
        "2014-12-31",
    ),
    (
        "PMID:28159733",
        {"pmid": "28159733", "pmcid": "PMC5438243"},
        "Normal-looking CTLA4 abundance with impaired ligand uptake",
        "For CTLA4 P137R, total staining was similar to a control while ligand uptake per CTLA4 molecule was reduced.",
        "P137R is not Q76H, but abundance and function are distinct measurements.",
        "full_text_peer_reviewed",
        "https://pubmed.ncbi.nlm.nih.gov/28159733/",
        "2017-02-03",
    ),
    (
        "PMID:37740092",
        {"pmid": "37740092", "pmcid": "PMC10661720"},
        "Functional characterization of 24 CTLA4 variants",
        "Seventeen tested variants showed impaired transendocytosis and seven were in the healthy-donor range; Q76H was not tested.",
        "The study supports measuring function rather than inferring it from VUS status.",
        "full_text_peer_reviewed",
        "https://pubmed.ncbi.nlm.nih.gov/37740092/",
        "2023-09-23",
    ),
    (
        "PMID:21474713",
        {"pmid": "21474713", "pmcid": "PMC3198051"},
        "CTLA4 transendocytosis of CD80 and CD86",
        "CTLA4-expressing cells captured and removed CD80 and CD86 from opposing cells, establishing a measurable CTLA4 function.",
        "This establishes the mechanism, not the effect of Q76H.",
        "full_text_peer_reviewed",
        "https://pubmed.ncbi.nlm.nih.gov/21474713/",
        "2011-04-07",
    ),
    (
        "PMID:26206937",
        {"pmid": "26206937"},
        "LRBA protects CTLA4 from lysosomal degradation",
        "LRBA colocalizes with CTLA4 and protects it from degradation; normal LRBA expression is narrow counterevidence, not exclusion.",
        "The result keeps other CTLA4-pathway mechanisms open.",
        "peer_reviewed_publication",
        "https://pubmed.ncbi.nlm.nih.gov/26206937/",
        "2015-07-24",
    ),
)


def paperclip_replay_fixture() -> JsonObject:
    records = []
    for source_id, identifiers, title, excerpt, span, state, uri, date in _RECORDS:
        records.append(
            {
                "source_id": source_id,
                "identifiers": identifiers,
                "title": title,
                "excerpt": excerpt,
                "supporting_spans": [span],
                "source_document_state": state,
                "source_uri": uri,
                "publication_date": date,
                "source_license": {
                    "status": "curated_short_paraphrase_demo_fixture",
                    "short_excerpt_storage_permitted": True,
                    "full_text_storage_permitted": False,
                    "figure_storage_permitted": False,
                },
                "source_currency": {
                    "current_source_checked_at": "2026-08-15T00:00:00Z",
                    "correction_status": "not_checked",
                    "retraction_status": "not_checked",
                },
            }
        )
    return {
        "status": "data_returned",
        "source_family": "literature",
        "coverage": {
            "consulted": [
                "Curated Paperclip evidence replay from the checked-in CTLA4 ledger; not a live provider call"
            ]
        },
        "process_provenance": {
            "provider_result_ids": ["ctla4-paperclip-replay-2026-08-15"],
            "provider_version": "checked-in-ledger-v1",
            "provider_repository": "local Genomi demo fixture",
            "retrieved_at": "2026-08-15T00:00:00Z",
        },
        "records": records,
    }
