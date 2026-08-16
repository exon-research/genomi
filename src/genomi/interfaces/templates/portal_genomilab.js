const PROVIDERS = Object.freeze([
  {
    id: 'paperclip',
    name: 'GXL Paperclip',
    description: 'Biomedical literature, regulatory, and trial evidence for explicitly approved investigation requests.',
    boundary: 'Public-source searches remain separate from private health context unless you explicitly approve a relevant transfer.'
  },
  {
    id: 'biohub-esm',
    name: 'BioHub ESM',
    description: 'Connection to the reviewed ESM endpoint for protein-model workflows.',
    boundary: 'Protein sequences are sent only for approved public or research-only comparisons.'
  },
  {
    id: 'proto',
    name: 'Proto',
    description: 'Typed computational-biology tools for approved public research inputs.',
    boundary: 'A Proto tool runs only after its typed inputs and external-transfer boundary are clear in the conversation.'
  }
]);

export function createGenomiLabController({ api, getProjectId }) {
  const byId = (id) => document.getElementById(id);
  let profile = null;
  let activeProfileFormId = '';

  function bind() {
    mountJourney();
    byId('refresh-patient-context')?.addEventListener('click', () => void loadProfile());
    byId('refresh-research-connections')?.addEventListener('click', () => void loadConnections());
    byId('refresh-genomilab-board')?.addEventListener('click', () => void loadBoard());
    byId('patient-observation-form')?.addEventListener('submit', submitObservation);
    byId('patient-report-form')?.addEventListener('submit', submitReport);
    byId('patient-specimen-form')?.addEventListener('submit', submitSpecimen);
    byId('patient-assay-form')?.addEventListener('submit', submitAssay);
    byId('patient-context-add')?.addEventListener('click', toggleProfileEditor);
    byId('patient-context-type-chooser')?.addEventListener('click', chooseProfileForm);
    byId('patient-context-editor')?.addEventListener('click', cancelProfileEditor);
  }

  function toggleProfileEditor() {
    const editor = byId('patient-context-editor');
    if (!editor) return;
    if (!editor.hidden) {
      closeProfileEditor();
      return;
    }
    editor.hidden = false;
    byId('patient-context-add')?.setAttribute('aria-expanded', 'true');
    if (activeProfileFormId) showProfileForm(activeProfileFormId, { focus: false });
    else byId('patient-context-type-chooser')?.querySelector('button')?.focus();
  }

  function chooseProfileForm(event) {
    const button = event.target.closest('button[data-profile-form]');
    if (!button) return;
    showProfileForm(button.dataset.profileForm);
  }

  function cancelProfileEditor(event) {
    if (!event.target.closest('[data-profile-form-cancel]')) return;
    closeProfileEditor();
  }

  function showProfileForm(formId, { focus = true } = {}) {
    const editor = byId('patient-context-editor');
    const selected = byId(formId);
    if (!editor || !selected || !selected.matches('[data-profile-entry-form]')) return;
    const forms = [...editor.querySelectorAll('[data-profile-entry-form]')];
    const selection = profileEditorSelection(forms.map((form) => form.id), formId);
    if (!selection.activeFormId) return;
    activeProfileFormId = selection.activeFormId;
    editor.hidden = false;
    byId('patient-context-add')?.setAttribute('aria-expanded', 'true');
    forms.forEach((form) => {
      form.hidden = selection.hiddenByFormId[form.id];
    });
    byId('patient-context-type-chooser')?.querySelectorAll('[data-profile-form]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.profileForm === selection.activeFormId));
    });
    if (focus) selected.querySelector('input, select, textarea')?.focus();
  }

  function closeProfileEditor() {
    const editor = byId('patient-context-editor');
    if (editor) editor.hidden = true;
    byId('patient-context-add')?.setAttribute('aria-expanded', 'false');
  }

  async function loadAll() {
    await Promise.all([loadProfile(), loadConnections(), loadBoard()]);
  }

  function mountJourney() {
    const workspace = byId('research-workspace');
    const messages = byId('messages');
    if (!workspace || !messages || byId('health-testing-step')) return;
    const steps = [
      ['health-testing-step', 'Health history and testing', 'Add facts, reports, specimens, and assay limits.', byId('patient-context-pane')],
      ['research-connections-step', 'Research connections', 'Review available evidence and model providers.', byId('research-connections-pane')]
    ];
    const mounted = [];
    for (const [id, title, description, pane] of steps) {
      if (!pane) continue;
      const details = document.createElement('details');
      details.id = id;
      details.className = 'genomilab-step-panel';
      const summary = document.createElement('summary');
      const copy = document.createElement('span');
      const strong = document.createElement('strong');
      strong.textContent = title;
      const small = document.createElement('small');
      small.textContent = description;
      copy.append(strong, small);
      summary.append(copy);
      pane.hidden = false;
      pane.removeAttribute('data-nav-section');
      pane.classList.add('genomilab-inline-pane');
      details.append(summary, pane);
      workspace.insertBefore(details, messages);
      mounted.push(details);
    }
    const composer = byId('composer');
    if (composer) workspace.insertBefore(composer, mounted[0] || messages);
    document.querySelectorAll('[data-genomilab-open]').forEach((button) => {
      button.addEventListener('click', () => {
        const details = byId(button.dataset.genomilabOpen);
        if (!(details instanceof HTMLDetailsElement)) return;
        details.open = true;
        details.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
    document.querySelector('[data-genomilab-focus-prompt]')?.addEventListener('click', () => {
      byId('prompt')?.focus();
      byId('composer')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }

  async function loadBoard() {
    const projectId = getProjectId();
    if (!projectId) return;
    setStatus('genomilab-board-status', 'Loading the investigation workspace…');
    try {
      const payload = await api.loadGenomiLabBoard(projectId);
      renderBoard(payload);
    } catch (error) {
      renderBoard(null);
      setStatus('genomilab-board-status', error.message || 'The investigation workspace is unavailable.', 'error');
    }
  }

  async function loadProfile() {
    const projectId = getProjectId();
    if (!projectId) return;
    setStatus('patient-context-status', 'Loading local health and testing context…');
    try {
      const payload = await api.loadGenomiLabProfile(projectId);
      profile = payload && payload.profile && typeof payload.profile === 'object' ? payload.profile : null;
      renderProfile(payload);
      renderOnboardingProfile(payload);
      setStatus('patient-context-status', profile ? 'Local context ready.' : setupMessage(payload), profile ? 'success' : '');
    } catch (error) {
      profile = null;
      renderProfile(null);
      setOnboardingState('onboarding-profile-state', 'Unavailable');
      setStatus('patient-context-status', error.message || 'Health context is unavailable.', 'error');
    }
  }

  async function loadConnections() {
    const projectId = getProjectId();
    if (!projectId) return;
    renderConnections(null);
    setStatus('research-connections-status', 'Checking research connections…');
    try {
      const payload = await api.loadGenomiLabIntegrations(projectId);
      renderConnections(payload);
      renderOnboardingConnections(payload);
      setStatus('research-connections-status', payload.status === 'ready' || payload.integrations ? 'Connection state ready.' : setupMessage(payload), payload.integrations ? 'success' : '');
    } catch (error) {
      renderConnections(null);
      setOnboardingState('onboarding-connections-state', 'Unavailable');
      setStatus('research-connections-status', error.message || 'Research connections are unavailable.', 'error');
    }
  }

  async function submitObservation(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const values = new FormData(form);
    const payload = {
      modality: text(values.get('modality')),
      label: text(values.get('label')),
      assertion_status: text(values.get('assertion_status')) || 'present'
    };
    optional(payload, 'artifact_id', values.get('artifact_id'));
    optional(payload, 'specimen_id', values.get('specimen_id'));
    optional(payload, 'assay_id', values.get('assay_id'));
    await submitProfileForm(form, () => api.addGenomiLabObservation(getProjectId(), payload), 'Health context saved.');
  }

  async function submitReport(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const values = new FormData(form);
    const file = values.get('report_file');
    if (!(file instanceof File)) return;
    const contentSha256 = await sha256(file);
    const payload = {
      content_sha256: contentSha256,
      source_type: text(values.get('source_type')) || 'issued_report',
      title: text(values.get('title'))
    };
    optional(payload, 'issued_at', values.get('issued_at'));
    await submitProfileForm(form, () => api.addGenomiLabSourceArtifact(getProjectId(), payload), 'Report fingerprint registered; file bytes were not uploaded.');
  }

  async function submitSpecimen(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const values = new FormData(form);
    const payload = {
      specimen_type: text(values.get('specimen_type')),
      tumor_normal_role: text(values.get('tumor_normal_role')) || 'unknown'
    };
    optional(payload, 'artifact_id', values.get('artifact_id'));
    optional(payload, 'body_site', values.get('body_site'));
    await submitProfileForm(form, () => api.addGenomiLabSpecimen(getProjectId(), payload), 'Specimen saved.');
  }

  async function submitAssay(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const values = new FormData(form);
    const payload = {
      assay_type: text(values.get('assay_type')),
      assay_scope: { reported_description: text(values.get('assay_scope')) },
      detection_limits: { reported_description: text(values.get('detection_limits')) }
    };
    for (const key of ['artifact_id', 'specimen_id', 'laboratory', 'platform', 'genome_build']) optional(payload, key, values.get(key));
    await submitProfileForm(form, () => api.addGenomiLabAssay(getProjectId(), payload), 'Assay scope and detection limits saved.');
  }

  async function submitProfileForm(form, operation, success) {
    setFormBusy(form, true);
    try {
      await operation();
      form.reset();
      setStatus('patient-context-status', success, 'success');
      await loadProfile();
      showProfileForm(form.id, { focus: false });
    } catch (error) {
      setStatus('patient-context-status', error.message || 'The context could not be saved.', 'error');
    } finally {
      setFormBusy(form, false);
    }
  }

  function renderProfile(payload) {
    const container = byId('patient-context-summary');
    if (!container) return;
    container.replaceChildren();
    if (!profile) {
      container.append(card('Genomi user required', setupMessage(payload)));
      populateEntitySelects([], [], []);
      return;
    }
    const observations = array(profile.observations);
    const artifacts = array(profile.source_artifacts);
    const specimens = array(profile.specimens);
    const assays = array(profile.assays);
    container.append(
      profileCollectionHeader(observations, artifacts, specimens, assays),
      collectionGroup('Health facts', observations, 'No health facts added yet.', (item) => [
        text(item.label) || 'Untitled observation',
        [text(item.modality), text(item.assertion_status)].filter(Boolean).join(' · ')
      ]),
      collectionGroup('Reports', artifacts, 'No reports registered yet.', (item) => [
        text(item.title) || 'Untitled report',
        [text(item.source_type), text(item.issued_at)].filter(Boolean).join(' · ')
      ]),
      collectionGroup('Specimens', specimens, 'No specimens added yet.', (item) => [
        text(item.specimen_type) || 'Untitled specimen',
        [text(item.body_site), text(item.tumor_normal_role)].filter(Boolean).join(' · ')
      ]),
      collectionGroup('Tests & assays', assays, 'No tests or assays added yet.', (item) => [
        text(item.assay_type) || 'Untitled assay',
        assayDescription(item)
      ])
    );
    populateEntitySelects(artifacts, specimens, assays);
  }

  function populateEntitySelects(artifacts, specimens, assays) {
    populateSelects('[data-profile-artifact-select]', artifacts, 'artifact_id', 'title', 'No linked report');
    populateSelects('[data-profile-specimen-select]', specimens, 'specimen_id', 'specimen_type', 'No linked specimen');
    populateSelects('[data-profile-assay-select]', assays, 'assay_id', 'assay_type', 'No linked assay');
  }

  function renderOnboardingProfile(payload) {
    if (!profile) {
      setOnboardingState('onboarding-profile-state', 'Not added');
      return;
    }
    const observationCount = array(profile.observations).length;
    const reportCount = array(profile.source_artifacts).length;
    setOnboardingState(
      'onboarding-profile-state',
      observationCount || reportCount
        ? `${observationCount} health facts · ${reportCount} reports`
        : 'Not added'
    );
  }

  async function refreshFromToolRecord(record) {
    if (!completedLabOperation(record)) return false;
    await Promise.all([loadProfile(), loadBoard()]);
    return true;
  }

  function renderOnboardingConnections(payload) {
    const records = connectionRecords(payload);
    const availableCount = records.filter((record) => text(record.capability_state) === 'available').length;
    const readyCount = records.filter((record) => text(record.connection_state) === 'ready').length;
    setOnboardingState(
      'onboarding-connections-state',
      readyCount
        ? `${readyCount} ready · ${availableCount} capabilities available`
        : availableCount
          ? `${availableCount} capabilities available · credentials needed`
          : 'No research capabilities available'
    );
  }

  function renderConnections(payload) {
    const container = byId('research-connections-list');
    if (!container) return;
    container.replaceChildren();
    if (!payload || !Array.isArray(payload.integrations)) {
      container.append(card('Connection state', 'Research capability state could not be loaded.'));
      return;
    }
    const records = connectionRecords(payload);
    const byProvider = new Map(records.map((item) => [text(item.provider), item]));
    PROVIDERS.forEach((definition) => container.append(connectionCard(definition, byProvider.get(definition.id) || {})));
  }

  function renderBoard(payload) {
    const container = byId('genomilab-board-content');
    if (!container) return;
    container.replaceChildren();
    const investigation = payload && payload.investigation && typeof payload.investigation === 'object' ? payload.investigation : null;
    if (!investigation) {
      byId('genomilab-case-board').hidden = true;
      return;
    }
    byId('genomilab-case-board').hidden = false;
    setStatus('genomilab-board-status', text(investigation.status) || 'Investigation active', 'success');
    const brief = doctorBriefModel(investigation);
    container.append(
      boardCard('Question', text(investigation.question) || 'Investigation question recorded.'),
      boardCard('Hypotheses', boardCollection(investigation.hypotheses, investigation.hypothesis_count, 'hypotheses recorded')),
      specialistWorkstreamsCard(investigation.specialist_workstreams),
      evidenceBoardCard(investigation),
      doctorBriefCard(brief)
    );
  }

  return Object.freeze({ bind, loadAll, loadBoard, loadProfile, loadConnections, refreshFromToolRecord });
}

export function completedLabOperation(record) {
  if (!record || !record.result || record.result.isError === true) return '';
  const call = record.call && typeof record.call === 'object' ? record.call : {};
  const input = call.input && typeof call.input === 'object' ? call.input : {};
  const invoked = text(input.tool);
  if (invoked.startsWith('lab.')) return invoked;
  const direct = text(call.name);
  return direct.startsWith('lab.') ? direct : '';
}

export function profileEditorSelection(formIds, selectedFormId) {
  const ids = [...new Set(array(formIds).map(text).filter(Boolean))];
  const requested = text(selectedFormId);
  const activeFormId = ids.includes(requested) ? requested : '';
  return {
    activeFormId,
    hiddenByFormId: Object.fromEntries(ids.map((id) => [id, id !== activeFormId]))
  };
}

function profileCollectionHeader(observations, artifacts, specimens, assays) {
  const node = document.createElement('div');
  node.className = 'genomilab-collection-header';
  const copy = document.createElement('div');
  const title = document.createElement('strong');
  title.textContent = 'Your context collection';
  const detail = document.createElement('span');
  detail.textContent = 'Add as many entries as needed. Each item remains separate, reusable, and local.';
  copy.append(title, detail);
  const total = document.createElement('b');
  const count = observations.length + artifacts.length + specimens.length + assays.length;
  total.textContent = `${count} ${count === 1 ? 'item' : 'items'}`;
  node.append(copy, total);
  return node;
}

function collectionGroup(titleText, records, emptyText, describe) {
  const section = document.createElement('section');
  section.className = 'genomilab-collection-group';
  const heading = document.createElement('header');
  const title = document.createElement('h3');
  title.textContent = titleText;
  const count = document.createElement('span');
  count.textContent = String(records.length);
  heading.append(title, count);
  section.append(heading);
  if (!records.length) {
    const empty = document.createElement('p');
    empty.className = 'genomilab-collection-empty';
    empty.textContent = emptyText;
    section.append(empty);
    return section;
  }
  const list = document.createElement('ul');
  list.className = 'genomilab-observation-list';
  records.forEach((item) => {
    const [labelText, metaText] = describe(item);
    const row = document.createElement('li');
    const label = document.createElement('b');
    label.textContent = labelText;
    const meta = document.createElement('small');
    meta.textContent = metaText || 'Saved locally';
    row.append(label, meta);
    list.append(row);
  });
  section.append(list);
  return section;
}

function assayDescription(item) {
  const scope = item && item.assay_scope;
  const scopeText = scope && typeof scope === 'object'
    ? text(scope.reported_description)
    : text(scope);
  return [text(item.laboratory), text(item.platform), scopeText].filter(Boolean).join(' · ');
}

function connectionCard(definition, record) {
  const article = document.createElement('article');
  article.className = 'genomilab-connection-card';
  const head = document.createElement('div');
  head.className = 'genomilab-connection-head';
  const copy = document.createElement('div');
  const title = document.createElement('h3');
  title.textContent = definition.name;
  const description = document.createElement('p');
  description.textContent = definition.description;
  copy.append(title, description);
  const state = document.createElement('span');
  const connectionState = text(record.connection_state) || 'not_configured';
  state.className = 'genomilab-connection-state' + (connectionState === 'ready' ? ' ready' : '');
  state.textContent = connectionState === 'ready'
    ? 'Ready'
    : connectionState === 'credentials_required'
      ? 'Credentials needed'
      : 'Capability unavailable';
  head.append(copy, state);
  const boundary = document.createElement('p');
  boundary.textContent = definition.boundary;
  article.append(head, boundary);
  const policy = document.createElement('p');
  const operations = array(record.investigation_operations);
  policy.textContent = operations.length
    ? connectionState === 'ready'
      ? 'Available to Genomi for relevant, approved research requests.'
      : 'The capability is installed. Add its credentials to the Genomi environment or local api.md when you want to use it.'
    : 'This focused research capability is not installed in the current Genomi build.';
  article.append(policy);
  return article;
}

function boardCard(titleText, value) {
  const article = document.createElement('article');
  const title = document.createElement('h4');
  title.textContent = titleText;
  const body = document.createElement('p');
  body.textContent = text(value) || 'No update yet.';
  article.append(title, body);
  return article;
}

function boardCollection(values, count, fallbackLabel) {
  const entries = array(values).map((item) => text(item.statement || item.title || item.summary || item.objective)).filter(Boolean);
  if (entries.length) return entries.join(' · ');
  const numeric = Number(count || 0);
  return numeric ? `${numeric} ${fallbackLabel}.` : 'No update yet.';
}

export function specialistWorkstreamModels(values) {
  const states = {
    proposed: 'Ready to start',
    spawned: 'Researching',
    completed: 'Findings added',
    failed: 'Needs attention',
    cancelled: 'Stopped'
  };
  return array(values).filter((item) => item && typeof item === 'object').map((item) => ({
    role: humanLabel(item.specialist_role || 'Research specialist'),
    status: states[text(item.state)] || 'Status pending'
  }));
}

export function doctorBriefModel(investigation) {
  const versionRecord = investigation && investigation.current_brief && typeof investigation.current_brief === 'object'
    ? investigation.current_brief
    : null;
  const brief = versionRecord && versionRecord.brief && typeof versionRecord.brief === 'object'
    ? versionRecord.brief
    : null;
  if (!brief) return null;
  const hypotheses = array(investigation.hypotheses);
  const hypothesisById = new Map();
  hypotheses.forEach((item) => {
    if (!item || typeof item !== 'object') return;
    [item.logical_hypothesis_id, item.hypothesis_version_id, item.hypothesis_id]
      .map(text).filter(Boolean).forEach((identifier) => hypothesisById.set(identifier, item));
  });
  const evidenceById = new Map(array(investigation.evidence_records)
    .filter((item) => item && typeof item === 'object' && text(item.evidence_record_id))
    .map((item) => [text(item.evidence_record_id), item]));
  return {
    version: Number(versionRecord.version || investigation.current_brief_version || 0),
    title: text(brief.title) || 'Clinician discussion brief',
    summary: text(brief.summary),
    claims: array(brief.claims).filter((claim) => claim && typeof claim === 'object').map((claim) => ({
      statement: text(claim.statement),
      evidence: array(claim.evidence_record_ids).map((identifier) => evidenceAnchor(evidenceById.get(text(identifier)))).filter(Boolean),
      profileCount: array(claim.profile_revision_ids).filter(Boolean).length
    })).filter((claim) => claim.statement),
    hypotheses: array(brief.hypothesis_ids).map((identifier) => hypothesisById.get(text(identifier)))
      .filter(Boolean).map((item) => text(item.statement)).filter(Boolean),
    gaps: [
      ...array(brief.gap_ids).map((identifier) => hypothesisById.get(text(identifier)))
        .filter(Boolean).flatMap((item) => array(item.unresolved_gaps).length ? array(item.unresolved_gaps) : [item.statement]),
      ...array(investigation.information_gaps)
    ].map(text).filter((value, index, values) => value && values.indexOf(value) === index),
    confirmationNeeds: array(brief.confirmation_needs).map(text).filter(Boolean),
    professionalQuestions: array(brief.professional_questions).map(text).filter(Boolean),
    clinicalBoundary: text(brief.clinical_boundary)
  };
}

function specialistWorkstreamsCard(values) {
  const card = boardCardShell('Research workstreams');
  const workstreams = specialistWorkstreamModels(values);
  if (!workstreams.length) {
    card.append(boardParagraph('No specialist research has been assigned yet.'));
    return card;
  }
  const list = document.createElement('ul');
  list.className = 'genomilab-board-list genomilab-workstreams';
  workstreams.forEach((workstream) => {
    const item = document.createElement('li');
    const role = document.createElement('b');
    role.textContent = workstream.role;
    const status = document.createElement('span');
    status.textContent = workstream.status;
    item.append(role, status);
    list.append(item);
  });
  card.append(list);
  return card;
}

function evidenceBoardCard(investigation) {
  const card = boardCardShell('Evidence & research');
  card.append(boardParagraph(boardEvidenceSummary(investigation)));
  const sources = [...new Set(array(investigation.evidence_records)
    .map((item) => text(item && item.source_family)).filter(Boolean).map(humanLabel))];
  appendBriefList(card, 'Evidence sources', sources);
  const artifacts = array(investigation.research_artifacts).map((item) => {
    const content = item && item.artifact && typeof item.artifact === 'object' ? item.artifact : {};
    const kind = text(item && item.artifact_kind);
    return text(content.title || content.name || content.summary) || (kind ? humanLabel(kind) : '');
  }).filter(Boolean);
  appendBriefList(card, 'Research outputs', artifacts);
  return card;
}

function doctorBriefCard(model) {
  const card = boardCardShell('Doctor brief');
  card.classList.add('genomilab-doctor-brief');
  if (!model) {
    card.append(boardParagraph('Not published yet. Genomi will add an evidence-linked brief here when the investigation is ready.'));
    return card;
  }
  const heading = document.createElement('div');
  heading.className = 'genomilab-brief-heading';
  const title = document.createElement('h5');
  title.textContent = model.title;
  heading.append(title);
  if (model.version) {
    const version = document.createElement('span');
    version.textContent = `Version ${model.version}`;
    heading.append(version);
  }
  card.append(heading);
  if (model.summary) card.append(boardParagraph(model.summary));
  appendBriefClaims(card, model.claims);
  appendBriefList(card, 'Hypotheses under review', model.hypotheses);
  appendBriefList(card, 'Evidence gaps', model.gaps);
  appendBriefList(card, 'Confirmation needed', model.confirmationNeeds);
  appendBriefList(card, 'Questions for your clinician', model.professionalQuestions);
  if (model.clinicalBoundary) {
    const boundary = boardParagraph(model.clinicalBoundary);
    boundary.className = 'genomilab-clinical-boundary';
    card.append(boundary);
  }
  return card;
}

function appendBriefClaims(card, claims) {
  if (!claims.length) return;
  const section = briefSection(card, 'Key findings');
  const list = document.createElement('ul');
  list.className = 'genomilab-board-list genomilab-brief-claims';
  claims.forEach((claim) => {
    const item = document.createElement('li');
    const statement = document.createElement('p');
    statement.textContent = claim.statement;
    item.append(statement);
    const anchors = document.createElement('div');
    anchors.className = 'genomilab-claim-anchors';
    claim.evidence.forEach((anchor) => {
      const node = anchor.url ? document.createElement('a') : document.createElement('span');
      node.textContent = anchor.label;
      if (anchor.url) {
        node.href = anchor.url;
        node.target = '_blank';
        node.rel = 'noreferrer';
      }
      anchors.append(node);
    });
    if (claim.profileCount) {
      const profile = document.createElement('span');
      profile.textContent = `${claim.profileCount} health profile ${claim.profileCount === 1 ? 'anchor' : 'anchors'}`;
      anchors.append(profile);
    }
    if (anchors.childNodes.length) item.append(anchors);
    list.append(item);
  });
  section.append(list);
}

function appendBriefList(card, titleText, values) {
  if (!values.length) return;
  const section = briefSection(card, titleText);
  const list = document.createElement('ul');
  list.className = 'genomilab-board-list';
  values.forEach((value) => {
    const item = document.createElement('li');
    item.textContent = value;
    list.append(item);
  });
  section.append(list);
}

function briefSection(card, titleText) {
  const section = document.createElement('section');
  const title = document.createElement('h6');
  title.textContent = titleText;
  section.append(title);
  card.append(section);
  return section;
}

function evidenceAnchor(record) {
  if (!record) return null;
  const evidence = record.evidence && typeof record.evidence === 'object' ? record.evidence : {};
  const source = array(evidence.records).find((item) => item && typeof item === 'object') || evidence;
  const uri = safeSourceUrl(source.uri || source.url, source.doi, source.pmid);
  return {
    label: text(source.title || source.source || source.doi || source.pmid) || humanLabel(record.source_family || 'Evidence source'),
    url: uri
  };
}

function safeSourceUrl(candidate, doi, pmid) {
  const direct = text(candidate);
  if (/^https?:\/\//i.test(direct)) return direct;
  const doiValue = text(doi).replace(/^https?:\/\/doi\.org\//i, '');
  if (doiValue) return `https://doi.org/${encodeURI(doiValue)}`;
  const pmidValue = text(pmid);
  return pmidValue ? `https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(pmidValue)}/` : '';
}

function humanLabel(value) {
  const words = text(value).replace(/[_-]+/g, ' ').replace(/\bspecialist\b/gi, '').replace(/\s+/g, ' ').trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Research specialist';
}

function boardCardShell(titleText) {
  const article = document.createElement('article');
  const title = document.createElement('h4');
  title.textContent = titleText;
  article.append(title);
  return article;
}

function boardParagraph(value) {
  const body = document.createElement('p');
  body.textContent = value;
  return body;
}

function boardEvidenceSummary(investigation) {
  const parts = [];
  const evidenceCount = Number(investigation.evidence_count || 0);
  const artifactCount = Number(investigation.research_artifact_count || 0);
  const gapCount = Number(investigation.gap_count || 0);
  const questionCount = array(investigation.patient_questions).length;
  if (evidenceCount) parts.push(`${evidenceCount} evidence records`);
  if (artifactCount) parts.push(`${artifactCount} research ${artifactCount === 1 ? 'artifact' : 'artifacts'}`);
  if (gapCount) parts.push(`${gapCount} open gaps`);
  if (questionCount) parts.push(`${questionCount} follow-up questions`);
  return parts.length ? parts.join(' · ') : 'New records and missing evidence will be tracked here.';
}

function connectionRecords(payload) {
  const value = payload && payload.integrations;
  if (Array.isArray(value)) return value.filter((item) => item && typeof item === 'object');
  if (!value || typeof value !== 'object') return [];
  return Object.entries(value).map(([provider, record]) => ({ ...(record || {}), provider }));
}

function populateSelects(selector, records, valueKey, labelKey, emptyLabel) {
  document.querySelectorAll(selector).forEach((select) => {
    const current = select.value;
    select.replaceChildren(new Option(emptyLabel, ''));
    records.forEach((record) => select.append(new Option(text(record[labelKey]) || text(record[valueKey]), text(record[valueKey]))));
    select.value = records.some((record) => text(record[valueKey]) === current) ? current : '';
  });
}

function card(titleText, detailText) {
  const node = document.createElement('article');
  node.className = 'genomilab-summary-card';
  const title = document.createElement('strong');
  title.textContent = titleText;
  const detail = document.createElement('span');
  detail.textContent = detailText;
  node.append(title, detail);
  return node;
}

function setStatus(id, message, kind = '') {
  const node = document.getElementById(id);
  if (!node) return;
  node.textContent = message || '';
  node.className = 'genomilab-status' + (kind ? ' ' + kind : '');
}

function setOnboardingState(id, message) {
  const node = document.getElementById(id);
  if (node) node.textContent = message || '';
}

function setFormBusy(form, busy) {
  form.querySelectorAll('input, select, textarea, button').forEach((control) => { control.disabled = busy; });
}

function setupMessage(payload) {
  return text(payload && payload.setup && payload.setup.message) || 'Select a Genomi user and active genome before adding patient context.';
}

function optional(target, key, value) {
  const clean = text(value);
  if (clean) target[key] = clean;
}

function text(value) {
  return value === null || value === undefined ? '' : String(value).trim();
}

function array(value) {
  return Array.isArray(value) ? value : [];
}

async function sha256(file) {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}
