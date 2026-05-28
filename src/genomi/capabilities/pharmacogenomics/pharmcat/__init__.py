"""PharmCAT runtime/execution and artifact-import facade package.

This package replaces the former ``pharmcat.py`` module. It preserves the full
public surface at ``genomi.capabilities.pharmacogenomics.pharmcat`` so imports
and test monkeypatches keep working — including patches that target
``pharmcat.shutil.which`` and ``pharmcat.subprocess.run`` (the ``shutil`` and
``subprocess`` standard-library modules are re-exported here as package
attributes; the execution submodule resolves ``shutil``/``subprocess`` at call
time, so patching the shared module objects takes effect).
"""

from __future__ import annotations

# Standard-library modules preserved as package attributes for monkeypatching
# (``patch("...pharmcat.shutil.which")`` / ``patch("...pharmcat.subprocess.run")``).
import os  # noqa: F401
import shutil  # noqa: F401
import subprocess  # noqa: F401

from ._common import (  # noqa: F401
    JsonObject,
    PHARMCAT_DOCS,
    PHARMCAT_IMPORT_SCHEMA,
    PHARMCAT_RUN_SCHEMA,
    PHARMCAT_STATUS_SCHEMA,
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
    _vcf_suffix,
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
    _surface_vcf_normalization,
    _unavailable_result,
    _version_command,
    _version_probe,
    _version_text,
    pharmcat_preflight,
    pharmcat_status,
    run_pharmcat,
)
