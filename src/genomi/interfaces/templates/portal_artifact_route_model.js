export function parsePortalRoute(pathname = '/', search = '') {
  const segments = routeSegments(pathname);
  if (segments[0] !== 'projects' || !segments[1]) return {};
  const projectId = segments[1];
  if (segments.length === 2) return { kind: 'project', projectId };
  if (segments[2] === 'frames' && segments[3] && segments.length === 4) {
    return frameRouteWithHighlight({ kind: 'frame', projectId, frameId: segments[3] }, pathname, search);
  }
  if (segments[2] === 'artifacts' && segments[3] && segments.length === 4) {
    return artifactRouteWithTab({ kind: 'artifact', projectId, artifactId: segments[3] }, pathname, search);
  }
  if (segments[2] === 'artifacts' && segments[3] && segments[4] === 'versions' && segments[5] && segments.length === 6) {
    return artifactRouteWithTab(
      { kind: 'artifact_version', projectId, artifactId: segments[3], versionId: segments[5] },
      pathname,
      search
    );
  }
  return {};
}

export function projectRoutePath(projectId) {
  const cleanProjectId = firstText(projectId);
  return cleanProjectId ? '/projects/' + encodeURIComponent(cleanProjectId) : '/';
}

export function frameRoutePath(projectId, frameId, highlightRunId = '', highlightStepId = '') {
  const cleanFrameId = firstText(frameId);
  const base = projectRoutePath(projectId);
  if (!cleanFrameId || base === '/') return base;
  return base + '/frames/' + encodeURIComponent(cleanFrameId) + frameRouteSearch(highlightRunId, highlightStepId);
}

export function artifactRoutePath(projectId, artifactId, versionId = '', artifactTabId = '') {
  const cleanArtifactId = firstText(artifactId);
  const projectPath = projectRoutePath(projectId);
  if (!cleanArtifactId || projectPath === '/') return projectPath;
  const base = projectPath + '/artifacts/' + encodeURIComponent(cleanArtifactId);
  const cleanVersionId = firstText(versionId);
  const routePath = cleanVersionId ? base + '/versions/' + encodeURIComponent(cleanVersionId) : base;
  return routePath + artifactRouteSearch(artifactTabId);
}

export function artifactRouteSearch(artifactTabId = '') {
  const cleanTabId = normalizeArtifactTabId(artifactTabId);
  return cleanTabId ? '?artifact_tab=' + encodeURIComponent(cleanTabId) : '';
}

export function frameRouteSearch(highlightRunId = '', highlightStepId = '') {
  const cleanRunId = normalizeHighlightRunId(highlightRunId);
  const cleanStepId = normalizeHighlightStepId(highlightStepId);
  const params = [];
  if (cleanRunId) params.push('highlight_run=' + encodeURIComponent(cleanRunId));
  if (cleanStepId) params.push('highlight_step=' + encodeURIComponent(cleanStepId));
  return params.length ? '?' + params.join('&') : '';
}

export function artifactWorkspaceUrl(projectId, artifactId, versionId = '', baseUrl = 'http://localhost', artifactTabId = '') {
  return absolutePortalUrl(artifactRoutePath(projectId, artifactId, versionId, artifactTabId), baseUrl);
}

export function absolutePortalUrl(path, baseUrl = 'http://localhost') {
  const cleanPath = firstText(path);
  if (!cleanPath) return '';
  try {
    return new URL(cleanPath, firstText(baseUrl) || 'http://localhost').href;
  } catch {
    return cleanPath;
  }
}

export function artifactRouteState(route) {
  return {
    artifactId: firstText(route && route.artifactId) || null,
    artifactVersionId: firstText(route && route.versionId) || null,
    artifactTabId: normalizeArtifactTabId(route && route.artifactTabId) || null,
    hasArtifactRoute: Boolean(route && route.artifactId)
  };
}

export function resolveArtifactRouteSelection({
  route,
  projectId,
  artifacts,
  activeArtifactId,
  activeArtifactVersionId,
  activeArtifactTabId,
  isPreviewableArtifact
} = {}) {
  const routeState = artifactRouteState(route);
  const cleanProjectId = firstText(projectId);
  const routeProjectMatches = Boolean(route && route.projectId && route.projectId === cleanProjectId);
  const routeArtifactId = routeProjectMatches ? routeState.artifactId : null;
  const normalizedArtifacts = artifactList(artifacts);
  const routeArtifact = routeArtifactId ? artifactById(normalizedArtifacts, routeArtifactId) : null;
  if (routeArtifact) {
    return {
      artifact: routeArtifact,
      artifactId: routeArtifact.id,
      artifactVersionId: routeState.artifactVersionId,
      artifactTabId: routeState.artifactTabId,
      routeArtifactId,
      routeArtifactFound: true,
      normalizeToProject: false,
      selectionSource: 'route'
    };
  }

  const cleanActiveArtifactId = firstText(activeArtifactId);
  const activeArtifact = cleanActiveArtifactId ? artifactById(normalizedArtifacts, cleanActiveArtifactId) : null;
  if (activeArtifact) {
    return {
      artifact: activeArtifact,
      artifactId: activeArtifact.id,
      artifactVersionId: firstText(activeArtifactVersionId) || null,
      artifactTabId: normalizeArtifactTabId(activeArtifactTabId) || null,
      routeArtifactId,
      routeArtifactFound: false,
      normalizeToProject: false,
      selectionSource: 'current'
    };
  }

  return {
    artifact: null,
    artifactId: null,
    artifactVersionId: null,
    artifactTabId: null,
    routeArtifactId,
    routeArtifactFound: false,
    normalizeToProject: Boolean(routeArtifactId),
    selectionSource: 'none'
  };
}

