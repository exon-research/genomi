from __future__ import annotations

import gzip
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.active_genome_index.active_genome_index import default_agi_path
from genomi.active_genome_index.normalize import default_normalized_path
from genomi.capabilities.clinvar.static_annotation import init_static_run
from genomi.evidence import (
    _ensure_schema,
    connect_evidence,
    default_evidence_path,
    import_clinvar_vcf,
    import_population_vcf,
    record_research_findings,
)
from genomi.runtime.paths import (
    default_export_variants_path,
    enclosing_work_dir,
    run_evidence_db_path,
    run_evidence_dir,
    run_output_path,
    run_project_dir,
    run_reference_dir,
    run_work_dir,
    sample_slug_from_vcf,
    shared_evidence_db_path,
    vcf_content_hash,
)
from genomi.runtime.sqlite_support import connect_sqlite

DATA_DIR = Path(__file__).parent / "data"
TINY_CLINVAR = DATA_DIR / "tiny.clinvar.vcf"
TINY_POPULATION = DATA_DIR / "tiny.population.vcf"


class GenomiDataPathTests(unittest.TestCase):
    def test_existing_raw_vcf_content_hash_derives_run_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "NG1LRQNESI.hard-filtered.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNG1LRQNESI\n",
                encoding="utf-8",
            )
            root = Path(".genomi-data")
            slug = f"vcf-sha256-{vcf_content_hash(vcf)}"

            self.assertEqual(sample_slug_from_vcf(vcf), slug)
            self.assertEqual(run_project_dir(vcf, root=root), Path(".genomi-data") / slug)
            self.assertEqual(run_work_dir(vcf, root=root), Path(".genomi-data") / slug / "work")
            self.assertEqual(run_evidence_dir(vcf, root=root), Path(".genomi-data") / slug / "evidence")
            self.assertEqual(run_reference_dir(vcf, root=root), Path(".genomi-data") / slug / "reference")
            self.assertEqual(default_evidence_path(vcf, root=root), Path(".genomi-data") / slug / "evidence/evidence.sqlite")
            self.assertEqual(shared_evidence_db_path(root=root), Path(".genomi-data/shared-evidence.sqlite"))
            self.assertEqual(default_agi_path(vcf, root=root), Path(".genomi-data") / slug / "work/active-genome-index.sqlite")

    def test_missing_raw_vcf_keeps_filename_fallback_for_planning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(sample_slug_from_vcf(Path(tmp) / "NG1LRQNESI.hard-filtered.vcf"), "ng1lrqnesi")

    def test_default_paths_use_genomi_home_across_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as cwd_one, tempfile.TemporaryDirectory() as cwd_two:
            home = Path(tmp) / "genomi-home"
            with mock.patch.dict(os.environ, {"GENOMI_HOME": str(home)}):
                previous = os.getcwd()
                try:
                    os.chdir(cwd_one)
                    vcf = Path(cwd_one) / "NG1LRQNESI.hard-filtered.vcf"
                    vcf.write_text("##fileformat=VCFv4.2\n", encoding="utf-8")
                    self.assertEqual(run_project_dir(vcf), home / f"vcf-sha256-{vcf_content_hash(vcf)}")
                    os.chdir(cwd_two)
                    self.assertEqual(shared_evidence_db_path(), home / "shared-evidence.sqlite")
                finally:
                    os.chdir(previous)

    def test_shared_evidence_db_env_overrides_default_shared_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "shared.sqlite"
            with mock.patch.dict(os.environ, {"GENOMI_SHARED_EVIDENCE_DB": str(shared)}):
                self.assertEqual(shared_evidence_db_path(), shared)
                self.assertEqual(shared_evidence_db_path(root=Path("/explicit")), Path("/explicit/shared-evidence.sqlite"))

    def test_existing_run_subdir_keeps_derived_vcfs_in_same_run(self) -> None:
        vcf = Path(".genomi-data/ng1lrqnesi/work/pass.primary.normalized.vcf.gz")

        self.assertEqual(sample_slug_from_vcf(vcf), "ng1lrqnesi")
        self.assertEqual(run_evidence_db_path(vcf), Path(".genomi-data/ng1lrqnesi/evidence/evidence.sqlite"))
        self.assertEqual(run_output_path(vcf, "clinvar.matches.jsonl"), Path(".genomi-data/ng1lrqnesi/work/clinvar.matches.jsonl"))
        self.assertEqual(enclosing_work_dir(vcf), Path(".genomi-data/ng1lrqnesi/work"))

    def test_default_outputs_are_under_vcf_run_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            try:
                os.chdir(tmp)
                vcf = Path("NG1LRQNESI.hard-filtered.vcf")
                root = Path(".genomi-data")

                self.assertEqual(
                    default_export_variants_path(vcf, pass_only=True, primary_contigs_only=True, chrom_style="no-chr", root=root),
                    Path(".genomi-data/ng1lrqnesi/work/pass.primary.nochr.variants.vcf"),
                )
                self.assertEqual(
                    default_normalized_path(vcf, root=root),
                    Path(".genomi-data/ng1lrqnesi/work/ng1lrqnesi.normalized.vcf.gz"),
                )
            finally:
                os.chdir(previous)

    def test_compressed_header_sample_is_fallback_for_generic_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf.gz"
            with gzip.open(vcf, "wt", encoding="utf-8") as handle:
                handle.write("##fileformat=VCFv4.2\n")
                handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tREAL_SAMPLE\n")

            self.assertEqual(sample_slug_from_vcf(vcf), f"vcf-sha256-{vcf_content_hash(vcf)}")

    def test_header_sample_takes_precedence_over_vendor_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "Sequencing.com_whole_genome_sequencing.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNG1LRQNESI\n",
                encoding="utf-8",
            )

            self.assertEqual(sample_slug_from_vcf(vcf), f"vcf-sha256-{vcf_content_hash(vcf)}")

    def test_static_clone_keeps_shared_static_and_purges_private_research(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_db = tmp_path / "source.sqlite"
            import_clinvar_vcf(TINY_CLINVAR, source_db, source_version="fixture", max_records=1)
            import_population_vcf(TINY_POPULATION, source_db, source="tiny_pop", source_version="pop_fixture")
            record_research_findings(
                source_db,
                {
                    "findings": [
                        {
                            "target": {"type": "gene", "gene": "GENE1"},
                            "source": {
                                "title": "Old Run Source",
                                "url": "https://example.test/old-run",
                                "accessed_at": "2026-05-05T00:00:00+00:00",
                            },
                            "finding": {"text": "Old run research text.", "summary": "Old run summary."},
                            "scope": "private",
                        },
                        {
                            "target": {"type": "gene", "gene": "GENE2"},
                            "source": {
                                "title": "Reusable Source",
                                "url": "https://example.test/shared",
                                "accessed_at": "2026-05-05T00:00:00+00:00",
                            },
                            "finding": {"text": "Shared research text.", "summary": "Shared summary."},
                            "scope": "shared",
                        }
                    ]
                },
            )
            vcf = tmp_path / "NG1LRQNESI.hard-filtered.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNG1LRQNESI\n",
                encoding="utf-8",
            )

            previous_cwd = Path.cwd()
            os.chdir(tmp_path)
            try:
                with mock.patch.dict(os.environ, {"GENOMI_HOME": str(tmp_path / ".genomi-data")}):
                    result = init_static_run(vcf.name, source_evidence_db=source_db, force=False)
            finally:
                os.chdir(previous_cwd)

            target_db = tmp_path / result["evidence_db"]
            self.assertEqual(result["agi_intake_source_path"], vcf.name)
            with mock.patch.dict(os.environ, {"GENOMI_HOME": str(tmp_path / ".genomi-data")}):
                init_static_run(vcf.name, source_evidence_db=None, force=False)
            with connect_sqlite(target_db) as connection:
                local_clinvar_rows = connection.execute("select count(*) from clinvar_variants").fetchone()[0]
                local_population_rows = connection.execute("select count(*) from population_frequencies").fetchone()[0]
                local_research_rows = connection.execute("select count(*) from research_findings").fetchone()[0]
                private_rows = connection.execute(
                    "select count(*) from research_findings where research_scope = 'private'"
                ).fetchone()[0]
                source_evidence_db = connection.execute(
                    "select value from metadata where key = 'source_evidence_db'"
                ).fetchone()[0]
                agi_intake_source_path = connection.execute(
                    "select value from metadata where key = 'agi_intake_source_path'"
                ).fetchone()[0]
                agi_sample_slug = connection.execute(
                    "select value from metadata where key = 'agi_sample_slug'"
                ).fetchone()[0]

            with connect_evidence(target_db) as connection:
                _ensure_schema(connection)
                clinvar_rows = connection.execute("select count(*) from clinvar_variants").fetchone()[0]
                population_rows = connection.execute("select count(*) from population_frequencies").fetchone()[0]
                research_rows = connection.execute("select count(*) from research_findings").fetchone()[0]

            self.assertEqual(local_clinvar_rows, 0)
            self.assertEqual(local_population_rows, 0)
            self.assertEqual(local_research_rows, 0)
            self.assertEqual(clinvar_rows, 1)
            self.assertEqual(population_rows, 3)
            self.assertEqual(research_rows, 1)
            self.assertEqual(private_rows, 0)
            self.assertEqual(source_evidence_db, f'"{source_db}"')
            self.assertEqual(agi_intake_source_path, f'"{vcf.name}"')
            self.assertEqual(agi_sample_slug, f'"{sample_slug_from_vcf(vcf)}"')


if __name__ == "__main__":
    unittest.main()
