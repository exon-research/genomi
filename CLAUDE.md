# Claude Code Protocol For Genomi

Use `INSTALL_FOR_AGENTS.md` only for setup. For operation, start with
`AGENTS.md` and `SKILL.md`. Capability tools are reached at runtime via the
`genomi.invoke` MCP dispatcher after the matching
`skills/<capability>/SKILL.md` has been read.

## Connect

Prefer MCP:

```json
{
  "mcpServers": {
    "genomi": {
      "command": "genomi",
      "args": ["serve"]
    }
  }
}
```

From a source checkout:

```json
{
  "mcpServers": {
    "genomi": {
      "command": "bash",
      "args": ["-lc", "cd /path/to/genomi && PYTHONPATH=src python3 -m genomi serve"]
    }
  }
}
```

## Context Rule

Only the current chat determines Active Genome Index context.

- Public genetics questions can use public Genomi tools immediately.
- Active Genome Index evidence can be used only when the chat mentions a
  genome source, a previous run, or asks about active Active Genome Index
  context.
- If the user provides a genome source path in this chat, that is approval to
  read that source for this session.
- A request about the user's genome is enough to check for an already imported
  Active Genome Index.
- Reading imported/parsed Active Genome Index artifacts, resuming a previous run
  for evidence, or searching for an existing user genome context requires
  explicit user approval for this session. Record approval with
  `active_genome_index.approve_access`.
- Do not use unrelated genome sources from other chats or prior tasks.

## Tool Selection

MCP `tools/list` returns only the base set (`genomi.*`, `journal.*`, plus the
`genomi.invoke` dispatcher). To use any other capability tool:

1. Read `skills/<capability>/SKILL.md` (Anthropic Claude Code Skills
   auto-loads each as `~/.claude/skills/genomi-<capability>/` based on
   frontmatter `description`).
2. Call `genomi.invoke` with the registered operation name, for example
   `genomi.invoke({tool: "variant.resolve", params: {"rsid": "rs429358"}})`.
   Do not use the capability ID as the tool name.

Use the smallest operation that can answer the question:

- `variant.resolve` for variants, rsIDs, genes, alleles, coordinates, or regions.
- `phenotype.plan_risk_investigation` for rare disease, hereditary disease, hereditary cancer,
  cancer risk, GeneCards, or disease-gene source review.
- `phenotype.compare_disease_evidence` for HPO or phenotype-to-disease
  ranking from reviewed records.
- `phenotype.retrieve_gene_disease_associations` for GenCC primary gene-disease
  associations from supplied genes.
- `phenotype.compare_gene_hpo_evidence` for HPO, patient phenotype,
  rare-disease, OMIM, Orphanet, ClinGen, or GenCC candidate-gene evidence.
- `pathway.retrieve_members`, `cell_type.retrieve_markers`, and
  `region.retrieve_features` for analytical grounding records.
- `gwas.compare_gene_associations`,
  `phenotype.compare_drug_target_evidence` when the question explicitly
  asks for one source prior.
- `phenotype.retrieve_disease_drug_targets` for disease-scoped clinical
  drug-target records from Open Targets.
- `sequence.*` for supplied-sequence ORF, translation, restriction, Kozak,
  primer, or local FASTA record-match questions.
- `gwas.compare_variant_associations` for phenotype plus candidate rsIDs.
- `functional_genomics.retrieve_perturbation_records` for native BioGRID ORCS and configured
  DepMap records; `functional_genomics.import_perturbation_table` for local CSV/TSV
  perturbation result tables; `functional_genomics.compare_gene_perturbation` for
  perturbation experiment context plus candidate genes.
- `pharmacogenomics.review_medication` for medication-response questions.
- `ancestry.list_reference_panels` for public ancestry panel metadata and
  `ancestry.estimate_population_context` for approved GRCh38 sample
  reference-panel similarity. Ancestry output is PCA/reference-neighbor context,
  not ethnicity, race, or origin prediction.
- `prs.search_scores` for public PGS Catalog score discovery and
  `prs.calculate_score` for approved local raw polygenic-score calculation.
  PRS output is common-risk/trait context only unless a validated calibration is
  supplied; it is not diagnosis or absolute risk by default.
- `genomi.describe_context` only after the chat mentions or asks about Active
  Genome Index context.
- `active_genome_index.approve_access` after explicit user approval, before reading
  existing imported/parsed Active Genome Index artifacts.

Answer from the returned evidence. Mention Active Genome Index use only when it
materially changes the result.
