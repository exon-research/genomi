import { compactLine, formatShort } from './portal_format.js';
import { nodeContext, selectedDomNodes, selectedEvidencePayload } from './portal_selected_evidence.js';

const GENOME_CONTEXT_LABEL = 'Active genome';

export function genomeContextViewModel(payload) {
  const envelope = contextEnvelope(payload);
  const context = object(envelope.context);
  const agi = object(context.active_genome_index);
  const readiness = object(agi.active_genome_index_readiness);
  const access = object(context.active_genome_index_access);
  const registry = object(context.active_genome_index_registry);
  const axes = object(context.context_axes);
  const agiAxis = object(axes.active_genome_index);
  const agiState = deriveAgiState(context, access, readiness, agiAxis);
  const identity = activeGenomeIdentity(agi, registry, readiness);
  const accessBadge = context.has_active_genome_index
    ? (access.approved ? 'Selected for this workspace' : 'Not selected')
    : '';
  return {
    title: agiState.title,
    subtitle: context.error || agiState.summary || identity.subtitle || context.status || 'Genomi genome index',
    identity,
    status: agiState.status,
    canAttach: false,
    actionHint: agiState.actionHint,
    promptIntro: agiState.promptIntro,
    badges: [
      agiState.badge,
      accessBadge
    ].filter(Boolean).map((value) => String(value)),
    metrics: [
      metric('Build', agi.genome_build),
      metric('Source', identity.sourceLabel),
      metric('Known genomes', registry.known_agi_count)
    ].filter(Boolean),
    sections: [
      section('Current genome', [
        node('Name', identity.displayName),
        node('Build', agi.genome_build),
        node('Source', identity.sourceLabel),
        node('Workspace use', privacyAccessLabel(access, context))
      ]),
      section('Available genomes', [
        node('Known genomes', registry.known_agi_count),
        node('Known profiles', registry.known_user_count)
      ]),
      section('Privacy boundary', [
        node('This workspace', privacyAccessLabel(access, context)),
        node('Other workspaces', privacyReuseLabel())
      ])
    ].filter((item) => item.nodes.length)
  };
}

export function genomeContextPayload(payload, options = {}) {
  const model = genomeContextViewModel(payload);
  return selectedEvidencePayload({
    contextKind: 'genome_context',
    label: GENOME_CONTEXT_LABEL + ': ' + model.title,
    summary: model.subtitle,
    sourceOperation: options.sourceOperation || 'genomi.describe_context',
    toolCallId: options.toolCallId,
    toolResultId: options.toolResultId,
    selectedNodes: model.sections.flatMap((sectionModel) => sectionModel.nodes.map((item) => ({
      label: sectionModel.title + ' / ' + item.label,
      text: GENOME_CONTEXT_LABEL + ' / ' + sectionModel.title + ' / ' + item.label + ': ' + formatContextNodeValue(item.value),
      value: item.summary
    }))),
    promptIntro: model.promptIntro + ': ' + model.title
  });
}

export function genomeContextPayloadForSelection(payload, root, options = {}) {
  const selectedNodes = root ? selectedDomNodes(root, '.genome-context-node.selected') : [];
  if (!selectedNodes.length) return genomeContextPayload(payload, options);
  const model = genomeContextViewModel(payload);
  return selectedEvidencePayload({
    contextKind: 'genome_context',
    label: GENOME_CONTEXT_LABEL + ': ' + model.title,
    summary: model.subtitle,
    sourceOperation: options.sourceOperation || 'genomi.describe_context',
    toolCallId: options.toolCallId,
    toolResultId: options.toolResultId,
    selectedNodes,
    promptIntro: model.promptIntro + ' facts: ' + model.title
  });
}

export function renderGenomeContext(container, payload, options = {}) {
  if (!container) return;
  const model = genomeContextViewModel(payload || {});
  container.innerHTML = '';
  const panel = document.createElement('div');
  panel.className = 'genome-context-card ' + model.status;
  panel.innerHTML = [
    '<div class="genome-context-head">',
    '<div><span></span><strong></strong><p></p></div>',
    '<div class="genome-context-badges"></div>',
    '</div>',
    '<div class="genome-context-actions"></div>',
    '<div class="genome-context-metrics"></div>',
    '<div class="genome-context-sections"></div>'
  ].join('');
  panel.querySelector('.genome-context-head span').textContent = GENOME_CONTEXT_LABEL;
  panel.querySelector('.genome-context-head strong').textContent = model.title;
  panel.querySelector('.genome-context-head p').textContent = model.subtitle;
  const badges = panel.querySelector('.genome-context-badges');
  model.badges.forEach((badge) => badges.appendChild(badgeEl(badge)));
  const actions = panel.querySelector('.genome-context-actions');
  if (options.actions === false) {
    actions.remove();
  } else if (!model.canAttach && model.status !== 'ready') {
    actions.appendChild(actionHint(model.actionHint || model.subtitle));
  } else {
    actions.hidden = true;
  }
  const metrics = panel.querySelector('.genome-context-metrics');
  model.metrics.forEach((item) => metrics.appendChild(metricEl(item)));
  const sections = panel.querySelector('.genome-context-sections');
  model.sections.forEach((sectionModel) => sections.appendChild(sectionEl(sectionModel, { selectable: model.canAttach })));
  container.appendChild(panel);
}

