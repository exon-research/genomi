from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from ..evidence import connect_evidence, default_evidence_path, init_evidence_db
from ..runtime.external import utc_now
from ..runtime.handoff import evidence_context
from ..runtime.paths import run_output_path, sample_slug_from_vcf
from ..runtime.static_dependencies import resolve_genome_build
from .genotype_resolver import resolve_locus_genotype
from .active_genome_index import (
    create_active_genome_index,
    default_active_genome_index_path,
    query_region,
    read_header_from_active_genome_index,
)
from .active_genome_index import connect_existing as connect_active_genome_index_existing
from .vcf import parse_region

DEFAULT_MIN_DEPTH = 10
DEFAULT_MIN_GENOTYPE_QUALITY = 20
DEFAULT_CALLABLE_FRACTION = 0.95


def assess_sample_qc(
    vcf: str | Path,
    *,
    active_genome_index_path: str | Path | None = None,
    evidence_db: str | Path | None = None,
    output: str | Path | None = None,
    genome_build: str = "auto",
    scan_records: int = 1000,
) -> dict[str, Any]:
    """Summarize callset shape and quality as deterministic sample evidence."""

    vcf_path = Path(vcf)
    active_genome_index_path = _ensure_active_genome_index(vcf_path, active_genome_index_path)
    effective_build = resolve_genome_build(vcf_path, genome_build)
    # Read the header and the FORMAT-key profile from the structured index —
    # never the canonical/source.
    with connect_active_genome_index_existing(active_genome_index_path) as _conn:
        header = read_header_from_active_genome_index(_conn)
        scan = _scan_record_profile(_conn, scan_records)
    counts = _active_genome_index_counts(active_genome_index_path)
    input_type = _classify_input_type(vcf_path, header.to_dict(), counts)
    has_reference_blocks = counts["reference_records"] > 0
    has_depth = counts["depth_present_records"] > 0
    has_genotype_quality = counts["genotype_quality_present_records"] > 0
    absence_allowed = has_reference_blocks and has_depth
    sample_id = header.samples[0] if header.samples else sample_slug_from_vcf(vcf_path)
    summary = {
        "total_records": counts["total_records"],
        "variant_records": counts["variant_records"],
        "reference_records": counts["reference_records"],
        "pass_records": counts["pass_records"],
        "fail_records": counts["fail_records"],
        "no_call_records": counts["no_call_records"],
        "depth_present_records": counts["depth_present_records"],
        "low_depth_records": counts["low_depth_records"],
        "genotype_quality_present_records": counts["genotype_quality_present_records"],
        "low_genotype_quality_records": counts["low_genotype_quality_records"],
        "filter_counts": counts["filter_counts"],
        "genotype_counts": counts["genotype_counts"],
        "format_key_counts": scan["format_key_counts"],
    }
    payload = {
        "workflow_area": "static",
        "status": "completed",
        "step": "sample-qc",
        "vcf": str(vcf_path),
        "active_genome_index_path": str(active_genome_index_path),
        "sample_id": sample_id,
        "genome_build": effective_build,
        "input_type": input_type,
        "has_reference_blocks": has_reference_blocks,
        "has_depth": has_depth,
        "has_genotype_quality": has_genotype_quality,
        "absence_claims_allowed_by_default": absence_allowed,
        "quality_thresholds": {
            "min_depth_for_supported_genotype": DEFAULT_MIN_DEPTH,
            "min_genotype_quality_for_supported_genotype": DEFAULT_MIN_GENOTYPE_QUALITY,
            "min_callable_fraction_for_region": DEFAULT_CALLABLE_FRACTION,
        },
        "summary": summary,
        "evidence_boundaries": _sample_qc_evidence_boundaries(input_type, absence_allowed),
        "evidence_context": evidence_context(
            "research",
            reason="Sample QC is available; intent research must use it to decide whether observed or absent alleles can support report claims.",
            commands=[
                "genomi call active_genome_index.classify_genotype_support --params '{\"vcf\":\"<vcf>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\",\"reference_fasta\":\"<GRCh38.fa>\"}'",
                "genomi call active_genome_index.classify_region_callability --params '{\"vcf\":\"<vcf>\",\"region\":\"<chrom:start-end>\"}'",
                "genomi call research.build_target_packet --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"gene\",\"gene\":\"<gene>\"}'",
            ],
        ),
    }
    db_path = Path(evidence_db) if evidence_db is not None else default_evidence_path(vcf_path)
    _record_sample_qc(db_path, payload)
    output_path = Path(output) if output is not None else run_output_path(vcf_path, "sample-qc.json")
    _write_json(output_path, payload)
    payload["output"] = str(output_path)
    return payload


