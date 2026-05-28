from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ...evidence import envelope as evidence_envelope
from . import overlap, reference_panels, source_context

JsonObject = dict[str, Any]


def project_sample_pca(
    vcf: str | Path,
    *,
    active_genome_index_path: str | Path | None = None,
    genome_build: str = "GRCh38",
    panel_root: str | Path | None = None,
    nearest_reference_count: int = 10,
) -> JsonObject:
    panel_or_missing = overlap._load_panel_or_missing(genome_build, panel_root, active_genome_index_path, vcf)
    if isinstance(panel_or_missing, dict) and panel_or_missing.get("status") == "panel_not_installed":
        result = {
            "schema": "genomi-ancestry-pca-projection-v1",
            "status": "panel_not_installed",
            "personal_context": {"uses_personal_dna": True},
            "reference_panel": panel_or_missing["reference_panel"],
            "sample_qc": panel_or_missing["sample_qc"],
            "pca_projection": None,
            "nearest_reference_groups": [],
            "limitations": source_context.limitations(),
            "next_actions": panel_or_missing["next_actions"],
        }
        result["evidence_envelope"] = _ancestry_envelope("ancestry.project_pca", result)
        return result
    panel = panel_or_missing
    genotype_context = overlap.collect_sample_genotypes(
        vcf,
        active_genome_index_path=active_genome_index_path,
        genome_build=genome_build,
        panel=panel,
    )
    sample_qc = genotype_context["sample_qc"]
    reference_panel = overlap._reference_panel_summary(panel)
    if not sample_qc.get("projection_allowed"):
        status = str(sample_qc.get("overlap_status") or "insufficient_overlap")
        result = {
            "schema": "genomi-ancestry-pca-projection-v1",
            "status": status,
            "personal_context": {"uses_personal_dna": True},
            "reference_panel": reference_panel,
            "sample_qc": sample_qc,
            "pca_projection": None,
            "nearest_reference_groups": [],
            "limitations": source_context.limitations(),
            "next_actions": _next_actions_for_blocked_projection(sample_qc),
        }
        result["evidence_envelope"] = _ancestry_envelope("ancestry.project_pca", result)
        return result

    projection = _project_from_genotypes(panel, genotype_context["dosages"], nearest_reference_count=nearest_reference_count)
    result = {
        "schema": "genomi-ancestry-pca-projection-v1",
        "status": "completed",
        "personal_context": {"uses_personal_dna": True},
        "reference_panel": reference_panel,
        "sample_qc": sample_qc,
        "pca_projection": projection["pca_projection"],
        "nearest_reference_groups": projection["nearest_reference_groups"],
        "limitations": source_context.limitations(),
        "next_actions": [{"action": "interpret_as_reference_similarity_only"}],
    }
    result["evidence_envelope"] = _ancestry_envelope("ancestry.project_pca", result)
    return result


def estimate_population_context(
    vcf: str | Path,
    *,
    active_genome_index_path: str | Path | None = None,
    genome_build: str = "GRCh38",
    panel_root: str | Path | None = None,
    nearest_reference_count: int = 10,
) -> JsonObject:
    projection_result = project_sample_pca(
        vcf,
        active_genome_index_path=active_genome_index_path,
        genome_build=genome_build,
        panel_root=panel_root,
        nearest_reference_count=nearest_reference_count,
    )
    status = projection_result["status"]
    interpretation = _interpretation(projection_result)
    result = {
        "schema": "genomi-ancestry-population-context-v1",
        "status": status,
        "personal_context": {"uses_personal_dna": True},
        "reference_panel": projection_result["reference_panel"],
        "sample_qc": projection_result["sample_qc"],
        "pca_projection": projection_result["pca_projection"],
        "nearest_reference_groups": projection_result["nearest_reference_groups"],
        "interpretation": interpretation,
        "limitations": source_context.limitations(),
        "next_actions": projection_result["next_actions"],
    }
    result["evidence_envelope"] = _ancestry_envelope("ancestry.estimate_population_context", result)
    return result


