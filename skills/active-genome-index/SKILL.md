---
name: active-genome-index
version: 1.0.0
description: |
  Register, parse, and digitize private genome source files into a local Active Genome Index and
  supporting evidence stores. Use when the session explicitly supplies a VCF/gVCF, BAM, 23andMe raw
  genotype export, AncestryDNA raw genotype export, MyHeritage raw genotype export, FamilyTreeDNA
  Family Finder export, Living DNA autosomal export, supported source zip, or known Active Genome Index.
tools:
  - genomi.describe_context
  - genomi.approve_agi_access
  - genomi.list_users
  - genomi.select_user
  - genomi.assign_user_genome
  - genomi.parse_source
  - genomi.rename_user
  - genomi.set_default_user
  - genomi.clear_default_user
  - active_genome_index.summarize
  - active_genome_index.classify_callset_qc
  - active_genome_index.classify_genotype_support
  - active_genome_index.classify_region_callability
  - genomi.clear_selection
  - genomi.revoke_agi_access
mutating: true
---

# Active Genome Index

Use this skill when the user provides a genome result file, asks to parse a genome
source, asks what local Active Genome Index context exists, or asks a sample-specific question
that requires a user file.

## Goal

Create or refresh the private Active Genome Index and local evidence stores. Interpret health meaning
only after the relevant evidence skill gathers support for the user's claim.

> **Convention:** See `skills/conventions/context-routing.md`.
> **Convention:** See `skills/_output-rules.md`.

## Contract

Contract:

- A supplied source file, an approved `agi_id`, or a default user's selected Active Genome Index is accessible before sample-specific work.
- `GENOMI_HOME` stores durable Active Genome Index records.
- Every genome source parsed by Genomi becomes an Active Genome Index record.
- User/profile nicknames belong to users, not genome artifacts.
- A user can have multiple genome records and one selected Active Genome Index.
- A default user is auto-selected for every session using this `GENOMI_HOME`, and readable access is scoped only to that user's selected Active Genome Index.
- `genomi.parse_source` digitizes the intake file so future inquiries use the Active Genome Index.
- The original intake path is hidden from normal agent-facing context after parsing.
- Parsing success creates a source-appropriate Active Genome Index for later interpretation.

## Supported Sources

- VCF/gVCF: variant callsets with VCF records, genotype fields, optional depth/quality, and possible region callability.
- BAM: aligned sequencing reads. Genomi derives a local VCF from the reads with a matching reference FASTA, then builds an Active Genome Index for the derived callset for normal sample-specific tools.
- FASTQ (paired-end): raw reads from sequencing services such as Nebula, Dante Labs, and Sequencing.com. Genomi auto-detects the R2 sibling, picks minimap2 (long reads) or bwa-mem2 (short reads) by the median sniffed read length, sorts the aligned BAM with samtools, then hands the BAM off to the standard BAM → derived-VCF path. Requires the `wgs-alignment` install purpose (or aligner binaries on PATH); a missing aligner returns `requires_library_install` instead of failing.
- 23andMe raw genotype text or zip: consumer SNP-array calls with `rsid`, chromosome, position, and plus-strand genotype on GRCh37.
- AncestryDNA raw genotype text or zip: consumer SNP-array calls with `rsid`, chromosome, position, `allele1`, and `allele2` on GRCh37/build 37.1.
- MyHeritage raw genotype CSV or zip: comma-delimited `RSID,CHROMOSOME,POSITION,RESULT` exports prefixed with a `# MyHeritage DNA raw data` banner, GRCh37.
- FamilyTreeDNA Family Finder autosomal CSV or `.csv.gz`: same `RSID,CHROMOSOME,POSITION,RESULT` columns as MyHeritage but with no banner, build encoded in the filename (`_o37_`), GRCh37.
- Living DNA autosomal text: tab-separated `rsid/chromosome/position/genotype` rows with a `# Living DNA customer genotype data` banner on GRCh37.

VCF deliverables from named consumer sequencing services (Nebula Genomics, Dante Labs, Sequencing.com) are accepted through the generic VCF path; the source provider is detected from header signatures and surfaced as `provider` on the parse result.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### active_genome_index.classify_callset_qc

Classify genome callset shape, depth/quality field availability, and absence-claim boundaries using an Active Genome Index.

**Use when**: Use before broad Active Genome Index claims when the agent needs callset shape, QC fields, and absence-claim boundaries.

**Why necessary**: Broad Active Genome Index claims depend on whether the artifact actually contains the fields and coverage needed to support them.

### active_genome_index.summarize

Summarize local parse/readiness/evidence state for an Active Genome Index.

