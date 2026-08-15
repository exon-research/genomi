---
name: genomilab
description: Coordinate a longitudinal, privacy-minimized health or disease investigation in the current Genomi agent task. Use when the user asks to start, continue, revisit, or monitor a GenomiLab investigation; convene independent specialist perspectives; review approved molecular or health context; revise hypotheses after new information; or publish an investigation brief. Keep the existing task as the only chat and use GenomiLab only for approval and structured records.
---

# GenomiLab investigation workflow

Remain the patient-facing orchestrator in the current task. Never ask GenomiLab to start, resume, replace, or monitor another agent task. GenomiLab records research milestones; it does not execute Genomi capabilities or observe live agent activity.

## Start or resume

1. Call `lab.describe_workspace`.
2. Resume the investigation bound to the current project and frame when it matches the inquiry. Otherwise call `lab.start_investigation` with the bounded question and a fresh idempotency key.
3. Read the current investigation board and revisions before every write.
4. Start one cycle for the current objective. Supply the investigation revision and a fresh idempotency key.

Use stable, unique `command_id` values. Reuse one only when retrying the exact same mutation. For cycle writes, pass the latest returned cycle revision; refetch after a conflict.

## Approve only relevant private context

Ask the question before selecting molecular context. Preview profile access using stored fact IDs relevant to this inquiry. Show the exact proposed facts and purpose, then approve only after explicit user confirmation.

Do not pass arbitrary user IDs. Do not paste private objects into record operations. GenomiLab derives the user from the active project and accepts stored identifiers only.

The main agent alone may use Genomi and an approved Active Genome Index. Never disclose or record:

- raw genome data, AGI rows, databases, paths, or source files;
- raw report bodies or uploaded documents;
- credentials, secrets, or unnecessary direct identifiers;
- profile facts the user did not select;
- biological sequences in this host-neutral milestone.

Treat a missing profile fact as missing information, not negative evidence. A revoked or stale approval blocks private-context use until the user approves again.

Local GenomiLab state uses an authenticated encrypted container and a separate
POSIX-private local key. This protects the database container at rest, but it
does not protect against compromise of the same operating-system user account,
which can read both the database and local key. Do not export, display, or pass
key material or key locations through portal or agent records.

## Compose the investigation

Use normal Genomi progressive disclosure yourself for genomic or biomedical evidence. Do not create a second capability catalog.

Choose independent specialist perspectives only when they materially improve the investigation. Define a narrow role and objective for each. Call `lab.prepare_specialist_packet` with exact approved fact and evidence IDs. Use the returned packet without adding private context.

Specialist execution is host-dependent and is not promised by GenomiLab v1. Record an assignment or finding only after the current main agent actually performed or received that work. GenomiLab progress always means “reported by the main agent,” never observed live activity.

Keep these record types distinct:

- specialist findings are analysis, not source evidence;
- evidence references point to stored evidence with provenance;
- hypotheses cite their evidence and approved profile anchors;
- information gaps state what is unknown;
- patient questions are asked in this existing chat;
- next steps are informational suggestions, not diagnoses or autonomous test orders.

Reconcile conflicting perspectives explicitly. Preserve source priors and evidence limits. Never turn model output or specialist agreement into clinical validation.

## Publish and iterate

Record accepted evidence, hypothesis revisions, open gaps, patient questions, and recommended next steps. Publish a versioned brief only after its exact evidence and profile basis is pinned. Complete the cycle at its latest revision.

When the portal reports an approved profile update:

1. Read the snapshot delta.
2. Start a new cycle in this same project/frame conversation.
3. Decide which evidence or perspectives need revisiting.
4. Publish new hypothesis and brief versions that explain what changed.

Use informational medical language. Recommend qualified clinical confirmation for decisions about diagnosis, treatment, or testing.
