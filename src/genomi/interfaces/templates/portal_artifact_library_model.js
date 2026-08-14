import { artifactDisplayModel, artifactOriginRunContext, artifactPreviewModel } from './portal_artifact_display_model.js';

const LAYOUTS = ['cards', 'compact'];
const CATEGORY_DEFINITIONS = [
  {
    key: 'evidence',
    label: 'Evidence',
    matches: (item) => item.category === 'evidence' && !item.hidden
  },
  {
    key: 'report',
    label: 'Reports',
    matches: (item) => item.category === 'report' && !item.hidden
  },
  {
    key: 'file',
    label: 'Files',
    matches: (item) => item.category === 'file' && !item.hidden
  },
  {
    key: 'other',
    label: 'Other',
    matches: (item) => item.category === 'other' && !item.hidden
  }
];
const FILTER_DEFINITIONS = [
  { key: 'all', label: 'All', matches: (item) => !item.hidden },
  { key: 'starred', label: 'Starred', matches: (item) => item.starred && !item.hidden },
  { key: 'previewable', label: 'Previewable', matches: (item) => item.previewable && !item.hidden },
  { key: 'hidden', label: 'Hidden', matches: (item) => item.hidden },
  ...CATEGORY_DEFINITIONS
];
const GROUP_DEFINITIONS = [
  {
    key: 'uploads',
    label: 'Your uploads',
    matches: (item) => item.category === 'file' && item.operation === 'portal.import_file' && !item.hidden
  },
  {
    key: 'produced_files',
    label: 'Produced files',
    matches: (item) => item.category === 'file' && item.operation !== 'portal.import_file' && !item.hidden
  },
  {
    key: 'hidden',
    label: 'Hidden items',
    matches: (item) => item.hidden
  }
];

export function artifactLibraryModel(artifacts, options = {}) {
  const baseUrl = options.baseUrl || 'http://localhost';
  const items = artifactItems(artifacts, baseUrl);
  const query = cleanQuery(options.query);
  const filter = filterDefinition(options.filter).key;
  const layout = LAYOUTS.includes(options.layout) ? options.layout : 'cards';
  const filtered = items.filter((item) => matchesFilter(item, filter) && matchesQuery(item, query));
  return {
    query,
    filter,
    layout,
    totalCount: items.length,
    shownCount: filtered.length,
    summary: filtered.length === items.length
      ? String(items.length) + ' library item' + (items.length === 1 ? '' : 's')
      : String(filtered.length) + ' of ' + String(items.length) + ' items',
    filters: artifactFilterItems(items),
    layouts: artifactLayoutItems(layout),
    groups: artifactGroups(filtered),
    items: filtered,
    artifacts: filtered.map((item) => item.artifact)
  };
}

export function artifactRecordsOutsideWorkspaceFiles(artifacts, workspacePayload) {
  const files = Array.isArray(workspacePayload && workspacePayload.files) ? workspacePayload.files : [];
  const linkedArtifactIds = new Set(files
    .map((file) => firstText(file && file.artifact_id, file && file.artifactId))
    .filter(Boolean));
  const workspacePaths = new Set(files
    .map((file) => firstText(file && file.relative_path, file && file.relativePath, file && file.path))
    .filter(Boolean));
  return Array.isArray(artifacts)
    ? artifacts.filter((artifact) => {
      if (!artifact) return false;
      if (linkedArtifactIds.has(firstText(artifact.id, artifact.artifact_id))) return false;
      const kind = firstText(artifact.kind, artifact.renderer);
      const filePaths = [
        firstText(artifact.title),
        ...(Array.isArray(artifact.summary_lines) ? artifact.summary_lines.map((line) => firstText(line)) : [])
      ];
      return kind !== 'project_file' || !filePaths.some((path) => workspacePaths.has(path));
    })
    : [];
}

