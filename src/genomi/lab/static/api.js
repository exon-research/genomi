"use strict";

const SESSION_STORAGE_KEY = "genomilab.portal-session.v1";

let sessionToken = "";
let csrfToken = "";

export class PortalError extends Error {
  constructor(message, code = "request_failed", status = 0) {
    super(message);
    this.name = "PortalError";
    this.code = code;
    this.status = status;
  }
}

export async function initializePortalSession() {
  const launchToken = consumeLaunchFragment();
  if (launchToken !== null) {
    clearStoredSession();
    if (!launchToken) {
      throw new PortalError("This GenomiLab launch link is not valid.", "invalid_launch_token", 401);
    }
    const credentials = await exchangeLaunchToken(launchToken);
    setSession(credentials.session_token, credentials.csrf_token);
    storeSession();
    return;
  }
  const stored = readStoredSession();
  if (stored) {
    setSession(stored.session_token, stored.csrf_token);
    return;
  }
  throw new PortalError("Open GenomiLab from its launch link.", "authentication_required", 401);
}

export async function apiRequest(path, options = {}) {
  if (typeof path !== "string" || !path.startsWith("/api/v1/")) {
    throw new PortalError("The GenomiLab workspace can only call local application APIs.", "invalid_api_path");
  }
  if (!sessionToken) {
    throw new PortalError("Open GenomiLab from its launch link.", "authentication_required", 401);
  }
  const method = String(options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  headers.set("X-GenomiLab-Session", sessionToken);
  if (method !== "GET") {
    if (!csrfToken) throw new PortalError("The local security session is missing. Refresh GenomiLab.");
    headers.set("X-GenomiLab-CSRF", csrfToken);
  }
  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: options.body,
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
      signal: options.signal,
    });
  } catch (_error) {
    throw new PortalError("The local GenomiLab process did not respond. Reopen it from Genomi.");
  }
  let payload = {};
  try {
    payload = await response.json();
  } catch (_error) {
    if (!response.ok) throw new PortalError("The local workspace returned an unreadable error.");
  }
  if (!response.ok) {
    if (response.status === 401) clearSession();
    const error = isRecord(payload.error) ? payload.error : {};
    throw new PortalError(
      typeof error.message === "string" ? error.message : "The request could not be completed.",
      typeof error.code === "string" ? error.code : "request_failed",
      response.status
    );
  }
  return isRecord(payload) ? payload : {};
}

export function postJson(path, payload) {
  return apiRequest(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function waitForEvents(path, afterSequence, signal) {
  return apiRequest(path, {
    headers: {"Last-Event-ID": String(Math.max(0, Number(afterSequence) || 0))},
    signal,
  });
}

function consumeLaunchFragment() {
  if (typeof globalThis.location === "undefined") return null;
  const fragment = String(globalThis.location.hash || "");
  if (!fragment.startsWith("#")) return null;
  const params = new URLSearchParams(fragment.slice(1));
  if (!params.has("token")) return null;
  const values = params.getAll("token");
  const onlyLaunchToken = [...params.keys()].every((key) => key === "token");
  const launchToken = values.length === 1 && onlyLaunchToken ? values[0] : "";
  try {
    const cleanUrl = `${globalThis.location.pathname}${globalThis.location.search}`;
    globalThis.history.replaceState(globalThis.history.state, "", cleanUrl);
  } catch (_error) {
    throw new PortalError(
      "GenomiLab could not remove its launch secret from browser history. Reopen the portal.",
      "launch_token_cleanup_failed"
    );
  }
  return launchToken;
}

async function exchangeLaunchToken(launchToken) {
  let response;
  try {
    response = await fetch("/api/v1/session", {
      method: "POST",
      headers: {"X-GenomiLab-Launch-Token": launchToken},
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
    });
  } catch (_error) {
    throw new PortalError("The local GenomiLab process did not respond. Reopen it from Genomi.");
  }
  let payload = {};
  try {
    payload = await response.json();
  } catch (_error) {
    throw new PortalError("The local workspace returned an unreadable session response.");
  }
  if (!response.ok) {
    const error = isRecord(payload.error) ? payload.error : {};
    throw new PortalError(
      typeof error.message === "string" ? error.message : "This GenomiLab launch link is not valid.",
      typeof error.code === "string" ? error.code : "invalid_launch_token",
      response.status
    );
  }
  return isRecord(payload) ? payload : {};
}

function setSession(nextSessionToken, nextCsrfToken) {
  if (typeof nextSessionToken !== "string" || !nextSessionToken) {
    throw new PortalError("The local workspace returned an invalid session.", "invalid_session_response");
  }
  if (typeof nextCsrfToken !== "string" || !nextCsrfToken) {
    throw new PortalError("The local workspace returned an invalid security session.", "invalid_session_response");
  }
  sessionToken = nextSessionToken;
  csrfToken = nextCsrfToken;
}

function readStoredSession() {
  try {
    const raw = globalThis.sessionStorage?.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    const stored = JSON.parse(raw);
    if (
      isRecord(stored) &&
      typeof stored.session_token === "string" &&
      stored.session_token &&
      typeof stored.csrf_token === "string" &&
      stored.csrf_token
    ) {
      return stored;
    }
  } catch (_error) {
    clearStoredSession();
    return null;
  }
  clearStoredSession();
  return null;
}

function storeSession() {
  try {
    globalThis.sessionStorage?.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({session_token: sessionToken, csrf_token: csrfToken})
    );
  } catch (_error) {
    // Page-memory authentication still works when storage is disabled.
  }
}

function clearStoredSession() {
  try {
    globalThis.sessionStorage?.removeItem(SESSION_STORAGE_KEY);
  } catch (_error) {
    // Storage can be unavailable in hardened browser profiles.
  }
}

function clearSession() {
  sessionToken = "";
  csrfToken = "";
  clearStoredSession();
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
