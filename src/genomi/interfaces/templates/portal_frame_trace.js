import { compactLine, formatPayload, formatShort, humanizeState } from './portal_format.js';
import { absolutePortalUrl, artifactRoutePath, frameRoutePath } from './portal_artifact_route_model.js';
import { promptSafeText, selectedEvidencePayload as buildSelectedEvidencePayload } from './portal_selected_evidence.js';
import {
  renderToolResultPrimaryPanels,
  toolNameLabel,
  toolResultFollowUpRequest,
  toolResultSummary
} from './portal_tool_result_presentation.js';
import { renderToolTechnicalDetails } from './portal_tool_details.js';

const MAX_TRACE_STEPS = 24;
const DIAGNOSTIC_OUTPUT_SUMMARY = 'Host-agent diagnostic output recorded.';

export function frameWorkTraceModel(messages = [], options = {}) {
  const messageSteps = traceStepsFromMessages(messages);
  const steps = [
    ...messageSteps,
    ...traceStepsFromExecutionCells(options.executionCells, messageSteps)
  ];
  const counts = traceCounts(steps);
  const displayed = steps.slice(-MAX_TRACE_STEPS);
  return {
    total: steps.length,
    displayed: displayed.length,
    hasMore: steps.length > displayed.length,
    counts,
    status: counts.errors ? 'needs_attention' : counts.running ? 'running' : steps.length ? 'ready' : 'empty',
    summary: traceSummary(steps, counts),
    steps: displayed
  };
}

export function frameTraceMessageFromToolRecord(record) {
  const messages = frameTraceMessagesFromToolRecord(record);
  return messages.length ? messages[messages.length - 1] : null;
}

export function frameTraceMessagesFromToolRecord(record) {
  if (!record || (!record.call && !record.result)) return [];
  const messages = [];
  if (record.call) {
    messages.push(traceBridgeMessage(record, { ...record.call, type: 'tool_call' }, 'call'));
  }
  if (record.result) {
    const callOperation = eventOperation(record.call);
    const resultEvent = {
      ...record.result,
      type: record.result.isError ? 'error' : 'tool_result'
    };
    if (!eventOperation(resultEvent) && callOperation) resultEvent.name = callOperation;
    messages.push(traceBridgeMessage(record, resultEvent, 'result'));
  }
  return messages;
}

export function frameTraceRecordKey(record) {
  const scope = object(record && record.scope);
  const event = (record && (record.result || record.call)) || {};
  const eventId = String(event.id || (record && record.call && record.call.id) || '').trim();
  const frameId = scope.frameId || 'frame';
  const runId = scope.runId || 'run';
  if (eventId) return [frameId, runId, 'tool', eventId].join(':');
  return [
    frameId,
    runId,
    eventOperation(event) || eventOperation(record && record.call) || 'tool',
    scope.messageId || 'event'
  ].join(':');
}

function traceBridgeMessage(record, event, phase) {
  const scope = object(record.scope);
  return {
    id: [scope.messageId || frameTraceRecordKey(record), phase].join(':'),
    role: 'tool',
    frame_id: scope.frameId,
    run_id: scope.runId,
    event
  };
}

export function frameTraceSummaryPayload(modelOrMessages, options = {}) {
  const presentation = workTracePresentation(options);
  const model = Array.isArray(modelOrMessages) ? frameWorkTraceModel(modelOrMessages, options) : modelOrMessages;
  if (!model || !Array.isArray(model.steps) || !model.steps.length) return null;
  return buildSelectedEvidencePayload({
    contextKind: 'work_trace',
    label: presentation.summaryLabel,
    summary: model.summary,
    sourceOperation: presentation.summarySourceOperation,
    fallbackNodes: model.steps.slice(-8).map((step, index) => frameTraceStepContextNode(step, index)),
    promptIntro: presentation.summaryPromptIntro
  });
}

