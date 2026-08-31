from __future__ import annotations

from ...runtime.libraries import manager as library_manager
from .agi_store import JsonObject


def installed_reference_fasta(
    genome_build: str,
    *,
    intent: str = "reference FASTA for sequencing source parsing",
) -> JsonObject:
    library = f"reference-{genome_build.lower()}"
    status = library_manager.status(library)
    if not status.get("installed"):
        request = library_manager.missing_request(
            library,
            intent=intent,
            operation="genomi.parse_source",
            genome_build=genome_build,
        )
        return {
            "status": "requires_library_install",
            "library": library,
            "library_install_request": request,
            "missing_library": request["missing_library"],
            "ask_user": request["ask_user"],
        }
    required_paths = status.get("required_paths") or []
    reference_fasta = str(required_paths[0]) if required_paths else ""
    return {
        "status": "installed",
        "library": library,
        "reference_fasta": reference_fasta,
        "library_status": status,
    }
