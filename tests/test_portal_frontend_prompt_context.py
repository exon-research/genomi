from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

from genomi.interfaces import portal_prompt_suggestions, portal_selected_context_catalog, portal_turns
from tests.test_portal_frontend_artifact_library import _dom_shim_script

_PRIVATE_PROMPT_RE = re.compile(r"(?:context_file|registry_file|agi_path|/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes|~)")


class PortalPromptContextFrontendTest(unittest.TestCase):
    def test_composer_renders_selected_material_as_compact_attachments(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_prompt_context.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const promptContext = await import(__MODULE_URL__);
            __DOM_SHIM__
            Element.prototype.append = function (...children) {
              children.forEach((child) => this.appendChild(child));
            };
            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const tray = document.createElement('section');
            const prompt = { value: '', focus() {} };
            const controller = promptContext.createPromptContextController({ tray, prompt, storageKey: '' });
            controller.add({
              context_kind: 'review_finding',
              label: 'Reviewer finding: unsupported genome name',
              source_operation: 'genomi.portal.conversation_review',
              selected_nodes: [
                { label: 'Evidence', text: 'The workspace does not provide a display name.' },
                { label: 'Recommendation', text: 'Remove the unsupported name.' }
              ]
            });
            const card = tray.querySelector('.prompt-context-card');
            const remove = tray.querySelector('.prompt-context-remove');
            const before = controller.snapshot().length;
            remove.eventListeners.click[0]();
            process.stdout.write(JSON.stringify({
              before,
              after: controller.snapshot().length,
              label: card.querySelector('strong').textContent,
              kind: card.querySelector('.prompt-context-kind').textContent,
              actions: tray.querySelectorAll('.prompt-context-card-actions').length,
              previews: tray.querySelectorAll('.prompt-context-preview').length,
              nodes: tray.querySelectorAll('.prompt-context-node-list').length,
              removeText: remove.textContent
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["before"], 1)
        self.assertEqual(result["after"], 0)
        self.assertEqual(result["label"], "Reviewer finding: unsupported genome name")
        self.assertEqual(result["kind"], "Review finding")
        self.assertEqual(result["actions"], 0)
        self.assertEqual(result["previews"], 0)
        self.assertEqual(result["nodes"], 0)
        self.assertEqual(result["removeText"], "×")

    def test_prompt_context_actions_and_wording_preserve_context_kind(self) -> None:
        prompt_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_prompt_context.js").as_uri()
        catalog_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_selected_context_catalog.js").as_uri()
        script = textwrap.dedent(
            f"""
            const prompt = await import({prompt_url!r});
            const catalog = await import({catalog_url!r});
            const evidenceContext = {{
              label: 'Envelope evidence',
              context_kind: 'evidence_panel',
              source_operation: 'variant.resolve',
              finding_state: 'data_returned',
              answer_readiness: 'partial_public_evidence',
              summary: 'variant.resolve summary keeps rs429358.evidence token',
              prompt_text: 'Selected evidence from variant.resolve:\\n- Coverage: ClinVar',
              selected_nodes: [
                {{
                  label: 'Coverage from /Users/matthewzmd/.genomi/private.json',
                  text: 'Coverage: context_file=/Users/matthewzmd/.genomi/context.json',
                  value: '/tmp/private-coverage.json'
                }},
                {{
                  label: 'variant.resolve guidance',
                  text: 'variant.resolve: preserve rs429358.evidence prior',
                  value: 'preserve source prior'
                }}
              ]
            }};
            const resultContext = {{
              label: 'Variant result',
              context_kind: 'result_nodes',
              source_operation: 'variant.resolve',
              selected_nodes: [
                {{ label: 'ClinVar row', text: 'ClinVar records: rs429358 risk factor' }}
              ]
            }};
            const evidenceReportContext = {{
              label: 'Evidence report: rs429358',
              context_kind: 'evidence_report',
              source_operation: 'research.build_target_packet',
              selected_nodes: [
                {{ label: 'ClinVar source', text: 'ClinVar: Variant clinical assertions' }}
              ]
            }};
            const toolRequestContext = {{
              label: 'Evidence source: research.build_target_packet',
              context_kind: 'tool_request',
              source_operation: 'research.build_target_packet',
              prompt_text: 'Prepared Genomi evidence-source request: research.build_target_packet\\nParameters: {{"target_type":"topic","topic":"rs429358"}}',
              selected_nodes: [
                {{ label: 'Parameters', text: 'Parameters: {{"target_type":"topic","topic":"rs429358"}}' }}
              ]
            }};
            const promptOnlyToolRequestContext = {{
              label: 'Evidence source: research.build_target_packet',
              context_kind: 'tool_request',
              source_operation: 'research.build_target_packet',
              prompt_text: 'Prepared Genomi evidence-source request: research.build_target_packet\\nParameters: {{"target_type":"topic","topic":"rs429358"}}'
            }};
            const serverProvidedToolRequestContext = {{
              label: 'Evidence source: Add a genome',
              context_kind: 'tool_request',
              source_operation: 'genomi.parse_source',
              selected_nodes: [
                {{ label: 'Evidence source', text: 'Evidence source: Add a genome' }},
                {{ label: 'Inputs provided', text: 'Inputs provided: No inputs supplied yet.' }}
              ]
            }};
            const workTraceContext = {{
              label: 'Message work trail',
              context_kind: 'work_trace',
              source_operation: 'genomi.portal.message_work_trace',
              selected_nodes: [
                {{ label: 'Tool step', text: 'variant.resolve completed' }}
              ]
            }};
            const workspaceFileContext = {{
              label: 'Project file: reports/apoe.md',
              context_kind: 'workspace_file',
              source_operation: 'genomi.portal.workspace_file',
              selected_nodes: [
                {{ label: 'File', text: 'Project file / File: reports/apoe.md' }},
                {{ label: 'Visible preview excerpt', text: 'Project file / Visible preview excerpt: APOE notes' }}
              ]
            }};
            const evidenceLedgerContext = {{
              label: 'Evidence map summary',
              context_kind: 'evidence_ledger',
              source_operation: 'genomi.portal.evidence_ledger',
              selected_nodes: [
                {{ label: 'variant.resolve', text: 'Evidence ledger / variant.resolve / summary: rs429358 supported' }}
              ]
            }};
            const genomeContext = {{
              label: 'Active genome: GRCh38 · VCF · query-ready genome',
              context_kind: 'genome_context',
              source_operation: 'genomi.describe_context',
              selected_nodes: [
                {{ label: 'Current genome / Build', text: 'Active genome / Current genome / Build: GRCh38' }}
              ]
            }};
            const nodeOnlyContext = {{
              label: 'Node-only variant result',
              context_kind: 'result_nodes',
              source_operation: 'variant.resolve',
              selected_nodes: [
                {{ label: 'ClinVar row', text: 'ClinVar records: rs429358 risk factor' }}
              ]
            }};
            const nodeOnlyOriginal = JSON.stringify(nodeOnlyContext);
            const materialSet = prompt.selectedMaterialSet([resultContext, toolRequestContext], nodeOnlyContext);
            const rebuilt = prompt.rebuildContextItemWithNodes(evidenceContext, [evidenceContext.selected_nodes[1]]);
            let submitted = null;
            let submittedOptions = null;
            let askFocused = 0;
            const askPromptEl = {{
              value: '',
              focus: () => {{ askFocused += 1; }}
            }};
            const askController = prompt.createPromptContextController({{
              prompt: askPromptEl,
              storageKey: '',
              onSuggestPrompt: async (items) => 'Server suggested prompt for ' + items.map((item) => item.context_kind).join(','),
              onAskSelected: (items, options) => {{
                submitted = items;
                submittedOptions = options;
              }}
            }});
            const addResultReturn = askController.add(resultContext);
            const addToolRequestReturn = askController.add(toolRequestContext);
            const addInvalidReturn = askController.add(null);
            const beforeAskSnapshot = askController.snapshot();
            const askWithReturn = await askController.askWith(beforeAskSnapshot[0]);
            const afterAskSnapshot = askController.snapshot();
            if (submittedOptions && typeof submittedOptions.onSuccess === 'function') submittedOptions.onSuccess();
            const afterSuccessSnapshot = askController.snapshot();
            const askPromptValue = askPromptEl.value;
            let draftFocused = 0;
            const draftPromptEl = {{
              value: '',
              focus: () => {{ draftFocused += 1; }}
            }};
            const draftController = prompt.createPromptContextController({{
              prompt: draftPromptEl,
              storageKey: '',
              onSuggestPrompt: async (items) => 'Server suggested prompt for ' + items.map((item) => item.context_kind).join(',')
            }});
            draftController.add(resultContext);
            draftController.add(toolRequestContext);
            const draftWithReturn = await draftController.draftWith(evidenceLedgerContext);
            const afterDraftSnapshot = draftController.snapshot();
            const lastDraftItem = afterDraftSnapshot[afterDraftSnapshot.length - 1] || {{}};
            let newConversationSubmitted = null;
            let newConversationOptions = null;
            let newConversationFocused = 0;
            const newConversationPromptEl = {{
              value: '',
              focus: () => {{ newConversationFocused += 1; }}
            }};
            const newConversationController = prompt.createPromptContextController({{
              prompt: newConversationPromptEl,
              storageKey: '',
              onSuggestPrompt: async (items) => 'Server suggested new conversation for ' + items.map((item) => item.context_kind).join(','),
              onAskNewConversation: (items, options) => {{
                newConversationSubmitted = items;
                newConversationOptions = options;
              }}
            }});
            newConversationController.add(workspaceFileContext);
            const beforeNewConversationSnapshot = newConversationController.snapshot();
            const askNewWithReturn = await newConversationController.askNewWith(beforeNewConversationSnapshot[0]);
            const newConversationPromptValue = newConversationPromptEl.value;
            if (newConversationOptions && typeof newConversationOptions.onSuccess === 'function') newConversationOptions.onSuccess();
            const afterNewConversationSuccessSnapshot = newConversationController.snapshot();
            process.stdout.write(JSON.stringify({{
              evidenceNodes: prompt.contextNodes(evidenceContext),
              actionModels: {{
                evidence: prompt.contextActionModel(evidenceContext),
                evidenceReport: prompt.contextActionModel(evidenceReportContext),
                toolRequest: prompt.contextActionModel(toolRequestContext),
                workTrace: prompt.contextActionModel(workTraceContext),
                workspaceFile: prompt.contextActionModel(workspaceFileContext),
                loose: prompt.contextActionModel({{ label: 'Loose note' }})
              }},
              copyCatalog: {{
                resultNodes: catalog.selectedContextCopy('result_nodes'),
                evidenceReport: catalog.selectedContextCopy('evidence_report'),
                workspaceFile: catalog.selectedContextCopy('workspace_file'),
                sourceAlias: catalog.selectedContextCopy('tool_intent'),
                loose: catalog.selectedContextCopy('loose-kind')
              }},
              materialSet: {{
                count: materialSet.length,
                kinds: materialSet.map((item) => item.context_kind),
                hasPromptText: materialSet.map((item) => Object.prototype.hasOwnProperty.call(item, 'prompt_text')),
                nodeOnlyHasPromptText: Object.prototype.hasOwnProperty.call(materialSet[2] || {{}}, 'prompt_text'),
                originalUnchanged: JSON.stringify(nodeOnlyContext) === nodeOnlyOriginal
              }},
              promptOnlyToolRequest: prompt.selectedMaterialSet([promptOnlyToolRequestContext])[0],
              promptOnlyToolRequestTray: prompt.composerTrayViewModel(prompt.selectedMaterialSet([promptOnlyToolRequestContext])),
              looseStringMaterial: prompt.selectedMaterialSet(['Loose lab note about rs429358'])[0],
              looseStringTray: prompt.composerTrayViewModel(prompt.selectedMaterialSet(['Loose lab note about rs429358'])),
              evidenceReportTray: prompt.composerTrayViewModel(prompt.selectedMaterialSet([evidenceReportContext])),
              workspaceFileTray: prompt.composerTrayViewModel(prompt.selectedMaterialSet([workspaceFileContext])),
              serverProvidedToolRequestTray: prompt.composerTrayViewModel(prompt.selectedMaterialSet([serverProvidedToolRequestContext])),
              trayModel: prompt.composerTrayViewModel(prompt.selectedMaterialSet([evidenceContext, toolRequestContext])),
              genomeTrayModel: prompt.composerTrayViewModel([genomeContext]),
              frontendFallbackPrompt: prompt.suggestedPromptForContexts([evidenceContext]),
              emptyFallbackPrompt: prompt.suggestedPromptForContexts([]),
              rebuilt,
              addReturns: {{
                resultKind: addResultReturn && addResultReturn.context_kind,
                sourceKind: addToolRequestReturn && addToolRequestReturn.context_kind,
                invalid: addInvalidReturn
              }},
              askWithOne: {{
                promptValue: askPromptValue,
                returnedKind: askWithReturn && askWithReturn.context_kind,
                submittedCount: submitted ? submitted.length : 0,
                submittedKinds: submitted ? submitted.map((item) => item.context_kind) : [],
                submittedLabels: submitted ? submitted.map((item) => item.label) : [],
                afterAskCount: afterAskSnapshot.length,
                afterSuccessCount: afterSuccessSnapshot.length,
                remainingKind: afterSuccessSnapshot[0] ? afterSuccessSnapshot[0].context_kind : null,
                focused: askFocused
              }},
              draftWithLedger: {{
                promptValue: draftPromptEl.value,
                returnedKind: draftWithReturn && draftWithReturn.context_kind,
                snapshotCount: afterDraftSnapshot.length,
                snapshotKinds: afterDraftSnapshot.map((item) => item.context_kind),
                lastKind: afterDraftSnapshot[afterDraftSnapshot.length - 1] && afterDraftSnapshot[afterDraftSnapshot.length - 1].context_kind,
                lastLabel: afterDraftSnapshot[afterDraftSnapshot.length - 1] && afterDraftSnapshot[afterDraftSnapshot.length - 1].label,
                lastHasPromptText: Object.prototype.hasOwnProperty.call(lastDraftItem, 'prompt_text'),
                focused: draftFocused
              }},
              askNewWithFile: {{
                promptValue: newConversationPromptValue,
                returnedKind: askNewWithReturn && askNewWithReturn.context_kind,
                submittedCount: newConversationSubmitted ? newConversationSubmitted.length : 0,
                submittedKinds: newConversationSubmitted ? newConversationSubmitted.map((item) => item.context_kind) : [],
                submittedLabels: newConversationSubmitted ? newConversationSubmitted.map((item) => item.label) : [],
                message: newConversationOptions && newConversationOptions.message,
                afterSuccessCount: afterNewConversationSuccessSnapshot.length,
                focused: newConversationFocused
              }}
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(len(result["evidenceNodes"]), 2)
        self.assertIn("[redacted local path]", result["evidenceNodes"][0]["label"])
        self.assertIn("[redacted local path]", result["evidenceNodes"][0]["text"])
        self.assertIn("[redacted local path]", result["evidenceNodes"][0]["value"])
        self.assertEqual(result["actionModels"]["evidence"]["kindLabel"], "Evidence")
        self.assertEqual(result["actionModels"]["evidence"]["askLabel"], "Ask about evidence")
        self.assertEqual(result["actionModels"]["evidenceReport"]["kindLabel"], "Evidence")
        self.assertEqual(result["actionModels"]["evidenceReport"]["askLabel"], "Ask about evidence")
        self.assertEqual(result["actionModels"]["toolRequest"]["askLabel"], "Ask with source")
        self.assertEqual(result["actionModels"]["workTrace"]["askLabel"], "Ask about this work")
        self.assertEqual(result["actionModels"]["workspaceFile"]["kindLabel"], "Project file")
        self.assertEqual(result["actionModels"]["workspaceFile"]["askLabel"], "Ask about file")
        self.assertEqual(result["actionModels"]["loose"]["askLabel"], "Ask about evidence")
        self.assertEqual(result["copyCatalog"]["resultNodes"]["kindLabel"], "Evidence")
        self.assertEqual(result["copyCatalog"]["resultNodes"]["selectedItemNoun"], "evidence item")
        self.assertEqual(result["copyCatalog"]["evidenceReport"]["summaryIncludedLabel"], "Evidence report summary included")
        self.assertEqual(result["copyCatalog"]["workspaceFile"]["kindLabel"], "Project file")
        self.assertEqual(result["copyCatalog"]["workspaceFile"]["selectedItemPluralNoun"], "file details")
        self.assertEqual(result["copyCatalog"]["sourceAlias"]["selectedItemPluralNoun"], "source details")
        self.assertEqual(result["copyCatalog"]["loose"]["kindLabel"], "Evidence")
        self.assertEqual(result["materialSet"]["count"], 3)
        self.assertEqual(result["materialSet"]["kinds"], ["result_nodes", "tool_request", "result_nodes"])
        self.assertEqual(result["materialSet"]["hasPromptText"], [False, False, False])
        self.assertFalse(result["materialSet"]["nodeOnlyHasPromptText"])
        self.assertTrue(result["materialSet"]["originalUnchanged"])
        self.assertEqual(result["promptOnlyToolRequest"]["label"], "Evidence source: Target evidence report")
        self.assertIn("Attached evidence source: Target evidence report", result["promptOnlyToolRequest"]["prompt_text"])
        self.assertNotIn("Prepared", result["promptOnlyToolRequest"]["prompt_text"])
        self.assertEqual(result["looseStringMaterial"]["label"], "Selected material")
        self.assertEqual(result["looseStringTray"]["items"][0]["label"], "Selected material")
        self.assertEqual(result["looseStringTray"]["items"][0]["kindLabel"], "Evidence")
        self.assertEqual(result["looseStringTray"]["items"][0]["preview"], "Loose lab note about rs429358")
        self.assertEqual(result["promptOnlyToolRequestTray"]["items"][0]["label"], "Evidence source: Target evidence report")
        self.assertEqual(result["promptOnlyToolRequestTray"]["items"][0]["nodeCountLabel"], "Evidence source included")
        self.assertEqual(result["promptOnlyToolRequestTray"]["items"][0]["action"]["askLabel"], "Ask with source")
        self.assertEqual(result["promptOnlyToolRequestTray"]["items"][0]["action"]["draftLabel"], "Draft question")
        self.assertEqual(result["evidenceReportTray"]["items"][0]["kindLabel"], "Evidence")
        self.assertEqual(result["evidenceReportTray"]["items"][0]["nodeCountLabel"], "1 selected evidence item")
        self.assertEqual(result["evidenceReportTray"]["items"][0]["action"]["askLabel"], "Ask about evidence")
        self.assertEqual(result["evidenceReportTray"]["items"][0]["action"]["draftLabel"], "Draft from evidence")
        self.assertEqual(result["workspaceFileTray"]["items"][0]["kindLabel"], "Project file")
        self.assertEqual(result["workspaceFileTray"]["items"][0]["source"], "Project file")
        self.assertEqual(result["workspaceFileTray"]["items"][0]["nodeCountLabel"], "2 selected file details")
        self.assertEqual(result["workspaceFileTray"]["items"][0]["action"]["askLabel"], "Ask about file")
        self.assertEqual(result["workspaceFileTray"]["items"][0]["action"]["draftLabel"], "Draft from file")
        self.assertNotIn("genomi.portal.workspace_file", json.dumps(result["workspaceFileTray"]))
        self.assertNotIn("research.build_target_packet", json.dumps(result["promptOnlyToolRequestTray"]))
        self.assertEqual(result["serverProvidedToolRequestTray"]["items"][0]["label"], "Evidence source: Add a genome")
        self.assertNotIn("Genomi Parse Source", json.dumps(result["serverProvidedToolRequestTray"]))
        self.assertEqual(result["trayModel"]["countLabel"], "2 included items")
        self.assertEqual(result["trayModel"]["items"][0]["kindLabel"], "Evidence")
        self.assertEqual(result["trayModel"]["items"][0]["source"], "Variant lookup")
        self.assertEqual(result["trayModel"]["items"][0]["action"]["askLabel"], "Ask about evidence")
        self.assertEqual(result["trayModel"]["items"][0]["action"]["draftLabel"], "Draft from evidence")
        self.assertEqual(result["trayModel"]["items"][0]["preview"], "Variant lookup summary keeps rs429358.evidence token")
        self.assertEqual(result["trayModel"]["items"][0]["nodeCountLabel"], "2 selected evidence items")
        self.assertEqual(result["trayModel"]["items"][0]["envelopeState"], "Data returned")
        self.assertEqual(result["trayModel"]["items"][0]["nodes"][0]["label"], "Coverage from [redacted local path]")
        self.assertEqual(result["trayModel"]["items"][0]["nodes"][1]["label"], "Variant lookup guidance")
        self.assertEqual(result["trayModel"]["items"][0]["nodes"][1]["text"], "preserve rs429358.evidence prior")
        self.assertEqual(result["trayModel"]["items"][1]["kindLabel"], "Evidence source")
        self.assertEqual(result["trayModel"]["items"][1]["source"], "Target evidence report")
        self.assertEqual(result["trayModel"]["items"][1]["action"]["askLabel"], "Ask with source")
        self.assertEqual(result["trayModel"]["items"][1]["action"]["draftLabel"], "Draft question")
        self.assertIn("rs429358.evidence", json.dumps(result["trayModel"]))
        self.assertNotIn("research.build_target_packet", json.dumps(result["trayModel"]))
        self.assertNotIn("variant.resolve", json.dumps(result["trayModel"]))
        self.assertEqual(result["genomeTrayModel"]["items"][0]["source"], "Active genome")
        self.assertFalse(result["genomeTrayModel"]["items"][0]["action"]["askEnabled"])
        self.assertFalse(result["genomeTrayModel"]["items"][0]["action"]["draftEnabled"])
        self.assertEqual(result["genomeTrayModel"]["items"][0]["action"]["askLabel"], "")
        self.assertEqual(result["genomeTrayModel"]["items"][0]["action"]["draftLabel"], "")
        self.assertEqual(result["genomeTrayModel"]["items"][0]["nodes"][0]["label"], "Current genome / Build")
        self.assertEqual(result["genomeTrayModel"]["items"][0]["nodes"][0]["text"], "GRCh38")
        self.assertEqual(
            result["frontendFallbackPrompt"],
            "Use the included evidence to answer my message. Preserve provenance, source limits, and genome privacy boundaries.",
        )
        self.assertEqual(result["emptyFallbackPrompt"], "")
        self.assertEqual(result["rebuilt"]["context_kind"], "evidence_panel")
        self.assertEqual(result["rebuilt"]["selected_nodes"][0]["label"], "variant.resolve guidance")
        self.assertNotIn("prompt_text", result["rebuilt"])
        self.assertEqual(result["addReturns"]["resultKind"], "result_nodes")
        self.assertEqual(result["addReturns"]["sourceKind"], "tool_request")
        self.assertIsNone(result["addReturns"]["invalid"])
        self.assertEqual(result["askWithOne"]["promptValue"], "Server suggested prompt for result_nodes,tool_request")
        self.assertEqual(result["askWithOne"]["returnedKind"], "result_nodes")
        self.assertEqual(result["askWithOne"]["submittedCount"], 2)
        self.assertEqual(result["askWithOne"]["submittedKinds"], ["result_nodes", "tool_request"])
        self.assertEqual(result["askWithOne"]["submittedLabels"], ["Variant result", "Evidence source: Target evidence report"])
        self.assertEqual(result["askWithOne"]["afterAskCount"], 2)
        self.assertEqual(result["askWithOne"]["afterSuccessCount"], 0)
        self.assertIsNone(result["askWithOne"]["remainingKind"])
        self.assertGreaterEqual(result["askWithOne"]["focused"], 1)
        self.assertEqual(result["draftWithLedger"]["promptValue"], "Server suggested prompt for result_nodes,tool_request,evidence_ledger")
        self.assertEqual(result["draftWithLedger"]["returnedKind"], "evidence_ledger")
        self.assertEqual(result["draftWithLedger"]["snapshotCount"], 3)
        self.assertEqual(result["draftWithLedger"]["snapshotKinds"], ["result_nodes", "tool_request", "evidence_ledger"])
        self.assertEqual(result["draftWithLedger"]["lastKind"], "evidence_ledger")
        self.assertEqual(result["draftWithLedger"]["lastLabel"], "Evidence map summary")
        self.assertFalse(result["draftWithLedger"]["lastHasPromptText"])
        self.assertGreaterEqual(result["draftWithLedger"]["focused"], 1)
        self.assertEqual(result["askNewWithFile"]["promptValue"], "")
        self.assertEqual(result["askNewWithFile"]["returnedKind"], "workspace_file")
        self.assertEqual(result["askNewWithFile"]["submittedCount"], 1)
        self.assertEqual(result["askNewWithFile"]["submittedKinds"], ["workspace_file"])
        self.assertEqual(result["askNewWithFile"]["submittedLabels"], ["Project file: reports/apoe.md"])
        self.assertEqual(result["askNewWithFile"]["message"], "Server suggested new conversation for workspace_file")
        self.assertEqual(result["askNewWithFile"]["afterSuccessCount"], 0)
        self.assertGreaterEqual(result["askNewWithFile"]["focused"], 1)
        self.assertNotIn("Prepared", json.dumps(result))
        self.assertIsNone(_PRIVATE_PROMPT_RE.search(json.dumps(result)))

    def test_server_prompt_suggestion_owns_typed_context_wording(self) -> None:
        payload = portal_prompt_suggestions.prompt_suggestion_payload(
            {
                "selectedEvidence": [
                    {
                        "id": "ev-1",
                        "label": "Variant result at /Users/matthewzmd/.genomi/private.json",
                        "context_kind": "result_nodes",
                        "source_operation": "variant.resolve",
                        "selected_nodes": [{"label": "ClinVar", "text": "ClinVar: risk factor"}],
                    },
                    {
                        "id": "ev-2",
                        "label": "Evidence",
                        "context_kind": "evidence_panel",
                        "source_operation": "pharmacogenomics.review_medication",
                        "selected_nodes": [{"label": "CPIC", "text": "CPIC: CYP2C19 guideline"}],
                    },
                ]
            }
        )

        self.assertEqual(payload["context_count"], 2)
        result_copy = portal_selected_context_catalog.selected_context_copy("result_nodes")
        report_copy = portal_selected_context_catalog.selected_context_copy("evidence_report")
        request_kinds = portal_selected_context_catalog.source_request_kinds()
        self.assertEqual(result_copy.prompt_group_label, "selected Genomi result facts")
        self.assertEqual(report_copy.prompt_group_label, "selected Genomi evidence report")
        self.assertEqual(result_copy.selected_item_plural_noun, "evidence items")
        self.assertIn("tool_request", request_kinds)
        self.assertIn("tool_intent", request_kinds)
        self.assertIn("selected Genomi result facts from variant lookup", payload["prompt"])
        self.assertIn("selected Genomi evidence from medication-response review", payload["prompt"])
        self.assertIn("Selected items: ClinVar and CPIC.", payload["prompt"])
        self.assertNotIn("variant.resolve", payload["prompt"])
        self.assertNotIn("pharmacogenomics.review_medication", payload["prompt"])
        self.assertIn("answer my question", payload["prompt"])
        self.assertEqual(payload["selected_evidence"][0]["label"], "Variant result at [redacted local path]")
        self.assertIsNone(_PRIVATE_PROMPT_RE.search(json.dumps(payload)))

    def test_server_prompt_suggestion_handles_request_artifact_and_empty_contexts(self) -> None:
        request_payload = portal_prompt_suggestions.prompt_suggestion_payload(
            {
                "selected_evidence": [
                    {
                        "context_kind": "tool_request",
                        "source_operation": "research.build_target_packet",
                        "prompt_text": "Prepared evidence-source request",
                    }
                ]
            }
        )
        evidence_report_payload = portal_prompt_suggestions.prompt_suggestion_payload(
            {
                "selectedEvidence": [
                    {
                        "context_kind": "evidence_report",
                        "label": "Evidence report: rs429358",
                        "source_operation": "research.build_target_packet",
                        "selected_nodes": [{"label": "clinvar · ClinVar", "text": "Available · Variant clinical assertions"}],
                    }
                ]
            }
        )
        artifact_payload = portal_prompt_suggestions.prompt_suggestion_payload(
            {
                "items": [
                    {
                        "context_kind": "artifact",
                        "label": "Evidence report",
                        "prompt_text": "Artifact summary",
                    }
                ]
            }
        )
        workspace_file_payload = portal_prompt_suggestions.prompt_suggestion_payload(
            {
                "items": [
                    {
                        "context_kind": "workspace_file",
                        "label": "Project file: reports/apoe.md",
                        "source_operation": "genomi.portal.workspace_file",
                        "selected_nodes": [
                            {"label": "File", "text": "Project file / File: reports/apoe.md"},
                            {
                                "label": "Visible preview excerpt",
                                "text": "Project file / Visible preview excerpt: APOE notes",
                            },
                        ],
                    }
                ]
            }
        )
        empty_payload = portal_prompt_suggestions.prompt_suggestion_payload({"selectedEvidence": []})

        self.assertIn("selected Genomi evidence source for target evidence report", request_payload["prompt"])
        self.assertNotIn("research.build_target_packet", request_payload["prompt"])
        self.assertIn("supplied request parameters", request_payload["prompt"])
        self.assertIn("selected Genomi evidence report from target evidence report", evidence_report_payload["prompt"])
        self.assertIn("Selected items: clinvar · ClinVar.", evidence_report_payload["prompt"])
        self.assertIn("answer my question", evidence_report_payload["prompt"])
        self.assertNotIn("research.build_target_packet", evidence_report_payload["prompt"])
        self.assertIn("Review this Genomi artifact", artifact_payload["prompt"])
        self.assertIn("Use this project file as selected research material", workspace_file_payload["prompt"])
        self.assertNotIn("genomi.portal.workspace_file", workspace_file_payload["prompt"])
        self.assertEqual(workspace_file_payload["selected_evidence"][0]["context_kind"], "workspace_file")
        self.assertEqual(empty_payload["prompt"], "")


class PortalSelectedEvidenceSanitizerTest(unittest.TestCase):
    def test_clean_selected_evidence_preserves_selected_context_metadata_without_raw_payloads(self) -> None:
        cleaned = portal_turns.clean_selected_evidence(
            [
                {
                    "id": "ev-1",
                    "label": "Variant evidence at /Users/matthewzmd/.genomi/private.json",
                    "context_kind": "evidence_panel",
                    "finding_state": "data_returned",
                    "answer_readiness": "answer_supported",
                    "source_operation": "variant.resolve",
                    "tool_call_id": "call-variant",
                    "tool_result_id": "result-variant",
                    "operation": "variant.resolve",
                    "tool_name": "variant.resolve",
                    "node_count": 7,
                    "selected_node_count": 99,
                    "prompt_text": "Selected evidence from variant.resolve:\n- ClinVar row",
                    "selected_nodes": [{"label": "ClinVar", "text": "ClinVar: risk_factor"}],
                    "evidence_envelope": {
                        "finding_state": "browser_payload_should_not_be_authority",
                        "registry_file": "/Users/matthewzmd/.genomi/registry.json",
                    },
                    "payload": {"agi_path": "/Users/matthewzmd/.genomi/private.sqlite"},
                    "raw_payload": {"context_file": "/Users/matthewzmd/.genomi/context.json"},
                    "unredacted_payload": {"path": "/tmp/private.json"},
                }
            ]
        )

        self.assertEqual(len(cleaned), 1)
        item = cleaned[0]
        self.assertEqual(item["label"], "Variant evidence at [redacted local path]")
        self.assertEqual(item["context_kind"], "evidence_panel")
        self.assertEqual(item["finding_state"], "data_returned")
        self.assertEqual(item["answer_readiness"], "answer_supported")
        self.assertEqual(item["source_operation"], "variant.resolve")
        self.assertEqual(item["tool_call_id"], "call-variant")
        self.assertEqual(item["tool_result_id"], "result-variant")
        self.assertEqual(item["operation"], "variant.resolve")
        self.assertEqual(item["tool_name"], "variant.resolve")
        self.assertEqual(item["node_count"], 7)
        self.assertEqual(item["selected_node_count"], 1)
        self.assertEqual(item["selected_nodes"][0]["label"], "ClinVar")
        self.assertFalse({"evidence_envelope", "payload", "raw_payload", "unredacted_payload"} & set(item))
        self.assertIsNone(_PRIVATE_PROMPT_RE.search(json.dumps(item)))


def _run_node_json(test_case: unittest.TestCase, script: str):
    if shutil.which("node") is None:
        test_case.skipTest("node is required for frontend module tests")
    completed = subprocess.run(
        ["node", "--input-type=module"],
        input=script,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)
