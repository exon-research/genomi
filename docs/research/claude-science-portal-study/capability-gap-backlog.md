# Claude Science Capability Gap Backlog

Date: 2026-07-02

This file tracks Claude Science workspace capabilities that Genomi should not
claim to support until there is a real user-facing equivalent. A "gap" here
means Genomi has no complete persisted portal feature for the same user job,
even if it has lower-level data structures, context packets, or partial
developer-facing state.

## Already Covered On This Branch

These Claude Science patterns now have Genomi equivalents in the current portal
work and should not stay on the gap list:

| Claude Science pattern | Genomi status | Reference |
| --- | --- | --- |
| Post-onboarding project chat workspace | Implemented as project/frame portal routes; `/start` is not a Genomi product route. | `screenshots/127-claude-science-project-session-workspace.png`, `screenshots/178-genomi-portal-user-facing-state-copy.png` |
| Artifact object actions for local project artifacts | Implemented for local star, hide, rename, delete, copy link, copy metadata, and metadata export. | `screenshots/166-claude-science-artifact-actions-menu.png`, `screenshots/180-genomi-fresh-evidence-report-actions-menu.png` |
| Artifact bundle downloads | Implemented as a local artifact ZIP bundle containing a manifest, public metadata JSON, and portal-owned artifact version files. | `screenshots/166-claude-science-artifact-actions-menu.png`, `screenshots/190-genomi-artifact-download-bundle-menu.png` |
| Frame/session bundle downloads | Implemented as a local frame ZIP bundle containing a manifest, frame metadata, transcript messages, attached artifact metadata, and portal-owned artifact version files. | `screenshots/191-genomi-frame-download-bundle-action.png` |
| Browser file import into workspace Library | Implemented as project-relative workspace files under `$GENOMI_HOME/workspace/<project>` plus immutable `project_file` artifact snapshots, local artifact/file preview, version metadata, attach/ask selection actions, and imported-file grouping distinct from generated records. | `screenshots/193-claude-science-library-reference-current.png`, `screenshots/195-genomi-imported-file-inline-preview.png` |
| Artifact workspace route identity | Implemented for artifact and artifact-version routes with tab state. | `screenshots/141-genomi-artifact-deep-link-route.png`, `screenshots/142-genomi-artifact-version-route.png`, `screenshots/145-genomi-artifact-tab-route.png` |
| Inline artifact provenance tabs | Partially implemented with Evidence, Tool calls, Work trail, Origin chat, Environment, Runtime, Technical state, Rebuild recipe, and Review tabs where the artifact supports those objects. The Work trail tab now renders latest bounded message-derived work-step cards plus producing-run execution cells when available, not a raw context packet. | `screenshots/140-genomi-artifact-runtime-tab.png`, `screenshots/91-genomi-artifact-origin-trace-tab.png`, `screenshots/20260703-genomi-artifact-work-trail-execution-cells-lower.png` |
| Rebuild recipe for portal-owned evidence reports | Partially implemented: Evidence report versions rendered by the portal now expose a detail-only `Rebuild recipe` tab with the operation params, host-agent handoff, and limitations. A shell command appears only when the public parameters are complete. | `screenshots/167-claude-science-artifact-provenance.png`, `screenshots/135-claude-science-artifact-provenance-code-tab.png` |
| Version-scoped rebuild script bundles | Implemented for artifact versions whose public rebuild recipe is ready. The action downloads a local ZIP with `rebuild.sh`, `rebuild-recipe.json`, `manifest.json`, and a README; no bundle is exposed when private parameters were redacted. | `exploration-log.md`, `src/genomi/interfaces/portal_artifact_bundles.py` |
| Version-owned deterministic review checks and run history | Partially implemented: artifact versions now carry a persisted Review state for snapshot metadata, evidence-envelope presence, rebuild recipe readiness, and public payload redaction. The artifact pane can run those deterministic checks for the selected version, show a browser-side `running` state while the route is in flight, and append a completed review-run history entry. | `screenshots/172-claude-science-artifact-review-tab.png`, `screenshots/139-claude-science-artifact-provenance-review-tab.png`, `screenshots/20260704-genomi-artifact-review-run-history-visible.png`, `exploration-log.md` |
| Version-owned Environment snapshot | Partially implemented: artifact versions now carry a public Environment snapshot with Genomi runtime, Python/platform fields, host-agent adapter id, package availability, and Genomi library materialization state. | `screenshots/170-claude-science-artifact-environment-tab.png`, `screenshots/138-claude-science-artifact-provenance-environment-tab.png`, `screenshots/186-genomi-artifact-environment-tab.png` |
| Producing-run navigation | Partially implemented: artifact `View in chat` can reopen the origin frame with `highlight_run` route state and highlight the producing assistant message or a tool-only work group; Work trail execution-cell links can also carry hidden `highlight_step` route state to focus the exact computed work card. | `screenshots/175-claude-science-view-in-context-result.png`, `screenshots/176-claude-science-view-in-context-work-step-visible.png` |
| User-facing science object language | Implemented enough to stop exposing context-packet mechanics in the main UI. Selected material is now composer-attached material instead of a standalone product pane. | `screenshots/185-genomi-clean-genome-index-language-cropped.png` |
| Active UI context orientation | Implemented as a prompt-safe project active-context API. The browser posts the current route, workspace pane, frame, artifact, version, and artifact tab; assistant prompts receive it as non-authoritative visible-view orientation, not evidence. | `exploration-log.md` |
| Project-scoped assistant working directory | Implemented for host-agent subprocess runs. Each browser-opened portal project gets a Genomi-owned workspace under `$GENOMI_HOME/workspace/<project>`; public project JSON and run/status payloads expose logical ownership and a `$GENOMI_HOME` path hint, not absolute local paths. Host-agent-only runs outside a portal project keep the agent's cwd and report host-agent ownership without a Genomi workspace path hint. | `exploration-log.md` |
| Host-agent produced workspace files | Implemented as a conservative post-run import slice: new or changed small files written under the project workspace become `project_file` artifacts with immutable versions, artifact events, and a `Produced files` Library group distinct from browser uploads. | `exploration-log.md` |
| Read-only project workspace file browser/search | Implemented as a project-scoped workspace files API and compact Files & Artifacts surface. It lists project-relative files grouped by project folder, generated-record identity, content type, size, search, selectable library-location filters, and linked artifact actions without exposing backend workspace roots. | `screenshots/20260704-genomi-workspace-file-folder-groups.png` |
| Native workspace file previews | Partially implemented for direct research-record inspection and chat reuse: Markdown renders as structured text, CSV/TSV as bounded tables, images/code/text as native previews, PDFs as project-scoped document frames, notebooks as bounded cell outlines, and previewed files can be included, asked about, or used to start a fresh focused conversation as typed `Project file` selected material with bounded visible details. | `screenshots/20260704-genomi-workspace-pdf-preview.png`, `screenshots/20260704-genomi-workspace-notebook-preview.png` |
| Bounded conversation transcript handoff | Implemented for one-shot host-agent subprocesses. Follow-up turns receive a bounded prompt-safe prior user/assistant transcript for continuity, explicitly labeled as non-authoritative chat context rather than Genomi tool evidence. | `exploration-log.md` |
| Reconnectable run event stream | Implemented as a frontend recovery slice. The browser tracks the last SSE event id, replays first with `after`, drains the durable `GET /api/runs/:id/event-page` contract after reconnect exhaustion, and only then checks `/api/runs/:id` status before treating a stream error as an interruption. | `exploration-log.md`, `src/genomi/interfaces/templates/portal_run_stream.js` |
| Reconnectable project event stream | Implemented as a bounded per-project SSE replay window backed by a local JSONL event log. Reopened or restarted portal processes can replay sanitized workspace events with `after` before streaming live updates. | `src/genomi/interfaces/portal_project_events.py`, `tests/test_mcp_http.py` |
| Canonical browser run-create endpoint | Implemented as `POST /api/runs` accepting project, optional frame, message, selected material, and agent id, delegating to the same project/frame run service used by the legacy submit routes. | `src/genomi/interfaces/portal.py`, `src/genomi/interfaces/templates/portal_api.js` |
| Run result package endpoint | Implemented as `GET /api/runs/:id/result-package`, returning public run status, project/frame metadata, transcript messages, frame-linked artifacts, relative workspace files, a bounded latest sanitized run-event excerpt from memory or durable logs, genome boundary state, and current active portal context. | `src/genomi/interfaces/portal_run_packages.py` |
| Read-only portal sidecar inspection | Implemented as base Genomi operations for describing the current portal workspace and retrieving a portal run result package. This lets host agents inspect portal project state without scraping browser UI or local state files. | `src/genomi/operations/registry/handlers_portal.py` |
| Portal sidecar run control | Implemented as base Genomi operations for starting a portal run, checking status, canceling an active run, and retrieving the same result package used by the web route. Sidecars route through the live portal process' project/frame run service instead of a parallel chat backend; the MCP dispatcher keeps these run-control/readback operations inline because active portal run state is process-local. | `src/genomi/operations/registry/handlers_portal.py`, `tests/test_portal_sidecar_operations.py` |
| Rich sidecar event replay | Implemented as `GET /api/runs/:id/event-page` and `genomi.retrieve_portal_run_event_page`, returning bounded sanitized run-event pages with `after_event_id`, `next_after_event_id`, source, total, truncation, and public run status. | `src/genomi/interfaces/portal_run_event_pages.py`, `tests/test_portal_sidecar_operations.py`, `tests/test_mcp_http.py` |
| Browser-visible execution-cell slice | Partially implemented in conversation and artifact Work trails. Run result packages expose normalized execution cells, and the browser merges non-duplicate diagnostic, stdout/stderr, artifact, and run-completion cells beside transcript-derived tool steps. | `src/genomi/interfaces/portal_execution_cells.py`, `src/genomi/interfaces/templates/portal_frame_trace.js`, `src/genomi/interfaces/templates/portal_artifact_work_trace_controller.js`, `tests/test_portal_frontend_frame_trace.py`, `tests/test_portal_frontend_artifact_origin_trace.py` |

