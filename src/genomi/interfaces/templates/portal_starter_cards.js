export function portalStarterModel() {
  const script = typeof document !== 'undefined' && document.getElementById
    ? document.getElementById('genomi-starter-cards')
    : null;
  if (!script) return { intro: '', cards: [] };
  try {
    const parsed = JSON.parse(script.textContent || '{}');
    return starterModel(parsed);
  } catch {
    return { intro: '', cards: [] };
  }
}

export function welcomeMessageMarkup(model = portalStarterModel()) {
  const data = starterModel(model);
  if (!data.intro && !data.cards.length) return '';
  return [
    '<div class="message assistant chat-welcome" data-testid="genomi-chat-welcome">',
    '<div class="role">Genomi Portal</div>',
    '<div class="body">',
    data.intro ? '<p>' + escapeHtml(data.intro) + '</p>' : '',
    '<div class="message-suggestions" data-testid="genomi-chat-suggestions">',
    data.cards.map(starterCardMarkup).join(''),
    '</div>',
    '</div>',
    '</div>'
  ].join('');
}

export function setStarterCardPending(button) {
  setStarterCardState(button, 'loading', 'Opening evidence source...');
}

export function clearStarterCardState(button) {
  if (!button) return;
  const detail = starterCardDetail(button);
  if (detail && button.dataset.starterDefaultDetail) detail.textContent = button.dataset.starterDefaultDetail;
  if (detail && detail.removeAttribute) detail.removeAttribute('data-source-unavailable');
  delete button.dataset.sourceState;
  if (button.removeAttribute) button.removeAttribute('aria-live');
}

export function markStarterSourceUnavailable(button, message = '') {
  const detail = starterCardDetail(button);
  setStarterCardState(button, 'unavailable', sourceUnavailableText(message));
  if (detail) detail.setAttribute('data-source-unavailable', 'true');
}

function setStarterCardState(button, state, message) {
  if (!button) return;
  const detail = starterCardDetail(button);
  if (detail && !button.dataset.starterDefaultDetail) {
    button.dataset.starterDefaultDetail = detail.textContent || '';
  }
  button.dataset.sourceState = state;
  button.setAttribute('aria-live', 'polite');
  if (detail) {
    detail.textContent = message;
    if (state !== 'unavailable' && detail.removeAttribute) detail.removeAttribute('data-source-unavailable');
  }
}

function sourceUnavailableText(message) {
  const detail = String(message || '').replace(/\s+/g, ' ').trim();
  return detail
    ? 'Evidence source unavailable. ' + detail
    : 'Evidence source unavailable. Refresh evidence sources or try again.';
}

function starterCardDetail(button) {
  if (!button || !button.querySelector) return null;
  return button.querySelector('[data-starter-card-detail]') || button.querySelector('span');
}

function starterModel(value) {
  const source = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  return {
    intro: String(source.intro || ''),
    cards: (Array.isArray(source.cards) ? source.cards : []).map(starterCardModel).filter(Boolean)
  };
}

function starterCardModel(value) {
  const source = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const label = String(source.label || '').trim();
  const detail = String(source.detail || '').trim();
  const prompt = String(source.prompt || '');
  const sourceOperation = String(source.sourceOperation || '').trim();
  if (!label || !detail || (!prompt && !sourceOperation)) return null;
  const card = {
    id: String(source.id || '').trim(),
    label,
    detail,
    prompt,
    sourceOperation,
    sourceParams: object(source.sourceParams)
  };
  return card;
}

function starterCardMarkup(card) {
  const attrs = [
    ['class', 'suggestion-chip'],
    ['type', 'button'],
    ['data-starter-card-id', card.id]
  ];
  if (card.prompt) attrs.push(['data-prompt', card.prompt]);
  if (card.sourceOperation) attrs.push(['data-source-operation', card.sourceOperation]);
  let attrText = attrs
    .filter((item) => item[1])
    .map((item) => item[0] + '="' + escapeAttribute(item[1]) + '"')
    .join(' ');
  const params = sourceParamsText(card.sourceParams);
  if (params) attrText += " data-source-params='" + escapeSingleQuotedAttribute(params) + "'";
  return [
    '<button ',
    attrText,
    '>',
    '<strong>' + escapeHtml(card.label) + '</strong>',
    '<span data-starter-card-detail>' + escapeHtml(card.detail) + '</span>',
    '</button>'
  ].join('');
}

function sourceParamsText(value) {
  const params = object(value);
  if (!Object.keys(params).length) return '';
  try {
    return JSON.stringify(params);
  } catch {
    return '';
  }
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function escapeAttribute(value) {
  return escapeHtml(value)
    .replace(/"/g, '&quot;');
}

function escapeSingleQuotedAttribute(value) {
  return escapeHtml(value)
    .replace(/'/g, '&#39;');
}
