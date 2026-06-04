from __future__ import annotations

from pathlib import Path
from typing import Any

from ....active_genome_index.active_genome_index import (
    ActiveGenomeIndexNeed,
    ActiveGenomeIndexReader,
    default_agi_path,
    open_reader,
)
from ....active_genome_index.export import export_variants
from ....active_genome_index.genotype_qc import assess_sample_qc
from ....active_genome_index.normalize import normalize_vcf
from ....active_genome_index.source_intake import parse_source as parse_genome_source
from ....evidence import (
    build_clinvar_annotation_index,
    build_clinvar_gene_index,
    build_clinvar_rsid_annotation_index,
    build_clinvar_rsid_index,
    default_evidence_path,
    evidence_summary,
    extract_clinvar_candidates,
    fetch_gnomad_variant,
    import_clinvar_vcf,
    import_population_vcf,
    match_clinvar_variants_from_active_genome_index,
    summarize_clinvar_matches,
)
from ....runtime.handoff import attach_evidence_context, evidence_context, workflow_step
from ....runtime.libraries import manager as library_manager
from ....runtime.paths import (
    default_export_variants_path,
    run_output_path,
)
from ....runtime.static_dependencies import resolve_genome_build

from ._helpers import (
    LONG_RUNNING_STATIC_REASON,
    WORKFLOW_AREA_ID,
    _has_clinvar_evidence,
    library_name_for_clinvar,
    _link_run_db_to_shared_static,
    _resolve_clinvar_cache_build,
    _reusable_static_db_with_clinvar,
    _shared_static_write_db,
    default_static_outputs,
    init_static_run,
    sync_static_evidence_to_shared,
    workflow_contract,
)


