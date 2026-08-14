import { artifactDisplayModel, artifactPreviewModel, artifactSurfaceCopy } from './portal_artifact_display_model.js';
import { artifactOriginContextModel } from './portal_artifact_messages.js';
import { artifactBundleUrl, artifactMetadataUrl, artifactScriptBundleUrl } from './portal_api.js';
import { artifactWorkspaceUrl } from './portal_artifact_route_model.js';
import { artifactContextPayload } from './portal_artifact_context.js';
import { artifactReviewBriefPayload, artifactReviewHasRunningRun, artifactReviewStateModel } from './portal_artifact_runtime_model.js';
import { artifactReproductionModel } from './portal_artifact_reproduction_model.js';

export const ARTIFACT_ACTIONS = Object.freeze({
  STAR: 'star',
  UNSTAR: 'unstar',
  RENAME: 'rename',
  HIDE: 'hide',
  UNHIDE: 'unhide',
  DELETE: 'delete'
});

const ARTIFACT_STATE_ACTIONS = Object.freeze([
  ARTIFACT_ACTIONS.STAR,
  ARTIFACT_ACTIONS.UNSTAR,
  ARTIFACT_ACTIONS.HIDE,
  ARTIFACT_ACTIONS.UNHIDE
]);
const ARTIFACT_ACTION_KIND = Object.freeze({
  COMMAND: 'command',
  DOWNLOAD: 'download',
  EXTERNAL_LINK: 'external_link'
});

export function isArtifactStateAction(action) {
  return ARTIFACT_STATE_ACTIONS.includes(action);
}

export function renderArtifactActionMenu({
  artifact,
  model = null,
  preview = null,
  options = {},
  mode = 'card',
  shell = null,
  linkScope = {},
  tabs = []
} = {}) {
  const display = model || artifactDisplayModel(artifact || {});
  const previewModel = preview || artifactPreviewModel(artifact || {}, artifactActionBaseUrl(options));
  const actions = artifactActionMenuModel({
    artifact,
    model: display,
    preview: previewModel,
    options,
    mode,
    linkScope,
    tabs
  });
  if (!actions.length) return null;
  const details = document.createElement('details');
  details.className = 'artifact-action-menu';
  details.setAttribute('data-testid', 'genomi-artifact-actions-menu');
  const summary = document.createElement('summary');
  summary.className = 'tool-action artifact-action-menu-trigger';
  summary.setAttribute('data-testid', 'genomi-artifact-more-actions');
  summary.setAttribute('aria-label', 'More actions for ' + (display.title || 'artifact'));
  summary.textContent = 'More';
  details.appendChild(summary);
  const menu = document.createElement('div');
  menu.className = 'artifact-action-menu-list';
  menu.setAttribute('role', 'menu');
  actions.forEach((action, index) => {
    if (action.advanced && !actions.slice(0, index).some((item) => item.advanced)) {
      const heading = document.createElement('div');
      heading.className = 'artifact-menu-section-label';
      heading.textContent = 'Technical';
      menu.appendChild(heading);
    }
    menu.appendChild(actionElement(action, details, shell, options));
  });
  details.appendChild(menu);
  return details;
}

