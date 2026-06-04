from __future__ import annotations

import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from genomi.capabilities.pharmacogenomics import clinpgx
from genomi.capabilities.pharmacogenomics.clinpgx import lookup_clinpgx
from genomi.capabilities.research.intent_research import (
    query_reviewed_research,
    record_reviewed_research,
)
from genomi.evidence.sources import evidence_source_catalog
from genomi.operations import call_operation, list_operations


class ClinPGxTests(unittest.TestCase):
    def test_lookup_returns_guideline_clinical_annotation_and_label_context(self) -> None:
        def fake_fetch(base_url, path, *, query=None, raw_calls):
            raw_calls.append({"url": base_url + path, "query": query, "status": 200})
            if path == "/data/chemical":
                return {"status": "success", "data": [{"objCls": "Chemical", "id": "PA449053", "name": "clopidogrel"}]}
            if path == "/data/gene":
                return {"status": "success", "data": [{"objCls": "Gene", "id": "PA124", "symbol": "CYP2C19", "name": "cytochrome P450 family 2 subfamily C member 19"}]}
            if path == "/data/variant/":
                return {"status": "success", "data": [{"objCls": "Variant", "id": "PA166154053", "symbol": "rs4244285", "name": "rs4244285"}]}
            if path == "/data/guidelineAnnotation" and query["source"] == "cpic":
                return {
                    "status": "success",
                    "data": [
                        {
                            "objCls": "Guideline Annotation",
                            "id": "PA166104948",
                            "name": "Annotation of CPIC Guideline for clopidogrel and CYP2C19",
                            "source": "CPIC",
                            "recommendation": True,
                            "dosingInformation": False,
                            "alternateDrugAvailable": True,
                            "summaryMarkdown": {
                                "html": "<p>CPIC recommends an alternative antiplatelet therapy for CYP2C19 poor or intermediate metabolizers.</p>"
                            },
                            "relatedChemicals": [{"objCls": "Chemical", "id": "PA449053", "name": "clopidogrel"}],
                            "relatedGenes": [{"objCls": "Gene", "id": "PA124", "symbol": "CYP2C19"}],
                            "literature": [
                                {
                                    "id": 15127862,
                                    "title": "Clinical Pharmacogenetics Implementation Consortium Guideline for CYP2C19 Genotype and Clopidogrel Therapy: 2022 Update.",
                                    "_sameAs": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9287492",
                                    "pubDate": "2022-11-01T00:00:00-07:00",
                                    "crossReferences": [{"resource": "PubMed", "resourceId": "35034351", "_url": "https://www.ncbi.nlm.nih.gov/pubmed/35034351"}],
                                }
                            ],
                        }
                    ],
                }
            if path == "/data/guidelineAnnotation":
                return {"status": "success", "data": []}
            if path == "/data/clinicalAnnotation":
                return {
                    "status": "success",
                    "data": [
                        {
                            "id": 1043858794,
                            "accessionId": "PA166134797",
                            "levelOfEvidence": {"term": "1A"},
                            "location": {
                                "displayName": "CYP2C19*2",
                                "genes": [{"objCls": "Gene", "id": "PA124", "symbol": "CYP2C19"}],
                                "haplotypes": [{"objCls": "Haplotype", "id": "PA165980635", "symbol": "CYP2C19*2", "name": "*2"}],
                            },
                            "relatedChemicals": [{"objCls": "Chemical", "id": "PA449053", "name": "clopidogrel"}],
                            "allelePhenotypes": [{"allele": "*2", "phenotype": "CYP2C19*2 is assigned as a no function allele by CPIC."}],
                        }
                    ],
                }
            if path == "/data/label":
                return {
                    "status": "success",
                    "data": [
                        {
                            "objCls": "Label Annotation",
                            "id": "PA166104777",
                            "name": "Annotation of FDA Label for clopidogrel and CYP2C19",
                            "source": "FDA",
                            "biomarkerStatus": "On FDA Biomarker List",
                            "testing": {"term": "Actionable PGx"},
                            "summaryMarkdown": {
                                "html": "<p>The FDA-approved drug label states that poor metabolizers have reduced platelet activity.</p>"
                            },
                            "relatedChemicals": [{"objCls": "Chemical", "id": "PA449053", "name": "clopidogrel"}],
                            "relatedGenes": [{"objCls": "Gene", "id": "PA124", "symbol": "CYP2C19"}],
                        }
                    ],
                }
            raise AssertionError(path)

        with patch("genomi.capabilities.pharmacogenomics.clinpgx._fetch_json", side_effect=fake_fetch):
            result = lookup_clinpgx(drug="clopidogrel", gene="CYP2C19", rsid="rs4244285")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["resolved"]["chemicals"][0]["id"], "PA449053")
        self.assertEqual(result["resolved"]["genes"][0]["symbol"], "CYP2C19")
        self.assertEqual(result["resolved"]["variants"][0]["symbol"], "rs4244285")
        self.assertEqual(result["summary"]["guideline_annotation_count"], 1)
        self.assertEqual(result["summary"]["clinical_annotation_count"], 1)
        self.assertEqual(result["summary"]["label_annotation_count"], 1)
        self.assertEqual(result["guideline_annotations"][0]["guideline_source"], "CPIC")
        self.assertNotIn("raw", result["guideline_annotations"][0])
        self.assertEqual(result["clinical_annotations"][0]["level_of_evidence"], "1A")
        self.assertNotIn("raw", result["clinical_annotations"][0])
        self.assertEqual(result["label_annotations"][0]["testing_level"], "Actionable PGx")
        self.assertNotIn("raw", result["label_annotations"][0])
        self.assertEqual(result["sample_follow_up_targets"]["genes"][0]["symbol"], "CYP2C19")
        self.assertEqual(result["sample_follow_up_targets"]["haplotypes"][0]["symbol"], "CYP2C19*2")
        self.assertEqual(result["clinical_verification"]["status"], "informational_evidence_review_requires_clinical_confirmation")
        self.assertIn("guideline_annotation", result["clinical_verification"]["public_evidence_classes"])
        self.assertEqual(result["evidence_envelope"]["coverage"]["libraries"][0]["library"], "clinpgx")
        self.assertGreaterEqual(result["summary"]["record_research_payload_count"], 3)
        self.assertEqual(result["record_research_payloads"][0]["captured_by"], "genomi call pharmacogenomics.fetch_clinpgx")
        self.assertIn("CPIC recommends", result["record_research_payloads"][0]["finding"]["text"])
        self.assertEqual(result["record_research_payloads"][0]["source"]["source_id"], "clinpgx")
        self.assertEqual(result["record_research_payloads"][0]["source"]["api_url"], "https://api.pharmgkb.org/v1")
        self.assertEqual(result["record_research_payloads"][0]["source"]["swagger_url"], "https://api.pharmgkb.org/swagger/")
        self.assertEqual(result["record_research_payloads"][0]["source"]["citations"][0]["id"], 15127862)
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            record = record_reviewed_research(db, result["record_research_payloads"], scope="shared", sync_shared=False)
            self.assertEqual(record["scope"], "shared")
            stored = query_reviewed_research(db, "drug", drug="clopidogrel")
            self.assertGreaterEqual(stored["count"], 1)
            self.assertIn("clinpgx_", stored["records"][0]["finding"]["type"])
            self.assertEqual(stored["records"][0]["source"]["source_id"], "clinpgx")
            self.assertEqual(stored["records"][0]["source"]["api_url"], "https://api.pharmgkb.org/v1")
            self.assertEqual(stored["records"][0]["source"]["citations"][0]["id"], 15127862)

    def test_lookup_can_include_compact_raw_records_when_requested(self) -> None:
        def fake_fetch(base_url, path, *, query=None, raw_calls):
            raw_calls.append({"url": base_url + path, "query": query, "status": 200})
            if path == "/data/chemical":
                return {"data": [{"objCls": "Chemical", "id": "PA449053", "name": "clopidogrel"}]}
            if path == "/data/guidelineAnnotation" and query["source"] == "cpic":
                return {
                    "data": [
                        {
                            "id": "PA166104948",
                            "source": "CPIC",
                            "summaryMarkdown": {"html": "<p>Use alternative therapy.</p>"},
                            "largeText": "x" * 2000,
                        }
                    ]
                }
            if path in {"/data/guidelineAnnotation", "/data/clinicalAnnotation", "/data/label"}:
                return {"data": []}
            raise AssertionError(path)

        with patch("genomi.capabilities.pharmacogenomics.clinpgx._fetch_json", side_effect=fake_fetch):
            result = lookup_clinpgx(drug="clopidogrel", guideline_source="cpic", include_raw_records=True)

        self.assertIn("raw", result["guideline_annotations"][0])
        self.assertLessEqual(len(result["guideline_annotations"][0]["raw"]["largeText"]), 620)

    def test_lookup_requires_selected_public_target(self) -> None:
        result = lookup_clinpgx()

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "invalid_target")
        self.assertEqual(result["raw_calls"], [])
        self.assertEqual(
            result["unanswered_answer_components"][0]["missing_inputs"],
            ["drug", "gene", "rsid", "chemical_id", "gene_id", "variant_id"],
        )

    def test_clinical_annotation_lookup_falls_back_from_exact_variant_query(self) -> None:
        def fake_fetch(base_url, path, *, query=None, raw_calls):
            raw_calls.append({"url": base_url + path, "query": query, "status": 200})
            if path == "/data/chemical":
                return {"data": [{"objCls": "Chemical", "id": "PA449053", "name": "clopidogrel"}]}
            if path == "/data/gene":
                return {"data": [{"objCls": "Gene", "id": "PA124", "symbol": "CYP2C19"}]}
            if path == "/data/variant/":
                return {"data": [{"objCls": "Variant", "id": "PA166154053", "symbol": "rs4244285"}]}
            if path == "/data/guidelineAnnotation":
                return {"data": []}
            if path == "/data/label":
                return {"data": []}
            if path == "/data/clinicalAnnotation":
                if query == {
                    "view": "base",
                    "relatedChemicals.name": "clopidogrel",
                    "location.genes.symbol": "CYP2C19",
                    "location.fingerprint": "rs4244285",
                }:
                    return {"data": []}
                if query == {
                    "view": "base",
                    "relatedChemicals.name": "clopidogrel",
                    "location.genes.symbol": "CYP2C19",
                }:
                    return {
                        "data": [
                            {
                                "id": 1043858794,
                                "accessionId": "PA166134797",
                                "levelOfEvidence": {"term": "1A"},
                                "location": {
                                    "displayName": "CYP2C19*2",
                                    "genes": [{"objCls": "Gene", "id": "PA124", "symbol": "CYP2C19"}],
                                    "haplotypes": [{"objCls": "Haplotype", "id": "PA165980635", "symbol": "CYP2C19*2"}],
                                },
                                "relatedChemicals": [{"objCls": "Chemical", "id": "PA449053", "name": "clopidogrel"}],
                            }
                        ]
                    }
                return {"data": []}
            raise AssertionError(path)

        with patch("genomi.capabilities.pharmacogenomics.clinpgx._fetch_json", side_effect=fake_fetch):
            result = lookup_clinpgx(drug="clopidogrel", gene="CYP2C19", rsid="rs4244285")

        clinical_queries = [
            call["query"]
            for call in result["raw_calls"]
            if call["url"].endswith("/data/clinicalAnnotation")
        ]
        self.assertEqual(result["summary"]["clinical_annotation_count"], 1)
        self.assertEqual(result["clinical_annotations"][0]["display_name"], "CYP2C19*2")
        self.assertEqual(
            clinical_queries[:2],
            [
                {
                    "view": "base",
                    "relatedChemicals.name": "clopidogrel",
                    "location.genes.symbol": "CYP2C19",
                    "location.fingerprint": "rs4244285",
                },
                {
                    "view": "base",
                    "relatedChemicals.name": "clopidogrel",
                    "location.genes.symbol": "CYP2C19",
                },
            ],
        )

    def test_lookup_returns_structured_status_when_source_unavailable(self) -> None:
        with patch("genomi.capabilities.pharmacogenomics.clinpgx.urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            result = lookup_clinpgx(drug="clopidogrel")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "source_unavailable")
        self.assertEqual(result["summary"]["guideline_annotation_count"], 0)
        self.assertEqual(result["raw_calls"][0]["attempts"], 2)
        self.assertIn("offline", result["warnings"][0]["error"])

    def test_clinpgx_404_is_empty_result_not_source_error(self) -> None:
        raw_calls = []
        error = urllib.error.HTTPError("https://api.pharmgkb.org/v1/data/clinicalAnnotation", 404, "Not Found", {}, None)

        with patch("genomi.capabilities.pharmacogenomics.clinpgx.urllib.request.urlopen", side_effect=error):
            payload = clinpgx._fetch_json(  # pylint: disable=protected-access
                "https://api.pharmgkb.org/v1",
                "/data/clinicalAnnotation",
                raw_calls=raw_calls,
            )

        self.assertEqual(payload, {"data": []})
        self.assertEqual(raw_calls[0]["status"], 404)
        self.assertTrue(raw_calls[0]["not_found"])
        self.assertNotIn("error", raw_calls[0])

    def test_clinpgx_lookup_is_agent_tool_and_source_catalog_entry(self) -> None:
        tools = {tool["name"]: tool for tool in list_operations(capability="pharmacogenomics")}
        self.assertIn("pharmacogenomics.fetch_clinpgx", tools)
        self.assertEqual(tools["pharmacogenomics.fetch_clinpgx"]["annotations"]["externalIO"], ["clinpgx_api"])

        cpic = evidence_source_catalog(source_id="cpic")["sources"][0]
        self.assertEqual(cpic["adapter_status"], "implemented_api_fetch")
        self.assertIn("pharmacogenomics.fetch_clinpgx", cpic["genomi_operations"])
        self.assertTrue(cpic["agent_contract"]["use_implemented_adapter_first"])

    def test_call_operation_uses_clinpgx_lookup(self) -> None:
        def fake_fetch(base_url, path, *, query=None, raw_calls):
            raw_calls.append({"url": base_url + path, "query": query, "status": 200})
            if path == "/data/chemical":
                return {"status": "success", "data": [{"objCls": "Chemical", "id": "PA449053", "name": "clopidogrel"}]}
            if path == "/data/guidelineAnnotation":
                return {"status": "success", "data": []}
            if path == "/data/clinicalAnnotation":
                return {"status": "success", "data": []}
            if path == "/data/label":
                return {"status": "success", "data": []}
            raise AssertionError(path)

        with patch("genomi.capabilities.pharmacogenomics.clinpgx._fetch_json", side_effect=fake_fetch):
            result = call_operation("pharmacogenomics.fetch_clinpgx", {"drug": "clopidogrel", "guideline_source": "cpic"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "no_matching_clinpgx_records")
        self.assertEqual(result["resolved"]["chemicals"][0]["id"], "PA449053")
        self.assertEqual(result["evidence_envelope"]["finding_state"], "not_observed_in_consulted_scope")
        self.assertIn(
            "not_observed_in_consulted_scope:clinpgx_no_records_for_target",
            result["evidence_envelope"]["guidance"],
        )
        self.assertEqual(result["evidence_envelope"]["next_actions"][0]["action"], "try_alternate_pgx_source_or_target_spelling")


if __name__ == "__main__":
    unittest.main()
