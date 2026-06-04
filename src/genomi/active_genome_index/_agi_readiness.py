from __future__ import annotations

from .vcf import iter_records
from .vcf import read_header
from collections import Counter
from pathlib import Path
from typing import Any
import json
import sqlite3
from ._agi_schema import ACTIVE_GENOME_INDEX_BUILD_STATUS_COMPLETED, ACTIVE_GENOME_INDEX_BUILD_STATUS_VARIANTS_READY, REQUIRED_QUERY_OBJECTS, SCHEMA_VERSION, _rows_as_dicts, _sort_bins, connect, connect_existing, default_active_genome_index_path


class ActiveGenomeIndexSchemaTooNew(RuntimeError):
    """Raised when an on-disk Active Genome Index was built by a newer
    Genomi runtime than the one currently importing it. The user must
    upgrade Genomi before that Active Genome Index is safe to read.

    Kept local to this module to avoid a circular import between
    active_genome_index and operations.registry; the operations layer
    catches RuntimeError and surfaces a structured envelope.
    """

class ActiveGenomeIndexIncomplete(RuntimeError):
    """Raised when an Active Genome Index is missing or has not finished
    building (no usable variants surface yet) and a capability needs to read
    it. Distinct from the schema-lifecycle errors: the fix is to (re)run
    genomi.parse_source, not to up/downgrade Genomi. The operations layer maps
    it to a structured ``active_genome_index_incomplete`` envelope so a host
    gets an actionable status instead of a raw exception — and so no capability
    has to hand-roll its own incomplete-index handling."""

def active_genome_index_summary(active_genome_index_path: str | Path) -> dict[str, Any]:
    with connect_existing(active_genome_index_path) as connection:
        readiness = _active_genome_index_readiness_from_connection(connection)
    return {
        "active_genome_index_path": str(active_genome_index_path),
        "active_genome_index_readiness": _public_active_genome_index_readiness(readiness),
        "metadata": readiness["metadata"],
        "stats": readiness["stats"],
    }

def active_genome_index_readiness(active_genome_index_path: str | Path) -> dict[str, Any]:
    path = Path(active_genome_index_path)
    if not path.exists():
        return {
            "status": "missing",
            "complete": False,
            "reason": "active_genome_index_not_found",
            "active_genome_index_path": str(path),
            "retry_operation": "genomi.parse_source",
        }
    try:
        with connect(path) as connection:
            readiness = _active_genome_index_readiness_from_connection(connection)
    except (sqlite3.Error, json.JSONDecodeError, ValueError) as exc:
        return {
            "status": "unreadable",
            "complete": False,
            "reason": "active_genome_index_unreadable",
            "error": str(exc),
            "active_genome_index_path": str(path),
            "retry_operation": "genomi.parse_source",
        }
    return _public_active_genome_index_readiness(readiness, active_genome_index_path=path)

def reference_pending(active_genome_index_path: str | Path) -> bool:
    """True when the index is variants_ready but its reference-block tail is
    still being appended (Phase B). Reference-dependent reads use this to stamp
    their result so a transient empty/negative is not read as a final answer."""
    try:
        return bool(active_genome_index_readiness(active_genome_index_path).get("variants_ready"))
    except (ActiveGenomeIndexNeedsReparse, ActiveGenomeIndexSchemaTooNew, RuntimeError):
        return False

# Guidance stamped onto a reference-dependent result while Phase B runs, so the
# host treats a negative as provisional instead of final.
REFERENCE_PENDING_NOTE = (
    "The Active Genome Index is variants_ready: every variant is queryable, but "
    "the reference-block pass is still running. A negative or zero-coverage "
    "reference answer here is provisional — do NOT treat it as final. Poll the "
    "active_genome_index.build_reference_pass job (genomi.check_background_job) "
    "or re-run this read once readiness reports 'completed'. Variant lookups are "
    "already final and need no wait."
)

