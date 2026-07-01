---
name: pharmacogenomics
description: |
  Answer drug-response, medication, PharmGKB-style, PGxDB, ATC, DrugBank,
  gene-drug, and variant-drug questions using public PGx evidence plus local
  sample genotype support when an Active Genome Index is selected.
tools:
  - genomi.describe_context
  - pharmacogenomics.review_medication
  - pharmacogenomics.describe_gene_requirements
  - pharmacogenomics.preflight_pharmcat
  - pharmacogenomics.prepare_outside_call_tsv
  - pharmacogenomics.validate_outside_call_tsv
  - pharmacogenomics.import_pharmcat_artifacts
  - pharmacogenomics.check_pharmcat
  - pharmacogenomics.run_pharmcat
  - pharmacogenomics.fetch_clinpgx
  - pharmacogenomics.fetch_fda_labels
  - pharmacogenomics.fetch_pgxdb
  - variant.resolve
  - active_genome_index.classify_genotype_support
  - research.list_sources
  - research.record
  - research.query
mutating: true
---

# Pharmacogenomics

Use this skill when the user asks about medication response, PGx guidelines,
drug-gene or variant-drug evidence, PGxDB, ATC codes, DrugBank IDs, PharmCAT,
or pharmacogene sample evidence.

## Contract

- Drug-response claims use public PGx source evidence.
- Personal drug-response statements cite separate local genotype or PGx caller
  support.
- External PGx lookups receive selected public targets only.
- Source-backed PGx findings can be stored as shared reviewed research.
- User-specific sample interpretations can be stored as private reviewed
  research.

> **Convention:** See `skills/conventions/evidence-quality.md`.
> **Convention:** See `skills/_output-rules.md`.

## Primary Flow

1. Use `pharmacogenomics.review_medication` for ordinary medication questions.
   It combines ClinPGx, FDA PGx tables, PGxDB, stored reviewed research, and
   optional selected sample evidence in one bounded review.
2. Inspect `evidence_envelope`, `medication_review_matrix`,
   `evidence_matrix`, `target_inventory`, `answer_support`, and
   `unanswered_answer_components` before answering. Treat each
   `medication_review_matrix.rows[]` entry as the review unit.
3. If the answer needs source review beyond returned public records, use
   `research.list_sources`, review the selected public target, then store the
   finding with `research.record`.
4. If the answer needs personal sample evidence, use the Active Genome Index
   only when selected or supplied in this chat. Confirm relevant alleles with
   `variant.resolve` or `active_genome_index.classify_genotype_support`.

## Tool Choices

- `pharmacogenomics.review_medication`: bounded medication evidence review;
  public-only by default, with Active Genome Index evidence when selected.
- `pharmacogenomics.fetch_clinpgx`, `pharmacogenomics.fetch_fda_labels`, and
  `pharmacogenomics.fetch_pgxdb`: focused public PGx source retrieval when the
  medication review needs a source-specific follow-up.
- `pharmacogenomics.describe_gene_requirements`: gene-specific sample evidence
  requirements for named allele matching, outside calls, HLA, MT-RNR1, G6PD,
  and SV/CNV-sensitive genes.
- `pharmacogenomics.check_pharmcat`: check local PharmCAT availability.
- `pharmacogenomics.preflight_pharmcat`: inspect whether the selected Active
  Genome Index can provide a suitable PharmCAT input before running it.
- `pharmacogenomics.prepare_outside_call_tsv` and
  `pharmacogenomics.validate_outside_call_tsv`: prepare or validate specialized
  outside-call evidence for PharmCAT.
- `pharmacogenomics.run_pharmcat`: run broad PharmCAT calling from the selected
  Active Genome Index and return provenance plus `sample_pgx_matrix` rows
  projected from report, phenotype, calls-only, and matcher artifacts.
- `pharmacogenomics.import_pharmcat_artifacts`: import existing PharmCAT JSON,
  TSV, matcher, phenotype, missing-position, or output-directory artifacts and
  return `sample_pgx_matrix`.

