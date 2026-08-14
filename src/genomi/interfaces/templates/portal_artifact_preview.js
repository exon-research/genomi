import { compactLine, formatShort } from './portal_format.js';
import { nodeContext } from './portal_selected_evidence.js';
import { renderArtifactActionMenu } from './portal_artifact_actions.js';
import { artifactContextForSelection } from './portal_artifact_context.js';
import { artifactSurfaceCopy, artifactVersionSelectorModel } from './portal_artifact_display_model.js';
import {
  artifactSelectionControlsMarkup,
  installArtifactSelectionControls,
  updateArtifactSelectionBar
} from './portal_artifact_selection.js';
import { renderArtifactWorkTrace } from './portal_artifact_origin_trace.js';
import { artifactProvenanceViewModel } from './portal_artifact_view_model.js';
import { markdownFilePreviewElement } from './portal_workspace_file_previews.js';

export function renderArtifactPreview(container, artifact, options = {}) {
  if (!container) return;
  container.innerHTML = '';
  if (!artifact) {
    const empty = document.createElement('div');
    empty.className = 'artifact-preview-empty';
    empty.setAttribute('data-testid', 'genomi-artifact-preview-empty');
    empty.innerHTML = '<strong>No artifact selected</strong><span>Select a file or artifact to inspect its preview, evidence, origin chat, and work history when available.</span>';
    container.appendChild(empty);
    return;
  }
  const view = artifactProvenanceViewModel(artifact, options.baseUrl || window.location.href, {
    executionCells: options.executionCells
  });
  const allTabs = view.allTabs || view.tabs;
  const activeTabId = validArtifactTabId(allTabs, options.activeTabId) || view.defaultTab;
  const renderOptions = { ...options, activeTabId };
  const model = view.preview;
  const shell = document.createElement('div');
  shell.className = 'artifact-preview-shell artifact-split-pane';
  shell.setAttribute('data-testid', 'genomi-split-right');
  shell.dataset.artifactId = model.id;
  shell.dataset.artifactKind = model.kind;
  shell.dataset.artifactRenderer = model.renderer;
  const copy = artifactSurfaceCopy(model);
  shell.dataset.artifactFamily = artifactSelectionPresentationValue(model) || model.family;
  shell.innerHTML = [
    '<div class="artifact-preview-head" data-testid="genomi-artifact-header"><div><span></span><strong></strong></div><div class="artifact-preview-actions" data-testid="genomi-artifact-actions"></div></div>',
    artifactSelectionControlsMarkup(),
    '<div class="artifact-provenance-tabs" data-testid="genomi-artifact-provenance-tabs" role="tablist"></div>',
    '<div class="artifact-tab-panels"></div>'
  ].join('');
  const meta = shell.querySelector('.artifact-preview-head span');
  meta.textContent = model.meta || '';
  meta.hidden = !meta.textContent;
  shell.querySelector('.artifact-preview-head strong').textContent = model.title;
  const actions = shell.querySelector('.artifact-preview-actions');
  const use = document.createElement('button');
  use.type = 'button';
  use.className = 'tool-action';
  use.setAttribute('data-testid', 'genomi-artifact-use-selected');
  use.textContent = copy.useLabel;
  use.title = 'Use this ' + copy.noun + ' in the next assistant turn';
  use.addEventListener('click', () => {
    if (typeof options.onUseContext === 'function') options.onUseContext(artifactContextForSelection(artifact, shell));
  });
  actions.appendChild(use);
  const versionControl = artifactVersionControl(artifact, options);
  if (versionControl) actions.appendChild(versionControl);
  const actionMenu = renderArtifactActionMenu({
    artifact,
    model,
    options: {
      ...renderOptions,
      includePreview: false,
      onActivateTab: (tabId) => {
        activateArtifactTab(shell, tabId);
        if (typeof options.onTabChange === 'function') options.onTabChange(tabId);
      }
    },
    mode: 'preview',
    shell,
    linkScope: {
      includeSelectedVersion: true,
      includeActiveTab: true
    },
    tabs: allTabs
  });
  if (actionMenu) actions.appendChild(actionMenu);
  installArtifactSelectionControls(shell, {
    onUseSelection: () => {
      if (typeof options.onUseContext === 'function') options.onUseContext(artifactContextForSelection(artifact, shell));
    },
    onAskSelection: typeof options.onAskContext === 'function'
      ? () => options.onAskContext(artifactContextForSelection(artifact, shell))
      : null,
    onDraftSelection: typeof options.onDraftContext === 'function'
      ? () => options.onDraftContext(artifactContextForSelection(artifact, shell))
      : null
  });
  const tabbar = shell.querySelector('.artifact-provenance-tabs');
  const panels = shell.querySelector('.artifact-tab-panels');
  view.tabs.forEach((tab) => {
    const panel = artifactTabPanel(tab);
    renderArtifactTabPanel(panel, tab, artifact, renderOptions);
    tabbar.appendChild(artifactTabButton(tab, shell, renderOptions));
    panels.appendChild(panel);
  });
  (view.secondaryTabs || []).forEach((tab) => {
    const panel = artifactTabPanel(tab, { ariaLabel: tab.label });
    renderArtifactTabPanel(panel, tab, artifact, renderOptions);
    panels.appendChild(panel);
  });
  activateArtifactTab(shell, activeTabId);
  updateArtifactSelectionBar(shell);
  container.appendChild(shell);
}

