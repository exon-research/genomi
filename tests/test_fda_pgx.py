from __future__ import annotations

import unittest
from unittest.mock import patch

from genomi.capabilities.pharmacogenomics.fda_pgx import lookup_fda_pgx
from genomi.evidence.sources import evidence_source_catalog
from genomi.operations import call_operation, list_operations

BIOMARKERS_HTML = """
<html><body>
<table>
  <tr><th>Drug</th><th>Therapeutic Area*</th><th>Biomarker†</th><th>Labeling Sections</th></tr>
  <tr><td>clopidogrel</td><td>Cardiology</td><td>CYP2C19</td><td>Warnings and Precautions; Clinical Pharmacology</td></tr>
</table>
</body></html>
"""


ASSOCIATIONS_HTML = """
<html><body>
<table>
  <tr><th>Drug</th><th>Gene</th><th>Affected Subgroups+</th><th>Description of Gene-Drug Interaction</th></tr>
  <tr><td>clopidogrel</td><td>CYP2C19</td><td>Poor metabolizers</td><td>Altered metabolism and therapeutic response.</td></tr>
</table>
</body></html>
"""


def _fake_fetch(url: str, *, raw_calls: list[dict[str, object]]) -> str:
    raw_calls.append({"url": url, "status": 200, "attempts": 1})
    if "association" in url:
        return ASSOCIATIONS_HTML
    return BIOMARKERS_HTML


