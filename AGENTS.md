# Genomi Development Agent Instructions

This file is for agents developing Genomi itself. It is not host-agent runtime
guidance. Host-facing runtime guidance lives in `SKILL.md`, focused skill docs,
and Genomi MCP tool metadata.

## Genomi Design Principles

Edit this section only with explicit owner approval.

1. Genomi should balance deterministic computation with agent judgment.
   Tools should structure evidence, not become a bottleneck that prevents the
   agent from using its reasoning.

2. Tool contracts should carry the architecture.
   Routing and answer-selection rules belong in schemas, required parameters,
   tool names, and runtime validation, not mainly in skill Markdown.

3. Tool names must be distinct verbs that say what the tool does.
   If multiple tools share the same real job, refactor or consolidate them. Do
   not keep aliases or backward-compatible duplicate names.

4. Candidate-gene evidence must preserve source priors.
   Drug-target, GWAS, screen, rare-disease, and locus-to-gene evidence can point
   to different candidates. Do not collapse them into one universal "best" gene.

5. Agent decisions need their evidence everywhere.
   Any tool surface that presents a candidate, ranking, or answer-shaped result
   must also present the evidence that led to it. The agent host decides.

6. Progressive disclosure should move from capability to focused tools, without mandatory ceremony.
   Do not expose the whole toolset at once, but do not force bootstrap and
   repeated discovery before ordinary evidence work.

7. Internal coherence is not enough.
   A cleaner tool surface can still reduce answer quality if it makes the wrong
   evidence prior feel authoritative.

8. Agent-facing documents should not expose Genomi internals.
   They should describe capabilities, privacy boundaries, and how to use tools,
   not internal implementation details.

9. Agent-facing surfaces must preserve the Active Genome Index boundary.
   Raw genome sources and parsed Active Genome Index artifacts are
   session-scoped. Do not expose or reuse them across chats unless the current
   session explicitly supplies or approves that context.

10. Tool outputs should be decisive only when evidence supports that shape.
   Low-confidence or non-direct evidence should not be presented as an answer.

11. Measure whether tools improve agent outcomes.
   Track whether a tool helps answer correctness and call efficiency compared
   with the same agent working without Genomi.

12. Genomi is a library of capabilities, not a router for question shapes.
   Tools are verbs on declared data. The host agent owns question decomposition;
   Genomi does not classify agent intent or condition behavior on question category.

13. Every capability has a declared input scope and source coverage.
   For inputs inside that scope, a clean empty retrieval is a valid result:
   Genomi looked in the declared sources and found no matching records. For
   inputs outside that scope, Genomi must explicitly refuse the input as
   out-of-scope. The response shape must let the host agent distinguish
   `data_returned`, `in_scope_empty`, and `out_of_scope_for_input`; an
   out-of-scope input must not mimic an in-scope weak ranking. Agent-supplied
   evidence is allowed only for capabilities that explicitly validate or import
   supplied data; it must not substitute for native retrieval in a retriever.

14. One canonical contract owns answer-readiness.
   Every evidence-producing tool reports answer-readiness, scope, and
   negative-inference rules through `evidence_envelope`. If a new policy
   facet is needed, extend the envelope. Case-specific facts (which
   library, which gene, which input is missing) live in adjacent factual
   fields — `coverage`, `observations`, `next_actions`. The only prose
   allowed in tool output is evidence content authored by the user or by
   an upstream public source.

15. Every tool returns one presented shape.
   The shape leads with the envelope (headline first), keeps the full
   work-trace — steps, coverage, observations, source-level lists,
   materialization state, typed warnings — so the host agent can judge
   what the tool did, and prunes pure noise (empty arrays,
   false-defaulted scalars, local filesystem paths). Hosts read it as
   delivered.

16. Guidance codes must be self-explanatory.
   Each `guidance` entry is a stable identifier shaped as
   `<typed_state>:<imperative_directive>` using full English morphemes
   (e.g. `not_observed_in_consulted_scope:do_not_imply_clinical_negative`,
   `blocked_missing_library:ask_user_to_install`). A host agent must be able
   to act on the code on first read without a legend lookup. Discipline:
   one code per envelope state, no abbreviations, no per-case prose bullets.
   Case-specific facts (which library, which gene, which input is missing)
   belong in adjacent envelope fields — `coverage`, `observations`,
   `next_actions` — not in the code string. If a new policy class is needed,
   add a new code; do not extend an existing one with a second sentence.

