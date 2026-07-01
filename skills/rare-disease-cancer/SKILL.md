---
name: rare-disease-cancer
description: |
  Plan rare disease, hereditary disease, cancer risk, carrier-relevance, and
  observed-condition source investigation from public targets or selected
  active genome evidence.
tools:
  - phenotype.plan_risk_investigation
  - phenotype.normalize_terms
  - phenotype.retrieve_gene_disease_associations
  - phenotype.compare_disease_evidence
  - phenotype.compare_gene_hpo_evidence
  - research.list_sources
  - variant.gather_gene_context
  - variant.gather_allele_context
  - gnomad.fetch_population_frequency
  - research.record
  - research.query
  - active_genome_index.classify_genotype_support
  - active_genome_index.classify_region_callability
mutating: true
---

# Condition Review

Use this skill when the user asks about rare disease, hereditary disease,
cancer risk genes, hereditary cancer, GeneCards-style gene context, MalaCards
disease context, HPO/phenotype-to-disease review, HPO-style
phenotype-to-gene review, carrier-relevance evidence, observed-condition
review, or disease-gene source review.

**Not for common-trait phenotypes.** Common, complex-disease, GWAS-style, or
drug-target candidate-gene questions use the matching source-specific tool.
Use this skill when the phenotype is explicitly rare/Mendelian, HPO-style, or
hereditary cancer.

## Contract

Support both public-only questions and selected active genome evidence.

- Public-only questions stay public-only.
- Active genome evidence is used only when the current chat has selected or
  approved active genome access.
- GeneCards and MalaCards are context sources, not clinical-validity sources by
  themselves.
- Cancer-gene role, somatic cancer evidence, and inherited germline risk remain
  separate unless a reviewed source links them.
- Carrier-review output consumes ClinVar `carrier_relevance` groups and ranks
  review targets by evidence strength plus missing interpretation gates.
- Observed-condition review consumes observed-condition, uncertainty/conflict,
  risk-association, benign/counterevidence, and population-context groups.
- Reviewed source findings are stored before final interpretation or reporting.
- HPO and symptom overlap can prioritize review targets, but it is not a
  diagnosis.

## First Tool

Call `phenotype.plan_risk_investigation` first. Provide any public targets the user gave:

- `phenotype.plan_risk_investigation` with `{"question":"BRCA1 hereditary breast cancer risk","gene":"BRCA1","investigation_type":"cancer_risk"}`
- `phenotype.plan_risk_investigation` with `{"question":"carrier relevance review","investigation_type":"carrier_review"}`
- `phenotype.plan_risk_investigation` with `{"question":"observed ClinVar condition review","investigation_type":"observed_condition_review"}`

For a selected Active Genome Index, add:

- `phenotype.plan_risk_investigation` with `{"question":"rare disease review for GENE2","gene":"GENE2","include_active_genome_index":true}`

If the user did not select active genome evidence, do not add active genome
parameters.

For phenotype-first questions, normalize and rank the public targets:

- `phenotype.normalize_terms` with `{"text":"ataxia; microcephaly; seizures; HP:0001250"}`
- `phenotype.retrieve_gene_disease_associations` with `{"genes":["PIEZO2"]}`
- `phenotype.compare_disease_evidence` with `{"phenotypes":["ataxia","microcephaly","seizures"],"candidate_diseases":["condition A","condition B"],"source_records":[{"diseases":["condition A"],"verified_fields":{"diseases":["condition A"],"phenotypes":["ataxia"]},"support_spans":[{"field":"phenotypes","text":"source-backed ataxia text"}]}]}`
- `phenotype.compare_disease_evidence` with `{"hpo_ids":["HP:0000822","HP:0001965"],"genes":["PIEZO2"]}`
- `phenotype.compare_gene_hpo_evidence` with `{"phenotypes":["ataxia","microcephaly"],"genes":["PNKP","SPG7"],"source_records":[{"genes":["PNKP"],"verified_fields":{"genes":["PNKP"],"phenotypes":["ataxia","microcephaly"]},"support_spans":[{"field":"genes","text":"source-backed PNKP text"}]}]}`

Use `phenotype.compare_disease_evidence` when the answer choices are diseases or syndromes.
Also use it when the input is HPO terms plus known or candidate genes but the
requested output is a disease name, syndrome name, or OMIM-style diagnosis. In
that shape, gene resolution is not the answer; the load-bearing step is
within-gene disease-family discrimination by the patient's specific HPO pattern.
`phenotype.retrieve_gene_disease_associations` returns the GenCC primary
gene-disease association set for supplied genes. `phenotype.compare_disease_evidence`
uses that association set as the gene-derived candidate universe and uses HPO
disease annotations only for phenotype terms.
Use `phenotype.compare_gene_hpo_evidence` for HPO IDs, patient-specific
phenotypes, rare-disease phenotype matching, or single-subject causal-gene
questions. Keep this phenotype/HPO evidence separate from population-trait,
drug-target, and perturbation evidence.
When HPO IDs are available, pass them so public phenotype-to-gene annotation can
be checked across the full candidate set. Do not pick a gene from partially
reviewed evidence; gather better source support or state that the source
evidence is incomplete.

