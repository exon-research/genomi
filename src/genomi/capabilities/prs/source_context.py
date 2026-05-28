from __future__ import annotations

from typing import Any

JsonObject = dict[str, Any]
CAPABILITY_ID = "polygenic-score"
PGS_CATALOG_REST = "https://www.pgscatalog.org/rest"
PGS_CATALOG_DOWNLOADS = "https://www.pgscatalog.org/downloads/"
PGS_CATALOG_METADATA_CSV = "https://ftp.ebi.ac.uk/pub/databases/spot/pgs/metadata/pgs_all_metadata_scores.csv"
PGS_CATALOG_ANCESTRY_DOCS = "https://www.pgscatalog.org/docs/ancestry/"
PGS_CATALOG_FAQ = "https://www.pgscatalog.org/docs/faq/"


def source_urls() -> JsonObject:
    return {
        "pgs_catalog": "https://www.pgscatalog.org/",
        "rest_api": PGS_CATALOG_REST,
        "downloads": PGS_CATALOG_DOWNLOADS,
        "score_metadata_csv": PGS_CATALOG_METADATA_CSV,
        "ancestry_and_evaluation_guidance": PGS_CATALOG_ANCESTRY_DOCS,
        "faq": PGS_CATALOG_FAQ,
    }


def limitations() -> list[str]:
    return [
        "Polygenic scores are published score formulas applied to observed genotypes; this capability does not train or validate new risk models.",
        "The default genome build is GRCh38 when omitted, and it is reported in defaults_applied. Use GRCh37 only with a matching imported scoring file and Active Genome Index.",
        "The output is a raw weighted score unless an explicit calibration mean and standard deviation are supplied. A raw score is not an absolute risk, diagnosis, or clinical category.",
        "Missing variants, low overlap, imputation differences, strand/build harmonization, array versus WGS coverage, and source population mismatch can materially change score behavior.",
        "Performance and portability depend on the score's development and evaluation cohorts. Reported ancestry labels are cohort/source descriptors, not personal identity labels.",
        "Private genotype data stays local. Genomi may fetch public scoring files and metadata, but it does not upload personal genotypes to external APIs.",
    ]


def build_source_context() -> JsonObject:
    return {
        "schema": "genomi-prs-source-context-v1",
        "status": "completed",
        "source": {
            "name": "PGS Catalog",
            "description": "Public catalog of published polygenic scores, score metadata, source publications, performance records, and downloadable scoring files.",
            "source_urls": source_urls(),
        },
        "method_boundaries": {
            "does": [
                "Search public PGS Catalog metadata.",
                "Import public or local scoring files into a local Genomi score cache.",
                "Check local genotype overlap against a selected score.",
                "Apply effect weights to approved local genotypes and return raw weighted score context.",
                "Optionally standardize the raw score when a matching calibration mean and standard deviation are supplied.",
            ],
            "does_not": [
                "Train new PRS models from GWAS summary statistics.",
                "Impute unobserved variants.",
                "Return diagnosis, absolute disease risk, treatment guidance, or clinical category without an explicit validated calibration model.",
                "Upload private genotypes to PGS Catalog or any other external service.",
            ],
        },
        "default_policy": {
            "genome_build": "GRCh38",
            "disclosure": "Private PRS tools report this default in defaults_applied when genome_build is omitted.",
            "override": "Use genome_build='GRCh37' only when the imported scoring file and Active Genome Index are both GRCh37/hg19.",
        },
        "limitations": limitations(),
    }
