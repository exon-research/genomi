import { compactLine, formatShort } from './portal_format.js';
import { artifactProjection } from './portal_artifact_projection.js';
import { artifactRuntimeModel } from './portal_artifact_runtime_model.js';
import { promptSafeText } from './portal_selected_evidence.js';

export function artifactEnvironmentModel(artifact) {
  const projection = artifactProjection(artifact || {});
  if (projection.hasUnresolvedSelectedVersion) return null;
  const display = projection.display;
  const environment = projection.environment;
  if (!environment.kind) return null;
  const runtime = object(environment.runtime);
  const libraries = object(environment.libraries);
  const librarySummary = object(libraries.summary);
  const packageRows = array(environment.packages).map(packageNode).filter(Boolean);
  const libraryRows = array(libraries.items).map(libraryNode).filter(Boolean);
  const limitations = array(environment.limitations).filter(Boolean);
  const pythonLabel = [runtime.python_implementation, runtime.python_version].filter(Boolean).join(' ');
  const libraryStatus = environmentLibraryStatus(librarySummary);
  const sourceDetails = artifactRuntimeModel(artifact);
  const sourceCount = metricValue(sourceDetails, 'Sources') || librarySummary.library_count;
  const defaultCount = metricValue(sourceDetails, 'Defaults');
  const metrics = [
    metric('Source status', libraryStatusMetric(librarySummary, libraryStatus)),
    metric('Sources', sourceCount),
    metric('Missing sources', librarySummary.missing_count),
    metric('Manual sources', librarySummary.manual_source_required_count),
    metric('Defaults', defaultCount)
  ].filter(Boolean);
  const sections = [
    ...sourceLimitSections(sourceDetails),
    section('Source inventory', [
      node('Inventory status', libraryStatusMetric(librarySummary, libraryStatus)),
      node('Inventory issue', librarySummary.error),
      node('Known sources', librarySummary.library_count),
      node('Available sources', librarySummary.installed_count),
      node('Missing sources', librarySummary.missing_count),
      node('Requires manual setup', librarySummary.manual_source_required_count),
      node('Not applicable', librarySummary.not_applicable_count)
    ]),
    section('Artifact context', [
      node('Artifact', display.title),
      node('Family', artifactFamilyLabel(display)),
      node('Category', artifactCategoryLabel(display)),
      node('Status', display.status)
    ]),
    section('Source snapshot limits', limitations.map((item, index) => node('Limit ' + (index + 1), item)))
  ].filter(Boolean);
  const technical = {
    title: 'Environment technical details: ' + display.title,
    metrics: [
      metric('Python', pythonLabel),
      metric('Packages', packageRows.length),
      metric('Library rows', libraryRows.length)
    ].filter(Boolean),
    sections: [
      section('Software environment', [
        node('Python version', runtime.python_version),
        node('Python implementation', runtime.python_implementation),
        node('System', runtime.system),
        node('Machine', runtime.machine)
      ]),
      section('Python packages', packageRows),
      section('Genomi libraries', [
        node('Inventory status', libraryStatusMetric(librarySummary, libraryStatus)),
        node('Inventory issue', librarySummary.error),
        ...libraryRows
      ]),
      section('Snapshot mechanics', [
        node('Operation', environment.operation),
        node('Renderer', environment.renderer),
        node('Result kind', environment.artifact_kind),
        node('Generated', environment.generated_at)
      ])
    ].filter(Boolean)
  };
  return metrics.length || sections.length ? {
    title: 'Source limits: ' + display.title,
    status: libraryStatus,
    metrics,
    sections,
    technical
  } : null;
}

function sourceLimitSections(sourceDetails) {
  const byTitle = new Map(array(sourceDetails && sourceDetails.sections).map((sectionModel) => [sectionModel && sectionModel.title, sectionModel]));
  return ['Source coverage', 'Interpretation boundary', 'Defaults applied']
    .map((title) => byTitle.get(title))
    .filter(Boolean)
    .map((sectionModel) => section(sectionModel.title, array(sectionModel.nodes).map(cloneNode)))
    .filter(Boolean);
}

