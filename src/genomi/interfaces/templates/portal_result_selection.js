import { formatContextValue } from './portal_format.js';
import { promptSafeText } from './portal_selected_evidence.js';
import { renderSelectedNodeInspector, selectedNodeInspectorModel } from './portal_selection_inspector.js';

export const RESULT_SELECTION_CHANGE_EVENT = 'genomi-result-selection-change';

export function selectShownResultNodes(panel) {
  if (!panel) return;
  selectedResultNodes(panel).forEach((node) => node.classList.remove('selected'));
  visibleSelectableResultNodes(panel).forEach((node) => node.classList.add('selected'));
  renderResultSelectionInspector(panel);
  syncResultToolbarSelection(panel);
  notifyResultSelectionChanged(panel);
}

export function clearResultSelection(panel) {
  if (!panel) return;
  selectedResultNodes(panel).forEach((node) => node.classList.remove('selected'));
  renderResultSelectionInspector(panel);
  syncResultToolbarSelection(panel);
  notifyResultSelectionChanged(panel);
}

export function selectableResultNodes(panel) {
  if (!panel || typeof panel.querySelectorAll !== 'function') return [];
  return [...panel.querySelectorAll('.result-node')]
    .filter((node) => node.dataset.selectable === 'true');
}

export function visibleSelectableResultNodes(panel) {
  return selectableResultNodes(panel)
    .filter((node) => !node.hidden && !(node.closest('.genomi-result-lane') && node.closest('.genomi-result-lane').hidden));
}

export function selectedResultNodes(panel) {
  return selectableResultNodes(panel).filter((node) => node.classList.contains('selected'));
}

export function selectedResultNodePayloads(panel) {
  return selectedResultNodes(panel)
    .map((node) => ({
      label: promptSafeText(node.dataset.label || 'Selected item'),
      text: promptSafeText(node.dataset.context || node.dataset.value || ''),
      value: promptSafeText(node.dataset.value || '')
    }))
    .filter((node) => node.text);
}

export function syncResultToolbarSelection(panel) {
  if (!panel) return;
  const toolbar = panel.querySelector('.genomi-result-toolbar');
  if (!toolbar) return;
  const selectedCount = selectedResultNodes(panel).length;
  const visibleCount = visibleSelectableResultNodes(panel).length;
  const selectShown = toolbar.querySelector('[data-toolbar-action="select-shown"]');
  const clearSelected = toolbar.querySelector('[data-toolbar-action="clear-selected"]');
  if (selectShown) selectShown.disabled = visibleCount === 0;
  if (clearSelected) clearSelected.disabled = selectedCount === 0;
  toolbar.dataset.selectedCount = String(selectedCount);
  toolbar.dataset.visibleSelectableCount = String(visibleCount);
}

export function resultSelectionInspectorModel(selectedNodes) {
  const model = selectedNodeInspectorModel(selectedNodes, {
    defaultLabel: 'Selected result',
    defaultGroup: 'Result lane',
    groupDatasetKey: 'lane',
    singularTitle: 'selected result item',
    pluralTitle: 'selected result items'
  });
  if (!model) return null;
  return {
    ...model,
    nodes: model.nodes.map((item) => ({ ...item, lane: item.group }))
  };
}

export function renderResultSelectionInspector(panel) {
  if (!panel) return;
  const inspector = panel.querySelector('.genomi-result-inspector');
  if (!inspector) return;
  const model = resultSelectionInspectorModel(selectedResultNodes(panel));
  renderSelectedNodeInspector(inspector, model, { heading: 'Selected result' });
}

export function notifyResultSelectionChanged(panel) {
  let node = panel;
  const detail = { source: panel };
  while (node) {
    if (typeof node.dispatchEvent === 'function') dispatchSelectionEvent(node, detail);
    node = node.parentNode;
  }
}

export function resultNodeSearchText(item, laneTitle) {
  return normalizeSearchText([
    laneTitle,
    item && item.label,
    item && item.summary,
    item && item.context,
    item && formatContextValue(item.value)
  ].filter(Boolean).join(' '));
}

export function normalizeSearchText(value) {
  return String(value || '').toLowerCase().replace(/\s+/g, ' ').trim();
}

function dispatchSelectionEvent(target, detail) {
  const event = typeof CustomEvent === 'function'
    ? new CustomEvent(RESULT_SELECTION_CHANGE_EVENT, { detail })
    : { type: RESULT_SELECTION_CHANGE_EVENT, detail };
  target.dispatchEvent(event);
}
