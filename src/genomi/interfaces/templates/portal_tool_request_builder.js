import {
  toolRequestBuilderModel,
  toolRequestFieldState
} from './portal_tool_request_model.js';

export {
  cleanRequestParams,
  conditionMatches,
  missingRequiredInputs,
  toolRequestBuilderModel,
  toolRequestFieldState
} from './portal_tool_request_model.js';

export function renderToolRequestBuilder(tool, options = {}) {
  const model = toolRequestBuilderModel(tool);
  if (!model.hasFields) return null;
  const section = document.createElement('div');
  section.className = 'tool-request-builder';
  section.innerHTML = [
    '<div class="tool-request-builder-head">',
    '<div><span>Evidence source</span><strong></strong></div>',
    '<p></p>',
    '</div>',
    '<div class="tool-request-guided"></div>',
    '<div class="tool-request-fields"></div>',
    '<div class="tool-request-actions"></div>'
  ].join('');
  section.querySelector('.tool-request-builder-head strong').textContent = model.displayLabel || model.name;
  section.querySelector('.tool-request-builder-head p').textContent = 'Add any details you know. Genomi will preserve source limits and ask for missing details in chat.';
  const fields = section.querySelector('.tool-request-fields');
  const fieldGroups = requestFieldGroups(model);
  model.fields.forEach((field) => {
    const row = toolRequestField(field);
    const group = fieldGroups.byParameter.get(field.name);
    if (group) group.body.appendChild(row);
    else fields.appendChild(row);
  });
  fieldGroups.groups.forEach((group) => {
    if (group.body.children.length) fields.appendChild(group.details);
  });
  installGuidedControls(section, model);
  applyInitialParams(section, model, options.initialParams);
  const actions = section.querySelector('.tool-request-actions');
  actions.appendChild(actionButton('Include source', () => {
    const params = toolRequestParams(section);
    if (typeof options.onAttachRequest === 'function') options.onAttachRequest(tool, params);
  }));
  actions.appendChild(actionButton('Ask now', () => {
    const params = toolRequestParams(section);
    if (typeof options.onAskRequest === 'function') options.onAskRequest(tool, params);
  }));
  installConditionalFieldFilter(section, model);
  return section;
}

function applyInitialParams(root, model, params = {}) {
  if (!params || typeof params !== 'object' || Array.isArray(params)) return;
  model.fields.forEach((field) => {
    if (!Object.prototype.hasOwnProperty.call(params, field.name)) return;
    const control = root.querySelector('[data-tool-param="' + cssString(field.name) + '"]');
    if (!control) return;
    setRequestInputValue(control, field, params[field.name]);
  });
}

function setRequestInputValue(control, field, value) {
  control.setAttribute('data-tool-param-touched', 'true');
  if (field.type === 'boolean') {
    control.checked = Boolean(value);
    control.indeterminate = false;
    dispatchControlChange(control);
    return;
  }
  control.value = value == null ? '' : String(value);
  dispatchControlInput(control);
  dispatchControlChange(control);
}

function requestFieldGroups(model) {
  const groups = [];
  const byParameter = new Map();
  const ui = model.ui || {};
  (Array.isArray(ui.fieldGroups) ? ui.fieldGroups : []).forEach((group) => {
    const details = document.createElement('details');
    details.className = group.className || 'tool-request-field-group';
    if (group.collapsed === false) details.setAttribute('open', 'open');
    details.innerHTML = [
      '<summary></summary>',
      '<div class="' + (group.bodyClassName || 'tool-request-field-group-body') + '"></div>'
    ].join('');
    details.querySelector('summary').textContent = group.label || 'More options';
    const body = details.querySelector('div');
    const record = { details, body };
    group.parameters.forEach((parameter) => byParameter.set(parameter, record));
    groups.push(record);
  });
  return { groups, byParameter };
}

