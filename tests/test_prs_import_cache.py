from __future__ import annotations

import gzip
import json
from pathlib import Path
from unittest import mock

from genomi.active_genome_index.active_genome_index import default_agi_path
from genomi.capabilities.prs import pgs_catalog as prs_pgs_catalog
from genomi.capabilities.prs import scorer as prs_scorer
from genomi.capabilities.prs import scoring_files as prs_scoring_files
from genomi.operations import call_operation
from genomi.runtime import context as runtime_context
from genomi.runtime.libraries import manager as library_manager
from genomi.runtime.sqlite_support import connect_sqlite

from tests.support.capabilities.prs_contract import PolygenicScoreTestBase


class PolygenicScoreImportCacheTests(PolygenicScoreTestBase):
    def test_local_scoring_file_import_overlap_and_score(self) -> None:
        scoring_file = self._write_scoring_file()
        imported = call_operation(
            "prs.import_scoring_file",
            {"pgs_id": "PGS900001", "scoring_file": str(scoring_file), "genome_build": "GRCh38"},
        )
        vcf = self._write_indexed_vcf("sample.vcf")
        self._select_approved_agi(vcf)

        self.assertEqual(imported["status"], "completed")
        self.assertEqual(imported["score_cache"]["variant_count"], 4)
        with self._tiny_thresholds():
            overlap = call_operation("prs.check_score_overlap", {"pgs_id": "PGS900001"})
            score = call_operation("prs.calculate_score", {"pgs_id": "PGS900001"})

        self.assertEqual(overlap["status"], "score_ready")
        self.assertEqual(overlap["sample_qc"]["matched_variant_count"], 4)
        self.assertEqual(overlap["sample_qc"]["missing_variant_count"], 0)
        self.assertEqual(score["status"], "completed")
        self.assertAlmostEqual(score["score_result"]["raw_weighted_score"], 2.0)
        self.assertEqual(score["score_result"]["calibration"]["status"], "not_provided")
        self.assertIn("not an absolute risk", " ".join(score["limitations"]).lower())
        self.assertTrue(score["personal_context"]["uses_personal_dna"])

    def test_import_default_build_reporting_does_not_follow_active_agi(self) -> None:
        vcf = self._write_indexed_vcf("sample_grch37_context.vcf")
        self._select_approved_agi(vcf, genome_build="GRCh37")

        result = call_operation(
            "prs.import_scoring_file",
            {"pgs_id": "PGS900001", "scoring_file": str(self._write_scoring_file())},
        )

        defaults = {item["parameter"]: item["value"] for item in result["defaults_applied"]}
        self.assertEqual(result["genome_build"], "GRCh38")
        self.assertEqual(defaults["genome_build"], "GRCh38")

    def test_catalog_source_choice_prefers_requested_harmonized_build(self) -> None:
        choice = prs_pgs_catalog.scoring_file_source_from_metadata(
            {
                "id": "PGS900001",
                "genome_build": "GRCh37",
                "ftp_scoring_file": "https://example.test/PGS900001.txt.gz",
                "ftp_harmonized_scoring_files": {
                    "GRCh38": {"positions": "https://example.test/PGS900001_hmPOS_GRCh38.txt.gz"}
                },
            },
            "GRCh38",
        )

        self.assertEqual(choice["status"], "available")
        self.assertEqual(choice["url"], "https://example.test/PGS900001_hmPOS_GRCh38.txt.gz")
        self.assertEqual(choice["genome_build"], "GRCh38")
        self.assertTrue(choice["harmonized"])
        self.assertFalse(choice["fallback_used"])

    def test_catalog_direct_fallback_uses_authoritative_original_build(self) -> None:
        scoring_file = self._write_scoring_file(
            filename="catalog-original.txt",
            pgs_id="PGS900001",
            harmonized=False,
        )
        metadata = {
            "id": "PGS900001",
            "genome_build": "GRCh37",
            "ftp_scoring_file": "https://example.test/PGS900001.txt.gz",
            "ftp_harmonized_scoring_files": {},
        }
        self.assertIsNone(prs_pgs_catalog.scoring_file_url_from_metadata(metadata, "GRCh38"))
        self.assertEqual(
            prs_pgs_catalog.scoring_file_url_from_metadata(metadata, "GRCh37"),
            "https://example.test/PGS900001.txt.gz",
        )

        def fake_download(_: str, target: Path) -> None:
            with gzip.open(target, "wt", encoding="utf-8") as handle:
                handle.write(scoring_file.read_text(encoding="utf-8"))

        with (
            mock.patch.object(prs_pgs_catalog, "fetch_rest_metadata", return_value=metadata),
            mock.patch.object(prs_scoring_files, "_download_source", side_effect=fake_download),
        ):
            imported = call_operation(
                "prs.import_scoring_file",
                {"pgs_id": "PGS900001", "genome_build": "GRCh38"},
            )

        self.assertEqual(imported["status"], "completed")
        self.assertEqual(imported["requested_genome_build"], "GRCh38")
        self.assertEqual(imported["genome_build"], "GRCh37")
        self.assertTrue(imported["source_choice"]["fallback_used"])
        self.assertFalse(imported["source_choice"]["harmonized"])
        self.assertIn("PGS900001/GRCH37", imported["score_cache"]["score_dir"])
        self.assertEqual(
            imported["next_actions"],
            [
                {
                    "action": "check_score_overlap",
                    "operation": "prs.check_score_overlap",
                    "score_dir": imported["score_cache"]["score_dir"],
                },
                {
                    "action": "calculate_score",
                    "operation": "prs.calculate_score",
                    "score_dir": imported["score_cache"]["score_dir"],
                },
            ],
        )
        self.assertFalse((self.genomi_home / "reference" / "prs" / "PGS900001" / "GRCH38").exists())

    def test_catalog_direct_fallback_pgs_id_lookup_uses_score_manifest_build(self) -> None:
        scoring_file = self._write_scoring_file(
            filename="PGS900001_original_GRCh37.txt",
            pgs_id="PGS900001",
        )
        metadata = {
            "id": "PGS900001",
            "genome_build": "GRCh37",
            "ftp_scoring_file": "https://example.test/PGS900001.txt.gz",
            "ftp_harmonized_scoring_files": {},
        }

        def fake_download(_: str, target: Path) -> None:
            with gzip.open(target, "wt", encoding="utf-8") as handle:
                handle.write(scoring_file.read_text(encoding="utf-8"))

        with (
            mock.patch.object(prs_pgs_catalog, "fetch_rest_metadata", return_value=metadata),
            mock.patch.object(prs_scoring_files, "_download_source", side_effect=fake_download),
        ):
            call_operation("prs.import_scoring_file", {"pgs_id": "PGS900001", "genome_build": "GRCh38"})

        vcf = self._write_indexed_vcf("sample_grch38_for_fallback_score.vcf")
        runtime_context.set_active_agi_from_source(
            vcf,
            status="parsed",
            agi_path=default_agi_path(vcf),
            genome_build="GRCh38",
        )
        runtime_context.approve_agi_access(reason="test approved Active Genome Index access")

        with mock.patch.object(
            prs_scorer,
            "liftover_preflight",
            return_value={"status": "requires_library_install", "missing_library": {"library": "liftover"}},
        ):
            result = call_operation("prs.calculate_score", {"pgs_id": "PGS900001"})

        self.assertEqual(result["score_genome_build"], "GRCh37")
        self.assertEqual(result["sample_genome_build"], "GRCh38")

    def test_catalog_direct_fallback_requires_proven_original_build(self) -> None:
        metadata = {
            "id": "PGS900001",
            "genome_build": "",
            "ftp_scoring_file": "https://example.test/PGS900001.txt.gz",
            "ftp_harmonized_scoring_files": {},
        }

        with (
            mock.patch.object(prs_pgs_catalog, "fetch_rest_metadata", return_value=metadata),
            mock.patch.object(prs_scoring_files, "_download_source") as download,
        ):
            result = call_operation(
                "prs.import_scoring_file",
                {"pgs_id": "PGS900001", "genome_build": "GRCh38"},
            )

        self.assertEqual(result["status"], "source_unavailable")
        self.assertEqual(result["source_choice"]["reason"], "fallback_build_unproven")
        self.assertTrue(result["source_choice"]["fallback_used"])
        download.assert_not_called()

    def test_import_reuses_final_cache_after_parsed_identity_is_known(self) -> None:
        scoring_file = self._write_scoring_file(
            filename="score-with-metadata.txt",
            pgs_id="PGS900777",
        )

        first = call_operation("prs.import_scoring_file", {"scoring_file": str(scoring_file)})
        second = call_operation("prs.import_scoring_file", {"scoring_file": str(scoring_file)})

        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["pgs_id"], "PGS900777")
        self.assertEqual(second["status"], "already_installed")
        prs_root = self.genomi_home / "reference" / "prs"
        score_dirs = sorted(path.name for path in prs_root.iterdir() if path.is_dir() and not path.name.startswith("."))
        self.assertEqual(score_dirs, ["PGS900777"])

    def test_import_replaces_incomplete_score_cache_directory(self) -> None:
        scoring_file = self._write_scoring_file(
            filename="PGS900888_hmPOS_GRCh38.txt",
            pgs_id="PGS900888",
        )
        target_dir = library_manager.prs_scoring_file_dir("PGS900888", "GRCh38")
        target_dir.mkdir(parents=True)
        (target_dir / "manifest.json").write_text('{"status":"incomplete"}\n', encoding="utf-8")

        result = call_operation(
            "prs.import_scoring_file",
            {"pgs_id": "PGS900888", "scoring_file": str(scoring_file), "genome_build": "GRCh38"},
        )

        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["pgs_id"], "PGS900888")
        self.assertTrue((target_dir / "manifest.json").exists())
        self.assertTrue((target_dir / "variants.sqlite").exists())

    def test_import_replaces_invalid_existing_score_cache(self) -> None:
        scoring_file = self._write_scoring_file(
            filename="PGS900889_hmPOS_GRCh38.txt",
            pgs_id="PGS900889",
        )
        target_dir = library_manager.prs_scoring_file_dir("PGS900889", "GRCh38")
        target_dir.mkdir(parents=True)
        stale_variant = {
            "variant_id": "rsStale",
            "rsid": "rsStale",
            "chrom": "1",
            "pos": 100,
            "effect_allele": "C",
            "other_allele": "A",
            "effect_weight": 0.5,
            "harmonized": False,
            "palindromic": False,
            "source_row_number": 2,
        }
        prs_scoring_files.write_variants_db(target_dir / "variants.sqlite", [stale_variant])
        (target_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "pgs_id": "PGS900889",
                    "genome_build": "GRCh38",
                    "variant_count": 99,
                }
            )
            + "\n",
            encoding="utf-8",
        )

        result = call_operation(
            "prs.import_scoring_file",
            {"pgs_id": "PGS900889", "scoring_file": str(scoring_file), "genome_build": "GRCh38"},
        )

        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["pgs_id"], "PGS900889")
        validation = prs_scoring_files.validate_score_cache(
            target_dir,
            expected_pgs_id="PGS900889",
            expected_genome_build="GRCh38",
        )
        self.assertTrue(validation["valid"], validation)
        self.assertEqual(validation["variant_count"], 4)

    def test_resolve_score_cache_rejects_wrong_manifest_identity(self) -> None:
        target_dir = library_manager.prs_scoring_file_dir("PGS900890", "GRCh38")
        target_dir.mkdir(parents=True)
        variant = {
            "variant_id": "rs1",
            "rsid": "rs1",
            "chrom": "1",
            "pos": 100,
            "effect_allele": "C",
            "other_allele": "A",
            "effect_weight": 0.5,
            "harmonized": False,
            "palindromic": False,
            "source_row_number": 2,
        }
        prs_scoring_files.write_variants_db(target_dir / "variants.sqlite", [variant])
        (target_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "pgs_id": "PGS000000",
                    "genome_build": "GRCh38",
                    "variant_count": 1,
                }
            )
            + "\n",
            encoding="utf-8",
        )

        result = prs_scoring_files.resolve_score_cache(pgs_id="PGS900890", genome_build="GRCh38")

        self.assertEqual(result["status"], "requires_score_import")
        self.assertFalse(result["score_cache_status"]["installed"])
        self.assertEqual(result["score_cache_status"]["validation"]["reason"], "pgs_id_mismatch")

    def test_variant_db_write_failure_preserves_existing_database(self) -> None:
        db_path = Path(self._home_tmp.name) / "variants.sqlite"
        variant = {
            "variant_id": "rs1",
            "rsid": "rs1",
            "chrom": "1",
            "pos": 100,
            "effect_allele": "C",
            "other_allele": "A",
            "effect_weight": 0.5,
            "harmonized": False,
            "palindromic": False,
            "source_row_number": 2,
        }
        prs_scoring_files.write_variants_db(db_path, [variant])

        with self.assertRaises(KeyError):
            prs_scoring_files.write_variants_db(db_path, [{"chrom": "1"}])

        with connect_sqlite(db_path, row_factory=False) as connection:
            rows = connection.execute("select rsid, effect_weight from score_variants").fetchall()
        self.assertEqual(rows, [("rs1", 0.5)])

    def test_existing_score_cache_publish_rolls_back_directory_on_replace_failure(self) -> None:
        target_dir = Path(self._home_tmp.name) / "PGS900777" / "GRCh38"
        staging_dir = Path(self._home_tmp.name) / "staging"
        target_dir.mkdir(parents=True)
        staging_dir.mkdir()
        (target_dir / "manifest.json").write_text('{"pgs_id":"PGS900777","genome_build":"GRCh38"}\n', encoding="utf-8")
        (target_dir / "variants.sqlite").write_text("old-db", encoding="utf-8")
        (staging_dir / "manifest.json").write_text('{"pgs_id":"PGS900777","genome_build":"GRCh38"}\n', encoding="utf-8")
        (staging_dir / "variants.sqlite").write_text("new-db", encoding="utf-8")
        original_replace = Path.replace

        def fail_staging_publish(self: Path, target: Path) -> Path:
            if self == staging_dir:
                raise RuntimeError("simulated publish failure")
            return original_replace(self, target)

        with mock.patch.object(Path, "replace", fail_staging_publish):
            with self.assertRaises(RuntimeError):
                library_manager.publish_prs_scoring_file_cache(staging_dir, target_dir, force=True)

        self.assertEqual((target_dir / "manifest.json").read_text(encoding="utf-8"), '{"pgs_id":"PGS900777","genome_build":"GRCh38"}\n')
        self.assertEqual((target_dir / "variants.sqlite").read_text(encoding="utf-8"), "old-db")
        self.assertTrue(staging_dir.exists())
