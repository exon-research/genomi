from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from genomi.evidence.store import clinvar_import as clinvar_import_module
from genomi.capabilities.clinvar.static_annotation import (
    _reusable_static_db_with_clinvar,
)
from genomi.evidence import (
    SQLITE_BUSY_TIMEOUT_SECONDS,
    connect_evidence,
    evidence_summary,
    import_clinvar_vcf,
    init_evidence_db,
    query_clinvar,
)
from genomi.runtime.sqlite_support import connect_sqlite
from tests.support.capabilities.external_layers import (
    TINY_CLINVAR,
    EvidenceImportTestBase,
)


class ExternalEvidenceStoreTests(EvidenceImportTestBase):
    def test_clinvar_rsid_index_materialization_is_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            active_calls = 0
            max_active_calls = 0
            guard = threading.Lock()

            def slow_unlocked(evidence_db: str | Path, *, force: bool = False) -> dict:
                nonlocal active_calls, max_active_calls
                with guard:
                    active_calls += 1
                    max_active_calls = max(max_active_calls, active_calls)
                try:
                    time.sleep(0.05)
                    return {"status": "completed", "evidence_db": str(evidence_db), "force": force}
                finally:
                    with guard:
                        active_calls -= 1

            with mock.patch.object(clinvar_import_module, "_build_clinvar_rsid_index_unlocked", side_effect=slow_unlocked):
                errors: list[BaseException] = []

                def run_builder() -> None:
                    try:
                        clinvar_import_module.build_clinvar_rsid_index(db)
                    except BaseException as exc:
                        errors.append(exc)

                threads = [threading.Thread(target=run_builder), threading.Thread(target=run_builder)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

            self.assertEqual(errors, [])
            self.assertEqual(max_active_calls, 1)

    def test_evidence_connections_wait_for_parallel_shared_writers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            init_evidence_db(db)

            with connect_evidence(db) as connection:
                timeout = connection.execute("pragma busy_timeout").fetchone()[0]

            self.assertEqual(timeout, SQLITE_BUSY_TIMEOUT_SECONDS * 1000)

    def test_schema_ensure_creates_tables_and_prunes_obsolete_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            with connect_sqlite(db) as connection:
                connection.execute("create table metadata (key text primary key, value text not null)")
                connection.execute("insert into metadata(key, value) values('schema_version', ?)", (json.dumps(2),))

            summary = evidence_summary(db)

            self.assertEqual(summary["metadata"], {})
            self.assertIn("research_findings", summary["tables"])
            self.assertIn("sample_qc", summary["tables"])

    def test_schema_ensure_migrates_existing_research_target_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            with connect_sqlite(db) as connection:
                connection.execute("create table metadata (key text primary key, value text not null)")
                connection.execute(
                    """
                    create table research_findings (
                        finding_id text primary key,
                        target_type text not null,
                        target_id text not null,
                        chrom text,
                        pos integer,
                        ref text,
                        alt text,
                        gene text,
                        genome_build text,
                        source_title text not null,
                        source_url text not null,
                        source_type text,
                        source_published_at text,
                        source_accessed_at text not null,
                        searched_query text,
                        finding_text text not null,
                        finding_summary text,
                        finding_type text,
                        captured_by text not null,
                        captured_at text not null,
                        raw_json text not null
                    )
                    """
                )

            summary = evidence_summary(db)

            self.assertEqual(summary["tables"]["research_findings"], 0)
            with connect_sqlite(db) as connection:
                columns = {row[1] for row in connection.execute("pragma table_info(research_findings)")}
            self.assertIn("drug", columns)
            self.assertIn("condition", columns)
            self.assertIn("topic", columns)
            self.assertIn("research_scope", columns)

    def test_clinvar_import_and_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"

            init = init_evidence_db(db)
            self.assertEqual(init, {"evidence_db": str(db)})

            result = import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["scanned_records"], 2)
            self.assertEqual(result["inserted_alleles"], 3)

            cached = import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            self.assertEqual(cached["status"], "cached")
            self.assertEqual(cached["inserted_alleles"], 3)

            query = query_clinvar(db, "1", 10250, "A", "C")
            self.assertEqual(query["count"], 1)
            self.assertEqual(query["records"][0]["clinvar_id"], "12345")
            self.assertEqual(query["records"][0]["clinical_significance"], "Benign")

            split_query = query_clinvar(db, "1", 10257, "A", "G")
            self.assertEqual(split_query["count"], 1)
            self.assertEqual(split_query["records"][0]["clinical_significance"], "Uncertain_significance")

    def test_explicit_clinvar_import_is_preferred_over_existing_shared_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_db = Path(tmp) / "run.sqlite"
            shared_db = Path(tmp) / "shared.sqlite"
            import_clinvar_vcf(TINY_CLINVAR, run_db, source_version="run-fixture")
            import_clinvar_vcf(TINY_CLINVAR, shared_db, source_version="shared-fixture")

            selected = _reusable_static_db_with_clinvar(
                run_db,
                shared_db,
                "GRCh38",
                preferred_db=run_db,
            )

        self.assertEqual(selected, run_db)
