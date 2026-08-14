import { workspaceFileContextPayload as workspaceFileContextPayloadFromModel } from './portal_workspace_file_context.js';
import { workspaceFilePreviewContentElement } from './portal_workspace_file_previews.js';

export function createWorkspaceFileController({
  container,
  onOpenArtifact,
  onViewContext,
  onPreviewFile,
  onAskFile,
  onAskNewFile,
  onUseFile
} = {}) {
  const state = {
    payload: null,
    query: '',
    locationKey: 'all',
    preview: null,
    projectId: '',
    previewRequestSerial: 0
  };

  function render(payload, options = {}) {
    const nextPayload = payload || {};
    const nextProjectId = firstText(options.projectId, nextPayload.project_id, nextPayload.projectId);
    if (nextProjectId !== state.projectId) {
      state.projectId = nextProjectId;
      state.locationKey = 'all';
      resetPreview();
    }
    state.payload = nextPayload;
    if (Object.prototype.hasOwnProperty.call(options, 'query')) {
      state.query = cleanQuery(options.query);
    }
    if (Object.prototype.hasOwnProperty.call(options, 'locationKey')) {
      state.locationKey = cleanLocationKey(options.locationKey);
    }
    if (Object.prototype.hasOwnProperty.call(options, 'preview')) {
      state.previewRequestSerial += 1;
      state.preview = workspaceFilePreviewModel(options.preview);
    } else if (state.preview && !payloadIncludesPreviewPath(state.payload, state.preview.path)) {
      resetPreview();
    }
    renderCurrent();
  }

  function renderCurrent() {
    renderWorkspaceFiles(container, state.payload, {
      query: state.query,
      locationKey: state.locationKey,
      preview: state.preview,
      onQuery: updateQuery,
      onLocation: updateLocation,
      onOpenArtifact,
      onViewContext,
      onPreviewFile: previewFile,
      onAskFile,
      onAskNewFile,
      onUseFile,
      onClosePreview: closePreview
    });
  }

  function updateQuery(query) {
    state.query = query;
    renderCurrent();
  }

  function updateLocation(locationKey) {
    state.locationKey = cleanLocationKey(locationKey);
    renderCurrent();
  }

  async function previewFile(file) {
    if (typeof onPreviewFile !== 'function') return;
    const requestSerial = state.previewRequestSerial + 1;
    const requestProjectId = state.projectId;
    const requestPath = file && file.path;
    const previewReference = workspaceFilePreviewReference(file);
    state.previewRequestSerial = requestSerial;
    state.preview = workspaceFilePreviewModel({ ...previewReference, status: 'loading' });
    renderCurrent();
    try {
      const response = await onPreviewFile(file);
      const preview = workspaceFilePreviewModel({
        ...previewReference,
        ...response,
        record_label: previewReference.record_label || (response && response.record_label)
      });
      if (!isCurrentPreviewRequest(requestSerial, requestProjectId, requestPath)) return;
      state.preview = preview;
    } catch (error) {
      if (!isCurrentPreviewRequest(requestSerial, requestProjectId, requestPath)) return;
      const typedPreview = workspaceFilePreviewModel(error && error.payload);
      if (typedPreview) {
        state.preview = typedPreview;
      } else {
        state.preview = workspaceFilePreviewModel({
          status: 'error',
          ...previewReference,
          reason: error && error.message ? error.message : 'Preview failed.'
        });
      }
    }
    renderCurrent();
  }

  function resetPreview() {
    state.previewRequestSerial += 1;
    state.preview = null;
  }

  function isCurrentPreviewRequest(serial, projectId, path) {
    return Boolean(
      serial === state.previewRequestSerial &&
      projectId === state.projectId &&
      state.preview &&
      state.preview.path === path
    );
  }

  function closePreview() {
    resetPreview();
    renderCurrent();
  }

  function reset() {
    state.payload = null;
    state.query = '';
    state.locationKey = 'all';
    state.projectId = '';
    resetPreview();
    renderCurrent();
  }

  return { render, reset };
}

