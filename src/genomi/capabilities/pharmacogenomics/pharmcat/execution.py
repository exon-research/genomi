from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ....active_genome_index.export import export_variants
from ....active_genome_index.active_genome_index import default_active_genome_index_path
from ....runtime.paths import run_work_dir, vcf_content_hash
from .. import pgx_outside_calls
from ._common import (
    JsonObject,
    PHARMCAT_DOCS,
    PHARMCAT_RUN_SCHEMA,
    PHARMCAT_STATUS_SCHEMA,
    _clean_base_filename,
    _tail,
    sqlite_error_cls,
)
from .artifacts import _summarize_outputs
from .preflight import _input_preflight
from .record_payloads import (
    _readiness,
    _record_payloads_from_calls,
    _record_payloads_from_match,
    _record_payloads_from_phenotype,
    _record_payloads_from_report,
)


def pharmcat_status(
    *,
    mode: str = "auto",
    pipeline_command: str | Path | None = None,
    pharmcat_jar: str | Path | None = None,
    java_command: str | Path | None = None,
    timeout_seconds: int = 15,
) -> JsonObject:
    selected = _select_execution_mode(
        mode=mode,
        pipeline_command=pipeline_command,
        pharmcat_jar=pharmcat_jar,
        java_command=java_command,
    )
    version = _version_probe(selected, timeout_seconds=timeout_seconds)
    available = selected.get("mode") != "unavailable"
    version_ok = version.get("status") in {"completed", "skipped"}
    status = "available" if available else "tool_unavailable"
    return {
        "schema": PHARMCAT_STATUS_SCHEMA,
        "ok": bool(available and version_ok),
        "status": status,
        "availability": selected,
        "version_probe": version,
        "traceability": {
            "source_tool": "PharmCAT",
            "definition_and_guideline_sources": PHARMCAT_DOCS,
        },
    }


def pharmcat_preflight(*, vcf: str | Path) -> JsonObject:
    """Inspect VCF structure needed for broad PharmCAT PGx calling without running PharmCAT."""

    vcf_path = Path(vcf).expanduser()
    if not vcf_path.exists():
        return {
            "schema": "genomi-pharmcat-preflight-v1",
            "ok": False,
            "status": "missing_vcf",
            "input": {"hidden_intake_source": True},
            "message": "Select an Active Genome Index or provide a genome source path.",
            "traceability": {
                "source_tool": "PharmCAT",
                "definition_and_guideline_sources": PHARMCAT_DOCS,
            },
        }
    preflight = _input_preflight(vcf_path)
    return {
        "schema": "genomi-pharmcat-preflight-v1",
        "ok": preflight.get("status") == "completed",
        "status": preflight.get("status") or "unknown",
        "input_preflight": preflight,
        "traceability": {
            "source_tool": "PharmCAT",
            "definition_and_guideline_sources": PHARMCAT_DOCS,
        },
    }


