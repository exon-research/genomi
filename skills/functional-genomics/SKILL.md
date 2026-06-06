---
name: functional-genomics
description: |
  Candidate gene evidence from perturbation, dependency, resistance,
  sensitivity, viability, or assay-context records.
tools:
  - functional_genomics.retrieve_perturbation_records
  - functional_genomics.query_geo
  - functional_genomics.import_perturbation_table
  - functional_genomics.compare_gene_perturbation
  - research.list_sources
  - research.record
mutating: true
---

# Functional Genomics Perturbation Evidence

Retrieve functional-genomics perturbation evidence for a declared experimental
context plus candidate genes. Screens are one supported perturbation experiment
subtype, not the capability name.

## Contract

Perturbation evidence comes from native public retrieval, user-provided local
tables, reviewed stored research, or explicitly supplied source records. Generic
gene biology can explain a result, but it should not outrank direct
perturbation-source evidence.

Direct support is source-verified perturbation evidence. Source records carry
verified fields or support spans for the requested cell line, perturbation,
assay/readout, and candidate gene relationship; broader biology remains
adjacent or plausibility-only evidence.

Native coverage currently includes BioGRID ORCS when a BioGRID ORCS access key
is available, DepMap CRISPR gene-effect release tables when a CSV URL or path
is configured, and bounded NCBI GEO metadata/table discovery. GEO's advantage is
source discovery for public or published perturbation datasets: SeriesMatrix
files, supplementary tables, and accession-indexed study records that curated
screen APIs may not expose for the requested cell line, perturbation, assay, or
readout. If native sources cannot be queried, the response makes that coverage
state visible rather than weak ranking evidence.

## Tool Flow

1. Extract candidate gene symbols and the requested context: organism, cell
   line, perturbation, assay, phenotype, resistance, sensitivity, viability, or
   readout.
2. Call `functional_genomics.compare_gene_perturbation` for the normal flow. It
   retrieves native public perturbation records when configured, verifies source
   records, and returns candidate evidence rows.
3. Call `functional_genomics.retrieve_perturbation_records` only for explicit
   native-source inspection, coverage debugging, or source availability review.
4. Call `functional_genomics.query_geo` when the advantage is public source
   discovery: the question mentions a published/public screen dataset, study
   accession, supplementary table, SeriesMatrix-style file, or compare has
   insufficient BioGRID/DepMap/stored evidence for a requested perturbation
   context that likely came from a public study. The user does not need to name
   GEO. GEO metadata alone is not direct evidence; direct support still requires
   table-derived, source-verified candidate gene and perturbation-context fields.
5. If the source is a local CSV/TSV result table, call
   `functional_genomics.import_perturbation_table` first.
6. Pass supplied, imported, or retrieved source records to
   `functional_genomics.compare_gene_perturbation`; it verifies source records
   before comparing candidate genes.
7. Use verified perturbation-source evidence when the user asks for only the gene
   symbol. Audit `decision_evidence` before explaining the result.

`functional_genomics.compare_gene_perturbation` returns evidence rather than a universal
answer. If source records do not support an identifier-only answer, do not invent
a gene; state the source gap or gather better source records.

## Source Record Shape

`functional_genomics.compare_gene_perturbation` accepts reviewed source records. Prefer records that
include the source title or URL, named genes, the source-backed finding, source
type, and any verified perturbation context such as cell line, perturbation, assay,
phenotype, readout, PMID, or DOI.

When a paper or dataset directly supports the requested perturbation context, include
the specific source-backed spans that verify the cell line, perturbation,
assay/readout, and gene relationship. Generic pathway or co-mention literature
should remain adjacent evidence.

Direct perturbation-source context outranks generic literature or
pathway plausibility only when source-backed fields verify the context. If no
source records are supplied, or if records are generic literature without
context verification, the tool cannot fairly make a high-support ranking.

## Cross-Capability Synthesis

A scope-limited result from this capability is not a final user-facing answer
when other Genomi capabilities can contribute orthogonal evidence to the same
question. Returning "cannot answer" while applicable capabilities remain
unexamined is a host-agent failure mode.

## Tools

### functional_genomics.compare_gene_perturbation

Compare candidate genes by verified functional-genomics perturbation experiment evidence.

**Use when**: Retrieves native public perturbation experiment records when configured, verifies source records, and returns candidate-gene evidence rows for the declared perturbation context.

**Why necessary**: Screen and dependency questions need verified perturbation evidence, not inherited-variant or disease association evidence.

**Example prompts**: Which candidate gene is best supported by this CRISPR resistance screen?

**Result semantics**: Runs source-record verification before candidate comparison; generic literature stays separate from direct perturbation experiment evidence.

### functional_genomics.import_perturbation_table

Extract verified perturbation experiment source records from a local CSV or TSV result table.

**Use when**: The agent has a local CSV/TSV perturbation, dependency, viability, resistance, or supplementary result table and needs source records before candidate comparison.

**Why necessary**: User-supplied screen tables need structured extraction before they can support gene comparisons.

**Result semantics**: Extracts table rows into source records and verifies row-level genes plus perturbation context; it does not select the answer gene.

### functional_genomics.query_geo

Query NCBI GEO metadata and bounded public study tables for functional-genomics perturbation source records.

**Use when**: The advantage is public dataset discovery: a published/public screen, study accession, supplementary table, SeriesMatrix-style file, or an under-covered perturbation context where curated sources did not provide direct source records.

**Why necessary**: GEO can find source-backed tables for study-specific cell lines, perturbations, assays, and readouts that BioGRID ORCS, DepMap, or stored reviewed records may not cover; it keeps metadata-only hits separate from direct perturbation evidence.

**Result semantics**: Returns GEO metadata hits, download candidates with skip reasons, and verified source records when candidate genes are supplied. Metadata-only matches never count as direct evidence; direct support requires source-verified gene plus requested perturbation context fields.

### functional_genomics.retrieve_perturbation_records

Retrieve native public functional-genomics perturbation records from BioGRID ORCS and DepMap for candidate genes and declared experimental context.

**Use when**: Explicit native-source inspection, source availability review, or coverage debugging for BioGRID ORCS and configured DepMap perturbation records.

**Why necessary**: Raw native-source retrieval lets agents inspect what BioGRID ORCS or DepMap returned, or why a native source was unavailable, without running candidate comparison.

**Result semantics**: Returns native functional-genomics source records from BioGRID ORCS and configured DepMap release tables; it does not select the final gene. For normal candidate-gene comparison, use functional_genomics.compare_gene_perturbation directly because it can retrieve native records when configured. BioGRID ORCS requires an access key; DepMap requires a configured public CRISPR gene-effect CSV URL or path.
