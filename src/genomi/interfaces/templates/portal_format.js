export function parseJsonText(text) {
  if (typeof text !== 'string') return null;
  const trimmed = text.trim();
  if (!trimmed || !'[{'.includes(trimmed[0])) return null;
  try { return JSON.parse(trimmed); } catch { return null; }
}

export function outputLineCount(value) {
  if (typeof value !== 'string' || !value.trim()) return 0;
  return value.replace(/\n$/, '').split('\n').length;
}

export function formatPayload(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

export function formatShort(value) {
  if (Array.isArray(value)) return value.length + ' item' + (value.length === 1 ? '' : 's');
  if (value && typeof value === 'object') {
    const preferred = ['status', 'headline', 'message', 'state', 'count', 'observation_count', 'source_count'];
    for (const key of preferred) {
      if (value[key] !== undefined && value[key] !== null && value[key] !== '') return String(value[key]);
    }
    return Object.keys(value).length + ' field' + (Object.keys(value).length === 1 ? '' : 's');
  }
  return String(value);
}

export function formatContextValue(value) {
  const text = formatPayload(value).replace(/\s+/g, ' ').trim();
  return compactLine(text, 500);
}

export function compactLine(text, limit) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim();
  return clean.length > limit ? clean.slice(0, limit - 1) + '...' : clean;
}

export function isEmptyValue(value) {
  return value === null || value === undefined || value === '' || value === false ||
    (Array.isArray(value) && value.length === 0) ||
    (value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 0);
}

export function titleCase(value) {
  return String(value || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

export function humanizeState(value) {
  const text = String(value || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!text) return '';
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function singularTitle(value) {
  const text = titleCase(value);
  if (/\s/.test(text)) return text;
  return text.endsWith('s') && !text.endsWith('ss') ? text.slice(0, -1) : text;
}
