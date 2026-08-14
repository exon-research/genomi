# Genomi Design Takeaways

## Central Finding

Claude Science makes the web UI feel like the agent because the local server
owns the agent session and persists every visible state transition. The browser
is a polished projection over:

- project state
- host-agent frames
- transcript messages
- tool/execution logs
- artifacts and artifact versions
- artifact lineage/provenance
- environment and verification state

Genomi should use the same shape. The web UI should not become a separate LLM
client, and it should not ask the user to interact with the host-agent CLI/UI.
The Genomi portal should own the visible chat surface while the local Genomi
server brokers work to the installed host agent and streams back durable state.

## Product-Page Workspace Comparison

The public Claude Science page frames the product as "one research
environment" that runs analyses, searches databases, and traces work from data
wrangling to publication. The visible product promises are not debug surfaces:
they are artifacts with history, built-in scientific renderers, reviewer/check
state, managed compute, domain-ready connectors, project files, and durable
provenance.

Current Genomi Portal is directionally close in architecture but too noisy in
presentation. The inspected workspace screen puts all of these on stage at the
same time:

- workspace switcher and workspace metadata
- assistant runtime status
- active genome identity
- conversation list
- chat transcript
- work-step/error list
- artifact cards in the conversation
- full Files & Artifacts library
- file search and library filters
- generated-file sections
- low-level runtime labels and raw tool fragments

That makes the portal feel like a system console rather than a scientific
workbench. The user should not have to understand which panel owns "context",
"work trail", "generated records", or "assistant status" before asking a
genomics question.

The default shell should become:

- Left rail: workspace identity, conversations, and a Files entry. Workspace
  management lives in a switcher or details drawer, not as a permanent
  operations panel.
- Center: the conversation and composer. Work should appear as one compact
  grouped progress line per assistant turn, with clean labels and a disclosure
  for details.
- Right side: the selected object workspace. It should show the open artifact,
  file, evidence map, genome state, or provenance view. It should not duplicate
  a complete file library while the conversation already shows generated
  artifacts.
- Top bar: the active genome object, if present, with direct Switch/Add
  actions. Avoid generic readiness/status chips and avoid a global Refresh
  button as a primary action unless it names what refreshes.

Work-step rows should be user-facing research progress, not host-agent
implementation output. Raw MCP tool ids, skill boot messages, oversized-output
recovery, shell commands, and permission plumbing belong in technical
diagnostics. If permission is needed, the visible object is an approval card
with a clear action such as "Allow Genomi tool access", not a failed run row
whose details say the host agent lacked permission.

The Files & Artifacts surface should copy the underlying mental model from the
reference portal:

- Generated results are first-class objects.
- Opening a file should make it the right-side workspace.
- Every artifact should have `Preview`, `View in chat`, `Provenance`, and
  `Download` where supported.
- Artifact provenance should connect code or operation recipe, work trail,
  origin chat, environment/source state, and review findings.
- File/library filters should be secondary once the user has selected an
  object; they should not crowd the default research turn.

Capability gaps should be explicit backlog, not weak UI substitutes. Genomi
does not yet fully match these reference capabilities:

- background reviewer that checks citations, numbers, figures, and evidence
  traceability before surfacing results;
- native renderers for proteins, alignments, genomic tracks, chemical
  structures, notebooks, and PDFs;
- persistent Python/R kernels and environment snapshots for arbitrary analyses;
- managed local/HPC/GPU compute;
- generated reconstruction code for every artifact;
- complete artifact version history with reproducible rebuild/edit loops.

Until those exist, Genomi should show the Genomi-native equivalent it actually
has: evidence envelopes, source coverage, AGI privacy boundaries, operation
trace, files, reports, and review/guardrail findings.

## What Genomi Should Copy

### Project And Frame Model

Use a local portal model close to:

```text
project
  frame / run
    message stream
    execution/tool events
    artifacts
      artifact versions
      lineage/provenance
```

For Genomi terms:

- Project: a local research workspace.
- Frame/run: one host-agent turn or delegated investigation.
- Message stream: exact user/assistant/tool/result blocks.
- Execution/tool events: Genomi MCP calls, host-agent calls, library installs,
  background jobs, and Active Genome Index parse/query operations.
- Artifact: any rendered report, evidence report, table, plot, review surface,
  notebook, or exported file.
- Artifact version: immutable content snapshot with checksum/provenance.

### Stable UI Hooks

Claude Science uses stable test IDs for real product surfaces. Genomi should do
the same for every artifact and transcript control.

Minimum Genomi equivalents:

```text
genomi-conversation-scroll
genomi-tool-chip
genomi-tool-group
genomi-artifact-tray
genomi-artifact-card
genomi-artifact-open-split
genomi-split-right
genomi-artifact-actions
genomi-artifact-download
genomi-artifact-provenance-inline
genomi-provenance-tab-evidence
genomi-provenance-tab-messages
genomi-provenance-tab-tools
genomi-provenance-tab-environment
genomi-provenance-tab-review
```

