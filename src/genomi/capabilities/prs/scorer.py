from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from ...active_genome_index.active_genome_index import ActiveGenomeIndexReader
from ...evidence import envelope as evidence_envelope
from ...runtime.libraries import manager as library_manager
from ...runtime.libraries.manager import status as library_status
from . import harmonize, scoring_files, source_context

JsonObject = dict[str, Any]
MIN_SCORE_VARIANTS = 10
MIN_OVERLAP_FRACTION = 0.10
MODERATE_OVERLAP_FRACTION = 0.50
HIGH_OVERLAP_FRACTION = 0.90


def check_score_overlap(
    reader: ActiveGenomeIndexReader,
    *,
    pgs_id: str | None = None,
    score_dir: str | Path | None = None,
    genome_build: str = "GRCh38",
    skip_ambiguous_palindromic: bool = True,
) -> JsonObject:
    collected = collect_score_context(
        reader,
        pgs_id=pgs_id,
        score_dir=score_dir,
        genome_build=genome_build,
        skip_ambiguous_palindromic=skip_ambiguous_palindromic,
        operation="prs.check_score_overlap",
    )
    if collected.get("status") != "completed":
        return collected
    result = {
        "schema": "genomi-prs-overlap-v1",
        "status": collected["sample_qc"]["overlap_status"],
        "personal_context": {"uses_personal_dna": True},
        "polygenic_score": collected["polygenic_score"],
        "sample_qc": collected["sample_qc"],
        "limitations": source_context.limitations(),
        "next_actions": _overlap_next_actions(collected["sample_qc"], collected["polygenic_score"]),
    }
    result["evidence_envelope"] = _prs_envelope("prs.check_score_overlap", result)
    return result


def calculate_score(
    reader: ActiveGenomeIndexReader,
    *,
    pgs_id: str | None = None,
    score_dir: str | Path | None = None,
    genome_build: str = "GRCh38",
    skip_ambiguous_palindromic: bool = True,
    score_mean: float | None = None,
    score_sd: float | None = None,
) -> JsonObject:
    collected = collect_score_context(
        reader,
        pgs_id=pgs_id,
        score_dir=score_dir,
        genome_build=genome_build,
        skip_ambiguous_palindromic=skip_ambiguous_palindromic,
        operation="prs.calculate_score",
    )
    if collected.get("status") != "completed":
        return collected
    sample_qc = collected["sample_qc"]
    if not sample_qc["calculation_allowed"]:
        result = {
            "schema": "genomi-prs-score-v1",
            "status": sample_qc["overlap_status"],
            "personal_context": {"uses_personal_dna": True},
            "polygenic_score": collected["polygenic_score"],
            "sample_qc": sample_qc,
            "score_result": None,
            "interpretation": _interpretation(sample_qc, score_result=None),
            "limitations": source_context.limitations(),
            "next_actions": _overlap_next_actions(sample_qc, collected["polygenic_score"]),
        }
        result["evidence_envelope"] = _prs_envelope("prs.calculate_score", result)
        return result

    score_result = _score_result(
        collected["matched_variants"],
        score_mean=score_mean,
        score_sd=score_sd,
    )
    result = {
        "schema": "genomi-prs-score-v1",
        "status": "completed",
        "personal_context": {"uses_personal_dna": True},
        "polygenic_score": collected["polygenic_score"],
        "sample_qc": sample_qc,
        "score_result": score_result,
        "variant_accounting": collected["variant_accounting"],
        "interpretation": _interpretation(sample_qc, score_result=score_result),
        "limitations": source_context.limitations(),
        "next_actions": _score_next_actions(sample_qc, collected["polygenic_score"], score_result),
    }
    result["evidence_envelope"] = _prs_envelope("prs.calculate_score", result)
    return result


