from __future__ import annotations

from pathlib import Path
from typing import Any

from ..capabilities.ancestry import reference_panels as ancestry_reference_panels
from ..capabilities.journal import journal
from ..capabilities.pharmacogenomics import review as pgx
from ..capabilities.prs import scoring_files as prs_scoring_files
from ..evidence.sources import evidence_source_catalog
from .host_response import host_response_profiles
from .libraries.manager import inventory as library_inventory
from .paths import genomi_data_root, shared_evidence_db_path, shared_reference_dir

RESOURCE_CATALOG_SCHEMA_VERSION = "genomi-resource-catalog-v1"


def list_resources() -> dict[str, Any]:
    """Return the agent-facing inventory of local and public Genomi resources."""

    root = genomi_data_root()
    shared_db = shared_evidence_db_path()
    reference_dir = shared_reference_dir()
    source_catalog = evidence_source_catalog()
    return {
        "schema": RESOURCE_CATALOG_SCHEMA_VERSION,
        "local_runtime": {"available": root.exists()},
        "context_policy": {
            "active_genome_index_context_listed": False,
            "rule": (
                "Resource discovery reports public capabilities only. Active Genome Index context is handled by context "
                "tools after the conversation asks for it."
            ),
            "context_tools": ["genomi.describe_context", "genomi.parse_source", "active_genome_index.assign_user_genome", "active_genome_index.approve_access"],
        },
        "toolset_disclosure": {
            "model": "skill_gated_dispatcher",
            "default": "Default tools/list returns the base set (genomi + journal capabilities) plus the genomi.invoke dispatcher.",
            "expanded": "Capability tools are reached by dispatch: read the capability's skill (skills/<capability>/SKILL.md), then call genomi.invoke({tool: '<cap>.<op>', params: {...}}).",
            "candidate_gene_tools": "Use source-specific candidate-gene tools: phenotype.compare_gene_hpo_evidence for HPO/single-subject candidate genes, gwas.compare_gene_associations for GWAS Catalog gene-field evidence, phenotype.retrieve_trait_gene_records for Open Targets trait-gene records, phenotype.compare_drug_target_evidence for drug-target evidence, and functional_genomics.compare_gene_perturbation for perturbation evidence.",
        },
        "host_response_profiles": host_response_profiles(),
        "resource_groups": [
            {
                "id": "journal",
                "title": "Journal",
                "resources": [
                    {
                        "id": "session_journal",
                        "title": "Session Journal",
                        **journal.journal_inventory()["session_journal"],
                        "best_for": "Chat/session-scoped observations, hypotheses, decisions, and unresolved questions over Genomi evidence.",
                    },
                    {
                        "id": "project_journal",
                        "title": "Project Journal",
                        **journal.journal_inventory()["project_journal"],
                        "best_for": "Workspace/project notes over public-target Genomi evidence.",
                    },
                ],
            },
            {
                "id": "evidence_storage",
                "title": "Evidence Storage",
                "resources": [
                    {
                        "id": "shared_evidence_db",
                        "title": "Shared Evidence Database",
                        "type": "sqlite",
                        "exists": shared_db.exists(),
                        "privacy_scope": "shared_public_or_reviewed_target_evidence",
                        "best_for": "Reusable public-target findings, source reviews, and population evidence.",
                    },
                    {
                        "id": "shared_reference_dir",
                        "title": "Shared Reference Directory",
                        "type": "directory",
                        "exists": reference_dir.exists(),
                        "artifact_count": _child_count(reference_dir),
                        "best_for": "Reusable reference files used by parsing and genotype support.",
                    },
                ],
            },
            {
                "id": "installed_libraries",
                "title": "Installed Public Libraries",
                "resources": library_inventory()["libraries"],
            },
            {
                "id": "source_adapters",
                "title": "Public Source Adapters",
                "resources": source_catalog["sources"],
            },
            {
                "id": "ancestry_reference_panels",
                "title": "Ancestry Reference Panels",
                "resources": ancestry_reference_panels.list_reference_panels()["panels"],
            },
            {
                "id": "polygenic_scores",
                "title": "Polygenic Score Cache",
                "resources": prs_scoring_files.list_imported_scores()["scores"],
            },
            {
                "id": "pharmacogenomics",
                "title": "Pharmacogenomics",
                "resources": [
                    {
                        "id": "pgx_capability_inventory",
                        "title": "PGx Capability Inventory",
                        "type": "capability_matrix",
                        "privacy_scope": "metadata_only",
                        "best_for": "Selecting public evidence, targeted sample lookup, supported marker calling, or broad PharmCAT PGx calling.",
                        "capabilities": pgx.capability_inventory(check_pharmcat=False),
                    }
                ],
            },
        ],
        "source_catalog": source_catalog,
    }


def _child_count(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    return sum(1 for _ in path.iterdir())
