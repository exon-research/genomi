from __future__ import annotations

import csv
import gzip
import hashlib
import json
import shutil
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...runtime.paths import prs_score_dir
from ...runtime.sqlite_support import connect_sqlite
from . import pgs_catalog, source_context

JsonObject = dict[str, Any]
SCHEMA_VERSION = "genomi-prs-score-cache-v1"
MANIFEST_NAME = "manifest.json"
VARIANTS_DB_NAME = "variants.sqlite"
SOURCE_FILE_NAME = "scoring_file.txt.gz"
USER_AGENT = "Genomi PRS scoring-file importer/0.1"


def import_scoring_file(
    *,
    pgs_id: str | None = None,
    genome_build: str = "GRCh38",
    scoring_file: str | Path | None = None,
    scoring_url: str | None = None,
    force: bool = False,
) -> JsonObject:
    normalized_build = normalize_build(genome_build)
    clean_pgs_id = pgs_catalog.normalize_pgs_id(pgs_id)
    rest_metadata: JsonObject = {}
    source_url = scoring_url
    if not scoring_file and not source_url and clean_pgs_id:
        try:
            rest_metadata = pgs_catalog.fetch_rest_metadata(clean_pgs_id)
        except pgs_catalog.SourceUnavailable as exc:
            return pgs_catalog.source_unavailable_result(exc, schema="genomi-prs-score-import-v1")
        source_url = pgs_catalog.scoring_file_url_from_metadata(rest_metadata, normalized_build)
        if not source_url:
            return {
                "schema": "genomi-prs-score-import-v1",
                "status": "source_unavailable",
                "pgs_id": clean_pgs_id,
                "genome_build": normalized_build,
                "message": f"No PGS Catalog scoring file URL was available for {clean_pgs_id} on {normalized_build}.",
                "source_urls": source_context.source_urls(),
                "next_actions": [{"action": "supply_scoring_file_or_scoring_url"}],
            }

    if not scoring_file and not source_url:
        return {
            "schema": "genomi-prs-score-import-v1",
            "status": "invalid_params",
            "message": "Provide pgs_id, scoring_file, or scoring_url.",
            "source_urls": source_context.source_urls(),
        }

    if scoring_file:
        source_path = Path(scoring_file).expanduser()
        if not source_path.exists():
            return {
                "schema": "genomi-prs-score-import-v1",
                "status": "source_unavailable",
                "message": f"Local scoring file not found: {source_path}",
                "source_status": {"source": str(source_path), "error": "file_not_found"},
                "next_actions": [{"action": "provide_existing_scoring_file"}],
            }
        inferred_id = clean_pgs_id or _infer_pgs_id_from_name(source_path) or f"CUSTOM-{_short_file_hash(source_path)}"
        out_dir = prs_score_dir(inferred_id, normalized_build)
        if out_dir.exists() and not force and manifest_path(out_dir).exists():
            return _already_imported(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        cached_source = _copy_source(source_path, out_dir / _source_filename_for(source_path))
        source_label = str(source_path)
    else:
        assert source_url is not None
        inferred_id = clean_pgs_id or _infer_pgs_id_from_name(Path(urllib.request.url2pathname(source_url))) or "CUSTOM"
        out_dir = prs_score_dir(inferred_id, normalized_build)
        if out_dir.exists() and not force and manifest_path(out_dir).exists():
            return _already_imported(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        cached_source = out_dir / SOURCE_FILE_NAME
        try:
            _download_source(source_url, cached_source)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {
                "schema": "genomi-prs-score-import-v1",
                "status": "source_unavailable",
                "pgs_id": inferred_id,
                "genome_build": normalized_build,
                "source_status": {"source": source_url, "error": str(exc)},
                "source_urls": source_context.source_urls(),
                "next_actions": [{"action": "retry_later_or_supply_local_scoring_file"}],
            }
        source_label = source_url

    try:
        parsed = parse_scoring_file(cached_source)
    except (OSError, ValueError, UnicodeError) as exc:
        return {
            "schema": "genomi-prs-score-import-v1",
            "status": "invalid_scoring_file",
            "pgs_id": clean_pgs_id or inferred_id,
            "genome_build": normalized_build,
            "message": str(exc),
            "source": source_label,
            "limitations": source_context.limitations(),
            "next_actions": [{"action": "provide_valid_pgs_scoring_file"}],
        }
    if not parsed["variants"]:
        return {
            "schema": "genomi-prs-score-import-v1",
            "status": "invalid_scoring_file",
            "pgs_id": clean_pgs_id or parsed.get("pgs_id") or inferred_id,
            "genome_build": normalized_build,
            "message": "The scoring file did not contain any usable variant weight rows.",
            "skipped": parsed["skipped"],
            "source": source_label,
            "limitations": source_context.limitations(),
            "next_actions": [{"action": "provide_valid_pgs_scoring_file"}],
        }
    score_id = clean_pgs_id or parsed.get("pgs_id") or inferred_id
    if score_id != inferred_id:
        target_dir = prs_score_dir(score_id, normalized_build)
        if target_dir != out_dir:
            if target_dir.exists() and force:
                shutil.rmtree(target_dir)
            if not target_dir.exists():
                out_dir.rename(target_dir)
                out_dir = target_dir
                cached_source = out_dir / cached_source.name

    db_path = variants_db_path(out_dir)
    write_variants_db(db_path, parsed["variants"])
    manifest = _manifest(
        score_id=score_id,
        genome_build=normalized_build,
        score_dir=out_dir,
        source_file=cached_source,
        source_label=source_label,
        parsed=parsed,
        rest_metadata=rest_metadata,
    )
    manifest_path(out_dir).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "schema": "genomi-prs-score-import-v1",
        "status": "completed",
        "pgs_id": score_id,
        "genome_build": normalized_build,
        "score_cache": _cache_summary(out_dir, manifest),
        "source_urls": source_context.source_urls(),
        "limitations": source_context.limitations(),
        "next_actions": [
            {"action": "check_score_overlap", "operation": "prs.check_score_overlap", "pgs_id": score_id, "genome_build": normalized_build},
            {"action": "calculate_score", "operation": "prs.calculate_score", "pgs_id": score_id, "genome_build": normalized_build},
        ],
    }


def list_imported_scores(root: str | Path | None = None) -> JsonObject:
    base = prs_score_dir("placeholder", "GRCh38", root=root).parents[1]
    records: list[JsonObject] = []
    if base.exists():
        for manifest in sorted(base.glob("*/*/manifest.json")):
            payload = read_manifest(manifest.parent)
            if payload:
                records.append(_cache_summary(manifest.parent, payload))
    return {
        "schema": "genomi-prs-score-cache-list-v1",
        "status": "completed",
        "score_count": len(records),
        "scores": records,
        "reference_dir": str(base),
    }


def resolve_score_cache(
    *,
    pgs_id: str | None = None,
    score_dir: str | Path | None = None,
    genome_build: str = "GRCh38",
) -> JsonObject:
    if score_dir:
        directory = Path(score_dir).expanduser()
    else:
        clean = pgs_catalog.normalize_pgs_id(pgs_id)
        if not clean:
            return _requires_score_import(pgs_id=pgs_id, genome_build=genome_build)
        directory = prs_score_dir(clean, normalize_build(genome_build))
    manifest = read_manifest(directory)
    if not manifest or not variants_db_path(directory).exists():
        return _requires_score_import(pgs_id=pgs_id, genome_build=genome_build, score_dir=directory)
    return {
        "status": "installed",
        "score_dir": str(directory),
        "manifest": manifest,
        "variants_db": str(variants_db_path(directory)),
    }


def score_cache_status(
    *,
    pgs_id: str | None,
    genome_build: str,
    score_dir: str | Path | None = None,
) -> JsonObject:
    clean = pgs_catalog.normalize_pgs_id(pgs_id)
    normalized_build = normalize_build(genome_build)
    directory = Path(score_dir).expanduser() if score_dir else prs_score_dir(clean or str(pgs_id or "unknown"), normalized_build)
    manifest = read_manifest(directory)
    installed = bool(manifest and variants_db_path(directory).exists())
    score_id = clean or str(pgs_id or manifest.get("pgs_id") or "").strip()
    title = f"PGS Catalog score {score_id}" if score_id else "PGS Catalog score"
    command = import_scoring_file_command(score_id, normalized_build) if score_id else ""
    helps = "Imports the public scoring file into Genomi's local PRS score cache so the approved local genome can be scored without uploading private genotypes."
    return {
        "library": score_id or "local_prs_score_cache",
        "title": title,
        "installed": installed,
        "status": "installed" if installed else "not_installed",
        "genome_build": normalized_build,
        "score_dir": str(directory),
        "manifest_path": str(manifest_path(directory)),
        "variants_db": str(variants_db_path(directory)),
        "install_command": command,
        "helps": helps,
    }


def load_variants(score_dir: str | Path) -> list[JsonObject]:
    path = variants_db_path(score_dir)
    with connect_sqlite(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            select variant_index, variant_id, rsid, chrom, pos, effect_allele,
                   other_allele, effect_weight, harmonized, palindromic,
                   source_row_number
            from score_variants
            order by variant_index
            """
        ).fetchall()
    output = []
    for row in rows:
        output.append(
            {
                "variant_index": int(row["variant_index"]),
                "variant_id": row["variant_id"],
                "rsid": row["rsid"],
                "chrom": row["chrom"],
                "pos": int(row["pos"]),
                "effect_allele": row["effect_allele"],
                "other_allele": row["other_allele"],
                "effect_weight": float(row["effect_weight"]),
                "harmonized": bool(row["harmonized"]),
                "palindromic": bool(row["palindromic"]),
                "source_row_number": int(row["source_row_number"]),
            }
        )
    return output


def read_manifest(score_dir: str | Path) -> JsonObject:
    path = manifest_path(score_dir)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def manifest_path(score_dir: str | Path) -> Path:
    return Path(score_dir) / MANIFEST_NAME


def variants_db_path(score_dir: str | Path) -> Path:
    return Path(score_dir) / VARIANTS_DB_NAME


def parse_scoring_file(path: str | Path) -> JsonObject:
    metadata: JsonObject = {}
    variants: list[JsonObject] = []
    skipped: dict[str, int] = {}
    header: list[str] | None = None
    delimiter = "\t"
    for line_number, raw_line in enumerate(_iter_text_lines(path), start=1):
        line = raw_line.rstrip("\n\r")
        if not line:
            continue
        if line.startswith("#"):
            _parse_metadata_line(line, metadata)
            continue
        if header is None:
            delimiter = "\t" if "\t" in line else " "
            header = _split_line(line, delimiter)
            continue
        row_values = _split_line(line, delimiter)
        if not header or len(row_values) < len(header):
            skipped["malformed_row"] = skipped.get("malformed_row", 0) + 1
            continue
        row = dict(zip(header, row_values, strict=False))
        parsed = _variant_from_row(row, line_number=line_number)
        if parsed.get("status") != "usable":
            reason = str(parsed.get("reason") or "unusable")
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        variants.append(parsed["variant"])
    if header is None:
        raise ValueError(f"scoring file has no header row: {path}")
    pgs_id = _metadata_value(metadata, "pgs_id", "PGS ID", "Polygenic Score (PGS) ID")
    return {
        "pgs_id": pgs_catalog.normalize_pgs_id(pgs_id),
        "metadata": metadata,
        "columns": header,
        "variants": variants,
        "variant_count": len(variants),
        "skipped": skipped,
        "harmonized": any(str(column).startswith("hm_") for column in header),
    }


def write_variants_db(path: str | Path, variants: Iterable[JsonObject]) -> None:
    db_path = Path(path)
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect_sqlite(db_path) as connection:
        connection.executescript(
            """
            create table score_variants (
              variant_index integer primary key,
              variant_id text,
              rsid text,
              chrom text not null,
              pos integer not null,
              effect_allele text not null,
              other_allele text,
              effect_weight real not null,
              harmonized integer not null,
              palindromic integer not null,
              source_row_number integer not null
            );
            create index score_variants_locus_idx on score_variants(chrom, pos);
            """
        )
        rows = []
        for index, variant in enumerate(variants):
            rows.append(
                (
                    index,
                    variant.get("variant_id"),
                    variant.get("rsid"),
                    variant["chrom"],
                    int(variant["pos"]),
                    str(variant["effect_allele"]).upper(),
                    str(variant.get("other_allele") or "").upper() or None,
                    float(variant["effect_weight"]),
                    1 if variant.get("harmonized") else 0,
                    1 if variant.get("palindromic") else 0,
                    int(variant.get("source_row_number") or 0),
                )
            )
        connection.executemany(
            """
            insert into score_variants(
              variant_index, variant_id, rsid, chrom, pos, effect_allele,
              other_allele, effect_weight, harmonized, palindromic,
              source_row_number
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def normalize_build(genome_build: str) -> str:
    lowered = str(genome_build or "").strip().lower()
    if lowered in {"grch38", "hg38", "38"}:
        return "GRCh38"
    if lowered in {"grch37", "hg19", "37"}:
        return "GRCh37"
    return str(genome_build or "").strip() or "GRCh38"


def _requires_score_import(
    *,
    pgs_id: str | None,
    genome_build: str,
    score_dir: Path | None = None,
) -> JsonObject:
    status = score_cache_status(pgs_id=pgs_id, genome_build=genome_build, score_dir=score_dir)
    normalized_build = str(status["genome_build"])
    score_id = str(status["library"]) if status.get("library") != "local_prs_score_cache" else str(pgs_id or "").strip()
    command = str(status.get("install_command") or "")
    ask_user: JsonObject | None = None
    if score_id:
        ask_user = {
            "question": f"{status['title']} is not in the local score cache. Import it from PGS Catalog now?",
            "install_command": command,
            "decline_effect": "Skip PRS calculation for this score; do not treat the missing local score file as negative risk evidence.",
        }
    next_actions: list[JsonObject] = []
    if score_id:
        next_actions.append(
            {
                "action": "import_scoring_file",
                "operation": "prs.import_scoring_file",
                "pgs_id": score_id,
                "genome_build": normalized_build,
                "install_command": command,
            }
        )
    else:
        next_actions.append({"action": "choose_pgs_id_or_supply_score_dir"})
    result: JsonObject = {
        "schema": "genomi-prs-score-required-v1",
        "status": "requires_score_import",
        "pgs_id": score_id or pgs_id,
        "genome_build": normalized_build,
        "score_dir": str(score_dir) if score_dir else None,
        "message": "Import the public or local scoring file before checking overlap or calculating a PRS.",
        "import_commands": [
            {
                "operation": "prs.import_scoring_file",
                "params": {"pgs_id": score_id or "<PGS_ID>", "genome_build": normalized_build},
                **({"command": command} if command else {}),
            }
        ],
        "missing_library": status,
        "how_it_helps": status["helps"],
        "source_urls": source_context.source_urls(),
        "limitations": source_context.limitations(),
        "next_actions": next_actions,
    }
    if ask_user:
        result["ask_user"] = ask_user
    return result


def import_scoring_file_command(pgs_id: str, genome_build: str) -> str:
    params = {"pgs_id": pgs_catalog.normalize_pgs_id(pgs_id) or str(pgs_id), "genome_build": normalize_build(genome_build)}
    return f"genomi call prs.import_scoring_file --params '{json.dumps(params, separators=(',', ':'))}'"


def _variant_from_row(row: JsonObject, *, line_number: int) -> JsonObject:
    chrom = _first_value(row, "hm_chr", "chr_name", "chromosome", "chrom", "chr")
    pos = _first_value(row, "hm_pos", "chr_position", "position", "pos")
    effect_allele = _first_value(row, "effect_allele", "effect allele")
    other_allele = _first_value(row, "other_allele", "reference_allele", "non_effect_allele", "hm_inferOtherAllele")
    weight = _first_value(row, "effect_weight", "weight", "beta")
    if not chrom or not pos or not effect_allele or not weight:
        return {"status": "skipped", "reason": "missing_required_columns"}
    try:
        parsed_pos = int(str(pos).replace(",", ""))
        parsed_weight = float(str(weight))
    except ValueError:
        return {"status": "skipped", "reason": "invalid_position_or_weight"}
    effect = _clean_allele(effect_allele)
    other = _clean_allele(other_allele)
    if not _is_supported_allele(effect) or (other and not _is_supported_allele(other)):
        return {"status": "skipped", "reason": "unsupported_allele"}
    rsid = _first_value(row, "hm_rsID", "rsID", "rsid", "rs_id")
    variant_id = _first_value(row, "hm_variant_id", "variant_id", "variantID") or rsid or f"{chrom}:{parsed_pos}:{effect}:{other}"
    harmonized = any(key.startswith("hm_") and row.get(key) not in (None, "") for key in row)
    return {
        "status": "usable",
        "variant": {
            "variant_id": str(variant_id),
            "rsid": str(rsid or ""),
            "chrom": _normalize_chrom(str(chrom)),
            "pos": parsed_pos,
            "effect_allele": effect,
            "other_allele": other,
            "effect_weight": parsed_weight,
            "harmonized": harmonized,
            "palindromic": _is_palindromic(effect, other),
            "source_row_number": line_number,
        },
    }


def _manifest(
    *,
    score_id: str,
    genome_build: str,
    score_dir: Path,
    source_file: Path,
    source_label: str,
    parsed: JsonObject,
    rest_metadata: JsonObject,
) -> JsonObject:
    return {
        "schema": SCHEMA_VERSION,
        "pgs_id": score_id,
        "genome_build": genome_build,
        "score_dir": str(score_dir),
        "source_file": str(source_file),
        "source": source_label,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "variant_count": parsed["variant_count"],
        "skipped": parsed["skipped"],
        "harmonized": bool(parsed["harmonized"]),
        "scoring_file_metadata": parsed["metadata"],
        "pgs_catalog_metadata": pgs_catalog._score_summary(rest_metadata) if rest_metadata else {},
        "limitations": source_context.limitations(),
    }


def _cache_summary(score_dir: Path, manifest: JsonObject) -> JsonObject:
    return {
        "pgs_id": manifest.get("pgs_id"),
        "genome_build": manifest.get("genome_build"),
        "score_dir": str(score_dir),
        "manifest_path": str(manifest_path(score_dir)),
        "variants_db": str(variants_db_path(score_dir)),
        "variant_count": manifest.get("variant_count"),
        "harmonized": manifest.get("harmonized"),
        "source": manifest.get("source"),
        "imported_at": manifest.get("imported_at"),
    }


def _already_imported(score_dir: Path) -> JsonObject:
    manifest = read_manifest(score_dir)
    return {
        "schema": "genomi-prs-score-import-v1",
        "status": "already_installed",
        "pgs_id": manifest.get("pgs_id"),
        "genome_build": manifest.get("genome_build"),
        "score_cache": _cache_summary(score_dir, manifest),
        "next_actions": [{"action": "calculate_score", "operation": "prs.calculate_score", "pgs_id": manifest.get("pgs_id")}],
    }


def _copy_source(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve(strict=False) != target.resolve(strict=False):
        shutil.copyfile(source, target)
    return target


def _download_source(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        target.write_bytes(response.read())


def _source_filename_for(path: Path) -> str:
    name = path.name
    if name.endswith(".gz"):
        return name
    return f"{name}.cached"


def _iter_text_lines(path: str | Path):
    source = Path(path)
    opener = gzip.open if source.name.endswith(".gz") else open
    with opener(source, "rt", encoding="utf-8", errors="replace", newline="") as handle:
        yield from handle


def _split_line(line: str, delimiter: str) -> list[str]:
    if delimiter == "\t":
        return next(csv.reader([line], delimiter="\t"))
    return line.split()


def _parse_metadata_line(line: str, metadata: JsonObject) -> None:
    clean = line.lstrip("#").strip()
    if not clean or clean.startswith("#"):
        return
    if "=" in clean:
        key, value = clean.split("=", 1)
    elif ":" in clean:
        key, value = clean.split(":", 1)
    else:
        return
    key = key.strip().strip("#").strip().replace(" ", "_").lower()
    if key:
        metadata[key] = value.strip()


def _metadata_value(metadata: JsonObject, *keys: str) -> str:
    normalized = {str(key).strip().replace(" ", "_").lower(): value for key, value in metadata.items()}
    for key in keys:
        value = normalized.get(key.strip().replace(" ", "_").lower())
        if value not in (None, ""):
            return str(value)
    return ""


def _first_value(row: JsonObject, *names: str) -> str:
    by_lower = {str(key).strip().lower(): value for key, value in row.items()}
    for name in names:
        value = by_lower.get(name.strip().lower())
        if value not in (None, "", "NR", "NA"):
            return str(value).strip()
    return ""


def _clean_allele(value: object) -> str:
    return str(value or "").strip().upper()


def _is_supported_allele(value: str) -> bool:
    if not value or value in {".", "?", "NR"}:
        return False
    if any(char in value for char in "<>[]"):
        return False
    return all(base in {"A", "C", "G", "T", "I", "D"} for base in value)


def _is_palindromic(effect: str, other: str) -> bool:
    if len(effect) != 1 or len(other) != 1:
        return False
    return {effect, other} in ({"A", "T"}, {"C", "G"})


def _normalize_chrom(value: str) -> str:
    clean = value.strip()
    if clean.lower().startswith("chr"):
        return clean[3:]
    return clean


def _infer_pgs_id_from_name(path: Path) -> str:
    for part in [path.name, *path.parts]:
        clean = pgs_catalog.normalize_pgs_id(part[:9])
        if clean.startswith("PGS") and len(clean) == 9:
            return clean
    return ""


def _short_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12].upper()
