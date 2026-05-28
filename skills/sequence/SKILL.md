---
name: sequence
version: 1.0.0
description: |
  Deterministic sequence utilities for translation, ORFs, restriction sites,
  Kozak context, primer checks, and local FASTA record matching.
tools:
  - sequence.analyze
  - sequence.match_reference
  - sequence.translate
  - sequence.find_orfs
  - sequence.find_restriction_sites
  - sequence.classify_kozak
  - sequence.check_primers
mutating: false
---

# Sequence

Use this skill when the user supplies a DNA sequence and asks for ORFs,
translation, restriction sites, Kozak context, primer checks, local FASTA
record matching, or simple bench-style sequence QA.

## Contract

- These tools operate only on supplied sequence strings and explicitly supplied
  local reference FASTA files.
- They do not use active genome context or external services.
- Report deterministic sequence facts directly. Add biological interpretation
  only when the user supplies enough context or separate source evidence.

## Tool Flow

- Use `sequence.analyze` when more than one deterministic sequence fact may be
  needed.
- Use `sequence.match_reference` when a local FASTA can identify the
  supplied sequence before downstream reasoning.
- Use `sequence.translate` for frame/strand translation.
- Use `sequence.find_orfs` for ATG-to-stop ORF discovery.
- Use `sequence.find_restriction_sites` for common enzymes or custom motifs.
- Use `sequence.classify_kozak` for ATG start-context checks.
- Use `sequence.check_primers` for basic GC, Wallace Tm, self-complementarity,
  and optional template amplicons.

Examples:

- `sequence.translate` with `{"sequence":"ATGGCCATTGTAATGGGCCGCTGA","frame":1}`
- `sequence.find_orfs` with `{"sequence":"AAATGAAATAG","min_aa":1}`
- `sequence.find_restriction_sites` with `{"sequence":"GAATTCGGATCC","enzymes":["EcoRI","BamHI"]}`
- `sequence.match_reference` with `{"sequence":"ATGAAATAA","reference_fasta":"refs.fa"}`

## Answering

Give the computed result and enough coordinates or frame details to make the
answer auditable. Do not turn sequence utility output into medical or
personal-genome interpretation.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### sequence.analyze

Run a compact deterministic sequence analysis bundle and point to focused sequence tools when needed.

**Use when**: The user supplies DNA/RNA sequence text and may need translation, ORF, motif, Kozak, or local FASTA identity facts.

**Why necessary**: Supplied DNA strings need deterministic sequence utilities before any biological interpretation.

**Example prompts**: Translate this DNA sequence and find ORFs.

**Result semantics**: Computes deterministic sequence facts from supplied text and optional local FASTA reference matches; no external annotation is performed.

### sequence.check_primers

Check basic primer properties and optional template amplicons.

**Use when**: Checks primer GC, melting temperature, self-complementarity, and optional amplicon context.

**Why necessary**: Primer checks combine basic thermodynamic and amplicon facts that are not variant evidence.

**Result semantics**: Performs lightweight deterministic primer checks; it does not replace full primer-design thermodynamics.

### sequence.classify_kozak

Classify Kozak sequence context around ATG start codons.

**Use when**: Checks Kozak/start-codon context around a supplied DNA sequence position.

**Why necessary**: Start-codon context is a specialized expression-design check and should stay separate from general translation.

**Result semantics**: Uses the simple -3 A/G and +4 G Kozak rule; experimental expression strength needs separate evidence.

### sequence.find_orfs

Find ATG-to-stop open reading frames in a supplied DNA sequence.

**Use when**: Finds open reading frames and coding-sequence candidates in a supplied DNA sequence.

**Why necessary**: ORF detection identifies candidate coding regions without relying on external annotation.

**Result semantics**: Finds simple ATG-to-stop ORFs from supplied sequence text; biological annotation requires separate source evidence.

### sequence.find_restriction_sites

Find common restriction enzyme or custom motif sites in a supplied DNA sequence.

**Use when**: Maps restriction enzyme sites and sequence motifs in a supplied DNA sequence.

**Why necessary**: Cloning and motif checks need exact site positions in the supplied sequence.

**Result semantics**: Reports motif positions in the supplied sequence; it does not model methylation or digestion conditions.

### sequence.match_reference

Match a supplied DNA sequence against local FASTA records and return record identifiers plus annotations.

**Use when**: The task supplies a DNA sequence and a local FASTA/reference set that can identify the sequence record before downstream reasoning.

**Why necessary**: Local FASTA matching identifies sequence records before downstream reasoning about that sequence.

**Result semantics**: Returns exact local FASTA record matches and header annotations; the host agent decides whether a matched record answers the question.

### sequence.translate

Translate a DNA sequence in a selected frame and strand using the standard genetic code.

**Use when**: Translates a supplied DNA sequence into codons or amino acids for the requested frame and strand.

**Why necessary**: Protein translation requires explicit frame and strand control rather than informal sequence reading.

**Result semantics**: Computes deterministic sequence facts from the supplied string only; no genome context or external IO is used.
