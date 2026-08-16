import { portalSessionHeaders } from './portal_session.js';

export async function fetchJson(path) {
  const response = await fetch(path, { headers: portalSessionHeaders() });
  return parseJsonResponse(response);
}

export async function postJson(path, payload = {}) {
  const response = await fetch(path, {
    method: 'POST',
    headers: postHeaders(),
    body: JSON.stringify(payload)
  });
  return parseJsonResponse(response);
}

export async function loadPortalRuntime(projectId = '') {
  const [context, assistants] = await Promise.all([
    fetchJson('/api/context' + projectQuery(projectId)),
    fetchJson('/api/agents' + projectQuery(projectId))
  ]);
  return { context, agents: assistants.agents || [], assistant: assistants.assistant || {} };
}

export async function selectWorkspaceAssistant(projectId, agentId) {
  return postJson('/api/projects/' + encodeURIComponent(projectId) + '/assistant', { agentId });
}

export async function loadGenomeInventory(projectId = '') {
  return fetchJson('/api/genomes' + projectQuery(projectId));
}

export async function selectGenome(projectId, payload = {}) {
  return postJson('/api/genomes/select', { ...payload, projectId });
}

export async function loadProjects() {
  return fetchJson('/api/projects');
}

export async function loadProject(routeProjectId) {
  if (routeProjectId) return fetchJson('/api/projects/' + encodeURIComponent(routeProjectId));
  const payload = await fetchJson('/api/projects/current');
  return payload.project || payload;
}

export async function createProject(name) {
  const payload = await postJson('/api/projects', { name });
  return payload.project || payload;
}

export async function selectProject(projectId) {
  const payload = await postJson('/api/projects/' + encodeURIComponent(projectId) + '/select', {});
  return payload.project || payload;
}

export async function renameProject(projectId, name) {
  const payload = await postJson('/api/projects/' + encodeURIComponent(projectId) + '/rename', { name });
  return payload.project || payload;
}

export async function loadProjectFrames(projectId) {
  return fetchJson('/api/projects/' + encodeURIComponent(projectId) + '/frames');
}

export async function renameConversation(projectId, frameId, title) {
  const payload = await postJson(
    '/api/projects/' + encodeURIComponent(projectId) + '/frames/' + encodeURIComponent(frameId) + '/rename',
    { title }
  );
  return payload.frame || payload;
}

export async function loadProjectArtifacts(projectId) {
  return fetchJson('/api/projects/' + encodeURIComponent(projectId) + '/artifacts');
}

export async function loadProjectWorkspaceFiles(projectId) {
  return fetchJson('/api/projects/' + encodeURIComponent(projectId) + '/workspace/files');
}

export async function loadProjectWorkspaceFilePreview(projectId, relativePath) {
  return fetchJson('/api/projects/' + encodeURIComponent(projectId) + '/workspace/file-preview?path=' + encodeURIComponent(relativePath || ''));
}

export async function loadActiveContext(projectId) {
  return fetchJson(activeContextEndpoint(projectId));
}

export async function updateActiveContext(projectId, payload = {}) {
  return postJson(activeContextEndpoint(projectId), payload);
}

export async function loadGenomiLabBoard(projectId) {
  return fetchJson(genomiLabEndpoint(projectId, 'board'));
}

export async function importProjectFile(projectId, payload = {}) {
  return postJson('/api/projects/' + encodeURIComponent(projectId) + '/artifacts/import', payload);
}

export async function loadArtifact(projectId, artifactId) {
  return fetchJson(projectArtifactEndpoint(projectId, artifactId));
}

export async function loadArtifactVersions(projectId, artifactId) {
  return fetchJson(projectArtifactEndpoint(projectId, artifactId) + '/versions');
}

export function artifactMetadataEndpoint(projectId, artifactId) {
  const endpoint = projectArtifactEndpoint(projectId, artifactId);
  return endpoint ? endpoint + '/metadata' : '';
}

