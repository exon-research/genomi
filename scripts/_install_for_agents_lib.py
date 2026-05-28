"""Core metadata, configuration, and host-wiring helpers for the Genomi
agent installer.

This module holds the bulk of the installer implementation so that the
``scripts/install_for_agents.py`` entry point stays small. It is imported both
when the entry point is run as a CLI and when the test suite loads
``scripts/install_for_agents.py`` directly via ``importlib``.

Download/verify/install-library helpers live in
``_install_for_agents_downloads`` to keep every module under the line budget.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

LIBRARIES = {
    "clinvar-grch38": "ClinVar VCF cache for GRCh38",
    "clinvar-grch37": "ClinVar VCF cache for GRCh37",
    "hpo": "HPO phenotype annotation files",
    "gencc": "GenCC gene-disease validity TSV",
    "reference-grch38": "UCSC hg38 reference FASTA and .fai",
    "reference-grch37": "UCSC hg19 reference FASTA and .fai",
    "gencode-grch38": "GENCODE v49 transcript annotation GTF for GRCh38",
    "gencode-grch37": "GENCODE v49lift37 transcript annotation GTF for GRCh37",
    "encode-ccre-grch38": "ENCODE SCREEN candidate cis-regulatory elements BED for GRCh38",
    "panglaodb-markers": "PanglaoDB cell-type marker table",
    "cellmarker-human": "CellMarker 2.0 human marker table normalized for Genomi",
    "msigdb-hallmark": "MSigDB Hallmark GMT from a user-supplied official export",
    "pharmcat": "PharmCAT all-in-one JAR for broad pharmacogenomic calling",
    "ancestry-1000g-30x-grch38": "1000 Genomes 30x GRCh38 compact ancestry PCA panel",
    "liftover-chains": "UCSC liftOver chain files for GRCh37 <-> GRCh38",
    "ancestry-1000g-30x-grch37": "1000 Genomes ancestry PCA panel lifted to GRCh37 (built locally)",
    "minimap2-binary": "minimap2 read aligner (long-read FASTQ → BAM)",
    "bwa-mem2-binary": "bwa-mem2 read aligner (short-read FASTQ → BAM)",
}

# On-disk footprint after install. Surfaced to the user before download so a
# multi-GB pull is not a surprise. Time-to-install depends on the user's
# bandwidth and is left to the host agent to estimate from the size.
LIBRARY_SIZES = {
    "clinvar-grch38": "~180 MB",
    "clinvar-grch37": "~180 MB",
    "hpo": "~100 MB",
    "gencc": "~25 MB",
    "reference-grch38": "~3.2 GB",
    "reference-grch37": "~3.1 GB",
    "gencode-grch38": "~100 MB",
    "gencode-grch37": "~100 MB",
    "encode-ccre-grch38": "~30 MB",
    "panglaodb-markers": "~5 MB",
    "cellmarker-human": "~10 MB",
    "msigdb-hallmark": "user-supplied",
    "pharmcat": "~30 MB",
    "ancestry-1000g-30x-grch38": "~3 MB",
    "liftover-chains": "~3 MB",
    "ancestry-1000g-30x-grch37": "~3 MB",
    "minimap2-binary": "~5 MB",
    "bwa-mem2-binary": "~50 MB",
}

MANUAL_SOURCE_LIBRARIES = {"msigdb-hallmark"}
OPT_IN_LARGE_LIBRARIES: set[str] = set()

# The 1000G ancestry panel is built once by the genomi-ancestry-panel project
# at https://github.com/exon-research/genomi-ancestry-panel and distributed as
# a GitHub release artifact. Bump version + sha256 here when consuming a new
# release. Users can override the source with --ancestry-panel-url (mirror or
# unreleased build) or --ancestry-panel-dir (local prebuilt copy).
ANCESTRY_PANEL_VERSION = "1.0.0"
ANCESTRY_PANEL_TARBALL_URL: str | None = (
    f"https://github.com/exon-research/genomi-ancestry-panel/releases/download/"
    f"v{ANCESTRY_PANEL_VERSION}/panel-1000g-30x-grch38-{ANCESTRY_PANEL_VERSION}.tar.gz"
)
ANCESTRY_PANEL_TARBALL_SHA256: str | None = (
    "6ee6a021ec0bfe66c1808b077e423837c48a8962d09433a2bb4b4c0b5a230cf5"
)
DEFAULT_LIBRARIES = tuple(name for name in LIBRARIES if name not in MANUAL_SOURCE_LIBRARIES | OPT_IN_LARGE_LIBRARIES)
LIBRARY_PURPOSES = {
    "setup-only": (),
    "common-questions": ("clinvar-grch38", "hpo", "gencc"),
    "medication-response": ("clinvar-grch38", "hpo", "gencc", "pharmcat"),
    "ancestry-context": ("ancestry-1000g-30x-grch38",),
    "sequence-and-regions": ("clinvar-grch38", "reference-grch38", "gencode-grch38", "encode-ccre-grch38"),
    "cell-and-tissue": ("panglaodb-markers", "cellmarker-human"),
    "wgs-alignment": (
        "minimap2-binary",
        "bwa-mem2-binary",
        "reference-grch38",
    ),
    "everything": DEFAULT_LIBRARIES,
}

# Pinned aligner releases. Bump the version + sha256 here to ship a newer
# aligner. Linux x86_64 is the only platform currently published by Genomi's
# installer; macOS and ARM builds fall back to `requires_library_install`
# semantics surfaced by the FASTQ parser.
MINIMAP2_VERSION = "2.28"
MINIMAP2_LINUX_X64_URL = (
    f"https://github.com/lh3/minimap2/releases/download/v{MINIMAP2_VERSION}/"
    f"minimap2-{MINIMAP2_VERSION}_x64-linux.tar.bz2"
)
MINIMAP2_LINUX_X64_SHA256 = (
    "51f2cf0e486d0f9f88ace1aa58fdc56571382a676ea0889ae607301c60693377"
)
BWA_MEM2_VERSION = "2.2.1"
BWA_MEM2_LINUX_X64_URL = (
    f"https://github.com/bwa-mem2/bwa-mem2/releases/download/v{BWA_MEM2_VERSION}/"
    f"bwa-mem2-{BWA_MEM2_VERSION}_x64-linux.tar.bz2"
)
BWA_MEM2_LINUX_X64_SHA256 = (
    "b4cfdbce8cc07cdf3f6a920facabc29c976cf77dd53573369508111d6d1c555b"
)

GENCODE_GRCH38_URL = "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_49/gencode.v49.annotation.gtf.gz"
GENCODE_GRCH37_URL = "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_49/GRCh37_mapping/gencode.v49lift37.annotation.gtf.gz"
ENCODE_CCRE_GRCH38_URL = "https://users.moore-lab.org/ENCODE-cCREs/Supplementary-Data/Supplementary-Data-1.GRCh38-cCREs-V4.bed.gz"
PANGLAODB_MARKERS_URL = "https://panglaodb.se/markers/PanglaoDB_markers_27_Mar_2020.tsv.gz"
CELLMARKER_HUMAN_URL = "https://bio-bigdata.hrbmu.edu.cn/CellMarker/CellMarker_download_files/file/Cell_marker_Human.xlsx"
PHARMCAT_RELEASES_API_URL = "https://api.github.com/repos/PharmGKB/PharmCAT/releases/latest"
GENOMI_USER_AGENT = "Genomi installer/0.1 (+https://www.genomiagent.com/)"


def genomi_home_path() -> Path:
    return Path(os.environ.get("GENOMI_HOME") or str(Path("~/.genomi").expanduser())).expanduser().resolve(strict=False)


def install_genomi_command_shim() -> Path:
    """Install a stable `genomi` launcher independent of pip's script dir."""

    genomi_home = genomi_home_path()
    bin_dir = genomi_home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "genomi"
    python = Path(sys.executable).expanduser().resolve(strict=False)
    runtime_update = ""
    if (REPO_ROOT / ".git").is_dir():
        update_command = (
            f"git -C {shlex.quote(str(REPO_ROOT))} pull --ff-only origin master "
            f"&& {shlex.quote(str(python))} -m pip install -e {shlex.quote(str(REPO_ROOT))}"
        )
        runtime_update = (
            'if [ -z "${GENOMI_RUNTIME_UPDATE+x}" ]; then\n'
            f"  export GENOMI_RUNTIME_UPDATE={shlex.quote(update_command)}\n"
            "fi\n"
        )
    content = (
        "#!/usr/bin/env sh\n"
        f"export GENOMI_HOME={shlex.quote(str(genomi_home))}\n"
        f"{runtime_update}"
        f"exec {shlex.quote(str(python))} -m genomi \"$@\"\n"
    )
    shim.write_text(content, encoding="utf-8")
    shim.chmod(0o755)
    return shim


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install Genomi for agent use.")
    parser.add_argument(
        "--libraries",
        help=(
            "Public data purpose to install, or exact comma-separated library IDs. "
            f"Purposes: {', '.join(LIBRARY_PURPOSES)}. Library IDs: {', '.join(LIBRARIES)}."
        ),
    )
    parser.add_argument("--skip-package", action="store_true", help="Skip editable package installation.")
    parser.add_argument("--skip-verify", action="store_true", help="Skip post-install verification commands.")
    parser.add_argument("--genomi-home", help="Set GENOMI_HOME for installed libraries and runtime state.")
    parser.add_argument("--force", action="store_true", help="Refresh selected library downloads when supported.")
    parser.add_argument(
        "--msigdb-gmt",
        help="Path to an official MSigDB Hallmark GMT export to copy when msigdb-hallmark is selected.",
    )
    parser.add_argument(
        "--msigdb-gmt-url",
        help="Download URL for an official MSigDB Hallmark GMT export when msigdb-hallmark is selected.",
    )
    parser.add_argument(
        "--pharmcat-version",
        help=(
            "Pin a specific PharmCAT release tag (e.g. 'v2.15.5'). When omitted, "
            "the installer queries GitHub for the latest stable release."
        ),
    )
    parser.add_argument(
        "--ancestry-panel-dir",
        help="Copy a prebuilt compact ancestry panel directory instead of downloading the released tarball.",
    )
    parser.add_argument(
        "--ancestry-panel-url",
        help="Override the ancestry panel tarball URL (escape hatch for mirrors or unreleased builds).",
    )
    parser.add_argument(
        "--genome-source",
        help="Optional genome source to import after setup, such as VCF, gVCF, BAM, 23andMe, or AncestryDNA raw data.",
    )
    parser.add_argument(
        "--user-nickname",
        default=None,
        help=(
            "User/profile nickname for --genome-source. Defaults to 'Default user' only when no "
            "users exist. Required when users already exist."
        ),
    )
    parser.add_argument(
        "--set-default-user",
        action="store_true",
        help="Make the user/profile the default auto-selected user.",
    )
    parser.add_argument(
        "--host-skill-dir",
        action="append",
        default=None,
        help=(
            "Install the Genomi host-agent skill into this skills directory. "
            "Can be repeated. Defaults to auto-detecting common host and "
            "shared Agent Skills directories when they already exist."
        ),
    )
    parser.add_argument(
        "--skip-host-skill",
        action="store_true",
        help="Do not install the Genomi host-agent skill.",
    )
    return parser.parse_args(argv)


