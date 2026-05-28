---
name: drug-targets
version: 1.0.0
description: |
  Causal drug-target and mechanism gene prioritization from public source
  records, drugs, drug classes, mechanisms, and candidate gene lists.
tools:
  - phenotype.retrieve_disease_drug_targets
  - phenotype.compare_drug_target_evidence
  - research.list_sources
  - research.record
  - research.query
  - research.search
mutating: false
---

# Drug Targets

Use this skill for disease-scoped clinical drug-target retrieval, direct
drug-target records, PharmaProjects-style target context, ChEMBL mechanism
genes, DrugBank target context, or candidate-gene review for a drug, drug
class, or mechanism.

## Contract

- Direct drug-target or mechanism evidence outranks target-disease association
  scores and GWAS-style association.
- ChEMBL, DrugBank, and PharmaProjects-style records can support direct target
  claims when the source supports both the gene and the drug, class, mechanism,
  or indication context.
- Open Targets association context is useful for review, but do not treat a high
  association score as direct drug-target evidence.
- Open Targets disease drug and clinical candidate records can retrieve
  disease-scoped clinical drug-target genes when the drug target comes from a
  mechanism-of-action row.
- Treat returned rankings as source evidence. The agent decides whether the
  drug-target prior matches the question. When using cross-source comparison,
  use `prior_fit` before reading a panel as task-relevant and audit
  `decision_evidence` before answering.

## Tool Flow

1. `phenotype.retrieve_disease_drug_targets` retrieves Open Targets clinical
   drug candidate target genes for a supplied disease anchor.
2. `phenotype.compare_drug_target_evidence` compares candidate genes against direct
   drug-side context: drug, drug class, or mechanism.
3. If source support is missing, use `research.list_sources` to choose direct target
   sources, review them, and store narrow findings with `research.record`.
4. Re-run the same selected tool after recording reviewed findings.

Example:

- `phenotype.retrieve_disease_drug_targets` with `{"disease":"asthma","genes":["ADRB2","IL13"]}`
- `phenotype.compare_drug_target_evidence` with `{"drug_class":"beta agonist","phenotype":"asthma","genes":["ADRB2","IL13"],"source_records":[...]}`

## Source Records

Prefer source records with:

- `genes`: candidate target genes named by the source.
- `drug`, `drug_class`, `indication`, or `mechanism`.
- `source_title`, `source_url`, and `source_type`.
- `finding` or `text`: short source-backed finding.
- `verified_fields` and `support_spans` showing where the source supports the
  gene and drug-target or mechanism context.

## Answering

Use a direct gene-symbol answer only when reviewed evidence supports the
drug-target or mechanism relationship requested by the question. Otherwise state
the source gap and summarize the strongest reviewed evidence without presenting
it as the final target.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### phenotype.compare_drug_target_evidence

Compare candidate genes using direct drug-target or mechanism evidence only.

**Use when**: Returns direct drug-target, target-mechanism, ChEMBL, DrugBank, or PharmaProjects evidence for candidate genes.

**Why necessary**: Drug-target questions require direct target/mechanism evidence, which is distinct from disease association evidence.

**Result semantics**: Returns source-local drug-target evidence only; association-only evidence cannot create direct target support.

### phenotype.retrieve_disease_drug_targets

Retrieve disease-scoped clinical drug-target genes from Open Targets drug candidate records.

**Use when**: Returns Open Targets clinical drug candidate target genes for a supplied disease anchor, with optional gene_membership projection for supplied candidate genes.

**Why necessary**: Clinical drug-target records answer therapeutic-target membership without implying causal genetics or treatment efficacy.

**Result semantics**: Returns disease-scoped clinical drug-target records and source-local ordering; the host agent decides how they apply. mode='gene_membership' projects the same source records into per-gene membership booleans and highest observed phase for supplied genes. Does not ingest agent-supplied evidence and does not infer treatment efficacy or final causal-gene answers.
