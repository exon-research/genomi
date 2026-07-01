from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from genomi.capabilities.decode import dashboard as decode_dashboard

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


class DashboardOfflineAssetTests(unittest.TestCase):
    """Guard the offline contract: vendored assets present and compiled JS in sync."""

    _TEMPLATES = (
        Path(decode_dashboard.__file__).resolve().parent / "templates"
    )

    def _compiled_chunks(self) -> list[Path]:
        vendor = self._TEMPLATES / "vendor"
        chunks: list[tuple[int, Path]] = []
        for path in vendor.glob("dashboard.compiled.*.js"):
            match = re.fullmatch(r"dashboard\.compiled\.(\d+)\.js", path.name)
            if match:
                chunks.append((int(match.group(1)), path))
        return [path for _, path in sorted(chunks)]

    def test_vendored_runtime_assets_present(self) -> None:
        vendor = self._TEMPLATES / "vendor"
        for name in ("react.production.min.js", "react-dom.production.min.js"):
            self.assertTrue((vendor / name).is_file(), f"missing vendored asset {name}")
        chunks = self._compiled_chunks()
        self.assertGreaterEqual(len(chunks), 1)
        self.assertEqual(
            [path.name for path in chunks],
            [f"dashboard.compiled.{i:03d}.js" for i in range(1, len(chunks) + 1)],
        )
        for path in chunks:
            self.assertLessEqual(len(path.read_text(encoding="utf-8").splitlines()), 1000)

    def test_template_uses_inline_runtime_placeholders(self) -> None:
        shell = (self._TEMPLATES / "shell.html").read_text(encoding="utf-8")
        scripts = re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", shell, flags=re.DOTALL)
        self.assertEqual(
            [script.strip() for script in scripts],
            [
                "window.__GENOMI_DASHBOARD__ = __GENOMI_EVIDENCE__;",
                "__GENOMI_APP_JS__",
            ],
        )
        self.assertEqual(shell.count("__GENOMI_VENDOR_SCRIPTS__"), 1)

    def test_compiled_js_matches_jsx_source(self) -> None:
        # Drift guard: compiled chunks stamp the sha256 of the dashboard app
        # sources they were built from. If someone edits the JSX/helper sources
        # without re-running scripts/build_dashboard.py, this fails — no JS
        # toolchain needed here.
        import hashlib

        sources = [
            (self._TEMPLATES / "dashboard_helpers.js").read_text(encoding="utf-8"),
            (self._TEMPLATES / "dashboard.jsx").read_text(encoding="utf-8"),
        ]
        source = "\n\n".join(sources).encode("utf-8")
        compiled = "\n".join(path.read_text(encoding="utf-8") for path in self._compiled_chunks())
        match = re.search(r"source-sha256:\s*([0-9a-f]{64})", compiled)
        self.assertIsNotNone(match, "compiled JS is missing its source-sha256 header")
        self.assertEqual(
            match.group(1),
            hashlib.sha256(source).hexdigest(),
            "dashboard compiled chunks are stale — re-run scripts/build_dashboard.py after editing dashboard sources.",
        )