export function artifactActionMenuModel({
  artifact,
  model = null,
  preview = null,
  options = {},
  mode = 'card',
  linkScope = {},
  tabs = []
} = {}) {
  const display = model || artifactDisplayModel(artifact || {});
  const previewModel = preview || artifactPreviewModel(artifact || {}, artifactActionBaseUrl(options));
  const originContext = artifactOriginContextModel(artifact);
  const reviewState = artifactReviewStateModel(artifact);
  const reviewRunning = artifactReviewHasRunningRun(artifact);
  const reproduction = artifactReproductionModel(artifact);
  const copy = artifactSurfaceCopy(display);
  const starAction = display.starred ? ARTIFACT_ACTIONS.UNSTAR : ARTIFACT_ACTIONS.STAR;
  const hiddenAction = display.hidden ? ARTIFACT_ACTIONS.UNHIDE : ARTIFACT_ACTIONS.HIDE;
  const actions = [
    action(ARTIFACT_ACTIONS.STAR, display.starred ? 'Unstar' : 'Star', 'genomi-artifact-toggle-star', {
      include: typeof options.onArtifactAction === 'function',
      run: () => options.onArtifactAction(artifact, { action: starAction }),
      title: display.starred ? 'Remove this artifact from starred items' : 'Keep this artifact near the top of the library'
    }),
    action(ARTIFACT_ACTIONS.RENAME, 'Rename', 'genomi-artifact-rename', {
      include: typeof options.onArtifactAction === 'function',
      run: () => options.onArtifactAction(artifact, { action: ARTIFACT_ACTIONS.RENAME }),
      title: 'Rename this artifact in the project library'
    }),
    action(ARTIFACT_ACTIONS.HIDE, display.hidden ? 'Unhide' : 'Hide', 'genomi-artifact-toggle-hidden', {
      include: typeof options.onArtifactAction === 'function',
      run: () => options.onArtifactAction(artifact, { action: hiddenAction }),
      title: display.hidden ? 'Return this artifact to the visible library' : 'Hide this artifact from the default library view'
    }),
    action('preview', 'Preview', 'genomi-artifact-menu-preview', {
      include: options.includePreview !== false && previewModel.previewable && typeof options.onPreview === 'function',
      run: () => options.onPreview(artifact)
    }),
    action('use', copy.useLabel, 'genomi-artifact-use', {
      include: mode !== 'preview' && typeof options.onUseContext === 'function',
      run: () => options.onUseContext(artifactContextPayload(artifact)),
      title: 'Use this ' + copy.noun + ' in the next assistant turn'
    }),
    action('start_conversation', 'Start conversation', 'genomi-artifact-start-conversation', {
      include: mode === 'preview' && typeof options.onAskNewContext === 'function',
      run: () => options.onAskNewContext(artifactContextPayload(artifact)),
      title: 'Start a focused conversation from this ' + copy.noun
    }),
    action('review', 'Use review summary', 'genomi-artifact-review-brief', {
      include: Boolean(reviewState) && typeof options.onUseContext === 'function',
      run: () => options.onUseContext(artifactReviewBriefPayload(artifact)),
      title: 'Use a concise review summary in the next assistant turn'
    }),
    action('run_review_checks', reviewRunning ? 'Checking review...' : 'Run review checks', 'genomi-artifact-run-review-checks', {
      include: Boolean(reviewState) && typeof options.onArtifactReviewRun === 'function',
      run: reviewRunning ? null : () => options.onArtifactReviewRun(artifact),
      title: reviewRunning
        ? 'Review checks are running for this artifact version'
        : 'Run Genomi artifact and evidence-boundary checks for this artifact version',
      disabled: reviewRunning
    }),
    action('view_chat', 'View in chat', 'genomi-artifact-view-context', {
      include: Boolean(originContext) && typeof options.onViewContext === 'function',
      run: () => options.onViewContext(originContext, artifact),
      title: 'Open the chat and work trail that produced this artifact'
    }),
    action('technical', 'Advanced technical details', 'genomi-artifact-menu-technical', {
      include: mode === 'preview' && hasArtifactTab(tabs, 'technical') && typeof options.onActivateTab === 'function',
      run: () => options.onActivateTab('technical'),
      title: 'Open technical tool, runtime, and state details',
      advanced: true
    }),
    copyLinkAction(display, options, linkScope),
    copyMetadataAction(display),
    exportMetadataAction(display, options),
    downloadScriptBundleAction(display, options, reproduction),
    downloadBundleAction(display, options),
    openArtifactAction(display),
    action(ARTIFACT_ACTIONS.DELETE, 'Delete', 'genomi-artifact-delete', {
      include: typeof options.onArtifactAction === 'function',
      run: () => options.onArtifactAction(artifact, { action: ARTIFACT_ACTIONS.DELETE }),
      title: 'Delete this artifact from the project'
    })
  ].filter((item) => item && item.include !== false);
  return actions;
}

export function artifactCopyLink(model, options = {}, linkScope = {}) {
  if (!model.projectId || !model.id) return '';
  const versionId = linkScope.includeSelectedVersion ? model.selectedVersionId : '';
  const tabId = linkScope.includeActiveTab ? options.activeTabId : '';
  return artifactWorkspaceUrl(model.projectId, model.id, versionId, artifactActionBaseUrl(options), tabId);
}

function action(id, label, testId, options = {}) {
  return {
    id,
    label,
    testId,
    kind: ARTIFACT_ACTION_KIND.COMMAND,
    include: options.include !== false,
    title: options.title || '',
    advanced: Boolean(options.advanced),
    disabled: Boolean(options.disabled),
    run: typeof options.run === 'function' ? options.run : null
  };
}

function copyLinkAction(model, options, linkScope) {
  const url = artifactCopyLink(model, options, linkScope);
  if (!url) return null;
  const item = action('copy_link', 'Copy link', 'genomi-artifact-copy-link', {
    title: linkScope.includeSelectedVersion && model.selectedVersionId
      ? 'Copy workspace link for this artifact version'
      : 'Copy workspace link for this artifact',
    run: (context) => {
      const currentTabId = context && context.shell
        ? context.shell.dataset.activeArtifactTab || options.activeTabId
        : options.activeTabId;
      const currentUrl = artifactCopyLink(model, { ...options, activeTabId: currentTabId }, linkScope);
      if (context && context.element) context.element.dataset.workspaceUrl = currentUrl;
      writeClipboardText(currentUrl);
    }
  });
  item.workspaceUrl = url;
  return item;
}

