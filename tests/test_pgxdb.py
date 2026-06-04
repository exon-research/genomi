from __future__ import annotations

import unittest
import urllib.error
from unittest.mock import patch

from genomi.capabilities.pharmacogenomics.pgxdb import lookup_pgxdb
from genomi.evidence.sources import evidence_source_catalog
from genomi.operations import call_operation, list_operations


class PGxDBTests(unittest.TestCase):
    def test_lookup_resolves_drug_and_filters_rsid(self) -> None:
        def fake_fetch(base_url, path, *, query=None, raw_calls):
            raw_calls.append({"url": base_url + path, "query": query, "status": 200})
            if path == "/atc/atc_code/CS/":
                return {
                    "All ATC codes in ChemicalSubstance group ": [
                        {"ATC code": "L04AB02", "Description": "Infliximab"},
                        {"ATC code": "A01AA01", "Description": "Sodium fluoride"},
                    ]
                }
            if path == "/atc/pgx/L04AB02/":
                return {
                    "ATC Pharmacogenomics for L04AB02": [
                        {
                            "DrugbankID": "DB00065",
                            "Drugname": "Infliximab",
                            "Variant_or_Haplotypes": "rs1061622",
                            "PMID": "18565259",
                            "Phenotype_Category": "Efficacy",
                            "Significance": "yes",
                            "Sentence": "Allele G is associated with decreased response to infliximab.",
                            "Alleles": "G",
                            "Direction_of_effect": "decreased",
                            "PD_PK_terms": "response to",
                        },
                        {
                            "DrugbankID": "DB00065",
                            "Drugname": "Infliximab",
                            "Variant_or_Haplotypes": "rs1800629",
                            "Sentence": "Different row.",
                        },
                    ]
                }
            raise AssertionError(path)

        with patch("genomi.capabilities.pharmacogenomics.pgxdb._fetch_json", side_effect=fake_fetch):
            result = lookup_pgxdb(drug="Infliximab", rsid="rs1061622")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["resolved_atc_codes"][0]["atc_code"], "L04AB02")
        self.assertEqual(len(result["pgx_records"]), 1)
        self.assertEqual(result["pgx_records"][0]["rsid"], "rs1061622")
        self.assertEqual(result["pgx_records"][0]["direction_of_effect"], "decreased")
        self.assertNotIn("raw", result["pgx_records"][0])
        self.assertEqual(result["evidence_envelope"]["coverage"]["libraries"][0]["library"], "pgxdb")
        self.assertEqual(result["record_research_payloads"][0]["target"]["topic"], "rs1061622 Infliximab pharmacogenomic response")
        self.assertEqual(result["record_research_payloads"][0]["target"]["type"], "topic")
        self.assertEqual(result["record_research_payloads"][0]["source"]["source_id"], "pgxdb")
        self.assertEqual(result["record_research_payloads"][0]["source"]["api_url"], "https://pgx-db.org/rest-api")
        self.assertEqual(result["record_research_payloads"][0]["source"]["swagger_url"], "https://pgx-db.org/swagger/")
        self.assertEqual(result["record_research_payloads"][0]["source"]["pmid"], "18565259")
        self.assertIn("decreased response", result["record_research_payloads"][0]["finding"]["text"])

    def test_lookup_can_include_compact_raw_records_when_requested(self) -> None:
        def fake_fetch(base_url, path, *, query=None, raw_calls):
            raw_calls.append({"url": base_url + path, "query": query, "status": 200})
            if path == "/atc/atc_code/CS/":
                return {"rows": [{"ATC code": "L04AB02", "Description": "Infliximab"}]}
            if path == "/atc/pgx/L04AB02/":
                return {
                    "rows": [
                        {
                            "Drugname": "Infliximab",
                            "Variant_or_Haplotypes": "rs1061622",
                            "Sentence": "Allele G is associated with decreased response to infliximab.",
                            "Notes": "x" * 2000,
                        }
                    ]
                }
            raise AssertionError(path)

        with patch("genomi.capabilities.pharmacogenomics.pgxdb._fetch_json", side_effect=fake_fetch):
            result = lookup_pgxdb(drug="Infliximab", include_raw_records=True)

        self.assertIn("raw", result["pgx_records"][0])
        self.assertLessEqual(len(result["pgx_records"][0]["raw"]["Notes"]), 520)

    def test_lookup_deduplicates_repeated_pgx_rows(self) -> None:
        def fake_fetch(base_url, path, *, query=None, raw_calls):
            raw_calls.append({"url": base_url + path, "query": query, "status": 200})
            if path == "/atc/atc_code/CS/":
                return {"rows": [{"ATC code": "L04AB02", "Description": "Infliximab"}]}
            if path == "/atc/pgx/L04AB02/":
                row = {
                    "Drugname": "Infliximab",
                    "Variant_or_Haplotypes": "rs1061622",
                    "Sentence": "Allele G is associated with decreased response to infliximab.",
                    "Alleles": "G",
                    "Direction_of_effect": "decreased",
                }
                return {"rows": [row, dict(row)]}
            raise AssertionError(path)

        with patch("genomi.capabilities.pharmacogenomics.pgxdb._fetch_json", side_effect=fake_fetch):
            result = lookup_pgxdb(drug="Infliximab")

        self.assertEqual(result["summary"]["pgx_record_count"], 1)
        self.assertEqual(result["summary"]["record_research_payload_count"], 1)

    def test_lookup_marks_medication_scoped_gene_drug_records(self) -> None:
        def fake_fetch(base_url, path, *, query=None, raw_calls):
            raw_calls.append({"url": base_url + path, "query": query, "status": 200})
            if path == "/drug/atc_code/DB00758/":
                return {"rows": []}
            if path == "/gene/drug/":
                self.assertEqual(query, {"genename": "cyp2c19"})
                return {
                    "rows": [
                        {
                            "drug_bankID": "DB00758",
                            "actions": "substrate",
                            "known_action": "yes",
                            "interaction_type": "enzyme",
                        },
                        {
                            "drug_bankID": "DB00000",
                            "actions": "substrate",
                            "known_action": "unknown",
                            "interaction_type": "enzyme",
                        },
                    ]
                }
            raise AssertionError(path)

        with patch("genomi.capabilities.pharmacogenomics.pgxdb._fetch_json", side_effect=fake_fetch):
            result = lookup_pgxdb(gene="CYP2C19", drugbank_id="DB00758")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"]["gene_drug_record_count"], 2)
        self.assertEqual(result["summary"]["medication_scoped_gene_drug_record_count"], 1)
        self.assertEqual(result["summary"]["record_research_payload_count"], 1)
        self.assertEqual(result["gene_drug_records"][0]["target_scope"], "selected_medication")
        self.assertEqual(result["gene_drug_records"][1]["target_scope"], "other_drug_for_gene")
        self.assertEqual(result["medication_scoped_gene_drug_records"][0]["drugbank_id"], "DB00758")
        self.assertEqual(result["record_research_payloads"][0]["finding"]["type"], "pgxdb_gene_drug_context")
        self.assertEqual(result["record_research_payloads"][0]["source"]["source_id"], "pgxdb")
        self.assertIn("CYP2C19", result["record_research_payloads"][0]["finding"]["text"])

    def test_lookup_treats_medication_scoped_gene_context_failure_as_optional(self) -> None:
        def fake_fetch(base_url, path, *, query=None, raw_calls):
            call = {"url": base_url + path, "query": query, "status": 200}
            raw_calls.append(call)
            if path == "/atc/atc_code/CS/":
                return {"rows": [{"Atc code": "B01AC04", "Description": "clopidogrel"}]}
            if path == "/atc/pgx/B01AC04/":
                return {
                    "rows": [
                        {
                            "Drugname": "clopidogrel",
                            "DrugBank_ID": "DB00758",
                            "Variant_or_Haplotypes": "rs4244285",
                            "Sentence": "A PGxDB association row.",
                        }
                    ]
                }
            if path == "/gene/drug/":
                self.assertEqual(query, {"genename": "cyp2c19"})
                call["status"] = 500
                call["error"] = "HTTP 500"
                return None
            raise AssertionError(path)

        with patch("genomi.capabilities.pharmacogenomics.pgxdb._fetch_json", side_effect=fake_fetch):
            result = lookup_pgxdb(drug="clopidogrel", gene="CYP2C19")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("warnings", result)
        optional_errors = [call for call in result["raw_calls"] if call.get("optional")]
        self.assertEqual(len(optional_errors), 1)
        self.assertEqual(optional_errors[0]["endpoint_role"], "pgxdb_gene_drug_context")

    def test_lookup_records_variant_context_payloads(self) -> None:
        def fake_fetch(base_url, path, *, query=None, raw_calls):
            raw_calls.append({"url": base_url + path, "query": query, "status": 200})
            if path == "/gene/associateStatictics/rs4244285":
                return {"rows": [{"gene": "CYP2C19", "p_value": "1e-8"}]}
            if path == "/variant/VEPscore/rs4244285":
                return {"Results": "No VEP score available"}
            raise AssertionError(path)

        with patch("genomi.capabilities.pharmacogenomics.pgxdb._fetch_json", side_effect=fake_fetch):
            result = lookup_pgxdb(variant_marker="rs4244285")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"]["variant_context_record_count"], 2)
        self.assertEqual(result["summary"]["record_research_payload_count"], 2)
        finding_types = {payload["finding"]["type"] for payload in result["record_research_payloads"]}
        self.assertEqual(finding_types, {"pgxdb_variant_context"})
        self.assertEqual(result["record_research_payloads"][0]["source"]["source_id"], "pgxdb")
        self.assertIn("rs4244285 PGxDB association_statistics", result["record_research_payloads"][0]["target"]["topic"])

    def test_lookup_requires_selected_public_target(self) -> None:
        result = lookup_pgxdb()

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "invalid_target")
        self.assertEqual(result["raw_calls"], [])
        self.assertEqual(
            result["unanswered_answer_components"][0]["missing_inputs"],
            ["drug", "atc_code", "drugbank_id", "rsid", "variant_marker", "gene"],
        )

    def test_lookup_no_match_is_successful_empty_lookup(self) -> None:
        result = lookup_pgxdb(rsid="rs999999999")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "no_matching_pgxdb_records")
        self.assertEqual(result["raw_calls"], [])
        self.assertEqual(result["summary"]["pgx_record_count"], 0)
        self.assertEqual(result["evidence_envelope"]["finding_state"], "not_assessed")
        self.assertIn(
            "scope_missing:pgxdb_requires_medication_context",
            result["evidence_envelope"]["guidance"],
        )
        self.assertEqual(result["evidence_envelope"]["next_actions"][0]["action"], "provide_medication_context")

    def test_lookup_returns_structured_status_when_source_unavailable(self) -> None:
        with patch("genomi.capabilities.pharmacogenomics.pgxdb.urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            result = lookup_pgxdb(drug="Infliximab")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "source_unavailable")
        self.assertEqual(result["summary"]["pgx_record_count"], 0)
        self.assertEqual(result["raw_calls"][0]["attempts"], 2)
        self.assertIn("offline", result["warnings"][0]["error"])

    def test_pgxdb_lookup_is_agent_tool_and_source_catalog_entry(self) -> None:
        names = {tool["name"] for tool in list_operations(capability="pharmacogenomics")}
        self.assertIn("pharmacogenomics.fetch_pgxdb", names)

        catalog = evidence_source_catalog(source_id="pgxdb")
        self.assertEqual(catalog["sources"][0]["adapter_status"], "implemented_api_fetch")
        self.assertIn("pharmacogenomics.fetch_pgxdb", catalog["sources"][0]["genomi_operations"])

    def test_call_operation_uses_pgxdb_lookup(self) -> None:
        def fake_fetch(base_url, path, *, query=None, raw_calls):
            raw_calls.append({"url": base_url + path, "query": query, "status": 200})
            if path == "/drug/atc_code/DB00065/":
                return {"ATC code of drug DB00065": [{"Atc code": "L04AB02", "Description": "Infliximab"}]}
            if path == "/atc/pgx/L04AB02/":
                return {
                    "ATC Pharmacogenomics for L04AB02": [
                        {
                            "DrugbankID": "DB00065",
                            "Drugname": "Infliximab",
                            "Variant_or_Haplotypes": "rs1061622",
                            "Sentence": "Allele G is associated with decreased response to infliximab.",
                            "Significance": "yes",
                        }
                    ]
                }
            raise AssertionError(path)

        with patch("genomi.capabilities.pharmacogenomics.pgxdb._fetch_json", side_effect=fake_fetch):
            result = call_operation("pharmacogenomics.fetch_pgxdb", {"drugbank_id": "DB00065", "rsid": "rs1061622"})

        self.assertEqual(result["summary"]["pgx_record_count"], 1)
        self.assertEqual(result["evidence_envelope"]["finding_state"], "evidence_present")
        self.assertIn(
            "pgxdb_evidence_present:public_pgx_context_only",
            result["evidence_envelope"]["guidance"],
        )


if __name__ == "__main__":
    unittest.main()
