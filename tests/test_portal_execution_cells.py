from __future__ import annotations

import json
import re

from genomi.interfaces import portal_execution_cells


_PRIVATE_PATH_RE = re.compile(r"(?:/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes|~)(?:/|$)")


def test_execution_cells_group_tool_call_and_result_with_event_range() -> None:
    payload = portal_execution_cells.execution_cells_payload(
        [
            {
                "id": 1,
                "event": "status",
                "timestamp": 1000,
                "data": {"status": "queued", "kind": "host_agent"},
            },
            {
                "id": 2,
                "event": "agent",
                "timestamp": 2000,
                "project_id": "proj_1",
                "frame_id": "frame_1",
                "data": {
                    "type": "tool_call",
                    "id": "call_1",
                    "name": "variant.resolve",
                    "input": {"rsid": "rs429358"},
                },
            },
            {
                "id": 3,
                "event": "agent",
                "timestamp": 3000,
                "project_id": "proj_1",
                "frame_id": "frame_1",
                "data": {
                    "type": "tool_result",
                    "id": "call_1",
                    "name": "variant.resolve",
                    "payload": {"headline": "variant.resolve: data_returned"},
                },
            },
            {
                "id": 4,
                "event": "end",
                "timestamp": 4000,
                "data": {"status": "succeeded", "error": None},
            },
        ],
        run_id="run_1",
    )

    assert payload["schema"] == "genomi_portal_execution_cells"
    assert payload["total"] == 2
    assert payload["counts"] == {"completed": 2, "running": 0, "errors": 0}
    tool_cell = payload["items"][0]
    assert tool_cell["id"] == "run_1:tool:call_1"
    assert tool_cell["kind"] == "tool"
    assert tool_cell["title"] == "variant.resolve"
    assert tool_cell["status"] == "completed"
    assert tool_cell["summary"] == "variant.resolve: data_returned"
    assert tool_cell["event_ids"] == [2, 3]
    assert tool_cell["event_range"] == {"first": 2, "last": 3}
    assert tool_cell["project_id"] == "proj_1"
    assert tool_cell["frame_id"] == "frame_1"
    _assert_public_payload(payload)


def test_execution_cells_preserve_diagnostics_streams_artifacts_and_errors() -> None:
    payload = portal_execution_cells.execution_cells_payload(
        [
            {
                "id": 1,
                "event": "agent",
                "timestamp": 1000,
                "data": {"type": "diagnostic", "name": "spawn_agent", "message": "using /Users/private/token"},
            },
            {"id": 2, "event": "stdout", "timestamp": 2000, "data": {"chunk": "installed package\n"}},
            {"id": 3, "event": "stderr", "timestamp": 3000, "data": {"chunk": "warning\n"}},
            {"id": 4, "event": "artifact", "timestamp": 4000, "data": {"artifact_id": "art_1", "title": "APOE report"}},
            {"id": 5, "event": "artifact_error", "timestamp": 5000, "data": {"artifact_id": "art_2", "error": "failed"}},
            {"id": 6, "event": "end", "timestamp": 6000, "data": {"status": "failed", "error": "agent failed"}},
        ],
        run_id="run_streams",
    )

    assert [item["kind"] for item in payload["items"]] == ["diagnostic", "stdout", "stderr", "artifact", "artifact", "run"]
    assert payload["items"][0]["title"] == "Diagnostic: spawn_agent"
    assert payload["items"][0]["summary"] == "Assistant runtime started."
    assert payload["items"][0]["visibility"] == "technical"
    assert payload["items"][1]["summary"] == "installed package\n"
    assert payload["items"][1]["visibility"] == "technical"
    assert payload["items"][2]["visibility"] == "technical"
    assert payload["items"][4]["status"] == "error"
    assert payload["items"][5]["status"] == "error"
    assert payload["counts"] == {"completed": 4, "running": 0, "errors": 2}
    _assert_public_payload(payload)


