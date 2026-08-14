import { compactLine, formatShort, humanizeState } from './portal_format.js';
import { installLedgerSelectionControls, ledgerSelectionControlsMarkup } from './portal_evidence_ledger_selection.js';
import { extractPresentedPayload } from './portal_presented_payload.js';
import { promptSafeText, selectedEvidencePayload as buildSelectedEvidencePayload } from './portal_selected_evidence.js';
import {
  renderToolResultPrimaryPanels,
  toolNameLabel,
  toolResultContextPayload,
  toolResultFollowUpRequest,
  toolResultPresentation,
  toolResultSummary
} from './portal_tool_result_presentation.js';

export function createEvidenceLedger({ container, detailContainer, onUseContext, onAskContext, onAskNewContext, onDraftContext, onAskFollowUp }) {
  let entries = [];
  let activeKey = null;
  let filter = 'all';
  let scope = ledgerScopeModel();

  function reset() {
    entries = [];
    activeKey = null;
    render();
  }

  function upsert(record) {
    const entry = ledgerEntryModel(record);
    if (!entry || !entryBelongsInEvidenceLedger(entry)) return;
    entries = [entry, ...entries.filter((item) => item.key !== entry.key)].slice(0, 12);
    if (entryMatchesScope(entry, scope)) activeKey = entry.key;
    else if (!activeVisibleEntries().some((item) => item.key === activeKey)) activeKey = activeVisibleEntries()[0] && activeVisibleEntries()[0].key || null;
    render();
  }

  function setScope(nextScope = {}) {
    scope = ledgerScopeModel(nextScope);
    if (activeKey && !visibleEntries().some((entry) => entry.key === activeKey)) activeKey = activeVisibleEntries()[0] && activeVisibleEntries()[0].key || null;
    render();
  }

  function select(key) {
    activeKey = key;
    render();
  }

  function setFilter(nextFilter) {
    filter = nextFilter || 'all';
    const shown = activeVisibleEntries();
    if (shown.length && !shown.some((entry) => entry.key === activeKey)) activeKey = shown[0].key;
    render();
  }

  function render() {
    renderList();
    renderDetail();
  }

  function renderList() {
    if (!container) return;
    container.innerHTML = '';
    const scopedEntries = visibleEntries();
    if (!scopedEntries.length) {
      container.appendChild(emptyBlock(
        'No current evidence yet',
        'Evidence results from ' + scope.label + ' will appear here for inspection and reuse. Reopening the conversation restores saved evidence from its work history.'
      ));
      return;
    }
    container.appendChild(ledgerToolbar(scopedEntries, filter, {
      scope,
      onFilter: setFilter,
      onUseSummary: () => {
        const payload = ledgerSummaryPayload(scopedEntries);
        if (payload && typeof onUseContext === 'function') onUseContext(payload);
      }
    }));
    const shownEntries = activeVisibleEntries();
    if (!shownEntries.length) {
      container.appendChild(emptyBlock('No matching evidence', 'Change the ledger filter to inspect other recorded evidence results.'));
      return;
    }
    const list = document.createElement('div');
    list.className = 'evidence-ledger-list';
    shownEntries.forEach((entry) => {
      list.appendChild(ledgerCard(entry, {
        active: entry.key === activeKey,
        onSelect: select,
        onAskFollowUp
      }));
    });
    container.appendChild(list);
  }

  function renderDetail() {
    if (!detailContainer) return;
    detailContainer.innerHTML = '';
    const scopedEntries = visibleEntries();
    if (!scopedEntries.length) {
      return;
    }
    const shownEntries = activeVisibleEntries();
    const entry = shownEntries.find((item) => item.key === activeKey) || shownEntries[0] || scopedEntries[0];
    detailContainer.appendChild(ledgerDetailPanel(entry, { onUseContext, onAskContext, onAskNewContext, onDraftContext, onAskFollowUp }));
  }

  reset();
  function count() {
    return visibleEntries().length;
  }

  return { reset, upsert, select, count, setScope };

  function visibleEntries() {
    return entries.filter((entry) => entryMatchesScope(entry, scope));
  }

  function activeVisibleEntries() {
    return filterLedgerEntries(visibleEntries(), filter);
  }
}