def resolve_library_selection(value: str | None) -> list[str]:
    if value is None:
        raise SystemExit(
            "Library selection requires an explicit --libraries value. "
            f"Pass one exact purpose ({', '.join(LIBRARY_PURPOSES)}) or exact library IDs."
        )
    return parse_library_selection(value)


def parse_library_selection(value: str) -> list[str]:
    cleaned = value.strip().lower()
    if not cleaned:
        raise SystemExit(
            f"Choose one exact purpose ({', '.join(LIBRARY_PURPOSES)}) or exact library IDs."
        )
    if cleaned in LIBRARY_PURPOSES:
        return list(LIBRARY_PURPOSES[cleaned])

    selected: list[str] = []
    invalid: list[str] = []
    for token in cleaned.split(","):
        item = token.strip()
        if not item:
            continue
        name = item
        if name not in LIBRARIES:
            invalid.append(item)
            continue
        if name not in selected:
            selected.append(name)
    if invalid:
        expected = ", ".join([*LIBRARY_PURPOSES, *LIBRARIES])
        raise SystemExit(
            f"Unknown library selection: {', '.join(invalid)}. "
            f"Expected one exact purpose or exact library IDs: {expected}"
        )
    return selected


HOST_AGENT_SKILL_DIR = REPO_ROOT
CAPABILITY_SKILLS_ROOT = REPO_ROOT / "skills"
CAPABILITY_SKILL_DIRS_TO_SKIP = frozenset({"host-agent", "conventions"})
# Host-agent skill directories that follow the Anthropic SKILL.md convention.
# Hosts differ in how they invoke installed skills, so the installer only links
# SKILL.md into known skill directories. Invocation must come from the active
# host's own skill list/help instead of being inferred from a directory name.
DEFAULT_HOST_SKILL_PARENTS = (
    Path("~/.claude/skills"),
    Path("~/.codex/skills"),
    Path("~/.openclaw/skills"),
    Path("~/.hermes/skills"),
    Path("~/.agents/skills"),
)