function payloadIncludesPreviewPath(payload, path) {
  if (!path) return false;
  const files = Array.isArray(payload && payload.files) ? payload.files : [];
  return files
    .filter((file) => file && typeof file === 'object' && !Array.isArray(file))
    .some((file) => workspaceFileItem(file).path === path);
}

export function workspaceFilesModel(payload, options = {}) {
  const query = cleanQuery(options.query);
  const locationKey = cleanLocationKey(options.locationKey);
  const workspace = workspaceDescriptor(payload && payload.workspace);
  const files = Array.isArray(payload && payload.files)
    ? payload.files
      .filter((file) => file && typeof file === 'object' && !Array.isArray(file))
      .map(workspaceFileItem)
      .filter((file) => file.path)
    : [];
  const locations = workspaceFileLocations(files, locationKey);
  const activeLocationKey = locations.some((location) => location.key === locationKey) ? locationKey : 'all';
  const visible = files
    .filter((file) => matchesLocation(file, activeLocationKey))
    .filter((file) => matchesQuery(file, query));
  const summary = payload && payload.summary && typeof payload.summary === 'object' ? payload.summary : {};
  return {
    query,
    locationKey: activeLocationKey,
    workspace,
    totalCount: files.length,
    shownCount: visible.length,
    linkedArtifacts: Number(summary.linked_artifacts || 0),
    summary: files.length
      ? String(visible.length) + ' of ' + String(files.length) + ' file' + (files.length === 1 ? '' : 's')
      : 'No project files',
    groups: workspaceFileGroups(visible),
    locations: locations.map((location) => ({ ...location, active: location.key === activeLocationKey })),
    files: visible
  };
}

export function workspaceFilePreviewModel(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const status = firstText(value.status) || 'available';
  const kind = firstText(value.preview_kind, value.previewKind) || (status === 'loading' ? 'loading' : 'none');
  const path = firstText(value.relative_path, value.relativePath, value.path);
  const name = firstText(value.name) || path.split('/').pop() || path || 'Project file';
  const contentType = firstText(value.content_type, value.contentType);
  const fileKind = firstText(value.file_kind, value.fileKind) || workspaceFileKind({ path, name, contentType, previewKind: kind });
  const artifactId = firstText(value.artifact_id, value.artifactId);
  const recordType = firstText(value.record_type, value.recordType) || workspaceFileRecordType({
    recordLabel: firstText(value.record_label, value.recordLabel),
    artifactId,
    preview: true
  });
  const origin = workspaceFileOrigin(value.origin_context || value.originContext);
  return {
    status,
    previewKind: kind,
    fileKind,
    path,
    name,
    title: path || name,
    contentType,
    kindLabel: firstText(value.kind_label, value.kindLabel) || workspaceFileKindLabel(fileKind),
    recordLabel: firstText(value.record_label, value.recordLabel) || workspaceFileRecordLabel(recordType),
    sizeLabel: firstText(value.size_label, value.sizeLabel),
    text: firstText(value.text),
    dataUrl: firstText(value.data_url, value.dataUrl),
    documentUrl: safeDocumentUrl(firstText(value.document_url, value.documentUrl)),
    notebook: notebookPreviewModel(value.notebook),
    artifactId,
    recordType,
    artifactTitle: firstText(value.artifact_title, value.artifactTitle),
    originContext: origin,
    originFrameId: origin.frameId,
    originFrameTitle: origin.frameTitle,
    originRunKey: origin.runIds[0] || '',
    reason: firstText(value.reason, value.error && value.error.message),
    truncated: Boolean(value.truncated)
  };
}

export function workspaceFileContextPayload(value) {
  return workspaceFileContextPayloadFromModel(workspaceFilePreviewModel(value));
}

