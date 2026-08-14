export function createActiveContextClient({
  api,
  state,
  activeArtifact,
  artifactPreviewModel,
  windowRef,
  documentRef,
  debounceMs = 120
} = {}) {
  const browserWindow = windowRef || (typeof window !== 'undefined' ? window : null);
  const browserDocument = documentRef || (typeof document !== 'undefined' ? document : null);
  let timer = null;
  let serial = 0;

  function schedule() {
    if (!state || !state.project) return;
    if (timer) clearTimer(timer);
    timer = setTimer(() => {
      timer = null;
      syncNow().catch(() => undefined);
    }, debounceMs);
  }

  async function syncNow() {
    if (!state || !state.project) return null;
    if (timer) {
      clearTimer(timer);
      timer = null;
    }
    serial += 1;
    const currentSerial = serial;
    const result = await api.updateActiveContext(state.project.project_id, payload());
    return serial === currentSerial ? result : null;
  }

  function payload() {
    const artifact = typeof activeArtifact === 'function' ? activeArtifact() : null;
    const model = artifact && typeof artifactPreviewModel === 'function'
      ? artifactPreviewModel(artifact, currentHref())
      : null;
    return {
      route: currentRoute(),
      workspaceSection: state.activeWorkspaceSection || activeWorkspaceSectionFromDom(),
      panel: activeWorkspacePanelLabel(),
      frameId: state.frameId || '',
      artifactId: state.activeArtifactId || '',
      artifactVersionId: state.activeArtifactVersionId || '',
      artifactTabId: state.activeArtifactTabId || '',
      artifactTabLabel: activeArtifactTabLabelFromDom(),
      artifactTitle: (model && model.title) || (artifact && artifact.title) || ''
    };
  }

  function activeWorkspaceSectionFromDom() {
    const active = browserDocument && browserDocument.querySelector
      ? browserDocument.querySelector('[data-nav-target].active')
      : null;
    return active ? active.getAttribute('data-nav-target') || 'research-workspace' : 'research-workspace';
  }

  function activeWorkspacePanelLabel() {
    const section = state.activeWorkspaceSection || activeWorkspaceSectionFromDom();
    const button = browserDocument && browserDocument.querySelector
      ? browserDocument.querySelector('[data-nav-target="' + section + '"]')
      : null;
    return button ? button.textContent.trim() : section;
  }

  function activeArtifactTabLabelFromDom() {
    const tabId = state.activeArtifactTabId || '';
    if (!browserDocument || !browserDocument.querySelector) return '';
    const active = browserDocument.querySelector('[data-artifact-tab].active');
    if (active) return artifactTabElementLabel(active);
    if (!tabId) return '';
    const selected = browserDocument.querySelector('[data-artifact-tab="' + cssEscape(tabId) + '"]');
    return selected ? artifactTabElementLabel(selected) : '';
  }

  function artifactTabElementLabel(element) {
    const label = element && element.querySelector ? element.querySelector('span') : null;
    return (label ? label.textContent : element.textContent).trim();
  }

  function currentRoute() {
    const location = currentLocation();
    return (location.pathname || '') + (location.search || '') + (location.hash || '');
  }

  function currentHref() {
    const location = currentLocation();
    return location.href || currentRoute();
  }

  function currentLocation() {
    return browserWindow && browserWindow.location ? browserWindow.location : {};
  }

  function cssEscape(value) {
    if (browserWindow && browserWindow.CSS && typeof browserWindow.CSS.escape === 'function') {
      return browserWindow.CSS.escape(value);
    }
    return String(value || '').replace(/["\\]/g, '\\$&');
  }

  function setTimer(callback, delay) {
    const clock = browserWindow || globalThis;
    return clock.setTimeout(callback, delay);
  }

  function clearTimer(value) {
    const clock = browserWindow || globalThis;
    clock.clearTimeout(value);
  }

  return { payload, schedule, syncNow };
}