def _project_from_genotypes(panel: JsonObject, dosages: dict[str, float], *, nearest_reference_count: int) -> JsonObject:
    markers = list(panel["markers"])
    loadings = np.asarray(panel["loadings"], dtype=float)
    if loadings.ndim != 2 or loadings.shape[0] != len(markers):
        raise ValueError("ancestry panel PCA loadings do not match marker rows")
    z = np.zeros((len(markers),), dtype=float)
    used_marker_count = 0
    for index, marker in enumerate(markers):
        marker_id = str(marker["marker_id"])
        if marker_id not in dosages:
            continue
        scale = float(marker.get("scale") or 1.0)
        if scale <= 0:
            continue
        z[index] = (float(dosages[marker_id]) - float(marker.get("mean") or 0.0)) / scale
        used_marker_count += 1
    scores = z @ loadings
    component_names = panel.get("component_names") or [f"PC{index + 1}" for index in range(len(scores))]
    score_payload = {component_names[index]: float(scores[index]) for index in range(min(len(component_names), len(scores)))}
    nearest_samples = _nearest_reference_samples(scores, panel["reference_scores"], nearest_reference_count=nearest_reference_count)
    nearest_groups = _nearest_reference_groups(scores, panel["reference_scores"])
    return {
        "pca_projection": {
            "method": "mean/std-normalized genotype dosage projected onto stored reference PCA loadings",
            "component_scores": score_payload,
            "used_marker_count": used_marker_count,
            "missing_markers_imputed_to_panel_mean": len(markers) - used_marker_count,
            "nearest_reference_samples": nearest_samples,
            "distance_metric": "euclidean_distance_in_panel_pca_space",
        },
        "nearest_reference_groups": nearest_groups,
    }


def _nearest_reference_samples(scores: np.ndarray, reference_scores: list[JsonObject], *, nearest_reference_count: int) -> list[JsonObject]:
    rows = []
    for record in reference_scores:
        ref_scores = np.asarray(record.get("scores") or [], dtype=float)
        if ref_scores.shape != scores.shape:
            continue
        rows.append(
            {
                "sample_id": record.get("sample_id"),
                "population": record.get("population"),
                "superpopulation": record.get("superpopulation"),
                "distance": float(np.linalg.norm(scores - ref_scores)),
                "label_scope": "1000 Genomes reference-panel sample label",
            }
        )
    rows.sort(key=lambda item: float(item["distance"]))
    return rows[: max(1, int(nearest_reference_count))]


def _nearest_reference_groups(scores: np.ndarray, reference_scores: list[JsonObject]) -> list[JsonObject]:
    grouped: dict[tuple[str, str], list[np.ndarray]] = {}
    for record in reference_scores:
        ref_scores = np.asarray(record.get("scores") or [], dtype=float)
        if ref_scores.shape != scores.shape:
            continue
        for group_type in ("superpopulation", "population"):
            label = str(record.get(group_type) or "").strip()
            if not label:
                continue
            grouped.setdefault((group_type, label), []).append(ref_scores)
    rows = []
    for (group_type, label), vectors in grouped.items():
        matrix = np.vstack(vectors)
        centroid = np.mean(matrix, axis=0)
        distances = np.linalg.norm(matrix - scores, axis=1)
        rows.append(
            {
                "group_type": group_type,
                "label": label,
                "sample_count": len(vectors),
                "centroid_distance": float(np.linalg.norm(scores - centroid)),
                "mean_sample_distance": float(np.mean(distances)),
                "nearest_sample_distance": float(np.min(distances)),
                "label_scope": "1000 Genomes reference-panel population label",
            }
        )
    rows.sort(key=lambda item: (float(item["centroid_distance"]), item["group_type"], item["label"]))
    return rows


