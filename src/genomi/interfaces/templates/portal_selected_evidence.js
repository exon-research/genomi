import { compactLine, formatContextValue } from './portal_format.js';

const LOCAL_PATH_PATTERN = /(?:~|\/Users|\/home|\/tmp|\/private\/tmp|\/var\/folders|\/opt\/homebrew|\/usr\/local|\/Applications|\/Volumes)(?:\/[^\s"'<>),;:]+)*/g;
const SENSITIVE_PATH_FIELD_PATTERN = /(["']?)(context_file|registry_file|agi_path)\1\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^,\s}\]]+)/gi;

export function selectedDomNodes(panel, selector) {
  return [...panel.querySelectorAll(selector)]
    .map((item) => ({
      label: promptSafeText(item.dataset.label || 'Selected item'),
      text: promptSafeText(item.dataset.context || item.dataset.text || item.dataset.value || ''),
      value: promptSafeText(item.dataset.value || '')
    }))
    .filter((item) => item.text);
}

export function promptSafeText(value) {
  return String(value || '')
    .replace(SENSITIVE_PATH_FIELD_PATTERN, (_match, _quote, key) => key.replace(/_/g, ' ') + ': [redacted local path]')
    .replace(LOCAL_PATH_PATTERN, '[redacted local path]');
}

export function selectedEvidencePayload({
  contextKind,
  evidenceEnvelope,
  label,
  summary,
  sourceOperation,
  toolCallId,
  toolResultId,
  selectedNodes,
  fallbackNodes,
  promptIntro
}) {
  const selected = Array.isArray(selectedNodes) ? selectedNodes : [];
  const fallback = Array.isArray(fallbackNodes) ? fallbackNodes : [];
  const nodes = (selected.length ? selected : fallback.slice(0, 8)).map((item) => ({
    label: promptSafeText(item.label || 'Selected item'),
    text: promptSafeText(item.text || item.value || ''),
    value: promptSafeText(item.value || '')
  })).filter((item) => item.text);
  const title = promptSafeText(label || sourceOperation || 'Included evidence');
  const safeSummary = promptSafeText(summary || compactLine(nodes.map((item) => item.text).join(' · '), 220));
  const safeSourceOperation = promptSafeText(sourceOperation || '');
  const safeToolCallId = promptSafeText(toolCallId || '');
  const safeToolResultId = promptSafeText(toolResultId || '');
  const safeIntro = promptSafeText(promptIntro || 'Included evidence: ' + title);
  const safeContextKind = contextKindValue(contextKind);
  const envelope = evidenceEnvelope && typeof evidenceEnvelope === 'object' && !Array.isArray(evidenceEnvelope) ? evidenceEnvelope : {};
  const safeFindingState = promptSafeText(envelope.finding_state || '').trim();
  const safeAnswerReadiness = promptSafeText(envelope.answer_readiness || '').trim();
  const prompt = [
    safeIntro,
    safeSummary,
    ...nodes.map((item) => '- ' + item.text)
  ].filter(Boolean).join('\n');
  return {
    label: title,
    summary: safeSummary,
    context_kind: safeContextKind || undefined,
    finding_state: safeFindingState || undefined,
    answer_readiness: safeAnswerReadiness || undefined,
    source_operation: safeSourceOperation || undefined,
    tool_call_id: safeToolCallId || undefined,
    tool_result_id: safeToolResultId || undefined,
    selected_nodes: nodes,
    prompt_text: prompt
  };
}

export function contextKindValue(value) {
  const clean = promptSafeText(value || '').trim().toLowerCase().replace(/[^a-z0-9_]+/g, '_');
  return clean || '';
}

export function nodeContext(label, value) {
  return promptSafeText(String(label || 'Evidence item').trim() + ': ' + formatContextValue(value));
}