def install_host_agent_skill(args: argparse.Namespace) -> None:
    """Symlink the in-repo Genomi skill into each detected host-agent skills dir.

    Symlinks (rather than copies) so updates to the canonical skill in the
    Genomi repo propagate to every host without re-running the installer.
    """
    if getattr(args, "skip_host_skill", False):
        return
    if not HOST_AGENT_SKILL_DIR.is_dir() or not (HOST_AGENT_SKILL_DIR / "SKILL.md").is_file():
        print(
            f"Skipping host-agent skill: canonical source not found at {HOST_AGENT_SKILL_DIR}",
            file=sys.stderr,
        )
        return

    raw_targets = getattr(args, "host_skill_dir", None)
    if raw_targets:
        parents = [Path(p).expanduser() for p in raw_targets]
    else:
        parents = [p.expanduser() for p in DEFAULT_HOST_SKILL_PARENTS if p.expanduser().exists()]

    if not parents:
        print(
            "No host-agent skill directories detected. "
            "Pass --host-skill-dir <path> to install the Genomi skill explicitly, "
            "or --skip-host-skill to silence this notice.",
            file=sys.stderr,
        )
        return

    source = HOST_AGENT_SKILL_DIR.resolve()
    installed_any = False
    for parent in parents:
        link = parent / "genomi"
        parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            if link.resolve() == source:
                print(f"Genomi host skill already linked: {link} -> {source}")
                installed_any = True
                continue
            link.unlink()
        elif link.exists():
            if getattr(args, "force", False):
                shutil.rmtree(link)
            else:
                print(
                    f"Skipping {link}: a non-symlink directory or file already exists. "
                    "Pass --force to replace it.",
                    file=sys.stderr,
                )
                continue
        link.symlink_to(source, target_is_directory=True)
        print(f"Genomi host skill installed: {link} -> {source}")
        installed_any = True
    if installed_any:
        print("Host skill invocation:")
        print("  Invocation is controlled by the active host, not by this installer.")
        print("  Ask the host to list installed skills, then use that host's documented skill syntax.")
        print("  Do not assume /genomi works in every host.")
    install_capability_skills(args)