def collect_score_context(
    reader: ActiveGenomeIndexReader,
    *,
    pgs_id: str | None = None,
    score_dir: str | Path | None = None,
    genome_build: str = "GRCh38",
    skip_ambiguous_palindromic: bool = True,
    operation: str = "prs.calculate_score",
) -> JsonObject:
    normalized_build = scoring_files.normalize_build(genome_build)
    cache = scoring_files.resolve_score_cache(pgs_id=pgs_id, score_dir=score_dir, genome_build=normalized_build)
    if cache.get("status") != "installed":
        result = dict(cache)
        result["personal_context"] = {"uses_personal_dna": True}
        result["evidence_envelope"] = _score_import_required_envelope(operation, result, normalized_build)
        return result

    manifest = cache["manifest"]
    score_build = scoring_files.normalize_build(str(manifest.get("genome_build") or normalized_build))
    score_summary = _polygenic_score_summary(cache["score_dir"], manifest)

    active_genome_index_file = reader.active_genome_index_path
    variants = scoring_files.load_variants(cache["score_dir"])
    original_variant_count = len(variants)
    lift_summary: JsonObject | None = None
    if score_build != normalized_build:
        liftover_status = library_status("liftover-chains")
        if not liftover_status["installed"]:
            request = library_manager.missing_request(
                "liftover-chains",
                intent=(
                    f"lifting PRS score variants from {score_build} to the active sample's "
                    f"{normalized_build} build so the imported score can be calculated against this AGI"
                ),
                operation=operation,
                genome_build=normalized_build,
            )
            request["schema"] = "genomi-prs-score-v1"
            request["polygenic_score"] = score_summary
            request["score_genome_build"] = score_build
            request["sample_genome_build"] = normalized_build
            return request
        lift_result = harmonize.lift_score_variants(
            variants, source_build=score_build, target_build=normalized_build
        )
        variants = lift_result["lifted"]
        lift_summary = {
            "source_build": score_build,
            "target_build": normalized_build,
            "lifted_variant_count": len(lift_result["lifted"]),
            "dropped_variant_count": len(lift_result["dropped"]),
            "dropped_reasons": dict(Counter(
                str(item.get("liftover_reason") or "unknown") for item in lift_result["dropped"]
            )),
            "chain": "UCSC pyliftover",
        }
    # No readiness / incompleteness handling here: open_agi has already gated
    # access (missing / incomplete -> active_genome_index_incomplete; reparse /
    # schema-too-new surfaced upstream). A variants_ready index proceeds and the
    # dispatch chokepoint stamps reference_pending.
    matched: list[JsonObject] = []
    missing: list[JsonObject] = []
    excluded: list[JsonObject] = []
    with reader.connect() as connection:
        dosages = harmonize.dosage_for_variants(
            connection,
            variants,
            skip_ambiguous_palindromic=skip_ambiguous_palindromic,
        )
    for dosage in dosages:
        if dosage["status"] == "matched":
            matched.append(dosage)
        elif dosage["status"] == "excluded":
            excluded.append(dosage)
        else:
            missing.append(dosage)

    sample_qc = _sample_qc(
        genome_build=normalized_build,
        score_build=score_build,
        active_genome_index_path=active_genome_index_file,
        score_variant_count=original_variant_count,
        matched=matched,
        missing=missing,
        excluded=excluded,
        note=_overlap_note(len(matched), original_variant_count),
        liftover=lift_summary,
    )
    return {
        "status": "completed",
        "polygenic_score": score_summary,
        "sample_qc": sample_qc,
        "matched_variants": matched,
        "missing_variants": missing,
        "excluded_variants": excluded,
        "variant_accounting": _variant_accounting(matched, missing, excluded),
    }


def _sample_qc(
    *,
    genome_build: str,
    score_build: str,
    active_genome_index_path: Path,
    score_variant_count: int,
    matched: list[JsonObject],
    missing: list[JsonObject],
    excluded: list[JsonObject],
    note: str,
    liftover: JsonObject | None = None,
) -> JsonObject:
    matched_count = len(matched)
    missing_count = len(missing)
    excluded_count = len(excluded)
    denominator = score_variant_count or 1
    overlap_fraction = matched_count / denominator
    payload: JsonObject = {
        "genome_build": genome_build,
        "score_genome_build": score_build,
        "active_genome_index_path": str(active_genome_index_path),
        "score_variant_count": score_variant_count,
        "matched_variant_count": matched_count,
        "missing_variant_count": missing_count,
        "excluded_variant_count": excluded_count,
        "overlap_fraction": overlap_fraction,
        "overlap_status": _overlap_status(matched_count, overlap_fraction),
        "calculation_allowed": matched_count >= MIN_SCORE_VARIANTS and overlap_fraction >= MIN_OVERLAP_FRACTION,
        "overlap_quality": _overlap_quality(overlap_fraction),
        "missing_reasons": dict(Counter(str(item.get("reason") or "missing") for item in missing)),
        "excluded_reasons": dict(Counter(str(item.get("reason") or "excluded") for item in excluded)),
        "note": note,
    }
    if liftover is not None:
        payload["liftover"] = liftover
    return payload


