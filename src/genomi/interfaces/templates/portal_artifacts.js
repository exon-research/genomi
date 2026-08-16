import { renderArtifactActionMenu } from './portal_artifact_actions.js';
import {
  artifactDisplayModel,
  artifactOriginRunContext,
  artifactPreviewModel
} from './portal_artifact_display_model.js';
import { artifactLibraryModel } from './portal_artifact_library_model.js';
import { artifactReviewStateModel } from './portal_artifact_runtime_model.js';

export { artifactWorkTraceModel } from './portal_artifact_origin_trace.js';
export { artifactMessagesModel, artifactOriginContextModel } from './portal_artifact_messages.js';
export { artifactSelectionModel, artifactSelectionInspectorModel } from './portal_artifact_selection.js';
export { artifactLibraryModel, artifactRecordsOutsideWorkspaceFiles } from './portal_artifact_library_model.js';
export { artifactActionMenuModel, artifactCopyLink } from './portal_artifact_actions.js';
export { renderArtifactPreview } from './portal_artifact_preview.js';
export {
  artifactDisplayModel,
  artifactOperationTraceModel,
  artifactPreviewModel,
  artifactProvenanceModel,
  artifactSurfaceCopy,
  artifactVersionSelectorModel
} from './portal_artifact_display_model.js';
export { artifactContextForSelection, artifactContextPayload } from './portal_artifact_context.js';
export { artifactEnvironmentModel } from './portal_artifact_environment_model.js';
export { artifactStateModel } from './portal_artifact_state_adapters.js';
export { artifactReproductionModel } from './portal_artifact_reproduction_model.js';
export {
  artifactReviewBriefModel,
  artifactReviewBriefPayload,
  artifactReviewStateModel,
  artifactRuntimeModel
} from './portal_artifact_runtime_model.js';
export {
  artifactProvenanceTabsModel,
  artifactProvenanceViewModel
} from './portal_artifact_view_model.js';

export function renderArtifacts(list, artifacts, options = {}) {
  const library = artifactLibraryModel(artifacts, {
    query: options.query,
    filter: options.filter,
    layout: options.layout,
    baseUrl: options.baseUrl || window.location.href
  });
  if (!library.totalCount) {
    renderArtifactNotice(
      list,
      'No files or artifacts yet',
      'Imported files, generated reports, project files, and reviewed outputs for this project will appear here.'
    );
    return;
  }
  list.innerHTML = '';
  list.appendChild(artifactLibraryToolbar(library, options));
  if (!library.shownCount) {
    list.appendChild(artifactNoticeCard('No matching library items', 'Change the search or filter to inspect other files and artifacts.'));
    return;
  }
  list.appendChild(artifactLibraryGroups(library, options));
}

export function createArtifactLibraryController({ container, onPreview, onUseContext, onArtifactAction, baseUrlProvider }) {
  const state = {
    artifacts: [],
    activeArtifactId: '',
    query: '',
    filter: 'all',
    layout: 'cards'
  };
  function render(artifacts, options = {}) {
    state.artifacts = Array.isArray(artifacts) ? artifacts : [];
    state.activeArtifactId = options.activeArtifactId || '';
    renderCurrent(Boolean(options.focusSearch));
  }
  function renderCurrent(focusSearch = false) {
    renderArtifacts(container, state.artifacts, {
      onPreview,
      onUseContext,
      onArtifactAction,
      baseUrl: artifactLibraryBaseUrl(baseUrlProvider),
      activeArtifactId: state.activeArtifactId,
      query: state.query,
      filter: state.filter,
      layout: state.layout,
      onQueryChange: updateQuery,
      onFilterChange: updateFilter,
      onLayoutChange: updateLayout
    });
    if (focusSearch) focusSearchInput(container);
  }
  function updateQuery(query) {
    state.query = query;
    renderCurrent(true);
  }
  function updateFilter(filter) {
    state.filter = filter || 'all';
    renderCurrent();
  }
  function updateLayout(layout) {
    state.layout = layout || 'cards';
    renderCurrent();
  }
  return { render };
}