## Hard Gaps: No User-Facing Genomi Equivalent Today

These are Claude Science capabilities where Genomi should not present an
action, tab, or label as if it has the same product object. Lower-level Genomi
state may exist, but there is no complete user-facing equivalent yet.

| Claude Science capability | Why Genomi has no equivalent yet | Later implementation unit |
| --- | --- | --- |
| `Export to Cloud` artifact action | Genomi only has local artifact actions. There is no provider registry, authenticated destination, export job, or persisted remote export result. | Project-scoped export providers and resumable artifact export jobs. |
| Full numbered execution-cell log | Genomi has bounded conversation and artifact Work trails that merge run-package execution cells for diagnostics, stdout/stderr, artifact updates, and run completion, and computed execution-cell links can focus a Work trail card through hidden route state. It still lacks full command source, language labels, environment labels, artifact-version links, and persisted execution-cell records. There is no complete Genomi equivalent yet. | Stable execution-cell records linked to runs, tool events, artifacts, versions, and route anchors. |
| Full artifact execution-environment snapshot | Genomi now has a minimal artifact-version Environment snapshot, but not Claude Science parity: no conda/kernel environment name, exhaustive package table, host-agent process package inventory, execution-cell dependency map, or environment operation history. | Rich execution environment records linked to execution cells, artifact versions, and host-agent process state. |
| Async reviewer/check-run lifecycle | Genomi has version-owned deterministic review checks, a user-triggered browser-side running state while checks are submitted, and completed check-run history for a selected artifact version. It still lacks backend async jobs, reviewer-agent checks, durable rerun transition streams, and richer check history beyond deterministic artifact/evidence-boundary checks. | Artifact check-run jobs keyed by artifact version, with durable running/pass/fail/warning transitions and reviewer-agent findings. |
| Full Project Library upload/session grouping | Genomi has browser file import as project-relative workspace files with artifact snapshots, host-agent produced files as project artifacts, a read-only file browser/search surface grouped and filterable by imported-file state, project folder, and generated-record identity, native previews for common research records, a Files filter, `Your uploads`, `Produced files`, run-origin generated-output groups for artifacts, and generated workspace records grouped by origin conversation when artifact provenance has a frame. It still lacks a full Library session model, long-running upload lifecycle, and richer file watcher equivalent to Claude Science Library. | Project library session metadata, richer generated-run grouping, and user-visible import/session groups. |
| Frame fork, side-chat, and handoff endpoints | Genomi selected-material cards can start a fresh portal conversation through the canonical run path, and new frames now persist a public `started_from` summary for selected files, artifacts, work steps, or evidence while hiding source-frame transport ids. Frames can also carry bounded transcript handoff, but there is still no full fork tree, side-chat pane, or branch comparison object. | Frame fork/handoff APIs with selected material, artifact links, evidence limits, AGI approval state, and user-visible branch relationships. |
| Exact run-event producing-step links | Genomi can page sanitized run events, compute execution cells for run packages, route computed cells to the corresponding Work trail card, and persist exact artifact-event anchors on produced artifact versions when the producing run emits an artifact event. It still does not persist full producing-step links to stdout/stderr panes, command cells, environment records, or every artifact path as durable execution-log records. | Stable execution-cell records with producing-step route anchors, command/source metadata, stdout/stderr panes, and environment links. |
| Generic Work trace core | Genomi currently shares the Work trail implementation through `portal_frame_trace.js`, which still owns message modeling, execution-cell adaptation, selected-context payloads, DOM rendering, and frame-branded helpers. | Split into a generic work-trace model/renderer plus narrow frame, artifact-origin, and execution-cell adapters before adding another Work trail feature. |
| Formal host-agent adapter contract | Genomi can start host-agent subprocess runs and normalize portal events, but it does not yet have Open Design-style adapter capability negotiation, runtime injection contracts, or consistent run/cancel/resume semantics across host agents. | Adapter registry with detect/capabilities/run/cancel/resume contracts, MCP/runtime injection, and user-facing troubleshooting state. |