17. Progressive disclosure has a concrete contract.
   The root `SKILL.md` is static startup guidance and lists default tools.
   Default tools expose full metadata without expansion. If a category has only
   default tools, the capability catalog must say it is default-complete and
   include the full default tool definitions. Focused expansion by capability
   or namespace must return both the focused skill documents and the full
   default-plus-expanded tool definitions for that category.

18. Focused guidance is loaded at the point of need.
   A host agent should not need to read every Genomi skill before ordinary use.
   When work enters a vertical category, Genomi must provide the relevant
   `skill_context.documents` beside the category toolset so the newest focused
   guidance is available in the current conversation context.

19. Tool schemas should stay compact.
   Do not repeat per-parameter provenance prose across every schema property.
   Host-supplied arguments should be constrained by required fields, enums,
   parameter names, native schema defaults, runtime validation, and focused
   skill guidance. If a parameter is not reliably available from the current
   request, selected context, previous Genomi result, explicit approval, or an
   explicit override, the host should omit it.

20. Defaults are evidence-relevant assumptions.
   Any default that affects interpretation must be visible in the tool
   definition through native schema defaults or compact default metadata, and
   visible in each result through `defaults_applied` when the host omitted that
   parameter. The host may then decide whether a follow-up call should override
   the default.

21. Long-running work must be resumable, not duplicated.
   Operations that exceed the interactive MCP window should return
   `status="in_progress"` with a background job identifier. Retrying the same
   operation and parameters while that job is active should reuse the job.
   Incomplete Active Genome Index artifacts must be reported as incomplete with
   a retry or resume operation rather than being treated as query-ready.

22. Missing optional libraries are not negative evidence.
   If a required evidence library is not installed, the tool must report that
   state explicitly and describe the blocked evidence scope. The host should
   explain how the library helps the user's intent and ask before installing it.
   Missing library evidence must never be interpreted as absence of variants,
   genes, associations, or risk.

23. The Active Genome Index reader is the read boundary.
   Production code outside `src/genomi/active_genome_index/` must not open,
   attach, or query Active Genome Index SQLite files directly. Route every AGI
   row read through `ActiveGenomeIndexReader` or through a narrow
   active-genome-index-owned helper exposed by that reader. If a capability
   needs a new AGI record contract, add a typed reader method instead of
   re-parsing AGI records in the capability. Name Active Genome Index variables,
   parameters, fields, and helpers with `agi_*`. Public operation namespaces
   such as `active_genome_index.*` are the exception and may keep their explicit
   namespace. Reserve `source_*` for the original genome source file during
   parse/intake only; downstream readers, handlers, and capabilities should not
   carry source-file aliases for AGI state.

24. Do not preserve broken backward compatibility.
   When an old contract is wrong, replace it with the correct contract and
   update callers, fixtures, tests, and docs together. Do not keep aliases,
   duplicate fields, compatibility modes, or fallback parsers that let the old
   incorrect behavior keep leaking through.

25. Do not anti-prompt around code defects.
   Avoid adding warning prose, prompt instructions, skill text, or schema
   verbosity to compensate for weak implementation. Fix the implementation,
   contract, evidence shape, or tests so the correct behavior is enforced in
   code.

26. Keep schemas and fields minimal.
   Only the Active Genome Index has schema versioning. Elsewhere, add schema
   fields only when they carry necessary data or enforce a real contract.
   Remove redundant provenance, duplicated labels, and parallel ways to express
   the same state.

27. Keep files below 1000 lines.
   No tracked text file should exceed 1000 lines. If a change would push a file
   past that limit, refactor into focused modules before adding the new
   behavior. Existing over-limit files should be split when touched for
   substantive work in that area; generated bundles need to be split at the
   generation step rather than edited by hand.

28. Tests must assert behavior, not refactor artifacts.
   Do not write `assertNotIn`/negative-string tests or before/after snapshots
   whose only purpose is proving a refactor renamed or removed something.
   Tests should exercise the durable contract and positive behavior: parsed AGI
   record kinds, reader-owned access, provenance fields, capability outputs,
   error states, and CI-visible user workflows.

