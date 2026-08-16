export function createGenomiLabController({ api, getProjectId }) {
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

  async function refreshFromToolRecord(record) {
    if (!completedLabOperation(record)) return false;
    await loadBoard();
    return true;
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

  return Object.freeze({ bind, loadAll, loadBoard, refreshFromToolRecord });
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