export function ledgerEntryModel(record) {
  if (!record || (!record.call && !record.result)) return null;
  const operation = (record.call && record.call.name) || (record.result && record.result.name) || 'tool';
  const payload = extractPresentedPayload(record);
  const storedLedger = ledgerObject((record.result && record.result.ledger) || (record.call && record.call.ledger));
  const result = record.result || {};
  const presentation = toolResultPresentation(record, {
    operation,
    payload,
    displayOnly: Boolean(storedLedger.display_only || result.persisted_display_only || (record.call && record.call.persisted_display_only))
  });
  const normalized = presentation.normalized;
  const status = storedLedger.status || (result.isError ? 'error' : record.result ? (normalized && normalized.status) || 'completed' : 'running');
  return {
    key: ledgerKey(record, operation),
    operation,
    title: toolNameLabel(operation),
    status: promptSafeText(status),
    summary: promptSafeText(storedLedger.headline || storedLedger.summary || (record.result ? toolResultSummary(record.result) : compactLine(formatShort(record.call && record.call.input), 160))),
    findingState: promptSafeText(storedLedger.finding_state || (normalized && normalized.envelope && normalized.envelope.finding_state)),
    answerReadiness: promptSafeText(storedLedger.answer_readiness || (normalized && normalized.envelope && normalized.envelope.answer_readiness)),
    displayOnly: Boolean(storedLedger.display_only || result.persisted_display_only || (record.call && record.call.persisted_display_only)),
    presentationState: presentation.presentationState,
    payload,
    record,
    scope: record.scope || {}
  };
}

export function ledgerDetailModel(entryOrRecord) {
  const entry = entryOrRecord && entryOrRecord.record ? entryOrRecord : ledgerEntryModel(entryOrRecord);
  if (!entry) return null;
  const presentation = ledgerEntryPresentation(entry);
  return {
    key: entry.key,
    operation: entry.operation,
    title: entry.title,
    status: entry.status,
    summary: entry.summary,
    findingState: entry.findingState,
    answerReadiness: entry.answerReadiness,
    displayOnly: entry.displayOnly,
    presentationState: presentation.presentationState,
    reuseKind: presentation.kind,
    hasCanonicalEnvelope: presentation.hasCanonicalEnvelope,
    canRenderResult: presentation.canRenderResult,
    canRenderEvidence: presentation.canRenderEvidence,
    canAttach: presentation.canAttach
  };
}

export function ledgerContextPayload(entryOrRecord, selectedRoot) {
  const entry = entryOrRecord && entryOrRecord.record ? entryOrRecord : ledgerEntryModel(entryOrRecord);
  if (!entry) return null;
  return toolResultContextPayload(entry.record, selectedRoot, {
    operation: entry.operation,
    payload: entry.payload,
    displayOnly: entry.displayOnly,
    title: entry.title,
    summary: entry.summary,
    selectedPromptIntro: 'Selected evidence: ' + entry.title
  });
}

export function filterLedgerEntries(entries, filter = 'all') {
  const shown = Array.isArray(entries) ? entries : [];
  if (filter === 'reusable') return shown.filter((entry) => reusableEntry(entry));
  if (filter === 'running') return shown.filter((entry) => String(entry.status || '').toLowerCase() === 'running');
  if (filter === 'errors') return shown.filter((entry) => {
    const status = String(entry.status || '').toLowerCase();
    return status === 'error' || status.includes('fail');
  });
  return shown;
}

export function ledgerSummaryPayload(entries) {
  const reusable = (Array.isArray(entries) ? entries : [])
    .filter((entry) => ledgerEntryPresentation(entry).includeInSummary)
    .slice(0, 8);
  if (!reusable.length) return null;
  return buildSelectedEvidencePayload({
    contextKind: 'evidence_ledger',
    label: 'Current evidence summary',
    summary: reusable.length + ' reusable current evidence result' + (reusable.length === 1 ? '' : 's'),
    sourceOperation: 'genomi.portal.evidence_ledger',
    selectedNodes: reusable.map((entry) => ({
      label: entry.title,
      text: ledgerSummaryLine(entry),
      value: entry.summary
    })),
    promptIntro: 'Selected current evidence summary:'
  });
}