export function frameTraceStepPayload(step, index = 0, options = {}) {
  if (!step) return null;
  const presentation = workTracePresentation(options);
  const operation = promptSafeText(step.operation || 'tool');
  const title = promptSafeText(step.title || frameTraceStepTitle(operation));
  const summary = promptSafeText(step.summary || frameTraceStepPromptLine(step));
  return buildSelectedEvidencePayload({
    contextKind: 'work_trace',
    label: 'Work step: ' + title,
    summary,
    sourceOperation: operation,
    selectedNodes: [frameTraceStepContextNode(step, index)],
    promptIntro: presentation.stepPromptIntro + title
  });
}

export function frameTraceStepContextNode(step, index = 0, options = {}) {
  const operation = promptSafeText(step && step.operation ? step.operation : 'tool');
  const title = promptSafeText(step && step.title ? step.title : frameTraceStepTitle(operation));
  const status = promptSafeText(step && step.status ? step.status : '');
  const presentation = promptSafeText(step && step.presentationState ? step.presentationState : '');
  const summary = promptSafeText(step && step.summary ? step.summary : '');
  const runId = promptSafeText(step && step.runId ? step.runId : '');
  const messageCount = Array.isArray(step && step.messageIds) ? step.messageIds.length : 0;
  const eventCount = Array.isArray(step && step.eventIds) ? step.eventIds.length : 0;
  const line = frameTraceStepPromptLine({ operation, status, presentationState: presentation, summary });
  const structuredValue = {
    operation,
    status,
    presentation,
    summary,
    run_id: runId,
    message_count: messageCount,
    event_count: eventCount,
    kind: promptSafeText(step && step.kind ? step.kind : ''),
    event_range: object(step && step.eventRange)
  };
  return {
    label: String(index + 1) + '. ' + title,
    text: line,
    summary: compactLine(line, 180),
    value: options.structuredValue ? structuredValue : (summary || line)
  };
}

export function frameTraceStepPromptLine(step) {
  const operation = promptSafeText(step && step.operation ? step.operation : 'tool');
  const title = promptSafeText(step && step.title ? step.title : frameTraceStepTitle(operation));
  const status = promptSafeText(step && step.status ? step.status : '');
  const presentation = presentationStateLabel(step && step.presentationState ? step.presentationState : '');
  const summary = promptSafeText(step && step.summary ? step.summary : '');
  return [
    'Work trail / ' + title,
    status ? 'status: ' + status : '',
    presentation ? 'presentation: ' + presentation : '',
    summary ? 'summary: ' + summary : ''
  ].filter(Boolean).join(' / ');
}

export function renderFrameWorkTrace(container, messages = [], options = {}) {
  if (!container) return;
  const model = frameWorkTraceModel(messages, options);
  container.innerHTML = '';
  if (!model.steps.length) {
    container.appendChild(emptyTraceBlock(options));
    return;
  }
  container.appendChild(traceToolbar(model, options));
  const list = document.createElement('div');
  list.className = 'frame-trace-list';
  model.steps.forEach((step, index) => {
    list.appendChild(traceStepCard(step, index, options));
  });
  container.appendChild(list);
  focusHighlightedWorkStep(list, options.highlightStepId);
}

export function traceStepsFromMessages(messages = []) {
  const byKey = new Map();
  const orderedKeys = [];
  (Array.isArray(messages) ? messages : []).forEach((message, index) => {
    const event = object(message && message.event);
    if (!isToolEvent(event)) return;
    const key = traceMessageKey(message, event, index);
    let step = byKey.get(key);
    if (!step) {
      step = newTraceStep(message, event, key, index);
      byKey.set(key, step);
      orderedKeys.push(key);
    }
    mergeTraceEvent(step, message, event);
  });
  return orderedKeys.map((key) => finalizeTraceStep(byKey.get(key))).filter(Boolean);
}

