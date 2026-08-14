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


class PortalArtifactSelectionFrontendTest(unittest.TestCase):
    def test_generic_selection_inspector_defaults_to_selected_material(self) -> None:
        inspector_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_selection_inspector.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const inspector = await import(__INSPECTOR_URL__);
            __DOM_SHIM__

            const container = document.createElement('div');
            const model = inspector.selectedNodeInspectorModel([
              { dataset: { context: 'rs429358 evidence note', value: 'rs429358' } }
            ]);
            inspector.renderSelectedNodeInspector(container, model);
            process.stdout.write(JSON.stringify({
              title: model.title,
              heading: container.querySelector('.genomi-selection-inspector-head span').textContent,
              group: container.querySelector('.genomi-selection-inspector-node span').textContent,
              label: container.querySelector('.genomi-selection-inspector-node strong').textContent,
              text: container.querySelector('.genomi-selection-inspector-node p').textContent
            }));
            """
        ).replace("__INSPECTOR_URL__", json.dumps(inspector_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["title"], "1 selected item")
        self.assertEqual(result["heading"], "Selected material")
        self.assertEqual(result["group"], "Material")
        self.assertEqual(result["label"], "Selected material")
        self.assertEqual(result["text"], "rs429358 evidence note")

    def test_artifact_selection_inspector_model_redacts_selected_nodes(self) -> None:
        selection_url = (
            Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_artifact_selection.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const selection = await import({selection_url!r});
            const selectedNode = {{
              dataset: {{
                label: 'Trace from /Users/matthewzmd/.genomi/private.json',
                context: 'Trace context_file=/Users/matthewzmd/.genomi/context.json',
                value: '/tmp/private-trace.json'
              }}
            }};
            const unselectedNode = {{
              dataset: {{
                label: 'Unselected',
                context: 'Unselected context',
                value: 'unselected'
              }}
            }};
            const root = {{
              querySelectorAll(selector) {{
                if (selector === '.artifact-node[data-selectable="true"]') return [selectedNode, unselectedNode];
                if (selector === '.artifact-node[data-selectable="true"].selected') return [selectedNode];
                return [];
              }}
            }};
            process.stdout.write(JSON.stringify({{
              selectionModel: selection.artifactSelectionModel(root),
              inspectorModel: selection.artifactSelectionInspectorModel(root)
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["selectionModel"]["totalNodes"], 2)
        self.assertEqual(result["selectionModel"]["selectedCount"], 1)
        self.assertEqual(result["selectionModel"]["summary"], "1 selected artifact item")
        self.assertEqual(result["inspectorModel"]["title"], "1 selected artifact item")
        self.assertEqual(result["inspectorModel"]["nodes"][0]["group"], "Artifact")
        self.assertIn("[redacted local path]", result["inspectorModel"]["nodes"][0]["label"])
        self.assertIn("[redacted local path]", result["inspectorModel"]["nodes"][0]["text"])
        self.assertIn("[redacted local path]", result["inspectorModel"]["nodes"][0]["value"])
        self.assertIsNone(_PRIVATE_PROMPT_RE.search(json.dumps(result)))

    def test_rendered_artifact_selection_uses_canonical_selected_nodes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        artifacts_url = (root / "src/genomi/interfaces/templates/portal_artifacts.js").as_uri()
        selection_url = (root / "src/genomi/interfaces/templates/portal_artifact_selection.js").as_uri()
        script = textwrap.dedent(
            """
            const artifacts = await import(__ARTIFACTS_URL__);
            const selection = await import(__SELECTION_URL__);
            __DOM_SHIM__

            const container = document.createElement('div');
            let used = null;
            let asked = null;
            let askedNew = null;
            let drafted = null;
            const artifact = {
              id: 'art_select',
              kind: 'decode_dashboard',
              renderer: 'decode_dashboard',
              title: 'Selection artifact',
              status: 'completed',
              operation: 'decode.render_dashboard',
              summary_lines: ['context_file=/Users/matthewzmd/.genomi/private-context.json'],
              url: '/Users/matthewzmd/.genomi/private-artifact.html',
              preview_url: '/api/artifacts/art_select/file'
            };

            artifacts.renderArtifactPreview(container, artifact, {
              baseUrl: window.location.href,
              onUseContext: (payload) => { used = payload; },
              onAskContext: (payload) => { asked = payload; },
              onAskNewContext: (payload) => { askedNew = payload; },
              onDraftContext: (payload) => { drafted = payload; }
            });
            const shell = container.querySelector('.artifact-preview-shell');
            const useSelection = container.querySelector('[data-testid="genomi-artifact-use-selection"]');
            const askNewConversation = container.querySelector('[data-testid="genomi-artifact-start-conversation"]');
            const askSelection = container.querySelector('[data-testid="genomi-artifact-ask-selection"]');
            const draftSelection = container.querySelector('[data-testid="genomi-artifact-draft-selection"]');
            const initialUseLabel = useSelection ? useSelection.textContent : '';
            const askNewConversationLabel = askNewConversation ? askNewConversation.textContent : '';
            const initialAskLabel = askSelection ? askSelection.textContent : '';
            const initialDraftLabel = draftSelection ? draftSelection.textContent : '';
            const selectionBar = container.querySelector('[data-artifact-selection-bar]');
            const selectionBarHiddenInitially = selectionBar ? selectionBar.hidden : false;
            const summaryNode = container.querySelectorAll('.artifact-node[data-selectable="true"]')
              .find((node) => node.dataset.label === 'Summary');
            if (summaryNode) summaryNode.click();
            const canonicalAfterClick = selection.artifactSelectedNodes(shell);
            const inspectorModelAfterClick = selection.artifactSelectionInspectorModel(shell);
            const inspector = container.querySelector('[data-artifact-selection-inspector]');
            const selectionBarLabel = container.querySelector('[data-artifact-selection-bar] span');
            const summaryNodeSelectedAfterClick = summaryNode ? summaryNode.classList.contains('selected') : false;
            const selectionLabelAfterClick = selectionBarLabel ? selectionBarLabel.textContent : '';
            const selectionBarHiddenAfterClick = selectionBar ? selectionBar.hidden : true;
            const selectedUseLabel = useSelection ? useSelection.textContent : '';
            const selectedAskLabel = askSelection ? askSelection.textContent : '';
            const selectedDraftLabel = draftSelection ? draftSelection.textContent : '';
            const inspectorTextAfterClick = inspector && inspector.querySelector('p') ? inspector.querySelector('p').textContent : '';
            if (useSelection) useSelection.click();
            if (askNewConversation) askNewConversation.click();

            const selectAll = container.querySelector('[data-testid="genomi-artifact-select-nodes"]');
            if (selectAll) selectAll.click();
            const allNodeCount = shell.querySelectorAll('.artifact-node').length;
            const selectableNodeCount = shell.querySelectorAll('.artifact-node[data-selectable="true"]').length;
            const staticNodeCount = shell.querySelectorAll('.artifact-node[data-selectable="false"]').length;
            const selectedNodeCount = shell.querySelectorAll('.artifact-node[data-selectable="true"].selected').length;
            const selectAllModel = selection.artifactSelectionModel(shell);
            if (askSelection) askSelection.click();
            if (draftSelection) draftSelection.click();

            const clear = container.querySelector('[data-testid="genomi-artifact-clear-selection"]');
            if (clear) clear.click();
            const clearModel = selection.artifactSelectionModel(shell);
            const inspectorAfterClear = container.querySelector('[data-artifact-selection-inspector]');
            const clearedUseLabel = useSelection ? useSelection.textContent : '';
            const clearedAskLabel = askSelection ? askSelection.textContent : '';
            const clearedDraftLabel = draftSelection ? draftSelection.textContent : '';

            process.stdout.write(JSON.stringify({
              summaryNodeFound: Boolean(summaryNode),
              initialUseLabel,
              askNewConversationLabel,
              selectionBarHiddenInitially,
              selectionBarHiddenAfterClick,
              initialAskLabel,
              initialDraftLabel,
              selectedUseLabel,
              selectedAskLabel,
              selectedDraftLabel,
              summaryNodeSelected: summaryNodeSelectedAfterClick,
              selectionLabelAfterClick,
              inspectorText: inspectorTextAfterClick,
              inspectorModelNode: inspectorModelAfterClick && inspectorModelAfterClick.nodes[0],
              canonicalAfterClick,
              usedSelectedNodes: used ? used.selected_nodes : [],
              askedNewSelectedNodes: askedNew ? askedNew.selected_nodes : [],
              askedNewPrompt: askedNew ? askedNew.prompt_text : '',
              usedPrompt: used ? used.prompt_text : '',
              allNodeCount,
              selectableNodeCount,
              staticNodeCount,
              selectedNodeCount,
              selectAllSelectedCount: selectAllModel.selectedCount,
              askedNodeCount: asked && Array.isArray(asked.selected_nodes) ? asked.selected_nodes.length : 0,
              draftedNodeCount: drafted && Array.isArray(drafted.selected_nodes) ? drafted.selected_nodes.length : 0,
              draftedPrompt: drafted ? drafted.prompt_text : '',
              clearSelectedCount: clearModel.selectedCount,
              selectionLabelAfterClear: selectionBarLabel ? selectionBarLabel.textContent : '',
              clearedUseLabel,
              clearedAskLabel,
              clearedDraftLabel,
              inspectorHiddenAfterClear: inspectorAfterClear ? inspectorAfterClear.hidden : false,
              selectionBarHiddenAfterClear: selectionBar ? selectionBar.hidden : false
            }));
            """
        ).replace("__ARTIFACTS_URL__", json.dumps(artifacts_url)).replace(
            "__SELECTION_URL__", json.dumps(selection_url)
        ).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertTrue(result["summaryNodeFound"])
        self.assertEqual(result["initialUseLabel"], "Use report")
        self.assertEqual(result["askNewConversationLabel"], "Start conversation")
        self.assertTrue(result["selectionBarHiddenInitially"])
        self.assertFalse(result["selectionBarHiddenAfterClick"])
        self.assertEqual(result["initialAskLabel"], "Ask about report")
        self.assertEqual(result["initialDraftLabel"], "Draft from report")
        self.assertEqual(result["selectedUseLabel"], "Use selected report")
        self.assertEqual(result["selectedAskLabel"], "Ask about selected report")
        self.assertEqual(result["selectedDraftLabel"], "Draft from selected report")
        self.assertTrue(result["summaryNodeSelected"])
        self.assertEqual(result["selectionLabelAfterClick"], "1 selected report item")
        self.assertEqual(len(result["canonicalAfterClick"]), 1)
        self.assertEqual(result["usedSelectedNodes"], result["canonicalAfterClick"])
        self.assertEqual(
            [node["label"] for node in result["askedNewSelectedNodes"]],
            ["Artifact", "Status", "Summary"],
        )
        self.assertNotEqual(result["askedNewSelectedNodes"], result["canonicalAfterClick"])
        self.assertIn("Selection artifact", result["askedNewPrompt"])
        self.assertEqual(result["inspectorModelNode"]["label"], result["canonicalAfterClick"][0]["label"])
        self.assertEqual(result["inspectorModelNode"]["text"], result["canonicalAfterClick"][0]["text"])
        self.assertEqual(result["inspectorModelNode"]["value"], result["canonicalAfterClick"][0]["value"])
        self.assertIn("[redacted local path]", result["inspectorText"])
        self.assertIn("Selected report: Selection artifact", result["usedPrompt"])
        self.assertIn("Selected report: Selection artifact", result["askedNewPrompt"])
        self.assertGreater(result["allNodeCount"], result["selectableNodeCount"])
        self.assertGreater(result["staticNodeCount"], 0)
        self.assertEqual(result["selectedNodeCount"], result["selectableNodeCount"])
        self.assertEqual(result["selectAllSelectedCount"], result["selectableNodeCount"])
        self.assertEqual(result["askedNodeCount"], result["selectableNodeCount"])
        self.assertEqual(result["draftedNodeCount"], result["selectableNodeCount"])
        self.assertIn("Selected report: Selection artifact", result["draftedPrompt"])
        self.assertEqual(result["clearSelectedCount"], 0)
        self.assertEqual(result["selectionLabelAfterClear"], "Using the report summary")
        self.assertEqual(result["clearedUseLabel"], "Use report")
        self.assertEqual(result["clearedAskLabel"], "Ask about report")
        self.assertEqual(result["clearedDraftLabel"], "Draft from report")
        self.assertTrue(result["inspectorHiddenAfterClear"])
        self.assertTrue(result["selectionBarHiddenAfterClear"])
        self.assertIsNone(_PRIVATE_PROMPT_RE.search(json.dumps(result)))

    def test_rendered_artifact_selection_uses_server_surface_copy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        artifacts_url = (root / "src/genomi/interfaces/templates/portal_artifacts.js").as_uri()
        script = textwrap.dedent(
            """
            const artifacts = await import(__ARTIFACTS_URL__);
            __DOM_SHIM__

            const container = document.createElement('div');
            artifacts.renderArtifactPreview(container, {
              id: 'art_server_copy',
              kind: 'note',
              renderer: 'markdown',
              title: 'Server copy artifact',
              status: 'completed',
              artifact_presentation: {
                schema: 'genomi_portal_artifact_presentation',
                family: 'evidence_report',
                category: 'evidence',
                surface_copy: {
                  noun: 'report',
                  summary_noun: 'server report summary',
                  selected_item: 'server evidence item',
                  selected_items: 'server evidence items',
                  selected_heading: 'Selected server evidence',
                  selected_group: 'Server evidence report',
                  use_label: 'Use server report',
                  ask_label: 'Ask server report',
                  draft_label: 'Draft server report',
                  open_label: 'Open server report',
                  label_prefix: 'Server evidence report',
                  prompt_intro_prefix: 'Selected server evidence report',
                  context_kind: 'evidence_report',
                  node_context_prefix: 'Server evidence report'
                }
              },
              summary_lines: ['completed'],
              preview_url: '/api/projects/proj_1/artifacts/art_server_copy/file'
            }, {
              baseUrl: window.location.href,
              onUseContext: () => {},
              onAskContext: () => {},
              onDraftContext: () => {}
            });
            const selectionBarLabel = container.querySelector('[data-artifact-selection-bar] span');
            process.stdout.write(JSON.stringify({
              useLabel: container.querySelector('[data-testid="genomi-artifact-use-selection"]').textContent,
              askLabel: container.querySelector('[data-testid="genomi-artifact-ask-selection"]').textContent,
              draftLabel: container.querySelector('[data-testid="genomi-artifact-draft-selection"]').textContent,
              summaryLabel: selectionBarLabel ? selectionBarLabel.textContent : ''
            }));
            """
        ).replace("__ARTIFACTS_URL__", json.dumps(artifacts_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["useLabel"], "Use server report")
        self.assertEqual(result["askLabel"], "Ask server report")
        self.assertEqual(result["draftLabel"], "Draft server report")
        self.assertEqual(result["summaryLabel"], "Using the server report summary")


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
            this.textContent = '';
            this.hidden = false;
            this.classList = new ClassList(this);
          }
          appendChild(child) {
            child.parentNode = this;
            this.children.push(child);
            return child;
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
            if (name.startsWith('data-')) {
              const key = dataKey(name.slice(5));
              return Object.prototype.hasOwnProperty.call(this.dataset, key) ? this.dataset[key] : null;
            }
            return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
          }
          addEventListener(type, handler) {
            this.eventListeners[type] = this.eventListeners[type] || [];
            this.eventListeners[type].push(handler);
          }
          click() {
            (this.eventListeners.click || []).forEach((handler) => handler({
              preventDefault() {},
              stopPropagation() {}
            }));
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
          set innerHTML(value) {
            this.children = [];
            this.textContent = '';
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
          const parts = String(selector || '').trim().split(/\\s+/).filter(Boolean);
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
          const clean = String(selector || '');
          const attrs = [...clean.matchAll(/\\[([^=\\]]+)(?:="([^"]*)")?\\]/g)];
          const withoutAttrs = clean.replace(/\\[[^\\]]+\\]/g, '');
          const pieces = withoutAttrs.split('.');
          const tag = pieces[0];
          if (tag && tag !== element.tagName) return false;
          const classesMatch = pieces.slice(1).filter(Boolean).every((name) => element.classList.contains(name));
          if (!classesMatch) return false;
          return attrs.every((attr) => {
            const value = element.getAttribute(attr[1]);
            return attr[2] === undefined ? value !== null : value === attr[2];
          });
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
