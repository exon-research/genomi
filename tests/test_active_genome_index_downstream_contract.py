from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
import os
import tempfile
from pathlib import Path
from unittest import mock

from genomi.active_genome_index.active_genome_index import active_genome_index_readiness
from genomi.active_genome_index.source_intake.arrays import SUPPORTED_CONSUMER_ARRAY_FORMATS
from genomi.evidence import build_clinvar_rsid_index, import_clinvar_vcf
from genomi.operations import call_operation

from _active_genome_index_contract_fixtures import (
    EXPECTED_CLINVAR_MATCHED_ALLELES,
    EXPECTED_RAW_SCORE,
    LOCUS_MODEL,
    ActiveGenomeIndexContractFixtureMixin,
)
from _genomi_runtime_helpers import GenomiRuntimeTestCase


@dataclass(frozen=True)
class SourceContractCase:
    case_id: str
    expected_format: str
    writer: Callable[[Path], Path]
    parse_overrides: dict[str, object] | None = None

    @property
    def is_consumer_array(self) -> bool:
        return self.expected_format in SUPPORTED_CONSUMER_ARRAY_FORMATS

    @property
    def expected_record_stats(self) -> dict[str, int]:
        if self.is_consumer_array:
            return {
                "total_records": len(LOCUS_MODEL),
                "variant_records": len(LOCUS_MODEL),
                "reference_records": 0,
                "pass_records": len(LOCUS_MODEL),
                "fail_records": 0,
            }
        if self.expected_format == "gvcf":
            return {
                "total_records": len(LOCUS_MODEL) + 1,
                "variant_records": 2,
                "reference_records": 3,
                "pass_records": len(LOCUS_MODEL) + 1,
                "fail_records": 0,
            }
        return {
            "total_records": len(LOCUS_MODEL),
            "variant_records": 2,
            "reference_records": 2,
            "pass_records": len(LOCUS_MODEL),
            "fail_records": 0,
        }

    @property
    def expected_callability_for_called_site(self) -> str:
        if self.is_consumer_array:
            return "unknown_no_reference_blocks"
        return "unknown_missing_depth"

    @property
    def expected_callability_for_unrepresented_site(self) -> str:
        if self.is_consumer_array:
            return "unknown_no_reference_blocks"
        return "not_callable"

    @property
    def expected_clinvar_scanned_records(self) -> int:
        if self.is_consumer_array:
            return len(LOCUS_MODEL)
        return EXPECTED_CLINVAR_MATCHED_ALLELES

    @property
    def expected_source_kind(self) -> str:
        return {
            "bam": "alignment_reads",
            "fastq": "paired_reads_input",
        }.get(
            self.expected_format,
            "consumer_genotype_array" if self.is_consumer_array else "variant_callset",
        )


@dataclass(frozen=True)
class LocusContract:
    rsid: str
    chrom: str
    pos: int
    ref: str
    alt: str
    expected_alt_observed: bool
    expected_alt_count: int | None
    expected_zygosity: str


LOCUS_CONTRACTS = (
    LocusContract("rs900000001", "1", 100, "A", "C", True, 2, "homozygous_alternate"),
    LocusContract("rs900000002", "1", 200, "T", "G", True, 1, "heterozygous"),
    LocusContract("rs900000003", "1", 300, "A", "G", False, 0, "reference_or_other_alternate"),
    LocusContract("rs900000004", "1", 400, "C", "T", False, 0, "reference_or_other_alternate"),
)

UNREPRESENTED_LOCUS = LocusContract(
    rsid="rs900000099",
    chrom="1",
    pos=500,
    ref="A",
    alt="G",
    expected_alt_observed=False,
    expected_alt_count=None,
    expected_zygosity="unknown",
)


