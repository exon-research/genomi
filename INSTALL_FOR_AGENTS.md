# Install Genomi

Official URL: https://www.genomiagent.com/

> Am I going bald? What does my DNA say about Alzheimer's risk? Why does
> ibuprofen do nothing for me?

Welcome 🧬 — you're about to give your AI agent a **genome**. Genomi turns
a flat DNA file into evidence-grounded answers about variants, genes,
phenotypes, diseases, ancestry, and drug response — all running locally on
your machine. No uploads, no cloud round-trips, no "we don't share your
data, trust us."

## For Humans

Paste this into your LLM agent session and let it drive:

```
Install and configure Genomi by following the instructions here:
https://raw.githubusercontent.com/exon-research/genomi/master/INSTALL_FOR_AGENTS.md
```

That's it. The agent will ask you three questions and handle the rest.

**Alternative — do it yourself (not recommended):**

```bash
GENOMI_DEFAULT_HOME="$(
python3 - <<'PY'
import os
import sys
from pathlib import Path

xdg = os.environ.get("XDG_DATA_HOME")
if xdg:
    xdg_path = Path(os.path.expandvars(os.path.expanduser(xdg)))
    if xdg_path.is_absolute():
        print(xdg_path / "genomi")
        raise SystemExit
if sys.platform == "linux":
    print(Path.home() / ".local" / "share" / "genomi")
else:
    print(Path.home() / ".genomi")
PY
)"
GENOMI_HOME="${GENOMI_HOME:-$GENOMI_DEFAULT_HOME}"
export GENOMI_HOME
git clone git@github.com:exon-research/genomi.git "$GENOMI_HOME/genomi"
cd "$GENOMI_HOME/genomi"
python3 scripts/install_for_agents.py --libraries everything
```

Python 3.10+ required. Runs on macOS, Linux, and Windows (via WSL2). One
caveat: raw paired-end FASTQ alignment (`wgs-alignment` purpose, or
`minimap2-binary`/`bwa-mem2-binary` libraries) ships Linux x86_64 binaries;
on macOS or ARM those binaries are skipped at install time and you can
install `minimap2` / `bwa-mem2` via your package manager if you need FASTQ
support. Everything else — variants, ClinVar, pharmacogenomics, ancestry,
PRS, sequence utilities — works the same on every platform. The full
install caches ~7 GB of public reference libraries under `GENOMI_HOME`
(preferred default: explicit `GENOMI_HOME`, then absolute
`$XDG_DATA_HOME/genomi`, then `~/.local/share/genomi` on Linux, otherwise
`~/.genomi`).

After install, peek at [`SKILL.md`](./SKILL.md) and the focused skill docs to
see what your agent can now do.

---

## For LLM Agents

Hey agent — you're installing Genomi for your user today. This is fun work:
in a few minutes you're going to hand your assistant something it has never
had before — a real human genome, queryable in natural language, kept
entirely on this machine.

Read this whole document before sending your first message. Decide whether
Genomi is already installed by computing the preferred default home and checking
whether `$GENOMI_HOME/genomi` holds the project:

```bash
GENOMI_DEFAULT_HOME="$(
python3 - <<'PY'
import os
import sys
from pathlib import Path

xdg = os.environ.get("XDG_DATA_HOME")
if xdg:
    xdg_path = Path(os.path.expandvars(os.path.expanduser(xdg)))
    if xdg_path.is_absolute():
        print(xdg_path / "genomi")
        raise SystemExit
if sys.platform == "linux":
    print(Path.home() / ".local" / "share" / "genomi")
else:
    print(Path.home() / ".genomi")
PY
)"
GENOMI_HOME="${GENOMI_HOME:-$GENOMI_DEFAULT_HOME}"
export GENOMI_HOME
test -f "$GENOMI_HOME/genomi/pyproject.toml" && echo installed || echo not-installed
```

- **Installed** → this is an **update**: run `genomi install` (alias
  `genomi update`), or `"$GENOMI_HOME/bin/genomi" install` if
  `genomi` isn't on PATH. It git-pulls the runtime, reinstalls, fills missing
  libraries, refreshes any whose upstream source changed, re-links any
  host-agent skill symlinks that went stale or dangling, and removes obsolete
  Genomi-owned skill symlinks for capabilities that no longer exist
  (idempotent). Then
  stop — skip the rest of this doc.
