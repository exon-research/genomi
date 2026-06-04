from __future__ import annotations

from dataclasses import dataclass
from typing import Any

JsonObject = dict[str, Any]


@dataclass(frozen=True)
class AncestryPanelPolicy:
    genome_build: str
    aliases: tuple[str, ...]
    panel_id: str
    library: str
    title: str
    source: str
    source_panel_id: str | None = None
    source_genome_build: str | None = None
    build_method: str | None = None


PANELS: tuple[AncestryPanelPolicy, ...] = (
    AncestryPanelPolicy(
        genome_build="GRCh38",
        aliases=("grch38", "hg38", "38", "b38"),
        panel_id="1000g_30x_grch38",
        library="ancestry-1000g-30x-grch38",
        title="1000 Genomes 30x GRCh38 ancestry PCA panel",
        source="IGSR / 1000 Genomes Project 30x GRCh38 collection",
    ),
    AncestryPanelPolicy(
        genome_build="GRCh37",
        aliases=("grch37", "hg19", "37", "b37"),
        panel_id="1000g_30x_grch37",
        library="ancestry-1000g-30x-grch37",
        title="1000 Genomes 30x ancestry PCA panel lifted to GRCh37",
        source="IGSR / 1000 Genomes Project 30x GRCh38 collection, lifted locally to GRCh37",
        source_panel_id="1000g_30x_grch38",
        source_genome_build="GRCh38",
        build_method="produced locally by lifting the GRCh38 panel via UCSC chain files",
    ),
)
SUPPORTED_BUILDS: tuple[str, ...] = tuple(panel.genome_build for panel in PANELS)
PANEL_LIBRARIES: tuple[str, ...] = tuple(panel.library for panel in PANELS)

HIGH_OVERLAP_FRACTION = 0.80
MODERATE_OVERLAP_FRACTION = 0.50
LOW_OVERLAP_FRACTION = 0.20


def normalize_build(value: str | None, *, default: str = "GRCh38") -> str:
    text = str(value or default).strip()
    normalized = text.lower()
    if not normalized:
        normalized = default.lower()
    for panel in PANELS:
        if normalized == panel.genome_build.lower() or normalized in panel.aliases:
            return panel.genome_build
    return text or default


def panel_for_build(genome_build: str | None) -> AncestryPanelPolicy:
    normalized = normalize_build(genome_build)
    for panel in PANELS:
        if panel.genome_build == normalized:
            return panel
    raise ValueError(f"unsupported genome build for ancestry panel: {genome_build}")


def supported_build_payload() -> list[JsonObject]:
    return [
        {
            "genome_build": panel.genome_build,
            "aliases": list(panel.aliases),
            "panel_id": panel.panel_id,
            "library": panel.library,
            "title": panel.title,
            **(
                {
                    "source_panel_id": panel.source_panel_id,
                    "source_genome_build": panel.source_genome_build,
                    "build_method": panel.build_method,
                }
                if panel.source_panel_id
                else {}
            ),
        }
        for panel in PANELS
    ]


def overlap_thresholds() -> JsonObject:
    return {
        "graded_by": "fraction of loaded panel covered by usable sample dosages",
        "high_overlap_fraction": f">={HIGH_OVERLAP_FRACTION:.0%}",
        "moderate_overlap_fraction": f">={MODERATE_OVERLAP_FRACTION:.0%}",
        "low_overlap_fraction": f">={LOW_OVERLAP_FRACTION:.0%}",
        "absolute_marker_floor": None,
    }


def overlap_status(fraction: float) -> str:
    if fraction < LOW_OVERLAP_FRACTION:
        return "low_overlap"
    return "completed"


def marker_overlap_quality(fraction: float) -> str:
    if fraction >= HIGH_OVERLAP_FRACTION:
        return "high"
    if fraction >= MODERATE_OVERLAP_FRACTION:
        return "moderate"
    if fraction >= LOW_OVERLAP_FRACTION:
        return "low"
    return "insufficient"


def overlap_note(fraction: float) -> str:
    pct = f"{fraction:.0%}"
    if fraction >= HIGH_OVERLAP_FRACTION:
        return f"Projection covers {pct} of the loaded panel; high marker-overlap quality."
    if fraction >= MODERATE_OVERLAP_FRACTION:
        return f"Projection covers {pct} of the loaded panel; moderate marker-overlap quality."
    if fraction >= LOW_OVERLAP_FRACTION:
        return f"Projection covers {pct} of the loaded panel; low marker-overlap quality; reference-neighbor context only."
    return f"Projection covers only {pct} of the loaded panel; do not produce a default reference-similarity interpretation."