These should be product contracts, not just testing conveniences. They make the
portal inspectable, debuggable, and automation-friendly.

### Inline Artifact Provenance

Genomi artifacts should have a right-side split pane with:

- artifact preview
- artifact actions
- inline provenance
- close/download/copy-link controls

Provenance should be adjacent to the artifact rather than buried in chat.

For Genomi, provenance tabs should be domain-shaped:

- Evidence: evidence envelope, coverage, observations, source-level records.
- Messages: host-agent turns and Genomi tool calls that produced the artifact.
- Tools: MCP operations, parameters, defaults applied, background job state.
- Environment: installed Genomi version, library status, source coverage,
  Active Genome Index context approval state, and runtime state.
- Review: checks, warnings, negative-inference constraints, clinical safety
  gates, and artifact validation status.

The second Claude Science Library pass makes one refinement sharper: provenance
must not be only artifact metadata. The Code, Execution Log, and Messages tabs
show that the artifact is connected to synthesized reproduction code,
execution cells, and the host-agent transcript slice that produced it. Genomi's
artifact pane should therefore make three relationships visible together:
artifact version, tool/execution trace, and originating conversation context.

The main chat transcript should use the same grouping principle. Assistant
answers should not be followed by a loose pile of raw tool chips; they should
show a compact work-group header with step/running/error counts, then keep each
tool call expandable below that header. This lets the chat stay readable while
still preserving the host-agent work trace in place.

Grouped work should also be actionable. A user should be able to attach or ask
about a grouped message-level work trace directly from the transcript, using
the same sanitized context packet contract as the dedicated Work trail pane.
That keeps the loop local to the place where the user noticed the issue.

Project files need the same loop. Opening a Markdown report, table, image, PDF,
or notebook outline should not be a dead-end preview; it should be selectable
research material with direct actions to include the file in the next message
or ask about it immediately in the current conversation or in a fresh focused
conversation. The selected material sent to the host agent should name the
project-relative file, file kind, preview state, and a bounded visible excerpt
or outline, while keeping backend workspace paths and raw transport fields
hidden.

Selected material should also be able to start a focused conversation without
turning the UI into a frame/fork console. The user-facing action is "Ask in new
conversation"; the implementation is simply a canonical portal run request
without the current frame id, carrying the clicked file, evidence item, work
step, or artifact as bounded selected material.

### Active Genome As A Workspace Object

The active genome is not an internal readiness flag. The default workspace
header should answer, at a glance, which genome is active and what kind of
source/readiness it has. The full genome pane can hold inventory, privacy
boundary, and technical state, but the top-level workspace needs direct actions
to view or switch the active genome and add a new genome source. Vague labels
such as `Genome ready` are not sufficient because they hide the actual research
object the user is relying on.

### Lazy Lineage

Do not compute full provenance for every card upfront. Cards should show compact
metadata; provenance should lazy-load when opened.

Useful states:

```text
lineage_pending
lineage_ready
lineage_failed
```

Claude Science has a `lineage_ready` event. Genomi should use the same event
shape for artifact provenance generated after the visible content.

### Versioned Artifacts

Artifacts need immutable versions. A Genomi artifact should have:

- `artifact_id`
- `version_id`
- `project_id`
- `run_id` or `frame_id`
- `creating_turn_id`
- `filename` or display title
- `content_type`
- `checksum`
- `created_at`
- `latest_version_id`
- `is_intermediate`
- `source_records` or evidence references
- `dependency_versions`

Avoid local filesystem paths in user-facing JSON unless the current action is
explicitly a local file operation.

Artifact identity should also be URL-addressable. Opening
`/projects/:project_id/artifacts/:artifact_id` should select that artifact and
restore the artifact workspace directly, without depending on a prior hash,
local-storage frame selection, or dashboard state.

Immutable artifact versions need the same treatment:
`/projects/:project_id/artifacts/:artifact_id/versions/:version_id` should
restore the artifact workspace and preview the versioned file only after the
artifact's own version list proves that version belongs to that artifact. A
version route is evidence-state identity, not just a file download shortcut.
The backing APIs should preserve the same boundary:
project-scoped artifact and version routes are the public contract, while
global artifact/version ids are internal storage details.

The selected artifact pane should also expose version state directly. Once an
artifact's version history is loaded, the user should be able to see the latest
and selected immutable versions in the preview header, switch versions without
leaving the workspace, and keep the active provenance/runtime/review tab in the
URL.

### Event-Driven UI

Claude Science updates the UI from event deltas. Genomi should use SSE first
because it is simple and sufficient for local-first streaming:

```text
frame_update
frame_messages_delta
text_chunk
tool_event
tool_stdout_chunk
artifact_created
artifact_version_created
lineage_ready
verification_update
environment_status
background_job_update
```

The browser should update cached project/frame/artifact data from these events.
It should not invent state that the server cannot replay after refresh.

## What Genomi Should Not Copy

### Do Not Copy `/start`

Claude Science's `/start` flow is onboarding. It is not the research workspace
model Genomi needs.