function copyMetadataAction(model) {
  if (!model.id) return null;
  return action('copy_metadata', 'Copy technical metadata', 'genomi-artifact-copy-metadata', {
    title: 'Copy artifact metadata JSON',
    advanced: true,
    run: () => writeClipboardText(JSON.stringify(artifactMetadata(model), null, 2))
  });
}

function exportMetadataAction(model, options) {
  const url = artifactMetadataUrl(model.projectId, model.id, artifactActionBaseUrl(options));
  if (!url) return null;
  return {
    id: 'export_metadata',
    label: 'Download technical metadata',
    testId: 'genomi-artifact-export-metadata',
    kind: ARTIFACT_ACTION_KIND.DOWNLOAD,
    href: url,
    title: 'Download artifact metadata, versions, and provenance as JSON',
    include: true,
    advanced: true
  };
}

function downloadScriptBundleAction(model, options, reproduction) {
  if (!reproduction || reproduction.status !== 'ready') return null;
  const url = artifactScriptBundleUrl(model.projectId, model.id, model.effectiveVersionId, artifactActionBaseUrl(options));
  if (!url) return null;
  return {
    id: 'download_script_bundle',
    label: 'Download rebuild script',
    testId: 'genomi-artifact-download-script-bundle',
    kind: ARTIFACT_ACTION_KIND.DOWNLOAD,
    href: url,
    title: 'Download the public rebuild script and recipe for this artifact version',
    include: true
  };
}

function downloadBundleAction(model, options) {
  const url = artifactBundleUrl(model.projectId, model.id, artifactActionBaseUrl(options));
  if (!url) return null;
  return {
    id: 'download_bundle',
    label: 'Download artifact bundle',
    testId: 'genomi-artifact-download-bundle',
    kind: ARTIFACT_ACTION_KIND.DOWNLOAD,
    href: url,
    title: 'Download artifact metadata and portal-owned version files',
    include: true
  };
}

function openArtifactAction(model) {
  if (!model.url) return null;
  return {
    id: 'open',
    label: model.openLabel,
    testId: 'genomi-artifact-open',
    kind: ARTIFACT_ACTION_KIND.EXTERNAL_LINK,
    href: model.url,
    title: 'Open this artifact file in a new tab',
    include: true
  };
}

function actionElement(actionItem, details, shell, options) {
  const kind = actionItem.kind || (actionItem.href ? ARTIFACT_ACTION_KIND.EXTERNAL_LINK : ARTIFACT_ACTION_KIND.COMMAND);
  const isCommand = kind === ARTIFACT_ACTION_KIND.COMMAND;
  const element = document.createElement(isCommand ? 'button' : 'a');
  element.className = 'artifact-menu-item' + (actionItem.advanced ? ' artifact-menu-item-advanced' : '');
  element.setAttribute('role', 'menuitem');
  element.setAttribute('data-testid', actionItem.testId);
  element.textContent = actionItem.label;
  if (actionItem.title) element.title = actionItem.title;
  if (actionItem.disabled) {
    element.setAttribute('aria-disabled', 'true');
    element.classList.add('disabled');
  }
  if (!isCommand) {
    element.href = actionItem.href;
    if (kind === ARTIFACT_ACTION_KIND.EXTERNAL_LINK) {
      element.target = '_blank';
      element.rel = 'noopener noreferrer';
    }
    if (actionItem.download) element.download = actionItem.download;
  } else {
    element.type = 'button';
    if (actionItem.disabled) element.disabled = true;
    if (actionItem.id === 'copy_link') {
      element.dataset.workspaceUrl = actionItem.workspaceUrl || '';
    }
    element.addEventListener('click', () => {
      if (typeof actionItem.run === 'function') actionItem.run({ element, shell });
      details.open = false;
    });
  }
  return element;
}

function artifactMetadata(model) {
  return {
    artifact_id: model.id,
    project_id: model.projectId,
    title: model.title,
    kind: model.kind,
    renderer: model.renderer,
    operation: model.operation,
    status: model.status,
    latest_version_id: model.latestVersionId,
    selected_version_id: model.selectedVersionId,
    effective_version_id: model.effectiveVersionId,
    version_count: model.versionCount || undefined
  };
}

function hasArtifactTab(tabs, id) {
  return Boolean(artifactTab(tabs, id));
}

function artifactTab(tabs, id) {
  return Array.isArray(tabs) ? tabs.find((tab) => tab && tab.id === id) : null;
}

function writeClipboardText(text) {
  const clipboard = clipboardApi();
  if (clipboard && typeof clipboard.writeText === 'function') clipboard.writeText(text);
}

function clipboardApi() {
  if (typeof navigator !== 'undefined' && navigator.clipboard) return navigator.clipboard;
  if (typeof window !== 'undefined' && window.navigator && window.navigator.clipboard) return window.navigator.clipboard;
  return null;
}

function artifactActionBaseUrl(options = {}) {
  if (options.baseUrl) return options.baseUrl;
  if (typeof window !== 'undefined' && window.location && window.location.href) return window.location.href;
  return 'http://localhost';
}
