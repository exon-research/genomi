---
name: genomi
description: Use this skill for genetics, genome source, variant, gene, phenotype, disease, screen, pharmacogenomics, and Genomi install/setup maintenance questions.
---

# Genomi

Genomi gives agents local tools for genetics and DNA-aware evidence work. Use it
when the user's request is about variants, genes, phenotypes, disease genes,
biological screens, medication response, ancestry reference-panel context,
polygenic-score context, or a
genome source.

## How To Call Genomi

Call Genomi through the MCP server: `mcp__genomi__<operation>` (or your
host's equivalent namespace).

If those tools are missing from the current session's tool list but the
host's MCP list shows Genomi connected, the session pre-dates the server's
registration. Ask the user to start a new session.

## Core Rules

- Public by default: if the chat has not mentioned a genome source, answer
  from public/tool sources only.
- Active Genome Index context is chat-scoped: use it only when this conversation
  provides a genome source, names a previous run, asks about the selected Active Genome Index
  context, or says something like "my Active Genome Index" or "my genome".
- If the user provides a genome source path in this chat, that is approval to read
  that source for this session.
- If the user says "my Active Genome Index" or "my genome" without a path, it is acceptable to
  check for an already imported Active Genome Index context.
- Reading imported/parsed Active Genome Index artifacts, resuming a previous run for
  evidence, or searching for an existing "my Active Genome Index"/"my genome" context requires
  explicit user approval for this session. Record approval with
  `active_genome_index.approve_access` before calling those tools.
- Do not use unrelated genome sources from other chats, workspaces, or external
  evaluation tasks.
- Call narrow tools first and inspect evidence before making a claim.
- Treat this root skill as static startup guidance. Do not infer live session
  state from it; use `genomi.describe_context`,
  `genomi.check_libraries`, and tool result envelopes for changing context.
- If an MCP tool returns `status="in_progress"`, call
  `genomi.check_background_job` with the returned `job_id`. Do not retry the
  same work with a capped parse or raw text scan unless the user asks for that
  fallback.
- Only send parameters supplied by the current user request, current Genomi
  context, a previous Genomi result, explicit user approval, or an explicit
  override. Omit unknown optional parameters.
- Defaults are part of the reasoning chain. Tool definitions expose
  `parameterDefaults`; returned results include `defaults_applied` for omitted
  defaults so the host agent can inspect and override them in a follow-up call
  when the user intent requires it.
- Tool definitions expose `dependencyContract` when a tool needs local
  installed libraries or external network/API sources. Missing local libraries
  return `requires_library_install`; unavailable external sources return
  `source_unavailable`; local source-file requirements appear as
  `localResources`.
- In the final answer, mention Active Genome Index use only when it materially
  affects the result: for example, it supports or refutes a user-specific claim,
  changes a limitation, blocks an operation until approval, or explains a
  required next action. Do not add a routine source-status line.
- Derive confidence dynamically for each Genomi-guided answer from tool
  evidence, source trust, coverage, conflicts, and missing evidence. Do not use
  a static default confidence or a user-selected confidence profile.
  Genomi result fields describe evidence support, coverage, overlap, and source
  state; they are not final answer-confidence labels.
- Use `genomi.describe_context` when the user asks about personal context,
  their own genome/context, a genome source, a previous run, a selected user,
  or before making sample-specific claims. When you call it, inspect
  `active_response_profile.guidance`; the active profile id is persisted in
  the Genomi registry (set via `genomi.set_response_profile`) and falls back
  to the catalog default in `src/genomi/runtime/host_response_profiles.json`
  when none is set. Do not call it only to bootstrap a public-only question.
- Handle Active Genome Index lifecycle states yourself. When a read op's
  envelope or `genomi.describe_context` returns
  `active_genome_index_readiness.status == "needs_reparse"`, look up the recorded source
  path under `active_genome_index.source` and call `genomi.parse_source`
  with it — routine maintenance, no user prompt needed. Only ask the user
  when `availability.source` is false (path moved or deleted) or the
  status is `schema_too_new` (Genomi runtime out of date). Never proceed
  with a stale Active Genome Index while silently substituting placeholder data; see
  `skills/active-genome-index/SKILL.md` for the full procedure.
- For search-like operations, pass host-inferred alternate wording in
  `semantic_context` when the current chat reasonably supports alternate
  biomedical wording. Send the user's original wording as `raw_query`, add
  `host_expansions` only as retrieval terms, and add `host_entities` for helpful
  proposed spans such as drug, gene, phenotype, trait_or_condition, variant, or
  rsid. These terms are retrieval inputs, not evidence; Genomi reports
  source/retrieval hits in `term_matches` and no-hit terms in `term_misses`.

## Routing

MCP `tools/list` returns only the base set:

- `genomi.*` and `journal.*` ops (always direct-callable).
- `genomi.invoke` — the dispatcher for every other capability tool.

To use a non-base capability tool, read the matching
`skills/<capability>/SKILL.md` (Anthropic Claude Code Skills auto-loads each
as `~/.claude/skills/genomi-<capability>/SKILL.md` based on its frontmatter
`description`), then call:

```
genomi.invoke({"tool": "<operation_name>", "params": {...}})
```

Example:

```
genomi.invoke({"tool": "variant.resolve", "params": {"rsid": "rs429358"}})
```

The dispatcher validates the registered operation name, runs the underlying tool's
input-schema validation, and returns the underlying tool's response with an
added `dispatched_tool` field.

Operation namespaces are tool-name prefixes, not disclosure branches. Use
namespace filters only for debugging or audits.

Resolve context, select the intent capability, read its skill markdown, call
the smallest useful operation through `genomi.invoke` (or direct call for
base tools), inspect evidence, journal material findings, and continue until
the answer is supported. Use `genomi.describe_context` only when this chat
asks about personal context, the user's own genome/context, Active Genome Index
context, a selected user, a genome source, or a previous run.

## Setup

`genomi.install` installs **or updates** Genomi, and `genomi install` /
`genomi update` are the same operation. It always updates everything that can
be updated: the runtime code (`git pull --ff-only` on a git checkout, unless
`GENOMI_SKIP_RUNTIME_GIT_PULL` is set for a non-git distribution), all public
reference libraries into `GENOMI_HOME` (idempotent — each installed library is
checked against its source and re-downloaded only if it changed upstream, so
re-running transfers nothing when nothing changed; pass `force` to re-download
regardless), the public retrieval indexes, and a
background reparse of any genome whose index schema is older than the updated
runtime's. There are no per-step skip flags — `genomi update` does the full
update by default. The `libraries` parameter only narrows *which* reference
libraries to materialize (default `everything`): pass a specific library (or
comma-separated set) to install just those — both for an install-time subset
the user chose and to add a single new library on demand at runtime (the
"install this missing library" path). To see which libraries are already
installed vs missing before deciding, call `genomi.check_libraries` (its
summary reports `installed_count` / `missing_count`). This applies once Genomi
is installed; first-time setup on a machine without the `genomi` runtime
follows the source bootstrap in `INSTALL_FOR_AGENTS.md`.

## Parsing A Genome Source

`genomi.parse_source` is a core `genomi.*` tool: it detects, parses, and
digitizes a genome source (VCF/gVCF, BAM, paired-end FASTQ, or a
consumer-array raw genotype export from 23andMe, AncestryDNA, MyHeritage,
FamilyTreeDNA, or Living DNA; bare text/CSV, gzip/bzip2/xz-compressed, or
inside a zip/tar archive) into a queryable Active Genome Index.

- **Use when**: the user supplied a genome source in this chat and downstream
  questions need a queryable Active Genome Index this session.
- **Why**: raw VCF/BAM/genotype files are too large and irregular for reliable
  direct reasoning; parsing builds the scoped index later tools query.
- **Not for**: public-only genetics questions, selecting an already-parsed
  index, or capped sample scans that should not replace a complete index.
- **Result**: digitizes local intake into an Active Genome Index; Genomi
  auto-detects the source type. Supplying `user_nickname` links the parsed
  artifact to a user profile. It does not run whole-callset annotation —
  focused tools materialize public libraries lazily when their evidence is
  needed.
- If it returns `status="in_progress"` with a `job_id`, poll
  `genomi.check_background_job`; don't substitute a capped parse or raw scan
  unless the user explicitly asks for a fallback.
- **gVCFs parse in two phases.** A gVCF is ~96% reference blocks, so the parse
  returns as soon as **every variant** is stored and indexed — the result
  reports `variants_ready` (not yet `completed`) and the whole interpretation
  surface (rsID, gene, region, exact-allele lookup, ClinVar, PRS, …) is already
  correct. The reference-block tail is appended by a detached background job
  (`active_genome_index.build_reference_pass`) whose `job_id` is surfaced in the
  result's `next_actions`. Until that job reports `completed`, only "is this
  locus confirmed reference vs not-callable" coverage answers are provisional —
  every readiness/coverage result carries `reference_pending` to say so. Plain
  VCFs, small files, and capped (`max_records`) parses stay single-phase. Other
  sources (consumer arrays, BAM/FASTQ) have no reference tail to defer.
- **After a parse, offer to name the profile.** When the user did not pass
  `user_nickname`, the result includes an `ask_user` next action: ask them for a
  profile nickname and whether to set it as the machine default, then record it
  by re-running with `user_nickname` (+ `set_default_user=true`) or via the
  invoke-only `active_genome_index.assign_user_genome` / `set_default_user`
  tools — exactly the offer `INSTALL_FOR_AGENTS.md` Step 8 makes.

The parse/digitize/user-management **workflow** (selecting users, approving
access, assigning a genome to a profile, lifecycle reparse) lives in
`skills/active-genome-index/SKILL.md`, which also owns the
`active_genome_index.*` interpretation tools.

## Journal

Use journal when an investigation spans multiple Genomi tools and the host
agent needs to record reasoning over evidence. Journal entries are agent notes
with traceability links; they are not source evidence and should not be used as
candidate-ranking `source_records`.

## Default Tools

These tools appear in the default tool list. Their full metadata is available
without expansion.

Genomi context and users:

- `genomi.check_background_job`
- `genomi.check_libraries`
- `genomi.describe_context`
- `genomi.install`
- `genomi.invoke`
- `genomi.list_resources`
- `genomi.search_indexes`

Active Genome Index:

- `genomi.parse_source`

All other `active_genome_index.*` tools are invoke-only: reach them via
`genomi.invoke` after reading `skills/active-genome-index/SKILL.md`.

ClinVar:

- `clinvar.match_variants`
- `clinvar.scan_candidates`

ClinVar exact matching uses the build-specific optional library
`clinvar-grch38` or `clinvar-grch37`. If the tool reports
`requires_library_install`, use `genomi.check_libraries` and ask before
installing.

Variant evidence:

- `variant.resolve`

Journal and research memory:

- `research.build_target_packet`
- `research.list_sources`

Phenotype, disease, and candidate gene:

- `phenotype.compare_disease_evidence`
- `phenotype.compare_drug_target_evidence`
- `phenotype.compare_gene_hpo_evidence`
- `phenotype.plan_risk_investigation`
- `phenotype.retrieve_disease_drug_targets`
- `phenotype.retrieve_gene_disease_associations`
- `phenotype.retrieve_trait_gene_records`

Pharmacogenomics:

- `pharmacogenomics.review_medication`

GWAS Catalog:

- `gwas.compare_gene_associations`
- `gwas.compare_variant_associations`

Functional genomics:

- `functional_genomics.compare_gene_perturbation`

Ancestry reference-panel context:

- `ancestry.list_reference_panels`
- `ancestry.estimate_population_context`

Polygenic scores:

- `prs.search_scores`
- `prs.calculate_score`

Sequence:

- `sequence.analyze`

Analytical grounding:

- `cell_type.retrieve_markers`
- `pathway.retrieve_members`
- `region.retrieve_features`

Journal:

- `journal.append_entry`
- `journal.search_entries`

Default-complete categories:

- `gwas-catalog`
- `analytical-grounding`

## Candidate Evidence

Candidate and ranking operations return evidence views, `decision_evidence`,
warnings, and coverage.
Use source-specific candidate-gene tools instead of a universal comparator:
`phenotype.compare_gene_hpo_evidence` for HPO/single-subject phenotype
matching, `gwas.compare_gene_associations` for GWAS Catalog gene-field
evidence, `phenotype.compare_drug_target_evidence` for drug-target evidence,
and `functional_genomics.compare_gene_perturbation` for perturbation evidence.
`phenotype.retrieve_trait_gene_records` retrieves trait-to-gene records from integrated
sources. Records labelled `association_only_not_causal` are visible evidence,
not an answer.
Any operation that exposes an answer-shaped candidate result must expose the
evidence behind that result. Use that evidence for the host-agent decision.

## Multi-Stream Synthesis

When multiple Genomi capabilities can contribute orthogonal evidence to the
same question, combine them — both in the initial plan and in follow-ups.

A scope-limited single-capability result (missing calibration, no record at
locus, association-only, library-not-installed, low overlap, source
unavailable, etc.) is not a final user-facing answer when other Genomi
capabilities can contribute orthogonal evidence to the same question.
Returning "I cannot answer" while applicable capabilities remain unexamined
is a host-agent failure mode, not a Genomi limitation.

When multiple plausible plans differ materially in cost, surface the choice
once with the tradeoff and commit to the user's pick. Over-checkpointing is
itself a failure mode.

## Answering

Lead with the answer. When a finding is grounded in a public dataset
(ClinVar, GWAS Catalog, PGS Catalog, 1000 Genomes panel, etc.) and that
source materially shapes the result, name the dataset inline in the
prose. Keep clinical language informational and recommend clinical
confirmation for medical decisions. Confidence is an answer-time
synthesis judgment, not static metadata. Adapt explanation depth to the
selected response profile without weakening evidence limits, privacy
boundaries, or clinical-confirmation language.