def assess_genotype_support(
    vcf: str | Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    active_genome_index_path: str | Path | None = None,
    evidence_db: str | Path | None = None,
    output: str | Path | None = None,
    genome_build: str = "auto",
    reference_fasta: str | Path | None = None,
    min_depth: int = DEFAULT_MIN_DEPTH,
    min_genotype_quality: int = DEFAULT_MIN_GENOTYPE_QUALITY,
) -> dict[str, Any]:
    """Classify whether one VCF allele is technically supported in the sample."""

    vcf_path = Path(vcf)
    active_genome_index_path = _ensure_active_genome_index(vcf_path, active_genome_index_path)
    effective_build = resolve_genome_build(vcf_path, genome_build)
    support = resolve_locus_genotype(
        vcf_path,
        chrom,
        pos,
        ref,
        alt,
        active_genome_index_path=active_genome_index_path,
        reference_fasta=reference_fasta,
        min_depth=min_depth,
        min_genotype_quality=min_genotype_quality,
    )
    payload = {
        "workflow_area": "static",
        "status": "completed",
        "step": "genotype-support",
        "vcf": str(vcf_path),
        "active_genome_index_path": str(active_genome_index_path),
        "genome_build": effective_build,
        "variant": {
            "chrom": chrom,
            "pos": int(pos),
            "ref": ref,
            "alt": alt,
        },
        "support_status": support["support_status"],
        "evidence_class": support["evidence_class"],
        "accepted_report_evidence_classes": support["accepted_report_evidence_classes"],
        "sample_observation": support["sample_observation"],
        "quality_thresholds": {
            "min_depth": min_depth,
            "min_genotype_quality": min_genotype_quality,
        },
        "reference_fasta": str(reference_fasta) if reference_fasta is not None else None,
        "matched_records": support.get("matched_records", [])[:10],
        "site_observation": support.get("site_observation"),
        "evidence_boundaries": _genotype_evidence_boundaries(support),
        "evidence_context": evidence_context(
            "research",
            reason="Genotype support is classified; intent research can decide whether this allele may be interpreted, downgraded, or excluded from claims.",
            commands=[
                "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
            ],
        ),
    }
    db_path = Path(evidence_db) if evidence_db is not None else default_evidence_path(vcf_path)
    _record_genotype_support(db_path, payload)
    if output is not None:
        _write_json(Path(output), payload)
        payload["output"] = str(output)
    return payload


def assess_region_callability(
    vcf: str | Path,
    region: str,
    *,
    active_genome_index_path: str | Path | None = None,
    evidence_db: str | Path | None = None,
    output: str | Path | None = None,
    genome_build: str = "auto",
    min_depth: int = DEFAULT_MIN_DEPTH,
    min_covered_fraction: float = DEFAULT_CALLABLE_FRACTION,
    limit: int = 5000,
) -> dict[str, Any]:
    """Classify whether a region can support reference/absence claims."""

    vcf_path = Path(vcf)
    active_genome_index_path = _ensure_active_genome_index(vcf_path, active_genome_index_path)
    effective_build = resolve_genome_build(vcf_path, genome_build)
    chrom, start, end = parse_region(region)
    records = query_region(vcf_path, chrom, start, end, active_genome_index_path, variants_only=False, pass_only=False, limit=limit)
    counts = _active_genome_index_counts(active_genome_index_path)
    callability = _classify_callability(
        records,
        start,
        end,
        has_reference_blocks=counts["reference_records"] > 0,
        min_depth=min_depth,
        min_covered_fraction=min_covered_fraction,
        truncated=len(records) >= limit,
    )
    payload = {
        "workflow_area": "static",
        "status": "completed",
        "step": "callability",
        "vcf": str(vcf_path),
        "active_genome_index_path": str(active_genome_index_path),
        "genome_build": effective_build,
        "region": region,
        "chrom": chrom,
        "start": start,
        "end": end,
        "callability_status": callability["callability_status"],
        "covered_bases": callability["covered_bases"],
        "requested_bases": callability["requested_bases"],
        "covered_fraction": callability["covered_fraction"],
        "segments": callability["segments"],
        "can_support_negative_or_reference_claim": callability["can_support_negative_or_reference_claim"],
        "evidence_class": callability["evidence_class"],
        "accepted_report_evidence_classes": callability["accepted_report_evidence_classes"],
        "quality_thresholds": {
            "min_depth": min_depth,
            "min_covered_fraction": min_covered_fraction,
        },
        "matched_records": records[:20],
        "evidence_boundaries": _callability_evidence_boundaries(callability),
        "evidence_context": evidence_context(
            "research",
            reason="Region callability is classified; intent research can use it for scoped absence/reference claims.",
            commands=[
                "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
            ],
        ),
    }
    db_path = Path(evidence_db) if evidence_db is not None else default_evidence_path(vcf_path)
    _record_region_callability(db_path, payload)
    if output is not None:
        _write_json(Path(output), payload)
        payload["output"] = str(output)
    return payload


