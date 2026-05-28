"""Nutrigenomic capability provenance, boundaries, and label definitions.

This module is the single source of truth for what the nutrigenomics
capability is and is not. Every operation references constants and helpers
defined here so the boundary language and source coverage cannot drift
between tools.
"""
from __future__ import annotations

from typing import Any

CAPABILITY_ID = "nutrigenomics"
CAPABILITY_TITLE = "Nutrigenomic Single-Marker Evidence"
SCHEMA_VERSION = "genomi-nutrigenomics-marker-records-v1"

BOUNDARY_NOTE = (
    "The output is curated single-marker evidence for declared nutrient-metabolism, "
    "food-tolerance, or taste-perception domains. It is not a diet prescription, "
    "supplement dosing recommendation, weight-loss prediction, methylation-cycle "
    "prescription, microbiome-mediated effect estimate, or genome-wide nutrition "
    "interpretation."
)


# Declared nutrigenomic domains. The set is intentionally bounded; domains
# outside this list are out_of_scope_for_input. Add new domains by curation
# commit, not by free-text expansion at call time.
DOMAIN_DEFINITIONS: dict[str, dict[str, Any]] = {
    "folate_metabolism": {
        "label": "Folate metabolism",
        "scope": "Single-marker evidence for folate / homocysteine pathway variants.",
        "downstream_traits": ["serum folate", "plasma homocysteine"],
        "primary_sources": ["ClinVar", "ClinGen", "NHGRI-EBI GWAS Catalog", "CDC MTHFR guidance"],
        "common_pseudoscience_claims_disowned": [
            "MTHFR as a general 'detoxification gene'",
            "MTHFR genotype as a basis for avoiding folic acid",
            "Methylfolate-only prescriptions based on genotype alone",
        ],
    },
    "lactose_tolerance": {
        "label": "Lactose tolerance",
        "scope": "Lactase persistence regulatory variant in the LCT/MCM6 region.",
        "downstream_traits": ["lactase persistence", "self-reported lactose tolerance"],
        "primary_sources": ["MedlinePlus", "ClinVar", "lactase persistence reviews"],
        "common_pseudoscience_claims_disowned": [
            "Variant predicts severity of lactose intolerance symptoms",
            "Variant predicts dairy fat or casein intolerance",
        ],
    },
    "iron_storage": {
        "label": "Iron storage and hemochromatosis",
        "scope": "HFE C282Y and H63D variants for hereditary hemochromatosis context.",
        "downstream_traits": ["serum ferritin", "transferrin saturation"],
        "primary_sources": ["GeneReviews", "ClinVar", "ClinGen"],
        "common_pseudoscience_claims_disowned": [
            "Single H63D allele as iron-overload diagnosis",
            "Genotype as basis for therapeutic phlebotomy decisions without iron labs",
        ],
    },
    "vitamin_d_status": {
        "label": "Vitamin D status",
        "scope": "GC, CYP2R1, DHCR7/NADSYN1 common variants associated with 25(OH)D levels.",
        "downstream_traits": ["serum 25(OH)D"],
        "primary_sources": ["NHGRI-EBI GWAS Catalog", "vitamin D GWAS reviews"],
        "common_pseudoscience_claims_disowned": [
            "Genotype as basis for vitamin D megadose prescriptions",
            "Genotype as substitute for measuring serum 25(OH)D",
        ],
    },
    "lipid_diet_response": {
        "label": "Lipid response context (APOE)",
        "scope": "APOE e2/e3/e4 isoform-defining variants (rs429358 + rs7412).",
        "downstream_traits": ["LDL cholesterol", "triglycerides", "apolipoprotein E isoform"],
        "primary_sources": ["GeneReviews APOE", "MedlinePlus APOE"],
        "common_pseudoscience_claims_disowned": [
            "APOE genotype as basis for macronutrient ratio prescriptions",
            "APOE genotype as a deterministic predictor of Alzheimer disease",
            "APOE genotype as basis for specific dietary fat type prescriptions",
        ],
    },
    "obesity_predisposition": {
        "label": "Obesity predisposition (common-risk context)",
        "scope": "FTO common-risk variant context only; explicitly not a polygenic risk score.",
        "downstream_traits": ["BMI", "body weight"],
        "primary_sources": ["NHGRI-EBI GWAS Catalog", "FTO functional studies"],
        "common_pseudoscience_claims_disowned": [
            "FTO genotype as basis for diet-matching for weight loss",
            "Single SNP as predictor of weight-loss intervention response",
            "FTO genotype as deterministic predictor of obesity",
        ],
    },
}