- **Not installed** → **first-time install**: follow the steps below to
  bootstrap from source with `scripts/install_for_agents.py`.

Use `--force` / `force: true` only when the user explicitly asks to re-download
already cached public libraries or replace a non-symlink file/directory that is
blocking a Genomi host-skill link; it's never needed to fill in missing ones.

### Step 0: Greet the user

**This is the first thing they see — don't skip it. Don't be cold.** Send
something like:

> 👋 Hey! I'm going to give your assistant a genome.
>
> Genomi installs entirely on your machine, caches some public reference
> libraries (ClinVar, HPO, GenCode, PharmCAT, 1000 Genomes, and friends),
> and then your agent can answer real questions like *"do I have anything
> pathogenic in BRCA1?"*, *"am I a fast or slow CYP2D6 metabolizer?"*, or
> *"what does my DNA say about Alzheimer's risk?"* — grounded in evidence,
> not vibes.
>
> I just need three answers from you, then I'll handle the rest. Ready?

Match the user's energy and their language. If they write in French, reply in
French. If they write in Chinese, reply in Chinese. Detect their language from
their very first message and use it for every message in this conversation —
questions, confirmations, the tour, all of it. Then go to Step 0.5.

### Rules

1. **One question at a time.** Send a question, wait for the answer, move on.
2. **Speak the user's language.** Detect the language of the user's first
   message and use it throughout the install flow. Never switch languages
   mid-conversation unless the user does first.
3. **Privacy boundary.** A genome path the user gives you in *this* chat is
   approval to read *that one source* for *this session only*. Don't reuse
   genome sources from other chats. Don't peek into existing Active Genome
   Index contexts without explicit current-session approval.
4. **Stay inside the user's choices.** Don't install libraries beyond what
   they picked. Don't move or delete `GENOMI_HOME`. Don't import a genome
   source unless they asked in this chat.

Silent defaults for source bootstrap only: source checkout at
`$GENOMI_HOME/genomi`, host-skill install on, install verification on.
User-owned choices: Q1 (`--libraries`), Q2 (`GENOMI_HOME`), and Q3
(response tone).

### Step 0.5: Note the platform

Record the host platform for later. It's only a hard gate when the user
selects FASTQ-alignment libraries:

```bash
python3 - <<'PY'
import platform, sys
print(sys.platform, platform.machine())
PY
```

Behavior by platform:

- **Linux x86_64** — every library installs, including `minimap2-binary`
  and `bwa-mem2-binary`. FASTQ → BAM alignment is supported.
