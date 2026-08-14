from __future__ import annotations

from typing import Any

from ..operations import all_operations
from . import portal_turns

JsonObject = dict[str, Any]

SOURCE_LOOKUP_ORDER = (
    "genomi.parse_source",
    "genomi.search_indexes",
    "variant.resolve",
    "research.build_target_packet",
    "pharmacogenomics.review_medication",
    "phenotype.normalize_terms",
    "gwas.compare_variant_associations",
    "prs.search_scores",
)

DISPLAY_LABELS = {
    "genomi.parse_source": "Add genome file",
    "genomi.search_indexes": "Search public sources",
    "variant.resolve": "Variant lookup",
    "research.build_target_packet": "Target evidence report",
    "pharmacogenomics.review_medication": "Medication response review",
    "phenotype.normalize_terms": "Phenotype term lookup",
    "gwas.compare_variant_associations": "GWAS variant comparison",
    "prs.search_scores": "Polygenic score search",
}

DESCRIPTIONS = {
    "genomi.parse_source": "Use a local VCF, BAM, FASTQ, array export, or genome bundle for approved session-scoped evidence.",
    "genomi.search_indexes": "Search public source metadata before opening a focused evidence workflow.",
    "variant.resolve": "Resolve a variant by rsID, coordinate, or region and collect scoped evidence.",
    "research.build_target_packet": "Build a compact evidence report for a gene, variant, drug, condition, or topic.",
    "pharmacogenomics.review_medication": "Review public medication-response evidence and the approved active genome when available.",
    "phenotype.normalize_terms": "Turn phenotype text or HPO IDs into normalized evidence-review targets.",
    "gwas.compare_variant_associations": "Compare candidate variants against public GWAS trait associations.",
    "prs.search_scores": "Search public PGS Catalog score metadata by trait, score ID, or EFO term.",
}

SOURCE_AREAS = {
    "genomi.parse_source": "Genome files",
    "genomi.search_indexes": "Public sources",
    "variant.resolve": "Variant evidence",
    "research.build_target_packet": "Evidence reports",
    "pharmacogenomics.review_medication": "Medication response",
    "phenotype.normalize_terms": "Phenotype terms",
    "gwas.compare_variant_associations": "GWAS evidence",
    "prs.search_scores": "Polygenic scores",
}

FIELD_ORDER = {
    "genomi.parse_source": ("source", "genome_build", "reference_fasta", "user_nickname", "set_default_user"),
    "genomi.search_indexes": ("query", "source", "limit"),
    "genomi.check_libraries": ("libraries",),
    "variant.resolve": (
        "rsid",
        "query",
        "chrom",
        "pos",
        "ref",
        "alt",
        "region",
        "genome_build",
        "include_active_genome_index",
    ),
    "research.build_target_packet": (
        "target_type",
        "gene",
        "drug",
        "condition",
        "topic",
        "chrom",
        "pos",
        "ref",
        "alt",
        "genome_build",
        "limit",
    ),
    "pharmacogenomics.review_medication": (
        "drug",
        "gene",
        "rsid",
        "indication",
        "known_genotype",
        "known_diplotype",
        "known_phenotype",
        "current_medications",
        "include_active_genome_index",
    ),
    "phenotype.normalize_terms": ("text", "phenotypes", "hpo_ids"),
    "gwas.compare_variant_associations": ("phenotype", "variants", "association_limit"),
    "prs.search_scores": ("query", "trait", "pgs_id", "efo_id", "limit"),
}

REQUIRED_INPUTS = {
    "genomi.parse_source": ("source",),
    "research.build_target_packet": ("target_type",),
    "gwas.compare_variant_associations": ("phenotype", "variants"),
}

