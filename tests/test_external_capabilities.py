from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from genomi.capabilities.biohub.esmc import compare_protein_embeddings
from genomi.capabilities.paperclip.search import search_biomedical
from genomi.capabilities.proto.tools import run_tool
from genomi.operations.registry.table import call_operation, list_operations
from genomi.runtime.external_credentials import external_credential_session


class ExternalCapabilityTests(unittest.TestCase):
    def test_capabilities_are_focused_and_dispatchable(self) -> None:
        self.assertEqual(
            [tool["name"] for tool in list_operations(capability="paperclip")],
            ["paperclip.search_biomedical"],
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

    def test_biohub_returns_metrics_without_secret_or_embeddings(self) -> None:
        vectors = iter(([1.0, 0.0], [0.8, 0.2]))

        def transport(path: str, payload: dict[str, object], token: str) -> dict[str, object]:
            self.assertEqual(token, "biohub-test-secret")
            if path.endswith("encode"):
                return {"sequence": [1, 2, 3]}
            return {"mean_embedding": list(next(vectors))}

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
