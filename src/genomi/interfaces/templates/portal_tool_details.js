import { compactLine, formatPayload } from './portal_format.js';
import { promptSafeText } from './portal_selected_evidence.js';
import {
  fallbackToolDetails,
  renderToolResultSections,
  toolResultFollowUpRequest,
  toolNameLabel as presentationToolNameLabel,
  toolResultSummary as presentationToolResultSummary
} from './portal_tool_result_presentation.js';

export const toolNameLabel = presentationToolNameLabel;
export const toolResultSummary = presentationToolResultSummary;

export function toolFollowUpActionModel(record) {
  const followUp = toolResultFollowUpRequest(record);
  return {
    label: followUp.displayOnly ? 'Re-check evidence' : 'Ask follow-up',
    followUp
  };
}

export function toolInputSummary(input) {
  if (!input || typeof input !== 'object') return compactLine(promptSafeText(formatPayload(input)), 160);
  const keys = ['human_description', 'description', 'summary', 'rsid', 'query', 'drug', 'gene', 'phenotype'];
  for (const key of keys) {
    if (typeof input[key] === 'string' && input[key].trim()) return compactLine(promptSafeText(input[key]), 160);
  }
  if (typeof input.operation === 'string' && input.operation.trim()) {
    return compactLine(presentationToolNameLabel(input.operation), 160);
  }
  if (typeof input.command === 'string') return compactLine(promptSafeText(input.command.split('\n')[0]), 160);
  return compactLine(promptSafeText(formatPayload(input)), 160);
}

export function renderToolDetails(container, record, options = {}) {
  container.innerHTML = '';
  renderToolResultSections(record, options).forEach((section) => {
    container.appendChild(section.node);
  });
  const technical = renderToolTechnicalDetails(record);
  if (technical) container.appendChild(technical);
  const actions = document.createElement('div');
  const followUpAction = toolFollowUpActionModel(record);
  actions.className = 'tool-actions';
  actions.innerHTML = '<button class="tool-action" type="button">Copy technical details</button><button class="tool-action" type="button">Ask follow-up</button>';
  actions.children[1].textContent = followUpAction.label;
  actions.children[0].addEventListener('click', (event) => {
    event.stopPropagation();
    const text = fallbackToolDetails(record).map((part) => part.label + ':\n' + part.text).join('\n\n');
    if (navigator.clipboard) navigator.clipboard.writeText(text);
  });
  actions.children[1].addEventListener('click', (event) => {
    event.stopPropagation();
    if (typeof options.onAskFollowUp === 'function') options.onAskFollowUp(followUpAction.followUp);
  });
  container.appendChild(actions);
}

export function renderToolTechnicalDetails(record, options = {}) {
  const parts = fallbackToolDetails(record);
  if (!parts.length) return null;
  const details = document.createElement('details');
  details.className = 'tool-technical-details';
  if (options.open === true) details.open = true;
  const summary = document.createElement('summary');
  summary.textContent = options.summary || 'Technical details';
  details.appendChild(summary);
  const body = document.createElement('div');
  body.className = 'tool-technical-details-body';
  parts.forEach((part) => body.appendChild(toolDetailBlock(part)));
  details.appendChild(body);
  return details;
}

function toolDetailBlock(part) {
  const block = document.createElement('div');
  block.innerHTML = '<div class="tool-detail-label"></div><pre class="tool-detail-pre"></pre>';
  block.querySelector('.tool-detail-label').textContent = part.label;
  block.querySelector('.tool-detail-pre').textContent = part.text || '';
  return block;
}