# Stamped when the reference-block pass DIED (worker crashed / went stale)
# rather than merely being slow. Distinct from REFERENCE_PENDING_NOTE because
# the answer is "re-run", not "wait": a dead pass never finishes on its own, so
# polling would loop forever.
REFERENCE_PENDING_FAILED_NOTE = (
    "The Active Genome Index is variants_ready, but its reference-block pass "
    "(Phase B) STOPPED before completing — it will not finish on its own, so "
    "waiting/polling is futile. This reference answer is provisional. Re-run "
    "genomi.parse_source for this source to resume the reference tail; variant "
    "lookups are already final."
)

def ensure_active_genome_index_complete(active_genome_index_path: str | Path) -> None:
    readiness = active_genome_index_readiness(active_genome_index_path)
    if readiness.get("complete"):
        return
    # A variants_ready index is a usable read target: every variant is stored
    # and indexed, and the resolver already degrades "confirmed reference vs
    # not-callable" gracefully while the reference tail is appended. Let reads
    # through; the readiness envelope they surface carries reference_pending.
    if readiness.get("variants_ready"):
        return
    status = readiness.get("status") or "incomplete"
    reason = readiness.get("reason") or "active_genome_index_not_complete"
    if reason == "active_genome_index_needs_reparse":
        raise ActiveGenomeIndexNeedsReparse(
            f"Active Genome Index predates the current schema "
            f"(SCHEMA_VERSION={SCHEMA_VERSION}); re-run genomi.parse_source "
            "to rebuild it before any capability tool can read it."
        )
    if reason == "active_genome_index_schema_too_new":
        raise ActiveGenomeIndexSchemaTooNew(
            "Active Genome Index was written by a newer genomi runtime "
            f"than this one (SCHEMA_VERSION={SCHEMA_VERSION}); upgrade "
            "genomi before reading it."
        )
    raise ActiveGenomeIndexIncomplete(
        f"Active Genome Index is not complete ({status}: {reason}); rerun `genomi call genomi.parse_source` for this source to resume/rebuild it"
    )

def preflight(vcf_path: str | Path, *, scan_records: int = 1000) -> dict[str, Any]:
    path = Path(vcf_path)
    header = read_header(path)
    stats = Counter()
    examples: list[dict[str, Any]] = []
    for record in iter_records(path, limit=scan_records):
        stats["scanned_records"] += 1
        stats["variant_records"] += int(record.is_variant)
        stats["reference_records"] += int(not record.is_variant)
        stats[f"filter:{record.filter}"] += 1
        genotype = record.genotype
        if genotype:
            stats[f"genotype:{genotype}"] += 1
        if len(examples) < 5:
            examples.append(record.to_dict(include_raw_fields=True))
    return {
        "vcf_path": str(path),
        "size_bytes": path.stat().st_size,
        "header": header.to_dict(),
        "scan_record_limit": scan_records,
        "scan_summary": dict(stats),
        "examples": examples,
        "notes": [
            "ALT='.' records are reference or gVCF block records, not variant calls.",
            "Build an Active Genome Index before repeated rsID, region, or coverage queries.",
        ],
    }