function artifactSelectionPresentationValue(model) {
  const presentation = model && model.presentation;
  if (!presentation || !presentation.surfaceCopy || !Object.keys(presentation.surfaceCopy).length) return '';
  return JSON.stringify(presentation);
}

function artifactVersionControl(artifact, options) {
  const selector = artifactVersionSelectorModel(artifact);
  if (!selector.visible) return null;
  const label = document.createElement('label');
  label.className = 'artifact-version-control';
  label.setAttribute('data-testid', 'genomi-artifact-version-control');
  const caption = document.createElement('span');
  caption.textContent = 'Version';
  const select = document.createElement('select');
  select.setAttribute('data-testid', 'genomi-artifact-version-select');
  select.value = selector.value;
  select.disabled = typeof options.onVersionChange !== 'function';
  selector.options.forEach((item) => {
    const option = document.createElement('option');
    option.value = item.value;
    option.textContent = item.label;
    select.appendChild(option);
  });
  select.value = selector.value;
  select.addEventListener('change', () => {
    if (typeof options.onVersionChange === 'function') options.onVersionChange(select.value);
  });
  label.appendChild(caption);
  label.appendChild(select);
  return label;
}

function artifactTabButton(tab, shell, options) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'artifact-tab';
  button.id = artifactTabButtonId(tab.id);
  button.setAttribute('role', 'tab');
  button.setAttribute('aria-controls', artifactTabPanelId(tab.id));
  button.setAttribute('data-artifact-tab', tab.id);
  button.setAttribute('data-testid', tab.testId);
  button.innerHTML = '<span></span>';
  button.querySelector('span').textContent = tab.label;
  if (tab.badge) {
    const badge = document.createElement('strong');
    badge.textContent = tab.badge;
    button.appendChild(badge);
  }
  button.addEventListener('click', () => {
    activateArtifactTab(shell, tab.id);
    if (typeof options.onTabChange === 'function') options.onTabChange(tab.id);
  });
  return button;
}

function artifactTabPanel(tabOrId, options = {}) {
  const id = typeof tabOrId === 'object' && tabOrId ? tabOrId.id : tabOrId;
  const panel = document.createElement('div');
  panel.className = 'artifact-tab-panel';
  panel.id = artifactTabPanelId(id);
  panel.setAttribute('role', 'tabpanel');
  if (options.ariaLabel) panel.setAttribute('aria-label', options.ariaLabel);
  else panel.setAttribute('aria-labelledby', artifactTabButtonId(id));
  panel.setAttribute('data-artifact-panel', id);
  panel.setAttribute('data-testid', 'genomi-artifact-panel-' + id);
  return panel;
}

