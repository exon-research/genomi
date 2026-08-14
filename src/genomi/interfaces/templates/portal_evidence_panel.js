import {
  compactLine,
  formatContextValue,
  formatShort,
  humanizeState,
  isEmptyValue,
  singularTitle,
  titleCase
} from './portal_format.js';
import { extractPresentedPayload, normalizeEvidencePayload } from './portal_presented_payload.js';
import { operationDisplayLabel } from './portal_operation_labels.js';
import {
  applySelectionActionLabels,
  createSelectionActionButton,
  selectionActionLabels,
  selectionFallbackLabels,
  selectedSurfaceActionLabels
} from './portal_selection_actions.js';
import { selectedNodeInspectorModel, renderSelectedNodeInspector } from './portal_selection_inspector.js';
import { nodeContext, selectedDomNodes, selectedEvidencePayload as buildSelectedEvidencePayload } from './portal_selected_evidence.js';

export function renderEvidencePanel(record, options) {
  const payload = options && options.payload !== undefined ? options.payload : extractPresentedPayload(record);
  if (isPersistedRedacted(payload, options)) return null;
  const normalized = options && options.normalized !== undefined ? options.normalized : normalizeEvidencePayload(payload);
  if (!normalized) return null;
  const operation = (options && options.operation) || (record.call && record.call.name) || (record.result && record.result.name);
  const labeler = (options && options.toolNameLabel) || ((name) => operationDisplayLabel(name, 'Genomi evidence'));
  const toolName = labeler(operation);
  const envelope = normalized.envelope;
  const panel = document.createElement('div');
  panel.className = 'evidence-panel';
  panel.setAttribute('data-testid', 'evidence-panel');

  const headline = normalized.headline || 'Evidence result';
  const header = document.createElement('div');
  header.className = 'evidence-head';
  header.innerHTML = '<div><div class="evidence-kicker"></div><strong></strong></div><div class="evidence-badges"></div>';
  header.querySelector('.evidence-kicker').textContent = toolName;
  header.querySelector('strong').textContent = compactLine(headline, 220);
  const badges = header.querySelector('.evidence-badges');
  addBadge(badges, humanizeState(normalized.status || envelope.finding_state || 'returned'));
  addBadge(badges, humanizeState(envelope.answer_readiness));
  addBadge(badges, humanizeState(envelope.finding_state));
  const activeContext = envelope.active_genome_index_context || envelope.personal_context;
  if (activeContext && activeContext.used) addBadge(badges, 'Active genome used', 'green');
  panel.appendChild(header);

  const summary = document.createElement('div');
  summary.className = 'evidence-summary';
  addMetric(summary, 'Answer boundary', humanizeState(envelope.answer_readiness));
  addMetric(summary, 'Evidence support', humanizeState(envelope.finding_state));
  addMetric(summary, 'Retrieval status', humanizeState(normalized.status));
  addMetric(summary, 'Default assumptions', summarizeDefaults(normalized.defaults_applied));
  if (summary.children.length) panel.appendChild(summary);

  renderSection(panel, 'Coverage', envelope.coverage);
  renderSection(panel, 'Observations', envelope.observations);
  renderSection(panel, 'Suggested follow-up', envelope.next_actions, { selectable: false });
  renderMetadataSection(panel, 'Assumptions used', normalized.defaults_applied);
  const inspector = document.createElement('div');
  inspector.className = 'evidence-node-inspector genomi-selection-inspector';
  inspector.setAttribute('data-testid', 'evidence-node-inspector');
  inspector.hidden = true;
  panel.appendChild(inspector);

  const actions = document.createElement('div');
  actions.className = 'evidence-actions';
  actions.innerHTML = '<button class="tool-action" type="button" data-action="use"></button><button class="tool-action" type="button" data-action="copy"></button>';
  actions.querySelector('[data-action="use"]').addEventListener('click', (event) => {
    event.stopPropagation();
    const selected = selectedEvidencePayload(panel, normalized, record, toolName);
    if (typeof options.onUseContext === 'function') options.onUseContext(selected);
  });
  actions.querySelector('[data-action="copy"]').addEventListener('click', (event) => {
    event.stopPropagation();
    const selected = selectedEvidencePayload(panel, normalized, record, toolName);
    if (navigator.clipboard) navigator.clipboard.writeText(selected.prompt_text);
  });
  if (typeof options.onAskContext === 'function') {
    actions.appendChild(createSelectionActionButton({
      action: 'ask',
      testId: 'genomi-evidence-ask-selected',
      label: selectionFallbackLabels('evidence').ask,
      title: 'Use this evidence in a focused assistant question',
      onClick: () => options.onAskContext(selectedEvidencePayload(panel, normalized, record, toolName))
    }));
  }
  if (typeof options.onAskNewContext === 'function') {
    actions.appendChild(createSelectionActionButton({
      action: 'ask_new',
      testId: 'genomi-evidence-ask-new-selected',
      label: 'Ask in new conversation',
      title: 'Start a focused conversation from this evidence',
      onClick: () => options.onAskNewContext(selectedEvidencePayload(panel, normalized, record, toolName))
    }));
  }
  if (typeof options.onDraftContext === 'function') {
    actions.appendChild(createSelectionActionButton({
      action: 'draft',
      testId: 'genomi-evidence-draft-selected',
      label: selectionFallbackLabels('evidence').draft,
      title: 'Write a draft question from this evidence without sending it',
      onClick: () => options.onDraftContext(selectedEvidencePayload(panel, normalized, record, toolName))
    }));
  }
  panel.appendChild(actions);
  updateEvidenceActionLabels(panel);
  return panel;
}