function cloneNode(item) {
  if (!item || typeof item !== 'object') return null;
  const value = item.value !== undefined ? safeValue(item.value) : safeValue(item.summary);
  const summary = firstText(item.summary, formatShort(value));
  if (!item.label || !summary) return null;
  return { label: promptSafeText(item.label), summary: promptSafeText(summary), value };
}

function packageNode(item) {
  const pkg = object(item);
  const label = firstText(pkg.name);
  if (!label) return null;
  return {
    label: promptSafeText(label),
    summary: promptSafeText(compactLine([pkg.version, pkg.status].filter(Boolean).join(' · '), 140)),
    value: safeValue(pkg)
  };
}

function libraryNode(item) {
  const library = object(item);
  const label = firstText(library.library, library.title, 'library');
  const title = firstText(library.title);
  const displayLabel = [label, title && title !== label ? title : ''].filter(Boolean).join(' · ');
  return {
    label: promptSafeText(displayLabel),
    summary: promptSafeText(compactLine([library.status, library.kind, library.size_class].filter(Boolean).join(' · '), 160)),
    value: safeValue(library)
  };
}

function section(title, nodes) {
  const cleanNodes = Array.isArray(nodes) ? nodes.filter(Boolean) : [];
  return cleanNodes.length ? { title, nodes: cleanNodes } : null;
}

function node(label, value) {
  if (value === null || value === undefined || value === '' || value === false) return null;
  const safe = safeValue(value);
  return { label: promptSafeText(label), summary: promptSafeText(formatShort(safe)), value: safe };
}

function metric(label, value) {
  if (value === null || value === undefined || value === '' || value === false) return null;
  return { label, value };
}

function metricValue(model, label) {
  const metrics = array(model && model.metrics);
  const item = metrics.find((candidate) => candidate && candidate.label === label);
  if (!item) return null;
  const value = item.value;
  return value === null || value === undefined || value === '' || value === false ? null : value;
}

function environmentLibraryStatus(librarySummary) {
  const status = firstText(librarySummary.status).toLowerCase();
  const error = firstText(librarySummary.error);
  if (status) return normalizeEnvironmentStatus(status);
  if (error) return 'error';
  return numberValue(librarySummary.missing_count) ? 'partial' : 'ready';
}

function normalizeEnvironmentStatus(status) {
  if (status.includes('error') || status.includes('fail')) return 'error';
  if (status.includes('unavailable')) return 'unavailable';
  if (status.includes('partial')) return 'partial';
  if (['ready', 'ok', 'available', 'complete', 'completed'].includes(status)) return 'ready';
  return promptSafeText(status.replace(/_/g, ' '));
}

function libraryStatusMetric(librarySummary, libraryStatus) {
  return statusLabel(firstText(librarySummary.status, libraryStatus));
}

function artifactFamilyLabel(display) {
  if (display.family === 'evidence_report') return 'Evidence report';
  if (display.family === 'legacy_report') return 'Report';
  return 'Artifact';
}

function artifactCategoryLabel(display) {
  if (display.category === 'evidence') return 'Evidence';
  if (display.category === 'report') return 'Report';
  if (display.category === 'other') return 'Other artifact';
  return statusLabel(display.category);
}

function numberValue(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function statusLabel(value) {
  const text = firstText(value);
  return text ? promptSafeText(text.replace(/_/g, ' ')) : '';
}

function safeValue(value) {
  if (value === null || value === undefined) return value;
  if (typeof value === 'string') return promptSafeText(value);
  if (typeof value === 'number' || typeof value === 'boolean') return value;
  if (Array.isArray(value)) {
    return value
      .map((child) => safeValue(child))
      .filter((child) => child !== null && child !== undefined && child !== '');
  }
  if (typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([, child]) => child !== null && child !== undefined && child !== '')
        .map(([key, child]) => [promptSafeText(key), safeValue(child)])
    );
  }
  return promptSafeText(String(value));
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function array(value) {
  return Array.isArray(value) ? value : [];
}

function firstText(...values) {
  for (const value of values) {
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return '';
}