class ActiveGenomeIndexDownstreamContractTests(
    ActiveGenomeIndexContractFixtureMixin,
    GenomiRuntimeTestCase,
):
    """PGP-HMS-shaped fake sources must feed every coordinate consumer.

    Public PGP-HMS downloads are used as the source of truth for wrappers,
    member names, comments, and columns. The genotype rows here are synthetic
    and deliberately tiny.
    """

    def test_pgp_hms_shaped_supported_sources_feed_coordinate_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                scoring_file = self._write_scoring_file(Path("PGSAGI001_hmPOS_GRCh37.txt"))
                imported_score = call_operation(
                    "prs.import_scoring_file",
                    {
                        "pgs_id": "PGSAGI001",
                        "scoring_file": str(scoring_file),
                        "genome_build": "GRCh37",
                        "force": True,
                    },
                )
                self.assertEqual(imported_score["status"], "completed")
                self._install_contract_ancestry_panel()

                clinvar_db = Path("contract-clinvar.sqlite")
                clinvar_vcf = self._write_clinvar_fixture(Path("contract.clinvar.vcf"))
                import_clinvar_vcf(clinvar_vcf, clinvar_db, source_version="contract-fixture", genome_build="GRCh37")
                build_clinvar_rsid_index(clinvar_db, force=True)

                for contract in self._source_contract_cases():
                    with self.subTest(source=contract.case_id):
                        source = contract.writer(Path(contract.case_id))
                        self._assert_source_contract(
                            source,
                            contract=contract,
                            imported_score=imported_score,
                            clinvar_db=clinvar_db,
                        )

                reference = self._write_reference_fasta(Path("contract-reference.fa"))
                with self.subTest(source="bam"):
                    bam = self._write_bam_source(Path("Nebula_Genomics_BAM_format.bam"))
                    with self._mock_derived_vcf_materialization():
                        self._assert_source_contract(
                            bam,
                            contract=SourceContractCase(
                                case_id="bam",
                                expected_format="bam",
                                writer=self._write_bam_source,
                                parse_overrides={"reference_fasta": str(reference)},
                            ),
                            imported_score=imported_score,
                            clinvar_db=clinvar_db,
                        )

                with self.subTest(source="fastq"):
                    fastq = self._write_fastq_sources(Path("60820188475559_SA_L001_R1_001.fastq.gz"))
                    with self._mock_derived_vcf_materialization(), mock.patch(
                        "genomi.active_genome_index.source_intake.sequencing.align_fastq_to_bam",
                        side_effect=self._fake_align_fastq_to_bam,
                    ):
                        self._assert_source_contract(
                            fastq,
                            contract=SourceContractCase(
                                case_id="fastq",
                                expected_format="fastq",
                                writer=self._write_fastq_sources,
                                parse_overrides={"reference_fasta": str(reference)},
                            ),
                            imported_score=imported_score,
                            clinvar_db=clinvar_db,
                        )
            finally:
                os.chdir(previous)

    def test_called_consumer_array_genotypes_are_coordinate_matchable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                source = self._write_23andme_text_source(Path("array"))
                contract = SourceContractCase("23andme_coordinate_contract", "23andme", self._write_23andme_text_source)
                parsed = self._parse_contract_source(source, contract=contract)
                self._assert_parse_ready(parsed, contract)
                self._assert_variant_locus_contracts(contract)
                self._assert_genotype_support_contracts(contract)
            finally:
                os.chdir(previous)

    def test_consumer_array_no_call_rows_do_not_create_reference_block_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                contract = SourceContractCase("23andme_no_call", "23andme", self._write_23andme_no_call_source)
                source = contract.writer(Path("no_call"))
                parsed = self._parse_contract_source(source, contract=contract)
                self._assert_parse_ready(parsed, contract)

                summary = call_operation("active_genome_index.summarize")
                stats = summary["active_genome_index"]["stats"]
                self.assertEqual(stats["total_records"], 1)
                self.assertEqual(stats["variant_records"], 0)
                self.assertEqual(stats["reference_records"], 0)
                self.assertEqual(stats["pass_records"], 0)
                self.assertEqual(stats["fail_records"], 1)

                callset_qc = call_operation(
                    "active_genome_index.classify_callset_qc",
                    {"genome_build": "GRCh37", "scan_records": 100},
                )
                self.assertEqual(callset_qc["input_type"], "array_or_genotyping_callset")
                self.assertFalse(callset_qc["has_reference_blocks"])
                self.assertEqual(callset_qc["summary"]["filter_counts"], {"NO_CALL": 1})

                variant = call_operation("variant.resolve", {"rsid": "rsnocall", "genome_build": "GRCh37"})
                self.assertEqual(variant["sample_context"]["count"], 0, variant)

                support = self._genotype_support(chrom="1", pos=700, ref="A", alt="G")
                self.assertEqual(support["support_status"], "no_call")
                observation = support["sample_observation"]
                self.assertEqual(observation["record_type"], "consumer_array")
                self.assertFalse(observation["reference_call_supported"])
                self.assertIsNone(observation["alt_allele_count"])

                callability = call_operation(
                    "active_genome_index.classify_region_callability",
                    {
                        "region": "1:700-700",
                        "genome_build": "GRCh37",
                        "min_covered_fraction": 0.1,
                    },
                )
                self.assertEqual(callability["callability_status"], "unknown_no_reference_blocks")
                self.assertFalse(callability["can_support_negative_or_reference_claim"])
            finally:
                os.chdir(previous)

    def _write_23andme_no_call_source(self, stem: Path) -> Path:
        path = stem.with_name("genome_no_call.txt")
        path.write_text(
            "# file_id: no-call-contract\n"
            "# This data file is generated by 23andMe.\n"
            "# rsid\tchromosome\tposition\tgenotype\n"
            "rsnocall\t1\t700\t--\n",
            encoding="utf-8",
        )
        return path

    def _source_contract_cases(self) -> list[SourceContractCase]:
        return [
            SourceContractCase(case_id=case_id, expected_format=expected_format, writer=writer)
            for case_id, expected_format, writer in self._source_cases()
        ]

    def _assert_source_contract(
        self,
        source: Path,
        *,
        contract: SourceContractCase,
        imported_score: dict[str, object],
        clinvar_db: Path,
    ) -> None:
        parsed = self._parse_contract_source(source, contract=contract)
        self._assert_parse_ready(parsed, contract)
        self._assert_record_contract(contract)
        self._assert_variant_locus_contracts(contract)
        self._assert_callability_contract(contract)
        self._assert_prs_contract(imported_score)
        self._assert_ancestry_contract()
        matches_path = self._assert_clinvar_contract(contract, clinvar_db)
        self._assert_clinvar_scan_contract(matches_path, contract, clinvar_db)
        self._assert_genotype_support_contracts(contract)
        pgx_result = self._assert_pgx_contract(contract, clinvar_db)
        self._assert_decode_dashboard_contract(contract, pgx_result, matches_path)

    def _parse_contract_source(self, source: Path, *, contract: SourceContractCase) -> dict[str, object]:
        parse_params = {"source": str(source), "genome_build": "GRCh37", "force": True}
        parse_params.update(contract.parse_overrides or {})
        return call_operation("genomi.parse_source", parse_params)

    def _assert_parse_ready(self, parsed: dict[str, object], contract: SourceContractCase) -> None:
        self.assertEqual(parsed["status"], "completed")
        self.assertEqual(parsed["source_format"], contract.expected_format)
        readiness = active_genome_index_readiness(parsed["outputs"]["active_genome_index_path"])
        self.assertTrue(readiness["complete"], readiness)
        self.assertEqual(readiness["missing_objects"], [])

    def _assert_record_contract(self, contract: SourceContractCase) -> None:
        summary = call_operation("active_genome_index.summarize")
        self.assertTrue(summary["active_genome_index"]["active_genome_index_readiness"]["complete"], summary)
        stats = summary["active_genome_index"]["stats"]
        for key, expected in contract.expected_record_stats.items():
            self.assertEqual(stats[key], expected, f"{contract.case_id}:{key}")

        callset_qc = call_operation(
            "active_genome_index.classify_callset_qc",
            {"genome_build": "GRCh37", "scan_records": 100},
        )
        self.assertEqual(callset_qc["status"], "completed", callset_qc)
        for key, expected in contract.expected_record_stats.items():
            self.assertEqual(callset_qc["summary"][key], expected, f"{contract.case_id}:qc:{key}")
        self.assertEqual(callset_qc["summary"]["no_call_records"], 0)
        self.assertEqual(callset_qc["absence_claims_allowed_by_default"], False)
        self.assertEqual(callset_qc["has_reference_blocks"], contract.expected_record_stats["reference_records"] > 0)
        self.assertEqual(callset_qc["has_depth"], False)
        self.assertEqual(callset_qc["has_genotype_quality"], False)

    def _assert_variant_locus_contracts(self, contract: SourceContractCase) -> None:
        for index, locus in enumerate(LOCUS_MODEL):
            with self.subTest(source=contract.case_id, contract="variant.resolve", rsid=locus["rsid"]):
                variant = call_operation("variant.resolve", {"rsid": str(locus["rsid"]), "genome_build": "GRCh37"})
                self.assertEqual(variant["sample_context"]["count"], 1, variant)
                match = variant["sample_context"]["matches"][0]
                self.assertEqual(match["genotype"], self._expected_genotype_for_source(contract.expected_format, index))
                self.assertEqual(match["source_format"], contract.expected_format)
                self.assertEqual(match["source_kind"], contract.expected_source_kind)
                if contract.is_consumer_array:
                    self.assertEqual(match["observation_semantics"]["kind"], "consumer_genotype_array_call")
                    self.assertEqual(match["ref"], "N")
                    self.assertEqual(match["alt"], locus["bases"])
                else:
                    self.assertEqual(match["ref"], locus["ref"])
                    self.assertEqual(match["alt"], locus["alt"])
                    self.assertEqual(match["is_variant"], 1 if index < 2 else 0)

        missing_rsid = call_operation("variant.resolve", {"rsid": UNREPRESENTED_LOCUS.rsid, "genome_build": "GRCh37"})
        self.assertEqual(missing_rsid["sample_context"]["count"], 0, missing_rsid)
        missing_allele = call_operation(
            "variant.resolve",
            {
                "query": (
                    f"chr{UNREPRESENTED_LOCUS.chrom}:{UNREPRESENTED_LOCUS.pos}:"
                    f"{UNREPRESENTED_LOCUS.ref}:{UNREPRESENTED_LOCUS.alt}"
                ),
                "genome_build": "GRCh37",
            },
        )
        self.assertEqual(missing_allele["sample_context"]["count"], 0, missing_allele)

    def _assert_callability_contract(self, contract: SourceContractCase) -> None:
        called_site = call_operation(
            "active_genome_index.classify_region_callability",
            {
                "region": "1:100-100",
                "genome_build": "GRCh37",
                "min_covered_fraction": 0.1,
            },
        )
        self.assertEqual(called_site["status"], "completed", called_site)
        self.assertEqual(called_site["callability_status"], contract.expected_callability_for_called_site)
        self.assertEqual(called_site["covered_bases"], 0)
        self.assertFalse(called_site["can_support_negative_or_reference_claim"])
        self.assertEqual(len(called_site["matched_records"]), 1)

        unrepresented_site = call_operation(
            "active_genome_index.classify_region_callability",
            {
                "region": f"{UNREPRESENTED_LOCUS.chrom}:{UNREPRESENTED_LOCUS.pos}-{UNREPRESENTED_LOCUS.pos}",
                "genome_build": "GRCh37",
                "min_covered_fraction": 0.1,
            },
        )
        self.assertEqual(unrepresented_site["status"], "completed", unrepresented_site)
        self.assertEqual(unrepresented_site["callability_status"], contract.expected_callability_for_unrepresented_site)
        self.assertEqual(unrepresented_site["matched_records"], [])
        self.assertFalse(unrepresented_site["can_support_negative_or_reference_claim"])

    def _assert_prs_contract(self, imported_score: dict[str, object]) -> None:
        with self._tiny_prs_thresholds():
            overlap_result = call_operation(
                "prs.check_score_overlap",
                {
                    "score_dir": imported_score["score_cache"]["score_dir"],
                    "genome_build": "GRCh37",
                },
            )
            prs_result = call_operation(
                "prs.calculate_score",
                {
                    "score_dir": imported_score["score_cache"]["score_dir"],
                    "genome_build": "GRCh37",
                },
            )
        self.assertEqual(overlap_result["status"], "score_ready", overlap_result)
        self.assertEqual(overlap_result["sample_qc"]["matched_variant_count"], len(LOCUS_MODEL))
        self.assertEqual(prs_result["status"], "completed", prs_result)
        self.assertEqual(prs_result["sample_qc"]["matched_variant_count"], len(LOCUS_MODEL))
        self.assertEqual(prs_result["sample_qc"]["missing_variant_count"], 0)
        self.assertAlmostEqual(prs_result["score_result"]["raw_weighted_score"], EXPECTED_RAW_SCORE)

    def _assert_ancestry_contract(self) -> None:
        ancestry_result = call_operation("ancestry.check_sample_overlap", {"genome_build": "GRCh37"})
        self.assertEqual(ancestry_result["status"], "completed", ancestry_result)
        self.assertEqual(ancestry_result["sample_qc"]["panel_marker_count"], len(LOCUS_MODEL))
        self.assertEqual(ancestry_result["sample_qc"]["usable_marker_count"], len(LOCUS_MODEL))
        self.assertEqual(ancestry_result["sample_qc"]["missing_marker_count"], 0)

    def _assert_clinvar_contract(self, contract: SourceContractCase, clinvar_db: Path) -> Path:
        matches_path = Path(f"{contract.case_id}.clinvar.matches.jsonl")
        clinvar_result = call_operation(
            "clinvar.match_variants",
            {
                "db": str(clinvar_db),
                "output": str(matches_path),
                "genome_build": "GRCh37",
                "force": True,
            },
        )
        self.assertEqual(clinvar_result["status"], "completed", clinvar_result)
        self.assertEqual(clinvar_result["stats"]["scanned_records"], contract.expected_clinvar_scanned_records)
        self.assertEqual(clinvar_result["stats"]["queried_alleles"], contract.expected_clinvar_scanned_records)
        self.assertEqual(clinvar_result["stats"]["matched_alleles"], EXPECTED_CLINVAR_MATCHED_ALLELES)
        self.assertEqual(clinvar_result["stats"]["written_records"], EXPECTED_CLINVAR_MATCHED_ALLELES)
        self._assert_clinvar_payloads_are_real_alleles(matches_path, expected_format=contract.expected_format)
        return matches_path

    def _assert_clinvar_scan_contract(
        self,
        matches_path: Path,
        contract: SourceContractCase,
        clinvar_db: Path,
    ) -> None:
        scanned = call_operation(
            "clinvar.scan_candidates",
            {
                "matches": str(matches_path),
                "db": str(clinvar_db),
                "output": str(Path(f"{contract.case_id}.clinvar.candidates.json")),
                "genome_build": "GRCh37",
                "force": True,
            },
        )
        self.assertEqual(scanned["status"], "completed", scanned)
        candidates_by_pos = {int(candidate["variant"]["pos"]): candidate for candidate in scanned["candidate_inventory"]}
        self.assertIn(200, candidates_by_pos)
        self.assertIn("heterozygous_p_lp_context_needed", candidates_by_pos[200]["buckets"])
        if contract.expected_format in {"vcf", "gvcf", "bam", "fastq"}:
            self.assertEqual(candidates_by_pos[200]["match_provenance"]["primary_match_basis"], "exact_allele")
        else:
            self.assertEqual(
                candidates_by_pos[200]["match_provenance"]["primary_match_basis"],
                "consumer_array_allele_inference",
            )
            self.assertEqual(candidates_by_pos[200]["variant"]["source_record_ref"], "N")
            self.assertEqual(candidates_by_pos[200]["variant"]["source_record_format"], "GT_ARRAY")

    def _assert_genotype_support_contracts(self, contract: SourceContractCase) -> None:
        for index, locus in enumerate(LOCUS_CONTRACTS):
            with self.subTest(source=contract.case_id, contract="genotype_support", rsid=locus.rsid):
                support = self._genotype_support(chrom=locus.chrom, pos=locus.pos, ref=locus.ref, alt=locus.alt)
                observation = support["sample_observation"]
                self.assertEqual(observation["target_alt_observed"], locus.expected_alt_observed)
                self.assertEqual(observation["alt_allele_count"], locus.expected_alt_count)
                self.assertEqual(observation["zygosity"], locus.expected_zygosity)
                if index < 2:
                    self.assertEqual(support["support_status"], "unknown")
                    self.assertEqual(observation["observed"], True)
                else:
                    self.assertEqual(support["support_status"], "not_observed")
                    self.assertEqual(observation["observed"], False)
                if contract.is_consumer_array:
                    self.assertEqual(observation["record_type"], "consumer_array")
                    self.assertEqual(observation["matched_by"], "consumer_array_letter_genotype")
                    self.assertFalse(observation["reference_call_supported"])
                elif index < 2:
                    self.assertEqual(observation["record_type"], "variant_call")
                    self.assertEqual(observation["matched_by"], "exact_variant")
                    self.assertFalse(observation["reference_call_supported"])
                else:
                    self.assertEqual(observation["record_type"], "reference_block")
                    self.assertEqual(observation["matched_by"], "reference_block")
                    self.assertTrue(observation["reference_call_supported"])

        support = self._genotype_support(
            chrom=UNREPRESENTED_LOCUS.chrom,
            pos=UNREPRESENTED_LOCUS.pos,
            ref=UNREPRESENTED_LOCUS.ref,
            alt=UNREPRESENTED_LOCUS.alt,
        )
        observation = support["sample_observation"]
        self.assertEqual(support["support_status"], "unknown")
        self.assertEqual(observation["site_status"], "not_represented")
        self.assertEqual(observation["target_alt_observed"], False)
        self.assertIsNone(observation["alt_allele_count"])
        self.assertFalse(observation["reference_call_supported"])

    def _assert_pgx_contract(self, contract: SourceContractCase, clinvar_db: Path) -> dict[str, object]:
        with self.subTest(source=contract.case_id, contract="pharmacogenomics.review_medication"):
            with self._mock_contract_pgx_sources():
                result = call_operation(
                    "pharmacogenomics.review_medication",
                    {
                        "drug": "contractdrug",
                        "rsid": "rs900000002",
                        "genome_build": "GRCh37",
                        "db": str(clinvar_db),
                        "include_active_genome_index": True,
                        "limit": 5,
                    },
                )
            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(result["sample_evidence"]["sample_match_count"], 1, result)
            self.assertEqual(result["sample_evidence"]["variant_lookups"][0]["sample_context"]["matches"][0]["source_format"], contract.expected_format)
            self.assertEqual(result["target_inventory"]["rsid_targets"], ["rs900000002"])
            self.assertEqual(
                result["target_inventory"]["genotype_support_loci"],
                [{"chrom": "1", "pos": 200, "ref": "T", "alt": "G", "genome_build": "GRCh37"}],
            )
            self.assertTrue(result["evidence_state"]["has_sample_evidence"])
            self.assertTrue(result["evidence_state"]["has_active_genome_variant_match"])
            self.assertNotIn("has_vcf_technical_support", result["evidence_state"])
            self.assertNotIn("has_vcf_derived_sample_signal", result["evidence_state"])
            if contract.is_consumer_array:
                self.assertEqual(result["answer_support"]["technical_sample_support"]["status"], "observed_genotype_available")
            return result

    def _assert_decode_dashboard_contract(
        self,
        contract: SourceContractCase,
        pgx_result: dict[str, object],
        matches_path: Path,
    ) -> None:
        with self.subTest(source=contract.case_id, contract="decode.render_dashboard"):
            call_operation(
                "active_genome_index.approve_access",
                {"approved_by_user": True, "reason": "contract dashboard render"},
            )
            out = Path(f"{contract.case_id}.dashboard.html")
            result = call_operation(
                "decode.render_dashboard",
                {
                    "evidence": {
                        "overview": {
                            "sampleId": contract.case_id,
                            "genomeBuild": "GRCh37",
                            "variantCount": contract.expected_record_stats["variant_records"],
                            "sourceFormat": contract.expected_format,
                        },
                        "variants": [
                            {
                                "rsid": "rs900000002",
                                "gene": "GENE2",
                                "chrom": "1",
                                "pos": 200,
                                "ref": "T",
                                "alt": "G",
                                "zygosity": "heterozygous",
                            }
                        ],
                        "pgx": [
                            {
                                "drug": "contractdrug",
                                "rsid": "rs900000002",
                                "sampleMatchCount": pgx_result["sample_evidence"]["sample_match_count"],
                                "technicalSupport": pgx_result["answer_support"]["technical_sample_support"]["status"],
                            }
                        ],
                    },
                    "variants_all_source": str(matches_path),
                    "mode": "full",
                    "output": str(out),
                },
            )
            self.assertEqual(result["status"], "completed", result)
            self.assertTrue(out.is_file())
            self.assertIn("overview", result["panels_rendered"])
            self.assertIn("variants", result["panels_rendered"])
            self.assertIn("variants_all", result["panels_rendered"])
            self.assertIn("pgx", result["panels_rendered"])

    @contextmanager
    def _mock_contract_pgx_sources(self):
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "status": "completed",
            "summary": {
                "guideline_annotation_count": 1,
                "clinical_annotation_count": 0,
                "label_annotation_count": 0,
            },
            "sample_follow_up_targets": {"rsids": ["rs900000002"], "genes": []},
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
            "summary": {
                "pgx_record_count": 1,
                "medication_scoped_gene_drug_record_count": 0,
            },
            "pgx_records": [
                {
                    "rsid": "rs900000002",
                    "variant_or_haplotype": "rs900000002",
                    "drug": "contractdrug",
                    "alleles": "GT",
                    "sentence": "Genotype GT is fixture evidence for contractdrug response context.",
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
            mock.patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            mock.patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            mock.patch("genomi.capabilities.pharmacogenomics.review.fda_pgx.lookup_fda_pgx", return_value=fda_result),
        ):
            yield