PGx capability metadata is exposed through `genomi.list_resources`; there is
no separate PGx capability-listing tool.

## Answering

- Mention Active Genome Index evidence only when it changes the medication
  interpretation, limitation, blocker, or next action.
- Keep PGx language informational and recommend clinical confirmation for
  medication decisions.
- Do not infer medication actionability from a genotype alone; connect sample
  evidence to public drug-response evidence.
- Treat user-provided diplotypes, phenotypes, activity scores, and outside
  calls as supplied sample evidence that may need independent confirmation.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### pharmacogenomics.check_pharmcat

Check local PharmCAT availability and version provenance for broad PGx calling from an AGI-derived PharmCAT input.

**Use when**: The agent needs to know whether broad PharmCAT PGx calling is available before running pharmacogenomics.run_pharmcat.

**Why necessary**: External PGx calls need availability and version provenance before they are trusted.

**Result semantics**: Reports local PharmCAT executable/jar availability and version probe output for auditability before broad PGx calling.

### pharmacogenomics.describe_gene_requirements

Return pharmacogene-specific sample evidence requirements for PharmCAT named allele matching, outside calls, CYP2D6 SV/CNV handling, HLA typing, MT-RNR1, and G6PD chrX representation.

**Use when**: The selected medication or source evidence names a pharmacogene and the agent needs to choose sample evidence, PharmCAT, outside-call, or targeted lookup handling.

**Why necessary**: Complex pharmacogenes require special evidence handling that a simple rsID lookup cannot provide.

**Result semantics**: Returns packaged source-backed pharmacogene sample-evidence requirements, candidate tools, and source references for the selected gene.

### pharmacogenomics.fetch_clinpgx

Fetch traceable ClinPGx pharmacogenomic guideline, clinical annotation, and FDA label evidence for a selected drug, gene, or rsID; compact normalized records are returned by default.

**Use when**: The question involves medication response, adverse effects, CPIC/DPWG guidance, FDA drug-label PGx context, PharmGKB/ClinPGx annotations, or drug plus gene/rsID interpretation.

**Why necessary**: Guideline, clinical annotation, and label rows are separate public PGx evidence from sample genotype calls.

**Result semantics**: Fetches public guideline, annotation, and label rows; raw API records are opt-in with include_raw_records; personal interpretation requires separate local genotype or diplotype evidence.

### pharmacogenomics.fetch_fda_labels

Fetch targeted FDA pharmacogenomic biomarker-labeling and pharmacogenetic-association table rows from official FDA pages.

**Use when**: The question needs FDA biomarker-labeling table context or FDA pharmacogenetic association table context for a selected drug or gene.

**Why necessary**: FDA biomarker and pharmacogenetic-association tables are official label evidence with their own boundaries.

**Result semantics**: Fetches official FDA table rows; keep biomarker-labeling rows separate from pharmacogenetic-association rows and combine with separate sample evidence for personal interpretation.

### pharmacogenomics.fetch_pgxdb

Fetch targeted PGxDB pharmacogenomic evidence for a selected drug, ATC code, DrugBank ID, rsID, variant marker, or gene.

**Use when**: The question involves medication response, adverse effects, pharmacogenomics, PharmGKB-style evidence, a drug plus rsID, or a drug plus gene.

**Why necessary**: PGxDB association records provide targeted drug-variant evidence distinct from guideline recommendations.

**Result semantics**: Fetches public PGxDB rows; sample interpretation requires separate local genotype evidence.

### pharmacogenomics.import_pharmcat_artifacts

Import existing PharmCAT report JSON, calls-only TSV, matcher JSON, phenotype JSON, missing-position VCF, or output directory without executing PharmCAT.

**Use when**: The agent has existing PharmCAT artifacts and needs sample-side PGx evidence without running local PharmCAT.

