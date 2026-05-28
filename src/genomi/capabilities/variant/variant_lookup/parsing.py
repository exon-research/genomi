from __future__ import annotations

import json
import re
from typing import Any

from ....active_genome_index.vcf import parse_region
from ....runtime import context as runtime_context

JsonObject = dict[str, Any]

RSID_RE = re.compile(r"\brs\d+\b", re.IGNORECASE)
EXACT_COLON_RE = re.compile(
    r"\b(?:chr)?(?P<chrom>[0-9]{1,2}|X|Y|M|MT):(?P<pos>[0-9,]+):(?P<ref>[ACGTN]+):(?P<alt>[ACGTN.\-]+)\b",
    re.IGNORECASE,
)
EXACT_ARROW_RE = re.compile(
    r"\b(?:chr)?(?P<chrom>[0-9]{1,2}|X|Y|M|MT):(?P<pos>[0-9,]+)\s+"
    r"(?P<ref>[ACGTN]+)\s*(?:>|/)\s*(?P<alt>[ACGTN.\-]+)\b",
    re.IGNORECASE,
)
REGION_RE = re.compile(
    r"\b(?:chr)?(?P<chrom>[0-9]{1,2}|X|Y|M|MT):(?P<start>[0-9,]+)-(?P<end>[0-9,]+)\b",
    re.IGNORECASE,
)
LOCUS_RE = re.compile(r"\b(?:chr)?(?P<chrom>[0-9]{1,2}|X|Y|M|MT):(?P<pos>[0-9,]+)\b", re.IGNORECASE)


def _resolve_targets(
    *,
    query: str | None,
    rsid: str | None,
    chrom: str | None,
    pos: int | str | None,
    ref: str | None,
    alt: str | None,
    region: str | None,
    genome_build: str,
    warnings: list[str],
) -> list[JsonObject]:
    targets: list[JsonObject] = []
    if rsid:
        targets.append({"target_type": "rsid", "rsid": _normalize_rsid(rsid), "resolution_status": "identifier"})

    parsed_pos = _int_or_none(pos)
    cleaned_chrom = _clean_chrom(chrom) if chrom else None
    cleaned_ref = _clean_allele(ref) if ref else None
    cleaned_alt = _clean_allele(alt) if alt else None
    if cleaned_chrom and parsed_pos and cleaned_ref and cleaned_alt:
        targets.append(_allele_target(cleaned_chrom, parsed_pos, cleaned_ref, cleaned_alt, genome_build, source="parameters"))
    elif cleaned_chrom and parsed_pos:
        targets.append(_locus_target(cleaned_chrom, parsed_pos, genome_build, source="parameters"))

    if region:
        try:
            reg_chrom, start, end = parse_region(region)
        except ValueError as exc:
            warnings.append(f"Could not parse region {region!r}: {exc}")
        else:
            targets.append(_region_target(_clean_chrom(reg_chrom), start, end, genome_build, source="parameters"))

    if query:
        for match in RSID_RE.finditer(query):
            targets.append({"target_type": "rsid", "rsid": _normalize_rsid(match.group(0)), "resolution_status": "identifier"})
        for pattern in (EXACT_COLON_RE, EXACT_ARROW_RE):
            for match in pattern.finditer(query):
                targets.append(
                    _allele_target(
                        _clean_chrom(match.group("chrom")),
                        int(match.group("pos").replace(",", "")),
                        _clean_allele(match.group("ref")),
                        _clean_allele(match.group("alt")),
                        genome_build,
                        source="query_text",
                    )
                )
        for match in REGION_RE.finditer(query):
            start = int(match.group("start").replace(",", ""))
            end = int(match.group("end").replace(",", ""))
            if end >= start:
                targets.append(
                    _region_target(
                        _clean_chrom(match.group("chrom")),
                        start,
                        end,
                        genome_build,
                        source="query_text",
                    )
                )
        for match in LOCUS_RE.finditer(query):
            if _overlaps_exact_or_region_match(query, match):
                continue
            targets.append(
                _locus_target(
                    _clean_chrom(match.group("chrom")),
                    int(match.group("pos").replace(",", "")),
                    genome_build,
                    source="query_text",
                )
            )

    targets = _dedupe_targets(targets)
    if not targets:
        warnings.append("No rsID, exact allele, locus, or region target was resolved from the input.")
    return targets


def _overlaps_exact_or_region_match(query: str, locus_match: re.Match[str]) -> bool:
    span = locus_match.span()
    for pattern in (EXACT_COLON_RE, EXACT_ARROW_RE, REGION_RE):
        for exact_match in pattern.finditer(query):
            exact_span = exact_match.span()
            if span[0] >= exact_span[0] and span[1] <= exact_span[1]:
                return True
    return False


