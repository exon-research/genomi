from __future__ import annotations

import json
import shutil
import sqlite3
import tarfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from ...runtime.external import file_metadata
from ...runtime.paths import (
    ACTIVE_GENOME_INDEX_DB_NAME,
    run_evidence_db_path_for_source,
    run_evidence_dir_for_source,
    run_output_path_for_source,
    run_project_dir_for_source,
    run_reference_dir_for_source,
    run_work_dir_for_source,
    sample_slug_from_source,
    shared_evidence_db_path,
)
from .._agi_schema import SCHEMA_VERSION
from ..active_genome_index import _chrom_sort
from ..active_genome_index import connect as connect_active_genome_index
from ..observations import observed_alleles_from_vcf_genotype
from ..record_kinds import (
    RECORD_KIND_NO_CALL,
    RECORD_KIND_REFERENCE_BLOCK,
    RECORD_KIND_VARIANT_CALL,
    _is_no_call_genotype,
)
from ..vcf_info import format_vcf_info
from .agi_store import (
    JsonObject,
    _cached_array_active_genome_index_if_usable,
    _create_source_query_indexes,
    _init_source_evidence_db,
    _insert_source_active_genome_index_metadata,
    _insert_source_record_batch,
    _insert_source_stat_rows,
    _mark_source_active_genome_index_completed,
    _reset_source_active_genome_index_schema,
)
from .detection import SourceDetection, detect_source


def parse_genome_bundle_source(
    source: str | Path,
    *,
    detection: SourceDetection | None = None,
    evidence_db: str | Path | None = None,
    source_evidence_db: str | Path | None = None,
    shared_evidence_db: str | Path | None = None,
    genome_build: str = "auto",
    force: bool = False,
    max_records: int | None = None,
) -> JsonObject:
    source_path = Path(source)
    detection = detection or detect_source(source_path)
    if detection.source_format != "genome":
        raise ValueError(f"no .genome bundle parser for source_format: {detection.source_format}")
    project_dir = run_project_dir_for_source(source_path, source_format="genome")
    work_dir = run_work_dir_for_source(source_path, source_format="genome")
    evidence_dir = run_evidence_dir_for_source(source_path, source_format="genome")
    reference_dir = run_reference_dir_for_source(source_path, source_format="genome")
    db_path = (
        Path(evidence_db)
        if evidence_db is not None
        else run_evidence_db_path_for_source(source_path, source_format="genome")
    )
    shared_db = Path(shared_evidence_db) if shared_evidence_db is not None else shared_evidence_db_path()
    agi_path = run_output_path_for_source(source_path, ACTIVE_GENOME_INDEX_DB_NAME, source_format="genome")
    project_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)

    bundle_dir = _materialize_genome_bundle(source_path, detection=detection, work_dir=work_dir, force=force)
    manifest = _read_manifest(bundle_dir)
    effective_build = _effective_genome_build(genome_build, manifest.get("genome_build"), detection.reference_build)

    _init_source_evidence_db(
        db_path,
        source_path,
        source_format="genome",
        source_evidence_db=source_evidence_db,
        shared_evidence_db=shared_db,
    )
    agi_result = _build_genome_bundle_active_genome_index(
        source_path,
        bundle_dir,
        agi_path,
        detection=detection,
        genome_build=effective_build,
        manifest=manifest,
        force=force,
        max_records=max_records,
    )
    return {
        "workflow_area": "active-genome-index",
        "status": "completed",
        "source": str(source_path),
        "source_format": "genome",
        "source_kind": "genome_bundle",
        "source_member": detection.member_name,
        "provider": detection.provider,
        "sample_slug": sample_slug_from_source(source_path, source_format="genome"),
        "genome_build": effective_build,
        "evidence_db": str(db_path),
        "shared_evidence_db": str(shared_db),
        "project_dir": str(project_dir),
        "work_dir": str(work_dir),
        "evidence_dir": str(evidence_dir),
        "reference_dir": str(reference_dir),
        "outputs": {"agi_path": str(agi_path), "bundle_dir": str(bundle_dir)},
        "steps": [
            {
                "name": "build-active-genome-index",
                "result": agi_result,
                "reason": "The .genome bundle variants are digitized into an Active Genome Index.",
            }
        ],
    }


