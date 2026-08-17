from __future__ import annotations

import gzip
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.genomilab_ctla4_demo.executors import (
    esm_precomputed_fixture,
    proto_precomputed_fixture,
)
from scripts.genomilab_ctla4_demo.fixtures import paperclip_replay_fixture


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPOSITORY_ROOT / "scripts" / "run_genomilab_ctla4_demo.py"


class GenomiLabCTLA4DemoHarnessTests(unittest.TestCase):
    def test_public_replay_uses_verified_source_dates(self) -> None:
        records = {
            row["source_id"]: row["publication_date"]
            for row in paperclip_replay_fixture()["records"]
        }
        self.assertEqual(
            records,
            {
                "CLINGEN:CTLA4-CGGV-e79675bd": "2025-06-04",
                "PMID:29729943": "2018-05-04",
                "PMID:25367873": "2014-11-03",
                "CLINVAR:2443104": "2022-05-23",
                "PMID:25556904": "2014-12-31",
                "PMID:28159733": "2017-02-03",
                "PMID:37740092": "2023-09-23",
                "PMID:21474713": "2011-04-07",
                "PMID:26206937": "2015-07-24",
            },
        )

    def test_demo_presentation_assets_hide_context_controls_and_show_disclosure(self) -> None:
        css = (REPOSITORY_ROOT / "src/genomi/lab/static/workspace.css").read_text(
            encoding="utf-8"
        )
        html = (REPOSITORY_ROOT / "src/genomi/lab/static/index.html").read_text(
            encoding="utf-8"
        )
        runtime = (
            REPOSITORY_ROOT / "scripts/genomilab_ctla4_demo/runtime.py"
        ).read_text(encoding="utf-8")
        self.assertIn('body[data-presentation="demo"] .context-card', css)
        self.assertIn('id="demo-mode-disclosure"', html)
        self.assertIn('/demo#token=', runtime)

    def test_illustrative_result_labels_preserve_fixture_provenance(self) -> None:
        sequence_input = {
            "gene": "CTLA4",
            "transcript_accession": "NM_005214.5",
            "protein_accession": "NP_005205.2",
            "protein_substitution": "Q76H",
            "reference_sequence_sha256": "a" * 64,
            "alternate_sequence_sha256": "b" * 64,
        }
        for artifact, system in (
            (esm_precomputed_fixture(sequence_input), "ESM"),
            (proto_precomputed_fixture(sequence_input), "Proto"),
        ):
            self.assertEqual(
                artifact["model"]["name"], f"{system} illustrative demo result"
            )
            self.assertEqual(
                artifact["provenance"]["source_label"],
                f"GenomiLab {system} demonstration dataset",
            )
            self.assertEqual(
                artifact["provenance"],
                {
                    "execution_class": "precomputed_fixture",
                    "execution_location": "not_verified",
                    "network_access": "not_verified",
                    "source_label": f"GenomiLab {system} demonstration dataset",
                    "source_version": "1",
                    "source_record_id": (
                        "esm-precomputed-demo-q76h-001"
                        if system == "ESM"
                        else "proto-precomputed-demo-q76h-001"
                    ),
                },
            )

    def test_synthetic_ctla4_demo_runs_three_grounded_rounds(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="genomilab-ctla4-test-"
        ) as parent:
            run_dir = Path(parent) / "fresh-run"
            completed = self._run(run_dir)
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            report = json.loads(
                (run_dir / "final-report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["status"], "completed")
            self.assertIs(report["fixture_mode"], True)
            self.assertEqual(report["round_count"], 3)
            self.assertEqual(report["specialist_count"], 3)
            self.assertEqual(
                report["orchestration"],
                "scripted fixture walkthrough; no live specialist agents",
            )
            self.assertTrue(
                all(
                    row["status"] == "completed" and row["report_count"] == 3
                    for row in report["rounds"]
                )
            )
            self.assertTrue(
                {"candidate", "supported", "weakened", "rejected"}.issubset(
                    report["hypothesis_statuses"]
                )
            )
            self.assertEqual(
                report["paperclip_evidence"],
                {
                    "route": "fixture_replay",
                    "access_modes": ["fixture"],
                    "live_provider_execution_claimed": False,
                },
            )
            artifacts = {
                row["system"]: row for row in report["research_artifacts"]
            }
            self.assertEqual(
                artifacts["genomi"]["origin"], "verified_scientific_operation"
            )
            self.assertEqual(artifacts["esm"]["origin"], "precomputed_fixture")
            self.assertEqual(artifacts["proto"]["origin"], "precomputed_fixture")
            self.assertEqual(
                report["scientific_operations"]["esm"],
                "precomputed illustrative fixture only",
            )
            self.assertEqual(
                report["scientific_operations"]["proto"],
                "precomputed illustrative fixture only",
            )
            self.assertGreaterEqual(report["brief"]["timeline_entries"], 8)
            self.assertEqual(report["brief"]["clinician_questions"], 4)

            stages = [
                json.loads(line)["stage"]
                for line in (run_dir / "timeline.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertLess(
                stages.index("patient_followup_a"), stages.index("round_2_started")
            )
            self.assertLess(
                stages.index("round_2_complete"), stages.index("patient_followup_b")
            )
            self.assertLess(
                stages.index("round_3_targeted_request"),
                stages.index("patient_followup_c"),
            )
            self.assertLess(
                stages.index("patient_followup_c"), stages.index("round_3_started")
            )
            self.assertEqual(stages[-1], "demo_complete")
            self.assertFalse((run_dir / "launch-url.txt").exists())

            manifest = json.loads(
                (run_dir / "run-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["orchestration"], report["orchestration"])
            gencode_path = (
                run_dir
                / "private-genomi-home"
                / "reference"
                / "gencode"
                / "gencode.v49.GRCh38.annotation.gtf.gz"
            )
            with gzip.open(gencode_path, "rt", encoding="utf-8") as handle:
                gencode_text = handle.read()
            self.assertIn("exact five-gene subset of GENCODE v49", gencode_text)
            for gene_id in (
                "ENSG00000171608.19",
                "ENSG00000163599.18",
                "ENSG00000109320.15",
                "ENSG00000198589.16",
                "ENSG00000240505.9",
            ):
                self.assertIn(gene_id, gencode_text)

    def test_fixture_mode_refuses_reused_state(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="genomilab-ctla4-safety-"
        ) as parent:
            run_dir = Path(parent) / "nonempty-run"
            run_dir.mkdir()
            sentinel = run_dir / "existing.txt"
            sentinel.write_text("do not overwrite\n", encoding="utf-8")
            completed = self._run(run_dir)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "refusing to reuse nonempty demo run directory", completed.stderr
            )
            self.assertEqual(
                sentinel.read_text(encoding="utf-8"), "do not overwrite\n"
            )

    @staticmethod
    def _run(run_dir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--fixture-mode",
                "--dry-run",
                "--run-dir",
                str(run_dir),
            ],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )


if __name__ == "__main__":
    unittest.main()
