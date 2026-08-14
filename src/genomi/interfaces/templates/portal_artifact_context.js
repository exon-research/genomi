import { formatShort } from './portal_format.js';
import { artifactSelectedNodes } from './portal_artifact_selection.js';
import { selectedEvidencePayload } from './portal_selected_evidence.js';
import { artifactDisplayModel, artifactProvenanceModel, artifactSurfaceCopy } from './portal_artifact_display_model.js';

export function artifactContextPayload(artifact) {
  const model = artifactDisplayModel(artifact || {});
  const copy = artifactSurfaceCopy(model);
  const title = contextTitle(copy, model.title);
  const label = contextLabel(copy, model.title);
  const provenance = artifactProvenanceModel(artifact);
  const nodes = provenance ? provenance.nodes.map((node) => provenanceContextNode(node, copy)) : [{ label: model.title, text: model.title, value: model.title }];
  return selectedEvidencePayload({
    contextKind: copy.contextKind,
    label,
    summary: model.meta,
    sourceOperation: model.operation || undefined,
    selectedNodes: nodes,
    promptIntro: copy.promptIntroPrefix + ': ' + title
  });
}

export function artifactContextForSelection(artifact, root, selectedNodes = artifactSelectedNodes(root)) {
  if (!selectedNodes.length) return artifactContextPayload(artifact);
  const model = artifactDisplayModel(artifact || {});
  const copy = artifactSurfaceCopy(model);
  const title = contextTitle(copy, model.title);
  return selectedEvidencePayload({
    contextKind: copy.contextKind,
    label: contextLabel(copy, model.title),
    summary: model.meta,
    sourceOperation: model.operation || undefined,
    selectedNodes,
    promptIntro: copy.promptIntroPrefix + ': ' + title
  });
}

function contextLabel(copy, title) {
  const cleanTitle = String(title || '').trim();
  if (startsWithPrefix(cleanTitle, copy.labelPrefix)) return cleanTitle;
  return copy.labelPrefix + ': ' + cleanTitle;
}

function contextTitle(copy, title) {
  const cleanTitle = String(title || '').trim();
  const prefix = String(copy.labelPrefix || '').trim();
  if (!startsWithPrefix(cleanTitle, prefix)) return cleanTitle;
  return cleanTitle.slice(prefix.length).replace(/^\s*:\s*/, '').trim() || cleanTitle;
}

function startsWithPrefix(title, prefix) {
  return Boolean(title && prefix && title.toLowerCase().startsWith(prefix.toLowerCase()));
}

function provenanceContextNode(node, copy) {
  return {
    label: node.label,
    text: copy.nodeContextPrefix + ' / ' + node.label + ': ' + formatContextNodeValue(node.value),
    value: node.summary || formatShort(node.value)
  };
}

function formatContextNodeValue(value) {
  return typeof value === 'string' ? value : formatShort(value);
}
