import { formatShort } from './portal_format.js';
import { operationDisplayLabel } from './portal_operation_labels.js';

export function artifactDisplayModel(artifact) {
  const rawArtifact = artifact || {};
  const versions = artifactVersions(rawArtifact);
  const requestedSelectedVersionId = firstText(rawArtifact.selected_version_id, rawArtifact.selectedVersionId);
  const selectedVersion = selectedArtifactVersion(rawArtifact, versions, requestedSelectedVersionId);
  const latestVersion = latestArtifactVersion(rawArtifact, versions);
  const latestVersionId = firstText(rawArtifact.latest_version_id, latestVersion && latestVersion.version_id);
  const selectedVersionId = firstText(selectedVersion && selectedVersion.version_id);
  const unresolvedSelectedVersionId = requestedSelectedVersionId && !selectedVersionId ? requestedSelectedVersionId : '';
  const effectiveVersion = selectedVersion || latestVersion;
  const effectiveVersionId = firstText(selectedVersionId, latestVersionId, effectiveVersion && effectiveVersion.version_id);
  const latestVersionFileUrl = artifactVersionFilePath(latestVersion || latestVersionId, rawArtifact);
  const selectedVersionFileUrl = artifactVersionFilePath(selectedVersion, rawArtifact);
  const effectiveVersionFileUrl = firstText(
    artifactVersionFilePath(effectiveVersion, rawArtifact),
    selectedVersionId ? selectedVersionFileUrl : '',
    latestVersionFileUrl
  );
  const previewUrl = firstText(effectiveVersionFileUrl, rawArtifact.preview_url);
  const artifactUrl = firstText(effectiveVersionFileUrl, rawArtifact.url, rawArtifact.preview_url);
  const presentation = artifactPresentationModel(rawArtifact);
  const summaryLines = Array.isArray(rawArtifact.summary_lines) && rawArtifact.summary_lines.length
    ? rawArtifact.summary_lines.map((line) => artifactSummaryLine(line, presentation)).filter(Boolean)
    : fallbackSummaryLines(rawArtifact, presentation);
  const title = artifactTitle(rawArtifact, presentation);
  return {
    id: rawArtifact.id || '',
    projectId: rawArtifact.project_id || rawArtifact.projectId || '',
    title,
    family: presentation.family,
    category: presentation.category,
    kind: rawArtifact.kind || '',
    renderer: rawArtifact.renderer || '',
    operation: rawArtifact.operation || '',
    status: rawArtifact.status || '',
    presentation,
    starred: rawArtifact.starred === true,
    hidden: rawArtifact.hidden === true,
    createdAt: rawArtifact.created_at || '',
    updatedAt: rawArtifact.updated_at || '',
    meta: summaryLines.join(' · '),
    url: firstText(effectiveVersionFileUrl, rawArtifact.url),
    artifactUrl,
    previewUrl,
    openLabel: artifactOpenLabel(rawArtifact, presentation),
    latestVersionId,
    latestVersionFileUrl,
    requestedSelectedVersionId,
    selectedVersionId,
    selectedVersionFileUrl,
    resolvedSelectedVersionId: selectedVersionId,
    unresolvedSelectedVersionId,
    effectiveVersionId,
    effectiveVersionFileUrl,
    versionCount: rawArtifact.version_count ?? (versions.length ? versions.length : ''),
    versionsLoaded: rawArtifact.versions_loaded === true,
    versions,
    latestVersion,
    selectedVersion,
    resolvedSelectedVersion: selectedVersion,
    effectiveVersion
  };
}

export function artifactSurfaceCopy(value = {}) {
  const presentation = artifactPresentationFromValue(value);
  const copy = serverSurfaceCopy(presentation.surfaceCopy || presentation.surface_copy);
  if (Object.keys(copy).length) return completeSurfaceCopy(copy);
  return legacySurfaceCopyFallback(presentation.family);
}

function completeSurfaceCopy(copy) {
  const noun = firstText(copy.noun, 'result');
  const selectedItem = firstText(copy.selectedItem, noun + ' item');
  const selectedItems = firstText(copy.selectedItems, selectedItem + 's');
  const labelPrefix = firstText(copy.labelPrefix, titleCase(noun));
  const promptIntroPrefix = firstText(copy.promptIntroPrefix, 'Selected ' + noun);
  return {
    noun,
    summaryNoun: firstText(copy.summaryNoun, noun + ' summary'),
    selectedItem,
    selectedItems,
    selectedHeading: firstText(copy.selectedHeading, 'Selected ' + selectedItems),
    selectedGroup: firstText(copy.selectedGroup, labelPrefix),
    useLabel: firstText(copy.useLabel, 'Use ' + noun),
    askLabel: firstText(copy.askLabel, 'Ask about ' + noun),
    draftLabel: firstText(copy.draftLabel, 'Draft from ' + noun),
    openLabel: firstText(copy.openLabel, 'Open ' + noun),
    labelPrefix,
    promptIntroPrefix,
    contextKind: firstText(copy.contextKind, noun.replace(/\s+/g, '_').toLowerCase()),
    nodeContextPrefix: firstText(copy.nodeContextPrefix, labelPrefix)
  };
}

