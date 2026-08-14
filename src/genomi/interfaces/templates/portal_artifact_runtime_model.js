import { compactLine, formatShort, titleCase } from './portal_format.js';
import { artifactOriginContextModel } from './portal_artifact_messages.js';
import {
  artifactDisplayModel,
  artifactOriginRunContext,
  artifactProvenanceModel,
  versionHistorySummary
} from './portal_artifact_display_model.js';
import { artifactProjection } from './portal_artifact_projection.js';
import { artifactStateModel } from './portal_artifact_state_adapters.js';
import { promptSafeText, selectedEvidencePayload } from './portal_selected_evidence.js';

export function artifactRuntimeModel(artifact) {
  if (!artifact || typeof artifact !== 'object') return null;
  const projection = artifactProjection(artifact);
  const display = projection.display;
  const summary = projection.summary;
  const envelope = object(summary.evidence_envelope);
  const sourceCatalog = object(summary.source_catalog);
  const sourceSummary = object(sourceCatalog.summary);
  const defaults = summary.defaults_applied;
  const defaultCount = collectionCount(defaults);
  const sourceCount = sourceCoverageCount(sourceCatalog, sourceSummary, envelope);
  const runtime = firstObject(summary.runtime_context, summary.runtime, summary.execution_context);
  const originContext = artifactOriginContextModel(artifact);
  const originRuns = artifactOriginRunContext(artifact).runIds;
  const effectiveVersion = object(display.effectiveVersion);
  const sections = [
    runtimeSection('Origin boundary', [
      safeBriefNode('Frame', originContext && originContext.frameId),
      safeBriefNode('Origin messages', originContext && originContext.messageIdsCount),
      safeBriefNode('Origin runs', originRuns.length ? originRuns.join(', ') : ''),
      safeBriefNode('Conversation summary', originContext && originContext.summary)
    ]),
    defaultsAppliedSection(defaults),
    runtimeSection('Source coverage', sourceCoverageNodes(sourceCatalog, sourceSummary, sourceCount)),
    runtimeSection('Interpretation boundary', [
      safeBriefNode('Finding state', evidenceStateLabel(envelope.finding_state)),
      safeBriefNode('Answer readiness', evidenceStateLabel(envelope.answer_readiness)),
      safeBriefNode('Scope', firstNonEmptyObjectValue(envelope.scope, summary.scope)),
      safeBriefNode('Negative inference', negativeInferenceSummary(envelope.negative_inference, summary.negative_inference))
    ]),
    runtimeSection('Artifact version', [
      safeBriefNode('Latest version', display.latestVersionId),
      safeBriefNode('Requested version', display.unresolvedSelectedVersionId),
      safeBriefNode('Selected version', display.selectedVersionId),
      safeBriefNode('Effective version', display.effectiveVersionId),
      safeBriefNode('Version history', versionHistorySummary(display))
    ]),
    runtimeObjectSection('Declared runtime', runtime)
  ].filter(Boolean);
  const metrics = [
    metric('Origin runs', originRuns.length),
    metric('Defaults', defaultCount),
    metric('Sources', sourceCount)
  ].filter(Boolean);
  return metrics.length || sections.length ? {
    title: 'Source details',
    metrics,
    sections
  } : null;
}

