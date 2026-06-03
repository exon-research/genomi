"""GRCh37 <-> GRCh38 coordinate lift-over.

Wraps the pure-Python ``pyliftover`` package so any Genomi capability that needs
to translate coordinates between human genome builds can do so without
reimplementing UCSC chain-file parsing. The wrapper is the canonical entry
point — capabilities should not import ``pyliftover`` directly.

Inputs and outputs are 1-based VCF-style coordinates; ``pyliftover`` works in
0-based BED coordinates under the hood, and this module translates at the
boundary.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from .libraries import manager as library_manager
from .paths import genomi_data_root

_BUILD_ALIASES: dict[str, str] = {
    "grch37": "GRCh37",
    "hg19": "GRCh37",
    "37": "GRCh37",
    "b37": "GRCh37",
    "grch38": "GRCh38",
    "hg38": "GRCh38",
    "38": "GRCh38",
    "b38": "GRCh38",
}

_UCSC_BUILD = {"GRCh37": "hg19", "GRCh38": "hg38"}

CHAIN_FILES: dict[tuple[str, str], str] = {
    ("GRCh38", "GRCh37"): "hg38ToHg19.over.chain.gz",
    ("GRCh37", "GRCh38"): "hg19ToHg38.over.chain.gz",
}
# Chain-file source URLs live in the central registry ("liftover-chains").
LIFTOVER_CHAIN_LIBRARY = "liftover-chains"
PYLIFTOVER_REQUIREMENT = "pyliftover>=0.4"
PYLIFTOVER_INSTALL_COMMAND = f"python3 -m pip install '{PYLIFTOVER_REQUIREMENT}'"


class LiftoverConfigurationError(RuntimeError):
    """Raised when a required chain file is missing or pyliftover is unusable."""


def liftover_resources_dir(root: str | Path | None = None) -> Path:
    return genomi_data_root(root) / "resources" / "liftover"


def chain_file_path(
    source_build: str,
    target_build: str,
    *,
    root: str | Path | None = None,
) -> Path:
    src, tgt = normalize_build(source_build), normalize_build(target_build)
    try:
        filename = CHAIN_FILES[(src, tgt)]
    except KeyError as exc:
        raise LiftoverConfigurationError(
            f"no chain file registered for {src} -> {tgt}"
        ) from exc
    return liftover_resources_dir(root) / filename


def normalize_build(value: str) -> str:
    key = (value or "").strip().lower()
    try:
        return _BUILD_ALIASES[key]
    except KeyError as exc:
        raise ValueError(
            f"unsupported genome build for liftover: {value!r} "
            f"(expected one of GRCh37/hg19, GRCh38/hg38)"
        ) from exc


def liftover_preflight(
    source_build: str,
    target_build: str,
    *,
    root: str | Path | None = None,
    operation: str = "liftover.preflight",
    intent: str | None = None,
    genome_build: str | None = None,
) -> dict[str, Any]:
    """Return the single setup-readiness contract for coordinate liftover.

    Liftover needs two independent resources: UCSC chain data on disk and the
    Python ``pyliftover`` dependency that parses those chains. Callers should
    use this preflight instead of checking only the library registry.
    """

    src, tgt = normalize_build(source_build), normalize_build(target_build)
    setup_intent = intent or f"lifting coordinates from {src} to {tgt}"
    if src == tgt:
        return {
            "status": "not_required",
            "tool_will_work": True,
            "operation": operation,
            "intent": setup_intent,
            "genome_build": genome_build,
            "liftover_setup": {
                "source_build": src,
                "target_build": tgt,
                "required": False,
                "reason": "same_build",
            },
        }

    chain_path = chain_file_path(src, tgt, root=root)
    chain_status = library_manager.status(LIFTOVER_CHAIN_LIBRARY, root=root)
    package_status = _pyliftover_status()
    setup = {
        "source_build": src,
        "target_build": tgt,
        "required": True,
        "chain_file": {"path": str(chain_path), "exists": chain_path.is_file()},
        "chain_library": chain_status,
        "python_dependency": package_status,
    }
    if not chain_path.is_file():
        request = library_manager.missing_request(
            LIFTOVER_CHAIN_LIBRARY,
            intent=setup_intent,
            operation=operation,
            genome_build=genome_build,
            root=root,
        )
        request["reason"] = "missing_liftover_chain"
        request["liftover_setup"] = setup
        return request
    if not package_status["installed"]:
        request = _missing_pyliftover_request(
            package_status,
            operation=operation,
            intent=setup_intent,
            genome_build=genome_build,
        )
        request["reason"] = "missing_python_dependency"
        request["liftover_setup"] = setup
        return request
    return {
        "status": "available",
        "tool_will_work": True,
        "operation": operation,
        "intent": setup_intent,
        "genome_build": genome_build,
        "liftover_setup": setup,
    }


def _pyliftover_status() -> dict[str, Any]:
    error: str | None = None
    try:
        module = importlib.import_module("pyliftover")
        getattr(module, "LiftOver")
        installed = True
    except Exception as exc:
        installed = False
        error = str(exc)
    status = {
        "library": "pyliftover",
        "title": "pyliftover Python package",
        "kind": "python_package",
        "size_class": "small",
        "manual_source_required": False,
        "install_libraries": ["pyliftover"],
        "install_command": PYLIFTOVER_INSTALL_COMMAND,
        "helps": "parses UCSC liftOver chain files and performs local GRCh37/GRCh38 coordinate translation",
        "installed": installed,
        "status": "installed" if installed else "not_installed",
        "required_paths": [],
        "existing_paths": [],
        "missing_paths": [],
        "requirement": PYLIFTOVER_REQUIREMENT,
    }
    if error:
        status["error"] = error
    return status


def _missing_pyliftover_request(
    status: Mapping[str, Any],
    *,
    operation: str,
    intent: str,
    genome_build: str | None,
) -> dict[str, Any]:
    return {
        "status": "requires_library_install",
        "tool_will_work": False,
        "operation": operation,
        "intent": intent,
        "genome_build": genome_build,
        "missing_library": status,
        "how_it_helps": (
            f"For this intent ({intent}), pyliftover {status['helps']}."
        ),
        "ask_user": {
            "question": "The pyliftover Python package is not importable. Install it so Genomi can use UCSC chain files for this request?",
            "install_command": status["install_command"],
            "decline_effect": "The tool should skip liftover-dependent evidence and avoid interpreting setup gaps as negative evidence.",
        },
    }


def _preflight_error_message(preflight: Mapping[str, Any]) -> str:
    reason = str(preflight.get("reason") or preflight.get("status") or "unavailable")
    missing = preflight.get("missing_library")
    if isinstance(missing, Mapping):
        command = missing.get("install_command")
        title = missing.get("title") or missing.get("library")
        if command:
            return f"liftover setup unavailable ({reason}): {title}. Install with: {command}"
        return f"liftover setup unavailable ({reason}): {title}"
    return f"liftover setup unavailable ({reason})"


@dataclass(frozen=True)
class LiftRecordResult:
    lifted: list[dict[str, Any]]
    dropped: list[dict[str, Any]]


class LiftOver:
    """Translate coordinates from ``source_build`` to ``target_build``.

    Instances are cheap to keep around — chain parsing happens once at
    construction (a few hundred ms) and lookups are then in-memory.
    """

    def __init__(
        self,
        source_build: str,
        target_build: str,
        *,
        root: str | Path | None = None,
    ) -> None:
        self.source_build = normalize_build(source_build)
        self.target_build = normalize_build(target_build)
        if self.source_build == self.target_build:
            raise ValueError(
                "source_build and target_build are identical; no liftover needed"
            )
        preflight = liftover_preflight(self.source_build, self.target_build, root=root)
        if preflight.get("status") != "available":
            raise LiftoverConfigurationError(_preflight_error_message(preflight))
        self._chain_path = chain_file_path(self.source_build, self.target_build, root=root)
        try:
            from pyliftover import LiftOver as _PyLiftOver
        except ImportError as exc:  # pragma: no cover - declared as a hard dep
            raise LiftoverConfigurationError(
                _preflight_error_message(
                    {
                        "reason": "missing_python_dependency",
                        "missing_library": _pyliftover_status(),
                    }
                )
            ) from exc
        self._lifter = _PyLiftOver(
            str(self._chain_path),
            use_web=False,
            write_cache=False,
        )

    @property
    def chain_path(self) -> Path:
        return self._chain_path

    def lift_position(self, chrom: str, pos: int) -> tuple[str, int] | None:
        """Lift a single 1-based VCF position.

        Returns ``None`` if the position falls in a chain gap or maps to the
        negative strand (SNP-only callers should treat strand-flipped hits as
        unmappable; callers that need strand-aware behavior should use
        :meth:`lift_position_full`).
        """

        full = self.lift_position_full(chrom, pos)
        if full is None:
            return None
        target_chrom, target_pos, strand = full
        if strand != "+":
            return None
        return target_chrom, target_pos

    def lift_position_full(
        self, chrom: str, pos: int
    ) -> tuple[str, int, str] | None:
        """Lift a single position and return ``(chrom, pos, strand)`` or None.

        Used by callers that need to distinguish chain-gap misses from
        strand-flipped hits.
        """

        if pos < 1:
            return None
        # pyliftover takes a 0-based BED-style position; convert at the boundary.
        results = self._lifter.convert_coordinate(_ucsc_chrom(chrom), pos - 1)
        if not results:
            return None
        target_chrom, target_pos_zero, strand, _score = results[0]
        return _strip_chr_prefix_like(chrom, target_chrom), target_pos_zero + 1, strand

    def lift_records(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        chrom_field: str = "chrom",
        pos_field: str = "pos",
    ) -> LiftRecordResult:
        """Lift a stream of row-shaped records.

        Each record is shallow-copied with ``chrom_field`` and ``pos_field``
        replaced. Records that fail to lift are returned in ``dropped`` with a
        ``"liftover_reason"`` field added (``"unmapped"`` or
        ``"strand_flipped"``).
        """

        lifted: list[dict[str, Any]] = []
        dropped: list[dict[str, Any]] = []
        for record in records:
            chrom = record.get(chrom_field)
            pos_raw = record.get(pos_field)
            if chrom is None or pos_raw is None:
                dropped.append({**dict(record), "liftover_reason": "missing_coordinates"})
                continue
            try:
                pos = int(pos_raw)
            except (TypeError, ValueError):
                dropped.append({**dict(record), "liftover_reason": "invalid_position"})
                continue
            full = self.lift_position_full(chrom, pos)
            if full is None:
                dropped.append({**dict(record), "liftover_reason": "unmapped"})
                continue
            target_chrom, target_pos, strand = full
            if strand != "+":
                dropped.append(
                    {**dict(record), "liftover_reason": "strand_flipped"}
                )
                continue
            new_record = dict(record)
            new_record[chrom_field] = target_chrom
            new_record[pos_field] = target_pos
            lifted.append(new_record)
        return LiftRecordResult(lifted=lifted, dropped=dropped)


@lru_cache(maxsize=4)
def get_liftover(source_build: str, target_build: str) -> LiftOver:
    """Cached accessor; reuses the parsed chain file across callers."""

    return LiftOver(source_build, target_build)


def _ucsc_chrom(chrom: str) -> str:
    """pyliftover expects UCSC-style ``chrN`` contig names."""

    chrom = str(chrom).strip()
    if not chrom:
        return chrom
    if chrom.startswith("chr"):
        return chrom
    if chrom in {"MT", "mt"}:
        return "chrM"
    return f"chr{chrom}"


def _strip_chr_prefix_like(input_chrom: str, output_chrom: str) -> str:
    """Match the caller's contig naming convention.

    If the caller passed ``chr1`` we return ``chr1``; if they passed ``1`` we
    strip the ``chr`` prefix on the way out so records round-trip cleanly.
    """

    if input_chrom.startswith("chr"):
        return output_chrom
    if output_chrom.startswith("chr"):
        stripped = output_chrom[3:]
        if stripped == "M":
            return "MT" if input_chrom in {"MT", "mt"} else "M"
        return stripped
    return output_chrom
