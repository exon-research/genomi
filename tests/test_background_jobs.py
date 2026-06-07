from __future__ import annotations

from genomi.runtime import background_jobs
from genomi.runtime import context as runtime_context

from tests.support.runtime.genomi import GenomiRuntimeTestCase


class BackgroundJobTests(GenomiRuntimeTestCase):
    def test_digest_includes_active_agi_for_private_reads(self) -> None:
        agi_a = {
            "agi_id": "agi-a",
            "sample_slug": "sample-a",
            "status": "parsed",
            "agi_path": str(self.genomi_home / "a.active-genome-index.sqlite"),
        }
        agi_b = {
            "agi_id": "agi-b",
            "sample_slug": "sample-b",
            "status": "parsed",
            "agi_path": str(self.genomi_home / "b.active-genome-index.sqlite"),
        }
        runtime_context.save_registry({"agis": {"agi-a": agi_a, "agi-b": agi_b}, "users": {}})
        runtime_context.save_context({"active_agi_id": "agi-a", "agis": {"agi-a": agi_a, "agi-b": agi_b}})
        direct_a = background_jobs.operation_params_digest("active_genome_index.summarize", {})
        invoke_a = background_jobs.operation_params_digest(
            "genomi.invoke",
            {"tool": "decode.build_dashboard_evidence", "params": {}},
        )

        runtime_context.save_context({"active_agi_id": "agi-b", "agis": {"agi-a": agi_a, "agi-b": agi_b}})
        direct_b = background_jobs.operation_params_digest("active_genome_index.summarize", {})
        invoke_b = background_jobs.operation_params_digest(
            "genomi.invoke",
            {"tool": "decode.build_dashboard_evidence", "params": {}},
        )

        self.assertNotEqual(direct_a, direct_b)
        self.assertNotEqual(invoke_a, invoke_b)
        self.assertEqual(
            background_jobs.operation_params_digest("genomi.list_resources", {}),
            background_jobs.operation_params_digest("genomi.list_resources", {}),
        )

    def test_find_latest_job_filters_by_status_and_digest(self) -> None:
        digest = background_jobs.operation_params_digest("pharmacogenomics.run_pharmcat", {"agi_id": "agi-a"})
        root = background_jobs.jobs_dir()
        older = {
            "job_id": "older",
            "operation": "pharmacogenomics.run_pharmcat",
            "params_digest": digest,
            "status": "completed",
            "created_at": "2026-06-07T00:00:00+00:00",
        }
        newer = {
            "job_id": "newer",
            "operation": "pharmacogenomics.run_pharmcat",
            "params_digest": digest,
            "status": "completed",
            "created_at": "2026-06-07T00:01:00+00:00",
        }
        running = {
            "job_id": "running",
            "operation": "pharmacogenomics.run_pharmcat",
            "params_digest": digest,
            "status": "running",
            "created_at": "2026-06-07T00:02:00+00:00",
        }
        background_jobs.write_job(root / "older.json", older)
        background_jobs.write_job(root / "newer.json", newer)
        background_jobs.write_job(root / "running.json", running)

        completed = background_jobs.find_latest_job(
            "pharmacogenomics.run_pharmcat",
            digest,
            statuses={"completed"},
        )
        active = background_jobs.find_active_job("pharmacogenomics.run_pharmcat", digest)

        self.assertEqual(completed["job_id"], "newer")
        self.assertEqual(active["job_id"], "running")
