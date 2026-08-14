# Screenshot Index

These screenshots were captured from the live in-app browser while inspecting
the authenticated Claude Science project. They are reference images for the UI
states described in `exploration-log.md`.

## 2026-07-16 Paired Generated-Report Flow

![Local reference home](screenshots/20260716-local-reference-home.jpg)

The authenticated local home is intentionally sparse: project entry, search,
and recent sessions lead directly into work rather than a dashboard.

![Local reference file library beside the conversation](screenshots/20260716-local-reference-files-library.jpg)

Opening Files preserves the conversation and adds a restrained artifact
library. The generated report remains the object of interest; search, layout,
and actions stay secondary.

![Genomi generated report appears during the live run](screenshots/20260716-genomi-live-generated-report.jpg)

The generated Markdown card appeared while the host-agent run still showed as
processing. This is the browser proof that successful file writes are now
materialized incrementally rather than only after process exit.

![Genomi chat-primary research workspace](screenshots/20260716-genomi-chat-primary-workspace.jpg)

The completed answer is rendered as readable Markdown, its generated file is
attached directly beneath the turn, and the default workspace does not keep a
second files dashboard permanently open.

![Genomi report opened beside its origin chat](screenshots/20260716-genomi-origin-chat-report-split-view.jpg)

Opening the generated report produces the adapted split workspace: chat stays
visible while the report renders as a document. Primary tabs are limited to
Preview, File details, Origin chat, and Work trail because those objects are
actually backed by Genomi state.

## Public Claude Science Product Page

![Claude Science public hero](screenshots/20260703-claude-science-public-hero-clean.png)

Public product-page hero. The main capability promise is not a dashboard: it is
a research partner that runs analyses, searches databases, and traces work from
data wrangling through publication.

![Rich artifacts and provenance](screenshots/20260703-claude-science-public-rich-artifacts-user-supplied.png)

User-supplied public-page capture showing the most important artifact pattern:
generated figures/tables/notebooks sit beside Code, Execution Log, Messages,
Environment, and Review tabs. This is the clearest target for Genomi artifact
provenance.

![Compute and persistent kernels](screenshots/20260703-claude-science-public-compute-user-supplied.png)

User-supplied public-page capture showing compute as a visible research-run
object: jobs, tables, plots, notebooks, and live kernels remain in the same
workspace rather than becoming hidden diagnostics.

![Domain-ready science tooling](screenshots/20260703-claude-science-public-domain-ready-user-supplied.png)

User-supplied public-page capture showing domain-ready tooling: literature
retrieval, skills/tools, reviewer findings, and rendered PDFs live together
with the conversation and file library.

## Conversation, Artifact Tray, And Split Pane

![Conversation with generated artifacts and split image pane](screenshots/01-live-conversation-artifact-tray.png)

Shows the research conversation, generated artifact tray, bottom composer, and
an opened image artifact in the right split pane. This is the core workspace
shape Genomi should emulate: chat and artifacts remain visible together.

## Artifact Split Pane

![Image artifact split pane](screenshots/02-live-artifact-split-image.png)

Shows an opened generated image artifact with its pane-level controls:
artifact tab, more-actions menu, maximize, download, and close.

## Artifact Actions Menu

![Artifact actions menu](screenshots/03-live-artifact-actions-menu.png)

Shows the artifact action menu: Star, Hide, View in context, Provenance, Copy
link, Rename, Export Metadata, Export to Cloud, and Delete. Genomi should
prioritize View in context, Provenance, Copy link, typed export, and download.

## Provenance: Code

![Provenance code tab](screenshots/04-live-provenance-code-tab.png)

Shows inline artifact provenance in the split pane. The Code tab includes a
download-script action, generated reconstruction text, input artifact chips,
and reconstructed source code.

## Provenance: Execution Log

![Provenance execution log tab](screenshots/05-live-provenance-execution-log-tab.png)

Shows raw execution cells that produced the artifact. This is the closest
Claude Science equivalent to a replayable tool/work trace.

## Provenance: Messages

![Provenance messages tab](screenshots/06-live-provenance-messages-tab.png)

Shows the transcript slice that led to the artifact. Genomi should expose the
host-agent turns and Genomi MCP tool results that produced each artifact.

## Provenance: Environment

![Provenance environment tab](screenshots/07-live-provenance-environment-tab.png)

Shows runtime environment state: Python version, package table, and environment
operations. Genomi's analogous tab should show Genomi version, library status,
Active Genome Index approval/context state, and source coverage.

## Provenance: Review

![Provenance review tab](screenshots/08-live-provenance-review-tab.png)

Shows the artifact review/check state. In the inspected run no checks had run
yet. Genomi should map this to evidence-envelope validation, negative-inference
warnings, clinical safety gates, and artifact checks.

## Genomi Portal Checkpoint

These screenshots were captured from the live in-app browser against the local
Genomi portal at `http://localhost:8767/` after applying the artifact-workspace
layout and provenance-tab work.

![Genomi portal initial workspace](screenshots/09-genomi-portal-initial.png)

Initial portal load. CSS is active, the artifact tray exists, and no selected
artifact pane is rendered until an artifact is available.

![Genomi desktop initial workspace](screenshots/10-genomi-portal-desktop-initial.png)

Desktop viewport sanity check. The two-column workspace is present, with chat
on the left and the right stack available for artifacts and utility panes.

![Genomi artifact preview before layout cleanup](screenshots/11-genomi-artifact-preview.png)

Artifact fixture opened in the split pane. This verified that the new artifact
tray, split-right pane, preview tab, evidence tab, tools tab, state tab, and
review tab all render from a persisted portal artifact.

![Genomi artifact provenance tab](screenshots/12-genomi-artifact-evidence-tab.png)

Provenance tab showing artifact provenance nodes: artifact id, kind, renderer,
source operation, status, timestamps, summary, and artifact URL.

![Genomi artifact tools tab](screenshots/13-genomi-artifact-tools-tab.png)

Tools tab showing the operation trace: source operation, renderer, kind, status,
timestamps, preview URL, and open URL.

![Genomi artifact state tab](screenshots/14-genomi-artifact-state-tab.png)

State tab from the earlier artifact fixture, now treated as report section
state in the current UI contract rather than dashboard panel state.

![Genomi artifact review tab before header fix](screenshots/15-genomi-artifact-review-tab.png)

Review tab before the header layout fix. The screenshot captured title
clipping caused by the metrics squeezing the title column.

![Genomi artifact-first workspace](screenshots/16-genomi-artifact-first-class-workspace.png)

Updated workspace with Artifacts as the first right-side pane. This removes the
product-explainer panel from the primary workspace and keeps chat plus artifact
preview visible together.

![Genomi artifact review tab after header fix](screenshots/17-genomi-artifact-review-tab-fixed.png)

Review tab after the artifact header/metric layout fix. The title now has the
full pane width, and review nodes remain selectable.

![Genomi mobile artifact final](screenshots/21-genomi-portal-mobile-final.png)

Final narrow-viewport checkpoint. Browser-side layout audit reported no
document-level horizontal overflow; only the provenance tab strip is
intentionally horizontally scrollable.

![Genomi artifact workspace before open-design follow-up](screenshots/22-genomi-live-artifact-workspace-before-open-design-followup.png)

Live in-app browser checkpoint before adding the project-level event stream.
This is the artifact-first workspace state used as the visual baseline for the
open-design architecture follow-up.

![Genomi project event stream after reload](screenshots/23-genomi-project-event-stream-after-reload.png)

Live in-app browser checkpoint after restarting the Genomi portal with
`portal_project_stream.js` active. Server logs showed the browser loading
`/api/projects/proj_4eff6d75d3f7/events`, a direct stream read returned a
`ready` SSE frame, and the browser console had no warnings or errors.

![Genomi renderer registry after reload](screenshots/24-genomi-renderer-registry-after-reload.png)

Live in-app browser checkpoint after adding the operation-keyed Genomi result
renderer registry. The artifact workspace still renders with the dark Genomi
visual language, the provenance preview remains open, and the browser console
reported no warnings or errors after reload.

![Genomi bounded project events after reload](screenshots/25-genomi-bounded-project-events-after-long-preview-wait.png)

Live in-app browser checkpoint after bounding project-event replay and
normalizing store-side workspace invalidation. The restarted portal rendered
the artifact workspace and dashboard preview, and the browser console reported
no warnings or errors after reload.

![Claude Science workspace before CYP2C19 prompt](screenshots/26-claude-science-workspace-before-question.png)

Claude Science post-onboarding workspace before the public pharmacogenomics
comparison prompt. The page shows the existing project transcript, generated
artifacts, a notebook entry point, and a contenteditable composer.

![Claude Science CYP2C19 response](screenshots/28-claude-science-cyp2c19-followup-state.png)

Claude Science after the CYP2C19/clopidogrel prompt. It answered concisely and
organized evidence sources into an ordered inspection list without starting a
long analysis.

![Genomi CYP2C19 response before checklist adaptation](screenshots/31-genomi-cyp2c19-followup-state.png)

Genomi after the same prompt routed through the local host-agent bridge. The
answer was useful, but the evidence-to-inspect section was still plain text at
this point.

![Genomi assistant evidence checklist](screenshots/32-genomi-assistant-evidence-checklist.png)

Genomi after adapting the comparison lesson: explicit assistant evidence plans
now render as selectable evidence-checklist nodes inside the chat transcript.

![Genomi assistant evidence checklist attached](screenshots/33-genomi-assistant-evidence-checklist-attached.png)

The selected "Variant-level rows" checklist node attached to the next-turn
context tray as an assistant evidence checklist packet.

## Genomi Server-Owned Candidate Evidence

![Candidate evidence expanded result header](screenshots/20260703-genomi-candidate-evidence-server-presentation-viewport-verified.png)

Expanded candidate-evidence tool card showing the server-owned result header,
metrics, and compact work-step context inside the chat transcript.

![Candidate evidence lanes](screenshots/20260703-genomi-candidate-evidence-lanes-top-verified.png)

Visible candidate-evidence lanes after reload: candidate comparison,
supporting evidence, evidence boundary, and coverage limits. Candidate and
supporting-source nodes are selectable; boundary and coverage remain
display-only interpretation context.

![Server-owned candidate evidence after review fixes](screenshots/20260703-genomi-candidate-evidence-server-owned-post-review.png)

