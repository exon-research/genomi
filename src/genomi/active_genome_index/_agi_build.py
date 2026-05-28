from __future__ import annotations

from .vcf import VcfHeader
from .vcf import iter_sample_records
from .vcf import parse_record_line
from .vcf import read_header
from .vcf import sample_field_count
from collections.abc import Callable
from pathlib import Path
from typing import Any
import contextlib
import json
import os
import sqlite3
from ._agi_readiness import ActiveGenomeIndexSchemaTooNew, _active_genome_index_readiness_from_connection
from ._agi_schema import ActiveGenomeIndexStats, SCHEMA_VERSION, _ReferenceRunCoalescer, _active_genome_index_build_lock, _byte_ranges, _create_query_indexes, _insert_metadata, _insert_record_batch, _insert_stat_rows, _is_plain_vcf, _mark_active_genome_index_build_completed, _multiprocessing_context, _record_row, _reset_schema, _shard_path, connect, connect_existing, connect_existing_readonly, default_active_genome_index_path
from ..runtime.sqlite_support import enable_wal


def create_active_genome_index(
    vcf_path: str | Path,
    active_genome_index_path: str | Path | None = None,
    *,
    include_reference: bool = True,
    commit_every: int = 50_000,
    max_records: int | None = None,
    parallel_workers: int | None = None,
    progress_every: int | None = None,
    progress: Callable[[int, int], None] | None = None,
    reuse_existing: bool = True,
) -> dict[str, Any]:
    vcf_path = Path(vcf_path)
    active_genome_index_path = Path(active_genome_index_path) if active_genome_index_path is not None else default_active_genome_index_path(vcf_path)
    active_genome_index_path.parent.mkdir(parents=True, exist_ok=True)
    # Schema v3 contract: the Active Genome Index must always carry a
    # canonical bgzip source so capability tools never reopen the intake.
    # Skip the canonical step ONLY when the caller passed us a bgzf-indexed
    # file that already lives under the Active Genome Index work dir (i.e. parse_source
    # routed through `<work_dir>/source/canonical.vcf.gz`, or a prior
    # create_active_genome_index materialized a per-Active-Genome-Index canonical here). Any external
    # bgzip — even with a .gzi sibling — must be re-materialized into the
    # Active Genome Index directory so it owns the bytes it
    # serves.
    from .canonical import (
        build_canonical_bgzip,
        canonical_paths_for_active_genome_index,
        canonical_vcf_path,
    )

    per_active_genome_index_canonical, per_active_genome_index_gzi = canonical_paths_for_active_genome_index(active_genome_index_path)
    # The only paths the Active Genome Index considers "already canonical"
    # are the two it would itself materialize: parse_source's standard
    # `<work_dir>/source/canonical.vcf.gz`, or the per-Active-Genome-Index variant from
    # `canonical_paths_for_active_genome_index`. Anything else — including an external
    # bgzip with a .gzi sibling that happens to share a parent directory —
    # is re-materialized so the Active Genome Index owns the bytes it serves.
    owned_canonicals = {
        Path(canonical_vcf_path(active_genome_index_path.parent)).resolve(),
        per_active_genome_index_canonical.resolve(),
    }
    try:
        resolved_input = Path(vcf_path).resolve()
    except OSError:
        resolved_input = Path(vcf_path)
    already_canonical = (
        Path(str(vcf_path) + ".gzi").exists()
        and resolved_input in owned_canonicals
    )
    if not already_canonical:
        # Per-Active-Genome-Index canonical so two Active Genome Index files that share a parent dir
        # (e.g. test_genotype_support_classifies_supported_and_weak_calls)
        # keep their own bgzip canonicals instead of stomping each other.
        build_canonical_bgzip(
            vcf_path,
            active_genome_index_path.parent,
            force=not reuse_existing,
            canonical_path=per_active_genome_index_canonical,
            gzi_path=per_active_genome_index_gzi,
        )
        vcf_path = per_active_genome_index_canonical
    if reuse_existing:
        cached = _cached_active_genome_index_if_usable(
            vcf_path,
            active_genome_index_path,
            include_reference=include_reference,
            max_records=max_records,
        )
        if cached is not None:
            return cached
    # Serialize concurrent builders on the same Active Genome Index path. Without this,
    # parallel callers (e.g. 10 agent sessions all calling
    # genomi.parse_source on the same VCF) race on the SQLite
    # writer and most fail with "database is locked". After acquiring the
    # advisory lock, re-check for a now-complete cached Active Genome Index in case
    # another process just finished — that converts the slow path into the
    # fast path for every follower.
    with _active_genome_index_build_lock(active_genome_index_path):
        if reuse_existing:
            cached = _cached_active_genome_index_if_usable(
                vcf_path,
                active_genome_index_path,
                include_reference=include_reference,
                max_records=max_records,
            )
            if cached is not None:
                return cached
        header = read_header(vcf_path)
        workers = _resolved_parallel_workers(vcf_path, parallel_workers=parallel_workers, max_records=max_records)
        if workers > 1:
            return _create_active_genome_index_parallel(
                vcf_path,
                active_genome_index_path,
                header=header,
                include_reference=include_reference,
                commit_every=commit_every,
                workers=workers,
                max_records=max_records,
            )
        active_genome_index_path.unlink(missing_ok=True)
        connection = connect(active_genome_index_path)
        try:
            _reset_schema(connection)
            _insert_metadata(connection, vcf_path, header, include_reference, max_records=max_records)
            stats = _populate_records(
                connection,
                vcf_path,
                include_reference=include_reference,
                commit_every=commit_every,
                max_records=max_records,
                progress_every=progress_every,
                progress=progress,
            )
            _create_query_indexes(connection)
            _insert_stat_rows(connection, stats)
            _mark_active_genome_index_build_completed(connection)
            connection.commit()
            enable_wal(connection)
            return {
                "status": "completed",
                "active_genome_index_complete": True,
                "vcf_path": str(vcf_path),
                "active_genome_index_path": str(active_genome_index_path),
                "schema_version": SCHEMA_VERSION,
                "include_reference": include_reference,
                "parallel_workers": 1,
                "stats": stats.to_dict(),
                "header": header.to_dict(),
            }
        finally:
            connection.close()

