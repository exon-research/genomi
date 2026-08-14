# Exploration Log

## Scope

Target inspected:

- `http://localhost:8765/projects/proj_65ee842cd510/frames/991ad887-1322-458d-9f87-91201044b16f`
- After opening an artifact, the UI route changed to:
  `http://localhost:8765/projects/proj_65ee842cd510`

Re-authentication used the official CLI flow:

- `claude-science url`
- One-time nonce URL opened in the browser and used with curl to seed a
  localhost cookie jar.
- The resulting auth is cookie-based with `operon_auth` and `operon_csrf`.
  Cookie values are intentionally not recorded here.

The exploration happened in phases:

- The initial `/start` and first workspace/source pass was read-only: browser
  DOM inspection, API GETs, local DB schema reads, local web bundle reads, and
  binary string inspection.
- Later comparison passes submitted short public science prompts in the
  authenticated Claude Science project to observe how answers become evidence
  lanes inside the workspace.
- The second Library/provenance pass was read-only again: no destructive
  artifact action, upload, export, or settings change was performed.

## Workspace UI Observations

The useful UI model is the project workspace, not `/start`.

Screenshots:

- `screenshots/01-live-conversation-artifact-tray.png`
- `screenshots/02-live-artifact-split-image.png`

The loaded project showed:

- A left-side transcript replaying the host-agent session.
- Grouped tool activity:
  - `data-testid="tool-chip"`: 47 instances in the inspected run.
  - `data-testid="tool-group"`: 9 instances.
  - `data-testid="tool-group-header"`: 9 instances.
- A generated artifact tray:
  - `data-testid="turn-artifact-tray"`: 1 instance.
  - `data-testid="turn-tray-card"`: 5 visible generated artifact cards.
  - `data-testid="turn-tray-open-split"`: one split-view action per card.
- A bottom composer:
  - `data-testid="composer"`
  - `data-testid="composer-dock"`
  - mode label: `Notebook`
  - model selector visible as `Opus`

Generated artifacts in the inspected tray included:

- `benchmark_report.md`
- `benchmark_figure.png`
- `benchmark_metrics.csv`
- `gatk_chr20.vcf.gz`
- `bcftools_chr20.vcf.gz`

Clicking `benchmark_figure.png` opened a right split pane. The artifact pane
exposed:

- `data-testid="split-right"`
- `data-testid="operon-split-session-right"`
- `data-testid="split-view-toggle"`
- `data-testid="artifact-actions"`
- `data-testid="artifact-maximize"`
- `data-testid="artifact-download"`

The opened image was served as a versioned artifact URL:

```text
/api/artifacts/versions/3a77b5ee-fb87-4414-88db-6a812abcd347?v=3a77b5ee-fb87-4414-88db-6a812abcd347
```

The artifact action menu contained:

- Star
- Hide
- View in context
- Provenance
- Copy link
- Rename
- Export Metadata
- Export to Cloud
- Delete

For Genomi, the high-value items are View in context, Provenance, Copy link,
typed export, and download. Star/hide/delete can wait unless they support a
specific research workflow.

Screenshot:

- `screenshots/03-live-artifact-actions-menu.png`

## Genomi Portal Implementation Checkpoint

Target inspected after local Genomi portal changes:

- `http://localhost:8767/`
- `http://localhost:8767/#artifact-workspace`

Screenshots:

- `screenshots/09-genomi-portal-initial.png`
- `screenshots/10-genomi-portal-desktop-initial.png`
- `screenshots/11-genomi-artifact-preview.png`
- `screenshots/12-genomi-artifact-evidence-tab.png`
- `screenshots/13-genomi-artifact-tools-tab.png`
- `screenshots/14-genomi-artifact-state-tab.png`
- `screenshots/15-genomi-artifact-review-tab.png`
- `screenshots/16-genomi-artifact-first-class-workspace.png`
- `screenshots/17-genomi-artifact-review-tab-fixed.png`
- `screenshots/21-genomi-portal-mobile-final.png`
- `screenshots/22-genomi-live-artifact-workspace-before-open-design-followup.png`
- `screenshots/23-genomi-project-event-stream-after-reload.png`

Validation steps:

- `GET /start` on the Genomi portal returned `404 Not Found`.
- Initial portal load showed CSS active, `data-testid="genomi-artifact-tray"`
  present, and no `data-testid="genomi-split-right"` before an artifact was
  selected.
- A visual-inspection artifact fixture was added to the current portal project
  to exercise the artifact UI without waiting on the obsolete decode renderer.
- Opening Artifacts rendered `data-testid="genomi-split-right"` with artifact
  tabs:
  - `genomi-provenance-tab-preview`
  - `genomi-provenance-tab-evidence`
  - `genomi-provenance-tab-tools`
  - `genomi-provenance-tab-state`
  - `genomi-provenance-tab-review`
- Desktop geometry after cleanup showed the artifact workspace as the first
  right-side pane:
  - `.right-stack > .pane` first id: `artifact-workspace`
  - artifact workspace top: `85`
  - review title width: `452`
- Narrow viewport audit at `390x900` reported:
  - `documentElement.scrollWidth === documentElement.clientWidth === 390`
  - no document-level horizontal overflow
  - only the provenance tab strip extended horizontally, which is intentional
    because it is a scrollable tab list.

Implementation notes from the checkpoint:

- Artifacts now lead the right-side workspace instead of a product-explainer
  panel.
- The artifact split pane exposes preview, evidence provenance, operation trace,
  panel state, and review brief tabs.
- Artifact review and provenance nodes are selectable and can be attached to the
  next host-agent turn.
- Review tab clipping was fixed by stacking artifact header metrics below the
  title.
- Mobile artifact/provenance values now wrap rather than being forced into
  one-line ellipses.
- A project-level SSE stream was added after the open-design source study:
  `GET /api/projects/:project_id/events`.
- The browser now loads `portal_project_stream.js`, subscribes to the current
  project, and debounces public REST refreshes for frame, message, artifact,
  and project changes.
- The run stream remains separate: `GET /api/runs/:run_id/events` is still the
  host-agent turn stream, while the project stream owns workspace refreshes.
- Verification after server restart:
  - Browser requested `/api/projects/proj_4eff6d75d3f7/events`.
  - Direct stream read returned:

```text
event: ready
data: {"project_id":"proj_4eff6d75d3f7"}
```

- Browser console reported no errors or warnings.

## Claude Science Product-Page Comparison Pass

Target inspected:

- `https://claude.com/product/claude-science`
- Local Genomi workspace:
  `http://127.0.0.1:8885/projects/proj_a73a9a7e9b75/frames/116bd0bc-0e7a-4d09-86fb-2a198c54d2d8`

Screenshots:

- `screenshots/20260704-claude-science-product-page.png`
- `screenshots/20260704-genomi-current-workspace.png`

The public Claude Science page frames the application around a small set of
research-workspace promises:

- The app runs analyses, searches databases, and traces every step from data
  wrangling to publication.
- Artifacts carry the exact code, environment, and conversation that produced
  them.
- The workbench includes built-in scientific renderers for proteins,
  alignments, genomic tracks, chemical structures, and PDFs.
- A reviewer/checking layer flags incorrect citations, untraceable numbers, and
  mismatches between figures and code.
- Compute and environments are managed where the data lives, including local
  machines and HPC.
- Domain readiness comes from skills, connectors, scientific databases, and
  open models.

Current Genomi Portal observations from the same comparison pass:

- The active genome header is better than the earlier `Genome ready` chip
  because it names `george`, build, source, profile, and available genomes.
- The default screen is still too crowded: assistant status, workspace
  switching, conversations, chat, work steps, artifact cards, file library,
  filters, generated-record sections, and genome controls all compete in one
  viewport.
- The right pane duplicates artifact information already present below the
  chat. It should become the selected-object workspace rather than a permanent
  all-files dashboard.
- Work-step rows still expose low-level host-agent implementation detail in
  existing frames, including raw MCP fragments and generic `Genomi work` labels.
  User-facing progress should summarize the research step and keep raw runtime
  detail behind diagnostics.
- The failed permission state is still not a product-quality approval object.
  The web UI should let the user grant the host-agent permission in place.
- `Download conversation bundle` is useful but too prominent as a default
  primary action. It belongs with reproducibility/export actions, probably near
  the artifact or conversation menu.

Design translation:

- Make the conversation the primary work surface.
- Use one compact assistant-work group per turn; expand to Work trail only when
  the user asks to inspect the process.
- Make Files & Artifacts a project library and selected-object workspace,
  not a second dashboard permanently visible beside every chat turn.
- Expose genome identity as a concrete workspace object with Switch/Add/View
  actions.
- Attach provenance to artifacts and generated files: Preview, View in chat,
  Work trail, Environment/sources, Review, Download.
- Keep implementation terms (`context packet`, raw operation id, MCP tool
  reference, selected payload, route id, adapter output) out of normal UI copy.

## 2026-07-16 Local Paired Workflow Pass

The local reference portal and Genomi were exercised as working applications,
not compared only from product screenshots. The reference project received a
public-source rs429358 request that produced a Markdown report, exposed the
report beneath the answer, opened it in a split document pane, and later showed
a reviewer finding that had been fixed in a new version. Its Files action kept
the conversation visible and opened a sparse artifact library as a second work
surface.

The user-facing sequence worth adapting is temporal:

1. The assistant works in the conversation.
2. A generated object appears under the answer when the file is saved.
3. Opening that object reveals a focused, readable document beside the chat.
4. File origin and work history remain attached but secondary.
5. Review appears when an actual review finding or check exists, not as a
   permanent empty or automatically-passed tab.

Genomi now follows that sequence for project-file writes:

- Successful host-agent `Write` and `Edit` results materialize project files
  immediately, before the host run exits.
- The generated file card appears beneath the originating assistant turn while
  the run can still be in progress.
- Assistant Markdown and generated Markdown render semantically rather than as
  literal syntax.
- Opening a generated report creates a chat/document split with `Preview`,
  `File details`, `Origin chat`, and `Work trail`.
- Passive review state and source/runtime metadata no longer occupy primary
  tabs for ordinary project files.
- The default research workspace is chat-primary. The complete file library is
  a deliberate destination, while a selected file opens beside its origin
  conversation.
- Local assistant/runtime troubleshooting is nested under `Workspace details`
  rather than occupying permanent primary sidebar space.

The adaptation deliberately does not copy every reference control. Genomi does
not expose an empty reviewer tab, generic environment claims, artifact packet
fields, or a host selector as normal research objects. The useful common model
is conversation → generated file → focused preview → attributable work trail.

Screenshots from this pass:

- `screenshots/20260716-local-reference-home.jpg`
- `screenshots/20260716-local-reference-files-library.jpg`
- `screenshots/20260716-genomi-live-generated-report.jpg`
- `screenshots/20260716-genomi-chat-primary-workspace.jpg`
- `screenshots/20260716-genomi-origin-chat-report-split-view.jpg`

## Local Claude Science App Recheck

Local app target:

- Started/authenticated via `claude-science url`
- Opened fresh nonce URL at `http://localhost:8765/`
- Project route:
  `http://localhost:8765/projects/proj_65ee842cd510/frames/991ad887-1322-458d-9f87-91201044b16f`
- Artifact route:
  `http://localhost:8765/projects/proj_65ee842cd510/artifacts/e06db6bc-dfe8-48e7-92cb-fa78fd2e2046?v=340cf487-b0c4-4f4c-907a-11128851d88a`

Screenshots:

- `screenshots/20260704-local-claude-science-project-files.png`
- `screenshots/20260704-local-claude-science-artifact-route.png`
- `screenshots/20260704-local-claude-science-artifact-menu.png`

Project-list observations:

- The home view is sparse: product identity, `New project`, `Customize`, account
  menu, project rows, and recent sessions.
- Project rows are the main resume object; recent sessions are the secondary
  resume path.
- No agent/tool/debug state appears on the project list.

Workspace observations:

- Opening the benchmark project restores the last active frame.
- The main workspace is a conversation surface plus a right split pane.
- The right split pane can be the Files library. It is not a separate
  always-visible dashboard; it is one selected workspace tab.
- The Files library groups artifacts by source/session:
  - user uploads;
  - benchmark session artifacts.
- Library cards expose user-facing object actions:
  - open in split view;
  - download;
  - more actions.
- The conversation still contains grouped work steps and generated artifact
  trays at the producing turn, so artifacts are reachable both from the project
  library and from their origin in chat.

Artifact-route observations:

- Opening `benchmark_report.md` changed the URL to an artifact identity while
  preserving the surrounding workspace.
- The producing conversation and work-step stack remained available behind the
  artifact route.
- Work groups use plain research-progress labels such as `Read a file, set up
  an environment`, `Ran 2 commands`, and `Saved artifacts, ran a command`.
- Tool chips use concise natural labels such as `Running GATK HaplotypeCaller
  on chr20` and show bounded output summaries such as `24 lines of output`.
- Errors are visible when they matter, but as part of the research process
  (`2 steps · 1 failed`), not as raw host-agent permission or transport
  failures.

Artifact menu observations:

- The artifact action menu contained:
  - Star
  - Hide
  - View in context
  - Provenance
  - Copy link
  - Rename
  - Download `.md`
  - Export Metadata
  - Export to Cloud
  - Delete

Genomi translation:

- The durable default artifact actions are `View in chat`, `Provenance`, `Copy
  link`, `Download`, and metadata export. Star/hide/delete are optional later
  library-management features.
- Genomi work-step labels should describe the research action or evidence
  operation, not the host-agent mechanism. Avoid default labels such as
  `Genomi work` when a better operation, file, source, or evidence label is
  available.
- A failed tool/permission run should become a clear approval card or bounded
  work-step failure, not a raw error row.
- The right side should be a selected workspace object: files, artifact preview,
  provenance, genome state, or evidence map. It should not permanently show a
  complete internal dashboard beside every chat.

## Genomi Work-Trail Copy And Filtering Checkpoint

Target inspected after implementation:

- `http://127.0.0.1:8885/projects/proj_a73a9a7e9b75/frames/116bd0bc-0e7a-4d09-86fb-2a198c54d2d8`

Screenshot:

- `screenshots/20260704-genomi-filtered-work-trail.png`

Implementation changes:

- Generic operation fallback copy changed from `Genomi work` to
  `Research step`.
- Selected-material prompt intros now say `Selected result`,
  `Selected report`, `Selected evidence report`, `Selected work step`, and
  `Selected conversation work trail` rather than repeating `Selected Genomi`.
- Transcript-side tool rendering now hides technical host-agent wrappers:
  raw `mcp__...` tool references, skill-loading messages, tool-search setup,
  Bash recovery chatter, and tool-reference JSON.
- If a technical recovery step returns a Genomi operation headline such as
  `pharmacogenomics.review_medication: evidence_present`, the transcript
  promotes that operation as the visible work step.

Verification:

- Focused portal suite:

```text
PYTHONPATH=src python3 -m unittest \
  tests.test_portal_frontend_assets \
  tests.test_portal_frontend_frame_trace \
  tests.test_portal_frontend_artifact_models \
  tests.test_portal_frontend_artifact_selection \
  tests.test_portal_target_packet_renderer \
  tests.test_portal_execution_cells
```

Result:

```text
Ran 50 tests in 38.263s
OK
```

- Live browser check after portal restart:
  - visible page text no longer contained `Genomi work`;
  - visible page text no longer contained `Selected Genomi`;
  - visible page text no longer contained raw `tool_reference` JSON;
  - 15 technical chips were hidden in the inspected frame;
  - the meaningful visible operation was `Medication-response review` with
    summary `pharmacogenomics.review_medication: evidence_present ·
    scoped_answer_only`.

## Genomi Evidence Packet Artifact Checkpoint

Target inspected after adding the first non-decode artifact renderer:

- `http://localhost:8767/projects/proj_4eff6d75d3f7/frames/cbf64764-22a2-4f9e-9fcf-e81798f4fd78`
- Render API path:
  `POST /api/projects/proj_4eff6d75d3f7/artifacts/render`
- Renderer payload:
  `{"renderer":"evidence_packet","target_type":"topic","topic":"rs429358","limit":6}`

Screenshots:

- `screenshots/50-genomi-evidence-packet-artifact-preview.png`
- `screenshots/51-genomi-evidence-packet-artifact-state.png`

The rendered artifact was produced by `research.build_target_packet`, persisted
as `kind="evidence_packet"` and `renderer="evidence_packet"`, and opened in the
same artifact split pane as other portal artifacts.

Preview tab observations:

- The iframe renders a Genomi-native evidence report rather than the old Decode
  dashboard.
- The hero exposes target, finding state, answer readiness, source catalog
  count, available operation count, and stored research count.
- The source list is a capped preview of the catalog, while the metric reports
  the catalog-level source count.
- Available operations are shown as concrete follow-up tools such as
  `research.query`, `research.list_sources`, `research.search`, and
  `research.record`.
- Evidence options show whether source-scope selection and stored research are
  available.

State tab observations:

- The artifact inspector adapts the same summary through the canonical
  `research.build_target_packet` frontend model rather than a second
  evidence-packet-only projection.
- Metrics match the preview iframe and add the target-packet model's counts:
  target `rs429358`, finding `evidence_present`, readiness
  `scoped_answer_only`, `20` sources, `0` stored findings, `4` operations, and
  `2` evidence options.
- Target, Source catalog, Available operations, and Evidence options are
  inspectable as selectable pane nodes.

Visual inspection caught a real renderer bug: the first iframe screenshot showed
`9` sources while the artifact card and State tab showed `20`. The cause was
that the iframe metric counted only the capped preview array. The renderer now
uses one source-count helper for summary lines, artifact summary, and iframe
metrics, while leaving the source card list capped for readability.

The subsequent thermo-nuclear review found two structural issues in the first
implementation:

- Evidence-packet artifacts used a fixed project file path, so a newer render
  could overwrite the HTML served by an older artifact record.
- The artifact State tab duplicated the target-packet frontend contract instead
  of reusing the canonical target-packet renderer.

The post-review implementation fixes both:

- Each evidence-packet render writes an artifact-specific HTML file.
- Portal file metadata moves through an explicit render-output object instead
  of being injected into the presented Genomi result.
- Missing target payloads fail the render run cleanly instead of fabricating a
  generic research-workspace topic.
- The State tab reuses the target-packet model and the review brief uses neutral
  `State metric` / `State section` wording rather than dashboard-specific panel
  language.

## Genomi Artifact History Summary Checkpoint

The artifact split pane now exposes a compact `Result history` strip directly
under the artifact title. This is the Genomi-native translation of the reference
portal's "every artifact ships with its history" pattern: the user can see at a
glance which backed research objects are attached to the open result.

The strip is deliberately derived from real artifact state only:

- immutable version count;
- bounded origin chat, when provenance messages exist;
- work trail, when producing work steps or origin tool events exist;
- rebuild recipe, when a public or redacted rebuild recipe exists;
- source limits, when environment/source coverage state exists;
- review, when artifact-version review checks exist.

Each chip activates the corresponding artifact tab when that tab is present.
The normal UI still avoids raw ids, operation schemas, context-packet wording,
and technical details. Technical details remain available through the secondary
technical tab and metadata copy action.

Verification:

```text
node --check src/genomi/interfaces/templates/portal_artifact_view_model.js
node --check src/genomi/interfaces/templates/portal_artifact_preview.js
node --check src/genomi/interfaces/templates/portal_artifacts.js
PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_artifact_models
```

Result:

```text
Ran 8 tests in 2.223s
OK
```

## Genomi Artifact Producing-Step Navigation Checkpoint

The reference workspace's `View in context` behavior does not only open the
surrounding conversation; it returns the user to the producing work group for
the artifact. Genomi now mirrors that behavior when it has backed state for the
exact producing step.

Artifact origin context now carries a `producingStepId` derived from the
version-owned `producing_work_step.execution_cell.id`. The artifact `View in
chat` action passes both `highlight_run` and `highlight_step` into the normal
frame route. When the exact step is available, the portal opens the Work trail
pane and highlights that step. When only the producing run is available, the
portal keeps the previous behavior and opens the producing conversation/run.

This keeps the behavior honest:

- exact step highlighting appears only for artifacts with persisted execution
  cell anchors;
- no operation ids, raw event ids, or context packets are shown in normal
  artifact UI;
- the same server-owned frame route handles broad run context and exact
  producing-step context.

Verification:

```text
node --check src/genomi/interfaces/templates/portal_artifact_messages.js
node --check src/genomi/interfaces/templates/portal.js
node --check src/genomi/interfaces/templates/portal_frame_trace.js
PYTHONPATH=src python3 -m unittest \
  tests.test_portal_frontend_artifact_models \
  tests.test_portal_frontend_frame_trace \
  tests.test_portal_frontend_routes \
  tests.test_portal_frontend_assets
```

Result:

```text
Ran 57 tests in 11.496s
OK
```

## Provenance UI Observations

Opening Provenance did not create a modal. It opened an inline provenance pane
inside the artifact split:

Screenshots:

- `screenshots/04-live-provenance-code-tab.png`
- `screenshots/05-live-provenance-execution-log-tab.png`
- `screenshots/06-live-provenance-messages-tab.png`
- `screenshots/07-live-provenance-environment-tab.png`
- `screenshots/08-live-provenance-review-tab.png`

- `data-testid="artifact-provenance-inline"`
- `data-testid="provenance-toggle"`
- `data-testid="provenance-tab-code"`
- `data-testid="provenance-tab-execution-log"`
- `data-testid="provenance-tab-messages"`
- `data-testid="provenance-tab-environment"`
- `data-testid="provenance-tab-review"`

The provenance pane is lazy. The Code tab initially showed:

```text
Generating reproduction code...
```

After loading, the Code tab showed:

- Download script action.
- "LLM-generated reconstruction" text.
- Inputs section with `data-testid="provenance-input-chip"`.
- Reconstructed code for the artifact.

The Execution Log tab showed:

- Download notebook action.
- Raw execution cells, each with cell index, language, conda environment,
  exit status, source code, and files written.

The Messages tab showed the conversation/tool-result transcript that led to the
artifact.

The Environment tab showed:

- Python version.
- Package table.
- Environment operation history.

The Review tab showed:

- A verification/check state.
- In this inspected artifact: `No checks run yet.`

## Claude Science Object UX Re-Anchor

The later artifact-route inspection corrected a Genomi design drift. Claude
Science does not ask the user to select an evidence report or manage a context
payload. It lets the user move between concrete scientific objects:

- a chat frame;
- grouped work steps inside that frame;
- generated files/artifacts;
- artifact object routes;
- provenance tabs;
- review/check state;
- the Files pane as a project library.

Screenshots:

- `screenshots/162-claude-science-frame-work-step-stack.png`
- `screenshots/163-claude-science-step-output-inline-detail.png`
- `screenshots/164-claude-science-project-library-files-pane.png`
- `screenshots/165-claude-science-artifact-route-metrics-open.png`
- `screenshots/166-claude-science-artifact-actions-menu.png`
- `screenshots/167-claude-science-artifact-provenance.png`
- `screenshots/168-claude-science-artifact-execution-log.png`
- `screenshots/169-claude-science-artifact-messages-tab.png`
- `screenshots/170-claude-science-artifact-environment-tab.png`
- `screenshots/172-claude-science-artifact-review-tab.png`
- `screenshots/175-claude-science-view-in-context-result.png`

The artifact route for `benchmark_metrics.csv` rendered a dedicated table
object with an action bar. The action menu exposed:

- Star
- Hide
- View in context
- Provenance
- Copy link
- Rename
- Export Metadata
- Export to Cloud
- Delete

The important pattern is not the exact menu list. The important pattern is that
the artifact itself owns navigation and provenance. `View in context` moved the
browser from:

```text
/projects/proj_65ee842cd510/artifacts/3b9026cb-0f2c-4f5f-9836-4f9c50d6bce2?v=5a404d35-5e7d-4363-b859-f99125d18229
```

back to:

```text
/projects/proj_65ee842cd510/frames/991ad887-1322-458d-9f87-91201044b16f
```

The DOM after navigation confirmed that the routed frame contained the
producing work group and the `benchmark_metrics.csv` artifact under the
`Saving benchmark figure and metrics` step. This is the behavior Genomi should
mirror: jump from an artifact back to the chat/work trace that created it.

Provenance also stayed object-shaped. The tabs were:

- Code: generated reconstruction code, input chips, and a download script
  action.
- Execution Log: raw cells with shell/python source and environment labels.
- Messages: transcript/work-step slice that produced the artifact.
- Environment: runtime/package snapshot.
- Review: verification/check surface, empty for this artifact with `No checks
  run yet.`

Genomi translation:

- User-facing labels should say artifact, evidence, source, work trace, review,
  files, and chat.
- `context`, `packet`, `selected_nodes`, `evidence_envelope`, and Active Genome
  Index details can remain internal contracts or host-agent prompt material.
- The portal should expose `View in chat`, `Provenance`, and `Copy link` from
  artifacts, then serialize the host-agent payload behind the scenes.
- Runtime state should be shown only when it explains the artifact: consulted
  sources, applied defaults, library/source coverage, artifact versions, and
  review limits.
- Follow-up actions should start from the object being inspected. A user should
  not need to visit a separate packet-staging shelf to ask about a table,
  report, source lane, or work step.

Implementation checkpoint after this correction:

- Artifact origin navigation is labeled `View in chat`.
- Artifact runtime provenance is labeled `Runtime & sources`.
- `evidence_packet` remains an internal renderer id, but the artifact title and
  open action are user-facing `Evidence report` / `Open report`.
- The genome pane is labeled `Genome State`, and root composer helper copy says
  evidence comes from Genomi tools and the current chat.

## HTTP API Observations

GETs performed with authenticated localhost cookies:

```text
GET /api/projects/proj_65ee842cd510
GET /api/frames/991ad887-1322-458d-9f87-91201044b16f
GET /api/frames/991ad887-1322-458d-9f87-91201044b16f/messages
GET /api/projects/proj_65ee842cd510/artifacts
```

`GET /api/projects/proj_65ee842cd510` returned a project record with:

- `project_id`
- `name`
- `description`
- `context`
- `conversation_count`
- `artifact_count`
- `created_at`
- `updated_at`

The project `context` included onboarding profile text. In Claude Science this
profile becomes project context, but Genomi should treat install onboarding as
setup state, not as a replacement for current chat state or explicit Active
Genome Index approval.

`GET /api/frames/<frame_id>` returned a host-agent frame with:

- `id`
- `root_frame_id`
- `parent_frame_id`
- `agent_name`
- `delegate_name`
- `status`
- `input_data`
- `output_data`
- `context_data`
- `model`
- `effort`
- token/cost fields
- `children`
- `project_id`
- `name`
- `conversation_type`
- `message_count`
- `task_summary`

`GET /api/frames/<frame_id>/messages` returned:

- `frame_id`
- `from`
- `total`
- `messages`

## Open-Design Source Observations

Local source inspected:

- `/Users/matthewzmd/code/open-design/apps/web/src/providers/daemon.ts`
- `/Users/matthewzmd/code/open-design/apps/web/src/providers/project-events.ts`
- `/Users/matthewzmd/code/open-design/apps/web/src/components/workspace/useConversationChat.ts`
- `/Users/matthewzmd/code/open-design/apps/web/src/runtime/tool-renderers.ts`
- `/Users/matthewzmd/code/open-design/apps/web/src/artifacts/renderer-registry.ts`
- `/Users/matthewzmd/code/open-design/apps/daemon/src/routes/runs.ts`
- `/Users/matthewzmd/code/open-design/apps/daemon/src/runtimes/runs.ts`

Relevant architecture:

- Web submit path:
  - Browser posts a run request to `POST /api/runs`.
  - The request includes agent id, project id, conversation id, selected
    skills/plugins, attachments, and contextual payloads.
  - The daemon creates a run id, then the web UI consumes
    `GET /api/runs/:id/events`.
- Run stream:
  - The daemon run registry stores event records with ids.
  - `GET /api/runs/:id/events?after=<id>` replays missed records, then keeps
    the SSE client attached.
  - The browser translates raw daemon/agent events into UI events such as text
    deltas, tool uses, tool results, status, usage, and live-artifact events.
- Project stream:
  - `GET /api/projects/:project_id/events` is separate from the run stream.
  - The project stream carries workspace changes such as file changes, live
    artifact refreshes, and conversation-created events.
  - The client reconnects with backoff and refetches public project/file data
    instead of trusting large state payloads inside the stream.
- Side conversation path:
  - `useConversationChat.ts` binds a secondary chat surface to one project
    conversation.
  - It creates local user/assistant messages immediately, streams deltas into
    the assistant message, persists terminal messages, and records run ids for
    retry/reattach.
- Renderer extension points:
  - `tool-renderers.ts` is a per-tool renderer registry. It receives tool
    lifecycle props and lets plugins/skills render tool cards before fallback
    cards.
  - `renderer-registry.ts` maps artifact manifests to renderers such as HTML,
    deck HTML, React component, Markdown, and SVG.

Implication for Genomi:

- Keep two event planes:
  - run events for the active host-agent turn;
  - project events for workspace refreshes that should survive route changes
    and page reloads.
- Keep project events compact. Emit identifiers and reasons, then let the
  browser refetch public REST shapes for frames, messages, artifacts, and
  project metadata.
- Put renderer selection behind explicit artifact metadata rather than making
  one dashboard renderer the portal's implicit default.

For the inspected frame, `total` was 136 after the later comparison turns.

`GET /api/projects/<project_id>/artifacts` returned a list of artifacts with:

- `id`
- `version_id`
- `version_number`
- `project_id`
- `root_frame_id`
- `frame_id`
- `creating_frame_id`
- `filename`
- `content_type`
- `size_bytes`
- `created_at`
- `checksum`
- `file_path`
- `is_user_upload`
- `agent_name`
- `folder_id`
- `is_intermediate`
- `priority`
- `all_version_ids`

Observed artifact/version examples:

```text
benchmark_figure.png      version 3a77b5ee-fb87-4414-88db-6a812abcd347
benchmark_metrics.csv     version 5a404d35-5e7d-4363-b859-f99125d18229
gatk_chr20.vcf.gz         version 65e6ef22-6014-47a1-b3d5-bf6378112389
bcftools_chr20.vcf.gz     version b0c47a29-de74-4054-8761-2ed130e92183
benchmark_report.md       version 340cf487-b0c4-4f4c-907a-11128851d88a
benchmark_metrics.json    version 08a60085-88fb-4e8e-b4ad-54b03b412b1e
```

`GET /api/projects/proj_65ee842cd510/frames` returned `Not found` in this
installation; the active UI did not need that route for the observed screen.

## Local Runtime And Source-Like Artifacts

The running local server process:

```text
/Users/matthewzmd/.claude-science/bin/claude-science serve --app --port 8765 --_restart-parent-pid ... --_daemon-child --no-browser
```

The CLI binary is a Mach-O executable, not an importable Python package.

Useful local files inspected:

```text
/Users/matthewzmd/.claude-science/runtime/0.1.0-dev.20260630.t212931.sha2bc1ac8-release/web-dist/index.html
/Users/matthewzmd/.claude-science/runtime/0.1.0-dev.20260630.t212931.sha2bc1ac8-release/web-dist/assets/ProvenancePane-C6bOYqUt.js
/Users/matthewzmd/.claude-science/runtime/0.1.0-dev.20260630.t212931.sha2bc1ac8-release/web-dist/assets/ArtifactTile-Bg__fT_t.js
/Users/matthewzmd/.claude-science/runtime/0.1.0-dev.20260630.t212931.sha2bc1ac8-release/web-dist/assets/useExecutionLog-Cbp70Chl.js
/Users/matthewzmd/.claude-science/runtime/0.1.0-dev.20260630.t212931.sha2bc1ac8-release/web-dist/assets/ConversationView-BRvL6xm6.js
/Users/matthewzmd/.claude-science/orgs/64b93c48-f8b4-4fb8-a8df-4b2a1ea6410f/operon-cli.db
```

`ProvenancePane-C6bOYqUt.js` confirmed the provenance tab model:

- Code
- Execution Log
- Messages
- Environment
- Review

It also confirmed:

- Code can be a generated reconstruction.
- Execution log records are fetched separately.
- Environment data is rendered as a snapshot.
- Review/check results are separate from the artifact content.

`ArtifactTile-Bg__fT_t.js` confirmed:

- Artifact cards and panes load text/binary content by artifact version.
- Artifact lineage uses an `artifact-lineage` query.
- Split view, fullscreen, download, provenance, copy link, rename, delete, and
  export actions are pane-level artifact actions.
- Artifact selection/annotation exists as its own interaction layer, with
  `data-testid="artifact-selection-pill"` and
  `data-testid="artifact-selection-annotate"`.

The bundled client event-routing code includes these relevant event types:

```text
frame_update
frame_messages_delta
text_chunk
text_reset
frame_activity
tool_stdout_chunk
artifact_created
artifact_deleted
artifact_priority_update
artifact_renamed
artifact_moved
lineage_ready
verification_update
environment_status
queued_user_messages
```

The client updates a query cache from these events rather than making the UI own
the agent state directly.

Binary string inspection exposed host SDK fragments and host-call surfaces such
as:

```text
host.lineage
host.artifacts
host.compute
host.agents
host.lineage[version_id]
host.lineage.graph(version_id)
agent_* host-call handlers
```

This supports the architecture inference: the agent/sandbox calls a host SDK;
the host persists cells, messages, artifacts, and lineage; the UI renders those
persisted records.

## SQLite Data Model

Primary tables observed:

```text
projects
frames
frame_messages
execution_log
artifacts
artifact_versions
artifact_dependencies
events
queued_user_messages
host_call_log
host_grants
verification_checks
```

`projects` stores:

- project id/name/description/context
- created/updated timestamps
- user/upload/memory fields

`frames` stores:

- frame id, parent/root frame ids
- agent name and delegate name
- status
- input/output/context data
- model/effort/token/cost fields
- project id
- conversation type
- task summary
- mentioned artifacts
- hidden/status/compute fields

`frame_messages` is deliberately compact:

```sql
PRIMARY KEY(frame_id, idx)
msg_json text not null
```

The message role, content type, tool call, and tool result structures are inside
`msg_json`. An earlier role sample showed 71 user-side messages/events, mostly
tool results, and 58 assistant messages. After the later comparison turns, the
API/database count for the same frame was 136 total frame messages.

Early payload examples included:

- system skill discovery text
- onboarding task text
- assistant `tool_use` for `read_file`
- user `tool_result` for `read_file`
- assistant planning text
- later tool results and assistant tool calls

`execution_log` stores:

- execution cell id
- frame id
- cell index
- kernel id
- conda environment
- language
- source
- stdout/stderr
- exit status
- files written/read
- origin
- detection metadata

For the inspected frame, execution cells included bash and python cells in
`python`, `varcall`, and `_operon` environments. Cells had `ok` or `error`
status and were linked to artifact provenance.

`artifacts` separates artifact identity from content versions:

- artifact id
- project/root/frame ids
- filename
- latest version id
- upload/ephemeral/folder/priority fields

`artifact_versions` stores version content metadata and lineage:

- version id
- artifact id
- version number
- frame id
- content type
- size
- checksum
- storage path
- extracted code
- code description
- lineage messages
- language
- dependency mappings
- environment snapshot
- annotations
- parent version id
- producing cell id
- cell sources
- checkpoint flag

`artifact_dependencies` links artifact versions to input artifact versions.

`host_call_log` records host SDK calls from execution cells. Observed methods:

```text
exec_peek       7 calls
artifact_path   6 calls
query_db        2 calls
exec_interrupt  1 call
```

## Architecture Inference

Claude Science's web UI does not appear to talk directly to the LLM provider as
the primary integration point. The local server owns the host-agent run.

The flow is:

1. Browser UI submits or displays a project/frame conversation.
2. Local server owns the frame and host-agent execution.
3. Agent/tool activity is appended to `frame_messages`, `execution_log`,
   `events`, and artifact tables.
4. The browser renders the transcript from frame messages.
5. The browser listens to event streams or socket-style updates for deltas.
6. Artifact panes read artifact versions and lazy lineage/provenance routes.

The UI is therefore a projection of the host-agent state, not the agent itself.
That is the key pattern for Genomi.

## Known Limits Of This Exploration

- Raw Chrome DevTools HAR was not captured through the available Browser bridge.
- A new Claude Science chat turn was submitted from the browser, but raw
  DevTools network capture was still not available through the Browser bridge.
- The event transport was inferred from the bundled client and event names, not
  packet-captured.
- The installed server is compiled, so backend source was inferred from SQLite
  schema, API behavior, runtime files, and binary strings.

## Genomi Implementation Checkpoint: Result Renderer Registry

Screenshot:
`screenshots/24-genomi-renderer-registry-after-reload.png`

Genomi now uses a small frontend result-renderer registry in
`portal_result_renderers.js`. Built-in evidence panes are registered by
operation name instead of being selected through a closed conditional map:

- `variant.resolve`
- `pharmacogenomics.review_medication`
- `research.build_target_packet`

The registry keeps the open-design lesson without copying open-design's domain:
the shell can stay stable while operation-specific result views are added as
separate renderer modules. The contract remains envelope-first: a renderer is
not called unless the presented payload has a canonical `evidence_envelope`.

