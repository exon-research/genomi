const SPECIALIST_TOOLS = new Set([
  'spawn_agent',
  'wait_agent',
  'list_agents',
  'interrupt_agent',
  'send_message',
  'followup_task',
  'specialist_progress'
]);
const LAB_ASSIGNMENT_OPERATIONS = new Set([
  'lab.create_specialist_assignment',
  'lab.transition_specialist_assignment'
]);
const LAB_ASSIGNMENT_STATES = new Set([
  'proposed',
  'spawned',
  'completed',
  'failed',
  'cancelled'
]);

export function isSpecialistToolName(value) {
  const name = String(value || '').trim().toLowerCase();
  if (!name) return false;
  const leaf = name.split(/\.|__/).filter(Boolean).pop() || '';
  return SPECIALIST_TOOLS.has(leaf);
}

export function specialistLaneModel(records = []) {
  const allRecords = Array.isArray(records) ? records : [];
  const collaboration = allRecords.filter(isCollaborationRecord);
  const specialists = [];
  const byIdentity = new Map();
  let parentWaiting = false;
  let parentStatus = '';

  collaboration.forEach((record, index) => {
    const call = object(record && record.call);
    const result = object(record && record.result);
    const operation = toolLeaf(call.name || result.name);
    if (operation !== 'spawn_agent') return;
    const input = object(call.input);
    const specialist = {
      key: clean(call.id) || 'specialist-' + String(index + 1),
      id: '',
      assignmentId: clean(input.assignment_id || input.specialist_assignment_id),
      taskName: clean(input.task_name || input.taskName),
      title: specialistTitle(input),
      summary: specialistSummary(input),
      status: result.isError ? 'error' : record.result ? 'waiting' : 'running'
    };
    specialists.push(specialist);
    registerIdentities(byIdentity, specialist);
    applySignals([result], specialists, byIdentity, specialist);
    // A successful spawn response confirms that the specialist was launched;
    // it does not mean the delegated task is complete. Keep that state visibly
    // waiting unless the response carries an explicit lifecycle status.
    if (record.result && !result.isError && !hasStructuredStatus(result)) {
      specialist.status = 'waiting';
    }
  });

  collaboration.forEach((record) => {
    const call = object(record && record.call);
    const result = object(record && record.result);
    const operation = toolLeaf(call.name || result.name);
    if (operation === 'spawn_agent') return;
    if (operation === 'specialist_progress') return;
    if (operation === 'wait_agent') {
      parentWaiting = !record.result;
      parentStatus = record.result ? (result.isError ? 'error' : 'completed') : 'waiting';
    }
    if (!record.result) return;
    applySignals([result], specialists, byIdentity, null);
    if (operation === 'interrupt_agent') {
      const target = clean(object(call.input).target);
      const specialist = findSpecialist(specialists, byIdentity, target);
      if (specialist && !result.isError) specialist.status = 'error';
    }
  });

  // Lab assignment results are the authoritative lifecycle. Collaboration
  // events describe live host activity; only a successful canonical Lab
  // result proves that an isolated assignment reached a durable state.
  allRecords.forEach((record) => {
    const update = labAssignmentUpdate(record);
    if (!update) return;
    let assignmentSpecialist = findSpecialist(specialists, byIdentity, update.assignmentId);
    const nativeSpecialist = findSpecialist(specialists, byIdentity, update.nativeAgentId);
    if (assignmentSpecialist && nativeSpecialist && assignmentSpecialist !== nativeSpecialist) {
      mergeSpecialists(nativeSpecialist, assignmentSpecialist, specialists);
      assignmentSpecialist = nativeSpecialist;
    }
    const specialist = assignmentSpecialist || nativeSpecialist || {
      key: update.assignmentId,
      id: update.nativeAgentId,
      taskName: '',
      title: update.title,
      summary: update.summary,
      status: update.status
    };
    if (!specialists.includes(specialist)) specialists.push(specialist);
    if (specialist.assignmentRevision && update.revision && update.revision < specialist.assignmentRevision) return;
    specialist.assignmentId = update.assignmentId;
    specialist.assignmentRevision = update.revision;
    specialist.id = update.nativeAgentId || specialist.id;
    specialist.title = update.title || specialist.title;
    specialist.summary = update.summary || specialist.summary;
    specialist.status = update.status;
    specialist.policy = update.policy;
    specialist.authoritative = true;
    registerIdentities(byIdentity, specialist);
  });

  // Child MCP output remains isolated from Main, but the protocol adapter emits
  // a redacted lifecycle signal when an authorized provider operation starts.
  // Apply that signal after the durable spawned assignment so its useful status
  // text is visible, while never reviving a terminal specialist.
  collaboration.forEach((record) => {
    const call = object(record && record.call);
    const result = object(record && record.result);
    if (toolLeaf(call.name || result.name) !== 'specialist_progress' || !record.result) return;
    applySignals([result], specialists, byIdentity, null, true);
  });

  // A host turn is a hard runtime boundary. If it ends without a canonical
  // completed/failed/cancelled transition, surface the assignment as an error
  // instead of presenting stale spawned state as live work.
  if (allRecords.some((record) => clean(record && record.runTerminalStatus))) {
    specialists.forEach((specialist) => {
      if (!['running', 'waiting'].includes(specialist.status)) return;
      specialist.status = 'error';
      specialist.summary = 'This research workstream stopped before findings were saved.';
    });
  }

  const counts = countStatuses(specialists);
  return {
    visible: specialists.length > 0,
    parentWaiting,
    parentStatus,
    status: counts.error ? 'error' : counts.running || counts.waiting ? 'running' : 'completed',
    summary: specialistSummaryText(counts),
    specialists
  };
}