Genomi install onboarding can collect setup choices, but the portal should open
directly into the research workspace after install. The user should not see
Claude-style allow/deny screens in the Genomi context.

The handoff command should read as a product entry point: `genomi serve`.
Interactive terminal launches open the local science workspace, while host-agent
pipe launches still get MCP stdio. Use `genomi serve --app --no-browser` for
supervised headless app launches and `genomi serve --transport stdio` when a
human explicitly wants MCP stdio.

### Do Not Rebuild The Old Decode Dashboard As The Portal

The old Genomi Decode dashboard is obsolete as the primary flow. Its utilities
can be reused only if they support the new chat/artifact/provenance workspace.

Allowed reuse:

- compact visual language
- artifact card rendering utilities
- table/plot preview helpers
- evidence report renderers

Not allowed:

- a dashboard-first portal
- a "render decode dashboard" primary action
- treating dashboard generation as the main user workflow

### Do Not Make Genomi A Question Router

Genomi's own `AGENTS.md` says Genomi is a library of capabilities, not a router
for question shapes. The portal must preserve that:

- Host agent owns decomposition.
- Genomi tools provide declared operations and evidence envelopes.
- The UI renders the work trace and artifacts.
- Genomi should not hide weak evidence behind answer-shaped UI.

## Proposed Genomi Portal Contract

### Local Routes

Recommended route shape:

```text
/                      redirects to current/new project
/projects/:project_id
/projects/:project_id/runs/:run_id
/projects/:project_id/artifacts/:artifact_id
/projects/:project_id/artifacts/:artifact_id/versions/:version_id
```

Avoid keeping `/start` as a live product route.

### Server APIs

Minimum API shape:

```text
GET  /api/projects
POST /api/projects
GET  /api/projects/:project_id
GET  /api/projects/:project_id/runs
POST /api/projects/:project_id/runs
GET  /api/runs/:run_id
GET  /api/runs/:run_id/messages?from=N
GET  /api/projects/:project_id/artifacts
GET  /api/artifacts/:artifact_id
GET  /api/artifacts/versions/:version_id
GET  /api/artifacts/versions/:version_id/provenance?slim=true
GET  /api/artifacts/versions/:version_id/provenance?slim=false
GET  /api/runs/:run_id/events
```

For streaming:

```text
GET /api/projects/:project_id/events
```

Use SSE events with replayable sequence ids.

### Host-Agent Bridge

The portal should not require users to leave the browser to talk to the host
agent. The server should own the bridge:

1. Browser submits a user message to the Genomi server.
2. Server creates a run/frame record.
3. Server sends the prompt plus current project context to the configured host
   agent surface.
4. Host agent uses Genomi MCP tools and skills.
5. Server records host-agent messages, tool calls, Genomi MCP results, and
   artifacts.
6. Browser streams the replayable state.

This is the open-design/Claude Science pattern: the web UI owns the chat
surface; the local server brokers the host-agent conversation.

## Open-Design Architecture Lesson

Open-design confirms that the browser should not talk directly to the host
agent CLI. Its web shell posts a run request to the daemon, the daemon starts
or resumes the selected host agent, and the browser consumes normalized SSE
events.

The important refinement is that open-design uses two event planes:

```text
GET /api/runs/:run_id/events
GET /api/projects/:project_id/events
```

The run stream is the active reasoning loop: text deltas, status, tool calls,
tool results, and terminal state. The project stream is the workspace loop:
files, live artifacts, conversation creation, and refresh signals.

Genomi has adopted this split for the portal:

- `GET /api/runs/:run_id/events` remains the host-agent turn stream.
- `GET /api/projects/:project_id/events` now emits compact project refresh
  signals:
  - `frame_changed`
  - `messages_changed`
  - `artifacts_changed`
  - `project_changed`
- The browser subscribes through `portal_project_stream.js` and refetches the
  public REST shape for the affected pane instead of trusting large stream
  payloads.
- Project-event replay must stay bounded. High-frequency message streaming
  should not create an unbounded in-memory history, and store mutators should
  route workspace invalidation through one normalized notifier.

This avoids a common failure mode for local agent portals: the chat pane looks
live during a single run, but artifacts and side panes only update by manual
refresh. Genomi should keep the project stream as the owner of workspace
freshness.

The follow-up source comparison also argues for one daemon-owned API surface
across web, CLI, and MCP. Genomi should move toward that without weakening its
evidence contracts:

- formalize the project workspace detail shape, including Genomi-owned storage
  today and explicit user-approved folder-backed workspaces only later;
- keep browser chat submission on the canonical `POST /api/runs` contract,
  then add durable run result packages while keeping project/frame submit
  endpoints as compatibility conveniences;
- add frame fork, side-chat, and handoff APIs only when the generated prompt
  can preserve selected material, artifact links, evidence limits, and Active
  Genome Index approval state;
- promote files gradually: Genomi now has read-only project-relative file
  listing/search; next steps are nested folder browsing, file content APIs
  independent of artifacts, then selective write/import/version flows;
