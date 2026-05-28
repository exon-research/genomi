---
name: prs
description: >
  Apply published polygenic scores from PGS Catalog to approved local personal
  DNA and return raw weighted score plus overlap QC.
tools:
  - prs.search_scores
  - prs.fetch_score_metadata
  - prs.list_imported_scores
  - prs.check_score_overlap
  - prs.calculate_score
  - prs.build_source_context
---

# Polygenic Scores

Use this skill when the user asks about polygenic risk scores, PRS, PGS
Catalog scores, common disease or trait risk from many variants, or applying a
published scoring file to their genome.

## Boundaries

- PRS/PGS here means applying published variant weights from a scoring file.
  Genomi does not train new PRS models from GWAS summary statistics.
- Default genome build is `GRCh38` when omitted; use `GRCh37` only when the
  Active Genome Index is GRCh37/hg19.
- Active Genome Index artifacts stay local. Public score metadata may use PGS
  Catalog, but private genotypes are not uploaded to external services.
- A raw PRS is common-risk or trait context, not a diagnosis, absolute disease
  risk, treatment recommendation, or clinical category.
- Only state standardized score context when valid `score_mean` and `score_sd`
  are supplied for the same score, build, cohort/reference distribution, and
  scoring convention.
- Do not use PRS output for ethnicity, identity, monogenic diagnosis,
  medication response, or rare-disease causality.

## Workflow

1. Use `prs.search_scores` for public trait or score discovery. If the user
   already supplies a PGS ID, use that ID directly.
2. Use `prs.fetch_score_metadata` when the source publication, build, variant
   count, scoring-file URLs, licensing, or cohort/evaluation context matters.
3. Use `prs.calculate_score` with the chosen `pgs_id` and the user's genome
   source to get the raw weighted score plus overlap QC.
4. Use `prs.check_score_overlap` when you only need readiness and QC without a
   calculated score.
5. Use `prs.list_imported_scores` when the user asks what scores are already
   available locally.
6. Use `prs.build_source_context` when the user asks what PRS can or cannot
   tell them.

## When published calibration is missing

PGS Catalog rarely publishes a reference cohort mean/SD, so a raw weighted
score has units on an arbitrary scale. Deliver a defensible directional or
quantitative answer for this specific question by combining capabilities
that contribute orthogonal evidence — population allele frequencies feeding
a closed-form z, direct effect-allele dosages at well-replicated lead loci,
additional published scores derived by different methods, treatment-response
context when the outcome is treatable, mechanism context from functional or
pathway evidence, or whatever else Genomi currently exposes that fits.
Disclose the assumptions of any closed-form estimate (HWE, variant
independence, ancestry of the allele-frequency source).

## Answering

When an Active Genome Index is scored or its overlap changes the result, report
the score ID/source, genome build, overlap status, matched/missing/excluded
variant counts, and whether the result is raw or calibrated. Do not add a
routine Active Genome Index status line for public score metadata lookups.

Use careful language:

- "The raw weighted score was calculated from N matched score variants."
- "This is source-bound PRS context, not an absolute risk estimate."
- "Performance may not transfer across ancestry/evaluation cohorts."
- When grounded in an analytic z from gnomAD or a multi-score consensus:
  "Your analytic z relative to <population> under HWE is +X.X, ~Yth
  percentile. This is a closed-form estimate, not an empirical
  reference-cohort percentile."

