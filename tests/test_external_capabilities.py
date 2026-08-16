from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from genomi.capabilities.biohub.esmc import compare_protein_embeddings
from genomi.capabilities.paperclip.read import retrieve_document_evidence
from genomi.capabilities.paperclip.search import search_biomedical
from genomi.capabilities.proto.tools import run_tool
from genomi.operations.registry.table import call_operation, list_operations
from genomi.runtime.external_credentials import external_credential_session


class ExternalCapabilityTests(unittest.TestCase):
    def test_capabilities_are_focused_and_dispatchable(self) -> None:
        self.assertEqual(
            [tool["name"] for tool in list_operations(capability="paperclip")],
            ["paperclip.search_biomedical", "paperclip.retrieve_document_evidence"],
        )
        with patch("genomi.capabilities.paperclip.search.shutil.which", return_value=None):
            result = call_operation(
                "genomi.invoke",
                {"tool": "paperclip.search_biomedical", "params": {"query": "immune deficiency"}},
            )
        self.assertEqual(result["dispatched_tool"], "paperclip.search_biomedical")
        self.assertIn(result["status"], {"source_unavailable", "completed", "in_scope_empty"})

    def test_paperclip_uses_secret_only_in_child_environment(self) -> None:
        seen: dict[str, object] = {}

        def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            seen["command"] = command
            seen["env"] = kwargs["env"]
            payload = {"results": [{"id": "PMC1", "title": "Public paper", "source": "pmc"}]}
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

        with external_credential_session({"PAPERCLIP_API_KEY": "paperclip-test-secret"}):
            with patch("genomi.capabilities.paperclip.search.shutil.which", return_value="paperclip"):
                result = search_biomedical(query="public question", runner=runner)
        self.assertEqual(result["records"][0]["title"], "Public paper")
        self.assertNotIn("paperclip-test-secret", json.dumps(result))
        self.assertNotIn("paperclip-test-secret", seen["command"])
        self.assertEqual(seen["env"]["PAPERCLIP_API_KEY"], "paperclip-test-secret")

    def test_paperclip_parses_current_cli_search_display(self) -> None:
        display = """Found 1 paper  [s_abc123]

  1. Public mechanism paper
     Ada Author, Ben Researcher
     PMC1234567 · Example Journal · 2024-04-02
     https://doi.org/10.1000/example
     \"A public evidence summary.\"

[20ms, saved to s_abc123]
"""

        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            self.assertNotIn("--json", command)
            return subprocess.CompletedProcess(command, 0, display, "")

        with external_credential_session({"PAPERCLIP_API_KEY": "paperclip-test-secret"}):
            with patch("genomi.capabilities.paperclip.search.shutil.which", return_value="paperclip"):
                result = search_biomedical(query="public question", sources=["pmc"], runner=runner)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result_id"], "s_abc123")
        self.assertEqual(result["records"][0]["record_id"], "PMC1234567")
        self.assertEqual(result["records"][0]["collection"], "papers")
        self.assertEqual(result["records"][0]["doi"], "10.1000/example")

    def test_paperclip_reads_line_pinned_public_evidence(self) -> None:
        seen: list[list[str]] = []

        def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            seen.append(command)
            self.assertEqual(kwargs["env"]["PAPERCLIP_API_KEY"], "paperclip-test-secret")
            if command[1] == "cat":
                payload = {
                    "document_id": "PMC1234567",
                    "title": "Public mechanism paper",
                    "authors": "Ada Author",
                    "doi": "10.1000/example",
                    "source": "pmc",
                }
                return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
            return subprocess.CompletedProcess(
                command,
                0,
                "L16:Mechanistic evidence from the public paper.\nL24:A second public observation.\n",
                "",
            )

        with external_credential_session({"PAPERCLIP_API_KEY": "paperclip-test-secret"}):
            with patch("genomi.capabilities.paperclip.read.shutil.which", return_value="paperclip"):
                result = retrieve_document_evidence(
                    document_id="PMC1234567",
                    collection="papers",
                    patterns=["mechanistic evidence", "public observation"],
                    runner=runner,
                )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["excerpts"][0]["line_start"], 16)
        self.assertEqual(
            result["excerpts"][0]["citation_url"],
            "https://paperclip.gxl.ai/citations/papers/PMC1234567#L16",
        )
        self.assertEqual(seen[0][1], "cat")
        self.assertEqual(seen[1][1], "grep")
        self.assertNotIn("paperclip-test-secret", json.dumps(result))

    def test_biohub_returns_metrics_without_secret_or_embeddings(self) -> None:
        vectors = iter(([1.0, 0.0], [0.8, 0.2]))

        def transport(path: str, payload: dict[str, object], token: str) -> dict[str, object]:
            self.assertEqual(token, "biohub-test-secret")
            if path.endswith("encode"):
                return {"outputs": {"sequence": [1, 2, 3]}}
            return {"mean_embedding": [[list(next(vectors))]]}

        with external_credential_session({"BIOHUB_API_KEY": "biohub-test-secret"}):
            result = compare_protein_embeddings(
                reference_sequence="ACD",
                alternate_sequence="AED",
                sequence_scope="public_reference_or_approved_research_artifact",
                external_transfer_approved=True,
                transport=transport,
            )
        self.assertEqual(result["comparison"]["changed_positions"][0]["position"], 2)
        self.assertNotIn("biohub-test-secret", json.dumps(result))
        self.assertNotIn("mean_embedding", json.dumps(result))

    def test_proto_preserves_result_and_prunes_paths(self) -> None:
        class Native:
            @staticmethod
            def run_tool(**_: object) -> dict[str, object]:
                return {"ok": True, "score": 0.7, "_saved_to": "/private/result.json"}

        with patch("genomi.capabilities.proto.tools._native_tools", return_value=Native()):
            with patch("genomi.capabilities.proto.tools._modal_client", return_value=(object(), object())):
                result = run_tool(
                    tool_key="example-tool",
                    inputs={"value": 1},
                    input_scope="public_or_approved_research_artifact",
                    external_transfer_approved=True,
                )
        self.assertEqual(result["result"]["score"], 0.7)
        self.assertEqual(result["result"]["artifact_state"], "materialized_not_presented")
        self.assertNotIn("/private/result.json", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
