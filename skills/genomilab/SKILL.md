---
name: genomilab
description: Run or continue patient-authorized, genome-informed GenomiLab investigations in the current Claude, Codex, or other MCP agent task. Use when a patient asks to open the Research Desk, investigate a condition against their active genome, review an existing investigation, supply follow-up information, revise a hypothesis, or publish a revised investigation response.
---

# GenomiLab Research Desk

Keep the current host agent in control of the conversation, native specialist
subagents, planning, streaming, follow-ups, and cancellation. Use GenomiLab for
typed capabilities, patient authorization, Active Genome Index access, durable
evidence and hypothesis state, validated briefs, and the patient portal.

The portal is for patient onboarding, exact approvals, integration setup, and
monitoring committed investigation milestones. Never start a second agent task
from the portal.

## Start or resume

1. Call `genomilab.open_workspace`.
2. If it returns `status="setup_required"`, keep setup in core Genomi. Select
   or finish the current user's Active Genome Index. If none exists, ask the
   user for the local VCF or another supported genome-source path and use core
   Genomi intake; pointing the host at that path is the only genome handoff.
   Do not open an investigation without a query-ready selected index.
3. Show the returned portal link when the patient needs onboarding or approval.
4. Call `genomilab.create_investigation` for a new question, or
   `genomilab.inspect_investigation` for an existing investigation.
5. If no profile observation exists, ask for one concise patient-reported fact
   before preparing authorization. Do not fabricate a symptom, diagnosis,
   phenotype, family history, or molecular finding.

Do not ask for a VCF path in GenomiLab. Genome intake remains in core Genomi;
GenomiLab uses the selected Active Genome Index.

## Chair the specialist board

For every new investigation, act as chair and form 2–5 native host subagents
with adaptive, non-overlapping domain roles. Give each specialist an explicit
role and bounded task chosen for the question; do not use a fixed board when a
different evidence mix is more relevant. Use stable logical `specialist_id`
values, not native task or thread identifiers. Record the board once with
`genomilab.form_specialist_board` before submitting a plan. These are persistent
specialist identities: reuse the same IDs in every investigation round, while
giving each specialist a new bounded assignment for that round.

On resume, inspect the investigation first. Treat its pre-authorization
`specialist_board` as a structural redacted marker only: board existence plus
`status` and `member_count`; a static chair description may also appear. If
that marker says a board exists, do not call
`genomilab.form_specialist_board` again. Renew current-session authorization
through the flow below. After `private_context_status` is
`approved_for_session`, inspect again; only then read and reuse the full
specialist IDs, roles, tasks, and current-work states, and reconstitute the
corresponding native subagents if the host requires it.

The chair alone owns the patient conversation, authorization, all private AGI
reads, and canonical plan, hypothesis, gap, and brief commits. Give specialists
public questions or only the minimum approved evidence needed for their task.
Specialists return their analysis to the chair; they never read the AGI
directly, interact with the portal, request patient approval, or commit the
canonical investigation artifacts.

Call `genomilab.report_specialist_progress` with the current `round_id` only at
meaningful work milestones, using `working`, `blocked`, or `completed` and a
short `current_work` label.
GenomiLab derives the initial `assigned` state. Do not send raw agent messages,
chain of thought, token streams, native task IDs, or per-call chatter. The
portal monitors only these committed board milestones.

When a specialist returns, use `genomilab.record_specialist_report` to commit
that round's findings and gaps with exact evidence and profile anchors. A
specialist report is traceable synthesis, not a new evidence record or a
clinical conclusion. Commit all assigned reports before starting another round.

## One investigation authorization

Call `genomilab.prepare_authorization` after the patient profile contains the
facts needed for the question. The portal presents the exact selected profile
slice, current genome scope, and current underlying-agent destination.
Give the patient the portal launch link returned by that call: its one-time
token targets the exact signed candidate, while the candidate itself remains
redacted from the agent-facing result and URL. Do not prepare another candidate
merely to display the review.
For an existing investigation in a new agent session, omit
`observation_revision_ids` to renew the pinned profile, AGI, scope, and purpose
without silently expanding to newer profile facts. Use
`genomilab.record_patient_observations` for an intentional context update.
Each local stdio MCP `initialize` handshake is a new GenomiLab agent session.
It closes the prior session's private authority even if the host reports the
same client name and version, so do not reinitialize the stdio MCP connection
mid-investigation. HTTP MCP initialization is public-tools-only and cannot
create or replace the private GenomiLab runtime.

The agent must not approve this candidate. Ask the patient to review it in the
portal, then poll with `genomilab.inspect_investigation`. Continue when
`private_context_status` is `approved_for_session`.

