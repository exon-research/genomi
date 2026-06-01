"""The Genomi data-source catalog — one ``LibrarySpec`` per source.

This is the single source of truth that replaces the catalogs previously
duplicated across ``scripts/_install_for_agents_lib.py`` (descriptions, sizes,
purposes, URLs, sha256/versions), ``runtime/library_status.py`` (titles, helps,
required paths), ``runtime/static_dependencies.py`` / ``runtime/liftover.py`` /
``analytical_grounding`` / ``phenotype`` / ``ancestry`` (per-source URLs +
paths). Every id is declared exactly once, here. Paths are RELATIVE to
GENOMI_HOME; the manager resolves them against the live data root.
"""

from __future__ import annotations

from pathlib import Path

from .spec import Freshness, Kind, LibrarySpec, Source, Transform

USER_AGENT = "Genomi installer/0.1 (+https://www.genomiagent.com/)"

# Pinned binary/panel releases. Bump version+sha256 here to ship a newer build.
_MINIMAP2_VERSION = "2.28"
_BWA_MEM2_VERSION = "2.2.1"
_ANCESTRY_PANEL_VERSION = "1.0.0"
_ANCESTRY_PANEL_FILES = (
    "manifest.json",
    "samples.tsv",
    "markers.tsv",
    "pca_loadings.tsv",
    "reference_scores.tsv",
    "panel_stats.json",
)


def _p(*parts: str) -> Path:
    return Path(*parts)


def _ancestry_required(panel_id: str) -> tuple[Path, ...]:
    return tuple(_p("reference", "ancestry", panel_id, name) for name in _ANCESTRY_PANEL_FILES)


