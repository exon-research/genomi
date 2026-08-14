import { artifactDisplayModel } from './portal_artifact_display_model.js';

export function artifactProjection(artifact) {
  const rawArtifact = object(artifact);
  const display = artifactDisplayModel(rawArtifact);
  const hasRequestedSelectedVersion = Boolean(display.requestedSelectedVersionId);
  const hasResolvedSelectedVersion = Boolean(display.resolvedSelectedVersionId);
  const hasUnresolvedSelectedVersion = Boolean(hasRequestedSelectedVersion && !hasResolvedSelectedVersion);
  const sources = projectedSources(rawArtifact, display, hasRequestedSelectedVersion, hasUnresolvedSelectedVersion);
  return {
    display,
    hasRequestedSelectedVersion,
    hasResolvedSelectedVersion,
    hasUnresolvedSelectedVersion,
    summary: sources.summary,
    environment: sources.environment,
    review: sources.review,
    reproduction: sources.reproduction
  };
}

function projectedSources(rawArtifact, display, hasRequestedSelectedVersion, hasUnresolvedSelectedVersion) {
  const source = sourceModel(rawArtifact, display, hasRequestedSelectedVersion, hasUnresolvedSelectedVersion);
  return {
    summary: sourceField(source, 'summary'),
    environment: sourceField(source, 'environment'),
    review: sourceField(source, 'review'),
    reproduction: sourceField(source, 'reproduction')
  };
}

function sourceModel(rawArtifact, display, hasRequestedSelectedVersion, hasUnresolvedSelectedVersion) {
  if (hasUnresolvedSelectedVersion) {
    return { version: {}, artifact: {}, latestVersion: {}, allowArtifactFallback: false };
  }
  const effectiveVersion = object(display && display.effectiveVersion);
  const latestVersion = object(display && display.latestVersion);
  return {
    version: effectiveVersion,
    artifact: hasRequestedSelectedVersion ? {} : rawArtifact,
    latestVersion: hasRequestedSelectedVersion ? {} : latestVersion,
    allowArtifactFallback: !hasRequestedSelectedVersion
  };
}

function sourceField(source, field) {
  if (!field) return {};
  return firstObject(
    source.version[field],
    source.allowArtifactFallback ? source.artifact[field] : null,
    source.allowArtifactFallback ? source.latestVersion[field] : null
  );
}

function firstObject(...values) {
  return values.find((value) => value && typeof value === 'object' && !Array.isArray(value)) || {};
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}
