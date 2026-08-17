# GenomiLab CTLA4 demo: Paperclip evidence ledger

These are the dated, pre-reviewed public-source evidence cards replayed in the
demo. The fixture was checked on `2026-08-15`. It is a curated Paperclip
replay, not a live provider call. Patient records, the synthetic recording-twin
genome, and Genomi's real local sequence verification remain separate evidence
streams. The ESM and Proto cards are precomputed illustrative demo fixtures,
not scientific evidence.

## Investigation 1

### 1. CTLA4 is an established disease gene

**Paperclip query:** `CTLA4 haploinsufficiency gene disease validity autoimmune cytopenia enteropathy`

**Source:** [ClinGen CTLA4 gene–disease validity](https://search.clinicalgenome.org/kb/gene-validity/CGGV%3Aassertion_e79675bd-3eef-4925-b4ef-3b7c48734f30-2025-06-04T210000.000Z)

**Fixture source date:** `2025-06-04`

**Show:**

> ClinGen classifies the CTLA4–disease relationship as **Definitive**, with
> autosomal-dominant inheritance and loss of function or haploinsufficiency as
> the established mechanism.

**Updates:** strengthens CTLA4 as a biologically credible candidate.

**Limit:** validates the gene–disease relationship, not Q76H.

### 2. The phenotype combination is documented

**Paperclip query:** `CTLA4 insufficiency hypogammaglobulinemia autoimmune cytopenia respiratory gastrointestinal 133`

**Source:** [Phenotype and penetrance in 133 CTLA4 variant carriers](https://pubmed.ncbi.nlm.nih.gov/29729943/)
— PMID `29729943`, PMCID `PMC6215742`

**Fixture source date:** `2018-05-04`

**Show:**

> A cohort included 133 CTLA4-variant carriers from 54 families. Ninety were
> affected. Among affected carriers with available data, 65/77 had
> hypogammaglobulinemia, 55/89 autoimmune cytopenia, 61/90 respiratory
> involvement, and 53/90 gastrointestinal involvement.

**Updates:** strengthens the possibility that the platelet, intestinal,
antibody, and respiratory findings share one explanation.

**Limit:** does not establish Q76H causality or an individual risk percentage.

### 3. Crohn-like disease has occurred with CTLA4 dysfunction

**Paperclip query:** `CTLA4 early-onset Crohn disease Y60C CD80 binding`

**Source:** [CTLA4 dysfunction in a family with Crohn-like disease](https://pubmed.ncbi.nlm.nih.gov/25367873/)
— PMID `25367873`, PMCID `PMC4512923`

**Fixture source date:** `2014-11-03`

**Show:**

> In one family, CTLA4 Y60C was associated with severe early-onset Crohn-like
> disease and systemic autoimmunity. The variant impaired dimerization and CD80
> binding.

**Updates:** makes a CTLA4-related explanation for a Crohn-like presentation
plausible enough to investigate.

**Limit:** this was one family with a different variant; its evidence cannot be
transferred to Q76H.

### 4. The exact Q76H allele remains uncertain

**Paperclip query:** `CTLA4 NM_005214.5 c.228G>C NP_005205.2 Gln76His rs2469719303`

**Source:** [ClinVar record for CTLA4 c.228G>C, p.Gln76His](https://www.ncbi.nlm.nih.gov/clinvar/variation/2443104/)

**Fixture source date:** `2022-05-23`

**Show:**

> The exact allele is `NM_005214.5:c.228G>C`,
> `NP_005205.2:p.Gln76His`, `rs2469719303`, at GRCh38
> `chr2:203870704 G>C`. ClinVar shows **Uncertain significance**, one
> submission, zero review stars, and no cited functional study.

**Updates:** creates a specific CTLA4 branch without turning the genome finding
into an answer.

**Limit:** the submission was last evaluated May 23, 2022 and lists the
condition as “not specified.” It is not a pathogenic classification.

### 5. The replay has no direct Q76H functional evidence

**Paperclip query:** `"rs2469719303" OR "NM_005214.5:c.228G>C" OR "CTLA4 Q76H" OR "CTLA4 Gln76His"`

**Grounded in:** [ClinVar record for Q76H](https://www.ncbi.nlm.nih.gov/clinvar/variation/2443104/),
fixture source date `2022-05-23`; and [functional characterization of 24 CTLA4 variants](https://pubmed.ncbi.nlm.nih.gov/37740092/),
fixture source date `2023-09-23`.

**Show:**

> The ClinVar record cites no functional study for Q76H, and Q76H was not among
> the 24 variants tested in the replayed functional series.

**Updates:** marks variant-level causality as unresolved.

**Limit:** no direct functional evidence in this replay scope does not prove
that no publication exists.

### 6. Medication remains a credible contributor

**Paperclip query:** `rituximab hypogammaglobulinemia pretreatment immunoglobulin autoimmune cohort`

**Source:** [Rituximab-associated hypogammaglobulinemia in autoimmune disease](https://pubmed.ncbi.nlm.nih.gov/25556904/)
— PMID `25556904`

**Fixture source date:** `2014-12-31`

**Show:**

> In a retrospective autoimmune-disease cohort, 26% of patients were already
> hypogammaglobulinemic when rituximab began and 56% were
> hypogammaglobulinemic during follow-up. Baseline IgG correlated with the later
> nadir.

**Updates:** keeps medication effects open and makes the pretreatment timeline
important.

**Limit:** whether abnormalities predated treatment comes from the patient's
records, not Paperclip.

## Investigation 2

### 7. Normal-looking abundance can coexist with impaired function

**Paperclip query:** `CTLA4 normal staining impaired function P137R CD80 uptake`

**Source:** [Normal-looking CTLA4 abundance with impaired ligand uptake](https://pubmed.ncbi.nlm.nih.gov/28159733/)
— PMID `28159733`, PMCID `PMC5438243`

**Fixture source date:** `2017-02-03`

**Show:**

> For CTLA4 P137R, total CTLA4 staining in memory regulatory T cells was
> similar to a healthy control, while soluble CD80-Ig uptake per CTLA4 molecule
> was substantially reduced.

**Updates:** weakens low protein abundance but keeps abnormal function open.

**Limit:** P137R is not Q76H, and this ligand-uptake assay is not identical to
every transendocytosis protocol.

### 8. Missense variants can test either abnormal or normal

**Paperclip query:** `CTLA4 variants transendocytosis functional assay 24 variants`

**Source:** [Functional characterization of 24 CTLA4 variants](https://pubmed.ncbi.nlm.nih.gov/37740092/)
— PMID `37740092`, PMCID `PMC10661720`

**Fixture source date:** `2023-09-23`

**Show:**

> In a published series of 24 CTLA4 variants, 17 showed impaired
> transendocytosis and seven tested within the healthy-donor range. Q76H was
> not tested.

**Updates:** justifies investigating function instead of predicting the answer
from “missense VUS.”

**Limit:** the assay cutoff is protocol-specific. An abnormal patient-cell
result would support pathway dysfunction, not prove Q76H caused it.

### 9. Transendocytosis measures a real CTLA4 function

**Paperclip query:** `CTLA4 trans-endocytosis CD80 CD86 mechanism`

**Source:** [CTLA4 transendocytosis of CD80 and CD86](https://pubmed.ncbi.nlm.nih.gov/21474713/)
— PMID `21474713`, PMCID `PMC3198051`

**Fixture source date:** `2011-04-07`

**Show:**

> CTLA4-expressing cells captured CD80 and CD86 from opposing cells, then
> internalized and degraded the ligands, reducing CD28 costimulation.

**Updates:** explains why the functional assay asks a different question from
antibody staining.

**Limit:** establishes the mechanism, not the effect of Q76H.

### 10. LRBA is a relevant alternative mechanism

**Paperclip query:** `LRBA CTLA4 expression turnover immune dysregulation`

**Source:** [LRBA protects CTLA4 from lysosomal degradation](https://pubmed.ncbi.nlm.nih.gov/26206937/)
— PMID `26206937`

**Fixture source date:** `2015-07-24`

**Show:**

> LRBA colocalizes with CTLA4 and protects it from lysosomal degradation. LRBA
> deficiency or knockdown increased CTLA4 turnover and reduced CTLA4 protein.

**Updates:** adds an alternative pathway mechanism.

**Limit:** normal LRBA expression is narrow counterevidence, not exclusion of
every LRBA or CTLA4-pathway mechanism.

## Investigation 3

### 11. Incomplete penetrance is documented

**Paperclip query:** `CTLA4 insufficiency incomplete penetrance unaffected carriers`

**Source:** [Phenotype and penetrance in 133 CTLA4 variant carriers](https://pubmed.ncbi.nlm.nih.gov/29729943/)

**Fixture source date:** `2018-05-04`

**Show:**

> Of 133 reported CTLA4-variant carriers, 43 were considered apparently
> unaffected. The observed affected fraction was 90/133, or 67.6%.

**Updates:** shows why an apparently healthy mother does not by itself disprove
a CTLA4-related hypothesis.

**Limit:** does not prove Q76H is disease-causing or give this family a personal
penetrance estimate.

## Keep the evidence streams separate

- **Paperclip:** curated replay of the dated public papers and database records
  listed above; no live provider call was made for the recording.
- **Genomi / Active Genome Index:** a real bounded local scan of the isolated
  synthetic recording-twin genome finds the heterozygous Q76H observation,
  its coordinates, and zygosity.
- **Genomi sequence verification:** a real local reference-sequence check
  verifies the requested reference and alternate substitution; it does not
  classify Q76H.
- **Patient records:** treatment chronology, infections, laboratory results,
  pathology, functional assay, and the mother's result.
- **ESM:** a precomputed illustrative demo fixture, clearly labeled
  nonclinical and not used as evidence; no ESM execution occurred.
- **Proto:** a precomputed illustrative demo fixture, clearly labeled
  nonclinical and not used as evidence; no Proto execution occurred.

## Do not claim

- Q76H is pathogenic.
- Paperclip found a functional study of Q76H.
- Normal CTLA4 staining rules out CTLA4 dysfunction.
- Reduced transendocytosis proves Q76H caused the condition.
- A healthy carrier proves Q76H is benign.
- A literature no-hit proves evidence does not exist.

## Public-evidence conclusion

> Public evidence strongly supports CTLA4 as a credible match for the combined
> phenotype and supports testing abundance separately from function. Public
> evidence does not establish Q76H as pathogenic. That unresolved contrast
> drives the next investigation.
