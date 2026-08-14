from __future__ import annotations

import json
import unittest

from genomi.interfaces import portal_run_events, portal_turns


class PortalResultPresentationTests(unittest.TestCase):
    def test_live_variant_tool_event_gets_server_presentation(self) -> None:
        payload = {
            "headline": "variant.resolve: data_returned",
            "status": "completed",
            "query": {"rsid": "rs429358"},
            "resolved_targets": [{"rsid": "rs429358", "chrom": "19", "pos": 44908684}],
            "public_context": {
                "clinvar_by_rsid": [
                    {"clinical_significance": "risk factor", "condition": "Alzheimer disease"}
                ]
            },
            "evidence_envelope": {
                "operation": "variant.resolve",
                "headline": "variant.resolve: data_returned",
                "answer_readiness": "answer_supported",
                "finding_state": "data_returned",
                "coverage": {"libraries": ["dbSNP", "ClinVar"]},
            },
        }

        event = portal_run_events.public_event_data(
            "agent",
            {
                "type": "tool_result",
                "id": "call_variant",
                "name": "variant.resolve",
                "content": "raw payload",
                "payload": payload,
            },
        )

        model = event["portal_presentation"]
        self.assertEqual(model["schema"], "genomi_portal_result_presentation")
        self.assertEqual(model["source"], "server")
        self.assertEqual(model["operation"], "variant.resolve")
        self.assertEqual(model["kicker"], "Variant evidence map")
        self.assertEqual(model["title"], "rs429358")
        self.assertEqual(model["metrics"][0], {"label": "Resolved", "value": 1})
        self.assertEqual(model["lanes"][0]["title"], "Resolved targets")
        self.assertEqual(model["lanes"][1]["title"], "ClinVar records")

    def test_persisted_variant_tool_event_gets_redacted_server_presentation(self) -> None:
        event = portal_turns.history_tool_event(
            {
                "type": "tool_result",
                "id": "call_variant",
                "name": "variant.resolve",
                "payload": {
                    "headline": "variant.resolve: data_returned",
                    "query": {"rsid": "rs429358"},
                    "sample_context": {"private": True},
                    "public_context": {"clinvar_by_rsid": [{"variation_id": "123"}]},
                    "evidence_envelope": {
                        "operation": "variant.resolve",
                        "headline": "variant.resolve: data_returned",
                        "answer_readiness": "answer_supported",
                        "finding_state": "data_returned",
                    },
                },
            }
        )

        model = event["portal_presentation"]
        self.assertEqual(model["schema"], "genomi_portal_result_presentation")
        self.assertEqual(model["operation"], "variant.resolve")
        self.assertEqual(model["notice"]["title"], "Persisted redacted history")
        self.assertNotIn("sample_context", event["payload"])
        self.assertNotIn("Sample evidence", [lane["title"] for lane in model["lanes"]])

    def test_live_pgx_tool_event_gets_server_presentation(self) -> None:
        payload = {
            "headline": "pharmacogenomics.review_medication: evidence_present",
            "status": "completed",
            "query": {"drug": "clopidogrel", "gene": "CYP2C19"},
            "medication_review_matrix": {
                "rows": [
                    {
                        "drug": "clopidogrel",
                        "gene": "CYP2C19",
                        "diplotype": "*1/*2",
                        "phenotype": "Intermediate metabolizer",
                        "recommendation_text": "Use alternate therapy.",
                        "sample_relevance": {"state": "sample_target_observed"},
                    }
                ]
            },
            "evidence_matrix": {
                "item_count": 3,
                "role_counts": {"public_source": 2, "sample_follow_up": 1},
            },
            "sample_evidence": {
                "star_allele_call_count": 1,
                "star_gene_targets": [{"symbol": "CYP2C19", "name": "cytochrome P450 2C19"}],
                "variant_lookups": [{"rsid": "rs4244285", "genotype": "0/1"}],
            },
            "unanswered_answer_components": [{"component": "clinical confirmation", "state": "needed"}],
            "evidence_envelope": {
                "operation": "pharmacogenomics.review_medication",
                "headline": "pharmacogenomics.review_medication: evidence_present",
                "answer_readiness": "scoped_answer_only",
                "finding_state": "data_returned",
            },
        }

        event = portal_run_events.public_event_data(
            "agent",
            {
                "type": "tool_result",
                "id": "call_pgx",
                "name": "pharmacogenomics.review_medication",
                "payload": payload,
            },
        )

        model = event["portal_presentation"]
        self.assertEqual(model["schema"], "genomi_portal_result_presentation")
        self.assertEqual(model["source"], "server")
        self.assertEqual(model["operation"], "pharmacogenomics.review_medication")
        self.assertEqual(model["kind"], "pgx")
        self.assertEqual(model["kicker"], "Medication evidence matrix")
        self.assertEqual(model["title"], "clopidogrel / CYP2C19")
        self.assertIn({"label": "Rows", "value": 1}, model["metrics"])
        self.assertIn({"label": "Evidence items", "value": 3}, model["metrics"])
        self.assertIn({"label": "Star calls", "value": 1}, model["metrics"])
        self.assertEqual(
            [lane["title"] for lane in model["lanes"]],
            ["Medication rows", "Evidence roles", "Sample follow-up", "Unanswered components"],
        )
        self.assertEqual(model["lanes"][0]["nodes"][0]["label"], "clopidogrel · CYP2C19")
        self.assertEqual(model["lanes"][2]["nodes"][0]["label"], "CYP2C19")

    def test_persisted_pgx_tool_event_redacts_sample_follow_up_lane(self) -> None:
        event = portal_turns.history_tool_event(
            {
                "type": "tool_result",
                "id": "call_pgx",
                "name": "pharmacogenomics.review_medication",
                "payload": {
                    "headline": "pharmacogenomics.review_medication: evidence_present",
                    "query": {"drug": "clopidogrel"},
                    "medication_review_matrix": {"rows": [{"drug": "clopidogrel", "gene": "CYP2C19"}]},
                    "evidence_matrix": {"role_counts": {"public_source": 1}},
                    "sample_evidence": {"star_gene_targets": [{"symbol": "CYP2C19"}]},
                    "evidence_envelope": {
                        "operation": "pharmacogenomics.review_medication",
                        "headline": "pharmacogenomics.review_medication: evidence_present",
                        "answer_readiness": "scoped_answer_only",
                        "finding_state": "data_returned",
                    },
                },
            }
        )

        model = event["portal_presentation"]
        self.assertEqual(model["schema"], "genomi_portal_result_presentation")
        self.assertEqual(model["operation"], "pharmacogenomics.review_medication")
        self.assertEqual(model["notice"]["title"], "Persisted redacted history")
        self.assertNotIn("sample_evidence", event["payload"])
        self.assertNotIn("Sample follow-up", [lane["title"] for lane in model["lanes"]])

    def test_live_candidate_evidence_tool_event_gets_server_presentation(self) -> None:
        payload = _candidate_gwas_payload()

        event = portal_run_events.public_event_data(
            "agent",
            {
                "type": "tool_result",
                "id": "call_gwas",
                "name": "gwas.compare_variant_associations",
                "payload": payload,
            },
        )

        model = event["portal_presentation"]
        self.assertEqual(model["schema"], "genomi_portal_result_presentation")
        self.assertEqual(model["source"], "server")
        self.assertEqual(model["operation"], "gwas.compare_variant_associations")
        self.assertEqual(model["kind"], "candidate_evidence")
        self.assertEqual(model["kicker"], "Variant association evidence")
        self.assertEqual(model["title"], "LDL cholesterol / rs111 / rs222")
        self.assertIn({"label": "Candidates", "value": 2}, model["metrics"])
        self.assertIn({"label": "Top observed", "value": "rs111"}, model["metrics"])
        self.assertIn({"label": "Answer boundary", "value": "Scoped answer only"}, model["metrics"])
        self.assertIn({"label": "Evidence support", "value": "Data returned"}, model["metrics"])
        self.assertIn({"label": "Retrieval status", "value": "Completed"}, model["metrics"])
        self.assertEqual(
            [lane["title"] for lane in model["lanes"]],
            ["Candidate comparison", "Supporting evidence", "Evidence boundary", "Coverage and limits"],
        )
        self.assertEqual(model["lanes"][0]["nodes"][0]["label"], "#1 rs111")
        self.assertEqual(model["lanes"][1]["nodes"][0]["label"], "rs111 · LDL cholesterol · GCST000001")
        self.assertFalse(model["lanes"][3]["selectable"])

    def test_genomi_invoke_candidate_payload_routes_by_envelope_operation(self) -> None:
        payload = _candidate_gwas_payload()

        event = portal_run_events.public_event_data(
            "agent",
            {
                "type": "tool_result",
                "id": "call_invoke",
                "name": "genomi.invoke",
                "payload": payload,
            },
        )

        model = event["portal_presentation"]
        self.assertEqual(model["operation"], "gwas.compare_variant_associations")
        self.assertEqual(model["kind"], "candidate_evidence")
        self.assertEqual(model["kicker"], "Variant association evidence")

    def test_persisted_candidate_evidence_tool_event_keeps_server_presentation(self) -> None:
        event = portal_turns.history_tool_event(
            {
                "type": "tool_result",
                "id": "call_gwas",
                "name": "gwas.compare_variant_associations",
                "payload": {
                    **_candidate_gwas_payload(),
                    "debug_local_path": "/Users/matthewzmd/private/source.tsv",
                },
            }
        )

        model = event["portal_presentation"]
        self.assertEqual(model["schema"], "genomi_portal_result_presentation")
        self.assertEqual(model["operation"], "gwas.compare_variant_associations")
        self.assertEqual(model["kind"], "candidate_evidence")
        self.assertEqual(
            [lane["title"] for lane in model["lanes"]],
            ["Candidate comparison", "Supporting evidence", "Evidence boundary", "Coverage and limits"],
        )
        self.assertEqual(model["lanes"][0]["nodes"][0]["label"], "#1 rs111")
        self.assertNotIn("debug_local_path", event["payload"])
        self.assertNotIn("/Users", str(event))

    def test_persisted_clinvar_candidate_scan_redacts_private_candidate_rows(self) -> None:
        event = portal_turns.history_tool_event(
            {
                "type": "tool_result",
                "id": "call_clinvar",
                "name": "clinvar.scan_candidates",
                "payload": _clinvar_candidate_payload_with_private_rows(),
            }
        )

        model = event["portal_presentation"]
        serialized_model = json.dumps(model, sort_keys=True)
        serialized_payload = json.dumps(event["payload"], sort_keys=True)
        self.assertEqual(model["operation"], "clinvar.scan_candidates")
        self.assertEqual(model["kind"], "candidate_evidence")
        self.assertEqual(model["notice"]["title"], "Persisted redacted history")
        self.assertNotIn("Candidate comparison", [lane["title"] for lane in model["lanes"]])
        self.assertIn("Scan summary", [lane["title"] for lane in model["lanes"]])
        self.assertNotIn("candidate_matrix", event["payload"])
        self.assertNotIn("evidence_view", event["payload"])
        for private_text in (
            "0/1",
            "sample-secret",
            "variant:1-100-A-G",
            "rsPRIVATE",
            "genotype_support",
            "private_sample_id",
        ):
            self.assertNotIn(private_text, serialized_model)
            self.assertNotIn(private_text, serialized_payload)


    def test_live_target_packet_tool_event_gets_server_presentation(self) -> None:
        payload = _target_packet_payload()

        event = portal_run_events.public_event_data(
            "agent",
            {
                "type": "tool_result",
                "id": "call_target",
                "name": "research.build_target_packet",
                "payload": payload,
            },
        )

        model = event["portal_presentation"]
        self.assertEqual(model["schema"], "genomi_portal_result_presentation")
        self.assertEqual(model["source"], "server")
        self.assertEqual(model["operation"], "research.build_target_packet")
        self.assertEqual(model["kind"], "target_packet")
        self.assertEqual(model["kicker"], "Target evidence report")
        self.assertEqual(model["title"], "rs429358")
        self.assertEqual(model["summary"], "Target-centric evidence report for focused Genomi research.")
        self.assertIn({"label": "Sources", "value": 2}, model["metrics"])
        self.assertIn({"label": "Stored findings", "value": 1}, model["metrics"])
        self.assertIn({"label": "Answer boundary", "value": "Scoped answer only"}, model["metrics"])
        self.assertEqual(
            [lane["title"] for lane in model["lanes"]],
            ["Target", "Reviewed research", "Source catalog", "Evidence readiness", "Coverage and limits"],
        )
        self.assertEqual(model["lanes"][1]["nodes"][0]["label"], "finding-apoe")
        self.assertEqual(model["lanes"][2]["nodes"][0]["label"], "hpo · Human Phenotype Ontology")
        self.assertFalse(model["lanes"][3]["selectable"])
        self.assertFalse(model["lanes"][4]["selectable"])
        self.assertNotIn("/Users", json.dumps(model, sort_keys=True))

    def test_genomi_invoke_target_packet_payload_routes_by_envelope_operation(self) -> None:
        event = portal_run_events.public_event_data(
            "agent",
            {
                "type": "tool_result",
                "id": "call_invoke",
                "name": "genomi.invoke",
                "payload": _target_packet_payload(),
            },
        )

        model = event["portal_presentation"]
        self.assertEqual(model["operation"], "research.build_target_packet")
        self.assertEqual(model["kind"], "target_packet")
        self.assertEqual(model["title"], "rs429358")

    def test_persisted_target_packet_tool_event_gets_redacted_server_presentation(self) -> None:
        event = portal_turns.history_tool_event(
            {
                "type": "tool_result",
                "id": "call_target",
                "name": "research.build_target_packet",
                "payload": _target_packet_payload(),
            }
        )

        model = event["portal_presentation"]
        serialized = json.dumps(event, sort_keys=True)
        self.assertEqual(model["schema"], "genomi_portal_result_presentation")
        self.assertEqual(model["operation"], "research.build_target_packet")
        self.assertEqual(model["kind"], "target_packet")
        self.assertEqual(model["notice"]["title"], "Persisted redacted history")
        self.assertEqual(event["content"], "Target evidence report for rs429358")
        self.assertEqual(event["ledger"]["headline"], "Target evidence report for rs429358")
        self.assertEqual(model["summary"], "Target-centric evidence report for focused Genomi research.")
        self.assertNotIn("research.build_target_packet: evidence_present", model["summary"])
        self.assertIn("Target", [lane["title"] for lane in model["lanes"]])
        self.assertNotIn("/Users", serialized)
        self.assertNotIn("shared-evidence.sqlite", serialized)

