---
name: genomi-decode
version: 1.0.0
description: |
  Activate this skill for "/genomi decode", "decode my genome", "decode my
  DNA", "show me the dashboard", "the Genomi dashboard", "full report",
  "one-shot rundown", or any all-at-once request that asks Genomi to
  compose every capability's findings into a single artifact. This is the
  whole-genome dashboard kicker — it sweeps every relevant Genomi capability
  in one shot, not a per-target lookup.

  Composes evidence from every relevant Genomi capability into a single
  self-contained Genomi Dashboard.html, then returns a localhost serve
  command the host agent runs in the background. Active genome required.
tools:
  - decode.build_dashboard_evidence
  - decode.render_dashboard
mutating: true
---

# Genomi Decode

The `/genomi decode` kicker tells the agent to assemble every relevant Genomi
capability's evidence about the user's active genome and emit a single
self-contained `Genomi Dashboard.html` artifact. Activate this skill whenever
the user types `/genomi decode`, asks for "the dashboard", asks to "decode my
genome", or asks for a one-shot full report.

## Activation

This skill requires an Active Genome Index session and explicit approval to
read it. The same approval gate that protects `variant.resolve`, `clinvar.*`,
and the PGx ops protects `decode.build_dashboard_evidence` and
`decode.render_dashboard`. If no active genome is selected the op fails with
`active_genome_index_required`; if approval has not been granted it fails with
`active_genome_index_approval_required`.

## Reconcile Active Genome Index lifecycle before gathering panels

Call `genomi.describe_context` first. If `active_genome_index.active_genome_index_readiness.status`
is `needs_reparse` or `schema_too_new`, **handle the lifecycle before
gathering any panel evidence** — do not proceed with a stale Active Genome Index and
silently bound the panels.

The full procedure lives in `skills/active-genome-index/SKILL.md` under
*"Lifecycle: handle `needs_reparse` and `schema_too_new` automatically"*.
Summary for decode:

1. If `needs_reparse` and `availability.agi_intake_source_path` is true, call
   `genomi.parse_source({"source": active_genome_index.agi_intake_source_path})` without
   prompting. Routine maintenance.
2. If `needs_reparse` and the source path is gone, ask the user once for
   the current path and parse that. Don't continue with a stale Active Genome Index.
3. If `schema_too_new`, the user's runtime is out of date — tell them to
   upgrade Genomi, stop.
4. Only after `active_genome_index_readiness.status == "complete"` call the
   decode operation.

## Default build

For a brand-new dashboard, call `decode.render_dashboard` with no `evidence`
parameter. The operation first runs the code-owned
`decode.build_dashboard_evidence` path, then renders the returned
`render_params`.

Call `decode.build_dashboard_evidence` directly only when you need to inspect
or reuse the built panel states before rendering. It returns:

- `render_params.evidence`
- `render_params.variants_all_source` when ClinVar matches were materialized
- `panel_states`, `panels_ready`, `panels_empty`, and `panels_blocked`

Do not manually orchestrate the default seven-panel sweep in prompt text. Use
explicit panel evidence only for a targeted refresh or user-supplied override.

The renderer normalizes common upstream-op shapes automatically:

- `overview` — pass `active_genome_index.summarize` output directly;
  snake_case keys (`genome_build`, `nickname`, `active_genome_index_completed_at`,
  `nearest_reference_groups`) are mapped automatically.
- `variants` — pass scan rows directly; both `clinvar.scan_candidates`
  shape (`{variant, clinvar, genes}`) and `clinvar.match_variants` JSONL
  shape (`{sample_variant, clinvar}`) are handled by the normalizer.
- `nutrigenomics` — pass the `markers` array from
  `nutrigenomics.retrieve_domain_markers` directly; the normalizer extracts
  `gene.symbol`, `variant.rsid`, `established_effect.claim` (→ `recommendation`),
  `evidence_tier`, and domain label (→ `marker`) from the nested catalog records.
- `ancestry` — pass `ancestry.estimate_population_context` output directly.
- `pgx` — pass `pharmacogenomics.run_pharmcat` output directly. The renderer
  accepts native PharmCAT artifact summaries and medication-review results, then
  adapts calls, phenotypes, diplotypes, and recommendations into PGx cards.
