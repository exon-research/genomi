const ASSISTANT_RADIO_NAME = 'workspace-assistant';

export function assistantReason(source) {
  if (source === 'workspace_choice') return 'chosen for this workspace';
  if (source === 'launch_option') return 'named with --agent when GenomiLab started';
  if (source === 'bootstrap_host_agent') return 'the assistant that started GenomiLab';
  if (source === 'only_runnable') return 'the only assistant installed here';
  if (source === 'only_one_working_here') return 'the only installed assistant that has not failed in this workspace';
  return '';
}

export function assistantWorkingLabel(assistant) {
  const label = assistant && assistant.active_label ? String(assistant.active_label).trim() : '';
  return label ? label + ' is working…' : 'Your assistant is working…';
}

export function applyAssistantWorkingLabel(assistant, root) {
  const target = root || (typeof document !== 'undefined' ? document.documentElement : null);
  if (!target || !target.style) return '';
  const label = assistantWorkingLabel(assistant);
  target.style.setProperty('--assistant-working-label', JSON.stringify(label));
  return label;
}

export function assistantSummaryLabel(assistant, agents) {
  const state = assistant && assistant.state ? String(assistant.state) : '';
  const label = assistant && assistant.active_label ? String(assistant.active_label) : '';
  if (state === 'ready' && label) {
    const reason = assistantReason(assistant.source);
    return reason ? 'Using ' + label + ' - ' + reason : 'Using ' + label;
  }
  if (state === 'choice_required') return 'Choose which local assistant this workspace uses';
  if (state === 'workspace_choice_unavailable') {
    const missing = assistant && assistant.unavailable_label ? String(assistant.unavailable_label) : 'This workspace assistant';
    return missing + ' is not available here - choose another below';
  }
  const detected = (Array.isArray(agents) ? agents : []).filter((agent) => agent && agent.available);
  if (detected.length) return detected.length + ' local assistant setup' + (detected.length === 1 ? '' : 's') + ' found';
  return 'No local assistant available';
}

export function assistantOptionModel(agent, assistant = {}) {
  const id = String((agent && agent.id) || '');
  const active = Boolean(id) && id === String(assistant.active_agent_id || '');
  const reason = active ? assistantReason(assistant.source) : '';
  return {
    id,
    label: String((agent && agent.label) || id || 'Assistant'),
    runnable: Boolean(agent && agent.runnable),
    checked: active,
    state: installStateLabel(agent),
    note: [reason ? 'In use: ' + reason + '.' : '', optionNote(agent)].filter(Boolean).join(' ')
  };
}

export function renderAssistantChoice(target, payload, { onSelect } = {}) {
  if (!target) return;
  const agents = Array.isArray(payload && payload.agents) ? payload.agents : [];
  const assistant = (payload && payload.assistant) || {};
  target.replaceChildren();
  if (!agents.length) {
    const empty = document.createElement('div');
    empty.className = 'runtime-empty';
    empty.textContent = 'No local assistant available.';
    target.appendChild(empty);
    return;
  }
  const fieldset = document.createElement('fieldset');
  fieldset.className = 'runtime-choice';
  const legend = document.createElement('legend');
  legend.textContent = assistant.state === 'choice_required'
    ? 'Choose the assistant for this workspace'
    : 'Assistant for this workspace';
  fieldset.appendChild(legend);
  agents.forEach((agent) => {
    fieldset.appendChild(assistantOptionElement(assistantOptionModel(agent, assistant), onSelect));
  });
  target.appendChild(fieldset);
}

function assistantOptionElement(option, onSelect) {
  const row = document.createElement('label');
  row.className = 'runtime-item';
  row.setAttribute('data-runtime-state', option.runnable ? 'runnable' : 'unavailable');
  row.setAttribute('data-testid', 'genomi-assistant-option-' + option.id);
  const input = document.createElement('input');
  input.type = 'radio';
  input.name = ASSISTANT_RADIO_NAME;
  input.value = option.id;
  input.checked = option.checked;
  if (option.checked) input.setAttribute('checked', 'checked');
  if (!option.runnable) {
    input.disabled = true;
    input.setAttribute('disabled', 'disabled');
  }
  input.addEventListener('change', () => {
    if (option.runnable && typeof onSelect === 'function') onSelect(option.id);
  });
  const name = document.createElement('strong');
  name.textContent = option.label;
  const state = document.createElement('span');
  state.className = 'runtime-state';
  state.textContent = option.state;
  row.append(input, name, state);
  if (option.note) {
    const note = document.createElement('span');
    note.className = 'runtime-note';
    note.textContent = option.note;
    row.appendChild(note);
  }
  return row;
}

function installStateLabel(agent) {
  if (agent && agent.runnable) return 'Installed';
  if (agent && agent.available) return 'Not supported yet';
  return 'Not installed';
}

function optionNote(agent) {
  if (agent && agent.runnable) return lastRunFailureNote(agent.last_run_failure);
  if (agent && agent.available) return 'Genomi has no verified driver for this assistant yet.';
  return 'Genomi did not find this assistant on this machine.';
}

function lastRunFailureNote(reason) {
  if (reason === 'assistant_usage_limit_reached') return 'Last turn here stopped: usage allowance reached.';
  if (reason === 'assistant_unavailable') return 'Last turn here stopped: Genomi could not start it.';
  if (reason === 'assistant_timed_out') return 'Last turn here stopped: it stopped responding.';
  if (reason === 'assistant_stopped_unexpectedly') return 'Last turn here stopped before answering.';
  return '';
}
