# Genomi Design Principles

Edit this file only with explicit owner approval.

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
