---
name: ancestry
version: 1.0.0
description: |
  Use local ancestry reference-panel tools for 1000 Genomes GRCh38 PCA
  projection, marker overlap QC, and qualitative reference-neighbor context.
tools:
  - genomi.check_libraries
  - genomi.describe_context
  - ancestry.list_reference_panels
  - ancestry.build_source_context
  - ancestry.check_sample_overlap
  - ancestry.project_pca
  - ancestry.estimate_population_context
  - active_genome_index.approve_access
  - genomi.parse_source
mutating: false
---

# Ancestry Reference-Panel Context

Use this skill when the user asks about ancestry, population context, PCA
projection, reference-panel similarity, or which public reference samples their
genome is closest to.

## Contract

- This capability is a local reference-panel workflow, not an ethnicity or race
  predictor.
- Private tools require current-session Active Genome Index access approval or a genome source
  path supplied in the current chat.
- Public metadata tools do not read an Active Genome Index.
- Private genotype data stays local. Do not upload sample genotypes to external
  APIs or URLs.
- The MVP supports GRCh38 only. If `genome_build` is omitted, the tool default
  is GRCh38 unless an approved Active Genome Index provides another build; the
  returned `defaults_applied` records that default.
- Labels are 1000 Genomes reference-panel labels, not ethnicity, nationality,
  race, tribe, caste, religion, or personal identity.
- Output is qualitative reference-panel similarity in PCA space. Do not produce
  component percentages, admixture proportions, haplogroups, local ancestry,
  ancestry dates, or relative matching.

> **Convention:** See `skills/conventions/context-routing.md`.
> **Convention:** See `skills/conventions/evidence-quality.md`.
> **Convention:** See `skills/_output-rules.md`.

## First Actions

1. Use `ancestry.list_reference_panels` to check whether the 1000 Genomes
   30x GRCh38 panel is installed and to inspect source URLs and label
   definitions.
2. Use `ancestry.build_source_context` when the user asks what the panel means
   or when you need explicit label and method boundaries before answering.
3. For sample-specific questions, use `genomi.describe_context` only
   when the chat asks about current Active Genome Index context or already mentioned a
   genome source. If the user supplied a genome source path, that is approval to read
   it for this session.
4. Use `ancestry.estimate_population_context` as the default sample-specific
   entry point. It runs overlap QC and PCA projection when enough markers are
   usable.
5. Use `ancestry.check_sample_overlap` when you only need QC readiness, and
   `ancestry.project_pca` when the host agent needs raw PCA coordinates and
   nearest reference-neighbor distances.

## Library Handling

The required optional library is `ancestry-1000g-30x-grch38`. If a private
ancestry tool returns `requires_library_install`, explain that the compact local
panel is needed for marker overlap and PCA projection, then ask before
installing:

```bash
python3 scripts/install_for_agents.py --libraries ancestry-1000g-30x-grch38
```

Do not treat a missing panel as evidence about the sample.

## Interpretation Rules

- Report marker overlap, projection readiness, marker-overlap quality, nearest reference
  group labels, and the method boundary.
- If fewer than 500 panel markers are usable, do not project.
- If 500-1999 panel markers are usable, do not produce a default reference
  similarity interpretation.
- If 2000-9999 panel markers are usable, projection is allowed with low
  marker-overlap quality.
- If at least 10000 panel markers are usable, projection is allowed with
  moderate marker-overlap quality.
- Use wording like: "The sample projects closest to the EUR reference cluster
  in this panel."
- Do not say "predict ethnicity", "determine origin", or imply personal
  identity from a reference-panel label.

## User-Facing Answer Shape

If an Active Genome Index was projected, give the qualitative reference-panel
similarity, marker-overlap quality, and limitations. If the tool only returned public
metadata, answer directly without an Active Genome Index status disclaimer.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### ancestry.build_source_context

Explain 1000 Genomes ancestry panel provenance, label meanings, sampling limits, and method boundaries.

**Use when**: The user asks what the ancestry panel means, where labels come from, or why output is reference similarity rather than identity.

**Why necessary**: Ancestry language is easy to overstate; source context gives agents explicit label and method boundaries before answering.

**Not for**: Reading or projecting a user's genome; use ancestry.estimate_population_context after approval.

**Example prompts**: Explain the source and limitations of the ancestry panel.

**Result semantics**: Public metadata only; no Active Genome Index is read.

### ancestry.check_sample_overlap

Check how many installed 1000 Genomes ancestry panel markers are usable in an approved Active Genome Index.

**Use when**: The agent needs to know if a selected sample has enough overlap with the installed ancestry reference panel before projection.

**Why necessary**: Projection is not interpretable below the overlap thresholds; this tool separates QC from interpretation.

**Not for**: Public panel metadata; use ancestry.list_reference_panels. Ethnicity or origin prediction; ancestry tools provide reference-panel similarity only.

**Example prompts**: Does my Active Genome Index have enough overlap with the ancestry panel?

**Result semantics**: Reports usable marker count and projection readiness. It must not be interpreted as ethnicity, nationality, race, tribe, caste, religion, or identity.

### ancestry.estimate_population_context

Estimate qualitative reference-panel similarity for an approved GRCh38 sample using local 1000 Genomes PCA projection.

**Use when**: The user asks for ancestry or population context from their genome and has approved Active Genome Index use in this session.

**Why necessary**: Provides a bounded default entry that combines overlap QC and PCA projection while preserving reference-similarity language.

**Not for**: Ethnicity prediction, determining origin, component percentages, haplogroups, local ancestry, or relative matching.

**Example prompts**: What 1000 Genomes reference cluster is my Active Genome Index closest to?

**Result semantics**: Uses schema genomi-ancestry-population-context-v1. The interpretation is qualitative reference-panel similarity only and must never be phrased as ethnicity, nationality, race, tribe, caste, religion, or personal identity.

### ancestry.list_reference_panels

List local ancestry reference panels, installation state, public source URLs, label definitions, and method boundaries.

**Use when**: The user asks what ancestry reference panels are available, whether the 1000 Genomes panel is installed, or what source data and labels are used.

**Why necessary**: Public panel metadata can be inspected without Active Genome Index access approval and tells agents whether private projection tools are answerable.

**Not for**: Projecting or interpreting a user's genome; use ancestry.estimate_population_context after Active Genome Index access approval.

**Example prompts**: What ancestry reference panel does Genomi have installed?

**Result semantics**: Returns public reference-panel metadata and install status only; it does not read Active Genome Index.

### ancestry.project_pca

Project an approved sample into the installed 1000 Genomes ancestry PCA space and return nearest reference neighbors.

**Use when**: The user or host agent needs PCA coordinates and nearest reference neighbors after scoped Active Genome Index access is approved.

**Why necessary**: This is the focused computational step behind ancestry.estimate_population_context and avoids component/admixture proportion claims.

**Not for**: Haplogroups, local ancestry, relative matching, component proportions, or identity/origin prediction.

**Example prompts**: Project my GRCh38 genome into the 1000 Genomes PCA panel.

**Result semantics**: Returns PCA coordinates and reference-neighbor distances only; labels are reference-panel labels, not personal identity labels.
