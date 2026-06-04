from __future__ import annotations

import contextlib
import shutil
from pathlib import Path
from typing import Any

from ...runtime.paths import (
    run_evidence_db_path_for_source,
    run_evidence_dir_for_source,
    run_project_dir_for_source,
    run_reference_dir_for_source,
    run_work_dir_for_source,
    sample_slug_from_source,
    shared_evidence_db_path,
)
from ...runtime.static_dependencies import resolve_genome_build
from ..active_genome_index import (
    active_genome_index_readiness,
    append_reference_pass,
    connect_existing,
    create_active_genome_index,
    default_active_genome_index_path,
)
from .._agi_schema import _upsert_metadata
from ..canonical import build_canonical_bgzip
from .agi_store import SOURCE_PARSE_SCHEMA, JsonObject, _init_source_evidence_db
from .detection import SourceDetection
from .text_io import open_genomic_binary


def _parse_vcf_active_genome_index(
    source_path: Path,
    *,
    detection: SourceDetection,
    evidence_db: str | Path | None,
    source_evidence_db: str | Path | None,
    shared_evidence_db: str | Path | None,
    genome_build: str,
    force: bool,
    max_records: int | None,
    parallel_workers: int | None,
) -> JsonObject:
    effective_build = resolve_genome_build(source_path, genome_build)
    project_dir = run_project_dir_for_source(source_path, source_format=detection.source_format)
    work_dir = run_work_dir_for_source(source_path, source_format=detection.source_format)
    evidence_dir = run_evidence_dir_for_source(source_path, source_format=detection.source_format)
    reference_dir = run_reference_dir_for_source(source_path, source_format=detection.source_format)
    db_path = Path(evidence_db) if evidence_db is not None else run_evidence_db_path_for_source(source_path, source_format=detection.source_format)
    shared_db = Path(shared_evidence_db) if shared_evidence_db is not None else shared_evidence_db_path()
    active_genome_index_path = default_active_genome_index_path(source_path)

    project_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)
    _init_source_evidence_db(
        db_path,
        source_path,
        source_format=detection.source_format,
        source_evidence_db=source_evidence_db,
        shared_evidence_db=shared_db,
    )
    # Every source parses in two phases on one unified path: Phase A stores
    # every variant and returns variants_ready (the whole interpretation surface
    # is live in minutes); Phase B appends the reference-block tail. A gVCF is
    # ~96% reference blocks so its tail is the bulk of the work; a plain VCF's
    # reference tail (homref/no-call rows) is tiny and Phase B finishes almost
    # immediately — but it travels the same code path either way. Only a
    # capped/forced build (max_records) stays single-phase, since there is no
    # stable reference tail to defer.
    readiness = active_genome_index_readiness(active_genome_index_path)
    two_phase = max_records is None
    reference_job: JsonObject | None = None
    if two_phase and readiness.get("variants_ready") and not readiness.get("complete") and not force:
        # Phase A already done from a prior call; just make sure the reference
        # tail is (still) being built instead of rebuilding variants.
        active_genome_index_result = {
            "status": "variants_ready",
            "active_genome_index_complete": False,
            "reference_pending": True,
            "active_genome_index_path": str(active_genome_index_path),
        }
        reference_job = _enqueue_reference_pass(active_genome_index_path, parallel_workers)
    else:
        intake_for_canonical = _materialize_vcf_intake_for_canonical(source_path, detection=detection, work_dir=work_dir, force=force)
        try:
            canonical_result = build_canonical_bgzip(intake_for_canonical, work_dir, force=force)
        finally:
            if intake_for_canonical != source_path:
                with contextlib.suppress(FileNotFoundError):
                    intake_for_canonical.unlink()
        canonical_path = Path(canonical_result["canonical_path"])
        active_genome_index_result = create_active_genome_index(
            canonical_path,
            active_genome_index_path,
            include_reference=True,
            max_records=max_records,
            parallel_workers=parallel_workers,
            reuse_existing=not force,
            defer_reference=two_phase,
        )
        # The canonical the index adopted as its source of record
        # (metadata.vcf_path) must outlive this call: a deferred reference pass
        # (Phase B) reads it, and every resume reuses it. So drop only a
        # *redundant* work-dir copy — present when create_active_genome_index
        # materialized its own separate per-index canonical (a different path).
        # When the index adopted this very file, keep it: Phase B reclaims it
        # once the reference tail lands. A single-phase complete build has no
        # later reader, so its canonical is disposable right away.
        index_canonical = Path(str(active_genome_index_result.get("vcf_path") or ""))
        if active_genome_index_result.get("status") == "variants_ready":
            _discard_canonical(canonical_path, keep=index_canonical)
            reference_job = _enqueue_reference_pass(active_genome_index_path, parallel_workers)
        else:
            _discard_canonical(canonical_path, keep=None)
            _discard_canonical(index_canonical, keep=None)
    outputs: dict[str, Any] = {"active_genome_index_path": str(active_genome_index_path)}
    if reference_job is not None:
        outputs["reference_pass_job_id"] = reference_job.get("job_id")
        outputs["reference_pass_job_path"] = reference_job.get("job_path")
    return {
        "schema": SOURCE_PARSE_SCHEMA,
        "workflow_area": "active-genome-index",
        "status": "completed",
        "source": str(source_path),
        "vcf": str(source_path),
        "source_format": detection.source_format,
        "source_kind": detection.source_kind,
        "provider": detection.provider,
        "annotation_scope": "active_genome_index",
        "sample_slug": sample_slug_from_source(source_path, source_format=detection.source_format),
        "genome_build": effective_build,
        "evidence_db": str(db_path),
        "shared_evidence_db": str(shared_db),
        "project_dir": str(project_dir),
        "work_dir": str(work_dir),
        "evidence_dir": str(evidence_dir),
        "reference_dir": str(reference_dir),
        "outputs": outputs,
        "steps": [
            {
                "name": "build-active-genome-index",
                "result": active_genome_index_result,
                "reason": "The VCF/gVCF is digitized into an Active Genome Index for targeted sample lookup.",
            }
        ],
        "warnings": [],
    }