def run_pharmcat(
    *,
    vcf: str | Path,
    output_dir: str | Path | None = None,
    base_filename: str | None = None,
    mode: str = "auto",
    pipeline_command: str | Path | None = None,
    pharmcat_jar: str | Path | None = None,
    java_command: str | Path | None = None,
    sample: str | None = None,
    sample_file: str | Path | None = None,
    sample_metadata: str | Path | None = None,
    outside_call_file: str | Path | None = None,
    reporter_sources: str | None = None,
    research_mode: str | None = None,
    max_memory: str | None = None,
    max_concurrent_processes: int | None = None,
    include_reporter_json: bool = True,
    include_calls_only_tsv: bool = True,
    probe_version: bool = True,
    dry_run: bool = False,
    timeout_seconds: int = 7200,
) -> JsonObject:
    """Run a local PharmCAT installation against a VCF and summarize artifacts."""

    vcf_path = Path(vcf).expanduser()
    if not vcf_path.exists():
        return {
            **_base_result(
                ok=False,
                status="missing_vcf",
                vcf_path=vcf_path,
                output_dir=output_dir,
                base_filename=base_filename,
                message="Select an Active Genome Index or provide a genome source path.",
            ),
        }

    out_dir = Path(output_dir).expanduser() if output_dir else run_work_dir(vcf_path) / "pharmcat"
    base = _selected_base_filename(base_filename, vcf_path)
    selected = _select_execution_mode(
        mode=mode,
        pipeline_command=pipeline_command,
        pharmcat_jar=pharmcat_jar,
        java_command=java_command,
    )
    version = _version_probe(selected, timeout_seconds=15) if probe_version else {"status": "skipped"}
    outside_call_validation = (
        pgx_outside_calls.validate_outside_call_file(outside_call_file)
        if outside_call_file
        else {"schema": pgx_outside_calls.OUTSIDE_CALL_SCHEMA, "ok": True, "status": "not_supplied"}
    )
    # Early gates that don't require touching the Active Genome Index or the intake source:
    # tool availability and outside-call validity. Surface these first so the
    # agent gets the right structured error without us needing to look at any
    # genomic data.
    if outside_call_file and not outside_call_validation.get("ok"):
        return {
            **_base_result(ok=False, status="invalid_outside_call_file", vcf_path=vcf_path, output_dir=out_dir, base_filename=base),
            "outside_call_validation": outside_call_validation,
            "warnings": list(outside_call_validation.get("warnings") or []),
        }
    if selected.get("mode") in {"unavailable", None}:
        return _unavailable_result(
            vcf_path=vcf_path,
            output_dir=out_dir,
            base_filename=base,
            selected=selected,
            sample=sample,
            sample_file=sample_file,
            sample_metadata=sample_metadata,
            input_preflight={"schema": "genomi-pharmcat-input-preflight-v1", "status": "skipped_tool_unavailable"},
            outside_call_validation=outside_call_validation,
            vcf_normalization={"status": "skipped_tool_unavailable", "intake_path_hidden": True},
        )

    input_preflight = _input_preflight(vcf_path)
    vcf_normalization = _prepare_pharmcat_input(
        vcf_path=vcf_path,
        out_dir=out_dir,
        base_filename=base,
        input_preflight=input_preflight,
        selected_mode=selected.get("mode"),
        dry_run=dry_run,
    )
    surfaced_vcf_normalization = _surface_vcf_normalization(vcf_normalization)
    # Genomi contract: never read the raw intake post-parse. If the Active
    # Active Genome Index export failed or no Active Genome Index exists, surface a
    # structured error instead of silently falling back to the user's intake VCF.
    if not vcf_normalization.get("remediated") or not vcf_normalization.get("input_path"):
        prep_status = str(vcf_normalization.get("status") or "active_genome_index_input_unavailable")
        return {
            **_base_result(ok=False, status=prep_status, vcf_path=vcf_path, output_dir=out_dir, base_filename=base),
            "input_preflight": input_preflight,
            "vcf_normalization": surfaced_vcf_normalization,
            "outside_call_validation": outside_call_validation,
            "warnings": list(vcf_normalization.get("warnings") or []),
        }
    matcher_vcf = Path(vcf_normalization["input_path"])
    command = _build_command(
        selected=selected,
        vcf_path=matcher_vcf,
        output_dir=out_dir,
        base_filename=base,
        sample=sample,
        sample_file=sample_file,
        sample_metadata=sample_metadata,
        outside_call_file=outside_call_file,
        reporter_sources=reporter_sources,
        research_mode=research_mode,
        max_memory=max_memory,
        max_concurrent_processes=max_concurrent_processes,
        include_reporter_json=include_reporter_json,
        include_calls_only_tsv=include_calls_only_tsv,
    )
    warnings = _command_warnings(selected=selected, outside_call_file=outside_call_file)
    warnings.extend(outside_call_validation.get("warnings") or [])
    warnings.extend(vcf_normalization.get("warnings") or [])
    if command is None:
        return _unavailable_result(
            vcf_path=vcf_path,
            output_dir=out_dir,
            base_filename=base,
            selected=selected,
            sample=sample,
            sample_file=sample_file,
            sample_metadata=sample_metadata,
            input_preflight=input_preflight,
            outside_call_validation=outside_call_validation,
            vcf_normalization=surfaced_vcf_normalization,
        )

    private_paths = [vcf_path]
    if matcher_vcf != vcf_path:
        private_paths.append(matcher_vcf)
    for private_value in (outside_call_file, sample_file, sample_metadata):
        if private_value:
            private_paths.append(Path(private_value).expanduser())
    redacted_command = _redact_command(command, private_paths)
    if dry_run:
        return {
            **_base_result(ok=True, status="planned", vcf_path=vcf_path, output_dir=out_dir, base_filename=base),
            "input_preflight": input_preflight,
            "vcf_normalization": surfaced_vcf_normalization,
            "outside_call_validation": outside_call_validation,
            "execution": {
                "mode": selected["mode"],
                "command": redacted_command,
                "dry_run": True,
                "timeout_seconds": int(timeout_seconds),
                "version_probe": version,
            },
            "warnings": warnings,
            "artifacts": _summarize_outputs(out_dir, base),
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    timeout = max(1, min(int(timeout_seconds or 7200), 604800))
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            **_base_result(ok=False, status="timeout", vcf_path=vcf_path, output_dir=out_dir, base_filename=base),
            "input_preflight": input_preflight,
            "vcf_normalization": surfaced_vcf_normalization,
            "outside_call_validation": outside_call_validation,
            "execution": {
                "mode": selected["mode"],
                "command": redacted_command,
                "returncode": None,
                "timeout_seconds": timeout,
                "version_probe": version,
                "stdout_tail": _tail(exc.stdout),
                "stderr_tail": _tail(exc.stderr),
            },
            "artifacts": _summarize_outputs(out_dir, base),
            "warnings": warnings,
        }

    artifacts = _summarize_outputs(out_dir, base)
    record_payloads = [
        *_record_payloads_from_calls(artifacts.get("calls_only") or {}),
        *_record_payloads_from_match(artifacts.get("named_allele_match_json") or {}),
        *_record_payloads_from_phenotype(artifacts.get("phenotype_json") or {}),
        *_record_payloads_from_report(artifacts.get("report_json") or {}),
    ]
    return {
        **_base_result(
            ok=completed.returncode == 0,
            status="completed" if completed.returncode == 0 else "failed",
            vcf_path=vcf_path,
            output_dir=out_dir,
            base_filename=base,
        ),
        "input_preflight": input_preflight,
        "vcf_normalization": vcf_normalization,
        "outside_call_validation": outside_call_validation,
        "execution": {
            "mode": selected["mode"],
            "command": redacted_command,
            "returncode": completed.returncode,
            "timeout_seconds": timeout,
            "version_probe": version,
            "stdout_tail": _tail(completed.stdout),
            "stderr_tail": _tail(completed.stderr),
        },
        "artifacts": artifacts,
        "warnings": warnings,
        "record_research_payloads": record_payloads,
        "interpretation_readiness": _readiness(completed.returncode, artifacts),
    }