def _inferred_allele_targets(public_context: JsonObject, *, genome_build: str) -> list[JsonObject]:
    targets: list[JsonObject] = []
    for row in public_context.get("clinvar_by_rsid", []):
        if row.get("chrom") and row.get("pos") and row.get("ref") and row.get("alt"):
            target = _allele_target(
                _clean_chrom(row["chrom"]),
                int(row["pos"]),
                _clean_allele(row["ref"]),
                _clean_allele(row["alt"]),
                str(row.get("genome_build") or genome_build),
                source="clinvar_rsid",
            )
            target["inferred_from"] = {"rsid": row.get("rsid"), "source": "clinvar_variant_rsids"}
            targets.append(target)
    return targets


def _allele_target(chrom: str, pos: int, ref: str, alt: str, genome_build: str, *, source: str) -> JsonObject:
    return {
        "target_type": "allele",
        "chrom": chrom,
        "pos": pos,
        "ref": ref,
        "alt": alt,
        "genome_build": genome_build,
        "resolution_status": "complete_allele",
        "source": source,
    }


def _locus_target(chrom: str, pos: int, genome_build: str, *, source: str) -> JsonObject:
    return {
        "target_type": "locus",
        "chrom": chrom,
        "pos": pos,
        "genome_build": genome_build,
        "resolution_status": "locus_only",
        "source": source,
    }


def _region_target(chrom: str, start: int, end: int, genome_build: str, *, source: str) -> JsonObject:
    return {
        "target_type": "region",
        "chrom": chrom,
        "start": start,
        "end": end,
        "genome_build": genome_build,
        "resolution_status": "region",
        "source": source,
    }


def _target_key(target: JsonObject) -> str:
    target_type = str(target.get("target_type"))
    if target_type == "rsid":
        return f"rsid:{target.get('rsid')}"
    if target_type == "allele":
        return f"allele:{target.get('genome_build')}:{target.get('chrom')}-{target.get('pos')}-{target.get('ref')}-{target.get('alt')}"
    if target_type == "locus":
        return f"locus:{target.get('genome_build')}:{target.get('chrom')}:{target.get('pos')}"
    if target_type == "region":
        return f"region:{target.get('genome_build')}:{target.get('chrom')}:{target.get('start')}-{target.get('end')}"
    return json.dumps(target, sort_keys=True)


def _dedupe_targets(targets: list[JsonObject]) -> list[JsonObject]:
    seen: set[str] = set()
    deduped: list[JsonObject] = []
    for target in targets:
        key = _target_key(target)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(target)
    return deduped


def _dedupe_records(records: list[JsonObject], keys: tuple[str, ...]) -> list[JsonObject]:
    seen: set[str] = set()
    deduped: list[JsonObject] = []
    for record in records:
        key_parts: list[str] = []
        for key in keys:
            value = record.get(key)
            if isinstance(value, dict):
                value = json.dumps(value, sort_keys=True)
            key_parts.append(str(value))
        composite = "\x1f".join(key_parts)
        if composite in seen:
            continue
        seen.add(composite)
        deduped.append(record)
    return deduped


def _dedupe_scalar(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _normalize_rsid(value: str | None) -> str | None:
    if value is None:
        return None
    match = RSID_RE.search(str(value))
    if not match:
        return str(value).strip()
    return match.group(0).lower()


def _clean_chrom(value: Any) -> str:
    text = str(value).strip()
    if text.lower().startswith("chr"):
        text = text[3:]
    return text.upper() if text.upper() in {"X", "Y", "M", "MT"} else text


def _chrom_aliases(chrom: str) -> list[str]:
    cleaned = _clean_chrom(chrom)
    aliases = [cleaned]
    chr_alias = "chr" + cleaned
    if chr_alias not in aliases:
        aliases.append(chr_alias)
    if cleaned == "MT":
        aliases.extend(["M", "chrM"])
    elif cleaned == "M":
        aliases.extend(["MT", "chrMT"])
    return list(dict.fromkeys(aliases))


def _clean_allele(value: Any) -> str:
    return str(value).strip().upper()


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _effective_genome_build(genome_build: str | None) -> str:
    value = str(genome_build or "").strip()
    if value and value.lower() != "auto":
        return value
    active = runtime_context.active_run()
    active_build = str(active.get("genome_build") or "").strip() if active else ""
    if active_build and active_build.lower() != "auto":
        return active_build
    return "GRCh38"