def _candidate_gwas_payload() -> dict:
    return {
        "headline": "gwas.compare_variant_associations: data_returned",
        "status": "completed",
        "query": {"phenotype": "LDL cholesterol", "variants": ["rs111", "rs222"]},
        "summary": {"top_observed_candidate": "rs111", "top_observed_support_level": "high"},
        "evidence_view": {
            "query": {"phenotype": "LDL cholesterol", "variants": ["rs111", "rs222"]},
            "coverage_state": "data_returned",
            "evidence_state": "decision_grade_evidence",
            "agent_decision_required": True,
            "evidence_policy": {"policy_id": "source_local_candidate_ranking"},
            "coverage": {
                "candidate_count": 2,
                "ranked_candidate_count": 2,
                "top_observed_candidate": "rs111",
                "top_observed_support_level": "high",
            },
            "candidate_matrix": [
                {
                    "candidate_id": "rs111",
                    "candidate_type": "rsid",
                    "rank": 1,
                    "score": 0.92,
                    "evidence_support_level": "high",
                    "answerability": "direct_source_supported",
                    "best_evidence_lane": "direct_source_match",
                    "best_pvalue": "1e-9",
                    "supporting_evidence": [
                        {
                            "candidate_id": "rs111",
                            "trait": "LDL cholesterol",
                            "pvalue": "1e-9",
                            "source_id": "GCST000001",
                            "study": "GWAS Catalog",
                        }
                    ],
                },
                {
                    "candidate_id": "rs222",
                    "candidate_type": "rsid",
                    "rank": 2,
                    "score": 0.41,
                    "evidence_support_level": "low",
                    "answerability": "adjacent_source_supported",
                    "best_evidence_lane": "nearby_trait_match",
                },
            ],
            "rankings": [],
            "warnings": ["Population-level associations are not individual diagnosis."],
        },
        "evidence_envelope": {
            "operation": "gwas.compare_variant_associations",
            "headline": "gwas.compare_variant_associations: data_returned",
            "answer_readiness": "scoped_answer_only",
            "finding_state": "data_returned",
            "coverage": {"consulted_libraries": ["GWAS Catalog"]},
            "observations": {"top_observed_candidate": "rs111"},
        },
    }


