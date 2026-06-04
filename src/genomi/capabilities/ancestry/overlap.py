from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any

from ...active_genome_index.array_genotypes import count_array_allele, is_array_genotype_record
from ...active_genome_index.active_genome_index import ActiveGenomeIndexReader
from ...active_genome_index.vcf import parse_sample
from . import policy, reference_panels, source_context

JsonObject = dict[str, Any]
# Overlap is graded purely as a fraction of the loaded panel. The
# 1000G-30x-GRCh38 panel is deliberately compact (~20k LD-pruned,
# MAF-filtered, ancestry-informative SNPs per genomi-ancestry-panel/
# docs/filters.md — "ancestry PCA on 3,202 samples stabilizes well below
# 10,000 informative markers"). Small-by-design ≠ low quality, so there
# is no absolute marker-count floor; what matters is how much of the
# chosen panel the sample's AGI actually covers.
HIGH_OVERLAP_FRACTION = policy.HIGH_OVERLAP_FRACTION
MODERATE_OVERLAP_FRACTION = policy.MODERATE_OVERLAP_FRACTION
LOW_OVERLAP_FRACTION = policy.LOW_OVERLAP_FRACTION


def check_sample_overlap(
    reader: ActiveGenomeIndexReader,
    *,
    genome_build: str = "GRCh38",
    panel_root: str | Path | None = None,
) -> JsonObject:
    panel_or_missing = _load_panel_or_missing(genome_build, panel_root, reader)
    if isinstance(panel_or_missing, dict) and panel_or_missing.get("status") == "panel_not_installed":
        return panel_or_missing
    panel = panel_or_missing
    genotype_context = collect_sample_genotypes(
        reader,
        genome_build=genome_build,
        panel=panel,
    )
    sample_qc = genotype_context["sample_qc"]
    return {
        "schema": "genomi-ancestry-overlap-v1",
        "status": sample_qc["overlap_status"],
        "personal_context": {"uses_personal_dna": True},
        "reference_panel": _reference_panel_summary(panel),
        "sample_qc": sample_qc,
        "limitations": source_context.limitations(),
        "next_actions": _overlap_next_actions(sample_qc),
    }


def _load_panel_or_missing(
    genome_build: str,
    panel_root: str | Path | None,
    reader: ActiveGenomeIndexReader,
) -> JsonObject:
    """Load the panel that matches the sample's genome build.

    Returns the panel payload on success, or a ``panel_not_installed``
    envelope payload that the caller should propagate directly when the
    matching panel library is missing on disk.
    """

    normalized_build = _normalize_build(genome_build)
    try:
        return reference_panels.load_panel(normalized_build, panel_root)
    except FileNotFoundError:
        return _panel_not_installed_payload(
            genome_build=normalized_build,
            active_genome_index_path=str(reader.active_genome_index_path),
        )


def _panel_not_installed_payload(*, genome_build: str, active_genome_index_path: str) -> JsonObject:
    from ...runtime.libraries import manager

    library = source_context.panel_library_for_build(genome_build)
    status = manager.status(library)
    panel_id = source_context.panel_id_for_build(genome_build)
    note = (
        f"No ancestry panel is installed for the sample's {genome_build} build. "
        f"Install {library} to enable reference-panel projection for this sample."
    )
    sample_qc = {
        "genome_build": genome_build,
        "active_genome_index_path": active_genome_index_path,
        "panel_marker_count": 0,
        "usable_marker_count": 0,
        "missing_marker_count": 0,
        "overlap_fraction": 0.0,
        "overlap_status": "panel_not_installed",
        "projection_allowed": False,
        "marker_overlap_quality": "unavailable",
        "required_library": library,
        "required_panel_id": panel_id,
        "install_command": status["install_command"],
        "note": note,
    }
    return {
        "schema": "genomi-ancestry-overlap-v1",
        "status": "panel_not_installed",
        "personal_context": {"uses_personal_dna": True},
        "reference_panel": {
            "panel_id": panel_id,
            "title": (
                source_context.PANEL_TITLE_GRCH38
                if genome_build == "GRCh38"
                else source_context.PANEL_TITLE_GRCH37
            ),
            "library": library,
            "genome_build": genome_build,
            "installed": False,
            "source_urls": source_context.source_urls(),
        },
        "sample_qc": sample_qc,
        "limitations": source_context.limitations(),
        "next_actions": [
            {
                "action": "install_library",
                "library": library,
                "install_command": status["install_command"],
                "reason": note,
            }
        ],
    }