function ledgerCard(entry, options) {
  const card = document.createElement('div');
  card.className = 'evidence-ledger-item ' + entry.status + (options.active ? ' active' : '');
  card.tabIndex = 0;
  card.setAttribute('role', 'button');
  card.setAttribute('aria-pressed', options.active ? 'true' : 'false');
  card.innerHTML = [
    '<div class="evidence-ledger-item-head">',
    '<div><span></span><strong></strong></div>',
    '<em></em>',
    '</div>',
    '<p></p>',
    '<div class="evidence-ledger-badges"></div>',
    '<div class="evidence-ledger-actions"></div>'
  ].join('');
  card.querySelector('.evidence-ledger-item-head span').textContent = humanizeState(entry.status);
  card.querySelector('.evidence-ledger-item-head strong').textContent = entry.title;
  card.querySelector('em').textContent = entry.displayOnly ? 'Saved evidence' : 'Evidence result';
  card.querySelector('p').textContent = entry.summary || 'Work step recorded';
  const badges = card.querySelector('.evidence-ledger-badges');
  [entry.answerReadiness, entry.findingState].filter(Boolean).forEach((badge) => {
    const item = document.createElement('span');
    item.textContent = humanizeState(badge);
    badges.appendChild(item);
  });
  const actions = card.querySelector('.evidence-ledger-actions');
  const inspect = document.createElement('button');
  inspect.type = 'button';
  inspect.className = 'tool-action';
  inspect.textContent = options.active ? 'Inspecting' : 'Inspect';
  inspect.addEventListener('click', (event) => {
    event.stopPropagation();
    if (typeof options.onSelect === 'function') options.onSelect(entry.key);
  });
  const follow = document.createElement('button');
  follow.type = 'button';
  follow.className = 'tool-action';
  follow.textContent = entry.displayOnly ? 'Re-check evidence' : 'Ask follow-up';
  follow.addEventListener('click', (event) => {
    event.stopPropagation();
    if (typeof options.onAskFollowUp === 'function') options.onAskFollowUp(ledgerFollowUpRequest(entry));
  });
  actions.appendChild(inspect);
  actions.appendChild(follow);
  card.addEventListener('click', () => {
    if (typeof options.onSelect === 'function') options.onSelect(entry.key);
  });
  card.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    if (typeof options.onSelect === 'function') options.onSelect(entry.key);
  });
  return card;
}

function ledgerToolbar(entries, activeFilter, options) {
  const toolbar = document.createElement('div');
  toolbar.className = 'evidence-ledger-toolbar';
  toolbar.innerHTML = '<div class="evidence-ledger-scope"><strong></strong><span></span></div><div class="evidence-ledger-filters"></div><div class="evidence-ledger-toolbar-actions"></div>';
  const scopeNode = toolbar.querySelector('.evidence-ledger-scope');
  if (scopeNode) {
    const label = (options.scope && options.scope.label) || 'this conversation';
    scopeNode.querySelector('strong').textContent = 'Current evidence from ' + label;
    scopeNode.querySelector('span').textContent = evidenceScopeSummary(entries);
  }
  const filters = toolbar.querySelector('.evidence-ledger-filters');
  ledgerFilterItems(entries).forEach((item) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tool-action' + (item.key === activeFilter ? ' active' : '');
    button.textContent = item.label + ' ' + item.count;
    button.addEventListener('click', () => {
      if (typeof options.onFilter === 'function') options.onFilter(item.key);
    });
    filters.appendChild(button);
  });
  const actions = toolbar.querySelector('.evidence-ledger-toolbar-actions');
  const summary = actionButton('Attach current evidence', () => {
    if (typeof options.onUseSummary === 'function') options.onUseSummary();
  });
  summary.disabled = !(Array.isArray(entries) ? entries : []).some((entry) => ledgerEntryPresentation(entry).includeInSummary);
  actions.appendChild(summary);
  return toolbar;
}

function ledgerFilterItems(entries) {
  const all = Array.isArray(entries) ? entries : [];
  return [
    { key: 'all', label: 'All', count: all.length },
    { key: 'reusable', label: 'Current evidence', count: filterLedgerEntries(all, 'reusable').length },
    { key: 'running', label: 'Running', count: filterLedgerEntries(all, 'running').length },
    { key: 'errors', label: 'Errors', count: filterLedgerEntries(all, 'errors').length }
  ];
}