def _build_genome_bundle_active_genome_index(
    source_path: Path,
    bundle_dir: Path,
    agi_path: Path,
    *,
    detection: SourceDetection,
    genome_build: str,
    manifest: JsonObject,
    force: bool,
    max_records: int | None,
) -> JsonObject:
    if agi_path.exists() and not force:
        cached = _cached_array_active_genome_index_if_usable(
            source_path,
            agi_path,
            detection=detection,
            source_format="genome",
            genome_build=genome_build,
            max_records=max_records,
        )
        if cached is not None:
            return cached
    agi_path.parent.mkdir(parents=True, exist_ok=True)
    with connect_active_genome_index(agi_path) as connection:
        _reset_source_active_genome_index_schema(connection)
        _insert_source_active_genome_index_metadata(
            connection,
            source_path,
            detection=detection,
            genome_build=genome_build,
            max_records=max_records,
        )
        _insert_genome_bundle_header_lines(connection, manifest=manifest)
        stats, chromosome_counts = _populate_genome_bundle_records(
            connection,
            bundle_dir,
            max_records=max_records,
        )
        _create_source_query_indexes(connection)
        _insert_source_stat_rows(connection, stats)
        _mark_source_active_genome_index_completed(connection)
        connection.commit()
    return {
        "status": "completed",
        "source": str(source_path),
        "source_format": "genome",
        "agi_path": str(agi_path),
        "schema_version": SCHEMA_VERSION,
        "genome_build": genome_build,
        "genome_schema_version": manifest.get("schema_version"),
        "pipeline_version": manifest.get("pipeline_version"),
        "stats": stats,
        "chromosome_counts": dict(sorted(chromosome_counts.items(), key=lambda item: (_chrom_sort(item[0]), item[0]))),
    }


def _populate_genome_bundle_records(
    connection: sqlite3.Connection,
    bundle_dir: Path,
    *,
    max_records: int | None,
) -> tuple[JsonObject, Counter[str]]:
    duckdb = _duckdb_module()
    variants_dir = bundle_dir / "variants.parquet"
    if not variants_dir.exists():
        raise ValueError(f".genome bundle is missing variants.parquet: {bundle_dir}")
    parquet_files = sorted(
        str(path)
        for path in variants_dir.rglob("*.parquet")
        if not path.name.startswith(".") and not any(part.startswith("__MACOSX") for part in path.parts)
    )
    if not parquet_files:
        raise ValueError(f".genome bundle has no readable variants parquet files: {variants_dir}")
    limit_clause = "" if max_records is None else " limit ?"
    params: list[Any] = [parquet_files]
    if max_records is not None:
        params.append(max_records)
    query = f"""
        select
            chrom,
            pos,
            ref,
            alt,
            rsid,
            genotype.gt as gt,
            genotype.phased as phased,
            quality.dp as dp,
            quality.gq as gq,
            gene.symbol as gene_symbol,
            variant_id
        from read_parquet(?, hive_partitioning=true)
        {limit_clause}
    """
    total = 0
    pass_records = 0
    fail_records = 0
    variant_records = 0
    reference_records = 0
    no_call_records = 0
    batch: list[tuple[Any, ...]] = []
    chrom_counts: Counter[str] = Counter()
    con = duckdb.connect()
    try:
        cursor = con.execute(query, params)
        while True:
            rows = cursor.fetchmany(50_000)
            if not rows:
                break
            for row in rows:
                total += 1
                record = _genome_bundle_record_row(row, row_index=total)
                chrom = str(record[0])
                chrom_counts[chrom] += 1
                if record[21] == RECORD_KIND_NO_CALL:
                    no_call_records += 1
                    fail_records += 1
                else:
                    pass_records += 1
                    if record[21] == RECORD_KIND_REFERENCE_BLOCK:
                        reference_records += 1
                    else:
                        variant_records += 1
                batch.append(record)
            _insert_source_record_batch(connection, batch)
            connection.commit()
            batch.clear()
    finally:
        con.close()
    stats = {
        "total_records": total,
        "variant_records": variant_records,
        "reference_records": reference_records,
        "pass_records": pass_records,
        "fail_records": fail_records,
        "no_call_records": no_call_records,
    }
    return stats, chrom_counts


def _genome_bundle_record_row(row: tuple[Any, ...], *, row_index: int) -> tuple[Any, ...]:
    chrom, pos, ref, alt, rsid, gt, phased, dp, gq, gene_symbol, variant_id = row
    chrom = str(chrom or "")
    pos = int(pos)
    ref = str(ref or ".")
    alt = str(alt or ".")
    genotype = _genotype_string(gt, phased=bool(phased))
    no_call = _is_no_call_genotype(genotype)
    is_reference = not no_call and _is_reference_genotype(genotype)
    if no_call:
        record_kind = RECORD_KIND_NO_CALL
    elif is_reference:
        record_kind = RECORD_KIND_REFERENCE_BLOCK
    else:
        record_kind = RECORD_KIND_VARIANT_CALL
    info_genes = [str(gene_symbol)] if gene_symbol else []
    info = format_vcf_info({"variant_id": variant_id}) if variant_id else "."
    sample = genotype
    if dp is not None or gq is not None:
        sample = f"{genotype}:{'.' if dp is None else int(dp)}:{'.' if gq is None else int(gq)}"
    observed = None if no_call else observed_alleles_from_vcf_genotype(ref, alt, genotype)
    return (
        chrom,
        _chrom_sort(chrom),
        pos,
        pos + max(len(ref), 1) - 1,
        rsid or None,
        0,
        "genome",
        json.dumps(info_genes, sort_keys=True),
        info,
        ref,
        alt,
        None,
        "PASS" if not no_call else ".",
        0 if no_call or is_reference else 1,
        "GT:DP:GQ" if dp is not None or gq is not None else "GT",
        sample,
        genotype,
        None if dp is None else int(dp),
        None if gq is None else int(gq),
        row_index,
        0,
        record_kind,
        json.dumps(observed, sort_keys=True) if observed is not None else None,
    )


