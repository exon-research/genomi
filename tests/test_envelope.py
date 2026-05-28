from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from genomi.capabilities.clinvar import materialization as mat
from genomi.evidence import envelope as env


class EnvelopeConstructorTests(unittest.TestCase):
    def test_evidence_present_supports_scoped_answer(self) -> None:
        e = env.evidence_present(
            operation="variant.resolve",
            observations={"observation_count": 2},
        )
        self.assertEqual(e["schema"], "genomi-evidence-envelope-v1")
        self.assertEqual(e["finding_state"], "evidence_present")
        self.assertEqual(e["answer_readiness"], "answer_supported")
        self.assertFalse(e["negative_inference"]["allowed"])
        self.assertTrue(e["guidance"])

    def test_empty_consulted_scope_disallows_negative_inference(self) -> None:
        e = env.empty_consulted_scope(
            operation="phenotype.plan_risk_investigation",
            query_scope={"context_scope": "active_genome_index_selected"},
        )
        self.assertEqual(e["finding_state"], "not_observed_in_consulted_scope")
        self.assertEqual(e["answer_readiness"], "scoped_answer_only")
        self.assertFalse(e["negative_inference"]["allowed"])
        self.assertIn("library_coverage", e["negative_inference"]["requires"])
        self.assertIn("not_observed_in_consulted_scope:do_not_imply_clinical_negative", e["guidance"])
        self.assertIn("negative_inference_disallowed:do_not_state_clinical_negative", e["guidance"])

    def test_missing_library_returns_install_action(self) -> None:
        e = env.missing_library(
            operation="clinvar.scan_candidates",
            library="clinvar-grch38",
            library_status_payload={
                "title": "ClinVar VCF cache for GRCh38",
                "install_command": "python3 scripts/install_for_agents.py --libraries clinvar-grch38",
                "helps": "enables exact ClinVar allele matching",
            },
            intent="broad genetic disease triage",
        )
        self.assertEqual(e["finding_state"], "blocked_missing_library")
        self.assertEqual(e["answer_readiness"], "needs_user_install")
        self.assertFalse(e["negative_inference"]["allowed"])
        install_action = next(a for a in e["next_actions"] if a.get("action") == "install_library")
        self.assertEqual(install_action["library"], "clinvar-grch38")
        self.assertIn("install_for_agents", install_action["install_command"])

    def test_materialization_pending_emits_wait_action(self) -> None:
        e = env.materialization_pending(
            operation="clinvar.scan_candidates",
            library="clinvar-grch38",
            materialization={
                "status": "running",
                "started_at": "2026-05-20T00:00:00Z",
                "completed_at": None,
                "agi_id": "genome-x",
                "library_version": "v1",
                "inputs_hash": "abc",
                "job_id": "job-1",
                "materialization_id": "mat-1",
            },
        )
        self.assertEqual(e["finding_state"], "materialization_incomplete")
        self.assertEqual(e["answer_readiness"], "needs_materialization")
        self.assertFalse(e["negative_inference"]["allowed"])
        self.assertEqual(e["next_actions"][-1]["action"], "wait_for_materialization")

    def test_not_assessed_records_reason(self) -> None:
        e = env.not_assessed(operation="x", reason="ambiguous query")
        self.assertEqual(e["finding_state"], "not_assessed")
        self.assertEqual(e["answer_readiness"], "cannot_answer_yet")

    def test_true_negative_requires_full_baseline(self) -> None:
        with self.assertRaises(env.EnvelopeValidationError):
            env.true_negative_supported(
                operation="x",
                satisfied_requirements=["callability"],  # missing baseline
            )
        e = env.true_negative_supported(
            operation="x",
            satisfied_requirements=[
                env.REQ_CALLABILITY,
                env.REQ_LIBRARY_COVERAGE,
                env.REQ_GENOTYPE_SUPPORT,
                env.REQ_SCOPE_ALIGNMENT,
            ],
        )
        self.assertTrue(e["negative_inference"]["allowed"])


