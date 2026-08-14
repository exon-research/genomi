# Web UI UX Comparison And Alignment

Date: 2026-07-03

This note synthesizes the independent subagent pass over the Claude Science
workspace captures, the Open Design daemon bridge, and the current Genomi portal
implementation. It is intentionally about end-user experience and product
boundaries, not a line-by-line implementation plan.

## Core Finding

The target UX is not `/start`, a setup wizard, a tool console, or the old
Decode dashboard. The target UX is a post-onboarding research workspace where
the browser feels like the agent surface because it renders durable project
state: conversation, run activity, files, artifacts, evidence lanes, provenance,
review state, and genome/privacy boundaries.

Genomi should use its own context and data structures, but users should not
have to understand those internals. They should see research objects and
object-local actions, not context packets, raw schemas, routing mechanics, or
manual tool wiring.

## Independent Alignment Pass

Three independent subagents reviewed the reference workspace captures, the
Open Design daemon bridge, and the current Genomi portal implementation. The
combined finding is that the current direction is structurally right, but the
remaining risk is over-exposing internal machinery in normal UI.

Keep as product direction:

- `Research workspace` and `Files & Artifacts` remain the two primary surfaces.
- Evidence, Work trail, Genome state, Review, Rebuild, Environment, and source
  lookup setup are valid only when they explain or reuse a research object.
- Browser chat submits user intent and typed selected material to the server;
  server-side code owns prompt/context composition, host-agent invocation,
  selected-material sanitization, persistence, and stream normalization.
- Web, future CLI, and future MCP sidecars should converge on the same
  project/run/result-package contracts rather than building parallel chat
  routes.

Treat as UX mismatches to fix:

- Genome state should default to readiness, approval, build, and privacy
  boundary. Registry counts, response profile, MCP endpoint, context axes,
  local paths, and raw JSON are diagnostics.
- Active browser context should be orientation, not evidence. Normal prompts
  should use user-facing object handles and selected material before route,
  frame, artifact, or version ids.
- Evidence sources should read as source preparation, not a schema or
  operation console. Operation ids, dependency contracts, defaults, and JSON
  params belong under expert disclosure.
- Composer-visible selected material should use friendly evidence labels. Raw
  `source_operation`, `context_kind`, ids, and payload fields stay in typed
  transport or technical details.
- Artifact panes should lead with preview, provenance or evidence, origin chat, work trail,
  review findings, rebuild readiness, environment limits, version identity, and
  downloads. Renderer ids, operation params, shell commands, checksums, and
  package inventories are technical details.
- Prompt starters and empty states must be gated by live typed state. A
  genome-specific suggestion should not imply personal genome access before a
  ready and approved genome context exists.
- Host-agent progress, setup output, stdout/stderr, and adapter chatter should
  render as work-trail or diagnostic state, not assistant answer prose.

The resulting `AGENTS.md` rule is: every normal portal surface must map to a
research object the user understands. If the UI control exists mainly to expose
routing, packet assembly, operation choice, schema shape, debug state, or ids,
it belongs behind technical disclosure or in backlog docs, not in the default
workspace.

## Subagent Comparison Pass

Date: 2026-07-03

Three independent subagents compared the current Genomi portal against the
reference science-workspace captures and the Open Design daemon bridge. The
combined conclusion was consistent:

- Genomi's top-level workspace shape is right: browser-owned chat, local
  server-owned project/run state, host-agent work behind the server boundary,
  primary `Research workspace` plus `Files & Artifacts`, and secondary details
  for evidence, work trail, genome state, evidence sources, and artifact
  provenance.
- The main remaining UX bug is disclosure level. Several normal UI surfaces
  still read like a schema form, MCP recipe, or operation trace instead of a
  research workspace object.
- Evidence sources should stay secondary and should present source purpose,
  required user inputs, source/privacy boundary, and a chat handoff action. Raw
  parameter names, defaults, produces/output shape, dependency contracts, and
  operation ids belong in technical disclosure.
- Rebuild should remain a user-facing reproducibility object, but the primary
  view should lead with rebuild readiness, public inputs, and limits. Shell
  commands, operation ids, renderer ids, parameter JSON, and host-agent handoff
  details belong in technical details.
- Evidence surfaces should show readable evidence language in normal badges and
  metrics. Raw envelope/status codes remain valid typed payload for the host
  agent and technical diagnostics, but should not be the default product copy.
