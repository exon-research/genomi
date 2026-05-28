from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .catalog_meta import (
    CAPABILITY_ENTRY_OPERATION_NAMES,
    TOOL_CATALOG_OPERATIONS,
    _catalog_input_schema,
    _catalog_tuple,
    _data_access,
    _operation_catalog_entry,
    _operation_dependency_contract,
    _operation_namespace,
    _operation_scope,
    _without_top_level_schema_combinators,
)
from .errors import JsonObject, OperationHandler


@dataclass(frozen=True)
class Operation:
    name: str
    handler: OperationHandler
    description: str | None = None
    input_schema: JsonObject | None = None
    skill: str | None = None
    area: str | None = None
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    context_optional: tuple[str, ...] = ()
    privacy_scope: str | None = None
    operation_scope: str | None = None
    mutating: bool | None = None
    external_io: tuple[str, ...] = ()
    data_access: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        catalog = TOOL_CATALOG_OPERATIONS.get(self.name)
        if catalog is None:
            return
        defaults: dict[str, Any] = {
            "description": str(catalog.get("description") or ""),
            "input_schema": _catalog_input_schema(catalog),
            "skill": str(catalog.get("skill") or ""),
            "area": str(catalog.get("namespace") or (self.name.split(".", 1)[0] if "." in self.name else self.name)),
            "requires": _catalog_tuple(catalog, "requires"),
            "produces": _catalog_tuple(catalog, "produces"),
            "context_optional": _catalog_tuple(catalog, "context_optional"),
            "privacy_scope": str(catalog.get("privacy_scope") or "local"),
            "operation_scope": str(catalog.get("operation_scope") or _operation_scope(self.name)),
            "mutating": bool(catalog.get("mutating", _operation_scope(self.name) != "read")),
            "external_io": _catalog_tuple(catalog, "external_io"),
            "data_access": _catalog_tuple(catalog, "data_access"),
        }
        for field, value in defaults.items():
            current = getattr(self, field)
            if current in (None, (), ""):
                object.__setattr__(self, field, value)

    def tool_definition(self) -> JsonObject:
        catalog = _operation_catalog_entry(self.name)
        description = self.description or str(catalog["description"])
        input_schema = _without_top_level_schema_combinators(self.input_schema or _catalog_input_schema(catalog))
        skill = self.skill or str(catalog["skill"])
        privacy_scope = self.privacy_scope or str(catalog.get("privacy_scope") or "local")
        operation_scope = self.operation_scope or str(catalog.get("operation_scope") or _operation_scope(self.name))
        mutating = self.mutating if self.mutating is not None else bool(catalog.get("mutating", operation_scope != "read"))
        external_io = self.external_io or _catalog_tuple(catalog, "external_io")
        data_access = self.data_access or _catalog_tuple(catalog, "data_access") or _data_access(privacy_scope)
        title = _display_title(self.name)
        parameter_defaults = _operation_parameter_defaults(self)
        dependency_contract = _operation_dependency_contract(
            optional_libraries=tuple(str(item) for item in catalog.get("optional_libraries") or []),
            external_io=tuple(external_io),
            library_check_operation=str(catalog.get("library_check_operation") or ""),
        )
        return {
            "name": self.name,
            "title": title,
            "description": description,
            "inputSchema": input_schema,
            "annotations": {
                "title": title,
                "skill": skill,
                "area": _operation_namespace(self.name),
                "requires": list(self.requires or _catalog_tuple(catalog, "requires")),
                "produces": list(self.produces or _catalog_tuple(catalog, "produces")),
                "contextOptional": list(self.context_optional or _catalog_tuple(catalog, "context_optional")),
                "parameterDefaults": parameter_defaults,
                **({"dependencyContract": dependency_contract} if dependency_contract else {}),
                "privacyScope": privacy_scope,
                "operationScope": operation_scope,
                "mutating": mutating,
                "externalIO": list(external_io),
                "dataAccess": list(data_access),
                "trustBoundary": "local_cli_or_stdio_mcp_host",
                "flow": "agent-composed",
                "toolCapability": _operation_capability(self),
                "discoveryRole": _tool_role(self),
            },
        }


