# Subagent Alignment Actions

Date: 2026-07-03

## UX Alignment Thesis

Genomi should reproduce the source portal pattern as a research workspace, not
as a copy of another product's internals. The transferable UX is that the
browser feels like the agent's natural working surface because it renders
durable project state: conversation, work steps, files, artifacts, evidence,
provenance, review state, reproducibility state, and privacy boundaries. The
non-transferable parts are implementation labels, route ids, execution storage,
schema forms, raw context packets, and any capability that Genomi does not yet
own as a user-facing object.

The current portal is structurally close. `portal.html` opens with `Research
workspace` and `Files & Artifacts`, keeps `Current evidence`, `Work trail`,
`Genome state`, and `Evidence sources` under secondary workspace details,
and routes source preparation through `Evidence source` actions instead of direct
browser-side MCP calls. Artifact templates already expose a split pane with
Preview, Provenance, Origin chat, Work trail, Review, Rebuild recipe,
Environment, and Technical details, while the file workspace separates uploads,
produced files, generated artifacts, and read-only workspace files.

The remaining alignment work is disclosure discipline. Every visible panel,
chip, tab, and action should answer a user question: What did I ask? What did
the assistant do? What evidence exists? What artifact was produced? Can I
reopen, reuse, rebuild, review, or download it? Is genome access ready and
approved? Internal structures are still valid behind the server and host-agent
boundary, but the normal UI should show research objects and object-local
actions. If the only reason a surface exists is to display operation ids,
schema shapes, context packet mechanics, adapter output, or raw JSON, it
belongs in technical disclosure or backlog docs.

Treat partial equivalents honestly. `Work trail` is the right current label
until Genomi has stable execution cells with command source, environment labels,
stdout/stderr panes, artifact-version links, and exact producing-step routes.
`Rebuild recipe` is the right current label until Genomi has version-owned
script bundles. `Environment` should explain artifact reproducibility and source
limits, not become a generic machine audit. `Evidence sources` should stay a
secondary source-preparation surface that collects friendly inputs and hands the
request to chat; it must not become a primary tool catalog or operation picker.

## Independent Subagent Consensus

Three independent passes were run against the source research-workspace
patterns, the Open Design daemon bridge, and the current Genomi portal code.
Their shared conclusion was:

- The product shell is aimed correctly: browser-owned chat, local-server-owned
  run/project state, host-agent work behind that server boundary, and durable
  files/artifacts beside the transcript.
- The main remaining UX failure mode is internal disclosure, not layout. Normal
  users should not see frame/run ids, packet keys, raw operation ids, schema
  fields, stdout/stderr chatter, or route/debug state as product objects.
- Artifact panes are justified when each pane answers an artifact-local
  question: preview, provenance, origin chat, work trail, review, rebuild,
  environment, or technical details.
- Evidence sources remain valuable only as a secondary source-preparation
  surface that routes back through chat.
- Gaps should be recorded instead of faked: full execution logs, script
  bundles, async check-run lifecycle, generated-session library grouping, and
  side-chat/fork/handoff APIs all need stronger backing contracts first.

Immediate alignment edits from this pass:

- Origin chat no longer shows the producing frame as a visible metric.
- Origin chat selected values no longer expose raw message ids, run ids, or raw
  event payloads.
- Origin chat humanizes operation ids such as `variant.resolve` into user-facing
  work labels.
- Host-agent stdout/stderr stream chunks no longer render as transcript tool
  chips; they stay durable run diagnostics for Work trail/package views.
- Prompt composition now calls browser attachments `selected portal material`
  instead of over-narrowing every attachment to evidence.

## Independent UX Comparison Pass, 2026-07-03

Three further subagents reviewed the current portal against the stored
research-workspace captures, Open Design's daemon bridge, and Genomi's own
domain rules.

Consensus:

- The architecture is on the right track: browser chat is the product surface,
  the local server owns project/run state, the host agent owns reasoning, and
  run events/project events/artifacts are durable server-owned objects.
- The remaining risk is product disclosure. Normal UI should not ask the user
  to reason about assistant runtime selection, frame/run ids, raw operation
  names, packet keys, schema fields, renderer ids, stdout/stderr chatter, or
  adapter diagnostics.
- Current evidence must be scoped honestly. A client-side/current-frame ledger
  should read as current or reusable evidence, not as a global authoritative
  evidence map unless it is persisted that way.
- Source preparation should read as `Evidence sources`: source purpose, required
  friendly inputs, coverage/source boundary, privacy boundary, and a chat
  handoff. It should not look like a primary tool picker or schema builder.
