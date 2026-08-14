import { selectedDomNodes } from './portal_selected_evidence.js';
import { RESULT_SELECTION_CHANGE_EVENT, syncResultToolbarSelection } from './portal_result_selection.js';
import { applySelectionActionLabels, selectionActionLabels, selectedSurfaceActionLabels } from './portal_selection_actions.js';
import { renderSelectedNodeInspector, selectedNodeInspectorModel } from './portal_selection_inspector.js';

const LEDGER_SELECTED_NODE_SELECTOR = '.evidence-node.selected, .result-node.selected';
const LEDGER_NESTED_INSPECTOR_SELECTOR = '.evidence-node-inspector, .genomi-result-inspector';

export function ledgerSelectedNodes(root) {
  if (!root || typeof root.querySelectorAll !== 'function') return [];
  return selectedDomNodes(root, LEDGER_SELECTED_NODE_SELECTOR);
}

export function ledgerSelectionModel(root, selectedNodes = ledgerSelectedNodes(root)) {
  const selectedCount = selectedNodes.length;
  return {
    selectedCount,
    mode: selectedCount ? 'selected_nodes' : 'ledger_result',
    summary: selectedCount
      ? selectedCount + ' selected evidence item' + (selectedCount === 1 ? '' : 's')
      : 'Full evidence result selected'
  };
}

export function ledgerSelectionInspectorModel(selectedNodes) {
  return selectedNodeInspectorModel(selectedNodes, {
    defaultLabel: 'Selected evidence item',
    defaultGroup: 'Current evidence',
    singularTitle: 'selected evidence item',
    pluralTitle: 'selected evidence items'
  });
}

export function ledgerSelectionControlsMarkup() {
  return [
    '<div class="selection-bar evidence-ledger-selection-bar" data-ledger-selection-bar>',
    '<span></span>',
    '<div class="selection-actions evidence-ledger-selection-actions">',
    '<button class="tool-action" type="button" data-action="use" data-testid="genomi-ledger-use-selection"></button>',
    '<button class="tool-action" type="button" data-action="ask" data-testid="genomi-ledger-ask-selection"></button>',
    '<button class="tool-action" type="button" data-action="draft" data-testid="genomi-ledger-draft-selection"></button>',
    '<button class="tool-action" type="button" data-testid="genomi-ledger-clear-selection">Clear</button>',
    '</div>',
    '</div>',
    '<div class="genomi-selection-inspector evidence-ledger-selection-inspector" data-ledger-selection-inspector hidden></div>'
  ].join('');
}

export function installLedgerSelectionControls(root, options = {}) {
  if (!root) return;
  root.querySelectorAll('.evidence-node, .result-node').forEach((node) => {
    node.addEventListener('click', () => updateLedgerSelectionBar(root));
  });
  root.addEventListener(RESULT_SELECTION_CHANGE_EVENT, () => updateLedgerSelectionBar(root));
  const use = root.querySelector('[data-testid="genomi-ledger-use-selection"]');
  if (use) {
    use.addEventListener('click', (event) => {
      event.stopPropagation();
      if (typeof options.onUseSelection === 'function') options.onUseSelection();
    });
  }
  const ask = root.querySelector('[data-testid="genomi-ledger-ask-selection"]');
  if (ask) {
    ask.addEventListener('click', (event) => {
      event.stopPropagation();
      if (typeof options.onAskSelection === 'function') options.onAskSelection();
    });
  }
  const draft = root.querySelector('[data-testid="genomi-ledger-draft-selection"]');
  if (draft) {
    draft.addEventListener('click', (event) => {
      event.stopPropagation();
      if (typeof options.onDraftSelection === 'function') options.onDraftSelection();
    });
  }
  const clear = root.querySelector('[data-testid="genomi-ledger-clear-selection"]');
  if (clear) {
    clear.addEventListener('click', (event) => {
      event.stopPropagation();
      clearLedgerNodeSelection(root);
    });
  }
  updateLedgerSelectionBar(root);
}

export function clearLedgerNodeSelection(root) {
  if (!root || typeof root.querySelectorAll !== 'function') return;
  root.querySelectorAll(LEDGER_SELECTED_NODE_SELECTOR).forEach((node) => node.classList.remove('selected'));
  root.querySelectorAll(LEDGER_NESTED_INSPECTOR_SELECTOR).forEach((inspector) => {
    renderSelectedNodeInspector(inspector, null);
  });
  root.querySelectorAll('.genomi-result-view').forEach((panel) => syncResultToolbarSelection(panel));
  updateLedgerSelectionBar(root);
}

export function updateLedgerSelectionBar(root) {
  if (!root) return;
  const selectedNodes = ledgerSelectedNodes(root);
  const model = ledgerSelectionModel(root, selectedNodes);
  const bar = root.querySelector('[data-ledger-selection-bar]');
  if (bar) {
    const label = bar.querySelector('span');
    if (label) label.textContent = model.summary;
    applySelectionActionLabels(bar, selectionActionLabels(
      model.selectedCount,
      'ledger',
      {
        ...selectedSurfaceActionLabels('selected evidence items'),
        use: 'Attach selected evidence',
        draft: 'Draft with selected evidence'
      }
    ));
    const clear = bar.querySelector('[data-testid="genomi-ledger-clear-selection"]');
    if (clear) clear.disabled = model.selectedCount === 0;
  }
  renderSelectedNodeInspector(
    root.querySelector('[data-ledger-selection-inspector]'),
    ledgerSelectionInspectorModel(selectedNodes),
    { heading: 'Selected evidence' }
  );
}
