import { artifactMessagesModel } from './portal_artifact_messages.js';
import { artifactEnvironmentModel } from './portal_artifact_environment_model.js';
import { artifactWorkTraceModel } from './portal_artifact_origin_trace.js';
import {
  artifactDisplayModel,
  artifactOperationTraceModel,
  artifactPreviewModel,
  artifactProvenanceModel
} from './portal_artifact_display_model.js';
import { artifactRuntimeModel, artifactReviewBriefModel, artifactReviewStateModel } from './portal_artifact_runtime_model.js';
import { artifactReproductionModel } from './portal_artifact_reproduction_model.js';
import { artifactStateModel } from './portal_artifact_state_adapters.js';

export function artifactProvenanceViewModel(artifact, baseUrl = 'http://localhost', options = {}) {
  const preview = artifactPreviewModel(artifact || {}, baseUrl);
  const evidence = artifactProvenanceModel(artifact);
  const reproduction = artifactReproductionModel(artifact);
  const operationTrace = artifactOperationTraceModel(artifact);
  const workTrace = artifactWorkTraceModel(artifact, {
    executionCells: options.executionCells
  });
  const messages = artifactMessagesModel(artifact);
  const environment = artifactEnvironmentModel(artifact);
  const runtime = artifactRuntimeModel(artifact);
  const state = artifactStateModel(artifact);
  const review = artifactReviewBriefModel(artifact);
  const reviewState = artifactReviewStateModel(artifact);
  const primaryDetails = artifactPrimaryDetailsModel(evidence, state);
  const technical = artifactTechnicalDetailsModel({
    reproduction,
    operationTrace,
    environment,
    runtime,
    state
  });
  const primaryTabs = [
    artifactTabDescriptor({
      id: 'preview',
      label: 'Preview',
      badge: '',
      testId: 'genomi-provenance-tab-preview',
      kind: 'preview',
      model: preview
    }),
    primaryDetails && artifactTabDescriptor({
      id: 'evidence',
      label: primaryDetails.tabLabel,
      badge: '',
      testId: 'genomi-provenance-tab-evidence',
      kind: 'panel',
      model: artifactPanelModel(primaryDetails.model, {
        className: primaryDetails.className,
        testId: 'genomi-artifact-provenance',
        metricLimit: 3,
        sectionTitle: primaryDetails.sectionTitle
      })
    }),
    messages && artifactTabDescriptor({
      id: 'messages',
      label: 'Origin chat',
      badge: '',
      testId: 'genomi-provenance-tab-messages',
      kind: 'panel',
      model: artifactPanelModel(messages, {
        className: 'artifact-messages',
        testId: 'genomi-artifact-messages'
      })
    }),
    workTrace && artifactTabDescriptor({
      id: 'trace',
      label: 'Work trail',
      badge: '',
      testId: 'genomi-provenance-tab-trace',
      kind: 'work-trace',
      model: workTrace
    }),
    reviewState && shouldShowReviewTab(reviewState) && artifactTabDescriptor({
      id: 'review',
      label: 'Review',
      badge: reviewAttentionBadge(reviewState),
      testId: 'genomi-provenance-tab-review',
      kind: 'panel',
      model: artifactPanelModel({
        title: 'Review',
        metrics: [
          metric('Checks', metricValue(reviewState.metrics, 'Checks')),
          positiveMetric('Warnings', metricValue(reviewState.metrics, 'Warnings')),
          positiveMetric('Failures', metricValue(reviewState.metrics, 'Failures')),
          positiveMetric('Check runs', metricValue(reviewState.metrics, 'Check runs'))
        ].filter(Boolean),
        sections: reviewState.sections
      }, {
        className: 'artifact-review',
        testId: 'genomi-artifact-review'
      })
    }),
    reproduction && artifactTabDescriptor({
      id: 'rebuild',
      label: 'Rebuild recipe',
      badge: '',
      testId: 'genomi-provenance-tab-rebuild',
      kind: 'panel',
      model: artifactPanelModel(reproduction, {
        className: 'artifact-rebuild',
        testId: 'genomi-artifact-rebuild'
      })
    }),
    environment && shouldShowSourceLimitsTab(environment, preview) && artifactTabDescriptor({
      id: 'environment',
      label: 'Source limits',
      badge: '',
      testId: 'genomi-provenance-tab-environment',
      kind: 'panel',
      model: artifactPanelModel(environment, {
        className: 'artifact-environment',
        testId: 'genomi-artifact-environment'
      })
    })
  ].filter(Boolean);
  const secondaryTabs = [
    technical && artifactTabDescriptor({
      id: 'technical',
      label: 'Technical details',
      badge: technical.badge,
      testId: 'genomi-provenance-tab-technical',
      kind: 'panel',
      model: artifactPanelModel(technical, {
        className: 'artifact-technical-details',
        testId: 'genomi-artifact-technical-details',
        selectable: false
      })
    })
  ].filter(Boolean);
  const allTabs = [...primaryTabs, ...secondaryTabs];
  return {
    artifact: artifactDisplayModel(artifact || {}),
    preview,
    evidence,
    reproduction,
    operationTrace,
    workTrace,
    messages,
    environment,
    runtime,
    state,
    reviewState,
    review,
    technical,
    defaultTab: preview.previewable ? 'preview' : (primaryTabs[1] ? primaryTabs[1].id : 'preview'),
    tabs: primaryTabs,
    secondaryTabs,
    allTabs
  };
}