## Partial Equivalents That Must Not Be Overclaimed

These are areas where Genomi has a useful slice, but not the full Claude
Science capability.

| Claude Science capability | Genomi partial equivalent | Missing part |
| --- | --- | --- |
| `View in context` | Artifact `View in chat` opens the origin frame with `highlight_run`, and produced artifact versions with an artifact event now carry a hidden `highlight_step` anchor for the producing Work trail card. | Exact producing tool-step links for non-artifact cells and full execution-log parity. |
| Provenance Code / reconstruction script | Portal-owned Evidence report versions now have a `Rebuild recipe` tab with a Genomi operation rebuild recipe and explicit limitations. Ready public recipes expose a version-scoped `Download rebuild script` ZIP. | Dependency input chips, exact host-agent replay boundaries, richer dependency graphs, and support across more artifact kinds. |
| Artifact work trail | Artifact provenance renders the latest bounded message-derived tool work, non-duplicate run-package execution cells, and a version-owned `Produced artifact` work step with an exact artifact-event anchor when available. | Not an Execution Log: artifact provenance still lacks command source, language/environment labels, stdout/stderr panes, and stable records for every execution step. |
| Provenance Review | Artifact versions now persist deterministic review checks. The Review tab renders those checks beside the review handoff brief, `Run review checks` shows a pending browser state while the route is in flight, and completed runs append a version-scoped check-run history entry. | Backend async job transitions, reviewer-agent checks, richer check history, and renderer/library validation checks. |
| Provenance Environment | Artifact versions now persist a minimal Environment snapshot and render it as an artifact tab. | Full host-agent process environment, conda/kernel labels, package-operation history, dependency graph, and exhaustive package table. |
| Provenance pane | Genomi has Evidence, Rebuild recipe, Tool calls, Work trail, Origin chat, Environment, Runtime, Technical state, and Review tabs where the artifact supports those objects. | Execution Log, full environment package table, dependency graph, and real check-run lifecycle tabs. |
| Artifact bundle download | Genomi has a local artifact ZIP with manifest, metadata, and portal-owned version files, plus ready public rebuild-script ZIPs for supported artifact versions. | Upload/import grouping and remote export state. |
| Frame/session bundle download | Genomi has a local frame ZIP with manifest, frame metadata, messages, attached artifact metadata, and portal-owned artifact version files. | Background/resumable bundle jobs and richer Claude Science Library grouping if later needed. |
| Workspace file/library pane | Genomi has an artifact workspace, project artifact routes, browser file imports written into the project workspace, host-agent produced-file import, read-only workspace file browser/search grouped and filterable by imported-file state, project folder, and generated-record identity, origin-conversation grouping for generated workspace records, a Files filter, `Your uploads` and `Produced files` grouping, native Markdown, CSV/TSV table, code, image, text, PDF document, and notebook-outline previews, `Project file` selected-material handoff actions, artifact bundle downloads, ready public rebuild-script downloads, and frame/session bundle downloads. | Full Library session model, cloud-backed library/export state, PDF annotation/search, full notebook execution/history, and richer file grouping parity. |
| Active UI context | Genomi has prompt-safe current-view orientation for route, pane, frame, artifact, version, and artifact tab. | No visible DOM-node selection stream, active viewport summary, or richer active-context inspector. Explicit composer attachments remain the authoritative evidence handoff. |
| Project file browser/search | Genomi has read-only project-relative file listing and search for the Genomi-owned workspace, bounded file previews, chat-routed `Project file` selected material, and a PDF document stream limited to project-scoped document previews. | No nested folder browser, general file content API independent of artifacts, selective write flow, richer watcher, or external/folder-backed workspace contract. |
| Selected-material conversation branch | Genomi can use a selected file, evidence item, work step, or artifact as bounded selected material for a fresh portal conversation through the same browser and sidecar run contract. The new conversation remains a normal visible root conversation and carries a public `Started from ...` summary in the frame list. | No full frame-fork object, side-chat pane, user-visible branch comparison, or transcript-synthesis API beyond selected material and bounded prior-message context. |
| Daemon-style run API | Genomi has browser chat submission through `POST /api/runs`, `GET /api/runs/:id`, run SSE, cancel, durable sanitized run-event logs, `GET /api/runs/:id/event-page`, `GET /api/runs/:id/result-package`, and base sidecar operations for workspace inspection, start, poll, cancel, event-page retrieval, and run-package retrieval. Artifact versions now retain exact artifact-event anchors where available. | Sidecars still lack full execution-cell records and richer CLI packaging around the base operations. |