function artifactItems(artifacts, baseUrl) {
  return Array.isArray(artifacts)
    ? artifacts.filter((artifact) => artifact && typeof artifact === 'object' && !Array.isArray(artifact)).map((artifact) => {
      const display = artifactDisplayModel(artifact);
      const preview = artifactPreviewModel(artifact, baseUrl);
      const origin = artifactOriginRunContext(artifact);
      return {
        artifact,
        display,
        preview,
        starred: display.starred,
        hidden: display.hidden,
        previewable: preview.previewable,
        category: display.category,
        operation: display.operation,
        originFrameId: origin.frameId,
        originRunKey: origin.runIds[0] || '',
        searchText: [
          display.id,
          display.title,
          display.kind,
          display.renderer,
          display.operation,
          display.status,
          display.starred ? 'starred' : '',
          display.hidden ? 'hidden' : '',
          display.meta,
          display.latestVersionId,
          display.selectedVersionId,
          display.effectiveVersionId
        ].filter(Boolean).join(' ').toLowerCase()
      };
    })
      .sort((left, right) => Number(right.starred) - Number(left.starred))
    : [];
}

function artifactFilterItems(items) {
  return FILTER_DEFINITIONS.map((definition) => ({
    key: definition.key,
    label: definition.label,
    count: items.filter((item) => definition.matches(item)).length
  }));
}

function artifactLayoutItems(activeLayout) {
  return [
    { key: 'cards', label: 'Cards', active: activeLayout === 'cards' },
    { key: 'compact', label: 'Compact', active: activeLayout === 'compact' }
  ];
}

function artifactGroups(items) {
  const groups = GROUP_DEFINITIONS.map((definition) => artifactGroupFromItems(
    definition.key,
    definition.label,
    items.filter((item) => definition.matches(item))
  )).filter(Boolean);
  return [
    ...groups.filter((group) => group.key !== 'hidden'),
    ...generatedArtifactGroups(items),
    ...groups.filter((group) => group.key === 'hidden')
  ];
}

function generatedArtifactGroups(items) {
  const generated = items.filter((item) => item.category !== 'file' && !item.hidden);
  const byRun = new Map();
  const withoutRun = [];
  generated.forEach((item) => {
    if (!item.originRunKey) {
      withoutRun.push(item);
      return;
    }
    const current = byRun.get(item.originRunKey) || [];
    current.push(item);
    byRun.set(item.originRunKey, current);
  });
  const groups = Array.from(byRun.values()).map((groupItems, index, allGroups) => artifactGroupFromItems(
    'generated_turn_' + String(index + 1),
    allGroups.length === 1 ? 'Created in assistant turn' : 'Created in assistant turn ' + String(index + 1),
    groupItems,
    'generated_turn'
  )).filter(Boolean);
  const fallback = artifactGroupFromItems('generated', 'Generated artifacts', withoutRun, 'generated');
  if (fallback) groups.push(fallback);
  return groups;
}

function artifactGroupFromItems(key, label, groupItems, summaryKey = key) {
  if (!groupItems.length) return null;
  return {
    key,
    label,
    count: groupItems.length,
    summary: artifactGroupSummary(summaryKey, groupItems.length),
    items: groupItems,
    artifacts: groupItems.map((item) => item.artifact)
  };
}

function artifactGroupSummary(key, count) {
  if (key === 'uploads') return String(count) + ' uploaded file' + (count === 1 ? '' : 's');
  if (key === 'produced_files') return String(count) + ' produced file' + (count === 1 ? '' : 's');
  if (key === 'generated_turn') return String(count) + ' artifact' + (count === 1 ? '' : 's') + ' from this assistant turn';
  if (key === 'hidden') return String(count) + ' hidden item' + (count === 1 ? '' : 's');
  return String(count) + ' generated artifact' + (count === 1 ? '' : 's');
}

function matchesFilter(item, filter) {
  return filterDefinition(filter).matches(item);
}

function filterDefinition(filter) {
  return FILTER_DEFINITIONS.find((definition) => definition.key === filter) || FILTER_DEFINITIONS[0];
}

function matchesQuery(item, query) {
  if (!query) return true;
  return query.split(/\s+/).every((term) => item.searchText.includes(term));
}

function cleanQuery(value) {
  return String(value || '').trim().toLowerCase();
}

function firstText(...values) {
  for (const value of values) {
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return '';
}