function evidenceScopeSummary(entries) {
  const all = Array.isArray(entries) ? entries : [];
  const count = all.length;
  const restored = all.filter((entry) => entry && entry.scope && entry.scope.messageId).length;
  const live = count - restored;
  const parts = [
    count + ' evidence result' + (count === 1 ? '' : 's'),
    restored ? restored + ' restored from saved work history' : '',
    live ? live + ' live in this session' : ''
  ].filter(Boolean);
  return parts.join(' · ');
}

function ledgerDetailPanel(entry, options) {
  const model = ledgerDetailModel(entry);
  const panel = document.createElement('div');
  panel.className = 'evidence-ledger-detail-panel';
  panel.innerHTML = [
    '<div class="evidence-ledger-detail-head">',
    '<div><span></span><strong></strong><p></p></div>',
    '<div class="evidence-ledger-badges"></div>',
    '</div>',
    '<div class="evidence-ledger-detail-body"></div>',
    '<div class="evidence-ledger-actions"></div>'
  ].join('');
  panel.querySelector('.evidence-ledger-detail-head span').textContent = model.displayOnly ? 'Saved evidence' : 'Evidence result';
  panel.querySelector('.evidence-ledger-detail-head strong').textContent = model.title;
  panel.querySelector('.evidence-ledger-detail-head p').textContent = model.summary || 'Work step recorded';
  const badges = panel.querySelector('.evidence-ledger-badges');
  [model.status, model.answerReadiness, model.findingState].filter(Boolean).forEach((badge) => {
    const item = document.createElement('span');
    item.textContent = humanizeState(badge);
    badges.appendChild(item);
  });
  const body = panel.querySelector('.evidence-ledger-detail-body');
  if (model.presentationState === 'persisted_redacted' && model.canRenderResult) {
    body.appendChild(detailNote(
      'Persisted redacted history',
      'This saved transcript entry can show persisted public lanes only. Re-check current Genomi tools before making evidence claims.'
    ));
    const panels = renderToolResultPrimaryPanels(entry.record, {
      ...options,
      operation: entry.operation,
      payload: entry.payload,
      displayOnly: entry.displayOnly,
      presentationState: model.presentationState,
      title: entry.title,
      summary: entry.summary,
      actions: false
    });
    panels.forEach((section) => {
      body.appendChild(section.node);
    });
  } else if (model.displayOnly) {
    body.appendChild(detailNote(
      'Display-only stored summary',
      'This saved transcript entry keeps only a compact summary. Re-check current Genomi tools before making evidence claims.'
    ));
  } else if (model.canRenderResult || model.canRenderEvidence) {
    const panels = renderToolResultPrimaryPanels(entry.record, {
      ...options,
      operation: entry.operation,
      payload: entry.payload,
      displayOnly: entry.displayOnly,
      title: entry.title,
      summary: entry.summary,
      actions: false
    });
    panels.forEach((section) => {
      body.appendChild(section.node);
    });
  } else {
    body.appendChild(detailNote(
      'No evidence view available',
      'This event is tracked for workflow continuity, but it is not an answer-shaped Genomi evidence result.'
    ));
  }
  const actions = panel.querySelector('.evidence-ledger-actions');
  if (model.canAttach) {
    body.insertAdjacentHTML('beforeend', ledgerSelectionControlsMarkup());
    const selectedPayload = () => ledgerContextPayload(entry, panel);
    installLedgerSelectionControls(panel, {
      onUseSelection: () => {
        const payload = selectedPayload();
        if (payload && typeof options.onUseContext === 'function') options.onUseContext(payload);
      },
      onAskSelection: () => {
        const payload = selectedPayload();
        if (payload && typeof options.onAskContext === 'function') options.onAskContext(payload);
      },
      onDraftSelection: () => {
        const payload = selectedPayload();
        if (payload && typeof options.onDraftContext === 'function') options.onDraftContext(payload);
      }
    });
  }
  actions.appendChild(actionButton(model.displayOnly ? 'Re-check evidence' : 'Ask follow-up', () => {
    if (typeof options.onAskFollowUp === 'function') options.onAskFollowUp(ledgerFollowUpRequest(entry));
  }));
  return panel;
}