- **macOS / Linux ARM / anything else** — `minimap2-binary` and
  `bwa-mem2-binary` are skipped at install time (the installer prints a
  notice). Every other purpose (`common-questions`, `medication-response`,
  `ancestry-context`, `sequence-and-regions`, `cell-and-tissue`,
  `setup-only`) installs and runs normally; `everything` installs too,
  just without the aligners. If the user needs FASTQ alignment on this
  host, point them at `brew install minimap2 bwa-mem2` (or their package
  manager's equivalent) and let them put the binaries on PATH.

### Step 1: Ask Q1 — what should Genomi be ready for?

Maps to `--libraries`. Recommend "Everything" unless the user volunteers
a disk, bandwidth, or time constraint.

```text
What should Genomi be ready to help with first?
1. Everything: all default public reference libraries (~7 GB, recommended)
2. Common variant / gene / phenotype / condition questions (~305 MB)
3. Medication-response questions (~335 MB)
4. Ancestry reference-panel context (~3 MB)
5. DNA sequence and genomic-region annotation (~3.5 GB)
6. Cell / tissue marker grounding (~15 MB)
7. Just install Genomi, no public data yet (0 MB)
```

Map their answer to one `--libraries` value (use the exact string — do not
translate to old tier names or numbered choices):

| User answer | `--libraries` value | Disk |
| --- | --- | --- |
| 1 / Everything | `everything` | ~7 GB |
| 2 / Common questions | `common-questions` | ~305 MB |
| 3 / Medication | `medication-response` | ~335 MB |
| 4 / Ancestry | `ancestry-context` | ~3 MB |
| 5 / Sequence + regions | `sequence-and-regions` | ~3.5 GB |
| 6 / Cell + tissue | `cell-and-tissue` | ~15 MB |
| 7 / Setup only | `setup-only` | 0 MB |
| Genuinely unsure | `everything` | ~7 GB |

Custom subsets: pass exact library IDs from the catalog at the bottom,
comma-separated.

After the user picks their libraries, offer one more in a single line:
`msigdb-hallmark` (MSigDB Hallmark pathway sets) — optional, useful for
cancer-biology and immune-signaling pathway questions, and a free manual
download (its license keeps it out of `everything`). Set it up if they want
it, using the "Manual-source library" section of the catalog.

### Step 2: Ask Q2 — where should Genomi live?

`GENOMI_HOME` is the data root — Active Genome Index plus every
downloaded reference library, up to ~7 GB depending on Q1.

```text
Where should Genomi store its data root (Active Genome Index + reference
libraries)? Up to ~7 GB depending on what you picked above.

Preferred default: compute it with the resolver below.
Or give any path (relative or absolute) on a disk with enough free space.
```

Resolve to an absolute path before exporting. The resolver matches Genomi's
runtime order: explicit `GENOMI_HOME`, then absolute `$XDG_DATA_HOME/genomi`,
then Linux `~/.local/share/genomi`, then legacy `~/.genomi` on other platforms.

```bash
GENOMI_DEFAULT_HOME="$(
python3 - <<'PY'
import os
import sys
from pathlib import Path

xdg = os.environ.get("XDG_DATA_HOME")
if xdg:
    xdg_path = Path(os.path.expandvars(os.path.expanduser(xdg)))
    if xdg_path.is_absolute():
        print(xdg_path / "genomi")
        raise SystemExit
if sys.platform == "linux":
    print(Path.home() / ".local" / "share" / "genomi")
else:
    print(Path.home() / ".genomi")
PY
)"
GENOMI_HOME="${GENOMI_HOME:-$GENOMI_DEFAULT_HOME}"
export GENOMI_HOME
printf '%s\n' "$GENOMI_HOME"
```

Then:

- Preferred default → export the computed `GENOMI_HOME`. No extra flag.
- Anywhere else → `export GENOMI_HOME=<absolute path>` **and** pass
  `--genomi-home <absolute path>` to the installer.

If the chosen path already exists and is non-empty but isn't a Genomi data
root, ask before proceeding — see the populated-home note in Step 6.

### Step 3: Ask Q3 — response tone

Required. This is the user's default explanation style for downstream Genomi
answers.

Maps to one of Genomi's response profiles in
`src/genomi/runtime/host_response_profiles.json`. The chosen profile
shapes every downstream answer.

```text
How should Genomi explain things in answers?
1. eli5      — explain to me like I am 5: define every term, use analogies,
               walk through the reasoning; educational, not terse (recommended)
2. patient   — concise answer, define terms on first use
3. literate  — include genes, variants, zygosity, evidence classes
4. expert    — full methods, QC, source provenance, structured evidence
```

Persist it by calling the **MCP tool** `genomi.set_response_profile` with
`{"profile": "<id>"}` (`<id>` ∈ `eli5`, `patient`, `literate`, `expert`) — an
MCP tool from your agent runtime, not a shell command (there is no
`genomi set-response-profile` CLI). Also record the id in the host's durable
memory as a backup. On "default" / "doesn't matter", use `eli5`.

### Step 4: Pre-flight checks

Run silently to choose the install path. If `$GENOMI_HOME/genomi` already holds
the project, Genomi is installed → update it via Step 6. Otherwise
clone/bootstrap in Step 5.

```bash
test -f "$GENOMI_HOME/genomi/pyproject.toml" && echo installed || echo not-installed
python3 --version    # need 3.10+
python3 -m pip --version || uv --version
git --version
```

Genomi's VCF/gVCF parse path requires `bgzip`. On Linux, install the `tabix`
package; it provides both `bgzip` and `tabix`.

```bash
command -v bgzip || echo "missing bgzip; on Linux install the tabix package"
```

### Step 5: Source checkout

Skip this step when `$GENOMI_HOME/genomi` already holds the project — you're
updating an existing install, not bootstrapping.

Source lives at `$GENOMI_HOME/genomi` (so it travels with the data root
chosen in Q2). Make sure it's current (skip if you're already inside
one):