export function traceStepsFromExecutionCells(executionCells = null, existingSteps = []) {
  const items = executionCellItems(executionCells);
  if (!items.length) return [];
  const seenToolKeys = new Set(
    (Array.isArray(existingSteps) ? existingSteps : [])
      .map((step) => step && step.toolExecutionKey)
      .filter(Boolean)
  );
  return items
    .map((cell, index) => executionCellStep(cell, index, executionCells))
    .filter((step) => {
      if (!step) return false;
      if (step.kind === 'tool' && step.toolExecutionKey && seenToolKeys.has(step.toolExecutionKey)) return false;
      return true;
    });
}

function traceToolbar(model, options) {
  const presentation = workTracePresentation(options);
  const toolbar = document.createElement('div');
  toolbar.className = 'frame-trace-toolbar';
  toolbar.innerHTML = [
    '<div class="frame-trace-summary">',
    '<strong></strong>',
    '<span></span>',
    '</div>',
    '<div class="frame-trace-metrics"></div>',
    '<div class="frame-trace-actions"></div>'
  ].join('');
  toolbar.querySelector('strong').textContent = presentation.toolbarTitle;
  toolbar.querySelector('span').textContent = model.summary;
  const metrics = toolbar.querySelector('.frame-trace-metrics');
  [
    ['Steps', model.total],
    ['Running', model.counts.running],
    ['Errors', model.counts.errors]
  ].forEach(([label, value]) => metrics.appendChild(traceMetric(label, value)));
  const actions = toolbar.querySelector('.frame-trace-actions');
  if (model.hasMore) {
    const more = document.createElement('span');
    more.className = 'frame-trace-more';
    more.textContent = 'Showing latest ' + model.displayed + ' of ' + model.total;
    actions.appendChild(more);
  }
  return toolbar;
}

function traceStepCard(step, index, options) {
  const card = document.createElement('div');
  const workStepId = workStepRouteId(step);
  const highlighted = workStepId && workStepId === firstText(options.highlightStepId);
  card.className = 'frame-trace-step ' + step.statusClass + (highlighted ? ' highlighted' : '');
  card.setAttribute('data-testid', 'frame-trace-step');
  if (workStepId) card.dataset.workStepId = workStepId;
  if (highlighted) card.setAttribute('data-highlighted-step', 'true');
  card.innerHTML = [
    '<div class="frame-trace-step-head">',
    '<div><span></span><strong></strong><p></p></div>',
    '<em></em>',
    '</div>',
    '<div class="frame-trace-badges"></div>',
    '<div class="frame-trace-step-actions"></div>',
    '<details class="frame-trace-step-details"><summary>View details</summary><div class="frame-trace-step-detail-body"></div></details>'
  ].join('');
  card.querySelector('.frame-trace-step-head span').textContent = String(index + 1).padStart(2, '0') + ' / ' + step.status;
  card.querySelector('.frame-trace-step-head strong').textContent = step.title;
  card.querySelector('.frame-trace-step-head p').textContent = step.summary || 'Work step recorded';
  card.querySelector('.frame-trace-step-head em').textContent = step.displayOnly ? 'Saved result' : 'Work step';
  const badges = card.querySelector('.frame-trace-badges');
  [presentationStateLabel(step.presentationState), traceStepCountLabel(step), executionKindLabel(step.kind)]
    .filter(Boolean)
    .forEach((badge) => badges.appendChild(traceBadge(badge)));
  const actions = card.querySelector('.frame-trace-step-actions');
  traceStepNavigationActions(step, options).forEach((action) => {
    actions.appendChild(actionLink(action.label, action.href, action.testId));
  });
  if (typeof options.onAskFollowUp === 'function') {
    actions.appendChild(actionButton(step.displayOnly ? 'Re-check evidence' : 'Ask follow-up', () => {
      options.onAskFollowUp(toolResultFollowUpRequest(step.record));
    }));
  }
  const body = card.querySelector('.frame-trace-step-detail-body');
  const panels = renderToolResultPrimaryPanels(step.record, {
    operation: step.operation,
    displayOnly: step.displayOnly,
    presentationState: step.presentationState,
    title: step.title,
    summary: step.summary,
    actions: false
  });
  panels.forEach((section) => body.appendChild(section.node));
  if (step.executionCell) body.appendChild(renderExecutionCellDetails(step));
  const technicalDetails = renderStepTechnicalDetails(step);
  if (technicalDetails) body.appendChild(technicalDetails);
  return card;
}