function installGuidedControls(root, model) {
  const guided = root.querySelector('.tool-request-guided');
  if (!guided) return;
  guided.hidden = true;
  const ui = model.ui || {};
  (Array.isArray(ui.guidedControls) ? ui.guidedControls : []).forEach((control) => {
    if (control.kind !== 'segmented') return;
    const field = model.fields.find((item) => item.name === control.parameter);
    const fieldControl = root.querySelector('[data-tool-param="' + cssString(control.parameter) + '"]');
    if (!field || !fieldControl) return;
    const node = segmentedControlNode(control, field, fieldControl);
    if (!node) return;
    if (control.hideField) hideFieldControl(fieldControl);
    guided.hidden = false;
    guided.appendChild(node);
  });
}

function hideFieldControl(control) {
  const row = control.closest && control.closest('.tool-request-field');
  if (row) {
    row.className = appendClass(row.className, 'tool-request-field-hidden-control');
    row.setAttribute('aria-hidden', 'true');
  }
  control.setAttribute('tabindex', '-1');
}

function segmentedControlNode(controlModel, field, control) {
  const choices = controlModel.options.length
    ? controlModel.options
    : field.enumValues.map((value) => ({ value, label: value }));
  if (!choices.length) return null;
  const node = document.createElement('div');
  node.className = 'tool-request-guided-targets';
  const label = document.createElement('div');
  label.className = 'tool-request-guided-label';
  label.textContent = controlModel.label || field.label || field.name;
  const buttons = document.createElement('div');
  buttons.className = 'tool-request-guided-options';
  choices.forEach((choice) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'target-type-chip';
    button.setAttribute('data-target-type', choice.value);
    button.textContent = choice.label;
    button.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      control.value = choice.value;
      control.setAttribute('data-tool-param-touched', 'true');
      dispatchControlChange(control);
      syncTargetButtons(buttons, control.value);
    });
    buttons.appendChild(button);
  });
  control.addEventListener('change', () => syncTargetButtons(buttons, control.value));
  node.appendChild(label);
  node.appendChild(buttons);
  syncTargetButtons(buttons, control.value);
  return node;
}