def _ensure_active_genome_index(vcf_path: Path, active_genome_index_path: str | Path | None) -> Path:
    active_genome_index_path = Path(active_genome_index_path) if active_genome_index_path is not None else default_active_genome_index_path(vcf_path)
    if not active_genome_index_path.exists():
        create_active_genome_index(vcf_path, active_genome_index_path, include_reference=True)
    return active_genome_index_path


def _active_genome_index_counts(active_genome_index_path: Path) -> dict[str, Any]:
    with connect_active_genome_index_existing(active_genome_index_path) as connection:
        row = connection.execute(
            """
            select
              count(*) as total_records,
              sum(case when is_variant = 1 then 1 else 0 end) as variant_records,
              sum(case when is_variant = 0 then 1 else 0 end) as reference_records,
              sum(case when filter in ('PASS', '.') then 1 else 0 end) as pass_records,
              sum(case when filter not in ('PASS', '.') then 1 else 0 end) as fail_records,
              sum(case when depth is not null then 1 else 0 end) as depth_present_records,
              sum(case when depth is not null and depth < ? then 1 else 0 end) as low_depth_records,
              sum(case when genotype_quality is not null then 1 else 0 end) as genotype_quality_present_records,
              sum(case when genotype_quality is not null and genotype_quality < ? then 1 else 0 end)
                as low_genotype_quality_records,
              sum(case when genotype is null or genotype in ('./.', '.|.', '.') or genotype like './%' or genotype like '%/.'
                    or genotype like '.|%' or genotype like '%|.' then 1 else 0 end) as no_call_records
            from records
            """,
            (DEFAULT_MIN_DEPTH, DEFAULT_MIN_GENOTYPE_QUALITY),
        ).fetchone()
        filter_counts = {
            str(item["filter"]): int(item["records"])
            for item in connection.execute(
                "select coalesce(filter, '') as filter, count(*) as records from records group by filter order by records desc"
            )
        }
        genotype_counts = {
            str(item["genotype"]): int(item["records"])
            for item in connection.execute(
                """
                select coalesce(genotype, '') as genotype, count(*) as records
                from records
                group by genotype
                order by records desc
                """
            )
        }
    return {
        key: int(row[key] or 0)
        for key in (
            "total_records",
            "variant_records",
            "reference_records",
            "pass_records",
            "fail_records",
            "depth_present_records",
            "low_depth_records",
            "genotype_quality_present_records",
            "low_genotype_quality_records",
            "no_call_records",
        )
    } | {"filter_counts": filter_counts, "genotype_counts": genotype_counts}


def _scan_record_profile(connection: Any, limit: int) -> dict[str, Any]:
    # FORMAT keys are stored verbatim in the records.format column; tally them
    # from the index instead of scanning the canonical/source VCF.
    format_keys: Counter[str] = Counter()
    scanned = 0
    for row in connection.execute(
        "select format from records order by chrom_sort, pos, offset, sample_index limit ?",
        (limit,),
    ):
        scanned += 1
        fmt = row["format"]
        for key in str(fmt).split(":") if fmt else []:
            format_keys[key] += 1
    return {
        "scanned_records": scanned,
        "scan_record_limit": limit,
        "format_key_counts": format_keys.most_common(),
    }


