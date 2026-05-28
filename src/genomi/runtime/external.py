from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DependencyError(RuntimeError):
    """Raised when an external genomics dependency is missing."""


@dataclass(frozen=True)
class ToolCheck:
    name: str
    path: str | None
    available: bool
    version: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "available": self.available,
            "version": self.version,
            "error": self.error,
        }


def check_tool(name: str, version_args: list[str] | None = None) -> ToolCheck:
    path = shutil.which(name)
    if path is None:
        return ToolCheck(name=name, path=None, available=False, error="not found on PATH")
    if not version_args:
        return ToolCheck(name=name, path=path, available=True)
    try:
        completed = subprocess.run(
            [path, *version_args],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return ToolCheck(name=name, path=path, available=True, error=str(exc))
    version_text = (completed.stdout or completed.stderr).strip().splitlines()
    return ToolCheck(
        name=name,
        path=path,
        available=True,
        version=version_text[0] if version_text else None,
        error=None if completed.returncode == 0 else f"version command exited {completed.returncode}",
    )


def check_docker_image(image: str) -> ToolCheck:
    docker = shutil.which("docker")
    if docker is None:
        return ToolCheck(name=f"docker image {image}", path=None, available=False, error="docker not found on PATH")
    completed = subprocess.run(
        [docker, "image", "inspect", image, "--format", "{{.Id}}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        return ToolCheck(
            name=f"docker image {image}",
            path=docker,
            available=False,
            error=(completed.stderr or completed.stdout).strip() or f"docker image inspect exited {completed.returncode}",
        )
    return ToolCheck(
        name=f"docker image {image}",
        path=docker,
        available=True,
        version=completed.stdout.strip(),
    )


def require_tools(checks: list[ToolCheck]) -> None:
    missing = [check.name for check in checks if not check.available]
    if missing:
        raise DependencyError(f"missing required external tool(s): {', '.join(missing)}")


def run_command(command: list[str], *, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {
            "command": command,
            "dry_run": True,
            "returncode": None,
        }
    completed = subprocess.run(command, check=False)
    return {
        "command": command,
        "dry_run": False,
        "returncode": completed.returncode,
    }


def check_returncode(result: dict[str, Any]) -> None:
    returncode = result.get("returncode")
    if returncode not in (0, None):
        command = " ".join(str(part) for part in result.get("command", []))
        raise RuntimeError(f"command failed with exit code {returncode}: {command}")


def file_metadata(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": stat.st_size,
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def write_manifest(path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_manifest(path: str | Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def matching_manifest(
    manifest_path: str | Path,
    expected: dict[str, Any],
    *,
    required_paths: list[str | Path] | None = None,
) -> dict[str, Any] | None:
    manifest = read_manifest(manifest_path)
    if manifest is None:
        return None
    for key, value in expected.items():
        if manifest.get(key) != value:
            return None
    for path in required_paths or []:
        if not Path(path).exists():
            return None
    return manifest


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def dependency_report() -> dict[str, Any]:
    checks = [
        check_tool("bcftools", ["--version"]),
        check_tool("bgzip", ["--version"]),
        check_tool("tabix", ["--version"]),
        check_tool("samtools", ["--version"]),
        check_tool("vep", ["--help"]),
        check_tool("docker", ["--version"]),
        check_docker_image("ensemblorg/ensembl-vep:latest"),
    ]
    return {
        "tools": [check.to_dict() for check in checks],
        "notes": [
            "Normalization is delegated to bcftools norm.",
            "BAM-derived variant materialization is delegated to samtools quickcheck/index and bcftools mpileup/call.",
            "Annotation is delegated to Ensembl VEP.",
            "The Genomi runtime records provenance and parses/imports outputs from these algorithms.",
        ],
    }
