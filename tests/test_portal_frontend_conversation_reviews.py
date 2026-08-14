from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path

from tests.test_portal_frontend_artifact_library import _dom_shim_script


class PortalFrontendConversationReviewTests(unittest.TestCase):
    def test_review_api_uses_project_frame_route(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_api.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const calls = [];
            globalThis.document = { querySelector: () => ({ getAttribute: () => 'csrf-token' }) };
            globalThis.fetch = async (path, options = {}) => {
              calls.push({ path, options });
              return { ok: true, async json() { return { runId: 'review_1' }; } };
            };
            const api = await import(__MODULE_URL__);
            await api.requestConversationReview('proj_1', 'frame_1', 'claude');
            process.stdout.write(JSON.stringify(calls));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url))

        result = _run_node_json(self, script)
        body = json.loads(result[0]["options"]["body"])

        self.assertEqual(result[0]["path"], "/api/projects/proj_1/frames/frame_1/reviews")
        self.assertEqual(result[0]["options"]["method"], "POST")
        self.assertEqual(result[0]["options"]["headers"]["x-genomi-csrf"], "csrf-token")
        self.assertEqual(body, {"agentId": "claude"})

    def test_review_model_and_finding_payload_use_user_facing_objects(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_conversation_reviews.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const reviews = await import(__MODULE_URL__);
            const model = reviews.conversationReviewModel({
              kind: 'conversation_review',
              review_run_id: 'review_private',
              status: 'completed',
              state: 'findings',
              summary: 'One claim needs qualification.',
              findings: [{
                finding_id: 'finding_1',
                verdict: 'warning',
                claim: 'The answer implies clinical certainty.',
                evidence: 'Only public variant evidence was reviewed.',
                recommendation: 'State the evidence boundary.',
                source_ref: { kind: 'message', message_id: 'msg_1' }
              }]
            });
            const payload = reviews.conversationReviewFindingPayload(model.findings[0]);
            process.stdout.write(JSON.stringify({ model, payload }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url))

        result = _run_node_json(self, script)

        self.assertEqual(result["model"]["title"], "Reviewer")
        self.assertEqual(result["model"]["issueCount"], 1)
        self.assertEqual(result["model"]["findings"][0]["sourceMessageId"], "msg_1")
        self.assertEqual(result["payload"]["context_kind"], "review_finding")
        self.assertEqual(result["payload"]["source_operation"], "genomi.portal.conversation_review")
        self.assertIn("Address this reviewer finding", result["payload"]["prompt_text"])
        self.assertNotIn("review_private", json.dumps(result["payload"]))

    def test_review_surface_renders_findings_and_actions(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_conversation_reviews.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const reviews = await import(__MODULE_URL__);
            __DOM_SHIM__
            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('section');
            const used = [];
            const jumped = [];
            const rerun = [];
            reviews.renderConversationReview(container, [{
              status: 'completed',
              state: 'findings',
              summary: 'One finding.',
              findings: [{
                verdict: 'warning',
                claim: 'Qualification needed',
                evidence: 'The source scope is incomplete.',
                recommendation: 'Name the missing scope.',
                source_ref: { kind: 'message', message_id: 'msg_answer' }
              }],
              limitations: ['Not clinical validation.']
            }], {
              onRequestReview: () => rerun.push(true),
              onUseFinding: (payload) => used.push(payload),
              onJumpToMessage: (messageId) => jumped.push(messageId)
            });
            const buttons = container.querySelectorAll('button');
            buttons.forEach((button) => button.eventListeners.click[0]());
            process.stdout.write(JSON.stringify({
              hidden: container.hidden,
              state: container.dataset.reviewState,
              title: container.querySelector('.conversation-review-head strong').textContent,
              headline: container.querySelector('.conversation-review-head span').textContent,
              claim: container.querySelector('.conversation-review-finding strong').textContent,
              labels: buttons.map((button) => button.textContent),
              used,
              jumped,
              rerun
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertFalse(result["hidden"])
        self.assertEqual(result["state"], "findings")
        self.assertEqual(result["title"], "Reviewer")
        self.assertEqual(result["headline"], "1 finding")
        self.assertEqual(result["claim"], "Qualification needed")
        self.assertEqual(result["labels"], ["Review again", "Jump to claim", "Use in chat"])
        self.assertEqual(result["jumped"], ["msg_answer"])
        self.assertEqual(result["rerun"], [True])
        self.assertEqual(result["used"][0]["context_kind"], "review_finding")

    def test_running_review_is_compact_and_not_selectable(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_conversation_reviews.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const reviews = await import(__MODULE_URL__);
            __DOM_SHIM__
            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('section');
            reviews.renderConversationReview(container, [{
              status: 'running',
              state: 'verifying',
              summary: 'Reviewer is checking this conversation.'
            }]);
            process.stdout.write(JSON.stringify({
              headline: container.querySelector('.conversation-review-head span').textContent,
              details: Boolean(container.querySelector('details')),
              buttons: container.querySelectorAll('button').length
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["headline"], "Reviewing this conversation…")
        self.assertFalse(result["details"])
        self.assertEqual(result["buttons"], 0)

    def test_successful_checks_count_without_rendering_pass_rows(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_conversation_reviews.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const reviews = await import(__MODULE_URL__);
            __DOM_SHIM__
            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('section');
            const model = reviews.conversationReviewModel({
              status: 'completed',
              state: 'findings',
              check_count: 2,
              findings: [
                { verdict: 'warning', claim: 'Needs a boundary', evidence: 'Scope is incomplete.' },
                { verdict: 'pass', claim: 'Source is named', evidence: 'The source is visible.' }
              ]
            });
            reviews.renderConversationReview(container, [{
              status: 'completed',
              state: 'findings',
              check_count: 2,
              findings: [
                { verdict: 'warning', claim: 'Needs a boundary', evidence: 'Scope is incomplete.' },
                { verdict: 'pass', claim: 'Source is named', evidence: 'The source is visible.' }
              ]
            }]);
            process.stdout.write(JSON.stringify({
              checkCount: model.checkCount,
              visibleFindings: model.findings.length,
              renderedFindings: container.querySelectorAll('.conversation-review-finding').length,
              summary: container.querySelector('details summary').textContent
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["checkCount"], 2)
        self.assertEqual(result["visibleFindings"], 1)
        self.assertEqual(result["renderedFindings"], 1)
        self.assertEqual(result["summary"], "2 checks")


def _run_node_json(test_case: unittest.TestCase, script: str) -> dict:
    process = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=False)
    test_case.assertEqual(process.returncode, 0, msg=process.stderr)
    return json.loads(process.stdout)