Post-review checkpoint after removing the browser candidate fallback. The
expanded result still shows candidate/support/boundary/coverage lanes, while
the compact work-step label is driven by the real capability operation rather
than the `genomi.invoke` transport wrapper.

![Genomi assistant evidence checklist after parser fix](screenshots/34-genomi-assistant-evidence-checklist-after-parser-fix.png)

Final reload after tightening the checklist parser to only accept explicit
"Evidence I would inspect" headings. The same checklist renders, the selected
context remains attached, and the browser console reported no warnings or
errors.

![Genomi focused Ask from evidence checklist](screenshots/35-genomi-focused-ask-from-evidence-checklist.png)

The selected assistant evidence checklist node is no longer just passive
context. Pressing Ask generates a focused next-turn prompt that tells the host
agent to choose the smallest relevant Genomi tool calls and preserve
`evidence_envelope` limits.

![Genomi focused Ask follow-up in progress](screenshots/36-genomi-focused-ask-followup-state.png)

The focused follow-up streams back through the same Genomi web chat surface,
with host-agent output, tool chips, and the evidence ledger staying attached to
the project frame.

![Genomi focused Ask completed state](screenshots/37-genomi-focused-ask-completed-state.png)

Completed focused follow-up after reload. The evidence-derived user turn and
the host-agent response are persisted in the frame, confirming the portal is
projecting host-agent state rather than acting as a separate LLM client.

![Genomi persisted result view before selection](screenshots/38-genomi-persisted-result-view-before-selection.png)

Persisted `variant.resolve` tool history now keeps a sanitized presented payload
for canonical evidence results, so the purpose-built Variant Evidence Map can
render after reload instead of falling back to raw text only.

![Genomi full result selection inspector](screenshots/39-genomi-result-selection-inspector.png)

Full-page capture of the selected-result-node state. It is useful as a layout
audit, though the fixed workspace makes the viewport capture clearer.

![Genomi result selection inspector viewport](screenshots/40-genomi-result-selection-inspector-viewport.png)

Viewport capture of the new result selection inspector. Selecting a ClinVar node
keeps the node highlighted and shows the selected lane, label, and redacted
context immediately below the result map.

![Genomi persisted redacted workspace](screenshots/45-genomi-persisted-redacted-result-view.png)

Post-review checkpoint after restarting the Genomi portal with the tightened
persisted-history contract. The workspace opens directly to the research chat;
the `variant.resolve` chip is present and `/start` is not part of the product
route.

![Genomi persisted redacted expanded result](screenshots/46-genomi-persisted-redacted-expanded-result.png)

Expanded persisted `variant.resolve` history. The result is inspectable, carries
the `Persisted redacted history` notice, shows only public `Resolved` and
`ClinVar` metrics, and omits attach/copy actions.

![Genomi persisted redacted selection inspector](screenshots/47-genomi-persisted-redacted-selection-inspector.png)

Selecting a public result node opens the in-place inspector with lane, label,
and redacted context. Persisted history remains non-attachable; this is an
inspection affordance, not a prompt-context shortcut.

![Genomi artifact context focused prompt](screenshots/48-genomi-artifact-context-focused-prompt.png)

The selected-context tray now turns an attached artifact packet into a focused
composer prompt. The visible chip keeps the artifact identity, while the draft
asks the host agent to preserve provenance and evidence limits before choosing
the next follow-up step.

![Genomi ledger re-check focused prompt](screenshots/49-genomi-ledger-recheck-focused-prompt.png)

The evidence ledger now treats persisted-redacted tool history as a re-check
handoff. Pressing `Re-check tool` drafts a prompt that asks the host agent to
rerun current Genomi evidence before making claims, with no selected context
chip attached.

![Genomi evidence report artifact preview](screenshots/50-genomi-evidence-packet-artifact-preview.png)

The first Genomi-native `evidence_packet` artifact renderer, produced by
`research.build_target_packet` rather than the legacy Decode dashboard. The
preview iframe shows target, finding state, readiness, source catalog count,
stored evidence count, and the relevant source sections. Follow-up operation
routes are no longer primary report lanes.

![Genomi evidence report artifact state](screenshots/51-genomi-evidence-packet-artifact-state.png)

The same evidence report in the artifact State tab after the thermo-nuclear
review fix. The structured state model reuses the canonical target-packet lanes:
Target and Source catalog.

![Genomi artifact version provenance shell](screenshots/52-genomi-artifact-version-provenance.png)

Full-page capture from the first artifact-version visual check. It confirms the
portal shell and generated artifact tray are still in the dark Genomi workspace
language, though the viewport capture below is the clearer artifact-provenance
reference.

![Genomi artifact version provenance detail](screenshots/53-genomi-artifact-version-provenance-detail.png)

The artifact provenance tab after adding immutable version metadata. The
provenance grid shows the latest version id, version count, content type,
checksum, and size while keeping local filesystem paths out of the browser
payload.

![Genomi artifact version file URL preview](screenshots/54-genomi-artifact-version-file-url-detail.png)

Post-review reload after making artifact versions the canonical file owner. The
Preview tab still renders the evidence report, with the DOM already carrying
the immutable version-file URL instead of the artifact-latest URL.

![Genomi artifact version file URL evidence tab](screenshots/55-genomi-artifact-version-file-evidence-tab.png)

The corrected provenance tab. `Artifact URL` now points at
`/api/artifacts/versions/ver_458a2c0ea7f0/file`; the old artifact `/file` route
is only a latest convenience and is not the provenance URL shown to the user.

![Genomi artifact hydrated version history](screenshots/56-genomi-artifact-hydrated-version-history.png)

The artifact split pane after adding detail/version hydration on open. Project
artifact cards still come from lightweight summaries, but the provenance tab now
shows `Version history` and `Version ids` loaded from the explicit artifact
version API.

![Genomi artifact Ask selected action](screenshots/57-genomi-artifact-ask-selected-action.png)

The artifact provenance tab with selected provenance nodes. The selection bar now
has `Use selection` for attaching the selected packet and `Ask selected` for
sending that selected evidence directly into the next host-agent turn.

## Current UX Subagent Pass

![Genomi current workspace after UX subagent pass](screenshots/208-genomi-current-workspace-ux-subagent-pass.png)

Live workspace baseline captured during the independent UX alignment pass. The
primary view is the chat plus Files & Artifacts workspace; setup and technical
surfaces stay secondary.

![Genomi workspace details expanded after UX subagent pass](screenshots/209-genomi-workspace-details-expanded-ux-subagent-pass.png)

Expanded secondary navigation showing Work trail, Genome state, and Source
lookup setup as workspace details rather than the default research path.

![Genomi live result Ask selected action](screenshots/58-genomi-live-result-ask-selected.png)

A live streamed `variant.resolve` result, using the operation-specific evidence
map rather than persisted history. One result node is selected, the inspector is
visible, and the live result actions include `Use selected view`, `Copy view`,
and `Ask selected`.

![Genomi live result Ask selected submitted](screenshots/59-genomi-live-result-ask-submitted.png)

After pressing `Ask selected`, the portal submits the next host-agent turn from
the selected result node. The user message shows the generated focused prompt,
the host-agent bridge reports `1 selected evidence item`, and the message
includes an `Evidence attached` chip for `rs429358`.

![Claude Science rs429358 answer tail](screenshots/41-claude-science-rs429358-evidence-lanes.png)

First Claude Science comparison capture after asking a matching rs429358 prompt.
The artifact pane was still open, so the evidence answer was partially obscured.

![Claude Science rs429358 lane list with artifact pane](screenshots/42-claude-science-rs429358-evidence-lanes-visible.png)

Second Claude Science capture with the answer tail visible, still constrained by
the open artifact split pane.

![Claude Science rs429358 transcript answer](screenshots/43-claude-science-rs429358-transcript-evidence-lanes.png)

Claude Science transcript after closing the artifact split pane. This shows the
public rs429358 answer body in the conversation workspace.

![Claude Science rs429358 evidence lane list](screenshots/44-claude-science-rs429358-lane-list.png)

Claude Science lane-list capture for the comparable prompt. It again turns a
science answer into explicit evidence lanes, which Genomi now maps into
selectable, inspectable result nodes when a Genomi tool result is present.

## Second-Pass Claude Science Project Workspace

These screenshots were captured during the second authenticated visible-browser
pass through the Claude Science project workspace. They are the reference set
for the Library, artifact split-pane, provenance, execution-log, and
message-lineage notes added after the first `/start` detour was discarded.

![Genomi current workspace before returning to Claude Science](screenshots/60-browser-current-state.png)

Starting checkpoint in the local Genomi portal. A selected result node is
attached to the next host-agent turn, the generated follow-up was submitted
from the web UI, and the artifact tray remains visible beside the chat. This is
the Genomi-side state being compared against Claude Science's mature project
workspace.

![Claude Science project workspace reopened](screenshots/61-claude-science-project-reopen.png)

Authenticated Claude Science project route after reopening
`/projects/proj_65ee842cd510`. The useful surface is the project workspace:
transcript, session controls, library entry point, grouped tool activity, and
composer. This confirms again that `/start` is not the relevant product model.

![Claude Science Library pane](screenshots/62-claude-science-library-pane.png)

The Library pane opened from the project workspace. It exposes search, layout
controls, upload grouping, task grouping, artifact cards, split-open actions,
download controls, and per-artifact menus. The Library is not separate from the
chat; it is a project artifact projection attached to the same frame history.

![Claude Science artifact opened from Library](screenshots/63-claude-science-library-artifact-split.png)

`benchmark_figure.png` opened from the Library in the split artifact pane. The
artifact can be inspected without leaving the project transcript, and the pane
keeps open-in-split, download, more-actions, and close controls close to the
artifact content.

![Claude Science split artifact action menu](screenshots/64-claude-science-split-artifact-actions.png)

The split artifact action menu contains Star, Hide, View in context,
Provenance, Copy link, Rename, Export Metadata, Export to Cloud, and Delete.
The Genomi-relevant actions are View in context, Provenance, Copy link,
download/export, and typed artifact metadata.

![Claude Science Library artifact provenance pane](screenshots/65-claude-science-library-provenance-pane.png)

The Provenance action opens an inline pane over the selected artifact rather
than a disconnected route. The Code tab is active and shows a generated
reconstruction, input artifact chips, and a download-script action.

![Claude Science provenance execution log](screenshots/66-claude-science-library-execution-log.png)