export function artifactProvenanceTabsModel(artifact, baseUrl = 'http://localhost') {
  const view = artifactProvenanceViewModel(artifact, baseUrl);
  return {
    defaultTab: view.defaultTab,
    tabs: view.tabs.map((tab) => ({
      id: tab.id,
      label: tab.label,
      badge: tab.badge,
      testId: tab.testId
    })),
    secondaryTabs: view.secondaryTabs.map((tab) => ({
      id: tab.id,
      label: tab.label,
      badge: tab.badge,
      testId: tab.testId
    })),
    allTabs: view.allTabs.map((tab) => ({
      id: tab.id,
      label: tab.label,
      badge: tab.badge,
      testId: tab.testId
    }))
  };
}

function artifactTabDescriptor({ id, label, badge, testId, kind, model }) {
  return { id, label, badge, testId, kind, model };
}

function artifactPrimaryDetailsModel(evidence, state) {
  if (state && state.title === 'Evidence report state') {
    return {
      tabLabel: 'Evidence report',
      tabBadge: primaryMetricValue(state, 'Sources') || primaryMetricValue(state, 'Evidence support') || String(state.sections.length),
      className: 'artifact-evidence-state',
      sectionTitle: state.title,
      model: state
    };
  }
  if (!evidence) return null;
  return {
    tabLabel: evidence.title || 'Artifact details',
    tabBadge: String(evidence.nodes.length),
    className: 'artifact-provenance',
    sectionTitle: evidence.title || 'Artifact details',
    model: evidence
  };
}

function artifactPanelModel(model, options = {}) {
  const metrics = Array.isArray(model.metrics)
    ? model.metrics
    : (model.nodes || []).slice(0, options.metricLimit || 3).map((item) => ({ label: item.label, value: item.summary }));
  const sections = Array.isArray(model.sections)
    ? model.sections
    : [{ title: options.sectionTitle || model.title, nodes: model.nodes || [] }];
  return {
    title: model.title,
    className: options.className || '',
    testId: options.testId || '',
    selectable: options.selectable !== false,
    metrics,
    sections,
    codeBlocks: Array.isArray(model.codeBlocks) ? model.codeBlocks : []
  };
}

function primaryMetricValue(model, label) {
  const metrics = Array.isArray(model && model.metrics) ? model.metrics : [];
  const item = metrics.find((metric) => metric && metric.label === label);
  if (!item) return '';
  const value = item.value;
  return value === null || value === undefined || value === '' || value === false ? '' : String(value);
}

