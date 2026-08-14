# Genomi Portal UX Product Rules

Date: 2026-07-03

This note condenses the Claude Science workspace study, the Open Design daemon
comparison, and the current Genomi portal checks into product rules for the
Genomi portal. It is a rule sheet, not another implementation log.

## Source Basis

The rules below are grounded in:

- Claude Science post-onboarding workspace captures:
  `screenshots/127-claude-science-project-session-workspace.png`,
  `screenshots/128-claude-science-desktop-session-and-files-pane.png`,
  `screenshots/129-claude-science-session-step-stack.png`,
  `screenshots/132-claude-science-artifacts-split-pane.png`,
  `screenshots/135-claude-science-artifact-provenance-code-tab.png`,
  `screenshots/136-claude-science-artifact-provenance-execution-log-tab.png`,
  `screenshots/137-claude-science-artifact-provenance-messages-tab.png`,
  `screenshots/138-claude-science-artifact-provenance-environment-tab.png`,
  `screenshots/139-claude-science-artifact-provenance-review-tab.png`,
  `screenshots/164-claude-science-project-library-files-pane.png`,
  `screenshots/175-claude-science-view-in-context-result.png`, and
  `screenshots/176-claude-science-view-in-context-work-step-visible.png`.
- Claude Science public-page captures:
  `screenshots/20260703-claude-science-public-hero-clean.png`,
  `screenshots/20260703-claude-science-public-rich-artifacts-user-supplied.png`,
  `screenshots/20260703-claude-science-public-compute-user-supplied.png`, and
  `screenshots/20260703-claude-science-public-domain-ready-user-supplied.png`.
  The user feedback attached to these captures emphasized that Markdown files,
  images, code, artifact history, reviewer checks, skills, tools, and domain
  database integrations are visible and directly openable inside the science
  workspace.
- Open Design source inspection summarized in
  `chat-routing-and-runtime-state.md`: browser chat posts to a local daemon,
  the daemon creates and streams runs, host-agent work happens behind that
  boundary, and project events/files/artifacts are replayable daemon state.
- Current Genomi portal checkpoints summarized in
  `webui-ux-comparison-and-alignment.md`,
  `subagent-alignment-actions.md`, and `capability-gap-backlog.md`, especially
  the screenshots around primary navigation, workspace details, evidence sources,
  attached material, workspace files, and artifact work trails.

## Core Rule

The Genomi portal is a local research workspace, not `/start`, not the old
Decode dashboard, and not a browser-side tool console.

The user-facing launch command is `genomi serve`. In an interactive terminal it
opens the local science workspace; when launched by a host agent over pipes, it
stays the MCP stdio command. Use `genomi serve --app --no-browser` for an
explicit headless app server and `genomi serve --transport stdio` for an
explicit MCP stdio server.

The browser should feel like the assistant's working surface because it renders
server-owned project state: conversation, files, artifacts, evidence, work
trail, provenance, review, reproducibility, genome readiness, and privacy
boundaries. The host agent still reasons and uses Genomi tools. The local
server owns prompt/context composition, selected-material sanitization,
host-agent invocation, run/project events, artifact materialization, and replay.

Every normal panel, chip, tab, and action must map to a research object the
user understands. If a surface mainly exposes route state, packet assembly,
schema shape, raw ids, adapter output, or tool wiring, keep it behind technical
disclosure or record it as a backlog gap.

## What Users Should See

- `Research workspace`: the main conversation, composer, assistant answers,
  compact work-step groups, and object-local follow-up actions.
- `Files & Artifacts`: uploaded files, produced files, generated artifacts,
  previews, versions, local downloads, bundles, and artifact actions.
- `Project Library`: the user-facing interpretation of files and artifacts.
  Markdown notes, code, images, PDFs, tables, notebooks, and generated reports
  should open beside chat as durable research records, not as generic file
  previews or raw download links. Library navigation may expose project-relative
  folders and generated-record groups, but never backend workspace roots.