The Execution Log tab shows the replayable work trace as numbered cells with
language labels, commands/code, copy controls, and file writes. This is the
closest visual analogue to a Genomi artifact's MCP/tool trace plus background
job history.

![Claude Science provenance messages tab](screenshots/67-claude-science-library-provenance-messages.png)

The Messages tab shows the transcript slice behind the artifact, including
step groups, tool outputs, corrections, and artifact-saving turns. This is the
most important UI clue: artifact provenance is tied back to host-agent
conversation state, not just to a generated file.

![Genomi artifact Messages provenance tab](screenshots/68-genomi-artifact-messages-provenance.png)

Genomi implementation checkpoint after adding origin-frame provenance messages
to artifact detail. The artifact split pane now has a `Messages` tab when an
artifact is tied to a frame. The tab shows the sanitized user turn, tool result,
and assistant save message that produced the artifact, with local paths
redacted before display or selected-context reuse.

![Genomi bounded artifact Messages tab](screenshots/69-genomi-bounded-artifact-messages.png)

Post-review Genomi checkpoint after hardening artifact provenance into an
explicit detail-only shape. The visual fixture was created through the current
`add_artifact(..., frame_id=...)` path, which snapshots the origin message ids
at creation time. The tab shows `Displayed 3` / `Total 3`, redacts the local
source path, and excludes a later frame message added after artifact creation.

![Genomi artifact View in chat action](screenshots/70-genomi-artifact-view-context-action.png)

Genomi artifact split pane after adding a Claude-Science-style `View in chat`
action. The action appears only after artifact detail hydration exposes an
origin frame through provenance messages.

![Genomi artifact origin frame opened from View in chat](screenshots/71-genomi-artifact-view-context-frame.png)

The `View in chat` action opens the host-agent frame that produced the artifact
and switches the workspace back to chat. The full frame can show later messages
that are not part of the artifact's bounded provenance snapshot, while local
paths remain redacted in the visible transcript.

![Genomi persisted tool result re-check card](screenshots/72-genomi-persisted-tool-recheck-card.png)

Genomi reopened a stored `variant.resolve` tool result as display-only,
persisted-redacted history. The result still renders public evidence lanes and
the canonical envelope summary, but the notice makes clear that private/sample
sections were omitted and that the result must be re-checked before use.

![Genomi persisted tool result re-check prompt](screenshots/73-genomi-persisted-tool-recheck-prompt.png)

Clicking `Re-check tool` drafts a provenance-aware follow-up prompt into the
chat box. The prompt asks the host agent to call current Genomi tools again,
use the persisted-redacted view only as a pointer, preserve
`evidence_envelope` limits, and report supported, missing, and out-of-scope
evidence.

![Genomi frame work trace pane](screenshots/74-genomi-frame-work-trace-pane.png)

Genomi now projects the current frame's sanitized tool messages into an ordered
Work trail pane. Paired tool calls/results collapse into one step, errors stay
visible, and each step keeps operation, status, run/message scope, and a
re-check action.

![Genomi work trace summary attached](screenshots/75-genomi-work-trace-summary-context.png)

The `Attach work trail` action sends the ordered trace summary back into the
next chat turn as selected context. This lets the user ask about a workflow
without copying raw transcript or private tool payloads.

![Genomi work trace inspect step](screenshots/76-genomi-work-trace-inspect-step.png)

Opening `Inspect step` inside the Work trail pane reveals the nested Genomi
tool-result renderer for that step. Persisted-redacted public evidence lanes
remain visible, while the notice preserves the re-check-before-use boundary.

![Genomi work trace post-review viewport](screenshots/86-genomi-work-trace-scrolled-post-review.png)

Post-review visual checkpoint after hardening Work trail event pairing and the
local-only portal route gate. The viewport is scrolled directly to the Work
trail section in the live browser; it shows the two ordered tool steps, the
error step, and the attached `Frame work trace` selected context below.

![Genomi evidence node inspector fixture](screenshots/88-genomi-evidence-node-inspector-viewport.png)

Frontend fixture for the generic Genomi evidence panel after adding envelope
node inspection. The fixture imports the real portal CSS and
`portal_evidence_panel.js` module, selects two guidance nodes, and shows the
new inspector with the exact node context that can be sent into the next turn.

![Genomi selected-context tray node inspector](screenshots/89-genomi-selected-context-tray-node-inspector.png)

Live Genomi portal checkpoint for the selected-context tray. A node inside the
attached `Frame work trace` evidence report is selected, and the tray opens the
same shared inspector class to show the full attached evidence detail before the
user sends the next host-agent turn.

![Genomi selected-context tray post-review](screenshots/90-genomi-selected-context-tray-post-review.png)

Post-review live browser checkpoint after extracting tray rendering into
`portal_prompt_context_tray.js` and preserving selected-context metadata
server-side. The first `Frame work trace` packet node is selected, the shared
`genomi-selection-inspector` is visible, and the browser console reported no
warnings or errors.

![Genomi artifact origin trace tab](screenshots/91-genomi-artifact-origin-trace-tab.png)

Live Genomi portal checkpoint for the artifact provenance Trace tab. An
`evidence_packet` artifact is open in the split pane, the new Trace tab shows
the bounded origin-frame work step, and the trace node is selected as artifact
context so it can be sent back into the host-agent conversation.

![Genomi artifact origin trace post-review](screenshots/92-genomi-artifact-origin-trace-post-review.png)

Post-review live browser checkpoint after extracting artifact origin trace
modeling into `portal_artifact_origin_trace.js` and reusing the canonical frame
trace context-node helper. The same Trace tab behavior remains visible after a
full portal reload, and the browser console reported no warnings or errors.

![Genomi artifact selection inspector](screenshots/93-genomi-artifact-selection-inspector.png)

Live Genomi portal checkpoint for selected artifact-node inspection. A Trace
tab node is selected, the artifact selection bar reports one selected artifact
node, and the shared `genomi-selection-inspector` shows the exact prompt-safe
context before `Use selection` or `Ask selected`.

![Genomi artifact selection inspector post-review](screenshots/94-genomi-artifact-selection-inspector-post-review.png)

Post-review live browser checkpoint after moving artifact selection controls
and canonical selected-node normalization into `portal_artifact_selection.js`.
The same inspector remains visible after reload, and the browser console
reported no warnings or errors.

![Genomi evidence ledger display-only boundary](screenshots/101-genomi-evidence-ledger-display-only-hash.png)

Live Genomi portal checkpoint for the Evidence Ledger after adding reusable
ledger selection controls. The visible frame is persisted/display-only history,
so it correctly exposes `Re-check tool` only: no ledger selection bar, no
attach action, and no selected-node inspector. The reusable/live path is covered
by the focused frontend test that renders a current `variant.resolve` ledger
entry, selects a result node, shows the shared inspector, and emits the same
selected node in the outgoing context payload.

![Genomi evidence ledger post-review](screenshots/102-genomi-evidence-ledger-selection-post-review.png)

Post-review live browser checkpoint after moving ledger follow-up policy back
to the canonical tool-result presentation layer, consolidating selected-node
extraction, clearing nested inspectors when ledger selection is cleared, and
deduplicating selection-bar CSS. The persisted/display-only ledger still shows
only `Re-check tool`; browser console warnings/errors were empty.

![Genomi tool request builder topic target](screenshots/109-genomi-tool-request-builder-topic-css-hidden.png)

Live Genomi portal checkpoint for the schema-driven tool request builder. The
`research.build_target_packet` inspector is set to `target_type=topic`, so the
builder shows the topic input for `rs429358`, omittable default hints, and
shared optional fields while hiding gene/drug/condition/variant-only fields.
Visual inspection caught and fixed a CSS regression where hidden target-specific
rows were still displayed because component `display` rules overrode the
browser's default `[hidden]` behavior.

![Genomi tool request attached context](screenshots/110-genomi-tool-request-attached-context.png)

The same live builder after `Attach request`. The request is represented as a
`Tool request: research.build_target_packet` selected-context chip, preserving
the web UI as the visible chat surface while the host agent remains responsible
for the actual Genomi MCP call.

![Genomi tool request drafted prompt](screenshots/111-genomi-tool-request-drafted-prompt.png)

The sibling `Draft request` path fills the composer with the structured
operation request and only the user-supplied parameters
`target_type=topic` and `topic=rs429358`. Defaulted fields remain omitted so
Genomi can still report them through `defaults_applied`.

![Genomi portal before Ask with request](screenshots/112-genomi-portal-before-tool-request-ask.png)

Live portal baseline before testing the direct request handoff. The composer
already had a `Tool request: research.build_target_packet` selected-context
chip from the prior attach path, confirming that tool requests are represented
as normal selected evidence rather than a hidden side channel.

![Genomi tools panel before Ask with request](screenshots/113-genomi-tools-panel-before-request-ask.png)

The Genomi Tools pane shows base operations and focused research operations in
the same Decode-inspired dark command surface. The `research.build_target_packet`
operation is visible as a selectable request target.

![Genomi tool request builder selected](screenshots/114-genomi-tool-request-builder-selected-inspector.png)

The selected `research.build_target_packet` inspector exposes the schema-driven
request builder and its three request actions: `Attach request`, `Draft request`,
and `Ask with request`.

![Genomi tool request builder filled topic](screenshots/115-genomi-tool-request-builder-filled-topic.png)

The filled request-builder state uses `target_type=topic` and
`topic=rs429358`. Defaults still render as omittable hints, and the topic branch
is the only target-specific branch visible.

![Genomi tool request Ask submitted](screenshots/116-genomi-tool-request-ask-submitted.png)

Clicking `Ask with request` posts a normal chat turn from the web UI. The message
contains the structured request JSON and shows the attached
`Tool request: research.build_target_packet` chip, preserving the portal as the
chat surface while the backend starts the host-agent run.

![Genomi tool request post-submit wait](screenshots/116b-genomi-tool-request-post-submit-wait.png)

After waiting for the host-agent run stream, the submitted user turn remains in
the transcript and the composer is clear. The local backend reported the run as
terminal `succeeded`; this particular local host-agent invocation emitted no
parsed assistant `text_delta` before exiting.

![Genomi post-review tool request builder](screenshots/117-genomi-tool-request-post-review-builder.png)

Post-review live checkpoint after extracting request semantics into the pure
`portal_tool_request_model.js` module. The visible UI remains the same, but the
DOM no longer serializes conditional rules into `data-tool-visible-when`; the
renderer keeps only stable field ids and asks the compiled model for visibility
and required state.

