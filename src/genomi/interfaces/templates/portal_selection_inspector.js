import { promptSafeText } from './portal_selected_evidence.js';

export function selectedNodeInspectorModel(selectedNodes, options = {}) {
  const maxNodes = options.maxNodes || 6;
  const nodes = [...(selectedNodes || [])]
    .map((item) => selectedNodeInspectorItem(item, options))
    .filter((item) => item.text);
  if (!nodes.length) return null;
  const singular = options.singularTitle || 'selected item';
  const plural = options.pluralTitle || singular + 's';
  return {
    count: nodes.length,
    title: nodes.length + ' ' + (nodes.length === 1 ? singular : plural),
    nodes: nodes.slice(0, maxNodes),
    overflow: Math.max(0, nodes.length - maxNodes)
  };
}

export function renderSelectedNodeInspector(inspector, model, options = {}) {
  if (!inspector) return;
  inspector.innerHTML = '';
  inspector.hidden = !model;
  if (!model) return;

  const head = document.createElement('div');
  head.className = 'genomi-selection-inspector-head';
  head.innerHTML = '<span></span><strong></strong>';
  head.querySelector('span').textContent = options.heading || 'Selected material';
  head.querySelector('strong').textContent = model.title;
  inspector.appendChild(head);

  const list = document.createElement('div');
  list.className = 'genomi-selection-inspector-list';
  model.nodes.forEach((item) => list.appendChild(selectedNodeInspectorElement(item)));
  inspector.appendChild(list);

  if (model.overflow) {
    const more = document.createElement('div');
    more.className = 'genomi-selection-inspector-more';
    more.textContent = '+' + model.overflow + ' more selected';
    inspector.appendChild(more);
  }
}

function selectedNodeInspectorItem(item, options) {
  const dataset = item && item.dataset ? item.dataset : {};
  const source = item && item.dataset ? dataset : (item || {});
  const groupKey = options.groupDatasetKey || '';
  return {
    label: promptSafeText(source.label || options.defaultLabel || 'Selected material'),
    group: promptSafeText(groupKey ? source[groupKey] || options.defaultGroup || '' : options.defaultGroup || ''),
    text: promptSafeText(source.context || source.text || source.value || ''),
    value: promptSafeText(source.value || '')
  };
}

function selectedNodeInspectorElement(item) {
  const node = document.createElement('div');
  node.className = 'genomi-selection-inspector-node';
  node.innerHTML = '<span></span><strong></strong><p></p>';
  node.querySelector('span').textContent = item.group || 'Material';
  node.querySelector('strong').textContent = item.label;
  node.querySelector('p').textContent = item.text;
  return node;
}