def test_execution_cells_unpack_nested_artifact_event_for_workspace_navigation() -> None:
    payload = portal_execution_cells.execution_cells_payload(
        [
            {
                "id": 9,
                "event": "artifact",
                "timestamp": 9000,
                "project_id": "proj_1",
                "frame_id": "frame_1",
                "data": {
                    "artifact": {
                        "id": "art_1",
                        "project_id": "proj_1",
                        "title": "APOE evidence report",
                        "kind": "markdown",
                        "status": "completed",
                        "latest_version_id": "ver_1",
                        "version_count": 2,
                    }
                },
            }
        ],
        run_id="run_artifact",
    )

    assert payload["total"] == 1
    cell = payload["items"][0]
    assert cell["kind"] == "artifact"
    assert cell["title"] == "APOE evidence report"
    assert cell["summary"] == "APOE evidence report"
    assert cell["project_id"] == "proj_1"
    assert cell["frame_id"] == "frame_1"
    assert cell["artifact"] == {
        "id": "art_1",
        "project_id": "proj_1",
        "title": "APOE evidence report",
        "kind": "markdown",
        "status": "completed",
        "latest_version_id": "ver_1",
        "version_count": 2,
        "workspace_route": "/projects/proj_1/artifacts/art_1/versions/ver_1",
    }
    _assert_public_payload(payload)


def test_artifact_event_cell_id_matches_artifact_execution_cell_records() -> None:
    payload = portal_execution_cells.execution_cells_payload(
        [
            {
                "id": 9,
                "event": "artifact",
                "timestamp": 9000,
                "project_id": "proj_1",
                "frame_id": "frame_1",
                "data": {"artifact": {"id": "art_1", "project_id": "proj_1", "latest_version_id": "ver_1"}},
            }
        ],
        run_id="run_1",
    )

    self_cell_id = portal_execution_cells.artifact_event_cell_id("run_1", 9)
    assert self_cell_id == "run_1:artifact:9"
    assert payload["items"][0]["id"] == self_cell_id
    assert payload["items"][0]["event_ids"] == [9]


def test_execution_cells_hide_raw_host_wrappers_and_promote_recovered_evidence_headline() -> None:
    payload = portal_execution_cells.execution_cells_payload(
        [
            {
                "id": 1,
                "event": "agent",
                "timestamp": 1000,
                "data": {
                    "type": "tool_call",
                    "id": "call_mcp",
                    "name": "mcp__genomi__genomi_invoke",
                    "input": {"tool": "pharmacogenomics.review_medication"},
                },
            },
            {
                "id": 2,
                "event": "agent",
                "timestamp": 2000,
                "data": {
                    "type": "tool_result",
                    "id": "call_mcp",
                    "content": "Error: result exceeds maximum allowed tokens.",
                },
            },
            {
                "id": 3,
                "event": "agent",
                "timestamp": 3000,
                "data": {
                    "type": "tool_call",
                    "id": "call_bash",
                    "name": "Bash",
                    "input": {"command": "jq .headline"},
                },
            },
            {
                "id": 4,
                "event": "agent",
                "timestamp": 4000,
                "data": {
                    "type": "tool_result",
                    "id": "call_bash",
                    "content": "pharmacogenomics.review_medication: evidence_present · scoped_answer_only",
                },
            },
        ],
        run_id="run_public_pgx",
    )

    assert payload["total"] == 2
    wrapper, recovered = payload["items"]
    assert wrapper["title"] == "mcp__genomi__genomi_invoke"
    assert wrapper["visibility"] == "technical"
    assert recovered["title"] == "pharmacogenomics.review_medication"
    assert recovered["operation"] == "pharmacogenomics.review_medication"
    assert "visibility" not in recovered
    assert recovered["summary"] == "pharmacogenomics.review_medication: evidence_present · scoped_answer_only"


def _assert_public_payload(value: object) -> None:
    text = json.dumps(value)
    if _PRIVATE_PATH_RE.search(text):
        raise AssertionError(f"private path leaked: {text}")