def failure_summary(
    vcf_path: str | Path,
    active_genome_index_path: str | Path | None = None,
    *,
    example_limit: int = 5,
) -> dict[str, Any]:
    active_genome_index_path = Path(active_genome_index_path) if active_genome_index_path is not None else default_active_genome_index_path(vcf_path)
    ensure_active_genome_index_complete(active_genome_index_path)
    with connect_existing(active_genome_index_path) as connection:
        by_variant_status = _rows_as_dicts(
            connection.execute(
                """
                select
                  case when is_variant = 1 then 'variant' else 'reference_or_no_call' end as status,
                  count(*) as records
                from records
                where filter = 'FAIL'
                group by is_variant
                order by is_variant desc
                """
            )
        )
        by_genotype = _rows_as_dicts(
            connection.execute(
                """
                select genotype, is_variant, count(*) as records
                from records
                where filter = 'FAIL'
                group by genotype, is_variant
                order by records desc
                limit 20
                """
            )
        )
        by_depth = _rows_as_dicts(
            connection.execute(
                """
                select
                  case
                    when depth is null then 'null'
                    when depth < 5 then '<5'
                    when depth < 10 then '5-9'
                    when depth < 20 then '10-19'
                    when depth < 30 then '20-29'
                    else '>=30'
                  end as depth_bin,
                  is_variant,
                  count(*) as records
                from records
                where filter = 'FAIL'
                group by depth_bin, is_variant
                """
            )
        )
        by_gq = _rows_as_dicts(
            connection.execute(
                """
                select
                  case
                    when genotype_quality is null then 'null'
                    when genotype_quality = 0 then '0'
                    when genotype_quality < 20 then '1-19'
                    when genotype_quality < 50 then '20-49'
                    when genotype_quality < 100 then '50-99'
                    else '>=100'
                  end as genotype_quality_bin,
                  is_variant,
                  count(*) as records
                from records
                where filter = 'FAIL'
                group by genotype_quality_bin, is_variant
                """
            )
        )
        examples = _fail_example_rows(connection, example_limit, variants_only=False)
        variant_examples = _fail_example_rows(connection, example_limit, variants_only=True)

    return {
        "vcf_path": str(vcf_path),
        "active_genome_index_path": str(active_genome_index_path),
        "filter": "FAIL",
        "filter_description": "Did not meet quality or depth criteria",
        "by_variant_status": by_variant_status,
        "by_genotype": by_genotype,
        "by_depth": _sort_bins(by_depth, "depth_bin", ["null", "<5", "5-9", "10-19", "20-29", ">=30"]),
        "by_genotype_quality": _sort_bins(by_gq, "genotype_quality_bin", ["null", "0", "1-19", "20-49", "50-99", ">=100"]),
        "examples": examples,
        "variant_examples": variant_examples,
    }

def _fail_example_rows(connection: sqlite3.Connection, limit: int, *, variants_only: bool) -> list[dict[str, Any]]:
    """Build example FAIL record dicts straight from the structured index
    columns — no reopening of the canonical/source."""
    where = "filter = 'FAIL'" + (" and is_variant = 1" if variants_only else "")
    rows = connection.execute(
        f"""
        select chrom, pos, end, rsid, ref, alt, qual, filter, is_variant,
               genotype, depth, genotype_quality, info, format, sample, sample_index
        from records
        where {where}
        order by chrom_sort, pos
        limit ?
        """,
        (limit,),
    ).fetchall()
    examples = []
    for row in rows:
        alt = None if row["alt"] in (None, "", ".") else row["alt"]
        examples.append(
            {
                "chrom": row["chrom"],
                "pos": int(row["pos"]),
                "end": int(row["end"]),
                "id": row["rsid"],
                "rsid": row["rsid"],
                "ref": row["ref"],
                "alt": alt,
                "alts": [v for v in str(alt or "").split(",") if v],
                "qual": None if row["qual"] in (None, "", ".") else row["qual"],
                "filter": row["filter"],
                "is_variant": bool(row["is_variant"]),
                "sample_index": int(row["sample_index"] or 0),
                "genotype": row["genotype"],
                "depth": row["depth"],
                "genotype_quality": row["genotype_quality"],
                "info_raw": row["info"],
                "format_raw": row["format"],
                "sample_raw": row["sample"],
            }
        )
    return examples