FIELD_LABELS = {
    "rsid": "rsID",
    "chrom": "Chromosome",
    "pos": "Position",
    "ref": "Reference allele",
    "alt": "Alternate allele",
    "genome_build": "Genome build",
    "source": "Genome source",
    "reference_fasta": "Reference FASTA",
    "user_nickname": "Profile label",
    "set_default_user": "Use as default profile",
    "query": "Search text",
    "libraries": "Libraries",
    "include_active_genome_index": "Use approved active genome",
    "target_type": "Target type",
    "drug": "Medication",
    "known_genotype": "Known genotype",
    "known_diplotype": "Known diplotype",
    "known_phenotype": "Known phenotype",
    "current_medications": "Current medications",
    "phenotypes": "Phenotypes",
    "hpo_ids": "HPO IDs",
    "association_limit": "Association limit",
    "pgs_id": "PGS ID",
    "efo_id": "EFO ID",
}

FIELD_LABEL_OVERRIDES = {
    ("genomi.search_indexes", "source"): "Index source",
    ("phenotype.normalize_terms", "text"): "Phenotype text",
}

FIELD_SUMMARIES = {
    "source": "Choose the local genome source for this session.",
    "reference_fasta": "Optional reference FASTA when the source format requires alignment context.",
    "genome_build": "Use when the build is known; otherwise Genomi will apply its visible default.",
    "query": "Plain-language search text from the user's request.",
    "libraries": "Specific evidence libraries to check, or leave empty to check all configured libraries.",
    "rsid": "A dbSNP rsID such as rs429358.",
    "chrom": "Chromosome for coordinate-based variant lookup.",
    "pos": "1-based variant position for coordinate-based lookup.",
    "ref": "Reference allele for a fully specified variant.",
    "alt": "Alternate allele for a fully specified variant.",
    "region": "Genomic interval such as 19:44908684-44908684.",
    "include_active_genome_index": "Only use when the user has approved the active genome in this session.",
    "target_type": "Pick the kind of target the report should center on.",
    "gene": "Gene symbol to review.",
    "drug": "Medication or drug class to review.",
    "condition": "Condition, disease, or phenotype target.",
    "topic": "Free-text research target when no structured target fits.",
    "known_genotype": "User-provided genotype when available outside a genome source.",
    "known_diplotype": "User-provided pharmacogenomic diplotype when available.",
    "known_phenotype": "Known metabolizer or response phenotype when available.",
    "current_medications": "Medication context supplied by the user.",
    "text": "Phenotype text to normalize.",
    "phenotypes": "Phenotype names to normalize.",
    "hpo_ids": "Known HPO terms to review.",
    "phenotype": "Trait or phenotype to compare against public associations.",
    "variants": "Candidate rsIDs to compare.",
    "trait": "Trait text for public score search.",
    "pgs_id": "Known PGS Catalog score identifier.",
    "efo_id": "Known EFO trait identifier.",
    "limit": "Maximum number of public records to return.",
}

PLACEHOLDERS = {
    "source": "/path/to/source.vcf",
    "reference_fasta": "/path/to/reference.fa",
    "query": "LDL cholesterol",
    "libraries": "pgs_catalog, pharmgkb",
    "rsid": "rs429358",
    "chrom": "19",
    "pos": "44908684",
    "ref": "T",
    "alt": "C",
    "region": "19:44908684-44908684",
    "gene": "CYP2C19",
    "drug": "clopidogrel",
    "condition": "Alzheimer disease",
    "topic": "APOE rs429358",
    "known_genotype": "CYP2C19 *1/*2",
    "known_diplotype": "*1/*2",
    "known_phenotype": "intermediate metabolizer",
    "text": "seizures and microcephaly",
    "phenotypes": "ataxia, microcephaly",
    "hpo_ids": "HP:0001250, HP:0000252",
    "phenotype": "LDL cholesterol",
    "variants": "rs7412, rs429358",
    "trait": "coronary artery disease",
    "pgs_id": "PGS000001",
    "efo_id": "EFO_0001645",
}