**Use when**: The agent needs a compact status check for an Active Genome Index before deciding whether parsing, library-scoped evidence materialization, or evidence refresh is needed.

**Why necessary**: Agents need Active Genome Index readiness and artifact status before deciding whether to reuse, resume, materialize, or answer.

**Example prompts**: What Active Genome Index context is active?

**Result semantics**: Summarizes local Active Genome Index and evidence artifact state; it does not parse new input or perform interpretation.

### genomi.assign_user_genome

Assign an existing or supplied genome source to a user/profile and optionally make it that user's selected Active Genome Index.

**Use when**: A genome source or existing genomi agi should belong to a named user/profile.

**Why necessary**: One user can own multiple genome artifacts while selecting exactly one Active Genome Index as active for that profile.

**Not for**: Parsing a source into a complete Active Genome Index; use genomi.parse_source when digitization is needed.

**Example prompts**: Assign this VCF to Alice.

**Result semantics**: Links user metadata to genomi agi metadata. Supplying a source path grants scoped session access to that source's resolved Active Genome Index.

### genomi.clear_default_user

Clear persistent default user/profile selection for this GENOMI_HOME.

**Use when**: The user no longer wants any user/profile auto-selected by default.

**Why necessary**: Users need an explicit way to remove persistent default Active Genome Index context without deleting users or Active Genome Index artifacts.

**Example prompts**: Stop auto-selecting the default user.

**Result semantics**: Clears default=true from all known users; session selections and artifacts remain.

### genomi.list_users

List user/profile metadata and the Active Genome Index records assigned to each user.

**Use when**: The user asks which people or profiles are configured, or which genomes are assigned to a user.

**Why necessary**: User nicknames belong to people/profiles, not genome artifacts, so agents need a metadata-only user registry view.

**Example prompts**: Which users have genomes imported?

**Result semantics**: Returns user and genomi agi metadata only; it does not approve reading genome artifacts.

### genomi.parse_source

Detect, parse, and digitize a genome source such as VCF/gVCF, BAM, or a consumer-array raw genotype export from 23andMe, AncestryDNA, MyHeritage, FamilyTreeDNA (Family Finder), or Living DNA (text, zip, or `.csv.gz`).

**Use when**: The user explicitly supplied a genome source and downstream questions need a queryable Active Genome Index in this session.

**Why necessary**: Raw VCF, BAM, and consumer genotype files are too large and irregular for reliable direct reasoning; parsing creates the scoped Active Genome Index used by later tools.

**Not for**: Public-only genetics questions, already parsed Active Genome Index selection, or capped sample scans that should not replace a complete Active Genome Index.

**Example prompts**: Parse this VCF for this session.

**Result semantics**: Digitizes local intake into an Active Genome Index for future tools. Genomi auto-detects the source type. Supplying user_nickname links the parsed artifact to a user profile. It does not run whole-callset static annotation; focused tools lazily materialize public libraries only when their evidence is needed.

### genomi.rename_user

Rename a user/profile nickname.

**Use when**: The user wants to rename a person/profile.

**Why necessary**: Human-friendly names belong to users, while Active Genome Index IDs remain stable hash-based artifact identifiers.

**Example prompts**: Rename this user to Alice.

**Result semantics**: Updates one user nickname. Active Genome Index artifact IDs are unchanged.

### genomi.select_user

Select a user/profile for this session without granting private artifact access.

**Use when**: The user names a person/profile and the agent needs to make that user's selected Active Genome Index the session metadata context.

**Why necessary**: Selecting another user should be metadata-only until genomi.approve_agi_access grants access to that user's selected Active Genome Index.

**Example prompts**: Use Alice's genome context.

**Result semantics**: Sets the selected user and selected Active Genome Index metadata; private reads still require scoped access approval unless this is the default user.

### genomi.set_default_user

Set the default user/profile for this GENOMI_HOME.

**Use when**: The user wants one profile's selected Active Genome Index available by default in every session.

**Why necessary**: Default access is scoped to a user's selected Active Genome Index rather than all genomes or all users.

**Example prompts**: Make Alice the default user.

**Result semantics**: Sets exactly one default user. Persistent private read access applies only to that user's active_agi_id.

## Selection Notes

- Use `genomi.describe_context` to inspect selected session context.
- If the user supplied a source file and the answer needs sample evidence, first
  inspect whether the same source or a known complete Active Genome Index is
  already selected. Use the existing complete Active Genome Index when available; call
  `genomi.parse_source --params '{"source":"<path>"}'` only when no complete
  matching Active Genome Index exists or Genomi reports the Active Genome Index is incomplete.