- `Current evidence`: scoped evidence from the active conversation or artifact,
  with readable source lanes, coverage, observations, defaults, and limits.
- `Work trail`: compact work steps explaining what the assistant and Genomi did,
  with diagnostics collapsed by default.
- `Active genome`: the current approved genome object plus readiness, genome
  build, source boundary, approval state, and privacy boundary when genome
  facts may matter.
- `Evidence sources`: secondary source-preparation cards with purpose, friendly
  required inputs, coverage/source limits, privacy boundary, and chat handoff.
- `Included evidence`: composer-adjacent cards for selected evidence, sources,
  artifacts, files, work steps, review findings, and genome facts. Message chips
  use `Using` plus the object name.
- Artifact-local tabs only when backed by real state: preview, provenance or
  evidence and sources, origin chat, work trail, review findings or limits,
  rebuild readiness and limits, runtime/source limits, version identity, and
  downloads.

Visible copy should name the user's object: evidence, source, artifact, file,
conversation, work step, active genome, review finding, or rebuild recipe.

## What Should Stay Hidden

Keep these out of default UI labels, selected-material chips, empty states, and
assistant-facing product copy:

- Context packet mechanics, raw selected payloads, `context_kind`,
  `source_operation`, route state, frame ids, run ids, tool-call ids, result ids,
  artifact ids, and version ids as primary labels.
- Raw operation ids, tool schemas, parameter JSON, dependency contracts,
  default metadata, output shapes, renderer ids, MCP routing details, and
  browser-owned request builders.
- Local filesystem roots, raw Active Genome Index paths, snapshot paths,
  registry files, response profiles, endpoint details, and debug JSON.
- Host-agent setup chatter, stdout/stderr dumps, adapter diagnostics, package
  inventories, and machine audits outside collapsed diagnostics or technical
  details.
- Persistent next-question panels, dashboard-first vocabulary, decode-first
  product flows, and any action that implies a missing capability already
  exists.

Technical details remain useful, but they are expert disclosure. They should
support debugging without becoming the normal artifact or evidence story.

## How Chat, Context, And Artifacts Should Feel

Chat should be the user's natural workspace, not a proxy for a separate CLI.
The transcript should read as assistant prose plus compact, expandable work
steps. Run and project events should be replayable after refresh; the browser
must not infer durable state by parsing assistant Markdown.

Context should feel like selected research material. Users select an artifact,
file, evidence node, source lane, work step, review finding, or genome fact.
The server turns that selection into a sanitized prompt handoff. Active browser
route context is orientation only, not evidence.

Artifacts should feel like first-class workspace objects. Opening an artifact
keeps preview, provenance, origin chat, work trail, review, rebuild, environment
limits, versions, downloads, and actions near the artifact. Provenance belongs
beside the artifact, not buried in raw logs. Partial equivalents must be named
honestly: `Work trail` is not a full execution log, `Rebuild recipe` is not a
script bundle, and `Environment` is not a complete package graph unless Genomi
has those backing records.

Files are part of provenance, not secondary attachments. A `.md` note, generated
image, script, table, or PDF should be directly openable in the workspace with
type-specific treatment and a clear connection to the project/run/artifact that
produced it. If a file has a linked immutable artifact version, the user should
be able to move from the file record to the artifact history without copying
paths or understanding snapshot storage.

Workspace ownership must stay explicit. Browser-opened portal projects use a
Genomi-owned workspace under `$GENOMI_HOME/workspace/<project>`, surfaced only
as project files, generated records, artifacts, and relative paths. Agent-opened
work outside a portal project stays owned by the host agent's current working
directory; Genomi should not imply arbitrary agent cwd files belong to a portal
workspace.