## Capability Details

### Artifact Cloud Export

Claude Science exposes `Export to Cloud` as an artifact object action.

Evidence:

- `screenshots/166-claude-science-artifact-actions-menu.png`
- `screenshots/134-claude-science-artifact-actions-menu.png`

Current Genomi state:

- Genomi has local artifact actions and local metadata export.
- Genomi has no authenticated/cloud destination model, no export job state, and
  no persisted cloud export result attached to the artifact.

Future implementation shape:

- Add a project-scoped export provider registry.
- Start export as a resumable background job.
- Attach export status, destination label, and resulting URI to the artifact
  without leaking credentials.

### Reproducible Artifact Code

Claude Science's Provenance Code tab shows generated reconstruction code,
inputs, and a script download action for an artifact.

Evidence:

- `screenshots/167-claude-science-artifact-provenance.png`
- `screenshots/135-claude-science-artifact-provenance-code-tab.png`

Current Genomi state:

- Genomi records evidence reports, artifact versions, origin messages, runtime
  facts, and work traces.
- Portal-owned Evidence report versions now persist a public rebuild recipe
  with the Genomi operation, safe parameters, host-agent handoff, and
  limitations. Executable shell commands are shown only when the public
  parameter set is complete enough to replay honestly.
- Genomi now attaches a downloadable rebuild-script ZIP when the artifact
  version has a ready public rebuild recipe. The bundle contains `rebuild.sh`,
  `rebuild-recipe.json`, `manifest.json`, and a README.
