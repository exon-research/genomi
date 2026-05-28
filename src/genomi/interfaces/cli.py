from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from ..capabilities.clinvar import static_annotation
from ..capabilities.research import intent_research
from ..evidence import research_scope_choices, research_target_type_choices
from ..operations import (
    OperationError,
    call_operation,
    load_params,
    operation_discovery_payload,
)
from ..runtime.handoff import evidence_context
from . import mcp
from .presentation import present_result

# `genomi serve` (the MCP launcher), `genomi install` (setup install/update), and
# `genomi --help` are available without GENOMI_CLI=1. The variable is
# intentionally undocumented in agent-facing material.
_AGENT_ONLY_SUBCOMMANDS = ("tools", "call", "workflow", "static")
_CLI_GATE_ENV = "GENOMI_CLI"


def _cli_gate_active() -> bool:
    return os.environ.get(_CLI_GATE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _cli_gate_block_message(area: str) -> str:
    return f"genomi: `{area}` is not available from the shell. Use the MCP server."


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "area", None) in _AGENT_ONLY_SUBCOMMANDS and not _cli_gate_active():
        print(_cli_gate_block_message(args.area), file=sys.stderr)
        return 2
    try:
        payload = args.func(args)
    except OperationError as exc:
        print(json.dumps(exc.to_json(operation=getattr(args, "operation", None)), indent=2, sort_keys=True), file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"genomi: error: {exc}", file=sys.stderr)
        return 1
    if payload is not None:
        print(json.dumps(payload, indent=2, sort_keys=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="genomi",
        description="Agent-facing genomics runtime for local genome analysis and evidence-grounded DNA research.",
    )
    subparsers = parser.add_subparsers(dest="area", required=True)

    tools_parser = subparsers.add_parser("tools", help="List Genomi operation tools for agents and MCP clients.")
    tools_parser.add_argument("--capability", help="Limit discovery to one capability, such as pharmacogenomics or gwas-catalog.")
    tools_parser.add_argument("--namespace", help="Debug/audit filter for one operation namespace, such as runtime or active_genome_index.")
    tools_parser.set_defaults(func=_cmd_tools)

    call_parser = subparsers.add_parser("call", help="Call a Genomi operation by name with JSON parameters.")
    call_parser.add_argument("operation")
    call_parser.add_argument("--params", default=None, help="JSON object with operation parameters.")
    call_parser.add_argument("--params-file", type=Path, default=None, help="Path to a JSON object with operation parameters.")
    call_parser.add_argument(
        "--debug-raw",
        action="store_true",
        help="Dump the uncompacted result dict (developer use). Not exposed via MCP.",
    )
    call_parser.set_defaults(func=_cmd_call)

    serve_parser = subparsers.add_parser("serve", help="Serve Genomi tools over MCP stdio or HTTP.")
    serve_parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get("GENOMI_MCP_TRANSPORT", "stdio"),
        help="MCP transport to serve. Defaults to stdio for existing host configs.",
    )
    serve_parser.add_argument(
        "--host",
        default=os.environ.get("GENOMI_HTTP_HOST", mcp.DEFAULT_HTTP_HOST),
        help="HTTP bind host when --transport=http.",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", os.environ.get("GENOMI_HTTP_PORT", str(mcp.DEFAULT_HTTP_PORT)))),
        help="HTTP bind port when --transport=http.",
    )
    serve_parser.set_defaults(func=_cmd_serve)

    install_parser = subparsers.add_parser(
        "install",
        aliases=["update"],
        help="Install or update Genomi setup inside the current runtime. `genomi update` is an alias.",
    )
    install_parser.add_argument(
        "--libraries",
        default="setup-only",
        help=(
            "Library purpose or exact comma-separated library IDs, e.g. "
            "common-questions, medication-response, everything. Defaults to "
            "'setup-only': a bare `genomi install` updates the runtime and "
            "leaves reference libraries untouched. Re-running with a purpose is "
            "idempotent — it downloads only the libraries that are missing."
        ),
    )
    install_parser.add_argument(
        "--response-profile",
        choices=["eli5", "patient", "literate", "expert"],
        help="Persist the default response profile for downstream Genomi answers.",
    )
    install_parser.add_argument("--force", action="store_true", help="Refresh selected libraries even when cached.")
    install_parser.add_argument("--msigdb-gmt", help="Path to an official MSigDB Hallmark GMT export.")
    install_parser.add_argument("--msigdb-gmt-url", help="Download URL for an official MSigDB Hallmark GMT export.")
    install_parser.add_argument("--pharmcat-version", help="Pin a PharmCAT release tag.")
    install_parser.add_argument("--ancestry-panel-url", help="Override the ancestry panel tarball URL.")
    install_parser.add_argument("--ancestry-panel-dir", help="Copy a prebuilt compact ancestry panel directory.")
    install_parser.set_defaults(func=_cmd_install)

    workflow_parser = subparsers.add_parser("workflow", help="Print the agent runtime and evidence contracts.")
    workflow_parser.set_defaults(func=_cmd_workflow)

    return parser