def _select_execution_mode(
    *,
    mode: str,
    pipeline_command: str | Path | None,
    pharmcat_jar: str | Path | None,
    java_command: str | Path | None,
) -> JsonObject:
    requested = str(mode or "auto").strip().lower()
    pipeline = _resolve_executable(pipeline_command, default_name="pharmcat_pipeline")
    jar = _resolve_jar(pharmcat_jar)
    java = _resolve_executable(java_command, default_name="java")
    if requested == "pipeline":
        return {"mode": "pipeline", "pipeline_command": pipeline, "pharmcat_jar": jar, "java_command": java}
    if requested == "jar":
        return {"mode": "jar", "pipeline_command": pipeline, "pharmcat_jar": jar, "java_command": java}
    if pipeline:
        return {"mode": "pipeline", "pipeline_command": pipeline, "pharmcat_jar": jar, "java_command": java}
    if jar and java:
        return {"mode": "jar", "pipeline_command": pipeline, "pharmcat_jar": jar, "java_command": java}
    return {"mode": "unavailable", "pipeline_command": pipeline, "pharmcat_jar": jar, "java_command": java}


def _version_probe(selected: JsonObject, *, timeout_seconds: int) -> JsonObject:
    command = _version_command(selected)
    if command is None:
        return {"status": "skipped", "reason": "pharmcat executable unavailable"}
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(1, min(int(timeout_seconds or 15), 120)),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "command": command,
            "returncode": None,
            "stdout_tail": _tail(exc.stdout),
            "stderr_tail": _tail(exc.stderr),
        }
    except OSError as exc:
        return {"status": "failed", "command": command, "error": str(exc)}
    return {
        "status": "completed" if completed.returncode == 0 else "failed",
        "command": command,
        "returncode": completed.returncode,
        "stdout_tail": _tail(completed.stdout, max_chars=1200),
        "stderr_tail": _tail(completed.stderr, max_chars=1200),
        "version_text": _version_text(completed.stdout, completed.stderr),
    }


