from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ...runtime.paths import ancestry_reference_panel_dir
from . import source_context

JsonObject = dict[str, Any]
PANEL_ID = source_context.PANEL_ID
PANEL_LIBRARY = source_context.PANEL_LIBRARY
PANEL_TITLE = source_context.PANEL_TITLE
SUPPORTED_BUILDS: tuple[str, ...] = ("GRCh38", "GRCh37")
MANIFEST_NAME = "manifest.json"
SAMPLES_NAME = "samples.tsv"
MARKERS_NAME = "markers.tsv"
LOADINGS_NAME = "pca_loadings.tsv"
REFERENCE_SCORES_NAME = "reference_scores.tsv"
PANEL_STATS_NAME = "panel_stats.json"
PANEL_FILES = (
    MANIFEST_NAME,
    SAMPLES_NAME,
    MARKERS_NAME,
    LOADINGS_NAME,
    REFERENCE_SCORES_NAME,
    PANEL_STATS_NAME,
)


def panel_dir(genome_build: str = "GRCh38", root: str | Path | None = None) -> Path:
    return ancestry_reference_panel_dir(
        source_context.panel_id_for_build(genome_build), root=root
    )


def manifest_path(genome_build: str = "GRCh38", root: str | Path | None = None) -> Path:
    return panel_dir(genome_build, root) / MANIFEST_NAME


def panel_paths(
    genome_build: str = "GRCh38", root: str | Path | None = None
) -> dict[str, Path]:
    root_dir = panel_dir(genome_build, root)
    return {
        "panel_dir": root_dir,
        "manifest": root_dir / MANIFEST_NAME,
        "samples": root_dir / SAMPLES_NAME,
        "markers": root_dir / MARKERS_NAME,
        "pca_loadings": root_dir / LOADINGS_NAME,
        "reference_scores": root_dir / REFERENCE_SCORES_NAME,
        "panel_stats": root_dir / PANEL_STATS_NAME,
    }


def panel_installed(genome_build: str = "GRCh38", root: str | Path | None = None) -> bool:
    return all(
        path.exists()
        for name, path in panel_paths(genome_build, root).items()
        if name != "panel_dir"
    )


def list_reference_panels() -> JsonObject:
    from ...runtime.libraries import manager

    panel_records: list[JsonObject] = []
    install_actions: list[JsonObject] = []
    installed_count = 0
    for build in SUPPORTED_BUILDS:
        library = source_context.panel_library_for_build(build)
        panel_id = source_context.panel_id_for_build(build)
        title = (
            source_context.PANEL_TITLE_GRCH38
            if build == "GRCh38"
            else source_context.PANEL_TITLE_GRCH37
        )
        status = manager.status(library)
        paths = panel_paths(build)
        manifest = _read_json(paths["manifest"]) if status["installed"] else None
        stats = _read_json(paths["panel_stats"]) if paths["panel_stats"].exists() else {}
        installed = bool(status["installed"])
        if installed:
            installed_count += 1
        else:
            install_actions.append(
                {
                    "action": "install_library",
                    "library": library,
                    "install_command": status["install_command"],
                }
            )
        panel_records.append(
            {
                "panel_id": panel_id,
                "title": title,
                "library": library,
                "installed": installed,
                "status": status["status"],
                "genome_build": build,
                "method": "PCA projection and reference-neighbor context",
                "documented_source_sample_count": 3202,
                "phase3_unrelated_sample_count": 2504,
                "sample_count": _first_int(manifest, stats, "sample_count"),
                "marker_count": _first_int(manifest, stats, "marker_count"),
                "component_count": _first_int(manifest, stats, "component_count"),
                "manifest_path": str(paths["manifest"]),
                "required_paths": status["required_paths"],
                "missing_paths": status["missing_paths"],
                "source_urls": source_context.source_urls(),
                "label_definitions": source_context.label_definitions(),
                "limitations": source_context.limitations(),
                "install_command": status["install_command"],
                **(
                    {
                        "source_panel_id": source_context.PANEL_ID_GRCH38,
                        "source_genome_build": "GRCh38",
                        "build_method": "produced locally by lifting the GRCh38 panel via UCSC chain files",
                    }
                    if build == "GRCh37"
                    else {}
                ),
            }
        )
    return {
        "schema": "genomi-ancestry-reference-panels-v1",
        "status": "completed",
        "panels": panel_records,
        "summary": {
            "panel_count": len(panel_records),
            "installed_count": installed_count,
            "missing_count": len(panel_records) - installed_count,
        },
        "next_actions": install_actions,
    }