class FdaPgxTests(unittest.TestCase):
    def test_lookup_returns_biomarker_and_association_rows(self) -> None:
        with patch("genomi.capabilities.pharmacogenomics.fda_pgx._fetch_text", side_effect=_fake_fetch):
            result = lookup_fda_pgx(
                drug="clopidogrel",
                gene="CYP2C19",
                biomarkers_url="https://example.test/biomarker",
                associations_url="https://example.test/association",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"]["row_count"], 2)
        self.assertEqual(result["summary"]["biomarker_labeling_count"], 1)
        self.assertEqual(result["summary"]["association_count"], 1)
        self.assertEqual(result["rows"][0]["source_id"], "fda_pharmacogenomics")
        self.assertEqual(result["rows"][1]["source_id"], "fda_pharmacogenetic_associations")
        self.assertNotIn("raw", result["rows"][0])
        self.assertEqual(result["record_research_payloads"][0]["captured_by"], "genomi call pharmacogenomics.fetch_fda_labels")
        self.assertEqual(result["record_research_payloads"][0]["source"]["source_id"], "fda_pgx")
        self.assertEqual(result["record_research_payloads"][0]["source"]["biomarkers_url"], "https://example.test/biomarker")
        self.assertEqual(result["record_research_payloads"][1]["source"]["associations_url"], "https://example.test/association")
        envelope = result["evidence_envelope"]
        self.assertEqual(envelope["finding_state"], "evidence_present")
        self.assertEqual(envelope["answer_readiness"], "scoped_answer_only")
        self.assertEqual(envelope["coverage"]["libraries"][0]["library"], "fda-pgx")
        self.assertEqual(envelope["observations"]["row_count"], 2)

    def test_lookup_filters_gene(self) -> None:
        with patch("genomi.capabilities.pharmacogenomics.fda_pgx._fetch_text", side_effect=_fake_fetch):
            result = lookup_fda_pgx(
                drug="clopidogrel",
                gene="CYP2D6",
                biomarkers_url="https://example.test/biomarker",
                associations_url="https://example.test/association",
            )

        self.assertEqual(result["status"], "no_matching_fda_pgx_records")
        self.assertEqual(result["summary"]["row_count"], 0)
        self.assertEqual(result["evidence_envelope"]["finding_state"], "not_observed_in_consulted_scope")
        self.assertIn(
            "not_observed_in_consulted_scope:fda_pgx_no_records_for_target",
            result["evidence_envelope"]["guidance"],
        )

    def test_lookup_can_include_raw_rows(self) -> None:
        with patch("genomi.capabilities.pharmacogenomics.fda_pgx._fetch_text", side_effect=_fake_fetch):
            result = lookup_fda_pgx(
                drug="clopidogrel",
                source="biomarkers",
                include_raw_rows=True,
                biomarkers_url="https://example.test/biomarker",
            )

        self.assertEqual(result["status"], "completed")
        self.assertIn("raw", result["rows"][0])

    def test_lookup_invalid_target_asks_required_question(self) -> None:
        result = lookup_fda_pgx()

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "invalid_target")
        self.assertEqual(result["unanswered_answer_components"][0]["missing_inputs"], ["drug", "gene"])
        self.assertEqual(result["evidence_envelope"]["finding_state"], "not_assessed")
        self.assertEqual(result["evidence_envelope"]["next_actions"][0]["action"], "provide_public_fda_pgx_target")

    def test_lookup_source_unavailable_asks_retry_question(self) -> None:
        def unavailable(url: str, *, raw_calls: list[dict[str, object]]) -> str:
            raw_calls.append({"url": url, "status": None, "attempts": 2, "error": "timeout"})
            return ""

        with patch("genomi.capabilities.pharmacogenomics.fda_pgx._fetch_text", side_effect=unavailable):
            result = lookup_fda_pgx(drug="clopidogrel")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "source_unavailable")
        self.assertEqual(len(result["warnings"]), 2)
        self.assertEqual(result["evidence_envelope"]["finding_state"], "not_assessed")
        self.assertEqual(result["evidence_envelope"]["coverage"]["unavailable_sources"], ["fda_pgx"])
        self.assertEqual(result["evidence_envelope"]["next_actions"][0]["action"], "use_alternate_pgx_source_or_retry")

    def test_fda_pgx_lookup_is_agent_tool_and_source_catalog_entry(self) -> None:
        tools = {tool["name"]: tool for tool in list_operations(capability="pharmacogenomics")}
        self.assertIn("pharmacogenomics.fetch_fda_labels", tools)
        self.assertEqual(tools["pharmacogenomics.fetch_fda_labels"]["annotations"]["externalIO"], ["fda_web"])
        self.assertIn("selected_public_targets", tools["pharmacogenomics.fetch_fda_labels"]["annotations"]["dataAccess"])

        sources = {source["source_id"]: source for source in evidence_source_catalog()["sources"]}
        self.assertEqual(sources["fda_pharmacogenomics"]["adapter_status"], "implemented_web_fetch")
        self.assertIn("pharmacogenomics.fetch_fda_labels", sources["fda_pharmacogenomics"]["genomi_operations"])
        self.assertEqual(sources["fda_pharmacogenetic_associations"]["adapter_status"], "implemented_web_fetch")
        self.assertIn("pharmacogenomics.fetch_fda_labels", sources["fda_pharmacogenetic_associations"]["genomi_operations"])

    def test_call_operation_uses_fda_pgx_lookup(self) -> None:
        with patch(
            "genomi.operations.fda_pgx.lookup_fda_pgx",
            return_value={"status": "completed", "rows": []},
        ) as lookup:
            result = call_operation(
                "pharmacogenomics.fetch_fda_labels",
                {
                    "drug": "clopidogrel",
                    "gene": "CYP2C19",
                    "source": "associations",
                    "include_raw_rows": True,
                    "limit": 5,
                    "biomarkers_url": "https://example.test/biomarker",
                    "associations_url": "https://example.test/association",
                },
            )

        self.assertEqual(result["status"], "completed")
        lookup.assert_called_once()
        self.assertEqual(lookup.call_args.kwargs["drug"], "clopidogrel")
        self.assertEqual(lookup.call_args.kwargs["gene"], "CYP2C19")
        self.assertEqual(lookup.call_args.kwargs["source"], "associations")
        self.assertTrue(lookup.call_args.kwargs["include_raw_rows"])
        self.assertEqual(lookup.call_args.kwargs["limit"], 5)


if __name__ == "__main__":
    unittest.main()