export function renderWorkspaceFiles(container, payload, options = {}) {
  if (!container) return;
  const model = workspaceFilesModel(payload, options);
  container.innerHTML = '';
  container.hidden = false;
  container.setAttribute('data-testid', 'genomi-workspace-files');
  container.appendChild(workspaceFilesToolbar(model, options));
  const preview = workspaceFilePreviewModel(options.preview);
  if (preview) container.appendChild(workspaceFilePreviewPanel(preview, options));
  if (!model.files.length) {
    container.appendChild(emptyWorkspaceFiles(model.query));
    return;
  }
  const list = document.createElement('div');
  list.className = 'workspace-file-list';
  list.setAttribute('data-testid', 'genomi-workspace-file-list');
  model.groups.forEach((group) => list.appendChild(workspaceFileGroup(group, options)));
  container.appendChild(list);
}

function workspaceFileGroup(group, options) {
  const section = document.createElement('section');
  section.className = 'workspace-file-group';
  section.setAttribute('data-testid', 'genomi-workspace-file-group');
  section.dataset.groupKey = group.key;
  const header = document.createElement('div');
  header.className = 'workspace-file-group-head';
  header.innerHTML = '<strong></strong><span></span>';
  header.querySelector('strong').textContent = group.label;
  header.querySelector('span').textContent = group.summary;
  section.appendChild(header);
  const rows = document.createElement('div');
  rows.className = 'workspace-file-group-rows';
  group.files.forEach((file) => rows.appendChild(workspaceFileRow(file, options)));
  section.appendChild(rows);
  return section;
}

function workspaceFilesToolbar(model, options) {
  const toolbar = document.createElement('div');
  toolbar.className = 'workspace-files-toolbar';
  toolbar.innerHTML = [
    '<div class="workspace-files-title"><strong></strong><span></span></div>',
    '<div class="workspace-file-locations" data-testid="genomi-workspace-file-locations"></div>',
    '<label><span>Search files</span><input type="search" autocomplete="off" placeholder="reports, csv, vcf"></label>'
  ].join('');
  const title = toolbar.querySelector('.workspace-files-title');
  const linkedSummary = model.linkedArtifacts ? String(model.linkedArtifacts) + ' linked record' + (model.linkedArtifacts === 1 ? '' : 's') : '';
  title.querySelector('strong').textContent = model.workspace.label;
  title.querySelector('span').textContent = [
    model.workspace.ownerLabel,
    model.summary,
    linkedSummary
  ].filter(Boolean).join(' · ');
  const locations = toolbar.querySelector('.workspace-file-locations');
  model.locations.forEach((location) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'workspace-file-location' + (location.active ? ' active' : '');
    button.dataset.locationKey = location.key;
    button.setAttribute('data-testid', 'genomi-workspace-file-location');
    button.textContent = location.label + ' · ' + String(location.count);
    button.addEventListener('click', () => {
      if (typeof options.onLocation === 'function') options.onLocation(location.key);
    });
    locations.appendChild(button);
  });
  const input = toolbar.querySelector('input');
  input.value = model.query;
  input.setAttribute('data-testid', 'genomi-workspace-file-search');
  input.addEventListener('input', () => {
    if (typeof options.onQuery === 'function') options.onQuery(cleanQuery(input.value));
  });
  return toolbar;
}