function artifactPresentationFromValue(value) {
  if (typeof value === 'string') {
    const parsed = parsePresentationString(value);
    return parsed || { family: value, category: '' };
  }
  if (!value || typeof value !== 'object') return { family: 'artifact', category: 'other' };
  if (value.presentation && typeof value.presentation === 'object') return normalizePresentationValue(value.presentation);
  if (value.artifact_presentation && typeof value.artifact_presentation === 'object') return normalizeServerPresentation(value.artifact_presentation);
  return artifactPresentationModel(value || {});
}

function artifactTitle(artifact, presentation) {
  const rawTitle = firstText(artifact && artifact.title, artifact && artifact.kind, 'Result');
  if (hasServerPresentation(artifact)) return rawTitle;
  if (presentation.family === 'evidence_report') return rawTitle.replace(/^Evidence packet\b/i, 'Evidence report');
  if (presentation.family === 'legacy_report') return legacyReportText(rawTitle);
  return rawTitle;
}

function artifactOpenLabel(artifact, presentation) {
  const rawLabel = firstText(artifact && artifact.open_label);
  const copy = artifactSurfaceCopy({ presentation });
  if (hasServerPresentation(artifact)) return firstText(copy.openLabel, rawLabel, 'Open artifact');
  if (presentation.family === 'evidence_report') {
    if (!rawLabel || /^Open (packet|artifact)$/i.test(rawLabel)) return copy.openLabel;
    return rawLabel.replace(/^Open packet\b/i, 'Open report');
  }
  if (presentation.family === 'legacy_report') {
    if (!rawLabel || /^Open (dashboard|artifact)$/i.test(rawLabel)) return copy.openLabel;
    return legacyReportText(rawLabel);
  }
  return rawLabel || copy.openLabel;
}

function artifactPresentationModel(artifact) {
  const server = artifact && typeof artifact.artifact_presentation === 'object' && !Array.isArray(artifact.artifact_presentation)
    ? normalizeServerPresentation(artifact.artifact_presentation)
    : null;
  if (server) return server;
  const kind = String(artifact && artifact.kind || '').toLowerCase();
  const renderer = String(artifact && artifact.renderer || '').toLowerCase();
  const operation = String(artifact && artifact.operation || '').toLowerCase();
  if (kind === 'evidence_packet' || renderer === 'evidence_packet' || operation === 'research.build_target_packet') {
    return { family: 'evidence_report', category: 'evidence' };
  }
  if (kind === 'decode_dashboard' || renderer === 'decode_dashboard' || operation === 'decode.render_dashboard') {
    return { family: 'legacy_report', category: 'report' };
  }
  if (kind === 'project_file' || renderer === 'project_file' || operation === 'portal.import_file') {
    return { family: 'file', category: 'file' };
  }
  return { family: 'artifact', category: 'other' };
}

function normalizeServerPresentation(value) {
  const family = firstText(value.family, 'artifact');
  const category = firstText(value.category, 'other');
  return {
    schema: firstText(value.schema),
    family,
    category,
    surfaceCopy: serverSurfaceCopy(value.surface_copy || value.surfaceCopy)
  };
}

function serverSurfaceCopy(value) {
  const source = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const copy = {};
  for (const [key, target] of [
    ['noun', 'noun'],
    ['summary_noun', 'summaryNoun'],
    ['summaryNoun', 'summaryNoun'],
    ['selected_item', 'selectedItem'],
    ['selectedItem', 'selectedItem'],
    ['selected_items', 'selectedItems'],
    ['selectedItems', 'selectedItems'],
    ['selected_heading', 'selectedHeading'],
    ['selectedHeading', 'selectedHeading'],
    ['selected_group', 'selectedGroup'],
    ['selectedGroup', 'selectedGroup'],
    ['use_label', 'useLabel'],
    ['useLabel', 'useLabel'],
    ['ask_label', 'askLabel'],
    ['askLabel', 'askLabel'],
    ['draft_label', 'draftLabel'],
    ['draftLabel', 'draftLabel'],
    ['open_label', 'openLabel'],
    ['openLabel', 'openLabel'],
    ['label_prefix', 'labelPrefix'],
    ['labelPrefix', 'labelPrefix'],
    ['prompt_intro_prefix', 'promptIntroPrefix'],
    ['promptIntroPrefix', 'promptIntroPrefix'],
    ['context_kind', 'contextKind'],
    ['contextKind', 'contextKind'],
    ['node_context_prefix', 'nodeContextPrefix'],
    ['nodeContextPrefix', 'nodeContextPrefix']
  ]) {
    const text = firstText(source[key]);
    if (text) copy[target] = text;
  }
  return copy;
}