![Genomi post-review Ask with request chat stream](screenshots/119-genomi-tool-request-post-review-chat-stream.png)

Post-review direct handoff from `Ask with request`. The button now submits an
explicit `{message, selectedEvidence}` turn draft, then brings the user back to
the chat surface where the host-agent stream appears.

![Genomi post-review Ask with request terminal](screenshots/119b-genomi-tool-request-post-review-terminal-chat.png)

The final post-review run reached terminal `succeeded` state, and browser
console warnings/errors were empty. This checkpoint confirms the web UI owns
the chat surface while the backend streams the selected host-agent run.

![Genomi stream diagnostics baseline](screenshots/120-genomi-stream-diagnostics-before-interaction.png)

Baseline before stream-diagnostic cleanup verification. Older host-agent turns
still show setup chatter and skill-loading text inside the assistant answer
body, which is the behavior this slice removes for new runs.

![Genomi stream diagnostics running checkpoint](screenshots/121-genomi-stream-diagnostics-running.png)

Running checkpoint after submitting a tiny host-agent prompt from the web UI.
The turn posts through the normal portal composer and the backend run completes
without browser console warnings or errors. This checkpoint also preserves the
old-history contrast: prior turns still contain setup text in the answer body
because they were persisted before the cleanup.

![Genomi persisted stream diagnostic chip](screenshots/123-genomi-stream-diagnostics-completed.png)

Current expected behavior after the cleanup. The assistant answer is only the
short response text, while host-agent startup appears as a compact
`spawn_agent` trace chip below the answer. The diagnostic is persisted, so it
survives the frame refresh after terminal run completion.

![Genomi live stream policy grouped](screenshots/124-genomi-stream-policy-live-grouped.png)

Post-review live checkpoint after introducing the host-agent run presentation
helper. A fresh chat turn renders answer text in the assistant body and keeps
startup state as a `spawn_agent` work-trace chip attached to that same
assistant message.

![Genomi reloaded stream policy grouped](screenshots/125-genomi-stream-policy-reloaded-grouped.png)

Reloaded checkpoint for persisted transcript grouping. The previous
`spawn_agent` diagnostic was stored before the assistant answer, but replay now
groups tool/diagnostic messages by `run_id`, so the chip remains under the
matching assistant response after refresh.

![Genomi inline message artifact strip](screenshots/126-genomi-inline-message-artifact-strip.png)

Current artifact checkpoint after adding run-scoped artifact origin metadata to
the public artifact summary. The `Evidence report: rs429358` artifact now
renders directly underneath the assistant turn whose `run_id` appears in the
artifact origin context, while the global artifact workspace remains available
elsewhere on the page.

![Claude Science project session workspace](screenshots/127-claude-science-project-session-workspace.png)

Post-onboarding Claude Science project route. The page is a research session
workspace with a transcript/composer surface; it is not the `/start` setup
wizard. The session can be reopened directly at a project/frame URL.

![Claude Science desktop session and files pane](screenshots/128-claude-science-desktop-session-and-files-pane.png)

Desktop-width checkpoint showing the project sidebar, session tab strip, Files
tab, and composer. The layout changes materially at wider widths, so this
desktop pass is the useful design reference for Genomi.

![Claude Science session step stack](screenshots/129-claude-science-session-step-stack.png)

The transcript interleaves assistant prose with compact grouped work cards.
Each group shows a title, child steps, completion marks, and output counts
without dumping logs into the normal answer body.

![Claude Science step command detail](screenshots/130-claude-science-step-command-detail.png)

Expanding a step reveals command source with language and environment labels.
Output remains collapsed behind a `Show output` affordance.

![Claude Science step output expanded](screenshots/131-claude-science-step-output-expanded.png)

The same step with output expanded. Command source and stdout are visibly
separate, preserving inspectability without turning the transcript into a raw
terminal stream.

![Claude Science artifacts split pane](screenshots/132-claude-science-artifacts-split-pane.png)

Split-pane view keeps the transcript on the left and opens a first-class
artifact library on the right. Artifacts are grouped by upload/session and show
type-specific previews, timestamps, authorship, and action affordances.

![Claude Science report artifact route](screenshots/133-claude-science-report-artifact-route.png)

Opening a Markdown report artifact creates a dedicated preview route/modal with
an artifact toolbar. The preview renders the artifact as a document, not as a
download link.

![Claude Science artifact actions menu](screenshots/134-claude-science-artifact-actions-menu.png)

Artifact actions include `View in context`, `Provenance`, `Copy link`, rename,
download, metadata export, cloud export, and delete. The important Genomi
lesson is that provenance and context are peer actions beside download.

![Claude Science artifact provenance code tab](screenshots/135-claude-science-artifact-provenance-code-tab.png)

The Provenance pane opens with a generated reproduction script and an Inputs
chip for the artifact dependency. The code is presented as a reconstruction,
with an explicit link to the raw Execution Log.

![Claude Science artifact provenance execution log tab](screenshots/136-claude-science-artifact-provenance-execution-log-tab.png)

The Execution Log tab renders numbered notebook-style cells with language and
environment labels. This is the raw record behind the generated script.

![Claude Science artifact provenance messages tab](screenshots/137-claude-science-artifact-provenance-messages-tab.png)

The Messages tab shows the transcript slice that led to the artifact,
including the same grouped work cards visible in the main session.

![Claude Science artifact provenance environment tab](screenshots/138-claude-science-artifact-provenance-environment-tab.png)

The Environment tab records the producing environment name, Python version,
package count, and package/version table.

![Claude Science artifact provenance review tab](screenshots/139-claude-science-artifact-provenance-review-tab.png)

The Review tab is present even when no checks have run. Claude Science reserves
artifact review as a first-class state beside code, execution, messages, and
environment.

![Genomi artifact Runtime tab](screenshots/140-genomi-artifact-runtime-tab.png)

Genomi checkpoint after mapping the useful part of Claude Science's environment
provenance into the artifact inspector. The Runtime tab stays Genomi-native:
origin boundary, applied defaults, consulted source coverage, interpretation
boundary, and immutable artifact version metadata sit beside Evidence, Tools,
Trace, Messages, State, and Review.

![Genomi artifact deep-link route](screenshots/141-genomi-artifact-deep-link-route.png)

Genomi checkpoint after adding first-class artifact routes. Opening
`/projects/:project_id/artifacts/:artifact_id` now selects the artifact, keeps
the URL on the artifact identity, and scrolls directly to the artifact
workspace with the packet preview visible.

![Genomi artifact version route](screenshots/142-genomi-artifact-version-route.png)

Genomi checkpoint after adding immutable artifact-version workspace routes.
Opening `/projects/:project_id/artifacts/:artifact_id/versions/:version_id`
keeps the browser on the version URL, restores the artifact workspace, and
previews the versioned file endpoint.

![Genomi scoped artifact version route](screenshots/143-genomi-scoped-artifact-version-route.png)

Post-review checkpoint after tightening artifact/version boundaries. The same
workspace route now hydrates through project-scoped artifact APIs and previews
the scoped immutable version file endpoint, while the old global artifact API
returns `404`.

![Genomi artifact copy link](screenshots/144-genomi-artifact-copy-link.png)

Genomi checkpoint after adding Claude Science-style artifact copy affordances.
Artifact cards and the active artifact preview both expose `Copy link`; the
copied value is the project workspace route, and the active version preview
uses the immutable `/projects/:project_id/artifacts/:artifact_id/versions/:version_id`
route instead of a raw file endpoint.

![Genomi artifact tab route](screenshots/145-genomi-artifact-tab-route.png)

Genomi checkpoint after making artifact inspection tabs route-addressable. A
versioned artifact URL can now carry `?artifact_tab=review`, reopen the same
artifact workspace, activate the Review tab, and copy the same tab-scoped
workspace identity.

![Genomi artifact library toolbar](screenshots/146-genomi-artifact-library-toolbar.png)

Genomi checkpoint after adding Claude Science-style artifact library controls.
The project artifact list can now search by title/kind/operation/status, filter
by artifact class, switch between card and compact layouts, and keep the active
artifact highlighted while the preview remains open.

![Genomi artifact version selector](screenshots/147-genomi-artifact-version-selector.png)

Genomi checkpoint after exposing immutable artifact-version state inside the
artifact workspace. The preview header now shows a compact Version selector,
keeps the selected version in the workspace URL, and preserves the active
inspection tab while the artifact remains open.

![Genomi message work group header](screenshots/148-genomi-message-work-group-header.png)

Genomi checkpoint after adding Claude Science-style work grouping to the chat
transcript. Tool calls under an assistant answer now sit behind a compact
work-step header with completed/running/error counts, while the individual tool
chip and generated artifacts remain inspectable in the same turn.

![Genomi message work trace actions](screenshots/149-genomi-message-work-trace-actions.png)

Genomi checkpoint after using an inline work-group action. Pressing `Attach work trail`
attaches a sanitized `Message work trace` packet to the next-turn context tray,
so the user can route grouped host-agent work back into chat without opening a
separate trace pane.

![Genomi message work action row](screenshots/150-genomi-message-work-action-row.png)

Genomi checkpoint showing the inline work-group action row itself. Each grouped
tool stack now exposes `Attach work trail` and `Ask about work trail` beside the compact step summary,
while the underlying tool chip and generated artifacts stay inspectable below.

![Genomi result search toolbar](screenshots/151-genomi-result-search-toolbar.png)

Genomi checkpoint after adding an evidence-node search toolbar to structured
result panels. The expanded persisted `variant.resolve` result keeps the
Decode-style evidence map, persisted-redacted warning, and node lanes visible;
the toolbar summarizes the unfiltered result as `3 nodes`.

![Genomi result search filtered](screenshots/152-genomi-result-search-filtered.png)

The same `variant.resolve` result after filtering for `ClinVar`. The resolved
target node is hidden, the two ClinVar nodes remain visible, and the toolbar
reports `2 of 3 shown`.

![Genomi result search empty](screenshots/153-genomi-result-search-empty.png)

No-match search state for `NoSuchGene`. The panel hides all result nodes,
collapses the evidence lanes, and marks the toolbar summary as `0 of 3 shown`.

![Genomi selected context actions](screenshots/154-genomi-selected-context-actions.png)

Historical Genomi checkpoint from when selected material had its own rail
target. That surface was later folded into composer `Attached material`.
The useful retained behavior is provenance-specific actions on attached
context cards: a work-trace packet renders as `Work trail`, uses the blue
work-trace card treatment, and offers `Ask about work trail` plus `Draft work`
beside packet copy/remove actions.