- add a portal MCP/CLI bridge only if it routes through the same portal APIs
  and respects current-session Active Genome Index approval.

### Artifact Provenance Model

Genomi should represent provenance in one canonical shape:

```json
{
  "artifact_id": "art_...",
  "version_id": "ver_...",
  "run_id": "run_...",
  "created_at": "...",
  "content_type": "application/json",
  "checksum": "...",
  "evidence_envelopes": [],
  "tool_calls": [],
  "messages": [],
  "dependencies": [],
  "environment": {
    "genomi_version": "...",
    "libraries": [],
    "active_genome_index": {
      "approved": false,
      "agi_id": null
    }
  },
  "review": {
    "status": "unchecked",
    "checks": []
  }
}
```

The exact fields can evolve, but the split between content, evidence, tool
trace, dependencies, environment, and review should stay explicit.

## Near-Term Implementation Priorities

1. Remove `/start` as a product route and make install onboarding responsible
   for first-run setup.
2. Keep the Genomi portal's first screen as the research workspace.
3. Replace dashboard-first language with artifact workspace language.
4. Add stable `data-testid` hooks to transcript, tool, artifact, split-pane,
   and provenance controls.
5. Make artifact cards open in a split pane with typed actions.
6. Add inline provenance tabs for Genomi artifacts.
7. Add lazy provenance/lineage records linked to artifact versions.
8. Stream host-agent events through a replayable local event API.
9. Make every Genomi tool result used in the portal preserve its
   `evidence_envelope`.
10. Reuse old decode utilities only where they render artifact previews or
    evidence reports in the new workflow.

## Current Genomi Checkpoint

The local portal checkpoint captured on 2026-07-02 has started applying these
takeaways:

- `/start` is not a Genomi portal route; it returned `404 Not Found`.
- The right-side workspace now starts with Files & Artifacts instead of an
  explanatory hero/product panel.
- Artifact cards and the generated-artifact tray expose stable hooks:
  `genomi-artifact-tray`, `genomi-artifact-card`,
  `genomi-artifact-open-split`, and `genomi-split-right`.
- The artifact pane now has inline provenance tabs for Preview, Evidence,
  Tool calls, Work trail, Origin chat, Environment, Runtime, Technical state,
  Rebuild recipe, and Review when those objects exist for the artifact.
- The Review tab can produce a host-agent handoff brief from artifact
  provenance and panel state, and artifact versions can now append a completed
  deterministic review-run history entry through `Run review checks`.
- The portal now has a first Genomi-native `evidence_packet` artifact renderer
  backed by `research.build_target_packet`, so not every built-in artifact path
  depends on the obsolete Decode dashboard.
- Post-review hardening fixed the renderer boundary: evidence-packet artifacts
  now get artifact-specific HTML files, portal file metadata no longer pollutes
  the presented Genomi result, missing targets fail cleanly, and the artifact
  State tab reuses the canonical target-packet frontend model.
- Artifact files now snapshot into immutable version records. Public artifact
  payloads expose latest-version metadata, version counts, and checksums while
  keeping local snapshot paths private. Artifact previews now prefer
  `/api/artifacts/versions/{version_id}/file`; artifact `/file` URLs are only
  latest-version convenience routes.
- A later live comparison removed the `Result history` strip. Even when backed,
  it repeated the same objects already available through the artifact view and
  made the preview read like a status dashboard. History remains available as
  version identity, origin chat, work trail, rebuild recipe, source limits,
  and review state, but only where the selected artifact actually has them.
- Artifact inspection now hydrates from explicit artifact detail and version
  routes on open, so cards can stay lightweight while the split pane owns the
  richer provenance/version state.
- Artifact detail can now expose origin-frame messages. When an artifact is
  tied to a host-agent frame, Genomi stores a bounded origin snapshot with the
  frame id and message ids present at artifact creation. The split pane shows an
  `Origin chat` provenance tab with the sanitized user/tool/assistant messages
  from that snapshot. Project artifact lists and render events use an explicit
  summary shape and omit message lineage until the artifact is opened.
- Artifact detail now also exposes a `View in chat` action when origin messages
  are available. This opens the full host-agent frame through the normal chat
  route, preserving a useful distinction from Claude Science: `Messages` is the
  bounded artifact lineage slice, while `View in chat` is the complete
  conversation frame for surrounding turns.
- Selected artifact evidence now has a direct `Ask selected` action in the
  split pane. The action reuses the same prompt-context controller and
  host-agent submit path as the composer, so visual evidence does not become a
  parallel chat mechanism.
- Live Genomi result views now have the same direct `Ask selected` path.
  Runtime tool cards stay attachable after completion in the current transcript;
  project refreshes must not replace them with persisted-redacted history until
  the user reloads or navigates.
- Reopened persisted tool history now uses a display-only follow-up model.
  Stored public result lanes can remain inspectable, but ordinary transcript
  cards and evidence-ledger cards draft `Re-check tool` prompts before the host
  agent relies on stale or redacted evidence.