export function normalizeArtifactTabId(value) {
  const text = firstText(value).toLowerCase();
  return /^[a-z][a-z0-9_-]{0,40}$/.test(text) ? text : '';
}

export function normalizeHighlightRunId(value) {
  return firstText(value).slice(0, 160);
}

export function normalizeHighlightStepId(value) {
  return firstText(value).slice(0, 220);
}

export function artifactWithSelectedVersion(artifact, requestedVersionId) {
  if (!artifact || typeof artifact !== 'object' || Array.isArray(artifact)) return artifact || null;
  const validation = validateRequestedArtifactVersion(artifact, requestedVersionId);
  return validation.artifact;
}

export function validateRequestedArtifactVersion(artifact, requestedVersionId) {
  const cleanRequestedVersionId = firstText(requestedVersionId);
  const cleanArtifact = artifact && typeof artifact === 'object' && !Array.isArray(artifact) ? artifact : {};
  if (!cleanRequestedVersionId) {
    return {
      artifact: cleanArtifact,
      requestedVersionId: null,
      selectedVersion: null,
      selectedVersionId: null,
      valid: true,
      shouldNormalizeToArtifact: false
    };
  }
  const selectedVersion = versionById(artifactVersions(cleanArtifact), cleanRequestedVersionId);
  if (selectedVersion) {
    return {
      artifact: { ...cleanArtifact, selected_version_id: selectedVersion.version_id },
      requestedVersionId: cleanRequestedVersionId,
      selectedVersion,
      selectedVersionId: selectedVersion.version_id,
      valid: true,
      shouldNormalizeToArtifact: false
    };
  }
  const normalizedArtifact = { ...cleanArtifact };
  delete normalizedArtifact.selected_version_id;
  delete normalizedArtifact.selectedVersionId;
  return {
    artifact: normalizedArtifact,
    requestedVersionId: cleanRequestedVersionId,
    selectedVersion: null,
    selectedVersionId: null,
    valid: false,
    shouldNormalizeToArtifact: true
  };
}

function routeSegments(pathname) {
  const cleanPath = String(pathname || '/').split(/[?#]/, 1)[0] || '/';
  return cleanPath.split('/').filter(Boolean).map(safeDecodeURIComponent);
}

function artifactRouteWithTab(route, pathname, search) {
  const artifactTabId = artifactTabIdFromSearch(pathname, search);
  return artifactTabId ? { ...route, artifactTabId } : route;
}

function frameRouteWithHighlight(route, pathname, search) {
  const highlightRunId = highlightRunIdFromSearch(pathname, search);
  const highlightStepId = highlightStepIdFromSearch(pathname, search);
  return cleanObject({
    ...route,
    highlightRunId: highlightRunId || undefined,
    highlightStepId: highlightStepId || undefined
  });
}

function artifactTabIdFromSearch(pathname, search) {
  const params = routeSearchParams(pathname, search);
  return normalizeArtifactTabId(params.get('artifact_tab'));
}

function highlightRunIdFromSearch(pathname, search) {
  const params = routeSearchParams(pathname, search);
  return normalizeHighlightRunId(params.get('highlight_run'));
}

function highlightStepIdFromSearch(pathname, search) {
  const params = routeSearchParams(pathname, search);
  return normalizeHighlightStepId(params.get('highlight_step'));
}

function routeSearchParams(pathname, search) {
  const explicitSearch = firstText(search);
  if (explicitSearch) return new URLSearchParams(explicitSearch.startsWith('?') ? explicitSearch.slice(1) : explicitSearch);
  const text = String(pathname || '');
  const queryStart = text.indexOf('?');
  if (queryStart < 0) return new URLSearchParams();
  return new URLSearchParams(text.slice(queryStart + 1).split('#', 1)[0]);
}

function safeDecodeURIComponent(value) {
  try {
    return decodeURIComponent(value);
  } catch {
    return String(value || '');
  }
}

function artifactList(artifacts) {
  return Array.isArray(artifacts)
    ? artifacts.filter((artifact) => artifact && typeof artifact === 'object' && !Array.isArray(artifact) && firstText(artifact.id))
    : [];
}

function artifactById(artifacts, artifactId) {
  const cleanArtifactId = firstText(artifactId);
  return artifacts.find((artifact) => firstText(artifact.id) === cleanArtifactId) || null;
}

function artifactVersions(artifact) {
  return Array.isArray(artifact && artifact.versions)
    ? artifact.versions.filter((version) => version && typeof version === 'object' && !Array.isArray(version) && firstText(version.version_id))
    : [];
}

function versionById(versions, versionId) {
  const cleanVersionId = firstText(versionId);
  return versions.find((version) => firstText(version.version_id) === cleanVersionId) || null;
}

function firstText(...values) {
  for (const value of values) {
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return '';
}

function cleanObject(value) {
  return Object.fromEntries(Object.entries(value || {}).filter(([, item]) => item !== undefined && item !== null && item !== ''));
}
