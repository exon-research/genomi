from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any
from ...active_genome_index.vcf import parse_info, parse_sample
from ...runtime.external import file_metadata, matching_manifest, utc_now

from .constants import (
    DEFAULT_POPULATION_LABEL,
    EVIDENCE_SCHEMA_VERSION,
    GNOMAD_API_URL,
    GNOMAD_VARIANT_QUERY,
)
from .helpers import (
    _gnomad_metadata_key,
    _gnomad_source_label,
    _gnomad_source_labels,
    _iter_vcf_records,
    _optional_float_info,
    _optional_float_value,
    _optional_int_info,
    _optional_int_value,
    _population_metadata_key,
    _post_graphql,
    read_vcf_header_metadata,
)
from .connection import (
    _ensure_schema,
    _insert_population_batch,
    _read_metadata,
    _upsert_metadata,
    connect_evidence,
)



def import_population_vcf(
    population_vcf: str | Path,
    evidence_db: str | Path,
    *,
    source: str,
    genome_build: str = "GRCh38",
    source_version: str | None = None,
    population: str = DEFAULT_POPULATION_LABEL,
    af_field: str = "AF",
    ac_field: str = "AC",
    an_field: str = "AN",
    hom_field: str = "nhomalt",
    max_records: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    population_vcf = Path(population_vcf)
    evidence_db = Path(evidence_db)
    if not population_vcf.exists():
        raise FileNotFoundError(population_vcf)
    evidence_db.parent.mkdir(parents=True, exist_ok=True)
    if not source.strip():
        raise ValueError("source is required")
    if not population.strip():
        raise ValueError("population is required")

    source = source.strip()
    population = population.strip()
    imported_at = utc_now()
    header_metadata = read_vcf_header_metadata(population_vcf)
    effective_source_version = source_version or header_metadata.get("fileDate") or header_metadata.get("source")
    metadata_key = _population_metadata_key(source, genome_build, population)
    cache_expected = {
        "source_file": file_metadata(population_vcf),
        "source": source,
        "source_version": effective_source_version,
        "genome_build": genome_build,
        "population": population,
        "af_field": af_field,
        "ac_field": ac_field,
        "an_field": an_field,
        "hom_field": hom_field,
        "max_records": max_records,
    }

    scanned = 0
    inserted = 0
    with connect_evidence(evidence_db, attach_shared=False) as connection:
        _ensure_schema(connection)
        existing_rows = int(
            connection.execute(
                """
                select count(*) as records
                from population_frequencies
                where source = ? and genome_build = ? and population = ?
                """,
                (source, genome_build, population),
            ).fetchone()["records"]
        )
        metadata = _read_metadata(connection)
        if not force and existing_rows and metadata.get(metadata_key) == cache_expected:
            return {
                "status": "cached",
                "evidence_db": str(evidence_db),
                "source": source,
                "source_version": effective_source_version,
                "genome_build": genome_build,
                "population": population,
                "scanned_records": existing_rows,
                "inserted_alleles": existing_rows,
            }
        if not force and existing_rows:
            raise RuntimeError(
                "evidence DB already contains population rows for this source/build/population with different "
                "source/options; use --force to rebuild"
            )
        if force:
            connection.execute(
                """
                delete from main.population_frequencies
                where source = ? and genome_build = ? and population = ?
                """,
                (source, genome_build, population),
            )
            connection.execute("delete from main.metadata where key = ?", (metadata_key,))

        _upsert_metadata(connection, "schema_version", EVIDENCE_SCHEMA_VERSION)
        _upsert_metadata(connection, metadata_key, cache_expected)

        batch: list[tuple[Any, ...]] = []
        for record in _iter_vcf_records(population_vcf):
            scanned += 1
            info = parse_info(record["info"])
            alts = [alt for alt in record["alt"].split(",") if alt not in ("", ".")]
            for alt_index, alt in enumerate(alts):
                batch.append(
                    (
                        record["chrom"],
                        int(record["pos"]),
                        record["ref"],
                        alt,
                        genome_build,
                        source,
                        effective_source_version,
                        population,
                        _optional_int_info(info, ac_field, alt_index),
                        _optional_int_info(info, an_field, alt_index, prefer_scalar=True),
                        _optional_float_info(info, af_field, alt_index),
                        _optional_int_info(info, hom_field, alt_index),
                        json.dumps(info, sort_keys=True),
                        str(population_vcf),
                        imported_at,
                    )
                )
                inserted += 1
            if len(batch) >= 10_000:
                _insert_population_batch(connection, batch)
                connection.commit()
                batch.clear()
            if max_records is not None and scanned >= max_records:
                break
        if batch:
            _insert_population_batch(connection, batch)
        connection.commit()

    return {
        "status": "completed",
        "evidence_db": str(evidence_db),
        "source": source,
        "source_version": effective_source_version,
        "genome_build": genome_build,
        "population": population,
        "scanned_records": scanned,
        "inserted_alleles": inserted,
    }


def query_population_frequency(
    evidence_db: str | Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    genome_build: str = "GRCh38",
    source: str | None = None,
    population: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    clauses = ["chrom = ?", "pos = ?", "ref = ?", "alt = ?", "genome_build = ?"]
    params: list[Any] = [chrom, pos, ref, alt, genome_build]
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if population is not None:
        clauses.append("population = ?")
        params.append(population)
    params.append(limit)

    with connect_evidence(evidence_db) as connection:
        _ensure_schema(connection)
        rows = [
            dict(row)
            for row in connection.execute(
                f"""
                select chrom, pos, ref, alt, genome_build, source, source_version,
                       population, allele_count, allele_number, allele_frequency,
                       homozygote_count, source_path, imported_at
                from population_frequencies
                where {' and '.join(clauses)}
                order by
                  source,
                  case when population = 'global' then 0 else 1 end,
                  population
                limit ?
                """,
                params,
            )
        ]
    return {
        "query": {
            "source": "population_frequency",
            "chrom": chrom,
            "pos": pos,
            "ref": ref,
            "alt": alt,
            "genome_build": genome_build,
            "population_source": source,
            "population": population,
        },
        "count": len(rows),
        "records": rows,
    }


def summarize_population_frequency(population_frequency: dict[str, Any]) -> dict[str, Any]:
    records = population_frequency.get("records") or []
    global_rows = [
        _compact_population_record(record)
        for record in records
        if record.get("population") == DEFAULT_POPULATION_LABEL
    ]
    max_af_record = max(
        (record for record in records if record.get("allele_frequency") is not None),
        key=lambda record: float(record["allele_frequency"]),
        default=None,
    )
    homozygote_rows = [
        _compact_population_record(record)
        for record in records
        if (record.get("homozygote_count") or 0) > 0
    ]
    source_counts: Counter[str] = Counter(record.get("source") or "missing" for record in records)
    return {
        "record_count": len(records),
        "global_rows": global_rows,
        "max_allele_frequency_record": _compact_population_record(max_af_record) if max_af_record else None,
        "homozygote_rows": homozygote_rows[:20],
        "homozygote_row_count": len(homozygote_rows),
        "source_counts": source_counts.most_common(),
        "freshness": _population_freshness_summary(records),
    }


def _compact_population_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": record.get("source"),
        "source_version": record.get("source_version"),
        "population": record.get("population"),
        "allele_frequency": record.get("allele_frequency"),
        "allele_count": record.get("allele_count"),
        "allele_number": record.get("allele_number"),
        "homozygote_count": record.get("homozygote_count"),
    }


def _population_freshness_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "status": "not_available",
            "latest_upstream_checked": False,
            "note": "No public population-frequency evidence rows are available for this exact allele.",
        }
    source_snapshots = sorted(
        {
            (
                record.get("source"),
                record.get("source_version"),
                record.get("source_path"),
            )
            for record in records
        },
        key=lambda item: tuple("" if value is None else str(value) for value in item),
    )
    imported_at_values = sorted(
        {
            record.get("imported_at")
            for record in records
            if record.get("imported_at")
        }
    )
    return {
        "status": "available",
        "latest_upstream_checked": False,
        "latest_source_imported_at": imported_at_values[-1] if imported_at_values else None,
        "source_versions": [
            {
                "source": source,
                "source_version": source_version,
                "source_path": source_path,
            }
            for source, source_version, source_path in source_snapshots
        ],
        "note": (
            "Public population-frequency evidence is available for this exact allele. "
            "Use source dates when the user asks for latest evidence."
        ),
    }


