export const SELECTED_ACTION_LABELS = Object.freeze({
  use: 'Use selection',
  copy: 'Copy selection',
  ask: 'Ask about selection',
  draft: 'Draft from selection'
});

const fallbackLabels = Object.freeze({
  result: Object.freeze({
    use: 'Use view',
    copy: 'Copy view',
    ask: 'Ask about view',
    draft: 'Draft from view'
  }),
  evidence: Object.freeze({
    use: 'Use evidence',
    copy: 'Copy evidence',
    ask: 'Ask about evidence',
    draft: 'Draft from evidence'
  }),
  ledger: Object.freeze({
    use: 'Attach evidence to chat',
    ask: 'Ask about current evidence',
    draft: 'Draft with current evidence'
  }),
  artifact: Object.freeze({
    use: 'Use result',
    ask: 'Ask about result',
    draft: 'Draft from result'
  })
});

const actionNames = Object.freeze(Object.keys(SELECTED_ACTION_LABELS));

export function selectedActionLabel(action) {
  return SELECTED_ACTION_LABELS[action] || '';
}

export function selectionFallbackLabels(surface) {
  return { ...(fallbackLabels[surface] || {}) };
}

export function selectedSurfaceActionLabels(subject = 'selection') {
  const clean = selectedActionSubject(subject);
  return {
    use: 'Use ' + clean,
    copy: 'Copy ' + clean,
    ask: 'Ask about ' + clean,
    draft: 'Draft from ' + clean
  };
}

export function selectionActionLabels(selectedCount, fallbackLabels = {}, selectedLabels = SELECTED_ACTION_LABELS) {
  const fallback = typeof fallbackLabels === 'string'
    ? selectionFallbackLabels(fallbackLabels)
    : { ...fallbackLabels };
  return {
    ...fallback,
    ...(selectedCount ? { ...selectedLabels } : {})
  };
}

function selectedActionSubject(value) {
  const text = String(value || '').trim().replace(/\s+/g, ' ');
  if (!text) return 'selection';
  const withoutItem = text.replace(/\s+items?\b$/i, '').trim();
  if (/^selected\b/i.test(withoutItem || text)) return withoutItem || text;
  return 'selected ' + (withoutItem || text);
}

export function createSelectionActionButton(options = {}) {
  const action = options.action || '';
  const button = document.createElement('button');
  button.type = 'button';
  button.className = options.className || 'tool-action';
  if (options.testId) button.setAttribute('data-testid', options.testId);
  if (action) button.setAttribute('data-action', options.dataAction || action);
  if (options.title) button.title = options.title;
  button.textContent = options.label || selectedActionLabel(action);
  if (options.disabled !== undefined) button.disabled = Boolean(options.disabled);
  button.addEventListener('click', (event) => {
    if (options.stopPropagation !== false && event && typeof event.stopPropagation === 'function') {
      event.stopPropagation();
    }
    if (typeof options.onClick === 'function') options.onClick(event);
  });
  return button;
}

export function applySelectionActionLabels(root, labels = {}, options = {}) {
  if (!root || typeof root.querySelector !== 'function') return;
  const actionSelectors = options.actionSelectors || {};
  actionNames.forEach((action) => {
    const selector = actionSelectors[action] || '[data-action="' + action + '"]';
    const button = root.querySelector(selector);
    if (button && labels[action]) button.textContent = labels[action];
  });
}
