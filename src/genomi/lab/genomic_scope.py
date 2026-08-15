"""Canonical exact genomic scopes for GenomiLab investigation reads."""

from __future__ import annotations

import re
from typing import Any, Mapping


JsonObject = dict[str, Any]
_RSID_RE = re.compile(r"^rs[0-9]+$", re.IGNORECASE)
INVESTIGATION_VARIANT_PARAMETER_FIELDS = frozenset(
    {
        "rsid",
        "chrom",
        "pos",
        "ref",
        "alt",
        "genome_build",
        "include_fail",
        "limit",
    }
)


class InvestigationAgiAuthorizationError(RuntimeError):
    """A structured failure at the investigation authorization boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalize_investigation_genomic_scope(
    scope: Mapping[str, object],
    *,
    default_genome_build: str,
) -> JsonObject:
    """Return the one supported canonical scope: one rsID or exact allele."""

    if not isinstance(scope, Mapping):
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope must be an object.",
        )
    allowed = {"operation", *INVESTIGATION_VARIANT_PARAMETER_FIELDS}
    if any(str(key) not in allowed for key in scope):
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope contains fields outside the supported exact variant scope.",
        )
    if str(scope.get("operation") or "") != "variant.resolve":
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope operation must be variant.resolve.",
        )

    rsid = str(scope.get("rsid") or "").strip().lower()
    allele_values = [scope.get(key) for key in ("chrom", "pos", "ref", "alt")]
    has_any_allele = any(value not in (None, "") for value in allele_values)
    has_exact_allele = all(value not in (None, "") for value in allele_values)
    if bool(rsid) == bool(has_exact_allele) or (has_any_allele and not has_exact_allele):
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope must contain exactly one rsID or one complete exact allele.",
        )
    if rsid and not _RSID_RE.fullmatch(rsid):
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope rsid must be an rs identifier.",
        )

    genome_build = str(scope.get("genome_build") or default_genome_build).strip()
    if not genome_build:
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope requires a genome build.",
        )
    include_fail = scope.get("include_fail", False)
    if not isinstance(include_fail, bool):
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope include_fail must be a boolean.",
        )
    raw_limit = scope.get("limit", 20)
    if isinstance(raw_limit, bool):
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope limit must be an integer from 1 to 200.",
        )
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope limit must be an integer from 1 to 200.",
        ) from exc
    if limit < 1 or limit > 200:
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope limit must be an integer from 1 to 200.",
        )

    normalized: JsonObject = {
        "operation": "variant.resolve",
        "genome_build": genome_build,
        "include_fail": include_fail,
        "limit": limit,
    }
    if rsid:
        normalized["rsid"] = rsid
        return normalized

    raw_pos = scope.get("pos")
    if isinstance(raw_pos, bool):
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope pos must be a positive integer.",
        )
    try:
        pos = int(raw_pos)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope pos must be a positive integer.",
        ) from exc
    if pos < 1:
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope pos must be a positive integer.",
        )
    chrom = _normalize_chrom(scope.get("chrom"))
    ref = _normalize_allele(scope.get("ref"), "ref")
    alt = _normalize_allele(scope.get("alt"), "alt")
    if ref == alt:
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope ref and alt must differ.",
        )
    normalized.update(
        {"chrom": chrom, "pos": pos, "ref": ref, "alt": alt}
    )
    return normalized


def validate_investigation_variant_request(
    *,
    approved_scope: Mapping[str, object],
    approved_agi_id: str,
    operation: str,
    params: Mapping[str, object],
) -> None:
    """Reject any operation or parameter that widens an approved exact scope."""

    if operation != "variant.resolve":
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_scope_mismatch",
            "This investigation authorization permits only variant.resolve.",
        )
    if not isinstance(params, Mapping):
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_scope_mismatch",
            "The authorized operation parameters must be an object.",
        )
    allowed = {
        "rsid",
        "chrom",
        "pos",
        "ref",
        "alt",
        "genome_build",
        "agi_id",
        "include_active_genome_index",
        "include_known_active_genome_indexes",
        "include_fail",
        "limit",
    }
    if any(str(key) not in allowed for key in params):
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_scope_mismatch",
            "The authorized variant request contains parameters outside its exact scope.",
        )
    requested_agi = str(params.get("agi_id") or approved_agi_id)
    if requested_agi != approved_agi_id:
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_scope_mismatch",
            "The requested Active Genome Index does not match the authorization.",
        )
    include_active = params.get("include_active_genome_index", True)
    if not isinstance(include_active, bool) or not include_active:
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_scope_mismatch",
            "An investigation-authorized call must use its bound Active Genome Index.",
        )
    include_known = params.get("include_known_active_genome_indexes", False)
    if not isinstance(include_known, bool) or include_known:
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_scope_mismatch",
            "An investigation authorization cannot search other known Active Genome Indexes.",
        )
    requested_scope = normalize_investigation_genomic_scope(
        {
            "operation": operation,
            **{
                key: value
                for key, value in params.items()
                if key in INVESTIGATION_VARIANT_PARAMETER_FIELDS
            },
        },
        default_genome_build=str(approved_scope["genome_build"]),
    )
    if requested_scope != approved_scope:
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_scope_mismatch",
            "The requested variant target does not match the approved genomic scope.",
        )


def _normalize_chrom(value: object) -> str:
    chrom = str(value or "").strip()
    if chrom.lower().startswith("chr"):
        chrom = chrom[3:]
    if not chrom or len(chrom) > 100 or any(char.isspace() for char in chrom):
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope chrom must identify one chromosome.",
        )
    return "MT" if chrom.upper() in {"M", "MT"} else chrom


def _normalize_allele(value: object, field: str) -> str:
    allele = str(value or "").strip().upper()
    if not allele or len(allele) > 10000 or any(char.isspace() for char in allele):
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            f"genomic_scope {field} must contain one allele.",
        )
    return allele


__all__ = [
    "INVESTIGATION_VARIANT_PARAMETER_FIELDS",
    "InvestigationAgiAuthorizationError",
    "normalize_investigation_genomic_scope",
    "validate_investigation_variant_request",
]
