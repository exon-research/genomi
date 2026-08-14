import { promptSafeText } from './portal_selected_evidence.js';
import { operationDisplayLabel } from './portal_operation_labels.js';
import {
  SELECTED_CONTEXT_FALLBACK_PROMPT,
  selectedContextKind,
  selectedContextSelectedItemNouns,
  selectedContextSummaryIncludedLabel
} from './portal_selected_context_catalog.js';
import {
  contextDisplayModel,
  contextLabel,
  contextNodes,
  contextSummary,
  rebuildContextItemWithNodes as rebuildModelContextItemWithNodes
} from './portal_prompt_context_model.js';

export {
  contextActionModel,
  contextDisplayModel,
  contextLabel,
  contextNodes,
  contextSummary,
  packetPromptText
} from './portal_prompt_context_model.js';

const storageVersion = 1;
const maxStoredContexts = 12;

export function createPromptContextController({
  tray,
  prompt,
  storageKey,
  onAskSelected,
  onAskNewConversation,
  onSuggestPrompt
}) {
  let contexts = selectedMaterialSet(readStoredContextItems(storageKey));
  if (contexts.length) writeStoredContextItems(storageKey, contexts);

  function add(value) {
    const item = promptContextItem(value);
    if (!item) return null;
    addContextItem(item);
    commit();
    prompt.focus();
    return item;
  }

  function clear() {
    contexts = [];
    commit();
  }

  function snapshot() {
    return selectedMaterialSet(contexts).map((item) => ({ ...item, selected_nodes: contextNodes(item) }));
  }

  function setPromptText(text) {
    prompt.value = text || '';
    prompt.focus();
  }

  async function askWith(value) {
    const item = promptContextItem(value);
    if (!item) return null;
    const submitted = selectedMaterialSet(contexts, item);
    contexts = submitted;
    commit();
    if (!prompt.value.trim()) prompt.value = await promptSuggestionForContexts(submitted);
    prompt.focus();
    if (typeof onAskSelected === 'function') {
      onAskSelected(submitted, { onSuccess: () => removeContextIds(new Set(submitted.map((candidate) => candidate.id))) });
    }
    return item;
  }

  async function askNewWith(value) {
    const item = promptContextItem(value);
    if (!item) return null;
    const submitted = selectedMaterialSet([], item);
    const promptText = promptSafeText(prompt.value || '').trim();
    const message = promptText || await promptSuggestionForContexts(submitted);
    prompt.value = '';
    prompt.focus();
    if (typeof onAskNewConversation === 'function') {
      onAskNewConversation(submitted, {
        message,
        onSuccess: () => removeContextIds(new Set(submitted.map((candidate) => candidate.id))),
        onError: () => {
          if (!prompt.value.trim()) prompt.value = promptText || message;
        }
      });
    }
    return item;
  }

  async function draftWith(value, options = {}) {
    const item = promptContextItem(value);
    if (!item) return null;
    let prompted = selectedMaterialSet([], item);
    if (options.attach !== false) {
      contexts = selectedMaterialSet(contexts, item);
      prompted = selectedMaterialSet(contexts);
      commit();
    }
    prompt.value = await promptSuggestionForContexts(prompted);
    prompt.focus();
    return item;
  }

  function render() {
    renderComposerTray();
  }

  function renderComposerTray() {
    if (!tray) return;
    tray.hidden = !contexts.length;
    if (!contexts.length) {
      tray.innerHTML = '';
      return;
    }
    const rendered = selectedMaterialSet(contexts);
    tray.innerHTML = '';
    const items = document.createElement('div');
    items.className = 'prompt-context-items';
    items.setAttribute('aria-label', 'Attached to next message');
    composerTrayViewModel(rendered).items.forEach((model, index) => {
      const card = document.createElement('article');
      card.className = 'prompt-context-card';
      card.setAttribute('data-testid', 'prompt-context-card');

      const cardHead = document.createElement('div');
      cardHead.className = 'prompt-context-card-head';
      const marker = document.createElement('span');
      marker.className = 'prompt-context-kind';
      marker.textContent = model.kindLabel;
      const label = document.createElement('strong');
      label.textContent = model.label;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'prompt-context-remove';
      remove.title = 'Remove from next message';
      remove.setAttribute('aria-label', 'Remove ' + model.label);
      remove.textContent = '\u00d7';
      remove.addEventListener('click', () => {
        const removedId = rendered[index] && rendered[index].id;
        contexts = contexts.filter((candidate) => candidate.id !== removedId);
        commit();
      });
      cardHead.append(marker, label, remove);
      card.appendChild(cardHead);
      items.appendChild(card);
    });
    if (rendered.length > 1) {
      const clearButton = document.createElement('button');
      clearButton.type = 'button';
      clearButton.className = 'prompt-context-clear';
      clearButton.textContent = 'Clear all';
      clearButton.addEventListener('click', clear);
      items.appendChild(clearButton);
    }
    tray.appendChild(items);
  }

  function removeContextIds(contextIds) {
    if (!contextIds || typeof contextIds.has !== 'function') return;
    contexts = contexts.filter((candidate) => !contextIds.has(candidate.id));
    commit();
  }

  function commit() {
    contexts = selectedMaterialSet(contexts);
    writeStoredContextItems(storageKey, contexts);
    render();
  }

  async function promptSuggestionForContexts(items) {
    const fallback = suggestedPromptForContexts(items);
    if (typeof onSuggestPrompt !== 'function') return fallback;
    try {
      const suggestion = await onSuggestPrompt(items);
      const text = promptSafeText(suggestion || '').trim();
      return text || fallback;
    } catch {
      return fallback;
    }
  }

  function addContextItem(item) {
    contexts = selectedMaterialSet(contexts, item);
  }

  render();
  return { add, askNewWith, askWith, clear, draftWith, setPromptText, snapshot };
}

