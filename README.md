<p align="center">
  <img src="assets/genomi-logo.png" alt="Genomi logo" width="160">
  <br>
  <strong>Your genome. Decoded.</strong>
  <br>
  <a href="https://www.genomiagent.com/">Website</a>
  ·
  <a href="https://raw.githubusercontent.com/exon-research/genomi/master/INSTALL_FOR_AGENTS.md">Install guide</a>
  ·
  <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white&labelColor=111827"></a>
  <a href="https://github.com/exon-research/genomi/releases/tag/v0.1.0"><img alt="Version" src="https://img.shields.io/badge/version-0.1.0-2563EB?style=flat-square&labelColor=111827"></a>
  <a href="https://modelcontextprotocol.io/"><img alt="MCP" src="https://img.shields.io/badge/MCP-agent--native-7C3AED?style=flat-square&labelColor=111827"></a>
  <a href="SKILL.md"><img alt="Skill" src="https://img.shields.io/badge/skill-agent--ready-0E7490?style=flat-square&labelColor=111827"></a>
  <a href="#privacy"><img alt="Local-first" src="https://img.shields.io/badge/privacy-local--first-15803D?style=flat-square&labelColor=111827"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-64748B?style=flat-square&labelColor=111827"></a>
</p>

# Genomi

> Am I going bald? What does my DNA say about Alzheimer's risk? Why does
> ibuprofen do nothing for me?

DNA is the layer underneath all of that. It shapes the proteins, enzymes,
receptors, and pathways behind nutrition, medication response, sleep,
exercise, inherited traits, and risk for some conditions. Not destiny. But
the most personal data you carry.

And it is overwhelming. ~3 billion base pairs, 20,000+ genes, millions of
observed variants per person. No clinician, no lab, no individual holds that
in their head. It is too much.

We live in an era where AI can take on tasks that were not possible before,
at scales never seen before. Your genome is exactly that kind of task. And
for the first time, we have the tools to actually read it at the scale it
lives at.

Genomi is an open-source AI agent runtime that turns your AI agent into a personal DNA expert.
Works with Claude Code, Codex, OpenClaw, Hermes, and any MCP-capable host. It gives the agent a private
workspace: your variants in a local Active Genome Index, public genetics evidence ready to
query, memory of what you explored, and report tools that turn DNA questions
into evidence-backed answers. Your genome stays on your machine. The agent
does the work.

## Launch video

<p align="center">
  <a href="https://youtu.be/8CkoDNlyvZ0">
    <img src="https://img.youtube.com/vi/8CkoDNlyvZ0/maxresdefault.jpg" alt="Genomi launch video" width="640">
  </a>
</p>

## See it in action