function workspaceFileRow(file, options) {
  const row = document.createElement('div');
  row.className = 'workspace-file-row';
  row.setAttribute('data-testid', 'genomi-workspace-file-row');
  row.setAttribute('role', 'button');
  row.setAttribute('tabindex', '0');
  row.setAttribute('aria-label', 'Preview ' + file.path);
  row.dataset.filePath = file.path;
  row.innerHTML = '<div><em></em><strong></strong><span></span></div><div class="workspace-file-actions"></div>';
  row.querySelector('em').textContent = file.kindLabel;
  row.querySelector('strong').textContent = file.path;
  row.querySelector('span').textContent = [
    file.contentType,
    file.sizeLabel,
    file.recordLabel
  ].filter(Boolean).join(' · ');
  const actions = row.querySelector('.workspace-file-actions');
  const openPreview = () => {
    if (typeof options.onPreviewFile === 'function') options.onPreviewFile(file);
  };
  row.addEventListener('click', openPreview);
  row.addEventListener('keydown', (event) => {
    if (event && (event.key === 'Enter' || event.key === ' ')) {
      if (typeof event.preventDefault === 'function') event.preventDefault();
      openPreview();
    }
  });
  if (typeof options.onPreviewFile === 'function') {
    const preview = document.createElement('button');
    preview.className = 'tool-action';
    preview.type = 'button';
    preview.textContent = 'Preview';
    preview.setAttribute('data-testid', 'genomi-workspace-file-preview');
    preview.addEventListener('click', (event) => {
      if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
      openPreview();
    });
    actions.appendChild(preview);
  }
  if (
    (file.artifactId && typeof options.onOpenArtifact === 'function') ||
    (file.originFrameId && typeof options.onViewContext === 'function')
  ) {
    actions.appendChild(workspaceFileMoreMenu(file, options));
  }
  return row;
}

function workspaceFileMoreMenu(file, options) {
  const menu = document.createElement('details');
  menu.className = 'workspace-file-more';
  const summary = document.createElement('summary');
  summary.textContent = 'More';
  summary.setAttribute('aria-label', 'More actions for ' + file.path);
  menu.appendChild(summary);
  const body = document.createElement('div');
  body.className = 'workspace-file-more-menu';
  if (file.artifactId && typeof options.onOpenArtifact === 'function') {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = 'Open details';
    button.setAttribute('data-testid', 'genomi-workspace-file-open-artifact');
    button.addEventListener('click', (event) => {
      if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
      options.onOpenArtifact(file);
    });
    body.appendChild(button);
  }
  if (file.originFrameId && typeof options.onViewContext === 'function') {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = 'Open origin chat';
    button.setAttribute('data-testid', 'genomi-workspace-file-view-context');
    button.addEventListener('click', (event) => {
      if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
      options.onViewContext(file.originContext, file);
    });
    body.appendChild(button);
  }
  menu.appendChild(body);
  menu.addEventListener('click', (event) => {
    if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
  });
  return menu;
}

function workspaceFilePreviewPanel(model, options) {
  const panel = document.createElement('section');
  panel.className = 'workspace-file-preview file-kind-' + model.fileKind;
  panel.setAttribute('data-testid', 'genomi-workspace-file-preview-panel');
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'true');
  panel.setAttribute('aria-label', 'File preview: ' + model.title);
  const dialog = document.createElement('div');
  dialog.className = 'workspace-file-preview-dialog';
  dialog.innerHTML = [
    '<div class="workspace-file-preview-head"><div><em></em><span></span><strong></strong></div><div class="workspace-file-preview-actions"></div></div>',
    '<div class="workspace-file-preview-body"></div>'
  ].join('');
  panel.appendChild(dialog);
  dialog.querySelector('em').textContent = model.kindLabel + ' · ' + model.recordLabel;
  dialog.querySelector('span').textContent = [model.contentType, model.sizeLabel].filter(Boolean).join(' · ') || 'Project file';
  dialog.querySelector('strong').textContent = model.title;
  const actions = dialog.querySelector('.workspace-file-preview-actions');
  if (typeof options.onUseFile === 'function') {
    const include = document.createElement('button');
    include.type = 'button';
    include.className = 'tool-action workspace-file-primary-action';
    include.textContent = 'Use file';
    include.setAttribute('data-testid', 'genomi-workspace-file-include');
    include.addEventListener('click', () => options.onUseFile(workspaceFileContextPayload(model)));
    actions.appendChild(include);
  }
  const more = workspaceFilePreviewMoreMenu(model, options);
  if (more) actions.appendChild(more);
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'tool-action';
  close.textContent = 'Close';
  close.addEventListener('click', () => {
    if (typeof options.onClosePreview === 'function') options.onClosePreview();
  });
  actions.appendChild(close);
  const body = dialog.querySelector('.workspace-file-preview-body');
  body.appendChild(workspaceFilePreviewContentElement(model));
  panel.addEventListener('click', (event) => {
    if (event && event.target === panel && typeof options.onClosePreview === 'function') options.onClosePreview();
  });
  panel.addEventListener('keydown', (event) => {
    if (event && event.key === 'Escape' && typeof options.onClosePreview === 'function') options.onClosePreview();
  });
  return panel;
}