29. Broad changes require independent functionality review.
   For AGI or capability-wide changes, spawn independent review/test agents in
   separate worktrees when feasible. Give each agent one functionality scope
   (for example AGI, PRS, ancestry, ClinVar, pharmacogenomics, decode, or
   source intake), enough context to review the whole behavior, and an explicit
   instruction to inspect functionality rather than only the latest diff. Use
   public fixtures for reproducible CI coverage; inspect private genome files
   only when the current session explicitly approves that exact path.

30. CI must exercise supported source formats and downstream capabilities.
   Public sample-derived fixtures, including PGP-HMS-derived minimal fakes,
   should cover every supported input form and the downstream capabilities that
   consume parsed AGI records. A parser fixture that only proves ingestion is
   not enough when PRS, ancestry, ClinVar, pharmacogenomics, variant lookup, or
   decode depend on the resulting record behavior.

31. Data-source libraries live in `genomi.runtime.libraries`.
   Shared public/reference assets, live APIs, derived panels, and per-key caches
   are `LibrarySpec` entries in `src/genomi/runtime/libraries/registry.py` and
   are materialized through `src/genomi/runtime/libraries/manager.py`.
   Capabilities must not add their own downloaders, URL catalogs, install roots,
   freshness checks, cache directories, or install-status shapes. Runtime code
   should use the library manager's `ensure`, `status`, or `missing_request`
   paths; install/update code should use `install` or `refresh`. Add a registry
   spec and transform when a new shared asset family is needed.

## Connect

Prefer MCP:

```json
{
  "mcpServers": {
    "genomi": {
      "command": "genomi",
      "args": ["serve"]
    }
  }
}
```

Call operations through MCP. Base operations are direct-callable; capability
operations go through `genomi.invoke` after reading the matching skill.

## Operating Rule

Only information discussed in the current chat is current context.
`SKILL.md`, `AGENTS.md`, and focused skill docs are static guidance. Live state
comes from Genomi operations and result envelopes.

- If the user asks a public genetics, variant, gene, phenotype, disease, screen,
  or pharmacogenomics question, answer from public/tool evidence.
- If the user provides a genome source file, use that as the current Active Genome Index
  context. Supplying the file path in this chat is approval to read that source
  for this session.
- If the user names a previous run, use that as the current Active Genome Index
  context only after explicit approval for this session.
- If the user says "my Active Genome Index", "my genome", or similar without a path, you may
  check whether Genomi already has an imported Active Genome Index context to use.
- Reading imported/parsed Active Genome Index artifacts, or searching for an existing
  "my Active Genome Index"/"my genome" context, requires explicit user approval for this
  session. After approval, record it with `active_genome_index.approve_access`.
- Do not use unrelated genome sources from other chats or previous tasks.

## Fresh Task Flow

1. Read `SKILL.md`.
2. Resolve context from this chat. If the user supplied a genome source, prepare or
   select the Active Genome Index before making sample-specific claims.
3. Identify the user's intent and the matching capability. MCP `tools/list`
   returns only the base set (`genomi.*` and `journal.*`) plus the
   `genomi.invoke` dispatcher; every other capability tool is reached by
   reading `skills/<capability>/SKILL.md` first, then calling
   `genomi.invoke` with the registered operation name, for example
   `genomi.invoke({tool: "variant.resolve", params: {"rsid": "rs429358"}})`.
   Do not use the capability ID as the tool name. Anthropic
   Claude Code Skills auto-loads each capability's skill via its YAML
   frontmatter (installed as `~/.claude/skills/genomi-<capability>/`).
4. Base tools (`genomi.*`, `journal.*`) are direct-callable from MCP without
   a skill read.
5. Call the smallest useful Genomi operation for the question.
6. Before calling a tool, only provide parameters supplied by the current user
   request, current Genomi context, a previous Genomi result, explicit user
   approval, or an explicit override. Omit unknown optional parameters.
7. Inspect `defaults_applied` in every result. These defaults are part of the
   reasoning chain; change them in a follow-up call when the user's intent or
   evidence context requires a different assumption.
8. Inspect the returned evidence. When the investigation spans multiple tools or
   produces a material finding, append a journal entry with evidence links.
9. Continue within the same category when the next question is local to that
   evidence. If the evidence shows another category is needed, discover that
   category's tools and repeat.
10. If an MCP tool returns `status="in_progress"`, the operation is still running
   in a background Genomi job. Call `genomi.check_background_job` with the
   returned `job_id`; do not retry with a smaller slice or raw file scan unless
   the user explicitly asks for that fallback.
