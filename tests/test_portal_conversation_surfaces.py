"""Conversation-level portal surfaces: intake empty state, attached records, starter cards."""

from __future__ import annotations

import base64
import json
import textwrap
import unittest
from pathlib import Path

from genomi.interfaces import portal_assets, portal_file_imports, portal_starter_cards, portal_store
from tests.support.runtime.genomi import IsolatedGenomiHomeTestCase
from tests.test_portal_frontend_artifact_library import _dom_shim_script
from tests.test_portal_frontend_assets import _run_node_json

_TEMPLATES = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"


class ConversationIntakeTests(unittest.TestCase):
    def test_message_surface_reports_when_the_conversation_has_content(self) -> None:
        messages_url = (_TEMPLATES / "portal_messages.js").as_uri()
        script = _dom_shim_script() + textwrap.dedent(
            f"""
            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            const messages = await import({messages_url!r});
            const list = document.createElement('div');
            const seen = [];
            const surface = messages.createMessageSurface({{
              list,
              onConversationStateChange: (state) => seen.push(state.empty)
            }});
            const latest = () => seen[seen.length - 1];
            const observed = [];
            surface.reset();
            observed.push(latest());
            surface.addMessage('user', 'I have Crohn\\'s and recurrent infections.');
            observed.push(latest());
            surface.reset();
            observed.push(latest());
            surface.renderStoredMessages([
              {{ role: 'user', text: 'I uploaded my records and DNA file.' }},
              {{ role: 'assistant', text: 'Reviewing the records now.' }}
            ]);
            observed.push(latest());
            process.stdout.write(JSON.stringify({{ observed }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["observed"], [True, False, True, False])

    def test_portal_hides_the_intake_prompt_once_the_conversation_has_content(self) -> None:
        portal = (_TEMPLATES / "portal.js").read_text(encoding="utf-8")
        html = portal_assets._portal_html("test-csrf-token")

        self.assertIn("onConversationStateChange: renderConversationIntake", portal)
        self.assertIn("function renderConversationIntake({ empty } = {}) {", portal)
        self.assertIn("if (intake) intake.hidden = !empty;", portal)
        self.assertIn('<section class="genomilab-intake"', html)


class ConversationAttachmentTests(IsolatedGenomiHomeTestCase):
    def test_records_attached_from_a_conversation_are_bound_to_that_conversation(self) -> None:
        project = portal_store.create_project(name="Crohn's + recurrent infections")
        project_id = str(project["project_id"])
        frame = portal_store.create_frame(
            project_id=project_id,
            request="I uploaded my records and DNA file.",
            agent_id="codex",
        )
        assert frame is not None

        status, payload = portal_file_imports.import_project_file(
            project_id,
            {
                "filename": "clinical-records.md",
                "contentType": "text/markdown",
                "contentBase64": base64.b64encode(b"# Clinical records\n- Crohn's disease\n").decode("ascii"),
                "frameId": frame["id"],
            },
        )

        self.assertEqual(int(status), 201)
        artifact = payload["artifact"]
        self.assertEqual(artifact["kind"], "project_file")
        self.assertEqual(artifact["origin_context"]["frame_id"], frame["id"])
        self.assertEqual(artifact["summary"]["original_filename"], "clinical-records.md")
        listed = portal_store.list_project_artifacts(project_id)
        assert listed is not None
        bound = [item for item in listed["artifacts"] if item.get("origin_context", {}).get("frame_id") == frame["id"]]
        self.assertEqual([item["summary"]["original_filename"] for item in bound], ["clinical-records.md"])

    def test_an_import_naming_another_projects_conversation_is_refused(self) -> None:
        first = portal_store.create_project(name="First workspace")
        second = portal_store.create_project(name="Second workspace")
        other_frame = portal_store.create_frame(
            project_id=str(second["project_id"]),
            request="Unrelated conversation",
            agent_id="codex",
        )
        assert other_frame is not None

        status, payload = portal_file_imports.import_project_file(
            str(first["project_id"]),
            {
                "filename": "records.md",
                "contentType": "text/markdown",
                "contentBase64": base64.b64encode(b"records").decode("ascii"),
                "frameId": other_frame["id"],
            },
        )

        self.assertEqual(int(status), 400)
        self.assertEqual(payload["error"]["code"], "conversation_not_found")

    def test_attached_records_render_as_named_conversation_attachments(self) -> None:
        attachments_url = (_TEMPLATES / "portal_conversation_attachments.js").as_uri()
        artifacts = [
            {
                "id": "art_records",
                "kind": "project_file",
                "title": "clinical-records.md",
                "summary": {"original_filename": "clinical-records.md", "content_type": "text/markdown", "size_bytes": 2048},
                "origin_context": {"frame_id": "frame_a"},
            },
            {
                "id": "art_vcf",
                "kind": "project_file",
                "title": "exome.vcf",
                "summary": {"original_filename": "exome.vcf", "content_type": "application/octet-stream", "size_bytes": 5_242_880},
                "origin_context": {"frame_id": "frame_a"},
            },
            {
                "id": "art_other_chat",
                "kind": "project_file",
                "title": "notes.md",
                "summary": {"original_filename": "notes.md", "content_type": "text/markdown", "size_bytes": 12},
                "origin_context": {"frame_id": "frame_b"},
            },
            {
                "id": "art_report",
                "kind": "evidence_packet",
                "title": "report.html",
                "summary": {},
                "origin_context": {"frame_id": "frame_a"},
            },
        ]
        script = _dom_shim_script() + textwrap.dedent(
            f"""
            globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            const attachments = await import({attachments_url!r});
            const artifacts = {json.dumps(artifacts)};
            const models = attachments.conversationAttachmentModels(artifacts, 'frame_a');
            const section = document.createElement('section');
            section.innerHTML = '<div><h3></h3><p data-conversation-attachment-summary></p></div>'
              + '<div data-conversation-attachment-list></div>';
            const opened = [];
            attachments.renderConversationAttachments(section, models, {{
              onOpenAttachment: (id) => opened.push(id)
            }});
            const cards = section.querySelectorAll('[data-testid="genomi-conversation-attachment"]');
            cards[1].eventListeners.click[0]();
            const emptySection = document.createElement('section');
            emptySection.innerHTML = '<div data-conversation-attachment-list></div>';
            attachments.renderConversationAttachments(emptySection, attachments.conversationAttachmentModels(artifacts, 'frame_z'), {{}});
            process.stdout.write(JSON.stringify({{
              names: models.map((model) => model.name),
              details: models.map((model) => model.detail),
              summary: section.querySelector('[data-conversation-attachment-summary]').textContent,
              cardCount: cards.length,
              opened,
              hidden: section.hidden,
              emptyHidden: emptySection.hidden
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["names"], ["clinical-records.md", "exome.vcf"])
        self.assertEqual(result["details"], ["Text record · 2 KB", "Genome data file · 5.0 MB"])
        self.assertEqual(result["summary"], "Genomi can read these 2 records in this conversation.")
        self.assertEqual(result["cardCount"], 2)
        self.assertEqual(result["opened"], ["art_vcf"])
        self.assertFalse(result["hidden"])
        self.assertTrue(result["emptyHidden"])

    def test_attached_records_stay_out_of_the_generated_artifact_strip(self) -> None:
        artifacts_url = (_TEMPLATES / "portal_artifacts.js").as_uri()
        artifacts = [
            {
                "id": "art_records",
                "kind": "project_file",
                "operation": "portal.import_file",
                "title": "clinical-records.md",
                "origin_context": {"frame_id": "frame_a", "run_ids": ["run_1"]},
            },
            {
                "id": "art_report",
                "kind": "evidence_packet",
                "operation": "research.build_target_packet",
                "title": "NFKB1 evidence report",
                "origin_context": {"frame_id": "frame_a", "run_ids": ["run_1"]},
            },
        ]
        script = textwrap.dedent(
            f"""
            const module = await import({artifacts_url!r});
            const artifacts = {json.dumps(artifacts)};
            process.stdout.write(JSON.stringify({{
              produced: module.artifactsForRun(artifacts, 'frame_a', 'run_1').map((item) => item.id)
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["produced"], ["art_report"])

    def test_chat_attachment_sends_the_open_conversation_with_the_import(self) -> None:
        portal = (_TEMPLATES / "portal.js").read_text(encoding="utf-8")

        self.assertIn(
            "const conversationId = attachToPrompt ? String(state.frameId || '').trim() : '';",
            portal,
        )
        self.assertIn("...(conversationId ? { frameId: conversationId } : {})", portal)
        self.assertIn("conversationAttachmentModels(state.artifacts, state.frameId)", portal)


class GenomeObjectNamingTests(unittest.TestCase):
    def test_every_conversation_surface_names_the_genome_the_same_way(self) -> None:
        html = portal_assets._portal_html("test-csrf-token")
        inventory = (_TEMPLATES / "portal_genome_inventory.js").read_text(encoding="utf-8")
        intake = html.split('<section class="genomilab-intake"', 1)[1].split("</section>", 1)[0]
        cards = {card["id"]: card for card in portal_starter_cards.welcome_model()["cards"]}

        self.assertIn('aria-label="Active genome selection"', intake)
        self.assertIn("<span>Active genome</span>", intake)
        self.assertIn('data-nav-target="genome-index">Active genome</button>', html)
        self.assertIn("<h2>Active genome</h2>", html)
        self.assertIn('<strong id="context-label">Active genome</strong>', html)
        self.assertIn("title: 'Choose a genome',", inventory)
        self.assertIn("return 'Choose an active genome for this workspace.';", inventory)
        self.assertEqual(cards["add-genome"]["label"], "Add your genome")


class StarterCardJourneyTests(unittest.TestCase):
    def test_starter_cards_lead_with_the_investigation_a_person_would_ask_for(self) -> None:
        cards = portal_starter_cards.welcome_model()["cards"]
        chat_routed = [card for card in cards if card.get("prompt")]
        source_routed = [card for card in cards if card.get("sourceOperation")]

        self.assertEqual(cards[0]["id"], "investigate-health-question")
        self.assertEqual(cards[0]["label"], "Investigate a health question")
        self.assertIn("competing explanations", cards[0]["detail"])
        self.assertEqual([card["id"] for card in chat_routed], ["investigate-health-question", "review-a-medication"])
        self.assertEqual([card["sourceOperation"] for card in source_routed], ["genomi.parse_source"])
        self.assertIn("saved on this computer", cards[2]["detail"])
        for card in chat_routed:
            self.assertNotIn("VCF", card["prompt"])

    def test_a_chat_routed_card_fills_the_composer_instead_of_the_source_console(self) -> None:
        portal = (_TEMPLATES / "portal.js").read_text(encoding="utf-8")

        self.assertIn("closest('[data-source-operation], [data-prompt]')", portal)
        self.assertIn("promptContext.setPromptText(button.getAttribute('data-prompt') || '');", portal)