def collect_sample_genotypes(
    reader: ActiveGenomeIndexReader,
    *,
    genome_build: str = "GRCh38",
    panel: JsonObject | None = None,
) -> JsonObject:
    normalized_build = _normalize_build(genome_build)
    panel_payload = panel or reference_panels.load_panel(normalized_build)
    markers = list(panel_payload["markers"])
    panel_marker_count = len(markers)

    active_genome_index_file = reader.active_genome_index_path
    # No readiness / incompleteness handling here: open_agi gated access
    # upstream (missing / incomplete -> active_genome_index_incomplete). A
    # variants_ready index proceeds; the dispatch chokepoint stamps
    # reference_pending.
    dosages: dict[str, float] = {}
    missing_marker_ids: list[str] = []
    missing_marker_reasons: dict[str, int] = {}
    missing_marker_examples: list[JsonObject] = []
    with reader.connect() as connection:
        for marker in markers:
            marker_result = _marker_dosage_result(connection, marker)
            marker_id = str(marker["marker_id"])
            if marker_result.get("status") != "matched":
                missing_marker_ids.append(marker_id)
                reason = str(marker_result.get("reason") or "unusable_marker")
                missing_marker_reasons[reason] = missing_marker_reasons.get(reason, 0) + 1
                if len(missing_marker_examples) < 10:
                    missing_marker_examples.append(
                        {
                            "marker_id": marker_id,
                            "reason": reason,
                            **(
                                {"detail": marker_result["detail"]}
                                if marker_result.get("detail") is not None
                                else {}
                            ),
                        }
                    )
                continue
            dosage = marker_result.get("dosage")
            if dosage is None or not math.isfinite(float(dosage)):
                missing_marker_ids.append(marker_id)
                missing_marker_reasons["nonfinite_dosage"] = missing_marker_reasons.get("nonfinite_dosage", 0) + 1
                continue
            dosages[marker_id] = float(dosage)

    usable_marker_ids = [str(marker["marker_id"]) for marker in markers if str(marker["marker_id"]) in dosages]
    usable_marker_count = len(usable_marker_ids)
    fraction = _overlap_fraction(usable_marker_count, panel_marker_count)
    sample_qc = _sample_qc(
        marker_count=panel_marker_count,
        usable_marker_count=usable_marker_count,
        missing_marker_count=len(missing_marker_ids),
        genome_build=normalized_build,
        active_genome_index_path=str(active_genome_index_file),
        overlap_status=_overlap_status(fraction),
        projection_allowed=fraction >= LOW_OVERLAP_FRACTION,
        marker_overlap_quality=_marker_overlap_quality(fraction),
        note=_overlap_note(fraction),
        missing_marker_reasons=missing_marker_reasons,
        missing_marker_examples=missing_marker_examples,
    )
    return {
        "sample_qc": sample_qc,
        "dosages": dosages,
        "usable_marker_ids": usable_marker_ids,
        "missing_marker_ids": missing_marker_ids,
        "missing_marker_reasons": missing_marker_reasons,
        "missing_marker_examples": missing_marker_examples,
    }