def _target_packet_payload() -> dict:
    return {
        "headline": "research.build_target_packet: evidence_present",
        "purpose": "Target-centric evidence report for focused Genomi research.",
        "target": {"target_type": "topic", "target_id": "topic:rs429358", "topic": "rs429358"},
        "stored_research": {
            "count": 1,
            "records": [
                {
                    "finding_id": "finding-apoe",
                    "scope": "public reviewed research",
                    "finding": {"summary": "APOE locus evidence reviewed for this target."},
                    "source": {"title": "Curated note"},
                }
            ],
        },
        "source_catalog": {
            "summary": {"source_count": 2},
            "sources": [
                {
                    "source_id": "hpo",
                    "title": "Human Phenotype Ontology",
                    "adapter_status": "implemented_local_normalization",
                    "best_for": "Normalizing phenotype terms and HPO identifiers.",
                },
                {
                    "source_id": "gwas_catalog",
                    "title": "GWAS Catalog",
                    "evidence_types": ["trait_association", "variant_association"],
                },
            ],
        },
        "available_operations": [
            {
                "tool": "research.query",
                "params": {"shared_evidence_db": "/Users/matthewzmd/.genomi/shared-evidence.sqlite"},
                "relevance": "stored reviewed evidence for this target",
            }
        ],
        "evidence_options": [
            {"component": "source_scope_selection", "state": "available", "inputs": ["target", "source_catalog"]},
            {"component": "stored_research", "state": "present"},
        ],
        "defaults_applied": {"limit": 8},
        "evidence_envelope": {
            "operation": "research.build_target_packet",
            "headline": "research.build_target_packet: evidence_present",
            "answer_readiness": "scoped_answer_only",
            "finding_state": "evidence_present",
            "coverage": {"source_count": 2},
            "observations": {"stored_findings": 1},
        },
    }