export function evidenceContextForPayload(payload, toolName = 'Genomi evidence') {
  const packet = evidenceSelectedPacketForPayload(payload, toolName);
  return packet ? packet.prompt_text : '';
}

export function evidenceSelectedPacketForPayload(payload, toolName = 'Genomi evidence', selectedNodes = [], options = {}) {
  if (isPersistedRedacted(payload, null)) return null;
  const normalized = normalizeEvidencePayload(payload);
  if (!normalized) return null;
  return selectedEvidencePayloadForNormalized(normalized, {
    toolName,
    sourceOperation: options.sourceOperation || toolName,
    toolCallId: options.toolCallId,
    toolResultId: options.toolResultId,
    selectedNodes,
    promptIntro: options.promptIntro
  });
}

function selectedEvidencePayload(panel, normalized, record, toolName) {
  const selectedNodes = selectedDomNodes(panel, '.evidence-node.selected');
  return selectedEvidencePayloadForNormalized(normalized, {
    toolName,
    sourceOperation: (record.call && record.call.name) || (record.result && record.result.name) || toolName,
    toolCallId: record.call && record.call.id,
    toolResultId: record.result && record.result.id,
    selectedNodes
  });
}

function selectedEvidencePayloadForNormalized(normalized, options) {
  const fallbackLines = compactEvidenceContext(normalized);
  const toolLabel = operationDisplayLabel(options.toolName, options.toolName || 'Genomi evidence');
  return buildSelectedEvidencePayload({
    contextKind: 'evidence_panel',
    evidenceEnvelope: normalized.envelope,
    label: normalized.headline || toolLabel,
    summary: options.selectedNodes && options.selectedNodes.length ? '' : compactLine(fallbackLines.join(' · '), 220),
    sourceOperation: options.sourceOperation,
    toolCallId: options.toolCallId,
    toolResultId: options.toolResultId,
    selectedNodes: options.selectedNodes,
    fallbackNodes: fallbackLines.map((line) => ({ label: 'Evidence', text: line })),
    promptIntro: options.promptIntro || 'Selected evidence from ' + toolLabel + ':'
  });
}

function compactEvidenceContext(normalized) {
  const envelope = normalized.envelope;
  const lines = [];
  if (normalized.headline) lines.push('Headline: ' + normalized.headline);
  if (envelope.answer_readiness) lines.push('Answer readiness: ' + envelope.answer_readiness);
  if (envelope.finding_state) lines.push('Finding state: ' + envelope.finding_state);
  evidenceEntries(envelope.coverage || {}).slice(0, 4).forEach((entry) => lines.push('Coverage ' + entry.label + ': ' + formatContextValue(entry.value)));
  evidenceEntries(envelope.observations || {}).slice(0, 4).forEach((entry) => lines.push('Observation ' + entry.label + ': ' + formatContextValue(entry.value)));
  return lines.length ? lines : ['Envelope: ' + formatContextValue(envelope)];
}

function addBadge(container, text, tone) {
  if (!text) return;
  const badge = document.createElement('span');
  badge.className = 'evidence-badge' + (tone ? ' ' + tone : '');
  badge.textContent = String(text);
  container.appendChild(badge);
}

function addMetric(container, label, value) {
  if (value === null || value === undefined || value === '' || value === false) return;
  const item = document.createElement('div');
  item.className = 'evidence-metric';
  item.innerHTML = '<span></span><strong></strong>';
  item.querySelector('span').textContent = label;
  item.querySelector('strong').textContent = compactLine(formatShort(value), 96);
  container.appendChild(item);
}

function renderSection(panel, title, value, options = {}) {
  if (isEmptyValue(value)) return;
  const section = document.createElement('div');
  section.className = 'evidence-section';
  const heading = document.createElement('div');
  heading.className = 'evidence-section-title';
  heading.textContent = title;
  section.appendChild(heading);
  const nodes = document.createElement('div');
  nodes.className = 'evidence-nodes';
  const selectable = options.selectable !== false;
  evidenceEntries(value, title).slice(0, 12).forEach((entry) => {
    nodes.appendChild(selectable ? evidenceNode(entry.label, entry.value) : evidenceStaticNode(entry.label, entry.value));
  });
  section.appendChild(nodes);
  panel.appendChild(section);
}

