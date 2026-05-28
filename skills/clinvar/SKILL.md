---
name: clinvar
version: 1.0.0
description: |
  Build and inspect ClinVar exact-match evidence and candidate inventories.
  Use for clinical labels, VUS/conflict, carrier context, and drug-response rows.
tools:
  - genomi.check_libraries
  - clinvar.match_variants
  - clinvar.scan_candidates
  - variant.gather_allele_context
  - variant.gather_gene_context
mutating: true
---

# ClinVar Evidence

Use this skill when the user asks about clinical labels, carrier findings,
pathogenic/likely pathogenic entries, VUS, conflicting classifications, drug
response, risk-factor labels, or ClinVar-derived discovery.

## Goal

Build a candidate landscape from exact ClinVar matches. Use the candidate
inventory as triage input for focused evidence gathering.

> **Convention:** See `skills/conventions/evidence-quality.md`.

## Contract

- ClinVar matches provide exact/static evidence for source-backed
  interpretation.
- Exact matching requires the optional build-specific library
  `clinvar-grch38` or `clinvar-grch37`.
- Candidate inventories are triage aids.
- `clinvar.scan_candidates` returns an evidence view, grouped support,
  warnings, and coverage; use those fields rather than inferring priority from
  prose.
- If ClinVar matches are missing, `clinvar.scan_candidates` materializes them
  from the Active Genome Index before building the candidate inventory.
- VUS, conflicts, and low-review assertions are downgraded unless reviewed
  source evidence supports a stronger claim.
- Drug-response rows use pharmacogenomic source context before actionability is
  implied.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### clinvar.match_variants

Materialize exact ClinVar matches for comparable Active Genome Index variants using the installed build-specific ClinVar library.

**Use when**: After an Active Genome Index and the matching build-specific ClinVar library are available to materialize exact ClinVar/sample matches.

**Why necessary**: ClinVar matching is library-scoped materialization; it turns installed public ClinVar rows into exact matches for an Active Genome Index without forcing every genome-artifact task to run ClinVar.

### clinvar.scan_candidates

Build a deterministic candidate inventory from exact ClinVar matches, materializing those matches from the Active Genome Index when needed.

**Use when**: Broad Active Genome Index disease or risk triage when exact ClinVar candidate inventory is needed.

**Why necessary**: Broad disease triage needs a bounded ClinVar candidate inventory instead of ad hoc spot checks over a large genome file. It performs missing match materialization internally before candidate scanning.

## Interpretation Rules

- Pathogenic/likely pathogenic labels need zygosity, inheritance, population
  frequency, gene-disease context, and source quality.
- VUS and conflicting labels use uncertainty/conflict wording.
- Drug-response labels require pharmacogenomic guideline context before clinical
  actionability is implied.
- Common association/risk/protective labels usually provide limited context for
  personal common-disease risk.

## Routing Checks

- Prioritize ClinVar matches by actionability, review status, uncertainty,
  population context, inheritance, and zygosity.
- If a ClinVar operation returns `status="requires_library_install"`, explain how
  the named library helps this request and ask before installing it.
- Treat ClinVar condition strings as database labels that need interpretation.
- Keep the whole candidate inventory local; send selected public targets to
  Journal source-review memory.
