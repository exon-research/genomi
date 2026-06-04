from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from genomi.evidence import (
    evidence_summary,
    init_evidence_db,
    query_genotype_support,
    query_region_callability_for_locus,
    query_sample_qc,
)


class EvidenceDbCurrentContractTests(unittest.TestCase):
    def test_init_evidence_db_enforces_current_private_sample_context_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            _write_noncurrent_private_tables(db)

            init_evidence_db(db)
            summary = evidence_summary(db)
            support = query_genotype_support(db, "1", 100, "A", "G", genome_build="GRCh37")
            sample_qc = query_sample_qc(db, genome_build="GRCh37")
            callability = query_region_callability_for_locus(db, "1", 100, genome_build="GRCh37")

            self.assertEqual(summary["tables"]["sample_qc"], 0)
            self.assertEqual(summary["tables"]["genotype_support"], 0)
            self.assertEqual(summary["tables"]["region_callability"], 0)
            self.assertEqual(support["count"], 0)
            self.assertEqual(sample_qc["count"], 0)
            self.assertEqual(callability["count"], 0)


def _write_noncurrent_private_tables(db: Path) -> None:
    with sqlite3.connect(db) as connection:
        connection.executescript(
            """
            create table sample_qc (
                sample_id text not null,
                temporary_path text not null,
                genome_build text not null,
                created_at text not null
            );
            insert into sample_qc values ('sample', 'temporary.active-genome-index.sqlite', 'GRCh37', '2026-06-04T00:00:00Z');

            create table genotype_support (
                temporary_path text not null,
                chrom text not null,
                pos integer not null,
                ref text not null,
                alt text not null,
                genome_build text not null,
                support_status text not null,
                raw_json text not null,
                created_at text not null
            );
            insert into genotype_support values (
                'temporary.active-genome-index.sqlite', '1', 100, 'A', 'G',
                'GRCh37', 'supported', '{}', '2026-06-04T00:00:00Z'
            );

            create table region_callability (
                temporary_path text not null,
                region text not null,
                chrom text not null,
                start integer not null,
                end integer not null,
                genome_build text not null,
                created_at text not null
            );
            insert into region_callability values (
                'temporary.active-genome-index.sqlite', '1:100-100', '1',
                100, 100, 'GRCh37', '2026-06-04T00:00:00Z'
            );
            """
        )

if __name__ == "__main__":
    unittest.main()
