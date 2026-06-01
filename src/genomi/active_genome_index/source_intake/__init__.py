"""Genome source intake: detection and digitization into an Active Genome Index.

This package is the facade for what was previously the single
``source_intake.py`` module. The complete public surface — including the
underscore-prefixed helpers and the re-exported dependency names that tests
patch (e.g. ``infer_genome_build_from_bam``, ``materialize_bam_variant_vcf``)
— is re-exported here so that ``genomi.active_genome_index.source_intake.<name>``
resolves exactly as it did before the split.
"""

from __future__ import annotations

# Standard-library names that were bound at module scope in the original file.
import contextlib
import csv
import gzip
import io
import json
import re
import sqlite3
import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

# Re-exported dependency names (some are patched by tests on this module).
from ..active_genome_index import (
    SCHEMA_VERSION,
    _chrom_sort,
    active_genome_index_readiness,
    create_active_genome_index,
    default_active_genome_index_path,
)
from ..active_genome_index import connect as connect_active_genome_index
from ..alignment import (
    align_fastq_to_bam,
    detect_paired_fastq,
    infer_genome_build_from_bam,
    materialize_bam_variant_vcf,
    normalize_alignment_genome_build,
)
from ..canonical import build_canonical_bgzip
from ...evidence import connect_evidence, init_evidence_db
from ...runtime.external import file_metadata
from ...runtime.paths import (
    run_evidence_db_path_for_source,
    run_evidence_dir_for_source,
    run_output_path_for_source,
    run_project_dir_for_source,
    run_reference_dir_for_source,
    run_work_dir_for_source,
    sample_slug_from_source,
    shared_evidence_db_path,
    shared_reference_dir,
)
from ...runtime.static_dependencies import resolve_genome_build

# Public and internal symbols defined across the topical submodules.
from .agi_store import (
    SOURCE_PARSE_SCHEMA,
    JsonObject,
    _array_record_row,
    _cached_array_active_genome_index_if_usable,
    _create_source_query_indexes,
    _init_source_evidence_db,
    _insert_source_active_genome_index_metadata,
    _insert_source_record_batch,
    _insert_source_stat_rows,
    _reset_source_active_genome_index_schema,
)
from .arrays import (
    _CONSUMER_ARRAY_SPECS,
    _ConsumerArraySpec,
    _build_consumer_array_active_genome_index,
    _iter_23andme_rows,
    _iter_ancestrydna_rows,
    _iter_livingdna_rows,
    _iter_myheritage_rows,
    _populate_23andme_records,
    _populate_ancestrydna_records,
    _populate_consumer_array_records,
    build_23andme_active_genome_index,
    build_ancestrydna_active_genome_index,
    parse_23andme_source,
    parse_ancestrydna_source,
    parse_consumer_array_source,
)
from .detection import (
    _NEBULA_SAMPLE_PATTERN,
    _VCF_PROVIDER_SIGNATURES,
    SourceDetection,
    _detect_23andme,
    _detect_ancestrydna,
    detect_source,
)
from .dispatch import parse_source
from .sequencing import parse_bam_source, parse_fastq_source
from .text_io import (
    _clean_array_chrom,
    _effective_array_build,
    _first_zip_text_member,
    _open_text_source,
)
from .vcf import _parse_vcf_active_genome_index

__all__ = [
    "SourceDetection",
    "SOURCE_PARSE_SCHEMA",
    "JsonObject",
    "parse_source",
    "detect_source",
    "parse_bam_source",
    "parse_fastq_source",
    "parse_23andme_source",
    "parse_ancestrydna_source",
    "parse_consumer_array_source",
    "build_23andme_active_genome_index",
    "build_ancestrydna_active_genome_index",
]
