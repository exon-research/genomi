"""Curated single-marker nutrigenomic records.

Each record carries: variant identifier, gene, domain, established_effect with
GWAS Catalog chain-out, evidence_tier, resolvable source citations, established
caveats, and out_of_scope_claims that the host agent must surface as
disclaimers rather than paraphrase around.

Add rows by curation commit only. Every row must cite at least one expert-
curation source or two replicating GWAS Catalog entries, and must populate
out_of_scope_claims listing the popular but unsupported claims about that
specific variant.
"""
from __future__ import annotations

from typing import Any

from . import source_context

DOMAIN_MARKER_RECORDS: list[dict[str, Any]] = [
    {
        "record_id": "mthfr_c677t_folate",
        "variant": {
            "rsid": "rs1801133",
            "chrom": "1",
            "pos_grch38": 11796321,
            "ref": "G",
            "alt": "A",
            "hgvs_p": "p.Ala222Val",
        },
        "gene": {"symbol": "MTHFR", "hgnc_id": "HGNC:7436"},
        "domain": "folate_metabolism",
        "effect_allele": "A",
        "established_effect": {
            "claim": (
                "C677T (T allele) reduces MTHFR enzyme thermostability; T/T homozygotes have "
                "~30% of C/C activity. Associated with higher plasma homocysteine."
            ),
            "mechanism": "Thermolabile enzyme variant",
            "downstream_traits_with_gwas": [
                {"trait": "plasma homocysteine", "gwas_catalog_id": "EFO_0004458"},
                {"trait": "serum folate", "gwas_catalog_id": "EFO_0004465"},
            ],
        },
        "evidence_tier": "established",
        "sources": [
            {
                "source": "CDC MTHFR and folic acid guidance",
                "evidence_type": "expert_curation",
                "url": "https://www.cdc.gov/folic-acid/data-research/mthfr/index.html",
            },
            {
                "source": "ClinVar rs1801133",
                "evidence_type": "clinical_curation",
                "identifier": "VCV:3520",
                "url": "https://www.ncbi.nlm.nih.gov/clinvar/variation/3520/",
            },
        ],
        "established_caveats": [
            "Effect on cardiovascular outcomes is contested across populations",
            "Folate fortification status of the population modifies effect size",
            "Lab values (homocysteine, folate, B12) and diet dominate the clinical picture",
        ],
        "out_of_scope_claims": [
            "MTHFR variants as a general 'detoxification gene' — not supported",
            "Avoiding folic acid solely on MTHFR genotype — CDC explicitly says people with "
            "MTHFR variants can process folic acid and should not avoid it on genotype grounds",
            "Methylfolate-only dosing prescriptions based on genotype alone — limited RCT evidence",
        ],
    },
    {
        "record_id": "lct_persistence",
        "variant": {
            "rsid": "rs4988235",
            "chrom": "2",
            "pos_grch38": 135851076,
            "ref": "G",
            "alt": "A",
        },
        "gene": {"symbol": "LCT", "hgnc_id": "HGNC:6530", "regulatory_region": "MCM6"},
        "domain": "lactose_tolerance",
        "effect_allele": "A",
        "established_effect": {
            "claim": (
                "A allele in the MCM6 regulatory region of LCT confers lactase persistence in "
                "European-ancestry populations."
            ),
            "mechanism": "Cis-regulatory variant maintaining LCT expression past weaning",
            "downstream_traits_with_gwas": [
                {"trait": "lactase persistence", "gwas_catalog_id": "EFO_0004294"},
            ],
        },
        "evidence_tier": "established",
        "sources": [
            {
                "source": "MedlinePlus lactose intolerance",
                "evidence_type": "expert_curation",
                "url": "https://medlineplus.gov/genetics/condition/lactose-intolerance/",
            },
            {
                "source": "LCT lactase persistence review",
                "evidence_type": "peer_reviewed_review",
                "identifier": "PMC:3048992",
                "url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3048992/",
            },
        ],
        "established_caveats": [
            "Ancestry-dependent; alternative persistence variants exist in African and Middle Eastern "
            "populations and are not captured by this single marker",
            "Secondary lactose intolerance from infection or other causes occurs regardless of genotype",
        ],
        "out_of_scope_claims": [
            "Variant as predictor of severity of lactose intolerance symptoms — not supported",
            "Variant as predictor of dairy fat or casein intolerance — different mechanism",
        ],
    },
    {
        "record_id": "hfe_c282y_iron",
        "variant": {
            "rsid": "rs1800562",
            "chrom": "6",
            "pos_grch38": 26092913,
            "ref": "G",
            "alt": "A",
            "hgvs_p": "p.Cys282Tyr",
        },
        "gene": {"symbol": "HFE", "hgnc_id": "HGNC:4886"},
        "domain": "iron_storage",
        "effect_allele": "A",
        "established_effect": {
            "claim": (
                "C282Y is the principal allele for HFE-related hereditary hemochromatosis. "
                "Penetrance is incomplete; homozygous or compound-heterozygous status with H63D "
                "carries the strongest clinical context."
            ),
            "mechanism": "Loss of HFE function disrupts hepcidin regulation of intestinal iron absorption",
            "downstream_traits_with_gwas": [
                {"trait": "serum ferritin", "gwas_catalog_id": "EFO_0004291"},
                {"trait": "transferrin saturation", "gwas_catalog_id": "EFO_0004785"},
            ],
        },
        "evidence_tier": "established",
        "sources": [
            {
                "source": "GeneReviews HFE-related hemochromatosis",
                "evidence_type": "expert_curation",
                "identifier": "Bookshelf:NBK1440",
                "url": "https://www.ncbi.nlm.nih.gov/books/NBK1440/",
            },
            {
                "source": "ClinVar rs1800562",
                "evidence_type": "clinical_curation",
                "identifier": "VCV:9",
                "url": "https://www.ncbi.nlm.nih.gov/clinvar/variation/9/",
            },
        ],
        "established_caveats": [
            "Penetrance is incomplete — most homozygotes never develop clinical iron overload",
            "Single heterozygous C282Y is carrier/risk context, not hemochromatosis diagnosis",
            "Must be interpreted alongside HFE H63D (rs1799945) and iron labs (ferritin, transferrin saturation)",
        ],
        "out_of_scope_claims": [
            "Therapeutic phlebotomy decisions on genotype alone without iron labs — not supported",
            "Heterozygous C282Y as basis for iron supplementation avoidance without ferritin data",
        ],
    },
    {
        "record_id": "hfe_h63d_iron",
        "variant": {
            "rsid": "rs1799945",
            "chrom": "6",
            "pos_grch38": 26091179,
            "ref": "C",
            "alt": "G",
            "hgvs_p": "p.His63Asp",
        },
        "gene": {"symbol": "HFE", "hgnc_id": "HGNC:4886"},
        "domain": "iron_storage",
        "effect_allele": "G",
        "established_effect": {
            "claim": (
                "H63D is the secondary HFE allele. Single H63D rarely causes clinical "
                "hemochromatosis; relevant primarily in compound-heterozygous C282Y/H63D context."
            ),
            "mechanism": "Reduced HFE function with lower penetrance than C282Y",
            "downstream_traits_with_gwas": [
                {"trait": "serum ferritin", "gwas_catalog_id": "EFO_0004291"},
            ],
        },
        "evidence_tier": "probable",
        "sources": [
            {
                "source": "GeneReviews HFE-related hemochromatosis",
                "evidence_type": "expert_curation",
                "identifier": "Bookshelf:NBK1440",
                "url": "https://www.ncbi.nlm.nih.gov/books/NBK1440/",
            },
            {
                "source": "ClinVar rs1799945",
                "evidence_type": "clinical_curation",
                "identifier": "VCV:10",
                "url": "https://www.ncbi.nlm.nih.gov/clinvar/variation/10/",
            },
        ],
        "established_caveats": [
            "Single H63D allele is rarely sufficient for hemochromatosis diagnosis",
            "Clinical penetrance is limited; interpret only with C282Y status and iron labs",
        ],
        "out_of_scope_claims": [
            "Single H63D as iron-overload diagnosis — not supported",
        ],
    },
    {
        "record_id": "gc_vitamin_d",
        "variant": {"rsid": "rs4588", "chrom": "4"},
        "gene": {"symbol": "GC", "hgnc_id": "HGNC:4187"},
        "domain": "vitamin_d_status",
        "effect_allele": "T",
        "established_effect": {
            "claim": (
                "GC (vitamin D binding protein) common variant associated with 25(OH)D level "
                "differences in GWAS meta-analyses."
            ),
            "mechanism": "Affects vitamin D binding protein affinity / clearance",
            "downstream_traits_with_gwas": [
                {"trait": "serum 25-hydroxyvitamin D level", "gwas_catalog_id": "EFO_0004631"},
            ],
        },
        "evidence_tier": "established",
        "sources": [
            {
                "source": "Vitamin D GWAS meta-analysis (Wang et al. Lancet 2010)",
                "evidence_type": "primary_literature",
                "identifier": "PMID:20541252",
                "url": "https://pubmed.ncbi.nlm.nih.gov/20541252/",
            },
            {
                "source": "Vitamin D genetics replication",
                "evidence_type": "primary_literature",
                "identifier": "PMID:22205959",
                "url": "https://pubmed.ncbi.nlm.nih.gov/22205959/",
            },
        ],
        "established_caveats": [
            "Effect size is small relative to sun exposure, diet, BMI, season, skin pigmentation, "
            "and supplementation",
            "Genotype does not substitute for serum 25(OH)D measurement",
        ],
        "out_of_scope_claims": [
            "Vitamin D megadose prescription based on genotype — not supported",
            "Genotype as substitute for serum 25(OH)D measurement — not supported",
        ],
    },
    {
        "record_id": "cyp2r1_vitamin_d",
        "variant": {"rsid": "rs10741657", "chrom": "11"},
        "gene": {"symbol": "CYP2R1", "hgnc_id": "HGNC:20580"},
        "domain": "vitamin_d_status",
        "effect_allele": "G",
        "established_effect": {
            "claim": (
                "CYP2R1 common variant associated with 25(OH)D differences in GWAS meta-analyses. "
                "CYP2R1 is the principal 25-hydroxylase of vitamin D."
            ),
            "mechanism": "Affects 25-hydroxylation efficiency",
            "downstream_traits_with_gwas": [
                {"trait": "serum 25-hydroxyvitamin D level", "gwas_catalog_id": "EFO_0004631"},
            ],
        },
        "evidence_tier": "established",
        "sources": [
            {
                "source": "Vitamin D GWAS meta-analysis (Wang et al. Lancet 2010)",
                "evidence_type": "primary_literature",
                "identifier": "PMID:20541252",
                "url": "https://pubmed.ncbi.nlm.nih.gov/20541252/",
            },
        ],
        "established_caveats": [
            "Small common-variant effect; environment and clinical factors are usually larger",
            "Not a deficiency diagnosis",
        ],
        "out_of_scope_claims": [
            "Genotype-targeted vitamin D dosing without serum 25(OH)D measurement — not supported",
        ],
    },
    {
        "record_id": "dhcr7_vitamin_d",
        "variant": {"rsid": "rs12785878", "chrom": "11"},
        "gene": {"symbol": "DHCR7", "hgnc_id": "HGNC:2860", "linked_locus": "NADSYN1"},
        "domain": "vitamin_d_status",
        "effect_allele": "G",
        "established_effect": {
            "claim": (
                "DHCR7/NADSYN1 locus common variant associated with 25(OH)D differences. "
                "DHCR7 affects substrate availability for vitamin D synthesis from cholesterol."
            ),
            "mechanism": "Substrate flux to 7-dehydrocholesterol",
            "downstream_traits_with_gwas": [
                {"trait": "serum 25-hydroxyvitamin D level", "gwas_catalog_id": "EFO_0004631"},
            ],
        },
        "evidence_tier": "established",
        "sources": [
            {
                "source": "Vitamin D GWAS meta-analysis (Wang et al. Lancet 2010)",
                "evidence_type": "primary_literature",
                "identifier": "PMID:20541252",
                "url": "https://pubmed.ncbi.nlm.nih.gov/20541252/",
            },
        ],
        "established_caveats": [
            "Small common-variant effect",
            "Genotype does not substitute for measured 25(OH)D",
        ],
        "out_of_scope_claims": [
            "Vitamin D supplement dosing on genotype alone — not supported",
        ],
    },
    {
        "record_id": "apoe_rs429358",
        "variant": {
            "rsid": "rs429358",
            "chrom": "19",
            "pos_grch38": 44908684,
            "ref": "T",
            "alt": "C",
        },
        "gene": {"symbol": "APOE", "hgnc_id": "HGNC:613"},
        "domain": "lipid_diet_response",
        "effect_allele": "C",
        "established_effect": {
            "claim": (
                "One of two variants that together define APOE e2/e3/e4 isoform status "
                "(combined with rs7412). APOE isoforms influence LDL cholesterol and triglyceride "
                "levels and modify response to dietary lipid composition in some studies."
            ),
            "mechanism": "Defines APOE isoform with downstream effects on lipoprotein metabolism",
            "downstream_traits_with_gwas": [
                {"trait": "LDL cholesterol", "gwas_catalog_id": "EFO_0004611"},
                {"trait": "total cholesterol", "gwas_catalog_id": "EFO_0004574"},
            ],
            "haplotype_partner": "rs7412 (required for e2/e3/e4 assignment)",
        },
        "evidence_tier": "established",
        "sources": [
            {
                "source": "GeneReviews Alzheimer Disease Overview",
                "evidence_type": "expert_curation",
                "identifier": "Bookshelf:NBK1161",
                "url": "https://www.ncbi.nlm.nih.gov/books/NBK1161/",
            },
            {
                "source": "MedlinePlus APOE",
                "evidence_type": "expert_curation",
                "url": "https://medlineplus.gov/genetics/gene/apoe/",
            },
        ],
        "established_caveats": [
            "Requires rs7412 for isoform assignment; unphased genotypes can be ambiguous",
            "Diet-response effect sizes are contested in RCTs",
            "Diet-disease outcome interpretations must include family history, lipid panel, BMI, and lifestyle",
        ],
        "out_of_scope_claims": [
            "APOE genotype as basis for specific macronutrient ratio prescriptions — not supported",
            "APOE genotype as deterministic predictor of Alzheimer disease — not supported",
            "APOE-based dietary fat type prescriptions (saturated vs unsaturated) — limited RCT evidence",
        ],
    },
    {
        "record_id": "apoe_rs7412",
        "variant": {
            "rsid": "rs7412",
            "chrom": "19",
            "pos_grch38": 44908822,
            "ref": "C",
            "alt": "T",
        },
        "gene": {"symbol": "APOE", "hgnc_id": "HGNC:613"},
        "domain": "lipid_diet_response",
        "effect_allele": "T",
        "established_effect": {
            "claim": (
                "Second of two variants that together define APOE e2/e3/e4 isoform status "
                "(combined with rs429358)."
            ),
            "mechanism": "Defines APOE isoform with downstream effects on lipoprotein metabolism",
            "downstream_traits_with_gwas": [
                {"trait": "LDL cholesterol", "gwas_catalog_id": "EFO_0004611"},
            ],
            "haplotype_partner": "rs429358 (required for e2/e3/e4 assignment)",
        },
        "evidence_tier": "established",
        "sources": [
            {
                "source": "GeneReviews Alzheimer Disease Overview",
                "evidence_type": "expert_curation",
                "identifier": "Bookshelf:NBK1161",
                "url": "https://www.ncbi.nlm.nih.gov/books/NBK1161/",
            },
            {
                "source": "MedlinePlus APOE",
                "evidence_type": "expert_curation",
                "url": "https://medlineplus.gov/genetics/gene/apoe/",
            },
        ],
        "established_caveats": [
            "Requires rs429358 for isoform assignment",
            "Not a diagnosis; clinical lipid measurements and family history dominate decisions",
        ],
        "out_of_scope_claims": [
            "APOE-based diet prescriptions without clinical lipid context — not supported",
        ],
    },
    {
        "record_id": "fto_rs1421085",
        "variant": {
            "rsid": "rs1421085",
            "chrom": "16",
            "pos_grch38": 53767042,
            "ref": "T",
            "alt": "C",
        },
        "gene": {"symbol": "FTO", "hgnc_id": "HGNC:24678"},
        "domain": "obesity_predisposition",
        "effect_allele": "C",
        "established_effect": {
            "claim": (
                "Common FTO-locus risk allele associated with higher BMI in population studies. "
                "Functional studies link the variant to IRX3/IRX5 regulation in adipocyte progenitor "
                "browning. Effect per allele is small relative to environment and lifestyle."
            ),
            "mechanism": "Disrupted ARID5B repression of IRX3/IRX5 in adipocyte progenitors",
            "downstream_traits_with_gwas": [
                {"trait": "body mass index", "gwas_catalog_id": "EFO_0004340"},
                {"trait": "obesity", "gwas_catalog_id": "EFO_0001073"},
            ],
        },
        "evidence_tier": "established",
        "sources": [
            {
                "source": "FTO BMI GWAS (Frayling et al. Science 2007)",
                "evidence_type": "primary_literature",
                "identifier": "PMID:17434869",
                "url": "https://pubmed.ncbi.nlm.nih.gov/17434869/",
            },
            {
                "source": "FTO rs1421085 functional study (Claussnitzer et al. NEJM 2015)",
                "evidence_type": "primary_literature",
                "identifier": "PMID:26287746",
                "url": "https://pubmed.ncbi.nlm.nih.gov/26287746/",
            },
        ],
        "established_caveats": [
            "Single SNP has limited predictive value for individual BMI",
            "Effect is on baseline BMI, not on weight-loss intervention response",
            "Activity, diet, and clinical context dominate individual outcomes",
        ],
        "out_of_scope_claims": [
            "FTO genotype as basis for diet-matching for weight loss — not supported",
            "FTO genotype as predictor of weight-loss intervention response — not supported",
            "FTO genotype as deterministic predictor of obesity — not supported",
        ],
    },
]


