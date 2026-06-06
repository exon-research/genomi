from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from genomi.capabilities.clinvar.static_annotation import (
    fetch_static_population,
)
from genomi.evidence import (
    _gnomad_population_batch,
    init_evidence_db,
    query_population_frequency,
)
from genomi.operations import call_operation
from genomi.runtime.sqlite_support import connect_sqlite
from tests.support.capabilities.external_layers import (
    EvidenceImportTestBase,
)


class PopulationFrequencyTests(EvidenceImportTestBase):
    def test_gnomad_population_batch_calculates_population_af(self) -> None:
        variant = {
            "variant_id": "1-10250-A-C",
            "rsids": ["rs1"],
            "chrom": "1",
            "pos": 10250,
            "ref": "A",
            "alt": "C",
            "exome": {
                "ac": 10,
                "an": 100,
                "af": 0.1,
                "homozygote_count": 1,
                "populations": [
                    {"id": "nfe", "ac": 2, "an": 50, "homozygote_count": 0},
                ],
            },
            "genome": None,
        }

        batch = _gnomad_population_batch(
            variant,
            dataset="gnomad_r4",
            genome_build="GRCh38",
            api_url="https://example.test/api",
            imported_at="2026-01-01T00:00:00+00:00",
        )

        self.assertEqual(len(batch), 2)
        self.assertEqual(batch[0][5], "gnomad_r4_exome")
        self.assertEqual(batch[0][7], "global")
        self.assertEqual(batch[0][10], 0.1)
        self.assertEqual(batch[1][7], "nfe")
        self.assertEqual(batch[1][10], 0.04)

    def test_fetch_population_writes_directly_to_shared_for_linked_run_db(self) -> None:
        variant = {
            "variant_id": "1-10250-A-C",
            "rsids": ["rs1"],
            "chrom": "1",
            "pos": 10250,
            "ref": "A",
            "alt": "C",
            "exome": {
                "ac": 10,
                "an": 100,
                "af": 0.1,
                "homozygote_count": 1,
                "populations": [
                    {"id": "nfe", "ac": 2, "an": 50, "homozygote_count": 0},
                ],
            },
            "genome": None,
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_db = tmp_path / "run.sqlite"
            shared_db = tmp_path / "shared.sqlite"
            init_evidence_db(run_db)
            with connect_sqlite(run_db) as connection:
                for key in ("source_evidence_db", "shared_evidence_db"):
                    connection.execute(
                        """
                        insert into metadata(key, value) values(?, ?)
                        on conflict(key) do update set value = excluded.value
                        """,
                        (key, json.dumps(str(shared_db))),
                    )
                connection.commit()

            with patch("genomi.evidence._post_graphql", return_value={"data": {"variant": variant}}):
                result = fetch_static_population(
                    run_db,
                    "1",
                    10250,
                    "A",
                    "C",
                    shared_evidence_db=shared_db,
                    sync_shared=True,
                )

            self.assertEqual(result["public_write_db"], str(shared_db))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["record_count"], 2)
            self.assertEqual(result["shared_sync"]["status"], "direct_shared_write")
            with connect_sqlite(run_db) as connection:
                local_rows = connection.execute("select count(*) from population_frequencies").fetchone()[0]
            with connect_sqlite(shared_db) as connection:
                shared_rows = connection.execute("select count(*) from population_frequencies").fetchone()[0]
            self.assertEqual(local_rows, 0)
            self.assertEqual(shared_rows, 2)
            visible = query_population_frequency(run_db, "1", 10250, "A", "C")
            self.assertEqual(visible["count"], 2)

    def test_population_fetch_operation_envelope_tracks_records(self) -> None:
        variant = {
            "variant_id": "1-10250-A-C",
            "rsids": ["rs1"],
            "chrom": "1",
            "pos": 10250,
            "ref": "A",
            "alt": "C",
            "exome": {
                "ac": 10,
                "an": 100,
                "af": 0.1,
                "homozygote_count": 1,
                "populations": [
                    {"id": "nfe", "ac": 2, "an": 50, "homozygote_count": 0},
                ],
            },
            "genome": None,
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_db = tmp_path / "run.sqlite"
            shared_db = tmp_path / "shared.sqlite"
            init_evidence_db(run_db)

            with patch("genomi.evidence._post_graphql", return_value={"data": {"variant": variant}}) as post:
                fetched = call_operation(
                    "gnomad.fetch_population_frequency",
                    {
                        "db": str(run_db),
                        "shared_db": str(shared_db),
                        "chrom": "1",
                        "pos": 10250,
                        "ref": "A",
                        "alt": "C",
                    },
                )

            self.assertEqual(fetched["status"], "completed")
            self.assertEqual(fetched["summary"]["record_count"], 2)
            self.assertEqual(fetched["population_frequency"]["count"], 2)
            self.assertEqual(fetched["evidence_envelope"]["finding_state"], "evidence_present")
            self.assertEqual(post.call_count, 1)

            with patch("genomi.evidence._post_graphql", side_effect=AssertionError("cached fetch should not call gnomAD")):
                cached = call_operation(
                    "gnomad.fetch_population_frequency",
                    {
                        "db": str(run_db),
                        "shared_db": str(shared_db),
                        "chrom": "1",
                        "pos": 10250,
                        "ref": "A",
                        "alt": "C",
                    },
                )

            self.assertEqual(cached["status"], "cached")
            self.assertEqual(cached["summary"]["record_count"], 2)
            self.assertEqual(cached["evidence_envelope"]["finding_state"], "evidence_present")

    def test_population_fetch_operation_envelope_tracks_empty_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_db = tmp_path / "run.sqlite"
            shared_db = tmp_path / "shared.sqlite"
            init_evidence_db(run_db)

            with patch("genomi.evidence._post_graphql", return_value={"data": {"variant": None}}):
                result = call_operation(
                    "gnomad.fetch_population_frequency",
                    {
                        "db": str(run_db),
                        "shared_db": str(shared_db),
                        "chrom": "1",
                        "pos": 10250,
                        "ref": "A",
                        "alt": "C",
                    },
                )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["record_count"], 0)
            self.assertFalse(result["found"])
            self.assertEqual(result["population_frequency"]["count"], 0)
            self.assertEqual(result["evidence_envelope"]["finding_state"], "not_observed_in_consulted_scope")

    def test_fetch_population_returns_structured_status_when_gnomad_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_db = tmp_path / "run.sqlite"
            shared_db = tmp_path / "shared.sqlite"
            init_evidence_db(run_db)

            with patch("genomi.evidence._post_graphql", side_effect=RuntimeError("gnomAD API request failed: offline")):
                result = fetch_static_population(
                    run_db,
                    "1",
                    10250,
                    "A",
                    "C",
                    shared_evidence_db=shared_db,
                    sync_shared=True,
                )

            self.assertEqual(result["status"], "source_unavailable")
            self.assertEqual(result["summary"]["record_count"], 0)
            self.assertEqual(result["inserted_rows"], 0)
            self.assertEqual(result["population_frequency"]["count"], 0)
            self.assertIn("offline", result["error"])
            self.assertEqual(result["shared_sync"]["status"], "direct_shared_write")

    def test_population_fetch_operation_envelope_tracks_source_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_db = tmp_path / "run.sqlite"
            shared_db = tmp_path / "shared.sqlite"
            init_evidence_db(run_db)

            with patch("genomi.evidence._post_graphql", side_effect=RuntimeError("gnomAD API request failed: offline")):
                result = call_operation(
                    "gnomad.fetch_population_frequency",
                    {
                        "db": str(run_db),
                        "shared_db": str(shared_db),
                        "chrom": "1",
                        "pos": 10250,
                        "ref": "A",
                        "alt": "C",
                    },
                )

            self.assertEqual(result["status"], "source_unavailable")
            self.assertEqual(result["summary"]["record_count"], 0)
            self.assertEqual(result["population_frequency"]["count"], 0)
            self.assertEqual(result["evidence_envelope"]["finding_state"], "not_assessed")


if __name__ == "__main__":
    unittest.main()