export function renderSpecialistLane(stack, records = []) {
  if (!stack || typeof stack.querySelector !== 'function') return null;
  const model = specialistLaneModel(records);
  let lane = stack.querySelector('.specialist-lane');
  if (!model.visible) {
    if (lane && typeof lane.remove === 'function') lane.remove();
    return null;
  }
  if (!lane) {
    lane = document.createElement('section');
    lane.className = 'specialist-lane';
    lane.setAttribute('data-testid', 'specialist-lane');
    const items = stack.querySelector('.tool-stack-items');
    if (items && typeof stack.insertBefore === 'function') stack.insertBefore(lane, items);
    else stack.appendChild(lane);
  }
  lane.dataset.status = model.status;
  lane.dataset.summary = model.summary;
  lane.innerHTML = '';

  const header = document.createElement('div');
  header.className = 'specialist-lane-head';
  header.innerHTML = '<div><span>Investigation team</span><strong>Research workstreams</strong></div><em></em>';
  header.querySelector('em').textContent = model.parentWaiting
    ? 'Coordinating research'
    : model.parentStatus === 'completed'
      ? 'Research coordination complete'
      : model.parentStatus === 'error'
        ? 'Research coordination needs attention'
        : model.summary;
  if (model.parentStatus) header.querySelector('em').className = model.parentStatus;
  lane.appendChild(header);

  const grid = document.createElement('div');
  grid.className = 'specialist-lane-grid';
  model.specialists.forEach((specialist) => {
    const card = document.createElement('article');
    card.className = 'specialist-card ' + specialist.status;
    card.dataset.specialistId = specialist.id || specialist.key;
    card.innerHTML = '<span class="specialist-state"></span><div><strong></strong><p></p></div>';
    card.querySelector('.specialist-state').textContent = statusLabel(specialist.status);
    card.querySelector('strong').textContent = specialist.title;
    card.querySelector('p').textContent = specialist.summary;
    grid.appendChild(card);
  });
  lane.appendChild(grid);
  return model;
}

function isCollaborationRecord(record) {
  const call = object(record && record.call);
  const result = object(record && record.result);
  return isSpecialistToolName(call.name || result.name);
}

function labAssignmentUpdate(record) {
  const call = object(record && record.call);
  const result = object(record && record.result);
  if (!record || !record.result || result.isError) return null;
  const payload = findKnownResultObject(result.payload);
  const input = object(call.input);
  const operation = clean(payload.dispatched_tool || input.tool || call.name || result.name);
  if (!LAB_ASSIGNMENT_OPERATIONS.has(operation)) return null;
  const assignment = object(payload.assignment);
  const assignmentId = clean(assignment.specialist_assignment_id);
  const state = clean(assignment.state).toLowerCase();
  if (!assignmentId || !LAB_ASSIGNMENT_STATES.has(state)) return null;
  const policy = clean(assignment.execution_policy);
  const finding = completedFinding(payload.specialist_analysis);
  return {
    assignmentId,
    nativeAgentId: clean(assignment.native_agent_id),
    title: humanTaskName(assignment.specialist_role) || 'Research workstream',
    policy,
    revision: Number(assignment.revision) || 0,
    status: labDisplayStatus(state),
    summary: finding || policySummary(policy)
  };
}

function findKnownResultObject(value, depth = 0) {
  if (depth > 4) return {};
  const parsed = parsedValue(value);
  if (Array.isArray(parsed)) {
    for (const item of parsed) {
      const found = findKnownResultObject(item, depth + 1);
      if (found.assignment || found.dispatched_tool) return found;
    }
    return {};
  }
  const source = object(parsed);
  if (source.assignment || source.dispatched_tool) return source;
  for (const key of ['structuredContent', 'structured_content', 'result', 'payload', 'content']) {
    if (source[key] === undefined) continue;
    const found = findKnownResultObject(source[key], depth + 1);
    if (found.assignment || found.dispatched_tool) return found;
  }
  if (typeof source.text === 'string') return findKnownResultObject(source.text, depth + 1);
  return {};
}