11. If a tool returns `status="requires_library_install"`, the library is not
   installed and that evidence tool will not work yet. Explain how the named
   library helps the user's intent, ask whether they want it installed, and use
   the returned install command if they approve. Do not treat missing library
   evidence as negative evidence.
12. If a result contains `ask_user`, the presence of that object means the host
   agent should ask. Surface its `question`, and use its `install_command` only
   after approval.
13. Tool definitions expose `dependencyContract` when they need installed
   libraries, local source files, or external network/API sources. External
   source failures return `source_unavailable`; retry later, use another source,
   or state the answerability gap rather than treating it as negative evidence.
14. Mention Active Genome Index use only when it materially affects the result:
   for example, it supports or refutes a user-specific claim, changes a
   limitation, blocks an operation until approval, or explains a required next
   action. Do not add a routine source-status line.
15. Derive answer confidence dynamically from the returned evidence, source
   trust, coverage, conflicts, and missing evidence. Do not use a static
   default confidence or a user-selected confidence profile.
   Genomi result fields describe evidence support, coverage, overlap, and source
   state; they are not final answer-confidence labels.
16. Use `genomi.describe_context` when the user asks about personal context,
   their own genome/context, a genome source, a previous run, a selected user,
   or before making sample-specific claims. When you call it, inspect
   `active_response_profile.guidance`; the active profile id is persisted in
   the Genomi registry (set via `genomi.set_response_profile`) and falls back
   to the catalog default in `src/genomi/runtime/host_response_profiles.json`
   when none is set. Do not call it only to bootstrap a public-only question.

## Tool Discovery

- MCP `tools/list`: base tools list (`genomi.*` + `journal.*` +
  `genomi.invoke`).
- Capability tools are dispatched at runtime through `genomi.invoke` after
  reading the relevant `skills/<capability>/SKILL.md`. Anthropic Claude Code
  Skills loads each `~/.claude/skills/genomi-<capability>/SKILL.md` based on
  its YAML frontmatter `description`.

Operation namespaces are tool-name prefixes, not disclosure branches. Use
namespace filters only for debugging or audits.

Tool definitions include `useWhen`, `whyNecessary`, `notFor`,
`examplePrompts`, `parameterDefaults`, and dependency contracts. Read those
fields when choosing among similar tools, deciding which omitted defaults
matter, and checking whether a source is installed, local-file, or
network-backed.

## Semantic Retrieval Terms

Search-like operations accept optional `semantic_context` so the host can pass
alternate biomedical wording inferred from the user's wording. These are search
terms, not evidence. Genomi reports which terms hit trusted local or public
source records and which terms had no hit in the consulted scope.

Host rules:

- Always send the user's original wording as `raw_query`.
- Add `host_expansions` only when the current chat reasonably supports alternate
  biomedical wording. The host supplies these; Genomi does not rely on a
  hardcoded synonym list.
- Add `host_entities` for proposed entity spans when helpful, such as drug,
  gene, phenotype, trait_or_condition, variant, or rsid.
- Do not treat host expansions as facts.
- Do not include Active Genome Index-derived findings unless the user approved
  that access in this session.
- Trust Genomi's returned evidence, provenance, `term_matches`, and
  `term_misses` over the host's guess.

Examples:

```json
{
  "tool": "prs.search_scores",
  "params": {
    "query": "will I go bald",
    "semantic_context": {
      "raw_query": "will I go bald",
      "host_expansions": ["male pattern baldness", "androgenetic alopecia", "hair loss"],
      "host_entities": [
        {"text": "androgenetic alopecia", "type": "trait_or_condition"}
      ]
    }
  }
}
```

```json
{
  "tool": "phenotype.normalize_terms",
  "params": {
    "text": "seizures and a small head",
    "semantic_context": {
      "raw_query": "seizures and a small head",
      "host_expansions": ["epileptic seizure", "microcephaly"],
      "host_entities": [
        {"text": "seizures", "type": "phenotype"},
        {"text": "microcephaly", "type": "phenotype"}
      ]
    }
  }
}
```

```json
{
  "tool": "pharmacogenomics.review_medication",
  "params": {
    "drug": "blood thinner after stent",
    "semantic_context": {
      "raw_query": "blood thinner after stent",
      "host_expansions": ["clopidogrel", "Plavix", "CYP2C19 antiplatelet response"],
      "host_entities": [
        {"text": "clopidogrel", "type": "drug"},
        {"text": "CYP2C19", "type": "gene"}
      ]
    }
  }
}
```

