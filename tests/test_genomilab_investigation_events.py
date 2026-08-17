from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.lab.investigation_event_store import (
    INVESTIGATION_EVENT_PAYLOAD_MAX_BYTES,
)
from genomi.lab.store import GenomiLabStore
from genomi.runtime import context as runtime_context
from tests.genomilab_support import TEST_LAB_KEY_PROVIDER


class GenomiLabInvestigationEventStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self.genomi_home = Path(self._temporary_home.name) / "genomi-home"
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(self.genomi_home),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "genomilab-investigation-event-tests",
                "GENOMI_MCP_BACKGROUND": "0",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)
        self.store = GenomiLabStore(key_provider=TEST_LAB_KEY_PROVIDER)
        self.store.open_workspace("user-a", "Synthetic user A")
        investigation = self.store.create_investigation(
            "user-a", question="What explains this synthetic phenotype?"
        )
        self.investigation_id = str(investigation["investigation_id"])

    def test_events_are_server_identified_ordered_replayable_and_persistent(self) -> None:
        first = self.store.append_investigation_event(
            self.investigation_id,
            event_type="investigation_started",
            payload={"status": "running"},
        )
        second = self.store.append_investigation_event(
            self.investigation_id,
            event_type="hypothesis_revised",
            payload={"hypothesis_id": "hypothesis-2", "version": 2},
        )

        self.assertTrue(str(first["event_id"]).startswith("investigation-event-"))
        self.assertEqual([first["sequence"], second["sequence"]], [1, 2])
        self.assertEqual(first["payload"], {"status": "running"})
        self.assertEqual(
            self.store.replay_investigation_events(
                self.investigation_id, after_sequence=1
            ),
            [second],
        )

        reopened = GenomiLabStore(
            self.store.path, key_provider=TEST_LAB_KEY_PROVIDER
        )
        self.assertEqual(
            reopened.replay_investigation_events(self.investigation_id),
            [first, second],
        )
        self.assertEqual(
            reopened.get_investigation(self.investigation_id)[
                "investigation_events"
            ],
            [first, second],
        )
        self.assertIn(
            "idx_investigation_events_investigation_sequence",
            reopened.indexes_for("investigation_events"),
        )

    def test_events_are_scoped_to_their_investigation(self) -> None:
        other = self.store.create_investigation(
            "user-a", question="A second synthetic question"
        )
        self.store.append_investigation_event(
            self.investigation_id,
            event_type="investigation_started",
            payload={"ordinal": 1},
        )
        other_event = self.store.append_investigation_event(
            str(other["investigation_id"]),
            event_type="investigation_started",
            payload={"ordinal": 2},
        )

        self.assertEqual(
            self.store.replay_investigation_events(str(other["investigation_id"])),
            [other_event],
        )
        self.assertEqual(other_event["sequence"], 1)
        with self.assertRaises(KeyError):
            self.store.append_investigation_event(
                "investigation-missing",
                event_type="investigation_started",
                payload={},
            )
        with self.assertRaises(KeyError):
            self.store.replay_investigation_events("investigation-missing")

    def test_event_payload_rejects_private_non_json_and_oversized_content(self) -> None:
        invalid_payloads = (
            ["not", "an", "object"],
            {"genome_path": "/private/patient.vcf"},
            {"raw_sequence": "ACGT"},
            {"value": b"binary"},
            {"value": float("nan")},
            {1: "non-string key"},
        )
        for payload in invalid_payloads:
            with (
                self.subTest(payload=repr(payload)),
                self.assertRaises(ValueError),
            ):
                self.store.append_investigation_event(
                    self.investigation_id,
                    event_type="invalid_payload",
                    payload=payload,  # type: ignore[arg-type]
                )

        with self.assertRaisesRegex(ValueError, "too large"):
            self.store.append_investigation_event(
                self.investigation_id,
                event_type="oversized_payload",
                payload={"message": "x" * INVESTIGATION_EVENT_PAYLOAD_MAX_BYTES},
            )
        self.assertEqual(
            self.store.replay_investigation_events(self.investigation_id), []
        )

    def test_replay_cursor_is_a_non_negative_integer(self) -> None:
        for value in (-1, True, 1.5, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.replay_investigation_events(
                    self.investigation_id,
                    after_sequence=value,  # type: ignore[arg-type]
                )


if __name__ == "__main__":
    unittest.main()