_SPECS: tuple[LibrarySpec, ...] = (
    # ---- OFFLINE: rolling HTTP files (freshness via ETag/Last-Modified) ----
    LibrarySpec(
        id="clinvar-grch38",
        title="ClinVar VCF cache for GRCh38",
        helps="enables exact ClinVar allele matching and candidate variant triage against the Active Genome Index",
        kind=Kind.OFFLINE,
        size_class="~180 MB",
        purposes=("common-questions", "medication-response", "sequence-and-regions"),
        source=Source(urls=("https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz",)),
        transform=Transform.NONE,
        targets=(_p("resources", "clinvar", "GRCh38", "clinvar.vcf.gz"),),
        required_paths=(_p("resources", "clinvar", "GRCh38", "clinvar.vcf.gz"),),
    ),
    LibrarySpec(
        id="clinvar-grch37",
        title="ClinVar VCF cache for GRCh37",
        helps="enables exact ClinVar allele matching and candidate variant triage against the Active Genome Index",
        kind=Kind.OFFLINE,
        size_class="~180 MB",
        source=Source(urls=("https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh37/clinvar.vcf.gz",)),
        targets=(_p("resources", "clinvar", "GRCh37", "clinvar.vcf.gz"),),
        required_paths=(_p("resources", "clinvar", "GRCh37", "clinvar.vcf.gz"),),
    ),
    LibrarySpec(
        id="hpo",
        title="HPO phenotype annotation files",
        helps="maps HPO phenotype terms to genes and diseases for phenotype-driven interpretation",
        kind=Kind.OFFLINE,
        size_class="~100 MB",
        purposes=("common-questions", "medication-response"),
        source=Source(
            urls=(
                "https://purl.obolibrary.org/obo/hp/hpoa/phenotype_to_genes.txt",
                "https://purl.obolibrary.org/obo/hp/hpoa/phenotype.hpoa",
            ),
            user_agent="genomi/0.1",
        ),
        targets=(_p("resources", "hpo", "phenotype_to_genes.txt"), _p("resources", "hpo", "phenotype.hpoa")),
        required_paths=(_p("resources", "hpo", "phenotype_to_genes.txt"), _p("resources", "hpo", "phenotype.hpoa")),
    ),
    LibrarySpec(
        id="gencc",
        title="GenCC gene-disease validity TSV",
        helps="checks curated gene-disease validity when a question asks which genes plausibly explain a disease or phenotype",
        kind=Kind.OFFLINE,
        size_class="~25 MB",
        purposes=("common-questions", "medication-response"),
        source=Source(
            urls=("https://thegencc.org/download/action/submissions-export-tsv?format=new",),
            user_agent="genomi/0.1",
        ),
        targets=(_p("resources", "gencc", "gencc-submissions.tsv"),),
        required_paths=(_p("resources", "gencc", "gencc-submissions.tsv"),),
    ),
    LibrarySpec(
        id="gencode-grch38",
        title="GENCODE transcript annotation GTF for GRCh38",
        helps="annotates genomic regions with transcript and gene features on GRCh38",
        kind=Kind.OFFLINE,
        size_class="~100 MB",
        purposes=("sequence-and-regions",),
        source=Source(urls=("https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_49/gencode.v49.annotation.gtf.gz",)),
        targets=(_p("reference", "gencode", "gencode.v49.GRCh38.annotation.gtf.gz"),),
        required_paths=(_p("reference", "gencode", "gencode.v49.GRCh38.annotation.gtf.gz"),),
    ),
    LibrarySpec(
        id="gencode-grch37",
        title="GENCODE transcript annotation GTF for GRCh37",
        helps="annotates genomic regions with transcript and gene features on GRCh37",
        kind=Kind.OFFLINE,
        size_class="~100 MB",
        source=Source(urls=("https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_49/GRCh37_mapping/gencode.v49lift37.annotation.gtf.gz",)),
        targets=(_p("reference", "gencode", "gencode.v49lift37.GRCh37.annotation.gtf.gz"),),
        required_paths=(_p("reference", "gencode", "gencode.v49lift37.GRCh37.annotation.gtf.gz"),),
    ),
    LibrarySpec(
        id="encode-ccre-grch38",
        title="ENCODE cCRE BED for GRCh38",
        helps="annotates GRCh38 regions with candidate regulatory elements",
        kind=Kind.OFFLINE,
        size_class="~30 MB",
        purposes=("sequence-and-regions",),
        source=Source(urls=("https://users.moore-lab.org/ENCODE-cCREs/Supplementary-Data/Supplementary-Data-1.GRCh38-cCREs-V4.bed.gz",)),
        targets=(_p("reference", "encode", "encode-cCREs.V4.GRCh38.bed.gz"),),
        required_paths=(_p("reference", "encode", "encode-cCREs.V4.GRCh38.bed.gz"),),
    ),
    LibrarySpec(
        id="panglaodb-markers",
        title="PanglaoDB cell-type marker table",
        helps="retrieves canonical cell-type marker genes from PanglaoDB",
        kind=Kind.OFFLINE,
        size_class="~5 MB",
        purposes=("cell-and-tissue",),
        source=Source(urls=("https://panglaodb.se/markers/PanglaoDB_markers_27_Mar_2020.tsv.gz",)),
        targets=(_p("reference", "cell-markers", "PanglaoDB_markers_27_Mar_2020.tsv.gz"),),
        required_paths=(_p("reference", "cell-markers", "PanglaoDB_markers_27_Mar_2020.tsv.gz"),),
    ),
    LibrarySpec(
        id="liftover-chains",
        title="UCSC liftOver chain files for GRCh37 <-> GRCh38",
        helps="translates coordinates between GRCh37 and GRCh38 for any capability that has to align personal-genome and public-resource positions across builds",
        kind=Kind.OFFLINE,
        size_class="~3 MB",
        source=Source(
            urls=(
                "https://hgdownload.soe.ucsc.edu/goldenPath/hg19/liftOver/hg19ToHg38.over.chain.gz",
                "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/liftOver/hg38ToHg19.over.chain.gz",
            ),
        ),
        targets=(
            _p("resources", "liftover", "hg19ToHg38.over.chain.gz"),
            _p("resources", "liftover", "hg38ToHg19.over.chain.gz"),
        ),
        required_paths=(
            _p("resources", "liftover", "hg19ToHg38.over.chain.gz"),
            _p("resources", "liftover", "hg38ToHg19.over.chain.gz"),
        ),
    ),
    # ---- OFFLINE: reference FASTA (download .gz, gunzip, build .fai) ----
    LibrarySpec(
        id="reference-grch38",
        title="Reference FASTA for GRCh38",
        helps="supports normalization, genotype support checks, BAM-derived calls, and callability review",
        kind=Kind.OFFLINE,
        size_class="~3.2 GB",
        purposes=("sequence-and-regions", "wgs-alignment"),
        source=Source(urls=("https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/latest/hg38.fa.gz",)),
        transform=Transform.GUNZIP_FAIDX,
        targets=(_p("reference", "GRCh38", "hg38.fa"),),
        required_paths=(_p("reference", "GRCh38", "hg38.fa"), _p("reference", "GRCh38", "hg38.fa.fai")),
    ),
    LibrarySpec(
        id="reference-grch37",
        title="Reference FASTA for GRCh37",
        helps="supports normalization, genotype support checks, BAM-derived calls, and callability review",
        kind=Kind.OFFLINE,
        size_class="~3.1 GB",
        source=Source(urls=("https://hgdownload.soe.ucsc.edu/goldenPath/hg19/bigZips/latest/hg19.fa.gz",)),
        transform=Transform.GUNZIP_FAIDX,
        targets=(_p("reference", "GRCh37", "hg19.fa"),),
        required_paths=(_p("reference", "GRCh37", "hg19.fa"), _p("reference", "GRCh37", "hg19.fa.fai")),
    ),
    # ---- OFFLINE: XLSX normalized to a Genomi marker TSV ----
    LibrarySpec(
        id="cellmarker-human",
        title="CellMarker 2.0 human marker table",
        helps="retrieves human cell-type marker genes from CellMarker",
        kind=Kind.OFFLINE,
        size_class="~10 MB",
        purposes=("cell-and-tissue",),
        source=Source(urls=("https://bio-bigdata.hrbmu.edu.cn/CellMarker/CellMarker_download_files/file/Cell_marker_Human.xlsx",)),
        transform=Transform.XLSX_TO_TSV,
        targets=(_p("reference", "cell-markers", "CellMarker2_human_markers.normalized.tsv"),),
        required_paths=(_p("reference", "cell-markers", "CellMarker2_human_markers.normalized.tsv"),),
    ),
    # ---- OFFLINE: GitHub release-tag freshness ----
    LibrarySpec(
        id="pharmcat",
        title="PharmCAT all-in-one JAR for broad pharmacogenomic calling",
        helps="enables broad PGx star-allele calling, diplotype phenotype assignment, and CPIC/DPWG recommendation export against the Active Genome Index",
        kind=Kind.OFFLINE,
        size_class="~30 MB",
        purposes=("medication-response",),
        source=Source(
            github_release_api="https://api.github.com/repos/PharmGKB/PharmCAT/releases/latest",
            user_agent=USER_AGENT,
        ),
        freshness=Freshness.GITHUB_RELEASE_TAG,
        targets=(_p("tools", "pharmcat", "pharmcat.jar"),),
        required_paths=(_p("tools", "pharmcat", "pharmcat.jar"),),
    ),
    # ---- OFFLINE: pinned sha256 tarballs (Linux x86_64 only) ----
    LibrarySpec(
        id="minimap2-binary",
        title="minimap2 read aligner (long-read FASTQ → BAM)",
        helps="aligns long-read FASTQ to BAM so a personal genome can be derived from raw reads",
        kind=Kind.OFFLINE,
        size_class="~5 MB",
        purposes=("wgs-alignment",),
        source=Source(
            urls=(f"https://github.com/lh3/minimap2/releases/download/v{_MINIMAP2_VERSION}/minimap2-{_MINIMAP2_VERSION}_x64-linux.tar.bz2",),
            sha256="51f2cf0e486d0f9f88ace1aa58fdc56571382a676ea0889ae607301c60693377",
            version=_MINIMAP2_VERSION,
        ),
        freshness=Freshness.PINNED_SHA,
        transform=Transform.TAR_EXTRACT,
        targets=(_p("tools", "aligners", "minimap2", "minimap2"),),
        required_paths=(_p("tools", "aligners", "minimap2", "minimap2"),),
        platform_linux_x64_only=True,
    ),
    LibrarySpec(
        id="bwa-mem2-binary",
        title="bwa-mem2 read aligner (short-read FASTQ → BAM)",
        helps="aligns short-read FASTQ to BAM so a personal genome can be derived from raw reads",
        kind=Kind.OFFLINE,
        size_class="~50 MB",
        purposes=("wgs-alignment",),
        source=Source(
            urls=(f"https://github.com/bwa-mem2/bwa-mem2/releases/download/v{_BWA_MEM2_VERSION}/bwa-mem2-{_BWA_MEM2_VERSION}_x64-linux.tar.bz2",),
            sha256="b4cfdbce8cc07cdf3f6a920facabc29c976cf77dd53573369508111d6d1c555b",
            version=_BWA_MEM2_VERSION,
        ),
        freshness=Freshness.PINNED_SHA,
        transform=Transform.TAR_EXTRACT,
        targets=(_p("tools", "aligners", "bwa-mem2", "bwa-mem2"),),
        required_paths=(_p("tools", "aligners", "bwa-mem2", "bwa-mem2"),),
        platform_linux_x64_only=True,
    ),
    LibrarySpec(
        id="ancestry-1000g-30x-grch38",
        title="1000 Genomes 30x GRCh38 ancestry PCA panel",
        helps="enables local PCA projection and reference-neighbor context against public 1000 Genomes GRCh38 reference samples without external genotype upload",
        kind=Kind.OFFLINE,
        size_class="~3 MB",
        purposes=("ancestry-context",),
        source=Source(
            urls=(f"https://github.com/exon-research/genomi-ancestry-panel/releases/download/v{_ANCESTRY_PANEL_VERSION}/panel-1000g-30x-grch38-{_ANCESTRY_PANEL_VERSION}.tar.gz",),
            sha256="6ee6a021ec0bfe66c1808b077e423837c48a8962d09433a2bb4b4c0b5a230cf5",
            version=_ANCESTRY_PANEL_VERSION,
        ),
        freshness=Freshness.PINNED_SHA,
        transform=Transform.TAR_EXTRACT,
        targets=(_p("reference", "ancestry", "1000g_30x_grch38"),),
        required_paths=_ancestry_required("1000g_30x_grch38"),
    ),
    # ---- DERIVED: built locally from other libraries ----
    LibrarySpec(
        id="ancestry-1000g-30x-grch37",
        title="1000 Genomes ancestry PCA panel lifted to GRCh37",
        helps="enables local PCA projection and reference-neighbor context for samples on the GRCh37/hg19 build; produced locally by lifting the GRCh38 panel via UCSC chain files",
        kind=Kind.DERIVED,
        size_class="~3 MB",
        source=Source(derived_from=("ancestry-1000g-30x-grch38", "liftover-chains")),
        freshness=Freshness.DERIVED,
        targets=(_p("reference", "ancestry", "1000g_30x_grch37"),),
        required_paths=_ancestry_required("1000g_30x_grch37"),
    ),
    # ---- MANUAL: user supplies the source file ----
    LibrarySpec(
        id="msigdb-hallmark",
        title="MSigDB Hallmark GMT",
        helps="retrieves Hallmark pathway member genes from a user-supplied official MSigDB export",
        kind=Kind.MANUAL,
        size_class="user-supplied",
        freshness=Freshness.MANUAL,
        targets=(_p("reference", "msigdb", "hallmark.symbols.gmt"),),
        required_paths=(_p("reference", "msigdb", "hallmark.symbols.gmt"),),
        manual_source_required=True,
    ),
    # ---- ONLINE: live public APIs (never cached offline) ----
    LibrarySpec(
        id="gnomad",
        title="gnomAD population allele frequencies (live API)",
        helps="fetches public population allele frequencies for a specific variant from the gnomAD GraphQL API",
        kind=Kind.ONLINE,
        size_class="online",
        source=Source(api_base="https://gnomad.broadinstitute.org/api"),
        freshness=Freshness.LIVE,
    ),
    LibrarySpec(
        id="pgs-catalog",
        title="PGS Catalog (live REST API)",
        helps="fetches polygenic score metadata and scoring-file references from the PGS Catalog REST API",
        kind=Kind.ONLINE,
        size_class="online",
        source=Source(api_base="https://www.pgscatalog.org/rest"),
        freshness=Freshness.LIVE,
    ),
    LibrarySpec(
        id="pgxdb",
        title="PGxDB pharmacogenomics (live REST API)",
        helps="fetches gene-drug and variant pharmacogenomic records from the PGxDB REST API",
        kind=Kind.ONLINE,
        size_class="online",
        source=Source(api_base="https://pgx-db.org/rest-api"),
        freshness=Freshness.LIVE,
    ),
    LibrarySpec(
        id="fda-pgx",
        title="FDA pharmacogenomic biomarker tables (live)",
        helps="reads the FDA pharmacogenomic biomarker and pharmacogenetic-association tables from fda.gov",
        kind=Kind.ONLINE,
        size_class="online",
        source=Source(api_base="https://www.fda.gov/drugs/science-and-research-drugs/table-pharmacogenomic-biomarkers-drug-labeling"),
        freshness=Freshness.LIVE,
    ),
    # ---- PARAMETERIZED: per-pgs_id PRS scoring-file cache (template) ----
    LibrarySpec(
        id="prs-scoring-file",
        title="PGS Catalog scoring file (per score id)",
        helps="imports and caches a specific published polygenic score's scoring file, keyed by PGS id and genome build",
        kind=Kind.PARAMETERIZED,
        size_class="varies",
        source=Source(api_base="https://www.pgscatalog.org/rest"),
        freshness=Freshness.MANUAL,
    ),
)