![Genomi selected context draft work](screenshots/155-genomi-selected-context-draft-work.png)

After pressing `Draft work`, the composer is filled with a work-trace-specific
prompt that asks the host agent to use the selected trace as provenance for
what was already attempted. No host-agent message is submitted by the draft
action.

![Genomi ledger direct actions selected](screenshots/156-genomi-ledger-direct-actions-selected.png)

Evidence Ledger fixture using the real portal modules. Selecting the first
current `variant.resolve` result node changes the ledger selection bar from
`Use evidence` / `Ask evidence` / `Draft evidence` to `Use selected` /
`Ask selected` / `Draft selected`, and the ledger inspector shows the selected
prompt-safe node.

![Genomi ledger direct actions draft](screenshots/157-genomi-ledger-direct-actions-draft.png)

After pressing `Draft selected`, the action panel shows the prepared
next-turn packet and the prompt text generated from the selected ledger node.
The packet remains `context_kind: result_nodes` with `source_operation:
variant.resolve`.

![Genomi ledger direct actions ask](screenshots/158-genomi-ledger-direct-actions-ask.png)

After pressing `Ask selected`, the fixture records the same selected packet as
the direct host-agent submission payload. This verifies that the ledger detail
can now send selected visual evidence directly through the chat loop without
first bouncing through a separate tray.

![Genomi assistant checklist direct actions selected](screenshots/159-genomi-assistant-checklist-direct-actions-selected.png)

Assistant evidence checklist fixture using the real transcript renderer. After
selecting one source lane, the checklist shows `1 selected source lane` and
enables `Use selected`, `Ask selected`, and `Draft selected`.

![Genomi assistant checklist direct actions draft](screenshots/160-genomi-assistant-checklist-direct-actions-draft.png)

After pressing `Draft selected`, the fixture composer contains the prompt-safe
`assistant_checklist` packet for the selected CPIC/PharmGKB source lane.

![Genomi assistant checklist direct actions ask](screenshots/161-genomi-assistant-checklist-direct-actions-ask.png)

After pressing `Ask selected`, the fixture records the same
`assistant_checklist` packet as the direct host-agent submission payload.

![Claude Science frame work-step stack](screenshots/162-claude-science-frame-work-step-stack.png)

Claude Science frame route after leaving onboarding. The useful surface is the
research session: a chat transcript with grouped work steps, artifacts, and a
composer in the same workspace.

![Claude Science inline step output](screenshots/163-claude-science-step-output-inline-detail.png)

Expanded step output inside the transcript. Tool/command work is grouped under
human-readable step titles rather than exposed as raw state machinery.

![Claude Science project library files pane](screenshots/164-claude-science-project-library-files-pane.png)

Files pane beside the conversation. Artifacts are grouped as durable project
objects with search/layout controls, not as transient attachments.

![Claude Science metrics artifact route](screenshots/165-claude-science-artifact-route-metrics-open.png)

Opening `benchmark_metrics.csv` turns the artifact into a dedicated table
object with its own header and action bar.

![Claude Science artifact action menu](screenshots/166-claude-science-artifact-actions-menu.png)

Artifact actions include Star, Hide, View in context, Provenance, Copy link,
Rename, Export Metadata, Export to Cloud, and Delete. The transferable Genomi
pattern is object navigation plus provenance, not user-managed context packets.

![Claude Science provenance code tab](screenshots/167-claude-science-artifact-provenance.png)

Provenance opens as a tabbed artifact history. The Code tab shows a generated
reconstruction, input chips, and a download script action.

![Claude Science provenance execution log](screenshots/168-claude-science-artifact-execution-log.png)

Execution Log tab shows runnable cells with command source and environment
labels. This keeps raw execution history adjacent to the artifact.

![Claude Science provenance messages tab](screenshots/169-claude-science-artifact-messages-tab.png)

Messages tab shows the transcript slice and grouped work that led to the
artifact. This is the user-facing answer to “where did this come from?”

![Claude Science provenance environment tab](screenshots/170-claude-science-artifact-environment-tab.png)

Environment tab shows the runtime snapshot and package versions that produced
the artifact.

![Claude Science current provenance state](screenshots/171-claude-science-current-artifact-provenance-state.png)

Current artifact route captured while the Environment tab was active.

![Claude Science provenance review tab](screenshots/172-claude-science-artifact-review-tab.png)

Review tab is first-class even when empty; this artifact showed `No checks run
yet.` Genomi should map this to review findings, evidence gaps, and validation
state.

![Claude Science artifact after closing provenance](screenshots/173-claude-science-artifact-after-closing-provenance.png)

Closing provenance returns to the artifact object, preserving the dedicated
table route.

![Claude Science artifact header menu](screenshots/174-claude-science-artifact-header-actions-menu.png)

The artifact header exposes the same object actions as the split pane.

![Claude Science View in context result](screenshots/175-claude-science-view-in-context-result.png)

Using `View in context` navigates from the artifact route back to the producing
project frame while keeping the Files pane available. The artifact remains a
project object; the user does not manually assemble a context payload.

![Claude Science View in context frame state](screenshots/176-claude-science-view-in-context-work-step-visible.png)

Second capture after attempting to scroll the frame state. The viewport stayed
anchored by the composer and Files pane, but the browser DOM confirmed the
producing `Saving benchmark figure and metrics` work step and
`benchmark_metrics.csv` artifact were present in the routed frame.

![Genomi portal user-facing state copy](screenshots/178-genomi-portal-user-facing-state-copy.png)

Genomi checkpoint after re-anchoring the portal copy around user-visible
science objects. The root workspace now says `Genome State` and `current chat`
instead of asking the user to reason about Genomi context machinery.

![Genomi evidence report action menu](screenshots/180-genomi-fresh-evidence-report-actions-menu.png)

Genomi checkpoint after adding the Claude Science-style artifact overflow menu.
The artifact is presented as an `Evidence report`, with object actions for use,
review, the Evidence/provenance tab shortcut, workspace link, metadata, and
opening the report.

![Genomi artifact Environment tab](screenshots/186-genomi-artifact-environment-tab.png)

Live branch checkpoint after adding version-owned Environment snapshots.
Genomi now shows the producing runtime, artifact context, package availability,
and Genomi library state on the artifact. This is a useful equivalent for
artifact inspection, but not full Claude Science parity: Genomi still lacks
cell-level environment labels, host-agent process package capture, and
environment operation history.

![Genomi artifact Work Trail tab](screenshots/189-genomi-artifact-work-trail-wide.png)

Earlier branch checkpoint after replacing the artifact Trace panel with latest
bounded message-derived Work Trail cards. The artifact provenance surface showed
the producing tool work as a numbered, user-facing card with wired artifact
actions such as `Attach this step` and `Ask about step`. Later checkpoints below
add producing-run execution cells to the artifact Work trail, but this remains
a practical provenance surface rather than a full Execution Log: Genomi still
lacks stdout/stderr panes, command
source, language/environment labels, stable cell ids, and complete tool-step
identity outside the bounded message slice.

![Genomi work trail language](screenshots/181-genomi-work-trail-language-live.png)

Live branch checkpoint showing the Work Trail pane using user-facing work-step
language. The historical transcript in this local project still included stale
saved wording from earlier experiments, so the clean captures below are the
preferred current-language references.

![Genomi historical next-question pane](screenshots/184-genomi-clean-next-question-language-cropped.png)

Historical capture from the terminology pass. This surface is superseded by the
composer-attached `Attached material` model; the standalone next-question pane
is no longer part of the current portal direction.

![Genomi clean genome index language](screenshots/185-genomi-clean-genome-index-language-cropped.png)

Clean project capture of the Genome Index pane. The visible actions are `Use
selected facts` and `Use genome summary`; the raw state remains available only
behind `Technical state`.

![Genomi ready genome state gated actions](screenshots/20260703-genomi-genome-state-ready-gated-actions.png)

Current live checkpoint for the same surface after gating attach actions by
Active Genome Index state. Ready and approved genome state still exposes `Use
selected facts` and `Use genome summary`; empty, blocked, unknown-readiness, or
still-building states render a status hint instead of attach buttons.

![Genomi artifact download bundle menu](screenshots/190-genomi-artifact-download-bundle-menu.png)

Live branch checkpoint after adding a local artifact bundle action. The
artifact action menu now exposes `Download artifact bundle`, backed by a ZIP containing a
manifest, public metadata JSON, and portal-owned version files. This closes the
artifact-bundle slice while script bundles remain a separate backlog item.

![Genomi frame download bundle action](screenshots/191-genomi-frame-download-bundle-action.png)

Live branch checkpoint after adding a local frame/session bundle action. The
chat header exposes `Download conversation bundle`, backed by a ZIP containing a manifest,
frame metadata, transcript messages, attached artifact metadata, and
portal-owned artifact version files. This closes the direct frame/session
bundle slice while artifact-version script bundles and Library upload/import
grouping remain separate backlog items.

![Claude Science Library reference](screenshots/193-claude-science-library-reference-current.png)

Claude Science reference capture after opening the Library pane in the project
workspace. The Files surface separates `Your uploads` from generated
session/task artifacts and keeps grid/list controls visible.

![Genomi imported file inline preview](screenshots/195-genomi-imported-file-inline-preview.png)

Live branch checkpoint after adding browser file import into Genomi's artifact
workspace. The imported CSV appears under the `Files` filter, keeps normal
artifact actions and version metadata, and renders inline as readable
workspace text instead of a raw context payload or blank iframe.

![Genomi portal UX alignment current workspace](screenshots/197-genomi-portal-ux-alignment-current-workspace.png)

Live branch checkpoint after the subagent UX-alignment pass. A stale
project/artifact URL recovers to the current workspace instead of showing a
false API outage; the primary nav uses `Expert tools`, there is no
standalone next-question/selected-context pane, the composer owns attached
material, the assistant rail reports available assistants, and Genome State
shows user-facing `Current genome`, `Privacy boundary`, and `Known genomes`
sections.

![Genomi desktop primary nav default](screenshots/204-genomi-desktop-primary-nav-default.png)

Live branch checkpoint after the web-UI comparison pass. The default desktop
rail presents `Research workspace` and `Files & Artifacts` as the only primary
navigation items. `Workspace details` is collapsed, keeping evidence maps, work
trails, genome state, and expert tool preparation out of the default user path.