def _marker_dosage_result(connection: sqlite3.Connection, marker: JsonObject) -> JsonObject:
    records = _records_for_marker(connection, marker)
    if not records:
        return {"status": "missing", "reason": "no_record_at_locus"}
    ref = str(marker["ref"]).upper()
    alt = str(marker["alt"]).upper()
    missing_reasons: list[JsonObject] = []
    for record in records:
        if int(record["pos"]) != int(marker["pos"]) or not is_array_genotype_record(record):
            continue
        array_dosage = count_array_allele(record, target_allele=alt, allowed_alleles=[ref, alt])
        if array_dosage["status"] == "matched":
            return {"status": "matched", "dosage": float(array_dosage["dosage"]), "basis": "consumer_array"}
        missing_reasons.append(
            {
                "reason": str(array_dosage.get("reason") or "array_genotype_unusable"),
                "basis": "consumer_array",
                **(
                    {"allele_bases": array_dosage["allele_bases"]}
                    if array_dosage.get("allele_bases") is not None
                    else {}
                ),
            }
        )
    exact_records = [
        record for record in records
        if int(record["pos"]) == int(marker["pos"]) and str(record["ref"]).upper() == ref
    ]
    for record in exact_records:
        dosage = _dosage_from_record(record, ref=ref, alt=alt)
        if dosage is not None:
            return {"status": "matched", "dosage": float(dosage), "basis": "exact_genotype"}
        missing_reasons.append({"reason": _vcf_unusable_reason(record, ref=ref, alt=alt), "basis": "exact_genotype"})
    for record in records:
        if not bool(record["is_variant"]) and not is_array_genotype_record(record):
            dosage = _reference_dosage_from_record(record, ref=ref)
            if dosage is not None:
                return {"status": "matched", "dosage": float(dosage), "basis": "reference_block"}
            missing_reasons.append({"reason": _vcf_unusable_reason(record, ref=ref, alt=alt), "basis": "reference_block"})
    if missing_reasons:
        return {
            "status": "missing",
            "reason": _primary_missing_reason(missing_reasons),
            "detail": missing_reasons[:3],
        }
    return {"status": "missing", "reason": "no_usable_record_at_locus"}


def _records_for_marker(connection: sqlite3.Connection, marker: JsonObject) -> list[JsonObject]:
    records: list[JsonObject] = []
    seen: set[tuple[int, int]] = set()
    for chrom in _chrom_candidates(str(marker["chrom"])):
        rows = connection.execute(
            """
            select *
            from records
            where chrom = ? and pos = ?
            order by chrom_sort, pos, offset, sample_index
            limit 20
            """,
            (chrom, int(marker["pos"])),
        ).fetchall()
        rows.extend(
            connection.execute(
                """
                select r.*
                from spans s
                join records r on r.offset = s.offset and r.sample_index = s.sample_index
                where s.chrom = ? and s.pos < ? and s.end >= ?
                order by s.pos desc
                limit 20
                """,
                (chrom, int(marker["pos"]), int(marker["pos"])),
            ).fetchall()
        )
        for row in rows:
            key = (int(row["offset"]), int(row["sample_index"] or 0))
            if key in seen:
                continue
            seen.add(key)
            records.append(_record_row_to_dict(row))
    return records


def _record_row_to_dict(row: sqlite3.Row) -> JsonObject:
    alt = "" if row["alt"] == "." else str(row["alt"] or "")
    return {
        "chrom": row["chrom"],
        "pos": int(row["pos"]),
        "end": int(row["end"]),
        "ref": row["ref"],
        "alt": alt,
        "alts": [value for value in alt.split(",") if value],
        "filter": row["filter"],
        "is_variant": bool(row["is_variant"]),
        "genotype": row["genotype"],
        "format": str(row["format"] or "").split(":") if row["format"] else [],
        "sample": parse_sample(str(row["format"] or ""), str(row["sample"] or "")),
        "offset": int(row["offset"]),
        "sample_index": int(row["sample_index"] or 0),
    }


def _dosage_from_record(record: JsonObject, *, ref: str, alt: str) -> float | None:
    if str(record.get("filter") or "") not in {"PASS", "."}:
        return None
    genotype = str(record.get("genotype") or "")
    if not genotype or "." in genotype:
        return None
    alts = [str(value).upper() for value in record.get("alts") or []]
    allele_bases: list[str] = []
    for token in genotype.replace("|", "/").split("/"):
        if token == "0":
            allele_bases.append(ref)
            continue
        try:
            allele_bases.append(alts[int(token) - 1])
        except (IndexError, ValueError):
            return None
    if not allele_bases:
        return None
    if any(base not in {ref, alt} for base in allele_bases):
        return None
    return float(sum(1 for base in allele_bases if base == alt))


def _reference_dosage_from_record(record: JsonObject, *, ref: str) -> float | None:
    if str(record.get("filter") or "") not in {"PASS", "."}:
        return None
    genotype = str(record.get("genotype") or "")
    if not genotype or "." in genotype:
        return None
    if str(record.get("ref") or "").upper() != ref:
        return None
    tokens = genotype.replace("|", "/").split("/")
    if tokens and all(token == "0" for token in tokens):
        return 0.0
    return None


