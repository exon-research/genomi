---
name: genomi-gnomad
description: |
  Fetch reusable public population allele frequencies from gnomAD for a
  specific variant. Use when the user asks about allele frequency, MAF,
  population stratification, gnomAD numbers, or rarity of a specific allele.
tools:
  - genomi.invoke
mutating: false
---

# Population Frequency (gnomAD)

Fetch public gnomAD population allele frequencies for one variant. Results
are cached locally in the evidence database so subsequent queries reuse them.

## Activation

To call the tool below, invoke it through the MCP dispatcher:

```
genomi.invoke({
  "tool": "gnomad.fetch_population_frequency",
  "params": {
    "chrom": "19",
    "pos": 44908684,
    "ref": "T",
    "alt": "C",
    "genome_build": "GRCh38"
  }
})
```

The dispatcher validates the params against the underlying tool's input
schema and returns the underlying tool's response with an added
`dispatched_tool` field.

## When to use this skill

- "What is the gnomAD frequency of rs429358?"
- "Is this variant rare in gnomAD?"
- "Allele frequency in African populations for rs1042522."
- Any question that needs MAF, AF, population-stratified counts.

## Boundaries

- Variant-anchored only — query one allele at a time.
- Public population data only — does not read the user's Active Genome Index.
- Cached after first fetch — subsequent queries for the same variant hit the
  local evidence store unless `force: true` is passed.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### gnomad.fetch_population_frequency

Fetch reusable gnomAD public population frequency for one allele and write it into evidence storage.

**Use when**: The agent needs gnomAD allele frequency, MAF, or population-stratified counts for a specific variant (rsID, chrom/pos/ref/alt, or VCF locus).

**Why necessary**: gnomAD is the canonical public population frequency source; cached results keep subsequent calls cheap.

**Not for**: Genome-wide rare-variant screening, ad-hoc curated annotations, anything not anchored to a specific variant.

**Example prompts**: What's the gnomAD frequency of rs429358? Is rs1042522 rare in East Asian populations?

**Result semantics**: Returns the gnomAD record with population-stratified counts and frequencies plus a `populations` block; writes to the local evidence database for reuse.