Reviewer checks should become a visible research object only when backed by
real check state. Claude Science's public page and workspace both make Reviewer
feel like an independent guardrail over claims, citations, code, and task
boundaries. Genomi should map that to evidence-envelope validation,
negative-inference gates, source-coverage checks, clinical-safety wording, and
artifact consistency checks. Do not show a Review tab as a promise unless there
are findings, limits, or runnable review state behind it.

Evidence sources should feel like source preparation for the assistant. They
should collect friendly inputs and route back through chat. They should not
feel like picking a Genomi operation, editing a schema payload, or executing a
tool directly in the browser.

Genomics guardrails are part of the UI. Evidence surfaces must not imply
calibrated PRS absolute risk without calibration, ancestry identity or
percentages from weak reference context, diagnosis or carrier conclusions from
raw variant inventory, causal gene claims from GWAS mapped genes alone, or
medication actionability from genotype alone.

## Latest Alignment Audit

The 2026-07-03 independent UI audit found that Genomi's architecture is aligned
with the target pattern, but several surfaces still let implementation concerns
leak into the product:

- `Evidence sources` still behaves too much like a browser-side tool console. The
  default path should be friendly source preparation: purpose, required inputs,
  coverage/source limits, privacy boundary, and chat handoff. Operation
  selection, validation, defaults, prompt composition, and selected-material
  handles should move to the server.
- Current status: evidence-source prompt and selected-material handoff now
  routes through `/api/evidence-sources/attach`; the remaining work is tighter
  gating of which evidence sources appear in ordinary workflows and deeper
  artifact/provenance integration.
- `Assistant runtime` should not be a primary workflow. Normal chat should ask
  the research question and let the server choose a default runnable host
  agent. Runtime details belong in readiness, settings, or troubleshooting.
- Artifact `Review`, `Rebuild`, and runtime/source-limit panes should appear only when
  backed by real review state, rebuild limits/recipes, or runtime/source
  limits. Generic review instructions are actions or technical details, not a
  review tab.
- Artifact metadata should not lead with ids, operations, renderer names,
  content types, checksums, raw URLs, run ids, or package inventory. Those are
  technical disclosure; preview, origin chat, evidence/sources, work trail,
  versions, and downloads are the normal workspace objects.
- `Work trail` selections should attach a user-facing title, status, summary,
  and evidence relevance. Run ids, event ranges, stdout/stderr chunks,
  diagnostic cells, and event ids remain collapsed diagnostics until stable
  execution-cell records support full execution-log UX.
- `Active genome` is the visible workspace object. Its readiness and privacy
  boundary are properties of that object. Include actions should only be
  enabled when an approved, ready Active Genome Index exists; empty, blocked,
  or pending states should show setup/approval status only.
- Capability result presentation should continue moving server-side. The
  browser should render generic lanes and actions from `portal_presentation`
  instead of deriving domain UX from raw capability payloads.

## Implementation Backlog

1. Continue simplifying evidence sources now that evidence-source prompt and
   attached-material preparation are server-owned. The browser should gather
   friendly intent/input state and avoid schema-shaped controls in normal
   source cards.
2. Persist or explicitly scope `Current evidence` per conversation so it never
   reads like a global evidence authority unless backed by durable evidence-map
   state. The current portal scope must name the active conversation and
   distinguish saved work-history evidence from live in-session evidence.
   Genome/session context and generic result views belong in their own
   workspace objects, not in the evidence ledger.
3. Gate artifact tabs by meaningful backing state. Review, rebuild, environment,
   and technical details should appear only when they carry real findings,
   honest limits, or explicit expert inspection value.
4. Promote execution-cell slices into stable execution-cell records with command
   source, environment labels, stdout/stderr panes, artifact-version links, and
   producing-step routes before using `Execution log` language.
5. Move more capability-specific result rendering into server-emitted portal
   presentation models so the browser no longer owns evidence-schema ladders.
6. Formalize host-agent adapter capability negotiation and runtime injection,
   while keeping web, CLI, MCP, fork, handoff, and side-chat surfaces on the
   same server-owned run/result-package contract.
