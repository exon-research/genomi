from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ....active_genome_index.export import export_variants
from ....runtime.libraries import manager as library_manager
from .. import pgx_outside_calls
from ._common import (
    JsonObject,
    PHARMCAT_DOCS,
    _clean_base_filename,
    _file_sha256,
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
    managed_install = _managed_pharmcat_install_request(
        selected=selected,
        mode=mode,
        pipeline_command=pipeline_command,
        pharmcat_jar=pharmcat_jar,
    )
    if managed_install is not None:
        return {
            **managed_install,
            "availability": selected,
            "version_probe": version,
            "traceability": {
                "source_tool": "PharmCAT",
                "definition_and_guideline_sources": PHARMCAT_DOCS,
            },
        }
    available = selected.get("mode") != "unavailable"
    if not available:
        status = "tool_unavailable"
    elif version.get("status") in {"completed", "skipped"}:
        status = "available"
    elif version.get("status") == "timeout":
        status = "version_probe_timeout"
    else:
        status = "version_probe_failed"
    return {
        "status": status,
        "availability": selected,
        "version_probe": version,
        "traceability": {
            "source_tool": "PharmCAT",
            "definition_and_guideline_sources": PHARMCAT_DOCS,
        },
    }


def pharmcat_preflight(*, agi_path: str | Path) -> JsonObject:
    """Inspect AGI records against broad PharmCAT PGx input requirements."""

    agi = Path(agi_path).expanduser()
    if not agi.exists():
        return {
            "status": "missing_active_genome_index",
            "summary": {"record_count": 0},
            "input": {"hidden_agi_path": True},
            "message": "Select or parse an Active Genome Index before running PharmCAT.",
            "traceability": {
                "source_tool": "PharmCAT",
                "definition_and_guideline_sources": PHARMCAT_DOCS,
            },
        }
    preflight = _input_preflight(agi)
    return {
        "status": preflight.get("status") or "unknown",
        "summary": _preflight_summary(preflight),
        "input_preflight": preflight,
        "traceability": {
            "source_tool": "PharmCAT",
            "definition_and_guideline_sources": PHARMCAT_DOCS,
        },
    }


def run_pharmcat(
    *,
    agi_path: str | Path,
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
    """Run a local PharmCAT installation against a selected Active Genome Index."""

    agi = Path(agi_path).expanduser()
    if not agi.exists():
        return {
            **_base_result(
                status="missing_active_genome_index",
                agi_path=agi,
                output_dir=output_dir,
                base_filename=base_filename,
                message="Select or parse an Active Genome Index before running PharmCAT.",
            ),
        }

    out_dir = Path(output_dir).expanduser() if output_dir else _default_output_dir(agi)
    base = _selected_base_filename(base_filename, agi)
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
        else {"status": "not_supplied"}
    )
    # Early gates that don't require touching the Active Genome Index or the intake source:
    # tool availability and outside-call validity. Surface these first so the
    # agent gets the right structured error without us needing to look at any
    # genomic data.
    if outside_call_file and outside_call_validation.get("status") != "completed":
        return {
            **_base_result(status="invalid_outside_call_file", agi_path=agi, output_dir=out_dir, base_filename=base),
            "outside_call_validation": outside_call_validation,
            "warnings": list(outside_call_validation.get("warnings") or []),
        }
    if outside_call_file and selected.get("mode") == "pipeline":
        return {
            **_base_result(
                status="outside_call_file_not_supported_in_pipeline_mode",
                agi_path=agi,
                output_dir=out_dir,
                base_filename=base,
                message=(
                    "The selected PharmCAT pipeline command cannot receive an explicit outside_call_file. "
                    "Use jar mode for explicit outside calls, or place pipeline-discovered outside-call files "
                    "beside the PharmCAT input outside this operation."
                ),
            ),
            "outside_call_validation": outside_call_validation,
            "availability": selected,
            "execution": {"version_probe": version},
        }
    if selected.get("mode") in {"unavailable", None}:
        managed_install = _managed_pharmcat_install_request(
            selected=selected,
            mode=mode,
            pipeline_command=pipeline_command,
            pharmcat_jar=pharmcat_jar,
        )
        if managed_install is not None:
            return {
                **_base_result(
                    status=managed_install["status"],
                    agi_path=agi,
                    output_dir=out_dir,
                    base_filename=base,
                ),
                **managed_install,
                "input_preflight": {"status": "skipped_missing_library"},
                "outside_call_validation": outside_call_validation,
                "pharmcat_input": {"status": "skipped_missing_library", "path_hidden": True},
                "availability": selected,
                "execution": {"version_probe": version},
            }
        return _explicit_pharmcat_unavailable_result(
            agi_path=agi,
            output_dir=out_dir,
            base_filename=base,
            selected=selected,
            input_preflight={"status": "skipped_tool_unavailable"},
            outside_call_validation=outside_call_validation,
            version=version,
        )

    input_preflight = _input_preflight(agi)
    pharmcat_input = _prepare_pharmcat_input(
        agi_path=agi,
        out_dir=out_dir,
        base_filename=base,
        dry_run=dry_run,
    )
    surfaced_pharmcat_input = _surface_pharmcat_input(pharmcat_input)
    if not pharmcat_input.get("remediated") or not pharmcat_input.get("input_path"):
        prep_status = str(pharmcat_input.get("status") or "active_genome_index_input_unavailable")
        return {
            **_base_result(status=prep_status, agi_path=agi, output_dir=out_dir, base_filename=base),
            "input_preflight": input_preflight,
            "pharmcat_input": surfaced_pharmcat_input,
            "outside_call_validation": outside_call_validation,
            "warnings": list(pharmcat_input.get("warnings") or []),
        }
    pharmcat_input_path = Path(pharmcat_input["input_path"])
    command = _build_command(
        selected=selected,
        pharmcat_input_path=pharmcat_input_path,
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
    warnings.extend(pharmcat_input.get("warnings") or [])
    if command is None:
        return _unavailable_result(
            agi_path=agi,
            output_dir=out_dir,
            base_filename=base,
            selected=selected,
            sample=sample,
            sample_file=sample_file,
            sample_metadata=sample_metadata,
            input_preflight=input_preflight,
            outside_call_validation=outside_call_validation,
            pharmcat_input=surfaced_pharmcat_input,
        )

    command_redactions = {
        pharmcat_input_path: "[derived_pharmcat_input]",
        out_dir: "[hidden_output_dir]",
    }
    for private_value in (outside_call_file, sample_file, sample_metadata):
        if private_value:
            command_redactions[Path(private_value).expanduser()] = "[hidden_private_path]"
    redacted_command = _redact_command(command, command_redactions)
    if dry_run:
        planned_artifacts = _summarize_outputs(out_dir, base)
        return {
            **_base_result(status="planned", agi_path=agi, output_dir=out_dir, base_filename=base),
            "summary": _pharmcat_run_summary([], planned_artifacts),
            "input_preflight": input_preflight,
            "pharmcat_input": surfaced_pharmcat_input,
            "outside_call_validation": outside_call_validation,
            "execution": {
                "mode": selected["mode"],
                "command": redacted_command,
                "dry_run": True,
                "timeout_seconds": int(timeout_seconds),
                "version_probe": version,
            },
            "warnings": warnings,
            "artifacts": planned_artifacts,
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
            **_base_result(status="timeout", agi_path=agi, output_dir=out_dir, base_filename=base),
            "input_preflight": input_preflight,
            "pharmcat_input": surfaced_pharmcat_input,
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
            status="completed" if completed.returncode == 0 else "failed",
            agi_path=agi,
            output_dir=out_dir,
            base_filename=base,
        ),
        "summary": _pharmcat_run_summary(record_payloads, artifacts),
        "input_preflight": input_preflight,
        "pharmcat_input": surfaced_pharmcat_input,
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
        selected_mode = "pipeline" if pipeline else "unavailable"
        return {"mode": selected_mode, "pipeline_command": pipeline, "pharmcat_jar": jar, "java_command": java}
    if requested == "jar":
        selected_mode = "jar" if jar and java else "unavailable"
        return {"mode": selected_mode, "pipeline_command": pipeline, "pharmcat_jar": jar, "java_command": java}
    if pipeline:
        return {"mode": "pipeline", "pipeline_command": pipeline, "pharmcat_jar": jar, "java_command": java}
    if jar and java:
        return {"mode": "jar", "pipeline_command": pipeline, "pharmcat_jar": jar, "java_command": java}
    return {"mode": "unavailable", "pipeline_command": pipeline, "pharmcat_jar": jar, "java_command": java}


def _managed_pharmcat_install_request(
    *,
    selected: JsonObject,
    mode: str,
    pipeline_command: str | Path | None,
    pharmcat_jar: str | Path | None,
) -> JsonObject | None:
    requested = str(mode or "auto").strip().lower()
    if selected.get("mode") != "unavailable":
        return None
    if requested == "pipeline" or pipeline_command or pharmcat_jar:
        return None
    request = library_manager.ensure(
        "pharmcat",
        intent="broad pharmacogenomic calling with PharmCAT",
        operation="pharmacogenomics.run_pharmcat",
    )
    return request if request.get("status") == "requires_library_install" else None


def _explicit_pharmcat_unavailable_result(
    *,
    agi_path: Path,
    output_dir: Path,
    base_filename: str,
    selected: JsonObject,
    input_preflight: JsonObject,
    outside_call_validation: JsonObject,
    version: JsonObject,
) -> JsonObject:
    return {
        **_base_result(
            status="explicit_pharmcat_executable_unavailable",
            agi_path=agi_path,
            output_dir=output_dir,
            base_filename=base_filename,
            message="The requested PharmCAT executable or jar override is unavailable.",
        ),
        "input_preflight": input_preflight,
        "pharmcat_input": {"status": "skipped_tool_unavailable", "path_hidden": True},
        "outside_call_validation": outside_call_validation,
        "availability": selected,
        "execution": {"version_probe": version},
    }


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
    # PharmCAT exposes the version as `--version` (`-version` is also accepted);
    # the short `-V` is rejected by the jar's CLI parser (exit 1), which made
    # the probe report a working install as failed.
    if selected.get("mode") == "pipeline" and selected.get("pipeline_command"):
        return [str(selected["pipeline_command"]), "--version"]
    if selected.get("mode") == "jar" and selected.get("pharmcat_jar") and selected.get("java_command"):
        return [str(selected["java_command"]), "-jar", str(selected["pharmcat_jar"]), "--version"]
    return None


def _version_text(stdout: str | None, stderr: str | None) -> str | None:
    text = "\n".join(value.strip() for value in [stdout or "", stderr or ""] if value and value.strip())
    if not text:
        return None
    return text.splitlines()[0][:400]


def _build_command(
    *,
    selected: JsonObject,
    pharmcat_input_path: Path,
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
        command = [str(selected["pipeline_command"]), str(pharmcat_input_path), "-o", str(output_dir), "-bf", base_filename]
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
        command.extend(["-jar", str(selected["pharmcat_jar"]), "-vcf", str(pharmcat_input_path), "-o", str(output_dir), "-bf", base_filename])
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
    agi_path: Path,
    output_dir: Path,
    base_filename: str,
    selected: JsonObject,
    sample: str | None,
    sample_file: str | Path | None,
    sample_metadata: str | Path | None,
    input_preflight: JsonObject,
    outside_call_validation: JsonObject,
    pharmcat_input: JsonObject | None = None,
) -> JsonObject:
    example = ["pharmcat_pipeline", "[derived_pharmcat_input]", "-o", "[hidden_output_dir]", "-bf", base_filename, "-reporterJson", "-reporterCallsOnlyTsv"]
    if sample:
        example.extend(["-s", str(sample)])
    if sample_file:
        example.extend(["-S", "[hidden_private_path]"])
    if sample_metadata:
        example.extend(["-sm", "[hidden_private_path]"])
    return {
        **_base_result(status="tool_unavailable", agi_path=agi_path, output_dir=output_dir, base_filename=base_filename),
        "input_preflight": input_preflight,
        "pharmcat_input": pharmcat_input or {"status": "not_evaluated"},
        "outside_call_validation": outside_call_validation,
        "availability": selected,
        "execution": {
            "version_probe": _version_probe(selected, timeout_seconds=15),
        },
        "suggested_command": example,
    }


def _prepare_pharmcat_input(
    *,
    agi_path: str | Path,
    out_dir: Path,
    base_filename: str,
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

    resolved_agi_path = Path(agi_path).expanduser()
    if not resolved_agi_path.exists():
        return {
            "status": "requires_active_genome_index",
            "remediated": False,
            "method": "active_genome_index_export",
            "path_hidden": True,
            "reason": (
                "No Active Genome Index was found. Run genomi.parse_source first."
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
            "path_hidden": True,
            "reason": "dry_run skipped the Active Genome Index export write; matcher would read the Active Genome Index-derived VCF below.",
            "would_apply": {
                "chrom_style": "chr",
                "pass_only": True,
                "variants_only": False,
                "primary_contigs_only": True,
            },
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    normalized_path = out_dir / f"{base_filename}.pharmcat-input.vcf"
    try:
        export = export_variants(
            resolved_agi_path,
            normalized_path,
            pass_only=True,
            variants_only=False,
            primary_contigs_only=True,
            chrom_style="chr",
            sanitize_metadata=True,
        )
    except (OSError, ValueError, sqlite_error_cls()) as exc:
        return {
            "status": "failed",
            "remediated": False,
            "method": "active_genome_index_export",
            "path_hidden": True,
            "reason": f"Active Genome Index export for the PharmCAT matcher failed: {exc}",
            "warnings": [
                "PharmCAT-compatible VCF could not be derived from the Active Genome Index; "
                "the matcher cannot be invoked safely. No intake fallback is permitted.",
            ],
        }
    if int(export.get("exported_records") or 0) <= 0:
        return {
            "status": "no_pharmcat_vcf_records",
            "remediated": False,
            "method": "active_genome_index_export",
            "path_hidden": True,
            "manifest_path": export.get("manifest_path"),
            "candidate_records": export.get("candidate_records"),
            "exported_records": export.get("exported_records"),
            "reason": (
                "The selected Active Genome Index did not contain VCF-encodable variant_call records "
                "for PharmCAT. Consumer-array observations are not passed to PharmCAT as fake VCF alleles."
            ),
            "warnings": [
                "Use targeted PGx variant evidence or an explicit PharmCAT-compatible VCF/sequence-derived Active Genome Index for broad PharmCAT calling."
            ],
        }
    return {
        "status": export.get("status", "completed"),
        "remediated": True,
        "method": "active_genome_index_export",
        "input_path": str(normalized_path),
        "path_hidden": True,
        "manifest_path": export.get("manifest_path"),
        "filters_applied": {
            "chrom_style": "chr",
            "pass_only": True,
            "variants_only": False,
            "primary_contigs_only": True,
        },
        "candidate_records": export.get("candidate_records"),
        "exported_records": export.get("exported_records"),
        "reason": (
            "Wrote the PharmCAT matcher input from the Active Genome Index with "
            "chr-prefixed chromosomes, PASS-only records, canonical primary contigs, "
            "and variant, reference, and no-call AGI rows preserved."
        ),
    }


def _surface_pharmcat_input(pharmcat_input: JsonObject) -> JsonObject:
    surfaced = dict(pharmcat_input)
    if surfaced.get("path_hidden"):
        surfaced["input_path"] = "[derived_pharmcat_input]"
    return surfaced


def _base_result(
    *,
    status: str,
    agi_path: Path,
    output_dir: str | Path | None,
    base_filename: str | None,
    message: str | None = None,
) -> JsonObject:
    payload: JsonObject = {
        "status": status,
        "input": {
            "role": "active_genome_index_for_local_pharmcat",
            "hidden_agi_path": True,
            "content_sha256": _file_sha256(agi_path),
        },
        "output_dir_hidden": True,
        "base_filename": _selected_base_filename(base_filename, agi_path),
        "traceability": {
            "source_tool": "PharmCAT",
            "definition_and_guideline_sources": PHARMCAT_DOCS,
        },
    }
    if message:
        payload["message"] = message
    return payload


def _preflight_summary(preflight: JsonObject) -> JsonObject:
    scan = preflight.get("scan_summary") if isinstance(preflight.get("scan_summary"), dict) else {}
    checks = preflight.get("pharmcat_requirement_checks") if isinstance(preflight.get("pharmcat_requirement_checks"), list) else []
    return {
        "record_count": int(scan.get("records_scanned") or 0),
        "requirement_check_count": len(checks),
    }


def _pharmcat_run_summary(record_payloads: list[JsonObject], artifacts: JsonObject) -> JsonObject:
    return {
        "record_count": len(record_payloads),
        "artifact_count": int((artifacts.get("file_count") or 0) if isinstance(artifacts, dict) else 0),
    }


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


def _redact_command(command: list[str], redactions: dict[Path, str]) -> list[str]:
    hidden: dict[str, str] = {}
    for private_path, placeholder in redactions.items():
        hidden[str(private_path)] = placeholder
        hidden[str(private_path.expanduser().resolve(strict=False))] = placeholder
    return [hidden.get(item, item) for item in command]


def _default_output_dir(agi_path: Path) -> Path:
    return agi_path.expanduser().resolve(strict=False).parent / "pharmcat"


def _selected_base_filename(base_filename: str | None, agi_path: Path) -> str:
    return _clean_base_filename(base_filename) or _default_base_filename(agi_path)


def _default_base_filename(agi_path: Path) -> str:
    content_hash = _file_sha256(agi_path)
    if content_hash:
        return f"active-genome-index-{content_hash[:12]}"
    return "active-genome-index"