def _operation_parameter_defaults(operation: Operation) -> list[JsonObject]:
    schema = operation.input_schema or _catalog_input_schema(_operation_catalog_entry(operation.name))
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    defaults: list[JsonObject] = []
    for parameter, value in properties.items():
        if not isinstance(value, dict):
            continue
        default_meta = value.get("x_genomi_default")
        if default_meta is not None and not isinstance(default_meta, dict):
            default_meta = {"rule": str(default_meta)}
        if "default" not in value and not default_meta:
            continue
        record: JsonObject = {"parameter": str(parameter)}
        if "default" in value:
            record["value"] = value["default"]
        if isinstance(default_meta, dict):
            for key in ("value", "rule", "source", "condition", "possible_values"):
                if key in default_meta and key not in record:
                    record[key] = default_meta[key]
        record.setdefault("source", "tool_default")
        record["applies_when_omitted"] = True
        defaults.append(record)
    return defaults


def _operation_capability(operation: Operation) -> str:
    return str(_operation_catalog_entry(operation.name).get("capability") or _operation_namespace(operation.name))


def _tool_role(operation: Operation) -> str:
    catalog = _operation_catalog_entry(operation.name)
    if catalog.get("discovery_role"):
        return str(catalog["discovery_role"])
    if operation.name in CAPABILITY_ENTRY_OPERATION_NAMES:
        return "entry_tool"
    return "focused_tool"


