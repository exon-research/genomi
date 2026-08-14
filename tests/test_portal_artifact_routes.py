from __future__ import annotations

import io
import json
import base64
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from genomi.interfaces import portal_store
from genomi.runtime import portal_routes

from tests.test_mcp_http import _assert_public_payload, _request_json, _request_raw, _running_server


class PortalArtifactRouteTests(unittest.TestCase):
    def test_project_artifact_import_route_creates_project_file_artifact(self) -> None:
        body = b"gene,score\nAPOE,0.91\n"
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"GENOMI_HOME": tmp}):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Portal Test"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]
                import_status, import_payload = _request_json(
                    "POST",
                    address,
                    portal_routes.project_artifact_import_endpoint(project_id),
                    {
                        "filename": "lab-notes.csv",
                        "contentType": "text/csv",
                        "contentBase64": base64.b64encode(body).decode("ascii"),
                    },
                )
                artifact = import_payload["artifact"]
                imports_dir_exists = (Path(tmp) / "portal" / "artifacts" / project_id / "imports").exists()
                workspace_file = Path(tmp) / "workspace" / project_id / "lab-notes.csv"
                file_status, file_headers, file_body = _request_raw(
                    "GET",
                    address,
                    artifact["preview_url"],
                )
                workspace_status, workspace_payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project_id}/workspace/files",
                )
                workspace_file_body = workspace_file.read_bytes()
                artifacts_status, artifacts_payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project_id}/artifacts",
                )

        self.assertEqual(import_status, 201)
        self.assertEqual(import_payload["imported"]["filename"], "lab-notes.csv")
        self.assertEqual(import_payload["imported"]["workspace_relative_path"], "lab-notes.csv")
        self.assertEqual(import_payload["imported"]["content_type"], "text/csv")
        self.assertEqual(import_payload["imported"]["size_bytes"], len(body))
        self.assertEqual(workspace_file_body, body)
        self.assertEqual(artifact["kind"], "project_file")
        self.assertEqual(artifact["renderer"], "project_file")
        self.assertEqual(artifact["operation"], "portal.import_file")
        self.assertEqual(artifact["title"], "lab-notes.csv")
        self.assertEqual(artifact["open_label"], "Open file")
        self.assertEqual(artifact["latest_version"]["content_type"], "text/csv")
        self.assertEqual(artifact["latest_version"]["size_bytes"], len(body))
        self.assertFalse(imports_dir_exists)
        self.assertEqual(file_status, 200)
        self.assertIn("text/csv", file_headers["content-type"])
        self.assertEqual(file_body, body)
        self.assertEqual(workspace_status, 200)
        self.assertEqual(workspace_payload["summary"], {"total_files": 1, "linked_artifacts": 1})
        self.assertEqual(workspace_payload["files"][0]["relative_path"], "lab-notes.csv")
        self.assertEqual(workspace_payload["files"][0]["record_label"], "Imported file")
        self.assertEqual(workspace_payload["files"][0]["record_type"], "imported_file")
        self.assertEqual(workspace_payload["files"][0]["artifact_id"], artifact["id"])
        self.assertNotIn("origin_context", workspace_payload["files"][0])
        self.assertEqual(artifacts_status, 200)
        self.assertEqual(artifacts_payload["artifacts"][0]["id"], artifact["id"])
        _assert_public_payload(import_payload)
        _assert_public_payload(workspace_payload)
        _assert_public_payload(artifacts_payload)

    def test_project_artifact_import_persists_explicit_content_type_for_extensionless_upload(self) -> None:
        body = b"plain notes\n"
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"GENOMI_HOME": tmp}):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Portal Test"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]
                import_status, import_payload = _request_json(
                    "POST",
                    address,
                    portal_routes.project_artifact_import_endpoint(project_id),
                    {
                        "filename": "notes",
                        "contentType": "text/plain",
                        "contentBase64": base64.b64encode(body).decode("ascii"),
                    },
                )
                artifact = import_payload["artifact"]
                version_id = artifact["latest_version_id"]
                version_status, version_payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project_id}/artifacts/{artifact['id']}/versions/{version_id}",
                )
                file_status, _file_headers, file_body = _request_raw("GET", address, artifact["preview_url"])
                imports_dir_exists = (Path(tmp) / "portal" / "artifacts" / project_id / "imports").exists()

        self.assertEqual(import_status, 201)
        self.assertEqual(version_status, 200)
        self.assertEqual(artifact["latest_version"]["content_type"], "text/plain")
        self.assertEqual(version_payload["content_type"], "text/plain")
        self.assertTrue(str(version_payload["filename"]).endswith(".artifact"))
        self.assertEqual(file_status, 200)
        self.assertEqual(file_body, body)
        self.assertFalse(imports_dir_exists)
        _assert_public_payload(import_payload)
        _assert_public_payload(version_payload)

    def test_project_artifact_import_rejects_hidden_workspace_filename(self) -> None:
        body = b"token=secret\n"
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"GENOMI_HOME": tmp}):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Portal Test"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]
                import_status, import_payload = _request_json(
                    "POST",
                    address,
                    portal_routes.project_artifact_import_endpoint(project_id),
                    {
                        "filename": ".env",
                        "contentType": "text/plain",
                        "contentBase64": base64.b64encode(body).decode("ascii"),
                    },
                )
                hidden_file_exists = (Path(tmp) / "workspace" / project_id / ".env").exists()

        self.assertEqual(import_status, 400)
        self.assertEqual(import_payload["error"]["code"], "bad_request")
        self.assertFalse(hidden_file_exists)

    def test_project_artifact_review_run_surfaces_current_review_in_artifact_list(self) -> None:
        body = b"# Artifact review fixture\n"
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"GENOMI_HOME": tmp}):
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Portal Test"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]
                import_status, import_payload = _request_json(
                    "POST",
                    address,
                    portal_routes.project_artifact_import_endpoint(project_id),
                    {
                        "filename": "review-fixture.md",
                        "contentType": "text/markdown",
                        "contentBase64": base64.b64encode(body).decode("ascii"),
                    },
                )
                artifact_id = import_payload["artifact"]["id"]
                review_status, review_payload = _request_json(
                    "POST",
                    address,
                    portal_routes.project_artifact_review_runs_endpoint(project_id, artifact_id),
                    {},
                )
                list_status, list_payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project_id}/artifacts",
                )

        self.assertEqual(import_status, 201)
        self.assertEqual(review_status, 201)
        self.assertEqual(review_payload["review_run"]["check_status"], "passed")
        self.assertEqual(list_status, 200)
        artifact = list_payload["artifacts"][0]
        self.assertEqual(artifact["id"], artifact_id)
        self.assertEqual(artifact["review"]["kind"], "artifact_version_review")
        self.assertEqual(artifact["review"]["status"], "passed")
        self.assertEqual(artifact["review"]["counts"]["passed"], 2)
        _assert_public_payload(list_payload)

    def test_project_artifact_action_metadata_bundle_and_delete_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"GENOMI_HOME": tmp}):
            source = Path(tmp) / "report.html"
            source.write_text("<!doctype html><title>Report</title>", encoding="utf-8")
            with _running_server() as address:
                status, project_payload = _request_json("POST", address, "/api/projects", {"name": "Portal Test"})
                self.assertEqual(status, 201)
                project_id = project_payload["project"]["project_id"]
                artifact = portal_store.add_artifact(
                    project_id,
                    kind="evidence_packet",
                    renderer="evidence_packet",
                    title="Evidence report",
                    operation="research.build_target_packet",
                    result={"status": "completed"},
                    file_path=str(source),
                )
                version_id = portal_store.get_artifact(artifact["id"])["latest_version_id"]
                version_path = portal_store.project_artifact_version_file_path(project_id, artifact["id"], version_id)
                assert version_path is not None

                update_status, update_payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/artifacts/{artifact['id']}/action",
                    {"action": "rename", "title": "Renamed report"},
                )
                star_status, star_payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/artifacts/{artifact['id']}/action",
                    {"action": "star"},
                )
                hide_status, hide_payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/artifacts/{artifact['id']}/action",
                    {"action": "hide"},
                )
                unstar_status, unstar_payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/artifacts/{artifact['id']}/action",
                    {"action": "unstar"},
                )
                unhide_status, unhide_payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/artifacts/{artifact['id']}/action",
                    {"action": "unhide"},
                )
                metadata_status, metadata_headers, metadata_body = _request_raw(
                    "GET",
                    address,
                    f"/api/projects/{project_id}/artifacts/{artifact['id']}/metadata",
                )
                bundle_status, bundle_headers, bundle_body = _request_raw(
                    "GET",
                    address,
                    portal_routes.project_artifact_bundle_endpoint(project_id, artifact["id"]),
                )
                delete_status, delete_payload = _request_json(
                    "POST",
                    address,
                    f"/api/projects/{project_id}/artifacts/{artifact['id']}/action",
                    {"action": "delete"},
                )
                get_deleted_status, get_deleted_payload = _request_json(
                    "GET",
                    address,
                    f"/api/projects/{project_id}/artifacts/{artifact['id']}",
                )

        self.assertEqual(update_status, 200)
        self.assertEqual(update_payload["artifact"]["title"], "Renamed report")
        self.assertEqual(star_status, 200)
        self.assertTrue(star_payload["artifact"]["starred"])
        self.assertFalse(star_payload["artifact"]["hidden"])
        self.assertEqual(hide_status, 200)
        self.assertTrue(hide_payload["artifact"]["hidden"])
        self.assertTrue(hide_payload["artifact"]["starred"])
        self.assertEqual(unstar_status, 200)
        self.assertFalse(unstar_payload["artifact"]["starred"])
        self.assertTrue(unstar_payload["artifact"]["hidden"])
        self.assertEqual(unhide_status, 200)
        self.assertFalse(unhide_payload["artifact"]["hidden"])
        self.assertFalse(unhide_payload["artifact"]["starred"])
        self.assertEqual(metadata_status, 200)
        self.assertIn("application/json", metadata_headers["content-type"])
        self.assertEqual(metadata_headers["x-content-type-options"], "nosniff")
        self.assertIn(f'{artifact["id"]}-metadata.json', metadata_headers["content-disposition"])
        metadata_payload = json.loads(metadata_body.decode("utf-8"))
        self.assertEqual(metadata_payload["schema"], "genomi_portal_artifact_metadata")
        self.assertEqual(metadata_payload["artifact"]["id"], artifact["id"])
        self.assertEqual(metadata_payload["artifact"]["title"], "Renamed report")
        self.assertEqual(metadata_payload["versions"]["latest_version_id"], version_id)
        self.assertEqual(
            metadata_payload["versions"]["items"][0]["file_url"],
            f"/api/projects/{project_id}/artifacts/{artifact['id']}/versions/{version_id}/file",
        )
        self.assertEqual(bundle_status, 200)
        self.assertIn("application/zip", bundle_headers["content-type"])
        self.assertEqual(bundle_headers["x-content-type-options"], "nosniff")
        self.assertIn(f'{artifact["id"]}-bundle.zip', bundle_headers["content-disposition"])
        with zipfile.ZipFile(io.BytesIO(bundle_body)) as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            bundled_metadata = json.loads(archive.read("metadata.json").decode("utf-8"))
            included = [item for item in manifest["files"] if item["included"]]
            self.assertEqual(len(included), 1)
            self.assertIn(included[0]["archive_entry"], archive.namelist())
            self.assertIn(b"<title>Report</title>", archive.read(included[0]["archive_entry"]))
        self.assertEqual(manifest["schema"], "genomi_portal_artifact_bundle")
        self.assertEqual(manifest["artifact_id"], artifact["id"])
        self.assertEqual(bundled_metadata["artifact"], metadata_payload["artifact"])
        self.assertEqual(bundled_metadata["versions"], metadata_payload["versions"])
        self.assertEqual(delete_status, 200)
        self.assertEqual(delete_payload, {"ok": True, "deleted": True, "artifact_id": artifact["id"]})
        self.assertEqual(get_deleted_status, 404)
        self.assertEqual(get_deleted_payload["error"]["code"], "not_found")
        self.assertFalse(version_path.exists())
        _assert_public_payload(update_payload)
        _assert_public_payload(star_payload)
        _assert_public_payload(hide_payload)
        _assert_public_payload(unstar_payload)
        _assert_public_payload(unhide_payload)
        _assert_public_payload(metadata_payload)
        _assert_public_payload(manifest)
        _assert_public_payload(bundled_metadata)
        _assert_public_payload(delete_payload)
