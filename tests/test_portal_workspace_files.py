from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from unittest import mock

from genomi.interfaces import portal_state, portal_store, portal_workspace_files, portal_workspaces

from tests.support.runtime.genomi import GenomiRuntimeTestCase

_PRIVATE_PATH_RE = re.compile(r"(?:/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes|~)(?:/|$)")


class PortalWorkspaceFileTests(GenomiRuntimeTestCase):
    def test_webui_project_workspace_lives_under_genomi_home_workspace(self) -> None:
        project = portal_store.create_project(name="Web workspace")
        workspace = portal_workspaces.project_workspace_dir(project["project_id"])

        self.assertEqual(workspace, self.genomi_home / "workspace" / project["project_id"])
        self.assertTrue(workspace.is_dir())
        self.assertEqual(project["workspace"]["owner"], "genomi_webui")
        self.assertEqual(project["workspace"]["storage"], "genomi_home_workspace")
        self.assertEqual(project["workspace"]["path_hint"], f"$GENOMI_HOME/workspace/{project['project_id']}")
        self.assertNotIn(str(self.genomi_home), str(project["workspace"]))

    def test_project_reads_refresh_stale_workspace_metadata(self) -> None:
        project = portal_store.create_project(name="Stale workspace metadata")

        def mutate(state: dict[str, object]) -> dict[str, object]:
            stored_project = state["projects"][project["project_id"]]
            stored_project["workspace"] = {
                "scope": "project",
                "workspace_id": project["project_id"],
                "status": "ready",
            }
            return stored_project

        portal_state.mutate_state(mutate)

        reloaded = portal_store.get_project(project["project_id"])
        [listed] = portal_store.list_projects()

        assert reloaded is not None
        self.assertEqual(reloaded["workspace"]["owner"], "genomi_webui")
        self.assertEqual(reloaded["workspace"]["storage"], "genomi_home_workspace")
        self.assertEqual(reloaded["workspace"]["path_hint"], f"$GENOMI_HOME/workspace/{project['project_id']}")
        self.assertEqual(listed["workspace"]["owner"], "genomi_webui")
        self.assertEqual(listed["workspace"]["storage"], "genomi_home_workspace")

    def test_workspace_file_listing_is_path_safe_and_links_produced_artifacts(self) -> None:
        project = portal_store.create_project(name="Workspace files")
        workspace = portal_workspaces.ensure_project_workspace(project["project_id"])
        (workspace / "reports").mkdir(parents=True, exist_ok=True)
        body = b"APOE report\n"
        (workspace / "reports" / "apoe.txt").write_bytes(body)
        (workspace / ".hidden.txt").write_text("hidden\n", encoding="utf-8")
        (workspace / "node_modules").mkdir()
        (workspace / "node_modules" / "ignored.txt").write_text("ignored\n", encoding="utf-8")
        artifact = portal_store.add_artifact_from_bytes(
            project["project_id"],
            kind="project_file",
            renderer="project_file",
            title="reports/apoe.txt",
            operation="portal.agent_file",
            result={"status": "completed", "source": "host_agent_workspace", "filename": "reports/apoe.txt"},
            original_filename="apoe.txt",
            content_type="text/plain",
            body=body,
            summary={
                "kind": "project_file",
                "source": "host_agent_workspace",
                "filename": "reports/apoe.txt",
                "content_type": "text/plain",
                "size_bytes": len(body),
                "sha256": _sha256(body),
            },
            summary_lines=["Produced file", "reports/apoe.txt", "text/plain"],
        )
        assert artifact is not None

        payload = portal_workspace_files.list_project_workspace_files(project["project_id"])

        assert payload is not None
        self.assertEqual(payload["project_id"], project["project_id"])
        self.assertEqual(payload["workspace"]["owner"], "genomi_webui")
        self.assertEqual(payload["workspace"]["storage"], "genomi_home_workspace")
        self.assertEqual(payload["workspace"]["path_hint"], f"$GENOMI_HOME/workspace/{project['project_id']}")
        self.assertEqual(payload["summary"], {"total_files": 1, "linked_artifacts": 1})
        self.assertEqual(len(payload["files"]), 1)
        file = payload["files"][0]
        self.assertEqual(file["relative_path"], "reports/apoe.txt")
        self.assertEqual(file["name"], "apoe.txt")
        self.assertEqual(file["directory"], "reports")
        self.assertEqual(file["content_type"], "text/plain")
        self.assertEqual(file["file_kind"], "text")
        self.assertEqual(file["kind_label"], "Text")
        self.assertEqual(file["record_type"], "generated_record")
        self.assertEqual(file["record_label"], "Generated record")
        self.assertEqual(file["size_bytes"], len("APOE report\n"))
        self.assertEqual(file["size_label"], "12 bytes")
        self.assertEqual(file["artifact_id"], artifact["id"])
        self.assertEqual(file["artifact_preview_url"], f"/api/projects/{project['project_id']}/artifacts/{artifact['id']}/file")
        _assert_public_payload(payload)

    def test_workspace_file_listing_does_not_link_stale_artifact_after_file_change(self) -> None:
        project = portal_store.create_project(name="Workspace stale generated file")
        workspace = portal_workspaces.ensure_project_workspace(project["project_id"])
        (workspace / "reports").mkdir(parents=True, exist_ok=True)
        original_body = b"APOE report\n"
        (workspace / "reports" / "apoe.txt").write_bytes(original_body)
        artifact = portal_store.add_artifact_from_bytes(
            project["project_id"],
            kind="project_file",
            renderer="project_file",
            title="reports/apoe.txt",
            operation="portal.agent_file",
            result={"status": "completed", "source": "host_agent_workspace", "filename": "reports/apoe.txt"},
            original_filename="apoe.txt",
            content_type="text/plain",
            body=original_body,
            summary={
                "kind": "project_file",
                "source": "host_agent_workspace",
                "filename": "reports/apoe.txt",
                "content_type": "text/plain",
                "size_bytes": len(original_body),
                "sha256": _sha256(original_body),
            },
            summary_lines=["Produced file", "reports/apoe.txt", "text/plain"],
        )
        assert artifact is not None
        (workspace / "reports" / "apoe.txt").write_bytes(b"BRCA report\n")

        payload = portal_workspace_files.list_project_workspace_files(project["project_id"])

        assert payload is not None
        self.assertEqual(payload["summary"], {"total_files": 1, "linked_artifacts": 0})
        [file] = payload["files"]
        self.assertEqual(file["relative_path"], "reports/apoe.txt")
        self.assertEqual(file["record_type"], "research_file")
        self.assertEqual(file["record_label"], "Research file")
        self.assertNotIn("artifact_id", file)
        self.assertNotIn("artifact_title", file)
        self.assertNotIn("artifact_preview_url", file)
        self.assertNotIn("origin_context", file)
        _assert_public_payload(payload)

    def test_workspace_file_listing_links_matching_artifact_when_filename_reused(self) -> None:
        project = portal_store.create_project(name="Workspace reused filename")
        workspace = portal_workspaces.ensure_project_workspace(project["project_id"])
        (workspace / "reports").mkdir(parents=True, exist_ok=True)
        first_body = b"APOE report v1\n"
        second_body = b"APOE report v2\n"
        (workspace / "reports" / "apoe.txt").write_bytes(first_body)
        first_artifact = portal_store.add_artifact_from_bytes(
            project["project_id"],
            kind="project_file",
            renderer="project_file",
            title="reports/apoe.txt",
            operation="portal.agent_file",
            result={"status": "completed", "source": "host_agent_workspace", "filename": "reports/apoe.txt"},
            original_filename="apoe.txt",
            content_type="text/plain",
            body=first_body,
            summary={
                "kind": "project_file",
                "source": "host_agent_workspace",
                "filename": "reports/apoe.txt",
                "content_type": "text/plain",
                "size_bytes": len(first_body),
                "sha256": _sha256(first_body),
            },
            summary_lines=["Produced file", "reports/apoe.txt", "text/plain"],
        )
        assert first_artifact is not None
        second_artifact = portal_store.add_artifact_from_bytes(
            project["project_id"],
            kind="project_file",
            renderer="project_file",
            title="reports/apoe.txt",
            operation="portal.agent_file",
            result={"status": "completed", "source": "host_agent_workspace", "filename": "reports/apoe.txt"},
            original_filename="apoe.txt",
            content_type="text/plain",
            body=second_body,
            summary={
                "kind": "project_file",
                "source": "host_agent_workspace",
                "filename": "reports/apoe.txt",
                "content_type": "text/plain",
                "size_bytes": len(second_body),
                "sha256": _sha256(second_body),
            },
            summary_lines=["Produced file", "reports/apoe.txt", "text/plain"],
        )
        assert second_artifact is not None

        def mark_second_newer(state: dict[str, object]) -> dict[str, object]:
            state["artifacts"][second_artifact["id"]]["updated_at"] = "9999-01-01T00:00:00.000Z"
            return state

        portal_state.mutate_state(mark_second_newer)
        (workspace / "reports" / "apoe.txt").write_bytes(first_body)

        payload = portal_workspace_files.list_project_workspace_files(project["project_id"])

        assert payload is not None
        self.assertEqual(payload["summary"], {"total_files": 1, "linked_artifacts": 1})
        [file] = payload["files"]
        self.assertEqual(file["relative_path"], "reports/apoe.txt")
        self.assertEqual(file["artifact_id"], first_artifact["id"])
        self.assertNotEqual(file["artifact_id"], second_artifact["id"])
        self.assertEqual(file["record_type"], "generated_record")
        _assert_public_payload(payload)

    def test_workspace_file_listing_projects_generated_file_origin_context(self) -> None:
        project = portal_store.create_project(name="Workspace file origin")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Create a markdown evidence record",
            agent_id="codex",
        )
        assert frame is not None
        portal_store.append_message(str(frame["id"]), role="assistant", text="Evidence record ready.", run_id="run-origin")
        portal_store.finish_frame(str(frame["id"]), status="completed", output="Evidence record ready.", run_id="run-origin")
        workspace = portal_workspaces.ensure_project_workspace(project["project_id"])
        (workspace / "reports").mkdir(parents=True, exist_ok=True)
        body = b"# APOE record\n"
        (workspace / "reports" / "apoe.md").write_bytes(body)
        artifact = portal_store.add_artifact_from_bytes(
            project["project_id"],
            kind="project_file",
            renderer="project_file",
            title="reports/apoe.md",
            operation="portal.agent_file",
            result={"status": "completed", "source": "host_agent_workspace", "filename": "reports/apoe.md"},
            original_filename="apoe.md",
            content_type="text/markdown",
            body=body,
            frame_id=str(frame["id"]),
            summary={
                "kind": "project_file",
                "source": "host_agent_workspace",
                "filename": "reports/apoe.md",
                "content_type": "text/markdown",
                "size_bytes": len(body),
                "sha256": _sha256(body),
            },
            summary_lines=["Produced file", "reports/apoe.md", "text/markdown"],
        )
        assert artifact is not None

        payload = portal_workspace_files.list_project_workspace_files(project["project_id"])

        assert payload is not None
        [file] = payload["files"]
        self.assertEqual(file["relative_path"], "reports/apoe.md")
        self.assertEqual(file["artifact_id"], artifact["id"])
        self.assertEqual(file["origin_context"]["frame_id"], frame["id"])
        self.assertEqual(file["origin_context"]["frame_title"], "Create a markdown evidence record")
        self.assertEqual(file["origin_context"]["run_ids"], ["run-origin"])
        self.assertEqual(file["origin_context"]["producing_run_id"], "run-origin")
        self.assertTrue(file["origin_context"]["producing_assistant_message_id"])
        _assert_public_payload(payload)

    def test_workspace_file_listing_links_imported_files_without_generated_origin(self) -> None:
        project = portal_store.create_project(name="Imported workspace file")
        workspace = portal_workspaces.ensure_project_workspace(project["project_id"])
        body = b"gene,score\nAPOE,0.91\n"
        (workspace / "lab-notes.csv").write_bytes(body)
        artifact = portal_store.add_artifact_from_bytes(
            project["project_id"],
            kind="project_file",
            renderer="project_file",
            title="lab-notes.csv",
            operation="portal.import_file",
            result={"status": "completed", "import": {"workspace_relative_path": "lab-notes.csv"}},
            original_filename="lab-notes.csv",
            content_type="text/csv",
            body=body,
            summary={
                "kind": "project_file",
                "source": "portal_import",
                "filename": "lab-notes.csv",
                "original_filename": "lab-notes.csv",
                "content_type": "text/csv",
                "size_bytes": len(body),
                "sha256": _sha256(body),
            },
            summary_lines=["Imported file", "lab-notes.csv", "text/csv"],
        )
        assert artifact is not None

        payload = portal_workspace_files.list_project_workspace_files(project["project_id"])

        assert payload is not None
        self.assertEqual(payload["summary"], {"total_files": 1, "linked_artifacts": 1})
        [file] = payload["files"]
        self.assertEqual(file["relative_path"], "lab-notes.csv")
        self.assertEqual(file["record_type"], "imported_file")
        self.assertEqual(file["record_label"], "Imported file")
        self.assertEqual(file["artifact_id"], artifact["id"])
        self.assertNotIn("origin_context", file)
        _assert_public_payload(payload)

    def test_workspace_file_listing_returns_none_for_missing_project(self) -> None:
        self.assertIsNone(portal_workspace_files.list_project_workspace_files("proj_missing"))

    def test_workspace_file_preview_is_bounded_and_path_safe(self) -> None:
        project = portal_store.create_project(name="Workspace file preview")
        workspace = portal_workspaces.ensure_project_workspace(project["project_id"])
        (workspace / "reports").mkdir(parents=True, exist_ok=True)
        (workspace / "reports" / "apoe.txt").write_text(
            "APOE report from /Users/matthewzmd/private.vcf\n",
            encoding="utf-8",
        )

        preview = portal_workspace_files.preview_project_workspace_file(project["project_id"], "reports/apoe.txt")

        assert preview is not None
        self.assertEqual(preview["status"], "available")
        self.assertEqual(preview["preview_kind"], "text")
        self.assertEqual(preview["file_kind"], "text")
        self.assertEqual(preview["kind_label"], "Text")
        self.assertEqual(preview["record_type"], "research_record")
        self.assertEqual(preview["record_label"], "Research record")
        self.assertEqual(preview["relative_path"], "reports/apoe.txt")
        self.assertIn("APOE report", preview["text"])
        self.assertIn("[redacted local path]", preview["text"])
        escaped = portal_workspace_files.preview_project_workspace_file(project["project_id"], "../outside.txt")
        missing_file = portal_workspace_files.preview_project_workspace_file(project["project_id"], "reports/missing.txt")
        missing_project = portal_workspace_files.preview_project_workspace_file("proj_missing", "reports/apoe.txt")
        self.assertEqual(escaped["status"], "path_escape")
        self.assertEqual(missing_file["status"], "not_found")
        self.assertEqual(missing_project["status"], "missing_project")
        with mock.patch.object(Path, "read_bytes", side_effect=OSError("blocked")):
            unreadable = portal_workspace_files.preview_project_workspace_file(project["project_id"], "reports/apoe.txt")
        self.assertEqual(unreadable["status"], "unreadable")
        _assert_public_payload(preview)
        _assert_public_payload(escaped)
        _assert_public_payload(missing_file)
        _assert_public_payload(missing_project)
        _assert_public_payload(unreadable)

    def test_workspace_file_preview_reports_large_files_as_unavailable(self) -> None:
        project = portal_store.create_project(name="Large workspace file preview")
        workspace = portal_workspaces.ensure_project_workspace(project["project_id"])
        (workspace / "large.bin").write_bytes(b"x" * (portal_workspace_files.MAX_WORKSPACE_FILE_PREVIEW_BYTES + 1))

        preview = portal_workspace_files.preview_project_workspace_file(project["project_id"], "large.bin")

        assert preview is not None
        self.assertEqual(preview["status"], "unavailable")
        self.assertEqual(preview["preview_kind"], "none")
        self.assertIn("larger", preview["reason"])

    def test_workspace_pdf_preview_exposes_project_document_url(self) -> None:
        project = portal_store.create_project(name="Workspace PDF preview")
        workspace = portal_workspaces.ensure_project_workspace(project["project_id"])
        (workspace / "papers").mkdir(parents=True, exist_ok=True)
        (workspace / "papers" / "review.pdf").write_bytes(b"%PDF-1.4\n" + b"x" * (portal_workspace_files.MAX_WORKSPACE_FILE_PREVIEW_BYTES + 1))

        preview = portal_workspace_files.preview_project_workspace_file(project["project_id"], "papers/review.pdf")

        self.assertEqual(preview["status"], "available")
        self.assertEqual(preview["preview_kind"], "document")
        self.assertEqual(preview["content_type"], "application/pdf")
        self.assertEqual(
            preview["document_url"],
            f"/api/projects/{project['project_id']}/workspace/file?path=papers%2Freview.pdf",
        )
        self.assertNotIn("text", preview)
        self.assertNotIn("data_url", preview)
        _assert_public_payload(preview)

    def test_workspace_notebook_preview_returns_cell_outline_without_raw_json(self) -> None:
        project = portal_store.create_project(name="Workspace notebook preview")
        workspace = portal_workspaces.ensure_project_workspace(project["project_id"])
        notebook = {
            "nbformat": 4,
            "metadata": {"language_info": {"name": "python"}},
            "cells": [
                {
                    "cell_type": "markdown",
                    "source": ["# APOE review\n", "Notes from /Users/matthewzmd/private.md"],
                },
                {
                    "cell_type": "code",
                    "source": ["print('CYP2C19')\n"],
                    "outputs": [{"output_type": "stream", "text": "ok\n"}],
                },
            ],
        }
        (workspace / "analysis.ipynb").write_text(json.dumps(notebook), encoding="utf-8")

        preview = portal_workspace_files.preview_project_workspace_file(project["project_id"], "analysis.ipynb")

        self.assertEqual(preview["status"], "available")
        self.assertEqual(preview["preview_kind"], "notebook")
        self.assertEqual(preview["notebook"]["summary"], "2 cells · 1 code · 1 markdown · python")
        self.assertEqual(preview["notebook"]["cell_count"], 2)
        self.assertEqual(preview["notebook"]["cells"][0]["cell_type"], "markdown")
        self.assertIn("APOE review", preview["notebook"]["cells"][0]["source"])
        self.assertIn("[redacted local path]", preview["notebook"]["cells"][0]["source"])
        self.assertEqual(preview["notebook"]["cells"][1]["output_count"], 1)
        self.assertNotIn('"cells"', str(preview["notebook"]["cells"][0]))
        _assert_public_payload(preview)

    def test_workspace_file_preview_rejects_symlink_components_like_listing(self) -> None:
        project = portal_store.create_project(name="Workspace file symlink preview")
        workspace = portal_workspaces.ensure_project_workspace(project["project_id"])
        real_dir = workspace / "reports"
        real_dir.mkdir(parents=True, exist_ok=True)
        (real_dir / "apoe.txt").write_text("APOE report\n", encoding="utf-8")
        try:
            os.symlink(real_dir, workspace / "linked_reports", target_is_directory=True)
            os.symlink(real_dir / "apoe.txt", workspace / "linked_apoe.txt")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

        payload = portal_workspace_files.list_project_workspace_files(project["project_id"])
        linked_dir_preview = portal_workspace_files.preview_project_workspace_file(
            project["project_id"],
            "linked_reports/apoe.txt",
        )
        linked_file_preview = portal_workspace_files.preview_project_workspace_file(
            project["project_id"],
            "linked_apoe.txt",
        )

        assert payload is not None
        self.assertEqual([file["relative_path"] for file in payload["files"]], ["reports/apoe.txt"])
        self.assertEqual(linked_dir_preview["status"], "path_escape")
        self.assertEqual(linked_file_preview["status"], "path_escape")
        _assert_public_payload(linked_dir_preview)
        _assert_public_payload(linked_file_preview)


def _assert_public_payload(value) -> None:
    text = str(value)
    assert not _PRIVATE_PATH_RE.search(text), text


def _sha256(body: bytes) -> str:
    return f"sha256:{hashlib.sha256(body).hexdigest()}"
