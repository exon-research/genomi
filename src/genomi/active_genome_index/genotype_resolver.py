from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .active_genome_index import query_region


@dataclass(frozen=True)
class FastaIndexRow:
    name: str
    length: int
    offset: int
    line_bases: int
    line_width: int


def resolve_locus_genotype(
    vcf: str | Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    active_genome_index_path: str | Path,
    reference_fasta: str | Path | None = None,
    min_depth: int = 10,
    min_genotype_quality: int = 20,
) -> dict[str, Any]:
    """Resolve one target allele into deterministic sample-site evidence."""

    vcf_path = Path(vcf)
    active_genome_index_path = Path(active_genome_index_path)
    records = _records_covering_locus(vcf_path, active_genome_index_path, chrom, pos)
    return resolve_locus_genotype_from_records(
        records,
        chrom,
        pos,
        ref,
        alt,
        reference_fasta=reference_fasta,
        min_depth=min_depth,
        min_genotype_quality=min_genotype_quality,
    )


def resolve_locus_genotype_from_records(
    records: list[dict[str, Any]],
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    reference_fasta: str | Path | None = None,
    min_depth: int = 10,
    min_genotype_quality: int = 20,
) -> dict[str, Any]:
    """Resolve one target allele from already-fetched Active Genome Index records."""

    records = [_normalize_record(record) for record in records]
    exact_alt_records = [
        record
        for record in records
        if record.get("is_variant")
        and int(record.get("pos") or 0) == int(pos)
        and record.get("ref") == ref
        and alt in (record.get("alts") or [])
    ]
    if exact_alt_records:
        record = _best_record(exact_alt_records)
        return _classify_variant_record(
            record,
            target_ref=ref,
            target_alt=alt,
            min_depth=min_depth,
            min_genotype_quality=min_genotype_quality,
            matched_by="exact_variant",
            records=records,
        )

    overlapping_complex_variants = [
        record
        for record in records
        if record.get("is_variant")
        and int(record.get("pos") or 0) <= int(pos) <= int(record.get("end") or 0)
        and _record_has_complex_allele(record)
    ]
    if overlapping_complex_variants:
        record = _best_record(overlapping_complex_variants)
        return _classify_projected_variant_record(
            record,
            target_pos=pos,
            target_ref=ref,
            target_alt=alt,
            min_depth=min_depth,
            min_genotype_quality=min_genotype_quality,
            records=records,
        )

    same_site_variants = [
        record
        for record in records
        if record.get("is_variant") and int(record.get("pos") or 0) == int(pos)
    ]
    if same_site_variants:
        record = _best_record(same_site_variants)
        return _classify_variant_record(
            record,
            target_ref=ref,
            target_alt=alt,
            min_depth=min_depth,
            min_genotype_quality=min_genotype_quality,
            matched_by="same_site_variant",
            records=records,
            limitation=(
                "A variant record exists at the site, but the exact target ref/alt was not observed in that row."
            ),
        )

    reference_blocks = [
        record
        for record in records
        if not record.get("is_variant") and int(record.get("pos") or 0) <= int(pos) <= int(record.get("end") or 0)
    ]
    if reference_blocks:
        record = _best_record(reference_blocks)
        return _classify_reference_record(
            record,
            target_chrom=chrom,
            target_pos=pos,
            target_ref=ref,
            target_alt=alt,
            reference_fasta=reference_fasta,
            min_depth=min_depth,
            records=records,
        )

    return _support_payload(
        "unknown",
        "genotype_support_unknown",
        "No VCF record covers this locus, so the data layer cannot distinguish homozygous reference from not callable.",
        record=None,
        alt_allele_count=None,
        matched_records=records,
        site_observation={
            "site_status": "not_represented",
            "record_type": None,
            "matched_by": None,
            "allele_bases": [],
            "reference_call_supported": False,
        },
    )


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    if "alts" not in payload:
        payload["alts"] = [alt for alt in str(payload.get("alt") or "").split(",") if alt and alt != "."]
    return payload