- `risk` — pass the list of native `prs.calculate_score` results directly as
  `evidence.risk`. The renderer adapts `polygenic_score`, `sample_qc`, and
  `score_result` into risk-score cards.

For the all-variants explorer panel, pass a file path via `variants_all_source`
instead of the evidence dict — the renderer reads and normalizes the JSONL
file server-side.

If no PRS scores are installed in the user's library, the builder supplies a
typed empty risk state so stale risk evidence is cleared rather than preserved.

## Verify before claiming success

The renderer's response is the source of truth:

- `panels_rendered`: panels that landed with real data.
- `panels_empty`: panels with no usable evidence — they render as the
  "Not gathered yet" placeholder in the UI.

A panel you omit (absent, or supplied as empty `{}`/`[]`) renders as the
"Not gathered yet" placeholder — that is a valid partial dashboard. Read
`panels_empty` before telling the user the dashboard is ready and surface
those panels honestly ("PGx and Risk weren't gathered — ask if you want
them next").

A panel you supply with real content must satisfy the panel schema after
normalization. Object panels require their key fields (overview:
`sampleId` + `variantCount`; ancestry: `dominantAncestry` + `neighbors`);
list panels require row objects with at least one recognized dashboard field.
PGx rows also require `gene`; risk rows also require `trait`. If supplied
content maps to none of those fields, the renderer raises
`panel_schema_mismatch` naming the panel and missing field — it does not render
a blank stat. When you hit it, fix the evidence mapping and re-render rather
than dropping the panel.

## Refresh vs. reuse

If the current chat already holds materially current evidence for a panel
(same active genome, no upstream library version bump, no user-driven change
in question scope), reuse it directly — do not redispatch the upstream op.
When only one or two panels need refresh, call `decode.render_dashboard` with
`mode: "update"` and only the refreshed panels; the previously-inlined
evidence for other panels is preserved.

For a brand-new dashboard, call `mode: "full"` and omit `evidence` unless you
are deliberately overriding the code-owned builder output. Panels not supplied
render as empty cards with a "Not gathered yet" placeholder.

## Output location

By default the artifact is written to
`<tmp>/genomi-dashboards/<sample>/dashboard.html`. The user may override
`output` with any absolute filesystem path; the parent directory is created on
demand.

## Serving the dashboard (agent runs this, not the MCP server)

`decode.render_dashboard` returns a `serve` block:

```json
{
  "serve": {
    "directory": "...",
    "filename": "dashboard.html",
    "port": 8765,
    "url": "http://127.0.0.1:8765/dashboard.html",
    "command": "python3 -m http.server 8765 --bind 127.0.0.1 --directory ..."
  }
}
```

After the render call returns, the host agent:

1. Runs `serve.command` **in the background** using the host's standard
   background-process pattern (Claude Code: `Bash` with `run_in_background=true`;
   Codex: append `&`; etc.). Do not block the conversation on it.
2. Tells the user the URL on a single line:
   `Your Genomi dashboard is live at http://127.0.0.1:8765/dashboard.html.`
3. If port 8765 is busy, pick a free port and rewrite the URL.

The MCP server itself does not open ports. The dashboard is a static HTML
file; the agent serves it because the host process is where background
processes belong.

## Boundaries

- Active Genome Index session approval is required.
- Omitted `evidence` uses the code-owned builder path. Explicit `evidence`
  remains supported for targeted updates and overrides.
- The artifact is a single self-contained HTML file that renders fully offline
  — React/ReactDOM and the precompiled app JS are inlined, no CDN, no
  in-browser Babel. (One optional Google Fonts stylesheet is referenced; it
  falls back to system fonts offline and carries no genome data.) It opens by
  double-click; the local server is only there so the user can hit a URL.

## Tool

### decode.build_dashboard_evidence

Build dashboard panel evidence from the approved Active Genome Index using
existing capability operations. Returns `render_params` plus panel state
metadata.

### decode.render_dashboard

Render the Genomi Dashboard HTML artifact. If `evidence` is omitted, it first
builds panel evidence through `decode.build_dashboard_evidence`. Active genome
required. Returns
`{ status, dashboard_path, panels_rendered, panels_empty, serve }` plus the
standard `evidence_envelope`. The `serve` block tells the host agent how to
expose the dashboard at a localhost URL — see the "Serving the dashboard"
section above.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.
