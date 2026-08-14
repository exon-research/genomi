export function watchRun(runId, handlers = {}, options = {}) {
  if (!runId) {
    if (handlers.onMissingRun) handlers.onMissingRun();
    return { close() {} };
  }
  if (typeof EventSource === 'undefined') {
    if (handlers.onInterrupt) handlers.onInterrupt({ reason: 'event_source_unavailable' });
    return { close() {} };
  }
  const maxReconnectAttempts = Number.isFinite(options.maxReconnectAttempts) ? options.maxReconnectAttempts : 6;
  const reconnectDelayMs = Number.isFinite(options.reconnectDelayMs) ? options.reconnectDelayMs : 500;
  let source = null;
  let closed = false;
  let finished = false;
  let recovering = false;
  let reconnectAttempts = 0;
  let lastEventId = 0;

  openSource();

  function openSource() {
    if (closed || finished) return;
    source = new EventSource(runEventUrl(runId, lastEventId));
    source.addEventListener('artifact', eventHandler('artifact'));
    source.addEventListener('artifact_error', eventHandler('artifact_error'));
    source.addEventListener('review', eventHandler('review'));
    source.addEventListener('agent', eventHandler('agent'));
    source.addEventListener('stdout', eventHandler('stdout'));
    source.addEventListener('stderr', eventHandler('stderr'));
    source.addEventListener('end', eventHandler('end'));
    source.addEventListener('error', () => {
      recoverStream();
    });
  }

  function eventHandler(name) {
    return (event) => {
      dispatchRunEvent(name, parseEvent(event), eventIdFromSourceEvent(event));
    };
  }

  function dispatchRunEvent(name, data, eventId) {
    lastEventId = latestEventId(lastEventId, eventId);
    reconnectAttempts = 0;
    if (name === 'end') {
      finish(data || {});
      return;
    }
    const callback = eventCallback(name);
    if (callback) callback(data || {});
  }

  function eventCallback(name) {
    return {
      artifact: handlers.onArtifact,
      artifact_error: handlers.onArtifactError,
      review: handlers.onReview,
      agent: handlers.onAgent,
      stdout: handlers.onStdout,
      stderr: handlers.onStderr
    }[name];
  }

  function finish(data) {
    if (finished) return;
    finished = true;
    closeSource();
    if (handlers.onEnd) handlers.onEnd(data || {});
  }

  async function recoverStream() {
    if (closed || finished || recovering) return;
    recovering = true;
    closeSource();
    try {
      if (reconnectAttempts < maxReconnectAttempts) {
        reconnectAttempts += 1;
        scheduleReconnect();
        return;
      }
      await finishFromStatusOrInterrupt('reconnect_exhausted');
    } catch {
      if (closed || finished) return;
      await finishFromStatusOrInterrupt('status_unavailable');
    } finally {
      recovering = false;
    }
  }

  async function finishFromStatusOrInterrupt(reason) {
    await replayDurableEvents();
    if (closed || finished) return;
    const status = await loadRunStatus(runId, options);
    if (closed || finished) return;
    if (status && status.terminal === true) {
      finish({
        status: status.status,
        error: status.error || null
      });
      return;
    }
    interrupt(reason);
  }

  async function replayDurableEvents() {
    let cursor = lastEventId;
    while (!closed && !finished) {
      let page = null;
      try {
        page = await loadRunEventPage(runId, cursor, options);
      } catch {
        return;
      }
      const items = Array.isArray(page && page.items) ? page.items : [];
      items.forEach((item) => {
        if (closed || finished) return;
        const eventId = Number.parseInt(item && item.id, 10);
        dispatchRunEvent(String(item && item.event || ''), object(item && item.data), eventId);
      });
      if (closed || finished) return;
      const nextAfter = Number.parseInt(page && page.next_after_event_id, 10);
      if (!page || page.truncated !== true || !Number.isFinite(nextAfter) || nextAfter <= cursor) return;
      cursor = nextAfter;
    }
  }

  function scheduleReconnect() {
    setTimeout(() => {
      if (!closed && !finished) openSource();
    }, reconnectDelayMs);
  }

  function interrupt(reason) {
    if (finished) return;
    finished = true;
    closeSource();
    if (handlers.onInterrupt) handlers.onInterrupt({ reason });
  }

  function closeSource() {
    if (source && typeof source.close === 'function') source.close();
    source = null;
  }

  return {
    close() {
      closed = true;
      finished = true;
      closeSource();
    }
  };
}

function runEventUrl(runId, after = 0) {
  const base = '/api/runs/' + encodeURIComponent(runId) + '/events';
  return after ? base + '?after=' + encodeURIComponent(String(after)) : base;
}

function parseEvent(event) {
  try { return JSON.parse(event.data); } catch { return {}; }
}

function eventIdFromSourceEvent(event) {
  return event && (event.lastEventId || event.id);
}

function latestEventId(current, raw) {
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed > current ? parsed : current;
}

async function loadRunStatus(runId, options = {}) {
  if (typeof options.loadRunStatus === 'function') return options.loadRunStatus(runId);
  const fetchImpl = options.fetch || globalThis.fetch;
  if (typeof fetchImpl !== 'function') return null;
  const response = await fetchImpl('/api/runs/' + encodeURIComponent(runId), { cache: 'no-store' });
  if (!response || !response.ok) throw new Error('run status unavailable');
  return response.json();
}

async function loadRunEventPage(runId, afterEventId, options = {}) {
  if (typeof options.loadRunEventPage === 'function') return options.loadRunEventPage(runId, afterEventId);
  const fetchImpl = options.fetch || globalThis.fetch;
  if (typeof fetchImpl !== 'function') return null;
  const path = '/api/runs/' + encodeURIComponent(runId) + '/event-page?after_event_id=' + encodeURIComponent(String(afterEventId || 0));
  const response = await fetchImpl(path, { cache: 'no-store' });
  if (!response || !response.ok) return null;
  return response.json();
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}