```bash
if [ -d "$GENOMI_HOME/genomi/.git" ]; then
  git -C "$GENOMI_HOME/genomi" pull --ff-only
else
  git clone git@github.com:exon-research/genomi.git "$GENOMI_HOME/genomi"
fi
cd "$GENOMI_HOME/genomi"
```

If `$GENOMI_HOME/genomi` exists but isn't a Genomi checkout, ask the
user for a different checkout path before continuing.

### Step 6: Run the installer

Assemble the command from Q1 and Q2. **Show the exact command before
running it** — the user should see what's about to download.

Use exactly one path.

MCP path, when the Genomi MCP server is available:

```json
{
  "name": "genomi.install",
  "arguments": {
    "libraries": "<Q1-value>",
    "response_profile": "<Q3-profile>"
  }
}
```

CLI path, when the `genomi` command is available:

```bash
export GENOMI_HOME=<Q2-path>
genomi install --libraries <Q1-value> --response-profile <Q3-profile>
```

Source bootstrap fallback, only after Step 5 cloned or selected a checkout:

```bash
export GENOMI_HOME=<Q2-path>
python3 scripts/install_for_agents.py \
  --libraries <Q1-value> \
  [--genomi-home <Q2-path>]   # include only when Q2 is not the computed default
  [--genome-source /path/to/file] [--user-nickname "Name"] [--set-default-user]
```

The installer will:
- install the Genomi Python package (skip with `--skip-package`),
- create a stable command shim at `<GENOMI_HOME>/bin/genomi`,
- download the selected public libraries into `GENOMI_HOME`,
- parse the genome source if `--genome-source` was passed,
- symlink the `genomi` umbrella skill and `genomi-<capability>` focused skills
  into detected host skill dirs,
- run its built-in install verification through `<GENOMI_HOME>/bin/genomi`.

The installer does **not** touch host MCP config files — see Step 7, you'll
write that yourself.

After install, add the shim directory to PATH so the MCP host can launch
`genomi serve`:

```bash
export PATH="<GENOMI_HOME>/bin:$PATH"
```

**PEP 668 / managed-Python fallback.** If `python3 -m pip` is blocked
("externally-managed-environment"), install `genomi` into a venv and run the
installer with that venv's interpreter, then pass `--skip-package`:

```bash
uv venv .venv && uv pip install -e . --python .venv/bin/python
export PATH="$PWD/.venv/bin:$PATH"
.venv/bin/python scripts/install_for_agents.py --skip-package --libraries <Q1-value>
```

Whatever interpreter runs the installer is the one the `genomi` shim launches,
so `genomi` must be importable from it (any venv/conda/system setup is fine).

**Re-running into a populated `GENOMI_HOME` is safe and idempotent.** Install
checks each present library against its source and re-downloads only what
actually changed upstream (transferring nothing for caches already current),
and fills any missing libraries — so running `--libraries everything` against a
near-complete home fills the gaps and refreshes stale caches without re-fetching
the multi-GB files you already have current. No `--force` needed for that; a
normal re-run already refreshes a changed-upstream cache (e.g. the weekly ClinVar
release). Use `--force` only to re-download unconditionally regardless of
freshness. To find what's missing first, check the library inventory
(`genomi.check_libraries` / `genomi tools`) — its summary reports
`installed_count` / `missing_count`.

#### Less common flags

