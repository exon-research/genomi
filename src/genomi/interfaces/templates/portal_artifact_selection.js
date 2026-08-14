import { selectedDomNodes } from './portal_selected_evidence.js';
import { artifactSurfaceCopy } from './portal_artifact_display_model.js';
import {
  applySelectionActionLabels,
  createSelectionActionButton,
  selectionActionLabels,
  selectionFallbackLabels,
  selectedSurfaceActionLabels
} from './portal_selection_actions.js';
import { selectedNodeInspectorModel, renderSelectedNodeInspector } from './portal_selection_inspector.js';

const ARTIFACT_NODE_SELECTOR = '.artifact-node[data-selectable="true"]';
const SELECTED_ARTIFACT_NODE_SELECTOR = '.artifact-node[data-selectable="true"].selected';

export function artifactSelectedNodes(root) {
  return root && typeof root.querySelectorAll === 'function'
    ? selectedDomNodes(root, SELECTED_ARTIFACT_NODE_SELECTOR)
    : [];
}

export function artifactSelectionControlsMarkup() {
  return [
    '<div class="selection-bar artifact-selection-bar" data-artifact-selection-bar data-testid="genomi-artifact-selection-bar">',
    '<span></span>',
    '<div class="selection-actions artifact-selection-actions" data-artifact-selection-actions></div>',
    '</div>',
    '<div class="artifact-selection-inspector genomi-selection-inspector" data-artifact-selection-inspector data-testid="genomi-artifact-selection-inspector" hidden></div>'
  ].join('');
}

export function installArtifactSelectionControls(shell, handlers = {}) {
  if (!shell) return;
  const actions = shell.querySelector('[data-artifact-selection-actions]');
  if (!actions) return;
  const copy = artifactSelectionCopy(shell);
  actions.innerHTML = '';
  actions.appendChild(selectionAction('use', 'genomi-artifact-use-selection', '', handlers.onUseSelection, {
    label: copy.useLabel
  }));
  if (typeof handlers.onAskSelection === 'function') {
    actions.appendChild(selectionAction(
      'ask',
      'genomi-artifact-ask-selection',
      'Use selected ' + copy.selectedItems + ' in a focused assistant question',
      handlers.onAskSelection,
      { label: copy.askLabel }
    ));
  }
  if (typeof handlers.onDraftSelection === 'function') {
    actions.appendChild(selectionAction(
      'draft',
      'genomi-artifact-draft-selection',
      'Write a draft question from selected ' + copy.selectedItems + ' without sending it',
      handlers.onDraftSelection,
      { label: copy.draftLabel }
    ));
  }
  actions.appendChild(selectionAction('select', 'genomi-artifact-select-nodes', '', () => selectAllArtifactNodes(shell), { label: 'Select all' }));
  actions.appendChild(selectionAction('clear', 'genomi-artifact-clear-selection', '', () => clearArtifactNodeSelection(shell), { label: 'Clear' }));
  updateArtifactSelectionBar(shell);
}

export function selectAllArtifactNodes(shell) {
  if (!shell || typeof shell.querySelectorAll !== 'function') return;
  shell.querySelectorAll(ARTIFACT_NODE_SELECTOR).forEach((node) => node.classList.add('selected'));
  updateArtifactSelectionBar(shell);
}

export function clearArtifactNodeSelection(shell) {
  if (!shell || typeof shell.querySelectorAll !== 'function') return;
  shell.querySelectorAll(SELECTED_ARTIFACT_NODE_SELECTOR).forEach((node) => node.classList.remove('selected'));
  updateArtifactSelectionBar(shell);
}

export function artifactSelectionModel(root, selectedNodes = artifactSelectedNodes(root)) {
  const copy = artifactSelectionCopy(root);
  const totalNodes = root && typeof root.querySelectorAll === 'function' ? root.querySelectorAll(ARTIFACT_NODE_SELECTOR).length : 0;
  const selectedCount = selectedNodes.length;
  return {
    totalNodes,
    selectedCount,
    mode: selectedCount ? 'selected_nodes' : 'artifact_summary',
    summary: selectedCount
      ? selectedCount + ' selected ' + (selectedCount === 1 ? copy.selectedItem : copy.selectedItems)
      : totalNodes
        ? 'Using the ' + copy.summaryNoun
        : sentenceCase(copy.summaryNoun) + ' only'
  };
}

export function artifactSelectionInspectorModel(root, selectedNodes = artifactSelectedNodes(root)) {
  const copy = artifactSelectionCopy(root);
  return selectedNodeInspectorModel(selectedNodes, {
    defaultLabel: sentenceCase(copy.selectedItem),
    defaultGroup: copy.selectedGroup,
    singularTitle: 'selected ' + copy.selectedItem,
    pluralTitle: 'selected ' + copy.selectedItems
  });
}

export function updateArtifactSelectionBar(shell) {
  if (!shell) return;
  const bar = shell.querySelector('[data-artifact-selection-bar]');
  if (!bar) return;
  const selectedNodes = artifactSelectedNodes(shell);
  const model = artifactSelectionModel(shell, selectedNodes);
  bar.hidden = model.selectedCount === 0;
  const label = bar.querySelector('span');
  if (label) label.textContent = model.summary;
  applySelectionActionLabels(
    bar,
    selectionActionLabels(
      model.selectedCount,
      artifactSelectionFallbackLabels(shell),
      artifactSelectionSelectedLabels(shell)
    )
  );
  renderSelectedNodeInspector(
    shell.querySelector('[data-artifact-selection-inspector]'),
    artifactSelectionInspectorModel(shell, selectedNodes),
    { heading: artifactSelectionCopy(shell).selectedHeading }
  );
}

function artifactSelectionCopy(root) {
  const family = root && root.dataset ? root.dataset.artifactFamily : '';
  return artifactSurfaceCopy(family || {});
}

function artifactSelectionFallbackLabels(root) {
  const copy = artifactSelectionCopy(root);
  return {
    use: copy.useLabel,
    ask: copy.askLabel,
    draft: copy.draftLabel
  };
}

function artifactSelectionSelectedLabels(root) {
  return selectedSurfaceActionLabels(artifactSelectionCopy(root).selectedItems);
}

function sentenceCase(value) {
  const text = String(value || '').trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : '';
}

function selectionAction(action, testId, title, onClick, options = {}) {
  return createSelectionActionButton({
    action,
    testId,
    title,
    label: options.label || selectionFallbackLabels('artifact')[action],
    onClick: () => {
      if (typeof onClick === 'function') onClick();
    }
  });
}
