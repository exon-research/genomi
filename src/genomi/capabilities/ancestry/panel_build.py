"""Local panel-build helpers for the ancestry capability.

The canonical 1000G 30x panel is built on GRCh38 by the external
``genomi-ancestry-panel`` project and distributed as a release tarball
(see ``scripts/install_for_agents.py``). The GRCh37 variant is produced
here, locally, by lifting the GRCh38 panel's marker coordinates across via
``genomi.runtime.liftover``. The PCA loadings and reference sample scores
are coordinate-free, so they are reused verbatim against the lifted
marker IDs.

This module is invoked from the installer; query-time selection of which
panel to use for a given Active Genome Index is handled separately.
"""

from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...runtime.liftover import LiftoverConfigurationError, get_liftover
from ...runtime.paths import ancestry_reference_panel_dir
from . import reference_panels, source_context

PANEL_BUILD_SCHEMA = "genomi-ancestry-panel-build-v1"


class PanelBuildError(RuntimeError):
    """Raised when a local panel build cannot proceed."""


def build_grch37_panel_from_grch38(
    *,
    force: bool = False,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Produce the GRCh37 panel by lifting the installed GRCh38 panel.

    Requires the ``ancestry-1000g-30x-grch38`` panel and the
    ``liftover-chains`` library to be installed first. The output panel
    is written to ``<genomi-home>/reference/ancestry/1000g_30x_grch37/``
    with the same file layout as the source panel; only ``markers.tsv``
    (chrom + pos + marker_id) and ``pca_loadings.tsv`` (joined by
    marker_id) change. ``samples.tsv`` and ``reference_scores.tsv`` are
    coordinate-free and copied verbatim.

    Markers that fail to lift (chain gap, strand-flipped) are dropped from
    both ``markers.tsv`` and ``pca_loadings.tsv`` so the two stay in lock
    step. Counts and the source-panel pointer are recorded in the new
    manifest.
    """

    source_dir = ancestry_reference_panel_dir(source_context.PANEL_ID_GRCH38, root=root)
    target_dir = ancestry_reference_panel_dir(source_context.PANEL_ID_GRCH37, root=root)

    source_paths = _expected_panel_paths(source_dir)
    missing_source = [path for path in source_paths.values() if not path.exists()]
    if missing_source:
        raise PanelBuildError(
            f"{source_context.PANEL_LIBRARY_GRCH38} is not installed; "
            f"missing {missing_source[0]}. Install with: "
            f"python3 scripts/install_for_agents.py --libraries "
            f"{source_context.PANEL_LIBRARY_GRCH38}"
        )

    target_paths = _expected_panel_paths(target_dir)
    if not force and all(path.exists() for path in target_paths.values()):
        return {
            "schema": PANEL_BUILD_SCHEMA,
            "status": "cached",
            "panel_id": source_context.PANEL_ID_GRCH37,
            "library": source_context.PANEL_LIBRARY_GRCH37,
            "genome_build": "GRCh37",
            "panel_dir": str(target_dir),
            "source_panel_id": source_context.PANEL_ID_GRCH38,
        }

    # The liftover chain files are a system-wide resource keyed off the
    # default GENOMI_HOME; the ``root`` parameter scopes only the ancestry
    # panel directories so tests can isolate panel I/O without having to copy
    # the chain library into a temp tree.
    try:
        lifter = get_liftover("GRCh38", "GRCh37")
    except LiftoverConfigurationError as exc:
        raise PanelBuildError(
            f"liftover-chains library is required to build the GRCh37 ancestry panel: {exc}"
        ) from exc

    target_dir.mkdir(parents=True, exist_ok=True)

    markers, marker_id_remap, dropped = _lift_markers(source_paths["markers"], lifter)
    _write_markers(target_paths["markers"], markers)
    _write_pca_loadings(source_paths["pca_loadings"], target_paths["pca_loadings"], marker_id_remap)
    shutil.copyfile(source_paths["samples"], target_paths["samples"])
    shutil.copyfile(source_paths["reference_scores"], target_paths["reference_scores"])

    source_manifest = _read_json(source_paths["manifest"])
    source_stats = _read_json(source_paths["panel_stats"])
    manifest = _build_manifest(source_manifest, len(markers), len(dropped))
    stats = _build_stats(source_stats, len(markers), len(dropped))
    _write_json(target_paths["manifest"], manifest)
    _write_json(target_paths["panel_stats"], stats)

    return {
        "schema": PANEL_BUILD_SCHEMA,
        "status": "completed",
        "panel_id": source_context.PANEL_ID_GRCH37,
        "library": source_context.PANEL_LIBRARY_GRCH37,
        "genome_build": "GRCh37",
        "panel_dir": str(target_dir),
        "source_panel_id": source_context.PANEL_ID_GRCH38,
        "source_panel_dir": str(source_dir),
        "marker_count": len(markers),
        "dropped_marker_count": len(dropped),
        "dropped_reasons": _summarize_drop_reasons(dropped),
        "files": {name: str(path) for name, path in target_paths.items()},
    }


def _expected_panel_paths(panel_dir: Path) -> dict[str, Path]:
    return {
        "manifest": panel_dir / reference_panels.MANIFEST_NAME,
        "samples": panel_dir / reference_panels.SAMPLES_NAME,
        "markers": panel_dir / reference_panels.MARKERS_NAME,
        "pca_loadings": panel_dir / reference_panels.LOADINGS_NAME,
        "reference_scores": panel_dir / reference_panels.REFERENCE_SCORES_NAME,
        "panel_stats": panel_dir / reference_panels.PANEL_STATS_NAME,
    }


def _lift_markers(
    markers_path: Path, lifter: Any
) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    lifted: list[dict[str, Any]] = []
    remap: dict[str, str] = {}
    dropped: list[dict[str, Any]] = []
    with markers_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            chrom = row["chrom"]
            pos = int(row["pos"])
            full = lifter.lift_position_full(chrom, pos)
            old_marker_id = row["marker_id"]
            if full is None:
                dropped.append({"marker_id": old_marker_id, "reason": "unmapped"})
                continue
            target_chrom, target_pos, strand = full
            if strand != "+":
                dropped.append({"marker_id": old_marker_id, "reason": "strand_flipped"})
                continue
            new_marker_id = _make_marker_id(target_chrom, target_pos, row["ref"], row["alt"])
            lifted.append(
                {
                    "marker_id": new_marker_id,
                    "chrom": target_chrom,
                    "pos": target_pos,
                    "ref": row["ref"],
                    "alt": row["alt"],
                    "mean": row["mean"],
                    "scale": row["scale"],
                }
            )
            remap[old_marker_id] = new_marker_id
    return lifted, remap, dropped


def _make_marker_id(chrom: str, pos: int, ref: str, alt: str) -> str:
    # Source panel stores chrom without "chr" prefix (e.g. "1", "X").
    # Liftover preserves the caller's prefix style, so chrom comes back
    # without "chr" here; assert defensively in case that ever changes.
    bare_chrom = chrom[3:] if chrom.startswith("chr") else chrom
    return f"{bare_chrom}:{pos}:{ref}:{alt}"


def _write_markers(path: Path, markers: list[dict[str, Any]]) -> None:
    fieldnames = ["marker_id", "chrom", "pos", "ref", "alt", "mean", "scale"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in markers:
            writer.writerow(row)


def _write_pca_loadings(
    source: Path, target: Path, marker_id_remap: dict[str, str]
) -> None:
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
        fieldnames = reader.fieldnames or ["marker_id"]
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            new_marker_id = marker_id_remap.get(row["marker_id"])
            if new_marker_id is None:
                continue
            new_row = dict(row)
            new_row["marker_id"] = new_marker_id
            writer.writerow(new_row)


def _build_manifest(
    source_manifest: dict[str, Any], marker_count: int, dropped_count: int
) -> dict[str, Any]:
    manifest = dict(source_manifest)
    manifest.update(
        {
            "panel_id": source_context.PANEL_ID_GRCH37,
            "library": source_context.PANEL_LIBRARY_GRCH37,
            "genome_build": "GRCh37",
            "marker_count": marker_count,
            "built_at": _utc_now(),
            "source_panel_id": source_context.PANEL_ID_GRCH38,
            "source_genome_build": "GRCh38",
            "lifted_with": "UCSC hg38ToHg19 chain (pyliftover)",
            "lifted_marker_count": marker_count,
            "dropped_marker_count": dropped_count,
            "files": {
                "markers": reference_panels.MARKERS_NAME,
                "panel_stats": reference_panels.PANEL_STATS_NAME,
                "pca_loadings": reference_panels.LOADINGS_NAME,
                "reference_scores": reference_panels.REFERENCE_SCORES_NAME,
                "samples": reference_panels.SAMPLES_NAME,
            },
        }
    )
    return manifest


def _build_stats(
    source_stats: dict[str, Any], marker_count: int, dropped_count: int
) -> dict[str, Any]:
    stats = dict(source_stats)
    stats.update(
        {
            "panel_id": source_context.PANEL_ID_GRCH37,
            "genome_build": "GRCh37",
            "marker_count": marker_count,
            "source_panel_id": source_context.PANEL_ID_GRCH38,
            "source_genome_build": "GRCh38",
            "dropped_marker_count": dropped_count,
        }
    )
    return stats


def _summarize_drop_reasons(dropped: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in dropped:
        reason = entry.get("reason", "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
