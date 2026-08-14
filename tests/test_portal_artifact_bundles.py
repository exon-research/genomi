from __future__ import annotations

import io
import json
import re
import zipfile

from genomi.interfaces import portal_artifact_bundles, portal_artifact_reproduction, portal_store

from tests.support.runtime.genomi import GenomiRuntimeTestCase

_PRIVATE_PATH_RE = re.compile(r"(?:/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes|~)(?:/|$)")
_PRIVATE_KEYS = {"context_file", "registry_file", "agi_path", "dashboard_path", "shared_evidence_db", "artifact_path", "path", "result"}


class PortalArtifactBundleTests(GenomiRuntimeTestCase):
    def test_project_artifact_bundle_includes_public_metadata_and_version_file(self) -> None:
        project = portal_store.create_project(name="Evidence")
        source = self.genomi_home / "private-inputs" / "report.html"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("<!doctype html><title>Report</title><p>Evidence</p>", encoding="utf-8")

        artifact = portal_store.add_artifact(
            project["project_id"],
            kind="evidence_packet",
            renderer="evidence_packet",
            title="Evidence report",
            operation="research.build_target_packet",
            result={"status": "completed"},
            file_path=str(source),
        )
        assert artifact is not None

        bundle = portal_artifact_bundles.project_artifact_bundle(project["project_id"], artifact["id"])

        assert bundle is not None
        self.assertEqual(bundle.content_type, "application/zip")
        self.assertEqual(bundle.filename, f"{artifact['id']}-bundle.zip")
        with zipfile.ZipFile(io.BytesIO(bundle.body)) as archive:
            names = archive.namelist()
            self.assertIn("manifest.json", names)
            self.assertIn("metadata.json", names)
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            metadata = json.loads(archive.read("metadata.json").decode("utf-8"))
            included = [item for item in manifest["files"] if item["included"]]
            self.assertEqual(len(included), 1)
            version_entry = included[0]["archive_entry"]
            self.assertIn(version_entry, names)
            self.assertEqual(archive.read(version_entry).decode("utf-8"), source.read_text(encoding="utf-8"))

        self.assertEqual(manifest["schema"], "genomi_portal_artifact_bundle")
        self.assertEqual(manifest["artifact_id"], artifact["id"])
        self.assertEqual(manifest["metadata_entry"], "metadata.json")
        self.assertTrue(manifest["files"][0]["filename"].startswith("ver_"))
        self.assertEqual(metadata["schema"], "genomi_portal_artifact_metadata")
        self.assertEqual(metadata["artifact"]["id"], artifact["id"])
        self.assertIsNone(portal_artifact_bundles.project_artifact_bundle("wrong-project", artifact["id"]))
        _assert_public_payload(manifest)
        _assert_public_payload(metadata)

    def test_project_artifact_script_bundle_includes_ready_public_rebuild_recipe(self) -> None:
        project = portal_store.create_project(name="Evidence")
        source = self.genomi_home / "private-inputs" / "report.html"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("<!doctype html><title>Report</title><p>Evidence</p>", encoding="utf-8")
        reproduction = portal_artifact_reproduction.operation_rebuild_recipe(
            operation="research.build_target_packet",
            renderer="evidence_packet",
            params={"target_type": "topic", "topic": "rs429358"},
            artifact_family="evidence_report",
        )
        artifact = portal_store.add_artifact(
            project["project_id"],
            kind="evidence_packet",
            renderer="evidence_packet",
            title="Evidence report",
            operation="research.build_target_packet",
            result={"status": "completed"},
            file_path=str(source),
            reproduction=reproduction,
        )
        assert artifact is not None
        version_id = artifact["latest_version_id"]

        bundle = portal_artifact_bundles.project_artifact_script_bundle(project["project_id"], artifact["id"], version_id)

        assert bundle is not None
        self.assertEqual(bundle.content_type, "application/zip")
        self.assertEqual(bundle.filename, f"{artifact['id']}-{version_id}-rebuild.zip")
        with zipfile.ZipFile(io.BytesIO(bundle.body)) as archive:
            names = archive.namelist()
            self.assertEqual({"manifest.json", "rebuild-recipe.json", "rebuild.sh", "README.md"}, set(names))
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            recipe = json.loads(archive.read("rebuild-recipe.json").decode("utf-8"))
            script = archive.read("rebuild.sh").decode("utf-8")
            readme = archive.read("README.md").decode("utf-8")

        self.assertEqual(manifest["schema"], "genomi_portal_artifact_script_bundle")
        self.assertEqual(manifest["artifact_id"], artifact["id"])
        self.assertEqual(manifest["version_id"], version_id)
        self.assertEqual(recipe["status"], "ready")
        self.assertIn("genomi call research.build_target_packet", script)
        self.assertTrue(script.startswith("#!/usr/bin/env bash\nset -euo pipefail\n"))
        self.assertIn("does not replay the assistant conversation", readme)
        self.assertIsNone(portal_artifact_bundles.project_artifact_script_bundle("wrong-project", artifact["id"], version_id))
        _assert_public_payload(manifest)
        _assert_public_payload(recipe)
        _assert_public_payload(script)
        _assert_public_payload(readme)

    def test_project_artifact_script_bundle_requires_public_ready_recipe(self) -> None:
        project = portal_store.create_project(name="Private evidence")
        source = self.genomi_home / "private-inputs" / "report.html"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("<!doctype html><title>Report</title><p>Evidence</p>", encoding="utf-8")
        reproduction = portal_artifact_reproduction.operation_rebuild_recipe(
            operation="research.build_target_packet",
            renderer="evidence_packet",
            params={"target_type": "topic", "topic": "rs429358", "context_file": "/Users/matthewzmd/private.json"},
            artifact_family="evidence_report",
        )
        artifact = portal_store.add_artifact(
            project["project_id"],
            kind="evidence_packet",
            renderer="evidence_packet",
            title="Private evidence report",
            operation="research.build_target_packet",
            result={"status": "completed"},
            file_path=str(source),
            reproduction=reproduction,
        )
        assert artifact is not None

        self.assertIsNone(portal_artifact_bundles.project_artifact_script_bundle(project["project_id"], artifact["id"]))


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