- Genomi does not yet attach dependency input chips, a complete reproducible
  dependency graph, or support this across every artifact kind.

Future implementation shape:

- Extend script bundles with explicit dependency/input manifests when the
  underlying artifact records support them.
- Preserve the current honesty boundary: expose script download only when the
  public rebuild recipe is complete enough to replay without private inputs.

### Cell-Level Execution Log

Claude Science renders command-like work as numbered execution cells with
source, output, language/environment labels, and expandable output.

Evidence:

- `screenshots/168-claude-science-artifact-execution-log.png`
- `screenshots/136-claude-science-artifact-provenance-execution-log-tab.png`
- `screenshots/129-claude-science-session-step-stack.png`
- `screenshots/130-claude-science-step-command-detail.png`
- `screenshots/131-claude-science-step-output-expanded.png`

Current Genomi state:

- Genomi has latest bounded work-trail provenance: run events, grouped work
  traces, tool chips, diagnostic chips, artifact Work trail cards, run-package
  execution cells, and browser Work trail rendering for non-duplicate
  diagnostic, stdout/stderr, artifact, and run-completion cells.
- Artifact Work trail cards are now useful for inspecting and reusing visible
  producing tool work from the stored message slice plus producing-run
  execution cells. They are intentionally still labeled as work trail, not
  Execution Log.
