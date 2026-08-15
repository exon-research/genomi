import { renderToolDetails, toolInputSummary, toolNameLabel, toolResultSummary } from './portal_evidence.js';
import { frameTraceMessagesFromToolRecord, frameTraceSummaryPayload } from './portal_frame_trace.js';
import { formatPayload } from './portal_format.js';
import { sourceOperation } from './portal_tool_result_presentation.js';
import { promptSafeText, selectedEvidencePayload as buildSelectedEvidencePayload } from './portal_selected_evidence.js';
import { artifactsForRun, renderInlineArtifactStrip } from './portal_artifacts.js';
import { welcomeMessageMarkup } from './portal_starter_cards.js';
import { isSpecialistToolName, renderSpecialistLane } from './portal_specialists.js';
import { markdownContentElement } from './portal_workspace_file_previews.js';

export function toolWorkGroupSummary(statuses = []) {
  const values = (Array.isArray(statuses) ? statuses : [])
    .map((status) => String(status || '').trim())
    .filter(Boolean);
  const total = values.length;
  const running = values.filter((status) => status === 'running').length;
  const errors = values.filter((status) => status === 'error').length;
  const done = values.filter((status) => status === 'done' || status === 'completed').length;
  const status = errors ? 'error' : running ? 'running' : total ? 'done' : 'running';
  return {
    total,
    running,
    errors,
    done,
    status,
    title: total + ' work step' + (total === 1 ? '' : 's'),
    summary: [
      done ? done + ' done' : '',
      running ? running + ' running' : '',
      errors ? errors + ' error' + (errors === 1 ? '' : 's') : ''
    ].filter(Boolean).join(' · ') || 'Waiting for assistant work'
  };
}

export function toolWorkGroupContextPayload(records = []) {
  const items = Array.isArray(records) ? records : [];
  const messages = items
    .filter((record) => !isDiagnosticRecord(record))
    .flatMap((record) => frameTraceMessagesFromToolRecord(record));
  const payload = frameTraceSummaryPayload(messages);
  const diagnosticNodes = diagnosticContextNodes(items);
  if (!payload && !diagnosticNodes.length) return null;
  if (!diagnosticNodes.length) {
    return {
      ...payload,
      label: 'Message work trail',
      source_operation: 'genomi.portal.message_work_trace'
    };
  }
  const nodes = [
    ...(payload && Array.isArray(payload.selected_nodes) ? payload.selected_nodes : []),
    ...diagnosticNodes
  ].slice(-8);
  const diagnosticSummary = diagnosticNodes.length + ' assistant status note' + (diagnosticNodes.length === 1 ? '' : 's');
  const summary = [payload && payload.summary, diagnosticSummary].filter(Boolean).join(' · ');
  return buildSelectedEvidencePayload({
    contextKind: 'work_trace',
    label: 'Message work trail',
    summary,
    sourceOperation: 'genomi.portal.message_work_trace',
    fallbackNodes: nodes,
    promptIntro: 'Selected conversation work trail:'
  });
}

function isDiagnosticRecord(record) {
  return Boolean(record && (record.kind === 'diagnostic' || record.diagnostic));
}

function diagnosticContextNodes(records = []) {
  return (Array.isArray(records) ? records : [])
    .filter(isDiagnosticRecord)
    .map((record, index) => {
      const diagnostic = diagnosticRecordModel(record.diagnostic && record.diagnostic.events || record.diagnostics || []);
      return {
        label: String(index + 1) + '. Assistant status notes',
        text: diagnosticContextText(diagnostic),
        value: diagnosticContextText(diagnostic)
      };
    });
}

function diagnosticContextText(diagnostic) {
  const lines = [
    'Work trail / Assistant status notes / status: completed / summary: ' + diagnostic.summary,
    ...diagnostic.events.map((event, index) => {
      const label = diagnosticEventLabel(event, index);
      const summary = diagnosticEventSummary(event);
      return 'Status update ' + String(index + 1) + ' / ' + label + (summary ? ' / ' + summary : '');
    })
  ];
  return promptSafeText(lines.filter(Boolean).join('\n'));
}

function diagnosticRecordModel(events) {
  const items = (Array.isArray(events) ? events : []).map(sanitizeDiagnosticEvent);
  const count = items.length;
  return {
    title: 'Assistant status notes',
    status: 'done',
    summary: count
      ? count + ' status update' + (count === 1 ? '' : 's') + ' recorded'
      : 'Status updates recorded',
    events: items
  };
}

