---
name: genomic-inquiry
version: 1.0.0
description: |
  Default entry for natural-language DNA questions. The host agent resolves
  intent, reads focused skills, calls narrow evidence tools, and adapts after
  inspecting tool output.
tools:
  - genomi.describe_context
mutating: false
---

# Genomic Inquiry

Use this skill as the default entry for natural-language DNA questions:
personal triage, "what matters in my genome?", "do I have this variant?",
variant/gene interpretation, GWAS-style questions, or public genomic background.

## Goal

Turn the user's question into the smallest useful evidence action. A genome
source is optional context. Use the Active Genome Index when present and relevant; with public-only context,
answer from public sources, GWAS, and shared reviewed evidence.

> **Convention:** See `skills/conventions/context-routing.md` before selecting
> Active Genome Index.
> **Convention:** See `skills/conventions/evidence-quality.md` before making
> personal or medical claims.

## Contract

Contract:

- User intent drives the selected evidence path.
- The host agent resolves intent from this skill pack and tool outputs.
- Personal claims use only explicitly selected session context.
- Public-source answers do not need a routine Active Genome Index status line.
- Tool outputs are inspected before choosing additional operations.
- Operation metadata and focused skills guide tool choice; tool results are
  evidence for the host agent to interpret.
- Candidate and ranking tools return evidence views, alternatives, warnings,
  coverage, and source-prior detail for the host agent to interpret.

## Agent Start

1. Use `genomi.describe_context` when the Active Genome Index is unknown.
2. Extract obvious fields from the user request: `source`, `agi_id`, user/profile
   nickname, `rsid`, `gene`, exact allele, phenotype, drug, condition, or topic.
3. Read the most specific `skills/<capability>/SKILL.md` (auto-loaded by Anthropic Claude Code Skills as `~/.claude/skills/genomi-<capability>/`), then call its capability tools through `genomi.invoke`.
4. Call one narrow tool and inspect its output before selecting additional
   evidence operations.

## Personal Source Triage

For "what matters in my genome?" or similar broad personal questions:

- If a source path is supplied, build/select it with `genomi.parse_source`
  when an Active Genome Index is needed. The supplied source path is approval to
  read that source for this session.
- Run `clinvar.scan_candidates` to build a deterministic ClinVar candidate
  inventory. If the build-specific ClinVar library is missing, ask before
  installing `clinvar-grch38` or `clinvar-grch37`.
- Inspect structured candidate guidance before selecting findings for follow-up
  or final interpretation.
- Drill into selected findings with `variant.gather_allele_context`,
  `variant.gather_gene_context`, `active_genome_index.classify_genotype_support`, or `active_genome_index.classify_region_callability`.

Group raw matches by actionability, clinical assertion strength,
uncertainty/conflict, carrier context, common-risk or trait context, and
limitations.

After `genomi.parse_source`, use the Active Genome Index for normal future inquiries.
Surface the original intake file path for rebuild or validation work.

## Specific Questions

- Personal rsID question with an Active Genome Index: use `variant.resolve` first.
- Personal exact allele question: use `active_genome_index.classify_genotype_support` and
  `variant.gather_allele_context` when allele support and source context are needed.
- Gene-level sample question: use `variant.gather_gene_context` and only make
  sample-specific statements for observed/sample-supported variants.
- Absence/reference claims require `active_genome_index.classify_region_callability`.
- Public variant/gene question with public-only context: use `research.list_sources`,
  `research.build_target_packet`, focused source review, and `research.record` when
  useful.
- Candidate genes: use the source-specific tool when the source family is clear:
  `phenotype.compare_gene_hpo_evidence` for HPO or single-subject phenotype
  matching, `gwas.compare_gene_associations` for explicit GWAS Catalog
  reported_gene/mapped_gene/source gene-field evidence,
  and `phenotype.compare_drug_target_evidence` for drug-target or mechanism evidence.
  `phenotype.retrieve_trait_gene_records` retrieves trait-to-gene records from integrated
  public sources and can be filtered by candidate genes. If several source
  families could answer the question, call the relevant source-specific tools
  separately and keep their evidence priors separate in the answer. GWAS
  Catalog mapped genes are not causal-gene assignments, and
  `association_only_not_causal` records cannot be the final support for a
  causal-gene answer.
- Analytical grounding: use `pathway.retrieve_members` for Reactome, KEGG, or
  Hallmark pathway member genes; `cell_type.retrieve_markers` for HPA,
  CellMarker, PanglaoDB, or ENCODE marker sources; and
  `region.retrieve_features` for local GENCODE/ENCODE interval overlaps.
- GWAS phenotype plus candidate rsIDs: read `skills/gwas-catalog/SKILL.md`, call
  `gwas.compare_variant_associations`, then select additional operations from the returned
  evidence. Variant lookup, ClinVar, Mendelian, sample, same-gene, or pathway
  context is follow-up context only; it cannot override the population-trait
  GWAS Catalog rsID ranking.
- Functional-genomics perturbation context plus candidate genes: read
  `skills/functional-genomics/SKILL.md`, call
  `functional_genomics.compare_gene_perturbation` for the normal native-retrieve,
  verify, and compare flow, and answer from verified perturbation-source evidence
  rather than generic co-mention.

## Outcome-Shaped Questions

Outcome-shaped questions ("will I get X?", "am I at higher risk for X?",
"how likely am I to X?", "will I go bald?") are answered by combining
capabilities that contribute orthogonal evidence to the same question.
The combination is question-dependent.

## Answer Contract

User-facing answers must include:

- The evidence classes used: sample observation, ClinVar/static source,
  population frequency, GWAS association, reviewed source, or limitation.
- Whether Active Genome Index evidence changed the result, limitation, blocker,
  or next action when that is material to the answer.
- The candidate evidence basis when present: source prior, direct versus adjacent
  or plausibility-only support, and any warnings.
- What matters for decision-making: answer support, genotype support, callability,
  source review, clinical confirmation, or user/clinical context.

Use informational medical language. Clinical decisions need clinician
confirmation. Personal risk percentages need cited source support. External
services receive selected public targets only.

## Intent Checks

- Use source intake for questions that provide or require a genome source file.
- Resolve intent as the host agent using this skill pack and tool metadata.
- Treat session-selected source Active Genome Index records or Active Genome Index records as the Active Genome Index.
- Keep answers from public sources clear without adding a routine "no Active
  Genome Index" disclaimer.
- Use narrow variant/source tools for small factual lookups.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### phenotype.retrieve_trait_gene_records

Retrieve native trait-to-gene records from integrated public sources, optionally filtered to gene symbols.

**Use when**: Retrieves trait-to-gene records from Open Targets target-disease associations and disease clinical drug candidate records. The genes array is an optional filter, not the scope of the capability.

**Why necessary**: Trait-to-gene retrieval supplies native public records for complex traits without pretending to rank final causal genes.

**Result semantics**: Returns native retrieved source records grouped by gene and evidence regime; it does not return a recommended answer. Association-only records are labelled as association_only_not_causal. A clean empty result means the declared sources had no matching trait-to-gene records for the input trait and optional gene filter.
