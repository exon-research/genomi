"""Public reference protein sequence retrieval from the declared UniProt source.

Declared input scope: a public UniProt accession, or a reviewed gene symbol plus
an organism taxon id. Anything else — a local path, a raw residue string, a
sample or index identifier, a malformed accession — is refused as
``out_of_scope_for_input`` rather than being resolved on a guess.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ....evidence import envelope as evidence_envelope
from ....runtime.http_json import fetch_json_with_trace
from .constants import (
    DEFAULT_PROTEIN_TAXON_ID,
    NOT_INTEGRATED_PROTEIN_SEQUENCE_SOURCES,
    UNIPROT_API_BASE,
)
from .helpers import _clean_text
from .responses import _source_coverage

OPERATION = "protein.retrieve_reference_sequence"
UNIPROT_SOURCE_LABEL = "UniProt Knowledgebase"
UNIPROT_TIMEOUT_SECONDS = 20
UNIPROT_USER_AGENT = "genomi/0.1"
MAX_RESOLUTION_CANDIDATES = 5

# Official UniProtKB accession grammar, optionally naming one isoform.
ACCESSION_RE = re.compile(
    r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})(?:-[0-9]+)?$"
)
GENE_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,24}$")
_RESIDUE_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWYBXZJUO")

_OK = "ok"
_NO_RECORD = "no_record"
_UNAVAILABLE = "source_unavailable"

# (payload, outcome, error) for one declared UniProt request.
UniProtFetch = Callable[[str, "dict[str, str] | None"], "tuple[Any, str, str]"]


def retrieve_reference_protein_sequence(
    *,
    accession: str | None = None,
    gene_symbol: str | None = None,
    organism_taxon_id: int = DEFAULT_PROTEIN_TAXON_ID,
    fetch_uniprot: UniProtFetch | None = None,
) -> dict[str, Any]:
    """Retrieve one public reference amino-acid sequence and its entry provenance."""

    raw_accession = _clean_text(accession)
    raw_gene_symbol = _clean_text(gene_symbol)
    taxon_id = _taxon_id(organism_taxon_id)
    query = {
        "accession": raw_accession.upper(),
        "gene_symbol": raw_gene_symbol.upper(),
        "organism_taxon_id": taxon_id,
    }
    fetch = fetch_uniprot or _fetch_uniprot

    if not raw_accession and not raw_gene_symbol:
        return _out_of_scope(query, "target_missing")
    if raw_accession:
        if not ACCESSION_RE.fullmatch(raw_accession.upper()):
            return _out_of_scope(query, _accession_refusal_code(raw_accession))
        return _retrieve_by_accession(query, raw_accession.upper(), fetch)
    if not GENE_SYMBOL_RE.fullmatch(raw_gene_symbol):
        return _out_of_scope(query, _gene_symbol_refusal_code(raw_gene_symbol))
    return _retrieve_by_gene_symbol(query, raw_gene_symbol.upper(), taxon_id, fetch)


# --------------------------------------------------------------------------- #
# declared retrieval paths
# --------------------------------------------------------------------------- #
def _retrieve_by_accession(query: dict[str, Any], accession: str, fetch: UniProtFetch) -> dict[str, Any]:
    entry, outcome, error = fetch(f"uniprotkb/{accession}.json", None)
    if outcome == _UNAVAILABLE:
        return _unavailable(query, error)
    if outcome == _NO_RECORD or not isinstance(entry, dict):
        return _empty(query, "no_uniprot_entry_for_accession")
    protein = _protein_record(entry)
    if not protein["sequence"]:
        return _empty(query, "uniprot_entry_carries_no_sequence", entry_type=protein["entry_type"])
    return _found(query, protein)


def _retrieve_by_gene_symbol(
    query: dict[str, Any],
    gene_symbol: str,
    taxon_id: int,
    fetch: UniProtFetch,
) -> dict[str, Any]:
    search_query = f"gene_exact:{gene_symbol} AND organism_id:{taxon_id} AND reviewed:true"
    payload, outcome, error = fetch(
        "uniprotkb/search",
        {"query": search_query, "format": "json", "size": str(MAX_RESOLUTION_CANDIDATES)},
    )
    if outcome == _UNAVAILABLE:
        return _unavailable(query, error)
    results = payload.get("results") if isinstance(payload, dict) else None
    entries = [item for item in (results or []) if isinstance(item, dict)]
    if not entries:
        return _empty(query, "no_reviewed_uniprot_entry_for_gene_symbol")
    if len(entries) > 1:
        return _ambiguous(query, [_candidate_record(entry) for entry in entries])
    protein = _protein_record(entries[0])
    if not protein["sequence"]:
        return _empty(query, "uniprot_entry_carries_no_sequence", entry_type=protein["entry_type"])
    return _found(query, protein)


# --------------------------------------------------------------------------- #
# source record shaping
# --------------------------------------------------------------------------- #
def _protein_record(entry: dict[str, Any]) -> dict[str, Any]:
    sequence_block = entry.get("sequence") if isinstance(entry.get("sequence"), dict) else {}
    audit = entry.get("entryAudit") if isinstance(entry.get("entryAudit"), dict) else {}
    organism = entry.get("organism") if isinstance(entry.get("organism"), dict) else {}
    entry_type = _clean_text(entry.get("entryType"))
    accession = _clean_text(entry.get("primaryAccession")).upper()
    sequence = "".join(str(sequence_block.get("value") or "").split()).upper()
    return {
        "accession": accession,
        "entry_name": _clean_text(entry.get("uniProtkbId")),
        "entry_type": entry_type,
        "reviewed": entry_type.startswith("UniProtKB reviewed"),
        "protein_name": _protein_name(entry),
        "gene_symbol": _gene_symbol(entry),
        "organism_scientific_name": _clean_text(organism.get("scientificName")),
        "organism_taxon_id": organism.get("taxonId"),
        "entry_version": audit.get("entryVersion"),
        "sequence_version": audit.get("sequenceVersion"),
        "sequence_length": sequence_block.get("length") or len(sequence),
        "sequence_crc64": _clean_text(sequence_block.get("crc64")),
        "sequence_md5": _clean_text(sequence_block.get("md5")),
        "sequence": sequence,
        "source": "uniprot",
        "source_record_url": f"{UNIPROT_API_BASE.rstrip('/')}/uniprotkb/{accession}.json",
    }


def _candidate_record(entry: dict[str, Any]) -> dict[str, Any]:
    record = _protein_record(entry)
    return {key: value for key, value in record.items() if key != "sequence"}


def _protein_name(entry: dict[str, Any]) -> str:
    description = entry.get("proteinDescription")
    if not isinstance(description, dict):
        return ""
    for key in ("recommendedName", "submissionNames"):
        value = description.get(key)
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            full_name = candidate.get("fullName")
            if isinstance(full_name, dict) and _clean_text(full_name.get("value")):
                return _clean_text(full_name.get("value"))
    return ""


def _gene_symbol(entry: dict[str, Any]) -> str:
    genes = entry.get("genes")
    for gene in genes if isinstance(genes, list) else []:
        if not isinstance(gene, dict):
            continue
        name = gene.get("geneName")
        if isinstance(name, dict) and _clean_text(name.get("value")):
            return _clean_text(name.get("value")).upper()
    return ""


# --------------------------------------------------------------------------- #
# declared response shapes
# --------------------------------------------------------------------------- #
def _capability_contract() -> dict[str, Any]:
    return {
        "name": OPERATION,
        "scope": "Retrieve the public reference amino-acid sequence and entry provenance for a declared UniProt accession or reviewed gene symbol.",
        "supported_sources": {"uniprot": "UniProt Knowledgebase entry records via the live UniProt REST API."},
        "out_of_scope": NOT_INTEGRATED_PROTEIN_SEQUENCE_SOURCES,
    }


def _found(query: dict[str, Any], protein: dict[str, Any]) -> dict[str, Any]:
    observations = {
        "observation_count": 1,
        "returned_sequence_count": 1,
        "accession": protein["accession"],
        "sequence_length": protein["sequence_length"],
        "sequence_version": protein["sequence_version"],
        "entry_version": protein["entry_version"],
        "sequence_crc64": protein["sequence_crc64"],
        "organism_taxon_id": protein["organism_taxon_id"],
        "reviewed": protein["reviewed"],
    }
    coverage = _source_coverage(
        "data_returned", consulted=[UNIPROT_SOURCE_LABEL], unavailable=[], not_integrated=NOT_INTEGRATED_PROTEIN_SEQUENCE_SOURCES
    )
    return {
        "coverage_state": "data_returned",
        "status": "reference_sequence_found",
        "agent_decision_required": True,
        "query": query,
        "capability": _capability_contract(),
        "protein": protein,
        "coverage": {"returned_sequence_count": 1, "source": "uniprot"},
        "source_coverage": coverage,
        "evidence_envelope": evidence_envelope.evidence_present(
            operation=OPERATION,
            query_scope=query,
            coverage=coverage,
            observations=observations,
            answer_readiness=evidence_envelope.SCOPED_ANSWER_ONLY,
            guidance=["evidence_present:cite_accession_and_sequence_version_with_any_sequence_claim"],
        ),
    }


def _empty(query: dict[str, Any], reason_code: str, *, entry_type: str = "") -> dict[str, Any]:
    observations = {"observation_count": 0, "reason_code": reason_code}
    if entry_type:
        observations["entry_type"] = entry_type
    coverage = _source_coverage(
        "in_scope_empty", consulted=[UNIPROT_SOURCE_LABEL], unavailable=[], not_integrated=NOT_INTEGRATED_PROTEIN_SEQUENCE_SOURCES
    )
    return {
        "coverage_state": "in_scope_empty",
        "status": "no_reference_sequence_record",
        "agent_decision_required": True,
        "query": query,
        "capability": _capability_contract(),
        "reason_code": reason_code,
        "resolution_candidates": [],
        "coverage": {"returned_sequence_count": 0, "source": "uniprot"},
        "source_coverage": coverage,
        "evidence_envelope": evidence_envelope.empty_consulted_scope(
            operation=OPERATION,
            query_scope=query,
            coverage=coverage,
            observations=observations,
            requires_for_true_negative=[evidence_envelope.REQ_SCOPE_ALIGNMENT],
            next_actions=[{"action": "supply_another_public_uniprot_accession_or_gene_symbol"}],
            guidance=["not_observed_in_consulted_scope:do_not_imply_the_protein_does_not_exist"],
        ),
    }


def _ambiguous(query: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    observations = {
        "observation_count": 0,
        "reason_code": "multiple_reviewed_entries_for_gene_symbol",
        "resolution_candidate_count": len(candidates),
    }
    coverage = _source_coverage(
        "in_scope_empty", consulted=[UNIPROT_SOURCE_LABEL], unavailable=[], not_integrated=NOT_INTEGRATED_PROTEIN_SEQUENCE_SOURCES
    )
    return {
        "coverage_state": "in_scope_empty",
        "status": "no_single_reference_sequence_record",
        "agent_decision_required": True,
        "query": query,
        "capability": _capability_contract(),
        "reason_code": "multiple_reviewed_entries_for_gene_symbol",
        "resolution_candidates": candidates,
        "coverage": {"returned_sequence_count": 0, "source": "uniprot"},
        "source_coverage": coverage,
        "evidence_envelope": evidence_envelope.not_assessed(
            operation=OPERATION,
            reason="multiple_reviewed_entries_for_gene_symbol",
            query_scope=query,
            coverage=coverage,
            observations=observations,
            next_actions=[{"action": "call_again_with_one_accession_from_resolution_candidates"}],
            guidance=["not_assessed:call_again_with_one_accession_from_resolution_candidates"],
        ),
    }


def _out_of_scope(query: dict[str, Any], reason_code: str) -> dict[str, Any]:
    coverage = _source_coverage(
        "out_of_scope_for_input", consulted=[], unavailable=[], not_integrated=NOT_INTEGRATED_PROTEIN_SEQUENCE_SOURCES
    )
    return {
        "coverage_state": "out_of_scope_for_input",
        "status": "out_of_scope_for_input",
        "agent_decision_required": True,
        "query": query,
        "capability": _capability_contract(),
        "reason_code": reason_code,
        "resolution_candidates": [],
        "source_coverage": coverage,
        "evidence_envelope": evidence_envelope.out_of_scope_for_input(
            operation=OPERATION,
            query_scope=query,
            coverage=coverage,
            observations={"observation_count": 0, "reason_code": reason_code},
            next_actions=[{"action": "supply_a_public_uniprot_accession_or_reviewed_gene_symbol"}],
            guidance=["out_of_scope_for_input:supply_a_public_uniprot_accession_or_reviewed_gene_symbol"],
        ),
    }


def _unavailable(query: dict[str, Any], error: str) -> dict[str, Any]:
    coverage = _source_coverage(
        "source_unavailable",
        consulted=[],
        unavailable=[{"source": UNIPROT_SOURCE_LABEL, "error": error}],
        not_integrated=NOT_INTEGRATED_PROTEIN_SEQUENCE_SOURCES,
    )
    return {
        "coverage_state": "source_unavailable",
        "status": "source_unavailable",
        "agent_decision_required": True,
        "query": query,
        "capability": _capability_contract(),
        "reason_code": "uniprot_request_failed",
        "resolution_candidates": [],
        "source_coverage": coverage,
        "evidence_envelope": evidence_envelope.not_assessed(
            operation=OPERATION,
            reason="uniprot_request_failed",
            query_scope=query,
            coverage=coverage,
            observations={"observation_count": 0, "reason_code": "uniprot_request_failed"},
            next_actions=[{"action": "retry_uniprot_later_or_supply_the_reference_sequence"}],
            guidance=["not_assessed:retry_external_source_or_use_another_source"],
        ),
    }


# --------------------------------------------------------------------------- #
# declared input-scope refusals
# --------------------------------------------------------------------------- #
def _accession_refusal_code(value: str) -> str:
    if _looks_like_local_or_private_input(value):
        return "non_public_identifier_form"
    if _looks_like_residue_string(value):
        return "raw_sequence_is_not_a_public_identifier"
    return "malformed_uniprot_accession"


def _gene_symbol_refusal_code(value: str) -> str:
    if _looks_like_residue_string(value):
        return "raw_sequence_is_not_a_public_identifier"
    return "non_public_identifier_form"


def _looks_like_local_or_private_input(value: str) -> bool:
    return any(marker in value for marker in ("/", "\\", ":", " ")) or value.startswith("~")


def _looks_like_residue_string(value: str) -> bool:
    upper = value.upper()
    return len(upper) > 24 and set(upper) <= _RESIDUE_ALPHABET


def _taxon_id(value: Any) -> int:
    try:
        taxon = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PROTEIN_TAXON_ID
    return taxon if taxon > 0 else DEFAULT_PROTEIN_TAXON_ID


# --------------------------------------------------------------------------- #
# declared source access
# --------------------------------------------------------------------------- #
def _fetch_uniprot(path: str, query: dict[str, str] | None) -> tuple[Any, str, str]:
    raw_calls: list[dict[str, Any]] = []
    payload = fetch_json_with_trace(
        UNIPROT_API_BASE,
        path,
        query=query,
        raw_calls=raw_calls,
        timeout=UNIPROT_TIMEOUT_SECONDS,
        user_agent=UNIPROT_USER_AGENT,
        not_found_payload=None,
    )
    call = raw_calls[-1] if raw_calls else {}
    if payload is not None:
        return payload, _OK, ""
    status = call.get("status")
    if isinstance(status, int) and 400 <= status < 500:
        return None, _NO_RECORD, ""
    return None, _UNAVAILABLE, str(call.get("error") or f"UniProt request returned no record (status={status})")
