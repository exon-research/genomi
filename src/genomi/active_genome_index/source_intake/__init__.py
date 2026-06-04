"""Genome source detection and digitization into an Active Genome Index."""

from __future__ import annotations

from .agi_store import SOURCE_PARSE_SCHEMA, JsonObject
from .arrays import SUPPORTED_CONSUMER_ARRAY_FORMATS, parse_consumer_array_source
from .detection import SourceDetection, detect_source
from .dispatch import parse_source
from .sequencing import parse_bam_source, parse_fastq_source

__all__ = [
    "JsonObject",
    "SOURCE_PARSE_SCHEMA",
    "SUPPORTED_CONSUMER_ARRAY_FORMATS",
    "SourceDetection",
    "detect_source",
    "parse_bam_source",
    "parse_consumer_array_source",
    "parse_fastq_source",
    "parse_source",
]
