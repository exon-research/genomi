from __future__ import annotations

from pathlib import Path
from typing import Any

from ..runtime.external import (
    check_returncode,
    check_tool,
    file_metadata,
    matching_manifest,
    require_tools,
    run_command,
    utc_now,
    write_manifest,
)
from ..runtime.handoff import evidence_context
from ..runtime.paths import default_normalized_path_for_vcf


def default_normalized_path(vcf_path: str | Path, root: str | Path | None = None) -> Path:
    return default_normalized_path_for_vcf(vcf_path, root=root)


def build_bcftools_norm_command(
    vcf_path: str | Path,
    reference_fasta: str | Path,
    output_path: str | Path,
    *,
    split_multiallelic: bool = True,
    check_ref: str = "s",
    output_type: str | None = None,
    allow_malformed_tags: bool = False,
) -> list[str]:
    output_path = Path(output_path)
    if output_type is None:
        output_type = "z" if output_path.suffix == ".gz" else "v"
    command = [
        "bcftools",
        "norm",
        "--fasta-ref",
        str(reference_fasta),
        "--check-ref",
        check_ref,
        "--output-type",
        output_type,
        "--output",
        str(output_path),
    ]
    if split_multiallelic:
        command.extend(["--multiallelics", "-any"])
    if allow_malformed_tags:
        command.append("--force")
    command.append(str(vcf_path))
    return command


def normalize_vcf(
    vcf_path: str | Path,
    reference_fasta: str | Path,
    output_path: str | Path | None = None,
    *,
    split_multiallelic: bool = True,
    check_ref: str = "s",
    index_output: bool = True,
    allow_malformed_tags: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    vcf_path = Path(vcf_path)
    reference_fasta = Path(reference_fasta)
    output_path = Path(output_path) if output_path is not None else default_normalized_path(vcf_path)

    if not vcf_path.exists():
        raise FileNotFoundError(vcf_path)
    if not reference_fasta.exists():
        raise FileNotFoundError(reference_fasta)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    tool_checks = [check_tool("bcftools", ["--version"])]
    if index_output and output_path.suffix == ".gz":
        tool_checks.append(check_tool("tabix", ["--version"]))
    if not dry_run:
        require_tools(tool_checks)

    norm_command = build_bcftools_norm_command(
        vcf_path,
        reference_fasta,
        output_path,
        split_multiallelic=split_multiallelic,
        check_ref=check_ref,
        allow_malformed_tags=allow_malformed_tags,
    )
    commands: list[list[str]] = [norm_command]
    if index_output and output_path.suffix == ".gz":
        commands.append(["tabix", "--preset", "vcf", str(output_path)])

    manifest_path = f"{output_path}.genomi-manifest.json"
    cache_expected = {
        "step": "normalize",
        "input": file_metadata(vcf_path),
        "reference_fasta": file_metadata(reference_fasta),
        "split_multiallelic": split_multiallelic,
        "check_ref": check_ref,
        "allow_malformed_tags": allow_malformed_tags,
        "tools": [check.to_dict() for check in tool_checks],
        "commands": commands,
        "dry_run": False,
    }
    required_paths: list[Path] = [output_path]
    if index_output and output_path.suffix == ".gz":
        required_paths.append(Path(f"{output_path}.tbi"))
    if not dry_run and not force:
        cached = matching_manifest(manifest_path, cache_expected, required_paths=required_paths)
        if cached is not None:
            return {
                "status": "cached",
                "output": str(output_path),
                "manifest_path": manifest_path,
                "tools": [check.to_dict() for check in tool_checks],
                "commands": commands,
                "results": [],
                "manifest": cached,
                "evidence_context": evidence_context(
                    "static",
                    reason="Normalized alleles are ready for deterministic static-source matching.",
                    commands=["genomi call clinvar.match_variants --params '{\"vcf\":\"<normalized.vcf>\"}'"],
                ),
            }

    results = []
    for command in commands:
        result = run_command(command, dry_run=dry_run)
        check_returncode(result)
        results.append(result)

    manifest = {
        "step": "normalize",
        "created_at_utc": utc_now(),
        "input": file_metadata(vcf_path),
        "reference_fasta": file_metadata(reference_fasta),
        "output": str(output_path),
        "split_multiallelic": split_multiallelic,
        "check_ref": check_ref,
        "allow_malformed_tags": allow_malformed_tags,
        "tools": [check.to_dict() for check in tool_checks],
        "commands": commands,
        "dry_run": dry_run,
    }
    if not dry_run:
        manifest["output_metadata"] = file_metadata(output_path)
        if index_output and output_path.suffix == ".gz":
            manifest["output_index_metadata"] = file_metadata(f"{output_path}.tbi")
        write_manifest(f"{output_path}.genomi-manifest.json", manifest)

    return {
        "status": "planned" if dry_run else "completed",
        "output": str(output_path),
        "manifest_path": None if dry_run else f"{output_path}.genomi-manifest.json",
        "tools": [check.to_dict() for check in tool_checks],
        "commands": commands,
        "results": results,
        "manifest": manifest,
        "evidence_context": evidence_context(
            "static",
            reason="Normalized alleles are ready for deterministic static-source matching.",
            commands=["genomi call clinvar.match_variants --params '{\"vcf\":\"<normalized.vcf>\"}'"],
        ),
    }
