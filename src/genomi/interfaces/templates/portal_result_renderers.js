import { compactLine, formatContextValue, formatShort, humanizeState, isEmptyValue, titleCase } from './portal_format.js';
import { genomeContextPayloadForSelection, genomeContextResultViewModel, renderGenomeContext } from './portal_genome_context.js';
import { extractPresentedPayload, normalizeEvidencePayload } from './portal_presented_payload.js';
import { serverResultPresentationModel, sourceOperation } from './portal_result_presentation_model.js';
import {
  clearResultSelection,
  normalizeSearchText,
  notifyResultSelectionChanged,
  renderResultSelectionInspector,
  resultNodeSearchText,
  resultSelectionInspectorModel,
  selectShownResultNodes,
  selectedResultNodePayloads,
  selectedResultNodes,
  syncResultToolbarSelection
} from './portal_result_selection.js';
import {
  applySelectionActionLabels,
  createSelectionActionButton,
  selectionActionLabels,
  selectionFallbackLabels,
  selectedSurfaceActionLabels
} from './portal_selection_actions.js';
import { nodeContext, promptSafeText, selectedEvidencePayload as buildSelectedEvidencePayload } from './portal_selected_evidence.js';

const resultRenderers = new Map();

export { resultSelectionInspectorModel };

export function registerGenomiResultRenderer(operation, buildModel) {
  const key = String(operation || '').trim();
  if (!key || typeof buildModel !== 'function') return () => {};
  resultRenderers.set(key, buildModel);
  return () => {
    if (resultRenderers.get(key) === buildModel) resultRenderers.delete(key);
  };
}

export function getGenomiResultRenderer(operation) {
  return resultRenderers.get(String(operation || '').trim());
}

export function registeredGenomiResultRendererOperations() {
  return [...resultRenderers.keys()];
}

export function genomiResultViewModel(record, options = {}) {
  const payload = options.payload !== undefined ? options.payload : extractPresentedPayload(record);
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
  const operation = options.operation || sourceOperation(record);
  const serverModel = serverResultPresentationModel(record && record.result && record.result.portal_presentation, operation);
  if (serverModel) return serverModel;
  if (operation === 'genomi.describe_context') return genomeContextResultViewModel(payload, operation);
  const renderer = getGenomiResultRenderer(operation);
  if (renderer) {
    const normalized = options.normalized !== undefined ? options.normalized : normalizeEvidencePayload(payload);
    if (!normalized) return null;
    const model = renderer(payload, operation, normalized, {
      displayOnly: Boolean(options.displayOnly),
      presentationState: options.presentationState || ''
    });
    return enrichResultModelWithEvidenceState(model, normalized);
  }
  return null;
}

