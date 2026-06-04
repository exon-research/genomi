from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from ...active_genome_index.active_genome_index import ActiveGenomeIndexReader
from ...evidence import envelope as evidence_envelope
from ...runtime.liftover import liftover_preflight
from . import harmonize, scoring_files, source_context

JsonObject = dict[str, Any]
MIN_SCORE_VARIANTS = 10
MIN_OVERLAP_FRACTION = 0.10
MODERATE_OVERLAP_FRACTION = 0.50
HIGH_OVERLAP_FRACTION = 0.90


def check_score_overlap(
    agi_reader: ActiveGenomeIndexReader,
    *,
    pgs_id: str | None = None,
    score_dir: str | Path | None = None,
    genome_build: str = "GRCh38",
    skip_ambiguous_palindromic: bool = True,
) -> JsonObject:
    collected = collect_score_context(
        agi_reader,
        pgs_id=pgs_id,
        score_dir=score_dir,
        genome_build=genome_build,
        skip_ambiguous_palindromic=skip_ambiguous_palindromic,
        operation="prs.check_score_overlap",
    )
    if collected.get("status") != "completed":
        return collected
    result = {
        "status": collected["sample_qc"]["overlap_status"],
        "personal_context": {"uses_personal_dna": True},
        "polygenic_score": collected["polygenic_score"],
        "sample_qc": collected["sample_qc"],
        "variant_accounting": collected["variant_accounting"],
        "limitations": source_context.limitations(),
        "next_actions": _overlap_next_actions(collected["sample_qc"], collected["polygenic_score"]),
    }
    result["evidence_envelope"] = _prs_envelope("prs.check_score_overlap", result)
    return result