def _cached_active_genome_index_if_usable(
    vcf_path: Path,
    active_genome_index_path: Path,
    *,
    include_reference: bool,
    max_records: int | None,
) -> dict[str, Any] | None:
    if not active_genome_index_path.exists():
        return None
    try:
        with connect_existing(active_genome_index_path) as connection:
            readiness = _active_genome_index_readiness_from_connection(connection)
            metadata = readiness["metadata"]
            stats = readiness["stats"]
    except (sqlite3.Error, json.JSONDecodeError, ValueError):
        return None
    stat = vcf_path.stat()
    if not readiness["complete"]:
        return None
    stored_schema_version = metadata.get("schema_version")
    try:
        stored_schema_version_int = int(stored_schema_version) if stored_schema_version is not None else None
    except (TypeError, ValueError):
        stored_schema_version_int = None
    if stored_schema_version_int is None or stored_schema_version_int < SCHEMA_VERSION:
        return None
    if stored_schema_version_int > SCHEMA_VERSION:
        raise ActiveGenomeIndexSchemaTooNew(
            f"Active Genome Index at {active_genome_index_path} has schema_version="
            f"{stored_schema_version_int}; this Genomi runtime only "
            f"supports up to schema_version={SCHEMA_VERSION}. Upgrade "
            "Genomi before reading this Active Genome Index."
        )
    if metadata.get("vcf_path") != str(vcf_path):
        return None
    if int(metadata.get("vcf_size_bytes") or -1) != stat.st_size:
        return None
    if bool(metadata.get("include_reference")) != include_reference:
        return None
    if not _cached_record_limit_satisfies_request(metadata.get("max_records"), max_records):
        return None
    if not stats:
        return None
    return {
        "status": "cached",
        "active_genome_index_complete": True,
        "vcf_path": str(vcf_path),
        "active_genome_index_path": str(active_genome_index_path),
        "schema_version": SCHEMA_VERSION,
        "include_reference": include_reference,
        "parallel_workers": 0,
        "stats": stats,
        "header": metadata.get("header") or {},
    }

def _cached_record_limit_satisfies_request(cached_max_records: Any, requested_max_records: int | None) -> bool:
    if cached_max_records is None:
        return True
    if requested_max_records is None:
        return False
    try:
        return int(cached_max_records) >= int(requested_max_records)
    except (TypeError, ValueError):
        return False