# Domains not included in the catalogue by construction. The capability
# refuses these inputs rather than returning shape-matching weak records.
OUT_OF_SCOPE_BY_CONSTRUCTION: list[str] = [
    "personalized_diet_match",
    "general_methylation_prescription",
    "detox_capacity",
    "weight_loss_intervention_response",
    "vitamin_megadose_response",
    "microbiome_diet_match",
    "food_allergy_prediction",
    "macronutrient_ratio_prescription",
    "supplement_product_recommendation",
]


def source_urls() -> dict[str, str]:
    return {
        "clinvar": "https://www.ncbi.nlm.nih.gov/clinvar/",
        "clingen": "https://search.clinicalgenome.org/",
        "gwas_catalog": "https://www.ebi.ac.uk/gwas/",
        "medlineplus_genetics": "https://medlineplus.gov/genetics/",
        "gene_reviews": "https://www.ncbi.nlm.nih.gov/books/NBK1116/",
        "cdc_mthfr_guidance": "https://www.cdc.gov/folic-acid/data-research/mthfr/index.html",
    }


def label_definitions() -> dict[str, Any]:
    return {
        "label_scope": "Declared nutrigenomic domain labels with bounded single-marker scope",
        "domains": {
            domain_id: {
                "label": definition["label"],
                "scope": definition["scope"],
            }
            for domain_id, definition in DOMAIN_DEFINITIONS.items()
        },
        "evidence_tier_meaning": {
            "established": (
                "Expert curation (ClinGen, GeneReviews, or equivalent) OR replicated in three or "
                "more independent GWAS at genome-wide significance, AND mechanistic plausibility "
                "published in peer-reviewed reviews."
            ),
            "probable": (
                "Two or more replicated GWAS at genome-wide significance, OR ClinVar P/LP for a "
                "defined Mendelian trait, but contested effect sizes."
            ),
            "emerging": (
                "Single GWAS at genome-wide significance with mechanistic plausibility, awaiting "
                "replication."
            ),
        },
        "non_prescription_boundary": BOUNDARY_NOTE,
    }


def limitations() -> list[str]:
    return [
        BOUNDARY_NOTE,
        "The catalogue is hand-curated and intentionally small; absence of a marker is not "
        "evidence of negligible effect.",
        "Single-marker evidence does not substitute for lab measurements (serum 25(OH)D, "
        "ferritin/transferrin saturation, homocysteine, lipid panel) when clinical decisions "
        "are at stake.",
        "Population-stratified allele frequencies are not duplicated here; the host agent "
        "should call gnomad.fetch_population_frequency for stratified frequencies.",
        "Primary GWAS effect sizes are not duplicated here; the host agent should call "
        "gwas.compare_variant_associations for primary association data.",
        "Out-of-scope domains (diet prescription, supplement dosing, weight-loss prediction, "
        "microbiome-mediated effects, etc.) are refused at the input boundary rather than "
        "approximated with weak records.",
    ]


def build_source_context() -> dict[str, Any]:
    return {
        "capability": CAPABILITY_ID,
        "title": CAPABILITY_TITLE,
        "schema": SCHEMA_VERSION,
        "source_urls": source_urls(),
        "label_definitions": label_definitions(),
        "declared_domains": list(DOMAIN_DEFINITIONS.keys()),
        "out_of_scope_by_construction": list(OUT_OF_SCOPE_BY_CONSTRUCTION),
        "limitations": limitations(),
        "boundary_note": BOUNDARY_NOTE,
        "coverage_status": "data_returned",
    }
