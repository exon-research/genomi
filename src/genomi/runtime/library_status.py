from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..capabilities.analytical_grounding.analytical_grounding import (
    analytical_library_path,
)
from .liftover import CHAIN_FILES, liftover_resources_dir
from .paths import (
    ancestry_reference_panel_dir,
    genomi_data_root,
    pharmcat_jar_path,
    shared_reference_dir,
)
from .static_dependencies import (
    REFERENCE_FASTA_FILENAMES,
    shared_clinvar_vcf_manifest_path,
    shared_clinvar_vcf_path,
)


@dataclass(frozen=True)
class LibrarySpec:
    name: str
    title: str
    helps: str
    size_class: str
    required_paths: tuple[Path, ...]
    install_libraries: tuple[str, ...]
    manual_source_required: bool = False


def library_name_for_clinvar(genome_build: str) -> str:
    build = _normalize_build_suffix(genome_build)
    return f"clinvar-{build}"


def library_name_for_reference(genome_build: str) -> str:
    build = _normalize_build_suffix(genome_build)
    return f"reference-{build}"


def library_status(name: str) -> dict[str, Any]:
    spec = _library_spec(name)
    existing = [path for path in spec.required_paths if path.exists()]
    missing = [path for path in spec.required_paths if not path.exists()]
    return {
        "library": spec.name,
        "title": spec.title,
        "installed": not missing,
        "status": "installed" if not missing else "not_installed",
        "size_class": spec.size_class,
        "manual_source_required": spec.manual_source_required,
        "required_paths": [str(path) for path in spec.required_paths],
        "existing_paths": [str(path) for path in existing],
        "missing_paths": [str(path) for path in missing],
        "install_libraries": list(spec.install_libraries),
        "install_command": _install_command_for_spec(spec),
        "helps": spec.helps,
    }


def library_install_request(
    name: str,
    *,
    intent: str,
    operation: str,
    genome_build: str | None = None,
) -> dict[str, Any]:
    status = library_status(name)
    return {
        "status": "requires_library_install",
        "tool_will_work": False,
        "operation": operation,
        "intent": intent,
        "genome_build": genome_build,
        "missing_library": status,
        "how_it_helps": _intent_help(status["library"], intent, status["helps"]),
        "ask_user": {
            "question": (
                f"{status['title']} is not installed. Install {', '.join(status['install_libraries'])} "
                f"so Genomi can use it for this request?"
            ),
            "install_command": status["install_command"],
            "decline_effect": "The tool should skip this evidence library and avoid interpreting missing library data as negative evidence.",
        },
    }


def install_command(libraries: tuple[str, ...] | list[str]) -> str:
    selected = ",".join(libraries)
    return f"genomi install --libraries {selected}"


def _install_command_for_spec(spec: LibrarySpec) -> str:
    command = install_command(spec.install_libraries)
    if spec.name == "msigdb-hallmark":
        return f"{command} --msigdb-gmt /path/to/h.all.v*.symbols.gmt"
    return command


def library_inventory() -> dict[str, Any]:
    statuses = [library_status(name) for name in _library_names()]
    return {
        "schema": "genomi-library-inventory-v1",
        "genomi_home": str(genomi_data_root()),
        "libraries": statuses,
        "summary": {
            "library_count": len(statuses),
            "installed_count": sum(1 for item in statuses if item["installed"]),
            "missing_count": sum(1 for item in statuses if not item["installed"]),
        },
    }


def _library_names() -> list[str]:
    return [
        "clinvar-grch38",
        "clinvar-grch37",
        "hpo",
        "gencc",
        "reference-grch38",
        "reference-grch37",
        "gencode-grch38",
        "gencode-grch37",
        "encode-ccre-grch38",
        "panglaodb-markers",
        "cellmarker-human",
        "msigdb-hallmark",
        "pharmcat",
        "ancestry-1000g-30x-grch38",
        "ancestry-1000g-30x-grch37",
        "liftover-chains",
    ]