7. Add version-owned script bundles, richer environment snapshots, async review
   check runs, richer Library session/folder grouping, cloud export, and exact
   producing-step links only when Genomi has real user-facing objects for those
   jobs.
8. Keep legacy Decode/dashboard records displayable as reports, but quarantine
   dashboard and decode vocabulary from the new portal product language.

## Applied Alignment

- The primary composer no longer exposes a runtime picker or submits `agentId`
  for normal chat turns. Runtime readiness remains in the rail, detected
  runtimes appear under secondary details, and the server selects the default
  runnable host agent.
- Plain user turns no longer render an included-evidence runtime bridge when
  no material was attached. Runtime state stays in secondary readiness/details
  surfaces.
- Evidence sources no longer auto-select the first available source when the
  catalog loads. The secondary pane waits for an intentional evidence-source
  choice.
- The visible source-preparation surface is now labeled `Evidence sources`, and
  row actions use `Choose` instead of the ambiguous `Prepare`.
- Evidence-source handoff actions use product language: `Use in chat`,
  `Draft question`, and `Ask with source`. User-visible copy should not say
  `Source check`, `Prepare`, `Preparation`, or `Attach source`; those are
  implementation or bridge concepts, not end-user workflow names.
- The Evidence sources chooser should include science/source choices, not
  backend readiness chores. Library availability checks remain support state
  surfaced only when a selected workflow needs that evidence source.
- Source request builders should guide the user through scientific intent
  before exposing parameters. For common sources such as Target evidence
  report, use target chips and collapse optional source limits instead of
  showing a raw target-type dropdown plus every possible field.
- Common source forms should use server-owned grouping metadata. Genome-file,
  public-source search, and variant lookup keep the primary scientific input
  visible and collapse optional source details, limits, alternate input forms,
  and approved-genome-context switches.
- `Current evidence` admits only evidence-shaped records for the active
  conversation. Active-genome/session context remains available through the
  Active genome surface, and generic result views or unscoped events do not
  count as reusable current evidence.
- Scope changes should be a view concern, not destructive ledger storage.
  Switching conversations may hide out-of-scope evidence, but returning to that
  conversation should restore its saved or live evidence entries.
- Do not repeat a generated input catalog under an interactive request builder.
  Once a form is visible, the duplicate `Inputs` section is implementation
  disclosure unless it carries additional evidence meaning.
- Artifact `Review` tabs and `Use review summary` actions are gated on real
  artifact-version review state. Generic artifact summaries remain available
  through the normal `Use artifact` action.
- Artifact detail tabs and actions should use the artifact's user-facing family:
  `Evidence report details`, `Report details`, `File details`, or `Artifact
  details`. Do not call files and reports generic artifacts in normal
  workspace chrome.
- Workspace file rows now use `Open` and classify files as Markdown, Code,
  Image, Table, Data, Text, or File. The preview panel presents the opened file
  as a research record, so Markdown notes, scripts, generated images, and tables
  feel like project-library material rather than a small utility preview.
- Workspace file display labels are server-owned where current payloads are
  available: `file_kind`, `kind_label`, and `record_label` travel with file
  listings and previews, while the browser keeps local classification only as a
  compatibility fallback.
- Opening a generated workspace file must keep its research history attached.
  The file preview should still expose the generated record and origin chat
  actions when the current file identity matches the materialized artifact.
  Generated previews should visibly say `Generated record`; ordinary opened
  files remain `Research record`.
- The visible artifact environment tab is labeled `Source limits`
  so Genomi does not imply a complete execution-environment snapshot before
  that backing object exists.
- Genome-state rows are selectable only when an approved, ready Active Genome
  Index can be attached. Empty, blocked, pending, or unknown-readiness genome
  states render static status rows plus an action hint.
