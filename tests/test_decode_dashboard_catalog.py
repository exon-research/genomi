from __future__ import annotations

import json
import unittest

from genomi.capabilities.decode import dashboard as decode_dashboard
from genomi.operations import (
    OPERATIONS,
    TOOL_CATALOG,
)

_DECODE_BUILDER_PATCH = (
    "genomi.operations.registry.handlers_screen_journal."
    "decode_evidence_builder.build_dashboard_evidence"
)


def _extract_evidence(html: str) -> dict:
    marker = "window.__GENOMI_DASHBOARD__"
    assignment_index = html.find(marker)
    assert assignment_index >= 0, "no __GENOMI_DASHBOARD__ block in HTML"
    json_start = html.find("{", assignment_index)
    assert json_start >= 0, "no __GENOMI_DASHBOARD__ object in HTML"
    parsed, _end = json.JSONDecoder().raw_decode(html[json_start:].replace("<\\/", "</"))
    assert isinstance(parsed, dict), "__GENOMI_DASHBOARD__ is not an object"
    return parsed


def _replace_evidence(html: str, evidence: dict) -> str:
    marker = "window.__GENOMI_DASHBOARD__"
    assignment_index = html.find(marker)
    assert assignment_index >= 0, "no __GENOMI_DASHBOARD__ block in HTML"
    json_start = html.find("{", assignment_index)
    assert json_start >= 0, "no __GENOMI_DASHBOARD__ object in HTML"
    _parsed, json_end = json.JSONDecoder().raw_decode(html[json_start:].replace("<\\/", "</"))
    blob = json.dumps(evidence, ensure_ascii=False).replace("</", "<\\/")
    return html[:json_start] + blob + html[json_start + json_end:]


def _panel_keys(payload: dict) -> set[str]:
    return {key for key in payload if key in decode_dashboard.PANEL_KEYS}


NAV_LABELS = (
    "Overview",
    "Variants",
    "Pharmacogenomics",
    "Risk Scores",
    "Ancestry",
    "Nutrigenomics",
    "Journal",
)


class DashboardCatalogTests(unittest.TestCase):
    def test_dashboard_in_base_catalog(self) -> None:
        names = {op.name for op in OPERATIONS}
        self.assertIn("decode.render_dashboard", names)
        self.assertIn("decode", TOOL_CATALOG["capability_order"])
        self.assertIn("decode", TOOL_CATALOG["namespace_order"])
        self.assertIn("decode", TOOL_CATALOG["capabilities"])
        decode_cap = TOOL_CATALOG["capabilities"]["decode"]
        self.assertIn("decode.render_dashboard", decode_cap["entry_operations"])
        schema_props = TOOL_CATALOG["operations"]["decode.render_dashboard"]["input_schema"]["properties"]
        self.assertEqual(
            set(schema_props),
            {
                "include_pgx",
                "journal_limit",
                "nutrigenomics_domain_ids",
                "output",
                "panels",
                "pgx_timeout_seconds",
                "risk_score_ids",
                "risk_score_limit",
            },
        )
