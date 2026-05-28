from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from ...active_genome_index.vcf import parse_info, parse_sample
from ...runtime.external import file_metadata, matching_manifest, utc_now

from .constants import (
    CLINVAR_RSID_INDEX_RULE_SET_VERSION,
    EVIDENCE_SCHEMA_VERSION,
)
from .helpers import (
    _clinvar_raw_info_rsids,
    _gene_symbols,
    _iter_vcf_records,
    _none_if_dot,
    _string_value,
    read_vcf_header_metadata,
)
from .connection import (
    _clinvar_import_cache,
    _ensure_schema,
    _insert_clinvar_batch,
    _insert_gene_index_batch,
    _insert_rsid_index_batch,
    _read_metadata,
    _upsert_metadata,
    connect_evidence,
)



def import_clinvar_vcf(
    clinvar_vcf: str | Path,
    evidence_db: str | Path,
    *,
    genome_build: str = "GRCh38",
    source_version: str | None = None,
    max_records: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    clinvar_vcf = Path(clinvar_vcf)
    evidence_db = Path(evidence_db)
    if not clinvar_vcf.exists():
        raise FileNotFoundError(clinvar_vcf)
    evidence_db.parent.mkdir(parents=True, exist_ok=True)

    imported_at = utc_now()
    header_metadata = read_vcf_header_metadata(clinvar_vcf)
    effective_source_version = source_version or header_metadata.get("fileDate") or header_metadata.get("source")
    inserted = 0
    scanned = 0
    with connect_evidence(evidence_db, attach_shared=False) as connection:
        _ensure_schema(connection)
        if not force:
            cached = _clinvar_import_cache(
                connection,
                evidence_db,
                clinvar_vcf,
                genome_build,
                effective_source_version,
                max_records,
            )
            if cached is not None:
                return cached
            existing_records = connection.execute("select count(*) as records from clinvar_variants").fetchone()["records"]
            if existing_records:
                raise RuntimeError(
                    "evidence DB already contains ClinVar rows from different source/options; use --force to rebuild"
                )
        else:
            connection.execute("delete from main.clinvar_variants")
            connection.execute("delete from main.clinvar_variant_genes")
            connection.execute("delete from main.metadata where key like 'clinvar_%'")

        _upsert_metadata(connection, "schema_version", EVIDENCE_SCHEMA_VERSION)
        _upsert_metadata(connection, "clinvar_source", file_metadata(clinvar_vcf))
        _upsert_metadata(connection, "clinvar_source_header", header_metadata)
        _upsert_metadata(connection, "clinvar_source_version", effective_source_version)
        _upsert_metadata(connection, "clinvar_genome_build", genome_build)
        _upsert_metadata(connection, "clinvar_max_records", max_records)

        # Drop indexes before bulk insert so SQLite doesn't maintain the B-tree
        # per row. They are rebuilt after all data is loaded, which is much faster.
        connection.execute("drop index if exists main.clinvar_variant_idx")
        connection.execute("drop index if exists main.clinvar_id_idx")
        # Commit metadata + index drops before setting pragmas — synchronous level
        # cannot be changed inside an open transaction.
        connection.commit()
        # Disable fsync and expand the page cache for the duration of the import.
        connection.execute("pragma synchronous = off")
        connection.execute("pragma cache_size = -131072")  # 128 MB
        connection.execute("pragma temp_store = memory")

        batch: list[tuple[Any, ...]] = []
        for record in _iter_vcf_records(clinvar_vcf):
            scanned += 1
            info = parse_info(record["info"])
            raw_info = json.dumps(info)
            chrom = record["chrom"]
            pos = int(record["pos"])
            ref = record["ref"]
            clinvar_id = _none_if_dot(record["id"])
            allele_id = _string_value(info.get("ALLELEID"))
            clnsig = _string_value(info.get("CLNSIG"))
            clnrevstat = _string_value(info.get("CLNREVSTAT"))
            clndn = _string_value(info.get("CLNDN"))
            geneinfo = _string_value(info.get("GENEINFO"))
            clnhgvs = _string_value(info.get("CLNHGVS"))
            for alt in record["alt"].split(","):
                batch.append(
                    (
                        chrom,
                        pos,
                        ref,
                        alt,
                        genome_build,
                        clinvar_id,
                        allele_id,
                        clnsig,
                        clnrevstat,
                        clndn,
                        geneinfo,
                        clnhgvs,
                        raw_info,
                        str(clinvar_vcf),
                        effective_source_version,
                        imported_at,
                    )
                )
                inserted += 1
            if len(batch) >= 100_000:
                _insert_clinvar_batch(connection, batch)
                batch.clear()
            if max_records is not None and scanned >= max_records:
                break
        if batch:
            _insert_clinvar_batch(connection, batch)
        connection.commit()

        # Rebuild indexes now that all rows are present — one B-tree sort pass
        # is far cheaper than per-row maintenance across 4M+ inserts.
        connection.execute(
            "create index if not exists clinvar_variant_idx"
            " on clinvar_variants(chrom, pos, ref, alt, genome_build)"
        )
        connection.execute(
            "create index if not exists clinvar_id_idx on clinvar_variants(clinvar_id)"
        )
        connection.execute("pragma synchronous = normal")
        connection.commit()

    return {
        "status": "completed",
        "evidence_db": str(evidence_db),
        "source": str(clinvar_vcf),
        "source_version": effective_source_version,
        "genome_build": genome_build,
        "scanned_records": scanned,
        "inserted_alleles": inserted,
    }


def build_clinvar_gene_index(
    evidence_db: str | Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    evidence_db = Path(evidence_db)
    if not evidence_db.exists():
        raise FileNotFoundError(evidence_db)

    with connect_evidence(evidence_db, attach_shared=False) as connection:
        _ensure_schema(connection)
        metadata = _read_metadata(connection)
        clinvar_records = int(connection.execute("select count(*) as records from clinvar_variants").fetchone()["records"])
        existing_gene_links = int(
            connection.execute("select count(*) as records from clinvar_variant_genes").fetchone()["records"]
        )
        expected_cache = {
            "clinvar_records": clinvar_records,
            "clinvar_source": metadata.get("clinvar_source"),
            "clinvar_source_version": metadata.get("clinvar_source_version"),
            "clinvar_genome_build": metadata.get("clinvar_genome_build"),
        }
        # The ClinVar gene index is deterministic for a given imported ClinVar
        # snapshot. Run-level --force should rerun sample artifacts, not rebuild
        # this public index in every cloned evidence DB.
        if existing_gene_links and metadata.get("clinvar_gene_index") == expected_cache:
            return {
                "status": "cached",
                "evidence_db": str(evidence_db),
                "clinvar_records": clinvar_records,
                "gene_links": existing_gene_links,
            }

        connection.execute("delete from main.clinvar_variant_genes")
        batch: list[tuple[str, int, str]] = []
        scanned = 0
        gene_links = 0
        for row in connection.execute(
            """
            select rowid as variant_rowid, genome_build, gene_info
            from clinvar_variants
            where gene_info is not null
            """
        ):
            scanned += 1
            for gene in _gene_symbols(row["gene_info"]):
                batch.append((gene, int(row["variant_rowid"]), row["genome_build"]))
                gene_links += 1
            if len(batch) >= 50_000:
                _insert_gene_index_batch(connection, batch)
                connection.commit()
                batch.clear()
        if batch:
            _insert_gene_index_batch(connection, batch)
        _upsert_metadata(connection, "clinvar_gene_index", expected_cache)
        connection.commit()

    return {
        "status": "completed",
        "evidence_db": str(evidence_db),
        "clinvar_records": clinvar_records,
        "scanned_records": scanned,
        "gene_links": gene_links,
    }


def build_clinvar_rsid_index(
    evidence_db: str | Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    evidence_db = Path(evidence_db)
    if not evidence_db.exists():
        raise FileNotFoundError(evidence_db)

    with connect_evidence(evidence_db, attach_shared=False) as connection:
        _ensure_schema(connection)
        metadata = _read_metadata(connection)
        clinvar_records = int(connection.execute("select count(*) as records from clinvar_variants").fetchone()["records"])
        existing_rsid_links = int(
            connection.execute("select count(*) as records from clinvar_variant_rsids").fetchone()["records"]
        )
        expected_cache = {
            "clinvar_records": clinvar_records,
            "clinvar_source": metadata.get("clinvar_source"),
            "clinvar_source_version": metadata.get("clinvar_source_version"),
            "clinvar_genome_build": metadata.get("clinvar_genome_build"),
            "rule_set_version": CLINVAR_RSID_INDEX_RULE_SET_VERSION,
        }
        if existing_rsid_links and metadata.get("clinvar_rsid_index") == expected_cache:
            return {
                "status": "cached",
                "evidence_db": str(evidence_db),
                "clinvar_records": clinvar_records,
                "rsid_links": existing_rsid_links,
            }

        connection.execute("delete from main.clinvar_variant_rsids")
        batch: list[tuple[str, int, str]] = []
        scanned = 0
        rsid_links = 0
        for row in connection.execute(
            """
            select rowid as variant_rowid, genome_build, raw_info_json
            from clinvar_variants
            """
        ):
            scanned += 1
            for rsid in _clinvar_raw_info_rsids(row["raw_info_json"]):
                batch.append((rsid, int(row["variant_rowid"]), row["genome_build"]))
                rsid_links += 1
            if len(batch) >= 50_000:
                _insert_rsid_index_batch(connection, batch)
                connection.commit()
                batch.clear()
        if batch:
            _insert_rsid_index_batch(connection, batch)
        _upsert_metadata(connection, "clinvar_rsid_index", expected_cache)
        connection.commit()

    return {
        "status": "completed",
        "evidence_db": str(evidence_db),
        "clinvar_records": clinvar_records,
        "scanned_records": scanned,
        "rsid_links": rsid_links,
    }
