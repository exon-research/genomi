from __future__ import annotations

from pathlib import Path
from typing import Any

from ...runtime.external import (
    check_docker_image,
    check_returncode,
    check_tool,
    file_metadata,
    require_tools,
    run_command,
    utc_now,
    write_manifest,
)
from ...runtime.handoff import evidence_context

DEFAULT_VEP_DOCKER_IMAGE = "ensemblorg/ensembl-vep:latest"


def default_annotation_path(vcf_path: str | Path) -> Path:
    path = Path(vcf_path)
    return path.with_suffix(path.suffix + ".vep.vcf")


def build_vep_command(
    vcf_path: str | Path,
    output_path: str | Path,
    *,
    assembly: str = "GRCh38",
    cache_dir: str | Path | None = None,
    offline: bool = True,
    fork: int = 1,
    force_overwrite: bool = False,
    everything: bool = False,
) -> list[str]:
    command = [
        "vep",
        "--input_file",
        str(vcf_path),
        "--output_file",
        str(output_path),
        "--vcf",
        "--assembly",
        assembly,
        "--cache",
        "--fork",
        str(fork),
        "--symbol",
        "--canonical",
        "--mane",
        "--protein",
        "--biotype",
        "--variant_class",
        "--hgvs",
    ]
    if offline:
        command.append("--offline")
    if cache_dir is not None:
        command.extend(["--dir_cache", str(cache_dir)])
    if force_overwrite:
        command.append("--force_overwrite")
    if everything:
        command.append("--everything")
    return command


def build_vep_docker_command(
    vcf_path: str | Path,
    output_path: str | Path,
    *,
    assembly: str = "GRCh38",
    cache_dir: str | Path | None = None,
    offline: bool = True,
    fork: int = 1,
    force_overwrite: bool = False,
    everything: bool = False,
    image: str = DEFAULT_VEP_DOCKER_IMAGE,
) -> list[str]:
    vcf_path = Path(vcf_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    input_mount = "/input"
    output_mount = "/output"
    container_input = f"{input_mount}/{vcf_path.name}"
    container_output = f"{output_mount}/{output_path.name}"
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{vcf_path.parent}:{input_mount}:ro",
        "-v",
        f"{output_path.parent}:{output_mount}",
    ]
    container_cache = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir).resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        container_cache = "/cache"
        command.extend(["-v", f"{cache_dir}:{container_cache}"])
    command.append(image)
    command.extend(
        build_vep_command(
            container_input,
            container_output,
            assembly=assembly,
            cache_dir=container_cache,
            offline=offline,
            fork=fork,
            force_overwrite=force_overwrite,
            everything=everything,
        )
    )
    return command


def annotate_vcf(
    vcf_path: str | Path,
    output_path: str | Path | None = None,
    *,
    assembly: str = "GRCh38",
    cache_dir: str | Path | None = None,
    offline: bool = True,
    fork: int = 1,
    force_overwrite: bool = False,
    everything: bool = False,
    runner: str = "local",
    docker_image: str = DEFAULT_VEP_DOCKER_IMAGE,
    dry_run: bool = False,
) -> dict[str, Any]:
    vcf_path = Path(vcf_path)
    output_path = Path(output_path) if output_path is not None else default_annotation_path(vcf_path)
    if not vcf_path.exists():
        raise FileNotFoundError(vcf_path)
    if runner not in ("local", "docker"):
        raise ValueError("runner must be 'local' or 'docker'")
    if runner == "local" and offline and cache_dir is not None and not Path(cache_dir).exists():
        raise FileNotFoundError(cache_dir)

    tool_checks = [check_tool("vep", ["--help"])] if runner == "local" else [check_tool("docker", ["--version"]), check_docker_image(docker_image)]
    if not dry_run:
        require_tools(tool_checks)

    if runner == "docker":
        command = build_vep_docker_command(
            vcf_path,
            output_path,
            assembly=assembly,
            cache_dir=cache_dir,
            offline=offline,
            fork=fork,
            force_overwrite=force_overwrite,
            everything=everything,
            image=docker_image,
        )
    else:
        command = build_vep_command(
            vcf_path,
            output_path,
            assembly=assembly,
            cache_dir=cache_dir,
            offline=offline,
            fork=fork,
            force_overwrite=force_overwrite,
            everything=everything,
        )
    result = run_command(command, dry_run=dry_run)
    check_returncode(result)

    manifest = {
        "step": "annotate-vep",
        "created_at_utc": utc_now(),
        "input": file_metadata(vcf_path),
        "output": str(output_path),
        "assembly": assembly,
        "cache_dir": str(cache_dir) if cache_dir is not None else None,
        "offline": offline,
        "fork": fork,
        "everything": everything,
        "runner": runner,
        "docker_image": docker_image if runner == "docker" else None,
        "tools": [check.to_dict() for check in tool_checks],
        "commands": [command],
        "dry_run": dry_run,
    }
    if not dry_run:
        manifest["output_metadata"] = file_metadata(output_path)
        write_manifest(f"{output_path}.genomi-manifest.json", manifest)

    return {
        "status": "planned" if dry_run else "completed",
        "output": str(output_path),
        "manifest_path": None if dry_run else f"{output_path}.genomi-manifest.json",
        "tools": [check.to_dict() for check in tool_checks],
        "commands": [command],
        "results": [result],
        "manifest": manifest,
        "evidence_context": evidence_context(
            "static",
            reason="VEP annotation is deterministic annotation context; continue with static structuring or target-scoped research.",
            commands=[
                "genomi call genomi.parse_source --params '{\"source\":\"<vcf>\"}'",
                "genomi call research.build_target_packet --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"gene\",\"gene\":\"<gene>\"}'",
            ],
        ),
    }
