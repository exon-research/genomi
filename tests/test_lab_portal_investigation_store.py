from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager

from genomi.lab.portal_investigation_store import PortalInvestigationStoreMixin


class _Store(PortalInvestigationStoreMixin):
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE evidence_records (
                evidence_record_id TEXT,
                investigation_id TEXT,
                source_family TEXT,
                operation TEXT,
                evidence_json TEXT,
                created_at TEXT
            );
            CREATE TABLE research_artifacts (
                research_artifact_id TEXT,
                investigation_id TEXT,
                artifact_kind TEXT,
                artifact_json TEXT,
                created_at TEXT
            );
            """
        )
        self.include_history = None

    @contextmanager
    def _connect(self):
        yield self.connection

    def read_orchestrator_investigation(
        self, investigation_id: str, *, include_history: bool = False
    ) -> dict[str, object]:
        self.include_history = include_history
        return {
            "investigation": {"investigation_id": investigation_id},
            "specialist_assignments": [
                {"specialist_assignment_id": "assignment-a", "state": "completed"}
            ],
            "brief_versions": [
                {"version": 1, "brief": {"summary": "Persisted brief"}}
            ],
        }


class PortalInvestigationStoreTests(unittest.TestCase):
    def test_read_adds_ordered_canonical_evidence_and_research_artifacts(self) -> None:
        store = _Store()
        self.addCleanup(store.connection.close)
        store.connection.executemany(
            "INSERT INTO evidence_records VALUES (?, 'investigation-a', ?, ?, ?, ?)",
            [
                ("evidence-b", "literature", "search", '{"records":[]}', "2026-01-02"),
                ("evidence-a", "profile", "read", '{"records":[]}', "2026-01-01"),
            ],
        )
        store.connection.execute(
            "INSERT INTO research_artifacts VALUES "
            "('artifact-a', 'investigation-a', 'evidence_map', '{\"title\":\"Map\"}', '2026-01-03')"
        )

        view = store.read_portal_investigation(
            "investigation-a", include_history=True
        )

        self.assertTrue(store.include_history)
        self.assertEqual(
            [item["evidence_record_id"] for item in view["evidence_records"]],
            ["evidence-a", "evidence-b"],
        )
        self.assertEqual(view["evidence_records"][0]["evidence"], {"records": []})
        self.assertEqual(
            view["research_artifacts"][0]["artifact"], {"title": "Map"}
        )
        self.assertEqual(
            view["specialist_assignments"][0]["specialist_assignment_id"],
            "assignment-a",
        )
        self.assertEqual(view["brief_versions"][0]["version"], 1)


if __name__ == "__main__":
    unittest.main()