- Artifact origin chat, environment, and metadata actions are justified, but
  frame/run ids, raw event names, package inventories, and machine details must
  remain secondary.
- The old dashboard/decode vocabulary can remain only as compatibility or
  historical documentation; it should not drive the new workspace product
  language.

Implemented immediately after this pass:

- Reset/welcome suggestions now use the same public-first wording as the static
  portal template.
- Evidence report artifact summaries no longer include operation counts as a
  product summary line.
- Evidence report HTML and frontend evidence badges/metrics render readable
  state text instead of raw status-code copy.
- Rebuild recipe models now separate primary readiness/input/limit sections
  from technical shell commands, operation ids, renderer ids, and host-agent
  handoff details.
- Evidence-source fields now use friendly labels and default wording in the
  visible form while preserving raw parameter keys in typed payloads.

Recorded as future work, not current UX:

- Normalized execution-cell records and CLI wrapping around the base sidecar
  operations that can start, poll, cancel, page events, and package portal runs
  through the same server contract.
- Server-emitted portal presentation models so the browser no longer owns
  capability-specific evidence schema ladders.
- Normalized execution-cell records with stdout/stderr, command source,
  language/environment labels, and producing artifact links.
- Host-agent adapter/injection contracts that make Genomi skill/MCP setup
  explicit per run.
- Frame fork, side-chat, and handoff APIs using the same selected-material and
  Active Genome Index approval model.

## UX Recheck Subagent Pass

Date: 2026-07-03

Three follow-up subagents compared the current Genomi portal, the stored
workspace screenshots/fixtures, and the Open Design daemon bridge. Their
consensus:

- The top-level Genomi shell is aligned: browser chat posts to the local
  server, the server starts host-agent work, run events and project events are
  separate planes, and files/artifacts are durable workspace objects.
- The remaining product risk is disclosure level. Normal UI must show research
  objects and object-local actions, not tool schemas, raw envelope policy,
  context-packet mechanics, operation ids, or adapter diagnostics.
- Evidence sources should stay secondary and read as source/evidence
  preparation. They should show purpose, required friendly inputs, and privacy/source
  boundary; raw schema fields, defaults, dependency contracts, operation ids,
  output shapes, and parameter JSON belong in technical disclosure.
- Evidence panels should expose readable answer state, source coverage,
  observations, source lanes, and follow-up actions. Raw guidance codes are
  typed policy for the host path and should not become selectable evidence
  nodes.
- Artifact primary views should lead with preview, readable provenance, origin
  chat, work trail, review state, rebuild readiness, source/environment limits,
  and version identity. Checksums, package inventories, machine details,
  renderer ids, operation ids, command recipes, and raw file URLs belong under
  technical details.
- Host-agent stdout, stderr, startup chatter, and adapter dumps should render
  only as collapsed work-trail diagnostics. The normal transcript should show
  assistant text, compact work steps, artifacts, files, and evidence summaries.
- Open Design's useful architectural lesson is the daemon bridge: browser
  -> local server run API -> host-agent process -> normalized events/artifacts.
  MCP/CLI sidecars should proxy the same portal run/result contracts rather
  than becoming separate chat transports.

Immediate alignment edits from this pass:

- Added stricter portal-copy and disclosure guidance to `AGENTS.md`.
- Changed evidence-source prompt/payload text to render friendly input labels
  instead of user-visible parameter JSON.
- Added `/api/source-lookups` as a server-owned source lookup presentation
  model. The browser now consumes curated lookup cards with purpose, friendly
  inputs, boundary copy, and technical disclosure instead of using raw operation
  discovery as the product catalog.
- Removed raw guidance-code sections from normal evidence/result panels.
- Demoted artifact checksum/content-type/size from primary provenance to
  technical details.
- Cleaned visual-inspection fixtures that still presented attached material as
  packets or logged `context_kind` / `source_operation` as visible output.

Remaining implementation backlog:

- Server-emitted portal presentation models so the browser stops owning
  capability-specific field ladders.
- Normalized execution-cell records before using execution-log language.
- Normalized execution-cell records and user-facing CLI wrappers around the
  existing start, poll, cancel, event-page, and package base operations.
- Split host-agent stdout/stderr and adapter chatter out of normal transcript
  work chips into collapsed work-trail diagnostics.
- Clean artifact primary tabs further so review/provenance lead with checks,
  warnings, limits, origin chat, and human version identity; keep operation ids,
  renderer ids, raw file URLs, and handoff briefs in technical disclosure.