- The portal now has a frame-level Work Trail pane. Sanitized tool
  calls/results/errors from the current conversation are projected into ordered
  steps, can be attached back into the next turn as a bounded trace summary,
  and can drill down into the same purpose-built Genomi result renderers used
  in transcript cards.
- Generic canonical-envelope evidence panels now have selected-node
  inspectors. Envelope guidance, coverage, observation, next-action, and
  defaults nodes can be selected, inspected inline, and sent into the next turn
  through the existing prompt-safe selected-context path.
- The selected-context tray now has its own node inspector, so evidence remains
  inspectable after attachment. Users can inspect full attached evidence detail,
  remove individual nodes, draft a prompt from the packet, copy it, or send it
  without losing provenance or context-kind boundaries.
- Attached material is a composer/workspace state, not a standalone product
  pane. Context cards should carry their provenance kind into the UI and expose
  actions that say what will happen: `Ask about work trail`, `Draft work`,
  `Ask evidence`, `Draft artifact`, and similar labels are more legible than a
  generic prompt button when the user routes visual state back through the host
  agent.
- Post-review hardening made selected context a cleaner contract: the browser
  groups mixed result-node and envelope-evidence context separately when
  drafting prompts, the server persists only whitelisted non-authoritative
  metadata, and tray packet rendering lives in a focused module instead of the
  composer controller.
- Artifact provenance now has an origin Trace tab derived from the artifact's
  latest bounded origin messages. It is message-derived work-trail provenance:
  useful for seeing and reusing the visible production trail, but not a Claude
  Science Execution Log equivalent with normalized cells, stdout/stderr,
  stable tool-step ids, and runtime labels.
- Artifact provenance now renders that bounded message-derived work trail as
  numbered work-step cards. This is the right user-facing partial equivalent:
  the user can inspect and ask about the visible producing tool work without
  seeing raw packet mechanics, while the exact Genomi operation id stays in the
  host-agent payload.
- The origin Trace tab should stay as an adapter boundary, not artifact-shell
  logic. `portal_artifact_origin_trace.js` owns the current message-snapshot
  source, while `portal_frame_trace.js` owns trace context-node formatting. This
  leaves room for future explicit execution-log cells, tool-call ids, and
  artifact dependency records without bloating `portal_artifacts.js`.
- Artifact selected-node inspection should match every other visual-evidence
  surface. `portal_artifact_selection.js` owns artifact selection counts and
  the shared inspector, so users can see the exact prompt-safe artifact context
  before `Use selection` or `Ask selected`.
- Artifact selected-node context must normalize once. The selected-node array
  used by the inspector is the same prompt-safe shape sent through
  `artifactContextForSelection`, avoiding drift between what the user sees and
  what the host-agent turn receives.
- A subagent UX comparison pass aligned the visible shell around research
  workspace objects: `Files & Artifacts`, `Evidence from this chat`, `Work
  trail`, `Genome state`, and `Evidence sources`. The evidence-source setup
  surface, technical JSON, artifact operation traces, and renderer state remain
  available, but their labels now mark them as secondary or technical detail
  instead of primary science objects.
- Host-agent-produced files written under the project workspace now become
  `project_file` artifacts after successful runs. The Library separates
  browser-supplied `Your uploads` from assistant-generated `Produced files`,
  while local filesystem paths remain backend-only.
- The Files & Artifacts pane now includes a read-only `Workspace files`
  surface backed by a project-scoped API. It lists project-relative files,
  supports search, and opens the linked artifact when a file has been
  snapshotted into the artifact/version system.
- Desktop and narrow-viewport screenshots are recorded in `screenshots.md`.

Remaining architectural work:

- Continue replacing the temporary visual-inspection artifact fixture with
  normal artifacts emitted from host-agent turns and Genomi tool results. The
  `evidence_packet` renderer is the first concrete slice of that path.
- Extend artifact provenance beyond the current bounded message-id snapshot
  with run ids, tool-call ids, frame work-trace steps, execution-log cells, and
  artifact dependency records. Keep the public list/summary shape separate
  from detail-only provenance.
- Stream artifact creation, provenance readiness, and review/check updates
  through replayable SSE events.
- Add more Genomi-native artifact renderers beyond `evidence_packet`; keep
  `decode_dashboard` available only as a compatibility/utility renderer, not as
  the primary portal workflow.
- Keep result rendering behind an operation-keyed registry so new Genomi
  evidence panes can be added without growing a closed branch in the portal
  shell. Renderer registration must still require canonical
  `evidence_envelope` payloads.
- Treat explicit assistant evidence plans as workspace objects. When an answer
  says what evidence should be inspected, the portal should expose those source
  lanes as selectable context nodes that can be attached, drafted, or sent
  directly into the next host-agent turn, without pretending they are Genomi
  tool evidence.
