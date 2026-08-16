---
name: lab
description: Coordinate a longitudinal, privacy-minimized health investigation in the current Genomi conversation. Use when fulfilling the user's underlying intent requires durable patient-specific synthesis across observations or data sources, competing explanations, evidence gathered or revised over time, bounded specialist research, or an investigation brief. Also use when continuing an existing Lab investigation. Infer this need semantically; do not depend on keywords, prompt templates, disease names, or the user naming Genomi Lab.
---

# Genomi Lab investigation workflow

Infer the user's underlying goal and the work needed to answer it. Activate Lab
when a useful response requires durable, patient-specific investigation across
turns rather than a one-shot lookup. Do not implement keyword, phrase,
prompt-template, or disease-specific trigger rules, and do not require the user
to request Lab by name. Keep a simple, self-contained factual question in the
smallest ordinary Genomi capability instead of creating an investigation
unnecessarily.

Remain the patient-facing Main Orchestrator in the current task. The Main
Orchestrator alone reads patient records, uses approved Active Genome Index
context, establishes and revises patient hypotheses, and writes `lab.*`
investigation state. Genomi Lab structures research milestones; it does not
choose scientific capabilities or run a second planner/executor.
Continue the same persistent Main Orchestrator conversation for every Lab UI
turn; do not create a fresh orchestration thread for each message.
Reach every operation named below through `genomi.invoke`; `lab.*` names are
dispatcher values, not separate direct MCP tools.

## Start or resume

1. Resume a named investigation with `lab.read_investigation` when it matches
   the inquiry. Otherwise call `lab.create_investigation` with the bounded
   question and a fresh idempotency key.
2. Extract health facts explicitly stated in the conversation and call
   `lab.update_health_profile`. Preserve `original_wording`; use
   `source_class=model_extracted` and `verification_state=unreviewed`. Do not
   infer unstated diagnoses, dates, negatives, measurements, or relationships.
3. Read the current investigation state with `lab.read_investigation` before
   every subsequent write.
4. Call `lab.create_cycle` for the current objective. Supply the investigation
   revision and a fresh idempotency key.

Use stable, unique `command_id` values. Reuse one only when retrying the exact
same mutation. For cycle writes, pass the latest returned revision; refetch
after a conflict.

## Keep private context with the Main Orchestrator

The web UI Main extracts health-profile facts from the user's natural-language
conversation and keeps the structured profile current; users do not need to
fill or approve a mechanical medical form. Record facts the user states or
uploads with `lab.update_health_profile`; use the current logical and revision
state when adding a conversational correction. Surface the resulting summary
so the user can correct it conversationally. Genomi Lab creates or refreshes the
investigation profile snapshot and consent binding atomically. The only mechanical context
selector is the Active Genome Index. Never pass its ID, snapshot ID, source
path, genomic scope, or derived facts to this operation; it binds the currently
selected, session-approved context internally.

An unavailable, incomplete, or legacy selected Active Genome Index does not
block saving health facts. Inspect the returned `agi_evidence_gap`, continue
with public evidence where useful, and resume or rebuild the index before using
sample-specific genome evidence. A later profile update binds the AGI only
after the operation sees its complete immutable snapshot identity.
The Main Orchestrator may call Genomi directly and capture the presented result
with `lab.capture_evidence_result`.

Never give a specialist:

- patient names, identifiers, original wording, exact clinical dates, record
  locators, profile fact IDs, raw reports, or complete medication histories;
- raw genome data, AGI rows, IDs, databases, paths, source files, or
  patient-linked genotypes and variant inventories;
- project files, the complete conversation, credentials, or Lab state.

If a task cannot be performed without patient-specific information, do it in
the Main Orchestrator and do not delegate it. A missing fact or unavailable
library is an information gap, not negative evidence.

Local Genomi Lab state is stored in a POSIX-private SQLite file. Do not export
or pass the local database path through portal or specialist records.

## Prepare bounded native specialists

Choose specialist roles dynamically. For each bounded public research
question, call `lab.prepare_specialist_brief` with:

- the current investigation and cycle IDs;
- a free-form `specialist_role`;
- one fixed `execution_policy`;
- a public `research_question` and public concept identifiers;
- abstract event relations without patient dates or linkage;
- public evidence record IDs;
- omit `source_fact_ids` to bind the private derivation directly to every fact
  in the investigation's current approved profile snapshot, or pass an exact
  returned subset only when the derivation intentionally uses fewer facts;
- purpose, command ID, and expected revision.

The returned outbound brief is the only payload supplied to a native
specialist. Do not add patient context to it. Genomi Lab records the internal
derivation separately and validates the outbound payload before release.
Call `lab.create_specialist_assignment` with that validated brief before
starting the native specialist, then record lifecycle changes separately.

Fixed policies are security profiles, not medical roles:

- `reasoning_only`: no connector, MCP, shell, filesystem, Genomi, or Lab;
- `public_literature`: Paperclip only;
- `protein_model_research`: ESM only, for public/reference sequences without
  patient linkage;
- `experiment_design`: Proto only, for public mechanistic questions and
  approved research artifacts.

Profiles do not inherit the portal project, workspace, environment, skills,
MCP inventory, AGI session, or Lab database. If effective isolation cannot be
verified, do not spawn the specialist. Specialists may report general evidence,
uncertainty, alternatives, and gaps; they may not request patient context.

## Record specialist work and provider evidence

After spawning a native specialist, record assignment transitions with
`lab.transition_specialist_assignment`:

```text
proposed → spawned → completed
                   ↘ failed
proposed/spawned → cancelled
```

Capture connector receipts through `lab.capture_provider_result`. Paperclip
receipts may become public source evidence. ESM and Proto results remain
nonclinical research artifacts. Arbitrary specialist prose is analysis and
cannot become canonical source evidence or directly create, strengthen,
reject, resolve, or publish a patient hypothesis.

## Publish and iterate

Only the Main Orchestrator creates immutable hypothesis versions. Preserve the
logical hypothesis identity across new profile and evidence snapshots, retain
competing explanations, and use only these statuses:

```text
open, strengthened, weakened, retained, rejected, resolved
```

Record supporting, contradicting, and contextual evidence plus unresolved
gaps and a revision rationale. Model output alone cannot change hypothesis
status. Classifications and uncertainty labels cannot be silently upgraded.

Record a durable unknown with `lab.create_information_gap`; revise the same
logical gap with `lab.revise_information_gap` when its wording or current
snapshot basis changes. A gap may be `open` or `resolved`; resolving it requires
a newer approved profile or evidence snapshot. Clinician brief `gap_ids` refer
only to current open information-gap threads or their latest versions, never to
hypotheses or arbitrary prose.

When the patient returns with new information, create a reviewed profile
snapshot and new evidence snapshot, revisit every current hypothesis, prepare
new de-identified specialist questions only where useful, and publish a new
brief version that explains what changed. Use informational medical language
and recommend qualified clinical confirmation for diagnosis, treatment, or
testing decisions.

## Tools

Every write takes a fresh `command_id`, and every write after the investigation
exists takes the `expected_revision` returned by the last read or write.

### lab.create_investigation

Create the investigation that owns every later cycle, profile revision,
hypothesis, gap, assignment, evidence record, and brief.

**Params**: `question`, `command_id`. Optional `disease_scope`, `public_only`.

**Use when**: The inquiry is new and `lab.read_investigation` shows no
investigation that already covers it.

### lab.read_investigation

Read current cycles, hypothesis versions, information gaps, evidence
snapshots, specialist assignments, disclosure summaries, and published briefs.

**Params**: `investigation_id`. Optional `include_history`.

**Use when**: Resuming an investigation, and before every write, to get the
current revision.

### lab.update_health_profile

Persist Main-Orchestrator-extracted health facts and refresh the approved
profile snapshot and consent binding.

**Params**: `investigation_id`, `facts`, `purpose`, `command_id`,
`expected_revision`. Each fact needs `modality`, `label`, `original_wording`,
`source_class`, `verification_state`.

**Use when**: The user states or uploads health facts, or corrects earlier
ones. Never pass Active Genome Index identity; the operation binds the selected
approved context itself.

### lab.create_cycle

Create the next immutable investigation cycle for the current objective.