export function artifactReviewBriefModel(artifact) {
  const projection = artifactProjection(artifact || {});
  const display = projection.display;
  const provenance = artifactProvenanceModel(artifact);
  const runtime = artifactRuntimeModel(artifact);
  const state = projection.hasRequestedSelectedVersion ? null : artifactStateModel(artifact);
  const reviewState = artifactReviewStateModel(artifact);
  const nodes = [
    briefNode('Artifact', display.title),
    briefNode('Artifact status', display.status),
    briefNode('Review instruction', 'Use the artifact provenance, source details, and review state to identify what is supported, missing, blocked, and worth following up.')
  ];
  if (provenance) {
    const important = new Set(['Artifact', 'Result', 'Status', 'Summary', 'Latest version', 'Selected version', 'Version history']);
    const provenancePrefix = provenance.title || 'Artifact details';
    provenance.nodes
      .filter((node) => important.has(node.label))
      .forEach((node) => nodes.push(briefNode(provenancePrefix + ' / ' + (node.label === 'Result' ? 'Artifact' : node.label), node.value)));
  }
  if (runtime) {
    runtime.metrics.forEach((item) => nodes.push(briefNode('Source detail / ' + item.label, item.value)));
    runtime.sections.forEach((section) => {
      nodes.push(briefNode('Source detail section / ' + section.title, summarizeSectionNodes(section.nodes)));
    });
  }
  if (state) {
    state.metrics.forEach((item) => nodes.push(briefNode('State metric / ' + item.label, item.value)));
    state.sections.forEach((section) => {
      nodes.push(briefNode('State section / ' + section.title, summarizeSectionNodes(section.nodes)));
    });
  }
  if (reviewState) {
    reviewState.metrics.forEach((item) => nodes.push(briefNode('Version review metric / ' + item.label, item.value)));
    reviewState.sections.forEach((section) => {
      nodes.push(briefNode('Version review section / ' + section.title, summarizeSectionNodes(section.nodes)));
    });
  }
  return {
    title: 'Artifact review summary: ' + display.title,
    summary: display.meta || 'Artifact ready',
    sourceOperation: display.operation,
    reviewState,
    nodes: nodes.filter(Boolean)
  };
}

export function artifactReviewStateModel(artifact) {
  const projection = artifactProjection(artifact || {});
  if (projection.hasUnresolvedSelectedVersion) return null;
  const review = projection.review;
  if (!review.status) return null;
  const counts = object(review.counts);
  const checks = Array.isArray(review.checks)
    ? review.checks.filter((check) => check && typeof check === 'object' && !Array.isArray(check))
    : [];
  const reviewRuns = Array.isArray(review.review_runs)
    ? review.review_runs.filter((run) => run && typeof run === 'object' && !Array.isArray(run))
    : [];
  const limitations = Array.isArray(review.limitations) ? review.limitations.filter(Boolean) : [];
  const metrics = [
    metric('Status', review.status),
    metric('Checks', firstPositiveOrZero(review.check_count, checks.length)),
    metric('Check runs', reviewRuns.length),
    metric('Warnings', firstPositiveOrZero(counts.warning)),
    metric('Failures', firstPositiveOrZero(counts.failed)),
    metric('Generated', review.generated_at)
  ].filter(Boolean);
  const sections = [
    runtimeSection('Version checks', checks.map((check) => reviewCheckNode(check))),
    runtimeSection('Check run history', reviewRuns.map((run, index) => reviewRunNode(run, index))),
    runtimeSection('Review limits', limitations.map((item, index) => safeBriefNode('Limit ' + (index + 1), item)))
  ].filter(Boolean);
  return metrics.length || sections.length ? {
    title: 'Artifact version review',
    status: review.status,
    metrics,
    sections
  } : null;
}

export function artifactReviewHasRunningRun(artifact) {
  const projection = artifactProjection(artifact || {});
  const review = projection.review;
  const reviewRuns = Array.isArray(review.review_runs)
    ? review.review_runs.filter((run) => run && typeof run === 'object' && !Array.isArray(run))
    : [];
  return reviewRuns.some((run) => firstText(run.status).toLowerCase() === 'running');
}

export function artifactReviewBriefPayload(artifact) {
  const model = artifactReviewBriefModel(artifact);
  return selectedEvidencePayload({
    contextKind: 'result',
    label: model.title,
    summary: model.summary,
    sourceOperation: model.sourceOperation || undefined,
    selectedNodes: model.nodes.map((node) => ({
      label: node.label,
      text: 'Artifact review / ' + node.label + ': ' + formatContextNodeValue(node.value),
      value: node.summary || formatShort(node.value)
    })),
    promptIntro: 'Review this Genomi artifact using the selected review summary: ' + artifactDisplayModel(artifact || {}).title
  });
}

function runtimeSection(title, nodes) {
  const cleanNodes = Array.isArray(nodes) ? nodes.filter(Boolean) : [];
  return cleanNodes.length ? { title, nodes: cleanNodes } : null;
}

function runtimeObjectSection(title, value) {
  const data = object(value);
  const nodes = Object.entries(data)
    .filter(([, child]) => child !== null && child !== undefined && child !== '' && child !== false)
    .map(([key, child]) => safeBriefNode(titleCase(key), child));
  return runtimeSection(title, nodes);
}