function workspaceFilePreviewMoreMenu(model, options) {
  const canStartConversation = typeof options.onAskNewFile === 'function';
  const canOpenArtifact = model.artifactId && typeof options.onOpenArtifact === 'function';
  const canViewOrigin = model.originFrameId && typeof options.onViewContext === 'function';
  if (!canStartConversation && !canOpenArtifact && !canViewOrigin) return null;
  const menu = document.createElement('details');
  menu.className = 'workspace-file-more workspace-file-preview-more';
  const summary = document.createElement('summary');
  summary.textContent = 'More';
  menu.appendChild(summary);
  const body = document.createElement('div');
  body.className = 'workspace-file-more-menu';
  if (canStartConversation) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = 'Start conversation';
    button.setAttribute('data-testid', 'genomi-workspace-file-ask-new');
    button.addEventListener('click', () => options.onAskNewFile(workspaceFileContextPayload(model)));
    body.appendChild(button);
  }
  if (canOpenArtifact) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = 'Open details';
    button.setAttribute('data-testid', 'genomi-workspace-preview-open-artifact');
    button.addEventListener('click', () => options.onOpenArtifact(model));
    body.appendChild(button);
  }
  if (canViewOrigin) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = 'Open origin chat';
    button.setAttribute('data-testid', 'genomi-workspace-preview-view-context');
    button.addEventListener('click', () => options.onViewContext(model.originContext, model));
    body.appendChild(button);
  }
  menu.appendChild(body);
  return menu;
}

function emptyWorkspaceFiles(query) {
  const empty = document.createElement('div');
  empty.className = 'workspace-file-empty';
  empty.innerHTML = '<strong></strong><span></span>';
  empty.querySelector('strong').textContent = query ? 'No matching files' : 'No project files yet';
  empty.querySelector('span').textContent = query
    ? 'Change the search to inspect another project file.'
    : 'Imported files and generated research records in this Genomi workspace will appear here.';
  return empty;
}

function workspaceFileItem(file) {
  const path = firstText(file.relative_path, file.relativePath, file.path);
  const name = firstText(file.name) || path.split('/').pop() || path;
  const directory = firstText(file.directory);
  const contentType = firstText(file.content_type, file.contentType);
  const sizeLabel = firstText(file.size_label, file.sizeLabel);
  const artifactId = firstText(file.artifact_id, file.artifactId);
  const recordLabel = firstText(file.record_label, file.recordLabel);
  const recordType = firstText(file.record_type, file.recordType) || workspaceFileRecordType({ recordLabel, artifactId });
  const origin = workspaceFileOrigin(file.origin_context || file.originContext);
  const fileKind = firstText(file.file_kind, file.fileKind) || workspaceFileKind({ path, name, contentType });
  return {
    path,
    name,
    directory,
    contentType,
    fileKind,
    kindLabel: firstText(file.kind_label, file.kindLabel) || workspaceFileKindLabel(fileKind),
    recordType,
    recordLabel: recordLabel || workspaceFileRecordLabel(recordType),
    sizeBytes: Number(file.size_bytes || file.sizeBytes || 0),
    sizeLabel,
    modifiedAt: firstText(file.modified_at, file.modifiedAt),
    artifactId,
    artifactTitle: firstText(file.artifact_title, file.artifactTitle),
    originContext: origin,
    originFrameId: origin.frameId,
    originFrameTitle: origin.frameTitle,
    originRunKey: origin.runIds[0] || '',
    searchText: [path, name, directory, contentType, fileKind, artifactId].filter(Boolean).join(' ').toLowerCase()
  };
}

