"""Bgzip-aware parallel parsing for Active Genome Index builds.

The canonical source every parse produces is a bgzip file with a sibling
`.gzi` block index. This module partitions that file by bgzip block across
worker processes so the CPU-bound per-record parse runs in parallel — the
previous byte-range parallel path only worked on plain (uncompressed) VCFs,
so in practice every real (bgzip) parse ran single-threaded.

Each worker seeks to a block boundary (a BGZF virtual offset of the form
``compressed_block_offset << 16``), parses the records whose start offset
falls in its range into a shard SQLite DB, coalescing contiguous reference
blocks exactly like the single-threaded path. Shards are merged by the
caller. Reference runs that straddle a shard seam stay as (at most W-1)
adjacent rows — harmless and far cheaper than cross-shard coalescing.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

# Sentinel "read to end of file" virtual offset for the final worker. Larger
# than any real BGZF virtual offset (compressed offset is bounded well under
# 2**46 for any practical file, shifted left 16 bits).
_VOFFSET_EOF = 1 << 62


def read_gzi_block_offsets(gzi_path: str | Path) -> list[int]:
    """Return the compressed-file offsets of every bgzip block start.

    The htslib `.gzi` format is: uint64 little-endian entry count, then that
    many (compressed_offset, uncompressed_offset) uint64 pairs for every block
    *after* the first. The first block always starts at compressed offset 0
    and is implicit, so we prepend it.
    """

    data = Path(gzi_path).read_bytes()
    if len(data) < 8:
        return [0]
    (count,) = struct.unpack_from("<Q", data, 0)
    offsets = [0]
    cursor = 8
    for _ in range(count):
        if cursor + 16 > len(data):
            break
        compressed_offset, _uncompressed_offset = struct.unpack_from("<QQ", data, cursor)
        offsets.append(int(compressed_offset))
        cursor += 16
    return offsets


def bgzf_block_ranges(gzi_path: str | Path, workers: int) -> list[tuple[int, int]]:
    """Partition bgzip blocks into ``workers`` contiguous virtual-offset ranges.

    Each range is ``(start_voffset, end_voffset)`` where a worker owns records
    whose start virtual offset is in ``[start, end)``. The final range ends at
    ``_VOFFSET_EOF`` so the last worker reads through end of file.
    """

    block_offsets = read_gzi_block_offsets(gzi_path)
    block_voffsets = [offset << 16 for offset in block_offsets]
    block_count = len(block_voffsets)
    if workers <= 1 or block_count <= 1:
        return [(0, _VOFFSET_EOF)]
    workers = min(workers, block_count)
    per_worker = max(1, block_count // workers)
    ranges: list[tuple[int, int]] = []
    for index in range(workers):
        start = block_voffsets[index * per_worker]
        if index == workers - 1:
            end = _VOFFSET_EOF
        else:
            end = block_voffsets[(index + 1) * per_worker]
        ranges.append((start, end))
    return ranges


def build_shard_from_bgzf_range(args: tuple[Any, ...]) -> dict[str, Any]:
    """Multiprocessing worker: parse one bgzip virtual-offset range to a shard.

    ``args`` = (canonical_path, shard_path, start_voffset, end_voffset,
    sample_names, include_reference, commit_every). Returns
    ``{"shard_path", "stats"}``. Imports the build internals lazily so this
    stays picklable and the worker process loads them fresh.
    """

    (
        canonical_path,
        shard_path,
        start_voffset,
        end_voffset,
        sample_names,
        include_reference,
        commit_every,
    ) = args

    from pysam.libcbgzf import BGZFile

    from .active_genome_index import (
        ActiveGenomeIndexStats,
        _insert_record_batch,
        _record_row,
        _ReferenceRunCoalescer,
        _reset_schema,
        connect,
    )
    from .vcf import parse_record_line, sample_field_count

    connection = connect(shard_path)
    total = variant = reference = pass_count = fail_count = 0
    batch: list[tuple[Any, ...]] = []
    coalescer = _ReferenceRunCoalescer()

    def _emit(row: tuple[Any, ...]) -> None:
        batch.append(row)
        if len(batch) >= commit_every:
            _insert_record_batch(connection, batch)
            connection.commit()
            batch.clear()

    try:
        _reset_schema(connection)
        with BGZFile(str(canonical_path), "rb") as handle:
            handle.seek(int(start_voffset))
            # Lines straddle block boundaries; if this worker does not own the
            # very first block, its first readline is the tail of a line owned
            # by the previous worker — discard it. The previous worker reads
            # one line past its end (the `offset > end` check below fires only
            # after reading the boundary line), so no record is dropped or
            # double-counted.
            if int(start_voffset) != 0:
                handle.readline()
            while True:
                offset = handle.tell()
                if offset > end_voffset:
                    break
                raw = handle.readline()
                if not raw:
                    break
                if raw.startswith(b"#"):
                    continue
                text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if not text:
                    continue
                line_length = len(raw)
                sample_count = sample_field_count(text, sample_names)
                for sample_index in range(sample_count):
                    total += 1
                    record = parse_record_line(
                        text,
                        sample_names=sample_names,
                        sample_index=sample_index,
                        offset=offset,
                        line_length=line_length,
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
                    if not include_reference and not is_variant:
                        continue
                    if is_variant:
                        for flushed in coalescer.flush():
                            _emit(flushed)
                        _emit(row)
                    else:
                        for flushed in coalescer.add(row):
                            _emit(flushed)
        for flushed in coalescer.flush():
            _emit(flushed)
        if batch:
            _insert_record_batch(connection, batch)
        connection.commit()
        return {
            "shard_path": str(shard_path),
            "stats": ActiveGenomeIndexStats(
                total_records=total,
                variant_records=variant,
                reference_records=reference,
                pass_records=pass_count,
                fail_records=fail_count,
            ).to_dict(),
        }
    finally:
        connection.close()