def _vcf_unusable_reason(record: JsonObject, *, ref: str, alt: str) -> str:
    if str(record.get("filter") or "") not in {"PASS", "."}:
        return "filtered_record"
    genotype = str(record.get("genotype") or "")
    if not genotype or "." in genotype:
        return "missing_genotype"
    if str(record.get("ref") or "").upper() != ref:
        return "reference_allele_mismatch"
    alts = {str(value).upper() for value in record.get("alts") or []}
    if alt not in alts and bool(record.get("is_variant")):
        return "alternate_allele_mismatch"
    return "genotype_unusable"


def _primary_missing_reason(reasons: list[JsonObject]) -> str:
    priority = [
        "missing_genotype",
        "array_genotype_allele_outside_allowed_alleles",
        "array_target_allele_not_single_base",
        "array_allele_model_not_single_base",
        "filtered_record",
        "reference_allele_mismatch",
        "alternate_allele_mismatch",
        "genotype_unusable",
    ]
    observed = [str(item.get("reason") or "") for item in reasons]
    for reason in priority:
        if reason in observed:
            return reason
    return observed[0] if observed else "unusable_marker"


def _chrom_candidates(chrom: str) -> list[str]:
    candidates = [chrom]
    if chrom.startswith("chr"):
        candidates.append(chrom[3:])
    else:
        candidates.append(f"chr{chrom}")
    output = []
    for candidate in candidates:
        if candidate not in output:
            output.append(candidate)
    return output


def _sample_qc(
    *,
    marker_count: int,
    usable_marker_count: int,
    missing_marker_count: int,
    genome_build: str,
    active_genome_index_path: str,
    overlap_status: str,
    projection_allowed: bool,
    marker_overlap_quality: str,
    note: str,
    missing_marker_reasons: dict[str, int] | None = None,
    missing_marker_examples: list[JsonObject] | None = None,
) -> JsonObject:
    return {
        "genome_build": genome_build,
        "supported_genome_builds": list(reference_panels.SUPPORTED_BUILDS),
        "active_genome_index_path": active_genome_index_path,
        "panel_marker_count": marker_count,
        "usable_marker_count": usable_marker_count,
        "missing_marker_count": missing_marker_count,
        "missing_marker_reasons": dict(missing_marker_reasons or {}),
        "missing_marker_examples": list(missing_marker_examples or []),
        "overlap_fraction": usable_marker_count / marker_count if marker_count else 0.0,
        "overlap_status": overlap_status,
        "projection_allowed": projection_allowed,
        "marker_overlap_quality": marker_overlap_quality,
        "thresholds": policy.overlap_thresholds(),
        "note": note,
    }


def _overlap_fraction(usable_marker_count: int, panel_marker_count: int) -> float:
    return usable_marker_count / panel_marker_count if panel_marker_count else 0.0


def _overlap_status(fraction: float) -> str:
    return policy.overlap_status(fraction)


def _marker_overlap_quality(fraction: float) -> str:
    return policy.marker_overlap_quality(fraction)


def _overlap_note(fraction: float) -> str:
    return policy.overlap_note(fraction)


def _overlap_next_actions(sample_qc: JsonObject) -> list[JsonObject]:
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
    if status in {"insufficient_overlap", "low_overlap"}:
        return [{"action": "use_higher_overlap_index", "reason": sample_qc.get("note")}]
    return [{"action": "project_pca", "operation": "ancestry.project_pca"}]


def _reference_panel_summary(panel: JsonObject) -> JsonObject:
    manifest = panel.get("manifest") or {}
    stats = panel.get("stats") or {}
    genome_build = str(manifest.get("genome_build") or "GRCh38")
    return {
        "panel_id": str(manifest.get("panel_id") or source_context.panel_id_for_build(genome_build)),
        "title": str(manifest.get("title") or reference_panels.PANEL_TITLE),
        "library": str(manifest.get("library") or source_context.panel_library_for_build(genome_build)),
        "genome_build": genome_build,
        "sample_count": int(manifest.get("sample_count") or stats.get("sample_count") or len(panel.get("samples") or [])),
        "marker_count": int(manifest.get("marker_count") or stats.get("marker_count") or len(panel.get("markers") or [])),
        "component_count": int(manifest.get("component_count") or stats.get("component_count") or len(panel.get("component_names") or [])),
        "label_scope": "1000 Genomes reference-panel population labels",
        "source_urls": source_context.source_urls(),
    }


def _normalize_build(value: str | None) -> str:
    return policy.normalize_build(value, default="unknown")