function section(title, nodes) {
  return { title, nodes: nodes.filter(Boolean) };
}

function node(label, value) {
  if (value === null || value === undefined || value === '') return null;
  return { label, value, summary: formatShort(value) };
}

function booleanNode(label, value) {
  if (typeof value !== 'boolean') return null;
  return node(label, value ? 'yes' : 'no');
}

function metric(label, value) {
  if (value === null || value === undefined || value === '') return null;
  return { label, value };
}

function privacyAccessLabel(access, context) {
  if (!context || !context.has_active_genome_index) return 'No genome selected';
  if (access && access.approved) return 'Selected for this workspace';
  return 'Choose a genome before use';
}

function privacyReuseLabel() {
  return 'Not shared automatically';
}

function actionHint(text) {
  const el = document.createElement('p');
  el.className = 'genome-context-action-hint';
  el.textContent = text || 'Active genome cannot be included yet.';
  return el;
}

function badgeEl(label) {
  const el = document.createElement('span');
  el.textContent = compactLine(label, 48);
  return el;
}

function metricEl(item) {
  const el = document.createElement('div');
  el.className = 'genome-context-metric';
  el.innerHTML = '<span></span><strong></strong>';
  el.querySelector('span').textContent = item.label;
  el.querySelector('strong').textContent = compactLine(formatShort(item.value), 64);
  return el;
}

function sectionEl(sectionModel, options = {}) {
  const el = document.createElement('div');
  el.className = 'genome-context-section';
  el.innerHTML = '<div class="genome-context-title"></div><div class="genome-context-nodes"></div>';
  el.querySelector('.genome-context-title').textContent = sectionModel.title;
  const nodes = el.querySelector('.genome-context-nodes');
  sectionModel.nodes.forEach((item) => nodes.appendChild(options.selectable ? nodeButton(sectionModel.title, item) : nodeRow(item)));
  return el;
}

function nodeRow(item) {
  const row = document.createElement('div');
  row.className = 'genome-context-node';
  row.innerHTML = '<span></span><strong></strong>';
  row.querySelector('span').textContent = compactLine(item.label, 52);
  row.querySelector('strong').textContent = compactLine(item.summary, 140);
  return row;
}

function nodeButton(sectionTitle, item) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'genome-context-node evidence-node';
  button.dataset.label = sectionTitle + ' / ' + item.label;
  button.dataset.context = nodeContext(GENOME_CONTEXT_LABEL + ' / ' + sectionTitle + ' / ' + item.label, item.value);
  button.dataset.value = item.summary;
  button.innerHTML = '<span></span><strong></strong>';
  button.querySelector('span').textContent = compactLine(item.label, 52);
  button.querySelector('strong').textContent = compactLine(item.summary, 140);
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    button.classList.toggle('selected');
  });
  return button;
}