Do not request another approval for routine local planning, evidence work,
hypothesis updates, or brief publication. A new patient approval is appropriate
only when the profile or genome snapshot/scope changes. Exact external-provider
egress can require a separate just-in-time portal approval.

## Plan and execute

Read `capability_catalog` from `genomilab.inspect_investigation`. Submit only
requests that are currently advertised as available:

```json
{
  "investigation_id": "investigation-...",
  "focus_question": "What does the approved profile establish?",
  "specialist_assignments": [
    {
      "specialist_id": "specialist-timeline",
      "task": "Reconstruct the approved clinical timeline"
    },
    {
      "specialist_id": "specialist-evidence",
      "task": "Review relevant public evidence"
    }
  ],
  "requests": [
    {
      "id": "profile-review",
      "capability": "investigation.project_profile",
      "parameters": {}
    }
  ]
}
```

`genomilab.submit_plan` validates and accepts the exact requests under the
active investigation authorization and requires the specialist board to exist.
Each accepted plan version is one immutable investigation round. Supply one
focus question and exactly one assignment for every persistent specialist.
The chair submits the canonical plan. Do not invent capability parameters or
resend modified parameters to execution. Call `genomilab.execute_request` with
only the investigation and request IDs.

When the approved genomic scope advertises
`genomi.variant.find_gene_variants`, the phenotype specialist may return a
bounded candidate set to the chair, but the chair alone submits and executes
the request. Use 1–10 canonical gene symbols, the exact AGI/build fields shown
by the catalog, and `candidate_set_lineage` naming that persistent specialist
plus the exact current profile/evidence anchors used. GenomiLab fingerprints
the actual set and lineage in the committed personal-genome evidence. Do not
give the specialist the AGI result or direct genome access.

When a request returns:

- `completed`: inspect the new investigation state and continue.
- `in_progress`: call `genomilab.check_request` with the same request ID.
- `approval_required`: show the portal link and ask the patient to approve the
  exact external disclosure there. Do not add an `approved` argument yourself.
- `source_unavailable` or an unavailable capability: state the evidence gap;
  do not treat it as negative biomedical evidence.

Re-inspect after evidence commits. The capability catalog may then advertise
new exact disease-relation, hypothesis, or gap templates. Submit a new bounded
plan when later synthesis depends on those newly available records.

## Publish the investigation response

Use the hypothesis and gap capabilities advertised by the investigation
catalog. Preserve source priors and cite the exact profile and evidence anchors.
Use `supersedes_hypothesis_id` when revising an existing hypothesis.

Read `brief_authoring.brief_schema` from the latest authorized
`genomilab.inspect_investigation` result. Build the `brief` argument from that
exact context-bound schema and the published investigation records. Omit
`modality_badges`; GenomiLab derives them from the cited records. Then call
`genomilab.submit_brief`. Treat the returned `investigation_response` as the
durable research record; answer the patient conversationally in the current
host task. Keep all health language informational and preserve the required
clinical boundary. Build `timeline` from exact evidence/profile anchors and
write case-specific `clinician_questions` with their motivating evidence,
profile, hypothesis, and gap identifiers; do not substitute generic canned
questions. The portal can print the current brief or download a self-contained
HTML copy for the patient to take to a treating professional.

## Patient follow-up and revision

When the patient supplies additional information in the current conversation:

1. Call `genomilab.record_patient_observations` with the same investigation ID.
   Each observation needs at least `modality` and `label` or
   `original_wording`. Use patient wording and patient-reported provenance.
2. For a correction, include `supersedes_observation_revision_id` on that one
   observation. Otherwise record a new observation.
3. Ask the patient to approve the returned context delta in the portal once.
4. Re-inspect after approval. Replan and rerun only evidence affected by the
   changed context.
5. Register a revised hypothesis with `supersedes_hypothesis_id`, then publish
   brief version 2. Explain what changed and what did not.

Keep the same host task and investigation ID throughout this flow.

## Research tools

Call `genomilab.list_research_tools` when provider availability matters.

- Paperclip supports approved investigation-scoped literature search/lookup,
  regulatory search, and trial-registry search when the returned capability
  catalog advertises the exact route. It does not provide full-text extraction
  or claim verification. A saved or verified credential is not a live route;
  without owner deployment authorization, an independent patient-data
  contract, and their configuration, state the route is unavailable. Every
  actual request also requires patient approval of its exact disclosure.
- Biohub and Modal connection checks are setup checks only. Never describe one
  as an ESM or Proto scientific run.
