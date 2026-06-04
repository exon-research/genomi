from __future__ import annotations

import json
from typing import Any

JsonObject = dict[str, Any]


def observed_alleles_from_record(record: JsonObject) -> list[str]:
    """Return called allele bases from AGI-owned observation fields."""
    return _observed_alleles(record.get("observed_alleles"))


def observed_alleles_from_vcf_genotype(ref: object, alt: object, genotype: object) -> list[str]:
    """Return observed bases from a raw VCF row's REF/ALT/GT fields."""
    if genotype in (None, ""):
        return []
    tokens = str(genotype).replace("|", "/").split("/")
    if not tokens or any(token in {"", "."} for token in tokens):
        return []
    alts = [item for item in str(alt or "").split(",") if item and item != "."]
    alleles: list[str] = []
    for token in tokens:
        if token == "0":
            alleles.append(str(ref).strip().upper())
            continue
        try:
            alleles.append(alts[int(token) - 1].strip().upper())
        except (IndexError, ValueError):
            return []
    return [allele for allele in alleles if allele]


def _observed_alleles(value: Any) -> list[str]:
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(base).strip().upper() for base in raw if str(base).strip()]