- If `genomi.parse_source` returns `status="in_progress"` with a
  `job_id`, keep polling `genomi.check_background_job` for that job. Do not
  switch to a capped parse or raw text scan as a substitute for the full active
  Active Genome Index unless the user explicitly asks for a temporary fallback.
- Do not add `max_records` for user-facing inspection when a complete Active Genome Index may
  already exist. A capped parse is only an explicit sampling/debug choice, not
  the normal path for "anything notable?".
- If a focused evidence tool returns
  `status="requires_library_install"`, explain what the named library enables
  for the user's intent and ask whether they want it installed. Do not treat
  missing library data as negative evidence.
- If the user supplied a known `agi_id`, call
  `genomi.approve_agi_access --params '{"approved_by_user":true,"agi_id":"..."}'`
  only after explicit approval for this session.
- If the user supplied a user nickname, call `genomi.select_user` for metadata
  selection, then call `genomi.approve_agi_access` if sample evidence is needed
  and the selected user is not the default user.
- For interpretation work, read the matching `skills/<capability>/SKILL.md` and call its capability tools through `genomi.invoke`.

## Boundaries

- Raw genome source files stay local.
- Durable Active Genome Index records in `GENOMI_HOME` become readable only when the session
  explicitly approves the resolved `agi_id`, supplies a source path, or uses the
  default user's selected Active Genome Index.
- VCF/gVCF parsing does not import public sources or build whole-callset static
  artifacts. Use focused tools such as `clinvar.match_variants`,
  `active_genome_index.classify_genotype_support`, or
  `region.retrieve_features` when that evidence is needed. BAM
  parsing also requires local `samtools` and `bcftools`.
- Consumer array calls support rsID/locus presence checks. Sequencing depth,
  genotype quality, phasing, and region callability come from sequencing-derived sources.
- If the user asks a tiny factual question and an Active Genome Index already exists, prefer
  `variant.resolve` from `skills/variant-evidence/SKILL.md` to resolve the
  target and query the Active Genome Index.
- If parsing already succeeded, the original file is an intake source. Future
  inquiries should normally use the Active Genome Index.
- For genetics questions outside Active Genome Index workflows, use Journal
  source-review memory, GWAS, or normal agent research without adding a routine
  source-status line.

## After Parsing

Select the focused skill from the user intent:

- ClinVar discovery: `skills/clinvar/SKILL.md`
- Specific variant/gene/rsID: `skills/variant-evidence/SKILL.md`
- GWAS phenotype plus rsIDs: `skills/gwas-catalog/SKILL.md`
- All-at-once dashboard / one-shot rundown: `skills/decode/SKILL.md`

## Lifecycle: handle `needs_reparse` and `schema_too_new` automatically

`genomi.describe_context` (and every read op's error envelope) returns an
`active_genome_index_readiness` block with `status` and a structured `reason` code. The
agent must reconcile lifecycle state on its own before falling back to the
user.

**`status: needs_reparse`** (`reason: active_genome_index_needs_reparse`)

The on-disk Active Genome Index was built by an older Genomi runtime than the current
`SCHEMA_VERSION`. Reparse rebuilds it at the current schema.

1. Read `active_genome_index.source` (and `active_genome_index.vcf`) from
   `genomi.describe_context`. Check `active_genome_index.availability.source`.
2. If `availability.source` is true (path is still on disk), call
   `genomi.parse_source({"source": "<path-from-describe_context>"})`
   without prompting the user — this is routine maintenance.
3. If `availability.source` is false (path moved or deleted), ask the user
   once: *"Your Active Genome Index needs to be reparsed at the new schema,
   but the original source isn't at `<recorded path>` anymore. Send me the
   current path, or restore the file there."* Wait for the user, then parse
   that path.
4. After reparse, call `genomi.describe_context` again to confirm
   `active_genome_index_readiness.status == "complete"`. Then continue the original
   request (decode, variant lookup, PharmCAT, whatever the user asked for).

**`status: schema_too_new`** (`reason: active_genome_index_schema_too_new`)

The Active Genome Index was built by a newer Genomi than the current process. Do not
reparse — that would downgrade the Active Genome Index. Tell the user the runtime is out
of date and they need to upgrade Genomi.

**Incomplete (missing objects)**

Continue with what's available; surface honest "Not gathered" notes in any
downstream artifacts. Do not silently substitute mock or placeholder data.

## Context Checks

- Select the Active Genome Index from the session's source path, approved `agi_id`, or default user.
- Use an existing Active Genome Index when it answers the question.
- Use `variant.resolve` for rsID, allele, locus, or region checks after parsing.
- Treat broad candidate inventories as triage inputs.
- Keep raw genome source content and broad match files local.