REQUEST_UI = {
    "genomi.parse_source": {
        "fieldGroups": [
            {
                "id": "genome_details",
                "label": "Genome details",
                "className": "tool-request-source-limits",
                "bodyClassName": "tool-request-source-limits-body",
                "collapsed": True,
                "parameters": ["genome_build", "reference_fasta", "user_nickname", "set_default_user"],
            },
        ],
    },
    "genomi.search_indexes": {
        "fieldGroups": [
            {
                "id": "source_limits",
                "label": "Source limits",
                "className": "tool-request-source-limits",
                "bodyClassName": "tool-request-source-limits-body",
                "collapsed": True,
                "parameters": ["source", "limit"],
            },
        ],
    },
    "variant.resolve": {
        "fieldGroups": [
            {
                "id": "variant_details",
                "label": "Other variant formats and source limits",
                "className": "tool-request-source-limits",
                "bodyClassName": "tool-request-source-limits-body",
                "collapsed": True,
                "parameters": [
                    "query",
                    "chrom",
                    "pos",
                    "ref",
                    "alt",
                    "region",
                    "genome_build",
                    "include_active_genome_index",
                ],
            },
        ],
    },
    "research.build_target_packet": {
        "guidedControls": [
            {
                "id": "target_type",
                "kind": "segmented",
                "parameter": "target_type",
                "label": "Review target",
                "hideField": True,
                "options": [
                    {"value": "condition", "label": "Condition"},
                    {"value": "drug", "label": "Medication"},
                    {"value": "gene", "label": "Gene"},
                    {"value": "topic", "label": "Topic"},
                    {"value": "variant", "label": "Variant"},
                ],
            },
        ],
        "fieldGroups": [
            {
                "id": "source_limits",
                "label": "Source limits",
                "className": "tool-request-source-limits",
                "bodyClassName": "tool-request-source-limits-body",
                "collapsed": True,
                "parameters": ["genome_build", "limit"],
            },
        ],
    },
}


def source_lookup_payload() -> JsonObject:
    operations = {tool["name"]: tool for tool in all_operations()}
    tools = [
        _tool_with_source_lookup(operations[name])
        for name in SOURCE_LOOKUP_ORDER
        if name in operations
    ]
    return portal_turns.prompt_safe_value({
        "surface": "source_lookup_setup",
        "sourceLookups": tools,
    })


def attach_evidence_source_payload(payload: JsonObject) -> JsonObject | None:
    operation_id = _requested_operation_id(payload)
    operations = {tool["name"]: tool for tool in all_operations()}
    if operation_id not in SOURCE_LOOKUP_ORDER or operation_id not in operations:
        return None
    model = _source_lookup_model(operations[operation_id])
    params = _clean_request_params(payload.get("params"), model)
    missing = _missing_required_inputs(model, params)
    prompt = _evidence_source_prompt(model, params, missing)
    packet = _evidence_source_packet(model, params, missing)
    return portal_turns.prompt_safe_value({
        "surface": "evidence_source_handoff",
        "evidenceSource": {
            "name": model["name"],
            "operationId": model["operationId"],
            "displayLabel": model["displayLabel"],
            "description": model["description"],
        },
        "params": params,
        "missingRequiredInputs": missing,
        "prompt": prompt,
        "selectedEvidence": [packet],
        "packet": packet,
    })


def _tool_with_source_lookup(tool: JsonObject) -> JsonObject:
    name = str(tool.get("name") or "")
    model = _source_lookup_model(tool)
    return {
        "name": name,
        "description": model["description"],
        "annotations": {
            "portalSurface": "source_lookup",
            "area": model["area"],
            "portalLabel": model["displayLabel"],
        },
        "sourceLookup": model,
    }


def _source_lookup_model(tool: JsonObject) -> JsonObject:
    name = str(tool.get("name") or "")
    annotations = _object(tool.get("annotations"))
    fields = _request_fields(tool)
    required = list(REQUIRED_INPUTS.get(name, tuple(_array(_object(tool.get("inputSchema")).get("required")))))
    defaults = _defaults_for_fields(tool, fields)
    dependencies = _dependency_rows(annotations)
    privacy = _privacy_rows(annotations)
    request: JsonObject = {
        "requiredInputs": required,
        "fields": fields,
    }
    request_ui = REQUEST_UI.get(name)
    if request_ui:
        request["ui"] = request_ui
    return {
        "surface": "source_lookup",
        "name": name,
        "operationId": name,
        "displayLabel": DISPLAY_LABELS.get(name) or _clean_text(annotations.get("portalLabel")) or _humanize(name),
        "area": SOURCE_AREAS.get(name) or _clean_text(annotations.get("area")) or "Evidence sources",
        "description": DESCRIPTIONS.get(name) or _clean_text(tool.get("description")),
        "badges": _badges(annotations, required),
        "request": request,
        "sections": [
            _section("Inputs", _field_nodes(fields)),
            _section("Boundary", privacy),
        ],
        "technicalSections": [
            _section("Operation", _operation_rows(name, annotations)),
            _section("Default assumptions if omitted", defaults),
            _section("Dependencies", dependencies),
            _section("Technical boundary", _technical_boundary_rows(annotations)),
        ],
    }