export function renderGenomiResultPanel(record, options = {}) {
  const operation = options.operation || sourceOperation(record);
  const payload = options.payload !== undefined ? options.payload : extractPresentedPayload(record);
  if (operation === 'genomi.describe_context' && payload && typeof payload === 'object' && !Array.isArray(payload)) {
    return renderGenomeContextResultPanel(payload, record, options);
  }
  const model = options.resultModel || genomiResultViewModel(record, options);
  if (!model) return null;
  const panel = document.createElement('div');
  panel.className = 'genomi-result-view';
  panel.setAttribute('data-testid', 'genomi-result-view');
  panel.innerHTML = '<div class="genomi-result-head"><div><div class="genomi-result-kicker"></div><strong></strong><p></p></div><div class="genomi-result-metrics"></div></div><div class="genomi-result-notice" hidden><strong></strong><span></span></div><div class="genomi-result-lanes"></div><div class="genomi-result-inspector genomi-selection-inspector" data-testid="genomi-result-selection-inspector" hidden></div><div class="evidence-actions"><button class="tool-action" type="button" data-action="use"></button><button class="tool-action" type="button" data-action="copy"></button></div>';
  panel.querySelector('.genomi-result-kicker').textContent = model.kicker;
  panel.querySelector('.genomi-result-head strong').textContent = model.title;
  panel.querySelector('.genomi-result-head p').textContent = model.summary;
  renderResultNotice(panel, model.notice);
  const metrics = panel.querySelector('.genomi-result-metrics');
  model.metrics.filter(Boolean).forEach((metric) => metrics.appendChild(metricNode(metric)));
  const lanes = panel.querySelector('.genomi-result-lanes');
  const toolbar = resultSearchToolbar(model, panel);
  if (toolbar) {
    if (typeof panel.insertBefore === 'function') panel.insertBefore(toolbar, lanes);
    else panel.appendChild(toolbar);
  }
  model.lanes.forEach((lane) => lanes.appendChild(laneNode(lane)));
  renderResultSelectionInspector(panel);
  syncResultToolbarSelection(panel);
  if (options.actions === false) {
    panel.querySelector('.evidence-actions').remove();
  } else {
    panel.querySelector('[data-action="use"]').addEventListener('click', (event) => {
      event.stopPropagation();
      if (typeof options.onUseContext === 'function') options.onUseContext(selectedEvidencePayload(panel, model, record));
    });
    panel.querySelector('[data-action="copy"]').addEventListener('click', (event) => {
      event.stopPropagation();
      const text = selectedEvidencePayload(panel, model, record).prompt_text;
      if (navigator.clipboard) navigator.clipboard.writeText(text);
    });
    if (typeof options.onAskContext === 'function') {
      panel.querySelector('.evidence-actions').appendChild(createSelectionActionButton({
        action: 'ask',
        testId: 'genomi-result-ask-selected',
        label: selectionFallbackLabels('result').ask,
        title: 'Use this result in a focused assistant question',
        onClick: () => options.onAskContext(selectedEvidencePayload(panel, model, record))
      }));
    }
    if (typeof options.onAskNewContext === 'function') {
      panel.querySelector('.evidence-actions').appendChild(createSelectionActionButton({
        action: 'ask_new',
        testId: 'genomi-result-ask-new-selected',
        label: 'Ask in new conversation',
        title: 'Start a focused conversation from this result',
        onClick: () => options.onAskNewContext(selectedEvidencePayload(panel, model, record))
      }));
    }
    if (typeof options.onDraftContext === 'function') {
      panel.querySelector('.evidence-actions').appendChild(createSelectionActionButton({
        action: 'draft',
        testId: 'genomi-result-draft-selected',
        label: selectionFallbackLabels('result').draft,
        title: 'Write a draft question from this result without sending it',
        onClick: () => options.onDraftContext(selectedEvidencePayload(panel, model, record))
      }));
    }
    updateResultActionLabels(panel);
  }
  return panel;
}

export function genomiResultContextPayload(record, selectedRoot, options = {}) {
  const operation = options.operation || sourceOperation(record);
  const payload = options.payload !== undefined ? options.payload : extractPresentedPayload(record);
  if (operation === 'genomi.describe_context' && payload && typeof payload === 'object' && !Array.isArray(payload)) {
    return genomeContextPayloadForResult(payload, record, selectedRoot);
  }
  const model = options.resultModel || genomiResultViewModel(record, options);
  if (!model) return null;
  return selectedEvidencePayload(selectedRoot, model, record);
}

export function resultSearchModel(model, query = '') {
  const cleanQuery = normalizeSearchText(query);
  const lanes = (Array.isArray(model && model.lanes) ? model.lanes : []).map((lane) => {
    const nodes = Array.isArray(lane && lane.nodes) ? lane.nodes : [];
    const matching = cleanQuery
      ? nodes.filter((item) => resultNodeSearchText(item, lane && lane.title).includes(cleanQuery)).length
      : nodes.length;
    return {
      title: lane && lane.title ? String(lane.title) : 'Result lane',
      total: nodes.length,
      matching
    };
  });
  const totalNodes = lanes.reduce((sum, lane) => sum + lane.total, 0);
  const matchingNodes = lanes.reduce((sum, lane) => sum + lane.matching, 0);
  return {
    query: cleanQuery,
    totalNodes,
    matchingNodes,
    lanes,
    visible: totalNodes > 2,
    empty: Boolean(cleanQuery && !matchingNodes),
    summary: cleanQuery ? matchingNodes + ' of ' + totalNodes + ' shown' : totalNodes + ' items'
  };
}