def build_static_annotation(
    vcf: str | Path,
    *,
    evidence_db: str | Path | None = None,
    source_evidence_db: str | Path | None = None,
    shared_evidence_db: str | Path | None = None,
    sync_shared: bool = True,
    reference_fasta: str | Path | None = None,
    genotype_reference_fasta: str | Path | None = None,
    auto_reference_fasta: bool = False,
    clinvar_vcf: str | Path | None = None,
    population_vcf: str | Path | None = None,
    population_source: str | None = None,
    population_version: str | None = None,
    primary_contigs_only: bool = True,
    chrom_style: str = "input",
    genome_build: str = "auto",
    force: bool = False,
    max_records: int | None = None,
    parallel_workers: int | None = None,
    allow_long_running_static: bool = False,
) -> dict[str, Any]:
    """Run raw VCF intake into an AGI-backed static evidence workflow.

    ``vcf`` is the raw intake source for this legacy static workflow. After the
    Active Genome Index is built, sample-level matching and QC read through the
    AGI reader boundary; public ``clinvar_vcf`` and ``population_vcf`` inputs
    remain true static-source VCF imports.
    """

    vcf_path = Path(vcf)
    init = init_static_run(
        vcf_path,
        source_evidence_db=source_evidence_db,
        shared_evidence_db=shared_evidence_db,
        force=force,
    )
    db_path = Path(evidence_db) if evidence_db is not None else Path(init["evidence_db"])
    shared_db_path = Path(shared_evidence_db) if shared_evidence_db is not None else Path(init["shared_evidence_db"])
    public_read_db_path = db_path
    public_write_db_path = db_path
    public_force = force
    agi_path = default_agi_path(vcf_path)
    exported_path = default_export_variants_path(
        vcf_path,
        pass_only=True,
        primary_contigs_only=primary_contigs_only,
        chrom_style=chrom_style,
    )

    steps: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    long_running_steps_deferred: list[str] = []

    def defer_long_running_step(name: str, reason: str = LONG_RUNNING_STATIC_REASON) -> None:
        long_running_steps_deferred.append(name)
        warnings.append({"stage": name, "status": "deferred", "message": reason})
        steps.append(
            workflow_step(
                name,
                {
                    "status": "deferred",
                    "reason": reason,
                    "resume_with": {
                        "operation": "focused evidence tool",
                        "hint": "Use clinvar.match_variants or an active_genome_index support tool when that library-specific evidence is needed.",
                    },
                },
                "static",
                reason="This static artifact is useful only when broad materialized source rows are explicitly needed.",
                commands=[
                    "genomi call clinvar.match_variants --params '{\"agi_path\":\"<agi.sqlite>\"}'",
                    "genomi call nutrigenomics.retrieve_domain_markers --params '{\"domain_id\":\"folate_metabolism\"}'",
                ],
            )
        )

    steps.append(
        workflow_step(
            "init-run",
            init,
            "static",
            reason="The run layout and evidence DB are ready; continue static preflight and Active Genome Indexing.",
            commands=["genomi call genomi.parse_source --params '{\"source\":\"<vcf>\"}'"],
        )
    )
    parse_result = parse_genome_source(
        vcf_path,
        evidence_db=db_path,
        source_evidence_db=source_evidence_db,
        shared_evidence_db=shared_db_path,
        genome_build=genome_build,
        force=force,
        max_records=max_records,
        parallel_workers=parallel_workers,
    )
    effective_genome_build = str(parse_result.get("genome_build") or resolve_genome_build(vcf_path, genome_build))
    steps.append(
        workflow_step(
            "parse-source",
            parse_result,
            "static",
            reason="The Active Genome Index can now feed deterministic sample QC and PASS variant export.",
            commands=["genomi call active_genome_index.classify_callset_qc --params '{\"agi_path\":\"<agi.sqlite>\"}'", "genomi call genomi.parse_source --params '{\"source\":\"<vcf>\"}'"],
        )
    )
    steps.append(
        workflow_step(
            "sample-qc",
            assess_sample_qc(
                vcf_path,
                agi_path=agi_path,
                evidence_db=db_path,
                output=run_output_path(vcf_path, "sample-qc.json"),
                genome_build=effective_genome_build,
            ),
            "static",
            reason="The sample QC handoff tells later research whether observed genotypes, missing alleles, and callability need extra checks.",
            commands=[
                "genomi call active_genome_index.classify_genotype_support --params '{\"agi_path\":\"<agi.sqlite>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\",\"reference_fasta\":\"<GRCh38.fa>\"}'",
                "genomi call active_genome_index.classify_region_callability --params '{\"agi_path\":\"<agi.sqlite>\",\"region\":\"<chrom:start-end>\"}'",
                "genomi call genomi.parse_source --params '{\"source\":\"<vcf>\"}'",
            ],
        )
    )
    resolved_reference_fasta = Path(reference_fasta) if reference_fasta is not None else None
    resolved_genotype_reference_fasta = Path(genotype_reference_fasta) if genotype_reference_fasta is not None else None
    if auto_reference_fasta and resolved_genotype_reference_fasta is None:
        if allow_long_running_static:
            dependency = library_manager.refresh(
                f"reference-{effective_genome_build.lower()}", force=force
            )
            steps.append(
                workflow_step(
                    "ensure-reference-fasta",
                    dependency,
                    "static",
                    reason="The matching reference FASTA is cached for genotype-support resolution of gVCF reference blocks.",
                    commands=[
                        "genomi call active_genome_index.classify_genotype_support --params '{\"agi_path\":\"<agi.sqlite>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\",\"reference_fasta\":\"<reference.fa>\"}'",
                        "genomi call genomi.parse_source --params '{\"source\":\"<vcf>\"}'",
                    ],
                )
            )
            resolved_genotype_reference_fasta = Path(dependency["output"])
            if resolved_reference_fasta is None:
                resolved_reference_fasta = resolved_genotype_reference_fasta
        else:
            defer_long_running_step(
                "ensure-reference-fasta",
                "Auto reference FASTA acquisition is deferred in the bounded static profile; targeted genotype-support tools can fetch it when needed.",
            )

    agi_comparable_variant_export: Path | None = None
    if allow_long_running_static or resolved_reference_fasta is not None:
        steps.append(
            workflow_step(
                "export-variants",
                export_variants(
                    agi_path,
                    exported_path,
                    pass_only=True,
                    primary_contigs_only=primary_contigs_only,
                    chrom_style=chrom_style,
                    max_records=max_records,
                    force=force,
                ),
                "static",
                reason="The exported comparable variant records can be normalized and matched against static databases.",
                commands=[
                    "genomi call genomi.parse_source --params '{\"source\":\"<vcf>\",\"reference_fasta\":\"<GRCh38.fa>\"}'",
                    "genomi call clinvar.match_variants --params '{\"agi_path\":\"<agi.sqlite>\"}'",
                ],
            )
        )
        agi_comparable_variant_export = exported_path
    else:
        defer_long_running_step(
            "export-variants",
            "Whole-callset PASS variant export is deferred because Active Genome Index matching does not need a materialized VCF.",
        )

    if resolved_reference_fasta is not None and agi_comparable_variant_export is not None:
        normalized = normalize_vcf(
            agi_comparable_variant_export,
            resolved_reference_fasta,
            allow_malformed_tags=True,
            force=force,
        )
        steps.append(
            workflow_step(
                "normalize",
                normalized,
                "static",
                reason="The normalized VCF is ready for exact static-source matching.",
                commands=[
                    "genomi call genomi.parse_source --params '{\"source\":\"<normalized.vcf>\"}'",
                    "genomi call clinvar.match_variants --params '{\"agi_path\":\"<agi.sqlite>\"}'",
                ],
            )
        )
        agi_comparable_variant_export = Path(normalized["output"])

    if clinvar_vcf is None and not _has_clinvar_evidence(public_read_db_path, effective_genome_build):
        clinvar_library = library_name_for_clinvar(effective_genome_build)
        clinvar_status = library_manager.status(clinvar_library)
        if clinvar_status["installed"]:
            clinvar_vcf = Path(clinvar_status["required_paths"][0])
            steps.append(
                workflow_step(
                    "select-clinvar-library",
                    {
                        "status": "installed",
                        "library": clinvar_library,
                        "clinvar_vcf": str(clinvar_vcf),
                        "library_status": clinvar_status,
                    },
                    "static",
                    reason="The installed ClinVar library can now be parsed into reusable static rows for this Active Genome Index.",
                    commands=["genomi call clinvar.match_variants --params '{\"agi_path\":\"<agi.sqlite>\"}'"],
                )
            )
        elif allow_long_running_static:
            dependency = library_manager.refresh(clinvar_library, force=public_force)
            steps.append(
                workflow_step(
                    "ensure-clinvar",
                    dependency,
                    "static",
                    reason="The matching ClinVar VCF is cached in the shared library and can be imported into the shared static evidence DB.",
                    commands=["genomi call genomi.parse_source --params '{\"source\":\"<vcf>\"}'"],
                )
            )
            clinvar_vcf = Path(library_manager.status(clinvar_library)["required_paths"][0])
        else:
            request = library_manager.missing_request(
                clinvar_library,
                intent="exact ClinVar annotation for variants in the Active Genome Index",
                operation="genomi.parse_source",
                genome_build=effective_genome_build,
            )
            warnings.append(
                {
                    "stage": "ensure-clinvar",
                    "status": "requires_library_install",
                    "message": f"{clinvar_library} is not installed; ClinVar static matching was not run.",
                    "library_install_request": request,
                }
            )
            steps.append(
                workflow_step(
                    "ensure-clinvar",
                    request,
                    "static",
                    reason="ClinVar static annotation needs an installed ClinVar library before Genomi can parse and match it.",
                    commands=[request["missing_library"]["install_command"]],
                )
            )

    imported_clinvar_db_path: Path | None = None
    if clinvar_vcf is not None or _has_clinvar_evidence(public_read_db_path, effective_genome_build):
        if clinvar_vcf is not None:
            steps.append(
                workflow_step(
                    "import-clinvar",
                    import_clinvar_vcf(
                        clinvar_vcf,
                        public_write_db_path,
                        genome_build=effective_genome_build,
                        force=public_force,
                    ),
                        "static",
                        reason="Imported ClinVar rows need a gene index before exact sample matching.",
                    commands=["genomi call clinvar.match_variants --params '{\"agi_path\":\"<agi.sqlite>\"}'"],
                )
            )
            imported_clinvar_db_path = public_write_db_path
        reusable_clinvar_db_path = _reusable_static_db_with_clinvar(
            public_read_db_path,
            shared_db_path,
            effective_genome_build,
            preferred_db=imported_clinvar_db_path,
        )
        steps.append(
            workflow_step(
                "index-clinvar-genes",
                build_clinvar_gene_index(reusable_clinvar_db_path, force=force),
                "static",
                reason="The ClinVar gene index is ready; match sample alleles to exact ClinVar assertions.",
                commands=["genomi call clinvar.match_variants --params '{\"agi_path\":\"<agi.sqlite>\"}'"],
            )
        )
        steps.append(
            workflow_step(
                "index-clinvar-rsids",
                build_clinvar_rsid_index(reusable_clinvar_db_path, force=force),
                "static",
                reason="The reusable ClinVar rsID index is ready for sample variants whose VCF IDs are rsIDs.",
                commands=["genomi call genomi.parse_source --params '{\"source\":\"<vcf>\"}'"],
            )
        )
        matches = run_output_path(vcf_path, "clinvar.matches.jsonl")
        active_genome_index_reader = open_reader(
            agi_path,
            need=ActiveGenomeIndexNeed.VARIANT,
            genome_build=effective_genome_build,
        )
        match_result = match_clinvar_variants_from_active_genome_index(
            active_genome_index_reader,
            public_read_db_path,
            matches,
            genome_build=effective_genome_build,
            max_records=max_records,
            force=force,
        )
        steps.append(
            workflow_step(
                "match-clinvar",
                match_result,
                "static",
                reason="Exact ClinVar matches can now be summarized and turned into deterministic candidate inventory.",
                commands=["genomi call clinvar.scan_candidates"],
            )
        )
        steps.append(
            workflow_step(
                "summarize-clinvar-matches",
                summarize_clinvar_matches(matches, matches.with_suffix(".summary.json"), force=force),
                "static",
                reason="The match summary is static context; build the candidate inventory next.",
                commands=["genomi call clinvar.scan_candidates"],
            )
        )
        steps.append(
            workflow_step(
                "index-clinvar-annotations",
                build_clinvar_annotation_index(
                    matches,
                    run_output_path(vcf_path, "clinvar.annotations.json"),
                    force=force,
                ),
                "static",
                reason="All exact ClinVar annotations are materialized for downstream gene and source-field lookup.",
                commands=[
                    "genomi call genomi.parse_source --params '{\"source\":\"<vcf>\"}'",
                    "genomi call variant.gather_allele_context --params '{\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
                ],
            )
        )
        steps.append(
            workflow_step(
                "index-clinvar-rsid-annotations",
                build_clinvar_rsid_annotation_index(
                    active_genome_index_reader,
                    public_read_db_path,
                    run_output_path(vcf_path, "clinvar.rsid-annotations.json"),
                    genome_build=effective_genome_build,
                    force=force,
                ),
                "static",
                reason="VCF rsIDs are joined to reusable ClinVar source fields for downstream gene/source-field lookup.",
                commands=["genomi call genomi.parse_source --params '{\"source\":\"<vcf>\"}'"],
            )
        )
        steps.append(
            workflow_step(
                "scan-static-candidates",
                extract_clinvar_candidates(
                    matches,
                    db_path,
                    run_output_path(vcf_path, "clinvar.candidates.json"),
                    genome_build=effective_genome_build,
                    evidence_groups=[
                        "clinvar_p_lp",
                        "clinvar_drug_response",
                        "clinvar_conflicting",
                        "clinvar_risk_association_protective",
                        "clinvar_vus",
                    ],
                    force=force,
                ),
                "research",
                reason="Static candidate inventory is structured evidence; user-facing interpretation must move to intent research.",
                commands=[
                    "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
                    "genomi call variant.gather_gene_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"gene\":\"<gene>\"}'",
                    "genomi call research.build_target_packet --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"gene\",\"gene\":\"<gene>\"}'",
                ],
            )
        )

    if population_vcf is not None:
        if not population_source:
            raise ValueError("--population-source is required when --population-vcf is provided")
        steps.append(
            workflow_step(
                "import-population",
                import_population_vcf(
                    population_vcf,
                    public_write_db_path,
                    source=population_source,
                    source_version=population_version,
                    genome_build=effective_genome_build,
                    force=public_force,
                ),
                "research",
                reason="Reusable public population rows are available; research can use them to resolve target-specific context.",
                commands=[
                    "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
                ],
            )
        )

    shared_sync = None
    if sync_shared:
        shared_sync = sync_static_evidence_to_shared(db_path, shared_db_path)

    return {
        "workflow_area": WORKFLOW_AREA_ID,
        "status": "completed_with_warnings" if warnings else "completed",
        "contract": workflow_contract(),
        "static_profile": "long_running" if allow_long_running_static else "bounded",
        "long_running_steps_deferred": long_running_steps_deferred,
        "warnings": warnings,
        "agi_intake_source_path": str(vcf_path),
        "genome_build": effective_genome_build,
        "evidence_db": str(db_path),
        "shared_evidence_db": str(shared_db_path),
        "shared_sync": shared_sync,
        "agi_comparable_variant_export": (
            str(agi_comparable_variant_export) if agi_comparable_variant_export is not None else None
        ),
        "reference_fasta": str(resolved_reference_fasta) if resolved_reference_fasta else None,
        "genotype_reference_fasta": str(resolved_genotype_reference_fasta) if resolved_genotype_reference_fasta else None,
        "outputs": default_static_outputs(vcf_path),
        "steps": steps,
        "evidence_summary": evidence_summary(db_path),
        "evidence_context": evidence_context(
            "research",
            reason="Static evidence is structured and reusable; Journal source-review memory can add interpretation for the user's selected target.",
            commands=[
                "genomi call research.build_target_packet --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"gene\",\"gene\":\"<gene>\"}'",
                "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
                "genomi call variant.gather_gene_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"gene\":\"<gene>\"}'",
            ],
        ),
    }