function cssString(value) {
  if (typeof CSS !== 'undefined' && CSS.escape) return CSS.escape(String(value || ''));
  return String(value || '').replace(/["\\]/g, '\\$&');
}

function appendClass(className, name) {
  const current = String(className || '').split(/\s+/).filter(Boolean);
  if (!current.includes(name)) current.push(name);
  return current.join(' ');
}

function dispatchControlChange(control) {
  const event = typeof Event === 'function'
    ? new Event('change', { bubbles: true })
    : { type: 'change' };
  control.dispatchEvent(event);
}

function dispatchControlInput(control) {
  const event = typeof Event === 'function'
    ? new Event('input', { bubbles: true })
    : { type: 'input' };
  control.dispatchEvent(event);
}

function syncTargetButtons(root, activeValue) {
  root.querySelectorAll('.target-type-chip').forEach((button) => {
    const active = button.getAttribute('data-target-type') === activeValue;
    button.className = active ? 'target-type-chip active' : 'target-type-chip';
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
}

function toolRequestField(field) {
  const row = document.createElement('label');
  row.className = 'tool-request-field';
  row.setAttribute('data-tool-field-id', field.id);
  row.innerHTML = '<span></span><small></small>';
  row.querySelector('small').textContent = field.summary;
  row.appendChild(requestInputForField(field));
  setFieldRequired(row, field, field.required);
  return row;
}

function requestInputForField(field) {
  if (field.enumValues.length) {
    const select = document.createElement('select');
    select.setAttribute('data-tool-field-id', field.id);
    select.setAttribute('data-tool-param', field.name);
    select.setAttribute('data-tool-param-type', field.type);
    select.setAttribute('autocomplete', 'off');
    select.appendChild(optionNode('', field.defaultHint ? 'Use default (' + field.defaultHint + ')' : field.required ? 'Select value' : 'Leave blank'));
    field.enumValues.forEach((value) => select.appendChild(optionNode(value, value)));
    markTouchedOnInput(select);
    return select;
  }
  if (field.type === 'boolean') {
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.indeterminate = true;
    input.setAttribute('data-tool-field-id', field.id);
    input.setAttribute('data-tool-param', field.name);
    input.setAttribute('data-tool-param-type', field.type);
    input.setAttribute('autocomplete', 'off');
    markTouchedOnInput(input);
    return input;
  }
  const input = document.createElement(field.type === 'object' || field.type === 'array' ? 'textarea' : 'input');
  input.setAttribute('data-tool-field-id', field.id);
  input.setAttribute('data-tool-param', field.name);
  input.setAttribute('data-tool-param-type', field.type);
  input.setAttribute('autocomplete', 'off');
  if (field.type === 'number' || field.type === 'integer') input.type = 'number';
  else if (String(input.tagName || '').toLowerCase() === 'input') input.type = 'text';
  input.placeholder = field.defaultHint || field.placeholder;
  markTouchedOnInput(input);
  return input;
}

function optionNode(value, label) {
  const option = document.createElement('option');
  option.value = value;
  option.textContent = label;
  return option;
}

function markTouchedOnInput(input) {
  input.addEventListener('input', () => input.setAttribute('data-tool-param-touched', 'true'));
  input.addEventListener('change', () => input.setAttribute('data-tool-param-touched', 'true'));
}

function setFieldRequired(row, field, required) {
  const label = row.querySelector('span');
  if (label) label.textContent = (field.label || field.name) + (required ? ' *' : '');
  const control = row.querySelector('[data-tool-param]');
  if (control) control.setAttribute('aria-required', required ? 'true' : 'false');
}

function toolRequestParams(root) {
  const params = {};
  root.querySelectorAll('[data-tool-param]').forEach((input) => {
    const field = input.closest && input.closest('.tool-request-field');
    if (field && field.hidden) return;
    const name = input.getAttribute('data-tool-param');
    const value = requestInputValue(input);
    if (name && value !== undefined) params[name] = value;
  });
  return params;
}

function installConditionalFieldFilter(root, model) {
  const controls = [...root.querySelectorAll('[data-tool-param]')];
  const fieldsById = new Map(model.fields.map((field) => [field.id, field]));
  const update = () => {
    const params = currentControlValues(root);
    root.querySelectorAll('[data-tool-field-id]').forEach((row) => {
      if (!row.classList || !row.classList.contains('tool-request-field')) return;
      const field = fieldsById.get(row.getAttribute('data-tool-field-id'));
      if (!field) return;
      const state = toolRequestFieldState(model, field, params);
      row.hidden = !state.visible;
      setFieldRequired(row, field, state.required);
    });
  };
  controls.forEach((control) => {
    control.addEventListener('input', update);
    control.addEventListener('change', update);
  });
  update();
}

function currentControlValues(root) {
  const params = {};
  root.querySelectorAll('[data-tool-param]').forEach((input) => {
    const name = input.getAttribute('data-tool-param');
    const value = requestInputValue(input, { includeUntouched: true });
    if (name && value !== undefined) params[name] = value;
  });
  return params;
}

function requestInputValue(input, options = {}) {
  const type = input.getAttribute('data-tool-param-type') || '';
  const touched = input.getAttribute('data-tool-param-touched') === 'true';
  if (type === 'boolean') {
    if (!touched && !options.includeUntouched) return undefined;
    return Boolean(input.checked);
  }
  const raw = String(input.value || '').trim();
  if (!raw) return undefined;
  if (type === 'number') {
    const number = Number(raw);
    return Number.isFinite(number) ? number : raw;
  }
  if (type === 'integer') {
    const number = Number(raw);
    return Number.isInteger(number) ? number : raw;
  }
  if (type === 'object' || type === 'array') {
    try {
      return JSON.parse(raw);
    } catch {
      return raw;
    }
  }
  return raw;
}

function actionButton(label, handler) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'tool-action';
  button.textContent = label;
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    Promise.resolve(handler()).catch(() => undefined);
  });
  return button;
}
