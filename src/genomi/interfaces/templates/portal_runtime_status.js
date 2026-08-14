export function runtimeStatusLabel(runnable, detected) {
  const readyItems = Array.isArray(runnable) ? runnable : [];
  const detectedItems = Array.isArray(detected) ? detected : [];
  if (readyItems.length) {
    const primary = readyItems[0] && readyItems[0].label ? readyItems[0].label : 'assistant';
    const extra = readyItems.length > 1 ? ' +' + (readyItems.length - 1) + ' ready' : '';
    return primary + ' ready' + extra;
  }
  if (detectedItems.length) return detectedItems.length + ' local assistant setup' + (detectedItems.length === 1 ? '' : 's') + ' found';
  return 'No local assistant available';
}

export function renderRuntimeDetails(target, agents) {
  if (!target) return;
  const items = Array.isArray(agents) ? agents : [];
  if (!items.length) {
    target.innerHTML = '<div class="runtime-empty">No local assistant available.</div>';
    return;
  }
  target.innerHTML = items.map((agent) => {
    const status = agent.runnable ? 'Ready' : agent.available ? 'Setup only' : 'Unavailable';
    return '<div class="runtime-item" data-runtime-state="' + escapeAttribute(String(agent.status || '')) + '"><strong>' + escapeHtml(agent.label || agent.id || 'Assistant') + '</strong><span>' + escapeHtml(status) + '</span></div>';
  }).join('');
}

function escapeHtml(value) {
  return String(value || '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[char]));
}

function escapeAttribute(value) {
  return escapeHtml(value).replace(/`/g, '&#96;');
}
