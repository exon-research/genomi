from __future__ import annotations

import sqlite3
from typing import Any

from ...runtime.liftover import LiftoverConfigurationError, get_liftover

JsonObject = dict[str, Any]


def lift_score_variants(
    variants: list[JsonObject],
    *,
    source_build: str,
    target_build: str,
) -> dict[str, Any]:
    """Translate PGS-style score variants between genome builds.

    Lift each variant's (chrom, pos) using ``genomi.runtime.liftover``.
    Variants whose auto-generated ``variant_id`` was built from
    ``"<chrom>:<pos>:<effect>:<other>"`` are regenerated on the new
    coordinates so downstream logs/audits stay consistent. Records that
    fail to lift (chain gap, strand flip, missing coordinates) are
    returned in ``dropped`` with the reason recorded; this keeps the
    overall variant-accounting story honest without crashing the score.
    """

    try:
        lifter = get_liftover(source_build, target_build)
    except LiftoverConfigurationError:
        raise
    lifted: list[JsonObject] = []
    dropped: list[JsonObject] = []
    for variant in variants:
        chrom = variant.get("chrom")
        pos = variant.get("pos")
        if chrom is None or pos is None:
            dropped.append({**dict(variant), "liftover_reason": "missing_coordinates"})
            continue
        try:
            pos_int = int(pos)
        except (TypeError, ValueError):
            dropped.append({**dict(variant), "liftover_reason": "invalid_position"})
            continue
        result = lifter.lift_position_full(str(chrom), pos_int)
        if result is None:
            dropped.append({**dict(variant), "liftover_reason": "unmapped"})
            continue
        target_chrom, target_pos, strand = result
        if strand != "+":
            dropped.append({**dict(variant), "liftover_reason": "strand_flipped"})
            continue
        new_variant = dict(variant)
        new_variant["chrom"] = target_chrom
        new_variant["pos"] = target_pos
        old_auto_id = f"{chrom}:{pos_int}:{variant.get('effect_allele')}:{variant.get('other_allele') or ''}"
        if variant.get("variant_id") == old_auto_id:
            new_variant["variant_id"] = (
                f"{target_chrom}:{target_pos}:"
                f"{variant.get('effect_allele')}:{variant.get('other_allele') or ''}"
            )
        lifted.append(new_variant)
    return {
        "lifted": lifted,
        "dropped": dropped,
        "source_build": source_build,
        "target_build": target_build,
    }

# Bulk-fetch path used by the PRS scorer. The original implementation issued
# two SQLite queries per score variant (~1.2M round-trips for a 600K-variant
# score); these are replaced with two temp-table joins.

_MINIMAL_COLUMNS = "r.chrom, r.pos, r.end, r.ref, r.alt, r.filter, r.genotype, r.offset, r.sample_index, r.chrom_sort"


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
    connection.execute("drop table if exists _prs_sites")
    connection.execute("create temp table _prs_sites (chrom text not null, pos integer not null)")
    try:
        connection.executemany("insert into _prs_sites(chrom, pos) values (?, ?)", sites)
        connection.execute("create index _prs_sites_idx on _prs_sites(chrom, pos)")

        records_by_key: dict[tuple[str, int], list[JsonObject]] = {}
        seen_keys: set[tuple[str, int, int, int]] = set()

        point_rows = connection.execute(
            f"""
            select {_MINIMAL_COLUMNS}
            from _prs_sites s
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
            from _prs_sites s
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
        connection.execute("drop table if exists _prs_sites")


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
        "genotype": row["genotype"],
        "offset": int(row["offset"]),
        "sample_index": int(row["sample_index"] or 0),
    }


def _dosage_from_record(record: JsonObject, variant: JsonObject) -> JsonObject:
    if str(record.get("filter") or "") not in {"PASS", "."}:
        return _excluded(variant, "filter_fail", record=record)
    genotype = str(record.get("genotype") or "")
    if not genotype or "." in genotype:
        return _missing(variant, "missing_genotype", record=record)
    ref = str(record.get("ref") or "").upper()
    alts = [str(value).upper() for value in record.get("alts") or []]
    effect = str(variant["effect_allele"]).upper()
    other = str(variant.get("other_allele") or "").upper()
    allele_bases: list[str] = []
    for token in genotype.replace("|", "/").split("/"):
        if token == "0":
            allele_bases.append(ref)
            continue
        try:
            allele_bases.append(alts[int(token) - 1])
        except (IndexError, ValueError):
            return _missing(variant, "unparseable_genotype", record=record)
    if not allele_bases:
        return _missing(variant, "empty_genotype", record=record)
    # Locus must be anchored to the score variant. If the score file provides
    # other_allele (typically the REF after PGS Catalog harmonization), match
    # via that allele only when the observed genotype stays inside the score
    # variant's allele model. A reference-block record (alt=".") can then
    # correctly yield dosage=0, while a third allele at the same locus does not
    # get misread as reference homozygous for the score variant.
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
    return {
        "status": "matched",
        "variant_index": variant["variant_index"],
        "variant_id": variant.get("variant_id"),
        "rsid": variant.get("rsid"),
        "chrom": variant["chrom"],
        "pos": variant["pos"],
        "effect_allele": effect,
        "other_allele": other or None,
        "effect_weight": float(variant["effect_weight"]),
        "effect_allele_dosage": dosage,
        "ploidy": len(allele_bases),
        "contribution": dosage * float(variant["effect_weight"]),
        "record": {
            "chrom": record.get("chrom"),
            "pos": record.get("pos"),
            "ref": record.get("ref"),
            "alt": record.get("alt"),
            "genotype": genotype,
        },
        "match_type": match_type,
    }


def _chrom_candidates(chrom: str) -> list[str]:
    if chrom.startswith("chr"):
        return [chrom, chrom[3:]]
    return [chrom, f"chr{chrom}"]


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
        }
    return payload