function focusHighlightedWorkStep(list, highlightStepId) {
  const cleanStepId = firstText(highlightStepId);
  if (!list || !cleanStepId) return;
  const step = Array.from(list.querySelectorAll('[data-work-step-id]'))
    .find((node) => node && node.dataset && node.dataset.workStepId === cleanStepId);
  if (!step || typeof step.scrollIntoView !== 'function') return;
  step.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

function traceMetric(label, value) {
  const metric = document.createElement('div');
  metric.className = 'frame-trace-metric';
  metric.innerHTML = '<span></span><strong></strong>';
  metric.querySelector('span').textContent = label;
  metric.querySelector('strong').textContent = String(value ?? 0);
  return metric;
}

function traceBadge(text) {
  const badge = document.createElement('span');
  badge.textContent = compactLine(text, 80);
  return badge;
}

function traceStepCountLabel(step) {
  const messageCount = Array.isArray(step && step.messageIds) ? step.messageIds.length : 0;
  if (messageCount) return 'Conversation update';
  const eventCount = Array.isArray(step && step.eventIds) ? step.eventIds.length : 0;
  if (eventCount) return 'Assistant update';
  return '';
}

function executionKindLabel(kind) {
  const clean = String(kind || '').trim();
  if (!clean || clean === 'tool') return '';
  if (clean === 'stdout' || clean === 'stderr') return 'Diagnostic output';
  if (clean === 'run') return 'Assistant update';
  return humanizeState(clean);
}

function renderExecutionCellDetails(step) {
  const cell = object(step && step.executionCell);
  const block = document.createElement('div');
  block.className = 'frame-trace-execution-cell';
  const parts = [
    { label: 'Kind', text: executionKindLabel(cell.kind) || cell.kind },
    { label: 'Status', text: cell.status },
    { label: 'Summary', text: executionCellVisibleSummary(cell) }
  ].filter((part) => promptSafeText(part.text).trim());
  if (!parts.length) {
    block.textContent = 'Execution step recorded.';
    return block;
  }
  parts.forEach((part) => block.appendChild(traceDetailPart(part)));
  return block;
}

function presentationStateLabel(value) {
  const state = promptSafeText(value || '').trim();
  if (!state) return '';
  if (state === 'persisted_redacted') return 'Saved redacted history';
  return humanizeState(state);
}

function traceDetailPart(part) {
  const block = document.createElement('div');
  block.className = 'frame-trace-detail-part';
  block.innerHTML = '<div class="tool-detail-label"></div><pre class="tool-detail-pre"></pre>';
  block.querySelector('.tool-detail-label').textContent = part.label;
  block.querySelector('.tool-detail-pre').textContent = part.text || '';
  return block;
}

function renderStepTechnicalDetails(step) {
  const recordDetails = renderToolTechnicalDetails(step.record, { summary: 'Technical details' });
  if (!recordDetails && !step.operation && !step.runId) return null;
  const details = recordDetails || document.createElement('details');
  details.classList.add('frame-trace-technical-details');
  if (!recordDetails) {
    const summary = document.createElement('summary');
    summary.textContent = 'Technical details';
    details.appendChild(summary);
  }
  const body = details.querySelector('.tool-technical-details-body') || document.createElement('div');
  if (!body.parentNode) {
    body.className = 'tool-technical-details-body';
    details.appendChild(body);
  }
  [
    { label: 'Operation', text: step.operation },
    { label: 'Run', text: step.runId },
    { label: 'Event range', text: technicalEventRange(step) },
    { label: 'Event records', text: technicalEventCount(step) }
  ].filter((part) => part.text).forEach((part) => {
    body.appendChild(traceDetailPart(part));
  });
  return details;
}

function technicalEventRange(step) {
  const range = object(step && (step.eventRange || object(step.executionCell).event_range));
  const first = range.first || '';
  const last = range.last || '';
  if (!first && !last) return '';
  if (last && last !== first) return String(first || '') + '-' + String(last);
  return String(first || last);
}

function technicalEventCount(step) {
  const count = Array.isArray(step && step.eventIds) ? step.eventIds.length : 0;
  return count ? String(count) : '';
}

function actionButton(label, handler, testId = '') {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'tool-action';
  if (testId) button.setAttribute('data-testid', testId);
  button.textContent = label;
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    handler();
  });
  return button;
}