def _genotype_string(gt: Any, *, phased: bool) -> str:
    if not isinstance(gt, list) or not gt:
        return "."
    separator = "|" if phased else "/"
    return separator.join("." if item is None else str(int(item)) for item in gt)


def _is_reference_genotype(genotype: str) -> bool:
    alleles = genotype.replace("|", "/").split("/")
    return bool(alleles) and all(allele == "0" for allele in alleles)


def _materialize_genome_bundle(source_path: Path, *, detection: SourceDetection, work_dir: Path, force: bool) -> Path:
    if source_path.is_dir():
        return source_path
    target_root = work_dir / "source-bundle"
    marker = target_root / ".source-metadata.json"
    expected_metadata = file_metadata(source_path)
    if not force and marker.is_file():
        try:
            if json.loads(marker.read_text(encoding="utf-8")) == expected_metadata:
                existing = _single_bundle_dir(target_root)
                if existing is not None:
                    return existing
        except (OSError, json.JSONDecodeError):
            pass
    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(source_path):
        with zipfile.ZipFile(source_path) as archive:
            _safe_extract_zip(archive, target_root)
    elif tarfile.is_tarfile(source_path):
        with tarfile.open(source_path) as archive:
            _safe_extract_tar(archive, target_root)
    else:
        raise ValueError(f".genome source is not a directory or archive: {source_path}")
    marker.write_text(json.dumps(expected_metadata, sort_keys=True), encoding="utf-8")
    bundle_dir = target_root / str(detection.member_name or "")
    if not bundle_dir.is_dir():
        bundle_dir = _single_bundle_dir(target_root) or bundle_dir
    if not bundle_dir.is_dir() and _is_bundle_dir(target_root):
        bundle_dir = target_root
    if not bundle_dir.is_dir():
        raise ValueError(f"extracted .genome bundle directory was not found in {source_path}")
    return bundle_dir


def _single_bundle_dir(root: Path) -> Path | None:
    bundles = [path for path in root.iterdir() if path.is_dir() and path.name.endswith(".genome")]
    return bundles[0] if len(bundles) == 1 else None


def _is_bundle_dir(path: Path) -> bool:
    return (path / "manifest.json").is_file() and (path / "schema.json").is_file() and (path / "variants.parquet").is_dir()


def _safe_extract_tar(archive: tarfile.TarFile, target_root: Path) -> None:
    resolved_root = target_root.resolve()
    for member in archive.getmembers():
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise ValueError(f"unsafe tar member type in .genome bundle: {member.name}")
        target = (target_root / member.name).resolve()
        if target != resolved_root and not str(target).startswith(str(resolved_root) + "/"):
            raise ValueError(f"unsafe tar member path in .genome bundle: {member.name}")
    try:
        archive.extractall(target_root, filter="data")
    except TypeError:
        archive.extractall(target_root)


def _safe_extract_zip(archive: zipfile.ZipFile, target_root: Path) -> None:
    for member in archive.infolist():
        target = (target_root / member.filename).resolve()
        if not str(target).startswith(str(target_root.resolve()) + "/"):
            raise ValueError(f"unsafe zip member path in .genome bundle: {member.filename}")
    archive.extractall(target_root)


def _read_manifest(bundle_dir: Path) -> JsonObject:
    manifest_path = bundle_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f".genome bundle manifest could not be read: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f".genome bundle manifest is not an object: {manifest_path}")
    schema_version = str(manifest.get("schema_version") or "")
    if not schema_version.startswith("1."):
        raise ValueError(f"unsupported .genome schema_version: {schema_version or '<missing>'}")
    return manifest


def _effective_genome_build(requested: str, declared: Any, detected: str | None) -> str:
    normalized = (requested or "auto").strip()
    if normalized.lower() == "auto":
        return str(declared or detected or "GRCh38")
    return normalized


def _insert_genome_bundle_header_lines(connection: sqlite3.Connection, *, manifest: JsonObject) -> None:
    lines = [
        "##fileformat=VCFv4.2",
        "##source=Genomi .genome bundle",
        "##genomiSourceFormat=genome",
        f"##genomiGenomeSchemaVersion={manifest.get('schema_version') or ''}",
        f"##genomiGenomePipelineVersion={manifest.get('pipeline_version') or ''}",
        '##INFO=<ID=variant_id,Number=1,Type=String,Description="Genomi variant identifier">',
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
    ]
    connection.execute("delete from source_header_lines")
    connection.executemany(
        "insert into source_header_lines(line_number, line) values(?, ?)",
        [(index, line) for index, line in enumerate(lines)],
    )


def _duckdb_module():
    try:
        import duckdb
    except ImportError as exc:
        raise ValueError("Reading .genome bundles requires the duckdb Python package.") from exc
    return duckdb