- Visual evidence and artifact `Use`/`Ask`/`Draft` actions should return the
  user to the Research composer with attached material visible. The current
  artifact route can remain as orientation, but the visible handoff should feel
  like "use this evidence in my next message", not like managing a packet or
  staying inside a secondary inspection pane.
- User-facing copy should say `Included`, `Using`, or `included evidence`
  depending on placement, not `attached material`, `selected context`, or
  `context card`. `Context` remains an internal contract word and should appear
  only in technical/debug surfaces.
- Source handoff copy should say `use in chat` / `ask with this source`, not
  `next question`, `prepare`, `source check`, or packet/setup language.
- Starter cards should open a concrete workspace object or source form whenever
  Genomi has one. Prompt-only starter cards are allowed only for genuinely
  open-ended planning requests with no better source/workspace entry point.
- Active genome is not a standalone question. A ready genome can be included in
  the composer, but direct Ask/Draft actions should stay hidden until the user
  supplies a genetics question.
- Active genome is a user-facing research object, not a boolean readiness
  state. The topbar and Genome pane should show enough safe identity for the
  user to know what is active, such as display name, build, source type,
  readiness, and known-genome count. Copy like `Genome ready` is too vague.
  Keep raw paths and payloads in technical disclosure, but expose `Add genome`,
  available genomes, and direct `Use this genome` selection in the normal
  Genome surface. Do not ask the user to draft a chat message merely to switch
  the active genome.
- Host-agent control prompts must never render as visible user messages. If a
  stored frame contains one from an earlier build, render a user-facing state
  summary instead of replaying the hidden instruction text.
- Conversation titles and frame-list rows must use a user-facing display
  request, not raw hidden prompt transport. Keep the raw request for host-run
  reconstruction, but project it before showing it in the rail or workspace
  breadcrumbs.
- Diagnostic-only runtime events should not create visible chat work cards.
  They may remain in technical trace/provenance data, but the main chat should
  show work cards only for meaningful tool calls, evidence results, or user
  artifacts.
- Work-trail steps should expose object navigation before mechanics. If a step
  can take the user to its origin conversation, show `View in chat`; if it
  produced a durable result, show `Open artifact`. Hidden route state may focus
  an exact work card when the card is stable, but run ids, event ranges, event
  records, and route anchors stay out of visible copy and inside collapsed
  technical details.
- An artifact's Work trail is artifact-local. Shared run setup and tool steps
  may remain visible, but concrete artifact-produced cells with a different
  artifact or version identity belong to that sibling artifact, not the
  selected artifact's work trail.
- Older stored genome-only turns with generic labels such as `Genome ready`
  should replay as the most specific safe genome summary available from the
  saved facts, for example build plus query-readiness, rather than preserving
  obsolete readiness-only copy.
- Workspace is an ownership boundary. Browser-opened project work belongs to
  Genomi and lives under `$GENOMI_HOME/workspace/*`; the portal should present
  those files as project files, generated records, artifacts, and relative
  workspace paths. Agent-opened work belongs to the host agent's current
  working directory unless the agent run is launched through a portal project;
  Genomi should not blur arbitrary agent cwd files into portal-owned workspace
  state.
- Run and event payloads should expose this as public workspace ownership
  metadata. UI code should branch on `owner` and `storage`, not guess from
  routes, ids, or backend paths.
- Browser imports are workspace files first. Importing a file from the portal
  should write a project-relative file into `$GENOMI_HOME/workspace/<project>`
  and snapshot it as an artifact for provenance. The file browser should label
  it as `Imported file`, not `Generated record`; generated records are reserved
  for current files produced by the host agent inside the project workspace.
- Generated-record file actions must be identity-backed. A workspace file may
  show generated-record grouping, `Open artifact`, or `View in chat` only when
  the current file still matches the materialized artifact identity. If the
  file has been edited or replaced at the same path, keep it visible as a
  normal project file and remove generated-record actions until a new artifact
  is materialized.