export function renderArtifactStrip(container, artifacts, options = {}) {
  if (!container) return;
  const visible = artifactsForDisplay(artifacts);
  const shown = visible.slice(0, 5);
  container.setAttribute('data-testid', 'genomi-artifact-tray');
  container.hidden = !shown.length;
  container.innerHTML = '';
  if (!shown.length) return;
  const head = document.createElement('div');
  head.className = 'artifact-strip-head';
  head.innerHTML = '<span></span><strong></strong>';
  head.querySelector('span').textContent = options.heading || 'Files';
  head.querySelector('strong').textContent = String(visible.length);
  container.appendChild(head);
  const row = document.createElement('div');
  row.className = 'artifact-strip-row';
  shown.forEach((artifact) => row.appendChild(artifactStripItem(artifact, options)));
  container.appendChild(row);
}

export function renderInlineArtifactStrip(container, artifacts, options = {}) {
  renderArtifactStrip(container, artifactsForDisplay(artifacts), { ...options, heading: 'Generated' });
  if (container) container.setAttribute('data-testid', 'message-artifact-strip');
}

export function artifactsForRun(artifacts, frameId, runId) {
  const cleanFrameId = String(frameId || '').trim();
  const cleanRunId = String(runId || '').trim();
  if (!cleanFrameId || !cleanRunId || !Array.isArray(artifacts)) return [];
  return artifacts.filter((artifact) => {
    // Records the person attached to the conversation belong to the
    // conversation's attachment strip, not to what an assistant turn produced.
    if (artifact && artifact.operation === 'portal.import_file') return false;
    const origin = artifactOriginRunContext(artifact);
    return origin.frameId === cleanFrameId && origin.runIds.includes(cleanRunId);
  });
}

export function renderArtifactNotice(list, title, message) {
  list.innerHTML = '';
  list.appendChild(artifactNoticeCard(title, message));
}

function artifactNoticeCard(title, message) {
  const card = document.createElement('div');
  card.className = 'artifact-card';
  card.innerHTML = '<strong></strong><div class="artifact-meta"></div>';
  card.querySelector('strong').textContent = title;
  card.querySelector('.artifact-meta').textContent = message;
  return card;
}

function artifactLibraryGroups(library, options) {
  const groups = document.createElement('div');
  groups.className = 'artifact-library-groups';
  groups.setAttribute('data-testid', 'genomi-artifact-library-groups');
  library.groups.forEach((group) => groups.appendChild(artifactLibraryGroup(group, options, library.layout)));
  return groups;
}

function artifactLibraryGroup(group, options, layout) {
  const section = document.createElement('section');
  section.className = 'artifact-library-group';
  section.setAttribute('data-testid', 'genomi-artifact-library-group');
  section.setAttribute('data-artifact-group', group.key);
  const head = document.createElement('div');
  head.className = 'artifact-library-group-head';
  head.innerHTML = '<strong></strong><span></span>';
  head.querySelector('strong').textContent = group.label;
  head.querySelector('span').textContent = group.summary;
  section.appendChild(head);
  const items = document.createElement('div');
  items.className = 'artifact-list-items artifact-list-items--' + layout;
  items.setAttribute('data-testid', 'genomi-artifact-list-items');
  group.items.forEach((item) => items.appendChild(artifactCard(item, options, layout)));
  section.appendChild(items);
  return section;
}

function artifactStripItem(artifact, options) {
  const model = artifactDisplayModel(artifact);
  const card = document.createElement('div');
  card.className = 'artifact-strip-item';
  card.setAttribute('data-testid', 'genomi-artifact-card');
  card.dataset.artifactId = model.id;
  card.dataset.artifactKind = model.kind;
  card.dataset.artifactRenderer = model.renderer;
  card.innerHTML = '<strong></strong><span></span><div class="artifact-strip-actions"></div>';
  card.querySelector('strong').textContent = model.title;
  card.querySelector('span').textContent = model.meta || 'Artifact ready';
  const actions = card.querySelector('.artifact-strip-actions');
  const preview = artifactPreviewAction(artifact, options, 'Open this generated file beside the conversation', null, 'Open');
  if (preview) actions.appendChild(preview);
  const menu = renderArtifactActionMenu({
    artifact,
    model,
    options: { ...options, includePreview: false },
    mode: 'card'
  });
  if (menu) actions.appendChild(menu);
  return card;
}

