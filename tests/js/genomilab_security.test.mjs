import assert from "node:assert/strict";
import test from "node:test";

import { safeHttpUrl } from "../../src/genomi/lab/static/render-evidence.js";

test("launch fragment becomes exact-origin header auth without ambient credentials", async () => {
  const original = {
    fetch: globalThis.fetch,
    history: globalThis.history,
    location: globalThis.location,
    sessionStorage: globalThis.sessionStorage,
  };
  const stored = new Map();
  const requests = [];
  const replacements = [];
  globalThis.location = {
    hash: "#token=one-time-launch-secret",
    pathname: "/",
    search: "",
  };
  globalThis.history = {
    state: null,
    replaceState: (_state, _title, url) => replacements.push(url),
  };
  globalThis.sessionStorage = {
    getItem: (key) => stored.get(key) || null,
    removeItem: (key) => stored.delete(key),
    setItem: (key, value) => stored.set(key, value),
  };
  globalThis.fetch = async (path, options) => {
    requests.push({path, options});
    if (path === "/api/v1/session") {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          session_token: "page-session-secret",
          csrf_token: "csrf-secret",
        }),
      };
    }
    return {ok: true, status: 200, json: async () => ({status: "ready"})};
  };

  try {
    const api = await import(
      `../../src/genomi/lab/static/api.js?security=${Date.now()}`
    );
    await api.initializePortalSession();
    await api.apiRequest("/api/v1/bootstrap");

    assert.deepEqual(replacements, ["/"]);
    assert.equal(requests[0].path, "/api/v1/session");
    assert.equal(
      requests[0].options.headers["X-GenomiLab-Launch-Token"],
      "one-time-launch-secret"
    );
    assert.equal(requests[0].options.credentials, "omit");
    const apiHeaders = requests[1].options.headers;
    assert.equal(apiHeaders.get("X-GenomiLab-Session"), "page-session-secret");
    assert.equal(apiHeaders.has("Cookie"), false);
    assert.equal(requests[1].options.credentials, "omit");
    const persisted = [...stored.values()].join("\n");
    assert.match(persisted, /page-session-secret/);
    assert.doesNotMatch(persisted, /one-time-launch-secret/);

    globalThis.location.hash = "";
    const refreshed = await import(
      `../../src/genomi/lab/static/api.js?refresh=${Date.now()}`
    );
    await refreshed.initializePortalSession();
    await refreshed.apiRequest("/api/v1/workspace");
    assert.equal(requests.filter((request) => request.path === "/api/v1/session").length, 1);
    assert.equal(
      requests.at(-1).options.headers.get("X-GenomiLab-Session"),
      "page-session-secret"
    );
  } finally {
    for (const [name, value] of Object.entries(original)) {
      if (value === undefined) delete globalThis[name];
      else globalThis[name] = value;
    }
  }
});

test("evidence links reject loopback and local hostnames", () => {
  for (const unsafe of [
    "http://127.0.0.1:48123/private",
    "http://127.2.3.4/private",
    "http://localhost:48123/private",
    "http://portal.localhost/private",
    "http://research.local/private",
    "http://[::1]:48123/private",
    "http://[::ffff:127.0.0.1]/private",
  ]) {
    assert.equal(safeHttpUrl(unsafe), "", unsafe);
  }
  assert.equal(
    safeHttpUrl("https://evidence.example/record?id=1"),
    "https://evidence.example/record?id=1"
  );
});