function workspaceFilePreviewReference(file) {
  const item = workspaceFileItem(file || {});
  const reference = {
    relative_path: item.path,
    name: item.name,
    content_type: item.contentType,
    file_kind: item.fileKind,
    kind_label: item.kindLabel,
    size_label: item.sizeLabel,
    record_type: item.recordType,
    artifact_id: item.artifactId,
    artifact_title: item.artifactTitle
  };
  if (item.artifactId && item.recordLabel) reference.record_label = item.recordLabel;
  if (item.originFrameId || item.originContext.runIds.length) {
    reference.origin_context = {
      frame_id: item.originFrameId,
      frame_title: item.originFrameTitle,
      run_ids: item.originContext.runIds
    };
  }
  return Object.fromEntries(Object.entries(reference).filter(([, value]) => {
    if (Array.isArray(value)) return value.length;
    if (value && typeof value === 'object') return Object.keys(value).some((key) => {
      const child = value[key];
      return Array.isArray(child) ? child.length : Boolean(child);
    });
    return Boolean(value);
  }));
}

function workspaceFileGroups(files) {
  const generatedRecords = files
    .filter((file) => file.recordType === 'generated_record')
    .sort((left, right) => left.path.localeCompare(right.path));
  const importedFiles = files
    .filter((file) => file.recordType === 'imported_file')
    .sort((left, right) => left.path.localeCompare(right.path));
  const ordinaryFiles = files.filter((file) => file.recordType !== 'generated_record' && file.recordType !== 'imported_file');
  const groups = [];
  groups.push(...workspaceGeneratedRecordGroups(generatedRecords));
  if (importedFiles.length) {
    groups.push({
      key: 'imported_files',
      label: 'Imported files',
      summary: String(importedFiles.length) + ' imported file' + (importedFiles.length === 1 ? '' : 's'),
      files: importedFiles
    });
  }
  const byDirectory = new Map();
  ordinaryFiles.forEach((file) => {
    const key = file.directory || '';
    const group = byDirectory.get(key) || [];
    group.push(file);
    byDirectory.set(key, group);
  });
  return groups.concat(Array.from(byDirectory.entries())
    .sort(([left], [right]) => workspaceDirectorySortKey(left).localeCompare(workspaceDirectorySortKey(right)))
    .map(([directory, groupFiles]) => ({
      key: directory || 'project_root',
      label: directory || 'Project root',
      summary: String(groupFiles.length) + ' file' + (groupFiles.length === 1 ? '' : 's'),
      files: groupFiles
    })));
}

function workspaceFileLocations(files, activeKey) {
  const locations = [{ key: 'all', label: 'All files', count: files.length }];
  const generatedCount = files.filter((file) => file.recordType === 'generated_record').length;
  if (generatedCount) locations.push({ key: 'generated_records', label: 'Generated records', count: generatedCount });
  const importedCount = files.filter((file) => file.recordType === 'imported_file').length;
  if (importedCount) locations.push({ key: 'imported_files', label: 'Imported files', count: importedCount });
  const directories = new Map();
  files.filter((file) => file.recordType !== 'generated_record' && file.recordType !== 'imported_file').forEach((file) => {
    const directory = file.directory || '';
    directories.set(directory, (directories.get(directory) || 0) + 1);
  });
  Array.from(directories.entries())
    .sort(([left], [right]) => workspaceDirectorySortKey(left).localeCompare(workspaceDirectorySortKey(right)))
    .forEach(([directory, count]) => {
      locations.push({
        key: 'directory:' + directory,
        label: directory || 'Project root',
        count
      });
    });
  return locations;
}