- Use `genomilab.verify_sequence_substitution` first to bind an intended
  substitution to a public reference protein. Genomi stores only sequence
  digests and normalized descriptors in the round-bound research ledger.
- Use `genomilab.run_esm_substitution_analysis` only when
  `scientific_operations` advertises it as available. It invokes the configured
  local, network-disabled scientific executor; otherwise it returns an explicit
  unavailable state and creates no artifact.
- Use `genomilab.run_proto_blinded_experiment_design` under the same rule for a
  bounded blinded experimental design. It is not a general sequence-design
  surface.
- ESM, Proto, Genomi verification, and unverified host submissions are
  nonclinical research artifacts. They cannot support hypotheses, evidence,
  answer-readiness, brief claims, treatment content, or clinician export.

Provider credentials and connect/disconnect actions stay in the patient portal
and must never appear in agent tool arguments or responses.

## Revocation and cancellation

Use `genomilab.revoke_context` when the patient revokes private investigation
access. This blocks future GenomiLab profile and genome operations. Cancel or
stop the native task with the underlying host's own task controls; do not claim
that portal revocation cancelled the host task.

## Operation reference

### genomilab.open_workspace

Check the current user and query-ready AGI, bind the current MCP host, and
return the loopback portal link when requested.

### genomilab.create_investigation

Create the durable investigation record for the patient's question. This does
not create or start another agent task.

### genomilab.form_specialist_board

Record the 2–5 persistent logical specialist IDs, explicit roles, and bounded
initial tasks for the
native board formed by the chair. Call once for a new investigation; reuse the
recorded board on resume.

### genomilab.report_specialist_progress

Commit a specialist's meaningful `working`, `blocked`, or `completed` milestone
for the current `round_id`, with a short current-work label for portal
monitoring. Completion is terminal within that round but the same persistent
specialist can receive a new assignment in the next round. This is not
agent-message, reasoning, token, or native-task streaming.

### genomilab.record_specialist_report

Commit one immutable findings-and-gaps report for a specialist assigned to the
current round. Findings cite exact current-round evidence or profile records;
gaps may identify still-missing evidence. This report is synthesis only and
cannot substitute for an evidence record.

### genomilab.inspect_investigation

Read current context, plan, evidence, hypotheses, briefs, domain events,
capability catalog, context-bound brief authoring schema, and next actions.
Before current-session authorization, an existing board is only a structural
redacted marker; inspect again after authorization to read its full assignments.

### genomilab.prepare_authorization

Prepare the exact context candidate for patient review in the portal. Omit
`observation_revision_ids` for a new-session renewal of an already pinned
investigation. For an initial authorization, omit it only when every current
profile fact is relevant.

### genomilab.record_patient_observations

Record patient-provided facts for either initial onboarding or a later turn,
then prepare the required initial or delta context authorization.

### genomilab.submit_plan

Submit the round focus, one assignment for every persistent specialist, and the
advertised capability names with their exact catalog parameters as immutable
request IDs. The accepted plan version and investigation round are the same
unit of work.

### genomilab.execute_request

Execute one accepted request ID. Never alter or resend its parameters here.

### genomilab.check_request

Poll the same accepted request ID only after it returns `in_progress`.

### genomilab.submit_brief

Commit the exact `brief` advertised by the latest authorized inspection. Claims
cite current evidence, profile, hypothesis, and gap identifiers; GenomiLab
derives modality badges and preserves the clinical boundary.

### genomilab.submit_research_artifact

Persist a round-bound unverified host artifact with its
exact method, model, versions, input/output digests, and provenance. This route
never verifies scientific or provider execution.

### genomilab.verify_sequence_substitution

Verify an intended protein substitution against a supplied public reference
protein sequence using deterministic local Genomi rules. The sequence is
transient; the ledger stores only hashes and normalized descriptors.

### genomilab.run_esm_substitution_analysis

Run the same-round verified substitution through the configured bounded local
ESM executor. Treat `status="unavailable"` as no execution and no result.

### genomilab.run_proto_blinded_experiment_design

Run a bounded same-round blinded-design request through the configured local
Proto executor. Treat `status="unavailable"` as no execution and no result.

### genomilab.list_research_artifacts

Read the investigation's current round-bound nonclinical research artifacts,
including their method, model, version, input/output, provenance, and fixed use
boundaries. These records are not evidence, hypothesis support, brief claims,
answer-readiness inputs, or clinician-export content.

### genomilab.list_research_tools

Inspect provider connection state and scientific-operation availability as
separate facts. Connection readiness never proves scientific execution.

### genomilab.revoke_context

Revoke future GenomiLab access to the investigation's private context. Use the
host's own controls separately if the native task must stop.
