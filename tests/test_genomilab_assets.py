from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from importlib import resources


class _PortalHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.scripts: list[dict[str, str | None]] = []
        self.stylesheets: list[str] = []
        self.inline_script = False
        self.inline_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if tag == "script":
            self.scripts.append(values)
            if not values.get("src"):
                self.inline_script = True
        if tag == "style":
            self.inline_style = True
        if tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.stylesheets.append(str(values["href"]))


class GenomiLabAssetTests(unittest.TestCase):
    def test_assets_are_packaged_local_and_use_safe_dom_rendering(self) -> None:
        static = resources.files("genomi.lab").joinpath("static")
        html = static.joinpath("index.html").read_text(encoding="utf-8")
        parser = _PortalHTMLParser()
        parser.feed(html)

        self.assertFalse(parser.inline_script)
        self.assertFalse(parser.inline_style)
        self.assertEqual(
            parser.scripts,
            [{"src": "/app.js", "type": "module"}],
        )
        self.assertEqual(
            parser.stylesheets,
            ["/styles.css", "/workspace.css", "/brief.css", "/responsive.css"],
        )

        asset_names = {
            "index.html",
            "app.js",
            "api.js",
            "render.js",
            "styles.css",
            "workspace.css",
            "brief.css",
            "responsive.css",
        }
        contents = {
            name: static.joinpath(name).read_text(encoding="utf-8")
            for name in asset_names
        }
        combined = "\n".join(contents.values())
        self.assertIsNone(re.search(r"https?://|(?:src|href)=[\"']//", combined))
        self.assertNotIn("@import", combined)
        for unsafe in (
            "innerHTML",
            "outerHTML",
            "insertAdjacentHTML",
            "localStorage",
            "sessionStorage",
            "eval(",
            "new Function",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertNotIn(unsafe, combined)

        required_ids = set(
            re.findall(r'"([a-z][a-z0-9-]+)"', contents["render.js"].split("];")[0])
        )
        self.assertTrue(required_ids)
        self.assertEqual(required_ids - parser.ids, set())

    def test_javascript_module_imports_have_packaged_targets(self) -> None:
        static = resources.files("genomi.lab").joinpath("static")
        app = static.joinpath("app.js").read_text(encoding="utf-8")
        imports = re.findall(r'from\s+"\./([^\"]+)"', app)
        self.assertEqual(set(imports), {"api.js", "render.js"})
        for target in imports:
            with self.subTest(target=target):
                self.assertTrue(static.joinpath(target).is_file())


if __name__ == "__main__":
    unittest.main()