_REGISTRY: dict[str, LibrarySpec] = {spec.id: spec for spec in _SPECS}

# Install purposes (absorbs LIBRARY_PURPOSES). "everything" resolves lazily to
# all installable offline ids except manual-source ones — see purposes().
_PURPOSES: dict[str, tuple[str, ...]] = {
    "setup-only": (),
    "common-questions": ("clinvar-grch38", "hpo", "gencc"),
    "medication-response": ("clinvar-grch38", "hpo", "gencc", "pharmcat"),
    "ancestry-context": ("ancestry-1000g-30x-grch38",),
    "sequence-and-regions": ("clinvar-grch38", "reference-grch38", "gencode-grch38", "encode-ccre-grch38"),
    "cell-and-tissue": ("panglaodb-markers", "cellmarker-human"),
    "wgs-alignment": ("minimap2-binary", "bwa-mem2-binary", "reference-grch38"),
}


def get(library_id: str) -> LibrarySpec:
    try:
        return _REGISTRY[library_id.strip()]
    except KeyError as exc:
        raise ValueError(f"unknown Genomi library: {library_id}") from exc


def has(library_id: str) -> bool:
    return library_id.strip() in _REGISTRY


def all_specs() -> tuple[LibrarySpec, ...]:
    return _SPECS


def all_ids() -> list[str]:
    return [spec.id for spec in _SPECS]


def installable_ids() -> list[str]:
    """Offline-family ids that `genomi install` materializes (excludes online +
    the parameterized template)."""
    return [spec.id for spec in _SPECS if spec.is_offline and spec.kind.value != "parameterized"]


def default_everything() -> tuple[str, ...]:
    """All installable libraries except manual-source ones (= old DEFAULT_LIBRARIES)."""
    return tuple(i for i in installable_ids() if not get(i).manual_source_required)


def purposes() -> dict[str, tuple[str, ...]]:
    return {**_PURPOSES, "everything": default_everything()}


def resolve_selection(selection: str) -> list[str]:
    """A purpose name, or comma-separated exact library ids → ordered id list.

    Absorbs parse_library_selection / resolve_library_selection.
    """
    value = (selection or "").strip()
    if not value:
        return []
    purpose_map = purposes()
    if value in purpose_map:
        return list(purpose_map[value])
    ids: list[str] = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        if not has(token):
            raise ValueError(
                f"unknown Genomi library or purpose: {token}. "
                f"Purposes: {', '.join(sorted(purpose_map))}. Libraries: {', '.join(all_ids())}."
            )
        ids.append(token)
    return ids
