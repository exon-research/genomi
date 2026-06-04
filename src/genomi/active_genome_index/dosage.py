from __future__ import annotations

import json
import sqlite3
from typing import Any

from .array_genotypes import count_array_allele, is_array_genotype_record
from .record_kinds import RECORD_KIND_ARRAY_NO_CALL, RECORD_KIND_NO_CALL, RECORD_KIND_REFERENCE_BLOCK

JsonObject = dict[str, Any]

_MINIMAL_COLUMNS = (
    "r.chrom, r.pos, r.end, r.ref, r.alt, r.filter, r.format, r.genotype, "
    "r.record_kind, r.observed_alleles, r.offset, r.sample_index, r.chrom_sort"
)


def dosage_for_variants(
    connection: sqlite3.Connection,
    variants: list[JsonObject],
    *,
    skip_ambiguous_palindromic: bool = True,
) -> list[JsonObject]:
    results: list[JsonObject | None] = [None] * len(variants)
    candidates_per_variant: list[list[str]] = []
    sites: list[tuple[str, int]] = []
    sites_seen: set[tuple[str, int]] = set()

    for i, variant in enumerate(variants):
        if skip_ambiguous_palindromic and variant.get("palindromic") and not variant.get("harmonized"):
            results[i] = _excluded(variant, "ambiguous_palindromic_unharmonized")
            candidates_per_variant.append([])
            continue
        candidates = _chrom_candidates(str(variant["chrom"]))
        candidates_per_variant.append(candidates)
        pos = int(variant["pos"])
        for candidate in candidates:
            key = (candidate, pos)
            if key in sites_seen:
                continue
            sites_seen.add(key)
            sites.append(key)

    if not sites:
        for i, variant in enumerate(variants):
            if results[i] is None:
                results[i] = _missing(variant, "no_record_at_locus")
        return [item for item in results if item is not None]

    records_by_key = _bulk_fetch_records(connection, sites)

    for i, variant in enumerate(variants):
        if results[i] is not None:
            continue
        pos = int(variant["pos"])
        seen_records: set[tuple[int, int]] = set()
        candidate_records: list[JsonObject] = []
        for candidate in candidates_per_variant[i]:
            for record in records_by_key.get((candidate, pos), ()):
                dedupe = (int(record["offset"]), int(record["sample_index"]))
                if dedupe in seen_records:
                    continue
                seen_records.add(dedupe)
                candidate_records.append(record)
        if not candidate_records:
            results[i] = _missing(variant, "no_record_at_locus")
            continue
        match: JsonObject | None = None
        exclusion: JsonObject | None = None
        first_missing: JsonObject | None = None
        for record in candidate_records:
            resolved = _dosage_from_record(record, variant)
            if resolved["status"] == "matched":
                match = resolved
                break
            if exclusion is None and resolved["status"] == "excluded":
                exclusion = resolved
            elif first_missing is None and resolved["status"] == "missing":
                first_missing = resolved
        if match is not None:
            results[i] = match
        elif exclusion is not None:
            results[i] = exclusion
        elif first_missing is not None:
            results[i] = first_missing
        else:
            results[i] = _missing(variant, "alleles_not_observed_at_locus")

    return [item for item in results if item is not None]


def dosage_for_variant(
    connection: sqlite3.Connection,
    variant: JsonObject,
    *,
    skip_ambiguous_palindromic: bool = True,
) -> JsonObject:
    return dosage_for_variants(
        connection,
        [variant],
        skip_ambiguous_palindromic=skip_ambiguous_palindromic,
    )[0]


