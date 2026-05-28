# Evidence Quality Convention

Claim rules for all Genomi skills.

## Source precedence

Use the highest available evidence class and say which class was used:

1. Current session sample evidence: genotype, zygosity, callability, QC.
2. Static curated/public rows: ClinVar, population frequency, panels, source versions.
3. Reviewed source findings stored in the evidence DB.
4. Current external research on selected public targets.
5. General model knowledge for background; personal claims require evidence
   from the listed classes.

When sources conflict, name the conflict and keep both sources visible.

## Evidence-Status Checks

- Positive personal allele claim: sample observation plus genotype support when
  interpretation depends on zygosity, read depth, genotype quality, or call support.
- Negative/reference claim: region callability.
- ClinVar medical meaning: classification, review status, condition, inheritance,
  population frequency, and reviewed source context when relevant.
- GWAS meaning: phenotype match, ancestry/source limitations, effect direction
  when available, and clear association-only language.
- Final interpretation: the host agent selects claims, citations, and
  limitations from Genomi evidence output.

## Citation discipline

Every user-facing claim should trace to a Genomi tool output or reviewed source.
Prefer stable evidence references:

- Operation name and target: `variant.resolve rs429358`.
- Local artifact class: Active Genome Index, evidence DB, candidate inventory.
- Source title/URL/access date when external research was used.

Use target-specific evidence packets or reviewed findings for final
interpretation citations.

## Dynamic Confidence

When a Genomi-guided answer needs a confidence judgment, derive it from the
actual evidence returned in that turn. Use `high` only for direct support from
Genomi tool output or a trusted source, with relevant quality checks satisfied
and no material unresolved conflict. For less certain answers, choose the
lowest honest label from the observed limitations: partial coverage, indirect
association, population/source mismatch, marker subset support, low review
status, source conflict, missing evidence, unavailable evidence, or evidence
outside declared tool/source coverage.

Do not promote a tool's evidence-support, overlap-quality, marker-support, or
other internal quality field directly into a final confidence statement. Do not
use a static default confidence or a user-selected confidence profile.

## Medical boundary

Use informational wording. Clinical decisions need clinician confirmation.
Personal risk percentages need cited source support. Explain uncertainty
directly.
