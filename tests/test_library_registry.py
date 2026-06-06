from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from genomi.operations.catalog import load_tool_catalog
from genomi.runtime.libraries import manager, registry
from genomi.runtime.libraries.spec import Freshness, Kind

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "genomi"
RUNTIME_LIBRARIES_ROOT = SRC_ROOT / "runtime" / "libraries"
ALLOWED_LIBRARY_MANAGER_INSTALL_CALLERS = {
    SRC_ROOT / "operations" / "registry" / "handlers_admin.py",
}
FORBIDDEN_LIBRARY_OWNERSHIP_PATTERNS = {
    "LibrarySpec(": "declare LibrarySpec entries only in genomi.runtime.libraries.registry",
    "source_fetch.": "route source freshness/download through genomi.runtime.libraries.manager",
    "library_manager.install(": "install libraries only through runtime library manager or genomi.install handler",
    "library_manager.refresh(": "refresh libraries only through runtime library manager or genomi.install handler",
    "manager.install(": "install libraries only through runtime library manager or genomi.install handler",
    "manager.refresh(": "refresh libraries only through runtime library manager or genomi.install handler",
}


class LibraryRegistryTests(unittest.TestCase):
    def test_all_ids_unique_and_resolvable(self) -> None:
        ids = registry.all_ids()
        self.assertEqual(len(ids), len(set(ids)), "library ids must be unique")
        for library_id in ids:
            self.assertTrue(registry.has(library_id))
            self.assertEqual(registry.get(library_id).id, library_id)

    def test_unknown_id_raises(self) -> None:
        self.assertFalse(registry.has("not-a-library"))
        with self.assertRaises(ValueError):
            registry.get("not-a-library")

    def test_every_purpose_member_is_a_real_id(self) -> None:
        known = set(registry.all_ids())
        for purpose, members in registry.purposes().items():
            for member in members:
                self.assertIn(member, known, f"purpose {purpose} references unknown id {member}")

    def test_everything_excludes_manual_and_online(self) -> None:
        everything = set(registry.purposes()["everything"])
        # 18 installable offline-family libraries, no manual or online-only sources.
        self.assertEqual(len(everything), 18)
        self.assertEqual({registry.get(item).kind for item in everything}, {Kind.OFFLINE, Kind.DERIVED})

    def test_paths_are_relative_and_resolve_under_a_temp_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for spec in registry.all_specs():
                for rel in (*spec.targets, *spec.required_paths):
                    self.assertFalse(rel.is_absolute(), f"{spec.id} path {rel} must be relative to GENOMI_HOME")
                    resolved = root / rel
                    self.assertTrue(str(resolved).startswith(str(root)))

    def test_online_specs_carry_api_base(self) -> None:
        online = [s for s in registry.all_specs() if s.kind is Kind.ONLINE]
        self.assertEqual(
            {s.id for s in online},
            {
                "biogrid-orcs",
                "chembl",
                "clinpgx",
                "depmap",
                "fda-pgx",
                "gnomad",
                "gwas-catalog",
                "hpa",
                "kegg",
                "ncbi-geo",
                "opentargets",
                "pgs-catalog",
                "pgxdb",
                "quickgo",
                "reactome",
            },
        )
        for spec in online:
            self.assertTrue(spec.is_online)
            self.assertEqual(spec.freshness, Freshness.LIVE)
            self.assertTrue(spec.source.api_base, f"{spec.id} must declare an api_base")
            self.assertEqual(spec.required_paths, ())

    def test_runtime_libraries_own_library_specs_and_install_paths(self) -> None:
        violations: list[str] = []
        for path in sorted(SRC_ROOT.rglob("*.py")):
            if path.is_relative_to(RUNTIME_LIBRARIES_ROOT):
                continue
            text = path.read_text(encoding="utf-8")
            for pattern, reason in FORBIDDEN_LIBRARY_OWNERSHIP_PATTERNS.items():
                if pattern not in text:
                    continue
                if path in ALLOWED_LIBRARY_MANAGER_INSTALL_CALLERS and pattern in {
                    "library_manager.install(",
                    "library_manager.refresh(",
                    "manager.install(",
                    "manager.refresh(",
                }:
                    continue
                violations.append(f"{path.relative_to(REPO_ROOT)}: {reason}")
        self.assertEqual(violations, [])

    def test_analytical_live_api_defaults_are_registry_owned(self) -> None:
        from genomi.capabilities.analytical_grounding import entity_relationships

        self.assertEqual(entity_relationships.QUICKGO_API_BASE, manager.api_base("quickgo"))
        self.assertEqual(entity_relationships.REACTOME_CONTENT_SERVICE_BASE, manager.api_base("reactome"))
        self.assertEqual(entity_relationships.KEGG_REST_API_BASE, manager.api_base("kegg"))
        self.assertEqual(entity_relationships.HPA_API_BASE, manager.api_base("hpa"))
        self.assertEqual(entity_relationships.HPA_TSV_DOWNLOAD_BASE, manager.source_url("hpa"))
        self.assertEqual(entity_relationships.CHEMBL_API_BASE, manager.api_base("chembl"))

    def test_functional_genomics_live_sources_are_registry_owned(self) -> None:
        from genomi.capabilities.functional_genomics import screen

        self.assertEqual(screen.BIOGRID_ORCS_API_BASE, manager.api_base("biogrid-orcs"))
        self.assertEqual(screen.BIOGRID_ORCS_HOME_URL, manager.source_url("biogrid-orcs"))
        self.assertEqual(
            screen.SUPPORTED_NATIVE_SCREEN_SOURCES["biogrid_orcs"],
            registry.get("biogrid-orcs").helps,
        )
        self.assertEqual(
            screen.SUPPORTED_NATIVE_SCREEN_SOURCES["depmap"],
            registry.get("depmap").helps,
        )

    def test_public_trait_live_sources_are_registry_owned(self) -> None:
        from genomi.capabilities.functional_genomics import geo
        from genomi.capabilities.gwas import gwas
        from genomi.capabilities.nutrigenomics import source_context as nutrigenomics_source_context
        from genomi.capabilities.phenotype import gene_identification, targets
        from genomi.evidence import sources as evidence_sources
        from genomi.evidence.store import constants as store_constants

        self.assertEqual(store_constants.GNOMAD_API_URL, manager.api_base("gnomad"))
        self.assertEqual(evidence_sources.SOURCE_HOME_URLS["gnomad"], manager.source_url("gnomad"))
        self.assertEqual(
            evidence_sources.SOURCE_HOME_URLS["opentargets"],
            manager.source_url("opentargets"),
        )
        self.assertEqual(
            evidence_sources.SOURCE_HOME_URLS["gwas_catalog"],
            manager.source_url("gwas-catalog"),
        )
        self.assertEqual(
            nutrigenomics_source_context.source_urls()["gwas_catalog"],
            manager.source_url("gwas-catalog"),
        )
        self.assertEqual(gwas.GWAS_CATALOG_SOURCE_URL, manager.source_url("gwas-catalog"))
        self.assertEqual(gwas.GWAS_CATALOG_API_URL, manager.source_url("gwas-catalog", 1))
        self.assertEqual(gwas.GWAS_CATALOG_V2_API_URL, manager.api_base("gwas-catalog"))
        self.assertEqual(
            gene_identification.OPENTARGETS_GRAPHQL_API_URL,
            manager.api_base("opentargets"),
        )
        self.assertEqual(targets.OPENTARGETS_GRAPHQL_API_URL, manager.api_base("opentargets"))
        self.assertEqual(geo.NCBI_EUTILS_BASE, manager.api_base("ncbi-geo"))
        self.assertEqual(geo.NCBI_GEO_FTP_BASE, manager.source_url("ncbi-geo"))

    def test_public_source_schema_defaults_match_registry(self) -> None:
        catalog = load_tool_catalog()

        gnomad_properties = catalog["operations"]["gnomad.fetch_population_frequency"]["input_schema"][
            "properties"
        ]
        gwas_variant_properties = catalog["operations"]["gwas.compare_variant_associations"]["input_schema"][
            "properties"
        ]
        gwas_gene_properties = catalog["operations"]["gwas.compare_gene_associations"]["input_schema"][
            "properties"
        ]
        trait_gene_properties = catalog["operations"]["phenotype.retrieve_trait_gene_records"]["input_schema"][
            "properties"
        ]
        disease_target_properties = catalog["operations"]["phenotype.retrieve_disease_drug_targets"][
            "input_schema"
        ]["properties"]

        self.assertEqual(gnomad_properties["api_url"]["default"], manager.api_base("gnomad"))
        self.assertEqual(gwas_variant_properties["api_url"]["default"], manager.source_url("gwas-catalog", 1))
        self.assertEqual(gwas_gene_properties["api_url"]["default"], manager.api_base("gwas-catalog"))
        self.assertEqual(
            trait_gene_properties["opentargets_api_url"]["default"],
            manager.api_base("opentargets"),
        )
        self.assertEqual(
            disease_target_properties["opentargets_api_url"]["default"],
            manager.api_base("opentargets"),
        )

    def test_pgx_online_source_urls_are_registry_owned(self) -> None:
        clinpgx = registry.get("clinpgx")
        self.assertEqual(clinpgx.source.urls[0], "https://api.pharmgkb.org/swagger/")
        self.assertEqual(clinpgx.source.urls[1], "https://www.clinpgx.org/page/policies")

        pgxdb = registry.get("pgxdb")
        self.assertEqual(pgxdb.source.urls, ("https://pgx-db.org/swagger/",))

    def test_pharmcat_documentation_urls_are_registry_owned(self) -> None:
        spec = registry.get("pharmcat")
        self.assertEqual(
            spec.source.urls,
            (
                "https://pharmcat.clinpgx.org/",
                "https://pharmcat.clinpgx.org/Genes-Drugs/",
                "https://pharmcat.clinpgx.org/using/Calling-CYP2D6/",
                "https://pharmcat.clinpgx.org/using/Outside-Call-Format/",
                "https://pharmcat.clinpgx.org/using/Calling-HLA/",
                "https://pharmcat.clinpgx.org/faqs/",
                "https://pharmcat.clinpgx.org/using/Running-PharmCAT-Pipeline/",
                "https://pharmcat.clinpgx.org/using/VCF-Requirements/",
            ),
        )

    def test_pharmcat_capability_urls_follow_registry(self) -> None:
        from genomi.capabilities.pharmacogenomics.pharmcat._common import (
            PHARMCAT_DOCS,
            PHARMCAT_GENES_DRUGS_URL,
            PHARMCAT_HOME_URL,
            PHARMCAT_VCF_REQUIREMENTS_URL,
        )

        spec = registry.get("pharmcat")
        self.assertEqual(PHARMCAT_HOME_URL, spec.source.urls[0])
        self.assertEqual(PHARMCAT_GENES_DRUGS_URL, spec.source.urls[1])
        self.assertEqual(PHARMCAT_VCF_REQUIREMENTS_URL, spec.source.urls[7])
        self.assertEqual({doc["url"] for doc in PHARMCAT_DOCS}, {spec.source.urls[0], spec.source.urls[6], spec.source.urls[7]})

    def test_pharmcat_gene_requirements_schema_uses_packaged_catalog(self) -> None:
        catalog = load_tool_catalog()
        properties = catalog["operations"]["pharmacogenomics.describe_gene_requirements"]["input_schema"]["properties"]
        self.assertEqual(set(properties), {"gene", "semantic_context"})

    def test_pgs_catalog_live_source_urls_are_registry_owned(self) -> None:
        spec = registry.get("pgs-catalog")
        self.assertEqual(
            spec.source.urls,
            (
                "https://www.pgscatalog.org/",
                "https://www.pgscatalog.org/downloads/",
                "https://www.pgscatalog.org/docs/ancestry/",
                "https://www.pgscatalog.org/docs/faq/",
            ),
        )

    def test_manual_and_platform_flags(self) -> None:
        msigdb = registry.get("msigdb-hallmark")
        self.assertIs(msigdb.kind, Kind.MANUAL)
        self.assertTrue(msigdb.manual_source_required)
        for aligner in ("minimap2-binary", "bwa-mem2-binary"):
            spec = registry.get(aligner)
            self.assertTrue(spec.platform_linux_x64_only)
            self.assertEqual(spec.freshness, Freshness.PINNED_SHA)
            self.assertIsNotNone(spec.source.sha256)

    def test_derived_panel_declares_its_inputs(self) -> None:
        spec = registry.get("ancestry-1000g-30x-grch37")
        self.assertIs(spec.kind, Kind.DERIVED)
        self.assertEqual(spec.source.derived_from, ("ancestry-1000g-30x-grch38", "liftover-chains"))

    def test_prs_scoring_file_is_parameterized(self) -> None:
        spec = registry.get("prs-scoring-file")
        self.assertIs(spec.kind, Kind.PARAMETERIZED)
        self.assertEqual(spec.source.derived_from, ("pgs-catalog",))

    def test_pgs_catalog_score_metadata_is_installable(self) -> None:
        spec = registry.get("pgs-catalog-score-metadata")
        self.assertIs(spec.kind, Kind.OFFLINE)
        self.assertEqual(
            spec.source.urls,
            ("https://ftp.ebi.ac.uk/pub/databases/spot/pgs/metadata/pgs_all_metadata_scores.csv",),
        )
        self.assertEqual(spec.required_paths, spec.targets)
        self.assertIn("pgs-catalog-score-metadata", registry.purposes()["common-questions"])

    def test_fda_pgx_declares_both_live_tables(self) -> None:
        spec = registry.get("fda-pgx")
        self.assertIs(spec.kind, Kind.ONLINE)
        self.assertEqual(
            spec.source.api_base,
            "https://www.fda.gov/drugs/science-and-research-drugs/table-pharmacogenomic-biomarkers-drug-labeling",
        )
        self.assertEqual(
            spec.source.urls,
            ("https://www.fda.gov/medical-devices/precision-medicine/table-pharmacogenetic-associations",),
        )

    def test_resolve_selection_purpose_ids_and_errors(self) -> None:
        self.assertEqual(
            registry.resolve_selection("common-questions"),
            ["clinvar-grch38", "hpo", "gencc", "pgs-catalog-score-metadata"],
        )
        self.assertEqual(registry.resolve_selection("clinvar-grch38,hpo"), ["clinvar-grch38", "hpo"])
        self.assertEqual(registry.resolve_selection(""), [])
        with self.assertRaises(ValueError):
            registry.resolve_selection("totally-unknown")


if __name__ == "__main__":
    unittest.main()