- Genomi does not yet persist a complete execution-cell table that can replay
  command source, language/environment labels, and producing artifact/version
  route anchors.

Future implementation shape:

- Promote computed run-package execution cells into stable execution-cell
  records owned by the portal run presentation layer.
- Link cells to run ids, frame ids, tool events, artifacts, artifact versions,
  command/source metadata, and route anchors.
- Render cells in artifact provenance without dumping raw logs into assistant
  answers.

### Runtime And Package Environment Snapshot

Claude Science attaches runtime environment details to artifact provenance,
including environment name, Python version, package count, and package table.

Evidence:

- `screenshots/170-claude-science-artifact-environment-tab.png`
- `screenshots/138-claude-science-artifact-provenance-environment-tab.png`
- `screenshots/186-genomi-artifact-environment-tab.png`

Current Genomi state:

- Genomi has a Runtime tab oriented around evidence boundaries, defaults,
  source coverage, and artifact version metadata.
- Artifact versions now persist a minimal Environment snapshot with Genomi
  version, Python/platform runtime fields, host-agent adapter id when known,
  selected package availability, and Genomi library materialization state.
- Genomi still does not persist a complete Claude Science-style environment
  object: no conda/kernel environment name, exhaustive host-agent package table,
  environment operation history, or execution-cell dependency graph.

Future implementation shape:

- Extend the current artifact-version Environment snapshot only where it helps
  reproduce or inspect the artifact.
- Add host-agent process package capture and execution-cell dependency links
  once normalized execution cells exist.
- Keep this evidence-native: package inventory should explain artifact
  reproducibility, not become a generic machine audit.

### Structured Review And Check Runs

Claude Science has a Review tab even when no checks have run, preserving review
as a first-class artifact state.

Evidence:

- `screenshots/172-claude-science-artifact-review-tab.png`
- `screenshots/139-claude-science-artifact-provenance-review-tab.png`

Current Genomi state:

- Genomi has review summaries, evidence-envelope interpretation boundaries,
  and deterministic review checks persisted on artifact versions.
- Genomi now has a user-triggered `Run review checks` action for selected
  artifact versions. It re-evaluates the stored deterministic artifact and
  evidence-boundary checks, updates the version's Review state, and appends a
  completed review-run history entry.
- The browser shows a pending `running` review run and disables the menu action
  while the review route is in flight.
- Genomi Library cards now surface the current artifact-version review status
  from the artifact list endpoint, so users can see `Review passed`, warnings,
  or failures before opening the artifact detail pane.
- Genomi does not yet have backend async artifact check jobs with durable
  transition streams, reviewer-agent findings, or richer renderer and library
  validation checks.

Future implementation shape:

- Extend deterministic checks to missing-library states and renderer
  validation.
- Add async check-run jobs keyed by artifact version with running/completed
  state transitions and history.
- Render review state beside evidence limits without implying clinical
  certification.

### Exact Producing-Step Navigation

Claude Science's `View in context` returns from an artifact to the producing
project frame and keeps the relevant work/artifact context visible.

Evidence:

- `screenshots/175-claude-science-view-in-context-result.png`
- `screenshots/176-claude-science-view-in-context-work-step-visible.png`

Current Genomi state:

- Genomi has artifact origin messages, origin trace, `View in chat`, and
  workspace artifact routes.
- Genomi can now carry the artifact's stored producing run id into the frame
  route as `highlight_run` and highlight either the producing assistant message
  or, for tool-only runs, the run's rendered work group in the transcript.
- Run-package execution cells now unpack nested artifact events into safe
  artifact identity and workspace-route metadata, and Work trail cards expose
  `View in chat` / `Open artifact` actions when that object navigation exists.