def _create_active_genome_index_parallel(
    vcf_path: Path,
    active_genome_index_path: Path,
    *,
    header: VcfHeader,
    include_reference: bool,
    commit_every: int,
    workers: int,
    max_records: int | None,
) -> dict[str, Any]:
    active_genome_index_path.unlink(missing_ok=True)
    connection = connect(active_genome_index_path)
    shard_paths: list[Path] = []
    try:
        _reset_schema(connection)
        _insert_metadata(connection, vcf_path, header, include_reference, max_records=max_records)
        use_bgzf = _bgzip_indexed(vcf_path)
        if use_bgzf:
            from .parallel_build import bgzf_block_ranges, build_shard_from_bgzf_range

            ranges = bgzf_block_ranges(str(vcf_path) + ".gzi", workers)
            shard_worker = build_shard_from_bgzf_range
        else:
            ranges = _byte_ranges(vcf_path.stat().st_size, workers)
            shard_worker = _build_active_genome_index_shard
        shard_paths = [_shard_path(active_genome_index_path, shard_index) for shard_index in range(len(ranges))]
        for shard_path in shard_paths:
            if shard_path.exists():
                shard_path.unlink()
        tasks = [
            (
                str(vcf_path),
                str(shard_paths[index]),
                start,
                end,
                header.samples,
                include_reference,
                commit_every,
            )
            for index, (start, end) in enumerate(ranges)
        ]
        context = _multiprocessing_context()
        with context.Pool(processes=len(tasks)) as pool:
            shard_results = pool.map(shard_worker, tasks)

        stats = _merge_active_genome_index_shards(connection, shard_results)
        _create_query_indexes(connection)
        _insert_stat_rows(connection, stats)
        _mark_active_genome_index_build_completed(connection)
        connection.commit()
        enable_wal(connection)
        return {
            "status": "completed",
            "active_genome_index_complete": True,
            "vcf_path": str(vcf_path),
            "active_genome_index_path": str(active_genome_index_path),
            "schema_version": SCHEMA_VERSION,
            "include_reference": include_reference,
            "parallel_workers": len(tasks),
            "stats": stats.to_dict(),
            "header": header.to_dict(),
        }
    finally:
        connection.close()
        for shard_path in shard_paths:
            with contextlib.suppress(FileNotFoundError):
                shard_path.unlink()

def _build_active_genome_index_shard(args: tuple[str, str, int, int, list[str], bool, int]) -> dict[str, Any]:
    vcf_path_raw, shard_path_raw, start, end, sample_names, include_reference, commit_every = args
    vcf_path = Path(vcf_path_raw)
    shard_path = Path(shard_path_raw)
    connection = connect(shard_path)
    try:
        _reset_schema(connection)
        stats = _populate_records_from_byte_range(
            connection,
            vcf_path,
            start=start,
            end=end,
            sample_names=sample_names,
            include_reference=include_reference,
            commit_every=commit_every,
        )
        connection.commit()
        return {"shard_path": str(shard_path), "stats": stats.to_dict()}
    finally:
        connection.close()

def _populate_records_from_byte_range(
    connection: sqlite3.Connection,
    vcf_path: Path,
    *,
    start: int,
    end: int,
    sample_names: list[str],
    include_reference: bool,
    commit_every: int,
) -> ActiveGenomeIndexStats:
    total = 0
    variant = 0
    reference = 0
    pass_count = 0
    fail_count = 0
    batch: list[tuple[Any, ...]] = []

    with vcf_path.open("rb") as handle:
        if start > 0:
            handle.seek(start - 1)
            previous = handle.read(1)
            if previous != b"\n":
                handle.readline()
        else:
            handle.seek(start)
        while True:
            offset = handle.tell()
            if offset >= end:
                break
            raw = handle.readline()
            if not raw:
                break
            if raw.startswith(b"#"):
                continue
            text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not text:
                continue
            sample_count = sample_field_count(text, sample_names)
            for sample_index in range(sample_count):
                total += 1
                record = parse_record_line(
                    text,
                    sample_names=sample_names,
                    sample_index=sample_index,
                    offset=offset,
                    line_length=len(raw),
                )
                row = _record_row(record)
                is_variant = bool(row[13])
                if is_variant:
                    variant += 1
                else:
                    reference += 1
                if record.filter == "PASS":
                    pass_count += 1
                elif record.filter == "FAIL":
                    fail_count += 1
                if include_reference or is_variant:
                    batch.append(row)
                    if len(batch) >= commit_every:
                        _insert_record_batch(connection, batch)
                        connection.commit()
                        batch.clear()

    if batch:
        _insert_record_batch(connection, batch)
    return ActiveGenomeIndexStats(
        total_records=total,
        variant_records=variant,
        reference_records=reference,
        pass_records=pass_count,
        fail_records=fail_count,
    )