- Artifact panes should lead with preview, evidence/sources, origin chat, work
  trail, version identity, review findings, rebuild readiness, runtime/source
  limits, and downloads. Raw version ids, renderer ids, checksums, package
  inventories, and operation payloads stay technical.
- Genomi-specific evidence panels should translate envelope fields into
  researcher-facing language: answer boundary, evidence support, retrieval
  status, coverage and limits, source roles, and evidence-library readiness.
- Domain guardrails are UI state: no PRS absolute-risk overclaim without
  calibration, no ancestry identity/percentage overclaim from weak reference
  context, no diagnosis/carrier conclusion from raw variant inventory, no
  causal gene claim from GWAS mapped genes alone, and no medication
  actionability from genotype alone.

Immediate alignment edits from this pass:

- The scoped evidence ledger is labeled `Current evidence`.
- Current evidence is now frame-scoped in the browser controller. Opening a
  conversation sets the ledger scope, rebuilt stored tool results are filtered
  to that frame, and mismatched records are ignored defensively.
- The secondary source-preparation pane is labeled `Evidence sources`.
- The assistant runtime selector is behind an `Assistant runtime` disclosure.
- Generic operation fallbacks now say `Genomi work` instead of `Genomi tool`.
- Legacy `decode.*` operation namespaces are translated to report language
  instead of user-facing Decode vocabulary.
- Evidence status metrics now use `Answer boundary`, `Evidence support`, and
  `Retrieval status`.
- The normal evidence boundary lane is labeled `Coverage and limits`.

New priorities:

1. Keep assistant/runtime selection out of the default path unless the user is
   configuring or debugging a host agent.
2. Persist the evidence ledger per frame or keep it clearly scoped as current
   evidence.
3. Demote raw result traces and raw artifact identity fields into technical
   disclosure or convert them into normalized Work trail cards.
4. Rename/reframe artifact `Provenance`, `Review`, and `Environment` panels
   around the actual backed object: evidence and sources, real review checks,
   and runtime/source limits.
5. Keep Open Design's bridge lesson architectural: all web, CLI, MCP, fork, and
   side-chat routes must use the same server-owned run/result-package contract.

## Alignment Table

| Source-pattern concept | Genomi equivalent | Current state | Required change | Priority |
| --- | --- | --- | --- | --- |
| Project session with chat as the working surface | `Research workspace`, project/frame runs, persisted messages | Primary nav and composer are in place; browser posts through server-owned run paths. | Keep chat as the only normal assistant entry point; do not add parallel browser tool execution. | P0 |
| Files and generated outputs as durable workspace objects | `Files & Artifacts`, artifact library, workspace files | Artifact library, uploads, produced files, generated artifacts, assistant-turn generated-output groups, workspace-file preview/search, and bundles exist. | Add richer session/folder grouping later; keep local paths and backend roots hidden. | P1 |
| Compact work-step stack in the transcript | `Work trail` and message-level work groups | Work trail renders tool/message steps and a partial execution-cell slice. | Continue using `Work trail`; add stable execution-cell records before using full execution-log language. | P0 |
| Artifact split pane with object actions | Artifact preview shell, action menu, version selector, copy link, local downloads | Preview, use artifact, view in chat, provenance, bundle download, technical metadata, rename/hide/star/delete exist; review summary appears only when review state exists. | Keep normal actions object-local; group technical metadata under advanced/technical sections. | P0 |
| Artifact provenance beside the artifact | Artifact details, Origin chat, Work trail, Review, Rebuild recipe, Runtime & source limits | Artifact details carries version/status summary; technical details are modeled separately; Review is gated on real artifact-version review state. | Keep evidence/source lineage distinct from generic artifact metadata; make exact producing-step links a backlog item until execution cells are stable. | P1 |
| Rebuild/code provenance | `Rebuild recipe` | Public-input rebuild readiness and limits exist; technical command recipe is secondary. | Do not present as downloadable script parity until version-owned script bundles and dependency manifests exist. | P1 |
| Execution log and stdout/stderr detail | `Work trail` diagnostics | Partial normalized cells appear in conversation work trail; artifact work trail remains message-derived. | Collapse diagnostics by default; backlog full execution-cell log with route anchors and artifact-version links. | P0 |
| Environment provenance | Artifact `Runtime & source limits` and `Runtime & sources` technical detail | Minimal runtime, library, package availability, source/runtime facts exist. | Show only reproducibility/source-limit facts by default; keep package inventories and machine details technical. | P1 |
| Review/check state | Artifact `Review` | Deterministic version checks render when attached to an artifact version. | Do not imply async check-run lifecycle; backlog user-triggered checks with status history. | P1 |
| Source preparation without tool-console feel | `Evidence sources`, `Evidence source`, friendly input builders | Curated evidence-source catalog and request builder use friendly labels and chat handoff actions. | Keep secondary; hide operation ids, parameter JSON, dependency contracts, and schemas behind technical disclosure. | P0 |
| Selected material routed back to the assistant | Composer `Attached material` and object-specific ask/draft actions | Context model labels artifacts, evidence, genome state, evidence sources, and work trail. | Keep visible chips object-based; never surface `context_kind`, `source_operation`, raw selected payloads, or ids as product text. | P0 |
| Genome/privacy boundary | `Genome state` | Readiness, approval, build, and privacy boundary render first; technical state is collapsible. | Keep registry counts, response profiles, endpoints, paths, and raw context JSON in technical state only. | P0 |
| Evidence lanes attached to answers | `Current evidence`, evidence panels, evidence ledger | Current evidence panels show coverage, observations, defaults, and selectable evidence nodes; suggested follow-up is static. | Clarify whether ledger is current-frame persisted evidence or transient current evidence; avoid selectable policy/guidance rows. | P1 |
| Unified local server bridge | Portal run APIs, run stream, project event stream, sidecar run controls | Browser, sidecar, run event pages, project events, and result packages are converging on one server-owned contract. | Continue convergence; do not add CLI/MCP chat backends that bypass project/run/result-package state. | P1 |