- Selected context should generate a next-turn prompt matched to its provenance.
  For assistant evidence checklists, Ask should request the smallest relevant
  Genomi tool calls, preserve `evidence_envelope` limits, and report supported,
  missing, or out-of-scope evidence instead of using a generic attachment
  prompt. The same provenance-aware behavior should continue expanding across
  each selected context card: tool-result nodes, genome context, artifact
  packets, and persisted-redacted history should each draft prompts that match
  whether the context is current evidence, selected evidence, or a re-check
  pointer.
- Persisted tool history should keep a narrow presented-payload layer for
  canonical Genomi evidence results. Raw tool payloads and private/sample fields
  remain out of persisted public messages, but allowlisted renderer-critical
  fields should survive reload so purpose-built evidence maps remain
  inspectable after reload. Persisted redacted history is display-only: it can
  show public lanes and selected-node details, but it should not attach evidence
  to a new host-agent turn without a fresh tool re-check.
- Result nodes should stay explorable before and during attachment. Selecting a
  node reveals its source lane, label, and redacted context in-place, matching
  the Claude Science habit of making evidence lanes inspectable inside the
  workspace instead of burying them in prose. The attach/ask action belongs to
  live/current canonical result views; stale persisted history remains a
  display-only re-check pointer.
- Evidence Ledger details should be first-class selected-context surfaces when
  they are current/reusable. A live ledger entry can render result/evidence
  nodes, show a ledger-level selected-node inspector, and expose the same
  direct loop as result panels: use selected evidence, draft a next-turn prompt,
  or ask the host agent with exactly those prompt-safe nodes. Persisted or
  display-only ledger entries must not gain that bar; they remain visual
  pointers that ask the host agent to re-check current Genomi tools.
- Evidence sources should include curated request builders only as a
  secondary surface. The portal can collect known friendly inputs,
  progressively disclose target-specific fields, and attach or draft selected
  material for the host agent, while raw schema property names, operation ids,
  parameter JSON, dependency contracts, and output shapes remain in technical
  disclosure.
- Request-builder behavior should come from a curated source-lookup model, not
  biomedical parameter-name guesses in the browser. Defaults should render as
  omittable hints and stay out of drafted parameters unless the user explicitly
  supplies them, preserving Genomi's `defaults_applied` evidence trail.
- Request builders need a direct chat handoff, not just copy/attach helpers.
  `Ask with check` should attach prompt-safe selected material and submit
  through the normal frame-message path. The browser should never call Genomi
  MCP directly from that button; it should post a chat turn, open the run SSE
  stream, and let the selected host agent decide the next tool call.
- Request-builder semantics belong in a pure model, not in DOM attributes.
  The renderer may keep stable field ids on controls, but visibility,
  conditional requiredness, omitted defaults, missing-input policy, prompt
  text, and selected-context payloads should be computed from the tool contract
  model. This prevents the UI from becoming an accidental state machine.
- Host-agent run finalization must always leave a visible terminal transcript
  outcome. If an agent exits successfully without parsed assistant output,
  Genomi should persist and stream a compact diagnostic instead of making the
  web UI look like the user's turn disappeared into a silent backend.
- Host-agent setup/progress chatter must not become assistant answer text.
  Startup, stderr, and recognizable context-loading dumps belong in compact
  work-trace diagnostics that remain attached to the run after refresh. The
  answer body should contain only answer-shaped assistant text; provenance and
  setup state should stay visible but separate.
- Stream presentation needs one run-local transcript policy. Agent adapters
  normalize transport events, but the run presentation layer decides answer
  text vs diagnostic vs tool event, owns persistence, and guarantees terminal
  failure on internal stream errors. The browser should render that transcript,
  not rediscover stream semantics from stdout/stderr channels.
- Persisted transcript replay should group by `run_id`, not by incidental
  storage order. Diagnostics and tool events can arrive before the assistant
  answer is materialized, but they still belong to the assistant run that
  produced them.
- Generated artifacts and produced files should appear at the originating turn
  boundary as well as in the global artifact workspace. The artifact summary
  can expose compact origin context (`frame_id`, bounded message count, stored
  producing run id, and `run_ids`) so the browser attaches an artifact card
  under the run that produced it without leaking raw transcript content.
- Artifact provenance should be tabbed, not flattened into one giant detail
  drawer. Claude Science separates generated reconstruction code, raw
  execution log, originating messages, environment snapshot, and review checks.
  Genomi should map that shape to evidence reports: summary/reproduction,
  tool-call trace, originating transcript, library/runtime context, dependency
  artifacts, and review/validation.
- Runtime state should be evidence-native, not a generic machine inventory.
  Claude Science's Environment tab is useful because it explains how an
  artifact was produced; Genomi should express the same class of state through
  origin boundaries, applied defaults, consulted source/library coverage,
  evidence-envelope interpretation limits, and immutable artifact versions.
- Work trail should be transcript-native but compact. Claude Science's command
  cards show grouped step titles and output counts inline, then expand to
  command source and stdout/stderr on demand. Genomi should keep host-agent
  setup and tool traces attached to the turn while avoiding raw log streams in
  the answer body.