- Artifact-local Work trail filters concrete sibling artifact cells from shared
  runs so a selected artifact does not display another artifact's produced
  result as if it belonged to the selected object.
- Computed Work trail execution-cell rows can now deep-link back to the origin
  frame with hidden `highlight_step` route state, opening the Work trail pane
  and focusing the exact computed card when that card is available.
- Artifact versions now persist a bounded producing work-step record and the
  artifact Work trail tab renders it as `Produced artifact`.
- When a portal run emits an artifact event, Genomi now records that event id
  and matching artifact execution-cell id on the produced artifact version, so
  `View in chat` can carry hidden `highlight_run` and `highlight_step` route
  state to the producing Work trail card.
- Genomi does not yet persist exact producing tool event ids or normalized
  execution-cell ids for non-artifact cells as full execution-log records.

Future implementation shape:

- Extend the current `highlight_step` route focus from computed Work trail
  cards and artifact-event anchors to version-owned execution-cell records.
- Scroll and highlight the producing work group without requiring users to
  manually select or attach a context packet.

### Library Uploads And Bundles

Claude Science's project Library is not only a generated-artifact list. The
inspected bundle and UI expose upload/session grouping, artifact download
controls, frame/session bundle downloads, and artifact-version script-bundle
downloads.

Evidence:

- `screenshots/164-claude-science-project-library-files-pane.png`
- `screenshots/62-claude-science-library-pane.png`
- `exploration-log.md` references `downloadSessionBundle -> GET
  /frames/:id/bundle` and `downloadScriptBundle -> GET
  /artifacts/:versionId/script-bundle`.

Current Genomi state:

- Genomi has generated artifacts, artifact routes, local file preview/open
  links, metadata export, copy-link actions, local artifact ZIP bundles, and
  local frame/session ZIP bundles.
- Genomi has browser file import into `project_file` artifacts with a Files
  filter, inline text-file preview, and a distinct `Your uploads` group.
- Genomi imports new or changed small files written by successful host-agent
  runs under the project workspace into `project_file` artifacts with a
  distinct `Produced files` group.
- Genomi exposes a read-only project-relative workspace file browser/search
  surface, renders Markdown and CSV/TSV tables as readable research records
  instead of raw preformatted text, and links files back to their Genomi
  artifact when a snapshot exists.
- Genomi exposes ready public rebuild-script ZIPs from artifact actions when
  an artifact version has a complete public rebuild recipe.
- Genomi groups generated artifacts by assistant turn when public artifact
  origin metadata includes a producing run. It still has no folder/session
  grouping, long-running upload lifecycle, or richer file watcher.

Future implementation shape:

- Add project library grouping metadata that distinguishes uploaded/imported
  files from generated session artifacts without mixing them into evidence
  claims.
- Add richer bundle-generation jobs only if direct local ZIP generation becomes
  too slow or needs remote/export state.
- Add version-owned script bundles only when the Code/rebuild recipe has a
  complete dependency/input manifest.

## Product Rule

Do not approximate any missing item by exposing raw context payloads,
`selectedEvidence`, internal packet ids, or debug JSON to the end user. If
Genomi lacks the product object, the docs should say it is missing and the UI
should either omit the action or label it as unavailable until the real feature
exists.

### Workspace-Scoped Genome Authorization

Current Genomi state:

- The portal persists a project-scoped AGI identity and approval time without
  copying private AGI records into project state.
- Browser context, prompt composition, and host-agent MCP processes all receive
  the same project binding. An unbound project explicitly disables default-user
  auto-selection.