function defaultsAppliedSection(value) {
  if (Array.isArray(value)) {
    return runtimeSection('Defaults applied', value.map((item, index) => defaultAppliedNode(item, index)));
  }
  return runtimeObjectSection('Defaults applied', value);
}

function defaultAppliedNode(item, index) {
  if (item && typeof item === 'object' && !Array.isArray(item)) {
    const label = firstText(item.parameter, item.name, item.key, item.id, 'Default ' + (index + 1));
    const summary = firstText(item.value, item.source, item.condition, item.applies_when_omitted);
    return {
      label: promptSafeText(label),
      summary: promptSafeText(compactLine(summary || formatShort(item), 140)),
      value: safeValue(item)
    };
  }
  return safeBriefNode('Default ' + (index + 1), item);
}

function sourceCoverageNodes(sourceCatalog, sourceSummary, sourceCount) {
  const sources = Array.isArray(sourceCatalog.sources)
    ? sourceCatalog.sources.filter((source) => source && typeof source === 'object' && !Array.isArray(source))
    : [];
  const nodes = [
    safeBriefNode('Source count', sourceCount),
    safeBriefNode('Installed', sourceSummary.installed_count),
    safeBriefNode('Unavailable', sourceSummary.unavailable_count),
    safeBriefNode('Source status', firstText(sourceSummary.status, sourceCatalog.status))
  ];
  sources.slice(0, 8).forEach((source) => nodes.push(sourceCoverageNode(source)));
  if (sources.length > 8) nodes.push(safeBriefNode('More sources', sources.length - 8));
  return nodes.filter(Boolean);
}

function sourceCoverageCount(sourceCatalog, sourceSummary, envelope) {
  const sources = Array.isArray(sourceCatalog.sources) ? sourceCatalog.sources : [];
  const observations = object(envelope.observations);
  return firstPositiveNumber(
    sourceSummary.source_count,
    sourceCatalog.source_count,
    observations.source_catalog_count,
    sources.length
  );
}

function sourceCoverageNode(source) {
  const sourceId = firstText(source.source_id, source.id, source.name, source.title);
  const title = firstText(source.title, source.name);
  const status = firstText(source.status, source.state, source.availability);
  const label = [sourceId, title && title !== sourceId ? title : ''].filter(Boolean).join(' · ') || 'Source';
  const summary = firstText(status, source.best_for, source.description, source.relevance);
  return {
    label: promptSafeText(label),
    summary: promptSafeText(compactLine(summary || formatShort(source), 140)),
    value: safeValue(source)
  };
}

function negativeInferenceSummary(...values) {
  const data = firstObject(...values);
  if (Object.keys(data).length) {
    if (data.allowed === false) return 'Not allowed from consulted sources';
    if (data.allowed === true) return 'Allowed within consulted scope';
    return firstText(data.rule, data.guidance, data.status, data.state, data.message);
  }
  return firstText(...values);
}

function evidenceStateLabel(value) {
  const text = firstText(value);
  if (!text) return '';
  const normalized = text
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return normalized ? normalized.charAt(0).toUpperCase() + normalized.slice(1) : '';
}

function reviewCheckNode(check) {
  const label = firstText(check.title, check.check_id, 'Review check');
  const status = firstText(check.status);
  const statusLabel = reviewStatusLabel(status);
  const severity = firstText(check.severity);
  const summary = firstText(check.summary);
  const value = {
    check_id: check.check_id,
    status,
    severity,
    summary,
    observed: check.observed
  };
  return {
    label: promptSafeText(label),
    summary: promptSafeText(compactLine([statusLabel, severity, summary].filter(Boolean).join(' · '), 180)),
    value: safeReviewValue(value)
  };
}

function briefNode(label, value) {
  if (value === null || value === undefined || value === '' || value === false) return null;
  return { label, summary: formatShort(value), value };
}

function safeBriefNode(label, value) {
  if (value === null || value === undefined || value === '' || value === false) return null;
  const safe = safeValue(value);
  return { label: promptSafeText(label), summary: promptSafeText(formatShort(safe)), value: safe };
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
        .filter(([, child]) => child !== null && child !== undefined && child !== '' && child !== false)
        .map(([key, child]) => [promptSafeText(key), safeValue(child)])
    );
  }
  return promptSafeText(String(value));
}