# Hand-curated display titles for the most user-visible tools. Hosts like
# Claude Code render this as the tool-execution status line — e.g.
# "Using Genomi to resolve a variant target...".
_DISPLAY_TITLE_OVERRIDES: dict[str, str] = {
    "variant.resolve": "Using Genomi to resolve a variant target",
    "phenotype.plan_risk_investigation": "Using Genomi to plan a disease / cancer-risk investigation",
    "pharmacogenomics.review_medication": "Using Genomi to review medication evidence",
    "pharmacogenomics.run_pharmcat": "Using Genomi to run PharmCAT",
    "pharmacogenomics.check_pharmcat": "Using Genomi to check PharmCAT availability",
    "pharmacogenomics.fetch_clinpgx": "Using Genomi to fetch ClinPGx guideline evidence",
    "pharmacogenomics.fetch_pgxdb": "Using Genomi to fetch PGxDB association evidence",
    "pharmacogenomics.fetch_fda_labels": "Using Genomi to fetch FDA PGx label evidence",
    "clinvar.scan_candidates": "Using Genomi to scan ClinVar candidate variants",
    "clinvar.match_variants": "Using Genomi to match ClinVar variants",
    "ancestry.list_reference_panels": "Using Genomi to list ancestry reference panels",
    "ancestry.check_sample_overlap": "Using Genomi to check ancestry panel overlap",
    "ancestry.project_pca": "Using Genomi to project ancestry PCA context",
    "ancestry.estimate_population_context": "Using Genomi to estimate reference-panel ancestry context",
    "ancestry.build_source_context": "Using Genomi to describe ancestry source context",
    "prs.search_scores": "Using Genomi to search PGS Catalog scores",
    "prs.fetch_score_metadata": "Using Genomi to fetch PGS Catalog score metadata",
    "prs.import_scoring_file": "Using Genomi to import a PRS scoring file",
    "prs.list_imported_scores": "Using Genomi to list imported PRS scores",
    "prs.check_score_overlap": "Using Genomi to check PRS score overlap",
    "prs.calculate_score": "Using Genomi to calculate a polygenic score",
    "prs.build_source_context": "Using Genomi to describe PRS source context",
    "genomi.parse_source": "Using Genomi to parse a genome source",
    "phenotype.compare_disease_evidence": "Using Genomi to compare phenotype evidence",
    "phenotype.retrieve_disease_drug_targets": "Using Genomi to retrieve clinical drug targets",
    "phenotype.compare_gene_hpo_evidence": "Using Genomi to compare gene-HPO evidence",
    "phenotype.normalize_terms": "Using Genomi to normalize phenotype terms",
    "phenotype.retrieve_gene_disease_associations": "Using Genomi to retrieve gene-disease associations",
    "phenotype.compare_drug_target_evidence": "Using Genomi to compare drug-target evidence",
    "gwas.compare_variant_associations": "Using Genomi to compare GWAS variant associations",
    "gwas.compare_gene_associations": "Using Genomi to compare GWAS gene-field associations",
    "phenotype.retrieve_trait_gene_records": "Using Genomi to retrieve trait-gene records",
    "functional_genomics.retrieve_perturbation_records": "Using Genomi to retrieve perturbation records",
    "functional_genomics.query_geo": "Using Genomi to discover GEO public study tables",
    "functional_genomics.compare_gene_perturbation": "Using Genomi to compare gene-perturbation evidence",
    "functional_genomics.import_perturbation_table": "Using Genomi to import a perturbation table",
    "pathway.retrieve_members": "Using Genomi to retrieve pathway member genes",
    "cell_type.retrieve_markers": "Using Genomi to retrieve canonical cell-type markers",
    "region.retrieve_features": "Using Genomi to retrieve region feature annotation",
    "gnomad.fetch_population_frequency": "Using Genomi to fetch gnomAD allele frequency",
    "research.build_target_packet": "Using Genomi to build a target evidence packet",
    "variant.gather_allele_context": "Using Genomi to gather allele context",
    "variant.gather_gene_context": "Using Genomi to gather gene context",
    "research.record": "Using Genomi to record reviewed research",
    "research.query": "Using Genomi to query reviewed research",
    "research.search": "Using Genomi to search reviewed research",
    "active_genome_index.summarize": "Using Genomi to summarize the Active Genome Index",
    "active_genome_index.classify_callset_qc": "Using Genomi to classify callset QC",
    "active_genome_index.classify_genotype_support": "Using Genomi to classify genotype support",
    "active_genome_index.classify_region_callability": "Using Genomi to classify region callability",
    "sequence.translate": "Using Genomi to translate DNA",
    "sequence.analyze": "Using Genomi to analyze a sequence",
    "sequence.match_reference": "Using Genomi to match reference records",
    "sequence.find_orfs": "Using Genomi to find ORFs",
    "sequence.find_restriction_sites": "Using Genomi to find restriction sites",
    "sequence.classify_kozak": "Using Genomi to classify Kozak context",
    "sequence.check_primers": "Using Genomi to check a primer pair",
    "genomi.describe_context": "Using Genomi to describe the current context",
    "genomi.set_response_profile": "Using Genomi to set the response tone",
    "genomi.install": "Using Genomi to install or update setup",
    "genomi.select_user": "Using Genomi to select a user",
    "genomi.clear_selection": "Using Genomi to clear the active context",
    "genomi.approve_agi_access": "Using Genomi to approve Active Genome Index access",
    "genomi.revoke_agi_access": "Using Genomi to revoke Active Genome Index access",
    "genomi.invoke": "Using Genomi to dispatch a capability tool",
    "genomi.list_resources": "Using Genomi to list public capabilities",
    "genomi.check_libraries": "Using Genomi to check installed libraries",
    "research.list_sources": "Using Genomi to list evidence sources",
    "genomi.check_background_job": "Using Genomi to check a background job",
    "journal.append_entry": "Using Genomi to append a journal entry",
    "journal.search_entries": "Using Genomi to search the journal",
    "journal.summarize": "Using Genomi to summarize the journal",
    "journal.export_memory": "Using Genomi to export journal memory",
    "pharmacogenomics.describe_gene_requirements": "Using Genomi to describe pharmacogene requirements",
    "pharmacogenomics.import_pharmcat_artifacts": "Using Genomi to import PharmCAT artifacts",
    "pharmacogenomics.validate_outside_call_tsv": "Using Genomi to validate an outside-call TSV",
    "pharmacogenomics.prepare_outside_call_tsv": "Using Genomi to prepare an outside-call TSV",
    "pharmacogenomics.preflight_pharmcat": "Using Genomi to preflight a PharmCAT VCF",
    "decode.render_dashboard": "Using Genomi to render the dashboard",
}


def _display_title(operation_name: str) -> str:
    explicit = _DISPLAY_TITLE_OVERRIDES.get(operation_name)
    if explicit:
        return explicit
    # Auto-derive from operation name: `area.verb_phrase` -> "Using Genomi to verb phrase".
    tail = operation_name.split(".", 1)[1] if "." in operation_name else operation_name
    words = tail.replace("-", "_").split("_")
    return "Using Genomi to " + " ".join(words)