**Why necessary**: Existing PharmCAT outputs should be reused rather than rerun when sample-side PGx evidence already exists.

**Result semantics**: Parses existing PharmCAT artifacts into `sample_pgx_matrix`, evidence summaries, and record_research_payloads used by pharmacogenomics.run_pharmcat, including interpretation readiness and missing-position review facts.

### pharmacogenomics.preflight_pharmcat

Inspect selected Active Genome Index structure for broad PharmCAT PGx calling without running PharmCAT or writing artifacts.

**Use when**: The agent needs read-only Active Genome Index structure, sample-column, genotype-field, or header evidence before broad PharmCAT PGx calling.

**Why necessary**: Broad PharmCAT runs need input suitability checks before execution or artifact interpretation.

**Result semantics**: Returns local AGI-derived preflight facts without exposing the raw AGI path; PharmCAT coverage sufficiency is judged from execution artifacts, especially missing PGx position review.

### pharmacogenomics.prepare_outside_call_tsv

Prepare a PharmCAT outside-call TSV from supported specialized caller output such as OptiType HLA calls, StellarPGx CYP2D6 summaries, or generic gene/diplotype tables.

**Use when**: The agent has specialized caller output for HLA-A, HLA-B, CYP2D6, MT-RNR1, or another pharmacogene and needs a PharmCAT outside-call TSV.

**Why necessary**: Specialized callers for HLA, CYP2D6, and related genes need conversion before PharmCAT can consume them.

**Result semantics**: Writes a canonical outside-call TSV under Genomi output storage or the requested output_file, validates it, and returns output.path for pharmacogenomics.run_pharmcat with parsed rows, invalid rows, warnings, caller format, and sample identity facts.

### pharmacogenomics.review_medication

Review medication pharmacogenomic evidence as medication-first rows combining ClinPGx guideline/label context, FDA PGx table rows, PGxDB association evidence, Active Genome Index rsID lookup when selected, implemented marker-definition evidence when selected, evidence components, and target inventory.

**Use when**: Combines public PGx evidence with selected active-genome-index or marker evidence for one medication.

**Why necessary**: Medication-response questions need drug-specific PGx sources plus optional personal genotype evidence in one bounded review.

**Not for**: diagnosing disease risk; it is medication-response evidence.

**Example prompts**: Does my DNA say anything about clopidogrel?

**Result semantics**: Returns `medication_review_matrix` where each row carries drug, gene, variant/diplotype/phenotype, recommendation/source text, evidence IDs, sample relevance, row readiness, and clinical boundary. Public-only by default unless active-genome-index context is selected.

### pharmacogenomics.run_pharmcat

Run a local PharmCAT installation from an approved Active Genome Index for broad PGx diplotype, phenotype, recommendation artifacts, and `sample_pgx_matrix` rows.

**Use when**: Runs local PharmCAT from the selected Active Genome Index to generate broad PGx diplotype, phenotype, and recommendation artifacts.

**Why necessary**: Broad PGx diplotype and recommendation artifacts require a specialized external caller.

**Result semantics**: Runs local PharmCAT as sample-side PGx evidence generation; returns input preflight, runtime provenance, outside-call validation, `sample_pgx_matrix`, artifacts, warnings, interpretation readiness, and record_research_payloads for synthesis.

### pharmacogenomics.validate_outside_call_tsv

Validate PharmCAT outside-call TSV structure and summarize selected diplotype, phenotype, or activity-score evidence.

**Use when**: The PGx sample evidence path already has a PharmCAT outside-call TSV for CYP2D6, HLA-A, HLA-B, MT-RNR1, or another specialized caller result before PharmCAT execution.

**Why necessary**: Outside calls can override complex gene evidence, so their structure must be validated before use.

**Result semantics**: Validates outside-call TSV shape, hides the local path, returns parsed rows, invalid rows, warnings, and explains that outside calls override PharmCAT VCF-derived calls for the same gene.