function actionLink(label, href, testId = '') {
  const link = document.createElement('a');
  link.className = 'tool-action';
  link.textContent = label;
  link.href = href;
  if (testId) link.setAttribute('data-testid', testId);
  link.addEventListener('click', (event) => {
    event.stopPropagation();
  });
  return link;
}

function traceStepNavigationActions(step, options = {}) {
  const links = object(step && step.links);
  const baseUrl = firstText(options.baseUrl, currentHref(), 'http://localhost');
  const actions = [];
  const artifactRoute = firstText(links.artifactRoute);
  if (artifactRoute) {
    actions.push({
      label: 'Open artifact',
      href: absolutePortalUrl(artifactRoute, baseUrl),
      testId: 'genomi-work-step-open-artifact'
    });
  }
  const chatRoute = firstText(links.chatRoute);
  if (chatRoute) {
    actions.push({
      label: 'View in chat',
      href: absolutePortalUrl(chatRoute, baseUrl),
      testId: 'genomi-work-step-view-chat'
    });
  }
  return actions;
}

function emptyTraceBlock(options = {}) {
  const presentation = workTracePresentation(options);
  const empty = document.createElement('div');
  empty.className = 'frame-trace-empty';
  empty.innerHTML = '<strong></strong><span></span>';
  empty.querySelector('strong').textContent = presentation.emptyTitle;
  empty.querySelector('span').textContent = presentation.emptyText;
  return empty;
}

function workTracePresentation(options = {}) {
  const presentation = object(options.workTracePresentation);
  return {
    summaryLabel: String(presentation.summaryLabel || 'Conversation work trail'),
    summarySourceOperation: String(presentation.summarySourceOperation || 'genomi.portal.frame_work_trace'),
    summaryPromptIntro: String(presentation.summaryPromptIntro || 'Selected conversation work trail:'),
    stepPromptIntro: String(presentation.stepPromptIntro || 'Selected work step: '),
    toolbarTitle: String(presentation.toolbarTitle || 'Work done in this conversation'),
    emptyTitle: String(presentation.emptyTitle || 'No work yet'),
    emptyText: String(presentation.emptyText || 'Assistant work, evidence-source requests, results, and errors from this conversation will appear here as a work trail.')
  };
}

function newTraceStep(message, event, key, index) {
  return {
    key,
    index,
    operation: eventName(event),
    record: { call: null, result: null, scope: traceScope(message) },
    messageIds: [],
    createdAt: message && message.created_at,
    runId: message && message.run_id
  };
}

function mergeTraceEvent(step, message, event) {
  const messageId = String((message && message.id) || '').trim();
  if (messageId && !step.messageIds.includes(messageId)) step.messageIds.push(messageId);
  step.record.scope = { ...step.record.scope, ...traceScope(message) };
  step.operation = eventOperation(event) || step.operation;
  step.runId = (message && message.run_id) || step.runId;
  if (event.type === 'tool_call') {
    step.record.call = event;
    return;
  }
  step.record.result = event.type === 'error' ? errorResultFromEvent(event) : event;
}

