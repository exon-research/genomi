"use strict";

let csrfToken = "";

export class PortalError extends Error {
  constructor(message, code = "request_failed", status = 0) {
    super(message);
    this.name = "PortalError";
    this.code = code;
    this.status = status;
  }
}

export function setCsrfToken(value) {
  csrfToken = typeof value === "string" ? value : "";
}

export async function apiRequest(path, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  if (method !== "GET") {
    if (!csrfToken) {
      throw new PortalError("The local security session is missing. Refresh GenomiLab.");
    }
    headers.set("X-GenomiLab-CSRF", csrfToken);
  }

  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: options.body,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    });
  } catch (_error) {
    throw new PortalError("The local GenomiLab process did not respond. Reopen it from the launch command.");
  }

  let payload = {};
  try {
    payload = await response.json();
  } catch (_error) {
    if (!response.ok) {
      throw new PortalError("The local workspace returned an unreadable error.", "invalid_response", response.status);
    }
  }

  if (!response.ok) {
    const errorPayload = isRecord(payload.error) ? payload.error : {};
    throw new PortalError(
      typeof errorPayload.message === "string" ? errorPayload.message : "The request could not be completed.",
      typeof errorPayload.code === "string" ? errorPayload.code : "request_failed",
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

export function profilePath(profileId, action = "") {
  const base = `/api/v1/profiles/${encodeURIComponent(profileId)}`;
  return action ? `${base}/${action}` : base;
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