| Flag | When to use |
| --- | --- |
| `--force` | Re-download selected libraries unconditionally, even if unchanged upstream, and replace non-symlink Genomi host-skill link conflicts. Not needed to fill gaps, refresh changed caches, or repair stale symlinks — a normal run does those. |
| `--ancestry-panel-dir /path` | Use a locally-built ancestry panel instead of the release tarball. |
| `--ancestry-panel-url <URL>` | Mirror or unreleased panel build. |
| `--pharmcat-version v2.15.5` | Pin a PharmCAT release. |
| `--msigdb-gmt /path/to/h.all.v*.symbols.gmt` | Required only when `msigdb-hallmark` is selected. |

### Step 7: Wire the MCP config yourself

You — the host agent — write this. The installer does not touch host config
files; their schemas differ across hosts and you have better merge tooling.

For the host you're running in, use that host's documented `mcp add` command
if one exists; otherwise read the config file, merge the single Genomi entry
under the existing servers map, and write it back, then re-read and confirm
it still parses.

Use the **absolute path** `<GENOMI_HOME>/bin/genomi` as the command, with
`<GENOMI_HOME>` resolved to the path chosen in Q2 (the installer printed the
exact value on completion). Don't write `"command": "genomi"` — that depends
on the MCP host's launch PATH, which often differs from the user's shell PATH.

In the snippets below, substitute `<GENOMI_HOME>` with the resolved absolute
path from Q2 or the installer summary.

After writing the entry below, ask the user to restart the host so the
server is spawned. Some hosts also require a per-host approval step
(project-scoped configs in particular) — check the host's docs and run it
if needed.