- Quarantine legacy decode/dashboard compatibility from new portal product
  language.

Browser verification from the same slice:

- Fresh `genomi serve --transport http --host 127.0.0.1 --port 8781` rendered
  the default project shell as `Research workspace` plus `Files & Artifacts`,
  with no `/start` route.
- The browser verified `/api/source-lookups` returns
  `surface="source_lookup_setup"`, curated cards, friendly fields such as
  `Genome source`, `Genome build`, `Reference FASTA`, `Search text`, and
  `Index source`, and no `inputSchema` or `genomi.install` entry.
- After navigation hardening, a fresh browser tab opened
  `/#tool-launcher`, restored the secondary source setup pane, loaded the
  curated catalog, and opened on `Add genome file`.
- Screenshot checkpoints:
  `screenshots/20260703-genomi-portal-source-lookup-shell.png` and
  `screenshots/20260703-genomi-source-lookup-catalog.png`.

## Reference Science Workspace Pattern

Relevant screenshots:

- `screenshots/127-claude-science-project-session-workspace.png`
- `screenshots/128-claude-science-desktop-session-and-files-pane.png`
- `screenshots/129-claude-science-session-step-stack.png`
- `screenshots/132-claude-science-artifacts-split-pane.png`
- `screenshots/134-claude-science-artifact-actions-menu.png`
- `screenshots/135-claude-science-artifact-provenance-code-tab.png`
- `screenshots/136-claude-science-artifact-provenance-execution-log-tab.png`
- `screenshots/137-claude-science-artifact-provenance-messages-tab.png`
- `screenshots/138-claude-science-artifact-provenance-environment-tab.png`
- `screenshots/139-claude-science-artifact-provenance-review-tab.png`
- `screenshots/164-claude-science-project-library-files-pane.png`
- `screenshots/175-claude-science-view-in-context-result.png`
- `screenshots/176-claude-science-view-in-context-work-step-visible.png`

UX lessons:

- The primary surface is a project session: chat on one side, files/artifacts
  and generated outputs as durable workspace objects.
- The transcript interleaves assistant prose with compact grouped work steps.
  Users can expand work detail, but the default reading path is still the
  answer.
- Artifacts are not just downloaded files. They are workspace objects with
  preview, actions, versions, provenance, origin messages, environment, review,
  and navigation back to the producing chat context.
- Provenance is adjacent to the artifact. The user does not hunt through raw
  logs or debug JSON to understand where an artifact came from.
- The useful object model appears after onboarding. The `/start` setup flow is
  not the Genomi portal model.

## Open Design Bridge Pattern

Open Design shows the architectural bridge Genomi should mirror:

```text
Browser chat
  -> local daemon HTTP API
  -> daemon creates a run
  -> daemon starts or resumes the selected host-agent CLI
  -> host agent uses injected skills, MCP tools, and workspace context
  -> daemon parses host-agent output
  -> daemon persists run, messages, files, artifacts, and events
  -> browser consumes normalized SSE events and refetches public state
```

Source anchors from `/Users/matthewzmd/code/open-design`:

- `apps/web/src/providers/daemon.ts`: builds the daemon transcript, posts run
  requests, handles `runId`, and consumes run SSE.
- `apps/daemon/src/routes/runs.ts`: owns `POST /api/runs`,
  `GET /api/runs/:id`, `GET /api/runs/:id/events`, cancel, and result package
  routes.
- `apps/daemon/src/runtimes/runs.ts`: creates run records, assigns event ids,
  fans events to SSE clients, supports reconnect with `after`, and optionally
  writes run event logs.
- `apps/web/src/providers/project-events.ts`: keeps project-level file,
  artifact, and conversation refreshes separate from active run streaming.
- `apps/web/src/components/workspace/useConversationChat.ts`: secondary chat
  surfaces still reuse the same daemon stream primitive.
- `apps/daemon/src/runtimes/defs/claude.ts` and
  `apps/daemon/src/runtimes/defs/codex.ts`: host-agent adapters keep binary
  invocation, argument construction, stream behavior, and MCP injection out of
  the browser.

Genomi implication: the portal browser should not call MCP tools or a host-agent
CLI directly. It should submit user text plus typed selected material to the
local Genomi server. The server owns prompt/context composition, host-agent
invocation, Genomi MCP/skill injection, state persistence, and event streaming.

## Genomi Alignment Rules

Default user surfaces:

- Research workspace conversation.
- Files and artifacts.
- Artifact preview and object actions.
- Composer-attached material.
- Evidence maps and source lanes when they explain an answer or artifact.
- Work trail summaries when they explain what the host agent did.
- Genome readiness, approval, and privacy state when it materially affects the
  task.
- Artifact version identity, review state, rebuild limits, environment summary,
  uploads, produced files, and local downloads.

Secondary or contextual surfaces:

- Origin chat.
- Work trail detail.
- Evidence ledger/detail views.
- Genome state detail.
- Tool-call detail.
- Evidence sources.
- Technical details.

Keep out of normal UI:

- Raw selected payloads.
- Context packet mechanics.
- MCP routing mechanics.
- Raw tool schemas.
- Debug JSON.
- Local filesystem roots.
- Raw Active Genome Index paths.
- Raw host-agent payloads.
- Route ids as labels.
- Standalone "next question" panels.
- Install/onboarding flows that belong in Genomi setup, not the project
  workspace.

## Controls Must Earn Their Place

Every selectable panel or control should map to an object users understand:
file, artifact, evidence/source lane, work step, provenance node, genome
summary, review finding, or attached material.

Use object-local action labels:

- `Ask selected`
- `Draft selected`
- `Use`
- `View in chat`
- `Re-check`
- `Copy link`
- `Download`
- `Export metadata`

Avoid product surfaces whose purpose is really internal routing:

- "select evidence packet"
- "context packet"
- "next question"
- "pick a tool"
- operation id as the visible label
- arbitrary debug/state panels

## Browser Boundary

The browser should render typed state and collect user intent. It should not be
a second host-agent policy engine.

Allowed browser inputs to the server:

- User text.
- Selected file, artifact, evidence-node, work-step, review, or genome-summary
  handles.
- Current visible route and active workspace pane as orientation.
- Explicit approvals or user-selected options.

Server-owned responsibilities:

- Prompt/context composition.
- Selected-material sanitization.
- Evidence interpretation policy.
- Genomi skill and MCP injection.
- Host-agent adapter selection and invocation.
- Run/event/message/artifact persistence.
- Reconnectable run and project event streams.

Do not parse assistant prose, Markdown headings, or checklist text into durable
portal state. If Genomi wants selectable evidence plans or work items, the
server/run layer should emit typed events, artifacts, or presentation models.

## Presentation Boundary

One Genomi result should have one presented shape. Capability-specific
presenters can choose sections and labels, but the browser should not render a
specialized panel and a generic evidence panel as competing primary objects for
the same tool result.

Preferred direction:

- Backend/capability presenters emit a stable portal presentation model.
- The presentation model contains envelope state, evidence lanes, coverage,
  observations, source records, warnings, actions, and materialization state.
- Frontend modules render that model generically.
- Raw capability payloads and schema-specific field ladders move behind
  technical details or backend presenters.

## Independent UX Subagent Pass, 2026-07-03

Three read-only subagents compared the reference science workspace, the Open
Design daemon bridge, and Genomi's current portal surfaces. Their shared
conclusion was that Genomi is structurally aimed at the right product model,
but the normal UI must keep removing implementation vocabulary.

Reference workspace findings:

- The post-onboarding surface is a durable research workspace: chat/composer,
  files, artifacts, provenance, review, environment, and work steps.
- The transcript keeps assistant prose readable while expandable work steps
  carry the technical trail.
- Artifacts are workspace objects with preview, actions, versions,
  provenance, origin messages, environment, review, and navigation back to the
  producing conversation.
- Users act on research objects: files, artifacts, evidence lanes, work steps,
  provenance tabs. They should not manage packets, schemas, ids, or routes.

Open Design routing findings:

- The web UI is a client shell over a local daemon, not a separate LLM client.
- Browser chat creates a run through the daemon; the daemon persists state,
  invokes the selected host agent, injects skills/MCP context, normalizes
  events, and emits files/artifacts.
- Run events and project events are separate planes. Active assistant work and
  durable workspace changes should be independently replayable.
- CLI and MCP sidecars should route through the same daemon/server contracts
  rather than becoming parallel backends.

Current Genomi alignment findings:

- The top-level portal shape is now aligned: Research workspace plus Files &
  Artifacts, with Work trail, Genome state, Current evidence, and source
  lookup setup as secondary surfaces.