function metric(label, value) {
  if (isEmptyValue(value)) return null;
  return { label, value };
}

function lane(title, nodes, options = {}) {
  return { title, nodes: nodes.filter(Boolean), selectable: options.selectable !== false };
}

function node(label, summary, value, options = {}) {
  const cleanLabel = String(label || 'Evidence item').trim();
  return {
    label: cleanLabel || 'Evidence item',
    summary: compactLine(String(summary || formatShort(value)), 160),
    context: nodeContext(cleanLabel, value),
    value,
    selectable: options.selectable !== false
  };
}

function enrichResultModelWithEvidenceState(model, normalized) {
  if (!model || !normalized || !normalized.envelope) return model;
  const envelope = object(normalized.envelope);
  const metrics = appendMissingMetrics(array(model.metrics), [
    metric('Answer boundary', humanizeState(envelope.answer_readiness)),
    metric('Evidence support', humanizeState(envelope.finding_state)),
    metric('Retrieval status', humanizeState(normalized.status)),
    metric('Default assumptions', defaultsSummary(normalized.defaults_applied))
  ]);
  const evidenceNodes = evidenceStateNodes(envelope, normalized);
  const lanes = [...array(model.lanes)];
  if (evidenceNodes.length && !lanes.some((item) => item.title === 'Coverage and limits')) {
    lanes.push(lane('Coverage and limits', evidenceNodes, { selectable: false }));
  }
  return {
    ...model,
    evidenceEnvelope: model.evidenceEnvelope || envelope,
    metrics,
    lanes
  };
}

function appendMissingMetrics(baseMetrics, additions) {
  const labels = new Set(baseMetrics.filter(Boolean).map((item) => String(item.label || '').toLowerCase()));
  const next = [...baseMetrics.filter(Boolean)];
  additions.filter(Boolean).forEach((item) => {
    const label = String(item.label || '').toLowerCase();
    if (!label || labels.has(label)) return;
    labels.add(label);
    next.push(item);
  });
  return next;
}

function evidenceStateNodes(envelope, normalized) {
  const nodes = [];
  addEvidenceStateNodes(nodes, 'Coverage', envelope.coverage);
  addEvidenceStateNodes(nodes, 'Observations', envelope.observations);
  addEvidenceStateNodes(nodes, 'Suggested follow-up', envelope.next_actions);
  return nodes.slice(0, 12);
}

function addEvidenceStateNodes(nodes, section, value) {
  if (isEmptyValue(value)) return;
  evidenceEntries(value, section).forEach((entry) => {
    nodes.push(node(section + ': ' + entry.label, formatContextValue(entry.value), {
      section,
      label: entry.label,
      value: entry.value
    }, { selectable: false }));
  });
}

function evidenceEntries(value, section) {
  if (Array.isArray(value)) {
    return value
      .filter((item) => !isEmptyValue(item))
      .map((item, index) => ({ label: evidenceEntryLabel(item, index, section), value: item }));
  }
  if (value && typeof value === 'object') {
    return Object.entries(value)
      .filter(([, child]) => !isEmptyValue(child))
      .map(([key, child]) => ({ label: titleCase(key), value: child }));
  }
  return [{ label: 'Value', value }];
}

function evidenceEntryLabel(value, index, section) {
  if (value && typeof value === 'object') {
    for (const key of ['action', 'type', 'source', 'source_id', 'gene', 'drug', 'rsid', 'status', 'title', 'label']) {
      if (typeof value[key] === 'string' && value[key]) return titleCase(value[key]);
    }
  }
  return singularEvidenceTitle(section || 'Item') + ' ' + (index + 1);
}

function singularEvidenceTitle(title) {
  const clean = String(title || 'Item').trim();
  const mapped = evidenceArrayItemLabel(clean);
  if (mapped) return mapped;
  if (/\s/.test(clean)) return clean;
  return clean.endsWith('s') && !clean.endsWith('ss') ? clean.slice(0, -1) : clean;
}