def _discard_canonical(path: Path, *, keep: Path | None) -> None:
    """Unlink a canonical bgzip (and its .gzi) unless it is the file to keep.

    `keep` is the canonical the index adopted as metadata.vcf_path; never delete
    that one here — Phase B (or a resume) still needs it.
    """
    if path == Path(""):
        return
    try:
        if keep is not None and path.resolve() == keep.resolve():
            return
    except OSError:
        if keep is not None and str(path) == str(keep):
            return
    for stale in (path, Path(str(path) + ".gzi")):
        with contextlib.suppress(FileNotFoundError):
            stale.unlink()


def _materialize_vcf_intake_for_canonical(
    source_path: Path,
    *,
    detection: SourceDetection,
    work_dir: Path,
    force: bool,
) -> Path:
    """Return a VCF-like file path that `build_canonical_bgzip` can read.

    Detection peels zip/tar archives to classify their genomic member. The
    canonical builder works on bare files, so archive-backed VCF/gVCF sources
    need the selected member streamed to a temporary plain VCF first. Bare
    gzip/bzip2/xz VCFs stay on the fast path and are handled by the canonical
    builder's compression sniffing.
    """
    if detection.member_name is None:
        return source_path
    extracted = work_dir / "source" / "selected-archive-member.vcf"
    if extracted.exists() and not force:
        return extracted
    extracted.parent.mkdir(parents=True, exist_ok=True)
    tmp = extracted.with_suffix(extracted.suffix + ".tmp")
    with open_genomic_binary(source_path, member_name=detection.member_name) as source, tmp.open("wb") as output:
        shutil.copyfileobj(source, output)
    tmp.replace(extracted)
    return extracted


def _enqueue_reference_pass(active_genome_index_path: Path, parallel_workers: int | None) -> JsonObject | None:
    """Run Phase B (the reference-block tail) — inline or as a detached job.

    When background jobs are disabled (the synchronous test/CLI default), run
    the reference pass inline so the index reaches `completed` within this call.
    Otherwise launch it through the standard job machinery (job_id, heartbeat,
    dead-worker detection, check_background_job polling); start_operation_job
    dedups on operation+params, so a duplicate parse_source call attaches to the
    running reference job instead of starting a second one, and we persist the
    job_id onto the index so readiness can later report whether that worker is
    alive, done, or dead. Best-effort throughout: if Phase B can't be launched
    the variants_ready index is still fully usable, so we swallow rather than
    fail the parse.
    """
    from ...runtime import background_jobs

    if not background_jobs.background_enabled():
        with contextlib.suppress(Exception):
            append_reference_pass(active_genome_index_path, parallel_workers=parallel_workers)
        return None

    params: JsonObject = {"active_genome_index_path": str(active_genome_index_path)}
    if parallel_workers is not None:
        params["parallel_workers"] = parallel_workers
    try:
        job = background_jobs.start_operation_job("active_genome_index.build_reference_pass", params)
    except Exception:
        return None
    _record_reference_pass_job(active_genome_index_path, job)
    return job


def _record_reference_pass_job(active_genome_index_path: Path, job: JsonObject | None) -> None:
    """Persist the reference-pass job id onto the index so readiness can find it.

    Lets active_genome_index_readiness tell a still-running Phase B from a dead
    one (instead of reporting reference_pending forever). Best-effort.
    """
    if not isinstance(job, dict):
        return
    job_id = job.get("job_id")
    if not job_id:
        return
    try:
        with connect_existing(active_genome_index_path) as connection:
            _upsert_metadata(connection, "reference_pass_job_id", str(job_id))
            job_path = job.get("job_path")
            if job_path:
                _upsert_metadata(connection, "reference_pass_job_path", str(job_path))
            connection.commit()
    except Exception:
        pass