function reviewRunNode(run, index) {
  const status = firstText(run.status, 'completed');
  const checkStatus = firstText(run.check_status, 'not run');
  const completedAt = firstText(run.completed_at);
  const startedAt = firstText(run.started_at);
  const time = completedAt || (startedAt ? 'started ' + startedAt : '');
  const countSummary = reviewRunCountSummary(run.counts, run.check_count);
  const summary = [reviewRunStatusLabel(status), reviewRunStatusLabel(checkStatus), time, countSummary].filter(Boolean).join(' · ');
  return {
    label: 'Check run ' + (index + 1),
    summary: promptSafeText(compactLine(summary || firstText(run.summary), 160)),
    value: safeReviewValue({
      status,
      check_status: checkStatus,
      started_at: startedAt,
      completed_at: completedAt,
      check_count: run.check_count,
      counts: run.counts,
      summary: run.summary
    })
  };
}

function reviewRunStatusLabel(value) {
  const clean = firstText(value).toLowerCase();
  if (!clean) return '';
  if (clean === 'running') return 'running';
  if (clean === 'completed') return 'completed';
  if (clean === 'not_run') return 'not run';
  if (/^(passed|pass|ok|success)$/.test(clean)) return 'no issues';
  return clean.replace(/_/g, ' ');
}

function reviewRunCountSummary(counts, checkCount) {
  const data = object(counts);
  const parts = [
    positiveCountLabel(data.failed, 'failed'),
    positiveCountLabel(data.warning, 'warning')
  ].filter(Boolean);
  if (parts.length) return parts.join(', ');
  const count = firstPositiveOrZero(checkCount, data.passed);
  return count !== '' ? String(count) + ' checks' : '';
}

function positiveCountLabel(value, label) {
  if (!Number.isFinite(Number(value)) || Number(value) <= 0) return '';
  return String(Number(value)) + ' ' + label;
}

function reviewStatusLabel(value) {
  const clean = firstText(value).toLowerCase();
  if (/^(passed|pass|ok|success)$/.test(clean)) return 'no issues';
  if (clean === 'completed') return 'completed';
  return clean.replace(/_/g, ' ');
}

function safeReviewValue(value) {
  if (value === null || value === undefined) return value;
  if (typeof value === 'string') return promptSafeText(value);
  if (typeof value === 'number' || typeof value === 'boolean') return value;
  if (Array.isArray(value)) {
    return value
      .map((child) => safeReviewValue(child))
      .filter((child) => child !== null && child !== undefined && child !== '');
  }
  if (typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([, child]) => child !== null && child !== undefined && child !== '')
        .map(([key, child]) => [promptSafeText(key), safeReviewValue(child)])
    );
  }
  return promptSafeText(String(value));
}

function summarizeSectionNodes(nodes) {
  if (!Array.isArray(nodes) || !nodes.length) return '';
  return nodes
    .map((node) => node.label + ': ' + (node.summary || formatShort(node.value)))
    .join('; ');
}

function firstObject(...values) {
  return values.find((value) => value && typeof value === 'object' && !Array.isArray(value)) || {};
}

function collectionCount(value) {
  if (Array.isArray(value)) return value.length;
  if (value && typeof value === 'object') return Object.keys(value).length;
  return 0;
}

function firstPositiveNumber(...values) {
  for (const value of values) {
    const number = Number(value);
    if (Number.isFinite(number) && number > 0) return number;
  }
  return '';
}

function firstPositiveOrZero(...values) {
  for (const value of values) {
    const number = Number(value);
    if (Number.isFinite(number) && number >= 0) return number;
  }
  return '';
}

function firstNonEmptyObjectValue(...values) {
  return values.find((value) => {
    if (Array.isArray(value)) return value.length;
    if (value && typeof value === 'object') return Object.keys(value).length;
    return value !== null && value !== undefined && value !== '' && value !== false;
  });
}

function metric(label, value) {
  if (value === null || value === undefined || value === '' || value === false) return null;
  return { label, value };
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function firstText(...values) {
  for (const value of values) {
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return '';
}

function formatContextNodeValue(value) {
  return typeof value === 'string' ? value : formatShort(value);
}
