const SESSION_STORAGE_KEY = 'genomi:portal:session';

export async function initializePortalSession() {
  const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  const embeddedToken = document.querySelector('meta[name="genomi-launch-token"]')?.getAttribute('content') || '';
  const launchToken = fragment.get('token') || embeddedToken;
  if (!launchToken) return sessionToken();
  const response = await fetch('/api/session', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ launch_token: launchToken })
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload || !payload.session_token) {
    throw new Error(payload?.error?.message || 'The private GenomiLab launch link could not be opened.');
  }
  storeSessionToken(String(payload.session_token));
  window.history.replaceState(null, '', window.location.pathname + window.location.search);
  return String(payload.session_token);
}

export function portalSessionHeaders() {
  const token = sessionToken();
  return token ? { 'x-genomi-session': token } : {};
}

function sessionStore() {
  try {
    return globalThis.sessionStorage || null;
  } catch (error) {
    return null;
  }
}

function sessionToken() {
  const store = sessionStore();
  if (!store) return '';
  try {
    return store.getItem(SESSION_STORAGE_KEY) || '';
  } catch (error) {
    return '';
  }
}

function storeSessionToken(token) {
  const store = sessionStore();
  if (!store) return;
  try {
    store.setItem(SESSION_STORAGE_KEY, token);
  } catch (error) {
    /* the launch exchange also sets the loopback session cookie */
  }
}