def _version_command(selected: JsonObject) -> list[str] | None:
    if selected.get("mode") == "pipeline" and selected.get("pipeline_command"):
        return [str(selected["pipeline_command"]), "-V"]
    if selected.get("mode") == "jar" and selected.get("pharmcat_jar") and selected.get("java_command"):
        return [str(selected["java_command"]), "-jar", str(selected["pharmcat_jar"]), "-V"]
    return None


def _version_text(stdout: str | None, stderr: str | None) -> str | None:
    text = "\n".join(value.strip() for value in [stdout or "", stderr or ""] if value and value.strip())
    if not text:
        return None
    return text.splitlines()[0][:400]


def _build_command(
    *,
    selected: JsonObject,
    vcf_path: Path,
    output_dir: Path,
    base_filename: str,
    sample: str | None,
    sample_file: str | Path | None,
    sample_metadata: str | Path | None,
    outside_call_file: str | Path | None,
    reporter_sources: str | None,
    research_mode: str | None,
    max_memory: str | None,
    max_concurrent_processes: int | None,
    include_reporter_json: bool,
    include_calls_only_tsv: bool,
) -> list[str] | None:
    mode = selected.get("mode")
    if mode == "pipeline":
        command = [str(selected["pipeline_command"]), str(vcf_path), "-o", str(output_dir), "-bf", base_filename]
        if include_reporter_json:
            command.append("-reporterJson")
        if include_calls_only_tsv:
            command.append("-reporterCallsOnlyTsv")
        if max_memory:
            command.extend(["-cm", str(max_memory)])
    elif mode == "jar" and selected.get("pharmcat_jar") and selected.get("java_command"):
        command = [str(selected["java_command"])]
        if max_memory:
            command.append(f"-Xmx{max_memory}")
        command.extend(["-jar", str(selected["pharmcat_jar"]), "-vcf", str(vcf_path), "-o", str(output_dir), "-bf", base_filename])
        if include_reporter_json:
            command.append("-reporterJson")
        if include_calls_only_tsv:
            command.append("-reporterCallsOnlyTsv")
    else:
        return None
    if sample:
        command.extend(["-s", str(sample)])
    if sample_file:
        command.extend(["-S", str(Path(sample_file).expanduser())])
    if sample_metadata:
        command.extend(["-sm", str(Path(sample_metadata).expanduser())])
    if outside_call_file and selected.get("mode") == "jar":
        command.extend(["-po", str(Path(outside_call_file).expanduser())])
    if reporter_sources:
        command.extend(["-rs", str(reporter_sources)])
    if research_mode:
        command.extend(["-research", str(research_mode)])
    if max_concurrent_processes is not None:
        command.extend(["-cp", str(int(max_concurrent_processes))])
    return command