function activateArtifactTab(shell, activeId) {
  shell.dataset.activeArtifactTab = activeId;
  shell.querySelectorAll('[data-artifact-tab]').forEach((button) => {
    const active = button.getAttribute('data-artifact-tab') === activeId;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
    button.tabIndex = active ? 0 : -1;
  });
  shell.querySelectorAll('[data-artifact-panel]').forEach((panel) => {
    panel.hidden = panel.getAttribute('data-artifact-panel') !== activeId;
  });
}

function validArtifactTabId(tabs, tabId) {
  const cleanTabId = String(tabId || '').trim();
  return cleanTabId && tabs.some((tab) => tab.id === cleanTabId) ? cleanTabId : '';
}

function artifactTabButtonId(id) {
  return 'artifact-tab-' + id;
}

function artifactTabPanelId(id) {
  return 'artifact-panel-' + id;
}

function renderArtifactTabPanel(panel, tab, artifact, options = {}) {
  if (tab.kind === 'preview') {
    renderPreviewPanel(panel, tab.model);
    return;
  }
  if (tab.kind === 'work-trace') {
    const wrapper = document.createElement('div');
    wrapper.className = 'artifact-insight artifact-work-trace';
    if (tab.model && tab.model.testId) wrapper.setAttribute('data-testid', tab.model.testId);
    renderArtifactWorkTrace(wrapper, artifact, options);
    panel.appendChild(wrapper);
    return;
  }
  panel.appendChild(artifactPanelElement(tab.model));
}

function renderPreviewPanel(panel, model) {
  if (model.previewable) {
    if (isTextPreview(model)) {
      renderTextFilePreview(panel, model);
      return;
    }
    const iframe = document.createElement('iframe');
    iframe.className = 'artifact-preview-frame';
    iframe.setAttribute('data-testid', 'genomi-artifact-preview-frame');
    iframe.title = model.title + ' preview';
    iframe.src = model.previewUrl;
    iframe.loading = 'lazy';
    iframe.referrerPolicy = 'no-referrer';
    iframe.sandbox = 'allow-scripts';
    panel.appendChild(iframe);
    return;
  }
  const notice = document.createElement('div');
  notice.className = 'artifact-preview-empty';
  notice.setAttribute('data-testid', 'genomi-artifact-preview-unavailable');
  notice.innerHTML = '<strong>Preview unavailable</strong><span></span>';
  notice.querySelector('span').textContent = model.reason || 'Open this artifact in a separate tab.';
  panel.appendChild(notice);
}

function renderTextFilePreview(panel, model) {
  const preview = document.createElement('pre');
  preview.className = 'artifact-file-preview';
  preview.setAttribute('data-testid', 'genomi-artifact-file-preview');
  preview.textContent = 'Loading preview...';
  panel.appendChild(preview);
  fetch(model.previewUrl, { credentials: 'same-origin' })
    .then((response) => {
      if (!response.ok) throw new Error('preview unavailable');
      return response.text();
    })
    .then((text) => {
      const visibleText = previewText(text);
      if (isMarkdownTextPreview(model)) {
        panel.innerHTML = '';
        panel.appendChild(markdownFilePreviewElement({ text: visibleText }));
      } else {
        preview.textContent = visibleText;
      }
    })
    .catch(() => {
      preview.textContent = 'Preview unavailable. Open the file to inspect it.';
    });
}

function isMarkdownTextPreview(model) {
  const version = model && model.effectiveVersion && typeof model.effectiveVersion === 'object' ? model.effectiveVersion : {};
  const contentType = String(version.content_type || '').toLowerCase();
  const title = String(model && model.title || '').toLowerCase();
  return contentType === 'text/markdown' || title.endsWith('.md') || title.endsWith('.markdown');
}

function isTextPreview(model) {
  if (!model || model.family !== 'file') return false;
  const version = model && model.effectiveVersion && typeof model.effectiveVersion === 'object' ? model.effectiveVersion : {};
  const contentType = String(version.content_type || '').toLowerCase();
  return (
    (contentType.startsWith('text/') && contentType !== 'text/html') ||
    contentType === 'application/json' ||
    contentType === 'application/xml' ||
    contentType.endsWith('+json') ||
    contentType.endsWith('+xml')
  );
}