## What Not To Expose To Users

Keep these out of normal UI, selected chips, tab titles, empty states, and
assistant-visible product copy:

- Context packet mechanics, raw selected payloads, `context_kind`,
  `source_operation`, tool-call ids, result ids, frame/run/artifact ids as
  labels, and route-state details.
- Raw tool schemas, parameter JSON, dependency contracts, default metadata,
  output shapes, operation ids, renderer ids, adapter ids, and MCP routing
  mechanics.
- Raw Active Genome Index paths, backend workspace roots, local snapshot paths,
  registry files, response profiles, endpoint details, and debug JSON.
- Host-agent setup chatter, stdout/stderr dumps, adapter diagnostics, package
  inventories, and machine/runtime audits outside collapsed work-trail or
  technical detail.
- Persistent next-question panels, tool pickers as primary workflow, dashboard
  or decode-first vocabulary, and any action that implies a missing capability
  exists.

## Panel Rationale

Every artifact-page panel must justify itself as a user-facing artifact
question:

- Preview: What did this artifact produce?
- Provenance: Which evidence, source lanes, observations, and limits led to
  this artifact?
- Origin chat: What bounded conversation slice produced it?
- Work trail: What visible assistant/tool work led here?
- Review: What checks, warnings, or review limits are attached to this version?
- Rebuild recipe: Can this artifact be reconstructed from saved public inputs,
  and what is missing or redacted?
- Runtime & source limits: What runtime, library, and source-boundary facts matter for
  understanding or reproducing this artifact?
- Technical details: What advanced metadata helps debugging without becoming
  the normal artifact story?

Every project-page panel must justify itself as a user-facing workspace
question:

- Research workspace: What am I asking and what did the assistant answer?
- Files & Artifacts: What files and outputs exist in this project?
- Workspace files: What project-relative files were imported or produced, and
  which have artifact snapshots?
- Current evidence: What current answer evidence can I inspect or reuse?
- Work trail: What did the assistant do in this conversation?
- Genome state: Is genome context available, approved, ready, and private?
- Evidence sources: Which evidence source should guide the next request to the
  assistant?

If a panel cannot be phrased this way, remove it from the default workspace,
fold it into technical disclosure, or record it as a backlog gap.

## Backlog Gaps Not To Fake

- Full execution-log parity: stable execution-cell records, command source,
  language/environment labels, stdout/stderr panes, artifact-version links, and
  exact producing-step routes.
- Version-owned script bundles and complete dependency/input manifests for
  artifact rebuilds.
- Cloud artifact export with provider registry, authentication, export jobs,
  and persisted destination state.
- Rich environment snapshots with host-agent process package inventory,
  environment operation history, and execution-cell dependency maps.
- User-triggered or async artifact check runs with empty/running/pass/fail/
  warning histories.
- Generated-session Library grouping, richer folder browsing, file content APIs
  independent of artifacts, and long-running import/watch lifecycle.