function normalizePresentationValue(value) {
  return normalizeServerPresentation({
    schema: value.schema,
    family: value.family,
    category: value.category,
    surface_copy: value.surface_copy || value.surfaceCopy
  });
}

function parsePresentationString(value) {
  const text = firstText(value);
  if (!text || text.charAt(0) !== '{') return null;
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? normalizePresentationValue(parsed) : null;
  } catch {
    return null;
  }
}

function hasServerPresentation(artifact) {
  return Boolean(
    artifact &&
    typeof artifact.artifact_presentation === 'object' &&
    !Array.isArray(artifact.artifact_presentation)
  );
}

function legacySurfaceCopyFallback(family) {
  const base = legacySurfaceCopyBase(family);
  return completeSurfaceCopy(base);
}

function legacySurfaceCopyBase(family) {
  if (family === 'evidence_report') {
    return {
      noun: 'report',
      selectedItem: 'evidence item',
      selectedItems: 'evidence items',
      selectedHeading: 'Selected evidence',
      selectedGroup: 'Evidence report',
      labelPrefix: 'Evidence report',
      promptIntroPrefix: 'Selected evidence report',
      contextKind: 'evidence_report',
      nodeContextPrefix: 'Evidence report'
    };
  }
  if (family === 'legacy_report') return legacySurfaceCopyBaseFor('report', 'Report', 'report');
  if (family === 'file') return legacySurfaceCopyBaseFor('file', 'File', 'file');
  return legacySurfaceCopyBaseFor('artifact', 'Artifact', 'result', 'Artifact details');
}

function legacySurfaceCopyBaseFor(noun, labelPrefix, contextKind, nodeContextPrefix = labelPrefix) {
  return {
    noun,
    labelPrefix,
    promptIntroPrefix: 'Selected ' + noun,
    contextKind,
    nodeContextPrefix
  };
}

function titleCase(value) {
  const text = firstText(value);
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : '';
}

export function artifactPreviewModel(artifact, baseUrl = 'http://localhost') {
  const model = artifactDisplayModel(artifact || {});
  const url = String(model.previewUrl || '').trim();
  const base = resolveUrl(baseUrl, 'http://localhost');
  if (!url) {
    return { ...model, previewable: false, previewUrl: '', reason: 'No preview URL' };
  }
  const resolved = resolveUrl(url, base ? base.href : 'http://localhost');
  if (!resolved || !base) {
    return { ...model, previewable: false, previewUrl: '', reason: 'Invalid artifact URL' };
  }
  if (resolved.origin === base.origin && artifactPreviewPaths(model).includes(resolved.pathname)) {
    return { ...model, previewable: true, previewUrl: resolved.href, reason: '' };
  }
  return { ...model, previewable: false, previewUrl: '', reason: 'Preview is limited to Genomi result files' };
}

export function artifactVersionSelectorModel(artifact) {
  const model = artifactDisplayModel(artifact || {});
  const options = model.versions
    .map((version) => artifactVersionOption(version, model))
    .filter(Boolean);
  return {
    visible: model.versionsLoaded && options.length > 1,
    value: firstText(model.effectiveVersionId, model.latestVersionId, options[0] && options[0].value),
    latestVersionId: model.latestVersionId,
    requestedSelectedVersionId: model.requestedSelectedVersionId,
    selectedVersionId: model.selectedVersionId,
    resolvedSelectedVersionId: model.resolvedSelectedVersionId,
    effectiveVersionId: model.effectiveVersionId,
    versionCount: options.length,
    options
  };
}

export function artifactProvenanceModel(artifact) {
  const model = artifactDisplayModel(artifact || {});
  const title = artifactDetailsTitle(model);
  const nodes = [
    provenanceNode('Artifact', model.title),
    provenanceNode('Status', model.status),
    provenanceNode('Created', model.createdAt),
    provenanceNode('Updated', model.updatedAt),
    provenanceNode('Summary', model.meta),
    provenanceNode(model.selectedVersionId ? 'Selected version' : 'Latest version', model.effectiveVersionId),
    provenanceNode('Version history', versionHistorySummary(model))
  ].filter(Boolean);
  return nodes.length ? { title, nodes } : null;
}