def _clinvar_candidate_payload_with_private_rows() -> dict:
    private_row = {
        "candidate_id": "variant:1-100-A-G",
        "candidate_type": "variant",
        "rank": 1,
        "score": 0.95,
        "evidence_support_level": "high",
        "answerability": "direct_source_supported",
        "best_evidence_lane": "direct_source_match",
        "private_sample_id": "sample-secret",
        "supporting_evidence": [
            {
                "source": "ClinVar",
                "clinvar_ids": ["rsPRIVATE"],
                "genotype_support": {"genotype": "0/1", "source": "private sample"},
                "match_provenance": {"match_basis_counts": [["exact_allele", 1]]},
            }
        ],
    }
    return {
        "headline": "clinvar.scan_candidates: data_returned",
        "status": "completed",
        "summary": {
            "total_match_records": 1,
            "total_match_variants": 1,
            "selected_candidate_variants": 1,
            "emitted_candidate_variants": 1,
            "clinical_significance_counts": [["pathogenic", 1]],
            "review_status_counts": [["criteria provided", 1]],
        },
        "coverage": {
            "candidate_count": 1,
            "ranked_candidate_count": 1,
            "top_observed_candidate": "variant:1-100-A-G",
            "top_observed_support_level": "high",
        },
        "evidence_view": {
            "query": {"genome_build": "GRCh38"},
            "coverage_state": "data_returned",
            "evidence_state": "decision_grade_evidence",
            "coverage": {
                "candidate_count": 1,
                "ranked_candidate_count": 1,
                "top_observed_candidate": "variant:1-100-A-G",
                "top_observed_support_level": "high",
            },
            "candidate_matrix": [private_row],
            "rankings": [private_row],
        },
        "candidate_matrix": [private_row],
        "rankings": [private_row],
        "evidence_envelope": {
            "operation": "clinvar.scan_candidates",
            "headline": "clinvar.scan_candidates: data_returned",
            "answer_readiness": "scoped_answer_only",
            "finding_state": "data_returned",
            "coverage": {"libraries": ["ClinVar static annotation"]},
            "observations": {"candidate_count": 1},
        },
    }


if __name__ == "__main__":
    unittest.main()