def _cmd_tools(args: argparse.Namespace) -> dict[str, Any]:
    return operation_discovery_payload(capability=args.capability, namespace=args.namespace)


def _cmd_call(args: argparse.Namespace) -> dict[str, Any]:
    payload = call_operation(args.operation, load_params(args.params, args.params_file))
    if getattr(args, "debug_raw", False):
        return payload
    return present_result(args.operation, payload)


def _cmd_serve(args: argparse.Namespace) -> None:
    if args.transport == "http":
        raise SystemExit(mcp.serve_http(host=args.host, port=args.port))
    raise SystemExit(mcp.serve_stdio())


def _cmd_install(args: argparse.Namespace) -> dict[str, Any]:
    params: dict[str, Any] = {
        "libraries": args.libraries,
        "force": bool(args.force),
    }
    for attr in (
        "response_profile",
        "msigdb_gmt",
        "msigdb_gmt_url",
        "pharmcat_version",
        "ancestry_panel_url",
        "ancestry_panel_dir",
    ):
        value = getattr(args, attr, None)
        if value:
            params[attr] = value
    return call_operation("genomi.install", params)


def _add_static(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    area = subparsers.add_parser(
        "static",
        help="Active Genome Index creation and library-scoped evidence materialization; no LLM judgment.",
    )
    commands = area.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Create the run layout and evidence DB.")
    init.add_argument("vcf", type=Path)
    init.add_argument("--shared-db", type=Path, default=None)
    init.add_argument("--source-evidence-db", type=Path, default=None)
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=_cmd_static_init)

    run = commands.add_parser("run", help="Run the static VCF annotation pass.")
    run.add_argument("vcf", type=Path)
    run.add_argument("--db", type=Path, default=None)
    run.add_argument("--shared-db", type=Path, default=None)
    run.add_argument("--source-evidence-db", type=Path, default=None)
    run.add_argument("--no-sync-shared", action="store_true")
    run.add_argument("--reference-fasta", type=Path, default=None)
    run.add_argument("--genotype-reference-fasta", type=Path, default=None)
    run.add_argument("--no-auto-reference-fasta", dest="auto_reference_fasta", action="store_false")
    run.add_argument("--reference-root", type=Path, default=None)
    run.add_argument("--clinvar-vcf", type=Path, default=None)
    run.add_argument("--population-vcf", type=Path, default=None)
    run.add_argument("--population-source", default=None)
    run.add_argument("--population-version", default=None)
    run.add_argument("--primary-contigs-only", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--chrom-style", choices=["input", "no-chr", "chr"], default="input")
    run.add_argument("--genome-build", default="auto")
    run.add_argument("--max-records", type=int, default=None)
    run.add_argument("--force", action="store_true")
    run.set_defaults(func=_cmd_static_run, auto_reference_fasta=True)

    match = commands.add_parser("match-clinvar", help="Match a comparable VCF against imported ClinVar rows.")
    match.add_argument("vcf", type=Path)
    match.add_argument("--db", type=Path, default=None)
    match.add_argument("--output", type=Path, default=None)
    match.add_argument("--genome-build", default="auto")
    match.add_argument("--force", action="store_true")
    match.set_defaults(func=_cmd_static_match_clinvar)

    scan = commands.add_parser("scan-static", help="Build deterministic candidate inventory from ClinVar matches.")
    scan.add_argument("matches", type=Path)
    scan.add_argument("--db", type=Path, default=None)
    scan.add_argument("--output", type=Path, default=None)
    scan.add_argument("--genome-build", default="GRCh38")
    scan.add_argument("--force", action="store_true")
    scan.set_defaults(func=_cmd_static_scan_static)

    pop = commands.add_parser("fetch-population", help="Fetch reusable public population frequency for one allele.")
    pop.add_argument("--db", required=True, type=Path)
    pop.add_argument("--shared-db", type=Path, default=None)
    pop.add_argument("--no-sync-shared", action="store_true")
    pop.add_argument("chrom")
    pop.add_argument("pos", type=int)
    pop.add_argument("ref")
    pop.add_argument("alt")
    pop.add_argument("--dataset", default="gnomad_r4")
    pop.add_argument("--genome-build", default="GRCh38")
    pop.add_argument("--api-url", default="https://gnomad.broadinstitute.org/api")
    pop.add_argument("--force", action="store_true")
    pop.set_defaults(func=_cmd_static_fetch_population)

    qc = commands.add_parser("qc", help="Summarize sample callset type, quality fields, and evidence boundaries.")
    qc.add_argument("vcf", type=Path)
    qc.add_argument("--db", type=Path, default=None)
    qc.add_argument("--active-genome-index-path", type=Path, default=None)
    qc.add_argument("--output", type=Path, default=None)
    qc.add_argument("--genome-build", default="auto")
    qc.add_argument("--scan-records", type=int, default=1000)
    qc.set_defaults(func=_cmd_static_qc)

    support = commands.add_parser("genotype-support", help="Classify technical support for one sample allele or site.")
    support.add_argument("vcf", type=Path)
    support.add_argument("chrom")
    support.add_argument("pos", type=int)
    support.add_argument("ref")
    support.add_argument("alt")
    support.add_argument("--db", type=Path, default=None)
    support.add_argument("--active-genome-index-path", type=Path, default=None)
    support.add_argument("--output", type=Path, default=None)
    support.add_argument("--genome-build", default="auto")
    support.add_argument("--reference-fasta", type=Path, default=None)
    support.add_argument("--min-depth", type=int, default=10)
    support.add_argument("--min-gq", type=int, default=20)
    support.set_defaults(func=_cmd_static_genotype_support)

    callability = commands.add_parser("callability", help="Classify whether a region can support reference/absence claims.")
    callability.add_argument("vcf", type=Path)
    callability.add_argument("region")
    callability.add_argument("--db", type=Path, default=None)
    callability.add_argument("--active-genome-index-path", type=Path, default=None)
    callability.add_argument("--output", type=Path, default=None)
    callability.add_argument("--genome-build", default="auto")
    callability.add_argument("--min-depth", type=int, default=10)
    callability.add_argument("--min-covered-fraction", type=float, default=0.95)
    callability.add_argument("--limit", type=int, default=5000)
    callability.set_defaults(func=_cmd_static_callability)

    query = commands.add_parser("query", help="Query structured VCF/static evidence.")
    query_commands = query.add_subparsers(dest="query_command", required=True)
    rsid = query_commands.add_parser("rsid")
    rsid.add_argument("vcf", type=Path)
    rsid.add_argument("rsid")
    rsid.add_argument("--active-genome-index-path", type=Path, default=None)
    rsid.add_argument("--include-fail", action="store_true")
    rsid.add_argument("--limit", type=int, default=50)
    rsid.set_defaults(func=_cmd_static_query_rsid)
    region = query_commands.add_parser("region")
    region.add_argument("vcf", type=Path)
    region.add_argument("region")
    region.add_argument("--active-genome-index-path", type=Path, default=None)
    region.add_argument("--variants-only", action="store_true")
    region.add_argument("--include-fail", action="store_true")
    region.add_argument("--limit", type=int, default=200)
    region.set_defaults(func=_cmd_static_query_region)
    variant = query_commands.add_parser("variant")
    variant.add_argument("vcf", type=Path)
    variant.add_argument("chrom")
    variant.add_argument("pos", type=int)
    variant.add_argument("ref")
    variant.add_argument("alt")
    variant.add_argument("--active-genome-index-path", type=Path, default=None)
    variant.add_argument("--include-fail", action="store_true")
    variant.add_argument("--limit", type=int, default=50)
    variant.set_defaults(func=_cmd_static_query_variant)
    coverage = query_commands.add_parser("coverage")
    coverage.add_argument("vcf", type=Path)
    coverage.add_argument("region")
    coverage.add_argument("--active-genome-index-path", type=Path, default=None)
    coverage.add_argument("--limit", type=int, default=200)
    coverage.set_defaults(func=_cmd_static_query_coverage)

    summary = commands.add_parser("summary", help="Summarize static outputs and evidence DB.")
    summary.add_argument("vcf", type=Path)
    summary.add_argument("--db", type=Path, default=None)
    summary.set_defaults(func=_cmd_static_summary)


def _add_research(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    area = subparsers.add_parser(
        "research",
        help="Intent-scoped LLM research using structured evidence packets and reviewed-source write-back.",
    )
    commands = area.add_subparsers(dest="command", required=True)

    catalog = commands.add_parser("sources", help="List relevant public sources for a target type.")
    catalog.add_argument("--target-type", choices=research_target_type_choices(), default=None)
    catalog.add_argument("--source-id", default=None)
    catalog.set_defaults(func=_cmd_research_sources)

    packet = commands.add_parser("packet", help="Build target-centric packet after the agent infers user intent.")
    _add_target_args(packet, require_type=True)
    packet.add_argument("--db", required=True, type=Path)
    packet.add_argument("--source-id", default=None)
    packet.add_argument("--limit", type=int, default=20)
    packet.set_defaults(func=_cmd_research_packet)

    gather_allele = commands.add_parser("gather-allele", help="Gather existing sample/static/research evidence for one allele.")
    gather_allele.add_argument("--db", required=True, type=Path)
    gather_allele.add_argument("chrom")
    gather_allele.add_argument("pos", type=int)
    gather_allele.add_argument("ref")
    gather_allele.add_argument("alt")
    gather_allele.add_argument("--matches", type=Path, default=None)
    gather_allele.add_argument("--genome-build", default="GRCh38")
    gather_allele.add_argument("--population-source", default=None)
    gather_allele.add_argument("--population", default=None)
    gather_allele.set_defaults(func=_cmd_research_gather_allele)

    gather_gene = commands.add_parser("gather-gene", help="Gather existing sample/static/research evidence for one gene.")
    gather_gene.add_argument("--db", required=True, type=Path)
    gather_gene.add_argument("gene")
    gather_gene.add_argument("--matches", type=Path, default=None)
    gather_gene.add_argument("--genome-build", default="GRCh38")
    gather_gene.set_defaults(func=_cmd_research_gather_gene)

    gwas_compare_variants = commands.add_parser("gwas-compare-variants", help="Compare candidate rsIDs by GWAS Catalog trait evidence.")
    gwas_compare_variants.add_argument("--phenotype", required=True)
    gwas_compare_variants.add_argument("--association-limit", type=int, default=200)
    gwas_compare_variants.add_argument("--api-url", default=None)
    gwas_compare_variants.add_argument("variants", nargs="+")
    gwas_compare_variants.set_defaults(func=_cmd_research_gwas_compare_variants)

    record = commands.add_parser("record", help="Store reviewed source finding with shared/private scope.")
    record.add_argument("--db", required=True, type=Path)
    record.add_argument("--input", required=True, type=Path)
    record.add_argument("--scope", choices=research_scope_choices(), default="shared")
    record.add_argument("--shared-db", type=Path, default=None)
    record.add_argument("--no-sync-shared", action="store_true")
    record.set_defaults(func=_cmd_research_record)

    query = commands.add_parser("query", help="Retrieve reviewed research for an exact target.")
    query.add_argument("--db", required=True, type=Path)
    _add_target_args(query, require_type=True)
    query.add_argument("--scope", choices=research_scope_choices(), default=None)
    query.add_argument("--limit", type=int, default=20)
    query.set_defaults(func=_cmd_research_query)

    search = commands.add_parser("search", help="Token-search stored reviewed research.")
    search.add_argument("--db", required=True, type=Path)
    search.add_argument("query")
    search.add_argument("--target-type", choices=research_target_type_choices(), default=None)
    search.add_argument("--scope", choices=research_scope_choices(), default=None)
    search.add_argument("--limit", type=int, default=50)
    search.set_defaults(func=_cmd_research_search)


def _add_target_args(parser: argparse.ArgumentParser, *, require_type: bool) -> None:
    parser.add_argument("--target-type", choices=research_target_type_choices(), required=require_type)
    parser.add_argument("--gene", default=None)
    parser.add_argument("--drug", default=None)
    parser.add_argument("--condition", default=None)
    parser.add_argument("--topic", default=None)
    parser.add_argument("--chrom", default=None)
    parser.add_argument("--pos", type=int, default=None)
    parser.add_argument("--ref", default=None)
    parser.add_argument("--alt", default=None)
    parser.add_argument("--genome-build", default="GRCh38")


def _cmd_workflow(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "status": "ok",
        "runtime": {
            "name": "genomi",
            "primary_interfaces": ["MCP tools/list", "genomi.invoke", "genomi serve"],
            "skill_root": "SKILL.md",
            "skill_dispatch": "genomi.invoke",
        },
        "agent_usage": [
            "Read the relevant skill in skills/<capability>/SKILL.md (auto-loaded by Anthropic Claude Code Skills as genomi-<capability>) before calling capability tools.",
            "Call base tools (genomi.* and journal.*) directly via MCP. Reach every other capability tool through genomi.invoke({tool, params}).",
            "Use genotype support, callability, source review, or coverage tools only when those evidence facts matter.",
        ],
        "workflow": [
            static_annotation.workflow_contract(),
            intent_research.workflow_contract(),
        ],
        "evidence_context": evidence_context(
            "static",
            reason="If the user provided a genome source or asks to inspect an Active Genome Index, start with source intake. Otherwise choose the target-specific tool directly.",
            commands=['genomi.invoke({"tool":"genomi.parse_source","params":{"source":"<source>"}})'],
        ),
    }


def _cmd_static_init(args: argparse.Namespace) -> dict[str, Any]:
    return static_annotation.init_static_run(
        args.vcf,
        source_evidence_db=args.source_evidence_db,
        shared_evidence_db=args.shared_db,
        force=args.force,
    )


def _cmd_static_run(args: argparse.Namespace) -> dict[str, Any]:
    return static_annotation.build_static_annotation(
        args.vcf,
        evidence_db=args.db,
        source_evidence_db=args.source_evidence_db,
        shared_evidence_db=args.shared_db,
        sync_shared=not args.no_sync_shared,
        reference_fasta=args.reference_fasta,
        genotype_reference_fasta=args.genotype_reference_fasta,
        auto_reference_fasta=args.auto_reference_fasta,
        reference_root=args.reference_root,
        clinvar_vcf=args.clinvar_vcf,
        population_vcf=args.population_vcf,
        population_source=args.population_source,
        population_version=args.population_version,
        primary_contigs_only=args.primary_contigs_only,
        chrom_style=args.chrom_style,
        genome_build=args.genome_build,
        force=args.force,
        max_records=args.max_records,
    )


def _cmd_static_match_clinvar(args: argparse.Namespace) -> dict[str, Any]:
    return static_annotation.match_static_clinvar(
        args.vcf,
        evidence_db=args.db,
        output=args.output,
        genome_build=args.genome_build,
        force=args.force,
    )


def _cmd_static_scan_static(args: argparse.Namespace) -> dict[str, Any]:
    return static_annotation.scan_static_candidates(
        args.matches,
        evidence_db=args.db,
        output=args.output,
        genome_build=args.genome_build,
        force=args.force,
    )


def _cmd_static_fetch_population(args: argparse.Namespace) -> dict[str, Any]:
    return static_annotation.fetch_static_population(
        args.db,
        args.chrom,
        args.pos,
        args.ref,
        args.alt,
        shared_evidence_db=args.shared_db,
        sync_shared=not args.no_sync_shared,
        dataset=args.dataset,
        genome_build=args.genome_build,
        api_url=args.api_url,
        force=args.force,
    )


def _cmd_static_qc(args: argparse.Namespace) -> dict[str, Any]:
    return static_annotation.run_static_sample_qc(
        args.vcf,
        evidence_db=args.db,
        active_genome_index_path=args.active_genome_index_path,
        output=args.output,
        genome_build=args.genome_build,
        scan_records=args.scan_records,
    )


def _cmd_static_genotype_support(args: argparse.Namespace) -> dict[str, Any]:
    return static_annotation.run_static_genotype_support(
        args.vcf,
        args.chrom,
        args.pos,
        args.ref,
        args.alt,
        evidence_db=args.db,
        active_genome_index_path=args.active_genome_index_path,
        output=args.output,
        genome_build=args.genome_build,
        reference_fasta=args.reference_fasta,
        min_depth=args.min_depth,
        min_genotype_quality=args.min_gq,
    )


def _cmd_static_callability(args: argparse.Namespace) -> dict[str, Any]:
    return static_annotation.run_static_callability(
        args.vcf,
        args.region,
        evidence_db=args.db,
        active_genome_index_path=args.active_genome_index_path,
        output=args.output,
        genome_build=args.genome_build,
        min_depth=args.min_depth,
        min_covered_fraction=args.min_covered_fraction,
        limit=args.limit,
    )


def _cmd_static_query_rsid(args: argparse.Namespace) -> dict[str, Any]:
    return static_annotation.query_static_rsid(
        args.vcf,
        args.rsid,
        active_genome_index_path=args.active_genome_index_path,
        pass_only=not args.include_fail,
        limit=args.limit,
    )


def _cmd_static_query_region(args: argparse.Namespace) -> dict[str, Any]:
    return static_annotation.query_static_region(
        args.vcf,
        args.region,
        active_genome_index_path=args.active_genome_index_path,
        variants_only=args.variants_only,
        pass_only=not args.include_fail,
        limit=args.limit,
    )


def _cmd_static_query_variant(args: argparse.Namespace) -> dict[str, Any]:
    return static_annotation.query_static_variant(
        args.vcf,
        args.chrom,
        args.pos,
        args.ref,
        args.alt,
        active_genome_index_path=args.active_genome_index_path,
        pass_only=not args.include_fail,
        limit=args.limit,
    )


def _cmd_static_query_coverage(args: argparse.Namespace) -> dict[str, Any]:
    return static_annotation.query_static_coverage(args.vcf, args.region, active_genome_index_path=args.active_genome_index_path, limit=args.limit)


def _cmd_static_summary(args: argparse.Namespace) -> dict[str, Any]:
    return static_annotation.summarize_static_state(args.vcf, evidence_db=args.db)


def _cmd_research_sources(args: argparse.Namespace) -> dict[str, Any]:
    return intent_research.source_catalog(target_type=args.target_type, source_id=args.source_id)


def _cmd_research_packet(args: argparse.Namespace) -> dict[str, Any]:
    return intent_research.evidence_packet(
        args.db,
        args.target_type,
        gene=args.gene,
        drug=args.drug,
        condition=args.condition,
        topic=args.topic,
        chrom=args.chrom,
        pos=args.pos,
        ref=args.ref,
        alt=args.alt,
        genome_build=args.genome_build,
        source_id=args.source_id,
        limit=args.limit,
    )


def _cmd_research_gather_allele(args: argparse.Namespace) -> dict[str, Any]:
    return intent_research.gather_allele_context(
        args.db,
        args.chrom,
        args.pos,
        args.ref,
        args.alt,
        matches=args.matches,
        genome_build=args.genome_build,
        population_source=args.population_source,
        population=args.population,
    )


def _cmd_research_gather_gene(args: argparse.Namespace) -> dict[str, Any]:
    return intent_research.gather_gene_context(
        args.db,
        args.gene,
        matches=args.matches,
        genome_build=args.genome_build,
    )


def _cmd_research_gwas_compare_variants(args: argparse.Namespace) -> dict[str, Any]:
    return intent_research.compare_gwas_variant_context(
        args.phenotype,
        args.variants,
        association_limit=args.association_limit,
        api_url=args.api_url,
    )


def _cmd_research_record(args: argparse.Namespace) -> dict[str, Any]:
    return intent_research.record_reviewed_research_file(
        args.db,
        args.input,
        scope=args.scope,
        shared_evidence_db=args.shared_db,
        sync_shared=not args.no_sync_shared,
    )


def _cmd_research_query(args: argparse.Namespace) -> dict[str, Any]:
    return intent_research.query_reviewed_research(
        args.db,
        args.target_type,
        gene=args.gene,
        drug=args.drug,
        condition=args.condition,
        topic=args.topic,
        chrom=args.chrom,
        pos=args.pos,
        ref=args.ref,
        alt=args.alt,
        genome_build=args.genome_build,
        scope=args.scope,
        limit=args.limit,
    )


def _cmd_research_search(args: argparse.Namespace) -> dict[str, Any]:
    return intent_research.search_reviewed_research(
        args.db,
        args.query,
        target_type=args.target_type,
        scope=args.scope,
        limit=args.limit,
    )
