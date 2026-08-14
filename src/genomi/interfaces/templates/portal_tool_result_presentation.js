import { evidenceSelectedPacketForPayload, renderEvidencePanel } from './portal_evidence_panel.js';
import { compactLine, formatPayload, outputLineCount } from './portal_format.js';
import { extractPresentedPayload, normalizeEvidencePayload } from './portal_presented_payload.js';
import { sourceOperation } from './portal_result_presentation_model.js';
import {
  genomiResultContextPayload,
  genomiResultViewModel,
  renderGenomiResultPanel
} from './portal_result_renderers.js';
import { renderResultTraceDetails } from './portal_result_trace.js';
import { operationDisplayLabel } from './portal_operation_labels.js';
import {
  selectedDomNodes,
  selectedEvidencePayload as buildSelectedEvidencePayload
} from './portal_selected_evidence.js';

export const LIVE_PRESENTATION_STATE = 'live';
export const DISPLAY_ONLY_PRESENTATION_STATE = 'display_only';
export const PERSISTED_REDACTED_PRESENTATION_STATE = 'persisted_redacted';

export { sourceOperation };

export function toolNameLabel(name) {
  return operationDisplayLabel(name, 'Research step');
}

export function toolResultSummary(result) {
  if (!result) return 'running';
  if (result.isError) return 'error';
  const presentation = result.portal_presentation && result.portal_presentation.schema === 'genomi_portal_result_presentation'
    ? result.portal_presentation
    : null;
  if (presentation && typeof presentation.summary === 'string' && presentation.summary.trim()) {
    return compactLine(presentation.summary, 160);
  }
  const ledger = result.ledger && typeof result.ledger === 'object' && !Array.isArray(result.ledger) ? result.ledger : null;
  if (ledger && typeof ledger.summary === 'string' && ledger.summary.trim()) return compactLine(ledger.summary, 160);
  if (ledger && typeof ledger.headline === 'string' && ledger.headline.trim()) return compactLine(ledger.headline, 160);
  const payload = extractPresentedPayload({ result });
  if (payload && typeof payload === 'object') {
    const envelope = payload.evidence_envelope && typeof payload.evidence_envelope === 'object' ? payload.evidence_envelope : null;
    if (typeof payload.headline === 'string') return compactLine(payload.headline, 160);
    if (envelope && typeof envelope.headline === 'string') return compactLine(envelope.headline, 160);
    if (typeof payload.status === 'string') return compactLine(payload.status, 80);
    const stdoutLines = outputLineCount(payload.stdout);
    if (stdoutLines) {
      const exit = typeof payload.exit_code === 'number' ? ' · exit ' + payload.exit_code : '';
      return stdoutLines + ' lines of output' + exit;
    }
  }
  if (typeof result.content === 'string' && result.content.trim()) {
    return compactLine(result.content.split('\n').find(Boolean) || result.content, 160);
  }
  return 'completed';
}

export function toolResultPresentation(record, options = {}) {
  const operation = options.operation || sourceOperation(record) || 'tool';
  const payload = options.payload !== undefined ? options.payload : extractPresentedPayload(record);
  const normalized = normalizeEvidencePayload(payload);
  const displayOnly = Boolean(options.displayOnly || recordDisplayOnly(record));
  const hasCanonicalEnvelope = Boolean(normalized);
  const presentationState = resultPresentationState(record, payload, displayOnly, options);
  const persistedRedacted = presentationState === PERSISTED_REDACTED_PRESENTATION_STATE;
  const resultModel = (!displayOnly || persistedRedacted) ? genomiResultViewModel(record, {
    operation,
    payload,
    normalized,
    displayOnly,
    presentationState
  }) : null;
  const canRenderResult = Boolean(resultModel);
  const canRenderEvidence = Boolean(hasCanonicalEnvelope && !displayOnly && !persistedRedacted);
  const kind = presentationKind({
    operation,
    displayOnly,
    persistedRedacted,
    hasCanonicalEnvelope,
    canRenderResult
  });
  const primaryPanelKind = canRenderResult ? 'result_view' : (canRenderEvidence ? 'evidence' : kind);
  const canAttach = Boolean(!displayOnly && !persistedRedacted && (
    kind === 'evidence' || kind === 'session_context' || kind === 'result_view'
  ));
  return {
    operation,
    title: options.title || toolNameLabel(operation),
    summary: options.summary || '',
    payload,
    normalized,
    resultModel,
    displayOnly,
    presentationState,
    kind,
    hasCanonicalEnvelope,
    canRenderResult,
    canRenderEvidence,
    primaryPanelKind,
    canAttach,
    includeInSummary: kind === 'evidence' && canAttach
  };
}