- The immediate cleanup target is visible disclosure: hide or humanize paths,
  version ids, operation ids, presentation-state tokens, selected payloads, and
  partial-equivalent claims in normal UI.
- Evidence sources must stay a secondary chat handoff surface. They should not
  become a tool catalog, operation picker, or browser-owned execution path.
- Work trail, Review, Environment, and Rebuild panes should name partial
  equivalents honestly until Genomi has normalized execution cells, review
  lifecycles, rich environment snapshots, and script bundles.

## Focused UX Subagent Pass, 2026-07-03

Three additional subagents independently reviewed the workspace pattern,
Open Design bridge, and current Genomi portal implementation.

Consensus:

- The target product is still the post-onboarding research workspace, not
  `/start`, not the old Decode dashboard, and not a browser-side tool console.
- Open Design's transferable pattern is architectural: browser chat creates a
  local server run, the server invokes the host agent and owns prompt/context
  composition, run events stream back to the browser, and CLI/MCP sidecars use
  the same run/result contracts.
- Genomi's top-level shell is now structurally aligned: `Research workspace`
  plus `Files & Artifacts`, secondary workspace details, separate run/project
  event planes, and sidecar operations over the same run service.
- The main remaining UX risk is disclosure bleed-through. Technical rows,
  envelope policy state, operation ids, renderer ids, command recipes, paths,
  and follow-up policy must not become ordinary selectable evidence.
- Evidence sources should read as chat-routed source preparation, not as a tool or
  schema picker. The browser should collect friendly inputs, then ask the
  server to prepare the chat prompt and selected-material packet; raw operation
  identity remains typed transport or technical disclosure.

Immediate changes made from this pass:

- Artifact technical-detail rows now render as static inspection rows, not
  selectable evidence nodes. `Select all` only targets selectable research
  material.
- Result `Coverage and limits` rows and evidence-panel suggested follow-up rows now
  render as static context/action state rather than selectable source evidence.
- Result fallback context excludes nonselectable policy lanes.
- Evidence-source actions now use product actions: `Use in chat`,
  `Draft question`, and `Ask with source`. The browser no longer composes
  evidence-source prompts or selected-material packets for the portal flow; it
  calls `/api/evidence-sources/attach` and receives server-owned chat handoff
  material.
- Evidence-source rows use `Choose` / `Selected`, so the list reads as a
  source-preparation surface rather than a tool browser.
- `AGENTS.md` now has source-neutral guidance that selectable material must be
  research material, and source preparation surfaces must not read as schema or
  operation wiring.

Immediate product-copy changes from this pass:

- The secondary preparation surface is named `Evidence sources`, while
  object-local actions and attachments use `Evidence source` language.
- Work-step summaries no longer prefer local paths, file paths, or version ids.
- Persisted work-trail state renders as readable saved-history language rather
  than raw presentation-state tokens.
- Evidence-map summary lines use evidence titles and readable states instead
  of raw operation ids.
- Saved evidence actions say `Re-check evidence` rather than a generic
  follow-up action.
- Persisted or display-only saved history attaches to chat as `Saved evidence`
  to re-check. User-facing follow-up copy must not expose workflow-event,
  presentation-state, or packet mechanics for stale history.
- Generic work-trace fallback copy says `Genomi work` / `Work summary`, not
  `workflow event`, because event vocabulary is an implementation detail.

## Current Genomi Status

Aligned or mostly aligned:

- `/start` is not a Genomi portal route.
- The portal opens into project/frame workspace routes.
- The primary shell leads with Research workspace and Files & Artifacts.
- The secondary evidence-preparation surface is labeled as Evidence sources,
  not a raw tool or schema catalog, and normal cards show source/privacy
  boundaries without host-runtime vocabulary.
- The old Decode dashboard is no longer the primary portal flow; legacy decode
  artifacts are translated into report-like artifacts.
- Artifacts have split-pane preview, routes, versions, provenance/review
  surfaces, object actions, local bundles, uploads, and produced-file grouping.
- Run SSE and project event streams exist as separate planes. Project events now
  have bounded durable replay from a sanitized local JSONL log, so refresh and
  restart recovery do not depend only on in-memory project-event state.
- Browser chat submission now has a canonical `POST /api/runs` create path
  that delegates to the existing project/frame run service.
- Base sidecar operations can start, poll, cancel, and package portal runs
  through the same project/frame run service instead of inventing a separate
  chat backend.
- Base sidecar operations can retrieve bounded sanitized run-event pages through
  the same durable run-event contract used by browser replay and result
  packages.
