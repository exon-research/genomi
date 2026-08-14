import { selectedEvidencePayload } from './portal_selected_evidence.js';

export function workspaceFileContextPayload(value) {
  const model = value && typeof value === 'object' && !Array.isArray(value) ? value : null;
  if (!model || !model.path) return null;
  return selectedEvidencePayload({
    contextKind: 'workspace_file',
    label: 'Project file: ' + model.path,
    summary: workspaceFileContextSummary(model),
    sourceOperation: 'genomi.portal.workspace_file',
    selectedNodes: workspaceFileContextNodes(model),
    promptIntro: 'Selected project file: ' + model.path
  });
}

function workspaceFileContextSummary(model) {
  return [
    model.kindLabel || workspaceFileKindLabel(model.fileKind),
    model.contentType,
    model.sizeLabel,
    model.truncated ? 'preview truncated' : '',
    model.previewKind === 'document' ? 'document preview available' : '',
    model.previewKind === 'image' ? 'image preview available' : '',
    model.previewKind === 'notebook' && model.notebook ? model.notebook.summary : ''
  ].filter(Boolean).join(' · ') || 'Project file';
}

function workspaceFileContextNodes(model) {
  const nodes = [
    contextNode('File', model.path),
    contextNode('Kind', model.kindLabel || workspaceFileKindLabel(model.fileKind)),
    contextNode('Content type', model.contentType),
    contextNode('Size', model.sizeLabel),
    contextNode('Preview state', model.status === 'available' ? previewStateLabel(model) : model.reason || model.status)
  ];
  const excerpt = workspaceFileContextExcerpt(model);
  if (excerpt) nodes.push(contextNode('Visible preview excerpt', excerpt));
  if (model.notebook) nodes.push(contextNode('Notebook outline', notebookContextSummary(model.notebook)));
  return nodes.filter(Boolean);
}

function contextNode(label, value) {
  const text = firstText(value);
  if (!text) return null;
  return {
    label,
    text: 'Project file / ' + label + ': ' + text,
    value: text
  };
}

function previewStateLabel(model) {
  if (model.previewKind === 'document') return 'PDF document preview available';
  if (model.previewKind === 'image') return 'Image preview available';
  if (model.previewKind === 'notebook') return 'Notebook cell outline available';
  if (model.previewKind === 'text') return model.truncated ? 'Bounded text preview shown' : 'Text preview shown';
  return model.previewKind || 'Preview available';
}

function workspaceFileContextExcerpt(model) {
  if (model.previewKind === 'text') return clampContextText(model.text, 1400);
  if (model.previewKind === 'document') {
    return 'PDF preview is open in the workspace. Use this file identity and ask for missing details if the visible PDF content is not enough.';
  }
  if (model.previewKind === 'image') {
    return 'Image preview is open in the workspace. Use this figure identity and ask for missing details if visual inspection is needed.';
  }
  if (model.previewKind === 'notebook' && model.notebook) {
    const cells = Array.isArray(model.notebook.cells) ? model.notebook.cells : [];
    return clampContextText(cells.map((cell) => notebookCellLabelForContext(cell) + ': ' + (cell.source || '')).join('\n\n'), 1400);
  }
  return '';
}

function notebookContextSummary(notebook) {
  return [
    notebook.summary,
    notebook.truncated ? 'showing ' + String(notebook.shownCellCount || 0) + ' of ' + String(notebook.cellCount || 0) + ' cells' : '',
    notebook.language ? 'language: ' + notebook.language : ''
  ].filter(Boolean).join(' · ');
}

function notebookCellLabelForContext(cell) {
  return (cell.type || 'Cell') + ' cell ' + String(cell.index || 0);
}

function clampContextText(value, limit) {
  const text = firstText(value).replace(/\s+\n/g, '\n').replace(/\n{4,}/g, '\n\n\n');
  if (!text) return '';
  const max = Number(limit || 0) || 1400;
  return text.length > max ? text.slice(0, max - 1).trimEnd() + '...' : text;
}

function workspaceFileKindLabel(kind) {
  switch (kind) {
    case 'pdf':
      return 'PDF document';
    case 'notebook':
      return 'Notebook';
    case 'markdown':
      return 'Markdown';
    case 'image':
      return 'Image';
    case 'code':
      return 'Code';
    case 'table':
      return 'Table';
    case 'data':
      return 'Data';
    case 'text':
      return 'Text';
    default:
      return 'File';
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