def _classify_input_type(vcf_path: Path, header: dict[str, Any], counts: dict[str, Any]) -> str:
    text = " ".join(
        [
            vcf_path.name,
            str(header.get("source") or ""),
            str(header.get("dataSourceType") or ""),
            str(header.get("dataAnalysisProvider") or ""),
            str(header.get("reference") or ""),
        ]
    ).lower()
    if "imput" in text:
        return "imputed_genotype_callset"
    if counts["reference_records"] > 0 or "gvcf" in text:
        return "callset_with_reference_blocks"
    if any(marker in text for marker in ("23andme", "ancestry", "array", "snp", "genotyping")):
        return "array_or_genotyping_callset"
    if "exome" in text or "wes" in text:
        return "exome_variant_callset"
    if "wgs" in text or "whole genome" in text:
        return "wgs_variant_callset"
    return "variant_only_callset"


def _classify_callability(
    records: list[dict[str, Any]],
    start: int,
    end: int,
    *,
    has_reference_blocks: bool,
    min_depth: int,
    min_covered_fraction: float,
    truncated: bool,
) -> dict[str, Any]:
    requested_bases = end - start + 1
    if not has_reference_blocks:
        status = "unknown_no_reference_blocks"
        segments: list[dict[str, int]] = []
        covered_bases = 0
    elif truncated:
        status = "unknown_truncated"
        segments = []
        covered_bases = 0
    else:
        raw_segments: list[tuple[int, int]] = []
        depth_missing = False
        for record in records:
            if str(record.get("filter") or "") not in {"PASS", "."}:
                continue
            depth = _optional_int(record.get("depth"))
            if depth is None:
                depth_missing = True
                continue
            if depth < min_depth:
                continue
            segment_start = max(start, int(record["pos"]))
            segment_end = min(end, int(record["end"]))
            if segment_start <= segment_end:
                raw_segments.append((segment_start, segment_end))
        merged = _merge_segments(raw_segments)
        segments = [{"start": left, "end": right} for left, right in merged]
        covered_bases = sum(right - left + 1 for left, right in merged)
        covered_fraction = covered_bases / requested_bases if requested_bases else 0.0
        if depth_missing and covered_fraction < min_covered_fraction:
            status = "unknown_missing_depth"
        elif covered_fraction >= min_covered_fraction:
            status = "callable"
        elif covered_fraction > 0:
            status = "partially_callable"
        else:
            status = "not_callable"
    covered_fraction = covered_bases / requested_bases if requested_bases else 0.0
    can_support = status == "callable"
    return {
        "callability_status": status,
        "requested_bases": requested_bases,
        "covered_bases": covered_bases,
        "covered_fraction": covered_fraction,
        "segments": segments,
        "can_support_negative_or_reference_claim": can_support,
        "evidence_class": "callability_supported" if can_support else "callability_not_supported",
        "accepted_report_evidence_classes": ["reference_inference_or_assay_completeness"] if can_support else [],
    }