def calculate_score(
    agi_reader: ActiveGenomeIndexReader,
    *,
    pgs_id: str | None = None,
    score_dir: str | Path | None = None,
    genome_build: str = "GRCh38",
    skip_ambiguous_palindromic: bool = True,
    score_mean: float | None = None,
    score_sd: float | None = None,
) -> JsonObject:
    collected = collect_score_context(
        agi_reader,
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
            "status": sample_qc["overlap_status"],
            "personal_context": {"uses_personal_dna": True},
            "polygenic_score": collected["polygenic_score"],
            "sample_qc": sample_qc,
            "score_result": None,
            "variant_accounting": collected["variant_accounting"],
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
    agi_reader: ActiveGenomeIndexReader,
    *,
    pgs_id: str | None = None,
    score_dir: str | Path | None = None,
    genome_build: str = "GRCh38",
    skip_ambiguous_palindromic: bool = True,
    operation: str = "prs.calculate_score",
) -> JsonObject:
    normalized_build = scoring_files.normalize_build(genome_build)
    if not scoring_files.is_supported_build(normalized_build):
        result = scoring_files.unsupported_genome_build_result(normalized_build)
        _add_unsupported_genome_build_envelope(
            result,
            operation=operation,
            pgs_id=pgs_id,
            genome_build=normalized_build,
        )
        return result
    mismatch = _active_genome_index_build_mismatch(
        agi_reader,
        normalized_build,
        operation=operation,
        pgs_id=pgs_id,
    )
    if mismatch is not None:
        return mismatch
    cache = scoring_files.resolve_score_cache(pgs_id=pgs_id, score_dir=score_dir, genome_build=normalized_build)
    if cache.get("status") == "out_of_scope_for_input":
        result = dict(cache)
        _add_unsupported_genome_build_envelope(
            result,
            operation=operation,
            pgs_id=pgs_id,
            genome_build=str(result.get("genome_build") or normalized_build),
        )
        return result
    if cache.get("status") != "installed":
        result = dict(cache)
        result["personal_context"] = {"uses_personal_dna": True}
        result["evidence_envelope"] = _score_import_required_envelope(operation, result, normalized_build)
        return result

    manifest = cache["manifest"]
    score_build = scoring_files.normalize_build(str(manifest.get("genome_build") or normalized_build))
    score_summary = _polygenic_score_summary(cache["score_dir"], manifest)

    variants = scoring_files.load_variants(cache["score_dir"])
    original_variant_count = len(variants)
    lift_summary: JsonObject | None = None
    liftover_excluded: list[JsonObject] = []
    if score_build != normalized_build:
        liftover_intent = (
            f"lifting PRS score variants from {score_build} to the active sample's "
            f"{normalized_build} build so the imported score can be calculated against this AGI"
        )
        preflight = liftover_preflight(
            score_build,
            normalized_build,
            operation=operation,
            intent=liftover_intent,
            genome_build=normalized_build,
        )
        if preflight.get("status") != "available":
            return _liftover_setup_required(
                preflight,
                operation=operation,
                score=score_summary,
                score_build=score_build,
                sample_build=normalized_build,
            )
        lift_result = harmonize.lift_score_variants(
            variants, source_build=score_build, target_build=normalized_build
        )
        variants = lift_result["lifted"]
        liftover_excluded = _liftover_excluded_variants(
            lift_result["dropped"],
            source_build=score_build,
            target_build=normalized_build,
        )
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
    # schema-too-new surfaced upstream). PRS reads variant-surface records, so a
    # variants_ready index is final for this capability.
    matched: list[JsonObject] = []
    missing: list[JsonObject] = []
    excluded: list[JsonObject] = list(liftover_excluded)
    dosages = agi_reader.dosage_for_variants(
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
    accounted_count = matched_count + missing_count + excluded_count
    denominator = score_variant_count or 1
    overlap_fraction = matched_count / denominator
    payload: JsonObject = {
        "genome_build": genome_build,
        "score_genome_build": score_build,
        "score_variant_count": score_variant_count,
        "matched_variant_count": matched_count,
        "missing_variant_count": missing_count,
        "excluded_variant_count": excluded_count,
        "accounted_variant_count": accounted_count,
        "unaccounted_variant_count": max(score_variant_count - accounted_count, 0),
        "overaccounted_variant_count": max(accounted_count - score_variant_count, 0),
        "accounting_complete": accounted_count == score_variant_count,
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


def _active_genome_index_build_mismatch(
    agi_reader: ActiveGenomeIndexReader,
    requested_build: str,
    *,
    operation: str,
    pgs_id: str | None,
) -> JsonObject | None:
    reader_build = str(getattr(agi_reader, "genome_build", "") or "").strip()
    if not reader_build or reader_build == "auto":
        return None
    agi_build = scoring_files.normalize_build(reader_build)
    if not scoring_files.is_supported_build(agi_build):
        result = scoring_files.unsupported_genome_build_result(agi_build)
        result["active_genome_index_genome_build"] = agi_build
        _add_unsupported_genome_build_envelope(
            result,
            operation=operation,
            pgs_id=pgs_id,
            genome_build=agi_build,
        )
        return result
    if agi_build == requested_build:
        return None
    result: JsonObject = {
        "status": "out_of_scope_for_input",
        "coverage_status": "out_of_scope_for_input",
        "requested_genome_build": requested_build,
        "active_genome_index_genome_build": agi_build,
        "supported_genome_builds": list(scoring_files.SUPPORTED_GENOME_BUILDS),
        "personal_context": {"uses_personal_dna": True},
        "next_actions": [
            {
                "action": "use_active_genome_index_build",
                "genome_build": agi_build,
            }
        ],
    }
    result["evidence_envelope"] = evidence_envelope.not_assessed(
        operation=operation,
        reason="requested genome build conflicts with Active Genome Index metadata",
        query_scope={
            "method": "published_polygenic_score",
            "pgs_id": pgs_id,
            "requested_genome_build": requested_build,
            "active_genome_index_genome_build": agi_build,
        },
        personal_context={"uses_personal_dna": True},
        observations={
            "status": "out_of_scope_for_input",
            "requested_genome_build": requested_build,
            "active_genome_index_genome_build": agi_build,
        },
        next_actions=result["next_actions"],
        guidance=["out_of_scope_for_input:use_active_genome_index_genome_build"],
    )
    return result


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
        "matched_count": len(matched),
        "missing_count": len(missing),
        "excluded_count": len(excluded),
        "accounted_variant_count": len(matched) + len(missing) + len(excluded),
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


def _liftover_excluded_variants(
    dropped: list[JsonObject],
    *,
    source_build: str,
    target_build: str,
) -> list[JsonObject]:
    excluded: list[JsonObject] = []
    for variant in dropped:
        liftover_reason = str(variant.get("liftover_reason") or "unknown")
        excluded.append(
            {
                "status": "excluded",
                "reason": f"liftover_{liftover_reason}",
                "liftover_reason": liftover_reason,
                "liftover_source_build": source_build,
                "liftover_target_build": target_build,
                "variant_index": variant.get("variant_index"),
                "variant_id": variant.get("variant_id"),
                "rsid": variant.get("rsid"),
                "chrom": variant.get("chrom"),
                "pos": variant.get("pos"),
                "effect_allele": variant.get("effect_allele"),
                "other_allele": variant.get("other_allele"),
                "effect_weight": variant.get("effect_weight"),
            }
        )
    return excluded


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


def _add_unsupported_genome_build_envelope(
    result: JsonObject,
    *,
    operation: str,
    pgs_id: str | None,
    genome_build: str,
) -> None:
    result["personal_context"] = {"uses_personal_dna": True}
    result["evidence_envelope"] = evidence_envelope.not_assessed(
        operation=operation,
        reason="PRS scoring-file workflows support GRCh37/hg19 and GRCh38/hg38 genome builds.",
        query_scope={
            "method": "published_polygenic_score",
            "pgs_id": pgs_id,
            "genome_build": genome_build,
        },
        personal_context={"uses_personal_dna": True},
        coverage={
            "libraries": [],
            "consulted_sources": [],
            "unavailable_sources": [],
            "materialization": [],
        },
        observations={"supported_genome_builds": list(scoring_files.SUPPORTED_GENOME_BUILDS)},
        next_actions=result.get("next_actions") or [],
        guidance=["out_of_scope_for_input:choose_supported_genome_build"],
    )


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


def _liftover_setup_required(
    preflight: JsonObject,
    *,
    operation: str,
    score: JsonObject,
    score_build: str,
    sample_build: str,
) -> JsonObject:
    result = dict(preflight)
    result["personal_context"] = {"uses_personal_dna": True}
    result["polygenic_score"] = score
    result["score_genome_build"] = score_build
    result["sample_genome_build"] = sample_build
    result["evidence_envelope"] = _liftover_setup_required_envelope(
        operation,
        result,
        score=score,
        score_build=score_build,
        sample_build=sample_build,
    )
    return result


def _liftover_setup_required_envelope(
    operation: str,
    result: JsonObject,
    *,
    score: JsonObject,
    score_build: str,
    sample_build: str,
) -> JsonObject:
    missing = result.get("missing_library") if isinstance(result.get("missing_library"), dict) else {}
    if missing and missing.get("install_command"):
        library = str(missing.get("library") or "liftover")
        return evidence_envelope.missing_library(
            operation=operation,
            library=library,
            library_status_payload=missing,
            query_scope={
                "method": "published_polygenic_score",
                "pgs_id": score.get("pgs_id"),
                "score_genome_build": score_build,
                "sample_genome_build": sample_build,
            },
            personal_context={"uses_personal_dna": True},
            intent=str(result.get("intent") or "lifting PRS score variants between genome builds"),
            next_actions=result.get("next_actions") or [],
            notes=[str(result.get("reason") or "liftover_setup_unavailable")],
            guidance=["blocked_missing_library:ask_user_to_install"],
        )
    return evidence_envelope.not_assessed(
        operation=operation,
        reason=str(result.get("reason") or "Liftover setup is unavailable."),
        personal_context={"uses_personal_dna": True},
        query_scope={
            "method": "published_polygenic_score",
            "pgs_id": score.get("pgs_id"),
            "score_genome_build": score_build,
            "sample_genome_build": sample_build,
        },
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
        coverage={
            "libraries": [{"library": str(score.get("pgs_id") or "local_prs_score"), "state": "installed"}],
            "consulted_sources": ["local_active_genome_index", "local_prs_score_cache"],
            "unavailable_sources": [],
            "materialization": [],
        },
        observations={
            "matched_variant_count": sample_qc.get("matched_variant_count"),
            "missing_variant_count": sample_qc.get("missing_variant_count"),
            "excluded_variant_count": sample_qc.get("excluded_variant_count"),
            "overlap_fraction": sample_qc.get("overlap_fraction"),
            "overlap_status": sample_qc.get("overlap_status"),
        },
        next_actions=result.get("next_actions") or [],
        guidance=["insufficient_overlap:use_more_complete_or_matching_genotype_source"],
    )
