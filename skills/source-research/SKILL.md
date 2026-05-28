---
name: journal-source-research
version: 1.0.0
description: |
  Journal sub-skill for focused public/source evidence review and reviewed
  finding write-back before interpretation or answer synthesis.
tools:
  - research.list_sources
  - research.build_target_packet
  - gnomad.fetch_population_frequency
  - phenotype.plan_risk_investigation
  - pharmacogenomics.fetch_pgxdb
  - research.record
  - research.query
  - research.search
mutating: true
---

# Journal Source Research

Use this Journal sub-skill when a claim needs source context beyond local static
rows: current ClinVar assertion, gene mechanism, inheritance, penetrance,
guideline evidence, population tension, or literature/source conflict.

## Goal

Review focused public targets and write reviewed findings back into the local
evidence DB before using them in final interpretation. In capability discovery,
these tools are part of `journal` because they create reusable investigation
memory rather than a separate evidence category.

Works with Active Genome Index context and public-only context. If Active Genome
Index context exists, use its evidence DB for user-specific context. With
public-only context, use the shared evidence DB and frame the answer as
public-target source review.

> **Convention:** See `skills/conventions/evidence-quality.md`.
> **Convention:** See `skills/_output-rules.md`.

## Contract

Contract:

- External research uses selected public targets only.
- API-backed sources are marked in tool `dependencyContract.externalNetwork`;
  local source files are marked in `dependencyContract.localResources`. If an
  API source is unavailable, the tool returns `source_unavailable`.
- Reviewed source findings are written back before final interpretation.
- Shared evidence is reusable public-target knowledge.
- Private evidence is reserved for user-specific combinations and context.
- Public-only answers describe public-target evidence.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### gnomad.fetch_population_frequency

Fetch reusable gnomAD public population frequency for one allele and write it into evidence storage.

**Use when**: gnomAD population frequency would change interpretation of an exact public allele or candidate variant.

**Why necessary**: gnomAD allele frequency changes interpretation; common and rare variants should not be discussed the same way.

**Result semantics**: Writes reusable aggregate public gnomAD frequency rows using selected public allele data.

### research.build_target_packet

Build a target-centric evidence packet after the agent identifies the user's target.

**Use when**: The agent has selected a gene, drug, condition, topic, or allele and needs local/source context for synthesis.

**Why necessary**: A target packet keeps gene, drug, condition, topic, and allele context grouped before synthesis.

**Result semantics**: Returns context and source candidates for agent synthesis.

### research.list_sources

List source catalogs relevant to a target type or one source ID.

**Use when**: choosing public source families for a target type or inspecting one source contract.

**Why necessary**: Source choice is part of the evidence contract; agents need to know which public adapters fit a target.

**Result semantics**: Returns source adapter and focused-review contracts for the host agent's selected public target.

### research.query

Retrieve reviewed research for an exact target from local evidence storage.

**Use when**: the agent needs stored reviewed research for one exact target.

**Why necessary**: Exact-target research retrieval prevents agents from relying on vague memory of prior reviews.

### research.record

Store reviewed source findings or tool-returned record_research_payloads in evidence storage with explicit shared/private scope.

**Use when**: Use after the agent has a reviewed source finding or tool-returned research payload that should be stored with scope.

**Why necessary**: Reviewed findings need durable, scoped storage so later answers can reuse source-backed evidence.

**Result semantics**: Writes reviewed public-target or private user-specific findings according to scope; private scope requires an active/private evidence DB.

### research.search

Token-search reviewed research findings stored in local evidence storage.

**Use when**: the agent needs token search across stored reviewed findings and does not have exact target fields.

**Why necessary**: Token search recovers stored findings when exact target fields are unknown.

## Privacy Boundary

External research may use selected public targets: gene, rsID, normalized
allele, drug, condition, topic, or guideline question. Intake files, broad
candidate inventories, and private phenotype/medication/family context stay
local unless the user explicitly chooses broader sharing.

## Record Before Use

For source-backed interpretation, store a reviewed finding JSON file or an
inline payload returned by a Genomi source tool:

- `research.record` with `{"db":"$GENOMI_HOME/sample/evidence/evidence.sqlite","input":"finding.json","scope":"shared"}`
- `research.record` with `{"payload":{"target":{"type":"drug","drug":"clopidogrel"},"source":{"title":"CPIC","url":"https://cpicpgx.org/guidelines/"},"finding":{"type":"pgx_guideline","text":"short reviewed finding"}},"scope":"shared"}`

With public-only context, `db` can be omitted and Genomi will use the shared
evidence DB.

Use `shared` for reusable public-target knowledge. Use `private` for
user-specific combinations, phenotype, medications, family history, or personal
interpretation. Private scope uses the selected Active Genome Index evidence DB
or an explicit private `db`.

## Source Selection

Use `research.list_sources` before focused review when the source choice is uncertain.
Each source returns:

- `query_mode`: implemented operation or focused source review.
- `public_target_inputs`: the fields safe to use for external review.
- `available_operations`: Genomi tools that support the source.
- `reviewed_finding_shape`: fields to store with `research.record`.

For GeneCards- or MalaCards-style context, use `phenotype.plan_risk_investigation` to keep gene
function, disease association, and clinical-validity cross-checks separated.

For implemented sources, call the listed adapter first. For focused-review
sources, review the official source or primary literature for the selected
public target, extract the narrow finding needed for the user's question, and
write it back as reviewed evidence.

## Operating Checks

- Send selected public targets to external research.
- Use cited source findings as final evidence.
- Store reusable public-target knowledge as shared evidence.
- Store user-specific interpretation as private evidence.
- Write reviewed findings back before using a source in an answer.
