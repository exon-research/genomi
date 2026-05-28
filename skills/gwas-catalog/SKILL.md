---
name: gwas-catalog
version: 1.0.0
description: |
  Compare candidate rsIDs against GWAS Catalog phenotype associations.
  Use association evidence with source and ancestry limitations.
tools:
  - gwas.compare_variant_associations
  - gwas.compare_gene_associations
  - phenotype.retrieve_trait_gene_records
  - variant.resolve
  - active_genome_index.classify_genotype_support
  - research.record
mutating: true
---

# GWAS Catalog Association Evidence

Use GWAS Catalog association records for supplied phenotypes plus candidate
variants or genes.

For phenotype plus candidate **genes**, `gwas.compare_gene_associations`
returns GWAS Catalog reported_gene, mapped_gene, or source gene-field
association evidence. `phenotype.retrieve_trait_gene_records` retrieves native
trait-to-gene records from integrated public sources, optionally filtered by
gene. If another source prior is relevant, call that source-specific tool
separately and keep the evidence regimes separate.
HPO or single-subject phenotype matching belongs outside this skill.

## Goal

Retrieve and compare GWAS Catalog association evidence with explicit
source-field and phenotype-match limitations. Personal interpretation requires
separate sample support and careful wording.

> **Convention:** See `skills/conventions/evidence-quality.md`.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### gwas.compare_gene_associations

Compare candidate genes using GWAS Catalog reported_gene and mapped_gene trait-association evidence.

**Use when**: The user gives a phenotype or trait plus candidate genes and asks for GWAS Catalog gene-field association support.

**Why necessary**: GWAS Catalog gene fields are source annotations for population-trait associations; they should stay separate from causal-gene, HPO, or drug-target evidence.

**Not for**: causal-gene claims unless separate causal evidence is supplied.

**Result semantics**: Returns source-local GWAS Catalog gene-field association evidence only. reported_gene and mapped_gene are source annotations and are not causal-gene evidence. Causal-gene or effector-gene wording returns wrong_evidence_regime with a routing hint.

### gwas.compare_variant_associations

Compare candidate rsIDs by population-trait GWAS Catalog association evidence.

**Use when**: Returns GWAS Catalog population-trait association records for candidate rsIDs, ranked by trait match and p-value.

**Why necessary**: Population-trait rsID ranking needs GWAS Catalog evidence, not ClinVar or personal genotype evidence.

**Not for**: clinical disease diagnosis or personal genotype support.

**Example prompts**: Compare these rsIDs for LDL cholesterol GWAS evidence.

**Result semantics**: Returns public GWAS association evidence rows ranked by source trait match and p-value. ClinVar, Mendelian, sample genotype, pathway, and same-gene context cannot override this ranking for population-trait lead-variant tasks. Personal interpretation uses separate sample genotype evidence tools only after the source-ranked rsID decision.

## Boundary

GWAS prioritization answers “which candidate has public association support for
this phenotype?” Personal risk interpretation requires sample support, phenotype
context, ancestry/source limitations, and careful claim wording.

For phenotype-plus-rsID questions, call `gwas.compare_variant_associations`
directly. If personal context exists, choose follow-up rsIDs from the returned
association evidence before checking sample support. ClinVar, Mendelian,
sample genotype, same-gene, or pathway context from follow-up lookups cannot
override the GWAS Catalog ranking for population-trait lead-variant tasks.

For phenotype-plus-gene-list questions, call
`gwas.compare_gene_associations` only when GWAS Catalog
reported_gene/mapped_gene/source gene-field association is the intended prior.
If a trait-to-gene source record is needed, retrieve native trait-to-gene
records with `phenotype.retrieve_trait_gene_records`. If it returns only
`association_only_not_causal` records, do not answer from those records alone.
Call separate source-specific tools when drug-target, curated association, or
locus-to-gene evidence also matters; do not collapse those priors into the GWAS
Catalog association result.
HPO or single-subject phenotype matching belongs to
`phenotype.compare_gene_hpo_evidence`.

For GWAS variant prioritization, exact GWAS Catalog trait matches outrank nearby
trait matches. P-value breaks ties inside the same evidence level; ClinVar,
Mendelian disease, same-gene, pathway, or sample context does not rerank the
population-trait lead-variant result.

## Routing Checks

- Present GWAS associations as association evidence.
- Preserve ancestry/source limitations.
- Check whether the selected rsID is present in the Active Genome Index before personal
  interpretation.
- Preserve which phenotype/query produced the ranking.
- Prefer direct GWAS Catalog records over inferring a winner from prose.
- Treat `variant.resolve` as context-only follow-up after the GWAS
  source ranking is chosen.
- Do not treat GWAS Catalog `mapped_genes` as causal-gene evidence.
- If the selected candidate is not direct-source supported, say the result is
  lower-support adjacent GWAS evidence.