## Source Review

Use the investigation guidance to decide which source to review next:

- ClinVar for exact variant assertions and review status.
- gnomAD for public population frequency when an exact allele matters.
- ClinGen and GenCC for gene-disease validity.
- GeneReviews for inheritance, mechanism, penetrance, and disease context.
- GeneCards for gene aliases, function, pathways, and disease-association
  triage.
- MalaCards for disease aliases, phenotype context, and associated genes.
- NCI cancer genetics for hereditary cancer background and counseling
  boundaries.
- COSMIC Cancer Gene Census for cancer-gene role context, not standalone
  germline-risk evidence.
- HPO for phenotype identifiers and synonyms.
- MONDO for disease identifiers, aliases, and ontology context.
- Orphanet and OMIM for rare disease phenotype and gene relationship context.

## Evidence Checks

For active genome evidence:

- Use `variant.gather_gene_context` for selected genes.
- Use `variant.gather_allele_context` for selected exact alleles.
- Use `active_genome_index.classify_genotype_support` before personal wording about an observed allele.
- Use `active_genome_index.classify_region_callability` before negative or absence wording.
- Use `gnomad.fetch_population_frequency` when public frequency is missing and would change
  interpretation.

For phenotype-first ranking, use reviewed records with source-backed fields or
support spans. Direct answers require a source to support both the candidate and
the relevant phenotype, disease, or HPO context.

## Answering

Mention Active Genome Index use only when it changes the result, limitation, or
next action. Keep risk language qualitative unless a cited source gives a
quantitative estimate. Recommend clinical genetics confirmation for medical
decisions.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### phenotype.compare_disease_evidence

Compare supplied or primary gene-derived diseases against phenotype/HPO evidence without selecting the diagnosis.

**Use when**: Compares phenotype/HPO terms against supplied diseases, disease source records, or primary gene-disease associations. Uses GenCC primary gene-disease associations as the gene-derived disease candidate universe when gene symbols are supplied.

**Why necessary**: Candidate diseases must be compared against phenotype/HPO evidence without letting the tool choose a diagnosis.

**Result semantics**: Returns phenotype/disease evidence rows, disease identifiers, HPO overlap counts, and source coverage; the host agent chooses the answer. The tool uses primary gene-disease retrieval for enumeration and HPO disease annotations for phenotype terms.

### phenotype.compare_gene_hpo_evidence

Compare candidate genes using phenotype, HPO, and curated rare-disease annotation evidence only.

**Use when**: Returns phenotype, HPO, OMIM, Orphanet, and rare-disease annotation evidence for candidate genes.

**Why necessary**: Rare-disease candidate genes need HPO/phenotype evidence, not GWAS, drug-target, or pathway priors.

**Not for**: common-trait GWAS ranking, drug-target evidence, or medication response.

**Example prompts**: Which of these genes best matches ataxia and microcephaly?

**Result semantics**: Returns source-local phenotype/HPO evidence only; the host agent decides whether this prior matches the question.

### phenotype.normalize_terms

Normalize phenotype text and HPO IDs into public evidence-review targets.

**Use when**: Normalizes supplied HPO IDs or free-text phenotypes into public evidence-review targets.

**Why necessary**: Free-text symptoms need normalization before HPO and rare-disease tools can compare them reliably.

**Result semantics**: Returns lexical phenotype normalization and safe public targets; it does not diagnose or call external ontology APIs.

### phenotype.plan_risk_investigation

Plan rare disease, cancer risk, carrier-relevance, or observed-condition investigation from public targets and optionally selected Active Genome Index evidence.

**Use when**: Returns rare disease, hereditary disease, hereditary cancer, cancer-risk-gene, carrier-relevance, observed-condition, and disease-gene source-review plans. Can include selected active-genome-index review targets when explicitly supplied or approved.

**Why necessary**: Broad disease and cancer-risk questions need declared source-review boundaries before any personal-risk wording.

**Example prompts**: Any inherited disease or cancer-risk findings worth following up?

**Result semantics**: Returns structured investigation guidance, relevant public source classes, reviewed-research gaps, and optional selected active-genome-index `candidate_review_groups`. Without include_active_genome_index or explicit matches, the operation stays public-only. GeneCards and MalaCards are treated as context sources that require cross-checking before clinical, carrier, or personal-risk wording.

### phenotype.retrieve_gene_disease_associations

Retrieve primary gene-disease associations from GenCC for supplied gene symbols.

**Use when**: Returns GenCC primary gene-disease associations for supplied genes, filtered to declared validity classifications.

**Why necessary**: Gene-disease validity should come from primary association sources before phenotype matching or diagnosis-like wording.

**Result semantics**: Returns a primary gene-disease candidate universe for downstream phenotype/HPO comparison. Does not ingest agent-supplied source records and does not diagnose.
