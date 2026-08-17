# Unreleased

- Added a host-owned GenomiLab developer preview. Claude Code, Codex, or another
  compatible MCP host keeps its native conversation, planning, subagents,
  streaming, follow-ups, and task controls while direct `genomilab.*`
  operations persist approved research evidence, hypotheses, and briefs.
- The loopback Research Desk is now a patient-onboarding, scoped-approval,
  provider-setup, and committed-domain-event monitoring portal. It requires a
  current user with a query-ready Active Genome Index; VCF/gVCF and other
  source intake stays in core Genomi and is reused across investigations.
- Paperclip exposes narrow investigation-scoped literature, regulatory, and
  trial-registry discovery only when owner deployment authorization, an
  independent patient-data contract, and exact disclosure approval all pass.
  A verified API key alone advertises no live route.
- Biohub ESM and Proto connection checks remain setup-only and never count as
  scientific execution. Separate bounded ESM substitution and Proto blinded
  experiment-design operations run only through configured local,
  network-disabled executors; an absent executor returns explicit
  `unavailable` without creating an artifact. Their outputs are round-bound
  nonclinical research artifacts and are ineligible as evidence, hypothesis or
  brief support, answer-readiness, treatment content, or clinician export.
- Added two disjoint synthetic patient fixtures and end-to-end isolation tests.
- Default-user selection is metadata-only; previously imported Active Genome
  Index data now always requires explicit current-session read approval.
- Runtime context, registry, and background-job state now use private file
  permissions, atomic JSON writes, and symlink refusal.
- Decode dashboard generation no longer probes a socket when no server will be
  started.

# Genomi 0.1.0 Release Notes

Released July 2026.

Genomi 0.1.0 is the first public release. These notes focus on release-specific
changes and upgrade-relevant behavior; see `README.md` for the broader product
overview, source support, privacy model, and setup flow.

## Highlights

- First public package metadata and install/update path for `genomi`.
- Local decode dashboard generation is available for broad first-pass genome
  review.
- Active Genome Index parsing now supports variant-ready gVCF imports with
  background reference-block completion.
- `.genome/1.0` bundle intake is supported alongside the source formats
  described in the README.
- Pharmacogenomic and ClinVar review paths now report clearer evidence state,
  missing-source state, and sample-specific context.
- Install/update runs are idempotent, so re-running `genomi install` or
  `genomi update` is the supported maintenance path.

## Decode Dashboard

- Dashboard panels now distinguish ready, empty, blocked, and unavailable
  states.
- Missing libraries, unavailable sources, or insufficient overlap are shown as
  limitations instead of negative findings.
- Pharmacogenomic findings are ordered by finding severity.
- Journal content is no longer included in the dashboard; the dashboard focuses
  on current evidence panels.
- Dashboard output is staged for local browser viewing.

## Pharmacogenomics And ClinVar

- Medication-response review separates guideline evidence, label evidence,
  association evidence, sample-specific evidence, and missing evidence more
  clearly.
- PharmCAT workflows handle preflight checks, generated artifacts, imported
  results, calls-only TSV files, and VCF header edge cases more reliably.
- ClinVar matching preserves the connection between public assertions and the
  observed allele evidence from the local genome index.
- Missing optional evidence libraries are reported as blocked evidence scope,
  not as absence of findings.

## Genome Indexing

- Source detection is content-based and can handle compressed or archived inputs.
- gVCF parsing becomes usable for variant interpretation before reference-block
  processing is fully complete.
- Consumer-array no-calls and downstream genotype matching have clearer
  behavior.
- VCF export for downstream pharmacogenomic workflows now normalizes metadata
  and invalidates stale export caches.

## Install And Update

`genomi install` and `genomi update` are the same update path. Re-running either
command is safe and will only refresh what needs refreshing unless a forced
download is requested.

The updater can:

- Refresh the Genomi runtime.
- Install or update selected public reference libraries.
- Repair host-agent skill links.
- Refresh public retrieval indexes.
- Keep older local Active Genome Index records aligned with the current runtime.

Genomi now also follows modern data-directory defaults when available, while
still supporting `GENOMI_HOME` for explicit installs.

## Known Limits

- Genomi is still experimental, and the tool surface may continue to change.
- Some evidence areas require optional public libraries or external tools before
  they can answer.
- External public sources may be temporarily unavailable.
- Missing data, missing libraries, or low overlap are limitations, not negative
  evidence.
- Polygenic, ancestry, nutrigenomic, and common-trait findings should be
  interpreted qualitatively unless a cited source provides a validated number.