_DOMAIN_INDEX: dict[str, list[dict[str, Any]]] | None = None
_VARIANT_INDEX: dict[str, list[dict[str, Any]]] | None = None


def _build_indices() -> None:
    global _DOMAIN_INDEX, _VARIANT_INDEX
    domain_index: dict[str, list[dict[str, Any]]] = {}
    variant_index: dict[str, list[dict[str, Any]]] = {}
    for record in DOMAIN_MARKER_RECORDS:
        domain_index.setdefault(record["domain"], []).append(record)
        rsid = record.get("variant", {}).get("rsid")
        if rsid:
            variant_index.setdefault(rsid.lower(), []).append(record)
    _DOMAIN_INDEX = domain_index
    _VARIANT_INDEX = variant_index


def domain_records(domain_id: str, *, min_evidence_tier: str = "established") -> list[dict[str, Any]]:
    if _DOMAIN_INDEX is None:
        _build_indices()
    records = list(_DOMAIN_INDEX.get(domain_id, []))  # type: ignore[union-attr]
    if not records:
        return []
    tier_rank = {"established": 3, "probable": 2, "emerging": 1}
    threshold = tier_rank.get(min_evidence_tier, 3)
    return [r for r in records if tier_rank.get(r.get("evidence_tier", ""), 0) >= threshold]


def variant_records(rsid: str) -> list[dict[str, Any]]:
    if _VARIANT_INDEX is None:
        _build_indices()
    return list(_VARIANT_INDEX.get(rsid.lower(), []))  # type: ignore[union-attr]


def domain_summary() -> list[dict[str, Any]]:
    if _DOMAIN_INDEX is None:
        _build_indices()
    summary: list[dict[str, Any]] = []
    for domain_id, definition in source_context.DOMAIN_DEFINITIONS.items():
        records = _DOMAIN_INDEX.get(domain_id, []) if _DOMAIN_INDEX else []  # type: ignore[union-attr]
        tier_counts = {"established": 0, "probable": 0, "emerging": 0}
        for record in records:
            tier = record.get("evidence_tier", "")
            if tier in tier_counts:
                tier_counts[tier] += 1
        summary.append({
            "domain_id": domain_id,
            "label": definition["label"],
            "scope": definition["scope"],
            "marker_count": len(records),
            "evidence_tier_summary": tier_counts,
            "downstream_traits": definition.get("downstream_traits", []),
            "primary_sources": definition.get("primary_sources", []),
            "out_of_scope_claims_examples": definition.get("common_pseudoscience_claims_disowned", []),
        })
    return summary
