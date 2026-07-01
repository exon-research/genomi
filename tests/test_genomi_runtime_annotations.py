from __future__ import annotations

from genomi.capabilities.ancestry import policy as ancestry_policy
from genomi.operations import all_operations, call_operation

from tests.support.runtime.genomi import GenomiRuntimeTestCase


class GenomiRuntimeAnnotationsTests(GenomiRuntimeTestCase):
    def test_operation_annotations_expose_scope_trust_and_external_io(self) -> None:
        by_name = {tool["name"]: tool for tool in all_operations()}

        current = by_name["genomi.describe_context"]["annotations"]
        self.assertEqual(current["operationScope"], "read")
        self.assertFalse(current["mutating"])
        self.assertEqual(current["privacyScope"], "metadata_only")
        self.assertIn("local_artifact_metadata", current["dataAccess"])

        invoke = by_name["genomi.invoke"]["annotations"]
        self.assertEqual(invoke["operationScope"], "read")
        self.assertIn("local_private_artifacts_when_supplied", invoke["dataAccess"])
        self.assertIn("active_genome_index_when_selected", invoke["dataAccess"])

        parse = by_name["genomi.parse_source"]["annotations"]
        self.assertEqual(parse["operationScope"], "write")
        self.assertTrue(parse["mutating"])
        self.assertEqual(parse["privacyScope"], "local_private")
        self.assertIn("genome_source_file", parse["dataAccess"])
        self.assertIn("active_genome_index_created_or_updated", parse["dataAccess"])
        parse_properties = by_name["genomi.parse_source"]["inputSchema"]["properties"]
        self.assertIn("parallel_workers", parse_properties)
        self.assertEqual(
            by_name["genomi.parse_source"]["annotations"]["title"],
            "Using Genomi to parse a genome source",
        )
        background_job = by_name["genomi.check_background_job"]["annotations"]
        self.assertIn("background_job_result", background_job["dataAccess"])
        self.assertIn("active_genome_index_when_job_targets_agi", background_job["dataAccess"])
        libraries = by_name["genomi.check_libraries"]["annotations"]
        self.assertEqual(libraries["operationScope"], "read")
        self.assertFalse(libraries["mutating"])
        self.assertEqual(libraries["privacyScope"], "metadata_only")
        self.assertIn("library_inventory", libraries["produces"])

        clinvar = by_name["clinvar.scan_candidates"]["annotations"]
        self.assertEqual(
            clinvar["dependencyContract"],
            {
                "installedLibraries": ["clinvar-grch38", "clinvar-grch37"],
                "missingInstalledLibraryStatus": "requires_library_install",
                "libraryCheckOperation": "genomi.check_libraries",
            },
        )

        pgx = by_name["pharmacogenomics.review_medication"]["annotations"]
        self.assertEqual(pgx["operationScope"], "read")
        self.assertFalse(pgx["mutating"])
        self.assertEqual(pgx["externalIO"], ["clinpgx_api", "pgxdb_api", "fda_web"])
        self.assertEqual(
            pgx["dependencyContract"],
            {
                "externalNetwork": ["clinpgx_api", "pgxdb_api", "fda_web"],
                "externalUnavailableStatus": "source_unavailable",
            },
        )
        self.assertIn("evidence_envelope", pgx["produces"])
        self.assertIn("medication_review_matrix", pgx["produces"])
        self.assertIn("evidence_view", pgx["produces"])
        self.assertIn("active_genome_index_when_selected", pgx["dataAccess"])
        self.assertIn("evidence_components", pgx["produces"])
        self.assertIn("target_inventory", pgx["produces"])

        requirements = by_name["pharmacogenomics.describe_gene_requirements"]["annotations"]
        self.assertEqual(requirements["operationScope"], "read")
        self.assertFalse(requirements["mutating"])
        self.assertEqual(requirements["privacyScope"], "metadata_only")
        self.assertIn("pharmacogene_requirement_catalog", requirements["produces"])

        pharmcat = by_name["pharmacogenomics.run_pharmcat"]["annotations"]
        self.assertEqual(pharmcat["operationScope"], "write")
        self.assertTrue(pharmcat["mutating"])
        self.assertEqual(pharmcat["externalIO"], [])
        self.assertEqual(pharmcat["dependencyContract"]["installedLibraries"], ["pharmcat"])
        self.assertEqual(pharmcat["dependencyContract"]["missingInstalledLibraryStatus"], "requires_library_install")
        self.assertEqual(pharmcat["dataAccess"], ["active_genome_index"])

        preflight = by_name["pharmacogenomics.preflight_pharmcat"]["annotations"]
        self.assertEqual(preflight["operationScope"], "read")
        self.assertFalse(preflight["mutating"])
        self.assertEqual(preflight["externalIO"], [])
        self.assertEqual(preflight["dataAccess"], ["active_genome_index"])

        outside = by_name["pharmacogenomics.validate_outside_call_tsv"]["annotations"]
        self.assertEqual(outside["operationScope"], "read")
        self.assertFalse(outside["mutating"])
        self.assertEqual(outside["externalIO"], [])
        self.assertEqual(outside["dataAccess"], ["local_private_artifact"])

        pharmcat_import = by_name["pharmacogenomics.import_pharmcat_artifacts"]["annotations"]
        self.assertEqual(pharmcat_import["operationScope"], "read")
        self.assertFalse(pharmcat_import["mutating"])
        self.assertEqual(pharmcat_import["externalIO"], [])
        self.assertEqual(pharmcat_import["dataAccess"], ["local_private_artifacts"])

        outside_prepare = by_name["pharmacogenomics.prepare_outside_call_tsv"]["annotations"]
        self.assertEqual(outside_prepare["operationScope"], "write")
        self.assertTrue(outside_prepare["mutating"])
        self.assertEqual(outside_prepare["externalIO"], [])
        self.assertEqual(outside_prepare["dataAccess"], ["local_private_artifact"])

        clinpgx = by_name["pharmacogenomics.fetch_clinpgx"]["annotations"]
        self.assertEqual(clinpgx["operationScope"], "read")
        self.assertFalse(clinpgx["mutating"])
        self.assertEqual(clinpgx["externalIO"], ["clinpgx_api"])
        self.assertIn("selected_public_targets", clinpgx["dataAccess"])

        fda = by_name["pharmacogenomics.fetch_fda_labels"]["annotations"]
        self.assertEqual(fda["operationScope"], "read")
        self.assertFalse(fda["mutating"])
        self.assertEqual(fda["externalIO"], ["fda_web"])
        self.assertIn("selected_public_targets", fda["dataAccess"])

        pgxdb = by_name["pharmacogenomics.fetch_pgxdb"]["annotations"]
        self.assertEqual(pgxdb["operationScope"], "read")
        self.assertFalse(pgxdb["mutating"])
        self.assertEqual(pgxdb["externalIO"], ["pgxdb_api"])
        self.assertIn("selected_public_targets", pgxdb["dataAccess"])

        gwas = by_name["gwas.compare_variant_associations"]["annotations"]
        self.assertEqual(gwas["externalIO"], ["gwas_catalog_api"])
        self.assertEqual(gwas["dependencyContract"]["externalNetwork"], ["gwas_catalog_api"])
        self.assertEqual(gwas["dependencyContract"]["externalUnavailableStatus"], "source_unavailable")
        self.assertIn("population-trait", by_name["gwas.compare_variant_associations"]["description"])

        gnomad = by_name["gnomad.fetch_population_frequency"]["annotations"]
        self.assertEqual(gnomad["externalIO"], ["gnomad_api"])
        gnomad_schema = by_name["gnomad.fetch_population_frequency"]["inputSchema"]
        self.assertEqual(
            set(gnomad_schema["properties"]),
            {
                "sync_shared",
                "dataset",
                "genome_build",
                "api_url",
                "db",
                "shared_db",
                "chrom",
                "pos",
                "ref",
                "alt",
            },
        )
        self.assertEqual(
            gnomad["dependencyContract"],
            {
                "externalNetwork": ["gnomad_api"],
                "externalUnavailableStatus": "source_unavailable",
            },
        )
        self.assertNotIn("installedLibraries", gnomad["dependencyContract"])

        pathway = by_name["pathway.retrieve_members"]["annotations"]
        self.assertEqual(pathway["dependencyContract"]["installedLibraries"], ["msigdb-hallmark"])
        self.assertEqual(pathway["dependencyContract"]["externalNetwork"], ["reactome_api", "kegg_api"])
        self.assertEqual(pathway["dependencyContract"]["localResources"], ["msigdb_hallmark_gmt"])

        cell_marker_schema = by_name["cell_type.retrieve_markers"]["inputSchema"]
        self.assertEqual(
            set(cell_marker_schema["properties"]),
            {
                "cell_type_id_or_name",
                "cell_type_id",
                "cell_type_name",
                "source",
                "species",
                "marker_table",
                "hpa_api_base",
                "limit",
                "semantic_context",
            },
        )

        region = by_name["region.retrieve_features"]["annotations"]
        self.assertEqual(
            region["dependencyContract"]["installedLibraries"],
            ["gencode-grch38", "gencode-grch37", "encode-ccre-grch38"],
        )
        self.assertNotIn("externalNetwork", region["dependencyContract"])
        self.assertEqual(
            region["dependencyContract"]["localResources"],
            ["local_gencode_gtf", "local_encode_ccre_bed"],
        )

        hpo = by_name["phenotype.compare_gene_hpo_evidence"]["annotations"]
        self.assertEqual(hpo["dependencyContract"]["installedLibraries"], ["hpo"])

        risk = by_name["phenotype.plan_risk_investigation"]["annotations"]
        self.assertEqual(risk["discoveryRole"], "focused_tool")

        trait_gene_records = by_name["phenotype.retrieve_trait_gene_records"]["annotations"]
        self.assertEqual(trait_gene_records["externalIO"], ["opentargets_api"])
        trait_schema = by_name["phenotype.retrieve_trait_gene_records"]["inputSchema"]
        self.assertEqual(trait_schema["required"], ["trait"])
        self.assertNotIn("source_records", trait_schema["properties"])
        self.assertNotIn("search_stored_research", trait_schema["properties"])
        self.assertNotIn("db", trait_schema["properties"])
        self.assertIn("gene_records", trait_gene_records["produces"])
        self.assertIn("records_by_gene", trait_gene_records["produces"])

        gwas_gene = by_name["gwas.compare_gene_associations"]["annotations"]
        gwas_schema = by_name["gwas.compare_gene_associations"]["inputSchema"]
        self.assertNotIn("source_records", gwas_schema["properties"])
        self.assertNotIn("answer", gwas_gene["produces"])
        self.assertIn("evidence_records", gwas_gene["produces"])
        self.assertIn("coverage", gwas_gene["produces"])

        drug_gene = by_name["phenotype.compare_drug_target_evidence"]["annotations"]
        self.assertEqual(drug_gene["toolCapability"], "phenotype-gene")
        drug_schema = by_name["phenotype.compare_drug_target_evidence"]["inputSchema"]
        self._assert_source_records_require_source_verification(drug_schema)
        self._assert_source_record_import_contract(drug_gene)
        self.assertNotIn("answer", drug_gene["produces"])
        self.assertIn("drug_or_drug_class_or_mechanism", drug_gene["requires"])

        disease_drug_targets = by_name["phenotype.retrieve_disease_drug_targets"]["annotations"]
        self.assertEqual(disease_drug_targets["toolCapability"], "phenotype-gene")
        self.assertEqual(disease_drug_targets["externalIO"], ["opentargets_api"])
        self.assertIn("disease_anchor", disease_drug_targets["requires"])
        self.assertIn("targets", disease_drug_targets["produces"])
        self.assertIn("source_records", disease_drug_targets["produces"])
        self.assertIn("coverage_state", disease_drug_targets["produces"])

        phenotype_gene = by_name["phenotype.compare_gene_hpo_evidence"]["annotations"]
        self.assertEqual(phenotype_gene["toolCapability"], "phenotype-gene")
        self.assertEqual(phenotype_gene["externalIO"], ["hpo_public_annotation_files"])
        phenotype_schema = by_name["phenotype.compare_gene_hpo_evidence"]["inputSchema"]
        self._assert_source_records_require_source_verification(phenotype_schema)
        self._assert_source_record_import_contract(phenotype_gene)
        self.assertNotIn("answer", phenotype_gene["produces"])
        self.assertIn("evidence_records", phenotype_gene["produces"])

        risk = by_name["phenotype.plan_risk_investigation"]["annotations"]
        self.assertEqual(risk["operationScope"], "read")
        self.assertFalse(risk["mutating"])
        self.assertEqual(risk["externalIO"], [])
        self.assertIn("selected_public_targets", risk["dataAccess"])
        self.assertIn("active_genome_index_when_selected", risk["dataAccess"])

        disease = by_name["phenotype.compare_disease_evidence"]["annotations"]
        self.assertEqual(disease["operationScope"], "read")
        self.assertFalse(disease["mutating"])
        self.assertEqual(disease["externalIO"], ["hpo_public_annotation_files", "gencc_public_download"])
        self.assertIn("selected_public_targets", disease["dataAccess"])
        self.assertIn("candidate_diseases_or_genes_or_source_records", disease["requires"])
        disease_schema = by_name["phenotype.compare_disease_evidence"]["inputSchema"]
        self._assert_source_records_require_source_verification(disease_schema)
        self._assert_source_record_import_contract(disease)
        self.assertIn("hpo_disease_annotation_evidence", disease["produces"])

        primary_gene_disease = by_name["phenotype.retrieve_gene_disease_associations"]["annotations"]
        self.assertEqual(primary_gene_disease["operationScope"], "read")
        self.assertFalse(primary_gene_disease["mutating"])
        self.assertEqual(primary_gene_disease["externalIO"], ["gencc_public_download"])
        self.assertIn("selected_public_targets", primary_gene_disease["dataAccess"])
        self.assertIn("candidate_genes", primary_gene_disease["requires"])
        self.assertIn("associations", primary_gene_disease["produces"])
        self.assertIn("coverage_state", primary_gene_disease["produces"])

        seq = by_name["sequence.analyze"]["annotations"]
        self.assertEqual(seq["operationScope"], "read")
        self.assertFalse(seq["mutating"])
        self.assertEqual(seq["externalIO"], [])
        self.assertIn("operation_parameters", seq["dataAccess"])

        screen = by_name["functional_genomics.compare_gene_perturbation"]["annotations"]
        self.assertEqual(screen["operationScope"], "read")
        self.assertFalse(screen["mutating"])
        self.assertEqual(
            screen["externalIO"],
            ["biogrid_orcs_api", "depmap_public_download", "ncbi_geo_eutilities", "ncbi_geo_ftp"],
        )
        self.assertIn("selected_public_targets", screen["dataAccess"])
        screen_schema = by_name["functional_genomics.compare_gene_perturbation"]["inputSchema"]
        self._assert_source_records_require_source_verification(screen_schema)
        self._assert_source_record_import_contract(screen)

        screen_retrieve = by_name["functional_genomics.retrieve_perturbation_records"]["annotations"]
        self.assertEqual(screen_retrieve["operationScope"], "read")
        self.assertFalse(screen_retrieve["mutating"])
        self.assertEqual(screen_retrieve["externalIO"], ["biogrid_orcs_api", "depmap_public_download"])
        self.assertIn("source_records", screen_retrieve["produces"])
        self.assertIn("coverage_state", screen_retrieve["produces"])

        screen_geo = by_name["functional_genomics.query_geo"]["annotations"]
        self.assertEqual(screen_geo["operationScope"], "read")
        self.assertFalse(screen_geo["mutating"])
        self.assertEqual(screen_geo["externalIO"], ["ncbi_geo_eutilities", "ncbi_geo_ftp"])
        self.assertEqual(
            screen_geo["dependencyContract"]["externalNetwork"],
            ["ncbi_geo_eutilities", "ncbi_geo_ftp"],
        )
        self.assertIn("geo_hits", screen_geo["produces"])
        self.assertIn("download_candidates", screen_geo["produces"])

        screen_table = by_name["functional_genomics.import_perturbation_table"]["annotations"]
        self.assertEqual(screen_table["operationScope"], "read")
        self.assertFalse(screen_table["mutating"])
        self.assertEqual(screen_table["externalIO"], [])
        self.assertIn("selected_public_targets", screen_table["dataAccess"])

        screen_answer = by_name["functional_genomics.compare_gene_perturbation"]["annotations"]
        self.assertEqual(screen_answer["operationScope"], "read")
        self.assertFalse(screen_answer["mutating"])
        self.assertEqual(
            screen_answer["externalIO"],
            ["biogrid_orcs_api", "depmap_public_download", "ncbi_geo_eutilities", "ncbi_geo_ftp"],
        )
        self.assertIn("evidence_view", screen_answer["produces"])
        self.assertIn("native_retrieval", screen_answer["produces"])
        self.assertIn("top_observed_candidate", screen_answer["produces"])

        ancestry = by_name["ancestry.estimate_population_context"]["annotations"]
        self.assertEqual(ancestry["operationScope"], "read")
        self.assertFalse(ancestry["mutating"])
        self.assertEqual(ancestry["externalIO"], [])
        self.assertEqual(ancestry["privacyScope"], "local_reference_panel_private_projection")
        self.assertEqual(ancestry["dependencyContract"]["installedLibraries"], list(ancestry_policy.PANEL_LIBRARIES))
        self.assertEqual(ancestry["dependencyContract"]["missingInstalledLibraryStatus"], "requires_library_install")
        self.assertIn("active_genome_index", ancestry["dataAccess"])
        self.assertIn("installed_public_reference_panel", ancestry["dataAccess"])
        self.assertIn("pca_projection", ancestry["produces"])
        ancestry_list = by_name["ancestry.list_reference_panels"]["annotations"]
        self.assertEqual(ancestry_list["privacyScope"], "public_metadata")
        self.assertNotIn("dependencyContract", ancestry_list)

        prs = by_name["prs.calculate_score"]["annotations"]
        self.assertEqual(prs["operationScope"], "read")
        self.assertFalse(prs["mutating"])
        self.assertEqual(prs["externalIO"], [])
        self.assertEqual(prs["privacyScope"], "local_private_prs_score")
        self.assertIn("active_genome_index", prs["dataAccess"])
        self.assertIn("local_public_score_cache", prs["dataAccess"])
        self.assertIn("raw_polygenic_score", prs["produces"])
        prs_search = by_name["prs.search_scores"]["annotations"]
        self.assertEqual(prs_search["privacyScope"], "public_metadata")
        self.assertEqual(prs_search["externalIO"], ["pgs_catalog_metadata"])

        self.assertEqual(prs_search["dependencyContract"]["externalNetwork"], ["pgs_catalog_metadata"])
        prs_import = by_name["prs.import_scoring_file"]["annotations"]
        self.assertTrue(prs_import["mutating"])
        self.assertIn("pgs_catalog_ftp", prs_import["dependencyContract"]["externalNetwork"])

        lookup = by_name["variant.resolve"]["annotations"]
        self.assertEqual(lookup["operationScope"], "read")
        self.assertFalse(lookup["mutating"])
        self.assertEqual(lookup["privacyScope"], "target_scoped")
        self.assertIn("explicit_known_active_genome_indexes_when_selected", lookup["dataAccess"])

        record = by_name["research.record"]["annotations"]
        self.assertEqual(record["operationScope"], "write")
        self.assertTrue(record["mutating"])

    def test_source_record_inputs_are_explicit_verified_import_contracts(self) -> None:
        tools = all_operations()
        source_record_input_tools = [
            tool
            for tool in tools
            if "source_records" in (tool["inputSchema"].get("properties") or {})
        ]
        self.assertGreaterEqual(len(source_record_input_tools), 1)
        for tool in source_record_input_tools:
            with self.subTest(operation=tool["name"]):
                self._assert_source_records_require_source_verification(tool["inputSchema"])
                self._assert_source_record_import_contract(tool["annotations"])

        by_name = {tool["name"]: tool for tool in tools}
        native_retrievers = (
            "phenotype.retrieve_trait_gene_records",
            "phenotype.retrieve_disease_drug_targets",
            "functional_genomics.retrieve_perturbation_records",
            "functional_genomics.query_geo",
            "gwas.compare_gene_associations",
        )
        for operation in native_retrievers:
            with self.subTest(operation=operation):
                schema = by_name[operation]["inputSchema"]
                annotations = by_name[operation]["annotations"]
                self.assertNotIn("source_records", schema.get("properties") or {})
                self.assertNotIn("sourceRecordInput", annotations)

    def _assert_source_records_require_source_verification(self, schema: dict) -> None:
        source_records = schema["properties"]["source_records"]
        verifier_keys = {
            tuple(option["required"])
            for option in source_records["items"]["anyOf"]
        }
        self.assertEqual(
            verifier_keys,
            {("verified_fields",), ("support_spans",), ("verification",)},
        )

    def _assert_source_record_import_contract(self, annotations: dict) -> None:
        self.assertEqual(
            annotations.get("sourceRecordInput"),
            {
                "role": "verified_source_record_import",
                "requiredRecordEvidence": ["support_spans", "verification", "verified_fields"],
            },
        )

    def test_agi_consuming_operation_schemas_use_agi_path(self) -> None:
        by_name = {tool["name"]: tool for tool in all_operations()}
        agi_operations = [
            "active_genome_index.summarize",
            "active_genome_index.classify_callset_qc",
            "active_genome_index.classify_genotype_support",
            "active_genome_index.classify_region_callability",
            "ancestry.check_sample_overlap",
            "ancestry.project_pca",
            "ancestry.estimate_population_context",
            "clinvar.match_variants",
            "clinvar.scan_candidates",
            "pharmacogenomics.preflight_pharmcat",
            "pharmacogenomics.run_pharmcat",
            "prs.check_score_overlap",
            "prs.calculate_score",
        ]

        for operation in agi_operations:
            properties = set(by_name[operation]["inputSchema"].get("properties") or {})
            self.assertEqual(properties & {"source", "vcf"}, set(), operation)
            self.assertTrue("agi_path" in properties, operation)

    def test_tool_definitions_expose_parameter_defaults(self) -> None:
        by_name = {tool["name"]: tool for tool in all_operations()}

        for tool in by_name.values():
            properties = tool["inputSchema"].get("properties") or {}
            defaulted_properties = {
                name
                for name, schema in properties.items()
                if isinstance(schema, dict) and ("default" in schema or "x_genomi_default" in schema)
            }
            annotation_defaults = {
                item["parameter"]
                for item in tool["annotations"].get("parameterDefaults") or []
            }
            self.assertEqual(annotation_defaults, defaulted_properties, tool["name"])

        parse_schema = by_name["genomi.parse_source"]["inputSchema"]
        self.assertEqual(parse_schema["required"], ["source"])
        for expected in ("source", "user_nickname", "set_default_user", "genome_build"):
            self.assertIn(expected, parse_schema["properties"])

        assign_schema = by_name["active_genome_index.assign_user_genome"]["inputSchema"]
        for expected in ("user_id", "nickname", "agi_id", "source", "set_active", "set_default_user"):
            self.assertIn(expected, assign_schema["properties"])

        parse_defaults = {
            item["parameter"]: item
            for item in by_name["genomi.parse_source"]["annotations"]["parameterDefaults"]
        }
        self.assertEqual(parse_defaults["genome_build"]["value"], "auto")
        self.assertTrue(parse_defaults["auto_reference_fasta"]["value"])

        variant_defaults = {
            item["parameter"]: item
            for item in by_name["variant.resolve"]["annotations"]["parameterDefaults"]
        }
        self.assertEqual(variant_defaults["genome_build"]["value"], "GRCh38")
        self.assertIn("Active Genome Index access", variant_defaults["include_active_genome_index"]["rule"])

        region_schema = by_name["region.retrieve_features"]["inputSchema"]["properties"]
        self.assertNotIn("default", region_schema["assembly"])
        self.assertNotIn("x_genomi_default", region_schema["assembly"])

        ancestry_defaults = {
            item["parameter"]: item
            for item in by_name["ancestry.estimate_population_context"]["annotations"]["parameterDefaults"]
        }
        self.assertEqual(ancestry_defaults["genome_build"]["value"], "GRCh38")
        self.assertIn("approved Active Genome Index", ancestry_defaults["genome_build"]["condition"])
        prs_defaults = {
            item["parameter"]: item
            for item in by_name["prs.calculate_score"]["annotations"]["parameterDefaults"]
        }
        self.assertEqual(prs_defaults["genome_build"]["value"], "GRCh38")
        self.assertIn("approved Active Genome Index", prs_defaults["genome_build"]["condition"])
        self.assertTrue(prs_defaults["skip_ambiguous_palindromic"]["value"])
        self.assertEqual(ancestry_defaults["nearest_reference_count"]["value"], 10)

    def test_operation_result_reports_defaults_applied(self) -> None:
        result = call_operation("sequence.analyze", {"sequence": "ATGGCC"})

        defaults = {item["parameter"]: item for item in result["defaults_applied"]}
        self.assertEqual(defaults["mode"]["value"], "summary")
        self.assertEqual(defaults["frame"]["value"], 1)
        self.assertEqual(defaults["min_aa"]["value"], 30)
        self.assertIn("summary mode", defaults["strand"]["rule"])
        self.assertNotIn("max_matches", defaults)

        explicit = call_operation("sequence.analyze", {"sequence": "ATGGCC", "mode": "translate"})
        explicit_defaults = {item["parameter"] for item in explicit["defaults_applied"]}
        self.assertNotIn("mode", explicit_defaults)
        self.assertNotIn("min_aa", explicit_defaults)


if __name__ == "__main__":
    import unittest

    unittest.main()