- [Genomi parses your raw DNA file into a local database your agent can query](https://youtu.be/mJUw6Lf8zEk)
- [Genomi keeps your raw DNA file on your machine](https://youtu.be/Paj2ixdeZGk)
- [Genomi knows when to say "No" and "I don't know"](https://youtu.be/-yXZhFDiYP0)
- [Genomi evolves — your agent self-updates to sync with the latest research](https://youtu.be/ih_7elp2H2w)

## TL;DR

Even TL;DR is too long, just paste this to your agent:

```text
Hey please read this and tell me why Genomi is different from other AI
agent harnesses. Why is this actually useful for understanding my DNA privately?
https://raw.githubusercontent.com/exon-research/genomi/master/llms-full.txt
```

## Just Install It

Install it through your agent. Paste one instruction, answer a few questions,
and let your agent wire up the runtime:

```text
Install and configure Genomi by following the instructions here:
https://raw.githubusercontent.com/exon-research/genomi/master/INSTALL_FOR_AGENTS.md
```

The install guide covers dependency checks, library selection, MCP
registration, optional genome-source import, and verification. If Genomi is
already packaged or otherwise present, the canonical install/update path is
`genomi install` or the MCP operation `genomi.install`; the source bootstrap is
only for hosts that do not have Genomi yet.

## Works With Every Agent

Genomi is not tied to one chat app. Any agent host that can use MCP tools,
local commands, or installed skills can talk to the same local Genomi runtime.

| Host family | How Genomi connects |
| --- | --- |
| Claude Code | MCP server plus Genomi skills |
| Codex CLI | MCP server plus Genomi skill |
| OpenCode, OpenClaw, Hermes | MCP server plus host skill where supported |
| Cursor, Gemini CLI, Cline, Goose, Roo Code, Windsurf, Claude Desktop | MCP server |
| Any other MCP-capable host | `genomi serve` over stdio |

One local Genomi home can hold the public libraries, Active Genome Index
records, score caches, and journals. Session access still follows Genomi's
approval rules, but the underlying evidence workspace is reusable across host
agents.

## Or If You Prefer The Old-School Way

Clone, install, point your MCP-capable agent at it. Same flow the installer
script runs, just done by hand. The
[install guide for agents](INSTALL_FOR_AGENTS.md) is the canonical reference —
if anything below drifts from it, that doc wins.

1. **Get the source.**

   ```bash
   git clone git@github.com:exon-research/genomi.git ~/.genomi/genomi
   cd ~/.genomi/genomi
   ```

2. **Install the package + public libraries.** The recommended install grabs
   every default reference library so Genomi can answer real questions without
   stopping later to fetch missing data. Use a smaller purpose from the catalog
   only when disk, bandwidth, or time is constrained (`common-questions`,
   `medication-response`, `ancestry-context`, `sequence-and-regions`,
   `cell-and-tissue`, `everything`, or `setup-only`):

   ```bash
   export GENOMI_HOME=~/.genomi
   python3 scripts/install_for_agents.py --libraries everything
   ```

   The installer creates a stable command at `$GENOMI_HOME/bin/genomi`.
   Add it to PATH if you want `genomi` available from any shell:

   ```bash
   export PATH="$GENOMI_HOME/bin:$PATH"
   ```

   Once the `genomi` command exists, use it for install/update:

   ```bash
   genomi install --libraries everything
   ```

3. **Register the MCP server with your host agent.**

   ```json
   {
     "mcpServers": {
       "genomi": {
         "command": "/absolute/path/to/GENOMI_HOME/bin/genomi",
         "args": ["serve"]
       }
     }
   }
   ```

   For a source checkout where the stable shim is unavailable:

   ```json
   {
     "mcpServers": {
       "genomi": {
         "command": "bash",
         "args": ["-lc", "cd /path/to/genomi && PYTHONPATH=src python3 -m genomi serve"]
       }
     }
   }
   ```

   Reload your host's MCP servers. For URL-based ingestion, `llms.txt` is the
   compact public map and `llms-full.txt` is one inlined reference file.

## Ask It Things Like

Once Genomi is wired up, you talk to the agent like this. In Codex, use
`$genomi` instead of `/genomi`. The quick stuff first:

> `/genomi` What does my DNA say about Alzheimer's risk?
>
> `/genomi` Am I at risk for early heart disease?
>
> `/genomi` Am I going bald?
>
> `/genomi` Am I a fast or slow metabolizer?
>
> `/genomi` Should I worry about diabetes?
>
> `/genomi` Am I lactose intolerant?
>
> `/genomi` Is alcohol bad for me specifically?

Then hand it something bigger:

> `/genomi` I'm about to start an SSRI. Walk me through my CYP2D6 and
> CYP2C19 status, what the major guideline sources say about dosing, and
> what's preliminary vs actually actionable.

> `/genomi` Run a pharmacogenomic review across every medication I take.
> Lead with guideline-backed dose adjustments. Flag lower-evidence signals
> second. Tell me what's outside scope.

> `/genomi` Build me a one-page rare-disease workup for my HPO terms.
> Rank candidate genes by source-backed evidence, cite each call, and
> show me what's missing before this is worth taking to a clinician.

Or just hand it the whole thing:

> `/genomi decode`

One command. The agent sweeps every capability across your genome —
variants, ClinVar, pharmacogenomics, ancestry, polygenic scores,
nutrigenomics, and your investigation journal — and serves the result
as a self-contained dashboard on localhost. Open the URL in a browser.

Behind those, Genomi gives the agent grounded tools across 20,000+ human
genes, millions of genotype observations from your file, and the public
evidence sources that keep the answer honest.

## What Genomi Provides

| Layer | What you get |
| --- | --- |
| Active Genome Index | A local, queryable ledger of alleles, zygosity, quality, depth, filters, and callability context from your genome source. |
| Evidence Library | Focused tools for variants, ClinVar, GWAS, HPO, pharmacogenomics, ancestry context, PRS, and sequence utilities. |
| Journal | A running log of what you explored, what mattered, and which evidence supported it. |
| Skills | Agent instructions for routing questions, asking for approval, preserving source priors, and answering clearly. |

### Bringing your own genome

Genomi reads your DNA from wherever it already lives. Point it at any VCF or
gVCF you have on disk — clinical exports, research callsets, anything that
follows the spec — and the rest of the pipeline reuses the same Active
Genome Index regardless of where the file came from.

Direct-to-consumer providers are supported natively too. Hand Genomi the
deliverable straight from your account export and it figures out the rest:

- **23andMe**, **AncestryDNA**, **MyHeritage**, **FamilyTreeDNA** (Family
  Finder), and **Living DNA** — raw genotype text/CSV as exported by the
  provider, including gzip/bzip2/xz-compressed files and zip/tar archives.
- **`.genome/1.0` bundles** — directories or archives such as
  `sample.genome.tar.gz`, with `manifest.json`, `schema.json`, and
  partitioned `variants.parquet` records.
- **Nebula Genomics**, **Dante Labs**, and **Sequencing.com** — their VCF
  deliverables are recognized and tagged with the originating provider.
- **Nebula / Dante / Sequencing.com FASTQ** — paired-end raw reads are
  aligned locally from sibling R1/R2 files or a zip/tar archive containing
  the pair (minimap2 for long reads, bwa-mem2 for short reads), sorted, and
  then fed into the same BAM → derived-VCF path. The `wgs-alignment`
  install purpose pulls down both aligners.

### No DNA file yet? Try a public one

If you don't have your own genome yet but want to see what Genomi actually
does, the [Personal Genome Project — Harvard Medical School](https://my.pgp-hms.org/public_genetic_data)
publishes real consumer-DNA deliverables from real participants. Their
catalog includes public examples for the common consumer-array, VCF, gVCF,
BAM, and paired FASTQ shapes above; the checked public inventory did not
include a Living DNA example, even though Genomi supports that export shape.
Pick a matching participant export, point Genomi at it, and ask questions.
It is the cleanest way to kick the tires without sequencing yourself.

Genome data is optional; Genomi also handles public-only genetics questions.

## Why We Built This

I built Genomi because I want AI to take on the things it never could before,
at the scale it never could before — and DNA is exactly that.

A single human genome is overwhelming. Labs spend careers on one gene. Reports
flatten thousands of variants into a single line. Even the best clinician
cannot hold 20,000+ genes and millions of genotype observations in their head.
That is not a limitation of effort. It is a limitation of scale. And it is
the kind of limitation AI is finally good enough to push against.

I want this for my own health. I want it for my family's health. And I want
it to be honest — grounded in real evidence, local by default, with the agent
showing its work instead of guessing from memory.

Raw genome files stay on your machine. Genomi is a workspace, not a static
PDF report. Answers trace back to a source record or they don't get to call
themselves answers. And the whole thing is built for agents over MCP from
the start, not bolted on after.

Generic AI can explain genetics. It should not guess when the question
depends on an exact variant, your genome file, a guideline source, or a
coverage limitation. Genomi gives the agent the tools for the parts that
need evidence, and stays out of the way for the rest.

## What Genomi Can Help Explore

Genomi is not a static report. It is a private workspace your agent can use to
ask better questions across different parts of your genome.

- Traits and everyday responses: lactose, caffeine, alcohol, taste, nutrition,
  sleep, exercise, and similar personal questions.
- Medication response: genes and variants that may affect how your body handles
  specific drugs.
- Carrier and inherited-risk context: exact variant checks, ClinVar assertions,
  and gene-disease evidence.
- Common-trait research: GWAS and published score context for complex traits,
  with clear limits.
- Rare-disease and phenotype review: HPO terms, gene-disease validity, and
  source-backed candidate comparisons.
- Ancestry reference-panel context: qualitative reference-panel similarity and
  overlap checks, not race or ethnicity prediction.
- Reports and memory: cited Markdown reports and a journal of what you explored,
  what mattered, and what still needs follow-up.

## How Genomi Keeps Answers Honest

DNA questions can be personal, messy, and easy to overstate. Genomi keeps the
pieces separated so an agent can show its work.

- Your genome evidence: genotype, zygosity, depth, quality, filters, exact
  allele observation, and callability.
- Public evidence: ClinVar assertions, population frequencies, GWAS records,
  gene-disease validity, phenotype annotations, and source versions.
- Reviewed findings: narrow source-backed notes recorded for a specific target
  or question.
- Agent memory: observations, decisions, unresolved questions, and links back to
  evidence.
- Personal context: optional phenotype, medications, family history, or other
  details you choose to provide.

Different evidence families can point in different directions. Genomi helps the
agent compare them without pretending that one database is the whole truth.

## Privacy

Genomi keeps the most sensitive data close to you.

- Raw genome sources stay on the user's machine.
- Genomi creates Active Genome Index records for personal genome files locally so agents query only the
  variants needed for the current question.
- Genomi asks for current-session approval before read operations use existing
  Active Genome Index artifacts, unless they belong to the configured default
  user.
- Public lookups use selected targets such as rsIDs, genes, drugs, conditions,
  or guideline questions.
- Journal entries are agent-authored memory, not evidence.
- Project journals reject private/sample evidence links.
- Memory exports omit private evidence links unless explicitly requested and
  approved.

## Sources, Libraries, And Attribution

Genomi talks to trusted, verified databases and specialist genomics tools so
your agent can ground answers in real evidence instead of vibes. Install-time
downloads write source manifests where possible. Live adapters return source
URLs and access context in their result envelopes. Reviewed source families are
not treated as background knowledge; agents cite or journal the specific source
records they used.

Installed Genomi libraries:

- [ClinVar](https://www.ncbi.nlm.nih.gov/clinvar/docs/downloads/) —
  `clinvar-grch38` and `clinvar-grch37` VCF caches for exact variant
  interpretation lookup.
- [Human Phenotype Ontology](https://obophenotype.github.io/human-phenotype-ontology/annotations/) —
  `hpo` phenotype-to-gene and disease annotation files.
- [GenCC](https://search.thegencc.org/download) — `gencc` gene-disease
  validity submissions.
- [UCSC Genome Browser downloads](https://hgdownload.soe.ucsc.edu/downloads.html) —
  `reference-grch38` and `reference-grch37` hg38/hg19 FASTA files for
  sequence, normalization, and callability workflows.
- [UCSC liftOver chain files](https://hgdownload.soe.ucsc.edu/downloads.html#liftover) —
  `liftover-chains` for GRCh37/GRCh38 coordinate translation.
- [GENCODE](https://www.gencodegenes.org/human/) — `gencode-grch38` and
  `gencode-grch37` transcript annotation GTFs.
- [ENCODE SCREEN](https://www.encodeproject.org/software/screen/) —
  `encode-ccre-grch38` candidate cis-regulatory element annotations.
- [PanglaoDB](https://panglaodb.se/markers.html?cell_type=%27all_cells%27)
  and [CellMarker 2.0](http://bio-bigdata.hrbmu.edu.cn/CellMarker/) —
  `panglaodb-markers` and `cellmarker-human` marker tables.
- [MSigDB Hallmark](https://www.gsea-msigdb.org/gsea/msigdb/human/collections.jsp#H) —
  `msigdb-hallmark`, installed only from a user-supplied official GMT export
  or URL.
- [PharmCAT](https://pharmcat.org/) and
  [PharmGKB](https://www.pharmgkb.org/) — `pharmcat` all-in-one JAR for
  pharmacogene diplotypes, phenotypes, and recommendation artifacts.
- [1000 Genomes 30x GRCh38](https://www.internationalgenome.org/data-portal/data-collections/30x-grch38.html) —
  `ancestry-1000g-30x-grch38` compact ancestry PCA panel, distributed from
  the [genomi-ancestry-panel](https://github.com/exon-research/genomi-ancestry-panel)
  build project. `ancestry-1000g-30x-grch37` is derived locally from that
  panel with UCSC liftOver chains.
- [minimap2](https://github.com/lh3/minimap2) and
  [bwa-mem2](https://github.com/bwa-mem2/bwa-mem2) —
  `minimap2-binary` and `bwa-mem2-binary` for optional FASTQ alignment.
  BAM/FASTQ workflows also use [samtools and bcftools](https://www.htslib.org/)
  when those tools are needed on the host.

Live public adapters and configured public data:

- [gnomAD](https://gnomad.broadinstitute.org/) population frequency lookups.
- [GWAS Catalog](https://www.ebi.ac.uk/gwas/) association-record retrieval.
- [PGS Catalog](https://www.pgscatalog.org/) score metadata and scoring files.
- [ClinPGx](https://www.clinpgx.org/), [PharmGKB](https://www.pharmgkb.org/),
  [PGxDB](https://pgx-db.org/), [CPIC](https://cpicpgx.org/guidelines/),
  and FDA [pharmacogenomic biomarker](https://www.fda.gov/drugs/science-and-research-drugs/table-pharmacogenomic-biomarkers-drug-labeling/)
  and [pharmacogenetic association](https://www.fda.gov/medical-devices/precision-medicine/table-pharmacogenetic-associations)
  tables for pharmacogenomic guideline, label, and association context.
- [KEGG](https://www.kegg.jp/kegg/pathway.html),
  [Reactome](https://reactome.org/),
  [QuickGO](https://www.ebi.ac.uk/QuickGO/),
  [Human Protein Atlas](https://www.proteinatlas.org/), and
  [ChEMBL](https://www.ebi.ac.uk/chembl/) for pathway, ontology,
  tissue/cell-type, compound, and drug-target relationships.
- [Open Targets Platform](https://platform.opentargets.org/) for disease and
  clinical drug-target context.
- [BioGRID ORCS](https://orcs.thebiogrid.org/),
  [DepMap](https://depmap.org/portal/download/), and
  [NCBI GEO](https://www.ncbi.nlm.nih.gov/geo/) for configured or discovered
  functional-genomics perturbation evidence.

Reviewed source families:

- [ClinGen Gene-Disease Validity](https://search.clinicalgenome.org/kb/gene-validity),
  [GeneReviews](https://www.ncbi.nlm.nih.gov/books/NBK1116/),
  [MONDO](https://mondo.monarchinitiative.org/),
  [Orphanet](https://www.orpha.net/), [OMIM](https://www.omim.org/),
  [GeneCards](https://www.genecards.org/), [MalaCards](https://www.malacards.org/),
  [NCI cancer genetics resources](https://www.cancer.gov/about-cancer/causes-prevention/genetics),
  and the [COSMIC Cancer Gene Census](https://www.cosmickb.org/knowledgebase/cosmic-modules/)
  are source families agents may review, cite, and journal for disease,
  cancer-risk, and gene-context investigations.
- [DrugBank](https://go.drugbank.com/),
  [PharmaProjects](https://pharmaintelligence.informa.com/products-and-services/data-and-analysis/pharmaprojects),
  and [PubMed](https://pubmed.ncbi.nlm.nih.gov/) support reviewed
  drug-target, mechanism, and primary-literature context when the agent records
  specific source-backed findings.

## How It Works

Genomi exposes a small base MCP surface plus a dispatcher for specialized
genomics tools. The host agent does the conversation; Genomi does the grounded
lookup, Active Genome Index creation, evidence retrieval, and report assembly.

1. Connect an agent over MCP — see [the install steps](#or-if-you-prefer-the-old-school-way)
   above for the config snippet.

2. Give the agent a genome file when you want personal context.

Genomi parses the file into an Active Genome Index: a local query substrate for
variants, zygosity, quality, depth, filters, and callability context. Public-only
questions do not require a genome file.

```json
{
  "tool": "genomi.parse_source",
  "params": {
    "source": "<genome-file>"
  }
}
```

3. Ask questions. The agent calls the smallest useful Genomi operation.

Base operations such as `genomi.parse_source`, `genomi.describe_context`, and
`journal.append_entry` are direct MCP tools. Capability operations go through
`genomi.invoke` after the agent reads the matching `skills/<capability>/SKILL.md`.

```json
{
  "tool": "genomi.invoke",
  "params": {
    "tool": "variant.resolve",
    "params": {
      "rsid": "rs429358"
    }
  }
}
```

4. Inspect evidence, defaults, and limitations.

Genomi results include structured evidence, source coverage, and
`defaults_applied` where assumptions matter. Missing libraries, unavailable
external sources, and background jobs return explicit statuses instead of being
treated as negative evidence.

5. Remember.

The Journal records observations, decisions, unresolved questions, and evidence
links.

## Build With Genomi

Genomi is open source and built for people who want AI agents to work with
genomics responsibly: local-first, evidence-grounded, and honest about
limitations. Use it to explore, explain, remember, and report on DNA questions
without uploading the raw genome file.

## Status

> [!WARNING]
> **Experimental. Research and informational use only.**
> Genomi is not a diagnostic device. It does not replace qualified clinical
> review for diagnosis or treatment. Raw genome data stays on your machine
> by design — but you are still responsible for how you share what comes out
> of it.

The schema, tool surface, and capability layout are still moving — pin a
commit if you need stability across upgrades.

## License

Genomi is released under the [Apache License 2.0](LICENSE).

## Citation

If you use Genomi in research, publications, reports, benchmarks, demos, or
derived tools, please cite the project using [CITATION.cff](CITATION.cff) and
acknowledge Genomi where appropriate.

```bibtex
@software{genomi2026,
  title = {Genomi: A Local Genomics Harness for AI Agents},
  author = {Zeng, Mingde and Zhou, Hongjian and Liu, Fenglin and Wu, Jinge},
  year = {2026},
  url = {https://www.genomiagent.com/},
  version = {0.1.0}
}
```

## Contributing

Issues and pull requests welcome. If you are reporting a bug, include the
genome source format (VCF / gVCF / 23andMe / AncestryDNA / etc.), the
operation you ran, and the structured error envelope the agent received —
that is usually enough to reproduce.

## Acknowledgements

Genomi owes a direct implementation debt to the
[Personal Genome Project — Harvard Medical School](https://my.pgp-hms.org/public_genetic_data)
public genetic data catalog.

That same PGP-HMS public dataset also did the unglamorous work of letting
Genomi support these provider shapes natively. Detectors, column quirks,
header banners, archive wrappers, and provider-tagged VCF paths are
sanity-checked against real PGP participant exports when the public catalog
contains that format. Native 23andMe, AncestryDNA, MyHeritage,
FamilyTreeDNA, Nebula, Dante, Sequencing.com, VCF, gVCF, BAM, and FASTQ
coverage benefits directly from those examples; Living DNA and `.genome`
remain supported formats, but the checked PGP-HMS public inventory did not
include examples for those shapes.

Thanks also to [GBrain](https://github.com/garrytan/gbrain), Garry Tan's
OpenClaw/Hermes agent-brain project, for inspiration around making agent
systems source-grounded, memory-aware, and useful from a single fetched
documentation entry point.
