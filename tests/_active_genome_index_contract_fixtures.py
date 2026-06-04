from __future__ import annotations

import bz2
import gzip
import io
import json
import lzma
import tarfile
import zipfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from genomi.capabilities.ancestry import reference_panels
from genomi.capabilities.ancestry import source_context as ancestry_source_context
from genomi.capabilities.prs import scorer as prs_scorer
from genomi.operations import call_operation


LOCUS_MODEL = [
    {
        "rsid": "rs900000001",
        "chrom": "1",
        "pos": 100,
        "ref": "A",
        "alt": "C",
        "bases": "CC",
        "vcf_gt": "1/1",
        "effect": "C",
        "other": "A",
        "weight": 0.5,
    },
    {
        "rsid": "rs900000002",
        "chrom": "1",
        "pos": 200,
        "ref": "T",
        "alt": "G",
        "bases": "GT",
        "vcf_gt": "0/1",
        "effect": "G",
        "other": "T",
        "weight": 1.0,
    },
    {
        "rsid": "rs900000003",
        "chrom": "1",
        "pos": 300,
        "ref": "A",
        "alt": "G",
        "bases": "AA",
        "vcf_gt": "0/0",
        "effect": "G",
        "other": "A",
        "weight": -0.25,
    },
    {
        "rsid": "rs900000004",
        "chrom": "1",
        "pos": 400,
        "ref": "C",
        "alt": "T",
        "bases": "CC",
        "vcf_gt": "0/0",
        "effect": "T",
        "other": "C",
        "weight": 2.0,
    },
]

EXPECTED_RAW_SCORE = 2.0
EXPECTED_CLINVAR_MATCHED_ALLELES = 2


