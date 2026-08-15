import { promptSafeText, selectedEvidencePayload } from './portal_selected_evidence.js';
import { operationDisplayLabel } from './portal_operation_labels.js';
import { isSelectedContextEvidenceSource, selectedContextCopy, selectedContextKind } from './portal_selected_context_catalog.js';

export function contextDisplayModel(value) {
  const item = asContextItem(value);
  const nodes = contextNodes(item);
  const envelopeState = item && (item.finding_state || item.answer_readiness || '');
  const action = contextActionModel(item);
  return {
    label: contextLabel(item),
    source: contextSourceLabel(item),
    preview: contextSummary(item && (item.summary || item.prompt_text || item.text)),
    nodeCount: nodes.length,
    envelopeState: envelopeState ? contextSummary(envelopeState) : '',
    kind: action.kind,
    kindLabel: action.kindLabel,
    action
  };
}

export function contextLabel(value) {
  const item = asContextItem(value);
  const raw = contextSummary(item && (item.label || item.summary || item.text || item.prompt_text));
  if (!item) return raw;
  const sourceOperation = promptSafeText(item.source_operation || '').trim();
  if (!sourceOperation || !isEvidenceSourceContext(item)) return raw;
  if (raw && /^evidence source:/i.test(raw) && !raw.includes(sourceOperation)) return raw;
  return 'Evidence source: ' + operationDisplayLabel(sourceOperation, 'Genomi evidence source');
}

function contextSourceLabel(item) {
  const sourceOperation = item && item.source_operation;
  if (sourceOperation && isEvidenceSourceContext(item)) {
    const label = contextLabel(item).replace(/^Evidence source:\s*/i, '').trim();
    if (label && !label.includes(promptSafeText(sourceOperation).trim())) return contextSummary(label);
  }
  if (sourceOperation) return contextSummary(operationDisplayLabel(sourceOperation, 'Research step'));
  return 'GenomiLab selection';
}

export function contextActionModel(value) {
  const item = asContextItem(value);
  const kind = selectedContextKind(item);
  const operation = promptSafeText(item && item.source_operation || '').trim();
  const action = selectedContextCopy(kind);
  return {
    kind: kind || 'selected_context',
    kindLabel: action.kindLabel,
    askLabel: action.askLabel,
    draftLabel: action.draftLabel,
    askEnabled: action.askEnabled !== false,
    draftEnabled: action.draftEnabled !== false,
    className: 'context-kind-' + (kind || 'selected_context'),
    operation
  };
}

export function contextNodes(value) {
  const nodes = Array.isArray(value && value.selected_nodes) ? value.selected_nodes : [];
  return nodes
    .map((node) => {
      const item = {
        label: promptSafeText(node && node.label ? node.label : 'Selected item'),
        text: promptSafeText(node && node.text ? node.text : '')
      };
      const valueText = promptSafeText(node && node.value ? node.value : '');
      if (valueText) item.value = valueText;
      return item;
    })
    .filter((node) => node.text || node.value);
}

export function packetPromptText(value) {
  const item = asContextItem(value);
  return promptSafeText(item && (item.prompt_text || item.text || item.summary || item.label || ''));
}

export function contextSummary(text) {
  const first = promptSafeText(text || '').split('\n').find((line) => line.trim()) || 'Selected material';
  return first.length > 90 ? first.slice(0, 87) + '...' : first;
}

export function rebuildContextItemWithNodes(item, nodes) {
  const source = item || {};
  const rebuilt = selectedEvidencePayload({
    contextKind: source.context_kind,
    label: source.label,
    sourceOperation: source.source_operation,
    toolCallId: source.tool_call_id,
    toolResultId: source.tool_result_id,
    selectedNodes: nodes,
    promptIntro: packetPromptText(source).split('\n')[0]
  });
  return {
    ...rebuilt,
    id: source.id,
    finding_state: source.finding_state,
    answer_readiness: source.answer_readiness
  };
}

function isEvidenceSourceContext(item) {
  return isSelectedContextEvidenceSource(item);
}

function asContextItem(value) {
  if (!value) return null;
  if (typeof value === 'string') return { label: 'Selected material', text: value };
  if (typeof value !== 'object') return null;
  return value;
}
