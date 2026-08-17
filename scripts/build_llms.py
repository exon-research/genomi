#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO_BASE = "https://raw.githubusercontent.com/exon-research/genomi/master"
DEFAULT_REPO_GIT = "git@github.com:exon-research/genomi.git"
DEFAULT_OFFICIAL_URL = "https://www.genomiagent.com/"
VERSION = "0.1.0"

DOCS: list[tuple[str, str, str]] = [
    ("Core entry points", "INSTALL_FOR_AGENTS.md", "Mandatory agent install path, verification, MCP setup, and first-question flow."),
    ("Core entry points", "SKILL.md", "Top-level Genomi skill contract and runtime axes."),
    ("Core entry points", "README.md", "Project overview, interfaces, architecture, examples, and verification."),
    ("Conventions", "skills/conventions/context-routing.md", "Index home, users, scoped access, and Active Genome Index selection rules."),
    ("Conventions", "skills/conventions/evidence-quality.md", "Evidence classes, source precedence, and citation discipline."),
    ("Conventions", "skills/_output-rules.md", "User-facing answer shape and safety language."),
    ("Structured context", "src/genomi/runtime/host_response_profiles.json", "Response-depth profile metadata for user-facing answer shape."),
    ("Skills", "skills/genomic-inquiry/SKILL.md", "Default natural-language DNA entrypoint."),
    ("Skills", "skills/genomilab/SKILL.md", "Host-chaired specialist-board workflow, patient authorization, provider gates, local scientific-executor boundaries, and Research Desk monitoring."),
    ("Skills", "skills/active-genome-index/SKILL.md", "Genome source selection, parsing, and Active Genome Index creation."),
    ("Skills", "skills/variant-evidence/SKILL.md", "Variant, rsID, allele, region, support, and callability questions."),
    ("Skills", "skills/clinvar/SKILL.md", "ClinVar matching, candidate inventory, and clinical-significance triage."),
    ("Skills", "skills/source-research/SKILL.md", "Journal source-review sub-skill for reviewed finding write-back."),
    ("Skills", "skills/rare-disease-cancer/SKILL.md", "Rare disease, hereditary cancer, and cancer risk source investigation."),
    ("Skills", "skills/drug-targets/SKILL.md", "Drug-target and causal pharma gene prioritization."),
    ("Skills", "skills/sequence/SKILL.md", "Supplied-sequence translation, ORF, restriction, Kozak, and primer utilities."),
    ("Skills", "skills/pharmacogenomics/SKILL.md", "Drug response, PharmCAT, ClinPGx, PGxDB, CPIC, DPWG, and FDA PGx evidence."),
    ("Skills", "skills/gwas-catalog/SKILL.md", "GWAS Catalog association-record retrieval and source-field comparison."),
    ("Skills", "skills/functional-genomics/SKILL.md", "Perturbation, dependency, viability, resistance, and screen evidence."),
    ("Skills", "skills/ancestry/SKILL.md", "1000 Genomes GRCh37/GRCh38 PCA projection and qualitative reference-panel similarity."),
    ("Skills", "skills/prs/SKILL.md", "PGS Catalog score discovery, local score import, overlap QC, and raw PRS calculation."),
    ("Skills", "skills/nutrigenomics/SKILL.md", "Declared nutrient-metabolism, food-tolerance, and taste-perception domains with curated single-marker records."),
    ("Skills", "skills/journal/SKILL.md", "Journal and research memory entries, evidence trace links, and reviewed findings."),
    ("Skills", "skills/decode/SKILL.md", "Heavy-kicker for /genomi decode: render the consolidated Genomi Dashboard HTML artifact from gathered panel evidence."),
]


def main() -> None:
    repo_base = os.environ.get("LLMS_REPO_BASE", DEFAULT_REPO_BASE).rstrip("/")
    repo_git = os.environ.get("LLMS_REPO_GIT", DEFAULT_REPO_GIT)
    official_url = os.environ.get("LLMS_OFFICIAL_URL", DEFAULT_OFFICIAL_URL)
    write_llms(repo_base, repo_git, official_url)
    write_llms_full(repo_base, official_url)


def write_llms(repo_base: str, repo_git: str, official_url: str) -> None:
    lines = [
        "# Genomi",
        "",
        "Genomi is an open-source, local-first genomics runtime for AI agents.",
        "It turns private genome sources into Active Genome Index records and exposes deterministic evidence and journal tooling through CLI/MCP.",
        "",
        f"Official URL: {official_url}",
        f"Repo: {repo_git}",
        f"Version: {VERSION}",
        "",
        "## Core rules",
        "",
        "- For installation or setup, read INSTALL_FOR_AGENTS.md first and follow it. Use SKILL.md and focused skill docs for runtime operating rules.",
        "- Direct MCP namespaces are genomi.*, genomilab.*, journal.*, and research.*. Load skills/genomilab/SKILL.md before GenomiLab work. Every other capability tool is reached via genomi.invoke after reading the relevant skills/<capability>/SKILL.md.",
        "- Treat genome source files as optional private context. Public-only genomic questions are valid.",
        "- After genomi.parse_source, use the Active Genome Index for normal future inquiries.",
        "- Use host_response_profiles for optional response-depth preferences; otherwise use the default without asking a standalone style question.",
        "- Derive confidence dynamically from Genomi evidence quality; confidence is not a response-style profile or static default.",
        "- Use variant.resolve as the umbrella deterministic lookup for rsIDs, alleles, loci, regions, and mixed variant text.",
        "",
    ]
    lines.extend(render_doc_map(repo_base))
    lines.extend(
        [
            "",
            "## Single-fetch option",
            "",
            "- llms-full.txt contains this map plus the inlined core docs and skills.",
        ]
    )
    write_text(REPO_ROOT / "llms.txt", "\n".join(lines) + "\n")


def write_llms_full(repo_base: str, official_url: str) -> None:
    lines = [
        "# Genomi — full agent context",
        "",
        "Genomi is an open-source, local-first genomics runtime for AI agents.",
        f"Official URL: {official_url}",
        "",
        "## Agent install directive",
        "",
        "After explaining why Genomi is useful, ask the user whether they want to install it. Obtain explicit current-session approval before installation, genome-file inspection, or searching existing Active Genome Index contexts.",
        "",
        "Follow the inlined INSTALL_FOR_AGENTS.md exactly. Prefer its install paths in order: Genomi MCP `genomi.install` when available, then `genomi install`, then `scripts/install_for_agents.py` only as the documented source-checkout fallback.",
        "",
        "## Documentation map",
        "",
    ]
    lines.extend(render_doc_map(repo_base)[2:])
    for _section, relative_path, _description in DOCS:
        path = REPO_ROOT / relative_path
        lines.extend(
            [
                "",
                "---",
                "",
                f"## Inlined: `{relative_path}`",
                "",
                path.read_text(encoding="utf-8").rstrip(),
            ]
        )
    write_text(REPO_ROOT / "llms-full.txt", "\n".join(lines) + "\n")


def render_doc_map(repo_base: str) -> list[str]:
    lines = ["## Documentation map", ""]
    current_section: str | None = None
    for section, path, description in DOCS:
        if section != current_section:
            lines.extend([f"### {section}", ""])
            current_section = section
        lines.append(f"- [{path}]({repo_base}/{path}): {description}")
    return lines


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
