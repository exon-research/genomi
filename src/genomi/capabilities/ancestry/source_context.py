from __future__ import annotations

from typing import Any

PANEL_ID_GRCH38 = "1000g_30x_grch38"
PANEL_LIBRARY_GRCH38 = "ancestry-1000g-30x-grch38"
PANEL_TITLE_GRCH38 = "1000 Genomes 30x GRCh38 ancestry PCA panel"
PANEL_ID_GRCH37 = "1000g_30x_grch37"
PANEL_LIBRARY_GRCH37 = "ancestry-1000g-30x-grch37"
PANEL_TITLE_GRCH37 = (
    "1000 Genomes 30x ancestry PCA panel lifted to GRCh37"
)
# Default panel for legacy single-panel callers. The GRCh38 panel is the
# canonical build (PCA loadings + reference scores were computed against the
# 30x GRCh38 cohort); the GRCh37 panel is the same loadings with marker
# coordinates lifted across.
PANEL_ID = PANEL_ID_GRCH38
PANEL_LIBRARY = PANEL_LIBRARY_GRCH38
PANEL_TITLE = PANEL_TITLE_GRCH38


def panel_id_for_build(genome_build: str) -> str:
    build = (genome_build or "").strip().lower()
    if build in {"grch38", "hg38", "38", "b38"}:
        return PANEL_ID_GRCH38
    if build in {"grch37", "hg19", "37", "b37"}:
        return PANEL_ID_GRCH37
    raise ValueError(f"unsupported genome build for ancestry panel: {genome_build}")


def panel_library_for_build(genome_build: str) -> str:
    build = (genome_build or "").strip().lower()
    if build in {"grch38", "hg38", "38", "b38"}:
        return PANEL_LIBRARY_GRCH38
    if build in {"grch37", "hg19", "37", "b37"}:
        return PANEL_LIBRARY_GRCH37
    raise ValueError(f"unsupported genome build for ancestry panel: {genome_build}")
# The panel is built and distributed by the genomi-ancestry-panel project.
# Genomi downloads the released tarball at install time and reads the
# extracted files at query time; it does not run the build itself. The
# tarball URL is configured at install time (see scripts/install_for_agents.py
# ANCESTRY_PANEL_TARBALL_URL).
IGSR_COLLECTION_URL = "https://www.internationalgenome.org/data-portal/data-collections/30x-grch38.html"
PUBLICATION_URL = "https://doi.org/10.1016/j.cell.2022.08.004"

SUPERPOPULATION_LABELS = {
    "AFR": "African reference-panel superpopulation label",
    "AMR": "Admixed American reference-panel superpopulation label",
    "EAS": "East Asian reference-panel superpopulation label",
    "EUR": "European reference-panel superpopulation label",
    "SAS": "South Asian reference-panel superpopulation label",
}

BOUNDARY_NOTE = (
    "The output is reference-panel similarity in PCA space. It is not ethnicity, nationality, race, tribe, caste, "
    "religion, or personal identity, and it is not an origin determination."
)


def source_urls() -> dict[str, str]:
    return {
        "igsr_collection": IGSR_COLLECTION_URL,
        "publication": PUBLICATION_URL,
    }


def label_definitions() -> dict[str, Any]:
    return {
        "label_scope": "1000 Genomes reference-panel sample labels",
        "superpopulation_labels": SUPERPOPULATION_LABELS,
        "population_labels": (
            "Population labels are the population codes assigned to reference samples by the 1000 Genomes Project. "
            "They are cohort labels for panel samples, not labels inferred for the user."
        ),
        "non_identity_boundary": BOUNDARY_NOTE,
    }


def limitations() -> list[str]:
    return [
        BOUNDARY_NOTE,
        "The MVP uses autosomal biallelic SNP markers and PCA projection only.",
        "No component/admixture proportions, haplogroups, local ancestry, ancestry dating, or relative matching are produced.",
        "The panel is selected by the sample's genome build (GRCh38 canonical; GRCh37 produced locally by lifting the GRCh38 panel via UCSC chain files).",
        "Reference clusters reflect 1000 Genomes sampling and cannot represent all populations or individual family histories.",
        "Private genotype data stays local; the ancestry tools do not upload sample genotypes to external APIs.",
    ]


def build_source_context() -> dict[str, Any]:
    return {
        "schema": "genomi-ancestry-source-context-v1",
        "status": "completed",
        "reference_panel": {
            "panel_id": PANEL_ID,
            "title": PANEL_TITLE,
            "library": PANEL_LIBRARY,
            "genome_build": "GRCh38",
            "source": "IGSR / 1000 Genomes Project 30x GRCh38 collection",
            "source_urls": source_urls(),
            "documented_sample_count": 3202,
            "phase3_unrelated_sample_count": 2504,
        },
        "label_definitions": label_definitions(),
        "method_scope": {
            "method": "PCA projection with reference-neighbor context",
            "included": [
                "local compact panel built from public reference genotypes",
                "marker overlap check",
                "sample projection into reference PCA space",
                "nearest reference samples and groups by PCA distance",
            ],
            "excluded": [
                "ethnicity prediction",
                "component or admixture proportions",
                "haplogroups",
                "local ancestry or chromosome painting",
                "relative matching",
                "external upload of private genotype data",
            ],
        },
        "limitations": limitations(),
    }

