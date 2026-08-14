import { compactLine, titleCase } from './portal_format.js';
import { operationDisplayLabel } from './portal_operation_labels.js';
import { promptSafeText } from './portal_selected_evidence.js';

export const ARTIFACT_MESSAGE_DISPLAY_LIMIT = 50;

export function artifactOriginContextModel(artifact) {
  const origin = object(artifact && (artifact.origin_context || artifact.origin_frame));
  const frameId = firstText(origin.frame_id, origin.frameId);
  if (!frameId) return null;
  const messageIdsCount = positiveInteger(
    firstText(origin.message_ids_count, origin.messageIdsCount, origin.message_count, origin.messageCount),
    0
  );
  const producingRunId = firstText(origin.producing_run_id, origin.producingRunId);
  const producingAssistantMessageId = firstText(origin.producing_assistant_message_id, origin.producingAssistantMessageId);
  const runIds = runIdList([producingRunId, ...runIdList(origin.run_ids || origin.runIds)]);
  const producingStepId = artifactProducingStepId(artifact);
  return {
    frameId,
    messageIdsCount,
    runIds,
    producingRunId,
    producingAssistantMessageId,
    producingStepId,
    label: 'View in chat',
    summary: messageIdsCount
      ? messageIdsCount + ' origin message' + (messageIdsCount === 1 ? '' : 's')
      : 'Origin frame'
  };
}

export function artifactMessagesModel(artifact, options = {}) {
  const provenance = object(artifact && artifact.provenance_messages);
  const rawMessages = Array.isArray(provenance.messages)
    ? provenance.messages.filter((message) => message && typeof message === 'object' && !Array.isArray(message))
    : [];
  const messages = rawMessages.map((message) => normalizeArtifactMessage(message)).filter(Boolean);
  const displayLimit = positiveInteger(options.displayLimit, ARTIFACT_MESSAGE_DISPLAY_LIMIT);
  const shown = messages.slice(0, displayLimit);
  if (!shown.length) return null;
  const total = positiveInteger(provenance.total, rawMessages.length || messages.length);
  const displayed = shown.length;
  const hasMore = total > displayed || messages.length > displayed;
  return {
    title: 'Origin messages',
    frame_id: firstText(provenance.frame_id),
    total,
    displayed,
    has_more: hasMore,
    display_limit: displayLimit,
    metrics: [
      metric('Displayed', displayed + (hasMore ? ' of ' + total : '')),
      metric('Total', total)
    ].filter(Boolean),
    sections: [
      {
        title: hasMore ? 'Transcript slice' : 'Transcript',
        nodes: shown.map((message, index) => artifactMessageNode(message, index))
      }
    ]
  };
}

function normalizeArtifactMessage(message) {
  const normalized = cleanObject({
    id: firstText(message.id),
    role: firstText(message.role) || 'message',
    created_at: firstText(message.created_at),
    updated_at: firstText(message.updated_at),
    run_id: firstText(message.run_id),
    stream_status: firstText(message.stream_status)
  });
  const text = firstText(message.text);
  if (text) normalized.text = promptSafeText(text);
  const event = normalizeArtifactMessageEvent(message.event);
  if (event) normalized.event = event;
  return Object.keys(normalized).length ? normalized : null;
}

function normalizeArtifactMessageEvent(value) {
  const event = object(value);
  if (!Object.keys(event).length) return null;
  const ledger = object(event.ledger);
  const content = firstText(event.content, event.message, ledger.summary);
  const normalized = cleanObject({
    id: firstText(event.id),
    type: firstText(event.type),
    name: firstText(event.name),
    is_error: event.isError === true ? true : undefined,
    status: firstText(ledger.status),
    summary: promptSafeText(firstText(ledger.summary)),
    content: promptSafeText(content)
  });
  return Object.keys(normalized).length ? normalized : null;
}

function artifactMessageNode(message, index) {
  const event = object(message.event);
  const role = firstText(message.role) || 'message';
  const eventName = artifactEventLabel(event);
  const label = (index + 1) + '. ' + (eventName ? titleCase(role) + ' / ' + eventName : titleCase(role));
  return {
    label,
    summary: artifactMessageSummary(message, event),
    value: artifactMessageValue(message, event)
  };
}

function artifactMessageSummary(message, event) {
  const text = firstText(message.text);
  if (text) return promptSafeText(compactLine(text, 140));
  const content = firstText(event.content, event.summary, event.name, event.type, message.stream_status, message.role);
  return promptSafeText(compactLine(content || 'Message', 140));
}

function artifactMessageValue(message, event) {
  const eventLabel = artifactEventLabel(event);
  return cleanObject({
    role: firstText(message.role),
    created_at: firstText(message.created_at),
    updated_at: firstText(message.updated_at),
    stream_status: firstText(message.stream_status),
    text: firstText(message.text),
    work_step: eventLabel,
    work_status: firstText(event.status),
    work_summary: firstText(event.summary, event.content)
  });
}

function artifactEventLabel(event) {
  const raw = firstText(event && event.name, event && event.type);
  if (!raw) return '';
  const friendly = operationDisplayLabel(raw, 'Research step');
  return friendly && friendly !== 'Research step' ? friendly : titleCase(raw);
}

function metric(label, value) {
  if (value === null || value === undefined || value === '' || value === false) return null;
  return { label, value };
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function artifactProducingStepId(artifact) {
  const item = object(artifact);
  const latestVersion = object(item.latest_version || item.latestVersion);
  const selectedVersion = object(item.selected_version || item.selectedVersion);
  const effectiveVersion = object(item.effective_version || item.effectiveVersion);
  const workStep = object(
    item.producing_work_step ||
    item.producingWorkStep ||
    effectiveVersion.producing_work_step ||
    effectiveVersion.producingWorkStep ||
    selectedVersion.producing_work_step ||
    selectedVersion.producingWorkStep ||
    latestVersion.producing_work_step ||
    latestVersion.producingWorkStep
  );
  if (firstText(workStep.kind) !== 'artifact_producing_work_step') return '';
  const executionCell = object(workStep.execution_cell || workStep.executionCell);
  return firstText(executionCell.id);
}

function cleanObject(value) {
  return Object.fromEntries(
    Object.entries(value).filter(([, child]) => child !== null && child !== undefined && child !== '')
  );
}

function firstText(...values) {
  for (const value of values) {
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return '';
}

function positiveInteger(value, fallback) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : fallback;
}

function runIdList(value) {
  if (!Array.isArray(value)) return [];
  const runIds = [];
  value.map((runId) => firstText(runId)).filter(Boolean).forEach((runId) => {
    if (!runIds.includes(runId)) runIds.push(runId);
  });
  return runIds;
}