def match_static_clinvar(
    vcf: str | Path,
    *,
    evidence_db: str | Path | None = None,
    output: str | Path | None = None,
    genome_build: str = "auto",
    force: bool = False,
) -> dict[str, Any]:
    # Personal-genome context comes only from the Active Genome Index. Resolve
    # the index for this sample and match against it; never read the raw source.
    vcf = Path(vcf)
    agi_path = default_agi_path(vcf)
    if not agi_path.exists():
        return {
            "status": "requires_active_genome_index",
            "message": "Select or parse an Active Genome Index before ClinVar matching.",
        }
    db_path = Path(evidence_db) if evidence_db is not None else default_evidence_path(vcf)
    output_path = Path(output) if output is not None else run_output_path(vcf, "clinvar.matches.jsonl")
    effective_genome_build = resolve_genome_build(vcf, genome_build)
    active_genome_index_reader = open_reader(
        agi_path,
        need=ActiveGenomeIndexNeed.VARIANT,
        genome_build=effective_genome_build,
    )
    return match_static_clinvar_from_active_genome_index(
        active_genome_index_reader,
        evidence_db=db_path,
        output=output_path,
        genome_build=effective_genome_build,
        force=force,
    )


def match_static_clinvar_from_active_genome_index(
    reader: ActiveGenomeIndexReader,
    *,
    evidence_db: str | Path,
    output: str | Path,
    genome_build: str = "GRCh38",
    force: bool = False,
    operation: str = "clinvar.match_variants",
    intent: str = "ClinVar matching for this Active Genome Index",
) -> dict[str, Any]:
    agi_path = reader.agi_path
    db_path = Path(evidence_db)
    output_path = Path(output)
    effective_genome_build = resolve_genome_build(agi_path, genome_build)
    cache_build, missing_library = _resolve_clinvar_cache_build(
        db_path,
        effective_genome_build,
        force=force,
        operation=operation,
        intent=intent,
    )
    if missing_library is not None:
        return missing_library
    return attach_evidence_context(
        match_clinvar_variants_from_active_genome_index(
            reader,
            db_path,
            output_path,
            genome_build=effective_genome_build,
            cache_genome_build=cache_build,
            force=force,
        ),
        "static",
        reason="Provenance-marked ClinVar matches should be scanned into a deterministic candidate inventory.",
        commands=["genomi call clinvar.scan_candidates"],
    )