export function suggestedPromptForContexts(items) {
  const contexts = Array.isArray(items) ? items : [];
  if (contexts.length && contexts.every((item) => selectedContextKind(item) === 'genome_context')) return '';
  return contexts.length ? SELECTED_CONTEXT_FALLBACK_PROMPT : '';
}

export function selectedMaterialSet(items, extraItem) {
  const selected = [];
  (Array.isArray(items) ? items : []).forEach((item) => addSelectedMaterialItem(selected, item));
  if (arguments.length > 1) addSelectedMaterialItem(selected, extraItem);
  return selected.slice(0, maxStoredContexts);
}

function addSelectedMaterialItem(selected, value) {
  const item = promptContextItem(value);
  if (!item) return;
  const key = contextKey(item);
  const existingIndex = selected.findIndex((candidate) => contextKey(candidate) === key);
  if (existingIndex >= 0) {
    selected[existingIndex] = item;
    return;
  }
  selected.push(item);
}

function normalizeContextItem(value) {
  if (!value) return null;
  if (typeof value === 'string') {
    return { id: stableContextId({ label: 'Selected material', text: value }), label: 'Selected material', text: value };
  }
  if (typeof value !== 'object') return null;
  const id = value.id || stableContextId(value);
  return { ...value, id };
}

export function serializeContextItems(items) {
  return JSON.stringify({
    version: storageVersion,
    items: serializeReadyContextItems(items)
  });
}

export function parseStoredContextItems(raw) {
  if (!raw || typeof raw !== 'string') return [];
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || parsed.version !== storageVersion || !Array.isArray(parsed.items)) return [];
    return serializeReadyContextItems(parsed.items);
  } catch {
    return [];
  }
}

function readStoredContextItems(storageKey) {
  const storage = contextStorage();
  if (!storageKey || !storage) return [];
  try {
    return parseStoredContextItems(storage.getItem(storageKey));
  } catch {
    return [];
  }
}

function writeStoredContextItems(storageKey, items) {
  const storage = contextStorage();
  if (!storageKey || !storage) return;
  try {
    const ready = serializeReadyContextItems(items);
    if (ready.length) storage.setItem(storageKey, JSON.stringify({ version: storageVersion, items: ready }));
    else storage.removeItem(storageKey);
  } catch {
    // Browser storage is an interaction convenience; it must never block chat.
  }
}

