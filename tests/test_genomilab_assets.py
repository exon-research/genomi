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
    @classmethod
    def setUpClass(cls) -> None:
        cls.static = resources.files("genomi.lab").joinpath("static")
        cls.html = cls.static.joinpath("index.html").read_text(encoding="utf-8")
        cls.modules = {
            item.name: item.read_text(encoding="utf-8")
            for item in cls.static.iterdir()
            if item.name.endswith(".js")
        }
        cls.styles = {
            item.name: item.read_text(encoding="utf-8")
            for item in cls.static.iterdir()
            if item.name.endswith(".css")
        }

    def test_assets_are_local_and_dom_rendering_avoids_injection_sinks(self) -> None:
        parser = _PortalHTMLParser()
        parser.feed(self.html)
        self.assertFalse(parser.inline_script)
        self.assertFalse(parser.inline_style)
        self.assertEqual(parser.scripts, [{"src": "/app.js", "type": "module"}])
        self.assertEqual(
            parser.stylesheets,
            ["/styles.css", "/workspace.css", "/brief.css", "/responsive.css"],
        )

        combined = "\n".join([self.html, *self.modules.values(), *self.styles.values()])
        self.assertIsNone(re.search(r"https?://|(?:src|href)=[\"']//", combined))
        self.assertNotIn("@import", combined)
        for unsafe in (
            "innerHTML",
            "outerHTML",
            "insertAdjacentHTML",
            "localStorage",
            "eval(",
            "new Function",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertNotIn(unsafe, combined)
        self.assertIn(
            "[hidden] { display: none !important; }", self.styles["styles.css"]
        )

    def test_portal_auth_is_exact_origin_header_state_not_an_ambient_cookie(
        self,
    ) -> None:
        api = self.modules["api.js"]
        app = self.modules["app.js"]
        self.assertIn("location.hash", api)
        self.assertIn('params.has("token")', api)
        self.assertIn("history.replaceState", api)
        self.assertIn("sessionStorage", api)
        self.assertIn("X-GenomiLab-Launch-Token", api)
        self.assertIn("X-GenomiLab-Session", api)
        self.assertIn('credentials: "omit"', api)
        self.assertNotIn("document.cookie", api)
        self.assertNotIn('credentials: "same-origin"', api)
        self.assertIn("initializePortalSession", app)

    def test_evidence_links_reject_local_loopback_targets(self) -> None:
        evidence = self.modules["render-evidence.js"]
        self.assertIn('hostname === "localhost"', evidence)
        self.assertIn('hostname.endsWith(".localhost")', evidence)
        self.assertIn("Number(ipv4[1]) === 127", evidence)

    def test_all_relative_javascript_imports_resolve_recursively(self) -> None:
        self.assertIn("app.js", self.modules)
        visited: set[str] = set()
        pending = ["app.js"]
        while pending:
            module_name = pending.pop()
            if module_name in visited:
                continue
            visited.add(module_name)
            source = self.modules[module_name]
            for relative in re.findall(
                r'(?:from\s+|import\s+)["\']\./([^"\']+)["\']', source
            ):
                with self.subTest(module=module_name, target=relative):
                    self.assertIn(relative, self.modules)
                pending.append(relative)
        self.assertEqual(visited, set(self.modules))

    def test_required_element_contract_matches_portal_markup(self) -> None:
        parser = _PortalHTMLParser()
        parser.feed(self.html)
        dom_contract = self.modules["render-dom.js"]
        block = dom_contract[
            dom_contract.index("const REQUIRED_ELEMENT_IDS") : dom_contract.index("];")
        ]
        required_ids = set(re.findall(r'"([a-z][a-z0-9-]+)"', block))
        self.assertTrue(required_ids)
        self.assertEqual(required_ids - parser.ids, set())

    def test_portal_uses_current_user_and_existing_genomi_genome_model(self) -> None:
        combined = "\n".join([self.html, *self.modules.values()])
        self.assertIn("Current Genomi user", self.html)
        self.assertIn("My Molecular Profile", self.html)
        self.assertIn("Disease investigations", self.html)
        self.assertIn("call 911", self.html)
        self.assertIn("ask you to upload a VCF for each question", self.html)
        self.assertIn("/api/v1/molecular-profile/observations", combined)
        self.assertIn("/api/v1/investigations", combined)

    def test_source_record_control_accepts_reports_not_genome_sources(self) -> None:
        source_form = self.html[
            self.html.index('id="source-artifact-form"') : self.html.index(
                "</form>", self.html.index('id="source-artifact-form"')
            )
        ]
        self.assertEqual(self.html.count('type="file"'), 1)
        accept = re.search(r'accept="([^"]+)"', source_form)
        self.assertIsNotNone(accept)
        accepted_types = accept.group(1).lower() if accept else ""
        for genomic_format in (".vcf", ".gvcf", ".bam", ".cram", ".fastq", ".fq"):
            with self.subTest(genomic_format=genomic_format):
                self.assertNotIn(genomic_format, accepted_types)
        self.assertIn("File bytes and the file path are never sent", source_form)

    def test_profile_and_investigation_workspace_controls_remain_present(self) -> None:
        for portal_id in (
            "source-artifact-form",
            "specimen-form",
            "assay-form",
            "observation-form",
            "observation-editor",
            "observation-history-list",
            "investigation-detail",
            "plan-list",
            "context-observation-list",
            "harness-outbound-details",
            "event-list",
            "evidence-ledger",
            "hypothesis-list",
            "gap-list",
            "brief-list",
        ):
            with self.subTest(portal_id=portal_id):
                self.assertIn(f'id="{portal_id}"', self.html)

    def test_patient_profile_forms_do_not_expose_generated_or_claimed_authority(
        self,
    ) -> None:
        observation_form = self.html[
            self.html.index('id="observation-form"') : self.html.index(
                "</form>", self.html.index('id="observation-form"')
            )
        ]
        for name in ("artifact_id", "specimen_id", "assay_id", "record_assertion"):
            self.assertIn(f'name="{name}"', observation_form)
        for forbidden in (
            "source_class",
            "verification_state",
            "assertion_author",
            "clinical_confirmation",
            "observation_revision_id",
            "logical_observation_id",
            "metadata",
            "qc",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(f'name="{forbidden}"', self.html)

    def test_safety_and_review_language_remains_visible(self) -> None:
        for copy in (
            "Exact private context",
            "Exact outbound disclosure",
            "Evidence, kept separate by source",
            "Hypotheses",
            "Open gaps",
            "Investigation Brief",
            "Nothing in this plan runs until you accept it",
            "Choose the profile observations this disease question needs",
        ):
            with self.subTest(copy=copy):
                self.assertIn(copy, self.html)

    def test_responsive_and_evidence_styles_remain_packaged(self) -> None:
        self.assertIn(
            ".work-card-heading { flex-wrap: wrap; }", self.styles["responsive.css"]
        )
        self.assertIn(".work-card-heading .mini-status", self.styles["responsive.css"])
        self.assertIn("white-space: normal", self.styles["responsive.css"])
        self.assertIn(".evidence-facts", self.styles["workspace.css"])
        self.assertIn(".negative-inference-not-allowed", self.styles["workspace.css"])
        self.assertIn(".modality-badge", self.styles["brief.css"])
        self.assertIn(".clinical-boundary", self.styles["brief.css"])


if __name__ == "__main__":
    unittest.main()