Visual inspection in the in-app browser after reload showed the styled Genomi
project portal, artifact workspace, and provenance preview still rendering with
zero browser warnings or errors. `/start` remains outside the product flow; the
workspace route used for this check was
`/projects/proj_4eff6d75d3f7?assetBust=renderer-registry-v1#artifact-workspace`.

## Genomi Implementation Checkpoint: Bounded Project Events

Screenshot:
`screenshots/25-genomi-bounded-project-events-after-long-preview-wait.png`

The project event stream now keeps a bounded per-project replay window instead
of an unbounded process-global event list. This matters because assistant
streaming can emit many `messages_changed` events during one host-agent turn.

The store-side event emission was also collapsed into one normalized workspace
notifier. Frame, message, artifact, and project refresh signals still use the
same event names, but the rules for paired `project_changed` invalidation now
live in one place instead of three separate notify helpers.

Verification:

- Targeted backend project-event tests passed.
- The broader portal/MCP suite passed after the registry change before this
  follow-up.
- The live portal was restarted on `http://localhost:8767/` and reloaded in the
  in-app browser.
- Browser console inspection reported zero warnings or errors after reload.

## Genomi Implementation Checkpoint: Durable Project Event Replay

The project event stream now matches the daemon-style event-plane contract more
closely: project events remain a compact workspace-refresh plane, but the latest
bounded replay window is also written to a sanitized local JSONL log under the
portal state. A restarted portal process can load that window, continue event
ids from the highest persisted event, replay missed events with `?after=...`,
and then keep streaming live changes.

This closes the earlier project-event caveat from the Open Design comparison.
Run events already had durable event-page and result-package readback; project
events now also survive process restart instead of relying only on the in-memory
deque.

Verification:

- `tests/test_mcp_http.py::MCPHTTPTests::test_project_event_stream_replays_persisted_events_after_restart`
  proves an event emitted before clearing the process-local log replays from the
  HTTP SSE endpoint after the log is reloaded from disk.
- Targeted portal HTTP and stream tests passed.
- A throwaway live portal on `http://127.0.0.1:8791/` opened as `Genomi Portal`,
  showed the Research workspace plus Files & Artifacts shell, kept `/start` out
  of the product text, showed Source setup / Source check language, and reported
  zero browser warnings or errors.

Thermonuclear review follow-up:

- Project-event persistence is now root-aware. Portal store mutations that write
  through a non-default root pass that root into project-event notifications, so
  state and durable project-event logs stay under the same Genomi home.
- Project-event durability tests moved out of the broad HTTP suite into focused
  `tests/test_portal_project_events.py` coverage for root isolation, bounded
  durable replay, root-scoped discard, and public-payload redaction.
- Browser run recovery now drains the durable run event-page contract after SSE
  reconnect exhaustion. Missed `agent`, `artifact`, `stdout`, `stderr`, and
  `end` records are dispatched through the same handlers before falling back to
  plain run status.
- `/start` still returned `404 Not Found`.

## Side-By-Side Science Prompt: CYP2C19 And Clopidogrel

Screenshots:

- `screenshots/26-claude-science-workspace-before-question.png`
- `screenshots/28-claude-science-cyp2c19-followup-state.png`
- `screenshots/31-genomi-cyp2c19-followup-state.png`
- `screenshots/32-genomi-assistant-evidence-checklist.png`
- `screenshots/33-genomi-assistant-evidence-checklist-attached.png`
- `screenshots/34-genomi-assistant-evidence-checklist-after-parser-fix.png`
- `screenshots/35-genomi-focused-ask-from-evidence-checklist.png`
- `screenshots/36-genomi-focused-ask-followup-state.png`
- `screenshots/37-genomi-focused-ask-completed-state.png`

Prompt used in both UIs:

```text
In one paragraph, review CYP2C19 evidence for clopidogrel response and list what evidence you would inspect. Do not run long analyses.
```

Claude Science accepted the prompt in the post-onboarding project workspace and
returned a compact answer without launching a heavy notebook workflow. The
notable interaction was not just the prose answer; the response made evidence
sources feel like a workspace object by organizing them into a clear ordered
list and offering a follow-up path to pull live curations.

Genomi also routed the prompt through the web UI to the host agent and produced
a concise answer. Before this checkpoint, the evidence-to-inspect section was
plain assistant text. Genomi now detects explicit "Evidence I would inspect"
sections in assistant answers and renders them as a selectable evidence
checklist. Each node can be selected and attached to the next host-agent turn
through the existing prompt-context tray.

The parser contract was tightened after maintainability review: only explicit
"Evidence I would inspect" headings activate this renderer. Negative prose such
as "No evidence to inspect" is covered by tests and does not create attachable
context.

This is a small but important interaction upgrade: even when the host agent does
not run a Genomi tool, its answer can still create structured, user-selected
context for the next turn without violating evidence-envelope or Active Genome
Index boundaries.

The next checkpoint made that context actionable. When the selected item is an
assistant evidence checklist, Ask now generates a focused follow-up prompt
instead of relying on a generic "review selected evidence" instruction. The
generated turn asks the host agent to identify the smallest relevant Genomi tool
call for each selected source lane, preserve `evidence_envelope` limits, and
summarize what is supported, missing, or out of scope.

The live follow-up completed through the same local project frame. During the
run, the portal showed the evidence-derived user message, attached context
packet, host-agent output, tool chips, and evidence ledger together. After
reload, the completed state remained visible, which is the important
Claude-Science/open-design property: the web UI is projecting persisted
host-agent conversation state, not keeping a separate browser-only chat.

## Genomi Implementation Checkpoint: Persisted Result Views And Selection Inspector

Screenshots:

- `screenshots/38-genomi-persisted-result-view-before-selection.png`
- `screenshots/39-genomi-result-selection-inspector.png`
- `screenshots/40-genomi-result-selection-inspector-viewport.png`
- `screenshots/45-genomi-persisted-redacted-result-view.png`
- `screenshots/46-genomi-persisted-redacted-expanded-result.png`
- `screenshots/47-genomi-persisted-redacted-selection-inspector.png`
- `screenshots/41-claude-science-rs429358-evidence-lanes.png`
- `screenshots/42-claude-science-rs429358-evidence-lanes-visible.png`
- `screenshots/43-claude-science-rs429358-transcript-evidence-lanes.png`
- `screenshots/44-claude-science-rs429358-lane-list.png`

Comparable prompt submitted to Claude Science:

```text
In one paragraph, review public rs429358 evidence and list the evidence lanes you would inspect. Do not run long analyses.
```

Claude Science again produced a compact science answer and then made the next
work visible as explicit evidence lanes: variant identity/haplotype definition,
GWAS evidence, Open Targets aggregation, ClinVar/clinical annotation,
meta-analysis/dosage studies, population frequencies, and functional biology.
The useful UX pattern is not the specific content; it is that the answer creates
a structured evidence map the user can reason over before asking for live
retrieval.

Genomi now carries that pattern one step deeper for actual Genomi tool results.
Persisted canonical evidence tool results retain an allowlisted, sanitized
presented payload after reload. Raw/private payload fields such as
`sample_context` and path-bearing fields are not persisted in the public message
shape, but renderer-critical public fields such as `headline`, `query`,
`resolved_targets`, `public_context`, `evidence_envelope`, and
`defaults_applied` are preserved.

With that presented payload available, a reloaded `variant.resolve` result can
render the purpose-built Variant Evidence Map rather than only a raw result
summary. A thermo-nuclear review tightened the boundary here: persisted
history renders with `presentation_state="persisted_redacted"`, shows only
public lanes, and is not attachable to a follow-up turn. Selecting a result
node still opens a local selection inspector inside the result view so the user
can inspect the selected source lane, node label, and redacted context, but the
portal omits "Use selected view" and "Copy view" actions for persisted history.
Live/current canonical Genomi results remain the attachable surface; saved
history should be re-checked before it is reused as evidence.

Visual verification:

- The persisted `variant.resolve` frame rendered a redacted Genomi result view
  after reload with the notice: "Persisted redacted history".
- The expanded result view showed only `Resolved targets` and `ClinVar records`
  lanes, with no `Sample context`, `Genotype support`, `Sample hits`, or
  `Support` metric.
- The result view had zero attach actions and zero "Use selected view" or
  "Copy view" buttons.
- Selecting a result node showed one visible result selection inspector without
  enabling attachment.
- Browser text did not include `/Users`, `context_file`, or the fixture private
  path marker.
- Genomi and Claude Science browser console checks reported no warnings or
  errors.

## Genomi Implementation Checkpoint: Provenance-Aware Context Prompts

Screenshot:

- `screenshots/48-genomi-artifact-context-focused-prompt.png`
- `screenshots/49-genomi-ledger-recheck-focused-prompt.png`

The selected-context tray now treats the per-card `Prompt` action as a real
agent handoff affordance instead of a placeholder. Clicking `Prompt` on an
attached context packet writes a provenance-aware draft into the composer:

- assistant evidence checklists ask for the smallest relevant Genomi tool call
  for each selected source lane;
- selected Genomi result nodes ask for a focused evidence step from the source
  operation, preserving `evidence_envelope` limits and source priors;
- selected genome context reminds the host agent that Active Genome Index state
  is a current-session boundary;
- artifact packets keep artifact/provenance wording even when their source
  operation is a renderer operation such as `decode.render_dashboard`.

Visual verification used the live Genomi portal. A legacy report artifact
fixture, stored at the time with the title `Genomi Dashboard`, was attached
from the workspace, then its context-card `Prompt` action populated the
composer with:

```text
Review the selected Genomi artifact context, preserve its provenance and evidence limits, and tell me what follow-up evidence step should come next.
```

The browser assertion confirmed the old placeholder text was absent, the
selected chip was visible, and the console had no warnings or errors.

The evidence ledger now uses the same provenance-aware handoff rule. For a
persisted-redacted `variant.resolve` entry, the detail action is labeled
`Re-check tool` and writes a current-evidence prompt instead of sending stale
history back as if it were live evidence:

```text
Re-check variant.resolve with current Genomi tools before making evidence claims. Use the saved persisted-redacted view only as a pointer to public lanes, preserve evidence_envelope limits, and report what current evidence supports, what is missing, and what is out of scope.
```

The visual check confirmed that the old `Use the variant.resolve result above`
stub was absent, no selected-context chip was active, and the browser console
had no warnings or errors.

## Genomi Implementation Checkpoint: Artifact Versions In Provenance UI

Screenshots:

- `screenshots/52-genomi-artifact-version-provenance.png`
- `screenshots/53-genomi-artifact-version-provenance-detail.png`
- `screenshots/54-genomi-artifact-version-file-url-detail.png`
- `screenshots/55-genomi-artifact-version-file-evidence-tab.png`
- `screenshots/56-genomi-artifact-hydrated-version-history.png`
- `screenshots/57-genomi-artifact-ask-selected-action.png`

The portal now separates artifact identity from immutable artifact file
versions. A generated `evidence_packet` artifact gets a version record with its
own `version_id`, `created_at`, `content_type`, `size_bytes`, and
`sha256` checksum. Public artifact payloads expose the latest version summary
and version count, while the internal snapshot path stays out of the browser
API.

The visual check used a fresh `research.build_target_packet` artifact for
`rs429358`. The artifact Evidence tab rendered provenance cells for:

- `Latest version`
- `Version count`
- `Version content type`
- `Version checksum`
- `Version size`

The browser-side inspection also checked the rendered page text for path
leakage and did not find `/Users`, `/tmp`, or `file://`. The important UX lesson
from Claude Science is the same one visible here: artifacts are not just files
to preview. They are replayable research objects with attached provenance,
version identity, and review state in the same project workspace as the chat.

A follow-up thermo-nuclear review found that the first pass still treated the
artifact row as the file owner. The hardened checkpoint makes artifact versions
canonical for file blobs: the backend exposes `/api/artifacts/versions/{version_id}/file`,
the old artifact `/file` route remains only a latest-version convenience, and
the frontend now prefers the immutable version-file URL whenever a latest
version exists. The post-review browser check confirmed the Evidence tab showed
`Artifact URL` as `/api/artifacts/versions/ver_458a2c0ea7f0/file`, did not show
the old `/api/artifacts/art_850526a0c356/file` URL, and still had no `/Users`,
`/tmp`, or `file://` leakage.

The next implementation slice moved artifact inspection closer to the
open-design/Claude Science pattern: artifact cards still render from lightweight
project summaries, but opening the split pane now hydrates the artifact through
explicit detail and version routes. The live server stream showed the page
calling `/api/artifacts/art_850526a0c356` and
`/api/artifacts/art_850526a0c356/versions` after loading project artifacts.
The hydrated Evidence tab increased from 14 to 16 provenance nodes and rendered
`Version history: 1 loaded version` plus `Version ids: ver_458a2c0ea7f0`.

The artifact pane now also exposes the next-turn action directly in the visual
surface. Selecting artifact nodes shows `Use selection` and `Ask selected` in
the selection bar. `Use selection` attaches the selected visual nodes to the
composer context tray; `Ask selected` sends the same packet through the normal
prompt-context controller and host-agent submit path with the artifact
follow-up prompt. This preserves the existing Genomi evidence report boundary
while reducing the interaction distance from "visual evidence I selected" to
"ask the host agent about this selected evidence."

## Genomi Implementation Checkpoint: Live Result Ask Selected

Screenshots:

- `screenshots/58-genomi-live-result-ask-selected.png`
- `screenshots/59-genomi-live-result-ask-submitted.png`

The next-turn action now also exists on live Genomi result panes. A streamed
`variant.resolve` result exposes `Ask selected` beside `Use selected view` and
`Copy view`. Selecting a result node opens the inline selection inspector, then
`Ask selected` sends that selected node through the same prompt-context
controller and host-agent submit path used by artifact context.

The browser check uncovered an important lifecycle bug before the final
screenshot: the project `messages_changed` refresh could reload the current
frame from persisted history immediately after a live tool result arrived. That
converted the live card into a persisted-redacted, display-only card and erased
the ask action. The portal now keeps a `liveMessageFrameId` guard for the active
frame so project refresh events do not clobber runtime tool cards. A normal page
reload or frame navigation still falls back to persisted-redacted history, which
keeps stale tool payloads non-attachable.

The final visual pass used a temporary local fixture host-agent stream that
emitted the same JSON event shape as Claude Code: text, a `variant.resolve`
tool call, and a canonical result with an `evidence_envelope`. The first
screenshot shows the selected `rs429358` result node and visible `Ask selected`
button. The second screenshot shows the generated follow-up message with
`1 selected evidence item` and an `Evidence attached` chip for `rs429358`.

## Second Authenticated Claude Science Pass: Library And Provenance

Screenshots:

- `screenshots/60-browser-current-state.png`
- `screenshots/61-claude-science-project-reopen.png`
- `screenshots/62-claude-science-library-pane.png`
- `screenshots/63-claude-science-library-artifact-split.png`
- `screenshots/64-claude-science-split-artifact-actions.png`
- `screenshots/65-claude-science-library-provenance-pane.png`
- `screenshots/66-claude-science-library-execution-log.png`
- `screenshots/67-claude-science-library-provenance-messages.png`

The second visible-browser pass reopened the authenticated Claude Science
project workspace after the Genomi Ask-selected checkpoint. The starting Genomi
capture shows the current target for parity: chat, selected context, submitted
host-agent follow-up, and the artifact tray all active in one workspace.

Reopening `http://localhost:8765/projects/proj_65ee842cd510` landed directly
on the project/frame workspace, not onboarding. The visible product surface
included session navigation, model/session controls, Library access, grouped
tool work, transcript messages, and the composer. This reinforces the main
product lesson: Claude Science makes the project workspace the first real
surface after setup.

Opening Library showed a project artifact browser rather than an external file
manager. The pane has search, layout controls, grouped artifact sections,
split-open buttons, download controls, and per-artifact menus. Artifacts are
therefore first-class project state attached to the same frame history as the
chat.

Opening `benchmark_figure.png` from Library placed the artifact in the split
workspace. The artifact stayed next to the transcript and carried pane-local
actions: open-in-split, download, more actions, and close. The more-actions
menu again exposed Star, Hide, View in context, Provenance, Copy link, Rename,
Export Metadata, Export to Cloud, and Delete. Genomi should copy the
interaction shape, but prioritize the scientific actions first: View in
context, Provenance, Copy link, versioned download/export, and metadata.

The Provenance action opened an inline provenance pane over the selected
artifact. The Code tab showed generated reconstruction text, an input artifact
chip for `benchmark_metrics.json`, and a Download script action. This is not
raw source-of-truth code; it is a reconstruction product attached to the
artifact. Genomi should label any synthesized replay script the same way and
avoid pretending it is the exact original host-agent implementation.

The Execution Log tab showed numbered bash/python cells, code blocks, copy
controls, file writes, and success/error states. This is the strongest visual
model for Genomi's artifact Tools tab: MCP calls, background jobs, library
materialization, renderer steps, and host-agent calls should be inspectable as
a replayable sequence rather than hidden behind a static artifact card.

The Messages tab showed the transcript slice that produced the artifact,
including step groups, tool outputs, correction turns, and artifact-save turns.
This is the key UI/architecture behavior: provenance reaches back into the
host-agent conversation. The artifact is not only linked to a file; it is linked
to the messages, tools, and execution steps that made it.

The authenticated API and SQLite checks support what the UI shows:

- `GET /api/projects/proj_65ee842cd510` returns project metadata and persisted
  onboarding context.
- `GET /api/frames/991ad887-1322-458d-9f87-91201044b16f/messages` returns the
  persisted frame transcript.
- `GET /api/projects/proj_65ee842cd510/artifacts` returns artifact/version
  records for the project.
- The local SQLite database has separate `projects`, `frames`,
  `frame_messages`, `execution_log`, `artifacts`, `artifact_versions`,
  `artifact_dependencies`, `events`, `host_call_log`, and
  `verification_checks` tables.
- In the current inspected state, the project has 8 frames, 7 artifacts, 40
  execution-log cells for the selected frame, and 136 persisted frame messages.

The shipped web bundle also matches the observed behavior. The project control
bundle calls high-level submit methods named `submitRequest` and
`submitProjectRequest`, passing `target_agent`, frame/project ids, input text,
model settings, mode flags, `viewport_context`, and an intent id. The same
bundle defines a client event map for frame, message, artifact, lineage,
environment, connector, verification, and execution-cell updates. The browser
therefore acts as a projection over persisted local host-agent state, with live
events keeping that projection fresh.

## Genomi Implementation Checkpoint: Artifact Origin Messages

Screenshot:

- `screenshots/68-genomi-artifact-messages-provenance.png`
- `screenshots/69-genomi-bounded-artifact-messages.png`

Genomi artifact detail now supports Claude-Science-style message lineage. When
an artifact is tied to a frame, the artifact stores an explicit origin snapshot:
the validated frame id and the message ids present when the artifact is
created. The detail API includes a public `provenance_messages` block derived
from that bounded snapshot, plus a compact `origin_context` action contract.
Project artifact lists and artifact render-stream events use the explicit
summary shape and do not include the transcript slice.

The artifact split pane now renders a `Messages` provenance tab when that block
is present. The tab uses the same selectable node surface as Evidence, Tools,
State, and Review: user messages, tool results, and assistant save messages can
be selected, attached, or sent through `Ask selected` as typed artifact context.
Frontend rendering is capped with `total`, `displayed`, and `has_more`
metadata so large frame histories do not turn into unbounded selected context.

Visual verification used a seeded local project at
`http://127.0.0.1:8767/projects/proj_992946bd96d4#artifact-workspace` with an
artifact created from a completed host-agent frame through the current bounded
origin path. The browser check opened the artifact split pane, selected the
Messages tab, and confirmed:

- `Messages` was the active artifact tab.
- Three origin messages rendered: user, `variant.resolve` tool result, and the
  assistant message saved before artifact creation.
- A later assistant message appended to the frame after artifact creation did
  not appear in artifact provenance.
- The page text did not include raw `/Users`, `/tmp/private`, or
  `/usr/local/bin` paths.
- The public panel exposed `Displayed 3` and `Total 3`, matching the bounded
  origin snapshot.

Verification:

- `PYTHONPATH=src pytest tests/test_portal_store.py tests/test_portal_runs.py tests/test_portal_frontend_artifact_models.py tests/test_portal_artifact_evidence_packet.py tests/test_mcp_http.py -k 'artifact or portal_store or artifact_models'`: 34 selected tests passed.
- `find src/genomi/interfaces/templates -maxdepth 1 -type f -name '*.js' -exec node --check {} \;`
- broader portal suite through `tests.test_genomi_install`: 105 tests passed.

## Genomi Implementation Checkpoint: Artifact View Context

Screenshots:

- `screenshots/70-genomi-artifact-view-context-action.png`
- `screenshots/71-genomi-artifact-view-context-frame.png`

Genomi now has a first direct analogue to Claude Science's artifact `View in
context` action. Hydrated artifact detail exposes a compact `origin_context`
separate from the bounded `provenance_messages` transcript slice. When that
origin context has a frame id, the split pane shows a `View in chat` button
beside `Use selected`, `Review brief`, and `Open report`.

Clicking `View in chat` opens the existing project frame route for the origin
frame and switches the workspace back to chat. This reuses the same
conversation-loading path as the sidebar rather than creating a parallel
artifact-only transcript. The frame can show later messages that are not part
of the artifact's bounded provenance snapshot, which is the desired distinction:
the artifact Messages tab is a creation-time lineage slice, while View in chat
is the full host-agent frame.

Visual verification used the same bounded provenance fixture at
`http://127.0.0.1:8767/projects/proj_992946bd96d4#artifact-workspace`.
The browser check confirmed:

- The hydrated artifact header exposed `View in chat`.
- Clicking it navigated to
  `/projects/proj_992946bd96d4/frames/e250be3a-a759-4faf-b993-376a9695f6b8#research-workspace`.
- The Research workspace scrolled into view after a small shell fix:
  `activateWorkspaceSection` now scrolls before focusing the prompt with
  `preventScroll`.
- The visible frame contained the redacted original request, the
  `variant.resolve` tool result, and no raw local source path.
- Browser console errors after the interaction: none.

Verification:

- `node --check src/genomi/interfaces/templates/portal.js && node --check src/genomi/interfaces/templates/portal_artifacts.js && node --check src/genomi/interfaces/templates/portal_artifact_messages.js`
- `PYTHONPATH=src pytest tests/test_portal_frontend_artifact_models.py tests/test_portal_frontend_assets.py`: 12 tests passed.

Follow-up hardening added automated coverage for the model/rendered-preview
action seam and an asset-level check that frame sidebar clicks and artifact
`View in chat` both use the same prepare-then-commit frame-opening helper. The
current lightweight frontend tests do not run the full portal shell in a
browser DOM.

## Genomi Implementation Checkpoint: Persisted Tool Re-check

Screenshots:

- `screenshots/72-genomi-persisted-tool-recheck-card.png`
- `screenshots/73-genomi-persisted-tool-recheck-prompt.png`

Genomi's reopened conversation history now treats persisted tool results as
display-only evidence pointers instead of reusable evidence reports. A stored
`variant.resolve` result can keep its public presented payload, including the
`evidence_envelope`, query, resolved targets, public ClinVar lane, and defaults,
but the card explicitly labels the view as `Persisted redacted history`.
Private/sample and support sections are omitted from the reopened display.

The ordinary transcript tool-card actions now use the same provenance-aware
follow-up model as the evidence ledger. For a live/current result, the card can
still draft an `Ask follow-up` prompt that uses the current result. For a
persisted-redacted or display-only result, the card shows `Re-check tool` and
drafts a prompt that asks the host agent to call current Genomi tools before
making evidence claims.

Visual verification used a seeded local project at
`http://127.0.0.1:8767/projects/proj_c2c2c0b6049f/frames/7e73a427-6e97-4390-be16-1d6659d12f58`.
The browser check confirmed:

- The reopened `variant.resolve` card renders public result lanes.
- The notice says persisted history omits private/sample and support sections.
- The card action is `Re-check tool`, not generic `Ask follow-up`.
- Clicking `Re-check tool` focuses the chat box and drafts a prompt beginning
  `Re-check variant.resolve with current Genomi tools before making evidence
  claims`.
- The prompt names the saved `persisted-redacted view` as a pointer only and
  asks for current support, missing evidence, and out-of-scope evidence.

Verification:

- `node --check src/genomi/interfaces/templates/portal_tool_result_presentation.js && node --check src/genomi/interfaces/templates/portal_tool_details.js`
- `PYTHONPATH=src pytest tests/test_portal_frontend_assets.py -k evidence_renderer_is_canonical_envelope_first`
- `PYTHONPATH=src pytest tests/test_portal_frontend_assets.py tests/test_portal_store.py tests/test_portal_stream.py`: 38 tests passed.
- All `src/genomi/interfaces/templates/*.js` files passed `node --check`.
- Browser console errors after the visual interaction: none.

## Genomi Implementation Checkpoint: Frame Work Trail

Screenshots:

- `screenshots/74-genomi-frame-work-trace-pane.png`
- `screenshots/75-genomi-work-trace-summary-context.png`
- `screenshots/76-genomi-work-trace-inspect-step.png`
- `screenshots/86-genomi-work-trace-scrolled-post-review.png`

Genomi now has a first frame-level analogue to Claude Science's execution-log
surface. The Work trail pane is derived from the same sanitized frame messages
used by the transcript. It does not add a new private backend channel: user and
assistant messages remain in the transcript, while tool calls, tool results,
and errors are projected into ordered trace steps.

The trace model pairs matching `tool_call` and `tool_result` messages by
frame, run, operation, and tool id. Each step shows operation, status, compact
summary, run/message scope, and a provenance-aware `Re-check tool` action for
display-only or persisted-redacted history. Errors remain visible as their own
steps instead of disappearing into chat prose.

The pane also has a `Use trace summary` action. It attaches a bounded
`work_trace` selected-context packet to the next host-agent turn, with one node
per recent trace step. This matches the broader portal rule: visual workspace
state can be selected and sent back into chat, but persisted/redacted evidence
remains a pointer for re-checking rather than a fresh evidence claim.

`Inspect step` opens a nested step detail. For canonical Genomi results, that
detail reuses the purpose-built result renderer, so a trace step can reveal the
same public evidence map, metrics, lanes, and persisted-redacted warning that
the transcript tool card shows. This is the closest current Genomi equivalent
to Claude Science's execution-log cells plus provenance drilldown.

Visual verification used a seeded local project at
`http://127.0.0.1:8767/projects/proj_a2e2a10dda60/frames/c9fc15a9-382d-4aa7-83c4-24487bafaa03#work-trace-pane`.
The browser check confirmed:

- The Work trail nav item and pane render in the right workspace stack.
- A paired `variant.resolve` call/result collapses into one completed step.
- A `research.build_target_packet` error remains visible as a separate error
  step.
- `Use trace summary` attaches `Frame work trace` as selected context for the
  next turn.
- `Inspect step` opens the nested `variant.resolve` evidence map with the
  persisted-redacted notice intact.
- Browser console errors after the interaction: none.

Post-review hardening tightened the trace pairing contract: live and persisted
events now group by frame id, run id, and tool-call id, and a result event with
no operation name inherits the call operation instead of becoming a generic
`tool` step. The portal server also gates portal pages, assets, and portal
APIs on both a loopback client address and a loopback/localhost Host header,
while leaving `/mcp` available for normal MCP clients.

The post-review browser check used the same seeded frame after restarting
`genomi serve` on `http://127.0.0.1:8767/`. The viewport was scrolled to the
Work trail section and captured as
`screenshots/86-genomi-work-trace-scrolled-post-review.png`. It showed the two
ordered trace steps, the persisted-redacted re-check actions, and the already
attached `Frame work trace` selected context. Browser console errors were
empty.

Verification:

- `PYTHONPATH=src pytest tests/test_portal_frontend_frame_trace.py tests/test_mcp_http.py`: 35 tests passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_frame_trace.py tests/test_portal_frontend_assets.py tests/test_portal_store.py tests/test_portal_stream.py tests/test_mcp_http.py -k 'portal or frame_trace or mcp_http'`: 73 tests passed.
- All `src/genomi/interfaces/templates/*.js` files passed `node --check`.
- `PYTHONPATH=src python3 -m py_compile src/genomi/interfaces/mcp.py src/genomi/interfaces/portal_assets.py`
- Screenshot references in `docs/research/claude-science-portal-study/*.md`
  resolve to existing files.

## Genomi Implementation Checkpoint: Evidence Node Inspector

Screenshots:

- `screenshots/88-genomi-evidence-node-inspector-viewport.png`

The generic canonical-envelope evidence panel now mirrors the richer
purpose-built result views: clicking envelope nodes selects them and opens an
inline inspector below the evidence sections. The inspector lists the selected
node labels and prompt-safe context text, so a user can see exactly what will
be attached before using `Attach selected evidence`, `Copy selected`, or
`Ask selected`.

This is a small but important Claude-Science-style interaction: evidence
chunks are not just decorative pills. They are inspectable units of context.
The selected-node payload still goes through the existing
`selectedEvidencePayload` redaction path, preserving the current rule that
private paths and sensitive local fields are scrubbed before reaching the next
host-agent turn.

Visual verification used the localhost fixture at
`docs/research/claude-science-portal-study/evidence-node-inspector-fixture.html`,
served temporarily from the repo root. The fixture imports the real
`portal.css` and `portal_evidence_panel.js`, renders a current
`custom.evidence_probe` canonical envelope, selects two guidance nodes, and
captures the visible inspector. The browser check confirmed:

- 8 envelope nodes rendered from guidance, coverage, observations,
  next-actions, and defaults.
- 2 guidance nodes were selected.
- The inspector was visible and showed the selected guidance context.
- Browser console errors after the fixture interaction: none.

Post-review hardening fixed a selected-context routing bug found by the
thermo-nuclear review pass. The outer tool-result context path previously
treated selected `.evidence-node` chips as generic result nodes when the user
used a wrapper-level action, which could mislabeled selected envelope context
as `result_nodes`. The routing now keeps evidence-node selections as
`context_kind="evidence_panel"` with the canonical envelope metadata preserved,
while result-only selections remain `result_nodes`. The result-node and
evidence-node inspectors now share `portal_selection_inspector.js` and common
`.genomi-selection-inspector` CSS instead of maintaining parallel inspector
implementations.

The refreshed fixture screenshot shows the shared inspector class
`evidence-node-inspector genomi-selection-inspector`, 8 envelope nodes, 2
selected guidance nodes, and no browser console errors.

Verification:

- `PYTHONPATH=src pytest tests/test_portal_frontend_assets.py`: 8 tests passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_assets.py tests/test_portal_frontend_frame_trace.py tests/test_portal_frontend_artifact_models.py -k 'evidence or frame_trace or artifact'`: 14 tests passed.
- All `src/genomi/interfaces/templates/*.js` files passed `node --check`.
- Screenshot references in `docs/research/claude-science-portal-study/*.md`
  resolve to existing files.

## Genomi Implementation Checkpoint: Selected Context Tray Inspector

Screenshots:

- `screenshots/89-genomi-selected-context-tray-node-inspector.png`

The selected-context tray now completes the loop from visual evidence to next
turn. Once evidence has been attached, each packet node can be selected inside
the tray before the user sends the next host-agent message. The tray then opens
the shared `genomi-selection-inspector`, showing the exact selected node label
and prompt-safe context text.

This matters because Claude-Science-style interaction is not only selecting
evidence from the original result. Users also need to inspect and trim the
attached evidence after it has moved into the composer/workspace state. The tray
already supported node removal; now it also exposes full node context before
removal, prompt drafting, copying, or sending.

The prompt contract was tightened at the same time. Attached
`context_kind="evidence_panel"` packets now draft prompts as selected Genomi
evidence, not as generic result nodes. `context_kind="result_nodes"` keeps the
existing result-node wording. Rebuilding a packet after node removal preserves
the original context kind.

Visual verification used the live Genomi portal at
`http://127.0.0.1:8767/projects/proj_931ea170d8ba/frames/796406c3-680c-4c5c-9f4c-24e88d073a30`.
The browser check confirmed:

- The workspace tray had one attached `Frame work trace` packet with two nodes.
- Selecting the first packet node opened
  `evidence-tray-node-inspector genomi-selection-inspector`.
- The inspector showed one selected packet node with the full work-trace
  context text.
- Browser console errors after the interaction: none.

Verification:

- `PYTHONPATH=src pytest tests/test_portal_frontend_prompt_context.py`: 1 test passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_prompt_context.py tests/test_portal_frontend_assets.py tests/test_portal_frontend_frame_trace.py -k 'prompt_context or evidence or frame_trace or assistant_evidence_checklist'`: 10 tests passed.
- All `src/genomi/interfaces/templates/*.js` files passed `node --check`.
- Screenshot references in `docs/research/claude-science-portal-study/*.md`
  resolve to existing files.

Post-review hardening fixed two contract issues found by an independent
thermo-nuclear review pass:

- Mixed selected context now preserves its wording boundary. Selected Genomi
  result nodes and selected canonical-envelope evidence are described as
  separate groups in the drafted follow-up prompt instead of being collapsed
  under whichever kind appeared first.
- Server-side selected-evidence sanitization now preserves only whitelisted
  non-authoritative metadata such as `context_kind`, finding/readiness state,
  operation ids, and node counts. Raw `evidence_envelope` and browser payload
  blobs remain excluded from persisted selected context.

The tray rendering and packet rebuild behavior moved into
`portal_prompt_context_tray.js`, leaving `portal_prompt_context.js` focused on
composer orchestration, storage, and prompt drafting.

The post-review browser check used the same live frame after reloading the
Genomi portal. The first `Frame work trace` packet node was selected and
captured as `screenshots/90-genomi-selected-context-tray-post-review.png`.
The browser check confirmed:

- One attached tray packet and two packet nodes remained after reload.
- Selecting the first packet node opened
  `evidence-tray-node-inspector genomi-selection-inspector`.
- The inspector showed one selected packet node with the variant-resolve
  work-trace context.
- Browser console warnings/errors after the interaction: none.

Additional verification:

- `PYTHONPATH=src pytest tests/test_portal_frontend_prompt_context.py`: 2 tests passed.
- `PYTHONPATH=src pytest tests/test_portal_runs.py -k 'selected_evidence or selected_node or compose_prompt'`: 4 tests passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_assets.py -k 'assistant_evidence_checklist or evidence_renderer_is_canonical_envelope_first or selected_context or selected_result'`: 3 tests passed.
- `PYTHONPATH=src pytest tests/test_portal_store.py::PortalStoreTests::test_project_frame_and_messages_persist_to_genomi_home tests/test_portal_store.py::PortalStoreTests::test_artifact_detail_includes_bounded_origin_frame_messages`: 2 tests passed.
- `PYTHONPATH=src pytest tests/test_mcp_http.py::MCPHTTPTests::test_project_request_creates_persistent_frame_messages tests/test_mcp_http.py::MCPHTTPTests::test_portal_static_app_assets`: 2 tests passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_prompt_context.py tests/test_portal_frontend_assets.py tests/test_portal_frontend_frame_trace.py -k 'prompt_context or evidence or frame_trace or assistant_evidence_checklist'`: 11 tests passed.
- All `src/genomi/interfaces/templates/*.js` files passed `node --check`.

## Genomi Implementation Checkpoint: Artifact Origin Trace Tab

Screenshots:

- `screenshots/91-genomi-artifact-origin-trace-tab.png`

Claude Science's artifact provenance makes the execution log visible beside
the artifact. Genomi now maps the same interaction into the artifact split pane
without inventing a second provenance source: when artifact detail includes a
bounded origin message slice, the frontend derives an `Origin work trace` from
those sanitized messages using the same frame work-trace model as the workspace
pane.

The artifact provenance tabs now include:

- Preview
- Evidence
- Tools
- Trace
- Messages
- State
- Review

The Trace tab turns origin-frame tool work into selectable artifact nodes. This
keeps the Claude-Science-style interaction loop intact: the user can inspect a
generated artifact, open how it was produced, select a trace step, and attach
that prompt-safe selected material to the next host-agent turn through the
existing artifact selection actions.

Visual verification used the live Genomi portal at
`http://127.0.0.1:8767/projects/proj_931ea170d8ba/frames/796406c3-680c-4c5c-9f4c-24e88d073a30`.
An `evidence_packet` artifact for `rs429358` was rendered through the portal
artifact API with the current frame as origin. After reload, opening the
artifact split pane showed a `Trace` tab with one origin work step. The browser
check confirmed:

- Artifact tabs included `Trace 1`.
- The Trace panel rendered `Origin work trace` with `Steps 1`, `Displayed 1`,
  `Errors 0`, and `Running 0`.
- Selecting the trace node updated the artifact selection bar to
  `1 selected artifact node`.
- The selected trace node context was prompt-safe and browser console
  warnings/errors were empty.

Verification:

- `node --check src/genomi/interfaces/templates/portal_artifacts.js`
- `node --check src/genomi/interfaces/templates/portal_frame_trace.js`
- `PYTHONPATH=src pytest tests/test_portal_frontend_artifact_models.py`: 5 tests passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_frame_trace.py -k frame_trace`: 5 tests passed.

The thermo-nuclear review for this milestone flagged the first implementation
as structurally too concentrated: `portal_artifacts.js` had crossed 1000
lines, artifact trace derivation lived in the artifact shell, and the trace
context string duplicated frame-trace logic.

Post-review hardening fixed the boundary:

- `portal_artifact_origin_trace.js` now owns the
  `provenance_messages -> frameWorkTraceModel -> artifact tab model` adapter.
- `portal_frame_trace.js` exports the canonical frame trace context-node
  helper used by both frame summary context and artifact origin trace.
- `portal_artifacts.js` consumes the final trace model and re-exports it for
  compatibility with the existing frontend model tests; its line count dropped
  below the 1000-line review threshold.
- Trace-specific tests moved into
  `tests/test_portal_frontend_artifact_origin_trace.py`, leaving the larger
  artifact model fixture to cover tab presence and broader artifact behavior.

The post-review live browser check reloaded the same Genomi project, opened the
same evidence-packet artifact, selected the Trace tab, selected the single trace
node, and captured
`screenshots/92-genomi-artifact-origin-trace-post-review.png`. Browser console
warnings/errors were empty.

Additional verification:

- `PYTHONPATH=src pytest tests/test_portal_frontend_artifact_origin_trace.py`: 3 tests passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_artifact_models.py tests/test_portal_frontend_frame_trace.py tests/test_portal_frontend_artifact_origin_trace.py -k 'artifact or frame_trace or trace'`: 13 tests passed.
- All `src/genomi/interfaces/templates/*.js` files passed `node --check`.
- Screenshot references in `docs/research/claude-science-portal-study/*.md`
  resolve to existing files.

## Genomi Implementation Checkpoint: Artifact Selection Inspector

Screenshots:

- `screenshots/93-genomi-artifact-selection-inspector.png`

Artifact provenance nodes can already be selected and sent into the next
host-agent turn, but the artifact pane only showed a count before this
checkpoint. The artifact split pane now mirrors result/evidence/tray
inspection: selected artifact nodes open the shared
`genomi-selection-inspector` immediately below the selection bar.

This makes the artifact interaction loop explicit:

- Select a node inside artifact Evidence, Tools, Trace, Messages, State, or
  Review.
- Inspect the exact prompt-safe context that will be attached.
- Use `Use selection` or `Ask selected` without relying on a hidden payload.

Implementation notes:

- `portal_artifact_selection.js` owns artifact selection counts and inspector
  rendering.
- `portal_artifacts.js` re-exports the selection model for existing callers,
  but no longer owns the selected-node count/inspector logic.
- The artifact shell line count dropped to `937`, keeping it below the
  1000-line review threshold after adding the inspector.

Visual verification used the same live Genomi portal frame and evidence-packet
artifact as the Trace-tab checkpoint. After a full reload, the Trace tab was
opened and its single origin work-trace node was selected. The browser check
confirmed:

- The artifact selection bar reported `1 selected artifact node`.
- `artifact-selection-inspector genomi-selection-inspector` was visible.
- The inspector showed the selected `custom.evidence_probe` trace-node context.
- Browser console warnings/errors after the interaction: none.

Verification:

- `node --check src/genomi/interfaces/templates/portal_artifacts.js`
- `node --check src/genomi/interfaces/templates/portal_artifact_selection.js`
- `node --check src/genomi/interfaces/templates/portal_selection_inspector.js`
- `PYTHONPATH=src pytest tests/test_portal_frontend_artifact_selection.py tests/test_portal_frontend_artifact_models.py tests/test_portal_frontend_artifact_origin_trace.py -k 'artifact or selection or trace'`: 9 tests passed.

The thermo-nuclear review for this milestone found that the first
implementation still had a split boundary: the inspector parsed selected DOM
nodes separately from the outgoing selected-context payload, and
`portal_artifacts.js` still owned most selection-control wiring.

Post-review hardening fixed both issues:

- `portal_artifact_selection.js` now owns artifact selection markup, selected
  node normalization, selected count state, shared inspector rendering,
  select-all, clear, Use selection, and Ask selected wiring.
- `artifactContextForSelection` receives the canonical normalized selected-node
  array through `artifactSelectedNodes`, so the inspector and outgoing selected
  context use the same prompt-safe node shape.
- `portal_selection_inspector.js` can render either DOM nodes or normalized
  selected-context node objects.
- The artifact shell dropped to `903` lines after moving selection controls out
  of it.
- A focused DOM integration test now renders an artifact preview, clicks an
  artifact node, checks redacted inspector text, clicks `Use selection`, and
  verifies the emitted `selected_nodes` match the canonical normalized nodes.

The post-review live browser check reloaded the same Genomi project and
artifact, opened the Trace tab, selected the trace node, and captured
`screenshots/94-genomi-artifact-selection-inspector-post-review.png`. Browser
console warnings/errors were empty.

Additional verification:

- `PYTHONPATH=src pytest tests/test_portal_frontend_artifact_selection.py`: 2 tests passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_artifact_selection.py tests/test_portal_frontend_artifact_models.py tests/test_portal_frontend_artifact_origin_trace.py tests/test_portal_frontend_frame_trace.py tests/test_portal_frontend_assets.py -k 'artifact or selection or trace or frame_trace or evidence'`: 19 tests passed.
- All `src/genomi/interfaces/templates/*.js` files passed `node --check`.

## Genomi Implementation Checkpoint: Evidence Ledger Selection

Screenshots:

- `screenshots/95-genomi-evidence-ledger-baseline.png`
- `screenshots/98-genomi-evidence-ledger-display-only-fullpage.png`
- `screenshots/101-genomi-evidence-ledger-display-only-hash.png`

The Evidence Ledger already had the important policy split: live/current
entries can be reused, while persisted/display-only entries route the user to a
fresh tool re-check. Visual inspection of the current live portal frame showed
the persisted side of that split clearly: the ledger detail displays a compact
stored summary and only offers `Re-check tool`.

The implementation gap was on the reusable/live side. When a live ledger detail
renders nested result/evidence panels, node selection technically worked, but
there was no ledger-level selection bar or shared inspector to show the exact
node context that would be sent back into the next host-agent turn.

Implementation notes:

- `portal_evidence_ledger_selection.js` now owns reusable ledger selected-node
  collection, selection summary text, shared inspector rendering, clear, and
  the `Use selected`/`Use evidence` action.
- `portal_evidence_ledger.js` installs those controls only when
  `ledgerDetailModel(...).canAttach` is true, so persisted-redacted and
  display-only history remains a re-check pointer rather than attachable
  evidence.
- The selected nodes shown in the ledger inspector use the same prompt-safe
  normalized shape that `ledgerContextPayload` sends onward.
- The CSS mirrors the artifact selection bar so the ledger keeps the same
  Decode-inspired dark/green workspace language.

Visual verification:

- The live browser was reloaded at
  `/projects/proj_931ea170d8ba/frames/796406c3-680c-4c5c-9f4c-24e88d073a30#evidence-ledger-pane`.
- `screenshots/101-genomi-evidence-ledger-display-only-hash.png` shows the
  persisted/display-only ledger entry with `Re-check tool`, no selection bar,
  and no attach affordance.
- Browser console warnings/errors after reload: none.

Verification:

- `PYTHONPATH=src pytest tests/test_portal_frontend_evidence_ledger_selection.py`: 2 tests passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_evidence_ledger_selection.py tests/test_portal_frontend_artifact_selection.py tests/test_portal_frontend_artifact_models.py tests/test_portal_frontend_artifact_origin_trace.py tests/test_portal_frontend_frame_trace.py tests/test_portal_frontend_assets.py`: 25 tests passed.
- All `src/genomi/interfaces/templates/*.js` files passed `node --check`.

The thermo-nuclear maintainability review for this milestone found four
concrete cleanup targets: duplicated follow-up prompt policy, selected-node
normalization drift, stale nested inspectors after ledger clear, and duplicate
selection-bar CSS.

Post-review hardening fixed those without broad portal rewrites:

- `ledgerFollowUpRequest` delegates to canonical
  `toolResultFollowUpRequest`, leaving persisted-redacted/display-only prompt
  policy in one layer.
- `toolResultContextPayload` reuses canonical `selectedDomNodes` extraction
  for result and evidence nodes, and `selectedDomNodes` now falls back through
  `context`, `text`, and `value` the same way the shared inspector does.
- `clearLedgerNodeSelection` clears selected node classes and resets nested
  result/evidence inspectors before refreshing the ledger bar.
- Ledger and artifact selection bars share `.selection-bar` and
  `.selection-actions` styling while preserving existing component-specific
  selectors.

The post-review live browser check reloaded the same frame at
`#evidence-ledger-pane` and captured
`screenshots/102-genomi-evidence-ledger-selection-post-review.png`. The
persisted/display-only ledger still exposed only `Re-check tool`, with no
selection bar and no attach affordance. Browser console warnings/errors were
empty.

## Genomi Implementation Checkpoint: Tool Request Builder

Screenshots:

- `screenshots/109-genomi-tool-request-builder-topic-css-hidden.png`
- `screenshots/110-genomi-tool-request-attached-context.png`
- `screenshots/111-genomi-tool-request-drafted-prompt.png`

The tool inspector now has a schema-driven request builder. This keeps the web
UI responsible for collecting known operation inputs, while the host agent
still owns reasoning, decomposition, and the actual Genomi MCP call.

Implementation notes:

- `portal_tool_request_builder.js` owns request-builder modeling, rendering,
  parameter extraction, draft prompts, and selected-context payloads.
- `portal_tool_catalog.js` now stays focused on catalog list and inspector
  shell rendering, importing the request-builder API rather than carrying that
  interaction logic directly.
- The server exposes compact request-builder metadata through
  `annotations.requestBuilder.conditionalFields`, currently used by
  `research.build_target_packet` to describe target-specific visible and
  conditionally required fields.
- `Attach request` emits a prompt-safe selected-context packet with
  `context_kind="tool_request"`, operation name, supplied parameters, missing
  required inputs, and sanitized description text.
- `Draft request` fills the composer with a structured prompt that names the
  operation, includes only supplied parameters, and tells the host agent to
  preserve evidence envelopes, defaults, source limits, and Active Genome Index
  privacy boundaries.
- Defaults are displayed as "default if omitted" hints rather than prefilled
  values. In the live `research.build_target_packet` check, `genome_build` and
  `limit` stayed empty and were omitted from the drafted JSON, leaving Genomi's
  `defaults_applied` contract intact for the actual tool call.
- For tools with conditional request-builder metadata, target-specific fields
  are progressively disclosed. In the live `research.build_target_packet`
  check, `target_type=topic` showed `target_type`, `topic`, omittable default
  hints, and shared optional fields; `chrom`, `pos`, `ref`, `alt`, `gene`,
  `drug`, and `condition` stayed hidden.

Visual inspection caught a real bug that the DOM-only check missed:
`row.hidden = true` was set correctly, but component `display` rules could
override the browser's default `[hidden]` display rule. The fix is now a
portal-wide invariant, `.app [hidden] { display: none !important; }`, rather
than a request-builder-only exception. The follow-up browser check confirmed
hidden target rows had computed `display: none`.

Visual verification used the live Genomi portal at
`http://127.0.0.1:8767/projects/proj_931ea170d8ba/frames/796406c3-680c-4c5c-9f4c-24e88d073a30`.
The browser selected `Genomi tools`, opened
`research.build_target_packet`, chose `target_type=topic`, entered
`rs429358`, and captured
`screenshots/109-genomi-tool-request-builder-topic-css-hidden.png`. Pressing
`Attach request` then captured
`screenshots/110-genomi-tool-request-attached-context.png`, where the selected
evidence tray showed `Tool request: research.build_target_packet` and the
composer stayed empty. Pressing `Draft request` captured
`screenshots/111-genomi-tool-request-drafted-prompt.png`, where the composer
held the structured operation prompt and only the supplied JSON parameters
`target_type` and `topic`, without submitting the turn.

Verification:

- `PYTHONPATH=src pytest tests/test_portal_frontend_tool_catalog.py tests/test_genomi_runtime_annotations.py tests/test_genomi_runtime_catalog.py`: 16 tests passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_tool_catalog.py tests/test_portal_frontend_evidence_ledger_selection.py tests/test_portal_frontend_artifact_selection.py tests/test_portal_frontend_artifact_models.py tests/test_portal_frontend_artifact_origin_trace.py tests/test_portal_frontend_frame_trace.py tests/test_portal_frontend_assets.py`: 28 tests passed.
- All `src/genomi/interfaces/templates/*.js` files passed `node --check`.

## Genomi Implementation Checkpoint: Direct Ask Request Handoff

Screenshots:

- `screenshots/112-genomi-portal-before-tool-request-ask.png`
- `screenshots/113-genomi-tools-panel-before-request-ask.png`
- `screenshots/114-genomi-tool-request-builder-selected-inspector.png`
- `screenshots/115-genomi-tool-request-builder-filled-topic.png`
- `screenshots/116-genomi-tool-request-ask-submitted.png`
- `screenshots/116b-genomi-tool-request-post-submit-wait.png`

The request builder now has a direct `Ask with request` action. This is the missing
bridge between "the web UI collects a tool intent" and "the user can just chat
in Genomi instead of switching back to the host-agent CLI".

Implementation notes:

- `portal_tool_request_builder.js` emits `onAskRequest(tool, params, prompt,
  payload)` from the same schema-derived parameter model used by `Attach
  request` and `Draft request`.
- `portal.js` handles that callback by attaching the prompt-safe
  `tool_request` selected-context packet, filling the composer with the
  structured request prompt, activating the research workspace, and submitting
  through the existing `askSelectedEvidence()` path.
- `portal_prompt_context.js` now recognizes attached `tool_request` packets and
  drafts a provenance-specific suggested prompt: use the supplied request
  parameters, ask for missing required inputs before calling a tool, and
  preserve `evidence_envelope`, `defaults_applied`, source limitations, and
  Active Genome Index privacy boundaries.
- The handoff intentionally does not call MCP from the browser. The browser
  posts a normal chat turn; the backend composes the host-agent prompt and
  starts a run. This preserves the same architecture observed in Open Design
  and Claude Science: browser owns the chat surface, backend owns run creation,
  host agent owns reasoning and tool calls.

Live visual verification:

1. Opened the local Genomi portal at
   `http://127.0.0.1:8767/projects/proj_931ea170d8ba/frames/796406c3-680c-4c5c-9f4c-24e88d073a30`.
2. Captured the baseline chat surface with an existing selected
   `Tool request: research.build_target_packet` chip
   (`screenshots/112-genomi-portal-before-tool-request-ask.png`).
3. Scrolled to the Genomi Tools pane and captured the Decode-style operation
   list (`screenshots/113-genomi-tools-panel-before-request-ask.png`).
4. Selected `research.build_target_packet` and captured the request-builder
   controls (`screenshots/114-genomi-tool-request-builder-selected-inspector.png`).
5. Filled `target_type=topic` and `topic=rs429358`, confirming defaults stayed
   as hints and only the topic-specific branch was visible
   (`screenshots/115-genomi-tool-request-builder-filled-topic.png`).
6. Clicked `Ask with request`, which submitted a normal user message with the JSON
   request and attached `Tool request: research.build_target_packet`
   selected-context chip
   (`screenshots/116-genomi-tool-request-ask-submitted.png`).
7. Waited for the run stream and captured the post-submit state
   (`screenshots/116b-genomi-tool-request-post-submit-wait.png`).

Observed route sequence from the local server:

- `POST /api/frames/796406c3-680c-4c5c-9f4c-24e88d073a30/message` returned
  `202`.
- The browser then opened
  `GET /api/runs/59841c82948d417fbca3ff69bcff3082/events`.
- `GET /api/runs/59841c82948d417fbca3ff69bcff3082` later reported
  `status="succeeded"`, `kind="host_agent"`, and `agentId="claude"`.
- Browser console warnings/errors after the submit/wait checkpoint: none.

The local host-agent invocation exited successfully but did not emit a parsed
assistant `text_delta`, so the visible proof for this checkpoint is the browser
message submission plus backend run lifecycle rather than a rendered assistant
answer. That is still enough to validate the UI-to-host-agent handoff path; a
separate host-agent parser slice should make terminal success without output
visible as a diagnostic if it recurs.

Verification:

- `PYTHONPATH=src pytest tests/test_portal_frontend_tool_catalog.py tests/test_portal_frontend_prompt_context.py tests/test_portal_frontend_assets.py`: 13 tests passed.
- All `src/genomi/interfaces/templates/*.js` files passed `node --check`.

Thermo-nuclear review found two concrete issues worth fixing before continuing:

- The request builder was still letting request semantics leak into DOM
  attributes. Conditional visibility was serialized into
  `data-tool-visible-when` and reparsed on each update.
- Direct `Ask with request` was implemented by mutating prompt context and
  re-entering the form submit path instead of submitting an explicit turn
  draft.
- The backend could mark a host-agent run `succeeded` while rendering no
  durable assistant output if the agent exited 0 without a parsed text delta.

Post-review hardening:

- `portal_tool_request_model.js` now owns the pure request-builder model:
  fields, defaults, conditional visibility/requiredness, clean params, missing
  required inputs, prompts, and selected-context payloads.
- `portal_tool_request_builder.js` is now just the renderer/controller. It
  stores stable `data-tool-field-id` values on rows/controls, reads values from
  controls, and asks the compiled model for each row's visible/required state.
  Live DOM verification on the post-review page reported zero
  `data-tool-visible-when`/`data-tool-required-when` attributes.
- `portal.js` now has `submitTurnDraft({message, selectedEvidence})`. The
  composer submit path, selected-evidence Ask path, and request-builder
  `Ask with request` path converge on that helper instead of invoking
  `requestSubmit()`.
- `Ask with request` still brings the user back to the research workspace after
  starting the explicit turn draft, so the visible chat stream remains the
  user's primary interaction surface.
- `portal_runs.py` now emits and persists a compact assistant diagnostic when
  a host-agent process exits 0 with no assistant text, tool event, stdout, or
  stderr. A focused `tests/test_portal_runs.py` regression covers that case.

Post-review visual verification:

- `screenshots/117-genomi-tool-request-post-review-builder.png` shows the same
  filled `research.build_target_packet` topic request after the pure-model
  extraction. Runtime DOM inspection showed `conditionAttributes=0`, field ids
  on controls, `topic` visible/required, target-specific non-topic fields
  hidden, and default fields still empty.
- `screenshots/119-genomi-tool-request-post-review-chat-stream.png` shows the
  direct `Ask with request` handoff landing back in the chat stream. Runtime DOM
  inspection showed `workspaceTop=0`, confirming the user sees the submitted
  turn and host-agent stream rather than staying down in the tool inspector.
- `screenshots/119b-genomi-tool-request-post-review-terminal-chat.png` captured
  the terminal chat state. Browser console warnings/errors were empty.
- Server route sequence for the final post-review run:
  `POST /api/frames/796406c3-680c-4c5c-9f4c-24e88d073a30/message` returned
  `202`, then the browser opened
  `GET /api/runs/b310ef69d083449c970ecbffc9be0715/events`.
  `GET /api/runs/b310ef69d083449c970ecbffc9be0715` reported
  `status="succeeded"`, `kind="host_agent"`, and `agentId="claude"`.

Post-review verification:

- `PYTHONPATH=src pytest tests/test_portal_runs.py tests/test_portal_frontend_tool_catalog.py tests/test_portal_frontend_assets.py tests/test_portal_frontend_prompt_context.py`: 26 tests passed.
- `PYTHONPATH=src pytest tests/test_portal_store.py`: 22 tests passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_assets.py tests/test_portal_frontend_tool_catalog.py tests/test_portal_runs.py`: 24 tests passed.
- `PYTHONPATH=src python3 -m py_compile src/genomi/interfaces/portal_runs.py src/genomi/interfaces/portal_store.py`: passed.
- `node --check` passed for the edited portal JS files, and the broader
  template JS check passed during the review-fix pass.

Stream-diagnostic cleanup:

1. Reopened the live portal in the in-app browser at
   `http://127.0.0.1:8767/projects/proj_931ea170d8ba/frames/796406c3-680c-4c5c-9f4c-24e88d073a30`.
2. Captured `screenshots/120-genomi-stream-diagnostics-before-interaction.png`
   as the baseline: older persisted host-agent turns still included
   setup/skill-loading prose in the assistant answer body.
3. Added adapter classification for obvious host setup dumps, especially text
   containing `Base directory for this skill:`, so those chunks become
   `diagnostic` events rather than `text_delta` answer content.
4. Changed live rendering so `diagnostic` and stderr events render as compact
   work-trace chips instead of being appended into the answer body.
5. Persisted startup diagnostics through the same `tool` message history path,
   so `spawn_agent` remains visible after the frame refresh that follows run
   completion.
6. Submitted a tiny prompt from the portal composer and captured
   `screenshots/123-genomi-stream-diagnostics-completed.png`. The new assistant
   message contains only the answer text, with a separate persisted
   `spawn_agent` chip underneath.

Verification for stream-diagnostic cleanup:

- `PYTHONPATH=src pytest tests/test_portal_stream.py tests/test_portal_runs.py tests/test_portal_frontend_assets.py -q`: 33 tests passed.
- `PYTHONPATH=src pytest tests/test_portal_store.py tests/test_portal_frontend_tool_catalog.py tests/test_portal_frontend_prompt_context.py -q`: 27 tests passed.
- `node --check src/genomi/interfaces/templates/portal.js && node --check src/genomi/interfaces/templates/portal_messages.js`: passed.
- `python3 -m py_compile src/genomi/interfaces/portal_agents.py src/genomi/interfaces/portal_runs.py src/genomi/interfaces/portal_run_events.py src/genomi/interfaces/portal_turns.py`: passed.
- Browser console warnings/errors during the verification pass: none.

Thermo-nuclear stream review:

Independent review agents found the stream cleanup was behaviorally useful but
still structurally weak in three places:

- raw non-JSON stdout from known agents could bypass the diagnostic classifier
  and append directly to answer text;
- `run_agent` could leave a run non-terminal if parser/store/emission logic
  raised inside the stream loop;
- persisted diagnostics emitted before assistant text could replay as loose
  tool groups rather than under the matching assistant run.

Review-fix implementation:

- `portal_agents.py` now exposes `text_or_diagnostic_event`, and known-agent
  non-JSON fallback lines use the same text-vs-diagnostic policy as structured
  agent messages.
- `portal_runs.py` now has `HostAgentRunPresentation`, a small run-local helper
  that owns answer text, diagnostics, tool events, empty-answer fallback,
  persistence, and internal stream errors. `run_agent` is back to process
  orchestration.
- Internal stream-loop exceptions now terminate the host process when needed,
  emit/persist a `host_agent_internal_error` event, finish the frame as failed,
  and call `run.finish("failed")`.
- `portal_messages.js` now replays stored messages through
  `renderStoredMessages`, groups tool/diagnostic messages by `run_id`, and
  attaches them to the matching assistant message even if storage order is
  user -> diagnostic tool -> assistant.
- Lower-priority review items remain intentionally deferred: EventSource
  reconnect behavior, splitting the large frontend asset test file, and moving
  more run lifecycle state behind locked `PortalRun` methods.

Review-fix visual verification:

- `screenshots/124-genomi-stream-policy-live-grouped.png` shows a fresh live
  run with answer text in the assistant body and a `spawn_agent` trace chip
  attached to the same message.
- `screenshots/125-genomi-stream-policy-reloaded-grouped.png` shows the same
  run after reload. Runtime inspection confirmed the last assistant message had
  one chip, `spawn_agent`, attached under the matching answer. Browser console
  warnings/errors were empty.

Review-fix verification:

- `PYTHONPATH=src pytest tests/test_portal_stream.py tests/test_portal_runs.py tests/test_portal_frontend_assets.py -q`: 37 tests passed.
- `PYTHONPATH=src pytest tests/test_portal_store.py tests/test_portal_frontend_tool_catalog.py tests/test_portal_frontend_prompt_context.py tests/test_portal_frontend_frame_trace.py -q`: 32 tests passed.
- `PYTHONPATH=src pytest tests/test_mcp_http.py -q`: 30 tests passed.
- `node --check src/genomi/interfaces/templates/portal_messages.js && node --check src/genomi/interfaces/templates/portal.js`: passed.
- `python3 -m py_compile src/genomi/interfaces/portal_agents.py src/genomi/interfaces/portal_runs.py src/genomi/interfaces/portal_turns.py src/genomi/interfaces/portal_run_events.py`: passed.

Inline artifact attachment checkpoint:

1. Reloaded the Genomi project frame in the in-app browser after restarting
   `genomi serve` on `http://127.0.0.1:8767`.
2. Verified the existing evidence report artifact exposes
   `origin_context.run_ids=["run_inspector_visual"]` through
   `GET /api/projects/proj_931ea170d8ba/artifacts`, and that the frame has an
   assistant message with the same run id.
3. Patched the inline artifact strip so the shared strip renderer no longer
   overwrites the inline strip's `message-artifact-strip` test id.
4. Runtime DOM verification after reload reported one inline artifact strip,
   one global artifact tray, and the inline strip attached to
   `run_inspector_visual`.
5. Captured
   `screenshots/126-genomi-inline-message-artifact-strip.png`, showing the
   generated `Evidence report: rs429358` card directly under the assistant turn
   that produced it.

Inline artifact verification:

- `PYTHONPATH=src pytest tests/test_portal_frontend_artifact_models.py tests/test_portal_frontend_assets.py -q`: 15 tests passed.
- `node --check src/genomi/interfaces/templates/portal_artifacts.js && node --check src/genomi/interfaces/templates/portal_messages.js && node --check src/genomi/interfaces/templates/portal.js`: passed.

Claude Science post-start workspace pass:

1. Opened the live Claude Science project frame at
   `http://localhost:8765/projects/proj_65ee842cd510/frames/991ad887-1322-458d-9f87-91201044b16f`
   in the in-app browser. No new chat turn was submitted.
2. Captured `screenshots/127-claude-science-project-session-workspace.png`.
   This confirmed the useful surface is the project/session workspace, not
   `/start`.
3. Switched to a desktop viewport only for layout inspection because the
   narrow in-app browser collapsed the multi-pane workspace. Captured
   `screenshots/128-claude-science-desktop-session-and-files-pane.png`.
4. Moved the conversation scroll area to the beginning of the selected session
   and captured `screenshots/129-claude-science-session-step-stack.png`. The
   transcript renders grouped work cards inline with assistant prose.
5. Expanded the `Checking GIAB and reference data access` step and captured
   `screenshots/130-claude-science-step-command-detail.png` and
   `screenshots/131-claude-science-step-output-expanded.png`. Command source,
   environment, and stdout are separate UI states.
6. Opened split-pane Files/Artifacts and captured
   `screenshots/132-claude-science-artifacts-split-pane.png`. The artifact
   library is grouped by upload/session and previews image, CSV, Markdown, and
   compressed VCF artifacts.
7. Opened `benchmark_report.md` and captured
   `screenshots/133-claude-science-report-artifact-route.png`. The artifact
   has its own route/modal with toolbar actions.
8. Opened the artifact actions menu and captured
   `screenshots/134-claude-science-artifact-actions-menu.png`. The menu
   includes `View in context`, `Provenance`, and `Export Metadata` beside
   ordinary file actions.
9. Opened artifact Provenance and captured:
   `screenshots/135-claude-science-artifact-provenance-code-tab.png`,
   `screenshots/136-claude-science-artifact-provenance-execution-log-tab.png`,
   `screenshots/137-claude-science-artifact-provenance-messages-tab.png`,
   `screenshots/138-claude-science-artifact-provenance-environment-tab.png`,
   and `screenshots/139-claude-science-artifact-provenance-review-tab.png`.

Claude Science implementation anchors:

- Running process:
  `/Users/matthewzmd/.claude-science/bin/claude-science serve --app --port 8765 --_restart-parent-pid 44565 --_daemon-child --no-browser`.
- The installed server is a compiled Mach-O binary. The inspected source
  surface is the shipped `web-dist` bundle under
  `/Users/matthewzmd/.claude-science/runtime/0.1.0-dev.20260630.t212931.sha2bc1ac8-release/web-dist/`.
- Important bundle modules found by filename:
  `ConversationView-BRvL6xm6.js`, `MessageBubble-Ct9R25kt.js`,
  `useFrameMessages-C5t5_4_z.js`, `ArtifactTile-Bg__fT_t.js`,
  `ProvenancePane-C6bOYqUt.js`, `KernelNotebookPane-DBhmauJk.js`,
  `EnvironmentSnapshotDrawer-DDJMjjSj.js`, and
  `LineageMessagesDrawer-to1gW31B.js`.
- Client route methods in `index-CIcUordt.js` include:
  `frames.getMessages -> GET /frames/:id/messages`,
  `frames.getStreamingBuffer -> GET /frames/:id/streaming`,
  `conversations.sendMessage -> POST /frames/:frameId/message`,
  `projects.submitRequest -> POST /projects/:pid/request`,
  `frames.submitRequest -> POST /request`,
  `projects.listArtifacts -> GET /projects/:pid/artifacts`,
  `downloadSessionBundle -> GET /frames/:id/bundle`,
  and `downloadScriptBundle -> GET /artifacts/:versionId/script-bundle`.
- The browser connects to `ws(s)://<host>/api/ws`. The WebSocket registry
  names include `frames`, `framesGlobal`, `messagesDelta`, `artifacts`,
  `textStream`, `toolStdout`, `executionCells`, `jobLog`,
  `managedTranscript`, `frameActivity`, `compaction`, `rateLimitNotice`,
  `notes`, `connectorUpdate`, and `verificationUpdate`.
- Local SQLite tables that explain the rendered state include `projects`,
  `frames`, `frame_messages`, `execution_log`, `artifacts`,
  `artifact_versions`, `artifact_dependencies`, `notes`,
  `frame_read_cursors`, and `verification_checks`.
- `artifact_versions` stores `lineage_messages`, `dependency_mappings`,
  `environment_snapshot`, `producing_cell_id`, and `cell_sources`; those fields
  correspond to the Provenance tabs observed in the browser.

Claude Science design conclusion:

- The workspace treats each host-agent turn as a durable frame/session, not as
  a free-floating chat completion.
- Science state is rendered through layered panes: transcript messages,
  compact work cards, command/detail expansion, artifact library, artifact
  preview route, and artifact provenance tabs.
- The provenance model is richer than a single "artifact origin" pointer. A
  mature Genomi artifact should be able to expose the answer turn, selected
  evidence/tool events, raw execution/work trace, environment/library state,
  dependency artifacts, and review status as separate inspectable tabs.

Genomi Runtime tab checkpoint:

1. Implemented a Genomi-native artifact `Runtime` provenance tab rather than
   copying Claude Science's environment pane directly.
2. The tab renders origin boundary, `defaults_applied`, source catalog
   coverage, evidence-envelope interpretation boundary, and immutable artifact
   version metadata.
3. Reloaded the live Genomi portal at
   `http://127.0.0.1:8767/projects/proj_931ea170d8ba/frames/796406c3-680c-4c5c-9f4c-24e88d073a30`.
4. Runtime DOM verification reported the active tab as `runtime`, metrics for
   operation, renderer, origin runs, defaults, sources, and content type, and
   visible sections for origin boundary, defaults applied, source coverage,
   interpretation boundary, and artifact version.
5. Captured `screenshots/140-genomi-artifact-runtime-tab.png`, showing the
   artifact inspector in the Genomi dark workspace language with Runtime active.

Runtime tab verification:

- `node --check` over every file in `src/genomi/interfaces/templates/*.js`:
  passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_artifact_models.py tests/test_portal_artifact_evidence_packet.py -q`:
  7 tests passed.
- `PYTHONPATH=src pytest tests/test_portal*.py -q`: 88 tests passed.
- `PYTHONPATH=src pytest tests/test_mcp_http.py -q`: 30 tests passed.

## Genomi Artifact Deep-Link Checkpoint

Claude Science's post-start workspace treats artifact identity as a first-class
workspace state: opening a report or provenance pane gives the user a durable
artifact view, not a transient dashboard widget. Genomi now has the matching
route shape for project artifacts:

```text
/projects/:project_id/artifacts/:artifact_id
```

Live inspection target:

- `http://127.0.0.1:8767/projects/proj_931ea170d8ba/artifacts/art_8098a8b4ac6d`

Screenshot:

- `screenshots/141-genomi-artifact-deep-link-route.png`

Browser verification after reload reported:

- URL remained on the artifact route.
- The page scrolled to the artifact workspace on load.
- `artifact-workspace` was visible at the top of the viewport.
- The selected artifact payload was
  `Evidence report: rs429358` with artifact id `art_8098a8b4ac6d`.
- The preview tab was active, and no frame card was selected by the artifact
  route.

Implementation notes:

- `GET /projects/:project_id/artifacts/:artifact_id` serves the portal shell
  the same way the project and frame routes do.
- The frontend route parser now recognizes artifact ids before falling back to
  frame routes.
- Loading a valid artifact route selects that artifact, avoids restoring a
  stale frame from local storage, and activates the artifact workspace without
  changing the route back to a hash.
- Invalid artifact ids fall back to the normal project route after the artifact
  list is loaded.

Thermo-nuclear maintainability review also ran against this branch. The
feature-blocking fixes applied in this slice were:

- split the oversized artifact renderer shell into focused artifact display,
  context, state-adapter, runtime-model, and view-model modules;
- keep `portal_artifacts.js` as the DOM/render coordinator instead of a
  renderer-specific catch-all;
- consolidate prompt-safe path redaction into `portal_privacy.py`, then route
  portal context and portal turn sanitization through that single module.

Larger review items remain intentionally deferred while feature development
continues: splitting `portal_store.py`, moving artifact file IO outside the
state transaction lock, reconciling HTTP/security policy boundaries, and
reshaping the broad MCP HTTP test suite.

Verification:

- `node --check` over every file in `src/genomi/interfaces/templates/*.js`:
  passed.
- `python3 -m py_compile src/genomi/interfaces/portal_privacy.py src/genomi/interfaces/portal_context.py src/genomi/interfaces/portal_turns.py src/genomi/interfaces/portal.py`:
  passed.
- `PYTHONPATH=src pytest tests/test_portal*.py -q`: 89 tests passed.
- `PYTHONPATH=src pytest tests/test_mcp_http.py -q`: 31 tests passed.

## Genomi Artifact Version Route Checkpoint

The artifact route establishes artifact identity. The next workspace contract
is immutable version identity: a URL should be able to reopen the exact
rendered artifact version that the user copied or reviewed, even if the
artifact later gains a newer version.

Live inspection target:

- `http://127.0.0.1:8767/projects/proj_931ea170d8ba/artifacts/art_8098a8b4ac6d/versions/ver_50848a5cfd8d`

Screenshot:

- `screenshots/142-genomi-artifact-version-route.png`

Browser verification after server restart reported:

- URL remained on the artifact-version route.
- The page scrolled to the artifact workspace on load.
- `artifact-workspace` was visible at the top of the viewport.
- The artifact shell carried artifact id `art_8098a8b4ac6d`.
- The preview iframe resolved to
  `/api/artifacts/versions/ver_50848a5cfd8d/file`.

Implementation notes:

- `GET /projects/:project_id/artifacts/:artifact_id/versions/:version_id`
  serves the same portal shell as project, frame, and artifact routes.
- The frontend route parser recognizes artifact-version routes before artifact
  routes.
- Route state keeps `activeArtifactVersionId` pending until artifact detail
  hydration loads the version list.
- The artifact preview model uses a selected version only when that version is
  present in the artifact's own loaded version list. Unknown or mismatched
  route versions are dropped and the URL is normalized back to the artifact
  route.
- Version-specific preview/open URLs resolve through
  `/api/artifacts/versions/:version_id/file`, preserving the immutable content
  boundary.

Verification:

- `node --check` over every file in `src/genomi/interfaces/templates/*.js`:
  passed.
- `python3 -m py_compile src/genomi/interfaces/portal.py`: passed.
- `PYTHONPATH=src pytest tests/test_portal*.py -q`: 89 tests passed.
- `PYTHONPATH=src pytest tests/test_mcp_http.py -q`: 32 tests passed.

## Genomi Scoped Artifact Route Review Checkpoint

The thermo-nuclear review after the first artifact-version route slice found
two merge-blocking design issues:

- frontend artifact/version route state was spread across `portal.js` instead
  of living in a route/selection model;
- backend artifact/version APIs treated artifacts and versions as global public
  resources even though the workspace routes are project-scoped.

Post-review implementation:

- `portal_artifact_route_model.js` now owns route parsing, route path building,
  route artifact selection, selected-version application, and invalid-version
  fallback.
- `artifactDisplayModel` distinguishes latest, selected, and effective
  artifact versions; selected historical versions are no longer labeled as the
  latest version.
- Public artifact metadata, detail, versions, and file endpoints are scoped as
  project -> artifact -> version relationships.
- Public artifact payloads recompute portal-owned scoped file URLs instead of
  exposing old global artifact paths.
- External artifact `url` values are kept only when they are `http(s)` loopback
  URLs without credentials. File URLs, absolute local paths, credentialed URLs,
  and non-loopback URLs fall back to the portal-owned snapshot URL.

Live inspection target:

- `http://127.0.0.1:8767/projects/proj_931ea170d8ba/artifacts/art_8098a8b4ac6d/versions/ver_50848a5cfd8d`

Screenshot:

- `screenshots/143-genomi-scoped-artifact-version-route.png`

Browser/API verification after server restart reported:

- `GET /api/projects/proj_931ea170d8ba/artifacts` returned scoped
  `url`/`preview_url` values under
  `/api/projects/proj_931ea170d8ba/artifacts/art_8098a8b4ac6d/...`.
- `GET /api/artifacts/art_8098a8b4ac6d` returned `404`.
- The version-route iframe resolved to
  `/api/projects/proj_931ea170d8ba/artifacts/art_8098a8b4ac6d/versions/ver_50848a5cfd8d/file`.
- The artifact evidence tab contains separate Latest version, Selected
  version, and Effective version labels.
- Opening an invalid version route normalized back to the artifact route and
  previewed the latest scoped version file.

Verification:

- `node --check` over every file in `src/genomi/interfaces/templates/*.js`:
  passed.
- `python3 -m py_compile src/genomi/interfaces/portal.py src/genomi/interfaces/portal_store.py src/genomi/interfaces/portal_assets.py src/genomi/interfaces/portal_artifact_presenters.py src/genomi/runtime/portal_routes.py`:
  passed.
- `PYTHONPATH=src pytest tests/test_portal*.py -q`: 92 tests passed.
- `PYTHONPATH=src pytest tests/test_mcp_http.py -q`: 32 tests passed.

## Genomi Artifact Copy-Link Checkpoint

Claude Science treats artifact links as workspace references, not just file
downloads. Genomi now mirrors that useful part of the pattern while keeping the
route contract Genomi-native: copied links reopen the artifact workspace inside
the project, and version-scoped previews copy the immutable artifact-version
route.

Live inspection target:

- `http://127.0.0.1:8767/projects/proj_931ea170d8ba/artifacts/art_8098a8b4ac6d/versions/ver_50848a5cfd8d`

Screenshot:

- `screenshots/144-genomi-artifact-copy-link.png`

Browser verification reported:

- The active preview header exposed exactly one `Copy link` action.
- The page exposed three `Copy link` actions total: artifact card, generated
  artifact strip, and active preview.
- The active preview action carried the workspace URL
  `http://127.0.0.1:8767/projects/proj_931ea170d8ba/artifacts/art_8098a8b4ac6d/versions/ver_50848a5cfd8d`.
- The in-app browser clipboard bridge returned an empty read after click, so
  the live verification used the rendered button's `data-workspace-url` plus
  frontend behavior tests for the click handler.

Implementation notes:

- `portal_artifact_route_model.js` owns absolute artifact workspace URL
  construction beside route parsing and path building.
- Artifact cards and generated-artifact strip items copy the artifact identity
  route.
- The active preview header copies the selected version route when the artifact
  is version-scoped; otherwise it falls back to the artifact route.
- Copy actions never expose the scoped file endpoint as the copied workspace
  identity.

Verification:

- `node --check` over every file in `src/genomi/interfaces/templates/*.js`:
  passed.
- `python3 -m py_compile src/genomi/interfaces/portal.py src/genomi/interfaces/portal_store.py src/genomi/interfaces/portal_assets.py src/genomi/interfaces/portal_artifact_presenters.py src/genomi/runtime/portal_routes.py`:
  passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_routes.py tests/test_portal_frontend_artifact_models.py -q`:
  9 tests passed.

## Genomi Artifact Tab Route Checkpoint

Claude Science artifact URLs preserve more than "which file": the user can
return to a specific inspection surface such as provenance or review. Genomi
now carries the same idea through a compact Genomi route contract: artifact
routes may include `artifact_tab` to reopen the exact artifact inspection tab
inside the project workspace.

Live inspection target:

- `http://127.0.0.1:8767/projects/proj_931ea170d8ba/artifacts/art_8098a8b4ac6d/versions/ver_50848a5cfd8d?artifact_tab=runtime`

Screenshot:

- `screenshots/145-genomi-artifact-tab-route.png`

Browser verification reported:

- Direct-opening the runtime-tab URL kept the browser at the same URL.
- The Runtime tab rendered with `artifact-tab active`.
- The Runtime panel was visible.
- Clicking Review changed the route to
  `?artifact_tab=review` without leaving the artifact workspace.
- The active preview `Copy link` action then exposed the same review-scoped
  workspace URL in `data-workspace-url`.

Implementation notes:

- `portal_artifact_route_model.js` now parses, validates, builds, and absolutizes
  artifact tab route state.
- `portal.js` keeps `activeArtifactTabId` beside active artifact/version state
  and updates the browser route on tab changes.
- `portal_artifacts.js` activates a requested tab during preview render and
  computes preview-header copy links from the currently active tab.
- Artifact cards still copy artifact identity only; tab-scoped copy belongs to
  the active preview where the user is looking at a specific inspection surface.

Verification:

- `node --check` over every file in `src/genomi/interfaces/templates/*.js`:
  passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_routes.py tests/test_portal_frontend_artifact_models.py -q`:
  9 tests passed.

## Genomi Artifact Library Toolbar Checkpoint

Claude Science treats artifacts as a navigable library beside the transcript,
not as an inert list of links. Genomi now adds the first piece of that library
behavior: search, class filters, and layout controls on the project artifact
list while preserving the active artifact preview.

Live inspection target:

- `http://127.0.0.1:8767/projects/proj_931ea170d8ba/artifacts/art_8098a8b4ac6d`

Screenshot:

- `screenshots/146-genomi-artifact-library-toolbar.png`

Browser verification reported:

- The artifact toolbar rendered with search, filter chips, layout controls, and
  count summary.
- The current project showed `All 1`, `Previewable 1`, `Evidence 1`,
  `Reports 0`, and `Other 0`.
- Searching for `no-match` kept the toolbar visible, preserved the query value,
  hid matching artifact cards, and showed `No matching artifacts`.
- Searching for `rs429358` restored the artifact.
- Switching to Compact changed the active card class to
  `artifact-card compact active`.

Implementation notes:

- `portal_artifact_library_model.js` owns artifact search/filter/layout state
  as a pure model.
- `portal_artifacts.js` renders the toolbar and keeps no-match notices
  append-only so controls remain available.
- `createArtifactLibraryController` owns artifact library query/filter/layout
  state beside the artifact renderer; `portal.js` only passes artifacts, active
  artifact id, and host-agent callbacks.
- Artifact cards now highlight the active artifact in both card and compact
  layouts.

Verification:

- `node --check` over every file in `src/genomi/interfaces/templates/*.js`:
  passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_artifact_library.py tests/test_portal_frontend_artifact_models.py tests/test_portal_frontend_routes.py -q`:
  11 tests passed.

## Genomi Artifact Version Selector Checkpoint

Claude Science makes artifact versions inspectable from the artifact surface
instead of forcing the user to reason from raw file endpoints. Genomi now
surfaces the same concept in the artifact preview header: loaded artifact
versions are shown in a compact selector, and choosing a version updates the
workspace route to the immutable `/versions/:version_id` identity while keeping
the active inspection tab.

Live inspection target:

- `http://127.0.0.1:8767/projects/proj_931ea170d8ba/artifacts/art_8098a8b4ac6d/versions/ver_50848a5cfd8d?artifact_tab=runtime`

Screenshot:

- `screenshots/147-genomi-artifact-version-selector.png`

Browser verification reported:

- The artifact preview rendered exactly one
  `data-testid="genomi-artifact-version-control"`.
- The selected value was `ver_50848a5cfd8d`.
- The selector option label included `latest`, the immutable version id,
  `text/html`, and the shortened checksum.
- The page stayed on the version-scoped runtime-tab URL while the Runtime panel
  remained active.

Implementation notes:

- `artifactVersionSelectorModel` owns the pure latest/selected/effective version
  option state.
- `portal_artifacts.js` renders a disabled read-only selector when no
  version-change callback is supplied, and an active selector inside the portal
  preview header.
- `portal.js` keeps version changes in route state through
  `activeArtifactVersionId`, preserving `activeArtifactTabId` when the version
  changes.

Verification:

- `node --check src/genomi/interfaces/templates/portal_artifact_display_model.js`
  passed.
- `node --check src/genomi/interfaces/templates/portal_artifacts.js` passed.
- `node --check src/genomi/interfaces/templates/portal.js` passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_artifact_models.py -q`:
  6 tests passed.
- `PYTHONPATH=src pytest tests/test_portal*.py -q`: 94 tests passed.

## Genomi Message Work-Group Header Checkpoint

Claude Science's transcript keeps assistant prose separate from grouped work
steps. Genomi now applies that interaction pattern to host-agent tool activity
inside each assistant turn: tool chips remain individually expandable, but they
are preceded by a compact work-group header that summarizes step count,
completed work, running work, and errors.

Live inspection target:

- `http://127.0.0.1:8767/projects/proj_931ea170d8ba/frames/796406c3-680c-4c5c-9f4c-24e88d073a30`

Screenshot:

- `screenshots/148-genomi-message-work-group-header.png`

Browser verification reported:

- The page rendered `6` `data-testid="tool-group-header"` elements.
- The page rendered `6` `data-testid="tool-group"` containers.
- The page rendered `15` `data-testid="tool-chip"` elements.
- Toggling the first work-group header collapsed and reopened its tool stack.
- The visible assistant turn kept answer text, the work-group header, the
  individual tool chip, and generated artifact cards in one coherent message
  block.

Implementation notes:

- `toolWorkGroupSummary` owns the count/status/title/summary wording as a pure
  frontend model.
- `portal_messages.js` now creates a `tool-stack` shell with
  `data-testid="tool-group-header"` and `tool-stack-items`.
- Work-group headers are expanded by default and can be collapsed without
  losing the individual tool cards.
- The header gets an `aria-label` so the compact grid reads as one coherent
  summary.

Verification:

- `node --check src/genomi/interfaces/templates/portal_messages.js` passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_assets.py -q`:
  10 tests passed.

## Genomi Result Search Toolbar Checkpoint

Dense evidence maps need a local narrowing control before selection. Claude
Science keeps generated state inspectable in-place; for Genomi's structured
tool results, the equivalent interaction is a compact toolbar directly inside
the result panel, above the evidence lanes.

Live inspection target:

- `http://127.0.0.1:8767/projects/proj_4eff6d75d3f7/frames/cbf64764-22a2-4f9e-9fcf-e81798f4fd78`

Screenshots:

- `screenshots/151-genomi-result-search-toolbar.png`
- `screenshots/152-genomi-result-search-filtered.png`
- `screenshots/153-genomi-result-search-empty.png`

Browser observations:

- The persisted `variant.resolve` fixture route rendered `6` structured
  Genomi result views and `6` result-search toolbars after reload.
- Expanding the first `variant.resolve` chip exposed a toolbar with the
  unfiltered summary `3 nodes`.
- Filtering for `ClinVar` changed the first toolbar summary to `2 of 3 shown`,
  hid the resolved-target node, and kept the two ClinVar nodes visible.
- Filtering for `NoSuchGene` changed the toolbar class to
  `genomi-result-toolbar empty` and left zero visible result nodes.

Implementation notes:

- `resultSearchModel` owns the pure query/total/matching/empty summary state
  for result view models.
- `renderGenomiResultPanel` inserts the toolbar only for result models with
  more than two selectable nodes, keeping small results quiet.
- `applyResultSearch` filters rendered `.result-node` buttons using the
  prompt-safe search text already attached to each node and hides empty
  `.genomi-result-lane` sections.
- The interaction is local to the result panel; selected nodes are not cleared
  by filtering, so a user can narrow the visible set without losing deliberate
  selections.

## Genomi Inline Work-Trace Actions Checkpoint

After adding compact work-group headers, the next useful Claude Science-style
interaction was letting the user act on a grouped step stack directly from the
chat transcript. Genomi now exposes `Attach work trail` and `Ask about work
trail` actions on each
message-level work group. The actions build a sanitized `work_trace` packet
from the grouped tool records using the same frame-trace serialization path as
the dedicated Work trail pane.

Live inspection target:

- `http://127.0.0.1:8767/projects/proj_931ea170d8ba/frames/796406c3-680c-4c5c-9f4c-24e88d073a30`

Screenshots:

- `screenshots/149-genomi-message-work-trace-actions.png`
- `screenshots/150-genomi-message-work-action-row.png`

Browser verification reported:

- The page rendered `6` inline `Attach work trail` actions.
- The page rendered `6` inline `Ask about work trail` actions.
- The page rendered `15` tool chips.
- The first work-group header had the accessibility label
  `1 work step: 1 done`.
- Clicking the first `Attach work trail` action attached one next-turn context chip:
  `Message work trace`.
- The context tray became visible after the click.

Implementation notes:

- `toolWorkGroupContextPayload` is a pure frontend helper that turns grouped
  tool records into a sanitized `work_trace` context packet.
- The message surface reuses `frameTraceMessagesFromToolRecord` and
  `frameTraceSummaryPayload`, so inline chat actions and the Work trail pane
  share one prompt/context contract.
- The work-group header is now a structured row: a toggle control plus `Attach
  work trail` and `Ask about work trail` actions. This avoids nested buttons and keeps the tool chips
  collapsible.

Verification:

- `node --check src/genomi/interfaces/templates/portal_messages.js` passed.
- `PYTHONPATH=src pytest tests/test_portal_frontend_assets.py -q`:
  10 tests passed.

## Genomi Selected Context Action Checkpoint

The selected-context tray is the return path from visual evidence back into
the host-agent conversation. It now behaves less like passive storage and more
like a workspace surface: each attached evidence carries its provenance kind,
uses a kind-specific card treatment, and exposes a matching ask/draft action.

Live inspection target:

- `http://127.0.0.1:8769/projects/proj_931ea170d8ba/frames/796406c3-680c-4c5c-9f4c-24e88d073a30#selected-evidence-pane`

Screenshots:

- `screenshots/154-genomi-selected-context-actions.png`
- `screenshots/155-genomi-selected-context-draft-work.png`

Browser observations from this historical checkpoint:

- The then-current portal shell rendered a rail target for `Selected evidence`
  and activated it from the `#selected-evidence-pane` route.
- Pressing the inline `Attach work trail` action attached a real
  `context_kind="work_trace"` packet to the attached-material state, displayed
  at that time in a selected-material pane.
- The selected context card rendered `context-kind-work_trace`, showed
  `Work trail · 1 node`, and exposed `Ask about work trail` plus `Draft work`.
- Pressing `Draft work` filled the composer with a work-trace-specific prompt:
  it asks the host agent to use the selected trace as provenance for what was
  already attempted, what failed or needs re-checking, and what remains out of
  scope.
- The draft action did not submit a host-agent message.

Implementation notes:

- `contextActionModel` maps context kinds to compact kind labels and
  provenance-specific `Ask ...` / `Draft ...` labels.
- `askWith(context)` now submits only the selected packet; the global
  `Ask` button still submits the full attached context set.
- The portal submit callback accepts a success cleanup hook, so item-level
  sends can remove only the submitted packet after a successful turn.
- `suggestedPromptForContexts` now has a work-trace branch instead of falling
  back to generic selected-evidence wording.
- At this checkpoint, the selected-material pane had a stable
  `selected-evidence-pane` route target in the rail. Later UX alignment folded
  this into composer `Attached material` rather than keeping a standalone
  product pane.

## Genomi Evidence Ledger Direct Action Checkpoint

The Evidence Ledger selection bar now has the same direct loop as live result
panels and the selected-context tray. Current/reusable ledger details can still
attach selected nodes with `Use evidence`, but they also expose `Ask evidence`
and `Draft evidence`. When a node is selected, the labels switch to
`Use selected`, `Ask selected`, and `Draft selected`.

The important boundary is unchanged: persisted-redacted ledger history remains
display-only and does not gain these controls. Visual verification first opened
the persisted `variant.resolve` frame and confirmed it showed public lanes but
no ledger action bar. A current/live ledger action fixture was then used to
exercise the real frontend modules without weakening persisted-history privacy.

Visual inspection fixture:

- `docs/research/claude-science-portal-study/evidence-ledger-actions-fixture.html`
- served temporarily at
  `http://127.0.0.1:8770/docs/research/claude-science-portal-study/evidence-ledger-actions-fixture.html`

Screenshots:

- `screenshots/156-genomi-ledger-direct-actions-selected.png`
- `screenshots/157-genomi-ledger-direct-actions-draft.png`
- `screenshots/158-genomi-ledger-direct-actions-ask.png`

Browser observations:

- The fixture rendered one current `variant.resolve` ledger entry, one ledger
  detail panel, and three selectable result nodes.
- Before node selection, the ledger selection bar exposed `Use evidence`,
  `Ask evidence`, and `Draft evidence`.
- Selecting the first result node changed the bar to `Use selected`,
  `Ask selected`, and `Draft selected`, and the ledger inspector showed one
  selected prompt-safe `rs429358` node.
- Pressing `Draft selected` filled the fixture composer with the selected
  ledger packet prompt and recorded `context_kind: result_nodes` plus
  `source_operation: variant.resolve`.
- Pressing `Ask selected` recorded the same selected packet as the direct
  host-agent submission payload.

Implementation notes:

- `ledgerSelectionControlsMarkup` now renders attach, ask, draft, and clear
  controls; `updateLedgerSelectionBar` keeps their labels tied to the current
  node-selection state.
- `createEvidenceLedger` forwards `onAskContext` and `onDraftContext` into the
  detail panel, so the ledger can route selected visual evidence directly to
  the host-agent conversation.
- `createPromptContextController.draftWith(context)` attaches a packet before
  drafting unless the caller explicitly opts out, which prevents draft text
  from referring to selected evidence that will not be sent.
- Evidence-ledger summary packets now get provenance-specific draft wording in
  `suggestedPromptForContexts`.

## Genomi Assistant Checklist Direct Action Checkpoint

Assistant evidence checklists already turned explicit "Evidence I would
inspect" sections into selectable source-lane nodes. The next useful step was
making those checklist nodes behave like the rest of the visual workspace:
selection, draft, and direct ask now happen inside the transcript instead of
requiring the user to bounce through a separate attached-material tray first.

Visual inspection fixture:

- `docs/research/claude-science-portal-study/assistant-checklist-actions-fixture.html`
- served temporarily at
  `http://127.0.0.1:8770/docs/research/claude-science-portal-study/assistant-checklist-actions-fixture.html`

Screenshots:

- `screenshots/159-genomi-assistant-checklist-direct-actions-selected.png`
- `screenshots/160-genomi-assistant-checklist-direct-actions-draft.png`
- `screenshots/161-genomi-assistant-checklist-direct-actions-ask.png`

Browser observations:

- The fixture rendered the real `createMessageSurface` transcript with one
  assistant answer and one parsed evidence checklist containing four source
  lanes.
- Before selecting a lane, `Use selected`, `Ask selected`, and
  `Draft selected` were disabled and the checklist showed
  `Select source lanes to ask or draft from this checklist`.
- Selecting the first source lane enabled the selected-only actions and showed
  `1 selected source lane`.
- Pressing `Draft selected` populated the fixture composer with a prompt-safe
  `assistant_checklist` packet containing only the selected CPIC/PharmGKB lane.
- Pressing `Ask selected` recorded the same `assistant_checklist` packet as the
  direct host-agent submission payload.

Implementation notes:

- `createMessageSurface` now accepts `onDraftContext` beside `onUseContext`
  and `onAskContext`.
- Assistant checklist panels now expose `Attach selected`, `Ask selected`,
  `Draft selected`, and `Attach all lanes`.
- `assistantEvidenceChecklistSelectionModel` owns the selected-count summary
  and selected-action enablement state.
- The portal shell wires transcript `onDraftContext` to
  `promptContext.draftWith`, so draft text and selected evidence stay coupled.

## Genomi Artifact Report Actions Checkpoint

Claude Science's artifact route keeps object actions on the artifact itself:
use the file, inspect provenance, copy/share a link, export metadata, or jump
back to the producing conversation. Genomi now follows that pattern for
evidence reports while keeping its internal context payloads out of the user's
way.

Screenshots:

- `screenshots/180-genomi-fresh-evidence-report-actions-menu.png`

Browser observations:

- The portal loaded a current `research.build_target_packet` artifact as
  `Evidence report: rs429358`.
- The active artifact header exposed a compact action menu with
  `Attach artifact`, `Attach review brief`, `Open evidence`, `Copy link`,
  `Copy artifact details`, and `Open report`.
- The generated preview also used `Evidence report`, confirming this is not
  just shell-level relabeling of an old artifact.
- `/start` stayed removed on the branch server: `GET /start` returned `404`.

Implementation notes:

- `portal_artifact_actions.js` owns the reusable artifact overflow menu so card
  and preview actions do not keep growing inside `portal_artifacts.js`.
- Evidence-report display labels normalize legacy `Evidence packet` and
  `Open packet` records at presentation time, preserving the underlying
  renderer/kind for routing.
- The copy/link actions operate on workspace artifact routes; raw artifact
  files remain preview/open implementation details.

## Genomi User-Facing Language Checkpoint

The portal now treats Genomi's context and data-structure machinery as backend
plumbing. The user-facing surface should explain what the user can actually do:
ask the next question, inspect an evidence map, review a work trail, open an
artifact, or use genome-index facts. Internal fields such as `context_kind`,
`selected_nodes`, and `evidence_envelope` can remain in payload contracts, but
they should not be product nouns.

Screenshots:

- `screenshots/181-genomi-work-trail-language-live.png`
- `screenshots/184-genomi-clean-next-question-language-cropped.png`
- `screenshots/185-genomi-clean-genome-index-language-cropped.png`

Browser observations:

- The `Next Question` capture is historical. That standalone pane was useful
  for testing selected material, but it is no longer the product direction.
  The current UI attaches findings, source lanes, work steps, and artifacts in
  the composer as `Attached material`.
- The genome pane presents `Genome Index`, `Use selected facts`, and
  `Use genome summary`; the raw JSON remains behind `Technical state`.
- The assistant rail says installed assistants can run Genomi tools while the
  portal keeps the conversation, work trail, and artifacts.
- Older local persisted conversations still contain stale text such as
  `selected-node follow-up`; those strings were found in
  `~/.genomi/portal/state.json`, not in the branch source.

Implementation notes:

- UI strings were moved from packet/node/context wording toward evidence,
  findings, facts, work steps, review summaries, and prepared requests.

## Genomi Product Surface Pruning Checkpoint

The standalone selected-context / next-question pane is now removed from the
portal product surface. Its underlying job is still real: visual evidence,
prepared requests, artifact summaries, and work-trail slices can be attached to
the assistant message. The user-facing location for that state is the composer
as `Attached material`, not a separate workspace pane.

Reasoning:

- A permanent pane for selected context mirrored internal packet state rather
  than a science-workspace object.
- Composer attachments preserve the useful loop from visual evidence back into
  chat without asking the user to manage implementation machinery.
- The right-stack workspace now stays focused on durable research objects:
  Files & Artifacts, Evidence from this chat, Work trail, and Genome Index,
  with Advanced tools available as an explicit request-builder surface.
- This aligns with the new development-agent rule that every selectable item
  or panel must have a clear end-user reason rooted in research work,
  reproducibility, provenance, or genome privacy.

Implementation notes:

- `portal.html` no longer includes the selected-context pane or rail target.
- `portal_prompt_context.js` owns only composer attachments.
- `portal_prompt_context_tray.js` and the corresponding evidence-tray CSS were
  removed.
- Action titles now describe attaching evidence/results/artifacts to the
  composer rather than sending an abstract next turn.

## Subagent UX / Architecture Alignment Checkpoint

Three independent read-only subagents reviewed the current portal against the
reference science workspace and Open Design-style local web UI architecture.

Agreed findings:

- The core loop is now directionally right: project chat, artifacts, evidence
  map, work trail, genome-index state, and composer-attached material are the
  real user-facing objects.
- The normal UI should avoid host-agent and context-packet language. The visible
  copy now says assistant/workspace/attached material, while implementation
  contracts can keep their internal names.
- `Advanced tools` should remain available, but it is not a primary science
  object; it is an advanced request builder.
- Genomi now has a first non-authoritative active-view context API for the
  current route, workspace pane, frame, artifact, version, and artifact tab.
  Explicit attachments remain the authoritative evidence handoff; the active
  view is only prompt orientation and still lacks selected DOM nodes or a rich
  viewport summary.
- Genomi projects persist portal state and artifacts, and assistant processes
  now execute from a project-scoped backend workspace path instead of the
  server launch directory.
- Execution-cell logs, richer environment snapshots, async check runs, script
  bundles, exact producing-step links, and generated-session Library grouping
  remain real capability gaps rather than UI labels Genomi should fake.
- The backend prompt handoff still preserves selected evidence and source
  boundaries, but it now describes browser-selected material as portal evidence
  instead of selected context.
- `/start` remains outside the product route; onboarding belongs in install
  setup, not the research workspace.

Visual verification:

- The current source-backed portal was opened through a stale
  project/artifact deep link. The browser recovered to the current project
  route instead of showing a false API outage. A follow-up maintainability pass
  narrowed this recovery to the exact `404/not_found` project case by adding
  typed portal API errors; other workspace failures now stay scoped to the
  workspace status instead of overwriting the assistant/runtime status.
- The live page showed `2 assistants ready`, `Advanced tools`, `Send`, no
  selected-context / next-question pane, and Genome Index sections for
  `Current genome`, `Privacy boundary`, and `Known genomes`.
- Screenshot reference:
  `screenshots/197-genomi-portal-ux-alignment-current-workspace.png`.

Thermo-nuclear maintainability review:

- Two independent reviewers found real structural pressure in the portal work:
  `portal.js`, `portal_artifacts.js`, `portal_store.py`, and several large
  frontend test files are becoming broad ownership buckets.
- The narrow stale-route issue was fixed immediately because it affected the
  user-facing recovery behavior and could hide real backend failures.
- Larger decomposition items remain backlog rather than being half-refactored
  in this UX slice: split frontend controllers, split artifact rendering
  responsibilities, centralize artifact presentation policy, move Genome Index
  presentation state closer to the backend contract, consolidate prompt-context
  payload policy, decompose `portal_store.py`, centralize stale-run recovery,
  and split oversized mixed integration tests.

## Genomi Active UI Context Checkpoint

Open Design's useful architecture pattern here is not that selected UI state
becomes evidence; it is that the local web shell can tell the assistant what
the user is currently viewing. Genomi now has the first version of that channel:

- `POST /api/projects/<project_id>/active-context` stores prompt-safe current
  view state in memory for the project.
- `GET /api/projects/<project_id>/active-context` returns the current active
  view or an empty state.
- The browser posts route, workspace pane, frame id, artifact id, artifact
  version id, artifact tab id, and artifact title when the route/pane/artifact
  view changes, and flushes the latest state before submitting a turn.
- Host-agent prompts include this as `# Current visible portal view`, with an
  explicit warning that it is non-authoritative orientation only and must not
  be treated as Genomi evidence unless the user explicitly attached material or
  a tool returned it.

This closes the "no active context channel at all" gap while preserving the
selected-material boundary. Remaining work: selected visible nodes, viewport
summaries, active-context inspection UI, and richer project-scoped workspace
state.

## Genomi Artifact Environment Checkpoint

Claude Science's artifact Environment tab is valuable because it answers a
simple user question: what runtime produced this artifact? Genomi now has a
partial equivalent on artifact versions without making the user reason about
internal context packets.

Screenshots:

- `screenshots/186-genomi-artifact-environment-tab.png`
- Claude Science comparison references:
  `screenshots/170-claude-science-artifact-environment-tab.png` and
  `screenshots/138-claude-science-artifact-provenance-environment-tab.png`

Browser/API observations:

- A live branch portal on `127.0.0.1:8773` rendered an `Evidence report:
  rs429358` artifact through the real `/api/projects/{project_id}/artifacts/render`
  route.
- Artifact list summaries and `latest_version` summaries intentionally omitted
  `environment`; immutable artifact-version and artifact-detail payloads carried
  `kind: artifact_environment_snapshot`.
- The visible artifact tab rendered Genomi version, Python/platform runtime,
  artifact operation/renderer/kind, selected Python package availability, and
  Genomi library materialization state.
- The screenshot confirms the tab uses the normal artifact route and product
  language (`Evidence report`, `Environment partial`) rather than exposing
  context-packet mechanics.

Implementation notes:

- The Environment snapshot is version-owned, like Code/reproduction and Review.
- The snapshot deliberately omits local filesystem paths and treats library
  availability as reproducibility context, not medical negative evidence.
- This is not full Claude Science parity. Genomi still lacks conda/kernel labels,
  host-agent process package capture, package operation history, execution-cell
  dependency links, and a complete environment history.

## Genomi Artifact Work Trail Checkpoint

Claude Science's Execution Log remains a hard gap for Genomi, but the artifact
provenance surface now has a concrete partial equivalent: reusable Work Trail
cards derived from the latest bounded message slice of the producing
conversation's tool events.

Screenshots:

- `screenshots/189-genomi-artifact-work-trail-wide.png`
- Claude Science comparison references:
  `screenshots/168-claude-science-artifact-execution-log.png` and
  `screenshots/136-claude-science-artifact-provenance-execution-log-tab.png`

Browser observations:

- A temporary local portal on `127.0.0.1:8773` rendered a seeded evidence
  report artifact with an origin frame containing paired `variant.resolve`
  tool call/result messages.
- The artifact Work Trail tab rendered one numbered work-step card from the
  artifact's bounded `provenance_messages` slice:
  `01 / completed`, visible title `Variant Resolve`, exact operation id
  `variant.resolve`, run badge, message-count badge, and action buttons for
  `Attach this step` and `Ask about step`.
- The context payload produced by `Attach this step` still preserves exact
  Genomi operation ids (`variant.resolve`) and prompt-safe work-trail text; the
  friendly title is presentation-only.
- Direct navigation to the artifact route with `?tab=trace` left the Preview
  tab active because `tab` is not Genomi's route contract. The canonical query
  key is `?artifact_tab=trace`, and copied artifact links use that route-state
  shape. The renderer no longer normalizes tab state as a render side effect,
  so `?artifact_tab=trace` survives the summary render and opens the Work Trail
  tab once artifact detail provenance loads.

Implementation notes:

- The artifact Work Trail renderer reuses the frame Work Trail card model but
  passes artifact-specific labels and prompt text. It is a bounded
  message-derived projection, not a version-owned execution record.
- This is intentionally not called Execution Log. Genomi still lacks
  normalized execution-cell records, command source, stdout/stderr panes,
  language/environment labels, and cell ids.
- The later implementation unit is an execution-cell record linked to runs,
  tool events, artifacts, versions, and environment snapshots. Until that
  exists, the UI should not claim Execution Log parity.

## Claude Science Capability Gaps To Implement Later

These are Claude Science affordances observed in the workspace/artifact UX that
Genomi does not currently have a true equivalent for. They are not copy tasks
for `/start`; they are product capabilities to schedule after the current chat,
evidence, and artifact loop is stable.

1. Artifact cloud export: Claude Science exposes Export to Cloud on artifact
   objects. Genomi now has persisted Star, Hide, Rename, Delete, and metadata
   export actions for local project artifacts, but it still has no cloud export
   path.
2. Reproducible artifact code: Claude Science's Provenance Code tab shows a
   generated reconstruction script with input chips and a download action. Genomi
   now has a conservative Evidence-report Code tab with a rebuild recipe, but it
   still lacks downloadable script artifacts and full dependency input chips.
3. Cell-level execution logs: Claude Science groups command execution into
   readable cells with command source, labels, and output. Genomi now has
   reusable artifact Work Trail cards for the latest bounded producing tool
   work, but it lacks a normalized execution-log artifact tab for command-like
   host work.
4. Full runtime/package environment snapshots: Claude Science shows a dedicated
   Environment tab with runtime, package, and environment-operation state. Genomi
   now has a minimal artifact-version Environment snapshot, but not full
   host-agent process package capture, conda/kernel labels, execution-cell
   dependency links, or environment history.
5. Review/check runs: Claude Science has a Review tab as a first-class artifact
   surface. Genomi now has deterministic version-owned review checks, but no
   user-triggered/asynchronous check-run system with recorded pass/fail/empty
   histories per artifact.
6. Exact producing-step navigation: Claude Science's View in context navigates
   from an artifact back to its producing conversation state. Genomi has origin
   trace data, chat/artifact routes, and `highlight_run`; exact
   highlight/scroll-to-step navigation remains future work.
7. Project Library upload/import grouping: Claude Science groups files by
   upload/session and keeps imported files as project Library objects. Genomi
   now imports browser-selected files as project artifacts with a Files filter
   and inline text previews, and the Library separates `Your uploads` from
   generated artifacts. It still lacks generated-session group headers and a
   long-running upload/import lifecycle.
8. Bundle downloads: Claude Science exposes session bundle, artifact bundle,
   and artifact script-bundle download endpoints. Genomi now has local
   artifact and frame/session ZIP bundle product objects; artifact-version
   script bundles remain missing.

## Genomi Artifact Bundle Checkpoint

Screenshot:

- `screenshots/190-genomi-artifact-download-bundle-menu.png`

Browser observations:

- A temporary local portal on `127.0.0.1:8774` rendered a seeded evidence
  report artifact with the artifact preview pane open.
- Opening the preview-header artifact actions menu showed `Download bundle`
  beside `Download artifact details`, `Copy link`, `Attach artifact`,
  `Attach review brief`, and `Open report`.
- The browser DOM confirmed the bundle action points to
  `/api/projects/:project_id/artifacts/:artifact_id/bundle`.

Implementation notes:

- The new bundle endpoint returns a local ZIP with `manifest.json`,
  `metadata.json`, and portal-owned artifact version files.
- This intentionally closes only the artifact-bundle slice. Frame/session
  bundles are tracked separately below, and artifact-version script-bundle
  downloads remain a separate product object.

## Genomi Frame Bundle Checkpoint

Screenshot:

- `screenshots/191-genomi-frame-download-bundle-action.png`

Browser observations:

- A temporary local portal on `127.0.0.1:8775` rendered a seeded project frame
  with a transcript and a frame-owned evidence report artifact.
- The chat header exposed `Download bundle` beside the agent selector once the
  frame was open.
- The browser DOM confirmed the action points to
  `/api/projects/:project_id/frames/:frame_id/bundle`.

Implementation notes:

- The frame bundle endpoint returns a local ZIP with `manifest.json`,
  `frame.json`, `messages.json`, artifact metadata JSON files, and
  portal-owned artifact version files under `artifacts/:artifact_id/versions/`.
- The bundle is built from one portal state snapshot and uses the same public
  artifact export model as artifact bundles, so the transcript and artifact
  metadata stay aligned.
- This closes the direct Claude Science-style frame/session bundle action for
  Genomi's current local portal. It does not implement artifact-version
  script-bundle downloads or project Library upload/import grouping.

## Genomi File Import Library Checkpoint

Screenshots:

- `screenshots/193-claude-science-library-reference-current.png`
- `screenshots/195-genomi-imported-file-inline-preview.png`

Browser observations:

- Claude Science's Library pane is visibly a Files surface, not a raw artifact
  JSON list. It separates `Your uploads` from generated session artifacts and
  offers grid/list controls.
- A temporary Genomi portal on `127.0.0.1:8776` rendered a seeded imported CSV
  as a project artifact named `lab-notes.csv`.
- The Genomi artifact Library now exposes a `Files 1` filter beside evidence,
  reports, previewable, hidden, and other filters.
- Selecting the imported file opens the normal artifact detail surface with
  version metadata, `Use artifact`, selection actions, and a Preview tab.
- The Preview tab renders text-like file contents inline in the dark Genomi
  workspace instead of falling back to a browser-default iframe.

Implementation notes:

- Browser imports use a project-scoped JSON upload endpoint for small local
  files and snapshot the uploaded bytes through the existing artifact-version
  machinery.
- Imported files are `project_file` artifacts. They can be previewed, selected,
  bundled, renamed, hidden, starred, deleted, and attached to the next chat
  like other artifact objects.
- Host-agent subprocesses now snapshot the project workspace before a run and
  materialize new or changed small files written under that workspace as
  `project_file` artifacts after a successful run.
- Assistant-produced workspace files use `operation="portal.agent_file"` and
  render under a separate `Produced files` Library group, while browser uploads
  stay under `Your uploads`.
- The portal now exposes a read-only project workspace file listing through
  `/api/projects/:project_id/workspace/files` and a compact `Workspace files`
  surface in Files & Artifacts. It shows relative file names, content type,
  size, search, and `Open artifact` when a file is linked to a snapshot
  artifact; raw backend workspace roots remain private.
- This is a partial Claude Science Library equivalent. Genomi still lacks
  generated-session grouping, folder/session organization, long-running upload
  lifecycle, and richer file-watching behavior.

## UX Subagent Alignment Follow-up

Three independent read-only subagents reviewed the current Genomi portal
against the science-workspace UX pattern and Open Design's local web UI bridge
pattern.

Agreed product decisions:

- Chat/composer is the primary post-onboarding surface.
- Files, generated artifacts, provenance tabs, evidence map, work trail, and
  Genome State privacy/readiness are legitimate user-facing workspace objects.
- Runs, frame ids, selected-context packets, and routing mechanics should stay
  internal unless they are translated into user concepts such as conversations,
  work steps, attached material, and artifacts.
- Expert tools should remain available as expert mode, not the default
  science workflow.
- Starter workflows belong in the empty chat state as suggested first messages,
  not as a separate dashboard pane in the workspace stack.
- Buttons that place material in the composer should say `Use`, not `Attach`,
  because the user is acting from a concrete science object while the context
  packet remains an internal bridge detail.

Implementation notes from this follow-up:

- Assistant subprocesses now run from a project-scoped backend workspace
  directory derived from the portal project id. The public project state exposes
  only logical workspace metadata, not the local filesystem path.
- Follow-up assistant subprocesses now receive a bounded, prompt-safe prior
  user/assistant transcript from the same conversation. The prompt labels that
  transcript as continuity context only, not authoritative Genomi tool evidence.
- The right-stack `Starter Workflows` pane was removed. The same starts now
  render as compact chat suggestions in the welcome message.
- Artifact/result/evidence/genome/request controls were renamed from
  `Attach ...` to `Use ...` where their behavior is composer attachment.
- The run-stream frontend wrapper now tracks the last SSE event id, reconnects
  first with `?after=...` to replay missed events, and checks
  `/api/runs/:run_id` only after reconnect exhaustion before deciding a stream
  error is a real interruption.
- Independent subagent comparison passes checked the portal against the
  reference science-workspace UX, open-design's daemon/host-agent pattern, and
  Genomi's own evidence/AGI contracts. The consensus was to keep chat,
  conversations, Files & Artifacts, Evidence from this chat, Work trail, Genome
  state, and artifact provenance as first-class surfaces, while demoting
  Expert tools, technical JSON, operation traces, and renderer state to expert
  or technical-detail surfaces.
- The visible shell now follows that synthesis: the primary rail exposes
  `Research workspace` and `Files & Artifacts`; `Evidence from this chat`,
  `Work trail`, `Genome state`, and `Expert tools` sit under `Workspace
  details`. The explanatory `Local workspace` rail card is gone; Genome State
  keeps raw JSON behind `Technical state`; artifact tabs use user-facing labels
  such as `Tool calls`, `Origin chat`, `Rebuild recipe`, and `Technical state`.
- Host-agent-produced files written into the backend project workspace are now
  imported into the same artifact/version system as other portal files and
  emitted as normal artifact events, keeping generated files visible in the
  web workspace rather than stranded in an internal directory.
- A read-only workspace file browser now sits above the artifact Library. It
  follows the Open Design pattern of daemon-owned files without exposing
  filesystem roots: users see project-relative files, can search them, and can
  open the linked Genomi artifact when one exists.

Remaining architecture gaps:

- Richer workspace file watching, folder/session grouping, and generated-run
  Library grouping.
- Full host-agent session resume beyond bounded transcript handoff.
- Execution cells, script bundles, full environment graphs, and async check-run
  lifecycle remain real missing capabilities.

## Friendly Operation Labels Browser Check

After the operation-label alignment slice, the Genomi portal and the local
reference workspace were opened in the in-app browser for a lightweight visual
comparison.

Screenshots:

- `screenshots/198-genomi-friendly-operation-labels-nav.png`
- `screenshots/199-reference-work-step-labels.png`

Observed reference pattern:

- The reference workspace presents work as named task/step cards such as
  setup, file reads, commands, and outputs.
- The visible workspace language is object/task oriented. It does not make raw
  tool operation ids the primary labels for users.

Genomi implication:

- The portal shell now keeps `Work trail` and `Genome state` as first-class
  workspace objects and leaves `Expert tools` behind the advanced disclosure.
- Evidence ledger, work-trail, target-packet, and selected-context surfaces now
  use friendly operation labels such as `Variant lookup` and `Target evidence
  report` for visible UI while preserving exact operation ids in
  `source_operation`, prompts, and technical details.
- Invalid or free-form `source_operation` values, including path-like strings,
  fall back to a generic safe label instead of being title-cased into visible
  path fragments.

## Tool Metadata Label Boundary

Follow-up browser/API check after moving short portal labels into operation
metadata.

Screenshots:

- `screenshots/200-genomi-tool-metadata-label-boundary.png`
- `screenshots/201-reference-workstep-artifact-search-boundary.png`

Observed reference pattern:

- The reference workspace still reads as a task/work-step surface: visible
  buttons name work such as reading files, setting up environments, running
  commands, checking data access, and downloading truth sets.
- Artifact search is a workspace affordance, not an operation catalog.

Genomi implication:

- Genomi operation metadata now exposes `annotations.portalLabel` separately
  from the host-agent status `annotations.title`.
- The portal Expert tools surface prefers `portalLabel` for visible labels but
  preserves raw operation ids in payloads and technical details.
- The browser fallback label helper remains only for legacy result events,
  portal pseudo-events, and operation ids that arrive without full metadata.

## Primary Workspace / Secondary Details Boundary

Subagent comparison pass after reviewing the reference workspace docs,
screenshots, Open Design daemon bridge, and current Genomi portal templates.

Screenshots:

- `screenshots/204-genomi-desktop-primary-nav-default.png`
- `screenshots/205-genomi-desktop-workspace-details-open.png`

Observed reference and Open Design pattern:

- The primary user workflow is chat plus files/artifacts. Work steps and
  provenance are visible where they explain the message or artifact that
  produced them.
- The web UI routes through a local server/daemon that owns project, run,
  message, artifact, and event state. The host agent does the reasoning; the
  browser does not become a separate LLM backend.
- Users select research objects: conversations, files, artifacts, source lanes,
  work steps, and provenance tabs. They are not asked to select context packets,
  schemas, operation ids, or internal evidence-envelope mechanics.

Genomi implication:

- The rail now exposes only `Research workspace` and `Files & Artifacts` as
  primary navigation. `Evidence from this chat`, `Work trail`, `Genome state`,
  and `Expert tools` sit under `Workspace details`.
- The evidence map remains available after evidence exists, but the dedicated
  pane does not appear as a peer workspace surface until the user opens it.
  Inline tool/result rendering remains the main evidence path.
- Artifact runtime metrics now omit raw `Operation` and `Renderer`; those stay
  in `Details` through the operation trace. Artifact fallback summaries also
  translate operation ids and underscore states into user-facing labels when
  possible.
- Tool chips and work-trail step details no longer dump raw request/result JSON
  as normal visible detail. Raw request/result material is kept behind an
  explicit `Technical details` disclosure and remains copyable for debugging.
- Conversation-level bundle actions and artifact metadata actions now name the
  object being handled: conversation bundle, artifact bundle, and metadata,
  instead of generic or renderer/operation-oriented detail language.

Remaining alignment work:

- Add normalized execution-cell records and exact producing-step links on top
  of the existing canonical run API, durable run-event replay, event pages,
  and result package model.
- Continue reducing raw operation ids, renderer names, version hashes, and
  state codes in primary artifact cards while keeping exact ids in technical
  details and prompt-safe payloads.
- Do not claim parity with full execution logs, script bundles, rich
  environment graphs, cloud export, or async check-run lifecycle until Genomi
  has real user-facing objects for those jobs.

## Legacy Report Presentation Boundary

Follow-up alignment pass after removing obsolete dashboard-first product
language from the current portal shell.

Implementation notes:

- Stored artifacts may still carry legacy renderer or operation ids such as
  `decode_dashboard` and `decode.render_dashboard`; those remain compatibility
  identifiers for old records, traces, and rebuild metadata.
- The user-facing artifact model now presents those records as reports:
  artifact family `legacy_report`, category `report`, Library filter
  `Reports`, open label `Open report`, and report section state.
- Legacy summary text such as `1 panel rendered` is normalized at the display
  boundary to `1 section rendered`. Persisted artifact payloads are not
  rewritten.
- Raw renderer names and operation ids stay in operation traces and technical
  details, not artifact cards, runtime metrics, or default workspace copy.
- This keeps useful old artifact records available without reviving the old
  dashboard flow as the portal's mental model.

Subagent follow-up after the comparison pass flagged two additional product
copy leaks, both now fixed:

- Empty-chat genome-review suggestion copy no longer says the user is avoiding
  a one-shot dashboard. It now positively frames the workflow as chat, sourced
  findings, workspace reports, and provenance together.
- Newly persisted legacy renderer artifacts now enter the portal with the title
  `Genomi Report`, open label `Open report`, and section-oriented summary
  lines. Existing old records still translate at the frontend display boundary.

Open Design comparison also reaffirmed the architecture boundary:

- The browser owns the visible chat.
- The local server owns durable project, frame, run, event, file, and artifact
  state.
- The host CLI is a reasoning runtime behind that surface, not a second
  user-facing chat UI.
- User-facing selected-context behavior should keep saying attached material,
  evidence from this chat, or ask about this evidence; `selectedEvidence`
  remains an internal bridge name.

## Selected Material Copy Boundary

Follow-up UX alignment pass after the Open Design comparison focused on the
composer context bridge.

Implementation notes:

- The internal browser/server bridge still uses `selectedEvidence` because it
  is the durable payload contract for selected visual context.
- User-facing selection bars and inspectors now say `selected material` rather
  than `selected evidence item`. This affects evidence-ledger selections,
  purpose-built result nodes, generic evidence panels, and fallback message
  chips.
- Prompt text may still use evidence-specific language when it instructs the
  host agent how to reason from selected Genomi evidence. The copy boundary is
  user chrome versus assistant handoff semantics, not a ban on the word
  evidence.
- Artifact `Details` remains a follow-up. The comparison agents were right
  that raw tool/runtime/state details should be demoted; the follow-up
  implementation now keeps technical data routeable while removing it from the
  primary tab row.

## Artifact Technical Details Demotion

Follow-up UX implementation after the selected-material copy boundary.

Implementation notes:

- Artifact tabs are now split into primary `tabs` and secondary
  `secondaryTabs` in the artifact view model. `allTabs` preserves routeability
  and activation for both groups.
- `Technical details` remains renderable and deep-linkable through
  `?artifact_tab=technical`, but it is no longer a peer in the visible primary
  tab row beside Preview, Evidence, Origin chat, Work trail, Review, Rebuild,
  and Environment.
- The artifact action menu exposes `Technical details` as the explicit access
  point for tool calls, runtime/source details, and technical state.
- Copy-link behavior still uses the active tab, so opening technical details
  and copying a workspace link can preserve that inspection surface.

## Assistant Prose Is Not Portal State

Follow-up UX implementation after the subagent comparison pass identified the
browser-side assistant checklist parser as the wrong lesson from the reference
workspace.

Implementation notes:

- `portal_messages.js` no longer scans assistant text for `Evidence I would
  inspect` or any other Markdown heading.
- Assistant answers now render as answer text only unless durable server/run
  state supplies typed tool events, artifacts, evidence nodes, work trails, or
  other portal presentation models.
- The previous `assistant_checklist` payload creator and selection-model helper
  were removed from the message renderer. Typed selected material from result
  nodes, evidence panels, artifacts, genome state, work trails, and tool
  requests continues to use the selected-material bridge.
- The old assistant-checklist fixture was converted into a boundary fixture:
  the sample answer still contains an evidence-list heading, but the browser
  does not create selectable lanes or a next-turn packet from prose.
- Focused verification:
  - `node --check src/genomi/interfaces/templates/portal_messages.js`
  - `PYTHONPATH=src pytest tests/test_portal_frontend_assets.py -k 'assistant_prose or user_facing' -q`
  - `PYTHONPATH=src pytest tests/test_portal_frontend_assets.py -q`
  - `for file in src/genomi/interfaces/templates/*.js; do node --check "$file" || exit 1; done`

## Server-Owned Prompt Suggestions

Follow-up implementation after the assistant-prose boundary removed the
browser-created checklist surface but left several browser-authored follow-up
prompts.

Implementation notes:

- Added `/api/prompt/suggestion` as the server-side contract for turning typed
  selected material into draft composer text.
- The endpoint reuses the selected-material sanitizer before choosing wording,
  so local paths and raw browser payloads are still redacted before host-agent
  handoff.
- `portal_prompt_context.js` now asks the server for Ask/Draft wording through
  `onSuggestPrompt`. Its fallback is intentionally generic and contains no
  operation-routing policy.
- Tool-result, evidence-ledger, and work-trace follow-up buttons now pass typed
  context payloads instead of prewritten browser prompt policy. Persisted
  display-only history becomes `work_trace` context so the server treats it as
  provenance to re-check, not current evidence.
- Removed the remaining assistant-checklist operation/context labels and
  orphaned checklist CSS from the portal source.
- Screenshot:
  - `screenshots/206-genomi-server-prompt-suggestion-boundary.png`
  - `screenshots/207-reference-typed-workspace-state.png`
- Reference check: the local science workspace route still presented sessions,
  work steps, library/artifact affordances, and generated outputs as typed
  workspace objects. This supports moving Genomi follow-up behavior through
  typed selected material and server-owned prompt suggestions rather than
  browser-parsed assistant prose.
- Focused verification:
  - `PYTHONPATH=src pytest tests/test_portal_frontend_prompt_context.py tests/test_portal_frontend_routes.py -q`
  - `PYTHONPATH=src pytest tests/test_portal_frontend_assets.py -q`
  - `PYTHONPATH=src pytest tests/test_portal*.py -q`
  - `for file in src/genomi/interfaces/templates/*.js; do node --check "$file" || exit 1; done`
  - `python3 -m py_compile src/genomi/interfaces/portal_prompt_suggestions.py src/genomi/interfaces/portal.py src/genomi/interfaces/portal_runs.py`
  - Browser smoke at `http://127.0.0.1:8815/`: portal loaded with no console
    errors and no assistant-checklist DOM nodes.

## UX Alignment Subagent Pass

Follow-up implementation after three independent subagents compared the current
portal against the reference science workspace and the Open Design daemon
bridge.

Implementation notes:

- The portal keeps the primary workspace model: chat, conversations, Files &
  Artifacts, artifact preview, selected attached material, Work trail, Genome
  state, Review, Rebuild, Environment, and provenance.
- The advanced tool surface is now labeled `Source lookup setup`, and the
  browser catalog requires an explicit source-lookup allowlist or annotation.
  The previous broad "any dotted read operation" fallback was removed.
- Prepared tool contexts now read as `Prepared source lookup` instead of
  `Prepared evidence request`. The server prompt-suggestion endpoint uses the
  same wording, so host-agent handoff text and browser text do not drift.
- Artifact metadata moved further behind technical language: artifact action
  menu labels now say `Copy technical metadata`, `Download technical metadata`,
  and `Download artifact bundle`.
- Artifact metadata/provenance tabs are labeled `Provenance`, while evidence
  panels keep evidence/source-lane language.
- Target evidence reports no longer expose `Available operations` or `Evidence
  options` as primary lanes. They show the target, sources, and stored research;
  follow-up routing remains a host-agent/tool concern.
- Screenshots:
  - `screenshots/208-genomi-current-workspace-ux-subagent-pass.png`
  - `screenshots/209-genomi-workspace-details-expanded-ux-subagent-pass.png`

## Composer Attached Material Tray

Follow-up implementation after the source-check alignment pass. The composer
already owned selected material, but it only showed removable chips. That made
the interaction feel like a hidden packet mechanism instead of an inspectable
workspace object.

Implementation notes:

- `portal_prompt_context.js` now exposes a pure composer tray view model and
  renders selected material as compact cards.
- Cards show friendly kind/source labels, selected-item counts, readable
  envelope state, and the first selected values before the turn is sent.
- Visible tray strings replace operation ids with friendly source labels and
  collapse repeated node prefixes; typed prompt payloads still preserve the
  handles needed by the server.
- Browser verification at `http://127.0.0.1:8783/`: selected Genome state facts
  appeared as `Attached material` with `Genome state`, `7 selected items`, and
  compact values such as `Current genome / Build` -> `GRCh38`.
- Reference check at
  `http://localhost:8765/projects/proj_65ee842cd510/frames/991ad887-1322-458d-9f87-91201044b16f`:
  the workspace showed a chat composer beside typed file/artifact/session
  objects. The relevant lesson for Genomi remains composer-adjacent selected
  workspace objects, not a visible packet builder.
- Screenshot:
  - `screenshots/20260703-genomi-attached-material-tray.png`
  - `screenshots/20260703-reference-workstep-composer-check.png`
- Focused verification:
  - `node --check src/genomi/interfaces/templates/portal_prompt_context.js`
  - `PYTHONPATH=src pytest tests/test_portal_frontend_prompt_context.py -q`
  - `PYTHONPATH=src pytest tests/test_portal_frontend_prompt_context.py tests/test_portal_frontend_evidence_ledger_selection.py tests/test_portal_frontend_artifact_selection.py tests/test_portal_frontend_result_presentations.py tests/test_portal_frontend_assets.py -q`

Review follow-up:

- A strict maintainability review flagged three boundary issues: browser-owned
  selected-material prompt prose, inconsistent Ask/Draft/Submit selected sets,
  and broad dotted-token display replacement.
- Follow-up fixes made selected-material sets canonical in
  `portal_prompt_context.js`, narrowed operation-id display cleanup to the
  exact `source_operation`, stopped storing browser `prompt_text` for
  node-backed material, and made `portal_turns.clean_selected_evidence` derive
  selected-node prompt sections on the server.
- Regression verification:
  - `PYTHONPATH=src pytest tests/test_portal_*.py tests/test_mcp_http.py -q`
  - `for file in src/genomi/interfaces/templates/*.js; do node --check "$file" || exit 1; done`
  - `python3 -m py_compile src/genomi/interfaces/portal_turns.py`

## Workspace File Preview

Follow-up implementation after the Files pane comparison. The artifact library
already grouped uploads, produced files, and generated artifacts, but file-only
workspace outputs were still just rows unless they had already been
materialized as artifacts.

Implementation notes:

- Added `/api/projects/{project_id}/workspace/file-preview?path=...` as a
  bounded preview endpoint for project-scoped workspace files.
- The backend resolves only files inside the project workspace, refuses path
  traversal, caps preview size, redacts local paths in text previews, returns
  text previews for text-like files, and returns data URLs for small images.
- `portal_workspace_files.js` now renders a `Preview file` action and an inline
  preview panel above the file rows. Binary or over-limit files produce an
  honest unavailable state.
- Live browser verification at `http://127.0.0.1:8784/`: a temporary project
  containing `reports/apoe.txt` showed the file-only row, opened inline with
  `APOE report` and `Variant evidence summary`, and kept the row available.
- Reference check at
  `http://localhost:8765/projects/proj_65ee842cd510/frames/991ad887-1322-458d-9f87-91201044b16f`:
  the Files pane still exposes uploads and generated artifacts as directly
  inspectable workspace objects beside the chat.
- Screenshots:
  - `screenshots/20260703-genomi-workspace-file-preview.png`
  - `screenshots/20260703-reference-files-pane-check.png`
- Verification:
  - `PYTHONPATH=src pytest tests/test_portal_workspace_files.py tests/test_portal_frontend_workspace_files.py tests/test_mcp_http.py::MCPHTTPTests::test_project_workspace_files_endpoint_lists_relative_files tests/test_mcp_http.py::MCPHTTPTests::test_project_workspace_file_preview_endpoint_returns_bounded_preview -q`
  - `PYTHONPATH=src pytest tests/test_portal_*.py tests/test_mcp_http.py -q`
  - `for file in src/genomi/interfaces/templates/*.js; do node --check "$file" || exit 1; done`
  - `python3 -m py_compile src/genomi/interfaces/portal_workspace_files.py src/genomi/interfaces/portal.py`

## UX Subagent Pass And Execution-Cell Work Trail

Three independent subagents rechecked the Genomi web UI against the stored
science-workspace captures, the Open Design daemon bridge, and the current
portal implementation. They agreed that the architecture is aligned but the
UX risk remains disclosure bleed: the default workspace should show research
objects, not frames, runs, route ids, schemas, packets, operation ids, or host
adapter chatter.

Implementation notes:

- Added source-neutral portal object-test guidance to `AGENTS.md`.
- Recorded the subagent synthesis and prioritized backlog in
  `webui-ux-comparison-and-alignment.md`.
- Updated `capability-gap-backlog.md` so execution cells are represented as a
  partial Work trail equivalent, not full execution-log parity.
- Added `api.loadRunResultPackage` and frame-level execution-cell loading in
  `portal.js`.
- `portal_frame_trace.js` now accepts `executionCells`, skips duplicate tool
  cells when transcript tool messages already render the work step, and adds
  diagnostic/stdout/stderr/artifact/run-completion cells as Work trail steps.
- Host-agent stdout/stderr remains diagnostic Work trail state rather than
  assistant answer prose.
- Live browser verification at
  `http://127.0.0.1:8796/projects/proj_6722fee5d3a6/frames/d52d106b-a197-43e7-ad0d-7431d040eb08`:
  the Work trail rendered one transcript-derived `Variant lookup` step plus
  execution-cell-backed diagnostic, artifact, and run-finished cards. The
  duplicate tool execution cell was suppressed because the transcript already
  carried that tool step. Later display wording changed stdout/stderr cells to
  `Diagnostic output`.
- Screenshots:
  - `screenshots/20260703-genomi-execution-cell-work-trail.png`
  - `screenshots/20260703-genomi-execution-cell-work-trail-cards.png`

Verification:

- `node --check src/genomi/interfaces/templates/portal_frame_trace.js`
- `node --check src/genomi/interfaces/templates/portal.js`
- `node --check src/genomi/interfaces/templates/portal_api.js`
- `PYTHONPATH=src pytest tests/test_portal_frontend_frame_trace.py tests/test_portal_execution_cells.py tests/test_portal_sidecar_operations.py::PortalSidecarOperationTests::test_retrieve_portal_run_result_package_replays_durable_run_events -q`
- `PYTHONPATH=src pytest tests/test_portal_frontend_run_stream.py tests/test_portal_frontend_assets.py tests/test_mcp_http.py::MCPHTTPTests::test_run_result_package_returns_public_workspace_handoff -q`
- `PYTHONPATH=src pytest tests/test_mcp_http.py::MCPHTTPTests::test_run_event_page_returns_bounded_sanitized_events -q`
- `PYTHONPATH=src pytest tests/test_portal_frontend_artifact_models.py tests/test_portal_frontend_artifact_origin_trace.py tests/test_portal_frontend_workspace_files.py -q`

## Artifact Work Trail Execution Cells

Follow-up feature slice after the conversation Work trail execution-cell pass.
The artifact Work trail was still message-derived even when the producing run
had a richer result package.

Implementation notes:

- Added `portal_artifact_work_trace_controller.js`, a small active-artifact
  loader that reads the producing run ids from artifact origin context and
  origin messages, fetches run result packages, and reuses the shared
  execution-cell normalization helper.
- `artifactWorkTraceModel` and `renderArtifactWorkTrace` now accept
  `executionCells` and pass them through to the shared frame Work trail model.
- `renderArtifactPreview` now hydrates the active artifact's producing-run
  cells lazily and re-renders the preview when they arrive.
- Duplicate tool execution cells remain suppressed when the origin transcript
  already has the matching tool call/result pair.
- Stdout/stderr execution cells render as `Diagnostic output` with the generic
  public summary `Host-agent diagnostic output recorded.` in cards, details,
  and selected-context payloads while preserving the raw kind/event metadata in
  structured data.
- Post-review hardening keeps the explicit producing run id outside the
  secondary run-id cap, scopes the artifact trace cache by project/artifact/
  version/run identity, and clears that cache on workspace reset.

Live browser verification used an isolated `GENOMI_HOME` and
`genomi serve --transport http --host 127.0.0.1 --port 8799`. The seeded
artifact route was:

`http://127.0.0.1:8799/projects/proj_e00c3858a434/artifacts/art_1dd59c234e35?artifact_tab=trace`

The Work trail rendered four cards:

- `Variant lookup`
- `Diagnostic output`
- `Artifact`
- `Run finished`

Screenshots:

- `screenshots/20260703-genomi-artifact-work-trail-execution-cells-focused.png`
- `screenshots/20260703-genomi-artifact-work-trail-execution-cells-lower.png`

Verification:

- `node --check src/genomi/interfaces/templates/portal_artifact_work_trace_controller.js`
- `node --check src/genomi/interfaces/templates/portal_artifact_origin_trace.js`
- `node --check src/genomi/interfaces/templates/portal_artifacts.js`
- `node --check src/genomi/interfaces/templates/portal_frame_trace.js`
- `node --check src/genomi/interfaces/templates/portal.js`
- `PYTHONPATH=src pytest tests/test_portal_frontend_artifact_origin_trace.py tests/test_portal_frontend_frame_trace.py tests/test_portal_frontend_artifact_models.py -q`
- `PYTHONPATH=src pytest tests/test_portal_*.py tests/test_mcp_http.py -q`
- Post-review focused check:
  `PYTHONPATH=src pytest tests/test_portal_frontend_artifact_origin_trace.py tests/test_portal_frontend_frame_trace.py -q`
- Post-review broad check:
  `PYTHONPATH=src pytest tests/test_portal_*.py tests/test_mcp_http.py -q`

## Portal Copy Cleanup And Source Panel Verification

Feature-alignment slice focused on visible workspace language rather than new
science capability. The user-facing target is a research workspace with
selectable evidence/source/work objects, not a tool console or setup wizard.

Implementation notes:

- Diagnostic-only host/runtime events remain explicit diagnostic records in
  `portal_messages.js`, but the visible card now reads `Assistant status notes`
  with `status update` copy. Diagnostic fields stay typed and prompt-safe under
  the hood.
- The message work-trail payload can include diagnostic records without
  fabricating a `host_agent_diagnostics` tool result.
- Source-prep language is normalized around `Evidence sources`, `Choose`,
  `Attach source`, `Draft question`, and `Ask with source`.
- Legacy selected-material prompt text such as `Prepared Genomi
  evidence-source request` is normalized to `Attached evidence source` before
  it appears in composer state.
- Source lookup technical disclosure now labels operation effect as
  `Workspace effect` instead of `Operation scope`.
- Active artifact-view context now reports the visible environment tab as
  `Source limits`, matching the actual artifact tab label.

Live Genomi verification used a fresh branch server:

`http://127.0.0.1:8808/#tool-launcher`

Browser DOM inspection of the fresh server found none of these visible strings
in the portal/source panel: `Source checks`, `Prepare`, `Operation scope`,
`Runtime & source limits`, or `Assistant diagnostics`.

Reference workspace sanity check used:

`http://localhost:8765/projects/proj_65ee842cd510/frames/991ad887-1322-458d-9f87-91201044b16f`

The reference still reinforces the current target pattern: compact work-step
cards, expandable technical/tool details, and artifact/file side panels. Genomi
should keep matching those user-facing objects while using Genomi-native labels
for evidence sources, current evidence, genome state, source limits, and work
trail.

Screenshots:

- `screenshots/20260703-genomi-serve-evidence-sources-copy-cleanup-fresh.png`
- `screenshots/20260703-reference-workspace-copy-sanity.png`

Verification:

- `node --check src/genomi/interfaces/templates/portal_messages.js`
- `node --check src/genomi/interfaces/templates/portal_prompt_context.js`
- `node --check src/genomi/interfaces/templates/portal_operation_labels.js`
- `node --check src/genomi/interfaces/templates/portal_frame_trace.js`
- `PYTHONPATH=src pytest tests/test_portal_frontend_assets.py::PortalFrontendAssetTests::test_message_surface_aggregates_diagnostics_as_collapsed_work_detail tests/test_portal_frontend_assets.py::PortalFrontendAssetTests::test_live_result_actions_can_submit_selected_context tests/test_portal_frontend_prompt_context.py::PortalPromptContextFrontendTest::test_prompt_context_actions_and_wording_preserve_context_kind tests/test_portal_frontend_prompt_context.py::PortalPromptContextFrontendTest::test_server_prompt_suggestion_handles_request_artifact_and_empty_contexts -q`
- `PYTHONPATH=src pytest tests/test_mcp_http.py::MCPHTTPTests::test_portal_source_lookups_endpoint_returns_curated_cards tests/test_mcp_http.py::MCPHTTPTests::test_portal_source_check_prepare_endpoint_owns_chat_handoff tests/test_mcp_http.py::MCPHTTPTests::test_portal_source_check_prepare_reports_missing_condition_inputs -q`

## Server-Owned Candidate Evidence Presentation

Feature-alignment slice focused on moving candidate-ranking results out of the
browser fallback renderer and into the same server-owned presentation contract
used by variant and medication-review evidence.

Implementation notes:

- Candidate evidence operations now emit a
  `genomi_portal_result_presentation` model from
  `portal_result_presentations.py`.
- The presentation exposes four user-facing lanes:
  `Candidate comparison`, `Supporting evidence`, `Evidence boundary`, and
  `Coverage and limits`.
- `Coverage and limits` is display-only. Users can select candidate rows and
  supporting source records for follow-up chat context, but policy/boundary
  metadata is shown as interpretation context rather than attachment material.
- Persisted history now keeps the minimal candidate-view fields required to
  rebuild the server presentation after reload without preserving private or
  noisy raw payload fields.
- The frontend still knows how to render candidate evidence, but tests now
  assert that a server presentation wins over the old browser fallback.

Reference-workspace alignment:

- The useful reference pattern is not a separate dashboard; it is a compact
  work-step card that expands into readable tool/result detail.
- Genomi applies that pattern by keeping the chat row compact, then expanding
  into evidence lanes that are readable and selectable inside the conversation.
- The UI does not ask users to manually choose an "evidence packet"; users
  select visible scientific material when they need it in the next turn.

Screenshots:

- `screenshots/20260703-genomi-candidate-evidence-server-presentation-viewport-verified.png`
- `screenshots/20260703-genomi-candidate-evidence-lanes-top-verified.png`
- `screenshots/20260703-genomi-candidate-evidence-lanes-viewport-verified.png`

Verification:

- Browser DOM check against
  `http://127.0.0.1:8811/projects/proj_761cd14ef030/frames/a6b916a5-a54a-4138-a674-3e864fa04bae`
  confirmed the expanded visible detail uses server lanes and does not contain
  `browser_fallback_candidate`.

Post-review correction:

- The strict review pass found that the browser still duplicated candidate
  presentation semantics and that wrapper calls could still surface
  `genomi.invoke` as the visible work-step label.
- The browser candidate fallback was removed. Candidate evidence now renders
  only when the server supplies `portal_presentation`.
- Follow-up context now prefers visible server result lanes before generic
  evidence-envelope packets.
- `portal_presentation.operation` is now the canonical visible operation for
  result-view work-step labels, so a `genomi.invoke` transport wrapper displays
  the actual capability label, for example `GWAS Compare Variant Associations`.
- Persisted ClinVar candidate scans redact private/sample candidate rows and
  keep only aggregate scan summary and coverage/limit lanes.
- The frontend parser drops malformed server lanes/nodes instead of inventing
  broad labels such as `Result lane` or `Evidence item`.

Additional screenshot:

- `screenshots/20260703-genomi-candidate-evidence-server-owned-post-review.png`

Post-review verification:

- `python3 -m py_compile src/genomi/interfaces/portal_turns.py src/genomi/interfaces/portal_result_presentations.py tests/test_portal_result_presentations.py tests/test_portal_frontend_result_presentations.py`
- `node --check src/genomi/interfaces/templates/portal_messages.js src/genomi/interfaces/templates/portal_result_renderers.js src/genomi/interfaces/templates/portal_tool_result_presentation.js`
- `PYTHONPATH=src pytest tests/test_portal_result_presentations.py tests/test_portal_frontend_result_presentations.py tests/test_portal_frontend_assets.py -q`
- `PYTHONPATH=src pytest tests/test_portal_*.py tests/test_mcp_http.py -q`

## Server-Owned Target Evidence Report Presentation

Feature-alignment slice focused on moving
`research.build_target_packet` chat-result rendering into the same
server-owned `genomi_portal_result_presentation` contract used by variant,
medication-review, and candidate evidence results.

Implementation notes:

- Target evidence reports now emit server presentation models from
  `portal_target_result_presentations.py`, routed by
  `portal_result_presentations.py`.
- The chat result view exposes user-facing lanes: `Target`,
  `Reviewed research`, `Source catalog`, `Evidence readiness`, and
  `Coverage and limits`.
- `Evidence readiness` and `Coverage and limits` are display-only lanes. Users
  can select the target, reviewed findings, and source catalog records for the
  next turn without attaching policy/source-boundary metadata as evidence.
- The browser no longer registers `research.build_target_packet` as a raw
  chat-result renderer. The existing target-packet frontend model remains
  reusable for artifact/report state, but normal chat results require a server
  `portal_presentation`.
- Persisted target report history keeps public `purpose` text so reloads keep
  the same friendly summary as live events.
- Visible tool-chip summaries now prefer server presentation and ledger copy
  before raw payload headlines, preventing operation headlines such as
  `research.build_target_packet: evidence_present` from becoming product copy.

Reference-workspace alignment:

- The reference workspace reinforces compact work-step cards that expand into
  readable scientific/result detail. Genomi follows that by keeping the target
  report as a chat work result with expandable evidence lanes rather than a
  separate dashboard or user-selected "evidence packet" workflow.

Screenshots:

- `screenshots/20260703-genomi-target-packet-server-presentation.png`
- `screenshots/20260703-genomi-target-packet-server-presentation-lanes-clipped.png`
- `screenshots/20260703-genomi-target-packet-server-presentation-lanes-lower.png`
- `screenshots/20260703-reference-workspace-target-report-sanity.png`

Verification:

- Browser DOM check against
  `http://127.0.0.1:8815/projects/proj_54e6281a69b1/frames/9576b87b-975e-4843-adc2-a9e34bf5d5cc`
  confirmed `Target evidence report`, the friendly target-report purpose, all
  target/source/coverage lanes, and no visible raw operation headline or local
  path.
- Reference browser check against
  `http://localhost:8765/projects/proj_65ee842cd510/frames/991ad887-1322-458d-9f87-91201044b16f`
  confirmed the comparable science-workspace pattern: compact step cards,
  readable work summaries, and a files/artifacts workspace instead of a
  dashboard-first flow.
- `node --check src/genomi/interfaces/templates/portal_tool_result_presentation.js src/genomi/interfaces/templates/portal_result_renderers.js`
- `PYTHONPATH=src pytest tests/test_portal_result_presentations.py tests/test_portal_target_packet_renderer.py tests/test_portal_frontend_result_presentations.py tests/test_portal_frontend_assets.py -q`

## Evidence Source Handoff Copy Cleanup

Feature-alignment slice focused on removing internal source-setup language
from the secondary Evidence sources pane.

Implementation notes:

- Visible source actions now say `Use in chat`, `Draft question`, and
  `Ask with source`; the user-facing surface no longer says `Attach source`.
- Empty and loading copy now describes choosing or using an evidence source for
  the next question rather than "attaching" one.
- The normal source chooser now hides the library-readiness operation because
  it is support state, not an evidence source a scientist should choose before
  asking a question.
- The Genomi support entries are now labeled `Add genome file` and
  `Search public sources` instead of implementation-shaped source/index
  language.
- `/api/evidence-sources/attach` owns the server handoff, and the returned
  surface is `evidence_source_handoff` with an `evidenceSource` summary.
- Drafted composer text is source-facing: `Use Target evidence report as the
  evidence source if it fits my question.` It preserves provided inputs, source
  limits, visible defaults, and privacy boundaries without mentioning
  preparation.
- Responsive verification confirmed the mobile workspace nav exposes Evidence
  sources when the desktop rail is hidden.

Screenshots:

- `screenshots/20260703-genomi-evidence-sources-curated-source-list.png`
- `screenshots/20260703-genomi-evidence-sources-panel-viewport.png`
- `screenshots/20260703-genomi-evidence-source-builder-crop.png`
- `screenshots/20260703-genomi-evidence-source-draft-clean-copy.png`

Follow-up UX note:

- Evidence sources currently behave as an advanced pane stacked below the
  primary research workspace at narrow widths. That is acceptable for source
  handoff because the composer remains visible, but the pane/tab relationship
  should be revisited if the mobile workspace starts feeling like a long
  document instead of a focused workspace.

Verification:

- Browser check against
  `http://127.0.0.1:8828/projects/proj_a3704c4a3c56#tool-launcher`
  confirmed no visible `Source check`, `Prepare`, `Preparation`,
  `Attach source`, or attach-helper copy in the selected Target evidence report
  source handoff.
- Browser check against
  `http://127.0.0.1:8830/projects/proj_5341523e8b62#tool-launcher`
  confirmed the curated source chooser has 8 visible source choices, labels
  `Add genome file` and `Search public sources`, and no
  `genomi.check_libraries` readiness card.
- `node --check src/genomi/interfaces/templates/portal.js src/genomi/interfaces/templates/portal_tool_catalog.js src/genomi/interfaces/templates/portal_tool_request_builder.js`
- `PYTHONPATH=src pytest tests/test_portal_frontend_assets.py tests/test_portal_frontend_tool_catalog.py tests/test_mcp_http.py::MCPHTTPTests::test_portal_source_check_prepare_endpoint_owns_chat_handoff tests/test_mcp_http.py::MCPHTTPTests::test_portal_source_check_prepare_reports_missing_condition_inputs -q`
- `PYTHONPATH=src pytest tests/test_portal_*.py tests/test_mcp_http.py -q`

## Guided Target Evidence Source Builder

Feature-alignment slice focused on making the common Target evidence report
source handoff feel like a science workspace control instead of a raw operation
parameter form.

Implementation notes:

- Target evidence report now shows a `Review target` chip row for
  `Condition`, `Medication`, `Gene`, `Topic`, and `Variant`.
- The underlying `target_type` select remains the submitted source parameter,
  but it is hidden from the normal UI.
- Choosing a chip reveals only the relevant target input. For example, choosing
  `Topic` reveals a single Topic field.
- `Genome build` and `Limit` move into a collapsed `Source limits` disclosure
  for this source, so normal users are not forced through source-limit fields.
- The inspector no longer repeats the generated `Inputs` section below the
  interactive request builder. Boundary and technical disclosure remain
  available.

Screenshot:

- `screenshots/20260703-genomi-guided-target-source-builder-final.png`
- `screenshots/20260703-reference-compact-workstate-after-guided-builder.png`

Reference-workspace alignment:

- The reference science workspace puts the normal user surface around project
  state, files/artifacts, and a compact composer, with operational detail
  available but not presented as the primary choice. The guided Target evidence
  report form follows the same product boundary: intent chips first, optional
  source limits collapsed, and technical/source details behind disclosure.

Verification:

- Browser check against
  `http://127.0.0.1:8832/projects/proj_565761979a82#tool-launcher`
  confirmed `Topic` becomes the active target chip, the Topic field is visible,
  the target-type select is hidden, `Source limits` is collapsed, and the
  duplicated `Inputs` section is absent.
- Drafting from the guided builder produced the same server-owned source
  prompt: `Use Target evidence report as the evidence source if it fits my
  question.`
- `node --check src/genomi/interfaces/templates/portal_tool_request_builder.js src/genomi/interfaces/templates/portal_tool_catalog.js`
- `PYTHONPATH=src pytest tests/test_portal_frontend_tool_catalog.py tests/test_portal_frontend_assets.py -q`

## Declarative Source Builder Cleanup

Post-review architecture cleanup for the same Target evidence report source
handoff. The visible UX stays the same, but the implementation no longer makes
the generic request builder know about `research.build_target_packet`.

Implementation notes:

- Source lookup payloads now carry declarative `request.ui` metadata for guided
  controls and field groups.
- The generic request builder renders segmented controls and grouped fields from
  that metadata instead of branching on an operation name.
- The Target evidence report source still shows review-target chips, a visible
  Topic field for `rs429358`, and collapsed Source limits.
- Inspector-level `Use in chat` / `Draft question` actions are suppressed when a
  request builder exists, so only the builder's param-aware actions remain.
- The server prepare endpoint filters submitted params to known request fields
  before rendering chat prompt or selected evidence material.

Screenshot:

- `screenshots/20260703-genomi-declarative-source-builder-viewport.png`

Verification:

- Browser check against `http://127.0.0.1:8835/` confirmed the curated source
  list has 8 user-facing source choices and no library-readiness card.
- Selecting Target evidence report confirmed hidden `target_type`, visible
  review-target chips, collapsed Source limits, no inspector-level empty-param
  actions, and builder actions `Use in chat`, `Draft question`, `Ask with
  source`.
- Posting a prepared source handoff with an injected unsupported
  `internal_leak` param returned only `target_type` and `topic`; the unsupported
  key did not appear in params, prompt, or selected evidence nodes.
- `node --check src/genomi/interfaces/templates/portal_tool_request_builder.js src/genomi/interfaces/templates/portal_tool_request_model.js src/genomi/interfaces/templates/portal_tool_catalog.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_tool_catalog tests.test_portal_frontend_assets tests.test_portal_frontend_prompt_context tests.test_mcp_http`
- `PYTHONPATH=src pytest tests/test_portal_*.py tests/test_mcp_http.py -q`

## Artifact And Evidence Report Context Handoff

Feature-alignment slice focused on making visual evidence/report selections
return to the conversation instead of leaving the user stranded in an artifact
or detail pane.

Reference-workspace observation:

- The reference science workspace keeps generated work, files, artifacts, and
  task steps as clickable workspace objects beside the conversation. The
  important pattern is not a user-managed "packet" builder; it is a visible
  research object that can be brought back into the next assistant turn while
  the workspace history remains available.
- The comparable reference checkpoint is
  `screenshots/20260703-reference-workspace-context-handoff-pattern.png`.

Implementation notes:

- `createPromptContextController.add`, `askWith`, and `draftWith` now return
  the attached context item, or `null` when the value is not attachable.
- The portal-level `Use`, `Ask`, and `Draft` context handoff paths switch the
  visible workspace back to `Research workspace` after a successful attach.
- The browser route can remain on the artifact URL for orientation, but the
  active workspace surface returns to the composer and shows the attached
  material tray. The explicit composer attachment remains the authoritative
  evidence handoff.
- The attached card uses end-user evidence language such as `Evidence report:
  rs429358`, `Evidence`, `Target evidence report`, `selected evidence items`,
  `Ask about evidence`, and `Draft from evidence`. It does not expose packet
  assembly, route ids, raw operation ids, or local paths in the normal surface.

Screenshot:

- `screenshots/20260703-genomi-context-handoff-composer.png`

Live verification:

- Started a fresh local portal at `http://127.0.0.1:8836/`.
- Rendered an evidence report through
  `POST /api/projects/proj_2e26864b4868/artifacts/render` with renderer
  `evidence_packet`, target type `topic`, topic `rs429358`, and limit `3`.
- Opened
  `http://127.0.0.1:8836/projects/proj_2e26864b4868/artifacts/art_c1bdc69576d2`.
- Clicked `data-testid="genomi-artifact-use-selection"`.
- Browser DOM check confirmed:
  - active workspace section: `Research workspace`
  - composer context tray visible
  - prompt focused
  - one prompt-context card attached
  - the card text included `Evidence report: rs429358`,
    `7 selected evidence items`, `Ask about evidence`, and
    `Draft from evidence`.

Verification:

- `node --check src/genomi/interfaces/templates/portal.js src/genomi/interfaces/templates/portal_prompt_context.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_prompt_context tests.test_portal_frontend_assets tests.test_portal_frontend_evidence_ledger_selection tests.test_portal_frontend_result_presentations`

## Attached-Material Copy Cleanup

Follow-up UX-alignment slice from the independent subagent pass. The pass
flagged that several visible surfaces still said `context`, `context card`,
`Selected context`, or `next question`, which made a user-facing research
handoff feel like packet mechanics.

Implementation notes:

- Composer handoff copy now says `Attached material` and `attached item(s)`.
- Submitted user turns now show `Attached material sent with this turn`.
- Fallback selected-material prompts now say `Use the attached material...`
  instead of `Use the selected context...`.
- Evidence-source empty and builder copy now uses chat language:
  `Choose an evidence source to use in chat` and
  `Fill any known inputs, then ask with this source in chat`.
- Workspace files no longer mention assistant runs or snapshots in the empty
  state.
- Genome privacy rows translate registry/source codes into user-facing session
  approval states: `Approved for this session`,
  `Approval required before use`, and `Approval required before reuse`.

Screenshots:

- `screenshots/20260703-genomi-attached-material-copy-cleanup.png`
- `screenshots/20260703-reference-attached-material-copy-check.png`

Live verification:

- Started a fresh Genomi portal at `http://127.0.0.1:8840/`.
- Initial workspace showed the cleaned workspace-file empty state and no
  visible `Context for next message` or `next question` copy.
- Evidence sources pane showed no visible `Prepare` or `next question` copy.
- Rendered `Evidence report: rs429358` as artifact
  `art_2e57818e3e11`, clicked `Use report`, and verified:
  - active workspace section: `Research workspace`
  - prompt focused
  - tray text: `ATTACHED MATERIAL` and `1 ATTACHED ITEM`
  - the card still exposed `Evidence report: rs429358`,
    `Ask about evidence`, and `Draft from evidence`
  - no `Context for next message` or `context card` copy was visible.
- Reference workspace at
  `http://localhost:8765/projects/proj_65ee842cd510/frames/991ad887-1322-458d-9f87-91201044b16f`
  still showed the target pattern: notebook conversation plus clickable work
  steps, files/artifacts, and generated workspace objects.

Verification:

- `node --check src/genomi/interfaces/templates/portal.js && node --check src/genomi/interfaces/templates/portal_prompt_context.js && node --check src/genomi/interfaces/templates/portal_messages.js && node --check src/genomi/interfaces/templates/portal_tool_catalog.js && node --check src/genomi/interfaces/templates/portal_tool_request_builder.js && node --check src/genomi/interfaces/templates/portal_genome_context.js && node --check src/genomi/interfaces/templates/portal_workspace_files.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_prompt_context tests.test_portal_frontend_assets tests.test_portal_selected_context_catalog`

## Source-Limits Panel Cleanup

Follow-up from live artifact verification. The evidence-report artifact detail
API already carried a source/environment snapshot, but the portal hid the
`Source limits` tab whenever version history was loaded and the version summary
did not repeat that snapshot. The panel also re-formatted useful source
summaries as object-count text such as `4 fields` and `0 fields`.

Implementation notes:

- The environment model now falls back to the artifact detail's source snapshot
  when no explicit older version is selected.
- Explicit selected versions remain exact: unresolved or missing selected
  versions do not borrow the latest artifact-level snapshot.
- The visible panel keeps source-facing metrics first:
  `Source status`, `Sources`, `Missing sources`, `Manual sources`, and
  `Defaults`.
- Source cards preserve their human summaries, for example what each consulted
  source is best for, instead of showing raw object field counts.
- Negative-inference policy now renders as `Not allowed from consulted sources`
  when the envelope says `allowed: false`.
- `Artifact context` became `Result context`, and `Manual-source required`
  became `Requires manual setup`; Python/package/runtime details remain in the
  secondary technical panel.

Screenshot:

- `screenshots/20260703-genomi-source-limits-panel-cleaned.png`

Live verification:

- Reused the local Genomi portal at `http://127.0.0.1:8841/`.
- Opened
  `http://127.0.0.1:8841/projects/proj_5f0bbacb8cdb/artifacts/art_3b6f704f4c0f?artifact_tab=environment`.
- Browser DOM check confirmed:
  - `data-testid="genomi-provenance-tab-environment"` was present
  - `data-testid="genomi-artifact-environment"` was visible
  - active tab text was `Source limits`
  - no `4 fields`, `0 fields`, or `Manual-source` wording was visible
  - the panel showed source summaries, `Not allowed from consulted sources`,
    `GRCh38`, and `Result context`.

Verification:

- `node --check src/genomi/interfaces/templates/portal_artifact_environment_model.js src/genomi/interfaces/templates/portal_artifact_runtime_model.js src/genomi/interfaces/templates/portal_artifact_view_model.js src/genomi/interfaces/templates/portal_artifacts.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_artifact_models tests.test_portal_frontend_artifact_selection tests.test_portal_frontend_assets`
- `git diff --check`

## Work-Trail Navigation And Stale Genome Replay Cleanup

Follow-up visual inspection on July 4, 2026 found two remaining UX leaks:
older genome-only host-control turns still replayed as `Genome ready`, and
run-package work steps could show generic execution cells without an obvious
way back to the conversation that produced them.

Implementation notes:

- Stored genome-only turns now derive a visible label from selected genome
  facts when the saved label is generic. A replayed `Genome state: Genome
  ready` attachment with build/readiness facts renders as
  `Genome context selected: GRCh38 · query-ready genome.` instead of exposing
  the vague readiness phrase.
- Execution cells now unpack nested artifact event payloads emitted by run
  materialization and artifact rendering. Artifact cells preserve artifact id,
  project id, title, kind, status, latest version id, version count, and a
  workspace route while still keeping raw file paths out of the normal UI
  contract.
- Work-trail cards now surface object navigation when provenance is available:
  `View in chat` for frame/run-backed steps, and `Open artifact` for
  artifact-producing cells that carry an artifact workspace route.
- Artifact Work trail now scopes concrete artifact execution cells to the
  artifact being inspected. If a shared run emits multiple artifact events, the
  selected artifact keeps shared run steps and its own produced-result cell,
  but hides sibling artifact cells with different artifact or version identity.
- The current implementation still highlights the producing run rather than
  an exact execution-cell row. Exact `highlight_work_step` routing remains a
  backlog item until artifact versions persist producing tool/cell ids.

Screenshots:

- `screenshots/20260704-genomi-work-trail-links-and-genome-inventory.png`
- `screenshots/20260704-genomi-work-trail-navigation.png`

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_execution_cells.py`
- `node --check src/genomi/interfaces/templates/portal_frame_trace.js src/genomi/interfaces/templates/portal_artifact_route_model.js src/genomi/interfaces/templates/portal.js`
- `node --check src/genomi/interfaces/templates/portal_messages.js src/genomi/interfaces/templates/portal_frame_trace.js src/genomi/interfaces/templates/portal.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_execution_cells tests.test_portal_frontend_frame_trace`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_artifact_origin_trace tests.test_portal_frontend_artifact_models tests.test_portal_frontend_genome_inventory tests.test_portal_genomes`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_execution_cells tests.test_portal_frontend_frame_trace tests.test_portal_frontend_assets tests.test_portal_frontend_genome_inventory tests.test_portal_genomes`
- `node --check src/genomi/interfaces/templates/portal_artifact_origin_trace.js src/genomi/interfaces/templates/portal_frame_trace.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_artifact_origin_trace tests.test_portal_frontend_frame_trace tests.test_portal_execution_cells`

## Attached-Material Fallback Cleanup

Follow-up after the Source limits pass. A production scan still found
`Selected context` as a generic fallback in the selection inspector, prompt
context display model, prompt-context storage normalization, and server-side
conversation-history prompt section. These paths are easy to miss because they
only appear for generic or legacy selected material, but they can leak back
into visible chips or assistant prompt context.

Implementation notes:

- Generic selection inspectors now default to `Selected material` and
  `Material`.
- Loose string material now stores and renders as `Selected material`.
- The server conversation-history section now says `Attached material:` for
  prior turns instead of `Selected context:`.
- Production source scan no longer finds visible `Selected context`,
  `Context for next`, `context card`, `next question`, `Source check`, or
  `Prepare` strings in `src/genomi/interfaces`.

Screenshot:

- `screenshots/20260703-genomi-attached-material-no-context-fallback.png`

Live verification:

- Started a fresh Genomi portal at `http://127.0.0.1:8842/`.
- Rendered `Evidence report: rs429358` through the CSRF-protected artifact
  render API.
- Opened `http://127.0.0.1:8842/projects/proj_fae4e3406839`, clicked
  `Use report`, and verified:
  - the composer showed `ATTACHED MATERIAL` and `1 ATTACHED ITEM`
  - the card showed `Evidence report: rs429358`, `Ask about evidence`, and
    `Draft from evidence`
  - no visible `Selected context`, `Context for next`, `context card`,
    `next question`, `Source check`, or `Prepare` wording appeared.

Verification:

- `node --check src/genomi/interfaces/templates/portal_selection_inspector.js src/genomi/interfaces/templates/portal_prompt_context_model.js src/genomi/interfaces/templates/portal_prompt_context.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_prompt_context tests.test_portal_frontend_artifact_selection tests.test_portal_frontend_assets tests.test_portal_runs`

## Artifact Projection Source-Boundary Cleanup

The artifact panels now share one projection for selected-version and
effective-version source data. This keeps the user-facing result tabs coherent
when a route points at a selected artifact version, while still allowing
detail-hydrated artifacts to show artifact-level source-limit snapshots when
the latest version itself only has file metadata.

Implementation notes:

- Added `portal_artifact_projection.js` as the shared boundary for artifact
  display metadata plus version-owned `environment`, `review`, and
  `reproduction` sources.
- `Source limits`, `Review`, and `Rebuild recipe` panels now use the projection
  instead of carrying separate selected-version fallback logic.
- Follow-up review tightened the projection into a single panel-source policy:
  unresolved selected versions borrow no panel data; explicit selected versions
  use version-owned fields only; normal latest/detail views can fall back
  through effective version, artifact detail, then latest version.
- Source details now come from the same projected summary as the environment,
  review, and rebuild panels, so selected-version panels do not mix old
  environment snapshots with latest/artifact source coverage.
- Explicit selected versions remain exact: if the selected version is
  unresolved, panels do not borrow environment/review/rebuild data from the
  latest artifact state.
- The detail-hydrated case remains supported: a freshly rendered evidence
  report with artifact-level environment/review/rebuild data still shows the
  `Source limits` tab even though the latest version object only has file
  metadata.
- Legacy artifact summary lines are cleaned at render time, so existing
  artifacts do not show raw operation/envelope headlines like
  `research.build_target_packet: evidence_present`.
- Runtime evidence state codes render as user-facing labels such as
  `Evidence present` and `Scoped answer only`.

Reference pattern:

- Opened the local science workspace at
  `http://localhost:8765/projects/proj_65ee842cd510/frames/991ad887-1322-458d-9f87-91201044b16f`.
- The relevant reference behavior is not an onboarding or permission flow: it
  keeps generated work, files/artifacts, and provenance-like state as ordinary
  workspace objects adjacent to the conversation.
- Genomi adapts that by keeping result/source/rebuild/review tabs coherent
  behind one projection instead of exposing version-source implementation
  drift to users.

Screenshots:

- `screenshots/20260703-genomi-artifact-projection-source-limits.png`
- `screenshots/20260703-reference-workspace-artifact-provenance-alignment.png`

Live verification:

- Started a fresh Genomi portal at `http://127.0.0.1:8843/`.
- Rendered `Evidence report: rs429358` through the CSRF-protected artifact
  render API.
- Opened
  `http://127.0.0.1:8843/projects/proj_70da12beba63/artifacts/art_ba61645d60e9?artifact_tab=environment`.
- Browser DOM check confirmed:
  - active tab text included `Source limits`
  - `data-testid="genomi-artifact-environment"` was visible
  - the panel showed `Source status`, `Sources`, `Missing sources`,
    `Manual sources`, and `Defaults`
  - no visible `Source checks`, `Prepare`, `Evidence packet`,
    `Next question`, `Selected context`, `Context for next`,
    `research.build_target_packet: evidence_present`, `evidence_present`, or
    `scoped_answer_only` wording appeared in cards or the active Source limits
    panel

Verification:

- `node --check src/genomi/interfaces/templates/portal_artifact_projection.js src/genomi/interfaces/templates/portal_artifact_environment_model.js src/genomi/interfaces/templates/portal_artifact_runtime_model.js src/genomi/interfaces/templates/portal_artifact_reproduction_model.js src/genomi/interfaces/templates/portal_artifacts.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_artifact_display_copy tests.test_portal_frontend_artifact_projection tests.test_portal_frontend_artifact_models tests.test_portal_artifact_evidence_packet tests.test_portal_frontend_artifact_selection tests.test_portal_frontend_assets tests.test_portal_frontend_prompt_context tests.test_portal_runs tests.test_portal_store`
- `git diff --check`

## Evidence-Source Handoff Route And Copy Cleanup

The Evidence sources flow now sends users back to the Research composer as a
chat action instead of leaving route state in the source picker.

Implementation notes:

- Source handoff primary action copy changed from `Use source` to `Use in chat`.
  The action is about placing the selected source into the next chat turn, not
  operating a browser-side source object.
- Composer attached-material cards now count source selections as `source
  details` instead of `request details`.
- Evidence-source `Use in chat`, `Draft question`, and `Ask with source` now
  activate `#research-workspace` instead of preserving the `#tool-launcher`
  hash. Refreshing after the handoff returns to the composer rather than the
  source picker.

Reference pattern:

- Reopened the local science workspace at
  `http://localhost:8765/projects/proj_65ee842cd510/frames/991ad887-1322-458d-9f87-91201044b16f`.
- The reference workspace keeps work steps, generated files, and artifacts as
  conversation-adjacent objects. Genomi adapts that by treating a chosen
  evidence source as attached chat material, not as a persistent request/setup
  panel the user has to manage.

Screenshots:

- `screenshots/20260703-genomi-evidence-source-use-in-chat-handoff.png`
- `screenshots/20260703-reference-workspace-step-stack-source-handoff-comparison.png`

Live verification:

- Started Genomi at `http://127.0.0.1:8853/`.
- Opened Evidence sources, chose `Target evidence report`, selected `Topic`,
  entered `APOE rs429358`, and clicked `Use in chat`.
- Browser DOM check confirmed:
  - URL hash became `#research-workspace`
  - the active nav was `Research workspace` / `Research`
  - the prompt textarea was focused
  - the attached-material tray showed `Evidence source: Target evidence report`
    and `3 selected source details`
  - no visible `Source checks`, `Prepare`, `Attach source`, `request details`,
    `Selected context`, `Evidence packet`, or `Next question` wording appeared

Verification:

- `node --check src/genomi/interfaces/templates/portal.js src/genomi/interfaces/templates/portal_tool_request_builder.js src/genomi/interfaces/templates/portal_tool_catalog.js src/genomi/interfaces/templates/portal_selected_context_catalog.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_tool_catalog tests.test_portal_frontend_prompt_context tests.test_portal_frontend_assets tests.test_mcp_http`

## Saved Evidence Re-check Copy Cleanup

Persisted or display-only tool history now hands off to chat as saved evidence
that should be re-checked, not as a workflow event.

Implementation notes:

- `toolResultFollowUpRequest` now returns a selected-material packet instead
  of a bare prompt string, matching the rest of the composer attachment model.
- Display-only and persisted-redacted follow-up contexts use
  `context_kind="work_trace"` internally but visible labels say
  `Saved evidence`.
- The generated prompt begins with `Selected saved evidence to re-check` and
  avoids user-facing `workflow event` language for saved evidence.
- Generic non-evidence fallback copy now uses `Genomi work` and `Work summary`
  instead of `workflow event`, so event vocabulary stays out of normal
  user-facing chat handoff copy.
- Current attachable evidence still uses result/evidence context packets, so
  this change does not make stale persisted history look like fresh retrieved
  evidence.

Reference pattern:

- Reopened the local science workspace at
  `http://localhost:8765/projects/proj_65ee842cd510/frames/991ad887-1322-458d-9f87-91201044b16f`.
- The reference workspace keeps generated work and compact work-step groups
  revisitable beside the conversation. Genomi adapts that pattern by making
  saved history read as evidence material to re-check, while keeping event and
  persistence mechanics out of the ordinary chat handoff.

Screenshots:

- `screenshots/20260703-genomi-saved-evidence-recheck-copy-check.png`
- `screenshots/20260703-reference-workspace-saved-evidence-comparison.png`

Live verification:

- Started Genomi at `http://127.0.0.1:8857/`.
- Browser DOM check confirmed the portal title `Genomi Portal`, active CSS
  stylesheets, the Research workspace, Files & Artifacts, Current evidence, Work
  trail, Genome state, and Evidence sources surfaces.
- The reference workspace remained reachable and showed the existing
  conversation, work-step stack, generated-object surface, and composer.
- The exact persisted-history wording is model-tested rather than visually
  forced in a fresh portal session because it depends on stored display-only
  replay state.

Verification:

- `node --check src/genomi/interfaces/templates/portal_tool_result_presentation.js src/genomi/interfaces/templates/portal_evidence_ledger.js src/genomi/interfaces/templates/portal_prompt_context.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_assets tests.test_portal_frontend_evidence_ledger_selection tests.test_portal_frontend_prompt_context`

## Evidence Source Form Simplification

The Evidence sources pane now receives grouped source-form metadata from the
server for common workflows, so the browser does not have to present flat
schema-like parameter lists.

Implementation notes:

- `genomi.parse_source` keeps `Genome source` as the primary visible input and
  collapses genome build, reference FASTA, profile label, and default-profile
  choices under `Genome details`.
- `genomi.search_indexes` keeps `Search text` primary and collapses index
  source plus limit under `Source limits`.
- `variant.resolve` keeps `rsID` primary and collapses query, coordinate,
  allele, region, genome build, and approved-genome-context fields under
  `Other variant formats and source limits`.
- Target evidence report already had guided target chips and source limits; the
  new catalog metadata brings the same product rule to the other first-run
  source workflows.

Reference pattern:

- Reopened the local science workspace at
  `http://localhost:8765/projects/proj_65ee842cd510/frames/991ad887-1322-458d-9f87-91201044b16f`.
- The reference workspace keeps work steps, files, and artifacts near the
  conversation rather than making the user manage a tool schema. Genomi adapts
  that by presenting the scientific input first and leaving optional source
  mechanics behind disclosure.

Screenshots:

- `screenshots/20260703-genomi-variant-source-grouped-form-focused.png`
- `screenshots/20260703-reference-source-form-comparison.png`

Live verification:

- Started Genomi at `http://127.0.0.1:8861/`.
- Opened `Evidence sources`, selected `Variant lookup`, and captured the source
  form.
- Browser check confirmed the active source was `Variant lookup`, visible
  actions were `Use in chat`, `Draft question`, and `Ask with source`, and the
  source detail group was present but closed by default.
- The screenshot confirms the visible form leads with `rsID`; coordinate,
  region, genome build, and approved-genome-context controls are not competing
  with the primary input.

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_source_lookups.py`
- `PYTHONPATH=src python3 -m unittest tests.test_mcp_http.MCPHTTPTests.test_portal_source_lookups_endpoint_returns_curated_cards tests.test_portal_frontend_tool_catalog`

## Genome-State Chat Cleanup

The chat surface no longer displays host-agent control prompts when the only
selected material is genome readiness/privacy state. Genome state is context
for a later genetics question, not a standalone research request.

Implementation notes:

- `genome_context` selected-material cards no longer expose direct Ask or Draft
  actions in the composer tray. The user attaches genome state, then asks an
  actual genetics question.
- The message renderer maps the old leaked host prompt into `Genome state
  included. Ask a genetics question to use it.` so existing stored frames stop
  replaying internal instruction text.
- The corresponding no-question assistant response now renders as a short next
  step instead of `registered constraints` / `smallest evidence step` language.
- User-message evidence chips say `Using` and strip prefixes such as `Genome
  state:` so the chat reads like normal workspace state.
- Diagnostic-only work stacks stay available in the trace model but are hidden
  from the main chat card surface until a real tool call/result appears.

Screenshot:

- `screenshots/20260703-genomi-genome-context-chat-cleaned.png`

Live verification:

- Reloaded
  `http://127.0.0.1:8863/projects/proj_7ed74bfb6367/frames/d29cc700-e976-4757-8c50-532f175b6220`.
- Browser check confirmed the stored user bubble rendered as `Genome state
  included`, the chip rendered as `Using Genome ready`, the assistant bubble
  rendered as a next-step instruction, and the diagnostic-only work group had
  `hidden=true`.

Verification:

- `node --check src/genomi/interfaces/templates/portal_messages.js src/genomi/interfaces/templates/portal_prompt_context.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_assets.PortalFrontendAssetTests.test_message_surface_aggregates_diagnostics_as_collapsed_work_detail tests.test_portal_frontend_prompt_context`

## Starter Cards As Evidence-Source Entry Points

The first-run chat suggestions now all point at concrete workspace actions when
there is a matching Genomi source workflow. The public-evidence card no longer
drops a planning prompt into chat; it opens the `Target evidence report` source
with the topic target mode selected.

Implementation notes:

- Replaced `Plan public evidence` with `Target evidence report` in both
  welcome render paths: the static HTML and the runtime message template.
- The card carries `data-source-operation="research.build_target_packet"` and
  `data-source-params='{"target_type":"topic"}'`, matching the existing
  source-suggestion router.
- The source form keeps the Topic field visible, the target chips available,
  and Source limits collapsed. That keeps the first user action focused on the
  research target rather than a raw operation schema.
- The existing `Add a genome` and `Variant evidence` cards continue to route
  to `genomi.parse_source` and `variant.resolve`; this makes the starter row
  consistently workspace-native.

Reference pattern:

- Reopened the local science workspace at
  `http://localhost:8765/projects/proj_65ee842cd510/frames/991ad887-1322-458d-9f87-91201044b16f`.
- The reference flow starts from a research task in chat and keeps files,
  artifacts, and work adjacent. Genomi adapts that by making starter cards open
  source/workspace entries that can be used in chat, rather than emitting hidden
  host-agent instructions as user text.

Screenshots:

- `screenshots/20260703-genomi-target-evidence-starter-source-entry.png`
- `screenshots/20260703-genomi-target-evidence-starter-source-entry-full.png`
- `screenshots/20260703-reference-workspace-starter-source-entry-comparison.png`

Live verification:

- Started Genomi at `http://127.0.0.1:8863/`.
- Clicked the `Target evidence report` starter card in the live in-app browser.
- Browser check confirmed:
  - URL hash became `#tool-launcher`
  - `target_type` was prefilled as `topic`
  - the Topic input existed and was visible
  - Source limits remained closed
  - visible actions were `Use in chat`, `Draft question`, and `Ask with source`

Verification:

- `node --check src/genomi/interfaces/templates/portal_messages.js src/genomi/interfaces/templates/portal.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_assets.PortalFrontendAssetTests.test_live_result_actions_can_submit_selected_context tests.test_portal_frontend_tool_catalog`

## Genome-State Regression Fixture After Starter Refactor

After the starter-card source routing was moved into a server-owned model, the
genome-state-only chat regression was rechecked with a fresh live fixture. The
fixture intentionally stored the old hidden genome-state instruction, the old
no-question assistant reply, and diagnostic-only host-agent events.

Implementation notes:

- Starter cards are now generated from `portal_starter_cards.py` and injected
  into both initial HTML and runtime message reset. This removes duplicate
  hard-coded starter markup from the browser message module.
- Source-backed starter cards now fail visibly as `Evidence source unavailable`
  instead of silently dropping their prompt fallback into chat. Prompt fallback
  remains for genuinely prompt-only starters.
- Generic selected-context wording now uses `included evidence` rather than
  `attached material`; exported bridge status uses `ready` rather than runtime
  words such as `runnable`.
- The live fixture still rewrites old stored host prompts into product copy:
  `Genome state included. Ask a genetics question to use it.` and `Genome state
  is ready...`.

Screenshot:

- `screenshots/20260703-genomi-genome-context-cleaned-live.png`

Live verification:

- Started Genomi at `http://127.0.0.1:8863/`.
- Seeded a local project/frame with the old leaked genome-state prompt,
  diagnostic-only tool messages, and the old no-question assistant text.
- Browser check confirmed:
  - no visible `Attached material`
  - no visible `runnable`
  - no visible leaked genome-state instruction
  - no visible `registered constraints` assistant text
  - one diagnostic-only work stack existed but was hidden
  - zero visible work stacks remained in the main chat

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_starter_cards.py src/genomi/interfaces/portal_assets.py src/genomi/interfaces/portal_selected_context_catalog.py src/genomi/interfaces/portal_turns.py src/genomi/interfaces/portal_store.py`
- `node --check src/genomi/interfaces/templates/portal.js src/genomi/interfaces/templates/portal_messages.js src/genomi/interfaces/templates/portal_starter_cards.js src/genomi/interfaces/templates/portal_tool_request_builder.js src/genomi/interfaces/templates/portal_prompt_context.js src/genomi/interfaces/templates/portal_selected_evidence.js src/genomi/interfaces/templates/portal_selected_context_catalog.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_assets tests.test_portal_frontend_prompt_context`
- `PYTHONPATH=src python3 -m unittest tests.test_mcp_http tests.test_portal_runs`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_selected_context_catalog tests.test_portal_frontend_tool_catalog tests.test_portal_frontend_artifact_selection`

## Conversation Rail Display Request

The genome-state cleanup needed to reach the conversation rail too. The stored
frame request remains the original host-agent input, but public frame summaries
now include a display-only title field so the rail can render the user's
research object instead of hidden control text.

Implementation notes:

- Added `portal_turns.display_request_text(...)` for request-to-title
  projection.
- `portal_store.public_frame(...)` and project frame listings now include
  `display_request`.
- The browser frame list prefers `display_request` while keeping `request` as
  a fallback.
- The rule is intentionally narrow: a genome-context-only hidden prompt with a
  genome-context packet displays as `Genome state included`; ordinary requests
  still display their prompt-safe text.

Screenshot:

- `screenshots/20260703-genomi-conversation-rail-display-request.png`

Live verification:

- Restarted Genomi at `http://127.0.0.1:8863/`.
- Reloaded the genome-state regression fixture frame.
- API check confirmed the frame still returned the raw `request` and also
  returned `display_request: "Genome state included"`.
- Browser check confirmed the Conversations rail title was `Genome state
  included`, with no visible leaked genome-boundary instruction.

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_turns.py src/genomi/interfaces/portal_store.py`
- `node --check src/genomi/interfaces/templates/portal.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_store.PortalStoreTests.test_public_frame_summary_redacts_request_paths tests.test_portal_store.PortalStoreTests.test_public_frame_summary_projects_genome_context_only_request tests.test_portal_frontend_assets.PortalFrontendAssetTests.test_live_result_actions_can_submit_selected_context tests.test_mcp_http.MCPHTTPTests.test_project_request_creates_persistent_frame_messages`

## Public Claude Science Product Page And Research-Record Feedback

The public Claude Science page was inspected for capability framing and visual
patterns. The in-app browser captured the hero before the browser automation
backend became unavailable; the user then supplied the missing product-section
captures for rich artifacts, compute, and domain-ready tooling.

Reference observations:

- The product promise is a research partner that runs analyses, searches
  scientific databases, and traces every step from data wrangling through
  publication.
- The rich-artifact section makes artifact history the main UX pattern:
  Code, Execution Log, Messages, Environment, and Review sit beside the
  generated figure/table/notebook.
- The compute section treats environments, remote jobs, notebooks, persistent
  Python/R kernels, and output figures as one visible research run.
- The domain-ready section presents tools/skills/databases, reviewer findings,
  rendered PDFs, and literature retrieval as ordinary science workspace
  objects rather than backend operations.
- User feedback emphasized that Markdown files, images, code, all artifacts,
  reviewer checks, and detailed skill/tool definitions are directly openable
  and useful as a durable lab record for later manuscript and experiment review.

Screenshots:

- `screenshots/20260703-claude-science-public-hero-clean.png`
- `screenshots/20260703-claude-science-public-rich-artifacts-user-supplied.png`
- `screenshots/20260703-claude-science-public-compute-user-supplied.png`
- `screenshots/20260703-claude-science-public-domain-ready-user-supplied.png`

Genomi adaptation in this slice:

- Workspace files are now classified as Markdown, Code, Image, Table, Data,
  Text, or File.
- File rows use the product action `Open` instead of `Preview file`.
- The opened file panel labels files as `Research record` and gives Markdown,
  code, table/data, and images type-specific visual treatment.
- Genome-context-only selected material no longer auto-submits an empty
  host-agent turn; the composer focuses and waits for a real genetics question.

## Active Genome As A User-Visible Research Object

User feedback on the portal header made clear that `Genome ready` is not useful
product information. The active genome should be visible as the current
research object, with enough safe metadata for the user to decide whether to
keep using it, switch it, or add a new source.

Implementation notes:

- `/api/context` now exposes safe active-genome identity fields:
  `display_name`, `sample_slug`, `agi_id`, source format/type/provider,
  genome build, readiness, and registry counts. It still does not expose raw
  local source paths or AGI file paths.
- The frontend genome model now titles a ready genome with identity, build,
  source type, and readiness, for example `GRCh38 · VCF · query-ready genome`,
  instead of `Genome ready`.
- The topbar genome pill is now a button that opens the Genome pane and shows a
  secondary detail line. Its label prefers the active row from the safe genome
  inventory, so generic context titles such as `Genome ready` cannot override
  the actual active genome identity.
- The Genome pane is labeled `Active genome` and exposes `Add genome` and
  `Switch genome` controls. `Add genome` opens the existing Add Genome File
  source workflow. `Switch genome` focuses the in-pane genome inventory.
- `/api/genomes` now returns a safe genome inventory for the portal: active
  identity, profile links, build/source/readiness, and counts. It strips raw
  local source references and AGI paths from the normal UI contract.
- `/api/genomes/select` routes a row selection through the existing AGI
  lifecycle operations. A row with an AGI id activates that exact genome for
  the session; profile information is preserved as selection context instead
  of replacing the selected genome.
- The inventory renders each known genome with `Use this genome` on inactive
  rows and an `Active` state on the selected row. Inventory failures render
  `Genome list unavailable` rather than pretending there are no genomes.
- The header model now rejects generic active-genome labels such as
  `Genome ready` even when they arrive through the safe genome inventory. A
  real display name wins; otherwise the header falls back to build, source
  type, readiness, or the short AGI id. If the inventory has not loaded yet
  but `/api/context` has safe identity fields, the topbar reconstructs the
  active-genome title from that context instead of showing a readiness slogan.
- The normal UI now uses `Active genome` for this object. The underlying typed
  handoff remains `genome_context`, but composer cards, operation labels,
  evidence badges, and result panels no longer expose `Genome state` as the
  default vocabulary.
- Genome-only hidden host-control turns now render as
  `Active genome selected: <active genome>.` rather than a generic readiness
  statement.

Screenshot:

- `screenshots/20260703-genomi-active-genome-inventory.png`
- `screenshots/20260704-genomi-active-genome-pane.png`

Verification:

- `node --check src/genomi/interfaces/templates/portal_genome_context.js src/genomi/interfaces/templates/portal_messages.js src/genomi/interfaces/templates/portal.js`
- `python3 -m py_compile src/genomi/interfaces/portal_context.py`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_context tests.test_portal_frontend_prompt_context tests.test_portal_store.PortalStoreTests.test_public_frame_summary_projects_genome_context_only_request`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_assets`
- `node --check src/genomi/interfaces/templates/portal_genome_inventory.js src/genomi/interfaces/templates/portal_api.js src/genomi/interfaces/templates/portal.js`
- `python3 -m py_compile src/genomi/interfaces/portal_genomes.py src/genomi/interfaces/portal.py`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_genomes tests.test_portal_frontend_genome_inventory tests.test_portal_frontend_assets tests.test_portal_context tests.test_mcp_http.MCPHTTPTests.test_root_endpoint_serves_portal_workspace tests.test_mcp_http.MCPHTTPTests.test_portal_static_app_assets tests.test_mcp_http.MCPHTTPTests.test_portal_genome_inventory_api_lists_and_selects_genomes`
- `git diff --check`

## Work Trail Exact Step Focus

Follow-up UX comparison work kept pointing at the same artifact provenance
gap: `View in chat` should not strand the user at an approximate run-level
position when the portal already has a concrete Work trail card for the
producing execution cell.

Implementation notes:

- Frame routes now accept hidden `highlight_step` query state alongside
  `highlight_run`. The route parser keeps both values typed, but neither value
  is rendered as visible product copy.
- Work trail execution-cell links include `highlight_step=<cell id>` when a
  computed execution cell has a stable id. Opening that route activates the
  Work trail pane, scrolls to the matching card, and applies a subtle highlight.
- The Work trace controller preserves the requested step focus while async run
  result packages hydrate execution cells, so the card can be highlighted after
  it arrives.
- The capability backlog is still conservative: this closes computed Work
  trail card focus, not full numbered Execution Log parity. Persisted
  version-owned execution-cell records remain future work.

Verification:

- `node --check src/genomi/interfaces/templates/portal_artifact_route_model.js`
- `node --check src/genomi/interfaces/templates/portal_frame_trace.js`
- `node --check src/genomi/interfaces/templates/portal_work_trace_controller.js && node --check src/genomi/interfaces/templates/portal.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_routes tests.test_portal_frontend_frame_trace`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_artifact_origin_trace tests.test_portal_frontend_artifact_models tests.test_portal_frontend_assets`

## Current Evidence Scope Refinement

The UX comparison sidecar flagged `Current evidence` as a risk: it can feel
like a durable project evidence map even when the implementation is the active
conversation's replayed evidence ledger.

Implementation notes:

- The ledger already rebuilds from stored frame tool messages when a
  conversation is reopened. This slice makes that contract visible in the
  normal UI instead of relying on implicit replay behavior.
- The ledger toolbar now names the active conversation and summarizes whether
  evidence results were restored from saved work history or are live in the
  current browser session.
- Empty ledger copy now says that saved conversation work history will restore
  evidence when the conversation is reopened.
- This is still not the full durable evidence-map backend described in the
  backlog; it is an honest scoped conversation evidence surface.

Verification:

- `node --check src/genomi/interfaces/templates/portal_evidence_ledger.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_evidence_ledger_selection`

## Evidence Source Attach Contract Cleanup

Follow-up implementation for the same UX issue: the normal portal surface had
cleaner copy, but the browser/server contract and asset names still preserved
the older source-check/preparation mental model.

Implementation notes:

- The source handoff endpoint is now `/api/evidence-sources/attach` instead of
  `/api/source-checks/prepare`.
- The browser API/helper names now read as evidence-source attach operations
  rather than source-check preparation.
- The focused stylesheet is now `portal_evidence_sources.css`.
- The selected-material copy catalog uses `sourceRequest` and
  `isSelectedContextEvidenceSource`, keeping old source-check terminology out
  of generated frontend copy.

Verification:

- `node --check src/genomi/interfaces/templates/portal_api.js src/genomi/interfaces/templates/portal.js src/genomi/interfaces/templates/portal_tool_catalog.js src/genomi/interfaces/templates/portal_tool_request_model.js src/genomi/interfaces/templates/portal_prompt_context_model.js src/genomi/interfaces/templates/portal_selected_context_catalog.js`
- `python3 -m py_compile src/genomi/interfaces/portal.py src/genomi/interfaces/portal_source_lookups.py src/genomi/interfaces/portal_selected_context_catalog.py`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_assets tests.test_portal_frontend_tool_catalog tests.test_mcp_http.MCPHTTPTests.test_portal_source_lookups_endpoint_returns_curated_cards tests.test_mcp_http.MCPHTTPTests.test_portal_evidence_source_attach_endpoint_owns_chat_handoff tests.test_mcp_http.MCPHTTPTests.test_portal_evidence_source_attach_reports_missing_condition_inputs`

## Generated Output Library Grouping

Claude Science's Library keeps generated artifacts near the session or work
that produced them. Genomi already had inline run-scoped artifact strips and
global Library groups for uploads, produced files, and generated outputs; this
slice makes the global Library preserve assistant-turn grouping when the
artifact summary has public producing-run metadata.

Implementation notes:

- Generated non-file artifacts now group as `Generated from assistant turn`
  when they share a producing run.
- Multiple producing turns render as `Generated from assistant turn 1`,
  `Generated from assistant turn 2`, etc. Raw run ids are used only as grouping
  keys in the model and are not shown as labels.
- Generated artifacts without producing-run metadata remain in the fallback
  `Generated artifacts` group so the UI does not overclaim provenance.
- Uploads, produced files, hidden items, filters, search, and layout behavior
  are unchanged.

Verification:

- `node --check src/genomi/interfaces/templates/portal_artifact_library_model.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_artifact_library tests.test_portal_frontend_artifact_models tests.test_portal_frontend_assets`

## Markdown Research Record Rendering

The Claude Science product/feedback emphasis on Markdown files opening directly
as complete records exposed a Genomi gap: workspace Markdown previews were
classified as Markdown but still rendered as raw preformatted text.

Implementation notes:

- Workspace-file previews now render Markdown text as a readable research
  record with headings, paragraphs, lists, blockquotes, inline code, safe links,
  and fenced code blocks.
- The renderer builds DOM nodes with `textContent` and constrained link hrefs;
  it does not inject raw Markdown HTML.
- Code, image, and plain-text preview paths are unchanged.
- CSV/TSV table previews are the next local parity target because Claude
  Science treats tables as native scientific artifacts rather than attachments.
- PDF/notebook navigation and richer Library grouping remain backlog items.

Verification:

- `node --check src/genomi/interfaces/templates/portal_workspace_files.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_workspace_files`

## Table Research Record Rendering

The same Library feedback applies to CSV/TSV outputs: a user should be able to
open a generated results table beside the conversation and inspect it as a
research record, not as an undifferentiated text blob.

Implementation notes:

- Workspace-file previews now render CSV/TSV files as native tables with a
  compact row/column summary.
- The parser handles quoted CSV fields and escaped quotes, builds DOM nodes with
  `textContent`, and caps the first preview to 50 rows and 16 columns.
- This is intentionally a preview surface. Rich sorting, filtering, notebooks,
  PDFs, and folder/session-level Library grouping remain backlog items.

Verification:

- `node --check src/genomi/interfaces/templates/portal_workspace_files.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_workspace_files`

## Version-Scoped Rebuild Script Bundles

The Claude Science comparison and UX sidecar both pointed at reproducible
artifact code as a major remaining workspace gap. Genomi already had a
version-owned `Rebuild recipe` tab for portal-owned evidence reports; this
slice turns ready public recipes into a local downloadable artifact object.

Implementation notes:

- Added `/api/projects/:project_id/artifacts/:artifact_id/script-bundle` for
  the latest version and
  `/api/projects/:project_id/artifacts/:artifact_id/versions/:version_id/script-bundle`
  for exact version-scoped downloads.
- Script bundles are ZIP files containing `rebuild.sh`,
  `rebuild-recipe.json`, `manifest.json`, and `README.md`.
- The frontend action menu shows `Download rebuild script` only when
  `artifactReproductionModel` sees a ready public recipe. If private parameters
  were redacted, no script download action appears.
- This is still not full Claude Science Code parity: dependency input chips,
  complete dependency graphs, exact host-agent replay, and support across every
  artifact kind remain future work.

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_artifact_bundles.py src/genomi/interfaces/portal.py src/genomi/runtime/portal_routes.py`
- `node --check src/genomi/interfaces/templates/portal_api.js src/genomi/interfaces/templates/portal_artifact_actions.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_artifact_bundles tests.test_portal_frontend_artifact_library tests.test_mcp_http.MCPHTTPTests.test_project_artifact_render_route_persists_evidence_packet_artifact`

## Version-Scoped Review Run History

The reference workspace treats Review as a first-class artifact state. Genomi
already persisted deterministic Review checks on artifact versions, but the
Review tab still behaved like static metadata. This slice makes Review an
artifact-local action and history while keeping the Genomi boundary explicit:
these are deterministic artifact/evidence-boundary checks, not clinical
validation and not an autonomous reviewer-agent lifecycle.

Implementation notes:

- Added version-scoped review-run endpoints:
  `/api/projects/:project_id/artifacts/:artifact_id/review-runs` for the latest
  version and
  `/api/projects/:project_id/artifacts/:artifact_id/versions/:version_id/review-runs`
  for exact version review.
- `portal_store.run_project_artifact_version_review` re-evaluates the stored
  deterministic review from persisted artifact/version state, updates the
  version's Review state, appends a bounded completed review-run history entry,
  and emits the normal artifact-change project event.
- Artifact version detail now exposes `review.review_runs`; the frontend Review
  model renders that as `Check run history` without showing raw review-run ids
  in the selectable normal UI.
- The artifact action menu shows `Run review checks` when the inspected artifact
  version has review state and the portal can call the review-run endpoint.
- Async/running review jobs, reviewer-agent findings, renderer validation, and
  richer missing-library checks remain future work.

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_artifact_review.py src/genomi/interfaces/portal_artifact_presenters.py src/genomi/interfaces/portal_store.py src/genomi/interfaces/portal.py src/genomi/runtime/portal_routes.py tests/test_portal_store.py tests/test_mcp_http.py tests/test_portal_artifact_evidence_packet.py`
- `node --check src/genomi/interfaces/templates/portal_api.js && node --check src/genomi/interfaces/templates/portal_artifact_runtime_model.js && node --check src/genomi/interfaces/templates/portal_artifact_actions.js && node --check src/genomi/interfaces/templates/portal.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_store.PortalStoreTests.test_artifact_version_review_run_appends_public_check_history tests.test_portal_frontend_artifact_library.PortalFrontendArtifactLibraryTests.test_artifact_action_menu_model_exposes_object_actions`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_artifact_evidence_packet.PortalArtifactEvidencePacketTests.test_evidence_packet_artifact_reuses_target_packet_model_with_neutral_review_brief`
- `PYTHONPATH=src python3 -m unittest tests.test_mcp_http.MCPHTTPTests.test_project_artifact_render_route_persists_evidence_packet_artifact`

## PDF And Notebook Workspace Records

The reference workspace and user feedback both emphasized that research files
should open directly beside the conversation. Genomi already had Markdown,
table, code, image, and text previews; this slice adds bounded PDF and notebook
inspection without claiming full notebook execution or provenance parity.

Implementation notes:

- Workspace PDF files now preview as `PDF document` research records. The
  preview payload exposes a project-scoped document URL, and the raw bytes are
  served only through `/api/projects/:project_id/workspace/file?path=...` for
  supported document previews inside the project boundary.
- The document endpoint refuses arbitrary workspace file types, path escapes,
  missing projects, and oversized documents. It is a narrow preview stream, not
  a general file-content API.
- Workspace `.ipynb` files now preview as `Notebook` research records with a
  bounded cell outline: summary, language, code/markdown counts, line counts,
  output counts, and sanitized cell source snippets.
- The frontend renders PDFs in a document frame and notebooks as inspectable
  cell cards. It does not expose raw notebook JSON, local filesystem roots,
  context packets, or operation ids.
- Full notebook kernel execution, execution-cell provenance, PDF annotation or
  search, and richer Library/session grouping remain backlog items.

Visual verification:

- `screenshots/20260704-genomi-workspace-pdf-preview.png` captures a project
  PDF opened as `PDF document · Research record` with a project-scoped document
  frame.
- `screenshots/20260704-genomi-workspace-notebook-preview.png` captures an
  `.ipynb` opened as `Notebook · Research record` with markdown/code cell
  cards, line counts, and output count.

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_workspace_files.py src/genomi/interfaces/portal.py tests/test_portal_workspace_files.py tests/test_mcp_http.py tests/test_portal_frontend_workspace_files.py`
- `node --check src/genomi/interfaces/templates/portal_workspace_files.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_workspace_files tests.test_portal_frontend_workspace_files`
- `PYTHONPATH=src python3 -m unittest tests.test_mcp_http.MCPHTTPTests.test_project_workspace_file_preview_endpoint_returns_bounded_preview tests.test_mcp_http.MCPHTTPTests.test_project_workspace_document_endpoint_streams_pdf_inside_project_boundary`

## Workspace File Grouping And Preview Renderer Split

The next UX comparison pass identified provenance/work-step persistence as the
largest product gap after richer file previews. The maintainability review also
flagged workspace-file previews as a local growth risk: list state, preview
request state, Markdown rendering, CSV parsing, PDF frames, and notebook cells
were accumulating in one browser controller.

Implementation notes:

- The workspace file browser now groups visible files by project-relative
  folder. This keeps papers, analyses, reports, and root-level files readable
  as a lightweight Project Library step without exposing backend workspace
  roots.
- Search narrows both files and folder groups, so matched records remain in
  their project folder context.
- Type-specific preview renderers moved from `portal_workspace_files.js` into
  `portal_workspace_file_previews.js`. The controller now owns list/search,
  folder grouping, preview request state, and row actions; the renderer module
  owns Markdown, table, image, PDF document, notebook, and fallback preview DOM.
- This is not the full Library grouping gap. Generated-session grouping,
  long-running import lifecycle, cloud export state, PDF annotation/search, and
  full notebook execution/history remain future work.

Visual verification:

- `screenshots/20260704-genomi-workspace-file-folder-groups.png` captures the
  workspace Files surface grouped into `analysis` and `papers` project-folder
  sections.

Verification:

- `node --check src/genomi/interfaces/templates/portal_workspace_files.js && node --check src/genomi/interfaces/templates/portal_workspace_file_previews.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_workspace_files tests.test_portal_frontend_assets`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_workspace_files tests.test_mcp_http.MCPHTTPTests.test_project_workspace_file_preview_endpoint_returns_bounded_preview tests.test_mcp_http.MCPHTTPTests.test_project_workspace_document_endpoint_streams_pdf_inside_project_boundary`

## Active Genome Header Runtime Check

User feedback on the live workspace caught a stale header showing only a
readiness phrase. The accepted product shape is the active genome as a visible
research object, with direct controls to inspect/switch the current genome and
add another genome source.

Runtime check:

- Reloaded `http://127.0.0.1:8863/projects/proj_7ed74bfb6367/frames/d29cc700-e976-4757-8c50-532f175b6220`.
- The current header rendered `Active genome: genome computer`.
- The detail line rendered safe context: `GRCh38`, genome-source kind,
  query-readiness, profile label, and known-genome count.
- `Switch` and `Add` were visible header actions.
- The topbar did not contain the old generic readiness label.

Visual verification:

- `screenshots/20260704-genomi-active-genome-identity-switch-add.png`

## Files And Artifacts Vocabulary Alignment

The reference Library pattern is a research-object surface, not a generic
result bucket. Genomi had already implemented much of the file/artifact
behavior, but several visible labels still used generic results/output
vocabulary instead of naming files and artifacts directly.

Implementation notes:

- The project pane is now labeled `Files & Artifacts`.
- Empty and no-match states speak in files, artifacts, and library items.
- Generated groups are artifacts created in assistant turns rather than
  outputs.
- Workspace-file rows say `Linked artifact` and `Open artifact`.
- Artifact preview, action titles, review-summary payloads, and origin work
  trail copy use artifact vocabulary instead of result/output vocabulary.

Visual verification:

- `screenshots/20260704-genomi-files-artifacts-library-copy.png`

Verification:

- `node --check src/genomi/interfaces/templates/portal.js src/genomi/interfaces/templates/portal_artifact_preview.js src/genomi/interfaces/templates/portal_artifacts.js src/genomi/interfaces/templates/portal_artifact_library_model.js src/genomi/interfaces/templates/portal_workspace_files.js src/genomi/interfaces/templates/portal_artifact_actions.js src/genomi/interfaces/templates/portal_artifact_display_model.js src/genomi/interfaces/templates/portal_artifact_runtime_model.js src/genomi/interfaces/templates/portal_artifact_origin_trace.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_artifact_library tests.test_portal_frontend_workspace_files tests.test_portal_frontend_assets tests.test_portal_artifact_evidence_packet tests.test_portal_frontend_artifact_models tests.test_portal_frontend_artifact_origin_trace`

## Library Review Status Checkpoint

The reference artifact model makes review state visible as part of the artifact
object. Genomi already had artifact-version review checks and a Review tab, but
the Library list endpoint returned only a lightweight version summary. That made
the Library card unable to show current review state until the artifact detail
was opened.

Implementation notes:

- Public artifact summaries now include the latest artifact-version review state.
- The Library card renders a compact `Review passed`, `Review warnings`, or
  `Review failed` badge when that current review state exists.
- The badge is a user-facing artifact state, not a transport packet, route id,
  or debug check payload.
- The focused backend regression covers the exact contract: after
  `POST /api/projects/:project_id/artifacts/:artifact_id/review-runs`,
  `GET /api/projects/:project_id/artifacts` must include the current
  `artifact.review.status`.

Visual verification:

- `screenshots/20260704-genomi-artifact-review-status-card.png`

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_artifact_presenters.py`
- `node --check src/genomi/interfaces/templates/portal_artifacts.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_artifact_routes.PortalArtifactRouteTests.test_project_artifact_review_run_surfaces_current_review_in_artifact_list tests.test_portal_frontend_artifact_library.PortalFrontendArtifactLibraryTests.test_artifact_library_card_surfaces_review_status`

Remaining comparison gap:

- The next product gap is richer execution-cell provenance, not the basic
  produced-artifact work-step record. Genomi should still keep calling the
  surface `Work trail`, not `Execution Log`, until command source,
  stdout/stderr panes, environment labels, and normalized execution-cell records
  exist.

## Artifact Producing Work-Step Checkpoint

The reference artifact pattern makes every artifact answer the question "what
produced this?" from the artifact view itself. Genomi should expose that as a
user-facing work step, not as a context packet, operation schema, or generic log.

Implementation notes:

- Artifact versions now persist a bounded `artifact_producing_work_step` record
  when a portal run creates a file-backed artifact.
- The public artifact summary/detail/version surfaces expose only the safe
  work-step fields: title, status, artifact identity, source label, origin
  frame/run/message ids, and workspace route.
- The artifact Work trail tab prepends this version-owned `Produced artifact`
  step before any computed run-package diagnostics.
- The UI label stays `Work trail`; Genomi still does not claim a full execution
  log until normalized execution-cell records back that surface.

Visual verification:

- `screenshots/20260704-genomi-artifact-producing-work-step-focused.png`
- `screenshots/20260704-genomi-artifact-producing-work-step-full.png`

Runtime check:

- Opened `http://127.0.0.1:8873/projects/proj_5db8c9098f55/artifacts/art_1d659de1cc48/versions/ver_76d5fcf0dcab?artifact_tab=trace&assetBust=producing-step-20260704`.
- The topbar rendered the active genome identity with `Switch` and `Add`.
- The artifact Work trail tab rendered `Work that produced this artifact`, one
  step, and `Produced artifact` with `APOE evidence ready`.
- Browser console warnings/errors were empty.

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_artifact_work_steps.py src/genomi/interfaces/portal_artifact_versions.py src/genomi/interfaces/portal_store.py src/genomi/interfaces/portal_artifact_presenters.py`
- `node --check src/genomi/interfaces/templates/portal_artifact_origin_trace.js src/genomi/interfaces/templates/portal_artifact_work_trace_controller.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_store.PortalStoreTests.test_artifact_version_persists_producing_work_step_from_origin tests.test_portal_store.PortalStoreTests.test_project_artifact_detail_exposes_public_reproduction_recipe tests.test_portal_frontend_artifact_origin_trace.PortalArtifactOriginTraceFrontendTest.test_artifact_origin_trace_starts_with_persisted_producing_work_step tests.test_portal_frontend_artifact_origin_trace.PortalArtifactOriginTraceFrontendTest.test_artifact_origin_trace_merges_execution_cells_from_producing_run`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_store tests.test_portal_frontend_artifact_origin_trace`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_artifact_models tests.test_portal_artifact_evidence_packet tests.test_portal_artifact_routes`

## Artifact Work Trail Anchor Checkpoint

The next independent comparison pass recommended the smallest non-overclaiming
step toward `View in context` parity: persist exact artifact-event anchors on
version-owned Work trail steps, but keep the visible surface as `Work trail`.
This lets users navigate from an artifact to the producing work card without
turning partial event state into an `Execution Log`.

Implementation notes:

- `PortalRun.emit(...)` now returns the emitted event, allowing artifact emitters
  to capture the exact event id without duplicating run-event logic.
- Host-agent produced workspace-file artifacts and artifact-render runs now call
  a narrow store helper after emitting the artifact event.
- Artifact versions keep their existing `artifact_producing_work_step`, now with
  an optional `execution_cell` anchor containing the computed artifact cell id
  and event id.
- The artifact Work trail adapter uses the stored cell id and event ids when
  rendering the `Produced artifact` card. Visible labels stay object-based; the
  ids only power hidden `highlight_step` routing and technical detail.

Visual verification:

- `screenshots/20260704-genomi-artifact-work-trail-anchor.png`

Runtime check:

- Opened `http://127.0.0.1:8874/projects/proj_819d6044b5dd/artifacts/art_9924fcad8554/versions/ver_588da5610552?artifact_tab=trace&assetBust=work-anchor-20260704`.
- The Work trail card rendered `Produced artifact`, `Open artifact`, and
  `View in chat`.
- The `View in chat` href included
  `highlight_step=run-anchor-visual%3Aartifact%3A7`.
- Browser console warnings/errors were empty.

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_execution_cells.py src/genomi/interfaces/portal_artifact_work_steps.py src/genomi/interfaces/portal_run_events.py src/genomi/interfaces/portal_store.py src/genomi/interfaces/portal_runs.py src/genomi/interfaces/portal_artifact_renderers.py`
- `node --check src/genomi/interfaces/templates/portal_artifact_origin_trace.js`
- Direct function check for all `tests/test_portal_execution_cells.py` tests.
- `PYTHONPATH=src python3 -m unittest tests.test_portal_runs tests.test_portal_frontend_artifact_origin_trace`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_store.PortalStoreTests.test_artifact_version_persists_producing_work_step_from_origin tests.test_portal_store.PortalStoreTests.test_project_artifact_detail_exposes_public_reproduction_recipe tests.test_portal_sidecar_operations.PortalSidecarOperationTests.test_retrieve_portal_run_result_package_replays_durable_run_events`

## Active Genome Switcher Checkpoint

The active-genome state must read as a user-selectable research object, not a
generic readiness flag. A status such as `Genome ready` does not tell the user
which genome is active, whether it can be switched, or how to add another
source.

Implementation notes:

- The topbar active-genome header now uses genome inventory identity before
  any generic runtime fallback.
- The ready-state context summary now prefers active genome name,
  build/source/readiness, profile, and known-genome count.
- The Genome pane keeps the active genome card, privacy boundary, known genome
  count, `Add genome`, and inactive genome `Use this genome` actions visible as
  normal product controls.

Visual verification:

- `screenshots/20260704-genomi-active-genome-switcher.png`

Runtime check:

- Opened `http://127.0.0.1:8878/?assetBust=active-genome-identity-20260704`.
- The topbar rendered `Active genome: genome computer`.
- The detail line rendered `GRCh38`, `Genome bundle`, `query-ready`, profile
  identity, and `3 genomes available`.
- The Genome pane rendered `Add genome`, the current active genome, and
  inactive genomes with `Use this genome`.
- The rendered body text did not contain `Genome ready`.

Verification:

- `node --check src/genomi/interfaces/templates/portal_genome_context.js src/genomi/interfaces/templates/portal_genome_inventory.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_genome_inventory tests.test_portal_frontend_genome_context tests.test_portal_genomes tests.test_portal_frontend_assets.PortalFrontendAssetTests.test_evidence_renderer_is_canonical_envelope_first`

## Active Genome Selector Follow-Up

The current user feedback sharpened the requirement: the topbar must not merely
say the genome is usable. It must identify the active genome and make the
switch/add flow visible.

Runtime check:

- Opened `http://127.0.0.1:8879/?assetBust=review-lifecycle-20260704` in the
  in-app browser.
- The topbar rendered `Active genome: genome computer`.
- The detail line rendered `GRCh38`, `Genome bundle`, `query-ready`, profile
  identity, and `3 genomes available`.
- `Switch` opened the Genome pane at `#genome-index` with the current genome,
  known genome count, privacy boundary, `Add genome`, and inactive genomes with
  `Use this genome`.
- The rendered body text did not contain `Genome ready`.

Visual verification:

- `screenshots/20260704-genomi-active-genome-visible-selector.png`
- `screenshots/20260704-genomi-active-genome-switch-add-flow.png`

## Artifact Review Run Lifecycle Checkpoint

The Review tab should behave like an artifact state, not a static copy block.
This slice adds a public running state and browser-side pending run while the
review POST is in flight, then keeps the completed run history attached to the
selected artifact version.

Implementation notes:

- Review-run public statuses now include `running`.
- The browser creates a pending artifact-version review run immediately when a
  user starts review checks, switches to the Review tab, and disables the menu
  action as `Checking review...` until the POST resolves.
- Completed deterministic check runs still persist on the selected artifact
  version and render in `CHECK RUN HISTORY`.
- This is still not a reviewer-agent system or async backend job queue; it is
  the honest lifecycle state around Genomi's deterministic artifact and
  evidence-boundary checks.

Runtime check:

- Opened
  `http://127.0.0.1:8879/projects/proj_819d6044b5dd/artifacts/art_9924fcad8554/versions/ver_588da5610552?assetBust=review-lifecycle-20260704`.
- Ran the review-run route with the portal CSRF token and reloaded the artifact
  version route.
- The Review tab rendered `Check run 1`, `completed`, `warning`, and
  `1 warning, 2 passed`.
- The Review summary retained the limit that these are deterministic artifact
  and evidence-boundary checks, not clinical validation.

Visual verification:

- `screenshots/20260704-genomi-artifact-review-run-history-visible.png`

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_artifact_review.py`
- `node --check src/genomi/interfaces/templates/portal_artifact_runtime_model.js`
- `node --check src/genomi/interfaces/templates/portal_artifact_actions.js`
- `node --check src/genomi/interfaces/templates/portal.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_store.PortalStoreTests.test_artifact_version_review_run_appends_public_check_history tests.test_portal_store.PortalStoreTests.test_artifact_review_pending_run_is_public_lifecycle_state tests.test_portal_frontend_artifact_library.PortalFrontendArtifactLibraryTests.test_artifact_action_menu_model_exposes_object_actions`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_artifact_evidence_packet tests.test_portal_frontend_artifact_models`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_artifact_library tests.test_portal_artifact_routes tests.test_portal_store.PortalStoreTests.test_artifact_version_review_run_appends_public_check_history tests.test_portal_store.PortalStoreTests.test_artifact_review_pending_run_is_public_lifecycle_state`

## Evidence Source Card Action Simplification

Independent UX review again flagged Evidence sources as a useful but still
fragile surface: it must read as source preparation for chat, not as a tool
request builder. The immediate visible problem was three similar actions in the
source setup panel: `Use in chat`, `Draft question`, and `Ask with source`.
Those labels made the user choose between implementation-adjacent workflows
instead of one source object.

Implementation notes:

- The source setup panel now presents one normal preparation path:
  `Include source`.
- The direct submit shortcut is now `Ask now`, making it clear that this sends
  the source-routed request through the normal chat path.
- The old setup-panel `Draft question` action was removed. Drafting remains
  available from the composer selected-material tray after a source has been
  included, where it belongs to the selected source object rather than the
  setup form.
- The server-owned source handoff packet is unchanged; selecting a source still
  routes through `/api/evidence-sources/attach` and chat, not through a
  browser-side tool runner.

Visual verification:

- `screenshots/20260704-genomi-evidence-source-actions-visible.png`

Subagent findings kept for next slices:

- UX/product review ranked durable Work trail records and research-session
  Library grouping above additional label cleanup. Evidence sources remain a
  useful small cleanup slice, but the larger goal is durable workspace objects.
- Architecture review flagged sidecar/daemon run ownership as the main
  Open-Design-style risk: sidecar `genomi.start_portal_run` should eventually
  proxy to a live portal daemon or clearly refuse when no daemon is bound, so
  browser, CLI, and MCP do not drift into parallel run owners.

Verification:

- `node --check src/genomi/interfaces/templates/portal_tool_catalog.js`
- `node --check src/genomi/interfaces/templates/portal_tool_request_builder.js`
- `node --check src/genomi/interfaces/templates/portal.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_tool_catalog tests.test_portal_frontend_assets.PortalFrontendAssetTests.test_live_result_actions_can_submit_selected_context`

## Active Genome Header Recheck

User feedback on the visible header repeated the core product requirement:
`Genome ready` is not enough information. The active genome must read as the
current research object and let the user inspect, switch, or add genomes.

Runtime check:

- Opened
  `http://127.0.0.1:8863/projects/proj_7ed74bfb6367/frames/d29cc700-e976-4757-8c50-532f175b6220`.
- The header rendered `Active genome: genome computer`.
- The detail line rendered build/source/readiness/profile context and known
  genome count.
- `Switch` and `Add` were visible as direct controls.
- A DOM check confirmed the rendered body did not contain `Genome ready`.
- Older genome-only turns rendered as `Active genome selected: ...` rather
  than replaying a hidden host-control prompt.

Visual verification:

- `screenshots/20260704-genomi-active-genome-header-object-current.png`

## Workspace Files Generated Records Grouping

The reference research-workspace pattern treats generated files as part of the
research record, not as anonymous filesystem entries. Genomi already links
workspace files back to produced artifacts when the host agent writes a file and
the portal materializes it as an artifact. This slice promotes that existing
state in the visible Files & Artifacts surface.

Implementation notes:

- Workspace files with an artifact link now appear in a top-level `Generated
  records` group.
- Generated workspace rows use `Generated record` metadata instead of leading
  with linkage mechanics.
- Ordinary workspace files still group by directory, so manual notes and local
  project files remain understandable as project files.
- `Open artifact` remains available for generated records because artifact is a
  real user-facing object in the Genomi workspace.
- This does not yet implement full session/run grouping for files. That remains
  a larger Library gap; this change uses the durable state Genomi already owns.

Runtime check:

- Created a local fixture project, `proj_a36551e56a51`, with one generated
  Markdown report linked to `art_7c93b7507325` and one plain project note.
- Opened
  `http://127.0.0.1:8863/projects/proj_a36551e56a51?assetBust=workspace-generated-records-20260704#artifact-workspace`.
- The Files pane rendered `Generated records`, `1 linked research record`,
  `Generated record`, and a separate `notes` group for the manual note.
- A DOM check confirmed the page no longer rendered the old `Linked artifact`
  row metadata.

Visual verification:

- `screenshots/20260704-genomi-workspace-files-generated-records.png`

Verification:

- `node --check src/genomi/interfaces/templates/portal_workspace_files.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_workspace_files tests.test_portal_workspace_files`
- `git diff --check -- src/genomi/interfaces/templates/portal_workspace_files.js tests/test_portal_frontend_workspace_files.py`

## Workspace Files Assistant-Turn Grouping

The previous generated-record grouping still fell short of session-style
Library organization: it grouped all produced workspace files together even
when Genomi knew which assistant turn produced each one. This slice threads
artifact origin context into the workspace-file list and uses it only as
hidden grouping state.

Implementation notes:

- `list_project_workspace_files` now projects a sanitized `origin_context` for
  generated workspace files linked to portal-owned artifacts.
- The Files pane groups generated records with origin runs as `Created in
  assistant turn`, or numbered assistant-turn groups when several turns
  produced records.
- Records without origin state still fall back to `Generated records`.
- Visible copy does not expose frame ids, run ids, operation ids, or payload
  mechanics. Those remain typed state for grouping and navigation.

Runtime check:

- Created local fixture project `proj_99e035f42ec0` with two generated
  workspace records linked to artifacts `art_26b6c3970f8f` and
  `art_f7dca6f4586c`, each with a distinct assistant-turn origin, plus one
  manual note.
- The existing `127.0.0.1:8863` server was stale and showed the older
  `Generated records` fallback. A fresh current-worktree server on
  `127.0.0.1:8884` rendered `Created in assistant turn 1`, `Created in
  assistant turn 2`, and a separate `notes` group.
- Browser DOM checks confirmed `run-origin-one`, `run-origin-two`, and frame-id
  strings were not present in visible body text.

Visual verification:

- `screenshots/20260704-genomi-workspace-files-assistant-turn-groups.png`

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_workspace_files.py`
- `node --check src/genomi/interfaces/templates/portal_workspace_files.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_workspace_files tests.test_portal_workspace_files`
- `git diff --check -- src/genomi/interfaces/portal_workspace_files.py src/genomi/interfaces/templates/portal_workspace_files.js tests/test_portal_frontend_workspace_files.py tests/test_portal_workspace_files.py`

## Active Genome Header Explicit Actions

The active-genome header must tell the user which genome is active and what
they can do with it. A green `Genome ready` chip is not enough: it hides the
current genome identity and does not make switching or adding a genome feel
like a normal workspace action.

Implementation notes:

- The topbar active-genome model now labels the selector action as `Switch`
  whenever a genome selector can be opened.
- The add action now renders as `Add genome` instead of the ambiguous `Add`.
- The portal shell fallback also uses `Add genome`, so stale or unexpected
  header models do not regress to a generic action label.

Runtime check:

- Reloaded the live current-worktree portal on `127.0.0.1:8885`.
- The header rendered `Active genome: genome computer`.
- The detail line rendered build/source/readiness/profile context and known
  genome count.
- `Switch` and `Add genome` were visible as direct controls.
- A DOM check confirmed the rendered body did not contain `Genome ready`.

Visual verification:

- `screenshots/20260704-genomi-active-genome-header-switch-add-genome.png`

Verification:

- `node --check src/genomi/interfaces/templates/portal_genome_inventory.js`
- `node --check src/genomi/interfaces/templates/portal.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_genome_inventory`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_assets.PortalFrontendAssetTests.test_genome_context_models_attach_public_context tests.test_portal_frontend_assets.PortalFrontendAssetTests.test_message_surface_replays_generic_genome_ready_as_specific_context`
- `git diff --check -- src/genomi/interfaces/templates/portal_genome_inventory.js src/genomi/interfaces/templates/portal.js tests/test_portal_frontend_genome_inventory.py`

## Workspace Ownership Boundary

The portal needs a natural workspace concept before the Files and artifact
surfaces can feel coherent. The user-facing rule is ownership-based:
browser-opened Genomi projects are Genomi-owned workspaces; agent-opened work
outside a portal project is host-agent-owned cwd.

Implementation notes:

- Portal project workspaces now resolve to `$GENOMI_HOME/workspace/<project
  workspace id>` instead of `$GENOMI_HOME/portal/workspaces/...`.
- Project workspace metadata marks portal workspaces as `owner:
  genomi_webui` and `storage: genomi_home_workspace`, without exposing an
  absolute local path in normal payloads.
- Host-agent runs launched through a portal project still execute in the
  Genomi-owned project workspace, so web chat, generated files, artifact
  materialization, and workspace-file previews share one boundary.
- Host-agent runs without a portal project still execute in the agent's current
  working directory; those files are agent-owned unless explicitly imported or
  packaged.
- Portal run status and stream events now carry a public `workspace` ownership
  object. Browser/project runs report `owner: genomi_webui` and
  `storage: genomi_home_workspace`; no-project host-agent runs report
  `owner: host_agent` without a Genomi workspace path hint.

Verification:

- `PYTHONPATH=src python3 -m unittest tests.test_portal_workspace_files tests.test_portal_runs.PortalRunPromptTests.test_host_agent_runs_from_project_workspace tests.test_portal_runs.PortalRunPromptTests.test_host_agent_without_portal_project_uses_agent_workspace`
- `PYTHONPATH=src python3 -m unittest tests.test_mcp_http.MCPHTTPTests.test_project_workspace_files_endpoint_lists_relative_files tests.test_mcp_http.MCPHTTPTests.test_run_result_package_returns_public_workspace_handoff`
- `python3 -m py_compile src/genomi/interfaces/portal_workspaces.py src/genomi/interfaces/portal_runs.py src/genomi/interfaces/portal_store.py`
- `git diff --check -- AGENTS.md src/genomi/interfaces/portal_workspaces.py src/genomi/interfaces/portal_store.py tests/test_portal_workspace_files.py tests/test_portal_runs.py docs/research/claude-science-portal-study/genomi-portal-ux-product-rules.md docs/research/claude-science-portal-study/exploration-log.md`

## Workspace File Identity Guard

Generated workspace files are research records only while the current file
still matches the artifact Genomi materialized. Filename alone is not enough:
an edited file with the same path is a project file, not the same generated
record.

Implementation notes:

- Workspace-file listing now checks the current file identity before attaching
  `artifact_id`, `artifact_preview_url`, or origin-chat context.
- The identity check compares current file size and SHA-256 against the
  materialized artifact identity from the project-file artifact summary or
  latest artifact version.
- Valid generated records keep `Open artifact` and `View in chat` actions.
- Edited same-name files remain visible as normal research files but do not
  inherit generated-record actions or hidden origin context.

Runtime check:

- Created fixture project `proj_a73a9a7e9b75` with `reports/current.txt`
  matching its generated artifact and `reports/stale.txt` edited after its
  artifact was created.
- The workspace-files endpoint returned `total_files: 2` and
  `linked_artifacts: 1`.
- The browser rendered `reports/current.txt` in `Created in assistant turn`
  with `Open artifact` and `View in chat`.
- The browser rendered `reports/stale.txt` under `reports` as `Research file`
  with only `Open`.
- DOM checks confirmed no run id or Genomi-home storage metadata was visible.

Visual verification:

- `screenshots/20260704-genomi-workspace-file-identity-guard.png`

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_workspace_files.py`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_workspace_files`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_workspace_files tests.test_mcp_http.MCPHTTPTests.test_project_workspace_files_endpoint_lists_relative_files tests.test_mcp_http.MCPHTTPTests.test_run_result_package_returns_public_workspace_handoff`

## Current Evidence Scope Guard

`Current evidence` must behave like the active conversation's evidence tray,
not a global project authority or session-state bucket. The useful research
workspace pattern is that users can reuse evidence results near the chat, while
active genome/session context stays in the genome object and technical runtime
state stays behind details.

Implementation notes:

- The evidence ledger now ignores records without the active conversation
  `frameId` whenever a frame scope is active.
- The ledger admits evidence-shaped entries and persisted redacted evidence
  history, but excludes generic result views, workflow events, and
  `genomi.describe_context` session context.
- The reusable ledger filter now counts only current-conversation evidence
  material. Active genome context remains attachable from the Active genome
  surface instead of being relabeled as evidence.
- A strict maintainability sidecar flagged destructive scope filtering as
  controller-state debt. The ledger now retains all evidence-shaped entries in
  memory and derives the visible list from the active conversation scope and
  filter, so switching conversations hides out-of-scope evidence without
  deleting it.

Verification:

- `node --check src/genomi/interfaces/templates/portal_evidence_ledger.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_evidence_ledger_selection tests.test_portal_frontend_assets`

## Artifact Detail Vocabulary By Object Family

Artifact workspace chrome should describe the research object the user opened.
The generic word `artifact` is still valid for unknown generated objects, but
normal files, reports, and evidence reports need their own labels.

Implementation notes:

- `artifactProvenanceModel()` now derives its details title from artifact
  family: `Evidence report details`, `Report details`, `File details`, or
  `Artifact details`.
- The artifact preview tab and action menu use that family label, so the menu
  says `Open evidence report details` for evidence reports and `Open report
  details` for legacy reports instead of the generic `Open artifact details`.
- Review-summary selected material uses the same family label when it includes
  version/history details.
- Empty artifact workspace copy no longer promises a generic review surface;
  it points users to preview, evidence, origin chat, and work history when
  those backed objects exist.

Verification:

- `node --check src/genomi/interfaces/templates/portal_artifact_display_model.js && node --check src/genomi/interfaces/templates/portal_artifact_view_model.js && node --check src/genomi/interfaces/templates/portal_artifact_runtime_model.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_artifact_models tests.test_portal_artifact_evidence_packet`

## Generated File Preview Keeps History Attached

The file workspace should preserve the strongest reference-workspace behavior:
when a generated Markdown/script/table/image/PDF/notebook is opened, the user
can still jump to the generated record and the origin conversation. Opening the
file should not discard the history that made it trustworthy.

Implementation notes:

- Workspace file previews now carry the row's artifact identity and origin chat
  context through the async preview request.
- Generated-file preview panels render `Open generated record` and `View in
  chat` when the workspace listing already proved the current file still
  matches its materialized artifact.
- Generated-file preview headers now say `Generated record`; ordinary opened
  files remain `Research record`.
- Portal projects now materialize their Genomi-owned workspace at project
  creation/default-project resolution under `$GENOMI_HOME/workspace/<project>`.
  Host-agent-only runs without a portal project still use the agent's current
  working directory and do not receive the portal workspace prompt section.
- Workspace file listings and previews now carry server-owned `file_kind`,
  `kind_label`, and `record_label` fields. The frontend prefers those fields
  and keeps local classification only as a stale-payload fallback.
- The preview API remains content-focused; the browser reuses the already
  loaded workspace-file identity rather than adding transport fields to the
  preview response.

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_workspace_files.py`
- `node --check src/genomi/interfaces/templates/portal_workspace_files.js && node --check src/genomi/interfaces/templates/portal_workspace_file_context.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_workspace_files tests.test_portal_frontend_workspace_files`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_workspace_files tests.test_portal_runs tests.test_portal_sidecar_operations tests.test_portal_frontend_workspace_files`

## Workspace Files Gain Library Location Filters

The project file surface should behave more like a research library than a
single undifferentiated output list. Genomi already keeps backend paths hidden
and groups project files by generated-record identity and project-relative
folder. The next useful slice is making those groups directly selectable.

Implementation notes:

- `workspaceFilesModel()` now computes user-facing library locations:
  `All files`, `Generated records`, and project-relative folders such as
  `reports` or `Project root`.
- The Files & Artifacts workspace renders those locations as compact filter
  buttons above the file list. Selecting a folder shows ordinary files in that
  project folder; selecting `Generated records` shows only current files that
  still match a materialized artifact identity.
- Search remains scoped to the selected library location. This keeps the normal
  UI focused on files, generated records, and relative project folders, not
  backend workspace paths or artifact ids.
- The controller preserves this as local browser view state and resets the
  selected location when the project changes.

Verification:

- `node --check src/genomi/interfaces/templates/portal_workspace_files.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_workspace_files`
- `git diff --check -- src/genomi/interfaces/templates/portal_workspace_files.js src/genomi/interfaces/templates/portal_workspace_files.css tests/test_portal_frontend_workspace_files.py`

## Serve App Launch Contract

The portal entry command now matches the product direction: `genomi serve`
opens the local Genomi science workspace when launched from an interactive
terminal. The same command remains safe for host-agent configs because non-TTY
launches stay on MCP stdio. `genomi serve --app --no-browser` is the
daemon/headless form for supervisors or tests, and `genomi serve --transport
stdio` explicitly selects the MCP stdio server.

Implementation notes:

- The CLI default transport is `auto`: TTY stdin/stdout selects the HTTP
  portal/MCP server with `open_browser=true`; non-TTY launch selects stdio MCP.
- `--app` forces the workspace mode and routes it through the HTTP portal/MCP
  server with `open_browser=true` unless `--no-browser` is present.
- `--transport http` remains available as a non-browser MCP/HTTP mode for
  existing technical setups; `--transport stdio` forces MCP stdio.
- `genomi install` now returns `genomi serve` as the portal onboarding handoff,
  plus explicit headless and MCP commands.
- The HTTP server prints `starting Genomi workspace` for the portal URL while
  still exposing `/mcp` on the same local server.

Verification:

- `python3 -m py_compile src/genomi/interfaces/cli.py src/genomi/interfaces/mcp.py src/genomi/operations/registry/handlers_admin.py`
- `PYTHONPATH=src python3 -m unittest tests.test_genomi_runtime_mcp.GenomiRuntimeMcpTests.test_cli_serve_auto_opens_workspace_from_terminal tests.test_genomi_runtime_mcp.GenomiRuntimeMcpTests.test_cli_serve_auto_keeps_stdio_for_host_agent_pipes tests.test_genomi_runtime_mcp.GenomiRuntimeMcpTests.test_cli_serve_auto_no_browser_keeps_workspace_headless tests.test_genomi_runtime_mcp.GenomiRuntimeMcpTests.test_cli_serve_app_uses_http_workspace_and_opens_browser tests.test_genomi_runtime_mcp.GenomiRuntimeMcpTests.test_cli_serve_app_no_browser_keeps_http_workspace_headless tests.test_genomi_runtime_mcp.GenomiRuntimeMcpTests.test_cli_serve_transport_http_preserves_non_browser_mcp_mode tests.test_mcp_http.MCPHTTPTests.test_http_serve_can_open_workspace_browser tests.test_genomi_install.GenomiInstallTests.test_install_persists_response_profile_without_context_disclosure`

## Browser Imports Become Workspace Files

The portal had the workspace ownership boundary, but browser imports still
behaved like artifact-only blobs. That split made the workspace feel less real:
the host agent ran in `$GENOMI_HOME/workspace/<project>`, generated files were
scanned from there, but user-imported source files lived only in artifact
storage.

Implementation notes:

- Browser file import now writes the sanitized filename into the Genomi-owned
  project workspace, then snapshots the same bytes as a `project_file` artifact.
- The import response returns a project-relative `workspace_relative_path`;
  public API payloads still avoid absolute local paths.
- Workspace-file listing links imported files back to their import artifact
  only while the current workspace file still matches the artifact checksum and
  size.
- Imported files are labeled and filterable as `Imported file`; assistant-
  produced files remain `Generated record` and retain origin-chat actions only
  when the file identity still matches the materialized artifact.
- The browser refreshes Files immediately after an import, so uploads appear as
  normal project files instead of only as artifact cards.

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_file_imports.py src/genomi/interfaces/portal_workspace_files.py`
- `node --check src/genomi/interfaces/templates/portal_workspace_files.js && node --check src/genomi/interfaces/templates/portal.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_workspace_files tests.test_portal_artifact_routes tests.test_portal_frontend_workspace_files`

## Selected Material Starts Focused Conversations

The portal already let users ask about a selected file, artifact, work step, or
evidence object in a fresh conversation, but the server treated that as an
ordinary new frame. The browser reset the current frame before submitting, so
the project lost the product-level fact that the new conversation started from
an existing research object.

Implementation notes:

- Fresh selected-material conversations now send a `startedFromSelectedMaterial`
  handoff flag and optional same-project `sourceFrameId` through the canonical
  `/api/runs` path.
- `portal_store.create_frame()` persists a compact `started_from` object in the
  frame input data. Public frame summaries expose only `kind`,
  `material_count`, selected-material labels, and a short `Started from ...`
  summary; source frame ids remain hidden transport state.
- The frame remains a normal root conversation. This avoids pretending Genomi
  has a full fork tree or side-chat pane before those product objects exist.
- The same shape is available from the sidecar operation
  `genomi.start_portal_run` through `started_from_selected_material` and
  `source_frame_id`, preserving the one-run-contract rule.
- The conversation list now includes the `Started from ...` summary beside
  status and message count, so the origin is visible without exposing packet
  mechanics.

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_selected_material.py src/genomi/interfaces/portal_turns.py src/genomi/interfaces/portal_store.py src/genomi/interfaces/portal_run_service.py src/genomi/interfaces/portal.py src/genomi/operations/registry/handlers_portal.py`
- `node --check src/genomi/interfaces/templates/portal.js && node --check src/genomi/interfaces/templates/portal_api.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_store.PortalStoreTests.test_selected_material_new_conversation_records_public_handoff tests.test_portal_store.PortalStoreTests.test_selected_material_handoff_ignores_cross_project_source_frame tests.test_mcp_http.MCPHTTPTests.test_run_create_new_frame_records_selected_material_handoff tests.test_portal_sidecar_operations.PortalSidecarOperationTests.test_portal_run_control_operations_are_in_default_tool_discovery tests.test_portal_sidecar_operations.PortalSidecarOperationTests.test_start_portal_run_can_start_focused_conversation_from_selected_material tests.test_portal_frontend_assets.PortalFrontendAssetTests.test_live_result_actions_can_submit_selected_context`

## Generated Files Group By Origin Conversation

The next Library gap was that generated workspace records were still grouped by
anonymous assistant-turn buckets. That is technically coherent, but the
reference science-workspace pattern makes files feel attached to the research
session or conversation that produced them.

Implementation notes:

- Generated workspace files now enrich their public `origin_context` with a
  prompt-safe `frame_title` when the linked artifact still matches the current
  project workspace file and the origin frame belongs to the same project.
- The Files & Artifacts Library groups generated records by origin conversation
  when that frame provenance exists. The visible group label becomes
  `Created in <conversation title>` and the summary says the files came from
  this conversation.
- Older or incomplete generated-file payloads still fall back cleanly: files
  with a frame id but no title group as `Created in conversation`; files with
  only run ids keep the previous assistant-turn grouping; files with no proven
  current artifact identity remain ordinary project files.
- Imported files are unchanged and still separate from generated records.

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_workspace_files.py`
- `node --check src/genomi/interfaces/templates/portal_workspace_files.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_workspace_files tests.test_portal_frontend_workspace_files`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_artifact_routes tests.test_portal_frontend_assets`

## Workspace Ownership In Files Pane

The portal already used the correct storage boundary: browser-opened project
runs execute inside `$GENOMI_HOME/workspace/<project>`, while agent-only runs
use the host agent's current working directory. The missing product layer was
that the Files pane still looked like an anonymous file list, so the user could
not see the local workspace concept.

Implementation notes:

- The workspace-file API already returns safe public `workspace` ownership
  metadata. The frontend now reads that metadata and labels the pane as
  `Project workspace` with `Genomi-owned files`.
- The only path-like hint shown is the safe `$GENOMI_HOME/workspace/<project>`
  tokenized path, never an absolute local filesystem path.
- Empty-state copy now says imported files and generated research records will
  appear in this Genomi workspace.
- Focused tests pin both sides of the boundary: project runs use Genomi-owned
  workspace metadata, and host-agent runs outside a portal project remain
  `host_agent_current_working_directory`.

Verification:

- `node --check src/genomi/interfaces/templates/portal_workspace_files.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_workspace_files.PortalWorkspaceFileTests.test_workspace_file_listing_is_path_safe_and_links_produced_artifacts tests.test_portal_runs.PortalRunPromptTests.test_compose_prompt_includes_portal_owned_workspace_only_for_project_runs tests.test_portal_runs.PortalRunPromptTests.test_host_agent_without_portal_project_uses_agent_workspace`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_workspace_files.PortalFrontendWorkspaceFilesTests.test_workspace_files_model_searches_and_links_artifacts tests.test_portal_frontend_workspace_files.PortalFrontendWorkspaceFilesTests.test_workspace_files_render_open_artifact_action_and_search_input`

## Web Chat Run Exercise: Public Pharmacogenomics Question

I exercised the portal through the same browser-facing run endpoint used by the
composer: `POST /api/runs` with project
`proj_a73a9a7e9b75`, frame
`116bd0bc-0e7a-4d09-86fb-2a198c54d2d8`, agent `claude`, and the message:

> Public-only UI test: Review CYP2C19 and clopidogrel evidence. Do not use the
> active genome. Explain what public evidence can and cannot support, and keep
> it concise.

The run id was `567706ac2f6c43eda12015d534b1f64c`. The portal CSRF boundary
worked: a raw POST without `X-Genomi-CSRF` was rejected with
`csrf_required`, and the accepted request used the CSRF token from the portal
HTML, matching the browser composer contract.

Observed run behavior:

- The server created a normal host-agent run and recorded the web-owned
  workspace boundary:
  `$GENOMI_HOME/workspace/proj_a73a9a7e9b75`,
  `owner=genomi_webui`, `scope=project`.
- Claude loaded the pharmacogenomics skill, discovered
  `mcp__genomi__genomi_invoke`, and called
  `pharmacogenomics.review_medication`.
- The first call defaulted to including active-genome context because an active
  genome existed, even though the prompt said public-only. Claude noticed this
  and reran with sample context off. Final assistant text explicitly reported
  `sample_context_requested: false` and `sample_signal_count: 0`.
- Genomi evidence retrieval succeeded. The assistant answer summarized public
  CYP2C19/clopidogrel evidence and stated that public evidence cannot infer the
  user's genotype or personal medication actionability.
- The run completed successfully with execution cells and generated artifacts.

UX problems exposed:

- The default Work Trail was polluted by host-agent mechanics: `Skill`,
  `ToolSearch`, `Bash`, `spawn_agent`, `host_agent_context_load`, oversized
  tool-output recovery, and a Bash static-analysis error.
- The loaded skill body appeared as a diagnostic event. That is useful
  technical state but wrong as a user-facing research step.
- The assistant had to recover from oversized Genomi outputs through saved-file
  inspection. The portal should render the Genomi evidence result as a clean
  evidence object/artifact and hide that recovery choreography by default.
- The public-only instruction was eventually honored, but only after an initial
  active-context-including call. The portal needs a clearer request-time switch
  or server-side policy for public-only turns, not just assistant prose.

Implementation response in this pass:

- Execution-cell payloads now mark diagnostics, stdout/stderr, and host-agent
  plumbing tools (`Skill`, `ToolSearch`, raw `mcp__...` wrappers, and ordinary
  `Bash` recovery steps) as `visibility=technical`.
- Bash recovery steps that surface a Genomi operation headline such as
  `pharmacogenomics.review_medication: evidence_present ...` are promoted back
  into a visible Genomi evidence step for the default Work Trail.
- The default Work Trail model filters technical execution cells. The records
  remain in the run package for technical inspection, but normal users see
  research work rather than setup chatter. Reprojecting the completed run after
  the patch showed two visible steps: the medication-response evidence review
  and the completed run state.

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_execution_cells.py`
- `node --check src/genomi/interfaces/templates/portal_frame_trace.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_execution_cells tests.test_portal_frontend_frame_trace`

## Genomi Portal UIUX Declutter Pass

Screenshots:

- `screenshots/20260704-genomi-portal-uiux-declutter-pass.png`
- `screenshots/20260704-genomi-workspace-switcher-search.png`

Changes made from the local Claude Science comparison:

- The topbar now treats the active genome as a named workspace object, not a
  readiness probe. Live verification showed `Active genome: george` with build,
  source, profile, and available-genome count; `Genome ready`, `query-ready`,
  and `Review passed` were absent from visible default copy.
- The local assistant status moved into a collapsed `Local assistant` support
  surface. The default rail no longer exposes `Assistant status` as a primary
  workspace object.
- Conversation export moved under a `More` menu. The chat header keeps the
  research task centered instead of advertising a bundle download as a main
  action.
- The workspace switcher now has search and a bounded recent/current list. In
  the live desktop check it showed 8 workspaces with `Showing 8 of 327. Search
  to narrow.` instead of flooding the sidebar.
- Message work-step summaries no longer count hidden diagnostics as user-facing
  work. Permission requests remain visible because they require user action;
  host-agent telemetry and status notes stay technical by default.

Verification:

- `node --check src/genomi/interfaces/templates/portal.js`
- `node --check src/genomi/interfaces/templates/portal_messages.js`
- `node --check src/genomi/interfaces/templates/portal_genome_inventory.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_genome_inventory tests.test_portal_frontend_assets tests.test_portal_frontend_routes`
- Live Browser check against
  `http://127.0.0.1:8885/projects/proj_a73a9a7e9b75/frames/116bd0bc-0e7a-4d09-86fb-2a198c54d2d8`

## Portal-Owned Permission Approval

The local science workspace cannot strand a user in host-agent permission
errors. If the host agent asks to use a Genomi MCP tool, the browser must show a
normal approval object and the server must retry the same turn with that
specific approved boundary.

Implementation response:

- Claude stream parsing now extracts permission requests from both top-level
  error events and `tool_result` error content. This covers the observed
  failure mode where the assistant surfaced
  `Claude requested permissions to use ... but you haven't granted it yet` as a
  failed tool result.
- Permission cards stay visible in the default work trail because they require
  user action, but their copy is user-facing. The card now says `Read current
  Genomi context`, `Add a genome source`, `Build an evidence packet`, or a
  similar plain-language access label instead of leading with raw
  `mcp__genomi__...` names.
- Raw tool names remain in the typed payload for server retry and in copied
  technical details, not in the normal card summary or explanation.
- `POST /api/runs/{run_id}/approve-permission` remains CSRF-protected. A valid
  browser approval creates a new host-agent run for the same frame/request with
  the approved tool included, rather than duplicating the user's message.

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_agents.py src/genomi/interfaces/portal_run_service.py src/genomi/interfaces/portal.py`
- `node --check src/genomi/interfaces/templates/portal_messages.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_agents tests.test_portal_runs tests.test_mcp_http.MCPHTTPTests.test_run_permission_approval_route_retries_from_portal tests.test_portal_frontend_assets.PortalFrontendAssetTests.test_message_surface_renders_permission_result_as_approval_card`

## Composer Genome Evidence Boundary

The live public-only pharmacogenomics run exposed a product gap: the assistant
eventually separated public evidence from active-genome context, but only after
an initial tool call included sample context. The workspace needs a visible
turn-level boundary before host-agent reasoning starts.

Implementation response:

- The composer no longer has a `Genome evidence` segmented control. Asking the
  user to choose `Public sources` versus `Use active genome when relevant`
  exposed routing machinery as product UX.
- The server-owned prompt boundary remains. The active genome is visible in the
  workspace header and genome panel; the user asks naturally, and the host
  agent uses the approved active genome only when the request actually calls
  for it.
- Prompt composition includes a `# Genome context boundary` section. In the
  normal portal path it says to use public evidence first and use the approved
  active genome only when it is directly relevant.
- Permission retries preserve the original run's genome-context mode when an
  explicit mode exists in older or specialized requests.
- Visible UI copy stays user-facing. The normal composer does not expose
  `genomeContextMode`, `Genome evidence`, or `Use active genome when relevant`
  as per-turn controls.

Screenshot:

- `screenshots/20260706-genomi-composer-genome-evidence-mode.png`

Verification:

- `python3 -m py_compile src/genomi/interfaces/portal_run_events.py src/genomi/interfaces/portal_runs.py src/genomi/interfaces/portal_store.py src/genomi/interfaces/portal_run_service.py src/genomi/interfaces/portal.py`
- `node --check src/genomi/interfaces/templates/portal.js && node --check src/genomi/interfaces/templates/portal_api.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_runs.PortalRunPromptTests.test_compose_prompt_respects_public_only_genome_boundary tests.test_portal_runs.PortalRunPromptTests.test_project_request_run_snapshots_active_view_context tests.test_portal_runs.PortalRunPromptTests.test_frame_followup_run_snapshots_prior_conversation tests.test_portal_runs.PortalRunPromptTests.test_permission_approval_retries_same_turn_without_duplicate_user_message tests.test_mcp_http.MCPHTTPTests.test_run_create_starts_project_frame_and_followup_message tests.test_portal_frontend_assets.PortalFrontendAssetTests.test_submit_turn_posts_canonical_run_request tests.test_portal_frontend_assets.PortalFrontendAssetTests.test_live_result_actions_can_submit_selected_context`
- Live browser check against `PYTHONPATH=src genomi serve --app --no-browser --port 8901`.

## Evidence Attachment Wording

The current-evidence ledger is already scoped to the active conversation and
restored from saved work history, but its controls still used context-packet
language: `Use current evidence`, `Use selected evidence`, and `Using the full
current evidence result`. That wording made the user feel like they were
managing an internal packet rather than carrying evidence into the next
research turn.

Implementation response:

- Full-result selection now reads `Full evidence result selected`.
- The primary ledger action is `Attach evidence to chat`, and the toolbar
  summary action is `Attach current evidence`.
- Node-level selection now says `Attach selected evidence` and `Draft with
  selected evidence`. The visible object remains evidence, while hidden
  transport fields stay in typed payloads for the host-agent handoff.

Verification:

- `node --check src/genomi/interfaces/templates/portal_evidence_ledger.js && node --check src/genomi/interfaces/templates/portal_evidence_ledger_selection.js && node --check src/genomi/interfaces/templates/portal_selection_actions.js`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_evidence_ledger_selection`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_assets`

## Live Host-Agent Answer And Permission Boundary

A real browser turn asked which gene contains `rs429358`. Before this pass,
every Claude assistant text block was appended to the visible answer, including
skill discovery, failed shell attempts, parameter corrections, and source
setup. The final answer was present, but only after several paragraphs of
runtime narration.

Implementation response:

- Claude assistant text emitted before its terminal result is now stored as
  `Assistant status` work-trail detail. The terminal result is the only text
  written to the visible assistant answer.
- Successful runs without a terminal answer still produce an explicit empty
  result notice rather than leaving a blank assistant message.
- Permission detection is enforced at the run-presentation boundary and again
  when saved work is presented. Older saved tool errors that contain the
  standard permission sentence can therefore recover the typed approval object
  even if the original event omitted it.
- Permission cards automatically open their work group and expose `Approve
  access and retry`. A live DOM check on the saved `rs429358` conversation found
  three approval actions for the blocked web/Open Targets calls after reload.
- Friendly labels translate `WebSearch`, `WebFetch`, external MCP connectors,
  and Genomi tools into the access being requested while retaining the exact
  tool name only for the typed retry contract and technical details.

The same run exposed two library problems: `$GENOMI_HOME` appeared in the
normal Files surface, and project files were repeated in a second artifact
inventory and in a project-wide strip above the composer.

- The file view model no longer carries or renders a workspace storage hint.
- File artifacts already represented by a project-relative file are removed
  from the secondary artifact record list by artifact id or relative path.
- When every artifact is already represented by a file, the second artifact
  inventory is hidden.
- The project-wide artifact strip was removed from the composer. Artifacts
  remain attached to their producing assistant message and available in Files.

Screenshots:

- `screenshots/20260710-genomi-clean-answer-permission-and-files.png`
- `screenshots/20260710-genomi-unified-files-workspace.png`

Verification:

- A live Claude turn at `http://localhost:8901/` completed with only its
  terminal result in the assistant answer.
- A browser DOM check confirmed three restored permission approval actions,
  no project-wide artifact tray, no visible workspace storage hint, two project
  file rows, and no duplicate artifact library.
- `PYTHONPATH=src python3 -m unittest tests.test_portal_agents tests.test_portal_runs tests.test_portal_frontend_workspace_files`
- `PYTHONPATH=src python3 -m unittest tests.test_portal_frontend_artifact_library tests.test_portal_frontend_workspace_files tests.test_portal_frontend_assets`

## Workspace-Scoped Active Genome Boundary

The portal previously projected the process-wide Active Genome Index as though
it belonged to every workspace. A configured default user or a genome selected
in one project could therefore remain visible and readable after switching to
another project.

Implementation response:

- Each portal project now persists only the selected `agi_id`, approval time,
  and `portal_project` scope. Private AGI records and source paths are not
  copied into portal project state.
- Every host-agent run receives a project-specific context file through
  `GENOMI_CONTEXT`. That file contains the selected AGI identity and grant, or
  an explicit empty binding, while the shared registry remains the source of
  AGI metadata.
- Project contexts disable default-user auto-selection. This preserves the
  existing default-user behavior for CLI/agent sessions while preventing it
  from crossing the portal workspace boundary.
- `/api/context` and `/api/genomes` now project the requested project's binding.
  Selecting a genome updates only that project instead of mutating the global
  runtime session.
- The top bar reads `Choose active genome` / `Choose` when registered genomes
  exist but the current workspace has no selection. After selection it names
  the actual genome and keeps `Switch` and `Add genome` available.
- The Genome pane no longer offers `Include active genome`. Selecting the
  workspace genome is the approval; the host agent uses it only when relevant.
  Privacy copy now says `Selected for this workspace` and `Not shared
  automatically`.
- Workspace transitions clear the old transcript and selected material before
  opening the target project, preventing another project's conversation from
  lingering under the new workspace header.

Live verification:

- In `Workspace identity guard checkpoint`, selecting `george` changed the
  header to `Active genome: george` and a real host-agent context check returned
  the 23andMe GRCh37 genome with portal-project approval.
- Switching to `Workspace assistant-turn records checkpoint` changed the header
  to `Choose active genome`; the same host-agent check returned no active
  genome.
- Switching back restored `george` and did not retain the other workspace's
  context-check conversation.

Screenshot:

- `screenshots/20260710-genomi-workspace-scoped-genome.jpg`

Verification:

- `PYTHONPATH=src python3 -m unittest tests.test_portal_genomes tests.test_portal_project_genomes tests.test_portal_frontend_genome_inventory tests.test_portal_runs tests.test_portal_store tests.test_mcp_http.MCPHTTPTests.test_portal_genome_selection_is_isolated_between_projects`
- `PYTHONPATH=src python3 -m unittest tests.test_genomi_runtime_context tests.test_portal_context tests.test_portal_frontend_assets tests.test_portal_frontend_genome_inventory tests.test_portal_genomes tests.test_portal_project_genomes tests.test_portal_runs tests.test_portal_store tests.test_mcp_http.MCPHTTPTests.test_portal_genome_selection_is_isolated_between_projects`
- Live in-app-browser comparison against `PYTHONPATH=src genomi serve --app
  --no-browser --port 8901`.

## Durable Conversation Identity

The reference workspace treats a session as a durable research object rather
than naming it with a clipped copy of the first prompt. The active session is
selected in the left rail, its title remains the navigation identity, and a
secondary session menu exposes rename, move, export, artifact download,
notebook, and delete actions. Only rename has an equivalent backed by current
Genomi state; move, delete, and archive remain intentionally absent.

Implementation response:

- Portal frames now persist a prompt-safe `title` separately from the original
  request. Existing frames receive the bounded request-derived title when read.
- The selected conversation title appears in the chat header and the
  conversation rail. Renaming updates the durable frame summary and any file
  origin label that resolves through that conversation.
- The rail has bounded client-side search over durable titles and original
  display requests. The selected conversation stays first when no search is
  active.
- A secondary `More` menu contains `Rename conversation` and the existing
  conversation bundle download. No archive or delete action is shown without a
  persisted recovery contract.
- Live browser testing found and fixed an incorrect chat-grid row assignment
  that pushed the rename controls out of view. The fixed grid keeps the header
  and rename row fixed, messages scrollable, and composer anchored.

Live verification:

- Renamed the active project conversation to `Active genome workspace check`.
- Confirmed the new title in both the rail and chat header, filtered the rail to
  one matching conversation, and confirmed title persistence after a full
  frame-route reload.
- `PYTHONPATH=src python3 -m unittest tests.test_portal_store tests.test_mcp_http tests.test_portal_frontend_assets tests.test_portal_frontend_workspace_files`
  passed 131 tests.

Screenshots:

- `screenshots/20260710-reference-conversation-identity.jpg`
- `screenshots/20260710-genomi-conversation-identity.jpg`

## Live Artifact Viewing Hierarchy

An authenticated local reference session was exercised beyond onboarding and
through the actual Files, quick-preview, and split-artifact flow. The important
pattern is not a particular visual treatment; it is an explicit promotion
hierarchy for research objects.

Observed reference behavior:

- Files opens as a workspace tab without discarding the active conversation.
- Clicking an artifact card first opens a large modal preview over the library.
  The preview has only More, open in split view, download, and close actions.
- Promoting the preview to split view restores the producing conversation on
  the left and places the selected artifact on the right. The artifact becomes
  the dominant right-pane object while the session remains active.
- The default artifact view does not show readiness badges, a result-history
  strip, or a single-version selector. Provenance remains accessible but is not
  presented as equal-weight status chrome around the preview.

Genomi implementation response:

- Selecting a generated record replaces the file list with the artifact view
  and exposes `Back to files`; the conversation stays open beside it.
- Artifact headers no longer show `Artifact ready`, a duplicate result-history
  strip, or a version selector when only one version exists.
- Successful review state and default tab badges are silent. Review warnings,
  failures, running state, source limits, privacy boundaries, and historical
  version identity remain visible when they materially affect the object.
- File rows now preview the file as their primary interaction. Generated-record
  details and origin chat are secondary actions under More instead of three
  competing row buttons.
- File preview is now a focused overlay over the library. Its default actions
  are `Use file`, More, and Close; Start conversation, generated-record details,
  and origin chat remain available under More.

Screenshots:

- `screenshots/20260710-reference-artifact-quick-preview.jpg`
- `screenshots/20260710-reference-artifact-split-view.jpg`
- `screenshots/20260710-genomi-file-quick-preview.jpg`
- `screenshots/20260710-genomi-selected-artifact-workspace.jpg`

Verification:

- Live in-app-browser interaction against the authenticated reference at
  `http://localhost:8765/` and Genomi at `http://127.0.0.1:8901/`.
- `node --check` for the changed artifact and workspace-file modules.
- Focused frontend suites for workspace files, artifact models, artifact
  selection, artifact library, evidence artifacts, and portal assets.

## Conversation Reviewer And Composer Attachments

The authenticated local reference was reopened at `http://localhost:8765/`
and exercised inside an example project rather than inferred from onboarding
or the public product page. The project view keeps session navigation, the
conversation, and the currently opened artifact visible as one workspace. A
generated image opens directly in the right pane while the producing
conversation and its generated-artifact thumbnails remain in place.

The reference runtime assets also confirm that Reviewer is a conversation-level
verification object. It has a compact idle/running state, claim-oriented
findings, evidence and recommendation text, and links back to reviewed work. It
is not the same object as deterministic artifact checks.

Genomi implementation response:

- A host-agent conversation review now runs through the existing server-owned
  run contract without adding a fake user or assistant message to the
  transcript.
- The persisted review records verifying, findings, clear, inconclusive, and
  failed states; findings carry a verdict, claim, evidence, recommendation, and
  a bounded source-message reference.
- `Jump to claim` highlights the reviewed message or research step. `Use in
  chat` attaches that finding to the next message without exposing run ids,
  tool ids, context fields, or raw payloads.
- Successful checks contribute to the check count but do not render affirmative
  `passed` rows. Only warnings, errors, and inconclusive findings occupy the
  expanded review surface.
- Composer attachments are now compact object chips. Their full evidence,
  provenance, and recommendation remain in the source surface where the user
  selected them; the composer no longer duplicates those details or offers
  generic `Ask about evidence`, `Ask in new conversation`, and `Draft question`
  controls inside every attachment.
- Reviewer language is projected through user-facing genome labels before it
  reaches the browser. Internal MCP names, Active Genome Index field names,
  and hashed transport ids are not product copy.
- Run-start attachment and thread-start failures now terminalize the new run
  and conversation coherently instead of leaving mismatched persisted and
  in-memory processing state.

Screenshots:

- `screenshots/20260710-claude-science-local-project-workspace.jpg`
- `screenshots/20260710-genomi-conversation-reviewer-findings.jpg`

Verification:

- Live request, completed host-agent review, claim jump, and reviewer-finding
  attachment against `http://127.0.0.1:8901/`.
- Live local reference project navigation and generated-image inspection at
  `http://localhost:8765/`.
- Focused reviewer, prompt-context, run-service, and store test suites plus JS
  syntax and Python compilation checks.

## Paired Research Run: Permission Boundaries

The same public-genetics task was submitted to both local workspaces:

> Using public sources only, summarize the functional evidence linking
> rs429358 to Alzheimer's disease and produce a concise Markdown report with a
> source table. Keep limitations explicit.

Observed reference behavior:

- Permission is a pause in the active research session, not a failed research
  result. The prompt names the requested connector or compute environment and
  stays visible until the user decides.
- Scope is part of the decision. The exercised run offered project scope for a
  connector method, conversation scope for Python, and a broader connector-wide
  allowance for Open Targets.
- Allowing access resumes the same session in place. The user request is not
  duplicated and prior research progress remains readable.

Genomi implementation response:

- A host-agent permission request now moves the run to an
  `awaiting_permission` terminal stream state and the conversation to the
  user-facing `Needs approval` state instead of recording a failed turn.
- The first requested capability is kept as the actionable boundary; duplicate
  permission errors and the tool failures that follow a blocked capability are
  suppressed from that run's visible stream.
- Approval can interrupt a still-running source process, persist the exact
  allowed tool for the Genomi workspace, and start the retry immediately. The
  retry reuses the original request and prior conversation without adding a
  second user message.
- The approval card says what the assistant needs in product language and uses
  `Allow for this workspace`. Later status diagnostics no longer collapse and
  hide a pending decision.

Remaining difference:

- Genomi currently supports exact-tool workspace scope. Conversation-only,
  connector-family, and explicit scope-change controls remain gaps and should
  not be implied until their revocation and persistence contracts exist.

Screenshots:

- `screenshots/20260714-local-reference-scoped-permission-run.jpg`
- `screenshots/20260714-genomi-workspace-scoped-permission.jpg`

Verification:

- Live permission request and `202 Accepted` retry against
  `http://127.0.0.1:8901/` while the source Claude process was still active.
- The persisted workspace allowance contains the requested PubMed connector
  method and is passed to the replacement host-agent run.
- Permission, run-service, HTTP-route, and message-surface suites passed 75
  focused tests.