def _interpretation(result: JsonObject) -> JsonObject:
    status = str(result.get("status") or "")
    sample_qc = result.get("sample_qc") if isinstance(result.get("sample_qc"), dict) else {}
    groups = result.get("nearest_reference_groups") if isinstance(result.get("nearest_reference_groups"), list) else []
    superpop = next((item for item in groups if isinstance(item, dict) and item.get("group_type") == "superpopulation"), None)
    population = next((item for item in groups if isinstance(item, dict) and item.get("group_type") == "population"), None)
    if status != "completed":
        return {
            "summary": "No reference-panel similarity interpretation was produced.",
            "reason": sample_qc.get("note") or status,
            "marker_overlap_quality": sample_qc.get("marker_overlap_quality"),
            "language_boundary": source_context.BOUNDARY_NOTE,
        }
    pieces = []
    if superpop:
        pieces.append(f"The sample projects closest to the {superpop['label']} reference cluster in this panel.")
    if population:
        pieces.append(f"The nearest population-label centroid is {population['label']} within the same reference-panel context.")
    if not pieces:
        pieces.append("The sample was projected into the panel PCA space, but no labeled reference groups were available for comparison.")
    return {
        "summary": " ".join(pieces),
        "marker_overlap_quality": sample_qc.get("marker_overlap_quality"),
        "language_boundary": source_context.BOUNDARY_NOTE,
        "not_identity": True,
    }


def _next_actions_for_blocked_projection(sample_qc: JsonObject) -> list[JsonObject]:
    status = str(sample_qc.get("overlap_status") or "")
    if status == "panel_not_installed":
        return [
            {
                "action": "install_library",
                "library": sample_qc.get("required_library"),
                "install_command": sample_qc.get("install_command"),
                "reason": sample_qc.get("note"),
            }
        ]
    if status == "active_genome_index_incomplete":
        return [{"action": "parse_source", "operation": "genomi.parse_source"}]
    return [{"action": "do_not_interpret", "reason": sample_qc.get("note")}]


def _ancestry_envelope(operation: str, result: JsonObject) -> JsonObject:
    status = str(result.get("status") or "")
    sample_qc = result.get("sample_qc") if isinstance(result.get("sample_qc"), dict) else {}
    projection = result.get("pca_projection") if isinstance(result.get("pca_projection"), dict) else {}
    reference_panel = result.get("reference_panel") if isinstance(result.get("reference_panel"), dict) else {}
    panel_id = str(reference_panel.get("panel_id") or reference_panels.PANEL_ID)
    panel_library = str(reference_panel.get("library") or reference_panels.PANEL_LIBRARY)
    panel_title = str(reference_panel.get("title") or reference_panels.PANEL_TITLE)
    library_state = "installed" if reference_panel.get("installed", True) else "missing"
    if status == "completed":
        return evidence_envelope.evidence_present(
            operation=operation,
            query_scope={"method": "ancestry_pca_projection", "reference_panel": panel_id},
            personal_context={"uses_personal_dna": True},
            coverage=evidence_envelope._coverage(
                libraries=[{"library": panel_library, "state": library_state, "title": panel_title}],
                consulted_sources=["active_genome_index", panel_library],
            ),
            observations={
                "usable_marker_count": sample_qc.get("usable_marker_count"),
                "marker_overlap_quality": sample_qc.get("marker_overlap_quality"),
                "projected": bool(projection),
            },
            answer_readiness=evidence_envelope.SCOPED_ANSWER_ONLY,
            next_actions=result.get("next_actions") if isinstance(result.get("next_actions"), list) else [],
            notes=[source_context.BOUNDARY_NOTE],
            guidance=["evidence_present:answer_as_reference_panel_similarity_only"],
        )
    return evidence_envelope.not_assessed(
        operation=operation,
        reason=sample_qc.get("note") or status,
        query_scope={"method": "ancestry_pca_projection", "reference_panel": panel_id},
        personal_context={"uses_personal_dna": True},
        coverage=evidence_envelope._coverage(
            libraries=[{"library": panel_library, "state": library_state, "title": panel_title}],
            consulted_sources=["active_genome_index", panel_library],
        ),
        observations={
            "status": status,
            "usable_marker_count": sample_qc.get("usable_marker_count"),
            "projection_allowed": sample_qc.get("projection_allowed"),
        },
        next_actions=result.get("next_actions") if isinstance(result.get("next_actions"), list) else [],
        notes=[source_context.BOUNDARY_NOTE],
        guidance=["not_assessed:do_not_interpret_reference_similarity"],
    )
