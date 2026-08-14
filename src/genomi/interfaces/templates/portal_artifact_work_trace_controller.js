import { artifactOriginContextModel } from './portal_artifact_messages.js';
import { executionCellsFromRunPackages, runIdsFromMessages } from './portal_work_trace_controller.js';

export function createArtifactWorkTraceController(options = {}) {
  const api = options.api || {};
  const cellsByKey = new Map();
  const loadingKeys = new Set();
  let activeKey = '';

  function executionCellsFor(artifact) {
    const key = artifactWorkTraceKey(artifact);
    return key ? (cellsByKey.get(key) || []) : [];
  }

  async function hydrate(artifact) {
    const key = artifactWorkTraceKey(artifact);
    activeKey = key;
    if (!key || cellsByKey.has(key) || loadingKeys.has(key)) return false;
    const runIds = artifactWorkTraceRunIds(artifact);
    if (!runIds.length) {
      cellsByKey.set(key, []);
      return false;
    }
    loadingKeys.add(key);
    try {
      const packages = await Promise.allSettled(runIds.map((runId) => loadRunResultPackage(runId)));
      const cells = executionCellsFromRunPackages(packages, runIds);
      cellsByKey.set(key, cells);
      if (activeKey === key && typeof options.onUpdate === 'function') options.onUpdate(artifact);
      return true;
    } finally {
      loadingKeys.delete(key);
    }
  }

  function reset(options = {}) {
    activeKey = '';
    if (options.clearCache) {
      cellsByKey.clear();
      loadingKeys.clear();
    }
  }

  function clearCache() {
    reset({ clearCache: true });
  }

  async function loadRunResultPackage(runId) {
    if (typeof api.loadRunResultPackage !== 'function') return {};
    return api.loadRunResultPackage(runId);
  }

  return {
    clearCache,
    executionCellsFor,
    hydrate,
    reset
  };
}

export function artifactWorkTraceRunIds(artifact) {
  const seen = new Set();
  const secondaryIds = [];
  function cleanRunId(runId) {
    const clean = String(runId || '').trim();
    return clean;
  }
  function addPrimary(runId) {
    const clean = cleanRunId(runId);
    if (!clean || seen.has(clean)) return '';
    seen.add(clean);
    return clean;
  }
  function addSecondary(runId) {
    const clean = cleanRunId(runId);
    if (!clean || seen.has(clean)) return;
    seen.add(clean);
    secondaryIds.push(clean);
  }
  const origin = artifactOriginContextModel(artifact);
  const producingRunId = addPrimary(origin && origin.producingRunId);
  (Array.isArray(origin && origin.runIds) ? origin.runIds : []).forEach(addSecondary);
  const provenance = artifact && artifact.provenance_messages;
  runIdsFromMessages(provenance && provenance.messages).forEach(addSecondary);
  return [producingRunId, ...secondaryIds.slice(-8)].filter(Boolean);
}

function artifactWorkTraceKey(artifact) {
  const id = String(artifact && artifact.id || '').trim();
  if (!id) return '';
  const runIds = artifactWorkTraceRunIds(artifact);
  return JSON.stringify([
    artifactProjectId(artifact),
    id,
    artifactVersionIdentity(artifact),
    runIds
  ]);
}

function artifactProjectId(artifact) {
  return firstText(artifact && artifact.project_id, artifact && artifact.projectId);
}

function artifactVersionIdentity(artifact) {
  const latestVersionId = firstText(
    artifact && artifact.latest_version_id,
    artifact && artifact.latestVersionId,
    artifact && artifact.latest_version && artifact.latest_version.version_id,
    artifact && artifact.latest_version && artifact.latest_version.versionId,
    artifact && artifact.latestVersion && artifact.latestVersion.version_id,
    artifact && artifact.latestVersion && artifact.latestVersion.versionId
  );
  const selectedVersionId = firstText(
    artifact && artifact.selected_version_id,
    artifact && artifact.selectedVersionId,
    artifact && artifact.selected_version && artifact.selected_version.version_id,
    artifact && artifact.selected_version && artifact.selected_version.versionId,
    artifact && artifact.selectedVersion && artifact.selectedVersion.version_id,
    artifact && artifact.selectedVersion && artifact.selectedVersion.versionId
  );
  const effectiveVersionId = firstText(
    artifact && artifact.effective_version_id,
    artifact && artifact.effectiveVersionId,
    artifact && artifact.effective_version && artifact.effective_version.version_id,
    artifact && artifact.effective_version && artifact.effective_version.versionId,
    artifact && artifact.effectiveVersion && artifact.effectiveVersion.version_id,
    artifact && artifact.effectiveVersion && artifact.effectiveVersion.versionId,
    selectedVersionId,
    latestVersionId
  );
  return [selectedVersionId, latestVersionId, effectiveVersionId].join('|');
}

function firstText(...values) {
  for (const value of values) {
    const clean = String(value || '').trim();
    if (clean) return clean;
  }
  return '';
}
