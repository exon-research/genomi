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
        self.assertIn("Investigations", self.html)
        self.assertIn("call 911", self.html)
        self.assertIn("ask you to upload a VCF for each question", self.html)
        self.assertIn("/api/v1/molecular-profile/observations", combined)
        self.assertIn("/api/v1/investigations", combined)

    def test_inquiry_setup_orders_question_before_molecular_context_and_authorization(self) -> None:
        molecular_position = self.html.index('id="molecular-profile"')
        inquiry_position = self.html.index('id="new-inquiry"')
        history_position = self.html.index('id="investigations"')

        self.assertLess(inquiry_position, molecular_position)
        self.assertLess(molecular_position, history_position)
        self.assertIn('href="#molecular-profile"', self.html)
        self.assertIn('href="#new-inquiry"', self.html)
        self.assertIn("Question before context", self.html)
        self.assertIn("Review &amp; authorize", self.html)

    def test_science_workspace_theme_covers_first_run_setup(self) -> None:
        self.assertIn('name="color-scheme" content="dark"', self.html)
        self.assertIn('name="theme-color" content="#0a0a0a"', self.html)
        styles = self.styles["styles.css"]
        setup_rule = styles[styles.index(".setup-state {") : styles.index("}", styles.index(".setup-state {"))]
        self.assertIn("background: var(--surface)", setup_rule)
        self.assertIn("--paper: #0a0a0a", styles)
        self.assertIn("--surface: #111111", styles)
        self.assertIn(".work-card { border-radius: 10px; background: var(--surface); }", self.styles["workspace.css"])
        self.assertIn("background: var(--surface-2)", self.styles["brief.css"])

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
            "context-preview-list",
            "harness-message-form",
            "capability-approval-list",
            "event-list",
            "evidence-ledger",
            "hypothesis-list",
            "gap-list",
            "brief-list",
        ):
            with self.subTest(portal_id=portal_id):
                self.assertIn(f'id="{portal_id}"', self.html)

    def test_optional_research_tool_onboarding_is_local_and_setup_only(self) -> None:
        controller = self.modules["connections-controller.js"]
        renderer = self.modules["render-connections.js"]

        self.assertIn('href="#research-tools"', self.html)
        for portal_id in ("research-tools", "integrations-summary", "integration-list"):
            with self.subTest(portal_id=portal_id):
                self.assertIn(f'id="{portal_id}"', self.html)

        self.assertIn('const INTEGRATIONS_PATH = "/api/v1/integrations"', controller)
        self.assertIn('new Set(["verify", "disconnect"])', controller)
        self.assertIn("/${provider}/connect", controller)
        self.assertIn("/${provider}/${action}", controller)
        for provider in ("paperclip", "biohub-esm", "proto"):
            with self.subTest(provider=provider):
                self.assertIn(f'provider: "{provider}"', renderer)
        for field in (
            "api_key",
            "api_token",
            "modal_token_id",
            "modal_token_secret",
            "modal_environment",
        ):
            with self.subTest(field=field):
                self.assertIn(f'name: "{field}"', renderer)

        self.assertIn('input.type = field.secret ? "password" : "text"', renderer)
        self.assertIn('input.autocomplete = "off"', renderer)
        self.assertNotIn("input.value", renderer)
        self.assertIn("form.reset()", controller)
        self.assertLess(
            controller.index("form.reset()"),
            controller.index("setFormBusy(form, submit, false)"),
        )
        self.assertNotIn("sessionStorage", controller + renderer)
        self.assertNotIn("localStorage", controller + renderer)
        self.assertNotIn("/run", controller)
        self.assertNotIn("/search", controller)
        self.assertIn('"Save securely"', renderer)
        self.assertIn('"Run public API check — may use credits"', renderer)
        self.assertIn('"Run fixed synthetic encode check — may use credits"', renderer)
        self.assertIn('"Check Modal account and environment"', renderer)
        self.assertNotIn('"Run paid synthetic check"', renderer)
        self.assertNotIn("paid synthetic check", controller)
        self.assertIn("never a patient-derived sequence", renderer)
        self.assertIn("one fixed public search for TP53", renderer)
        self.assertIn("PMC with a limit of 1", renderer)
        self.assertIn("never sends the patient's profile", renderer)
        self.assertIn("Paperclip API key checked", renderer)
        self.assertIn("enables no general public-evidence operation", renderer)
        self.assertIn("Patient investigations:", renderer)
        self.assertIn("no Proto tool will run", controller)
        self.assertIn('url: "/official/biohub-api-keys"', renderer)
        self.assertIn('url: "/official/biohub-terms"', renderer)
        self.assertIn('url: "/official/biohub-privacy"', renderer)
        self.assertIn('url: "/official/biohub-limitations"', renderer)
        self.assertIn('link.rel = "noopener noreferrer"', renderer)
        self.assertIn("independent patient-data agreement", renderer)
        for field in (
            "investigation_operations",
            "investigation_routes",
            "investigation_purposes",
        ):
            with self.subTest(field=field):
                self.assertIn(field, renderer + controller)
        self.assertIn(
            "When ready, run the fixed public API check: TP53 in PMC, limit 1",
            controller,
        )
        self.assertIn(
            "Secure credential storage is unavailable, so this tool cannot be connected",
            renderer,
        )
        self.assertIn("Enabled patient-investigation routes", renderer)
        self.assertIn("Approved purposes", renderer)
        self.assertIn(
            "Every patient-influenced query still requires an exact preview and approval",
            renderer,
        )
        self.assertIn("connection_state", renderer)
        self.assertIn("reconciliation_required", renderer)
        self.assertIn("Confirm disconnected", renderer)
        self.assertIn("Run the connection check", renderer)
        self.assertIn('credentialState === "stored"', renderer)
        self.assertIn("policy_state", renderer)
        self.assertIn('credentialState === "corrupt"', renderer)
        self.assertIn('integration.connection_state === "not_configured"', controller)
        self.assertIn('integration.credential_state === "missing"', controller)
        self.assertIn("remains configured", controller)
        self.assertIn("await load({announceFailure: connected})", controller)
        self.assertIn("await load({announceFailure: completed})", controller)
        self.assertIn("No credentials can be changed until it is available", renderer)
        self.assertIn("connecting a tool does not start research", self.html.lower())

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
            "Research authorization",
            "Authorize and start investigation",
            "covers routine planning, local evidence work, replanning, and",
            "pauses before using an external",
            "Evidence, kept separate by source",
            "Hypotheses",
            "Open gaps",
            "Investigation Brief",
            "keeps this working plan current",
            "Choose the profile observations this disease question needs",
        ):
            with self.subTest(copy=copy):
                self.assertIn(copy, self.html)

    def test_investigation_uses_one_start_authorization_and_direct_routine_work(
        self,
    ) -> None:
        controller = self.modules["investigation-controller.js"]
        renderer = self.modules["render.js"]

        self.assertIn('session.path("/authorization-candidate")', controller)
        self.assertIn('session.path("/authorize-start")', controller)
        self.assertIn('session.path("/messages")', controller)
        self.assertIn('session.path("/cancel")', controller)
        self.assertIn("authorization_candidate_receipt", controller + renderer)
        self.assertIn("authorization_scope", controller + renderer)
        self.assertIn("Authorize and start investigation", self.html + renderer)
        self.assertIn("Working plan", renderer)
        self.assertIn("Approve exact evidence request", renderer)
        self.assertIn("Operation:", renderer)
        self.assertIn("Purpose:", renderer)
        self.assertIn("Data:", renderer)
        self.assertIn("Query terms:", renderer)
        self.assertIn("Retention:", renderer)
        self.assertIn("Training:", renderer)
        self.assertIn("approvalSha256", controller + renderer)

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