![Genomi desktop workspace details open](screenshots/205-genomi-desktop-workspace-details-open.png)

The same checkpoint with `Workspace details` open. The secondary surfaces are
still reachable for inspection and continuation work: Work trail, Genome state,
and Expert tools. Evidence from this chat appears in the same disclosure only
after evidence exists for the current conversation.

![Genomi server-owned prompt suggestion boundary](screenshots/206-genomi-server-prompt-suggestion-boundary.png)

Live branch checkpoint after moving selected-material Ask/Draft wording to the
server. The browser remains the chat and workspace surface, but follow-up
prompt policy now comes from `/api/prompt/suggestion`; assistant prose no
longer creates checklist UI or selected-context packets.

![Reference typed workspace state](screenshots/207-reference-typed-workspace-state.png)

Reference workspace checkpoint from the same pass. The visible interaction
model is session/work-step/artifact state, not prose-derived checklist parsing;
Genomi should preserve that typed-state lesson while using its own evidence
contracts and privacy boundaries.

![Genomi source lookup shell checkpoint](screenshots/20260703-genomi-portal-source-lookup-shell.png)

Live branch checkpoint after adding the server-owned source lookup catalog.
The portal still opens on the research workspace with Files & Artifacts as the
other primary surface. Evidence sources remain a secondary workspace
detail; `/api/source-lookups` now returns curated lookup cards without raw
operation schemas or install/debug operations.

![Genomi source lookup catalog](screenshots/20260703-genomi-source-lookup-catalog.png)

Live branch checkpoint of the secondary Evidence sources pane. The catalog
groups curated source lookups by domain, opens on `Add genome file`, shows
friendly input labels and source/privacy boundary copy, and keeps operation ids
behind `Technical disclosure`.

![Genomi evidence-source setup aligned](screenshots/20260703-genomi-source-lookup-setup-aligned.png)

Live branch checkpoint after the independent UX-alignment pass and follow-up
copy/disclosure cleanup. The secondary surface is labeled `Evidence sources`,
attached material now uses evidence-source language, and the page avoids
tool-console wording in normal copy. The welcome starters are public-first
unless genome approval exists, normal Boundary rows show privacy and operation
scope only, and trust-boundary/runtime mechanics stay behind technical
disclosure.

![Genomi attached material tray](screenshots/20260703-genomi-attached-material-tray.png)

Live branch checkpoint after upgrading the composer attached-material surface.
Selected genome/evidence facts render as compact inspectable cards in the
composer before the user sends the turn. The tray shows friendly object labels,
source labels, selected-item counts, and value previews while keeping raw
operation ids and packet mechanics out of the normal UI.

![Reference workstep composer check](screenshots/20260703-reference-workstep-composer-check.png)

Reference workspace checkpoint from the same pass. The useful pattern is a chat
composer adjacent to typed workspace objects: files, generated artifacts,
session/work-step state, and artifact handles. Genomi's attached-material tray
adapts that pattern with Genomi evidence/genome objects rather than exposing a
separate packet builder.

![Genomi workspace file preview](screenshots/20260703-genomi-workspace-file-preview.png)

Live branch checkpoint after adding bounded workspace-file previews. A
file-only assistant workspace output now has a `Preview file` action and opens
inline in Files & Artifacts without requiring it to already be a generated
artifact. Text previews are redacted for local paths; small image previews use
data URLs; large/binary files report an unavailable preview state.

![Genomi workspace file preview with extracted CSS](screenshots/20260703-genomi-workspace-file-preview-css-extracted.png)

Live branch checkpoint after the maintainability review fix. The preview
surface still renders inline, and the page links `portal_workspace_files.css`
so the workspace-file component no longer grows the global portal stylesheet.

![Reference Files pane check](screenshots/20260703-reference-files-pane-check.png)

Reference workspace checkpoint from the same pass. The Files pane keeps uploads
and generated artifacts directly inspectable beside the conversation. The
Genomi file-preview slice adapts that object-continuity pattern for project
workspace files produced by host-agent runs.

![Genomi sidecar run-control smoke](screenshots/20260703-genomi-sidecar-run-control-smoke.png)

Live branch checkpoint after adding base sidecar run-control operations. The
portal still opens directly into the post-onboarding Research workspace plus
Files & Artifacts shell; the new start/check/cancel/package operations are
backend sidecar affordances and do not introduce a separate `/start` or
parallel chat UI.

![Genomi UX alignment shell](screenshots/20260703-genomi-ux-alignment-shell.png)

Live branch checkpoint from the focused subagent UX-alignment pass. The portal
opens directly into the Research workspace plus Files & Artifacts shell; `/start`
is not part of the product route, and genome state is a compact readiness
boundary rather than an onboarding wizard.

![Genomi evidence-source actions](screenshots/20260703-genomi-ux-alignment-source-check.png)

Live branch checkpoint after replacing source-lookup action wording with
evidence-source handoff wording. The secondary setup pane still groups curated
source workflows, and raw operation identity stays behind the typed/technical
boundary.

![Genomi evidence-source server-prepared actions](screenshots/20260703-genomi-source-check-actions-server-prepared.png)

Live branch checkpoint after moving evidence-source prompt and selected-material
handoff behind `/api/evidence-sources/attach`. The secondary evidence-source
surface uses product actions (`Use in chat`, `Draft question`,
`Ask with source`) and `Choose` / `Selected` row affordances, keeping operation
ids out of normal copy.

![Genomi evidence-source attached material handoff](screenshots/20260703-genomi-source-check-server-handoff.png)

The server-prepared evidence source appears in the composer as attached
material: `Evidence source: Add genome file`, with friendly source chips and no
operation-id fallback such as `Genomi Parse Source`.

![Genomi execution-cell Work trail shell](screenshots/20260703-genomi-execution-cell-work-trail.png)

Live branch checkpoint after wiring run-package execution cells into the
conversation Work trail. The active workspace detail is Work trail, using the
seeded smoke frame.

![Genomi execution-cell Work trail cards](screenshots/20260703-genomi-execution-cell-work-trail-cards.png)

Scrolled checkpoint of the same smoke frame. The Work trail renders one
transcript-derived `Variant lookup` step plus execution-cell-backed diagnostic,
artifact, and run-finished cards. The tool execution cell is not duplicated
because the transcript already carries the tool step.

![Genomi artifact Work trail execution cells](screenshots/20260703-genomi-artifact-work-trail-execution-cells-focused.png)

Artifact-route visual checkpoint after wiring producing-run execution cells into
artifact Work trails. The Work trail tab shows four work steps, with
`Diagnostic output` replacing raw stdout/stderr process language.

![Genomi artifact Work trail run completion cell](screenshots/20260703-genomi-artifact-work-trail-execution-cells-lower.png)

Lower viewport of the same artifact Work trail showing the `Artifact` and
`Run finished` execution-cell cards beside the transcript-derived
`Variant lookup` card.

![Genomi portal UX alignment smoke](screenshots/20260703-genomi-portal-ux-alignment-smoke.png)

Live branch checkpoint after the independent UX comparison/alignment pass. The
portal opens directly into the research workspace and Files & Artifacts shell,
with the assistant runtime tucked into a secondary disclosure. Empty-state
workspace objects are visible, while evidence sources and current evidence stay
out of the default empty view until there is a reason to show them. `/start`
still returns `404`.

![Genomi runtime rail smoke](screenshots/20260703-genomi-runtime-default-rail-smoke.png)

Live branch checkpoint after removing the primary chat runtime picker. The
chat header no longer exposes an assistant selector; runtime readiness is rail
status plus secondary details, and normal web turns let the server choose the
default runnable host agent.

![Reference workspace runtime-hidden smoke](screenshots/20260703-reference-runtime-hidden-workspace-smoke.png)

Reference science-workspace checkpoint from the same pass. The visible
workspace is organized around project steps, files, and artifacts rather than
a user-facing runtime choice, which is the interaction boundary adapted in the
Genomi runtime-default slice.

![Genomi evidence-source neutral state](screenshots/20260703-genomi-evidence-sources-neutral-no-auto-select.png)

Live branch checkpoint after the source-preparation copy cleanup. Opening the
secondary Evidence sources pane shows available evidence sources, row actions
say `Choose`, and the pane does not auto-select the first source; the user must
intentionally choose one before the request builder and chat handoff appear.

![Genomi target report server presentation](screenshots/20260703-genomi-target-packet-server-presentation.png)

Live branch checkpoint after moving `research.build_target_packet` chat-result
rendering to the server-owned result presentation contract. The collapsed
work-step chip and expanded header use friendly target-report copy instead of
the raw operation headline.

![Genomi target report reviewed research lane](screenshots/20260703-genomi-target-packet-server-presentation-lanes-clipped.png)

Clipped checkpoint of the same expanded target evidence report. The target and
reviewed-research lanes render as selectable scientific material in the chat
result detail.

![Genomi target report source and coverage lanes](screenshots/20260703-genomi-target-packet-server-presentation-lanes-lower.png)

Lower clipped checkpoint of the same report showing source catalog, evidence
readiness, and coverage/limits lanes. Source-boundary lanes are shown as result
context rather than evidence the user has to package manually.

![Reference workspace target-report sanity](screenshots/20260703-reference-workspace-target-report-sanity.png)

Reference workspace sanity check from the same browser pass. The relevant
pattern is compact work-step history plus files/artifacts side surfaces; Genomi
adapts that into local target-report result lanes rather than reusing a
dashboard-first or packet-selection flow.

![Genomi evidence sources clean panel](screenshots/20260703-genomi-evidence-sources-panel-viewport.png)

Live branch checkpoint after the Evidence sources copy cleanup. The secondary
pane is reachable through the responsive workspace navigation and presents
source choices without `Prepare`, `Source check`, or attach-helper wording.

![Genomi curated evidence-source chooser](screenshots/20260703-genomi-evidence-sources-curated-source-list.png)

Live branch checkpoint after hiding backend library-readiness checks from the
normal source chooser. The Genomi support group contains user-facing choices
(`Add genome file`, `Search public sources`) while source availability remains
support state surfaced only when a selected workflow needs it.

![Genomi evidence-source builder clean handoff](screenshots/20260703-genomi-evidence-source-builder-crop.png)

Focused crop of the selected Target evidence report source from an earlier
handoff pass. The current builder uses `Use in chat`, `Draft question`, and a
filled topic input without exposing source-preparation internals.