function formatContextNodeValue(value) {
  return typeof value === 'string' ? value : formatShort(value);
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function deriveAgiState(context, access, readiness, agiAxis) {
  const axisState = String(agiAxis.current_state || '').trim();
  const axisSummary = readableAgiAxisSummary(axisState);
  const hasAgi = Boolean(context.has_active_genome_index);
  const approved = Boolean(access.approved);
  if (!hasAgi) {
    return {
      status: 'empty',
      title: 'Choose a genome',
      badge: '',
      summary: axisSummary || 'No genome is selected for this workspace',
      actionHint: 'Choose one of the available genomes or add a new genome.',
      promptIntro: 'Selected active genome'
    };
  }
  if (!approved || /approval|required|blocked/i.test(axisState)) {
    return {
      status: 'blocked',
      title: 'Choose this genome for the workspace',
      badge: '',
      summary: axisSummary || 'Select the genome for this workspace before sample-specific data is used',
      actionHint: 'Choose the genome from Available genomes.',
      promptIntro: 'Selected active genome boundary'
    };
  }
  return {
    status: 'ready',
    title: readyGenomeTitle(context, agiAxis, readiness),
    badge: '',
    summary: readyGenomeSummary(context, agiAxis, readiness, axisSummary),
    actionHint: '',
    promptIntro: 'Selected active genome'
  };
}

function activeGenomeIdentity(agi, registry, readiness) {
  const displayName = firstText(agi.display_name, agi.nickname, agi.sample_slug);
  const build = firstText(agi.genome_build);
  const source = firstText(agi.source_format, agi.source_type, agi.source_provider);
  const sourceLabel = sourceDisplayLabel(source);
  const parts = [build, sourceLabel].filter(Boolean);
  const shortId = shortIdentifier(firstText(agi.agi_id));
  return {
    displayName,
    build,
    sourceLabel,
    readinessLabel: '',
    shortId,
    summaryLabel: parts.join(' · '),
    subtitle: [
      displayName ? 'Active genome: ' + displayName : '',
      parts.join(' · '),
      registry.known_agi_count ? String(registry.known_agi_count) + ' known genome' + (Number(registry.known_agi_count) === 1 ? '' : 's') : ''
    ].filter(Boolean).join(' · ')
  };
}

function readyGenomeTitle(context, agiAxis, readiness) {
  const agi = object(context.active_genome_index);
  const registry = object(context.active_genome_index_registry);
  const identity = activeGenomeIdentity(agi, registry, readiness);
  const name = identity.displayName;
  const summary = identity.summaryLabel;
  if (name && summary) return name + ' · ' + summary;
  if (summary) return summary + ' genome';
  if (name) return name + ' genome';
  if (agiAxis && agiAxis.known_agis) return String(agiAxis.known_agis) + ' genomes available';
  return 'Active genome';
}

function readyGenomeSummary(context, agiAxis, readiness, axisSummary = '') {
  const agi = object(context.active_genome_index);
  const registry = object(context.active_genome_index_registry);
  const identity = activeGenomeIdentity(agi, registry, readiness);
  if (identity.subtitle) return identity.subtitle;
  if (axisSummary) return axisSummary;
  if (agiAxis && agiAxis.known_agis) {
    return String(agiAxis.known_agis) + ' genome' + (Number(agiAxis.known_agis) === 1 ? '' : 's') + ' available';
  }
  return 'Open Active genome to switch or add genomes';
}

function sourceDisplayLabel(value) {
  const original = firstText(value);
  const clean = original.toLowerCase().replace(/[\s_-]+/g, '');
  if (!clean) return '';
  if (clean === 'vcf') return 'VCF';
  if (clean === 'gvcf') return 'gVCF';
  if (clean === '23andme') return '23andMe';
  if (clean === 'genome') return 'Genome bundle';
  if (clean === 'localpath') return 'Local source';
  return original.replace(/_/g, ' ');
}

function shortIdentifier(value) {
  const clean = firstText(value);
  if (!clean) return '';
  return clean.length > 14 ? clean.slice(0, 10) + '...' : clean;
}

function firstText(...values) {
  for (const value of values) {
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return '';
}

function readableAgiAxisSummary(value) {
  switch (String(value || '').trim()) {
    case 'active_accessible':
      return 'Selected for this workspace';
    case 'approval_required':
    case 'access_blocked':
      return 'Choose the genome for this workspace before sample-specific data is used';
    case 'parsing':
    case 'active_incomplete':
    case 'pending':
      return 'Genome is selected for this workspace';
    case 'none':
    case 'no_active_genome_index':
      return 'No genome is selected for this workspace';
    default:
      return '';
  }
}

export function genomeContextResultViewModel(payload, operation = 'genomi.describe_context') {
  const context = genomeContextViewModel(payload);
  return {
    kind: 'context',
    operation,
    kicker: GENOME_CONTEXT_LABEL,
    title: context.title,
    summary: context.subtitle,
    metrics: context.metrics,
    lanes: context.sections.map((sectionModel) => ({
      title: sectionModel.title,
      nodes: sectionModel.nodes.map((item) => ({
        label: item.label,
        summary: item.summary,
        value: item.value,
        context: nodeContext(GENOME_CONTEXT_LABEL + ' / ' + sectionModel.title + ' / ' + item.label, item.value)
      }))
    }))
  };
}

function contextEnvelope(value) {
  const payload = object(value);
  const nested = object(payload.context);
  if (nested.context || nested.mcp || nested.genomiVersion) {
    return { context: object(nested.context), mcp: object(nested.mcp) };
  }
  if (payload.context || payload.mcp || payload.genomiVersion) {
    return { context: nested, mcp: object(payload.mcp) };
  }
  return { context: payload, mcp: {} };
}