def _bulk_fetch_records(
    connection: sqlite3.Connection,
    sites: list[tuple[str, int]],
) -> dict[tuple[str, int], list[JsonObject]]:
    connection.execute("drop table if exists _agi_dosage_sites")
    connection.execute("create temp table _agi_dosage_sites (chrom text not null, pos integer not null)")
    try:
        connection.executemany("insert into _agi_dosage_sites(chrom, pos) values (?, ?)", sites)
        connection.execute("create index _agi_dosage_sites_idx on _agi_dosage_sites(chrom, pos)")

        records_by_key: dict[tuple[str, int], list[JsonObject]] = {}
        seen_keys: set[tuple[str, int, int, int]] = set()

        point_rows = connection.execute(
            f"""
            select {_MINIMAL_COLUMNS}
            from _agi_dosage_sites s
            inner join records r on r.chrom = s.chrom and r.pos = s.pos
            order by r.chrom_sort, r.pos, r.offset, r.sample_index
            """
        ).fetchall()
        for row in point_rows:
            chrom = str(row["chrom"])
            pos = int(row["pos"])
            offset = int(row["offset"])
            sample_index = int(row["sample_index"] or 0)
            dedupe_key = (chrom, pos, offset, sample_index)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            records_by_key.setdefault((chrom, pos), []).append(_row_to_record_dict(row))

        span_rows = connection.execute(
            f"""
            select s.chrom as query_chrom, s.pos as query_pos, {_MINIMAL_COLUMNS}
            from _agi_dosage_sites s
            inner join spans sp on sp.chrom = s.chrom and sp.pos < s.pos and sp.end >= s.pos
            inner join records r on r.offset = sp.offset and r.sample_index = sp.sample_index
            order by sp.pos desc
            """
        ).fetchall()
        for row in span_rows:
            query_chrom = str(row["query_chrom"])
            query_pos = int(row["query_pos"])
            offset = int(row["offset"])
            sample_index = int(row["sample_index"] or 0)
            dedupe_key = (query_chrom, query_pos, offset, sample_index)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            records_by_key.setdefault((query_chrom, query_pos), []).append(_row_to_record_dict(row))

        return records_by_key
    finally:
        connection.execute("drop table if exists _agi_dosage_sites")


def _row_to_record_dict(row: sqlite3.Row) -> JsonObject:
    alt = "" if row["alt"] == "." else str(row["alt"] or "")
    return {
        "chrom": row["chrom"],
        "pos": int(row["pos"]),
        "end": int(row["end"]),
        "ref": row["ref"],
        "alt": alt,
        "alts": [value for value in alt.split(",") if value],
        "filter": row["filter"],
        "format": row["format"],
        "genotype": row["genotype"],
        "record_kind": row["record_kind"],
        "observed_alleles": _json_list(row["observed_alleles"]),
        "offset": int(row["offset"]),
        "sample_index": int(row["sample_index"] or 0),
    }


def _dosage_from_record(record: JsonObject, variant: JsonObject) -> JsonObject:
    genotype = str(record.get("genotype") or "")
    if is_array_genotype_record(record):
        if record.get("record_kind") == RECORD_KIND_ARRAY_NO_CALL:
            return _missing(variant, "no_call", record=record)
        if str(record.get("filter") or "") not in {"PASS", "."}:
            return _excluded(variant, "filter_fail", record=record)
        effect = str(variant["effect_allele"]).upper()
        other = str(variant.get("other_allele") or "").upper()
        allowed = [effect, other] if other else None
        array_dosage = count_array_allele(record, target_allele=effect, allowed_alleles=allowed)
        if array_dosage["status"] != "matched":
            reason = str(array_dosage.get("reason") or "unparseable_genotype")
            if reason == "array_genotype_allele_outside_allowed_alleles":
                reason = "genotype_allele_outside_score_alleles"
            elif reason == "array_allele_model_not_single_base":
                reason = "score_allele_model_not_supported_by_array_genotype"
            elif reason == "array_target_allele_not_single_base":
                reason = "effect_allele_not_supported_by_array_genotype"
            elif reason == "missing_genotype":
                reason = "no_call"
            return _missing(variant, reason, record=record)
        return _matched(
            variant,
            effect_allele_dosage=float(array_dosage["dosage"]),
            ploidy=int(array_dosage["ploidy"]),
            record=record,
            match_type="consumer_array_letter_count",
        )
    if str(record.get("filter") or "") not in {"PASS", "."}:
        return _excluded(variant, "filter_fail", record=record)
    if record.get("record_kind") == RECORD_KIND_NO_CALL:
        return _missing(variant, "no_call", record=record)
    if not genotype or "." in genotype:
        return _missing(variant, "missing_genotype", record=record)
    effect = str(variant["effect_allele"]).upper()
    other = str(variant.get("other_allele") or "").upper()
    ref = str(record.get("ref") or "").upper()
    alts = [str(value).upper() for value in record.get("alts") or []]
    genotype_tokens = genotype.replace("|", "/").split("/")
    allele_bases: list[str] = []
    for token in genotype_tokens:
        if token == "0":
            allele_bases.append(ref)
            continue
        try:
            allele_bases.append(alts[int(token) - 1])
        except (IndexError, ValueError):
            return _missing(variant, "unparseable_genotype", record=record)
    if not allele_bases:
        return _missing(variant, "empty_genotype", record=record)
    if _is_homozygous_reference_block(record, genotype_tokens):
        if effect == ref:
            return _matched(
                variant,
                effect_allele_dosage=float(len(allele_bases)),
                ploidy=len(allele_bases),
                record=record,
                match_type="reference_homozygous_inferred",
            )
        if other == ref:
            return _matched(
                variant,
                effect_allele_dosage=0.0,
                ploidy=len(allele_bases),
                record=record,
                match_type="reference_homozygous_inferred",
            )
    effect_in_record = effect in {ref, *alts}
    other_in_record = other and other in {ref, *alts}
    if other:
        if not other_in_record:
            return _missing(variant, "other_allele_not_in_record", record=record)
        score_alleles = {effect, other}
        if any(allele not in score_alleles for allele in allele_bases):
            return _missing(variant, "genotype_allele_outside_score_alleles", record=record)
    elif not effect_in_record:
        return _missing(variant, "effect_allele_not_in_record", record=record)
    dosage = float(sum(1 for allele in allele_bases if allele == effect))
    match_type = "direct_allele_count" if effect_in_record else "reference_homozygous_inferred"
    return _matched(
        variant,
        effect_allele_dosage=dosage,
        ploidy=len(allele_bases),
        record=record,
        match_type=match_type,
    )


