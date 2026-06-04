from __future__ import annotations

import os
import tempfile
from pathlib import Path

from _genomi_runtime_helpers import GenomiRuntimeTestCase

from genomi.active_genome_index.active_genome_index import (
    active_genome_index_readiness,
    append_reference_pass,
    connect_existing,
    create_active_genome_index,
)
from genomi.active_genome_index._agi_schema import _upsert_metadata
from genomi.active_genome_index.canonical import canonical_paths_for_active_genome_index
from genomi.operations.registry import agi_access
from genomi.operations.registry.table import _stamp_reference_pending_if_due
from genomi.runtime import background_jobs
from genomi.runtime import context as runtime_context
from genomi.runtime.external import utc_now


def _write_gvcf(path: Path) -> None:
    """A gVCF: variant rows every 500 bp, reference-confidence blocks between."""
    with path.open("w", encoding="utf-8") as handle:
        handle.write("##fileformat=VCFv4.2\n")
        handle.write('##INFO=<ID=END,Number=1,Type=Integer,Description="End">\n')
        handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n")
        for pos in range(1, 6001):
            if pos % 500 == 0:
                handle.write(f"1\t{pos}\trs{pos}\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/1:42:99\n")
            else:
                handle.write(f"1\t{pos}\t.\tA\t<NON_REF>\t.\tPASS\tEND={pos}\tGT:DP:GQ\t0/0:35:50\n")


def _set_reference_job(index: Path, *, status: str, pid: int | None, fresh_heartbeat: bool) -> str:
    """Record a fake Phase B job on the index and on disk, return its job_id."""
    job_id = f"active-genome-index-build-reference-pass-test-{status}"
    job_path = background_jobs.jobs_dir() / f"{job_id}.json"
    now = utc_now()
    job = {
        "schema": background_jobs.JOB_SCHEMA,
        "job_id": job_id,
        "operation": "active_genome_index.build_reference_pass",
        "params": {"agi_path": str(index)},
        "params_digest": background_jobs.operation_params_digest(
            "active_genome_index.build_reference_pass", {"agi_path": str(index)}
        ),
        "status": status,
        "pid": pid,
        "started_at": now,
        "heartbeat_at": now if fresh_heartbeat else "2000-01-01T00:00:00+00:00",
        "created_at": now,
        "updated_at": now,
    }
    if status == "failed":
        job["error"] = {"code": "needs_file", "message": "canonical.vcf.gz missing"}
    background_jobs.write_job(job_path, job)
    with connect_existing(index) as connection:
        _upsert_metadata(connection, "reference_pass_job_id", job_id)
        connection.commit()
    return job_id