def _active_genome_index_readiness_from_connection(connection: sqlite3.Connection) -> dict[str, Any]:
    objects = {
        (row["type"], row["name"])
        for row in connection.execute(
            """
            select type, name
            from sqlite_master
            where type in ('table', 'index')
            """
        )
    }
    metadata: dict[str, Any] = {}
    stats: dict[str, int] = {}
    if ("table", "metadata") in objects:
        metadata = {
            row["key"]: json.loads(row["value"])
            for row in connection.execute("select key, value from metadata")
        }
    if ("table", "stats") in objects:
        stats = {
            row["key"]: int(row["value"])
            for row in connection.execute("select key, value from stats")
        }
    missing_objects = sorted(f"{kind}:{name}" for kind, name in REQUIRED_QUERY_OBJECTS - objects)
    marker_complete = metadata.get("active_genome_index_complete") is True
    status = str(metadata.get("active_genome_index_build_status") or ("completed" if marker_complete else "unknown"))
    complete = marker_complete and status == ACTIVE_GENOME_INDEX_BUILD_STATUS_COMPLETED and not missing_objects and bool(stats)
    # A two-phase gVCF build reaches variants_ready when every variant is
    # stored and the query objects/stats exist, but the reference tail is still
    # being appended (active_genome_index_complete stays False). It is queryable
    # for variants now; only "confirmed reference vs not-callable" is provisional.
    variants_ready = (
        not complete
        and status == ACTIVE_GENOME_INDEX_BUILD_STATUS_VARIANTS_READY
        and not missing_objects
        and bool(stats)
    )
    reason = None
    if not complete and not variants_ready:
        if not marker_complete:
            reason = "completion_marker_missing_or_false"
        elif status != ACTIVE_GENOME_INDEX_BUILD_STATUS_COMPLETED:
            reason = "build_status_not_completed"
        elif missing_objects:
            reason = "query_objects_missing"
        elif not stats:
            reason = "stats_missing"
        else:
            reason = "active_genome_index_not_complete"
    elif variants_ready:
        reason = "reference_pass_pending"
    else:
        # Even a structurally complete Active Genome Index is unusable if its
        # schema_version doesn't match the runtime. Downgrade readiness so
        # ensure_active_genome_index_complete (and every query path that funnels through
        # it) raises the lifecycle exception.
        schema_compat = check_agi_schema_compatibility(connection)
        if schema_compat == AGI_SCHEMA_NEEDS_REPARSE:
            complete = False
            status = "needs_reparse"
            reason = "active_genome_index_needs_reparse"
        elif schema_compat == AGI_SCHEMA_TOO_NEW:
            complete = False
            status = "schema_too_new"
            reason = "active_genome_index_schema_too_new"
    return {
        "complete": complete,
        "variants_ready": variants_ready,
        "status": ACTIVE_GENOME_INDEX_BUILD_STATUS_COMPLETED if complete else status,
        "reason": reason,
        "metadata": metadata,
        "stats": stats,
        "objects": objects,
        "missing_objects": missing_objects,
    }

def _public_active_genome_index_readiness(readiness: dict[str, Any], *, active_genome_index_path: Path | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": readiness.get("status") or "unknown",
        "complete": bool(readiness.get("complete")),
        "variants_ready": bool(readiness.get("variants_ready")),
        "reason": readiness.get("reason"),
        "missing_objects": list(readiness.get("missing_objects") or []),
        "retry_operation": "genomi.parse_source",
    }
    if result["variants_ready"] and not result["complete"]:
        result["reference_pending"] = True
        # Reconcile the SQLite state against the Phase B job: variants_ready only
        # means the reference tail had not landed *as of the last write*. If the
        # worker that was appending it died, the index would sit at variants_ready
        # forever — so surface the job's liveness instead of an open-ended "still
        # running". A dead worker turns the provisional note into a retry.
        # `retry_operation` is already genomi.parse_source in the base result.
        # The two notes are the single source of this wording (the chokepoint
        # relays whatever we set here — it composes no message of its own).
        job_status = _reference_pass_job_status(readiness.get("metadata") or {})
        if job_status is not None:
            result["reference_pass"] = job_status
        if job_status is not None and job_status.get("status") == "failed":
            result["reference_pass_failed"] = True
            result["note"] = REFERENCE_PENDING_FAILED_NOTE
        else:
            result["note"] = REFERENCE_PENDING_NOTE
    if active_genome_index_path is not None:
        result["active_genome_index_path"] = str(active_genome_index_path)
    return result


def _reference_pass_job_status(metadata: dict[str, Any]) -> dict[str, Any] | None:
    """The public status of the Phase B job recorded on this index, if any.

    Returns None when no job id was persisted (e.g. an inline reference pass, or
    an index built before this field existed). read_job lazily flips a worker
    that died or went stale to `failed`, so a crashed Phase B shows up as failed
    here rather than as a perpetually-running job.
    """
    job_id = metadata.get("reference_pass_job_id")
    if not job_id:
        return None
    try:
        from ..runtime import background_jobs

        job = background_jobs.read_job(job_id=str(job_id))
        return background_jobs.public_job_status(job)
    except Exception:
        return None

