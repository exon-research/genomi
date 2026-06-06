---
name: variant-evidence
description: |
  Answer specific rsID, allele, gene, region, genotype, and absence/callability
  questions using explicit session context or public evidence.
tools:
  - genomi.describe_context
  - variant.resolve
  - active_genome_index.classify_genotype_support
  - active_genome_index.classify_region_callability
  - variant.gather_allele_context
  - variant.gather_gene_context
mutating: true
---

# Variant And Gene Evidence

Use this skill when the user asks about a specific rsID, allele, gene, genomic
region, observed genotype, absence/reference claim, or whether the user's own
Active Genome Index supports a claim.

## Goal

Answer with the smallest evidence packet needed. Use sample support and
callability checks when the claim requires them.

Run `genomi.describe_context` first if the Active Genome Index is unknown. If an active
Active Genome Index exists, use it for sample-specific lookup. With public-only
context, answer from public/source evidence or ask the user for a file only
when personal evidence is required.

Use `variant.resolve` as the umbrella first lookup when the user's target is an
rsID, coordinate, exact allele, locus, region, or mixed text. It resolves
flexible input, checks the Active Genome Index, gathers existing deterministic
ClinVar/population/reviewed-source facts, and can search explicitly selected
accessible Active Genome Index records with `agi_id` or `include_known_active_genome_indexes`.

> **Convention:** See `skills/conventions/evidence-quality.md`.
> **Convention:** See `skills/_output-rules.md`.

## Contract

Contract:

- Personal variant claims are grounded in the selected Active Genome Index.
- Public-only variant answers are clearly marked public-only.
- Absence/reference claims require callability.
- Positive allele claims use genotype support when answer confidence matters.
- Medical meaning beyond static rows uses Journal source-review memory.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### active_genome_index.classify_genotype_support

Classify whether one exact allele has enough sample support to be used in a personal interpretation.

**Use when**: A user-specific interpretation depends on whether one exact allele is actually supported by Active Genome Index genotype/QC evidence.

**Why necessary**: A reported variant match still needs depth, genotype quality, and allele support before user-specific wording is justified.

**Example prompts**: Does this exact allele have enough support in my Active Genome Index?

**Result semantics**: Returns support_status and evidence_class; the host agent decides whether weak or missing support is a gap.

### active_genome_index.classify_region_callability

Classify whether a region can support reference or absence claims.

**Use when**: A negative, reference, absent-marker, or no-variant claim depends on whether the region was callable.

**Why necessary**: Absence claims require callability; a missing variant in a poorly covered region is not evidence of absence.

**Example prompts**: Can this region support saying a variant was absent?

**Result semantics**: Returns callability_status and support for negative/reference wording; the host agent writes the claim.

### variant.gather_allele_context

Gather existing sample, static, population, and reviewed research evidence for one allele.

**Use when**: The agent needs a consolidated context pack for one exact allele before interpreting or reporting it.

**Why necessary**: Variant reports need sample, static, population, and reviewed-research evidence gathered without recomputing unrelated evidence.

**Result semantics**: Combines stored sample/static/population/research evidence; missing sections are facts for the agent to interpret.

### variant.gather_gene_context

Gather existing sample, ClinVar, and reviewed research evidence for one gene.

**Use when**: a selected gene needs existing sample, ClinVar, and reviewed-research context before synthesis.

**Why necessary**: Gene-level interpretation needs gene-scoped context, which is different from one exact variant lookup.

**Result semantics**: Combines stored gene-scoped sample, static, and reviewed research evidence; absence of a section is not negative evidence by itself.

### variant.resolve

Resolve one variant target and return deterministic public, local sample, and stored evidence facts.

**Use when**: The user gives an rsID, chromosome coordinate, allele string, locus, region, or mixed variant text and needs deterministic facts before interpretation. The agent wants one lookup that can check the selected Active Genome Index and optionally approved previously parsed Active Genome Index records.

**Why necessary**: Precise variant questions need deterministic target resolution before public or personal evidence can be interpreted.

**Not for**: ranking population-trait candidate rsIDs; use gwas.compare_variant_associations for that task.

**Example prompts**: What is known about rs429358, and do I have it?

**Result semantics**: Returns resolved targets, local sample matches from Active Genome Index records, stored ClinVar/population/research facts, and target_inventory facts for host-agent synthesis. Previously parsed Active Genome Index records are searched only when agi_id or include_known_active_genome_indexes is supplied and scoped access is approved. ClinVar, Mendelian, stored research, and sample evidence are interpretation context, not population-trait lead-variant ranking evidence. target_inventory exposes resolved rsID, allele, sample, support, population, and reviewed-research facts; unanswered_answer_components identifies unresolved lookup components and missing inputs. The host agent decides whether any additional operation is relevant to the user's question.

## Evidence Requirements

- Positive personal allele claims use sample observation plus genotype support
  from `active_genome_index.classify_genotype_support` or a current private `genotype_support` row.
- Negative or reference claims use `active_genome_index.classify_region_callability`.
- Medical meaning beyond static rows uses the Journal source-review sub-skill
  in the source research skill and reviewed findings stored with
  `research.record`.
- Gene/variant background with public-only context uses `research.list_sources`,
  `research.query`, `research.search`, or public research.

## Gene Synthesis Checks

When `variant.gather_gene_context` is the selected evidence packet, cover only
the pieces supported by the returned data and reviewed sources:

- Gene function in the user's question context.
- Sample observations and zygosity limits.
- ClinVar/static database labels with informational interpretation wording.
- Inheritance, mechanism, and penetrance only when supported by reviewed
  sources.
- Population evidence tension when allele frequency affects interpretation.
- Shared public-source knowledge versus private user-specific interpretation.
- Citations for every finding that reaches report output.

Use explicit user/source evidence for phenotype, family history, medications,
and phase. Use source titles or URLs as citations, not evidence classes. Keep
medical language informational and include clinical-confirmation boundaries.

## User-Facing Answer Shape

Lead with whether the file contains/supports the allele or region claim. Then
explain what public evidence supports, its limitations, and what would reduce
uncertainty.

## Routing Checks

- Use callability for negative or reference claims.
- Use `variant.resolve` before narrower VCF or evidence tools when the input can
  be interpreted multiple ways or may exist in the Active Genome Index.
- Check ref/alt when rsID interpretation depends on the exact allele.
- Keep gene background separate from sample-specific interpretation.
- Use target-specific evidence packets for final interpretation.
