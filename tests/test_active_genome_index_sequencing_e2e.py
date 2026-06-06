from __future__ import annotations

import gzip
import json
import random
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pysam

from genomi.capabilities.ancestry import reference_panels
from genomi.capabilities.ancestry import source_context as ancestry_source_context
from genomi.capabilities.prs import scorer as prs_scorer
from genomi.evidence import build_clinvar_rsid_index, import_clinvar_vcf
from genomi.operations import call_operation
from genomi.operations.registry import handlers_screen_journal

from _capability_matrix_contract import SOURCE_FORMAT_MATRIX_OPERATIONS
from _genomi_runtime_helpers import GenomiRuntimeTestCase

SYNTHETIC_ALT_READ_COUNT = 12
NATIVE_VARIANT_RSID = "rs910000001"
NATIVE_PGS_ID = "PGSNATIVE001"


def _has_tools(*names: str) -> bool:
    return all(shutil.which(name) for name in names)


@unittest.skipUnless(
    _has_tools("samtools", "bcftools", "minimap2"),
    "native sequencing e2e tests require samtools, bcftools, and minimap2",
)
class ActiveGenomeIndexSequencingE2ETests(GenomiRuntimeTestCase):
    def _reference_and_variant(self, root: Path) -> tuple[Path, int, str, str, str]:
        rng = random.Random(17)
        bases = [rng.choice("ACGT") for _ in range(1000)]
        pos = 251
        ref = bases[pos - 1]
        alt = {"A": "G", "C": "T", "G": "A", "T": "C"}[ref]
        reference = root / "reference.fa"
        sequence = "".join(bases)
        reference.write_text(f">1\n{sequence}\n", encoding="utf-8")
        (root / "reference.fa.fai").write_text(
            f"1\t{len(sequence)}\t3\t{len(sequence)}\t{len(sequence) + 1}\n",
            encoding="utf-8",
        )
        return reference, pos, ref, alt, sequence

    def _alt_read(self, sequence: str, *, pos: int, alt: str) -> tuple[int, str]:
        start = 80
        length = 420
        read = list(sequence[start : start + length])
        read[pos - 1 - start] = alt
        return start, "".join(read)

    def _write_bam(self, path: Path, *, start: int, read: str) -> None:
        header = {"HD": {"VN": "1.6"}, "SQ": [{"SN": "1", "LN": 1000}]}
        with pysam.AlignmentFile(str(path), "wb", header=header) as handle:
            for index in range(SYNTHETIC_ALT_READ_COUNT):
                segment = pysam.AlignedSegment()
                segment.query_name = f"alt{index}"
                segment.query_sequence = read
                segment.flag = 0
                segment.reference_id = 0
                segment.reference_start = start
                segment.mapping_quality = 60
                segment.cigartuples = [(0, len(read))]
                segment.query_qualities = pysam.qualitystring_to_array("I" * len(read))
                handle.write(segment)

    def _write_fastq_pair(self, root: Path, read: str) -> Path:
        r1 = root / "PGP_PUBLIC_SA_L001_R1_001.fastq.gz"
        r2 = root / "PGP_PUBLIC_SA_L001_R2_001.fastq.gz"
        records = "".join(
            f"@alt{index}\n{read}\n+\n{'I' * len(read)}\n"
            for index in range(SYNTHETIC_ALT_READ_COUNT)
        ).encode("utf-8")
        with gzip.open(r1, "wb") as handle:
            handle.write(records)
        with gzip.open(r2, "wb") as handle:
            handle.write(records)
        return r1

    def _write_native_prs_score(self, path: Path, *, pos: int, ref: str, alt: str) -> Path:
        path.write_text(
            "\n".join(
                [
                    f"#pgs_id={NATIVE_PGS_ID}",
                    "#pgs_name=Native sequencing downstream fixture",
                    "#reported_trait=Native sequencing downstream contract",
                    "hm_chr\thm_pos\trsID\teffect_allele\tother_allele\teffect_weight",
                    f"1\t{pos}\t{NATIVE_VARIANT_RSID}\t{alt}\t{ref}\t1.0",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def _write_native_clinvar_fixture(self, path: Path, *, pos: int, ref: str, alt: str) -> Path:
        path.write_text(
            "\n".join(
                [
                    "##fileformat=VCFv4.2",
                    "##source=GenomiNativeSequencingDownstreamContract",
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                    (
                        f"1\t{pos}\tCNVNATIVE\t{ref}\t{alt}\t.\t.\t"
                        "ALLELEID=910001;RS=910000001;CLNSIG=Pathogenic;"
                        "CLNREVSTAT=criteria_provided,_single_submitter;"
                        "CLNDN=Native_sequencing_contract_condition;GENEINFO=NATIVE1:910001"
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def _write_tsv(self, path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
        lines = ["\t".join(fieldnames)]
        for row in rows:
            lines.append("\t".join(str(row.get(field, "")) for field in fieldnames))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _install_native_ancestry_panel(self, *, pos: int, ref: str, alt: str) -> None:
        panel_dir = reference_panels.panel_dir(genome_build="GRCh37")
        panel_dir.mkdir(parents=True, exist_ok=True)
        self._write_tsv(
            panel_dir / reference_panels.MARKERS_NAME,
            ["marker_id", "chrom", "pos", "ref", "alt", "mean", "scale"],
            [
                {
                    "marker_id": NATIVE_VARIANT_RSID,
                    "chrom": "1",
                    "pos": pos,
                    "ref": ref,
                    "alt": alt,
                    "mean": "1.0",
                    "scale": "1.0",
                }
            ],
        )
        self._write_tsv(
            panel_dir / reference_panels.SAMPLES_NAME,
            ["sample_id", "population", "superpopulation", "sex"],
            [{"sample_id": "REF_NATIVE", "population": "CEU", "superpopulation": "EUR", "sex": ""}],
        )
        self._write_tsv(
            panel_dir / reference_panels.LOADINGS_NAME,
            ["marker_id", "PC1"],
            [{"marker_id": NATIVE_VARIANT_RSID, "PC1": "0.1"}],
        )
        self._write_tsv(
            panel_dir / reference_panels.REFERENCE_SCORES_NAME,
            ["sample_id", "population", "superpopulation", "PC1"],
            [{"sample_id": "REF_NATIVE", "population": "CEU", "superpopulation": "EUR", "PC1": "0.2"}],
        )
        now = "2026-01-01T00:00:00Z"
        (panel_dir / reference_panels.PANEL_STATS_NAME).write_text(
            json.dumps(
                {
                    "sample_count": 1,
                    "marker_count": 1,
                    "component_count": 1,
                    "target_marker_count": 1,
                    "built_at": now,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (panel_dir / reference_panels.MANIFEST_NAME).write_text(
            json.dumps(
                {
                    "panel_id": ancestry_source_context.panel_id_for_build("GRCh37"),
                    "title": ancestry_source_context.PANEL_TITLE_GRCH37,
                    "library": ancestry_source_context.panel_library_for_build("GRCh37"),
                    "genome_build": "GRCh37",
                    "sample_count": 1,
                    "marker_count": 1,
                    "component_count": 1,
                    "built_at": now,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    @contextmanager
    def _tiny_prs_thresholds(self):
        with mock.patch.multiple(
            prs_scorer,
            MIN_SCORE_VARIANTS=1,
            MIN_OVERLAP_FRACTION=0.10,
            MODERATE_OVERLAP_FRACTION=0.50,
            HIGH_OVERLAP_FRACTION=0.90,
        ):
            yield

    @contextmanager
    def _mock_native_pgx_sources(self):
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "status": "completed",
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [NATIVE_VARIANT_RSID], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "guideline_annotations": [],
            "clinical_annotations": [],
            "label_annotations": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "status": "completed",
            "summary": {"pgx_record_count": 1, "medication_scoped_gene_drug_record_count": 0},
            "pgx_records": [
                {
                    "rsid": NATIVE_VARIANT_RSID,
                    "variant_or_haplotype": NATIVE_VARIANT_RSID,
                    "drug": "nativedrug",
                    "alleles": "variant observed",
                    "sentence": "Native sequencing fixture evidence for nativedrug response context.",
                }
            ],
            "raw_calls": [],
            "record_research_payloads": [],
        }
        fda_result = {
            "source": {"source_id": "fda_pgx"},
            "status": "no_matching_fda_pgx_records",
            "summary": {"biomarker_labeling_count": 0, "association_count": 0},
            "biomarker_labeling": [],
            "associations": [],
            "raw_calls": [],
        }
        with (
            mock.patch("genomi.capabilities.pharmacogenomics.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            mock.patch("genomi.capabilities.pharmacogenomics.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            mock.patch("genomi.capabilities.pharmacogenomics.fda_pgx.lookup_fda_pgx", return_value=fda_result),
        ):
            yield

    def _import_native_support_libraries(self, root: Path, *, pos: int, ref: str, alt: str) -> dict[str, object]:
        scoring_file = self._write_native_prs_score(root / "PGSNATIVE001_hmPOS_GRCh37.txt", pos=pos, ref=ref, alt=alt)
        imported_score = call_operation(
            "prs.import_scoring_file",
            {
                "pgs_id": NATIVE_PGS_ID,
                "scoring_file": str(scoring_file),
                "genome_build": "GRCh37",
                "force": True,
            },
        )
        self.assertEqual(imported_score["status"], "completed", imported_score)
        self._install_native_ancestry_panel(pos=pos, ref=ref, alt=alt)
        clinvar_db = root / "native-clinvar.sqlite"
        clinvar_vcf = self._write_native_clinvar_fixture(root / "native.clinvar.vcf", pos=pos, ref=ref, alt=alt)
        import_clinvar_vcf(clinvar_vcf, clinvar_db, source_version="native-fixture", genome_build="GRCh37")
        build_clinvar_rsid_index(clinvar_db, force=True)
        return {"imported_score": imported_score, "clinvar_db": clinvar_db}

    def _assert_native_downstream_contract(
        self,
        *,
        root: Path,
        pos: int,
        ref: str,
        alt: str,
        source_format: str,
    ) -> None:
        support_libraries = self._import_native_support_libraries(root, pos=pos, ref=ref, alt=alt)
        imported_score = support_libraries["imported_score"]
        clinvar_db = support_libraries["clinvar_db"]
        seen_operations: set[str] = set()

        def run(operation: str, params: dict[str, object] | None = None) -> dict[str, object]:
            seen_operations.add(operation)
            return call_operation(operation, params or {})

        summary = run("active_genome_index.summarize")
        stats = summary["active_genome_index"]["stats"]
        self.assertGreaterEqual(stats["variant_records"], 1, summary)

        callset_qc = run("active_genome_index.classify_callset_qc", {"genome_build": "GRCh37", "scan_records": 100})
        self.assertEqual(callset_qc["status"], "completed", callset_qc)
        self.assertGreaterEqual(callset_qc["summary"]["variant_records"], 1, callset_qc)

        variant = run("variant.resolve", {"query": f"chr1:{pos}:{ref}:{alt}", "genome_build": "GRCh37"})
        self.assertEqual(variant["sample_context"]["count"], 1, variant)
        self.assertEqual(variant["sample_context"]["matches"][0]["agi_source_format"], source_format)

        callability = run(
            "active_genome_index.classify_region_callability",
            {"region": f"1:{pos}-{pos}", "genome_build": "GRCh37", "min_covered_fraction": 0.1},
        )
        self.assertEqual(callability["status"], "completed", callability)
        self.assertTrue(callability["matched_records"], callability)

        support = run(
            "active_genome_index.classify_genotype_support",
            {"chrom": "1", "pos": pos, "ref": ref, "alt": alt, "genome_build": "GRCh37"},
        )
        self.assertEqual(support["support_status"], "supported", support)
        self.assertEqual(support["sample_observation"]["agi_source_format"], source_format)

        with self._tiny_prs_thresholds():
            overlap = run(
                "prs.check_score_overlap",
                {"score_dir": imported_score["score_cache"]["score_dir"], "genome_build": "GRCh37"},
            )
            score = run(
                "prs.calculate_score",
                {"score_dir": imported_score["score_cache"]["score_dir"], "genome_build": "GRCh37"},
            )
        self.assertEqual(overlap["status"], "score_ready", overlap)
        self.assertEqual(overlap["sample_qc"]["matched_variant_count"], 1, overlap)
        self.assertEqual(score["status"], "completed", score)
        self.assertEqual(score["sample_qc"]["matched_variant_count"], 1, score)

        ancestry_overlap = run("ancestry.check_sample_overlap", {"genome_build": "GRCh37"})
        self.assertEqual(ancestry_overlap["status"], "completed", ancestry_overlap)
        self.assertEqual(ancestry_overlap["sample_qc"]["usable_marker_count"], 1, ancestry_overlap)
        ancestry_context = run(
            "ancestry.estimate_population_context",
            {"genome_build": "GRCh37", "nearest_reference_count": 1},
        )
        self.assertEqual(ancestry_context["status"], "completed", ancestry_context)
        self.assertTrue(ancestry_context["nearest_reference_groups"], ancestry_context)
        ancestry_projection = run(
            "ancestry.project_pca",
            {"genome_build": "GRCh37", "nearest_reference_count": 1},
        )
        self.assertEqual(ancestry_projection["status"], "completed", ancestry_projection)
        self.assertTrue(ancestry_projection["nearest_reference_groups"], ancestry_projection)

        matches_path = root / f"{source_format}.native.clinvar.matches.jsonl"
        clinvar_match = run(
            "clinvar.match_variants",
            {"db": str(clinvar_db), "output": str(matches_path), "genome_build": "GRCh37", "force": True},
        )
        self.assertEqual(clinvar_match["status"], "completed", clinvar_match)
        self.assertEqual(clinvar_match["stats"]["matched_alleles"], 1, clinvar_match)
        clinvar_scan = run(
            "clinvar.scan_candidates",
            {
                "db": str(clinvar_db),
                "output": str(root / f"{source_format}.native.clinvar.candidates.json"),
                "genome_build": "GRCh37",
                "force": True,
            },
        )
        self.assertEqual(clinvar_scan["status"], "completed", clinvar_scan)
        self.assertEqual(clinvar_scan["summary"]["total_match_variants"], 1, clinvar_scan)

        with self._mock_native_pgx_sources():
            pgx = run(
                "pharmacogenomics.review_medication",
                {
                    "drug": "nativedrug",
                    "rsid": NATIVE_VARIANT_RSID,
                    "genome_build": "GRCh37",
                    "db": str(clinvar_db),
                    "include_active_genome_index": True,
                    "limit": 5,
                },
            )
        self.assertEqual(pgx["status"], "completed", pgx)
        self.assertIn("sample_evidence", pgx)

        call_operation(
            "active_genome_index.approve_access",
            {"approved_by_user": True, "reason": "native sequencing dashboard render"},
        )
        out = root / f"{source_format}.native.dashboard.html"
        real_panel_runner = handlers_screen_journal._run_decode_panel_operation

        def run_contract_panel(name: str, params: dict[str, object] | None = None) -> dict[str, object]:
            safe_params = dict(params or {})
            if name == "clinvar.scan_candidates":
                safe_params.update(
                    {
                        "db": str(clinvar_db),
                        "output": str(root / f"{source_format}.decode.clinvar.candidates.json"),
                        "genome_build": "GRCh37",
                        "force": True,
                    }
                )
            return real_panel_runner(name, safe_params)

        with mock.patch.object(handlers_screen_journal, "_run_decode_panel_operation", side_effect=run_contract_panel):
            dashboard_result = run(
                "decode.render_dashboard",
                {
                    "panels": ["overview", "variants", "variants_all", "pgx", "risk", "ancestry", "nutrigenomics"],
                    "risk_score_ids": [NATIVE_PGS_ID],
                    "nutrigenomics_domain_ids": ["folate_metabolism"],
                    "output": str(out),
                },
            )
        self.assertEqual(dashboard_result["status"], "completed", dashboard_result)
        dashboard = _extract_dashboard_evidence(out.read_text(encoding="utf-8"))
        self.assertEqual(dashboard["overview"]["genomeSource"], source_format)
        self.assertEqual(dashboard["risk"][0]["sources"], [NATIVE_PGS_ID])
        self.assertTrue(dashboard["ancestry"]["neighbors"])
        self.assertIn("pgx", dashboard_result["evidence_build"]["panels_blocked"])
        self.assertIn("pgx", dashboard_result["evidence_build"]["panels_empty"])

        self.assertLessEqual(SOURCE_FORMAT_MATRIX_OPERATIONS, seen_operations)

    def _assert_variant_support(self, *, pos: int, ref: str, alt: str, source_format: str) -> None:
        support = call_operation(
            "active_genome_index.classify_genotype_support",
            {
                "chrom": "1",
                "pos": pos,
                "ref": ref,
                "alt": alt,
                "genome_build": "GRCh37",
            },
        )
        self.assertEqual(support["status"], "completed", support)
        self.assertEqual(support["support_status"], "supported", support)
        self.assertEqual(support["sample_observation"]["agi_source_format"], source_format)

    def test_bam_parse_calls_variants_with_native_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference, pos, ref, alt, sequence = self._reference_and_variant(root)
            start, read = self._alt_read(sequence, pos=pos, alt=alt)
            bam = root / "PGP_PUBLIC_NATIVE.bam"
            self._write_bam(bam, start=start, read=read)

            self.approve_access()
            parsed = call_operation(
                "genomi.parse_source",
                {
                    "source": str(bam),
                    "reference_fasta": str(reference),
                    "genome_build": "GRCh37",
                    "force": True,
                },
            )

            self.assertEqual(parsed["status"], "completed", parsed)
            self.assertEqual(parsed["source_format"], "bam")
            self.assertIn(
                "materialize-variants-from-bam",
                [step["name"] for step in parsed["steps"]],
            )
            self.assertTrue(Path(parsed["outputs"]["derived_vcf"]).exists())
            self._assert_variant_support(pos=pos, ref=ref, alt=alt, source_format="bam")
            self._assert_native_downstream_contract(root=root, pos=pos, ref=ref, alt=alt, source_format="bam")

    def test_fastq_parse_aligns_and_calls_variants_with_native_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference, pos, ref, alt, sequence = self._reference_and_variant(root)
            _start, read = self._alt_read(sequence, pos=pos, alt=alt)
            r1 = self._write_fastq_pair(root, read)

            self.approve_access()
            parsed = call_operation(
                "genomi.parse_source",
                {
                    "source": str(r1),
                    "reference_fasta": str(reference),
                    "genome_build": "GRCh37",
                    "force": True,
                },
            )

            self.assertEqual(parsed["status"], "completed", parsed)
            self.assertEqual(parsed["source_format"], "fastq")
            self.assertEqual(parsed["aligner"], "minimap2")
            self.assertIn("align-fastq-to-bam", [step["name"] for step in parsed["steps"]])
            self.assertIn("digitize-derived-bam", [step["name"] for step in parsed["steps"]])
            self.assertTrue(Path(parsed["outputs"]["aligned_bam"]).exists())
            self._assert_variant_support(pos=pos, ref=ref, alt=alt, source_format="fastq")
            self._assert_native_downstream_contract(root=root, pos=pos, ref=ref, alt=alt, source_format="fastq")


def _extract_dashboard_evidence(html: str) -> dict[str, object]:
    marker = "window.__GENOMI_DASHBOARD__"
    assignment_index = html.find(marker)
    assert assignment_index >= 0, "no __GENOMI_DASHBOARD__ block in HTML"
    json_start = html.find("{", assignment_index)
    assert json_start >= 0, "no __GENOMI_DASHBOARD__ object in HTML"
    parsed, _end = json.JSONDecoder().raw_decode(html[json_start:].replace("<\\/", "</"))
    assert isinstance(parsed, dict), "__GENOMI_DASHBOARD__ is not an object"
    return parsed


if __name__ == "__main__":
    unittest.main()