export function createMessageSurface({ list, onUseContext, onAskContext, onAskNewContext, onDraftContext, onAskFollowUp, onToolRecord, onApprovePermission }) {
  let lastToolParent = null;
  let toolCards = new Map();
  let assistantMessagesByRunId = new Map();
  let toolStacksByRunId = new Map();
  let pendingStoredToolMessagesByRunId = new Map();
  let permissionRecordsByRunId = new Map();

  function reset() {
    list.innerHTML = welcomeMessageMarkup();
    lastToolParent = null;
    toolCards = new Map();
    assistantMessagesByRunId = new Map();
    toolStacksByRunId = new Map();
    pendingStoredToolMessagesByRunId = new Map();
    permissionRecordsByRunId = new Map();
    if (typeof onToolRecord === 'function') onToolRecord(null);
  }

  function addMessage(role, text, selectedEvidence, bridge = {}) {
    if (list.querySelector('[data-testid="genomi-chat-welcome"]')) list.innerHTML = '';
    const el = document.createElement('div');
    el.className = 'message ' + role;
    el.innerHTML = '<div class="role"></div><div class="body"></div>';
    el.querySelector('.role').textContent = role === 'user' ? 'You' : 'Genomi';
    const body = el.querySelector('.body');
    const messageId = promptSafeText(bridge.messageId || '').trim();
    if (messageId) el.dataset.messageId = messageId;
    const evidence = Array.isArray(selectedEvidence) ? selectedEvidence : [];
    const rawText = promptSafeText(text || '');
    const presentationKind = messagePresentationKind(bridge.presentationKind, evidence);
    const visibleText = visibleMessageText(role, rawText, evidence, presentationKind);
    if (role === 'assistant') {
      body.dataset.rawText = rawText;
      if (presentationKind) body.dataset.presentationKind = presentationKind;
      renderAssistantBody(body, visibleText);
    } else {
      body.textContent = visibleText;
    }
    if (shouldShowSelectedEvidenceRefs(role, evidence, presentationKind)) body.appendChild(selectedEvidenceRefs(evidence));
    list.appendChild(el);
    scrollBottom();
    lastToolParent = role === 'assistant' ? el : null;
    return body;
  }

  function visibleMessageText(role, text, selectedEvidence = [], presentationKind = '') {
    const clean = promptSafeText(text || '').trim();
    if (role === 'user' && presentationKind === 'genome_context_control') {
      return selectedGenomeContextTurnLabel(selectedEvidence);
    }
    if (role === 'user' && presentationKind === 'selected_material_control') {
      return 'Use the included evidence.';
    }
    if (role === 'assistant' && presentationKind === 'genome_context_acknowledgement') {
      return 'Ask a genetics question when you want to use the approved active genome.';
    }
    return clean;
  }

  function shouldShowSelectedEvidenceRefs(role, selectedEvidence = [], presentationKind = '') {
    if (!Array.isArray(selectedEvidence) || !selectedEvidence.length) return false;
    if (role === 'user' && presentationKind === 'genome_context_control') return false;
    return true;
  }

  function messagePresentationKind(explicitKind, selectedEvidence = []) {
    const direct = cleanMessagePresentationKind(explicitKind);
    if (direct) return direct;
    if (!Array.isArray(selectedEvidence)) return '';
    for (const item of selectedEvidence) {
      const kind = cleanMessagePresentationKind(item && item.message_presentation_kind);
      if (kind) return kind;
    }
    return '';
  }

  function cleanMessagePresentationKind(value) {
    const kind = String(value || '').trim().toLowerCase();
    return [
      'genome_context_acknowledgement',
      'genome_context_control',
      'selected_material_control'
    ].includes(kind) ? kind : '';
  }

  function selectedGenomeContextTurnLabel(selectedEvidence = []) {
    const first = selectedEvidence.find((item) => item && item.context_kind === 'genome_context') || {};
    const label = promptSafeText(first.label || '').replace(/^(Genome state|Active genome):\s*/i, '').trim();
    const friendlyLabel = friendlyGenomeContextLabel(first, label);
    return friendlyLabel
      ? 'Active genome selected: ' + friendlyLabel + '.'
      : 'Active genome selected for this conversation.';
  }

  function friendlyGenomeContextLabel(item, label) {
    const cleanLabel = promptSafeText(label || '').trim();
    if (cleanLabel && !isGenericGenomeContextLabel(cleanLabel)) return cleanLabel;
    const nodes = Array.isArray(item && item.selected_nodes)
      ? item.selected_nodes
      : (Array.isArray(item && item.selectedNodes) ? item.selectedNodes : []);
    const name = genomeContextNodeValue(nodes, 'current genome / name');
    const build = genomeContextNodeValue(nodes, 'current genome / build');
    const source = genomeContextNodeValue(nodes, 'current genome / source');
    const parts = [name, build, source].filter(Boolean);
    if (parts.length) {
      const text = parts.join(' · ');
      return /genome$/i.test(text) ? text : text + ' genome';
    }
    return cleanLabel && !/^genome ready$/i.test(cleanLabel) ? cleanLabel : '';
  }

  function genomeContextNodeValue(nodes, label) {
    const target = String(label || '').toLowerCase();
    const node = nodes.find((item) => {
      const nodeLabel = promptSafeText(item && item.label || '').toLowerCase();
      return nodeLabel === target || nodeLabel.endsWith('/ ' + target.split('/ ').pop());
    });
    return promptSafeText(node && (node.value || node.summary || '')).trim();
  }

  function isGenericGenomeContextLabel(label) {
    return /^(genome ready|ready genome|active genome|genome state|genome)$/i.test(promptSafeText(label || '').trim());
  }

  function renderStoredMessages(messages) {
    pendingStoredToolMessagesByRunId = new Map();
    const plan = storedMessageReplayPlan(messages);
    if (plan.items.length) list.innerHTML = '';
    let pendingAssistantPresentationKind = '';
    plan.items.forEach((item) => {
      const message = item.message || {};
      if (message.role === 'user') {
        const userKind = messagePresentationKind(
          message.presentation_kind || message.message_presentation_kind,
          message.selected_evidence || []
        );
        pendingAssistantPresentationKind = userKind === 'genome_context_control'
          ? 'genome_context_acknowledgement'
          : '';
      }
      renderStoredMessage(message, {
        expectedAssistantRunId: item.assistantRunId,
        presentationKind: message.role === 'assistant' ? pendingAssistantPresentationKind : ''
      });
      if (message.role === 'assistant') pendingAssistantPresentationKind = '';
    });
    flushPendingStoredToolMessages();
  }

  function renderStoredMessage(message, replay = {}) {
    if (message.role === 'tool' && message.event) {
      const runId = cleanRunId(message.run_id);
      const parent = runId ? assistantMessagesByRunId.get(runId) : null;
      if (!parent && replay.expectedAssistantRunId) {
        bufferStoredToolMessage(replay.expectedAssistantRunId, message);
        return;
      }
      addToolEvent(message.event.type || 'tool_event', message.event, parent || lastToolParent, {
        frameId: message.frame_id,
        runId: message.run_id,
        messageId: message.id
      });
      return;
    }
    const body = addMessage(
      message.role === 'user' ? 'user' : 'assistant',
      message.text || '',
      message.selected_evidence || [],
      {
        presentationKind: message.presentation_kind
          || message.message_presentation_kind
          || replay.presentationKind,
        messageId: message.id
      }
    );
    if (message.role === 'assistant') {
      registerAssistantRun(body, message.run_id);
    }
  }

  function registerAssistantRun(body, runId) {
    const clean = cleanRunId(runId);
    const parent = body && typeof body.closest === 'function' ? body.closest('.message') : null;
    if (!clean || !parent) return;
    parent.dataset.runId = clean;
    if (!(body.dataset.rawText || '').trim()) parent.classList.add('streaming');
    assistantMessagesByRunId.set(clean, parent);
    flushPendingStoredToolMessages(clean, parent);
  }

  function focusRun(runId) {
    clearRunFocus();
    const clean = cleanRunId(runId);
    if (!clean) return false;
    const parent = assistantMessagesByRunId.get(clean);
    if (parent) {
      parent.classList.add('run-highlight');
      parent.setAttribute('data-testid', 'genomi-message-run-highlight');
      parent.dataset.highlightedRun = clean;
      const stack = parent.querySelector('.tool-stack');
      if (stack) {
        stack.classList.add('run-highlight');
        stack.dataset.highlightedRun = clean;
      }
      scrollFocusedNode(parent);
      return true;
    }
    const stack = firstToolStackForRun(clean);
    if (!stack) return false;
    stack.classList.add('run-highlight');
    stack.dataset.highlightedRun = clean;
    scrollFocusedNode(stack);
    return true;
  }

  function focusMessage(messageId) {
    const clean = promptSafeText(messageId || '').trim();
    if (!clean) return false;
    const message = [...list.querySelectorAll('[data-message-id]')]
      .find((item) => item.dataset.messageId === clean);
    if (!message) return false;
    clearRunFocus();
    message.classList.add('run-highlight');
    message.setAttribute('data-testid', 'genomi-message-review-highlight');
    if (message.classList.contains('tool-chip')) {
      message.classList.add('open');
      const chevron = message.querySelector('.tool-chevron');
      if (chevron) chevron.textContent = 'v';
      const stack = message.closest('.tool-stack');
      if (stack) setToolStackCollapsed(stack, false);
    }
    scrollFocusedNode(message);
    return true;
  }

  function firstToolStackForRun(runId) {
    const stacks = toolStacksByRunId.get(runId) || [];
    if (!stacks.length) return null;
    return Array.from(list.querySelectorAll('.tool-stack')).find((stack) => stacks.includes(stack)) || null;
  }

  function scrollFocusedNode(node) {
    if (node && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }

  function clearRunFocus() {
    list.querySelectorAll('.run-highlight').forEach((node) => {
      node.classList.remove('run-highlight');
      if (node.dataset) delete node.dataset.highlightedRun;
      if (node.getAttribute && ['genomi-message-run-highlight', 'genomi-message-review-highlight'].includes(node.getAttribute('data-testid'))) {
        node.removeAttribute('data-testid');
      }
    });
  }

  function renderInlineArtifacts(artifacts, options = {}) {
    for (const [runId, parent] of assistantMessagesByRunId.entries()) {
      removeInlineArtifacts(parent);
      const matched = artifactsForRun(artifacts, options.frameId, runId);
      if (!matched.length) continue;
      const container = document.createElement('div');
      container.className = 'message-inline-artifacts artifact-strip';
      container.setAttribute('data-testid', 'message-artifact-strip');
      parent.appendChild(container);
      renderInlineArtifactStrip(container, matched, options);
    }
    scrollBottom();
  }

  function addToolEvent(kind, data, parentMessage, scope = {}) {
    const permissionRunId = promptSafeText(scope.runId || '').trim();
    const permission = data && data.permission_request;
    if (permissionRunId && permission && permissionRecordsByRunId.has(permissionRunId)) {
      return permissionRecordsByRunId.get(permissionRunId);
    }
    const stack = ensureToolStack(parentMessage || lastToolParent);
    const hasPendingPermission = Boolean(stack.querySelector('.permission-request'));
    setToolStackCollapsed(stack, kind === 'diagnostic' && !hasPendingPermission);
    const key = kind === 'diagnostic' ? diagnosticRecordKey(scope) : toolRecordKey(data, scope);
    let record = toolCards.get(key);
    if (!record) {
      const el = document.createElement('div');
      el.className = kind === 'diagnostic' ? 'tool-chip tool-chip-diagnostic' : 'tool-chip';
      el.setAttribute('data-testid', 'tool-chip');
      if (scope.messageId) el.dataset.messageId = promptSafeText(scope.messageId).trim();
      el.innerHTML = '<button class="tool-chip-head" type="button"><span class="tool-status"></span><span class="tool-title"></span><span class="tool-summary"></span><span class="tool-chevron">&gt;</span></button><div class="tool-details"></div>';
      el.querySelector('.tool-chip-head').addEventListener('click', () => {
        el.classList.toggle('open');
        el.querySelector('.tool-chevron').textContent = el.classList.contains('open') ? 'v' : '>';
      });
      toolStackItems(stack).appendChild(el);
      record = {
        kind: kind === 'diagnostic' ? 'diagnostic' : 'tool',
        el,
        stack,
        call: null,
        result: null,
        scope: { ...scope },
        diagnostics: [],
        diagnostic: kind === 'diagnostic' ? diagnosticRecordModel([]) : null
      };
      toolCards.set(key, record);
    } else if (!record.stack) {
      record.stack = stack;
    }
    record.scope = { ...record.scope, ...scope };
    if (scope.messageId) record.el.dataset.messageId = promptSafeText(scope.messageId).trim();
    registerToolStackRun(record.stack, record.scope.runId);
    if (kind === 'diagnostic') {
      record.kind = 'diagnostic';
      record.diagnostics = [...(record.diagnostics || []), sanitizeDiagnosticEvent(data)];
      record.diagnostic = diagnosticRecordModel(record.diagnostics);
    } else if (kind === 'tool_result') {
      record.kind = 'tool';
      record.result = data;
    } else if (kind === 'error') {
      record.kind = 'tool';
      record.result = {
        id: data.id,
        name: data.name || (record.call && record.call.name) || 'error',
        isError: true,
        content: data.message || JSON.stringify(data)
      };
      if (data.permission_request) record.result.permission_request = data.permission_request;
    } else {
      record.kind = 'tool';
      record.call = data;
    }
    updateToolCard(record);
    if (isPermissionRequestRecord(record)) {
      if (permissionRunId) permissionRecordsByRunId.set(permissionRunId, record);
      setToolStackCollapsed(record.stack, false);
      record.el.classList.add('open');
      record.el.querySelector('.tool-chevron').textContent = 'v';
    }
    if (typeof onToolRecord === 'function') onToolRecord(record);
    scrollBottom();
  }

  function appendText(body, text) {
    if (text) {
      body.closest('.message.assistant')?.classList.remove('streaming');
      if (body.closest('.message.assistant')) {
        body.dataset.rawText = (body.dataset.rawText || '') + text;
        renderAssistantBody(body, visibleMessageText(
          'assistant',
          body.dataset.rawText,
          [],
          body.dataset.presentationKind || ''
        ));
      } else {
        body.textContent += text;
      }
    }
    scrollBottom();
  }

  function scrollBottom() {
    list.scrollTop = list.scrollHeight;
  }

  function updateToolCard(record) {
    const model = toolCardModel(record);
    record.el.className = 'tool-chip'
      + (isDiagnosticRecord(record) ? ' tool-chip-diagnostic' : '')
      + (record.el.classList.contains('open') ? ' open' : '');
    record.el.hidden = Boolean(model.technical);
    record.technical = Boolean(model.technical);
    record.el.querySelector('.tool-status').className = 'tool-status ' + model.status;
    record.el.querySelector('.tool-title').textContent = model.title;
    record.el.querySelector('.tool-summary').textContent = model.summary;
    const details = record.el.querySelector('.tool-details');
    if (isDiagnosticRecord(record)) {
      renderDiagnosticDetails(details, record, { onAskFollowUp });
    } else if (isPermissionRequestRecord(record)) {
      renderPermissionRequestDetails(details, record, { onApprovePermission });
    } else {
      renderToolDetails(details, record, {
        onUseContext,
        onAskContext,
        onAskNewContext,
        onDraftContext,
        onAskFollowUp
      });
    }
    renderSpecialistLane(
      record.stack,
      Array.from(toolCards.values()).filter((item) => item.stack === record.stack)
    );
    updateToolStackSummary(record.stack);
  }

  function toolCardModel(record) {
    if (isDiagnosticRecord(record)) {
      const diagnostic = record.diagnostic || diagnosticRecordModel(record.diagnostics || []);
      return {
        title: diagnostic.title,
        status: diagnostic.status,
        summary: diagnostic.summary,
        technical: true
      };
    }
    if (isAllowedPermissionRecord(record)) {
      return {
        title: 'Access allowed',
        status: 'done',
        summary: permissionRequestSummary(record),
        technical: true
      };
    }
    const name = sourceOperation(record) || 'tool';
    const summary = record.result ? toolResultSummary(record.result) : toolInputSummary(record.call && record.call.input);
    const recoveredOperation = recoveredOperationFromSummary(summary);
    if (isSpecialistToolName(name)) {
      return {
        title: 'Specialist collaboration',
        status: record.result ? (record.result.isError ? 'error' : 'done') : 'running',
        summary,
        technical: true
      };
    }
    if (isPermissionRequestRecord(record)) {
      return {
        title: 'Permission needed',
        status: 'error',
        summary: permissionRequestSummary(record),
        technical: false
      };
    }
    return {
      title: recoveredOperation ? toolNameLabel(recoveredOperation) : toolNameLabel(name),
      status: record.result ? (record.result.isError ? 'error' : 'done') : 'running',
      summary,
      technical: isTechnicalToolRecord(record, name, summary, recoveredOperation)
    };
  }

  function recoveredOperationFromSummary(summary) {
    const match = String(summary || '').trim().match(/^([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+):\s+/);
    return match ? match[1] : '';
  }

  function isTechnicalToolRecord(record, name, summary, recoveredOperation) {
    if (isPermissionRequestRecord(record) || recoveredOperation) return false;
    const cleanName = promptSafeText(String(name || '')).trim().toLowerCase();
    if (cleanName.startsWith('mcp__')) return true;
    if (['bash', 'skill', 'toolsearch'].includes(cleanName)) return true;
    const text = promptSafeText(String(summary || '')).trim();
    if (!text) return false;
    if (text.includes('"type":"tool_reference"') || text.includes('"type": "tool_reference"')) return true;
    if (/^\[\s*\{\s*"tool_name"\s*:/.test(text)) return true;
    return false;
  }

  function isPermissionRequestRecord(record) {
    const request = record && record.result && record.result.permission_request;
    return Boolean(request && request.status !== 'allowed');
  }

  function isAllowedPermissionRecord(record) {
    const request = record && record.result && record.result.permission_request;
    return Boolean(request && request.status === 'allowed');
  }

  function permissionRequestSummary(record) {
    const request = permissionRequest(record);
    return permissionDisplayLabel(request) || 'Approve in browser to retry';
  }

  function renderPermissionRequestDetails(container, record, options = {}) {
    if (!container) return;
    const request = permissionRequest(record);
    container.innerHTML = '';
    const panel = document.createElement('div');
    panel.className = 'permission-request';
    panel.innerHTML = '<strong></strong><p></p>';
    panel.querySelector('strong').textContent = permissionDisplayLabel(request) || 'Assistant permission';
    panel.querySelector('p').textContent = 'The local assistant needs this access to continue. Allow it for this workspace or deny the request.';
    container.appendChild(panel);
    const actions = document.createElement('div');
    actions.className = 'tool-actions permission-actions';
    actions.innerHTML = '<button class="tool-action primary-action" data-testid="genomi-permission-approve" type="button">Allow for this workspace</button><button class="tool-action" type="button">Deny</button><button class="tool-action" type="button">Copy technical details</button>';
    const approve = actions.children[0];
    const deny = actions.children[1];
    approve.disabled = typeof options.onApprovePermission !== 'function';
    approve.addEventListener('click', (event) => {
      event.stopPropagation();
      if (typeof options.onApprovePermission !== 'function') return;
      approve.disabled = true;
      approve.textContent = 'Approving...';
      Promise.resolve(options.onApprovePermission(record))
        .then(() => {
          approve.textContent = 'Allowed for this workspace';
          deny.hidden = true;
          panel.querySelector('p').textContent = 'Access allowed. The assistant is continuing the same request.';
        })
        .catch((error) => {
          approve.disabled = false;
          approve.textContent = 'Allow for this workspace';
          panel.querySelector('p').textContent = (error && error.message) || 'Permission approval failed.';
        });
    });
    deny.addEventListener('click', (event) => {
      event.stopPropagation();
      approve.disabled = true;
      deny.disabled = true;
      deny.textContent = 'Denied';
    });
    actions.children[2].addEventListener('click', (event) => {
      event.stopPropagation();
      if (navigator.clipboard) navigator.clipboard.writeText(formatPayload(record.result || {}));
    });
    container.appendChild(actions);
  }

  function permissionRequest(record) {
    const request = record && record.result && record.result.permission_request;
    return request && typeof request === 'object' && !Array.isArray(request) ? request : {};
  }

  function permissionDisplayLabel(request) {
    const rawLabel = request && typeof request.label === 'string' ? request.label : '';
    return promptSafeText(rawLabel).replace(/\s+/g, ' ').trim().slice(0, 160) || 'Assistant permission';
  }

  function renderDiagnosticDetails(container, record, options = {}) {
    if (!container) return;
    const diagnostic = record.diagnostic || diagnosticRecordModel(record.diagnostics || []);
    container.innerHTML = '';
    const overview = document.createElement('div');
    overview.className = 'tool-diagnostic-overview';
    overview.innerHTML = '<strong></strong><p></p>';
    overview.querySelector('strong').textContent = diagnostic.title;
    overview.querySelector('p').textContent = diagnostic.summary;
    container.appendChild(overview);
    container.appendChild(diagnosticTechnicalDetails(diagnostic));
    const actions = document.createElement('div');
    actions.className = 'tool-actions';
    actions.innerHTML = '<button class="tool-action" type="button">Copy technical details</button><button class="tool-action" type="button">Ask follow-up</button>';
    actions.children[0].addEventListener('click', (event) => {
      event.stopPropagation();
      if (navigator.clipboard) navigator.clipboard.writeText(diagnosticDetailsText(diagnostic));
    });
    actions.children[1].addEventListener('click', (event) => {
      event.stopPropagation();
      if (typeof options.onAskFollowUp === 'function') {
        options.onAskFollowUp(diagnosticFollowUpRequest(record, diagnostic));
      }
    });
    container.appendChild(actions);
  }

  function diagnosticTechnicalDetails(diagnostic) {
    const details = document.createElement('details');
    details.className = 'tool-technical-details tool-diagnostic-details';
    const summary = document.createElement('summary');
    summary.textContent = 'Technical status updates';
    details.appendChild(summary);
    const body = document.createElement('div');
    body.className = 'tool-technical-details-body';
    if (diagnostic.events.length) {
      diagnostic.events.forEach((event, index) => body.appendChild(diagnosticEventBlock(event, index)));
    } else {
      body.appendChild(diagnosticEventBlock({ message: 'Status updates recorded' }, 0));
    }
    details.appendChild(body);
    return details;
  }

  function diagnosticEventBlock(event, index) {
    const block = document.createElement('div');
    block.innerHTML = '<div class="tool-detail-label"></div><pre class="tool-detail-pre"></pre>';
    block.querySelector('.tool-detail-label').textContent = diagnosticEventLabel(event, index);
    block.querySelector('.tool-detail-pre').textContent = formatPayload(event);
    return block;
  }

  function diagnosticDetailsText(diagnostic) {
    if (!diagnostic.events.length) return diagnostic.summary;
    return diagnostic.events.map((event, index) => {
      return diagnosticEventLabel(event, index) + ':\n' + formatPayload(event);
    }).join('\n\n');
  }

  function diagnosticFollowUpRequest(record, diagnostic) {
    const context = buildSelectedEvidencePayload({
      contextKind: 'work_trace',
      label: diagnostic.title,
      summary: diagnostic.summary,
      sourceOperation: 'genomi.portal.message_work_trace',
      fallbackNodes: [{
        label: 'Assistant status notes',
        text: diagnosticContextText(diagnostic),
        value: diagnosticContextText(diagnostic)
      }],
      promptIntro: 'Selected assistant status trail:'
    });
    return {
      title: diagnostic.title,
      operation: 'genomi.portal.message_work_trace',
      displayOnly: true,
      presentationState: 'display_only',
      context,
      selectedEvidence: context ? [context] : [],
      scope: record.scope || {}
    };
  }

  function renderAssistantBody(body, text) {
    body.innerHTML = '';
    const answer = markdownContentElement(text || '', {
      className: 'message-answer-text',
      testId: 'genomi-assistant-answer'
    });
    body.appendChild(answer);
  }

  function ensureToolStack(parentMessage) {
    const parent = parentMessage || createLooseToolParent();
    let stack = parent.querySelector('.tool-stack');
    if (!stack) {
      stack = createToolStack();
      parent.appendChild(stack);
    }
    ensureToolStackStructure(stack);
    return stack;
  }

  function createLooseToolParent() {
    const el = document.createElement('div');
    el.className = 'message compact-tools';
    el.appendChild(createToolStack());
    list.appendChild(el);
    return el;
  }

  function createToolStack() {
    const stack = document.createElement('div');
    stack.className = 'tool-stack';
    stack.setAttribute('data-testid', 'tool-group');
    stack.innerHTML = [
      '<div class="tool-stack-head" data-testid="tool-group-header">',
      '<button class="tool-stack-toggle" type="button">',
      '<span class="tool-status"></span><span class="tool-stack-title"></span><span class="tool-stack-summary"></span><span class="tool-chevron">v</span>',
      '</button>',
      '</div>',
      '<div class="tool-stack-items"></div>'
    ].join('');
    stack.querySelector('.tool-stack-toggle').addEventListener('click', () => {
      stack.classList.toggle('collapsed');
      stack.querySelector('.tool-chevron').textContent = stack.classList.contains('collapsed') ? '>' : 'v';
    });
    updateToolStackSummary(stack);
    return stack;
  }

  function setToolStackCollapsed(stack, collapsed) {
    if (!stack || !stack.classList) return;
    stack.classList.toggle('collapsed', Boolean(collapsed));
    const chevron = stack.querySelector('.tool-stack-toggle .tool-chevron');
    if (chevron) chevron.textContent = collapsed ? '>' : 'v';
  }

  function registerToolStackRun(stack, runId) {
    const clean = cleanRunId(runId);
    if (!stack || !clean) return;
    const stacks = toolStacksByRunId.get(clean) || [];
    if (!stacks.includes(stack)) {
      stacks.push(stack);
      toolStacksByRunId.set(clean, stacks);
    }
  }

  function ensureToolStackStructure(stack) {
    if (!stack.querySelector('.tool-stack-head') || !stack.querySelector('.tool-stack-items')) {
      const chips = Array.from(stack.querySelectorAll('.tool-chip'));
      stack.innerHTML = '';
      const replacement = createToolStack();
      stack.appendChild(replacement.querySelector('.tool-stack-head'));
      stack.appendChild(replacement.querySelector('.tool-stack-items'));
      const items = toolStackItems(stack);
      chips.forEach((chip) => items.appendChild(chip));
    }
    updateToolStackSummary(stack);
  }

  function toolStackItems(stack) {
    let items = stack.querySelector('.tool-stack-items');
    if (!items) {
      items = document.createElement('div');
      items.className = 'tool-stack-items';
      stack.appendChild(items);
    }
    return items;
  }

  function updateToolStackSummary(stack) {
    if (!stack) return;
    const chips = Array.from(stack.querySelectorAll('.tool-chip')).filter((chip) => !chip.hidden);
    const allChips = Array.from(stack.querySelectorAll('.tool-chip'));
    const diagnosticOnly = chips.length > 0 && chips.every((chip) => chip.classList && chip.classList.contains('tool-chip-diagnostic'));
    const specialistLane = stack.querySelector('.specialist-lane');
    stack.hidden = !specialistLane && (!chips.length || diagnosticOnly || (allChips.length > 0 && !chips.length));
    const model = toolWorkGroupSummary(chips.map(toolChipStatus));
    const specialistOnly = Boolean(specialistLane && !chips.length);
    const statusNode = stack.querySelector('.tool-stack-head .tool-status');
    const head = stack.querySelector('.tool-stack-head');
    const toggle = stack.querySelector('.tool-stack-toggle');
    const title = stack.querySelector('.tool-stack-title');
    const summary = stack.querySelector('.tool-stack-summary');
    const titleText = specialistOnly ? 'Specialists' : model.title;
    const summaryText = specialistOnly ? (specialistLane.dataset.summary || 'Coordinating specialists') : model.summary;
    const statusText = specialistOnly ? (specialistLane.dataset.status === 'completed' ? 'done' : specialistLane.dataset.status) : model.status;
    if (statusNode) statusNode.className = 'tool-status ' + statusText;
    if (head) head.setAttribute('aria-label', titleText + ': ' + summaryText);
    if (toggle) toggle.setAttribute('aria-label', titleText + ': ' + summaryText);
    if (title) title.textContent = titleText;
    if (summary) summary.textContent = summaryText;
  }

  function toolStackContextPayload(stack) {
    const records = Array.from(toolCards.values()).filter((record) => record.stack === stack && !record.technical);
    return toolWorkGroupContextPayload(records);
  }

  function toolChipStatus(chip) {
    const status = chip && chip.querySelector('.tool-chip-head .tool-status');
    if (!status || !status.classList) return '';
    if (status.classList.contains('error')) return 'error';
    if (status.classList.contains('done')) return 'done';
    if (status.classList.contains('running')) return 'running';
    return '';
  }

  function removeInlineArtifacts(parent) {
    if (!parent || !parent.children) return;
    Array.from(parent.children)
      .filter((child) => child.classList && child.classList.contains('message-inline-artifacts'))
      .forEach((child) => child.remove());
  }

  function bufferStoredToolMessage(runId, message) {
    const pending = pendingStoredToolMessagesByRunId.get(runId) || [];
    pending.push(message);
    pendingStoredToolMessagesByRunId.set(runId, pending);
  }

  function flushPendingStoredToolMessages(runId, parent) {
    if (runId) {
      const pending = pendingStoredToolMessagesByRunId.get(runId) || [];
      pendingStoredToolMessagesByRunId.delete(runId);
      pending.forEach((message) => {
        addToolEvent(message.event.type || 'tool_event', message.event, parent, {
          frameId: message.frame_id,
          runId: message.run_id,
          messageId: message.id
        });
      });
      return;
    }
    for (const [pendingRunId, pending] of pendingStoredToolMessagesByRunId.entries()) {
      const runParent = assistantMessagesByRunId.get(pendingRunId) || null;
      pending.forEach((message) => {
        addToolEvent(message.event.type || 'tool_event', message.event, runParent || lastToolParent, {
          frameId: message.frame_id,
          runId: message.run_id,
          messageId: message.id
        });
      });
    }
    pendingStoredToolMessagesByRunId.clear();
  }

  reset();
  return { addMessage, addToolEvent, appendText, focusMessage, focusRun, registerAssistantRun, renderInlineArtifacts, renderStoredMessage, renderStoredMessages, reset, scrollBottom };
}

export function storedMessageReplayPlan(messages) {
  const items = Array.isArray(messages) ? messages : [];
  const assistantRunIds = new Set();
  items.forEach((message) => {
    if (message && message.role === 'assistant') {
      const runId = cleanRunId(message.run_id);
      if (runId) assistantRunIds.add(runId);
    }
  });
  return {
    assistantRunIds: Array.from(assistantRunIds),
    items: items.map((message) => {
      const runId = message && message.role === 'tool' ? cleanRunId(message.run_id) : '';
      return {
        message,
        assistantRunId: runId && assistantRunIds.has(runId) ? runId : ''
      };
    })
  };
}

export function hostBridgeModel(agent, selectedEvidence = []) {
  if (!agent || typeof agent !== 'object') return null;
  const count = Array.isArray(selectedEvidence) ? selectedEvidence.length : 0;
  if (!count) return null;
  const label = cleanLabel(agent.label || agent.id || 'Assistant');
  const id = cleanLabel(agent.id || '');
  const packetLabel = count + ' included item' + (count === 1 ? '' : 's');
  return {
    label,
    id,
    packetCount: count,
    summary: label + ' · ' + packetLabel,
    status: agent.runnable ? 'ready' : cleanLabel(agent.status || 'unavailable')
  };
}

function toolRecordKey(data, scope = {}) {
  const frameId = scope.frameId || 'frame';
  const runScope = scope.runId || (scope.messageId ? 'message:' + scope.messageId : 'run');
  const toolId = data && data.id ? data.id : Date.now() + ':' + Math.random().toString(16).slice(2);
  return ['tool', frameId, runScope, toolId].join(':');
}

function diagnosticRecordKey(scope = {}) {
  const frameId = scope.frameId || 'frame';
  const runScope = scope.runId || (scope.messageId ? 'message:' + scope.messageId : 'run');
  return ['diagnostics', frameId, runScope].join(':');
}

function sanitizeDiagnosticEvent(event) {
  const source = event && typeof event === 'object' && !Array.isArray(event) ? event : { message: event };
  const allowed = ['type', 'name', 'message', 'summary', 'status', 'level', 'chunk', 'error', 'created_at', 'timestamp'];
  const clean = {};
  allowed.forEach((key) => {
    if (source[key] === undefined || source[key] === null || source[key] === '') return;
    clean[key] = diagnosticFieldValue(source[key]);
  });
  if (!clean.type) clean.type = 'diagnostic';
  return clean;
}

function diagnosticFieldValue(value) {
  if (value && typeof value === 'object') return promptSafeText(formatPayload(value));
  return promptSafeText(String(value));
}

function diagnosticEventLabel(event, index = 0) {
  const name = promptSafeText(event && (event.name || event.type) || '').trim();
  if (!name || name === 'diagnostic') return 'Status update ' + String(index + 1);
  return name
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^./, (letter) => letter.toUpperCase());
}

function diagnosticEventSummary(event) {
  const source = event || {};
  return promptSafeText(source.message || source.summary || source.chunk || source.error || source.status || '').trim();
}

function hostBridgeBadge(model) {
  const bridge = document.createElement('div');
  bridge.className = 'message-bridge';
  bridge.innerHTML = '<span>Using</span><strong></strong><em></em>';
  bridge.querySelector('strong').textContent = model.summary;
  bridge.querySelector('em').textContent = model.status;
  return bridge;
}

function selectedEvidenceRefs(items) {
  const refs = document.createElement('div');
  refs.className = 'message-evidence-refs';
  const label = document.createElement('span');
  label.textContent = 'Using';
  refs.appendChild(label);
  items.slice(0, 4).forEach((item, index) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.textContent = selectedEvidenceDisplayLabel(item, index);
    chip.title = item.summary || item.prompt_text || item.text || chip.textContent;
    refs.appendChild(chip);
  });
  return refs;
}

function selectedEvidenceDisplayLabel(item, index) {
  const raw = cleanLabel(item && (item.label || item.summary || item.id) || '');
  const fallback = 'Context ' + String(index + 1);
  return (raw || fallback)
    .replace(/^(Genome state|Active genome):\s*/i, '')
    .replace(/^Evidence source:\s*/i, '')
    .trim() || fallback;
}

function cleanLabel(value) {
  return promptSafeText(String(value || '')).replace(/\s+/g, ' ').trim();
}

function cleanRunId(value) {
  return String(value || '').trim();
}