Every result that uses semantic terms should be inspected for `term_matches`,
`term_misses`, `retrieval_streams`, and match diagnostics. Missing retrieval
hits are not negative medical evidence.

## Common Starts

Public variant or gene question:

- `variant.resolve` with `{"rsid":"rs429358"}`
- `research.build_target_packet` with `{"target_type":"topic","topic":"rs429358"}`

User provides a genome source:

- `genomi.describe_context`
- `genomi.parse_source` with `{"source":"<genome-file>"}`

If the same source already has a complete Active Genome Index, or the user
names a complete Active Genome Index in the current approved session,
use/select that existing Active Genome Index instead of parsing again. Only rerun
`genomi.parse_source` when no complete matching Active Genome Index exists or
the Active Genome Index readiness says it is incomplete. Do not add
`max_records` for normal user-facing inspection; capped parses are sampling or
debug tools and should not replace a complete Active Genome Index.

Long MCP parses may return `status="in_progress"` with a `job_id` after about
30 seconds. That means the original parse is still running in the background.
Poll it with:

- `genomi.check_background_job` with `{"job_id":"<job_id>"}`

Retrying the same operation and params while the job is active reuses that
background job rather than starting duplicate parsing.

User asks what Active Genome Index context is active:

- `genomi.describe_context`

GWAS-style candidate variant question:

- `gwas.compare_variant_associations` with `{"phenotype":"LDL cholesterol","variants":["rs7412","rs429358"]}`

Single-subject HPO or rare-disease phenotype plus candidate genes:

- `phenotype.compare_gene_hpo_evidence` with `{"hpo_ids":["HP:0001251","HP:0000752"],"genes":["PNKP","SPG7"]}`

Candidate genes under an explicit public source prior:

- `gwas.compare_gene_associations` with `{"phenotype":"LDL cholesterol","genes":["PCSK9","APOB"]}`
- `phenotype.compare_drug_target_evidence` with `{"drug_class":"beta agonist","genes":["ADRB2","IL13"]}`

If several source families may be valid, call the relevant source-specific tools
separately and keep their priors separate in the answer.

Screen or perturbation candidate-gene question:

- `functional_genomics.compare_gene_perturbation` with `{"context":"CRISPR dependency screen","genes":["EGFR","MYC"]}`
- `functional_genomics.import_perturbation_table` with `{"table":"screen.tsv","context":"CRISPR dependency screen","genes":["EGFR","MYC"]}`

Rare disease or hereditary cancer source review:

- `phenotype.plan_risk_investigation` with `{"question":"BRCA1 hereditary breast cancer risk","gene":"BRCA1","investigation_type":"cancer_risk"}`

Phenotype or rare disease candidate question:

- `phenotype.normalize_terms` with `{"text":"ataxia; microcephaly; HP:0001250"}`
- `phenotype.compare_gene_hpo_evidence` with `{"phenotypes":["ataxia","microcephaly"],"genes":["PNKP","SPG7"],"source_records":[...]}`

Drug-target candidate question:

- `phenotype.compare_drug_target_evidence` with `{"drug_class":"beta agonist","genes":["ADRB2","IL13"],"source_records":[...]}`

Analytical grounding records:

- `pathway.retrieve_members` with `{"pathway_id_or_name":"R-HSA-70635"}`
- `pathway.retrieve_members` with `{"pathway_id_or_name":"hsa00010"}`
- `cell_type.retrieve_markers` with `{"cell_type_id_or_name":"hepatocytes","source":"hpa"}`
- `region.retrieve_features` with `{"region":"1:1000-1250","assembly":"GRCh38","gencode_gtf":"gencode.gtf","encode_ccre_bed":"encode.ccre.bed"}`

Medication-response question:

- `pharmacogenomics.review_medication` with `{"drug":"clopidogrel","gene":"CYP2C19"}`

## Answering

Keep medical and pharmacogenomic language informational. Use Genomi tool output
as evidence, keep risk language qualitative unless a cited source supplies a
number, and recommend clinical confirmation for clinical decisions. Confidence
is an answer-time synthesis judgment; style preferences never override evidence
limits, privacy boundaries, or clinical-confirmation language.
