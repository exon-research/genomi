from __future__ import annotations

try:
    import fcntl  # POSIX-only; falls back to no-op locking elsewhere.
except ImportError:  # pragma: no cover - non-POSIX support is best-effort
    fcntl = None  # type: ignore[assignment]

from ..runtime.external import utc_now
from ..runtime.paths import ACTIVE_GENOME_INDEX_DB_NAME, run_output_path
from ..runtime.sqlite_support import DEFAULT_BUSY_TIMEOUT_SECONDS
from ..runtime.sqlite_support import connect_sqlite, connect_readonly_sqlite
from .vcf import SIMPLE_GENE_KEYS
from .vcf import VcfHeader
from .vcf import VcfRecord
from .vcf import _is_symbolic_non_ref_alt
from .vcf import sample_metrics as _vcf_sample_metrics
from .observations import observed_alleles_from_vcf_genotype
from .record_kinds import (
    RECORD_KIND_NO_CALL,
    RECORD_KIND_REFERENCE_BLOCK,
    RECORD_KIND_VARIANT_CALL,
    _is_no_call_genotype,
)
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import contextlib
import errno
import json
import multiprocessing
import os
import sqlite3
import time


SCHEMA_VERSION = 5

ACTIVE_GENOME_INDEX_BUILD_STATUS_IN_PROGRESS = "in_progress"

# Intermediate state for the two-phase gVCF build: every variant record is
# parsed, stored and indexed (so the entire interpretation surface — rsID,
# gene, region, exact-allele lookup — is correct), while the reference-block
# tail (~96% of a gVCF, the slow part) is still being appended by a detached
# continuation. A variants_ready index is queryable now; the only answers it
# cannot give yet are "is this locus confirmed reference vs not-callable",
# which the resolver already degrades gracefully (see _agi_readiness).
ACTIVE_GENOME_INDEX_BUILD_STATUS_VARIANTS_READY = "variants_ready"

ACTIVE_GENOME_INDEX_BUILD_STATUS_COMPLETED = "completed"

REQUIRED_QUERY_OBJECTS = {
    ("table", "metadata"),
    ("table", "stats"),
    ("table", "records"),
    ("table", "spans"),
    ("table", "source_header_lines"),
    ("index", "records_rsid_idx"),
    ("index", "records_region_idx"),
    ("index", "records_variant_idx"),
    ("index", "records_export_idx"),
    ("index", "records_offset_sample_idx"),
    ("index", "records_record_kind_idx"),
    ("index", "spans_region_idx"),
}

@dataclass(frozen=True)
class ActiveGenomeIndexStats:
    total_records: int
    variant_records: int
    reference_records: int
    no_call_records: int
    pass_records: int
    fail_records: int

    def to_dict(self) -> dict[str, int]:
        return {
            "total_records": self.total_records,
            "variant_records": self.variant_records,
            "reference_records": self.reference_records,
            "no_call_records": self.no_call_records,
            "pass_records": self.pass_records,
            "fail_records": self.fail_records,
        }

def default_agi_path(vcf_path: str | Path, root: str | Path | None = None) -> Path:
    return run_output_path(vcf_path, ACTIVE_GENOME_INDEX_DB_NAME, root=root)

def connect(agi_path: str | Path) -> sqlite3.Connection:
    # Even with the advisory build lock holding off other builders, a long-
    # lived reader (variant_lookup, _active_genome_index_counts, active_genome_index_readiness) can
    # still have a connection open when the writer reaches
    # _create_query_indexes. Without a busy_timeout that connection's
    # writes fail with "database is locked" immediately. 30s is enough
    # to outlast any normal read transaction.
    return connect_sqlite(agi_path, timeout_seconds=DEFAULT_BUSY_TIMEOUT_SECONDS)

def connect_existing(agi_path: str | Path) -> sqlite3.Connection:
    path = Path(agi_path)
    if not path.exists():
        raise FileNotFoundError(f"Active Genome Index not found: {path}; run `genomi call genomi.parse_source` to create it first")
    return connect(path)


def connect_existing_readonly(agi_path: str | Path) -> sqlite3.Connection:
    path = Path(agi_path)
    if not path.exists():
        raise FileNotFoundError(f"Active Genome Index not found: {path}; run `genomi call genomi.parse_source` to create it first")
    connection = connect_readonly_sqlite(path)
    connection.execute("pragma cache_size = -65536")  # 64 MB read cache
    connection.execute("pragma mmap_size = 268435456")  # 256 MB mmap for sequential scans
    return connection