function finalizeTraceStep(step) {
  if (!step) return null;
  const result = step.record.result || {};
  const call = step.record.call || {};
  const ledger = object(result.ledger || call.ledger);
  const status = traceStatus(step.record, ledger);
  const operation = step.operation || eventName(result) || eventName(call) || 'tool';
  const toolId = String(result.id || call.id || '').trim();
  return {
    ...step,
    operation,
    kind: 'tool',
    toolId,
    toolExecutionKey: toolExecutionKey(step.runId, toolId),
    title: frameTraceStepTitle(operation),
    status,
    statusClass: statusClass(status),
    summary: traceStepSummary(step.record, ledger),
    displayOnly: Boolean(ledger.display_only || result.persisted_display_only || call.persisted_display_only),
    presentationState: result.presentation_state || call.presentation_state || ledger.presentation_state || '',
    record: {
      ...step.record,
      scope: {
        ...step.record.scope,
        messageId: step.messageIds[0] || step.record.scope.messageId
      }
    }
  };
}

function executionCellItems(executionCells) {
  if (Array.isArray(executionCells)) {
    const includeDiagnostics = Boolean(executionCells.include_diagnostics);
    return executionCells.filter((cell) => visibleExecutionCell(cell, includeDiagnostics));
  }
  if (executionCells && typeof executionCells === 'object' && Array.isArray(executionCells.items)) {
    const runId = String(executionCells.run_id || '').trim();
    const includeDiagnostics = Boolean(executionCells.include_diagnostics);
    return executionCells.items
      .filter((cell) => visibleExecutionCell(cell, includeDiagnostics))
      .map((cell) => ({ ...cell, run_id: cell.run_id || runId }));
  }
  return [];
}

function visibleExecutionCell(cell, includeDiagnostics = false) {
  if (!cell || typeof cell !== 'object') return false;
  const visibility = String(cell.visibility || '').trim();
  if (visibility === 'technical') return false;
  const kind = String(cell.kind || '').trim();
  if (!includeDiagnostics && (kind === 'diagnostic' || kind === 'stdout' || kind === 'stderr')) return false;
  return true;
}

function executionCellStep(cell, index, source) {
  const kind = String(cell.kind || '').trim() || 'step';
  const runId = String(cell.run_id || (source && source.run_id) || '').trim();
  const artifact = object(cell.artifact);
  const operation = String(cell.operation || (kind === 'tool' ? cell.title : 'genomi.portal.execution_cell')).trim();
  const toolId = executionCellToolId(cell);
  const summary = compactLine(executionCellVisibleSummary(cell), 180);
  const status = String(cell.status || 'completed').trim() || 'completed';
  const projectId = firstText(cell.project_id, artifact.project_id);
  const frameId = firstText(cell.frame_id);
  const workStepId = executionCellRouteId(cell, { runId, index });
  return {
    key: 'execution:' + (cell.id || index),
    workStepId,
    index,
    kind,
    operation,
    toolId,
    toolExecutionKey: kind === 'tool' ? toolExecutionKey(runId, toolId) : '',
    title: executionCellTitle(cell),
    status,
    statusClass: statusClass(status),
    summary,
    displayOnly: false,
    presentationState: '',
    record: executionCellRecord(cell, runId),
    messageIds: [],
    eventIds: Array.isArray(cell.event_ids) ? cell.event_ids : [],
    eventRange: object(cell.event_range),
    runId,
    projectId,
    frameId,
    artifact,
    links: executionCellLinks(cell, { runId, projectId, frameId, artifact, workStepId }),
    executionCell: cell
  };
}

function executionCellTitle(cell) {
  const kind = String(cell.kind || '').trim();
  const title = promptSafeText(cell.title || '').trim();
  if (kind === 'tool') return frameTraceStepTitle(cell.operation || title || 'tool');
  if (kind === 'stdout' || kind === 'stderr') return 'Diagnostic output';
  if (kind === 'run') return title || 'Assistant update';
  if (kind === 'artifact') return title || 'Artifact update';
  if (kind === 'diagnostic') return title || 'Diagnostic';
  return title || 'Work step';
}