Directional language ("leans above population average", "in the upper
tertile of the analytic z distribution") is appropriate when grounded in
the orthogonal evidence the synthesis combined.

Avoid:

- Clinical-risk category labels (high/elevated/low risk) unless a
  validated calibration and category threshold from the same source
  context is explicitly supplied.
- Absolute outcome probabilities ("X% chance of disease by age N") —
  these require an empirical risk-calibration model.
- "This diagnoses", "rules out", "predicts disease", or "determines origin".

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### prs.build_source_context

Explain PGS Catalog provenance, local scoring workflow, genome-build defaults, calibration limits, and PRS risk boundaries.

**Use when**: The user asks what PRS can and cannot tell them, whether PRS means common risk analysis, or how Genomi applies published scores.

**Why necessary**: PRS answers require explicit boundaries around calibration, cohort portability, missing variants, and clinical non-diagnosis.

**Not for**: Calculating a personal score; use prs.calculate_score after Active Genome Index access approval.

**Example prompts**: Explain how Genomi implements PRS. Does PRS give common disease risk?

**Result semantics**: Returns public method context only; it does not read Active Genome Index.

### prs.calculate_score

Apply a published polygenic score to an approved Active Genome Index and return raw weighted score plus QC.

**Use when**: The user asks to calculate or apply a published PRS/PGS score to their genome.

**Why necessary**: This keeps Active Genome Index local, applies only selected published weights, reports overlap and build defaults, and avoids unsupported risk-category claims.

**Not for**: Training a new PRS model. Diagnosis, monogenic disease interpretation, medication response, or absolute-risk prediction without a validated calibration model. Ancestry or identity inference.

**Example prompts**: Calculate PGS000001 for my Active Genome Index. Apply this local scoring file to my GRCh38 genome.

**Result semantics**: Uses schema genomi-prs-score-v1. Output is a raw weighted score and QC unless explicit calibration parameters are supplied. Do not phrase it as diagnosis, absolute disease risk, ethnicity, or clinical actionability.

### prs.check_score_overlap

Check how many variants from a polygenic score are usable in an approved Active Genome Index.

**Use when**: The agent needs PRS overlap/readiness before calculating or interpreting a published polygenic score.

**Why necessary**: A PRS score can be misleading with low variant overlap, build mismatch, unharmonized palindromic alleles, or missing genotype records.

**Not for**: Public score search; use prs.search_scores. Diagnosis or absolute risk classification.

**Example prompts**: Does my genome have enough overlap with PGS000001?

**Result semantics**: Reports overlap and calculation readiness only; missing score variants are not negative evidence for disease risk.

### prs.fetch_score_metadata

Fetch detailed public PGS Catalog metadata for one score ID, including scoring-file URLs and source publication context.

**Use when**: The agent needs the exact PGS Catalog record context — trait, build, variant count, source publication, cohort, ancestry/evaluation, licensing — before explaining or applying a score.

**Why necessary**: The score metadata carries build, trait, source publication, cohort, ancestry/evaluation, and licensing context that determines whether applying a score is appropriate.

**Not for**: Calculating a personal score; use prs.calculate_score with the chosen pgs_id.

**Example prompts**: Fetch metadata for PGS000001.

**Result semantics**: Returns public PGS Catalog metadata only and may report source_unavailable if the external source cannot be reached.

### prs.import_scoring_file

Import a PGS Catalog or local scoring file into Genomi's local PRS score cache for a declared genome build.

**Use when**: A score has been selected and needs to be materialized locally before overlap checking or scoring.

**Why necessary**: Private genotype scoring must run against local score artifacts rather than uploading genotypes to external services.

**Not for**: Reading Active Genome Index; import is public/local score materialization only. Interpreting the score as risk; use prs.calculate_score and preserve its limitations.

**Example prompts**: Import PGS000001 for GRCh38. Import this local scoring file for GRCh37.

**Result semantics**: Creates a local cache of variant weights and manifest metadata. The default genome_build is GRCh38 when omitted and is disclosed in defaults_applied.

### prs.list_imported_scores

List polygenic scores available locally for use without reading Active Genome Index.

**Use when**: The user asks which polygenic scores are available locally.

**Why necessary**: Knowing which scores are already available locally helps the agent pick a matching genome build and avoid re-fetching.

**Not for**: Calculating personal PRS values; use prs.calculate_score after approval.

**Example prompts**: Which PRS scores are imported locally?

**Result semantics**: Lists local score-cache metadata only; it does not read Active Genome Index.

### prs.search_scores

Search public PGS Catalog score metadata by trait, score ID, EFO term, or free-text query without reading Active Genome Index.

**Use when**: The user asks which published PGS/PRS scores exist for a trait or provides a PGS Catalog score ID.

**Why necessary**: Score selection is source-specific and must expose trait, build, variant count, publication, evaluation, and licensing context before using a score on Active Genome Index.

**Not for**: Reading or scoring a user's genome; pass the chosen pgs_id to prs.calculate_score after Active Genome Index access approval. Training a new PRS from GWAS summary statistics.

**Example prompts**: Find PGS Catalog scores for coronary artery disease. What is PGS000001?

**Result semantics**: Returns public score candidates and source metadata only; it does not read Active Genome Index.
