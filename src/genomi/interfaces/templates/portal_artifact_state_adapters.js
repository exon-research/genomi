import { formatShort, titleCase } from './portal_format.js';
import { serverResultPresentationModel } from './portal_result_presentation_model.js';

const TARGET_PACKET_OPERATION = 'research.build_target_packet';

export function artifactStateModel(artifact) {
  if (!artifact || typeof artifact !== 'object') return null;
  const renderer = String(artifact.renderer || '');
  const kind = String(artifact.kind || '');
  const adapter = ARTIFACT_STATE_ADAPTERS[renderer] || ARTIFACT_STATE_ADAPTERS[kind];
  return adapter ? adapter(artifact) : null;
}

function reportSectionStateModel(artifact) {
  if (!artifact || typeof artifact !== 'object') return null;
  const summary = object(artifact.summary);
  const evidenceBuild = object(summary.evidence_build);
  const sections = [
    sectionGroup('Rendered sections', summary.panels_rendered),
    sectionGroup('Ready sections', evidenceBuild.panels_ready),
    sectionGroup('Empty sections', firstNonEmpty(summary.panels_empty, evidenceBuild.panels_empty)),
    sectionGroup('Blocked sections', evidenceBuild.panels_blocked),
    sectionGroup('Running sections', evidenceBuild.panels_running),
    sectionGroup('Failed sections', evidenceBuild.panels_failed),
    stateSection(evidenceBuild.panel_states)
  ].filter(Boolean);
  if (!sections.length) return null;
  const rendered = sectionCount(summary.panels_rendered);
  const empty = sectionCount(firstNonEmpty(summary.panels_empty, evidenceBuild.panels_empty));
  const blocked = sectionCount(evidenceBuild.panels_blocked);
  return {
    title: 'Report section state',
    metrics: [
      metric('Status', artifact.status),
      metric('Rendered', rendered),
      metric('Empty', empty),
      metric('Blocked', blocked)
    ].filter(Boolean),
    sections
  };
}

function evidencePacketStateModel(artifact) {
  if (!artifact || typeof artifact !== 'object') return null;
  const presentation = serverResultPresentationModel(artifactPortalPresentation(artifact), artifact.operation || TARGET_PACKET_OPERATION);
  if (presentation && presentation.operation === TARGET_PACKET_OPERATION) return evidencePacketPresentationStateModel(presentation);
  return null;
}

function evidencePacketPresentationStateModel(presentation) {
  const metrics = [
    metric('Target', presentation.title),
    ...array(presentation.metrics).map((item) => metric(item.label, item.value))
  ].filter(Boolean);
  const sections = array(presentation.lanes).map((lane) => ({
    title: lane.title,
    nodes: array(lane.nodes).map((item) => ({
      label: item.label,
      summary: item.summary,
      value: item.value
    }))
  })).filter((section) => section.nodes.length);
  return metrics.length || sections.length ? {
    title: 'Evidence report state',
    metrics,
    sections
  } : null;
}

function artifactPortalPresentation(artifact) {
  const summary = object(artifact.summary);
  const latestVersion = object(artifact.latest_version);
  return artifact.portal_presentation || summary.portal_presentation || latestVersion.portal_presentation || object(latestVersion.summary).portal_presentation;
}

const ARTIFACT_STATE_ADAPTERS = {
  decode_dashboard: reportSectionStateModel,
  evidence_packet: evidencePacketStateModel,
  portal_visual_fixture: reportSectionStateModel
};

function sectionGroup(title, value) {
  const nodes = sectionItems(value).map((item) => ({
    label: item.label,
    summary: item.summary,
    value: item.value
  }));
  return nodes.length ? { title, nodes } : null;
}

function stateSection(value) {
  const state = object(value);
  const nodes = Object.entries(state).map(([key, child]) => ({
    label: titleCase(key),
    summary: formatShort(child),
    value: child
  }));
  return nodes.length ? { title: 'Section states', nodes } : null;
}

function sectionItems(value) {
  if (Array.isArray(value)) {
    return value
      .filter((item) => item !== null && item !== undefined && item !== '')
      .map((item) => sectionItem(item));
  }
  if (value && typeof value === 'object') {
    return Object.entries(value)
      .filter(([, child]) => child !== null && child !== undefined && child !== '' && child !== false)
      .map(([key, child]) => sectionItem({ panel: key, state: child }));
  }
  return [];
}

function sectionItem(item) {
  if (item && typeof item === 'object' && !Array.isArray(item)) {
    const label = String(item.panel || item.name || item.id || item.kind || item.status || 'Section').trim();
    return { label: label || 'Section', summary: sectionItemSummary(item), value: item };
  }
  const label = String(item || 'Section').trim();
  return { label: label || 'Section', summary: label, value: item };
}

function sectionItemSummary(item) {
  for (const key of ['status', 'headline', 'message', 'reason', 'state', 'count']) {
    const value = item[key];
    if (value === null || value === undefined || value === '') continue;
    return formatShort(value);
  }
  return formatShort(item);
}

function firstNonEmpty(...values) {
  return values.find((value) => sectionCount(value) > 0);
}

function sectionCount(value) {
  if (Array.isArray(value)) return value.length;
  if (value && typeof value === 'object') return Object.keys(value).length;
  return 0;
}

function metric(label, value) {
  if (value === null || value === undefined || value === '' || value === false) return null;
  return { label, value };
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function array(value) {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === 'object') : [];
}