def _score_result(
    matched: list[JsonObject],
    *,
    score_mean: float | None,
    score_sd: float | None,
) -> JsonObject:
    raw_score = sum(float(item["contribution"]) for item in matched)
    weighted_allele_count = sum(float(item["effect_allele_dosage"]) for item in matched)
    result: JsonObject = {
        "raw_weighted_score": raw_score,
        "weighted_allele_count": weighted_allele_count,
        "matched_variant_count": len(matched),
        "calibration": {
            "status": "not_provided",
            "meaning": "Raw score only; no absolute risk, percentile, or clinical category is inferred.",
        },
    }
    if score_mean is not None and score_sd is not None and float(score_sd) > 0:
        z = (raw_score - float(score_mean)) / float(score_sd)
        result["calibration"] = {
            "status": "standardized_from_supplied_parameters",
            "mean": float(score_mean),
            "sd": float(score_sd),
            "z_score": z,
            "meaning": "Standardized against user-supplied parameters only; this is not an absolute clinical risk model.",
        }
    return result


def _polygenic_score_summary(score_dir: str | Path, manifest: JsonObject) -> JsonObject:
    catalog_meta = manifest.get("pgs_catalog_metadata") if isinstance(manifest.get("pgs_catalog_metadata"), dict) else {}
    return {
        "pgs_id": manifest.get("pgs_id"),
        "name": catalog_meta.get("name") or manifest.get("scoring_file_metadata", {}).get("pgs_name"),
        "reported_trait": catalog_meta.get("reported_trait") or manifest.get("scoring_file_metadata", {}).get("reported_trait"),
        "genome_build": manifest.get("genome_build"),
        "variant_count": manifest.get("variant_count"),
        "harmonized": manifest.get("harmonized"),
        "score_dir": str(score_dir),
        "source": manifest.get("source"),
        "publication": catalog_meta.get("publication") or {},
        "ancestry_distribution": catalog_meta.get("ancestry_distribution") or {},
        "license_terms": manifest.get("scoring_file_metadata", {}).get("license"),
    }


def _variant_accounting(matched: list[JsonObject], missing: list[JsonObject], excluded: list[JsonObject]) -> JsonObject:
    return {
        "matched_examples": _compact_variant_examples(matched[:20]),
        "missing_examples": _compact_variant_examples(missing[:20]),
        "excluded_examples": _compact_variant_examples(excluded[:20]),
        "missing_reasons": dict(Counter(str(item.get("reason") or "missing") for item in missing)),
        "excluded_reasons": dict(Counter(str(item.get("reason") or "excluded") for item in excluded)),
    }


def _compact_variant_examples(items: list[JsonObject]) -> list[JsonObject]:
    return [
        {
            "variant_id": item.get("variant_id"),
            "rsid": item.get("rsid"),
            "chrom": item.get("chrom"),
            "pos": item.get("pos"),
            "effect_allele": item.get("effect_allele"),
            "effect_weight": item.get("effect_weight"),
            **({"effect_allele_dosage": item.get("effect_allele_dosage"), "contribution": item.get("contribution")} if item.get("status") == "matched" else {"reason": item.get("reason")}),
        }
        for item in items
    ]


def _overlap_status(matched_count: int, overlap_fraction: float) -> str:
    if matched_count < MIN_SCORE_VARIANTS or overlap_fraction < MIN_OVERLAP_FRACTION:
        return "insufficient_overlap"
    if overlap_fraction < MODERATE_OVERLAP_FRACTION:
        return "low_overlap"
    return "score_ready"


def _overlap_quality(overlap_fraction: float) -> str:
    if overlap_fraction >= HIGH_OVERLAP_FRACTION:
        return "high"
    if overlap_fraction >= MODERATE_OVERLAP_FRACTION:
        return "moderate"
    if overlap_fraction >= MIN_OVERLAP_FRACTION:
        return "low"
    return "insufficient"


def _overlap_note(matched_count: int, total_count: int) -> str:
    if total_count <= 0:
        return "The imported score contains no usable variants."
    fraction = matched_count / total_count
    if matched_count < MIN_SCORE_VARIANTS or fraction < MIN_OVERLAP_FRACTION:
        return "Too few score variants were observed for a usable raw PRS calculation."
    if fraction < MODERATE_OVERLAP_FRACTION:
        return "A raw score can be calculated, but overlap is low and interpretation should be cautious."
    return "The sample has enough direct overlap for a raw score calculation."


