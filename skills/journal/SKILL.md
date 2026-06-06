---
name: journal
description: |
  Maintain agent-authored investigation memory over Genomi evidence links,
  reviewed source findings, decisions, contradictions, and unresolved questions.
tools:
  - journal.append_entry
  - journal.search_entries
  - journal.summarize
  - journal.export_memory
  - research.list_sources
  - research.build_target_packet
  - gnomad.fetch_population_frequency
  - research.record
  - research.query
  - research.search
mutating: true
---

# Journal and Research Memory

Use journal when an investigation spans multiple Genomi tools and the host
agent needs to record reasoning, evidence links, or reviewed source findings.

## Goal

Record the host agent's observations, hypotheses, decisions, contradictions,
plans, summaries, and unresolved questions while preserving traceability to
Genomi operations and evidence identifiers.

Journal entries are the append-only notebook. Reviewed research records are
source-memory entries in the evidence DB. They live in the same capability
because both preserve investigation memory, but they have different roles:
journal entries explain what the host agent concluded or still needs to check;
reviewed research records store source-backed findings for reuse.

Neither journal entries nor reviewed research records rank candidates by
themselves. Candidate ranking still belongs to the relevant evidence tools, with
reviewed source records passed only when a tool explicitly accepts them.

## Scopes

- `session`: current chat/session notebook. It may link private/sample evidence
  only after scoped Active Genome Index access is approved for this session.
- `project`: current workspace notebook. It is public/target-scoped and
  rejects private/sample evidence links.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### journal.append_entry

Append a new journal entry, or append evidence links and/or an amendment to an existing entry.

**Use when**: Record an observation, hypothesis, decision, contradiction, plan, summary, unresolved question, or append evidence/amendment to an existing entry.

**Why necessary**: Multi-tool investigations need one append-only write path for notes, evidence links, and corrections so agents do not sequence separate journal mutations.

**Not for**: Not source evidence and not a candidate-ranking input by itself.

**Example prompts**: Record this supported Genomi finding with evidence links.

**Result semantics**: With no entry_id, creates a new entry. With entry_id, adds evidence_links and/or stores content as an append-only amendment; original entry text is preserved.

### journal.export_memory

Return a MemOS-shaped JSON memory artifact from journal entries without requiring or writing to MemOS.

**Use when**: The user or host agent explicitly wants the journal exported for ingestion by another memory system.

**Why necessary**: External memory systems need a shaped export without requiring Genomi to write to that system.

**Result semantics**: Exports journal memory records only; private evidence links are omitted unless explicitly requested and approved.

### journal.search_entries

Token-search session and project journal entries by scope, target, tag, entry type, and text.

**Use when**: The host agent needs to recover recorded investigation state before continuing a multi-tool Genomi analysis.

**Why necessary**: Agents need to recover prior investigation state without treating chat memory as authoritative evidence.

**Result semantics**: Returns agent-authored notes and traceability links; journal entries are not source evidence.

### journal.summarize

Summarize journal state into observations, decisions, contradictions, unresolved questions, and commonly linked evidence sources.

**Use when**: The host agent needs a compact state of an ongoing Genomi investigation before deciding next evidence steps.

**Why necessary**: Long investigations need compact journal state before the agent chooses the next evidence step.

**Result semantics**: Summarizes journaled reasoning only; evidence authority remains in the linked Genomi outputs and public sources.

## Operating Checks

- Link evidence for traceability, but treat linked Genomi outputs and public
  sources as the authority.
- When a downstream tool needs `source_records`, provide reviewed research or
  tool-returned source records that satisfy that tool's verified source-record
  input contract.
- Use `journal.append_entry` with `entry_id` for corrections; do not silently
  overwrite entries.
- Omit private evidence links from memory exports unless the user explicitly
  requests them and scoped Active Genome Index access is approved for the
  session.
