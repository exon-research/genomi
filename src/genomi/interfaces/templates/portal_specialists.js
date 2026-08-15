const SPECIALIST_TOOLS = new Set([
  'spawn_agent',
  'wait_agent',
  'list_agents',
  'interrupt_agent',
  'send_message',
  'followup_task'
]);

export function isSpecialistToolName(value) {
  const name = String(value || '').trim().toLowerCase();
  if (!name) return false;
  const leaf = name.split(/\.|__/).filter(Boolean).pop() || '';
  return SPECIALIST_TOOLS.has(leaf);
}

export function specialistLaneModel(records = []) {
  const collaboration = (Array.isArray(records) ? records : []).filter(isSpecialistRecord);
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
  header.innerHTML = '<div><span>Live collaboration</span><strong>Specialists</strong></div><em></em>';
  header.querySelector('em').textContent = model.parentWaiting
    ? 'Parent waiting'
    : model.parentStatus === 'completed'
      ? 'Parent wait completed'
      : model.parentStatus === 'error'
        ? 'Parent wait error'
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

function isSpecialistRecord(record) {
  const call = object(record && record.call);
  const result = object(record && record.result);
  return isSpecialistToolName(call.name || result.name);
}

function applySignals(values, specialists, byIdentity, fallback) {
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
    const agentId = clean(signal.agent_id || signal.agentId || signal.id);
    const taskName = clean(signal.task_name || signal.taskName);
    if (agentId) specialist.id = agentId;
    if (taskName) {
      specialist.taskName = taskName;
      specialist.title = humanTaskName(taskName);
    }
    const status = normalizedStatus(signal.status || signal.state || signal.result || signal.type);
    if (status) specialist.status = status;
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
  [specialist.id, specialist.taskName, specialist.key, specialist.title].forEach((value) => {
    const cleanValue = clean(value).toLowerCase();
    if (cleanValue) index.set(cleanValue, specialist);
    const leaf = cleanValue.split('/').filter(Boolean).pop();
    if (leaf) index.set(leaf, specialist);
  });
}

function specialistTitle(input) {
  const taskName = clean(input.task_name || input.taskName);
  if (taskName) return humanTaskName(taskName);
  const message = compact(input.message || input.objective, 72);
  return message || 'Research specialist';
}

function specialistSummary(input) {
  return compact(input.message || input.objective, 150) || 'Independent specialist task';
}

function humanTaskName(value) {
  const leaf = clean(value).split('/').filter(Boolean).pop() || clean(value);
  const text = leaf.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : 'Research specialist';
}

function normalizedStatus(value) {
  const text = clean(value).toLowerCase();
  if (!text) return '';
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
    counts.running ? counts.running + ' running' : '',
    counts.waiting ? counts.waiting + ' waiting' : '',
    counts.completed ? counts.completed + ' completed' : '',
    counts.error ? counts.error + ' error' + (counts.error === 1 ? '' : 's') : ''
  ].filter(Boolean).join(' · ') || 'Coordinating specialists';
}

function statusLabel(status) {
  return status === 'completed' ? 'Completed' : status === 'error' ? 'Error' : status === 'waiting' ? 'Waiting' : 'Running';
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
