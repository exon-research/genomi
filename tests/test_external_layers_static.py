from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from genomi.active_genome_index.active_genome_index import create_active_genome_index
from genomi.capabilities.clinvar.static_annotation import (
    build_static_annotation,
    match_static_clinvar,
)
from genomi.evidence import (
    build_clinvar_gene_index,
    import_clinvar_vcf,
    init_evidence_db,
    record_research_findings,
)
from genomi.evidence.investigation import prepare_investigation_packet
from genomi.runtime.static_dependencies import infer_genome_build_from_vcf, resolve_genome_build
from genomi.runtime.sqlite_support import connect_sqlite
from tests.support.capabilities.external_layers import (
    TINY_CLINVAR,
    TINY_POPULATION,
    TINY_VCF,
    EvidenceImportTestBase,
)


class StaticRunTests(EvidenceImportTestBase):
    def test_static_run_builds_static_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            vcf = tmp_path / "sample.vcf"
            vcf.write_text(TINY_VCF.read_text(encoding="utf-8"), encoding="utf-8")
            previous_cwd = Path.cwd()
            os.chdir(tmp_path)
            try:
                result = build_static_annotation(vcf.name, clinvar_vcf=TINY_CLINVAR, max_records=10)
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(result["workflow_area"], "static")
            self.assertEqual(result["status"], "completed_with_warnings")
            self.assertEqual(result["static_profile"], "bounded")
            self.assertEqual(result["agi_intake_source_path"], vcf.name)
            self.assertIn("export-variants", result["long_running_steps_deferred"])
            self.assertEqual(result["shared_sync"]["inserted"]["clinvar_variants"], 3)
            step_names = [step["name"] for step in result["steps"]]
            self.assertIn("parse-source", step_names)
            self.assertIn("match-clinvar", step_names)
            self.assertEqual(result["evidence_context"]["id"], "research")
            self.assertEqual(result["evidence_context"]["skill_contract"]["path"], "SKILL.md")
            for step in result["steps"]:
                self.assertIn("evidence_context", step)
                self.assertEqual(step["evidence_context"]["skill_contract"]["path"], "SKILL.md")
            self.assertTrue((tmp_path / result["outputs"]["clinvar_matches"]).exists())
            self.assertTrue((tmp_path / result["outputs"]["clinvar_annotations"]).exists())
            self.assertTrue((tmp_path / result["shared_evidence_db"]).exists())

    def test_static_run_uses_source_intake_for_archive_backed_vcf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_archive = tmp_path / "sample-source.zip"
            with zipfile.ZipFile(source_archive, "w") as archive:
                archive.writestr("README.txt", "ignored by source intake")
                archive.writestr("sample.vcf", TINY_VCF.read_text(encoding="utf-8"))
            previous_cwd = Path.cwd()
            os.chdir(tmp_path)
            try:
                result = build_static_annotation(
                    source_archive.name,
                    clinvar_vcf=TINY_CLINVAR,
                    genome_build="GRCh37",
                    max_records=10,
                    sync_shared=False,
                )
            finally:
                os.chdir(previous_cwd)

            step_by_name = {step["name"]: step for step in result["steps"]}
            self.assertEqual(step_by_name["parse-source"]["result"]["source_format"], "vcf")
            self.assertEqual(step_by_name["parse-source"]["result"]["source_kind"], "variant_callset")
            self.assertEqual(result["status"], "completed_with_warnings")
            self.assertTrue((tmp_path / result["outputs"]["clinvar_matches"]).exists())

    def test_static_run_links_shared_static_evidence_without_copying(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shared_db = tmp_path / "shared.sqlite"
            import_clinvar_vcf(TINY_CLINVAR, shared_db, source_version="fixture", genome_build="GRCh37")
            build_clinvar_gene_index(shared_db)
            vcf = tmp_path / "sample.vcf"
            vcf.write_text(TINY_VCF.read_text(encoding="utf-8"), encoding="utf-8")
            previous_cwd = Path.cwd()
            os.chdir(tmp_path)
            try:
                result = build_static_annotation(
                    vcf.name,
                    source_evidence_db=shared_db,
                    shared_evidence_db=shared_db,
                    population_vcf=TINY_POPULATION,
                    population_source="fixture_population",
                    sync_shared=False,
                    genome_build="GRCh37",
                    force=True,
                    max_records=10,
                )
            finally:
                os.chdir(previous_cwd)

            evidence_db = tmp_path / result["evidence_db"]
            with connect_sqlite(evidence_db) as connection:
                local_clinvar_rows = connection.execute("select count(*) from clinvar_variants").fetchone()[0]
                local_population_rows = connection.execute("select count(*) from population_frequencies").fetchone()[0]
            with connect_sqlite(shared_db) as connection:
                shared_population_rows = connection.execute("select count(*) from population_frequencies").fetchone()[0]
            self.assertEqual(local_clinvar_rows, 0)
            self.assertGreater(local_population_rows, 0)
            self.assertEqual(shared_population_rows, 0)
            self.assertLess(evidence_db.stat().st_size, 1_000_000)
            self.assertEqual(result["evidence_summary"]["tables"]["clinvar_variants"], 3)
            self.assertGreater(result["evidence_summary"]["tables"]["population_frequencies"], 0)
            self.assertIn("match-clinvar", [step["name"] for step in result["steps"]])

    def test_static_run_auto_uses_installed_clinvar_when_not_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            vcf = tmp_path / "sample.vcf"
            vcf.write_text(TINY_VCF.read_text(encoding="utf-8"), encoding="utf-8")
            previous_cwd = Path.cwd()
            os.chdir(tmp_path)
            try:
                with (
                    patch("genomi.runtime.libraries.manager.refresh") as refresh,
                    patch("genomi.runtime.libraries.manager.status") as status,
                ):
                    status.return_value = {
                        "library": "clinvar-grch38",
                        "installed": True,
                        "status": "installed",
                        "required_paths": [str(TINY_CLINVAR)],
                    }
                    result = build_static_annotation(
                        vcf.name,
                        genome_build="GRCh38",
                        max_records=10,
                        allow_long_running_static=True,
                    )
            finally:
                os.chdir(previous_cwd)

            refresh.assert_not_called()
            self.assertEqual(result["genome_build"], "GRCh38")
            step_names = [step["name"] for step in result["steps"]]
            self.assertIn("select-clinvar-library", step_names)
            self.assertIn("import-clinvar", step_names)
            self.assertIn("match-clinvar", step_names)
            self.assertTrue((tmp_path / result["outputs"]["clinvar_matches"]).exists())

    def test_static_run_auto_reference_fasta_uses_installed_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            vcf = tmp_path / "sample.vcf"
            reference = tmp_path / "reference.fa"
            normalized = tmp_path / "normalized.vcf.gz"
            reference.write_text(">1\nACGT\n", encoding="utf-8")
            vcf.write_text(TINY_VCF.read_text(encoding="utf-8"), encoding="utf-8")
            previous_cwd = Path.cwd()
            os.chdir(tmp_path)
            try:
                def status_side_effect(library):
                    if str(library).startswith("reference-"):
                        return {
                            "library": "reference-grch38",
                            "installed": True,
                            "status": "installed",
                            "required_paths": [str(reference), str(reference) + ".fai"],
                        }
                    return {
                        "library": "clinvar-grch38",
                        "installed": True,
                        "status": "installed",
                        "required_paths": [str(TINY_CLINVAR)],
                    }
                with (
                    patch("genomi.runtime.libraries.manager.refresh") as refresh,
                    patch("genomi.runtime.libraries.manager.status", side_effect=status_side_effect),
                    patch("genomi.capabilities.clinvar.static_annotation.build.normalize_vcf") as normalize,
                ):
                    normalize.return_value = {
                        "status": "completed",
                        "output": str(normalized),
                    }
                    result = build_static_annotation(
                        vcf.name,
                        genome_build="GRCh38",
                        auto_reference_fasta=True,
                        sync_shared=False,
                        max_records=10,
                        allow_long_running_static=True,
                    )
            finally:
                os.chdir(previous_cwd)

            refresh.assert_not_called()
            normalize.assert_called_once()
            self.assertEqual(normalize.call_args.args[1], reference)
            self.assertTrue(normalize.call_args.kwargs["allow_malformed_tags"])
            self.assertEqual(result["reference_fasta"], str(reference))
            self.assertEqual(result["genotype_reference_fasta"], str(reference))
            self.assertEqual(result["agi_comparable_variant_export"], str(normalized))
            step_names = [step["name"] for step in result["steps"]]
            self.assertIn("ensure-reference-fasta", step_names)
            self.assertIn("normalize", step_names)

    def test_static_run_bounded_profile_defers_timeout_prone_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            vcf = tmp_path / "sample.vcf"
            vcf.write_text(TINY_VCF.read_text(encoding="utf-8"), encoding="utf-8")
            previous_cwd = Path.cwd()
            os.chdir(tmp_path)
            try:
                with (
                    patch("genomi.runtime.libraries.manager.refresh") as refresh,
                    patch("genomi.capabilities.clinvar.static_annotation.build.export_variants") as export,
                    patch("genomi.capabilities.clinvar.static_annotation.build.normalize_vcf") as normalize,
                ):
                    result = build_static_annotation(
                        vcf.name,
                        genome_build="GRCh38",
                        auto_reference_fasta=True,
                        sync_shared=False,
                        max_records=10,
                    )
            finally:
                os.chdir(previous_cwd)

            refresh.assert_not_called()
            export.assert_not_called()
            normalize.assert_not_called()
            self.assertEqual(result["status"], "completed_with_warnings")
            self.assertEqual(result["static_profile"], "bounded")
            self.assertIn("ensure-reference-fasta", result["long_running_steps_deferred"])
            self.assertIn("export-variants", result["long_running_steps_deferred"])
            self.assertTrue(any(item["stage"] == "ensure-clinvar" for item in result["warnings"]))
            clinvar_warning = next(item for item in result["warnings"] if item["stage"] == "ensure-clinvar")
            self.assertEqual(clinvar_warning["status"], "requires_library_install")
            self.assertIn("install_command", clinvar_warning["library_install_request"]["missing_library"])

    def test_clinvar_match_reports_missing_library_install_request(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"GENOMI_HOME": str(Path(tmp) / "genomi-home")}),
        ):
            tmp_path = Path(tmp)
            vcf = tmp_path / "sample.vcf"
            db = tmp_path / "evidence.sqlite"
            vcf.write_text(TINY_VCF.read_text(encoding="utf-8"), encoding="utf-8")
            init_evidence_db(db)
            # ClinVar matching reads the Active Genome Index, so build it first;
            # with the ClinVar library absent, the match must surface the
            # library-install requirement.
            create_active_genome_index(vcf)

            result = match_static_clinvar(vcf, evidence_db=db, genome_build="GRCh38")

        self.assertEqual(result["status"], "requires_library_install")
        self.assertFalse(result["tool_will_work"])
        self.assertEqual(result["operation"], "clinvar.match_variants")
        self.assertEqual(result["missing_library"]["library"], "clinvar-grch38")
        self.assertIn("--libraries clinvar-grch38", result["ask_user"]["install_command"])

    def test_static_run_infers_g1k37_vcf_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            vcf.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "##reference=file:///references/G1K.37.fa",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                        "1\t100\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertEqual(infer_genome_build_from_vcf(vcf), "GRCh37")
            self.assertEqual(resolve_genome_build(vcf, "auto"), "GRCh37")

    def test_static_run_infers_g1k37_from_wrapped_vcf_reference(self) -> None:
        import bz2
        import lzma
        import zipfile

        body = (
            "##fileformat=VCFv4.2\n"
            "##reference=file:///references/G1K.37.fa\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
            "1\t100\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bz2_path = root / "sample.vcf.bz2"
            bz2_path.write_bytes(bz2.compress(body.encode()))
            xz_path = root / "sample.vcf.xz"
            xz_path.write_bytes(lzma.compress(body.encode()))
            zip_path = root / "sample.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("README.txt", "not genomic")
                archive.writestr("sample.vcf", body)

            for path in (bz2_path, xz_path, zip_path):
                with self.subTest(path=path.name):
                    self.assertEqual(infer_genome_build_from_vcf(path), "GRCh37")
                    self.assertEqual(resolve_genome_build(path, "auto"), "GRCh37")

    def test_investigation_packet_bundles_stored_research_sources_and_writeback_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            record_research_findings(
                db,
                {
                    "target": {"type": "drug", "drug": "Warfarin"},
                    "source": {
                        "title": "Example CPIC Warfarin",
                        "url": "https://example.test/cpic-warfarin",
                        "type": "pgx_guideline",
                        "accessed_at": "2026-05-07T00:00:00+00:00",
                    },
                    "finding": {
                        "text": "Short warfarin pharmacogenomic finding.",
                        "summary": "Warfarin source context.",
                        "type": "pharmacogenomic_guideline",
                    },
                },
            )

            packet = prepare_investigation_packet(db, "drug", drug="Warfarin")
            source_ids = {source["source_id"] for source in packet["source_catalog"]["sources"]}
            action_tools = {action["tool"] for action in packet["available_operations"]}

            self.assertEqual(packet["target"]["target_type"], "drug")
            self.assertEqual(packet["stored_research"]["count"], 1)
            self.assertIn("cpic", source_ids)
            self.assertIn("pharmgkb", source_ids)
            self.assertIn("research.query", action_tools)
            self.assertIn("research.search", action_tools)
            self.assertIn("research.record", action_tools)
            self.assertEqual(packet["record_research_template"]["target"]["type"], "drug")
            self.assertEqual(packet["record_research_template"]["target"]["drug"], "Warfarin")
            self.assertIn("source_catalog", packet)