export function toolResultContextPayload(record, selectedRoot, options = {}) {
  const presentation = toolResultPresentation(record, options);
  if (!presentation.canAttach) return null;
  const evidenceNodes = selectedRoot ? selectedDomNodes(selectedRoot, '.evidence-node.selected') : [];
  const resultNodes = selectedRoot ? selectedDomNodes(selectedRoot, '.result-node.selected') : [];
  if (evidenceNodes.length) {
    const evidencePayload = selectedEvidenceNodesPayload(presentation, record, [...evidenceNodes, ...resultNodes], options);
    if (evidencePayload) return evidencePayload;
  }
  if (resultNodes.length) {
    return selectedResultNodesPayload(presentation, record, resultNodes, options);
  }
  if (presentation.canRenderResult) {
    const resultPacket = genomiResultContextPayload(record, selectedRoot, presentation);
    if (resultPacket) return resultPacket;
  }
  if (presentation.kind === 'evidence') {
    return evidenceSelectedPacketForPayload(presentation.payload, presentation.operation, [], {
      sourceOperation: presentation.operation,
      toolCallId: record.call && record.call.id,
      toolResultId: record.result && record.result.id
    });
  }
  return genomiResultContextPayload(record, selectedRoot, presentation);
}

export function toolResultFollowUpRequest(record, options = {}) {
  const presentation = toolResultPresentation(record, options);
  const context = toolResultFollowUpContext(record, presentation);
  return {
    title: presentation.title,
    operation: presentation.operation,
    displayOnly: presentation.displayOnly,
    presentationState: presentation.presentationState,
    context,
    selectedEvidence: context ? [context] : []
  };
}

export function toolResultFollowUpPrompt(record, options = {}) {
  const request = toolResultFollowUpRequest(record, options);
  return request.context && request.context.prompt_text ? request.context.prompt_text : '';
}

export function renderToolResultPrimaryPanels(record, options = {}) {
  const panels = [];
  const presentation = toolResultPresentation(record, options);
  if (presentation.canRenderResult) {
    const resultPanel = renderGenomiResultPanel(record, {
      ...options,
      operation: presentation.operation,
      payload: presentation.payload,
      normalized: presentation.normalized,
      resultModel: presentation.resultModel,
      displayOnly: presentation.displayOnly,
      presentationState: presentation.presentationState,
      actions: options.actions === false ? false : presentation.canAttach
    });
    if (resultPanel) panels.push({ kind: 'result_view', node: resultPanel });
    return panels;
  }
  if (presentation.canRenderEvidence) {
    const evidencePanel = renderEvidencePanel(record, {
      ...options,
      toolNameLabel,
      operation: presentation.operation,
      payload: presentation.payload,
      normalized: presentation.normalized,
      displayOnly: presentation.displayOnly,
      presentationState: presentation.presentationState
    });
    if (evidencePanel) {
      if (options.actions === false) {
        evidencePanel.querySelectorAll('.evidence-actions').forEach((node) => node.remove());
      }
      panels.push({ kind: 'evidence', node: evidencePanel });
    }
  }
  return panels;
}

export function renderToolResultSections(record, options = {}) {
  const presentation = toolResultPresentation(record, options);
  const sections = renderToolResultPrimaryPanels(record, { ...options, ...presentation });
  const tracePanel = renderResultTraceDetails(presentation.payload);
  if (tracePanel) sections.push({ kind: 'trace', node: tracePanel });
  return sections;
}

export function fallbackToolDetails(record) {
  const parts = [];
  if (record.call && record.call.input !== undefined) {
    parts.push({ label: 'Request', text: formatPayload(record.call.input) || '{}' });
  }
  if (record.result) {
    parts.push({ label: record.result.isError ? 'Error' : 'Result', text: formatPayload(record.result.content || record.result.message || record.result) });
  }
  if (!parts.length) parts.push({ label: 'Event', text: formatPayload(record.call || record.result || {}) });
  return parts;
}

