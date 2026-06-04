from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from genomi.runtime.libraries import registry
from genomi.runtime.libraries.spec import Freshness, Kind


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
        self.assertEqual({s.id for s in online}, {"gnomad", "pgs-catalog", "clinpgx", "pgxdb", "fda-pgx"})
        for spec in online:
            self.assertTrue(spec.is_online)
            self.assertEqual(spec.freshness, Freshness.LIVE)
            self.assertTrue(spec.source.api_base, f"{spec.id} must declare an api_base")
            self.assertEqual(spec.required_paths, ())

    def test_pgx_online_source_urls_are_registry_owned(self) -> None:
        clinpgx = registry.get("clinpgx")
        self.assertEqual(clinpgx.source.urls[0], "https://api.pharmgkb.org/swagger/")
        self.assertEqual(clinpgx.source.urls[1], "https://www.clinpgx.org/page/policies")

        pgxdb = registry.get("pgxdb")
        self.assertEqual(pgxdb.source.urls, ("https://pgx-db.org/swagger/",))

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