export function artifactDetailsTitle(value) {
  const presentation = artifactPresentationFromValue(value || {});
  if (presentation.family === 'evidence_report') return 'Evidence report details';
  if (presentation.family === 'legacy_report') return 'Report details';
  if (presentation.family === 'file') return 'File details';
  return 'Artifact details';
}

export function artifactOperationTraceModel(artifact) {
  const display = artifactDisplayModel(artifact || {});
  const nodes = [
    briefNode('Artifact id', display.id),
    briefNode('Project id', display.projectId),
    briefNode('Source operation', display.operation),
    briefNode('Renderer', display.renderer),
    briefNode('Kind', display.kind),
    briefNode('Status', display.status),
    briefNode('Created', display.createdAt),
    briefNode('Updated', display.updatedAt),
    briefNode('Latest version', display.latestVersionId),
    briefNode('Latest version file', display.latestVersionFileUrl),
    briefNode('Requested version', display.unresolvedSelectedVersionId),
    briefNode('Selected version', display.selectedVersionId),
    briefNode('Selected version file', display.selectedVersionFileUrl),
    briefNode('Effective version', display.selectedVersionId ? display.effectiveVersionId : ''),
    briefNode('Effective version file', display.selectedVersionId ? display.effectiveVersionFileUrl : ''),
    briefNode('Version count', display.versionCount),
    briefNode('Version history', versionHistorySummary(display)),
    briefNode('Version ids', display.versions.map((version) => version.version_id).filter(Boolean).join(', ')),
    briefNode('Version content type', display.effectiveVersion && display.effectiveVersion.content_type),
    briefNode('Version checksum', display.effectiveVersion && display.effectiveVersion.checksum),
    briefNode('Version size', display.effectiveVersion && display.effectiveVersion.size_bytes),
    briefNode('Preview URL', display.previewUrl),
    briefNode('Open URL', display.url)
  ].filter(Boolean);
  return nodes.length ? { title: 'Operation trace', nodes } : null;
}

export function artifactOriginRunContext(artifact) {
  const origin = artifact && typeof artifact === 'object' ? artifact.origin_context || artifact.originContext || {} : {};
  const runIds = Array.isArray(origin.run_ids) ? origin.run_ids : Array.isArray(origin.runIds) ? origin.runIds : [];
  return {
    frameId: String(origin.frame_id || origin.frameId || '').trim(),
    runIds: runIds.map((runId) => String(runId || '').trim()).filter(Boolean)
  };
}

export function artifactVersionFilePath(versionOrId, artifact = {}) {
  const version = versionOrId && typeof versionOrId === 'object' && !Array.isArray(versionOrId) ? versionOrId : null;
  const versionId = firstText(version && version.version_id, version ? '' : versionOrId);
  const projectId = firstText(version && version.project_id, artifact && artifact.project_id, artifact && artifact.projectId);
  const artifactId = firstText(version && version.artifact_id, artifact && artifact.id, artifact && artifact.artifact_id);
  const scopedPath = projectId && artifactId && versionId
    ? '/api/projects/' + encodeURIComponent(projectId) + '/artifacts/' + encodeURIComponent(artifactId) + '/versions/' + encodeURIComponent(versionId) + '/file'
    : '';
  const suppliedFileUrl = firstText(version && version.file_url, version && version.fileUrl);
  if (suppliedFileUrl) return urlPathname(suppliedFileUrl) === scopedPath ? suppliedFileUrl : '';
  if (!versionId) return '';
  if (projectId && artifactId) {
    return scopedPath;
  }
  return '';
}

export function artifactVersions(artifact) {
  return Array.isArray(artifact && artifact.versions)
    ? artifact.versions.filter((version) => version && typeof version === 'object' && !Array.isArray(version))
    : [];
}

export function latestArtifactVersion(artifact, versions = artifactVersions(artifact)) {
  const latestVersion = artifact && artifact.latest_version;
  if (latestVersion && typeof latestVersion === 'object' && !Array.isArray(latestVersion)) return latestVersion;
  const latestVersionId = firstText(artifact && artifact.latest_version_id);
  if (latestVersionId) {
    const matching = versions.find((version) => firstText(version.version_id) === latestVersionId);
    if (matching) return matching;
  }
  return versions[0] || null;
}

