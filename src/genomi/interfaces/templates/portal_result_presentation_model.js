import { compactLine, isEmptyValue } from './portal_format.js';
import { promptSafeText } from './portal_selected_evidence.js';

export const PORTAL_RESULT_PRESENTATION_SCHEMA = 'genomi_portal_result_presentation';

export function sourceOperation(record) {
  const presentation = portalResultPresentation(record && record.result && record.result.portal_presentation);
  const operation = presentationText(presentation && presentation.operation);
  if (operation) return operation;
  const resultPayload = object(record && record.result && record.result.payload);
  const dispatched = presentationText(
    resultPayload.dispatched_tool
    || (record && record.result && record.result.dispatched_tool)
    || object(record && record.call && record.call.input).tool
  );
  if (dispatched) return dispatched;
  return (record && record.call && record.call.name) || (record && record.result && record.result.name) || '';
}

export function serverResultPresentationModel(presentation, operation = '') {
  const raw = portalResultPresentation(presentation);
  if (!raw) return null;
  const kicker = presentationText(raw.kicker);
  const title = presentationText(raw.title) || presentationText(raw.summary);
  if (!kicker || !title) return null;
  const lanes = array(raw.lanes)
    .map((lane) => serverPresentationLane(lane))
    .filter(Boolean);
  const notice = object(raw.notice);
  return {
    kind: presentationText(raw.kind) || 'result',
    operation: presentationText(raw.operation) || String(operation || ''),
    kicker,
    title,
    summary: compactLine(presentationText(raw.summary), 220),
    evidenceEnvelope: object(raw.evidenceEnvelope),
    notice: Object.keys(notice).length ? notice : null,
    metrics: array(raw.metrics).map((item) => serverPresentationMetric(item)).filter(Boolean),
    lanes
  };
}

export function portalResultPresentation(value) {
  const model = object(value);
  return model.schema === PORTAL_RESULT_PRESENTATION_SCHEMA ? model : null;
}

function serverPresentationLane(lane) {
  const model = object(lane);
  const title = presentationText(model.title);
  if (!title) return null;
  const nodes = array(model.nodes)
    .map((item) => serverPresentationNode(item))
    .filter(Boolean);
  return nodes.length ? { title, nodes, selectable: model.selectable !== false } : null;
}

function serverPresentationNode(item) {
  const nodeModel = object(item);
  const label = presentationText(nodeModel.label);
  const summary = compactLine(presentationText(nodeModel.summary), 160);
  if (!label || !summary) return null;
  return {
    label,
    summary,
    context: presentationText(nodeModel.context) || (label + ': ' + summary),
    value: nodeModel.value,
    selectable: nodeModel.selectable !== false
  };
}

function serverPresentationMetric(item) {
  const model = object(item);
  const label = presentationText(model.label);
  if (!label || isEmptyValue(model.value)) return null;
  return { label, value: model.value };
}

function presentationText(value) {
  return typeof value === 'string' ? promptSafeText(value).trim() : '';
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function array(value) {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === 'object') : [];
}