function contextStorage() {
  try {
    return typeof window !== 'undefined' && window.sessionStorage ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

export function composerTrayViewModel(items) {
  const contexts = Array.isArray(items) ? items : [];
  return {
    count: contexts.length,
    countLabel: contexts.length + ' included item' + (contexts.length === 1 ? '' : 's'),
    items: contexts.map(composerTrayItemModel).filter(Boolean)
  };
}

export function composerTrayItemModel(item) {
  if (!item) return null;
  const display = contextDisplayModel(item);
  const nodes = contextNodes(item);
  const selectedCount = nodes.length;
  const source = display.source;
  const sourceOperation = promptSafeText(item.source_operation || '').trim();
  return {
    id: promptSafeText(item.id || '').slice(0, 160),
    label: trayVisibleText(display.label, sourceOperation),
    kindLabel: display.kindLabel,
    source,
    action: trayActionModel(display.action),
    preview: trayVisibleText(display.preview, sourceOperation),
    nodeCount: selectedCount,
    nodeCountLabel: selectedContextCountLabel(item, selectedCount),
    envelopeState: readableTrayState(display.envelopeState),
    nodes: nodes.slice(0, 3).map((node) => trayNodePreview(node, sourceOperation)),
    moreCount: Math.max(0, selectedCount - 3)
  };
}

function trayActionModel(action) {
  if (!action || typeof action !== 'object') return {};
  return {
    kindLabel: promptSafeText(action.kindLabel || '').trim(),
    askLabel: promptSafeText(action.askLabel || '').trim(),
    draftLabel: promptSafeText(action.draftLabel || '').trim(),
    askEnabled: action.askEnabled !== false,
    draftEnabled: action.draftEnabled !== false
  };
}

function selectedContextCountLabel(item, selectedCount) {
  if (!selectedCount) return selectedContextSummaryIncludedLabel(item);
  const nouns = selectedContextSelectedItemNouns(item);
  return selectedCount + ' selected ' + (selectedCount === 1 ? nouns.singular : nouns.plural);
}

function trayNodePreview(node, sourceOperation) {
  const label = trayVisibleText(node && node.label, sourceOperation);
  const rawText = trayVisibleText(node && (node.text || node.value), sourceOperation);
  const colonIndex = rawText.indexOf(':');
  let text = rawText;
  if (colonIndex > 0) {
    const prefix = rawText.slice(0, colonIndex).trim();
    const value = rawText.slice(colonIndex + 1).trim();
    if (value && (prefix.includes(label) || label.includes(prefix))) text = value;
  }
  return { label, text };
}

function trayVisibleText(value, sourceOperation) {
  const text = contextSummary(value || '');
  const operation = promptSafeText(sourceOperation || '').trim();
  if (!operation) return text;
  const label = promptSafeText(operationDisplayLabel(operation, 'Genomi evidence')).trim() || 'Genomi evidence';
  return replaceExactOperationId(text, operation, label);
}

function replaceExactOperationId(text, operation, label) {
  if (!text || !operation || operation === label) return text;
  const pattern = new RegExp('(^|[^A-Za-z0-9_])' + escapeRegExp(operation) + '(?=$|[^A-Za-z0-9_])', 'g');
  return text.replace(pattern, (_match, prefix) => prefix + label);
}

function escapeRegExp(value) {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function readableTrayState(value) {
  const clean = promptSafeText(value || '').trim();
  if (!clean) return '';
  return clean
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^./, (letter) => letter.toUpperCase());
}

function serializeReadyContextItems(items) {
  if (!Array.isArray(items)) return [];
  return items
    .slice(0, maxStoredContexts)
    .map((item) => storageContextItem(normalizeContextItem(item)))
    .filter(Boolean);
}

function promptContextItem(value) {
  return storageContextItem(normalizeContextItem(value));
}

function storageContextItem(item) {
  if (!item) return null;
  const nodes = contextNodes(item);
  const label = contextLabel(item);
  const promptText = storedPromptText(item, label, nodes);
  if (!promptText && !nodes.length) return null;
  const stored = {
    id: promptSafeText(item.id || stableContextId(item)).slice(0, 160),
    label: label.slice(0, 240),
    client_supplied: true
  };
  if (promptText) stored.prompt_text = promptText;
  copyTextField(stored, item, 'context_kind', 80);
  copyTextField(stored, item, 'finding_state', 120);
  copyTextField(stored, item, 'answer_readiness', 120);
  copyTextField(stored, item, 'summary', 1200);
  copyTextField(stored, item, 'source_operation', 240);
  copyTextField(stored, item, 'tool_call_id', 160);
  copyTextField(stored, item, 'tool_result_id', 160);
  if (nodes.length) stored.selected_nodes = nodes.slice(0, 16);
  return stored;
}

function storedPromptText(item, label, nodes) {
  if (nodes.length) return '';
  const text = promptSafeText(item.prompt_text || item.text || item.summary || '').trim();
  if (text) return trayVisibleText(normalizeStoredPromptText(text), item && item.source_operation).slice(0, 4000);
  return promptSafeText(label).slice(0, 4000);
}

function normalizeStoredPromptText(text) {
  return promptSafeText(text || '')
    .replace(/^Prepared(?: Genomi)? evidence-source request\b\s*:?\s*/i, 'Attached evidence source: ')
    .trim();
}

function copyTextField(target, item, key, limit) {
  const value = item && item[key];
  if (typeof value !== 'string' || !value.trim()) return;
  target[key] = promptSafeText(value).trim().slice(0, limit);
}

function contextKey(item) {
  const nodeKey = contextNodes(item)
    .map((node) => [node.label || '', node.text || '', node.value || ''].join(':'))
    .join('|');
  return [item.context_kind || '', item.source_operation || '', item.tool_call_id || '', item.tool_result_id || '', item.label || '', nodeKey || item.text || item.prompt_text || ''].join('|');
}

function stableContextId(value) {
  const nodes = contextNodes(value);
  const source = value && typeof value === 'object'
    ? [
        value.context_kind || '',
        value.source_operation || '',
        value.tool_call_id || '',
        value.tool_result_id || '',
        value.label || '',
        value.summary || '',
        value.text || '',
        value.prompt_text || '',
        nodes.map((node) => [node.label || '', node.text || '', node.value || ''].join(':')).join('|')
      ].join('|')
    : String(value || '');
  return 'ctx-' + stableHash(promptSafeText(source).slice(0, 4000));
}

function stableHash(value) {
  let hash = 2166136261;
  const text = String(value || '');
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16);
}

export function rebuildContextItemWithNodes(item, nodes) {
  return storageContextItem(rebuildModelContextItemWithNodes(item, nodes));
}