function workspaceGeneratedRecordGroups(files) {
  if (!files.length) return [];
  const byOrigin = new Map();
  const withoutRun = [];
  files.forEach((file) => {
    const originKey = generatedRecordOriginKey(file);
    if (!originKey) {
      withoutRun.push(file);
      return;
    }
    const group = byOrigin.get(originKey) || [];
    group.push(file);
    byOrigin.set(originKey, group);
  });
  const runGroups = Array.from(byOrigin.values()).map((groupFiles, index, allGroups) => ({
    key: generatedRecordGroupKey(groupFiles, index),
    label: generatedRecordGroupLabel(groupFiles, index, allGroups.length),
    summary: generatedRecordGroupSummary(groupFiles),
    files: groupFiles
  }));
  if (!withoutRun.length) return runGroups;
  return runGroups.concat({
    key: 'generated_records',
    label: 'Generated records',
    summary: String(withoutRun.length) + ' linked research record' + (withoutRun.length === 1 ? '' : 's'),
    files: withoutRun
  });
}

function generatedRecordTurnSummary(count) {
  return String(count) + ' generated record' + (count === 1 ? '' : 's') + ' from this assistant turn';
}

function generatedRecordOriginKey(file) {
  if (file.originFrameId) return 'frame:' + file.originFrameId;
  if (file.originRunKey) return 'run:' + file.originRunKey;
  return '';
}

function generatedRecordGroupKey(groupFiles, index) {
  const first = groupFiles[0] || {};
  if (first.originFrameId) return 'generated_record_frame_' + first.originFrameId;
  return 'generated_record_turn_' + String(index + 1);
}

function generatedRecordGroupLabel(groupFiles, index, groupCount) {
  const first = groupFiles[0] || {};
  if (first.originFrameTitle) return 'Created in ' + first.originFrameTitle;
  if (first.originFrameId) return 'Created in conversation';
  return groupCount === 1 ? 'Created in assistant turn' : 'Created in assistant turn ' + String(index + 1);
}

function generatedRecordGroupSummary(groupFiles) {
  const count = groupFiles.length;
  const first = groupFiles[0] || {};
  if (first.originFrameTitle || first.originFrameId) {
    return String(count) + ' generated record' + (count === 1 ? '' : 's') + ' from this conversation';
  }
  return generatedRecordTurnSummary(count);
}

function workspaceDirectorySortKey(directory) {
  return directory ? '1:' + directory.toLowerCase() : '0:';
}

function workspaceFileOrigin(value) {
  const origin = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const runIds = Array.isArray(origin.run_ids)
    ? origin.run_ids
    : Array.isArray(origin.runIds)
      ? origin.runIds
      : [];
  const producingRunId = firstText(origin.producing_run_id, origin.producingRunId);
  const cleanRunIds = [producingRunId].concat(runIds)
    .map((runId) => firstText(runId))
    .filter(Boolean);
  return {
    frameId: firstText(origin.frame_id, origin.frameId),
    frameTitle: firstText(origin.frame_title, origin.frameTitle),
    runIds: Array.from(new Set(cleanRunIds))
  };
}

function workspaceDescriptor(value) {
  const workspace = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const scope = firstText(workspace.scope);
  const owner = firstText(workspace.owner);
  const storage = firstText(workspace.storage);
  const isProjectWorkspace = scope === 'project' || owner === 'genomi_webui' || storage === 'genomi_home_workspace';
  const isAgentWorkspace = scope === 'agent' || owner === 'host_agent' || storage === 'host_agent_current_working_directory';
  return {
    scope,
    owner,
    storage,
    label: isProjectWorkspace ? 'Project workspace' : 'Workspace',
    ownerLabel: isProjectWorkspace
      ? 'Genomi-owned files'
      : (isAgentWorkspace ? 'Host-agent workspace' : '')
  };
}

