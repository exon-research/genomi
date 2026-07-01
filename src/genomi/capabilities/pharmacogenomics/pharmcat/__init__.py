"""PharmCAT runtime/execution and artifact-import facade package.

This package exposes PharmCAT preflight, execution, artifact import, and record
payload helpers. ``shutil`` and ``subprocess`` are package attributes because
execution resolves them at call time and tests patch those module handles.
"""

from __future__ import annotations

# Standard-library module handles used by execution and tests.
import os  # noqa: F401
import shutil  # noqa: F401
import subprocess  # noqa: F401

from ._common import (  # noqa: F401
    JsonObject,
    PHARMCAT_DOCS,
    _artifact_fingerprint,
    _artifact_source_summary,
    _as_dicts,
    _as_list,
    _clean_base_filename,
    _clean_report_text,
    _file_sha256,
    _first_string,
    _int_or_original,
    _size,
    _tail,
    _without_none,
    sqlite_error_cls,
)
from .preflight import (  # noqa: F401
    _chrom_style_from_header_or_records,
    _contig_style,
    _header_preflight,
    _input_preflight,
    _is_indel_record,
    _is_symbolic_alt,
    _pharmcat_requirement_checks,
)
from .record_payloads import (  # noqa: F401
    _call_finding_text,
    _diplotype_texts,
    _has_imported_pharmcat_evidence,
    _match_finding_text,
    _phenotype_finding_text,
    _phenotype_record_has_result,
    _readiness,
    _record_payloads_from_calls,
    _record_payloads_from_match,
    _record_payloads_from_phenotype,
    _record_payloads_from_report,
    _report_finding_text,
)
from .matrix import (  # noqa: F401
    MEDICATION_REVIEW_TARGETS_POLICY_ID,
    SAMPLE_PGX_MATRIX_POLICY_ID,
    build_medication_review_targets,
    build_sample_pgx_matrix,
)
from .artifacts import (  # noqa: F401
    _artifact_descriptor,
    _artifact_type,
    _compact_citations,
    _dedupe_file_descriptors,
    _diplotype_label,
    _diplotypes,
    _diplotypes_from_genotypes,
    _explicit_artifact_descriptor,
    _extract_report_recommendations,
    _genes_from_genotypes,
    _import_artifacts,
    _matcher_metadata,
    _parse_calls_only_tsv,
    _phenotype_diplotype_summaries,
    _phenotypes_from_genotypes,
    _report_metadata,
    _report_recommendation_count,
    _summarize_json,
    _summarize_match_json,
    _summarize_missing_pgx_vcf,
    _summarize_outputs,
    _summarize_phenotype_json,
    import_pharmcat_artifacts,
)
from .execution import (  # noqa: F401
    _base_result,
    _build_command,
    _command_warnings,
    _default_base_filename,
    _prepare_pharmcat_input,
    _redact_command,
    _resolve_executable,
    _resolve_jar,
    _select_execution_mode,
    _selected_base_filename,
    _surface_pharmcat_input,
    _unavailable_result,
    _version_command,
    _version_probe,
    _version_text,
    pharmcat_preflight,
    pharmcat_status,
    run_pharmcat,
)