- Tool-result events can carry server-owned `portal_presentation` models, and
  the browser prefers them before falling back to legacy renderers.
- Selected visual context is composer-owned `Attached material`, not a
  standalone next-question or packet panel. The composer tray now previews
  selected evidence/genome facts with friendly labels, source labels,
  selected-item counts, and compact values before the turn is sent.
- Files & Artifacts now supports direct workspace-file inspection: file-only
  outputs can be previewed inline with bounded text/image previews instead of
  requiring artifact materialization first.

Needs correction or discipline:

- Some frontend modules still contain legacy fallback renderers and raw-schema
  request-builder paths. They should remain secondary or move behind explicit
  developer disclosure as backend presenters mature.
- Tool-result rendering still has fallback specialized/generic shapes for
  operations without a server presentation model.
- The source-lookup request builder must stay secondary and always route
  through chat.
- Technical details should behave as expert disclosure. Package inventories,
  machine/runtime details, trust boundaries, operation ids, and raw metadata
  should not sit in normal evidence/source lanes.

## Independent Web UI Alignment Subagents, 2026-07-03

Three independent subagents rechecked the current Genomi portal against the
stored science-workspace captures, the Open Design daemon bridge, and Genomi's
own current implementation.

Shared conclusion:

- Genomi is structurally pointed in the right direction: browser-owned chat,
  local server-owned project/run state, host-agent execution behind the server
  boundary, separate run/project event planes, and Files & Artifacts as durable
  workspace objects.
- The product risk is not architecture now; it is disclosure bleed. Normal UI
  must keep hiding frames, runs, route ids, operation ids, schemas, packet
  mechanics, renderer names, stdout/stderr chatter, and adapter diagnostics
  behind user-facing research objects or technical disclosure.
- The strongest current UX gap was execution/progress. Backend
  `execution_cells` exist in run result packages, and the browser Work trail now
  consumes those cells for non-duplicate diagnostic, stdout/stderr, artifact,
  and run-completion steps. Full execution-log parity still requires stable
  producing-step links, command source, environment labels, and artifact-version
  links.
- Evidence sources are correctly secondary and now use a server-owned chat handoff
  endpoint. They still need more visual polish so the surface reads as
  evidence-source preparation first and only reveals operation mechanics in
  technical disclosure.
- Genome state attach actions now depend on a ready, approved Active Genome
  Index. Empty, blocked, unknown-readiness, and still-building states expose a
  status/action hint instead of `Use selected facts` or `Use genome summary`.
- Persistent next-question panels should stay out. Suggestions belong in the
  composer or object-local actions.
- Artifact UX is mostly aligned: preview, actions, provenance, origin chat,
  work trail, review/rebuild/environment state, versions, and downloads. The
  remaining gap is exact producing-step links backed by normalized execution
  cells.

Reference screenshots used for this pass:

- `screenshots/127-claude-science-project-session-workspace.png`
- `screenshots/129-claude-science-session-step-stack.png`
- `screenshots/132-claude-science-artifacts-split-pane.png`
- `screenshots/136-claude-science-artifact-provenance-execution-log-tab.png`
- `screenshots/164-claude-science-project-library-files-pane.png`
- `screenshots/175-claude-science-view-in-context-result.png`
- `screenshots/208-genomi-current-workspace-ux-subagent-pass.png`
- `screenshots/209-genomi-workspace-details-expanded-ux-subagent-pass.png`

Open Design architecture anchors used for the comparison:

- `/Users/matthewzmd/code/open-design/apps/web/src/providers/daemon.ts`
- `/Users/matthewzmd/code/open-design/apps/daemon/src/routes/runs.ts`
- `/Users/matthewzmd/code/open-design/apps/daemon/src/runtimes/runs.ts`
- `/Users/matthewzmd/code/open-design/apps/web/src/providers/project-events.ts`
- `/Users/matthewzmd/code/open-design/apps/daemon/src/mcp.ts`

Prioritized alignment backlog:

1. Extend the browser execution-cell slice from the conversation Work trail
   into artifact provenance, with stable producing-step links. Stdout/stderr
   and setup chatter should remain collapsed diagnostics instead of assistant
   prose or debug chips.
2. Keep source setup secondary and make visible actions read as source
   preparation/checking, not tool attachment or schema request building.
3. Clarify `Current evidence`: either persist it per frame, fold it into
   Work trail/current evidence, or label it as transient current evidence.