function evidenceArrayItemLabel(title) {
  const normalized = String(title || '').trim().toLowerCase();
  if (normalized === 'suggested follow-up') return 'Follow-up';
  if (normalized === 'default assumptions') return 'Default assumption';
  return '';
}

function defaultsSummary(value) {
  if (!value || typeof value !== 'object') return null;
  const count = Array.isArray(value) ? value.length : Object.keys(value).length;
  return count ? count + ' applied' : null;
}

function metricNode(metric) {
  const el = document.createElement('div');
  el.className = 'genomi-result-metric';
  el.innerHTML = '<span></span><strong></strong>';
  el.querySelector('span').textContent = metric.label;
  el.querySelector('strong').textContent = compactLine(formatShort(metric.value), 68);
  return el;
}

function renderResultNotice(panel, notice) {
  const el = panel.querySelector('.genomi-result-notice');
  if (!el || !notice) return;
  el.hidden = false;
  el.querySelector('strong').textContent = notice.title || 'Presentation note';
  el.querySelector('span').textContent = notice.text || '';
}

function resultSearchToolbar(model, panel) {
  const search = resultSearchModel(model);
  if (!search.visible) return null;
  const toolbar = document.createElement('div');
  toolbar.className = 'genomi-result-toolbar';
  toolbar.setAttribute('data-testid', 'genomi-result-toolbar');
  toolbar.innerHTML = [
    '<label><span>Search evidence</span><input type="search" placeholder="Filter by source, gene, variant, finding" data-testid="genomi-result-search"></label>',
    '<strong></strong>',
    '<div class="genomi-result-toolbar-actions">',
    '<button type="button" class="tool-action" data-toolbar-action="clear-search">Clear search</button>',
    '<button type="button" class="tool-action" data-toolbar-action="select-shown">Select shown</button>',
    '<button type="button" class="tool-action" data-toolbar-action="clear-selected">Clear selected</button>',
    '</div>'
  ].join('');
  const input = toolbar.querySelector('input');
  const clear = toolbar.querySelector('[data-toolbar-action="clear-search"]');
  const selectShown = toolbar.querySelector('[data-toolbar-action="select-shown"]');
  const clearSelected = toolbar.querySelector('[data-toolbar-action="clear-selected"]');
  const update = () => applyResultSearch(panel, input.value);
  input.addEventListener('input', update);
  clear.addEventListener('click', () => {
    input.value = '';
    update();
    input.focus({ preventScroll: true });
  });
  selectShown.addEventListener('click', () => {
    selectShownResultNodes(panel);
    updateResultActionLabels(panel);
  });
  clearSelected.addEventListener('click', () => {
    clearResultSelection(panel);
    updateResultActionLabels(panel);
  });
  updateResultToolbar(toolbar, search);
  return toolbar;
}

function applyResultSearch(panel, query) {
  if (!panel) return;
  const toolbar = panel.querySelector('.genomi-result-toolbar');
  const cleanQuery = normalizeSearchText(query);
  let shown = 0;
  let total = 0;
  panel.querySelectorAll('.genomi-result-lane').forEach((lane) => {
    let laneShown = 0;
    lane.querySelectorAll('.result-node').forEach((node) => {
      total += 1;
      const matches = !cleanQuery || normalizeSearchText(node.dataset.search || '').includes(cleanQuery);
      node.hidden = !matches;
      if (matches) {
        shown += 1;
        laneShown += 1;
      }
    });
    lane.hidden = cleanQuery && laneShown === 0;
  });
  updateResultToolbar(toolbar, {
    query: cleanQuery,
    totalNodes: total,
    matchingNodes: shown,
    empty: Boolean(cleanQuery && !shown),
    summary: cleanQuery ? shown + ' of ' + total + ' shown' : total + ' items'
  });
  syncResultToolbarSelection(panel);
}