- Frame fork, side-chat, and handoff APIs that preserve selected material,
  artifact links, evidence limits, and Active Genome Index approval state.
- Server-emitted portal presentation models for every capability so the browser
  no longer owns capability-specific fallback ladders.

## Applied After This Pass

- Plain user chat turns no longer show an assistant-runtime bridge when no
  material is attached.
- Evidence sources no longer auto-select the first available source; the user
  must intentionally choose a secondary evidence source.
- Artifact Review tabs and `Use review summary` actions now require real
  artifact-version review state.
- Artifact `Environment` is presented as `Runtime & source limits`, matching
  Genomi's current partial backing object instead of implying full execution
  environment parity.
- Genome-state rows are selectable only when an approved, ready Active Genome
  Index can be attached; non-ready states stay static and show the next setup
  or approval action.
- The composer and message transcript use `Attached material` rather than
  selected-context vocabulary. Evidence-source copy uses chat language instead
  of `next question`, and workspace-file empty states no longer expose run or
  snapshot mechanics.
- Genome privacy rows translate registry/access codes into session-approval
  language. Raw registry fields remain available only through technical state.

## Latest Structural Review Items

The thermonuclear maintainability pass found architecture issues that should be
handled as dedicated development slices rather than hidden inside wording
cleanup:

1. Streaming deltas currently persist through full portal state rewrites on
   each chunk. The cleaner shape is: run events/SSE own live output, and the
   assistant message is persisted once when the frame run finishes.
2. Run/frame lifecycle state is split across run service, worker execution, and
   store mutation paths. The cleaner shape is one coordinator/store transition
   API for starting frame runs, starting follow-up runs, and completing runs.
3. Source lookups are still a hand-maintained portal operation catalog. The
   cleaner shape is operation-catalog annotations for source eligibility,
   ordering, display, required inputs, and request UI, with portal source
   lookups reduced to an adapter over canonical metadata.
4. Backend/frontend route contracts and some frontend tests are still too
   source-string driven. The cleaner shape is a route manifest plus rendered
   DOM/API behavior tests instead of tests that calcify implementation names.

## Thermonuclear Maintainability Pass, 2026-07-04

Two independent read-only review agents inspected the current branch after the
Source limits and attached-material cleanup. They agreed that feature direction
is still right, but maintainability risk is now structural rather than wording
level.

Frontend findings:

1. `portal.js` is still a shell-level controller for route state, project
   state, frames, artifacts, workspace files, tool catalog, run streaming,
   selection, and rendering. The cleaner shape is a workspace controller that
   produces one workspace snapshot, with renderers consuming that snapshot.
2. Artifact panels independently rediscover display, version, runtime,
   environment, and reproduction source state. The cleaner shape is one
   canonical artifact projection consumed by panel models.
3. Tool-result presentation has become a scattered boolean state machine. The
   cleaner shape is a single presentation descriptor with state, renderer,
   attach policy, follow-up policy, and redaction note.
4. Messages, frame trace, and execution-cell slices duplicate event
   normalization. The cleaner shape is one `WorkStep`/`ToolRecord` model used
   by transcript and work-trail views.
5. Frontend prompt-safety and panel-node helpers are copied across modules.
   The cleaner shape is shared frontend model utilities for safe text, safe
   values, metrics, sections, and nodes.

Backend findings:

1. `portal_store.py` is a 1k+ line catch-all for projects, frames, messages,
   artifacts, versioning, run recovery, stale-run rewriting, and project event
   emission. The cleaner shape is separate project/frame repository, artifact
   repository, run-state service, stale-run recovery, and event publisher.
2. Run events, project events, and durable run logs duplicate append/replay/SSE
   mechanics. The cleaner shape is one portal event-log abstraction with
   run/project-specific path and sanitizer hooks.
3. Route contracts are split between `portal.py`, partial URL builders, and raw
   route strings in tests. The cleaner shape is a named endpoint registry that
   owns method, template, handler, and URL builder.
4. Run-start/cancel state is loose dict branching across service, HTTP, and MCP
   layers. The cleaner shape is typed result enums plus one HTTP/MCP adapter.
5. Source lookup and result presentation are drifting into hand-written
   operation catalogs. The cleaner shape is operation/capability-owned
   declarative metadata plus small registries.

Priority:

- Keep feature development moving, but the next structural slices should start
  with canonical artifact projection or the backend event-log/store split.
  Those two changes remove the most repeated branching without changing the
  product direction.