**Claude Code** — write `~/.claude.json` (this is the user-level config;
**not** `~/.claude/.mcp.json`, which Claude Code doesn't read). It already
exists as a large JSON file owned by Claude Code; read it, add or update
the top-level `mcpServers.genomi` key, and write it back without touching
unrelated keys:

```json
{
  "mcpServers": {
    "genomi": {
      "command": "<GENOMI_HOME>/bin/genomi",
      "args": ["serve"]
    }
  }
}
```

User-level `mcpServers` in `~/.claude.json` launches at session start with
no separate enable step. (The `enabledMcpjsonServers` array in
`~/.claude/settings.json` is a separate gate that only applies to
project-scoped `.mcp.json` files in the working directory — not to this
user-level entry.)

**Gemini CLI** — write `~/.gemini/settings.json` using the same
`mcpServers` schema. Check `gemini --help` for any enable step in the
running release.

**Codex CLI** — `~/.codex/config.toml`. The key is `[mcp_servers.<name>]`:

```toml
[mcp_servers.genomi]
command = "<GENOMI_HOME>/bin/genomi"
args = ["serve"]
```

**Hermes** — `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  genomi:
    command: <GENOMI_HOME>/bin/genomi
    args:
      - serve
```

**OpenClaw** — `~/.openclaw/openclaw.json` (servers live under `mcp.servers`):

```json
{
  "mcp": {
    "servers": {
      "genomi": {
        "command": "<GENOMI_HOME>/bin/genomi",
        "args": ["serve"]
      }
    }
  }
}
```

If a `genomi` entry already exists, check its `command`. A stale path from a
prior install (e.g. one pointing into `/tmp` or `/private/var/folders`) won't
launch — overwrite it with the resolved `<GENOMI_HOME>/bin/genomi`.

The installer already symlinked the Genomi skill into detected skill dirs
(`~/.claude/skills`, `~/.codex/skills`, `~/.openclaw/skills`,
`~/.hermes/skills`, `~/.agents/skills`). Confirm the skill symlinks point
back into the Genomi checkout, then reload the host's MCP servers.

> ⚠️ **Invocation syntax is host-specific.** Ask the host to list installed
> skills; don't assume `/genomi` works in every host.

### Step 8: Offer to import a genome (optional)

Ask the user:

```text
Do you want to provide a genome file now? If yes, send the local file path.
Genomi will detect the source type. If not, say skip — you can add one later.
```

If they decline (skip / no / later), go to Step 9.

#### "What kind of file?"

Answer from this list. Genomi reads any of these locally — **nothing is
uploaded off-machine**:

- **VCF** or **gVCF** from anywhere (`.vcf`, `.vcf.gz`, `.vcf.bz2`,
  `.vcf.xz`, `.gvcf`, `.gvcf.gz`, or a zip/tar archive containing the
  VCF/gVCF).
- **BAM** of aligned reads, either as a file or as a zip/tar archive member
  (Genomi derives a local VCF).
- **`.genome/1.0` bundle**, including `sample.genome.tar.gz`.
- **Direct-to-consumer raw DNA exports**, used as-is from the provider account:
  - 23andMe — raw genotype `.txt`, compressed file, or zip/tar archive
  - AncestryDNA — raw genotype `.txt`, compressed file, or zip/tar archive
  - MyHeritage — raw genotype `.csv`, compressed file, or zip/tar archive
    (the `# MyHeritage DNA raw data` banner file)
  - FamilyTreeDNA (Family Finder autosomal) — `.csv`, compressed file, or
    zip/tar archive
  - Living DNA — autosomal `.txt`, compressed file, or zip/tar archive
- **Whole-genome VCF or paired FASTQ** from a sequencing service:
  - Nebula Genomics — `.vcf` / `.vcf.gz` or paired `_R1_/_R2_` FASTQ files
  - Dante Labs — `.vcf.gz` (DRAGEN) or paired FASTQ files
  - Sequencing.com — `.vcf.gz` (SNV+indel gVCF / CNV / SV) or paired FASTQ files

For consumer-DNA providers, **do not** ask the user to convert their file.
Hand the original deliverable straight to Genomi; source-type auto-detection
figures out the rest. The user must point at the actual data file — not a
manifest, folder, or screenshot. If their FASTQ is archived, the zip/tar must
contain both R1 and R2 files with recognized pair suffixes such as `_R1_` /
`_R2_` or `_1` / `_2`; a single archived FASTQ member is not enough.

**Paired-end FASTQ needs `minimap2` and `bwa-mem2` on PATH or under
`<GENOMI_HOME>/tools/aligners/`.** On Linux x86_64, `--libraries
wgs-alignment` (or `everything`) installs them automatically. On macOS or
ARM the bundled binaries don't apply; if the user wants the FASTQ path on
this host, have them `brew install minimap2 bwa-mem2` (or use their package
manager's equivalent) so the runtime can find them. If the user runs a
FASTQ parse without the aligners present, the parse returns a
`requires_library_install` envelope naming `minimap2-binary` and
`bwa-mem2-binary` — install or point at locally-built aligners and retry.

#### "I don't have a file"

Point them at the **Personal Genome Project — Harvard Medical School**
public catalog: <https://my.pgp-hms.org/public_genetic_data>. PGP-HMS
participants have published real, freely-licensed consumer-DNA
deliverables covering most listed source shapes, including public examples
for 23andMe, AncestryDNA, MyHeritage, FamilyTreeDNA, VCF/gVCF, BAM, and
paired FASTQ. The checked public inventory did not include Living DNA or
`.genome` examples even though Genomi supports those source shapes.
Download a matching participant export and pass the path as
`--genome-source <path>` exactly like a personal file.

If asked: Genomi's multi-provider support is validated where possible by
PGP-HMS real participant exports freely available under a permissive re-use
license; formats not present in the public inventory are explicitly tracked
as supported-without-PGP-example.

#### If they give you a path

Ask, in this order (one at a time):

1. **Profile nickname:**
   ```text
   Profile nickname for this genome (e.g., your first name or initials)?
   ```
2. **Default-profile flag:**
   ```text
   Should this profile be the default Genomi uses in future sessions? (yes/no)
   ```

Map answers to installer flags:

| Captured | Flag |
| --- | --- |
| The path | `--genome-source <path>` |
| The nickname | `--user-nickname <name>` |
| "yes" to default | `--set-default-user` |

Don't ask about file format (auto-detected). Don't ask for a file label.
If `GENOMI_HOME` already contains user profiles, the nickname is required
to disambiguate.

### Step 9: Verify

Read this document again. Did you skip anything? Did you set
`GENOMI_HOME`? Did the verifier print `verify: genomi tools ok`? Is the
MCP server connected in the host?

### Step 10: Quick tour of what they just got

A few pointers so they can actually use Genomi:

1. **`/genomi decode`** — the one-shot whole-genome dashboard. Codex is the
   exception: use **`$genomi-decode`** there. Composes
   every capability into a single HTML report.
2. **Ask anything in natural language.** The host agent routes through
   Genomi's skills and tools; no jargon required.
3. **90+ per-capability skills** were dropped into your host's skill
   directories — pharmacogenomics, ancestry, GWAS, rare disease, cancer
   risk, nutrigenomics, ClinVar lookup, gnomAD frequencies, PRS,
   functional genomics, sequence utilities, plus a journal for
   investigation memory.
4. **Privacy stays local.** Every reference library is cached on disk;
   every genome stays on disk; the only network calls are tool-level and
   clearly marked.

### Step 11: Ask for a Star ⭐

Ask the user:

> "If Genomi was helpful, would you mind giving the repo a star? It really
> helps the project grow! ⭐"

If they say yes, run:

```bash
gh repo star exon-research/genomi
```

**Important:** Only run the command if the user explicitly says yes. Never
star automatically without consent.

### Step 12: Congratulations 🎉 — final message

Send something like this (adapt the dashboard line if no genome was
imported):

```text
Congratulations 🎉 Genomi is installed and ready.

Day-to-day use: invoke Genomi the way your host lists installed skills.
The skill calls the Genomi MCP server (`genomi serve`) under the hood and
keeps session context + tool-use audit in one place.

Try the full one-shot rundown — type:  /genomi decode

In Codex, use:  $genomi-decode

The decode skill is the whole-genome dashboard kicker. It sweeps every
relevant Genomi capability in one shot — variants, ClinVar interpretation,
pharmacogenomics, ancestry, phenotype risk, rare-disease and cancer
signals, nutrigenomics, GWAS associations, PRS — then composes a single
self-contained `Genomi Dashboard.html` with a localhost serve command you
can open in a browser. One command, full rundown.

(Requires an active genome — if you skipped genome import, run
`parse_source` with your file path first.)
```

Then offer a few starter questions from the README. Pick whichever fit
their vibe:

> `/genomi` What does my DNA say about Alzheimer's risk?
>
> `/genomi` Am I at risk for early heart disease?
>
> `/genomi` What actually runs in my family?
>
> `/genomi` Am I a fast or slow metabolizer?
>
> `/genomi` Should I worry about diabetes?
>
> `/genomi` Am I lactose intolerant?
>
> `/genomi` Is alcohol bad for me specifically?

And when they're ready for something bigger:

> `/genomi` I'm about to start an SSRI. Walk me through my CYP2D6 and
> CYP2C19 status, what the major guideline sources say about dosing, and
> what's preliminary vs actually actionable.
>
> `/genomi` Run a pharmacogenomic review across every medication I take.
> Lead with guideline-backed dose adjustments. Flag lower-evidence signals
> second. Tell me what's outside scope.
>
> `/genomi` Build me a one-page rare-disease workup for my HPO terms.
> Rank candidate genes by source-backed evidence, cite each call, and
> show me what's missing before this is worth taking to a clinician.

That's it. The agent will figure out the rest.

---

## Boundaries (recap)

- Don't move or delete `GENOMI_HOME`.
- Don't import a genome source unless the user asked in this chat.
- Don't search existing Active Genome Index contexts without explicit
  session approval.
- Don't install libraries beyond what the user picked in Step 1.
- Don't write private genome evidence into shared journals.

## Library Catalog

Reference for Q1 mapping, custom-subset installs, and answering user
follow-ups. On-disk sizes are typical post-install; the full default set
is ~7 GB.

Default downloadable libraries:

| Library | What it enables | Disk |
| --- | --- | --- |
| `clinvar-grch38` | ClinVar VCF cache for GRCh38 variant interpretation lookups. | ~180 MB |
| `clinvar-grch37` | ClinVar VCF cache for GRCh37 variant interpretation lookups. | ~180 MB |
| `hpo` | HPO phenotype gene and disease annotation files. | ~100 MB |
| `gencc` | GenCC gene-disease validity TSV. | ~25 MB |
| `reference-grch38` | UCSC hg38 reference FASTA and `.fai` for sequence/callability workflows. | ~3.2 GB |
| `reference-grch37` | UCSC hg19 reference FASTA and `.fai` for sequence/callability workflows. | ~3.1 GB |
| `gencode-grch38` | GENCODE v49 transcript annotation GTF for GRCh38 region annotation. | ~100 MB |
| `gencode-grch37` | GENCODE v49lift37 transcript annotation GTF for GRCh37 region annotation. | ~100 MB |
| `encode-ccre-grch38` | ENCODE SCREEN candidate cis-regulatory elements BED for GRCh38. | ~30 MB |
| `panglaodb-markers` | PanglaoDB cell-type marker table. | ~5 MB |
| `cellmarker-human` | CellMarker 2.0 human marker table normalized for Genomi. | ~10 MB |
| `pharmcat` | PharmCAT all-in-one JAR for broad pharmacogenomic calling. Requires `java` on `PATH` at runtime. | ~30 MB |
| `ancestry-1000g-30x-grch38` | 1000 Genomes 30x GRCh38 compact ancestry PCA panel used by `ancestry.estimate_population_context`. Downloaded as a pre-built tarball from [`exon-research/genomi-ancestry-panel`](https://github.com/exon-research/genomi-ancestry-panel/releases) and SHA-256 verified. | ~3 MB |
| `ancestry-1000g-30x-grch37` | GRCh37 coordinate version of the ancestry PCA panel, produced locally from the GRCh38 panel plus `liftover-chains`, for GRCh37 samples. | ~3 MB |
| `minimap2-binary` | Pinned [minimap2](https://github.com/lh3/minimap2) release used for long-read FASTQ → BAM alignment. Linux x86_64 only; the tarball is SHA-256 verified and dropped at `<GENOMI_HOME>/tools/aligners/minimap2/minimap2`. Do not select this library on native macOS or ARM hosts. | ~5 MB |
| `bwa-mem2-binary` | Pinned [bwa-mem2](https://github.com/bwa-mem2/bwa-mem2) release used for short-read FASTQ → BAM alignment. Linux x86_64 only, with the same platform boundary as `minimap2-binary`. Builds a reference index on first use (~5 min for GRCh38). Do not select this library on native macOS or ARM hosts. | ~50 MB |

Manual-source library (not in any default purpose):

| Library | What it enables | Requirement |
| --- | --- | --- |
| `msigdb-hallmark` | MSigDB Hallmark member-gene lookup through `pathway.retrieve_members`. | User-supplied official GMT export or URL. |

Offer `msigdb-hallmark` during install (Step 1). When you do, give the user
these three facts:

- It's optional. Reactome and KEGG pathway sources install automatically and
  cover most pathway needs; only `pathway.retrieve_members
  source=msigdb_hallmark` lookups depend on this file.
- It enables MSigDB Hallmark gene sets — 50 curated pathway signatures
  (cell-cycle, EMT, hypoxia, inflammation, oxidative phosphorylation, etc.),
  useful for cancer-biology and immune-signaling questions.
- It needs a free manual download: the user registers at
  <https://www.gsea-msigdb.org/gsea/msigdb>, downloads
  `h.all.v<version>.symbols.gmt`, and gives you the path. MSigDB's license bars
  redistribution, so Genomi installs it from the user's copy:

```bash
python3 scripts/install_for_agents.py --libraries msigdb-hallmark --msigdb-gmt /path/to/h.all.v*.symbols.gmt
GENOMI_MSIGDB_HALLMARK_GMT=/path/to/h.all.v*.symbols.gmt python3 scripts/install_for_agents.py --libraries msigdb-hallmark
```

**Network-backed sources are not libraries.** Tool metadata marks them
with `dependencyContract.externalNetwork`; local source files use
`dependencyContract.localResources`. Example:
`gnomad.fetch_population_frequency` hits the public gnomAD API and caches
returned rows in the evidence DB — there is no local gnomAD library by
default. If a network source is unreachable, the tool returns
`source_unavailable`.