export function ledgerFollowUpRequest(entryOrRecord) {
  const entry = entryOrRecord && entryOrRecord.record ? entryOrRecord : ledgerEntryModel(entryOrRecord);
  if (!entry) return { prompt: '' };
  return toolResultFollowUpRequest(entry.record, {
    operation: entry.operation,
    payload: entry.payload,
    displayOnly: entry.displayOnly,
    presentationState: entry.presentationState,
    title: entry.title,
    summary: entry.summary
  });
}

export function ledgerFollowUpPrompt(entryOrRecord) {
  const request = ledgerFollowUpRequest(entryOrRecord);
  return request.context && request.context.prompt_text ? request.context.prompt_text : '';
}

function detailNote(title, text) {
  const note = document.createElement('div');
  note.className = 'evidence-ledger-detail-note';
  note.innerHTML = '<strong></strong><span></span>';
  note.querySelector('strong').textContent = title;
  note.querySelector('span').textContent = text;
  return note;
}

function actionButton(label, handler) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'tool-action';
  button.textContent = label;
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    handler();
  });
  return button;
}

function emptyBlock(title, text) {
  const empty = document.createElement('div');
  empty.className = 'evidence-ledger-empty';
  empty.innerHTML = '<strong></strong><span></span>';
  empty.querySelector('strong').textContent = title;
  empty.querySelector('span').textContent = text;
  return empty;
}

function ledgerKey(record, operation) {
  const scope = record.scope || {};
  const id = (record.call && record.call.id) || (record.result && record.result.id);
  const frameId = scope.frameId || 'frame';
  const runScope = scope.runId || (scope.messageId ? 'message:' + scope.messageId : 'run');
  const toolId = id || (record.result ? 'result' : 'call') + ':' + entrySummaryKey(record);
  return [operation, frameId, runScope, toolId].join(':');
}

function reusableEntry(entry) {
  return entryBelongsInEvidenceLedger(entry) && ledgerEntryPresentation(entry).canAttach;
}

function entryBelongsInEvidenceLedger(entry) {
  const presentation = ledgerEntryPresentation(entry);
  if (!presentation) return false;
  if (presentation.kind === 'session_context' || presentation.kind === 'result_view' || presentation.kind === 'workflow_event') return false;
  return Boolean(presentation.kind === 'evidence' || presentation.kind === 'persisted_redacted' || presentation.hasCanonicalEnvelope);
}

function ledgerEntryPresentation(entry) {
  return toolResultPresentation(entry && entry.record, {
    operation: entry && entry.operation,
    payload: entry && entry.payload,
    displayOnly: entry && entry.displayOnly,
    presentationState: entry && entry.presentationState,
    title: entry && entry.title,
    summary: entry && entry.summary
  });
}

function ledgerSummaryLine(entry) {
  const parts = [
    'Current evidence / ' + entry.title,
    entry.status ? 'status: ' + humanizeState(entry.status) : '',
    entry.answerReadiness ? 'readiness: ' + humanizeState(entry.answerReadiness) : '',
    entry.findingState ? 'finding: ' + humanizeState(entry.findingState) : '',
    entry.summary ? 'summary: ' + readableEvidenceSummary(entry) : ''
  ].filter(Boolean);
  return promptSafeText(parts.join(' / '));
}

function readableEvidenceSummary(entry) {
  const summary = promptSafeText(entry && entry.summary ? entry.summary : '');
  const operation = promptSafeText(entry && entry.operation ? entry.operation : '');
  const title = promptSafeText(entry && entry.title ? entry.title : '');
  if (!summary || !operation || !title || operation === title) return summary;
  return summary.split(operation).join(title);
}

function entrySummaryKey(record) {
  const text = record.result ? toolResultSummary(record.result) : formatShort(record.call && record.call.input);
  return compactLine(text, 80);
}

function ledgerObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function ledgerScopeModel(value = {}) {
  const frameId = promptSafeText(value.frameId || value.frame_id || '').trim();
  const label = promptSafeText(value.label || value.title || '').trim();
  return {
    frameId,
    label: label || (frameId ? 'the current conversation' : 'this conversation')
  };
}

function recordMatchesScope(record, scope) {
  const recordFrameId = promptSafeText(record && record.scope && record.scope.frameId || '').trim();
  if (!scope.frameId) return true;
  return Boolean(recordFrameId && recordFrameId === scope.frameId);
}

function entryMatchesScope(entry, scope) {
  return recordMatchesScope(entry && entry.record, scope);
}