def _command_warnings(*, selected: JsonObject, outside_call_file: str | Path | None) -> list[JsonObject]:
    warnings = []
    if outside_call_file and selected.get("mode") == "pipeline":
        warnings.append(
            {
                "code": "pipeline_outside_call_naming",
                "message": (
                    "pharmcat_pipeline discovers outside calls by filename next to the VCF. "
                    "Use PharmCAT jar mode for an explicit outside_call_file parameter."
                ),
            }
        )
    return warnings


def _unavailable_result(
    *,
    vcf_path: Path,
    output_dir: Path,
    base_filename: str,
    selected: JsonObject,
    sample: str | None,
    sample_file: str | Path | None,
    sample_metadata: str | Path | None,
    input_preflight: JsonObject,
    outside_call_validation: JsonObject,
    vcf_normalization: JsonObject | None = None,
) -> JsonObject:
    example = ["pharmcat_pipeline", "[hidden_intake_source]", "-o", str(output_dir), "-bf", base_filename, "-reporterJson", "-reporterCallsOnlyTsv"]
    if sample:
        example.extend(["-s", str(sample)])
    if sample_file:
        example.extend(["-S", "[hidden_intake_source]"])
    if sample_metadata:
        example.extend(["-sm", "[hidden_intake_source]"])
    return {
        **_base_result(ok=False, status="tool_unavailable", vcf_path=vcf_path, output_dir=output_dir, base_filename=base_filename),
        "input_preflight": input_preflight,
        "vcf_normalization": vcf_normalization or {"status": "not_evaluated"},
        "outside_call_validation": outside_call_validation,
        "availability": selected,
        "execution": {
            "version_probe": _version_probe(selected, timeout_seconds=15),
        },
        "suggested_command": example,
    }