def fetch_gnomad_variant(
    evidence_db: str | Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    dataset: str = "gnomad_r4",
    genome_build: str = "GRCh38",
    api_url: str = GNOMAD_API_URL,
    force: bool = False,
) -> dict[str, Any]:
    evidence_db = Path(evidence_db)
    variant_id = f"{chrom}-{pos}-{ref}-{alt}"
    metadata_key = _gnomad_metadata_key(dataset, genome_build, variant_id)
    source_labels = _gnomad_source_labels(dataset)
    cached_inserted_rows: int | None = None

    with connect_evidence(evidence_db, attach_shared=False) as connection:
        _ensure_schema(connection)
        metadata = _read_metadata(connection)
        existing_rows = _count_population_rows_for_sources(
            connection,
            chrom,
            pos,
            ref,
            alt,
            genome_build,
            source_labels,
        )
        if not force and metadata.get(metadata_key) is not None:
            cached_inserted_rows = existing_rows
            cached_found = metadata.get(metadata_key, {}).get("found")
        elif not force and existing_rows:
            raise RuntimeError(
                "evidence DB already contains gnomAD rows for this variant/dataset without matching cache metadata; "
                "use --force to rebuild"
            )
        if force:
            _delete_population_rows_for_sources(connection, chrom, pos, ref, alt, genome_build, source_labels)
            connection.execute("delete from main.metadata where key = ?", (metadata_key,))
            connection.commit()
    if cached_inserted_rows is not None:
        return {
            "status": "cached",
            "evidence_db": str(evidence_db),
            "variant_id": variant_id,
            "dataset": dataset,
            "genome_build": genome_build,
            "inserted_rows": cached_inserted_rows,
            "found": cached_found,
            "population_frequency": query_population_frequency(
                evidence_db,
                chrom,
                pos,
                ref,
                alt,
                genome_build=genome_build,
                limit=500,
            ),
        }

    # Resolve through the package so test patches of
    # `genomi.evidence._post_graphql` (forwarded onto the store package) apply.
    from . import _post_graphql as _post_graphql_current

    response = _post_graphql_current(
        api_url,
        {
            "query": GNOMAD_VARIANT_QUERY,
            "variables": {
                "variantId": variant_id,
                "dataset": dataset,
            },
        },
    )
    if response.get("errors"):
        raise RuntimeError(f"gnomAD API returned errors: {response['errors']}")

    variant = (response.get("data") or {}).get("variant")
    imported_at = utc_now()
    batch = _gnomad_population_batch(
        variant,
        dataset=dataset,
        genome_build=genome_build,
        api_url=api_url,
        imported_at=imported_at,
    )
    metadata_payload = {
        "api_url": api_url,
        "dataset": dataset,
        "genome_build": genome_build,
        "variant_id": variant_id,
        "fetched_at_utc": imported_at,
        "found": variant is not None,
        "inserted_rows": len(batch),
    }

    with connect_evidence(evidence_db, attach_shared=False) as connection:
        _ensure_schema(connection)
        _delete_population_rows_for_sources(connection, chrom, pos, ref, alt, genome_build, source_labels)
        if batch:
            _insert_population_batch(connection, batch)
        _upsert_metadata(connection, "schema_version", EVIDENCE_SCHEMA_VERSION)
        _upsert_metadata(connection, metadata_key, metadata_payload)
        connection.commit()

    return {
        "status": "completed",
        "evidence_db": str(evidence_db),
        "variant_id": variant_id,
        "dataset": dataset,
        "genome_build": genome_build,
        "inserted_rows": len(batch),
        "found": variant is not None,
        "population_frequency": query_population_frequency(
            evidence_db,
            chrom,
            pos,
            ref,
            alt,
            genome_build=genome_build,
            limit=500,
        ),
    }


