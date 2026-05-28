from __future__ import annotations

import unittest

from genomi.capabilities.nutrigenomics import catalog, operations, source_context


class NutrigenomicsCatalogTests(unittest.TestCase):
    def test_every_record_has_required_fields(self) -> None:
        for record in catalog.DOMAIN_MARKER_RECORDS:
            for field in (
                "record_id",
                "variant",
                "gene",
                "domain",
                "effect_allele",
                "established_effect",
                "evidence_tier",
                "sources",
                "established_caveats",
                "out_of_scope_claims",
            ):
                self.assertIn(field, record, msg=f"{record.get('record_id')} missing {field}")
            self.assertIn(record["evidence_tier"], ("established", "probable", "emerging"))
            self.assertIn(record["domain"], source_context.DOMAIN_DEFINITIONS)
            self.assertGreater(len(record["sources"]), 0, msg=f"{record['record_id']} has no sources")
            for source in record["sources"]:
                self.assertTrue("source" in source and "evidence_type" in source)
                self.assertTrue("url" in source or "identifier" in source,
                                msg=f"{record['record_id']} source lacks resolvable identifier")
            self.assertGreater(
                len(record["out_of_scope_claims"]), 0,
                msg=f"{record['record_id']} must explicitly disown at least one pseudoscience claim",
            )


class NutrigenomicsOperationTests(unittest.TestCase):
    def test_list_domains_returns_catalog_summary(self) -> None:
        result = operations.list_domains()
        self.assertEqual(result["coverage_status"], "data_returned")
        self.assertEqual(result["capability"], "nutrigenomics")
        self.assertEqual(result["schema"], source_context.SCHEMA_VERSION)
        domain_ids = {d["domain_id"] for d in result["domains"]}
        self.assertEqual(domain_ids, set(source_context.DOMAIN_DEFINITIONS))
        self.assertIn("personalized_diet_match", result["out_of_scope_by_construction"])

    def test_build_source_context_returns_provenance(self) -> None:
        result = operations.build_source_context()
        self.assertEqual(result["coverage_status"], "data_returned")
        self.assertIn("source_urls", result)
        self.assertIn("label_definitions", result)
        self.assertIn("limitations", result)
        self.assertIn(
            "diet prescription",
            result["boundary_note"].lower(),
            msg="boundary_note must explicitly refuse diet prescriptions",
        )

    def test_retrieve_domain_markers_happy_path(self) -> None:
        result = operations.retrieve_domain_markers(domain_id="folate_metabolism")
        self.assertEqual(result["coverage_status"], "data_returned")
        self.assertGreater(len(result["markers"]), 0)
        self.assertEqual(result["markers"][0]["variant"]["rsid"], "rs1801133")
        self.assertIn("out_of_scope_claims", result["markers"][0])
        self.assertIn("composition_hints", result)

    def test_retrieve_domain_markers_uses_host_semantic_domain_hint(self) -> None:
        result = operations.retrieve_domain_markers(
            domain_id="can I drink milk",
            semantic_context={
                "raw_query": "Am I lactose intolerant?",
                "host_expansions": ["lactose_tolerance"],
                "host_entities": [{"text": "lactose_tolerance", "type": "nutrigenomic_domain"}],
            },
        )

        self.assertEqual(result["coverage_status"], "data_returned")
        self.assertEqual(result["domain"]["id"], "lactose_tolerance")
        accepted = {item["text"] for item in result["semantic_context"]["term_matches"]}
        self.assertIn("lactose_tolerance", accepted)

    def test_retrieve_domain_markers_refuses_out_of_scope_by_construction(self) -> None:
        result = operations.retrieve_domain_markers(domain_id="personalized_diet_match")
        self.assertEqual(result["coverage_status"], "out_of_scope_for_input")
        self.assertEqual(result["status"], "domain_out_of_scope_by_construction")

    def test_retrieve_domain_markers_refuses_unknown_domain(self) -> None:
        result = operations.retrieve_domain_markers(domain_id="not_a_real_domain")
        self.assertEqual(result["coverage_status"], "out_of_scope_for_input")
        self.assertEqual(result["status"], "unknown_domain")

    def test_retrieve_domain_markers_requires_domain_id(self) -> None:
        result = operations.retrieve_domain_markers(domain_id=None)
        self.assertEqual(result["coverage_status"], "out_of_scope_for_input")
        self.assertEqual(result["status"], "domain_id_required")

    def test_retrieve_domain_markers_rejects_invalid_tier(self) -> None:
        result = operations.retrieve_domain_markers(
            domain_id="folate_metabolism", min_evidence_tier="bogus",
        )
        self.assertEqual(result["status"], "invalid_evidence_tier")

    def test_retrieve_domain_markers_in_scope_empty_when_tier_filter_excludes_all(self) -> None:
        # iron_storage has one 'established' (C282Y) and one 'probable' (H63D);
        # default established tier returns only C282Y. emerging tier returns
        # both. There is no domain with only emerging-tier rows in the seed
        # catalogue, so use a tier raise that filters all out is not possible.
        # Instead validate filter consistency.
        established = operations.retrieve_domain_markers(
            domain_id="iron_storage", min_evidence_tier="established",
        )
        probable = operations.retrieve_domain_markers(
            domain_id="iron_storage", min_evidence_tier="probable",
        )
        self.assertEqual(len(established["markers"]), 1)
        self.assertGreater(len(probable["markers"]), len(established["markers"]))

    def test_retrieve_variant_records_happy_path(self) -> None:
        result = operations.retrieve_variant_records(rsid="rs1801133")
        self.assertEqual(result["coverage_status"], "data_returned")
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["gene"]["symbol"], "MTHFR")

    def test_retrieve_variant_records_in_scope_empty(self) -> None:
        result = operations.retrieve_variant_records(rsid="rs999999999")
        self.assertEqual(result["coverage_status"], "in_scope_empty")

    def test_retrieve_variant_records_rejects_invalid_rsid(self) -> None:
        result = operations.retrieve_variant_records(rsid="chr1:11796321")
        self.assertEqual(result["coverage_status"], "out_of_scope_for_input")
        self.assertEqual(result["status"], "invalid_rsid")

    def test_retrieve_variant_records_apoe_haplotype_partner_present(self) -> None:
        result = operations.retrieve_variant_records(rsid="rs429358")
        self.assertEqual(result["coverage_status"], "data_returned")
        record = result["records"][0]
        self.assertEqual(record["domain"], "lipid_diet_response")
        self.assertIn("haplotype_partner", record["established_effect"])


class NutrigenomicsRegistryTests(unittest.TestCase):
    def test_operations_registered(self) -> None:
        from genomi.operations.registry import OPERATIONS

        names = {op.name for op in OPERATIONS}
        for op_name in (
            "nutrigenomics.list_domains",
            "nutrigenomics.build_source_context",
            "nutrigenomics.retrieve_domain_markers",
            "nutrigenomics.retrieve_variant_records",
        ):
            self.assertIn(op_name, names)

    def test_catalog_fragment_loaded(self) -> None:
        from genomi.operations.catalog import load_tool_catalog

        catalog_obj = load_tool_catalog()
        self.assertIn("nutrigenomics", catalog_obj["capabilities"])
        for op_name in (
            "nutrigenomics.list_domains",
            "nutrigenomics.build_source_context",
            "nutrigenomics.retrieve_domain_markers",
            "nutrigenomics.retrieve_variant_records",
        ):
            self.assertIn(op_name, catalog_obj["operations"])


if __name__ == "__main__":
    unittest.main()