function updateResultToolbar(toolbar, search) {
  if (!toolbar) return;
  const summary = toolbar.querySelector('strong');
  if (summary) summary.textContent = search.summary;
  toolbar.classList.toggle('empty', Boolean(search.empty));
}

function laneNode(lane) {
  const section = document.createElement('div');
  section.className = 'genomi-result-lane';
  section.innerHTML = '<div class="genomi-result-lane-title"></div><div class="genomi-result-nodes"></div>';
  section.querySelector('.genomi-result-lane-title').textContent = lane.title;
  const nodes = section.querySelector('.genomi-result-nodes');
  lane.nodes.forEach((item) => nodes.appendChild(resultNode(item, lane.title, lane.selectable !== false)));
  return section;
}

function resultNode(item, laneTitle, laneSelectable) {
  const selectable = laneSelectable && item.selectable !== false;
  const node = document.createElement(selectable ? 'button' : 'div');
  if (selectable) node.type = 'button';
  node.className = selectable ? 'result-node' : 'result-node result-node-static';
  node.dataset.selectable = selectable ? 'true' : 'false';
  node.dataset.label = promptSafeText(item.label);
  node.dataset.lane = promptSafeText(laneTitle || 'Result lane');
  node.dataset.value = promptSafeText(formatContextValue(item.value));
  node.dataset.search = resultNodeSearchText(item, laneTitle);
  if (selectable) node.dataset.context = promptSafeText(item.context);
  node.innerHTML = '<span></span><strong></strong>';
  node.querySelector('span').textContent = compactLine(item.label, 54);
  node.querySelector('strong').textContent = compactLine(item.summary, 140);
  if (selectable) {
    node.addEventListener('click', (event) => {
      event.stopPropagation();
      node.classList.toggle('selected');
      const panel = node.closest('.genomi-result-view');
      renderResultSelectionInspector(panel);
      updateResultActionLabels(panel);
      syncResultToolbarSelection(panel);
      notifyResultSelectionChanged(panel);
    });
  }
  return node;
}

function updateResultActionLabels(panel) {
  if (!panel) return;
  const selectedCount = selectedResultNodes(panel).length;
  applySelectionActionLabels(panel, selectionActionLabels(
    selectedCount,
    'result',
    selectedSurfaceActionLabels('selected result items')
  ));
}

function selectedEvidencePayload(panel, model, record) {
  const selectedNodes = selectedResultNodePayloads(panel);
  const fallbackNodes = model.lanes
    .filter((lane) => lane.selectable !== false)
    .flatMap((lane) => lane.nodes
      .filter((item) => item.selectable !== false)
      .slice(0, 3)
      .map((item) => ({ label: item.label, text: item.context, value: formatContextValue(item.value) })))
    .slice(0, 8);
  return buildSelectedEvidencePayload({
    contextKind: 'result_nodes',
    evidenceEnvelope: model.evidenceEnvelope,
    label: model.title,
    summary: model.summary,
    sourceOperation: model.operation,
    toolCallId: record.call && record.call.id,
    toolResultId: record.result && record.result.id,
    selectedNodes,
    fallbackNodes,
    promptIntro: 'Selected ' + model.kicker + ': ' + model.title
  });
}

function renderGenomeContextResultPanel(payload, record, options) {
  const panel = document.createElement('div');
  panel.className = 'genomi-context-result-view';
  panel.setAttribute('data-testid', 'genome-context-result-view');
  renderGenomeContext(panel, payload, {
    onUseContext: options.onUseContext,
    actions: options.actions !== false,
    sourceOperation: sourceOperation(record) || 'genomi.describe_context',
    toolCallId: record.call && record.call.id,
    toolResultId: record.result && record.result.id
  });
  return panel;
}

function genomeContextPayloadForResult(payload, record, selectedRoot) {
  return genomeContextPayloadForSelection(payload, selectedRoot, {
    sourceOperation: sourceOperation(record) || 'genomi.describe_context',
    toolCallId: record.call && record.call.id,
    toolResultId: record.result && record.result.id
  });
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function array(value) {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === 'object') : [];
}
