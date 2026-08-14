export function watchProject(projectId, handlers = {}) {
  if (!projectId || typeof EventSource === 'undefined') {
    if (handlers.onMissingProject) handlers.onMissingProject();
    return { close() {} };
  }
  const source = new EventSource('/api/projects/' + encodeURIComponent(projectId) + '/events');
  let closed = false;

  source.addEventListener('ready', (event) => {
    if (handlers.onReady) handlers.onReady(parseEvent(event));
  });
  source.addEventListener('project_changed', (event) => {
    if (handlers.onProjectChanged) handlers.onProjectChanged(parseEvent(event));
  });
  source.addEventListener('frame_changed', (event) => {
    if (handlers.onFrameChanged) handlers.onFrameChanged(parseEvent(event));
  });
  source.addEventListener('messages_changed', (event) => {
    if (handlers.onMessagesChanged) handlers.onMessagesChanged(parseEvent(event));
  });
  source.addEventListener('artifacts_changed', (event) => {
    if (handlers.onArtifactsChanged) handlers.onArtifactsChanged(parseEvent(event));
  });
  source.addEventListener('error', () => {
    if (!closed && handlers.onInterrupt) handlers.onInterrupt();
  });
  return {
    close() {
      closed = true;
      source.close();
    }
  };
}

function parseEvent(event) {
  try { return JSON.parse(event.data); } catch { return {}; }
}
