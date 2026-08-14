from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

_PRIVATE_PROMPT_RE = re.compile(
    r"(?:context_file|registry_file|agi_path|/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes|~)"
)


class PortalEvidenceLedgerSelectionFrontendTest(unittest.TestCase):
    def test_ledger_selection_model_redacts_selected_nodes(self) -> None:
        selection_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_evidence_ledger_selection.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const selection = await import({selection_url!r});
            const selectedEvidenceNode = {{
              dataset: {{
                label: 'Coverage from /Users/matthewzmd/.genomi/private.json',
                context: 'Coverage context_file=/Users/matthewzmd/.genomi/context.json',
                value: '/tmp/private-coverage.json'
              }}
            }};
            const selectedResultNode = {{
              dataset: {{
                label: 'ClinVar row',
                context: 'ClinVar row: risk factor',
                value: 'risk factor'
              }}
            }};
            const root = {{
              querySelectorAll(selector) {{
                if (selector === '.evidence-node.selected, .result-node.selected') return [selectedEvidenceNode, selectedResultNode];
                return [];
              }}
            }};
            process.stdout.write(JSON.stringify({{
              selected: selection.ledgerSelectedNodes(root),
              model: selection.ledgerSelectionModel(root),
              inspector: selection.ledgerSelectionInspectorModel(selection.ledgerSelectedNodes(root))
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(len(result["selected"]), 2)
        self.assertEqual(result["model"]["selectedCount"], 2)
        self.assertEqual(result["model"]["summary"], "2 selected evidence items")
        self.assertEqual(result["inspector"]["title"], "2 selected evidence items")
        self.assertIn("[redacted local path]", result["selected"][0]["label"])
        self.assertIn("[redacted local path]", result["selected"][0]["text"])
        self.assertIsNone(_PRIVATE_PROMPT_RE.search(json.dumps(result)))

    def test_ledger_detail_selection_updates_bar_and_payload(self) -> None:
        root = Path(__file__).resolve().parents[1]
        ledger_url = (root / "src/genomi/interfaces/templates/portal_evidence_ledger.js").as_uri()
        selection_url = (root / "src/genomi/interfaces/templates/portal_evidence_ledger_selection.js").as_uri()
        script = textwrap.dedent(
            """
            const ledger = await import(__LEDGER_URL__);
            const selection = await import(__SELECTION_URL__);
            __DOM_SHIM__

            const list = document.createElement('div');
            const detail = document.createElement('div');
            let used = null;
            let asked = null;
            let drafted = null;
            const ledgerSurface = ledger.createEvidenceLedger({
              container: list,
              detailContainer: detail,
              onUseContext: (payload) => { used = payload; },
              onAskContext: (payload) => { asked = payload; },
              onDraftContext: (payload) => { drafted = payload; },
              onAskFollowUp: () => {}
            });
            const envelope = {
              finding_state: 'data_returned',
              answer_readiness: 'answer_supported',
              guidance: ['data_returned:use_variant_evidence'],
              coverage: { consulted_libraries: ['ClinVar'] },
              observations: { variant: 'rs429358' }
            };
            const variantPresentation = {
              schema: 'genomi_portal_result_presentation',
              source: 'server',
              operation: 'variant.resolve',
              kind: 'variant',
              kicker: 'Variant evidence map',
              title: 'rs429358',
              summary: 'variant.resolve: data_returned',
              evidenceEnvelope: envelope,
              metrics: [{ label: 'Resolved', value: 1 }, { label: 'ClinVar', value: 1 }],
              lanes: [{
                title: 'ClinVar records',
                nodes: [{
                  label: 'rs429358',
                  summary: 'risk_factor',
                  context: 'ClinVar records / rs429358: risk_factor',
                  value: { rsid: 'rs429358', clinical_significance: 'risk_factor' }
                }]
              }]
            };
            const record = {
              call: { id: 'call_variant', name: 'variant.resolve', input: { rsid: 'rs429358' } },
              result: {
                id: 'result_variant',
                name: 'variant.resolve',
                payload: {
                  headline: 'variant.resolve: data_returned',
                  status: 'completed',
                  evidence_envelope: envelope,
                  query: { rsid: 'rs429358' },
                  resolved_targets: [{ rsid: 'rs429358', resolution_status: 'identifier' }],
                  public_context: {
                    clinvar_by_rsid: [{ rsid: 'rs429358', clinical_significance: 'risk_factor' }]
                  }
                },
                portal_presentation: variantPresentation
              }
            };
            ledgerSurface.upsert(record);

            const panel = detail.querySelector('.evidence-ledger-detail-panel');
            const bar = detail.querySelector('[data-ledger-selection-bar]');
            const initialBar = bar.querySelector('span').textContent;
            const use = detail.querySelector('[data-testid="genomi-ledger-use-selection"]');
            const ask = detail.querySelector('[data-testid="genomi-ledger-ask-selection"]');
            const draft = detail.querySelector('[data-testid="genomi-ledger-draft-selection"]');
            const initialUseLabel = use ? use.textContent : '';
            const initialAskLabel = ask ? ask.textContent : '';
            const initialDraftLabel = draft ? draft.textContent : '';
            const node = detail.querySelector('.result-node');
            if (node) node.click();
            const selected = selection.ledgerSelectedNodes(panel);
            const selectedBar = bar.querySelector('span').textContent;
            const selectedUseLabel = use ? use.textContent : '';
            const selectedAskLabel = ask ? ask.textContent : '';
            const selectedDraftLabel = draft ? draft.textContent : '';
            const inspector = detail.querySelector('[data-ledger-selection-inspector]');
            const inspectorHiddenSelected = inspector ? inspector.hidden : true;
            const inspectorTextSelected = inspector ? inspector.textContent : '';
            const resultInspector = detail.querySelector('.genomi-result-inspector');
            const resultInspectorHiddenSelected = resultInspector ? resultInspector.hidden : true;
            const resultInspectorTextSelected = resultInspector ? resultInspector.textContent : '';
            if (use) use.click();
            if (ask) ask.click();
            if (draft) draft.click();
            const clear = detail.querySelector('[data-testid="genomi-ledger-clear-selection"]');
            if (clear) clear.click();
            const clearedBar = bar.querySelector('span').textContent;
            const clearedSelected = selection.ledgerSelectedNodes(panel);
            const resultInspectorHiddenCleared = resultInspector ? resultInspector.hidden : false;
            const resultInspectorTextCleared = resultInspector ? resultInspector.textContent : '';

            process.stdout.write(JSON.stringify({
              hasPanel: Boolean(panel),
              hasBar: Boolean(bar),
              initialBar,
              initialUseLabel,
              initialAskLabel,
              initialDraftLabel,
              selectedCount: selected.length,
              selectedBar,
              selectedUseLabel,
              selectedAskLabel,
              selectedDraftLabel,
              inspectorHiddenSelected,
              inspectorTextSelected,
              resultInspectorHiddenSelected,
              resultInspectorTextSelected,
              usedNodes: used ? used.selected_nodes : [],
              usedPrompt: used ? used.prompt_text : '',
              askedNodes: asked ? asked.selected_nodes : [],
              askedPrompt: asked ? asked.prompt_text : '',
              draftedNodes: drafted ? drafted.selected_nodes : [],
              draftedPrompt: drafted ? drafted.prompt_text : '',
              clearedBar,
              clearedCount: clearedSelected.length,
              resultInspectorHiddenCleared,
              resultInspectorTextCleared
            }));
            """
        ).replace("__LEDGER_URL__", json.dumps(ledger_url)).replace(
            "__SELECTION_URL__", json.dumps(selection_url)
        ).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertTrue(result["hasPanel"])
        self.assertTrue(result["hasBar"])
        self.assertEqual(result["initialBar"], "Full evidence result selected")
        self.assertEqual(result["initialUseLabel"], "Attach evidence to chat")
        self.assertEqual(result["initialAskLabel"], "Ask about current evidence")
        self.assertEqual(result["initialDraftLabel"], "Draft with current evidence")
        self.assertEqual(result["selectedCount"], 1)
        self.assertEqual(result["selectedBar"], "1 selected evidence item")
        self.assertEqual(result["selectedUseLabel"], "Attach selected evidence")
        self.assertEqual(result["selectedAskLabel"], "Ask about selected evidence")
        self.assertEqual(result["selectedDraftLabel"], "Draft with selected evidence")
        self.assertFalse(result["inspectorHiddenSelected"])
        self.assertIn("Selected evidence", result["inspectorTextSelected"])
        self.assertFalse(result["resultInspectorHiddenSelected"])
        self.assertIn("Selected result", result["resultInspectorTextSelected"])
        self.assertEqual(len(result["usedNodes"]), 1)
        self.assertIn("Selected evidence: Variant lookup", result["usedPrompt"])
        self.assertIn("rs429358", result["usedPrompt"])
        self.assertEqual(result["askedNodes"], result["usedNodes"])
        self.assertEqual(result["askedPrompt"], result["usedPrompt"])
        self.assertEqual(result["draftedNodes"], result["usedNodes"])
        self.assertEqual(result["draftedPrompt"], result["usedPrompt"])
        self.assertEqual(result["clearedBar"], "Full evidence result selected")
        self.assertEqual(result["clearedCount"], 0)
        self.assertTrue(result["resultInspectorHiddenCleared"])
        self.assertEqual(result["resultInspectorTextCleared"], "")
        self.assertIsNone(_PRIVATE_PROMPT_RE.search(json.dumps(result)))

    def test_ledger_detail_bulk_result_selection_updates_selection_bar(self) -> None:
        root = Path(__file__).resolve().parents[1]
        ledger_url = (root / "src/genomi/interfaces/templates/portal_evidence_ledger.js").as_uri()
        selection_url = (root / "src/genomi/interfaces/templates/portal_evidence_ledger_selection.js").as_uri()
        script = textwrap.dedent(
            """
            const ledger = await import(__LEDGER_URL__);
            const selection = await import(__SELECTION_URL__);
            __DOM_SHIM__

            const list = document.createElement('div');
            const detail = document.createElement('div');
            let used = null;
            const ledgerSurface = ledger.createEvidenceLedger({
              container: list,
              detailContainer: detail,
              onUseContext: (payload) => { used = payload; },
              onAskContext: () => {},
              onDraftContext: () => {},
              onAskFollowUp: () => {}
            });
            const envelope = {
              finding_state: 'data_returned',
              answer_readiness: 'answer_supported',
              coverage: { consulted_libraries: ['ClinVar', 'GWAS Catalog'] }
            };
            const record = {
              call: { id: 'call_variant', name: 'variant.resolve', input: { rsid: 'rs429358' } },
              result: {
                id: 'result_variant',
                name: 'variant.resolve',
                payload: {
                  headline: 'variant.resolve: data_returned',
                  status: 'completed',
                  evidence_envelope: envelope
                },
                portal_presentation: {
                  schema: 'genomi_portal_result_presentation',
                  source: 'server',
                  operation: 'variant.resolve',
                  kind: 'variant',
                  kicker: 'Variant evidence map',
                  title: 'rs429358',
                  summary: 'variant.resolve: data_returned',
                  evidenceEnvelope: envelope,
                  metrics: [{ label: 'Resolved', value: 1 }],
                  lanes: [{
                    title: 'Evidence records',
                    nodes: [
                      { label: 'ClinVar rs429358', summary: 'risk_factor', context: 'ClinVar rs429358: risk_factor', value: { source: 'ClinVar' } },
                      { label: 'GWAS rs429358', summary: 'LDL association', context: 'GWAS rs429358: LDL association', value: { source: 'GWAS' } },
                      { label: 'dbSNP rs429358', summary: 'identifier', context: 'dbSNP rs429358: identifier', value: { source: 'dbSNP' } }
                    ]
                  }]
                }
              }
            };
            ledgerSurface.upsert(record);

            const panel = detail.querySelector('.evidence-ledger-detail-panel');
            const bar = detail.querySelector('[data-ledger-selection-bar]');
            const toolbar = detail.querySelector('[data-testid="genomi-result-toolbar"]');
            const selectShown = detail.querySelector('[data-toolbar-action="select-shown"]');
            const use = detail.querySelector('[data-testid="genomi-ledger-use-selection"]');
            const before = {
              bar: bar.querySelector('span').textContent,
              selected: toolbar.dataset.selectedCount,
              visibleSelectable: toolbar.dataset.visibleSelectableCount
            };
            selectShown.click();
            const after = {
              bar: bar.querySelector('span').textContent,
              selected: toolbar.dataset.selectedCount,
              selectedCount: selection.ledgerSelectedNodes(panel).length
            };
            use.click();
            process.stdout.write(JSON.stringify({ before, after, used }));
            """
        ).replace("__LEDGER_URL__", json.dumps(ledger_url)).replace(
            "__SELECTION_URL__", json.dumps(selection_url)
        ).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["before"]["bar"], "Full evidence result selected")
        self.assertEqual(result["before"]["selected"], "0")
        self.assertEqual(result["before"]["visibleSelectable"], "3")
        self.assertEqual(result["after"]["bar"], "3 selected evidence items")
        self.assertEqual(result["after"]["selected"], "3")
        self.assertEqual(result["after"]["selectedCount"], 3)
        self.assertEqual(len(result["used"]["selected_nodes"]), 3)
        self.assertEqual(result["used"]["finding_state"], "data_returned")
        self.assertEqual(result["used"]["answer_readiness"], "answer_supported")
        self.assertIn("ClinVar rs429358", result["used"]["prompt_text"])
        self.assertIsNone(_PRIVATE_PROMPT_RE.search(json.dumps(result)))

    def test_ledger_scope_filters_records_to_current_frame(self) -> None:
        root = Path(__file__).resolve().parents[1]
        ledger_url = (root / "src/genomi/interfaces/templates/portal_evidence_ledger.js").as_uri()
        script = textwrap.dedent(
            """
            const ledger = await import(__LEDGER_URL__);
            __DOM_SHIM__

            const list = document.createElement('div');
            const detail = document.createElement('div');
            const ledgerSurface = ledger.createEvidenceLedger({
              container: list,
              detailContainer: detail,
              onUseContext: () => {},
              onAskContext: () => {},
              onDraftContext: () => {},
              onAskFollowUp: () => {}
            });
            function variantPresentation(rsid) {
              const envelope = {
                finding_state: 'data_returned',
                answer_readiness: 'answer_supported',
                coverage: { consulted_libraries: ['ClinVar'] },
                observations: { variant: rsid }
              };
              return {
                schema: 'genomi_portal_result_presentation',
                source: 'server',
                operation: 'variant.resolve',
                kind: 'variant',
                kicker: 'Variant evidence map',
                title: rsid,
                summary: 'variant.resolve: data_returned',
                evidenceEnvelope: envelope,
                metrics: [{ label: 'Resolved', value: 1 }],
                lanes: [{
                  title: 'Resolved targets',
                  nodes: [{
                    label: rsid,
                    summary: 'identifier',
                    context: 'Resolved targets / ' + rsid + ': identifier',
                    value: { rsid }
                  }]
                }]
              };
            }
            function record(frameId, rsid) {
              return {
                scope: { frameId, runId: 'run_' + frameId, messageId: rsid === 'rs429358' ? 'msg_saved' : '' },
                call: { id: 'call_' + frameId, name: 'variant.resolve', input: { rsid } },
                result: {
                  id: 'result_' + frameId,
                  name: 'variant.resolve',
                  payload: {
                    headline: 'variant.resolve: data_returned',
                    status: 'completed',
                    evidence_envelope: {
                      finding_state: 'data_returned',
                      answer_readiness: 'answer_supported',
                      coverage: { consulted_libraries: ['ClinVar'] },
                      observations: { variant: rsid }
                    },
                    query: { rsid },
                    resolved_targets: [{ rsid }]
                  },
                  portal_presentation: variantPresentation(rsid)
                }
              };
            }
            ledgerSurface.setScope({ frameId: 'frame_a', label: 'Conversation A' });
            ledgerSurface.upsert({
              call: { id: 'call_unscoped', name: 'variant.resolve', input: { rsid: 'rs999' } },
              result: {
                id: 'result_unscoped',
                name: 'variant.resolve',
                payload: {
                  headline: 'variant.resolve: data_returned',
                  status: 'completed',
                  evidence_envelope: {
                    finding_state: 'data_returned',
                    answer_readiness: 'answer_supported',
                    coverage: { consulted_libraries: ['ClinVar'] },
                    observations: { variant: 'rs999' }
                  },
                  query: { rsid: 'rs999' },
                  resolved_targets: [{ rsid: 'rs999' }]
                },
                portal_presentation: variantPresentation('rs999')
              }
            });
            const afterUnscoped = ledgerSurface.count();
            ledgerSurface.upsert(record('frame_b', 'rs7412'));
            const afterMismatch = ledgerSurface.count();
            const mismatchText = list.textContent;
            ledgerSurface.upsert(record('frame_a', 'rs429358'));
            const afterMatch = ledgerSurface.count();
            const matchText = list.textContent;
            ledgerSurface.setScope({ frameId: 'frame_b', label: 'Conversation B' });
            const afterSwitch = ledgerSurface.count();
            const switchText = list.textContent;
            const switchDetailText = detail.textContent;
            process.stdout.write(JSON.stringify({ afterUnscoped, afterMismatch, mismatchText, afterMatch, matchText, afterSwitch, switchText, switchDetailText }));
            """
        ).replace("__LEDGER_URL__", json.dumps(ledger_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["afterUnscoped"], 0)
        self.assertEqual(result["afterMismatch"], 0)
        self.assertIn("No current evidence yet", result["mismatchText"])
        self.assertIn("Conversation A", result["mismatchText"])
        self.assertEqual(result["afterMatch"], 1)
        self.assertIn("Current evidence from Conversation A", result["matchText"])
        self.assertIn("1 evidence result", result["matchText"])
        self.assertIn("1 restored from saved work history", result["matchText"])
        self.assertIn("Variant lookup", result["matchText"])
        self.assertEqual(result["afterSwitch"], 1)
        self.assertIn("Conversation B", result["switchText"])
        self.assertIn("rs7412", result["switchDetailText"])
        self.assertNotIn("rs429358", result["switchText"])
        self.assertNotIn("rs429358", result["switchDetailText"])


def _dom_shim_script() -> str:
    return textwrap.dedent(
        """
        class ClassList {
          constructor(element) { this.element = element; }
          items() { return String(this.element.className || '').split(/\\s+/).filter(Boolean); }
          set(items) { this.element.className = [...new Set(items)].join(' '); }
          add(...names) { this.set([...this.items(), ...names.filter(Boolean)]); }
          remove(...names) { this.set(this.items().filter((item) => !names.includes(item))); }
          contains(name) { return this.items().includes(name); }
          toggle(name, force) {
            const active = force === undefined ? !this.contains(name) : Boolean(force);
            if (active) this.add(name);
            else this.remove(name);
            return active;
          }
        }

        class Element {
          constructor(tagName) {
            this.tagName = String(tagName || '').toLowerCase();
            this.children = [];
            this.parentNode = null;
            this.attributes = {};
            this.dataset = {};
            this.eventListeners = {};
            this.className = '';
            this._textContent = '';
            this.hidden = false;
            this.disabled = false;
            this.classList = new ClassList(this);
          }
          set textContent(value) {
            this._textContent = String(value || '');
          }
          get textContent() {
            return this._textContent + this.children.map((child) => child.textContent).join('');
          }
          appendChild(child) {
            child.parentNode = this;
            this.children.push(child);
            return child;
          }
          remove() {
            if (!this.parentNode) return;
            this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
            this.parentNode = null;
          }
          setAttribute(name, value) {
            const text = String(value);
            this.attributes[name] = text;
            if (name === 'class') this.className = text;
            if (name === 'id') this.id = text;
            if (name.startsWith('data-')) this.dataset[dataKey(name.slice(5))] = text;
          }
          getAttribute(name) {
            if (name === 'class') return this.className;
            return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
          }
          addEventListener(type, handler) {
            this.eventListeners[type] = this.eventListeners[type] || [];
            this.eventListeners[type].push(handler);
          }
          dispatchEvent(event) {
            const type = event && event.type;
            const typed = {
              ...event,
              type,
              preventDefault() {},
              stopPropagation() {}
            };
            (this.eventListeners[type] || []).forEach((handler) => handler(typed));
          }
          click() {
            this.dispatchEvent({ type: 'click' });
          }
          closest(selector) {
            let node = this;
            while (node) {
              if (matches(node, selector)) return node;
              node = node.parentNode;
            }
            return null;
          }
          querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
          querySelectorAll(selector) { return querySelectorAll(this, selector); }
          insertAdjacentHTML(_position, html) {
            parseHtml(String(html || ''), this);
          }
          set innerHTML(value) {
            this.children = [];
            this._textContent = '';
            parseHtml(String(value || ''), this);
          }
          get innerHTML() { return ''; }
        }

        function dataKey(name) {
          return name.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
        }

        function descendants(node) {
          const found = [];
          node.children.forEach((child) => {
            found.push(child);
            found.push(...descendants(child));
          });
          return found;
        }

        function querySelectorAll(root, selector) {
          const alternatives = String(selector || '').split(',').map((item) => item.trim()).filter(Boolean);
          if (alternatives.length > 1) {
            return [...new Set(alternatives.flatMap((item) => querySelectorAll(root, item)))];
          }
          const parts = alternatives[0] ? alternatives[0].split(/\\s+/).filter(Boolean) : [];
          let current = [root];
          parts.forEach((part) => {
            const next = [];
            current.forEach((node) => {
              descendants(node).forEach((child) => {
                if (matches(child, part)) next.push(child);
              });
            });
            current = next;
          });
          return current;
        }

        function matches(element, selector) {
          const attr = String(selector || '').match(/^\\[([^=\\]]+)(?:="([^"]*)")?\\]$/);
          if (attr) {
            const value = element.getAttribute(attr[1]);
            return attr[2] === undefined ? value !== null : value === attr[2];
          }
          const pieces = String(selector || '').split('.');
          const tag = pieces[0];
          if (tag && tag !== element.tagName) return false;
          return pieces.slice(1).every((name) => element.classList.contains(name));
        }

        function parseHtml(html, root) {
          const tags = /<\\/?[^>]+>/g;
          const stack = [root];
          let match;
          while ((match = tags.exec(html))) {
            const token = match[0];
            if (/^<\\//.test(token)) {
              if (stack.length > 1) stack.pop();
              continue;
            }
            const parsed = token.match(/^<([a-zA-Z0-9-]+)([^>]*)>/);
            if (!parsed) continue;
            const child = new Element(parsed[1]);
            const attrs = parsed[2] || '';
            const attrPattern = /([a-zA-Z0-9:-]+)(?:="([^"]*)")?/g;
            let attr;
            while ((attr = attrPattern.exec(attrs))) child.setAttribute(attr[1], attr[2] || '');
            stack[stack.length - 1].appendChild(child);
            if (!/\\/>$/.test(token) && !['br', 'hr', 'img', 'input', 'link', 'meta'].includes(child.tagName)) {
              stack.push(child);
            }
          }
        }

        globalThis.document = { createElement: (tagName) => new Element(tagName) };
        globalThis.window = { location: { href: 'http://127.0.0.1:8768/projects/proj_1' } };
        """
    )


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
