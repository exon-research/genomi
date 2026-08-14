import {
  frameTraceMessagesFromToolRecord,
  frameTraceRecordKey,
  renderFrameWorkTrace
} from './portal_frame_trace.js';

export function createWorkTraceController(options = {}) {
  const state = {
    frameId: null,
    messages: [],
    executionCells: [],
    liveToolRecords: [],
    liveMessageFrameId: null,
    highlightStepId: '',
    loadSerial: 0
  };
  const renderWorkTrace = typeof options.renderWorkTrace === 'function'
    ? options.renderWorkTrace
    : renderFrameWorkTrace;
  const api = options.api || {};

  function container() {
    return typeof options.container === 'function' ? options.container() : options.container;
  }

  function renderOptions() {
    const actionOptions = typeof options.actionOptions === 'function' ? options.actionOptions() : {};
    return {
      ...actionOptions,
      highlightStepId: state.highlightStepId,
      executionCells: state.executionCells
    };
  }

  function render() {
    const liveMessages = state.liveToolRecords.flatMap(frameTraceMessagesFromToolRecord);
    renderWorkTrace(container(), [...state.messages, ...liveMessages], renderOptions());
    notifyStateChange();
  }

  function reset(next = {}) {
    state.frameId = next.frameId || null;
    state.messages = [];
    state.executionCells = [];
    state.liveToolRecords = [];
    state.liveMessageFrameId = null;
    state.highlightStepId = '';
    state.loadSerial += 1;
    render();
  }

  async function setFrameMessages(frameId, payload, options = {}) {
    if (!payload || payload.frame_id !== frameId) return false;
    const loadSerial = state.loadSerial + 1;
    state.loadSerial = loadSerial;
    state.frameId = frameId;
    state.messages = Array.isArray(payload.messages) ? payload.messages : [];
    state.executionCells = [];
    state.liveToolRecords = [];
    state.highlightStepId = cleanText(options.highlightStepId);
    render();
    await loadExecutionCells(frameId, state.messages, loadSerial);
    return true;
  }

  function beginLiveRun(frameId) {
    const cleanFrameId = frameId || null;
    if (cleanFrameId) state.frameId = cleanFrameId;
    state.liveMessageFrameId = cleanFrameId;
  }

  function trackLiveToolRecord(record, activeRun) {
    if (!shouldTrackLiveToolRecord(record, activeRun)) return false;
    const key = frameTraceRecordKey(record);
    state.liveToolRecords = [
      ...state.liveToolRecords.filter((item) => frameTraceRecordKey(item) !== key),
      record
    ].slice(-24);
    render();
    return true;
  }

  function hasWork() {
    return hasWorkTrace();
  }

  function hasWorkTrace() {
    const liveMessages = state.liveToolRecords.flatMap(frameTraceMessagesFromToolRecord);
    return frameTraceMessagesHaveWork([...state.messages, ...liveMessages])
      || state.executionCells.length > 0;
  }

  function notifyStateChange() {
    if (typeof options.onStateChange === 'function') {
      options.onStateChange({ hasWork: hasWorkTrace() });
    }
  }

  function shouldTrackLiveToolRecord(record, activeRun) {
    const scope = (record && record.scope) || {};
    return Boolean(
      activeRun &&
      activeRun.runId &&
      state.liveMessageFrameId === state.frameId &&
      scope.frameId === state.frameId &&
      scope.runId === activeRun.runId
    );
  }

  async function loadExecutionCells(frameId, messages, loadSerial) {
    const runIds = runIdsFromMessages(messages);
    if (!runIds.length) {
      if (state.frameId === frameId && state.loadSerial === loadSerial) {
        state.executionCells = [];
        render();
      }
      return;
    }
    const packages = await Promise.allSettled(runIds.map((runId) => loadRunResultPackage(runId)));
    if (state.frameId !== frameId || state.loadSerial !== loadSerial) return;
    state.executionCells = executionCellsFromRunPackages(packages, runIds);
    render();
  }

  async function loadRunResultPackage(runId) {
    if (typeof api.loadRunResultPackage !== 'function') return {};
    return api.loadRunResultPackage(runId);
  }

  return {
    beginLiveRun,
    hasWork,
    render,
    reset,
    setFrameMessages,
    trackLiveToolRecord
  };
}

function cleanText(value) {
  return String(value || '').trim();
}

function frameTraceMessagesHaveWork(messages) {
  return (Array.isArray(messages) ? messages : []).some((message) => {
    const event = message && message.event;
    return event && ['tool_call', 'tool_result', 'error'].includes(String(event.type || ''));
  });
}

export function runIdsFromMessages(messages) {
  const seen = new Set();
  const ids = [];
  (Array.isArray(messages) ? messages : []).forEach((message) => {
    const runId = String((message && message.run_id) || '').trim();
    if (!runId || seen.has(runId)) return;
    seen.add(runId);
    ids.push(runId);
  });
  return ids.slice(-8);
}

export function executionCellsFromRunPackages(packages, runIds = []) {
  return (Array.isArray(packages) ? packages : []).flatMap((result, index) => {
    if (!result || result.status !== 'fulfilled') return [];
    const payload = result.value || {};
    const cells = payload.execution_cells || {};
    const runId = cells.run_id || runIds[index] || '';
    return (Array.isArray(cells.items) ? cells.items : []).map((cell) => ({
      ...cell,
      run_id: cell.run_id || runId
    }));
  });
}