function completedFinding(value) {
  const analysis = object(value);
  const decoded = parsedValue(analysis.general_analysis_json);
  if (typeof decoded === 'string') return compact(decoded, 180);
  const general = object(decoded).general_analysis;
  if (typeof general === 'string') return compact(general, 180);
  if (typeof analysis.general_analysis === 'string') return compact(analysis.general_analysis, 180);
  return '';
}

function labDisplayStatus(state) {
  if (state === 'completed') return 'completed';
  if (state === 'spawned') return 'running';
  if (state === 'proposed') return 'waiting';
  return 'error';
}

function policySummary(policy) {
  return {
    reasoning_only: 'Focused analysis in progress',
    public_literature: 'Reviewing public biomedical literature',
    protein_model_research: 'Comparing protein-model evidence',
    experiment_design: 'Developing an experiment plan'
  }[policy] || 'Focused research workstream';
}

function mergeSpecialists(target, source, specialists) {
  if (!target || !source || target === source) return target;
  target.assignmentId = source.assignmentId || target.assignmentId;
  target.assignmentRevision = source.assignmentRevision || target.assignmentRevision;
  target.policy = source.policy || target.policy;
  target.authoritative = source.authoritative || target.authoritative;
  const index = specialists.indexOf(source);
  if (index >= 0) specialists.splice(index, 1);
  return target;
}

function applySignals(values, specialists, byIdentity, fallback, preserveTerminal = false) {
  const signals = signalObjects(values);
  let applied = false;
  signals.forEach((signal) => {
    const identities = signalIdentities(signal);
    let specialist = identities.map((value) => findSpecialist(specialists, byIdentity, value)).find(Boolean);
    if (!specialist && fallback) specialist = fallback;
    if (!specialist && specialists.length === 1) specialist = specialists[0];
    if (!specialist && (signal.task_name || signal.taskName || signal.agent_id || signal.agentId)) {
      const input = {
        task_name: signal.task_name || signal.taskName,
        message: signal.message || signal.summary || signal.objective
      };
      specialist = {
        key: clean(signal.agent_id || signal.agentId || signal.task_name || signal.taskName) || 'specialist-' + String(specialists.length + 1),
        id: clean(signal.agent_id || signal.agentId),
        taskName: clean(signal.task_name || signal.taskName),
        title: specialistTitle(input),
        summary: specialistSummary(input),
        status: 'running'
      };
      specialists.push(specialist);
    }
    if (!specialist) return;
    if (preserveTerminal && ['completed', 'error'].includes(specialist.status)) {
      applied = true;
      return;
    }
    const agentId = clean(signal.agent_id || signal.agentId || signal.id);
    const taskName = clean(signal.task_name || signal.taskName);
    if (agentId) specialist.id = agentId;
    if (taskName) {
      specialist.taskName = taskName;
      specialist.title = humanTaskName(taskName);
    }
    const status = normalizedStatus(signal.status || signal.state || signal.result || signal.type);
    if (status) specialist.status = status;
    const summary = compact(signal.message || signal.summary, 150);
    if (summary) specialist.summary = summary;
    registerIdentities(byIdentity, specialist);
    applied = true;
  });
  if (!applied) applyTextSignal(values, specialists, fallback);
}

function signalObjects(values) {
  const output = [];
  const seen = new Set();
  function visit(value) {
    const parsed = parsedValue(value);
    if (parsed !== value) {
      visit(parsed);
      return;
    }
    if (!parsed || typeof parsed !== 'object' || seen.has(parsed)) return;
    seen.add(parsed);
    if (!Array.isArray(parsed)) {
      const hasIdentity = signalIdentities(parsed).length > 0;
      const hasStatus = Boolean(normalizedStatus(parsed.status || parsed.state || parsed.result || parsed.type));
      if (hasIdentity || hasStatus) output.push(parsed);
      Object.values(parsed).forEach(visit);
      return;
    }
    parsed.forEach(visit);
  }
  values.forEach(visit);
  return output;
}

function hasStructuredStatus(value) {
  return signalObjects([value]).some((signal) => {
    return Boolean(normalizedStatus(signal.status || signal.state || signal.result || signal.type));
  });
}

function applyTextSignal(values, specialists, fallback) {
  const text = flattenedText(values).toLowerCase();
  if (!text) return;
  const status = normalizedStatus(text);
  if (!status) return;
  const matched = specialists.filter((specialist) => {
    return [specialist.id, specialist.taskName, specialist.title]
      .map((value) => clean(value).toLowerCase())
      .filter(Boolean)
      .some((value) => text.includes(value));
  });
  const targets = matched.length ? matched : (fallback ? [fallback] : specialists.length === 1 ? specialists : []);
  targets.forEach((specialist) => { specialist.status = status; });
}

