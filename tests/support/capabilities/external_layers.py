from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from genomi.evidence import (
    init_evidence_db,
)
from genomi.runtime.sqlite_support import connect_sqlite

DATA_DIR = Path(__file__).parents[2] / "data"
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
    with connect_sqlite(db) as connection:
        connection.execute(
            """
            insert or replace into genotype_support (
                agi_path, chrom, pos, ref, alt, genome_build, support_status,
                evidence_class, genotype, zygosity, depth, genotype_quality,
                filter, raw_json, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "test.active-genome-index.sqlite",
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