class ReferencePassObservabilityTests(GenomiRuntimeTestCase):
    """Readiness reconciles the variants_ready state against the Phase B job, so
    a dead reference pass surfaces as failed instead of pending forever."""

    def _build_variants_ready(self, tmp: Path) -> Path:
        vcf = tmp / "s.vcf"
        index = tmp / "s.sqlite"
        _write_gvcf(vcf)
        result = create_active_genome_index(vcf, index, parallel_workers=4, defer_reference=True)
        self.assertEqual(result["status"], "variants_ready")
        return index

    def test_failed_reference_job_turns_pending_into_retry(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            index = self._build_variants_ready(Path(raw))
            _set_reference_job(index, status="failed", pid=None, fresh_heartbeat=False)

            readiness = active_genome_index_readiness(index)
            self.assertTrue(readiness["reference_pending"])
            self.assertTrue(readiness["reference_pass_failed"])
            self.assertEqual(readiness["retry_operation"], "genomi.parse_source")
            self.assertEqual(readiness["reference_pass"]["status"], "failed")
            self.assertIn("re-run", readiness["note"].lower())

    def test_dead_worker_without_status_is_detected_as_failed(self) -> None:
        # status still "running", but the pid is gone and the heartbeat is
        # ancient — read_job must flip it to failed via staleness detection.
        with tempfile.TemporaryDirectory() as raw:
            index = self._build_variants_ready(Path(raw))
            _set_reference_job(index, status="running", pid=2_000_000_000, fresh_heartbeat=False)

            readiness = active_genome_index_readiness(index)
            self.assertTrue(readiness.get("reference_pass_failed"))

    def test_live_reference_job_stays_provisional_not_failed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            index = self._build_variants_ready(Path(raw))
            # This very test process is alive and the heartbeat is fresh.
            _set_reference_job(index, status="running", pid=os.getpid(), fresh_heartbeat=True)

            readiness = active_genome_index_readiness(index)
            self.assertTrue(readiness["reference_pending"])
            self.assertFalse("reference_pass_failed" in readiness)
            self.assertEqual(readiness["reference_pass"]["status"], "in_progress")

    def test_completed_index_drops_reference_pending(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            index = self._build_variants_ready(Path(raw))
            append_reference_pass(index)
            readiness = active_genome_index_readiness(index)
            self.assertTrue(readiness["complete"])
            self.assertFalse("reference_pending" in readiness)
            self.assertFalse("reference_pass_failed" in readiness)


class ReferencePassCanonicalLifecycleTests(GenomiRuntimeTestCase):
    """Phase B owns the canonical's lifecycle: it survives until the reference
    tail lands (regression for the parse deleting it too early), then is reclaimed."""

    def test_canonical_survives_until_phase_b_then_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            vcf = Path(raw) / "s.vcf"
            index = Path(raw) / "s.sqlite"
            _write_gvcf(vcf)
            create_active_genome_index(vcf, index, parallel_workers=4, defer_reference=True)

            canonical, _gzi = canonical_paths_for_active_genome_index(index)
            # The canonical the index recorded must still exist for Phase B to read.
            self.assertTrue(canonical.exists(), "canonical must survive Phase A for the reference pass")

            append_reference_pass(index)
            # Phase B is the canonical's sole post-parse reader; once it lands the
            # reference tail, the bgzip is reclaimed.
            self.assertFalse(canonical.exists(), "canonical should be reclaimed after Phase B completes")
            self.assertFalse(Path(str(canonical) + ".gzi").exists())


class ReferencePassChokepointTests(GenomiRuntimeTestCase):
    """A reference-dependent read learns the tail's state at the moment it runs,
    so the host never has to guess when to poll. A dead pass turns the stamp from
    'still running, wait' into 'failed, re-run'."""

    def _active_variants_ready(self) -> Path:
        vcf = self.genomi_home / "active.vcf"
        vcf.parent.mkdir(parents=True, exist_ok=True)
        index = vcf.with_suffix(".sqlite")
        _write_gvcf(vcf)
        create_active_genome_index(vcf, index, parallel_workers=4, defer_reference=True)
        runtime_context.set_active_agi_from_source(
            vcf, status="parsed", agi_path=index, genome_build="GRCh38"
        )
        runtime_context.approve_agi_access(reason="test approved Active Genome Index access")
        return index

    def test_running_pass_stamps_wait(self) -> None:
        index = self._active_variants_ready()
        _set_reference_job(index, status="running", pid=os.getpid(), fresh_heartbeat=True)
        result = _stamp_reference_pending_if_due(
            "active_genome_index.classify_region_callability", {}, {"ok": True}
        )
        self.assertTrue(result["reference_pending"])
        self.assertFalse("reference_pending_failed" in result)
        self.assertFalse("retry_operation" in result)

    def test_dead_pass_stamps_rerun_not_wait(self) -> None:
        index = self._active_variants_ready()
        _set_reference_job(index, status="failed", pid=None, fresh_heartbeat=False)

        state = agi_access.reference_state_for_call({})
        self.assertTrue(state["failed"])

        result = _stamp_reference_pending_if_due(
            "active_genome_index.classify_region_callability", {}, {"ok": True}
        )
        self.assertTrue(result["reference_pending"])
        self.assertTrue(result["reference_pending_failed"])
        self.assertEqual(result["retry_operation"], "genomi.parse_source")
        self.assertIn("re-run", result["reference_pending_note"].lower())

    def test_non_reference_op_is_not_stamped(self) -> None:
        index = self._active_variants_ready()
        _set_reference_job(index, status="failed", pid=None, fresh_heartbeat=False)
        # variant.resolve is variant-need: its rows are final at variants_ready,
        # so it must never carry a reference_pending stamp.
        result = _stamp_reference_pending_if_due("variant.resolve", {}, {"ok": True})
        self.assertFalse("reference_pending" in result)


if __name__ == "__main__":
    import unittest

    unittest.main()