- The artifact library belongs beside the transcript, not below it. A split
  pane with grouped artifacts, previews, search/layout controls, and per-file
  actions lets the user inspect durable outputs while keeping the chat loop in
  view.
- Public Claude Science captures and user feedback sharpen the Library target:
  Markdown notes, scripts, generated figures, PDFs, tables, notebooks, and
  review records must be directly openable as the research record. Users should
  be able to return after manuscript submission and reconstruct what happened
  from the files, code, images, conversation, and artifact history without
  searching through raw logs.
- The follow-up/re-check wording for tool evidence belongs in the canonical
  tool-result presentation layer, not in each surface that displays a tool
  event. Ledger, Work trail, and tool chips should delegate to the same policy
  so persisted-redacted and display-only boundaries cannot drift.
- Selected-node extraction should have one canonical prompt-safe path. Result
  panels, evidence panels, ledgers, trays, and artifacts may present different
  chrome, but the node shape sent to the host agent should be the same shape
  the user just inspected.
- Artifact routes are part of the workspace contract, not a convenience link.
  A copied artifact URL should reopen the same project artifact, show the
  preview/provenance surface, and leave the user in the artifact workspace
  rather than at the chat composer or an obsolete dashboard.
- Version routes should preserve immutable review context. If a user reviews
  or shares an artifact version, the portal should reopen that exact rendered
  content through the artifact workspace and fall back to the artifact route
  when the named version is not part of the artifact's loaded version history.
- Artifact metadata must not leak raw filesystem or untrusted upstream URLs.
  Portal-owned scoped snapshot URLs are the default public links. Optional
  external open links are allowed only for explicit loopback `http(s)` targets
  without credentials.
- Artifact `Copy link` should copy workspace identity, not artifact bytes.
  Cards copy `/projects/:project_id/artifacts/:artifact_id`; active
  version-scoped previews copy
  `/projects/:project_id/artifacts/:artifact_id/versions/:version_id`, leaving
  raw file endpoints as preview/open implementation details.
- Artifact tab state is workspace state. Evidence, Tool calls, Work trail,
  Origin chat, Runtime, Technical state, and Review tabs should be addressable
  by route so a user can return to the same inspection surface and send/copy
  context from the view they were actually inspecting.
- Artifact lists should behave like a research library. Search, class filters,
  compact/card layout, active-artifact highlighting, and no-match recovery keep
  generated evidence inspectable as a project grows beyond one artifact.
- Structured result panels should narrow evidence in-place. Before sending
  selected nodes back to the host agent, the user needs local search by source,
  gene, variant, and finding inside the exact rendered result they are
  inspecting; this keeps dense evidence maps usable without sending them to an
  obsolete dashboard or a separate utility pane.
- Selection should happen where evidence is inspected, not inside an attachment
  staging shelf. Claude Science's useful pattern is source-surface continuity:
  the user opens a result, file, step output, or provenance pane and continues
  from that concrete object. Genomi can serialize a prompt-safe packet behind
  the scenes, but the UI should expose reports, evidence lanes, artifacts, and
  provenance surfaces rather than packet mechanics.
- Open artifacts should support both immediate reuse and fresh focused
  continuation from the artifact pane itself. If the user selects a specific
  evidence/provenance node in the artifact, `Ask in new conversation` should
  carry that selected slice; otherwise it should carry the artifact summary.

- Users should not need to understand Genomi's internal context and data
  structures. Those contracts still matter to the host-agent bridge, but the
  web UI should translate them into scientific work objects: files, evidence
  lanes, source coverage, work steps, reviews, provenance, and chat. The
  artifact action copied from Claude Science should therefore read `View in
  chat`, not `View context`, even though the implementation still routes through
  an origin-frame context model.
- Evidence packets are an internal contract, not a product noun. The artifact
  library, preview header, generated HTML, and actions should call these
  `Evidence report` / `Open report`, while preserving packet-shaped data
  internally for the host-agent bridge.

## Current Capability Gaps

Claude Science has several artifact-workspace capabilities that Genomi should
not pretend to have yet. The important distinction is hard gap versus partial
equivalent: if Genomi has no product object for the same user job, the UI should
omit the action or mark it unavailable rather than exposing internal context
state as a substitute.

- Hard gaps with no user-facing Genomi equivalent today: artifact cloud export,
  numbered execution-cell logs, full Claude Science-style execution-environment
  snapshots, asynchronous reviewer/check-run lifecycles, rich project Library
  session/folder grouping, PDF annotation/search, and full notebook execution
  or notebook-history workflows.
- Partial equivalents that must not be overclaimed: artifact provenance tabs,
  workspace artifact routes, Evidence-report `Code` rebuild recipes,
  artifact Work Trail cards, version-owned Environment snapshots,
  version-owned deterministic Review checks plus completed review-run history,
  and `View in chat`. These are
  useful Genomi surfaces, but they are not full parity with Claude Science's
  downloadable Code, Execution Log, Environment, async reviewer lifecycle, and
  exact `View in context` behavior.