class ActiveGenomeIndexContractFixtureMixin:
    def _expected_genotype_for_source(self, source_format: str, locus_index: int) -> str:
        if source_format in {"vcf", "gvcf", "bam", "fastq"}:
            return str(LOCUS_MODEL[locus_index]["vcf_gt"])
        return str(LOCUS_MODEL[locus_index]["bases"])

    def _genotype_support(self, *, chrom: str, pos: int, ref: str, alt: str) -> dict[str, object]:
        result = call_operation(
            "active_genome_index.classify_genotype_support",
            {
                "chrom": chrom,
                "pos": pos,
                "ref": ref,
                "alt": alt,
                "db": "contract-genotype-support.sqlite",
                "genome_build": "GRCh37",
            },
        )
        self.assertEqual(result["status"], "completed", result)
        return result

    def _source_cases(self) -> list[tuple[str, str, Callable[[Path], Path]]]:
        return [
            ("vcf", "vcf", self._write_vcf_source),
            ("vcf_gz", "vcf", self._write_vcf_gzip_source),
            ("vcf_bz2", "vcf", self._write_vcf_bzip2_source),
            ("vcf_xz", "vcf", self._write_vcf_xz_source),
            ("vcf_zip", "vcf", self._write_vcf_zip_source),
            ("vcf_tar", "vcf", self._write_vcf_tar_source),
            ("gvcf", "gvcf", self._write_gvcf_source),
            ("gvcf_gz", "gvcf", self._write_gvcf_gzip_source),
            ("gvcf_bz2", "gvcf", self._write_gvcf_bzip2_source),
            ("gvcf_xz", "gvcf", self._write_gvcf_xz_source),
            ("gvcf_zip", "gvcf", self._write_gvcf_zip_source),
            ("gvcf_tar", "gvcf", self._write_gvcf_tar_source),
            ("23andme_txt", "23andme", self._write_23andme_text_source),
            ("23andme_zip", "23andme", self._write_23andme_zip_source),
            ("23andme_tar", "23andme", self._write_23andme_tar_source),
            ("ancestrydna_txt", "ancestrydna", self._write_ancestry_text_source),
            ("ancestrydna_zip", "ancestrydna", self._write_ancestry_zip_source),
            ("ancestrydna_tar", "ancestrydna", self._write_ancestry_tar_source),
            ("myheritage_csv", "myheritage", self._write_myheritage_csv_source),
            ("myheritage_zip", "myheritage", self._write_myheritage_zip_source),
            ("myheritage_tar", "myheritage", self._write_myheritage_tar_source),
            ("ftdna_csv", "ftdna", self._write_ftdna_csv_source),
            ("ftdna_csv_gz", "ftdna", self._write_ftdna_gzip_source),
            ("ftdna_zip", "ftdna", self._write_ftdna_zip_source),
            ("ftdna_tar", "ftdna", self._write_ftdna_tar_source),
            ("livingdna_txt", "livingdna", self._write_livingdna_text_source),
            ("livingdna_zip", "livingdna", self._write_livingdna_zip_source),
            ("livingdna_tar", "livingdna", self._write_livingdna_tar_source),
        ]

    def _sequencing_source_case_formats(self) -> dict[str, str]:
        return {
            "bam": "bam",
            "bam_zip": "bam",
            "bam_tar": "bam",
            "fastq": "fastq",
            "fastq_zip": "fastq",
            "fastq_tar": "fastq",
        }

    def _write_zip_members(self, path: Path, members: list[tuple[str, bytes]]) -> Path:
        with zipfile.ZipFile(path, "w") as archive:
            for member_name, content in members:
                archive.writestr(member_name, content)
        return path

    def _write_zip_member(self, path: Path, member_name: str, content: bytes) -> Path:
        return self._write_zip_members(path, [(member_name, content)])

    def _write_tar_members(self, path: Path, members: list[tuple[str, bytes]]) -> Path:
        with tarfile.open(path, "w:gz") as archive:
            for member_name, content in members:
                info = tarfile.TarInfo(member_name)
                info.size = len(content)
                archive.addfile(info, fileobj=io.BytesIO(content))
        return path

    def _write_tar_member(self, path: Path, member_name: str, content: bytes) -> Path:
        return self._write_tar_members(path, [(member_name, content)])

    def _fastq_record_bytes(self) -> bytes:
        sequence = "ACGT" * 40
        return f"@contract\n{sequence}\n+\n{'I' * len(sequence)}\n".encode("utf-8")

    def _write_reference_fasta(self, path: Path) -> Path:
        path.write_text(">1\n" + "A" * 1000 + "\n", encoding="utf-8")
        return path

    def _write_bam_source(self, path: Path) -> Path:
        path.write_bytes(b"BAM\x01")
        return path

    def _write_bam_zip_source(self, stem: Path) -> Path:
        path = stem.with_name("Nebula_Genomics_BAM_format.zip")
        return self._write_zip_member(path, "reads/Nebula_Genomics_BAM_format.bam", b"BAM\x01")

    def _write_bam_tar_source(self, stem: Path) -> Path:
        path = stem.with_name("Nebula_Genomics_BAM_format.tar.gz")
        return self._write_tar_member(path, "reads/Nebula_Genomics_BAM_format.bam", b"BAM\x01")

    def _write_fastq_sources(self, r1_path: Path) -> Path:
        r2_path = r1_path.with_name(r1_path.name.replace("_R1_", "_R2_"))
        record = self._fastq_record_bytes()
        with gzip.open(r1_path, "wb") as handle:
            handle.write(record)
        with gzip.open(r2_path, "wb") as handle:
            handle.write(record)
        return r1_path

    def _write_fastq_zip_sources(self, stem: Path) -> Path:
        path = stem.with_name("GENOS_fastq_pair.zip")
        record = self._fastq_record_bytes()
        return self._write_zip_members(
            path,
            [
                ("reads/60820188475559_SA_L001_R1_001.fastq.gz", gzip.compress(record)),
                ("reads/60820188475559_SA_L001_R2_001.fastq.gz", gzip.compress(record)),
            ],
        )

    def _write_fastq_tar_sources(self, stem: Path) -> Path:
        path = stem.with_name("GENOS_fastq_pair.tar.gz")
        record = self._fastq_record_bytes()
        return self._write_tar_members(
            path,
            [
                ("reads/60820188475559_SA_L001_R1_001.fastq.gz", gzip.compress(record)),
                ("reads/60820188475559_SA_L001_R2_001.fastq.gz", gzip.compress(record)),
            ],
        )

    @contextmanager
    def _mock_derived_vcf_materialization(self):
        with (
            mock.patch("genomi.active_genome_index.source_intake.sequencing.infer_genome_build_from_bam", return_value="GRCh37"),
            mock.patch(
                "genomi.active_genome_index.source_intake.sequencing.materialize_bam_variant_vcf",
                side_effect=self._fake_materialize_bam_variant_vcf,
            ),
        ):
            yield

    def _fake_align_fastq_to_bam(
        self,
        r1: str | Path,
        r2: str | Path,
        reference_fasta: str | Path,
        output_bam: str | Path,
        *,
        aligner: str = "auto",
        threads: int = 4,
        force: bool = False,
    ) -> dict[str, object]:
        del r1, r2, reference_fasta, aligner, threads, force
        Path(output_bam).write_bytes(b"BAM\x01")
        return {
            "status": "completed",
            "aligner": "bwa-mem2",
            "median_read_length": 160,
            "output": str(output_bam),
            "manifest_path": str(Path(f"{output_bam}.genomi-manifest.json")),
        }

    def _fake_materialize_bam_variant_vcf(
        self,
        bam_path: Path,
        reference_fasta: Path,
        output_vcf: Path,
        *,
        force: bool = False,
    ) -> dict[str, object]:
        del bam_path, reference_fasta, force
        self._write_contract_vcf(output_vcf)
        return {
            "status": "completed",
            "output": str(output_vcf),
            "manifest_path": str(Path(f"{output_vcf}.genomi-manifest.json")),
        }

    def _write_scoring_file(self, path: Path) -> Path:
        rows = [
            "#pgs_id=PGSAGI001",
            "#pgs_name=AGI downstream contract fixture",
            "#reported_trait=AGI downstream contract",
            "hm_chr\thm_pos\trsID\teffect_allele\tother_allele\teffect_weight",
        ]
        for locus in LOCUS_MODEL:
            rows.append(
                "\t".join(
                    [
                        str(locus["chrom"]),
                        str(locus["pos"]),
                        str(locus["rsid"]),
                        str(locus["effect"]),
                        str(locus["other"]),
                        str(locus["weight"]),
                    ]
                )
            )
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return path

    def _write_clinvar_fixture(self, path: Path) -> Path:
        rows = [
            "##fileformat=VCFv4.2",
            "##source=GenomiActiveGenomeIndexDownstreamContract",
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
        ]
        for index, locus in enumerate(LOCUS_MODEL[:EXPECTED_CLINVAR_MATCHED_ALLELES], start=1):
            rows.append(
                "\t".join(
                    [
                        str(locus["chrom"]),
                        str(locus["pos"]),
                        f"CNV{index}",
                        str(locus["ref"]),
                        str(locus["alt"]),
                        ".",
                        ".",
                        (
                            f"ALLELEID={9000 + index};RS={str(locus['rsid']).removeprefix('rs')};CLNSIG=Pathogenic;"
                            "CLNREVSTAT=criteria_provided,_single_submitter;"
                            f"CLNDN=Contract_condition_{index};GENEINFO=GENE{index}:{index}"
                        ),
                    ]
                )
            )
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return path

    def _install_contract_ancestry_panel(self) -> None:
        panel_dir = reference_panels.panel_dir(genome_build="GRCh37")
        panel_dir.mkdir(parents=True, exist_ok=True)
        marker_rows = [
            {
                "marker_id": str(locus["rsid"]),
                "chrom": str(locus["chrom"]),
                "pos": str(locus["pos"]),
                "ref": str(locus["ref"]),
                "alt": str(locus["alt"]),
                "mean": "1.0",
                "scale": "1.0",
            }
            for locus in LOCUS_MODEL
        ]
        self._write_tsv(
            panel_dir / reference_panels.MARKERS_NAME,
            ["marker_id", "chrom", "pos", "ref", "alt", "mean", "scale"],
            marker_rows,
        )
        self._write_tsv(
            panel_dir / reference_panels.SAMPLES_NAME,
            ["sample_id", "population", "superpopulation", "sex"],
            [
                {"sample_id": "REF1", "population": "CEU", "superpopulation": "EUR", "sex": ""},
                {"sample_id": "REF2", "population": "YRI", "superpopulation": "AFR", "sex": ""},
            ],
        )
        self._write_tsv(
            panel_dir / reference_panels.LOADINGS_NAME,
            ["marker_id", "PC1"],
            [{"marker_id": str(locus["rsid"]), "PC1": "0.1"} for locus in LOCUS_MODEL],
        )
        self._write_tsv(
            panel_dir / reference_panels.REFERENCE_SCORES_NAME,
            ["sample_id", "population", "superpopulation", "PC1"],
            [
                {"sample_id": "REF1", "population": "CEU", "superpopulation": "EUR", "PC1": "0.2"},
                {"sample_id": "REF2", "population": "YRI", "superpopulation": "AFR", "PC1": "-0.2"},
            ],
        )
        now = "2026-01-01T00:00:00Z"
        (panel_dir / reference_panels.PANEL_STATS_NAME).write_text(
            json.dumps(
                {
                    "schema": "genomi-ancestry-panel-stats-v1",
                    "sample_count": 2,
                    "marker_count": len(LOCUS_MODEL),
                    "component_count": 1,
                    "target_marker_count": len(LOCUS_MODEL),
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
                    "schema": "genomi-ancestry-reference-panel-v1",
                    "panel_id": ancestry_source_context.panel_id_for_build("GRCh37"),
                    "title": ancestry_source_context.PANEL_TITLE_GRCH37,
                    "library": ancestry_source_context.panel_library_for_build("GRCh37"),
                    "genome_build": "GRCh37",
                    "sample_count": 2,
                    "marker_count": len(LOCUS_MODEL),
                    "component_count": 1,
                    "built_at": now,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def _write_tsv(self, path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
        lines = ["\t".join(fieldnames)]
        for row in rows:
            lines.append("\t".join(str(row.get(field, "")) for field in fieldnames))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_vcf_source(self, stem: Path) -> Path:
        path = stem.with_suffix(".vcf")
        self._write_contract_vcf(path)
        return path

    def _write_vcf_gzip_source(self, stem: Path) -> Path:
        path = stem.with_name("NG1N4ZH3KB.mm2.sortdup.bqsr.hc.vcf.gz")
        with gzip.open(path, "wb") as handle:
            handle.write(self._contract_vcf_text().encode("utf-8"))
        return path

    def _write_vcf_bzip2_source(self, stem: Path) -> Path:
        path = stem.with_name("ANCESTRYDNAOpenHumansParsed.vcf.bz2")
        path.write_bytes(bz2.compress(self._contract_vcf_text().encode("utf-8")))
        return path

    def _write_vcf_xz_source(self, stem: Path) -> Path:
        path = stem.with_name("pgp-supported-wrapper.vcf.xz")
        path.write_bytes(lzma.compress(self._contract_vcf_text().encode("utf-8")))
        return path

    def _write_vcf_zip_source(self, stem: Path) -> Path:
        path = stem.with_suffix(".zip")
        return self._write_zip_member(
            path,
            "68484e35b07b48cd9eed01d1a0110ff0.vcf",
            self._contract_vcf_text().encode("utf-8"),
        )

    def _write_vcf_tar_source(self, stem: Path) -> Path:
        path = stem.with_name("pgp-supported-vcf-wrapper.tar.gz")
        return self._write_tar_member(path, "genome/sample.vcf", self._contract_vcf_text().encode("utf-8"))

    def _write_contract_vcf(self, path: Path) -> Path:
        path.write_text(self._contract_vcf_text(), encoding="utf-8")
        return path

    def _contract_vcf_text(self) -> str:
        rows = [
            "##fileformat=VCFv4.2",
            '##FILTER=<ID=PASS,Description="All filters passed">',
            "##source=loimpute",
            "##reference=b37_g1k",
            "##generatedby=Gencove",
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            '##FORMAT=<ID=GP,Number=G,Type=Float,Description="Genotype Probabilities">',
            '##FORMAT=<ID=DS,Number=1,Type=Float,Description="Estimated Alternate Allele Dosage">',
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
        ]
        for locus in LOCUS_MODEL:
            rows.append(
                "\t".join(
                    [
                        str(locus["chrom"]),
                        str(locus["pos"]),
                        str(locus["rsid"]),
                        str(locus["ref"]),
                        str(locus["alt"]),
                        ".",
                        "PASS",
                        ".",
                        "GT",
                        str(locus["vcf_gt"]),
                    ]
                )
            )
        return "\n".join(rows) + "\n"

    def _write_gvcf_source(self, stem: Path) -> Path:
        path = stem.with_suffix(".g.vcf")
        path.write_text(self._contract_gvcf_text(), encoding="utf-8")
        return path

    def _write_gvcf_gzip_source(self, stem: Path) -> Path:
        path = stem.with_name("60820188475559_SA_L001_R1_001.fastq.gz.10009.g.vcf.gz")
        with gzip.open(path, "wb") as handle:
            handle.write(self._contract_gvcf_text().encode("utf-8"))
        return path

    def _write_gvcf_bzip2_source(self, stem: Path) -> Path:
        path = stem.with_name("huA2692E-veritas-gVCF-4.2.vcf.bz2")
        path.write_bytes(bz2.compress(self._contract_gvcf_text().encode("utf-8")))
        return path

    def _write_gvcf_xz_source(self, stem: Path) -> Path:
        path = stem.with_name("huA2692E-veritas-gVCF-4.2.vcf.xz")
        path.write_bytes(lzma.compress(self._contract_gvcf_text().encode("utf-8")))
        return path

    def _write_gvcf_zip_source(self, stem: Path) -> Path:
        path = stem.with_name("huA2692E-veritas-gVCF-4.2.zip")
        return self._write_zip_member(
            path,
            "huA2692E-veritas-gVCF-4.2.vcf",
            self._contract_gvcf_text().encode("utf-8"),
        )

    def _write_gvcf_tar_source(self, stem: Path) -> Path:
        path = stem.with_name("pgp-supported-gvcf-wrapper.tar.gz")
        return self._write_tar_member(
            path,
            "gvcf/huA2692E-veritas-gVCF-4.2.vcf",
            self._contract_gvcf_text().encode("utf-8"),
        )

    def _contract_gvcf_text(self) -> str:
        rows = [
            "##fileformat=VCFv4.2",
            '##ALT=<ID=NON_REF,Description="Represents any possible alternative allele at this location">',
            '##INFO=<ID=END,Number=1,Type=Integer,Description="End position of the reference block">',
            '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Approximate read depth">',
            '##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Genotype Quality">',
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            "##GVCFBlock0-1=minGQ=0(inclusive),maxGQ=1(exclusive)",
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
            "1\t1\t.\tA\t<NON_REF>\t.\tPASS\tEND=99\tGT\t0/0",
        ]
        for locus in LOCUS_MODEL:
            rows.append(
                "\t".join(
                    [
                        str(locus["chrom"]),
                        str(locus["pos"]),
                        str(locus["rsid"]),
                        str(locus["ref"]),
                        str(locus["alt"]),
                        ".",
                        "PASS",
                        ".",
                        "GT",
                        str(locus["vcf_gt"]),
                    ]
                )
            )
        return "\n".join(rows) + "\n"

    def _write_23andme_text_source(self, stem: Path) -> Path:
        path = stem.with_name("genome_Lorena_Sandoval_v5_Full_20260429131650.txt")
        path.write_text(self._23andme_text(), encoding="utf-8")
        return path

    def _write_23andme_zip_source(self, stem: Path) -> Path:
        path = stem.with_name("genome_Marika_Forsythe_v4_Full_20240826181111.zip")
        return self._write_zip_member(
            path,
            "genome_Marika_Forsythe_v4_Full_20240828221950.txt",
            self._23andme_text().encode("utf-8"),
        )

    def _write_23andme_tar_source(self, stem: Path) -> Path:
        path = stem.with_name("genome_Lorena_Sandoval_v5_Full_20260429131650.tar.gz")
        return self._write_tar_member(
            path,
            "23andMe/genome_Lorena_Sandoval_v5_Full_20260429131650.txt",
            self._23andme_text().encode("utf-8"),
        )

    def _23andme_text(self) -> str:
        rows = [
            "# file_id: synthetic-pgp-contract-fixture",
            "# signature: synthetic",
            "# timestamp: 2026-04-29 13:16:50",
            "#",
            "# This data file is generated by 23andMe.",
            "#",
            "# Below is a text version of your data.  Fields are TAB-separated",
            "# We are using reference human assembly build 37 (also known as Annotation Release 104).",
            "# rsid\tchromosome\tposition\tgenotype",
        ]
        rows.extend(f"{locus['rsid']}\t{locus['chrom']}\t{locus['pos']}\t{locus['bases']}" for locus in LOCUS_MODEL)
        return "\n".join(rows) + "\n"

    def _write_ancestry_text_source(self, stem: Path) -> Path:
        path = stem.with_name("AncestryDNA.txt")
        path.write_text(self._ancestry_text(), encoding="utf-8")
        return path

    def _write_ancestry_zip_source(self, stem: Path) -> Path:
        path = stem.with_name("dna-data-2023-04-26.zip")
        return self._write_zip_member(
            path,
            "AncestryDNA.txt",
            self._ancestry_text().encode("utf-8"),
        )

    def _write_ancestry_tar_source(self, stem: Path) -> Path:
        path = stem.with_name("AncestryDNA.tar.gz")
        return self._write_tar_member(
            path,
            "AncestryDNA.txt",
            self._ancestry_text().encode("utf-8"),
        )

    def _ancestry_text(self) -> str:
        rows = [
            "#AncestryDNA raw data download",
            "#This file was generated by AncestryDNA at: 04/26/2023 04:30:29 UTC",
            "#Data was collected using AncestryDNA array version: V2.0",
            "#Data is formatted using AncestryDNA converter version: V1.0",
            "#Genetic data is reported using human reference build 37.1 coordinates.",
            "rsid\tchromosome\tposition\tallele1\tallele2",
        ]
        rows.extend(
            f"{locus['rsid']}\t{locus['chrom']}\t{locus['pos']}\t{str(locus['bases'])[0]}\t{str(locus['bases'])[1]}"
            for locus in LOCUS_MODEL
        )
        return "\n".join(rows) + "\n"

    def _write_myheritage_csv_source(self, stem: Path) -> Path:
        path = stem.with_name("MyHeritage_raw_dna_data.csv")
        path.write_text(self._consumer_csv(include_banner=True), encoding="utf-8")
        return path

    def _write_myheritage_zip_source(self, stem: Path) -> Path:
        path = stem.with_name("Dave_raw_dna_data.zip")
        return self._write_zip_member(
            path,
            "MyHeritage_raw_dna_data.csv",
            self._consumer_csv(include_banner=True).encode("utf-8"),
        )

    def _write_myheritage_tar_source(self, stem: Path) -> Path:
        path = stem.with_name("Dave_raw_dna_data.tar.gz")
        return self._write_tar_member(
            path,
            "MyHeritage_raw_dna_data.csv",
            self._consumer_csv(include_banner=True).encode("utf-8"),
        )

    def _write_ftdna_csv_source(self, stem: Path) -> Path:
        path = stem.with_name("AM34047_Autosomal_o37_Results_20200820.csv")
        path.write_text(self._consumer_csv(include_banner=False), encoding="utf-8")
        return path

    def _write_ftdna_gzip_source(self, stem: Path) -> Path:
        path = stem.with_name("AM34047_Autosomal_o37_Results_20200820.csv.gz")
        with gzip.open(path, "wb") as handle:
            handle.write(self._consumer_csv(include_banner=False).encode("utf-8"))
        return path

    def _write_ftdna_zip_source(self, stem: Path) -> Path:
        path = stem.with_name("AM34047_Autosomal_o37_Results_20200820.zip")
        return self._write_zip_member(
            path,
            "Family_Finder/AM34047_Autosomal_o37_Results_20200820.csv",
            self._consumer_csv(include_banner=False).encode("utf-8"),
        )

    def _write_ftdna_tar_source(self, stem: Path) -> Path:
        path = stem.with_name("AM34047_Autosomal_o37_Results_20200820.tar.gz")
        return self._write_tar_member(
            path,
            "Family_Finder/AM34047_Autosomal_o37_Results_20200820.csv",
            self._consumer_csv(include_banner=False).encode("utf-8"),
        )

    def _consumer_csv(self, *, include_banner: bool) -> str:
        rows = []
        if include_banner:
            rows.extend(
                [
                    "# MyHeritage DNA raw data. ",
                    "# This file was generated on 2018-01-01 02:34:37 ",
                    "# For each SNP, we provide the identifier, chromosome number, base pair position and genotype.",
                    "# The genotype is reported on the forward (+) strand with respect to the human reference build 37. ",
                ]
            )
        rows.append("RSID,CHROMOSOME,POSITION,RESULT")
        rows.extend(
            f'"{locus["rsid"]}","{locus["chrom"]}","{locus["pos"]}","{locus["bases"]}"'
            for locus in LOCUS_MODEL
        )
        return "\n".join(rows) + "\n"

    def _write_livingdna_text_source(self, stem: Path) -> Path:
        path = stem.with_name("living-dna-LD0251144A-autosomal.txt")
        path.write_text(self._livingdna_text(), encoding="utf-8")
        return path

    def _write_livingdna_zip_source(self, stem: Path) -> Path:
        path = stem.with_name("living-dna-LD0251144A-autosomal.zip")
        return self._write_zip_member(
            path,
            "living-dna-LD0251144A-autosomal.txt",
            self._livingdna_text().encode("utf-8"),
        )

    def _write_livingdna_tar_source(self, stem: Path) -> Path:
        path = stem.with_name("living-dna-LD0251144A-autosomal.tar.gz")
        return self._write_tar_member(
            path,
            "living-dna-LD0251144A-autosomal.txt",
            self._livingdna_text().encode("utf-8"),
        )

    def _livingdna_text(self) -> str:
        rows = [
            "# Living DNA customer genotype data download file version: 1.0.2",
            "# File creation date: 9-3-2019",
            "# Genotype chip: Sirius",
            "# The content of this file is subject to updates and changes depending on the time of download.",
            "# Human Genome Reference Build 37 (GRCh37.p13).",
            "# rsid\tchromosome\tposition\tgenotype",
        ]
        rows.extend(f"{locus['rsid']}\t{locus['chrom']}\t{locus['pos']}\t{locus['bases']}" for locus in LOCUS_MODEL)
        return "\n".join(rows) + "\n"

    def _assert_clinvar_payloads_are_real_alleles(self, matches_path: Path, *, expected_format: str) -> None:
        payloads = [json.loads(line) for line in matches_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(payloads), EXPECTED_CLINVAR_MATCHED_ALLELES)
        for payload in payloads:
            sample = payload["sample_variant"]
            clinvar = payload["clinvar"]
            provenance_source = payload["match_provenance"]["source_record"]
            genotype = str(sample["genotype"] or "")
            self.assertIn("source_record_info", sample)
            self.assertEqual(provenance_source["info"], sample["source_record_info"])
            if "/" not in genotype and "|" not in genotype:
                self.assertIn(clinvar["alt"], genotype)
            if expected_format in {"vcf", "gvcf", "bam", "fastq"}:
                self.assertEqual(sample["ref"], clinvar["ref"])
                self.assertEqual(sample["alt"], clinvar["alt"])
                self.assertEqual(payload["match_basis"], "exact_allele")
                self.assertEqual(sample["source_record_ref"], sample["ref"])
                self.assertEqual(sample["source_record_alt"], sample["alt"])
                self.assertEqual(sample["record_kind"], "variant_call")
                self.assertEqual(provenance_source["record_kind"], "variant_call")
            else:
                self.assertEqual(payload["match_basis"], "consumer_array_allele_inference")
                self.assertEqual(payload["match_kind"], "consumer_array_allele_inference")
                self.assertEqual(payload["source_format"], expected_format)
                self.assertEqual(sample["source_format"], expected_format)
                self.assertEqual(provenance_source["source_format"], expected_format)
                self.assertEqual(sample["record_kind"], "array_call")
                self.assertEqual(sample["ref"], ".")
                self.assertEqual(sample["alt"], ".")
                self.assertEqual(sample["observed_alleles"], list(genotype))
                self.assertEqual(sample["source_record_ref"], ".")
                self.assertEqual(sample["source_record_alt"], ".")
                self.assertEqual(sample["source_record_format"], "GT_ARRAY")
                self.assertEqual(
                    payload["match_provenance"]["inferred_clinvar_allele"],
                    {
                        "chrom": clinvar["chrom"],
                        "pos": clinvar["pos"],
                        "ref": clinvar["ref"],
                        "alt": clinvar["alt"],
                    },
                )
                self.assertEqual(provenance_source["ref"], ".")
                self.assertEqual(provenance_source["alt"], ".")
                self.assertEqual(provenance_source["genotype"], genotype)
                self.assertEqual(provenance_source["record_kind"], "array_call")
                self.assertEqual(provenance_source["observed_alleles"], list(genotype))

    def _tiny_prs_thresholds(self):
        return mock.patch.multiple(
            prs_scorer,
            MIN_SCORE_VARIANTS=1,
            MIN_OVERLAP_FRACTION=0.10,
            MODERATE_OVERLAP_FRACTION=0.50,
            HIGH_OVERLAP_FRACTION=0.90,
        )
