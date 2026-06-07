---
name: genomi-decode
description: |
  Activate this skill for "/genomi decode", "decode my genome", "decode my
  DNA", "show me the dashboard", "the Genomi dashboard", "full report",
  "one-shot rundown", or any all-at-once request that asks Genomi to
  compose every capability's findings into a single artifact. This is the
  whole-genome dashboard kicker — it sweeps every relevant Genomi capability
  in one shot, not a per-target lookup.

  Composes evidence from every relevant Genomi capability into a single
  self-contained Genomi Dashboard.html and returns localhost serve metadata.
  Active genome required.
tools:
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
and the PGx ops protects `decode.render_dashboard`. If no active genome is
selected the op fails with `active_genome_index_required`; if approval has not
been granted it fails with `active_genome_index_approval_required`.

## Reconcile Active Genome Index lifecycle before gathering panels

Call `genomi.describe_context` first. If `active_genome_index.active_genome_index_readiness.status`
is `needs_reparse` or `schema_too_new`, **handle the lifecycle before
gathering any panel evidence** — do not proceed with a stale Active Genome Index and
silently bound the panels.

The full procedure lives in the Active Genome Index skill under the lifecycle
guidance for `needs_reparse` and `schema_too_new`.
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

## Dashboard Build

Call `decode.render_dashboard`. Decode owns panel gathering, panel shaping,
and rendering. The agent may choose dashboard categories through structured
parameters such as `panels` and select declared score/domain options. Omitted
`panels` means every dashboard category. The agent does not assemble panel
evidence and does not ask which PGx route to run; decode owns that work.

The renderer normalizes native upstream-op shapes internally:

- `overview` — adapts `active_genome_index.summarize` output;
  snake_case keys (`genome_build`, `nickname`, `active_genome_index_completed_at`,
  `nearest_reference_groups`) are mapped automatically.
- `variants` — adapts scan rows; both `clinvar.scan_candidates`
  shape (`{variant, clinvar, genes}`) and `clinvar.match_variants` JSONL
  shape (`{sample_variant, clinvar}`) are handled.
- `nutrigenomics` — adapts `nutrigenomics.retrieve_domain_markers`; it extracts
  `gene.symbol`, `variant.rsid`, `established_effect.claim` (→ `recommendation`),
  `evidence_tier`, and domain label (→ `marker`).
- `ancestry` — adapts `ancestry.estimate_population_context`.
- `pgx` — adapts native PharmCAT artifact summaries and medication-review
  results into PGx cards.
- `risk` — adapts native `prs.calculate_score` results into risk-score cards.
- `variants_all` — uses the ClinVar matches JSONL path materialized by decode.

If no PRS scores are installed in the user's library, the builder supplies a
typed empty risk state so stale risk evidence is cleared rather than preserved.

## Verify before claiming success

The renderer's response is the source of truth:

- `panels_rendered`: panels that landed with real data.
- `panels_empty`: panels with no usable evidence — they render as
  category-specific unavailable states in the UI.
- `evidence_build.panels_running`: panels still running in a background job.
- `evidence_build.panel_states`: per-panel source status, including PGx
  background job ids and check operations when applicable.

Read `panels_empty` and any `evidence_build.panel_states` before telling the
user the dashboard is ready. Surface incomplete categories honestly with their
typed state.

## Refresh vs. reuse

Call `decode.render_dashboard` again to refresh the dashboard after installing
libraries or changing category selections. Panels without usable evidence render
as category-specific unavailable states.

## Output location

By default the artifact is written to
`<tmp>/genomi-dashboards/<sample>/dashboard.html`. The user may override
`output` with any absolute filesystem path; the parent directory is created on
demand.

## Serving the dashboard

`decode.render_dashboard` returns a `serve` block:

```json
{
  "serve": {
    "status": "started",
    "directory": "...",
    "filename": "dashboard.html",
    "port": 8766,
    "url": "http://127.0.0.1:8766/dashboard.html",
    "command": "python3 -m http.server 8766 --bind 127.0.0.1 --directory ..."
  }
}
```

Normal runtime calls start a local static dashboard server automatically and
choose a free localhost port. Tell the user `serve.url`. If `serve.status` is
`ready_to_start` or `start_failed`, run `serve.command` as a fallback and then
tell the user the adjusted URL.

## Boundaries

- Active Genome Index session approval is required.
- Decode owns panel evidence collection and shaping for the dashboard artifact.
- The artifact is a single self-contained HTML file that renders fully offline
  — React/ReactDOM and the precompiled app JS are inlined, no CDN, no
  in-browser Babel. (One optional Google Fonts stylesheet is referenced; it
  falls back to system fonts offline and carries no genome data.) It opens by
  double-click; the local server is only there so the user can hit a URL.

## Tool

### decode.build_dashboard_evidence

Support operation used by `decode.render_dashboard` to inspect panel readiness
and gaps. Normal dashboard requests should call `decode.render_dashboard`.

### decode.render_dashboard

Build, shape, and render the Genomi Dashboard HTML artifact from the approved
Active Genome Index. Returns
`{ status, dashboard_path, panels_rendered, panels_empty, serve }` plus the
standard `evidence_envelope`. The `serve` block tells the host agent how to
expose the dashboard at a localhost URL — see the "Serving the dashboard"
section above.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.
