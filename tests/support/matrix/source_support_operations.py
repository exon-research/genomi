from __future__ import annotations

from pathlib import Path
from typing import Protocol

from genomi.evidence import init_evidence_db
from genomi.operations import call_operation

from tests.support.active_genome_index.contract_cases import LocusContract, SourceContractCase
from tests.support.matrix.capability_contract import MatrixCaseContext


class SupportsAssertions(Protocol):
    def assertEqual(self, first: object, second: object, msg: object = ...) -> None: ...

    def assertGreater(self, first: object, second: object, msg: object = ...) -> None: ...

    def assertIn(self, member: object, container: object, msg: object = ...) -> None: ...

    def assertTrue(self, expr: object, msg: object = ...) -> None: ...


def assert_source_support_operations(
    testcase: SupportsAssertions,
    contract: SourceContractCase,
    ctx: MatrixCaseContext,
    source: Path,
    parsed: dict[str, object],
    *,
    allele_locus: LocusContract,
) -> set[str]:
    seen_operations: set[str] = set()
    _assert_source_context_operations(testcase, seen_operations)
    _assert_pgx_support_operations(testcase, contract, ctx, seen_operations)
    _assert_variant_context_operations(testcase, contract, ctx, allele_locus, seen_operations)
    _assert_decode_evidence_builder(testcase, contract, seen_operations)
    _assert_agi_and_user_context_operations(testcase, contract, source, parsed, seen_operations)
    return seen_operations


def _assert_source_context_operations(testcase: SupportsAssertions, seen_operations: set[str]) -> None:
    ancestry_context = call_operation("ancestry.build_source_context")
    seen_operations.add("ancestry.build_source_context")
    testcase.assertEqual(ancestry_context["status"], "completed")

    ancestry_panels = call_operation("ancestry.list_reference_panels")
    seen_operations.add("ancestry.list_reference_panels")
    testcase.assertEqual(ancestry_panels["status"], "completed")

    prs_context = call_operation("prs.build_source_context")
    seen_operations.add("prs.build_source_context")
    testcase.assertEqual(prs_context["status"], "completed")

    prs_scores = call_operation("prs.list_imported_scores")
    seen_operations.add("prs.list_imported_scores")
    testcase.assertEqual(prs_scores["status"], "completed")


def _assert_pgx_support_operations(
    testcase: SupportsAssertions,
    contract: SourceContractCase,
    ctx: MatrixCaseContext,
    seen_operations: set[str],
) -> None:
    requirements = call_operation("pharmacogenomics.describe_gene_requirements", {"gene": "HLA-B"})
    seen_operations.add("pharmacogenomics.describe_gene_requirements")
    testcase.assertEqual(requirements["records"][0]["gene"], "HLA-B")
    testcase.assertEqual(requirements["records"][0]["category"], "outside_call_required")

    preflight = call_operation("pharmacogenomics.preflight_pharmcat", {"genome_build": "GRCh37"})
    seen_operations.add("pharmacogenomics.preflight_pharmcat")
    testcase.assertEqual(preflight["status"], "completed", preflight)
    testcase.assertTrue(preflight["input_preflight"]["input"]["hidden_agi_path"])

    outside_source = ctx.write_text(
        f"{contract.expected_format}.outside-source.csv",
        "gene,diplotype,phenotype,activity_score\n"
        "CYP2D6,*1/*4,Intermediate Metabolizer,1.0\n",
    )
    outside_output = ctx.tmp_path / f"{contract.expected_format}.outside.tsv"
    prepared = call_operation(
        "pharmacogenomics.prepare_outside_call_tsv",
        {
            "caller_output_file": outside_source,
            "caller_format": "generic_table",
            "output_file": str(outside_output),
        },
    )
    seen_operations.add("pharmacogenomics.prepare_outside_call_tsv")
    testcase.assertEqual(prepared["status"], "completed", prepared)

    validated = call_operation(
        "pharmacogenomics.validate_outside_call_tsv",
        {"outside_call_file": str(outside_output)},
    )
    seen_operations.add("pharmacogenomics.validate_outside_call_tsv")
    testcase.assertEqual(validated["status"], "completed", validated)
    testcase.assertEqual(validated["summary"]["genes"], ["CYP2D6"])


def _assert_variant_context_operations(
    testcase: SupportsAssertions,
    contract: SourceContractCase,
    ctx: MatrixCaseContext,
    allele_locus: LocusContract,
    seen_operations: set[str],
) -> None:
    evidence_db = ctx.tmp_path / f"{contract.expected_format}.evidence.sqlite"
    init_evidence_db(evidence_db)
    matches_path = _empty_matches_path(ctx, contract)
    allele_context = call_operation(
        "variant.gather_allele_context",
        {
            "db": str(evidence_db),
            "matches": str(matches_path),
            "chrom": allele_locus.chrom,
            "pos": allele_locus.pos,
            "ref": allele_locus.ref,
            "alt": allele_locus.alt,
            "genome_build": "GRCh37",
        },
    )
    seen_operations.add("variant.gather_allele_context")
    testcase.assertEqual(allele_context["query"]["pos"], allele_locus.pos)

    gene_context = call_operation(
        "variant.gather_gene_context",
        {"db": str(evidence_db), "matches": str(matches_path), "gene": "MTHFR", "genome_build": "GRCh37"},
    )
    seen_operations.add("variant.gather_gene_context")
    testcase.assertEqual(gene_context["query"]["gene"], "MTHFR")


