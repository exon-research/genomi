# GenomiLab demo script: Could these health problems be connected?

*Simulated demonstration: the patient, follow-up results, and specialist
investigation are scripted. The recording uses an isolated one-variant
synthetic twin as the visible stand-in for a separately prevalidated full
private Active Genome Index; the twin is not a whole genome. Paperclip evidence
is a curated replay, ESM and Proto outputs are illustrative precomputed demo
results, and the Genomi sequence verification is a real local operation. This
is research support, not a diagnosis.*

The public evidence used in the investigation is listed in
[GENOMILAB_CTLA4_PAPERCLIP_EVIDENCE_LEDGER.md](./GENOMILAB_CTLA4_PAPERCLIP_EVIDENCE_LEDGER.md).

## 1. The patient asks a simple question

**Patient**

> “I have Crohn’s, and I keep getting sinus and chest infections. My doctor
> thinks the infections might be from my medication, but I also had very low
> platelets when I was a teenager. Could any of this be connected?”

**GenomiLab**

> “I’ll compare the history you have shared with your selected genome profile,
> investigate several possible explanations, and show you which evidence would
> change them.”

The workspace begins with four facts: Crohn’s disease, recurrent sinus and
chest infections, severe thrombocytopenia during adolescence, and a possible
medication contribution.

## 2. GenomiLab forms the first hypotheses

The Main Investigator creates four provisional hypotheses:

1. Medication-related immune suppression is causing the infections.
2. One immune-dysregulation condition connects the platelet, intestinal, and
   infection history.
3. A primary antibody-deficiency disorder explains the infections and some of
   the immune findings.
4. Several unrelated conditions only appear to be connected.

It forms a three-member panel from the full specialist board:

- a **clinical timeline specialist** aligns infections and immune findings with
  treatment dates;
- an **immune-genetics specialist** builds a phenotype-led candidate set; and
- a **literature and evidence-skeptic specialist** tests the candidates against
  public evidence, alternatives, conflicts, and gaps.

The immune-genetics specialist proposes **CTLA4, LRBA, PIK3CD, NFKB1, and
TNFRSF13B**. The Main Investigator sends that bounded five-gene query to
Genomi; specialists never receive genome rows directly. It also supplies
focused questions to the Paperclip evidence workstream.

## 3. Round 1: a genome lead, not an answer

The three specialist reports converge on five findings:

- Medication could contribute, but timing is still missing.
- The teenage platelet event may have been immune thrombocytopenia, but the
  original record is needed.
- Immune cytopenia, intestinal inflammation, antibody deficiency, and
  respiratory infections can occur together in immune-dysregulation
  disorders.
- The bounded Active Genome Index search finds one heterozygous **CTLA4
  p.Gln76His (Q76H)** call: `rs2469719303`, GRCh38 `2:203870704 G>C`, genotype
  `0/1`.
- The reviewed public evidence makes CTLA4 a credible phenotype match, but the
  exact Q76H variant remains a variant of uncertain significance and lacks
  direct published functional evidence in the searched sources.

The hypothesis board adds **CTLA4-related immune dysregulation** while keeping
medication effects, CTLA4-independent antibody deficiency, and unrelated or
multiple causes open.

**GenomiLab**

> “CTLA4 is worth investigating, but this variant is not an answer. The most
> useful next evidence is whether the infections and immune abnormalities began
> before treatment.”

The panel asks for the infection and medication timeline, pretreatment
immunoglobulins, current immunoglobulins, vaccine responses, B-cell subsets,
and review of the older intestinal pathology.

## 4. The patient returns with the evidence Round 1 requested

Several weeks later, the patient adds clinician-ordered results and older
records.

**Patient**

> “I found a pneumonia record from before my first biologic and an old blood
> test showing my antibody levels were already low before rituximab. My new
> tests are still low, and my doctor says the old bowel biopsy may not look like
> typical Crohn’s.”

The new record set shows pneumonia before the first biologic, low
immunoglobulins before rituximab, persistently low IgG and IgA, an inadequate
pneumococcal antibody response, abnormal B-cell maturation, and pathology that
raises immune-mediated enteropathy as a possibility.

The board changes immediately:

- **Medication-only explanation: rejected.** Treatment can still contribute,
  but key abnormalities came first.
- **CTLA4-related immune dysregulation: strengthened.**
- **CTLA4-independent antibody deficiency: strengthened as an alternative.**
- **Several unrelated conditions: weakened.**
- **Another immune or genetic cause: remains open.**

## 5. Round 2: separate protein abundance from function

The Main Investigator narrows the panel question:

> “If CTLA4 is involved, is there too little CTLA4 protein, or could the protein
> be present but function abnormally?”

The reviewed evidence shows that CTLA4 abundance and function are different
measurements. Published variants have impaired ligand uptake despite
normal-looking total CTLA4 staining. One 24-variant study reported impaired
transendocytosis for 17 variants and normal-range results for seven; Q76H was
not tested.

The panel asks for clinical confirmation of Q76H, CTLA4 staining, and LRBA
expression. The patient returns with all three.

**Patient**

> “The clinical lab confirmed Q76H, but it is still classified as uncertain.
> CTLA4 staining and LRBA expression were both in the lab’s control range. Does
> that rule CTLA4 out?”

The board updates again:

- **Reduced CTLA4 abundance: weakened.**
- **An LRBA-expression defect: less supported.**
- **Impaired CTLA4 function despite normal staining: now the key unresolved
  mechanism.**
- **CTLA4-independent antibody deficiency and other causes: remain open.**

**GenomiLab**

> “Normal staining means CTLA4 abundance was in the control range under that
> protocol. It does not show whether the protein performs its ligand-removal
> function normally.”

The panel asks for a qualified functional assay with independent repeats and
targeted family testing.

## 6. The patient returns with the final requested tests

**Patient**

> “The reference laboratory repeated the functional assay and reported reduced
> CTLA4 activity both times. My mother has the same variant but seems healthy.
> Does one result prove it and the other disprove it?”

## 7. Round 3: integrate mechanism and conflicting evidence

The specialists compare the two reduced transendocytosis results, the normal
abundance measurements, the unchanged VUS classification, and the apparently
healthy carrier with the prior record:

- Repeatedly reduced transendocytosis supports CTLA4-pathway dysfunction under
  the reported assay conditions.
- An apparently healthy carrier argues against a simple, fully penetrant
  variant-to-disease explanation.
- Published CTLA4 cohorts include apparently unaffected carriers, making
  variable penetrance or modifiers plausible.
- Neither observation proves that Q76H caused the patient’s condition.
- Q76H remains a variant of uncertain significance.

The research-artifact panel adds three bounded views without changing the
clinical evidence board:

- **Genomi** verifies the Q76H substitution against the public reference
  protein in a real local sequence operation.
- The **ESM illustrative result** shows how a reference-versus-Q76H sequence
  perturbation would be reviewed as a nonclinical research signal.
- The **Proto illustrative result** lays out a blinded experiment comparing
  wild-type CTLA4, Q76H, and controls while measuring abundance and ligand
  removal separately.

The final board lands on a bounded differential:

1. **CTLA4-pathway immune dysregulation — leading unifying research
   hypothesis.**
2. **Impaired CTLA4 function despite normal staining — strengthened.**
3. **Primary antibody deficiency with another cause — retained.**
4. **Medication effects — retained as a contributor, not a complete
   explanation.**
5. **Other immune or genetic causes — still open.**

## 8. GenomiLab prepares the doctor brief

GenomiLab creates **brief version 1**, preserving the chronology, source links,
Q76H’s uncertain classification, supporting and conflicting evidence, and the
remaining alternatives.

The brief asks the clinician:

1. How should the Q76H uncertain classification be interpreted in light of two
   reduced transendocytosis repeats and the reported maternal result?
2. What assay method, controls, reference range, and repeatability evidence
   support the reported reduction in CTLA4 transendocytosis?
3. What do CTLA4 staining within the laboratory control range and LRBA
   expression within the laboratory control range narrow or leave unresolved
   about pathway function?
4. What evidence would help distinguish CTLA4-pathway dysfunction from other
   immune or genetic mechanisms behind recurrent infections and antibody
   deficiency?

The patient can select **Print / Save PDF** or **Download doctor brief (.html)**
and take the report to an immunologist or clinical geneticist.