function previewText(text) {
  const clean = String(text || '');
  if (clean.length <= 24000) return clean;
  return clean.slice(0, 24000) + '\n\n[Preview truncated]';
}

function artifactPanelElement(model) {
  const panel = document.createElement('div');
  panel.className = 'artifact-insight' + (model.className ? ' ' + model.className : '');
  const selectable = model.selectable !== false;
  if (model.testId) panel.setAttribute('data-testid', model.testId);
  panel.innerHTML = '<div class="artifact-insight-head"><strong></strong><div class="artifact-insight-metrics"></div></div><div class="artifact-insight-sections"></div>';
  panel.querySelector('.artifact-insight-head strong').textContent = model.title;
  const metrics = panel.querySelector('.artifact-insight-metrics');
  model.metrics.forEach((item) => metrics.appendChild(artifactMetric(item)));
  const sections = panel.querySelector('.artifact-insight-sections');
  const codeBlocks = artifactCodeBlocks(model.codeBlocks);
  if (codeBlocks) panel.insertBefore(codeBlocks, sections);
  model.sections.forEach((section) => sections.appendChild(artifactSection(section, selectable)));
  return panel;
}

function artifactCodeBlocks(blocks) {
  const items = Array.isArray(blocks) ? blocks.filter((block) => block && block.code) : [];
  if (!items.length) return null;
  const wrapper = document.createElement('div');
  wrapper.className = 'artifact-code-blocks';
  items.forEach((block) => {
    const item = document.createElement('div');
    item.className = 'artifact-code-block';
    item.innerHTML = '<div><span></span><strong></strong></div><pre></pre>';
    item.querySelector('span').textContent = block.language || 'text';
    item.querySelector('strong').textContent = block.label || 'Code';
    item.querySelector('pre').textContent = block.code;
    wrapper.appendChild(item);
  });
  return wrapper;
}

function artifactMetric(metric) {
  const el = document.createElement('div');
  el.className = 'artifact-insight-metric';
  el.innerHTML = '<span></span><strong></strong>';
  el.querySelector('span').textContent = metric.label;
  el.querySelector('strong').textContent = compactLine(formatShort(metric.value), 64);
  return el;
}

function artifactSection(section, panelSelectable) {
  const el = document.createElement('div');
  el.className = 'artifact-insight-section';
  el.innerHTML = '<div class="artifact-insight-title"></div><div class="artifact-insight-nodes"></div>';
  el.querySelector('.artifact-insight-title').textContent = section.title;
  const nodes = el.querySelector('.artifact-insight-nodes');
  const selectable = panelSelectable && section.selectable !== false;
  section.nodes.forEach((node) => nodes.appendChild(artifactNode(section.title, node, selectable)));
  return el;
}

function artifactNode(sectionTitle, item, sectionSelectable) {
  const selectable = sectionSelectable && item.selectable !== false;
  const node = document.createElement(selectable ? 'button' : 'div');
  if (selectable) node.type = 'button';
  node.className = selectable ? 'artifact-node evidence-node' : 'artifact-node artifact-node-static';
  node.dataset.selectable = selectable ? 'true' : 'false';
  node.dataset.label = item.label;
  node.dataset.value = item.summary || formatShort(item.value);
  if (selectable) node.dataset.context = nodeContext(sectionTitle + ' / ' + item.label, item.value);
  node.innerHTML = '<span></span><strong></strong>';
  node.querySelector('span').textContent = compactLine(item.label, 52);
  node.querySelector('strong').textContent = compactLine(item.summary || formatShort(item.value), 140);
  if (selectable) {
    node.addEventListener('click', (event) => {
      event.stopPropagation();
      node.classList.toggle('selected');
      const shell = node.closest('.artifact-preview-shell');
      if (shell) updateArtifactSelectionBar(shell);
    });
  }
  return node;
}
