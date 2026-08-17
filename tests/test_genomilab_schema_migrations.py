from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from genomi.lab.store import GenomiLabStore
from genomi.runtime import context as runtime_context
from tests.genomilab_support import TEST_LAB_KEY_PROVIDER


_LEGACY_TABLES = (
    "harness_bindings",
    "harness_commands",
    "harness_jobs",
    "harness_events",
)

_LEGACY_SCHEMA_SQL = """
CREATE TABLE harness_bindings (
    binding_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    command_id TEXT NOT NULL UNIQUE,
    host_id TEXT NOT NULL,
    task_id TEXT,
    run_id TEXT,
    binding_state TEXT NOT NULL,
    harness_status TEXT NOT NULL,
    harness_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE harness_commands (
    command_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    workspace_session_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES workspaces(user_id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    command_fingerprint TEXT NOT NULL,
    command_state TEXT NOT NULL,
    disclosure_receipt_id TEXT REFERENCES outbound_disclosure_receipts(disclosure_receipt_id),
    response_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE harness_jobs (
    job_id TEXT PRIMARY KEY,
    command_id TEXT NOT NULL UNIQUE REFERENCES harness_commands(command_id) ON DELETE CASCADE,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES workspaces(user_id) ON DELETE CASCADE,
    host_id TEXT NOT NULL,
    task_id TEXT,
    run_id TEXT,
    job_state TEXT NOT NULL,
    terminal_response_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE harness_events (
    event_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
    binding_id TEXT NOT NULL REFERENCES harness_bindings(binding_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(investigation_id, sequence)
);
CREATE INDEX idx_harness_events_investigation_sequence
    ON harness_events(investigation_id, sequence);
CREATE INDEX idx_harness_commands_investigation_created
    ON harness_commands(investigation_id, created_at);
CREATE INDEX idx_harness_jobs_investigation_created
    ON harness_jobs(investigation_id, created_at);
CREATE UNIQUE INDEX idx_harness_bindings_one_active
    ON harness_bindings(investigation_id) WHERE binding_state = 'active';
CREATE INDEX idx_custom_legacy_event_type ON harness_events(event_type);
"""


class GenomiLabSchemaMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store_path = Path(temporary.name) / "genomilab.sqlite3"
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(Path(temporary.name) / "genomi-home"),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "genomilab-schema-migration-tests",
                "GENOMI_MCP_BACKGROUND": "0",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)
        self.store = GenomiLabStore(
            self.store_path, key_provider=TEST_LAB_KEY_PROVIDER
        )
        self.store.open_workspace("migration-user", "Migration Patient")
        investigation = self.store.create_investigation(
            "migration-user",
            question="What did the prior investigation observe?",
        )
        self.investigation_id = str(investigation["investigation_id"])

    def test_reopen_adds_round_schema_without_inventing_legacy_rounds(self) -> None:
        reopened = self._reopen()
        with reopened._connect() as connection:
            objects = {
                (str(row["type"]), str(row["name"]))
                for row in connection.execute(
                    "SELECT type, name FROM sqlite_schema WHERE name IN ("
                    "'investigation_rounds', 'specialist_round_assignments', "
                    "'specialist_round_reports', 'investigation_rounds_immutable', "
                    "'specialist_round_reports_immutable')"
                ).fetchall()
            }
        self.assertEqual(
            objects,
            {
                ("table", "investigation_rounds"),
                ("table", "specialist_round_assignments"),
                ("table", "specialist_round_reports"),
                ("trigger", "investigation_rounds_immutable"),
                ("trigger", "specialist_round_reports_immutable"),
            },
        )
        investigation = reopened.get_investigation(self.investigation_id)
        self.assertEqual(investigation["rounds"], [])
        self.assertIsNone(investigation["current_round"])

    def test_reopen_translates_safe_monitoring_history_and_removes_transport_store(
        self,
    ) -> None:
        self._seed_legacy_transport(
            drop_current_events=True,
            events=[
                (
                    "legacy-event-progress",
                    "agent_progress",
                    self._legacy_event_payload(
                        event_id="legacy-event-progress",
                        kind="agent_progress",
                        status="running",
                        cursor=1,
                        details={
                            "agent_id": "agent-reviewer",
                            "assigned_step_id": "step-evidence",
                            "progress": "Reviewed the prior source-linked evidence.",
                        },
                    ),
                    "2026-08-10T12:00:00+00:00",
                ),
                (
                    "legacy-event-source",
                    "source_unavailable",
                    self._legacy_event_payload(
                        event_id="legacy-event-source",
                        kind="source_unavailable",
                        status="unavailable",
                        cursor=2,
                        details={
                            "source_family": "synthetic_literature",
                            "message": "The prior source could not be reached.",
                        },
                    ),
                    "2026-08-10T12:01:00+00:00",
                ),
            ],
        )

        reopened = self._reopen()
        events = reopened.replay_investigation_events(self.investigation_id)

        self.assertEqual(
            [(event["sequence"], event["event_type"]) for event in events],
            [(1, "source_unavailable")],
        )
        self.assertEqual(
            events[0]["payload"],
            {
                "source_family": "synthetic_literature",
                "status": "unavailable",
                "history_origin": "legacy_embedded_harness",
            },
        )
        self.assertEqual(
            reopened.get_investigation(self.investigation_id)[
                "investigation_events"
            ],
            events,
        )
        self._assert_current_transport_schema(reopened)

    def test_reopen_projects_nested_legacy_payload_through_typed_allowlist(
        self,
    ) -> None:
        self._seed_legacy_transport(
            drop_current_events=True,
            events=[
                (
                    "legacy-event-nested-transport",
                    "agent_progress",
                    self._legacy_event_payload(
                        event_id="legacy-event-nested-transport",
                        kind="agent_progress",
                        status="raw host status sentinel",
                        cursor=1,
                        details={
                            "source_family": "synthetic_literature",
                            "task_id": "nested-native-task",
                            "run_id": "nested-native-run",
                            "message": "raw host transport message",
                            "nested": {
                                "task_id": "deep-native-task",
                                "message": "deep raw host transport message",
                            },
                        },
                    ),
                    "2026-08-10T12:00:00+00:00",
                )
            ],
        )

        reopened = self._reopen()

        self.assertEqual(
            reopened.replay_investigation_events(self.investigation_id)[0][
                "payload"
            ],
            {
                "source_family": "synthetic_literature",
                "history_origin": "legacy_embedded_harness",
            },
        )
        self._assert_current_transport_schema(reopened)

    def test_reopen_keeps_current_domain_history_and_migrates_only_safe_events(
        self,
    ) -> None:
        current = self.store.append_investigation_event(
            self.investigation_id,
            event_type="investigation_created",
            payload={"question": "What did the prior investigation observe?"},
        )
        self._seed_legacy_transport(
            drop_current_events=False,
            events=[
                (
                    "legacy-event-brief",
                    "brief_completed",
                    self._legacy_event_payload(
                        event_id="legacy-event-brief",
                        kind="brief_completed",
                        status="completed",
                        cursor=1,
                        details={"artifact_kind": "brief_draft"},
                    ),
                    "2026-08-10T12:02:00+00:00",
                ),
                (
                    "legacy-event-unsafe",
                    "agent_progress",
                    self._legacy_event_payload(
                        event_id="legacy-event-unsafe",
                        kind="agent_progress",
                        status="running",
                        cursor=2,
                        details={"genome_path": "/private/patient.vcf"},
                    ),
                    "2026-08-10T12:03:00+00:00",
                ),
                (
                    "legacy-event-token",
                    "token_delta",
                    self._legacy_event_payload(
                        event_id="legacy-event-token",
                        kind="token_delta",
                        status="running",
                        cursor=3,
                        details={"text": "uncommitted model output"},
                    ),
                    "2026-08-10T12:04:00+00:00",
                ),
            ],
        )

        reopened = self._reopen()
        events = reopened.replay_investigation_events(self.investigation_id)

        self.assertEqual(events[0], current)
        self.assertEqual(
            [(event["sequence"], event["event_type"]) for event in events],
            [(1, "investigation_created"), (2, "brief_completed")],
        )
        self.assertEqual(
            events[1]["payload"],
            {
                "artifact_kind": "brief_draft",
                "status": "completed",
                "history_origin": "legacy_embedded_harness",
            },
        )
        self._assert_current_transport_schema(reopened)

    def _seed_legacy_transport(
        self,
        *,
        drop_current_events: bool,
        events: list[tuple[str, str, dict[str, Any], str]],
    ) -> None:
        with self.store._connect() as connection:
            if drop_current_events:
                connection.execute("DROP TABLE investigation_events")
            connection.executescript(_LEGACY_SCHEMA_SQL)
            connection.execute(
                "INSERT INTO harness_commands("
                "command_id, investigation_id, workspace_session_id, user_id, "
                "operation, command_fingerprint, command_state, response_json, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "legacy-command",
                    self.investigation_id,
                    "legacy-session",
                    "migration-user",
                    "start_task_run",
                    "legacy-command-fingerprint",
                    "completed",
                    json.dumps({"sensitive_legacy_response": "must be removed"}),
                    "2026-08-10T11:59:00+00:00",
                    "2026-08-10T12:05:00+00:00",
                ),
            )
            connection.execute(
                "INSERT INTO harness_bindings("
                "binding_id, investigation_id, command_id, host_id, task_id, "
                "run_id, binding_state, harness_status, harness_revision, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "legacy-binding",
                    self.investigation_id,
                    "legacy-command",
                    "legacy-codex-adapter",
                    "legacy-task",
                    "legacy-run",
                    "active",
                    "completed",
                    1,
                    "2026-08-10T11:59:00+00:00",
                    "2026-08-10T12:05:00+00:00",
                ),
            )
            connection.execute(
                "INSERT INTO harness_jobs("
                "job_id, command_id, investigation_id, user_id, host_id, "
                "task_id, run_id, job_state, terminal_response_json, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "legacy-job",
                    "legacy-command",
                    self.investigation_id,
                    "migration-user",
                    "legacy-codex-adapter",
                    "legacy-task",
                    "legacy-run",
                    "completed",
                    json.dumps({"sensitive_terminal_response": "must be removed"}),
                    "2026-08-10T11:59:00+00:00",
                    "2026-08-10T12:05:00+00:00",
                ),
            )
            for sequence, (event_id, event_type, payload, created_at) in enumerate(
                events, start=1
            ):
                connection.execute(
                    "INSERT INTO harness_events("
                    "event_id, investigation_id, binding_id, sequence, event_type, "
                    "payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        self.investigation_id,
                        "legacy-binding",
                        sequence,
                        event_type,
                        json.dumps(payload),
                        created_at,
                    ),
                )

    def _legacy_event_payload(
        self,
        *,
        event_id: str,
        kind: str,
        status: str,
        cursor: int,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "protocol_version": "genomilab.harness.v1",
            "event_id": event_id,
            "kind": kind,
            "workspace_session_id": "legacy-session",
            "host_id": "legacy-codex-adapter",
            "task_id": "legacy-task",
            "run_id": "legacy-run",
            "investigation_id": self.investigation_id,
            "user_id": "migration-user",
            "cursor": cursor,
            "correlation_id": "legacy-command",
            "status": status,
            "timestamp": f"2026-08-10T12:0{cursor}:00+00:00",
            "payload": details,
            "proposed_artifacts": [],
            "job_id": "legacy-job",
        }

    def _reopen(self) -> GenomiLabStore:
        return GenomiLabStore(
            self.store_path, key_provider=TEST_LAB_KEY_PROVIDER
        )

    def _assert_current_transport_schema(self, store: GenomiLabStore) -> None:
        with store._connect() as connection:
            legacy_objects = connection.execute(
                "SELECT type, name, tbl_name FROM sqlite_schema "
                f"WHERE tbl_name IN ({','.join('?' for _ in _LEGACY_TABLES)}) "
                "OR name LIKE 'idx_harness_%' "
                "OR name = 'idx_custom_legacy_event_type' "
                "ORDER BY type, name",
                _LEGACY_TABLES,
            ).fetchall()
            current_table = connection.execute(
                "SELECT name FROM sqlite_schema "
                "WHERE type = 'table' AND name = 'investigation_events'"
            ).fetchone()
        self.assertEqual(
            [(row["type"], row["name"], row["tbl_name"]) for row in legacy_objects],
            [],
        )
        self.assertEqual(str(current_table["name"]), "investigation_events")


if __name__ == "__main__":
    unittest.main()