def _merge_segments(segments: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not segments:
        return []
    ordered = sorted(segments)
    merged = [ordered[0]]
    for left, right in ordered[1:]:
        last_left, last_right = merged[-1]
        if left <= last_right + 1:
            merged[-1] = (last_left, max(last_right, right))
        else:
            merged.append((left, right))
    return merged


def _sample_qc_evidence_boundaries(input_type: str, absence_allowed: bool) -> dict[str, Any]:
    absence_rule = (
        "Reference or absence claims need callable status for the exact locus."
        if absence_allowed
        else "Reference or absence claims need gVCF, BAM/CRAM, coverage report, array manifest, or other callability evidence."
    )
    return {
        "component": "sample_qc",
        "input_type": input_type,
        "absence_claims_allowed_by_default": absence_allowed,
        "available_operations": [
            "active_genome_index.classify_genotype_support",
            "active_genome_index.classify_region_callability",
        ],
        "evidence_boundaries": [
            "Treat a missing variant-only VCF row as unknown genotype context.",
            "Carry weak, unknown, no-call, or not-observed support as limitation or follow-up evidence context.",
            "Use static QC as technical context for research and reporting.",
            absence_rule,
            "If a result depends on combinations of alleles, phase, phenotype, family history, or user medication context, store the conclusion privately.",
        ],
    }


def _genotype_evidence_boundaries(support: dict[str, Any]) -> dict[str, Any]:
    status = support["support_status"]
    accepted = set(support.get("accepted_report_evidence_classes") or [])
    if status == "supported":
        boundary = "This supports sample_observation plus genotype_support_supported evidence."
    elif "reference_inference_or_assay_completeness" in accepted:
        boundary = "This supports narrow reference/absence evidence for the queried locus, with target alternate allele carry status kept separate."
    elif status == "weak":
        boundary = "This is limitation context until stronger sample evidence supports personal interpretation."
    elif status == "unknown":
        boundary = "This is technically incomplete sample context."
    else:
        boundary = "Sample carry evidence is absent; public interpretation remains background evidence."
    return {
        "component": "sample_genotype_support",
        "support_status": status,
        "evidence_boundaries": [
            boundary,
            "Keep public interpretation evidence separate from weak/no-call sample observation evidence.",
            "Store this sample-specific support row in the private evidence DB.",
        ],
    }


def _callability_evidence_boundaries(callability: dict[str, Any]) -> dict[str, Any]:
    status = callability["callability_status"]
    if callability["can_support_negative_or_reference_claim"]:
        boundary = "reference_inference_or_assay_completeness supports a narrowly scoped not-observed/reference claim."
    else:
        boundary = "Negative/reference claims in this region need additional callability evidence."
    return {
        "component": "region_callability",
        "callability_status": status,
        "evidence_boundaries": [
            boundary,
            "Keep negative language narrow: not observed or callable in this file, not disease excluded.",
            "Use broader disease exclusion only with external clinical assay scope evidence and clinical confirmation.",
            "Treat variant-only callsets as insufficient for absence inference.",
            "Treat callable regions as locus-scoped evidence rather than complete disease exclusion.",
        ],
    }


def _record_sample_qc(evidence_db: Path, payload: dict[str, Any]) -> None:
    init_evidence_db(evidence_db)
    with connect_evidence(evidence_db) as connection:
        connection.execute(
            """
            insert or replace into sample_qc (
                sample_id, vcf_path, genome_build, input_type, has_reference_blocks,
                has_depth, has_genotype_quality, absence_claims_allowed,
                summary_json, evidence_boundaries_json, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["sample_id"],
                payload["vcf"],
                payload["genome_build"],
                payload["input_type"],
                int(payload["has_reference_blocks"]),
                int(payload["has_depth"]),
                int(payload["has_genotype_quality"]),
                int(payload["absence_claims_allowed_by_default"]),
                json.dumps(payload["summary"], sort_keys=True),
                json.dumps(payload["evidence_boundaries"], sort_keys=True),
                utc_now(),
            ),
        )
        connection.commit()


def _record_genotype_support(evidence_db: Path, payload: dict[str, Any]) -> None:
    init_evidence_db(evidence_db)
    observation = payload["sample_observation"]
    variant = payload["variant"]
    with connect_evidence(evidence_db) as connection:
        connection.execute(
            """
            insert or replace into genotype_support (
                vcf_path, chrom, pos, ref, alt, genome_build, support_status,
                evidence_class, genotype, zygosity, depth, genotype_quality,
                filter, raw_json, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["vcf"],
                variant["chrom"],
                variant["pos"],
                variant["ref"],
                variant["alt"],
                payload["genome_build"],
                payload["support_status"],
                payload["evidence_class"],
                observation.get("genotype"),
                observation.get("zygosity"),
                observation.get("depth"),
                observation.get("genotype_quality"),
                observation.get("filter"),
                json.dumps(payload, sort_keys=True),
                utc_now(),
            ),
        )
        connection.commit()


def _record_region_callability(evidence_db: Path, payload: dict[str, Any]) -> None:
    init_evidence_db(evidence_db)
    with connect_evidence(evidence_db) as connection:
        connection.execute(
            """
            insert or replace into region_callability (
                vcf_path, region, chrom, start, end, genome_build, callability_status,
                covered_fraction, can_support_negative_claim, evidence_class,
                raw_json, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["vcf"],
                payload["region"],
                payload["chrom"],
                payload["start"],
                payload["end"],
                payload["genome_build"],
                payload["callability_status"],
                payload["covered_fraction"],
                int(payload["can_support_negative_or_reference_claim"]),
                payload["evidence_class"],
                json.dumps(payload, sort_keys=True),
                utc_now(),
            ),
        )
        connection.commit()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _optional_int(value: Any) -> int | None:
    if value in (None, "", "."):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