**Params**: `investigation_id`, `purpose`, `public_only`, `command_id`,
`expected_revision`. Optional `profile_snapshot_id`, `prior_cycle_id`.

**Use when**: Starting a new round of hypothesis, evidence, and specialist
work.

### lab.create_hypothesis

Create the first immutable version of a logical hypothesis with its cited
evidence and unresolved gaps.

**Params**: `investigation_id`, `cycle_id`, `statement`, `status` (`open`),
`supporting_evidence_record_ids`, `contradicting_evidence_record_ids`,
`contextual_evidence_record_ids`, `unresolved_gaps`, `revision_rationale`,
`command_id`, `expected_revision`.

**Use when**: A competing explanation first enters the investigation.

### lab.revise_hypothesis

Append a new immutable version to an existing logical hypothesis.

**Params**: the `lab.create_hypothesis` fields plus `logical_hypothesis_id`,
with `status` in `open`, `strengthened`, `weakened`, `retained`, `rejected`,
`resolved`.

**Use when**: New evidence or a new profile snapshot changes the hypothesis
statement, status, or cited evidence. Never edit a prior version.

### lab.create_information_gap

Create the first immutable version of a durable unknown.

**Params**: `investigation_id`, `cycle_id`, `statement`, `status` (`open`),
`revision_rationale`, `command_id`, `expected_revision`.

**Use when**: A missing fact, missing measurement, or uninstalled library
blocks a conclusion. Do not record it as negative evidence.

### lab.revise_information_gap

Append a new immutable version to an existing logical information gap.

**Params**: the `lab.create_information_gap` fields plus
`logical_information_gap_id`, with `status` `open` or `resolved`.

**Use when**: The gap's wording changes, or a newer approved profile or
evidence snapshot resolves it.

### lab.prepare_specialist_brief

Validate a de-identified public research brief, keep the private derivation
internal, and return only the outbound specialist payload.

**Params**: `investigation_id`, `cycle_id`, `specialist_role`,
`execution_policy`, `research_question`, `public_concepts`,
`abstract_event_relations`, `public_evidence_record_ids`, `purpose`,
`command_id`, `expected_revision`. Optional `source_fact_ids`.

**Use when**: A bounded public research question can be answered without any
patient-specific information.

### lab.create_specialist_assignment

Create the proposed assignment that a native specialist will run.

**Params**: `investigation_id`, `cycle_id`, `specialist_brief_id`,
`command_id`, `expected_revision`.

**Use when**: After the brief validates and before the specialist is spawned.

### lab.transition_specialist_assignment

Apply one legal assignment state transition; completing an assignment records
its general finding and closes it atomically.

**Params**: `investigation_id`, `assignment_id`, `to_state` (`spawned`,
`completed`, `failed`, `cancelled`), `command_id`, `expected_revision`.
Optional `native_agent_id`, `general_finding`, `failure`.

**Use when**: The specialist is spawned, finishes, fails, or is cancelled.

### lab.capture_evidence_result

Capture a durable, tamper-checked Genomi result receipt as investigation
evidence.

**Params**: `investigation_id`, `cycle_id`, `result_receipt_id`, `purpose`,
`command_id`, `expected_revision`.

**Use when**: The Main Orchestrator called a Genomi capability directly and its
presented result should become citable evidence. Caller-supplied replacement
evidence is rejected.

### lab.capture_provider_result

Redeem a policy-authorized provider receipt and bind it to the completed
specialist assignment.

**Params**: `investigation_id`, `cycle_id`, `assignment_id`,
`specialist_brief_id`, `result_receipt_id`, `purpose`, `command_id`,
`expected_revision`.

**Use when**: A Paperclip, ESM, or Proto receipt returns with a completed
assignment. Paperclip receipts may become public source evidence; ESM and Proto
receipts stay nonclinical research artifacts.

### lab.publish_brief

Publish an immutable clinician-brief version from current investigation state.

**Params**: `investigation_id`, `cycle_id`, `brief`, `command_id`,
`expected_revision`. Every `brief.claims` entry cites `evidence_record_ids` or
`profile_revision_ids`.

**Use when**: The cycle has enough cited evidence to hand the user something a
clinician can review.