@contextlib.contextmanager
def _active_genome_index_build_lock(agi_path: Path):
    """Cross-process advisory lock keyed on the Active Genome Index path.

    Uses POSIX fcntl.flock with a sidecar `.lock` file. Falls back to a
    best-effort poll on non-POSIX platforms where fcntl is unavailable.
    The lock is held only for the duration of the Active Genome Index build; readers
    do not need to acquire it.
    """
    lock_path = agi_path.with_suffix(agi_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:
        # No POSIX flock; busy-wait on lock file presence as a soft fallback.
        deadline = time.monotonic() + 600
        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
                break
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise
                if time.monotonic() > deadline:
                    raise TimeoutError(f"timed out waiting for Active Genome Index build lock at {lock_path}") from exc
                time.sleep(0.5)
        try:
            yield
        finally:
            os.close(fd)
            with contextlib.suppress(FileNotFoundError):
                lock_path.unlink()
        return
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)

def _is_plain_vcf(vcf_path: Path) -> bool:
    with vcf_path.open("rb") as handle:
        return handle.read(2) != b"\x1f\x8b"

def _byte_ranges(size: int, workers: int) -> list[tuple[int, int]]:
    chunk_size = max(1, size // workers)
    ranges = []
    for index in range(workers):
        start = index * chunk_size
        end = size if index == workers - 1 else (index + 1) * chunk_size
        ranges.append((start, end))
    return ranges

def _shard_path(agi_path: Path, shard_index: int) -> Path:
    return agi_path.with_name(f"{agi_path.name}.shard-{shard_index}.sqlite")

def _multiprocessing_context() -> multiprocessing.context.BaseContext:
    if "fork" in multiprocessing.get_all_start_methods():
        return multiprocessing.get_context("fork")
    return multiprocessing.get_context()

def _reset_schema(connection: sqlite3.Connection) -> None:
    # NOTE: do not set `locking_mode = exclusive` here. That pragma makes
    # SQLite hold an OS-level exclusive lock on the Active Genome Index file for the
    # entire build, which causes every concurrent reader
    # (active_genome_index.classify_genotype_support, etc.) to fail with
    # "database is locked" while one process is parsing. The advisory file
    # lock in create_active_genome_index already serializes builders; SQLite-level
    # exclusive locking is redundant and only hurts readers.
    connection.executescript(
        """
        pragma page_size = 16384;
        pragma journal_mode = off;
        pragma synchronous = off;
        pragma temp_store = memory;

        drop table if exists metadata;
        drop table if exists stats;
        drop table if exists spans;
        drop table if exists records;
        drop table if exists source_header_lines;

        create table metadata (
            key text primary key,
            value text not null
        );

        create table stats (
            key text primary key,
            value text not null
        );

        create table records (
            chrom text not null,
            chrom_sort integer not null,
            pos integer not null,
            end integer not null,
            rsid text,
            sample_index integer not null default 0,
            sample_name text,
            info_genes text,
            info text,
            ref text not null,
            alt text not null,
            qual text,
            filter text not null,
            is_variant integer not null,
            format text,
            sample text,
            genotype text,
            depth integer,
            genotype_quality integer,
            -- Schema v3: `offset` and `line_length` describe a position
            -- inside the Active Genome Index's owned canonical bgzip VCF
            -- (`<agi_dir>/source/canonical.vcf.gz`). `offset` is the BGZF
            -- virtual offset (block-address << 16 | within-block-offset);
            -- `line_length` is the decompressed record-line length and is
            -- informational only — random access uses BGZFile.seek(offset).
            offset integer not null,
            line_length integer not null,
            record_kind text not null,
            observed_alleles text
        );

        create table spans (
            chrom text not null,
            chrom_sort integer not null,
            pos integer not null,
            end integer not null,
            offset integer not null,
            sample_index integer not null default 0
        );

        -- Parse self-sufficiency: persist the source VCF header verbatim so
        -- the structured Active Genome Index can reconstruct the header (meta
        -- lines + #CHROM columns) without ever reopening the source/canonical.
        -- Required in schema v4 (see REQUIRED_QUERY_OBJECTS); pre-v4 indexes
        -- are rebuilt by the schema-version reparse path, not tolerated.
        create table source_header_lines (
            line_number integer primary key,
            line text not null
        );
        """
    )

def _create_query_indexes(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        create index records_rsid_idx on records(rsid) where rsid is not null;
        create index records_region_idx on records(chrom, pos, end);
        create index records_variant_idx on records(chrom, pos, ref, alt) where is_variant = 1;
        create index records_export_idx on records(is_variant, filter, chrom_sort, pos) where is_variant = 1;
        create index records_offset_sample_idx on records(offset, sample_index);
        create index records_record_kind_idx on records(record_kind, chrom, pos);
        create index spans_region_idx on spans(chrom, pos, end);
        """
    )

def _insert_metadata(
    connection: sqlite3.Connection,
    vcf_path: Path,
    header: VcfHeader,
    include_reference: bool,
    *,
    max_records: int | None,
    source_format: str = "vcf",
    provider: str | None = None,
) -> None:
    stat = vcf_path.stat()
    values = {
        "schema_version": SCHEMA_VERSION,
        "vcf_path": str(vcf_path),
        "source_format": source_format,
        "provider": provider,
        "vcf_size_bytes": stat.st_size,
        "vcf_mtime_ns": stat.st_mtime_ns,
        "include_reference": include_reference,
        "max_records": max_records,
        "header": header.to_dict(),
        "active_genome_index_build_status": ACTIVE_GENOME_INDEX_BUILD_STATUS_IN_PROGRESS,
        "active_genome_index_complete": False,
        "active_genome_index_started_at": utc_now(),
        "active_genome_index_completed_at": None,
    }
    connection.executemany(
        "insert into metadata(key, value) values(?, ?)",
        [(key, json.dumps(value)) for key, value in values.items()],
    )
    _insert_source_header_lines(connection, header)

def _insert_source_header_lines(connection: sqlite3.Connection, header: VcfHeader) -> None:
    """Persist the source VCF header verbatim (meta ## lines + the #CHROM
    column line) so the header can be reconstructed from the structured index
    alone — no reopening the source/canonical."""
    header_lines = [*list(header.meta), "\t".join(header.columns)]
    connection.executemany(
        "insert into source_header_lines(line_number, line) values(?, ?)",
        [(index, line) for index, line in enumerate(header_lines)],
    )

def read_header_from_active_genome_index(connection: sqlite3.Connection) -> VcfHeader:
    """Reconstruct the source VcfHeader from the persisted header lines.

    Schema v4 always persists the header at parse time (source_header_lines is
    a required table), so this reads the structured index alone — never the
    source or canonical.
    """
    rows = connection.execute(
        "select line from source_header_lines order by line_number"
    ).fetchall()
    lines = [str(row[0]) for row in rows]
    meta = [line for line in lines if line.startswith("##")]
    chrom_line = next((line for line in lines if line.startswith("#CHROM")), None)
    columns = chrom_line.split("\t") if chrom_line else []
    return VcfHeader(meta=meta, columns=columns)

def _mark_active_genome_index_variants_ready(connection: sqlite3.Connection) -> None:
    """Phase A done: variants stored + indexed, reference tail still pending.

    Leaves active_genome_index_complete False on purpose — readiness keys
    `complete` on that marker, so a variants_ready index reports the distinct
    intermediate status while still serving variant queries.
    """
    _upsert_metadata(connection, "active_genome_index_build_status", ACTIVE_GENOME_INDEX_BUILD_STATUS_VARIANTS_READY)
    _upsert_metadata(connection, "active_genome_index_complete", False)
    _upsert_metadata(connection, "variants_complete", True)
    _upsert_metadata(connection, "reference_complete", False)
    _upsert_metadata(connection, "variants_ready_at", utc_now())

def _mark_active_genome_index_build_completed(connection: sqlite3.Connection) -> None:
    _upsert_metadata(connection, "active_genome_index_build_status", ACTIVE_GENOME_INDEX_BUILD_STATUS_COMPLETED)
    _upsert_metadata(connection, "active_genome_index_complete", True)
    # A single-phase build never set these; stamp them so every completed
    # index is self-consistent (variants + reference both present).
    _upsert_metadata(connection, "variants_complete", True)
    _upsert_metadata(connection, "reference_complete", True)
    _upsert_metadata(connection, "active_genome_index_completed_at", utc_now())

def _upsert_metadata(connection: sqlite3.Connection, key: str, value: Any) -> None:
    connection.execute(
        """
        insert into metadata(key, value) values(?, ?)
        on conflict(key) do update set value = excluded.value
        """,
        (key, json.dumps(value)),
    )

# json.dumps([]) for the common no-gene record, precomputed once.
_EMPTY_INFO_GENES_JSON = json.dumps([])

_ROW_CHROM = 0

_ROW_POS = 2

_ROW_END = 3

_ROW_SAMPLE_INDEX = 5

_ROW_IS_VARIANT = 13

_ROW_FILTER = 12

_ROW_GENOTYPE = 16

_ROW_DEPTH = 17

_ROW_GQ = 18

def _reference_gq_tier(gq: Any) -> str:
    """Coarse GQ band so a low-confidence position is never merged into a
    high-confidence reference run (callability must keep that distinction)."""
    if gq is None:
        return "na"
    try:
        return "hi" if int(gq) >= 20 else "lo"
    except (TypeError, ValueError):
        return "na"

class _ReferenceRunCoalescer:
    """Merge consecutive, contiguous reference-block rows into one stored row.

    A run extends only while chrom, sample_index, FILTER, genotype and GQ tier
    match and the next block starts exactly one base after the current end
    (no gap, no overlap). The merged row keeps the first block's identity
    (ref/genotype/offset/rsid/...), spans the full pos..end, and reports the
    minimum DP and GQ across the run so callability stays conservative.
    """

    def __init__(self) -> None:
        self._pending: list[Any] | None = None
        self._key: tuple[Any, ...] | None = None

    def _row_key(self, row: tuple[Any, ...]) -> tuple[Any, ...]:
        return (
            row[_ROW_CHROM],
            row[_ROW_SAMPLE_INDEX],
            row[_ROW_FILTER],
            row[_ROW_GENOTYPE],
            _reference_gq_tier(row[_ROW_GQ]),
        )

    def add(self, row: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        key = self._row_key(row)
        if (
            self._pending is not None
            and key == self._key
            and int(row[_ROW_POS]) == int(self._pending[_ROW_END]) + 1
        ):
            self._pending[_ROW_END] = row[_ROW_END]
            self._pending[_ROW_DEPTH] = _min_optional(self._pending[_ROW_DEPTH], row[_ROW_DEPTH])
            self._pending[_ROW_GQ] = _min_optional(self._pending[_ROW_GQ], row[_ROW_GQ])
            return []
        emitted = self.flush()
        self._pending = list(row)
        self._key = key
        return emitted

    def flush(self) -> list[tuple[Any, ...]]:
        if self._pending is None:
            return []
        emitted = [tuple(self._pending)]
        self._pending = None
        self._key = None
        return emitted

def _min_optional(current: Any, candidate: Any) -> Any:
    if current is None:
        return candidate
    if candidate is None:
        return current
    try:
        return current if int(current) <= int(candidate) else candidate
    except (TypeError, ValueError):
        return current

def _record_row(record: VcfRecord) -> tuple[Any, ...]:
    genotype, depth, genotype_quality = _sample_metrics(record.format, record.sample, record.info)
    end, info_genes = _info_end_and_genes(record.info, record.pos, record.ref)
    alts = [] if record.alt in ("", ".") else record.alt.split(",")
    no_call = _is_no_call_genotype(genotype)
    has_variant_allele = _record_is_variant(record.alt, alts, genotype)
    record_kind = (
        RECORD_KIND_NO_CALL
        if no_call
        else (RECORD_KIND_VARIANT_CALL if has_variant_allele else RECORD_KIND_REFERENCE_BLOCK)
    )
    is_variant = record_kind == RECORD_KIND_VARIANT_CALL
    observed_alleles = observed_alleles_from_vcf_genotype(record.ref, record.alt, genotype)
    # Reference blocks — the bulk of a WGS gVCF — carry no genes, so skip the
    # json.dumps round-trip for the empty list with a shared literal.
    info_genes_json = _EMPTY_INFO_GENES_JSON if not info_genes else json.dumps(info_genes)
    return (
        record.chrom,
        _chrom_sort(record.chrom),
        record.pos,
        end,
        None if record.record_id == "." else record.record_id,
        record.sample_index,
        record.sample_name,
        info_genes_json,
        record.info,
        record.ref,
        record.alt,
        None if record.qual == "." else record.qual,
        record.filter,
        int(is_variant),
        record.format,
        record.sample,
        genotype,
        depth,
        genotype_quality,
        record.offset,
        record.line_length,
        record_kind,
        json.dumps(observed_alleles, sort_keys=True) if observed_alleles is not None else None,
    )


def _sample_metrics(
    format_field: str,
    sample_field: str,
    info_field: str | dict[str, str | bool] | None = None,
) -> tuple[str | None, int | None, int | None]:
    return _vcf_sample_metrics(format_field, sample_field, info_field)

def _info_end_and_genes(info: str, pos: int, ref: str) -> tuple[int, list[str]]:
    fallback_end = pos + max(len(ref), 1) - 1
    if not info or info == ".":
        return fallback_end, []
    end = fallback_end
    genes: list[str] = []
    for item in info.split(";"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        if key == "END":
            try:
                end = int(value)
            except ValueError:
                end = fallback_end
            continue
        if key in SIMPLE_GENE_KEYS:
            genes.extend(_split_gene_values(value))
            continue
        if key == "ANN":
            for annotation in value.split(","):
                fields = annotation.split("|")
                if len(fields) > 3:
                    genes.extend(_split_gene_values(fields[3]))
            continue
        if key == "CSQ":
            for annotation in value.split(","):
                fields = annotation.split("|")
                for field_index in (3, 4):
                    if len(fields) > field_index:
                        genes.extend(_split_gene_values(fields[field_index]))
            continue
        if key == "EFF":
            for annotation in value.split(","):
                if "(" not in annotation or ")" not in annotation:
                    continue
                fields = annotation.split("(", 1)[1].split(")", 1)[0].split("|")
                if len(fields) > 5:
                    genes.extend(_split_gene_values(fields[5]))
    return end, _unique_gene_values(genes)

def _split_gene_values(value: str) -> list[str]:
    return [
        item.strip()
        for item in value.replace("&", ",").replace("+", ",").split(",")
        if item.strip() and item.strip() not in {".", "-"}
    ]

def _unique_gene_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output = []
    for value in values:
        key = value.upper()
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output

def _record_is_variant(alt: str, alts: list[str], genotype: str | None) -> bool:
    if alt in ("", "."):
        return False
    if genotype:
        for token in genotype.replace("|", "/").split("/"):
            if token in {"", ".", "0"}:
                continue
            try:
                allele = alts[int(token) - 1]
            except (IndexError, ValueError):
                continue
            if not _is_symbolic_non_ref_alt(allele):
                return True
        return False
    return any(not _is_symbolic_non_ref_alt(allele) for allele in alts)

def _insert_record_batch(connection: sqlite3.Connection, batch: Iterable[tuple[Any, ...]]) -> None:
    rows = list(batch)
    connection.executemany(
        """
        insert into records(
            chrom, chrom_sort, pos, end, rsid, sample_index, sample_name, info_genes, info, ref, alt, qual, filter,
            is_variant, format, sample, genotype, depth, genotype_quality, offset, line_length,
            record_kind, observed_alleles
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    connection.executemany(
        """
        insert into spans(chrom, chrom_sort, pos, end, offset, sample_index)
        values (?, ?, ?, ?, ?, ?)
        """,
        [
            (row[0], row[1], row[2], row[3], row[19], row[5])
            for row in rows
            if int(row[3]) > int(row[2])
        ],
    )

def _insert_stat_rows(connection: sqlite3.Connection, stats: ActiveGenomeIndexStats) -> None:
    connection.executemany(
        "insert into stats(key, value) values(?, ?)",
        [(key, str(value)) for key, value in stats.to_dict().items()],
    )

def _rows_as_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]

def _sort_bins(rows: list[dict[str, Any]], key: str, order: list[str]) -> list[dict[str, Any]]:
    order_index = {value: index for index, value in enumerate(order)}
    return sorted(rows, key=lambda row: (order_index.get(str(row[key]), len(order)), int(row["is_variant"])))

# A whole-genome VCF has only ~25 distinct chromosome labels but tens of
# millions of records, so memoize the label→sort-key mapping instead of
# redoing the string work on every record in the parse hot path.
_CHROM_SORT_CACHE: dict[str, int] = {}

def _chrom_sort(chrom: str) -> int:
    cached = _CHROM_SORT_CACHE.get(chrom)
    if cached is not None:
        return cached
    normalized = chrom.removeprefix("chr")
    if normalized.isdigit():
        value = int(normalized)
    elif normalized == "X":
        value = 23
    elif normalized == "Y":
        value = 24
    elif normalized in ("M", "MT"):
        value = 25
    else:
        value = 10_000
    _CHROM_SORT_CACHE[chrom] = value
    return value
