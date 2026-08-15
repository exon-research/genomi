from __future__ import annotations

import io
import json
import os
import re
import tempfile
import unittest
import zipfile
from unittest import mock

from genomi.interfaces import portal_frame_bundles, portal_store
from genomi.runtime import portal_routes

from tests.support.runtime.genomi import GenomiRuntimeTestCase
from tests.test_mcp_http import _request_raw, _running_server

_PRIVATE_PATH_RE = re.compile(r"(?:/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes|~)(?:/|$)")
_PRIVATE_KEYS = {"context_file", "registry_file", "agi_path", "dashboard_path", "shared_evidence_db", "artifact_path", "path", "result"}


class PortalFrameBundleTests(GenomiRuntimeTestCase):
    def test_project_frame_bundle_includes_messages_artifacts_and_version_files(self) -> None:
        project = portal_store.create_project(name="Frame bundle")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Resolve rs429358",
            agent_id="codex",
            selected_evidence=[{"id": "ev-1", "label": "ClinVar", "text": "ClinVar: /tmp/private.sqlite"}],
        )
        assert frame is not None
        portal_store.append_message(
            str(frame["id"]),
            role="tool",
            run_id="run_1",
            event={
                "type": "tool_result",
                "name": "variant.resolve",
                "content": "resolved from /Users/matthewzmd/private/genome.sqlite",
            },
        )
        source = self.genomi_home / "private-inputs" / "report.html"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("<!doctype html><title>Frame report</title><p>Evidence</p>", encoding="utf-8")
        artifact = portal_store.add_artifact(
            project["project_id"],
            kind="evidence_packet",
            renderer="evidence_packet",
            title="Evidence report",
            operation="research.build_target_packet",
            result={"status": "completed"},
            frame_id=str(frame["id"]),
            file_path=str(source),
        )
        assert artifact is not None

        bundle = portal_frame_bundles.project_frame_bundle(project["project_id"], str(frame["id"]))

        assert bundle is not None
        self.assertEqual(bundle.content_type, "application/zip")
        self.assertEqual(bundle.filename, f"{frame['id']}-bundle.zip")
        with zipfile.ZipFile(io.BytesIO(bundle.body)) as archive:
            names = archive.namelist()
            self.assertIn("manifest.json", names)
            self.assertIn("frame.json", names)
            self.assertIn("messages.json", names)
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            frame_metadata = json.loads(archive.read("frame.json").decode("utf-8"))
            messages = json.loads(archive.read("messages.json").decode("utf-8"))
            artifact_entry = manifest["artifacts"][0]
            artifact_metadata = json.loads(archive.read(artifact_entry["metadata_entry"]).decode("utf-8"))
            included = [item for item in artifact_entry["files"] if item["included"]]
            self.assertEqual(len(included), 1)
            self.assertIn(included[0]["archive_entry"], names)
            self.assertEqual(archive.read(included[0]["archive_entry"]).decode("utf-8"), source.read_text(encoding="utf-8"))

        self.assertEqual(manifest["schema"], "genomi_portal_frame_bundle")
        self.assertEqual(manifest["frame_id"], frame["id"])
        self.assertEqual(frame_metadata["schema"], "genomi_portal_frame_metadata")
        self.assertEqual(frame_metadata["frame"]["id"], frame["id"])
        self.assertEqual(frame_metadata["messages"]["entry"], "messages.json")
        self.assertEqual(frame_metadata["artifacts"]["count"], 1)
        self.assertEqual(messages["schema"], "genomi_portal_frame_messages")
        self.assertEqual(messages["total"], 2)
        self.assertEqual(messages["items"][0]["role"], "user")
        self.assertEqual(artifact_metadata["artifact"]["id"], artifact["id"])
        self.assertIsNone(portal_frame_bundles.project_frame_bundle("wrong-project", str(frame["id"])))
        _assert_public_payload(manifest)
        _assert_public_payload(frame_metadata)
        _assert_public_payload(messages)
        _assert_public_payload(artifact_metadata)


class PortalFrameBundleRouteTests(unittest.TestCase):
    def test_project_frame_bundle_route_returns_zip_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            project = portal_store.create_project(name="Frame bundle")
            frame = portal_store.create_frame(
                project_id=project["project_id"],
                request="Resolve rs429358",
                agent_id="codex",
            )
            assert frame is not None
            with _running_server() as address:
                status, headers, body = _request_raw(
                    "GET",
                    address,
                    portal_routes.project_frame_bundle_endpoint(project["project_id"], frame["id"]),
                )
                wrong_status, _wrong_headers, _wrong_body = _request_raw(
                    "GET",
                    address,
                    portal_routes.project_frame_bundle_endpoint("wrong-project", frame["id"]),
                )

        self.assertEqual(status, 200)
        self.assertIn("application/zip", headers["content-type"])
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertIn(f"{frame['id']}-bundle.zip", headers["content-disposition"])
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertIn("manifest.json", archive.namelist())
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        self.assertEqual(manifest["schema"], "genomi_portal_frame_bundle")
        self.assertEqual(manifest["frame_id"], frame["id"])
        self.assertEqual(wrong_status, 404)
        _assert_public_payload(manifest)


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