def _library_spec(name: str) -> LibrarySpec:
    normalized = name.strip().lower()
    root = genomi_data_root()
    if normalized == "clinvar-grch38":
        return _clinvar_spec("GRCh38")
    if normalized == "clinvar-grch37":
        return _clinvar_spec("GRCh37")
    if normalized == "reference-grch38":
        return _reference_spec("GRCh38")
    if normalized == "reference-grch37":
        return _reference_spec("GRCh37")
    if normalized == "hpo":
        return LibrarySpec(
            "hpo",
            "HPO phenotype annotation files",
            "maps HPO phenotype terms to genes and diseases for phenotype-driven interpretation",
            "light",
            (root / "resources" / "hpo" / "phenotype_to_genes.txt", root / "resources" / "hpo" / "phenotype.hpoa"),
            ("hpo",),
        )
    if normalized == "gencc":
        return LibrarySpec(
            "gencc",
            "GenCC gene-disease validity TSV",
            "checks curated gene-disease validity when a question asks which genes plausibly explain a disease or phenotype",
            "light",
            (root / "resources" / "gencc" / "gencc-submissions.tsv",),
            ("gencc",),
        )
    if normalized == "pharmcat":
        return LibrarySpec(
            "pharmcat",
            "PharmCAT all-in-one JAR for broad pharmacogenomic calling",
            "enables broad PGx star-allele calling, diplotype phenotype assignment, and CPIC/DPWG recommendation export against the Active Genome Index",
            "medium",
            (pharmcat_jar_path(),),
            ("pharmcat",),
        )
    if normalized == "liftover-chains":
        chain_dir = liftover_resources_dir(root)
        chain_paths = tuple(
            chain_dir / filename for filename in sorted(CHAIN_FILES.values())
        )
        return LibrarySpec(
            "liftover-chains",
            "UCSC liftOver chain files for GRCh37 <-> GRCh38",
            "translates coordinates between GRCh37 and GRCh38 for any capability that has to align personal-genome and public-resource positions across builds",
            "light",
            chain_paths,
            ("liftover-chains",),
        )
    if normalized == "ancestry-1000g-30x-grch38":
        panel_dir = ancestry_reference_panel_dir("1000g_30x_grch38")
        return LibrarySpec(
            "ancestry-1000g-30x-grch38",
            "1000 Genomes 30x GRCh38 ancestry PCA panel",
            "enables local PCA projection and reference-neighbor context against public 1000 Genomes GRCh38 reference samples without external genotype upload",
            "large",
            (
                panel_dir / "manifest.json",
                panel_dir / "samples.tsv",
                panel_dir / "markers.tsv",
                panel_dir / "pca_loadings.tsv",
                panel_dir / "reference_scores.tsv",
                panel_dir / "panel_stats.json",
            ),
            ("ancestry-1000g-30x-grch38",),
        )
    if normalized == "ancestry-1000g-30x-grch37":
        panel_dir = ancestry_reference_panel_dir("1000g_30x_grch37")
        return LibrarySpec(
            "ancestry-1000g-30x-grch37",
            "1000 Genomes ancestry PCA panel lifted to GRCh37",
            "enables local PCA projection and reference-neighbor context against the public 1000 Genomes panel for samples on the GRCh37/hg19 build. Produced locally by lifting the GRCh38 panel via UCSC chain files; loadings and reference scores are coordinate-free and reused unchanged",
            "light",
            (
                panel_dir / "manifest.json",
                panel_dir / "samples.tsv",
                panel_dir / "markers.tsv",
                panel_dir / "pca_loadings.tsv",
                panel_dir / "reference_scores.tsv",
                panel_dir / "panel_stats.json",
            ),
            ("ancestry-1000g-30x-grch38", "liftover-chains", "ancestry-1000g-30x-grch37"),
        )
    analytical_titles = {
        "gencode-grch38": ("GENCODE transcript annotation GTF for GRCh38", "large", "annotates genomic regions with transcript and gene features on GRCh38"),
        "gencode-grch37": ("GENCODE transcript annotation GTF for GRCh37", "large", "annotates genomic regions with transcript and gene features on GRCh37"),
        "encode-ccre-grch38": ("ENCODE cCRE BED for GRCh38", "medium", "annotates GRCh38 regions with candidate regulatory elements"),
        "panglaodb-markers": ("PanglaoDB cell-type marker table", "light", "retrieves canonical cell-type marker genes from PanglaoDB"),
        "cellmarker-human": ("CellMarker 2.0 human marker table", "light", "retrieves human cell-type marker genes from CellMarker"),
        "msigdb-hallmark": ("MSigDB Hallmark GMT", "manual", "retrieves Hallmark pathway member genes from a user-supplied official MSigDB export"),
    }
    if normalized in analytical_titles:
        title, size_class, helps = analytical_titles[normalized]
        return LibrarySpec(
            normalized,
            title,
            helps,
            size_class,
            (analytical_library_path(normalized),),
            (normalized,),
            manual_source_required=normalized == "msigdb-hallmark",
        )
    raise ValueError(f"unknown Genomi library: {name}")


def _clinvar_spec(genome_build: str) -> LibrarySpec:
    name = library_name_for_clinvar(genome_build)
    build = "GRCh38" if name.endswith("grch38") else "GRCh37"
    return LibrarySpec(
        name,
        f"ClinVar VCF cache for {build}",
        "enables exact ClinVar allele matching and candidate variant triage against the Active Genome Index",
        "medium",
        (shared_clinvar_vcf_path(build), shared_clinvar_vcf_manifest_path(build)),
        (name,),
    )


def _reference_spec(genome_build: str) -> LibrarySpec:
    name = library_name_for_reference(genome_build)
    build = "GRCh38" if name.endswith("grch38") else "GRCh37"
    fasta = shared_reference_dir() / build / REFERENCE_FASTA_FILENAMES[build]
    return LibrarySpec(
        name,
        f"Reference FASTA for {build}",
        "supports normalization, genotype support checks, BAM-derived calls, and callability review",
        "large",
        (fasta, Path(f"{fasta}.fai")),
        (name,),
    )


def _normalize_build_suffix(genome_build: str) -> str:
    normalized = genome_build.strip().lower()
    if normalized in {"grch38", "hg38", "38"}:
        return "grch38"
    if normalized in {"grch37", "hg19", "37"}:
        return "grch37"
    raise ValueError(f"unsupported genome build for library status: {genome_build}")


def _intent_help(library: str, intent: str, default_help: str) -> str:
    clean_intent = intent.strip()
    if not clean_intent:
        return default_help
    return f"For this intent ({clean_intent}), {library} {default_help}."
