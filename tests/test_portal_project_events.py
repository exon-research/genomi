from __future__ import annotations

import re

from genomi.interfaces import portal_project_events, portal_store

from tests.support.runtime.genomi import GenomiRuntimeTestCase


_PRIVATE_PATH_RE = re.compile(r"(?:/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes|~)(?:/|$)")
_PRIVATE_KEYS = {"context_file", "registry_file", "agi_path", "dashboard_path", "shared_evidence_db", "path", "result"}


class PortalProjectEventTests(GenomiRuntimeTestCase):
    def test_project_event_emit_and_load_are_isolated_by_root(self) -> None:
        root_a = self.genomi_home / "root-a"
        root_b = self.genomi_home / "root-b"
        project_id = "proj_same_id"
        self.addCleanup(portal_project_events.discard_project_events, project_id, root=root_a)
        self.addCleanup(portal_project_events.discard_project_events, project_id, root=root_b)

        portal_project_events.emit_project_event(
            project_id,
            "messages_changed",
            {"frame_id": "frame_a", "reason": "assistant_stream", "note": "from /tmp/private-a.json"},
            root=root_a,
        )
        portal_project_events.emit_project_event(
            project_id,
            "messages_changed",
            {"frame_id": "frame_b", "reason": "assistant_stream", "note": "from /tmp/private-b.json"},
            root=root_b,
        )

        records_a = portal_project_events.read_project_event_records(project_id, root=root_a)
        records_b = portal_project_events.read_project_event_records(project_id, root=root_b)

        self.assertEqual([record["id"] for record in records_a], [1])
        self.assertEqual([record["id"] for record in records_b], [1])
        self.assertEqual(records_a[0]["data"]["frame_id"], "frame_a")
        self.assertEqual(records_b[0]["data"]["frame_id"], "frame_b")
        self.assertTrue(portal_project_events.project_event_log_path(project_id, root=root_a).is_file())
        self.assertTrue(portal_project_events.project_event_log_path(project_id, root=root_b).is_file())
        self.assertEqual(portal_project_events.read_project_event_records(project_id), [])
        _assert_public_payload(records_a)
        _assert_public_payload(records_b)

    def test_portal_store_emits_project_events_into_mutation_root(self) -> None:
        root = self.genomi_home / "portal-root"
        project = portal_store.create_project(name="Rooted events", root=root)
        self.addCleanup(portal_project_events.discard_project_events, project["project_id"], root=root)

        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Resolve rs429358",
            agent_id="codex",
            root=root,
        )
        assert frame is not None

        records = portal_project_events.read_project_event_records(project["project_id"], root=root)

        self.assertEqual([record["event"] for record in records], ["frame_changed", "messages_changed", "project_changed"])
        self.assertEqual(records[0]["data"]["frame_id"], frame["id"])
        self.assertEqual(records[0]["data"]["reason"], "created")
        self.assertEqual(records[1]["data"]["frame_id"], frame["id"])
        self.assertEqual(records[1]["data"]["reason"], "created")
        self.assertEqual(records[2]["data"], {"project_id": project["project_id"], "reason": "frame_created"})
        self.assertTrue(portal_project_events.project_event_log_path(project["project_id"], root=root).is_file())
        self.assertFalse(portal_project_events.project_event_log_path(project["project_id"]).exists())
        self.assertEqual(portal_project_events.read_project_event_records(project["project_id"]), [])
        _assert_public_payload(records)

    def test_project_event_replay_window_is_bounded_when_loading_durable_log(self) -> None:
        root = self.genomi_home / "bounded-root"
        project_id = "proj_replay_window"
        self.addCleanup(portal_project_events.discard_project_events, project_id, root=root)

        for index in range(portal_project_events.PROJECT_EVENT_REPLAY_LIMIT + 7):
            portal_project_events.emit_project_event(
                project_id,
                "messages_changed",
                {
                    "frame_id": "frame_1",
                    "reason": "assistant_stream",
                    "message_id": f"msg_{index}",
                },
                root=root,
            )

        records = portal_project_events.read_project_event_records(project_id, root=root)

        self.assertEqual(len(records), portal_project_events.PROJECT_EVENT_REPLAY_LIMIT)
        self.assertEqual(records[0]["id"], 8)
        self.assertEqual(records[-1]["id"], portal_project_events.PROJECT_EVENT_REPLAY_LIMIT + 7)
        _assert_public_payload(records)

    def test_discard_project_events_removes_only_requested_root(self) -> None:
        root_a = self.genomi_home / "discard-a"
        root_b = self.genomi_home / "discard-b"
        project_id = "proj_discard_root"
        self.addCleanup(portal_project_events.discard_project_events, project_id, root=root_b)

        portal_project_events.emit_project_event(
            project_id,
            "messages_changed",
            {"frame_id": "frame_a", "reason": "assistant_stream"},
            root=root_a,
        )
        portal_project_events.emit_project_event(
            project_id,
            "messages_changed",
            {"frame_id": "frame_b", "reason": "assistant_stream"},
            root=root_b,
        )

        portal_project_events.discard_project_events(project_id, root=root_a)

        self.assertEqual(portal_project_events.read_project_event_records(project_id, root=root_a), [])
        self.assertEqual(portal_project_events.read_project_event_records(project_id, root=root_b)[0]["data"]["frame_id"], "frame_b")
        self.assertFalse(portal_project_events.project_event_log_path(project_id, root=root_a).exists())
        self.assertTrue(portal_project_events.project_event_log_path(project_id, root=root_b).is_file())


def _assert_public_payload(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in _PRIVATE_KEYS:
                raise AssertionError(f"private key leaked: {key}")
            _assert_public_payload(child)
    elif isinstance(value, list):
        for child in value:
            _assert_public_payload(child)
    elif isinstance(value, str) and _PRIVATE_PATH_RE.search(value):
        raise AssertionError(f"private path leaked: {value}")
