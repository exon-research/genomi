import { compactLine, titleCase } from './portal_format.js';
import { renderToolRequestBuilder } from './portal_tool_request_builder.js';
import { toolRequestBuilderModel } from './portal_tool_request_model.js';

const LOCAL_PATH_PATTERN = /(?:~|\/Users|\/home|\/tmp|\/private\/tmp|\/var\/folders|\/opt\/homebrew|\/usr\/local|\/Applications|\/Volumes)(?:\/[^\s"'<>),;:]+)*/g;
const SENSITIVE_PATH_FIELD_PATTERN = /(["']?)(context_file|registry_file|agi_path)\1\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^,\s}\]]+)/gi;

export { toolRequestBuilderModel };

export function visibleTools(tools) {
  return (Array.isArray(tools) ? tools : []).filter((tool) => tool && object(tool.sourceLookup).operationId);
}

export function renderToolCatalog(container, tools, options = {}) {
  if (!container) return;
  const shown = Array.isArray(tools) ? tools : [];
  if (!shown.length) {
    container.innerHTML = '<div class="tool-launcher-empty">No evidence sources available.</div>';
    return;
  }
  container.innerHTML = '';
  Object.entries(groupToolsByArea(shown)).forEach(([area, areaTools]) => {
    const section = document.createElement('section');
    section.className = 'tool-launcher-section';
    const heading = document.createElement('div');
    heading.className = 'tool-launcher-heading';
    heading.innerHTML = '<strong></strong><span></span>';
    heading.querySelector('strong').textContent = areaLabel(area);
    heading.querySelector('span').textContent = areaTools.length + ' evidence source' + (areaTools.length === 1 ? '' : 's');
    section.appendChild(heading);
    const rows = document.createElement('div');
    rows.className = 'tool-launcher-rows';
    areaTools.forEach((tool) => rows.appendChild(toolLauncherRow(tool, options)));
    section.appendChild(rows);
    container.appendChild(section);
  });
}

export function renderToolCatalogStatus(container, status, message = '') {
  if (!container) return;
  const label = status === 'error'
    ? 'Evidence source catalog unavailable'
    : status === 'loading'
      ? 'Loading evidence sources...'
      : status === 'idle'
        ? 'Evidence sources'
        : 'No evidence sources available.';
  const detail = message || (status === 'error'
    ? 'Refresh the portal or check the local Genomi server.'
    : status === 'idle'
      ? 'Choose an evidence source to use in chat.'
      : '');
  container.innerHTML = '';
  const empty = document.createElement('div');
  empty.className = 'tool-launcher-empty';
  empty.innerHTML = '<strong></strong><span></span>';
  empty.querySelector('strong').textContent = label;
  empty.querySelector('span').textContent = detail;
  container.appendChild(empty);
}

export function renderToolInspector(container, tool, options = {}) {
  if (!container) return;
  container.innerHTML = '';
  if (!tool) {
    const empty = document.createElement('div');
    empty.className = 'tool-inspector-empty';
    empty.innerHTML = '<strong>Choose an evidence source</strong><span>Use public or approved genome material in chat.</span>';
    container.appendChild(empty);
    return;
  }
  const model = toolInspectorModel(tool);
  const panel = document.createElement('div');
  panel.className = 'tool-inspector-card';
  panel.innerHTML = [
    '<div class="tool-inspector-head">',
    '<div><span></span><strong></strong><p></p></div>',
    '<div class="tool-inspector-badges"></div>',
    '</div>',
    '<div class="tool-inspector-actions"></div>',
    '<div class="tool-inspector-sections"></div>'
  ].join('');
  panel.querySelector('.tool-inspector-head span').textContent = model.area;
  panel.querySelector('.tool-inspector-head strong').textContent = model.displayLabel;
  panel.querySelector('.tool-inspector-head p').textContent = model.description || 'Genomi evidence source';
  const badges = panel.querySelector('.tool-inspector-badges');
  model.badges.forEach((badge) => badges.appendChild(toolBadge(badge)));
  const sections = panel.querySelector('.tool-inspector-sections');
  const requestBuilder = renderToolRequestBuilder(tool, options);
  const actions = panel.querySelector('.tool-inspector-actions');
  if (!requestBuilder) {
    actions.appendChild(actionButton('Include source', () => {
      if (typeof options.onAttachRequest === 'function') options.onAttachRequest(tool, {});
    }));
  }
  if (requestBuilder) {
    const requestBuilderTitle = requestBuilder.querySelector('.tool-request-builder-head strong');
    if (requestBuilderTitle) requestBuilderTitle.textContent = model.displayLabel;
    sections.appendChild(requestBuilder);
  }
  model.sections
    .filter((section) => !requestBuilder || section.title !== 'Inputs')
    .forEach((section) => sections.appendChild(toolSection(section)));
  const technical = technicalDisclosure(model.technicalSections);
  if (technical) sections.appendChild(technical);
  container.appendChild(panel);
}

export function toolInspectorModel(tool) {
  const operationId = String(tool && tool.name || 'tool');
  const sourceLookup = object(tool && tool.sourceLookup);
  if (sourceLookup.operationId || sourceLookup.displayLabel) {
    const request = object(sourceLookup.request);
    const requestFields = array(request.fields).map((field) => object(field)).filter((field) => field.name || field.id);
    const requiredInputs = array(request.requiredInputs).map(String).filter(Boolean);
    const sections = normalizeSections(sourceLookup.sections);
    const technicalSections = normalizeSections(sourceLookup.technicalSections);
    const defaults = sectionNodes(technicalSections, 'Default assumptions if omitted');
    const dependencyRows = sectionNodes(technicalSections, 'Dependencies');
    return {
      name: String(sourceLookup.name || sourceLookup.operationId || operationId),
      operationId: String(sourceLookup.operationId || sourceLookup.name || operationId),
      displayLabel: safeEvidenceSourceText(String(sourceLookup.displayLabel || sourceLookup.operationId || operationId)),
      area: areaLabel(sourceLookup.area || object(tool && tool.annotations).area || 'workspace'),
      description: compactLine(safeEvidenceSourceText(String(sourceLookup.description || tool && tool.description || '')), 360),
      requiredInputs,
      requestFields,
      defaults,
      produces: [],
      dependencyRows,
      dependencies: dependencyRows.map((item) => item.label + ': ' + item.value),
      badges: array(sourceLookup.badges).map(String).filter(Boolean),
      sections,
      technicalSections
    };
  }
  return {
    name: operationId,
    operationId,
    displayLabel: operationId,
    area: areaLabel('workspace'),
    description: '',
    requiredInputs: [],
    requestFields: [],
    defaults: [],
    produces: [],
    dependencyRows: [],
    dependencies: [],
    badges: [],
    sections: [],
    technicalSections: []
  };
}

function toolLauncherRow(tool, options) {
  const model = toolInspectorModel(tool);
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'tool-launcher-row' + (tool.name === options.activeToolName ? ' active' : '');
  button.innerHTML = '<span><strong></strong><small></small></span><em></em>';
  button.querySelector('strong').textContent = model.displayLabel;
  button.querySelector('small').textContent = toolSummary(tool);
  button.querySelector('em').textContent = tool.name === options.activeToolName ? 'Selected' : 'Choose';
  button.addEventListener('click', () => {
    if (typeof options.onSelectTool === 'function') options.onSelectTool(tool);
  });
  return button;
}

function groupToolsByArea(tools) {
  return tools.reduce((groups, tool) => {
    const area = toolInspectorModel(tool).area || areaLabel((tool.annotations && tool.annotations.area) || 'workspace');
    if (!groups[area]) groups[area] = [];
    groups[area].push(tool);
    return groups;
  }, {});
}

function toolSummary(tool) {
  const sourceLookup = object(tool && tool.sourceLookup);
  if (sourceLookup.description) return compactLine(safeEvidenceSourceText(String(sourceLookup.description)), 180);
  const description = String(tool && tool.description || '').replace(/\s+/g, ' ').trim();
  return safeEvidenceSourceText(description || 'Choose a focused evidence source');
}

function areaLabel(area) {
  return titleCase(String(area || 'workspace'));
}

function normalizeSections(value) {
  return array(value)
    .map((section) => {
      const model = object(section);
      const title = safeEvidenceSourceText(String(model.title || '')).trim();
      const nodes = array(model.nodes)
        .map((node) => {
          const item = object(node);
          return {
            label: safeEvidenceSourceText(String(item.label || '')).trim(),
            value: safeEvidenceSourceText(String(item.value || '')).trim()
          };
        })
        .filter((node) => node.label && node.value);
      return title && nodes.length ? { title, nodes } : null;
    })
    .filter(Boolean);
}

function sectionNodes(sections, title) {
  const section = array(sections).find((item) => item && item.title === title);
  return section ? array(section.nodes) : [];
}

function safeEvidenceSourceText(value) {
  return String(value || '')
    .replace(SENSITIVE_PATH_FIELD_PATTERN, (_match, _quote, key) => key.replace(/_/g, ' ') + ': [redacted local path]')
    .replace(LOCAL_PATH_PATTERN, '[redacted local path]');
}

function toolSection(section) {
  const el = document.createElement('div');
  el.className = 'tool-inspector-section';
  el.innerHTML = '<div class="tool-inspector-section-title"></div><div class="tool-inspector-nodes"></div>';
  el.querySelector('.tool-inspector-section-title').textContent = section.title;
  const nodes = el.querySelector('.tool-inspector-nodes');
  section.nodes.forEach((node) => nodes.appendChild(toolNode(node)));
  return el;
}

function technicalDisclosure(sections) {
  const visibleSections = array(sections).filter((section) => section && Array.isArray(section.nodes) && section.nodes.length);
  if (!visibleSections.length) return null;
  const details = document.createElement('details');
  details.className = 'tool-inspector-technical';
  details.innerHTML = '<summary>Technical disclosure</summary><div class="tool-inspector-technical-sections"></div>';
  const body = details.querySelector('.tool-inspector-technical-sections');
  visibleSections.forEach((section) => body.appendChild(toolSection(section)));
  return details;
}

function toolNode(node) {
  const el = document.createElement('div');
  el.className = 'tool-inspector-node';
  el.innerHTML = '<span></span><strong></strong>';
  el.querySelector('span').textContent = compactLine(node.label, 70);
  el.querySelector('strong').textContent = compactLine(String(node.value || ''), 180);
  return el;
}

function toolBadge(label) {
  const badge = document.createElement('span');
  badge.textContent = label;
  return badge;
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

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function array(value) {
  return Array.isArray(value) ? value : [];
}
