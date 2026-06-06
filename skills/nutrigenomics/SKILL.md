---
name: nutrigenomics
description: |
  Curated single-marker evidence for declared nutrient-metabolism,
  food-tolerance, and taste-perception domains. Refuses diet prescriptions,
  supplement dosing, weight-loss prediction, methylation-cycle prescriptions,
  microbiome-mediated effects, and other out-of-scope nutrigenomic claims.
tools:
  - nutrigenomics.list_domains
  - nutrigenomics.build_source_context
  - nutrigenomics.retrieve_domain_markers
  - nutrigenomics.retrieve_variant_records
  - gnomad.fetch_population_frequency
  - gwas.compare_variant_associations
mutating: true
---

# Nutrigenomics

Use this skill when the user asks how a germline variant affects nutrient
metabolism, food tolerance, or taste perception within declared domains:

- folate metabolism
- vitamin D status
- iron storage
- lactose tolerance
- lipid diet response (APOE e2/e3/e4)
- obesity predisposition (single-marker context only)

## Out of scope — refuse, do not approximate

Do NOT use this skill for, and DO surface as refusals:

- Macronutrient ratio prescriptions ("eat X% fat because of your APOE")
- Specific supplement dosing recommendations
- Weight-loss outcome prediction from genotype
- Diet-matching to genotype for fitness goals
- Microbiome-mediated dietary effects
- "Methylation cycle" prescriptions beyond folate marker context
- General health-outcome prediction from a small marker set
- "Detox capacity" framings
- Food allergy risk prediction
- Vitamin megadose prescriptions

The capability returns `coverage_status: out_of_scope_for_input` for these
domain ids. Treat the refusal literally — do not reach for adjacent records
that look similar.

## Contract

- Reads public catalogue metadata only; does not read an Active Genome Index.
- For scanning an active genome, compose with
  `active_genome_index.classify_genotype_support` using the variant
  coordinates carried in each record.
- For stratified allele frequencies, call `gnomad.fetch_population_frequency`.
- For primary GWAS effect sizes, call `gwas.compare_variant_associations`
  using the `gwas_catalog_id` carried in each record's
  `downstream_traits_with_gwas`.

> **Convention:** See `skills/conventions/context-routing.md`.
> **Convention:** See `skills/conventions/evidence-quality.md`.
> **Convention:** See `skills/_output-rules.md`.

## First Actions

1. If the request is shaped like a diet prescription, supplement dosing,
   weight-loss prediction, or any item in the out-of-scope list, refuse
   first. Do not call retrieval tools.
2. Use `nutrigenomics.list_domains` to confirm the relevant domain is
   declared and to inspect evidence-tier counts before drilling in.
3. Use `nutrigenomics.build_source_context` when grounding a discussion in
   provenance is needed — e.g. when a user asks where the records come from
   or why diet prescriptions are out of scope.
4. Use `nutrigenomics.retrieve_domain_markers` with the validated
   `domain_id`. Default `min_evidence_tier="established"`. Loosen to
   `"probable"` only when the question explicitly invites less-replicated
   evidence.
5. Use `nutrigenomics.retrieve_variant_records` when the agent already has
   an rsID and wants to know which declared domains reference it.

## Interpretation Rules

- Each record carries `out_of_scope_claims`. Surface these as explicit
  disclaimers — do not paraphrase around them.
- `evidence_tier` is literal. An `emerging` record is not equivalent to an
  `established` one; hedge in any agent-generated text accordingly.
- Single-marker evidence does not substitute for measured lab values
  (serum 25(OH)D, ferritin/transferrin saturation, homocysteine, lipid panel)
  when clinical decisions are at stake.
- Absence of a marker from the catalogue is not evidence of negligible effect
  — the catalogue is intentionally small and curated.

## User-Facing Answer Shape

Do not add a routine Active Genome Index status line for these public catalogue
tools. For each cited marker:

- Variant identifier (rsID + gene)
- Established effect (single sentence)
- Evidence tier
- One or two of the most relevant `out_of_scope_claims` as disclaimers
- The single most relevant lab measurement that should accompany the marker
  (when applicable: homocysteine for MTHFR, 25(OH)D for vitamin D markers,
  ferritin + transferrin saturation for HFE)

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### nutrigenomics.build_source_context

Explain nutrigenomic catalogue provenance, domain definitions, evidence-tier meanings, method limitations, and the non-prescription boundary.

**Use when**: The user or agent asks what the nutrigenomics catalogue is, where the records come from, what evidence tiers mean, or why the capability refuses diet prescriptions.

**Why necessary**: Nutrigenomic language is easy to overstate. Explicit source context grounds the agent in the boundary before it interprets records.

**Not for**: Returning marker records; use nutrigenomics.retrieve_domain_markers or nutrigenomics.retrieve_variant_records.

**Example prompts**: Explain the source and limitations of Genomi's nutrigenomic catalogue.

**Result semantics**: Public metadata only. Returns capability provenance, declared domains, evidence-tier definitions, out-of-scope-by-construction items, and the non-prescription boundary note.

### nutrigenomics.list_domains

List declared nutrigenomic domains with evidence-tier coverage and explicit out-of-scope-by-construction notes.

**Use when**: The user asks what nutrigenomic domains Genomi covers, or the host agent needs to validate that a domain is in scope before retrieving markers.

**Why necessary**: Nutrigenomics is a pseudoscience-prone domain. Listing declared domains and explicit out-of-scope-by-construction items lets the agent refuse out-of-scope questions before reaching for marker records.

**Not for**: Returning specific marker records; use nutrigenomics.retrieve_domain_markers. Diet prescriptions, supplement dosing, weight-loss prediction.

**Example prompts**: What nutrigenomic domains does Genomi cover? Is weight-loss diet matching in scope for Genomi nutrigenomics?

**Result semantics**: Returns the declared domain catalogue, evidence-tier counts per domain, the out-of-scope-by-construction list, and the non-prescription boundary note.

### nutrigenomics.retrieve_domain_markers

Retrieve curated single-marker records for a declared nutrigenomic domain, filtered by minimum evidence tier.

**Use when**: The host agent needs curated single-marker evidence for a declared domain (folate_metabolism, lactose_tolerance, iron_storage, vitamin_d_status, lipid_diet_response, obesity_predisposition).

**Why necessary**: Returns evidence-tiered records with explicit out_of_scope_claims so the agent can ground a nutrient/tolerance discussion without propagating pseudoscience claims about the variant.

**Not for**: Diet prescriptions, supplement dosing, weight-loss prediction. Polygenic risk scoring; this is single-marker evidence only. Genome scanning; compose with active_genome_index.classify_genotype_support using the variant coordinates from each record. Population-stratified allele frequencies; use gnomad.fetch_population_frequency. Primary GWAS effect sizes; use gwas.compare_variant_associations with the gwas_catalog_id from downstream_traits_with_gwas.

**Example prompts**: What does Genomi have on folate_metabolism markers? Retrieve established-tier iron_storage records.

**Result semantics**: Each record carries variant identifiers, established_effect with GWAS Catalog chain-out, evidence_tier, resolvable source citations, established_caveats, and out_of_scope_claims. The agent must surface out_of_scope_claims as disclaimers rather than paraphrase around them.

### nutrigenomics.retrieve_variant_records

Retrieve any nutrigenomic catalogue records referencing a specific rsID.

**Use when**: The host agent has a specific variant identifier and wants to know whether the nutrigenomic catalogue carries any records for it.

**Why necessary**: A variant may participate in more than one declared domain. Variant-anchored lookup surfaces all matching curated records at once.

**Not for**: Variant resolution from coordinate to rsID; use variant.resolve first. Variants outside declared nutrigenomic domains; in_scope_empty indicates the catalogue does not cover the variant.

**Example prompts**: What does Genomi say about rs1801133 nutrigenomically? Are there nutrigenomic records for rs429358?

**Result semantics**: Returns one or more curated records referencing the variant. coverage_status='in_scope_empty' when the variant is not in the catalogue; absence is not evidence of negligible effect.