def _capability_skill_sources() -> list[tuple[str, Path]]:
    """Return (capability_name, abs_skill_dir) for every per-capability skill."""
    out: list[tuple[str, Path]] = []
    if not CAPABILITY_SKILLS_ROOT.is_dir():
        return out
    for entry in sorted(CAPABILITY_SKILLS_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in CAPABILITY_SKILL_DIRS_TO_SKIP:
            continue
        if not (entry / "SKILL.md").is_file():
            continue
        out.append((entry.name, entry.resolve()))
    return out


def install_capability_skills(args: argparse.Namespace) -> None:
    """Symlink each per-capability skill dir into every detected host skill dir.

    Per-capability skills (e.g. ``skills/decode``, ``skills/clinvar``) land at
    ``~/.claude/skills/genomi-<name>/`` so the host's skill matcher can read
    each one's ``description:`` frontmatter and route on it. The monolithic
    ``~/.claude/skills/genomi`` skill remains as the umbrella entry.
    """
    if getattr(args, "skip_host_skill", False):
        return
    sources = _capability_skill_sources()
    if not sources:
        return

    raw_targets = getattr(args, "host_skill_dir", None)
    if raw_targets:
        parents = [Path(p).expanduser() for p in raw_targets]
    else:
        parents = [p.expanduser() for p in DEFAULT_HOST_SKILL_PARENTS if p.expanduser().exists()]
    if not parents:
        return

    force = bool(getattr(args, "force", False))
    installed = 0
    for parent in parents:
        parent.mkdir(parents=True, exist_ok=True)
        for cap_name, cap_source in sources:
            link = parent / f"genomi-{cap_name}"
            if link.is_symlink():
                if link.resolve() == cap_source:
                    installed += 1
                    continue
                link.unlink()
            elif link.exists():
                if force:
                    shutil.rmtree(link)
                else:
                    print(
                        f"Skipping {link}: non-symlink already exists. "
                        "Pass --force to replace it.",
                        file=sys.stderr,
                    )
                    continue
            link.symlink_to(cap_source, target_is_directory=True)
            installed += 1
    if installed:
        print(f"Genomi per-capability skills linked: {installed} symlinks across {len(parents)} host dir(s).")


def configure_genome_source(args: argparse.Namespace) -> None:
    source = args.genome_source
    user_nickname = args.user_nickname.strip() if args.user_nickname else None
    set_default_user = bool(args.set_default_user)

    if not source:
        return

    source_path = Path(source).expanduser()
    if not source_path.exists():
        raise SystemExit(f"Genome source does not exist: {source_path}")
    _ensure_src_on_path()
    existing_users = _load_existing_users()
    user_nickname = resolve_genome_source_user_nickname(
        user_nickname,
        existing_users=existing_users,
    )
    from genomi.operations import call_operation

    print(f"Importing genome source as Active Genome Index: {source_path}")
    params = {
        "source": str(source_path),
        "user_nickname": user_nickname,
        "set_default_user": set_default_user,
    }
    result = call_operation("genomi.parse_source", params)
    active = result.get("active_genome_index") if isinstance(result, dict) else {}
    if isinstance(active, dict):
        default = " [default user]" if set_default_user else ""
        print(f"  Active Genome Index: {active.get('agi_id') or '(unknown)'} for {user_nickname}{default}")
    print_summary(result if isinstance(result, dict) else {"status": "completed", "output": ""})


def _ensure_src_on_path() -> None:
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))


def _load_existing_users() -> list[dict[str, object]]:
    _ensure_src_on_path()
    from genomi.runtime import context as runtime_context

    return [user for user in runtime_context.list_users() if isinstance(user, dict)]


def resolve_genome_source_user_nickname(
    provided_nickname: str | None,
    *,
    existing_users: list[dict[str, object]],
) -> str:
    nickname = (provided_nickname or "").strip()
    if nickname:
        return nickname
    if not existing_users:
        return "Default user"
    raise SystemExit(
        "GENOMI_HOME already has users. Pass --user-nickname to assign this genome source "
        "to an existing user or a new user."
    )


def print_summary(payload: dict[str, object]) -> None:
    status = payload.get("status") or "completed"
    output = payload.get("output") or payload.get("manifest_path") or ""
    print(f"  {status}: {output}")
