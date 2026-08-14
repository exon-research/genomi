from __future__ import annotations

import json
import re
from unittest import mock

from genomi.interfaces import portal_artifact_exports, portal_artifact_reproduction, portal_artifact_review, portal_decode_artifacts, portal_state, portal_store
from genomi.runtime import portal_routes

from tests.support.runtime.genomi import GenomiRuntimeTestCase


_PRIVATE_PATH_RE = re.compile(r"(?:/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes|~)(?:/|$)")
_PRIVATE_KEYS = {"context_file", "registry_file", "agi_path", "dashboard_path", "shared_evidence_db", "path", "result"}


class PortalStoreTests(GenomiRuntimeTestCase):
    def test_project_frame_and_messages_persist_to_genomi_home(self) -> None:
        project = portal_store.create_project(name="Variant review")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Resolve rs429358",
            agent_id="codex",
            selected_evidence=[{"id": "ev-1", "label": "ClinVar node", "text": "ClinVar: observed pathogenic assertion"}],
        )
        assert frame is not None

        portal_store.append_message(
            str(frame["id"]),
            role="tool",
            event={
                "type": "tool_call",
                "name": "variant.resolve",
                "input": {"rsid": "rs429358", "agi_path": "/tmp/private.sqlite"},
            },
        )
        portal_store.finish_frame(str(frame["id"]), status="completed", output="Done")

        reloaded_project = portal_store.get_project(project["project_id"])
        reloaded_frame = portal_store.get_frame(str(frame["id"]))
        reloaded_messages = portal_store.list_frame_messages(str(frame["id"]))

        self.assertEqual(reloaded_project["conversation_count"], 1)
        self.assertEqual(reloaded_frame["status"], "completed")
        self.assertEqual(reloaded_messages["total"], 3)
        self.assertEqual(reloaded_messages["messages"][0]["role"], "user")
        self.assertEqual(reloaded_messages["messages"][0]["text"], "Resolve rs429358")
        self.assertEqual(reloaded_messages["messages"][0]["genome_context_mode"], "auto")
        self.assertEqual(reloaded_messages["messages"][0]["selected_evidence"][0]["label"], "ClinVar node")
        self.assertEqual(reloaded_frame["input_data"]["selected_evidence"][0]["prompt_text"], "ClinVar: observed pathogenic assertion")
        self.assertEqual(reloaded_messages["messages"][1]["role"], "tool")
        self.assertEqual(reloaded_messages["messages"][1]["event"]["persisted_display_only"], True)
        self.assertEqual(reloaded_messages["messages"][1]["event"]["input"], {"summary": "rs429358"})
        _assert_public_payload(reloaded_messages)
        self.assertEqual(reloaded_messages["messages"][2]["text"], "Done")
        self.assertTrue(portal_state.state_path().is_file())
        self.assertEqual(
            set(json.loads(portal_state.state_path().read_text(encoding="utf-8"))),
            {"active_project_id", "projects", "frames", "messages", "artifacts", "artifact_versions"},
        )

    def test_user_messages_preserve_turn_genome_evidence_mode(self) -> None:
        project = portal_store.create_project(name="Genome mode")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Review CYP2C19 evidence",
            agent_id="codex",
            genome_context_mode="public",
        )
        assert frame is not None
        accepted = portal_store.begin_frame_message(
            str(frame["id"]),
            text="Now include my active genome if relevant",
            agent_id="codex",
            run_id="run-auto",
            genome_context_mode="auto",
        )
        assert accepted is not None

        messages = portal_store.list_frame_messages(str(frame["id"]))["messages"]

        self.assertEqual(messages[0]["genome_context_mode"], "public")
        self.assertEqual(messages[1]["genome_context_mode"], "auto")
        _assert_public_payload(messages)

    def test_project_frames_list_returns_updated_root_frame_summaries(self) -> None:
        project = portal_store.create_project(name="Frames")
        old_frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="First question",
            agent_id="codex",
        )
        new_frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Second question",
            agent_id="claude",
        )
        assert old_frame is not None
        assert new_frame is not None
        portal_store.append_message(str(old_frame["id"]), role="assistant", text="Older answer")

        frames = portal_store.list_project_frames(project["project_id"])
        by_id = {frame["id"]: frame for frame in frames["frames"]}

        self.assertEqual(frames["project_id"], project["project_id"])
        self.assertEqual(set(by_id), {old_frame["id"], new_frame["id"]})
        self.assertEqual(by_id[old_frame["id"]]["request"], "First question")
        self.assertEqual(by_id[old_frame["id"]]["title"], "First question")
        self.assertEqual(by_id[old_frame["id"]]["message_count"], 2)
        self.assertEqual(by_id[new_frame["id"]]["agent_id"], "claude")

    def test_conversation_title_can_be_renamed_within_its_project(self) -> None:
        project = portal_store.create_project(name="Frames")
        other_project = portal_store.create_project(name="Other")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Review rs429358 and APOE evidence",
            agent_id="codex",
        )
        assert frame is not None

        renamed = portal_store.rename_frame(
            project["project_id"],
            str(frame["id"]),
            "  APOE   variant review  ",
        )

        self.assertEqual(renamed["title"], "APOE variant review")
        self.assertEqual(portal_store.public_frame(portal_store.get_frame(str(frame["id"])))["title"], "APOE variant review")
        self.assertEqual(portal_store.list_project_frames(project["project_id"])["frames"][0]["title"], "APOE variant review")
        self.assertIsNone(portal_store.rename_frame(other_project["project_id"], str(frame["id"]), "Wrong project"))

    def test_conversation_title_is_prompt_safe_and_bounded(self) -> None:
        project = portal_store.create_project(name="Frames")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Review context_file=/Users/example/private.json " + ("evidence " * 30),
            agent_id="codex",
        )
        assert frame is not None

        title = portal_store.public_frame(frame)["title"]

        self.assertLessEqual(len(title), portal_store.MAX_CONVERSATION_TITLE_LENGTH)
        self.assertIn("context file: [redacted local path]", title)
        self.assertNotIn("/Users/example", title)

    def test_selected_material_new_conversation_records_public_handoff(self) -> None:
        project = portal_store.create_project(name="Focused conversation")
        source_frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Build CYP2C19 report",
            agent_id="codex",
        )
        assert source_frame is not None

        focused_frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Use this file to draft the limitations section.",
            agent_id="codex",
            selected_evidence=[
                {
                    "id": "file-1",
                    "label": "Project file: reports/cyp2c19.md",
                    "text": "CYP2C19 report excerpt",
                    "source_operation": "genomi.portal.workspace_file",
                }
            ],
            started_from_selected_material=True,
            source_frame_id=str(source_frame["id"]),
        )
        assert focused_frame is not None

        stored = portal_store.get_frame(str(focused_frame["id"]))
        frames = portal_store.list_project_frames(project["project_id"])
        public = portal_store.public_frame(stored)
        focused_summary = next(frame for frame in frames["frames"] if frame["id"] == focused_frame["id"])

        self.assertIsNone(stored["parent_frame_id"])
        self.assertEqual(stored["input_data"]["started_from"]["source_frame_id"], source_frame["id"])
        self.assertEqual(
            focused_summary["started_from"],
            {
                "kind": "selected_material",
                "summary": "Started from Project file: reports/cyp2c19.md",
                "material_count": 1,
                "labels": ["Project file: reports/cyp2c19.md"],
            },
        )
        self.assertEqual(public["started_from"], focused_summary["started_from"])
        self.assertNotIn("source_frame_id", json.dumps(focused_summary["started_from"]))
        _assert_public_payload(public)

    def test_selected_material_handoff_ignores_cross_project_source_frame(self) -> None:
        project = portal_store.create_project(name="Focused conversation")
        other_project = portal_store.create_project(name="Other")
        other_frame = portal_store.create_frame(
            project_id=other_project["project_id"],
            request="Other conversation",
            agent_id="codex",
        )
        assert other_frame is not None

        focused_frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Start from selected material.",
            agent_id="codex",
            selected_evidence=[{"id": "ev-1", "label": "Selected artifact", "text": "Artifact excerpt"}],
            started_from_selected_material=True,
            source_frame_id=str(other_frame["id"]),
        )
        assert focused_frame is not None

        stored = portal_store.get_frame(str(focused_frame["id"]))

        self.assertEqual(stored["input_data"]["started_from"]["summary"], "Started from Selected artifact")
        self.assertNotIn("source_frame_id", stored["input_data"]["started_from"])

    def test_project_artifacts_persist_and_update_count(self) -> None:
        project = portal_store.create_project(name="Dashboard")
        artifact = portal_store.add_artifact(
            project["project_id"],
            kind="decode_dashboard",
            renderer="decode_dashboard",
            title="Genomi Dashboard",
            operation="decode.render_dashboard",
            result={
                "status": "completed",
                "dashboard_path": "/tmp/dashboard.html",
                "panels_rendered": ["clinvar"],
                "panels_empty": ["prs"],
                "serve": {"url": "http://127.0.0.1:9000/dashboard.html"},
            },
            external_url="http://127.0.0.1:9000/dashboard.html",
        )

        artifacts = portal_store.list_project_artifacts(project["project_id"])
        reloaded_project = portal_store.get_project(project["project_id"])

        self.assertEqual(reloaded_project["artifact_count"], 1)
        self.assertEqual(artifacts["artifacts"][0]["id"], artifact["id"])
        self.assertEqual(artifacts["artifacts"][0]["kind"], "decode_dashboard")
        self.assertEqual(artifacts["artifacts"][0]["renderer"], "decode_dashboard")
        self.assertEqual(artifacts["artifacts"][0]["url"], "http://127.0.0.1:9000/dashboard.html")
        self.assertIsNone(artifacts["artifacts"][0]["preview_url"])
        self.assertIsNone(artifacts["artifacts"][0]["latest_version_id"])
        self.assertEqual(artifacts["artifacts"][0]["version_count"], 0)
        self.assertIsNone(artifacts["artifacts"][0]["latest_version"])
        self.assertEqual(artifacts["artifacts"][0]["summary_lines"], ["completed", "decode.render_dashboard"])
        self.assertEqual(artifacts["artifacts"][0]["open_label"], "Open result")
        self.assertFalse(artifacts["artifacts"][0]["starred"])
        self.assertFalse(artifacts["artifacts"][0]["hidden"])
        self.assertEqual(
            set(artifacts["artifacts"][0]),
            {
                "id",
                "project_id",
                "kind",
                "renderer",
                "title",
                "operation",
                "status",
                "artifact_presentation",
                "starred",
                "hidden",
                "url",
                "preview_url",
                "summary",
                "summary_lines",
                "open_label",
                "latest_version_id",
                "version_count",
                "latest_version",
                "created_at",
                "updated_at",
            },
        )
        self.assertEqual(artifacts["artifacts"][0]["artifact_presentation"]["schema"], "genomi_portal_artifact_presentation")
        self.assertEqual(artifacts["artifacts"][0]["artifact_presentation"]["family"], "legacy_report")
        self.assertEqual(artifacts["artifacts"][0]["artifact_presentation"]["surface_copy"]["use_label"], "Use report")
        self.assertNotIn("result", portal_store.get_artifact(artifact["id"]))
        _assert_public_payload(artifacts)

    def test_project_artifact_without_external_server_gets_portal_file_url(self) -> None:
        project = portal_store.create_project(name="Dashboard")
        source = self.genomi_home / "dashboard.html"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("<title>Dashboard</title>", encoding="utf-8")
        artifact = portal_store.add_artifact(
            project["project_id"],
            kind="decode_dashboard",
            renderer="decode_dashboard",
            title="Genomi Dashboard",
            operation="decode.render_dashboard",
            result={"status": "completed", "dashboard_path": "/tmp/dashboard.html"},
            file_path=str(source),
        )

        artifact_file_endpoint = portal_routes.project_artifact_file_endpoint(project["project_id"], str(artifact["id"]))
        self.assertEqual(artifact["url"], artifact_file_endpoint)
        self.assertEqual(artifact["preview_url"], artifact_file_endpoint)
        self.assertEqual(portal_store.get_artifact(artifact["id"])["id"], artifact["id"])
        stored = portal_store.get_artifact(artifact["id"])
        self.assertNotIn("path", stored)
        self.assertNotIn("result", stored)
        self.assertNotIn("latest_version", stored)
        self.assertTrue(stored["latest_version_id"].startswith("ver_"))
        self.assertEqual(stored["version_count"], 1)
        raw_version = portal_store.get_artifact_version(stored["latest_version_id"])
        self.assertEqual(raw_version["filename"], f"{stored['latest_version_id']}.html")
        self.assertNotIn("path", raw_version)
        versions = portal_store.list_project_artifact_versions(project["project_id"], artifact["id"])
        self.assertEqual(versions["latest_version_id"], stored["latest_version_id"])
        self.assertEqual(len(versions["versions"]), 1)
        version = versions["versions"][0]
        self.assertEqual(version["version_id"], stored["latest_version_id"])
        self.assertEqual(version["artifact_id"], artifact["id"])
        self.assertEqual(version["content_type"], "text/html")
        self.assertEqual(version["size_bytes"], len("<title>Dashboard</title>"))
        self.assertTrue(version["checksum"].startswith("sha256:"))
        self.assertEqual(
            version["file_url"],
            portal_routes.project_artifact_version_file_endpoint(project["project_id"], artifact["id"], stored["latest_version_id"]),
        )
        self.assertNotIn("path", version)
        public = portal_store.list_project_artifacts(project["project_id"])["artifacts"][0]
        self.assertEqual(public["url"], artifact_file_endpoint)
        self.assertEqual(public["preview_url"], artifact_file_endpoint)
        self.assertEqual(public["latest_version"]["version_id"], stored["latest_version_id"])
        self.assertEqual(public["latest_version"]["content_type"], "text/html")
        self.assertTrue(public["latest_version"]["checksum"].startswith("sha256:"))
        self.assertEqual(public["latest_version"]["file_url"], version["file_url"])
        self.assertNotIn("path", public["latest_version"])
        _assert_public_payload(public)

    def test_project_artifact_detail_exposes_public_reproduction_recipe(self) -> None:
        project = portal_store.create_project(name="Evidence")
        source = self.genomi_home / "evidence.html"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("<title>Evidence</title>", encoding="utf-8")
        reproduction = portal_artifact_reproduction.operation_rebuild_recipe(
            operation="research.build_target_packet",
            renderer="evidence_packet",
            params={
                "target_type": "topic",
                "topic": "rs429358",
                "limit": 6,
                "agi_path": "/Users/matthewzmd/private/genome.sqlite",
                "dashboard_path": "/tmp/dashboard.html",
                "shared_evidence_db": "/Users/matthewzmd/private/evidence.sqlite",
                "note": "derived from /private/tmp/rebuild-input.json",
            },
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

        summary = portal_store.list_project_artifacts(project["project_id"])["artifacts"][0]
        stored = portal_store.get_artifact(artifact["id"])
        raw_version = portal_store.get_artifact_version(stored["latest_version_id"])
        version_summary = portal_store.public_artifact_version_summary(raw_version)
        version_detail = portal_store.public_artifact_version_detail(raw_version)
        versions = portal_store.list_project_artifact_versions(project["project_id"], artifact["id"])["versions"]
        detail = portal_store.public_artifact_detail(stored)
        metadata = portal_artifact_exports.project_artifact_metadata_bundle(project["project_id"], artifact["id"])

        self.assertNotIn("reproduction", summary)
        self.assertNotIn("reproduction", summary["latest_version"])
        self.assertNotIn("review", summary["latest_version"])
        self.assertNotIn("environment", summary)
        self.assertNotIn("environment", summary["latest_version"])
        self.assertNotIn("reproduction", stored)
        self.assertNotIn("review", stored)
        self.assertNotIn("environment", stored)
        self.assertIn("reproduction", raw_version)
        self.assertIn("review", raw_version)
        self.assertIn("environment", raw_version)
        self.assertNotIn("reproduction", version_summary)
        self.assertNotIn("review", version_summary)
        self.assertNotIn("environment", version_summary)
        self.assertEqual(version_summary["version_id"], stored["latest_version_id"])
        recipe = detail["reproduction"]
        self.assertEqual(recipe, raw_version["reproduction"])
        self.assertEqual(recipe, version_detail["reproduction"])
        self.assertEqual(recipe, versions[0]["reproduction"])
        self.assertEqual(recipe["status"], "partial_private_parameters_redacted")
        self.assertEqual(recipe["operation"], "research.build_target_packet")
        self.assertEqual(recipe["params"]["topic"], "rs429358")
        self.assertNotIn("agi_path", recipe["params"])
        self.assertNotIn("dashboard_path", recipe["params"])
        self.assertNotIn("shared_evidence_db", recipe["params"])
        self.assertTrue(recipe["params_redacted"])
        self.assertNotIn("commands", recipe)
        self.assertNotIn("script", recipe)
        self.assertIn("redacted parameters", " ".join(recipe["limitations"]))
        review = detail["review"]
        self.assertEqual(summary["review"], raw_version["review"])
        self.assertEqual(review, raw_version["review"])
        self.assertEqual(review, version_detail["review"])
        self.assertEqual(review, versions[0]["review"])
        self.assertEqual(review["kind"], "artifact_version_review")
        self.assertEqual(review["status"], "warning")
        self.assertEqual(review["counts"]["failed"], 0)
        self.assertEqual(
            {check["check_id"] for check in review["checks"]},
            {"artifact_file_snapshot", "evidence_envelope_present", "rebuild_recipe", "public_payload_safety"},
        )
        self.assertEqual(
            next(check for check in review["checks"] if check["check_id"] == "rebuild_recipe")["status"],
            "warning",
        )
        self.assertEqual(
            next(check for check in review["checks"] if check["check_id"] == "public_payload_safety")["observed"],
            {"redacted": False},
        )
        self.assertIn("not clinical validation", " ".join(review["limitations"]))
        environment = detail["environment"]
        self.assertEqual(environment, raw_version["environment"])
        self.assertEqual(environment, version_detail["environment"])
        self.assertEqual(environment, versions[0]["environment"])
        self.assertEqual(environment["kind"], "artifact_environment_snapshot")
        self.assertEqual(environment["operation"], "research.build_target_packet")
        self.assertEqual(environment["renderer"], "evidence_packet")
        self.assertEqual(environment["artifact_kind"], "evidence_packet")
        self.assertEqual(environment["runtime"]["genomi_version"], "0.1.0")
        self.assertIn("python_version", environment["runtime"])
        self.assertIn("genomi", {package["name"] for package in environment["packages"]})
        self.assertIn("library_count", environment["libraries"]["summary"])
        self.assertNotIn("reproduction", metadata["artifact"])
        self.assertEqual(metadata["versions"]["items"][0]["environment"], environment)
        self.assertEqual(metadata["versions"]["items"][0]["reproduction"], recipe)
        self.assertEqual(metadata["versions"]["items"][0]["review"], review)
        _assert_public_payload(detail)
        _assert_public_payload(version_detail)
        _assert_public_payload(metadata)

    def test_artifact_version_persists_producing_work_step_from_origin(self) -> None:
        project = portal_store.create_project(name="Producing work")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Build an APOE evidence report",
            agent_id="codex",
        )
        assert frame is not None
        portal_store.finish_frame(str(frame["id"]), status="completed", output="Report ready", run_id="run-produce")
        source = self.genomi_home / "apoe-report.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# APOE report\n", encoding="utf-8")

        artifact = portal_store.add_artifact(
            project["project_id"],
            kind="evidence_packet",
            renderer="evidence_packet",
            title="APOE evidence report",
            operation="research.build_target_packet",
            result={"status": "completed", "headline": "APOE evidence ready"},
            frame_id=str(frame["id"]),
            file_path=str(source),
            summary_lines=["APOE evidence ready", "/Users/matthewzmd/private/input.json"],
        )
        assert artifact is not None
        stored = portal_store.get_artifact(artifact["id"])
        raw_version = portal_store.get_artifact_version(stored["latest_version_id"])
        summary = portal_store.public_artifact_summary(stored)
        detail = portal_store.public_artifact_detail(stored)
        version_detail = portal_store.public_artifact_version_detail(raw_version)

        work_step = raw_version["producing_work_step"]
        self.assertEqual(work_step["kind"], "artifact_producing_work_step")
        self.assertEqual(work_step["title"], "Produced artifact")
        self.assertEqual(work_step["status"], "completed")
        self.assertEqual(work_step["summary"], "APOE evidence ready")
        self.assertEqual(work_step["artifact"], {"title": "APOE evidence report", "kind": "evidence_packet"})
        self.assertEqual(work_step["source"]["label"], "Assistant run")
        self.assertEqual(work_step["source"]["operation"], "research.build_target_packet")
        self.assertEqual(work_step["origin"]["frame_id"], frame["id"])
        self.assertEqual(work_step["origin"]["run_id"], "run-produce")
        self.assertIn(f"/projects/{project['project_id']}/frames/{frame['id']}", work_step["workspace_route"])
        self.assertEqual(summary["latest_version"]["producing_work_step"], work_step)
        self.assertEqual(detail["latest_version"]["producing_work_step"], work_step)
        self.assertEqual(version_detail["producing_work_step"], work_step)
        self.assertNotIn("/Users", json.dumps(work_step))
        _assert_public_payload(detail)
        _assert_public_payload(version_detail)

        updated = portal_store.attach_artifact_producing_event(artifact["id"], run_id="run-produce", event_id=9)
        assert updated is not None
        anchored_version = portal_store.get_artifact_version(stored["latest_version_id"])
        anchored_step = anchored_version["producing_work_step"]
        self.assertEqual(anchored_step["execution_cell"], {"id": "run-produce:artifact:9", "kind": "artifact", "event_ids": [9]})
        self.assertIn("highlight_run=run-produce", anchored_step["workspace_route"])
        self.assertIn("highlight_step=run-produce%3Aartifact%3A9", anchored_step["workspace_route"])
        anchored_detail = portal_store.public_artifact_detail(portal_store.get_artifact(artifact["id"]))
        self.assertEqual(anchored_detail["latest_version"]["producing_work_step"], anchored_step)
        self.assertNotIn("/Users", json.dumps(anchored_step))
        _assert_public_payload(anchored_detail)

    def test_artifact_environment_snapshot_exposes_host_agent_and_omits_library_paths(self) -> None:
        project = portal_store.create_project(name="Evidence")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Build report",
            agent_id="codex",
        )
        source = self.genomi_home / "environment.html"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("<title>Environment</title>", encoding="utf-8")
        assert frame is not None
        fake_inventory = {
            "genomi_home": "/Users/matthewzmd/private/genomi-home",
            "summary": {
                "library_count": 2,
                "installed_count": 1,
                "missing_count": 1,
                "manual_source_required_count": 0,
                "not_applicable_count": 0,
            },
            "libraries": [
                {
                    "library": "clinvar-grch38",
                    "title": "ClinVar",
                    "kind": "offline",
                    "status": "installed",
                    "installed": True,
                    "size_class": "/Users/matthewzmd/private/clinvar.vcf.gz 180 MB",
                    "required_paths": ["/Users/matthewzmd/private/clinvar.vcf.gz"],
                    "existing_paths": ["/Users/matthewzmd/private/clinvar.vcf.gz"],
                },
                {
                    "library": "hpo",
                    "title": "HPO",
                    "kind": "offline",
                    "status": "not_installed",
                    "installed": False,
                    "missing_paths": ["/tmp/hpo.tsv"],
                },
            ],
        }

        with mock.patch("genomi.interfaces.portal_artifact_environment.library_manager.inventory", return_value=fake_inventory):
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

        detail = portal_store.public_artifact_detail(portal_store.get_artifact(artifact["id"]))
        environment = detail["environment"]

        self.assertEqual(environment["host_agent"], {"agent_id": "codex"})
        self.assertEqual(environment["libraries"]["summary"]["library_count"], 2)
        self.assertEqual(environment["libraries"]["summary"]["missing_count"], 1)
        self.assertEqual([item["library"] for item in environment["libraries"]["items"]], ["clinvar-grch38", "hpo"])
        self.assertNotIn("required_paths", json.dumps(environment))
        self.assertNotIn("genomi_home", json.dumps(environment))
        self.assertNotIn("[redacted local path]", json.dumps(environment))
        _assert_public_payload(environment)

    def test_artifact_version_review_run_appends_public_check_history(self) -> None:
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
            result={
                "status": "completed",
                "evidence_envelope": {
                    "finding_state": "evidence_present",
                    "answer_readiness": "scoped_answer_only",
                },
            },
            file_path=str(source),
            summary={
                "evidence_envelope": {
                    "finding_state": "evidence_present",
                    "answer_readiness": "scoped_answer_only",
                }
            },
        )
        assert artifact is not None
        version_id = artifact["latest_version_id"]

        result = portal_store.run_project_artifact_version_review(project["project_id"], artifact["id"], version_id)
        stored_version = portal_store.get_artifact_version(version_id)
        assert stored_version is not None
        version_detail = portal_store.public_artifact_version_detail(stored_version)

        assert result is not None
        self.assertEqual(result["review_run"]["kind"], "artifact_review_run")
        self.assertEqual(result["review_run"]["status"], "completed")
        self.assertEqual(result["review_run"]["check_status"], result["version"]["review"]["status"])
        self.assertEqual(result["review_run"]["version_id"], version_id)
        self.assertEqual(len(stored_version["review_runs"]), 1)
        self.assertEqual(version_detail["review"]["review_runs"][0]["status"], "completed")
        self.assertEqual(version_detail["review"]["review_runs"][0]["check_status"], version_detail["review"]["status"])
        self.assertNotIn("review_runs", portal_store.public_artifact_version_summary(stored_version))
        self.assertIsNone(portal_store.run_project_artifact_version_review("wrong-project", artifact["id"], version_id))
        _assert_public_payload(result)
        _assert_public_payload(version_detail)

    def test_artifact_review_pending_run_is_public_lifecycle_state(self) -> None:
        pending = portal_artifact_review.artifact_review_run_pending(
            review_run_id="rev_pending",
            version={"version_id": "ver_pending"},
            started_at="2026-07-04T12:00:00Z",
        )

        self.assertEqual(pending["kind"], "artifact_review_run")
        self.assertEqual(pending["status"], "running")
        self.assertEqual(pending["check_status"], "running")
        self.assertEqual(pending["version_id"], "ver_pending")
        self.assertEqual(pending["started_at"], "2026-07-04T12:00:00Z")
        self.assertNotIn("completed_at", pending)
        _assert_public_payload(pending)

    def test_artifact_public_fields_are_redacted_before_review_and_metadata(self) -> None:
        project = portal_store.create_project(name="Evidence")
        source = self.genomi_home / "public-fields.html"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("<title>Evidence</title>", encoding="utf-8")
        artifact = portal_store.add_artifact(
            project["project_id"],
            kind="evidence_packet",
            renderer="evidence_packet",
            title="Evidence report from /Users/matthewzmd/private/report.html",
            operation="research.build_target_packet",
            result={"status": "completed"},
            file_path=str(source),
            summary={"headline": "Source file /private/tmp/input.json"},
            summary_lines=["completed", "input /tmp/private-input.json"],
            open_label="Open /Users/matthewzmd/private/report.html",
        )
        assert artifact is not None

        listed = portal_store.list_project_artifacts(project["project_id"])["artifacts"][0]
        detail = portal_store.public_artifact_detail(portal_store.get_artifact(artifact["id"]))
        metadata = portal_artifact_exports.project_artifact_metadata_bundle(project["project_id"], artifact["id"])
        version = portal_store.get_artifact_version(artifact["latest_version_id"])
        assert metadata is not None
        assert version is not None
        safety = next(check for check in version["review"]["checks"] if check["check_id"] == "public_payload_safety")

        self.assertEqual(artifact["title"], "Evidence report from [redacted local path]")
        self.assertEqual(artifact["open_label"], "Open [redacted local path]")
        self.assertEqual(artifact["summary"]["headline"], "Source file [redacted local path]")
        self.assertEqual(artifact["summary_lines"], ["completed", "input [redacted local path]"])
        self.assertEqual(listed["title"], artifact["title"])
        self.assertEqual(detail["open_label"], artifact["open_label"])
        self.assertEqual(metadata["artifact"]["summary_lines"], artifact["summary_lines"])
        self.assertEqual(safety["status"], "warning")
        self.assertEqual(safety["observed"], {"redacted": True})
        _assert_public_payload(listed)
        _assert_public_payload(detail)
        _assert_public_payload(metadata)

    def test_public_reproduction_allowlist_blocks_redacted_executable_recipe(self) -> None:
        public = portal_artifact_reproduction.public_reproduction(
            {
                "status": "ready",
                "kind": "operation_rebuild_recipe",
                "artifact_family": "evidence_report",
                "operation": "research.build_target_packet",
                "renderer": "evidence_packet",
                "params": {
                    "topic": "rs429358",
                    "agi_path": "/Users/matthewzmd/private/genome.sqlite",
                    "nested": {"dashboard_path": "/tmp/dashboard.html", "public": "kept"},
                },
                "params_redacted": False,
                "commands": [
                    {
                        "label": "Unsafe command",
                        "language": "shell",
                        "command": "genomi call research.build_target_packet --shared_evidence_db /tmp/evidence.sqlite",
                        "purpose": "Uses /Users/matthewzmd/private/input.json",
                        "arbitrary": "must not leak",
                    }
                ],
                "script": "genomi call research.build_target_packet --dashboard_path /tmp/dashboard.html",
                "host_agent": {
                    "tool": "research.build_target_packet",
                    "params": {"topic": "rs429358", "shared_evidence_db": "/tmp/evidence.sqlite"},
                    "instruction": "Use agi_path=/Users/matthewzmd/private/genome.sqlite before rerun.",
                    "arbitrary": "/Users/matthewzmd/private/host-agent.txt",
                },
                "limitations": ["Original command used dashboard_path=/tmp/dashboard.html."],
                "arbitrary": "/Users/matthewzmd/private/top-level.txt",
                "result": {"path": "/tmp/result.json"},
            }
        )
        assert public is not None

        self.assertEqual(public["status"], "partial_private_parameters_redacted")
        self.assertEqual(set(public), {"status", "kind", "artifact_family", "operation", "renderer", "params", "params_redacted", "host_agent", "limitations"})
        self.assertEqual(public["params"], {"topic": "rs429358", "nested": {"public": "kept"}})
        self.assertEqual(public["host_agent"]["params"], {"topic": "rs429358"})
        self.assertNotIn("commands", public)
        self.assertNotIn("script", public)
        self.assertNotIn("arbitrary", json.dumps(public))
        _assert_public_payload(public)

    def test_project_artifact_actions_update_and_delete_version_files(self) -> None:
        project = portal_store.create_project(name="Artifacts")
        source = self.genomi_home / "evidence.html"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("<title>Evidence</title>", encoding="utf-8")
        artifact = portal_store.add_artifact(
            project["project_id"],
            kind="evidence_packet",
            renderer="evidence_packet",
            title="Evidence report",
            operation="research.build_target_packet",
            result={"status": "completed"},
            file_path=str(source),
        )
        version_id = portal_store.get_artifact(artifact["id"])["latest_version_id"]
        version_path = portal_store.project_artifact_version_file_path(project["project_id"], artifact["id"], version_id)
        assert version_path is not None
        self.assertTrue(version_path.is_file())

        renamed = portal_store.rename_project_artifact(
            project["project_id"],
            artifact["id"],
            title="Renamed evidence report",
        )
        assert renamed is not None
        starred = portal_store.set_project_artifact_starred(project["project_id"], artifact["id"], True)
        hidden = portal_store.set_project_artifact_hidden(project["project_id"], artifact["id"], True)
        assert starred is not None
        assert hidden is not None
        listed = portal_store.list_project_artifacts(project["project_id"])["artifacts"][0]

        self.assertEqual(renamed["title"], "Renamed evidence report")
        self.assertTrue(starred["starred"])
        self.assertTrue(hidden["hidden"])
        self.assertEqual(listed["title"], "Renamed evidence report")
        self.assertTrue(listed["starred"])
        self.assertTrue(listed["hidden"])
        self.assertIsNone(portal_store.rename_project_artifact("wrong-project", artifact["id"], title="Wrong"))
        self.assertIsNone(portal_store.set_project_artifact_starred("wrong-project", artifact["id"], False))
        self.assertIsNone(portal_store.set_project_artifact_hidden("wrong-project", artifact["id"], False))

        metadata = portal_artifact_exports.project_artifact_metadata_bundle(project["project_id"], artifact["id"])
        assert metadata is not None
        self.assertEqual(metadata["schema"], "genomi_portal_artifact_metadata")
        self.assertEqual(metadata["artifact"]["id"], artifact["id"])
        self.assertEqual(metadata["artifact"]["title"], "Renamed evidence report")
        self.assertTrue(metadata["artifact"]["starred"])
        self.assertTrue(metadata["artifact"]["hidden"])
        self.assertEqual(
            set(metadata["artifact"]),
            {
                "id",
                "project_id",
                "kind",
                "renderer",
                "title",
                "operation",
                "status",
                "starred",
                "hidden",
                "url",
                "preview_url",
                "open_label",
                "summary",
                "summary_lines",
            },
        )
        self.assertEqual(metadata["versions"]["latest_version_id"], version_id)
        self.assertEqual(metadata["versions"]["version_count"], 1)
        self.assertEqual(metadata["versions"]["items"][0]["version_id"], version_id)
        self.assertEqual(
            set(metadata["versions"]["items"][0]),
            {
                "version_id",
                "artifact_id",
                "project_id",
                "created_at",
                "content_type",
                "filename",
                "checksum",
                "size_bytes",
                "is_intermediate",
                "file_url",
                "environment",
                "review",
            },
        )
        self.assertIsNone(portal_artifact_exports.project_artifact_metadata_bundle("wrong-project", artifact["id"]))
        _assert_public_payload(metadata)

        deleted = portal_store.delete_project_artifact(project["project_id"], artifact["id"])
        reloaded_project = portal_store.get_project(project["project_id"])

        self.assertEqual(deleted["id"], artifact["id"])
        self.assertIsNone(portal_store.get_project_artifact(project["project_id"], artifact["id"]))
        self.assertIsNone(portal_store.get_artifact_version(version_id))
        self.assertFalse(version_path.exists())
        self.assertEqual(reloaded_project["artifact_count"], 0)
        self.assertEqual(portal_store.list_project_artifacts(project["project_id"])["artifacts"], [])

    def test_artifact_snapshot_is_removed_when_state_commit_fails(self) -> None:
        project = portal_store.create_project(name="Dashboard")
        source = self.genomi_home / "dashboard.html"
        source.write_text("<title>Dashboard</title>", encoding="utf-8")
        original_write = portal_state._write_state_unlocked

        def fail_artifact_commit(state: dict[str, object], root: object = None) -> None:
            if state.get("artifacts"):
                raise OSError("state write failed")
            original_write(state, root)

        with mock.patch.object(portal_state, "_write_state_unlocked", side_effect=fail_artifact_commit):
            with self.assertRaises(OSError):
                portal_store.add_artifact(
                    project["project_id"],
                    kind="decode_dashboard",
                    renderer="decode_dashboard",
                    title="Genomi Dashboard",
                    operation="decode.render_dashboard",
                    result={"status": "completed"},
                    file_path=str(source),
                )

        version_dir = portal_store.artifacts_dir(project["project_id"]) / "versions"
        remaining = list(version_dir.iterdir()) if version_dir.exists() else []
        self.assertEqual(remaining, [])
        self.assertEqual(portal_store.list_project_artifacts(project["project_id"])["artifacts"], [])

    def test_decode_artifact_keeps_external_open_url_and_same_origin_preview_url(self) -> None:
        project = portal_store.create_project(name="Dashboard")
        source = self.genomi_home / "dashboard.html"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("<title>Dashboard</title>", encoding="utf-8")

        artifact = portal_decode_artifacts.add_decode_dashboard_artifact(
            project["project_id"],
            {
                "status": "completed",
                "dashboard_path": str(source),
                "panels_rendered": ["clinvar"],
                "panels_empty": ["prs"],
                "evidence_build": {
                    "panels_ready": ["clinvar"],
                    "panels_empty": ["prs"],
                    "panels_blocked": ["ancestry"],
                    "panels_running": ["nutrigenomics"],
                    "panels_failed": {"rare_disease": {"status": "failed", "reason": "library unavailable"}},
                    "panel_states": {"clinvar": {"status": "ready", "count": 3}},
                },
                "serve": {"url": "http://127.0.0.1:9000/dashboard.html"},
            },
        )
        assert artifact is not None

        public = portal_store.list_project_artifacts(project["project_id"])["artifacts"][0]
        endpoint = portal_routes.project_artifact_file_endpoint(project["project_id"], str(artifact["id"]))
        self.assertEqual(public["title"], "Genomi Report")
        self.assertEqual(public["open_label"], "Open report")
        self.assertEqual(public["summary_lines"][:3], ["completed", "1 section rendered", "1 empty"])
        self.assertEqual(public["url"], "http://127.0.0.1:9000/dashboard.html")
        self.assertEqual(public["preview_url"], endpoint)
        self.assertEqual(artifact["preview_url"], endpoint)
        evidence_build = public["summary"]["evidence_build"]
        self.assertEqual(evidence_build["panels_ready"], ["clinvar"])
        self.assertEqual(evidence_build["panels_empty"], ["prs"])
        self.assertEqual(evidence_build["panels_blocked"], ["ancestry"])
        self.assertEqual(evidence_build["panels_running"], ["nutrigenomics"])
        self.assertEqual(evidence_build["panels_failed"]["rare_disease"]["status"], "failed")
        self.assertEqual(evidence_build["panel_states"]["clinvar"]["count"], 3)
        _assert_public_payload(public)

    def test_artifact_external_url_rejects_private_or_non_loopback_targets(self) -> None:
        project = portal_store.create_project(name="Dashboard")
        source = self.genomi_home / "dashboard.html"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("<title>Dashboard</title>", encoding="utf-8")

        unsafe_urls = [
            "file:///Users/matthewzmd/private-dashboard.html",
            "/Users/matthewzmd/private-dashboard.html",
            "https://example.com/dashboard.html",
            "http://user:pass@127.0.0.1:9000/dashboard.html",
        ]
        for unsafe_url in unsafe_urls:
            artifact = portal_store.add_artifact(
                project["project_id"],
                kind="decode_dashboard",
                renderer="decode_dashboard",
                title="Genomi Dashboard",
                operation="decode.render_dashboard",
                result={"status": "completed"},
                file_path=str(source),
                external_url=unsafe_url,
            )
            assert artifact is not None
            endpoint = portal_routes.project_artifact_file_endpoint(project["project_id"], str(artifact["id"]))
            public = portal_store.public_artifact_summary(artifact)
            self.assertEqual(artifact["url"], endpoint)
            self.assertEqual(public["url"], endpoint)
            self.assertEqual(public["preview_url"], endpoint)
            _assert_public_payload(public)

    def test_artifact_detail_includes_bounded_origin_frame_messages(self) -> None:
        project = portal_store.create_project(name="Artifact provenance")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Review context_file=/Users/matthewzmd/.genomi/private.json",
            agent_id="codex",
        )
        assert frame is not None
        portal_store.append_message(
            str(frame["id"]),
            role="tool",
            run_id="run-1",
            event={
                "type": "tool_result",
                "name": "variant.resolve",
                "content": "raw result at /tmp/private.sqlite",
                "payload": {
                    "headline": "variant.resolve: data_returned",
                    "agi_path": "/tmp/private.sqlite",
                    "evidence_envelope": {
                        "finding_state": "data_returned",
                        "answer_readiness": "answer_supported",
                    },
                },
            },
        )
        portal_store.finish_frame(str(frame["id"]), status="completed", output="Done from /usr/local/bin/agent", run_id="run-1")
        origin_messages = portal_store.list_frame_messages(str(frame["id"]))["messages"]
        origin_message_ids = [message["id"] for message in origin_messages]
        producing_assistant_message_id = next(
            message["id"] for message in origin_messages if message.get("role") == "assistant"
        )

        artifact = portal_store.add_artifact(
            project["project_id"],
            kind="evidence_packet",
            renderer="evidence_packet",
            title="Evidence report",
            operation="research.build_target_packet",
            result={"status": "completed", "headline": "Evidence ready"},
            frame_id=str(frame["id"]),
        )
        assert artifact is not None
        portal_store.append_message(str(frame["id"]), role="assistant", text="Later message not captured")

        stored = portal_store.get_artifact(artifact["id"])
        summary = portal_store.public_artifact_summary(stored)
        detail = portal_store.public_artifact_detail(stored)
        listed = portal_store.list_project_artifacts(project["project_id"])["artifacts"][0]
        metadata = portal_artifact_exports.project_artifact_metadata_bundle(project["project_id"], artifact["id"])
        assert metadata is not None
        metadata_artifact = metadata["artifact"]

        self.assertEqual(stored["origin"]["frame_id"], frame["id"])
        self.assertEqual(stored["origin"]["message_ids"], origin_message_ids)
        self.assertEqual(stored["origin"]["producing_run_id"], "run-1")
        self.assertEqual(stored["origin"]["producing_assistant_message_id"], producing_assistant_message_id)
        self.assertNotIn("creating_frame_id", stored)
        self.assertNotIn("provenance_messages", summary)
        self.assertNotIn("provenance_messages", listed)
        self.assertEqual(summary["origin_context"]["frame_id"], frame["id"])
        self.assertEqual(summary["origin_context"]["message_ids_count"], 3)
        self.assertEqual(summary["origin_context"]["run_ids"], ["run-1"])
        self.assertEqual(summary["origin_context"]["producing_run_id"], "run-1")
        self.assertEqual(summary["origin_context"]["producing_assistant_message_id"], producing_assistant_message_id)
        self.assertEqual(listed["origin_context"]["run_ids"], ["run-1"])
        self.assertEqual(listed["origin_context"]["producing_run_id"], "run-1")
        self.assertEqual(detail["provenance_messages"]["frame_id"], frame["id"])
        self.assertEqual(detail["provenance_messages"]["total"], 3)
        self.assertEqual(detail["provenance_messages"]["displayed"], 3)
        self.assertEqual([message["role"] for message in detail["provenance_messages"]["messages"]], ["user", "tool", "assistant"])
        self.assertEqual([message["id"] for message in detail["provenance_messages"]["messages"]], origin_message_ids)
        self.assertIn("context file: [redacted local path]", detail["provenance_messages"]["messages"][0]["text"])
        self.assertEqual(detail["provenance_messages"]["messages"][1]["event"]["content"], "variant.resolve: data_returned")
        self.assertEqual(detail["provenance_messages"]["messages"][2]["text"], "Done from [redacted local path]")
        self.assertEqual(metadata_artifact["origin_context"], summary["origin_context"])
        self.assertEqual(metadata_artifact["provenance_messages"]["frame_id"], frame["id"])
        self.assertEqual(metadata_artifact["provenance_messages"]["total"], 3)
        self.assertNotIn("latest_version", metadata_artifact)
        self.assertNotIn("Later message", json.dumps(detail))
        _assert_public_payload(detail)
        _assert_public_payload(metadata)

    def test_tool_only_artifact_origin_persists_producing_run_without_assistant_message(self) -> None:
        project = portal_store.create_project(name="Tool-only artifact provenance")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Render a file artifact",
            agent_id="codex",
        )
        assert frame is not None
        portal_store.append_message(
            str(frame["id"]),
            role="tool",
            run_id="run-tool-only",
            event={
                "type": "tool_result",
                "name": "decode.render_dashboard",
                "content": "dashboard ready",
            },
        )

        artifact = portal_store.add_artifact(
            project["project_id"],
            kind="decode_dashboard",
            renderer="decode_dashboard",
            title="Tool-only dashboard",
            operation="decode.render_dashboard",
            result={"status": "completed"},
            frame_id=str(frame["id"]),
        )
        assert artifact is not None

        stored = portal_store.get_artifact(artifact["id"])
        summary = portal_store.public_artifact_summary(stored)

        self.assertEqual(stored["origin"]["producing_run_id"], "run-tool-only")
        self.assertNotIn("producing_assistant_message_id", stored["origin"])
        self.assertEqual(summary["origin_context"]["run_ids"], ["run-tool-only"])
        self.assertEqual(summary["origin_context"]["producing_run_id"], "run-tool-only")
        self.assertNotIn("producing_assistant_message_id", summary["origin_context"])
        _assert_public_payload(summary)

    def test_artifact_invalid_origin_frame_fails_visibly(self) -> None:
        project = portal_store.create_project(name="Artifact provenance")
        other_project = portal_store.create_project(name="Other")
        other_frame = portal_store.create_frame(
            project_id=other_project["project_id"],
            request="Different project",
            agent_id="codex",
        )
        assert other_frame is not None

        with self.assertRaisesRegex(portal_store.ArtifactOriginError, "not found"):
            portal_store.add_artifact(
                project["project_id"],
                kind="evidence_packet",
                renderer="evidence_packet",
                title="Evidence report",
                operation="research.build_target_packet",
                result={"status": "completed"},
                frame_id="missing-frame",
            )
        with self.assertRaisesRegex(portal_store.ArtifactOriginError, "different project"):
            portal_store.add_artifact(
                project["project_id"],
                kind="evidence_packet",
                renderer="evidence_packet",
                title="Evidence report",
                operation="research.build_target_packet",
                result={"status": "completed"},
                frame_id=str(other_frame["id"]),
            )

        self.assertEqual(portal_store.list_project_artifacts(project["project_id"])["artifacts"], [])

    def test_project_artifact_requires_renderer(self) -> None:
        project = portal_store.create_project(name="Artifacts")

        with self.assertRaises(ValueError):
            portal_store.add_artifact(
                project["project_id"],
                kind="decode_dashboard",
                renderer="",
                title="Genomi Dashboard",
                operation="decode.render_dashboard",
                result={"status": "completed"},
            )

    def test_tool_result_history_is_display_only(self) -> None:
        project = portal_store.create_project(name="Variant review")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Resolve rs429358",
            agent_id="codex",
        )
        assert frame is not None

        portal_store.append_message(
            str(frame["id"]),
            role="tool",
            run_id="run-1",
            event={
                "type": "tool_result",
                "id": "call_1",
                "name": "variant.resolve",
                "content": "raw result at /Users/matthewzmd/.genomi/private.sqlite",
                "payload": {
                    "headline": "variant.resolve: data_returned",
                    "agi_path": "/Users/matthewzmd/.genomi/private.sqlite",
                    "sample_context": {"private": True},
                    "evidence_envelope": {
                        "answer_readiness": "answer_supported",
                        "finding_state": "data_returned",
                    },
                },
            },
        )

        messages = portal_store.list_frame_messages(str(frame["id"]))["messages"]
        stored = json.loads(portal_state.state_path().read_text(encoding="utf-8"))
        event = messages[1]["event"]

        self.assertEqual(event["content"], "variant.resolve: data_returned")
        self.assertEqual(
            set(event),
            {
                "type",
                "id",
                "name",
                "isError",
                "content",
                "ledger",
                "payload",
                "portal_presentation",
                "presentation_state",
                "persisted_display_only",
            },
        )
        self.assertEqual(event["persisted_display_only"], True)
        self.assertEqual(event["presentation_state"], "persisted_redacted")
        self.assertEqual(event["portal_presentation"]["schema"], "genomi_portal_result_presentation")
        self.assertEqual(event["portal_presentation"]["operation"], "variant.resolve")
        self.assertEqual(event["portal_presentation"]["notice"]["title"], "Persisted redacted history")
        self.assertEqual(event["payload"]["headline"], "variant.resolve: data_returned")
        self.assertEqual(event["payload"]["presentation_state"], "persisted_redacted")
        self.assertEqual(event["payload"]["evidence_envelope"]["answer_readiness"], "answer_supported")
        self.assertNotIn("agi_path", event["payload"])
        self.assertNotIn("sample_context", event["payload"])
        self.assertEqual(messages[1]["run_id"], "run-1")
        self.assertEqual(messages[1]["frame_id"], frame["id"])
        self.assertEqual(event["ledger"]["operation"], "variant.resolve")
        self.assertEqual(event["ledger"]["summary"], "variant.resolve: data_returned")
        self.assertEqual(event["ledger"]["answer_readiness"], "answer_supported")
        self.assertEqual(event["ledger"]["finding_state"], "data_returned")
        self.assertEqual(event["ledger"]["presentation_state"], "persisted_redacted")
        self.assertEqual(event["ledger"]["display_only"], True)
        _assert_public_payload(messages)
        _assert_public_payload(stored["messages"])

    def test_public_frame_summary_redacts_request_paths(self) -> None:
        project = portal_store.create_project(name="Frame summaries")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Review context_file=/Users/matthewzmd/.genomi/private.json for rs429358",
            agent_id="codex",
        )
        assert frame is not None

        frames = portal_store.list_project_frames(project["project_id"])["frames"]
        public = portal_store.public_frame(portal_store.get_frame(str(frame["id"])))

        self.assertIn("context file: [redacted local path]", frames[0]["request"])
        self.assertEqual(public["request"], frames[0]["request"])
        self.assertEqual(public["display_request"], frames[0]["request"])
        _assert_public_payload(frames)
        _assert_public_payload(public)

    def test_public_frame_summary_projects_genome_context_only_request(self) -> None:
        project = portal_store.create_project(name="Frame display")
        raw_request = "Internal genome-boundary prompt wording may change."
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request=raw_request,
            agent_id="codex",
            selected_evidence=[
                {
                    "label": "Active genome: GRCh38 · VCF · query-ready genome",
                    "context_kind": "genome_context",
                    "summary": "Active genome ready for this session",
                    "prompt_text": "Active genome / Current genome / Build: GRCh38",
                    "selected_nodes": [{"label": "Current genome / Build", "text": "GRCh38"}],
                    "message_presentation_kind": "genome_context_control",
                }
            ],
        )
        assert frame is not None

        frames = portal_store.list_project_frames(project["project_id"])["frames"]
        public = portal_store.public_frame(portal_store.get_frame(str(frame["id"])))

        self.assertEqual(frames[0]["request"], raw_request)
        self.assertEqual(public["request"], raw_request)
        self.assertEqual(frames[0]["display_request"], "Active genome included")
        self.assertEqual(public["display_request"], "Active genome included")

        untyped_request = "Use this Genomi genome state only as the current-session boundary."
        untyped = portal_store.create_frame(
            project_id=project["project_id"],
            request=untyped_request,
            agent_id="codex",
            selected_evidence=[
                {
                    "label": "Active genome",
                    "context_kind": "genome_context",
                    "prompt_text": "Active genome / Current genome / Build: GRCh38",
                }
            ],
        )
        assert untyped is not None
        self.assertEqual(portal_store.public_frame(untyped)["display_request"], untyped_request)

    def test_public_frame_status_omits_output_body(self) -> None:
        project = portal_store.create_project(name="Variant review")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Resolve rs429358",
            agent_id="codex",
        )
        assert frame is not None
        portal_store.finish_frame(
            str(frame["id"]),
            status="failed",
            output="answer from /Users/matthewzmd/.genomi/private.sqlite",
            error="failed in /usr/local/bin/claude",
            run_id="run-1",
        )

        public = portal_store.public_frame(portal_store.get_frame(str(frame["id"])))

        self.assertEqual(public["status"], "failed")
        self.assertEqual(set(public["output"]), {"error"})
        _assert_public_payload(public)

    def test_state_loader_rejects_schema_marker(self) -> None:
        path = portal_state.state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        original = {
            "schema_version": 999,
            "active_project_id": None,
            "projects": {},
            "frames": {},
            "messages": {},
            "artifacts": {},
            "artifact_versions": {},
        }
        path.write_text(json.dumps(original), encoding="utf-8")

        with self.assertRaises(portal_state.PortalStateError):
            portal_store.ensure_default_project()

        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_state_loader_requires_artifact_versions_section(self) -> None:
        path = portal_state.state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        original = {
            "active_project_id": None,
            "projects": {},
            "frames": {},
            "messages": {},
            "artifacts": {},
        }
        path.write_text(json.dumps(original), encoding="utf-8")

        with self.assertRaises(portal_state.PortalStateError):
            portal_store.ensure_default_project()

        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_state_loader_fails_closed_on_corrupt_json(self) -> None:
        path = portal_state.state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")

        with self.assertRaises(portal_state.PortalStateError):
            portal_store.create_project(name="Should not overwrite corrupt state")

        self.assertEqual(path.read_text(encoding="utf-8"), "{not json")
        self.assertFalse(any(path.parent.glob("state.json.*.tmp")))

    def test_state_loader_fails_closed_on_wrong_section_types(self) -> None:
        path = portal_state.state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        original = {
            "active_project_id": None,
            "projects": [],
            "frames": {},
            "messages": {},
            "artifacts": {},
        }
        path.write_text(json.dumps(original), encoding="utf-8")

        with self.assertRaises(portal_state.PortalStateError):
            portal_store.create_project(name="Should not normalize structurally corrupt state")

        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)
        self.assertFalse(any(path.parent.glob("state.json.*.tmp")))

    def test_streaming_assistant_message_is_updated_not_duplicated(self) -> None:
        project = portal_store.create_project(name="Variant review")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Resolve rs429358",
            agent_id="codex",
        )
        assert frame is not None

        portal_store.upsert_assistant_message(str(frame["id"]), run_id="run-1", text="Partial")
        portal_store.upsert_assistant_message(str(frame["id"]), run_id="run-1", text="Partial answer")
        portal_store.finish_frame(str(frame["id"]), status="completed", output="Final answer", run_id="run-1")

        messages = portal_store.list_frame_messages(str(frame["id"]))["messages"]

        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        self.assertEqual(messages[1]["text"], "Final answer")
        self.assertEqual(messages[1]["run_id"], "run-1")
        self.assertEqual(messages[1]["stream_status"], "completed")

    def test_reconcile_stale_processing_run_marks_frame_and_messages_terminal(self) -> None:
        project = portal_store.create_project(name="Variant review")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Resolve rs429358",
            agent_id="codex",
        )
        assert frame is not None
        frame_id = str(frame["id"])
        portal_store.attach_run(frame_id, run_id="old-run", agent_id="codex")
        portal_store.upsert_assistant_message(frame_id, run_id="old-run", text="Partial answer", stream_status="streaming")
        portal_store.append_message(
            frame_id,
            role="tool",
            run_id="old-run",
            event={"type": "tool_call", "id": "call-1", "name": "variant.resolve", "input": {"rsid": "rs429358"}},
        )

        reconciled = portal_store.reconcile_stale_processing_runs(known_run_ids=set(), run_id="old-run")

        updated = portal_store.get_frame(frame_id)
        public = portal_store.public_frame(updated)
        messages = portal_store.list_frame_messages(frame_id)["messages"]
        self.assertEqual([frame["id"] for frame in reconciled], [frame_id])
        self.assertEqual(updated["status"], portal_store.STALE_AFTER_RESTART_STATUS)
        self.assertEqual(updated["output_data"]["stale_run_id"], "old-run")
        self.assertEqual(updated["output_data"]["stale_run_status"], portal_store.STALE_AFTER_RESTART_STATUS)
        self.assertEqual(public["status"], portal_store.STALE_AFTER_RESTART_STATUS)
        self.assertEqual(public["output"]["stale_run_id"], "old-run")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["stream_status"], portal_store.STALE_AFTER_RESTART_STATUS)
        self.assertEqual(messages[2]["event"]["ledger"]["status"], portal_store.STALE_AFTER_RESTART_STATUS)
        self.assertEqual(messages[3]["role"], "tool")
        self.assertEqual(messages[3]["event"]["type"], "error")
        self.assertEqual(messages[3]["event"]["id"], "call-1")
        self.assertEqual(messages[3]["event"]["ledger"]["status"], "error")
        _assert_public_payload(public)
        _assert_public_payload(messages)

    def test_reconcile_stale_processing_run_keeps_known_in_memory_run_active(self) -> None:
        project = portal_store.create_project(name="Variant review")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Resolve rs429358",
            agent_id="codex",
        )
        assert frame is not None
        portal_store.attach_run(str(frame["id"]), run_id="active-run", agent_id="codex")

        reconciled = portal_store.reconcile_stale_processing_runs(known_run_ids={"active-run"}, run_id="active-run")

        updated = portal_store.get_frame(str(frame["id"]))
        self.assertEqual(reconciled, [])
        self.assertEqual(updated["status"], "processing")
        self.assertEqual(updated["run_id"], "active-run")

    def test_begin_frame_message_recovers_stale_processing_run(self) -> None:
        project = portal_store.create_project(name="Variant review")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Resolve rs429358",
            agent_id="codex",
        )
        assert frame is not None
        portal_store.attach_run(str(frame["id"]), run_id="old-run", agent_id="codex")

        result = portal_store.begin_frame_message(
            str(frame["id"]),
            text="Continue",
            selected_evidence=[{"id": "ev-2", "label": "Selected coverage", "text": "Coverage: ClinVar consulted"}],
            agent_id="codex",
            run_id="new-run",
            recover_stale_run=True,
            project_id=project["project_id"],
        )

        updated = portal_store.get_frame(str(frame["id"]))
        messages = portal_store.list_frame_messages(str(frame["id"]))["messages"]
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(updated["status"], "processing")
        self.assertEqual(updated["run_id"], "new-run")
        self.assertEqual(updated["output_data"]["stale_run_id"], "old-run")
        self.assertEqual(messages[-1]["role"], "user")
        self.assertEqual(messages[-1]["text"], "Continue")
        self.assertEqual(messages[-1]["selected_evidence"][0]["prompt_text"], "Coverage: ClinVar consulted")

    def test_begin_frame_message_rejects_active_processing_run_atomically(self) -> None:
        project = portal_store.create_project(name="Variant review")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Resolve rs429358",
            agent_id="codex",
        )
        assert frame is not None
        portal_store.attach_run(str(frame["id"]), run_id="old-run", agent_id="codex")

        result = portal_store.begin_frame_message(
            str(frame["id"]),
            text="Continue",
            agent_id="codex",
            run_id="new-run",
            recover_stale_run=False,
            project_id=project["project_id"],
        )

        updated = portal_store.get_frame(str(frame["id"]))
        messages = portal_store.list_frame_messages(str(frame["id"]))["messages"]
        self.assertEqual(result["status"], "busy")
        self.assertEqual(updated["run_id"], "old-run")
        self.assertEqual([message["text"] for message in messages if message.get("role") == "user"], ["Resolve rs429358"])

    def test_begin_frame_message_rejects_wrong_project(self) -> None:
        project = portal_store.create_project(name="One")
        other = portal_store.create_project(name="Two")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Resolve rs429358",
            agent_id="codex",
        )
        assert frame is not None

        result = portal_store.begin_frame_message(
            str(frame["id"]),
            text="Continue",
            agent_id="codex",
            run_id="new-run",
            recover_stale_run=False,
            project_id=other["project_id"],
        )

        updated = portal_store.get_frame(str(frame["id"]))
        self.assertEqual(result["status"], "wrong_project")
        self.assertIsNone(updated["run_id"])
        self.assertEqual(updated["status"], "queued")


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