def _assert_decode_evidence_builder(
    testcase: SupportsAssertions,
    contract: SourceContractCase,
    seen_operations: set[str],
) -> None:
    call_operation(
        "active_genome_index.approve_access",
        {"approved_by_user": True, "reason": "representative dashboard evidence build"},
    )
    built = call_operation("decode.build_dashboard_evidence", {"panels": ["overview"]})
    seen_operations.add("decode.build_dashboard_evidence")
    testcase.assertEqual(built["status"], "completed", built)
    testcase.assertEqual(built["panels_ready"], ["overview"])
    overview = built["render_params"]["evidence"]["overview"]["active_genome_index"]
    testcase.assertEqual(overview["metadata"]["source_format"], contract.expected_format)


def _assert_agi_and_user_context_operations(
    testcase: SupportsAssertions,
    contract: SourceContractCase,
    source: Path,
    parsed: dict[str, object],
    seen_operations: set[str],
) -> None:
    nickname = f"matrix-{contract.expected_format}"
    renamed = f"{nickname}-renamed"
    outputs = parsed.get("outputs") if isinstance(parsed.get("outputs"), dict) else {}
    assigned = call_operation(
        "active_genome_index.assign_user_genome",
        {
            "nickname": nickname,
            "source": str(source),
            "agi_path": str(outputs.get("agi_path")),
            "genome_build": "GRCh37",
        },
    )
    seen_operations.add("active_genome_index.assign_user_genome")
    testcase.assertEqual(assigned["status"], "completed")
    testcase.assertEqual(assigned["user"]["nickname"], nickname)

    agis = call_operation("active_genome_index.list")
    seen_operations.add("active_genome_index.list")
    testcase.assertEqual(agis["status"], "completed")
    testcase.assertTrue(any(agi["agi_id"] == assigned["user"]["active_agi_id"] for agi in agis["active_genome_indexes"]))
    testcase.assertTrue(any(user["nickname"] == nickname for user in agis["users"]))

    selected = call_operation("active_genome_index.select_user", {"nickname": nickname})
    seen_operations.add("active_genome_index.select_user")
    testcase.assertEqual(selected["status"], "completed")
    testcase.assertEqual(selected["user"]["nickname"], nickname)
    testcase.assertEqual(selected["context"]["active_user_id"], selected["user"]["user_id"])

    defaulted = call_operation("active_genome_index.set_default_user", {"nickname": nickname})
    seen_operations.add("active_genome_index.set_default_user")
    testcase.assertEqual(defaulted["status"], "completed")
    testcase.assertEqual(defaulted["default_user"]["nickname"], nickname)

    renamed_result = call_operation("active_genome_index.rename_user", {"nickname": nickname, "new_nickname": renamed})
    seen_operations.add("active_genome_index.rename_user")
    testcase.assertEqual(renamed_result["status"], "completed")
    testcase.assertEqual(renamed_result["user"]["nickname"], renamed)

    cleared_default = call_operation("active_genome_index.clear_default_user")
    seen_operations.add("active_genome_index.clear_default_user")
    testcase.assertEqual(cleared_default["status"], "completed")

    approved = call_operation(
        "active_genome_index.approve_access",
        {"approved_by_user": True, "nickname": renamed, "reason": "source matrix support"},
    )
    seen_operations.add("active_genome_index.approve_access")
    testcase.assertEqual(approved["status"], "completed")
    testcase.assertTrue(approved["active_genome_index_access"]["approved"])

    revoked = call_operation("active_genome_index.revoke_access")
    seen_operations.add("active_genome_index.revoke_access")
    testcase.assertEqual(revoked["status"], "completed")
    testcase.assertTrue(revoked["revoked_all"])

    reapproved = call_operation(
        "active_genome_index.approve_access",
        {"approved_by_user": True, "nickname": renamed, "reason": "source matrix support restore"},
    )
    testcase.assertEqual(reapproved["status"], "completed")
    testcase.assertTrue(reapproved["active_genome_index_access"]["approved"])

    cleared = call_operation("active_genome_index.clear_selection")
    seen_operations.add("active_genome_index.clear_selection")
    testcase.assertEqual(cleared["status"], "completed")

    restored = call_operation("active_genome_index.select_user", {"nickname": renamed})
    testcase.assertEqual(restored["status"], "completed")
    restored_approval = call_operation(
        "active_genome_index.approve_access",
        {"approved_by_user": True, "nickname": renamed, "reason": "source matrix support final restore"},
    )
    testcase.assertEqual(restored_approval["status"], "completed")
    testcase.assertTrue(restored_approval["active_genome_index_access"]["approved"])


def _empty_matches_path(ctx: MatrixCaseContext, contract: SourceContractCase) -> Path:
    matches_path = ctx.tmp_path / f"{contract.expected_format}.clinvar.matches.jsonl"
    matches_path.write_text("", encoding="utf-8")
    return matches_path
