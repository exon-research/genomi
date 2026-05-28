from __future__ import annotations

import json
from importlib import resources as importlib_resources

from genomi.active_genome_index.active_genome_index import create_active_genome_index
from genomi.operations import (
    OPERATIONS,
    TOOL_CATALOG,
    TOOL_CATALOG_OPERATIONS,
    OperationError,
    all_operations,
    call_operation,
    list_operations,
)
from genomi.runtime import context as runtime_context

from _genomi_runtime_helpers import (
    DEFAULT_TASK_ENTRY_TOOLS,
    GenomiRuntimeTestCase,
)


class GenomiRuntimeCatalogTests(GenomiRuntimeTestCase):
    def test_tool_catalog_groups_and_backs_registered_operations(self) -> None:
        self.assertEqual(TOOL_CATALOG["schema"], "genomi-tool-catalog-v1")
        registered_names = {operation.name for operation in OPERATIONS}
        self.assertEqual(set(TOOL_CATALOG_OPERATIONS), registered_names)

        grouped_names: set[str] = set()
        for capability_id in TOOL_CATALOG["capability_order"]:
            capability = TOOL_CATALOG["capabilities"][capability_id]
            self.assertTrue(capability["title"], capability_id)
            self.assertTrue(capability["start_when"], capability_id)
            self.assertTrue(capability["skill_documents"], capability_id)
            self.assertTrue(capability["entry_operations"], capability_id)
            grouped_names.update(capability["operations"])
            for operation_name in capability["operations"]:
                operation = TOOL_CATALOG_OPERATIONS[operation_name]
                self.assertEqual(operation["capability"], capability_id, operation_name)
                self.assertEqual(operation["input_schema"].get("type"), "object", operation_name)
                self.assertTrue(operation["description"].strip(), operation_name)

        self.assertEqual(grouped_names, registered_names)
        # After the dispatcher refactor, default tools/list is only the base
        # capabilities (genomi + journal namespaces) plus the dispatcher.
        listed = {tool["name"] for tool in list_operations()}
        self.assertEqual(listed, DEFAULT_TASK_ENTRY_TOOLS)

    def test_refactored_package_layout_preserves_public_imports(self) -> None:
        catalog_base = importlib_resources.files("genomi.operations").joinpath("catalog_base.json")
        self.assertTrue(catalog_base.is_file())
        pgx_catalog = importlib_resources.files("genomi.capabilities.pharmacogenomics").joinpath("tool_catalog.json")
        ancestry_catalog = importlib_resources.files("genomi.capabilities.ancestry").joinpath("tool_catalog.json")
        prs_catalog = importlib_resources.files("genomi.capabilities.prs").joinpath("tool_catalog.json")
        self.assertTrue(pgx_catalog.is_file())
        self.assertTrue(ancestry_catalog.is_file())
        self.assertTrue(prs_catalog.is_file())

        from genomi import operations
        from genomi.active_genome_index.build import create_active_genome_index as build_create_active_genome_index
        from genomi.active_genome_index.active_genome_index import (
            create_active_genome_index as package_create_active_genome_index,
        )
        from genomi.active_genome_index.query import query_variant
        from genomi.active_genome_index.readiness import active_genome_index_readiness
        from genomi.capabilities.pharmacogenomics.review import (
            review_medication_interaction,
        )
        from genomi.evidence.clinvar import match_clinvar_variants
        from genomi.evidence.population import fetch_gnomad_variant
        from genomi.evidence.research import record_research_findings
        from genomi.operations.discovery import (
            list_operations as discovery_list_operations,
        )
        from genomi.operations.registry import call_operation as registry_call_operation
        from genomi.operations.types import OperationError as PackageOperationError
        from genomi.runtime.paths import genomi_data_root

        self.assertIs(create_active_genome_index, package_create_active_genome_index)
        self.assertIs(create_active_genome_index, build_create_active_genome_index)
        self.assertIsNotNone(operations.get_operation("sequence.analyze"))
        self.assertIs(OperationError, PackageOperationError)
        self.assertIs(call_operation, registry_call_operation)
        self.assertIs(list_operations, discovery_list_operations)
        self.assertTrue(callable(review_medication_interaction))
        self.assertTrue(callable(match_clinvar_variants))
        self.assertTrue(callable(fetch_gnomad_variant))
        self.assertTrue(callable(record_research_findings))
        self.assertTrue(callable(genomi_data_root))
        self.assertTrue(callable(query_variant))
        self.assertTrue(callable(active_genome_index_readiness))

    def test_operations_expose_agent_tool_groups(self) -> None:
        tools = list_operations()
        names = {tool["name"] for tool in tools}
        expanded_tools = all_operations()
        expanded_names = {tool["name"] for tool in expanded_tools}
        self.assertLess(len(tools), len(expanded_tools))
        self.assertEqual(names, DEFAULT_TASK_ENTRY_TOOLS)
        self.assertTrue(names <= expanded_names)
        expected_namespace_flows = {
            "active_genome_index": {"active_genome_index.summarize", "active_genome_index.classify_genotype_support"},
            "variant": {
                "variant.resolve",
                "variant.gather_allele_context",
                "variant.gather_gene_context",
            },
            "phenotype": {"phenotype.plan_risk_investigation", "phenotype.compare_gene_hpo_evidence"},
            "pathway": {"pathway.retrieve_members"},
            "cell_type": {"cell_type.retrieve_markers"},
            "region": {"region.retrieve_features"},
            "sequence": {"sequence.analyze", "sequence.translate"},
            "pharmacogenomics": {"pharmacogenomics.review_medication", "pharmacogenomics.fetch_clinpgx"},
            "gwas": {"gwas.compare_variant_associations", "gwas.compare_gene_associations"},
            "functional_genomics": {
                "functional_genomics.compare_gene_perturbation",
                "functional_genomics.import_perturbation_table",
                "functional_genomics.query_geo",
            },
            "ancestry": {"ancestry.list_reference_panels", "ancestry.estimate_population_context", "ancestry.project_pca"},
            "prs": {"prs.search_scores", "prs.calculate_score", "prs.import_scoring_file"},
            "research": {"research.list_sources", "research.build_target_packet", "research.record"},
            "gnomad": {"gnomad.fetch_population_frequency"},
            "journal": {"journal.append_entry", "journal.search_entries", "journal.export_memory"},
            "genomi": {"genomi.invoke", "genomi.check_libraries", "genomi.parse_source"},
            "clinvar": {"clinvar.match_variants", "clinvar.scan_candidates"},
            "nutrigenomics": {"nutrigenomics.list_domains", "nutrigenomics.retrieve_domain_markers"},
        }
        for namespace, expected in expected_namespace_flows.items():
            self.assertTrue(expected <= expanded_names, namespace)
            self.assertTrue(all(name.startswith(f"{namespace}.") for name in expected), namespace)
        self.assertTrue(all("inputSchema" in tool for tool in tools))
        by_name = {tool["name"]: tool for tool in expanded_tools}
        capability_namespaces: dict[str, set[str]] = {}
        for tool in expanded_tools:
            capability = tool["annotations"]["toolCapability"]
            namespace = tool["name"].split(".", 1)[0]
            capability_namespaces.setdefault(capability, set()).add(namespace)
        self.assertEqual(capability_namespaces["variant-evidence"], {"variant"})
        self.assertEqual(capability_namespaces["journal"], {"journal", "research"})
        self.assertEqual(capability_namespaces["gnomad"], {"gnomad"})
        self.assertEqual(capability_namespaces["clinvar"], {"clinvar"})
        self.assertEqual(capability_namespaces["ancestry"], {"ancestry"})
        self.assertEqual(capability_namespaces["polygenic-score"], {"prs"})
        review_annotations = by_name["pharmacogenomics.review_medication"]["annotations"]
        self.assertIn("operationScope", review_annotations)
        self.assertIn("mutating", review_annotations)
        self.assertIn("externalIO", review_annotations)
        self.assertIn("dataAccess", review_annotations)
        self.assertIn("toolCapability", review_annotations)
        self.assertIn("discoveryRole", review_annotations)
        self.assertIn("trustBoundary", review_annotations)
        for tool in expanded_tools:
            self.assertTrue(tool["description"].strip(), tool["name"])
        self.assertEqual(by_name["pharmacogenomics.review_medication"]["annotations"]["toolCapability"], "pharmacogenomics")
        self.assertEqual(by_name["pharmacogenomics.review_medication"]["annotations"]["discoveryRole"], "entry_tool")
        for operation in (
            "clinvar.scan_candidates",
            "pharmacogenomics.review_medication",
            "gwas.compare_variant_associations",
            "functional_genomics.compare_gene_perturbation",
            "phenotype.plan_risk_investigation",
            "phenotype.compare_disease_evidence",
        ):
            self.assertIn("evidence_view", by_name[operation]["annotations"]["produces"])
            self.assertIn("decision_evidence", by_name[operation]["annotations"]["produces"])
            self.assertIn("candidate_matrix", by_name[operation]["annotations"]["produces"])
            self.assertIn("top_observed_candidate", by_name[operation]["annotations"]["produces"])

    def test_tool_discovery_filters_by_capability(self) -> None:
        default_names = {tool["name"] for tool in list_operations()}
        self.assertEqual(default_names, DEFAULT_TASK_ENTRY_TOOLS)

        pgx_tools = list_operations(capability="pharmacogenomics")
        pgx_names = {tool["name"] for tool in pgx_tools}

        self.assertIn("pharmacogenomics.review_medication", pgx_names)
        self.assertIn("pharmacogenomics.fetch_clinpgx", pgx_names)
        self.assertTrue(all(tool["annotations"]["toolCapability"] == "pharmacogenomics" for tool in pgx_tools))
        self.assertEqual(
            {tool["name"] for tool in pgx_tools if tool["annotations"]["discoveryRole"] == "entry_tool"},
            {"pharmacogenomics.review_medication"},
        )

        sequence_names = {tool["name"] for tool in list_operations(capability="sequence")}
        self.assertIn("sequence.analyze", sequence_names)
        self.assertIn("sequence.match_reference", sequence_names)
        self.assertIn("sequence.translate", sequence_names)
        self.assertIn("sequence.find_orfs", sequence_names)
        sequence_tools = list_operations(capability="sequence")
        self.assertTrue(all(tool["annotations"]["toolCapability"] == "sequence" for tool in sequence_tools))

        clinvar_tools = list_operations(capability="clinvar")
        clinvar_names = {tool["name"] for tool in clinvar_tools}
        self.assertEqual(clinvar_names, {"clinvar.scan_candidates", "clinvar.match_variants"})
        self.assertTrue(all(tool["annotations"]["toolCapability"] == "clinvar" for tool in clinvar_tools))

        expanded_names = {tool["name"] for tool in all_operations()}
        self.assertIn("sequence.translate", expanded_names)
        self.assertIn("research.list_sources", expanded_names)
        ancestry_tools = list_operations(capability="ancestry")
        ancestry_names = {tool["name"] for tool in ancestry_tools}
        self.assertEqual(
            ancestry_names,
            {
                "ancestry.list_reference_panels",
                "ancestry.build_source_context",
                "ancestry.check_sample_overlap",
                "ancestry.project_pca",
                "ancestry.estimate_population_context",
            },
        )
        self.assertTrue(all(tool["annotations"]["toolCapability"] == "ancestry" for tool in ancestry_tools))

        prs_tools = list_operations(capability="polygenic-score")
        prs_names = {tool["name"] for tool in prs_tools}
        self.assertEqual(
            prs_names,
            {
                "prs.search_scores",
                "prs.fetch_score_metadata",
                "prs.import_scoring_file",
                "prs.list_imported_scores",
                "prs.check_score_overlap",
                "prs.calculate_score",
                "prs.build_source_context",
            },
        )
        self.assertTrue(all(tool["annotations"]["toolCapability"] == "polygenic-score" for tool in prs_tools))

        namespace_names = {tool["name"] for tool in list_operations(namespace="active_genome_index")}
        self.assertEqual(
            namespace_names,
            {
                "active_genome_index.summarize",
                "active_genome_index.classify_callset_qc",
                "active_genome_index.classify_genotype_support",
                "active_genome_index.classify_region_callability",
            },
        )

        with self.assertRaises(OperationError) as raised:
            list_operations(capability="everything")
        self.assertEqual(raised.exception.code, "invalid_params")

        with self.assertRaises(OperationError) as raised_namespace:
            list_operations(namespace="everything")
        self.assertEqual(raised_namespace.exception.code, "invalid_params")



    def test_gene_list_tool_contracts_are_non_overlapping(self) -> None:
        all_by_name = {tool["name"]: tool for tool in all_operations()}
        all_tools = set(all_by_name)

        self.assertIn("phenotype.compare_gene_hpo_evidence", all_tools)
        self.assertIn("gwas.compare_gene_associations", all_tools)
        self.assertIn("phenotype.compare_drug_target_evidence", all_tools)
        self.assertIn("phenotype.retrieve_trait_gene_records", all_tools)
        phenotype_schema = all_by_name["phenotype.compare_gene_hpo_evidence"]["inputSchema"]
        self.assertIn("hpo_ids", phenotype_schema["description"])
        disease_schema = all_by_name["phenotype.compare_disease_evidence"]["inputSchema"]
        self.assertIn("genes", disease_schema["properties"])
        self.assertIn("gene_symbols", disease_schema["properties"])
        self.assertIn("gwas.compare_gene_associations", all_tools)
        gwas_gene_schema = all_by_name["gwas.compare_gene_associations"]["inputSchema"]
        self.assertEqual(gwas_gene_schema["required"], ["phenotype", "genes"])
        self.assertIn("phenotype.compare_drug_target_evidence", all_tools)
        self.assertIn("phenotype.compare_gene_hpo_evidence", all_tools)
        drug_schema = all_by_name["phenotype.compare_drug_target_evidence"]["inputSchema"]
        self.assertEqual(drug_schema["required"], ["genes"])
        self.assertIn("drug", drug_schema["description"])
        self.assertIn("drug_class", drug_schema["description"])
        self.assertIn("mechanism", drug_schema["description"])
        self.assertIn("phenotype.compare_drug_target_evidence", all_tools)
        self.assertIn("gwas.compare_gene_associations", all_tools)
        self.assertIn("phenotype.compare_gene_hpo_evidence", all_tools)

    def test_tool_input_schemas_are_function_parameter_compatible(self) -> None:
        forbidden_top_level_keywords = {"oneOf", "anyOf", "allOf", "enum", "not"}

        self.assertIn("schema_fragments", TOOL_CATALOG)
        self.assertIn("property_groups", TOOL_CATALOG["schema_fragments"])
        self.assertIn("variant_locus", TOOL_CATALOG["schema_fragments"]["property_groups"])
        self.assertIn(
            "#/schema_fragments/properties/local_path",
            json.dumps(TOOL_CATALOG_OPERATIONS),
        )
        self.assertIn(
            "x_genomi_property_groups",
            json.dumps(TOOL_CATALOG_OPERATIONS),
        )
        for tool in all_operations():
            schema = tool["inputSchema"]
            self.assertEqual(schema.get("type"), "object", tool["name"])
            self.assertFalse(forbidden_top_level_keywords & set(schema), tool["name"])
            self.assertNotIn('"$ref"', json.dumps(schema), tool["name"])
            self.assertNotIn("x_genomi_property_groups", schema, tool["name"])

        by_name = {tool["name"]: tool for tool in all_operations()}
        variant_properties = by_name["variant.resolve"]["inputSchema"]["properties"]
        for key in ("chrom", "pos", "ref", "alt"):
            self.assertIn(key, variant_properties)
        self.assertEqual(
            by_name["phenotype.compare_gene_hpo_evidence"]["inputSchema"]["properties"]["db"],
            {"type": "string", "description": "Local filesystem path."},
        )
        self.assertEqual(
            by_name["variant.resolve"]["inputSchema"]["properties"]["limit"],
            {"type": "integer", "default": 20},
        )

    def test_operation_names_are_descriptive(self) -> None:
        tools = all_operations()
        names = [tool["name"] for tool in tools]

        self.assertEqual(len(names), len(set(names)))
        allowed_verbs = {
            "approve",
            "bootstrap",
            "build",
            "call",
            "check",
            "classify",
            "clear",
            "compare",
            "describe",
            "discover",
            "fetch",
            "find",
            "gather",
            "import",
            "invoke",
            "install",
            "list",
            "match",
            "normalize",
            "parse",
            "plan",
            "preflight",
            "prepare",
            "query",
            "rank",
            "record",
            "refresh",
            "render",
            "rename",
            "retrieve",
            "resolve",
            "revoke",
            "review",
            "run",
            "scan",
            "search",
            "select",
            "set",
            "summarize",
            "translate",
            "validate",
            "verify",
            "analyze",
            "append",
            "assign",
            "export",
            "estimate",
            "link",
            "project",
            "calculate",
        }
        for tool in tools:
            name = tool["name"]
            verb = name.split(".", 1)[1].split("_", 1)[0]
            self.assertIn(verb, allowed_verbs, name)
            self.assertGreaterEqual(len(tool.get("description") or ""), 20, name)
            annotations = tool["annotations"]
            self.assertIn("toolCapability", annotations)
            self.assertIn("discoveryRole", annotations)
            self.assertTrue(annotations.get("produces"), name)


if __name__ == "__main__":
    import unittest

    unittest.main()