function flattenedText(values) {
  const parts = [];
  function visit(value) {
    const parsed = parsedValue(value);
    if (parsed !== value) {
      visit(parsed);
    } else if (typeof parsed === 'string') {
      parts.push(parsed);
    } else if (Array.isArray(parsed)) {
      parsed.forEach(visit);
    } else if (parsed && typeof parsed === 'object') {
      Object.values(parsed).forEach(visit);
    }
  }
  values.forEach(visit);
  return parts.join(' ');
}

function parsedValue(value) {
  if (typeof value !== 'string') return value;
  const text = value.trim();
  if (!text || !['{', '['].includes(text[0])) return value;
  try { return JSON.parse(text); } catch { return value; }
}

function signalIdentities(signal) {
  return [
    signal.agent_id,
    signal.agentId,
    signal.assignment_id,
    signal.specialist_assignment_id,
    signal.task_name,
    signal.taskName,
    signal.target,
    signal.name
  ].map(clean).filter(Boolean);
}

function findSpecialist(specialists, byIdentity, value) {
  const identity = clean(value).toLowerCase();
  if (!identity) return null;
  if (byIdentity.has(identity)) return byIdentity.get(identity);
  return specialists.find((specialist) => {
    return [specialist.id, specialist.taskName, specialist.key, specialist.title]
      .map((item) => clean(item).toLowerCase())
      .some((item) => item && (item === identity || item.endsWith('/' + identity)));
  }) || null;
}

function registerIdentities(index, specialist) {
  [specialist.id, specialist.assignmentId, specialist.taskName, specialist.key, specialist.title].forEach((value) => {
    const cleanValue = clean(value).toLowerCase();
    if (cleanValue) index.set(cleanValue, specialist);
    const leaf = cleanValue.split('/').filter(Boolean).pop();
    if (leaf) index.set(leaf, specialist);
  });
}

function specialistTitle(input) {
  const specialistRole = clean(input.specialist_role || input.specialistRole);
  if (specialistRole) return humanTaskName(specialistRole);
  const taskName = clean(input.task_name || input.taskName);
  if (taskName) return humanTaskName(taskName);
  const message = compact(input.message || input.objective, 72);
  return message || 'Research workstream';
}

function specialistSummary(input) {
  return compact(input.message || input.objective, 150) || 'Focused research in progress';
}

function humanTaskName(value) {
  const leaf = clean(value).split('/').filter(Boolean).pop() || clean(value);
  const text = leaf.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : 'Research workstream';
}

function normalizedStatus(value) {
  const text = clean(value).toLowerCase();
  if (!text) return '';
  if (['pendinginit', 'pending_init'].includes(text)) return 'waiting';
  if (['inprogress', 'in_progress'].includes(text)) return 'running';
  if (['errored', 'notfound', 'not_found'].includes(text)) return 'error';
  if (text === 'shutdown') return 'completed';
  if (/\b(error|failed|failure|blocked|cancelled|canceled|interrupted)\b/.test(text)) return 'error';
  if (/\b(completed|complete|succeeded|finished|done|final_answer)\b/.test(text)) return 'completed';
  if (/\b(waiting|idle|pending)\b/.test(text)) return 'waiting';
  if (/\b(running|working|in_progress|active|started|spawned)\b/.test(text)) return 'running';
  return '';
}

function countStatuses(specialists) {
  return specialists.reduce((counts, specialist) => {
    counts[specialist.status] = (counts[specialist.status] || 0) + 1;
    return counts;
  }, { running: 0, waiting: 0, completed: 0, error: 0 });
}

function specialistSummaryText(counts) {
  return [
    counts.running ? counts.running + ' in progress' : '',
    counts.waiting ? counts.waiting + ' ready' : '',
    counts.completed ? counts.completed + ' findings added' : '',
    counts.error ? counts.error + ' need' + (counts.error === 1 ? 's' : '') + ' attention' : ''
  ].filter(Boolean).join(' · ') || 'Coordinating research';
}

function statusLabel(status) {
  return status === 'completed' ? 'Findings added' : status === 'error' ? 'Needs attention' : status === 'waiting' ? 'Ready' : 'Researching';
}

function toolLeaf(value) {
  return clean(value).toLowerCase().split(/\.|__/).filter(Boolean).pop() || '';
}

function compact(value, limit) {
  const text = clean(value).replace(/\s+/g, ' ');
  if (text.length <= limit) return text;
  return text.slice(0, Math.max(1, limit - 1)).trimEnd() + '…';
}

function clean(value) {
  return String(value || '').trim();
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}
