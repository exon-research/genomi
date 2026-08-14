# Claude Science Portal Study

Date: 2026-07-02

This directory records the Claude Science and open-design exploration used to
inform Genomi's new local science portal. It intentionally focuses on
post-onboarding workspace behavior, artifact handling, provenance, host-agent
routing, and local web-to-daemon event flow. Claude Science's `/start`
onboarding flow is not treated as a Genomi product model. The directory also
includes Genomi portal checkpoint screenshots captured while applying those
findings to the local web UI.

Files:

- `exploration-log.md`: factual notes from browser interaction, API inspection,
  local database/schema inspection, bundled client/runtime source inspection,
  and open-design source-code inspection.
- `chat-routing-and-runtime-state.md`: distilled model for how the web UI
  routes chat through the local server/daemon to the host agent, then renders
  persisted messages, events, artifacts, and provenance back in the browser.
- `webui-ux-comparison-and-alignment.md`: subagent-synthesized UX comparison
  across the Claude Science workspace, Open Design's daemon bridge, and the
  current Genomi portal, with concrete rules for what users should and should
  not see.
- `genomi-portal-ux-product-rules.md`: concise product-rule sheet translating
  the comparison into Genomi portal UX rules, disclosure boundaries, interaction
  feel, and implementation backlog.
- `genomi-design-takeaways.md`: concrete implications for Genomi's portal,
  including what to copy, what to avoid, and the near-term implementation shape.
- `capability-gap-backlog.md`: Claude Science capabilities that Genomi does not
  yet have a full user-facing equivalent for, with screenshot references and
  implementation notes.
- `screenshots.md`: live in-app-browser screenshots with captions for Claude
  Science workspace behavior and Genomi portal checkpoint states.
- `screenshots/`: PNG captures referenced by `screenshots.md`.

Important constraints:

- No new Claude Science chat turn was submitted during this exploration.
- Screenshots were captured from the live in-app browser during inspection; no
  headless browser captures are used in the retained notes.
- Auth cookies and nonce values are deliberately omitted.
- The installed Claude Science server is a compiled binary, so the inspected
  "source" is the shipped web bundle, local SQLite schema, runtime files, and
  binary strings that expose host SDK fragments and route/event names.