function executionCellSummary(cell) {
  const kind = String(cell && cell.kind || '').trim();
  if (isDiagnosticOutputKind(kind)) return DIAGNOSTIC_OUTPUT_SUMMARY;
  if (kind === 'artifact') return 'Artifact update recorded.';
  if (kind === 'run') return 'Assistant update recorded.';
  return 'Execution step recorded.';
}

function executionCellVisibleSummary(cell) {
  const kind = String(cell && cell.kind || '').trim();
  if (isDiagnosticOutputKind(kind)) return DIAGNOSTIC_OUTPUT_SUMMARY;
  return (cell && cell.summary) || executionCellSummary(cell);
}

function isDiagnosticOutputKind(kind) {
  const clean = String(kind || '').trim();
  return clean === 'stdout' || clean === 'stderr';
}

function executionCellToolId(cell) {
  const id = String(cell.id || '').trim();
  if (id.includes(':tool:')) return id.split(':tool:').pop();
  const records = Array.isArray(cell.records) ? cell.records : [];
  for (const record of records) {
    const data = object(record && record.data);
    const toolId = String(data.id || data.call_id || '').trim();
    if (toolId) return toolId;
  }
  return '';
}

function executionCellRecord(cell, runId) {
  const records = Array.isArray(cell.records) ? cell.records : [];
  const first = object(records[0]);
  const data = object(first.data);
  if (cell.kind === 'tool') {
    const event = {
      type: cell.status === 'error' ? 'error' : 'tool_result',
      id: executionCellToolId(cell),
      name: cell.operation,
      content: cell.summary,
      ledger: {
        status: cell.status,
        summary: cell.summary
      }
    };
    return { call: null, result: event, scope: { frameId: cell.frame_id, runId } };
  }
  return {
    call: null,
    result: {
      type: String(cell.kind || 'execution_cell'),
      id: String(cell.id || ''),
      name: String(cell.kind || 'execution_cell'),
      content: executionCellRecordContent(cell, data),
      ledger: {
        status: cell.status,
        summary: executionCellRecordContent(cell, data)
      }
    },
    scope: { frameId: cell.frame_id, runId }
  };
}

function executionCellRecordContent(cell, data) {
  if (isDiagnosticOutputKind(cell && cell.kind)) return DIAGNOSTIC_OUTPUT_SUMMARY;
  return (cell && cell.summary) || data.message || data.chunk || '';
}

function executionCellLinks(cell, context) {
  const projectId = firstText(context.projectId);
  const frameId = firstText(context.frameId);
  const runId = firstText(context.runId);
  const artifact = object(context.artifact);
  const artifactId = firstText(artifact.id, cell && cell.artifact_id);
  const versionId = firstText(artifact.latest_version_id, cell && cell.latest_version_id);
  const workStepId = firstText(context.workStepId);
  const artifactRoute = firstText(artifact.workspace_route) || (
    projectId && artifactId ? artifactRoutePath(projectId, artifactId, versionId) : ''
  );
  const chatRoute = projectId && frameId && runId ? frameRoutePath(projectId, frameId, runId, workStepId) : '';
  return cleanObject({
    artifactRoute,
    chatRoute
  });
}

function executionCellRouteId(cell, context = {}) {
  const cellId = firstText(cell && cell.id);
  if (cellId) return cellId;
  return [
    firstText(context.runId) || 'run',
    'execution',
    String(context.index || 0)
  ].join(':');
}

function workStepRouteId(step) {
  return firstText(step && step.workStepId, step && step.executionCell && step.executionCell.id);
}

function toolExecutionKey(runId, toolId) {
  const cleanToolId = String(toolId || '').trim();
  if (!cleanToolId) return '';
  return [String(runId || '').trim() || 'run', cleanToolId].join(':tool:');
}