def scan_static_candidates(
    matches: str | Path,
    *,
    evidence_db: str | Path | None = None,
    output: str | Path | None = None,
    genome_build: str = "GRCh38",
    force: bool = False,
) -> dict[str, Any]:
    from ._helpers import _evidence_from_matches

    db_path = Path(evidence_db) if evidence_db is not None else _evidence_from_matches(matches)
    output_path = Path(output) if output is not None else run_output_path(matches, "clinvar.candidates.json")
    return attach_evidence_context(
        extract_clinvar_candidates(
            matches,
            db_path,
            output_path,
            genome_build=genome_build,
            evidence_groups=[
                "clinvar_p_lp",
                "clinvar_drug_response",
                "clinvar_conflicting",
                "clinvar_risk_association_protective",
                "clinvar_vus",
            ],
            force=force,
        ),
        "research",
        reason="Candidate inventory is static evidence; Journal source-review memory can add interpretation for agent-selected target scope.",
        commands=[
            "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
            "genomi call variant.gather_gene_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"gene\":\"<gene>\"}'",
        ],
    )


def fetch_static_population(
    evidence_db: str | Path,
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    *,
    shared_evidence_db: str | Path | None = None,
    sync_shared: bool = True,
    dataset: str = "gnomad_r4",
    genome_build: str = "GRCh38",
    api_url: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    run_db = Path(evidence_db)
    public_write_db = (
        _shared_static_write_db(run_db, shared_evidence_db=shared_evidence_db) if sync_shared else run_db
    )
    public_write_db.parent.mkdir(parents=True, exist_ok=True)
    if sync_shared and public_write_db.resolve() != run_db.resolve():
        _link_run_db_to_shared_static(run_db, public_write_db)
    try:
        result = fetch_gnomad_variant(
            public_write_db,
            chrom,
            pos,
            ref,
            alt,
            dataset=dataset,
            genome_build=genome_build,
            api_url=api_url or str(library_manager.get("gnomad").source.api_base or ""),
            force=force,
        )
    except RuntimeError as exc:
        message = str(exc)
        if not message.startswith("gnomAD API"):
            raise
        result = {
            "ok": False,
            "status": "source_unavailable",
            "evidence_db": str(public_write_db),
            "variant_id": f"{chrom}-{pos}-{ref}-{alt}",
            "dataset": dataset,
            "genome_build": genome_build,
            "inserted_rows": 0,
            "found": None,
            "error": message,
            "population_frequency": {
                "query": {
                    "chrom": chrom,
                    "pos": pos,
                    "ref": ref,
                    "alt": alt,
                    "genome_build": genome_build,
                },
                "count": 0,
                "records": [],
            },
        }
    else:
        result.setdefault("ok", True)
    if sync_shared:
        result["run_evidence_db"] = str(run_db)
        result["public_write_db"] = str(public_write_db)
        result["shared_sync"] = {
            "status": "same_db" if public_write_db.resolve() == run_db.resolve() else "direct_shared_write",
            "shared_evidence_db": str(public_write_db),
            "evidence_context": evidence_context(
                "research",
                reason="Population evidence is stored in shared static evidence and visible through the run DB read-through views.",
                commands=[
                    "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'"
                ],
            ),
        }
    return attach_evidence_context(
        result,
        "research",
        reason="Population evidence is available as structured static evidence; return to intent research to apply it to the selected target.",
        commands=[
            "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
        ],
    )
