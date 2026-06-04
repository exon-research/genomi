from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "genomi"
AGI_ROOT = SRC_ROOT / "active_genome_index"


FORBIDDEN_AGI_READ_PATTERNS = {
    r"\bsqlite3\.connect\s*\(\s*agi_path": "read AGI SQLite through ActiveGenomeIndexReader",
    r"\bconnect_sqlite\s*\(\s*agi_path": "read AGI SQLite through ActiveGenomeIndexReader",
    r"\bconnect_readonly_sqlite\s*\(\s*agi_path": "read AGI SQLite through ActiveGenomeIndexReader",
    r"\breader\.connect\s*\(": "capabilities must expose narrow reader methods instead of opening reader connections",
    r"\bconnect_active_genome_index\s*\(\s*agi_path": "read AGI SQLite through ActiveGenomeIndexReader",
    r"\bconnect_active_genome_index_existing\s*\(\s*agi_path": "read AGI SQLite through ActiveGenomeIndexReader",
    r"\bconnect_existing_readonly\s*\(\s*agi_path": "read AGI SQLite through ActiveGenomeIndexReader",
    r"\bconnect_existing\s*\(\s*agi_path": "read AGI SQLite through ActiveGenomeIndexReader",
    r"\breader\.attach_to\s*\(": "stage AGI rows through an active-genome-index-owned helper",
    r"sample_active_genome_index\.": "do not query attached AGI aliases outside active_genome_index",
    r"\bquery_variant\s*\(\s*vcf\b": "call ActiveGenomeIndexReader.query_variant from capability code",
    r"\bquery_region\s*\(\s*vcf\b": "call ActiveGenomeIndexReader.query_region from capability code",
    r"\bquery_rsid_filtered\s*\(\s*vcf\b": "call ActiveGenomeIndexReader.query_rsid from capability code",
    r"\bcoverage_query\s*\(\s*vcf\b": "call ActiveGenomeIndexReader.coverage from capability code",
    r"attach database \? as sample_active_genome_index": "attach AGI databases through ActiveGenomeIndexReader.attach_to",
}


class ActiveGenomeIndexReaderBoundaryTests(unittest.TestCase):
    def test_production_agi_reads_are_routed_through_reader(self) -> None:
        violations: list[str] = []
        for path in sorted(SRC_ROOT.rglob("*.py")):
            if path.is_relative_to(AGI_ROOT):
                continue
            text = path.read_text(encoding="utf-8")
            for pattern, reason in FORBIDDEN_AGI_READ_PATTERNS.items():
                for match in re.finditer(pattern, text):
                    line = text.count("\n", 0, match.start()) + 1
                    rel = path.relative_to(REPO_ROOT)
                    violations.append(f"{rel}:{line}: {reason}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
