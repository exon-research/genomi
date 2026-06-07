from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceFixtureSpec:
    case_id: str
    expected_format: str
    writer_method: str


SOURCE_FIXTURE_INVENTORY = (
    SourceFixtureSpec("vcf", "vcf", "_write_vcf_source"),
    SourceFixtureSpec("vcf_gz", "vcf", "_write_vcf_gzip_source"),
    SourceFixtureSpec("vcf_bz2", "vcf", "_write_vcf_bzip2_source"),
    SourceFixtureSpec("vcf_xz", "vcf", "_write_vcf_xz_source"),
    SourceFixtureSpec("vcf_zip", "vcf", "_write_vcf_zip_source"),
    SourceFixtureSpec("vcf_tar", "vcf", "_write_vcf_tar_source"),
    SourceFixtureSpec("gvcf", "gvcf", "_write_gvcf_source"),
    SourceFixtureSpec("gvcf_gz", "gvcf", "_write_gvcf_gzip_source"),
    SourceFixtureSpec("gvcf_bz2", "gvcf", "_write_gvcf_bzip2_source"),
    SourceFixtureSpec("gvcf_xz", "gvcf", "_write_gvcf_xz_source"),
    SourceFixtureSpec("gvcf_zip", "gvcf", "_write_gvcf_zip_source"),
    SourceFixtureSpec("gvcf_tar", "gvcf", "_write_gvcf_tar_source"),
    SourceFixtureSpec("23andme_txt", "23andme", "_write_23andme_text_source"),
    SourceFixtureSpec("23andme_gz", "23andme", "_write_23andme_gzip_source"),
    SourceFixtureSpec("23andme_bz2", "23andme", "_write_23andme_bzip2_source"),
    SourceFixtureSpec("23andme_xz", "23andme", "_write_23andme_xz_source"),
    SourceFixtureSpec("23andme_zip", "23andme", "_write_23andme_zip_source"),
    SourceFixtureSpec("23andme_tar", "23andme", "_write_23andme_tar_source"),
    SourceFixtureSpec("genome", "genome", "_write_genome_bundle_source"),
    SourceFixtureSpec("genome_tar_gz", "genome", "_write_genome_tar_source"),
    SourceFixtureSpec("genome_root_tar_gz", "genome", "_write_genome_root_tar_source"),
    SourceFixtureSpec("ancestrydna_txt", "ancestrydna", "_write_ancestry_text_source"),
    SourceFixtureSpec("ancestrydna_gz", "ancestrydna", "_write_ancestry_gzip_source"),
    SourceFixtureSpec("ancestrydna_bz2", "ancestrydna", "_write_ancestry_bzip2_source"),
    SourceFixtureSpec("ancestrydna_xz", "ancestrydna", "_write_ancestry_xz_source"),
    SourceFixtureSpec("ancestrydna_zip", "ancestrydna", "_write_ancestry_zip_source"),
    SourceFixtureSpec("ancestrydna_tar", "ancestrydna", "_write_ancestry_tar_source"),
    SourceFixtureSpec("myheritage_csv", "myheritage", "_write_myheritage_csv_source"),
    SourceFixtureSpec("myheritage_gz", "myheritage", "_write_myheritage_gzip_source"),
    SourceFixtureSpec("myheritage_bz2", "myheritage", "_write_myheritage_bzip2_source"),
    SourceFixtureSpec("myheritage_xz", "myheritage", "_write_myheritage_xz_source"),
    SourceFixtureSpec("myheritage_zip", "myheritage", "_write_myheritage_zip_source"),
    SourceFixtureSpec("myheritage_tar", "myheritage", "_write_myheritage_tar_source"),
    SourceFixtureSpec("ftdna_csv", "ftdna", "_write_ftdna_csv_source"),
    SourceFixtureSpec("ftdna_csv_gz", "ftdna", "_write_ftdna_gzip_source"),
    SourceFixtureSpec("ftdna_bz2", "ftdna", "_write_ftdna_bzip2_source"),
    SourceFixtureSpec("ftdna_xz", "ftdna", "_write_ftdna_xz_source"),
    SourceFixtureSpec("ftdna_zip", "ftdna", "_write_ftdna_zip_source"),
    SourceFixtureSpec("ftdna_tar", "ftdna", "_write_ftdna_tar_source"),
    SourceFixtureSpec("livingdna_txt", "livingdna", "_write_livingdna_text_source"),
    SourceFixtureSpec("livingdna_gz", "livingdna", "_write_livingdna_gzip_source"),
    SourceFixtureSpec("livingdna_bz2", "livingdna", "_write_livingdna_bzip2_source"),
    SourceFixtureSpec("livingdna_xz", "livingdna", "_write_livingdna_xz_source"),
    SourceFixtureSpec("livingdna_zip", "livingdna", "_write_livingdna_zip_source"),
    SourceFixtureSpec("livingdna_tar", "livingdna", "_write_livingdna_tar_source"),
)

SEQUENCING_SOURCE_FIXTURE_FORMATS = {
    "bam": "bam",
    "bam_zip": "bam",
    "bam_tar": "bam",
    "fastq_pair": "fastq",
    "fastq": "fastq",
    "fastq_zip": "fastq",
    "fastq_tar": "fastq",
}