function artifactsForDisplay(artifacts) {
  return Array.isArray(artifacts) ? artifacts.filter((artifact) => artifact && artifact.hidden !== true) : [];
}

function artifactCard(libraryItem, options, layout = 'cards') {
  const item = artifactCardItem(libraryItem, options.baseUrl || window.location.href);
  const artifact = item.artifact;
  const model = item.display;
  const card = document.createElement('div');
  card.className = 'artifact-card' + (layout === 'compact' ? ' compact' : '') + (model.id && model.id === options.activeArtifactId ? ' active' : '') + (model.starred ? ' starred' : '') + (model.hidden ? ' hidden' : '');
  card.setAttribute('data-testid', 'genomi-artifact-card');
  card.dataset.artifactId = model.id;
  card.dataset.artifactKind = model.kind;
  card.dataset.artifactRenderer = model.renderer;
  card.dataset.artifactStarred = model.starred ? 'true' : 'false';
  card.dataset.artifactHidden = model.hidden ? 'true' : 'false';
  card.innerHTML = '<strong></strong><div class="artifact-meta"></div><div class="artifact-review-slot" hidden></div><div class="artifact-actions"></div>';
  card.querySelector('strong').textContent = model.title;
  card.querySelector('.artifact-meta').textContent = artifactCardMeta(model);
  const reviewBadge = artifactReviewBadge(artifact);
  const reviewSlot = card.querySelector('.artifact-review-slot');
  if (reviewBadge && reviewSlot) {
    reviewSlot.hidden = false;
    reviewSlot.appendChild(reviewBadge);
  }
  const actions = card.querySelector('.artifact-actions');
  const preview = artifactPreviewAction(artifact, options, '', item.preview);
  if (preview) actions.appendChild(preview);
  const menu = renderArtifactActionMenu({
    artifact,
    model,
    preview: item.preview,
    options: { ...options, includePreview: false },
    mode: 'card'
  });
  if (menu) actions.appendChild(menu);
  return card;
}

function artifactLibraryToolbar(library, options) {
  const toolbar = document.createElement('div');
  toolbar.className = 'artifact-library-toolbar';
  toolbar.setAttribute('data-testid', 'genomi-artifact-library-toolbar');
  const searchWrap = document.createElement('label');
  searchWrap.className = 'artifact-library-search';
  searchWrap.innerHTML = '<span>Search library</span>';
  const search = document.createElement('input');
  search.type = 'search';
  search.value = library.query;
  search.placeholder = 'Search title, report type, source, or status';
  search.setAttribute('data-testid', 'genomi-artifact-search');
  search.addEventListener('input', () => {
    if (typeof options.onQueryChange === 'function') options.onQueryChange(search.value);
  });
  searchWrap.appendChild(search);
  toolbar.appendChild(searchWrap);

  const controls = document.createElement('div');
  controls.className = 'artifact-library-controls';
  const filters = document.createElement('div');
  filters.className = 'artifact-library-filters';
  library.filters.forEach((item) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tool-action' + (item.key === library.filter ? ' active' : '');
    button.setAttribute('data-testid', 'genomi-artifact-filter-' + item.key);
    button.textContent = item.label + ' ' + item.count;
    button.addEventListener('click', () => {
      if (typeof options.onFilterChange === 'function') options.onFilterChange(item.key);
    });
    filters.appendChild(button);
  });
  controls.appendChild(filters);

  const layout = document.createElement('div');
  layout.className = 'artifact-library-layout';
  library.layouts.forEach((item) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tool-action' + (item.active ? ' active' : '');
    button.setAttribute('data-testid', 'genomi-artifact-layout-' + item.key);
    button.textContent = item.label;
    button.addEventListener('click', () => {
      if (typeof options.onLayoutChange === 'function') options.onLayoutChange(item.key);
    });
    layout.appendChild(button);
  });
  controls.appendChild(layout);

  const summary = document.createElement('strong');
  summary.textContent = library.summary;
  controls.appendChild(summary);
  toolbar.appendChild(controls);
  return toolbar;
}

