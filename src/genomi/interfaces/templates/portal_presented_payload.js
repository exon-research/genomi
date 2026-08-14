import { parseJsonText } from './portal_format.js';

export function extractPresentedPayload(record) {
  if (record && record.result && record.result.payload !== undefined) {
    return unwrapPresentedPayload(record.result.payload);
  }
  const raw = record && record.result ? record.result.content : null;
  const parsed = parseJsonText(raw);
  return unwrapPresentedPayload(parsed);
}

export function unwrapPresentedPayload(value) {
  if (!value || typeof value !== 'object') return value;
  if (Array.isArray(value.content)) {
    const textItem = value.content.find((item) => item && item.type === 'text' && typeof item.text === 'string');
    const nested = textItem ? parseJsonText(textItem.text) : null;
    if (nested) return unwrapPresentedPayload(nested);
  }
  if (value.result && typeof value.result === 'object' && !value.evidence_envelope) {
    return unwrapPresentedPayload(value.result);
  }
  return value;
}

export function hasCanonicalEvidenceEnvelope(payload) {
  return Boolean(
    payload &&
    typeof payload === 'object' &&
    !Array.isArray(payload) &&
    payload.evidence_envelope &&
    typeof payload.evidence_envelope === 'object' &&
    !Array.isArray(payload.evidence_envelope)
  );
}

export function normalizeEvidencePayload(payload) {
  if (!hasCanonicalEvidenceEnvelope(payload)) return null;
  const envelope = payload.evidence_envelope;
  return {
    payload,
    envelope,
    headline: payload.headline || envelope.headline || payload.message || payload.status || '',
    status: payload.status || '',
    defaults_applied: payload.defaults_applied
  };
}
