from __future__ import annotations

import json
import unittest

from genomi.capabilities.decode import dashboard as decode_dashboard
from genomi.interfaces.presentation import present_result

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
    "Risk Review",
    "Ancestry",
    "Nutrigenomics",
)


class DashboardPresentationTests(unittest.TestCase):
    def test_presented_dashboard_result_preserves_artifact_serving_fields(self) -> None:
        raw = {
            "status": "completed",
            "mode": "full",
            "dashboard_path": "/tmp/genomi-dashboards/sample/dashboard.html",
            "panels_rendered": ["overview"],
            "panels_empty": ["pgx"],
            "evidence_build": {
                "panels_ready": ["overview"],
                "panels_empty": ["pgx"],
                "panels_blocked": ["pgx"],
                "panel_states": [{"panel": "pgx", "status": "position_aware_pharmcat_export_required"}],
            },
            "serve": {
                "directory": "/tmp/genomi-dashboards/sample",
                "filename": "dashboard.html",
                "port": 8765,
                "url": "http://127.0.0.1:8765/dashboard.html",
                "command": (
                    "python3 -m http.server 8765 --bind 127.0.0.1 "
                    "--directory /tmp/genomi-dashboards/sample"
                ),
            },
        }

        presented = present_result("decode.render_dashboard", raw)

        self.assertEqual(
            set(presented),
            {"status", "dashboard_path", "panels_rendered", "panels_empty", "evidence_build", "serve"},
        )
        self.assertEqual(presented["dashboard_path"], raw["dashboard_path"])
        self.assertEqual(presented["serve"]["directory"], raw["serve"]["directory"])
        self.assertEqual(presented["serve"]["command"], raw["serve"]["command"])
        self.assertEqual(presented["panels_rendered"], ["overview"])
        self.assertEqual(presented["panels_empty"], ["pgx"])
        self.assertEqual(presented["evidence_build"]["panels_blocked"], ["pgx"])


if __name__ == "__main__":
    unittest.main()