function artifactPreviewAction(artifact, options, title, previewModel = null, label = 'Preview') {
  const preview = previewModel || artifactPreviewModel(artifact, options.baseUrl || window.location.href);
  if (!preview.previewable || typeof options.onPreview !== 'function') return null;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'tool-action';
  button.setAttribute('data-testid', 'genomi-artifact-open-split');
  button.textContent = label;
  if (title) button.title = title;
  button.addEventListener('click', () => options.onPreview(artifact));
  return button;
}

function artifactCardItem(value, baseUrl) {
  if (value && value.artifact && value.display && value.preview) return value;
  const artifact = value || {};
  return {
    artifact,
    display: artifactDisplayModel(artifact),
    preview: artifactPreviewModel(artifact, baseUrl)
  };
}

function artifactLibraryBaseUrl(provider) {
  if (typeof provider === 'function') return provider();
  return provider || window.location.href;
}

function artifactCardMeta(model) {
  return [
    model.starred ? 'Starred' : '',
    model.hidden ? 'Hidden' : '',
    model.meta
  ].filter(Boolean).join(' · ');
}

function artifactReviewBadge(artifact) {
  const review = artifactReviewStateModel(artifact);
  if (!review) return null;
  const status = reviewStatus(review);
  if (status.kind === 'passed' || status.kind === 'checked') return null;
  const badge = document.createElement('div');
  badge.className = 'artifact-review-status ' + status.kind;
  badge.setAttribute('data-testid', 'genomi-artifact-review-status');
  badge.innerHTML = '<span></span><strong></strong>';
  badge.querySelector('span').textContent = 'Review';
  badge.querySelector('strong').textContent = status.label;
  badge.title = reviewSummary(review);
  return badge;
}

function reviewStatus(review) {
  const status = String(review && review.status || '').toLowerCase();
  const failures = metricNumber(review, 'Failures');
  const warnings = metricNumber(review, 'Warnings');
  if (/fail|error/.test(status) || failures > 0) return { kind: 'failed', label: 'failed' };
  if (/warn/.test(status) || warnings > 0) return { kind: 'warning', label: 'warnings' };
  if (/pass|ok|success|complete/.test(status)) return { kind: 'passed', label: 'no issues' };
  if (/running|pending|progress/.test(status)) return { kind: 'pending', label: 'running' };
  return { kind: 'checked', label: status || 'checked' };
}

function reviewSummary(review) {
  const checks = metricNumber(review, 'Checks');
  const warnings = metricNumber(review, 'Warnings');
  const failures = metricNumber(review, 'Failures');
  const parts = [
    checks ? String(checks) + ' check' + (checks === 1 ? '' : 's') : '',
    failures ? String(failures) + ' failed' : '',
    warnings ? String(warnings) + ' warning' + (warnings === 1 ? '' : 's') : ''
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : 'Review state attached to this artifact version';
}

function metricNumber(review, label) {
  const metrics = Array.isArray(review && review.metrics) ? review.metrics : [];
  const metric = metrics.find((item) => item && item.label === label);
  const value = Number(metric && metric.value);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function focusSearchInput(container) {
  const search = container && container.querySelector('[data-testid="genomi-artifact-search"]');
  if (!search) return;
  search.focus({ preventScroll: true });
  if (typeof search.setSelectionRange === 'function') search.setSelectionRange(search.value.length, search.value.length);
}