def _records_covering_locus(vcf_path: Path, active_genome_index_path: Path, chrom: str, pos: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_offsets: set[tuple[int, int]] = set()
    for query_chrom in _chrom_candidates(chrom):
        for record in query_region(
            vcf_path,
            query_chrom,
            pos,
            pos,
            active_genome_index_path,
            variants_only=False,
            pass_only=False,
            limit=500,
        ):
            offset = record.get("offset")
            if isinstance(offset, int):
                sample_index = int(record.get("sample_index") or 0)
                key = (offset, sample_index)
                if key in seen_offsets:
                    continue
                seen_offsets.add(key)
            records.append(record)
    return records


def _chrom_candidates(chrom: str) -> list[str]:
    candidates = [chrom]
    if chrom.startswith("chr"):
        stripped = chrom[3:]
        candidates.append("MT" if stripped == "M" else stripped)
    else:
        candidates.append("chrM" if chrom == "MT" else f"chr{chrom}")
    if chrom == "M":
        candidates.extend(["MT", "chrM"])
    if chrom == "chrM":
        candidates.extend(["M", "MT"])
    return _unique(candidates)


def _classify_variant_record(
    record: dict[str, Any],
    *,
    target_ref: str,
    target_alt: str,
    min_depth: int,
    min_genotype_quality: int,
    matched_by: str,
    records: list[dict[str, Any]],
    limitation: str | None = None,
) -> dict[str, Any]:
    genotype = str(record.get("genotype") or "")
    alts = [str(alt) for alt in (record.get("alts") or [])]
    alt_allele_count = _target_alt_count(genotype, alts, target_alt)
    allele_bases = _genotype_allele_bases(genotype, str(record.get("ref") or ""), alts)
    site_observation = _site_observation(
        record,
        matched_by=matched_by,
        allele_bases=allele_bases,
        alt_allele_count=alt_allele_count,
        reference_call_supported=(
            alt_allele_count == 0
            and str(record.get("ref") or "") == target_ref
            and bool(allele_bases)
            and all(base == target_ref for base in allele_bases)
            and _record_quality_supported(record, min_depth=min_depth)
        ),
        status="variant",
        limitation=limitation,
    )
    if alt_allele_count is None:
        return _support_payload(
            "no_call",
            "genotype_support_no_call",
            "The record exists but the genotype is missing or no-called.",
            record=record,
            alt_allele_count=None,
            matched_records=records,
            site_observation=site_observation,
        )
    if alt_allele_count == 0:
        return _support_payload(
            "not_observed",
            "genotype_support_not_observed",
            limitation or "The site is represented, but this target alternate allele is not carried by the sample.",
            record=record,
            alt_allele_count=0,
            matched_records=records,
            site_observation=site_observation,
        )
    weak_reason = _weak_variant_reason(record, min_depth=min_depth, min_genotype_quality=min_genotype_quality)
    if weak_reason is not None:
        return _support_payload(
            "weak",
            "genotype_support_weak",
            weak_reason,
            record=record,
            alt_allele_count=alt_allele_count,
            matched_records=records,
            site_observation=site_observation,
        )
    if record.get("depth") is None or record.get("genotype_quality") is None:
        return _support_payload(
            "unknown",
            "genotype_support_unknown",
            "The observed alternate allele is present, but DP or GQ is missing from the callset.",
            record=record,
            alt_allele_count=alt_allele_count,
            matched_records=records,
            site_observation=site_observation,
        )
    return _support_payload(
        "supported",
        "genotype_support_supported",
        "The observed alternate allele passes filter and meets DP/GQ thresholds.",
        record=record,
        alt_allele_count=alt_allele_count,
        matched_records=records,
        site_observation=site_observation,
    )


def _classify_projected_variant_record(
    record: dict[str, Any],
    *,
    target_pos: int,
    target_ref: str,
    target_alt: str,
    min_depth: int,
    min_genotype_quality: int,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    genotype = str(record.get("genotype") or "")
    alts = [str(alt) for alt in (record.get("alts") or [])]
    allele_bases = _project_genotype_bases_at_locus(
        genotype,
        str(record.get("ref") or ""),
        alts,
        record_pos=int(record.get("pos") or 0),
        target_pos=target_pos,
    )
    site_observation = _site_observation(
        record,
        matched_by="overlapping_variant_projection",
        allele_bases=allele_bases,
        alt_allele_count=None,
        reference_call_supported=False,
        status="complex_projection",
        limitation=None,
        record_type="complex_projection",
    )
    if _genotype_is_no_call(genotype):
        return _support_payload(
            "no_call",
            "genotype_support_no_call",
            "An overlapping complex variant record covers this locus, but the genotype is missing or no-called.",
            record=record,
            alt_allele_count=None,
            matched_records=records,
            site_observation=site_observation,
        )
    if len(target_ref) != 1 or len(target_alt) != 1 or not allele_bases:
        return _unresolved_complex_projection(record, records, site_observation)
    allowed = {target_ref, target_alt}
    if any(base not in allowed for base in allele_bases):
        site_observation["site_status"] = "complex_projection_conflict"
        return _support_payload(
            "unknown",
            "genotype_support_unknown",
            "The overlapping complex variant projects to bases outside the requested ref/alt alleles.",
            record=record,
            alt_allele_count=None,
            matched_records=records,
            site_observation=site_observation,
        )
    alt_allele_count = sum(1 for base in allele_bases if base == target_alt)
    site_observation["alt_allele_count"] = alt_allele_count
    site_observation["reference_call_supported"] = (
        alt_allele_count == 0
        and all(base == target_ref for base in allele_bases)
        and _record_quality_supported(record, min_depth=min_depth)
    )
    if alt_allele_count == 0:
        return _support_payload(
            "not_observed",
            "genotype_support_not_observed",
            "An overlapping complex variant record projects to the reference allele at this target site.",
            record=record,
            alt_allele_count=0,
            matched_records=records,
            site_observation=site_observation,
        )
    weak_reason = _weak_variant_reason(record, min_depth=min_depth, min_genotype_quality=min_genotype_quality)
    if weak_reason is not None:
        return _support_payload(
            "weak",
            "genotype_support_weak",
            weak_reason,
            record=record,
            alt_allele_count=alt_allele_count,
            matched_records=records,
            site_observation=site_observation,
        )
    if record.get("depth") is None or record.get("genotype_quality") is None:
        return _support_payload(
            "unknown",
            "genotype_support_unknown",
            "The projected target allele is present, but DP or GQ is missing from the callset.",
            record=record,
            alt_allele_count=alt_allele_count,
            matched_records=records,
            site_observation=site_observation,
        )
    return _support_payload(
        "supported",
        "genotype_support_supported",
        "An overlapping complex variant record unambiguously projects to the target alternate allele.",
        record=record,
        alt_allele_count=alt_allele_count,
        matched_records=records,
        site_observation=site_observation,
    )


def _unresolved_complex_projection(
    record: dict[str, Any],
    records: list[dict[str, Any]],
    site_observation: dict[str, Any],
) -> dict[str, Any]:
    site_observation["site_status"] = "complex_projection_unresolved"
    return _support_payload(
        "unknown",
        "genotype_support_unknown",
        "An overlapping complex variant record covers this locus, but it could not be projected to a simple requested base genotype.",
        record=record,
        alt_allele_count=None,
        matched_records=records,
        site_observation=site_observation,
    )


def _classify_reference_record(
    record: dict[str, Any],
    *,
    target_chrom: str,
    target_pos: int,
    target_ref: str,
    target_alt: str,
    reference_fasta: str | Path | None,
    min_depth: int,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    genotype = str(record.get("genotype") or "")
    reference_base = _reference_base_for_locus(record, target_chrom, target_pos, reference_fasta)
    if reference_base is None:
        return _support_payload(
            "unknown",
            "genotype_support_unknown",
            "A gVCF reference block covers this locus, but the exact interior reference base was not resolved.",
            record=record,
            alt_allele_count=None,
            matched_records=records,
            site_observation=_site_observation(
                record,
                matched_by="reference_block_unresolved",
                allele_bases=[],
                alt_allele_count=None,
                reference_call_supported=False,
                status="reference_block_unresolved",
                limitation="Pass a matching --reference-fasta to resolve interior gVCF reference-block bases.",
            ),
        )
    allele_bases = _reference_allele_bases(genotype, reference_base)
    reference_supported = (
        reference_base == target_ref
        and target_alt not in allele_bases
        and _record_quality_supported(record, min_depth=min_depth)
    )
    site_observation = _site_observation(
        record,
        matched_by="reference_block",
        allele_bases=allele_bases,
        alt_allele_count=0,
        reference_call_supported=reference_supported,
        status="homozygous_reference" if reference_supported else "reference_block_weak",
        limitation=None
        if reference_base == target_ref
        else f"Reference FASTA base {reference_base} does not match target ref {target_ref}.",
    )
    site_observation["reference_base"] = reference_base
    site_observation["reference_base_source"] = "reference_fasta" if reference_fasta is not None else "record_ref"
    if _genotype_is_no_call(genotype):
        return _support_payload(
            "no_call",
            "genotype_support_no_call",
            "A reference/nonvariant record covers this locus, but the genotype is no-called.",
            record=record,
            alt_allele_count=None,
            matched_records=records,
            site_observation=site_observation,
        )
    if not reference_supported:
        return _support_payload(
            "weak",
            "genotype_support_weak",
            "A reference/nonvariant record covers this locus, but filter or depth does not support a reference inference.",
            record=record,
            alt_allele_count=0,
            matched_records=records,
            site_observation=site_observation,
        )
    return _support_payload(
        "not_observed",
        "genotype_support_not_observed",
        "A PASS reference block covers this locus and supports a homozygous-reference observation for the target site.",
        record=record,
        alt_allele_count=0,
        matched_records=records,
        site_observation=site_observation,
    )


def _reference_base_for_locus(
    record: dict[str, Any],
    target_chrom: str,
    target_pos: int,
    reference_fasta: str | Path | None,
) -> str | None:
    if int(record.get("pos") or 0) == int(target_pos) and len(str(record.get("ref") or "")) == 1:
        return str(record["ref"]).upper()
    if reference_fasta is None:
        return None
    return fetch_reference_base(reference_fasta, str(record.get("chrom") or target_chrom), target_pos)


def fetch_reference_base(reference_fasta: str | Path, chrom: str, pos: int) -> str | None:
    fasta_path = Path(reference_fasta)
    fai_path = Path(f"{fasta_path}.fai")
    if fai_path.exists():
        return _fetch_reference_base_with_fai(fasta_path, fai_path, chrom, pos)
    return _fetch_reference_base_sequential(fasta_path, chrom, pos)


def _fetch_reference_base_with_fai(fasta_path: Path, fai_path: Path, chrom: str, pos: int) -> str | None:
    rows = _read_fai(fai_path)
    for candidate in _chrom_candidates(chrom):
        row = rows.get(candidate)
        if row is None or pos < 1 or pos > row.length:
            continue
        zero_based = pos - 1
        byte_offset = row.offset + (zero_based // row.line_bases) * row.line_width + (zero_based % row.line_bases)
        with fasta_path.open("rb") as handle:
            handle.seek(byte_offset)
            base = handle.read(1).decode("ascii", errors="ignore").upper()
        return base if base in {"A", "C", "G", "T", "N"} else None
    return None


def _read_fai(fai_path: Path) -> dict[str, FastaIndexRow]:
    rows: dict[str, FastaIndexRow] = {}
    with fai_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            name, length, offset, line_bases, line_width = line.rstrip("\n").split("\t")[:5]
            rows[name] = FastaIndexRow(
                name=name,
                length=int(length),
                offset=int(offset),
                line_bases=int(line_bases),
                line_width=int(line_width),
            )
    return rows


def _fetch_reference_base_sequential(fasta_path: Path, chrom: str, pos: int) -> str | None:
    wanted = set(_chrom_candidates(chrom))
    current: str | None = None
    observed = 0
    with fasta_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                current = line[1:].split()[0]
                observed = 0
                continue
            if current not in wanted:
                continue
            if observed + len(line) < pos:
                observed += len(line)
                continue
            index = pos - observed - 1
            if 0 <= index < len(line):
                base = line[index].upper()
                return base if base in {"A", "C", "G", "T", "N"} else None
            observed += len(line)
    return None


def _support_payload(
    status: str,
    evidence_class: str,
    limitation: str,
    *,
    record: dict[str, Any] | None,
    alt_allele_count: int | None,
    matched_records: list[dict[str, Any]],
    site_observation: dict[str, Any],
) -> dict[str, Any]:
    observation = {
        "observed": status in {"supported", "weak", "unknown"} and bool(alt_allele_count),
        "target_alt_observed": bool(alt_allele_count),
        "genotype": record.get("genotype") if record else None,
        "zygosity": _zygosity(record.get("genotype") if record else None, alt_allele_count),
        "alt_allele_count": alt_allele_count,
        "filter": record.get("filter") if record else None,
        "depth": record.get("depth") if record else None,
        "genotype_quality": record.get("genotype_quality") if record else None,
        **site_observation,
        "limitation": limitation,
    }
    accepted: list[str] = []
    if status == "supported":
        accepted = ["sample_observation", "genotype_support_supported"]
    elif observation.get("reference_call_supported"):
        accepted = ["reference_inference_or_assay_completeness"]
    return {
        "support_status": status,
        "evidence_class": evidence_class,
        "accepted_report_evidence_classes": accepted,
        "sample_observation": observation,
        "matched_records": matched_records[:20],
        "site_observation": site_observation,
    }


def _site_observation(
    record: dict[str, Any],
    *,
    matched_by: str,
    allele_bases: list[str],
    alt_allele_count: int | None,
    reference_call_supported: bool,
    status: str,
    limitation: str | None,
    record_type: str | None = None,
) -> dict[str, Any]:
    return {
        "site_status": status,
        "record_type": record_type or ("variant" if record.get("is_variant") else "reference_block"),
        "matched_by": matched_by,
        "allele_bases": allele_bases,
        "observed_genotype": "/".join(allele_bases) if allele_bases else None,
        "alt_allele_count": alt_allele_count,
        "reference_call_supported": reference_call_supported,
        "source_record": _compact_record(record),
        "limitation": limitation,
    }


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "chrom": record.get("chrom"),
        "pos": record.get("pos"),
        "end": record.get("end"),
        "id": record.get("id"),
        "sample_index": record.get("sample_index"),
        "sample_name": record.get("sample_name"),
        "ref": record.get("ref"),
        "alt": record.get("alt"),
        "alts": record.get("alts"),
        "filter": record.get("filter"),
        "genotype": record.get("genotype"),
        "depth": record.get("depth"),
        "genotype_quality": record.get("genotype_quality"),
    }


def _best_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(
        records,
        key=lambda item: (
            0 if item.get("filter") in {"PASS", "."} else 1,
            -int(item.get("depth") or 0),
            -int(item.get("genotype_quality") or 0),
        ),
    )[0]


def _target_alt_count(genotype: str, alts: list[str], target_alt: str) -> int | None:
    if _genotype_is_no_call(genotype):
        return None
    target_index = alts.index(target_alt) + 1 if target_alt in alts else None
    if target_index is None:
        return 0
    return sum(1 for token in _genotype_tokens(genotype) if token == str(target_index))


def _record_has_complex_allele(record: dict[str, Any]) -> bool:
    ref = str(record.get("ref") or "")
    alts = [str(alt) for alt in record.get("alts") or []]
    return len(ref) != 1 or any(len(alt) != 1 for alt in alts)


def _project_genotype_bases_at_locus(
    genotype: str,
    ref: str,
    alts: list[str],
    *,
    record_pos: int,
    target_pos: int,
) -> list[str]:
    if _genotype_is_no_call(genotype):
        return []
    offset = target_pos - record_pos
    if offset < 0:
        return []
    allele_bases: list[str] = []
    alleles = [ref, *alts]
    for token in _genotype_tokens(genotype):
        try:
            allele_index = int(token)
        except ValueError:
            return []
        if not 0 <= allele_index < len(alleles):
            return []
        allele = alleles[allele_index]
        if offset >= len(allele):
            allele_bases.append("-")
            continue
        base = allele[offset].upper()
        if base not in {"A", "C", "G", "T"}:
            return []
        allele_bases.append(base)
    return allele_bases


def _genotype_allele_bases(genotype: str, ref: str, alts: list[str]) -> list[str]:
    if _genotype_is_no_call(genotype):
        return []
    allele_bases: list[str] = []
    for token in _genotype_tokens(genotype):
        if token == "0":
            allele_bases.append(ref)
            continue
        try:
            allele_index = int(token) - 1
        except ValueError:
            continue
        if 0 <= allele_index < len(alts):
            allele_bases.append(alts[allele_index])
    return allele_bases


def _reference_allele_bases(genotype: str, reference_base: str) -> list[str]:
    if _genotype_is_no_call(genotype):
        return []
    ploidy = len(_genotype_tokens(genotype)) or 2
    return [reference_base] * ploidy


def _genotype_tokens(genotype: str) -> list[str]:
    return [token for token in genotype.replace("|", "/").split("/") if token not in {"", "."}]


def _genotype_is_no_call(genotype: str) -> bool:
    if not genotype or genotype == ".":
        return True
    return any(token == "." for token in genotype.replace("|", "/").split("/"))


def _weak_variant_reason(record: dict[str, Any], *, min_depth: int, min_genotype_quality: int) -> str | None:
    if str(record.get("filter") or "") not in {"", "PASS", "."}:
        return "The observed alternate allele has a non-PASS VCF filter."
    depth = _optional_int(record.get("depth"))
    genotype_quality = _optional_int(record.get("genotype_quality"))
    if depth is not None and depth < min_depth:
        return "The observed alternate allele is below the minimum read-depth threshold."
    if genotype_quality is not None and genotype_quality < min_genotype_quality:
        return "The observed alternate allele is below the minimum genotype-quality threshold."
    return None


def _record_quality_supported(record: dict[str, Any], *, min_depth: int) -> bool:
    if str(record.get("filter") or "") not in {"", "PASS", "."}:
        return False
    depth = _optional_int(record.get("depth"))
    return depth is None or depth >= min_depth


def _zygosity(genotype: Any, alt_allele_count: int | None) -> str:
    if alt_allele_count is None:
        return "unknown"
    alleles = str(genotype or "").replace("|", "/").split("/")
    ploidy = len([allele for allele in alleles if allele not in {"", "."}])
    if alt_allele_count == 0:
        return "reference_or_other_alternate"
    if ploidy and alt_allele_count >= ploidy:
        return "homozygous_alternate"
    return "heterozygous"


def _optional_int(value: Any) -> int | None:
    if value in (None, "", "."):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unique(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique
