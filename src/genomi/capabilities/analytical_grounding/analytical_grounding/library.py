from __future__ import annotations

from pathlib import Path

from ....runtime.paths import genomi_data_root
from .constants import ANALYTICAL_LIBRARY_RELATIVE_PATHS
from .helpers import _normalize_assembly, _normalize_cell_marker_source


def analytical_library_path(name: str, *, root: str | Path | None = None) -> Path:
    try:
        relative = ANALYTICAL_LIBRARY_RELATIVE_PATHS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown analytical grounding library: {name}") from exc
    return genomi_data_root(root) / relative


def installed_analytical_library_path(name: str, *, root: str | Path | None = None) -> Path | None:
    path = analytical_library_path(name, root=root)
    return path if path.is_file() else None


def default_gencode_gtf_path(assembly: str, *, root: str | Path | None = None) -> Path | None:
    assembly_label = _normalize_assembly(assembly)
    if not assembly_label:
        return None
    key = f"gencode-{assembly_label.lower()}"
    return installed_analytical_library_path(key, root=root)


def default_encode_ccre_bed_path(assembly: str, *, root: str | Path | None = None) -> Path | None:
    assembly_label = _normalize_assembly(assembly)
    if not assembly_label:
        return None
    key = f"encode-ccre-{assembly_label.lower()}"
    return installed_analytical_library_path(key, root=root)


def default_marker_table_path(source: str, *, root: str | Path | None = None) -> Path | None:
    source_key = _normalize_cell_marker_source(source)
    if source_key == "panglaodb":
        return installed_analytical_library_path("panglaodb-markers", root=root)
    if source_key == "cellmarker":
        return installed_analytical_library_path("cellmarker-human", root=root)
    return None


def _cell_marker_library_for_source(source: str) -> str | None:
    source_key = _normalize_cell_marker_source(source)
    if source_key == "panglaodb":
        return "panglaodb-markers"
    if source_key == "cellmarker":
        return "cellmarker-human"
    return None
