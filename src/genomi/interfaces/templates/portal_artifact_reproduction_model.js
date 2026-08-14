import { compactLine, formatPayload, formatShort } from './portal_format.js';
import { promptSafeText } from './portal_selected_evidence.js';
import { artifactProjection } from './portal_artifact_projection.js';

const READY_STATUS = 'ready';
const PARTIAL_PRIVATE_PARAMETERS_REDACTED_STATUS = 'partial_private_parameters_redacted';
const PUBLIC_STATUSES = new Set([READY_STATUS, PARTIAL_PRIVATE_PARAMETERS_REDACTED_STATUS]);
const SENSITIVE_KEYS = new Set([
  'context_file',
  'registry_file',
  'agi_path',
  'dashboard_path',
  'shared_evidence_db',
  'path',
  'file_path',
  'result'
]);
const SENSITIVE_REPRODUCTION_FIELD_PATTERN = /(["']?)(context_file|registry_file|agi_path|dashboard_path|shared_evidence_db)\1\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^,\s}\]]+)/gi;

export function artifactReproductionModel(artifact) {
  const projection = artifactProjection(artifact || {});
  if (projection.hasUnresolvedSelectedVersion) return null;
  const display = projection.display;
  const recipe = normalizeRecipe(projection.reproduction);
  if (!recipe) return null;
  const params = recipe.params;
  const inputFidelity = recipe.params_redacted ? 'Private inputs redacted' : 'Exact public inputs';
  const sections = [
    section('Rebuild readiness', [
      node('Recipe state', statusLabel(recipe.status)),
      node('Input coverage', inputFidelity),
      node('Replay scope', 'Rebuilds the artifact from saved source inputs; does not replay the assistant reasoning turn.')
    ]),
    section('Public inputs', parameterNodes(params)),
    section('Rebuild limits', listNodes(recipe.limitations, 'Limit'))
  ].filter(Boolean);
  return {
    title: 'Rebuild recipe: ' + display.title,
    status: recipe.status,
    metrics: [
      metric('Recipe state', statusLabel(recipe.status)),
      metric('Input coverage', inputFidelity),
      metric('Inputs', Object.keys(params).length),
      metric('Limits', recipe.limitations.length)
    ].filter(Boolean),
    sections,
    codeBlocks: [],
    technical: reproductionTechnicalModel(recipe)
  };
}

function normalizeRecipe(value) {
  const recipe = object(value);
  const rawStatus = firstText(recipe.status);
  if (!PUBLIC_STATUSES.has(rawStatus)) return null;
  const paramsRedacted = recipe.params_redacted === true || rawStatus === PARTIAL_PRIVATE_PARAMETERS_REDACTED_STATUS;
  const status = paramsRedacted ? PARTIAL_PRIVATE_PARAMETERS_REDACTED_STATUS : READY_STATUS;
  const normalized = {
    status,
    kind: safeText(recipe.kind),
    artifact_family: safeText(recipe.artifact_family),
    operation: safeText(recipe.operation),
    renderer: safeText(recipe.renderer),
    params: safePublicValue(object(recipe.params)),
    params_redacted: paramsRedacted,
    host_agent: normalizeHostAgent(recipe.host_agent),
    limitations: textList(recipe.limitations),
    commands: [],
    script: ''
  };
  if (status === READY_STATUS) {
    normalized.commands = normalizeCommands(recipe.commands);
    normalized.script = safeText(recipe.script);
  }
  return normalized;
}

function normalizeCommands(value) {
  return array(value).map((item) => {
    const source = object(item);
    return {
      label: safeText(source.label),
      language: safeText(source.language),
      command: safeText(source.command),
      purpose: safeText(source.purpose)
    };
  }).filter((item) => item.command);
}

function normalizeHostAgent(value) {
  const source = object(value);
  return {
    tool: safeText(source.tool),
    params: safePublicValue(object(source.params)),
    instruction: safeText(source.instruction),
    guidance: textList(source.guidance)
  };
}

function commandNode(item, index) {
  const label = firstText(item.label, 'Command ' + (index + 1));
  const summary = firstText(item.purpose, item.language, item.command);
  return {
    label: safeText(label),
    summary: safeText(compactLine(summary || formatShort(item), 140)),
    value: compactObject(item)
  };
}

function hostAgentNodes(value) {
  return [
    node('Operation', value.tool),
    node('Parameters', object(value.params)),
    node('Instruction', value.instruction)
  ].filter(Boolean);
}

function reproductionTechnicalModel(recipe) {
  const commandItems = recipe.commands;
  const command = recipe.status === READY_STATUS ? firstText(recipe.script, commandItems[0] && commandItems[0].command) : '';
  return {
    title: 'Rebuild technical details',
    status: recipe.status,
    metrics: [
      metric('Operation', recipe.operation),
      metric('Renderer', recipe.renderer),
      metric('Commands', commandItems.length)
    ].filter(Boolean),
    sections: [
      section('Operation details', [
        node('Operation', recipe.operation),
        node('Renderer', recipe.renderer),
        node('Artifact family', recipe.artifact_family)
      ]),
      section('Operation parameters', parameterNodes(recipe.params, { technical: true })),
      section('Command recipe', commandItems.map(commandNode)),
      section('Host-agent handoff', hostAgentNodes(recipe.host_agent))
    ].filter(Boolean),
    codeBlocks: command ? [{ label: 'Technical shell recipe', language: 'shell', code: safeText(command) }] : []
  };
}

function parameterNodes(params, options = {}) {
  return Object.entries(params).map(([key, value]) => ({
    label: safeText(options.technical ? key : fieldLabel(key)),
    summary: safeText(compactLine(formatShort(value), 140)),
    value
  }));
}

function fieldLabel(name) {
  return String(name || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function statusLabel(status) {
  if (status === READY_STATUS) return 'Ready to rebuild';
  if (status === PARTIAL_PRIVATE_PARAMETERS_REDACTED_STATUS) return 'Private inputs redacted';
  return fieldLabel(status);
}

function listNodes(value, labelPrefix) {
  const items = array(value);
  return items.map((item, index) => node(labelPrefix + ' ' + (index + 1), item)).filter(Boolean);
}

function section(title, nodes) {
  const cleanNodes = Array.isArray(nodes) ? nodes.filter(Boolean) : [];
  return cleanNodes.length ? { title, nodes: cleanNodes } : null;
}

function node(label, value) {
  if (value === null || value === undefined || value === '' || value === false) return null;
  const safe = safeValue(value);
  return {
    label: safeText(label),
    summary: safeText(compactLine(formatShort(safe), 140)),
    value: safe
  };
}

function metric(label, value) {
  if (value === null || value === undefined || value === '' || value === false) return null;
  return { label, value: safeText(value) };
}

function safeValue(value) {
  if (value === null || value === undefined) return value;
  if (typeof value === 'string') return safeText(value);
  if (typeof value === 'number' || typeof value === 'boolean') return value;
  if (Array.isArray(value)) return value.map(safeValue).filter((item) => item !== null && item !== undefined && item !== '');
  if (typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([, child]) => child !== null && child !== undefined && child !== '' && child !== false)
        .filter(([key]) => !SENSITIVE_KEYS.has(String(key).toLowerCase()))
        .map(([key, child]) => [safeText(key), safeValue(child)])
    );
  }
  return safeText(String(value));
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function array(value) {
  return Array.isArray(value) ? value : [];
}

function textList(value) {
  return array(value).map(safeText).filter(Boolean);
}

function safePublicValue(value) {
  const safe = safeValue(value);
  return safe && typeof safe === 'object' && !Array.isArray(safe) ? safe : {};
}

function compactObject(value) {
  return Object.fromEntries(
    Object.entries(value || {}).filter(([, child]) => child !== null && child !== undefined && child !== '' && child !== false)
  );
}

function safeText(value) {
  return promptSafeText(String(value || '').replace(
    SENSITIVE_REPRODUCTION_FIELD_PATTERN,
    (_match, _quote, key) => key.replace(/_/g, ' ') + ': [redacted local path]'
  ));
}

function firstText(...values) {
  for (const value of values) {
    if (value === null || value === undefined) continue;
    const text = typeof value === 'string' ? value.trim() : formatPayload(value).trim();
    if (text) return text;
  }
  return '';
}
