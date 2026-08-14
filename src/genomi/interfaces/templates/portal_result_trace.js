export function resultTraceEntries(payload) {
  const trace = explicitTrace(payload);
  if (!trace) return [];
  if (Array.isArray(trace)) {
    return trace.map((value, index) => ({ key: String(index), label: itemLabel(value, index), value }))
      .filter((entry) => !isEmptyValue(entry.value));
  }
  if (trace && typeof trace === 'object') {
    return Object.entries(trace)
      .map(([key, value]) => ({ key, label: titleCase(key), value }))
      .filter((entry) => !isEmptyValue(entry.value));
  }
  return [{ key: 'value', label: 'Value', value: trace }];
}

export function renderResultTraceDetails(payload) {
  if (!payload || typeof payload !== 'object') return null;
  const entries = resultTraceEntries(payload);
  if (!entries.length) return null;
  const details = traceDetails('How this result was built');
  const body = details.querySelector('.result-trace-body');
  entries.slice(0, 10).forEach((entry) => body.appendChild(traceSection(entry.label, entry.value)));
  return details;
}

export function traceValueSummary(value) {
  return formatShort(value);
}

function explicitTrace(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
  if (!isEmptyValue(payload.presented_trace)) return payload.presented_trace;
  if (!isEmptyValue(payload.work_trace)) return payload.work_trace;
  return null;
}

function traceDetails(summaryText) {
  const details = document.createElement('details');
  details.className = 'result-trace-panel';
  const summary = document.createElement('summary');
  summary.textContent = summaryText;
  const body = document.createElement('div');
  body.className = 'result-trace-body';
  details.appendChild(summary);
  details.appendChild(body);
  return details;
}

function traceSection(label, value) {
  const section = document.createElement('div');
  section.className = 'result-trace-section';
  const heading = document.createElement('div');
  heading.className = 'result-trace-title';
  heading.innerHTML = '<span></span><strong></strong>';
  heading.querySelector('span').textContent = label;
  heading.querySelector('strong').textContent = traceValueSummary(value);
  const pre = document.createElement('pre');
  pre.textContent = formatPayload(value);
  section.appendChild(heading);
  section.appendChild(pre);
  return section;
}

function itemLabel(value, index) {
  if (value && typeof value === 'object') {
    for (const key of ['label', 'title', 'operation', 'source_id', 'status', 'type']) {
      if (typeof value[key] === 'string' && value[key]) return titleCase(value[key]);
    }
  }
  return 'Step ' + (index + 1);
}

import { formatPayload, formatShort, isEmptyValue, titleCase } from './portal_format.js';