def _requested_operation_id(payload: JsonObject) -> str:
    for key in ("operationId", "operation_id", "sourceOperation", "source_operation", "tool", "name"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _clean_request_params(value: Any, model: JsonObject) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    clean: JsonObject = {}
    for name in _request_field_names(model):
        item = value.get(name)
        if item is None or item == "":
            continue
        clean[name] = portal_turns.prompt_safe_value(item)
    return clean


def _request_field_names(model: JsonObject) -> list[str]:
    names: list[str] = []
    for field in _array(_object(model.get("request")).get("fields")):
        name = str(_object(field).get("name") or _object(field).get("id") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _missing_required_inputs(model: JsonObject, params: JsonObject) -> list[str]:
    request = _object(model.get("request"))
    missing = {
        name
        for name in (str(item) for item in _array(request.get("requiredInputs")))
        if name and name not in params
    }
    for field in _array(request.get("fields")):
        field_model = _object(field)
        name = str(field_model.get("name") or field_model.get("id") or "").strip()
        if not name or name in params:
            continue
        if _condition_matches(_object(field_model.get("requiredWhen")), params):
            missing.add(name)
    return sorted(missing, key=lambda item: _field_index(model, item))


def _condition_matches(condition: JsonObject, params: JsonObject) -> bool:
    parameter = str(condition.get("parameter") or "").strip()
    if not parameter:
        return False
    value = params.get(parameter)
    if "equals" in condition:
        return value == condition.get("equals")
    choices = _array(condition.get("in"))
    return bool(choices) and value in choices


def _field_index(model: JsonObject, name: str) -> int:
    fields = _array(_object(model.get("request")).get("fields"))
    for index, field in enumerate(fields):
        field_name = str(_object(field).get("name") or _object(field).get("id") or "")
        if field_name == name:
            return index
    return len(fields)


def _evidence_source_prompt(model: JsonObject, params: JsonObject, missing: list[str]) -> str:
    label = _clean_text(model.get("displayLabel")) or "this evidence source"
    return "\n".join(
        line
        for line in (
            f"Use {label} as the evidence source if it fits my question.",
            f"Inputs provided: {_request_inputs_text(model, params)}",
            (
                "Ask me for: "
                + _friendly_field_list(model, missing)
                + "."
                if missing
                else ""
            ),
            "Preserve source limits, visible default assumptions, and genome privacy boundaries in the answer.",
        )
        if line
    )


def _evidence_source_packet(model: JsonObject, params: JsonObject, missing: list[str]) -> JsonObject:
    description = _clean_text(model.get("description"))
    label = _clean_text(model.get("displayLabel")) or _clean_text(model.get("operationId"))
    params_text = _request_inputs_text(model, params)
    nodes = [
        {"label": "Evidence source", "text": f"Evidence source: {label}"},
        {"label": "Inputs provided", "text": f"Inputs provided: {params_text}"},
    ]
    if missing:
        nodes.append({"label": "Missing required inputs", "text": "Missing required inputs: " + _friendly_field_list(model, missing)})
    if description:
        nodes.append({"label": "Description", "text": "Description: " + description})
    summary = params_text if params else description or label
    return {
        "label": f"Evidence source: {label}",
        "summary": _clean_text(summary)[:220],
        "context_kind": "tool_request",
        "source_operation": _clean_text(model.get("operationId")),
        "selected_nodes": nodes,
    }


def _request_inputs_text(model: JsonObject, params: JsonObject) -> str:
    if not params:
        return "No inputs supplied yet."
    return "; ".join(
        f"{_field_display_label(model, key)}: {_clean_text(_input_value_text(value))}"
        for key, value in params.items()
    )


def _input_value_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return portal_turns.prompt_safe_text(str(value))


def _friendly_field_list(model: JsonObject, names: list[str]) -> str:
    return ", ".join(_field_display_label(model, name) for name in names)


def _field_display_label(model: JsonObject, name: str) -> str:
    for field in _array(_object(model.get("request")).get("fields")):
        field_model = _object(field)
        if str(field_model.get("name") or field_model.get("id") or "") == name:
            return _clean_text(field_model.get("label")) or name
    return name


def _request_fields(tool: JsonObject) -> list[JsonObject]:
    name = str(tool.get("name") or "")
    schema = _object(tool.get("inputSchema"))
    properties = _object(schema.get("properties"))
    required = set(REQUIRED_INPUTS.get(name, tuple(_array(schema.get("required")))))
    conditional = _conditional_fields(tool)
    fields: list[JsonObject] = []
    for key in FIELD_ORDER.get(name, tuple(properties)):
        spec = _object(properties.get(key))
        if not spec:
            continue
        condition = conditional.get(key, {})
        fields.append(_field_model(name, key, spec, key in required, condition))
    return fields


def _field_model(operation: str, name: str, spec: JsonObject, required: bool, condition: JsonObject) -> JsonObject:
    default = spec.get("default")
    enum_values = [str(item) for item in _array(spec.get("enum")) if str(item)]
    label = _field_label(operation, name)
    model: JsonObject = {
        "id": name,
        "name": name,
        "label": label,
        "required": bool(required or condition.get("requiredWhen")),
        "type": str(spec.get("type") or "string"),
        "enumValues": enum_values,
        "summary": FIELD_SUMMARIES.get(name) or ("Required input" if required else "Optional input"),
        "placeholder": PLACEHOLDERS.get(name) or f"Enter {label.lower()}",
    }
    if default is not None:
        model["defaultValue"] = default
        model["defaultHint"] = _format_default(default)
    if condition.get("visibleWhen"):
        model["visibleWhen"] = condition["visibleWhen"]
    if condition.get("requiredWhen"):
        model["requiredWhen"] = condition["requiredWhen"]
    return model


def _conditional_fields(tool: JsonObject) -> dict[str, JsonObject]:
    request_builder = _object(_object(tool.get("annotations")).get("requestBuilder"))
    result: dict[str, JsonObject] = {}
    for item in _array(request_builder.get("conditionalFields")):
        field = _object(item)
        parameter = str(field.get("parameter") or "").strip()
        if not parameter:
            continue
        condition: JsonObject = {}
        visible = _condition(field.get("visibleWhen"))
        required = _condition(field.get("requiredWhen"))
        if visible:
            condition["visibleWhen"] = visible
        if required:
            condition["requiredWhen"] = required
        result[parameter] = condition
    return result


def _condition(value: Any) -> JsonObject | None:
    condition = _object(value)
    parameter = str(condition.get("parameter") or "").strip()
    if not parameter:
        return None
    if "equals" in condition:
        return {"parameter": parameter, "equals": condition["equals"]}
    values = _array(condition.get("in"))
    if values:
        return {"parameter": parameter, "in": values}
    return None


def _field_nodes(fields: list[JsonObject]) -> list[JsonObject]:
    nodes = []
    for field in fields:
        value = str(field.get("summary") or "")
        enum_values = _array(field.get("enumValues"))
        if enum_values:
            value = f"{value} Choices: {', '.join(str(item) for item in enum_values)}"
        nodes.append({"label": field.get("label"), "value": value})
    return nodes


def _defaults_for_fields(tool: JsonObject, fields: list[JsonObject]) -> list[JsonObject]:
    operation = str(tool.get("name") or "")
    defaults = []
    schema_properties = _object(_object(tool.get("inputSchema")).get("properties"))
    field_names = {str(field.get("name") or "") for field in fields}
    for item in _array(_object(tool.get("annotations")).get("parameterDefaults")):
        entry = _object(item)
        parameter = str(entry.get("parameter") or "").strip()
        if parameter in field_names:
            defaults.append({"label": _field_label(operation, parameter), "value": _format_default(entry.get("value"))})
    known = {item["label"] for item in defaults}
    for name in field_names:
        spec = _object(schema_properties.get(name))
        if "default" not in spec:
            continue
        label = _field_label(operation, name)
        if label not in known:
            defaults.append({"label": label, "value": _format_default(spec.get("default"))})
    return defaults


def _dependency_rows(annotations: JsonObject) -> list[JsonObject]:
    contract = _object(annotations.get("dependencyContract"))
    rows: list[JsonObject] = []
    _add_list_row(rows, "Installed libraries", contract.get("installedLibraries"))
    _add_text_row(rows, "Library check", contract.get("libraryCheckOperation"))
    _add_list_row(rows, "External sources", contract.get("externalNetwork"))
    _add_list_row(rows, "Local resources", contract.get("localResources"))
    _add_list_row(rows, "Requires", annotations.get("requires"))
    return rows


def _privacy_rows(annotations: JsonObject) -> list[JsonObject]:
    rows: list[JsonObject] = []
    _add_text_row(rows, "Privacy scope", _readable_state(annotations.get("privacyScope")))
    return rows


def _operation_rows(name: str, annotations: JsonObject) -> list[JsonObject]:
    rows = [{"label": "Operation ID", "value": name}]
    _add_text_row(rows, "Workspace effect", _readable_state(annotations.get("operationScope")))
    return rows


def _technical_boundary_rows(annotations: JsonObject) -> list[JsonObject]:
    rows: list[JsonObject] = []
    _add_text_row(rows, "Trust boundary", _readable_state(annotations.get("trustBoundary")))
    return rows


def _badges(annotations: JsonObject, required: list[str]) -> list[str]:
    badges = []
    privacy = _readable_state(annotations.get("privacyScope"))
    source_action = _source_action_badge(annotations.get("operationScope"))
    if privacy:
        badges.append(f"Privacy: {privacy}")
    if source_action:
        badges.append(source_action)
    badges.append(f"{len(required)} required input{'s' if len(required) != 1 else ''}" if required else "Ready to use")
    return badges


def _source_action_badge(value: Any) -> str:
    clean = str(value or "").strip().lower().replace("-", "_")
    if clean in {"read", "metadata_read"}:
        return "Reads sources"
    if clean in {"write", "mutation", "mutating"}:
        return "Updates workspace"
    if clean in {"read_write", "write_read"}:
        return "Reads and updates workspace"
    return _readable_state(value)


def _section(title: str, nodes: list[JsonObject]) -> JsonObject:
    clean_nodes = [
        {"label": _clean_text(node.get("label")), "value": _clean_text(node.get("value"))}
        for node in nodes
        if _clean_text(node.get("label")) and _clean_text(node.get("value"))
    ]
    return {"title": title, "nodes": clean_nodes}


def _add_text_row(rows: list[JsonObject], label: str, value: Any) -> None:
    text = _clean_text(value)
    if text:
        rows.append({"label": label, "value": text})


def _add_list_row(rows: list[JsonObject], label: str, value: Any) -> None:
    items = [_clean_text(item) for item in _array(value)]
    items = [item for item in items if item]
    if items:
        rows.append({"label": label, "value": ", ".join(items)})


def _format_default(value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None:
        return "none"
    if isinstance(value, str):
        return _clean_text(value)
    return _clean_text(value)


def _readable_state(value: Any) -> str:
    clean = str(value or "").replace("_", " ").replace("-", " ").strip()
    return clean[:1].upper() + clean[1:] if clean else ""


def _field_label(operation: str, name: str) -> str:
    return FIELD_LABEL_OVERRIDES.get((operation, name)) or FIELD_LABELS.get(name) or _humanize(name)


def _humanize(value: str) -> str:
    clean = value.rsplit(".", 1)[-1].replace("_", " ").replace("-", " ").strip()
    return clean.title() if clean else ""


def _clean_text(value: Any) -> str:
    return portal_turns.prompt_safe_text(str(value or "")).strip()


def _object(value: Any) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _array(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
