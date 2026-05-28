from __future__ import annotations

import contextlib
import gzip
import io
import json
import subprocess
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from .constants import (
    STRICT_PATHOGENIC_CLINSIG,
)



def _json_object(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _gene_symbols(gene_info: str) -> set[str]:
    symbols: set[str] = set()
    for token in gene_info.split("|"):
        symbol = token.split(":", 1)[0].strip()
        if symbol:
            symbols.add(symbol.upper())
    return symbols


def _clinvar_raw_info_rsids(raw_info_json: str) -> list[str]:
    try:
        raw_info = json.loads(raw_info_json)
    except json.JSONDecodeError:
        return []
    raw_rsids = raw_info.get("RS")
    if raw_rsids is None:
        return []
    if isinstance(raw_rsids, list):
        values = raw_rsids
    else:
        values = str(raw_rsids).replace("|", ",").split(",")
    rsids = []
    for value in values:
        token = str(value).strip()
        if not token or token == ".":
            continue
        rsids.append(token if token.lower().startswith("rs") else f"rs{token}")
    return _ordered_unique(iter(rsids))


def _chrom_lookup_values(chrom: str) -> list[str]:
    value = str(chrom)
    if value.startswith("chr"):
        return _ordered_unique(iter([value, value.removeprefix("chr")]))
    return _ordered_unique(iter([value, f"chr{value}"]))


def read_vcf_header_metadata(path: str | Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    opener = gzip.open if Path(path).suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("#CHROM"):
                break
            if not line.startswith("##") or "=" not in line:
                continue
            key, value = line[2:].rstrip("\r\n").split("=", 1)
            metadata.setdefault(key, value)
    return metadata


def _post_graphql(api_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "genomi/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"gnomAD API request failed: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"gnomAD API request failed: {exc}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"gnomAD API request timed out: {exc}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"gnomAD API response parse failed: {exc}") from exc


def _gnomad_metadata_key(dataset: str, genome_build: str, variant_id: str) -> str:
    return f"gnomad_fetch:{dataset}:{genome_build}:{variant_id}"


def _gnomad_source_labels(dataset: str) -> tuple[str, str]:
    return (_gnomad_source_label(dataset, "exome"), _gnomad_source_label(dataset, "genome"))


def _gnomad_source_label(dataset: str, sequencing_type: str) -> str:
    return f"{dataset}_{sequencing_type}"


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc


def _clinical_significance_components(clinical_significance: Counter[str]) -> set[str]:
    components: set[str] = set()
    for significance in clinical_significance:
        for component in significance.split("|"):
            component = component.strip()
            if component:
                components.add(component)
                for subcomponent in component.split("/"):
                    subcomponent = subcomponent.strip()
                    if subcomponent:
                        components.add(subcomponent)
    return components


def _has_strict_pathogenic_component(clinical_significance: Counter[str]) -> bool:
    return bool(_clinical_significance_components(clinical_significance) & STRICT_PATHOGENIC_CLINSIG)


def _optional_int_value(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ordered_unique(values: Iterator[Any]) -> list[Any]:
    seen: set[Any] = set()
    ordered: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _population_metadata_key(source: str, genome_build: str, population: str) -> str:
    return f"population_import:{source}:{genome_build}:{population}"


def _optional_int_info(
    info: dict[str, str | bool],
    field: str,
    alt_index: int,
    *,
    prefer_scalar: bool = False,
) -> int | None:
    value = _info_value(info, field, alt_index, prefer_scalar=prefer_scalar)
    if value is None or value in ("", "."):
        return None
    try:
        return int(value)
    except ValueError:
        try:
            return int(float(value))
        except ValueError:
            return None


def _optional_float_info(info: dict[str, str | bool], field: str, alt_index: int) -> float | None:
    value = _info_value(info, field, alt_index)
    if value is None or value in ("", "."):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _info_value(
    info: dict[str, str | bool],
    field: str,
    alt_index: int,
    *,
    prefer_scalar: bool = False,
) -> str | None:
    value = info.get(field)
    if value is None or value is True:
        return None
    raw = str(value)
    values = raw.split(",")
    if prefer_scalar and len(values) == 1:
        return values[0]
    if len(values) > alt_index:
        return values[alt_index]
    return raw


def _optional_int_value(value: Any) -> int | None:
    if value is None or value == ".":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _optional_float_value(value: Any) -> float | None:
    if value is None or value == ".":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iter_vcf_records(path: Path) -> Iterator[dict[str, Any]]:
    for _record, sample_records in _iter_vcf_record_groups(path):
        yield from sample_records


@contextlib.contextmanager
def _open_text_vcf(path: Path):
    if path.suffix != ".gz":
        with path.open("rt", encoding="utf-8", errors="replace") as fh:
            yield fh
        return
    # Prefer isal (Intel ISA-L C bindings, 3-5x faster than stdlib gzip), then
    # a subprocess decompressor for OS-level parallelism, then stdlib fallback.
    try:
        from isal import igzip as _igzip
        with _igzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            yield fh
        return
    except ImportError:
        pass
    for cmd in (["pigz", "-dc", str(path)], ["gzip", "-dc", str(path)]):
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            continue
        if proc.stdout is None:
            proc.wait()
            continue
        try:
            with io.TextIOWrapper(proc.stdout, encoding="utf-8", errors="replace") as fh:
                yield fh
        finally:
            if proc.poll() is None:
                proc.terminate()
            proc.wait()
        return
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        yield fh


def _iter_vcf_record_groups(path: Path) -> Iterator[tuple[dict[str, Any], list[dict[str, Any]]]]:
    with _open_text_vcf(path) as handle:
        sample_names: list[str] = []
        for line in handle:
            if line.startswith("#CHROM"):
                sample_names = line.rstrip("\r\n").split("\t")[9:]
                continue
            if not line or line.startswith("#"):
                continue
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) < 8:
                continue
            observed_sample_fields = max(0, len(parts) - 9)
            sample_count = min(len(sample_names), observed_sample_fields) if sample_names else observed_sample_fields
            base_record = {
                "chrom": parts[0],
                "pos": parts[1],
                "id": parts[2],
                "ref": parts[3],
                "alt": parts[4],
                "qual": parts[5],
                "filter": parts[6],
                "info": parts[7],
                "format": parts[8] if len(parts) > 8 else "",
                "sample": parts[9] if len(parts) > 9 else "",
                "sample_index": "0",
                "sample_name": sample_names[0] if sample_names else None,
            }
            sample_records = []
            for sample_index in range(sample_count or 1):
                sample_field_index = 9 + sample_index
                sample_records.append(
                    {
                        **base_record,
                        "sample": parts[sample_field_index] if len(parts) > sample_field_index else "",
                        "sample_index": str(sample_index),
                        "sample_name": sample_names[sample_index] if sample_index < len(sample_names) else None,
                    }
                )
            yield base_record, sample_records


def _none_if_dot(value: str) -> str | None:
    return None if value in ("", ".") else value


def _string_value(value: str | bool | None) -> str | None:
    if value is None or value is True:
        return None
    return str(value)


def _is_passing_filter(value: str) -> bool:
    return value in ("PASS", ".")
