from __future__ import annotations

from ...capabilities.sequence import sequence
from .coerce import (
    _int,
    _list_str,
    _optional_int,
    _optional_path,
    _path,
    _str,
)
from .errors import JsonObject, OperationError


def _sequence_translate(params: JsonObject) -> JsonObject:
    return sequence.translate_sequence(
        _str(params, "sequence"),
        frame=_int(params, "frame", 1),
        strand=_str(params, "strand", "forward"),
    )


def _sequence_analyze(params: JsonObject) -> JsonObject:
    mode = _str(params, "mode", "summary")
    if mode not in {"summary", "translate", "orfs", "restriction_sites", "kozak"}:
        raise OperationError("invalid_params", "mode must be one of: summary, translate, orfs, restriction_sites, kozak")
    selected = {"translate", "orfs", "restriction_sites", "kozak"} if mode == "summary" else {mode}
    sequence_text = _str(params, "sequence")
    analyses: JsonObject = {}
    if "translate" in selected:
        analyses["translation"] = sequence.translate_sequence(
            sequence_text,
            frame=_int(params, "frame", 1),
            strand=_str(params, "strand", "forward"),
        )
    if "orfs" in selected:
        analyses["orfs"] = sequence.find_orfs(
            sequence_text,
            min_aa=_int(params, "min_aa", 30),
            strand=_str(params, "strand", "both"),
        )
    if "restriction_sites" in selected:
        analyses["restriction_sites"] = sequence.find_restriction_sites(
            sequence_text,
            enzymes=_list_str(params, "enzymes"),
            motifs=_list_str(params, "motifs"),
        )
    if "kozak" in selected:
        analyses["kozak_context"] = sequence.kozak_context(
            sequence_text,
            start_pos=_optional_int(params, "start_pos"),
        )
    reference_fasta = _optional_path(params, "reference_fasta")
    if reference_fasta is not None:
        analyses["reference_matches"] = sequence.match_reference_records(
            sequence_text,
            reference_fasta,
            max_matches=_int(params, "max_matches", 10),
        )
    return {
        "schema": "genomi-sequence-analysis-v1",
        "status": "completed",
        "query": {"mode": mode, "sequence_length": len(sequence_text)},
        "analyses": analyses,
        "next_skill": {
            "reason": "Use focused sequence tools when only one deterministic sequence operation is needed.",
            "skill": "sequence",
            "focused_tools": [
                {"tool": "sequence.translate", "use_when": "Only translation is needed."},
                {"tool": "sequence.find_orfs", "use_when": "Only ORF discovery is needed."},
                {"tool": "sequence.find_restriction_sites", "use_when": "Only motif or restriction-site lookup is needed."},
                {"tool": "sequence.classify_kozak", "use_when": "Only start-codon context is needed."},
                {"tool": "sequence.match_reference", "use_when": "A local FASTA reference can identify the supplied sequence."},
            ],
        },
    }


def _sequence_match_reference_records(params: JsonObject) -> JsonObject:
    return sequence.match_reference_records(
        _str(params, "sequence"),
        _path(params, "reference_fasta"),
        max_matches=_int(params, "max_matches", 10),
    )


def _sequence_find_orfs(params: JsonObject) -> JsonObject:
    return sequence.find_orfs(
        _str(params, "sequence"),
        min_aa=_int(params, "min_aa", 30),
        strand=_str(params, "strand", "both"),
    )


def _sequence_restriction_sites(params: JsonObject) -> JsonObject:
    return sequence.find_restriction_sites(
        _str(params, "sequence"),
        enzymes=_list_str(params, "enzymes"),
        motifs=_list_str(params, "motifs"),
    )


def _sequence_kozak_context(params: JsonObject) -> JsonObject:
    start_pos = params.get("start_pos")
    return sequence.kozak_context(
        _str(params, "sequence"),
        start_pos=int(start_pos) if start_pos not in (None, "") else None,
    )


def _sequence_check_primers(params: JsonObject) -> JsonObject:
    return sequence.check_primers(
        forward_primer=_str(params, "forward_primer"),
        reverse_primer=params.get("reverse_primer"),
        template=params.get("template"),
    )