class EnvelopeValidatorTests(unittest.TestCase):
    def test_evidence_present_with_install_state_is_invalid(self) -> None:
        with self.assertRaises(env.EnvelopeValidationError):
            env.envelope(
                operation="x",
                finding_state=env.EVIDENCE_PRESENT,
                answer_readiness=env.NEEDS_USER_INSTALL,
            )

    def test_blocked_missing_library_requires_needs_user_install(self) -> None:
        with self.assertRaises(env.EnvelopeValidationError):
            env.envelope(
                operation="x",
                finding_state=env.BLOCKED_MISSING_LIBRARY,
                answer_readiness=env.SCOPED_ANSWER_ONLY,
            )

    def test_not_observed_must_disallow_negative_inference(self) -> None:
        with self.assertRaises(env.EnvelopeValidationError):
            env.envelope(
                operation="x",
                finding_state=env.NOT_OBSERVED_IN_CONSULTED_SCOPE,
                answer_readiness=env.SCOPED_ANSWER_ONLY,
                negative_inference={"allowed": True, "requires": [], "satisfied": []},
            )

    def test_unknown_finding_state_raises(self) -> None:
        with self.assertRaises(env.EnvelopeValidationError):
            env.envelope(operation="x", finding_state="invented", answer_readiness=env.CANNOT_ANSWER_YET)


class MaterializationRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_lookup_or_init_creates_then_reuses(self) -> None:
        first, created = mat.lookup_or_init(
            agi_id="genome-1",
            library_id="clinvar-grch38",
            inputs={"sample": "demo"},
            root=self.root,
        )
        self.assertTrue(created)
        self.assertEqual(first["status"], mat.QUEUED)
        again, created2 = mat.lookup_or_init(
            agi_id="genome-1",
            library_id="clinvar-grch38",
            inputs={"sample": "demo"},
            root=self.root,
        )
        self.assertFalse(created2)
        self.assertEqual(again["inputs_hash"], first["inputs_hash"])

    def test_complete_manifest_with_missing_artifacts_flips_to_stale(self) -> None:
        manifest, _ = mat.lookup_or_init(
            agi_id="genome-1",
            library_id="clinvar-grch38",
            inputs={"sample": "demo"},
            root=self.root,
        )
        mat.mark_complete(manifest, artifact_paths=["/tmp/this-does-not-exist.sqlite"])
        again, _ = mat.lookup_or_init(
            agi_id="genome-1",
            library_id="clinvar-grch38",
            inputs={"sample": "demo"},
            root=self.root,
        )
        self.assertEqual(again["status"], mat.STALE)

    def test_library_use_snapshot_matches_status(self) -> None:
        manifest, _ = mat.lookup_or_init(
            agi_id="genome-2",
            library_id="pgx-artifacts",
            inputs={"drug": "clopidogrel"},
            root=self.root,
        )
        running = mat.mark_running(manifest, job_id="job-x")
        snap = mat.library_use_from_manifest(running)
        self.assertEqual(snap["library"], "pgx-artifacts")
        self.assertEqual(snap["state"], "materializing")
        complete = mat.mark_complete(running, artifact_paths=[])
        snap2 = mat.library_use_from_manifest(complete)
        self.assertEqual(snap2["state"], "complete")


class RiskRegressionTests(unittest.TestCase):
    """Plan-mandated regression: broad triage with zero ClinVar candidates."""

    def test_broad_risk_zero_candidates_does_not_assert_negative(self) -> None:
        # Use the risk module directly; mirrors the explicit plan ask.
        import tempfile as _tempfile
        from pathlib import Path as _Path

        from genomi.capabilities.phenotype.risk import prepare_risk_investigation
        from genomi.evidence import import_clinvar_vcf

        DATA_DIR = _Path(__file__).parent / "data"
        with _tempfile.TemporaryDirectory() as tmp:
            db = _Path(tmp) / "evidence.sqlite"
            matches = _Path(tmp) / "matches.jsonl"
            import_clinvar_vcf(DATA_DIR / "tiny.clinvar.vcf", db, source_version="fixture")
            matches.write_text("", encoding="utf-8")
            result = prepare_risk_investigation(
                db,
                question="anything I should worry about?",
                matches=matches,
                investigation_type="cancer_risk",
            )
        e = result["evidence_envelope"]
        self.assertEqual(e["finding_state"], "not_observed_in_consulted_scope")
        self.assertFalse(e["negative_inference"]["allowed"])
        # Guidance is typed codes, never prose.
        self.assertIn("not_observed_in_consulted_scope:do_not_imply_clinical_negative", e["guidance"])
        self.assertIn("negative_inference_disallowed:do_not_state_clinical_negative", e["guidance"])
        for g in e["guidance"]:
            self.assertNotIn(" ", g, f"guidance must be code, got prose: {g!r}")


if __name__ == "__main__":
    unittest.main()
