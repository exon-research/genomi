from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_ACCESSION_RE = re.compile(r"\b(?:GSE|GSM|GDS)\d+\b", flags=re.I)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LOW_INFORMATION_CONTEXT_TOKENS = {
    "and",
    "cell",
    "cells",
    "dataset",
    "geo",
    "gene",
    "genes",
    "human",
    "in",
    "line",
    "of",
    "or",
    "screen",
    "study",
    "the",
    "to",
    "with",
}


def _value_supported_by_text(value: str, source_text: str) -> bool:
    value_tokens = set(_meaningful_tokens(value))
    source_tokens = set(_meaningful_tokens(source_text))
    if not value_tokens:
        return False
    return value_tokens <= source_tokens or _canonical(value) in _canonical(source_text)


def _meaningful_tokens(value: str) -> list[str]:
    return [
        token
        for token in _tokens(value)
        if len(token) > 1 and token not in _LOW_INFORMATION_CONTEXT_TOKENS
    ]


def _records_by_gene(records: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        for gene in record.get("genes") or []:
            grouped.setdefault(str(gene), []).append(record)
    return grouped


def _extract_accessions(*values: Any) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        for match in _ACCESSION_RE.findall(str(value or "")):
            accession = match.upper()
            if accession in seen:
                continue
            seen.add(accession)
            output.append(accession)
    return output


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        output: list[str] = []
        for item in value.values():
            output.extend(_flatten_strings(item))
        return output
    if isinstance(value, list):
        output: list[str] = []
        for item in value:
            output.extend(_flatten_strings(item))
        return output
    if value in (None, ""):
        return []
    return [str(value)]


def _dedupe_text(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _normalize_genes(genes: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for gene in genes:
        cleaned = _clean_text(gene).upper()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
    return output


def _table_key(value: Any) -> str:
    return " ".join(_tokens(str(value or "").replace("_", " ")))


def _tokens(value: str) -> list[str]:
    return _TOKEN_RE.findall(value.casefold())


def _canonical(value: Any) -> str:
    return "".join(_tokens(_clean_text(value)))


def _https_url(url: str) -> str:
    text = _clean_text(url)
    if text.startswith("ftp://"):
        return "https://" + text.removeprefix("ftp://")
    return text


def _clean_text(value: Any) -> str:
    return str(value or "").strip()