- Direct `View in chat` navigation is implemented for stored producing runs
  through `highlight_run`, and now uses `highlight_step` when the artifact
  version has a persisted producing execution-cell anchor. Exact producing-step
  highlighting is therefore available for Genomi-owned artifacts with
  `producing_work_step.execution_cell.id`; artifacts without that backed state
  still fall back to the broader producing run.
- Workspace files now have a first step toward the Library target: the portal
  classifies opened files as Markdown, Code, Image, Table, Data, Text, PDF
  document, Notebook, or File, groups project files by project-relative folder,
  separates browser-imported files from assistant-generated records, renders
  Markdown and CSV/TSV tables as readable research records, opens PDFs through
  a project-scoped document frame, and renders notebooks as bounded cell
  outlines. This is not yet full parity with a scientific file library, but it
  prevents common research records from feeling like generic attachments.
- Ready public rebuild recipes now have a version-scoped `Download rebuild
  script` action. The ZIP is deliberately narrow: `rebuild.sh`,
  `rebuild-recipe.json`, `manifest.json`, and README, and it appears only when
  the saved public recipe can be replayed without redacted private inputs.

The remaining gaps should be implemented later as first-class artifact/workspace features.
They are not reasons to revive `/start`, and they should not be approximated by
showing raw context payloads to the end user.

The tracked backlog with screenshot references and implementation notes lives
in `capability-gap-backlog.md`.

## Design North Star

The Genomi web UI should feel like a scientific command center with chat at the
center, not like a dashboard with a chat box bolted on.

The user writes in the portal. The host agent reasons. Genomi tools produce
evidence. The portal shows the transcript, work trace, artifacts, and
provenance as one local, replayable research workspace.

## Run-Time UX Evidence

A live portal chat exercise against the web-owned `/api/runs` path showed that
the basic loop works: browser-facing run creation, CSRF protection,
Genomi-owned workspace metadata, Claude host-agent execution, Genomi evidence
retrieval, persisted messages, execution cells, and result packages all
completed for a public CYP2C19/clopidogrel question.

The same run also exposed product rules that should guide the next UI pass:

- Public-only versus active-genome use must be a visible request boundary. If a
  user asks for public-only evidence while an active genome is available, the
  portal should make that state explicit before run creation rather than
  relying on the assistant to recover after an initial active-context call.
- Host-agent setup, skill loading, tool discovery, raw Bash inspection, and
  oversized-output recovery are technical provenance, not normal research
  steps. They belong in technical disclosure, while the default Work Trail
  should show evidence lookups, artifacts, review results, and final run state.
- If a technical recovery step extracts a durable Genomi operation headline,
  promote that operation into the visible trail. Show `Medication-response
  review`, not `Bash`, `ToolSearch`, or a raw `mcp__...` wrapper.
- Oversized Genomi result handling should become a portal artifact/evidence
  rendering problem. A user should see a concise evidence report with expandable
  sources, not the host agent's saved-output recovery choreography.

## Default Workspace Copy Rules

The portal should name the user's current object and next useful action, not a
generic state machine.

- Genome header: show the active genome identity, build/source/profile, and
  Switch/Add actions. Do not show generic `ready`, `not ready`, or
  `query-ready` labels in the default header.
- Composer genome evidence mode: do not ask the user to choose `Public sources`
  versus `Use active genome when relevant` on every turn. The active genome is
  visible as workspace state; the user should ask naturally, and the host
  prompt should receive the privacy boundary without exposing routing controls.
- Workspace rail: show the current workspace and conversations. Keep local
  assistant status collapsed as support/troubleshooting unless the assistant is
  blocking the user's turn.
- Workspace switching: default to the current/recent workspaces plus search.
  Large local project inventories should not become a long visible sidebar.
- Work trail: count visible research steps only. Diagnostics, host-agent setup,
  tool discovery, stdout/stderr, and recovery mechanics belong in technical
  disclosure; permission requests stay visible because they require action.
- Permission approval: show the access being granted in product language
  (`Read current Genomi context`, `Add a genome source`, `Build an evidence
  packet`) and keep raw MCP tool ids in technical details and server retry
  payloads only. Treat permission as a paused user decision, keep the request
  expanded, state its scope, and resume the same turn without duplicating the
  user message.
- Chat header: primary actions should be conversation work. Exports and bundles
  belong under a secondary menu unless the user is on an artifact/download
  surface.
- Current evidence: users attach evidence to the next chat turn. Avoid generic
  `Use evidence` wording because it reads like hidden context machinery rather
  than a visible research object.
- Composer attachments: show a compact file, artifact, evidence, work-step, or
  review-finding identity with remove. Keep previews, provenance, source limits,
  recommendations, and continuation actions in the object surface where the
  user selected it; do not duplicate them as a card inside the composer.
- Conversation review: treat reviewer findings as claims linked back to the
  transcript. Count successful checks quietly and surface warnings, errors, or
  inconclusive findings. Do not merge this object with deterministic artifact
  checks or display internal field names as reviewer evidence.
