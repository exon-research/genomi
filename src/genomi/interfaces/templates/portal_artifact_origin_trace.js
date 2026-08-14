import { frameTraceStepContextNode, frameWorkTraceModel, renderFrameWorkTrace } from './portal_frame_trace.js';

export function artifactWorkTraceModel(artifact, options = {}) {
  const messages = artifactWorkTraceMessages(artifact);
  const trace = frameWorkTraceModel(messages, {
    executionCells: artifactWorkTraceExecutionCells(artifact, options.executionCells)
  });
  if (!trace.steps.length) return null;
  return {
    title: 'Origin work trail',
    summary: trace.summary,
    metrics: [
      metric('Steps', trace.total),
      metric('Displayed', trace.displayed),
      metric('Errors', trace.counts.errors),
      metric('Running', trace.counts.running)
    ].filter(Boolean),
    sections: [
      {
        title: 'Work steps',
        nodes: trace.steps.map((step, index) => frameTraceStepContextNode(step, index, { structuredValue: true }))
      }
    ]
  };
}

export function artifactWorkTraceMessages(artifact) {
  const provenance = object(artifact && artifact.provenance_messages);
  return Array.isArray(provenance.messages) ? provenance.messages : [];
}

export function renderArtifactWorkTrace(container, artifact, options = {}) {
  renderFrameWorkTrace(container, artifactWorkTraceMessages(artifact), {
    ...options,
    executionCells: artifactWorkTraceExecutionCells(artifact, options.executionCells),
    workTracePresentation: {
      summaryLabel: 'Origin work trail',
      summarySourceOperation: 'genomi.portal.origin_work_trail',
      summaryPromptIntro: 'Selected origin work trail:',
      stepPromptIntro: 'Selected origin work step: ',
      toolbarTitle: 'Work that produced this artifact',
      emptyTitle: 'No origin work recorded',
      emptyText: 'Tool work from the producing conversation will appear here when this artifact has origin messages.'
    }
  });
}

export function artifactWorkTraceExecutionCells(artifact, executionCells) {
  const producingCell = artifactProducingWorkStepCell(artifact);
  const target = artifactTraceIdentity(artifact);
  if (Array.isArray(executionCells)) return withProducingWorkStep(
    executionCells.filter((cell) => keepArtifactTraceCell(cell, target)),
    producingCell
  );
  if (executionCells && typeof executionCells === 'object' && Array.isArray(executionCells.items)) {
    return {
      ...executionCells,
      items: withProducingWorkStep(
        executionCells.items.filter((cell) => keepArtifactTraceCell(cell, target)),
        producingCell
      )
    };
  }
  return producingCell ? [producingCell] : executionCells;
}

function metric(label, value) {
  if (value === null || value === undefined || value === '' || value === false) return null;
  return { label, value };
}

function keepArtifactTraceCell(cell, target) {
  const item = object(cell);
  if (String(item.kind || '').trim() !== 'artifact') return true;
  const cellArtifact = object(item.artifact);
  const cellArtifactId = firstText(cellArtifact.id, item.artifact_id, item.artifactId);
  if (target.artifactId && cellArtifactId && cellArtifactId !== target.artifactId) return false;
  const targetVersionId = target.selectedVersionId || target.effectiveVersionId || target.latestVersionId;
  const cellVersionId = firstText(
    cellArtifact.selected_version_id,
    cellArtifact.selectedVersionId,
    cellArtifact.effective_version_id,
    cellArtifact.effectiveVersionId,
    cellArtifact.latest_version_id,
    cellArtifact.latestVersionId,
    item.version_id,
    item.versionId
  );
  if (targetVersionId && cellVersionId && cellArtifactId && cellArtifactId === target.artifactId && cellVersionId !== targetVersionId) {
    return false;
  }
  return true;
}

function artifactTraceIdentity(artifact) {
  const item = object(artifact);
  const selectedVersionId = firstText(
    item.selected_version_id,
    item.selectedVersionId,
    object(item.selected_version).version_id,
    object(item.selected_version).versionId,
    object(item.selectedVersion).version_id,
    object(item.selectedVersion).versionId
  );
  const latestVersionId = firstText(
    item.latest_version_id,
    item.latestVersionId,
    object(item.latest_version).version_id,
    object(item.latest_version).versionId,
    object(item.latestVersion).version_id,
    object(item.latestVersion).versionId
  );
  const effectiveVersionId = firstText(
    item.effective_version_id,
    item.effectiveVersionId,
    object(item.effective_version).version_id,
    object(item.effective_version).versionId,
    object(item.effectiveVersion).version_id,
    object(item.effectiveVersion).versionId,
    selectedVersionId,
    latestVersionId
  );
  return {
    artifactId: firstText(item.id, item.artifact_id, item.artifactId),
    selectedVersionId,
    latestVersionId,
    effectiveVersionId
  };
}

function withProducingWorkStep(cells, producingCell) {
  const items = Array.isArray(cells) ? cells : [];
  if (!producingCell) return items;
  const producingId = firstText(producingCell.id);
  if (producingId && items.some((cell) => firstText(cell && cell.id) === producingId)) return items;
  return [producingCell, ...items];
}

function artifactProducingWorkStepCell(artifact) {
  const item = object(artifact);
  const latestVersion = object(item.latest_version || item.latestVersion);
  const selectedVersion = object(item.selected_version || item.selectedVersion);
  const effectiveVersion = object(item.effective_version || item.effectiveVersion);
  const workStep = object(
    item.producing_work_step ||
    item.producingWorkStep ||
    effectiveVersion.producing_work_step ||
    effectiveVersion.producingWorkStep ||
    selectedVersion.producing_work_step ||
    selectedVersion.producingWorkStep ||
    latestVersion.producing_work_step ||
    latestVersion.producingWorkStep
  );
  if (firstText(workStep.kind) !== 'artifact_producing_work_step') return null;
  const identity = artifactTraceIdentity(item);
  const origin = object(workStep.origin);
  const artifactInfo = object(workStep.artifact);
  const executionCell = object(workStep.execution_cell || workStep.executionCell);
  const projectId = firstText(item.project_id, item.projectId);
  const artifactId = firstText(item.id, item.artifact_id, item.artifactId);
  const versionId = firstText(identity.effectiveVersionId, identity.latestVersionId, identity.selectedVersionId);
  const route = projectId && artifactId ? '/projects/' + encodeURIComponent(projectId) + '/artifacts/' + encodeURIComponent(artifactId) + (versionId ? '/versions/' + encodeURIComponent(versionId) : '') : '';
  return {
    id: firstText(executionCell.id) || [versionId || artifactId || 'artifact', 'producing-work-step'].join(':'),
    kind: 'artifact',
    title: firstText(workStep.title, 'Produced artifact'),
    status: firstText(workStep.status, 'completed'),
    summary: firstText(workStep.summary, 'Artifact created.'),
    run_id: firstText(origin.run_id, origin.runId),
    project_id: projectId,
    frame_id: firstText(origin.frame_id, origin.frameId),
    event_ids: Array.isArray(executionCell.event_ids) ? executionCell.event_ids : [],
    artifact: {
      id: artifactId,
      project_id: projectId,
      title: firstText(artifactInfo.title, item.title),
      kind: firstText(artifactInfo.kind, item.kind),
      latest_version_id: firstText(identity.latestVersionId, versionId),
      workspace_route: firstText(route)
    }
  };
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function firstText(...values) {
  for (const value of values) {
    const text = String(value || '').trim();
    if (text) return text;
  }
  return '';
}