export function artifactMetadataUrl(projectId, artifactId, baseUrl = 'http://localhost') {
  const endpoint = artifactMetadataEndpoint(projectId, artifactId);
  return endpoint ? absoluteApiUrl(endpoint, baseUrl) : '';
}

export function artifactBundleEndpoint(projectId, artifactId) {
  const endpoint = projectArtifactEndpoint(projectId, artifactId);
  return endpoint ? endpoint + '/bundle' : '';
}

export function artifactBundleUrl(projectId, artifactId, baseUrl = 'http://localhost') {
  const endpoint = artifactBundleEndpoint(projectId, artifactId);
  return endpoint ? absoluteApiUrl(endpoint, baseUrl) : '';
}

export function artifactScriptBundleEndpoint(projectId, artifactId, versionId = '') {
  const endpoint = projectArtifactEndpoint(projectId, artifactId);
  if (!endpoint) return '';
  const cleanVersionId = firstText(versionId);
  return cleanVersionId
    ? endpoint + '/versions/' + encodeURIComponent(cleanVersionId) + '/script-bundle'
    : endpoint + '/script-bundle';
}

export function artifactScriptBundleUrl(projectId, artifactId, versionId = '', baseUrl = 'http://localhost') {
  const endpoint = artifactScriptBundleEndpoint(projectId, artifactId, versionId);
  return endpoint ? absoluteApiUrl(endpoint, baseUrl) : '';
}

export function artifactReviewRunsEndpoint(projectId, artifactId, versionId = '') {
  const endpoint = projectArtifactEndpoint(projectId, artifactId);
  if (!endpoint) return '';
  const cleanVersionId = firstText(versionId);
  return cleanVersionId
    ? endpoint + '/versions/' + encodeURIComponent(cleanVersionId) + '/review-runs'
    : endpoint + '/review-runs';
}

export async function runArtifactReview(projectId, artifactId, versionId = '') {
  return postJson(artifactReviewRunsEndpoint(projectId, artifactId, versionId), {});
}

export async function loadArtifactInspection(projectId, artifactId) {
  const [artifact, versions] = await Promise.all([
    loadArtifact(projectId, artifactId),
    loadArtifactVersions(projectId, artifactId)
  ]);
  return {
    ...artifact,
    versions: Array.isArray(versions.versions) ? versions.versions : [],
    versions_loaded: true
  };
}

export async function loadTools() {
  return fetchJson('/api/tools');
}

export async function loadSourceLookups() {
  return fetchJson('/api/source-lookups');
}

export async function attachEvidenceSource(operationId, params = {}) {
  return postJson('/api/evidence-sources/attach', { operationId, params });
}

export async function loadFrame(frameId, projectId) {
  return fetchJson('/api/frames/' + encodeURIComponent(frameId) + projectFrameQuery(projectId));
}

export async function loadFrameMessages(frameId, projectId) {
  return fetchJson('/api/frames/' + encodeURIComponent(frameId) + '/messages' + projectFrameQuery(projectId));
}

export async function requestConversationReview(projectId, frameId, agentId = '') {
  return postJson(
    '/api/projects/' + encodeURIComponent(projectId) + '/frames/' + encodeURIComponent(frameId) + '/reviews',
    agentId ? { agentId } : {}
  );
}

export async function loadRunResultPackage(runId) {
  return fetchJson('/api/runs/' + encodeURIComponent(runId) + '/result-package');
}

export function frameBundleEndpoint(projectId, frameId) {
  const cleanProjectId = firstText(projectId);
  const cleanFrameId = firstText(frameId);
  if (!cleanProjectId || !cleanFrameId) return '';
  return '/api/projects/' + encodeURIComponent(cleanProjectId) + '/frames/' + encodeURIComponent(cleanFrameId) + '/bundle';
}

export function frameBundleUrl(projectId, frameId, baseUrl = 'http://localhost') {
  const endpoint = frameBundleEndpoint(projectId, frameId);
  return endpoint ? absoluteApiUrl(endpoint, baseUrl) : '';
}