function presentationKind({ operation, displayOnly, persistedRedacted, hasCanonicalEnvelope, canRenderResult }) {
  if (persistedRedacted) return 'persisted_redacted';
  if (displayOnly && !hasCanonicalEnvelope && !canRenderResult) return 'display_only';
  if (hasCanonicalEnvelope) return 'evidence';
  if (operation === 'genomi.describe_context' && canRenderResult) return 'session_context';
  if (canRenderResult) return 'result_view';
  return 'workflow_event';
}

function toolResultFollowUpContext(record, presentation) {
  if (presentation.displayOnly) {
    return fallbackToolFollowUpContext(record, presentation);
  }
  if (presentation.canRenderResult) {
    const resultPacket = genomiResultContextPayload(record, null, presentation);
    if (resultPacket) return resultPacket;
  }
  if (presentation.kind === 'evidence') {
    const packet = evidenceSelectedPacketForPayload(presentation.payload, presentation.operation, [], {
      sourceOperation: presentation.operation,
      toolCallId: record.call && record.call.id,
      toolResultId: record.result && record.result.id
    });
    if (packet) return packet;
  }
  return fallbackToolFollowUpContext(record, presentation);
}

function fallbackToolFollowUpContext(record, presentation) {
  const summary = presentation.summary || fallbackToolDetails(record).map((part) => part.label + ': ' + part.text).join('\n');
  if (presentation.displayOnly) {
    const title = presentation.title || presentation.operation || 'Genomi evidence';
    return buildSelectedEvidencePayload({
      contextKind: 'work_trace',
      label: 'Saved evidence: ' + title,
      summary,
      sourceOperation: presentation.operation,
      toolCallId: record.call && record.call.id,
      toolResultId: record.result && record.result.id,
      fallbackNodes: [{
        label: 'Saved evidence',
        text: summary || 'Saved Genomi evidence captured in this conversation; re-check current tools before using it.'
      }],
      promptIntro: 'Selected saved evidence to re-check: ' + title
    });
  }
  return buildSelectedEvidencePayload({
    contextKind: 'result_nodes',
    label: presentation.title || presentation.operation || 'Research summary',
    summary,
    sourceOperation: presentation.operation,
    toolCallId: record.call && record.call.id,
    toolResultId: record.result && record.result.id,
    fallbackNodes: [{ label: 'Work summary', text: summary || 'Research work captured in this conversation.' }],
    promptIntro: 'Selected research work: ' + (presentation.title || presentation.operation || 'Research step')
  });
}

function selectedResultNodesPayload(presentation, record, selectedNodes, options) {
  return buildSelectedEvidencePayload({
    contextKind: 'result_nodes',
    evidenceEnvelope: presentation.resultModel && presentation.resultModel.evidenceEnvelope || presentation.normalized && presentation.normalized.envelope,
    label: presentation.title,
    summary: presentation.summary,
    sourceOperation: presentation.operation,
    toolCallId: record.call && record.call.id,
    toolResultId: record.result && record.result.id,
    selectedNodes,
    promptIntro: options.selectedPromptIntro || 'Selected result: ' + presentation.title
  });
}

function selectedEvidenceNodesPayload(presentation, record, selectedNodes, options) {
  return evidenceSelectedPacketForPayload(presentation.payload, presentation.operation, selectedNodes, {
    sourceOperation: presentation.operation,
    toolCallId: record.call && record.call.id,
    toolResultId: record.result && record.result.id,
    promptIntro: options && options.selectedPromptIntro
  });
}

function recordDisplayOnly(record) {
  const result = (record && record.result) || {};
  const call = (record && record.call) || {};
  const resultLedger = object(result.ledger);
  const callLedger = object(call.ledger);
  return Boolean(resultLedger.display_only || callLedger.display_only || result.persisted_display_only || call.persisted_display_only);
}

function resultPresentationState(record, payload, displayOnly, options) {
  const explicit = stringValue(options.presentationState) ||
    stringValue(record && record.result && record.result.presentation_state) ||
    stringValue(record && record.call && record.call.presentation_state) ||
    stringValue(record && record.result && record.result.ledger && record.result.ledger.presentation_state) ||
    stringValue(record && record.call && record.call.ledger && record.call.ledger.presentation_state) ||
    stringValue(payload && payload.presentation_state);
  if (explicit) return explicit;
  if (displayOnly && normalizeEvidencePayload(payload)) return PERSISTED_REDACTED_PRESENTATION_STATE;
  if (displayOnly) return DISPLAY_ONLY_PRESENTATION_STATE;
  return LIVE_PRESENTATION_STATE;
}

function stringValue(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : '';
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}