function workspaceFileKind(file) {
  const contentType = String(file && file.contentType || '').toLowerCase();
  const name = String(file && (file.path || file.name) || '').toLowerCase();
  if (contentType === 'application/pdf' || name.endsWith('.pdf') || (file && file.previewKind === 'document')) return 'pdf';
  if (name.endsWith('.ipynb') || contentType === 'application/x-ipynb+json' || (file && file.previewKind === 'notebook')) return 'notebook';
  if (contentType === 'text/markdown' || name.endsWith('.md') || name.endsWith('.markdown')) return 'markdown';
  if (contentType.startsWith('image/') || (file && file.previewKind === 'image')) return 'image';
  if (
    name.endsWith('.py') ||
    name.endsWith('.r') ||
    name.endsWith('.sh') ||
    name.endsWith('.js') ||
    name.endsWith('.ts') ||
    name.endsWith('.sql')
  ) return 'code';
  if (
    contentType === 'text/csv' ||
    contentType === 'text/tab-separated-values' ||
    name.endsWith('.csv') ||
    name.endsWith('.tsv')
  ) return 'table';
  if (contentType.startsWith('text/') || name.endsWith('.txt') || name.endsWith('.log')) return 'text';
  if (contentType === 'application/json' || contentType.endsWith('+json') || name.endsWith('.json') || name.endsWith('.jsonl')) return 'data';
  return 'file';
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

function notebookPreviewModel(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const cells = Array.isArray(value.cells)
    ? value.cells.filter((cell) => cell && typeof cell === 'object' && !Array.isArray(cell)).map(notebookCellModel)
    : [];
  return {
    status: firstText(value.status) || 'available',
    summary: firstText(value.summary),
    language: firstText(value.language),
    cellCount: Number(value.cell_count || value.cellCount || 0),
    codeCellCount: Number(value.code_cell_count || value.codeCellCount || 0),
    markdownCellCount: Number(value.markdown_cell_count || value.markdownCellCount || 0),
    shownCellCount: Number(value.shown_cell_count || value.shownCellCount || cells.length),
    truncated: Boolean(value.truncated),
    cells
  };
}

function notebookCellModel(value) {
  const type = firstText(value.cell_type, value.cellType, value.type) || 'unknown';
  return {
    index: Number(value.index || 0),
    type,
    source: firstText(value.source),
    lineCount: Number(value.line_count || value.lineCount || 0),
    outputCount: Number(value.output_count || value.outputCount || 0),
    truncated: Boolean(value.truncated)
  };
}

function safeDocumentUrl(value) {
  const url = firstText(value);
  if (!url || /^(javascript|data|file):/i.test(url)) return '';
  if (url.startsWith('/api/projects/')) return url;
  return '';
}

function matchesQuery(file, query) {
  if (!query) return true;
  return query.split(/\s+/).every((term) => file.searchText.includes(term));
}

function matchesLocation(file, locationKey) {
  if (!locationKey || locationKey === 'all') return true;
  if (locationKey === 'generated_records') return file.recordType === 'generated_record';
  if (locationKey === 'imported_files') return file.recordType === 'imported_file';
  if (locationKey.startsWith('directory:')) {
    return file.recordType !== 'generated_record' && file.recordType !== 'imported_file' && (file.directory || '') === locationKey.slice('directory:'.length);
  }
  return true;
}

function workspaceFileRecordType({ recordLabel, artifactId, preview = false } = {}) {
  const label = firstText(recordLabel).toLowerCase();
  if (label === 'imported file') return 'imported_file';
  if (label === 'generated record') return 'generated_record';
  if (label === 'research record') return 'research_record';
  if (artifactId) return 'generated_record';
  return preview ? 'research_record' : 'research_file';
}

function workspaceFileRecordLabel(recordType) {
  switch (recordType) {
    case 'generated_record':
      return 'Generated record';
    case 'imported_file':
      return 'Imported file';
    case 'research_record':
      return 'Research record';
    default:
      return 'Research file';
  }
}

function cleanQuery(value) {
  return String(value || '').trim().toLowerCase();
}

function cleanLocationKey(value) {
  const text = String(value || '').trim();
  return text || 'all';
}

function firstText(...values) {
  for (const value of values) {
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return '';
}