![Genomi guided target evidence-source builder](screenshots/20260703-genomi-guided-target-source-builder-final.png)

Live branch checkpoint after replacing the Target evidence report's raw
target-type selector with review-target chips. Choosing `Topic` reveals only the
Topic field, keeps source limits collapsed, and removes the duplicated generated
Inputs section from the normal inspector surface.

![Genomi declarative source-builder verification](screenshots/20260703-genomi-declarative-source-builder-viewport.png)

Live branch checkpoint after moving the guided Target evidence report controls
into declarative request UI metadata. The visible behavior is unchanged, but
the generic request builder no longer branches on the target-report operation;
only param-aware builder actions remain visible.

![Reference compact workstate after guided builder pass](screenshots/20260703-reference-compact-workstate-after-guided-builder.png)

Reference science-workspace checkpoint from the same pass. The relevant pattern
is a compact composer plus project/files/artifacts state as normal workspace
objects, with operational details available but not forced into the primary
interaction. Genomi adapts that boundary in the guided Target evidence report
form.

![Genomi evidence-source drafted prompt](screenshots/20260703-genomi-evidence-source-draft-clean-copy.png)

Composer state after `Draft question` from the selected source. The prompt asks
the host agent to use the Target evidence report as the evidence source and
keeps source limits, defaults, and genome privacy boundaries in plain language.

![Reference workspace context-handoff pattern](screenshots/20260703-reference-workspace-context-handoff-pattern.png)

Reference science-workspace checkpoint for the context-handoff pass. Generated
work, files, artifacts, and task steps remain clickable workspace objects near
the conversation; the lesson for Genomi is to bring selected visual evidence
back into the chat flow without making users manage an internal packet.

![Genomi report context handoff to composer](screenshots/20260703-genomi-context-handoff-composer.png)

Live Genomi checkpoint after clicking `Use` on a generated evidence report.
The active workspace returns to the Research composer, the attached-material
tray is visible, and the card uses evidence/report language rather than raw
operation or packet wording.

![Genomi attached-material copy cleanup](screenshots/20260703-genomi-attached-material-copy-cleanup.png)

Live Genomi checkpoint after replacing remaining selected-context copy with
attached-material language. The report handoff returns to the Research
composer, focuses the prompt, and shows `ATTACHED MATERIAL` plus one attached
evidence report card.

![Reference attached-material pattern check](screenshots/20260703-reference-attached-material-copy-check.png)

Reference workspace checkpoint from the same pass. Conversation, work steps,
and files/artifacts remain adjacent; Genomi adapts that pattern by making
selected reports and evidence feel like attached research material in chat.

![Genomi Source limits panel cleanup](screenshots/20260703-genomi-source-limits-panel-cleaned.png)

Live Genomi checkpoint after fixing the artifact source-limits tab. The panel
now appears for detail-hydrated artifacts, preserves source summaries instead
of object field counts, and keeps Python/package/runtime details out of the
primary user surface.

![Genomi attached material without context fallback](screenshots/20260703-genomi-attached-material-no-context-fallback.png)

Live Genomi checkpoint after removing the remaining `Selected context`
fallbacks from generic selected-material paths. The composer shows attached
material for a report handoff and avoids `Selected context`, `next question`,
`Prepare`, and `Source check` wording.

![Genomi artifact projection source limits](screenshots/20260703-genomi-artifact-projection-source-limits.png)

Live Genomi checkpoint after routing artifact environment/review/rebuild panels
through a shared projection. A freshly rendered evidence report still exposes
the `Source limits` tab when the version object only contains file metadata,
and the visible cards/panel avoid internal `Source checks`, `Prepare`, packet
wording, raw operation headlines, and raw envelope codes.

![Reference workspace artifact/provenance alignment](screenshots/20260703-reference-workspace-artifact-provenance-alignment.png)

Reference science-workspace checkpoint for the same alignment pass. Work steps,
files, and artifact/provenance state sit beside the conversation as workspace
objects; Genomi adapts the pattern by keeping result tabs coherent and
user-facing rather than exposing selected-version source plumbing.

![Genomi evidence-source Use in chat handoff](screenshots/20260703-genomi-evidence-source-use-in-chat-handoff.png)

Live Genomi checkpoint after changing source handoff copy and route state. The
Target evidence report source is attached to the Research composer as
included evidence, the route is `#research-workspace`, and the visible card
uses `source details` rather than request/setup wording.

![Reference workspace step-stack source handoff comparison](screenshots/20260703-reference-workspace-step-stack-source-handoff-comparison.png)

Reference science-workspace checkpoint for the same source-handoff pass. The
relevant behavior is conversation-adjacent work steps and generated objects;
Genomi adapts that pattern by making source choices feed chat instead of
remaining as a tool-picker route.

![Genomi saved evidence re-check copy checkpoint](screenshots/20260703-genomi-saved-evidence-recheck-copy-check.png)

Live Genomi checkpoint after tightening persisted/display-only follow-up copy.
The fresh workspace confirms the portal shell and Evidence sources surface are
styled and user-facing; the exact persisted saved-evidence handoff is covered
by frontend model tests because it requires replayed stored history.

![Reference workspace saved evidence comparison](screenshots/20260703-reference-workspace-saved-evidence-comparison.png)

Reference science-workspace checkpoint for the same saved-evidence pass. The
relevant behavior is still the same: work steps and generated objects sit near
the conversation and can be revisited without exposing event names as the
primary user model.

![Genomi Variant source grouped form](screenshots/20260703-genomi-variant-source-grouped-form-focused.png)

Live Genomi checkpoint after simplifying source-preparation forms. Variant
lookup now leads with the primary science input, `rsID`, while coordinate,
region, build, and approved-genome-context options stay collapsed under
`Other variant formats and source limits`.

![Reference source-form comparison](screenshots/20260703-reference-source-form-comparison.png)

Reference science-workspace checkpoint for the same source-form pass. The
reference keeps files, artifacts, and work steps as nearby workspace objects;
Genomi adapts that lesson by making source preparation concise and chat-bound
rather than exposing a flat operation schema.

![Genomi genome-state chat cleanup](screenshots/20260703-genomi-genome-context-chat-cleaned.png)

Live Genomi checkpoint after removing a leaked host-instruction turn from the
visible chat layer. A genome-state-only handoff now renders as `Genome state
included` plus a small `Using Genome ready` chip, and the no-question assistant
reply says what the user can do next. Diagnostic-only runtime status is hidden
from the main chat work-card surface.

![Genomi genome-state cleaned live regression](screenshots/20260703-genomi-genome-context-cleaned-live.png)

Live regression fixture after the starter-card refactor and terminology pass.
The frame was seeded with the old hidden genome-state instruction and diagnostic
events; the UI renders only `Genome state included`, `Using Genome ready`, and a
short next-step reply. The screenshot confirms there is no visible
`Attached material`, `runnable`, leaked host prompt, or diagnostic-only work
card.

![Genomi conversation rail display request](screenshots/20260703-genomi-conversation-rail-display-request.png)

Live desktop checkpoint after adding server-owned `display_request` to public
frame summaries. The stored raw request still preserves the original host run
input, but the left conversation rail uses `Genome state included` instead of
the hidden genome-boundary instruction. The same capture confirms the Research
workspace and Files & Artifacts pane remain side by side on desktop.

![Genomi target-evidence starter source entry](screenshots/20260703-genomi-target-evidence-starter-source-entry.png)

Live Genomi checkpoint after making all first-run starter cards route to real
workspace actions. The public-evidence starter is now `Target evidence report`;
clicking it opens Evidence sources, selects the target-report source, and uses
source-form state instead of dropping an instruction prompt into chat.

![Reference starter/workspace comparison](screenshots/20260703-reference-workspace-starter-source-entry-comparison.png)

Reference science-workspace checkpoint for the same alignment pass. The useful
pattern is not the exact content: the user starts from a research task in chat,
and files/artifacts/work stay adjacent as workspace objects. Genomi adapts that
by making first-run cards open source/workspace entries that can feed chat.

![Genomi active genome include handoff](screenshots/20260704-genomi-active-genome-responsive-fixed.png)

Live Genomi checkpoint after making Active genome a visible workspace object
instead of a generic readiness chip. The topbar shows the active genome
identity and wraps the switch/add controls at the narrow viewport. The Genome
panel action includes the active genome in the composer and focuses the
research question flow instead of submitting a genome-only turn.

![Genomi mobile Files section navigation](screenshots/20260704-genomi-mobile-files-section-and-nav-fixed.png)

Live Genomi checkpoint after tightening narrow-viewport workspace navigation.
Selecting `Files` hides the Research pane and shows only the Files & Artifacts
workspace section. This preserves the split research workspace on desktop while
making mobile nav behave as real section navigation rather than a scroll past
unrelated panels.

![Genomi mobile active genome minimal nav](screenshots/20260704-genomi-mobile-active-genome-minimal-nav.png)

Live Genomi checkpoint after making the mobile default strip product-facing.
The topbar names the active genome and exposes `Switch` and `Add`; the mobile
workspace strip starts with only `Research`, `Files`, and `Genome`. Empty
secondary panes such as work trail and evidence sources stay hidden until real
work or source-preparation state makes them useful.

![Genomi include active genome handoff](screenshots/20260704-genomi-include-active-genome-handoff.png)

Live Genomi checkpoint after changing active-genome handoff from a standalone
ask action to an include action. Clicking `Include active genome` returns to
Research, shows the active-genome material in the composer, focuses the
question field, and does not submit a genome-only turn.

![Genomi Add genome source form](screenshots/20260704-genomi-add-genome-source-form.png)

Live Genomi checkpoint after fixing the Add genome path. The topbar `Add`
control opens Evidence sources, selects `Add genome file`, and leaves the chat
composer empty. This keeps genome intake as a workspace/source action rather
than a hidden prompt.

![Genomi Add genome source form full page](screenshots/20260704-genomi-add-genome-source-form-full.png)

Full-page companion capture for the same Add genome state, showing the selected
source row and the source form in one artifact for later comparison.

![Genomi active genome identity controls](screenshots/20260704-genomi-active-genome-identity-switch-add.png)

Current live checkpoint for the active-genome header. The header names the
active genome object, shows safe build/source/readiness/profile context, and
keeps `Switch` and `Add` as direct controls. A generic readiness label is not
accepted as the default workspace state.

