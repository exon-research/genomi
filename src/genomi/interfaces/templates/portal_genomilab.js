export function createGenomiLabController({ api, getProjectId, getFrameId = () => '' }) {
  const byId = (id) => document.getElementById(id);

  function bind() {
    byId('refresh-genomilab-board')?.addEventListener('click', () => void loadBoard());
    document.querySelector('[data-genomilab-focus-prompt]')?.addEventListener('click', () => {
      byId('prompt')?.focus();
      byId('composer')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }

  async function loadAll() {
    await loadBoard();
  }

  async function loadBoard() {
    const projectId = getProjectId();
    const frameId = text(getFrameId());
    if (!projectId || !frameId) {
      renderBoard(null);
      return;
    }
    setStatus('genomilab-board-status', 'Loading the investigation workspace…');
    try {
      const payload = await api.loadGenomiLabBoard(projectId);
      if (text(getFrameId()) !== frameId) return;
      renderBoard(payload, frameId);
    } catch (error) {
      if (text(getFrameId()) !== frameId) return;
      renderBoard(null);
      setStatus('genomilab-board-status', error.message || 'The investigation workspace is unavailable.', 'error');
    }
  }

  async function refreshFromToolRecord(record) {
    if (!completedLabOperation(record)) return false;
    await loadBoard();
    return true;
  }

  function renderBoard(payload, frameId = text(getFrameId())) {
    const container = byId('genomilab-board-content');
    if (!container) return;
    container.replaceChildren();
    const investigation = investigationForFrame(payload, frameId);
    if (!investigation) {
      byId('genomilab-case-board').hidden = true;
      return;
    }
    byId('genomilab-case-board').hidden = false;
    const investigationStatus = investigationStatusModel(investigation);
    setStatus('genomilab-board-status', investigationStatus.label, investigationStatus.kind);
    const brief = doctorBriefModel(investigation);
    // An investigation that has only just started has nothing to show beyond
    // its question. Rendering the finished shape up front -- empty panels
    // promising explanations, workstreams and a brief -- presents an answer
    // before one exists, so each panel appears only once it holds real work.
    const cards = [
      boardCard('Question', text(investigation.question) || 'Investigation question recorded.'),
      roundBoardCard(investigation.cycles),
      hypothesisBoardCard(investigation.hypotheses),
      informationGapsCard(investigation.information_gaps),
      setupFaultsCard(investigation.information_gaps),
      evidenceBoardCard(investigation),
      doctorBriefCard(brief)
    ].filter(Boolean);
    container.append(...cards);
  }

  return Object.freeze({ bind, loadAll, loadBoard, refreshFromToolRecord });
}

export function investigationForFrame(payload, frameId) {
  const binding = payload && payload.binding && typeof payload.binding === 'object' ? payload.binding : null;
  return binding && text(binding.frame_id) === text(frameId)
    && payload && payload.investigation && typeof payload.investigation === 'object'
    ? payload.investigation
    : null;
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


function boardCard(titleText, value) {
  const article = document.createElement('article');
  const title = document.createElement('h4');
  title.textContent = titleText;
  const body = document.createElement('p');
  body.textContent = text(value) || 'No update yet.';
  article.append(title, body);
  return article;
}

export function hypothesisModels(values) {
  const labels = {
    strengthened: 'More supported',
    weakened: 'Less supported',
    rejected: 'Not supported by current evidence',
    retained: 'Still open',
    open: 'Still open',
    unresolved: 'Unresolved',
    proposed: 'Under review'
  };
  return array(values).filter((item) => item && typeof item === 'object').map((item) => {
    const status = text(item.status).toLowerCase() || 'proposed';
    return {
      statement: text(item.statement || item.title || item.summary),
      status,
      statusLabel: labels[status] || humanLabel(status),
      rationale: text(item.revision_rationale),
      gaps: array(item.unresolved_gaps).map((gap) => text(gap && (gap.question || gap.statement) ? (gap.question || gap.statement) : gap)).filter(Boolean)
    };
  }).filter((item) => item.statement);
}

export function informationGapModels(values) {
  const labels = {
    open: 'Open',
    resolved: 'Resolved',
    deferred: 'Deferred',
    closed: 'Closed'
  };
  return array(values).filter((item) => item && typeof item === 'object').map((item) => {
    const status = text(item.status).toLowerCase() || 'open';
    return {
      id: text(item.logical_information_gap_id || item.information_gap_version_id),
      statement: text(item.statement),
      status,
      statusLabel: labels[status] || humanLabel(status)
    };
  }).filter((item) => item.statement);
}

export function specialistWorkstreamModels(values) {
  const states = {
    proposed: 'Ready to start',
    spawned: 'Researching',
    completed: 'Findings added',
    failed: 'No findings',
    cancelled: 'Stopped'
  };
  return array(values).filter((item) => item && typeof item === 'object').map((item) => ({
    role: humanLabel(item.specialist_role || 'Research specialist'),
    status: states[text(item.state)] || 'Status pending',
    finding: text(item.finding),
    gaps: array(item.gaps).map(text).filter(Boolean)
  }));
}

export function investigationStatusModel(value) {
  const investigation = value && typeof value === 'object' ? value : null;
  if (investigation && investigation.current_brief) {
    return { label: 'Doctor brief ready', kind: 'success' };
  }
  const status = text(investigation ? investigation.status : value).toLowerCase();
  if (status === 'completed') return { label: 'Doctor brief ready', kind: 'success' };
  if (['running', 'active', 'in_progress'].includes(status)) {
    return { label: 'Research in progress', kind: 'active' };
  }
  if (['needs_input', 'blocked', 'waiting'].includes(status)) {
    return { label: 'Needs your input', kind: 'warning' };
  }
  if (['failed', 'error'].includes(status)) {
    return { label: 'Investigation needs attention', kind: 'error' };
  }
  if (status === 'cancelled') return { label: 'Investigation stopped', kind: 'muted' };
  if (status === 'approved') return { label: 'Investigation ready', kind: 'active' };
  if (['created', 'planning', ''].includes(status)) {
    return { label: 'Organizing your investigation', kind: 'active' };
  }
  return { label: humanLabel(status), kind: 'active' };
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
  const gapById = new Map();
  informationGapModels(investigation.information_gaps).forEach((item) => {
    if (item.id) gapById.set(item.id, item);
  });
  return {
    version: Number(versionRecord.version || investigation.current_brief_version || 0),
    title: text(brief.title) || 'Clinician discussion brief',
    question: text(investigation.question),
    summary: text(brief.summary),
    claims: array(brief.claims).filter((claim) => claim && typeof claim === 'object').map((claim) => ({
      statement: text(claim.statement),
      evidence: array(claim.evidence_record_ids).map((identifier) => evidenceAnchor(evidenceById.get(text(identifier)))).filter(Boolean),
      profileCount: array(claim.profile_revision_ids).filter(Boolean).length
    })).filter((claim) => claim.statement),
    hypotheses: array(brief.hypothesis_ids).map((identifier) => hypothesisById.get(text(identifier)))
      .filter(Boolean).map((item) => text(item.statement)).filter(Boolean),
    gaps: array(brief.gap_ids).map((identifier) => gapById.get(text(identifier)))
      .filter(Boolean).map((item) => item.statement),
    confirmationNeeds: array(brief.confirmation_needs).map(text).filter(Boolean),
    professionalQuestions: array(brief.professional_questions).map(text).filter(Boolean),
    clinicalBoundary: text(brief.clinical_boundary)
  };
}

function specialistWorkstreamsCard(values) {
  const card = boardCardShell('Research workstreams');
  const workstreams = specialistWorkstreamModels(values);
  if (!workstreams.length) return null;
  const list = document.createElement('ul');
  list.className = 'genomilab-board-list genomilab-workstreams';
  workstreams.forEach((workstream) => {
    const item = document.createElement('li');
    const role = document.createElement('b');
    role.textContent = workstream.role;
    const status = document.createElement('span');
    status.textContent = workstream.status;
    const heading = document.createElement('div');
    heading.className = 'genomilab-workstream-heading';
    heading.append(role, status);
    item.append(heading);
    if (workstream.finding) item.append(boardParagraph(workstream.finding));
    if (workstream.gaps.length) appendInlineList(item, 'Still needed', workstream.gaps);
    list.append(item);
  });
  card.append(list);
  return card;
}

export function currentRoundModel(values) {
  const cycles = array(values).filter((item) => item && typeof item === 'object');
  if (!cycles.length) return null;
  const current = cycles.reduce((latest, item) => (
    Number(item.ordinal || 0) >= Number(latest.ordinal || 0) ? item : latest
  ), cycles[0]);
  return {
    ordinal: Number(current.ordinal || cycles.length) || cycles.length,
    total: cycles.length,
    purpose: text(current.purpose)
  };
}

function roundBoardCard(values) {
  const round = currentRoundModel(values);
  if (!round) return null;
  // The investigation runs in rounds, each chasing a stated objective. Naming
  // the round the reader is in is what makes the board legible as work in
  // progress rather than a verdict.
  const card = boardCardShell('Round ' + round.ordinal);
  if (round.purpose) card.append(boardParagraph(round.purpose));
  return card;
}

function hypothesisBoardCard(values) {
  const hypotheses = hypothesisModels(values);
  if (!hypotheses.length) return null;
  // Say how many explanations are in play up front: holding several open at
  // once is the point of the investigation, not an implementation detail.
  const card = boardCardShell('Competing explanations (' + hypotheses.length + ')');
  const list = document.createElement('ol');
  list.className = 'genomilab-board-list genomilab-hypotheses';
  hypotheses.forEach((hypothesis) => {
    const item = document.createElement('li');
    const state = document.createElement('span');
    state.className = `genomilab-hypothesis-state ${hypothesis.status}`;
    state.textContent = hypothesis.statusLabel;
    const statement = document.createElement('p');
    statement.textContent = hypothesis.statement;
    item.append(state, statement);
    if (hypothesis.rationale) {
      const rationale = boardParagraph(hypothesis.rationale);
      rationale.className = 'genomilab-hypothesis-rationale';
      item.append(rationale);
    }
    if (hypothesis.gaps.length) appendInlineList(item, 'Waiting on', hypothesis.gaps);
    list.append(item);
  });
  card.append(list);
  return card;
}

// Two very different things end up recorded as gaps: facts about the person's
// case that nobody has yet, and Genomi failing to run something. Only the first
// is missing evidence -- the second is a setup problem the reader can actually
// act on, and showing them in one list makes a configuration fault look like an
// unknown about the person's health.
const SETUP_FAULT_MARKERS = [
  'credential',
  'api key',
  'unreachable',
  'not installed',
  'not configured',
  'variants_ready',
  'candidate inventory',
  'active genome index',
  'source families',
  'provider was unavailable',
  'provider was unreachable'
];

export function isSetupFaultGap(statement) {
  const value = String(statement || '').toLowerCase();
  return SETUP_FAULT_MARKERS.some((marker) => value.includes(marker));
}

function gapListCard(titleText, gaps, note) {
  if (!gaps.length) return null;
  const card = boardCardShell(titleText);
  if (note) card.append(boardParagraph(note));
  const list = document.createElement('ul');
  list.className = 'genomilab-board-list genomilab-information-gaps';
  gaps.forEach((gap) => {
    const item = document.createElement('li');
    const state = document.createElement('span');
    state.className = `genomilab-gap-state ${gap.status}`;
    state.textContent = gap.statusLabel;
    const statement = document.createElement('p');
    statement.textContent = gap.statement;
    item.append(state, statement);
    list.append(item);
  });
  card.append(list);
  return card;
}

function informationGapsCard(values) {
  const gaps = informationGapModels(values).filter((gap) => !isSetupFaultGap(gap.statement));
  return gapListCard('What is still missing', gaps);
}

function setupFaultsCard(values) {
  const gaps = informationGapModels(values).filter((gap) => isSetupFaultGap(gap.statement));
  return gapListCard(
    'Genomi could not finish these',
    gaps,
    'Problems with this setup, not findings about you.'
  );
}

function evidenceBoardCard(investigation) {
  const summary = boardEvidenceSummary(investigation);
  if (!summary) return null;
  const card = boardCardShell('Evidence & research');
  card.append(boardParagraph(summary));
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
  if (!model) return null;
  const heading = document.createElement('div');
  heading.className = 'genomilab-brief-heading';
  const title = document.createElement('h5');
  title.textContent = model.title;
  const headingActions = document.createElement('div');
  headingActions.className = 'genomilab-brief-actions';
  if (model.version) {
    const version = document.createElement('span');
    version.textContent = `Version ${model.version}`;
    headingActions.append(version);
  }
  const download = document.createElement('button');
  download.type = 'button';
  download.className = 'secondary genomilab-brief-download';
  download.textContent = 'Download brief';
  download.addEventListener('click', () => downloadDoctorBrief(model));
  headingActions.append(download);
  heading.append(title, headingActions);
  card.append(heading);
  if (model.question) appendBriefList(card, 'Question investigated', [model.question]);
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
      profile.textContent = `${claim.profileCount} ${claim.profileCount === 1 ? 'detail' : 'details'} from your health history`;
      anchors.append(profile);
    }
    if (anchors.childNodes.length) item.append(anchors);
    list.append(item);
  });
  section.append(list);
}

