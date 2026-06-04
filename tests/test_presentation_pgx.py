from __future__ import annotations

import unittest

from genomi.interfaces.presentation import present_result


class PgxPresentationTests(unittest.TestCase):
    def test_review_medication_compacts_schema_bearing_subobjects(self) -> None:
        presented = present_result(
            "pharmacogenomics.review_medication",
            {
                "schema": "genomi-pgx-medication-review-v1",
                "ok": True,
                "status": "completed",
                "query": {"drug": "clopidogrel", "rsid": "rs4244285"},
                "evidence_state": {
                    "schema": "genomi-pgx-evidence-state-v1",
                    "status": "source_and_sample_evidence_present",
                    "has_public_pgx_evidence": True,
                    "has_sample_evidence": True,
                },
                "interpretation_readiness": {
                    "schema": "genomi-pgx-interpretation-readiness-v1",
                    "status": "ready_for_agent_synthesis",
                },
                "pgx_evidence_scope": {
                    "schema": "genomi-pgx-evidence-scope-v1",
                    "model": "bounded_target_scoped_evidence",
                    "status": "bounded_evidence_ready",
                    "scope": {
                        "schema": "genomi-pgx-scope-v1",
                        "sample_context_requested": True,
                    },
                },
                "public_evidence": {
                    "source_evidence_count": 1,
                    "clinpgx": {
                        "status": "completed",
                        "guideline_annotations": [
                            {"summary": "Use alternate therapy.", "raw_json": {"large": "payload"}}
                        ],
                    },
                },
                "sample_evidence": {
                    "sample_context_requested": True,
                    "sample_match_count": 1,
                    "variant_lookups": [
                        {
                            "sample_context": {
                                "matches": [
                                    {
                                        "rsid": "rs4244285",
                                        "chrom": "10",
                                        "pos": 94761900,
                                        "ref": "G",
                                        "alt": "A",
                                        "genotype": "0/1",
                                    }
                                ]
                            }
                        }
                    ],
                },
                "answer_support": {
                    "status": "source_and_sample_evidence_present",
                    "public_signal_count": 1,
                    "sample_signal_count": 1,
                    "source_recommendation_summaries": [
                        {"summary": "Use alternate therapy.", "raw_json": {"large": "payload"}}
                    ],
                },
            },
        )

        self.assertEqual(
            presented["evidence_state"],
            {
                "status": "source_and_sample_evidence_present",
                "has_public_pgx_evidence": True,
                "has_sample_evidence": True,
            },
        )
        self.assertEqual(
            presented["interpretation_readiness"],
            {"status": "ready_for_agent_synthesis"},
        )
        self.assertEqual(
            presented["pgx_evidence_scope"],
            {
                "model": "bounded_target_scoped_evidence",
                "status": "bounded_evidence_ready",
                "scope": {"sample_context_requested": True},
            },
        )
        self.assertEqual(
            presented["sample_evidence"]["variant_matches"],
            [
                {
                    "rsid": "rs4244285",
                    "chrom": "10",
                    "pos": 94761900,
                    "ref": "G",
                    "alt": "A",
                    "genotype": "0/1",
                }
            ],
        )
        self.assertEqual(
            presented["public_evidence"]["clinpgx"]["guideline_annotations"],
            [{"summary": "Use alternate therapy."}],
        )
        self.assertEqual(
            presented["answer_support"]["source_recommendation_summaries"],
            [{"summary": "Use alternate therapy."}],
        )


if __name__ == "__main__":
    unittest.main()