def _interpretation(sample_qc: JsonObject, *, score_result: JsonObject | None) -> JsonObject:
    if score_result is None:
        return {
            "summary": "No polygenic score was calculated because score overlap was insufficient or setup was incomplete.",
            "claim_boundary": "This is not negative evidence for disease risk.",
        }
    calibration = score_result.get("calibration") or {}
    if calibration.get("status") == "standardized_from_supplied_parameters":
        detail = f" The supplied calibration gives z={calibration['z_score']:.4g}."
    else:
        detail = " No absolute risk, percentile, or clinical category was inferred."
    return {
        "summary": (
            f"The raw weighted polygenic score was calculated from {sample_qc['matched_variant_count']} "
            f"matched score variants with {sample_qc['overlap_quality']} overlap quality.{detail}"
        ),
        "claim_boundary": "Use as source-bound quantitative context only; clinical risk needs validated calibration and clinical review.",
    }


def _overlap_next_actions(sample_qc: JsonObject, score: JsonObject) -> list[JsonObject]:
    if sample_qc.get("calculation_allowed"):
        return [{"action": "calculate_score", "operation": "prs.calculate_score", "pgs_id": score.get("pgs_id")}]
    return [
        {"action": "check_sample_build_and_score_build"},
        {"action": "use_more_complete_or_matching_genotype_source"},
    ]


def _score_next_actions(sample_qc: JsonObject, score: JsonObject, score_result: JsonObject) -> list[JsonObject]:
    actions: list[JsonObject] = []
    if (score_result.get("calibration") or {}).get("status") == "not_provided":
        actions.append({"action": "supply_validated_calibration_parameters_if_available", "parameters": ["score_mean", "score_sd"]})
    if sample_qc.get("overlap_quality") in {"low", "insufficient"}:
        actions.append({"action": "use_more_complete_or_matching_genotype_source"})
    actions.append({"action": "review_score_metadata", "operation": "prs.fetch_score_metadata", "pgs_id": score.get("pgs_id")})
    return actions


def _score_import_required_envelope(operation: str, result: JsonObject, genome_build: str) -> JsonObject:
    missing = result.get("missing_library") if isinstance(result.get("missing_library"), dict) else {}
    pgs_id = str(result.get("pgs_id") or missing.get("library") or "")
    if missing and missing.get("install_command"):
        return evidence_envelope.missing_library(
            operation=operation,
            library=pgs_id,
            library_status_payload=missing,
            query_scope={"method": "published_polygenic_score", "pgs_id": pgs_id, "genome_build": genome_build},
            personal_context={"uses_personal_dna": True},
            intent="calculating a PRS from an approved Active Genome Index",
            next_actions=result.get("next_actions") or [],
            guidance=["blocked_missing_library:ask_user_to_install"],
        )
    return evidence_envelope.not_assessed(
        operation=operation,
        reason="The requested polygenic score has not been imported into the local score cache.",
        personal_context={"uses_personal_dna": True},
        query_scope={"pgs_id": pgs_id or None, "genome_build": genome_build},
        next_actions=result.get("next_actions") or [],
    )


def _prs_envelope(operation: str, result: JsonObject) -> JsonObject:
    sample_qc = result.get("sample_qc") if isinstance(result.get("sample_qc"), dict) else {}
    score = result.get("polygenic_score") if isinstance(result.get("polygenic_score"), dict) else {}
    if result.get("status") == "completed" or sample_qc.get("calculation_allowed"):
        return evidence_envelope.evidence_present(
            operation=operation,
            query_scope={"method": "published_polygenic_score", "pgs_id": score.get("pgs_id"), "genome_build": sample_qc.get("genome_build")},
            personal_context={"uses_personal_dna": True},
            coverage={
                "libraries": [{"library": str(score.get("pgs_id") or "local_prs_score"), "state": "installed"}],
                "consulted_sources": ["local_active_genome_index", "local_prs_score_cache"],
                "unavailable_sources": [],
                "materialization": [],
            },
            observations={
                "matched_variant_count": sample_qc.get("matched_variant_count"),
                "overlap_fraction": sample_qc.get("overlap_fraction"),
            },
            answer_readiness=evidence_envelope.SCOPED_ANSWER_ONLY,
            next_actions=result.get("next_actions") or [],
            guidance=["prs_raw_score:do_not_infer_absolute_risk"],
        )
    return evidence_envelope.not_assessed(
        operation=operation,
        reason=str(sample_qc.get("note") or result.get("message") or "PRS score was not assessed."),
        query_scope={"method": "published_polygenic_score", "pgs_id": score.get("pgs_id"), "genome_build": sample_qc.get("genome_build")},
        personal_context={"uses_personal_dna": True},
        next_actions=result.get("next_actions") or [],
    )