def _merge_active_genome_index_shards(connection: sqlite3.Connection, shard_results: list[dict[str, Any]]) -> ActiveGenomeIndexStats:
    total = variant = reference = pass_count = fail_count = 0
    for index, result in enumerate(shard_results):
        stats = result.get("stats") or {}
        total += int(stats.get("total_records") or 0)
        variant += int(stats.get("variant_records") or 0)
        reference += int(stats.get("reference_records") or 0)
        pass_count += int(stats.get("pass_records") or 0)
        fail_count += int(stats.get("fail_records") or 0)
        alias = f"shard_{index}"
        connection.execute(f"attach database ? as {alias}", (str(result["shard_path"]),))
        try:
            connection.execute(f"insert into records select * from {alias}.records")
            connection.execute(f"insert into spans select * from {alias}.spans")
            connection.commit()
        finally:
            connection.execute(f"detach database {alias}")
    return ActiveGenomeIndexStats(
        total_records=total,
        variant_records=variant,
        reference_records=reference,
        pass_records=pass_count,
        fail_records=fail_count,
    )

def _resolved_parallel_workers(vcf_path: Path, *, parallel_workers: int | None, max_records: int | None) -> int:
    if max_records is not None:
        return 1
    # A bgzip file with a `.gzi` block index can be partitioned by block and
    # parsed in parallel. A plain (uncompressed) VCF can be partitioned by raw
    # byte range. Plain gzip without a `.gzi` cannot be seeked into, so it
    # stays single-threaded.
    plain = _is_plain_vcf(vcf_path)
    bgzip_indexed = (not plain) and Path(str(vcf_path) + ".gzi").exists()
    if not (plain or bgzip_indexed):
        return 1
    if parallel_workers is not None:
        return max(1, int(parallel_workers))
    size = vcf_path.stat().st_size
    # bgzip is ~4-5x denser than plain VCF, so use a smaller byte threshold for
    # the compressed case to still parallelize genome-scale gVCFs.
    threshold = 128 * 1024 * 1024 if bgzip_indexed else 512 * 1024 * 1024
    if size < threshold:
        return 1
    requested = min(8, max(1, (os.cpu_count() or 1) - 1))
    return min(requested, max(1, size // (16 * 1024 * 1024)))

def _bgzip_indexed(vcf_path: Path) -> bool:
    return (not _is_plain_vcf(vcf_path)) and Path(str(vcf_path) + ".gzi").exists()

def _populate_records(
    connection: sqlite3.Connection,
    vcf_path: Path,
    *,
    include_reference: bool,
    commit_every: int,
    max_records: int | None,
    progress_every: int | None,
    progress: Callable[[int, int], None] | None,
) -> ActiveGenomeIndexStats:
    total = 0
    variant = 0
    reference = 0
    pass_count = 0
    fail_count = 0
    batch: list[tuple[Any, ...]] = []
    coalescer = _ReferenceRunCoalescer()

    def _emit(row: tuple[Any, ...]) -> None:
        batch.append(row)
        if len(batch) >= commit_every:
            _insert_record_batch(connection, batch)
            connection.commit()
            batch.clear()

    for record in iter_sample_records(vcf_path, limit=max_records):
        total += 1
        row = _record_row(record)
        is_variant = bool(row[13])
        if is_variant:
            variant += 1
        else:
            reference += 1
        if record.filter == "PASS":
            pass_count += 1
        elif record.filter == "FAIL":
            fail_count += 1
        if not include_reference and not is_variant:
            continue
        # Coalesce contiguous reference blocks of the same FILTER + GQ tier
        # into a single stored row. Fine-grained gVCFs emit short (sometimes
        # near-per-base) reference blocks; storing each as its own row is what
        # blows the index up to tens of GB. A merged row spans pos..end exactly
        # like the large reference blocks gVCFs already produce, so every
        # downstream reader treats it identically — no schema or reader change.
        if is_variant:
            for flushed in coalescer.flush():
                _emit(flushed)
            _emit(row)
        else:
            for flushed in coalescer.add(row):
                _emit(flushed)
        if progress is not None and progress_every is not None and total % progress_every == 0:
            progress(total, variant)

    for flushed in coalescer.flush():
        _emit(flushed)
    if batch:
        _insert_record_batch(connection, batch)

    return ActiveGenomeIndexStats(
        total_records=total,
        variant_records=variant,
        reference_records=reference,
        pass_records=pass_count,
        fail_records=fail_count,
    )
