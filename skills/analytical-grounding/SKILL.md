---
name: analytical-grounding
version: 1.0.0
description: |
  Retrieve canonical pathway members, cell-type marker records, and genomic
  interval feature overlaps from declared analytical sources.
tools:
  - pathway.retrieve_members
  - cell_type.retrieve_markers
  - region.retrieve_features
mutating: false
---

# Analytical Grounding

Use this skill for source-declared records that ground an analytical statement,
without asking Genomi to choose the interpretation.

## Use When

- The input is a controlled pathway or gene-set name/id and the agent needs its
  canonical member genes.
- The input is a controlled cell type and the agent needs marker-gene records.
- The input is a genomic interval and the agent needs overlaps against declared
  GENCODE or ENCODE annotation files.

## Operations

- `pathway.retrieve_members`: retrieve Reactome, KEGG human pathway, or
  supplied or installed MSigDB Hallmark GMT member genes. Use a source for
  free-text pathway names unless the identifier prefix makes the source clear.
- `cell_type.retrieve_markers`: retrieve HPA single-cell marker
  records, installed CellMarker/PanglaoDB tables, or supplied marker tables.
- `region.retrieve_features`: retrieve interval overlaps from
  supplied or installed GENCODE GTF and/or ENCODE cCRE BED files for
  GRCh37/GRCh38. Supply `assembly`; without it the tool reports unsupported
  assembly instead of guessing a genome build.

## Boundaries

- These are retrieval verbs over declared source coverage.
- Do not use them as experimental protocol recommendations, workflow templates,
  or free-text biological interpretation.
- Treat `coverage_status` / `coverage_state` literally:
  - `data_returned`: declared source records were returned.
  - `in_scope_empty`: the input was in declared scope, and no records matched.
  - `out_of_scope_for_input`: the source, assembly, identifier, or required
    source file is outside declared coverage.
- Preserve source priors. A pathway member, marker gene, interval overlap, or
  druggable-target membership row is evidence context, not a selected answer.

## Examples

- `pathway.retrieve_members` with `{"pathway_id_or_name":"R-HSA-70635"}`
- `pathway.retrieve_members` with `{"pathway_id_or_name":"hsa00010"}`
- `cell_type.retrieve_markers` with `{"cell_type_id_or_name":"hepatocytes","source":"hpa"}`
- `cell_type.retrieve_markers` with `{"cell_type_id_or_name":"Hepatocyte","source":"cellmarker"}`
- `region.retrieve_features` with `{"region":"1:1000-1250","assembly":"GRCh38"}`

The installer can cache `gencode-grch38`, `gencode-grch37`,
`encode-ccre-grch38`, `panglaodb-markers`, and `cellmarker-human` under
`GENOMI_HOME`. MSigDB Hallmark requires a user-supplied official GMT export.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### cell_type.retrieve_markers

Retrieve canonical marker genes for a controlled cell-type source entity.

**Use when**: Returns source-declared marker genes for HPA single-cell records or supplied CellMarker, PanglaoDB, or ENCODE marker tables.

**Why necessary**: Cell-type identity questions need marker records, not disease genetics or GWAS evidence.

**Result semantics**: Returns marker records only; it does not annotate clusters, assign cell identities, rank cell types, or interpret cell states. Free-text cluster IDs and hypothetical cell-state labels are out of scope.

### pathway.retrieve_members

Retrieve canonical member genes for a controlled pathway or gene-set source entity.

**Use when**: Returns source-declared member genes for Reactome pathways, KEGG human pathways, or supplied MSigDB Hallmark GMT gene sets.

**Why necessary**: Pathway membership is a grounding fact and should be retrieved separately from disease or variant claims.

**Result semantics**: Returns pathway membership records only; it does not infer pathway activity, choose genes, or summarize pathway biology. Free-text pathway names should include source unless the identifier prefix implies a declared source.

### region.retrieve_features

Retrieve genomic-region feature annotations from supplied or installed GENCODE and ENCODE annotation files.

**Use when**: The user or an upstream tool supplies a genomic interval and the agent needs transcript or regulatory-feature overlaps for an explicit GRCh37 or GRCh38 assembly.

**Why necessary**: Genomic coordinates need gene and regulatory feature context before they can be biologically discussed.

**Result semantics**: Returns source-declared interval overlaps for the assembly shown in query. Empty results mean no overlap in declared files, not biological absence outside declared coverage.