![Genomi Files and Artifacts library copy](screenshots/20260704-genomi-files-artifacts-library-copy.png)

Live checkpoint after aligning the Library surface vocabulary. The project pane
is `Files & Artifacts`, empty states talk about files and artifacts, and the
preview placeholder asks the user to select a file or artifact instead of a
generic result or output.

![Genomi workspace files generated records](screenshots/20260704-genomi-workspace-files-generated-records.png)

Live checkpoint after grouping generated workspace files by the research object
they represent. Files linked to produced artifacts appear under `Generated
records` and use `Generated record` row metadata, while ordinary project notes
remain grouped by folder. This is a partial Genomi-native Library step, not yet
the full session/run grouping seen in the reference portal.

![Genomi workspace files assistant turn groups](screenshots/20260704-genomi-workspace-files-assistant-turn-groups.png)

Follow-up checkpoint for generated workspace records with real artifact origin
state. Generated files now group as `Created in assistant turn 1` and `Created
in assistant turn 2`, while ordinary notes stay in their folder group. The
browser body does not expose run ids or frame ids; those remain hidden origin
state used only to organize the research library.

![Genomi workspace file identity guard](screenshots/20260704-genomi-workspace-file-identity-guard.png)

Live checkpoint after making generated workspace-file links prove current file
identity. `reports/current.txt` still appears as a generated record with
`Open artifact` and `View in chat`, while same-name edited `reports/stale.txt`
appears only as a research file. The UI does not expose run ids or
Genomi-home storage metadata.

![Genomi artifact review status card](screenshots/20260704-genomi-artifact-review-status-card.png)

Live checkpoint after surfacing current artifact-version review state in the
Library card. The artifact list endpoint now carries the current review summary,
so the card can show `Review passed` without requiring the user to open the
artifact detail pane first.

![Genomi artifact producing work step](screenshots/20260704-genomi-artifact-producing-work-step-focused.png)

Live checkpoint after persisting a version-owned artifact producing work step.
The topbar names the active genome and exposes `Switch` / `Add`, while the
artifact Work trail tab shows `Work that produced this artifact` and a
`Produced artifact` step for the report. This is the Genomi-native version of
artifact provenance without exposing packet mechanics or calling it an
execution log.

![Genomi artifact producing work step full page](screenshots/20260704-genomi-artifact-producing-work-step-full.png)

Full-page companion capture for the same producing-work-step state.

![Genomi artifact Work trail anchor](screenshots/20260704-genomi-artifact-work-trail-anchor.png)

Live checkpoint after adding exact artifact-event anchors to version-owned
Work trail steps. The visible card still reads as `Produced artifact` with
ordinary `Open artifact` and `View in chat` actions. The `View in chat` link
now carries hidden `highlight_run` and `highlight_step` route state to focus
the producing Work trail card, without exposing event ids as product copy.

![Genomi active genome switcher](screenshots/20260704-genomi-active-genome-switcher.png)

Live checkpoint after replacing the generic active-genome ready state with a
real genome control. The topbar names the active genome, shows safe
build/source/readiness/profile context, and exposes direct `Switch` and `Add`
actions. The Genome pane shows the current genome, privacy boundary, known
genome count, and inactive genomes with `Use this genome` actions. The rendered
page no longer contains the literal `Genome ready` fallback.

![Genomi active genome visible selector](screenshots/20260704-genomi-active-genome-visible-selector.png)

Live in-app-browser checkpoint for the default workspace header after the
active-genome fix. The visible state names `Active genome: genome computer`,
shows build/source/readiness/profile context, exposes `Switch` and `Add`, and
does not render `Genome ready`.

![Genomi active genome switch/add flow](screenshots/20260704-genomi-active-genome-switch-add-flow.png)

Live in-app-browser checkpoint after opening the active-genome switcher. The
Genome pane shows the current active genome, privacy boundary, known genome
count, `Add genome`, and inactive genomes with `Use this genome`.

![Genomi active genome current header object](screenshots/20260704-genomi-active-genome-header-object-current.png)

Live checkpoint on `127.0.0.1:8863` after user feedback that `Genome ready`
is not useful product information. The header names the active genome,
shows build/source/readiness/profile context, and keeps `Switch` and `Add`
available without exposing raw genome paths or technical packets.

![Genomi active genome header switch add genome](screenshots/20260704-genomi-active-genome-header-switch-add-genome.png)

Live checkpoint after making the topbar controls explicit. The header names
`Active genome: genome computer`, keeps `Switch` available, and labels the
second action `Add genome` rather than the ambiguous `Add`. A DOM check
confirmed the rendered body does not contain `Genome ready`.

![Genomi artifact Review run history](screenshots/20260704-genomi-artifact-review-run-history-visible.png)

Live in-app-browser checkpoint for the artifact Review tab after a completed
deterministic check run. The tab shows version checks, `Check run 1`, warning
status, and the explicit limit that these are artifact/evidence-boundary
checks, not clinical validation.

![Genomi evidence source card actions](screenshots/20260704-genomi-evidence-source-actions-visible.png)

Live in-app-browser checkpoint after simplifying the Evidence sources setup
panel. Selecting `Target evidence report` shows source purpose, target chips,
source limits, and two distinct actions: `Include source` for adding source
context to chat, and `Ask now` for immediately submitting through the normal
chat path. The setup panel no longer shows the old `Use in chat` /
`Draft question` action pair.

![Genomi permission approval card](screenshots/20260706-genomi-permission-approval-card.png)

Fixture checkpoint for the portal-owned permission approval surface. The
default card reads `Permission needed` and `Read current Genomi context`, with
`Approve access and retry` as the primary action. A browser DOM check confirmed
the visible fixture text does not contain a raw `mcp__genomi__` tool id.
This fixture is superseded by the workspace-scoped permission checkpoint below;
the current action is `Allow for this workspace` and the run pauses instead of
being presented as a failed turn.

![Genomi composer genome evidence mode](screenshots/20260706-genomi-composer-genome-evidence-mode.png)

Live checkpoint after adding a turn-level genome evidence boundary to the
composer. This screenshot is now superseded: the visible per-turn genome mode
selector was removed because it exposed routing machinery as product UX.
A DOM check confirmed the visible page text does not expose `genomeContextMode`
or raw MCP tool names.

![Genomi clean host-agent answer](screenshots/20260710-genomi-clean-answer-permission-and-files.png)

Live browser checkpoint after separating Claude's intermediate narration from
the research answer. The transcript shows the user's question and one bounded
answer; skill loading, retries, shell failures, and progress prose remain in
the work trail. The active genome stays visible as workspace state rather than
a per-turn mode selector.

![Genomi unified files workspace](screenshots/20260710-genomi-unified-files-workspace.png)

Live browser checkpoint after removing the overlapping artifact inventory.
Project-relative files appear once, linked generated records retain `Open
artifact` and `View in chat`, and the selected file opens directly below with
version, origin, work-trail, source-limit, and review records. The normal view
does not display `$GENOMI_HOME` or a second library search.

![Genomi workspace-scoped active genome](screenshots/20260710-genomi-workspace-scoped-genome.jpg)

Live browser checkpoint after binding Active Genome Index access to the portal
project. This workspace names `Active genome: george`, while a second workspace
on the same Genomi installation shows `Choose active genome`. Host-agent checks
through each workspace's isolated MCP context returned `george` for this
project and no active genome for the unbound project. Switching projects also
clears the previous transcript before opening the target workspace.

![Reference durable session identity](screenshots/20260710-reference-conversation-identity.jpg)

Authenticated local reference capture of the selected session's action menu.
The session title is the stable left-rail identity; rename, move, export,
artifact download, notebook, and delete are secondary actions. For Genomi this
supports durable conversation naming and rename now, while move/delete remain
gaps until corresponding workspace state and recovery behavior exist.

![Genomi durable conversation identity](screenshots/20260710-genomi-conversation-identity.jpg)

Live Genomi checkpoint after adding durable conversation titles, bounded rail
search, active-title display, and rename. `Active genome workspace check`
appears in both the rail and chat header and persisted after a full route
reload. The active genome remains a separate workspace object in the top bar.

![Reference artifact quick preview](screenshots/20260710-reference-artifact-quick-preview.jpg)

Authenticated local reference capture after clicking an artifact card in the
Files library. The library and active session remain behind a near-full-screen
preview; only More, open in split view, download, and close are immediate.

![Reference artifact split view](screenshots/20260710-reference-artifact-split-view.jpg)

The same artifact after explicit promotion to split view. The producing
conversation remains on the left, the artifact dominates the right, and Files
and the selected artifact remain workspace tabs rather than separate products.

![Genomi file quick preview](screenshots/20260710-genomi-file-quick-preview.jpg)

Live Genomi translation of the quick-preview hierarchy. The project file opens
over the library with `Use file`, More, and Close; generated-record details,
origin chat, and starting a new conversation are secondary actions.

![Genomi selected artifact workspace](screenshots/20260710-genomi-selected-artifact-workspace.jpg)

Live Genomi selected-object state. The producing conversation remains visible,
the file list is replaced by the generated record, and `Back to files` restores
the library. Default readiness badges and duplicate result-history controls are
absent while backed provenance tabs remain available.

![Local reference project workspace](screenshots/20260710-claude-science-local-project-workspace.jpg)

Authenticated local project checkpoint. Session navigation stays narrow, the
conversation remains the continuous work surface, generated artifacts appear
as visual thumbnails in the answer, and the selected image becomes the
dominant right-pane object without replacing the conversation.

![Genomi conversation reviewer findings](screenshots/20260710-genomi-conversation-reviewer-findings.jpg)

Live Genomi conversation-review checkpoint. The reviewer is attached to the
conversation, reports only actionable findings in its expanded state, links
back to the reviewed claim, and can attach one compact finding to the next
message. Internal tool and Active Genome Index field names are not shown in the
composer attachment.

![Local reference scoped permission run](screenshots/20260714-local-reference-scoped-permission-run.jpg)

Authenticated local reference checkpoint during the paired rs429358 research
task. Permission is presented as an interruption inside the active session,
with the requested capability and scope attached to the decision rather than
reported as a failed research result.

![Genomi workspace-scoped permission](screenshots/20260714-genomi-workspace-scoped-permission.jpg)

Live Genomi checkpoint for the same research task. The pending connector
request stays expanded, names the user-facing capability, and offers one
workspace-scoped allowance. The source run can be paused and replaced
immediately without duplicating the user's message.