4. Hide artifact tabs unless they represent meaningful artifact state. Preview,
   provenance, origin chat, and work trail are default-worthy; review, rebuild,
   and environment should appear only when they carry actual state or honest
   limits.
5. Keep selected material object-based. Visible chips and actions should name
   evidence, sources, artifacts, files, work steps, review findings, or genome
   facts, while packet fields remain typed transport.
6. Keep genome UI about readiness, build, approval, and privacy first. Registry
   counts, response profiles, endpoints, local paths, and raw context JSON stay
   under technical disclosure.
7. Quarantine legacy dashboard/decode vocabulary. Legacy utilities can render
   reports, but the new portal product language is research workspace,
   evidence, files, artifacts, work steps, review, and reproducibility.
8. Keep host-agent identity out of the default path unless the user needs to
   choose, fix, or inspect the assistant runtime.

## Backlog Gaps Not To Fake

Do not expose weak substitutes for these:

- Cloud artifact export.
- Full normalized execution logs with stable producing-step links, command
  source, environment labels, stdout/stderr panes, and artifact-version links.
- Full execution environment and package graphs.
- Async review/check-run lifecycle.
- Generated-session Library grouping.
- Version-owned script bundles.
- Exact producing-step links.
- Frame fork, side-chat, and handoff APIs.
- Stable execution-cell records, exact producing-step links, and higher-level
  CLI wrappers around the base portal run-control/event-page operations.

## Practical Decision Test

Before adding a portal panel or action, ask:

1. Is this an object a researcher understands?
2. Does it help the user ask the next question, inspect evidence, reproduce an
   artifact, or understand a privacy/approval boundary?
3. Can the server replay this state after refresh?
4. Is it typed state rather than assistant prose or raw debug payload?
5. If this copies a reference-system affordance, does Genomi actually have the
   same user-facing capability?

If the answer is no, keep it behind technical disclosure, omit it, or record a
backlog gap.

## Latest Subagent Comparison Pass, 2026-07-03

Three independent agents rechecked the current branch against the Claude
Science workspace captures, Open Design's daemon bridge, and Genomi's domain
rules.

Findings:

- The bridge pattern is correct: the browser owns the product experience, the
  local server owns run/project state, and the host agent owns reasoning and
  tool use. Genomi should keep web, CLI, MCP, side-chat, and future fork routes
  as front doors into the same server-owned run/result-package contract.
- The main UX mismatch is disclosure level. Assistant runtime selection,
  frame/run ids, operation ids, context packet fields, schemas, renderer ids,
  setup logs, stdout/stderr, and adapter diagnostics are not research objects.
- Current evidence needs honest scoping. Until the ledger is persisted as a
  durable evidence map, the user-facing label should be current/reusable
  evidence rather than a broad evidence authority.
- Source preparation should read as evidence sources, not setup or tool picking.
  Cards should show purpose, friendly required inputs, source coverage, privacy
  boundary, and a chat handoff.
- Evidence panels should translate envelope fields into user-facing labels:
  answer boundary, evidence support, retrieval status, and coverage/limits.
- Artifact panels should appear only when backed by meaningful artifact state.
  Review means real checks/findings or explicit limits; environment means
  runtime/source limits unless a full environment snapshot exists; execution
  log remains backlog until stable execution-cell records support it.
- Applied follow-up: artifact Review tabs and `Use review summary` actions now
  require artifact-version review state, plain chat turns no longer show a
  runtime bridge without attached material, evidence sources no longer
  auto-select the first source, source rows say `Choose`, and the artifact
  environment tab is labeled `Runtime & source limits`.

Applied alignment from this pass:

- `Evidence from this chat` became `Current evidence`.
- `Current evidence` is scoped to the active conversation. Stored tool results
  are replayed from server messages for that frame, and mismatched frame
  records are ignored rather than merging into a cross-conversation browser
  list.
- `Source setup` became `Evidence sources`.
- The assistant selector moved behind an `Assistant runtime` disclosure.
- Generic fallback labels use `Genomi work` instead of `Genomi tool`.
- `decode.*` operation namespaces translate to report language.
- UI evidence metrics use `Answer boundary`, `Evidence support`,
  `Retrieval status`, and `Coverage and limits`.
- Evidence-source selected material stores and renders friendly object labels such
  as `Evidence source: Target evidence report` while preserving the hidden
  `source_operation` contract for host-agent handoff. Raw operation ids stay
  out of the attached-material tray and prompt-only evidence-source text.