def _gnomad_population_batch(
    variant: dict[str, Any] | None,
    *,
    dataset: str,
    genome_build: str,
    api_url: str,
    imported_at: str,
) -> list[tuple[Any, ...]]:
    if variant is None:
        return []

    batch: list[tuple[Any, ...]] = []
    for sequencing_type in ("exome", "genome"):
        data = variant.get(sequencing_type)
        if data is None:
            continue
        source = _gnomad_source_label(dataset, sequencing_type)
        batch.append(
            _gnomad_population_row(
                variant,
                data,
                dataset=dataset,
                genome_build=genome_build,
                source=source,
                population=DEFAULT_POPULATION_LABEL,
                api_url=api_url,
                imported_at=imported_at,
            )
        )
        for population_data in data.get("populations") or []:
            batch.append(
                _gnomad_population_row(
                    variant,
                    population_data,
                    dataset=dataset,
                    genome_build=genome_build,
                    source=source,
                    population=population_data["id"],
                    api_url=api_url,
                    imported_at=imported_at,
                )
            )
    return batch


def _gnomad_population_row(
    variant: dict[str, Any],
    data: dict[str, Any],
    *,
    dataset: str,
    genome_build: str,
    source: str,
    population: str,
    api_url: str,
    imported_at: str,
) -> tuple[Any, ...]:
    ac = _optional_int_value(data.get("ac"))
    an = _optional_int_value(data.get("an"))
    af = _optional_float_value(data.get("af"))
    if af is None and ac is not None and an:
        af = ac / an
    return (
        variant["chrom"],
        int(variant["pos"]),
        variant["ref"],
        variant["alt"],
        genome_build,
        source,
        dataset,
        population,
        ac,
        an,
        af,
        _optional_int_value(data.get("homozygote_count")),
        json.dumps(
            {
                "api": "gnomad_browser_graphql",
                "dataset": dataset,
                "variant_id": variant.get("variant_id"),
                "rsids": variant.get("rsids") or [],
                "source": source,
                "population": population,
            },
            sort_keys=True,
        ),
        api_url,
        imported_at,
    )


def _count_population_rows_for_sources(
    connection: sqlite3.Connection,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    genome_build: str,
    sources: tuple[str, ...],
) -> int:
    placeholders = ", ".join("?" for _ in sources)
    return int(
        connection.execute(
            f"""
            select count(*) as records
            from population_frequencies
            where chrom = ? and pos = ? and ref = ? and alt = ? and genome_build = ?
              and source in ({placeholders})
            """,
            (chrom, pos, ref, alt, genome_build, *sources),
        ).fetchone()["records"]
    )


def _delete_population_rows_for_sources(
    connection: sqlite3.Connection,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    genome_build: str,
    sources: tuple[str, ...],
) -> None:
    placeholders = ", ".join("?" for _ in sources)
    connection.execute(
        f"""
        delete from main.population_frequencies
        where chrom = ? and pos = ? and ref = ? and alt = ? and genome_build = ?
          and source in ({placeholders})
        """,
        (chrom, pos, ref, alt, genome_build, *sources),
    )
