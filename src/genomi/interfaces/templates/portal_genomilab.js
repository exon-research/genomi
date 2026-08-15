const PROVIDERS = Object.freeze([
  {
    id: 'paperclip',
    name: 'GXL Paperclip',
    description: 'Biomedical literature, regulatory, and trial evidence for explicitly approved investigation requests.',
    boundary: 'The connection check sends one fixed public TP53 query with limit 1. It never sends health context. Patient-informed retrieval still requires exact disclosure approval.',
    fields: [{ name: 'api_key', label: 'Paperclip API key', secret: true }]
  },
  {
    id: 'biohub-esm',
    name: 'BioHub ESM',
    description: 'Connection to the reviewed ESM endpoint for protein-model workflows.',
    boundary: 'The check sends only GenomiLab\'s fixed synthetic 20-residue alphabet and may use credits. It does not send a patient-derived sequence or enable an analysis operation.',
    fields: [{ name: 'api_token', label: 'BioHub API token', secret: true }]
  },
  {
    id: 'proto',
    name: 'Proto prerequisite (Modal)',
    description: 'Connection to the Modal account and environment reserved for a reviewed Proto workflow.',
    boundary: 'The check lists Modal environments. It does not deploy, start, or run a Proto model.',
    fields: [
      { name: 'modal_token_id', label: 'Modal token ID', secret: true },
      { name: 'modal_token_secret', label: 'Modal token secret', secret: true },
      { name: 'modal_environment', label: 'Modal environment', secret: false }
    ]
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
    byId('research-connections-list')?.addEventListener('submit', submitConnection);
    byId('research-connections-list')?.addEventListener('click', handleConnectionAction);
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
      setOnboardingState('onboarding-agi-state', 'Needs attention');
      setOnboardingState('onboarding-profile-state', 'Unavailable');
      setStatus('patient-context-status', error.message || 'Health context is unavailable.', 'error');
    }
  }

  async function loadConnections() {
    const projectId = getProjectId();
    if (!projectId) return;
    renderConnections(null);
    setStatus('research-connections-status', 'Checking the encrypted local Lab store…');
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

  async function submitConnection(event) {
    const form = event.target.closest('form[data-provider]');
    if (!form) return;
    event.preventDefault();
    if (!form.reportValidity()) return;
    const payload = {};
    const values = new FormData(form);
    for (const [key, value] of values.entries()) payload[key] = text(value);
    await changeConnection(form.dataset.provider, 'connect', payload, form);
  }

  function handleConnectionAction(event) {
    const button = event.target.closest('button[data-provider-action]');
    if (!button) return;
    const action = button.dataset.providerAction;
    if (action === 'disconnect' && !window.confirm('Disconnect this research provider and remove its saved credentials?')) return;
    void changeConnection(button.dataset.provider, action, action === 'disconnect' ? { confirmed: true } : {}, button);
  }

  async function changeConnection(provider, action, payload, control) {
    setControlBusy(control, true);
    setStatus('research-connections-status', action === 'verify' ? 'Running the disclosed connection check…' : 'Updating secure connection state…');
    try {
      await api.changeGenomiLabIntegration(getProjectId(), provider, action, payload);
      if (control instanceof HTMLFormElement) control.reset();
      await loadConnections();
    } catch (error) {
      setStatus('research-connections-status', error.message || 'The connection could not be updated.', 'error');
    } finally {
      setControlBusy(control, false);
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
      setOnboardingState('onboarding-agi-state', 'Choose a genome');
      setOnboardingState('onboarding-profile-state', 'Not added');
      return;
    }
    const observationCount = array(profile.observations).length;
    const reportCount = array(profile.source_artifacts).length;
    setOnboardingState('onboarding-agi-state', 'Ready');
    setOnboardingState(
      'onboarding-profile-state',
      observationCount || reportCount
        ? `${observationCount} health facts · ${reportCount} reports`
        : 'Not added'
    );
  }

  function renderOnboardingConnections(payload) {
    const records = connectionRecords(payload);
    if (records.length && records.every((record) => text(record.connection_state) === 'backend_unavailable')) {
      setOnboardingState('onboarding-connections-state', 'Unavailable');
      return;
    }
    const readyCount = records.filter((record) => text(record.connection_state) === 'ready').length;
    const storedCount = records.filter((record) => text(record.credential_state) === 'stored').length;
    setOnboardingState(
      'onboarding-connections-state',
      readyCount
        ? `${readyCount} checked · ${storedCount} credentials encrypted locally`
        : storedCount
          ? `${storedCount} configured · run an explicit connection check`
          : 'Not configured'
    );
  }

  function renderConnections(payload) {
    const container = byId('research-connections-list');
    if (!container) return;
    container.replaceChildren();
    if (!payload || !Array.isArray(payload.integrations)) {
      container.append(card('Connection state', 'Waiting for the encrypted local Lab backend. No credentials can be entered while connection state is unavailable.'));
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
    container.append(
      boardCard('Question', text(investigation.question) || 'Investigation question recorded.'),
      boardCard('Hypotheses', boardCollection(investigation.hypotheses, investigation.hypothesis_count, 'hypotheses recorded')),
      boardCard('Specialist workstreams', boardCollection(investigation.specialist_workstreams, investigation.specialist_count, 'workstreams recorded')),
      boardCard('Evidence and questions', boardEvidenceSummary(investigation)),
      boardCard('Doctor brief', investigation.current_brief || (investigation.current_brief_version ? `Brief version ${investigation.current_brief_version} is ready.` : 'Not published yet.'))
    );
  }

  return Object.freeze({ bind, loadAll, loadProfile, loadConnections });
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
  state.textContent = connectionState.replaceAll('_', ' ');
  head.append(copy, state);
  const boundary = document.createElement('p');
  boundary.textContent = definition.boundary;
  article.append(head, boundary);
  if (connectionState === 'backend_unavailable') {
    const unavailable = document.createElement('p');
    unavailable.className = 'genomilab-connection-unavailable';
    unavailable.textContent = 'This connection is not available in the current encrypted Lab backend. No credential can be entered or sent.';
    article.append(unavailable);
    return article;
  }
  const form = document.createElement('form');
  form.className = 'genomilab-credential-form';
  form.dataset.provider = definition.id;
  form.autocomplete = 'off';
  definition.fields.forEach((field) => {
    const label = document.createElement('label');
    label.textContent = field.label;
    const input = document.createElement('input');
    input.name = field.name;
    input.type = field.secret ? 'password' : 'text';
    input.required = true;
    input.autocomplete = 'off';
    label.append(input);
    form.append(label);
  });
  const save = document.createElement('button');
  save.className = 'primary';
  save.type = 'submit';
  save.textContent = record.credential_state === 'stored' ? 'Replace credentials' : 'Save encrypted';
  form.append(save);
  article.append(form);
  if (record.credential_state === 'stored' || record.credential_state === 'corrupt') {
    const actions = document.createElement('div');
    actions.className = 'genomilab-connection-actions';
    if (record.verification_available !== false) actions.append(actionButton(definition.id, 'verify', verificationLabel(definition.id)));
    actions.append(actionButton(definition.id, 'disconnect', 'Disconnect'));
    article.append(actions);
  }
  const policy = document.createElement('p');
  const operations = array(record.investigation_operations);
  policy.textContent = operations.length
    ? `Enabled operations: ${operations.join(', ')}. Exact request approval remains required.`
    : `Use policy: ${text(record.policy_state) || 'not enabled'}. No model or investigation operation is implied by a successful connection check.`;
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

function boardEvidenceSummary(investigation) {
  const parts = [];
  const evidenceCount = Number(investigation.evidence_count || 0);
  const gapCount = Number(investigation.gap_count || 0);
  const questionCount = array(investigation.patient_questions).length;
  if (evidenceCount) parts.push(`${evidenceCount} evidence records`);
  if (gapCount) parts.push(`${gapCount} open gaps`);
  if (questionCount) parts.push(`${questionCount} follow-up questions`);
  return parts.length ? parts.join(' · ') : 'New records and missing evidence will be tracked here.';
}

function actionButton(provider, action, label) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'secondary';
  button.dataset.provider = provider;
  button.dataset.providerAction = action;
  button.textContent = label;
  return button;
}

function verificationLabel(provider) {
  if (provider === 'paperclip') return 'Run fixed public check';
  if (provider === 'biohub-esm') return 'Run fixed synthetic ESM check';
  return 'Check Modal environment';
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

function setControlBusy(control, busy) {
  if (control instanceof HTMLFormElement) setFormBusy(control, busy);
  else if (control) control.disabled = busy;
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