export function selectedArtifactVersion(artifact, versions = artifactVersions(artifact), requestedVersionId = firstText(artifact && artifact.selected_version_id, artifact && artifact.selectedVersionId)) {
  const selectedVersionId = firstText(requestedVersionId);
  if (!selectedVersionId) return null;
  return versions.find((version) => firstText(version.version_id) === selectedVersionId) || null;
}

export function versionHistorySummary(model) {
  if (!model.versionsLoaded && !model.versions.length) return '';
  const count = model.versions.length;
  return count + ' loaded version' + (count === 1 ? '' : 's');
}

function provenanceNode(label, value) {
  if (value === null || value === undefined || value === '') return null;
  return { label, summary: formatShort(value), value };
}

function briefNode(label, value) {
  if (value === null || value === undefined || value === '' || value === false) return null;
  return { label, summary: formatShort(value), value };
}

function artifactVersionOption(version, model) {
  const versionId = firstText(version && version.version_id);
  if (!versionId) return null;
  const badges = [];
  if (versionId === model.latestVersionId) badges.push('Latest');
  if (versionId === model.selectedVersionId && versionId !== model.latestVersionId) badges.push('Selected');
  const details = [
    badges.length ? badges.join(' / ') : 'Saved version',
    contentTypeLabel(version && version.content_type),
    byteSizeLabel(version && version.size_bytes),
    dateLabel(version && (version.created_at || version.createdAt))
  ].filter(Boolean);
  return {
    value: versionId,
    label: details.join(' · ')
  };
}

function contentTypeLabel(value) {
  const text = firstText(value);
  if (!text) return '';
  if (text === 'text/html') return 'HTML';
  if (text === 'text/markdown') return 'Markdown';
  if (text === 'application/json') return 'JSON';
  if (text.startsWith('text/')) return text.slice(5).toUpperCase();
  return text;
}

function byteSizeLabel(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '';
  if (bytes < 1024) return String(bytes) + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0) + ' MB';
}

function dateLabel(value) {
  const text = firstText(value);
  if (!text) return '';
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return '';
  return date.toISOString().slice(0, 10);
}

function firstText(...values) {
  for (const value of values) {
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return '';
}

function fallbackSummaryLines(artifact, presentation) {
  const lines = [];
  if (artifact.status) lines.push(artifactSummaryLine(artifact.status, presentation));
  if (artifact.summary && typeof artifact.summary === 'object' && typeof artifact.summary.headline === 'string') {
    lines.push(artifactSummaryLine(artifact.summary.headline, presentation));
  }
  return lines.length ? lines : ['Artifact ready'];
}

function artifactSummaryLine(value, presentation) {
  const text = firstText(value);
  if (!text) return '';
  const family = presentation && presentation.family;
  if (/^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+:\s*/i.test(text)) {
    return '';
  }
  if (/^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$/.test(text)) {
    return legacyReportLine(operationDisplayLabel(text, 'Research step'), family);
  }
  if (/^[a-z0-9]+(?:_[a-z0-9]+)+$/i.test(text)) {
    return legacyReportLine(text.split('_').filter(Boolean).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(' '), family);
  }
  return legacyReportLine(text, family);
}

function legacyReportLine(text, family) {
  if (family !== 'legacy_report') return text;
  return legacyReportText(text);
}

function legacyReportText(text) {
  return text
    .replace(/\bDashboards\b/g, 'Reports')
    .replace(/\bdashboards\b/g, 'reports')
    .replace(/\bDashboard\b/g, 'Report')
    .replace(/\bdashboard\b/g, 'report')
    .replace(/\bPanels\b/g, 'Sections')
    .replace(/\bpanels\b/g, 'sections')
    .replace(/\bPanel\b/g, 'Section')
    .replace(/\bpanel\b/g, 'section');
}

function resolveUrl(value, baseUrl) {
  try {
    return new URL(value, baseUrl);
  } catch {
    return null;
  }
}

function artifactPreviewPaths(model) {
  const paths = [
    model.effectiveVersionFileUrl,
    model.selectedVersionFileUrl,
    model.latestVersionFileUrl,
    artifactFilePath(model.id, model.projectId)
  ].map((value) => urlPathname(value)).filter(Boolean);
  return [...new Set(paths)];
}

function artifactFilePath(artifactId, projectId = '') {
  const cleanArtifactId = firstText(artifactId);
  if (!cleanArtifactId) return '';
  const cleanProjectId = firstText(projectId);
  if (cleanProjectId) {
    return '/api/projects/' + encodeURIComponent(cleanProjectId) + '/artifacts/' + encodeURIComponent(cleanArtifactId) + '/file';
  }
  return '';
}

function urlPathname(value) {
  const resolved = resolveUrl(value, 'http://localhost');
  return resolved ? resolved.pathname : '';
}