function artifactTechnicalDetailsModel(models) {
  const groups = [
    technicalGroup('Rebuild details', models.reproduction && models.reproduction.technical),
    technicalGroup('Tool calls', models.operationTrace, { sectionTitle: 'Operation trace' }),
    technicalGroup('Environment details', models.environment && models.environment.technical),
    technicalGroup('Source details', models.runtime),
    technicalGroup('Technical state', models.state)
  ].filter(Boolean);
  if (!groups.length) return null;
  const sections = groups.flatMap((group) => group.sections.map((section) => ({
    title: group.title + ' / ' + section.title,
    nodes: section.nodes
  })));
  const codeBlocks = groups.flatMap((group) => group.codeBlocks.map((block) => ({
    ...block,
    label: group.title + ' / ' + (block.label || 'Code')
  })));
  const metrics = [
    metric('Areas', groups.length),
    ...groups.map((group) => metric(group.title, group.badge))
  ].filter(Boolean);
  return {
    title: 'Technical details',
    badge: String(groups.length),
    metrics,
    sections,
    codeBlocks
  };
}

function technicalGroup(title, model, options = {}) {
  if (!model) return null;
  const panel = artifactPanelModel(model, {
    sectionTitle: options.sectionTitle || title,
    metricLimit: options.metricLimit || 4
  });
  if (!panel.sections.length && !panel.metrics.length && !panel.codeBlocks.length) return null;
  return {
    title,
    badge: technicalGroupBadge(model, panel),
    sections: panel.sections,
    codeBlocks: panel.codeBlocks
  };
}

function technicalGroupBadge(model, panel) {
  if (model.status) return model.status;
  if (Array.isArray(model.nodes)) return String(model.nodes.length);
  if (Array.isArray(model.sections)) return String(model.sections.length);
  if (Array.isArray(panel.sections)) return String(panel.sections.length);
  return 'ready';
}

function reviewAttentionBadge(reviewState) {
  const failures = Number(metricValue(reviewState && reviewState.metrics, 'Failures') || 0);
  const warnings = Number(metricValue(reviewState && reviewState.metrics, 'Warnings') || 0);
  if (Number.isFinite(failures) && failures > 0) return failures + ' issue' + (failures === 1 ? '' : 's');
  if (Number.isFinite(warnings) && warnings > 0) return warnings + ' warning' + (warnings === 1 ? '' : 's');
  return '';
}

function shouldShowReviewTab(reviewState) {
  const status = String(reviewState && reviewState.status || '').toLowerCase();
  const checksRun = Number(metricValue(reviewState && reviewState.metrics, 'Check runs') || 0);
  const warnings = Number(metricValue(reviewState && reviewState.metrics, 'Warnings') || 0);
  const failures = Number(metricValue(reviewState && reviewState.metrics, 'Failures') || 0);
  return !['passed', 'not_run'].includes(status)
    || (Number.isFinite(checksRun) && checksRun > 0)
    || (Number.isFinite(warnings) && warnings > 0)
    || (Number.isFinite(failures) && failures > 0);
}

function shouldShowSourceLimitsTab(environment, preview) {
  if (preview && preview.family === 'file') return false;
  if (!preview) return true;
  const userFacingSections = new Set([
    'Source coverage',
    'Interpretation boundary',
    'Defaults applied',
    'Source snapshot limits'
  ]);
  return Array.isArray(environment.sections)
    && environment.sections.some((section) => section && userFacingSections.has(section.title));
}

function metric(label, value) {
  if (value === null || value === undefined || value === '' || value === false) return null;
  return { label, value };
}

function positiveMetric(label, value) {
  const count = Number(value || 0);
  return Number.isFinite(count) && count > 0 ? metric(label, count) : null;
}

function metricValue(metrics, label) {
  const item = Array.isArray(metrics) ? metrics.find((metric) => metric.label === label) : null;
  return item ? item.value : '';
}