export async function startArtifactRender(projectId, renderer, options = {}) {
  return postJson('/api/projects/' + encodeURIComponent(projectId) + '/artifacts/render', {
    renderer,
    ...(options.frameId ? { frameId: options.frameId } : {}),
    ...(options.params ? { params: options.params } : {})
  });
}

export async function updateArtifact(projectId, artifactId, payload = {}) {
  return postJson(
    projectArtifactEndpoint(projectId, artifactId) + '/action',
    payload
  );
}

export async function submitTurn({ projectId, frameId, sourceFrameId, startedFromSelectedMaterial, message, agentId, selectedEvidence, genomeContextMode }) {
  return postJson('/api/runs', {
    message,
    projectId,
    ...(frameId ? { frameId } : {}),
    ...(sourceFrameId ? { sourceFrameId } : {}),
    ...(startedFromSelectedMaterial ? { startedFromSelectedMaterial: true } : {}),
    ...(agentId ? { agentId } : {}),
    ...(genomeContextMode ? { genomeContextMode } : {}),
    selectedEvidence: selectedEvidence || []
  });
}

export async function approveRunPermission(runId, permission = {}) {
  return postJson('/api/runs/' + encodeURIComponent(runId) + '/approve-permission', { permission });
}

export async function suggestPrompt(payload = {}) {
  return postJson('/api/prompt/suggestion', payload);
}

export function isNotFoundError(error) {
  return Boolean(error && error.status === 404 && error.code === 'not_found');
}

export class PortalApiError extends Error {
  constructor(message, options = {}) {
    super(message || 'request failed');
    this.name = 'PortalApiError';
    this.status = options.status || 0;
    this.code = options.code || '';
    this.payload = options.payload || null;
  }
}

function projectFrameQuery(projectId) {
  return projectId ? '?projectId=' + encodeURIComponent(projectId) : '';
}

function projectQuery(projectId) {
  return projectId ? '?projectId=' + encodeURIComponent(projectId) : '';
}

function activeContextEndpoint(projectId) {
  return '/api/projects/' + encodeURIComponent(projectId) + '/active-context';
}

function genomiLabEndpoint(projectId, suffix) {
  const cleanProjectId = firstText(projectId);
  const cleanSuffix = firstText(suffix).replace(/^\/+/, '');
  if (!cleanProjectId || !cleanSuffix) return '';
  return '/api/projects/' + encodeURIComponent(cleanProjectId) + '/genomilab/' + cleanSuffix;
}

function projectArtifactEndpoint(projectId, artifactId) {
  const cleanProjectId = firstText(projectId);
  const cleanArtifactId = firstText(artifactId);
  if (!cleanProjectId || !cleanArtifactId) return '';
  return '/api/projects/' + encodeURIComponent(cleanProjectId) + '/artifacts/' + encodeURIComponent(cleanArtifactId);
}

function absoluteApiUrl(path, baseUrl = 'http://localhost') {
  const cleanPath = firstText(path);
  if (!cleanPath) return '';
  try {
    return new URL(cleanPath, firstText(baseUrl) || 'http://localhost').href;
  } catch {
    return cleanPath;
  }
}

function firstText(...values) {
  for (const value of values) {
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return '';
}

async function parseJsonResponse(response) {
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const message = payload && payload.error && payload.error.message ? payload.error.message : 'request failed';
    const code = payload && payload.error && payload.error.code ? payload.error.code : '';
    throw new PortalApiError(message, {
      status: response.status,
      code,
      payload
    });
  }
  return payload;
}

function postHeaders() {
  const headers = { 'content-type': 'application/json', ...portalSessionHeaders() };
  const token = document.querySelector('meta[name="genomi-csrf-token"]')?.getAttribute('content') || '';
  if (token) headers['x-genomi-csrf'] = token;
  return headers;
}
