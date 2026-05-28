# Agents Working With Genomi

After installation, use this file for session rules and common operations. Use
`INSTALL_FOR_AGENTS.md` only for setup.

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
  session. After approval, record it with `genomi.approve_agi_access`.
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