- Switching projects restores that project's selected genome or shows `Choose
  active genome`; it also clears the previous project's transcript and selected
  material before loading the target workspace.
- Live paired host-agent checks returned `george` in the bound project and no
  active genome in the unbound project.

Remaining implementation shape:

- Add a visible remove/clear action only when the product has a deliberate
  workflow for returning a genome-enabled workspace to public-only state.
- Keep cross-project isolation in the HTTP and host-agent regression suites as
  additional runtimes are added.

### Conversation Identity And Navigation

Current Genomi state:

- Conversations are durable, reopenable, and have a persisted prompt-safe
  title separate from the original request.
- The active title appears in the chat header and rail, rename persists through
  the server-owned frame contract, and bounded rail search matches titles and
  original display requests.
- Conversation bundle download remains in the secondary action menu.

Remaining implementation shape:

- Add move, archive, or delete only when each has real persisted state,
  project-boundary semantics, and a recovery path.
- Consider recency grouping only when conversation volume makes it useful;
  search and the selected-first ordering are sufficient for the current local
  workspace scale.

### Artifact Viewing Hierarchy

Current Genomi state:

- A file row opens a focused quick preview without leaving the producing
  conversation or destroying the library state.
- Generated-record details and origin chat are secondary actions under More.
- Promoting a generated record to its artifact view replaces the file list,
  keeps chat visible, restores the active conversation on direct artifact
  routes, and provides `Back to files`.
- Single-version selectors, affirmative readiness badges, duplicate result
  history, and successful-review badges are omitted from the default surface.

Remaining implementation shape:

- Add a true tab model for Files and multiple simultaneously opened artifacts
  only when the portal has persisted open-object state worth restoring.
- Add fullscreen and download controls to quick preview when those operations
  are backed consistently for every supported file renderer.
- Consolidate the plain-file preview and generated-artifact inspector into one
  selected-object shell without weakening artifact provenance, source limits,
  review warnings, or Active Genome Index privacy boundaries.

### Conversation Reviewer

Current Genomi state:

- A manual `Request review` action runs a real host-agent review over the
  bounded current conversation and its research-step evidence.
- The review is persisted as a conversation object with running, findings,
  clear, inconclusive, and failed states. Actionable findings link to their
  source message and can be attached to the next chat turn.
- Successful checks are counted without creating `Review passed` noise, and
  reviewer findings use user-facing genome and evidence language.

Remaining implementation shape:

- Add an optional automatic review policy only after its trigger, cost, and
  interruption behavior are explicit workspace settings.
- Support a distinct reviewer agent/model preference rather than always using
  the conversation's installed host agent.
- Add a reviewer transcript only when the portal persists a bounded,
  user-readable review conversation rather than exposing adapter output.
- Keep deterministic artifact checks separate; add artifact-specific agent
  review only when it can cite artifact versions, code, environment, and source
  records directly.
- External source verification remains a capability gap when the reviewer has
  no backed source access for a claim.

### Portal Controller And Presentation Model Decomposition

Current Genomi state:

- The portal has accumulated route, workspace, conversation/run, artifact,
  evidence-source, and DOM lifecycle ownership in the main browser controller.
- The message surface combines event replay, tool-record reduction,
  permission actions, diagnostic aggregation, and DOM rendering in one
  stateful subsystem.
- Workspace-file and artifact identity still accepts legacy aliases and, for
  old unlinked records, may recover identity from display metadata.
- Several frontend tests assert source layout or maintain separate handwritten
  DOM shims instead of sharing a behavior-oriented browser harness.

Required implementation shape:

- Extract route/workspace, conversation/run, artifact, and evidence-source
  controllers behind explicit inputs and outputs, leaving the main portal
  module as a composition root.
- Split message event reduction into a pure replay model and keep permission,
  work-trail, and message rendering as focused views over that model.
- Make the server-owned workspace projection the only source of canonical
  `relative_path`, `artifact_id`, `record_type`, and `file_kind` identity, then
  remove display-text and alias-based deduplication.
- Consolidate frontend test support around observable behavior and a shared DOM
  or real-browser harness before the next large presentation refactor.

This is an architectural milestone, not a reason to pause feature work. Apply
bounded correctness fixes immediately when prose parsing or duplicated policy
can change user-visible behavior; schedule the broader extraction around a
stable portal contract.

### Assistant Permission Scope

Current Genomi state:

- Permission requests pause the conversation as `Needs approval`, remain
  visible despite later status updates, and resume the same user turn.
- Duplicate permission failures from one blocked run are consolidated to the
  first actionable request.
- `Allow for this workspace` persists the exact approved host-agent tool and
  passes it to subsequent runs in that workspace without exposing it in the
  public project payload.

Remaining implementation shape:

- Add conversation-only scope when a transient permission record and revocation
  behavior are defined.
- Add connector-family scope only when tool families have a canonical server
  identity; do not infer families from display labels.
- Add a workspace permission settings surface before offering broad or global
  allowances, so users can inspect and revoke what they granted.
