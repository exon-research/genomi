# Genomi Context Convention

Rules for selecting the Active Genome Index and evidence database.

## Context Axes

- **Active Genome Index home** = durable Active Genome Index storage. `GENOMI_HOME`, default `~/.genomi`.
- **Active Genome Index** = the currently selected digitized genome source for this agent session.
  `GENOMI_CONTEXT` can pin a context file; `GENOMI_SESSION_ID` can pin a
  session namespace.
- **Evidence context** = the Active Genome Index evidence DB plus optional shared evidence DB.
  Private sample evidence stays in the Active Genome Index DB; reusable public-target findings
  can live in the shared DB.
- **Source context** = the source adapter or reviewed-source protocol selected
  from `research.list_sources`.

Pick Active Genome Index, evidence context, and source context separately for
each operation.

## Default behavior

Start from the current session context:

1. Run `genomi.describe_context`.
2. If it has an accessible Active Genome Index, Active Genome Index-aware tools use the selected Active Genome Index.
   VCF-specific tools resolve `vcf`, `db`, `active_genome_index_path`, and
   `matches` from a VCF/gVCF-derived Active Genome Index.
3. If it has public-only context, keep public/source/GWAS/shared-evidence work
   available.
4. If the user supplies a source path, read `skills/active-genome-index/SKILL.md`.
   The supplied path is approval to read that source for this session. Use
   `genomi.parse_source` when the question needs an Active Genome Index.
5. If the user explicitly names a known `agi_id`, approve that specific Active Genome Index
   with `genomi.approve_agi_access` before using parsed Active Genome Index evidence.
6. If the user names a profile nickname, select the user with
   `genomi.select_user`. That is metadata-only unless the selected user is the
   default user or the session explicitly approves the selected Active Genome
   Index with `genomi.approve_agi_access`.
7. If one user is configured as the default user, Genomi auto-selects that
   user's selected Active Genome Index for every session using this
   `GENOMI_HOME` without a separate per-session approval step. Other genome
   records for the same user remain metadata-only until explicitly approved.

Parsed Active Genome Index records become active when the session names the source path, `agi_id`,
or default user's selected Active Genome Index.

## When to select context

Select or change the Active Genome Index when:

- The user supplies a genome source path.
- The user explicitly says to use a known `agi_id`.
- The user names a user/profile nickname and then approves that user's selected
  Active Genome Index for sample evidence, unless that user is the default user.
- The user is in a multi-sample environment and names the sample or Active Genome Index for this query.
- The selected skill or user request requires sample-specific evidence.

Keep public-only context when:

- A file happens to exist under `GENOMI_HOME`.
- Multiple parsed Active Genome Index records exist and no default user or explicit Active Genome Index is selected.
- The user asks a public genetics question that uses public evidence.

## Multi-sample mode

For organizations or other multi-sample use, every query must carry an explicit
source path, `agi_id`, user/profile nickname, or session context. Multiple genome sources can share one
`GENOMI_HOME`; the Active Genome Index is still per session.

Recommended patterns:

- One host-agent thread per sample: set `GENOMI_SESSION_ID=<sample-or-case>`.
- Multi-sample automation: pass `source`, `agi_id`, or user/profile nickname into every sample-specific tool call, or
  set a dedicated `GENOMI_SESSION_ID` per sample.
- Human exploratory session: use `genomi.describe_context` before personal claims.

## Context Checks

- Use the session-selected Active Genome Index for sample-specific claims.
- Use one selected source or Active Genome Index per sample-specific answer.
- Use public-only language when the session has no selected genome.
- Use the Active Genome Index after parsing; surface the intake path for rebuild or
  validation work.