function appendInlineList(parent, titleText, values) {
  const label = document.createElement('b');
  label.className = 'genomilab-inline-label';
  label.textContent = `${titleText}: `;
  const detail = document.createElement('span');
  detail.className = 'genomilab-inline-value';
  detail.textContent = values.join(' · ');
  const line = document.createElement('p');
  line.append(label, detail);
  parent.append(line);
}

export function doctorBriefMarkdown(model) {
  if (!model) return '';
  const lines = [`# ${model.title}`];
  if (model.version) lines.push('', `Version ${model.version}`);
  appendMarkdownSection(lines, 'Question investigated', model.question ? [model.question] : []);
  if (model.summary) lines.push('', '## Summary', '', model.summary);
  appendMarkdownSection(lines, 'Key findings', model.claims.map((claim) => {
    const sources = claim.evidence.map((anchor) => anchor.url ? `[${anchor.label}](${anchor.url})` : anchor.label);
    const support = [sources.length ? `Sources: ${sources.join('; ')}` : '', claim.profileCount ? `Health-history details: ${claim.profileCount}` : '']
      .filter(Boolean).join(' — ');
    return support ? `${claim.statement} (${support})` : claim.statement;
  }));
  appendMarkdownSection(lines, 'Competing explanations', model.hypotheses);
  appendMarkdownSection(lines, 'What is still missing', model.gaps);
  appendMarkdownSection(lines, 'Confirmation needed', model.confirmationNeeds);
  appendMarkdownSection(lines, 'Questions for your clinician', model.professionalQuestions);
  if (model.clinicalBoundary) lines.push('', '## Clinical boundary', '', model.clinicalBoundary);
  return `${lines.join('\n').trim()}\n`;
}

function appendMarkdownSection(lines, titleText, values) {
  if (!values.length) return;
  lines.push('', `## ${titleText}`, '', ...values.map((value) => `- ${value}`));
}

function downloadDoctorBrief(model) {
  const markdown = doctorBriefMarkdown(model);
  if (!markdown || typeof Blob === 'undefined' || typeof URL === 'undefined') return;
  const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `genomi-doctor-brief-v${model.version || 1}.md`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
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
  if (evidenceCount) parts.push(`${evidenceCount} source ${evidenceCount === 1 ? 'record' : 'records'}`);
  if (artifactCount) parts.push(`${artifactCount} research ${artifactCount === 1 ? 'output' : 'outputs'}`);
  if (gapCount) parts.push(`${gapCount} open gaps`);
  if (questionCount) parts.push(`${questionCount} follow-up questions`);
  return parts.length ? parts.join(' · ') : '';
}

function setStatus(id, message, kind = '') {
  const node = document.getElementById(id);
  if (!node) return;
  node.textContent = message || '';
  node.className = 'genomilab-status' + (kind ? ' ' + kind : '');
}

function text(value) {
  return value === null || value === undefined ? '' : String(value).trim();
}

function array(value) {
  return Array.isArray(value) ? value : [];
}