def _prepare_pharmcat_input(
    *,
    vcf_path: Path,
    out_dir: Path,
    base_filename: str,
    input_preflight: JsonObject,
    selected_mode: str | None,
    dry_run: bool,
) -> JsonObject:
    """Produce a PharmCAT-compatible VCF derived from the Active Genome Index.

    Genomi's contract: only `genomi.parse_source` is permitted to read the
    raw intake source. Every downstream capability — including PharmCAT —
    consumes the Active Genome Index. This step therefore always exports a
    PharmCAT-shaped VCF (chr-prefixed chromosomes, PASS-only records, canonical
    primary contigs) from the Active Genome Index, regardless of what the intake looked like. The
    intake VCF is never handed to the matcher.
    """

    active_genome_index_path = default_active_genome_index_path(vcf_path)
    if not Path(active_genome_index_path).exists():
        return {
            "status": "requires_active_genome_index",
            "remediated": False,
            "method": "active_genome_index_export",
            "intake_path_hidden": True,
            "reason": (
                "No Active Genome Index found for the intake source; PharmCAT "
                "input must be derived from the Active Genome Index. "
                "Run genomi.parse_source first."
            ),
            "next_actions": [
                {
                    "operation": "genomi.parse_source",
                    "reason": "Build the Active Genome Index that PharmCAT will read from.",
                }
            ],
        }

    if dry_run:
        return {
            "status": "planned",
            "remediated": True,
            "method": "active_genome_index_export",
            "input_path": str(out_dir / f"{base_filename}.pharmcat-input.vcf"),
            "intake_path_hidden": True,
            "reason": "dry_run skipped the Active Genome Index export write; matcher would read the Active Genome Index-derived VCF below.",
            "would_apply": {
                "chrom_style": "chr",
                "pass_only": True,
                "primary_contigs_only": True,
            },
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    normalized_path = out_dir / f"{base_filename}.pharmcat-input.vcf"
    try:
        export = export_variants(
            vcf_path,
            normalized_path,
            active_genome_index_path=active_genome_index_path,
            pass_only=True,
            primary_contigs_only=True,
            chrom_style="chr",
        )
    except (OSError, ValueError, sqlite_error_cls()) as exc:
        return {
            "status": "failed",
            "remediated": False,
            "method": "active_genome_index_export",
            "intake_path_hidden": True,
            "reason": f"Active Genome Index export for the PharmCAT matcher failed: {exc}",
            "warnings": [
                "PharmCAT-compatible VCF could not be derived from the Active Genome Index; "
                "the matcher cannot be invoked safely. No intake fallback is permitted.",
            ],
        }
    return {
        "status": export.get("status", "completed"),
        "remediated": True,
        "method": "active_genome_index_export",
        "input_path": str(normalized_path),
        "intake_path_hidden": True,
        "manifest_path": export.get("manifest_path"),
        "filters_applied": {
            "chrom_style": "chr",
            "pass_only": True,
            "primary_contigs_only": True,
        },
        "candidate_records": export.get("candidate_records"),
        "exported_records": export.get("exported_records"),
        "reason": (
            "Wrote the PharmCAT matcher input from the Active Genome Index with "
            "chr-prefixed chromosomes, PASS-only records, and canonical primary contigs."
        ),
    }


def _surface_vcf_normalization(vcf_normalization: JsonObject) -> JsonObject:
    """Return a copy of a vcf_normalization dict safe to surface in MCP/CLI output.

    The internal record carries `input_path` so the command builder can plumb
    the real intake file into the PharmCAT matcher. That same field, however,
    leaks the user's intake source (which may be any of the supported genome
    source formats — VCF, gVCF, BAM, 23andMe, AncestryDNA — by the time it
    reaches normalization). Whenever `intake_path_hidden` is set, redact the
    path before returning the dict to the agent.
    """

    if not vcf_normalization.get("intake_path_hidden"):
        return dict(vcf_normalization)
    surfaced = dict(vcf_normalization)
    surfaced["input_path"] = "[hidden_intake_source]"
    return surfaced


def _base_result(
    *,
    ok: bool,
    status: str,
    vcf_path: Path,
    output_dir: str | Path | None,
    base_filename: str | None,
    message: str | None = None,
) -> JsonObject:
    out_dir = Path(output_dir).expanduser() if output_dir else run_work_dir(vcf_path) / "pharmcat"
    payload: JsonObject = {
        "schema": PHARMCAT_RUN_SCHEMA,
        "ok": ok,
        "status": status,
        "input": {
            "role": "active_genome_index_vcf_for_local_pharmcat",
            "hidden_intake_source": True,
            "content_sha256": vcf_content_hash(vcf_path),
        },
        "output_dir": str(out_dir.expanduser().resolve(strict=False)),
        "base_filename": _selected_base_filename(base_filename, vcf_path),
        "traceability": {
            "source_tool": "PharmCAT",
            "definition_and_guideline_sources": PHARMCAT_DOCS,
        },
    }
    if message:
        payload["message"] = message
    return payload


def _resolve_executable(value: str | Path | None, *, default_name: str) -> str | None:
    if value:
        path = Path(value).expanduser()
        return str(path) if path.exists() else str(value)
    found = shutil.which(default_name)
    return found


def _resolve_jar(value: str | Path | None) -> str | None:
    candidate = value or os.environ.get("PHARMCAT_JAR")
    if candidate:
        path = Path(candidate).expanduser()
        if path.exists():
            return str(path)
    # Fall back to the Genomi-managed install path populated by the
    # `pharmcat` library installer.
    from ....runtime.paths import pharmcat_jar_path  # local import to avoid cycle

    managed = pharmcat_jar_path()
    return str(managed) if managed.exists() else None


def _redact_command(command: list[str], private_paths: list[Path]) -> list[str]:
    hidden = set()
    for private_path in private_paths:
        hidden.add(str(private_path))
        hidden.add(str(private_path.expanduser().resolve(strict=False)))
    return ["[hidden_intake_source]" if item in hidden else item for item in command]


def _selected_base_filename(base_filename: str | None, vcf_path: Path) -> str:
    return _clean_base_filename(base_filename) or _default_base_filename(vcf_path)


def _default_base_filename(vcf_path: Path) -> str:
    content_hash = vcf_content_hash(vcf_path)
    if content_hash:
        return f"active-genome-index-{content_hash[:12]}"
    return "active-genome-index"