def _matched(
    variant: JsonObject,
    *,
    effect_allele_dosage: float,
    ploidy: int,
    record: JsonObject,
    match_type: str,
) -> JsonObject:
    return {
        "status": "matched",
        "variant_index": variant["variant_index"],
        "variant_id": variant.get("variant_id"),
        "rsid": variant.get("rsid"),
        "chrom": variant["chrom"],
        "pos": variant["pos"],
        "effect_allele": str(variant["effect_allele"]).upper(),
        "other_allele": str(variant.get("other_allele") or "").upper() or None,
        "effect_weight": float(variant["effect_weight"]),
        "effect_allele_dosage": effect_allele_dosage,
        "ploidy": ploidy,
        "contribution": effect_allele_dosage * float(variant["effect_weight"]),
        "record": {
            "chrom": record.get("chrom"),
            "pos": record.get("pos"),
            "ref": record.get("ref"),
            "alt": record.get("alt"),
            "genotype": record.get("genotype"),
            "record_kind": record.get("record_kind"),
            "observed_alleles": record.get("observed_alleles"),
        },
        "match_type": match_type,
    }


def _chrom_candidates(chrom: str) -> list[str]:
    if chrom.startswith("chr"):
        return [chrom, chrom[3:]]
    return [chrom, f"chr{chrom}"]


def _is_homozygous_reference_block(record: JsonObject, genotype_tokens: list[str]) -> bool:
    if record.get("record_kind") != RECORD_KIND_REFERENCE_BLOCK:
        return False
    return all(token == "0" for token in genotype_tokens)


def _missing(variant: JsonObject, reason: str, *, record: JsonObject | None = None) -> JsonObject:
    return _nonmatch("missing", variant, reason, record=record)


def _excluded(variant: JsonObject, reason: str, *, record: JsonObject | None = None) -> JsonObject:
    return _nonmatch("excluded", variant, reason, record=record)


def _nonmatch(status: str, variant: JsonObject, reason: str, *, record: JsonObject | None = None) -> JsonObject:
    payload: JsonObject = {
        "status": status,
        "reason": reason,
        "variant_index": variant["variant_index"],
        "variant_id": variant.get("variant_id"),
        "rsid": variant.get("rsid"),
        "chrom": variant["chrom"],
        "pos": variant["pos"],
        "effect_allele": variant["effect_allele"],
        "other_allele": variant.get("other_allele"),
        "effect_weight": float(variant["effect_weight"]),
    }
    if record:
        payload["record"] = {
            "chrom": record.get("chrom"),
            "pos": record.get("pos"),
            "ref": record.get("ref"),
            "alt": record.get("alt"),
            "genotype": record.get("genotype"),
            "record_kind": record.get("record_kind"),
            "observed_alleles": record.get("observed_alleles"),
        }
    return payload


def _json_list(value: Any) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