def require_panel_installed(
    genome_build: str = "GRCh38", root: str | Path | None = None
) -> None:
    paths = panel_paths(genome_build, root)
    missing = [path for name, path in paths.items() if name != "panel_dir" and not path.exists()]
    if missing:
        library = source_context.panel_library_for_build(genome_build)
        raise FileNotFoundError(f"{library} is not installed; missing {missing[0]}")


def load_panel(
    genome_build: str = "GRCh38", root: str | Path | None = None
) -> JsonObject:
    require_panel_installed(genome_build, root)
    paths = panel_paths(genome_build, root)
    manifest = _read_json(paths["manifest"])
    stats = _read_json(paths["panel_stats"])
    markers = _read_marker_rows(paths["markers"])
    loadings = _read_loading_rows(paths["pca_loadings"])
    samples = _read_tsv(paths["samples"])
    reference_scores = _read_reference_score_rows(paths["reference_scores"])
    marker_ids = [str(marker["marker_id"]) for marker in markers]
    missing_loading_ids = [marker_id for marker_id in marker_ids if marker_id not in loadings]
    if missing_loading_ids:
        raise ValueError(f"panel loadings missing marker IDs: {missing_loading_ids[:3]}")
    return {
        "manifest": manifest,
        "stats": stats,
        "markers": markers,
        "marker_ids": marker_ids,
        "loadings": [loadings[marker_id] for marker_id in marker_ids],
        "samples": samples,
        "reference_scores": reference_scores,
        "component_names": _component_names(reference_scores, loadings),
        "paths": {key: str(value) for key, value in paths.items()},
    }


def _first_int(*sources: object) -> int | None:
    key = str(sources[-1]) if sources and isinstance(sources[-1], str) else ""
    candidate_sources = sources[:-1] if key else sources
    for source in candidate_sources:
        if not isinstance(source, dict):
            continue
        value = source.get(key)
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _read_json(path: Path) -> JsonObject:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _read_tsv(path: Path) -> list[JsonObject]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def _read_marker_rows(path: Path) -> list[JsonObject]:
    rows = _read_tsv(path)
    markers = []
    for row in rows:
        marker = dict(row)
        marker["pos"] = int(marker["pos"])
        marker["mean"] = float(marker["mean"])
        marker["scale"] = float(marker["scale"])
        markers.append(marker)
    return markers


def _read_loading_rows(path: Path) -> dict[str, list[float]]:
    rows = _read_tsv(path)
    output: dict[str, list[float]] = {}
    for row in rows:
        marker_id = str(row.get("marker_id") or "")
        output[marker_id] = [float(value) for key, value in row.items() if key.startswith("PC")]
    return output


def _read_reference_score_rows(path: Path) -> list[JsonObject]:
    rows = _read_tsv(path)
    output = []
    for row in rows:
        payload = dict(row)
        payload["scores"] = [float(value) for key, value in row.items() if key.startswith("PC")]
        output.append(payload)
    return output


def _component_names(reference_scores: list[JsonObject], loadings: dict[str, list[float]]) -> list[str]:
    if reference_scores:
        return [key for key in reference_scores[0] if key.startswith("PC")]
    if loadings:
        first = next(iter(loadings.values()))
        return [f"PC{index + 1}" for index in range(len(first))]
    return []
