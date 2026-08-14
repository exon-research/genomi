from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from genomi.interfaces import portal_selected_context_catalog


class PortalSelectedContextCatalogTests(unittest.TestCase):
    def test_js_asset_is_generated_from_python_catalog(self) -> None:
        self.assertEqual(
            portal_selected_context_catalog.SELECTED_CONTEXT_CATALOG_JS_PATH.read_text(encoding="utf-8"),
            portal_selected_context_catalog.selected_context_catalog_js(),
        )

    def test_write_helper_emits_generated_js(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "portal_selected_context_catalog.js"

            written_path = portal_selected_context_catalog.write_selected_context_catalog_js(output_path)

            self.assertEqual(written_path, output_path)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                portal_selected_context_catalog.selected_context_catalog_js(),
            )