function frameTraceStepTitle(operation) {
  const label = toolNameLabel(operation);
  if (label !== operation || !/^[a-z0-9_.-]+$/i.test(operation)) return label;
  return String(operation)
    .split(/[_.-]+/)
    .filter(Boolean)
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(' ');
}

function traceStatus(record, ledger) {
  if (record.result && record.result.isError) return 'error';
  if (ledger.status) return String(ledger.status);
  if (record.result) return 'completed';
  return 'running';
}

function traceStepSummary(record, ledger) {
  if (ledger.summary) return compactLine(ledger.summary, 180);
  if (ledger.headline) return compactLine(ledger.headline, 180);
  if (record.result) return toolResultSummary(record.result);
  const input = record.call && record.call.input;
  if (input && typeof input === 'object') {
    for (const key of ['summary', 'description', 'operation', 'rsid', 'query', 'drug', 'gene', 'phenotype']) {
      if (typeof input[key] === 'string' && input[key].trim()) return compactLine(input[key], 180);
    }
  }
  return compactLine(formatShort(input || record.call || {}), 180);
}

function traceCounts(steps) {
  const counts = { completed: 0, running: 0, errors: 0 };
  steps.forEach((step) => {
    const cls = step.statusClass || statusClass(step.status);
    if (cls === 'error') counts.errors += 1;
    else if (cls === 'running') counts.running += 1;
    else counts.completed += 1;
  });
  return counts;
}

function traceSummary(steps, counts) {
  if (!steps.length) return 'No work steps have been recorded for this conversation.';
  const parts = [
    steps.length + ' work step' + (steps.length === 1 ? '' : 's'),
    counts.running ? counts.running + ' running' : '',
    counts.errors ? counts.errors + ' needing attention' : ''
  ].filter(Boolean);
  return parts.join(' · ');
}

function traceMessageKey(message, event, index) {
  const id = String(event.id || '').trim();
  const runId = String((message && message.run_id) || '').trim();
  const frameId = String((message && message.frame_id) || '').trim();
  const operation = eventOperation(event) || 'tool';
  if (id) return [frameId || 'frame', runId || 'run', 'tool', id].join(':');
  return [frameId || 'frame', runId || 'run', operation, 'message', message && message.id || index].join(':');
}

function traceRecordKey(record) {
  return frameTraceRecordKey(record);
}

function traceScope(message) {
  return {
    frameId: message && message.frame_id,
    runId: message && message.run_id,
    messageId: message && message.id
  };
}

function isToolEvent(event) {
  return ['tool_call', 'tool_result', 'error'].includes(String(event.type || ''));
}

function errorResultFromEvent(event) {
  return {
    id: event.id,
    name: event.name,
    isError: true,
    content: event.message || event.content || formatPayload(event),
    ledger: event.ledger,
    persisted_display_only: event.persisted_display_only,
    presentation_state: event.presentation_state
  };
}

function eventName(event) {
  return eventOperation(event) || 'tool';
}

function eventOperation(event) {
  return String((event && (event.name || object(event.ledger).operation)) || '').trim();
}

function statusClass(status) {
  const clean = String(status || '').toLowerCase();
  if (clean.includes('error') || clean.includes('fail') || clean.includes('canceled') || clean.includes('stale')) return 'error';
  if (clean.includes('running') || clean.includes('stream') || clean.includes('queued') || clean.includes('progress')) return 'running';
  return 'completed';
}

function shortId(value) {
  const text = String(value || '');
  return text.length > 10 ? text.slice(0, 10) : text;
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function firstText(...values) {
  for (const value of values) {
    const text = String(value || '').trim();
    if (text) return text;
  }
  return '';
}

function cleanObject(value) {
  const result = {};
  Object.entries(object(value)).forEach(([key, item]) => {
    if (item !== undefined && item !== null && item !== '') result[key] = item;
  });
  return result;
}

function currentHref() {
  if (typeof window !== 'undefined' && window.location && window.location.href) return window.location.href;
  return '';
}