- Result views with searchable evidence lanes now support `Select shown` and
  `Clear selected`, so users can filter to a visible evidence subset and send
  exactly those nodes back into chat without accidentally attaching hidden
  filtered-out evidence.
- The primary chat path no longer exposes or submits a runtime selection.
  Runtime readiness remains visible in the rail, detected runtimes are listed
  under secondary details, and normal web turns omit `agentId` so the local
  server selects the default runnable host agent.
- Medication-response tool results now receive a server-owned portal
  presentation with medication rows, evidence roles, sample follow-up, and
  unanswered-component lanes. The browser renders the generic server result
  model and no longer has a `pharmacogenomics.review_medication` raw-payload
  presenter, so the normal PGx science-workspace shape is not inferred from
  tool internals in the client.
- Variant lookup results also render through server-owned
  `genomi_portal_result_presentation` models. The legacy
  `variant.resolve` browser raw-payload presenter was removed, so live and
  persisted variant cards now depend on the same replayable server result
  contract as other first-class workspace objects.
- Target evidence reports now render through server-owned
  `genomi_portal_result_presentation` models in chat. The browser still reuses
  the target-packet model for artifact/report state, but it no longer sniffs raw
  `research.build_target_packet` payloads to produce normal chat-result UX.
  Visible summaries prefer server presentation and ledger text over raw payload
  headlines, keeping operation IDs out of product copy.

Additional implementation backlog:

- Replace browser-owned evidence-source request building with server-owned
  evidence-source setup. The browser should gather friendly intent and required inputs, then
  let the local server select operations, validate/default inputs, and create
  attached-material handles.
- Gate artifact Review/Rebuild/runtime-source-limit surfaces by real persisted state or
  honest limits. Do not show review tabs from generic review instructions.
- Move artifact ids, source operations, renderer names, content types,
  checksums, raw URLs, origin run ids, package inventory, and event ids into
  collapsed technical disclosure.
- Keep Work trail selection user-facing: title, status, summary, and evidence
  relevance only. Run ids, event ranges, stdout/stderr, and diagnostics remain
  collapsed until normalized execution-cell records support full execution-log
  UX.
- Enable genome attach/use actions only when an approved, ready Active Genome
  Index exists; blocked or pending states should show setup/approval status
  only.
- Formal host-agent adapter capability negotiation and runtime injection closer
  to the Open Design daemon model.
- Persisted evidence-map promotion beyond the current-frame `Current evidence`
  model.
- Artifact panel gating so Review/Rebuild/runtime-source-limit panes appear only when backed
  by state or honest limits.
- Server-emitted presentation models for more Genomi capabilities so generic
  fallback panels stop carrying domain UX.

## 2026-07-04 Follow-Up Subagent Pass

Two independent read-only passes rechecked the current portal against the
reference science-workspace pattern and the Open Design daemon bridge.

UX/product priority:

- Durable Work trail records are the highest-value next workspace object. The
  current `Work trail` is useful, but still partly computed from messages and
  events. Do not rename it to `Execution Log` until command source,
  environment labels, stdout/stderr panes, artifact-version links, and stable
  execution-cell records exist.
- Research-session Library grouping is the next file/artifact gap. Files and
  artifacts are previewable, but the Library should eventually group uploads,
  generated outputs, reports, notebooks, PDFs, and code by conversation/run or
  session without exposing backend paths.
- Evidence sources remain a small but important cleanup surface. They should
  read as source cards with purpose, friendly inputs, coverage/source limits,
  privacy boundary, and chat handoff. Operation IDs, schemas, defaults,
  dependency contracts, and parameter JSON stay behind technical disclosure.

Architecture priority:

- The browser path now routes through server-owned run creation and replay, but
  sidecar-started portal runs must not become a parallel owner. Future
  `genomi.start_portal_run` behavior should proxy to the live portal daemon or
  clearly refuse when no daemon is bound.
- More Work trail presentation should move server-side as typed user-facing
  records, while raw event records remain available only as diagnostics.
- Artifact Review/Rebuild actions should stay attached to the same run/result
  package story if they become async or agentic.

Applied follow-up:

- The Evidence sources setup panel now has two distinct actions: `Include
  source` and `Ask now`. The old setup-panel `Use in chat` / `Draft question`
  pair was removed so users do not have to choose among near-duplicate source
  preparation workflows.
