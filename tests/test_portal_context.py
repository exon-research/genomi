from __future__ import annotations

import re
import unittest
from unittest import mock

from genomi.interfaces import portal_context


_PRIVATE_PATH_RE = re.compile(r"(?:/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes|~)(?:/|$)")
_PRIVATE_KEYS = {"context_file", "registry_file", "agi_path", "dashboard_path", "shared_evidence_db"}


class PortalContextTests(unittest.TestCase):
    def test_context_payload_returns_public_display_contract(self) -> None:
        raw_context = {
            "context_file": "/Users/matthewzmd/.genomi/context.json",
            "context_policy": {"mode": "explicit", "implicit_artifact_selection": False},
            "active_genome_index_access": {"approved": True, "scope": "current_session", "agi_path": "/tmp/private.sqlite"},
            "has_active_genome_index": True,
            "active_user": {"nickname": "Taylor", "user_id": "user-private"},
            "active_genome_index": {
                "agi_id": "agi_1234567890abcdef",
                "sample_slug": "sample-a",
                "status": "completed",
                "genome_build": "GRCh38",
                "source_type": "vcf",
                "agi_source_format": "vcf",
                "agi_source_provider": "local",
                "agi_path": "/Users/matthewzmd/.genomi/private.sqlite",
                "active_genome_index_readiness": {
                    "status": "complete",
                    "complete": True,
                    "variants_ready": True,
                    "agi_path": "/Users/matthewzmd/.genomi/private.sqlite",
                },
            },
            "shared_evidence_db": "/tmp/shared.sqlite",
            "active_genome_index_registry": {
                "registry_file": "/Users/matthewzmd/.genomi/registry.json",
                "known_agi_count": 2,
                "known_user_count": 1,
                "resume_requires": "approval required",
            },
            "context_axes": {
                "active_genome_index": {"current_state": "active_accessible", "known_agis": 2},
                "evidence_context": {"shared_evidence_db": "/tmp/shared.sqlite"},
            },
            "active_response_profile": {"id": "expert", "label": "Expert", "path": "/tmp/profile.json"},
        }

        with mock.patch("genomi.interfaces.portal_context.call_operation", return_value=raw_context):
            payload = portal_context.context_payload()
            prompt_payload = portal_context.prompt_context_payload()
            prompt_section = portal_context.prompt_context_section()

        self.assertEqual(set(payload), {"genomiVersion", "context", "mcp"})
        self.assertEqual(
            set(payload["context"]),
            {
                "status",
                "error",
                "has_active_genome_index",
                "context_policy",
                "active_genome_index_access",
                "active_genome_index",
                "active_genome_index_registry",
                "selection_source",
                "default_auto_selected",
                "context_axes",
                "active_response_profile",
            },
        )
        self.assertTrue(payload["context"]["has_active_genome_index"])
        self.assertEqual(payload["context"]["active_genome_index"]["genome_build"], "GRCh38")
        self.assertEqual(payload["context"]["active_genome_index"]["display_name"], "Taylor")
        self.assertEqual(payload["context"]["active_genome_index"]["source_format"], "vcf")
        self.assertEqual(payload["context"]["active_genome_index"]["source_provider"], "local")
        self.assertEqual(payload["context"]["active_genome_index_registry"]["known_agi_count"], 2)
        _assert_public_payload(payload)
        self.assertEqual(set(prompt_payload), {"genomiVersion", "contextPolicy", "activeGenomeIndex"})
        self.assertNotIn("mcp", prompt_payload)
        self.assertIn("- Genome context: available", prompt_section)
        self.assertIn("- Genome access approved: yes", prompt_section)
        self.assertIn("- Genome build: GRCh38", prompt_section)
        self.assertNotIn("MCP", prompt_section)
        self.assertNotIn("endpoint", prompt_section)
        self.assertNotIn("known_agi_count", prompt_section)
        _assert_public_payload(prompt_payload)

    def test_context_payload_redacts_path_bearing_errors(self) -> None:
        error = RuntimeError('failed reading context_file="/Users/matthewzmd/.genomi/context.json" from /tmp/context.json')

        with mock.patch("genomi.interfaces.portal_context.call_operation", side_effect=error):
            payload = portal_context.context_payload()

        self.assertEqual(payload["context"]["status"], "unavailable")
        self.assertIn("[redacted local path]", payload["context"]["error"])
        self.assertNotIn("/Users", payload["context"]["error"])
        self.assertNotIn("/tmp", payload["context"]["error"])
        _assert_public_payload(payload)


def _assert_public_payload(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in _PRIVATE_KEYS:
                raise AssertionError(f"private key leaked: {key}")
            _assert_public_payload(child)
    elif isinstance(value, list):
        for child in value:
            _assert_public_payload(child)
    elif isinstance(value, str):
        if _PRIVATE_PATH_RE.search(value):
            raise AssertionError(f"private path leaked: {value}")


if __name__ == "__main__":
    unittest.main()