function evidenceNode(label, value) {
  const node = document.createElement('button');
  node.type = 'button';
  node.className = 'evidence-node';
  const context = nodeContext(label, value);
  node.dataset.context = context;
  node.dataset.label = label;
  node.dataset.value = formatContextValue(value);
  node.innerHTML = '<span></span><strong></strong>';
  node.querySelector('span').textContent = compactLine(label, 52);
  node.querySelector('strong').textContent = compactLine(formatShort(value), 140);
  node.addEventListener('click', (event) => {
    event.stopPropagation();
    node.classList.toggle('selected');
    const panel = node.closest('.evidence-panel');
    renderEvidenceSelectionInspector(panel);
    updateEvidenceActionLabels(panel);
  });
  return node;
}

function evidenceStaticNode(label, value) {
  const node = document.createElement('div');
  node.className = 'evidence-node evidence-node-static';
  node.innerHTML = '<span></span><strong></strong>';
  node.querySelector('span').textContent = compactLine(label, 52);
  node.querySelector('strong').textContent = compactLine(formatShort(value), 140);
  return node;
}

function renderMetadataSection(panel, title, value) {
  if (isEmptyValue(value)) return;
  const section = document.createElement('div');
  section.className = 'evidence-section evidence-section-metadata';
  const heading = document.createElement('div');
  heading.className = 'evidence-section-title';
  heading.textContent = title;
  section.appendChild(heading);
  const list = document.createElement('div');
  list.className = 'evidence-metadata-list';
  evidenceEntries(value, title).slice(0, 12).forEach((entry) => {
    const item = document.createElement('div');
    item.className = 'evidence-metadata-item';
    item.innerHTML = '<span></span><strong></strong>';
    item.querySelector('span').textContent = compactLine(entry.label, 52);
    item.querySelector('strong').textContent = compactLine(formatShort(entry.value), 140);
    list.appendChild(item);
  });
  section.appendChild(list);
  panel.appendChild(section);
}

function updateEvidenceActionLabels(panel) {
  if (!panel) return;
  const selectedCount = panel.querySelectorAll('.evidence-node.selected').length;
  applySelectionActionLabels(panel, selectionActionLabels(
    selectedCount,
    'evidence',
    selectedSurfaceActionLabels('selected evidence items')
  ));
}

export function evidencePanelSelectionInspectorModel(selectedNodes) {
  return selectedNodeInspectorModel(selectedNodes, {
    defaultLabel: 'Selected evidence',
    defaultGroup: 'Evidence',
    singularTitle: 'selected evidence item',
    pluralTitle: 'selected evidence items'
  });
}

function renderEvidenceSelectionInspector(panel) {
  if (!panel) return;
  const inspector = panel.querySelector('.evidence-node-inspector');
  if (!inspector) return;
  const model = evidencePanelSelectionInspectorModel(panel.querySelectorAll('.evidence-node.selected'));
  renderSelectedNodeInspector(inspector, model, { heading: 'Selected evidence' });
}

function evidenceEntries(value, title) {
  if (Array.isArray(value)) {
    return value.map((item, index) => ({ label: itemLabel(item, index, title), value: item }));
  }
  if (value && typeof value === 'object') {
    return Object.entries(value)
      .filter(([, child]) => !isEmptyValue(child))
      .map(([key, child]) => ({ label: titleCase(key), value: child }));
  }
  return [{ label: 'Value', value }];
}

function itemLabel(value, index, title) {
  if (value && typeof value === 'object') {
    for (const key of ['action', 'type', 'source', 'source_id', 'gene', 'drug', 'rsid', 'status', 'title', 'label']) {
      if (typeof value[key] === 'string' && value[key]) return titleCase(value[key]);
    }
  }
  return evidenceArrayItemLabel(title) + ' ' + (index + 1);
}

function evidenceArrayItemLabel(title) {
  const normalized = String(title || '').trim().toLowerCase();
  if (normalized === 'how to use this') return 'Use limit';
  if (normalized === 'suggested follow-up') return 'Follow-up';
  if (normalized === 'assumptions used') return 'Assumption';
  return singularTitle(title || 'Item');
}

function summarizeDefaults(value) {
  if (!value || typeof value !== 'object') return null;
  const count = Array.isArray(value) ? value.length : Object.keys(value).length;
  return count ? count + ' applied' : null;
}

function isPersistedRedacted(payload, options) {
  return Boolean(
    (options && options.presentationState === 'persisted_redacted') ||
    (payload && typeof payload === 'object' && payload.presentation_state === 'persisted_redacted')
  );
}