AGI_SCHEMA_CURRENT = "current"

AGI_SCHEMA_NEEDS_REPARSE = "needs_reparse"

AGI_SCHEMA_TOO_NEW = "too_new"

class ActiveGenomeIndexNeedsReparse(RuntimeError):
    """Raised when an on-disk Active Genome Index predates the current
    schema and must be rebuilt via `genomi.parse_source` before any
    capability tool can read it. Kept local to this module to avoid a
    circular import with operations.registry; the operations layer
    catches RuntimeError and surfaces a structured envelope.
    """

def canonical_source_for_active_genome_index(connection: sqlite3.Connection) -> Path:
    """Return the path to the Active Genome Index-owned canonical bgzip VCF.

    Schema v3 stores this as `metadata.vcf_path` (the path passed into
    `create_active_genome_index`, which `_parse_vcf_active_genome_index` populates from
    `build_canonical_bgzip`). This is the deferred reference pass's source: Phase B
    re-opens it via `pysam.libcbgzf.BGZFile` to append the reference-block tail,
    then reclaims it. Capability tools never read it — they read the SQLite index.

    This is also the lifecycle gate. Every capability tool resolves
    through here, so we enforce schema-version compatibility once:
    older Active Genome Indexes raise `ActiveGenomeIndexNeedsReparse`;
    newer ones raise `ActiveGenomeIndexSchemaTooNew`. The same `< / == / >`
    compatibility rule is used by `_cached_active_genome_index_if_usable`.
    """

    compatibility = check_agi_schema_compatibility(connection)
    if compatibility == AGI_SCHEMA_NEEDS_REPARSE:
        raise ActiveGenomeIndexNeedsReparse(
            f"Active Genome Index predates the current schema "
            f"(SCHEMA_VERSION={SCHEMA_VERSION}); re-run genomi.parse_source "
            "to rebuild it before any capability tool can read it."
        )
    if compatibility == AGI_SCHEMA_TOO_NEW:
        raise ActiveGenomeIndexSchemaTooNew(
            f"Active Genome Index was built by a newer Genomi runtime than "
            f"this one (current SCHEMA_VERSION={SCHEMA_VERSION}). Upgrade "
            "Genomi before reading this Active Genome Index."
        )

    row = connection.execute(
        "select value from metadata where key = 'vcf_path'"
    ).fetchone()
    if row is None:
        raise ActiveGenomeIndexNeedsReparse(
            "Active Genome Index has no canonical source path; re-parse with genomi.parse_source."
        )
    return Path(json.loads(row[0]))

def check_agi_schema_compatibility(connection: sqlite3.Connection) -> str:
    """Compare the stored Active Genome Index schema_version to the runtime's
    current SCHEMA_VERSION.

    Returns one of:
    - AGI_SCHEMA_CURRENT: stored == current; safe to read.
    - AGI_SCHEMA_NEEDS_REPARSE: stored < current; the Active Genome Index predates the
      runtime, must be rebuilt via genomi.parse_source.
    - AGI_SCHEMA_TOO_NEW: stored > current; the runtime predates the Active Genome Index,
      the user must upgrade Genomi before this Active Genome Index is safe to read.
    """

    cursor = connection.execute(
        "select value from metadata where key = 'schema_version'"
    )
    row = cursor.fetchone()
    if row is None:
        return AGI_SCHEMA_NEEDS_REPARSE
    try:
        stored = int(json.loads(row[0]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return AGI_SCHEMA_NEEDS_REPARSE
    if stored < SCHEMA_VERSION:
        return AGI_SCHEMA_NEEDS_REPARSE
    if stored > SCHEMA_VERSION:
        return AGI_SCHEMA_TOO_NEW
    return AGI_SCHEMA_CURRENT
