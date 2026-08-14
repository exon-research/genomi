import { compactLine } from './portal_format.js';

const LOCAL_PATH_PATTERN = /(?:~|\/Users|\/home|\/tmp|\/private\/tmp|\/var\/folders|\/opt\/homebrew|\/usr\/local|\/Applications|\/Volumes)(?:\/[^\s"'<>),;:]+)*/g;
const SENSITIVE_PATH_FIELD_PATTERN = /(["']?)(context_file|registry_file|agi_path)\1\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^,\s}\]]+)/gi;

export function toolRequestBuilderModel(tool) {
  const name = String(tool && tool.name || 'tool');
  const sourceLookup = object(tool && tool.sourceLookup);
  const sourceRequest = object(sourceLookup.request);
  const sourceFields = array(sourceRequest.fields).map((field) => sourceRequestFieldModel(field)).filter(Boolean);
  const sourceRequired = array(sourceRequest.requiredInputs).map(String).filter(Boolean);
  const operationId = String(sourceLookup.operationId || sourceLookup.name || name);
  return {
    name: operationId,
    displayLabel: safeEvidenceSourceText(String(sourceLookup.displayLabel || operationId)),
    description: compactLine(safeEvidenceSourceText(String(sourceLookup.description || '')), 360),
    requiredInputs: sourceRequired,
    fields: sourceFields,
    ui: sourceRequestUiModel(sourceRequest.ui),
    hasFields: Boolean(sourceFields.length)
  };
}

export function cleanRequestParams(params) {
  if (!params || typeof params !== 'object' || Array.isArray(params)) return {};
  return Object.fromEntries(Object.entries(params).filter(([, value]) => value !== undefined && value !== ''));
}

export function missingRequiredInputs(model, params) {
  const clean = cleanRequestParams(params);
  const missing = new Set((Array.isArray(model.requiredInputs) ? model.requiredInputs : []).filter((name) => clean[name] === undefined));
  model.fields.forEach((field) => {
    if (field.requiredWhen && conditionMatches(field.requiredWhen, clean) && clean[field.name] === undefined) {
      missing.add(field.name);
    }
  });
  return [...missing];
}

export function toolRequestFieldState(model, field, params = {}) {
  const clean = cleanRequestParams(params);
  return {
    visible: !field.visibleWhen || conditionMatches(field.visibleWhen, clean),
    required: (Array.isArray(model.requiredInputs) && model.requiredInputs.includes(field.name)) ||
      Boolean(field.requiredWhen && conditionMatches(field.requiredWhen, clean))
  };
}

export function conditionMatches(condition, params) {
  const clean = cleanRequestParams(params);
  const name = condition && condition.parameter;
  if (!name) return false;
  const value = clean[name];
  if (Object.prototype.hasOwnProperty.call(condition, 'equals')) return value === condition.equals;
  if (Array.isArray(condition.in)) return condition.in.includes(value);
  return false;
}

function sourceRequestFieldModel(value) {
  const field = object(value);
  const name = String(field.name || field.id || '').trim();
  if (!name) return null;
  const result = {
    id: String(field.id || name),
    name,
    label: safeEvidenceSourceText(String(field.label || name)),
    required: Boolean(field.required),
    type: String(field.type || 'string'),
    enumValues: array(field.enumValues || field.enum).map(String).filter(Boolean),
    defaultValue: field.defaultValue,
    defaultHint: String(field.defaultHint || ''),
    summary: compactLine(safeEvidenceSourceText(String(field.summary || (field.required ? 'Required input' : 'Optional input'))), 150),
    placeholder: safeEvidenceSourceText(String(field.placeholder || '')),
    visibleWhen: normalizedCondition(field.visibleWhen),
    requiredWhen: normalizedCondition(field.requiredWhen)
  };
  if (!Object.prototype.hasOwnProperty.call(field, 'defaultValue')) delete result.defaultValue;
  return result;
}

function sourceRequestUiModel(value) {
  const ui = object(value);
  return {
    guidedControls: array(ui.guidedControls).map((control) => guidedControlModel(control)).filter(Boolean),
    fieldGroups: array(ui.fieldGroups).map((group) => fieldGroupModel(group)).filter(Boolean)
  };
}

function guidedControlModel(value) {
  const control = object(value);
  const parameter = String(control.parameter || '').trim();
  const kind = String(control.kind || '').trim();
  if (!parameter || !kind) return null;
  return {
    id: String(control.id || parameter),
    kind,
    parameter,
    label: safeEvidenceSourceText(String(control.label || parameter)),
    hideField: Boolean(control.hideField),
    options: controlOptions(control.options)
  };
}

function fieldGroupModel(value) {
  const group = object(value);
  const parameters = array(group.parameters).map(String).filter(Boolean);
  if (!parameters.length) return null;
  return {
    id: String(group.id || parameters.join('_')),
    label: safeEvidenceSourceText(String(group.label || 'More options')),
    className: safeClassName(group.className, 'tool-request-field-group'),
    bodyClassName: safeClassName(group.bodyClassName, 'tool-request-field-group-body'),
    collapsed: group.collapsed !== false,
    parameters
  };
}

function safeClassName(value, fallback) {
  const classes = String(value || '')
    .split(/\s+/)
    .map((item) => item.trim())
    .filter((item) => /^[a-zA-Z][a-zA-Z0-9_-]*$/.test(item));
  return classes.length ? classes.join(' ') : fallback;
}

function controlOptions(value) {
  return array(value)
    .map((option) => {
      const item = object(option);
      const rawValue = Object.prototype.hasOwnProperty.call(item, 'value') ? item.value : option;
      const optionValue = String(rawValue ?? '').trim();
      if (!optionValue) return null;
      return {
        value: optionValue,
        label: safeEvidenceSourceText(String(item.label || optionValue))
      };
    })
    .filter(Boolean);
}

function normalizedCondition(value) {
  const condition = object(value);
  const parameter = String(condition.parameter || '').trim();
  if (!parameter) return null;
  if (Object.prototype.hasOwnProperty.call(condition, 'equals')) {
    return { parameter, equals: condition.equals };
  }
  if (array(condition.in).length) {
    return { parameter, in: array(condition.in) };
  }
  return null;
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function array(value) {
  return Array.isArray(value) ? value : [];
}

function safeEvidenceSourceText(value) {
  return String(value || '')
    .replace(SENSITIVE_PATH_FIELD_PATTERN, (_match, _quote, key) => key.replace(/_/g, ' ') + ': [redacted local path]')
    .replace(LOCAL_PATH_PATTERN, '[redacted local path]');
}
