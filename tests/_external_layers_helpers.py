from __future__ import annotations

import gzip
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from genomi.active_genome_index.alignment import (
    build_bam_variant_call_commands,
    infer_genome_build_from_bam_header,
)
from genomi.active_genome_index.active_genome_index import create_active_genome_index
from genomi.active_genome_index.normalize import (
    build_bcftools_norm_command,
    normalize_vcf,
)
from genomi.capabilities.clinvar.static_annotation import (
    _reusable_static_db_with_clinvar,
    build_static_annotation,
    default_static_outputs,
    fetch_static_population,
    match_static_clinvar,
    run_static_callability,
    run_static_genotype_support,
    run_static_sample_qc,
)
from genomi.capabilities.clinvar.static_annotation import (
    workflow_contract as static_contract,
)
from genomi.capabilities.research.intent_research import (
    query_reviewed_research,
    record_reviewed_research,
)
from genomi.capabilities.research.intent_research import (
    workflow_contract as research_contract,
)
from genomi.capabilities.variant.annotation import (
    annotate_vcf,
    build_vep_command,
    build_vep_docker_command,
)
from genomi.evidence import (
    SQLITE_BUSY_TIMEOUT_SECONDS,
    _gnomad_population_batch,
    build_clinvar_annotation_index,
    build_clinvar_gene_index,
    build_clinvar_rsid_annotation_index,
    build_clinvar_rsid_index,
    connect_evidence,
    evidence_summary,
    extract_clinvar_candidates,
    fetch_gene_evidence,
    gather_variant_evidence,
    import_clinvar_vcf,
    import_population_vcf,
    init_evidence_db,
    match_clinvar_variants,
    match_clinvar_variants_from_active_genome_index,
    query_clinvar,
    query_population_frequency,
    query_research_findings,
    record_research_findings,
    search_research_findings,
    summarize_clinvar_matches,
)
from genomi.evidence.investigation import prepare_investigation_packet
from genomi.evidence.sources import evidence_source_catalog
from genomi.runtime.external import dependency_report
from genomi.runtime.static_dependencies import (
    ensure_reference_fasta,
    infer_genome_build_from_vcf,
    resolve_genome_build,
)

DATA_DIR = Path(__file__).parent / "data"
TINY_VCF = DATA_DIR / "tiny.gvcf.vcf"
TINY_FASTA = DATA_DIR / "tiny.fa"
TINY_CLINVAR = DATA_DIR / "tiny.clinvar.vcf"
TINY_POPULATION = DATA_DIR / "tiny.population.vcf"
TINY_NORMALIZE_VCF = DATA_DIR / "tiny.normalize.vcf"
TINY_NORMALIZE_FASTA = DATA_DIR / "tiny.normalize.fa"


def _insert_genotype_support(
    db: Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    status: str = "supported",
    genotype: str = "0/1",
    depth: int = 50,
    genotype_quality: int = 99,
    filter_value: str = "PASS",
) -> None:
    init_evidence_db(db)
    evidence_class = {
        "supported": "genotype_support_supported",
        "weak": "genotype_support_weak",
        "unknown": "genotype_support_unknown",
        "no_call": "genotype_support_no_call",
        "not_observed": "genotype_support_not_observed",
    }.get(status, "genotype_support_unknown")
    accepted = ["sample_observation", "genotype_support_supported"] if status == "supported" else []
    raw = {
        "support_status": status,
        "evidence_class": evidence_class,
        "accepted_report_evidence_classes": accepted,
        "sample_observation": {
            "genotype": genotype,
            "zygosity": "heterozygous",
            "depth": depth,
            "genotype_quality": genotype_quality,
            "filter": filter_value,
            "limitation": "test stored genotype-support row",
        },
        "evidence_boundaries": {
            "component": "sample_genotype_support",
            "support_status": status,
            "evidence_boundaries": ["test boundary"],
        },
    }
    with sqlite3.connect(db) as connection:
        connection.execute(
            """
            insert or replace into genotype_support (
                vcf_path, chrom, pos, ref, alt, genome_build, support_status,
                evidence_class, genotype, zygosity, depth, genotype_quality,
                filter, raw_json, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "test.vcf",
                chrom,
                pos,
                ref,
                alt,
                "GRCh38",
                status,
                evidence_class,
                genotype,
                "heterozygous",
                depth,
                genotype_quality,
                filter_value,
                json.dumps(raw, sort_keys=True),
                "2026-05-08T00:00:00+00:00",
            ),
        )
        connection.commit()


class EvidenceImportTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._genomi_home_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._genomi_home_tmp.cleanup)
        self._genomi_home_env = patch.dict(os.environ, {"GENOMI_HOME": str(Path(self._genomi_home_tmp.name) / "genomi-home")})
        self._genomi_home_env.start()
        self.addCleanup(self._genomi_home_env.stop)
